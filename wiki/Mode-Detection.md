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

```toml
[hud]
crop = "440x45+740+50"
capture_timeout = 1.5
```

`capture_hud_image()` runs:

```python
cmd = ["import", "-silent", "-window", win_id, "-crop", HUD_CROP_GEOM, "png:-"]
```

| Part | Meaning |
| --- | --- |
| `440x45` | Crop width × height. |
| `+740+50` | X and Y offset inside the game window. |
| `-window <id>` | Capture that X11/XWayland window, not the whole screen. |
| `png:-` | Write PNG bytes to stdout, captured in memory. |
| `capture_timeout` | A hung capture cannot stall the worker. |

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

`capture_hud_image()` returns `None` when:

- the window ID cannot be resolved,
- `import` exits non-zero,
- the subprocess hits `hud.capture_timeout`,
- Pillow cannot decode the bytes.

`classify_hud()` also returns `None` when the crop is too small to analyze or when `max(center, edge) < hud.thresholds.min_brightness` (the black-frame guard).

`None` means "not detected", so the worker leaves `locked_mode` empty. It calls `detect_hud_mode_with_retry()`, which makes the first attempt plus `hud.lookup_retries` (default **3**) retries, spaced by `hud.lookup_retry_delay` (default **2 seconds**). If all attempts fail, normal polling continues. It does **not** lock a wrong value on a failed lookup.

---

## Image analysis

The PNG is converted to 8-bit grayscale (`Image.convert("L")`), so every pixel is 0–255.

With `w = 440`, `h = 45` and the default fractions:

```toml
[hud]
edge_fraction = 0.15
center_start_fraction = 0.35
center_end_fraction = 0.65
```

```python
edge_w       = int(w * edge_fraction)         # 66 px
center_start = int(w * center_start_fraction) # 154
center_end   = int(w * center_end_fraction)   # 286
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

The checks run **in order**; the first match wins. They are implemented in `classify_hud()` and use the `[hud.thresholds]` config values.

```text
                    ┌──────────────────────────────────────────────┐
                    │ ratio <= ratio_max_deathmatch                │──yes──► Deathmatch
                    │ OR edge >= edge_min_deathmatch               │
                    └──────────────┬───────────────────────────────┘
                                   │ no
                                   ▼
                    ┌──────────────────────────────────────────────┐
                    │ center >= center_min_cpc                     │──yes──► Control Point Clash
                    │ AND ratio >= ratio_min_cpc                   │
                    └──────────────┬───────────────────────────────┘
                                   │ no
                                   ▼
                    ┌──────────────────────────────────────────────┐
                    │ center < center_max_ffa                      │──yes──► Free-For-All
                    └──────────────┬───────────────────────────────┘
                                   │ no
                                   ▼
                               "In Battle"
```

The defaults are:

```toml
[hud.thresholds]
center_min_cpc = 95
center_max_ffa = 95
ratio_max_deathmatch = 0.88
edge_min_deathmatch = 150
ratio_min_cpc = 1.20
min_brightness = 5
```

Why this order?

- Deathmatch has the strongest positive signal: bright team score plates on the wings. Both the ratio test and the absolute `edge` test catch it.
- CPC is the only mode expected to have a bright **centre** (beacons) relative to the wings. The ratio requirement avoids classifying a uniformly bright image as CPC.
- FFA is the "dim everything" profile. It is checked last because a dark CPC or DM frame with a low ratio is already covered.
- The fallback avoids forcing a wrong label when the frame is ambiguous.

### Empty / black captures

Without a guard, a fully black capture gives `center = 0`, `edge = 1.0` (clamped), and `ratio = 0.0`, so the first branch would classify it as **Deathmatch**. A minimised or blocked window can produce exactly that.

`min_brightness` (default `5`) prevents it: `classify_hud()` treats any frame where both `center` and `edge` are below that value as a failed capture and returns `None`, so the retry burst runs. Set `min_brightness = 0` to disable the guard.

Keep the game visible during matches regardless.

---

## Locking the result

```toml
[hud]
mode_lock_delay = 15
lookup_retries = 3
lookup_retry_delay = 2
```

On entering `STATE_BATTLE`, the worker sets `battle_start = now` and `locked_mode = None`. It publishes a generic "In Battle" presence.

On a later poll, when `now - battle_start >= mode_lock_delay` and `locked_mode is None`, it calls `detect_hud_mode_with_retry()`:

- If the first attempt returns a non-empty string, that string is stored in `locked_mode`, logged, and used in the presence. **It is never re-evaluated for the rest of the match.**
- If the first attempt returns `None`, the helper retries up to `lookup_retries` times (default 3) with `lookup_retry_delay` seconds between attempts (default 2). The first success locks the mode.
- If every attempt fails, the helper returns `None` and the worker falls back to its normal `timing.poll_interval` poll for another burst of attempts.

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

If the mode is wrong or always "In Battle", calibrate the crop and thresholds for your setup. The interactive wizard does the capture/preview/sample loop for you.

### Launching the wizard

From the tray: **Calibrate HUD**. It opens a terminal running:

```bash
.venv/bin/python RPCA.py --config ~/.config/mech-arena-rpc/config.toml --calibrate
```

Or run it directly:

```bash
.venv/bin/python RPCA.py --calibrate
```

It needs an interactive terminal. With redirected stdin it prints an error and exits with code 1.

### Workflow

1. Start Mech Arena and join a match. Keep the window visible.
2. Run `show` to confirm the config path, crop, window title, and current thresholds.
3. Run `test`. It captures the crop, prints `Center`, `Edge`, `Ratio`, the current verdict, and a 16-row ASCII brightness preview. It also saves the crop under the calibration artifact directory.
4. If the crop is misplaced, run `preview` to save the full window with the crop outlined in red, then `open` to view it.
5. Move/resize the crop with the nudge commands, or run `auto` to scale the 1920×1080 default to the current window.
6. Run `test` again until the preview clearly shows the score/beacon strip and the verdict looks right.
7. Collect labelled samples with `sample dm`, `sample cpc`, `sample ffa`, and `sample other`. Repeat across maps/lighting.
8. Run `suggest`. It finds separations in the sample ranges and prints proposed thresholds. `apply-suggest` accepts the non-overlapping ones.
9. `save` writes the config atomically (keeping `config.toml.bak`). Then use tray → **Reload Config**.
10. Play a few matches in each mode and confirm the label.

### Commands

| Command | Effect |
| --- | --- |
| `test` / `t` | Capture and report stats plus an ASCII preview. |
| `preview` / `p` | Save the full window with the crop outlined in red. |
| `open` / `o` | Open the last preview/crop in an image viewer. |
| `left/right/up/down [N]` | Move the crop by N pixels (default 10). |
| `wider/narrower [N]` | Grow/shrink width around its centre. |
| `taller/shorter [N]` | Grow/shrink height around its centre. |
| `crop WxH+X+Y` | Set the geometry directly. |
| `auto` | Scale the 1920×1080 default crop to the window size. |
| `center` | Centre the crop horizontally in the window. |
| `show` | Show the current crop and thresholds. |
| `sample dm\|cpc\|ffa\|other` | Record the current stats as a labelled sample. |
| `samples` | List recorded samples. |
| `suggest` | Suggest thresholds from the samples. |
| `apply-suggest` | Accept suggestions that have a clean gap. |
| `set KEY VALUE` | Set a threshold (keys match the config names). |
| `reset` | Reset crop and thresholds to defaults. |
| `save [PATH]` | Write the config file (default: the active one). |
| `quit` / `q` | Exit; asks to save when there are unsaved changes. |

### Manual threshold editing

The same values live under `[hud.thresholds]`:

```toml
[hud.thresholds]
center_min_cpc = 95
center_max_ffa = 95
ratio_max_deathmatch = 0.88
edge_min_deathmatch = 150
ratio_min_cpc = 1.20
min_brightness = 5
```

Pick cut-offs that separate your samples with some margin. Keep the checks ordered and keep the fallback. `min_brightness` is the black-frame guard described above.

The log still prints raw values on every detection, so you can tune by hand if you prefer:

```text
HUD Analysis: Center=118.4, Edge=71.2, Ratio(C/E)=1.66
```

`TestingTools/DumpStrip.py` remains useful for a raw horizontal brightness profile outside the wizard.

### Optional: colour-based checks

`TestingTools/InspectUHD.py` counts cyan, red, and gold pixels. If brightness alone is not separable for you, a colour ratio (e.g. cyan vs red beacons) could be added to `classify_hud()`. The production daemon deliberately sticks to grayscale because it is simpler and does not assume a colour scheme.

---

## Resolution and UI scaling

The default crop assumes 1920×1080 at 100% UI scale. If your game renders at a different size, the wizard's `auto` command applies this starting point:

```text
scale = actual_width / 1920
W = round(440 * scale)
H = round(45  * scale)
X = round(740 * scale)
Y = round(50  * scale)
[hud]
crop = "WxH+X+Y"
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
| Always "In Battle" | Crop misaligned or ambiguous frame | Run **Calibrate HUD**, then `test` and `suggest`. |
| Always "Deathmatch" | Black frame or very bright edges | Check the preview; tune `min_brightness` and `edge_min_deathmatch`. |
| Wrong mode on some maps | Lighting/UI differences | Collect more samples in the wizard and `apply-suggest`. |
| Label flickers | Not possible in production (locked) | If using the prototype, it re-detects every poll. |
| "In Battle (In Battle)" | Ambiguous read locked | Tune thresholds or filter the sentinel. |
| Detection is late | `mode_lock_delay` | Lower it, accepting intro-frame risk. |
| Mode changes mid-match | You are running the prototype, not `RPCA.py` | Use the production daemon. |
| Config edits ignored | Daemon has old values | Tray → **Reload Config**. |

---

## Related pages

- [Configuration](Configuration.md) — change the crop, thresholds, and timers.
- [Testing Tools](Testing-Tools.md) — `DumpStrip.py`, `CountBeacons.py`, `DetectMode.py`, `InspectUHD.py`.
- [Troubleshooting](Troubleshooting.md) — symptom-first fixes.
