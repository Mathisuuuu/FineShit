# Guide pour un nouveau Claude (lu automatiquement par Claude Code)

État au 2026-10-25. Lire ce fichier en entier avant d'agir, puis `LISEZMOI.md` (racine), `Python/LISEZMOI.md` et
`Dashboard/LISEZMOI.md` selon la tâche.

## L'utilisateur et le but

- Il parle français : répondre en français, simplement, sans jargon (il a dit « t'explique trop mal » quand c'était
  trop technique). Expliquer les notions (Sharpe déflaté, puissance…) en une phrase avec un exemple.
- **SEUL BUT depuis le 2026-10-25 : le modèle économique « arbitrage de prop firm »** (celui de l'équipe Kairos,
  registre n° 344-349) : l'argent vient surtout des règles des prop firms (plusieurs comptes en parallèle, mise
  calibrée pour passer l'évaluation vite sans sauter, puis payouts réguliers), avec nos stratégies validées (S1 +
  Gotobi) comme signal à espérance positive. Tout le travail sert ce but : simuler les vraies règles de chaque firme
  (drawdown suiveur, objectif, jours minimum, règle de cohérence, plafonds et fréquence des payouts, prix de l'éval et
  de l'activation) et choisir mise et nombre de comptes qui maximisent le gain net espéré (payouts − frais), avec le
  risque de sauter. Plus de recherche de papiers sauf demande (la méthode ci-dessous reste la règle si on en refait).
  Ancien but (jusqu'au 2026-10-25) : portefeuille de stratégies intraday courtes, fiables, non corrélées.
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

## Méthode de recherche (obligatoire) — 24 critères validés un à un par l'utilisateur le 2026-10-21

**A. Choisir les papiers**
1. Source sérieuse : revue à comité, banque centrale, grande université.
   **Assoupli le 2026-10-25 (décision de l'utilisateur)** : pour atteindre un book de 8-9 stratégies proche de celui de
   Kairos (≈ 4 NQ, 3 or, 1 ES), les familles de règles de Kairos et des praticiens (cassure Asie → Londres sur l'or,
   cassure de l'initial balance, cassure de volatilité sur ES / GC, ORB filtrée…) peuvent être testées SANS papier.
   Tous les autres critères restent (règles figées avant le calcul, puissance quand un chiffre existe, t ≥ 3, deux
   périodes, Welch, Sharpe déflaté ≥ 0,95 avec le compteur cumulé, IC > 0, coûts, conformité prop) ; chaque test
   compte un essai.
2. Récente de préférence (les effets publiés avant 2016-2018 sont nuls ou inversés sur nos données). Décision du
   2026-10-25 : un papier ancien est accepté s'il est encore vivant aujourd'hui (confirmé par un travail récent, ou
   par notre test sur 2016-2026, critère 11). Tous les marchés sont permis (Chine, Europe, Asie…), pas seulement le
   CME ; noter pour chaque piste si une prop firm permet de la jouer.
3. Lire d'abord le résumé ; s'il est cohérent avec notre cadre, lire le texte COMPLET avant toute règle ou tout test
   (texte introuvable : l'idée attend).
4. Chercher et lire les papiers contraires (« disappearing », « replication », « out-of-sample »).
5. Vérifier que l'idée n'est pas déjà testée : d'abord le registre `Python/recherche/inventaire_hypotheses.md` (349
   hypothèses au 2026-10-25, à compléter à chaque lecture ou test), puis `Python/recherche/`, en-têtes de
   `nexus/perso/`, `Python/.cache/`.
   Décision du 2026-10-21 : les tests faits sur simple résumé (Nikkei N1-N2-J1, argent A1, crypto H11-H12…) sont
   repris un à un ; on ne reteste que si le texte complet donne une règle DIFFÉRENTE de celle testée, et chaque
   nouveau test compte comme un essai (le compteur n'est jamais remis à 0).

**B. Avant de tester**

6. **Calcul de puissance AVANT de tester** (`nexus.perso.soixante.t_attendu`) avec l'effet MESURÉ par le papier sur le
   MÊME objet que nous tradons (indice, futures…), jamais une approximation tirée de nos données. Sous t = 3
   (t = 2 pour < 60 cas) : on ne teste pas, on ne compte pas d'essai.
7. Protocole écrit dans l'en-tête du module avant le calcul : sources et chiffres, règles figées (tirées du papier),
   témoin neutre (même opération sans la cause), répliques sur d'autres marchés, critères.
8. Coûts : 1 tick + 2,50 $ de commission par côté ; stress à 2 ticks.
9. Calculer UNE fois, ne rien retoucher après avoir vu les résultats. **Vérifier que le calcul est juste** sans regarder
   le gain : horodatage contrôlé contre une source connue, test d'anticipation (prix futurs modifiés → ordres passés
   inchangés), rejeu vectorbt = P&L du moteur trade par trade, 5 trades tirés au hasard vérifiés à la main (heure,
   sens, prix, coûts), comptes cohérents (trades, jours exclus, heures). Un bug se documente ; montrer les deux
   exécutions.

**C. Critères statistiques**

10. t ≥ 3.
11. Même signe et t ≥ 1,5 sur 2016-2020 ET sur 2021-2026.
12. Welch ≥ 2 contre le témoin, pour TOUTES les stratégies (gardé tel quel : le micro bitcoin reste rejeté).
13. Gain net > 0.
14. Gain net > 0 sans les 3 meilleurs jours.
15. Événements rares (< 60 cas) : t ≥ 2 et net positif ≥ 65 % des années, à la place des n° 10-11.
16. **Sharpe déflaté ≥ 0,95** avec le nombre CUMULÉ d'essais (`ESSAIS_PROGRAMME` de `Python/nexus/tableau.py`,
    **437** au 2026-10-25 ; l'augmenter à chaque essai) pour toute NOUVELLE candidate. Décision du 2026-10-24 : une
    stratégie validée garde le nombre d'essais du jour de sa validation (`ESSAIS_FIGES` : S1, Gotobi et ORB figées à
    **430**, compteur du 2026-10-21) ; les essais faits ensuite sur d'autres idées ne la pénalisent plus.

**D. Fiabilité vectorbt**

17. Borne basse de l'IC 95 % du Sharpe (1 000 tirages des séances) > 0.
18. Sharpe > 0 avant ET après le 01/01/2021.

**E. Profil prop firm**

19. **Plus de plafond d'heures en position** (l'ancienne limite de 400 h/an est levée le 2026-10-21) : on classe au
    rendement par heure en position, et une stratégie ne doit pas tenir le même contrat en même temps qu'une autre du
    groupe (conflit de contrat dans le compte).
20. Corrélation journalière ≤ 0,3 avec les autres stratégies retenues.
21. À plat à 16:10 New York et pas de week-end (la nuit est permise) : tester la version conforme. Exception à part :
    firmes qui permettent nuit et week-end (Phidias Premium, Elite Trader Funding).
22. Tester TOUJOURS les deux : le contrat de base (NQ, GC, 6J…) ET celui que le compte peut tenir (micro), chacun avec
    ses coûts ; garder les deux résultats.

**F. Livrer**

23. Module, `recherche/resultats_<nom>.txt`, paragraphe dans `Python/LISEZMOI.md`, test dans `tests/test_perso.py`,
    `python -m nexus tableau`.
24. Rapport honnête en français.

## Ce qui tient (critères complets)

| Stratégie | Sharpe | IC bas | Déflaté | h/an | Statut |
|---|---|---|---|---|---|
| S1 Noise Area NQ (trade MNQ) | 1,32 | 0,74 | 0,96 | 329 | **en direct** (démo) |
| Gotobi 6J | 1,49 | 0,87 | 0,97 | 210 | **en direct** (démo) |
| ORB 5 min NQ | 0,92 | 0,40 | 0,70 | 170 | candidate : à confirmer sur NQ 2010-2015 |
| Boombitch (NQ, MBT) | 1,37-1,44 | 0,82-0,88 | 0,98-1,00 | 486-879 | fiables ; NQ redevient candidate (plafond de 400 h levé), en conflit de contrat avec S1 / ORB ; MBT rejetée (Welch 1,39) |
| Or la nuit GC | 1,11 | 0,49 | 0,74 | 7 311 | garde la nuit et le week-end : prop firm spéciale |

Onglet Prop firm (2026-10-21) : seules les stratégies qui passent les 24 critères entrent dans les combinaisons
(`RETENUES_METHODE` de `Python/nexus/prop_combinaisons.py` : S1, Gotobi, boombitch NQ conforme ; à tenir à jour) ;
recommandation : S1 + Gotobi (Sharpe 2,04 [1,47 ; 2,59], 519 h/an).

Tout le reste est rejeté (voir `Python/recherche/`). Derniers rejets : jambes Kairos sans papier, or Asie → Londres et
cassure de l'initial balance ES (`kairos_jambes.py`, essais 436-437, 2026-10-25), paris de pentification COT et ES le jour du FOMC (`pente_fomc.py`, essai 435, 2026-10-25), fin de mois Trésor (`fin_de_mois_taux.py`),
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
- **Modèle prop firm (2026-10-25, `nexus/prop_comptes.py`, `resultats_prop_comptes.txt`)** : cycle de vie d'un compte
  50K sur un an avec S1 (MNQ) + Gotobi (6J). Meilleur choix : Topstep, payout Standard, AVEC la perte journalière de
  1 000 $ choisie à l'achat (règles officielles lues le 2026-10-25) : bootstrap +7 300 $/compte-an, 26 % d'années
  perdantes ; Lucid et Tradeify nettement moins bons (médiane négative). Prochaine étape : nombre de comptes, et
  vérifier l'offre limitée « plafonds doublés ».
- Prop firms (2026-10-21) : Topstep la plus sûre (NKD permis, pas de nuit) ; seule Phidias Premium permet NKD + or +
  nuit ; proposition en cours : simuler le challenge Phidias Premium avec l'or de nuit.

## Règles à respecter

- Jamais de secret ni de donnée sous licence dans le dépôt (`Cotations/`, `Dashboard/donnees/`, `.env.txt`,
  `acces.json`) ; ne jamais afficher une clé. Ne pas mettre l'e-mail de l'utilisateur dans un User-Agent.
- Jamais de mot de passe saisi à la place de l'utilisateur ; jamais de compte réel ; aucun achat de données sans
  accord explicite après devis.
- Commiter seulement quand l'utilisateur le demande ; branche de travail, PR vers `main`.
