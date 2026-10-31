#!/usr/bin/env python3
import subprocess
import io
import re
import time
import psutil
from PIL import Image

POLL_INTERVAL = 2.0
HUD_CROP_GEOM = "440x45+740+50"  # 1080p center HUD strip


def get_mech_process():
    """Finds the Mech Arena Wine process."""
    for proc in psutil.process_iter(['pid', 'name']):
        try:
            name = proc.info['name']
            if name and "mecharena" in name.lower():
                return proc
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return None


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


def has_active_battle_connection(proc):
    """
    Checks if Mech Arena has an active UDP socket open to a game server,
    which confirms the player is actively loaded into a live match.
    """
    try:
        connections = proc.net_connections(kind='udp')
        for conn in connections:
            if conn.raddr and conn.status == psutil.CONN_NONE:
                return True
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        pass
    return False


def detect_hud_mode(win_id):
    """
    Extracts the top HUD banner and calculates edge vs. center brightness profiles
    to deterministically differentiate CPC, Deathmatch, and FFA.
    """
    cmd = ["import", "-window", win_id, "-crop", HUD_CROP_GEOM, "png:-"]

    try:
        proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=1.5)
        if proc.returncode != 0:
            return "In Battle"
        img = Image.open(io.BytesIO(proc.stdout)).convert("L")
    except Exception:
        return "In Battle"

    w, h = img.size
    pixels = img.load()

    # Outer 15% edges vs middle 30% center
    edge_w = int(w * 0.15)
    center_start = int(w * 0.35)
    center_end = int(w * 0.65)

    left_edge_avg = sum(pixels[x, y] for x in range(edge_w) for y in range(h)) / (edge_w * h)
    right_edge_avg = sum(pixels[x, y] for x in range(w - edge_w, w) for y in range(h)) / (edge_w * h)
    center_avg = sum(pixels[x, y] for x in range(center_start, center_end) for y in range(h)) / ((center_end - center_start) * h)

    edge_avg = (left_edge_avg + right_edge_avg) / 2.0

    # 1. Deathmatch: Bright score wings (~180+)
    if edge_avg >= 120:
        return "Deathmatch"

    # 2. Control Point Clash: High center beacon cluster (>85), darker wings (~67)
    if center_avg >= 85 and center_avg > edge_avg:
        return "Control Point Clash"

    # 3. Free-For-All: Dim profile across the entire row
    if center_avg < 85 and edge_avg < 60:
        return "Free-For-All"

    return "In Battle"


def main():
    print("[*] Monitoring Mech Arena game state...")
    last_state = None

    while True:
        proc = get_mech_process()
        if not proc:
            if last_state != "Closed":
                print("[-] Mech Arena is not running.")
                last_state = "Closed"
            time.sleep(POLL_INTERVAL)
            continue

        in_battle = has_active_battle_connection(proc)

        if in_battle:
            win_id = get_mech_window_id()
            mode = detect_hud_mode(win_id) if win_id else "In Battle (No Window ID)"
            current_state = f"In Battle ({mode})"
        else:
            current_state = "In Hangar"

        if current_state != last_state:
            print(f"[>] State Changed: {current_state}")
            last_state = current_state

        time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n[*] Exiting.")