#!/bin/bash
set -e

EMAIL=$1

if [ -z "$EMAIL" ]; then
  echo "Usage: ./init-ssl.sh your@email.com"
  exit 1
fi

# Install certbot on host if not present
if ! command -v certbot &>/dev/null; then
  apt update && apt install -y certbot
fi

# Stop nginx to free port 80 for standalone challenge
docker compose stop nginx 2>/dev/null || true

# Get certificate from Let's Encrypt
certbot certonly --standalone \
  --email "$EMAIL" \
  -d prepstats.pro \
  --agree-tos \
  --non-interactive

# Start all services
docker compose up -d

echo ""
echo "Done! https://prepstats.pro"
echo ""
echo "Setup auto-renewal (run once):"
echo "  (crontab -l 2>/dev/null; echo \"0 3 1 * * cd $(pwd) && docker compose stop nginx && certbot renew --quiet && docker compose start nginx\") | crontab -"
