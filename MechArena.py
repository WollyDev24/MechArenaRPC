#!/usr/bin/env python3
import os
import sys
import signal

# 1. Ignore SIGHUP so terminal hangup signals never terminate the process
signal.signal(signal.SIGHUP, signal.SIG_IGN)

# 2. Check flags early
is_mock = "-mock" in sys.argv or "--mock" in sys.argv
is_detached = "--detached" in sys.argv

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
import threading
import time
from pathlib import Path
import psutil
from PIL import Image, ImageDraw
import pystray
from pystray import MenuItem as item
from pypresence import Presence, DiscordNotFound, InvalidID

CLIENT_ID = "1565766221813776505"
HUD_CROP_GEOM = "440x45+740+50"
MODE_LOCK_DELAY = 15
HUD_LOOKUP_RETRIES = 3        # Retries after the first failed lookup
HUD_LOOKUP_RETRY_DELAY = 2    # Seconds between lookup attempts
RESULTS_DISPLAY_DURATION = 10  # Seconds to hold "Viewing Results" after battle ends

LOG_FILE = Path.home() / ".cache/mech_arena_rpc.log"

STATE_CLOSED = 0
STATE_MENU = 1
STATE_BATTLE = 2

DOWNLOAD_BUTTONS = [
    {"label": "Download Mech Arena", "url": "https://plarium.com/en/game/mech-arena/"}
]

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
initial_matches = 4 if is_mock else parse_flag_arg("--matches", int, 0)

# Shared thread state
state_lock = threading.Lock()
current_ui_status = "In Battle (Deathmatch)" if is_mock else "Waiting for Mech Arena..."
match_count = initial_matches
is_running = True
tray_icon = None


def log(msg):
    """Prints to console (if attached) and writes timestamped lines to LOG_FILE."""
    timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{timestamp}] {msg}"
    if not is_detached:
        print(line)
    try:
        LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


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
    """Dynamically resolves the XWayland window ID for Mech Arena."""
    try:
        out = subprocess.check_output(["xwininfo", "-root", "-tree"], stderr=subprocess.DEVNULL).decode()
        for line in out.splitlines():
            if '"Mech Arena"' in line:
                match = re.search(r'(0x[0-9a-fA-F]+)', line)
                if match:
                    return match.group(1)
    except Exception:
        pass
    return None


def detect_hud_mode():
    """Differentiates Deathmatch, CPC, and FFA using ratio and absolute center floor."""
    win_id = get_mech_window_id()
    if not win_id:
        return None

    cmd = ["import", "-silent", "-window", win_id, "-crop", HUD_CROP_GEOM, "png:-"]

    try:
        proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=1.5)
        if proc.returncode != 0:
            return None
        img = Image.open(io.BytesIO(proc.stdout)).convert("L")
    except Exception:
        return None

    w, h = img.size
    pixels = img.load()

    edge_w = int(w * 0.15)
    center_start = int(w * 0.35)
    center_end = int(w * 0.65)

    left_edge_avg = sum(pixels[x, y] for x in range(edge_w) for y in range(h)) / (edge_w * h)
    right_edge_avg = sum(pixels[x, y] for x in range(w - edge_w, w) for y in range(h)) / (edge_w * h)
    center_avg = sum(pixels[x, y] for x in range(center_start, center_end) for y in range(h)) / ((center_end - center_start) * h)

    edge_avg = max((left_edge_avg + right_edge_avg) / 2.0, 1.0)
    ratio = center_avg / edge_avg

    log(f"HUD Analysis: Center={center_avg:.1f}, Edge={edge_avg:.1f}, Ratio(C/E)={ratio:.2f}")

    if ratio <= 0.88 or edge_avg >= 150:
        return "Deathmatch"
    if center_avg >= 95 and ratio >= 1.20:
        return "Control Point Clash"
    if center_avg < 95:
        return "Free-For-All"

    return "In Battle"


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
            if name and "mecharena.exe" in name.lower():
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

    # Handle Mock mode: locks RPC to Deathmatch with 1h 8m elapsed and 4 matches played
    if is_mock:
        log("[*] Running in MOCK mode (-mock flag detected).")
        mock_start = int(time.time()) - (68 * 60)  # 1 hour and 8 minutes
        active_session_start = mock_start

        # Allow main thread to initialize tray_icon
        time.sleep(0.5)
        set_status("In Battle (Deathmatch)")

        while is_running and rpc is None:
            try:
                rpc = Presence(CLIENT_ID)
                rpc.connect()
                log("Connected to Discord RPC (Mock Mode).")
                rpc.update(
                    details="In Battle (Deathmatch)",
                    state=f"Session: {get_stats_summary()}",
                    start=mock_start,
                    large_image="mech_arena_logo",
                    large_text="Mech Arena",
                    buttons=DOWNLOAD_BUTTONS
                )
            except (DiscordNotFound, InvalidID, ConnectionRefusedError):
                rpc = None
                time.sleep(2)

        while is_running:
            time.sleep(2)

        if rpc is not None:
            try:
                rpc.clear()
                rpc.close()
            except Exception:
                pass
        return

    # Normal daemon flow
    last_state = STATE_CLOSED
    session_start = initial_session_start
    battle_start = None
    locked_mode = None
    results_until = None

    log("Mech Arena RPC daemon started. Waiting for game...")

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
                    log("Status: In Battle (Waiting 15s to detect mode...)")

                    rpc.update(
                        details="In Battle",
                        state=f"Session: {get_stats_summary()}",
                        start=battle_start,
                        large_image="mech_arena_logo",
                        large_text="Mech Arena",
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
                            large_image="mech_arena_logo",
                            large_text="Mech Arena",
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
                        large_image="mech_arena_logo",
                        large_text="Mech Arena",
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
                        large_image="mech_arena_logo",
                        large_text="Mech Arena",
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
                        large_image="mech_arena_logo",
                        large_text="Mech Arena",
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

        time.sleep(2)

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


def on_show_log(icon, menu_item):
    """Opens the log file in a live terminal viewer or GUI text editor."""
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    if not LOG_FILE.exists():
        LOG_FILE.touch()

    terminals = [
        ["ghostty", "-e", "tail", "-f", str(LOG_FILE)],
        ["kitty", "-e", "tail", "-f", str(LOG_FILE)],
        ["alacritty", "-e", "tail", "-f", str(LOG_FILE)],
        ["konsole", "-e", "tail", "-f", str(LOG_FILE)],
    ]

    for term_cmd in terminals:
        if shutil.which(term_cmd[0]):
            subprocess.Popen(term_cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return

    gui_openers = ["kate", "kwrite", "gedit", "xdg-open"]
    for opener in gui_openers:
        if shutil.which(opener):
            subprocess.Popen([opener, str(LOG_FILE)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return


def on_restart(icon, menu_item):
    """
    Relaunches the script file on disk to pick up code modifications while preserving
    session start timestamp and current match count seamlessly.
    """
    global is_running
    log("Reloading updated script from disk (preserving session state)...")

    script_path = os.path.abspath(__file__)
    args = [sys.executable, script_path, "--detached"]

    if is_mock:
        args.append("-mock")

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
    args = [sys.executable, script_path, "--detached"]

    if is_mock:
        args.append("-mock")

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

    menu = pystray.Menu(
        item(get_menu_status_text, None, enabled=False),
        item(get_menu_stats_text, None, enabled=False),
        pystray.Menu.SEPARATOR,
        item("Restart / Apply Update", on_restart),
        item("Reset Match Counter", on_reset_stats),
        item("Show Log", on_show_log),
        item("Dispatch (Detach Terminal)", on_dispatch, enabled=lambda item: not is_detached),
        pystray.Menu.SEPARATOR,
        item("Quit", on_quit)
    )

    initial_title = (
        f"Mech Arena: In Battle (Deathmatch) | {get_stats_summary()}"
        if is_mock
        else "Mech Arena: Waiting for game..."
    )

    tray_icon = pystray.Icon(
        name="mech_arena_rpc",
        icon=create_tray_icon_image(),
        title=initial_title,
        menu=menu
    )

    worker_thread = threading.Thread(target=rpc_worker, daemon=True)
    worker_thread.start()

    tray_icon.run()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        is_running = False
        sys.exit(0)