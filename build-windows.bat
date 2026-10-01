@echo off
REM Build a standalone, double-clickable "Photo Transfer" app for Windows.
REM Run this on a Windows machine. Produces: dist\PhotoTransfer\PhotoTransfer.exe
cd /d "%~dp0"

python -m pip install -q segno pyinstaller pillow

REM Make a .ico from icon.png for a nice app icon (best-effort).
python -c "from PIL import Image; Image.open('icon.png').save('icon.ico', sizes=[(256,256),(128,128),(64,64),(32,32),(16,16)])" 2>nul

python -m PyInstaller --noconfirm --onedir --windowed ^
  --name PhotoTransfer ^
  --hidden-import segno ^
  --icon icon.ico ^
  app.py

echo.
echo Done -^> dist\PhotoTransfer\
echo Share the whole 'PhotoTransfer' folder (or zip it). The user double-clicks PhotoTransfer.exe
pause
