# Discord Presence

The daemon publishes presence through [`pypresence`](https://github.com/qwertyquerty/pypresence), which talks to the locally running Discord client over its IPC socket. This page covers the connection, the state machine, the exact payloads, and the timing semantics.

---

## Connection lifecycle

### Client ID

```python
CLIENT_ID = "1565766221813776505"
```

This identifies the Discord application whose name, icon, and assets are shown in the presence card. It is not a secret.

To use your own application:

1. Create an application at the Discord Developer Portal.
2. Copy its Application ID into `CLIENT_ID`.
3. Upload a Rich Presence asset named `mech_arena_logo` (or change the `large_image` values).

### Connect

```python
rpc = Presence(CLIENT_ID)
rpc.connect()
```

`connect()` finds the Discord IPC socket, performs the handshake, and prepares the pipe. If it fails, the exception is caught and `rpc` stays `None`; the worker retries on the next poll (2 seconds later).

Caught exceptions:

| Exception | Meaning |
| --- | --- |
| `DiscordNotFound` | No Discord IPC socket was found. |
| `InvalidID` | The client ID was rejected. |
| `ConnectionRefusedError` | The socket exists but the connection was refused. |

Other exceptions from pypresence are not caught at connect time and could terminate the worker. In practice the three above cover the common cases.

### Update

`rpc.update(...)` sends a `SET_ACTIVITY` frame with the presence payload. It is called only on state transitions, not every poll.

### Clear and close

On game close:

```python
rpc.clear()
rpc.close()
```

Both are wrapped in `try/except`. `clear()` removes the presence; `close()` releases the IPC pipe. The worker then resets `rpc`, timers, and the locked mode, and waits for the game to return.

On daemon shutdown, the worker attempts the same cleanup after its loop ends. Because the worker is a daemon thread, an immediate process exit (e.g. Quit or Dispatch) may terminate it before cleanup runs. Discord also removes presence when the IPC connection closes, so the card usually disappears anyway.

---

## Discord IPC location

On Linux, pypresence looks for a Unix socket named `discord-ipc-0`, `discord-ipc-1`, … in `XDG_RUNTIME_DIR` (and some fallback locations). Typical paths:

```text
$XDG_RUNTIME_DIR/discord-ipc-0
$XDG_RUNTIME_DIR/app/com.discordapp.Discord/discord-ipc-0
```

Check with:

```bash
ls -l "$XDG_RUNTIME_DIR"/discord-ipc-* 2>/dev/null
find "$XDG_RUNTIME_DIR" -name 'discord-ipc-*' 2>/dev/null
```

If Discord is installed as a sandboxed Flatpak or Snap, it may not see the same runtime directory as the daemon. You may need to grant filesystem access or run the daemon inside the same sandbox. This is a common cause of "Discord not found".

---

## Presence payloads

All updates share:

```python
large_image="mech_arena_logo"
large_text="Mech Arena"
buttons=DOWNLOAD_BUTTONS
```

where:

```python
DOWNLOAD_BUTTONS = [
    {"label": "Download Mech Arena", "url": "https://plarium.com/en/game/mech-arena/"}
]
```

The `details` and `state` lines are the two text rows in the Discord card; `large_image` is the big artwork; `start` drives the elapsed-time counter.

### Battle start

Triggered when `STATE_BATTLE` is first observed.

```python
rpc.update(
    details="In Battle",
    state="Combat Session",
    start=battle_start,
    large_image="mech_arena_logo",
    large_text="Mech Arena",
    buttons=DOWNLOAD_BUTTONS
)
```

### Mode locked (15 s later)

```python
rpc.update(
    details=f"In Battle ({locked_mode})",
    state="Combat Session",
    start=battle_start,
    large_image="mech_arena_logo",
    large_text="Mech Arena",
    buttons=DOWNLOAD_BUTTONS
)
```

`locked_mode` is one of `Deathmatch`, `Control Point Clash`, `Free-For-All`, or the fallback `In Battle` (which produces the cosmetic `In Battle (In Battle)`).

### Results window

Triggered when the state changes from `BATTLE` to `MENU`.

```python
rpc.update(
    details="Viewing Results",
    state=f"Post-Match{last_mode_label}",
    start=session_start,
    large_image="mech_arena_logo",
    large_text="Mech Arena",
    buttons=DOWNLOAD_BUTTONS
)
```

`last_mode_label` is `" (Deathmatch)"`, `" (Control Point Clash)"`, `" (Free-For-All)"`, or an empty string if no mode was locked. The presence holds for `RESULTS_DISPLAY_DURATION = 10` seconds.

### Hangar

Triggered after the results window, or on any normal menu transition.

```python
rpc.update(
    details="In Hangar",
    state="Main Menu",
    start=session_start,
    large_image="mech_arena_logo",
    large_text="Mech Arena",
    buttons=DOWNLOAD_BUTTONS
)
```

### Cleared

Triggered when the game process disappears. `rpc.clear()` removes the card; `rpc.close()` closes the pipe.

---

## State machine

```text
                         ┌─────────────┐
                         │   CLOSED    │
                         └──────┬──────┘
                                │ game process appears, Discord connects
                                ▼
                         ┌─────────────┐
              ┌─────────►│    MENU     │◄──────────────┐
              │          └──────┬──────┘               │
              │                 │ UDP socket opens      │ results timer expires
              │                 ▼                       │
              │          ┌─────────────┐               │
              │          │   BATTLE    │               │
              │          └──────┬──────┘               │
              │                 │ UDP socket closes    │
              │                 ▼                       │
              │          ┌─────────────┐               │
              │          │  RESULTS    │───────────────┘
              │          │  (10 s)     │
              │          └─────────────┘
              │                 │
              └─────────────────┘ game process exits
```

In code, the machine is the `if/elif` block inside `rpc_worker()`:

```python
if state == STATE_BATTLE:
    ...
elif state == STATE_MENU:
    ...
elif state == STATE_CLOSED and state != last_state:
    ...
last_state = state
```

The extra flags are:

| Variable | Meaning |
| --- | --- |
| `last_state` | Previous game state, used to detect transitions. |
| `session_start` | Unix timestamp when the game was first seen. Drives the menu/results timer. |
| `battle_start` | Unix timestamp when the current battle began. Drives the match timer. |
| `locked_mode` | Mode string, or `None` until detected. |
| `results_until` | Unix timestamp when the 10-second results window ends. |

---

## Timers

Discord renders `start` as an **elapsed** counter ("12:34 elapsed"), not a countdown.

| Presence | `start` value | Effect |
| --- | --- | --- |
| Battle | `battle_start` | Counter resets each match. |
| Results | `session_start` | Counter continues from the gaming session. |
| Hangar | `session_start` | Counter continues for the whole game session. |

`session_start` is set once, the first time the game is detected, and cleared when the game closes. `battle_start` is set per battle and cleared when the battle ends.

### Results timer detail

The results state is entered only when `last_state == STATE_BATTLE` and the new state is `STATE_MENU`. It sets:

```python
results_until = now + RESULTS_DISPLAY_DURATION
```

On subsequent menu polls:

- If `results_until` is `None`, normal menu handling applies.
- If `now >= results_until`, the presence switches to "In Hangar" and `results_until` is cleared.
- If the player starts another battle before the 10 seconds elapse, the battle branch runs and resets `results_until` to `None`.

The results state does not start if the daemon was already in the menu when the battle ended (e.g. it was started mid-session and missed the transition).

---

## Reconnection behaviour

There is no background reconnect task. Reconnection happens naturally in the main loop:

1. `state != STATE_CLOSED and rpc is None` → try `Presence(...).connect()`.
2. On failure, `rpc` stays `None`.
3. Next poll (2 s), try again.

This recovers connections that fail when they are attempted — for example, Discord started after the game. It does **not** fully handle a Discord restart: the existing `rpc` object is not reset, and the next `rpc.update()` may raise. Because updates are not wrapped in `try/except`, that can terminate the worker thread. If presence stops after a Discord restart, restart the daemon.

Caveat: `last_state` is updated only inside the `if rpc is not None:` block. While Discord is unavailable, state transitions are not recorded. When the connection succeeds, the worker compares the current state with the last recorded one and emits the appropriate update. This is usually desirable, but it means a battle that starts and ends entirely while Discord is down is not replayed. For the same reason, if the game closes while Discord is disconnected, the session timers and `last_state` may not be reset.

---

## Rate limits

Discord rate-limits presence updates (roughly 5 updates per 20 seconds per client). The production daemon updates only on transitions:

- connect + battle start,
- one mode lock,
- results,
- hangar,
- clear on close.

That is far below the limit. If you lower `time.sleep(2)` or add frequent updates, keep the rate limit in mind.

---

## Assets and buttons

### Large image

`large_image="mech_arena_logo"` refers to an asset key uploaded to the Discord application. If the asset does not exist, Discord may show a placeholder or nothing. Upload a 512×512 (or larger) image with that exact key, or change the key in all `rpc.update()` calls.

### Buttons

Buttons are included in every presence payload. They do not require uploaded assets. Discord shows up to two buttons; this project uses one:

```python
{"label": "Download Mech Arena", "url": "https://plarium.com/en/game/mech-arena/"}
```

Buttons are not shown in some Discord clients or when the user has certain privacy settings. That is a Discord limitation, not a daemon issue.

---

## Testing presence without the game

`MechArena.py` is the smallest way to verify that Discord IPC works. Temporarily change its `get_mech_state()` to return `STATE_MENU`, run it, and see whether a card appears.

A more direct smoke test:

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

If this fails, fix Discord IPC before debugging the daemon.

---

## Known quirks

| Quirk | Explanation |
| --- | --- |
| Presence can show "In Battle (In Battle)" | The mode fallback string is treated as a valid lock. |
| Results screen may be skipped | It requires an observed `BATTLE → MENU` transition. |
| Presence may linger briefly after Quit | The daemon thread may exit before `clear()`; the IPC socket closing normally removes it. |
| Discord restart can stop updates | The existing `rpc` object is not reset, and an unwrapped `rpc.update()` may raise and kill the worker. Restart the daemon. |
| Game close while Discord is down is not handled | `STATE_CLOSED` handling is inside `if rpc is not None`, so timers and `last_state` can stay stale. |
| No presence while game is closed | The worker only connects when `state != STATE_CLOSED`. |

---

## Related pages

- [Architecture](Architecture.md) — where the state machine sits in the process.
- [Game State Detection](Game-State-Detection.md) — what drives `STATE_*`.
- [Mode Detection](Mode-Detection.md) — what fills `locked_mode`.
- [Troubleshooting](Troubleshooting.md) — Discord IPC diagnostics.
