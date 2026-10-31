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

# Check both ASCII/UTF-8 and UTF-16LE representations
TARGETS = {
    "Beacon (CPC)": [b"Beacon", "Beacon".encode("utf-16le")],
    "EmblemControl (CPC)": [b"BattleEmblemControl", "BattleEmblemControl".encode("utf-16le")],
    "KillLeader (FFA)": [b"BattleMessageNewKillLeader", "BattleMessageNewKillLeader".encode("utf-16le")],
    "EmblemFFA (FFA)": [b"BattleEmblemFFA", "BattleEmblemFFA".encode("utf-16le")],
    "Emblem5x5 (DM)": [b"BattleEmblem5x5", "BattleEmblem5x5".encode("utf-16le")],
    "Emblem2x2 (DM)": [b"BattleEmblem2x2", "BattleEmblem2x2".encode("utf-16le")]
}

counts = {k: 0 for k in TARGETS}

maps_path = f"/proc/{pid}/maps"
mem_path = f"/proc/{pid}/mem"

with open(maps_path, 'r') as maps_file, open(mem_path, 'rb', 0) as mem_file:
    for line in maps_file:
        parts = line.split()
        perms = parts[1]
        
        # Only scan readable+writable memory
        if not perms.startswith('rw'):
            continue
        if len(parts) > 5 and parts[5].startswith(('/dev', '[vvar]', '[vdso]')):
            continue

        addr_range = parts[0].split('-')
        start = int(addr_range[0], 16)
        end = int(addr_range[1], 16)
        length = end - start

        if length > 30 * 1024 * 1024:
            continue

        try:
            mem_file.seek(start)
            chunk = mem_file.read(length)
            for label, tokens in TARGETS.items():
                for token in tokens:
                    counts[label] += chunk.count(token)
        except (OSError, PermissionError):
            continue

print("=== Active Mode String Frequencies ===")
for label, cnt in counts.items():
    print(f"{label:<24}: {cnt}")