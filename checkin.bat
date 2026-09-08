@echo off
cd /d %~dp0
".venv\Scripts\python.exe" checkin.py %*
set EXIT_CODE=%ERRORLEVEL%
echo %* | findstr /i "\--no-pause" >nul
if %ERRORLEVEL% equ 0 exit /b %EXIT_CODE%
if defined CI exit /b %EXIT_CODE%
if defined NON_INTERACTIVE exit /b %EXIT_CODE%
pause
exit /b %EXIT_CODE%
