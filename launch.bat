@echo off
title Personal AI Voice Studio (Updated 2026-10-24)
cd /d "%~dp0"
echo Starting Personal AI Voice Studio...
call .venv\Scripts\activate.bat
python run.py
pause
