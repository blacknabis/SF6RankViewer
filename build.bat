@echo off
echo Installing PyInstaller...
pip install pyinstaller

echo Building SF6 Viewer...
pyinstaller --noconfirm --onedir --noupx --add-data "static;static" --name "SF6Viewer" --exclude-module PyQt5 --exclude-module PyQt6 --exclude-module tkinter main.py

echo Build complete!
echo The executable is located in the 'dist' folder.
pause
