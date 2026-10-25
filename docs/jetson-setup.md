# Jetson setup for Wall-E 2.0

From a wiped Jetson to driving the robot with an Xbox controller. Work
through it in order; each step ends with a check so you know it worked.

## 0. Identify the board

Which Jetson you have decides the JetPack version, the Python version, and two
pin numbers. Look at the label on the carrier board (under the module/heatsink),
or if it still boots run `cat /proc/device-tree/model`.

| Board | Carrier label | JetPack to install | Ubuntu / Python |
|---|---|---|---|
| Jetson Nano 4GB dev kit | P3450 (A02 or B01) | 4.6.1 SD card image (last one for the Nano) | 18.04 / 3.6 |
| Jetson Nano 2GB dev kit | P3541 | 4.6.1 SD card image (2GB variant) | 18.04 / 3.6 |
| Jetson Orin Nano dev kit | P3766 / P3768 | 6.x SD card image | 22.04 / 3.10 |

The code in this repo is written for Python 3.6+, so it runs on both. The
differences are in the [pin notes](#pin-differences-between-nano-and-orin-nano) below.

## 1. Flash the SD card

1. Get a good microSD: 64 GB, UHS-I, A1/A2 rated (SanDisk Extreme or similar).
2. Download the image for your board from
   <https://developer.nvidia.com/embedded/jetpack-archive> (Nano: "JetPack 4.6.1",
   Orin Nano: the latest 6.x).
3. Write it with balenaEtcher or Raspberry Pi Imager ("Use custom" image).
   This erases the card.
4. **Orin Nano only:** if the board's firmware is older than 36.x it will not
   boot a JetPack 6 card. NVIDIA's Orin Nano "Getting Started" page has the
   firmware-update path (boot a JetPack 5.1.3 card once, let it update QSPI, then
   switch to the 6.x card).

## 2. Power and first boot

- **Nano:** use a 5 V / 4 A barrel-jack supply and fit the J48 jumper (next to
  the barrel jack). Micro-USB power browns out as soon as you add a camera or
  USB devices. On the robot this 5 V comes from the DC-DC converter (see the
  electronics thread), not the battery directly.
- **Orin Nano:** the included 19 V barrel supply. On the robot it needs a
  9-20 V input.

First boot runs the Ubuntu setup wizard. Either plug in HDMI + keyboard, or go
headless: connect the dev kit's micro-USB (Nano) / USB-C (Orin) port to your PC
and open the serial console (`screen /dev/ttyACM0 115200` on Linux/Mac, PuTTY on
the COM port on Windows).

Suggested choices: user `walle` (any name works), hostname **`walle`**, log in
automatically off.

**Check:** you can log in, and `ping walle.local` works from your PC.

## 3. Base system

SSH in from your PC (`ssh walle@walle.local`) and run:

```bash
sudo apt update && sudo apt upgrade -y
sudo apt install -y git nano htop i2c-tools python3-pip python3-dev \
                    python3-yaml python3-smbus python3-evdev bluez
sudo -H pip3 install -U jetson-stats    # gives you `jtop`; reboot afterwards

# Max performance mode
sudo nvpmodel -m 0          # Nano: 10 W MAXN.  Orin Nano: check `nvpmodel -q` for MAXN/Super
sudo jetson_clocks

# The robot does not need a desktop; this frees ~1 GB of RAM on a Nano.
sudo systemctl set-default multi-user.target    # undo with graphical.target

# Extra swap (Nano only; helps when building packages)
sudo fallocate -l 4G /swapfile && sudo chmod 600 /swapfile
sudo mkswap /swapfile && sudo swapon /swapfile
echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab

# Let your user reach GPIO, I2C and input devices without sudo
sudo groupadd -f -r gpio
sudo usermod -aG gpio,i2c,input $USER
sudo reboot
```

**Check:** after the reboot, `groups` lists `gpio i2c input`, and `jtop` shows the
board.

## 4. Enable the hardware PWM pins

The track motor speed signals need hardware PWM, which is off by default.

```bash
sudo /opt/nvidia/jetson-io/jetson-io.py
```

Choose *Configure Jetson 40pin Header* → *Configure header pins manually* →
tick **pwm0** and **pwm2** (Nano: pins 32 and 33) → Back → *Save pin changes* →
*Save and reboot to reconfigure pins*. On an Orin Nano enable the PWM functions
on pins **15** and **33**.

**Check:** `sudo /opt/nvidia/jetson-io/jetson-io.py` shows the PWM pins as
enabled when you reopen it.

## 5. Wire it up

See [wiring.md](wiring.md) for the pin table and diagram. Do the wiring with
everything powered off, and power the servo rail and motors from the battery
side, never from the Jetson's 5 V pins.

**Check (I2C):** with the PCA9685 connected and powered,

```bash
sudo i2cdetect -y -r 1      # Orin Nano: -r 7
```

The old project's board answered at **0x7f** (all six address pads bridged).
If you see a different address (0x40 is the factory default), put it in
`servos.address` in `config/robot.yaml`. `0x70` may also show up; that is the
chip's "all call" address and can be ignored.

## 6. Xbox controller

**USB cable (simplest, recommended for first tests):** plug it in, done. The
kernel's `xpad` driver handles it.

**Bluetooth:** the Nano 4GB has no built-in Bluetooth; add an M.2 Key-E card
(Intel 8265) or a USB Bluetooth dongle. Then:

```bash
# Xbox One/Series pads on older kernels need ERTM off to pair
echo 'options bluetooth disable_ertm=Y' | sudo tee /etc/modprobe.d/xbox-bt.conf
sudo reboot

bluetoothctl
  power on
  agent on
  default-agent
  scan on            # hold the pairing button on top of the pad until the logo flashes fast
  pair XX:XX:XX:XX:XX:XX
  trust XX:XX:XX:XX:XX:XX
  connect XX:XX:XX:XX:XX:XX
  quit
```

Over Bluetooth without extra drivers the pad shows up with a slightly
different axis layout; the code detects and handles that. If you want the
cleanest mapping and rumble support, the [xpadneo](https://github.com/atar-axis/xpadneo)
driver can be installed later (needs `nvidia-l4t-kernel-headers` and dkms).

**Check:** `ls /dev/input/by-id/` lists a joystick/event device.

## 7. Get the code and run the tools

```bash
git clone https://github.com/Lichter1/Wall-E_2025.git
cd Wall-E_2025
pip3 install --user -r requirements.txt   # skips what apt already installed
python3 -m pip install --user pytest && python3 -m pytest -q   # no hardware needed
```

Then bring the hardware up one piece at a time:

1. `python3 tools/controller_test.py` moves numbers when you move the sticks.
   Push the left stick up: `L(+0.00,+1.00)`. If a button shows the wrong name,
   run with `--raw` and tell me the codes.
2. `python3 tools/servo_test.py` and calibrate each joint (below).
3. **Robot on a stand, tracks off the ground:** `python3 tools/drive_test.py`.
   Fix any track running backwards with `inverted: true` in `config/robot.yaml`.
4. `python3 tools/teleop.py` and drive (hold LB). Add `--head` to look around
   with the right stick.

Every tool accepts `--mock` to run without hardware, which is handy on a laptop.

### Calibrating servos

The limits in `config/robot.yaml` start narrow (45-135°) on purpose. For each joint:

```
ch head_pan        select it
90                 go to the middle
- 5  / + 5         creep towards one end until just before it binds
setmin             store that angle (or setmax at the other end)
sethome            store the resting pose
save               writes config/servo_calibration.yaml
```

If a servo buzzes at its ends or doesn't use its full travel, adjust that
channel's `min_us`/`max_us` in `robot.yaml` (the old Python tests used
600-2400 µs, the Arduino firmware 1000-2000 µs).

## Pin differences between Nano and Orin Nano

| Signal | Nano | Orin Nano |
|---|---|---|
| Left track PWM (ENA) | pin 32 | pin 15 (set `drive.left.pwm_pin: 15`) |
| Right track PWM (ENB) | pin 33 | pin 33 |
| PCA9685 I2C bus (pins 3/5) | 1 | 7 (set `servos.i2c_bus: 7`) |

Everything else is the same.

## Troubleshooting

- **`RuntimeError: ... PWM ... not supported` or no motor speed control:** step 4
  (jetson-io) was not saved, or the pin number does not match your board.
- **`Permission denied` on /dev/i2c-1 or /dev/input/event*:** step 3 group
  membership; log out and in again (or reboot).
- **Motors whine but don't move:** raise `drive.min_duty` a little.
- **Jetson reboots when the motors start:** the motors are sagging the shared
  supply. The Jetson needs its own regulated DC-DC branch (electronics thread).
- **Servos jitter or the PCA9685 disappears from i2cdetect:** servo current is
  sagging the board's logic. Check the separate servo supply on the V+ terminal
  and that all grounds are tied together.
