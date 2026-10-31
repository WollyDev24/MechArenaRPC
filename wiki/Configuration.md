# Configuration

This page lists every value you are likely to change, where it lives, and what happens when you change it. All runtime configuration is hardcoded in the Python files; there are no config files or environment variables beyond `PYSTRAY_BACKEND` (which the script sets itself).

---

## Constants in `RPCA.py`

```python
CLIENT_ID = "1565766221813776505"
HUD_CROP_GEOM = "440x45+740+50"
MODE_LOCK_DELAY = 15
HUD_LOOKUP_RETRIES = 3
HUD_LOOKUP_RETRY_DELAY = 2
RESULTS_DISPLAY_DURATION = 10
LOG_FILE = Path.home() / ".cache/mech_arena_rpc.log"

STATE_CLOSED = 0
STATE_MENU = 1
STATE_BATTLE = 2

DOWNLOAD_BUTTONS = [
    {"label": "Download Mech Arena", "url": "https://plarium.com/en/game/mech-arena/"}
]
```

| Constant | Default | Effect |
| --- | --- | --- |
| `CLIENT_ID` | `1565766221813776505` | Discord application identity. |
| `HUD_CROP_GEOM` | `440x45+740+50` | ImageMagick crop geometry for mode detection. |
| `MODE_LOCK_DELAY` | `15` | Seconds after battle start before the HUD is read. |
| `HUD_LOOKUP_RETRIES` | `3` | Retries after the first failed HUD lookup. |
| `HUD_LOOKUP_RETRY_DELAY` | `2` | Seconds between HUD lookup attempts. |
| `RESULTS_DISPLAY_DURATION` | `10` | Seconds to show "Viewing Results". |
| `LOG_FILE` | `~/.cache/mech_arena_rpc.log` | Log destination. |
| `DOWNLOAD_BUTTONS` | one button | Presence button(s), max two. |
| Poll interval | `time.sleep(2)` in `rpc_worker()` | How often game state is checked. |

`MechArena.py` has its own `CLIENT_ID`, `STATE_*`, and `DOWNLOAD_BUTTONS`, and polls every 3 seconds.

---

## Discord application

### Use your own app

1. Go to <https://discord.com/developers/applications>.
2. Create an application.
3. Copy the **Application ID** into `CLIENT_ID` in both scripts you use.
4. Optional: upload Rich Presence assets under **Rich Presence → Art Assets**.
5. Make sure the Discord desktop client is running.

The application name appears as the small header on the presence card ("Playing …"). The default app is named after this project's registration.

### Change the large image

Every `rpc.update()` call uses:

```python
large_image="mech_arena_logo",
large_text="Mech Arena",
```

To use a different asset key, either upload an asset named `mech_arena_logo` or update all call sites. There are five in `RPCA.py` and two in `MechArena.py`.

If the asset is missing, the presence still works but the artwork is blank or a placeholder.

### Change the buttons

```python
DOWNLOAD_BUTTONS = [
    {"label": "Download Mech Arena", "url": "https://plarium.com/en/game/mech-arena/"}
]
```

Discord supports at most two buttons, each with a label and an `https://` URL. To remove the button entirely, pass `buttons=None` or remove the argument from the `rpc.update()` calls.

Remember to update both scripts if you want consistent behaviour.

---

## Mode detection crop

### Default geometry

```python
HUD_CROP_GEOM = "440x45+740+50"
```

Format is ImageMagick geometry: `WIDTHxHEIGHT+X+Y`. The offset is relative to the captured window's top-left corner.

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

1. Capture the whole window:
   ```bash
   import -window "$WIN" /tmp/full.png
   ```
2. Open it in an image viewer and note the pixel coordinates of the score/beacon strip.
3. Crop that rectangle. If you use ImageMagick, the geometry is `WxH+X+Y`.
4. Run `TestingTools/DumpStrip.py` with the new geometry to see a brightness profile.

### When to change the crop size

The analysis regions are percentages of the crop:

- left edge: 0–15%
- centre: 35–65%
- right edge: 85–100%

So the crop width does not need to be exactly proportional; it needs to **contain the same HUD element** with the same horizontal composition. A wider crop shifts the percentages; a taller crop includes more rows of pixels and therefore changes the averages.

If you only need to move the crop, keep `440x45` and adjust `+X+Y`.

---

## Detection thresholds

These are inside `detect_hud_mode()`:

```python
if ratio <= 0.88 or edge_avg >= 150:
    return "Deathmatch"

if center_avg >= 95 and ratio >= 1.20:
    return "Control Point Clash"

if center_avg < 95:
    return "Free-For-All"

return "In Battle"
```

See [Mode Detection](Mode-Detection.md) for the rationale and calibration workflow. Change thresholds only after collecting labelled samples from your own setup.

A sensible change is to add a black-frame guard before the DM check:

```python
if max(center_avg, edge_avg) < 5:
    return None   # capture was black/failed
```

Then the worker will retry instead of locking "Deathmatch" on a black frame.

---

## Timing

### Battle mode delay

```python
MODE_LOCK_DELAY = 15
```

- Lower (e.g. 8–10): the mode appears sooner, but intro/loading frames may be misread.
- Raise (e.g. 20–30): more reliable, but the presence says "In Battle" for longer.
- Detection runs on the first poll where `now - battle_start >= MODE_LOCK_DELAY`. With a 2-second poll, the effective delay is 15–17 seconds.

### HUD lookup retries

```python
HUD_LOOKUP_RETRIES = 3
HUD_LOOKUP_RETRY_DELAY = 2
```

When `detect_hud_mode()` returns `None`, `detect_hud_mode_with_retry()` makes up to `HUD_LOOKUP_RETRIES` additional attempts, sleeping `HUD_LOOKUP_RETRY_DELAY` seconds between them. The first success locks the mode.

- Set `HUD_LOOKUP_RETRIES = 0` to disable the burst and rely on normal polling.
- The retries run inside the worker, so a failed burst can delay state updates by roughly `HUD_LOOKUP_RETRIES * HUD_LOOKUP_RETRY_DELAY` seconds (6 seconds by default).
- After the burst fails, the worker falls back to its normal 2-second poll and tries again.
- Each attempt can itself take up to the `import` timeout (1.5 seconds), so worst-case latency is higher than the sleep total.

### Results duration

```python
RESULTS_DISPLAY_DURATION = 10
```

How long "Viewing Results" stays visible after the UDP socket closes. The check runs on menu polls every 2 seconds, so the effective duration is 10–12 seconds.

### Poll interval

In `RPCA.py`:

```python
time.sleep(2)
```

In `MechArena.py`:

```python
time.sleep(3)
```

Lowering this makes state changes snappier but increases `psutil` work. Values below 1 second are unnecessary; Discord itself rate-limits presence updates. Keep `MODE_LOCK_DELAY` in mind: it is measured in wall-clock seconds, not poll counts.

### Session and battle timers

These are not configurable; they are derived:

- `session_start` = first time the game is seen.
- `battle_start` = first time `STATE_BATTLE` is seen.

They are Unix timestamps passed as `start=` to Discord. If you want a countdown instead of elapsed time, you would need to use `end=` (not currently implemented).

---

## Logging

### Change the path

```python
LOG_FILE = Path.home() / ".cache/mech_arena_rpc.log"
```

Examples:

```python
LOG_FILE = Path("/tmp/mech_arena_rpc.log")
LOG_FILE = Path.home() / ".local/state/mech_arena_rpc.log"
```

The parent directory is created automatically. If you move it outside your home, make sure the daemon user can write there.

### Add console output while detached

`log()` prints only when `is_detached` is false:

```python
if not is_detached:
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

```python
if '"Mech Arena"' in line:
```

If your window title differs (Wine virtual desktop, custom launcher), change this string. It is case-sensitive.

For a more robust match:

```python
if "mech" in line.lower() and "arena" in line.lower():
```

Be careful not to match unrelated windows. The first matching line wins.

---

## Process matching

```python
if name and "mecharena.exe" in name.lower():
```

This is used by both `get_mech_state()` implementations. If Wine reports a different executable name, adjust it. Check with:

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
    pystray.Menu.SEPARATOR,
    item("Show Log", on_show_log),
    item("Dispatch (Detach Terminal)", on_dispatch, enabled=lambda item: not is_detached),
    pystray.Menu.SEPARATOR,
    item("Quit", on_quit)
)
```

Add a handler function and an `item(...)` entry. Keep the status item disabled.

### Show Log preferences

Edit the `terminals` and `gui_openers` lists in `on_show_log()` to change priority or add editors.

---

## Adding a new mode

1. Extend `detect_hud_mode()` with a new branch **before** the generic fallback.

   ```python
   if center_avg >= 80 and edge_avg >= 80 and ratio > 0.95:
       return "Assault"
   ```

2. The presence formatting already handles any string:
   ```python
   details=f"In Battle ({locked_mode})"
   ```
3. Use the exact label you want players to see.

4. Update the docs and, if desired, the post-match label logic. It uses the same `locked_mode` string.

Test with `TestingTools/RPCdaemon.py` before changing the production daemon: it prints the detected value on every poll, so you can watch it change without waiting for a match to end.

---

## Using a different game

The architecture is not Mech Arena-specific, but several values are:

| Item | Change |
| --- | --- |
| Process match | `"mecharena.exe"` |
| Window title | `"Mech Arena"` |
| HUD crop | `HUD_CROP_GEOM` |
| Thresholds | `detect_hud_mode()` |
| Presence text | `details` / `state` strings |
| Asset key | `large_image` |
| Buttons | `DOWNLOAD_BUTTONS` |
| Client ID | `CLIENT_ID` |

If the new game exposes mode information in a simpler way (window title, log file, API), prefer that over screenshot heuristics.

---

## Files created at runtime

| Path | Created by | Purpose |
| --- | --- | --- |
| `~/.cache/mech_arena_rpc.log` | `RPCA.py` | Timestamped log. |
| `beacon_strip.png` | `TestingTools/CountBeacons.py` | HUD strip sample. |
| `beacon_strip_debug.png` | `TestingTools/DumpStrip.py` | HUD strip sample. |
| `current_hud.png` | `TestingTools/InspectUHD.py` | HUD snapshot. |
| `full_match.png` | `TestingTools/TestCrop.py` | Full-screen capture. |
| `cpc_ally_pct.png`, `cpc_enemy_pct.png` | `TestingTools/LiveStats.py` | CPC score crops. |
| `~/DiscordRPC/extracted_mode_icons/` | `TestingTools/StripAssets.py` | Extracted Unity textures. |

Those test artifacts are written next to the project or in the current working directory. Delete them freely.

---

## Related pages

- [Mode Detection](Mode-Detection.md) — calibration in depth.
- [Discord Presence](Discord-Presence.md) — payload fields.
- [Tray and Daemon](Tray-and-Daemon.md) — autostart and log viewer.
- [Troubleshooting](Troubleshooting.md) — when a change does not take effect.
