#!/usr/bin/env python3
"""
face_recognizer.py - Runs on Raspberry Pi 3
Features:
  - face_recognition for known face ID
  - SQLite logging of all detections (known + unknown)
  - Telegram notifications with snapshots
  - Flask web dashboard (port 5000)
  - Multi-camera aware (reads camera_id from MQTT payload)
  - Python 3+ compatible
"""

import face_recognition
import paho.mqtt.client as mqtt
import requests
import base64
import json
import sqlite3
import numpy as np
import logging
import pickle
import time
import threading
import os
import sys
from datetime import datetime
from pathlib import Path
from flask import Flask, render_template, jsonify, send_file
import io
import cv2

# ── Config ────────────────────────────────────────────────────────────────────
MQTT_BROKER        = "localhost"
MQTT_PORT          = 1883
MQTT_TOPIC         = "home/security/face"

TELEGRAM_BOT_TOKEN = "YOUR_BOT_TOKEN_HERE"
TELEGRAM_CHAT_ID   = "YOUR_CHAT_ID_HERE"

KNOWN_FACES_DIR    = Path("known_faces")
ENCODINGS_CACHE    = Path("encodings.pkl")
DB_PATH            = Path("detections.db")

TOLERANCE          = 0.55
COOLDOWN_SECONDS   = 30
DASHBOARD_PORT     = 5000
# ──────────────────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [Pi3] %(levelname)s: %(message)s"
)
log = logging.getLogger(__name__)

last_notification_time = 0
latest_snapshot        = {}   # camera_id -> jpeg bytes
db_lock                = threading.Lock()


# ── Database ──────────────────────────────────────────────────────────────────

def init_db():
    with sqlite3.connect(str(DB_PATH)) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS detections (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp   TEXT    NOT NULL,
                camera_id   INTEGER DEFAULT 0,
                face_count  INTEGER DEFAULT 0,
                names       TEXT    DEFAULT '',
                image_b64   TEXT    DEFAULT ''
            )
        """)
        conn.commit()
    log.info("Database ready at %s", DB_PATH)


def log_detection(timestamp, camera_id, face_count, names, image_b64):
    ts = datetime.fromtimestamp(timestamp).strftime("%Y-%m-%d %H:%M:%S")
    names_str = ", ".join(names) if names else "Unknown"
    with db_lock:
        with sqlite3.connect(str(DB_PATH)) as conn:
            conn.execute(
                "INSERT INTO detections (timestamp, camera_id, face_count, names, image_b64) VALUES (?,?,?,?,?)",
                (ts, camera_id, face_count, names_str, image_b64)
            )
            conn.commit()


def get_recent_detections(limit=50):
    with db_lock:
        with sqlite3.connect(str(DB_PATH)) as conn:
            cur = conn.execute(
                "SELECT id, timestamp, camera_id, face_count, names FROM detections ORDER BY id DESC LIMIT ?",
                (limit,)
            )
            rows = cur.fetchall()
    return [
        {"id": r[0], "timestamp": r[1], "camera_id": r[2], "face_count": r[3], "names": r[4]}
        for r in rows
    ]


# ── Telegram ──────────────────────────────────────────────────────────────────

def send_telegram_message(text):
    url = "https://api.telegram.org/bot{}/sendMessage".format(TELEGRAM_BOT_TOKEN)
    try:
        requests.post(url, data={"chat_id": TELEGRAM_CHAT_ID, "text": text}, timeout=10)
    except Exception as e:
        log.error("Telegram message error: %s", e)


def send_telegram_photo(image_bytes, caption):
    url = "https://api.telegram.org/bot{}/sendPhoto".format(TELEGRAM_BOT_TOKEN)
    try:
        resp = requests.post(
            url,
            data={"chat_id": TELEGRAM_CHAT_ID, "caption": caption},
            files={"photo": ("snapshot.jpg", image_bytes, "image/jpeg")},
            timeout=15
        )
        return resp.ok
    except Exception as e:
        log.error("Telegram photo error: %s", e)
        return False


# ── Face encodings ────────────────────────────────────────────────────────────

def load_known_faces():
    if ENCODINGS_CACHE.exists():
        log.info("Loading encodings from cache...")
        with open(str(ENCODINGS_CACHE), "rb") as f:
            return pickle.load(f)

    known_encodings = []
    known_names     = []

    if not KNOWN_FACES_DIR.exists():
        KNOWN_FACES_DIR.mkdir()
        log.warning("known_faces/ created. Add photos and restart.")
        return known_encodings, known_names

    for img_path in sorted(KNOWN_FACES_DIR.iterdir()):
        if img_path.suffix.lower() not in (".jpg", ".jpeg", ".png"):
            continue
        name  = img_path.stem
        image = face_recognition.load_image_file(str(img_path))
        encs  = face_recognition.face_encodings(image)
        if encs:
            known_encodings.append(encs[0])
            known_names.append(name)
            log.info("Loaded: %s", name)
        else:
            log.warning("No face found in %s", img_path.name)

    with open(str(ENCODINGS_CACHE), "wb") as f:
        pickle.dump((known_encodings, known_names), f)

    return known_encodings, known_names


def identify_faces(frame_rgb, known_encodings, known_names):
    locations = face_recognition.face_locations(frame_rgb)
    encodings = face_recognition.face_encodings(frame_rgb, locations)
    results   = []
    for enc in encodings:
        name = "Unknown"
        if known_encodings:
            matches   = face_recognition.compare_faces(known_encodings, enc, tolerance=TOLERANCE)
            distances = face_recognition.face_distance(known_encodings, enc)
            if True in matches:
                best = int(np.argmin(distances))
                name = known_names[best]
        results.append(name)
    return results


# ── Flask dashboard ───────────────────────────────────────────────────────────

app = Flask(__name__)


@app.route("/")
def dashboard():
    return render_template("dashboard.html")


@app.route("/api/detections")
def api_detections():
    return jsonify(get_recent_detections())


@app.route("/api/snapshot/<int:camera_id>")
def api_snapshot(camera_id):
    img = latest_snapshot.get(camera_id)
    if img is None:
        return "No snapshot yet", 404
    return send_file(io.BytesIO(img), mimetype="image/jpeg")


def run_flask():
    app.run(host="0.0.0.0", port=DASHBOARD_PORT, debug=False, use_reloader=False)


# ── MQTT handler ──────────────────────────────────────────────────────────────

def make_on_message(known_encodings, known_names):
    def on_message(client, userdata, msg):
        global last_notification_time

        try:
            payload    = json.loads(msg.payload.decode())
            face_count = payload.get("face_count", 0)
            image_b64  = payload.get("image_b64", "")
            ts         = payload.get("timestamp", time.time())
            camera_id  = payload.get("camera_id", 0)
        except Exception as e:
            log.error("Bad MQTT payload: %s", e)
            return

        if not image_b64:
            return

        image_bytes = base64.b64decode(image_b64)
        np_arr      = np.frombuffer(image_bytes, dtype=np.uint8)
        frame_bgr   = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)
        frame_rgb   = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)

        names = identify_faces(frame_rgb, known_encodings, known_names)
        log.info("Camera %d | Faces: %s", camera_id, names)

        # Save latest snapshot for dashboard
        latest_snapshot[camera_id] = image_bytes

        # Log to SQLite
        log_detection(ts, camera_id, face_count, names, image_b64)

        # Telegram notification (with cooldown)
        now = time.time()
        if now - last_notification_time >= COOLDOWN_SECONDS:
            last_notification_time = now
            ts_str    = datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")
            name_list = ", ".join(names) if names else "Unknown"
            caption   = "🔔 Security Alert\n{}\nCamera: {}\nDetected: {}".format(
                ts_str, camera_id, name_list
            )
            send_telegram_photo(image_bytes, caption)

    return on_message


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    init_db()

    log.info("Loading known faces...")
    known_encodings, known_names = load_known_faces()
    log.info("Loaded %d known person(s): %s", len(known_names), known_names)

    # Start Flask in background thread
    flask_thread = threading.Thread(target=run_flask, daemon=True)
    flask_thread.start()
    log.info("Dashboard running at http://localhost:%d", DASHBOARD_PORT)

    # Start MQTT
    client = mqtt.Client(client_id="pi3_face_recognizer")
    client.on_message = make_on_message(known_encodings, known_names)
    client.connect(MQTT_BROKER, MQTT_PORT, keepalive=60)
    client.subscribe(MQTT_TOPIC, qos=1)
    log.info("Subscribed to MQTT topic: %s", MQTT_TOPIC)

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
