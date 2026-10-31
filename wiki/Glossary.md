# Glossary

Terms used throughout the project and documentation.

---

## A–C

**AppIndicator / StatusNotifierItem**
A DBus-based system-tray protocol used by KDE, GNOME (with an extension), and other desktops. `pystray` uses it via the `appindicator` backend.

**Backend (pystray)**
The platform-specific implementation pystray uses to create a tray icon. This project forces `appindicator`. The environment variable must be set before importing pystray.

**Battle**
The state where `MechArena.exe` exists and has at least one open UDP socket. See [Game State Detection](Game-State-Detection.md).

**Buttons (Discord Rich Presence)**
Clickable links on a presence card. Discord allows up to two. This project uses one "Download Mech Arena" button.

**Client ID**
The Discord application ID used by `pypresence` to identify the presence. It is public, not a secret.

**Closed**
The state where no matching game process exists (`STATE_CLOSED`).

**CPC (Control Point Clash)**
A Mech Arena mode with capturable beacons. Detected by a bright central HUD cluster.

**Crop geometry**
An ImageMagick string of the form `WIDTHxHEIGHT+X+Y`, used to capture a sub-region of the game window.

---

## D–G

**Daemon**
A long-running background process. Here, `RPCA.py` or `MechArena.py` running its polling loop.

**Detached mode**
Running with `--detached`: stdio redirected to `/dev/null`, no controlling terminal, logging to a file. Entered via the tray's Dispatch item or by passing the flag manually.

**DM (Deathmatch)**
A team mode with score plates on the wings of the HUD. Detected by bright edges or a centre/edge brightness ratio ≤ 0.88.

**FFA (Free-For-All)**
A free-for-all mode with a dim HUD profile. Detected when centre brightness is below 95.

**HUD**
Heads-up display: the on-screen score, beacon, and status elements. Mode detection samples a 440×45 strip at the top centre of a 1920×1080 window.

**HUD_CROP_GEOM**
The constant that defines the HUD crop. Default: `440x45+740+50`.

---

## I–M

**ImageMagick `import`**
A command-line X11 screenshot tool. The daemon uses `import -window <id> -crop <geometry> png:-` to capture the HUD into a pipe.

**IPC (Inter-Process Communication)**
The local socket Discord exposes for Rich Presence. `pypresence` connects to a `discord-ipc-N` socket.

**Locked mode**
The mode string stored after the first successful HUD read. It is not re-evaluated for the rest of the match.

**Menu**
The state where the game process exists but has no open UDP socket (`STATE_MENU`). Covers launcher, login, hangar, results, and settings.

**Mode**
A game mode: Deathmatch, Control Point Clash, Free-For-All, or the generic "In Battle".

**MODE_LOCK_DELAY**
Seconds between entering battle and the first HUD read. Default: 15.

---

## P–R

**pypresence**
The Python library that implements Discord Rich Presence over the local IPC socket.

**psutil**
A cross-platform process and system utility library. Used to find `MechArena.exe` and inspect its UDP sockets.

**pystray**
The Python library that creates the system-tray icon and menu.

**Presence**
The card shown on a Discord profile: details, state, image, buttons, and timers.

**Proton**
Valve's Wine-based compatibility layer for Steam. The docs say "Wine/Proton" because the process behaviour is the same for this project.

**`raddr`**
The remote address of a socket. `TestingTools/RPCdaemon.py` requires a non-empty `raddr` to consider a UDP socket a battle; production does not.

**Results window**
The 10-second period after a battle where the presence says "Viewing Results". Controlled by `RESULTS_DISPLAY_DURATION`.

**Rich Presence**
Discord's feature for displaying what a user is doing, including images and buttons.

---

## S–W

**`SIGHUP`**
The hangup signal sent when a terminal closes. `RPCA.py` ignores it so the daemon survives.

**Session timer**
`session_start`, set when the game is first detected. Used as the `start` value in menu and results presence so the elapsed counter continues across the session.

**`STATE_CLOSED` / `STATE_MENU` / `STATE_BATTLE`**
The three game states, numbered 0, 1, and 2.

**Tray**
The system tray / status notifier area where the icon and menu live.

**UDP heuristic**
Treating the presence of any UDP socket on the game process as "in battle". Cheap, but can produce false positives and negatives.

**Unity**
The engine Mech Arena is built with. Research tools search for Unity scene, component, and asset names.

**UnityPy**
A Python library for reading Unity asset bundles and cache files. Used by `StripAssets.py`.

**Wine**
The compatibility layer used to run the Windows game on Linux. The game process appears as `MechArena.exe` in `psutil`.

**XWayland**
The X11 compatibility layer in a Wayland session. Wine windows are XWayland windows, which is why `xwininfo` and `import` can see them.

**`xwininfo`**
An X11 utility that lists windows. Used to find the "Mech Arena" window ID.

---

## Related pages

- [Home](Home.md)
- [Architecture](Architecture.md)
- [Game State Detection](Game-State-Detection.md)
- [Mode Detection](Mode-Detection.md)
- [Discord Presence](Discord-Presence.md)
