@echo off
cd /d "%~dp0\.."
if exist .venv\Scripts\activate.bat call .venv\Scripts\activate.bat
python central_server.py --host 0.0.0.0 --port 8090
pause
