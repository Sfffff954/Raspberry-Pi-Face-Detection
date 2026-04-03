# 🌍 Remote Access with Tailscale

Access your Raspberry Pi Face Security System from anywhere in the world — no port forwarding, no dynamic DNS, no router setup.

---

## What is Tailscale?

Tailscale is a free VPN tool that connects your devices into a private network, no matter where they are. Every device gets a stable private IP (`100.x.x.x`) that works from any network.

| | Without Tailscale | With Tailscale |
|---|---|---|
| Access | Home network only | Anywhere in the world |
| Setup | Port forwarding + dynamic DNS | Just install & login |
| IP | Changes constantly | Always `100.x.x.x` |
| Security | Exposed ports | End-to-end encrypted |

> **Free** for personal use — up to 3 users and 100 devices.

---

## Installation

### 1. Create a Tailscale account

Go to [tailscale.com](https://tailscale.com) and sign up (Google or GitHub login works fine).

---

### 2. Install on Pi Zero 2W

SSH into the Pi Zero 2W and run:

```bash
curl -fsSL https://tailscale.com/install.sh | sh
sudo tailscale up
```

After the second command, a link appears — open it in your browser and authorize the device.

---

### 3. Install on Pi 3

Same steps on the Pi 3:

```bash
curl -fsSL https://tailscale.com/install.sh | sh
sudo tailscale up
```

Authorize this device in the browser as well.

---

### 4. Install on your Phone / Laptop

- **Android / iOS** — install the Tailscale app from the App Store
- **Windows / Mac / Linux** — download at [tailscale.com/download](https://tailscale.com/download)
- Log in with the same account on all devices

---

## Find your Tailscale IPs

After installation, each device has a stable `100.x.x.x` IP. Find it with:

```bash
tailscale ip -4
```

Or go to [tailscale.com/admin](https://tailscale.com/admin) to see all devices and their IPs.

Example setup:

| Device | Example Tailscale IP | Used for |
|---|---|---|
| Pi Zero 2W | `100.64.0.1` | Camera, publishes MQTT |
| Pi 3 | `100.64.0.2` | MQTT broker, face recognition |
| Phone / Laptop | `100.64.0.3` | SSH, Telegram, monitoring |

---

## Update the Configuration

### camera_detector.py (runs on Pi Zero 2W)

Replace the local IP with the Tailscale IP of your Pi 3:

```python
# Before (home network only):
MQTT_BROKER = "192.168.1.100"

# After (works from anywhere):
MQTT_BROKER = "100.64.0.2"   # Tailscale IP of your Pi 3
```

### Mosquitto on Pi 3

Make sure Mosquitto accepts connections on all interfaces:

```bash
sudo nano /etc/mosquitto/mosquitto.conf
```

Add or confirm these lines:

```
listener 1883
allow_anonymous true
```

Then restart:

```bash
sudo systemctl restart mosquitto
```

> **Note:** For better security, consider adding username/password authentication. See [mosquitto.org/documentation](https://mosquitto.org/documentation/authentication-methods/).

---

## SSH from Anywhere

With Tailscale you can SSH into your Pis from anywhere — no port forwarding needed:

```bash
# Connect to Pi Zero 2W
ssh pi@100.64.0.1

# Connect to Pi 3
ssh pi@100.64.0.2
```

This works on mobile data, abroad, on any Wi-Fi — as long as Tailscale is running on both devices.

---

## Enable Autostart

Make sure Tailscale starts automatically after a reboot on both Pis:

```bash
sudo systemctl enable tailscaled
sudo systemctl start tailscaled
```

Check the status at any time:

```bash
sudo tailscale status
```

---

## Quick Reference

| Task | Command |
|---|---|
| Install Tailscale | `curl -fsSL https://tailscale.com/install.sh \| sh` |
| Connect & login | `sudo tailscale up` |
| Show your IP | `tailscale ip -4` |
| Show all devices | `tailscale status` |
| Disconnect | `sudo tailscale down` |
| SSH into Pi | `ssh pi@100.x.x.x` |
| Enable autostart | `sudo systemctl enable tailscaled` |

---

## How it fits into the system

```
[Pi Zero 2W]              [Tailscale Network]          [Pi 3]
camera_detector.py  --->  100.64.0.1 <-> 100.64.0.2  --->  face_recognizer.py
MQTT publish                                                 MQTT subscribe
                                                             Telegram alerts
                                  ↑
                          [Your Phone / Laptop]
                          SSH, Telegram, /status
                          from anywhere in the world
```

---

*Tailscale is free for personal use — [tailscale.com](https://tailscale.com)*
