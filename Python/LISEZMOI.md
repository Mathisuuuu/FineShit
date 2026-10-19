# Nexus en Python (vectorbt)

Moteur de backtest Python des fiches Nexus et des stratégies minute étudiées depuis. Il reprend la logique des
fichiers NinjaScript du dépôt (fiches 1 à 14, modules A, B, C) et la complète ; les stratégies minute (fiche 15
LETF, fiche 16 Noise Area, S1, Gotobi, ORB, or la nuit) sont construites dans vectorbt et exportées vers le
tableau de bord Node.js (`../Dashboard`).

> Spécifications de recherche, pas des conseils d'investissement. Un backtest ne remplace pas le
> paper trading ; faire relire chaque rapport par une seconde IA (`python -m nexus audit`).

## 1. Fiches et modules

| Fiche | Module (`nexus/strategies/`) | Données nécessaires |
|---|---|---|
| 1 TSMOM | `s01_tsmom.py` | cours journaliers |
| 2 XSMOM | `s02_xsmom.py` | cours journaliers |
| 3 Multi-facteurs | `s03_multifactor.py` | cours + `Data/fundamentals.csv` (sinon momentum + sécurité seulement) |
| 4A Résidu actions | `s04a_residual.py` | actions + ETF sectoriels ; `Data/ff_factors.csv` pour le mode mensuel |
| 4B Crypto 15 min | `s04b_crypto.py` | klines Binance 15 min ou 1 min avec `taker_buy_volume` (ou fichiers de transactions) |
| 5 Vol mean reversion | `s05_volmr.py` | cours journaliers |
| 6 Paires | `s06_pairs.py` | cours journaliers |
| 7 Actualités + LLM | `s07_newsllm.py` | cours + `Data/news.csv` + réponses LLM (cache ou API) |
| 8 Juge LLM | `s08_judge.py` | cours + actualités + `Data/earnings.csv` ; fondamentaux pour la source fiche 3 |
| 9 Consensus 3 LLM | `s09_consensus.py` | cours + actualités + Claude, DeepSeek, Gemini (cache ou API) |
| 10 FinBERT | `s10_finbert.py` | cours + actualités + FinBERT local (serveur ou `transformers`) |
| 11 Roue d'options | `s11_wheel.py` | cours journaliers (+ `^VIX` / `^VXN` en mode indice de vol) |
| 12 Régime de vol | `s12_volregime.py` | cours journaliers (+ `^VIX`) |
| 13 Trend prop 24/5 | `s13_proptrend.py` | FX, or, indices + `Data/macro_events.csv` pour le veto |
| 14 Swing strict | `s14_strictswing.py` | cours + `Data/earnings.csv` |
| 15 LETF NQ / ES (candidate) | `letf.py` (vectorbt direct) | minutes NQ et ES (Cotations), GEX SqueezeMetrics ; voir § 13 |
| 16 Noise Area (barres 1 min) | `s16_noisearea.py` | minutes ; Python seulement, voir § 8 |
| **S1 Noise Area NQ** | `s1_noiseareanq.py` + `S1_NoiseAreaNQ.py` | **validée le 2026-10-15, réglage figé**, voir § 9 |
| Gotobi 6J (candidate) | `gotobi.py` (vectorbt direct) | minutes 6J ; voir § 10 |
| ORB 5 min NQ (candidate) | `orb.py` (vectorbt direct) | minutes NQ ; voir § 11 |
| Or la nuit GC (candidate) | `or_nuit.py` (vectorbt direct) | minutes GC ; voir § 12 |
| Module A | `regime.py` | HMM 3 états (Baum-Welch compilé numba) + terciles ; commande `regime` |
| Module B | `sizing.py` | demi-Kelly bayésien, waiver, diviseur de corrélation, plafonds |
| Module C | `risk.py`, `validation.py`, `report.py`, `collect.py` | disjoncteurs, coûts, stress test, Monte Carlo, bootstrap, DSR, PBO, walk-forward, corrélation du portefeuille, audit par une seconde IA |
| Tableau de bord | `tableau.py` | export JSON des 5 stratégies ci-dessus pour `Dashboard/` (§ 10) |
| Recherche locale | `perso/` | 74 stratégies et anomalies testées dans les sessions locales (§ 16) |

## 2. Installation

```
cd Python
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
```

Python 3.10 ou plus récent (testé avec 3.11, pandas 3, vectorbt 1.1). L'environnement `.venv` du dossier
`Python` est celui qu'utilise le bouton « Recalculer » du tableau de bord. Toutes les commandes se lancent
depuis le dossier `Python` (avec `.venv\Scripts\python` à la place de `python`).
FinBERT en mémoire (fiches 7, 9, 10) est optionnel : `pip install transformers torch`.

## 3. Données

### 3.1 Le dossier `Cotations` (futures Databento)

Par défaut, les commandes lisent `../Cotations` : 10 contrats continus Databento en minute
(ES, NQ, YM, FDAX, GC, CL, 6E, 6B, 6J, 6A). Ce dossier est sous licence Databento (usage privé,
redistribution interdite) : il est exclu du dépôt par `.gitignore` et ne doit jamais être poussé.

Traitement automatique à la lecture :

- **Roulements.** Les séries `.v.0` changent d'échéance sans ajustement. Le changement est détecté
  exactement si le fichier contient une colonne `instrument_id` / `raw_symbol`. Sinon une heuristique le
  cherche : au plus un roulement par fenêtre calendaire, au saut de minuit UTC le plus anormal.
  Les prix sont ensuite ajustés vers l'arrière (`--ajustement proportionnel | additif | aucun`).
- **Barres de séance.** CME : 17:00 → 16:00 Chicago (la séance du dimanche soir appartient au lundi) ;
  Eurex : jour calendaire de Francfort.
- **Cache.** Les séries agrégées sont mises en cache dans `Python/.cache` : la deuxième lecture est instantanée.

`python -m nexus verifier --profil futures` liste les roulements détectés et les cotations manquantes.

### 3.2 Autres formats

Un fichier par symbole (dossier lu récursivement). Formats reconnus :

- export NinjaTrader (`SPY.Last.txt`) ;
- Yahoo, Stooq ou CSV générique avec en-tête (noms français acceptés) ;
- MetaTrader ;
- klines Binance (avec ou sans en-tête ; la colonne `taker_buy_volume` est conservée pour la fiche 4B) ;
- Parquet.

Le symbole vient du nom de fichier : `BTC-USD.csv` → `BTCUSD`, `EURUSD=X.csv` → `EURUSD`, `^GSPC.csv` → `US500`.

### 3.3 Profil `futures`

Les fiches ont été écrites pour des actions US et de la crypto. `--profil futures` les adapte au
dossier Cotations :

- **Univers.** ES remplace SPY comme baromètre.
- **Taille.** Contrats micro (MES, MNQ, MGC, M6E…) et capital de 1 M$.
- **Plafonds.** Les plafonds de notionnel du module B, calibrés pour des actions sans levier, sont levés ;
  il reste un plafond d'exposition brute de 300 %.
- **Coûts.** 2,50 $ par contrat.
- **Fiche 6.** Paires sectorielles, vente à découvert autorisée.
- **Fiche 13.** Ses 8 marchés en futures.

Fiches couvertes : 1, 2, 5, 6, 12, 13, 14.

### 3.4 Données à ajouter pour les autres fiches

| Fiches | À ajouter | Source gratuite |
|---|---|---|
| 1, 2, 3, 4A, 8, 12, 14 | cours journaliers SPY, QQQ, ETF sectoriels XL*, actions de l'univers | Stooq, Yahoo |
| 3, 8 | `Data/fundamentals.csv` (bilans trimestriels datés de publication) | SEC EDGAR (XBRL) |
| 4A mensuel | `Data/ff_factors.csv` | bibliothèque de Ken French |
| 4B | klines Binance 1 min ou 15 min des 20 cryptos | data.binance.vision |
| 7, 8, 9, 10 | `Data/news.csv` (historique de titres) | aucune source gratuite historique ; collecter avec `actualites` |
| 8, 14 | `Data/earnings.csv` | Alpha Vantage (`actualites --resultats-av`) |
| 11, 12 | `^VIX`, `^VXN` | Cboe |
| 13 | `Data/macro_events.csv` (agenda macro) | calendriers économiques publics |

## 4. Commandes

```
python -m nexus liste [--details]                              # fiches, paramètres, profils
python -m nexus verifier [--profil futures]                    # cotations présentes / manquantes, roulements
python -m nexus backtest -s 01 [--profil futures] [--html] [-p target_vol_pct=10] [--audit claude]
python -m nexus backtest -s 01 --synthetique                   # démonstration sans données
python -m nexus tout [--profil futures]                        # toutes les fiches + rapport de portefeuille
python -m nexus portefeuille --resultats resultats/tout_...    # module C : corrélations, check-list avant le réel
python -m nexus grille -s 01 -p lookback_days=126,252 -p skip_days=0,21 --walkforward 180/30
python -m nexus valider [-s 01] [--profil futures] [--audit claude]   # module C complet, verdict par fiche
python -m nexus recherche --type tsmom -p lookback=63,126,252 -p skip=0,21
python -m nexus regime [--barometre ES] [--html]               # module A : HMM 3 états + terciles
python -m nexus actualites -s 07 [--reddit] [--resultats-av] [--prenoter]
python -m nexus audit --rapport resultats/.../rapport.txt [--fournisseur claude]
python -m nexus backtest -s 16 -p symbols=ES --html             # fiche 16, barres 1 minute (§ 8)
python -m nexus backtest -s S1                                  # S1, reglage fige (§ 9)
python -m nexus tableau [--seulement S1,G1,O1,N1,L1]            # export du tableau de bord (§ 10)
```

- `--donnees` / `-d` change le dossier de cotations (défaut `../Cotations`).
- `--debut` / `--fin` bornent les données ; `--debut-trading` laisse un chauffage avant cette date
  (indicateurs calculés, aucun ordre).
- Les paramètres sont ceux du C# en minuscules avec des tirets bas (`LookbackDays` → `lookback_days`).
  Priorité : fichiers `Data/*.csv` < profil < `-p`.
- `grille` lance le moteur complet par configuration, puis calcule le PBO (CSCV), le Deflated Sharpe
  avec le vrai nombre d'essais et un walk-forward.
- `valider` applique tout le module C a chaque fiche : petite grille sur ses parametres [Choix], walk-forward
  180/30, PBO, Deflated Sharpe corrige du nombre d essais, Monte Carlo, 30 trades + cycle drawdown, PnL net,
  puis verdict VALIDEE / NON VALIDEE (option `--audit` : relecture par une seconde IA).
- `recherche` est une grille vectorbt signal seul (sans module B ni stops), pour explorer vite.
- `tout` fait tourner les fiches minute (16, S1) une fois par instrument présent en barres minute.
- Les résultats vont dans `resultats/<stratégie>_<date>/` : `rapport.txt`, `trades.csv`, `fills.csv`,
  `equity.csv`, `journal.txt`, `signaux.csv`, et `graphique.html` avec `--html`.

## 5. LLM, actualités et FinBERT (fiches 7, 8, 9, 10, veto de la 13)

**Clés API.** Ordre de recherche : paramètre (`-p llm_api_key=...`, à éviter), variable d'environnement
(`ANTHROPIC_API_KEY`, `DEEPSEEK_API_KEY`, `GEMINI_API_KEY`, `NEWSAPI_KEY`, `ALPHAVANTAGE_KEY`), puis un
fichier `NOM=valeur` : `Python/keys.txt`, `.env.txt` ou `.env` à la racine du dépôt, ou
`Documents/NinjaTrader 8/Nexus/keys.txt`. Ces fichiers sont exclus du dépôt.

**Cache et coût.** Chaque réponse est mise en cache dans `Python/.cache/llm_cache.tsv`, au même format
et avec les mêmes clés que le C# (le cache NinjaTrader est relu s'il existe). Par défaut, un backtest
**n'appelle jamais l'API** : seules les réponses en cache servent, les titres sans réponse sont comptés
« non notés ». Méthode recommandée :

1. lancer une fois avec `-p api_calls_in_backtest=true` (budget `max_api_calls_per_run=500`) ;
2. relancer ensuite gratuitement, autant de fois que nécessaire.

Chaque appel payant est journalisé dans `Python/.cache/ai_costs.csv`. Le rapport compare le PnL au
coût API si les prix par token sont renseignés (`llm_price_in_per_mtok`, `llm_price_out_per_mtok`).

**Actualités.** `Data/news.csv` (`published_utc,symbol,source,headline,url`, heures en UTC) plus
`Data/news_live.csv`, que remplit `python -m nexus actualites`. Cette commande appelle NewsAPI (requêtes
groupées par 8 symboles) et, en option, Reddit, Fear & Greed et le calendrier de résultats Alpha Vantage.
Les doublons sont écartés : un même événement repris par plusieurs sources compte pour un seul titre.
`--prenoter` note tout de suite les nouveaux titres avec la consigne exacte de la fiche, pour que le cache
soit chaud au backtest suivant.

**Horodatage (fiche 7).** Un titre publié avant l'ouverture est tradé à l'ouverture du jour ; après,
à l'ouverture du lendemain. Marge : `news_cutoff_minutes` (5) + `data_delay_minutes` (ou la variable
`NEXUS_DATA_DELAY_MINUTES`).

**FinBERT.** Trois modes via `finbert_mode` :

- `serveur` : `Tools/finbert_server.py` ;
- `local` : modèle `ProsusAI/finbert` chargé en mémoire ;
- `auto` (défaut) : le serveur, puis le modèle en mémoire.

Les scores sont mis en cache dans `Python/.cache/finbert_cache.csv`.

## 6. Différences avec le C# et corrections

Reproduit à l'identique :

- décisions à la clôture, ordres à l'ouverture suivante, réductions avant entrées ;
- ordres limites valables N barres, stops natifs (ouverture si gap, sinon prix du stop) ;
- coûts du module C, conversion de devises, comptabilité par trade ;
- module B, rééquilibrage mensuel avec rattrapage.

Corrections apportées par rapport au code NinjaScript (révélées par le portage) :

1. **Waiver ×0,5 en backtest.** Le compteur de trades réels vaut toujours 0 en backtest, donc le waiver
   s'appliquait toujours. Il ne s'applique plus que sur demande (`waiver_in_backtest=true`).
2. **Diviseur de corrélation.** Il ne vaut plus que pour les signaux dimensionnés par Kelly, face aux
   positions ouvertes. Les portefeuilles des fiches 1, 2, 3, 5, 12, 13 sont déjà dimensionnés ensemble ;
   les diviser écrasait l'exposition (1,5 % au lieu de ~24 % sur la fiche 1).
3. **Kelly ≤ 0.** Le blocage était définitif : sans trade fermé, l'estimation ne pouvait plus remonter.
   Les entrées passent désormais en taille sonde de 0,25 %, signalée dans le rapport ;
   `no_edge_fraction_pct=0` rétablit le blocage.
4. **Disjoncteur journalier.** La perte du jour est mesurée depuis la clôture de la veille, comme en
   temps réel ; `daily_breaker_ref=ninja` reproduit l'ancien comportement.
5. **Fiche 5.** Le seuil de dérive de 20 % compare maintenant des grandeurs comparables.
6. **Fiches 4A, 4B, 6, 7, 9, 10, 14.** Un plafond par trade désactivé (`max_trade_pct=0`) donnait une
   taille nulle ; il ne bride plus rien.
7. **Fiche 13.** La référence de la perte journalière prop est l'equity de la veille.
8. **Fiche 11.** Après assignation, la jambe action partait du strike alors que la jambe put avait déjà
   payé K − S : la perte était comptée deux fois dans les trades (pas dans l'equity). La jambe action va
   maintenant du cours à l'assignation au cours à l'appel.
9. **Fiche 8.** Un verdict du juge vaut `rejudge_days` jours (5) tant que le symbole reste candidat.
   Sans cela, un candidat bloqué par les plafonds était rejugé chaque jour : un appel payant par jour et
   des trades fantômes dupliqués. `rejudge_days=0` revient au C#.

Écarts assumés :

- **Quantités crypto.** Le moteur garde des quantités entières, mais une unité crypto vaut
  `crypto_unit` = 0,0001 pièce. Sans cela, 3 % de 100 000 $ en BTC arrondirait à 0.
  `crypto_unit=0` retrouve le comportement NinjaTrader.
- **Fiche 4B.** Le filtre de choc partagé avec les autres stratégies n'existe qu'en temps réel. En
  backtest, le mode `filtre_seulement` mesure à la place l'avantage à terme de chaque choc : rendement
  à N barres, retour au milieu de la barre, trade maker théorique comparé aux frais. Il exporte aussi
  les chocs (`shocks_file`).
- **Fiche 11.** Pas de routage réel d'ordres d'options. Le mode `signal_seul` écrit des tickets au journal.
- **Fiche 13.** Pas de webhook ni de comptes miroirs (temps réel). Le veto macro existe en trois
  variantes : par règles, par Claude, ou règles puis Claude.
- **Exécution.** Stops actifs dès la barre d'entrée ; jours fériés déduits des données.

## 7. Résultats sur Cotations (profil futures, janvier 2016 - août 2026)

1 M$, contrats micro, coûts inclus (2,50 $ par contrat + glissement de 0,05 %) :

| Fiche | Trades | Rendement total | Sharpe | Drawdown max |
|---|---|---|---|---|
| 1 TSMOM | 243 | +21,0 % | 0,48 | 10,0 % |
| 2 XSMOM | 93 | +49,5 % | 0,59 | 17,2 % |
| 5 Vol MR | 1 (position permanente redimensionnée) | +125 % | 0,78 | 17,5 % |
| 6 Paires | 6 | −0,06 % | −0,23 | 0,1 % |
| 12 Régime de vol | 477 | +0,7 % | 0,04 | 17,2 % |
| 13 Trend prop | 880 | −6,1 % | −0,11 | 13,0 % |
| 14 Swing strict | 267 | +3,0 % | 0,20 | 4,0 % |

Corrélation 0,67 entre les fiches 1 et 2 : les demi-Kelly additionnés surestiment le risque.
La fiche 6 trouve peu de paires co-intégrées sur 10 futures ; la fiche 13 perd sur cet univers.

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
python -m nexus backtest -s 16 -d ../Cotations/indices -p symbols=ES -p initial_bankroll=1000000 --html
python -m nexus tout -d ../Cotations/indices -p initial_bankroll=1000000 --html     # ES, NQ, YM au récapitulatif
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
python S1_NoiseAreaNQ.py --donnees ../Cotations/indices/NQ_v0_1m.parquet
# moteur nexus (rapport, graphique vectorbt) ; les parametres de strategie sont verrouilles
python -m nexus backtest -s S1 -d ../Cotations/indices -p initial_bankroll=1000000 --html
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
python -m nexus tableau                                  # ../Cotations -> ../Dashboard/donnees/*.json (environ 10 min)
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
O1 ORB, N1 or la nuit, L1 fiche 15 LETF). Le lien « Archive de la recherche » du tableau de bord ouvre la
page des stratégies testées en local (`python -m nexus.perso.tableau` l'écrit dans `Dashboard/donnees/`).
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

## 13. Fiche 15 — rebalancement des ETF à levier sur NQ / ES (candidate, `nexus/letf.py`)

Portage Python du NinjaScript `Strategies/Nexus15_LetfRebalancing.cs` (session cloud du 14/10/2026), mêmes
règles et mêmes valeurs par défaut, construit directement dans vectorbt (`Portfolio.from_signals`, colonnes NQ
et ES, trésorerie commune). Source : Barbon, Beckmeyer, Buraschi & Moerke, *Liquidity Provision to Leveraged
ETFs and Equity Options Rebalancing Flows*, SSRN 3925725.

| Heure (New York) | Règle |
|---|---|
| 15:25 | r = cloture de la veille -> 15:25 ; flux des LETF F = Σ A L(L-1) r / (1 + L r) ; S = F / (multiplicateur × niveau) / V (volume moyen 15:30-16:00 sur 20 séances) ; Score = S × w (w = 1 si GEX < 0 ou inconnu, 0,3 sinon) |
| 15:30 | trade si \|r\| ≥ 0,5 %, \|Score\| ≥ q70 des 250 séances précédentes, jour non exclu (FOMC, CPI, NFP, quatre sorcières, demi-séances, rebalancement spécial NDX) ; NQ d'abord, ES en secours ; entrée au marché dans le sens de r |
| 15:30-16:00 | stop 1,5 × ATR(14) des barres de 30 min ; sortie à 16:00 ; jamais de position la nuit |

Taille : 0,5 % de 500 000 $ par écart-type du mouvement attendu en 30 min, × |Score| / seuil, contrats entiers,
plafond 2 % du volume de la fenêtre, **sans plafond de levier** (comme le NinjaScript ; levier médian 3,6,
jusqu'à 25 certains jours). Coûts : 1 tick aller-retour + 2,50 $ par contrat et par côté.

Écarts imposés par les données : l'actif net des fonds (`Data/letf_aum.csv`) est vide → encours **constants**
(ordre de grandeur 2024) ; le seuil q70 glissant est invariant à l'échelle, seule la croissance des encours
depuis 2016 manque. Un `letf_aum.csv` rempli (format du C#) est pris automatiquement. Le future remplace
l'indice ; GEX SqueezeMetrics (S&P 500 seul) de la veille.

Résultats (tableau de bord, 2016-2026) : 656 trades, Sharpe 0,50, perte max 25 %, mais **26 alertes** :
Sharpe 0,28 après publication et 0,10 sur les 2 dernières années, 4 années positives sur 11, pas mieux que
des jours tirés au hasard (p = 0,80), placebo 13:30-14:00 aussi bon (0,54), Sharpe 0,26 avec un levier ≤ 4 et
−0,16 sans le filtre gamma. Mécanisme : la dernière demi-heure ne prolonge pas le mouvement du jour (pente
≈ 0) sauf quand les teneurs de marché sont courts gamma (interaction t ≈ 2), ce qui rejoint
`perso/gamma_intraday.py`. Verdict : **rejetée en l'état**. Tests : `tests/test_letf.py`.

## 14. Groupe P1 (en cours) : intraday, Sharpe ≥ 1 avant et après publication (`nexus/p1.py`)

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

## 15. Catalogue des articles SSRN au moins intraday (`outils/ssrn_intraday.py`)

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
## 16. Recherche locale : stratégies NinjaScript personnelles et anomalies (`nexus/perso`)

Les scripts du dossier `Documents/NinjaTrader 8/bin/Custom/Strategies` (suite S01-S20, MyCustomStrategy1-4,
ZarattiniEnvelope, IntradayMomentumC01, boombitch, AUDusd) sont portés dans `nexus/perso` :

- `qf.py` : moteur intrajournalier qui reproduit NinjaTrader et le socle `QuantStrategyBase` (QF_Core.cs) :
  heures en ET, décision à la clôture, exécution à l'ouverture suivante, stops et objectifs en prix,
  ordres limites, sortie de fin de séance, commission par contrat et 1 tick de glissement ;
- `suite_s.py` : S01 (A, B, D), S02 (A, B, C), S05-A, S06 (A, B), S07-A, S09 (A, B), S11 (A, B), S19 (A, B), S20 (A, B) ;
- `user.py`, `ict.py` : les scripts personnels ;
- `runner.py` : lance tous les backtests et écrit `recherche/resultats_strategies.txt` (une ligne par stratégie).

```
python -m nexus.perso.runner [--processus 4] [--seulement S01-A,boombitch]
```

Données : minutes de futures Databento (`Cotations`, ajustement additif des roulements, proportionnel pour
le CL dont l'historique ajusté deviendrait négatif), minutes de SPY et d'IWM et crypto 15 min téléchargées chez
Alpaca (`nexus/alpaca.py`, `minutes_cache("IWM")` pour une nouvelle action ; clés `APCA_API_KEY_ID` /
`APCA_API_SECRET_KEY` dans `.env.txt`). IWM sert de substitut au future Russell 2000 (RTY / M2K, absent des
données Databento) pour S06-C : 500 parts ≈ 1 RTY.
Les bugs trouvés dans le C# sont reproduits (version « tel que codé ») et corrigés dans une seconde version.
Les variantes à ML ou à actualités ne sont pas portées. La liste de ce qui n'est pas testé, et pourquoi, est en fin
de `recherche/resultats_strategies.txt` (lignes « NON TESTEES »).

Historique long du DAX (S19-B) : Databento n'a l'Eurex que depuis mars 2025. `nexus/dukascopy.py` télécharge les
minutes du CFD DAX cash de Dukascopy depuis 2014 (usage personnel, cache `.cache/dukascopy`, reprise automatique) :

```
python -m nexus.dukascopy DEUIDXEUR 2014-01-01 2026-08-28
```

Analyses sur les résultats du runner (elles relisent les fichiers de `resultats/perso_*`) :

- `python -m nexus.perso.inversion` : que donne chaque stratégie perdante jouée à l'envers (mêmes trades, sens
  opposé, frais payés une seconde fois) → `recherche/resultats_inversees.txt` ;
- `python -m nexus.perso.portefeuille --compte 50000 --perte-jour 1000 --dd-suiveur 2000 [--objectif 3000]` :
  portefeuille pour un compte prop futures → `recherche/resultats_portefeuille_prop.txt`. Retient les stratégies nettement
  positives (Sharpe ≥ 0,3, positives sur 2016-2020 et 2021-2026, au moins 1 micro par position), puis :
  - `Diversification` : corrélations des P&L quotidiens, corrélation les jours de pertes, stabilité sur 1 an
    glissant, ratio de diversification, sélection peu corrélée ;
  - `Chevauchement` : temps en position, recouvrement dans le temps, conflits sur le même contrat (deux
    stratégies sur NQ en même temps se compensent dans un compte unique), profil horaire ;
  - `meilleurs_groupes` : groupes sans conflit de contrat et peu corrélés, taille maximale sans violation des
    règles (perte journalière, drawdown suiveur de fin de journée) ;
  - `evaluation_prop` : l'évaluation rejouée en partant de chaque jour (taux de réussite, d'échec, durée
    médiane) à plusieurs tailles, comparée au hasard (une stratégie sans avantage réussit
    dd / (objectif + dd) des évaluations).

Tableau de bord (vectorbt) : `python -m nexus.perso.tableau` écrit `../Dashboard/donnees/recherche.html` (lien « Archive de la recherche » du tableau de bord), une page autonome
(plotly.js intégré, s'ouvre par double-clic, sans connexion) à régénérer après chaque passage du runner :

- le top des stratégies : quatre critères fixés d'avance (Sharpe significatif = borne basse de l'IC à 95 % > 0 ;
  stable = Sharpe positif sur 2016-2020 et 2021-2026 ; pas seulement du bêta = alpha contre le SPY avec t ≥ 2 et pas
  de verdict « surtout du bêta » dans `recherche/resultats_alternatives.txt` ; données fiables = 5 ans au moins, sans biais du
  survivant ni options synthétiques), classement par critères remplis puis par la borne basse de l'IC du Sharpe ;
- toutes les stratégies (tableau triable, filtres par verdict, recherche) ;
- un explorateur par stratégie : statistiques vectorbt (rendement, Sharpe, Sortino, Calmar, Omega, drawdown max,
  plus long drawdown, tail ratio, VaR, asymétrie), gain cumulé et drawdown, Sharpe sur 1 an glissant, P&L mensuel,
  les 5 pires drawdowns (enregistrements vectorbt) ;
- le portefeuille prop firm futures : comptes 50k / 100k / 150k, règles modifiables (objectif, perte du jour,
  drawdown suiveur, durée), classement des stratégies et groupes par taux de réussite de l'évaluation recalculé
  dans la page (mêmes calculs que `portefeuille.py`), corrélations, conflits de contrat, profil horaire ;
- la recherche sur les 60 stratégies intraday : t de chaque anomalie, tableau des critères, variantes de NQ 1,
  familles éliminées et stratégies en attente (lu dans `recherche/resultats_60.json`, écrit par `soixante`, `soixante_bc` et
  `nq1_variantes`).

Les cotations sources (licence Databento) ne sont pas dans la page : seulement les P&L quotidiens des backtests.

Intervalles de confiance, edge et Monte Carlo : `python -m nexus.perso.statistiques` → `recherche/resultats_ic_montecarlo.txt`
(une ligne par stratégie), repris dans le tableau de bord (colonnes « Edge / trade » et « P(Sharpe > 0) », graphique
des Sharpe avec leur intervalle à 95 %, panneaux « Edge » et « Monte Carlo » de l'explorateur) :

- edge = gain moyen par trade net de coûts, IC à 95 % par bootstrap des trades (2 000 tirages) et loi de Student,
  P(edge > 0) ; taux de réussite (Wilson) ; profit factor (bootstrap) ;
- temps en position par trade (colonne « Durée moy. ») : moyenne, médiane, gagnants / perdants et plus long, en temps
  calendaire de l'entrée à la sortie (nuits et week-ends compris), à une barre près ;
- Sharpe annualisé avec l'erreur type de Mertens (rendements non normaux) et P(Sharpe > 0) (Sharpe probabiliste) ;
- Monte Carlo par bootstrap en blocs de 10 jours du P&L quotidien : cône des trajectoires sur un an (centiles
  5 / 25 / 50 / 75 / 95), P(perte sur un an), drawdown sur un an, distribution du drawdown sur l'historique rejoué
  (centile du drawdown réel), pire série de pertes. Le bootstrap mesure le hasard du tirage, pas un changement de régime.

Fil ES/NQ « 6 mois de simulation » (order flow) : `python -m nexus.perso.orderflow` → `recherche/resultats_orderflow.txt`.
Fiches 1 (choc prix + volume) et 3 (retour au POC) testées sur ES et NQ en micros, 1R = 250 $, avec les paramètres
des fiches figés avant le test ; fiche 4 en filtre (VPIN par classification en volume, annonces 08:30 / 10:00 ET et
FOMC) ; modules A (taille en R, 2 positions, perte du jour 3R, seuils d'arrêt) et B (intervalles de confiance,
concentration, périodes, coûts 2 / 4 ticks, régimes de volatilité, Sharpe déflaté, PBO). La fiche 2 (absorption) et
le déséquilibre du carnet de la fiche 4 demandent des données de carnet (Databento mbp-1 / tbbo) : `ofi_cont()` et
`absorption()` sont prêts, mais rien n'est testé sur les barres 1 minute.

Trois stratégies FX combinées : `python -m nexus.perso.fx_trois` → `recherche/resultats_fx.txt` (futures 6E, 6B, 6J, 6A en
micros, 1R = 250 $).

- Fix flow (16:00 Londres) : dollar acheteur 15:00 → 16:00, vendeur 16:00 → 16:15 (Krohn, Mueller & Whelan), en fin
  de mois seulement et dans le sens du signal de Melvin & Prins (SPY contre EZU / EWU / EWJ / EWA sur le mois) ;
  stop à 2 fois la volatilité attendue de la fenêtre (Andersen & Bollerslev). Anomalie précise : rien n'est optimisé.
- Post-annonce + flux (NFP, CPI, calendrier BLS dans `nexus/perso/annonces_us.csv`) : attente de 5 à 15 min (ABDV),
  surprise implicite (mouvement du panier dollar standardisé sur les annonces passées, faute de consensus), entrée si
  le flux de la paire confirme (Love & Payne), sortie au temps ou à un multiple d'ATR. Attente et durée choisies en
  walk-forward (3 ans d'apprentissage, choix annuel, hors échantillon 2019-2026).
- Cascade de stops sur chiffres ronds (Osler) : niveaux 00 / 50 du prix non ajusté du future (USD/JPY = 1 / 6J),
  continuation après cassure nette avec accélération, rebond après approche sans cassure avec ralentissement, filtre
  horaire de Ranaldo. Seuil de cassure, accélération et durée choisis en walk-forward.

Le rapport donne, pour chacune : coûts réalistes (glissement élargi au fix et après les annonces) et stress,
diagnostic sans coûts, l'anomalie mesurée sans exécution (rendement du dollar autour du fix, effet du signal de
Melvin & Prins, biais horaire de Ranaldo), PBO de la grille, Sharpe déflaté, persistance par année et combinaison des
trois. Le runner relit les trades de la dernière étude (`resultats/fx_*`).

Gotobi Pre-Fix Drift : `python -m nexus.perso.gotobi` → `recherche/resultats_gotobi.txt`. Achat de USD/JPY (vente du 6J,
micro MJY) de 09:00 à 09:55 heure de Tokyo les jours gotobi (5, 10, 15, 20, 25, 30 et dernier jour du mois, décalés au
jour ouvré précédent ; jours fériés japonais dans `nexus/perso/feries_japon.csv`), abstention si le dollar a déjà
monté de plus d'une volatilité habituelle entre 08:00 et 09:00, stop à 1,5 volatilité robuste de la fenêtre. Règles de
la fiche, sans optimisation. Le rapport teste d'abord l'anomalie contre un groupe témoin (même fenêtre les jours non
gotobi : t de Welch et permutation, par période et par année), puis la stratégie (MJY, 6J standard, stress, sans
coûts) et la seconde jambe (vente 09:55 → 11:00) mesurée à part.

Or, 10 stratégies intraday fondées sur des anomalies (fiche du 9 octobre 2026) : `python -m nexus.perso.or_anomalies`
→ `recherche/resultats_or.txt`. Ordre de travail de la fiche : (1) effet brut de chaque anomalie, sans exécution, année par
année et contre sa fenêtre témoin ; (2) critères de sélection : t total ≥ 3 (tests multiples, Harvey, Liu & Zhu) et
signe stable sur 2024-2026 ; (3) règles de trading de la fiche, paramètres figés, micro MGC, 1R = 250 $, coûts et
stress à 0,30 $/once, critère d'abandon sur les 50 derniers trades. Substituts : surprise du FOMC mesurée par le dollar
(le rendement à 2 ans manque) ; stratégie 5 non testable (consensus et dispersion des prévisions absents) ; filtres PCE,
annonces européennes et tours d'enchère LBMA omis faute de calendrier.

60 stratégies intraday par actif (vue d'ensemble du 9 octobre 2026) : `python -m nexus.perso.soixante` →
`recherche/resultats_60_niveau_A.txt`. Étape 1 de la vue d'ensemble : anomalie brute des stratégies de niveau A et A contesté,
avec les conventions communes (prix à l'ouverture de la barre qui commence à l'heure indiquée, fuseaux IANA, jour exclu
si le contrat change dans la fenêtre, coûts du tableau) et les critères fixés avant le test (t ≥ 3, même signe et
t ≥ 1,5 sur 2016-2020 et 2021-2026, Welch ≥ 2 contre le témoin, net de coûts > 0, encore > 0 sans les 3 meilleurs jours ;
événements rares : t ≥ 2 et net positif ≥ 65 % des années). Les onglets par actif n'ayant pas été fournis, chaque
définition est la lecture du papier cité ; elles seront remplacées par celles des onglets.

Étape 2, niveaux B et C : `python -m nexus.perso.soixante_bc` → `recherche/resultats_60_niveaux_BC.txt`. Mêmes critères, test
par familles (l'actif le mieux placé d'abord ; s'il échoue, la famille entière est éliminée) : ES 2, IWM 2, ES 3 et
YM 2 en tête de famille, les membres de la famille « banque centrale » (6E 3, 6B 3, 6J 4, 6A 4) en attendant DAX 2,
puis les 14 fiches isolées. DAX 1 à 5 et 6E 1 attendent les minutes du DAX ; CL 3 demande le contrat qui expire.

Calendriers des niveaux B et C (`python -m nexus.perso.calendriers` affiche le contrôle par le pic de volume) :
`banques_centrales.csv` (BCE, Banque d'Angleterre, Banque du Japon, Banque de réserve d'Australie, sites officiels,
réunions d'urgence marquées et exclues), `chine_nbs.csv` (calendriers officiels du NBS, date et heure de Pékin),
`recherche/resultats_megacaps.csv` (8-K de résultats de AAPL, MSFT, AMZN, GOOGL, META, NVDA, heure « Accepted » des pages
d'index EDGAR) ; ISM manufacturier (1er jour ouvré), ISM services (3e) et Conference Board (dernier mardi, décembre
exclu) par règle. L'heure de la Banque du Japon, qui n'est pas fixe, est reconstituée par le pic de volume du 6J.

NQ 1, variantes corrigées : `python -m nexus.perso.nq1_variantes` → `recherche/resultats_nq1_variantes.txt`. Protocole écrit
avant le calcul (en-tête du module) : B = heure réelle du communiqué reconstituée par le volume de l'action, C = signal
tiré de la réaction de l'action ; retenue = critères de la vue d'ensemble et Sharpe déflaté ≥ 0,95 pour 33 essais.
Contrôle de l'heure contre les 8-K d'AAPL, NVDA et GOOGL (déposés à la minute du communiqué) : il échoue, car le volume
d'après-clôture monte avant le communiqué. B et C sont donc invalides, et la version d'origine reste à t 2,8. Minutes des
six actions (heures étendues) : `.cache/alpaca_minute/`.

Stratégie construite sur les papiers de la Fed de New York : `python -m nexus.perso.derive_nocturne` →
`recherche/resultats_derive_nocturne.txt`. Boyarchenko, Larsen & Whelan, « The Overnight Drift » (Review of Financial Studies,
2023 ; NY Fed Staff Report 917) : l'E-mini gagne l'essentiel de son rendement de 2:00 à 3:00 ET, à l'ouverture
européenne, quand les teneurs de marché écoulent le déséquilibre d'ordres de la clôture américaine ; « The Disappearing
Overnight Drift » (Liberty Street Economics, juillet 2026) : effet nul depuis 2021, parce que les gros déséquilibres de
clôture sont devenus rares. Protocole écrit avant le calcul (en-tête du module) : étape 1, l'anomalie et son mécanisme
(déséquilibre approché par BVC sur les minutes, VIX du CBOE) ; étape 2, une seule stratégie cohérente avec les deux
papiers (achat de 1:30 à 3:30 ET seulement après un gros déséquilibre vendeur et un VIX ≥ 20), avec l'anomalie brute
et la stratégie exacte du papier en référence, répliquées sur NQ et YM. VIX : `.cache/fred/VIX_History.csv` (CBOE) et
`VIXCLS.csv` (FRED), gratuits.

Exposition gérée par la volatilité, construite sur neuf papiers : `python -m nexus.perso.vol_geree` →
`recherche/resultats_vol_geree.txt`. Moreira & Muir (JF 2017) et les papiers qui le discutent : Cederburg et al. (JFE 2020), Liu,
Tang & Zhou (JPM 2019), Barroso & Detzel (JFE 2021), Harvey et al. (Man Group, JPM 2018), Bongaerts, Kang & van Dijk
(FAJ 2020), Wang & Yan (JBF 2021), DeMiguel et al. (JF 2024), Moreira & Muir (JFE 2019). Stratégie retenue avant le
calcul : la version conditionnelle de Bongaerts et al., en temps réel (exposition réduite seulement après un mois du
quintile le plus agité, augmentée jusqu'à 2 après un mois du quintile le plus calme, sinon 1). Étape 1 sur le marché
américain de Ken French (1926-2026, gratuit : `.cache/french/`), avant et après la publication des papiers ; prédiction
de Harvey et al. vérifiée sur nos futures (actions contre or, pétrole et devises) ; étape 2 sur ES, NQ, YM, nette de
coûts.

Cycle du FOMC et « Fed put », construit sur six travaux : `python -m nexus.perso.cycle_fomc` →
`recherche/resultats_cycle_fomc.txt`. Cieslak, Morse & Vissing-Jorgensen (JF 2019 : la prime des actions se gagne en semaines
paires du cycle du FOMC, surtout après une baisse) ; Uppal (Imperial College, 2025 : ne tient plus hors échantillon) ;
Cieslak & Vissing-Jorgensen (RFS 2021, le Fed put) ; Lucca & Moench (Fed de New York) ; Kurov et al. (2021) ; FEDS
Notes (Fed, 2020). Stratégie retenue avant le calcul : la version « Fed put » de CMVJ (semaine paire après une baisse
des 5 séances dans le quintile bas), la seule partie que personne n'avait réfutée. Marché américain de Ken French
1994-2026 et ES 2016-2026 ; réunions programmées du FOMC 1994-2026 : `nexus/perso/fomc_programmees.csv` (site de la
Réserve fédérale).

Pression de couverture et pression spéculative (rapports COT), construite sur huit travaux :
`python -m nexus.perso.pression_cot` → `recherche/resultats_pression_cot.txt`. Kang, Rouwenhorst & Tang (JF 2020 : effet de
liquidité d'une semaine et prime d'assurance de long terme), Fan, Fernandez-Perez, Fuertes & Miffre (JFM 2020, pression
spéculative sur 52 semaines, rémunérée dans les matières premières, devises et indices), Klitgaard & Weir (Fed de New
York 2004 : rien à une semaine sur les devises), Kearns & Manners (Banque de réserve d'Australie 2004), Sanders et al.
(2004), de Roon et al. (JF 2000), Maréchal (2023). Stratégie retenue avant le calcul : le portefeuille « partout » de
Fan et al. sur nos 9 futures, classes à parts égales, tenu un mois. Rapports COT « Legacy, Futures Only » de la CFTC,
gratuits : `.cache/cftc/` (un rapport n'est utilisé qu'à partir de son vendredi de publication).

`python -m nexus.perso.tendance` → `recherche/resultats_tendance.txt`. Suivi de tendance sur les 9 futures, construit sur sept
travaux : Moskowitz, Ooi & Pedersen (JFE 2012), Hurst, Ooi & Pedersen (AQR 2017), Baltussen, Swinkels & van Vliet (JFE
2021), Kurth, Eisler, Rej & Bouchaud (CFM, 2026 : depuis 2009 la tendance ne survit que sur les contrats à gros tick
rapporté à la volatilité), Huang et al. (JFE 2020), Kim, Tse & Wald (2016), Hutchinson & O'Brien (2014). V = signal
EWM à quatre horizons (5, 10, 20, 50 jours) sur la moitié « gros tick » du mois ; témoin = moitié « petit tick » ;
références : les 9 contrats et le momentum 12 mois de 2012.

`python -m nexus.perso.carry_fx` → `recherche/resultats_carry_fx.txt`. Portage de devises sur 6E 6B 6J 6A, construit sur neuf
travaux : Lustig, Roussanov & Verdelhan (JFE 2014, « dollar carry »), Daniel, Hodrick & Lu (CFR 2017), Koijen et al.
(JFE 2018), Hassan & Mano (QJE 2019), Andrews, Colacito, Croce & Gavazzoni (2020), Fan et al. (2022), Hsu et al. (JIMF
2024), Brunnermeier, Nagel & Pedersen (2008), Bekaert & Panayotov (JFQA 2020). V = acheter ou vendre les quatre devises
contre le dollar selon le signe du différentiel de taux moyen ; références : carry devise par devise et carry sans
dollar ; témoin = panier toujours acheteur. Taux à 3 mois de l'OCDE via la FRED (`.cache/fred/`, dernière valeur
prolongée quand la série s'arrête avant nos prix).

`python -m nexus.perso.saisonnalite` → `recherche/resultats_saisonnalite.txt`. Saisonnalité des rendements (même mois calendaire),
construite sur huit travaux : Keloharju, Linnainmaa & Nyberg (JF 2016 et JFE 2021), Baltussen, Swinkels & van Vliet
(JFE 2021), Heston & Sadka (JFE 2008), Baltas (2016), Hofmann & Keiber (2021), McLean & Pontiff (JF 2016), Jacobs &
Müller (JFE 2020). V = dans chaque classe (indices actions ES NQ YM, matières premières GC CL), classement par le
rendement moyen du même mois sur les 20 années précédentes ; témoin = même construction avec les autres mois ;
référence : les trois classes, devises comprises. Le signal vient de séries gratuites Yahoo Finance (`.cache/yahoo/`,
API « chart » : ^GSPC, ^NDX, ^DJI, GLD, CL=F, EURUSD=X, GBPUSD=X, JPY=X, AUDUSD=X), les rendements de nos futures.

`python -m nexus.perso.momentum_transversal` → `recherche/resultats_momentum_transversal.txt`. Momentum transversal (rendement
des mois m-12 à m-2), construit sur sept travaux : Asness, Moskowitz & Pedersen (JF 2013), Baltussen et al. (JFE 2021),
Daniel & Moskowitz (JFE 2016), Menkhoff et al. (JFE 2012), Goyal & Jegadeesh (RFS 2018), Moskowitz, Ooi & Pedersen (JFE
2012), Huang et al. (JFE 2020). V = indices actions et devises ; référence : les trois classes ; témoin = toujours
acheteur à risque égal. Test non aveugle (une variante proche avait servi de témoin au module COT) : verdict indicatif.

`python -m nexus.perso.rachat_baisse` → `recherche/resultats_rachat_baisse.txt`. Rachat après baisse (retournement de court terme
des indices), construit sur six travaux : Baltussen, van Bekkum & Da (JFE 2019 : depuis 2000 les indices se retournent,
à cause de l'arbitrage des produits indiciels), Nagel (RFS 2012 : prime de liquidité qui suit le VIX), Cieslak, Morse &
Vissing-Jorgensen (JF 2019), Lo & MacKinlay (1990), Lehmann (1990), Uppal (2025). V = position contraire à
4 r(t-1) + 3 r(t-2) + 2 r(t-3) + r(t-4) sur ES NQ YM ; référence : la même modulée par le VIX ; témoin : la même sur
l'or, le pétrole et les devises. Idée notée après coup : verdict indicatif.

`python -m nexus.perso.gamma_intraday` → `recherche/resultats_gamma_intraday.txt`. Momentum de fin de séance conditionné par le
gamma des dealers d'options (hypothèse H2 de l'arbre `arbres/market-intraday-momentum`) : Baltussen, Da, Lammers &
Martens (JFE 2021), SqueezeMetrics (2017), Dim, Eraker & Vilkov (2024), Adams, Fontaine & Ornthanalai (2024), Barbon &
Buraschi (2020), Yuan & Li (2022), Willeboordse (2026), Paz (2026), Mesfin (2026). V = signe du rendement 16h00 de la
veille → 15h30, tenu de 15h30 à 16h00 sur ES, inversé quand le gamma de la veille est positif ; référence : momentum
seulement quand le gamma est négatif (version du papier) ; témoin : sans conditionnement. Gamma : GEX quotidien public
de SqueezeMetrics (`.cache/gex/DIX.csv`, source utilisée par les auteurs après 2017).

`python -m nexus.perso.bdlm_conditionnel` → `recherche/resultats_bdlm_conditionnel.txt`. Implémentation de la spécification
`arbres/market-intraday-momentum/strategie_BDLM_conditionnelle.md` : étalonnage sur 01/2016-05/2020 (seul recouvrement
avec l'échantillon du papier), hors échantillon 06/2020-05/2022 puis ère 0DTE depuis le 11/05/2022 ; signal sur la
clôture de 15h29, entrée à l'ouverture de 15h30, sortie à 16h00 ; variantes V0 (inconditionnel), V1 (momentum si
gamma < 0), V2 (version continue réestimée en fenêtre expansive), V3 (retournement si gamma > 0) ; R² hors échantillon
avec le test de Clark-West, correction de Holm. V4 (filtre LETF) non testée faute de données.

Calendrier des annonces américaines de 08:30 ET (`nexus/perso/annonces_us.csv`, sources officielles, vérifié sur le
pic de volume de 08:30) : NFP et CPI (archives du BLS), PCE (BEA, dates ALFRED de la Fed de Saint-Louis), ventes au
détail (Census Bureau, dates ALFRED sans les révisions annuelles, calendrier officiel pour 2025-2026). Jours fériés
japonais : `nexus/perso/feries_japon.csv`.

Données payantes Databento : `python -m nexus.databento_dl cout ZT.v.0 2016-01-01 2026-08-29` affiche le coût estimé,
`telecharger ... --dossier taux --confirmer` achète et range le fichier dans `Cotations/taux/` (clé
`DATABENTO_API_KEY` dans `.env.txt`, paquet `databento`). Si `Cotations/taux/ZT_v0_1m.parquet` existe, la stratégie or
n° 4 mesure la surprise du FOMC par le rendement à 2 ans (seuil de la fiche : baisse de plus de 4 pb) au lieu du
dollar.

Alternatives aux stratégies prometteuses : `python -m nexus.perso.alternatives` → `recherche/resultats_alternatives.txt`.
Protocole écrit dans l'en-tête du module, avant les calculs : comparaison à une référence naïve (achat-conservation
ou 1/N, régression bêta / alpha), familles courtes de variantes motivées, découverte 2016-2020 et validation
2021-2026 (une variante n'est retenue que si elle bat l'originale sur les deux périodes avec un Sharpe déflaté
≥ 90 %), PBO par famille, marchés de contrôle sans ré-optimisation. Les variantes retenues sont ajoutées au runner
(lignes « (alternative) ») et passent donc dans le rapport prop et le tableau de bord.

## 17. Tests

```
python -m pytest -q
```

165 tests, sans réseau (le test de référence S1 lit `../Cotations` s'il existe). Ils couvrent :

- les contrôles numériques de `Tests/Unit/Tests.cs` ;
- le moteur : exécutions, stops, ordres limites, absence de biais d'anticipation, rejeu vectorbt à 1e-9 ;
- les roulements de futures et les séances CME ;
- les profils ;
- la couche LLM : hachage compatible C#, analyse des réponses, consignes identiques au C# ;
- les actualités : dédoublonnage, horodatage ;
- les fiches 4B, 7, 8, 9, 10, 11 et le veto Claude de la 13, avec des caches LLM et FinBERT pré-remplis ;
- le moteur intrajournalier `perso` : exécutions, stops, objectifs, limites, déclencheurs horaires,
  calendrier US (fériés, EIA, fin de mois), ATR NinjaTrader, parité de risque ;
- les stratégies minute : fiche 16 et S1 (dont le résultat de référence), Gotobi, ORB, or la nuit, fiche 15 LETF,
  groupe P1, simulation des challenges prop, catalogue SSRN et export du tableau de bord.

## 18. Architecture

```
nexus/
  mathx.py       NxMath, MCO, ADF + MacKinnon, Engle-Granger, OU, Black-Scholes
  data.py        instruments, lecture des cotations, historiques, fichiers Data/*.csv, données synthétiques
  futures.py     contrats, roulements, ajustement, barres de séance, Parquet Databento
  intraday.py    barres 1 minute : fuseau, horodatage, séance cash 9:30-16:00 en matrices, minutes synthétiques
  profiles.py    profils de paramètres par jeu de données (futures)
  engine.py      NexusStrategyBase : univers, lot synchronisé, position cible, exécutions, comptabilité
  sizing.py      module B          risk.py  disjoncteurs, coûts, stress test
  validation.py  Monte Carlo, bootstrap, Sharpe, PSR, DSR, PBO, walk-forward
  report.py      rapport texte     regime.py  module A     signals.py  moteurs de signaux partagés
  news.py        titres, dédoublonnage, Fear & Greed, horodatage des séances
  llm.py         HTTP, clés, Claude / DeepSeek / Gemini, cache, journal des coûts, consignes, FinBERT
  collect.py     collecte d'actualités, pré-notation, audit par une seconde IA
  vbt_bridge.py  rejeu vectorbt, graphique HTML, grilles vectorisées
  alpaca.py      téléchargement Alpaca (actions, ETF, crypto ; journalier et minute)
  strategies/    une classe par fiche (+ llm_base.py, socle des fiches 7 à 10)
  gotobi.py orb.py or_nuit.py letf.py   candidates minute construites dans vectorbt (§ 10 à 13)
  p1.py prop.py  groupe P1 (criblage intraday) et simulation des challenges de prop firms
  tableau.py     export du tableau de bord Node.js (statistiques vectorbt, tests, corrélations)
  perso/         stratégies NinjaScript personnelles, anomalies, moteur intrajournalier (§ 16)
outils/          recalcul indépendant de la fiche 16, catalogue SSRN
recherche/       rapports de chaque étude (resultats_*.txt, resultats_60.json, resultats_strategies.*)
tests/           pytest (sans réseau ; le test de référence S1 lit ../Cotations s'il existe)
```

Pour ajouter une stratégie : hériter de `NexusStrategy` (ou de `NewsEventStrategy` pour une fiche à
actualités), définir `NAME`, `DEFAULTS`, `on_batch(jour)` ou `on_symbol_bar` avec `BATCH_MODE = False`,
puis l'enregistrer dans `strategies/__init__.py`.
