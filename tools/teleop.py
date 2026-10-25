#!/usr/bin/env python3
"""Drive Wall-E with an Xbox controller.

  Hold LB          deadman: the tracks only move while LB is held
  Left stick       drive (up/down = throttle, left/right = turn)
  Y                toggle slow mode (half speed)
  B                emergency stop (latched)   Menu  clear the e-stop
  Right stick      head pan / neck tilt (only with --head)
  A                centre the head (only with --head)

  python3 tools/teleop.py [--head] [--mock]
"""

import argparse
import sys
import time

import _bootstrap  # noqa: F401
from walle.config import load_config
from walle.hardware.drive import open_drive
from walle.inputs.xbox import XboxController
from walle.mathx import apply_deadzone, apply_expo

LOOP_HZ = 50
HEAD_RATE_DEG_S = 90.0


class Teleop(object):
    def __init__(self, cfg, drive, head=None):
        self.cfg = cfg["controller"]
        self.drive = drive
        self.head = head   # (pan_servo, tilt_servo) or None
        self.estop = False
        self.slow = False

    def shape(self, value):
        return apply_expo(apply_deadzone(value, self.cfg["deadzone"]), self.cfg["expo"])

    def step(self, state, presses, connected, dt):
        """One control tick. Returns (throttle, turn) actually commanded."""
        if "b" in presses:
            self.estop = True
        if "menu" in presses:
            self.estop = False
        if "y" in presses:
            self.slow = not self.slow

        if not connected or self.estop or not state["lb"]:
            self.drive.stop()
            throttle = turn = 0.0
        else:
            scale = 0.5 if self.slow else 1.0
            throttle = self.shape(state["ly"]) * scale
            turn = self.shape(state["lx"]) * scale
            self.drive.drive(throttle, turn)

        if self.head and connected:
            pan, tilt = self.head
            if "a" in presses:
                pan.go_home()
                tilt.go_home()
            rx = apply_deadzone(state["rx"], self.cfg["deadzone"])
            ry = apply_deadzone(state["ry"], self.cfg["deadzone"])
            if rx:
                pan.nudge(-rx * HEAD_RATE_DEG_S * dt)
            if ry:
                tilt.nudge(ry * HEAD_RATE_DEG_S * dt)
        return throttle, turn


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--head", action="store_true", help="also drive head servos from the right stick")
    parser.add_argument("--mock", action="store_true", help="no motors or servos, just print")
    args = parser.parse_args()

    cfg = load_config()
    drive = open_drive(cfg["drive"], mock=args.mock, verbose=False)
    drive.start_watchdog()
    head = board = None
    if args.head:
        from walle.hardware.servos import ServoBank, open_servo_board
        board = open_servo_board(cfg["servos"], mock=args.mock, verbose=False)
        bank = ServoBank(board, cfg["servos"]["channels"])
        head = (bank.get("head_pan"), bank.get("neck_upper"))
        for servo in head:
            servo.go_home()

    pad = XboxController(cfg["controller"]["device"])
    teleop = Teleop(cfg, drive, head)
    print("Waiting for controller... (Ctrl+C to quit)")
    period = 1.0 / LOOP_HZ
    last = time.monotonic()
    was_connected = False
    try:
        while True:
            now = time.monotonic()
            dt, last = now - last, now
            connected = pad.connected
            if connected != was_connected:
                print("\nController %s" % ("connected: %s" % pad.name if connected else "LOST, motors stopped"))
                was_connected = connected
            throttle, turn = teleop.step(pad.state, pad.pop_presses(), connected, dt)
            status = "E-STOP (Menu clears)" if teleop.estop else ("slow" if teleop.slow else "normal")
            sys.stdout.write("\rthrottle %+.2f turn %+.2f  duty L %+.2f R %+.2f  %-22s"
                             % (throttle, turn, drive.duties[0], drive.duties[1], status))
            sys.stdout.flush()
            time.sleep(max(0.0, period - (time.monotonic() - now)))
    except KeyboardInterrupt:
        print()
    finally:
        pad.close()
        drive.close()
        if board:
            board.release_all()
        if drive.gpio:
            drive.gpio.cleanup()


if __name__ == "__main__":
    main()
