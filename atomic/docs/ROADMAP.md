# Roadmap

## Fase 1 — No ar (semana 1-2)
- [x] Fork 8.9.1 + estrutura `atomic/`
- [x] Conector Hermes ↔ Rocket.Chat com testes
- [x] Stack de deploy (Caddy, Mongo, Rocket.Chat, Hermes) + backup
- [x] Criar repositório da empresa e subir o código
- [ ] Rodar o workflow de build e publicar a primeira imagem
- [ ] Contratar VPS, DNS, primeiro deploy

## Fase 2 — Cara da Atomic (semana 2-3)
- [x] Logo, favicon, cores e tela de login (`atomic/branding/`)
- [ ] Canais padrão (#geral, #alertas, #vendas, #produto, #board)
- [ ] Login com Google Workspace (OAuth) para não ter senha separada
- [ ] Apps desktop/mobile apontando para o domínio

## Fase 3 — Dados e bots (semana 3-5)
- [ ] Token MCP da Nekt (só leitura) e teste de consultas pelo `@hermes`
- [ ] Alertas: meta diária de vendas, leads novos, churn (cron do Hermes → #alertas)
- [ ] Resumo semanal para o board meeting
- [ ] Comando `/nekt` nativo no chat (customização no fork)

## Fase 4 — Customizações no core (contínuo)
- [ ] Levantar o que o white-label não resolve e implementar em `apps/meteor/*/atomic/`
