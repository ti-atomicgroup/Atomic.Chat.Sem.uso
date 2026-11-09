# Branding Atomic

Coloque aqui os arquivos de identidade visual:

| Arquivo | Onde entra no Rocket.Chat |
|---|---|
| `logo.svg` / `logo.png` | Administração → Workspace → Assets → Logo |
| `favicon.svg` / `favicon-512.png` | Assets → Favicon |
| `custom.css` | Administração → Layout → Custom CSS |
| cores (tokens) | Administração → Layout → Cores / tema |

Configurações fixas (nome, idioma) já vêm do `deploy/docker-compose.yml` via `OVERWRITE_SETTING_*`.
Mudanças que o painel não cobre viram código do fork (ver `docs/FORK.md`).
