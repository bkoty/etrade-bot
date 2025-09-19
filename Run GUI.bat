@echo off
REM Cross-platform Windows launcher
SETLOCAL
set HERE=%~dp0
if not exist "%HERE%\.venv" (
    py -3 -m venv "%HERE%\.venv"
)
call "%HERE%\.venv\Scripts\python.exe" -m pip install --upgrade pip wheel setuptools
if exist "%HERE%\requirements.txt" (
    call "%HERE%\.venv\Scripts\pip.exe" install -r "%HERE%\requirements.txt"
)
call "%HERE%\.venv\Scripts\python.exe" "%HERE%\gui.py"
