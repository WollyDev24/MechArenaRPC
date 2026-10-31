#!/usr/bin/env python3
import time
from pypresence import Presence, DiscordNotFound, InvalidID

CLIENT_ID = "1565766221813776505"

DOWNLOAD_BUTTONS = [
    {"label": "Download Mech Arena", "url": "https://plarium.com/en/game/mech-arena/"}
]

def main():
    print("[*] Connecting to Discord RPC...")
    try:
        rpc = Presence(CLIENT_ID)
        rpc.connect()
    except (DiscordNotFound, InvalidID, ConnectionRefusedError) as e:
        print(f"[-] Could not connect to Discord: {e}")
        return

    # 1 hour and 8 minutes ago
    mock_start_time = int(time.time()) - (68 * 60)

    print("[+] Connected! Setting mock presence...")
    print("    Mode:    In Battle (Deathmatch)")
    print("    Session: 4 Matches")
    print("    Elapsed: ~1h 08m")

    rpc.update(
        details="In Battle (Deathmatch)",
        state="Session: 7 Matches",
        start=mock_start_time,
        large_image="mech_arena_logo",
        large_text="Mech Arena",
        buttons=DOWNLOAD_BUTTONS
    )

    print("[*] Mock presence is live. Press Ctrl+C to stop.")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n[*] Exiting and clearing RPC...")
        try:
            rpc.clear()
            rpc.close()
        except Exception:
            pass

if __name__ == "__main__":
    main()