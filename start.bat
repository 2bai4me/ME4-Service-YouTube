@echo off
REM ME4-YouTube — Windows-Start
setlocal

cd /d "%~dp0"

REM .env laden
if exist .env (
    for /f "usebackq tokens=1,2 delims==" %%a in (".env") do (
        if not "%%a"=="" if not "%%a:~0,1%"=="#" set "%%a=%%b"
    )
)

REM Virtuelle Umgebung
if not exist .venv (
    python -m venv .venv
)

call .venv\Scripts\activate.bat

REM Dependencies
python -m pip install --upgrade pip --quiet
pip install -r requirements.txt --quiet

REM Start
python main.py %*
