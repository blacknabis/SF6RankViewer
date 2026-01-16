@echo off
title Stop SF6 Viewer Server
echo Stopping SF6 Viewer Server...

:: Kill all python processes originating from this app context (or generally python.exe/main.py if specific PID tracking isn't available)
:: Since we are in a dedicated environment, killing python.exe is the most reliable way to ensure it stops.
taskkill /F /IM python.exe /T

echo.
echo Server stopped successfully.
timeout /t 2 >nul
