"""Small numeric helpers shared by drive, servo and input code."""


def clamp(value, low, high):
    """Limit value to the closed range [low, high]."""
    return max(low, min(high, value))


def remap(value, in_min, in_max, out_min, out_max):
    """Linearly map value from one range to another (no clamping)."""
    if in_max == in_min:
        raise ValueError("input range is empty")
    return (value - in_min) * (out_max - out_min) / float(in_max - in_min) + out_min


def apply_deadzone(value, deadzone):
    """Zero out small stick values and rescale the rest back to [-1, 1].

    Rescaling avoids a jump at the edge of the dead zone: the output starts
    at 0 just outside it and still reaches +/-1 at full deflection.
    """
    if deadzone <= 0:
        return clamp(value, -1.0, 1.0)
    if abs(value) <= deadzone:
        return 0.0
    sign = 1.0 if value > 0 else -1.0
    return sign * clamp((abs(value) - deadzone) / (1.0 - deadzone), 0.0, 1.0)


def apply_expo(value, expo):
    """Soften the stick response near centre. expo=0 is linear, 1 is cubic."""
    return (1.0 - expo) * value + expo * value ** 3


class SlewLimiter(object):
    """Limits how fast a value may change, in units per second.

    Used to ramp motor commands so a full-stick reversal does not slam the
    gearboxes or brown out the battery.
    """

    def __init__(self, rate_per_s, initial=0.0):
        self.rate = float(rate_per_s)
        self.value = float(initial)

    def update(self, target, dt):
        if self.rate <= 0:
            self.value = float(target)
            return self.value
        step = self.rate * max(dt, 0.0)
        delta = clamp(target - self.value, -step, step)
        self.value += delta
        return self.value

    def reset(self, value=0.0):
        self.value = float(value)
