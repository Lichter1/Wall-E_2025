#!/usr/bin/env bash
# One-shot setup for the Wall-E Jetson (Xavier NX, JetPack 5.1.x).
# Safe to run again: every step checks before it changes anything.
#
#   bash scripts/setup_jetson.sh              # base setup
#   bash scripts/setup_jetson.sh --headless   # also boot to console instead of the desktop
#
# Covers docs/jetson-setup.md steps 3, 6 (Bluetooth fixes, xpadneo) and 7.
# Enabling the PWM pins (step 4, jetson-io) is interactive and is left for you; the script tells
# you whether it is done.

set -euo pipefail

HEADLESS=0
for arg in "$@"; do
  case "$arg" in
    --headless) HEADLESS=1 ;;
    *) echo "unknown option: $arg"; exit 2 ;;
  esac
done

REPO_URL="https://github.com/Lichter1/Wall-E_2025.git"
REPO_DIR="$HOME/Wall-E_2025"
NEED_REBOOT=0

step() { printf '\n==> %s\n' "$*"; }

if [ "$(id -u)" -eq 0 ]; then
  echo "Run this as your normal user (it uses sudo where needed)."
  exit 1
fi
sudo -v

step "Board"
tr -d '\0' < /proc/device-tree/model; echo
head -n1 /etc/nv_tegra_release 2>/dev/null || true

step "System update and packages"
export DEBIAN_FRONTEND=noninteractive
sudo apt-get update
sudo -E apt-get -y upgrade
sudo -E apt-get install -y git nano htop curl i2c-tools \
  python3-pip python3-dev python3-yaml python3-smbus python3-evdev python3-pytest bluez

step "Python packages"
python3 -m pip install --user --upgrade pip
python3 -m pip install --user smbus2 evdev PyYAML Jetson.GPIO
if ! command -v jtop >/dev/null; then
  sudo -H python3 -m pip install -U jetson-stats
  NEED_REBOOT=1
fi

step "Hardware access groups (gpio, i2c, input)"
sudo groupadd -f -r gpio
for g in gpio i2c input; do
  if ! id -nG "$USER" | tr ' ' '\n' | grep -qx "$g"; then
    sudo usermod -aG "$g" "$USER"
    NEED_REBOOT=1
  fi
done
# Jetson.GPIO ships udev rules that hand the GPIO/PWM sysfs files to the gpio group.
RULES=$(python3 -c 'import os, Jetson.GPIO as g; print(os.path.join(os.path.dirname(g.__file__), "99-gpio.rules"))' 2>/dev/null || true)
if [ -n "$RULES" ] && [ -f "$RULES" ] && [ ! -f /etc/udev/rules.d/99-gpio.rules ]; then
  sudo cp "$RULES" /etc/udev/rules.d/
  sudo udevadm control --reload-rules && sudo udevadm trigger
fi

step "Power mode (20 W, 6 cores)"
MODE_ID=$(grep -E 'POWER_MODEL.*NAME=MODE_20W_6CORE' /etc/nvpmodel.conf | sed -E 's/.*ID=([0-9]+).*/\1/' | head -n1 || true)
if [ -n "$MODE_ID" ]; then
  sudo nvpmodel -m "$MODE_ID" || true
else
  echo "MODE_20W_6CORE not found; current mode left as is:"
fi
sudo nvpmodel -q || true

step "Bluetooth tweak for Xbox controllers"
# Bluetooth is built into the L4T kernel, so a modprobe.d option is ignored;
# set the parameter through sysfs at every boot instead.
sudo rm -f /etc/modprobe.d/xbox-bt.conf
if [ ! -f /etc/tmpfiles.d/xbox-bt.conf ]; then
  echo 'w /sys/module/bluetooth/parameters/disable_ertm - - - - Y' | sudo tee /etc/tmpfiles.d/xbox-bt.conf >/dev/null
fi
sudo systemd-tmpfiles --create /etc/tmpfiles.d/xbox-bt.conf || true

step "Bluetooth LE pairing fix (Tegra hardware ECDH)"
# Xbox Series X|S pads pair over BLE; the Tegra security engine's ECDH rejects
# the pairing keys, so hand ECDH back to the kernel's software implementation.
SERVICE=walle-bt-ecdh-fix.service
SRC="$(cd "$(dirname "$0")" && pwd)/systemd/$SERVICE"
if [ -f "$SRC" ] && ! cmp -s "$SRC" "/etc/systemd/system/$SERVICE"; then
  sudo cp "$SRC" /etc/systemd/system/
  sudo systemctl daemon-reload
fi
sudo systemctl enable --now "$SERVICE" || true

step "xpadneo driver (Xbox pads over Bluetooth)"
# v0.10 is the newest release that builds on the 5.10 L4T kernel (later ones
# need Linux 6.4+); the kernel build uses gnu89, which xpadneo's C rejects.
if ! dkms status 2>/dev/null | grep -q '^hid-xpadneo'; then
  sudo -E apt-get install -y dkms "nvidia-l4t-kernel-headers" || true
  XPADNEO_DIR="$HOME/xpadneo"
  [ -d "$XPADNEO_DIR/.git" ] || git clone https://github.com/atar-axis/xpadneo.git "$XPADNEO_DIR"
  git -C "$XPADNEO_DIR" fetch --tags
  git -C "$XPADNEO_DIR" checkout -f v0.10
  XPADNEO_MK="$XPADNEO_DIR/hid-xpadneo/src/Makefile"
  grep -q 'std=gnu11' "$XPADNEO_MK" || echo 'ccflags-y += -std=gnu11' >> "$XPADNEO_MK"
  (cd "$XPADNEO_DIR" && sudo ./install.sh) || echo "xpadneo install failed; see docs/jetson-setup.md step 6"
  NEED_REBOOT=1
fi

if [ "$HEADLESS" -eq 1 ]; then
  step "Boot to console (no desktop)"
  sudo systemctl set-default multi-user.target
fi

step "Wall-E code"
if [ -d "$REPO_DIR/.git" ]; then
  git -C "$REPO_DIR" pull --ff-only
else
  git clone "$REPO_URL" "$REPO_DIR"
fi
(cd "$REPO_DIR" && python3 -m pytest -q)

step "Checks"
echo "I2C buses (the PCA9685 goes on the one for header pins 3/5, normally i2c-8):"
i2cdetect -l || true
if ls /sys/class/pwm/ >/dev/null 2>&1 && [ -n "$(ls /sys/class/pwm/ 2>/dev/null)" ]; then
  echo "PWM chips present: $(ls /sys/class/pwm/ | tr '\n' ' ')"
fi
cat <<'EOF'

PWM pins 32 and 33 still need enabling once, if you have not done it:
  sudo /opt/nvidia/jetson-io/jetson-io.py
  -> Configure Jetson 40pin Header -> Configure header pins manually
  -> tick the PWM entries for pins 32 and 33 -> Back -> Save pin changes
  -> Save and reboot to reconfigure pins
EOF

if [ "$NEED_REBOOT" -eq 1 ]; then
  printf '\nDone. Reboot now so the group and driver changes apply: sudo reboot\n'
else
  printf '\nDone. Nothing needs a reboot.\n'
fi
