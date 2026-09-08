@echo off
setlocal
cd /d "%~dp0"
set RADMON_LAN_ENABLED=1
call :bootstrap || exit /b 1
call :grafana
call :central || exit /b 1
start "" "%~dp0.venv\Scripts\pythonw.exe" "%~dp0main.py" --source lan
exit /b 0

:bootstrap
if not exist ".venv\Scripts\python.exe" (
  py -3 --version >nul 2>&1
  if errorlevel 1 (
    python --version >nul 2>&1 || (
      echo Python 3 tidak ditemukan.
      pause
      exit /b 1
    )
    python -m venv .venv
  ) else (
    py -3 -m venv .venv
  )
  if errorlevel 1 (
    echo Gagal membuat virtual environment.
    pause
    exit /b 1
  )
)
".venv\Scripts\python.exe" -c "import PySide6, pyqtgraph, mariadb, fastapi, uvicorn, reportlab, serial, httpx, dotenv, selenium" >nul 2>&1
if errorlevel 1 (
  echo Menyiapkan dependency Radiation Monitoring. Proses first run dapat memerlukan beberapa menit...
  ".venv\Scripts\python.exe" -m pip install -r requirements.txt
  if errorlevel 1 (
    echo Gagal install dependency.
    pause
    exit /b 1
  )
)
if not exist ".env" copy /Y ".env.example" ".env" >nul
exit /b 0

:grafana
where docker >nul 2>&1 || (
  echo [RadMon] Docker belum tersedia. Admin akan mencoba Grafana auto-setup lagi saat Monitoring dibuka.
  exit /b 0
)
docker info >nul 2>&1 || (
  echo [RadMon] Docker Desktop belum aktif. Admin tetap dijalankan.
  exit /b 0
)
if not defined RADMON_GRAFANA_PORT set RADMON_GRAFANA_PORT=3300
docker compose --env-file ".env" -f "grafana\docker-compose.yml" up -d
if errorlevel 1 echo [RadMon] Grafana belum berhasil start; Admin akan menampilkan status setup.
exit /b 0

:central
".venv\Scripts\python.exe" -c "import socket; s=socket.socket(); s.settimeout(.5); r=s.connect_ex(('127.0.0.1',8090)); s.close(); raise SystemExit(0 if r == 0 else 1)" >nul 2>&1
if not errorlevel 1 exit /b 0
echo [RadMon] Menjalankan central collector/API tunggal di port 8090...
start "RadMon Central" "%~dp0.venv\Scripts\python.exe" "%~dp0central_server.py" --host 0.0.0.0 --port 8090
for /L %%I in (1,1,30) do (
  ".venv\Scripts\python.exe" -c "import socket; s=socket.socket(); s.settimeout(.5); r=s.connect_ex(('127.0.0.1',8090)); s.close(); raise SystemExit(0 if r == 0 else 1)" >nul 2>&1 && exit /b 0
  timeout /t 1 /nobreak >nul
)
echo [RadMon] Central server belum siap di port 8090.
pause
exit /b 1
