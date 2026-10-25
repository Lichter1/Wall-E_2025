#!/usr/bin/env python3
"""Scripted DC motor test. PUT THE ROBOT ON A STAND, tracks off the ground.

Runs each track forward and back on its own, then both together, so you can
check wiring and direction before trying teleop.

  python3 tools/drive_test.py            # real motors
  python3 tools/drive_test.py --mock     # print only
  python3 tools/drive_test.py --speed 0.4
"""

import argparse
import time

import _bootstrap  # noqa: F401
from walle.config import load_config
from walle.hardware.drive import open_drive


def run_step(drive, label, throttle, turn, seconds):
    print("%-28s" % label, end="", flush=True)
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        left, right = drive.drive(throttle, turn)
        time.sleep(0.02)
    print("duty L %+.2f R %+.2f" % (left, right))
    drive.stop()
    time.sleep(0.7)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--mock", action="store_true")
    parser.add_argument("--speed", type=float, default=0.5, help="command level 0-1 (default 0.5)")
    parser.add_argument("--seconds", type=float, default=1.5)
    args = parser.parse_args()

    drive = open_drive(load_config()["drive"], mock=args.mock)
    drive.start_watchdog()
    s, t = args.speed, args.seconds
    # A pure spin (throttle 0, turn +/-1) drives one track forward and the other back.
    steps = [
        ("forward", s, 0.0),
        ("reverse", -s, 0.0),
        ("spin right (L fwd, R back)", 0.0, s),
        ("spin left (L back, R fwd)", 0.0, -s),
    ]
    try:
        input("Robot on a stand, tracks clear? Enter to start, Ctrl+C to abort. ")
        for label, throttle, turn in steps:
            run_step(drive, label, throttle, turn, t)
        print("Done. If a track ran the wrong way, set drive.<side>.inverted in config/robot.yaml.")
    except KeyboardInterrupt:
        print("\nAborted.")
    finally:
        drive.close()
        if drive.gpio:
            drive.gpio.cleanup()


if __name__ == "__main__":
    main()
