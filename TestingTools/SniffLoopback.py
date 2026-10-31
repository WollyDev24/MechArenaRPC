import socket
import struct
import re

# Bind to the loopback interface on raw TCP
s = socket.socket(socket.AF_INET, socket.SOCK_RAW, socket.IPPROTO_TCP)

print("[*] Listening on 127.0.0.1 for matchmaking IPC... Start matchmaking in Mech Arena!")

printable = re.compile(rb'[A-Za-z0-9_\-\.\:\/\"\{\}\[\]\,\s]{4,}')
INTERESTING_PORTS = {5200, 50306}

try:
    while True:
        raw_packet, addr = s.recvfrom(65535)

        # Parse IPv4 header
        ip_header = raw_packet[:20]
        iph = struct.unpack('!BBHHHBBH4s4s', ip_header)
        src_ip = socket.inet_ntoa(iph[8])
        dst_ip = socket.inet_ntoa(iph[9])

        if src_ip == "127.0.0.1" and dst_ip == "127.0.0.1":
            ihl = (iph[0] & 0xF) * 4
            tcp_header = raw_packet[ihl:ihl+20]
            tcph = struct.unpack('!HHLLBBHHH', tcp_header)
            src_port = tcph[0]
            dst_port = tcph[1]

            if src_port in INTERESTING_PORTS or dst_port in INTERESTING_PORTS:
                data_offset = (tcph[4] >> 4) * 4
                payload = raw_packet[ihl + data_offset:]

                if payload:
                    matches = printable.findall(payload)
                    text_chunks = [m.decode('ascii', errors='ignore').strip() for m in matches if len(m.strip()) > 3]
                    joined = " ".join(text_chunks)

                    # Filter for match/game setup keywords to ignore keep-alive heartbeats
                    keywords = ["battle", "mode", "match", "cpc", "ffa", "deathmatch", "room", "game", "ticket", "start"]
                    if any(k in joined.lower() for k in keywords):
                        print(f"\n[+] IPC ({src_port} -> {dst_port}) [Bytes: {len(payload)}]")
                        print(joined[:350])
except KeyboardInterrupt:
    print("\n[*] Stopped sniffing.")