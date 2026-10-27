import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))

from walle import config as config_mod
from walle.hardware import pca9685
from walle.hardware.drive import DifferentialDrive, MockMotor, mix_arcade, to_duty
from walle.hardware.pca9685 import MockPCA9685
from walle.hardware.servos import ServoBank
from walle.inputs.xbox import (ABS_BRAKE, ABS_GAS, ABS_RZ, ABS_X, ABS_Y, ABS_Z,
                               EV_ABS, EV_KEY, ControllerState)
from walle.mathx import SlewLimiter, apply_deadzone
from teleop import Teleop  # noqa: E402


# --- math -------------------------------------------------------------

def test_deadzone_zeroes_and_rescales():
    assert apply_deadzone(0.05, 0.1) == 0.0
    assert apply_deadzone(1.0, 0.1) == pytest.approx(1.0)
    assert apply_deadzone(-0.55, 0.1) == pytest.approx(-0.5)


def test_slew_limiter_caps_rate():
    s = SlewLimiter(2.0)
    assert s.update(1.0, 0.1) == pytest.approx(0.2)
    assert s.update(1.0, 1.0) == pytest.approx(1.0)


# --- drive ------------------------------------------------------------

def test_mix_keeps_ratio_when_saturated():
    left, right = mix_arcade(1.0, 1.0)
    assert (left, right) == (1.0, 0.0)
    left, right = mix_arcade(0.0, 0.5)
    assert left == pytest.approx(0.5) and right == pytest.approx(-0.5)


def test_to_duty_starts_at_min_duty_and_caps_at_max():
    assert to_duty(0.0, 0.25, 0.6) == 0.0
    assert to_duty(0.01, 0.25, 0.6) == pytest.approx(0.2535)
    assert to_duty(-1.0, 0.25, 0.6) == pytest.approx(-0.6)


class FakeClock(object):
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t


def test_drive_ramps_and_stops():
    clock = FakeClock()
    left, right = MockMotor("l"), MockMotor("r")
    drive = DifferentialDrive(left, right, max_speed=1.0, min_duty=0.0, turn_gain=1.0,
                              ramp_per_s=2.0, clock=clock)
    clock.t = 0.1
    drive.drive(1.0, 0.0)
    assert left.duty == pytest.approx(0.2)
    clock.t = 1.0
    drive.drive(1.0, 0.0)
    assert left.duty == pytest.approx(1.0) and right.duty == pytest.approx(1.0)
    drive.stop()
    assert (left.duty, right.duty) == (0.0, 0.0)


# --- pca9685 ----------------------------------------------------------

def test_prescale_and_ticks():
    assert pca9685.prescale_for(50) == 121
    assert pca9685.pulse_us_to_ticks(1500, 50) == 307


class FakeBus(object):
    def __init__(self):
        self.regs = {0x00: 0x11}
        self.blocks = []

    def write_byte_data(self, addr, reg, val):
        self.regs[reg] = val

    def read_byte_data(self, addr, reg):
        return self.regs.get(reg, 0)

    def write_i2c_block_data(self, addr, reg, data):
        self.blocks.append((reg, list(data)))


def test_pca9685_register_writes():
    bus = FakeBus()
    board = pca9685.PCA9685(smbus=bus, address=0x7F, frequency_hz=50)
    assert bus.regs[pca9685.PRESCALE] == 121
    assert not bus.regs[pca9685.MODE1] & pca9685.MODE1_SLEEP
    board.set_pulse_us(3, 1500)
    assert bus.blocks[-1] == (0x06 + 12, [0, 0, 307 & 0xFF, 307 >> 8])
    board.release(3)
    assert bus.blocks[-1] == (0x06 + 12, [0, 0, 0, 0x10])


# --- servos -----------------------------------------------------------

def test_servo_clamps_to_soft_limits():
    board = MockPCA9685()
    bank = ServoBank(board, {0: {"name": "head_pan", "min_angle": 45, "max_angle": 135}})
    pan = bank.get("head_pan")
    assert pan.move(10) == 45
    assert board.pulses[0] == 1250
    assert pan.move(180) == 135
    assert bank.get(5).move(90) == 90   # unconfigured channel gets defaults


def test_inverted_servo():
    board = MockPCA9685()
    servo = ServoBank(board, {1: {"inverted": True}}).get(1)
    servo.move(0)
    assert board.pulses[1] == 2000


# --- controller -------------------------------------------------------

RANGES = {ABS_X: (-32768, 32767), ABS_Y: (-32768, 32767), ABS_Z: (0, 1023), ABS_RZ: (0, 1023)}


def test_controller_xpad_mapping():
    st = ControllerState(RANGES)
    st.handle(EV_ABS, ABS_Y, -32768)          # stick pushed up
    st.handle(EV_ABS, ABS_Z, 1023)            # LT fully pressed
    st.handle(EV_KEY, 0x136, 1)               # LB
    assert st.values["ly"] == pytest.approx(1.0)
    assert st.values["lt"] == pytest.approx(1.0)
    assert st.values["lb"] is True
    assert st.pressed_events == ["lb"]


def test_controller_hid_generic_mapping():
    ranges = {ABS_X: (0, 65535), ABS_Y: (0, 65535), ABS_Z: (0, 65535),
              ABS_RZ: (0, 65535), ABS_GAS: (0, 1023), ABS_BRAKE: (0, 1023)}
    st = ControllerState(ranges)
    st.handle(EV_ABS, ABS_Z, 65535)           # right stick full right on hid-generic
    st.handle(EV_ABS, ABS_GAS, 1023)
    assert st.values["rx"] == pytest.approx(1.0)
    assert st.values["rt"] == pytest.approx(1.0)
    assert st.values["lt"] == 0.0


# --- teleop -----------------------------------------------------------

def make_teleop():
    cfg = config_mod.load_config()
    left, right = MockMotor("l"), MockMotor("r")
    drive = DifferentialDrive(left, right, ramp_per_s=0)
    return Teleop(cfg, drive), left


def pad(**kw):
    from walle.inputs.xbox import empty_state
    s = empty_state()
    s.update(kw)
    return s


def test_teleop_needs_deadman():
    teleop, left = make_teleop()
    teleop.step(pad(ly=1.0), [], True, 0.02)
    assert left.duty == 0.0
    teleop.step(pad(ly=1.0, lb=True), [], True, 0.02)
    assert left.duty > 0


def test_teleop_estop_latches_and_disconnect_stops():
    teleop, left = make_teleop()
    teleop.step(pad(ly=1.0, lb=True), ["b"], True, 0.02)
    assert left.duty == 0.0
    teleop.step(pad(ly=1.0, lb=True), [], True, 0.02)
    assert left.duty == 0.0
    teleop.step(pad(ly=1.0, lb=True), ["menu"], True, 0.02)
    assert left.duty > 0
    teleop.step(pad(ly=1.0, lb=True), [], False, 0.02)
    assert left.duty == 0.0


def test_calibration_overlays_robot_yaml(tmp_path):
    cal = tmp_path / "cal.yaml"
    config_mod.save_calibration({0: {"min_angle": 60}}, str(cal))
    cfg = config_mod.load_config(calibration_path=str(cal))
    assert cfg["servos"]["channels"][0]["min_angle"] == 60
    assert cfg["servos"]["channels"][0]["name"] == "head_pan"
    assert cfg["servos"]["address"] == 0x7F


class FakeGPIO(object):
    OUT, HIGH, LOW = "out", 1, 0

    def __init__(self):
        self.levels = {}

    def setup(self, pin, mode, initial=0):
        self.levels[pin] = initial

    def output(self, pin, level):
        self.levels[pin] = level

    def PWM(self, pin, freq):
        gpio = self

        class P(object):
            def start(self, d):
                gpio.levels[("pwm", pin)] = d

            def ChangeDutyCycle(self, d):
                gpio.levels[("pwm", pin)] = d

            def stop(self):
                pass
        return P()


def test_l298n_and_pwm_dir_motors():
    from walle.hardware.drive import JetsonMotor
    gpio = FakeGPIO()
    m = JetsonMotor(gpio, pwm_pin=32, frequency_hz=1000, in1_pin=29, in2_pin=31)
    m.set(-0.5)
    assert (gpio.levels[29], gpio.levels[31], gpio.levels[("pwm", 32)]) == (0, 1, 50.0)
    m = JetsonMotor(gpio, pwm_pin=33, frequency_hz=1000, dir_pin=35, inverted=True)
    m.set(0.25)
    assert (gpio.levels[35], gpio.levels[("pwm", 33)]) == (0, 25.0)
    assert 37 not in gpio.levels
