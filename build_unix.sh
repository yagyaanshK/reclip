#!/bin/bash
set -e

echo "Installing dependencies..."
pip install -r requirements.txt

echo "Building ReClip app..."
# Note the use of ':' instead of ';' for path separation in unix
pyinstaller --noconfirm --onedir --windowed --add-data "templates:templates" --add-data "static:static" --name "ReClip" app.py

echo ""
echo "Build complete! You can find the ReClip executable inside the 'dist/ReClip' folder."
