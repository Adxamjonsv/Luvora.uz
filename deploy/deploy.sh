#!/usr/bin/env bash
# ============================================================
#  Luvora — VDS'ga avtomatik o'rnatish (Ubuntu 22.04 / 24.04)
#  Ishlatish:   sudo bash deploy.sh SIZNING-DOMEN.uz
#  Loyiha fayllari /opt/luvora ichida bo'lishi kerak.
# ============================================================
set -e

DOMAIN="$1"
APP_DIR="/opt/luvora"

if [ -z "$DOMAIN" ]; then
  echo "❌ Domen kiritilmadi."
  echo "   Masalan:  sudo bash deploy.sh luvora.uz"
  exit 1
fi

if [ ! -f "$APP_DIR/dvinchik_bot.py" ]; then
  echo "❌ $APP_DIR/dvinchik_bot.py topilmadi."
  echo "   Avval loyiha fayllarini $APP_DIR ichiga yuklang (dvinchik_bot.py, miniapp/, logo.png ...)."
  exit 1
fi

echo "==> [1/6] Tizim yangilanmoqda..."
apt update && apt -y upgrade

echo "==> [2/6] Python va vositalar o'rnatilmoqda..."
apt -y install python3 python3-venv python3-pip curl gnupg debian-keyring debian-archive-keyring apt-transport-https ufw

echo "==> [3/6] Caddy (avtomatik HTTPS) o'rnatilmoqda..."
if ! command -v caddy >/dev/null 2>&1; then
  curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' | gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
  curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' | tee /etc/apt/sources.list.d/caddy-stable.list >/dev/null
  apt update
  apt -y install caddy
fi

echo "==> [4/6] Kutubxonalar (venv) o'rnatilmoqda..."
cd "$APP_DIR"
python3 -m venv venv
./venv/bin/pip install --upgrade pip
if [ -f requirements.txt ]; then
  ./venv/bin/pip install -r requirements.txt
else
  ./venv/bin/pip install "aiogram>=3.4,<4" "aiohttp>=3.9"
fi

# WEBAPP_URL = domen (bot shu fayldan o'qiydi, cloudflared endi kerak emas)
echo "https://$DOMAIN" > "$APP_DIR/webapp_url.txt"

echo "==> [5/6] systemd xizmati sozlanmoqda..."
cat > /etc/systemd/system/luvora.service <<EOF
[Unit]
Description=Luvora Telegram bot + Mini App
After=network.target

[Service]
Type=simple
WorkingDirectory=$APP_DIR
ExecStart=$APP_DIR/venv/bin/python $APP_DIR/dvinchik_bot.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

echo "==> [6/6] Caddy (HTTPS) sozlanmoqda..."
cat > /etc/caddy/Caddyfile <<EOF
$DOMAIN {
    reverse_proxy 127.0.0.1:8080
}
EOF

# Portlarni ochamiz (SSH + HTTP + HTTPS)
ufw allow 22/tcp  >/dev/null 2>&1 || true
ufw allow 80/tcp  >/dev/null 2>&1 || true
ufw allow 443/tcp >/dev/null 2>&1 || true
yes | ufw enable  >/dev/null 2>&1 || true

systemctl daemon-reload
systemctl enable luvora >/dev/null 2>&1 || true
systemctl restart luvora
systemctl reload caddy 2>/dev/null || systemctl restart caddy

echo ""
echo "============================================================"
echo "✅ TAYYOR!  Bot 24/7 ishlayapti."
echo "   Mini App manzili:  https://$DOMAIN"
echo ""
echo "   Bot loglari:       journalctl -u luvora -f"
echo "   Botni qayta ishga: systemctl restart luvora"
echo "   Kodni yangilagach: (fayllarni yuklab) systemctl restart luvora"
echo "============================================================"
