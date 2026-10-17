# Firmware that was on the board before 2026-10-11

The compiled program could not be read back: the UNO R4 WiFi bootloader
refuses flash reads (`bossac -r` → "SAM-BA operation failed"), and the
source code was not in this folder. This is its serial output (115200 baud),
captured just before it was replaced, so its behaviour is on record.

Notable: it had a captive-portal login step ("Portal Auth") for a WiFi
network that requires a browser sign-in, printed one status line per second,
and sent to the server on an "Interval Tick".

```
Time: 66s | WiFi: OFF | Portal: NO-AUTH | Dist: NA | Water: 0% | Turb: 0.0 NTU | Flow: 0.16 L/min | Alert: NO

--- Interval Tick ---
Skipping server update:
  WiFi: Disconnected
  Portal Auth: No
Time: 67s | WiFi: OFF | Portal: NO-AUTH | Dist: NA | Water: 0% | Turb: 0.0 NTU | Flow: 0.16 L/min | Alert: NO
```

If you still have the original .ino (check the thesis author's laptop or
Arduino IDE sketchbook), put it in this folder.
