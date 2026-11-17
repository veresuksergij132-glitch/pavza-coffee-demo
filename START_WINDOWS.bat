@echo off
setlocal
cd /d "%~dp0"
echo =======================================
echo   PAVZA 3.0 - local demo server
echo =======================================
where py >nul 2>nul
if %errorlevel%==0 (
  set PYTHON=py
) else (
  set PYTHON=python
)
%PYTHON% -m pip install -r requirements.txt
if errorlevel 1 (
 echo.
 echo Python / pip not found. Please install Python 3.11+.
 pause
 exit /b 1
)
echo.
echo Site:   http://127.0.0.1:8000/
echo Admin:  http://127.0.0.1:8000/admin.html
echo Password file after first launch: .pavza-data\initial-admin-password.txt
echo Stop server with Ctrl+C.
echo.
start "" http://127.0.0.1:8000/
%PYTHON% -m uvicorn server:app --host 127.0.0.1 --port 8000
pause
