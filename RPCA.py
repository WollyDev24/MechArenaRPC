#!/usr/bin/env python3
import os
import sys
import signal

# 1. Ignore SIGHUP so terminal hangup signals never terminate the process
signal.signal(signal.SIGHUP, signal.SIG_IGN)

# 2. Handle detached background state if spawned via Dispatch or Restart
is_detached = "--detached" in sys.argv
cli_mode = "--print-config" in sys.argv or "--calibrate" in sys.argv
if is_detached:
    try:
        null_fd = os.open(os.devnull, os.O_RDWR)
        os.dup2(null_fd, 0)
        os.dup2(null_fd, 1)
        os.dup2(null_fd, 2)
        os.close(null_fd)
    except Exception:
        pass

# Force native AppIndicator/DBus backend for proper Wayland/KDE tray handling
os.environ["PYSTRAY_BACKEND"] = "appindicator"

import io
import re
import shutil
import subprocess
import tempfile
import threading
import time
from dataclasses import replace
from pathlib import Path
import psutil
from PIL import Image, ImageDraw
import pystray
from pystray import MenuItem as item
from pypresence import Presence, DiscordNotFound, InvalidID

import settings
from settings import (
    Config,
    dump_config,
    format_crop,
    load_config,
    parse_crop,
    persistent_cli_args,
    save_config,
)

CONFIG_PATH = settings.config_path_from_argv(sys.argv)
CONFIG, CONFIG_WARNINGS = load_config(CONFIG_PATH, sys.argv)


def apply_config(config):
    """Mirror config values into module globals so a reload is picked up live."""
    global CONFIG
    global CLIENT_ID, LARGE_IMAGE, LARGE_TEXT, DOWNLOAD_BUTTONS
    global HUD_CROP_GEOM, MODE_LOCK_DELAY
    global HUD_LOOKUP_RETRIES, HUD_LOOKUP_RETRY_DELAY, CAPTURE_TIMEOUT
    global HUD_EDGE_FRACTION, HUD_CENTER_START_FRACTION, HUD_CENTER_END_FRACTION
    global HUD_CENTER_MIN_CPC, HUD_CENTER_MAX_FFA
    global HUD_RATIO_MAX_DEATHMATCH, HUD_EDGE_MIN_DEATHMATCH, HUD_RATIO_MIN_CPC
    global HUD_MIN_BRIGHTNESS
    global RESULTS_DISPLAY_DURATION, POLL_INTERVAL
    global LOG_FILE, WINDOW_TITLE, PROCESS_NAME

    CONFIG = config
    CLIENT_ID = config.client_id
    LARGE_IMAGE = config.large_image
    LARGE_TEXT = config.large_text
    DOWNLOAD_BUTTONS = [
        {"label": button.label, "url": button.url} for button in config.buttons
    ] or None

    HUD_CROP_GEOM = config.crop
    MODE_LOCK_DELAY = config.mode_lock_delay
    HUD_LOOKUP_RETRIES = config.lookup_retries
    HUD_LOOKUP_RETRY_DELAY = config.lookup_retry_delay
    CAPTURE_TIMEOUT = config.capture_timeout
    HUD_EDGE_FRACTION = config.edge_fraction
    HUD_CENTER_START_FRACTION = config.center_start_fraction
    HUD_CENTER_END_FRACTION = config.center_end_fraction

    HUD_CENTER_MIN_CPC = config.center_min_cpc
    HUD_CENTER_MAX_FFA = config.center_max_ffa
    HUD_RATIO_MAX_DEATHMATCH = config.ratio_max_deathmatch
    HUD_EDGE_MIN_DEATHMATCH = config.edge_min_deathmatch
    HUD_RATIO_MIN_CPC = config.ratio_min_cpc
    HUD_MIN_BRIGHTNESS = config.min_brightness

    RESULTS_DISPLAY_DURATION = config.results_display_duration
    POLL_INTERVAL = config.poll_interval
    LOG_FILE = config.log_file
    WINDOW_TITLE = config.window_title
    PROCESS_NAME = config.process_name


apply_config(CONFIG)

STATE_CLOSED = 0
STATE_MENU = 1
STATE_BATTLE = 2

# ----------------- CLI Argument Parsing for Persistent State -----------------
def parse_flag_arg(flag_name, cast_type, default=None):
    if flag_name in sys.argv:
        try:
            idx = sys.argv.index(flag_name)
            return cast_type(sys.argv[idx + 1])
        except (IndexError, ValueError):
            return default
    return default

initial_session_start = parse_flag_arg("--session-start", int, None)
initial_matches = parse_flag_arg("--matches", int, 0)

# Shared thread state
state_lock = threading.Lock()
current_ui_status = "Waiting for Mech Arena..."
match_count = initial_matches
is_running = True
tray_icon = None


def log(msg):
    """Prints to console (if attached) and writes timestamped lines to LOG_FILE."""
    timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{timestamp}] {msg}"
    if not is_detached and not cli_mode:
        print(line)
    try:
        LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


if not cli_mode:
    for _config_warning in CONFIG_WARNINGS:
        log(f"Config: {_config_warning}")


def get_stats_summary():
    """Generates a clean match counter string."""
    with state_lock:
        count = match_count
    if count == 1:
        return "1 Match"
    return f"{count} Matches"


def set_status(text):
    """Updates the UI status text, tooltip, and redraws the tray menu."""
    global current_ui_status, tray_icon
    with state_lock:
        current_ui_status = text
    if tray_icon:
        tray_icon.title = f"Mech Arena: {text} | {get_stats_summary()}"
        try:
            tray_icon.update_menu()
        except Exception:
            pass


def create_tray_icon_image():
    """Generates a clean 64x64 blue mech visor icon for the system tray."""
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    draw.polygon([(32, 4), (58, 18), (58, 46), (32, 60), (6, 46), (6, 18)], fill=(30, 35, 45, 255))
    draw.rounded_rectangle([(16, 26), (48, 38)], radius=4, fill=(0, 200, 255, 255))
    draw.polygon([(32, 10), (42, 18), (22, 18)], fill=(0, 200, 255, 255))

    return img


def get_mech_window_id():
    """Dynamically resolves the XWayland window ID for the configured game."""
    try:
        out = subprocess.check_output(
            ["xwininfo", "-root", "-tree"], stderr=subprocess.DEVNULL
        ).decode()
        for line in out.splitlines():
            if f'"{WINDOW_TITLE}"' in line:
                match = re.search(r"(0x[0-9a-fA-F]+)", line)
                if match:
                    return match.group(1)
    except Exception:
        pass
    return None


def get_window_geometry(win_id=None):
    """Return ``(width, height)`` for an X11 window, or None."""
    win_id = win_id or get_mech_window_id()
    if not win_id:
        return None
    try:
        out = subprocess.check_output(
            ["xwininfo", "-id", win_id], stderr=subprocess.DEVNULL
        ).decode()
        width = re.search(r"Width:\s+(\d+)", out)
        height = re.search(r"Height:\s+(\d+)", out)
        if width and height:
            return int(width.group(1)), int(height.group(1))
    except Exception:
        pass
    return None


def capture_hud_image(win_id=None, crop_geom=None, timeout=None):
    """Capture the configured HUD crop and return a grayscale PIL image."""
    win_id = win_id or get_mech_window_id()
    if not win_id:
        return None

    geom = crop_geom or HUD_CROP_GEOM
    timeout = timeout or CAPTURE_TIMEOUT
    cmd = ["import", "-silent", "-window", win_id, "-crop", geom, "png:-"]

    try:
        proc = subprocess.run(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=timeout
        )
        if proc.returncode != 0:
            return None
        return Image.open(io.BytesIO(proc.stdout)).convert("L")
    except Exception:
        return None


def capture_full_window_image(win_id=None, timeout=5.0):
    """Capture the entire game window for calibration previews."""
    win_id = win_id or get_mech_window_id()
    if not win_id:
        return None

    cmd = ["import", "-silent", "-window", win_id, "png:-"]
    try:
        proc = subprocess.run(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=timeout
        )
        if proc.returncode != 0:
            return None
        return Image.open(io.BytesIO(proc.stdout)).convert("RGB")
    except Exception:
        return None


def analyze_hud_image(img):
    """Compute brightness statistics for a grayscale HUD crop."""
    if img is None:
        return None

    w, h = img.size
    if w < 3 or h < 1:
        return None

    pixels = img.load()
    edge_w = max(1, min(int(w * HUD_EDGE_FRACTION), w // 2))
    center_start = min(max(0, int(w * HUD_CENTER_START_FRACTION)), w - 1)
    center_end = min(max(center_start + 1, int(w * HUD_CENTER_END_FRACTION)), w)

    left_edge_avg = sum(
        pixels[x, y] for x in range(edge_w) for y in range(h)
    ) / (edge_w * h)
    right_edge_avg = sum(
        pixels[x, y] for x in range(w - edge_w, w) for y in range(h)
    ) / (edge_w * h)
    center_avg = sum(
        pixels[x, y] for x in range(center_start, center_end) for y in range(h)
    ) / ((center_end - center_start) * h)

    edge_avg = max((left_edge_avg + right_edge_avg) / 2.0, 1.0)
    ratio = center_avg / edge_avg

    return {
        "width": w,
        "height": h,
        "left": left_edge_avg,
        "right": right_edge_avg,
        "center": center_avg,
        "edge": edge_avg,
        "ratio": ratio,
        "brightness": max(center_avg, edge_avg),
        "center_start": center_start,
        "center_end": center_end,
        "edge_width": edge_w,
    }


def classify_hud(analysis):
    """Map HUD statistics to a presence mode using the active config."""
    if analysis is None:
        return None
    if analysis["brightness"] < HUD_MIN_BRIGHTNESS:
        return None

    center_avg = analysis["center"]
    edge_avg = analysis["edge"]
    ratio = analysis["ratio"]

    if ratio <= HUD_RATIO_MAX_DEATHMATCH or edge_avg >= HUD_EDGE_MIN_DEATHMATCH:
        return "Deathmatch"
    if center_avg >= HUD_CENTER_MIN_CPC and ratio >= HUD_RATIO_MIN_CPC:
        return "Control Point Clash"
    if center_avg < HUD_CENTER_MAX_FFA:
        return "Free-For-All"

    return "In Battle"


def detect_hud_mode():
    """Differentiates Deathmatch, CPC, and FFA using ratio and absolute center floor."""
    img = capture_hud_image()
    if img is None:
        return None

    analysis = analyze_hud_image(img)
    if analysis is None:
        return None

    log(
        f"HUD Analysis: Center={analysis['center']:.1f}, "
        f"Edge={analysis['edge']:.1f}, Ratio(C/E)={analysis['ratio']:.2f}"
    )
    return classify_hud(analysis)


def detect_hud_mode_with_retry():
    """Retries a failed HUD lookup before giving up for this loop iteration."""
    total_attempts = HUD_LOOKUP_RETRIES + 1

    for attempt in range(1, total_attempts + 1):
        detected = detect_hud_mode()
        if detected is not None:
            return detected

        if attempt < total_attempts:
            log(
                f"HUD lookup failed (attempt {attempt}/{total_attempts}); "
                f"retrying in {HUD_LOOKUP_RETRY_DELAY}s..."
            )
            time.sleep(HUD_LOOKUP_RETRY_DELAY)

    log(f"HUD lookup failed after {total_attempts} attempts; will retry on the next poll.")
    return None


def get_mech_state():
    """Checks process status and UDP network socket existence for Wine."""
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


active_session_start = initial_session_start


def rpc_worker():
    global is_running, active_session_start, match_count

    rpc = None
    last_state = STATE_CLOSED
    session_start = initial_session_start
    battle_start = None
    locked_mode = None
    results_until = None

    log(f"Mech Arena RPC daemon started. Config: {CONFIG_PATH}")
    log("Waiting for game...")

    while is_running:
        state = get_mech_state()

        if state != STATE_CLOSED and rpc is None:
            try:
                rpc = Presence(CLIENT_ID)
                rpc.connect()
                log("Connected to Discord RPC.")
            except (DiscordNotFound, InvalidID, ConnectionRefusedError):
                rpc = None

        if state != STATE_CLOSED and session_start is None:
            session_start = int(time.time())

        active_session_start = session_start
        now = time.time()

        if rpc is not None:
            if state == STATE_BATTLE:
                results_until = None

                # Transitioned into battle
                if state != last_state:
                    battle_start = int(now)
                    locked_mode = None
                    set_status("In Battle (Detecting mode...)")
                    log(
                        "Status: In Battle "
                        f"(Waiting {MODE_LOCK_DELAY:g}s to detect mode...)"
                    )

                    rpc.update(
                        details="In Battle",
                        state=f"Session: {get_stats_summary()}",
                        start=battle_start,
                        large_image=LARGE_IMAGE,
                        large_text=LARGE_TEXT,
                        buttons=DOWNLOAD_BUTTONS
                    )

                # Attempt mode detection once 15s grace period passes
                elif locked_mode is None and (now - battle_start) >= MODE_LOCK_DELAY:
                    detected = detect_hud_mode_with_retry()
                    if detected:
                        locked_mode = detected
                        set_status(f"In Battle ({locked_mode})")
                        log(f"Locked Mode: {locked_mode}")

                        rpc.update(
                            details=f"In Battle ({locked_mode})",
                            state=f"Session: {get_stats_summary()}",
                            start=battle_start,
                            large_image=LARGE_IMAGE,
                            large_text=LARGE_TEXT,
                            buttons=DOWNLOAD_BUTTONS
                        )

            elif state == STATE_MENU:
                # Transitioned from battle into menu -> increment counter and show for 10s
                if last_state == STATE_BATTLE:
                    battle_start = None
                    last_mode = locked_mode or "Battle"
                    locked_mode = None

                    now = time.time()
                    results_until = now + RESULTS_DISPLAY_DURATION

                    with state_lock:
                        match_count += 1
                    log(f"[+] Match finished ({last_mode}). Total played: {match_count}")

                    result_title = f"Viewing Results ({last_mode})"
                    set_status(result_title)

                    rpc.update(
                        details=result_title,
                        state=f"Session: {get_stats_summary()}",
                        start=session_start,
                        large_image=LARGE_IMAGE,
                        large_text=LARGE_TEXT,
                        buttons=DOWNLOAD_BUTTONS
                    )

                # Results period finished -> switch to Hangar
                elif results_until is not None and now >= results_until:
                    results_until = None
                    set_status("In Hangar")
                    log("Status: Main Menu (Results complete)")

                    rpc.update(
                        details="In Hangar",
                        state=f"Session: {get_stats_summary()}",
                        start=session_start,
                        large_image=LARGE_IMAGE,
                        large_text=LARGE_TEXT,
                        buttons=DOWNLOAD_BUTTONS
                    )

                # Normal initial menu startup
                elif state != last_state and results_until is None:
                    battle_start = None
                    locked_mode = None
                    set_status("In Hangar")
                    log("Status: Main Menu")

                    rpc.update(
                        details="In Hangar",
                        state=f"Session: {get_stats_summary()}",
                        start=session_start,
                        large_image=LARGE_IMAGE,
                        large_text=LARGE_TEXT,
                        buttons=DOWNLOAD_BUTTONS
                    )

            elif state == STATE_CLOSED and state != last_state:
                set_status("Game Closed")
                log("Game closed. Clearing RPC.")
                try:
                    rpc.clear()
                    rpc.close()
                except Exception:
                    pass
                rpc = None
                session_start = None
                active_session_start = None
                battle_start = None
                locked_mode = None
                results_until = None

            last_state = state

        time.sleep(POLL_INTERVAL)

    # Cleanup upon exiting
    if rpc is not None:
        try:
            rpc.clear()
            rpc.close()
        except Exception:
            pass


def get_menu_status_text(menu_item):
    with state_lock:
        return f"Status: {current_ui_status}"


def get_menu_stats_text(menu_item):
    return f"Matches Played: {get_stats_summary()}"


def on_reset_stats(icon, menu_item):
    """Resets match counter to 0."""
    global match_count
    with state_lock:
        match_count = 0
    log("Match counter reset to 0.")
    try:
        icon.update_menu()
    except Exception:
        pass


TERMINAL_COMMANDS = (
    ("ghostty", ["-e"]),
    ("kitty", ["-e"]),
    ("alacritty", ["-e"]),
    ("konsole", ["-e"]),
    ("wezterm", ["start", "--"]),
    ("xterm", ["-e"]),
    ("gnome-terminal", ["--"]),
)


def launch_in_terminal(command):
    """Launch a command in the first available terminal emulator."""
    for terminal, prefix in TERMINAL_COMMANDS:
        if not shutil.which(terminal):
            continue
        try:
            subprocess.Popen(
                [terminal, *prefix, *command],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
            return True
        except Exception:
            continue
    return False


def open_with_default_app(path):
    """Open a file with the desktop's default handler or a text editor."""
    for opener in ("xdg-open", "kate", "kwrite", "gedit"):
        if not shutil.which(opener):
            continue
        try:
            subprocess.Popen(
                [opener, str(path)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
            return True
        except Exception:
            continue
    return False


def on_show_log(icon, menu_item):
    """Opens the log file in a live terminal viewer or GUI text editor."""
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    if not LOG_FILE.exists():
        LOG_FILE.touch()

    if launch_in_terminal(["tail", "-f", str(LOG_FILE)]):
        return
    if not open_with_default_app(LOG_FILE):
        log("Show Log: no supported terminal or file opener was found.")


def reload_config():
    """Reload the TOML file and refresh every runtime setting."""
    global CONFIG, CONFIG_WARNINGS
    config, warnings = load_config(CONFIG_PATH, sys.argv)
    CONFIG_WARNINGS = warnings
    apply_config(config)
    for warning in warnings:
        log(f"Config: {warning}")
    log(f"Configuration reloaded from {CONFIG_PATH}")
    return warnings


def on_reload_config(icon, menu_item):
    warnings = reload_config()
    set_status("Config reloaded" if not warnings else "Config reloaded (warnings)")
    try:
        icon.update_menu()
    except Exception:
        pass
    try:
        icon.notify(
            "Configuration reloaded"
            if not warnings
            else "Configuration reloaded with warnings (see log)",
            "Mech Arena RPC",
        )
    except Exception:
        pass


def on_open_config(icon, menu_item):
    try:
        if not CONFIG_PATH.exists():
            save_config(CONFIG, CONFIG_PATH, backup=False)
    except OSError as exc:
        log(f"Open Config: could not create {CONFIG_PATH}: {exc}")
        return
    if not open_with_default_app(CONFIG_PATH):
        log(f"Open Config: no file opener found. Edit {CONFIG_PATH} manually.")


def on_calibrate(icon, menu_item):
    """Open the interactive calibration wizard in a new terminal."""
    command = [
        sys.executable,
        os.path.abspath(__file__),
        "--config",
        str(CONFIG_PATH),
        "--calibrate",
    ]
    if launch_in_terminal(command):
        log("Opened the HUD calibration wizard in a terminal.")
        return
    log(
        "Calibrate: no terminal emulator found. Run this manually: "
        + " ".join(command)
    )


# ----------------------------- Calibration wizard ---------------------------

CALIBRATION_LABELS = {
    "dm": "Deathmatch",
    "deathmatch": "Deathmatch",
    "cpc": "Control Point Clash",
    "control": "Control Point Clash",
    "ffa": "Free-For-All",
    "free": "Free-For-All",
    "other": "Other",
}

CALIBRATION_THRESHOLD_KEYS = {
    "center-min-cpc": "center_min_cpc",
    "center_max_cpc": "center_min_cpc",
    "center-max-ffa": "center_max_ffa",
    "ratio-max-dm": "ratio_max_deathmatch",
    "ratio-max-deathmatch": "ratio_max_deathmatch",
    "edge-min-dm": "edge_min_deathmatch",
    "edge-min-deathmatch": "edge_min_deathmatch",
    "ratio-min-cpc": "ratio_min_cpc",
    "min-brightness": "min_brightness",
}


def ascii_hud_preview(img, columns=80, rows=16):
    """Render a compact grayscale preview of a HUD crop."""
    preview = img.convert("L").resize((columns, rows))
    pixels = preview.load()
    ramp = " .:-=+*#%@"
    lines = []
    for y in range(rows):
        line = "".join(
            ramp[min(len(ramp) - 1, pixels[x, y] * len(ramp) // 256)]
            for x in range(columns)
        )
        lines.append(line)
    return "\n".join(lines)


def calibration_artifact_dir():
    """Return a writable directory for calibration screenshots."""
    candidate = CONFIG.log_file.parent / "mech_arena_calibration"
    try:
        candidate.mkdir(parents=True, exist_ok=True)
        return candidate
    except OSError:
        return Path(tempfile.gettempdir())


def print_thresholds(config):
    print("Thresholds:")
    print(f"  center-min-cpc       = {config.center_min_cpc}")
    print(f"  center-max-ffa       = {config.center_max_ffa}")
    print(f"  ratio-max-deathmatch = {config.ratio_max_deathmatch}")
    print(f"  edge-min-deathmatch  = {config.edge_min_deathmatch}")
    print(f"  ratio-min-cpc        = {config.ratio_min_cpc}")
    print(f"  min-brightness       = {config.min_brightness}")


def print_calibration_help():
    print(
        """
Commands:
  test / t                 capture the crop, print stats and an ASCII preview
  preview / p              save the full window with the crop outlined in red
  open / o                 open the last saved preview/crop in an image viewer
  left/right/up/down [N]   move the crop by N pixels (default 10)
  wider/narrower [N]       grow/shrink width around its centre
  taller/shorter [N]       grow/shrink height around its centre
  crop WxH+X+Y             set the geometry directly
  auto                     scale the 1920x1080 default crop to the window size
  center                   centre the crop horizontally in the window
  show                     show the current crop and thresholds
  sample dm|cpc|ffa|other  record the current stats as a labelled sample
  samples                  list recorded samples
  suggest                  suggest thresholds from the samples
  apply-suggest            accept the suggestions that have a clean gap
  set KEY VALUE            set a threshold (see `show` for KEY names)
  reset                    reset crop and thresholds to defaults
  save [PATH]              write the config file (default: the active one)
  quit / q                 exit; asks to save when there are unsaved changes
"""
    )


def suggest_thresholds(samples, config):
    """Suggest threshold values where the recorded samples separate cleanly."""
    suggestions = {}
    notes = []

    def group(label):
        return [s for s in samples if s["label"] == label]

    dm = group("Deathmatch")
    cpc = group("Control Point Clash")
    ffa = group("Free-For-All")
    non_dm = [s for s in samples if s["label"] not in ("Deathmatch", "Other")]
    non_cpc = [s for s in samples if s["label"] not in ("Control Point Clash", "Other")]
    non_ffa = [s for s in samples if s["label"] not in ("Free-For-All", "Other")]

    if dm and non_dm:
        dm_max = max(s["ratio"] for s in dm)
        other_min = min(s["ratio"] for s in non_dm)
        if dm_max < other_min:
            suggestions["ratio_max_deathmatch"] = round((dm_max + other_min) / 2, 3)
        else:
            notes.append(
                "ratio-max-deathmatch: deathmatch and other ratio ranges overlap; "
                "collect more samples or keep the current value."
            )
    else:
        notes.append("ratio-max-deathmatch: need DM and non-DM samples.")

    if dm and non_dm:
        dm_min = min(s["edge"] for s in dm)
        other_max = max(s["edge"] for s in non_dm)
        if dm_min > other_max:
            suggestions["edge_min_deathmatch"] = round((dm_min + other_max) / 2, 1)
        else:
            notes.append(
                "edge-min-deathmatch: deathmatch and other edge ranges overlap."
            )
    else:
        notes.append("edge-min-deathmatch: need DM and non-DM samples.")

    if cpc and non_cpc:
        cpc_min = min(s["center"] for s in cpc)
        other_max = max(s["center"] for s in non_cpc)
        if cpc_min > other_max:
            suggestions["center_min_cpc"] = round((cpc_min + other_max) / 2, 1)
        else:
            notes.append("center-min-cpc: CPC and other centre ranges overlap.")
        cpc_ratio_min = min(s["ratio"] for s in cpc)
        other_ratio_max = max(s["ratio"] for s in non_cpc)
        if cpc_ratio_min > other_ratio_max:
            suggestions["ratio_min_cpc"] = round(
                (cpc_ratio_min + other_ratio_max) / 2, 3
            )
        else:
            notes.append("ratio-min-cpc: CPC and other ratio ranges overlap.")
    else:
        notes.append("center-min-cpc / ratio-min-cpc: need CPC and non-CPC samples.")

    if ffa and non_ffa:
        ffa_max = max(s["center"] for s in ffa)
        other_min = min(s["center"] for s in non_ffa)
        if ffa_max < other_min:
            suggestions["center_max_ffa"] = round((ffa_max + other_min) / 2, 1)
        else:
            notes.append("center-max-ffa: FFA and other centre ranges overlap.")
    else:
        notes.append("center-max-ffa: need FFA and non-FFA samples.")

    for key, value in list(suggestions.items()):
        if getattr(config, key) == value:
            del suggestions[key]
    if samples and not suggestions and not notes:
        notes.append("No change suggested; the current thresholds already match the samples.")
    return suggestions, notes


def run_calibration():
    """Interactive HUD calibration wizard. Returns a process exit code."""
    if not sys.stdin.isatty():
        print(
            "The calibration wizard needs an interactive terminal.\n"
            f"Run: {sys.executable} {os.path.abspath(__file__)} --calibrate",
            file=sys.stderr,
        )
        return 1

    cfg = CONFIG
    geometry = cfg.crop
    width, height, x, y = parse_crop(geometry)
    samples = []
    preview_path = None
    crop_path = None
    dirty = False
    artifact_dir = calibration_artifact_dir()

    print("=== Mech Arena RPC HUD calibration ===")
    print(f"Config: {CONFIG_PATH}")
    print(f"Window: {WINDOW_TITLE!r}")
    for warning in CONFIG_WARNINGS:
        print(f"Config warning: {warning}")
    if get_mech_window_id():
        print("Window found. Start a match, wait for the HUD to settle, then type `test`.")
    else:
        print("Window not found. Start Mech Arena (and keep it visible), then type `test`.")
    print("Type `help` for commands.\n")

    def update_geometry(new_geometry, note=""):
        nonlocal geometry, width, height, x, y, cfg, dirty
        width, height, x, y = parse_crop(new_geometry)
        geometry = format_crop(width, height, x, y)
        cfg = replace(cfg, crop=geometry)
        apply_config(cfg)
        dirty = True
        print(f"Crop: {geometry}" + (f"  ({note})" if note else ""))

    def capture_report():
        nonlocal crop_path
        img = capture_hud_image(crop_geom=geometry)
        if img is None:
            print("Capture failed. Is Mech Arena running and visible?")
            print("  Check: xwininfo -root -tree | grep -i 'Mech Arena'")
            return
        analysis = analyze_hud_image(img)
        if analysis is None:
            print("The crop is too small to analyze; increase its size.")
            return

        verdict = classify_hud(analysis)
        print(
            f"HUD {analysis['width']}x{analysis['height']}  crop={geometry}  "
            f"Center={analysis['center']:.1f}  Edge={analysis['edge']:.1f}  "
            f"Ratio={analysis['ratio']:.2f}  ->  {verdict or 'no result'}"
        )
        print("  Left edge={:.1f}  Right edge={:.1f}".format(
            analysis["left"], analysis["right"]
        ))
        print("  Brightness preview (left -> right):")
        print(ascii_hud_preview(img))
        try:
            crop_path = artifact_dir / "mech_arena_calibration_crop.png"
            img.save(crop_path)
            print(f"  Saved crop: {crop_path}")
        except OSError as exc:
            print(f"  Could not save crop: {exc}")

    while True:
        try:
            raw = input("calibrate> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            raw = "quit"

        if not raw:
            continue
        parts = raw.split()
        command = parts[0].lower()
        try:
            if command in ("help", "?"):
                print_calibration_help()
            elif command in ("test", "t"):
                capture_report()
            elif command in ("preview", "p"):
                full = capture_full_window_image()
                if full is None:
                    print("Full-window capture failed; is the game visible?")
                else:
                    draw = ImageDraw.Draw(full)
                    draw.rectangle(
                        [x, y, x + width - 1, y + height - 1],
                        outline=(255, 0, 0),
                        width=3,
                    )
                    preview_path = artifact_dir / "mech_arena_calibration_full.png"
                    full.save(preview_path)
                    print(f"Saved full-window preview: {preview_path}")
                    print("The red rectangle is the current crop. Use `open` to view it.")
            elif command in ("open", "o"):
                target = preview_path or crop_path
                if target is None:
                    print("Run `test` or `preview` first.")
                elif not open_with_default_app(target):
                    print(f"No image viewer found; open manually: {target}")
                else:
                    print(f"Opening {target}")
            elif command in ("left", "right", "up", "down"):
                amount = int(parts[1]) if len(parts) > 1 else 10
                if amount <= 0:
                    raise ValueError("distance must be positive")
                if command == "left":
                    x -= amount
                elif command == "right":
                    x += amount
                elif command == "up":
                    y -= amount
                else:
                    y += amount
                update_geometry(format_crop(width, height, x, y))
            elif command in ("wider", "narrower", "taller", "shorter"):
                amount = int(parts[1]) if len(parts) > 1 else 10
                if amount <= 0:
                    raise ValueError("amount must be positive")
                if command == "wider":
                    width += amount
                    x -= amount // 2
                elif command == "narrower":
                    delta = min(amount, max(0, width - 10))
                    width -= delta
                    x += delta // 2
                elif command == "taller":
                    height += amount
                    y -= amount // 2
                else:
                    delta = min(amount, max(0, height - 5))
                    height -= delta
                    y += delta // 2
                update_geometry(format_crop(width, height, x, y))
            elif command in ("crop", "set-crop"):
                if len(parts) != 2:
                    print("Usage: crop WxH+X+Y")
                    continue
                update_geometry(format_crop(*parse_crop(parts[1])))
            elif command in ("auto", "scale"):
                size = get_window_geometry()
                if size is None:
                    print("Could not read the window size; is the game visible?")
                else:
                    win_w, win_h = size
                    scale = win_w / 1920.0
                    new_w = max(10, round(440 * scale))
                    new_h = max(5, round(45 * scale))
                    new_x = round(740 * scale)
                    new_y = round(50 * scale)
                    update_geometry(
                        format_crop(new_w, new_h, new_x, new_y),
                        f"scaled to {win_w}x{win_h}",
                    )
            elif command in ("center", "centre"):
                size = get_window_geometry()
                if size is None:
                    print("Could not read the window size; is the game visible?")
                else:
                    x = max(0, (size[0] - width) // 2)
                    update_geometry(format_crop(width, height, x, y))
            elif command in ("show", "status"):
                print(f"Config file: {CONFIG_PATH}")
                print(f"Crop: {geometry}  Window: {WINDOW_TITLE!r}")
                print_thresholds(cfg)
                print(f"Samples: {len(samples)}")
                print(f"Window id: {get_mech_window_id() or 'not found'}")
            elif command in ("sample", "s"):
                if len(parts) < 2 or parts[1].lower() not in CALIBRATION_LABELS:
                    print("Usage: sample dm|cpc|ffa|other")
                    continue
                label = CALIBRATION_LABELS[parts[1].lower()]
                img = capture_hud_image(crop_geom=geometry)
                analysis = analyze_hud_image(img) if img else None
                if analysis is None:
                    print("Capture failed; sample not recorded.")
                else:
                    samples.append(
                        {
                            "label": label,
                            "center": analysis["center"],
                            "edge": analysis["edge"],
                            "ratio": analysis["ratio"],
                        }
                    )
                    print(
                        f"Recorded {label}: Center={analysis['center']:.1f}, "
                        f"Edge={analysis['edge']:.1f}, Ratio={analysis['ratio']:.2f}"
                    )
            elif command in ("samples", "list"):
                if not samples:
                    print("No samples yet. Use `sample dm`, `sample cpc`, or `sample ffa`.")
                else:
                    print(f"{'#':>2}  {'Mode':<20} {'Center':>7} {'Edge':>7} {'Ratio':>6}")
                    for index, sample in enumerate(samples, start=1):
                        print(
                            f"{index:>2}  {sample['label']:<20} "
                            f"{sample['center']:>7.1f} {sample['edge']:>7.1f} "
                            f"{sample['ratio']:>6.2f}"
                        )
            elif command == "suggest":
                suggestions, notes = suggest_thresholds(samples, cfg)
                for note in notes:
                    print(note)
                if suggestions:
                    for key, value in suggestions.items():
                        print(f"  {key} = {value}  (current: {getattr(cfg, key)})")
                    print("Run `apply-suggest` to accept these values.")
            elif command in ("apply-suggest", "apply"):
                suggestions, notes = suggest_thresholds(samples, cfg)
                if suggestions:
                    cfg = replace(cfg, **suggestions)
                    apply_config(cfg)
                    dirty = True
                    print("Applied suggestions:")
                    for key, value in suggestions.items():
                        print(f"  {key} = {value}")
                for note in notes:
                    print(note)
                if not suggestions:
                    print("Nothing to apply.")
            elif command == "set":
                if len(parts) != 3:
                    print("Usage: set KEY VALUE")
                    continue
                key = CALIBRATION_THRESHOLD_KEYS.get(parts[1].lower())
                if key is None:
                    print("Unknown key. Use `show` to see the available names.")
                    continue
                value = float(parts[2])
                if key in (
                    "center_min_cpc",
                    "center_max_ffa",
                    "edge_min_deathmatch",
                    "min_brightness",
                ):
                    if not 0 <= value <= 255:
                        raise ValueError("brightness values must be between 0 and 255")
                elif value < 0:
                    raise ValueError("ratio values must be >= 0")
                cfg = replace(cfg, **{key: value})
                apply_config(cfg)
                dirty = True
                print(f"{key} = {value}")
            elif command == "reset":
                defaults = Config()
                cfg = replace(
                    cfg,
                    crop=defaults.crop,
                    center_min_cpc=defaults.center_min_cpc,
                    center_max_ffa=defaults.center_max_ffa,
                    ratio_max_deathmatch=defaults.ratio_max_deathmatch,
                    edge_min_deathmatch=defaults.edge_min_deathmatch,
                    ratio_min_cpc=defaults.ratio_min_cpc,
                    min_brightness=defaults.min_brightness,
                )
                apply_config(cfg)
                geometry = cfg.crop
                width, height, x, y = parse_crop(geometry)
                dirty = True
                print("Crop and thresholds reset to defaults.")
            elif command in ("save", "write"):
                target = Path(parts[1]).expanduser() if len(parts) > 1 else CONFIG_PATH
                try:
                    save_config(cfg, target)
                    dirty = False
                    print(f"Saved config to {target}")
                    if target == CONFIG_PATH:
                        print("Use tray -> Reload Config (or restart the daemon) to apply it.")
                    else:
                        print(f"Note: the daemon reads {CONFIG_PATH}.")
                except OSError as exc:
                    print(f"Could not save: {exc}")
            elif command in ("quit", "exit", "q"):
                if dirty:
                    answer = input(f"Save changes to {CONFIG_PATH}? [y/N] ").strip().lower()
                    if answer in ("y", "yes"):
                        try:
                            save_config(cfg, CONFIG_PATH)
                            print(f"Saved {CONFIG_PATH}")
                        except OSError as exc:
                            print(f"Could not save: {exc}")
                break
            else:
                print(f"Unknown command {command!r}. Type `help`.")
        except (ValueError, IndexError) as exc:
            print(f"Invalid input: {exc}")
        except KeyboardInterrupt:
            print()
            break

    return 0


def on_restart(icon, menu_item):
    """
    Relaunches the script file on disk to pick up code modifications while preserving
    session start timestamp and current match count seamlessly.
    """
    global is_running
    log("Reloading updated script from disk (preserving session state)...")

    script_path = os.path.abspath(__file__)
    args = [sys.executable, script_path, "--detached", *persistent_cli_args(sys.argv)]

    if active_session_start is not None:
        args.extend(["--session-start", str(active_session_start)])

    with state_lock:
        args.extend(["--matches", str(match_count)])

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


def on_dispatch(icon, menu_item):
    """
    Relaunches the daemon in a brand new, fully orphaned kernel session
    via start_new_session=True, then immediately terminates the foreground
    process without waiting for threads to join.
    """
    global is_running
    log("Dispatching process to independent background session...")

    script_path = os.path.abspath(__file__)
    args = [sys.executable, script_path, "--detached", *persistent_cli_args(sys.argv)]

    if active_session_start is not None:
        args.extend(["--session-start", str(active_session_start)])

    with state_lock:
        args.extend(["--matches", str(match_count)])

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


def on_quit(icon, menu_item):
    global is_running
    is_running = False
    icon.stop()


def main():
    global tray_icon

    if "--print-config" in sys.argv:
        print(f"# Effective config: {CONFIG_PATH}")
        print(dump_config(CONFIG))
        for warning in CONFIG_WARNINGS:
            print(f"# warning: {warning}", file=sys.stderr)
        return 0

    if "--calibrate" in sys.argv:
        return run_calibration()

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

    tray_icon = pystray.Icon(
        name="mech_arena_rpc",
        icon=create_tray_icon_image(),
        title="Mech Arena: Waiting for game...",
        menu=menu
    )

    worker_thread = threading.Thread(target=rpc_worker, daemon=True)
    worker_thread.start()

    tray_icon.run()


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        is_running = False
        sys.exit(0)