# Configuration

Runtime configuration lives in a TOML file. Defaults are built into `settings.py`, and a commented config is created on first launch:

```text
~/.config/mech-arena-rpc/config.toml
```

If `XDG_CONFIG_HOME` is set, the path is `$XDG_CONFIG_HOME/mech-arena-rpc/config.toml`. Override it with `--config PATH`.

`MechArena.py` is unchanged: it still has its own hardcoded constants and does not read this file.

---

## Precedence

1. **Command-line overrides** such as `--crop` or `--retries`.
2. **The config file**.
3. **Built-in defaults** in `settings.py`.

The daemon logs the effective config path at startup. Use `RPCA.py --print-config` to print the merged result without starting the tray.

---

## Config file

The generated file contains every supported key:

```toml
[discord]
client_id = "1565766221813776505"
large_image = "mech_arena_logo"
large_text = "Mech Arena"

[[discord.buttons]]
label = "Download Mech Arena"
url = "https://plarium.com/en/game/mech-arena/"

[hud]
crop = "440x45+740+50"
mode_lock_delay = 15
lookup_retries = 3
lookup_retry_delay = 2
capture_timeout = 1.5
edge_fraction = 0.15
center_start_fraction = 0.35
center_end_fraction = 0.65

[hud.thresholds]
center_min_cpc = 95
center_max_ffa = 95
ratio_max_deathmatch = 0.88
edge_min_deathmatch = 150
ratio_min_cpc = 1.20
min_brightness = 5

[timing]
results_display_duration = 10
poll_interval = 2

[logging]
file = "~/.cache/mech_arena_rpc.log"

[window]
title = "Mech Arena"

[process]
name = "mecharena.exe"
```

### Reference

| Key | Default | Effect |
| --- | --- | --- |
| `discord.client_id` | `1565766221813776505` | Discord application identity. |
| `discord.large_image` | `mech_arena_logo` | Rich Presence asset key. |
| `discord.large_text` | `Mech Arena` | Tooltip for the large image. |
| `discord.buttons` | one download button | Up to two `{ label, url }` tables. Use `buttons = []` for none. |
| `hud.crop` | `440x45+740+50` | ImageMagick crop geometry (`WxH+X+Y`). |
| `hud.mode_lock_delay` | `15` | Seconds after battle start before the HUD is read. |
| `hud.lookup_retries` | `3` | Retries after the first failed HUD lookup. |
| `hud.lookup_retry_delay` | `2` | Seconds between HUD lookup attempts. |
| `hud.capture_timeout` | `1.5` | Timeout for the ImageMagick capture. |
| `hud.edge_fraction` | `0.15` | Fraction of the crop width sampled on each edge. |
| `hud.center_start_fraction` | `0.35` | Start of the centre sample. |
| `hud.center_end_fraction` | `0.65` | End of the centre sample. |
| `hud.thresholds.center_min_cpc` | `95` | Minimum centre brightness for CPC. |
| `hud.thresholds.center_max_ffa` | `95` | Maximum centre brightness for FFA. |
| `hud.thresholds.ratio_max_deathmatch` | `0.88` | Centre/edge ratio at or below which a frame is Deathmatch. |
| `hud.thresholds.edge_min_deathmatch` | `150` | Edge brightness at or above which a frame is Deathmatch. |
| `hud.thresholds.ratio_min_cpc` | `1.20` | Minimum centre/edge ratio for CPC. |
| `hud.thresholds.min_brightness` | `5` | Frames dimmer than this are treated as failed captures. Set `0` to disable. |
| `timing.results_display_duration` | `10` | Seconds to show "Viewing Results". |
| `timing.poll_interval` | `2` | Seconds between game-state checks. |
| `logging.file` | `~/.cache/mech_arena_rpc.log` | Log destination. |
| `window.title` | `Mech Arena` | X11 window title to match. |
| `process.name` | `mecharena.exe` | Process name substring to match. |

Unknown keys and invalid values produce a warning in the log. Invalid fields fall back to their defaults; the daemon keeps running.

---

## CLI overrides

| Flag | Equivalent config key |
| --- | --- |
| `--config PATH` | Select a different config file. |
| `--client-id ID` | `discord.client_id` |
| `--crop WxH+X+Y` | `hud.crop` |
| `--log-file PATH` | `logging.file` |
| `--window-title TITLE` | `window.title` |
| `--process-name NAME` | `process.name` |
| `--mode-delay SECONDS` | `hud.mode_lock_delay` |
| `--retries N` | `hud.lookup_retries` |
| `--retry-delay SECONDS` | `hud.lookup_retry_delay` |
| `--poll SECONDS` | `timing.poll_interval` |
| `--results-duration SECONDS` | `timing.results_display_duration` |

Example:

```bash
.venv/bin/python RPCA.py --crop 440x45+740+50 --retries 3 --poll 2
```

Config-related flags are preserved across **Restart / Apply Update** and **Dispatch**.

---

## Reloading and calibration

- **Reload Config** in the tray reloads the TOML file and applies it on the next worker poll.
- **Open Config** opens the file in your default editor.
- **Calibrate HUD** (or `RPCA.py --calibrate`) opens the interactive wizard described in [Mode Detection](Mode-Detection.md#calibration).
- Saving from the wizard rewrites the file atomically and keeps a `config.toml.bak` copy.
- Manual edits are validated on reload. Check `~/.cache/mech_arena_rpc.log` for `Config:` warnings.

---

## Discord application

### Use your own app

1. Go to <https://discord.com/developers/applications>.
2. Create an application.
3. Copy the **Application ID** into `discord.client_id` (and into `MechArena.py` if you use that variant).
4. Optional: upload Rich Presence assets under **Rich Presence → Art Assets**.
5. Make sure the Discord desktop client is running.

The application name appears as the small header on the presence card ("Playing …"). The default app is named after this project's registration.

### Change the large image

```toml
[discord]
large_image = "mech_arena_logo"
large_text = "Mech Arena"
```

Upload an asset with that key in the Discord Developer Portal, or change `large_image` to another uploaded key. If the asset is missing, the presence still works but the artwork is blank or a placeholder.

### Change the buttons

```toml
[[discord.buttons]]
label = "Download Mech Arena"
url = "https://plarium.com/en/game/mech-arena/"

# Add a second table for a second button.
# Use:
# buttons = []
# for no buttons at all.
```

Discord supports at most two buttons, each with a label and an `https://` URL. Extra entries are ignored with a warning.

Only `RPCA.py` reads the config file. `MechArena.py` keeps its own hardcoded values.

---

## Mode detection crop

### Default geometry

```toml
[hud]
crop = "440x45+740+50"
```

Format is ImageMagick geometry: `WIDTHxHEIGHT+X+Y`. The offset is relative to the captured window's top-left corner.

The easiest way to change it is the calibration wizard:

```bash
.venv/bin/python RPCA.py --calibrate
```

Inside the wizard, `auto` applies the linear scale below for the current window, and `left/right/up/down`, `wider/narrower`, and `taller/shorter` nudge the crop interactively.

### For a different resolution

Scale linearly as a starting point:

```text
scale = width / 1920
W = round(440 * scale)
H = round(45  * scale)
X = round(740 * scale)
Y = round(50  * scale)
```

| Resolution | Starting geometry |
| --- | --- |
| 1920×1080 | `440x45+740+50` |
| 2560×1440 | `587x60+987+67` |
| 3840×2160 | `880x90+1480+100` |
| 1600×900 | `367x38+617+42` |
| 1280×720 | `293x30+493+33` |

Then verify with a real capture:

```bash
WIN=$(xwininfo -root -tree | awk '/"Mech Arena"/ {print $1; exit}')
import -window "$WIN" -crop "440x45+740+50" /tmp/hud.png
```

Open `/tmp/hud.png`. It must show the mode HUD, not empty space. Do not trust the formula blindly: UI scale and Wine virtual desktops change the layout.

### Finding the right offsets

1. In the wizard, run `preview` to save the whole window with the current crop outlined in red.
2. Run `open` to view it.
3. Note the pixel coordinates of the score/beacon strip.
4. Move or resize the crop with the nudge commands, then run `test` to see the ASCII preview and brightness stats.
5. Optionally save labelled samples and run `suggest`.

Manual alternative:

```bash
import -window "$WIN" /tmp/full.png
```

Then crop the rectangle in an image editor or with ImageMagick, and test it with `TestingTools/DumpStrip.py`.

### When to change the crop size

The analysis regions are percentages of the crop, configured by:

```toml
[hud]
edge_fraction = 0.15
center_start_fraction = 0.35
center_end_fraction = 0.65
```

So the crop width does not need to be exactly proportional; it needs to **contain the same HUD element** with the same horizontal composition. A wider crop shifts the percentages; a taller crop includes more rows of pixels and therefore changes the averages.

If you only need to move the crop, keep `440x45` and adjust `+X+Y`.

---

## Detection thresholds

These live under `[hud.thresholds]`:

```toml
[hud.thresholds]
center_min_cpc = 95
center_max_ffa = 95
ratio_max_deathmatch = 0.88
edge_min_deathmatch = 150
ratio_min_cpc = 1.20
min_brightness = 5
```

The checks run in order:

```text
ratio <= ratio_max_deathmatch OR edge >= edge_min_deathmatch  -> Deathmatch
center >= center_min_cpc AND ratio >= ratio_min_cpc           -> Control Point Clash
center < center_max_ffa                                       -> Free-For-All
otherwise                                                     -> In Battle
```

`min_brightness` is a black-frame guard: if `max(center, edge)` is below it, the read is treated as a failed capture and retried instead of locking a wrong mode. Set it to `0` to disable the guard.

See [Mode Detection](Mode-Detection.md) for the rationale and the calibration workflow. Change thresholds only after collecting labelled samples from your own setup; the wizard's `sample` and `suggest` commands can help.

---

## Timing

### Battle mode delay

```toml
[hud]
mode_lock_delay = 15
```

- Lower (e.g. 8–10): the mode appears sooner, but intro/loading frames may be misread.
- Raise (e.g. 20–30): more reliable, but the presence says "In Battle" for longer.
- Detection runs on the first poll where `now - battle_start >= mode_lock_delay`. With a 2-second poll, the effective delay is 15–17 seconds.

### HUD lookup retries

```toml
[hud]
lookup_retries = 3
lookup_retry_delay = 2
```

When `detect_hud_mode()` returns `None`, `detect_hud_mode_with_retry()` makes up to `lookup_retries` additional attempts, sleeping `lookup_retry_delay` seconds between them. The first success locks the mode.

- Set `lookup_retries = 0` to disable the burst and rely on normal polling.
- The retries run inside the worker, so a failed burst can delay state updates by roughly `lookup_retries * lookup_retry_delay` seconds (6 seconds by default).
- After the burst fails, the worker falls back to its normal poll and tries again.
- Each attempt can itself take up to `hud.capture_timeout` (1.5 seconds by default), so worst-case latency is higher than the sleep total.

### Results duration

```toml
[timing]
results_display_duration = 10
```

How long "Viewing Results" stays visible after the UDP socket closes. The check runs on menu polls every `poll_interval` seconds, so the effective duration is 10–12 seconds with the defaults.

### Poll interval

```toml
[timing]
poll_interval = 2
```

This controls `RPCA.py`'s worker loop. `MechArena.py` still uses its own 3-second sleep.

Lowering this makes state changes snappier but increases `psutil` work. Values below 1 second are unnecessary; Discord itself rate-limits presence updates. Keep `mode_lock_delay` in mind: it is measured in wall-clock seconds, not poll counts.

### Session and battle timers

These are not configurable; they are derived:

- `session_start` = first time the game is seen.
- `battle_start` = first time `STATE_BATTLE` is seen.

They are Unix timestamps passed as `start=` to Discord. If you want a countdown instead of elapsed time, you would need to use `end=` (not currently implemented).

---

## Logging

### Change the path

```toml
[logging]
file = "~/.cache/mech_arena_rpc.log"
```

Examples:

```toml
file = "/tmp/mech_arena_rpc.log"
file = "~/.local/state/mech_arena_rpc.log"
```

The parent directory is created automatically. If you move it outside your home, make sure the daemon user can write there.

### Add console output while detached

`log()` prints only when `is_detached` is false and the process is not running `--print-config`/`--calibrate`:

```python
if not is_detached and not cli_mode:
    print(line)
```

Removing that condition would make a detached process write to `/dev/null` (because its stdout was redirected), which accomplishes nothing. To see live output, run in the foreground.

### Increase verbosity

There is no log level. To debug more, add `log(...)` calls. Useful places:

- every poll: current state, `last_state`, `locked_mode`;
- capture failures: `import` return code/stderr;
- Discord update failures.

Avoid logging every poll forever; the file will grow quickly.

---

## Window matching

```toml
[window]
title = "Mech Arena"
```

If your window title differs (Wine virtual desktop, custom launcher), change this string. It is case-sensitive. The first matching line wins.

The daemon builds the match as `"<title>"` inside `xwininfo` output. If you need a looser match, change `get_mech_window_id()` in `RPCA.py` to a substring test, but be careful not to match unrelated windows.

---

## Process matching

```toml
[process]
name = "mecharena.exe"
```

This is used by `RPCA.py`'s `get_mech_state()` (the minimal `MechArena.py` still hardcodes its own). If Wine reports a different executable name, adjust it. Check with:

```bash
pgrep -af -i mecharena
```

---

## UDP heuristic

To require a real remote peer (fewer false positives):

```python
connections = proc.net_connections(kind='udp')
if any(c.raddr for c in connections):
    return STATE_BATTLE
return STATE_MENU
```

This is what `TestingTools/RPCdaemon.py` does. It may miss connections that are open but not yet associated with a peer, so test it in your setup.

To filter by port, inspect `c.raddr.port` / `c.laddr.port` and match the ports you observe with `ss`. Avoid hardcoding ports unless you have confirmed they are stable.

---

## Tray behaviour

### Backend

```python
os.environ["PYSTRAY_BACKEND"] = "appindicator"
```

- `appindicator`: DBus/StatusNotifier, best for KDE and modern desktops.
- `xorg`: legacy X11 tray, may work on some setups; remove or change the variable to try it.
- `gtk`: another pystray backend, depends on the environment.

The variable must be set before `import pystray`.

### Menu items

Edit the `pystray.Menu` in `main()`:

```python
menu = pystray.Menu(
    item(get_menu_status_text, None, enabled=False),
    item(get_menu_stats_text, None, enabled=False),
    pystray.Menu.SEPARATOR,
    item("Restart / Apply Update", on_restart),
    item("Reload Config", on_reload_config),
    item("Open Config", on_open_config),
    item("Calibrate HUD", on_calibrate),
    item("Reset Match Counter", on_reset_stats),
    item("Show Log", on_show_log),
    item("Dispatch (Detach Terminal)", on_dispatch, enabled=lambda item: not is_detached),
    pystray.Menu.SEPARATOR,
    item("Quit", on_quit)
)
```

Add a handler function and an `item(...)` entry. Keep the status items disabled.

### Show Log preferences

`Show Log` uses `launch_in_terminal(["tail", "-f", LOG_FILE])`, which tries the terminal emulators in `TERMINAL_COMMANDS`, then `open_with_default_app()`. Edit those lists in `RPCA.py` to change priority or add editors. The same helpers are used by **Calibrate HUD** and **Open Config**.

### Config and calibration handlers

- `on_reload_config()` calls `reload_config()`, which re-reads the TOML file and re-applies every runtime value.
- `on_open_config()` creates the file if needed, then opens it with the default handler.
- `on_calibrate()` launches `RPCA.py --config <path> --calibrate` in a terminal emulator. If none is found, it logs the exact command to run manually.

---

## Adding a new mode

1. Extend `classify_hud()` in `RPCA.py` with a new branch **before** the generic fallback. Add the thresholds it needs to `settings.Config` and the `[hud.thresholds]` TOML table.

   ```python
   if center_avg >= HUD_CENTER_MIN_ASSAULT and edge_avg >= HUD_EDGE_MIN_ASSAULT:
       return "Assault"
   ```

2. The presence formatting already handles any string:
   ```python
   details=f"In Battle ({locked_mode})"
   ```
3. Use the exact label you want players to see.
4. Update the docs and, if desired, the post-match label logic. It uses the same `locked_mode` string.
5. Extend `suggest_thresholds()` in `RPCA.py` if you want the calibration wizard's `sample`/`suggest` commands to tune the new thresholds.

Test with `TestingTools/RPCdaemon.py` before changing the production daemon: it prints the detected value on every poll, so you can watch it change without waiting for a match to end.

---

## Using a different game

The architecture is not Mech Arena-specific, but several values are:

| Item | Change |
| --- | --- |
| Process match | `[process] name` |
| Window title | `[window] title` |
| HUD crop | `[hud] crop` (or run the calibration wizard) |
| Thresholds | `[hud.thresholds]` |
| Presence text | `details` / `state` strings in `RPCA.py` |
| Asset key | `[discord] large_image` |
| Buttons | `[[discord.buttons]]` |
| Client ID | `[discord] client_id` |

If the new game exposes mode information in a simpler way (window title, log file, API), prefer that over screenshot heuristics.

---

## Files created at runtime

| Path | Created by | Purpose |
| --- | --- | --- |
| `~/.config/mech-arena-rpc/config.toml` | `RPCA.py` / `settings.py` | Active configuration. Created on first launch. |
| `~/.config/mech-arena-rpc/config.toml.bak` | `settings.save_config()` | Backup from the previous save. |
| `~/.config/mech-arena-rpc/config.toml.tmp` | `settings.save_config()` | Short-lived atomic-write temp file. |
| `~/.cache/mech_arena_rpc.log` | `RPCA.py` | Timestamped log. |
| `~/.cache/mech_arena_calibration/` | Calibration wizard | Full-window preview and HUD crop snapshots. |
| `beacon_strip.png` | `TestingTools/CountBeacons.py` | HUD strip sample. |
| `beacon_strip_debug.png` | `TestingTools/DumpStrip.py` | HUD strip sample. |
| `current_hud.png` | `TestingTools/InspectUHD.py` | HUD snapshot. |
| `full_match.png` | `TestingTools/TestCrop.py` | Full-screen capture. |
| `cpc_ally_pct.png`, `cpc_enemy_pct.png` | `TestingTools/LiveStats.py` | CPC score crops. |
| `~/DiscordRPC/extracted_mode_icons/` | `TestingTools/StripAssets.py` | Extracted Unity textures. |

Calibration snapshots live next to the configured log file; if that directory is not writable, the wizard falls back to the system temp directory. Test artifacts are written next to the project or in the current working directory. Delete them freely.

---

## Related pages

- [Mode Detection](Mode-Detection.md) — calibration in depth.
- [Discord Presence](Discord-Presence.md) — payload fields.
- [Tray and Daemon](Tray-and-Daemon.md) — autostart and log viewer.
- [Troubleshooting](Troubleshooting.md) — when a change does not take effect.
