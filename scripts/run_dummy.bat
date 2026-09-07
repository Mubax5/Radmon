@echo off
cd /d "%~dp0\.."
if exist .venv\Scripts\activate.bat call .venv\Scripts\activate.bat
python dummy_measurement.py --mode mixed --interval 2
pause
