@echo off
setlocal
cd /d "%~dp0"

echo ================================================
echo   RADMON DPFK - WINDOWS SETUP
echo ================================================

py -3 --version >nul 2>&1
if errorlevel 1 (
  python --version >nul 2>&1
  if errorlevel 1 (
    echo [ERROR] Python 3 tidak ditemukan di PATH.
    echo Install Python 3.11+ lalu centang "Add python.exe to PATH".
    exit /b 1
  )
  set "PY_LAUNCHER=python"
) else (
  set "PY_LAUNCHER=py -3"
)

if not exist ".venv\Scripts\python.exe" (
  echo [1/3] Membuat virtual environment .venv ...
  %PY_LAUNCHER% -m venv .venv
  if errorlevel 1 exit /b 1
) else (
  echo [1/3] Virtual environment sudah ada.
)

echo [2/3] Install / update dependency dari requirements.txt ...
".venv\Scripts\python.exe" -m pip install --upgrade pip
if errorlevel 1 exit /b 1
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 exit /b 1

if not exist ".env" (
  echo [3/3] Membuat .env dari .env.example ...
  copy /Y ".env.example" ".env" >nul
) else (
  echo [3/3] .env sudah ada - tidak ditimpa.
)

echo.
echo Setup selesai.
echo Edit .env kalau konfigurasi COM, database, atau token server pusat berbeda.
echo Lanjutkan dengan START_COMMON.bat lalu pilih SATU writer:
echo   RUN_DUMMY.bat    atau    RUN_DETECTOR.bat
exit /b 0
