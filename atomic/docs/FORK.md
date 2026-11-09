# Regras do fork

## Branches e remotes

| Remote | Aponta para | Uso |
|---|---|---|
| `origin` | repositório da Atomic Group | onde a equipe trabalha |
| `upstream` | `github.com/RocketChat/Rocket.Chat` | só leitura, para puxar versões novas |

- `atomic/main`: branch principal da Atomic. Fica em cima de uma **tag de release** do Rocket.Chat
  (hoje `8.9.1`), nunca em cima do `develop` deles.
- Features: `atomic/feat/<nome>` → PR para `atomic/main`.

## Onde mexer (para não sofrer nas atualizações)

1. **Prefira configuração a código**: muita coisa (nome, idioma, cores, logo, CSS, textos do login)
   sai por `OVERWRITE_SETTING_*` no `docker-compose.yml` ou por `atomic/branding/`.
2. **Código novo da Atomic** vai em pastas novas, nunca misturado em arquivos do upstream:
   - servidor: `apps/meteor/server/atomic/`
   - cliente: `apps/meteor/client/atomic/`
   - traduções: chaves com prefixo `Atomic_` em `packages/i18n/src/locales/pt-BR.i18n.json`
3. **Quando precisar alterar um arquivo do upstream**, deixe a mudança mínima e marque:
   ```ts
   // ATOMIC: <motivo em uma linha>
   ```
   Assim `git grep "ATOMIC:"` mostra tudo que pode dar conflito na próxima atualização.
4. Nada de mexer em `apps/meteor/ee/` e `ee/` (licença Enterprise).

## Atualizar para uma versão nova do Rocket.Chat

```bash
git fetch upstream tag 8.10.0 --no-tags
```

```bash
git checkout -b atomic/upgrade-8.10.0 atomic/main && git merge 8.10.0
```

Resolva conflitos (comece por `git grep "ATOMIC:"`), rode o build do workflow manualmente,
suba em um ambiente de teste, e só então faça o PR para `atomic/main`.
Leia as notas de versão do Rocket.Chat antes: algumas versões exigem upgrade do MongoDB.

Cada release do Rocket.Chat tem suporte de 6 meses (as LTS, mais). Planeje uma atualização
por trimestre — combina com o ciclo de rocks.

## Workflows do GitHub Actions

O fork herda dezenas de workflows do Rocket.Chat (testes E2E, release, etc.) que não fazem
sentido para nós e gastam minutos de Actions. Depois de criar o repositório, desative-os e
deixe só o `Atomic — build da imagem`:

```bash
gh workflow list --all
```

```bash
for w in ci.yml ci-code-check.yml ci-test-e2e.yml ci-test-unit.yml ci-test-storybook.yml ci-deploy-gh-pages.yml release.yml codeql-analysis.yml stale.yml todo.yml dedupe-issues.yml auto-close-duplicates.yml pr-update-description.yml update-version-durability.yml; do gh workflow disable "$w"; done
```
