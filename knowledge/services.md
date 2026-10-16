# Base de connaissances des agents de service AGROGUIDCI

Document de référence des quatre agents de service : **Recherche**, **Analyse de
données**, **Relation producteur**, **Automatisation**. Il ne remplace pas les
bases métier (agronomie, techniques agricoles, production animale) : il décrit
les outils réels dont disposent ces agents et les règles d'honnêteté qui vont
avec.

## Règle fondatrice : la donnée vient de l'outil, pas du modèle

Chaque outil rend un bloc « données réelles » horodaté, avec sa source et son
URL. L'agent doit :
1. Reprendre ces valeurs **telles quelles** — ne jamais recalculer mentalement,
   ne jamais « arrondir vers le plausible », ne jamais compléter une case vide ;
2. Dire explicitement quand un outil a échoué (réseau, absence de donnée) et ne
   rien affirmer sur le domaine concerné ;
3. Distinguer ce qui est **mesuré** (pluie relevée, calcul arithmétique), ce qui
   est **modélisé** (prévision météo, réanalyse), et ce qui est **déclaré par le
   producteur** (quantités, prix, charges) ;
4. Renvoyer au terrain dès qu'il s'agit d'une décision : marché local, agent de
   vulgarisation, laboratoire, vétérinaire.

## 1. Agent Recherche — données publiques ouvertes

| Outil | Ce qu'il produit | Source (sans clé d'API) |
|---|---|---|
| `meteo_et_pluies` | pluie cumulée par mois sur 12 mois, jours sans pluie, déficit des 30 derniers jours, prévision 7 jours (pluie, T min/max) pour la localité citée | Open-Meteo : géocodage, archive ERA5, prévision |
| `contexte_documentaire` | extraits Wikipédia FR (titre + URL) et indicateurs macro Côte d'Ivoire : indice de production alimentaire, part des terres agricoles, population rurale | API MediaWiki, API ouverte Banque mondiale |

Limites à énoncer : la réanalyse est un **modèle**, pas une station ; elle indique
une tendance locale, pas la pluie tombée dans une parcelle précise. Les
indicateurs macro sont des ordres de grandeur nationaux, jamais un argument de
décision d'exploitation. Aucune donnée de prix de marché n'est disponible via
API ouverte : les prix doivent être relevés au marché local, et l'agent le dit au
lieu d'avancer un chiffre.

## 2. Agent Analyse de données — calculer, pas estimer

| Outil | Ce qu'il produit |
|---|---|
| `analyser_tableau` | statistiques descriptives calculées (n, min, max, moyenne, médiane, somme) sur un tableau CSV fourni dans la demande ou un fichier `.csv` du poste |
| `calculer_marge` | recette, total des charges, marge brute, taux de marge, seuil de rentabilité et quantité minimale à vendre — **arithmétique faite par l'outil** |

Limites : tout repose sur les chiffres fournis par le producteur ; un
échantillon de moins de 5 lignes ne permet aucune tendance ; les pertes
(mortalité, vols, avaries, transport) ne sont pas dans les chiffres saisis et
doivent être rappelées. Aucune projection financière sur plusieurs années, aucun
taux d'intérêt, aucune promesse de revenu.

## 3. Agent Relation producteur — dossier et communication

| Outil | Ce qu'il produit |
|---|---|
| `registre_producteur` | ouverture/mise à jour d'un dossier local dans `data/producteurs/<identifiant>.json` (nom, téléphone, localité, historique des demandes) et liste des champs manquants pour qualifier le dossier |

Règles : n'enregistrer que les informations **explicitement données** ; ne jamais
inventer un nom, un numéro ou une localité ; annoncer où la donnée est stockée
(ce poste) ; produire une réponse courte, en langage simple, utilisable en
message vocal ou SMS/WhatsApp ; ne rien promettre (ni subvention, ni prix, ni
rendement) ; si la demande est une réclamation, accuser réception, reformuler,
dire ce qui est possible et ce qui ne l'est pas, proposer l'échelon compétent.

## 4. Agent Automatisation — transformer un plan en actions datées

| Outil | Ce qu'il produit |
|---|---|
| `calendrier_et_rappels` | `calendrier.ics` importable, file `data/automatisations/rappels.json`, commandes de suivi |
| `activer_rappels` | création **puis vérification** d'une tâche planifiée Windows `AGROGUIDCI_Rappels` (quotidienne 07:00) appelant `verifier_rappels.py` |

Règles : une échéance sans date n'est pas planifiable → demander la date ou le
délai ; ne jamais annoncer « c'est planifié » sans avoir relu la tâche
(`schtasks /Query`) ; toute activation reste réversible et la commande de
suppression est fournie. L'automatisation ne remplace pas la décision du
producteur : elle rappelle l'opération, elle ne l'exécute pas.

## Sources et limites

- Institutions de référence à citer pour toute donnée ivoirienne officielle :
  MINADER, MIRAH, ANADER, CNRA, FIRCA, INS/ENSEA, Conseil Coton-Anacarde,
  Laboratoire National d'Appui au Développement Agricole, abattoirs et
  mandataires sanitaires.
- Sources ouvertes utilisées par les outils, citées avec URL et date de relevé :
  Open-Meteo (météo/climat), Wikipédia FR (contexte), Banque mondiale
  (indicateurs macro).
- Ce qui doit toujours être vérifié localement avant décision : prix réels du
  marché, disponibilité des intrants, statut sanitaire, autorisations, météo de
  la station la plus proche.
- Aucune URL inventée, aucun prix inventé, aucune donnée personnelle collectée
  sans que le producteur l'ait donnée.
