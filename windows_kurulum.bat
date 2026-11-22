@echo off
chcp 65001 >nul
title Kariyer Otonomu - Windows Kurulumu (Ali Cavlak)
cd /d "%~dp0"

echo ============================================================================
echo  KARIYER OTONOMU - WINDOWS OTOMATIK KURULUM
echo  (c) 2026 Ali Cavlak tarafindan yapilmistir. Tum telif haklari ona aittir.
echo ============================================================================
echo.

where python >nul 2>nul
if %errorlevel% neq 0 (
    echo [HATA] Python bulunamadi!
    echo Lutfen https://www.python.org/downloads/ adresinden Python 3.11+ indirin.
    echo Kurulum sirasinda "Add Python to PATH" kutusunu MUTLAKA isaretleyin!
    echo.
    pause
    exit /b 1
)

echo [1/4] Sanal ortam (venv) olusturuluyor...
if not exist "venv\Scripts\python.exe" (
    python -m venv venv
    if %errorlevel% neq 0 (
        echo [HATA] Sanal ortam olusturulamadi.
        pause
        exit /b 1
    )
) else (
    echo       venv zaten mevcut, devam ediliyor.
)

echo [2/4] Gerekli kutuphaneler yukleniyor (birkaç dakika surebilir)...
venv\Scripts\python.exe -m pip install --upgrade pip
venv\Scripts\pip.exe install -r requirements.txt
if %errorlevel% neq 0 (
    echo [HATA] Paketler yuklenirken hata olustu.
    pause
    exit /b 1
)

echo [3/4] Tarayici motoru (Playwright Chromium) kuruluyor...
venv\Scripts\playwright.exe install chromium
if %errorlevel% neq 0 (
    echo [UYARI] Chromium kurulumunda uyari olustu. Bilgisayarda Google Chrome varsa calismaya devam eder.
)

echo [4/4] Yapilandirma (.env) kontrol ediliyor...
if not exist ".env" (
    copy ".env.example" ".env" >nul
    echo       .env dosyasi olusturuldu. API anahtarinizi .env dosyasindan veya Ayarlar sayfasindan girebilirsiniz.
) else (
    echo       .env dosyasi zaten mevcut, korunuyor.
)

echo.
echo ============================================================================
echo  KURULUM TAMAMLANDI!
echo  Uygulamayi baslatmak icin "windows_baslat.bat" dosyasina cift tiklayin.
echo ============================================================================
echo.
pause
