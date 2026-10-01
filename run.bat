@echo off
REM Photo Transfer - Windows launcher.
REM Tries a virtual environment for the optional QR library, but falls back to
REM running directly. The app has NO required dependencies, so it always runs.
cd /d "%~dp0"

where python >nul 2>nul && (set PY=python) || (set PY=py)
set RUNPY=%PY%

if not exist .venv (
  %PY% -m venv .venv >nul 2>nul
)
if exist .venv\Scripts\python.exe (
  set RUNPY=.venv\Scripts\python.exe
)

REM Optional: install 'segno' for the on-screen QR image. Best-effort only.
%RUNPY% -c "import segno" >nul 2>nul || %RUNPY% -m pip install -q --disable-pip-version-check segno >nul 2>nul

%RUNPY% app.py %*
pause
