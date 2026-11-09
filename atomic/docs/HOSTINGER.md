# Deploy na VPS Hostinger

## 1. Escolher a VPS

| Usuários ativos | Plano Hostinger sugerido | Observação |
|---|---|---|
| até ~50 | KVM 2 (2 vCPU, 8 GB) | Rocket.Chat + Mongo + Hermes cabem com folga |
| 50–300 | **KVM 4 (4 vCPU, 16 GB)** | recomendado para começar com margem |
| 300+ | KVM 8 | ou separar o MongoDB em outra VPS |

Sistema: **Ubuntu 24.04 LTS** (template limpo, sem painel). Região: São Paulo, se disponível.

O **build** da imagem não roda na VPS: é feito no GitHub Actions e a VPS só baixa a imagem pronta.

## 2. DNS

Crie um registro `A` de `chat.atomicgroup.com.br` (ou o domínio que escolherem) apontando para o IP da VPS.

## 3. Preparar a VPS

Acesse por SSH (evite o terminal do navegador do hPanel para colar comandos):

```bash
ssh root@IP_DA_VPS
```

```bash
git clone https://github.com/ti-atomicgroup/Atomic.Chat.git /opt/atomic-chat && cd /opt/atomic-chat
```

```bash
bash atomic/deploy/scripts/bootstrap-vps.sh
```

No hPanel, confira se o firewall da Hostinger também libera 22, 80 e 443.

## 4. Configurar e subir o chat

Edite `atomic/deploy/.env` (domínio, admin, tag da imagem). A imagem `ghcr.io/ti-atomicgroup/atomic-chat` é pública e não precisa de login. Só se um dia ela virar privada:

```bash
echo "<TOKEN_COM_read:packages>" | docker login ghcr.io -u <usuario-github> --password-stdin
```

```bash
cd /opt/atomic-chat/atomic/deploy && docker compose up -d mongodb rocketchat caddy
```

```bash
docker compose logs -f rocketchat
```

Quando aparecer `SERVER RUNNING`, acesse `https://chat.atomicgroup.com.br` com o admin do `.env` e troque a senha.

## 5. Criar o bot do Hermes

1. Administração → Usuários → Novo: usuário `hermes`, papel **bot**.
2. Entre como `hermes` → Minha Conta → Tokens de Acesso Pessoal → gerar (sem 2FA).
3. Copie **User ID** e **Token** para `atomic/deploy/.env.hermes`.
4. Crie a sala `#alertas`, adicione o `hermes`, e copie o ID da sala para `ROCKETCHAT_HOME_CHANNEL`.
5. Preencha a chave do modelo (`ANTHROPIC_API_KEY`) e as variáveis da Nekt.

```bash
docker compose up -d hermes && docker compose logs -f hermes
```

Procure por `Rocket.Chat: WebSocket autenticado`. Depois mande uma DM para `@hermes`.

## 6. Backup

```bash
crontab -e
```

Adicione a linha:

```
15 3 * * * /opt/atomic-chat/atomic/deploy/scripts/backup.sh >> /var/log/atomic-backup.log 2>&1
```

Ative também o snapshot semanal da VPS no hPanel. É barato e cobre desastres.

## 7. Atualizar

```bash
cd /opt/atomic-chat && git pull && cd atomic/deploy && docker compose pull && docker compose up -d
```
