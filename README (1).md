# 🔒 Raspberry Pi Face Security System

A two-device home security system using a **Raspberry Pi Zero 2W** for camera capture and a **Raspberry Pi 3** for face recognition, connected via **MQTT**.

**Features:**
- 🎥 Multiple camera support
- 🏃 Motion detection pre-filter (saves CPU)
- 🧠 Face recognition for known persons
- 🗄️ SQLite database logging of all detections
- 📱 Telegram notifications with snapshots
- 🌐 Live web dashboard (Flask)
- 🐍 Python 3+ compatible

---

## 📸 How It Works

```
[Camera(s)]          [MQTT Broker]       [Face Recognition]      [Telegram]
Pi Zero 2W   ──────► Mosquitto on Pi 3 ──► Pi 3               ──► Your Phone
Motion detect        (192.168.1.100)       face_recognition
Haar Cascade                               SQLite logging
Multiple cams                              Flask dashboard
```

1. Pi Zero detects motion → runs face detection → publishes JPEG + metadata to MQTT
2. Pi 3 receives event → identifies known faces → logs to SQLite
3. Telegram alert sent (with cooldown to avoid spam)
4. Web dashboard at `http://<Pi3-IP>:5000` shows live snapshots + history

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
│   ├── templates/
│   │   └── dashboard.html        # Web dashboard
│   └── known_faces/              # Add face photos here
└── README.md
```

---

## 🛒 Requirements

### Hardware
- Raspberry Pi Zero 2W + Camera Module (v1 or v2)
- Raspberry Pi 3 (Model B or B+)
- Both on the same local network

### Software
- Raspberry Pi OS Lite (64-bit recommended for Pi 3)
- Python 3.6+
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
pip3 install -r pi_zero/requirements.txt

# Edit config
nano pi_zero/camera_detector.py
# Set MQTT_BROKER to your Pi 3 IP
# Set CAMERA_INDEXES = [0] for one camera, [0, 1] for two
```

### 3. Setup Pi 3

```bash
# Install dlib dependency (required for face_recognition)
sudo apt install -y cmake build-essential libopenblas-dev liblapack-dev

pip3 install -r pi_3/requirements.txt
```

### 4. Add Known Faces

Put one clear photo per person in `pi_3/known_faces/`:

```
known_faces/
├── Steff.jpg
├── Mom.jpg
└── Max.jpg
```

The **filename** (without extension) is used as the display name.
After adding photos, delete `encodings.pkl` to force re-encoding.

### 5. Setup Telegram Bot

1. Open Telegram → search **@BotFather** → `/newbot`
2. Copy the **Bot Token**
3. Send a message to your bot, then open:
   ```
   https://api.telegram.org/bot<YOUR_TOKEN>/getUpdates
   ```
   Find your **Chat ID** in the JSON response.

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

Then open the dashboard: `http://<Pi3-IP>:5000`

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

Check logs:
```bash
sudo journalctl -u camera_detector -f
sudo journalctl -u face_recognizer -f
```

---

## 🔧 Configuration

### Pi Zero (`camera_detector.py`)

| Variable | Default | Description |
|---|---|---|
| `MQTT_BROKER` | `192.168.1.100` | Pi 3 IP address |
| `CAMERA_INDEXES` | `[0]` | Camera indexes, e.g. `[0, 1]` for two |
| `DETECTION_INTERVAL` | `1.0` | Seconds between face scans per camera |
| `MOTION_ENABLED` | `True` | Enable motion pre-filter |
| `MOTION_THRESHOLD` | `25` | Pixel diff sensitivity |
| `MOTION_MIN_AREA` | `1500` | Min contour area for motion |
| `MIN_FACE_SIZE` | `(60, 60)` | Minimum face size in pixels |

### Pi 3 (`face_recognizer.py`)

| Variable | Default | Description |
|---|---|---|
| `TOLERANCE` | `0.55` | Face match strictness (0.4–0.6) |
| `COOLDOWN_SECONDS` | `30` | Min time between Telegram alerts |
| `DASHBOARD_PORT` | `5000` | Flask web dashboard port |

---

## 🌐 Web Dashboard

Visit `http://<Pi3-IP>:5000` in your browser.

- **Live snapshots** for each camera, auto-refreshing every 3 seconds
- **Detection history** table with timestamp, camera ID, face count, and names
- Known faces shown in **green**, Unknown in **red**

---

## 🗄️ Database

All detections are stored in `pi_3/detections.db` (SQLite).

```bash
# Query detections manually
sqlite3 pi_3/detections.db "SELECT timestamp, camera_id, names FROM detections ORDER BY id DESC LIMIT 20;"
```

Schema:
```sql
CREATE TABLE detections (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp  TEXT,
    camera_id  INTEGER,
    face_count INTEGER,
    names      TEXT,
    image_b64  TEXT
);
```

---

## 📱 Example Telegram Notification

```
🔔 Security Alert
2025-03-15 22:47:03
Camera: 0
Detected: Unknown
```

```
🔔 Security Alert
2025-03-15 22:48:10
Camera: 1
Detected: Steff, Mom
```

---

## 📦 Dependencies

| Package | Used For |
|---|---|
| `opencv-python-headless` | Camera capture, motion detection, Haar Cascade |
| `face_recognition` | Deep learning face identification (dlib) |
| `paho-mqtt` | MQTT communication between devices |
| `requests` | Telegram Bot API |
| `flask` | Web dashboard |
| `numpy` | Frame processing |

---

## 📄 License

MIT License – free to use and modify.

---

## 💡 Future Ideas

- [ ] YOLOv8 face detection for higher accuracy
- [ ] Email notifications as fallback
- [ ] Snapshot gallery with download button in dashboard
- [ ] Night mode / IR camera support
- [ ] Alert sound via Pi 3 audio output
