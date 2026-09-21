@echo off
title AutoCAD AI Automation
setlocal

set "PROJ=C:\RC-Projects\autocad-ai\autocad-ai"
set "PY=%PROJ%\venv\Scripts\python.exe"

if not exist "%PY%" (
  echo.
  echo  Could not find the virtual environment Python at:
  echo    %PY%
  echo.
  echo  If you moved the project, edit PROJ at the top of this file.
  echo.
  pause
  exit /b 1
)

cd /d "%PROJ%"

echo.
echo   AutoCAD AI Automation
echo   =====================
echo   Project  : %PROJ%
echo   Server   : http://127.0.0.1:8000
echo   Chat UI  : http://127.0.0.1:8000/sketch.html
echo   COM check: http://127.0.0.1:8000/api/autocad-status
echo.
echo   Open AutoCAD with a drawing before you press Build in AutoCAD.
echo   Leave this window open. Press Ctrl+C to stop the server.
echo.

start "" /min powershell -NoProfile -Command "Start-Sleep -Seconds 6; Start-Process 'http://127.0.0.1:8000/sketch.html'"

"%PY%" -m uvicorn src.api.main:app --host 127.0.0.1 --port 8000

echo.
echo   Server stopped.
pause
