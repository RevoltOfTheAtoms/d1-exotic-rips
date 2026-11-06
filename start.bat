@echo off
rem D1 Exotic Rips: double-click to open the window. Installs the two Python packages it needs on first run.
cd /d "%~dp0"
where py >nul 2>nul
if errorlevel 1 (
  echo Python is not installed. Get Python 3.10 or newer from https://www.python.org/downloads/
  echo ^(tick "Add python.exe to PATH" in the installer^), then double-click start.bat again.
  pause
  exit /b 1
)
py -3 -c "import numpy, PIL" >nul 2>nul || (
  echo Installing the Python packages D1 Exotic Rips needs ^(numpy, pillow^)...
  py -3 -m pip install --disable-pip-version-check -q -r requirements.txt || (pause & exit /b 1)
)
start "" pyw -3 d1rip.py gui
