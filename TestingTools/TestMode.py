import psutil
import re

def get_mech_pid():
    for p in psutil.process_iter(['name', 'pid']):
        try:
            name = p.info['name']
            if name and "mecharena" in name.lower():
                return p.info['pid']
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return None

pid = get_mech_pid()
print(f"[*] Mech Arena PID: {pid}")

if not pid:
    print("[-] Process not found. Make sure MechArena.exe is active.")
    exit(0)

maps_path = f"/proc/{pid}/maps"
mem_path = f"/proc/{pid}/mem"

# Track scenes and counts
map_pattern = re.compile(rb'(?:CPC|TDM|FFA|DeathMatch|Beacon)_[A-Za-z0-9_]+', re.IGNORECASE)
found_tags = set()
beacon_token = "Beacon".encode("utf-16le")
beacon_count = 0

try:
    with open(maps_path, 'r') as maps_file, open(mem_path, 'rb', 0) as mem_file:
        for line in maps_file:
            parts = line.split()
            perms = parts[1]
            if not perms.startswith('rw'):
                continue
            if len(parts) > 5 and parts[5].startswith(('/dev', '[vvar]', '[vdso]')):
                continue

            addr_range = parts[0].split('-')
            start = int(addr_range[0], 16)
            end = int(addr_range[1], 16)
            length = end - start

            if length > 25 * 1024 * 1024:
                continue

            try:
                mem_file.seek(start)
                chunk = mem_file.read(length)
                beacon_count += chunk.count(beacon_token)
                for match in map_pattern.findall(chunk):
                    try:
                        found_tags.add(match.decode('ascii'))
                    except UnicodeDecodeError:
                        pass
            except (OSError, PermissionError):
                continue
except PermissionError as e:
    print(f"[-] Permission error reading mem: {e}")
    exit(1)

print(f"[+] Beacon Count: {beacon_count}")
print(f"[+] Found Match Tags: {found_tags}")

if beacon_count > 150 or any(t.startswith("CPC") for t in found_tags):
    print("[>] Mode: Control Point Clash")
elif any(t.startswith("FFA") for t in found_tags):
    print("[>] Mode: Free-For-All")
else:
    print("[>] Mode: Deathmatch (5v5 / 2v2)")