import serial
import time
import json
import requests

SERIAL_PORT = "/dev/cu.usbmodem101"   # change to port, set to None to auto-detect
BAUD = 115200
BACKEND_URL = "http://127.0.0.1:5000/api/event"  # Flask server
MIN_INTERVAL = 2  # Minimum seconds between events

last_event_time = 0

def send_to_backend(payload):
    try:
        r = requests.post(BACKEND_URL, json=payload, timeout=5)
        print("POST", r.status_code, r.text)
    except Exception as e:
        print("Error posting to backend:", e)

def run():
    global last_event_time
    
    # Determine which port to open. If SERIAL_PORT is set and available, use it.
    from serial.tools import list_ports

    def choose_port(preferred=None):
        # If a preferred port is given, try it first
        if preferred:
            try:
                s = serial.Serial(preferred, BAUD, timeout=1)
                s.close()
                return preferred
            except Exception:
                print(f"Preferred port {preferred} not available.")

        ports = list_ports.comports()
        if not ports:
            print("No serial ports found. Is your device connected?")
            return None

        # Heuristic: prefer tty/cu devices and USB descriptions
        candidates = []
        for p in ports:
            dev = getattr(p, 'device', str(p))
            desc = getattr(p, 'description', '')
            candidates.append((dev, desc))

        # Print candidates
        print("Available serial ports:")
        for i, (dev, desc) in enumerate(candidates, start=1):
            print(f" {i}) {dev}  {desc}")

        # Interactive confirmation if possible
        try:
            import sys
            if sys.stdin.isatty():
                choice = input(f"Select port [1] or enter number (q to quit): ").strip()
                if choice.lower() == 'q':
                    return None
                if choice == '':
                    idx = 1
                else:
                    try:
                        idx = int(choice)
                    except ValueError:
                        print("Invalid selection, using first port.")
                        idx = 1
                idx = max(1, min(len(candidates), idx))
                return candidates[idx-1][0]
            else:
                # Non-interactive: auto-select first
                print("Non-interactive shell: auto-selecting first available port.")
                return candidates[0][0]
        except Exception:
            return candidates[0][0]

    print("Opening serial", SERIAL_PORT if SERIAL_PORT else "(auto-detect)")
    chosen = choose_port(SERIAL_PORT)
    if not chosen:
        print("No port chosen, exiting.")
        return

    try:
        ser = serial.Serial(chosen, BAUD, timeout=1)
    except Exception as e:
        print(f"Could not open port {chosen}: {e}")
        return
    
    print(f"Connected to {chosen}")
    time.sleep(2)  # wait for Arduino reset
    
    while True:
        try:
            line = ser.readline().decode(errors="ignore").strip()
            if not line:
                continue
            
            print("Serial:", line)

            # Attempt to parse JSON; fallback to raw line
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                payload = {"raw": line}

            payload.setdefault("device_id", "ELEGOO_PROTO_01")
            payload.setdefault("timestamp_ms", int(time.time() * 1000))

            # Rate-limiting: skip if last event was too recent
            current_time = payload["timestamp_ms"]
            if last_event_time > 0 and (current_time - last_event_time) < (MIN_INTERVAL * 1000):
                print(f"  (Skipped - too soon after last event)")
                continue

            last_event_time = current_time
            send_to_backend(payload)
            
        except KeyboardInterrupt:
            print("\nStopping bridge")
            break
        except Exception as e:
            print("Serial read error:", e)
            time.sleep(1)

if __name__ == "__main__":
    run()