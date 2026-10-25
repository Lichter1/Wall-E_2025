#!/usr/bin/env python3
"""Interactive servo tester and calibrator for the PCA9685 board.

  python3 tools/servo_test.py           # real board
  python3 tools/servo_test.py --mock    # no hardware, prints pulses

Power the servo rail from its own 5-6 V supply before running this.
Type 'help' at the prompt for commands.
"""

import argparse
import time

import _bootstrap  # noqa: F401
from walle.config import load_config, save_calibration
from walle.hardware.servos import ServoBank, open_servo_board

HELP = """
  list               show configured channels and limits
  ch <n|name>        select a channel (0-15 or a name from robot.yaml)
  <angle>            move selected servo to angle (clamped to its limits)
  + [step] / - [step] nudge selected servo (default 5 degrees)
  sweep              slowly sweep min -> max -> home
  home | homeall     move selected / all configured servos to home
  off  | offall      stop pulses (servo goes limp) on selected / all
  us <pulse>         send a raw pulse in microseconds, IGNORING limits
  setmin | setmax | sethome   store current angle as a limit for this channel
  save               write limits to config/servo_calibration.yaml
  q                  release all servos and quit
"""


def show(bank):
    for ch, s in sorted(bank.servos.items()):
        marker = "" if s.angle is None else " at %d" % s.angle
        print("  %2d %-12s limits %3d-%3d home %3d pulse %d-%dus%s"
              % (ch, s.name, s.min_angle, s.max_angle, s.home, s.min_us, s.max_us, marker))


def sweep(servo, step=2, delay=0.03):
    for angle in range(int(servo.min_angle), int(servo.max_angle) + 1, step):
        servo.move(angle)
        time.sleep(delay)
    for angle in range(int(servo.max_angle), int(servo.home) - 1, -step):
        servo.move(angle)
        time.sleep(delay)
    servo.go_home()


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--mock", action="store_true", help="run without hardware")
    args = parser.parse_args()

    cfg = load_config()
    board = open_servo_board(cfg["servos"], mock=args.mock)
    bank = ServoBank(board, cfg["servos"]["channels"])
    current = None
    print("Servo tester. 'help' for commands.")
    show(bank)

    try:
        while True:
            prompt = "[%s] > " % (current.name if current else "no channel")
            try:
                line = input(prompt).strip()
            except EOFError:
                break
            if not line:
                continue
            cmd, _, arg = line.partition(" ")
            arg = arg.strip()
            try:
                if cmd in ("q", "quit", "exit"):
                    break
                elif cmd == "help":
                    print(HELP)
                elif cmd == "list":
                    show(bank)
                elif cmd == "ch":
                    current = bank.get(arg)
                    print("Selected %s (channel %d)" % (current.name, current.channel))
                elif cmd == "homeall":
                    bank.home_all()
                elif cmd == "offall":
                    bank.release_all()
                elif current is None:
                    print("Select a channel first: ch <n>")
                elif cmd in ("+", "-"):
                    step = float(arg) if arg else 5.0
                    print("-> %.0f" % current.nudge(step if cmd == "+" else -step))
                elif cmd == "sweep":
                    sweep(current)
                elif cmd == "home":
                    current.go_home()
                elif cmd == "off":
                    current.release()
                elif cmd == "us":
                    board.set_pulse_us(current.channel, int(arg))
                    current.angle = None
                elif cmd in ("setmin", "setmax", "sethome"):
                    if current.angle is None:
                        print("Move the servo to an angle first.")
                    else:
                        setattr(current, {"setmin": "min_angle", "setmax": "max_angle",
                                          "sethome": "home"}[cmd], current.angle)
                        print("Stored. Remember to 'save'.")
                elif cmd == "save":
                    save_calibration({ch: s.settings() for ch, s in bank.servos.items()})
                    print("Saved to config/servo_calibration.yaml")
                else:
                    angle = float(cmd)
                    print("-> %.0f" % current.move(angle))
            except (ValueError, KeyError) as exc:
                print("?", exc)
    except KeyboardInterrupt:
        print()
    finally:
        board.release_all()


if __name__ == "__main__":
    main()
