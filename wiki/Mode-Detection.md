# Mode Detection

Mech Arena's Discord presence can include the game mode, but the game does not expose it through any API this project uses. The daemon therefore takes a single screenshot of the in-match HUD and classifies it with brightness heuristics.

This page explains the crop, the maths, the thresholds, and how to recalibrate.

> This is a heuristic, not an official data source. It is intentionally simple and deliberately locked after one read per match.

---

## Why the HUD?

Earlier experiments tried several other sources (see [Testing Tools](Testing-Tools.md)):

| Approach | Result |
| --- | --- |
| Read process memory for Unity scene/mode strings | Worked sometimes, but needs `/proc/<pid>/mem` access, is brittle across updates, and may conflict with anti-cheat/ToS. |
| OCR the HUD with Tesseract | Too unreliable: stylised fonts, anti-aliasing, motion, and score changes. |
| Capture network traffic | Needs root/raw sockets, and useful metadata is not reliably plaintext. |
| Unpack Unity assets | Good for icons, not for live match state. |

A grayscale screenshot is fast, non-invasive, and stable enough for three coarse classes.

---

## The screenshot

```python
HUD_CROP_GEOM = "440x45+740+50"
cmd = ["import", "-silent", "-window", win_id, "-crop", HUD_CROP_GEOM, "png:-"]
```

| Part | Meaning |
| --- | --- |
| `440x45` | Crop width × height. |
| `+740+50` | X and Y offset inside the game window. |
| `-window <id>` | Capture that X11/XWayland window, not the whole screen. |
| `png:-` | Write PNG bytes to stdout, captured in memory. |
| timeout `1.5` | A hung capture cannot stall the worker. |

### Where is this region?

For a 1920×1080 window, the crop spans:

- X: `740` to `1179` (440 px wide)
- Y: `50` to `94` (45 px tall)

That is a horizontal band across the top-centre HUD, where the mode-specific score / beacon / team indicators sit. The crop is centred on x=960, the horizontal midpoint of a 1920-wide window.

```
1920 × 1080 window
┌──────────────────────────────────────────────────────────────┐
│                            ▲                                 │
│             ┌──────────────┴──────────────┐                  │
│             │  HUD strip 440×45 at y=50   │                  │
│             └──────────────┬──────────────┘                  │
│                            ▼                                 │
│                                                              │
│                      game viewport                           │
│                                                              │
└──────────────────────────────────────────────────────────────┘
```

> The crop is **window-relative**. It assumes the game window is 1920×1080 and the UI is at 100% scale. Different resolutions, UI scaling, or a Wine virtual desktop will move the HUD and break detection. See [Calibration](#calibration).

### Capture failure

`detect_hud_mode()` returns `None` when:

- the window ID cannot be resolved,
- `import` exits non-zero,
- the subprocess times out,
- Pillow cannot decode the bytes.

`None` means "not detected", so the worker leaves `locked_mode` empty. The worker calls `detect_hud_mode_with_retry()`, which makes the first attempt plus `HUD_LOOKUP_RETRIES` (default **3**) retries, spaced by `HUD_LOOKUP_RETRY_DELAY` (default **2 seconds**). If all attempts fail, normal 2-second polling continues. It does **not** lock a wrong value on a failed lookup.

---

## Image analysis

The PNG is converted to 8-bit grayscale (`Image.convert("L")`), so every pixel is 0–255.

With `w = 440`, `h = 45`:

```python
edge_w       = int(w * 0.15)              # 66 px
center_start = int(w * 0.35)              # 154
center_end   = int(w * 0.65)              # 286
```

Regions:

```
0                        154          286                    440
│◄── left edge 66px ──►│◄──── centre 132px ────►│◄── right edge 66px ──►│
└──────────────────────┴────────────────────────┴──────────────────────┘
       15%                      30%                       15%
```

The outer 20% on each side (between the sampled edge and the centre) is not used.

### Averages

```python
left_edge_avg  = mean(pixels[x, y] for 0 <= x < 66)
right_edge_avg = mean(pixels[x, y] for 374 <= x < 440)
center_avg     = mean(pixels[x, y] for 154 <= x < 286)

edge_avg = max((left_edge_avg + right_edge_avg) / 2.0, 1.0)
ratio    = center_avg / edge_avg
```

`edge_avg` is clamped to at least `1.0` to avoid division by zero on a completely black capture.

### What the profiles look like

These are illustrative, not measured guarantees:

| Scene | Edges | Centre | Ratio | Likely label |
| --- | --- | --- | --- | --- |
| Deathmatch score banners | Bright (~150–200) | Dimmer | ≤ 0.88 | Deathmatch |
| Deathmatch with bright score plates | Very bright | Any | — | Deathmatch (`edge >= 150`) |
| CPC beacon cluster | Darker (~60–80) | Bright (~100–140) | ≥ 1.20 | CPC |
| FFA | Dim (~40–70) | Dim (< 95) | ~1.0 | FFA |
| Ambiguous / transition | Mixed | Mixed | 0.89–1.19 | "In Battle" fallback |

The thresholds are empirical and may need adjustment for your GPU, resolution, HUD scale, colour settings, and game version.

---

## Decision tree

The checks run **in order**; the first match wins.

```text
                    ┌──────────────────────────────┐
                    │ ratio <= 0.88 OR edge >= 150 │──yes──► Deathmatch
                    └──────────────┬───────────────┘
                                   │ no
                                   ▼
                    ┌──────────────────────────────┐
                    │ center >= 95 AND ratio >= 1.20│──yes──► Control Point Clash
                    └──────────────┬───────────────┘
                                   │ no
                                   ▼
                    ┌──────────────────────────────┐
                    │ center < 95                  │──yes──► Free-For-All
                    └──────────────┬───────────────┘
                                   │ no
                                   ▼
                               "In Battle"
```

Why this order?

- Deathmatch has the strongest positive signal: bright team score plates on the wings. Both the ratio test and the absolute `edge` test catch it.
- CPC is the only mode expected to have a bright **centre** (beacons) relative to the wings. The ratio requirement avoids classifying a uniformly bright image as CPC.
- FFA is the "dim everything" profile. It is checked last because a dark CPC or DM frame with a low ratio is already covered.
- The fallback avoids forcing a wrong label when the frame is ambiguous.

### Empty / black captures

If the capture is fully black, both averages are 0. `edge_avg` becomes `1.0`, `ratio` becomes `0.0`, and the first branch classifies it as **Deathmatch**. This is a real failure mode: a minimised or blocked window can produce a black frame that looks like a valid DM read. Keep the game visible, and/or add a minimum-brightness sanity check if this affects you.

---

## Locking the result

```python
MODE_LOCK_DELAY = 15
HUD_LOOKUP_RETRIES = 3
HUD_LOOKUP_RETRY_DELAY = 2
```

On entering `STATE_BATTLE`, the worker sets `battle_start = now` and `locked_mode = None`. It publishes a generic "In Battle" presence.

On a later poll, when `now - battle_start >= 15` and `locked_mode is None`, it calls `detect_hud_mode_with_retry()`:

- If the first attempt returns a non-empty string, that string is stored in `locked_mode`, logged, and used in the presence. **It is never re-evaluated for the rest of the match.**
- If the first attempt returns `None`, the helper retries up to `HUD_LOOKUP_RETRIES` times (default 3) with `HUD_LOOKUP_RETRY_DELAY` seconds between attempts (default 2). The first success locks the mode.
- If every attempt fails, the helper returns `None` and the worker falls back to its normal 2-second poll for another burst of attempts.

Why 15 seconds?

- Loading screens, spawn animations, and the intro banner can produce misleading HUD frames.
- By 15 seconds the normal score/beacon HUD is usually settled.
- One read prevents flicker from score changes, kill feeds, and beacon captures.

Why one shot?

- Repeating the read would make the Discord label change whenever the HUD changes.
- A wrong read is preferable to a label that oscillates every 2 seconds.
- The label resets on the next match.

To force a re-read during the same match, restart the daemon (or the match). There is no runtime "re-detect" button.

### The "In Battle (In Battle)" quirk

`detect_hud_mode()` returns the string `"In Battle"` when the heuristics are inconclusive. The worker treats any non-empty string as a successful lock and formats:

```python
details=f"In Battle ({locked_mode})"
```

So an ambiguous read produces:

```text
In Battle (In Battle)
```

This is cosmetic. It can be fixed by treating `"In Battle"` as a sentinel:

```python
detected = detect_hud_mode_with_retry()
if detected and detected != "In Battle":
    locked_mode = detected
    ...
```

or by returning `None` instead of `"In Battle"` from the fallback. The docs describe the current behaviour rather than changing it.

---

## Calibration

If the mode is wrong or always "In Battle", calibrate the crop and thresholds for your setup.

### 1. Capture the current HUD

```bash
WIN=$(xwininfo -root -tree | awk '/"Mech Arena"/ {print $1; exit}')
import -window "$WIN" -crop 440x45+740+50 /tmp/hud.png
identify /tmp/hud.png
```

Open `/tmp/hud.png`. It should show the score/beacon strip, not empty sky or the wrong HUD element. If it is wrong, adjust `+X+Y` (and possibly `WxH`).

### 2. Print a brightness profile

Run `TestingTools/DumpStrip.py` (edit its hardcoded window ID first if necessary), or use the equivalent command:

```bash
python TestingTools/DumpStrip.py
```

It saves `beacon_strip_debug.png` and prints a 40-bucket ASCII profile, for example:

```text
--- Horizontal Brightness Profile (Left -> Right) ---
[####............................####]
```

Use this to see whether the centre or the edges are brighter, and whether your crop is aligned.

### 3. Collect labelled samples

Join each mode and run the daemon in the foreground. The log prints:

```text
HUD Analysis: Center=118.4, Edge=71.2, Ratio(C/E)=1.66
```

Record several values per mode, ideally from different maps and lighting conditions. A simple table helps:

| Mode | Center | Edge | Ratio | Current verdict |
| --- | --- | --- | --- | --- |
| Deathmatch | | | | |
| CPC | | | | |
| FFA | | | | |

### 4. Adjust thresholds

Edit `detect_hud_mode()` in `RPCA.py`:

```python
if ratio <= 0.88 or edge_avg >= 150:
    return "Deathmatch"

if center_avg >= 95 and ratio >= 1.20:
    return "Control Point Clash"

if center_avg < 95:
    return "Free-For-All"
```

Pick cut-offs that separate your samples with some margin. Keep the checks ordered and keep the fallback.

### 5. Validate

Play a few matches in each mode and confirm the presence label. Remember that the label locks after the first successful read, so a bad early frame lasts the whole match. If intro frames are the problem, increase `MODE_LOCK_DELAY` (e.g. 20–25) rather than loosening thresholds.

### 6. Optional: colour-based checks

`TestingTools/InspectUHD.py` counts cyan, red, and gold pixels. If brightness alone is not separable for you, a colour ratio (e.g. cyan vs red beacons) could be added to `detect_hud_mode()`. The production daemon deliberately sticks to grayscale because it is simpler and does not assume a colour scheme.

---

## Resolution and UI scaling

The crop is hardcoded for 1920×1080 at 100% UI scale. If your game renders at a different size, scale the crop as a starting point:

```text
scale = actual_width / 1920
W = round(440 * scale)
H = round(45  * scale)
X = round(740 * scale)
Y = round(50  * scale)
HUD_CROP_GEOM = f"{W}x{H}+{X}+{Y}"
```

Examples:

| Resolution | Starting crop |
| --- | --- |
| 1920×1080 | `440x45+740+50` |
| 2560×1440 | `587x60+987+67` |
| 1280×720 | `293x30+493+33` |

Caveats:

- This assumes the HUD scales linearly with render resolution. Games often scale UI independently.
- If you use a Wine virtual desktop, the game window may be the virtual desktop size, not the render resolution.
- If UI scale is not 100%, the HUD may be larger/smaller than the linear estimate.
- Always verify with a real capture before trusting the numbers.
- The region fractions (15% edges, 35–65% centre) are relative to the crop, so they adapt automatically once the crop contains the same HUD element.

---

## Failure modes

| Symptom | Cause | Fix |
| --- | --- | --- |
| Mode never updates | Window not found or capture fails | Check `xwininfo`; keep the game visible. |
| Always "In Battle" | Crop misaligned or ambiguous frame | Recalibrate with `DumpStrip.py`. |
| Always "Deathmatch" | Black frame or very bright edges | Check capture; add a minimum-brightness guard. |
| Wrong mode on some maps | Lighting/UI differences | Collect more samples and widen thresholds. |
| Label flickers | Not possible in production (locked) | If using the prototype, it re-detects every poll. |
| "In Battle (In Battle)" | Ambiguous read locked | Tune thresholds or filter the sentinel. |
| Detection is late | 15 s lock delay | Lower `MODE_LOCK_DELAY`, accepting intro-frame risk. |
| Mode changes mid-match | You are running the prototype, not `RPCA.py` | Use the production daemon. |

---

## Related pages

- [Configuration](Configuration.md) — change the crop, thresholds, and timers.
- [Testing Tools](Testing-Tools.md) — `DumpStrip.py`, `CountBeacons.py`, `DetectMode.py`, `InspectUHD.py`.
- [Troubleshooting](Troubleshooting.md) — symptom-first fixes.
