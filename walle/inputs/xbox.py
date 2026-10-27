"""Xbox controller input via Linux evdev.

evdev reads /dev/input directly, so it works headless over SSH (pygame
needs a display or SDL tricks). A background thread keeps the latest
normalised state; the control loop just reads controller.state.

Works with a USB cable (xpad driver), the Xbox wireless dongle, or
Bluetooth. For Bluetooth on Xbox One/Series pads, install the xpadneo
driver (see docs/jetson-setup.md) for the cleanest mapping; the raw
hid-generic mapping is also handled below.
"""

import asyncio
import threading
import time

# Linux input event codes (linux/input-event-codes.h), duplicated here so the
# mapping logic can be tested without evdev installed.
EV_KEY = 0x01
EV_ABS = 0x03
ABS_X, ABS_Y, ABS_Z = 0x00, 0x01, 0x02
ABS_RX, ABS_RY, ABS_RZ = 0x03, 0x04, 0x05
ABS_GAS, ABS_BRAKE = 0x09, 0x0A
ABS_HAT0X, ABS_HAT0Y = 0x10, 0x11

BUTTONS = {
    0x130: "a", 0x131: "b", 0x133: "x", 0x134: "y",
    0x136: "lb", 0x137: "rb",
    0x13A: "view", 0x13B: "menu", 0x13C: "xbox",
    0x13D: "ls", 0x13E: "rs",
}

# xpad / xpadneo layout.
AXES_XPAD = {
    ABS_X: ("lx", False), ABS_Y: ("ly", True),
    ABS_RX: ("rx", False), ABS_RY: ("ry", True),
    ABS_Z: ("lt", False), ABS_RZ: ("rt", False),
}
# Bluetooth pad on the generic HID driver: right stick moves to Z/RZ and
# the triggers to BRAKE/GAS.
AXES_HID_GENERIC = {
    ABS_X: ("lx", False), ABS_Y: ("ly", True),
    ABS_Z: ("rx", False), ABS_RZ: ("ry", True),
    ABS_BRAKE: ("lt", False), ABS_GAS: ("rt", False),
}
TRIGGERS = ("lt", "rt")


def empty_state():
    state = {name: 0.0 for name in ("lx", "ly", "rx", "ry", "lt", "rt")}
    state.update({"dpad_x": 0, "dpad_y": 0})
    state.update({name: False for name in BUTTONS.values()})
    return state


class ControllerState(object):
    """Pure event-to-state mapping, separated from the device for testing."""

    def __init__(self, axis_ranges, layout=None):
        # axis_ranges: {code: (min, max)} from the device's absinfo.
        self.ranges = axis_ranges
        if layout is None:
            layout = AXES_HID_GENERIC if ABS_GAS in axis_ranges else AXES_XPAD
        self.layout = layout
        self.values = empty_state()
        self.pressed_events = []   # button names pressed since last poll

    def normalise(self, code, value, trigger, invert):
        low, high = self.ranges.get(code, (-32768, 32767))
        if high == low:
            return 0.0
        if trigger:
            out = (value - low) / float(high - low)
            return max(0.0, min(1.0, out))
        out = 2.0 * (value - low) / float(high - low) - 1.0
        out = max(-1.0, min(1.0, out))
        # evdev Y axes grow downwards; flip so stick-up is +1.
        return -out if invert else out

    def handle(self, ev_type, code, value):
        if ev_type == EV_ABS:
            if code == ABS_HAT0X:
                self.values["dpad_x"] = value
            elif code == ABS_HAT0Y:
                self.values["dpad_y"] = -value   # up is +1
            elif code in self.layout:
                name, invert = self.layout[code]
                self.values[name] = self.normalise(code, value, name in TRIGGERS, invert)
        elif ev_type == EV_KEY and code in BUTTONS:
            name = BUTTONS[code]
            self.values[name] = bool(value)
            if value == 1:
                self.pressed_events.append(name)


def find_gamepad(path=None):
    """Return an evdev InputDevice for the configured path or first gamepad."""
    import evdev
    if path:
        return evdev.InputDevice(path)
    for dev_path in evdev.list_devices():
        dev = evdev.InputDevice(dev_path)
        caps = dev.capabilities()
        if 0x130 in caps.get(EV_KEY, []) and any(
                (c[0] if isinstance(c, tuple) else c) == ABS_X for c in caps.get(EV_ABS, [])):
            return dev
        dev.close()
    return None


class XboxController(object):
    """Background reader with automatic reconnect.

    Read .state (a dict copy) and .connected each loop. Xbox pads only send
    events on change, so a resting stick is silent and "no recent events" is
    not a fault; safety comes from disconnect detection plus the deadman
    button in the teleop loop.
    """

    def __init__(self, device_path=None):
        import evdev  # noqa: F401  fail here, loudly, rather than in the thread
        self.device_path = device_path
        self.connected = False
        self.name = None
        self._mapper = None
        self._lock = threading.Lock()
        self._last_event = 0.0
        self._running = True
        self._thread = threading.Thread(target=self._run, name="xbox-reader")
        self._thread.daemon = True
        self._thread.start()

    @property
    def state(self):
        with self._lock:
            return dict(self._mapper.values) if self._mapper else empty_state()

    def pop_presses(self):
        """Button names pressed since the last call (edge-triggered)."""
        with self._lock:
            if not self._mapper:
                return []
            presses, self._mapper.pressed_events = self._mapper.pressed_events, []
            return presses

    def seconds_since_event(self):
        return time.monotonic() - self._last_event

    def _run(self):
        # Older python-evdev (Ubuntu 20.04 ships 1.3.0) calls
        # asyncio.get_event_loop() in InputDevice.close(), which raises in a
        # thread without a loop. Give this thread its own.
        asyncio.set_event_loop(asyncio.new_event_loop())
        while self._running:
            try:
                dev = find_gamepad(self.device_path)
            except Exception as exc:
                # Never let a bad device kill the reader: teleop would see
                # "no controller" forever instead of reconnecting.
                if not isinstance(exc, OSError):
                    print("xbox-reader: %s: %s" % (type(exc).__name__, exc))
                dev = None
            if dev is None:
                time.sleep(1.0)
                continue
            ranges = {}
            for code, info in dev.capabilities(absinfo=True).get(EV_ABS, []):
                ranges[code] = (info.min, info.max)
            with self._lock:
                self._mapper = ControllerState(ranges)
                self.name = dev.name
                self.connected = True
            try:
                for event in dev.read_loop():
                    if not self._running:
                        break
                    with self._lock:
                        self._mapper.handle(event.type, event.code, event.value)
                        self._last_event = time.monotonic()
            except OSError:
                pass  # unplugged or Bluetooth dropped: reconnect
            except Exception as exc:
                print("xbox-reader: %s: %s" % (type(exc).__name__, exc))
                time.sleep(1.0)
            finally:
                with self._lock:
                    self.connected = False
                    self._mapper = None
                try:
                    dev.close()
                except OSError:
                    pass

    def close(self):
        self._running = False
