@echo off
:: Move to the directory first
cd /d "c:\study\sf6viewer"

:: Start main.py in a NEW visible window with a specific title
:: "start" command forces a new separate window
start "SF6 Viewer Server" cmd /k "python main.py"

:: This launcher script then exits, leaving the server running in the new window
exit
