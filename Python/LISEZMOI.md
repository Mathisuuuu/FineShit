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
