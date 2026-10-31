import socket
import struct
import re

# Capture loopback TCP traffic on ports 5200 or 50306
s = socket.socket(socket.AF_INET, socket.SOCK_RAW, socket.IPPROTO_TCP)

print("[*] Sniffing loopback (127.0.0.1) IPC traffic... Matchmake or switch modes now!")

printable = re.compile(rb'[A-Za-z0-9_\-\.\:\/\"\{\}\[\]\,]{4,}')

while True:
    raw_packet, addr = s.recvfrom(65535)
    
    ip_header = raw_packet[:20]
    iph = struct.unpack('!BBHHHBBH4s4s', ip_header)
    src_ip = socket.inet_ntoa(iph[8])
    dst_ip = socket.inet_ntoa(iph[9])
    
    if src_ip == "127.0.0.1" and dst_ip == "127.0.0.1":
        ihl = (iph[0] & 0xF) * 4
        tcp_header = raw_packet[ihl:ihl+20]
        tcph = struct.unpack('!HHLLBBHHH', tcp_header)
        src_port, dst_port = tcph[0], tcph[1]
        
        # Check IPC ports
        if src_port in (5200, 50306) or dst_port in (5200, 50306):
            payload = raw_packet[ihl + (tcph[4] >> 4) * 4:]
            matches = printable.findall(payload)
            text_chunks = [m.decode('ascii', errors='ignore') for m in matches]
            joined = " ".join(text_chunks)
            
            # Print if payload looks like game/match metadata
            if any(k in joined.lower() for k in ["battle", "mode", "match", "cpc", "ffa", "deathmatch", "game"]):
                print(f"[IPC {src_port}->{dst_port}] {joined[:200]}")