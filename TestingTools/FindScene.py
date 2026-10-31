import os
import psutil
import re

def get_mech_pid():
    for p in psutil.process_iter(['name', 'pid']):
        if p.info['name'] and "mecharena.exe" in p.info['name'].lower():
            return p.info['pid']
    return None

pid = get_mech_pid()
if not pid:
    print("MechArena.exe is not running.")
    exit(1)

maps_path = f"/proc/{pid}/maps"
mem_path = f"/proc/{pid}/mem"

# Unity scenes often have names matching these patterns
scene_pattern = re.compile(rb'Battle[A-Za-z0-9_]{2,30}|CPC_[A-Za-z0-9_]+|FFA_[A-Za-z0-9_]+|TDM_[A-Za-z0-9_]+')

# Test candidates in UTF-16LE (Unity standard string representation)
utf16_targets = {
    "ControlPoint": "ControlPoint".encode("utf-16le"),
    "DeathMatch": "DeathMatch".encode("utf-16le"),
    "FreeForAll": "FreeForAll".encode("utf-16le"),
    "Beacon": "Beacon".encode("utf-16le"),
    "5v5": "5v5".encode("utf-16le"),
    "2v2": "2v2".encode("utf-16le")
}

counts = {k: 0 for k in utf16_targets}
found_scenes = set()

with open(maps_path, 'r') as maps_file, open(mem_path, 'rb', 0) as mem_file:
    for line in maps_file:
        parts = line.split()
        perms = parts[1]
        
        # Only inspect readable + writable heap/anonymous regions
        if not perms.startswith('rw'):
            continue
        if len(parts) > 5 and parts[5].startswith(('/dev', '[vvar]', '[vdso]')):
            continue

        addr_range = parts[0].split('-')
        start = int(addr_range[0], 16)
        end = int(addr_range[1], 16)
        length = end - start

        # Avoid scanning blocks larger than 30MB to keep it fast
        if length > 30 * 1024 * 1024:
            continue

        try:
            mem_file.seek(start)
            chunk = mem_file.read(length)
            
            # Search scene names
            for match in scene_pattern.findall(chunk):
                try:
                    found_scenes.add(match.decode('ascii'))
                except UnicodeDecodeError:
                    pass

            # Count dynamic UTF-16 occurrences
            for name, token in utf16_targets.items():
                counts[name] += chunk.count(token)

        except (OSError, PermissionError):
            continue

print(f"--- Scene Names Detected ---")
print(found_scenes if found_scenes else "[None]")

print(f"\n--- Dynamic String Frequencies (UTF-16LE) ---")
for name, cnt in counts.items():
    print(f"{name:15}: {cnt}")