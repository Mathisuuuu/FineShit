# Nexus — 15 stratégies + 3 modules en NinjaScript (NinjaTrader 8)

> **Version de travail : Python / vectorbt (dossier `Python/`) et tableau de bord Node.js
> (dossier `Dashboard/`).** Démarrage rapide : section 11. Le code NinjaScript ci-dessous reste la référence.

| Dossier | Contenu |
|---|---|
| `AddOns/`, `Strategies/`, `Tools/`, `Installer.ps1` | stratégies NinjaScript (fiches 1 à 15) et modules A, B, C |
| `Tests/` | bancs d'essai C# (compilation, tests unitaires, simulateur Linux de la fiche 15) |
| `Data/` | modèles des fichiers externes (actualités, résultats, facteurs, agenda, encours LETF, GEX) |
| `Python/` | moteur vectorbt (`nexus/`), stratégies minute, recherche locale (`nexus/perso/`), tests (`tests/`) |
| `Python/recherche/` | rapports de toutes les études (`resultats_*.txt`, `resultats_60.json`) |
| `Dashboard/` | tableau de bord Node.js : serveur, interface, résultats exportés (`donnees/`, hors dépôt) |
| `Cotations/` | barres 1 minute Databento (dépôt séparé, licence, hors dépôt) |

Implémentation des 17 fiches « Fil Nexus r/algotrading » (08/10/2026). Chaque fiche a son
fichier ; les trois modules transverses (A régime, B taille, C risque/validation) sont des
bibliothèques branchées sur **toutes** les stratégies, plus deux outils exécutables. La fiche 15
(rebalancement des ETF à levier, NQ/ES en fin de séance, 13/10/2026) a été ajoutée le 14/10/2026.

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
| 15 LETF rebalancing NQ/ES | `Nexus15_LetfRebalancing.cs` (+ `AddOns\NexusLetf.cs`) | Nexus15_LetfRebalancing | 1 min |
| A HMM 3 états | `AddOns\NexusModuleA_RegimeHmm.cs` + outil `NexusA_RegimeMonitor.cs` | NexusA_RegimeMonitor | Jour |
| B Kelly + plafonds | `AddOns\NexusModuleB_Sizing.cs` (dans toutes les stratégies) | — | — |
| Groupe en direct (S1 + Gotobi, logique en Python) | `AddOns\NexusPasserelle.cs` (passerelle TCP locale) + `Python/nexus/live` | AddOn NexusPasserelle (démarre avec NinjaTrader) ; fenêtre *New → Groupe* | 1 min |
| C Disjoncteurs, exécution, validation | `AddOns\NexusModuleC_RiskValidation.cs` + socle + outil `NexusC_PortfolioMonitor.cs` | NexusC_PortfolioMonitor | — |

Socle commun : `AddOns\NexusCore.cs` (maths, ADF/MacKinnon, OU, Black-Scholes, CSV, JSON),
`NexusSignals.cs` (moteurs de signaux partagés), `NexusData.cs` (actualités, résultats,
fondamentaux, agenda macro, facteurs), `NexusLlm.cs` (HTTP, Claude/DeepSeek/Gemini, cache,
coûts, FinBERT, NewsAPI/Reddit, webhook), `NexusLetf.cs` (fiche 15 : flux LETF, GEX, calendrier,
Newey-West, protocole de backtest), `Strategies\NexusStrategyBase.cs` (univers, exécution,
comptabilité, modules B/C) et `Strategies\NexusLlmStrategyBase.cs` (fiches 7-10).

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
| `macro_events.csv` | 13, 15 | `datetime_utc,currency,impact,title` |
| `letf_aum.csv` | 15 | `date,fund,shares_outstanding,nav[,aum][,net_flow_usd]` — parts × NAV **de la veille** |
| `gex.csv` | 15 | `date[,underlying],gex[,gex_ref]` — $ par 1 %, date = séance d'application |
| `letf_excluded_days.csv` | 15 | `date,reason` (FOMC, CPI, NFP, NDX rebalance, autre) |

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
- **15 LETF rebalancing** : instrument du Strategy Analyzer **NQ 12-26, Minute 1** (série principale
  ignorée ; NQ, ES, `^NDX` et `^SP500` sont ajoutés en 1 min). Futures en modèle d'horaires
  « CME US Index Futures RTH » par défaut (3 fois moins de barres en mémoire sur 2012-2026 ; vide =
  modèle de l'instrument) ; indices `^NDX` / `^SP500` (r_t sans le basis) — absents, le future est
  utilisé avec un avertissement. Toutes les heures sont en **heure de New York** quel que soit le
  fuseau de NinjaTrader (21:30 Paris = 15:30 ET, 20:30 pendant les semaines de décalage d'heure d'été).
  Signal 15:25 (index à 15:25 vs clôture J-1 ; actif net de la veille ; V = volume moyen 15:30-16:00
  des 20 dernières séances complètes), décision et entrée sur la barre de 15:30 (ordre au marché en
  backtest ; en réel limite au mid si le spread dépasse 1 tick, valable 5 min), stop natif 1,5 × ATR(14)
  de barres 30 min RTH, sortie au marché à 16:00 (ou TWAP 15:55-16:00 en 5 tranches), garde « jamais
  d'overnight ». Coûts du module C remplacés par la fiche : 1 tick aller-retour + 2,50 $/contrat/côté
  (stress 2 ticks dans le rapport) ; capital par défaut 500 000 $. Le rapport de fin de run contient
  le protocole complet (régression Newey-West, 5 tests d'identification, IS 2012-2020 / OOS 2021+,
  walk-forward 3 ans de w, critères d'acceptation, β2 annuel, concentration TQQQ, GEX vs source tierce)
  et écrit le panel quotidien `Nexus\reports\*_panel_*.csv`. Sans `gex.csv` le régime est inconnu
  (w = 1 par défaut = version « sans filtre gamma ») ; sans jours FOMC/CPI/NFP fournis, l'exclusion
  macro est inactive (message au démarrage). Optimisables : w long gamma, quantile du seuil, filtre de
  rendement, cible de risque, multiplicateur ATR, sortie, formule du flux, règle d'instrument.
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

- **Groupe en direct** (S1 + Gotobi) : l'AddOn `NexusPasserelle` diffuse les barres 1 minute au moteur Python
  (`python -m nexus.live`) et exécute ses positions cibles sur **Sim101** par défaut, avec ses propres garde-fous
  (compte réel refusé sauf autorisation, plafond de contrats, coupure 16:10 ET, perte du jour, battement de cœur,
  interrupteur global). Fenêtre **Groupe** (Control Center → *New* → Groupe) : état, stratégies avec Activer /
  Désactiver, positions, journal, bouton « Tout arrêter ». Ajouter une stratégie = un fichier Python + une ligne
  dans `Python/nexus/live/groupe.json`, sans redémarrer NinjaTrader. Détails : `Python/LISEZMOI.md`, § 17.

## 9. Choix d'interprétation (signalés aussi dans les en-têtes)

- Kelly lu comme **fraction du bankroll en notionnel** (lecture du fil) ; option « fraction risquée ».
- Avec les plafonds du fil (3 %/trade), la taille vol-cible des fiches 1-2 est souvent plafonnée :
  c'est la conséquence des règles du fil, modifiables par stratégie.
- Après une pause de disjoncteur, la référence de drawdown est remise à l'equity courante (sinon
  blocage permanent).
- Fiche 11 « à 21 jours » : par défaut, clôturer si hors de la monnaie, sinon laisser l'assignation
  (pour que la roue tourne) ; « Clôturer » et « Rouler » disponibles.
- Fiche 8 « retirer le dernier quart » : interprété comme le quart **le plus risqué**.
- Fiche 15, formule du flux : la fiche écrit F = A·L(L−1)·r/(1+L·r) avec A = actif net **de la veille** ;
  or avec la NAV de la veille le flux exact est A·L(L−1)·r (Cheng-Madhavan 2009) — la forme avec
  1/(1+L·r) est exacte avec la NAV de **fin** de journée (vérifié par simulation dans les tests). La
  formule de la fiche est gardée par défaut ; « Formule du flux = NavVeilleExacte » donne l'autre
  (écart de 3 % à |r| = 1 %, 10 % à |r| = 3 %).
- Fiche 15, taille : contrats = capital × cible de risque / (prix × $/point × vol réalisée 30 min
  annualisée × √(30/98 280)) × |Score|/seuil, plafonnés à 2 % de V (1 % si |r| > 3 %). La fiche ne
  borne pas |Score|/seuil : un jour extrême peut demander un levier élevé ; « Taille : levier max »
  (hors fiche, 0 = désactivé) le borne.
- Fiche 15, « NQ en priorité ; ES seulement si le score ES passe aussi le seuil » + « une position
  par jour » : NQ si son score passe ; sinon ES si **son** score passe son propre seuil (règles
  « les deux » et « NQ seul » disponibles). Créations/rachats nets du jour : ajoutés au flux sous la
  forme L × C (des rachats, C < 0, réduisent le flux d'un fonds haussier) ; à défaut, tendance des
  parts sur 5 jours en variable de contrôle. Seuil q70 calculé sur les 250 séances précédentes (jour
  courant exclu), jours exclus compris. GEX à 0 traité comme long gamma.

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
  (→ « 120 OK, 0 ECHEC(S) » depuis l'ajout de la fiche 15).
- **Fiche 15 (14/10/2026), vérifiée hors NinjaTrader** (Linux, SDK .NET 8, dossier `Tests\Linux`) :
  - `Unit` : les mêmes tests que `Tests\Unit` (NinjaTrader.Core remplacé par un stub), dont 44 de la
    fiche 15 → « 120 OK, 0 ECHEC(S) » : exemple chiffré de la fiche (+1 % → ~2,5 Md$ ≈ 5 000 NQ),
    exactitude du flux (simulation d'un rebalancement 3x), A_i = parts × NAV de la veille, GEX et poids w,
    jours fériés, demi-séances et quatre sorcières NYSE (dont le 18/06/2026, Juneteenth tombant le
    3e vendredi), classement des libellés macro (minutes du FOMC et ADP non exclus), barres 1 et 30 min,
    q70 glissant, taille et plafonds, Newey-West (= MCO en iid, plus large en autocorrélé).
  - `Net48` : socle + fiche 15 compilés contre les assemblys de référence .NET Framework 4.8 en C# 7.3
    → 0 erreur, 0 avertissement.
  - `Sim` : la **vraie** classe `Nexus15LetfRebalancing` (et `NexusStrategyBase`) exécutée par un
    émulateur minimal de l'API NinjaScript (barres horodatées à la clôture, ordres au marché à
    l'ouverture de la barre suivante, stops/limites intrabar, callbacks d'ordres synchrones) sur des
    marchés synthétiques 1 min. (1) 40 scénarios déterministes : signal, seuil q70, taille et stop
    recalculés indépendamment ; entrée 15:30 / sortie 16:00 ET ; vente les jours de baisse ; filtre
    |r| ; FOMC, CPI, NFP, rebalancement NDX, quatre sorcières, demi-séance ; stop sans réentrée ; ES en
    secours ; une position par jour ; mêmes trades avec NinjaTrader réglé sur Paris (y compris pendant
    le décalage d'heure d'été : entrée à 20:30 Paris) ; sortie TWAP. (2) Quatre backtests 2011-2026 :
    effet LETF réaliste planté → H1 et les 5 tests d'identification passent, mais NO-GO sur la stabilité
    de β2 (critère exigeant de la fiche) ; effet fort → GO ; momentum intraday générique seul (pourtant
    rentable, Sharpe ≈ 2,3) → identifié comme non-LETF, NO-GO ; bruit → NO-GO. Invariants partout : jamais
    d'overnight, une position par jour, aucun trade un jour exclu. (3) Taille des tests sous H0 (20
    marchés de bruit) : ≈ 5 % de rejets, écart-type des t ≈ 1.
  - Commandes : `Tests\Linux\Unit` → `dotnet run -c Release` ; `Tests\Linux\Net48` →
    `dotnet build -c Release` ; `Tests\Linux\Sim` → `dotnet run -c Release` (tout, ~5 min), ou avec
    l'argument `regles`, `stats` ou `taille`.
  - Limites : la fiche 15 n'a **pas** été compilée contre les DLL NinjaTrader réelles (machine Linux) :
    relancer `Tests\CompileCheck` sous Windows ; l'émulateur n'est pas NinjaTrader (ordre exact des
    événements, remplissages partiels, sessions ETH) ; les marchés sont synthétiques. **Aucune donnée réelle** (parts des LETF, GEX, NQ/ES
    1 min 2012-2026) n'était accessible depuis la machine de test : la validation de l'hypothèse elle-même
    reste à faire sur vos données, dans le Strategy Analyzer.
- **Non vérifié ici** : l'exécution dans le moteur NinjaTrader (aucun backtest lancé depuis cette
  machine) et les appels réels aux API (aucune clé utilisée). Premier pas recommandé : un backtest de
  `Nexus01_TSMOM` sur SPY journalier, puis Sim101 ; pour la fiche 15, NQ 12-26 en 1 min avec
  `letf_aum.csv`, `gex.csv` et les jours exclus remplis.

## 11. Version Python (vectorbt) et tableau de bord

Le dossier `Python/` contient le moteur de backtest Python. Il porte les fiches 1 à 14 et les modules
A, B et C, ajoute les futures Databento du dossier `Cotations` (roulements détectés et ajustés, profil
`futures`), la couche LLM avec un cache compatible avec ce C#, la collecte d'actualités et l'audit d'un
rapport par une seconde IA. Les stratégies minute (fiche 15 LETF, fiche 16 Noise Area, S1, Gotobi, ORB,
or la nuit) n'existent qu'en Python ou y sont recalculées avec vectorbt.

```
cd Python
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
.venv\Scripts\python -m nexus tableau          # calcule toutes les strategies du tableau de bord (environ 25 min)
cd ..\Dashboard
node serveur.js                                    # puis http://localhost:3000
```

Le tableau de bord (`Dashboard/`, Node.js sans dépendance) montre **toutes les stratégies** dans une seule liste : la
validée **S1 Noise Area NQ**, les candidates des sessions cloud (**Gotobi 6J**, **ORB 5 min NQ**, **or la nuit (GC)**,
**fiche 15 LETF NQ / ES**) et toutes celles testées en local par le runner (`nexus/perso`), passées par les mêmes objets
vectorbt et les mêmes tests (statistiques vectorbt, trades, Monte Carlo, bootstrap, Sharpe déflaté du programme
entier, stabilité). Pages communes : Comparaison (corrélations, portefeuille combiné), **Prop firm** (combinaison la
plus fiable de futures intraday d'après les statistiques vectorbt, validée hors échantillon, règles du compte
modifiables) et Études sur papiers.

Détails : `Python/LISEZMOI.md` (moteur, fiches, résultats) et `Dashboard/LISEZMOI.md` (tableau de bord).
Le dossier `Cotations` (licence Databento, redistribution interdite) est exclu du dépôt par `.gitignore`.

