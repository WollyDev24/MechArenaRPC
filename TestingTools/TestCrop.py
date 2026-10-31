import mss
from PIL import Image

with mss.MSS() as sct:
    # 1080p full screen capture
    full = sct.grab({"top": 0, "left": 0, "width": 1920, "height": 1080})
    img = Image.frombytes("RGB", full.size, full.bgra, "raw", "BGRX")
    img.save("/home/wolly/DiscordRPC/full_match.png")
    print("Saved /home/wolly/DiscordRPC/full_match.png")