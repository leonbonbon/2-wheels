# Lower-Tier Wiring Reference — ESP32, Motors, Power, IMU

Scope: everything below the Pi. Battery → BMS → charger/switch → power rails, both
NEMA17 + TMC2209 drivers, the MPU6050, and the ESP32 pins that tie it together. No
Pi wiring yet — that comes later as its own doc. This is the reference to wire
against before you start writing the balance/PID control code.

Board assumed: ESP32-WROOM-32D dev board. Driver assumed: Pololu-footprint TMC2209
UART module (BTT/FYSETC-style) — pin *names* below are near-universal for this
footprint, but confirm against your specific board's silkscreen before wiring;
low-cost clones vary slightly.

## 1. Power system

### Topology

```
18650 x3 (series)              Type-C 3S Boost Charger
   │  │  │                            │      │
   C+ J2 J1 C-                      BAT+   BAT-
   │  │  │  │                         │      │
   ▼  ▼  ▼  ▼                         ▼      ▼
┌─────────────────────────────────────────────┐
│  3S BMS   B+ B1 B2 B-        P+          P-  │
└─────────────────────────────────────────────┘
   (sense/balance,                │            │
    thin wire, no                 ▼            │
    load current)              SPST switch     │
                                   │            │
                                   ▼            │
                          ── 12V BUS (switched) ┼── STAR GROUND POINT
                          │      │      │       │   (BMS P-, unswitched)
                          ▼      ▼      ▼       │
                     TMC2209  TMC2209  12V fan  │
                       #1 VM    #2 VM    (+)    │
                          │      │      │       │
                          ▼      ▼      ▼       │
                     Buck#1(5V,Pi,   Buck#2(5V, │
                     reserved,        2A→ESP32/ │
                     not wired yet)   IMU)      │
                                          │      │
                                    each GND ────┘  (individual home run)
```

- **B+ / B1 / B2 / B-** on the BMS are thin *sense/balance* taps to each series
  junction — cell1/2 junction → B1, cell2/3 junction → B2, pack top → B+, pack
  bottom → B-. No load current runs through these; don't use them as a power
  path.
- **P+ / P-** is the BMS's single high-current port — both the Type-C charger's
  output *and* the switch/load side connect here. This is standard for common
  low-cost 3S 10-20A BMS boards (one FET pair handles both charge and
  discharge protection). Verify against your board's silkscreen; a few
  variants split charge/discharge onto separate pads.
- The **SPST switch sits only in the P+ path.** BMS P- runs straight through,
  unswitched, to the star-ground point. Never put a switch or fuse in the
  ground return — that's how you'd break the reference every module measures
  against while still having "power."

### Star grounding

Every rail's *return* wire runs individually back to BMS P- rather than
daisy-chaining ground from module to module:

- TMC2209 #1 GND (power side) → star point
- TMC2209 #2 GND (power side) → star point
- 12V fan (−) → star point
- Buck#1 input (−) → star point (reserved, Pi not wired yet)
- Buck#2 input (−) → star point

Within a buck converter's *output* zone it's fine to share a common ground —
e.g. ESP32 GND and MPU6050 GND both tie to Buck#2's output ground, and only
that one wire runs back to the star point. The point of star grounding is
isolating the noisy high-current returns (motors, fan) from the quiet
logic/sensor return, not eliminating all shared ground everywhere.

### Bulk capacitor (don't skip this)

Put a **≥100–470 µF electrolytic capacitor, rated ≥25V**, across VM/GND close
to the drivers (one per driver, or one shared cap right at the 12V bus tap).
Stepper coils kick back significant inductive voltage on quick deceleration;
without local bulk capacitance that spike can exceed the TMC2209's rating and
kill the driver. This is a very common failure mode on stepstick-based builds
— cheap insurance.

## 2. Motor + driver wiring (x2, identical except address/GPIO)

### TMC2209 pinout (Pololu-footprint UART module)

| Pin | Connects to | Notes |
|---|---|---|
| VM | 12V bus (switched) | motor supply |
| GND (power side) | star ground point | home-run wire, not shared with logic GND |
| 1A / 1B | NEMA17 coil A | verify pairing, see below |
| 2A / 2B | NEMA17 coil B | verify pairing, see below |
| VIO | ESP32 **3V3** | sets logic threshold — 3.3V, not 5V, since ESP32 GPIOs are 3.3V |
| GND (logic side) | ESP32 GND | shared logic ground is fine here |
| EN | shared ESP32 GPIO32 | active LOW, pull-up to 3V3 (see safety note below) |
| STEP | per-motor ESP32 GPIO | see pin table |
| DIR | per-motor ESP32 GPIO | see pin table |
| PDN_UART | shared ESP32 GPIO18 | single-wire UART bus, both drivers on one line |
| MS1 / MS2 | static strap, not to ESP32 | sets UART slave address — see below |
| DIAG / INDEX | unconnected for now | optional, only needed for stall detection/homing |

**UART addressing:** in UART mode, MS1/MS2 select the driver's slave address
instead of microstep resolution (microsteps are set over UART instead).
Driver L: MS1→GND, MS2→GND (address 0). Driver R: MS1→VIO, MS2→GND (address
1). This lets both drivers share the single PDN_UART line while your firmware
talks to each independently (e.g. via TMCStepper).

**Current setting:** set RMS current over UART in firmware rather than
hunting for a Vref trimpot — most UART-mode TMC2209 boards don't expose one
usefully. Use your NEMA17's rated phase current from its datasheet and stay
under the TMC2209's ~1.7A RMS continuous rating; the fan on the direct 12V
rail is there specifically so you have thermal headroom to run closer to that
limit.

### NEMA17 coil check

4-wire NEMA17 coloring is *not* standardized across vendors. The common (not
universal) convention is Black/Green = coil A, Red/Blue = coil B — but verify
with a multimeter continuity test before wiring to the driver: touch probes
between wire pairs, the two wires of a coil will show low resistance (a few
ohms) to each other and no continuity to the other coil's wires. Get this
wrong and the motor will stall/vibrate instead of turning.

## 3. ESP32 pin assignment

| GPIO | Function | Notes |
|---|---|---|
| 21 | I2C SDA → MPU6050 | ESP32 default I2C pin |
| 22 | I2C SCL → MPU6050 | ESP32 default I2C pin |
| 4 | MPU6050 INT (optional) | data-ready interrupt, avoids polling in your control loop |
| 25 | STEP — left motor | |
| 26 | DIR — left motor | |
| 27 | STEP — right motor | |
| 14 | DIR — right motor | |
| 32 | EN — both drivers (shared) | active LOW, pull-up = disabled by default at boot |
| 18 | PDN_UART — both drivers (shared) | single-wire UART bus |
| 16 | UART2 RX — **reserved** for Pi link | not wired yet, don't reuse |
| 17 | UART2 TX — **reserved** for Pi link | not wired yet, don't reuse |

**Avoid:** GPIO 0/2/5/12/15 (boot-strapping pins — using them can prevent the
board from booting depending on state at power-up), GPIO 6–11 (wired
internally to flash, unusable), GPIO 1/3 (UART0, used by USB programming/serial
monitor). GPIO 34–39 are input-only (no internal pull-up/down) — fine for
future ADC use (e.g. battery voltage sense) but not usable for STEP/DIR/EN.

**Safety default — shared EN:** wiring EN active-LOW with a pull-up to 3.3V
means both drivers power up *disabled* by default, before your firmware runs.
Your control code should only pull GPIO32 LOW after IMU init and calibration
have settled — that's the intended handoff point into the balance loop you're
building. Without this, the drivers could receive noise/garbage on STEP
during boot before your code is in control.

## 4. IMU (MPU6050) wiring

| MPU6050 pin | Connects to |
|---|---|
| VCC | ESP32 3V3 (breakout has its own onboard 3.3V regulator on most GY-521 boards, so 5V from Buck#2 also works if you'd rather feed it there — 3V3 from the ESP32 is simplest) |
| GND | ESP32 GND (same logic ground as the drivers' logic side) |
| SCL | GPIO22 |
| SDA | GPIO21 |
| AD0 | GND (sets I2C address to 0x68, the default) |
| INT | GPIO4 (optional) |

Most GY-521 breakouts already have onboard 4.7kΩ pull-ups on SDA/SCL — check
yours before adding external ones.

**Mounting:** fix the MPU6050 rigidly (no foam/tape flex) as close to the
wheel axle centerline as the chassis allows, oriented so one sensor axis is
parallel to the robot's pitch (tilt) axis. Any mounting slop or offset from
the axle shows up directly as noise/bias in your angle estimate later.

## 5. Pre-power-on checklist

- [ ] Continuity-check every module's ground back to the BMS P- star point
      before connecting the battery.
- [ ] Confirm the switch interrupts only P+ — P- should read continuous to
      the star point with the switch off.
- [ ] Measure TMC2209 VIO reads 3.3V (not 5V) before connecting STEP/DIR/EN —
      wrong VIO can mean the driver never sees your GPIOs as logic-high.
- [ ] Multimeter-verify NEMA17 coil pairs before wiring into 1A/1B/2A/2B.
- [ ] Bulk capacitor installed across VM/GND on each driver.
- [ ] First power-up: motors mechanically disconnected from the wheels, EN
      left high (disabled) until you've confirmed the ESP32 sketch is running
      and IMU is reading sane values.
