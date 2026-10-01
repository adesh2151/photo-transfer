# 📸 Photo Transfer

A small **WiFi file hub** to move photos, videos and any files **between phones
and computers** — no cable, no app store, no cloud.

One device (a computer) runs the hub. Every phone or computer on the **same
WiFi** opens it in a browser — or installs it to the home screen like an app —
and can:

- **Send** files to the hub
- **Receive** (download) anything on the hub

So it covers **phone → computer**, **computer → phone**, and **phone → phone**
(through the hub). Works on **Linux, macOS and Windows**.

---

## Quick start

**No-terminal version (for sharing with non-technical people):** build a
double-click app with the `build-*` scripts — the person just double-clicks an
icon and a browser opens with a QR to scan. See **[SHARING.md](SHARING.md)**.

**Run from source:**

| OS | How to run |
|----|-----------|
| **Linux / macOS** | `./run.sh` |
| **Windows** | double-click **`run.bat`** |
| **Any (manual)** | `python3 app.py` |

It prints a link like `http://192.168.1.7:8765` and opens it on the computer.
On each phone (same WiFi): open that link, or go to the **Connect** tab and scan
the QR. Then use **Send** / **Receive**.

**Install it like an app:** on the phone, open the link and choose
**"Add to Home Screen"** — you get the app icon and a full-screen, app-like
experience.

---

## Features

- **Three tabs:** Send · Receive · Connect (QR + settings)
- **Fast uploads:** pick many, tap once — uploaded in parallel with a progress bar
- **Any file type** — photos, videos, PDFs, anything
- **HEIC → JPG** auto-copy for iPhone photos (best-effort; see below)
- **Installable PWA** — home-screen icon, standalone display, generated app icon
- **Safe** — downloads are locked to the save folder (no path escapes)
- **Smart port** — default 8765, auto-picks a free one if busy

---

## Where files are saved

Default: `~/Pictures/PhoneTransfer/<date>/`. Change it in the **Connect → ⚙️**
box on the page, or with `--dir`. Your choice is remembered in
`~/.photo-transfer.json`.

---

## Options

```
python3 app.py --dir PATH       # where to save files
python3 app.py --port 9000      # specific port (default 8765)
python3 app.py --no-browser     # don't auto-open the browser
python3 app.py --no-heic        # don't auto-convert HEIC to JPG
python3 app.py --pin 4321       # fixed access code (default: random)
python3 app.py --no-auth        # no access code (trusted networks only)
python3 app.py --https          # encrypt traffic (self-signed certificate)
python3 app.py --approve        # approve each new device on the computer
python3 app.py --idle 15        # auto-stop after 15 min with no activity
```

Combine them, e.g. a locked-down run:
```
python3 app.py --https --approve --idle 15
```

---

## Desktop shortcut (optional)

- **Linux:** `./install-desktop.sh` → adds "Photo Transfer" to your app menu.
- **macOS:** in Automator, make an "Application" that runs
  `bash /path/to/run.sh`, or add `run.sh` to the Dock.
- **Windows:** right-click `run.bat` → Send to → Desktop (create shortcut); set
  its icon to `icon.png` in the shortcut's Properties.

---

## HEIC → JPG

iPhone photos are often HEIC. The app makes a `.jpg` copy automatically **if** a
converter is available. Any one of these enables it:

- `pip install pillow-heif pillow` (cross-platform), or
- ImageMagick (`magick`/`convert`), `libheif` (`heif-convert`), or macOS `sips`.

Without a converter, the original HEIC is still saved — just not converted.

---

## About "publishing as a real app"

This is already an **installable PWA on your WiFi** (add-to-home-screen works
over plain WiFi). A *fully* installable PWA with **offline mode** and Android's
"Install app" prompt requires **HTTPS** — browsers block service workers on a
plain `http://192.168.x.x` address. Serving over HTTPS would mean hosting it
(with a certificate), which changes the simple "same-WiFi, no-cloud" design.
The service worker is included and activates automatically **when** the app is
served over HTTPS or from `localhost`.

---

## Security

- **Access code** — each run shows a 6-digit code. Devices must enter it (or just
  **scan the QR**, which carries it) before they can do anything. Random by
  default; `--pin 1234` for a fixed one; `--no-auth` to disable on a trusted LAN.
- **Per-device sessions + brute-force throttle** — each device gets its own
  session cookie; repeated wrong codes lock that device out for a minute.
- **`--approve` (allow new devices)** — with this on, every new device has to be
  **approved by you on the hub computer** before it can connect, even with the
  code. Your own computer is trusted automatically.
- **`--https` (encryption)** — encrypts all traffic with a self-signed
  certificate, so files can't be read even on an untrusted network. The first
  visit on each device shows a "not private" warning (it's *your* certificate) —
  tap **Advanced → Proceed**. This also enables the full offline PWA.
- **`--idle MIN` (auto-stop)** — the hub shuts itself off after a quiet period so
  it's never left open and forgotten.
- **Activity log** — uploads, downloads and logins are recorded (with device IP
  and time) in `~/.photo-transfer.log`.
- **Folder is locked down** — downloads can't escape the save folder (no `../`),
  and the save folder can only be changed **from the hub computer itself**.

Stop the hub (Ctrl+C) to cut off all access instantly.

## How it works

A tiny built-in web server (Python standard library) serves the app and stores
what devices send. The only optional extra is
[`segno`](https://pypi.org/project/segno/) for the QR image — installed
automatically by the launchers, with a fallback if it's missing. Nothing leaves
your local network.
