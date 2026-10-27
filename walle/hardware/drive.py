"""Differential (tank) drive on a dual H-bridge.

Two driver styles are supported, chosen by drive.driver in robot.yaml:

  l298n    one hardware PWM pin for speed (ENA/ENB) and two GPIOs for
           direction (IN1/IN2, IN3/IN4)
  pwm_dir  one PWM pin and one DIR pin per channel (Cytron MDD10A and
           similar MOSFET drivers)

The Jetson's 3.3 V logic is a valid high for both, so no level shifter is
needed, but the grounds must be tied together.
"""

import threading
import time

from walle.mathx import SlewLimiter, clamp


def mix_arcade(throttle, turn, turn_gain=1.0):
    """Arcade mix: throttle forward/back, turn > 0 spins clockwise (right).

    Returns (left, right) in [-1, 1]. When the sum saturates, both sides are
    scaled down together so the turning ratio is kept.
    """
    turn *= turn_gain
    left = throttle + turn
    right = throttle - turn
    biggest = max(abs(left), abs(right), 1.0)
    return left / biggest, right / biggest


def to_duty(value, min_duty, max_speed):
    """Map a [-1, 1] command to a signed duty cycle in [-max_speed, max_speed].

    Brushed gear motors do not turn below some duty (the old Arduino code
    zeroed anything under 70/255), so non-zero commands start at min_duty
    instead of wasting the first quarter of the stick.
    """
    if abs(value) < 1e-3:
        return 0.0
    min_duty = min(min_duty, max_speed)
    magnitude = min_duty + (max_speed - min_duty) * clamp(abs(value), 0.0, 1.0)
    return magnitude if value > 0 else -magnitude


class JetsonMotor(object):
    """One motor channel driven by Jetson.GPIO (BOARD pin numbering).

    Pass in1_pin and in2_pin for an L298N, or dir_pin for a PWM+DIR driver.
    """

    def __init__(self, gpio, pwm_pin, frequency_hz, in1_pin=None, in2_pin=None,
                 dir_pin=None, inverted=False):
        if dir_pin is None and (in1_pin is None or in2_pin is None):
            raise ValueError("need in1_pin and in2_pin, or dir_pin")
        self.gpio = gpio
        self.in1 = in1_pin
        self.in2 = in2_pin
        self.dir = dir_pin
        self.inverted = inverted
        pins = (dir_pin,) if dir_pin is not None else (in1_pin, in2_pin)
        for pin in pins + (pwm_pin,):
            gpio.setup(pin, gpio.OUT, initial=gpio.LOW)
        self.pwm = gpio.PWM(pwm_pin, frequency_hz)
        self.pwm.start(0)

    def set(self, duty):
        """duty in [-1, 1]; sign is direction."""
        if self.inverted:
            duty = -duty
        if self.dir is not None:
            # PWM+DIR drivers brake/coast on PWM low; DIR only matters while moving.
            self.gpio.output(self.dir, self.gpio.HIGH if duty >= 0 else self.gpio.LOW)
        elif duty > 0:
            self.gpio.output(self.in1, self.gpio.HIGH)
            self.gpio.output(self.in2, self.gpio.LOW)
        elif duty < 0:
            self.gpio.output(self.in1, self.gpio.LOW)
            self.gpio.output(self.in2, self.gpio.HIGH)
        else:
            # Both low lets the motor coast to a stop.
            self.gpio.output(self.in1, self.gpio.LOW)
            self.gpio.output(self.in2, self.gpio.LOW)
        self.pwm.ChangeDutyCycle(abs(duty) * 100.0)

    def close(self):
        self.set(0)
        self.pwm.stop()


class MockMotor(object):
    def __init__(self, name, verbose=False):
        self.name = name
        self.duty = 0.0
        self.verbose = verbose

    def set(self, duty):
        if self.verbose and abs(duty - self.duty) > 1e-6:
            print("[mock motor] %s -> %+.2f" % (self.name, duty))
        self.duty = duty

    def close(self):
        self.set(0)


class DifferentialDrive(object):
    """Turns (throttle, turn) commands into ramped, limited motor duties.

    A watchdog thread stops both motors if drive() is not called for
    watchdog_s seconds, so a crashed or hung control loop cannot leave the
    robot driving away.
    """

    def __init__(self, left, right, max_speed=0.6, min_duty=0.25, turn_gain=0.7,
                 ramp_per_s=2.0, watchdog_s=0.5, clock=time.monotonic):
        self.left = left
        self.right = right
        self.max_speed = max_speed
        self.min_duty = min_duty
        self.turn_gain = turn_gain
        self.clock = clock
        self.left_ramp = SlewLimiter(ramp_per_s)
        self.right_ramp = SlewLimiter(ramp_per_s)
        self.watchdog_s = watchdog_s
        self._lock = threading.Lock()
        self._last_command = clock()
        self._last_update = clock()
        self._watchdog = None
        self._running = False
        self.duties = (0.0, 0.0)

    def start_watchdog(self):
        if self.watchdog_s and not self._running:
            self._running = True
            self._watchdog = threading.Thread(target=self._watch, name="drive-watchdog")
            self._watchdog.daemon = True
            self._watchdog.start()

    def _watch(self):
        while self._running:
            time.sleep(self.watchdog_s / 4.0)
            with self._lock:
                stale = self.clock() - self._last_command > self.watchdog_s
                if stale and self.duties != (0.0, 0.0):
                    self._stop_locked()

    def drive(self, throttle, turn):
        """throttle, turn in [-1, 1]. Call this every loop iteration."""
        with self._lock:
            now = self.clock()
            dt = now - self._last_update
            self._last_update = now
            self._last_command = now
            left, right = mix_arcade(clamp(throttle, -1, 1), clamp(turn, -1, 1), self.turn_gain)
            left = self.left_ramp.update(left, dt)
            right = self.right_ramp.update(right, dt)
            self.duties = (to_duty(left, self.min_duty, self.max_speed),
                           to_duty(right, self.min_duty, self.max_speed))
            self.left.set(self.duties[0])
            self.right.set(self.duties[1])
            return self.duties

    def stop(self):
        """Immediate stop, bypassing the ramp."""
        with self._lock:
            self._stop_locked()

    def _stop_locked(self):
        self.left_ramp.reset()
        self.right_ramp.reset()
        self.duties = (0.0, 0.0)
        self.left.set(0.0)
        self.right.set(0.0)

    def close(self):
        self._running = False
        self.stop()
        self.left.close()
        self.right.close()


DRIVER_PINS = {
    "l298n": ("pwm_pin", "in1_pin", "in2_pin", "inverted"),
    "pwm_dir": ("pwm_pin", "dir_pin", "inverted"),
}


def _pick(side_cfg, keys):
    # Defaults carry L298N pins; only pass the ones this driver uses.
    return {k: side_cfg[k] for k in keys if k in side_cfg}


def open_drive(drive_cfg, mock=False, verbose=True):
    """Build a DifferentialDrive from the 'drive' config section."""
    gpio = None
    if mock or drive_cfg.get("backend") == "mock":
        left, right = MockMotor("left", verbose), MockMotor("right", verbose)
    else:
        import Jetson.GPIO as gpio
        gpio.setwarnings(False)
        gpio.setmode(gpio.BOARD)
        freq = drive_cfg["pwm_frequency_hz"]
        keys = DRIVER_PINS[drive_cfg.get("driver", "l298n")]
        left = JetsonMotor(gpio, frequency_hz=freq, **_pick(drive_cfg["left"], keys))
        right = JetsonMotor(gpio, frequency_hz=freq, **_pick(drive_cfg["right"], keys))
    drive = DifferentialDrive(left, right,
                              max_speed=drive_cfg["max_speed"],
                              min_duty=drive_cfg["min_duty"],
                              turn_gain=drive_cfg["turn_gain"],
                              ramp_per_s=drive_cfg["ramp_per_s"])
    drive.gpio = gpio
    return drive
