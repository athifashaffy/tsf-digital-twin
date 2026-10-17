"""Talk to the TSF node over USB: python board.py [command ...] — e.g. STATUS, SCAN, SERVER:ip:port"""
import sys, time
import serial

PORT = "/dev/cu.usbmodem1051DB2EBCF02"
for _ in range(30):
    try:
        s = serial.Serial(PORT, 115200, timeout=0.3)
        break
    except Exception:
        time.sleep(0.3)

def read(t):
    b, end = b"", time.time() + t
    while time.time() < end:
        b += s.read(4096)
    return b.decode("utf8", "replace")

out = read(3)
for cmd in sys.argv[1:]:
    s.write((cmd + "\n").encode())
    out += read(12 if cmd == "SCAN" else 3)
print(out)
