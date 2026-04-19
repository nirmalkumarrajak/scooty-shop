@echo off
REM ============================================================
REM   ScootyBazaar - One-click setup for Windows
REM   This script: creates venv -> installs requirements -> runs app
REM ============================================================

echo.
echo ==========================================
echo   ScootyBazaar Setup (Windows)
echo ==========================================
echo.

REM Check if Python is installed
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python is not installed or not in PATH.
    echo Please install Python 3.8+ from https://www.python.org/downloads/
    pause
    exit /b 1
)

REM Create venv if it doesn't exist
if not exist "venv\" (
    echo [1/3] Creating virtual environment...
    python -m venv venv
    if errorlevel 1 (
        echo [ERROR] Failed to create venv.
        pause
        exit /b 1
    )
) else (
    echo [1/3] Virtual environment already exists - skipping.
)

REM Activate venv
echo [2/3] Activating virtual environment...
call venv\Scripts\activate.bat

REM Install requirements
echo [3/3] Installing dependencies...
pip install --upgrade pip --quiet
pip install -r requirements.txt

echo.
echo ==========================================
echo   Setup complete! Starting ScootyBazaar...
echo ==========================================
echo.
echo   Website: http://127.0.0.1:5000
echo   Admin:   http://127.0.0.1:5000/admin/login
echo            username: admin  /  password: admin123
echo.
echo   Press Ctrl+C to stop the server
echo ==========================================
echo.

python app.py
pause
