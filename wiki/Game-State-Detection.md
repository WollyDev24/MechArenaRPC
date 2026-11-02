# Game State Detection

The daemon needs to answer one question every couple of seconds: **is Mech Arena closed, sitting in a menu, or in an active match?**

It uses two signals only:

1. Does a process matching `[process] name` exist (default `mecharena.exe`)?
2. Does that process have any open UDP sockets?

No window titles, CPU usage, or memory reads are involved.

---

## The three states

```python
STATE_CLOSED = 0
STATE_MENU   = 1
STATE_BATTLE = 2
```

| State | Meaning | Typical situation |
| --- | --- | --- |
| `STATE_CLOSED` | No matching process | Game not launched, or fully exited. |
| `STATE_MENU` | Process exists, no UDP socket | Launcher, login, hangar, results, settings. |
| `STATE_BATTLE` | Process exists, at least one UDP socket | Matchmaking/lobby or an actual battle. |

---

## Algorithm

```python
def get_mech_state():
    for proc in psutil.process_iter(['name']):
        try:
            name = proc.info['name']
            if name and PROCESS_NAME.lower() in name.lower():
                connections = proc.net_connections(kind='udp')
                if len(connections) > 0:
                    return STATE_BATTLE
                return STATE_MENU
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return STATE_CLOSED
```

`PROCESS_NAME` comes from `[process] name` in the config.

### Step by step

1. **Iterate all processes.** `psutil.process_iter(['name'])` is a reasonably cheap generator. Only the `name` field is requested, so psutil does not read the full process metadata.
2. **Match the game process.** The configured substring is compared case-insensitively, so `mecharena.exe` accepts `MechArena.exe` and similar Wine-reported names. Keeping the `.exe` suffix avoids matching unrelated processes that merely contain "mecharena".
3. **First match wins.** The function returns as soon as it finds a matching process. If several exist (rare, e.g. a stale Wine process), the first one encountered decides the state.
4. **Read UDP sockets.** `proc.net_connections(kind='udp')` returns UDP endpoints owned by that process. If the list is non-empty, assume a battle.
5. **Handle permission errors.** Other users' processes can raise `AccessDenied`. Those are skipped. A matching game process that raises `AccessDenied` is effectively ignored, and detection may fall through to `STATE_CLOSED`. Run the daemon as the same user that runs Wine to avoid this.
6. **No match means closed.** Returning `STATE_CLOSED` is also the safe default when psutil cannot inspect anything.

---

## Why UDP?

Mech Arena is a networked game running under Wine. In the hangar it may keep the login/HTTP connection open, but joining a match opens UDP endpoints to game servers. The presence of a UDP socket is a simple, cheap proxy for "the game is doing something match-related".

Advantages:

- No special privileges.
- No packet inspection.
- Works regardless of the game's internal scene names.
- Same code path on any Linux distro.

Trade-offs:

- **Any** UDP socket is treated as battle. A launcher, voice chat, or an unrelated socket owned by the same process could create a false positive.
- A battle that uses only TCP, or a matchmaking state before sockets open, would be a false negative.
- The socket may remain open briefly after a match, delaying the return to the menu.
- The production code only checks `len(connections) > 0`, not whether the socket has a remote address. The prototype in `TestingTools/RPCdaemon.py` is stricter:

```python
for conn in connections:
    if conn.raddr and conn.status == psutil.CONN_NONE:
        return True
```

  This requires an actual peer address. It is a good improvement if you see false positives, but it was not adopted in the production daemon.

---

## State transitions in practice

```
                 game process appears
CLOSED ───────────────────────────────────► MENU
   ▲                                          │
   │                                          │ UDP socket opens
   │ game process exits                       ▼
   └────────────────────────────────────── BATTLE
                                              │
                                              │ UDP socket closes
                                              ▼
                                            MENU
```

The worker does not act on every poll; it compares the new state with `last_state` and only runs the transition logic when they differ.

Important detail: `last_state` is only updated inside `if rpc is not None:`. If Discord is unavailable, state changes are not recorded. When Discord becomes available, the worker still sees the difference from its last recorded state and updates correctly.

---

## Window discovery

Mode detection needs the game window even though state detection does not. `get_mech_window_id()` runs `xwininfo -root -tree` and scans for a line containing the configured `[window] title` (default `"Mech Arena"`):

```text
0x4a00001 "Mech Arena": ("mecharena.exe" "MechArena.exe")  1920x1080+0+0  +0+0
```

It extracts the first hexadecimal token via `re.search(r"(0x[0-9a-fA-F]+)", line)`.

Notes:

- The title match is exact and case-sensitive, and includes the surrounding quotes.
- On Wayland, Wine windows are exposed through XWayland, so `xwininfo` can see them.
- If the game runs in a Wine virtual desktop, the outer window may have a different title or size.
- If multiple windows match, the first one in tree order is used. A splash screen with the same title could be selected.
- The function is only called after the `mode_lock_delay` battle delay, so transient loading windows are usually gone by then.

Manual check:

```bash
xwininfo -root -tree | grep -i 'Mech Arena'
```

If that prints nothing, window lookup fails, so each HUD burst logs `lookup_retries` retries and then leaves mode detection unlocked for the next poll.

---

## Verifying state detection manually

### Is the process visible?

```bash
pgrep -af -i mecharena
```

You should see something like a Wine process whose command line includes `MechArena.exe`.

### Does it have UDP sockets?

```bash
ss -u -p | grep -i mech
```

or, if you prefer psutil directly:

```bash
python - <<'PY'
import psutil
for p in psutil.process_iter(['name']):
    if p.info['name'] and 'mecharena.exe' in p.info['name'].lower():
        print(p.pid, p.info['name'])
        for c in p.net_connections(kind='udp'):
            print('  ', c)
PY
```

### Is the window visible to X11?

```bash
xwininfo -root -tree | grep -i 'Mech Arena'
```

### What does the daemon see?

Run `RPCA.py` in the foreground and watch the log. State changes are printed as:

```text
[2026-10-31 12:00:00] Status: In Battle (Waiting 15s to detect mode...)
[2026-10-31 12:00:15] HUD Analysis: Center=..., Edge=..., Ratio(C/E)=...
[2026-10-31 12:00:15] Locked Mode: Control Point Clash
```

Or tail the file:

```bash
tail -f ~/.cache/mech_arena_rpc.log
```

---

## Differences between the production daemon and the prototype

| Behaviour | `RPCA.py` / `MechArena.py` | `TestingTools/RPCdaemon.py` |
| --- | --- | --- |
| Matching process | configured `[process] name` (default `mecharena.exe`) | `"mecharena" in name.lower()` |
| UDP condition | `len(connections) > 0` | at least one socket with `conn.raddr` |
| Poll interval | `timing.poll_interval` (2 s), `MechArena.py` 3 s | 2 s |
| HUD detection | Once, after `mode_lock_delay`, then locked | On every battle poll |
| Output | Discord presence + log | Console state changes |

The prototype was used to calibrate the screen heuristics. It is a useful diagnostic tool when the production daemon's state disagrees with what you see.

---

## Edge cases and known issues

| Situation | Effect | Mitigation |
| --- | --- | --- |
| Game process is owned by another user | `AccessDenied`; may appear closed | Run the daemon as the same user as Wine. |
| Stale `MechArena.exe` process | Ruins state detection | Kill the stale process. |
| UDP socket opens in the launcher | False "battle" | Use the prototype's `raddr` check. |
| Socket stays open after the match | Longer "battle" state | Wait for it to close, or add a timeout. |
| Game uses TCP only | Never enters battle | Extend the socket check. |
| Window title changes | Mode detection fails | Update `[window] title`. |
| Game minimised | Screenshot may be black or fail | Keep the game visible on the XWayland display. |
| Wine virtual desktop | Crop coordinates may shift | Capture the virtual desktop or adjust the crop. |
| Multiple matching windows | Wrong window captured | Make the title match more specific. |

---

## Related pages

- [Mode Detection](Mode-Detection.md) — what happens after `STATE_BATTLE`.
- [Discord Presence](Discord-Presence.md) — how state transitions become presence updates.
- [Testing Tools](Testing-Tools.md) — `RPCdaemon.py` and the memory/network probes.
