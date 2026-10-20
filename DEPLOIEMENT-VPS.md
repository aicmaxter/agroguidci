# Déployer le moteur AGROGUIDCI sur un VPS et y brancher la vitrine

La vitrine `https://agroguidci.vercel.app` reste statique sur Vercel ; le **moteur**
(orchestrateur + sept agents + API HTTP) tourne sur le VPS et c'est lui qui répond.
La page n'appelle jamais le VPS directement : elle passe par les fonctions
`api/demande.js` et `api/missions/[id].js` du projet Vercel, qui détiennent la clé.

```
navigateur ──▶ agroguidci.vercel.app/api/demande        (fonction Vercel, clé côté serveur)
                        │
                        ▼  HTTPS + X-API-Key
              api.<domaine>/api/demande  ──▶  serveur_api.py (VPS)
                                                  │
                                    orchestrateur (127.0.0.1:8000)
                                                  │
                                 6 sous-agents + agent principal
```

## 1. Ce qu'il faut sur le VPS

- Ubuntu 22.04/24.04 (ou Debian 12), 2 vCPU / 4 Go suffisent (les modèles tournent
  chez DeepSeek, pas sur la machine).
- Docker + le plugin compose :
  ```bash
  curl -fsSL https://get.docker.com | sh
  docker compose version
  ```
- Un (sous-)domaine, par exemple `api.agroguidci.org`, avec un enregistrement **A**
  vers l'IP du VPS (à faire avant le premier `up`, Caddy a besoin de le résoudre).
- Les ports 80 et 443 ouverts.

## 2. Copier les deux projets

Le moteur et l'orchestrateur sont deux dépôts distincts ; l'orchestrateur est copié
dans `vps/orchestrateur/` pour entrer dans l'image.

```bash
# depuis le poste de dev
ssh root@IP_DU_VPS 'mkdir -p /opt/agroguidci'

rsync -az --delete \
  --exclude '.git' --exclude 'data/' --exclude 'out/' --exclude 'logs/' \
  --exclude '__pycache__' --exclude '.env' --exclude '.agent-token*' \
  ~/agents/agroguidci/ root@IP_DU_VPS:/opt/agroguidci/

rsync -az --delete \
  --exclude '.git' --exclude 'data/' --exclude 'logs/' --exclude '*.db*' \
  ~/orchestrator/ root@IP_DU_VPS:/opt/agroguidci/vps/orchestrateur/
```

> Depuis Windows, `rsync` fonctionne dans Git Bash. À défaut : `scp -r` sur un
> `.tar.gz` produit par `tar czf agroguidci.tgz --exclude=data --exclude=out …`.

## 3. Renseigner les secrets

```bash
cd /opt/agroguidci/vps
cp .env.example .env
# clés à générer :
openssl rand -hex 32          # → AGRO_API_KEY
openssl rand -hex 24          # → ORCH_ADMIN_KEY
nano .env                     # AGRO_DOMAINE, DEEPSEEK_API_KEY, AGRO_CORS_ORIGINS
chmod 600 .env
```

`AGRO_API_KEY` sera aussi stockée côté Vercel (étape 6) : **la même valeur** des deux
côtés, sinon le proxy reçoit 401.

## 4. Démarrer

```bash
cd /opt/agroguidci/vps
docker compose up -d --build
docker compose ps
docker compose logs -f moteur        # doit montrer les agents qui s'enrôlent
```

Le premier build prend 2 à 4 minutes. Le conteneur `moteur` attend l'orchestrateur,
puis démarre les six sous-agents, l'agent principal et l'API sur `8080`.

## 5. Vérifier le moteur (côté VPS)

```bash
curl -s localhost:8080/health | head -c 400        # status ok, agents_en_ligne: 7
curl -s -H "X-API-Key: $AGRO_API_KEY" localhost:8080/api/etat | head -c 400
```

Puis une vraie mission, en mode asynchrone (recommandé) :

```bash
J=$(curl -s -X POST localhost:8080/api/demande \
  -H "X-API-Key: $AGRO_API_KEY" -H 'Content-Type: application/json' \
  -d '{"texte":"J ai 2 hectares a Bouake, je debute, budget 300 000 FCFA. Que cultiver ?","profil":{"localite":"Bouake","surface_ha":2},"async":true}')
echo "$J"                                        # {"id":"j_…","statut":"en_cours"}
curl -s -H "X-API-Key: $AGRO_API_KEY" localhost:8080/api/missions/$(echo "$J" | sed -n 's/.*"id":"\(j_[^"]*\)".*/\1/p')
```

De l'extérieur : `curl -s https://api.<domaine>/health` (TLS Caddy).

## 6. Brancher la vitrine

Depuis le poste de dev, dans le dépôt :

```bash
export AGRO_API_KEY=…            # la même clé que dans vps/.env
./scripts/basculer-moteur.sh https://api.agroguidci.org
```

Le script contrôle `/health`, teste la clé, écrit `AGRO_ENGINE_URL` et
`AGRO_ENGINE_KEY` dans les variables **Production** du projet Vercel
`agroguidci-site`, redéploie, puis lance une mission réelle à travers
`https://agroguidci.vercel.app/api/demande` et suit son état jusqu'à la réponse.

Équivalent manuel :

```bash
vercel env add AGRO_ENGINE_URL production     # https://api.agroguidci.org
vercel env add AGRO_ENGINE_KEY production     # la clé
vercel deploy --prod --yes
```

## 7. Exploitation

| Besoin | Commande |
|---|---|
| logs moteur | `cd /opt/agroguidci/vps && docker compose logs -f moteur` |
| logs orchestrateur | `docker compose logs -f orchestrateur` |
| redémarrer | `docker compose restart moteur` |
| mettre à jour le code | `rsync …` puis `docker compose up -d --build` |
| état des agents | `curl -s -H "X-API-Key: …" https://api.<domaine>/api/etat` |
| sauvegarde | volumes `orch-etat` (clés + base), `agro-data` (producteurs), `agro-out` (rapports) |

Sauvegarde simple :

```bash
docker run --rm -v agroguidci_orch-etat:/e -v agroguidci_agro-data:/d \
  -v "$PWD":/sauvegarde alpine tar czf /sauvegarde/agro-$(date +%F).tgz /e /d
```

**Validation humaine.** Sur le VPS, les actions sensibles (tâche planifiée, etc.)
restent des demandes : `python validation.py --lister` / `--approuver <id>` ne
fonctionne que dans le conteneur moteur :

```bash
docker compose exec moteur python validation.py --lister
```

**Capacité.** Une mission consomme 5 à 7 appels de modèle et 40 à 120 s.
`AGRO_MAX_CONCURRENCE=2` par défaut : au-delà, les demandes attendent (le moteur
répond `429` en mode synchrone, la file est assumée en mode asynchrone).

## 8. Variante sans Docker (systemd)

```bash
sudo useradd --system --home /opt/agroguidci agro
sudo python3 -m venv /opt/agroguidci/.venv
sudo /opt/agroguidci/.venv/bin/pip install -r /opt/agroguidci/requirements-moteur.txt
# orchestrateur comme service séparé :
sudo cp /opt/agroguidci/vps/agroguidci.service /etc/systemd/system/
sudo systemctl daemon-reload && sudo systemctl enable --now agroguidci
```

Dans ce mode, l'orchestrateur doit tourner à part sur `127.0.0.1:8000`
(`python orchestrateur.py` dans `/opt/orchestrateur`, mêmes `ORCH_LEASE=900` et
`ORCH_DELEGATE_TIMEOUT=420`), et `AGRO_KEYS` pointe vers son `.keys.json`.
Caddy s'installe alors avec `apt install caddy` et le `Caddyfile` fourni.

## 9. Ce que ce déploiement ne fait pas

- **Aucune authentification des producteurs** : la clé d'API protège le moteur des
  appels non autorisés, pas les usages. Ajouter des comptes (et des quotas par
  producteur) est une étape séparée.
- **Pas de file d'attente persistante** : les missions en cours vivent en mémoire du
  processus API ; un redémarrage les perd (les rapports déjà écrits restent dans
  `agro-out`).
- **Un seul worker API** : ne pas lancer `serveur_api.py` en plusieurs exemplaires
  sans externaliser l'état des missions.
