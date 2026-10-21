# Guide pour un nouveau Claude (lu automatiquement par Claude Code)

État au 2026-10-21. Lire ce fichier en entier avant d'agir, puis `LISEZMOI.md` (racine), `Python/LISEZMOI.md` et
`Dashboard/LISEZMOI.md` selon la tâche.

## L'utilisateur et le but

- Il parle français : répondre en français, simplement, sans jargon (il a dit « t'explique trop mal » quand c'était
  trop technique). Expliquer les notions (Sharpe déflaté, puissance…) en une phrase avec un exemple.
- But : un portefeuille de stratégies de **futures intraday COURTES, fiables, non corrélées**, jouables en **prop firm**
  (le moins de temps possible devant l'écran, le plus rentable à long terme).
- Toute décision repose sur les **statistiques vectorbt**, jamais sur une intuition ni sur « rien de Claude » dans les
  calculs : en cas de doute, tout recalculer (`python -m nexus tableau`).

## Structure

| Dossier | Contenu |
|---|---|
| `Python/nexus/` | moteur de backtest vectorbt ; `orb.py`, `tableau.py` (export du tableau de bord), `prop_combinaisons.py` |
| `Python/nexus/perso/` | études sur papiers (une par module : protocole écrit dans l'en-tête AVANT le calcul) |
| `Python/nexus/live/` | rapport du forward (`rapport.py`), parité NinjaScript / Python (`parite_ninjascript.py`) |
| `Python/recherche/` | résultats de toutes les études (`resultats_*.txt`, `resultats_60.json`), pistes (`pistes*.md`) |
| `Dashboard/` | tableau de bord Node.js (`serveur.js`, `public/`) ; `donnees/` est généré et HORS dépôt |
| `AddOns/`, `Strategies/` | NinjaScript : `NexusGroupe*.cs` (stratégies en direct), `NexusTableau.cs` (AddOn), `NexusGroupeLogique.cs` |
| `Tests/PariteGroupe/` | banc C# (net8) qui rejoue la logique NinjaScript contre la recherche Python |
| `Cotations/` | barres 1 minute Databento, **sous licence, jamais dans le dépôt** (dépôt séparé chez l'utilisateur) |

Environnement Python : `Python/.venv` (pandas 3, vectorbt). Tests : `cd Python && .venv/Scripts/python -m pytest -q`
et `cd Dashboard && node --test`.

## Méthode de recherche (obligatoire)

1. Partir de papiers sérieux (revue, banque centrale, grande université), récents de préférence (les effets publiés
   avant 2016-2018 sont nuls ou inversés sur nos données). Lire le texte COMPLET et chercher les papiers contraires.
2. **Calcul de puissance AVANT de tester** (`nexus.perso.soixante.t_attendu`) avec l'effet MESURÉ par le papier sur le
   MÊME objet que nous tradons (indice, futures…), jamais une approximation tirée de nos données. Sous t = 3
   (t = 2 pour < 60 cas) : on ne teste pas, on ne compte pas d'essai.
3. Écrire le protocole (sources, règles figées, témoin neutre, coûts 1 tick + 2,50 $ par côté, critères) dans l'en-tête
   du module, puis calculer UNE fois. Ne rien retoucher après avoir vu les résultats ; un bug se documente.
4. Critères : t ≥ 3 ; même signe et t ≥ 1,5 sur 2016-2020 et 2021-2026 ; Welch ≥ 2 contre le témoin ; net > 0 ;
   net > 0 sans les 3 meilleurs ; **Sharpe déflaté ≥ 0,95** avec le nombre CUMULÉ d'essais
   (`ESSAIS_PROGRAMME` de `Python/nexus/tableau.py`, **430** au 2026-10-21 ; l'augmenter à chaque essai).
   Fiabilité vectorbt : borne basse de l'IC 95 % du Sharpe > 0 et Sharpe > 0 sur les deux moitiés.
5. Profil prop firm : ≤ 400 h/an en position, corrélation ≤ 0,3 avec le reste, à plat à 16:10 New York chez la plupart
   des firmes ; tester avec le contrat que le compte peut tenir (micros : les coûts pèsent plus).
6. Livrer : module, `recherche/resultats_<nom>.txt`, paragraphe dans `Python/LISEZMOI.md`, test dans
   `tests/test_perso.py`, `python -m nexus tableau` ; rapport honnête en français.

## Ce qui tient (critères complets)

| Stratégie | Sharpe | IC bas | Déflaté | h/an | Statut |
|---|---|---|---|---|---|
| S1 Noise Area NQ (trade MNQ) | 1,32 | 0,74 | 0,96 | 329 | **en direct** (démo) |
| Gotobi 6J | 1,49 | 0,87 | 0,97 | 210 | **en direct** (démo) |
| ORB 5 min NQ | 0,92 | 0,40 | 0,70 | 170 | candidate : à confirmer sur NQ 2010-2015 |
| Boombitch (NQ, MBT) | 1,37-1,44 | 0,82-0,88 | 0,98-1,00 | 486-879 | fiables mais trop longues (> 400 h) |
| Or la nuit GC | 1,11 | 0,49 | 0,74 | 7 311 | garde la nuit et le week-end : prop firm spéciale |

Tout le reste est rejeté (voir `Python/recherche/`). Derniers rejets : fin de mois Trésor (`fin_de_mois_taux.py`),
enchère de clôture C1 (abandonnée à la lecture, aucun essai). Avec nos 9 contrats (ES NQ YM GC CL 6E 6B 6J 6A),
les idées intraday documentées sont épuisées : il faut des données nouvelles.

## En direct (NinjaTrader sur un serveur Windows distant)

- S1 sur MNQ DEC26 et Gotobi sur 6J DEC26, compte de **démo DEMO8920103** (connexion « Simulation »), depuis le
  2026-10-21. Les stratégies refusent tout compte réel (`CompteSimule()` dans `NexusGroupeBase.cs`).
- L'AddOn `NexusTableau` écrit `live.json` ; la tâche « Nexus - Rapport du Groupe » (15 min) calcule les stats vectorbt
  du forward ; le tableau de bord est protégé par mot de passe (`Dashboard/mot-de-passe.js`).
- L'utilisateur a demandé le 2026-10-21 de **laisser NinjaTrader tranquille** : ne pas y toucher sans demande.
- Adresse du serveur, accès SSH et identifiants : à demander à l'utilisateur, jamais dans le dépôt.

## En attente

- **Clé Databento** (absente) : chiffrer SANS ACHETER (`python -m nexus.databento_dl cout NQ.v.0 2010-01-01 2016-01-01`),
  attendre l'accord sur le prix, puis rejouer l'ORB figée sur 2010-2015 (pas un nouvel essai).
- Binance (BTC / ETH 2017-2026) et HistData (Nikkei JPXJPY, argent XAGUSD…) sont **déjà téléchargés**
  (`Python/.cache/`, 2026-10-20) **et déjà testés** : micro bitcoin fiable mais rejeté (Welch 1,39, 486 h/an) ;
  Nikkei et argent rejetés (`resultats_creneaux.txt`, `resultats_zones.txt`). Ne pas les relancer. Version courte
  du micro bitcoin : close le 2026-10-21 (Zarattini-Pagani-Barbon 2025 lu en entier : aucune version courte, tous ses
  modèles tiennent 3 300 à 3 900 h/an).
  Avant de proposer une piste, vérifier `.cache/` et `recherche/`. Inventaire : `Python/recherche/pistes_contrats_manquants.md`.
- Prop firms (2026-10-21) : Topstep la plus sûre (NKD permis, pas de nuit) ; seule Phidias Premium permet NKD + or +
  nuit ; proposition en cours : simuler le challenge Phidias Premium avec l'or de nuit.

## Règles à respecter

- Jamais de secret ni de donnée sous licence dans le dépôt (`Cotations/`, `Dashboard/donnees/`, `.env.txt`,
  `acces.json`) ; ne jamais afficher une clé. Ne pas mettre l'e-mail de l'utilisateur dans un User-Agent.
- Jamais de mot de passe saisi à la place de l'utilisateur ; jamais de compte réel ; aucun achat de données sans
  accord explicite après devis.
- Commiter seulement quand l'utilisateur le demande ; branche de travail, PR vers `main`.
