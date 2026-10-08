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
python -m nexus tout -d DOSSIER                                # toutes les fiches + tableau récapitulatif
python -m nexus grille -s 01 -d DOSSIER -p lookback_days=126,252 -p skip_days=0,21 --walkforward 180/30
python -m nexus recherche --type tsmom -d DOSSIER -p lookback=63,126,252 -p skip=0,21
```

- `--debut` / `--fin` bornent les données chargées ; `--debut-trading` laisse le chauffage avant cette
  date (indicateurs calculés, aucun ordre) et ne compte que la période tradée dans le rapport.
- Les noms de paramètres sont ceux du C# en minuscules avec des tirets bas
  (`LookbackDays` → `lookback_days`) ; `python -m nexus liste --details` les affiche.
- `grille` lance le moteur complet pour chaque configuration, puis calcule le **PBO** (CSCV), le
  **Deflated Sharpe** avec le vrai nombre d'essais et un **walk-forward** (sélection sur la fenêtre
  d'entraînement, rendement hors échantillon concaténé).
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

Contrôles : `python -m pytest -q tests` (35 tests) reprend les contrôles numériques de
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
