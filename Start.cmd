@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  py -3.11 -m venv .venv
  if errorlevel 1 goto failed
)
if not exist ".venv\ready.txt" (
  .venv\Scripts\python.exe -m pip install -r requirements.txt
  if errorlevel 1 goto failed
  echo ready>.venv\ready.txt
)
.venv\Scripts\python.exe app.py
if errorlevel 1 goto failed
exit /b 0
:failed
echo.
echo Setup or launch failed. Install Python 3.11 from python.org if missing.
echo Internet is required for the first setup. See the error above.
pause
exit /b 1
