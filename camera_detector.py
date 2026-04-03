#!/usr/bin/env python3
"""
camera_detector.py - Runs on Raspberry Pi Zero 2W
Captures frames from camera, detects faces using OpenCV Haar Cascade,
and publishes events via MQTT to the Pi 3.
"""

import cv2
import paho.mqtt.client as mqtt
import base64
import json
import time
import logging
import os

# ── Config ────────────────────────────────────────────────────────────────────
MQTT_BROKER = "192.168.1.100"   # IP of your Raspberry Pi 3
MQTT_PORT   = 1883
MQTT_TOPIC  = "home/security/face"

CAMERA_INDEX      = 0
FRAME_WIDTH       = 640
FRAME_HEIGHT      = 480
DETECTION_INTERVAL = 1.0        # seconds between detections
MIN_FACE_SIZE     = (60, 60)    # ignore tiny false positives
SCALE_FACTOR      = 1.1
MIN_NEIGHBORS     = 5

CASCADE_PATH = cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
# ──────────────────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [PiZero] %(levelname)s: %(message)s"
)
log = logging.getLogger(__name__)


def encode_frame(frame):
    """JPEG-encode frame and return as base64 string."""
    _, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 60])
    return base64.b64encode(buf).decode("utf-8")


def on_connect(client, userdata, flags, rc):
    if rc == 0:
        log.info("Connected to MQTT broker.")
    else:
        log.error(f"MQTT connection failed, rc={rc}")


def main():
    # Load cascade
    face_cascade = cv2.CascadeClassifier(CASCADE_PATH)
    if face_cascade.empty():
        log.error("Could not load Haar cascade. Check OpenCV installation.")
        return

    # Setup MQTT
    client = mqtt.Client(client_id="pi_zero_camera")
    client.on_connect = on_connect
    client.connect(MQTT_BROKER, MQTT_PORT, keepalive=60)
    client.loop_start()

    # Setup camera
    cap = cv2.VideoCapture(CAMERA_INDEX)
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, FRAME_WIDTH)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, FRAME_HEIGHT)

    if not cap.isOpened():
        log.error("Cannot open camera.")
        return

    log.info("Camera ready. Starting detection loop...")
    last_detection = 0

    try:
        while True:
            ret, frame = cap.read()
            if not ret:
                log.warning("Failed to grab frame.")
                time.sleep(0.5)
                continue

            now = time.time()
            if now - last_detection < DETECTION_INTERVAL:
                continue
            last_detection = now

            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            faces = face_cascade.detectMultiScale(
                gray,
                scaleFactor=SCALE_FACTOR,
                minNeighbors=MIN_NEIGHBORS,
                minSize=MIN_FACE_SIZE
            )

            if len(faces) > 0:
                log.info(f"Detected {len(faces)} face(s).")

                # Draw rectangles on frame
                for (x, y, w, h) in faces:
                    cv2.rectangle(frame, (x, y), (x + w, y + h), (0, 255, 0), 2)

                payload = {
                    "timestamp": now,
                    "face_count": len(faces),
                    "image_b64": encode_frame(frame)
                }
                client.publish(MQTT_TOPIC, json.dumps(payload), qos=1)
                log.info("Published face event to MQTT.")

    except KeyboardInterrupt:
        log.info("Stopped by user.")
    finally:
        cap.release()
        client.loop_stop()
        client.disconnect()


if __name__ == "__main__":
    main()
