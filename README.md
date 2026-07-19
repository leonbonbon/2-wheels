# 2 wheels

Raspberry Pi side of a two-wheeled self-balancing companion robot ("Jelo"). Handles voice input,
Gemini conversation + TTS, a camera-based person-follow signal, and a UART link to the ESP32 that
runs the balance/motor control loop.

The ESP32 firmware (IMU filtering, PID, stepper control) lives outside this repo and is intentionally
not covered here — see [`docs/UART_PROTOCOL.md`](docs/UART_PROTOCOL.md) for the contract between the
two boards.

## Setup

```bash
pip install -r requirements.txt
cp .env.example .env   # then fill in your own GEMINI_API_KEY
```

`Pi.py` expects:
- An INMP441 (or similar) mic reachable via PortAudio — check the device index with
  `python -m speech_recognition` and set `MIC_INDEX` accordingly.
- A camera at `CAM_INDEX` (default `0`).
- UART available at `UART_PORT` (default `/dev/ttyS0`) wired to the ESP32.

## Run

```bash
python Pi.py
```

## Layout

- `Pi.py` — the whole Pi-side process: CV follow loop, UART telemetry, TTS pipeline, mic capture,
  Gemini conversation loop, all running concurrently under `asyncio`.
- `docs/UART_PROTOCOL.md` — packet format and design boundary between Pi and ESP32.
