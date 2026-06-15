#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

if [[ ! -f .env ]]; then
  echo "Missing core/.env — copy .env.example and fill in your values."
  exit 1
fi

docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build

echo "Waiting for API health check..."
for i in {1..30}; do
  if curl -sf http://127.0.0.1:8000/health >/dev/null 2>&1; then
    echo "API is healthy."
    exit 0
  fi
  sleep 2
done

echo "API did not become healthy in time. Check: docker compose logs api"
exit 1
