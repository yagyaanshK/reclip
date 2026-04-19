@echo off
setlocal

echo Installing dependencies...
pip install -r requirements.txt

echo Building ReClip app...
REM --noconfirm overwrites previous builds
REM --onedir creates a folder containing the executable and dependencies
REM --windowed hides the command prompt window
REM --add-data bundles the HTML/CSS template folders
pyinstaller --noconfirm --onedir --windowed --add-data "templates;templates" --add-data "static;static" --name "ReClip" app.py

echo.
echo Build complete! You can find ReClip.exe inside the "dist\ReClip" folder.
pause
