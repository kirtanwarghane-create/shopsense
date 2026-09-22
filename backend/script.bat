@echo off
setlocal

set "BACKEND_DIR=%~dp0"
set "FRONTEND_DIR=%~dp0..\frontend"
set "VENV_ACTIVATE=%~dp0venv\Scripts\activate.bat"

if not exist "%VENV_ACTIVATE%" (
    echo Virtual environment not found: "%VENV_ACTIVATE%"
    echo Create it with: py -m venv "%~dp0venv"
    pause
    exit /b 1
)

start "ShopSense Backend" cmd /k "cd /d "%BACKEND_DIR%" && call "%VENV_ACTIVATE%" && py app.py"
start "ShopSense Frontend" cmd /k py -m http.server 5500 --directory "%FRONTEND_DIR%"

timeout /t 2 /nobreak >nul
start "" "http://localhost:5500"

echo ShopSense is starting.
echo Frontend: http://localhost:5500
echo Backend:  http://localhost:5000
endlocal