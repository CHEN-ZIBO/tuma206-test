@echo off
chcp 65001 >nul
title Intelligent Beverage Production Line

cd /d "%~dp0TUMA206-main"

echo.
echo ╔══════════════════════════════════════════╗
echo ║  🏭  Intelligent Production Line       ║
echo ║  Starting Dashboard, please wait...    ║
echo ╚══════════════════════════════════════════╝
echo.

start "" http://localhost:5678

streamlit run dashboard/app.py --server.port 5678 --server.headless true

pause
