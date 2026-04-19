@echo off
setlocal

echo Checking for prerequisites...
where python >nul 2>nul
if %errorlevel% neq 0 (
    echo Python is not installed or not in your PATH!
    echo Please install Python 3.x+ ^(https://www.python.org/downloads/^) and try again.
    pause
    exit /b 1
)

where ffmpeg >nul 2>nul
if %errorlevel% neq 0 (
    echo FFmpeg is not installed or not in your PATH!
    echo Please install FFmpeg, add it to your PATH, and try again.
    echo ^(You can download it from https://ffmpeg.org/download.html^)
    pause
    exit /b 1
)

if not exist venv (
    echo.
    echo Setting up virtual environment...
    python -m venv venv
)

echo.
echo Activating virtual environment and installing requirements...
call venv\Scripts\activate.bat
pip install -q -r requirements.txt

:: Set default port if not provided
if "%PORT%"=="" set PORT=8899

echo.
echo =======================================================
echo   ReClip is running at http://localhost:%PORT%
echo =======================================================
echo.

python app.py
pause
