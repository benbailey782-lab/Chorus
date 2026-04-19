@echo off
setlocal
cd /d "%~dp0\.."

if not exist .venv (
    python -m venv .venv
)
call .venv\Scripts\activate.bat

pip install -q -r requirements.txt

if not exist frontend\node_modules (
    pushd frontend
    call npm install
    popd
)

start "chorus-frontend" cmd /c "cd frontend && npm run dev -- --host 0.0.0.0"
start "chorus-backend" cmd /c "uvicorn backend.main:app --host 0.0.0.0 --port 8765 --reload"

timeout /t 3 >nul
start "" http://localhost:5173
