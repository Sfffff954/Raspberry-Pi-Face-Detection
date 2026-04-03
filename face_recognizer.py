#!/usr/bin/env python3
"""
face_recognizer.py - Runs on Raspberry Pi 3
Subscribes to MQTT face events from Pi Zero, runs face_recognition
to identify known faces, and sends Telegram notifications with snapshots.
"""

import face_recognition
import paho.mqtt.client as mqtt
import requests
import base64
import json
import numpy as np
import logging
import os
import pickle
import time
from datetime import datetime
from pathlib import Path

# ── Config ────────────────────────────────────────────────────────────────────
MQTT_BROKER = "localhost"
MQTT_PORT   = 1883
MQTT_TOPIC  = "home/security/face"

TELEGRAM_BOT_TOKEN = "YOUR_BOT_TOKEN_HERE"   # from @BotFather
TELEGRAM_CHAT_ID   = "YOUR_CHAT_ID_HERE"     # your personal chat ID

KNOWN_FACES_DIR    = Path("known_faces")      # folder with known face images
ENCODINGS_CACHE    = Path("encodings.pkl")    # cached encodings for speed
TOLERANCE          = 0.55                     # lower = stricter matching
COOLDOWN_SECONDS   = 30                       # min seconds between notifications
# ──────────────────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [Pi3] %(levelname)s: %(message)s"
)
log = logging.getLogger(__name__)

last_notification_time = 0


# ── Telegram helpers ──────────────────────────────────────────────────────────

def send_telegram_message(text: str):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    resp = requests.post(url, data={"chat_id": TELEGRAM_CHAT_ID, "text": text}, timeout=10)
    if not resp.ok:
        log.error(f"Telegram message failed: {resp.text}")


def send_telegram_photo(image_bytes: bytes, caption: str):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendPhoto"
    resp = requests.post(
        url,
        data={"chat_id": TELEGRAM_CHAT_ID, "caption": caption},
        files={"photo": ("snapshot.jpg", image_bytes, "image/jpeg")},
        timeout=15
    )
    if not resp.ok:
        log.error(f"Telegram photo failed: {resp.text}")
    return resp.ok


# ── Face encoding helpers ─────────────────────────────────────────────────────

def load_known_faces():
    """Load known face encodings. Uses cache if available and up to date."""
    if ENCODINGS_CACHE.exists():
        log.info("Loading encodings from cache...")
        with open(ENCODINGS_CACHE, "rb") as f:
            return pickle.load(f)

    known_encodings = []
    known_names = []

    if not KNOWN_FACES_DIR.exists():
        log.warning(f"known_faces/ folder not found. Creating it.")
        KNOWN_FACES_DIR.mkdir()
        return known_encodings, known_names

    for img_path in KNOWN_FACES_DIR.iterdir():
        if img_path.suffix.lower() not in (".jpg", ".jpeg", ".png"):
            continue
        name = img_path.stem  # filename without extension = person's name
        image = face_recognition.load_image_file(str(img_path))
        encs = face_recognition.face_encodings(image)
        if encs:
            known_encodings.append(encs[0])
            known_names.append(name)
            log.info(f"Loaded encoding for: {name}")
        else:
            log.warning(f"No face found in {img_path.name}, skipping.")

    with open(ENCODINGS_CACHE, "wb") as f:
        pickle.dump((known_encodings, known_names), f)

    return known_encodings, known_names


def identify_faces(frame_rgb, known_encodings, known_names):
    """Returns list of identified names ('Unknown' if not recognized)."""
    locations = face_recognition.face_locations(frame_rgb)
    encodings = face_recognition.face_encodings(frame_rgb, locations)
    results = []
    for enc in encodings:
        matches = face_recognition.compare_faces(known_encodings, enc, tolerance=TOLERANCE)
        name = "Unknown"
        if True in matches:
            distances = face_recognition.face_distance(known_encodings, enc)
            best = int(np.argmin(distances))
            name = known_names[best]
        results.append(name)
    return results


# ── MQTT callback ─────────────────────────────────────────────────────────────

def make_on_message(known_encodings, known_names):
    def on_message(client, userdata, msg):
        global last_notification_time

        try:
            payload = json.loads(msg.payload.decode())
            face_count = payload.get("face_count", 0)
            image_b64 = payload.get("image_b64", "")
            ts = payload.get("timestamp", time.time())
        except Exception as e:
            log.error(f"Failed to parse MQTT payload: {e}")
            return

        if not image_b64:
            return

        image_bytes = base64.b64decode(image_b64)
        np_arr = np.frombuffer(image_bytes, dtype=np.uint8)

        import cv2
        frame_bgr = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)
        frame_rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)

        names = identify_faces(frame_rgb, known_encodings, known_names)
        timestamp_str = datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")

        log.info(f"Faces identified: {names}")

        # Throttle notifications
        now = time.time()
        if now - last_notification_time < COOLDOWN_SECONDS:
            log.info("Cooldown active, skipping notification.")
            return
        last_notification_time = now

        # Build caption
        if names:
            name_list = ", ".join(names)
            caption = f"🔔 Security Alert\n{timestamp_str}\nDetected: {name_list}"
        else:
            caption = f"🔔 Security Alert\n{timestamp_str}\nDetected: {face_count} face(s)"

        send_telegram_photo(image_bytes, caption)

    return on_message


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    log.info("Loading known faces...")
    known_encodings, known_names = load_known_faces()
    log.info(f"Loaded {len(known_names)} known person(s): {known_names}")

    client = mqtt.Client(client_id="pi3_face_recognizer")
    client.on_message = make_on_message(known_encodings, known_names)
    client.connect(MQTT_BROKER, MQTT_PORT, keepalive=60)
    client.subscribe(MQTT_TOPIC, qos=1)

    log.info(f"Subscribed to MQTT topic: {MQTT_TOPIC}")
    send_telegram_message("✅ Face Security System is online.")

    try:
        client.loop_forever()
    except KeyboardInterrupt:
        log.info("Stopped by user.")
        send_telegram_message("⚠️ Face Security System went offline.")
    finally:
        client.disconnect()


if __name__ == "__main__":
    main()
