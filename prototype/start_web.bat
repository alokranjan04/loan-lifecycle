@echo off
rem Starts the Loan Lifecycle web app on http://localhost:8000
rem Optional: set ANTHROPIC_API_KEY=... in this window first to enable Claude runs.
cd /d "%~dp0"
python -m pip install -q -r web\requirements.txt
start "" http://localhost:8000
python web\app.py
