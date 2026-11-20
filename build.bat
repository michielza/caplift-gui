@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0"

echo == Caplift UI build ==
echo.

if not exist ".venv\Scripts\python.exe" (
    echo [1/4] Creating virtual environment...
    python -m venv .venv || goto :error
) else (
    echo [1/4] Virtual environment present.
)

echo [2/4] Installing dependencies...
".venv\Scripts\python.exe" -m pip install --upgrade pip --quiet || goto :error
".venv\Scripts\python.exe" -m pip install -r requirements-dev.txt --quiet || goto :error

echo [3/4] Running tests...
".venv\Scripts\python.exe" -m unittest discover -s tests -t . --quiet || goto :error

echo [4/4] Building executable...
".venv\Scripts\python.exe" -m PyInstaller --noconfirm --clean main.spec || goto :error

echo.
echo Built: %CD%\dist\caplift-ui.exe

if /i "%~1"=="deploy" (
    echo Deploying next to lmstudio-caplift.exe...
    copy /y "dist\caplift-ui.exe" "..\caplift-ui.exe" >nul || goto :error
    echo Copied to ..\caplift-ui.exe
)

echo.
echo Done. Place caplift-ui.exe in the same folder as lmstudio-caplift.exe.
goto :eof

:error
echo.
echo BUILD FAILED.
exit /b 1
