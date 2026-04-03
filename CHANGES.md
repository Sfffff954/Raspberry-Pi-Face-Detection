# 🔒 Raspberry Pi Face Security System — Extended Edition

Drei neue Features wurden hinzugefügt:

---

## ✅ Was ist neu?

### [EINFACH] Per-Person Cooldown
Jede erkannte Person hat ihren eigenen Cooldown-Timer.
- Bekannte Personen: Standard 30 Sekunden
- Unbekannte: 20 Sekunden (kürzerer Cooldown = schnellere Reaktion bei Fremden)

Konfigurierbar in `face_recognizer.py`:
```python
COOLDOWN_PER_PERSON = 30   # Sekunden pro Name
COOLDOWN_UNKNOWN    = 20   # Sekunden für "Unknown"
```

---

### [MITTEL] SQLite Datenbank-Logging
Jede Erkennung wird in `detections.db` gespeichert.
- Timestamp, Kamera-ID, erkannte Namen, Anzahl Gesichter
- Unbekannte Gesichter werden automatisch als Snapshot in `snapshots/` gespeichert

Schema:
```sql
detections (id, timestamp, camera_id, names, face_count, snapshot)
```

---

### [ANSPRUCHSVOLL] Telegram Bot-Befehle
Steuere das System direkt aus Telegram heraus:

| Befehl     | Funktion                                      |
|------------|-----------------------------------------------|
| `/arm`     | System aktivieren (auch Pi Zero wird informiert) |
| `/disarm`  | Alerts pausieren                              |
| `/status`  | Aktueller Status + letzte 5 Erkennungen       |
| `/help`    | Alle Befehle anzeigen                         |

Arm/Disarm wird per MQTT auch an den Pi Zero geschickt, der dann keine Frames mehr verarbeitet.

---

## ⚙️ Setup (neue Dependencies)

Keine neuen Pakete nötig — `sqlite3` und `threading` sind Python-Standard.

---

## 📁 Neue Dateien/Ordner

```
snapshots/          ← Automatisch erstellt, speichert unbekannte Gesichter
detections.db       ← SQLite Datenbank (automatisch erstellt)
```

---

## 🔧 Konfiguration (face_recognizer.py)

| Variable             | Beschreibung                          |
|----------------------|---------------------------------------|
| `COOLDOWN_PER_PERSON`| Sekunden zwischen Alerts pro Person   |
| `COOLDOWN_UNKNOWN`   | Sekunden zwischen Alerts für Fremde   |
| `DB_PATH`            | Pfad zur SQLite Datenbank             |
| `SNAPSHOT_DIR`       | Ordner für unbekannte Snapshots       |
| `TELEGRAM_POLL_INTERVAL` | Wie oft nach Telegram-Befehlen geprüft wird |
