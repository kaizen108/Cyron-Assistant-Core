#!/usr/bin/env bash
# Install nginx reverse proxy for api.cyronticket.com → Docker API (127.0.0.1:8000)
# Run on VPS: sudo bash deploy/setup-nginx.sh

set -euo pipefail

DOMAIN="${API_DOMAIN:-api.cyronticket.com}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SITE_AVAILABLE="/etc/nginx/sites-available/${DOMAIN}"
SITE_ENABLED="/etc/nginx/sites-enabled/${DOMAIN}"

if [ "$(id -u)" -ne 0 ]; then
  echo "Run as root: sudo bash deploy/setup-nginx.sh"
  exit 1
fi

apt-get update -qq
apt-get install -y nginx curl

# Ensure API is up before wiring nginx
if ! curl -sf http://127.0.0.1:8000/health >/dev/null; then
  echo "ERROR: API not running on 127.0.0.1:8000"
  echo "Start Docker first: docker compose up -d"
  exit 1
fi

if [ -f "/etc/letsencrypt/live/${DOMAIN}/fullchain.pem" ]; then
  echo "Using existing Let's Encrypt certificate for ${DOMAIN}"
  cp "${SCRIPT_DIR}/nginx-api.conf.example" "${SITE_AVAILABLE}"
else
  echo "No certificate yet — installing HTTP-only config, then running certbot..."
  cat > "${SITE_AVAILABLE}" <<EOF
server {
    listen 80;
    server_name ${DOMAIN};

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_read_timeout 120s;
    }
}
EOF
  ln -sf "${SITE_AVAILABLE}" "${SITE_ENABLED}"
  nginx -t
  systemctl enable nginx
  systemctl restart nginx

  if command -v certbot >/dev/null; then
    certbot --nginx -d "${DOMAIN}" --non-interactive --agree-tos -m admin@${DOMAIN#api.} || \
      certbot --nginx -d "${DOMAIN}"
  else
    apt-get install -y certbot python3-certbot-nginx
    certbot --nginx -d "${DOMAIN}"
  fi

  # Replace with full HTTPS template (certbot usually patches in-place; ensure proxy_pass)
  if ! grep -q "127.0.0.1:8000" "${SITE_AVAILABLE}"; then
    cp "${SCRIPT_DIR}/nginx-api.conf.example" "${SITE_AVAILABLE}"
  fi
fi

ln -sf "${SITE_AVAILABLE}" "${SITE_ENABLED}"
rm -f /etc/nginx/sites-enabled/default 2>/dev/null || true

nginx -t
systemctl enable nginx
systemctl restart nginx

echo ""
echo "Testing origin..."
curl -sf "http://127.0.0.1:8000/health" && echo ""
curl -sf --resolve "${DOMAIN}:443:127.0.0.1" "https://${DOMAIN}/health" && echo ""
echo "Done. Test from outside: curl https://${DOMAIN}/health"
