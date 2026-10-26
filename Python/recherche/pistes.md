# Pistes de recherche (papiers après 2020) — 19/10/2026

Proposées **avant tout test**. Choisir avant de lancer quoi que ce soit (méthode : `memory/methode-strategie-papiers`).

## Ce qui oriente le choix

- **Groupe P1 (cloud, 124 essais)** : avec des signaux de **prix intraday** sur nos 9 contrats, aucune hypothèse n'a
  atteint un Sharpe de 1, ni avant ni après publication. Les études récentes vont dans le même sens : Mesfin 2026
  (SSRN 6709401, 14 familles de signaux sur MNQ, aucune ne survit à 2 points de coût), Seeck 2026 (SSRN 7008318,
  momentum intraday des devises réel mais mangé par les coûts).
- Les pistes ci-dessous s'appuient donc sur une **cause extérieure au prix**, observable (un autre marché, un flux,
  un calendrier), ou sur un **vrai hors-échantillon**.
- Recherche faite :
  - catalogue SSRN (`outils/ssrn_intraday.py`) : 5 185 articles au moins intraday ; il en reste 79 publiés depuis
    2021, sur nos actifs, avec une règle ou une prédictibilité, et pas encore testés ;
  - 18 requêtes OpenAlex sur nos marchés (343 articles depuis 2021) ;
  - recherches ciblées : flux, calendriers, options, crypto, liquidité.

## Classement proposé

| # | Piste | Papiers | Données | Aveugle ? | Intraday | A priori |
|---|---|---|---|---|---|---|
| 1 | **TESTÉE le 19/10/2026 : rejetée** (`resultats_weekend_crypto.txt`) — Week-end crypto → lundi ES / NQ | Mourey, Shahrour & Şoiman, *FRL* 2025 ; Li & Yuan 2026 (SSRN 7543402) | BTC / ETH 15 min (Alpaca, depuis 01/2021) + ES / NQ minute : **prêt** | oui | oui (lundi 9:30-16:00) | faible à moyen |
| 2 | **TESTÉE le 19/10/2026 : rejetée** (`resultats_dax_cloture.txt`) — Retournement du DAX 17:00-17:30, vrai hors-échantillon 2014-2025 | observation locale S19-B inversée (Sharpe 2,2 sur 03/2025-08/2026) ; enchères de clôture (Bogousslavsky & Muravyev, *JFM* 2023) | Dukascopy DAX gratuit : 2014 → 03/2018 en cache, **reste à télécharger** 2018-2025 | oui sur 2014-2025 | oui | moyen |
| 3 | Sentiment des ETF sectoriels de nuit → futures d'indices | Lee, Liao & Lee, *J. Futures Markets* 2022 ; Aboody et al., *JFQA* 2018 | ETF XL* journaliers (Alpaca, 2016-2026) : **prêt** | oui | non (jour suivant) | faible à moyen ; texte complet payant |
| 4 | Suivi hors-échantillon des candidates (S1, ORB, Gotobi, or la nuit) | Chuk 2026 (SSRN 7609644) ; Demirev 2025 (SSRN 5325376) ; Wei 2026 (SSRN 7257240) | Yahoo 5 min sur 60 jours (NQ=F, GC=F, 6J=F) : gratuit | — (pas un nouvel essai) | oui | — |
| 5 | Couverture de fin de séance des ETP VIX → ES 15:30-16:00 | Bangsgaard & Kokholm 2023 (SSRN 4470636) | encours des ETP VIX introuvable gratuitement ; un substitut referait l'échec LETF | oui | oui | faible |
| 6 | Retour à la valeur après une enchère hebdomadaire ratée (ES, NQ, GC) | Perry 2026 (SSRN 6728359, pré-enregistré) | ES / NQ / GC minute : prêt | oui | oui | faible (p 0,014 sur ES, 0,09 sur les autres) |
| 7 | Nouveaux contrats (10 ans ZN, Russell RTY, argent, cuivre, gaz, grains) | Pan & Peng 2026 (pré-FOMC obligations) ; Fleming, Liu & Nguyen 2026 (NY Fed SR 1188, adjudications) | Databento **payant** ; clé `DATABENTO_API_KEY` absente de `.env.txt` | oui | oui | dépend du contrat |

### 1. Week-end crypto → lundi

- **Ce que dit le papier.** Des rendements négatifs des cryptomonnaies le week-end prédisent une baisse des
  actions le lundi. L'effet est asymétrique (rien quand le week-end est positif) et il s'est renforcé après
  l'effondrement de LUNA (mai 2022).
- **Mécanisme.** Pendant le week-end, la crypto est le seul grand marché ouvert. Li & Yuan 2026 montrent qu'un
  prix formé quand la référence est fermée est repris à 70-90 % à la réouverture.
- **Le piège.** ES rouvre le dimanche à 18:00 ET, donc l'information du week-end est déjà dans le prix
  d'ouverture. La question tradable est de savoir s'il reste quelque chose après :
  - de dimanche 18:00 à lundi 16:00 ;
  - et surtout de lundi 9:30 à 16:00, ce qui reste intraday et compatible avec une prop firm.
- **Données.** Environ 300 lundis depuis 2021, dont environ 45 % après un week-end négatif.
- **Contre-papiers à lire.**
  - Ali, Du & Majeed (*FRL* 2025) : la façon de calculer le rendement du lundi change les conclusions.
  - Kaiko (cité par InvestingLive) : volume crypto faible et écarts élargis le week-end, donc du bruit.

### 2. DAX 17:00-17:30, hors-échantillon long

- **D'où vient la piste.** S19-B (achat ou vente dans le sens du jour avant la clôture de Xetra) perdait 152 000 $ sur
  03/2025-08/2026. Jouée à l'envers, elle donnait un Sharpe de 2,2. C'est une observation faite après coup, sur
  1,5 an : elle n'est **pas vérifiable** en l'état.
- **Le test.** Préenregistrer la règle inversée telle quelle et la juger sur 2014-2025, une période qu'on n'a
  jamais regardée.
- **Lectures avant le test.**
  - enchère de clôture de Xetra (17:30-17:35) ;
  - Bogousslavsky & Muravyev 2023 : les distorsions du prix de clôture se retournent ;
  - Barbon et al. (LETF) prédisent au contraire un prolongement.
- **Coût.** Téléchargement Dukascopy gratuit mais long (`nexus/dukascopy.py`).
- **Résultat (19/10/2026) : rejetée.**
  - Données : Dukascopy bloquait les téléchargements ; le même flux CFD a été pris chez HistData (`nexus/histdata.py`).
  - Sur 2014-2025, 2 707 trades : −4,0 pb net par trade (t −4,9), négatif sur les deux moitiés.
  - La demi-heure 17:00-17:30 prolonge le mouvement du jour (pente +0,020, t 2,7), comme le prévoient Li, Sakkas &
    Urquhart 2022 : c'est un momentum, pas un retournement. Il est trop faible pour payer les coûts.
  - Sur 03/2025-08/2026, le même calcul sur le CFD ne fait qu'un Sharpe de 0,30, contre 2,2 sur FDAX : l'observation
    d'origine venait en partie des futures et du hasard d'un an et demi.

### 3. ETF sectoriels de nuit

- Le co-mouvement des rendements de nuit (clôture → ouverture) des ETF sectoriels mesure le sentiment. Selon
  Lee et al. 2022, il prédit les futures d'indices hors échantillon.
- Nos 11 ETF XL* journaliers suffisent.
- L'article est en accès payant : il faut trouver une version de travail pour reprendre la définition exacte.

### 4. Suivi des candidates

Ce n'est pas un nouvel essai. Les Cotations s'arrêtent le 28/08/2026 ; Yahoo fournit 60 jours de barres 5 min
gratuites, de quoi suivre S1 (NQ), ORB (NQ), Gotobi (6J) et or la nuit (GC) depuis fin août. L'échantillon est
court, à lire comme un paper trading.

Lectures externes sur les candidates :
- **Chuk 2026** : la zone de bruit sur NQ, exécutable, fait un Sharpe de 1,14 sur 2020-07/2026, positive 7 années
  sur 7. C'est l'une des 2 survivantes sur 144 tests pré-enregistrés : un appui indépendant pour S1.
- **ORB** :
  - Demirev 2025 réplique l'ORB sur QQQ ;
  - Mesfin 2026 le voit échouer sur MNQ avec 2 points de coût.
- **Or la nuit** : Wei 2026 trouve que l'or monte surtout pendant la séance asiatique (2024-2026).

### 5. La nuit (22:00-9:30 New York) : nouveaux contrats, en attente de l'accord pour les données

Lot « créneaux vides » (nuit du 19 au 20/10/2026, `nexus/perso/creneaux.py`, H1-H10) : avec nos 9 contrats, plus rien
de documenté à tester la nuit (plus de 260 essais au total) ; chaque essai faible baisse le Sharpe déflaté de toutes
les stratégies. « Or la nuit » conforme (H10) n'est fiable qu'avec GC, trop gros pour un compte prop firm. Il faut des
contrats qui se tradent la nuit en micro.

- **Micro Bitcoin / Micro Ether (MBT, MET, CME ; 0,1 BTC / 0,1 ETH ; autorisés chez Topstep).** Séance CME 18:00-17:00
  comme les autres. Source : Zarattini, Pagani & Barbon 2025, *Catching Crypto Trends* (ensemble de canaux de
  Donchian, taille à la volatilité ; Sharpe > 1,5 net). Test prévu : la même règle que H5 (Donchian 15 min rendu
  conforme, vendu à 16:59, racheté à 18:00) et la règle du papier rendue conforme. **Données manquantes** : nos
  barres crypto Alpaca commencent en 2021, la moitié 2016-2020 du filtre « fiable » est vide. Source gratuite
  proposée : Binance (data.binance.vision, BTCUSDT et ETHUSDT en barres 1 minute depuis 08/2017, fichiers zip mensuels
  d'environ 1 à 3 Mo, environ 250 Mo en tout), proxy du future CME (base faible en intraday).
- **Nikkei (NKD, CME).** Li, Sakkas & Urquhart 2022 (*JFM*) : momentum intraday de série temporelle au Japon,
  t = 4,07 ; la séance de Tokyo (19:00-1:30 New York) est le cœur de la nuit. Réplique de S1 et de l'ORB à
  l'ouverture de Tokyo. Données : HistData JPXJPY (CFD Nikkei, minutes, zips annuels de 3 à 5 Mo, même source que le
  DAX). Réserve : un NKD vaut environ 240 000 $ de notionnel, trop gros pour un compte de 50 000 $.
- **Argent (SIL micro, 1 000 onces).** Wei 2026 (momentum de séance sur l'or ET l'argent) ; H1 a rejeté l'or seul.
  Données : HistData XAGUSD.

### 6. Saisonnalité intraday du Brent (à revoir quand le texte sera libre)

- Ewald, Haugom, Ouyang, Smith-Meyer & Størdal 2025, *Quantitative Finance* (SSRN 5037563) : creux et pics de prix à
  heures fixes sur le Brent (ICE, 2010-2021), stratégies long-short à alpha positif après coûts. Les heures exactes sont
  dans le texte payant (manuscrit de Glasgow sous embargo jusqu'en 2027) : les choisir nous-mêmes sur CL serait de la
  fouille de données. À tester sur CL dès que la règle publiée est lisible.

## Lot du 2026-10-21 (après le calcul de puissance obligatoire)

### C1. Retournement de l'enchère de clôture, ES / NQ, 16:00 → 16:10 New York — ABANDONNÉE à la lecture (aucun essai)

Verdict du 2026-10-21 après lecture complète de Bogousslavsky-Muravyev (version de juin 2021, publiée JFM 2023) et de
Bender-Clapham-Schwemmlein (EFMA 2023) : le calcul de puissance ci-dessous reposait sur une hypothèse fausse.
- L'écart de l'enchère est mesuré sur le PRIX D'ENCHÈRE de chaque action (8,1 pb en moyenne, surtout le
  demi-écart), mais agrégé sur l'indice il ne vaut que 0,93 pb (3,6 pb pour SPY / QQQ) : « trop petit pour un
  portefeuille diversifié ». Les futures ES / NQ ne passent pas par l'enchère : ils suivent le prix médian continu,
  pas le prix d'enchère ; la distorsion ne leur est pas transmise.
- Le mouvement de 15:55-16:00 est « surtout efficient » : 19 % seulement s'inverse, et d'ici le lendemain matin.
- Le papier EFMA porte sur des actions européennes (23 % du rendement d'enchère inversé la nuit), pas sur un indice.
- Puissance refaite avec les chiffres des papiers : effet brut ≤ 0,5-1,8 pb par jour contre 1,1 pb de coûts ;
  t attendu < 1 sur les jours lourds. Sous le seuil de 3 : pas de test, pas d'essai compté (règle du 2026-10-21).
Leçon : faire le calcul de puissance avec l'effet MESURÉ par le papier sur le même objet (ici l'indice), jamais
avec une approximation tirée de nos données.

Texte d'origine de la piste (conservé) :
- Cause : l'enchère de clôture du NYSE concentre une part croissante du volume (fonds indiciels, rééquilibrages,
  échéances, fins de mois) ; le prix de clôture est poussé puis se corrige (Bogousslavsky-Muravyev, *Journal of
  Financial Markets* 2023 : écart de clôture inversé de moitié peu après la clôture, en entier la nuit ; volume
  d'enchère maximal les jours de rééquilibrage d'indice, d'échéance d'options et de fin de mois ; EFMA 2023 sur
  l'Europe : 23 % du rendement de l'enchère inversé la nuit). Les futures ES / NQ cotent après 16:00 : on peut
  prendre le retournement dans les 10 minutes, avant la limite de 16:10 des prop firms.
- Jamais testé chez nous (BM23 n'a servi qu'à la clôture du DAX, `dax_cloture.py`).
- Calcul de puissance (`t_attendu`, seulement |mouvement| et écart-type, jamais leur lien), hypothèse prudente : la
  moitié du mouvement de la DERNIÈRE minute (15:59-16:00) s'inverse de 16:00 à 16:10, coûts 1,1 pb aller-retour :
  ES jours lourds (fins de mois, quatre sorcières, Russell ; 175 jours) t ≈ 3,3 ; ES tous les jours (2 658) t ≈ 5,3 ;
  NQ jours lourds t ≈ 2,7 ; NQ tous les jours t ≈ 4,5. Passe le seuil de 3 pour ES.
- Temps en position : 10 minutes par jour joué (3 h/an sur les jours lourds, 42 h/an tous les jours).
- À figer dans le protocole avant le calcul : jours (V = jours lourds, cause la plus forte ; R0 = tous les jours),
  signal (signe de 15:59-16:00 ou de 15:50-16:00), sortie 16:09 (marge avant 16:10), témoin (16:10-16:20, hors
  enchère), réplique NQ, lecture complète de BM23 et du papier EFMA avant d'écrire les règles.

### Écartées au crible du 2026-10-21
| Piste | Raison |
|---|---|
| Retournement de fin de journée (Baltussen-Da-Soebhag 2025) | déjà mesuré sur ES / NQ dans `gamma_intraday` / LETF (pente −0,017, t −1,5) |
| Retournement nuit / jour (Della Corte-Kosowski) | famille S06 (fade de l'overnight) déjà rejetée |
| Première heure des devises après le saut de 18:00 (SSRN 7135159, 2026) | H2 de `creneaux.py` déjà rejetée |
| Prépublications 2026 sur le NQ intraday (régimes, LSTM, ICT, Gann...) | famille saturée chez nous ; chaque essai abaisse le Sharpe déflaté |
| Brent intraday, ZN / ZB | pas de données (Brent) ou clé Databento absente |

## Lot du 2026-10-21 au soir (lecture et calcul de puissance seulement, aucun essai)

| Piste | Source (lue) | Verdict à la lecture |
|---|---|---|
| Retournement du dollar autour des fixings BCE / Londres sur 6E | Krohn, Mueller & Whelan, *JF* 2024 (version de travail lue en entier) | sur futures CME, coûts complets : Sharpe 0,61 pour le fix BCE (long dollar 2:00 → 8:15 ET, court 8:15 → 17:00) ; t attendu ≈ 0,61 × √10,6 ≈ 2,0 < 3 et 15 h par jour en position (≈ 3 800 h/an) ; les fenêtres courtes sont « plus que compensées par les coûts » selon les auteurs |
| Surcouche « fast alpha » (attendre une barre 5 min contraire avant d'entrer / sortir) sur S1 | Zarattini & Pagani, QuanTips n° 2, 02/2026 (note de praticiens lue en entier) | Sharpe 0,87 → 0,99 sur SPY 2007-2026, sans hors échantillon ni test du gain ; l'écart de 0,12 n'est pas mesurable avec t ≥ 3 sur 10 ans ; modifierait S1 figée |
| Tendance intraday du bitcoin selon la séance (Asie / États-Unis) | articles de blog (Concretum, Amberdata) ; « Bitcoin on Wall Street Time » (volatilité seulement) | aucune règle publiée ni rendement testé ; H12 (Padyšák-Vojtko, Wen) déjà rejetée |
| Effet de nuit et momentum intraday sur l'or et l'argent chinois | *Global Finance Journal* 2025 | marchés de Shanghai ; sur GC, même famille que or la nuit, H1, A1 (déjà testées) |
| Pression du roulement trimestriel des E-mini | aucune source académique trouvée | écartée |

## Crible du catalogue SSRN, 2026-10-22 (aucun essai)

`ssrn_intraday.csv` filtré sur nos actifs, avec une règle de trading, depuis 2020, non marqué testé : 84 articles. Presque
tous sont des prépublications de 2026 sans relecture (critère 1), souvent des tests négatifs (« falsification »,
« negative result ») ou des méthodes (LSTM, ICT, Gann). Les rares articles sérieux tombent dans des familles déjà
testées : momentum du pétrole (Wen et al. → Z1), EIA (P1), gamma des teneurs de marché (`gamma_intraday`), jours de
rendement anormal sur l'or et le pétrole (Caporale-Plastun 2020 → P1, M2), ETP VIX (données absentes), la clôture de
New York annonce l'ouverture de l'Asie (Kinoshita 2026 : le signal passe dans le saut d'ouverture, comme le week-end
crypto). Conclusion : aucune hypothèse nouvelle ne passe les critères 1 à 6 avec nos données ; pour atteindre 5
stratégies fiables, il faut de nouvelles données (voir `pistes_contrats_manquants.md`).

## Écartées après lecture

| Piste | Raison |
|---|---|
| Effet « quart d'heure » et « tour de bougie » sur la crypto (arXiv 2607.09426 ; 2023) | gain brut d'environ 0,4 pb par trade, inférieur aux frais |
| Flux des ETF bitcoin (Mazur & Polyzos 2025) | expliquent des niveaux de prix, pas des rendements ; créations en nature depuis 07/2025 |
| Fenêtres d'interdiction des rachats d'actions | SSGA et Alpha Architect : pas d'effet mesurable |
| Liquidité nette de la Fed, fonds à volatilité cible, DIX, structure courte du VIX | aucun article académique récent qui teste la prévision |
| Échéances d'options (vanna / charm, semaine d'OPEX) | sources de fournisseurs seulement ; options 0DTE quotidiennes depuis 2022 |
| Déséquilibre des volumes d'options (arXiv 2201.09319) | demande les volumes par type d'intervenant (CBOE, payant) |
| Momentum intraday des devises, effet yen (Seeck 2026) | famille déjà couverte par P1 ; l'article conclut lui-même à une barrière de coûts |
| Pré-FOMC actions, Halloween, tour de mois | lignées closes le 19/10/2026 (`fin_de_mois.py`) |

## Sources

- Zarattini, Pagani & Barbon 2025 : https://abarbon.com/papers/catching-crypto-trends
- Produits autorisés Topstep (MBT, MET) : https://topstepbrokerage.com/blog/new-permitted-products-offered-at-topstep

- Mourey, Shahrour & Şoiman 2025, *Finance Research Letters* : https://doi.org/10.1016/j.frl.2025.108661
- Li & Yuan 2026 : https://papers.ssrn.com/sol3/papers.cfm?abstract_id=7543402
- Bogousslavsky & Muravyev 2023, *Journal of Financial Markets* : https://doi.org/10.1016/j.finmar.2023.100852
- Lee, Liao & Lee 2022, *Journal of Futures Markets* : https://doi.org/10.1002/fut.22321
- Chuk 2026 : https://papers.ssrn.com/sol3/papers.cfm?abstract_id=7609644
- Demirev 2025 : https://papers.ssrn.com/sol3/papers.cfm?abstract_id=5325376
- Mesfin 2026 : https://papers.ssrn.com/sol3/papers.cfm?abstract_id=6709401
- Wei 2026 : https://papers.ssrn.com/sol3/papers.cfm?abstract_id=7257240
- Seeck 2026 : https://papers.ssrn.com/sol3/papers.cfm?abstract_id=7008318
- Bangsgaard & Kokholm 2023 : https://papers.ssrn.com/sol3/papers.cfm?abstract_id=4470636
- Perry 2026 : https://papers.ssrn.com/sol3/papers.cfm?abstract_id=6728359
- Pan & Peng 2026 : https://en.saif.sjtu.edu.cn/junpan/FOMC_new.pdf
- Fleming, Liu & Nguyen 2026 : https://www.newyorkfed.org/research/staff_reports/sr1188
