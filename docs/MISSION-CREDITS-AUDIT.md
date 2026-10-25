# Audit initial — crédits, offres, chat (mission AGROGUIDCI)

Date : 2026-10-25 · branche `main` · HEAD `3629063` (arbre propre)

## Constats

| Sujet | État réel |
|---|---|
| Dépôt | `~/agents/agroguidci`, `main` = `origin/main` = `3629063` |
| Offres | 3 cartes : Gratuit (2 conseils/jour), Crédits 599 FCFA / **10** conseils, **Suivi 9 900 FCFA/mois** |
| Crédits | **uniquement côté navigateur** : `localStorage["agro.credits.v2"]`, 2/jour, remise à zéro par date locale |
| « Recharge » | bouton `#creditsRecharge` → **crédite 10 crédits localement sur simple clic** (simulation, à supprimer) |
| Chat | `/api/conversations*` (fonctions Vercel) → moteur VPS, session anonyme HttpOnly, jetons hachés en SQLite |
| Session | serveur : table `sessions` (token_hash, expires_at) — base saine pour un solde serveur |
| Paiement | **aucune intégration** (ni Stripe, ni mobile money, ni webhook) |
| Boutons conseil | hero, header (`Conseil gratuit`), onglet Conseil, formulaire, carte Gratuit (tarifs), bandeau final, fiches cultures |
| Caddy VPS | chemins autorisés listés explicitement (`/health`, `/api/demande`, `/api/sessions`, `/api/conversations*`…) |
| Secrets | `AGRO_ENGINE_KEY`/`AGRO_ENGINE_URL` côté Vercel, clé moteur sur le VPS — jamais dans le dépôt |

## Décisions (règle retenue, documentée)

- **Renouvellement** : automatique au passage de fenêtre (l'implémentation existante remettait
  déjà le quota à zéro automatiquement, sans action de l'utilisateur) — 15 crédits par fenêtre
  de 7 h, calcul en UTC, idempotent par `(session, période)`.
- **Coût** : 1 crédit par consultation **réussie**. Débit après production de la réponse,
  idempotent par `message_id` ; refus 402 avant exécution si solde nul.
- **Achats** : packs affichés, paiement **indisponible** (aucune intégration fiable) — aucun
  crédit attribué sur clic.
- **Suivi personnalisé** : retiré des offres (aucune page dédiée n'existe, donc rien à masquer).

## Fichiers à modifier

`conversations.py`, `serveur_api.py`, `api/credits.js` (nouveau), `vps/Caddyfile`,
`web/index.html`, `web/assets/ui.js`, `web/assets/chat.js`, `web/assets/site.css`,
`scripts/build_cultures.py` (version CSS), `tests_credits.py` (nouveau),
`tests_vitrine_v9.py`, `tests_confidentialite.py`, `README.md`.
