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
│  │  ├─ Show Log         │ status │    rpc.update() / clear()    │  │
│  │  ├─ Dispatch         │        │    sleep(2)                  │  │
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
2. **Detect `--detached`** in `sys.argv`.
3. If detached, open `/dev/null` and replace stdin/stdout/stderr file descriptors with it.
4. Set `PYSTRAY_BACKEND=appindicator` so pystray chooses the AppIndicator backend.
5. Import the rest (`psutil`, PIL, pystray, pypresence).
6. Define functions and globals.
7. In `main()`, build the tray, start the worker, and enter the tray loop.

The ordering matters. In particular, `PYSTRAY_BACKEND` must be set before `import pystray`, and the stdio redirection must happen before any library writes output.

### Detached environment

| Aspect | Foreground | `--detached` |
| --- | --- | --- |
| stdin/stdout/stderr | Terminal | `/dev/null` |
| `is_detached` | `False` | `True` |
| Console logging | Yes | No |
| File logging | Yes | Yes |
| Tray menu "Dispatch" | Enabled | Disabled |
| Parent session | Current shell | New session via `start_new_session=True` |

`log()` checks `is_detached` before printing. File logging always happens, with a timestamp and a maximum of one line per call.

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
state == BATTLE and (now - battle_start) >= 15 and locked_mode is None
   │
   ├─ attempt 1 ──► detect_hud_mode()
   │     ├─ xwininfo finds "Mech Arena" ──► window id
   │     ├─ import -window <id> -crop 440x45+740+50 png:-
   │     ├─ PIL converts to grayscale
   │     ├─ compute left/right edge averages and centre average
   │     ├─ ratio = centre / max(edge, 1.0)
   │     └─ classify ──► "Deathmatch" | "Control Point Clash" | "Free-For-All" | "In Battle"
   ├─ failure and attempts left ──► sleep 2 s, try again (up to 3 retries)
   └─ all attempts failed ──► leave locked_mode None, retry on the next poll
```

Implemented by `get_mech_window_id()`, `detect_hud_mode()`, and `detect_hud_mode_with_retry()`. See [Mode Detection](Mode-Detection.md).

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
| `RPCA.py` worker | 2 s | `psutil.process_iter` + one `net_connections` call per matching process. One screenshot only after the 15 s battle gate. |
| `MechArena.py` worker | 3 s | Same process/UDP check, no screenshot. |
| `TestingTools/RPCdaemon.py` | 2 s | Process/UDP check plus optional screenshot on every battle poll. |

The production loop is intentionally cheap: no image work happens while in the menu, and after the mode locks no further captures happen for that match. A failed lookup can take up to 4 captures (the first attempt plus 3 retries).

---

## Error strategy

- `psutil.NoSuchProcess` and `psutil.AccessDenied` are ignored; iteration continues.
- `Presence.connect()` failures set `rpc = None`, and the next poll retries.
- `rpc.update()` calls are **not** individually wrapped. A broken connection can raise and terminate the worker; this is a known robustness gap. In practice Discord IPC failures usually happen at connect time.
- Screenshot failures return `None`, so `detect_hud_mode_with_retry()` makes up to 3 more attempts (2 s apart). If all fail, the mode stays unlocked and the next poll starts another burst.
- `rpc.clear()` / `rpc.close()` on shutdown are wrapped in `try/except`.
- Logging failures are swallowed; the daemon never crashes because `~/.cache` is unavailable.

The broad `except Exception` style favours uptime over diagnostics. The log file is the primary debugging surface.

---

## Extension points

| Goal | Where to change |
| --- | --- |
| Different Discord application or asset | `CLIENT_ID`, `large_image`, `large_text` in `RPCA.py` / `MechArena.py`. |
| Different resolution / UI scale | `HUD_CROP_GEOM`; recalibrate with `TestingTools/DumpStrip.py`. |
| Different timing | `MODE_LOCK_DELAY`, `RESULTS_DISPLAY_DURATION`, `time.sleep(...)`. |
| Add a mode | Extend `detect_hud_mode()` and the branch that formats `details`. |
| Change tray menu | `main()` in `RPCA.py`. |
| Replace the tray with another UI | Keep `rpc_worker()` and `get_mech_state()`, replace `main()`. |

See [Configuration](Configuration.md) for concrete examples.

---

## Related pages

- [Game State Detection](Game-State-Detection.md)
- [Mode Detection](Mode-Detection.md)
- [Discord Presence](Discord-Presence.md)
- [Tray and Daemon](Tray-and-Daemon.md)
