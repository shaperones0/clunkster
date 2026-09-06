@echo off
setlocal

set "OUTPUT_ZIP=release.zip"
set "TARGETS=main.py clunkster data requirements.txt"

git archive --format=zip --output="%OUTPUT_ZIP%" HEAD %TARGETS%

if %errorlevel% equ 0 (
    echo.
    echo dun
) else (
    echo.
    echo faile :(
)

pause
