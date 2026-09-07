@echo off
setlocal
cd /d "%~dp0"
call :bootstrap || exit /b 1
start "" "%~dp0.venv\Scripts\pythonw.exe" "%~dp0main.py" --source detector
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
".venv\Scripts\python.exe" -c "import PySide6, mariadb, fastapi, uvicorn, reportlab, serial, httpx, dotenv" >nul 2>&1
if errorlevel 1 (
  echo Menyiapkan dependency Radmon. Proses ini hanya lama pada first run...
  ".venv\Scripts\python.exe" -m pip install -r requirements.txt
  if errorlevel 1 (
    echo Gagal install dependency.
    pause
    exit /b 1
  )
)
if not exist ".env" copy /Y ".env.example" ".env" >nul
exit /b 0
