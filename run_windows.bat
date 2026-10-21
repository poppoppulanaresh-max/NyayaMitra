@echo off
setlocal
cd /d "%~dp0"

where python >nul 2>&1
if errorlevel 1 (
  echo Python was not found on PATH. Install Python 3.10 or 3.11 and try again.
  pause
  exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
  echo Creating virtual environment...
  python -m venv .venv
  if errorlevel 1 (
    echo Could not create .venv. Check that Python 3.10+ is installed.
    pause
    exit /b 1
  )
)

call ".venv\Scripts\activate.bat"
if errorlevel 1 (
  echo Could not activate the virtual environment.
  pause
  exit /b 1
)

python -m pip install --upgrade pip
if errorlevel 1 (
  echo pip upgrade failed.
  pause
  exit /b 1
)

python -m pip install -r requirements.txt
if errorlevel 1 (
  echo Dependency installation failed. See the messages above.
  pause
  exit /b 1
)

if not exist ".env" (
  if exist ".env.example" copy ".env.example" ".env" >nul
  echo A local .env file was created from .env.example. Edit it privately if you need an API key or admin password.
)

echo Starting Nyaya Mitra...
python -m streamlit run app.py
if errorlevel 1 (
  echo Streamlit failed to start. See the messages above.
  pause
  exit /b 1
)
pause
