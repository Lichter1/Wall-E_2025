# Wiring: Jetson ↔ motor driver ↔ servo board

Signal wiring for the first features. Battery, fuse, switch and DC-DC sizing
are covered by the electronics wishlist; the power boxes below are placeholders
for whatever that settles on.

```mermaid
flowchart LR
  BAT[Battery pack] --> FUSE[Fuse + main switch]
  FUSE --> DCJ[DC-DC 5 V 4 A+<br/>Jetson supply]
  FUSE --> BEC[UBEC 5-6 V<br/>servo supply]
  FUSE --> L298[L298N<br/>12 V input]

  DCJ -->|barrel jack| JET[Jetson]
  BEC -->|V+ screw terminal| PCA[PCA9685<br/>16-ch servo board]

  JET -->|pin 1 3.3 V → VCC<br/>pin 3 SDA, pin 5 SCL| PCA
  JET -->|pins 32/33 PWM → ENA/ENB<br/>pins 29,31,35,37 → IN1-IN4| L298
  L298 -->|OUT1/OUT2| ML[Left track motor]
  L298 -->|OUT3/OUT4| MR[Right track motor]
  PCA -->|ch 0-6| SERVOS[Head, neck, eyes, arms]

  GND((Common ground)) --- JET
  GND --- PCA
  GND --- L298
  GND --- BAT
```

## Pin table (Jetson 40-pin header, BOARD numbering)

| Jetson pin | Name | Goes to | Notes |
|---|---|---|---|
| 1 | 3.3 V | PCA9685 VCC | logic power only, a few mA |
| 3 | I2C SDA | PCA9685 SDA | bus 1 on Nano, bus 7 on Orin Nano |
| 5 | I2C SCL | PCA9685 SCL | |
| 6 | GND | PCA9685 GND | |
| 32 | PWM0 | L298N ENA | **remove the ENA jumper cap**. Orin Nano: use pin 15 |
| 29 | GPIO | L298N IN1 | |
| 31 | GPIO | L298N IN2 | |
| 33 | PWM2 | L298N ENB | **remove the ENB jumper cap** |
| 35 | GPIO | L298N IN3 | |
| 37 | GPIO | L298N IN4 | |
| 39 | GND | L298N GND | ties logic grounds together |

## Rules that protect the Jetson

1. **Servos never draw from the Jetson.** Servo power goes into the PCA9685's
   V+ screw terminal from its own supply. The Jetson only powers the chip's
   logic (pin 1 → VCC).
2. **Do not connect the L298N's "+5V" terminal to the Jetson.** Leave its
   5 V regulator jumper as is and leave that terminal unconnected (or use it
   only for the L298N itself).
3. **One common ground.** Jetson GND, PCA9685 GND, L298N GND and battery
   negative must all connect, or the control signals have no reference.
4. **Jetson pins are 3.3 V and not 5 V tolerant.** We only drive outputs into
   the L298N (its inputs accept 3.3 V as high), so no level shifter is needed.
   Never wire a 5 V signal back into a Jetson pin.

## Servo channel map

Carried over from the old Arduino firmware; see `config/robot.yaml`.

| Ch | Joint (name in config) |
|---|---|
| 0 | head_pan |
| 1 | neck_upper |
| 2 | neck_lower |
| 3 | eye_right |
| 4 | eye_left |
| 5 | arm_right |
| 6 | arm_left |
| 7-15 | free |
