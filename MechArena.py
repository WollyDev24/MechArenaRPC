import time
import psutil
from pypresence import Presence, DiscordNotFound, InvalidID

# Replace with your Application ID from the Discord Developer Portal
CLIENT_ID = "1565766221813776505"

# Official download page
DOWNLOAD_BUTTONS = [
    {"label": "Download Mech Arena", "url": "https://plarium.com/en/game/mech-arena/"}
]

STATE_CLOSED = 0
STATE_MENU = 1
STATE_BATTLE = 2

def get_mech_state():
    for proc in psutil.process_iter(['name']):
        try:
            name = proc.info['name']
            if name and "mecharena.exe" in name.lower():
                connections = proc.net_connections(kind='udp')
                if len(connections) > 0:
                    return STATE_BATTLE
                return STATE_MENU
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return STATE_CLOSED

def main():
    rpc = None
    last_state = STATE_CLOSED
    session_start = None
    battle_start = None

    print("[*] Mech Arena RPC daemon started. Waiting for game...")

    while True:
        state = get_mech_state()

        # Connect to Discord if game is active
        if state != STATE_CLOSED and rpc is None:
            try:
                rpc = Presence(CLIENT_ID)
                rpc.connect()
                print("[+] Connected to Discord RPC.")
            except (DiscordNotFound, InvalidID, ConnectionRefusedError):
                rpc = None

        # Start persistent session timer once game is detected
        if state != STATE_CLOSED and session_start is None:
            session_start = int(time.time())

        if rpc is not None:
            if state != last_state:
                if state == STATE_BATTLE:
                    battle_start = int(time.time())
                    print("[>] Status: In Battle")
                    rpc.update(
                        details="In Battle",
                        state="Combat Session",
                        start=battle_start,
                        large_image="mech_arena_logo",
                        large_text="Mech Arena",
                        buttons=DOWNLOAD_BUTTONS
                    )
                elif state == STATE_MENU:
                    battle_start = None
                    print("[>] Status: Main Menu")
                    rpc.update(
                        details="In Hangar",
                        state="Main Menu",
                        start=session_start,
                        large_image="mech_arena_logo",
                        large_text="Mech Arena",
                        buttons=DOWNLOAD_BUTTONS
                    )
                elif state == STATE_CLOSED:
                    print("[-] Game closed. Clearing RPC.")
                    try:
                        rpc.clear()
                        rpc.close()
                    except Exception:
                        pass
                    rpc = None
                    session_start = None
                    battle_start = None

                last_state = state

        time.sleep(3)

if __name__ == "__main__":
    main()