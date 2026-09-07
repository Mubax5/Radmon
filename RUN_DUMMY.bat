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
echo   RADMON DPFK - DUMMY WRITER

echo   Station : 5202 - IS-1 Koridor - Gd.52
echo   Default : mixed mode, setiap 2 detik
echo ================================================
echo.
echo JANGAN jalankan bersamaan dengan RUN_DETECTOR.bat.
echo.

if "%~1"=="" (
  start "RADMON DUMMY" cmd /k ""%~dp0.venv\Scripts\python.exe" "%~dp0dummy_measurement.py" --mode mixed --interval 2"
) else (
  start "RADMON DUMMY" cmd /k ""%~dp0.venv\Scripts\python.exe" "%~dp0dummy_measurement.py" %*"
)
exit /b 0
