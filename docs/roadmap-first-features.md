# Roadmap: from first features to an integrated robot

This covers the motion stack (drive, controller, servos) and how it grows. The
project-wide feature roadmap and code review live in their own documents.

## What changed from the old setup

The old robot ran **Raspberry Pi → USB serial → Arduino**. The Pi read the
joystick and sent `"speed turn headX headY"` strings; the Arduino drove the
L298N and the PCA9685 (at I2C address 0x7F). The new setup drops the Arduino
for now: the Jetson drives the L298N from its own PWM/GPIO pins and the PCA9685
directly over I2C. That removes the serial protocol, its handshake stalls, and
a second codebase.

If later we want hard real-time behaviour or a hardware failsafe independent
of Linux, a small microcontroller can come back as a motor co-processor behind
the same `DifferentialDrive` interface.

## Phase 0: bring-up (this PR)

- [x] Config file for pins, servo channels and limits (`config/robot.yaml`)
- [x] PCA9685 driver without Adafruit Blinka (works on Python 3.6)
- [x] Calibrated servos with per-joint soft limits
- [x] Differential drive: arcade mixing, ramping, minimum duty, speed cap,
      watchdog that stops the motors if the control loop stalls
- [x] Xbox controller reader (USB or Bluetooth, auto-reconnect)
- [x] Tools: `controller_test`, `servo_test` (with calibration), `drive_test`, `teleop`
- [x] Teleop safety: hold-to-drive deadman (LB), latched e-stop (B), stop on
      controller disconnect
- [ ] **You:** flash the Jetson, wire, run the four tools in order
      ([jetson-setup.md](jetson-setup.md))
- [ ] **You:** calibrate all 7 servos and commit `config/servo_calibration.yaml`
- [ ] **You:** tune `min_duty`, `max_speed`, `turn_gain` on the floor

## Phase 1: integrate the three pieces

Steps in order, each one testable on its own:

1. **Head on the right stick.** Already there as `teleop.py --head`; verify
   it with real servos and tune the rate.
2. **Every joint on the pad.** Proposed mapping: D-pad = eyes (tilt/sad/happy
   poses), triggers = left/right arm raise, right stick click = head home.
3. **Smooth servo motion.** Per-joint slew limiting so a button press moves a
   joint over ~0.3 s instead of snapping (less current spike, more Wall-E).
4. **Power-on and power-off poses.** Move slowly to home at start, to a
   "tucked" pose and release at shutdown.
5. **One robot process.** Replace the separate tools with a `walle` service
   with a small state machine: `IDLE → TELEOP → ESTOP`, later `AUTONOMOUS`.
6. **Start on boot.** systemd unit so the robot is drivable without SSH, and
   a status LED or sound for "ready / controller connected / e-stop".

## Phase 2: robustness

- Battery voltage and current monitoring (INA219/INA226 on the same I2C bus),
  low-battery warning and cut-off
- Logging to file, crash restart via systemd
- A physical e-stop that cuts motor and servo power independently of software
- Unit tests stay runnable without hardware (`--mock`, `pytest`)

## Phase 3: camera and tracking

- Camera capture through GStreamer (CSI or USB)
- Port the old face detection (`FaceDetect&Move.py`, Haar cascade) to a
  Jetson-accelerated detector (jetson-inference / TensorRT)
- Head tracking with the old PID idea (`PID controal.py`) driving head_pan
  and neck servos
- Teleop mode switch: manual head vs. "follow face"

## Phase 4: personality

- Animation sequences (poses with timing) played from buttons
- Sound: Wall-E voice clips through a small speaker/amp
- Phone or web control panel
- If moving to an Orin Nano: consider ROS 2 for navigation and mapping

## Open decisions

- **Which Jetson exactly?** Nano vs Orin Nano changes two pin numbers and the
  JetPack version (see setup guide). Everything else is the same.
- **Keep an Arduino in the loop?** Current plan says no; revisit in Phase 2
  if Linux jitter or failsafe behaviour becomes a problem.
- **L298N long term.** It wastes ~2-4 V as heat and limits current. A MOSFET
  driver (e.g. Cytron MDD10A or a BTS7960 pair) is a drop-in upgrade for the
  same pin interface; flagged for the electronics wishlist.
