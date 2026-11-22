@echo off
chcp 65001 >nul
title Kariyer Otonomu (Ali Cavlak)
cd /d "%~dp0"

if not exist "venv\Scripts\streamlit.exe" (
    echo [UYARI] Kurulum henuz yapilmamis!
    echo Once "windows_kurulum.bat" dosyasina cift tiklayip kurulumu tamamlayin.
    echo.
    pause
    exit /b 1
)

echo ============================================================================
echo  KARIYER OTONOMU BASLATILIYOR...
echo  Tarayicida otomatik acilmazsa: http://localhost:8501
echo  Kapatmak icin bu pencereyi kapatin veya Ctrl+C tusuna basin.
echo  (c) 2026 Ali Cavlak tarafindan yapilmistir. Tum telif haklari ona aittir.
echo ============================================================================
echo.

venv\Scripts\streamlit.exe run app/dashboard.py
pause
