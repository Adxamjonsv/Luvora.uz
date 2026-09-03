@echo off
title Luvora Mini App - Tunnel
cd /d "%~dp0"
echo ============================================
echo   Luvora Mini App uchun HTTPS tunnel
echo ============================================
echo.

if not exist cloudflared.exe (
  echo cloudflared topilmadi - yuklab olinmoqda ^(bir marta, ~30 MB^)...
  powershell -NoProfile -Command "[Net.ServicePointManager]::SecurityProtocol=[Net.SecurityProtocolType]::Tls12; try { Invoke-WebRequest -Uri 'https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-windows-amd64.exe' -OutFile 'cloudflared.exe' } catch { Write-Host 'YUKLASH XATO:' $_.Exception.Message; exit 1 }"
)

if not exist cloudflared.exe (
  echo.
  echo Yuklab bo'lmadi. Internetni tekshir yoki qo'lda yukla:
  echo https://github.com/cloudflare/cloudflared/releases/latest
  echo.
  pause
  exit /b
)

echo.
echo Tunnel ochilmoqda ^(port 8080^)...
echo Chiqadigan https://...trycloudflare.com manzilini nusxalab,
echo webapp_url.txt fayliga yoz va botni qayta ishga tushir.
echo.
del /q "%~dp0tunnel.log" 2>nul
cloudflared.exe tunnel --url http://localhost:8080 --logfile "%~dp0tunnel.log"

echo.
echo Tunnel yopildi.
pause
