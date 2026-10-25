# Inventaire des hypothèses (registre unique, critère 5)

État au 2026-10-25. Une ligne par hypothèse tirée d'une source sérieuse ou déjà étudiée dans ce dépôt. À consulter AVANT
toute nouvelle piste ; à compléter à chaque lecture ou test.

**Statut**
- **RETENUE** : passe les 24 critères de `CLAUDE.md`.
- **FIABLE, NON RETENUE** : fiable au sens du tableau de bord (critères 17-18) mais échoue à un autre critère.
- **REJETÉE** : testée, échoue (fichier de résultats indiqué).
- **ÉCARTÉE** : abandonnée à la lecture, sans essai (source faible, puissance insuffisante, données impossibles…).
- **OUVERTE** : jamais testée ; reste à lire en entier, puis calcul de puissance (critère 6) avant tout essai.
- **À RELIRE** : testée sur un simple résumé ; relire le texte complet et ne retester que si la règle diffère (critère 5).

**Fiabilité a priori** (seulement pour les OUVERTES) : ★ à ★★★★★, d'après la source (revue, institution), la preuve
récente (après 2016), la cause observable aujourd'hui et la puissance attendue. Ce n'est PAS un résultat.

**Données** : « dispo » = déjà sur le PC (`Cotations`, `.cache`) ; « Databento » = à acheter (clé absente, devis à faire) ;
« payant » = autre source payante.

## 1. Indices actions (ES, NQ, YM, RTY, Nikkei, DAX, FTSE)

| # | Hypothèse | Source | Statut | Données | Résultat / remarque |
|---|---|---|---|---|---|
| 1 | La 1re demi-heure annonce la dernière | Gao, Han, Li & Zhou, *JFE* 2018 | REJETÉE | dispo | P1 (`Python/LISEZMOI.md` § 14) |
| 2 | Momentum de fin de séance porté par la couverture gamma | Baltussen, Da, Lammers & Martens, *JFE* 2021 | REJETÉE | dispo | `gamma_intraday`, `bdlm_conditionnel` : mécanisme confirmé, stratégie trop faible |
| 3 | Zone de bruit (Noise Area) | Zarattini, Aziz & Barbon 2024 | **RETENUE** sur NQ (S1) | dispo | rejetée sur ES, YM, DAX, GC, CL, devises |
| 4 | Cassure de la 1re bougie de 5 min, filtre de volume | Zarattini, Barbon & Aziz 2024 | FIABLE, NON RETENUE | dispo | ORB NQ : Sharpe 0,92, déflaté 0,70 ; voir n° 49 |
| 5 | Cassure d'ouverture, version 2023 | Zarattini & Aziz 2023 | REJETÉE | dispo | NQ après publication, Nikkei (N2), FTSE (E3), DAX (H3) |
| 6 | Retour au VWAP | Zarattini 2024 | REJETÉE | dispo | 0,21 / 0,26 |
| 7 | Dérive de nuit (2:00-3:00 ET) | Boyarchenko, Larsen & Whelan, *RFS* 2023 | REJETÉE | dispo | `derive_nocturne` ; disparue depuis 2021 (Fed de New York 2026) |
| 8 | Hausse avant le FOMC | Lucca & Moench, *JF* 2015 | REJETÉE | dispo | trois fois (ES 4, P1, `cycle_fomc`) |
| 9 | Rallye et retournement le jour du FOMC | lignée Lucca-Moench | REJETÉE | dispo | P1 |
| 10 | Cycle du FOMC, « Fed put » | Cieslak, Morse & Vissing-Jorgensen, *JF* 2019 | REJETÉE | dispo | `cycle_fomc` ; contre-papier Uppal 2025 |
| 11 | Prime des jours d'annonce macro | Savor & Wilson, *JFQA* 2013 | REJETÉE | dispo | SPY 5, P1 |
| 12 | Dérive avant ISM / NFP | lignée Kurov et al. | REJETÉE | dispo | ES 2 (famille entière éliminée) |
| 13 | Tour de mois, ventes forcées | Etula et al. 2020 | REJETÉE | dispo | `fin_de_mois` |
| 14 | Rééquilibrage des 60/40 en fin de mois | Harvey, Mazzoleni & Melone 2026 | REJETÉE | dispo | `fin_de_mois` |
| 15 | Rééquilibrage des ETF à levier | Cheng & Madhavan 2009 ; Barbon et al. | REJETÉE | dispo | fiche 15 (L1) |
| 16 | Couverture des ETP VIX en fin de séance | Bangsgaard & Kokholm, *JBF* 2025 (publié) | ÉCARTÉE | encours ETP introuvables | un substitut referait l'échec LETF ; version publiée vérifiée le 2026-10-23 : même blocage |
| 17 | Retournement de l'enchère de clôture | Bogousslavsky & Muravyev, *JFM* 2023 | ÉCARTÉE | — | C1 : l'effet ne passe pas aux futures, t < 1 |
| 18 | Veilles de jours fériés | Ariel 1990 | REJETÉE | dispo | Z2 |
| 19 | Halloween | Bouman & Jacobsen, *AER* 2002 | ÉCARTÉE | dispo | trop peu de puissance sur 10 ans |
| 20 | Retournement des indices (arbitrage indiciel) | Baltussen, van Bekkum & Da, *JFE* 2019 ; Nagel, *RFS* 2012 | REJETÉE | dispo | `rachat_baisse` |
| 21 | Exposition gérée par la volatilité | Moreira & Muir, *JF* 2017 (+ 8 papiers) | REJETÉE | dispo | `vol_geree` |
| 22 | Résultats des méga-capitalisations (NQ 1-A) | 8-K EDGAR | FIABLE, NON RETENUE | dispo | déflaté 0,32 ; extension à 8 autres sociétés rejetée (H13) |
| 23 | Indice local après les résultats (Japon, SAP) | règle de NQ 1-A | REJETÉE | dispo | J1, D1 |
| 24 | Week-end crypto → lundi des indices | Mourey, Shahrour & Şoiman, *FRL* 2025 | REJETÉE | dispo | `weekend_crypto` |
| 25 | Écart d'ouverture, fade de la nuit | famille S06 | REJETÉE | dispo | S06-C, IWM 1, P1 |
| 26 | Un actif en retard sur un autre | famille IWM 2 | REJETÉE | dispo | famille éliminée |
| 27 | Écart YM - ES (paires intraday) | famille YM 2 | REJETÉE | dispo | — |
| 28 | Retournement après un choc de 2 écarts-types | Nagel 2012 | REJETÉE | dispo | YM 5, 6B 2, 6J 3 |
| 29 | Quatre sorcières | — | REJETÉE | dispo | YM 4 ; version du papier (pic de nuit + retournement) → n° 145 |
| 30 | Lundi matin, après le déjeuner, retournement d'après-midi (0DTE) | divers | REJETÉE | dispo | P1 |
| 31 | Persistance à la même heure | Heston, Korajczyk & Sadka, *JF* 2010 | REJETÉE | dispo | P1 |
| 32 | Microstructure : volume, déséquilibre, emballements | Campbell-Grossman-Wang ; Chordia-Subrahmanyam ; Christensen-Oomen-Renò 2022 | REJETÉE | dispo | M1, M2 (66 essais) |
| 33 | Retour après sortie de la bande du VIX | Seeck 2026 | REJETÉE | dispo | H8 |
| 34 | Tendance Donchian 15 min conforme (boombitch) | script personnel | **RETENUE** sur NQ (H5) | dispo | Welch 2,81, déflaté 0,98 |
| 35 | Même règle sur les 8 autres contrats | H5 | REJETÉE (YM fiable non retenu) | dispo | H6 : YM t 2,91, 2e moitié t 1,04 |
| 36 | Achats d'ETF par la Banque du Japon l'après-midi | Harada & Okimoto, *IRFA* 2021 | ÉCARTÉE | — | programme arrêté en mars 2024 : plus jouable |
| 37 | Momentum intraday du Nikkei et du FTSE | Li, Sakkas & Urquhart, *J. Financial Markets* 2022 | REJETÉE | dispo (CFD) | N1 −1,16, E2 −0,70 ; texte complet relu le 2026-10-22 : même règle, pas de nouveau test |
| 38 | Clôture du DAX 17:00-17:30 | Li-Sakkas-Urquhart ; S19-B inversée | REJETÉE | dispo | `dax_cloture` |
| 39 | Sentiment des ETF sectoriels la nuit → futures d'indices | Lee, Liao & Lee, *J. Futures Markets* 42(6), 2022 | REJETÉE (essai n° 431) | dispo (ETF XL*) | résumé seul, test par dérogation demandée par l'utilisateur ; règle intraday unique figée (`etf_nuit`) : ES 9:35-16:00 contre le sens de la nuit les jours de forte comouvement, −3,4 pb net (t −0,4), Sharpe −0,22, Welch −0,7 ; NQ, YM pareils |
| 40 | Retour après une enchère hebdomadaire ratée | Perry 2026 (prépublication pré-enregistrée, SSRN 6728359) | ÉCARTÉE le 2026-10-25 | dispo | p 0,014 sur ES (t ≈ 2,5), 0,09 ailleurs : même si l'effet se maintient, t attendu ≈ 2,5 < 3 (critère 6) ; auteur seul, prépublication (critère 1, comme le n° 124) ; page SSRN bloquée par la vérification anti-robot |
| 41 | La clôture de New York annonce l'ouverture de l'Asie | Kinoshita 2026 | ÉCARTÉE | — | le signal passe dans le saut d'ouverture |
| 42 | Prime des actions tenue la nuit (18:00 → 9:30) | Boyarchenko et al. 2023 ; Fed de New York 2026 | ÉCARTÉE | dispo | contre-papier : disparue depuis 2021 |
| 43 | Surcouche « fast alpha » sur S1 | Zarattini & Pagani 2026 (note) | ÉCARTÉE | dispo | gain de 0,12 de Sharpe non mesurable ; S1 figée |
| 44 | Facteurs intraday qui prédisent le marché | Aleti, Bollerslev & Siggaard, *Mgmt Sci* 2025 | ÉCARTÉE | — | apprentissage automatique sur des facteurs d'actions qu'on n'a pas |
| 45 | Réplique de S1, ORB, H5 sur le Russell (RTY) | règles retenues | **OUVERTE** ★ | Databento (RTY depuis 07/2017) | répliques sur ES / YM déjà ratées |
| 46 | Reconstitution du Russell (juin) | Dimensional 2024 ; EFMA 2007 | ÉCARTÉE | — | actions au comptant, 1 fois par an |
| 47 | Échéance du VIX (règlement du mercredi) sur l'ouverture d'ES | Griffin & Shams, *RFS* 2018 | ÉCARTÉE le 2026-10-25 | dispo | critère 6 : effet mesuré sur les options du S&P, pas sur l'indice ni sur ES → aucun calcul de puissance possible ; la seule mesure sur ES (Perry 2026, n° 40) donne t ≈ 2,5 < 3 |
| 48 | Momentum des facteurs de nuit (« Day destroys the night ») | Akbas et al. ; Carlo Alberto | ÉCARTÉE | — | actions individuelles ; famille S06 rejetée |
| 49 | **ORB NQ rejouée sur 2010-2015** (confirmation, pas un essai) | n° 4 | **OUVERTE** ★★★★ | Databento | t attendu ≈ 2,3 sur la période ; déflaté probablement juste sous 0,95 |

## 2. Taux (ZN, ZB, ZF, ZT) — tout demande Databento

| # | Hypothèse | Source | Statut | Données | Résultat / remarque |
|---|---|---|---|---|---|
| 50 | Cycle des adjudications : baisse avant, reprise après | Lou, Yan & Zhang, *RFS* 2013 ; Fleming, Liu & Nguyen, Fed de New York SR 1188, 2026 | ÉCARTÉE (calcul de puissance du 2026-10-22) | Databento | ZB (meilleur cas) : ~160 $ bruts contre ~135 $ de coûts par contrat et par adjudication, soit ~25 $ nets ; écart-type sur les ~6 h ~800 $ ; ~128 adjudications à 30 ans sur 2016-2026 → t attendu ≈ 0,35 ; ZN : gain net négatif. Pas d'achat de données pour elle |
| 51 | Momentum de fin de séance sur les obligations (et matières premières : or, pétrole, gaz, grains, bétail) | Baltussen et al., *JFE* 2021 (60 futures dont 16 obligations et 21 matières premières, 1974-2020) | ÉCARTÉE (texte complet lu le 2026-10-23, PDF libre www3.nd.edu/~zda/intramom.pdf) | Databento | tableau 6, portefeuille 1/N, avant frais : obligations 2,16 %/an soit **~0,9 pb par jour** (Sharpe 1,62), matières premières 4,34 %/an soit ~1,7 pb par jour ; la pente sur les obligations est divisée par deux entre 1974-1999 (3,19) et 2000-2020 (1,53, R² 0,47 %) ; par contrat (tableau B2) ZN : R² 0,24 % (première demi-heure). Nos frais aller-retour : ZN ~3,3 pb, grains ~11 pb (ZC : tick 12,50 $ pour ~22 000 $), bien au-dessus du gain brut → t attendu < 0 ; les auteurs disent eux-mêmes que la stratégie n'est sans doute pas exploitable après frais (seul le S&P l'est, rejeté chez nous, n° 2). Aucun essai |
| 52 | Fin de mois du Trésor, partie de jour | Hartley & Schwarz 2019 | REJETÉE (ETF journalier) ; version future ÉCARTÉE le 2026-10-25 | Databento | IEF : t 2,1, déflaté 0,10 ; version future : puissance < 3 avec 129 mois (critère 6), et le volume de 16:00 (n° 286) ne donne pas de rendement |
| 53 | Hausse des obligations la veille du FOMC | Pan & Peng 2026 | ÉCARTÉE | — | ~5 pb par réunion, 8 réunions par an : puissance trop faible |
| 54 | Dérive des taux après un changement de taux directeur | Brooks, Katz & Lustig, NBER 2018 | ÉCARTÉE le 2026-10-25 | Databento | tenue de plusieurs semaines dans le sens de la surprise (non conforme : stratégie courte, à plat à 16:10) ; même famille que le n° 166, écarté ; la seule partie intraday est le n° 55 |
| 55 | Baisse des taux dans les 3 h après le FOMC | Fleming, Liu & Nguyen, Fed de New York SR 1188, 2026 (texte complet lu le 2026-10-25, annexe fig. A4) ; Brooks-Katz-Lustig ; Indriawan et al. 2021 | ÉCARTÉE le 2026-10-25 | Databento (ZN, ZB) | baisse de 0,5 à 1,5 pb de rendement en 3 h, 1997-2024 (~220 FOMC), « significative » (t brut ≈ 2 pris comme hypothèse, aucun écart-type chiffré). Coût en pb de rendement : ZN 0,51 (3,3 pb de prix ÷ duration 6,5), ZB 0,34 (5,8 ÷ 17). t attendu sur 1997-2024 : ZN −0,03 / 0,98 / 1,32, ZB 0,64 / 1,32 / 1,55 (effet 0,5 / 1 / 1,5 pb) ; sur 2016-2026 (~80 FOMC) au mieux 0,93 → sous 3, aucun essai |
| 56 | Dérive avant les publications de 8:30 | Kurov et al., BCE WP 1901 | ÉCARTÉE | — | suit le signe de la surprise, inconnu avant 8:30 |
| 57 | Prime des jours d'annonce sur les obligations | Savor & Wilson 2013 ; Wachter & Zhu | ÉCARTÉE le 2026-10-25 | Databento | papier contraire (critère 4) : Balduzzi & Moneta, *JFQA* 2017 (données intraday des taux) : prime forte avant la crise, gagnée surtout AVANT les annonces, **non significative après la crise** ; Savor & Wilson : actions, 1958-2009 (critère 2) |
| 165 | Les obligations montent la veille de l'annonce trimestrielle de refinancement du Trésor (vendredi avant le lundi 15:00) | Wang (Notre Dame) & Zhao (OFR), prépublication SocArXiv 2024 (lue en entier le 2026-10-23) | ÉCARTÉE | Databento | 1991-2023 ; tableau 8 (2003-2023, effets jour et fin de mois retirés) : 5 ans +8,0 pb (t 2,7), 7 ans +10,6 (t 2,5), 30 ans +16,5 (t 1,5) ; le « Sharpe de 4 » annualise 4 jours par 252 ; inversé en récession. Puissance (effet du papier moins nos coûts, 43 annonces 2016-2026, 67 depuis 2010) : ZF 1,5 (1,8), ZN 1,2 (1,6), ZT 1,0, ZB 0,7, UB 0,7 → t < 2 partout ; source sans comité de lecture (`tri_hypotheses_donnees.md`) |
| 166 | Les taux continuent 2 à 7 semaines dans le sens de la surprise du FOMC | Brooks, Katz & Lustig, NBER w25127 2019 (1989-2008, lu) ; Indriawan, Jiao & Tse, *JBF* 2021 (après 2008, payant : ~15 jours, aucune dérive avant le FOMC) | ÉCARTÉE | Databento (ZN, ZQ) | complète les n° 54-55 ; surprises récentes de 2 à 5 pb → 20-50 pb de dérive contre ~280 pb d'écart-type sur 50 jours, et la version conforme (sortie chaque vendredi) coûte ~10 allers-retours : t ≈ 0 |
| 167 | Le marché américain monte les jours où beaucoup de dividendes sont versés (réinvestissement annoncé des semaines avant) | Hartzmark & Solomon, *AER* 2025 (« Market-Wide Predictable Price Pressure » ; NBER w30688 lu en entier le 2026-10-23) | ÉCARTÉE | dispo (ES, NQ) + calendrier des versements (CRSP, payant) | 1926-2018, marché pondéré : quintile haut ~8 pb par jour contre ~2 pb pour les deux bas (moyenne 4,1 pb) ; le coefficient faiblit avec le temps (avant 1960 t 1,83, après 1960 t 1,58, **après 1980 t 0,73**). Puissance sur ES (quintile haut ≈ 50 jours par an, 8 pb − 1 pb de coûts, écart-type ~110 pb, ~540 jours 2016-2026) : t ≈ 1,5 seul, ≈ 0,8 contre le témoin (tous les jours) → aucun essai |
| 168 | Retournement de fin de séance (les actions qui ont baissé dans la journée remontent dans la dernière demi-heure) | Baltussen, Da & Soebhag 2025 (document de travail, 2e prix Quantpedia 2025 ; texte complet lu, www3.nd.edu/~zda/EOD.pdf) | ÉCARTÉE | — | effet en coupe transversale (acheter les actions perdantes, vendre les gagnantes : 3,8 pb par jour, t 10,7) ; au niveau de l'indice, les mêmes auteurs trouvent le contraire (momentum, n° 2, déjà rejeté) : rien à jouer avec un future d'indice |
| 169 | La nuit des indices américains se retourne dans la première demi-heure | Iwanaga & Sakemoto 2025 (« Intraday Time Series Reversal », document de travail ; texte complet derrière un captcha ; publié en 2026 : *North American J. of Economics and Finance* 102707, effet affaibli depuis les années 2010 d'après le résumé) | ÉCARTÉE | dispo | même famille que le n° 25 (fade de la nuit), déjà rejetée ; les auteurs disent eux-mêmes que l'effet **faiblit après les années 2010** et vient surtout des crises (2008, COVID) |
| 170 | Les devises se retournent après le FOMC (le mouvement de la journée de l'annonce s'efface dans les 12 h) | Lee & Wang, *Review of Asset Pricing Studies* 2025 (chiffres de la thèse de Lee) | ÉCARTÉE | dispo (6E, 6J, 6B, 6A) | ~10 pb rendus par fenêtre de 12 h, ~85 réunions 2016-2026 → t attendu 1,6 à 2,2 (< 3) ; famille du n° 9 (retournement FOMC sur le S&P, rejeté) |
| 171 | Les gilts britanniques montent avant les réunions de la Banque d'Angleterre | Lou, Pinter, Üslü & Walker, *JFE* 2025 | ÉCARTÉE | — | gilts cotés à l'ICE (pas de prop firm) ; la version américaine est contredite par Pan & Peng 2026 (n° 53 : ~5 pb par réunion, puissance trop faible) ; **réexaminé le 2026-10-25 (tous marchés permis)** : Lou, Pinter & Üslü, BoE SWP 998 (2022) et Bank Underground (02/2025) : les taux des gilts MONTENT sur les 2 jours avant le MPC, ~2 points de % cumulés en 20 ans (~160 réunions → ~1,25 pb de taux par réunion ≈ 12 pb de prix sur le Long Gilt, frais ~2,5 pb) ; écart-type sur 2 jours ≈ 80 pb de prix (approximation, non donnée par le papier) → t attendu ≈ 1,1 sur 2016-2026 (80 réunions), ≈ 1,8 sur les seules réunions précédées d'une adjudication (~40 cas, il faut t ≥ 2) ; ÉCARTÉE |
| 172 | **Tout le rendement de l'ES se fait dans les 4 h autour de l'ouverture européenne (23:30 → 3:30 ET)**, créneau vide de notre groupe | Bondarenko & Muravyev, *JFQA* 58(3) 2023 (texte complet payant, SSRN derrière une vérification anti-robot ; annexe en ligne lue le 2026-10-23) | REJETÉE (essai n° 434, dérogation demandée par l'utilisateur) | dispo (ES, NQ, YM) | 2004-2018 : 7,6 % par an dans la fenêtre, Sharpe 1,6-1,67 (t 6,4), rien les 20 autres heures ; **l'heure 1:30-2:30 fait 5,0 des 7,6 points**. Puissance (`t_attendu`, effet du papier 3,0 pb par nuit, écart-type ~29 pb tiré du Sharpe 1,67, 2 680 nuits 2016-2026, coûts au prix médian, recalculée le 2026-10-24 : le chiffre du 2026-10-23, t ≈ 3,8, prenait par erreur le coût de l'ES au prix récent) : **ES 2,6 (coût 1,55 pb) → sous 3**, MES −1,6 (3,9 pb) ; répliques NQ 4,3 (0,62 pb), MNQ 1,0, YM 3,7, MYM −1,5. Mais le cœur de la fenêtre est celui de la dérive de nuit (n° 7) : plat sur 2021-2025 selon la Fed de New York (« The Disappearing Overnight Drift », 2026) et chez nous (2:00-3:00 ES 2021-2026 : −0,04 pb, t −0,1 ; `resultats_derive_nocturne.txt`) → critère 11 presque sûrement perdu. Testé le 2026-10-24 (`ouverture_europe`, règle du papier figée : achat 23:30 → vente 3:30 chaque nuit, témoin 19:30 → 23:30) : ES +1,38 pb brut (t 2,3), **2016-2020 +3,19 pb (t 3,1) = le papier, 2021-2026 −0,23 pb** ; net −0,18 pb, Sharpe −0,07 [−0,73 ; 0,51], Welch 1,3 ; MES −2,5 pb net ; NQ net +1,22 pb mais Sharpe 0,55 [−0,03 ; 1,09], après 2021 −0,04 ; YM pareil ; micros perdants → rejetée, l'effet s'est éteint comme la dérive de nuit |
| 173 | Dérive avant les décisions de la BCE (8:15 ET), de la Banque d'Angleterre et de la Banque du Japon | Quantpedia 2025 (praticiens) | ÉCARTÉE | dispo (6E, 6B, 6J, ES) | contre-papier à comité : Brusa, Savor & Wilson, *Review of Finance* 2020 (« One Central Bank to Rule Them All ») : aucune prime autour des autres banques centrales, ni à l'étranger ni chez elles ; Lucca & Moench (2015) n'en trouvent pas non plus ; les dérives d'après décision sont déjà rejetées (n° 81) |
| 174 | Le yen baisse en début de mois (achats d'actions étrangères des fonds NISA) | presse (MUFG, Barclays 2026) | ÉCARTÉE | dispo (6J) | aucune étude ; les flux ne sont publiés qu'en total mensuel (critère 1) |
| 175 | Le « gap » du dimanche soir des futures bitcoin CME se referme | indicateurs TradingView, presse crypto | ÉCARTÉE | dispo (MBT, Binance) | aucune étude ; le bitcoin cote tout le week-end, le saut de réouverture contient déjà l'information (même raisonnement que le n° 83, rejeté) |
| 176 | L'or réagit au fixing de Shanghai (10:15 et 14:15 Pékin = 22:15 et 2:15 ET) | aucune étude (règlement SGE, blogs) | ÉCARTÉE | dispo (GC) | critère 1 ; le seul fixing d'or étudié (Londres, n° 72) a perdu son effet à la réforme de 2015 |
| 177 | Or et argent : momentum d'une séance (Asie, Europe, États-Unis) à la suivante | prépublication SSRN 7257240, 2026 (auteurs et résumé introuvables) | ÉCARTÉE | dispo (GC, XAGUSD) | source invérifiable (critère 1) ; la version « séance américaine → Asie » est déjà rejetée (n° 70) |
| 178 | Le trading de nuit des actions américaines depuis l'Asie (Blue Ocean, 20:00-4:00 ET, investisseurs coréens) crée des écarts qui se corrigent | Eaton et al., document de travail (Université du Tennessee, 2024) | ÉCARTÉE | — | le papier trouve l'inverse : deux tiers des mouvements de nuit ne se retournent pas (c'est de l'information) ; les futures d'indices cotent déjà la nuit |
| 179 | Grains (maïs, soja, blé) : rendement de la séance de nuit (19:00-7:45 ET) | aucune étude (seulement des liens Chine - États-Unis, *J. Futures Markets* 2017) | ÉCARTÉE | Databento | critère 1 ; contrats hors de nos 9 (rang 4 du classement des achats) |
| 180 | Nikkei : retournement autour de la pause de midi de Tokyo ou de la séance de nuit d'Osaka (créneau 22:30-3:30 ET) | aucune étude (commentaires de marché) | ÉCARTÉE | Databento (NKD) | critère 1 ; les créneaux du Nikkei sont déjà testés et rejetés sur HistData (`resultats_creneaux.txt`) |
| 181 | Devises : le momentum entre devises se gagne la nuit, le portage le jour | Krohn, Mueller & Whelan, « FX Premia Around the Clock » (version 2018) ; « Uncovered Interest Parity in High Frequency », Banque du Canada 2024 (lu) | ÉCARTÉE | dispo (6E, 6B, 6J, 6A) | la version publiée et celle de 2024 ne gardent que le portage, gagné **le jour** (la nuit ≈ 0) et déjà rejeté (n° 84) ; le momentum de nuit n'est que dans le brouillon de 2018 ; un panier long-court tenu chaque nuit paierait ~1,3-2 pb par devise et par nuit pour un gain brut de l'ordre de 1-2 pb par jour |
| 182 | Pétrole : rendement selon la séance (Asie, Europe, États-Unis) | aucune étude (seul l'ES est décomposé, n° 172) | ÉCARTÉE | dispo (CL) | critère 1 ; prime de nuit du pétrole déjà sans source (n° 115) |
| 183 | Devises : le cours est « aimanté » vers les gros prix d'exercice des options qui expirent à 10:00 New York (NY cut), puis se libère | commentaires de courtiers (Newsquawk, VT Markets, 2026) | ÉCARTÉE | dispo (6E, 6J) + tailles des expirations (payantes) | aucune étude ; le sens dépend des positions des teneurs de marché, invisibles dans la liste des expirations |
| 184 | Or : hausse avant le FOMC (version or de la dérive de Lucca-Moench) | aucune étude | ÉCARTÉE | dispo (GC) | critère 1 ; Lucca & Moench (2015) ne trouvent la dérive ni sur les taux ni sur les devises, et elle est rejetée sur l'ES (n° 8) |
| 185 | Pétrole : réaction au décompte des forages Baker Hughes (vendredi 13:00 ET) | presse (Bloomberg 2015, Forexlive 2016) | ÉCARTÉE | dispo (CL) | aucune étude ; réaction devenue faible selon la presse elle-même ; le sens suit la surprise |
| 186 | Or et devises : le rapport COT de la CFTC (vendredi 15:30 ET) prévoit les prix du lundi | thèse PolyU 2013 ; Sanders, Irwin & Merrin, *JARE* 2009 | ÉCARTÉE | dispo (fichiers COT dans `.cache/cftc`) | études contraires : les positions des spéculateurs SUIVENT les prix (or, argent, agricoles), elles ne les prévoient pas ; données vieilles de 3 jours à la publication ; version mensuelle déjà jugée (Park, *JBF* 2022 : anticipation) |
| 187 | Or et devises : dérive (ou retournement) dans l'heure qui suit l'emploi (NFP) ou l'inflation (CPI) | FXStreet (or, 2022-2023) ; Almeida, Goodhart & Payne, *JFQA* 1998 ; Banque de Norvège, mémo 5-2026 | ÉCARTÉE | dispo (GC, 6E, 6J) | contre-papiers : les devises s'ajustent en moins de 15 min puis l'effet s'efface (JFQA 1998, Norges Bank 2026) ; l'or : corrélation non significative après 1 h (FXStreet) ; le test FX après NFP/CPI du labo est déjà rejeté |
| 188 | Pétrole : les dates des réunions de l'OPEP prévoient les rendements | *J. Economics, Finance & Administrative Science* 2020 ; *North American J. Econ. & Finance* 2018 | ÉCARTÉE | dispo (CL) | sources faibles, 2013-2017, effet sur les quantiles et la volatilité (pas sur la moyenne), sens selon la décision ; une dizaine de réunions par an |
| 189 | Momentum croisé entre futures d'actions et devises | *J. International Money and Finance* 2024 | ÉCARTÉE | — | horizon mensuel, pas une stratégie courte |
| 190 | Or : comportement pendant les fêtes chinoises (Nouvel An, Semaine d'or : Shanghai fermé) | aucune étude trouvée | ÉCARTÉE | dispo (GC) | critère 1 ; deux épisodes par an |

## 3. Énergie (CL, NG)

| # | Hypothèse | Source | Statut | Données | Résultat / remarque |
|---|---|---|---|---|---|
| 58 | **Gaz : le rendement se gagne les jours du rapport de stocks EIA** (> 50 % du rendement annuel ces jours-là, moitié avant, moitié après 10:30) | Prokopczuk, Wese Simen & Wichmann, *Energy Journal* 2021 | ÉCARTÉE | Databento (NG) | texte complet (SSRN 3575861) lu le 2026-10-22 : vente 90 min avant → 30 min après 10:30, 2003-2018 ; Sharpe net 1,76 sur tout l'échantillon mais **3,26 avant 2011 et −0,16 après 2011** (brut +2,9 %/an, p = 0,56) ; effet journalier absent sur 2014-2018 (annexe A.3) ; les auteurs concluent à sa disparition. Calcul de puissance avec l'effet après 2011 (5,6 pb brut par rapport, notre coût 8,3 pb) : t attendu ≈ −0,4 → aucun essai, aucun achat |
| 59 | Gaz : dérive dans le bon sens 90 min avant le rapport | même lignée (2008-2016) | **OUVERTE** ★★ | Databento + consensus des analystes (payant) | le sens dépend de la surprise, inconnue avant |
| 60 | Gaz : retour partiel la semaine suivant une surprise | Ederington, Lin, Linn & Yang, *Energy Journal* 2019 | **OUVERTE** ★★ | Databento + consensus (payant) | — |
| 61 | Roulement des indices de matières premières (GSCI) | Mou 2010 | REJETÉE sur CL ; ÉCARTÉE sur NG / HG le 2026-10-25 | Databento | écarts entre échéances tenus plusieurs jours (non conforme) ; papier contraire (critère 4) : Dubois & Maréchal (pas de gain après coûts, écart moyen négatif sur 2004-2010) ; seule preuve après 2011 : un mémoire de master (Aalto, 2012), critère 1 |
| 62 | Pétrole : momentum intraday | Wen et al. 2021 | REJETÉE | dispo | Z1 −2,28 |
| 63 | Pétrole : rapport EIA, rapport API | divers | REJETÉE | dispo | P1, CL 1, CL 2, CL 4 |
| 64 | Brent : saisonnalité intraday | Ewald et al., *Quantitative Finance* 2025 | ÉCARTÉE | — | heures sous embargo jusqu'en 2027 |
| 65 | Pétrole et or : jours de rendement anormal | Caporale & Plastun 2020 | ÉCARTÉE | dispo | familles P1 / M2 déjà rejetées |
| 66 | Pression de la fenêtre de règlement (TAS) | dossiers CFTC, présentations | ÉCARTÉE | — | aucun article publié |

## 4. Métaux (GC, SI, HG)

| # | Hypothèse | Source | Statut | Données | Résultat / remarque |
|---|---|---|---|---|---|
| 67 | Or tenu la nuit (13:30 → 8:20) | Blose & Gondhalekar 2014 | FIABLE, NON RETENUE | dispo | 1,11, déflaté 0,74 ; garde la nuit et le week-end |
| 68 | Or la nuit rendu conforme | même | REJETÉE | dispo | H10 : 0,34 en MGC |
| 69 | Dix anomalies intraday de l'or | fiche du 9/10/2026 | REJETÉE | dispo | `or_anomalies` |
| 70 | Or et argent : la séance américaine annonce l'Asie | Wei 2026 | REJETÉE, À RELIRE | dispo | H1 −0,29 (or), A1 −0,29 (argent) ; testé sur résumé |
| 71 | Or : ouverture de Shanghai | — | REJETÉE | dispo | P1 |
| 72 | Or : fixing de Londres | Caminschi & Heaney, *JFM* 2014 | ÉCARTÉE | — | effet d'avant la réforme du fixing (2015) |
| 73 | Métaux chinois : momentum intraday, effet de la nuit | *Global Finance Journal* 2025 ; Bouri et al. | ÉCARTÉE | — | marché de Shanghai ; disparaît avec la séance de nuit |
| 74 | Réplique de S1 / H5 sur l'argent (SI) | règles retenues | **OUVERTE** ★ | Databento | — |
| 75 | Réplique de S1 / H5 sur le cuivre (HG) | règles retenues | **OUVERTE** ★ | Databento | — |

**Crible « or / MGC » du 2026-10-22 (aucun essai).** Seuil de coûts du MGC : 1 tick (1 $) + 2,50 $ par côté, soit 7 $
l'aller-retour pour ~45 000 $ de notionnel : ~1,6 pb par trade à battre (environ 3 fois le GC rapporté au notionnel). Les
156 résumés SSRN qui parlent de l'or (sur 23 136) ont été lus : méthodes de particuliers (VWAP / EMA, « Smart Money »,
Fibonacci, Fair Value Gap), apprentissage automatique, études de volatilité ou de valeur refuge, or tokenisé, marchés
chinois et indiens. Seuls rapprochements utiles : Bell 2026 (or tenu la nuit entre deux fixings de Londres, 2000-2010 :
même famille que n° 67) ; Aggarwal & Lucey 2005 (barrières psychologiques : famille des chiffres ronds, rejetée). Recherche
dans les revues (*JFM*, *J. Commodity Markets*, *J. Empirical Finance*, *Global Finance Journal*) et sur le prix
d'enchère LBMA depuis 2015 : rien de jouable. **Aucune hypothèse nouvelle pour le MGC.** Seule version déjà mesurée qui
tient en MGC : l'or la nuit dans sa forme publiée (nuit ET week-end), Sharpe 0,96 en MGC (`Python/LISEZMOI.md` § 12),
réservée aux firmes qui permettent nuit et week-end (Phidias Premium, Elite Trader Funding) et sous le seuil de Sharpe
déflaté (critère 16).

## 5. Devises (6E, 6B, 6J, 6A ; 6C, 6S, 6N, 6M absents)

| # | Hypothèse | Source | Statut | Données | Résultat / remarque |
|---|---|---|---|---|---|
| 76 | Gotobi : flux des importateurs japonais au fixing de Tokyo | Ito & Yamada 2017 ; Krohn et al. 2024 | **RETENUE** (6J) | dispo | micro MJY non fiable, 6J entier oui |
| 77 | Gotobi sur 6E, 6B, 6A | même | REJETÉE | dispo | H9 −1,63 |
| 78 | Dollar en forme de W autour des fixings (Tokyo, BCE, Londres) | Krohn, Mueller & Whelan, *JF* 2024 | ÉCARTÉE | dispo | futures, coûts complets : Sharpe 0,61 (fix BCE), t attendu ≈ 2,0 |
| 79 | Fix de Londres en fin de mois | Melvin & Prins ; Krohn et al. | REJETÉE | dispo | `fx_trois` |
| 80 | Devises autour du FOMC | lignée Mueller et al. | REJETÉE | dispo | P1 |
| 81 | Dérive après BCE, BoE, BoJ, RBA | — | REJETÉE | dispo | 6E 3, 6B 3, 6J 4, 6A 4 |
| 82 | Australien après les chiffres chinois (NBS) | — ; Baum, Kurov & Halova, *JIMF* (chiffres chinois → futures mondiaux) | REJETÉE | dispo | 6A 1 ; le sens suit la surprise (industrie, PMI), inconnue avant la publication |
| 83 | Retour du saut de réouverture de 18:00 | Tolusic 2026 | REJETÉE | dispo | H2 : réel mais plus petit que les coûts |
| 84 | Portage des devises | Lustig, Roussanov & Verdelhan 2014 (+ 8) | REJETÉE | dispo | `carry_fx` |
| 85 | Une devise baisse pendant ses propres heures | Breedon & Ranaldo, *JMCB* 2013 (version QMUL lue en entier le 2026-10-22) | ÉCARTÉE | dispo | EUR/USD vendu en séance européenne : Sharpe 1,3 net sur EBS 1997-2007 ; mesure la plus récente sur NOS futures (Krohn et al. 1999-2018, coûts CME complets) : Sharpe 0,61 → t attendu ≈ 2,0 < 3 ; la BCE publie son fixing à 16:00 depuis 07/2016 |
| 86 | Momentum intraday des devises | Elaut et al. ; Seeck 2026 | REJETÉE | dispo | P1 ; Seeck conclut lui-même à une barrière de coûts |
| 87 | Cascades de stops sur chiffres ronds | Osler 2003, 2005 | REJETÉE | dispo | `fx_trois`, 6E 2 |
| 88 | Dollar valeur refuge (retournement de 2025) | Torul 2026 | ÉCARTÉE | — | épisode de 2025 seulement |
| 89 | Fixings et Gotobi sur 6C, 6S, 6N, 6M | Krohn, Mueller & Whelan, *JF* 2024 (version de juillet 2022 lue, tableaux I, II, IV, V) | ÉCARTÉE le 2026-10-25 | Databento | effet par devise du papier (1999-2019, pb par jour, 2 allers-retours) : retournement de Tokyo CAD 3,02 (é.-t. 20,5), CHF 2,49 (25,1), NZD 5,68 (44,4) ; d'Europe CAD 2,31, CHF 4,79 (51,1), NZD 2,16. Coûts : 6C 4,1 pb, 6S 2,5, 6N 5,0 par jour. t attendu sur 10 ans au mieux **2,29** (CHF Europe, effet complet) ; avec la baisse mesurée sur 2014-2019 (tableau II : Tokyo × 0,35, Europe × 0,6) au mieux 0,38 → aucun essai. MXN absent du papier ; Gotobi propre à ces devises : aucune mesure (tableau V : le retournement de Tokyo faiblit les jours fériés japonais, sans détail gotobi) ; Gotobi déjà rejeté sur 6E, 6B, 6A (H9) |

## 6. Crypto (MBT, MET ; comptant Binance 2017-2026)

| # | Hypothèse | Source | Statut | Données | Résultat / remarque |
|---|---|---|---|---|---|
| 90 | Tendance Donchian à 9 horizons | Zarattini, Pagani & Barbon 2025 | REJETÉE ; lu en entier | dispo | R1 0,42 ; aucune version courte ; version testée = celle du papier rendue conforme (pas de retest) |
| 91 | Boombitch sur le micro bitcoin | H5 | FIABLE, NON RETENUE | dispo | Sharpe 1,56, Welch 1,39 (critère 12) |
| 92 | Fenêtres courtes du bitcoin | Padyšák & Vojtko 2022 ; Wen et al. 2022 | REJETÉE, À RELIRE | dispo | H12 −2,18 et −0,70 ; testé sur résumé |
| 93 | Boombitch sur le micro ether | H5 | REJETÉE | dispo | −0,74 (coûts) |
| 94 | Portage crypto (base perpétuels) | Schmeling, Schrimpf & Todorov, BRI 2023 | ÉCARTÉE | — | demande des perpétuels, non jouable en prop |
| 95 | Flux des ETF bitcoin | Mazur & Polyzos 2025 | ÉCARTÉE | — | expliquent des niveaux, pas des rendements |
| 96 | Bitcoin selon la séance (Asie / États-Unis) | blogs | ÉCARTÉE | — | aucune règle publiée |
| 97 | Effet « quart d'heure » de la crypto | arXiv 2607.09426 | ÉCARTÉE | — | ~0,4 pb brut, sous les frais |

**Crible Semantic Scholar crypto du 2026-10-22** : 29 requêtes, 446 résumés 2021-2026, 53 sur des effets intraday ; n° 158 à 161. Second crible (26 requêtes : momentum, tendance, calendrier, volume, options, attention) : 173 résumés nouveaux, 90 retenus au filtre, presque tous en coupe transversale, à horizon de semaines ou en apprentissage automatique ; n° 162 à 164.

**Crible arXiv crypto du 2026-10-22 (aucun essai).** API publique d'arXiv, 24 requêtes (bitcoin / crypto × horizons
courts) : 1 095 articles, 525 en finance ou économie, 219 sans apprentissage automatique ; titres lus, 12 résumés lus,
1 texte complet. Coûts du critère 8 : **MBT** (0,1 BTC ≈ 8 360 $, tick 0,50 $) ≈ 3 $ par côté, soit ~7 pb l'aller-retour ;
**MET** (0,1 ETH ≈ 270 $, tick 0,05 $) ≈ 2,55 $ par côté, soit ~190 pb l'aller-retour : **l'ether est injouable en micro**.

| # | Hypothèse | Source | Statut | Données | Résultat / remarque |
|---|---|---|---|---|---|
| 128 | Le déséquilibre d'ordres des 10 premières secondes de chaque quart d'heure prédit le rendement des 4 à 12 h suivantes | Kim & Hansen 2026 (arXiv 2607.09426, UNC ; lu en entier) | ÉCARTÉE | trades agrégés Binance à la seconde (publics, non téléchargés ; nos barres 1 min n'ont pas le sens de l'agresseur) | aucune règle de trading ni coût dans le papier ; effet en écart interquartile ≈ 18 pb à 8 h et ≈ 26 pb à 12 h, porté surtout par des indicateurs techniques ; échantillon 2021-2024 seulement (critère 11 impossible) ; puissance estimée : ~4 pb nets par trade de 12 h, écart-type ~210 pb, ~6 500 trades → t ≈ 1,5 < 3 |
| 129 | Retour à la moyenne sur 15 min (contre la bougie précédente) | Kitron & Wengrowicz 2026 (arXiv 2608.21888) | ÉCARTÉE | dispo | gain brut 1,3 pb contre 5 pb de coûts selon les auteurs eux-mêmes |
| 130 | Hausse du bitcoin 5 à 30 min après une création de Tether | Saggu 2025 (arXiv 2501.05232) | ÉCARTÉE | historique des créations (Whale Alert) | échantillon 2014-2021 ; famille de Griffin & Shams (n° 108) |
| 131 | Flux on-chain (entrées nettes de Tether sur les plateformes) → rendements à 1-6 h | Chi, Chu & Hao 2024 (arXiv 2411.06327) | ÉCARTÉE | flux on-chain (payants) | données indisponibles gratuitement |
| 132 | Retournement après le règlement des contrats Polymarket de 5 min | Dai, Jia & Yu 2026 (arXiv 2606.31675) | ÉCARTÉE | — | mouvements de quelques points de base, sous les coûts du MBT |

Le reste : volatilité, modèles, DeFi, marchés de prédiction, rythmes d'activité sans effet de prix (Härdle et al. 2020 ;
Wątorek et al. 2023). **Aucune hypothèse crypto nouvelle ne passe les critères 1 à 6.**

**Crible arXiv élargi à tous nos marchés (2026-10-22, aucun essai).** Deux collectes de plus sur les catégories q-fin et
econ : 50 expressions intraday (309 articles), puis 88 croisements marché × effet (917 articles) ; au total, avec la
collecte crypto, ~2 300 articles arXiv. Après filtre (nos marchés, horizon intraday ou d'annonce, effet de prix, sans
apprentissage automatique ni marchés émergents) : 47 résumés lus. arXiv q-fin publie surtout de la théorie, des modèles
de volatilité ou de carnet d'ordres et de l'apprentissage automatique ; les rares effets de prix sont déjà testés
(« drift burst » de Christensen, Oomen & Renò → M2 ; dérive de nuit → n° 7 ; Mesfin 2026 → mise en garde ORB).

| # | Hypothèse | Source | Statut | Données | Résultat / remarque |
|---|---|---|---|---|---|
| 133 | Le sentiment financier de la nuit sur Twitter prévoit le rendement des actions du lendemain | Adams, Ajello, Silva & Vazquez-Grande, Réserve fédérale, FEDS 2023-034 (arXiv 2305.16164) | ÉCARTÉE | indice non publié en série ; données Twitter (X) fermées depuis 2023 | impossible de le reconstruire, de le tester sur 2023-2026 ou de le suivre en direct |

**Conclusion arXiv : aucune hypothèse fiable nouvelle, pour aucun de nos marchés.**

## 7. Produits agricoles (ZC, ZS, ZW) — tout demande Databento

| # | Hypothèse | Source | Statut | Données | Résultat / remarque |
|---|---|---|---|---|---|
| 98 | Rapports USDA (WASDE, Grain Stocks) | Adjemian ; Karali & Park ; Silveira et al., *JFM* | ÉCARTÉE | — | effet sur la volatilité, pas de sens prévisible |
| 99 | Prime de volatilité des options agricoles autour du WASDE | He & Bian 2025 | ÉCARTÉE | — | options, pas futures |

## 7 bis. Ajouts du 2026-10-22 (deuxième recherche : échéances, flux mécaniques, politique monétaire, matières premières)

| # | Hypothèse | Source | Statut | Données | Résultat / remarque |
|---|---|---|---|---|---|
| 100 | Les futures S&P sont « aimantés » vers le prix d'exercice le jour d'échéance des options sur futures | Golez & Jackwerth, *JFE* 2012 | **OUVERTE** ★ | positions d'options par prix d'exercice (CME, payant) | échantillon d'avant les options quotidiennes (0DTE) : aucune confirmation récente trouvée |
| 101 | « Momentum monétaire » : les actions dérivent pendant ~25 jours avant le FOMC dans le sens de la surprise lue sur les futures fed funds | Neuhierl & Weber, NBER w24748, 2018 (non publié) | ÉCARTÉE le 2026-10-25 | Databento (ZQ) | échantillon 1994-2009 (critère 2) ; tenue de plusieurs semaines : la version « de jour seulement » n'est mesurée par personne (critère 6), comme les n° 54 et 166 |
| 102 | Basis-momentum : le momentum de la pente de la courbe des futures prévoit les primes des matières premières | Boons & Porras Prado, *JF* 2019 | **OUVERTE** ★ | Databento (~20 matières premières, 1er et 2e contrats) | papier solide, mais portefeuille de ~20 contrats : intenable dans un compte prop de 50 000 $ ; pas de réplication hors échantillon trouvée |
| 103 | Portage (« carry ») des matières premières | Koijen, Moskowitz, Pedersen & Vrugt, *JFE* 2018 | **OUVERTE** ★ | Databento | même limite de taille ; le portage des devises est déjà rejeté (`carry_fx`) |
| 104 | Bitcoin autour de l'échéance mensuelle des futures CME (volume, volatilité, rendements) | Blasco, Corredor & Satrústegui, *IREF* 2023 (poster des auteurs lu le 2026-10-22 ; article payant) | ÉCARTÉE | dispo | les auteurs : effet sur les rendements « sans schéma commun » (576 modèles) ; Quantpedia : sens inversé après 2021 ; aucun effet stable à tester |
| 105 | Pétrole : pression vendeuse l'avant-dernier jour avant l'échéance du WTI | Ge, Kang, Tang & Yang, AEA 2023 (document de conférence) | **OUVERTE** ★ | Databento (contrats individuels : notre série continue a déjà roulé) | construit sur avril 2020 (prix négatifs) |
| 106 | Le dollar monte au comptant en fin de trimestre (manque de dollars des banques) | BRI WP 836 ; présentations BCE 2020 et 2024 | ÉCARTÉE | — | l'effet est sur la base des swaps et l'écart achat-vente, pas sur le sens du cours |
| 107 | Rééquilibrage des fonds à volatilité cible en fin de séance | aucune source académique | ÉCARTÉE | — | seuls les ETF à levier (n° 15) et les ETP VIX (n° 16) sont documentés |
| 108 | Émissions de Tether → hausse du bitcoin | Griffin & Shams, *JF* 2020 | ÉCARTÉE | — | effet de 2017-2018 seulement |
| 109 | Rééquilibrage des ETP VIX → rendement de fin de séance des futures VIX | *J. Futures Markets* | ÉCARTÉE | — | futures VIX non proposés par les prop firms ; effet en baisse avec le temps selon l'article ; réexaminé le 2026-10-25 (tous marchés) : même mur de frais que le n° 141 (~59 pb l'aller-retour sur VX) ; ÉCARTÉE |

## 7 ter. Recherche de pistes ★★★ du 2026-10-22 (aucune trouvée)

Directions explorées : gaz et prévisions météo, nuit sur les taux et les matières premières, inflation (CPI), flux de
dividendes des ETF japonais, saisonnalité intraday récente dans *JFE* / *RFS* / *Management Science*.

| # | Hypothèse | Source | Statut | Données | Résultat / remarque |
|---|---|---|---|---|---|
| 110 | Hausse des actions AVANT l'emploi, l'ISM et le PIB, plus forte quand l'incertitude (VIX) monte avant la publication | Hu, Pan, Wang & Zhu, *JFE* 2022 (lu en entier le 2026-10-22) | ÉCARTÉE | dispo | effet sur futures S&P, veille 16:00 → 5 min avant : 2012-2018 +6,98 pb par annonce (NFP, ISM, PIB), écart-type ~57 pb ; net de ~1,1 pb de coûts, ~380 annonces 2016-2026 → t attendu ≈ 2,0 ; version « 20 % de plus forte hausse du VIX sur 6 jours » (+16,95 pb, 1994-2018) → t ≈ 1,7 ; avec le FOMC (+7,02 pb) → t ≈ 2,2 : tous < 3, aucun essai |
| 111 | Réaction asymétrique d'ES aux surprises du CPI (2021-2025) | *Applied Economics Letters* 2026 | ÉCARTÉE | — | réaction APRÈS la publication, sens inconnu à l'avance |
| 112 | Gaz : réaction aux mises à jour des modèles météo (GFS, ECMWF) | articles de fournisseurs | ÉCARTÉE | — | aucun article académique ; prévisions météo à acheter |
| 113 | Ventes des ETF japonais avant leurs dividendes (juillet) | presse (Daiwa, Nomura) | ÉCARTÉE | — | aucune étude ; un événement par an |
| 114 | Les taux baissent pendant la séance asiatique | presse (Morgan Stanley cité par ETF Trends) | ÉCARTÉE | — | aucune étude (vérifié de nouveau le 2026-10-23) |
| 115 | Prime de nuit des matières premières (pétrole, cuivre) | aucune étude trouvée (seulement les marchés chinois) | ÉCARTÉE | — | l'or la nuit (n° 67) reste le seul cas documenté |

## 7 quater. Crible SSRN intraday du 2026-10-22 (articles déposés depuis le 2025-06-01)

Collecte Crossref (DOI SSRN 10.2139, 31 requêtes, 18 334 articles ; OpenAlex refuse désormais les requêtes sans clé au-delà
d'un petit budget quotidien). Après retrait des articles déjà au catalogue, filtre sur nos marchés ET un horizon intraday,
sans apprentissage automatique ni marchés émergents : 128 articles, presque tous hors sujet (le moteur de Crossref est
large). Retenus pour lecture du résumé :

| # | Hypothèse | Source | Statut | Données | Résultat / remarque |
|---|---|---|---|---|---|
| 116 | Le dénouement des couvertures des options S&P qui expirent pousse les futures dans les 30 min avant l'échéance | Garcia-Ares, Vasquez, Pearson et al. 2026 (SSRN 7330098 ; Pearson, auteur reconnu) | **OUVERTE** ★★ | positions des teneurs de marché sur les options qui expirent (CBOE Open-Close, payant) | le sens de la poussée dépend de ces positions : sans elles, pas de règle |
| 117 | Après le FOMC, les actions suivent le ton du communiqué (≈ 12 pb en 2 h par écart-type de ton) | Boucher, Gagnon & Power 2026 (SSRN 7213059) | ÉCARTÉE | dispo + score de ton | ~85 réunions 2016-2026, écart-type ~70 pb sur 2 h → t attendu ≈ 1,6 |
| 118 | Retournement de l'ouverture sur YM, attribué aux options 0DTE | Ladia 2026 (SSRN 7124578) | ÉCARTÉE | dispo | auteur seul, 194 trades depuis 2023, perdant avant 2023 (critères 1 et 11) |
| 119 | « Murs » de gamma (GEX) comme supports et résistances, SPY et NDX | Popovici 2026 ; Cenobar & Fazeli 2026 (pré-enregistrés) | ÉCARTÉE | — | les deux tests concluent à l'absence d'effet |
| 120 | Échéances des options S&P : de l'aimantation à l'amplification depuis 2016 | Elms 2026 (SSRN 6564078) | ÉCARTÉE | positions d'options (payant) | auteur seul ; recoupe le n° 100 |
| 121 | Déséquilibre d'ordres au meilleur prix, rachat après une forte baisse | Rodas 2026 ; Dashyan 2026 | ÉCARTÉE | — | résultats négatifs publiés par leurs auteurs |

Conclusion du crible : aucune hypothèse intraday nouvelle jouable avec nos données ne passe les critères 1 à 6.

**Analyse des résumés (2026-10-22, à la demande de l'utilisateur).** Les 23 136 résumés (ancien catalogue + collecte
Crossref) ont été notés automatiquement (marché parmi les nôtres, horizon intraday ou de séance, effet exploitable,
chiffres, source ; malus pour l'apprentissage automatique, les marchés émergents et les sujets hors trading) : 458
passent les conditions minimales, les 250 mieux notés ont été lus un par un. Constat : presque tous sont des
prépublications de 2026 d'auteurs seuls (critère 1), des tests de méthodes de particuliers (ICT, Gann, Fibonacci, « Smart
Money », Market Profile), des résultats négatifs pré-enregistrés, ou des familles déjà testées. Ajouts :

| # | Hypothèse | Source | Statut | Données | Résultat / remarque |
|---|---|---|---|---|---|
| 122 | **Contre-papier de l'ORB** : aucune variante simple de cassure d'ouverture ne survit aux coûts sur 9 futures américains en 16 ans (225 cases pré-enregistrées) | Fetna 2026 (SSRN 7428398) | — (résumé complet lu le 2026-10-22 ; texte bloqué par la vérification anti-robot de SSRN) | — | 2010-2026 (couvre la période du rejeu n° 49) ; 9 marchés × 2 ancres (9:30, 18:00) × 4 durées (5/15/30/60 min) × 3 sorties ; critère t ≥ 2,5 à 25 $ l'aller-retour ; 0 case sur 225 ; gain brut médian −0,01 tick par trade ; la plage de 5 min est la pire ; la meilleure case échoue au contrôle « ancre au hasard » (continuation de volatilité, pas d'information à l'ouverture). Notre ORB est différente sur trois points (filtre de volume, stop à 10 % de l'ATR, sortie à la clôture) et son gain brut est d'environ +0,33 R (~40 ticks) par trade : à vérifier dans le texte si ces règles sont dans la grille. **Contrôle « ancre au hasard » fait le 2026-10-22** (`nexus/perso/orb_ancre.py`, `resultats_orb_ancre.txt`, pas un essai) : l'ORB réelle (9:30, R moyen +0,182, Sharpe 0,92) bat 100 % des 200 tirages d'ancres entre 10:00 et 11:30 en R moyen et 99,5 % en Sharpe (médianes +0,032 et 0,25) ; idem entre 10:00 et 14:30. **Son avantage vient bien de l'ouverture** : la lecture de Fetna ne s'applique pas à notre version ; le rejeu 2010-2015 garde son sens |
| 123 | Asymétrie de la séance (ouverture, haut, bas) → séance suivante, en sens contraire | Valenti 2026 (SSRN 6074846) | ÉCARTÉE | dispo | auteur seul, SPY ; famille des retournements d'un jour déjà rejetée |
| 124 | Retour après une enchère ratée aux extrêmes de la zone de valeur (ES, NQ, ZN, GC) | Perry 2026 (SSRN 7106618) | ÉCARTÉE | dispo | même auteur que le n° 40, prépublication |
| 125 | Contre-pied du résidu de déséquilibre d'ordres sur 20 futures | Levander 2026 (SSRN 7245981) | ÉCARTÉE | déséquilibre d'ordres (carnet, payant) | auteur seul ; « fragile selon les régimes » d'après l'auteur |
| 126 | Une devise baisse pendant ses heures (16 devises, 2010-2015) | Zhang 2018 (SSRN 3138756) | ÉCARTÉE | dispo | même famille que n° 78 et 85 (puissance insuffisante sur futures) |
| 127 | Prime de nuit des actions conditionnée au sentiment | Vojtko & Hanicova 2021 (Quantpedia) | ÉCARTÉE | dispo | note de praticiens ; famille de la nuit déjà rejetée (n° 7, 42) |

Appuis indépendants trouvés pour nos stratégies retenues : Chuk 2026 (zone de bruit sur NQ, Sharpe 1,14 sur 2020-2026),
Delgado 2026 (réplication de « Beat the Market » jusqu'en 2026) ; et mises en garde : Paz 2026 (SPY après mai 2024 :
0,39).

## 7 quinquies. Autres marchés, recherche du 2026-10-22 (soir)

Crible : 124 résumés SSRN et arXiv sur d'autres marchés (argent, cuivre, gaz, Brent, taux, Nikkei, DAX, FTSE, VIX,
devises absentes, grains, bétail) et recherches ciblées sur le web. Presque tout était déjà inscrit (n° 12, 56, 58, 64,
70…). Crible complémentaire (Crossref) : tous les articles 2023-2026 de *J. Futures Markets*, *J. Commodity Markets*,
*J. Financial Markets*, *J. Empirical Finance* et *J. Banking & Finance* (2 393 articles, 28 sur des rendements
intraday hors marchés émergents) : rien de jouable en prop firm. Nouveautés, toutes écartées à la lecture, aucun
essai :

| # | Hypothèse | Source | Statut | Données | Résultat / raison |
|---|---|---|---|---|---|
| 134 | La première demi-heure américaine annonce la dernière demi-heure des autres bourses (Europe le jour même, Asie le lendemain) | Li, Sakkas & Urquhart, *J. Financial Markets* 2022 (version acceptée lue en entier) | ÉCARTÉE | dispo (CFD HistData) | indices au comptant, 2005-2017, sans coûts ; pente significative dans 8 pays sur 15 seulement ; aucun chiffre net jouable pour le calcul de puissance (critères 2 et 6) |
| 135 | Les rendements de nuit d'un autre indice prévoient l'écart d'ouverture du matin | Si, Nadarajah & Chen, *Borsa Istanbul Review* 2026 | ÉCARTÉE | — | prévoit l'écart des indices au comptant ; les futures cotent la nuit et contiennent déjà cet écart : rien à jouer |
| 136 | L'argent baisse d'environ 12 pb autour du fixing de Londres | document de travail NYU Stern 2014 (« Any Silver Linings ») | ÉCARTÉE | dispo (XAGUSD) | ancien fixing téléphonique, remplacé par l'enchère LBMA en 08/2014 ; même cas que l'or (n° 72) |
| 137 | Le S&P se retourne après le FOMC (mouvement d'avant l'annonce effacé ensuite) | Baglioni & Ribeiro 2022 (SSRN 4182628, non publié) | ÉCARTÉE | dispo | même famille que le n° 9, déjà testée et rejetée (lot P1, « retournement FOMC ») |
| 138 | Les taux surréagissent aux annonces très suivies (CPI 2021-2023), puis se retournent | Kroner, Réserve fédérale, FEDS 2025-022 (lu) | ÉCARTÉE | Databento | le retournement prend plusieurs jours (pas intraday) ; la mesure d'attention n'est pas publiée en série |
| 140 | Le bitcoin suit l'horloge de New York depuis les ETF au comptant (fenêtre 15:00-16:00) | Schmidt & Kraft, *Finance Research Letters* 2026 | ÉCARTÉE | dispo (Binance) | effet sur le volume seulement : aucun effet horaire sur le rendement après correction des tests multiples |
| 141 | Momentum intraday des futures VIX | Huang, Tsai, Weng & Yang, *J. Banking & Finance* 2023 | ÉCARTÉE | — | futures VIX non proposés par les prop firms (comme le n° 109) ; **réexaminé le 2026-10-25 (tous marchés permis)** : texte payant ; frais prohibitifs : tick du VX 0,05 point = 50 $ ≈ 28 pb d'un contrat à ~18 000 $ (VXM idem en proportion) → ~59 pb l'aller-retour, au-dessus de tout gain de dernière demi-heure plausible (même avec R² 2 % : ~17 pb brut) ; ÉCARTÉE |
| 139 | Momentum de fin de séance sur le café | Couleau, Trujillo-Barrera & Etienne, *J. Commodity Markets* 2025 | ÉCARTÉE | — | café coté sur ICE, pas proposé par les prop firms (CME seulement) ; **réexaminé le 2026-10-25 (tous marchés permis)** : version de conférence AAEA 2023 lue en entier (même équipe, mêmes données ICE 2010-2021) : aucune stratégie chiffrée ; R² 0,28 % (corrélation ≈ 0,05), la nuit + 1re demi-heure n'annonce la fin que en 2020-2021 (pandémie) ; gain brut d'une stratégie au signe ≈ 0,04 écart-type ≈ 2-3 pb contre ~7,6 pb de frais (tick 0,05 ¢ = 18,75 $ ≈ 3,3 pb par côté) → perdant net, ÉCARTÉE |

## 7 sexies. Carte des flux forcés (nouvelle méthode décidée le 2026-10-22 : partir du flux, puis chercher la preuve)

Un flux forcé = un acteur OBLIGÉ d'acheter ou de vendre à une heure ou une date connue d'avance. Déjà couverts dans ce
registre : fin de mois et 60/40 (n° 14), ETF à levier (15), ETP VIX (16, 109), enchère de clôture (17), quatre
sorcières (29), fixings de change et Gotobi (76-79, 89), roulement GSCI (61), adjudications et fin de mois du Trésor
(50, 52), couverture gamma (2, 116, 119), achats d'ETF de la Banque du Japon (36), reconstitution du Russell (46),
dérive de nuit des teneurs de marché (7).

| # | Flux forcé | Source | Statut | Données | Résultat / raison |
|---|---|---|---|---|---|
| 142 | Rééquilibrage annuel des poids du S&P GSCI / BCOM (janvier, 5 jours, sens connu dès novembre) | Yan, Irwin & Sanders, *J. Commodity Markets* 2022 (SSRN 3715726) | ÉCARTÉE le 2026-10-23 : contredite par Yan & Irwin 2016 et 2017 (AgEcon 285846, 258504 : rendements nuls pendant le rééquilibrage, aucun lien causal) | dispo (CL, GC) ; Databento pour les autres | texte non lu (SSRN) ; 1 événement par an et par contrat → ~20 cas sur CL + GC (événement rare) ; tenue de plusieurs jours, à rendre intraday (fenêtre de règlement) ; la lignée Irwin conclut d'ordinaire à un faible impact des flux indiciels |
| 143 | Flux des CTA (suiveurs de tendance : positions déduites de règles connues) | aucune source académique (fournisseurs de données, arXiv 2405.12768 théorique) | ÉCARTÉE | — | critère 1 : aucune mesure publiée de l'effet sur les rendements |
| 145 | **Pic du 3e vendredi** : la couverture des teneurs de marché pousse les indices la nuit avant le règlement des options (SOQ), rendu avant midi | Baltussen, Terstegge & Whelan, « The Derivative Payoff Bias », 2024 (SSRN 4562800, texte complet lu) | REJETÉE (essai n° 432) | dispo | version trimestrielle seule (puissance) : ES +33,8 pb net mais +92 pb en 2016-2020 et −13 pb en 2021-2026, Sharpe 0,41, déflaté 0,17 ; NQ, YM pareils ; éteint depuis les options du jour (0DTE) (`tiers_vendredi`) |
| 146 | Japon : ventes des ETF pour payer leurs dividendes (juillet) ; pression avant le règlement mensuel du Nikkei (SQ, 2e vendredi) | presse (Reuters), note d'Optiver | ÉCARTÉE | Databento (NKD) | aucune étude sérieuse mesurant l'effet sur les prix |
| 147 | Europe : échéances et enchères de clôture de l'Euro Stoxx 50, du DAX, du Bund | mémoires (Aalto 2010), produits Eurex | ÉCARTÉE | — | aucune étude récente ; contrats Eurex absents des prop firms CME |
| 148 | Crypto : retournement intraday autour de l'échéance des options Deribit (vendredi 8:00 UTC) | Weiss, Gaudiosi, Zhou & Webb, *Finance Research Letters* 2026 (texte complet lu le 2026-10-22) | ÉCARTÉE | intérêt ouvert par prix d'exercice et sens des transactions Deribit (payants) | 2021-2023 seulement ; **rien sur l'échantillon complet** (« not evident for the full sample ») ; l'effet n'existe que les jours du décile supérieur d'intérêt ouvert à la monnaie ET de gamma négatif (interaction triple −1,03, t −2,97 ; mouvement d'avant 8:00 plus bas de 0,17 %) ; calcul de puissance (17 pb rendus, écart-type 121 pb après l'échéance, coûts MBT 7 pb, 12 à 35 cas par an sur 7 ans) : t attendu 0,8 à 1,3 → aucun essai |
| 149 | Crypto : mouvements de prix aux heures de financement des perpétuels (0:00, 8:00, 16:00 UTC) | aucune étude (arXiv 2212.06888 décrit le mécanisme seulement) | ÉCARTÉE | dispo | critère 1 : aucun effet de prix mesuré |
| 150 | Crypto : rebond après les cascades de liquidations forcées | Garcia Seuma 2026 (arXiv 2607.27070, 2608.03616) ; Lim (SSRN 6579278) | ÉCARTÉE | liquidations (payant) | 7 cascades seulement ; aucun rebond mesuré ; préprints |
| 151 | Crypto : échéance mensuelle des futures bitcoin CME | Vojtko & Dujava 2024 (Quantpedia, SSRN 4779669) | ÉCARTÉE | dispo | note de praticiens (critère 1) ; CME en continu 24/7 depuis mai 2026 |
| 152 | Crypto : la première demi-heure (volume) annonce la dernière demi-heure (17:00 ET) | Shen, Urquhart & Wang, *Financial Review* 2022 (version acceptée lue en entier) | ÉCARTÉE | dispo | 2013-2020, plateformes au comptant ; point mort de la meilleure version 3 à 10 pb, contre ~7 pb de frais sur le MBT → gain net ≈ 0 ; même famille que H12 (rejetée) |
| 153 | Crypto : le bitcoin se retourne dans la journée après les grands mouvements des bourses mondiales (surréaction) | Jia, Shen & Zhang, *Int. Review of Economics & Finance* 2024 | **OUVERTE** ★ | dispo (BTC Binance + ES) | texte payant : seule la phrase du résumé est connue (règle, seuil et effet inconnus) ; titre exact « Bitcoin market reactions to large price swings of international stock markets », *IREF* 90, 2024 : vérifié le 2026-10-25, accès fermé, aucune copie libre (OpenAlex) |
| 154 | Crypto : rendements positifs aux minutes 0, 15, 30 et 45 de chaque heure (« turn of the candle ») | Shanaev, Vasenin & Stepanov, *Heliyon* 2023 (lu) | ÉCARTÉE | dispo | ~0,6 pb par minute contre ~7 pb de frais (même famille que le n° 97) ; apparu en 2020, déjà « moins prononcé » en 2022 |
| 155 | Crypto : prime de la séance asiatique (achat la nuit en Asie) | mémoire de master (Aalto, 2026) ; Padyšák & Vojtko 2022 | ÉCARTÉE | dispo | pas une revue ; la prime asiatique disparaît après les ETF au comptant (2024) ; heures de Padyšák-Vojtko déjà rejetées (H12) |
| 156 | **Crypto : retournement sur 2 h après un mouvement de 3 écarts-types** | De Nicola, *Ledger* 2021 (texte complet lu) | REJETÉE (essai n° 433) | dispo (Binance) | papier 2015-2018 : +0,49 % brut ; chez nous 2019-2026 (hors échantillon) : +9,4 pb brut (t 1,2), MBT −21,5 pb net, Sharpe −0,95 ; BTC +3,7 pb net, Sharpe 0,15 (`crypto_retour`) |
| 157 | Crypto : momentum le jour d'un rendement anormal et le lendemain | Caporale & Plastun, *Financial Markets and Portfolio Management* 2020 (lu) | ÉCARTÉE | dispo | 2015-2019 seulement, paramètres de temps estimés sur l'échantillon ; contre-pied pour le bitcoin dans les hausses : résultats mêlés (critère 2) |
| 158 | Crypto : rebond 6 à 24 h après une forte baisse sur une heure (surréaction aux mauvaises nouvelles) | Miralles-Quirós & Miralles-Quirós, *Journal of Applied Economics* 2022 (texte complet lu le 2026-10-22) | ÉCARTÉE | dispo (Binance) | Kraken 2016-2021, seuils fixes, sans frais ni témoin (la hausse générale du bitcoin, ~0,2 %/jour, n'est pas retirée) ; à 6 h (tenue la plus longue compatible prop) : +0,43 % (baisse ≥ 1,5 %), +0,75 % (≥ 2,5 %), +1,47 % (≥ 3,5 %) ; calcul de puissance (écart-type à 6 h 330-520 pb et cas mesurés sur nos données, frais MBT réels 32-45 pb) : t attendu 0,8 à 1,6 (1,6 à 1,9 depuis 05/2021) → aucun essai |
| 159 | Crypto : rendements du bitcoin après des taux de financement extrêmes des perpétuels (15 min à 24 h) | revue sans comité reconnu (2026) | ÉCARTÉE | dispo | critère 1 |
| 160 | Crypto : effets du vendredi et de certaines heures | *J. Applied Finance & Banking* 2024 ; *Oeconomia Copernicana* 2022 (heures, 2016-2021) | ÉCARTÉE | dispo | sources faibles ; mêmes familles que H12 et le n° 155, déjà rejetées |
| 161 | Crypto : la variance réalisée prédit le rendement des semaines suivantes (coupe transversale) | *JFQA* 2024 | ÉCARTÉE | — | horizon de plusieurs semaines, panier de dizaines de cryptos : ni intraday, ni jouable en prop |
| 162 | Crypto : contre-pied après 3 bougies d'une minute dans le même sens sur les futures bitcoin CME, sortie sur objectif | *Applied Economics Letters* 2021 | ÉCARTÉE | dispo | lettre courte, mouvements d'une minute (quelques pb) contre ~7 pb de frais du MBT ; famille des n° 97, 129, 154 |
| 163 | Crypto : le retournement à court terme rémunère la fourniture de liquidité (paires peu actives) | *J. Banking & Finance* 2022 | ÉCARTÉE | — | coupe transversale de dizaines de paires ; l'effet est dans les petites cryptos, pas le bitcoin |
| 164 | Crypto : moyennes mobiles à longueur variable sur les futures bitcoin (« carte de chaleur ») | *Heliyon* 2023 | ÉCARTÉE | dispo | choisir la meilleure case d'une carte de chaleur = surajustement ; pas d'effet mesuré hors échantillon |
| 144 | Achats de fonds étrangers des particuliers japonais (NISA) → ventes de yens | notes de banques (MUFG), presse | ÉCARTÉE | dispo (6J) | aucune source sérieuse sur l'heure ou le jour ; le jour de paie (le 25) est déjà un jour Gotobi (n° 76) |

## 7 septies. Recherche continue du 2026-10-24 (thèmes absents du registre)

Thèmes cherchés : résultats des grandes entreprises, discours de la Fed, inscriptions au chômage, échéance des options
sur l'or et le pétrole, changement d'heure, jour de paie, rachats d'actions, fin d'exercice japonaise, semaine d'échéance.

Crible des grandes revues du 2026-10-24 (Crossref) : tous les articles publiés depuis 2022 dans *J. Finance*, *JFE*,
*RFS*, *JFQA*, *Management Science*, *Review of Finance*, *RAPS*, *J. Financial Econometrics*, *Financial Analysts J.*,
*J. Portfolio Management*, *Quantitative Finance*, *J. Monetary Economics*, *J. International Money and Finance* et
*Review of Corporate Finance Studies* (8 197 articles ; 277 retenus par mots clés : intraday, nuit, heure, futures,
annonce, fixing, échéance, flux…). Les seuls articles sur des rendements intraday d'indices, de devises ou de matières
premières étaient déjà inscrits (n° 7, 78, 110, 170, 172, 191) ; nouveautés : n° 200-203, toutes écartées.
Crible arXiv du 2026-10-24 (finance quantitative et économétrie, déposés depuis 2025, mots clés intraday, nuit, heure,
annonce, E-mini) : 30 articles, presque tous de modélisation de la volatilité ou d'apprentissage automatique ;
nouveautés n° 221-222, écartées ; Mesfin 2026 (aucun signal de momentum intraday sur MNQ 2021-2025) était déjà noté.

| # | Hypothèse | Source | Statut | Données | Résultat / raison |
|---|---|---|---|---|---|
| 191 | **Le S&P monte dans les 24 h avant les grappes de résultats publiés après la clôture par les entreprises les plus médiatisées** (3 jours par trimestre, en janvier, avril, juillet, octobre) | Chen, Cohen & Wang, « Famous Firms, Earnings Clusters, and the Stock Market », 2021-2022 (SSRN 3685452, NBER AP 2020 ; texte complet lu, versions de 05/2021 et 11/2021) ; réplique : Da, Hua, Hung & Peng, *Management Science* 2024-2025 (lu en entier) | **OUVERTE** ★★ | horaires des résultats : gratuits (8-K item 2.02 de data.sec.gov, déjà utilisés par `nexus/perso/edgar.py`, accord du 2026-10-20 ; il faudrait la liste des sociétés du S&P 500 et leurs CIK) ; nombre d'articles Dow Jones de l'année d'avant par entreprise : Factiva, **payant** (seul blocage) | 1999-2018 : +34,3 pb de clôture à clôture (t 4,01, 240 cas), dont +11,5 pb la nuit (t 2,13) et +23,0 pb de 9:30 à 16:00 (t 3,17) ; rien avant les grappes du matin (témoin naturel) ; écart-type du jour 1,12 % ; tient sur les deux décennies ; calendrier ex ante 2006-2018 : +32,8 pb (t 3,32) ; 30 pb sur 34 rendus en 3 jours. Grappes pesées par la capitalisation (seule mesure gratuite) : +17,6 pb (t 1,97) ; réplique Da et al. 2004-2019, 4 jours par trimestre pesés par la capitalisation : +17 à +21 pb, nul quand l'attention des particuliers est basse. Aucune preuve après 2019 (critère 2). Puissance (coût ES 1,55 pb, 12 cas par an sur 2016-2026 = 127 cas) : version médiatisée 18:00 → 16:00 t 3,29 ; partie 9:30-16:00 seule t 2,41 ; version capitalisation (16 cas par an, 170 cas) t 1,82 → testable seulement avec les comptes d'articles payants. **Substitut gratuit vérifié le 2026-10-25** : l'API DOC de GDELT donne le nombre d'articles par jour et par nom d'entreprise, mais seulement depuis le 01/01/2017 (essai : « Netflix », janvier 2017 ; une requête toutes les 5 s) ; avec le classement de l'année d'avant, les grappes commencent en 2018 : 105 cas, t attendu 2,99 (calendrier ex ante 2,86) → sous 3, on ne teste pas ; et GDELT (toute la presse web) n'est pas la mesure du papier (articles Dow Jones). Remonter à 2015 demanderait les fichiers bruts du GKG (plusieurs centaines de Go) |
| 192 | Les discours du président de la Fed font bouger les indices dans un sens prévisible | Rosa, *Int. J. Central Banking* 2016 (2001-2012) ; Narain & Sangani, *IJCB* 2026 (conférences de presse) | ÉCARTÉE | dispo | effet sur la volatilité et le volume seulement, le sens dépend du contenu (inconnu avant) ; la dérive avant le FOMC est déjà rejetée (n° 9) |
| 193 | Les futures de l'or et du pétrole sont « aimantés » vers les gros prix d'exercice le jour d'échéance de leurs options | aucune étude (seulement le S&P : Golez & Jackwerth, n° 100) | ÉCARTÉE | — | critère 1 ; il faudrait en plus l'intérêt ouvert par prix d'exercice (payant) |
| 194 | Les indices baissent après le changement d'heure | Gregory-Allen, Jacobsen & Marquering 2010 (22 pays, 1966-2005) ; Mugerman, Yidov & Wiener 2020 | ÉCARTÉE | dispo | aucun effet fiable sur 22 pays ; l'effet contraire n'existe que sur de petits marchés ; 2 cas par an |
| 195 | Dérive des indices avant les inscriptions au chômage (jeudi 8:30) | aucune étude | ÉCARTÉE | dispo | critère 1 ; même famille que le n° 12 (dérive avant l'ISM et l'emploi, rejetée) |
| 196 | Le S&P monte le 16 du mois et les 1er-2 (versements des salaires par quinzaine dans les plans de retraite) | Ma & Pratt 2017 (SSRN, non publié) ; revue Alpha Architect 2019 | ÉCARTÉE | dispo | source faible (critère 1) ; ~14 pb par jour le 16 sur 1952-2018 ; puissance (127 cas sur 2016-2026, écart-type 1,12 %, coût ES 1,55 pb) : t ≈ 1,25 ; le tour de mois est déjà rejeté (n° 13) |
| 197 | Les indices baissent pendant les fenêtres où les entreprises ne peuvent pas racheter leurs actions (avant les résultats) | commentaires de courtiers (LPL), blogs | ÉCARTÉE | dispo | critère 1 ; le seul test chiffré (Hedge Fund Alpha) ne trouve rien ; les rachats continuent par plans automatiques (10b5-1) |
| 198 | Le yen monte fin mars (rapatriement de l'exercice fiscal japonais) | notes de banques (MUFG, Standard Chartered 2009, ANZ 2012, Nomura 2018) | ÉCARTÉE | dispo (6J) | critère 1 ; les tests des banques elles-mêmes ne trouvent pas d'effet fiable (Nomura : « aucune saisonnalité en mars ») ; un cas par an |
| 199 | Les actions montent pendant la semaine d'échéance mensuelle des options | Stivers & Sun, *J. Banking & Finance* 2013 (actions du S&P 100, avant 2010) | ÉCARTÉE | dispo | ancien, sans confirmation récente (critère 2) ; praticiens : effet affaibli depuis 2020 ; puissance (~6 pb par séance, 636 séances) : t ≈ 1,1 ; famille du n° 145 (3e vendredi, rejetée) |
| 200 | La dérive d'avant le FOMC vient du désaccord des investisseurs qui cessent de s'informer juste avant l'annonce | Cocoma, *JFQA* 2025 | ÉCARTÉE | dispo | modèle théorique : aucune règle nouvelle ; la dérive d'avant le FOMC est déjà rejetée sur nos données (n° 9) |
| 201 | L'asymétrie et les queues implicites des options avant le FOMC prévoient le rendement de la semaine d'après | Jacobs, Ke & Pan, *JFQA* 2025 | ÉCARTÉE | moments implicites des options (OptionMetrics, payant) | horizon d'une semaine (pas intraday) ; 8 FOMC par an ; famille FOMC rejetée (n° 9) |
| 202 | Le rééquilibrage des ETF (levier, échéances, flux) déforme les futures du VIX et des matières premières | Todorov, *Review of Finance* 2023 | ÉCARTÉE | — | effet surtout sur les futures du VIX (non proposés par les prop firms, comme les n° 16 et 109) ; partie matières premières = roulement (n° 61) |
| 203 | Les conseils de « market timing » suivis par les fonds de pension chiliens font bouger le peso | Aldunate, Da, Larrain & Sialm, *JFE* 2025 | ÉCARTÉE | — | peso chilien : contrat absent ; réexaminé le 2026-10-25 (tous marchés) : effet lié aux conseils de « Felices y Forrados » (2011-2020), freinés par les règles chiliennes de changement de fonds ; aucun future liquide sur le peso chilien jouable ; ÉCARTÉE |
| 204 | Les fonds à volatilité cible (« vol control ») rééquilibrent en fin de séance et prolongent le mouvement du jour | méthodologies S&P DJI, notes de praticiens (Salt Financial, Convex) | ÉCARTÉE | dispo | critère 1 : aucune mesure publiée de l'effet sur les futures ; momentum de fin de séance déjà testé (n° 2, gamma, rejeté ; n° 15, ETF à levier, rejeté) ; S1 capte déjà le momentum intraday |
| 205 | La couverture des garanties des contrats d'assurance-vie (rentes variables) pousse les futures d'indices en fin de séance | aucune étude d'impact (articles d'actuariat sur la couverture seulement) | ÉCARTÉE | dispo | critère 1 |
| 206 | Les fonds à date cible vendent les actions après une hausse (contre-tendance macro) | Parker, Schoar & Sun, *J. Finance* 2023 | ÉCARTÉE | dispo | horizon de quelques mois (pas intraday) ; leur version journalière (Harvey, Mazzoleni & Melone 2026) est déjà rejetée (n° 14) |
| 207 | Pression de clôture le jour des revues trimestrielles MSCI, puis retour | mémoire de master (Le Cap, marchés émergents), presse (Inde, 2026) | ÉCARTÉE | dispo | critère 1 ; effet sur les actions des émergents, rien sur les futures américains |
| 208 | Les produits à levier sur le VIX poussent les prix en fin de séance, effet rendu la nuit | *J. Banking & Finance* 2021 (« The market impact of predictable flows ») | ÉCARTÉE | — | futures du VIX non proposés par les prop firms (n° 16, 109) ; réexaminé le 2026-10-25 (tous marchés) : frais du VX ~59 pb l'aller-retour (n° 141) ; ÉCARTÉE |
| 209 | Les futures de la livre dérivent avant les chiffres britanniques (inflation, production, ventes au détail) | Kurov, Sancetta & Halova Wolfe, « Drift Begone! Release Policies and Preannouncement Informed Trading » (document de travail 2021-2022) | ÉCARTÉE | dispo (6B) | la dérive suit le signe de la surprise (inconnu avant, comme le n° 56) et s'est éteinte en 2017, quand l'accès anticipé des fonctionnaires a été supprimé |
| 210 | L'euro et la livre réagissent aux chiffres de la zone euro dans un sens prévisible | Evans & Speight (Cardiff, cours au comptant) | ÉCARTÉE | dispo (6E, 6B) | effet sur la volatilité ; la réaction se fait dans les 5 minutes qui suivent la publication, selon la surprise |
| 211 | Pression sur le prix de règlement du pétrole (fenêtre de clôture de 14:28-14:30 ET, ordres « au prix de règlement ») | dossiers de la CFTC (Optiver 2008, SHK 2013) | ÉCARTÉE | dispo (CL) | critère 1 : cas de manipulation, aucune étude d'un effet régulier |
| 212 | Le pétrole réagit au comptage des forages de Baker Hughes (vendredi 13:00 ET) | dépêches de presse (2015-2016) | ÉCARTÉE | dispo (CL) | critère 1 ; le sens dépend du chiffre (inconnu avant) ; réaction « plus faible ces derniers temps » |
| 213 | Les futures se retournent sur quelques minutes et suivent la tendance au-delà de quelques heures | Safari & Schmidhuber 2025 (arXiv 2501.16772, prépublication) | ÉCARTÉE | dispo | prépublication sans chiffre de gain net ; les deux côtés sont déjà couverts (retournement court : n° 28, 97, 129 ; momentum intraday : S1, ORB) |
| 214 | L'or réagit aux fortes baisses des actions (valeur refuge à 5 minutes) | *Finance Research Letters* 2019 (« The timing of the flight to gold ») | ÉCARTÉE | dispo (GC, ES) | la réaction est rapide (pas de retard exploitable) ; même famille que le n° 88 |
| 215 | Effets du jour de la semaine (lundi faible, rebond du mardi) | French 1980 et suite ; méta-analyse 2024 ; études du S&P 2013-2023 | ÉCARTÉE | dispo | publiés bien avant 2016 (critère 2) ; aucune trace sur le S&P de 2013 à 2023 ni de 2000 à 2024 ; les heures de fin de semaine sont déjà testées (n° 24, 30, 83) |
| 216 | La pente de la courbe du VIX annonce le rendement des futures S&P du lendemain | Johnson, *JFQA* 2017 ; Fassas 2012 (document de travail) | ÉCARTÉE | dispo (VIX, VIX3M gratuits) | Johnson prévoit les actifs de variance (VIX, swaps de variance), pas l'indice ; Fassas : aucun effet net le lendemain ; ancien (critère 2) |
| 217 | Le ratio puts / calls de tout le marché annonce le rendement de l'indice du lendemain | Pan & Poteshman, *RFS* 2006 (actions seulement) ; revues CXO 1995-2013 ; *JDQS* 2024 (Corée) | ÉCARTÉE | dispo (CBOE gratuit) | aucun effet sur les options d'indice (Pan & Poteshman) ; corrélations « très faibles » et de signe instable sur le SPY |
| 218 | Contre-papier de NQ 1-A : après 2016, le prix des sociétés se forme efficacement après leurs résultats publiés hors séance (pas de dérive exploitable) ; les résultats font aussi sauter le marché | Christensen, Timmermann & Veliyev 2026 (arXiv 2601.08962, « Warp Speed Price Moves ») | — (contre-papier) | — | aucune stratégie testée ; appuie le déflaté faible de NQ 1-A (0,32, n° 22) : pas de raison de la reprendre |
| 219 | Pétrole : la première demi-heure (9:30-10:00) annonce la suite de la séance, sauf après les chocs extrêmes | Wang, Bouri, Xu & Zhang, *Energy Economics* 2023 (ETF USO, 2008-2022) | ÉCARTÉE | dispo (CL) | aucune règle de trading ni gain chiffré ; momentum intraday du pétrole déjà rejeté (n° 62, Z1 −2,28) |
| 220 | Or : saisonnalité intraday des rendements (heures GMT) | Batten, Lucey, McGroarty, Peat & Urquhart, *PLoS ONE* 2017 (5 min, ~2000-2015) | ÉCARTÉE | dispo (GC) | données d'avant 2016 (critère 2) ; texte inaccessible (serveur hors ligne) ; heures de l'or déjà criblées (n° 67, 72, 176, 177) |
| 221 | L'E-mini S&P dépasse sa cible quand l'inflation (CPI, 8:30) déclenche une pause de cotation (« velocity logic »), puis revient | Winkelmann & Yao 2026 (arXiv 2603.22835, texte complet lu) | ÉCARTÉE | dispo (ES) | 14 cas sur 2020-2025 (événement rare, sous les 60 cas) ; le dépassement se joue en 5 à 30 secondes, invisible en barres d'une minute ; sur 10 minutes, l'écart n'est plus net |
| 222 | Le déséquilibre des ordres annonce les rendements à quelques minutes, plus fort autour des chiffres macro | Takahashi 2025 (arXiv 2508.06788) | ÉCARTÉE | carnet d'ordres (payant) | données absentes ; flux d'ordres déjà testé (`resultats_orderflow.txt`) |
| 223 | Le déséquilibre publié avant l'enchère d'ouverture (NYSE, Nasdaq) annonce les futures d'indices après 9:30 | aucune étude (mémoire de master sur la clôture ; Fung & Yu 2007 cité de seconde main) | ÉCARTÉE | messages de déséquilibre (payants) | critère 1 ; données absentes |

## 7 octies. Recherche continue du 2026-10-25

| # | Hypothèse | Source | Statut | Données | Résultat / raison |
|---|---|---|---|---|---|
| 224 | Les indices bougent dans un sens prévisible à la publication du compte rendu du FOMC (14:00, trois semaines après) | Kansoy 2022 (Warwick, document de travail, 2004-2017) ; étude de la Fed (volatilité et volume) ; Schaeffer's 2015 | ÉCARTÉE | dispo | effet sur la volatilité seulement, le sens dépend du texte ; rendement moyen nul le jour du compte rendu |
| 225 | Les indices réagissent au Beige Book (mercredi 14:00) | Zavodny & Ginther, *Southern Economic J.* 2005 | ÉCARTÉE | dispo | effet sur les taux seulement, et il disparaît une fois les autres chiffres pris en compte ; rien sur les actions |
| 226 | L'écart NQ - ES revient à sa moyenne dans la journée (paire) | forums de traders (NexusFi) | ÉCARTÉE | dispo | critère 1 ; les traders eux-mêmes disent que l'effet a disparu ; même famille que le n° 27 (YM - ES, rejetée) |
| 227 | Dérives autour de Jackson Hole, des élections américaines | — | ÉCARTÉE | dispo | événements rares (1 par an ou tous les 2 ans, moins de 15 cas en 10 ans) : aucune puissance |
| 228 | Le « gap » d'ouverture de 9:30 de l'ES se referme dans la séance | mémoire de master (Nova SBE 2022) ; blogs de traders | ÉCARTÉE | dispo | critère 1 ; le retour de la nuit au matin est déjà rejeté (n° 25, 169) |
| 229 | Cassure du plus haut ou du plus bas de la veille | indicateurs TradingView, blogs | ÉCARTÉE | dispo | critère 1 : aucune étude ; famille de l'ORB (cassures), déjà testée |
| 230 | Crypto : après le FOMC, le CPI et l'emploi, le bitcoin et l'ether continuent de réagir pendant 30 minutes (baisse quand la surprise fait monter les taux) | Kroner, Mohammed & Vega, Réserve fédérale, mars 2026 (connu par un résumé de seconde main) ; contre-papier : Fed de New York SR 1052 (2023 : bitcoin insensible aux annonces, 2017-2022) | **OUVERTE** ★ | dispo (MBT, Binance) + surprises (consensus payant, ou réaction des taux à reconstruire) | texte complet introuvable (critère 3 : l'idée attend) ; le sens dépend de la surprise ; réactions surtout sur la volatilité ; frais MBT ~7 pb à battre en 30 min ; vérifié le 2026-10-25 : absent des listes FEDS et IFDP 2026 de la Fed, résumé de seconde main supprimé (page 404) |
| 231 | L'ES continue dans le sens de la première minute après les chiffres de 8:30 | Kurov, Sancetta, Strasser & Halova Wolfe, *JFQA* 2019 (E-mini à la seconde, 2008-2014) | ÉCARTÉE | dispo | ajustement résiduel seulement dans les 5 minutes (quelques ticks), sous nos coûts ; rien au-delà |
| 232 | Le yen fait des mouvements brusques pendant les jours fériés japonais (Golden Week, Nouvel An), liquidité réduite | presse (Reuters, Bloomberg), encadré de la Banque de réserve d'Australie 2019 | ÉCARTÉE | dispo (6J) | critère 1 ; volatilité dans les deux sens (sens imprévisible, interventions du Japon) ; 2 à 3 épisodes par an |
| 233 | Les extrêmes du TICK du NYSE (±1 000) se retournent en quelques minutes les jours sans tendance | sites de formation (LuxAlgo, NexusFi), étude auto-publiée (thetrading.tools) | ÉCARTÉE | TICK du NYSE (flux payant) | critère 1 ; retournement court déjà rejeté (n° 28, 32) |
| 234 | Le rendement intraday de tout le marché américain se prévoit avec les rendements à haute fréquence des centaines de « facteurs » d'actions (apprentissage automatique) | Aleti, Bollerslev & Siggaard, *Management Science* 2025 | ÉCARTÉE | rendements intraday de ~200 facteurs construits sur toutes les actions (payant) | données absentes ; la règle est un modèle d'apprentissage automatique ré-estimé, pas une règle figée (critère 7) |
| 235 | La dernière demi-heure américaine annonce la première demi-heure du lendemain des autres bourses (Nikkei, DAX, FTSE…) | Xu, Li, Singh, Chen & Li, *J. International Financial Markets, Institutions and Money* 2025 | **OUVERTE** ★ | dispo (FDAX, CFD Nikkei et FTSE) | texte complet sous embargo jusqu'en 10/2027 (critère 3 : l'idée attend) ; probablement le même effet que le n° 41 (le signal passe dans l'écart d'ouverture, déjà dans le prix des futures qui cotent la nuit) ; famille du n° 134 |
| 236 | Le sentiment des nouvelles prévoit les futures du Nikkei du CME | *Research in International Business and Finance* 2026 | ÉCARTÉE | indices de sentiment (payants) | résumé introuvable ; demande des scores de sentiment des dépêches |
| 237 | Le marché crypto a son pic d'activité, de volatilité et d'illiquidité entre 16:00 et 17:00 UTC | *Review of Quantitative Finance and Accounting* 2024 (1 940 paires, 38 plateformes) | ÉCARTÉE | dispo | effet sur l'activité et la volatilité, pas sur le rendement |
| 238 | Momentum de fin de séance (la nuit annonce la dernière demi-heure) seulement quand le signal est fort (seuils) | Rosa, *J. Futures Markets* 2022 | ÉCARTÉE | dispo | papier contraire au n° 1 : la prévisibilité disparaît hors échantillon ; la version à seuils vient d'un modèle à régimes estimé après coup (critère 7) ; confirme le rejet du n° 1 |
| 239 | Le sentiment des messages boursiers en ligne de la 1re demi-heure annonce la dernière demi-heure du S&P 500 | Renault, *J. Banking & Finance* 2017 ; Broadstock & Zhang, *Finance Research Letters* 2019 (Twitter) | ÉCARTÉE | messages StockTwits / Twitter (accès fermé ou payant) | données absentes ; échantillons 2012-2016 (critère 2) |
| 240 | Règles techniques intraday sur l'or et l'argent ; fréquence des règles techniques sur les devises | Batten, Lucey, McGroarty & Peat, *JIFMIM* 2017 ; Frömmel & Lampaert, *FRL* 2016 | ÉCARTÉE | dispo | données d'avant 2016 (critère 2) ; règles techniques génériques déjà couvertes par les momentums rejetés (n° 62, 86) |
| 241 | Effets heure par heure des devises (rendement selon l'heure de la journée) | Khademalomoom & Narayan, *JIFMIM* 2019 ; Zhang, *FRL* 2018 | ÉCARTÉE | dispo | même famille que le n° 85 (une devise baisse pendant ses propres heures), t attendu < 3 sur nos futures |
| 242 | Courbes de rendement intraday du bitcoin ; comportement intraday des cryptos ; momentum intraday du bitcoin calé sur le volume | Bouri, Lau, Saeed & Wang, *IRFA* 2021 ; Hu, McInish, Miller & Zeng, *FRL* 2019 ; Shen, Urquhart & Wang, *Financial Review* 2021 | ÉCARTÉE | dispo (Binance) | même famille que le n° 92 (fenêtres courtes du bitcoin, rejetée) ; modèles estimés, pas de règle figée ; crible crypto du 2026-10-22 |
| 243 | Les événements de la nuit (séance de nuit) changent la séance de jour suivante | Ham, Ryu & Webb, *IRFA* 2022 | ÉCARTÉE | — | futures KOSPI 200 (Corée) ; pas nos marchés |
| 244 | Prime de risque des obligations gagnée juste avant les chiffres macro | Balduzzi & Moneta, *JFQA* 2017 | ÉCARTÉE | pas de minutes ZN/ZB | le papier lui-même : prime non significative après la crise de 2008 |
| 245 | Les indices baissent le lundi qui suit le changement d'heure (manque de sommeil) | Kamstra, Kramer & Levi, *AER* 2000 ; contraires : Gregory-Allen, Jacobsen & Marquering, *Financial Analysts J.* 2010 (22 pays, 1 150 changements : aucun effet) | ÉCARTÉE | dispo | papier ancien démenti par la réplication la plus large (critères 2 et 4) ; 2 cas par an : t attendu ≈ 0,7 (−0,2 % pour 1,2 % d'écart-type, 20 cas) |
| 246 | Les indices montent mieux autour de la nouvelle lune que de la pleine lune | Dichev & Janes 2003 ; Yuan, Zheng & Zhu, *J. Empirical Finance* 2006 (48 pays) | ÉCARTÉE | dispo | anciens (critère 2) ; écart de 3 à 5 % par an, instable selon les périodes ; t attendu ≈ 0,7 sur 10 ans (4 % par an pour 17 % de volatilité) |
| 247 | Le soleil à New York fait monter la bourse ; la météo agit sur les rendements | Hirshleifer & Shumway, *JF* 2003 ; Kathiravelu et al., *Critical Finance Review* 2021 (49 pays) | ÉCARTÉE | météo gratuite (NOAA) | l'effet de New York s'affaiblit avec la dispersion géographique des ordres (*Review of Economic Analysis*) ; pas de règle intraday ; effet récent surtout sur les actions « loterie » |
| 248 | Les défaites sportives nationales font baisser la bourse le lendemain | Edmans, García & Norli, *JF* 2007 | ÉCARTÉE | dispo | ancien (critère 2) ; football surtout européen et rare (quelques matchs décisifs par an) : aucune puissance |
| 249 | Quand le S&P 500 a monté la veille, le Nikkei baisse dans sa 1re demi-heure et monte dans sa dernière demi-heure | Iwanaga, *Finance Research Open* 2026 (accès libre) | ÉCARTÉE | dispo (CFD Nikkei HistData) | revue née en 2025, hors des listes de référence, un seul auteur (critère 1) ; texte complet bloqué par un CAPTCHA (non contourné) ; même famille que N1 et le n° 134 (rejetées ou écartées) |
| 250 | Momentum intraday dans une « bande de bruit » sur les futures Nasdaq-100 | SSRN 7609644 (2026) | ÉCARTÉE (déjà couverte) | dispo | variante de S1 (Noise Area, déjà en direct) : pas une hypothèse nouvelle ; page SSRN bloquée par la vérification anti-robot |
| 251 | Effets du jour de la semaine en crypto, heure par heure | *Finance Research Letters* 2026 | ÉCARTÉE | dispo (Binance) | le papier conclut lui-même à des écarts localisés et de courte durée ; balayer les heures × jours = chasse aux motifs (critère 16) |
| 252 | Les messages de Donald Trump (campagne 2024) font bouger le SPY dans les minutes suivantes | *Journal of Finance Issues* 2026 | ÉCARTÉE | dispo | volatilité +33 %, mais aucun rendement anormal après les messages |
| 253 | Le bêta redevient payant en séance après un fort choc de VIX ; anomalies de jour et de nuit sur 11,6 millions de prix | *Applied Economics Letters* 2026 ; *Finance Research Letters* 2025 | ÉCARTÉE | — | actions en coupe transversale, pas un indice |
| 254 | Momentum intraday des futures du café | *J. Commodity Markets* 2025 | ÉCARTÉE | café (KC) absent | contrat absent ; famille du momentum intraday, rejetée sur nos contrats (n° 1, 62, 86) ; réexaminé le 2026-10-25 : voir n° 139 (même papier), ÉCARTÉE |
| 255 | Modèle « de sciences naturelles » qui prévoit les retournements intraday du S&P 500 | arXiv 2510.01542 (2025) | ÉCARTÉE | dispo | critère 1 ; aucune statistique hors échantillon |
| 256 | Le sentiment des nouvelles de la nuit annonce (à l'envers) la séance du S&P 500 | SSRN 5723163 (2025) | ÉCARTÉE | scores de sentiment (payants) | données absentes ; résumé introuvable |
| 257 | Le sentiment des messages Twitter pousse le prix des actions, et l'écart met plusieurs jours à se corriger ; les particuliers achètent contre la tendance de la journée sur les produits dérivés et y perdent | *Financial Review* 2024 ; *J. Futures Markets* 2024 (dérivés pour particuliers) | ÉCARTÉE | — | actions individuelles et produits pour particuliers, horizon de plusieurs jours |
| 258 | Synthèse de la Fed sur le FOMC et la bourse (surprise de l'annonce, dérive d'avant l'annonce, cycle du FOMC) | Réserve fédérale, FEDS 2026-023 | ÉCARTÉE (déjà couverte) | dispo | aucune règle nouvelle : dérive d'avant l'annonce et cycle déjà testés (n° 9, 10) ; risque extrême avant le FOMC déjà noté (n° 201) ; retournement de l'ouverture du YM déjà noté (n° 118) |
| 259 | Prime de risque du gaz naturel les jours où les prévisions annoncent une météo extrême | Monteux, Arcuri, Gandolfi & Caselli, *North American J. Economics and Finance* 2025 | ÉCARTÉE | gaz (NG) : Databento ; prévisions de température (payantes) | rendements journaliers, pas intraday ; gaz absent ; même famille que le n° 112 |
| 260 | Le levier fait perdre les clients non qualifiés d'un courtier de futures (appels de marge, ventes forcées) | Subrahmanyam, Tang, Wang & Yang, *JF* 2024 | ÉCARTÉE | données d'un courtier (privées) | comptes clients chinois ; aucun signal sur le prix |
| 261 | Le dollar australien suit la surprise du fixing quotidien du yuan par la Banque populaire de Chine (21:15 ET) | presse (Pound Sterling Live, FXStreet) ; McCauley & Shu (BRI, document préliminaire : réforme d'août 2015 seulement) | ÉCARTÉE | dispo (6A) ; estimation Reuters du fixing (payante) | critère 1 : aucune étude intraday sur le dollar australien ; le sens dépend de la surprise (fixing contre estimation) ; famille du n° 82 (chiffres chinois, rejetée) |
| 262 | L'or est « aimanté » vers les prix d'exercice des options COMEX à leur échéance | commentaires de marché (Goldmoney, Business Recorder) | ÉCARTÉE | positions d'options par prix d'exercice (payant) | critère 1 : aucune étude ; famille du n° 100 |
| 263 | Les indices réagissent à l'annonce trimestrielle de refinancement du Trésor (mercredi 8:30) | notes de marché (Saxo, MNI) | ÉCARTÉE | dispo | critère 1 : aucune étude d'événement ; 4 cas par an ; le sens dépend de la répartition des émissions annoncée |
| 264 | Un indice de sentiment tiré des GIF postés sur un réseau d'investisseurs annonce (à l'envers) la bourse des 4 semaines suivantes | Gu, Hirshleifer, Teoh & Wu, NBER 2026 | ÉCARTÉE | messages StockTwits (accès fermé) | horizon de semaines, pas intraday ; données absentes |
| 265 | Les « nouvelles pures » (purgées de ce qui était prévisible) prévoient les actions jusqu'à 18 mois | Didisheim, Kelly, Pourmohammadi & Tian, NBER 2026 | ÉCARTÉE | textes de dépêches (payants) | actions en coupe transversale, horizon mensuel |
| 266 | Les gros paris acheteurs de financiers sur le contrat WTI qui expire poussent son prix à l'échéance (avril 2020 : prix négatif) | Gilje, Ready, Roussanov & Taillard, NBER 2026 | ÉCARTÉE (appui du n° 105) | Databento (contrats individuels) | un seul épisode étudié (avril 2020) : confirme le mécanisme du n° 105, sans effet moyen mesurable pour un calcul de puissance |
| 267 | Le momentum des actions se gagne sur 6 séances par mois, finies 4 séances avant la fin du mois (les institutions vendent leurs perdantes pour avoir du cash réglé) | Nathan, Suominen & Tasa 2026 (2e prix Quantpedia 2026 ; annexe lue sur le site de l'auteur) | ÉCARTÉE | — | actions en coupe transversale (gagnantes contre perdantes) ; la version indice (fin de mois, ventes forcées) est déjà rejetée (n° 13) |
| 268 | Autres primés Quantpedia 2026 : pondération apprise des rendements passés (momentum), hypothèses trouvées par IA, anomalies « ravivées », trading des ETN VIX | Wiedemann & Beckmeyer ; Liu et al. ; Beckmeyer et al. ; Zarattini et al. (SSRN 5702162, 6569258, 6468806, 5316487) | ÉCARTÉE | — | coupe transversale des actions ou produits VIX (non proposés en prop firm, comme le n° 109) |
| 269 | Les données gratuites d'attention et de ton des nouvelles (GDELT, pages vues Wikipedia, Google Trends, marchés de prédiction Kalshi / Polymarket) prévoient les indices, l'or ou le bitcoin dans la journée | crible OpenAlex 2019-2026 (262 résultats) : *Int. J. Forecasting* 2019 (volatilité), *European J. Finance* 2020 (bitcoin), *Intelligent Systems in Accounting* 2022 (Wikipedia, Nasdaq), arXiv 2505.16136 | ÉCARTÉE | gratuites | les études portent sur la volatilité, des horizons journaliers ou plus, ou des modèles d'apprentissage automatique ; aucune règle intraday figée avec un effet mesuré sur nos contrats (critères 6 et 7) |

**Crible des revues spécialisées 2016-2022 (2026-10-25, aucun essai).** API Crossref, titres contenant intraday /
overnight / hour / session dans *J. Futures Markets*, *J. Financial Markets*, *JBF*, *FRL*, *IRFA*, *JIFMIM*, *Energy
Economics*, *Quantitative Finance*, *Financial Review*, *JFQA* (96 titres) : après exclusion des marchés émergents, de
l'électricité, de la volatilité et de la liquidité, n° 238 à 244, tous écartés ou déjà couverts (n° 1, 39, 63, 85, 92).

**Crible OpenAlex des articles 2023-2026 (2026-10-25, aucun essai).** API publique d'OpenAlex (une base qui recense
revues, SSRN, arXiv), trois collectes de 12 requêtes (effets intraday des futures ; annonces, échéances, enchères,
fixings ; nos marchés : or, yen, livre, dollar australien, DAX, Nikkei, pétrole) : 1 396 résultats, 121 après filtre
(effet de prix, horizon intraday, hors marchés émergents et prévision de volatilité). Déjà inscrits : n° 86, 118, 170,
181, 201, 213 et la note Mesfin ; nouveaux : n° 249 à 260, tous écartés ou déjà couverts.

**Crible des documents de travail du NBER 2023-2026 (2026-10-25, aucun essai).** OpenAlex, source NBER, 12 requêtes
(intraday, nuit, annonces, futures, clôture, FOMC, couverture, échéances, flux, prévisibilité, pression) : 426 titres,
aucun effet intraday nouveau sur nos contrats ; n° 264 à 266. À retenir comme **source de données gratuite** : les
marchés de prédiction Kalshi donnent un consensus macro en continu (Diercks, Katz & Wright, NBER 2026), mais le sens
d'une surprise se trade après l'annonce, quand le prix a déjà bougé.

**Crible des séries de la Fed (FEDS, Liberty Street, rapports du personnel) 2023-2026 et des primés Quantpedia 2026
(2026-10-25, aucun essai)** : 316 titres de la Fed, aucun effet intraday nouveau ; Brent intraday (n° 64), dérives
avant les banques centrales (n° 173) déjà inscrits ; n° 267-268.

## 7 nonies. Tous les actifs (demande du 2026-10-25 : chercher hors de nos 9 contrats, constituer un stock de candidates, puis acheter les données en une fois)

Même méthode (critères 1 à 6) ; la colonne « Données » donne le contrat de base et le micro jouable en prop firm. Une
candidate entre dans le **stock à acheter** seulement si le papier est sérieux, lu, non contredit, et si le t attendu
avec l'effet du papier atteint 3 (2 pour moins de 60 cas).

| # | Hypothèse | Source | Statut | Données | Résultat / raison |
|---|---|---|---|---|---|
| 270 | Les actions européennes continuent jusqu'à 20 jours dans le sens de la surprise de la conférence de presse de la BCE | Valentin (Goethe, 2022 ; AEA 2023) ; texte derrière un contrôle anti-robot (non contourné) | ÉCARTÉE | FESX / FDAX (Eurex ; micro FSXE) | +160 / −114 pb en 20 jours (2002-2020) contre ~540 pb d'écart-type sur 20 jours : t attendu 2,3 avec 85 réunions 2016-2026 ; tenue de 20 jours (week-ends, critère 21) ; la version d'avant l'annonce est déjà écartée (n° 173) |
| 271 | Les taux d'État de la zone euro montent avant leurs adjudications et baissent après | Beetsma, Giuliodori, de Jong & Widijanto, *J. Financial Intermediation* 2016 | ÉCARTÉE | FGBL / FBTP (Eurex) | effet surtout sur l'Italie et seulement pendant la crise (depuis mi-2007) ; faible sur l'Allemagne (critère 2) |
| 272 | Les taux longs américains baissent dans la fenêtre de 3 jours autour du FOMC (toute la baisse séculaire depuis 1980 s'y concentre) | Hillenbrand, *Review of Financial Studies* 2025 | ÉCARTÉE | ZN / ZB (Databento ; micro « 10Y » en rendement) | ~7,7 points de baisse sur ~300 réunions → ~2,5 pb de rendement par réunion (≈ 16 pb de prix sur ZN, 42 sur ZB) contre ~15 pb d'écart-type de rendement sur 3 jours : t attendu 1,2 (ZN) et 1,3 (ZB) avec 85 réunions ; la tendance s'est inversée en 2021-2023 |
| 273 | Le gaz naturel bouge le lundi selon les modèles météo du week-end | presse spécialisée (NGI, ETF Trends) | ÉCARTÉE | NG (micro MNG) | critère 1 : aucune étude ; le sens dépend de la prévision ; famille des n° 112 et 259 |
| 274 | Le cuivre réagit aux heures de Shanghai (séance de nuit, momentum intraday chinois) | Jin, Kearney, Li & Yang, *J. Futures Markets* 2020 ; Klein & Todorova, *Resources Policy* 2021 | ÉCARTÉE | HG (micro MHG) | contrats chinois seulement ; aucune étude sur le cuivre du COMEX |
| 275 | Le ZN monte dans le quart d'heure qui suit une adjudication du Trésor, surtout quand la demande (ratio d'offres) est forte : les teneurs de marché rachètent leurs couvertures | Smales, *Accounting & Finance* 2021 (2000-2017, texte payant) | ÉCARTÉE | ZN (Databento) | famille du n° 50 : Fleming, Liu & Nguyen 2026 (lu en entier) mesure ce V autour de 13:00 divisé par 2 depuis 2015, gain brut ≈ coûts ; le ratio d'offres est publié à 13:00, la réaction suit aussitôt (rien à prendre après) |
| 276 | Le gaz réagit 74 % moins fort aux rapports de stocks publiés un vendredi (semaines fériées) : manque d'attention, donc rattrapage possible ensuite | Gu, Kurov & Stan, *J. Futures Markets* 2026 (texte payant) | ÉCARTÉE | NG (micro MNG) | aucun rattrapage chiffré dans le résumé ; 3 à 5 vendredis par an (< 60 cas sur 2016-2026) ; texte introuvable (critère 3) |
| 277 | Après un FOMC lu comme une « mauvaise nouvelle » de la Fed sur l'économie, les actions montent pendant 20 jours | Ma & Zhang, *Quarterly J. Finance* 2023 | ÉCARTÉE | ES / NQ (dispo) | tenue de 20 jours (week-ends, critère 21) ; classement bon / mauvais par restrictions de signe sur données intraday (modèle estimé, critère 7) ; famille du cycle du FOMC (n° 10, rejetée) |
| 278 | Les rapports de l'USDA font bouger le maïs et le soja ; la volatilité implicite baisse plusieurs jours après | Ying, Chen & Dorfman, *AJAE* 2019 ; Cao & Robe, *J. Futures Markets* 2021 ; Indriawan, Martinez & Tse, *J. Commodity Markets* 2021 | ÉCARTÉE | ZC / ZS (mini XC / XK) | le sens dépend de la surprise ; l'effet sûr porte sur la volatilité (options), pas sur le prix des futures |
| 279 | Le gaz et le pétrole ont une saisonnalité selon le MOIS où l'on traite le contrat (pression de couverture saisonnière) | Ewald, Haugom, Lien, Størdal & Wu, *Energy Economics* 2022 (accès libre, lu) | ÉCARTÉE | NG, CL | moyennes mensuelles et positions de plusieurs mois entre deux échéances : pas intraday ; même équipe que le n° 64 |
| 280 | Les titres du Trésor sont sous-évalués à l'adjudication parce que les teneurs de marché portent le risque jusqu'au règlement | Herb, *J. Banking & Finance* 2025 | ÉCARTÉE | ZN / ZB | prime mesurée au jour (2000-2016) ; même famille que les n° 50 et 275 (affaiblie depuis 2015 d'après Fleming 2026) |
| 281 | Anomalie d'horaire des adjudications sur les futures d'obligations japonaises | Iwanaga, *Finance Research Letters* 2025 | rouverte le 2026-10-25 | JGB (Osaka) | contrat non proposé par les prop firms ; même auteur que le n° 249 ; **réexaminé le 2026-10-25 (tous marchés permis)** : futures JGB d'Osaka accessibles (courtiers internationaux), frais faibles ; résumé introuvable (ni sur la page de l'auteur ni sur RePEc) → l'idée attend : **OUVERTE** ★ |
| 282 | Effet week-end des futures : le vendredi rapporte plus que le lundi (risque des positions vendeuses, humeur) | Singal & Tayal, *J. Futures Markets* 2020 | ÉCARTÉE | tous futures | anomalie connue depuis French 1980 (n° 215) ; texte payant, échantillon non vérifié (critères 2 et 3) |
| 283 | Copier les positions des spéculateurs (rapport COT) sur les futures de devises autour du chiffre de l'emploi : ils vendent avant les bons chiffres et gagnent ; l'information dure | Park, *J. Banking & Finance* 2022 (SSRN 3983210) | **OUVERTE** ★ | 6E 6B 6J 6A (dispo) + COT (gratuit) ; 6C 6S (Databento) | texte payant, page SSRN bloquée par un contrôle anti-robot : la règle exacte et l'effet sont inconnus (critères 3 et 6) ; piège de calendrier : le COT du mardi sort le vendredi à 15:30, après le chiffre de 8:30, donc seul le COT de la semaine d'avant est connu à temps ; notre test COT (`pression_cot`) est déjà rejeté |
| 284 | Le ton des notes d'analystes prévoit les futures de matières premières | Han, Hsieh & Zhang, *J. Futures Markets* 2026 | ÉCARTÉE | — | marchés chinois, notes d'analystes payantes |
| 285 | Le lundi, le pétrole se découple des mesures de risque systémique (trou d'information du week-end) | Conlon, Corbet, Larkin & Muñiz, *J. Futures Markets* 2026 | ÉCARTÉE | CL | liens de volatilité (modèles TVP-VAR, ondelettes), pas un rendement à prendre |
| 286 | Les fins de mois concentrent l'activité du Trésor autour de 16:00 (heure de calcul des indices obligataires déplacée de 15:00 à 16:00 en janvier 2021) | Dyer, Fleming & Shachar, *Liberty Street Economics* (Fed de New York), 09/2026 (lu) | ÉCARTÉE (appui du n° 52) | ZN / ZB | volume seulement (part du créneau 15:55-16:00 en hausse : 20 % du jour en 2025 les derniers jours du mois), aucun effet de prix mesuré |
| 287 | Les futures de taux courts (SOFR, fed funds) montent avant le FOMC comme les actions | Lucca & Moench, Fed de New York SR 512 / *JF* 2015 | ÉCARTÉE | SR3 / ZQ | le papier lui-même : aucun effet avant le FOMC sur les taux |
| 288 | Le gaz subit une pression de prix dans la fenêtre de règlement (14:28-14:30) | aucune étude | ÉCARTÉE | NG | critère 1 ; famille du n° 66 (TAS) |
| 289 | Le soja continue dans le sens de la surprise du WASDE après les 30 premières minutes, jusqu'à la clôture | Anderson, McKenzie & Noyes, conférence NCCC-134 2024 (Arkansas ; lu en entier ; 2010-2021, 122 rapports) | ÉCARTÉE | ZS (mini XK) + consensus Bloomberg (payant) | coefficient −0,061 à 30 min, −0,124 à la clôture → ~14,5 pb de plus pour une surprise moyenne, contre ~150 pb d'écart-type et ~5 pb de frais : t attendu 0,7 (125 rapports 2016-2026) ; actes de conférence (critère 1) ; maïs : rien après 30 min |
| 290 | Les grains et le bétail sur- ou sous-réagissent aux rapports de l'USDA | Lehecka, Wang & Garcia, *Applied Economic Perspectives and Policy* 2014 (maïs : tout est fait en 10 min, ni sur- ni sous-réaction) ; soja aux heures de séance (*Applied Economics* 2017) ; bétail (AgEcon, 1985-2004 : volatilité seulement) | ÉCARTÉE | ZC ZS LE HE | prix ajustés en quelques minutes ; rien à prendre ensuite |
| 291 | Pression de prix des grains dans la minute de règlement (13:14-13:15 CT) | aucune étude | ÉCARTÉE | ZC ZS ZW | critère 1 |
| 292 | Dérive du dollar canadien après la Banque du Canada ; franc suisse valeur refuge selon l'heure ; peso mexicain à l'ouverture américaine | Ghazei (mémoire, Victoria 2025) ; Ranaldo & Söderlind, BNS 2007 (1993-2006) ; Tse & Martinez, *RIBAF* 2018 | ÉCARTÉE | 6C 6S 6M (Databento) | aucune étude de rendement intraday prévisible : le franc monte EN MÊME TEMPS que les actions baissent (pas d'avance) ; dérive après les banques centrales déjà rejetée ailleurs (n° 81) |
| 293 | Les futures sur le Trésor et le pétrole sont « aimantés » vers les prix d'exercice à l'échéance de leurs options | aucune étude (seul le S&P l'est : Golez & Jackwerth, n° 100) ; notes MNI sur les positions d'options WTI | ÉCARTÉE | ZN, CL | critère 1 ; positions par prix d'exercice payantes |
| 294 | Le Russell 2000 (RTY) a son propre profil nuit / jour ou de retournement intraday | rapport Milliman 2024 (praticiens) ; aucune étude académique propre au RTY | ÉCARTÉE | RTY / M2K (Databento) | critère 1 ; nos répliques de nuit sur IWM étaient nulles (t 0,6-0,8, n° 45 et piste S06-C) |
| 295 | La cassure du range d'ouverture (ORB) gagne sur le pétrole et le DAX, surtout quand la volatilité est haute | Holmberg, Lönnbark & Lundström, *FRL* 2013 ; Lundström, documents de travail d'Umeå | ÉCARTÉE | CL, FDAX | données anciennes (critère 2) ; nos répliques de l'ORB sur CL et le DAX ont déjà échoué |
| 296 | Bandes de bruit (méthode de S1) appliquées à un portefeuille de futures (taux, devises, matières premières) | Zarattini (entretien Concretum : portefeuille de tendance sur futures, sans chiffres) ; Maróy 2025 (variantes sur SPY) | ÉCARTÉE | — | aucun chiffre publié par contrat : le critère 6 exige l'effet mesuré sur le même contrat (comme les n° 45, 74, 75, 89) |
| 297 | Platine et palladium : saisonnalité ou prévisibilité intraday | Batten, Lucey, McGroarty, Peat & Urquhart, *PLoS ONE* 2017 (faits stylisés, 2000-2015) ; Cohen, *Mathematics* 2022 (journalier) | ÉCARTÉE | PL, PA (Databento) | aucune étude du rendement intraday ; données d'avant 2016 (critère 2) ; Cohen : retour à la moyenne journalier, pas intraday |
| 298 | Huile de soja, blé (Chicago, Kansas City) : profil du rendement selon l'heure | Jordan et al. 1988 (variance du soja) ; Janzen & Legrand 2019 (volume du blé, brouillon) | ÉCARTÉE | ZL, ZW, KE | volatilité et volume seulement ; 1988 (critère 2) ; la seule étude de momentum intraday porte sur Dalian (Chine) |
| 299 | Essence et fioul (RB, HO) : dérive après le rapport de stocks EIA du mercredi | présentation de l'EIA 2017 (Linn, fenêtres de 5 min) ; Halova, Kurov & Kucher | ÉCARTÉE | RB, HO | la réaction se fait en 5 à 7 minutes, comme sur le pétrole (n° 63, rejeté) ; le sens dépend de la surprise, inconnue à l'avance |
| 300 | Bétail (LE, HE, GF) : sur- ou sous-réaction aux rapports USDA | Schroeder, Blair & Mintert 1990 ; Colling & Irwin 1990 ; Frank, Garcia & Irwin 2008 ; *JARE* 2006 | ÉCARTÉE | LE, HE, GF | études journalières et anciennes (critère 2) ; marché du porc efficace ; écarts courts sur les bovins dépendant de la surprise (consensus payant) |
| 301 | Dollar néo-zélandais (6N) après la RBNZ ; ether, SOL et XRP du CME ; métaux précieux par règles algorithmiques ; écart d'ouverture prévu par les nuits des autres bourses | Karagedikli & Siklos, RBNZ DP 2008/02 ; Gil, *Chaos, Solitons & Fractals* 2022 ; Si, Nadarajah & Chen, *Borsa Istanbul Review* 2026 | ÉCARTÉE | 6N, MET, GC/SI | RBNZ : effet permanent de la surprise, pas de dérive, 2008 ; cryptos : aucune étude propre, SOL et XRP cotés depuis 2025 (historique trop court) ; Gil : revue de physique, règles techniques génériques (n° 240) ; Si et al. : famille du n° 235 |
| 302 | Corrélation négative des variations de prix au fil de la séance sur les futures du 10 ans (retournement intraday) | *Banking and Finance Review* 2009 (« Intraday serial correlation and the predictability of returns in Treasury futures ») | ÉCARTÉE | ZN | revue mineure (critère 1), données anciennes (critère 2) ; retournement court déjà couvert (n° 28, 97, 129) ; momentum de fin de séance sur les taux écarté (n° 51) |
| 303 | Écart entre échéances des futures du Trésor pendant le roulement trimestriel : retour à la moyenne, positions des gérants d'actifs (COT) | Quantitative Brokers 2018-2024 (notes de courtier) ; CME, « A descriptive study of US Treasury rolls » 2018 | ÉCARTÉE | ZN, ZB (écarts) | critère 1 (notes de courtier) ; prédicteurs « très faibles » seuls d'après les auteurs ; écart tenu sur ~10 jours (non conforme), aucune mesure intraday |
| 304 | Futures chinois (cuivre, acier, soja, tourteau) : la 1re demi-heure annonce la dernière demi-heure et le reste de la séance | Jin, Kearney, Li & Yang, *J. Futures Markets* 2020 (version MPRA 97134 lue en entier ; 2002-2013) | ÉCARTÉE | SHFE, DCE (données payantes) | gain BRUT de la dernière demi-heure 2,5 à 4,2 pb par jour (6,1 à 10,3 %/an, tableau 7, sans frais) contre ~4 à 8 pb de frais (1 tick + frais de bourse par côté) : perdant net ; et l'effet de jour disparaît après l'ouverture de la séance de nuit en 2013 (n° 305) |
| 305 | Métaux chinois (or, argent, aluminium, cuivre) : depuis 2013, la 1re demi-heure de la séance de NUIT (21:00 Pékin) annonce la suite | Bouri, Ma, Xu & Zhou, document de travail (texte complet lu, AUT 2023 ; 1 minute, 2008-2021) ; publié pour l'or et l'argent : Ma, Bouri, Xu & Zhou, *Global Finance Journal* 2025 | ÉCARTÉE | SHFE (fermé aux particuliers étrangers ; aucune prop firm) | tableau 11 B (après 2013, brut) : or 6,77 %/an (t 3,71), argent 10,20 % (2,68), aluminium 6,79 % (3,40), cuivre 2,99 % (2,42). Brut par jour 2,8 / 4,2 / 2,8 / 1,2 pb contre 1,5 / 5,0 / 6,2 / 3,9 pb de frais. t attendu net sur 10 ans : or **1,86**, les autres négatifs → aucun essai |
| 306 | Futures chinois : le rendement de la nuit se retourne pendant la journée (pétrole de l'INE ; matières premières et options 2017-2022) | Wen, Wang & Zhang, *Economic Modelling* 2021 (pétrole SC de l'INE, résumé lu) ; Zheng & Luo, *Pacific-Basin Finance Journal* 2024 (résumé lu) | **OUVERTE** ★ | INE SC (ouvert aux étrangers par des intermédiaires agréés ; aucune prop firm) ; données payantes | deux papiers récents dans le même sens ; textes payants (critère 3 : l'idée attend) ; échantillon court (SC coté depuis 2018) ; frais du SC ≈ 4,8 pb l'aller-retour |
| 307 | Prévisibilité intraday des matières premières chinoises dans un marché dominé par les particuliers | Guo & Zhu, *J. Banking & Finance* 2026 | **OUVERTE** ★ | DCE, SHFE, ZCE (payantes) | résumé introuvable (pas sur RePEc ni OpenAlex) : rien à juger pour l'instant |
| 308 | Momentum intraday des futures d'indices chinois (CSI 300, CSI 500) | Li, Shen, Wang & Zhang, *Finance Research Letters* 2020 ; Zhang et al. 2019 | ÉCARTÉE | CFFEX | contrats fermés aux particuliers étrangers (seuls les investisseurs agréés peuvent couvrir) : injouable ; momentum intraday déjà rejeté sur les indices (n° 1, 37) |
| 309 | Momentum intraday du KOSPI 200 qui survit aux coûts | Lai, Lin, Eom & Tsai, *J. Risk and Financial Management* 2022 | ÉCARTÉE | KOSPI 200 (KRX) | revue MDPI, 2 citations (critère 1) ; famille du momentum intraday mondial (Li, Sakkas & Urquhart 2022, n° 37, rejeté) |
| 310 | KOSPI 200 : le déséquilibre des ordres d'options des 10 premières minutes annonce l'indice et ses futures pour le reste de la séance (gain après frais selon les auteurs) | Kang, Kang & Lee, *J. Futures Markets* 2022 (résumé lu) ; thèse KAIST 2021 | **OUVERTE** ★ | KOSPI 200 (KRX ; courtiers internationaux) + ordres d'options signés par type d'investisseur (KRX, payant) | texte payant : effet et écart-type inconnus (critères 3 et 6) ; porté surtout par les institutionnels, d'après le résumé |
| 311 | Momentum intraday (1re → dernière demi-heure) sur les ETF d'Asie-Pacifique : présent en Chine et au Japon, faible en Corée, absent à Hong Kong et Singapour, affaibli pendant le Covid | Limkriangkrai, Chai & Zheng, *Pacific-Basin Finance J.* 2023 | ÉCARTÉE | Nikkei (dispo, CFD HistData), autres payants | famille du n° 37 (Li, Sakkas & Urquhart : Japon Sharpe 0,72, rejeté sur nos données, N1) ; aucun gain chiffré net |
| 312 | Contre-papiers des effets de calendrier : fin de mois qui disparaît ; prime d'avant les jours fériés devenue un effet des petites capitalisations ; prime des annonces macro surtout due au hasard de l'échantillon | Han, Han & Tian, *FRL* 2025 ; Ko & Yang, *Critical Finance Review* 2024 ; Ghaderi & Seo, *Management Science* 2026 | — (contre-papiers) | — | confirment le rejet des n° 57, 199, 215 et des répliques sur indices : les effets de calendrier classiques ne vivent plus sur les grands indices |
| 313 | Effets du jour de la semaine en crypto : quelques heures précises seulement, propres à chaque actif | Aalipour, Mehdian & Rezvanian, *FRL* 2026 | ÉCARTÉE | dispo (Binance) | les auteurs concluent à des inefficiences « limitées et brèves » ; choisir les heures après coup = surajustement ; heures crypto déjà testées (H11, H12, n° 92) |
| 314 | Le flux d'ordres mondial (11 devises) explique et prévoit les rendements des cryptos | Anastasopoulos, Gradojevic & Li, *J. Financial Markets* 2026 | ÉCARTÉE | flux d'ordres FX des courtiers (payant, non public) | coupe transversale et modèles d'apprentissage ; données non accessibles |
| 315 | Le flux d'ordres sur les puts d'indice annonce le S&P de la semaine suivante | Chordia, Kurov, Muravyev & Subrahmanyam, *Management Science* 2021 | ÉCARTÉE | flux signé ISE (payant) | horizon d'une semaine (pas intraday) ; 2006-2013 |
| 316 | Inde : échéance hebdomadaire des options sur le Nifty (épinglage, couverture des teneurs de marché) ; options vendues le jour ou la nuit | Kumar 2022 (revue indienne) ; Bhat, Pandey & Nageswara Rao, *J. Futures Markets* 2024 | ÉCARTÉE | Nifty (NSE fermé aux particuliers étrangers ; GIFT Nifty à Singapour/Gift City) | aucune étude du rendement de l'indice à l'échéance ; le papier JFM porte sur la prime de variance des options (vente d'options, hors cadre) ; échéances hebdomadaires réduites par la SEBI fin 2024 |
| 317 | Brésil (mini-Ibovespa WIN) et options 0DTE américaines : prévisibilité intraday | arXiv 1904.09214 (réseau de neurones) ; Baptista & Pereira 2008 ; thèses de Princeton 2026 (flux delta signé SPX → ES, 2024) ; résumé Quantpedia (0DTE → retournements) | ÉCARTÉE | WIN (B3), ES (dispo) + OPRA (Databento, payant) | aucune étude sérieuse et chiffrée : prépublication, revue de 2008, thèses de licence ; l'effet 0DTE porte sur la volatilité (baisse), pas sur un sens |
| 318 | **Les spéculateurs qui parient sur une pentification de la courbe des taux (rapport COT) annoncent la hausse de l'ES le jour du FOMC, de 9:30 à 15 min avant l'annonce** | Park, Réserve fédérale, FEDS 2019-025 « Information in Yield Spread Trades » (texte complet lu le 2026-10-25 ; version 2018 « Spread Trades, Business Cycles, and Asset Prices ») ; non publié en revue (critère 1 : banque centrale) | **REJETÉE (essai n° 435, 2026-10-25)** | ES et MES (dispo) + COT « legacy » futures seuls (gratuit, déjà dans `.cache/cftc`, 2014-2026) | `pente_fomc` : règle du papier figée (STEEP connu à la réunion précédente, coefficients du papier, 9:30 → 13:45 ET ; substitut Eurodollar → SOFR 3 mois au 2023-04-11) ; ES 84 réunions 2016-2026 : −3,45 pb brut (t −1,07) au lieu de +28,5 ; 2021-2026 −6,8 ; Sharpe −0,47 [−1,00 ; 0,12] ; MES, NQ, YM négatifs ; l'achat systématique de la fenêtre est nul aussi (−1,9 pb) |
| 319 | Les mêmes paris de pentification annoncent la réaction des taux courts et de la livre et du franc suisse au chiffre de l'emploi (fenêtre de 10 min) | Park, FEDS 2019-025, tableau 6 | ÉCARTÉE | 6B (dispo), 6S, ZQ, SR3 (Databento) | β livre 7,5 pb, franc 11,4 pb pour STEEP = 1 (t 2,2-2,3 sur ~30 ans, mensuel) : sur 10 ans (~125 chiffres) t ≈ 1,3 avant frais ; fed funds / Eurodollar t ≈ 3 sur 30 ans → ≈ 1,7 sur 10 ans → sous 3 |
| 320 | Les taux britanniques montent dans les 2 jours avant les chiffres macro (emploi, inflation) et la Banque d'Angleterre, surtout les semaines d'émission | Lou, Pinter, Üslü & Walker, BRI WP / BoE SWP (« Bond supply, yield drifts and liquidity provision before macroeconomic announcements », résumé lu le 2026-10-25) | ÉCARTÉE | gilts (ICE), ZN / ZB | extension du n° 171 (mêmes auteurs) aux chiffres macro ; gilts à l'ICE (aucune prop firm) ; version américaine contredite (Pan & Peng, n° 53 : ~5 pb par réunion, puissance trop faible) |
| 321 | Le volume des actions baisse avant le FOMC et remonte après ; il explique un tiers de la dérive d'avant le FOMC | BRI WP « Volume dynamics around FOMC announcements » (résumé lu le 2026-10-25) | ÉCARTÉE | ES | explique la dérive d'avant le FOMC, rejetée trois fois (n° 8) ; aucune règle de prix nouvelle |
| 322 | **Le Nikkei monte dans les jours qui précèdent les décisions de la Banque du Japon, culmine juste avant et ne continue pas après** (plus fort quand la volatilité implicite est haute avant la réunion) | Maeda 2026, « The Pre-BOJ Announcement Drift » (SSRN 7356758, résumé lu le 2026-10-25 ; auteur seul, affiliation inconnue, texte introuvable) | **OUVERTE** ★ | NKD (CME, permis chez Topstep) ; Nikkei HistData JPXJPY déjà dans `.cache/` | contre-papier : Brusa, Savor & Wilson (n° 173 : pas de dérive avant les banques centrales autres que la Fed) ; la dérive d'APRÈS la BoJ est rejetée (n° 81, 6J 4) ; tenue de plusieurs jours → version conforme = séances de Tokyo seulement (nuit à New York), à plat à 16:10 ; aucun chiffre dans le résumé : puissance impossible sans le texte (critères 3 et 6) |
| 323 | Actions et matières premières chinoises montent dans les 48 h avant les annonces du gouvernement chinois | Wang, Wang & Xu 2026, « Cross-Asset Pre-Announcement Premia in China » (SSRN 6751458, résumé lu) | **OUVERTE** ★ | futures chinois (aucune prop firm) | texte introuvable ; même famille que la dérive d'avant le FOMC (n° 8, rejetée sur l'ES) |
| 324 | Futures : acheter ceux qui ont le plus baissé la nuit et vendre ceux qui ont le plus monté, de l'ouverture à la clôture (retournement nuit → journée en coupe transversale) | Della Corte, Kosowski & Wang 2015, « Market Closure and Short-Term Reversal » (SSRN 2730304, 1982-2014 ; résumé CXO lu) | **OUVERTE** ★ (faible) | dispo (nos 9 contrats) | texte bloqué (SSRN) ; sur les futures, effet « nettement plus faible » que sur les actions, chiffres bruts, rotation de 100 % par jour, aucun chiffre lisible pour le calcul de puissance ; version série temporelle sur les indices américains : n° 169 |
| 325 | Obligations d'État : achat le dernier jour du mois au prorata de la duration (rééquilibrage des indices), pic à la photo de l'indice (16:00 depuis 2021) | Soebhag, Verwijmeren & Martinetti 2026, « Buying Duration » (SSRN 7601879, résumé lu) | ÉCARTÉE | ZB, UB (Databento) | 1,19 pb le dernier jour du mois : t attendu ≈ 1,9 (ZB), 2,2 (UB) < 3 ; famille déjà rejetée (`fin_de_mois_taux.py`) |
| 326 | Réaction des actions au FOMC plus forte en récession | Ryabinin 2023 (SSRN) | ÉCARTÉE | ES | la récession n'est connue qu'après coup (datation NBER) ; réaction APRÈS l'annonce, sens inconnu à l'avance |
| 327 | Futures bitcoin et ether du CME : rafale de volume et d'écart à la réouverture du dimanche | Lee 2026, « What Recedes and What Remains When Markets Go 24/7 » (SSRN 7546659, résumé lu) | ÉCARTÉE | MBT, MET | l'auteur ne trouve aucune composante de prix persistante (le déséquilibre des premières secondes ne prévoit rien) ; le CME cote en continu depuis mai 2026 : plus de réouverture |
| 328 | Momentum des notes à 2 ans le long du cycle de la Fed | Vojtko & Dujava 2026 (Quantpedia, SSRN 6344979) | ÉCARTÉE | ZT (Databento) | note de praticiens (critère 1) ; horizon mensuel (pas intraday) |
| 329 | « Momentum du même jour de la semaine » : 70 % du momentum des actions vient des rendements passés du même jour de la semaine (flux saisonniers des fonds) | Da & Zhang, AFA 2026 (SSRN 4806275 ; texte complet lu le 2026-10-25, site de Notre Dame) | ÉCARTÉE | — | coupe transversale de milliers d'actions, rotation quotidienne ; aucune version sur indice ou futures dans le texte ; l'effet jour de la semaine sur l'indice est déjà écarté (n° 215) |
| 330 | Le retournement du lundi vient de l'après-midi : les actions qui montent le lundi après-midi baissent le reste de la semaine | Pigorsch & Schäfer, *Finance Research Letters* 2024 (résumé lu ; actions américaines 2007-2022) | ÉCARTÉE | — | coupe transversale d'actions, tenue de plusieurs jours ; la version indice (lundi, après-midi) est déjà rejetée (n° 30, 215) |
| 331 | Futures d'indices de 11 pays : acheter les perdants du mois (stratégie contrarienne), surtout en marché haussier | Tse, *J. Futures Markets* 2017 (résumé lu ; 1988-2016) | ÉCARTÉE | FDAX, NKD, ES… | horizon mensuel (pas intraday) |
| 332 | Les particuliers allemands achètent des produits à levier sur le DAX à contre-tendance, tick par tick, et perdent le jour même | Baule, Frijns & Schlie, *J. Futures Markets* 2024 (résumé lu) | ÉCARTÉE | FDAX (dispo) | les pertes viennent de l'écart achat-vente et du mauvais minutage ; aucun effet sur le prix du DAX à exploiter |
| 333 | Pétrole : mouvement de prix pendant la fenêtre d'évaluation de Platts (16:00-16:30 Londres pour le Brent, 14:00-14:30 ET aux États-Unis) | méthodologies S&P Global Platts, blogs | ÉCARTÉE | CL (dispo) | critère 1 : aucune étude du rendement des futures autour de la fenêtre (seulement une volatilité accrue, selon un blog) ; la minute de règlement du CL est déjà couverte |
| 334 | L'outil FedWatch du CME prévoit la décision du FOMC mieux que les fed funds et rapporte en tradant réunion par réunion ; sa popularité réduit la dérive d'avant le FOMC | Bonini, Huang & Simaan, *J. Futures Markets* 2025 (résumé lu) | ÉCARTÉE | ZQ (Databento) | prévision 30 jours avant la réunion : tenue de plusieurs semaines (pas intraday) ; **contre-papier de plus pour la dérive d'avant le FOMC** (n° 8, 318) |
| 335 | Cycles de 2 et 6 semaines des actions liés aux réunions de la Fed : portefeuille investi une semaine sur deux | Ortu, Reggiani & Severino, *Quarterly J. of Finance* 2025 (résumé lu) | ÉCARTÉE | ES (dispo) | même famille que le cycle du FOMC (Cieslak, Morse & Vissing-Jorgensen), déjà rejeté (`cycle_fomc`) ; tenue d'une semaine |
| 336 | Après une chute de 3-4 % du Nasdaq, les actions taïwanaises qui baissent de plus de 7 % sans toucher la limite rebondissent | Lin, Lin, Huang & Lin, *Finance Research Letters* 2024 (résumé lu) | ÉCARTÉE | actions de Taïwan | actions individuelles, pas d'indice ni de futures ; événement rare |
| 337 | Les actions coréennes très détenues par les étrangers gagnent les jours du FOMC (pas ceux de la Banque de Corée) | Bae, Kang & Lee, *Bulletin of Economic Research* 2025 (résumé lu) | ÉCARTÉE | — | coupe transversale d'actions coréennes ; famille de la prime du jour du FOMC, rejetée sur l'ES (n° 8) |

**Crible par citations récentes, 2e passage (2026-10-25, aucun essai).** OpenCitations sur 28 papiers sources, version
publiée en revue cette fois (le 1er passage avait parfois pris la version SSRN, mal couverte) : les 14 du 1er crible
plus le fixing de Tokyo (Ito & Yamada), Brusa, Savor & Wilson, Bogousslavsky (2016, 2021), les stratégies de
Zarattini (zone de bruit, ORB), la « drift burst ». 264 papiers citants depuis 2024, dont 138 nouveaux. Déjà au
registre : Iwanaga 2026 (n° 249, Nikkei après le S&P), achats d'ETF de la BoJ (n° 36, Ko 2026), nuit des métaux
chinois (n° 305), café (n° 139, 254), dérives des taux avant les chiffres (n° 320), devises après le FOMC (n° 170).
Crossref (12 requêtes : DAX, FTSE, Euro Stoxx, Nikkei, Hang Seng, Bund, BCE, déjeuner, échéances Eurex) : rien de
nouveau. **Aucune candidate nouvelle.** n° 330 à 337.

**Crible SSRN par marché et programmes des congrès 2026 (2026-10-25, aucun essai).** Crossref, prépublications SSRN
(préfixe 10.2139), 2 balayages : 1 472 puis 825 titres nouveaux (Nikkei, DAX, Bund, JGB, or, cuivre, gaz, soja, OPEP,
EIA, bitcoin du CME, Hang Seng, Nifty, Taïwan, devises, VIX, FOMC, SOFR, BCE, BoJ, CPI, emploi, échéances, sorcières,
reconstitutions, tendance, portage, COT) ; programmes complets de l'AFA (ASSA, janvier 2026), du WFA (juin 2026) et de
l'EFA (août 2026 ; textes complets téléchargeables sur ConfTool). Presque tout est déjà au registre : Fetna 2026 (n° 122,
contre-papier de l'ORB), Pan & Peng (n° 53, aussi présenté à l'AFA 2026), Fleming, Liu & Nguyen (n° 50, présenté à
l'EFA 2026), Ladia (n° 118), Aleti, Bollerslev & Siggaard (n° 44, 234), échéance du bitcoin (n° 104, 151), dérive avant
la BCE de Quantpedia (n° 173). Contre-papiers notés : **Song 2026** (SSRN 7412318 : la dérive d'avant le FOMC disparaît
dès l'arrivée des options 0DTE du mercredi, ce qui confirme les rejets n° 8 et 318) ; Mahadzva 2026 (SSRN 7435081 :
cassure d'ouverture perdante sur 4 devises, hors échantillon). **Aucune candidate nouvelle** : trois pistes attendent
leur texte (n° 322-324). n° 322 à 329.

**Crible des documents de travail (2026-10-25, aucun essai).** Titres de 27 séries RePEc relevés en entier : Fed (FEDS, IFDP, New York, et les 11 Fed régionales), BCE, Banque d'Angleterre, Banque du Canada, BRI, Banque du Japon, Banque de France, Banque d'Italie, RBA, RBNZ, BNS, OFR, NBER et CEPR (les 11 683 plus récents de chacun) : ~48 000 titres, ~1 000 après filtre de mots (futures, intraday, annonce, FOMC, fixing, adjudication, dérive, spéculateurs…), lus au titre ; 20 résumés lus. Tout ce qui décrit un effet de prix jouable est **déjà au registre** : fixings de change (n° 78, 89), gilts avant la BoE (171), dérive de nuit (7), momentum monétaire (101), incertitude avant les annonces (110), dividendes (167), dérive après le FOMC (54, 166), rééquilibrage 60/40 (14), adjudications (50, 271), dérive avant les chiffres (12, 56), paris de pentification et emploi (318, 319). n° 320 et 321 ajoutées et écartées. **Aucune candidate nouvelle.**

**Crible large tous marchés (2026-10-25, demande « continue jusqu'à 10 candidates » ; aucun essai).** 60 requêtes
Crossref (calendrier, événements, heures, enchères, banques centrales, devises émergentes, indices d'Asie, d'Europe,
d'Amérique latine) → 1 329 titres, 195 dans des revues sérieuses avec un mot de rendement dans le titre ; lus au titre,
13 résumés. Recherches web ciblées : Corée, Taïwan, Japon (achats d'ETF de la BoJ, arrêtés en 2024), Hong Kong, Chine
(fêtes), Inde, Brésil, options 0DTE, perpétuels crypto (heures de financement : n° 149), ETF bitcoin. **Aucune
candidate nouvelle.** Seule candidate au sens des critères 1 à 6 dans tout le registre : **n° 191** (t attendu 3,29,
bloquée par les comptes d'articles Factiva, payants). n° 310 à 317.

**Crible des futures chinois et des autres marchés (2026-10-25, demande d'élargir à tous les marchés, papiers anciens
permis s'ils survivent ; aucun essai).** 18 requêtes Crossref (Chine, Corée, Hong Kong, Taïwan, Inde, Eurex,
émergents) → ~700 titres, ~130 retenus au titre. Deux textes complets lus (Jin et al. 2020 ; Bouri et al.).
**Aucune candidate ne passe le calcul de puissance** ; deux pistes attendent leur texte (n° 306, 307). Rappel
pratique : aucune prop firm ne propose les futures chinois ; SHFE, DCE et ZCE ne sont ouverts aux étrangers que pour
quelques contrats « internationalisés » (pétrole SC, cuivre BC, fioul, caoutchouc 20#, minerai de fer, PTA, huile de
palme…). n° 304 à 309.

**Crible Crossref des revues 2022-2026 sur les futures autres que les nôtres (2026-10-25, aucun essai).** 16 requêtes
(momentum et saisonnalité intraday des matières premières, des taux, des devises ; nuit ; fenêtre de règlement) →
~600 titres, 85 avec « intraday », « overnight » ou « settlement » dans le titre. Hors Chine, volatilité, liquidité ou
prévision par réseaux de neurones, il ne reste que des papiers déjà au registre (Brent n° 64, café n° 139 et 254,
VIX n° 141, Rosa n° 238, pétrole EIA n° 63, momentum mondial n° 37, Nikkei n° 249). **Aucune candidate nouvelle** ;
n° 297 à 301.

**Recherche contrat par contrat, futures CME intraday (2026-10-25, demande de rester sur les futures CME en
intraday ; aucun essai).** Recherches web ciblées : SOFR et fed funds, ZN en fin de séance (15:00 et 16:00), gaz
(fenêtre de règlement, rapport de stocks), maïs et soja (WASDE, minute de règlement), bétail (rapports USDA), argent
(fixing), cuivre, 6C, 6S, 6M, RTY, échéances d'options (ZN, CL), cassure d'ouverture et bandes de bruit sur d'autres
contrats. **Aucune candidate ne passe les critères 1 à 6** : les effets documentés sont sur la volatilité, dépendent
d'une surprise inconnue à l'avance, sont anciens, ou n'ont pas d'étude. n° 286 à 296.

**Crible du 2026-10-25 (aucun essai).** Crossref (OpenAlex a épuisé son quota gratuit du jour) : 41 requêtes par
classe d'actifs (taux, énergie, métaux, agricoles, indices, devises, divers ; 853 articles depuis 2016) et 15 requêtes
d'événements (échéance, règlement, roulement, saisonnalité, rapport, adjudication, week-end, jours fériés, heure de la
journée…) dans 18 revues (*JF*, *JFE*, *RFS*, *JFQA*, *Management Science*, *Review of Finance*, *J. Futures Markets*,
*J. Commodity Markets*, *Energy Economics*, *AJAE*, *J. Fixed Income*, *JBF*, *J. Empirical Finance*, *JIMF*,
*J. Financial Markets*, *Quantitative Finance*, *JIFMIM*, *FRL* ; 1 693 articles) ; arXiv (10 requêtes). Recherches
directes : Bund et BCE, adjudications de la zone euro, Trésor la nuit, grains la nuit, gaz le lundi, cuivre et
Shanghai, échéance du gaz, Trésor et heures asiatiques. **Aucune candidate ne passe les critères 1 à 6** ; n° 270 à 285.

## 8. Tests faits sur simple résumé, à relire (décision du 2026-10-21)

| Test | Papier à relire en entier | Ce qu'on compare |
|---|---|---|
| N1, E2 | Li, Sakkas & Urquhart, *J. Financial Markets* 2022 — **relu en entier le 2026-10-22** | même règle que N1 / E2 (signe de la 1re demi-heure → dernière demi-heure, clôture locale) : pas de nouveau test ; Japon 0,72 et Royaume-Uni 0,51 de Sharpe sans coûts sur 2005-2017 |
| H1, A1 | Wei 2026 | heures des séances, signal |
| H12 | Padyšák & Vojtko 2022 ; Wen et al. 2022 | heures UTC, filtres |
| J1, D1, H13 | (règle de NQ 1-A, pas de papier externe) | sans objet |

## 9. Hypothèses OUVERTES, classées de la plus probablement fiable à la moins

| Rang | # | Hypothèse | Fiabilité a priori | Bloquée par |
|---|---|---|---|---|
| 1 | 49 | ORB NQ rejouée sur 2010-2015 (pas un essai) | ★★★★ | Databento ; simulation du 2026-10-23 : déflaté ~0,91 si 2010-2015 ressemble à 2016-2026, une chance sur trois de passer 0,95 |
| — | 58 | Gaz : jours du rapport de stocks EIA | écartée | texte lu : effet disparu après 2011 (Sharpe net −0,16), t attendu ≈ −0,4 |
| — | 50 | Cycle des adjudications du Trésor | écartée | t attendu ≈ 0,35 (ZB), gain net négatif (ZN) |
| — | 51 | Momentum de fin de séance sur les obligations et les matières premières | écartée | texte lu le 2026-10-23 : ~0,9 pb brut par jour sur les obligations contre ~3,3 pb de frais |
| — | 39 | ETF sectoriels de nuit → futures d'indices | rejetée | essai n° 431 (`etf_nuit`) |
| 6 | 59-60 | Gaz : dérive avant le rapport, retour après une surprise | ★★ | Databento + consensus payant |
| — | 52 | Fin de mois du Trésor, partie de jour, sur ZN | écartée | 2026-10-25 : puissance < 3 avec 129 mois (critère 6) |
| — | 54-55, 57 | Taux après le FOMC, prime des jours d'annonce | écartées | 2026-10-25 : n° 55 t attendu ≤ 0,93 sur 2016-2026 (SR 1188 lu) ; n° 57 disparue après la crise (Balduzzi & Moneta 2017) ; n° 54 tenue de plusieurs semaines |
| 9 | 45, 74, 75 | Répliques des règles retenues sur RTY, SI, HG (n° 89, devises : écartée le 2026-10-25, t attendu ≤ 2,29) | ★ | Databento |
| — | 61 | Roulement GSCI sur NG / HG | écartée | 2026-10-25 : tenue de plusieurs jours ; pas de gain après coûts (Dubois & Maréchal) |
| — | 47 | Échéance du VIX | écartée | 2026-10-25 : effet mesuré sur les options, pas sur l'indice (critère 6) ; n° 40 : t publié ≈ 2,5 < 3 |
| 13 | 105 | Pression avant l'échéance du WTI (n° 101 écartée le 2026-10-25 : tenue de plusieurs semaines) | ★ | Databento ; texte de 2023 non publié, construit sur avril 2020 |
| 5 | 191 | Grappes de résultats des entreprises médiatisées (24 h avant, S&P) | ★★ | comptes d'articles Factiva (payants ; les horaires des résultats sont gratuits sur l'EDGAR) ; puissance 3,29 avec la règle du papier, 1,82 avec la capitalisation (gratuite) |
| 14 | 102, 103, 100 | Basis-momentum, portage des matières premières, aimantation des futures S&P | ★ | taille du compte ou données d'options payantes |

Bilan : 337 hypothèses inventoriées ; 3 RETENUES (S1, H5, Gotobi) ; 5 FIABLES NON RETENUES (ORB, NQ 1-A, or la nuit,
boombitch MBT, boombitch YM) ; 23 OUVERTES au 2026-10-25 (crible par citations récentes, 2e passage : n° 330-337 écartées ; crible SSRN par marché et congrès AFA, WFA, EFA 2026 : n° 322-324 ajoutées, textes introuvables, n° 325-329 écartées ; **n° 318 testée le 2026-10-25 (essai n° 435) : REJETÉE** ; crible des documents de travail de 27 séries (banques centrales, NBER, CEPR) : n° 320-321 écartées, aucune candidate nouvelle ; n° 310 ajoutée, KOSPI, texte payant ; n° 281 rouverte, JGB, résumé introuvable ; café n° 139, VIX n° 141, gilts n° 171 réexaminés et écartés ; n° 306 et 307 ajoutées, futures chinois, textes introuvables ; n° 47, 52, 54, 55, 57, 61, 89 et 101 écartées le 2026-10-25 : tenue de plusieurs semaines, t attendu ≤ 1,6, papiers contraires ; n° 283 ajoutée, texte introuvable ; n° 230 et 235 ajoutées, textes introuvables ; n° 40 écartée au calcul de puissance ; n° 191 : substitut gratuit GDELT vérifié, t attendu 2,99 < 3 ; n° 191 ajoutée, bloquée par des données payantes ; n° 51 écartée le 2026-10-23 après lecture du texte complet, n° 142
contredite). Tri du 2026-10-23 (n° 165, 166 ajoutées et écartées ; crible des revues 2022-2026 et des citations récentes : n° 167-171 ajoutées et écartées ; crible des heures vides du groupe (23:30-9:30 et 18:00-19:00 ET hors gotobi) : n° 172-182 ajoutées et écartées, la n° 172, testée par dérogation le 2026-10-24 (essai n° 434), est rejetée : réelle sur 2016-2020, éteinte depuis 2021 ; crible des autres marchés que nous avons (or, pétrole, devises, crypto) du 2026-10-24 : n° 183-190 ajoutées et écartées) et classement des données à acheter :
`tri_hypotheses_donnees.md` — seul achat utile : NQ, 6J, GC de 2010 à 2015 pour contrôler S1 et Gotobi. Le 2026-10-22, les trois seules jouables sans achat et lisibles (n° 85,
104, 110) ont été lues en entier : toutes écartées au calcul de puissance ou faute d'effet stable, aucun essai. Les trois
restantes sans achat (n° 39, 40, 47) sont bloquées (texte payant, prépublication, effet mesuré sur un autre objet).
Classement validé par l'utilisateur : n° 1 ORB 2010-2015, n° 2 gaz. Le gaz (n° 58) est écarté le 2026-10-22 après
lecture du texte complet : l'ORB 2010-2015 reste la seule piste ouverte qui justifie un achat.
