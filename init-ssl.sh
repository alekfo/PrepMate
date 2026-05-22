#!/bin/bash
set -e

EMAIL=$1

if [ -z "$EMAIL" ]; then
  echo "Usage: ./init-ssl.sh your@email.com"
  exit 1
fi

# Создаём временный самоподписной сертификат, чтобы nginx смог стартовать
docker compose run --rm --entrypoint "" certbot sh -c "
  mkdir -p /etc/letsencrypt/live/prepstats.pro &&
  openssl req -x509 -nodes -newkey rsa:2048 -days 1 \
    -keyout /etc/letsencrypt/live/prepstats.pro/privkey.pem \
    -out  /etc/letsencrypt/live/prepstats.pro/fullchain.pem \
    -subj '/CN=localhost'
"

# Запускаем nginx с временным сертификатом
docker compose up -d nginx

# Получаем реальный сертификат Let's Encrypt
docker compose run --rm --entrypoint "" certbot certbot certonly \
  --webroot -w /var/www/certbot \
  --email "$EMAIL" \
  -d prepstats.pro \
  --agree-tos \
  --non-interactive \
  --force-renewal

# Перезагружаем nginx с реальным сертификатом
docker compose exec nginx nginx -s reload

# Запускаем все сервисы
docker compose up -d

echo ""
echo "Done! https://prepstats.pro"
