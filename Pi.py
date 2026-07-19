"""
robot_main.py  —  Jelo companion bot · Raspberry Pi 3
======================================================
Combines conversation pipeline + CV follow loop into
one async process. Fully headless (no cv2.imshow).

Dependencies:
    pip install pyaudio SpeechRecognition pyserial \
                opencv-python-headless ultralytics \
                google-genai edge-tts pygame pillow \
                python-dotenv

UART packet format (10 Hz → ESP32):
    $GEMINI_STATUS,EMOTION,ERROR,X_OFFSET,SPECIAL\n

    GEMINI_STATUS : BOOTING | LISTENING | PARSING | THINKING | SPEAKING | API_ERR | MIC_ERR | CAM_LOST
    EMOTION       : HAPPY | SAD | CONFUSED | EXCITED | SCARED | THINKING
    ERROR         : NOT_ERROR | MIC_ERR | CAM_LOST | API_ERR | UART_ERR | YOLO_ERR | TTS_ERR | AUDIO_ERR
    X_OFFSET      : integer pixels, negative = person left, positive = person right
    SPECIAL       : NONE | SPIN | DANCE | LEAN_FORWARD | LEAN_BACKWARD
"""

import os, io, re, sys, math, struct, asyncio, time, warnings
import cv2
import numpy as np
from PIL import Image
from dotenv import load_dotenv
from google import genai
from google.genai import types
import pygame
import edge_tts
import serial
from ultralytics import YOLO

# ── silence noisy imports ──────────────────────────────────────────────
os.environ["PYGAME_HIDE_SUPPORT_PROMPT"] = "hide"
warnings.filterwarnings("ignore", category=UserWarning)
warnings.filterwarnings("ignore", category=DeprecationWarning)

try:
    import pyaudio
    import speech_recognition as sr
except ImportError:
    print("❌  Run: pip install pyaudio SpeechRecognition")
    sys.exit(1)


# ══════════════════════════════════════════════════════════════════════
# CONFIG
# ══════════════════════════════════════════════════════════════════════
GEMINI_MODEL    = "gemini-3.1-flash-lite"
TTS_VOICE       = "en-US-BrianNeural"
TTS_RATE        = "+10%"

# Audio
AUDIO_FORMAT    = pyaudio.paInt16
AUDIO_CHANNELS  = 1
AUDIO_RATE      = 16000          # 16 kHz is enough for speech recognition
AUDIO_CHUNK     = 1024
SILENCE_LIMIT   = 1.5            # seconds of silence before utterance ends
THRESHOLD       = 300            # RMS gate — below this = silence
MIC_INDEX       = 2              # INMP441 device index, check with: python -m speech_recognition

# Camera / CV
CAM_INDEX       = 0
CAM_W, CAM_H    = 320, 240
CV_FPS          = 8
YOLO_MODEL      = "yolo26n.pt"
YOLO_IMGSZ      = 160
YOLO_CONF       = 0.35
DEAD_ZONE_RATIO = 0.08           # fraction of frame width treated as "centered"

# UART
UART_PORT       = "/dev/ttyS0"
UART_BAUD       = 115200
UART_HZ         = 10

# Send camera frame to Gemini every N conversation turns (1 = always)
CAM_SEND_EVERY  = 1


# ══════════════════════════════════════════════════════════════════════
# SHARED STATE
# ══════════════════════════════════════════════════════════════════════
state_lock = asyncio.Lock()
cam_lock   = asyncio.Lock()   # serializes cap.grab()/cap.read() between cv_follow_loop and conversation_loop

robot_state = {
    # --- Gemini / conversation layer ---
    "gemini_status":  "BOOTING",    # what the Gemini pipeline is doing right now
    "emotion":        "HAPPY",      # facial expression command for ESP face display

    # --- Error tracking (any subsystem can write here) ---
    # NOT_ERROR | MIC_ERR | CAM_LOST | API_ERR | UART_ERR | YOLO_ERR | TTS_ERR | AUDIO_ERR
    "error_state":    "NOT_ERROR",

    # --- Movement (ESP32 owns all motion math) ---
    # x_offset: pixel distance of detected person from frame centre
    #   negative = person is LEFT of centre → ESP should turn left
    #   positive = person is RIGHT of centre → ESP should turn right
    #   zero (or no detection) = no lateral correction needed
    # ESP combines x_offset with ToF distance to compute actual wheel commands.
    "x_offset":       0,

    # special_move: one-shot macro animation the ESP plays out fully
    # NONE | SPIN | DANCE | LEAN_FORWARD | LEAN_BACKWARD
    "special_move":   "NONE",

    # --- Internal only (not sent over UART) ---
    "speaking":       False,        # True while TTS audio is playing
    "rms":            0,            # current mic loudness, used for silence detection only
}


# ══════════════════════════════════════════════════════════════════════
# HARDWARE INIT
# ══════════════════════════════════════════════════════════════════════

# UART
try:
    ser = serial.Serial(port=UART_PORT, baudrate=UART_BAUD, timeout=1)
    print(f"📡  UART ready on {UART_PORT}")
except Exception as e:
    print(f"⚠️   UART unavailable (sim mode): {e}")
    ser = None

# Gemini client
load_dotenv()
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
if not GEMINI_API_KEY:
    print("❌  GEMINI_API_KEY not set. Create a .env file (see .env.example) with GEMINI_API_KEY=your_key")
    sys.exit(1)
client = genai.Client(api_key=GEMINI_API_KEY).aio

SYSTEM_PROMPT = """
CRITICAL RULES:
- You are my male friend. YOU ARE NOT AN AI OR A ROBOT. NO LYING or OVEREXAGGERATING AT ALL COST. BE AS REAL AS YOU CAN.
- Input can be Thai or English. Respond ONLY in English with Gen Z language. You can swear. Be funny and not annoying.
- Choose exactly ONE facial expression from [HAPPY, SAD, CONFUSED, EXCITED, SCARED, THINKING].
- Choose exactly ONE body expression from [NONE, SPIN, DANCE, LEAN_FORWARD, LEAN_BACKWARD].
- Place BOTH commands at the VERY BEGINNING wrapped in angle brackets like: <HAPPY, SPIN>
- No emoji or markdown. Response will be read by TTS.
- For casual chat: 1-3 sentences. For explanations: as long as needed.
- Do not repeat the same comment. Try to start new topics sometimes.
Example: <HAPPY, SPIN> Yo bro, nice shirt. Where'd you get that?
"""

gemini_config = types.GenerateContentConfig(
    system_instruction=SYSTEM_PROMPT,
    temperature=1.1,
    max_output_tokens=1000,
)

# YOLO
print("🔍  Loading YOLO model...")
try:
    yolo = YOLO(YOLO_MODEL)
    print("✅  YOLO ready.")
except Exception as e:
    print(f"❌  YOLO failed to load: {e}")
    sys.exit(1)

# Camera
cap = cv2.VideoCapture(CAM_INDEX)
cap.set(cv2.CAP_PROP_FRAME_WIDTH,  CAM_W)
cap.set(cv2.CAP_PROP_FRAME_HEIGHT, CAM_H)
cap.set(cv2.CAP_PROP_AUTOFOCUS, 0)
cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)   # discard stale frames immediately

if not cap.isOpened():
    print(f"❌  Camera index {CAM_INDEX} failed to open.")
    sys.exit(1)
print(f"📷  Camera ready (index {CAM_INDEX}, {CAM_W}x{CAM_H})")


# ══════════════════════════════════════════════════════════════════════
# HELPERS
# ══════════════════════════════════════════════════════════════════════

def get_rms(data: bytes) -> float:
    """
    Root Mean Square of raw PCM audio bytes.
    Converts raw bytes → 16-bit signed ints → squared average → sqrt.
    Result is a loudness value: 0 = silence, ~300+ = speech.
    """
    count = len(data) // 2
    if count == 0:
        return 0.0
    shorts = struct.unpack(f"{count}h", data)
    return math.sqrt(sum(s * s for s in shorts) / count)


def grab_fresh_frame():
    """Flush OpenCV's internal buffer then grab a fresh frame."""
    cap.grab()
    return cap.read()


# ══════════════════════════════════════════════════════════════════════
# TASK 1 — CV FOLLOW LOOP  (8 fps, headless)
# ══════════════════════════════════════════════════════════════════════

async def cv_follow_loop():
    interval  = 1.0 / CV_FPS
    dead_zone = int(CAM_W * DEAD_ZONE_RATIO)
    cx        = CAM_W // 2
    print("👁️   CV follow loop started.")

    while True:
        t0 = time.monotonic()

        # Skip CV while speaking — saves CPU for TTS playback
        async with state_lock:
            speaking = robot_state["speaking"]
        if speaking:
            await asyncio.sleep(interval)
            continue

        async with cam_lock:
            ret, frame = await asyncio.to_thread(grab_fresh_frame)
        if not ret:
            async with state_lock:
                robot_state["error_state"] = "CAM_LOST"
            print("⚠️   CV: failed to grab frame.")
            await asyncio.sleep(0.1)
            continue

        try:
            results = await asyncio.to_thread(
                yolo.predict,
                source=frame,
                imgsz=YOLO_IMGSZ,
                conf=YOLO_CONF,
                classes=[0],      # person class only
                verbose=False,
            )
        except Exception as e:
            print(f"❌  YOLO inference error: {e}")
            async with state_lock:
                robot_state["error_state"] = "YOLO_ERR"
            await asyncio.sleep(0.2)
            continue

        x_offset = 0   # 0 = no detection or centred → ESP holds position

        for result in results:
            if len(result.boxes) == 0:
                break
            # pick highest-confidence detection
            best   = result.boxes[result.boxes.conf.argmax()]
            x1, _, x2, _ = map(int, best.xyxy[0])
            x_avg  = (x1 + x2) // 2
            x_offset = x_avg - cx   # negative = left, positive = right
            # dead-zone: if within ±dead_zone pixels treat as centred
            if abs(x_offset) <= dead_zone:
                x_offset = 0
            break

        async with state_lock:
            robot_state["x_offset"]   = x_offset
            # Clear YOLO_ERR on successful inference
            if robot_state["error_state"] == "YOLO_ERR":
                robot_state["error_state"] = "NOT_ERROR"

        elapsed = time.monotonic() - t0
        await asyncio.sleep(max(0.001, interval - elapsed))


# ══════════════════════════════════════════════════════════════════════
# TASK 2 — UART TELEMETRY  (10 Hz)
# Packet: $GEMINI_STATUS,EMOTION,ERROR,X_OFFSET,SPECIAL\n
# ══════════════════════════════════════════════════════════════════════

async def uart_worker():
    global ser
    print("📡  UART telemetry worker started.")
    last_reconnect_attempt = 0.0
    RECONNECT_INTERVAL = 5.0   # seconds between reconnect attempts when port is down

    while True:
        if not (ser and ser.is_open):
            now = time.monotonic()
            if now - last_reconnect_attempt >= RECONNECT_INTERVAL:
                last_reconnect_attempt = now
                try:
                    ser = serial.Serial(port=UART_PORT, baudrate=UART_BAUD, timeout=1)
                    print(f"📡  UART reconnected on {UART_PORT}")
                    async with state_lock:
                        if robot_state["error_state"] == "UART_ERR":
                            robot_state["error_state"] = "NOT_ERROR"
                except Exception:
                    ser = None
        else:
            async with state_lock:
                packet = (
                    f"${robot_state['gemini_status']},"
                    f"{robot_state['emotion']},"
                    f"{robot_state['error_state']},"
                    f"{robot_state['x_offset']},"
                    f"{robot_state['special_move']}\n"
                )
            try:
                await asyncio.to_thread(ser.write, packet.encode())
            except Exception as e:
                print(f"⚠️   UART write error: {e}")
                async with state_lock:
                    robot_state["error_state"] = "UART_ERR"
                try:
                    ser.close()
                except Exception:
                    pass
                ser = None
        await asyncio.sleep(1.0 / UART_HZ)


# ══════════════════════════════════════════════════════════════════════
# TASK 3 — TTS PIPELINE
# ══════════════════════════════════════════════════════════════════════

sentence_q = asyncio.Queue()
audio_q    = asyncio.Queue()


async def tts_downloader():
    """Fetches audio from edge-tts as each sentence arrives."""
    while True:
        sentence = await sentence_q.get()
        if sentence is None:
            await audio_q.put(None)
            sentence_q.task_done()
            break
        try:
            com = edge_tts.Communicate(text=sentence, voice=TTS_VOICE, rate=TTS_RATE)
            buf = io.BytesIO()
            async for chunk in com.stream():
                if chunk["type"] == "audio":
                    buf.write(chunk["data"])
            buf.seek(0)
            await audio_q.put(buf)
        except Exception as e:
            print(f"❌  TTS download error: {e}")
            async with state_lock:
                robot_state["error_state"] = "TTS_ERR"
        finally:
            sentence_q.task_done()


async def tts_player():
    """Plays audio buffers sequentially via pygame."""
    pygame.mixer.pre_init(44100, -16, 2, 2048)
    pygame.mixer.init()
    while True:
        buf = await audio_q.get()
        if buf is None:
            audio_q.task_done()
            break
        try:
            buf.seek(0)
            pygame.mixer.music.load(buf)
            pygame.mixer.music.play()
            async with state_lock:
                robot_state["speaking"]      = True
                robot_state["gemini_status"] = "SPEAKING"
            while pygame.mixer.music.get_busy():
                await asyncio.sleep(0.01)
            pygame.mixer.music.unload()
            buf.close()
        except Exception as e:
            print(f"❌  TTS playback error: {e}")
            async with state_lock:
                robot_state["error_state"] = "AUDIO_ERR"
        finally:
            if audio_q.empty():
                async with state_lock:
                    robot_state["speaking"]      = False
                    robot_state["gemini_status"] = "LISTENING"
            audio_q.task_done()
    pygame.quit()


# ══════════════════════════════════════════════════════════════════════
# TASK 4 — SPEECH INPUT
# ══════════════════════════════════════════════════════════════════════

async def listen_and_transcribe() -> str:
    p = pyaudio.PyAudio()
    try:
        stream = p.open(
            format=AUDIO_FORMAT, channels=AUDIO_CHANNELS,
            rate=AUDIO_RATE, input=True,
            frames_per_buffer=AUDIO_CHUNK,
            input_device_index=MIC_INDEX,
        )
    except Exception as e:
        print(f"❌  Mic open error (index {MIC_INDEX}): {e}")
        async with state_lock:
            robot_state["error_state"] = "MIC_ERR"
        p.terminate()
        await asyncio.sleep(2)
        return ""

    recognizer                          = sr.Recognizer()
    recognizer.energy_threshold         = THRESHOLD
    recognizer.dynamic_energy_threshold = False

    frames, has_spoken, silence_start = [], False, None
    record_start = asyncio.get_event_loop().time()
    MAX_RECORD_SECONDS = 20   # safety cap so a stuck-open mic can't grow frames forever

    async with state_lock:
        robot_state["gemini_status"] = "LISTENING"
        robot_state["error_state"]   = "NOT_ERROR"

    print("🎤  Listening...", end="", flush=True)

    while True:
        try:
            data = await asyncio.to_thread(stream.read, AUDIO_CHUNK, exception_on_overflow=False)
        except Exception as e:
            print(f"\n❌  Mic read error: {e}")
            async with state_lock:
                robot_state["error_state"] = "MIC_ERR"
            break

        rms = get_rms(data)
        async with state_lock:
            robot_state["rms"] = rms

        if rms > THRESHOLD:
            if not has_spoken:
                has_spoken = True
                print(" recording...", end="", flush=True)
            silence_start = None

        if has_spoken:
            frames.append(data)
            if rms <= THRESHOLD and silence_start is None:
                silence_start = asyncio.get_event_loop().time()
            elif rms > THRESHOLD:
                silence_start = None

        if has_spoken and silence_start is not None:
            if asyncio.get_event_loop().time() - silence_start > SILENCE_LIMIT:
                break

        if asyncio.get_event_loop().time() - record_start > MAX_RECORD_SECONDS:
            print(" (max recording length reached)", end="", flush=True)
            break

        await asyncio.sleep(0.001)

    stream.stop_stream()
    stream.close()
    p.terminate()

    if not frames:
        print(" (nothing recorded)")
        return ""

    async with state_lock:
        robot_state["gemini_status"] = "PARSING"

    print(" parsing...", end="", flush=True)

    raw        = b"".join(frames)
    audio_data = sr.AudioData(raw, AUDIO_RATE, 2)

    def try_parse(lang):
        try:
            return recognizer.recognize_google(audio_data, language=lang)
        except Exception:
            return ""

    en, th = await asyncio.gather(
        asyncio.to_thread(try_parse, "en-US"),
        asyncio.to_thread(try_parse, "th-TH"),
    )

    if th and not en:
        result = th
    elif en and not th:
        result = en
    elif th and en:
        result = th if any("\u0e00" <= c <= "\u0e7f" for c in th) else en
    else:
        result = ""

    if result:
        print(f"\n🗣️   \"{result}\"", flush=True)
    else:
        print(" (nothing recognised)", flush=True)
    return result


# ══════════════════════════════════════════════════════════════════════
# TASK 5 — GEMINI CONVERSATION LOOP
# ══════════════════════════════════════════════════════════════════════

async def conversation_loop():
    conversation_history = []
    turn_counter         = 0
    print(f"🤖  Conversation loop started ({GEMINI_MODEL}).")

    while True:
        spoken = await listen_and_transcribe()
        if not spoken.strip():
            continue

        turn_counter += 1
        async with state_lock:
            robot_state["gemini_status"] = "THINKING"

        # Grab camera frame for Gemini context
        pil_image = None
        if turn_counter % CAM_SEND_EVERY == 0:
            async with cam_lock:
                ret, frame = await asyncio.to_thread(grab_fresh_frame)
            if ret:
                # frame is already CAM_W x CAM_H — no resize needed before encoding
                _, buf    = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 70])
                pil_image = Image.open(io.BytesIO(buf.tobytes()))
            else:
                print("⚠️   Gemini: camera frame unavailable.")
                async with state_lock:
                    robot_state["error_state"] = "CAM_LOST"

        payload = []
        if pil_image:
            payload.append(pil_image)
        payload.append(f"User Spoke: {spoken}")

        full_response = ""
        text_buffer   = ""
        print("🤖  ", end="", flush=True)

        try:
            response = await client.models.generate_content_stream(
                model=GEMINI_MODEL,
                contents=conversation_history + payload,
                config=gemini_config,
            )

            async for chunk in response:
                if not chunk.text:
                    continue
                print(chunk.text, end="", flush=True)
                full_response += chunk.text
                text_buffer   += chunk.text

                # Stream sentences to TTS as they arrive — minimises first-word latency
                if any(m in text_buffer for m in (". ", "! ", "? ", "\n")):
                    clean = re.sub(r"<[^>]+>", "", text_buffer)
                    parts = re.split(r"(?<=[.!?])\s+|\n", clean)
                    if parts[0].strip():
                        await sentence_q.put(parts[0].strip())
                    text_buffer = " ".join(parts[1:]) if len(parts) > 1 else ""

        except Exception as e:
            print(f"\n❌  Gemini API error: {e}", flush=True)
            async with state_lock:
                robot_state["error_state"]   = "API_ERR"
                robot_state["gemini_status"] = "API_ERR"
            continue

        # Flush remaining TTS buffer
        leftover = re.sub(r"<[^>]+>", "", text_buffer).strip()
        if leftover:
            await sentence_q.put(leftover)
        print(flush=True)

        # Update conversation history (keep last 20 turns = 40 entries)
        if full_response.strip():
            conversation_history.append(
                types.Content(role="user",  parts=[types.Part.from_text(text=f"User Spoke: {spoken}")])
            )
            conversation_history.append(
                types.Content(role="model", parts=[types.Part.from_text(text=full_response)])
            )
            if len(conversation_history) > 40:
                conversation_history.pop(0)
                conversation_history.pop(0)

        # Parse emotion and special move from response tags
        face_match    = re.search(r"<(HAPPY|SAD|CONFUSED|EXCITED|SCARED|THINKING)", full_response.upper())
        special_match = re.search(r"\b(SPIN|DANCE|LEAN_FORWARD|LEAN_BACKWARD)\b", full_response.upper())

        async with state_lock:
            if face_match:
                robot_state["emotion"] = face_match.group(1)
            robot_state["special_move"] = special_match.group(1) if special_match else "NONE"
            robot_state["error_state"]  = "NOT_ERROR"


# ══════════════════════════════════════════════════════════════════════
# ENTRY POINT
# ══════════════════════════════════════════════════════════════════════

async def main():
    print("🚀  Jelo robot starting up...")
    try:
        await asyncio.gather(
            cv_follow_loop(),
            uart_worker(),
            tts_downloader(),
            tts_player(),
            conversation_loop(),
        )
    except asyncio.CancelledError:
        pass
    finally:
        await sentence_q.put(None)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n👋  Shutting down...")
    finally:
        if ser and ser.is_open:
            ser.close()
        cap.release()
        print("🔌  Clean shutdown complete.")