@echo off
chcp 65001 >nul
title Kariyer Otonomu - GitHub Guncelleme (Ali Cavlak)
cd /d "%~dp0"

echo ============================================================================
echo  KARIYER OTONOMU - GITHUB'DAN GUNCELLEME
echo  (c) 2026 Ali Cavlak tarafindan yapilmistir. Tum telif haklari ona aittir.
echo ============================================================================
echo.

where git >nul 2>nul
if %errorlevel% neq 0 (
    echo [HATA] Git kurulu degil! https://git-scm.com/downloads adresinden kurabilirsiniz.
    pause
    exit /b 1
)

echo [1/2] GitHub'dan son degisiklikler cekiliyor...
git pull origin main
if %errorlevel% neq 0 (
    echo [HATA] Guncelleme alinamadi. Internet baglantinizi veya GitHub yetkinizi kontrol edin.
    pause
    exit /b 1
)

if exist "venv\Scripts\pip.exe" (
    echo [2/2] Yeni kutuphane varsa yukleniyor...
    venv\Scripts\pip.exe install -r requirements.txt
)

echo.
echo Guncelleme tamamlandi! "windows_baslat.bat" ile uygulamayi acabilirsiniz.
echo.
pause
