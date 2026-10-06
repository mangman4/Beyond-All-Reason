@echo off
cd /d "%~dp0"
if not exist "bar_duel\.venv\Scripts\python.exe" (
  py -3 -m venv bar_duel\.venv
  if errorlevel 1 exit /b 1
)
bar_duel\.venv\Scripts\python.exe -c "import langgraph.graph" >nul 2>&1
if errorlevel 1 (
  bar_duel\.venv\Scripts\python.exe -m pip install -r bar_duel\requirements-swarm-lock.txt
  if errorlevel 1 exit /b 1
)
exit /b 0
