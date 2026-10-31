import os
from pathlib import Path
import UnityPy

CACHE_DIR = Path.home() / ".wine/drive_c/users/wolly/AppData/LocalLow/Unity/Plarium_Mech Arena"
OUTPUT_DIR = Path.home() / "DiscordRPC/extracted_mode_icons"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# Target specific folders that house mode graphics and dialogs
TARGET_FOLDERS = [
    "ToBattleDialog_SD",
    "PolygonFFA01_SD",
    "RankedTournamentShared_SD",
    "MapSpaceSetCPC_SD",
    "HudDebug_SD",
]

print("[*] Scanning selected bundles for icons...")

for folder_name in TARGET_FOLDERS:
    folder_path = CACHE_DIR / folder_name
    if not folder_path.exists():
        continue

    for root, _, files in os.walk(folder_path):
        for f in files:
            # Unity cache data files don't have .bundle extensions; they are raw hash names or __data
            file_path = os.path.join(root, f)
            try:
                env = UnityPy.load(file_path)
                for obj in env.objects:
                    if obj.type.name in ["Texture2D", "Sprite"]:
                        data = obj.read()
                        img = data.image
                        # Filter out tiny 1x1 dummy textures
                        if img.size[0] >= 64 and img.size[1] >= 64:
                            out_file = OUTPUT_DIR / f"{folder_name}_{data.name}.png"
                            img.save(out_file)
                            print(f"[+] Dumped: {out_file.name} ({img.size[0]}x{img.size[1]})")
            except Exception:
                continue

print(f"\n[*] Extraction complete! Check images inside: {OUTPUT_DIR}")