# Troubleshooting

This page is organised by symptom. Start with the checklist, then jump to the matching section.

---

## First-response checklist

```bash
# 1. Is the game running?
pgrep -af -i mecharena

# 2. Does it have UDP sockets?
ss -u -p | grep -i mech

# 3. Is the window visible to X11?
xwininfo -root -tree | grep -i 'Mech Arena'

# 4. Is Discord running and exposing IPC?
ls -l "$XDG_RUNTIME_DIR"/discord-ipc-* 2>/dev/null
find "$XDG_RUNTIME_DIR" -name 'discord-ipc-*' 2>/dev/null

# 5. Is the daemon running?
pgrep -af RPCA.py

# 6. What config is it using?
.venv/bin/python RPCA.py --print-config | head -20

# 7. What does it say?
tail -n 100 ~/.cache/mech_arena_rpc.log
```

If step 1–3 fail, the problem is the game/XWayland environment, not the daemon. If step 4 fails, it is Discord IPC. If only step 7 shows capture failures, it is the HUD crop. If step 6 looks wrong, see [Config changes have no effect](#config-changes-have-no-effect).

---

## Tray icon does not appear

`RPCA.py` forces the AppIndicator backend:

```python
os.environ["PYSTRAY_BACKEND"] = "appindicator"
```

The tray therefore needs PyGObject and an AppIndicator/Ayatana typelib.

### Checks

```bash
# Run in the foreground to see tracebacks
.venv/bin/python RPCA.py

# PyGObject available to the venv?
.venv/bin/python -c 'import gi; print(gi.__version__)'

# AyatanaAppIndicator3 typelib available?
.venv/bin/python - <<'PY'
import gi
gi.require_version('AyatanaAppIndicator3', '0.1')
print('AyatanaAppIndicator3 available')
PY
```

If `gi` is missing, install `python3-gi`/`python-gobject` from your distro. If the venv was created without system site packages, recreate it with `--system-site-packages` (or install PyGObject into the venv itself).

### Desktop-specific

- **GNOME**: install and enable the *AppIndicator and KStatusNotifierItem Support* extension.
- **KDE**: AppIndicator is supported natively; make sure the status notifier widget is present.
- **X11-only environments**: try the legacy backend by removing/changing the `PYSTRAY_BACKEND` line (e.g. `"xorg"`), then restart the daemon.
- After installing packages, log out and back in (or restart the panel) so DBus/typelib changes take effect.

### The process runs but there is no icon

Check whether the tray host is alive:

```bash
busctl --user list | grep -i indicator
```

Also make sure the daemon is not crashing after creating the icon. Run it in the foreground and watch the terminal.

---

## Config changes have no effect

### Where is the config?

```bash
ls -l ~/.config/mech-arena-rpc/config.toml
.venv/bin/python RPCA.py --print-config | head -20
```

`--print-config` prints the **merged** result: CLI overrides, then file, then defaults. If the printed value is not what you edited, you are probably editing a different file. Use `--config PATH` or check `XDG_CONFIG_HOME`.

### Did the daemon reload it?

Editing the file does nothing until you choose tray → **Reload Config**. A restart also works. The log prints `Configuration reloaded from …` on success.

### Are there validation warnings?

```bash
grep 'Config:' ~/.cache/mech_arena_rpc.log | tail -20
```

Invalid values and unknown keys are logged and replaced with defaults. Common causes:

| Warning | Meaning |
| --- | --- |
| `invalid crop geometry ...` | Use `WxH+X+Y`, e.g. `440x45+740+50`. |
| `is above 255` / `is below ...` | A threshold or timing value is out of range. |
| `unknown setting ignored` | Typo or a key that belongs under a different table. |
| `expected a table` | A `[section]` header is wrong or duplicated. |
| `created default config at ...` | First run; the file did not exist yet. |

### TOML syntax errors

A parse error makes the daemon fall back to built-in defaults and log the exception. Validate with:

```bash
.venv/bin/python - <<'PY'
import tomllib, pathlib
print(tomllib.loads(pathlib.Path('~/.config/mech-arena-rpc/config.toml').expanduser().read_text()))
PY
```

### Buttons

Discord rejects more than two buttons. Extra entries are ignored with a warning. Each URL must start with `http://` or `https://`; a `label` is required.

### Python 3.10

`settings.py` uses `tomllib` on Python 3.11+. On 3.10 it needs `tomli`; `setup.sh` installs it. Without either, the daemon logs a warning and uses defaults.

---

## Discord presence never appears

### Is Discord running?

The daemon only connects when the game is running (`state != STATE_CLOSED`). If Discord starts later, the daemon retries every 2 seconds.

### Is the IPC socket visible?

```bash
ls -l "$XDG_RUNTIME_DIR"/discord-ipc-* 2>/dev/null
find "$XDG_RUNTIME_DIR" -name 'discord-ipc-*' 2>/dev/null
```

Typical:
- `$XDG_RUNTIME_DIR/discord-ipc-0`
- `$XDG_RUNTIME_DIR/app/com.discordapp.Discord/discord-ipc-0`

If there is no socket, Discord's IPC is unavailable. Start the desktop client, not the web version.

### Flatpak / Snap

Sandboxed Discord may have a private `XDG_RUNTIME_DIR` and expose the socket somewhere the daemon cannot see. Options:

- Install the native Discord client.
- Grant the Flatpak filesystem access to the runtime directory.
- Run the daemon inside the same sandbox (advanced).

### Client ID or asset problem

- `InvalidID` in the log means `discord.client_id` is rejected. Restore the default or create your own app.
- If the card appears but the large image is blank, upload an asset named `mech_arena_logo` or change `discord.large_image`.
- Buttons may not render on all clients; that is a Discord limitation.
- `MechArena.py` does not read the config file; change its hardcoded values separately.

### Smoke test

```bash
python - <<'PY'
import time
from pypresence import Presence

rpc = Presence("1565766221813776505")
rpc.connect()
rpc.update(details="Test", state="Presence", start=int(time.time()))
time.sleep(30)
rpc.clear()
rpc.close()
PY
```

If this fails, fix Discord IPC before touching the daemon.

### Presence appears but is stale

- The daemon only updates on transitions. If it crashed, the card disappears when the socket closes.
- If the game is running but the daemon is not, no one updates the card.
- If Discord restarted, the daemon may still hold a stale connection; an `rpc.update()` can raise and stop the worker. Restart the daemon.
- If the game closed while Discord was disconnected, the internal timers/state may be stale. Restart the daemon.
- If the mode is wrong, see [Mode detection is wrong](#mode-detection-is-wrong).

---

## Game is not detected

### Process name mismatch

```bash
pgrep -af -i mecharena
```

The code matches the `name` set in `[process]` (default `"mecharena.exe"`) as a case-insensitive substring. Wine usually reports `MechArena.exe`. If your setup reports something else, change the config and reload:

### Permission errors

`psutil.AccessDenied` is caught and skipped. If the game runs under another user (or a different Wine prefix owned by root), the daemon may see no process or no sockets. Run the daemon as the same user as the game.

### Stale process

A leftover `MechArena.exe` from a previous session can keep the daemon in "menu" or "battle" forever. Kill it:

```bash
pkill -f MechArena.exe
```

### UDP false negative

If the game is clearly in a match but the daemon says "In Hangar", check the socket list:

```bash
ss -u -p | grep -i mech
```

If there are no UDP sockets, the heuristic cannot see the battle. The prototype's stricter/looser check may behave differently:

```bash
python TestingTools/RPCdaemon.py
```

### UDP false positive

If the daemon says "In Battle" while in the hangar, the process has a UDP socket for another reason. Try the prototype's remote-address condition:

```python
if any(c.raddr for c in proc.net_connections(kind='udp')):
    return STATE_BATTLE
```

or filter by the ports you observe with `ss`.

### It works in `MechArena.py` but not `RPCA.py`

They share the same `get_mech_state()`. If one works and the other does not, the tray daemon is probably failing before the worker starts. Run `RPCA.py` in the foreground and read the traceback.

---

## Mode detection is wrong

### Is the game window found?

```bash
xwininfo -root -tree | grep -i 'Mech Arena'
```

If nothing matches, `get_mech_window_id()` returns `None` and detection silently retries. Check the exact title against `[window] title` (case-sensitive `"Mech Arena"` by default).

### Is the crop correct?

The easiest check is the calibration wizard:

```bash
.venv/bin/python RPCA.py --calibrate
calibrate> test
```

It prints `Center`, `Edge`, `Ratio`, the current verdict, and an ASCII preview. Use `preview` and `open` to see the crop outlined on the full window.

Manual check:

```bash
WIN=$(xwininfo -root -tree | awk '/"Mech Arena"/ {print $1; exit}')
import -window "$WIN" -crop 440x45+740+50 /tmp/hud.png
```

The geometry must match `[hud] crop`. Open `/tmp/hud.png`; it must show the score/beacon strip. If it shows empty sky or another HUD element, recalibrate.

See [Mode Detection → Calibration](Mode-Detection.md#calibration).

### Is it always "In Battle"?

That means the heuristics returned the fallback (or detection never locked and the generic battle presence is shown). Check the log for `HUD Analysis` lines.

- If there are no `HUD Analysis` lines, the capture or window lookup is failing. Look for `HUD lookup failed (attempt X/4); retrying in 2s...` and `HUD lookup failed after 4 attempts` in the log.
- If there are lines but no `Locked Mode` line, the fallback was returned.
- If the analysis values are all near zero, the capture is black or `min_brightness` is rejecting it.

### Is it always "Deathmatch"?

Older code treated a fully black capture as Deathmatch (`ratio = 0.0`). Current code has a `min_brightness` guard (default `5`): a frame where both centre and edge are below it returns `None` and is retried instead.

If you still see false Deathmatch:

- Check the log values. If `edge >= edge_min_deathmatch` on genuine menu/intro frames, raise `edge_min_deathmatch`.
- If the ratio is low on non-DM frames, lower `ratio_max_deathmatch` (e.g. `0.80`).
- Set `min_brightness = 0` only if you deliberately want to disable the guard.

### "In Battle (In Battle)"

The fallback string is treated as a successful lock. It is cosmetic. Tune the thresholds, or treat `"In Battle"` as a sentinel in the worker:

```python
if detected and detected != "In Battle":
    locked_mode = detected
```

### The mode is correct but appears late

`hud.mode_lock_delay` (default `15`) plus `timing.poll_interval` (default 2 seconds) means 15–17 seconds. Lower it if you accept intro-frame risk; raise it for reliability. A failed lookup burst adds up to `lookup_retries * lookup_retry_delay` seconds (6 by default).

### The mode changes during the match

You are probably running `TestingTools/RPCdaemon.py`, which re-detects every poll. `RPCA.py` locks after one read.

### Wrong mode for your resolution

The default crop is for 1920×1080 at 100% UI scale. Run the calibration wizard and try `auto`, then nudge. See [Mode Detection → Calibration](Mode-Detection.md#calibration).

### The wizard will not start

- **Calibrate HUD** needs a terminal emulator from `TERMINAL_COMMANDS`. If none is found, the log prints the exact command.
- `RPCA.py --calibrate` with redirected stdin prints `The calibration wizard needs an interactive terminal` and exits 1. Run it from a real terminal.
- If captures fail inside the wizard, the game is minimised or `[window] title` does not match. Run `xwininfo -root -tree`.

### Window is in a Wine virtual desktop

The captured window may be the virtual desktop, not the game viewport. Adjust the crop to the virtual desktop's HUD position, or disable the virtual desktop.

---

## Results screen does not appear

The results state requires an observed `BATTLE → MENU` transition:

```python
if last_state == STATE_BATTLE:
    results_until = now + RESULTS_DISPLAY_DURATION
```

Common causes:

| Cause | Explanation |
| --- | --- |
| Daemon started while already in the menu | It never saw the battle state. |
| UDP socket closed before the match ended | The transition happened earlier than expected. |
| Discord was disconnected during the transition | `last_state` updates only when `rpc` is connected. |
| Match ended and a new one started within 10 s | The battle branch clears the results timer. |
| `RESULTS_DISPLAY_DURATION` set to 0 | The window expires immediately. |

The results card uses `session_start`, so the timer continues from the session rather than resetting.

---

## Show Log does nothing

`on_show_log()` tries terminals in this order:

1. `ghostty`
2. `kitty`
3. `alacritty`
4. `konsole`

Then GUI openers:

1. `kate`
2. `kwrite`
3. `gedit`
4. `xdg-open`

If none are installed, the handler returns silently. Install one, or read the log manually:

```bash
tail -f ~/.cache/mech_arena_rpc.log
```

Check `shutil.which` visibility from the daemon's environment:

```bash
for c in ghostty kitty alacritty konsole kate kwrite gedit xdg-open; do
  command -v "$c" && echo "  ^ $c"
done
```

If the log file is not growing, logging itself is failing. `log()` swallows all exceptions. Check permissions on `~/.cache` and the file:

```bash
ls -ld ~/.cache
ls -l ~/.cache/mech_arena_rpc.log
```

---

## Dispatch leaves duplicates or fails

### Check running instances

```bash
pgrep -af 'RPCA.py'
```

You may briefly see two processes during the handover; the foreground one calls `os._exit(0)` immediately. If it persists, kill it:

```bash
pkill -f 'RPCA.py'
```

### The detached process exits immediately

Its stdout/stderr are `/dev/null`, so tracebacks are lost. Reproduce in the foreground:

```bash
.venv/bin/python RPCA.py
```

Common causes: missing AppIndicator/PyGObject, no DBus session, wrong Python interpreter, or the working directory missing.

The detached child uses `sys.executable`, so it inherits the venv if you launched with `.venv/bin/python`. If you launched with a system Python that cannot import the dependencies, the child fails the same way.

### Verify the session

```bash
ps -o pid,ppid,sid,tty,cmd -p "$(pgrep -f 'RPCA.py --detached' | head -1)"
```

`TTY` should be `?`. `SID` should not be your shell's session.

### Closing the terminal still kills it

- Did you use the menu's Dispatch, or just close the terminal?
- `SIGHUP` is ignored, but `SIGTERM`/`SIGKILL` from the terminal emulator or session manager can still terminate the process.
- A systemd user service or `.desktop` autostart is more robust than a terminal launch.

---

## Testing tool problems

### `Permission denied` reading `/proc/<pid>/mem`

```bash
cat /proc/sys/kernel/yama/ptrace_scope
```

- `0`: permissive (may still be restricted by other LSMs).
- `1`: only descendants can be traced.
- `2`/`3`: stricter.

Run the tool as the same user as the game. If needed, temporarily lower the scope (not recommended for general use):

```bash
sudo sysctl kernel.yama.ptrace_scope=0
```

or run the tool with elevated privileges. Prefer fixing ownership/permissions over running everything as root.

### Raw socket permission denied

`SniffHandshake.py`, `SniffLoopback.py`, and `TestNet.py` need `CAP_NET_RAW`:

```bash
sudo python TestingTools/SniffHandshake.py
```

Avoid permanently granting capabilities to a general-purpose Python binary. If you do, remove the capability afterwards.

### `DetectMode.py` cannot find Tesseract

```bash
tesseract --version
pip install pytesseract
```

Install the `tesseract-ocr` system package. The pip package is only a wrapper.

### `StripAssets.py` finds nothing

- The hardcoded user path (`/home/wolly/...`) does not match your account.
- The game may not have populated that cache folder yet.
- Bundle layouts change; the target folder names may be stale.
- Check the installed UnityPy API; object type names can differ between versions.

### Window ID `0x4a00001` does not exist

`CountBeacons.py` and `DumpStrip.py` hardcode that ID. Resolve the current one:

```bash
xwininfo -root -tree | grep -i 'Mech Arena'
```

Then edit the script, or use `InspectUHD.py`, which resolves the ID dynamically.

### `mss` capture is black on Wayland

`TestCrop.py` captures the X display. On a pure Wayland session without XWayland it may fail. Use the ImageMagick `import -window` approach against the XWayland window instead.

### Memory scans are slow

They read tens of megabytes per mapping. Expect seconds, not milliseconds. Close the game or stop the scan if it stalls. The production daemon does none of this.

---

## Wayland and Wine notes

- Wine windows are XWayland windows. `xwininfo` and `import` require XWayland; a pure Wayland setup with no XWayland will not work.
- Keep the game window visible and unminimised for screenshots.
- A Wine virtual desktop changes the captured window size and coordinate origin.
- Compositor screen-capture restrictions can affect `mss`; window-targeted ImageMagick capture is usually more reliable.
- AppIndicator is the right tray backend for Wayland/KDE, but GNOME needs the extension.

---

## Performance

The production daemon is light:

- One `psutil.process_iter` and one `net_connections` call every 2 seconds.
- One `import` screenshot per match, 15 seconds after the battle starts.
- A handful of Discord updates per match.

If you see CPU usage, check for:

- Multiple daemon instances (`pgrep -af RPCA.py`).
- A tiny poll interval you introduced.
- Running `TestingTools/RPCdaemon.py` in parallel (it screenshots every battle poll).
- A very large number of processes making `process_iter` expensive.

Memory usage is mostly Python + PyGObject + Pillow. The screenshot is decoded in memory and discarded after analysis.

---

## FAQ

**Does it work on Windows?**
No. It relies on Linux `/proc`, `psutil` process names under Wine, `xwininfo`, and ImageMagick X11 capture.

**Does it modify or automate the game?**
No. The production daemon reads process metadata and takes a screenshot. It does not inject, automate input, or alter game files.

**Can I get banned?**
The production daemon does not read memory or sniff packets. The research tools do, and may violate the game's terms of service or anti-cheat policy. Use them at your own risk.

**Why does it say "In Battle" in the lobby?**
The production heuristic treats any UDP socket as a battle. The prototype's `raddr` check is stricter.

**Why did the timer reset?**
Battle presence uses `battle_start`; menu/results use `session_start`. A new match resets the battle timer.

**Can I show the mode icon instead of the logo?**
Yes, in principle: extract icons with `StripAssets.py`, upload them as Discord assets, and choose `large_image` based on `locked_mode`. The current code always uses `mech_arena_logo`.

**Can I make it start at login?**
Yes. See [Tray and Daemon → Autostart](Tray-and-Daemon.md#autostart).

**Can I use my own Discord app?**
Yes. Replace `CLIENT_ID` and upload an asset named `mech_arena_logo`, or change the asset key.

**Why is there no config file?**
Configuration is intentionally minimal and hardcoded. Edit the constants at the top of the scripts.

---

## Known limitations

- Linux + X11/XWayland only.
- The HUD crop assumes 1920×1080 and 100% UI scale by default.
- Mode detection is a one-shot heuristic with 15 s delay; a bad read lasts the match.
- Any UDP socket counts as a battle in production.
- Results state requires an observed battle-to-menu transition.
- No automatic re-detection of the mode within a match.
- No log rotation.
- Tray requires AppIndicator/PyGObject.
- Sandboxed Discord installs may block IPC.
- Research tools may need root and can break with game updates.

---

## Related pages

- [Game State Detection](Game-State-Detection.md)
- [Mode Detection](Mode-Detection.md)
- [Discord Presence](Discord-Presence.md)
- [Tray and Daemon](Tray-and-Daemon.md)
- [Configuration](Configuration.md)
- [Testing Tools](Testing-Tools.md)
