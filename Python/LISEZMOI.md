# Nexus en Python (vectorbt)

Moteur de backtest Python qui reproduit les stratégies NinjaScript du dépôt pour les tester sans
NinjaTrader : même logique de décision, mêmes modules A (régime), B (taille) et C (disjoncteurs,
coûts, validation), même rapport. vectorbt sert à rejouer les exécutions (contrôle croisé de la
comptabilité), aux graphiques et aux grilles de recherche rapides.

> Spécifications de recherche, pas des conseils d'investissement. Un backtest Python ne remplace
> pas la validation dans le Strategy Analyzer puis sur Sim101.

## 1. Ce qui est porté

| Fiche | Module Python (`nexus/strategies/`) | Statut |
|---|---|---|
| 1 TSMOM | `s01_tsmom.py` | complet |
| 2 XSMOM | `s02_xsmom.py` | complet |
| 3 Multi-facteurs | `s03_multifactor.py` | complet (sans `fundamentals.csv` : momentum + sécurité seulement, comme en C#) |
| 4A Résidu actions | `s04a_residual.py` | complet (quotidien OU et mensuel décile) |
| 5 Vol mean reversion | `s05_volmr.py` | complet (mode par symbole) |
| 6 Paires | `s06_pairs.py` | mode actions journalier |
| 12 Régime de vol | `s12_volregime.py` | complet (terciles ou HMM du module A) |
| 13 Trend prop 24/5 | `s13_proptrend.py` | complet sauf veto Claude, webhook et comptes miroirs (temps réel) |
| 14 Swing strict | `s14_strictswing.py` | complet (spread mesurable seulement en temps réel, comme en C#) |
| 16 Noise Area (barres 1 min) | `s16_noisearea.py` | Python seulement, voir § 8 |
| **S1 Noise Area NQ** | `s1_noiseareanq.py` + `S1_NoiseAreaNQ.py` | **validée le 2026-10-15, réglage figé**, voir § 9 |
| Gotobi 6J (candidate) | `gotobi.py` (vectorbt direct) | à l'étude, voir § 10 |
| ORB 5 min NQ (candidate) | `orb.py` (vectorbt direct) | à l'étude, voir § 11 |
| Module A | `regime.py` | HMM 3 états (Baum-Welch compilé numba) + terciles |
| Module B | `sizing.py` | demi-Kelly, waiver, corrélation, plafonds |
| Module C | `risk.py`, `validation.py`, `report.py` | disjoncteurs, coûts, Monte Carlo, bootstrap, DSR, PBO, walk-forward |

Pas encore portées : **4B** (exige des ticks), **7 à 10** (actualités historiques + appels LLM),
**11** (roue d'options synthétique).

## 2. Installation

```
cd Python
pip install -r requirements.txt
```

Python 3.10 ou plus récent. Toutes les commandes se lancent depuis le dossier `Python`.

## 3. Données

Les cotations journalières sont lues dans un dossier (récursif), un fichier par symbole. Formats
reconnus automatiquement :

- export NinjaTrader (`SPY.Last.txt` : `yyyyMMdd;open;high;low;close;volume`, ou barres minute agrégées en jour) ;
- Yahoo / Stooq / CSV générique avec en-tête (`Date,Open,High,Low,Close[,Adj Close],Volume`,
  noms français acceptés : `ouverture`, `haut`, `bas`, `cloture`, virgule décimale avec `;`) ;
- MetaTrader (`<DATE> <TIME> <OPEN> ...`) ; klines Binance sans en-tête.

Le symbole vient du nom de fichier : `BTC-USD.csv` → `BTCUSD`, `EURUSD=X.csv` → `EURUSD`,
`SPY_daily.csv` → `SPY`, `^GSPC.csv` → `US500`, `^NDX` → `NAS100`, `^GDAXI` → `GER40`, `GC=F` → `XAUUSD`.
Avec une colonne `Adj Close`, les prix sont ajustés des dividendes et splits.

Vérifier ce qui manque pour chaque fiche :

```
python -m nexus verifier --donnees "C:\Users\Mathis\Desktop\Cotations"
```

Les fichiers `Data/*.csv` du dépôt (fondamentaux, facteurs Fama-French, résultats, agenda macro) sont
branchés automatiquement s'ils contiennent des données (option `--externes` pour un autre dossier).

## 4. Commandes

```
python -m nexus liste [--details]                              # fiches et paramètres
python -m nexus backtest -s 01 -d DOSSIER --html               # rapport + trades.csv + equity.csv + graphique
python -m nexus backtest -s 01 -d DOSSIER -p target_vol_pct=10 -p use_panic_state=false
python -m nexus backtest -s 01 --synthetique                   # démonstration sans données
python -m nexus tout -d DOSSIER [--donnees-minute DOSSIER_MINUTE]  # toutes les fiches + tableau récapitulatif
python -m nexus grille -s 01 -d DOSSIER -p lookback_days=126,252 -p skip_days=0,21 --walkforward 180/30
python -m nexus recherche --type tsmom -d DOSSIER -p lookback=63,126,252 -p skip=0,21
python -m nexus backtest -s 16 -d DOSSIER_MINUTE -p symbols=ES --html     # barres 1 minute, voir § 8
```

- `tout` lit seulement les symboles dont chaque fiche a besoin ; la fiche 16 y tourne une fois par
  instrument présent en barres minute (SPY, QQQ, IWM, DIA, ES, NQ, YM, RTY et micros), une ligne chacun.
  Les `-p` s'appliquent aux fiches qui connaissent le paramètre (ex. `-p initial_bankroll=1000000`).
- `--debut` / `--fin` bornent les données chargées ; `--debut-trading` laisse le chauffage avant cette
  date (indicateurs calculés, aucun ordre) et ne compte que la période tradée dans le rapport.
- Les noms de paramètres sont ceux du C# en minuscules avec des tirets bas
  (`LookbackDays` → `lookback_days`) ; `python -m nexus liste --details` les affiche.
- `grille` lance le moteur complet pour chaque configuration, puis calcule le **PBO** (CSCV), le
  **Deflated Sharpe** avec le vrai nombre d'essais et un **walk-forward** (sélection sur la fenêtre
  d'entraînement, rendement hors échantillon concaténé). Il affiche aussi le **plateau** : Sharpe des
  configurations voisines de la meilleure (un cran sur un seul paramètre), tableaux croisés par paire
  de paramètres et, avec `--html`, cartes de chaleur (`plateau.html`).
- `recherche` est une grille vectorbt **signal seul** (sans module B ni stops), très rapide, pour
  explorer avant de lancer `grille`.
- Les résultats sont écrits dans `resultats/<stratégie>_<date>/`.

## 5. Fidélité au C#

Reproduit à l'identique : décisions à la clôture, ordres à l'ouverture de la barre suivante,
réductions avant entrées, ordres limites valables N barres, stops natifs (exécution à l'ouverture si
gap, sinon au prix du stop), stop déjà franchi → sortie au marché, quantités entières, coûts du module C,
conversion de devise par les paires chargées, comptabilité par trade (rendement = PnL net / notionnel max),
module B complet (a priori bayésien, waiver, diviseur de corrélation, plafonds), rééquilibrage mensuel
avec rattrapage.

Écarts assumés :

- **Stops** actifs dès la barre d'entrée (au plus prudent).
- **Jours fériés** déduits des données (jours ouvrés sans barre) au lieu des modèles d'horaires NinjaTrader.
- **Hasard** : Monte Carlo et initialisations du HMM utilisent le générateur de numpy (résultats proches,
  pas identiques au bit près).
- **Disjoncteur journalier** : par défaut (`daily_breaker_ref=veille`), la perte du jour est mesurée
  depuis la clôture précédente, comme en temps réel ; `daily_breaker_ref=ninja` reproduit le backtest C#.

Contrôles : `python -m pytest -q tests` (54 tests, dont 18 pour la fiche 16) reprend les contrôles numériques de
`Tests/Unit/Tests.cs` et vérifie le moteur. Il couvre :

- les exécutions, stops et ordres limites ;
- l'absence de biais d'anticipation : modifier les données après une date ne change aucune décision antérieure ;
- le rejeu vectorbt, qui retrouve l'equity du moteur à 1e-9 près.

## 6. Constats sur le code NinjaScript (révélés par le portage)

Le moteur Python reproduit fidèlement ces comportements, qui existent donc aussi dans NinjaTrader :

1. **Exposition écrasée par le module B (fiches 1, 2, 5, 12).** En backtest, le compteur de trades
   réels vaut 0, donc le *waiver* ×0,5 s'applique toujours. Le diviseur de corrélation divise ensuite
   chaque position par 1 + Σ corrélations avec les ~15 autres positions corrélées. Sur données
   synthétiques, la fiche 1 investit en moyenne 1,5 % du capital au lieu de ~24 %. Pour l'évaluer :
   `-p waiver_multiplier=1 -p use_correlation_divisor=false`.
2. **Blocage définitif quand Kelly ≤ 0 (fiches 4A, 6, 14, mode demi-Kelly).** Dès que l'estimation
   bayésienne donne f* ≤ 0, toute entrée est refusée. Comme plus aucun trade ne se ferme, l'estimation
   ne peut plus remonter et la stratégie ne trade plus jamais. Parade : `no_edge_fraction_pct` > 0
   (taille « sonde »).
3. **Disjoncteur journalier inopérant en backtest journalier.** La référence du jour est prise à la
   première mise à jour du jour, qui inclut déjà la clôture : la perte du jour vaut toujours 0.
4. **Fiche 5 : seuil de dérive toujours franchi.** Le seuil de 20 % compare la position *après* waiver
   et corrélation à la cible w *avant* ; d'où des réajustements fréquents.

## 7. Architecture

```
nexus/
  mathx.py       NxMath, MCO, ADF + MacKinnon, Engle-Granger, OU, Black-Scholes
  data.py        instruments, lecture des cotations, historiques, fichiers Data/*.csv, données synthétiques
  intraday.py    barres 1 minute : fuseau, horodatage, séance cash 9:30-16:00 en matrices, minutes synthétiques
  engine.py      NexusStrategyBase : univers, lot synchronisé, position cible, exécutions, comptabilité
  sizing.py      module B          risk.py  disjoncteurs, coûts, stress test
  validation.py  Monte Carlo, bootstrap, Sharpe, PSR, DSR, PBO, walk-forward
  report.py      rapport texte (même plan que NxReport)
  regime.py      module A (HMM, terciles)    signals.py  moteurs de signaux partagés
  vbt_bridge.py  rejeu vectorbt, graphique HTML, grilles vectorisées
  strategies/    une classe par fiche
```

Pour ajouter une stratégie : hériter de `NexusStrategy`, définir `NAME`, `DEFAULTS`, `on_batch(jour)`
(ou `on_symbol_bar` avec `BATCH_MODE = False`) et l'enregistrer dans `strategies/__init__.py`.

## 8. Fiche 16 — Noise Area Intraday Momentum (barres 1 minute)

Liste de recherche « fiche 02 » (la fiche 01, rebalancement des ETF à levier, est la fiche 15 du dépôt).
Source : Zarattini, Aziz & Barbon (2024), *Beat the Market: An Effective Intraday Momentum Strategy
for S&P500 ETF (SPY)*, SSRN 4824172 — 19,6 %/an, Sharpe 1,33 nets de coûts sur SPY, 2007–début 2024.
Pas d'équivalent NinjaScript : la fiche n'existe qu'en Python.

### Données

- **Barres 1 minute** de la séance cash (les barres hors séance sont ignorées) : `SPY.Last.txt`,
  `ES ##-##.Last.txt` (série continue NinjaTrader → symbole `ES`), CSV génériques, **Parquet**
  (`ES_v0_1m.parquet` du dépôt Cotations, Databento → symbole `ES`). Seuls les fichiers des symboles
  utiles sont lus, sans agrégation en jour (`pip install pyarrow` pour le Parquet).
- **Futures : rolls**. NinjaTrader : série continue *Merge Back Adjusted*. Databento `.v.0` : contrats
  raboutés **sans ajustement** (sauts de −0,6 % à +1,4 % par trimestre) → `roll_adjust=auto` (défaut :
  un future dont le fichier est horodaté en UTC) ou `minuit_utc` repère le saut à 00:00 UTC de chaque mois
  d'échéance et ajuste les prix antérieurs en proportion
  (les rendements sont conservés ; trimestres sans saut net, < 5 bp ou ambigu, laissés tels quels).
  Des contrats individuels (`ES 03-25`…) sont refusés ; le rapport signale des gaps anormaux en fenêtre de roll.
- **Jours fériés NYSE exclus** (`exchange_calendar=NYSE`) : les futures CME y ont une séance raccourcie
  jusqu'à 13:00 qui ressemblerait sinon à une demi-séance.
- **Fuseau** (`data_timezone=auto`) : UTC si le fichier porte son fuseau (Parquet Databento), sinon New
  York. NinjaTrader exporte dans le fuseau du PC : en France `-p data_timezone=Europe/Paris`. Si moins de
  la moitié des jours ont une séance complète, le run s'arrête en suggérant le fuseau.
- **Horodatage des barres** (`bar_label=auto`) : début ou fin de barre, déduit du saut de volume à
  l'ouverture (NinjaTrader date en fin de barre : la barre 9:30-9:31 est datée 9:31). Le rapport indique
  ce qui a été retenu ; forcer avec `-p bar_label=debut|fin`.
- Facultatif : `^VIX.csv` journalier dans le même dossier (régime VIX ; sans lui, le rapport découpe par
  terciles de vol réalisée 20 j de l'instrument), `Data/gex.csv` (format de la
  fiche 15, branché automatiquement s'il existe ; régime gamma), `-p dividends_file=...` (CSV
  `date,dividend` au jour ex : PrevClose ajusté, utile pour SPY non ajusté).
- Demi-séances (13:00) reconnues ; jour incomplet (première barre après 9:35 ou séance tronquée) ignoré.

### Règles et paramètres

| Règle de la fiche | Implémentation | Paramètre (défaut) |
|---|---|---|
| sigma(t) = moyenne 14 j de \|Close(t)/Open − 1\| | même minute, 14 jours **précédents** (jour courant exclu) | `lookback_days=14` |
| Upper/Lower avec max/min(Open, PrevClose) | PrevClose = clôture 16:00 de la veille | `band_mult=1.0` |
| Contrôle toutes les 30 min | 10:00, 10:30… 15:30 (minutes depuis l'ouverture multiples de M) | `check_interval_min=30`, `first_check_min` |
| Long > Upper, short < Lower | l'entrée exige aussi Close > VWAP (< VWAP), comme le code des auteurs | `vwap_entry_filter=true` (false = règle littérale) |
| Stop suiveur max(Upper, VWAP) | vérifié aux contrôles (papier) ou chaque minute | `use_vwap_stop=true`, `stop_check=controle\|minute` |
| Clôture en fin de séance | ordre MOC (clôture de la barre 16:00) ou N min avant | `exit_minutes_before_close=0` (10 → 15:50) |
| Ciblage de volatilité | AUM de la veille × min(2 % / vol 14 j, 4) / Open, arrondi | `target_daily_vol_pct=2`, `max_leverage=4`, `sizing=vol_cible\|fixe` |
| Exécution | **ouverture de la barre suivante** (pas au prix du franchissement) | `execution=ouverture_suivante\|cloture\|cloture_suivante` |

Coûts par exécution, selon l'instrument (surchargeables : `commission_per_unit`,
`commission_min_per_order`, `slippage_ticks`, `point_value`, `tick_size`) :

| Instrument | $/point | Commission | Glissement |
|---|---|---|---|
| SPY, QQQ, IWM, DIA | 1 | 0,0035 $/action, min 0,35 $/ordre (papier) | 0,1 tick = 0,001 $ (papier) |
| ES / NQ / RTY / YM | 50 / 20 / 50 / 5 | 2,25 $/contrat | 0,5 tick |
| MES / MNQ / M2K / MYM | 5 / 2 / 5 / 0,5 | 0,62 $/contrat | 0,5 tick |

Un instrument par run. Quantités entières (`fractional_units=true` pour juger le signal sans
l'arrondi : 1 ES = 250 000 $ de notionnel). Le module B (Kelly) n'est pas utilisé : la taille est
celle du papier. Disjoncteurs du module C désactivés par défaut (absents du papier),
`-p use_circuit_breakers=true` pour les activer (ils bloquent les entrées, jamais les sorties).

### Plan de test

```
# 1. Réplication SPY (viser un Sharpe proche de 1,3 ; execution=cloture = prix du franchissement, comme le papier)
python -m nexus backtest -s 16 -d DOSSIER_MINUTE -p symbols=SPY --debut 2007-01-01 --fin 2024-04-30 --html
python -m nexus backtest -s 16 -d DOSSIER_MINUTE -p symbols=SPY --debut 2007-01-01 --fin 2024-04-30 -p execution=cloture

# 2. Portage ES puis NQ (coûts futures) ; données Databento du dépôt Cotations (1 M$ : arrondi des contrats négligeable)
python -m nexus backtest -s 16 -d ../../cotations/indices -p symbols=ES -p initial_bankroll=1000000 --html
python -m nexus tout -d ../../cotations/indices -p initial_bankroll=1000000 --html     # ES, NQ, YM au récapitulatif
# export NinjaTrader en heure de Paris
python -m nexus backtest -s 16 -d DOSSIER_MINUTE -p symbols=ES -p data_timezone=Europe/Paris

# 3. Post-publication seul (chauffage avant, rapport à partir du 1er juin 2024)
python -m nexus backtest -s 16 -d DOSSIER_MINUTE -p symbols=ES --debut 2024-01-01 --debut-trading 2024-06-01

# 4. Sensibilité (48 configurations, PBO, Deflated Sharpe, plateau, walk-forward 3 ans / 6 mois)
python -m nexus grille -s 16 -d DOSSIER_MINUTE -p symbols=ES -p lookback_days=7,14,21,30 -p check_interval_min=15,30,60 -p band_mult=0.8,1,1.2,1.5 --walkforward 756/126 --html

# 5. Régimes : ^VIX.csv dans le dossier, Data/gex.csv rempli ; variante filtre gamma
python -m nexus backtest -s 16 -d DOSSIER_MINUTE -p symbols=ES -p gamma_filter=court

# 6. Coûts : le rapport donne trades/séance, coût total et Sharpe à 0x/1x/2x/3x les coûts
python -m nexus backtest -s 16 -d DOSSIER_MINUTE -p symbols=ES -p slippage_ticks=1
# Variante : sortie forcée à 15:50
python -m nexus backtest -s 16 -d DOSSIER_MINUTE -p symbols=ES -p exit_minutes_before_close=10
```

Le rapport (section « Spécifique à la stratégie ») contient : séances valides et demi-séances, levier
moyen et part des jours plafonnés, trades par séance et leur répartition, raisons de sortie (stop bande,
stop VWAP, inversion, fin de séance), PnL long/short, coûts (total, bp par aller-retour, Sharpe selon le
multiple des coûts), buy & hold et corrélation, avant/après la date de publication (`publication_date`),
tableau par année, robustesse (sans le top 1 % des séances, hors 2008/2020/2022), régimes VIX et gamma,
contrôle des rolls, et les **critères de rejet** de la fiche :

- `[REJET]` si le Sharpe net après publication est < 0,5 (au moins 60 séances) ;
- `[ALERTE]` si le Sharpe tombe sous 0,5 sans le top 1 % des séances ou hors années de crise ;
- plateau : `grille` (Sharpe des voisins, « PIC ISOLÉ » s'ils font moins de 70 % du meilleur).

Fichiers : `rapport.txt`, `trades.csv`, `fills.csv` (colonne `moment` : ouverture/clôture de barre),
`jours.csv` (une ligne par séance : Open, PrevClose, gap, vol 14 j, levier, unités, trades, PnL brut,
coûts, VIX de la veille, GEX…), `equity.csv`, `graphique.html` (rejeu vectorbt minute par minute, qui
doit retrouver l'equity du moteur ; écart affiché dans le titre).

### Garde-fous (red flags de la fiche)

- **Biais d'anticipation** : sigma n'utilise que les jours précédents ; vol de taille décalée d'un jour ;
  test : modifier les prix après 12:00 un jour donné ne change aucune exécution antérieure.
- **Prix du franchissement** : exécution par défaut à l'ouverture de la minute suivante ;
  `execution=cloture` mesure l'écart avec l'hypothèse du papier.
- **Globex** : PrevClose = 16:00 heure de New York (le gap de nuit compte dans la bande) ; contrôle des
  rolls pour les séries non ajustées.

### Limites connues

- Exécutions sur barres 1 minute (pas de ticks) ; la « clôture MOC » d'un future est la dernière
  minute avant 16:00, pas une enchère.
- Un jour aux données incomplètes est écarté entier (filtre de qualité des données, pas de signal).
- `--synthetique` produit une marche aléatoire minute : le Sharpe brut doit y être proche de 0 (les
  tests vérifient aussi qu'un momentum intrajournalier planté est bien capté).

## 9. S1_NoiseAreaNQ — stratégie validée (réglage figé)

Noise Area de la fiche 16 sur **NQ seul**, avec le meilleur réglage de la grille, **validée le
2026-10-15** et figée : sigma sur **30 séances**, contrôle toutes les **30 min**, bande **× 1,2**,
filtre VWAP, ordre à l'ouverture de la minute suivante, sortie à la clôture, vol cible 2 %/jour
(vol 14 séances), levier max 4, coûts 2,25 $ par contrat + ½ tick par exécution.

Deux versions qui donnent le même résultat à la séance près :

```
# fichier autonome (numpy + pandas seulement), verifie le resultat de reference a chaque lancement
python S1_NoiseAreaNQ.py --donnees ../../cotations/indices/NQ_v0_1m.parquet
# moteur nexus (rapport, graphique vectorbt) ; les parametres de strategie sont verrouilles
python -m nexus backtest -s S1 -d ../../cotations/indices -p initial_bankroll=1000000 --html
```

`-s S1` refuse tout paramètre de stratégie modifié (`band_mult`, `lookback_days`, `symbols`…). Seuls
les réglages de données (`data_timezone`, `bar_label`, `roll_adjust`, `exchange_calendar`), le capital
et les dates restent libres. Pour explorer un autre réglage, il faut passer par la fiche 16.

**Référence** : Cotations `NQ_v0_1m.parquet`, 2016-01-04 → 2026-08-28, 1 M$ → equity finale
**5 717 821,79 $**, **1 828** allers-retours. Le fichier autonome affiche `Reference CONFORME` quand
il retrouve ce résultat. `tests/test_s1_noiseareanq.py` le vérifie aussi quand les données sont présentes.

### Tests passés (réglage figé, calculs vectorbt / scipy / `nexus.validation`)

| Test | Résultat |
|---|---|
| Rejeu vectorbt de la comptabilité | identique (écart relatif max 3,7e-14) |
| Second programme indépendant (`S1_NoiseAreaNQ.py`, sans nexus) | identique (0 séance différente sur 2 679) |
| Biais d'anticipation (prix après le 15/06/2022 × 1,25) | aucun (2 182 exécutions antérieures inchangées) |
| Sharpe (vectorbt) | 1,32 ; avant juin 2024 : 1,42 ; après : 0,95 (562 séances) |
| Sortino / Calmar / perte max | 2,63 / 1,28 / 13,9 % |
| Rendement annuel / volatilité | 17,8 % / 13,1 % |
| Années positives | 10 sur 11 (2026 à −0 % au 28/08) |
| IC 95 % du Sharpe 2016-2026 (bootstrap BCa scipy) | [0,76 ; 1,85] |
| IC 95 % du Sharpe après publication | [−0,34 ; 2,07] |
| Probabilité Sharpe vrai > 0 (PSR) | 100 % ; après publication : 94,2 % (> 0,5 : 77,2 %) |
| Test des signes (permutation scipy, 20 000 tirages) | p < 0,0001 |
| Perte max, ordre des trades mélangé (vectorbt) | médiane 15,6 %, 95 % : 22,7 %, 99 % : 27,2 % |
| Perte max, tirage avec remise | médiane 15,7 %, 95 % : 24,4 %, 99 % : 30,0 % |
| Glissement 0 / 1 / 2 ticks | Sharpe 1,37 / 1,25 / 1,14 |
| 1 minute de retard en plus | Sharpe 1,16 ; après publication 0,57 |
| Walk-forward 3 ans / 6 mois (grille de 48) | Sharpe hors échantillon 0,97 |
| Plateau de paramètres | 48 réglages NQ entre 1,04 et 1,32 |

### Réserves connues (acceptées à la validation)

- **Choix du réglage** : PBO 81 % sur les 48 réglages et Deflated Sharpe 61,5 % (177 essais comptés).
  Toute la famille est positive, mais le choix de 30 / 30 / 1,2 plutôt qu'un voisin relève surtout du
  hasard. Il faut donc attendre plutôt un Sharpe de 1,0 à 1,2 que 1,32.
- **Dépendance aux meilleures séances** : hors du top 1 % des séances, le Sharpe tombe à 0,50.
- **Après publication** : l'intervalle de confiance inclut 0 (562 séances seulement).
- **Latence** : une minute de retard fait passer le Sharpe après publication de 0,95 à 0,57.
- **Exécution** : barres 1 minute, sans ticks ; marge non modélisée ; remplissages réels à comparer en
  Sim101 avant tout compte réel.

## 10. Gotobi 6J (candidate) et tableau de bord

### Gotobi sur le yen (`nexus/gotobi.py`)

Les jours de règlement japonais (5, 10, 15, 20, 25 et fin de mois), les importateurs achètent leurs
dollars au cours du fixing de 9:55 à Tokyo. Les banques les achètent sur le marché juste avant : le dollar
monte, puis redescend après le fixing.

| Heure de Tokyo | Ordre (6J = yen en dollars) |
|---|---|
| 08:00 | vente de 6J (achat de dollars) |
| 09:55 | retournement : achat de 6J (vente de dollars) |
| 11:00 | sortie |

Jour gotobi férié au Japon ou tombant un week-end : jour ouvré précédent. Le calendrier japonais est
calculé dans le module : fériés, jours de remplacement, jours entre deux fériés, années 2019-2021, 2 et
3 janvier, 31 décembre. Le backtest est écrit directement dans vectorbt (`Portfolio.from_signals`, une
colonne, retournement à 9:55). Les ordres partent à l'ouverture de la première barre 1 minute de l'heure
prévue.

Coûts : 2,25 $ par contrat et par côté + ½ tick. Taille : notionnel fixe de 95 000 $ pour 100 000 $ de
capital. Données : `forex/6J_v0_1m.parquet` du dépôt Cotations (Databento, 2016-2026, 3 684 259 barres,
36 rolls ajustés). Tests : `tests/test_gotobi.py`.

Statut : **candidate, non validée**. Les tests (tableau de bord) montrent un effet net et spécifique aux
jours gotobi (placebos négatifs), mais très sensible :
- aux coûts (Sharpe 0,62 à 2 fois les coûts) ;
- à une minute de retard au fixing (0,62) ;
- au nombre d'hypothèses essayées avant de le retenir (Sharpe déflaté strict 0,1 %).

### Tableau de bord (`python -m nexus tableau`)

```
python -m nexus tableau --cotations ../../cotations      # ecrit ../Dashboard/donnees/*.json
cd ../Dashboard && node serveur.js                       # http://localhost:3000
```

Exporte chaque stratégie marquée `VALIDATED` dans le registre (S1...) et les candidates (Gotobi). Pour
chacune :
- les statistiques vectorbt complètes et les courbes ;
- les trades ;
- la batterie de tests : rejeu vectorbt, anticipation, bootstrap BCa, Sharpe probabiliste et déflaté,
  permutation, Monte Carlo, coûts, latence, placebo, plateau, PBO, walk-forward ;
- les corrélations entre stratégies.

Tests de sur-ajustement (le réglage de chaque stratégie reste figé, rien n'est réoptimisé) :
- stabilité sur 6 sous-périodes et par moitié ;
- test SPA de Hansen (`arch`) sur la famille de réglages voisins ;
- Sharpe corrigé des essais multiples (Bonferroni sur tous les essais, Holm et BHY sur la famille, `statsmodels`) ;
- durée minimale de backtest ;
- prime du choix du réglage, comparée au réglage publié par les auteurs pour S1 ;
- test sur hasard : marchés minute simulés sans momentum pour S1, faux jours gotobi tirés au hasard pour le Gotobi.

Options : `--simulations 2000`, `--sans-grille` (plus rapide), `--seulement S1,G1` (codes : S1, G1 Gotobi,
O1 ORB, N1 or la nuit).
Détails de l'interface : `Dashboard/LISEZMOI.md`. Les fichiers exportés restent hors du dépôt (licence des
données).

## 11. ORB 5 minutes sur NQ (candidate, `nexus/orb.py`)

Règles du papier « Stocks in Play » (Zarattini, Barbon et Aziz 2024, SSRN 4729284), appliquées telles
quelles au Nasdaq 100 E-mini :

1. La bougie 9:30-9:35 doit avoir un volume au moins égal à la moyenne des bougies 9:30-9:35 des
   14 séances précédentes.
2. Bougie haussière : ordre stop d'achat à son plus haut. Bougie baissière : ordre stop de vente à son
   plus bas.
3. Stop de protection à 10 % de l'ATR sur 14 jours, sinon sortie à la clôture.
4. Taille : 1 % du capital risqué au stop, levier maximum 4.

Le backtest est écrit dans vectorbt (`from_signals` avec `sl_stop`). Le stop est ancré sur le prix
d'exécution (`stop_entry_price="fillprice"`) ; vectorbt prend par défaut la clôture de la minute
d'entrée. Tests : `tests/test_orb.py`.

Pourquoi celle-ci : parmi les stratégies SSRN testées sur nos contrats avec les règles des auteurs, c'est
la seule qui garde son niveau après publication :

| Stratégie | Sharpe avant / après publication |
|---|---|
| ORB 2024 avec filtre de volume (NQ) | 0,94 / 0,99 |
| ORB 2024 sans filtre (NQ) | 1,12 / 0,66 |
| ORB 2023 (NQ) | 1,09 / 0,42 |
| VWAP (NQ) | 0,21 / 0,26 |
| Première → dernière demi-heure | négatif |
| Toutes ces stratégies sur ES | nulles ou négatives |

Statut : **candidate, non validée**. La batterie complète de tests est dans le tableau de bord.

## 12. Or la nuit (candidate, `nexus/or_nuit.py`)

Source : Blose et Gondhalekar (2014), *Overnight gold returns*, Applied Economics Letters 21(18). Sur le
COMEX de 1985 à 2012, le rendement de l'or est positif hors de la séance de jour (8:20-13:30 à New York) et
négatif pendant. La règle des auteurs est appliquée telle quelle. C'est la toute première version testée
sur l'or (G1a).

| Heure de New York (Paris) | Ordre (GC) |
|---|---|
| 13:30 (19:30), clôture du COMEX | achat |
| 8:20 (14:20) à la séance suivante, ouverture du COMEX | vente |

La position traverse la pause 17:00-18:00. Le vendredi, elle est gardée tout le week-end. S'il n'y a pas
de barre à 13:30 (séance raccourcie), il n'y a pas d'achat ce jour-là.

Taille : 100 % du capital, réinvesti, sans levier. Coûts : 2,25 $ par contrat et par exécution + ½ tick.
Les rolls de GC (souvent en fin de mois) sont ajustés au saut dominant de chaque mois à minuit UTC
(29 rolls). Le backtest est écrit dans vectorbt (`from_signals`, prix d'exécution par barre). Le mode
`compact=True` ne donne à vectorbt que les barres d'ordres et de fin de séance : il produit les mêmes
résultats, plus vite, pour les grilles et les tirages. Tests : `tests/test_or_nuit.py`.

Résultats (GC.v.0, 2016-2026, tout l'historique est postérieur à la publication) :

| Version | Sharpe |
|---|---|
| Nuit 13:30 → 8:20 (stratégie) | 1,11 |
| Or gardé en permanence | 0,80 |
| Séance du COMEX seule | −0,42 |
| Version intraday (fermée à 17:00, reprise à 18:00) | 0,65 |

Ce qui tient :
- 6 sous-périodes positives sur 6 ;
- coûts ×3 : Sharpe 0,76 ; latence +5 min : 0,99 ;
- les 25 horaires voisins vont de 0,86 à 1,11 ; PBO 35 % ; walk-forward 1,14 ; SPA p = 0,002 ;
- Sharpe corrigé de Bonferroni sur 178 essais : 0,59 ;
- la même pause de 5 h 10 placée ailleurs fait moins bien (p = 0,009).

### Prop firms (`nexus/prop.py`)

La plupart des prop firms de futures imposent d'être à plat avant leur heure limite (16:10 New York chez
Topstep, MyFundedFutures et FundedNext ; 16:45 à 16:59 ailleurs) et interdisent le week-end. Règles relevées
le 2026-10-15 ; elles changent souvent, à revérifier. Variantes testées, fixées avant le calcul :

| Version | Sharpe |
|---|---|
| Règle publiée, contrat GC | 1,11 |
| Règle publiée, micro MGC (coûts environ 3 fois plus élevés par once) | 0,96 |
| Sans week-end, MGC (nuit permise, week-end interdit) | 0,56 |
| CFD XAUUSD avec financement de 5 / 20 / 45 $ par 100 onces et par nuit | 1,02 / 0,77 / 0,35 |
| Intraday, à plat à 16:10, sans la jambe du soir les jours de FOMC : GC / MGC | 0,45 / 0,14 |

Variantes intraday tirées des articles (Sharpe, coûts GC) :

| Variante | Source | Sharpe |
|---|---|---|
| Après une séance COMEX faible | Boyarchenko, Larsen et Whelan 2023 | 0,53 |
| Asie seule, 18:00-3:00 | Donati et Jung 2019 | 0,38 |
| Ouverture européenne, 3:00-8:20 | Bondarenko et Muravyev 2023 | 0,14 |
| Vente 8:20-11:00 | Berkman et al. 2012 | −0,18 |
| Achat 11:00-16:10 | Krohn, Mueller et Whelan 2024 | −0,27 |
| Achat 2:00-4:00 | — | −0,02 |

Aucune ne rend la version intraday viable.

Challenges simulés (un départ à chaque séance 2016-2026, chemin minute réel, micros MGC) :
- **Elite Trader Funding Diamond Hands 100K** (nuit et week-end permis), règle publiée : 41 % de réussite
  à 50 000 $ de notionnel (environ 3 MGC), en 76 séances en médiane.
- **Topstep 50K**, version intraday : 14 à 17 % de réussite.

Repère : une stratégie sans avantage ni frais, avec une perte max fixe, réussirait environ 40 %.

Conclusion :
- l'avantage est dans la nuit **et** dans les fermetures (pause quotidienne, week-end) ;
- la version intraday ne tient pas, surtout en micros ;
- pour rester conforme, il faut un compte qui permet de garder la nuit et le week-end, ou un CFD dont le
  financement de nuit reste bas (environ 5 $ par 100 onces).

Statut : **candidate, non validée**. Points faibles :
- c'est surtout un pari sur la hausse de l'or (bêta 0,56) ;
- l'écart avec l'or gardé en permanence n'est pas prouvé (+0,31 de Sharpe, p = 0,09) ;
- Sharpe déflaté strict à 0 %.

## 13. Groupe P1 (en cours) : intraday, Sharpe ≥ 1 avant et après publication (`nexus/p1.py`)

Critères fixés avant les tests (tous requis) :
1. à l'échelle de 5 %/an, perte max ≤ 5,5 % sur 2016-2026 ;
2. Sharpe ≥ 1,2 sur chaque moitié, au moins 5 sous-périodes positives sur 6, 2 dernières années positives ;
3. Sharpe après publication ≥ 1 ;
4. coûts × 2 : Sharpe ≥ 1 et perte max ≤ 7,5 % ;
5. significatif après correction de Bonferroni sur tous les essais du projet ;
6. corrélation ≤ 0,3 avec les autres P1.

Repère : avec ces critères, S1 échoue de peu (Sharpe après publication 0,95). Gotobi échoue sur ses moitiés et
après publication.

État au 2026-10-15 : 58 hypothèses testées en 9 lots, **aucune approuvée**. Toutes ont été fixées avant le
calcul, d'après les articles. Rejetées :
- pré-FOMC (avec ou sans filtre de volatilité), rallye FOMC 13:55-14:55, retournement FOMC, devises autour du FOMC ;
- dérive avant l'emploi (NFP) et l'ISM, jour d'annonce, dérive juste avant la publication ;
- momentum intraday de marché (15:30-16:00), rééquilibrage des ETF à levier, retournement après la clôture,
  lundi matin, week-end, retournement d'après-midi (0DTE) ;
- zone de bruit sur ES, YM, GC, CL et les devises, persistance à la même heure, saisonnalité horaire (découverte
  2016-2020, testée 2021-2026) ;
- écarts d'ouverture (dimanche soir compris), retournement après une nuit extrême, paires intraday ;
- EIA (momentum, minute extrême), API, roll GSCI ;
- chiffres britanniques sur 6B, veille de la BCE (calendrier reconstruit par le volume, trop imprécis),
  après le déjeuner, ouverture de Shanghai sur l'or ;
- chiffres ronds : Sharpe 1,66 au premier passage, dû à une anticipation d'une minute ; −0,74 une fois corrigé ;
- retournement croisé entre les 9 contrats, prévision ridge de la demi-heure suivante.

Les deux recherches d'articles (SSRN, revues, Quantpedia) ne trouvent aucune stratégie intraday publiée sur ces
contrats avec un Sharpe seul de 1,5 ou plus sur 2016-2026.

Mises en garde publiées :
- Paz (SSRN 7290621) : la zone de bruit sur SPY tombe à un Sharpe de 0,39 hors échantillon depuis mai 2024 ;
- Mesfin (arXiv 2605.04004) : l'ORB sur MNQ ne survit pas à 2 points de coût sur 2021-2025.

À l'inverse, le panier S1 + Gotobi + ORB tient déjà l'objectif : Sharpe 1,92, 6 sous-périodes positives sur 6,
perte max de 3,0 % à 5 %/an.

**Critères révisés le 2026-10-16 (version 2, celle qui décide) :**
- l'objectif de 5 %/an et la perte max sont abandonnés ;
- Sharpe ≥ 1 avant la publication (si au moins 1 an de données avant) **et** ≥ 1 après (au moins 1 an) ;
- toujours intraday, sur les actifs du dépôt, avec une corrélation ≤ 0,3 entre P1 ;
- coûts × 2 et Bonferroni sont affichés pour information.

Les 58 hypothèses repassées avec ces critères : aucune approuvée. La meilleure est la zone de bruit sur ES
(0,89 avant publication, 0,16 après).

Familles de découverte, réglées sur 2016-2020 et jugées sur 2021-2026 (la fin 2020 tient lieu de date de
publication) :

| Famille | Réglages | Résultat |
|---|---|---|
| Zone de bruit par actif | 36 à 72 par actif | ES et CL atteignent 1 sur 2016-2020, puis 0,79 et −0,57 sur 2021-2026 |
| Momentum ou retournement intraday | 20 par actif | aucun actif ≥ 1 sur 2016-2020 (le meilleur : 0,45) |
| Cassure du range d'ouverture | 8 par actif | aucun actif ≥ 1 (le meilleur : 0,48) |
| Retour vers le VWAP | 3 par actif | aucun actif ≥ 1 (le meilleur : 0,47) |

Avec ces critères, parmi les stratégies existantes, seule « or la nuit » passe (1,11 sur un historique tout entier
postérieur à la publication), mais elle n'est pas intraday. S1 (0,95 après publication), Gotobi (0,89) et ORB
(0,92 avant publication) échouent de peu.

Deux autres familles, réglées sur 2016-2020 :
- enchaînement des sessions dans une même séance (Asie vers Europe, nuit vers New York) : le meilleur actif
  plafonne à 0,48 ;
- signal croisé (le matin d'un contrat annonce l'après-midi d'un autre, 72 couples) : le meilleur couple plafonne
  à 0,62.

Aucune n'atteint 1 sur 2016-2020. Avec des signaux de prix intraday sur ces 9 contrats, les pistes sont épuisées.
Étape suivante : ajouter des contrats (taux, Russell, autres devises, métaux, gaz, grains), avec les mêmes
critères.

**Microstructure, mono-actif (2026-10-16)** — signaux tirés des barres 1 minute (volume anormal, déséquilibre
par classification en volume, volatilité réalisée, emballements de prix), règles traduites des articles,
chaque actif testé seul. Résultat : 66 essais, aucun approuvé.

| Lot | Hypothèses (source) | Essais | Résultat |
|---|---|---|---|
| M1 | retournement à fort volume (Campbell, Grossman et Wang 1993 ; Llorente et al. 2002) ; suivre le déséquilibre (Chordia et Subrahmanyam 2004) ; fournir la liquidité quand la volatilité est haute (Nagel 2012) | 3 × 9 actifs = 27 | aucun approuvé ; meilleur : Nagel sur 6E, 0,42 |
| M2 | contre-pied des emballements de prix (Christensen, Oomen et Renò 2022) ; régression volume × rendement sur 15 min ; dérive de nuit conditionnelle (Boyarchenko, Larsen et Whelan 2023) ; déséquilibre sur 5 min | 39 | aucun approuvé ; meilleur : emballements sur YM, 0,48 (0,42 après publication) |

Ce qu'on observe :
- les rendements accompagnés d'un fort volume se prolongent (ils ne se retournent pas) sur les 9 actifs, mais
  trop peu pour couvrir les coûts ;
- sur 5 minutes, le déséquilibre se retourne fortement avant coûts sur les devises : c'est le rebond entre
  achat et vente, impossible à exploiter après coûts.

## 14. Catalogue des articles SSRN au moins intraday (`outils/ssrn_intraday.py`)

```
cd Python
python outils/ssrn_intraday.py --sortie ssrn_intraday     # -> ssrn_intraday.csv et ssrn_intraday.html
```

L'outil interroge **OpenAlex** et **Crossref**, deux index publics, gratuits et sans clé, qui couvrent les
articles SSRN dotés d'un DOI (préfixe 10.2139). SSRN n'a pas d'API et interdit qu'on aspire son site.

Fonctionnement :
- environ 50 requêtes par mot-clé (intraday, haute fréquence, nuit/séance, ouverture/clôture, microstructure,
  fixings…), avec toutes les pages de résultats ;
- fusion des résultats par numéro SSRN ;
- on ne garde que les articles dont le titre ou le résumé contient un terme d'horizon intraday ou plus court.

Chaque article reçoit des étiquettes :
- horizon ;
- actifs, dont « nos actifs » : futures sur indices, or, pétrole, devises ;
- règle de trading ou prédictibilité ;
- nombre de citations ;
- statut « déjà testé » pour les articles passés dans ce dépôt.

La page HTML est autonome : recherche, filtres et tri. Chaque lien peut recevoir un statut (à lire, à tester,
testé, rejeté, retenu) et une note. Ils sont gardés dans le navigateur et s'exportent en CSV. Le script
n'utilise que la bibliothèque standard de Python. Tests : `tests/test_ssrn_intraday.py` (API simulées).
