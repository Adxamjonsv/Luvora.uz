@echo off
chcp 65001 >nul
title LUVORA - Ishga tushirish
cd /d "%~dp0"
echo ============================================
echo    LUVORA  --  hammasi bitta bosishda
echo ============================================
echo.

REM --- Avval tekshir: bot allaqachon ishlayaptimi? (8080 band) ---
netstat -ano | findstr ":8080" | findstr "LISTENING" >nul && (
  echo [!] Bot allaqachon ishlayapti ^(8080-port band^).
  echo     Agar PyCharm da ishlatayotgan bo'lsangiz - shu yetarli, bu faylni yoping.
  echo     START.bat bilan ishlatmoqchi bo'lsangiz - avval PyCharm dagi botni to'xtating.
  echo.
  pause
  exit /b
)

REM --- cloudflared bor-yo'qligini tekshir, bo'lmasa yukla ---
if not exist cloudflared.exe (
  echo cloudflared yuklab olinmoqda ^(bir marta, ~30 MB^)...
  powershell -NoProfile -Command "[Net.ServicePointManager]::SecurityProtocol=[Net.SecurityProtocolType]::Tls12; try { Invoke-WebRequest -Uri 'https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-windows-amd64.exe' -OutFile 'cloudflared.exe' } catch { Write-Host $_.Exception.Message }"
)
if not exist cloudflared.exe (
  echo cloudflared yuklab bo'lmadi. Internetni tekshiring.
  pause
  exit /b
)

REM --- tunnelni fon rejimida ishga tushir ---
del /q tunnel.log 2>nul
echo Tunnel ochilmoqda...
start "Luvora Tunnel" /min cmd /c cloudflared.exe tunnel --url http://localhost:8080 --logfile tunnel.log

REM --- manzil chiqishini kutamiz ---
:wait
timeout /t 1 >nul
if not exist tunnel.log goto wait
findstr /c:"trycloudflare.com" tunnel.log >nul 2>&1
if errorlevel 1 goto wait

REM --- manzilni ajratib to'g'ridan-to'g'ri webapp_url.txt ga yozamiz (fayl bloklansa ham) ---
powershell -NoProfile -Command "$u=(Select-String -Path 'tunnel.log' -Pattern 'https://[a-z0-9-]+\.trycloudflare\.com' | Select-Object -First 1).Matches[0].Value; if($u){ Set-Content -NoNewline -Path 'webapp_url.txt' -Value $u }"
set "URL="
set /p URL=<webapp_url.txt
echo.
echo   Mini App manzili:  %URL%
echo.

REM --- 8080-port band bo'lsa (boshqa bot ishlayotgan bo'lsa) ogohlantir ---
netstat -ano | findstr ":8080" | findstr "LISTENING" >nul && (
  echo [!] 8080-port band. Boshqa bot ishlayapti ^(PyCharm dagi bot?^).
  echo     Avval uni to'xtating ^(qizil kvadrat^), keyin bu oynani qayta oching.
  pause
  exit /b
)

REM --- botni ishga tushir ---
echo Bot ishga tushmoqda...  (BU OYNANI YOPMANG)
echo ------------------------------------------------
".venv\Scripts\python.exe" dvinchik_bot.py

echo.
echo Bot to'xtadi. Yopish uchun tugma bosing.
pause
