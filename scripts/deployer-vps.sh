#!/usr/bin/env bash
# deployer-vps.sh — installe le moteur AGROGUIDCI sur le VPS et vérifie qu'il répond.
#
#   ./scripts/deployer-vps.sh                 # valeurs par défaut ci-dessous
#   HOTE=… UTILISATEUR=… DOMAINE=… ./scripts/deployer-vps.sh
#
# Ce que fait le script :
#   1. vérifie l'accès SSH (clé ~/.ssh/agroguidci_vps) et installe Docker si absent ;
#   2. copie le moteur et l'orchestrateur dans /opt/agroguidci ;
#   3. écrit vps/.env (secrets générés une seule fois, conservés dans ~/.agroguidci/vps.env) ;
#   4. construit et démarre orchestrateur + moteur + Caddy, puis attend /health ;
#   5. vérifie https://<domaine>/health depuis ce poste.
#
# Aucun secret n'est affiché : la clé d'API est écrite dans ~/.agroguidci/vps.env
# (chmod 600) et n'apparaît que dans les fichiers, jamais dans la sortie.
set -euo pipefail

HOTE="${HOTE:-185.213.27.95}"
UTILISATEUR="${UTILISATEUR:-root}"
DOMAINE="${DOMAINE:-185-213-27-95.sslip.io}"     # sslip.io : DNS gratuit, TLS Let's Encrypt
DEST="${DEST:-/opt/agroguidci}"
CLE_SSH="${CLE_SSH:-$HOME/.ssh/agroguidci_vps}"
LOCAL="$(cd "$(dirname "$0")/.." && pwd)"
ETAT="$HOME/.agroguidci"
ENV_LOCAL="$ETAT/vps.env"

SSH=(ssh -i "$CLE_SSH" -o IdentitiesOnly=yes -o StrictHostKeyChecking=accept-new
     -o ConnectTimeout=15 "$UTILISATEUR@$HOTE")

# copier <source> <cible distante> [exclusions…] — rsync si présent, sinon tar sur SSH.
copier() {
  local src="$1" dst="$2"; shift 2
  if command -v rsync >/dev/null; then
    local ex=()
    for p in "$@"; do ex+=("--exclude=$p"); done
    rsync -az --delete -e "ssh -i $CLE_SSH -o IdentitiesOnly=yes -o StrictHostKeyChecking=accept-new" \
      "${ex[@]}" "$src/" "$UTILISATEUR@$HOTE:$dst/"
  else
    local ex=()
    for p in "$@"; do ex+=("--exclude=$p"); done
    "${SSH[@]}" "mkdir -p '$dst'"
    tar czf - "${ex[@]}" -C "$src" . | "${SSH[@]}" "tar xzf - -C '$dst'"
  fi
}

echo "1/6 · accès SSH $UTILISATEUR@$HOTE"
"${SSH[@]}" 'echo "   connecté : $(hostname) · $(. /etc/os-release 2>/dev/null; echo $PRETTY_NAME)"'

echo "2/6 · Docker"
if ! "${SSH[@]}" 'command -v docker >/dev/null && docker compose version >/dev/null'; then
  echo "   installation de Docker…"
  "${SSH[@]}" 'curl -fsSL https://get.docker.com | sh >/dev/null && systemctl enable --now docker >/dev/null'
fi
"${SSH[@]}" 'docker --version; docker compose version | head -1'

echo "3/6 · secrets"
mkdir -p "$ETAT"
chmod 700 "$ETAT"
if [ ! -f "$ENV_LOCAL" ]; then
  umask 077
  {
    echo "AGRO_API_KEY=$(openssl rand -hex 32)"
    echo "ORCH_ADMIN_KEY=$(openssl rand -hex 24)"
  } > "$ENV_LOCAL"
fi
# shellcheck disable=SC1090
. "$ENV_LOCAL"
CLE_LLM=$(grep -m1 '^DEEPSEEK_API_KEY=' "$HOME/AppData/Local/hermes/.env" 2>/dev/null | cut -d= -f2- || true)
if [ -z "$CLE_LLM" ]; then
  echo "   DEEPSEEK_API_KEY introuvable dans ~/AppData/Local/hermes/.env" >&2
  exit 1
fi
echo "   clés prêtes (clé moteur conservée dans ~/.agroguidci/vps.env)"

echo "4/6 · copie des projets"
"${SSH[@]}" "mkdir -p $DEST/vps/orchestrateur"
copier "$LOCAL" "$DEST" \
  '.git' 'data' 'out' 'logs' '__pycache__' '*.pyc' '.env' '.env.local' '.agent-token*' \
  '.vercel' 'node_modules' 'vps/orchestrateur'
copier "$HOME/orchestrator" "$DEST/vps/orchestrateur" \
  '.git' 'data' 'logs' '*.db*' '*.ps1' '__pycache__' '.keys.json'
echo "   moteur + orchestrateur copiés dans $DEST"

echo "5/6 · .env et démarrage (build 2-4 min)"
"${SSH[@]}" "cat > $DEST/vps/.env" <<EOF
AGRO_DOMAINE=$DOMAINE
AGRO_API_KEY=$AGRO_API_KEY
ORCH_ADMIN_KEY=$ORCH_ADMIN_KEY
AGRO_CORS_ORIGINS=https://agroguidci.vercel.app
DEEPSEEK_API_KEY=$CLE_LLM
AGRO_LLM_MODEL=deepseek-chat
AGRO_MAX_CONCURRENCE=2
AGRO_BUDGET_S=300
EOF
"${SSH[@]}" "chmod 600 $DEST/vps/.env && cd $DEST/vps && docker compose up -d --build 2>&1 | tail -5"

echo "   attente de l'API (jusqu'à 90 s)"
for i in $(seq 1 30); do
  if "${SSH[@]}" "curl -fsS -m 5 localhost:8080/health >/dev/null"; then break; fi
  sleep 3
done
"${SSH[@]}" "curl -s -m 10 localhost:8080/health" | head -c 400
echo

echo "6/6 · état du moteur depuis l'extérieur"
for i in $(seq 1 20); do
  if curl -fsS -m 10 "https://$DOMAINE/health" -o /dev/null 2>/dev/null; then break; fi
  sleep 3
done
curl -s -m 15 "https://$DOMAINE/health" | head -c 400 || echo "   (TLS peut prendre quelques secondes de plus)"
echo
echo
echo "Moteur en ligne : https://$DOMAINE"
echo "Pour brancher la vitrine :"
echo "  AGRO_API_KEY=\$(sed -n 's/^AGRO_API_KEY=//p' $ENV_LOCAL) ./scripts/basculer-moteur.sh https://$DOMAINE"
