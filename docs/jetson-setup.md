# Jetson setup for Wall-E 2.0

From a wiped Jetson to driving the robot with an Xbox controller. Work
through it in order; each step ends with a check so you know it worked.

## 0. The board

Wall-E 2.0 runs on a **Jetson Xavier NX Developer Kit** (kit P3518: the
P3668 module on the P3509 carrier). That decides:

| | |
|---|---|
| JetPack | **5.1.x** (the newest line that supports Xavier NX; JetPack 6 does not) |
| OS / Python | Ubuntu 20.04 / Python 3.8 |
| Power input | 9-20 V barrel jack (the kit came with a 19 V supply) |
| Wi-Fi / Bluetooth | built in (M.2 card on the carrier) |
| Track PWM pins | 32 and 33 (15 is also PWM-capable) |
| PCA9685 I2C (pins 3/5) | bus **8** |

Check the module's sticker: **P3668-0000** has a microSD slot (the dev-kit
module, use step 1A). **P3668-0001** has eMMC and no SD slot (use step 1B).

The code also runs on a Nano or Orin Nano; see [other boards](#other-jetson-boards)
at the end.

## 1A. Flash an SD card (P3668-0000)

1. Get a good microSD: 64 GB, UHS-I, A1/A2 rated (SanDisk Extreme or similar).
2. Download the **Jetson Xavier NX Developer Kit SD Card Image** for the latest
   JetPack 5.1.x from <https://developer.nvidia.com/embedded/jetpack-archive>.
3. Write it with balenaEtcher or Raspberry Pi Imager ("Use custom" image).
   This erases the card.
4. If the kit was last used with JetPack 4.x, its on-module boot firmware
   (QSPI) may be too old to boot a 5.x card: you get a black screen or a boot
   loop. Fix it once with step 1B, then go back to booting from SD.

## 1B. Flash with SDK Manager (eMMC module, or old firmware)

1. On an x86 PC running Ubuntu 18.04 or 20.04 (a spare laptop or a live USB
   works; a VM usually does not), install
   [NVIDIA SDK Manager](https://developer.nvidia.com/sdk-manager).
2. Put the kit in recovery mode: power off, short **FC REC** to **GND** on the
   button header under the module (a jumper or tweezers), power on, then remove
   the short. Connect the kit's micro-USB port to the PC; `lsusb` shows
   "NVIDIA Corp. APX".
3. In SDK Manager pick Jetson Xavier NX, JetPack 5.1.x, and flash. Choose
   "Pre-config" to set the user name in SDK Manager, or "Runtime" to do it on
   first boot.

## 2. Power and first boot

Use the 19 V supply for now. On the robot, feed the barrel jack from a
regulated DC-DC output (12-19 V) rather than straight from the 3S pack: a
3S pack sags towards 9 V under motor load, right at the Jetson's lower limit.
The electronics thread covers that converter.

First boot runs the Ubuntu setup wizard. Either plug in HDMI/DisplayPort +
keyboard, or go headless: connect the micro-USB port to your PC and open the
serial console (`screen /dev/ttyACM0 115200` on Linux/Mac, PuTTY on the COM port
on Windows). The same cable also gives you SSH at `192.168.55.1`.

Suggested choices: user `walle` (any name works), hostname **`walle`**, log in
automatically off. Join your Wi-Fi in the wizard or later with `nmtui`.

**Check:** you can log in, and `ping walle.local` works from your PC.

## 3. Base system

**Shortcut:** steps 3, 6 (Bluetooth tweak) and 7 are automated. SSH in from
your PC (`ssh walle@walle.local`) and run

```bash
git clone https://github.com/Lichter1/Wall-E_2025.git ~/Wall-E_2025
bash ~/Wall-E_2025/scripts/setup_jetson.sh      # add --headless to drop the desktop
sudo reboot
```

then continue at step 4. The manual commands are below if you prefer them.

```bash
sudo apt update && sudo apt upgrade -y
sudo apt install -y git nano htop i2c-tools python3-pip python3-dev \
                    python3-yaml python3-smbus python3-evdev
sudo -H pip3 install -U jetson-stats    # gives you `jtop`; reboot afterwards

# Performance mode: list the modes, then pick a 20 W one
grep POWER_MODEL /etc/nvpmodel.conf
sudo nvpmodel -m <id of a 20W mode>
sudo jetson_clocks

# The robot does not need a desktop; this frees RAM and CPU.
sudo systemctl set-default multi-user.target    # undo with graphical.target

# Let your user reach GPIO, I2C and input devices without sudo
sudo groupadd -f -r gpio
sudo usermod -aG gpio,i2c,input $USER
sudo reboot
```

**Check:** after the reboot, `groups` lists `gpio i2c input`, and `jtop` shows a
Xavier NX on JetPack 5.1.x.

## 4. Enable the hardware PWM pins

The track motor speed signals need hardware PWM, which is off by default.

```bash
sudo /opt/nvidia/jetson-io/jetson-io.py
```

Choose *Configure Jetson 40pin Header* → *Configure header pins manually* →
tick the **PWM** entries for pins **32** and **33** → Back → *Save pin changes*
→ *Save and reboot to reconfigure pins*.

Or without the menu (on the Xavier NX, pin 32 is `pwm8` and pin 33 is `pwm1`):

```bash
sudo /opt/nvidia/jetson-io/config-by-function.py -o dtb pwm1 pwm8
sudo reboot
```

`-o dtb` adds a "JetsonIO" boot entry to `/boot/extlinux/extlinux.conf` and
keeps the original "primary" entry as a fallback. (`-o dtbo` only writes an
overlay file and does not change the boot config.)

**Check:** `sudo /opt/nvidia/jetson-io/config-by-function.py -l enabled` lists
`pwm1` and `pwm8`.

**If Jetson-IO crashes with "No APP_b partition found":** the bootloader runs
from slot B (common after a firmware update) but the SD card has only one
system partition, `APP`. Back up `/opt/nvidia/jetson-io/Jetson/board.py` and
add these lines right after `mountpart = "APP_b"` in `Board.__init__`:

```python
        # no redundant rootfs on this board, so slot B still uses APP
        if mountpart == "APP_b" and not _board_partition_exists(mountpart):
            mountpart = "APP"
```

A JetPack update may overwrite the file; re-apply the lines if the error returns.

## 5. Wire it up

See [wiring.md](wiring.md) for the pin table and diagram. Do the wiring with
everything powered off, and power the servo rail and motors from the battery
side, never from the Jetson's 5 V pins.

**Check (I2C):** with the PCA9685 connected and powered,

```bash
i2cdetect -l                # find the bus named for pins 3/5; normally i2c-8
sudo i2cdetect -y -r 8
```

The old project's board answered at **0x7f** (all six address pads bridged).
If you see a different address (0x40 is the factory default), put it in
`servos.address` in `config/robot.yaml`. If nothing shows on bus 8, try bus 1
(pins 27/28) and check the wires. `0x70` may also show up; that is the chip's
"all call" address and can be ignored.

## 6. Xbox controller

**USB cable (simplest, recommended for first tests):** plug it in, done. The
kernel's `xpad` driver handles it.

**Bluetooth:** the kit has Bluetooth built in.

```bash
# Xbox One/Series pads need ERTM off to pair on this kernel
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
   run with `--raw` and send me the codes.
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

## Troubleshooting

- **`RuntimeError` mentioning PWM, or the tracks run at one speed only:** step 4
  (jetson-io) was not saved, or the ENA/ENB jumper caps are still on the L298N.
- **`Permission denied` on /dev/i2c-8 or /dev/input/event*:** step 3 group
  membership; log out and in again (or reboot).
- **Motors whine but don't move:** raise `drive.min_duty` a little.
- **Jetson reboots when the motors start:** the motors are sagging the shared
  supply. The Jetson needs its own regulated DC-DC branch (electronics thread).
- **Servos jitter or the PCA9685 disappears from i2cdetect:** servo current is
  sagging the board's logic. Check the separate servo supply on the V+ terminal
  and that all grounds are tied together.

## Other Jetson boards

Only two settings in `config/robot.yaml` change:

| Board | JetPack | `servos.i2c_bus` | `drive.left.pwm_pin` / `right.pwm_pin` |
|---|---|---|---|
| Xavier NX (this robot) | 5.1.x | 8 | 32 / 33 |
| Nano (P3450) | 4.6.x | 1 | 32 / 33 |
| Orin Nano (P3766/P3768) | 6.x | 7 | 15 / 33 |
