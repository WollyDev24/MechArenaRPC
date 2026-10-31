import os
import re
import psutil

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

# Patterns for active battle scenes
tag_pattern = re.compile(rb'\b(CPC_[A-Za-z0-9_]+|FFA_[A-Za-z0-9_]+|TDM_[A-Za-z0-9_]+|DM_[A-Za-z0-9_]+)\b')
found = set()

maps_path = f"/proc/{pid}/maps"
mem_path = f"/proc/{pid}/mem"

with open(maps_path, 'r') as maps_file, open(mem_path, 'rb', 0) as mem_file:
    for line in maps_file:
        parts = line.split()
        perms = parts[1]
        
        # Only check writable private pages (rw-p) that are NOT file-backed (anonymous heap)
        if perms != 'rw-p' or len(parts) > 5:
            continue

        addr_range = parts[0].split('-')
        start = int(addr_range[0], 16)
        end = int(addr_range[1], 16)
        length = end - start

        # Only read standard heap allocations (between 64KB and 8MB)
        if length < 65536 or length > 8 * 1024 * 1024:
            continue

        try:
            mem_file.seek(start)
            chunk = mem_file.read(length)
            for match in tag_pattern.findall(chunk):
                found.add(match.decode('ascii', errors='ignore'))
        except (OSError, PermissionError):
            continue

print(f"[*] Detected Active Map/Mode Tags: {found}")