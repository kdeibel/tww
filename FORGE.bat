@echo off
title Decomp Forge - Wind Waker
cd /d "%~dp0"
echo Starting Decomp Forge...
start "" http://localhost:7878
python forge\forge.py serve
pause
