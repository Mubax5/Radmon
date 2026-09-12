@echo off
setlocal EnableExtensions
cd /d "%~dp0"
set RADMON_LAN_ENABLED=1
set "RADMON_CENTRAL_PID_FILE=%~dp0runtime\radmon-central.pid"
call :bootstrap || exit /b 1
call :grafana
call :central || exit /b 1
start "" /wait "%~dp0.venv\Scripts\pythonw.exe" "%~dp0main.py" --source lan
set "RADMON_ADMIN_EXIT=%ERRORLEVEL%"
call :stop_central
exit /b %RADMON_ADMIN_EXIT%

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
".venv\Scripts\python.exe" -c "import PySide6, pyqtgraph, mariadb, fastapi, uvicorn, reportlab, serial, httpx, dotenv, selenium, tzdata" >nul 2>&1
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
call :central_ready
if not errorlevel 1 (
  call :capture_central_pid || exit /b 1
  exit /b 0
)
call :port_open
if not errorlevel 1 (
  echo [RadMon] Port 8090 dipakai proses lama. Memeriksa apakah ini RadMon Central stale...
  call :recover_stale_central
  if errorlevel 1 (
    echo [RadMon] Port 8090 dipakai proses lain atau proses RadMon tidak dapat dihentikan dengan aman.
    echo [RadMon] Tutup proses konflik lalu jalankan RUN_LAN.bat lagi.
    pause
    exit /b 1
  )
)
echo [RadMon] Menjalankan central collector/API tunggal di port 8090...
start "RadMon Central" "%~dp0.venv\Scripts\python.exe" "%~dp0central_server.py" --host 0.0.0.0 --port 8090
for /L %%I in (1,1,30) do (
  call :central_ready
  if not errorlevel 1 (
    call :capture_central_pid || exit /b 1
    exit /b 0
  )
  timeout /t 1 /nobreak >nul
)
echo [RadMon] Central server belum siap sebagai owner LAN di port 8090.
pause
exit /b 1

:capture_central_pid
if not exist "%~dp0runtime" mkdir "%~dp0runtime" >nul 2>&1
powershell.exe -NoProfile -NonInteractive -Command "$c=Get-NetTCPConnection -State Listen -LocalPort 8090 -ErrorAction SilentlyContinue ^| Select-Object -First 1; if(-not $c){exit 1}; Set-Content -LiteralPath $env:RADMON_CENTRAL_PID_FILE -Value $c.OwningProcess -Encoding ascii" >nul 2>&1
exit /b %ERRORLEVEL%

:recover_stale_central
call :capture_central_pid || exit /b 1
set "RADMON_CENTRAL_PID="
set /p RADMON_CENTRAL_PID=<"%RADMON_CENTRAL_PID_FILE%"
powershell.exe -NoProfile -NonInteractive -Command "$p=Get-CimInstance Win32_Process -Filter ('ProcessId=' + $env:RADMON_CENTRAL_PID) -ErrorAction SilentlyContinue; if(-not $p){exit 1}; if(($p.CommandLine -as [string]) -notmatch 'central_server\.py'){exit 2}; exit 0" >nul 2>&1
if errorlevel 1 exit /b 1
call :stop_central
for /L %%I in (1,1,20) do (
  call :port_open
  if errorlevel 1 exit /b 0
  timeout /t 1 /nobreak >nul
)
exit /b 1

:stop_central
if not exist "%RADMON_CENTRAL_PID_FILE%" exit /b 0
set "RADMON_CENTRAL_PID="
set /p RADMON_CENTRAL_PID=<"%RADMON_CENTRAL_PID_FILE%"
if not defined RADMON_CENTRAL_PID (
  del /q "%RADMON_CENTRAL_PID_FILE%" >nul 2>&1
  exit /b 0
)
powershell.exe -NoProfile -NonInteractive -Command "$p=Get-CimInstance Win32_Process -Filter ('ProcessId=' + $env:RADMON_CENTRAL_PID) -ErrorAction SilentlyContinue; if(-not $p){exit 0}; if(($p.CommandLine -as [string]) -notmatch 'central_server\.py'){exit 2}; Stop-Process -Id ([int]$env:RADMON_CENTRAL_PID) -ErrorAction SilentlyContinue; Start-Sleep -Milliseconds 750; if(Get-Process -Id ([int]$env:RADMON_CENTRAL_PID) -ErrorAction SilentlyContinue){Stop-Process -Id ([int]$env:RADMON_CENTRAL_PID) -Force -ErrorAction SilentlyContinue}" >nul 2>&1
set "RADMON_STOP_RC=%ERRORLEVEL%"
if "%RADMON_STOP_RC%"=="0" del /q "%RADMON_CENTRAL_PID_FILE%" >nul 2>&1
exit /b %RADMON_STOP_RC%

:central_ready
".venv\Scripts\python.exe" -c "import json, urllib.request; d=json.load(urllib.request.urlopen('http://127.0.0.1:8090/health', timeout=1.0)); raise SystemExit(0 if d.get('service') == 'radmon-central' and d.get('status') == 'ok' and d.get('lan_enabled') is True else 1)" >nul 2>&1
if errorlevel 1 exit /b 1
exit /b 0

:port_open
".venv\Scripts\python.exe" -c "import socket; s=socket.socket(); s.settimeout(.5); r=s.connect_ex(('127.0.0.1',8090)); s.close(); raise SystemExit(0 if r == 0 else 1)" >nul 2>&1
if errorlevel 1 exit /b 1
exit /b 0
