#!/usr/bin/env python3
"""
Photo Transfer — a local WiFi hub to send files between phones and computers.

One device (this computer) runs the hub. Every device on the SAME WiFi opens it
in a browser (or installs it to the home screen) and can:
  • SEND photos/videos/files to the hub
  • RECEIVE (download) anything already on the hub

So it covers phone → computer, computer → phone, and phone → phone (via the hub).
No cable, no app store, no cloud. Works on Linux, macOS and Windows.

Run it:
    python3 app.py                 # or double-click run.sh / run.bat
    python3 app.py --dir ~/Photos  # choose where files are saved
    python3 app.py --port 9000     # choose a port
"""

import argparse
import datetime
import html
import io
import json
import mimetypes
import os
import queue
import re
import secrets
import shutil
import socket
import ssl
import struct
import subprocess
import threading
import time
import urllib.parse
import webbrowser
import zlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

APP_NAME = "Photo Transfer"
SHORT_NAME = "Transfer"
DEFAULT_PORT = 8765
MAX_UPLOAD_BYTES = 5 * 1024 * 1024 * 1024  # 5 GB per file
CONFIG_FILE = Path.home() / ".photo-transfer.json"
UPLOAD_CONCURRENCY = 4
THEME = "#007aff"

# Runtime state (set in main()).
SAVE_ROOT = ""
SERVER_URL = ""        # plain base link, shown to people
QR_URL = ""            # link the QR encodes (carries the access code)
CONVERT_HEIC = True
REQUIRE_AUTH = True
AUTH_PIN = ""          # access code; random each run unless --pin given
_ICON_CACHE = {}

# Simple brute-force throttle: per-IP failed PIN attempts.
_FAILS = {}
_FAILS_LOCK = threading.Lock()
_MAX_FAILS = 8
_LOCK_SECONDS = 60

# Security options (set in main()).
USE_HTTPS = False
REQUIRE_APPROVAL = False
IDLE_MINUTES = 0
LOG_FILE = Path.home() / ".photo-transfer.log"
CERT_DIR = Path.home() / ".photo-transfer-cert"

# TLS context (set in main() when --https); the handshake runs per-connection.
SSL_CONTEXT = None

# Per-device sessions: token -> expiry timestamp. Approval queue for new devices.
APPROVED = {}
_APPROVED_LOCK = threading.Lock()
_APPROVE_Q = queue.Queue()
_LAST_ACTIVITY = time.time()
_ACT_LOCK = threading.Lock()


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
def default_save_dir():
    return str(Path.home() / "Pictures" / "PhoneTransfer")


def load_config():
    try:
        return json.loads(CONFIG_FILE.read_text())
    except Exception:
        return {}


def save_config(cfg):
    try:
        CONFIG_FILE.write_text(json.dumps(cfg, indent=2))
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Networking
# ---------------------------------------------------------------------------
def lan_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except Exception:
        return "127.0.0.1"
    finally:
        s.close()


def find_server(preferred_port):
    last_err = None
    for port in range(preferred_port, preferred_port + 20):
        try:
            return ThreadingHTTPServer(("0.0.0.0", port), Handler), port
        except OSError as exc:
            last_err = exc
    raise last_err


# ---------------------------------------------------------------------------
# QR code
# ---------------------------------------------------------------------------
def qr_png_bytes(url):
    try:
        import segno
        buf = io.BytesIO()
        segno.make(url, error="m").save(buf, kind="png", scale=8, border=2)
        return buf.getvalue()
    except Exception:
        pass
    if shutil.which("qrencode"):
        try:
            return subprocess.run(
                ["qrencode", "-o", "-", "-t", "PNG", "-s", "8", "-m", "2", url],
                capture_output=True, check=True).stdout
        except Exception:
            pass
    return None


def qr_terminal(url):
    if not shutil.which("qrencode"):
        return
    try:
        print(subprocess.run(["qrencode", "-t", "ANSIUTF8", "-m", "2", url],
                             capture_output=True, text=True, check=True).stdout)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# App icon — generated in pure Python (no image libraries needed)
# ---------------------------------------------------------------------------
def _png(width, height, buf):
    def chunk(typ, data):
        return (struct.pack(">I", len(data)) + typ + data +
                struct.pack(">I", zlib.crc32(typ + data) & 0xffffffff))
    raw = bytearray()
    row = width * 4
    for y in range(height):
        raw.append(0)
        raw += buf[y * row:(y + 1) * row]
    return (b"\x89PNG\r\n\x1a\n" +
            chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)) +
            chunk(b"IDAT", zlib.compress(bytes(raw), 9)) +
            chunk(b"IEND", b""))


def icon_png(size):
    if size in _ICON_CACHE:
        return _ICON_CACHE[size]
    w = h = size
    buf = bytearray(w * h * 4)
    s = size / 512.0
    radius = size * 0.22

    def put(x, y, col):
        x = int(x); y = int(y)
        if 0 <= x < w and 0 <= y < h:
            i = (y * w + x) * 4
            buf[i], buf[i + 1], buf[i + 2], buf[i + 3] = col[0], col[1], col[2], 255

    # Rounded-rect gradient background (blue -> purple).
    for y in range(h):
        t = y / (h - 1)
        r = int(0 + (88 - 0) * t); g = int(122 + (86 - 122) * t); b = int(255 + (214 - 255) * t)
        for x in range(w):
            cx = min(x, w - 1 - x); cy = min(y, h - 1 - y)
            if cx < radius and cy < radius:
                dx = radius - cx; dy = radius - cy
                if dx * dx + dy * dy > radius * radius:
                    continue
            i = (y * w + x) * 4
            buf[i], buf[i + 1], buf[i + 2], buf[i + 3] = r, g, b, 255

    def rrect(x0, y0, x1, y1, rr, col):
        for y in range(int(y0), int(y1)):
            for x in range(int(x0), int(x1)):
                cx = min(x - x0, x1 - 1 - x); cy = min(y - y0, y1 - 1 - y)
                if cx < rr and cy < rr:
                    dx = rr - cx; dy = rr - cy
                    if dx * dx + dy * dy > rr * rr:
                        continue
                put(x, y, col)

    def circle(cx, cy, rad, col):
        for y in range(int(cy - rad), int(cy + rad + 1)):
            for x in range(int(cx - rad), int(cx + rad + 1)):
                if (x - cx) ** 2 + (y - cy) ** 2 <= rad * rad:
                    put(x, y, col)

    white = (255, 255, 255); accent = (0, 122, 255)
    rrect(150 * s, 150 * s, 250 * s, 185 * s, 10 * s, white)      # viewfinder bump
    rrect(90 * s, 180 * s, 422 * s, 400 * s, 34 * s, white)       # camera body
    circle(256 * s, 294 * s, 80 * s, accent)                      # lens
    circle(256 * s, 294 * s, 50 * s, white)
    circle(256 * s, 294 * s, 28 * s, accent)
    circle(372 * s, 214 * s, 12 * s, accent)                      # flash

    png = _png(w, h, buf)
    _ICON_CACHE[size] = png
    return png


def manifest_json():
    return json.dumps({
        "name": APP_NAME,
        "short_name": SHORT_NAME,
        "description": "Send files between phones and computers on your WiFi.",
        "start_url": "/",
        "display": "standalone",
        "background_color": "#000000",
        "theme_color": THEME,
        "icons": [
            {"src": "/icon-192.png", "sizes": "192x192", "type": "image/png"},
            {"src": "/icon-512.png", "sizes": "512x512", "type": "image/png",
             "purpose": "any maskable"},
        ],
    })


SERVICE_WORKER = """
const CACHE = 'photo-transfer-v1';
self.addEventListener('install', e => self.skipWaiting());
self.addEventListener('activate', e => self.clients.claim());
self.addEventListener('fetch', e => {
  // Network-first; fall back to cache so the shell still opens offline.
  e.respondWith(
    fetch(e.request).then(r => {
      if (e.request.method === 'GET' && r.ok) {
        const c = r.clone(); caches.open(CACHE).then(ch => ch.put(e.request, c));
      }
      return r;
    }).catch(() => caches.match(e.request))
  );
});
"""


# ---------------------------------------------------------------------------
# File helpers
# ---------------------------------------------------------------------------
def safe_name(name):
    name = name.replace("\\", "/").split("/")[-1]
    name = re.sub(r"[^A-Za-z0-9._-]", "_", name)
    return name or "upload.bin"


def unique_path(folder, name):
    dest = os.path.join(folder, name)
    if not os.path.exists(dest):
        return dest
    base, ext = os.path.splitext(name)
    i = 1
    while True:
        cand = os.path.join(folder, f"{base} ({i}){ext}")
        if not os.path.exists(cand):
            return cand
        i += 1


def today_folder():
    folder = os.path.join(SAVE_ROOT, datetime.date.today().isoformat())
    os.makedirs(folder, exist_ok=True)
    return folder


def convert_heic_to_jpg(src_path):
    """Best-effort HEIC/HEIF -> JPG alongside the original. Returns jpg path or None."""
    if os.path.splitext(src_path)[1].lower() not in (".heic", ".heif"):
        return None
    jpg = os.path.splitext(src_path)[0] + ".jpg"
    if os.path.exists(jpg):
        jpg = unique_path(os.path.dirname(src_path),
                          os.path.splitext(os.path.basename(src_path))[0] + ".jpg")
    try:  # 1) pillow-heif + Pillow
        from PIL import Image
        import pillow_heif
        pillow_heif.register_heif_opener()
        Image.open(src_path).convert("RGB").save(jpg, "JPEG", quality=90)
        return jpg
    except Exception:
        pass
    for cmd in (["magick", src_path, jpg], ["convert", src_path, jpg],
                ["heif-convert", src_path, jpg],
                ["sips", "-s", "format", "jpeg", src_path, "--out", jpg]):
        if shutil.which(cmd[0]):
            try:
                subprocess.run(cmd, check=True, capture_output=True, timeout=120)
                if os.path.exists(jpg):
                    return jpg
            except Exception:
                continue
    return None


def list_files(limit=1000):
    items = []
    for dirpath, _dirs, files in os.walk(SAVE_ROOT):
        for f in files:
            if f.startswith("."):
                continue
            full = os.path.join(dirpath, f)
            try:
                st = os.stat(full)
            except OSError:
                continue
            rel = os.path.relpath(full, SAVE_ROOT).replace(os.sep, "/")
            items.append({"name": f, "path": rel, "size": st.st_size, "mtime": st.st_mtime})
    items.sort(key=lambda x: x["mtime"], reverse=True)
    return items[:limit]


def resolve_in_root(rel):
    """Return an absolute path inside SAVE_ROOT, or None if it escapes."""
    rel = (rel or "").replace("/", os.sep)
    full = os.path.realpath(os.path.join(SAVE_ROOT, rel))
    root = os.path.realpath(SAVE_ROOT)
    if full == root or full.startswith(root + os.sep):
        return full
    return None


# ---------------------------------------------------------------------------
# The page
# ---------------------------------------------------------------------------
PAGE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>%%APP%%</title>
<link rel="manifest" href="/manifest.webmanifest">
<meta name="theme-color" content="%%THEME%%">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
<meta name="apple-mobile-web-app-title" content="%%SHORT%%">
<link rel="apple-touch-icon" href="/icon-180.png">
<link rel="icon" href="/icon-192.png">
<style>
  :root{color-scheme:light dark;--accent:#007aff;--green:#34c759;--purple:#5856d6;--orange:#ff9500;}
  *{box-sizing:border-box;}
  body{font-family:-apple-system,BlinkMacSystemFont,system-ui,sans-serif;margin:0;
       padding:env(safe-area-inset-top) 16px calc(16px + env(safe-area-inset-bottom));
       background:#f2f2f7;color:#111;min-height:100vh;}
  @media (prefers-color-scheme:dark){
    body{background:#000;color:#fff;}
    .card,.box{background:#1c1c1e;}
    .drop{background:#2c2c2e;border-color:#3a3a3c;}
    .seg{background:#2c2c2e;} .frow{border-color:#2c2c2e;}
    input[type=text]{background:#2c2c2e;color:#fff;border-color:#444;}
  }
  .wrap{max-width:460px;margin:0 auto;}
  header{display:flex;align-items:center;gap:10px;padding:18px 4px 6px;}
  header img{width:40px;height:40px;border-radius:10px;}
  header h1{font-size:20px;margin:0;} header p{font-size:13px;margin:0;opacity:.6;}
  .seg{display:flex;background:#e5e5ea;border-radius:11px;padding:3px;margin:10px 0 16px;}
  .seg button{flex:1;border:none;background:transparent;color:inherit;font-size:14px;
       font-weight:600;padding:9px;border-radius:9px;cursor:pointer;}
  .seg button.active{background:var(--accent);color:#fff;}
  .card{background:#fff;border-radius:18px;padding:20px;box-shadow:0 8px 30px rgba(0,0,0,.10);}
  .box{background:#f2f2f7;border:1px solid #e5e5ea;border-radius:12px;padding:13px;
       font-size:14px;line-height:1.5;margin-bottom:14px;}
  .box b{font-size:12px;text-transform:uppercase;letter-spacing:.04em;opacity:.6;}
  ol{margin:6px 0 0;padding-left:20px;} ol li{margin:3px 0;}
  .drop{border:2px dashed #c7c7cc;border-radius:14px;padding:20px;text-align:center;
        font-size:14px;margin-bottom:12px;}
  input[type=file]{display:none;}
  label.pick,button.big{display:block;width:100%;text-align:center;font-size:17px;
        font-weight:600;padding:15px;border-radius:12px;border:none;cursor:pointer;}
  label.pick{background:var(--accent);color:#fff;margin-bottom:10px;}
  button.go{background:var(--green);color:#fff;} button.go:disabled{background:#a7a7a7;}
  #count{font-size:14px;opacity:.7;margin:6px 0 12px;text-align:center;}
  #progwrap{display:none;margin-top:14px;}
  #bar{height:10px;background:#e5e5ea;border-radius:6px;overflow:hidden;}
  #bar>div{height:100%;width:0;background:var(--green);transition:width .2s;}
  #status{font-size:14px;margin-top:8px;text-align:center;}
  .ok{color:var(--green);font-weight:600;}
  #qrbox{text-align:center;} #qrbox img{width:100%;max-width:230px;background:#fff;
        padding:10px;border-radius:12px;} .url{font-size:14px;margin-top:8px;word-break:break-all;}
  .frow{display:flex;align-items:center;justify-content:space-between;gap:10px;
        padding:10px 2px;border-bottom:1px solid #eee;}
  .frow a{color:var(--accent);text-decoration:none;font-size:15px;word-break:break-all;}
  .frow .sz{font-size:12px;opacity:.5;white-space:nowrap;}
  .muted{font-size:13px;opacity:.55;text-align:center;margin-top:14px;}
  .row{display:flex;gap:8px;margin-top:10px;}
  input[type=text]{flex:1;padding:10px;border-radius:10px;border:1px solid #c7c7cc;font-size:14px;}
  .row button{padding:10px 16px;border:none;border-radius:10px;background:var(--accent);
        color:#fff;font-size:14px;font-weight:600;}
  .hide{display:none;}
  button.refresh{background:var(--orange);color:#fff;margin-bottom:12px;}
</style>
</head>
<body>
<div class="wrap">
  <header>
    <img src="/icon-192.png" alt="">
    <div><h1>%%APP%%</h1><p>Share files on your WiFi — no cable</p></div>
  </header>

  <div class="seg">
    <button id="t-send" class="active" onclick="tab('send')">Send</button>
    <button id="t-files" onclick="tab('files')">Receive</button>
    <button id="t-connect" onclick="tab('connect')">Connect</button>
  </div>

  <!-- SEND -->
  <section id="tab-send" class="card">
    <div class="box"><b>Send to this hub</b>
      <ol><li>Pick photos (swipe to grab many — <b>~150 at a time</b> is fastest).</li>
          <li>Tap <b>Upload</b> once — they all send together.</li></ol>
    </div>
    <form id="f">
      <div class="drop">Choose what to send, then upload.</div>
      <label class="pick" for="file">Choose Files</label>
      <input id="file" type="file" accept="*/*" multiple>
      <div id="count">No files selected</div>
      <button class="big go" id="go" type="submit" disabled>Upload</button>
    </form>
    <div id="progwrap"><div id="bar"><div></div></div><div id="status"></div></div>
  </section>

  <!-- RECEIVE -->
  <section id="tab-files" class="card hide">
    <div class="box"><b>Receive from the hub</b>
      Tap any file to download it to this device. Works from any phone or computer
      on the WiFi — so one phone can grab what another phone sent.
    </div>
    <button class="big refresh" onclick="loadFiles()">🔄 Refresh list</button>
    <div id="files"></div>
  </section>

  <!-- CONNECT -->
  <section id="tab-connect" class="card hide">
    <div class="box"><b>Add another device</b>
      Open this same app on another phone or computer on the same WiFi — scan the
      code or type the link.
    </div>
    <div id="qrbox">
      <img src="/qr.png" alt="QR code" id="qrimg">
      <div class="url">%%URL%%</div>
      <div class="box" style="margin-top:12px"><b>Access code</b>
        <div style="font-size:24px;letter-spacing:.25em;font-weight:700;margin-top:4px">%%PIN%%</div>
        <div class="muted" style="margin-top:4px">Scanning the QR fills this in automatically.</div>
      </div>
    </div>
    <details style="margin-top:16px">
      <summary style="cursor:pointer;opacity:.7;font-size:14px">⚙️ Where files are saved</summary>
      <p class="muted" style="text-align:left">On the hub computer:</p>
      <div class="box" style="word-break:break-all">%%SAVE_DIR%%</div>
      <form id="dirform" class="row">
        <input type="text" id="dir" value="%%SAVE_DIR%%" placeholder="Folder path on the computer">
        <button type="submit">Save</button>
      </form>
      <div id="dirmsg" class="muted" style="margin-top:6px"></div>
    </details>
  </section>

  <div class="muted">All devices must be on the same WiFi network.</div>
  <div class="muted" style="margin-top:2px">by <b>Adesh</b></div>
</div>

<script>
function $(id){return document.getElementById(id);}
function tab(name){
  ['send','files','connect'].forEach(function(n){
    $('tab-'+n).classList.toggle('hide', n!==name);
    $('t-'+n).classList.toggle('active', n===name);
  });
  if(name==='files') loadFiles();
}

var input=$('file'), count=$('count'), go=$('go'), form=$('f');
var progwrap=$('progwrap'), barFill=document.querySelector('#bar>div'), status=$('status');
// iOS "prepares" picked photos before handing them over (slow for iCloud/large
// batches). We can't remove that step, but we show feedback so it isn't frozen.
var picking=false, prepTimer=null;
input.addEventListener('click', function(){ picking=true; });
window.addEventListener('focus', function(){
  if(picking){
    count.innerHTML='⏳ Preparing your photos… large batches &amp; iCloud photos take a bit.';
    clearTimeout(prepTimer);
    prepTimer=setTimeout(function(){ if(picking){picking=false;count.textContent='No files selected';} }, 180000);
  }
});
input.addEventListener('change', function(){
  picking=false; clearTimeout(prepTimer);
  var n=input.files.length;
  count.textContent=n?n+' file(s) selected':'No files selected';
  go.disabled=n===0;
});
function uploadOne(file){
  return new Promise(function(resolve){
    var xhr=new XMLHttpRequest();
    xhr.open('POST','/put');
    xhr.setRequestHeader('X-Filename', encodeURIComponent(file.name||'file'));
    xhr.setRequestHeader('Content-Type','application/octet-stream');
    xhr.onloadend=function(){resolve(xhr.status===200);};
    xhr.send(file);
  });
}
form.addEventListener('submit', function(e){
  e.preventDefault();
  var files=Array.prototype.slice.call(input.files);
  if(!files.length) return;
  go.disabled=true; go.textContent='Uploading…'; progwrap.style.display='block';
  var done=0,ok=0,next=0;
  function upd(){barFill.style.width=Math.round(done/files.length*100)+'%';
                status.textContent=done+' / '+files.length+' uploaded';}
  upd();
  function worker(){
    if(next>=files.length) return Promise.resolve();
    var file=files[next++];
    return uploadOne(file).then(function(good){done++;if(good)ok++;upd();return worker();});
  }
  var ws=[]; for(var i=0;i<Math.min(%%CONC%%,files.length);i++) ws.push(worker());
  Promise.all(ws).then(function(){
    status.innerHTML='<span class="ok">✅ Done! '+ok+' of '+files.length+' sent.</span>';
    go.textContent='Send more'; go.disabled=false;
    input.value=''; count.textContent='No files selected';
  });
});

function fmt(n){if(n<1024)return n+' B';if(n<1048576)return (n/1024).toFixed(0)+' KB';
  if(n<1073741824)return (n/1048576).toFixed(1)+' MB';return (n/1073741824).toFixed(2)+' GB';}
function loadFiles(){
  var box=$('files'); box.innerHTML='<p class="muted">Loading…</p>';
  fetch('/list').then(function(r){return r.json();}).then(function(items){
    if(!items.length){box.innerHTML='<p class="muted">Nothing here yet. Send something from the Send tab.</p>';return;}
    var h='';
    items.forEach(function(it){
      h+='<div class="frow"><a href="/get?p='+encodeURIComponent(it.path)+'" download>'+
         it.name+'</a><span class="sz">'+fmt(it.size)+'</span></div>';
    });
    box.innerHTML=h;
  }).catch(function(){box.innerHTML='<p class="muted">Could not load files.</p>';});
}

var qrimg=$('qrimg'); if(qrimg) qrimg.onerror=function(){qrimg.style.display='none';};
var dirform=$('dirform'), dirmsg=$('dirmsg');
dirform.addEventListener('submit', function(e){
  e.preventDefault();
  fetch('/set-dir',{method:'POST',headers:{'Content-Type':'text/plain'},body:$('dir').value})
   .then(function(r){return r.json();})
   .then(function(j){dirmsg.innerHTML=j.ok?'<span class="ok">✔ Saving to: '+j.dir+'</span>':'✖ '+(j.error||'failed');});
});

if('serviceWorker' in navigator){navigator.serviceWorker.register('/sw.js').catch(function(){});}
tab("%%DEFAULTTAB%%");  // hub computer opens on the QR; phones open on Send
</script>
</body>
</html>
"""


def render_page(default_tab="send"):
    return (PAGE
            .replace("%%APP%%", APP_NAME)
            .replace("%%SHORT%%", SHORT_NAME)
            .replace("%%THEME%%", THEME)
            .replace("%%URL%%", SERVER_URL)
            .replace("%%PIN%%", html.escape(AUTH_PIN))
            .replace("%%SAVE_DIR%%", html.escape(SAVE_ROOT))
            .replace("%%DEFAULTTAB%%", default_tab)
            .replace("%%CONC%%", str(UPLOAD_CONCURRENCY)))


LOGIN_PAGE = r"""<!doctype html><html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>%%APP%%</title>
<link rel="apple-touch-icon" href="/icon-180.png"><meta name="theme-color" content="%%THEME%%">
<style>
 :root{color-scheme:light dark;}
 body{font-family:-apple-system,system-ui,sans-serif;margin:0;min-height:100vh;display:flex;
      align-items:center;justify-content:center;background:#f2f2f7;color:#111;padding:20px;}
 @media (prefers-color-scheme:dark){body{background:#000;color:#fff;}.card{background:#1c1c1e;}
      input{background:#2c2c2e;color:#fff;border-color:#444;}}
 .card{background:#fff;border-radius:18px;padding:26px;max-width:340px;width:100%;text-align:center;
       box-shadow:0 10px 40px rgba(0,0,0,.12);}
 img{width:54px;height:54px;border-radius:12px;margin-bottom:10px;}
 h1{font-size:19px;margin:0 0 4px;} p{font-size:14px;opacity:.6;margin:0 0 18px;}
 input{width:100%;padding:14px;font-size:22px;text-align:center;letter-spacing:.3em;
       border-radius:12px;border:1px solid #c7c7cc;margin-bottom:12px;}
 button{width:100%;padding:14px;font-size:17px;font-weight:600;border:none;border-radius:12px;
        background:#007aff;color:#fff;cursor:pointer;}
 .err{color:#ff3b30;font-size:14px;margin-bottom:10px;min-height:18px;}
</style></head><body>
 <form class="card" method="post" action="/login">
   <img src="/icon-192.png" alt=""><h1>%%APP%%</h1>
   <p>Enter the access code shown on the computer.</p>
   <div class="err">%%ERR%%</div>
   <input name="pin" inputmode="numeric" autocomplete="one-time-code" placeholder="••••••" autofocus>
   <button type="submit">Unlock</button>
 </form>
</body></html>"""


def login_page(error=""):
    return (LOGIN_PAGE
            .replace("%%APP%%", APP_NAME)
            .replace("%%THEME%%", THEME)
            .replace("%%ERR%%", html.escape(error)))


def is_localhost(addr):
    return addr in ("127.0.0.1", "::1", "localhost")


def _throttled(ip):
    with _FAILS_LOCK:
        rec = _FAILS.get(ip)
        return bool(rec and rec[1] > time.time())


def _note_fail(ip):
    with _FAILS_LOCK:
        count, _until = _FAILS.get(ip, (0, 0))
        count += 1
        until = time.time() + _LOCK_SECONDS if count >= _MAX_FAILS else 0
        _FAILS[ip] = (0 if until else count, until)


def _clear_fails(ip):
    with _FAILS_LOCK:
        _FAILS.pop(ip, None)


# --- Activity log ---------------------------------------------------------
def log_event(action, ip, detail=""):
    line = "%s  %-15s  %-10s %s" % (
        datetime.datetime.now().isoformat(timespec="seconds"), ip, action, detail)
    print("  · " + line, flush=True)
    try:
        with open(LOG_FILE, "a") as f:
            f.write(line.rstrip() + "\n")
    except Exception:
        pass


# --- Idle auto-stop -------------------------------------------------------
def touch_activity():
    global _LAST_ACTIVITY
    with _ACT_LOCK:
        _LAST_ACTIVITY = time.time()


def idle_watchdog(server):
    while True:
        time.sleep(20)
        if not IDLE_MINUTES:
            continue
        with _ACT_LOCK:
            idle = time.time() - _LAST_ACTIVITY
        if idle > IDLE_MINUTES * 60:
            print(f"\n  ⏲  No activity for {IDLE_MINUTES} min — shutting down for safety.",
                  flush=True)
            server.shutdown()
            return


# --- Device approval + sessions -------------------------------------------
def approval_worker():
    """Prompts on the hub terminal to allow/deny each new device."""
    while True:
        item = _APPROVE_Q.get()
        try:
            ans = input(f"\n  🔔 Allow device {item['ip']} to connect? [y/N]: ").strip().lower()
        except (EOFError, OSError):
            ans = ""
        item["ok"] = ans.startswith("y")
        log_event("APPROVED" if item["ok"] else "DENIED", item["ip"])
        item["event"].set()


def new_session(ip):
    tok = secrets.token_urlsafe(16)
    with _APPROVED_LOCK:
        APPROVED[tok] = time.time() + 86400
    return tok


def request_session(ip):
    """Return a session token if the device may connect, else None."""
    if not REQUIRE_APPROVAL or is_localhost(ip):
        log_event("LOGIN", ip)
        return new_session(ip)
    item = {"ip": ip, "event": threading.Event(), "ok": False}
    _APPROVE_Q.put(item)
    if item["event"].wait(timeout=60) and item["ok"]:
        return new_session(ip)
    return None


def session_valid(token):
    with _APPROVED_LOCK:
        exp = APPROVED.get(token)
        if exp and exp > time.time():
            return True
        if exp:
            APPROVED.pop(token, None)
    return False


# --- TLS certificate ------------------------------------------------------
def ensure_cert(ip):
    """Return (certfile, keyfile) for a self-signed cert covering this IP, or (None, None)."""
    CERT_DIR.mkdir(exist_ok=True)
    cert, key = CERT_DIR / "cert.pem", CERT_DIR / "key.pem"
    if cert.exists() and key.exists():
        return str(cert), str(key)
    san = f"subjectAltName=IP:{ip},IP:127.0.0.1,DNS:localhost"
    if shutil.which("openssl"):
        try:
            subprocess.run(
                ["openssl", "req", "-x509", "-newkey", "rsa:2048", "-sha256",
                 "-keyout", str(key), "-out", str(cert), "-days", "825", "-nodes",
                 "-subj", "/CN=Photo Transfer", "-addext", san],
                check=True, capture_output=True)
            return str(cert), str(key)
        except Exception:
            pass
    try:  # pure-Python fallback
        import ipaddress
        import datetime as _dt
        from cryptography import x509
        from cryptography.x509.oid import NameOID
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import rsa
        k = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        nm = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Photo Transfer")])
        alt = x509.SubjectAlternativeName([
            x509.IPAddress(ipaddress.ip_address(ip)),
            x509.IPAddress(ipaddress.ip_address("127.0.0.1")),
            x509.DNSName("localhost")])
        crt = (x509.CertificateBuilder().subject_name(nm).issuer_name(nm)
               .public_key(k.public_key()).serial_number(x509.random_serial_number())
               .not_valid_before(_dt.datetime.utcnow() - _dt.timedelta(days=1))
               .not_valid_after(_dt.datetime.utcnow() + _dt.timedelta(days=825))
               .add_extension(alt, critical=False).sign(k, hashes.SHA256()))
        key.write_bytes(k.private_bytes(serialization.Encoding.PEM,
                        serialization.PrivateFormat.TraditionalOpenSSL,
                        serialization.NoEncryption()))
        cert.write_bytes(crt.public_bytes(serialization.Encoding.PEM))
        return str(cert), str(key)
    except Exception:
        return None, None


# ---------------------------------------------------------------------------
# HTTP handler
# ---------------------------------------------------------------------------
class Handler(BaseHTTPRequestHandler):
    def setup(self):
        # Do the TLS handshake HERE (in this connection's own worker thread), so a
        # client speaking plain HTTP to the HTTPS port can't block other devices.
        if SSL_CONTEXT is not None:
            try:
                self.request.settimeout(20)
                self.request = SSL_CONTEXT.wrap_socket(self.request, server_side=True)
                self.request.settimeout(None)
            except Exception:
                try:
                    self.connection = self.request
                    self.rfile = io.BytesIO()
                    self.wfile = io.BytesIO()
                except Exception:
                    pass
                self._dead = True
                return
        super().setup()

    def handle(self):
        if getattr(self, "_dead", False):
            return
        super().handle()

    def _send(self, body, ctype="text/html; charset=utf-8", code=200, extra=None):
        if isinstance(body, str):
            body = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _authed(self):
        """True if the request carries a valid device session cookie."""
        if not REQUIRE_AUTH:
            return True
        m = re.search(r"pt_sess=([^;]+)", self.headers.get("Cookie", ""))
        return bool(m and session_valid(m.group(1)))

    def _session_cookie(self, token):
        return f"pt_sess={token}; Path=/; SameSite=Lax; Max-Age=86400"

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        ip = self.client_address[0]

        # Static, non-sensitive assets are open (needed by the login page too).
        if path == "/manifest.webmanifest":
            return self._send(manifest_json(), "application/manifest+json")
        if path == "/sw.js":
            return self._send(SERVICE_WORKER, "application/javascript")
        if path.startswith("/icon-") or path.startswith("/apple-touch-icon"):
            m = re.search(r"(\d+)", path)
            size = max(32, min(int(m.group(1)) if m else 180, 1024))
            return self._send(icon_png(size), "image/png")

        authed = self._authed()

        # Entry point: the main page. A valid ?k=CODE starts a session (which may
        # need approval on the hub). Otherwise show the unlock screen.
        if path in ("/", "/index.html"):
            dtab = "connect" if is_localhost(ip) else "send"  # computer sees QR, phone sees Send
            if authed:
                touch_activity()
                return self._send(render_page(dtab))
            if not REQUIRE_AUTH:
                return self._send(render_page(dtab))
            k = urllib.parse.parse_qs(parsed.query).get("k", [None])[0]
            if k and secrets.compare_digest(k, AUTH_PIN):
                token = request_session(ip)
                if token:
                    touch_activity()
                    return self._send(render_page(dtab),
                                      extra={"Set-Cookie": self._session_cookie(token)})
                return self._send(login_page("Not approved. Ask the computer to allow it."),
                                  code=401)
            return self._send(login_page(), code=401)

        if not authed:
            return self.send_error(403, "access code required")
        touch_activity()

        if path == "/qr.png":
            png = qr_png_bytes(QR_URL)
            return self._send(png, "image/png") if png else self.send_error(404)
        if path == "/list":
            return self._send(json.dumps(list_files()), "application/json")
        if path == "/get":
            q = urllib.parse.parse_qs(parsed.query)
            full = resolve_in_root(q.get("p", [""])[0])
            if not full or not os.path.isfile(full):
                return self.send_error(404, "not found")
            ctype = mimetypes.guess_type(full)[0] or "application/octet-stream"
            disp = 'attachment; filename="%s"' % os.path.basename(full).replace('"', "")
            log_event("DOWNLOAD", ip, os.path.basename(full))
            try:
                size = os.path.getsize(full)
                self.send_response(200)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(size))
                self.send_header("Content-Disposition", disp)
                self.end_headers()
                with open(full, "rb") as fh:
                    shutil.copyfileobj(fh, self.wfile, 1024 * 256)
            except Exception:
                pass
            return
        return self.send_error(404)

    def _save_stream(self, length, raw_name):
        name = safe_name(urllib.parse.unquote(raw_name or ""))
        path = unique_path(today_folder(), name)
        remaining, chunk = length, 1024 * 256
        with open(path, "wb") as fh:
            while remaining > 0:
                data = self.rfile.read(min(chunk, remaining))
                if not data:
                    break
                fh.write(data)
                remaining -= len(data)
        return path

    def do_POST(self):
        global SAVE_ROOT
        parsed = urllib.parse.urlparse(self.path)
        ip = self.client_address[0]

        # Login: validate the access code, then (maybe) wait for approval, set session.
        if parsed.path == "/login":
            if REQUIRE_AUTH and _throttled(ip):
                return self._send(login_page("Too many tries — wait a minute."), code=429)
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length).decode("utf-8", "replace")
            pin = urllib.parse.parse_qs(body).get("pin", [""])[0].strip()
            if not REQUIRE_AUTH:
                return self._send(b"", code=303, extra={"Location": "/"})
            if not secrets.compare_digest(pin, AUTH_PIN):
                _note_fail(ip)
                return self._send(login_page("Wrong code. Try again."), code=401)
            _clear_fails(ip)
            token = request_session(ip)
            if not token:
                return self._send(login_page("Not approved by the computer."), code=401)
            return self._send(b"", code=303,
                              extra={"Set-Cookie": self._session_cookie(token), "Location": "/"})

        # Everything else needs a valid session.
        if not self._authed():
            return self.send_error(403, "access code required")
        touch_activity()

        if parsed.path == "/put":
            length = int(self.headers.get("Content-Length", 0))
            if length <= 0 or length > MAX_UPLOAD_BYTES:
                return self.send_error(400, "empty or too large")
            try:
                full = self._save_stream(length, self.headers.get("X-Filename", ""))
            except Exception as exc:
                return self.send_error(500, f"save failed: {exc}")
            if CONVERT_HEIC:
                try:
                    jpg = convert_heic_to_jpg(full)
                    if jpg:
                        print(f"     (also made {os.path.basename(jpg)})", flush=True)
                except Exception:
                    pass
            log_event("UPLOAD", ip, os.path.basename(full))
            return self._send(b'{"ok":true}', "application/json")

        if parsed.path == "/set-dir":
            # Only the hub computer itself may change where files are saved —
            # remote phones can't repoint it at other folders.
            if not is_localhost(ip):
                return self._send(
                    json.dumps({"ok": False,
                                "error": "Change the folder on the computer running the hub."}),
                    "application/json", code=403)
            length = int(self.headers.get("Content-Length", 0))
            new_dir = os.path.expanduser(
                self.rfile.read(length).decode("utf-8", "replace").strip())
            try:
                os.makedirs(new_dir, exist_ok=True)
                t = os.path.join(new_dir, ".write-test")
                open(t, "w").close(); os.remove(t)
            except Exception as exc:
                return self._send(json.dumps({"ok": False, "error": str(exc)}),
                                  "application/json")
            SAVE_ROOT = new_dir
            cfg = load_config(); cfg["save_dir"] = new_dir; save_config(cfg)
            print(f"  ⚙  save folder -> {new_dir}", flush=True)
            return self._send(json.dumps({"ok": True, "dir": new_dir}), "application/json")

        return self.send_error(404)

    def log_message(self, *args):
        pass


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    global SAVE_ROOT, SERVER_URL, QR_URL, CONVERT_HEIC, REQUIRE_AUTH, AUTH_PIN
    global USE_HTTPS, REQUIRE_APPROVAL, IDLE_MINUTES

    p = argparse.ArgumentParser(description=f"{APP_NAME} — share files over WiFi")
    p.add_argument("--dir", help="folder to save files into")
    p.add_argument("--port", type=int, default=DEFAULT_PORT, help="port (default 8765)")
    p.add_argument("--no-browser", action="store_true", help="don't auto-open the browser")
    p.add_argument("--no-heic", action="store_true", help="don't auto-convert HEIC to JPG")
    p.add_argument("--pin", help="set a fixed access code (default: random each run)")
    p.add_argument("--no-auth", action="store_true",
                   help="disable the access code (trusted networks only)")
    p.add_argument("--https", action="store_true",
                   help="encrypt with a self-signed certificate (one-time trust prompt)")
    p.add_argument("--approve", action="store_true",
                   help="ask you to allow each new device before it can connect")
    p.add_argument("--idle", type=int, default=0, metavar="MIN",
                   help="auto-stop after MIN minutes with no activity (0 = never)")
    args = p.parse_args()

    CONVERT_HEIC = not args.no_heic
    REQUIRE_AUTH = not args.no_auth
    REQUIRE_APPROVAL = args.approve
    IDLE_MINUTES = max(0, args.idle)
    USE_HTTPS = args.https
    AUTH_PIN = args.pin or ("%06d" % secrets.randbelow(1000000))

    cfg = load_config()
    SAVE_ROOT = (args.dir and os.path.expanduser(args.dir)) \
        or cfg.get("save_dir") or default_save_dir()
    os.makedirs(SAVE_ROOT, exist_ok=True)
    cfg["save_dir"] = SAVE_ROOT
    save_config(cfg)

    server, port = find_server(args.port)
    ip = lan_ip()

    global SSL_CONTEXT
    scheme = "http"
    if USE_HTTPS:
        certf, keyf = ensure_cert(ip)
        if certf:
            ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            ctx.load_cert_chain(certf, keyf)
            SSL_CONTEXT = ctx            # handshake happens per-connection in Handler.setup()
            scheme = "https"
        else:
            print("  ⚠  Could not create a certificate — falling back to HTTP (no encryption).")
            USE_HTTPS = False

    SERVER_URL = f"{scheme}://{ip}:{port}"
    QR_URL = f"{SERVER_URL}/?k={AUTH_PIN}" if REQUIRE_AUTH else SERVER_URL

    bar = "=" * 56
    print(bar)
    print(f"  📸  {APP_NAME} — WiFi file hub is running")
    print(bar)
    print("  Open this on any phone/computer on the SAME WiFi:\n")
    print(f"        {SERVER_URL}\n")
    if REQUIRE_AUTH:
        print("  🔒 Access code (type it on the phone, or just scan the QR):\n")
        print(f"        {AUTH_PIN}\n")
    sec = []
    sec.append("encrypted (HTTPS)" if USE_HTTPS else "not encrypted (HTTP)")
    if REQUIRE_APPROVAL:
        sec.append("new devices need your approval")
    if IDLE_MINUTES:
        sec.append(f"auto-stops after {IDLE_MINUTES} min idle")
    print(f"  Security: {', '.join(sec)}.")
    if USE_HTTPS:
        print("  (First visit shows a 'not private' warning — tap Advanced → Proceed; it's your own cert.)")
    print(f"  Files saved to: {SAVE_ROOT}{os.sep}<date>{os.sep}")
    print(f"  Activity log:   {LOG_FILE}\n")
    qr_terminal(QR_URL)
    print("  Tip: on the phone, 'Add to Home Screen' to install it like an app.")
    print("  Press Ctrl+C to stop.")
    print(bar)

    threading.Thread(target=idle_watchdog, args=(server,), daemon=True).start()
    if REQUIRE_APPROVAL:
        threading.Thread(target=approval_worker, daemon=True).start()

    if not args.no_browser:
        try:
            webbrowser.open(QR_URL)
        except Exception:
            pass
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n  Stopped. Bye!")
        server.shutdown()


if __name__ == "__main__":
    main()
