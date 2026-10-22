# Contrat du chat agronome (v1)

Document de référence des routes de conversation. Il décrit ce qui est **implémenté
et testé en local**, pas un état de production.

## Chaîne d'appel

```
navigateur (chat.js)
   │  POST /api/conversations                        → session anonyme + fil
   │  POST /api/conversations/{id}/messages          → question (202)
   │  GET  /api/conversations/{id}                   → historique + états
   ▼
fonctions Vercel (api/conversations/*)  — clé du moteur côté serveur, cookie HttpOnly
   ▼
moteur FastAPI (serveur_api.py)
   ├─ POST /api/sessions            → jeton (rendu une seule fois, stocké haché)
   ├─ POST /api/conversations       → conversation_id (cnv_ + 32 hex)
   ├─ POST /api/conversations/{id}/messages → message_id, statut en_cours
   └─ GET  /api/conversations/{id}  → messages, statuts, sources
   ▼
Coordonnateur (agent principal « Agent Agronome Expert ») → /delegate → sous-agents
   ▼
verification.py → enveloppe JSON → message assistant enregistré en base
```

## Modèle de session

- Jeton : 32 octets aléatoires (`secrets.token_urlsafe(32)`), transmis une seule fois.
- Stockage : **SHA-256 du jeton** dans `sessions.token_hash`. Le jeton en clair n'existe
  que dans le cookie posé par Vercel : `HttpOnly; Secure; SameSite=Lax; Path=/; Max-Age=2592000`.
- Durée : 30 jours glissants (prolongée à chaque appel réussi).
- Toute conversation est rattachée à une session ; une conversation d'une autre session
  renvoie **404**, jamais 403 (pas de révélation d'existence).

## Contrat de réponse

`GET /api/conversations/{id}`

```json
{
  "conversation_id": "cnv_…",
  "culture_id": "igname",
  "localite": "Bouaké",
  "statut": "active",
  "cree_le": 1760000000,
  "expire_le": 1767776000,
  "messages": [
    { "message_id": "msg_…", "role": "user", "contenu": "…", "statut": "termine",
      "mission_id": null, "erreur": null, "sources": [], "cree_le": 1760000000 },
    { "message_id": "msg_…", "role": "assistant", "contenu": "…", "statut": "termine",
      "mission_id": "mis_20261021-…", "erreur": null, "sources": [], "cree_le": 1760000042 }
  ]
}
```

Statuts de message : `en_cours`, `termine`, `echec`, `clarification`, `escalade`.
Correspondance avec les états du moteur (`mission.py`) :

| état moteur | statut du message |
|---|---|
| TERMINEE_VERIFIEE | termine |
| EN_ATTENTE_INFORMATION | clarification |
| A_VALIDER / ESCALADE_HUMAINE / ARRETEE_PERMISSION | escalade |
| ECHEC_OUTIL ou autre | echec |

## Erreurs

| Code | Sens |
|---|---|
| 400 | message invalide (moins de 2 ou plus de 2000 caractères), corps JSON invalide, identifiant de conversation mal formé |
| 401 | session absente ou expirée |
| 404 | conversation inconnue **ou appartenant à une autre session** |
| 405 | méthode non autorisée |
| 429 | quota (prévu, **non activé** : valeurs non validées) |
| 502 | moteur injoignable ou erreur interne |
| 504 | moteur muet au-delà du délai |

Aucune réponse d'erreur ne contient de trace interne, de chemin ni de clé.

## Contexte de culture

Le navigateur peut envoyer `culture_id`, `localite`, `stade`. Le serveur les valide
(troncature stricte, liste de champs fermée) et les ajoute au texte sous la forme
« Contexte fourni par la page — culture : … · localité : … ». **Le navigateur ne peut
jamais désigner un agent, une capacité ou un outil.**

## Idempotence

`POST /api/conversations/{id}/messages` accepte `idempotency_key`. Contrainte en base :
`UNIQUE(conversation_id, idempotency_key)`. Un second envoi avec la même clé renvoie
**200** avec le message existant (`rejoue: true`) au lieu de créer une seconde mission.

## Quotas proposés (NON appliqués)

| Limite | Valeur proposée |
|---|---|
| messages par session et par heure | 20 |
| messages par IP et par jour | 40 |
| conversations actives par session | 5 |
| taille maximale d'un message | 2 000 caractères |

Ils figurent dans `conversations.QUOTAS_PROPOSES` mais aucun contrôle ne les applique :
la validation de ces valeurs est une décision humaine (D-5).

## Ce qui reste à faire pour la production

1. Fournir `AGRO_CONVERSATIONS_DB` sur le volume `agro-data` et vérifier les droits (uid 10001).
2. Ajouter la signature HMAC Vercel → VPS (proposition dans le rapport, non activée).
3. Activer les quotas après validation.
4. Planifier la purge quotidienne (`scripts/purge_conversations.py`).
5. Tester la restauration d'une sauvegarde avant ouverture au public.
