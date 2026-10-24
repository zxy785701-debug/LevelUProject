@echo off
setlocal
pushd "%~dp0"
if errorlevel 1 exit /b 1
"%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe" -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\start.ps1" %*
set "LEVELUP_START_EXIT=%ERRORLEVEL%"
popd
if not "%LEVELUP_START_EXIT%"=="0" (
    echo.
    echo LevelUp could not start. Read the error above and the logs in backend\logs and frontend\logs.
    if "%~1"=="" pause
)
endlocal & exit /b %LEVELUP_START_EXIT%
