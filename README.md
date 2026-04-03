# 🔒 Raspberry Pi Face Security System

A two-device home security system using a **Raspberry Pi Zero 2W** for camera capture and a **Raspberry Pi 3** for face recognition, connected via **MQTT**. When a face is detected, a snapshot is sent to your **Telegram** chat instantly.

---

## 📸 How It Works

```
[Camera]           [MQTT Broker]        [Face Recognition]     [Telegram]
Pi Zero 2W   --->  Mosquitto on Pi 3  --->  Pi 3               --->  Your Phone
OpenCV             (192.168.1.100)         face_recognition
Haar Cascade                               library
```

1. Pi Zero 2W captures frames and detects faces using OpenCV Haar Cascade
2. On detection, a JPEG snapshot is published to an MQTT topic
3. Pi 3 receives the message, identifies known faces using `face_recognition`
4. A Telegram notification with the snapshot is sent to your phone

---

## 🗂 Project Structure

```
rpi-face-security/
├── pi_zero/
│   ├── camera_detector.py        # Runs on Pi Zero 2W
│   ├── requirements.txt
│   └── camera_detector.service   # systemd autostart
├── pi_3/
│   ├── face_recognizer.py        # Runs on Pi 3
│   ├── requirements.txt
│   ├── face_recognizer.service   # systemd autostart
│   └── known_faces/              # Put face images here (name.jpg)
└── README.md
```

---

## 🛒 Requirements

### Hardware
- Raspberry Pi Zero 2W + Camera Module (v1 or v2)
- Raspberry Pi 3 (Model B or B+)
- Both devices on the same local network

### Software
- Raspberry Pi OS Lite (64-bit recommended for Pi 3)
- Python 3.9+
- Mosquitto MQTT broker (on Pi 3)
- Telegram Bot (free, via @BotFather)

---

## ⚙️ Setup

### 1. Install Mosquitto on Pi 3

```bash
sudo apt update
sudo apt install -y mosquitto mosquitto-clients
sudo systemctl enable mosquitto
sudo systemctl start mosquitto
```

### 2. Setup Pi Zero 2W

```bash
# Enable camera
sudo raspi-config  # → Interface Options → Camera → Enable

# Install dependencies
pip install -r pi_zero/requirements.txt

# Edit config at top of script
nano pi_zero/camera_detector.py
# Set MQTT_BROKER to your Pi 3's IP address
```

### 3. Setup Pi 3

```bash
# Install dlib dependency (needed for face_recognition)
sudo apt install -y cmake build-essential libopenblas-dev liblapack-dev

pip install -r pi_3/requirements.txt
```

### 4. Add Known Faces

Put a photo of each person you want to recognize in `pi_3/known_faces/`:

```
known_faces/
├── Steff.jpg
├── Mom.jpg
└── Max.jpg
```

The **filename** (without `.jpg`) will be used as the person's name in Telegram notifications.
Delete `encodings.pkl` after adding new photos to force re-encoding.

### 5. Setup Telegram Bot

1. Open Telegram → search **@BotFather** → `/newbot`
2. Copy your **Bot Token**
3. Send a message to your new bot, then visit:
   ```
   https://api.telegram.org/bot<YOUR_TOKEN>/getUpdates
   ```
   Find your **Chat ID** in the response.

4. Edit `pi_3/face_recognizer.py`:
   ```python
   TELEGRAM_BOT_TOKEN = "1234567890:ABCdef..."
   TELEGRAM_CHAT_ID   = "987654321"
   ```

---

## 🚀 Running

### Manual

```bash
# Pi Zero 2W
python3 pi_zero/camera_detector.py

# Pi 3
python3 pi_3/face_recognizer.py
```

### Autostart with systemd

```bash
# Pi Zero 2W
sudo cp pi_zero/camera_detector.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable camera_detector
sudo systemctl start camera_detector

# Pi 3
sudo cp pi_3/face_recognizer.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable face_recognizer
sudo systemctl start face_recognizer
```

Check status:
```bash
sudo systemctl status camera_detector
sudo systemctl status face_recognizer
```

---

## 🔧 Configuration

| Variable | File | Description |
|---|---|---|
| `MQTT_BROKER` | `camera_detector.py` | Pi 3 IP address |
| `DETECTION_INTERVAL` | `camera_detector.py` | Seconds between scans (default: 1.0) |
| `MIN_FACE_SIZE` | `camera_detector.py` | Minimum face size in pixels |
| `TOLERANCE` | `face_recognizer.py` | Face matching strictness (0.4–0.6) |
| `COOLDOWN_SECONDS` | `face_recognizer.py` | Min time between Telegram alerts |

---

## 📱 Example Telegram Notification

```
🔔 Security Alert
2025-03-15 22:47:03
Detected: Unknown

[snapshot image]
```

```
🔔 Security Alert
2025-03-15 22:48:10
Detected: Steff, Mom

[snapshot image]
```

---

## 📦 Dependencies

| Package | Used For |
|---|---|
| `opencv-python-headless` | Camera capture + Haar Cascade detection |
| `face_recognition` | Deep learning face ID (dlib-based) |
| `paho-mqtt` | MQTT communication between devices |
| `requests` | Telegram Bot API calls |

---

## 📄 License

MIT License – feel free to use and modify.

---

## 💡 Ideas for Future Improvements

- [ ] Web dashboard (Flask) showing live snapshots
- [ ] Unknown face logging to SQLite database  
- [ ] Motion detection pre-filter to reduce false triggers
- [ ] Multiple camera support
- [ ] Upgrade Haar Cascade to YOLOv8 for better accuracy
