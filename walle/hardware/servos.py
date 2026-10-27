"""Calibrated servos on the PCA9685.

Each channel has its own min/max pulse and angle limits so a joint can
never be commanded past the point where it binds against the body.
"""

from walle.mathx import clamp, remap

DEFAULT_CHANNEL = {
    "name": None,
    "min_us": 1000,     # pulse at 0 degrees; the old Arduino code used 1000-2000
    "max_us": 2000,     # pulse at 180 degrees
    "min_angle": 0,     # soft limits, tighten these during calibration
    "max_angle": 180,
    "home": 90,
    "inverted": False,
}


class Servo(object):
    def __init__(self, board, channel, **settings):
        self.board = board
        self.channel = channel
        cfg = dict(DEFAULT_CHANNEL)
        cfg.update({k: v for k, v in settings.items() if v is not None})
        self.name = cfg["name"] or "ch%d" % channel
        self.min_us = cfg["min_us"]
        self.max_us = cfg["max_us"]
        self.min_angle = cfg["min_angle"]
        self.max_angle = cfg["max_angle"]
        self.home = cfg["home"]
        self.inverted = cfg["inverted"]
        self.angle = None

    def angle_to_us(self, angle):
        angle = clamp(angle, self.min_angle, self.max_angle)
        if self.inverted:
            angle = 180 - angle
        return int(round(remap(angle, 0, 180, self.min_us, self.max_us)))

    def move(self, angle):
        """Move to an angle (degrees), clamped to this joint's soft limits."""
        angle = clamp(angle, self.min_angle, self.max_angle)
        self.board.set_pulse_us(self.channel, self.angle_to_us(angle))
        self.angle = angle
        return angle

    def nudge(self, delta):
        return self.move((self.angle if self.angle is not None else self.home) + delta)

    def go_home(self):
        return self.move(self.home)

    def release(self):
        self.board.release(self.channel)
        self.angle = None

    def settings(self):
        return {
            "name": self.name,
            "min_us": self.min_us,
            "max_us": self.max_us,
            "min_angle": self.min_angle,
            "max_angle": self.max_angle,
            "home": self.home,
            "inverted": self.inverted,
        }


class ServoBank(object):
    """All configured servos, addressable by channel number or name."""

    def __init__(self, board, channels_cfg):
        self.board = board
        self.servos = {}
        for channel, settings in sorted((channels_cfg or {}).items()):
            self.servos[int(channel)] = Servo(board, int(channel), **(settings or {}))

    def get(self, key):
        if isinstance(key, int) or (isinstance(key, str) and key.isdigit()):
            channel = int(key)
            if channel not in self.servos:
                if not 0 <= channel <= 15:
                    raise KeyError("channel must be 0-15")
                # Unconfigured channels get safe defaults so they can be explored.
                self.servos[channel] = Servo(self.board, channel)
            return self.servos[channel]
        for servo in self.servos.values():
            if servo.name == key:
                return servo
        raise KeyError("no servo named %r" % key)

    def home_all(self):
        for servo in self.servos.values():
            servo.go_home()

    def release_all(self):
        self.board.release_all()
        for servo in self.servos.values():
            servo.angle = None


def open_servo_board(servo_cfg, mock=False, verbose=True):
    """Create the real board, or a mock when asked or configured."""
    from walle.hardware.pca9685 import PCA9685, MockPCA9685
    if mock or servo_cfg.get("backend") == "mock":
        return MockPCA9685(frequency_hz=servo_cfg["frequency_hz"], verbose=verbose)
    return PCA9685(bus=servo_cfg["i2c_bus"], address=servo_cfg["address"],
                   frequency_hz=servo_cfg["frequency_hz"])
