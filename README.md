# Wall-E_2025

Wall-E 2.0: the relaunch of the Wall-E replica robot, now running on an
NVIDIA Jetson Xavier NX. The original Raspberry Pi + Arduino code lives in
[Lichter1/Wall-E](https://github.com/Lichter1/Wall-E).

## Status

Phase 0, bring-up: tracks, servos and the Xbox controller each work on their
own and together in a basic teleop. See
[docs/roadmap-first-features.md](docs/roadmap-first-features.md).

## Getting started

1. [docs/jetson-setup.md](docs/jetson-setup.md): reflash and prepare the Jetson
2. [docs/wiring.md](docs/wiring.md): power, protection and every connection
3. Run the tools in order:

```bash
python3 tools/controller_test.py   # see the stick values
python3 tools/servo_test.py        # move and calibrate servos
python3 tools/drive_test.py        # spin the tracks (robot on a stand!)
python3 tools/teleop.py --head     # drive: hold LB, left stick; right stick = head
```

Add `--mock` to any tool to run without hardware. Tests: `python3 -m pytest -q`.

## Layout

```
config/robot.yaml        pins, servo channels, limits, tuning
walle/mathx.py           deadzone, expo, slew limiter
walle/hardware/          PCA9685 driver, servos, L298N differential drive
walle/inputs/xbox.py     Xbox controller over evdev
tools/                   test and teleop scripts
docs/                    setup guide, wiring, roadmap
tests/                   hardware-free unit tests
```

## Teleop controls

| Input | Action |
|---|---|
| Hold LB | deadman, tracks only move while held |
| Left stick | drive |
| Y | toggle slow mode |
| B / Menu | e-stop / clear e-stop |
| Right stick | head pan and tilt (`--head`) |
| A | centre head (`--head`) |
