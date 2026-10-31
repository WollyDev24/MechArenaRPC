# Testing Tools

`TestingTools/` is the research lab for this project. It contains 17 standalone scripts that were used to answer questions like:

- Can the game mode be read from process memory?
- Does the HUD contain a reliable visual signature?
- Can OCR identify the mode?
- What network ports and payloads are involved?
- Which Unity assets correspond to the mode icons?

None of these scripts are imported by `RPCA.py` or `MechArena.py`. They are kept for reference, debugging, and recalibration.

> **Safety first.** Some tools read another process's memory or open raw sockets. That can require root or relaxed `ptrace` permissions, and it may conflict with the game's terms of service or anti-cheat. Use them only on your own machine and only if you understand the risk. The production daemon deliberately avoids both techniques.

---

## Summary

| Script | Category | What it does | Privileges |
| --- | --- | --- | --- |
| `RPCdaemon.py` | Prototype | Tray-less detection loop, prints state changes. | Normal |
| `DumpStrip.py` | Screen | ASCII brightness profile of the HUD strip. | Normal + X11 |
| `CountBeacons.py` | Screen | Counts bright column peaks in the HUD. | Normal + X11 |
| `InspectUHD.py` | Screen | Counts cyan/red/gold HUD pixels. | Normal + X11 |
| `DetectMode.py` | Screen + OCR | Tesseract OCR of the HUD, keyword classifier. | Normal + X11 + tesseract |
| `LiveStats.py` | Screen | Saves ally/enemy CPC score crops. | Normal + X11 |
| `TestCrop.py` | Screen | Full-screen capture with `mss`. | Normal + display |
| `FindScene.py` | Memory | Scene/mode strings, ASCII and UTF-16LE. | `/proc/<pid>/mem` access |
| `TestSceneQuick.py` | Memory | Fast scene-tag scan of small heaps. | `/proc/<pid>/mem` access |
| `TestMode.py` | Memory | Memory-based mode classifier. | `/proc/<pid>/mem` access |
| `CompareModes.py` | Memory | Compares mode signature frequencies. | `/proc/<pid>/mem` access |
| `TestBeaconObject.py` | Memory | Counts Unity beacon class names. | `/proc/<pid>/mem` access |
| `AnalyzeGame.py` | Memory | General ASCII string search. | `/proc/<pid>/mem` access |
| `SniffHandshake.py` | Network | Raw UDP capture on port 7015. | root / `CAP_NET_RAW` |
| `SniffLoopback.py` | Network | Loopback TCP capture on 5200/50306. | root / `CAP_NET_RAW` |
| `TestNet.py` | Network | Earlier loopback TCP variant. | root / `CAP_NET_RAW` |
| `StripAssets.py` | Assets | Extracts Unity textures/sprites. | Normal |

Prerequisites for the optional stack:

```bash
pip install pytesseract UnityPy mss numpy opencv-python-headless
sudo apt install tesseract-ocr   # or your distro equivalent
```

Several scripts hardcode paths, window IDs, or a username. Read them before running; they are research code, not polished utilities.

---

## 1. Detection prototype

### `RPCdaemon.py`

The closest thing to a production daemon without the production dependencies. It has no Discord, no tray, and no logging framework; it prints state changes to the terminal.

```
POLL_INTERVAL = 2.0
HUD_CROP_GEOM = "440x45+740+50"
```

Flow:

1. Find a process whose name contains `mecharena` (note: no `.exe` here).
2. `has_active_battle_connection()` requires at least one UDP connection with a remote address (`conn.raddr`) and `status == psutil.CONN_NONE`.
3. If in battle, resolve the window ID and capture the HUD.
4. Classify with different thresholds from production:

   ```python
   if edge_avg >= 120:                          return "Deathmatch"
   if center_avg >= 85 and center_avg > edge_avg: return "Control Point Clash"
   if center_avg < 85 and edge_avg < 60:        return "Free-For-All"
   return "In Battle"
   ```
5. Print `State Changed: In Battle (mode)` or `State Changed: In Hangar`.

Why keep it?

- It shows the raw classification on every poll, so you can watch thresholds behave without waiting for a match to end.
- Its `raddr` check is stricter than production and is a good reference if you see false battle states.
- Its thresholds are an earlier calibration; comparing them with production shows how the heuristics evolved.

Run:

```bash
python TestingTools/RPCdaemon.py
```

---

## 2. Screen analysis

These scripts all capture the game window with ImageMagick (`import`) and analyse pixels with Pillow. They assume an XWayland/X11 display.

### `DumpStrip.py`

The main calibration tool.

- Fixed window ID `0x4a00001` and crop `440x45+740+50` (edit both if needed).
- Converts to grayscale.
- Divides the width into 40 buckets.
- Prints a 40-character ASCII profile (`#` for bright, `.` for dim) and the bucket values.
- Saves `beacon_strip_debug.png` in `/home/wolly/DiscordRPC/`.

Example:

```text
--- Horizontal Brightness Profile (Left -> Right) ---
[####............................####]
Values (40 buckets): [ ... ]
```

Use it to confirm the crop contains the score/beacon strip and to see whether the centre or edges dominate.

### `CountBeacons.py`

An earlier attempt at counting CPC beacons by looking for bright columns.

- Fixed window `0x4a00001`, crop `440x35+740+55`.
- Saves `beacon_strip.png`.
- Computes per-column average brightness.
- Threshold = overall average + 15.
- Counts contiguous runs above the threshold ("peaks").
- `peaks >= 4` ⇒ CPC, otherwise "Deathmatch / FFA".

This works when the beacon indicators are distinct bright blobs, but map lighting and score plates can create false peaks. It was superseded by the centre/edge brightness ratio.

### `InspectUHD.py`

A colour-counter for the top HUD.

- Resolves the window ID dynamically (falls back to `0x4a00001`).
- Crops `500x120+710+0`.
- Saves `current_hud.png`.
- Counts RGB pixels matching:
  - **Cyan**: `b > 150`, `g > 120`, `r < 100` — player/beacon UI.
  - **Red**: `r > 170`, `g < 80`, `b < 80` — enemy/beacon UI.
  - **Gold**: `r > 190`, `g > 140`, `b < 70` — FFA badge.

Output is just counts. Compare counts across modes to see whether a colour signature is usable. The production daemon uses grayscale because it is simpler and more robust to HUD skins/settings.

### `DetectMode.py`

The OCR experiment.

- Captures `460x100+730+10` from the window titled `"Mech Arena"` (by title, not ID).
- Converts to grayscale and binarises at 175.
- Runs Tesseract with `--psm 6` (single uniform block).
- Classifies lowercase text:
  - FFA keywords: `ffa`, `rank`, `leader`, `solo`, `1st`, `2nd`, `3rd`.
  - Deathmatch: a score-like regex `\d+\s*[\:\-\®\©\*\.\_\|vV]\s*\d+`.
  - CPC: a lone letter `a`–`e`, or `cpc`, `beacon`, `capture`, `%`.
  - Fallback: three or more letters ⇒ CPC.
  - Otherwise "In Battle".

Why it was rejected: the HUD font is stylised, small, anti-aliased, and often moving. Tesseract produced inconsistent strings, and the fallback logic could flip modes on a single misread character. The script is useful for seeing what OCR actually extracts.

### `LiveStats.py`

A capture-only utility for CPC score regions.

- Resolves the window ID dynamically.
- Saves:
  - `cpc_ally_pct.png` — crop `65x32+710+45`.
  - `cpc_enemy_pct.png` — crop `65x32+1145+45`.

There is no analysis. Open the images to read ally/enemy scores or percentages manually, or feed them to your own OCR/threshold code. Useful when designing score-aware features.

### `TestCrop.py`

The simplest screen tool:

```python
with mss.MSS() as sct:
    full = sct.grab({"top": 0, "left": 0, "width": 1920, "height": 1080})
    img = Image.frombytes("RGB", full.size, full.bgra, "raw", "BGRX")
    img.save("/home/wolly/DiscordRPC/full_match.png")
```

Captures the full 1920×1080 screen and saves `full_match.png`. Use it to locate HUD elements and derive crop coordinates. On pure Wayland without XWayland, `mss` may capture nothing; use ImageMagick against the XWayland window instead.

---

## 3. Memory scanning

These scripts read `/proc/<pid>/maps` and `/proc/<pid>/mem` to look for Unity strings. They share a common pattern:

1. Find the PID of `mecharena`.
2. Iterate readable memory mappings.
3. Skip large blocks and special mappings (`/dev`, `[vvar]`, `[vdso]`).
4. Read chunks and search for ASCII or UTF-16LE tokens.
5. Count occurrences or collect unique matches.

### Access requirements

- The daemon/user must be allowed to read the game process's memory.
- On Linux with Yama, `ptrace_scope=1` restricts access to descendants. Reading `/proc/<pid>/mem` of a non-child may fail with `PermissionError`.
- Options: run the tool as the same user and check `cat /proc/sys/kernel/yama/ptrace_scope`, run the game as a child of the tool, or (not recommended) relax the scope or use elevated privileges.
- Wine processes are normal Linux processes, so the same rules apply.

### `FindScene.py`

- Scans `rw` mappings up to 30 MB.
- Searches ASCII with `Battle[A-Za-z0-9_]{2,30}|CPC_...|FFA_...|TDM_...`.
- Counts UTF-16LE occurrences of `ControlPoint`, `DeathMatch`, `FreeForAll`, `Beacon`, `5v5`, `2v2`.
- Prints detected scene names and frequencies.

This was used to confirm that Unity scene/mode names are present and to see which strings are stable enough to classify.

### `TestSceneQuick.py`

A faster, narrower scanner:

- Only private anonymous `rw-p` mappings with no pathname (`len(parts) <= 5`).
- Only 64 KB–8 MB blocks.
- Regex for `CPC_`, `FFA_`, `TDM_`, `DM_` tags with word boundaries.
- Prints the set of tags found.

Useful for a quick "what scene is loaded?" check, but it only sees ASCII tags in small heaps.

### `TestMode.py`

The memory-based classifier.

- Scans `rw` mappings up to 25 MB.
- Counts UTF-16LE `Beacon`.
- Collects ASCII `CPC|TDM|FFA|DeathMatch|Beacon` tags.
- Decision:

  ```python
  if beacon_count > 150 or any(t.startswith("CPC") for t in found_tags):
      "Control Point Clash"
  elif any(t.startswith("FFA") for t in found_tags):
      "Free-For-All"
  else:
      "Deathmatch (5v5 / 2v2)"
  ```

The absolute `150` threshold is empirical. It illustrates why memory scanning is fragile: counts depend on map, match length, allocator behaviour, and game version.

### `CompareModes.py`

Counts both ASCII and UTF-16LE occurrences of:

- `Beacon`
- `BattleEmblemControl`
- `BattleMessageNewKillLeader`
- `BattleEmblemFFA`
- `BattleEmblem5x5`
- `BattleEmblem2x2`

Scans `rw` mappings up to 30 MB and prints a frequency table. The intent was to find a signature that separates the three modes without a hardcoded count. It requires a sample from each mode to compare.

### `TestBeaconObject.py`

Looks for Unity component/class names rather than generic words:

- `BeaconController`
- `BeaconView`
- `CapturePointController`
- `ControlPointView`
- `BeaconIndicator`
- `BeaconCaptureZone`

It is strict about mappings: only `rw-p` private anonymous regions (`len(parts) <= 5`) up to 16 MB. Counts ASCII occurrences. This was an attempt to detect live beacon objects instead of scene-name strings.

### `AnalyzeGame.py`

The broadest and simplest scanner:

- Reads readable mappings (`perms.startswith('r')`) up to 50 MB.
- Skips `/dev`, `[vvar]`, `[vdso]`.
- Searches ASCII for `ControlPoint`, `DeathMatch`, `FreeForAll`, `Beacon`, `TeamDeathmatch`.
- Prints the set of strings found.

Use it as a first probe when you do not know what to look for.

### Why memory scanning is not in production

| Issue | Detail |
| --- | --- |
| Permissions | `/proc/<pid>/mem` access is restricted and user-dependent. |
| Stability | Counts and strings change with maps, updates, and allocator state. |
| Cost | Scanning tens of MB every poll is expensive. |
| Risk | Anti-cheat and terms of service may treat memory reads as suspicious. |
| Simplicity | A single screenshot provided enough signal for three coarse classes. |

---

## 4. Network probing

These scripts open raw sockets and parse packet headers manually. They are read-only: they capture traffic, they do not inject or modify packets.

### `SniffHandshake.py`

- Raw UDP socket (`AF_INET`, `SOCK_RAW`, `IPPROTO_UDP`).
- Requires root or `CAP_NET_RAW`.
- Parses the IPv4 header (IHL, source/destination IP) and UDP header (ports).
- Filters packets where the source or destination port is **7015**.
- Extracts printable ASCII strings of length ≥ 3 from the payload.
- Prints up to **8** matching packets with strings, then exits.

Observed use: inspecting the initial match handshake for plaintext mode/scene fields during the loading phase. Game traffic is often compressed or encrypted, so this is exploratory.

### `SniffLoopback.py`

- Raw TCP socket on the loopback interface.
- Parses IPv4 and TCP headers, including the data offset.
- Only considers `127.0.0.1 → 127.0.0.1`.
- Filters ports **5200** and **50306** (observed local IPC ports).
- Extracts printable text including JSON punctuation.
- Prints payloads containing keywords: `battle`, `mode`, `match`, `cpc`, `ffa`, `deathmatch`, `room`, `game`, `ticket`, `start`.
- Truncates output to 350 characters.

The idea was that the game client and a local service might exchange match metadata in JSON before the battle. The filter avoids keep-alive noise.

### `TestNet.py`

An earlier variant of `SniffLoopback.py` with the same raw TCP approach and ports. Differences:

- Slightly different printable-character regex (no spaces).
- Prints up to 200 characters.
- Keyword list lacks `room`, `ticket`, `start`.

It is kept for comparison; `SniffLoopback.py` is the more developed version.

### Privileges

```bash
sudo python TestingTools/SniffHandshake.py
```

or grant the capability to the Python binary (affects every script run with it, so prefer `sudo` for a one-off):

```bash
sudo setcap cap_net_raw+ep "$(readlink -f .venv/bin/python)"
```

Remove it afterwards with `sudo setcap -r ...`.

### Caveats

- Raw sockets see traffic for the whole host, not just the game. Do not capture more than you need.
- Packet formats and ports can change with updates.
- TLS/encryption will hide most useful fields.
- This approach was **not** adopted in production because it needs elevated privileges and is not reliable.

---

## 5. Unity assets

### `StripAssets.py`

Uses [`UnityPy`](https://github.com/K0lb3/UnityPy) to open Unity cache files and export textures/sprites.

Hardcoded paths:

```python
CACHE_DIR = Path.home() / ".wine/drive_c/users/wolly/AppData/LocalLow/Unity/Plarium_Mech Arena"
OUTPUT_DIR = Path.home() / "DiscordRPC/extracted_mode_icons"
```

Target folders:

- `ToBattleDialog_SD`
- `PolygonFFA01_SD`
- `RankedTournamentShared_SD`
- `MapSpaceSetCPC_SD`
- `HudDebug_SD`

For every file in those folders, it:

1. Loads the file with `UnityPy.load(file_path)`.
2. Iterates objects of type `Texture2D` or `Sprite`.
3. Reads the image.
4. Skips images smaller than 64×64 (dummy/placeholder textures).
5. Saves as `{folder_name}_{data.name}.png` in `OUTPUT_DIR`.

Why keep it? It is useful for finding mode icons, HUD art, and badges for custom Discord assets. It does not provide live match state.

Caveats:

- The username `wolly` is hardcoded; change `CACHE_DIR` for your user.
- Unity cache files often have hash-like names and no extension; the script walks every file.
- UnityPy versions differ in API details; if it fails, check the installed version's docs.
- Extracted art is copyrighted by the game's owner; use it only for personal/non-commercial purposes.

---

## Findings that shaped the production daemon

| Finding | Consequence |
| --- | --- |
| Process + UDP socket is a cheap, reliable battle signal. | Adopted in both production scripts. |
| Unity memory contains mode strings, but access and stability are problematic. | Rejected for production. |
| HUD brightness differs between modes. | Adopted as a one-shot grayscale heuristic. |
| HUD column peaks can indicate beacons. | Folded into the centre/edge ratio. |
| Colour counts might work, but add assumptions. | Kept as an optional experiment. |
| OCR is inconsistent on the stylised HUD. | Rejected. |
| Raw packet capture needs root and often sees encrypted data. | Rejected. |
| Unity assets can supply icons, not live state. | Used for art research only. |

The result is the minimal runtime design described in [Architecture](Architecture.md): process + UDP + one screenshot per match.

---

## Generated files and cleanup

| File / directory | Created by |
| --- | --- |
| `beacon_strip.png` | `CountBeacons.py` |
| `beacon_strip_debug.png` | `DumpStrip.py` |
| `current_hud.png` | `InspectUHD.py` |
| `full_match.png` | `TestCrop.py` |
| `cpc_ally_pct.png`, `cpc_enemy_pct.png` | `LiveStats.py` |
| `extracted_mode_icons/` | `StripAssets.py` |

These are safe to delete. Some paths are absolute (`/home/wolly/DiscordRPC/...`); edit them before running on another machine.

---

## Extending the tools

- **New HUD region?** Copy `DumpStrip.py`, change the crop, and look at the profile.
- **New colour signature?** Copy `InspectUHD.py` and add a counter.
- **New memory token?** Copy `FindScene.py`, change the byte targets, and scan both ASCII and UTF-16LE.
- **New IPC port?** Copy `SniffLoopback.py`, change `INTERESTING_PORTS`, and add keywords.
- **New asset folder?** Copy `StripAssets.py`, change `TARGET_FOLDERS` and `CACHE_DIR`.

Whenever a probe becomes useful enough for production, reduce it to the smallest, lowest-privilege version and add it behind a `try/except` in the worker.

---

## Related pages

- [Mode Detection](Mode-Detection.md) — the production algorithm these tools helped design.
- [Game State Detection](Game-State-Detection.md) — process/UDP logic.
- [Troubleshooting](Troubleshooting.md) — permission and capture failures.
- [Configuration](Configuration.md) — recalibrating the crop.
