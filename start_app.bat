@echo off
echo =======================================================
echo   Compliance Tracker - Service Agent Startup Script
echo =======================================================
echo.
echo Starting FastAPI Backend on port 8000...
start "FastAPI Backend" cmd /k "python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload"

timeout /t 2 >nul

echo Starting Streamlit Dashboard on port 8501...
start "Streamlit Dashboard" cmd /k "python -m streamlit run app_ui.py --server.port=8501"

echo.
echo =======================================================
echo   Services Launched!
echo   Web UI: http://localhost:8501
echo   API Docs: http://127.0.0.1:8000/docs
echo =======================================================
