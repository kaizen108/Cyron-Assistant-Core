#!/usr/bin/env bash
# Quick diagnostics after `docker compose up -d`.
# Run on VPS from the core/ directory: bash deploy/verify-stack.sh

set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

ok()   { echo -e "${GREEN}OK${NC}    $*"; }
fail() { echo -e "${RED}FAIL${NC}  $*"; }
warn() { echo -e "${YELLOW}WARN${NC}  $*"; }

echo "=== Docker containers ==="
docker compose ps

echo ""
echo "=== API health (localhost only — expected path) ==="
if curl -sf http://127.0.0.1:8000/health; then
  echo ""
  ok "API responds on 127.0.0.1:8000"
else
  echo ""
  fail "API not reachable on 127.0.0.1:8000"
  echo "       Check: docker compose logs api --tail 80"
  exit 1
fi

echo ""
echo "=== Public IP :8000 (should FAIL — API is bound to localhost) ==="
PUBLIC_IP=$(curl -sf ifconfig.me 2>/dev/null || hostname -I | awk '{print $1}')
if curl -sf --connect-timeout 2 "http://${PUBLIC_IP}:8000/health" >/dev/null 2>&1; then
  warn "Port 8000 is publicly exposed (not required if nginx is used)"
else
  ok "Port 8000 not public (correct — use nginx on 443)"
fi

echo ""
echo "=== nginx ==="
if systemctl is-active --quiet nginx; then
  ok "nginx is running"
else
  fail "nginx is NOT running"
  echo "       Fix: sudo systemctl start nginx"
fi

if [ -f /etc/nginx/sites-enabled/api.cyronticket.com ] || \
   grep -rq "api.cyronticket.com" /etc/nginx/sites-enabled/ 2>/dev/null; then
  ok "nginx site config found for api.cyronticket.com"
else
  fail "No nginx site for api.cyronticket.com"
  echo "       Fix: sudo bash deploy/setup-nginx.sh"
fi

if sudo nginx -t 2>/dev/null; then
  ok "nginx config syntax valid"
else
  fail "nginx config invalid — run: sudo nginx -t"
fi

echo ""
echo "=== HTTPS via nginx (origin) ==="
if curl -sf --resolve api.cyronticket.com:443:127.0.0.1 \
  https://api.cyronticket.com/health 2>/dev/null; then
  echo ""
  ok "HTTPS origin works through nginx"
else
  fail "nginx is not proxying api.cyronticket.com → 127.0.0.1:8000"
  echo "       Fix: sudo bash deploy/setup-nginx.sh && sudo systemctl reload nginx"
fi

echo ""
echo "=== Cloudflare note ==="
warn "HTTP 521 = Cloudflare cannot reach your origin on 443."
echo "       1. nginx must be running with SSL on 443"
echo "       2. Cloudflare DNS A record → $(echo "${PUBLIC_IP:-your VPS IP}")"
echo "       3. Cloudflare SSL/TLS mode: Full (strict)"
echo "       4. Firewall: sudo ufw allow 443/tcp && sudo ufw allow 80/tcp"
