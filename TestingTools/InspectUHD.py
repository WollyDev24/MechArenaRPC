import subprocess
import io
import re
from PIL import Image

def get_mech_window_id():
    out = subprocess.check_output(["xwininfo", "-root", "-tree"]).decode()
    for line in out.splitlines():
        if '"Mech Arena"' in line:
            match = re.search(r'(0x[0-9a-fA-F]+)', line)
            if match:
                return match.group(1)
    return "0x4a00001"

win_id = get_mech_window_id()
print(f"[*] Targeting Window ID: {win_id}")

# Target top-center HUD (500x120 centered at 1920x1080)
# X offset = (1920 - 500) // 2 = 710, Y offset = 0
crop_geom = "500x120+710+0"
cmd = ["import", "-window", win_id, "-crop", crop_geom, "png:-"]

proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
if proc.returncode != 0:
    print(f"[-] Capture failed: {proc.stderr.decode()}")
    exit(1)

img = Image.open(io.BytesIO(proc.stdout)).convert("RGB")
img.save("/home/wolly/DiscordRPC/current_hud.png")
print("[+] Saved HUD snapshot to /home/wolly/DiscordRPC/current_hud.png")

cyan = 0
red = 0
gold = 0

# Direct tuple unpacking (works across all Pillow versions)
for r, g, b in list(img.getdata()):
    # Cyan Beacon / capture bar (high blue and green, low red)
    if b > 150 and g > 120 and r < 100:
        cyan += 1
    # Red Enemy Beacon / bar
    elif r > 170 and g < 80 and b < 80:
        red += 1
    # Gold FFA badge
    elif r > 190 and g > 140 and b < 70:
        gold += 1

print(f"[*] Cyan Pixels : {cyan}")
print(f"[*] Red Pixels  : {red}")
print(f"[*] Gold Pixels : {gold}")