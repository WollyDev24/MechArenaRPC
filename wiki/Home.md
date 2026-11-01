# Mech Arena RPC Wiki

This wiki explains how the Mech Arena Discord Rich Presence daemon works, why it is built the way it is, and how to adapt or debug it.

The project has two runnable entry points:

- **`RPCA.py`** — the full tray daemon. Process detection, HUD mode detection, config reload, HUD calibration, results screen, logging, and terminal detaching.
- **`MechArena.py`** — a minimal console daemon with process detection only.

`settings.py` holds the TOML config schema, validation, defaults, and CLI overrides used by `RPCA.py`.

Everything in **`TestingTools/`** is research code. It is not imported by either entry point.

---

## Start here

| Page | What it covers |
| --- | --- |
| [Architecture](Architecture.md) | Components, threads, data flow, and the reasoning behind the design. |
| [Game State Detection](Game-State-Detection.md) | How the daemon decides the game is closed, in the menu, or in battle. |
| [Mode Detection](Mode-Detection.md) | The HUD crop, brightness maths, thresholds, and the calibration wizard. |
| [Discord Presence](Discord-Presence.md) | Presence payloads, timers, state transitions, and reconnects. |
| [Tray and Daemon](Tray-and-Daemon.md) | Tray menu, config reload/calibration, log viewer, detach/dispatch, shutdown, and autostart. |
| [Configuration](Configuration.md) | The TOML config file, every key, CLI overrides, and safe changes. |
| [Testing Tools](Testing-Tools.md) | All 17 research scripts, grouped by technique, with usage notes. |
| [Troubleshooting](Troubleshooting.md) | Symptom-driven diagnostics and known limitations. |
| [Glossary](Glossary.md) | Quick definitions of the terms used here. |

---

## The 30-second version

1. Every `timing.poll_interval` seconds (default 2) the daemon asks `psutil` whether `mecharena.exe` exists. Both the process name and the window title are configurable.
2. If it exists and has an open UDP socket, the state is **battle**; otherwise it is **menu**.
3. On entering battle, it immediately publishes a generic "In Battle" presence.
4. After `hud.mode_lock_delay` (default 15 seconds) it captures a `440x45` HUD strip with ImageMagick, measures grayscale brightness in the centre and on the edges, and classifies the mode.
5. When the UDP socket disappears, it shows "Viewing Results" for `timing.results_display_duration` (default 10 seconds), then returns to "In Hangar".
6. All presence updates go through `pypresence` to the local Discord IPC socket. A tray icon shows the current status, reloads the config, opens the calibration wizard, and can detach the process from the terminal.

Settings come from `~/.config/mech-arena-rpc/config.toml`, created on first launch. CLI flags override the file; the file overrides built-in defaults.

```
CLOSED ──game starts──► MENU ──UDP socket opens──► BATTLE
   ▲                      ▲                          │
   │                      └────UDP socket closes─────┘
   │                          (results for 10 s)
   └──────────────── game exits ─────────────────────┘
```

---

## Design principles

| Principle | How it is applied |
| --- | --- |
| **Do not touch the game** | Runtime uses only process metadata, a UDP socket count, and an X11 screenshot. No injection, no memory reads, no packet capture. |
| **Fail soft** | Window lookup, screenshot capture, socket inspection, and Discord connect/clear are wrapped in `try/except`; a failed HUD lookup is retried up to 3 times (2 s apart) before normal polling resumes. Invalid config fields fall back to defaults with a log warning. |
| **One read per match** | Mode detection is locked after the first successful read, so score changes and kill feeds cannot make the presence flicker. |
| **Survive the terminal** | `SIGHUP` is ignored and Dispatch relaunches the daemon in a new kernel session with stdio redirected. |
| **Keep the UI thread clean** | The tray event loop owns the main thread; all game polling runs in a daemon worker thread. |

---

## Files and responsibilities

| File | Runtime? | Responsibility |
| --- | --- | --- |
| `RPCA.py` | ✅ | Production tray daemon. |
| `settings.py` | ✅ | TOML config defaults, validation, load/save, CLI overrides. |
| `MechArena.py` | ✅ | Minimal alternative daemon. |
| `TestingTools/RPCdaemon.py` | ❌ | Tray-less prototype of the detection loop, with slightly different thresholds. |
| `TestingTools/DetectMode.py` | ❌ | OCR-based mode classifier. |
| `TestingTools/CountBeacons.py` | ❌ | Column-brightness beacon counter. |
| `TestingTools/DumpStrip.py` | ❌ | ASCII brightness profile for calibration. |
| `TestingTools/InspectUHD.py` | ❌ | RGB colour counting of the HUD. |
| `TestingTools/LiveStats.py` | ❌ | Saves ally/enemy CPC score crops. |
| `TestingTools/FindScene.py` | ❌ | Unity scene/mode string scanner. |
| `TestingTools/TestMode.py` | ❌ | Memory-based mode classifier. |
| `TestingTools/TestSceneQuick.py` | ❌ | Fast scene-tag scanner. |
| `TestingTools/TestBeaconObject.py` | ❌ | Unity beacon class scanner. |
| `TestingTools/CompareModes.py` | ❌ | Compares mode signature frequencies. |
| `TestingTools/AnalyzeGame.py` | ❌ | General memory string search. |
| `TestingTools/StripAssets.py` | ❌ | Unity asset/icon extractor. |
| `TestingTools/SniffHandshake.py` | ❌ | Raw UDP capture on port 7015. |
| `TestingTools/SniffLoopback.py` | ❌ | Loopback TCP capture on ports 5200/50306. |
| `TestingTools/TestNet.py` | ❌ | Earlier loopback capture variant. |
| `TestingTools/TestCrop.py` | ❌ | `mss` full-screen capture. |

---

## Reading order

- **Just want to run it?** Read the repository `README.md`, then [Troubleshooting](Troubleshooting.md).
- **Want to understand the state machine?** [Architecture](Architecture.md) → [Discord Presence](Discord-Presence.md).
- **Mode detection is wrong?** [Mode Detection](Mode-Detection.md) → [Configuration](Configuration.md).
- **Curious about the research?** [Testing Tools](Testing-Tools.md).
- **Debugging the tray or detach mode?** [Tray and Daemon](Tray-and-Daemon.md).

---

## Scope and caveats

- This is an unofficial project, not a game API integration.
- The full tray daemon is Linux/XWayland-specific.
- The default HUD crop assumes 1920×1080 and the default UI scale; the calibration wizard adapts it.
- `MechArena.py` does not read the config file.
- The research tools may need root, may break with game updates, and may conflict with the game's terms of service.
