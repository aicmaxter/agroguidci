#!/usr/bin/env bash
# basculer-moteur.sh — branche la vitrine Vercel sur le moteur du VPS.
#
#   ./scripts/basculer-moteur.sh https://api.mon-domaine.tld
#   AGRO_API_KEY=... ./scripts/basculer-moteur.sh https://api.mon-domaine.tld
#
# Ce que fait le script :
#   1. vérifie que le moteur répond (/health) et qu'il accepte la clé ;
#   2. écrit AGRO_ENGINE_URL et AGRO_ENGINE_KEY dans les variables de production
#      du projet Vercel « agroguidci-site » (la clé ne transite jamais par la page) ;
#   3. redéploie et vérifie la chaîne complète vitrine -> moteur.
#
# La clé n'est jamais affichée : elle est lue dans AGRO_API_KEY (ou le 2e argument).
set -euo pipefail

URL="${1:-}"
CLE="${2:-${AGRO_API_KEY:-}}"
PROJET="${PROJET:-agroguidci-site}"
SITE="${SITE:-https://agroguidci.vercel.app}"

if [ -z "$URL" ]; then
  echo "usage : $0 https://api.mon-domaine.tld   (clé dans AGRO_API_KEY)" >&2
  exit 2
fi
if [ -z "$CLE" ]; then
  echo "clé absente : exporte AGRO_API_KEY avant de lancer (ou passe-la en 2e argument)" >&2
  exit 2
fi
URL="${URL%/}"

echo "1/4 · état du moteur $URL/health"
curl -fsS --max-time 20 "$URL/health" || { echo "moteur injoignable" >&2; exit 1; }
echo

echo "2/4 · contrôle de la clé (GET /api/etat)"
code=$(curl -s -o /dev/null -w "%{http_code}" --max-time 20 -H "X-API-Key: $CLE" "$URL/api/etat" || true)
case "$code" in
  200) echo "   clé acceptée" ;;
  401) echo "   clé refusée par le moteur (401) : vérifie AGRO_API_KEY" >&2; exit 1 ;;
  *)   echo "   réponse inattendue ($code) : on continue, à vérifier" >&2 ;;
esac

echo "3/4 · variables Vercel (production) sur $PROJET"
vercel env rm AGRO_ENGINE_URL production --yes >/dev/null 2>&1 || true
vercel env rm AGRO_ENGINE_KEY production --yes >/dev/null 2>&1 || true
printf '%s' "$URL" | vercel env add AGRO_ENGINE_URL production >/dev/null
printf '%s' "$CLE" | vercel env add AGRO_ENGINE_KEY production >/dev/null
echo "   AGRO_ENGINE_URL et AGRO_ENGINE_KEY écrites"

echo "4/4 · redéploiement de la vitrine"
vercel deploy --prod --yes >/dev/null
echo "   déployé"

echo
echo "vérification de la chaîne complète : $SITE/api/demande"
reponse=$(curl -sS --max-time 60 -X POST "$SITE/api/demande" \
  -H 'Content-Type: application/json' \
  -d '{"texte":"Verification de connexion : j ai 1 hectare de manioc a Daloa, comment ameliorer le rendement ?","profil":{"localite":"Daloa","surface_ha":1},"async":true}')
echo "   $reponse"

jid=$(printf '%s' "$reponse" | sed -n 's/.*"id":"\(j_[A-Za-z0-9]*\)".*/\1/p')
if [ -n "$jid" ]; then
  echo "   mission lancée ($jid) — suivi pendant 4 minutes max"
  for i in $(seq 1 48); do
    sleep 5
    etat=$(curl -sS --max-time 20 "$SITE/api/missions/$jid")
    statut=$(printf '%s' "$etat" | sed -n 's/.*"statut":"\([a-z_]*\)".*/\1/p')
    echo "   [$((i*5))s] statut=${statut:-?}"
    if [ "$statut" = "termine" ]; then
      printf '%s' "$etat" | sed -n 's/.*"etat_final":"\([A-Z_]*\)".*/   état final : \1/p'
      echo "OK — la vitrine parle au moteur du VPS."
      exit 0
    fi
    if [ "$statut" = "echec" ]; then
      echo "échec côté moteur : $etat" >&2
      exit 1
    fi
  done
  echo "la mission n'a pas conclu dans le délai : vérifie les logs du conteneur moteur" >&2
  exit 1
fi

# Le moteur a répondu de façon synchrone : la vitrine est branchée aussi.
if printf '%s' "$reponse" | grep -q '"data"'; then
  echo "OK — réponse synchrone reçue : la vitrine parle au moteur."
  exit 0
fi
echo "réponse inattendue : vérifie AGRO_ENGINE_URL / AGRO_ENGINE_KEY côté Vercel" >&2
exit 1
