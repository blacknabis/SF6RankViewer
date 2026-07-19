@echo off
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\pyinstaller.exe" (
    echo [ERROR] PyInstaller is missing from .venv.
    echo Run: uv sync --dev
    exit /b 1
)

echo Building SF6Viewer.exe...
".venv\Scripts\pyinstaller.exe" --noconfirm --clean "packaging\sf6viewer.spec"
if errorlevel 1 exit /b %errorlevel%

echo.
echo Build complete: %CD%\dist\SF6Viewer.exe
endlocal
