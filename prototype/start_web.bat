@echo off
rem Starts the Loan Lifecycle web app on http://localhost:8000
rem Keys are loaded from .env.local if it exists, otherwise set them here.
cd /d "%~dp0"

rem Load .env.local if present (never commit that file)
if exist .env.local (
    for /f "usebackq tokens=1,* delims==" %%A in (".env.local") do (
        if not "%%A"=="" if not "%%A:~0,1%"=="#" set "%%A=%%B"
    )
)

python -m pip install -q -r web\requirements.txt
start "" http://localhost:8000
python -m uvicorn web.app:app --host 0.0.0.0 --port 8000
