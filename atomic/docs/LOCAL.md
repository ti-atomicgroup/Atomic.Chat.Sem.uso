# Rodar o Atomic Chat localmente

Para testar no seu computador antes de levar para a VPS. Usa a **mesma imagem** da produção
(`ghcr.io/ti-atomicgroup/atomic-chat`), só que sem domínio e sem HTTPS: o chat abre em
`http://localhost:3000`.

## Pré-requisitos (Windows)

1. **Docker Desktop** com o backend WSL 2 (padrão na instalação).
2. Em Docker Desktop → Settings → Resources, deixe pelo menos **6 GB de memória**.
3. O repositório clonado em `C:\AtomicClub` (ver o README).

## Subir o chat

No PowerShell:

```bash
cd C:\AtomicClub\atomic\deploy
```

```bash
copy .env.example .env
```

Abra o `.env` e ajuste pelo menos `RC_ADMIN_PASS` (e `MONGO_CACHE_GB=1` se a máquina tiver pouca RAM).
O `CHAT_DOMAIN` não é usado localmente.

```bash
docker compose -f docker-compose.yml -f docker-compose.local.yml up -d
```

```bash
docker compose -f docker-compose.yml -f docker-compose.local.yml logs -f rocketchat
```

Quando aparecer `SERVER RUNNING`, abra **http://localhost:3000** e entre com o admin do `.env`.
A primeira subida leva de 1 a 3 minutos.

## Aplicar o branding

Gere um Personal Access Token do admin (Minha Conta → Tokens de Acesso Pessoal, marque
"Ignorar autenticação de dois fatores"). O script é bash, então rode pelo **Git Bash** ou WSL:

```bash
RC_URL=http://localhost:3000 RC_USER_ID=<id> RC_TOKEN=<token> bash ../branding/apply-branding.sh
```

## Ligar o Hermes (opcional)

1. No chat local, crie o usuário `hermes` (papel bot), gere o token dele e crie a sala `#alertas`.
2. Copie o modelo de segredos e preencha (token do bot, chave do modelo de IA, Nekt):

```bash
copy .env.hermes.example .env.hermes
```

3. Prepare a pasta de dados do Hermes e suba o bot:

```bash
mkdir data\hermes; copy ..\hermes\config.yaml data\hermes\; copy ..\hermes\SOUL.md data\hermes\
```

```bash
docker compose -f docker-compose.yml -f docker-compose.local.yml --profile bot up -d hermes
```

Mande uma DM para `@hermes` no chat local.

## Parar, recomeçar do zero

Parar (mantém os dados):

```bash
docker compose -f docker-compose.yml -f docker-compose.local.yml --profile bot down
```

Apagar tudo, inclusive o banco local:

```bash
docker compose -f docker-compose.yml -f docker-compose.local.yml --profile bot down -v
```

## Problemas comuns

| Sintoma | Causa provável |
|---|---|
| `$'\r': command not found` ou `no such file or directory` ao rodar scripts | arquivo com quebra de linha do Windows (CRLF). O `atomic/.gitattributes` força LF; se você clonou antes dele existir e **não tem alterações locais**, rode `git rm --cached -r -q atomic` e depois `git reset --hard` |
| Rocket.Chat reinicia em loop | pouca memória no Docker Desktop (aumente para 6 GB+) |
| Porta 3000 ocupada | outro serviço usando a porta. No `docker-compose.local.yml`, troque a porta para `"3001:3000"` **e** o `ROOT_URL` para `http://localhost:3001` |
