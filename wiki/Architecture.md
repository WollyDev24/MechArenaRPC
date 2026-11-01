# Architecture

This page describes the runtime structure of `RPCA.py`, the flow of data from the game to Discord, and the trade-offs behind the design.

---

## Component overview

```
┌──────────────────────────────────────────────────────────────────┐
│                            RPCA.py                                │
│                                                                   │
│  ┌─────────────────────┐        ┌──────────────────────────────┐  │
│  │   Main thread        │        │   Worker thread (daemon)     │  │
│  │                      │        │                              │  │
│  │  pystray event loop  │        │  while is_running:           │  │
│  │  ├─ tray icon        │        │    get_mech_state()          │  │
│  │  ├─ status menu item │◄───────┤    maybe detect_hud_mode()   │  │
│  │  ├─ Reload/Open cfg  │ status │    rpc.update() / clear()    │  │
│  │  ├─ Calibrate HUD    │        │    sleep(poll_interval)      │  │
│  │  ├─ Show Log         │        │                              │  │
│  │  ├─ Dispatch         │        │                              │  │
│  │  └─ Quit             │        │                              │  │
│  └─────────────────────┘        └──────────────┬───────────────┘  │
│                                                 │                  │
└─────────────────────────────────────────────────┼──────────────────┘
                                                  │
              ┌───────────────────────────────────┼──────────────────────┐
              │                                   │                      │
              ▼                                   ▼                      ▼
     ┌─────────────────┐              ┌──────────────────┐     ┌─────────────────┐
     │ Linux / Wine     │              │ ImageMagick      │     │ Discord client  │
     │ psutil process   │              │ import + xwininfo│     │ IPC socket      │
     │ + UDP sockets    │              │ HUD screenshot   │     │ (pypresence)    │
     └─────────────────┘              └──────────────────┘     └─────────────────┘

     ┌───────────────────────────────────────────────────────────────┐
     │ settings.py: Config defaults, validation, TOML, CLI overrides │
     └───────────────────────────────────────────────────────────────┘
```

---

## Process model

### Main thread: tray event loop

`main()` builds a `pystray.Menu`, creates a `pystray.Icon`, starts the worker thread, and calls `tray_icon.run()`.

The tray loop must own the main thread. Some AppIndicator/GTK backends require it, and blocking it with polling would freeze the menu. This is why all game logic lives in a separate thread.

### Worker thread: game and presence loop

`rpc_worker()` is started with `daemon=True`, so it does not keep the process alive if the tray exits. It owns:

- the current `Presence` connection,
- the last observed game state,
- the session timer,
- the battle timer,
- the locked mode,
- the results-window deadline.

The only shared state with the UI thread is:

| Global | Protected by | Purpose |
| --- | --- | --- |
| `current_ui_status` | `state_lock` | Text shown in the tray status item and tooltip. |
| `is_running` | (plain flag) | Tells the worker to stop. |
| `tray_icon` | (plain reference) | Used by `set_status()` to update title and menu. |

`set_status()` takes `state_lock` when writing the text, then updates `tray_icon.title` and calls `update_menu()` outside the lock. The menu callback `get_menu_status_text()` reads the text under the same lock.

This is a deliberately small amount of shared state. No queues and no condition variables are needed.

---

## Startup sequence

`RPCA.py` executes a few things **before** importing the heavy modules:

1. **Ignore `SIGHUP`** so a closed terminal does not kill the process.
2. **Detect `--detached`** in `sys.argv`, plus `--print-config` / `--calibrate` (`cli_mode`).
3. If detached, open `/dev/null` and replace stdin/stdout/stderr file descriptors with it.
4. Set `PYSTRAY_BACKEND=appindicator` so pystray chooses the AppIndicator backend.
5. Import the rest (`psutil`, PIL, pystray, pypresence, `settings`).
6. Load the config, then copy every value into module globals through `apply_config()`.
7. Define functions and globals.
8. In `main()`, handle `--print-config` / `--calibrate` and exit, or build the tray, start the worker, and enter the tray loop.

The ordering matters. In particular, `PYSTRAY_BACKEND` must be set before `import pystray`, and the stdio redirection must happen before any library writes output.

### Configuration flow

```
defaults (settings.Config)
        │
        ├── config.toml (created on first launch)
        │        │
        │        └── validation warnings for bad/unknown keys
        │
        ├── CLI overrides (--crop, --retries, ...)
        │
        ▼
   Config object ──► apply_config() ──► module globals (CLIENT_ID, HUD_CROP_GEOM, ...)
        │
        └── works at runtime: it formats presence payloads and drives the capture
```

`reload_config()` reruns the same load pipeline and calls `apply_config()` again, so **Reload Config** takes effect on the next worker poll. **Restart / Apply Update** and **Dispatch** carry config-related CLI flags forward via `persistent_cli_args()`.

`--print-config` runs the same load and prints the merged result without opening the tray. `--calibrate` runs the interactive wizard instead of the daemon.

### Detached environment

| Aspect | Foreground | `--detached` |
| --- | --- | --- |
| stdin/stdout/stderr | Terminal | `/dev/null` |
| `is_detached` | `False` | `True` |
| Console logging | Yes (unless `cli_mode`) | No |
| File logging | Yes | Yes |
| Tray menu "Dispatch" | Enabled | Disabled |
| Parent session | Current shell | New session via `start_new_session=True` |

`log()` checks `is_detached` and `cli_mode` before printing. File logging always happens, with a timestamp and a maximum of one line per call.

---

## Data flow

### 1. Game state

```
MechArena.exe process exists?
├─ no  ─────────────────────────────► STATE_CLOSED
└─ yes
   └─ has at least one UDP socket?
      ├─ yes ────────────────────────► STATE_BATTLE
      └─ no  ────────────────────────► STATE_MENU
```

Implemented by `get_mech_state()`. See [Game State Detection](Game-State-Detection.md).

### 2. HUD mode (battle only)

```
state == BATTLE and (now - battle_start) >= mode_lock_delay and locked_mode is None
   │
   ├─ attempt 1 ──► detect_hud_mode()
   │     ├─ xwininfo finds window.title ──► window id
   │     ├─ import -window <id> -crop hud.crop png:-
   │     ├─ PIL converts to grayscale
   │     ├─ compute left/right edge averages and centre average
   │     ├─ ratio = centre / max(edge, 1.0)
   │     ├─ if brightness < min_brightness ──► None (failed capture)
   │     └─ classify_hud() ──► "Deathmatch" | "Control Point Clash" | "Free-For-All" | "In Battle"
   ├─ failure and attempts left ──► sleep lookup_retry_delay, try again (up to lookup_retries)
   └─ all attempts failed ──► leave locked_mode None, retry on the next poll
```

Implemented by `get_mech_window_id()`, `capture_hud_image()`, `analyze_hud_image()`, `classify_hud()`, `detect_hud_mode()`, and `detect_hud_mode_with_retry()`. See [Mode Detection](Mode-Detection.md).

### 3. Presence lifecycle

The worker is a hand-written state machine driven by `(state, last_state, timers)`. It calls `rpc.update()` only on meaningful transitions, not on every poll. See [Discord Presence](Discord-Presence.md).

---

## Why this design?

### Why process + UDP instead of window title or CPU usage?

- Window titles are unreliable under Wine and may stay constant across menu and battle.
- CPU usage is noisy and hardware-dependent.
- Wine games open UDP sockets when they join a match; in the hangar they typically do not.
- The check is cheap, cross-distro, and does not require elevated privileges.

The cost is that **any** UDP socket counts as a battle in the production scripts. This is documented as a known limitation.

### Why a HUD screenshot instead of memory scanning?

- Reading `/proc/<pid>/mem` needs matching user permissions or relaxed `ptrace` settings, and can be brittle across updates.
- Memory scanning can conflict with anti-cheat and terms of service.
- OCR was tested (`DetectMode.py`) but stylised fonts, anti-aliasing, and motion made it unreliable.
- Network sniffing requires raw sockets and root, and the useful metadata is not guaranteed to be plaintext.
- A single grayscale screenshot is non-invasive, fast, and good enough for three coarse classes.

### Why lock the mode after one successful read?

During a match the HUD changes constantly: scores update, kill feeds appear, beacons flip, and players die. Re-running the heuristics would make the Discord presence flicker between modes. The 15-second delay lets the intro and loading finish; one read then locks the label for the match.

### Why a separate `MechArena.py`?

It is a minimal reproduction of the core idea: process detection plus presence updates, with no tray, screenshots, or external window tools. It is useful for testing Discord connectivity and for users who do not want a tray icon.

---

## Polling cadence and cost

| Loop | Interval | Work |
| --- | --- | --- |
| `RPCA.py` worker | `timing.poll_interval` (2 s) | `psutil.process_iter` + one `net_connections` call per matching process. One screenshot only after the `mode_lock_delay` battle gate. |
| `MechArena.py` worker | 3 s | Same process/UDP check, no screenshot. |
| `TestingTools/RPCdaemon.py` | 2 s | Process/UDP check plus optional screenshot on every battle poll. |

The production loop is intentionally cheap: no image work happens while in the menu, and after the mode locks no further captures happen for that match. A failed lookup can take up to `lookup_retries + 1` captures (four by default).

---

## Error strategy

- `psutil.NoSuchProcess` and `psutil.AccessDenied` are ignored; iteration continues.
- `Presence.connect()` failures set `rpc = None`, and the next poll retries.
- `rpc.update()` calls are **not** individually wrapped. A broken connection can raise and terminate the worker; this is a known robustness gap. In practice Discord IPC failures usually happen at connect time.
- Screenshot failures return `None`, so `detect_hud_mode_with_retry()` makes up to `lookup_retries` more attempts (`lookup_retry_delay` apart). If all fail, the mode stays unlocked and the next poll starts another burst.
- Invalid config values are reported to the log and replaced with defaults; a missing/unreadable config falls back to the built-in defaults. The daemon never refuses to start because of config.
- `rpc.clear()` / `rpc.close()` on shutdown are wrapped in `try/except`.
- Logging failures are swallowed; the daemon never crashes because `~/.cache` is unavailable.

The broad `except Exception` style favours uptime over diagnostics. The log file is the primary debugging surface.

---

## Extension points

| Goal | Where to change |
| --- | --- |
| Different Discord application or asset | `[discord] client_id`, `large_image`, `large_text` in the config file (or `MechArena.py`). |
| Different resolution / UI scale | `[hud] crop`, or run the calibration wizard. |
| Different timing | `[hud] mode_lock_delay`, `[timing] results_display_duration`, `[timing] poll_interval`. |
| Add a mode | Extend `classify_hud()`, `settings.Config`, `[hud.thresholds]`, and the branch that formats `details`. |
| Change tray menu | `main()` in `RPCA.py`. |
| Add a setting | `settings.Config`, `from_mapping()`, `dump_config()`, `apply_cli_overrides()`, then `apply_config()`. |
| Replace the tray with another UI | Keep `rpc_worker()` and `get_mech_state()`, replace `main()`. |

See [Configuration](Configuration.md) for concrete examples.

---

## Related pages

- [Game State Detection](Game-State-Detection.md)
- [Mode Detection](Mode-Detection.md)
- [Discord Presence](Discord-Presence.md)
- [Tray and Daemon](Tray-and-Daemon.md)
