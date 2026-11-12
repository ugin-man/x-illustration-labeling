@echo off
cd /d "%~dp0"
python -m pipeline.review_app --open
if errorlevel 1 pause
