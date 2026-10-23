# Tri des hypothèses et choix des données à acheter (2026-10-23)

Demande de l'utilisateur : trier les hypothèses et stratégies, puis voir quelles données achetées seraient les plus
rentables à tester. Pour chaque idée : le papier montre-t-il un effet qui tient sur le long terme, un papier le
contredit-il, l'idée est-elle encore pertinente (cause présente aujourd'hui, jouable en prop firm), et le calcul de
puissance (critère 6) passe-t-il ? **Aucun essai compté** (compteur toujours à 433).

Coûts du critère 8 (1 tick + 2,50 $ par côté), aller-retour : ZT ~1,0 pb, ZF ~1,9 pb, ZN ~3,3 pb, ZB ~5,8 pb, UB ~5,4 pb,
ZC ~11 pb, MBT ~7 pb.

## 1. Confirmations sur 2010-2015 (règles figées, pas un nouvel essai)

Le jeu Databento GLBX.MDP3 commence en juin 2010 : 5,5 ans jamais vus pour toutes nos stratégies. Simulation du
2026-10-23 (séries de `Dashboard/donnees/`, `prop_combinaisons.dsr`, rendements tirés dans la série de chaque stratégie, 100 tirages, 433 essais) : Sharpe déflaté si
2010-2015 ressemble à 2016-2026 (« pareil ») ou ne rapporte que la moitié (« à moitié »). Ce n'est PAS un résultat.

| Stratégie | Déflaté actuel | + 5,5 ans pareils | + 5,5 ans à moitié | Chance de passer 0,95 (pareil / moitié) | Papier : preuve long terme | Contre | Données |
|---|---|---|---|---|---|---|---|
| S1 Noise Area NQ (en direct) | 0,96 | 1,00 | 0,97 | 95 % / 63 % | Zarattini, Aziz & Barbon 2024 : SPY 2007-2024 | Paz 2026 (SPY après 05/2024 : 0,39) ; appuis Chuk 2026, Delgado 2026 | NQ |
| Gotobi 6J (en direct) | 0,97 | 1,00 | 0,98 | 100 % / 68 % | Ito & Yamada 2017 ; Krohn et al., *JF* 2024 (1999-2018) | aucun trouvé | 6J |
| ORB NQ | 0,70 | 0,91 | 0,74 | 34 % / 4 % | papier 2016-2023 seulement | Fetna 2026 (prépublication ; son argument est réfuté pour notre version par le contrôle « ancre au hasard ») | NQ |
| Or la nuit GC | 0,74 | 0,93 | 0,76 | 42 % / 7 % | Blose & Gondhalekar 2014 (son échantillon couvre déjà 2010-2013) | — | GC |
| NQ 1-A | 0,32 | 0,55 | 0,34 | 4 % / 0 % | aucun papier | — | NQ |

Lecture : 2010-2015 **ne crée probablement pas** de 3e stratégie (l'ORB n'a qu'une chance sur trois, même si elle se
comporte aussi bien qu'aujourd'hui). Sa vraie valeur est de **contrôler les deux stratégies en direct** sur des données
jamais vues : si S1 ou Gotobi s'effondrent sur 2010-2015, c'est une alerte avant d'engager un compte réel.

## 2. Hypothèses nouvelles ou ouvertes qui demandent des données à acheter

| # | Hypothèse | Papier | Long terme d'après le papier | Papiers contraires | Pertinence | Puissance | Verdict |
|---|---|---|---|---|---|---|---|
| 165 | Les obligations du Trésor montent la veille de l'annonce trimestrielle de refinancement (vendredi avant le lundi 15:00) | Wang (Notre Dame) & Zhao (OFR), prépublication SocArXiv 2024, lue en entier | 1991-2023, plus fort depuis 2003 ; mais t propre au papier sur 2003-2023 : 10 ans 2,5, 30 ans 1,5 (non significatif) ; le « Sharpe de 4 » vient d'une annualisation par 252 jours pour 4 jours par an | aucun trouvé ; l'effet s'inverse en récession (−30 pb sur 30 ans) | cause plausible (incertitude budgétaire, en hausse) ; jouable en prop (achat jeudi 18:00, vente vendredi avant 16:10) | effet du papier 2003-2023 moins nos coûts, 43 annonces 2016-2026 (67 depuis 2010) : ZT 1,0 (1,3) ; **ZF 1,5 (1,8)** ; ZN 1,2 (1,6) ; ZB 0,7 (0,8) ; UB 0,7 (0,9) | ÉCARTÉE : t < 2 (événement rare) partout, source non relue par un comité |
| 166 | Les taux continuent dans le sens de la surprise du FOMC pendant 2 à 7 semaines | Brooks, Katz & Lustig, NBER 2019 (AQR, Stanford ; 1989-2008) ; Indriawan, Jiao & Tse, *JBF* 2021 (après 2008, texte payant) | échantillon de BKL d'avant 2009 ; Indriawan confirme une dérive d'environ 15 jours mais ses chiffres ne sont pas publics | Indriawan : aucune dérive AVANT le FOMC | demande une mesure de surprise (futures fed funds) ; tenue de plusieurs semaines → version conforme = sortir chaque vendredi, soit ~10 allers-retours par signal (~33 pb sur ZN) | surprises récentes de 2 à 5 pb → ~20-50 pb de dérive contre ~280 pb d'écart-type sur 50 jours : t ≈ 0 | ÉCARTÉE |
| 51 | Momentum de fin de séance (taux, or, pétrole, gaz, grains, bétail) | Baltussen et al., *JFE* 2021, lu en entier | 1974-2020, pente sur les taux divisée par deux depuis 2000 | les auteurs : sans doute pas exploitable après frais | — | ~0,9 pb brut par jour (taux) contre ~3,3 pb de frais | ÉCARTÉE (2026-10-23) |
| 142 | Rééquilibrage annuel du GSCI / BCOM en janvier | Yan, Irwin & Sanders 2022 | — | **Yan & Irwin 2016 et 2017 (AgEcon)** : rendements nuls pendant le rééquilibrage, aucun lien causal | flux connu d'avance, donc absorbé par des contreparties | — | ÉCARTÉE (contredite) |
| 61 | Roulement du GSCI sur NG / HG | Mou 2010 | affaibli après 2011 | Stoll & Whaley : peu d'impact des roulements ; Yan & Irwin | — | — | ÉCARTÉE |
| 59-60 | Gaz : dérive avant le rapport EIA, retour après une surprise | Halova, Kurov et al., *JFM* 2018 (2008-2016) ; Ederington et al. 2019 | 2008-2016 | Prokopczuk, Wese Simen & Wichmann 2021 : la dérive n'existe que les jours où le stock dépasse les attentes, donc pas prévisible | demande le consensus des analystes (payant) | — | ÉCARTÉE / bloquée |
| — | Grains : dérive avant le WASDE dans le bon sens | Aitkulova, Balsamo & Seamon 2026 (AgEcon) | — | — | le sens dépend de la surprise, inconnue avant | — | ÉCARTÉE |
| — | Grains : momentum intraday | Jin, Kearney, Li & Yang, *JFM* 2020 | — | — | marchés chinois seulement ; rien sur les grains du CBOT | — | ÉCARTÉE |
| — | Bétail : rapports Hogs and Pigs | AgEcon (anciens) | — | marché du porc jugé efficace | — | — | ÉCARTÉE |
| 50, 52 | Adjudications du Trésor ; fin de mois du Trésor sur ZN | Fleming, Liu & Nguyen 2026 ; Hartley & Schwarz 2019 | — | — | — | t ≈ 0,35 ; t ≈ 2 | ÉCARTÉES (déjà au registre) |
| 45, 74, 75, 89 | Répliques de S1, H5, ORB sur RTY, SI, HG, 6C… | aucun papier sur ces contrats | — | répliques déjà ratées sur ES, YM, DAX, GC, CL, devises | — | **impossible** : le critère 6 exige l'effet mesuré par un papier sur le même contrat | bloquées par la méthode |

Sources lues ou consultées : [Baltussen et al. 2021](https://www3.nd.edu/~zda/intramom.pdf) ;
[Wang & Zhao 2024](https://ideas.repec.org/p/osf/socarx/xucf8.html) ;
[Brooks, Katz & Lustig 2019](https://www.nber.org/papers/w25127) ;
[Indriawan, Jiao & Tse 2021](https://ideas.repec.org/a/eee/jbfina/v123y2021ics0378426620302880.html) ;
[Yan & Irwin](https://ageconsearch.umn.edu/record/285846) ;
[Halova, Kurov et al. 2018](https://ideas.repec.org/a/wly/jfutmk/v38y2018i9p1079-1096.html) ;
[Aitkulova et al. 2026](https://doi.org/10.22004/ag.econ.410270) ;
[Jin et al.](https://hull-repository.worktribe.com/output/3295550/intraday-time-series-momentum-evidence-from-china).
Crible OpenAlex du 2026-10-23 : 26 requêtes (gaz, taux, Russell, argent, cuivre, grains, bétail, devises absentes,
roulements, heures de la journée), 483 articles depuis 2015, 172 après filtre, ~15 résumés lus.

## 3. Classement des jeux de données (valeur pour la décision, par dollar)

| Rang | Données | Coût estimé (avant devis) | Ce qu'elles permettent | Verdict |
|---|---|---|---|---|
| 1 | **NQ, 6J, GC de 06/2010 à 12/2015** (ohlcv-1m) | ~20 Mo par contrat et par an → ~0,3 Go, quelques dollars, sans doute couverts par les 125 $ offerts | contrôle de S1 et Gotobi (en direct) et de boombitch NQ sur 5,5 ans jamais vus ; ORB et or la nuit : une chance sur trois environ de passer 0,95 | **à prendre** dès que la clé existe (devis d'abord) |
| 2 | ES, YM, CL, 6E, 6B, 6A de 2010 à 2015 | idem, quelques dollars | même contrôle pour les stratégies rejetées ou les répliques ; aucune candidate à sauver | facultatif |
| 3 | ZT, ZF, ZN, ZB, UB de 2010 à 2026 | ~1-2 Go | seule idée : la veille du refinancement (n° 165), t attendu ≤ 1,8 | **ne pas acheter** pour l'instant |
| 4 | NG, RTY, SI, HG, grains, bétail | ~1 Go | aucune hypothèse ne passe les critères 1 à 6 | **ne pas acheter** |

Conclusion : les papiers lus ne donnent **aucune nouvelle stratégie testable**, même avec des données achetées. L'achat
le plus utile est 2010-2015 sur nos propres contrats, pour vérifier ce qui est déjà en direct. Il faut d'abord une clé
Databento (compte gratuit, 125 $ de crédits) et un devis, sans rien acheter.
