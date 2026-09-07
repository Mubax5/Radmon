@echo off
cd /d "%~dp0\.."
if exist .venv\Scripts\activate.bat call .venv\Scripts\activate.bat
python public_app.py --host 0.0.0.0 --port 8080
pause
