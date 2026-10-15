# Nexus — 14 stratégies + 3 modules en NinjaScript (NinjaTrader 8)

Implémentation des 17 fiches « Fil Nexus r/algotrading » (08/10/2026). Chaque fiche a son
fichier ; les trois modules transverses (A régime, B taille, C risque/validation) sont des
bibliothèques branchées sur **toutes** les stratégies, plus deux outils exécutables.

> Spécifications de recherche, pas des conseils d'investissement. Résultats du fil auto-déclarés
> et non audités. Testez d'abord en backtest puis sur un compte simulé (Sim101).

## 1. Contenu

| Fiche | Fichier (`Strategies\`) | Nom dans NinjaTrader | Barres |
|---|---|---|---|
| 1 TSMOM | `Nexus01_TSMOM.cs` | Nexus01_TSMOM | Jour |
| 2 XSMOM | `Nexus02_XSMOM.cs` | Nexus02_XSMOM | Jour |
| 3 Multi-facteurs | `Nexus03_MultiFactorRotation.cs` | Nexus03_MultiFactorRotation | Jour |
| 4 variante A (actions) | `Nexus04A_ResidualMeanReversion.cs` | Nexus04A_ResidualMeanReversion | Jour |
| 4 variante B (crypto) | `Nexus04B_CryptoIntradayReversal.cs` | Nexus04B_CryptoIntradayReversal | 15 min + ticks |
| 5 Vol mean reversion | `Nexus05_VolatilityMeanReversion.cs` | Nexus05_VolatilityMeanReversion | Jour |
| 6 Paires | `Nexus06_PairsCointegration.cs` | Nexus06_PairsCointegration | Jour ou 1 h |
| 7 News + LLM | `Nexus07_NewsLlmEvent.cs` | Nexus07_NewsLlmEvent | Jour |
| 8 Juge LLM | `Nexus08_LlmJudgeVeto.cs` | Nexus08_LlmJudgeVeto | Jour |
| 9 Consensus 3 LLM | `Nexus09_LlmConsensus.cs` | Nexus09_LlmConsensus | Jour |
| 10 FinBERT | `Nexus10_FinBertSentiment.cs` (+ `Tools\finbert_server.py`) | Nexus10_FinBertSentiment | Jour |
| 11 Wheel options | `Nexus11_OptionsWheel.cs` | Nexus11_OptionsWheel | Jour |
| 12 Régime de vol | `Nexus12_VolRegimeConditional.cs` | Nexus12_VolRegimeConditional | Jour |
| 13 Trend prop 24/5 | `Nexus13_PropTrend8.cs` | Nexus13_PropTrend8 | Jour |
| 14 Swing strict | `Nexus14_StrictSwing.cs` | Nexus14_StrictSwing | Jour |
| A HMM 3 états | `AddOns\NexusModuleA_RegimeHmm.cs` + outil `NexusA_RegimeMonitor.cs` | NexusA_RegimeMonitor | Jour |
| B Kelly + plafonds | `AddOns\NexusModuleB_Sizing.cs` (dans toutes les stratégies) | — | — |
| C Disjoncteurs, exécution, validation | `AddOns\NexusModuleC_RiskValidation.cs` + socle + outil `NexusC_PortfolioMonitor.cs` | NexusC_PortfolioMonitor | — |

Socle commun : `AddOns\NexusCore.cs` (maths, ADF/MacKinnon, OU, Black-Scholes, CSV, JSON),
`NexusSignals.cs` (moteurs de signaux partagés), `NexusData.cs` (actualités, résultats,
fondamentaux, agenda macro, facteurs), `NexusLlm.cs` (HTTP, Claude/DeepSeek/Gemini, cache,
coûts, FinBERT, NewsAPI/Reddit, webhook), `Strategies\NexusStrategyBase.cs` (univers,
exécution, comptabilité, modules B/C) et `Strategies\NexusLlmStrategyBase.cs` (fiches 7-10).

## 2. Installation

```
powershell -ExecutionPolicy Bypass -File .\Installer.ps1
```

Le script copie le code dans `Documents\NinjaTrader 8\bin\Custom\{AddOns,Strategies}`, crée
`Documents\NinjaTrader 8\Nexus\{data,journal,reports,cache,returns,state,tools}` et y dépose les
modèles de données **sans écraser** vos fichiers. Puis : NinjaTrader → *New → NinjaScript Editor*
→ **F5**. (Installation manuelle : copier les mêmes fichiers aux mêmes endroits.)

Les fichiers compilent avec **0 erreur et 0 avertissement** contre NinjaTrader 8.1.8.3
(C# 13 / .NET 4.8, mêmes références que `NinjaTrader.Custom.csproj`). Aucun nom ne collisionne
avec vos scripts existants (préfixes `Nexus` / `Nx`). Rappel : si un autre fichier de votre
dossier Custom ne compile pas, NinjaTrader ne compile rien.

## 3. Lancer un backtest (Strategy Analyzer)

1. Instrument : n'importe lequel (ex. SPY), type **Day** (fiche 4B : Minute 15 ; fiche 6 crypto :
   Minute 60). L'univers réel est la propriété **« Symboles tradés »** ; chaque symbole est ajouté
   comme série secondaire. Un symbole absent de la base NinjaTrader est ignoré avec un message.
2. Prévoir un **historique de chauffage** : 12-1 = 1 an, HMM = 250-600 jours, régime de vol = 2 ans.
3. Les coûts sont modélisés **en interne** (module C : 0,05 % de glissement, frais crypto 0,1 %…).
   Le rapport Nexus (Output + `Nexus\reports\*.txt`) est net de ces coûts ; laissez commission et
   slippage NinjaTrader à 0 pour ne pas les compter deux fois dans le rapport NinjaTrader.
4. NinjaTrader ne gère que des **quantités entières** (pas d'actions fractionnaires comme Alpaca).
   Avec 1 000 $ et 3 %/trade, la plupart des quantités valent 0 : capital par défaut **100 000 $**.
5. Walk-forward 180/30 [Fil] : utiliser *Walk Forward Optimization* (180 jours / 30 jours). Pour le
   DSR multi-essais et le **PBO**, activer « Sauver rendements pour PBO » puis lancer une
   optimisation : chaque itération écrit ses rendements, le rapport suivant calcule PBO et DSR.

Chaque fin de run écrit un rapport : trades, IC de Wilson, Kelly, coûts, Sharpe, DD, Monte Carlo
1 000 tirages, bootstrap par blocs, Deflated Sharpe, PBO, stress test, extras de la fiche, et la
**check-list avant le réel** (1 000 trades, 30 trades + cycle DD→récupération par stratégie, frais
modélisés et PnL positif, fills réels comparés au paper).

## 4. Paramètres communs (groupes 80-82 de chaque stratégie)

- **Module B** : demi-Kelly (p et b estimés avec un a priori bayésien de 30 pseudo-trades, puis sur
  les trades de la stratégie), *Davey waiver* ×0,5 tant que < 30 trades **réels** (compteur
  persistant dans `Nexus\state`), correction de corrélation (taille / (1 + Σ corrélations > 0)),
  plafonds 3 %/trade, 10 %/symbole, 30 %/classe, 50 % total, Kelly contraint (Busseti) en option,
  borne basse de Wilson en option. En temps réel, un **registre inter-stratégies** applique « un
  titre = une seule stratégie » et les plafonds au niveau du compte.
- **Module C** : disjoncteurs (−15 % du plus haut → 12 h ; −5 % du jour → 24 h ; nouvelle référence
  après la pause), garde de cotation (35 %), chien de garde (sondage 500 ms, annulation après 5 s),
  stops natifs ou logiciels (sondage 60 s actions / 1 s crypto), retard des données (SIP : 16 min),
  interrupteur global (`Nexus\KILL_SWITCH`), avertissement PDT < 25 000 $, stress test.
- **Journal CSV** (`Nexus\journal`) : trades, fills (glissement réel vs attendu), signaux, rendements
  journaliers, coûts IA. Par défaut en temps réel seulement (pas de fichiers par itération d'optimisation).

## 5. Données externes (`Documents\NinjaTrader 8\Nexus\data`)

| Fichier | Utilisé par | Colonnes |
|---|---|---|
| `news.csv` | 7, 8, 9, 10 | `published_utc,symbol,source,headline,url` (UTC) |
| `news_live.csv` | 7-10 | rempli automatiquement en temps réel (NewsAPI/Reddit) → backtests suivants |
| `earnings.csv` | 8, 14 | `symbol,date` (ou format Alpha Vantage) |
| `fundamentals.csv` | 3, 8 | `symbol,available_date,book_equity,net_income_ttm,gross_profit_ttm,total_assets,total_liabilities,shares_outstanding` — **date de publication**, pas de fin de trimestre |
| `ff_factors.csv` | 4A mensuel | `date,mkt_rf,smb,hml,rf` (fichier Ken French) |
| `macro_events.csv` | 13 | `datetime_utc,currency,impact,title` |

Les modèles fournis ne contiennent **aucune donnée** (exemples commentés par `#`) : sans vos
données, les fiches concernées le signalent et se dégradent proprement (ex. fiche 3 en
momentum + sécurité seulement, fiche 14 ignore la condition 6 si aucun fichier).

## 6. Clés API et coûts IA

Clés : propriété de la stratégie, sinon variable d'environnement (`ANTHROPIC_API_KEY`,
`DEEPSEEK_API_KEY`, `GEMINI_API_KEY`, `NEWSAPI_KEY`, `ALPHAVANTAGE_KEY`,
`NEXUS_WEBHOOK_SECRET`), sinon `Nexus\keys.txt` (modèle `keys.txt.example`). Préférez les deux
dernières : les propriétés sont enregistrées en clair dans les workspaces.

- Modèle Claude par défaut : `claude-opus-5-5` (le plus capable) ; `claude-haiku-5-5` pour réduire
  le coût. DeepSeek : `deepseek-chat` ; Gemini : `gemini-2.5-flash` (modifiables).
- **En backtest, aucun appel API par défaut** : seules les réponses déjà en cache
  (`Nexus\cache\llm_cache.tsv`) sont utilisées. Activer « Appels API en backtest » une fois (budget
  par run : 500 appels), puis relancer gratuitement.
- Renseigner les prix ($/M tokens) pour que le rapport rapporte le coût IA au PnL ; les tokens sont
  toujours journalisés dans `Nexus\journal\ai_costs.csv`.

## 7. Notes par fiche

- **1 TSMOM** : signal 12-1 quotidien, décision à la clôture du dernier jour de bourse du mois
  (ordres à l'ouverture du 1er jour), vol cible 12 % / N, stop ATR×3 borné 2-8 % qui ne recule
  jamais, panique (SPY < niveau d'il y a 24 mois **et** vol 1 mois > médiane 1 an) → ×0,5, contrôlé
  aussi en cours de mois. « Mise à l'échelle par la vol » = faux pour tester le signal seul.
- **2 XSMOM** : quartile supérieur (6/25), tampon top 9, panier équipondéré mis à 12 % de vol, 50 % max.
- **3 Multi-facteurs** : z-scores par rang centré ; qualité = rentabilité, croissance 5 ans, sécurité
  (beta + levier) ; rendement 12 mois tiers haut − tiers bas recalculé chaque jour → poids ×1,5 / ×0,5.
- **4A** : s-score OU Avellaneda-Lee (moyennes centrées), demi-vie < 15 j ; mode mensuel décile
  (3 facteurs ou modèle de marché).
- **4B** : flux taker par règle du tick sur une série 1-tick par symbole ; **mode FiltreSeulement par
  défaut** (règle de survie) : publie les chocs que les autres stratégies peuvent respecter
  (option « Filtre de choc taker » : entrée différée puis limite au milieu de la barre de choc).
  Noms crypto à adapter à votre connexion (ex. Coinbase).
- **5** : w = c/variance, c **glissant** (le c de Moreira-Muir sur tout l'échantillon utiliserait le
  futur), w = 1 ↔ « Allocation max par actif » (10 %). Mode par symbole : SPY/QQQ et BTC/ETH gardent
  leur propre calendrier.
- **6** : valeurs critiques **Engle-Granger N=2** (l'ADF classique est trop permissif sur un résidu
  estimé). Long seul par défaut (petit compte) ; « Vente à découvert autorisée » = vrai pour la version
  neutre au marché. Une jambe ne peut appartenir qu'à une paire.
- **7 / 9 / 10** : fenêtre d'actualités ]ouverture précédente − marge ; ouverture suivante − marge]
  (marge = 5 min + retard des données), moyenne du jour, ≥ +0,5 sur 2 titres → long 1 jour,
  ≤ −0,5 → sortie / entrée interdite. Fiche 9 : désaccord = pas de trade ce jour + mesure de la
  volatilité du lendemain. Fiche 10 : lancer `python Tools\finbert_server.py`
  (`pip install torch transformers`) ; le rapport compare son journal à celui de la fiche 7.
- **8** : candidats des moteurs exacts des fiches 1-3 ; veto si confiance ≥ 0,7 (bloquer ou /2) ;
  classement optionnel (retrait du quart le plus risqué) ; **trades fantômes** bloqués vs acceptés
  suivis avec les mêmes règles et test de Welch après 30 vetos ; alerte si veto > 25 %.
- **11 Wheel** : NinjaScript n'offre pas de chaîne d'options → **backtest synthétique Black-Scholes**
  (IV = vol réalisée × 1,28, ou VIX), spread modélisé, filtre de spread à 3 niveaux, garde-fou « pas de
  call sur des actions avec un ordre de vente en attente », pire perte mensuelle et décomposition
  Israelov-Nielsen dans le rapport. Mode **SignalSeul** (tickets en temps réel) ; mode
  **CompteNT_Experimental** (ordres d'options via l'API Account, nom d'instrument paramétrable) à
  valider sur compte simulé. L'assignation anticipée n'est pas modélisée.
- **12** : terciles 2 ans, anti-clignotement 5 j (ou HMM du module A) ; grille {3, 6, 12 mois} ×
  {z 1,5 ; 2 ; 2,5} recalibrée tous les 30 j sur 180 j, **uniquement sur les jours du régime**
  (< 30 jours → paramètres par défaut) ; trades par régime dans le rapport. Une instance par classe
  (Baromètre SPY ou BTCUSD).
- **13** : noms CFD dépendants du fournisseur ; alternatives futures (micro) possibles en adaptant
  « Symboles » et « Tailles de lot ». Règles prop **à vérifier chez la firme**. Veto « Règles » par
  défaut (aucun appel API) ; « ReglesPuisClaude » n'appelle Claude que s'il y a un événement.
  Webhook signé `X-Nexus-Secret`, comptes miroirs par l'API Account, interrupteur global.
- **14** : les 6 conditions avec un compteur de rejets par condition ; repli brut ou résiduel
  (« tester les deux ») ; alerte au-delà de 2 trades/semaine.
- **NexusA_RegimeMonitor** : à appliquer sur un graphique journalier de SPY ; trace P(calme/neutre/
  stress) et le régime des terciles ; probabilités **filtrées** (aucune information future), EMA 5 j,
  plafond 0,95, réestimation hebdomadaire, 10 initialisations.
- **NexusC_PortfolioMonitor** : rapport consolidé (corrélation hebdomadaire des stratégies, check-list
  avant le réel, PBO/DSR, coût IA vs PnL) ; permet d'activer/désactiver l'interrupteur global.

## 8. Passage au temps réel

- *Start behavior* = **Wait until flat** par défaut (sûr : les positions historiques virtuelles ne
  sont pas supposées exister sur le compte).
- En barres journalières, NinjaTrader clôt la barre du jour J au premier tick de J+1 : les ordres
  partent donc à l'ouverture, comme en backtest.
- Activer le journal (« TempsReelSeulement » par défaut), lancer `NexusC_PortfolioMonitor`, commencer
  sur Sim101 puis sur un petit montant (objectif : réalité de l'exécution, pas le profit).

## 9. Choix d'interprétation (signalés aussi dans les en-têtes)

- Kelly lu comme **fraction du bankroll en notionnel** (lecture du fil) ; option « fraction risquée ».
- Avec les plafonds du fil (3 %/trade), la taille vol-cible des fiches 1-2 est souvent plafonnée :
  c'est la conséquence des règles du fil, modifiables par stratégie.
- Après une pause de disjoncteur, la référence de drawdown est remise à l'equity courante (sinon
  blocage permanent).
- Fiche 11 « à 21 jours » : par défaut, clôturer si hors de la monnaie, sinon laisser l'assignation
  (pour que la roue tourne) ; « Clôturer » et « Rouler » disponibles.
- Fiche 8 « retirer le dernier quart » : interprété comme le quart **le plus risqué**.

## 10. Ce qui a été vérifié

- Compilation complète contre les DLL NinjaTrader installées : 0 erreur, 0 avertissement.
- 76 tests numériques du socle, tous réussis : loi normale, p-values MacKinnon vs valeurs critiques
  publiées (ADF 1/5/10 %, Engle-Granger N=2), taille/puissance de l'ADF et d'Engle-Granger sur
  simulations, OU (demi-vie, σ_eq), Black-Scholes (parité, strike par delta, vol implicite), Kelly
  (IC de Wilson [42,7 % ; 51,7 %] de la fiche B, seuil b = 1,12, Kelly contraint), HMM (99,8 % des
  états retrouvés en filtrage avant), terciles anti-clignotement, PBO non biaisé (0,50 sur bruit,
  0 avec une vraie compétence), DSR, Monte Carlo, disjoncteurs, JSON, analyse des réponses LLM,
  dates/CSV, dédoublonnage des actualités, panel aligné.
- Contrôle des strikes de la fiche 11 sur 108 cas (spot × vol × échéance × put/call) : strike dans la
  bande |Δ| 0,20-0,30, ou abstention quand la grille de strikes n'offre aucun strike dans la bande.
- Rejouer ces contrôles (SDK .NET requis) : dossier `Tests\CompileCheck`, commande
  `dotnet build -c Release` (→ 0 erreur) ; dossier `Tests\Unit`, commande `dotnet run -c Release`
  (→ « 76 OK, 0 ECHEC(S) »).
- **Non vérifié ici** : l'exécution dans le moteur NinjaTrader (aucun backtest lancé depuis cette
  machine) et les appels réels aux API (aucune clé utilisée). Premier pas recommandé : un backtest de
  `Nexus01_TSMOM` sur SPY journalier, puis Sim101.

## 11. Version Python (vectorbt)

Le dossier `Python/` contient un moteur de backtest Python qui reproduit les fiches 1, 2, 3, 4A, 5, 6,
12, 13 et 14 avec les modules A, B et C, pour tester sans NinjaTrader :

```
cd Python
pip install -r requirements.txt
python -m nexus verifier --donnees "C:\Users\Mathis\Desktop\Cotations"
python -m nexus backtest -s 01 --donnees "C:\Users\Mathis\Desktop\Cotations" --html
```

Détails, formats de cotations acceptés et constats sur le code NinjaScript : `Python/LISEZMOI.md`.

La fiche 16 (Noise Area Intraday Momentum, barres 1 minute, SPY puis ES/NQ) n'existe qu'en Python :
`python -m nexus backtest -s 16 -d DOSSIER_MINUTE -p symbols=ES --html` (voir `Python/LISEZMOI.md` § 8).

**S1_NoiseAreaNQ** est la version validée (le 2026-10-15) et figée de la fiche 16 sur NQ : sigma 30 séances,
contrôle 30 min, bande × 1,2. Fichier autonome `Python/S1_NoiseAreaNQ.py`, ou `python -m nexus backtest -s S1`
dans le moteur. Résultat de référence, tests passés et réserves : `Python/LISEZMOI.md` § 9.
