@echo off
cd /d "%~dp0"
py -3 bar_duel\run.py --control direct --local-mode single
pause
