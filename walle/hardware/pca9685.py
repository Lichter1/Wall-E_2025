"""Minimal PCA9685 16-channel PWM driver over smbus2.

Talking to the chip directly keeps us off Adafruit Blinka, which has to be
taught each Jetson model and its I2C bus numbering.
The register sequence follows the NXP PCA9685 datasheet.
"""

import time

MODE1 = 0x00
MODE2 = 0x01
LED0_ON_L = 0x06
PRESCALE = 0xFE

MODE1_RESTART = 0x80
MODE1_AI = 0x20       # register auto-increment
MODE1_SLEEP = 0x10
MODE2_OUTDRV = 0x04   # totem-pole outputs

OSC_HZ = 25000000
FULL_OFF_BIT = 0x10   # bit 4 of LEDn_OFF_H


def prescale_for(frequency_hz):
    """Prescale register value for a PWM frequency (datasheet eq. 1)."""
    value = int(round(OSC_HZ / (4096.0 * frequency_hz))) - 1
    if not 3 <= value <= 255:
        raise ValueError("frequency %s Hz out of PCA9685 range" % frequency_hz)
    return value


def pulse_us_to_ticks(pulse_us, frequency_hz):
    """Convert a pulse width in microseconds to a 12-bit off-count."""
    ticks = int(round(pulse_us * frequency_hz * 4096 / 1e6))
    return max(0, min(4095, ticks))


class PCA9685(object):
    def __init__(self, bus=1, address=0x7F, frequency_hz=50, smbus=None):
        if smbus is None:
            try:
                from smbus2 import SMBus
            except ImportError:
                from smbus import SMBus   # apt python3-smbus, same calls
            smbus = SMBus(bus)
        self.bus = smbus
        self.address = address
        self.frequency_hz = None
        self.bus.write_byte_data(self.address, MODE2, MODE2_OUTDRV)
        self.bus.write_byte_data(self.address, MODE1, MODE1_AI)
        time.sleep(0.005)  # oscillator start-up
        self.set_frequency(frequency_hz)

    def set_frequency(self, frequency_hz):
        prescale = prescale_for(frequency_hz)
        old_mode = self.bus.read_byte_data(self.address, MODE1)
        # Prescale can only be written while the oscillator sleeps.
        self.bus.write_byte_data(self.address, MODE1, (old_mode & 0x7F) | MODE1_SLEEP)
        self.bus.write_byte_data(self.address, PRESCALE, prescale)
        self.bus.write_byte_data(self.address, MODE1, old_mode & ~MODE1_SLEEP & 0xFF)
        time.sleep(0.005)
        self.bus.write_byte_data(self.address, MODE1, (old_mode | MODE1_RESTART | MODE1_AI) & ~MODE1_SLEEP & 0xFF)
        self.frequency_hz = frequency_hz

    def set_ticks(self, channel, off_ticks):
        """Output high from count 0 to off_ticks (0-4095) on one channel."""
        if not 0 <= channel <= 15:
            raise ValueError("channel must be 0-15")
        off_ticks = max(0, min(4095, int(off_ticks)))
        reg = LED0_ON_L + 4 * channel
        self.bus.write_i2c_block_data(self.address, reg, [0, 0, off_ticks & 0xFF, off_ticks >> 8])

    def set_pulse_us(self, channel, pulse_us):
        self.set_ticks(channel, pulse_us_to_ticks(pulse_us, self.frequency_hz))

    def release(self, channel):
        """Stop sending pulses so the servo goes limp (no holding torque)."""
        reg = LED0_ON_L + 4 * channel
        self.bus.write_i2c_block_data(self.address, reg, [0, 0, 0, FULL_OFF_BIT])

    def release_all(self):
        for channel in range(16):
            self.release(channel)

    def close(self):
        self.release_all()
        if hasattr(self.bus, "close"):
            self.bus.close()


class MockPCA9685(object):
    """Stands in for the board on a laptop or in tests; records pulses."""

    def __init__(self, frequency_hz=50, verbose=False, **_):
        self.frequency_hz = frequency_hz
        self.pulses = {}
        self.verbose = verbose

    def set_pulse_us(self, channel, pulse_us):
        self.pulses[channel] = pulse_us
        if self.verbose:
            print("[mock pca9685] ch%d -> %d us" % (channel, pulse_us))

    def release(self, channel):
        self.pulses[channel] = None
        if self.verbose:
            print("[mock pca9685] ch%d released" % channel)

    def release_all(self):
        for channel in range(16):
            self.pulses[channel] = None

    def close(self):
        self.release_all()
