@echo off
cd /d "%~dp0\.."
if exist .venv\Scripts\activate.bat call .venv\Scripts\activate.bat
python sync_agent.py --interval 2
pause
