# Pi ↔ ESP32 UART Protocol

## Physical layer

- Raspberry Pi UART (`/dev/ttyS0`, GPIO14/15) ↔ ESP32 UART2 (any two free GPIOs via `HardwareSerial`).
- 115200 baud, 8N1, TX→RX / RX→TX crossed, common ground back to the star-ground point (BMS P-).
- Both sides are native 3.3V logic — no level shifter needed.

## Design boundary

The ESP32 owns balance and motion math end-to-end (IMU read → filter → PID → step/dir pulses).
The Pi never sends raw velocity, angle, or motor commands — only high-level intent. This keeps a
runaway or slow Pi process (Gemini API hang, camera stall) from ever being able to destabilize the
balance loop; worst case the ESP32 just keeps balancing in place on stale/default intent.

## Direction 1: Pi → ESP32 (implemented, `Pi.py::uart_worker`, 10 Hz)

```
$GEMINI_STATUS,EMOTION,ERROR,X_OFFSET,SPECIAL\n
```

| Field | Type | Values | Meaning |
|---|---|---|---|
| `GEMINI_STATUS` | enum | `BOOTING`, `LISTENING`, `PARSING`, `THINKING`, `SPEAKING`, `API_ERR`, `MIC_ERR`, `CAM_LOST` | What the conversation pipeline is doing — drives face/LCD state, not motion |
| `EMOTION` | enum | `HAPPY`, `SAD`, `CONFUSED`, `EXCITED`, `SCARED`, `THINKING` | Expression to show on the face display |
| `ERROR` | enum | `NOT_ERROR`, `MIC_ERR`, `CAM_LOST`, `API_ERR`, `UART_ERR`, `YOLO_ERR`, `TTS_ERR`, `AUDIO_ERR` | Latest fault flag from any Pi subsystem |
| `X_OFFSET` | int | pixels, negative = person left, positive = person right, `0` = centered/no detection | Lateral follow bias — the *only* motion input from the Pi |
| `SPECIAL` | enum | `NONE`, `SPIN`, `DANCE`, `LEAN_FORWARD`, `LEAN_BACKWARD` | One-shot macro the ESP32 plays out fully before returning to normal balance/follow behavior |

**ESP32-side parsing:** read until `\n`, discard if it doesn't start with `$`, `strtok` the rest on `,`.
Treat an unrecognized enum value as `NOT_ERROR`/`NONE` rather than crashing — the Pi side should
never be able to send a string that hangs the control loop.

`X_OFFSET` and `SPECIAL` together *are* the "driving override" channel: `X_OFFSET` is a continuous
bias the balance loop blends in (e.g. add a small differential to left/right step rate proportional
to offset, clamped), `SPECIAL` is a discrete macro request. Both are advisory — the ESP32 should
ignore them (or fall back to `NONE`/`0`) if it hasn't received a fresh packet in some timeout window
(e.g. 500 ms), so a dead Pi never leaves the robot leaning or spinning.

## Direction 2: ESP32 → Pi (not yet implemented — for when you get to the ESP32 side)

Low rate (~1 Hz) is enough since nothing on the Pi side is control-critical:

```
#BATTERY_MV,FALL_DETECTED,UPTIME_S\n
```

| Field | Type | Meaning |
|---|---|---|
| `BATTERY_MV` | int | Pack voltage in millivolts, for low-battery warnings/TTS |
| `FALL_DETECTED` | bool (`0`/`1`) | Set when the balance loop gives up (angle out of recoverable range) — Pi can pause the conversation loop and have Jelo comment on it |
| `UPTIME_S` | int | ESP32 uptime, mainly useful for detecting an unexpected reset |

Prefixing this direction with `#` instead of `$` makes the two streams trivially distinguishable if
you ever need to sniff both directions on one logic analyzer capture. Nothing in `Pi.py` reads serial
input yet — add a `uart_reader()` task mirroring `uart_worker()` (readline in a thread, parse, update
`robot_state` under `state_lock`) once the ESP32 side actually emits this.

## Timeout / failure behavior

- Pi side: `uart_worker` already treats a closed/errored port as non-fatal (sim mode) and retries
  opening it every 5 s — see `Pi.py`.
- ESP32 side (your responsibility): stop trusting `X_OFFSET`/`SPECIAL` after ~500 ms without a new
  packet; that's a design requirement of this protocol, not just a suggestion.
