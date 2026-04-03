#!/usr/bin/env python3
"""
camera_detector.py - Runs on Raspberry Pi Zero 2W
Supports: multiple cameras, motion detection pre-filter, Python 3+
Publishes face events via MQTT to Pi 3.
"""

import cv2
import paho.mqtt.client as mqtt
import base64
import json
import time
import logging
import sys

# ── Config ────────────────────────────────────────────────────────────────────
MQTT_BROKER         = "192.168.1.100"   # IP of your Raspberry Pi 3
MQTT_PORT           = 1883
MQTT_TOPIC          = "home/security/face"

# Camera indexes to use (e.g. [0] for one, [0, 1] for two cameras)
CAMERA_INDEXES      = [0]

FRAME_WIDTH         = 640
FRAME_HEIGHT        = 480
DETECTION_INTERVAL  = 1.0       # seconds between face detections per camera
MIN_FACE_SIZE       = (60, 60)
SCALE_FACTOR        = 1.1
MIN_NEIGHBORS       = 5

# Motion detection settings
MOTION_ENABLED      = True
MOTION_THRESHOLD    = 25        # pixel difference threshold
MOTION_MIN_AREA     = 1500      # minimum contour area to count as motion

CASCADE_PATH = cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
# ──────────────────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [PiZero] %(levelname)s: %(message)s"
)
log = logging.getLogger(__name__)


def encode_frame(frame):
    _, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 60])
    return base64.b64encode(buf).decode("utf-8")


def detect_motion(prev_gray, curr_gray):
    """Returns True if motion detected between two grayscale frames."""
    diff = cv2.absdiff(prev_gray, curr_gray)
    _, thresh = cv2.threshold(diff, MOTION_THRESHOLD, 255, cv2.THRESH_BINARY)
    thresh = cv2.dilate(thresh, None, iterations=2)
    contours, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    for c in contours:
        if cv2.contourArea(c) >= MOTION_MIN_AREA:
            return True
    return False


def on_connect(client, userdata, flags, rc):
    if rc == 0:
        log.info("Connected to MQTT broker at %s", MQTT_BROKER)
    else:
        log.error("MQTT connection failed, rc=%d", rc)


def open_cameras(indexes):
    cameras = {}
    for idx in indexes:
        cap = cv2.VideoCapture(idx)
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, FRAME_WIDTH)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, FRAME_HEIGHT)
        if cap.isOpened():
            cameras[idx] = cap
            log.info("Camera %d opened.", idx)
        else:
            log.warning("Camera %d could not be opened, skipping.", idx)
    return cameras


def main():
    face_cascade = cv2.CascadeClassifier(CASCADE_PATH)
    if face_cascade.empty():
        log.error("Could not load Haar cascade.")
        sys.exit(1)

    client = mqtt.Client(client_id="pi_zero_camera")
    client.on_connect = on_connect
    client.connect(MQTT_BROKER, MQTT_PORT, keepalive=60)
    client.loop_start()

    cameras = open_cameras(CAMERA_INDEXES)
    if not cameras:
        log.error("No cameras available. Exiting.")
        sys.exit(1)

    last_detection = {idx: 0 for idx in cameras}
    prev_grays     = {idx: None for idx in cameras}

    log.info("Starting detection loop on %d camera(s)...", len(cameras))

    try:
        while True:
            for idx, cap in cameras.items():
                ret, frame = cap.read()
                if not ret:
                    log.warning("Camera %d: failed to grab frame.", idx)
                    continue

                now = time.time()
                gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

                # ── Motion pre-filter ──────────────────────────────────────
                if MOTION_ENABLED:
                    if prev_grays[idx] is not None:
                        if not detect_motion(prev_grays[idx], gray):
                            prev_grays[idx] = gray
                            continue  # no motion → skip face detection
                    prev_grays[idx] = gray

                # ── Rate limit ─────────────────────────────────────────────
                if now - last_detection[idx] < DETECTION_INTERVAL:
                    continue
                last_detection[idx] = now

                # ── Face detection ─────────────────────────────────────────
                faces = face_cascade.detectMultiScale(
                    gray,
                    scaleFactor=SCALE_FACTOR,
                    minNeighbors=MIN_NEIGHBORS,
                    minSize=MIN_FACE_SIZE
                )

                if len(faces) > 0:
                    log.info("Camera %d: %d face(s) detected.", idx, len(faces))
                    for (x, y, w, h) in faces:
                        cv2.rectangle(frame, (x, y), (x + w, y + h), (0, 255, 0), 2)

                    payload = {
                        "timestamp":  now,
                        "camera_id":  idx,
                        "face_count": len(faces),
                        "image_b64":  encode_frame(frame)
                    }
                    client.publish(MQTT_TOPIC, json.dumps(payload), qos=1)
                    log.info("Camera %d: published face event.", idx)

            time.sleep(0.05)

    except KeyboardInterrupt:
        log.info("Stopped by user.")
    finally:
        for cap in cameras.values():
            cap.release()
        client.loop_stop()
        client.disconnect()


if __name__ == "__main__":
    main()
