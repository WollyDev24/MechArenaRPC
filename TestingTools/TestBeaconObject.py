import psutil
import re

def get_mech_pid():
    for p in psutil.process_iter(['name', 'pid']):
        try:
            if p.info['name'] and "mecharena" in p.info['name'].lower():
                return p.info['pid']
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return None

pid = get_mech_pid()
if not pid:
    print("[-] Mech Arena not running.")
    exit(1)

# Specific Unity component names used for physical beacon points
TARGET_OBJECTS = [
    b"BeaconController",
    b"BeaconView",
    b"CapturePointController",
    b"ControlPointView",
    b"BeaconIndicator",
    b"BeaconCaptureZone"
]

found_counts = {t.decode(): 0 for t in TARGET_OBJECTS}

maps_path = f"/proc/{pid}/maps"
mem_path = f"/proc/{pid}/mem"

with open(maps_path, 'r') as maps_file, open(mem_path, 'rb', 0) as mem_file:
    for line in maps_file:
        parts = line.split()
        perms = parts[1]
        
        # Only check private writable heap allocations
        if perms != 'rw-p' or len(parts) > 5:
            continue

        addr_range = parts[0].split('-')
        start = int(addr_range[0], 16)
        end = int(addr_range[1], 16)
        length = end - start

        # Skip buffers larger than 16MB to avoid stalls
        if length > 16 * 1024 * 1024:
            continue

        try:
            mem_file.seek(start)
            chunk = mem_file.read(length)
            for t in TARGET_OBJECTS:
                if t in chunk:
                    found_counts[t.decode()] += chunk.count(t)
        except (OSError, PermissionError):
            continue

print("=== Live Beacon Object Signatures ===")
for name, cnt in found_counts.items():
    print(f"{name:<25}: {cnt}")