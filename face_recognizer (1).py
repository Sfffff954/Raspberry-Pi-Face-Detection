#!/usr/bin/env python3
"""
face_recognizer.py - Runs on Raspberry Pi 3

NEW FEATURES added:
  [EINFACH]       Per-person cooldown  – each known name has its own cooldown timer
  [MITTEL]        SQLite logging       – every detection is saved to detections.db
  [ANSPRUCHSVOLL] Telegram commands    – /arm, /disarm, /status via bot polling
"""

import os
import io
import json
import time
import base64
import logging
import sqlite3
import threading
import pickle
import requests
import numpy as np

import face_recognition
import paho.mqtt.client as mqtt
from PIL import Image

# ── Config ────────────────────────────────────────────────────────────────────
MQTT_BROKER         = "localhost"
MQTT_PORT           = 1883
MQTT_TOPIC          = "home/security/face"
MQTT_CONTROL_TOPIC  = "home/security/control"   # publishes arm/disarm to Pi Zero

TELEGRAM_BOT_TOKEN  = "YOUR_BOT_TOKEN_HERE"
TELEGRAM_CHAT_ID    = "YOUR_CHAT_ID_HERE"

KNOWN_FACES_DIR     = "known_faces"
ENCODINGS_FILE      = "encodings.pkl"
TOLERANCE           = 0.5

# ── [EINFACH] Per-person cooldown ─────────────────────────────────────────────
# Each name gets its own timer; unknown faces use key "Unknown"
COOLDOWN_PER_PERSON = 30          # seconds per individual name
COOLDOWN_UNKNOWN    = 20          # shorter cooldown for unknowns (more urgent)

# ── [MITTEL] SQLite DB ────────────────────────────────────────────────────────
DB_PATH             = "detections.db"
SNAPSHOT_DIR        = "snapshots"   # unknown face snapshots saved here

# ── [ANSPRUCHSVOLL] Telegram polling ─────────────────────────────────────────
TELEGRAM_POLL_INTERVAL = 2          # seconds between getUpdates calls
# ──────────────────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [Pi3] %(levelname)s: %(message)s"
)
log = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# State
# ─────────────────────────────────────────────────────────────────────────────
system_armed    = True
last_seen       = {}        # name -> last alert timestamp  (per-person cooldown)
mqtt_client_ref = None      # set in main(), used by Telegram thread

# ─────────────────────────────────────────────────────────────────────────────
# [MITTEL] SQLite helpers
# ─────────────────────────────────────────────────────────────────────────────
def init_db():
    os.makedirs(SNAPSHOT_DIR, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS detections (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp   TEXT    NOT NULL,
            camera_id   INTEGER,
            names       TEXT,           -- comma-separated list of names
            face_count  INTEGER,
            snapshot    TEXT            -- file path for unknown snapshots
        )
    """)
    conn.commit()
    conn.close()
    log.info("SQLite DB ready: %s", DB_PATH)

def log_detection(timestamp, camera_id, names, face_count, snapshot_path=None):
    ts_str = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(timestamp))
    names_str = ", ".join(names) if names else "Unknown"
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        "INSERT INTO detections (timestamp, camera_id, names, face_count, snapshot) VALUES (?,?,?,?,?)",
        (ts_str, camera_id, names_str, face_count, snapshot_path)
    )
    conn.commit()
    conn.close()

def save_snapshot(image_bytes, timestamp):
    """Save unknown face snapshot to disk, return file path."""
    fname = time.strftime("unknown_%Y%m%d_%H%M%S.jpg", time.localtime(timestamp))
    fpath = os.path.join(SNAPSHOT_DIR, fname)
    with open(fpath, "wb") as f:
        f.write(image_bytes)
    return fpath

# ─────────────────────────────────────────────────────────────────────────────
# Telegram helpers
# ─────────────────────────────────────────────────────────────────────────────
def tg_url(method):
    return f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/{method}"

def send_message(text, chat_id=None):
    cid = chat_id or TELEGRAM_CHAT_ID
    try:
        requests.post(tg_url("sendMessage"), json={"chat_id": cid, "text": text}, timeout=10)
    except Exception as e:
        log.warning("Telegram sendMessage failed: %s", e)

def send_photo(image_bytes, caption, chat_id=None):
    cid = chat_id or TELEGRAM_CHAT_ID
    try:
        requests.post(
            tg_url("sendPhoto"),
            data={"chat_id": cid, "caption": caption},
            files={"photo": ("snapshot.jpg", image_bytes, "image/jpeg")},
            timeout=15
        )
    except Exception as e:
        log.warning("Telegram sendPhoto failed: %s", e)

# ─────────────────────────────────────────────────────────────────────────────
# [ANSPRUCHSVOLL] Telegram command polling thread
# ─────────────────────────────────────────────────────────────────────────────
def telegram_polling_thread():
    """Runs in background; listens for /arm /disarm /status commands."""
    global system_armed
    offset = None
    log.info("Telegram polling started.")

    while True:
        try:
            params = {"timeout": 10, "allowed_updates": ["message"]}
            if offset:
                params["offset"] = offset

            r = requests.get(tg_url("getUpdates"), params=params, timeout=15)
            updates = r.json().get("result", [])

            for update in updates:
                offset = update["update_id"] + 1
                msg = update.get("message", {})
                text = msg.get("text", "").strip().lower()
                chat_id = str(msg.get("chat", {}).get("id", ""))

                # Security: only accept commands from your own chat
                if chat_id != str(TELEGRAM_CHAT_ID):
                    continue

                if text == "/arm":
                    system_armed = True
                    # Tell the Pi Zero too
                    if mqtt_client_ref:
                        mqtt_client_ref.publish(
                            MQTT_CONTROL_TOPIC,
                            json.dumps({"command": "arm"}),
                            qos=1
                        )
                    send_message("✅ System ARMED. Monitoring active.", chat_id)
                    log.info("System armed via Telegram.")

                elif text == "/disarm":
                    system_armed = False
                    if mqtt_client_ref:
                        mqtt_client_ref.publish(
                            MQTT_CONTROL_TOPIC,
                            json.dumps({"command": "disarm"}),
                            qos=1
                        )
                    send_message("🔓 System DISARMED. Alerts paused.", chat_id)
                    log.info("System disarmed via Telegram.")

                elif text == "/status":
                    state = "🔒 ARMED" if system_armed else "🔓 DISARMED"
                    # Pull last 5 detections from DB
                    conn = sqlite3.connect(DB_PATH)
                    rows = conn.execute(
                        "SELECT timestamp, names, face_count FROM detections ORDER BY id DESC LIMIT 5"
                    ).fetchall()
                    conn.close()

                    lines = [f"Status: {state}", "", "Last 5 detections:"]
                    if rows:
                        for ts, names, count in rows:
                            lines.append(f"  {ts} | {names} ({count} face(s))")
                    else:
                        lines.append("  No detections yet.")

                    send_message("\n".join(lines), chat_id)

                elif text == "/help":
                    send_message(
                        "Available commands:\n"
                        "/arm      – activate monitoring\n"
                        "/disarm   – pause monitoring\n"
                        "/status   – system state + last 5 detections\n"
                        "/help     – this message",
                        chat_id
                    )

        except Exception as e:
            log.warning("Telegram polling error: %s", e)

        time.sleep(TELEGRAM_POLL_INTERVAL)

# ─────────────────────────────────────────────────────────────────────────────
# Face encoding
# ─────────────────────────────────────────────────────────────────────────────
def load_known_faces():
    if os.path.exists(ENCODINGS_FILE):
        with open(ENCODINGS_FILE, "rb") as f:
            data = pickle.load(f)
        log.info("Loaded %d encodings from cache.", len(data["names"]))
        return data["encodings"], data["names"]

    encodings, names = [], []
    for fname in os.listdir(KNOWN_FACES_DIR):
        if not fname.lower().endswith((".jpg", ".jpeg", ".png")):
            continue
        path = os.path.join(KNOWN_FACES_DIR, fname)
        img  = face_recognition.load_image_file(path)
        encs = face_recognition.face_encodings(img)
        if encs:
            encodings.append(encs[0])
            names.append(os.path.splitext(fname)[0])
            log.info("Encoded: %s", fname)
        else:
            log.warning("No face found in %s, skipping.", fname)

    with open(ENCODINGS_FILE, "wb") as f:
        pickle.dump({"encodings": encodings, "names": names}, f)
    log.info("Saved %d encodings to cache.", len(names))
    return encodings, names

# ─────────────────────────────────────────────────────────────────────────────
# [EINFACH] Per-person cooldown check
# ─────────────────────────────────────────────────────────────────────────────
def should_alert(name):
    """Returns True if enough time has passed since the last alert for this name."""
    cooldown = COOLDOWN_UNKNOWN if name == "Unknown" else COOLDOWN_PER_PERSON
    last = last_seen.get(name, 0)
    return (time.time() - last) >= cooldown

def mark_alerted(name):
    last_seen[name] = time.time()

# ─────────────────────────────────────────────────────────────────────────────
# MQTT callbacks
# ─────────────────────────────────────────────────────────────────────────────
known_encodings = []
known_names     = []

def on_connect(client, userdata, flags, rc):
    if rc == 0:
        client.subscribe(MQTT_TOPIC)
        log.info("Subscribed to %s", MQTT_TOPIC)
    else:
        log.error("MQTT connection failed, rc=%d", rc)

def on_message(client, userdata, msg):
    if not system_armed:
        log.info("System disarmed – ignoring detection.")
        return

    try:
        payload    = json.loads(msg.payload.decode())
        timestamp  = payload["timestamp"]
        camera_id  = payload.get("camera_id", 0)
        face_count = payload.get("face_count", 1)
        image_b64  = payload["image_b64"]
    except (KeyError, json.JSONDecodeError) as e:
        log.warning("Bad payload: %s", e)
        return

    image_bytes = base64.b64decode(image_b64)
    image       = face_recognition.load_image_file(io.BytesIO(image_bytes))
    locations   = face_recognition.face_locations(image)
    encodings   = face_recognition.face_encodings(image, locations)

    detected_names = []
    for enc in encodings:
        matches = face_recognition.compare_faces(known_encodings, enc, tolerance=TOLERANCE)
        dists   = face_recognition.face_distance(known_encodings, enc)
        name    = "Unknown"
        if any(matches) and len(dists) > 0:
            best = int(np.argmin(dists))
            if matches[best]:
                name = known_names[best]
        detected_names.append(name)

    if not detected_names:
        detected_names = ["Unknown"]

    # ── [MITTEL] SQLite log ───────────────────────────────────────────────────
    snapshot_path = None
    if "Unknown" in detected_names:
        snapshot_path = save_snapshot(image_bytes, timestamp)

    log_detection(timestamp, camera_id, detected_names, face_count, snapshot_path)
    log.info("Logged detection: %s", detected_names)

    # ── [EINFACH] Per-person cooldown + send alerts ───────────────────────────
    ts_str = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(timestamp))

    for name in set(detected_names):          # deduplicate per frame
        if not should_alert(name):
            log.info("Cooldown active for '%s', skipping alert.", name)
            continue

        mark_alerted(name)

        caption = (
            f"🔔 Security Alert\n"
            f"{ts_str}\n"
            f"Camera: {camera_id}\n"
            f"Detected: {name}"
        )
        send_photo(image_bytes, caption)
        log.info("Telegram alert sent for: %s", name)

# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────
def main():
    global known_encodings, known_names, mqtt_client_ref

    init_db()

    os.makedirs(KNOWN_FACES_DIR, exist_ok=True)
    known_encodings, known_names = load_known_faces()

    # Start Telegram polling in background thread
    t = threading.Thread(target=telegram_polling_thread, daemon=True)
    t.start()

    client = mqtt.Client(client_id="pi3_face_recognizer")
    client.on_connect = on_connect
    client.on_message = on_message
    client.connect(MQTT_BROKER, MQTT_PORT, keepalive=60)

    mqtt_client_ref = client   # share with Telegram thread for arm/disarm publish

    log.info("Face recognizer running. Waiting for events...")
    send_message(
        "🟢 Face Security System started.\n"
        "Commands: /arm /disarm /status /help"
    )

    try:
        client.loop_forever()
    except KeyboardInterrupt:
        log.info("Stopped by user.")
        send_message("🔴 Face Security System stopped.")

if __name__ == "__main__":
    main()
