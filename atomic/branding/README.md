# Branding Atomic

Identidade visual do Atomic Chat, aplicada por API (sem alterar código do Rocket.Chat).

## Paleta

| Token | Cor | Uso |
|---|---|---|
| base | `#000A15` | fundos escuros, barra lateral |
| navy | `#002244` | ícones/favicons, superfícies escuras |
| azul | `#0D5E94` | botões primários, destaques |
| azul claro | `#3A8DDE` | hover, foco, links |

Tirada do logo e da assinatura de e-mail da Atomic Group.

## Arquivos

| Arquivo | Vai para |
|---|---|
| `assets/logo.png` | logo do tema claro (marca em `#000A15`, fundo transparente) |
| `assets/logo_dark.png` | logo do tema escuro (branco, fundo transparente) |
| `assets/background*.jpg` | fundo da tela de login |
| `assets/favicon*`, `touchicon*`, `tile*` | ícones de aba, celular e Windows (marca AG sobre navy) |
| `assets/mark_white.png` | só a marca AG, para outros usos |
| `custom.css` | cores da marca sobre os tokens do Fuselage |
| `home.html` | conteúdo da página inicial do chat |

## Aplicar

1. Entre como admin → Minha Conta → Tokens de Acesso Pessoal → gere um token com
   **"Ignorar autenticação de dois fatores"** marcado (alterar settings exige isso via API).
2. Rode na VPS (ou em qualquer máquina com `curl` e `jq`):

```bash
RC_URL=https://chat.atomicgroup.com.br RC_USER_ID=<id> RC_TOKEN=<token> bash atomic/branding/apply-branding.sh
```

3. Recarregue o navegador com Ctrl+F5. Depois de aplicar, apague o token de admin.

O script é idempotente: mudou um arquivo daqui, rode de novo.

## Observações

- O `custom.css` usa variáveis do Fuselage. Algumas podem mudar entre versões do Rocket.Chat;
  confira a tela depois de cada upgrade.
- Temas de cor completos (editor de tema) são recurso Enterprise; aqui usamos só CSS, que é livre.
- Nome do site e idioma ficam fixos pelo `deploy/docker-compose.yml` (`OVERWRITE_SETTING_*`).
