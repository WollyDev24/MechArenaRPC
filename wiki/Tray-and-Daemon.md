# Tray and Daemon

`RPCA.py` is designed to live in the system tray, survive the terminal that launched it, and expose just enough controls to debug and tune it. This page covers the tray UI, config/calibration actions, logging, the detach mechanism, and shutdown.

---

## Why a tray icon?

- The daemon is long-running and mostly silent.
- Users need a way to see the current status without reading a terminal.
- A tray icon provides quit/log/detach controls without a separate window.
- On Wayland/KDE, AppIndicator integrates with the desktop's status notifier area.

The icon is generated in code with Pillow, so there are no external image files to ship.

---

## Backend selection

```python
os.environ["PYSTRAY_BACKEND"] = "appindicator"
```

This line runs **before** `import pystray`. pystray reads the environment variable at import time to choose its backend.

Why AppIndicator?

- Works with KDE's StatusNotifierItem and GNOME's AppIndicator extension.
- Uses DBus instead of raw X11 tray windows.
- Handles Wayland sessions better than the legacy Xorg backend.

Requirements:

- PyGObject (`gi` module) available to the same Python interpreter.
- An AppIndicator/Ayatana typelib (e.g. `libayatana-appindicator3`).
- A desktop that displays AppIndicator/StatusNotifier items.

If the backend cannot load, pystray raises at import or when the icon runs. See [Troubleshooting](Troubleshooting.md).

### Foreground vs detached

The environment variable is set unconditionally. Running `RPCA.py` from a terminal and running it detached use the same tray backend; only stdio and the parent session differ.

---

## The icon

```python
def create_tray_icon_image():
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.polygon([(32, 4), (58, 18), (58, 46), (32, 60), (6, 46), (6, 18)],
                 fill=(30, 35, 45, 255))
    draw.rounded_rectangle([(16, 26), (48, 38)], radius=4, fill=(0, 200, 255, 255))
    draw.polygon([(32, 10), (42, 18), (22, 18)], fill=(0, 200, 255, 255))
    return img
```

- Transparent 64×64 canvas.
- Dark hexagonal shield.
- Cyan visor bar and crest.

It is deliberately simple and readable at small tray sizes. No file I/O, no theme dependency.

---

## Menu

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

| Item | Behaviour |
| --- | --- |
| **Status: …** | Disabled item whose label is computed at render time from `current_ui_status`. |
| **Matches Played: …** | Disabled item showing the session match counter. |
| **Restart / Apply Update** | Re-executes the script from disk, preserving session/match state and config CLI flags. |
| **Reload Config** | Re-reads the TOML file and re-applies every runtime value on the next worker poll. |
| **Open Config** | Creates the config if needed, then opens it with the default handler. |
| **Calibrate HUD** | Launches `RPCA.py --config <path> --calibrate` in a terminal emulator. |
| **Reset Match Counter** | Sets the session match count back to 0. |
| **Show Log** | Opens the log file in a terminal follower or GUI editor. |
| **Dispatch (Detach Terminal)** | Relaunches the daemon detached and exits the current process. Disabled when already detached. |
| **Quit** | Stops the tray loop and ends the process. |

### Status updates

`set_status(text)`:

1. Writes `current_ui_status` under `state_lock`.
2. Sets `tray_icon.title = f"Mech Arena: {text}"` (tooltip).
3. Calls `tray_icon.update_menu()` so the disabled item re-renders.

Possible status strings:

| Status | When |
| --- | --- |
| `Waiting for Mech Arena...` | Initial value. |
| `In Battle (Detecting mode...)` | Battle started, `mode_lock_delay` grace period running. |
| `In Battle (Deathmatch)` etc. | Mode locked. |
| `Viewing Results` | Post-match window (`results_display_duration`). |
| `In Hangar` | Menu. |
| `Game Closed` | Process disappeared. |
| `Config reloaded` | After **Reload Config**. |
| `Config reloaded (warnings)` | After **Reload Config** with validation warnings; see the log. |

The status text is independent of the Discord presence; it is the tray's own view of the worker state.

---

## Config and calibration actions

### Reload Config

`on_reload_config()` calls `reload_config()`, which:

1. Loads the TOML file again through `settings.load_config()`.
2. Applies CLI overrides again.
3. Calls `apply_config()` to refresh every runtime global.
4. Logs each `Config:` warning.
5. Updates the status text and sends a notification.

Because `apply_config()` updates the same globals the worker reads, the new values take effect on its next poll without a restart.

### Open Config

`on_open_config()` creates `CONFIG_PATH` if it is missing, then tries `xdg-open`, `kate`, `kwrite`, and `gedit`. If none is available, it logs the path so you can edit it manually.

### Calibrate HUD

`on_calibrate()` builds:

```bash
<venv python> /abs/path/RPCA.py --config <CONFIG_PATH> --calibrate
```

and launches it through `launch_in_terminal()`. If no terminal emulator is found, the exact command is written to the log. The wizard itself is documented in [Mode Detection](Mode-Detection.md#calibration).

### Terminal and opener detection

`TERMINAL_COMMANDS` is tried in order:

- `ghostty -e`
- `kitty -e`
- `alacritty -e`
- `konsole -e`
- `wezterm start --`
- `xterm -e`
- `gnome-terminal --`

`open_with_default_app()` falls back to `xdg-open`, `kate`, `kwrite`, then `gedit`. Both helpers start the child in a new session and send its stdio to `/dev/null`.

---

## Logging

### Destination

```toml
[logging]
file = "~/.cache/mech_arena_rpc.log"
```

`RPCA.py` loads this into `LOG_FILE`. If the parent directory does not exist, `log()` creates it. Each line is prefixed with a local timestamp:

```text
[2026-10-31 12:34:56] Connected to Discord RPC.
[2026-10-31 12:35:02] Status: In Battle (Waiting 15s to detect mode...)
[2026-10-31 12:35:17] HUD Analysis: Center=118.4, Edge=71.2, Ratio(C/E)=1.66
[2026-10-31 12:35:17] Locked Mode: Control Point Clash
[2026-10-31 12:36:40] Status: Viewing Results (10s)
```

### Behaviour by mode

| | Foreground | Detached | `--print-config` / `--calibrate` |
| --- | --- | --- | --- |
| Console output | Yes (`print`) | No | No |
| File output | Yes | Yes | Yes |
| Timestamp | Yes | Yes | Yes |
| Failure handling | Swallowed | Swallowed | Swallowed |

`log()` checks `is_detached` and `cli_mode`. It never raises. If the file cannot be written (permissions, read-only home, full disk), the daemon keeps running.

### Log rotation

There is none. The file grows slowly (a handful of lines per match), but if you run the daemon for months, truncate it periodically:

```bash
: > ~/.cache/mech_arena_rpc.log
```

or add a logrotate rule. Do not truncate while a `tail -f` viewer is open unless you expect the viewer to handle it.

### Watching the log

```bash
tail -f ~/.cache/mech_arena_rpc.log
```

---

## Show Log

```python
def on_show_log(icon, menu_item):
    ...
```

The handler:

1. Ensures the parent directory and file exist.
2. Calls `launch_in_terminal(["tail", "-f", str(LOG_FILE)])`, which tries terminal emulators in `TERMINAL_COMMANDS` (ghostty, kitty, alacritty, konsole, wezterm, xterm, gnome-terminal).
3. Falls back to `open_with_default_app()`, which tries `xdg-open`, `kate`, `kwrite`, `gedit`.
4. If none are found, logs that fact.

`shutil.which()` decides availability. The child process is started with `subprocess.Popen` in a new session and its stdio sent to `/dev/null`. The terminal window stays open until you close it; closing it stops `tail`, which is harmless.

The GUI fallback opens the file statically; it will not auto-refresh. Re-open it or use `tail -f` for live updates.

---

## Dispatch (detach from terminal)

### The problem

A process started from a terminal is in that terminal's session. Closing the terminal sends `SIGHUP` (and often `SIGTERM`) to the foreground process group, which would kill the daemon.

### The solution

Two layers:

1. At startup, `RPCA.py` ignores `SIGHUP`:
   ```python
   signal.signal(signal.SIGHUP, signal.SIG_IGN)
   ```
2. Dispatch relaunches the daemon in a **new kernel session** with no controlling terminal:
   ```python
   args = [sys.executable, os.path.abspath(__file__), "--detached",
           *persistent_cli_args(sys.argv)]
   subprocess.Popen(
       args,
       stdin=subprocess.DEVNULL,
       stdout=subprocess.DEVNULL,
       stderr=subprocess.DEVNULL,
       start_new_session=True,
       close_fds=True
   )
   is_running = False
   icon.stop()
   os._exit(0)
   ```

`start_new_session=True` calls `setsid()` in the child, detaching it from the parent's session and process group. `close_fds=True` prevents leaking file descriptors. The parent then calls `os._exit(0)` immediately, without joining threads or running `finally` blocks.

`persistent_cli_args()` carries `--config`, `--crop`, `--retries`, and the other config overrides into the new process. The TOML file itself is read again by the child.

### The `--detached` flag

The child sees `--detached` in `sys.argv`:

```python
is_detached = "--detached" in sys.argv
if is_detached:
    null_fd = os.open(os.devnull, os.O_RDWR)
    os.dup2(null_fd, 0)
    os.dup2(null_fd, 1)
    os.dup2(null_fd, 2)
    os.close(null_fd)
```

This is belt-and-braces: the parent already redirected stdio, but the child re-applies it so it behaves correctly regardless of how it was launched. `is_detached` also suppresses console logging and disables the Dispatch menu item (to avoid spawning an endless chain of detached processes).

### Why `os._exit(0)`?

`sys.exit()` would unwind the stack, stop the tray loop, and wait for non-daemon threads. `os._exit()` terminates immediately. The worker thread is a daemon and is killed as part of process teardown. The child is already independent, so there is nothing to wait for.

The trade-off: the parent's RPC connection is not explicitly cleared. Discord removes presence when the IPC socket closes, and the child reconnects and republishes, so the visible result is a brief refresh rather than a stale card.

### Dispatch flow

```
Foreground process                  New detached process
──────────────────                  ────────────────────
tray menu click
  │
  ├─ Popen(self --detached,
  │        persistent CLI flags,
  │        new session,
  │        stdio=/dev/null) ───────► starts RPCA.py
  │                                    │
  │                                    ├─ SIGHUP ignored
  │                                    ├─ stdio -> /dev/null
  │                                    ├─ PYSTRAY_BACKEND=appindicator
  │                                    ├─ config loaded (same path/flags)
  │                                    ├─ tray + worker start
  │                                    └─ logs only to ~/.cache/...
  │
  ├─ is_running = False
  ├─ icon.stop()
  └─ os._exit(0)
```

### Verifying it worked

```bash
pgrep -af 'RPCA.py'
```

You should see a process with `--detached` in its command line. Check that it is in its own session:

```bash
ps -o pid,ppid,sid,tty,cmd -p "$(pgrep -f 'RPCA.py --detached' | head -1)"
```

`TTY` should be `?` and `SID` should equal the PID (or at least not your shell's session).

### Detaching manually

Instead of using the menu:

```bash
setsid -f python /path/to/RPCA.py --detached
```

or a desktop autostart entry (see below).

---

## Quit

```python
def on_quit(icon, menu_item):
    global is_running
    is_running = False
    icon.stop()
```

`icon.stop()` ends the tray loop, `main()` returns, and the interpreter exits. The worker is a daemon thread, so it does not block shutdown. The worker's post-loop `rpc.clear()` / `rpc.close()` is best-effort and may not run; Discord normally clears the presence when the IPC socket closes.

There is no confirmation dialog.

---

## Autostart

### Desktop autostart

Create `~/.config/autostart/mech-arena-rpc.desktop`:

```ini
[Desktop Entry]
Type=Application
Name=Mech Arena RPC
Comment=Discord Rich Presence for Mech Arena
Exec=/home/YOUR_USER/DiscordRPC/.venv/bin/python /home/YOUR_USER/DiscordRPC/RPCA.py --detached
Terminal=false
X-GNOME-Autostart-enabled=true
```

Use absolute paths. The `--detached` flag suppresses console logging and disables the Dispatch item.

### systemd user service (optional)

```ini
# ~/.config/systemd/user/mech-arena-rpc.service
[Unit]
Description=Mech Arena Discord Rich Presence
After=graphical-session.target

[Service]
Type=simple
ExecStart=/home/YOUR_USER/DiscordRPC/.venv/bin/python /home/YOUR_USER/DiscordRPC/RPCA.py
Restart=on-failure

[Install]
WantedBy=graphical-session.target
```

Enable with:

```bash
systemctl --user daemon-reload
systemctl --user enable --now mech-arena-rpc.service
```

Caveats:

- The service needs access to the graphical session: `DISPLAY`, `WAYLAND_DISPLAY`, `XDG_RUNTIME_DIR`, and the DBus session bus. Depending on your distro, `graphical-session.target` and the imported environment may be enough; otherwise set `Environment=` explicitly.
- Tray integration may need the service to run after the status notifier host is ready.
- A systemd service does not have a terminal, so the detached flag is unnecessary.

For most users, the `.desktop` autostart is simpler.

---

## Wayland / KDE notes

- Wine windows are XWayland windows; `xwininfo` and ImageMagick `import` operate on the XWayland display.
- The tray uses AppIndicator over DBus, which KDE exposes through StatusNotifierItem.
- On GNOME, install and enable the **AppIndicator and KStatusNotifierItem Support** extension; otherwise the icon may not appear.
- If the session is pure Wayland with no XWayland, the screenshot tools will not find the game window.
- Screen capture may be restricted by the compositor. `import -window <id>` against an XWayland window usually works; full-screen `mss` capture may need XWayland rather than a native Wayland grab.

---

## Debugging the tray

```bash
# Is the process running?
pgrep -af RPCA.py

# Did it log anything?
tail -n 50 ~/.cache/mech_arena_rpc.log

# What config is it actually using?
.venv/bin/python RPCA.py --print-config | head -20

# Did the config have warnings?
grep 'Config:' ~/.cache/mech_arena_rpc.log | tail -20

# Is PyGObject importable by the venv?
.venv/bin/python -c 'import gi; print(gi.__version__)'

# Is the AppIndicator typelib present?
.venv/bin/python - <<'PY'
import gi
gi.require_version('AyatanaAppIndicator3', '0.1')
print('AyatanaAppIndicator3 available')
PY

# Run in the foreground to see tracebacks
.venv/bin/python RPCA.py
```

If `gi` is missing from the venv, recreate the venv with `--system-site-packages` so it can see the distro's PyGObject, or install PyGObject into the venv itself.

---

## Related pages

- [Discord Presence](Discord-Presence.md) — what the worker publishes.
- [Configuration](Configuration.md) — log path, timers, tray changes.
- [Troubleshooting](Troubleshooting.md) — tray and detach failures.
