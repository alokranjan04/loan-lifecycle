@echo off
rem Starts the agentic workbench API for the Northstar portal on 127.0.0.1:8001.
rem Sign in through the Northstar administrator portal on port 8000 first.
cd /d "%~dp0"

rem Load .env.local if present (never commit that file)
if exist .env.local (
    for /f "usebackq tokens=1,* delims==" %%A in (".env.local") do (
        if not "%%A"=="" if not "%%A:~0,1%"=="#" set "%%A=%%B"
    )
)

python -m pip install -q -r web\requirements.txt
python -m uvicorn web.app:app --host 127.0.0.1 --port 8001
