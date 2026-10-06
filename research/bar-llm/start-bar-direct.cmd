@echo off
cd /d "%~dp0"
call setup-bar-swarm.cmd
if errorlevel 1 goto done
bar_duel\.venv\Scripts\python.exe bar_duel\run.py --control direct --local-mode swarm
:done
pause
