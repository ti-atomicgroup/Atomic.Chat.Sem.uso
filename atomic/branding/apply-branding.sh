#!/usr/bin/env bash
# Aplica a identidade visual da Atomic no Rocket.Chat via REST API.
# Idempotente: rode de novo sempre que mudar algum arquivo de atomic/branding/.
#
# Pré-requisito: Personal Access Token de um admin, gerado com "Ignorar autenticação de dois fatores"
# marcado (Minha Conta → Tokens de Acesso Pessoal). Alterar settings exige 2FA sem essa opção.
#
# Uso:
#   RC_URL=https://chat.atomicgroup.com.br RC_USER_ID=... RC_TOKEN=... bash atomic/branding/apply-branding.sh
set -euo pipefail

: "${RC_URL:?defina RC_URL}" "${RC_USER_ID:?defina RC_USER_ID}" "${RC_TOKEN:?defina RC_TOKEN}"
DIR="$(cd "$(dirname "$0")" && pwd)"
AUTH=(-H "X-User-Id: $RC_USER_ID" -H "X-Auth-Token: $RC_TOKEN")

FAILS=0
ok() { jq -e '.success == true' >/dev/null 2>&1 || { echo "  FALHOU"; FAILS=$((FAILS + 1)); return 1; }; }

set_asset() {
	local name="$1" file="$2"
	printf "asset %-18s ← %s" "$name" "$(basename "$file")"
	local resp
	resp=$(curl -sS "${AUTH[@]}" -F "asset=@$file" -F "assetName=$name" "$RC_URL/api/v1/assets.setAsset" || true)
	ok <<<"$resp" && echo "  ok" || true
}

set_setting() {
	local id="$1" json_value="$2"
	printf "setting %-28s" "$id"
	local resp
	resp=$(curl -sS "${AUTH[@]}" -H 'Content-Type: application/json' \
		-d "{\"value\": $json_value}" "$RC_URL/api/v1/settings/$id" || true)
	ok <<<"$resp" && echo "  ok" || true
}

A="$DIR/assets"
set_asset logo              "$A/logo.png"
set_asset logo_dark         "$A/logo_dark.png"
set_asset background        "$A/background.jpg"
set_asset background_dark   "$A/background_dark.jpg"
set_asset favicon_ico       "$A/favicon.ico"
for n in favicon_16 favicon_32 favicon_192 favicon_512 touchicon_180 touchicon_180_pre \
	tile_70 tile_144 tile_150 tile_310_square tile_310_wide; do
	set_asset "$n" "$A/$n.png"
done

set_setting theme-custom-css          "$(jq -Rs . < "$DIR/custom.css")"
set_setting Layout_Home_Title         '"Atomic Chat"'
set_setting Layout_Home_Body          "$(jq -Rs . < "$DIR/home.html")"
set_setting Layout_Login_Hide_Powered_By true
set_setting Layout_Login_Template     '"vertical-template"'
set_setting Layout_Sidenav_Footer      '"<a href=\"/home\"><img src=\"assets/logo.png\" alt=\"Atomic Group\" /></a>"'
set_setting Layout_Sidenav_Footer_Dark '"<a href=\"/home\"><img src=\"assets/logo_dark.png\" alt=\"Atomic Group\" /></a>"'

[ "$FAILS" -eq 0 ] || { echo "$FAILS item(ns) falharam — confira token/permissões."; exit 1; }
echo "Pronto. Recarregue o chat (Ctrl+F5) para ver as mudanças."
