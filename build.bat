@echo off
echo Installing PyInstaller...
pip install pyinstaller

echo Building SF6 Viewer...
pyinstaller --noconfirm --onedir --windowed --add-data "static;static" --name "SF6Viewer" main.py

echo Build complete!
echo The executable is located in the 'dist' folder.
pause
