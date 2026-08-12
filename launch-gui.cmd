@echo off
cd /d "%~dp0"
start "" pythonw.exe "%~dp0app.py" --config "%~dp0config\app.json"
