@echo off
setlocal
cd /d "%~dp0"

echo ================================================
echo   RADMON DPFK - COMMON SERVICES
echo ================================================

if not exist ".venv\Scripts\python.exe" (
  echo .venv belum tersedia. Menjalankan SETUP_WINDOWS.bat ...
  call "%~dp0SETUP_WINDOWS.bat"
  if errorlevel 1 exit /b 1
)

if not exist ".env" (
  copy /Y ".env.example" ".env" >nul
  echo .env dibuat dari .env.example. Silakan review konfigurasinya.
)

echo Starting central server ...
start "RADMON CENTRAL" cmd /k call "%~dp0scripts\run_central.bat"
timeout /t 1 /nobreak >nul

echo Starting public fullscreen monitoring ...
start "RADMON PUBLIC" cmd /k call "%~dp0scripts\run_public.bat"

echo Starting sync agent ...
start "RADMON SYNC" cmd /k call "%~dp0scripts\run_sync.bat"

echo Starting admin desktop ...
start "RADMON ADMIN" cmd /k call "%~dp0scripts\run_admin.bat"

echo.
echo Common services aktif.
echo Public monitoring : http://127.0.0.1:8080
echo Central API       : http://127.0.0.1:8090
echo.
echo PENTING: START_COMMON tidak menjalankan writer measurement.
echo Jalankan salah satu saja: RUN_DUMMY.bat ATAU RUN_DETECTOR.bat.
exit /b 0
