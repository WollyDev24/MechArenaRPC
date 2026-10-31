import subprocess
import io
from PIL import Image

def analyze_beacon_row():
    # Crop horizontal band where beacons sit (y=50 to y=85 inside top HUD)
    crop_geom = "440x35+740+55"
    cmd = ["import", "-window", "0x4a00001", "-crop", crop_geom, "png:-"]
    
    proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if proc.returncode != 0:
        print(f"[-] Capture failed: {proc.stderr.decode()}")
        return

    img = Image.open(io.BytesIO(proc.stdout)).convert("L")
    img.save("/home/wolly/DiscordRPC/beacon_strip.png")
    print("[*] Saved captured strip to /home/wolly/DiscordRPC/beacon_strip.png")

    width, height = img.size
    pixels = img.load()

    # Calculate average brightness per column
    col_brightness = []
    for x in range(width):
        col_sum = sum(pixels[x, y] for y in range(height))
        col_brightness.append(col_sum / height)

    avg_brightness = sum(col_brightness) / len(col_brightness)
    threshold = avg_brightness + 15

    peaks = 0
    in_peak = False

    for val in col_brightness:
        if val > threshold and not in_peak:
            peaks += 1
            in_peak = True
        elif val <= threshold:
            in_peak = False

    print(f"[*] Detected Brightness Peaks across row: {peaks}")

    if peaks >= 4:
        print("[>] Mode: Control Point Clash (Beacons Active)")
    else:
        print("[>] Mode: Deathmatch / FFA")

if __name__ == "__main__":
    analyze_beacon_row()