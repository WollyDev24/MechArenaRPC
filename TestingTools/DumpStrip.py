import subprocess
import io
from PIL import Image

def inspect_strip():
    crop_geom = "440x45+740+50"
    cmd = ["import", "-window", "0x4a00001", "-crop", crop_geom, "png:-"]
    
    proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if proc.returncode != 0:
        print("Capture failed")
        return

    img = Image.open(io.BytesIO(proc.stdout)).convert("L")
    img.save("/home/wolly/DiscordRPC/beacon_strip_debug.png")
    
    w, h = img.size
    pixels = img.load()

    # Bin columns into 40 segments across width to print a low-res ASCII graph
    bucket_size = w // 40
    graph = []
    for b in range(40):
        col_vals = []
        for x in range(b * bucket_size, (b + 1) * bucket_size):
            for y in range(h):
                col_vals.append(pixels[x, y])
        graph.append(sum(col_vals) // len(col_vals))

    max_v = max(graph) if max(graph) > 0 else 1
    print("\n--- Horizontal Brightness Profile (Left -> Right) ---")
    line = "".join("#" if v > (max_v * 0.6) else "." for v in graph)
    print(f"[{line}]")
    print(f"Values (40 buckets): {graph}\n")

if __name__ == "__main__":
    inspect_strip()