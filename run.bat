@echo off
REM ============================================================================
REM Mini Audio Editor - Quick Launch Script
REM CSE220 Signals & Linear Systems Project
REM ============================================================================

echo.
echo ====================================================================
echo   Mini Audio Editor - CSE220 Project
echo ====================================================================
echo.

REM Check if Python is installed
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python is not installed or not in PATH.
    echo Please install Python 3.8+ and try again.
    pause
    exit /b 1
)

echo [1/3] Checking dependencies...

REM Check if requirements are installed (test for Flask)
python -c "import flask" >nul 2>&1
if errorlevel 1 (
    echo.
    echo Dependencies not found. Installing from requirements.txt...
    echo.
    pip install -r requirements.txt
    if errorlevel 1 (
        echo.
        echo [ERROR] Failed to install dependencies.
        pause
        exit /b 1
    )
) else (
    echo Dependencies OK
)

echo.
echo [2/3] Checking for test audio file...

if not exist "test_audio.wav" (
    echo Generating test audio file...
    python generate_test_audio.py
) else (
    echo Test audio file already exists
)

echo.
echo [3/3] Starting Mini Audio Editor...
echo.
echo ====================================================================
echo   Server will start at http://localhost:5000
echo   Press Ctrl+C to stop the server
echo ====================================================================
echo.

REM Start the Flask application
python app.py

pause
