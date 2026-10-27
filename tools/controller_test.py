#!/usr/bin/env python3
"""Live view of the Xbox controller state. Ctrl+C to quit.

  python3 tools/controller_test.py          # normalised state
  python3 tools/controller_test.py --raw    # raw evdev events (to check mapping)
"""

import argparse
import sys
import time

import _bootstrap  # noqa: F401
from walle.config import load_config


def raw_mode(device_path):
    import evdev
    from walle.inputs.xbox import find_gamepad
    dev = find_gamepad(device_path)
    if dev is None:
        sys.exit("No gamepad found. Is it paired / plugged in? Try: ls -l /dev/input/by-id/")
    print("Reading %s (%s)" % (dev.name, dev.path))
    for event in dev.read_loop():
        if event.type in (evdev.ecodes.EV_KEY, evdev.ecodes.EV_ABS):
            print(evdev.categorize(event), "value=%d" % event.value)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--raw", action="store_true", help="print raw evdev events")
    args = parser.parse_args()
    cfg = load_config()["controller"]

    if args.raw:
        return raw_mode(cfg["device"])

    from walle.inputs.xbox import XboxController
    pad = XboxController(cfg["device"])
    print("Waiting for controller...")
    try:
        while True:
            if not pad.connected:
                sys.stdout.write("\r(no controller)" + " " * 70)
            else:
                s = pad.state
                held = [k for k, v in s.items() if v is True]
                sys.stdout.write(
                    "\rL(%+.2f,%+.2f) R(%+.2f,%+.2f) LT %.2f RT %.2f dpad(%+d,%+d) %-24s"
                    % (s["lx"], s["ly"], s["rx"], s["ry"], s["lt"], s["rt"],
                       s["dpad_x"], s["dpad_y"], " ".join(held)))
            sys.stdout.flush()
            time.sleep(0.05)
    except KeyboardInterrupt:
        print()
    finally:
        pad.close()


if __name__ == "__main__":
    main()
