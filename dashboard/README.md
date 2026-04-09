# Pi Zero 2 W Dashboard — Setup Guide
    #Created by Claude Code.

## Files
```
dashboard/
├── app.py               # Flask backend
├── reminders.json       # Auto-created on first reminder add
├── requirements.txt
└── templates/
    ├── dashboard.html   # Kiosk display (jungle/beach theme)
    └── admin.html       # Mobile admin UI
```

---

## 1. OS & Dependencies

Flash **Raspberry Pi OS Lite 64-bit**, enable SSH + Wi-Fi in the imager.

```bash
sudo apt update && sudo apt upgrade -y
sudo apt install -y python3-pip chromium-browser unclutter xorg openbox

pip3 install -r requirements.txt
```

---

## 2. Configure Environment Variables

Edit `/etc/environment`:

```
LATITUDE=41.6
LONGITUDE=-89.5
```

(Adjust to your actual coordinates for accurate weather.)

---

## 3. Run the App

```bash
python3 app.py
```

- **Dashboard (kiosk):** `http://localhost:5000`
- **Admin (phone):**     `http://yourpi.local:5000/admin`

Both your phone and Pi must be on the same Wi-Fi network.

---

## 4. Using the Admin Interface on Your Phone

1. Find your Pi's hostname: `hostname` (default is `raspberrypi`)
2. Open `http://raspberrypi.local:5000/admin` in your phone's browser
3. Bookmark it for quick access

The admin lets you:
- Add reminders with an optional due date
- Mark reminders as done (they move to a completed section)
- Edit title or due date inline
- Delete reminders entirely

The dashboard auto-refreshes every 5 minutes, so changes appear quickly.

---

## 5. Auto-Start Flask on Boot

Create `/etc/systemd/system/dashboard.service`:

```ini
[Unit]
Description=Pi Dashboard
After=network.target

[Service]
User=pi
WorkingDirectory=/home/pi/dashboard
EnvironmentFile=/etc/environment
ExecStart=/usr/bin/python3 app.py
Restart=always

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl enable dashboard
sudo systemctl start dashboard
```

---

## 6. Chromium Kiosk Auto-Start

Create `/home/pi/.config/openbox/autostart`:

```bash
xset s off
xset s noblank
xset -dpms
unclutter -idle 0.5 -root &
chromium-browser --noerrdialogs --disable-infobars --kiosk http://localhost:5000 &
```

Enable desktop autologin:
```bash
sudo raspi-config
# System Options → Boot / Auto Login → Desktop Autologin
```

---

## 7. Troubleshooting

| Issue | Fix |
|-------|-----|
| `yourpi.local` not resolving | Use the Pi's IP address instead, e.g. `192.168.1.x:5000/admin` |
| Weather shows ERR | Check internet / lat-lon in `/etc/environment` |
| Reminders not saving | Check write permissions on the `dashboard/` folder |
| Chromium crashes | Add `--disable-gpu` flag to the kiosk launch command |
