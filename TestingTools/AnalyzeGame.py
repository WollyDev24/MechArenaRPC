import os
import re
import psutil

def get_mech_pid():
    for p in psutil.process_iter(['name', 'pid']):
        if p.info['name'] and "mecharena.exe" in p.info['name'].lower():
            return p.info['pid']
    return None

pid = get_mech_pid()
if not pid:
    print("MechArena.exe is not running.")
    exit(1)

print(f"Inspecting PID: {pid}")

# Targets to search in memory
TARGETS = [
    b"ControlPoint",
    b"DeathMatch",
    b"FreeForAll",
    b"Beacon",
    b"TeamDeathmatch"
]

maps_path = f"/proc/{pid}/maps"
mem_path = f"/proc/{pid}/mem"

found = set()

with open(maps_path, 'r') as maps_file, open(mem_path, 'rb', 0) as mem_file:
    for line in maps_file:
        parts = line.split()
        perms = parts[1]
        
        # Only read readable heap / anonymous memory regions
        if not perms.startswith('r'):
            continue
        if len(parts) > 5 and parts[5].startswith(('/dev', '[vvar]', '[vdso]')):
            continue

        addr_range = parts[0].split('-')
        start = int(addr_range[0], 16)
        end = int(addr_range[1], 16)
        length = end - start

        # Skip gigantic blocks to keep it fast
        if length > 50 * 1024 * 1024:
            continue

        try:
            mem_file.seek(start)
            chunk = mem_file.read(length)
            for target in TARGETS:
                if target in chunk:
                    found.add(target.decode('utf-8', errors='ignore'))
        except (OSError, PermissionError):
            continue

print(f"Found match strings in memory: {found}")