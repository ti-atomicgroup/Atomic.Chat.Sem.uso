#!/usr/bin/env bash
# Prepara uma VPS Hostinger (Ubuntu 24.04) para o Atomic Chat. Idempotente: pode rodar de novo.
# Uso (como root):  bash atomic/deploy/scripts/bootstrap-vps.sh
set -euo pipefail

DEPLOY_DIR="$(cd "$(dirname "$0")/.." && pwd)"

echo "==> Pacotes básicos e atualizações de segurança automáticas"
apt-get update -y
apt-get install -y ca-certificates curl git ufw unattended-upgrades
dpkg-reconfigure -f noninteractive unattended-upgrades

if ! command -v docker >/dev/null; then
  echo "==> Instalando Docker"
  curl -fsSL https://get.docker.com | sh
fi

echo "==> Firewall: SSH, HTTP, HTTPS"
ufw allow OpenSSH
ufw allow 80/tcp
ufw allow 443/tcp
ufw allow 443/udp
ufw --force enable

if ! swapon --show | grep -q /swapfile; then
  echo "==> Criando swap de 4 GB"
  fallocate -l 4G /swapfile && chmod 600 /swapfile && mkswap /swapfile && swapon /swapfile
  echo '/swapfile none swap sw 0 0' >> /etc/fstab
fi

echo "==> Arquivos de configuração"
cd "$DEPLOY_DIR"
[ -f .env ] || { cp .env.example .env; echo "   criado .env — EDITE antes de subir"; }
[ -f .env.hermes ] || { cp .env.hermes.example .env.hermes; chmod 600 .env.hermes; echo "   criado .env.hermes — EDITE"; }

mkdir -p data/hermes
[ -f data/hermes/config.yaml ] || cp ../hermes/config.yaml data/hermes/config.yaml
[ -f data/hermes/SOUL.md ] || cp ../hermes/SOUL.md data/hermes/SOUL.md
chown -R 10000:10000 data/hermes

echo
echo "Pronto. Próximos passos:"
echo "  1. Edite $DEPLOY_DIR/.env e $DEPLOY_DIR/.env.hermes"
echo "  2. Aponte o DNS de CHAT_DOMAIN para o IP desta VPS"
echo "  3. cd $DEPLOY_DIR && docker compose up -d mongodb rocketchat caddy"
echo "  4. Crie o usuário-bot 'hermes' no chat, gere o token e só então: docker compose up -d hermes"
