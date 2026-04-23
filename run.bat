@echo off
echo Installing dependencies...
pip install -r requirements.txt
echo.
echo Starting Mini Jarvis on http://localhost:8000
python main.py
