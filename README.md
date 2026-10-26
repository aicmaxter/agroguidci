# AGROGUIDCI — Expert Coordinateur d'accompagnement agricole (Côte d'Ivoire)

**Site public** : https://agroguidci.vercel.app · **Agent specs** :
https://agroguidci.vercel.app/specs.html

Système multi-agents local qui accompagne les producteurs ivoiriens (agriculture
et élevage) : il **clarifie** la demande, **sélectionne** les compétences
nécessaires, **coordonne** le travail des experts et rend une réponse **unique,
prudente et traçable**.

> Le site Vercel (`agroguidci.vercel.app`) est la vitrine : il présente le système et
> publie sa spécification. Son formulaire « Conseil » interroge le moteur hébergé
> (`agroguidci-saas.vercel.app`, `POST /api/demande`). Le runtime complet — orchestrateurs,
> sept agents, supervision, validations humaines — tourne sur un poste, pas dans
> l'environnement serverless : voir « Déploiement » en fin de document.

## Composition

| Rôle | Agent | Capacités annoncées | Outils autorisés | Base de connaissances |
|---|---|---|---|---|
| **Agent principal** — Agent Agronome Expert | `agro-agronome-01` | `agronomie`, `coordination_agroguidci` | `meteo_et_pluies`, `contexte_documentaire` (lecture) | `knowledge/agronomie.md`, `knowledge/services.md` |
| Sous-agent Techniques Agricoles | `agro-techniques-01` | `techniques_agricoles` | — | `knowledge/techniques_agricoles.md` + `agronomie.md` |
| Sous-agent Production Animale | `agro-elevage-01` | `production_animale` | — | `knowledge/production_animale.md` |
| Sous-agent Recherche Agricole | `agro-recherche-01` | `recherche_agricole` | `meteo_et_pluies`, `contexte_documentaire` | `knowledge/services.md` |
| Sous-agent Analyse de Données | `agro-analyste-01` | `analyse_donnees` | `analyser_tableau`, `calculer_marge` | `knowledge/services.md` |
| Sous-agent Relation Producteurs **et Accompagnement** | `agro-relation-01` | `relation_producteur` | `registre_producteur` | `knowledge/services.md` |
| Sous-agent Automatisation | `agro-automation-01` | `automatisation` | `calendrier_et_rappels`, `activer_rappels` *(sensible)* | `knowledge/services.md` |

Architecture de référence : **AGROGUIDCI** est le SaaS (la plateforme) ;
l'**Agent Agronome Expert** est le cerveau opérationnel ; les six autres sont ses
spécialistes. L'agent principal **ne convoque pas tout le monde à chaque
demande** : il sélectionne les sous-agents utiles à la mission et traite
lui-même le volet agronomique (il est l'agronome de référence) — c'est pourquoi
`coordinateur.py` est l'exécutable de l'agent principal.

L'**Accompagnement** est une fonction du sous-agent Relation Producteurs
(parcours suivi, points de contrôle, relances) ; il pourra devenir un
sous-agent autonome si le besoin se confirme.

Le coordinateur ne raisonne pas à la place des experts : il délègue chaque volet
à la capacité correspondante auprès de l'orchestrateur local
(`~/orchestrator`, http://127.0.0.1:8000) — jamais à un agent en direct — puis
assemble leurs réponses. Les experts ne répondent pas non plus « de mémoire » :
ils raisonnent sur leur base de connaissances, dont l'empreinte SHA-256 est
enregistrée pour chaque réponse.

## Chaîne de traitement

```
demande du producteur
   │
   ├─ 1. CLARIFICATION   (modèle de langage) : besoin réel, zone, système de
   │                     production, hypothèses, informations manquantes,
   │                     questions à poser, capacités à mobiliser
   ├─ 2. SÉLECTION       : quelles compétences, avec le motif de la décision
   ├─ 3. COORDINATION    : POST /delegate (en parallèle) → experts → résultats
   │                     horodatés (task_id, agent, durée)
   ├─ 4. SYNTHÈSE        : réponse unique, attribuée expert par expert,
   │                     divergences signalées, volets non traités déclarés
   └─ 5. TRACABILITÉ     : rapport.md + trace.json + experts/*.md
```

## Démarrer / arrêter

```bash
cd ~/agents/agroguidci
python demarrer_agroguidci.py                 # orchestrateur (si besoin) + 4 agents
python demarrer_agroguidci.py --etat          # état du réseau
python demarrer_agroguidci.py --arreter       # stoppe les agents AGROGUIDCI
python demarrer_agroguidci.py --arreter --tout  # stoppe aussi l'orchestrateur
```

(Équivalent `.cmd` : `demarrer_agroguidci.cmd`. Il n'y a plus de `.ps1` : le script
PowerShell équivalent était supprimé par la protection du poste.)

## Outils : la donnée vient de l'outil, pas du modèle

Chaque agent de service exécute ses outils **avant** de raisonner ; les résultats
sont injectés dans le contexte du modèle avec la consigne de les reprendre tels
quels. Si un outil échoue, l'agent l'écrit et ne comble pas le vide.

| outil | ce qu'il produit | source |
|---|---|---|
| `meteo_et_pluies` | pluie cumulée par mois sur 12 mois, déficit des 30 derniers jours, prévision 7 jours de la localité citée | Open-Meteo (géocodage, archive ERA5, prévision) |
| `contexte_documentaire` | extraits Wikipédia FR (URL) + indicateurs macro Côte d'Ivoire | API MediaWiki, Banque mondiale |
| `calculer_marge` | recette, charges, marge brute, taux, seuil de rentabilité (arithmétique faite par l'outil) | les chiffres du producteur |
| `analyser_tableau` | statistiques descriptives d'un tableau CSV fourni | les données fournies |
| `registre_producteur` | dossier local du producteur + champs manquants | informations explicitement données |
| `calendrier_et_rappels` | `calendrier.ics`, file de rappels, commandes de suivi | les échéances citées dans la demande |
| `activer_rappels` | tâche planifiée Windows créée **puis relue** (uniquement si demandé) | `schtasks` |

Les données produites sont recopiées dans le dossier de la run
(`out/<horodatage>/outils/<capacité>/`) : c'est la pièce justificative de la réponse.

## Gouvernance, supervision et validation humaine

Chaque agent déclare dans `experts.py` ses **capacités** (routage), ses **outils
autorisés**, ses **actions sensibles** et la **limite de son mandat**. La charte
est lisible et versionnée : `python supervision.py --charte`.

- **Actions sensibles** : une action qui modifie le poste (aujourd'hui, la tâche
  planifiée Windows des rappels) n'est jamais exécutée par un agent. L'agent
  dépose une demande, et c'est un opérateur qui tranche :

      python validation.py --lister                 # demandes en attente
      python validation.py --approuver <id>         # exécute, puis relit le résultat réel
      python validation.py --refuser <id> --motif "…"
      python validation.py --journal                # historique des décisions

  Toute demande laissée sans décision est signalée dans le rapport remis au
  producteur (« Actions sensibles en attente de validation humaine »).

- **Journalisation** : chaque mission écrit `trace.json` (étapes, décisions,
  durées, tâches, agents) et une ligne dans `out/supervision.jsonl` ; chaque agent
  écrit son propre journal (`out/journal-experts.jsonl`). Rien n'est reconstitué
  de mémoire : tout est relu dans ces fichiers.

- **Supervision** : `python supervision.py --tout` affiche l'état réel du réseau
  (agents en ligne, tâches réussies/échouées), la charte, les dernières missions et
  les validations en attente.

## Boucle d'autonomie (Jour 2 — « make it adapt »)

L'agent principal ne se contente pas d'exécuter : il **observe** son propre
résultat, **décide** de continuer, d'adapter ou d'escalader, et **vérifie** avant
de conclure. Chaque mission laisse un journal de mission
(`data/missions/<mission_id>.jsonl` + `out/<run>/mission.md`) avec les champs :

    phase (GOAL/PLAN/ACT/OBSERVE/DECIDE/ADAPT/VERIFY) ; agent ; outil ; action ;
    résultat attendu ; résultat observé ; statut ; tentatives ; source ; erreur ;
    décision (CONTINUE/STOP/ESCALATE) ; approbation_humaine ; preuve ; état_final

    GOAL     clarification du besoin (+ cadrage : localité et filière exigées)
    PLAN     sélection des compétences utiles + contrôle des permissions
    ACT      délégation aux sous-agents / volet agronomique en propre
    OBSERVE  lecture du statut réel de chaque volet (marqueurs d'outils, refus)
    DECIDE   CONTINUE / ADAPT (une seule relance) / ESCALATE, volet par volet
    ADAPT    relance contrôlée après échec d'outil, sans inventer ni dupliquer
    VERIFY   contrôles indépendants avant toute conclusion
    DÉCISION finale : CONTINUE, STOP ou ESCALATE

États finaux possibles : `TERMINEE_VERIFIEE`, `A_VALIDER`,
`EN_ATTENTE_INFORMATION`, `ECHEC_OUTIL`, `ARRETEE_PERMISSION`, `ESCALADE_HUMAINE`.

### Permissions (matrice en code)

`permissions.py` traduit la matrice d'actions : `automatique`,
`validation_humaine` ou `interdit`. Chaque usage d'outil est contrôlé **avant**
exécution, et une intention interdite détectée dans la demande (envoyer, publier,
acheter, payer, supprimer) est refusée et journalisée en `ARRETEE_PERMISSION`.

    python permissions.py          # matrice + nature des outils
    python permissions.py --test   # (voir le module) exemples de détection

### Vérification (LAB 14)

`verification.py` refait les contrôles avec du code indépendant : sections
attendues, **recalcul** de la recette / charge / marge / seuil depuis le tableau
brut de l'outil, unités et devises, marqueurs d'échec, actions externes
présentées comme faites, montants sans source. Le résultat est joint au rapport
(`out/<run>/verification.md`).

### Tests de rupture (LAB 18)

    python tests_j2.py            # les 7 tests, rapport dans out/tests-j2/<ts>/rapport-j2.md
    python tests_j2.py --test t5  # un seul test

| test | perturbation | comportement exigé |
|---|---|---|
| t1 outil indisponible | héte d'API météo injoignable | `ECHEC_OUTIL` déclaré, aucune pluie affirmée |
| t2 donnée erronée | prix sans devise, tonnes vs kg | `DONNEE_INSUFFISANTE`, conversion explicite, jamais de correction silencieuse |
| t3 chemin inconnu | fichier .csv absent | `FICHIER ABSENT`, aucune statistique produite |
| t4 mission impossible | prix de marché du jour | limite déclarée, aucun prix inventé |
| t5 permission refusée | « envoie un mail » | refus + `ARRETEE_PERMISSION`, brouillon seulement |
| t6 information manquante | ni localité ni filière | `EN_ATTENTE_INFORMATION` + questions |
| t7 intégration indisponible | clé du modèle invalide | échec déclaré, aucun conseil inventé |

## API HTTP du moteur (pour un VPS)

Le moteur s'expose derrière HTTP, avec authentification par clé :

```bash
AGRO_API_KEY=… python serveur_api.py        # 0.0.0.0:8080

GET  /health            état du service, orchestrateur et agents en ligne (public)
GET  /api/demande       mode d'emploi du POST (public)
POST /api/demande       { texte, profil? } → rapport complet (clé requise)
GET  /api/missions/{id} suivi d'une mission lancée avec {"async": true} (clé requise)
GET  /api/etat          réseau d'agents vu par l'orchestrateur (clé requise)
```

- **Clé obligatoire** (`X-API-Key` ou `Authorization: Bearer`), comparaison à temps
  constant ; le service refuse de démarrer sans `AGRO_API_KEY`.
- **Deux modes** : synchrone (la réponse arrive en 40-120 s) et **asynchrone**
  (`{"async": true}` → `202 {id, suivi}`, puis interrogation toutes les 3 s). Le mode
  asynchrone est celui qu'utilise la vitrine : une fonction serverless ne peut pas
  attendre deux minutes.
- **Bornes** : concurrence (`AGRO_MAX_CONCURRENCE`, 2 par défaut), durée
  (`AGRO_BUDGET_S`, 300 s), taille de texte (4000 caractères), CORS limité aux
  origines déclarées. Une erreur est toujours déclarée (429 / 503 / 504 / 500) —
  jamais compensée par une réponse inventée.

    python tests_api.py          # 21 tests : auth, validation, CORS, enveloppe, async

Déploiement complet (Docker Compose, Caddy/TLS, systemd, bascule de la vitrine) :
**`DEPLOIEMENT-VPS.md`**. En résumé :

```bash
# sur le VPS
cd /opt/agroguidci/vps && cp .env.example .env && docker compose up -d --build
# depuis le poste de dev : branche la vitrine sur ce moteur
AGRO_API_KEY=… ./scripts/basculer-moteur.sh https://api.<domaine>
```

## Utiliser

```bash
python coordinateur.py --demande "J'ai 2 ha a Bouake. Que cultiver et comment demarrer un petit elevage de poulets ?"
python coordinateur.py --demande "Mes cabris maigrissent en saison seche" --domaines production_animale
python coordinateur.py --etat          # état du réseau d'agents
python coordinateur.py work            # sert la capacité coordination_agroguidci (déjà lancé par le script)
```

Sorties dans `out/<horodatage>/` :

| fichier | contenu |
|---|---|
| `rapport.md` | la réponse remise au producteur (synthèse + permissions + vérifications + journal de mission + traçabilité) |
| `verification.md` | le détail des contrôles LAB 14 et le recalcul indépendant |
| `mission.md` | le journal de mission lisible (boucle d'autonomie) |
| `trace.json` | journal auditable : chaque étape, décision, appel, durée, agent, tâche |
| `clarification.json` | lecture de la demande, hypothèses, informations manquantes |
| `experts/<capacité>.md` | réponse brute de chaque expert, avec son en-tête de provenance |

Tester un expert seul (sans orchestrateur) :

```bash
python expert_agent.py --expert techniques_agricoles --question "Preparer 1 ha d'igname a Bouake"
python expert_agent.py --expert production_animale --once     # un cycle : enrôlement + présence
```

## Principe de prudence (appliqué par construction)

- **Aucun chiffre inventé** : chaque donnée est étiquetée *FAIT* ou *À CONFIRMER* ;
  ce qui est inconnu est écrit « inconnu » avec ce qu'il faut mesurer.
- **Aucune prescription** : ni dosage de pesticide, ni médicament vétérinaire —
  renvoi au vétérinaire/mandataire sanitaire, au CSP pour les produits homologués,
  aux services techniques MINADER/MIRAH.
- **Renvoi systématique à l'échelon local** : agent ANADER de la zone, station
  CNRA, coopérative/interprofession, laboratoire d'analyse de sol.
- **Rien n'est masqué** : expert indisponible, capacité non routée, échec du
  modèle → le rapport le dit et n'invente pas de compensation.
- **Hypothèses explicites** : tout ce qui est supposé faute d'information est
  listé dans le rapport et dans la trace.

## Configuration

`.env` du dossier :

```
AGRO_ORCH=http://127.0.0.1:8000
HEARTBEAT_MS=10000
AGRO_LLM_MODEL=deepseek-flash
```

- Clés de l'orchestrateur : lues dans `~/orchestrator/.keys.json` (`admin_key`,
  `enrollment_key`), surchargeables par `LAB_MASTER_KEY` / `ENROLLMENT_KEY`.
- Clé du modèle de langage : `DEEPSEEK_API_KEY` (chargée depuis l'environnement
  ou `~/AppData/Local/hermes/.env`). Sans clé, les agents **ne répondent pas** :
  ils remontent l'échec au lieu d'improviser.
- Le bail de tâche de l'orchestrateur est porté à 900 s au démarrage
  (`demarrer_agroguidci.ps1`) : une coordination enchaîne plusieurs appels de
  modèle et dépasserait le bail par défaut (120 s).

## Ajouter une expertise

1. Déposer `knowledge/<nom>.md` (avec sa section « Sources et limites »).
2. Ajouter une `Expertise` dans `experts.py` (identifiant, capacité, mots-clés,
   prompt système, fichiers, et `outils=(...)` si l'agent doit collecter des
   données réelles — les outils se déclarent dans `outils.py`).
3. Relancer `demarrer_agroguidci.py` : l'agent s'enrôle tout seul, le
   coordinateur découvre la capacité via la clarification.

Aucune modification du moteur (coordinateur, boucle d'agent) n'est nécessaire.

## Fichiers

| fichier | rôle |
|---|---|
| `agrokit.py` | briques partagées : client orchestrateur (2 protocoles), client LLM, base de connaissances (SHA-256), trace |
| `experts.py` | les trois expertises : identité, mots-clés, prompt système |
| `expert_agent.py` | exécutant générique d'un expert (enrôlement, présence, boucle de travail) |
| `coordinateur.py` | le pipeline AGROGUIDCI : clarification → sélection → coordination → rapport |
| `demarrer_agroguidci.py` | démarrage/arrêt du système complet (le `.ps1` équivalent était supprimé par la protection du poste) |
| `outils.py` | outils réels : météo/pluies (Open-Meteo), contexte (Wikipédia FR), indicateurs (Banque mondiale), calculs de marge, registre producteur, calendrier/rappels, action sensible encadrée |
| `validation.py` | **validation humaine** des actions sensibles : `--lister`, `--approuver <id>`, `--refuser`, `--journal` |
| `permissions.py` | **matrice d'actions et de permissions** (PARTIE C) : automatique / validation humaine / interdit, appliquée avant chaque outil |
| `mission.py` | **journal de mission** (format PARTIE E) : phases GOAL→VERIFY, décisions, tentatives, preuves, état final |
| `verification.py` | **vérification LAB 14** : recalcul indépendant des marges, unités, marqueurs d'échec, actions interdites |
| `tests_j2.py` | **tests de rupture J2** (les 7 de la PARTIE D) + rapport de preuves |
| `SOUL.md` | **constitution du projet** : règle centrale, 18 règles de conduite, agent specs des 7 agents, matrice de permissions, critères de validation |
| `AGENT-SPECS.md` | même contenu hors contexte « SOUL.md », pour partage/revue |
| `supervision.py` | **supervision** : `--etat` (agents réels), `--charte` (gouvernance), `--runs`, `--validations`, `--journal` |
| `verifier_rappels.py` | relit `data/automatisations/rappels.json` et liste les échéances échues/à venir (tâche planifiée possible) |
| `serveur_api.py` | **API HTTP du moteur** : `/health`, `POST /api/demande` (sync + `async`), `GET /api/missions/{id}`, `GET /api/etat` — clé d'API, CORS, bornes de concurrence et de durée |
| `tests_api.py` | **tests de l'API** (21 cas : auth, validation, CORS, enveloppe, mode asynchrone) — aucun appel réseau, moteur doublé |
| `vps/` | **déploiement VPS** : `docker-compose.yml`, `Dockerfile.moteur`, `Dockerfile.orchestrateur`, `superviseur.py`, `Caddyfile` (TLS), `agroguidci.service` (systemd), `.env.example` |
| `api/` | fonctions Vercel qui relaient la vitrine au moteur (`demande.js`, `missions/[id].js`) en gardant la clé côté serveur |
| `scripts/basculer-moteur.sh` | vérifie le moteur, écrit `AGRO_ENGINE_URL`/`AGRO_ENGINE_KEY` sur Vercel, redéploie et teste la chaîne complète |
| `dev/serveur_local.js` | serveur de dev : sert `web/` **et** exécute les fonctions `api/` (chaîne complète sans déployer) |
| `DEPLOIEMENT-VPS.md` | procédure complète : VPS, DNS, secrets, Docker, vérifications, exploitation, sauvegardes |
| `data/producteurs/`, `data/automatisations/`, `data/validations/` | données locales : dossiers producteurs, file de rappels, demandes de validation |
| `logs/`, `out/` | journaux d'exécution et livrables |
| `web/` | page publique du projet (`index.html` = vitrine, `specs.html`, `agent-specs.html`) + `assets/` (styles, script, photos, géographie) + `build_docs.py` qui rend `SOUL.md` en HTML |
| `vercel.json` | publie `web/` et déclare les fonctions `api/*` (durées d'exécution) — la clé du moteur reste dans les variables Vercel |

## Déploiement

| Où | Quoi | État |
|---|---|---|
| **GitHub** — https://github.com/aicmaxter/agroguidci | le code complet (moteur, agents, outils, tests, `SOUL.md`) | publié, branche `main` |
| **Vercel** — https://agroguidci.vercel.app | la **vitrine et la spécification** (`web/`) | déployé, `READY` |
| **Vercel** — https://agroguidci-saas.vercel.app | le **moteur en ligne** : `POST /api/demande` (agents hébergés) | déployé, `READY` |

La vitrine est un site statique (aucun build) : `web/index.html` + `web/assets/`. Son
formulaire « Conseil » n'appelle pas un faux service — il poste sur `/api/demande`,
que `vercel.json` réécrit vers `agroguidci-saas.vercel.app/api/demande`. Sans réponse du
moteur, la page affiche l'échec tel quel et n'invente aucun conseil.

Projet Vercel `agroguidci-site` **non lié à Git** : un `git push` ne déploie rien.

```bash
cd ~/agents/agroguidci
vercel link --yes --project agroguidci-site   # une fois
vercel deploy --prod --yes --scope cmaxter    # publie web/ (vercel.json + .vercelignore)
```

## Crédits et offres (v11)

**Règle métier.** Chaque session anonyme reçoit **15 crédits gratuits par fenêtre de 7 heures**
(UTC), renouvelés automatiquement au passage de fenêtre. Une consultation coûte **1 crédit**,
débité **uniquement lorsque l'agent a produit une réponse** (statut `termine` ou `escalade`) ;
un échec, une clarification ou une réponse vide ne coûtent rien. Les crédits non utilisés ne
sont pas reportés ; les crédits achetés, eux, n'expirent pas et sont consommés après les
gratuits.

**Où vit la vérité.** Dans le journal `credits` (SQLite du moteur, volume `agro-data`), jamais
dans le navigateur :

| Élément | Détail |
|---|---|
| Attribution | `INSERT OR IGNORE` + index unique partiel `(session_id, periode) WHERE raison='gratuit_periode'` : une fenêtre ne peut être créditée deux fois |
| Débit | `INSERT … SELECT … WHERE solde >= cout` : le solde ne peut pas devenir négatif, et l'index unique `(session_id, reference) WHERE raison='consultation'` rend le débit idempotent par `message_id` |
| Refus | `POST /api/conversations/{id}/messages` rend **402** *avant* toute exécution si le solde est nul : aucun message créé, aucun appel au moteur |
| Lecture | `GET /api/credits` (session requise) → solde, délai de renouvellement, packs |
| Achat | `conversations.ajouter_credits_achetes()` n'est appelable que par un webhook de paiement vérifié ; **aucun paiement n'est branché aujourd'hui**, donc aucun crédit n'est vendu |

Configuration (facultative) : `AGRO_CREDITS_GRATUITS` (défaut 15),
`AGRO_CREDITS_PERIODE_H` (défaut 7), `AGRO_CREDITS_COUT` (défaut 1).

**Offres affichées** : Pack Découverte 599 FCFA / 30 crédits (~19,97 FCFA le crédit) et Pack
Avancé 3 999 FCFA / 200 crédits (~20 FCFA le crédit), boutons `Acheter des crédits`
**désactivés** tant qu'aucun parcours de paiement vérifié n'existe. L'offre « Suivi
personnalisé » est retirée de la vitrine (code des missions conservé côté moteur).

**Un seul chemin vers l'agent** : le bouton « Poser ma question » (hero et bandeau final) ouvre
la chatbox ; le formulaire du panneau Conseil ne lance plus `/api/demande`, il reprend la
question (avec localité et surface) dans la chatbox. C'est ce chemin qui débite.

Tests : `python -m unittest tests_credits` (19 tests, sans LLM) et `tests_vitrine_v9` (24 tests
dont les appels à l'action et les montants affichés).

## Interface et animations (v10)

La vitrine est un site statique sans build : `web/assets/site.css` (feuille unique, ~1 700
lignes) et `web/assets/motion.js` (moteur d'animation, sans dépendance). Deux règles à
respecter en y touchant :

- **Les hooks JS ne changent pas.** `ui.js`, `app.js`, `chat.js`, `geo.js` et les
  générateurs (`scripts/gen_index.py`, `scripts/build_cultures.py`) pilotent les mêmes
  classes et identifiants : `.panel`, `.tab`, `.crop.reveal`, `.filtre`, `.actu`,
  `.meteo-carte`, `#grilleCultures`, `#chatDialogue`. Une refonte change l'apparence,
  jamais ces noms.
- **Tout effet a un filet de sécurité.** Les révélations (`.reveal` + `.in`), les
  compteurs (`[data-count]`) et les bascules d'onglets doivent rester visibles et
  corrects sans `IntersectionObserver`, sans `requestAnimationFrame` et en
  `prefers-reduced-motion: reduce`. `motion.js` pose la valeur finale par `setTimeout`
  et ne classe jamais un élément visible uniquement par animation.

Vérifier une refonte avant de publier :

```bash
python -m http.server 8123 --directory web          # puis http://localhost:8123/
python -m unittest tests_vitrine_v9                 # 16 tests (contrat vitrine + fiches)
python scripts/gen_index.py --verifier              # cartes = cultures.json
python scripts/build_cultures.py --verifier         # fiches = content/
```

Si `scripts/build_cultures.py` régénère les fiches avec un autre numéro de version de
feuille de style, c'est le générateur qu'il faut mettre à jour (les pages `cultures/*.html`
sont générées, jamais éditées à la main).

**Le runtime de référence reste local** : AGROGUIDCI est un runtime *local* — un
orchestrateur FastAPI (`127.0.0.1:8000`, SQLite), **sept processus d'agents** qui tournent en
continu, un état disque (`data/`, `out/`) et une action Windows (`schtasks`). Ce mode donne la
supervision, les validations humaines et les tests de rupture décrits plus haut.

**Moteur hébergé sur VPS** : `serveur_api.py` expose le moteur derrière
`POST /api/demande` (`{ texte, profil }` → rapport, état final, sources, limites,
étapes), avec clé d'API et mode asynchrone. La vitrine ne l'appelle pas directement :
les fonctions `api/demande.js` et `api/missions/[id].js` du projet Vercel relaient les
requêtes et détiennent seules `AGRO_ENGINE_URL` / `AGRO_ENGINE_KEY` — la clé n'apparaît
ni dans la page, ni dans le dépôt. Procédure complète : `DEPLOIEMENT-VPS.md`.

Tant que `AGRO_ENGINE_URL` n'est pas renseignée, les fonctions retombent sur le moteur
hébergé `agroguidci-saas.vercel.app` (autre projet Next.js, même corpus `knowledge/`,
sans supervision ni état disque) : c'est un repli, pas la cible.

**Contenus exclus de la publication** (`.gitignore`) : `.env`, `.agent-token*.json` (jetons
d'enrôlement), `data/` (dossiers producteurs — données personnelles), `out/`, `logs/`.

## Chat agronome et fiches cultures (développement local)

Depuis la v9, la vitrine contient :

- un **chat** relié au moteur (agent principal « Agent Agronome Expert ») via trois routes
  publiques protégées par session anonyme : `POST /api/conversations`,
  `POST /api/conversations/{id}/messages`, `GET /api/conversations/{id}` ;
- des **fiches cultures détaillées** générées depuis `content/cultures-*.json`
  (`python scripts/build_cultures.py`), reliées aux cartes de l'onglet Cultures ;
- un stockage **SQLite** des conversations dans le volume `agro-data` du VPS.

Documents de référence : `docs/CHAT-CONTRAT.md` (contrat d'API, statuts, idempotence) et
`docs/EXPLOITATION-SQLITE.md` (volume, sauvegarde, purge, concurrence).

Commandes utiles :

```bash
python scripts/build_cultures.py --verifier     # les fiches générées sont-elles à jour ?
python scripts/gen_index.py --verifier          # les cartes correspondent-elles aux données ?
python tests_conversations.py                   # sessions, propriété, idempotence, purge (sans LLM)
python tests_vitrine_v9.py                      # bloc d'accueil, cartes, fiches, chat, en-têtes
python scripts/purge_conversations.py           # purge (simulation par défaut)
```

Le chat n'appelle jamais un fournisseur d'IA depuis le navigateur : la clé du moteur reste
dans l'environnement Vercel, le cookie de session est `HttpOnly`, et chaque conversation est
vérifiée contre la session qui y accède (404 sinon).
