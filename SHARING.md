# 📦 Sharing Photo Transfer with non-technical people

Goal: a friend on **any laptop (Windows / Mac / Linux)** **double-clicks an icon**,
a window/browser opens showing a **QR code**, they **scan it with their phone**,
and start sending/receiving. **No terminal. No Python. No setup.**

Each person runs their **own** hub on their **own** laptop for their **own** phone.

---

## For you (the builder): make the double-click app

A standalone app only runs on the OS it was built on, so build one per OS using
the matching script:

| Build on… | Run | Produces |
|-----------|-----|----------|
| **Linux** | `./build-linux.sh` | `dist/PhotoTransfer/` |
| **Windows** | `build-windows.bat` | `dist\PhotoTransfer\PhotoTransfer.exe` |
| **macOS** | `./build-macos.sh` | `dist/Photo Transfer.app` |

Each produces a self-contained app with Python bundled inside — nothing to install.

### How to hand it out (one link, any OS)
1. Put this project on GitHub.
2. Build the app on each OS you want to support.
3. **Zip** each `dist` result and upload them to a **GitHub Release**.
4. Share the **Release page link**. People click the download for *their* OS.

(Or just send someone the zip directly over chat / USB.)

### The one public link: a download page (GitHub Pages)
This repo includes a ready-made landing page in **`docs/`** — download buttons for
all three OSes, what it's for, and how to use it. Host it free:

1. On GitHub: **Settings → Pages → Source:** "Deploy from a branch", **branch:**
   `main`, **folder:** `/docs` → Save.
2. A minute later your page is live at
   `https://<your-username>.github.io/<repo>/`.
3. **Share that one link.** It auto-detects each visitor's OS and points them at
   the right download (which comes from your latest Release — see below).

Before publishing, open `docs/index.html` and set the repo URL at the top:
```html
<meta name="repo" content="https://github.com/adesh2151/photo-transfer">
```
(Change it if your username or repo name is different.) The page is also an
installable PWA.

### Easiest: let GitHub build all three for you (no build machines)
This repo includes `.github/workflows/build.yml`. Once the project is on GitHub,
you never need Windows/Mac/Linux build machines — GitHub builds all three:

```bash
git tag v1.0.0
git push origin v1.0.0
```

That kicks off the build. A few minutes later, a **Release** appears with
`PhotoTransfer-windows.zip`, `PhotoTransfer-macos-apple-silicon.zip`, `PhotoTransfer-macos-intel.zip`, and
`PhotoTransfer-linux.zip` attached. Share that **Release page link** — done.

(You can also trigger it by hand from the repo's **Actions** tab → *Build apps*
→ *Run workflow*, which uploads the three zips as downloadable artifacts.)

---

## For the person receiving it (zero tech)

1. **Download** the app for their computer and **unzip** it anywhere.
2. **Double-click** it:
   - **Windows:** `PhotoTransfer.exe` (if SmartScreen warns: *More info → Run anyway*)
   - **macOS:** right-click `Photo Transfer` → **Open** (first time only, unsigned app)
   - **Linux:** double-click `PhotoTransfer` (or the `.desktop` file), or run `./PhotoTransfer`
3. A **browser window opens showing a QR code**.
4. On their **phone (same WiFi)**: open the **Camera**, point at the QR, tap the link.
5. **Send** photos, or **Receive** files the computer has. Done. 🎉

That's the whole thing. No accounts, no cloud, no commands — and files stay on
their own computer and WiFi.

---

## Notes

- **Same WiFi is required** — phone and laptop must be on the same network.
- **Unsigned-app warnings** (Windows SmartScreen / macOS Gatekeeper) are normal
  for apps without a paid code-signing certificate — the "Run anyway" / right-click
  "Open" steps above get past them.
- **Antivirus false positives** can occasionally flag PyInstaller apps; harmless
  but expected for unsigned bundles.
- To rebuild after changing the code, just run the build script again.
