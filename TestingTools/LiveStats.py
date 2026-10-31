import subprocess
import io
import re
from PIL import Image

def get_mech_window_id():
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

def dump_cpc_numbers():
    win_id = get_mech_window_id()
    if not win_id:
        print("[-] Mech Arena window not found.")
        return

    # Ally (Blue) and Enemy (Red) score regions
    crops = {
        "cpc_ally_pct.png": "65x32+710+45",
        "cpc_enemy_pct.png": "65x32+1145+45"
    }

    for fname, geom in crops.items():
        cmd = ["import", "-silent", "-window", win_id, "-crop", geom, f"png:{fname}"]
        subprocess.run(cmd)
        print(f"[+] Dumped {fname}")

if __name__ == "__main__":
    dump_cpc_numbers()