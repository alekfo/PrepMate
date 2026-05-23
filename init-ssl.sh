#!/bin/bash
set -e

DOMAIN="prepstats.pro"
EMAIL=$1

if [ -z "$EMAIL" ]; then
  echo "Usage: ./init-ssl.sh your@email.com"
  exit 1
fi

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

log()  { echo -e "${GREEN}[INFO]${NC}  $1"; }
warn() { echo -e "${YELLOW}[WARN]${NC}  $1"; }

# ─── 1. Install Docker Engine ─────────────────────────────────────────────────

if command -v docker &>/dev/null; then
  log "Docker already installed: $(docker --version)"
else
  log "Removing conflicting packages..."
  CONFLICT_PKGS=$(dpkg --get-selections \
    docker.io docker-compose docker-compose-v2 docker-doc \
    podman-docker containerd runc 2>/dev/null | cut -f1)
  if [ -n "$CONFLICT_PKGS" ]; then
    apt remove -y $CONFLICT_PKGS
  else
    log "No conflicting packages found."
  fi

  log "Installing prerequisites..."
  apt update
  apt install -y ca-certificates curl

  log "Setting up Docker GPG key..."
  install -m 0755 -d /etc/apt/keyrings
  curl -fsSL https://download.docker.com/linux/ubuntu/gpg \
    -o /etc/apt/keyrings/docker.asc
  chmod a+r /etc/apt/keyrings/docker.asc

  log "Adding Docker apt repository..."
  tee /etc/apt/sources.list.d/docker.sources > /dev/null <<EOF
Types: deb
URIs: https://download.docker.com/linux/ubuntu
Suites: $(. /etc/os-release && echo "${UBUNTU_CODENAME:-$VERSION_CODENAME}")
Components: stable
Architectures: $(dpkg --print-architecture)
Signed-By: /etc/apt/keyrings/docker.asc
EOF

  apt update
  apt install -y \
    docker-ce docker-ce-cli containerd.io \
    docker-buildx-plugin docker-compose-plugin

  systemctl enable docker
  systemctl start docker
  log "Docker installed: $(docker --version)"
fi

if ! systemctl is-active --quiet docker; then
  log "Starting Docker..."
  systemctl start docker
fi

# ─── 2. Install Certbot ───────────────────────────────────────────────────────

if ! command -v certbot &>/dev/null; then
  log "Installing certbot..."
  apt update && apt install -y certbot
fi

# ─── 3. Obtain SSL certificate ────────────────────────────────────────────────

if [ -d "/etc/letsencrypt/live/$DOMAIN" ]; then
  warn "Certificate for $DOMAIN already exists — skipping certbot."
else
  log "Stopping nginx to free port 80..."
  docker compose stop nginx 2>/dev/null || true
  fuser -k 80/tcp 2>/dev/null || true

  log "Obtaining certificate for $DOMAIN..."
  certbot certonly \
    --standalone \
    --non-interactive \
    --agree-tos \
    --email "$EMAIL" \
    -d "$DOMAIN"

  log "Certificate obtained."
fi

# ─── 4. Start stack ───────────────────────────────────────────────────────────

log "Building and starting Docker Compose stack..."
docker compose up -d --build

log "Verifying containers..."
docker compose ps

echo ""
echo -e "${GREEN}Done!${NC} https://$DOMAIN"
echo ""
echo "Set up monthly auto-renewal (run once):"
echo "  (crontab -l 2>/dev/null; echo \"0 3 1 * * cd $(pwd) && docker compose stop nginx && certbot renew --quiet && docker compose start nginx\") | crontab -"