import socket
import struct
import re

# Listen on raw IP packets (requires sudo)
s = socket.socket(socket.AF_INET, socket.SOCK_RAW, socket.IPPROTO_UDP)

print("[*] Listening for Mech Arena battle handshake... Launch into a match!")

target_port = 7015
printable = re.compile(rb'[A-Za-z0-9_\-\.]{3,}')

packet_count = 0

while True:
    raw_packet, addr = s.recvfrom(65535)
    
    # Parse IP Header (first 20 bytes standard)
    ip_header = raw_packet[:20]
    iph = struct.unpack('!BBHHHBBH4s4s', ip_header)
    src_ip = socket.inet_ntoa(iph[8])
    dst_ip = socket.inet_ntoa(iph[9])
    
    # Parse UDP Header (8 bytes following IP header)
    ihl = (iph[0] & 0xF) * 4
    udp_header = raw_packet[ihl:ihl+8]
    udph = struct.unpack('!HHHH', udp_header)
    src_port = udph[0]
    dst_port = udph[1]
    
    if src_port == target_port or dst_port == target_port:
        payload = raw_packet[ihl+8:]
        strings_found = printable.findall(payload)
        
        # Clean decoded ascii strings
        clean_strings = [s.decode('ascii', errors='ignore') for s in strings_found if len(s) >= 3]
        
        if clean_strings:
            packet_count += 1
            direction = "->" if dst_port == target_port else "<-"
            print(f"[{packet_count}] {src_ip}:{src_port} {direction} {dst_ip}:{dst_port} (Len: {len(payload)})")
            print(f"    Payload strings: {clean_strings}")
            
        if packet_count >= 8:
            break

print("[*] Done capturing initial burst.")