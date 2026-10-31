import subprocess
import io
import re
from PIL import Image
import pytesseract

def get_hud_text():
    crop_geom = "460x100+730+10"
    cmd = ["import", "-window", "Mech Arena", "-crop", crop_geom, "png:-"]
    
    proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if proc.returncode != 0:
        return ""

    img = Image.open(io.BytesIO(proc.stdout))
    gray = img.convert("L")
    threshold = 175
    binarized = gray.point(lambda p: 255 if p > threshold else 0)

    # psm 6 assumes a single uniform block of text
    text = pytesseract.image_to_string(binarized, config="--psm 6").strip()
    return text.lower()

def classify_mode(text):
    print(f"[*] Raw OCR: {repr(text)}")

    # 1. FFA Detection
    if any(k in text for k in ["ffa", "rank", "leader", "solo", "1st", "2nd", "3rd"]):
        return "Free-For-All"

    # 2. Deathmatch Detection: matches "0®0", "0-0", "0:0", "0 v 0", "12 - 8"
    if re.search(r'\d+\s*[\:\-\®\©\*\.\_\|vV]\s*\d+', text):
        return "Deathmatch"

    # 3. CPC Detection: Beacon letters or percentage gauges
    if re.search(r'\b[a-e]\b', text) or any(k in text for k in ["cpc", "beacon", "capture", "%"]):
        return "Control Point Clash"

    # Fallback heuristic based on your observed samples:
    # If there are multiple isolated letters across lines (beacon markers)
    if len(re.findall(r'[a-z]', text)) >= 3:
        return "Control Point Clash"

    return "In Battle"

if __name__ == "__main__":
    raw_text = get_hud_text()
    mode = classify_mode(raw_text)
    print(f"[>] Determined Game Mode: {mode}")