@echo off
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
  echo .venv belum tersedia. Jalankan SETUP_WINDOWS.bat terlebih dahulu.
  pause
  exit /b 1
)

if not exist ".env" copy /Y ".env.example" ".env" >nul

echo ================================================
echo   RADMON DPFK - REAL DETECTOR WRITER

echo   Entry point : main.py

echo   Serial      : mengikuti .env (default COM15 / 2400)
echo ================================================
echo.
echo JANGAN jalankan bersamaan dengan RUN_DUMMY.bat.
echo.

start "RADMON DETECTOR" cmd /k ""%~dp0.venv\Scripts\python.exe" "%~dp0main.py""
exit /b 0
