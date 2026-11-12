@echo off
cd /d "%~dp0"
python -m pipeline.screening_app --open
if errorlevel 1 pause
