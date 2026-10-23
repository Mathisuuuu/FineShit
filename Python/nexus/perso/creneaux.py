"""Lot « creneaux vides » : strategies futures intraday pour les heures ou les strategies fiables ne sont pas en position.

    python -m nexus.perso.creneaux [--hypotheses H1,H2] [--sortie recherche/resultats_creneaux.txt]

Heures des protocoles et des resultats : approximatives (corrigees a 22:59 ; une premiere version portait par erreur
des heures plus tardives) ; l ordre, protocole puis calcul, est celui des modifications du fichier.
Demande du 2026-10-19 (22:41) : profil horaire sur 1 an des strategies fiables du tableau de bord, puis trouver le plus
de strategies possible qui remplissent les heures vides et passent les filtres (futures, positions soldees dans la
seance CME qui finit a 17:00 New York, fiabilite vectorbt). Methode : memoire « methode-strategie-papiers ».

Profil horaire, 28/08/2025 -> 28/08/2026 (S1 NQ, Gotobi 6J, ORB NQ ; part des jours ouvres avec une position) : 9:30-16:00
New York environ 28 % (NQ), 18:00-22:00 environ 24 % (6J), RIEN de 22:00 a 9:30 ni de 16:00 a 18:00 ; ES, YM, GC, CL, 6E,
6B, 6A jamais utilises.

Criteres communs (fixes avant tout calcul, ceux de la methode) sur les rendements nets par trade de la version V de
chaque hypothese : t >= 3 ; meme signe et t >= 1,5 sur chaque moitie (2016-2020 / 2021-2026) ; Welch >= 2 contre le
temoin ; gain moyen net > 0 ; net > 0 sans les 3 meilleurs trades ; Sharpe deflate >= 0,95 pour le nombre CUMULE
d essais (N_ESSAIS, mis a jour a chaque hypothese ajoutee). En plus, le filtre du tableau de bord (« fiable ») : borne
basse de l IC a 95 % du Sharpe (vectorbt, bootstrap) > 0 et Sharpe > 0 sur les deux moities, sur la serie quotidienne
nette. Couts : 1 tick par cote + 2,50 $ par contrat et par cote ; stress 2 ticks. Prix a une heure H = ouverture de la
barre minute qui commence a H (sinon cloture d une barre finie dans les 5 minutes) ; trade exclu si l echeance change
dans la fenetre ; rendement = variation du prix ajuste / prix reel d entree.

-------------------------------------------------------------------------------------------------------------------------
H1 - OR : MOMENTUM D UNE SESSION A L AUTRE, ASIE ET EUROPE (protocole ecrit le 2026-10-19 vers 22:45, avant tout calcul)
-------------------------------------------------------------------------------------------------------------------------
Sources (texte complet inaccessible : SSRN bloque par une verification anti-robots ; resume du catalogue = [R]) :
 [WEI26] [R] W. Wei, « Who Moves the Price? Trading-Session Return Decomposition and Cross-Session Momentum in Gold and
         Silver Markets », SSRN 7257240, 2026 : XAU/USD horaire, 22/07/2024 -> 07/08/2026 ; sessions Asie 00:00-08:00
         UTC, Europe 08:00-14:30 UTC, Etats-Unis (avec la fin de soiree) 14:30-24:00 UTC. L Asie fait 77 % du rendement
         cumule de l or, l Europe +36 %, les Etats-Unis -13 %. Momentum d une session a la suivante (autocorrelation
         +0,13), concentre dans la continuation VERS l Asie. Apres 0,02 % par changement de position, seule la version
         ACHETEUSE survit : Sharpe net 1,68 sur l or. Le momentum a l interieur de la session americaine perd.
 [BG14]  [T, fiche « or la nuit », nexus/or_nuit.py] Blose & Gondhalekar 2014 : l or monte hors de la seance du COMEX.
         Chez nous, achat 18:00 -> 3:00 New York sans condition : Sharpe 0,38 (2016-2026) ; regle publiee (nuit
         entiere, a travers la cloture) 1,11 mais non intraday.
Lecture : l echantillon du papier (2024-2026, l or +81 %) est une periode de hausse ; 2016-2024 est un vrai hors
echantillon (en arriere) pour la regle. Le signal est observe a la fin de la session precedente, la position est
prise a son ouverture : executable. La session americaine traverse la cloture de 17:00 New York : elle est exclue.
Donnees : GC Databento (minutes, ajustement additif des roulements), heures UTC du papier.
Session Asie du jour UTC d : 00:00 -> 08:00 UTC ; Europe : 08:00 -> 14:30 UTC ; session americaine precedente : 14:30
UTC du jour de bourse precedent -> 00:00 UTC du jour d (le lundi, elle contient le week-end et la reouverture du
dimanche : c est l information disponible a l ouverture de l Asie).
ETAPE 1 : rendements moyens des trois sessions par periode (2016-2020 / 2021-2026 / periode du papier 07/2024 ->) et
correlations de signe entre sessions consecutives (Etats-Unis -> Asie, Asie -> Europe), comme [WEI26].
ETAPE 2 :
  V  = achat GC sur la session d Asie (00:00 -> 08:00 UTC) si la session americaine precedente a monte, rien sinon ;
  R1 = la regle acheteuse du papier sans la session americaine : V + achat sur l Europe (08:00 -> 14:30 UTC) si l Asie
       du jour a monte ;
  R0 = achat de l Asie tous les jours (la derive de session, sans signal) ;
  temoin de V = achat de l Asie apres une session americaine en BAISSE (le momentum predit un rendement plus faible) ;
  pas de replique (argent absent des donnees).
  Essais ajoutes : V, R1, R0 -> N_ESSAIS = 381.
RESULTAT (2026-10-19 vers 22:47) : REJETEE (V -1,3 pb net, Sharpe -0,29 ; pas de lien US -> Asie, meme sur 2024-2026).

-------------------------------------------------------------------------------------------------------------------------
H2 - DEVISES : RETOUR DU SAUT DE REOUVERTURE DE 18:00 (protocole ecrit le 2026-10-19 vers 22:49, avant tout calcul)
-------------------------------------------------------------------------------------------------------------------------
Sources (resumes du catalogue SSRN, [R]) :
 [TOL26a] [R] M. Tolusic, « The First Hour: How Foreign Exchange Absorbs Its Daily Gap », SSRN 7135159 / 7356684, 2026 :
          six paires contre dollar, barres horaires 2014-2026, nettes des ecarts : a la reouverture quotidienne, la
          premiere barre ouvre en moyenne 4,8 pips de la cloture precedente (74 % des sauts > 1 pip ; les autres heures
          0,12 pip). Prendre le contre-pied des sauts d au moins 1 pip et tenir UNE heure : facteur de profit net 2,63,
          aucune annee perdante 2019-2026 ; 3,16 a 2 pips, 4,69 a 5 pips ; tenir jusqu a la cloture du jour : 1,18 ; la
          meme regle aux heures 1 a 23 perd toujours (le mecanisme est l enchere de liquidite quotidienne) ; 2014-2018
          marginal a 1 pip.
 [TOL26b] [R] meme auteur, « Observable and Latent Regime Structure in Intraday Gap Reversals », SSRN 6616479, 2026 :
          sur barres FX journalieres, les sauts opposes a la tendance se retournent (FP 1,59, 26 ans, aucune annee
          perdante), ceux dans le sens de la tendance non.
Adaptation aux futures CME (le point faible, annonce avant le calcul) : les futures de devises sont FERMES de 17:00 a
18:00 New York, l heure ou le spot absorbe son saut d apres [TOL26a]. Le saut des futures = ouverture de 18:00 contre
cloture de 16:59 ; il contient le mouvement du spot pendant la fermeture. Le test porte donc sur l enchere de
reouverture DES FUTURES (meme nature : carnet vide, ordres accumules), pas sur le chiffre du papier. A priori : faible.
Donnees : 6E, 6B, 6A, 6J (Databento, minutes), toutes les reouvertures de 18:00 (dimanche a jeudi), heure de New York.
Saut en pips de la paire au comptant : 6E / 6B / 6A : (ouverture - cloture) / 0,0001 ; 6J : USD/JPY = 1 / prix, en
centiemes de yen. Trade exclu si l echeance change entre 16:59 et la sortie.
ETAPE 1 : taille des sauts (moyenne, part >= 1 pip) et pente du rendement 18:00-19:00 sur le saut, par periode.
ETAPE 2 :
  V  = contre-pied du saut >= 1 pip, 18:00 -> 19:00, les quatre devises (une jambe par devise, portefeuille a parts
       egales) ;
  R1 = la meme entree tenue jusqu a la fin de seance (16:59) [TOL26a, variante « jusqu a la cloture »] ;
  R0 = contre-pied de TOUS les sauts (sans seuil), 18:00 -> 19:00 ;
  temoin = contre-pied du micro-saut d une heure ordinaire (ouverture 20:00 contre cloture 19:59), 20:00 -> 21:00, memes
  jours ([TOL26a] : perd) ;
  replique : par devise (pas un essai supplementaire, lecture seulement).
  Essais ajoutes : V, R1, R0 -> N_ESSAIS = 384. Couts : 1 tick + 2,50 $ par cote (stress 2 ticks : l ecart est large a
  la reouverture).
RESULTAT (2026-10-19 vers 22:51) : REJETEE. Le retour existe AVANT couts (+0,64 pb par trade, t 5,8, positif sur les deux
moities) mais il est plus petit que l aller-retour (environ 1,8 pb) : net -1,2 pb, Sharpe -2,75.

-------------------------------------------------------------------------------------------------------------------------
H3 - DAX : CASSURE DU RANGE D OUVERTURE DE XETRA (protocole ecrit le 2026-10-19 vers 22:53, avant tout calcul)
-------------------------------------------------------------------------------------------------------------------------
Pourquoi : la matinee europeenne (3:00-9:30 New York) est vide ; l ORB est un des trois mecanismes fiables du tableau
de bord (NQ) ; le DAX n a jamais ete teste avec (le groupe P1 l a essaye sur les 9 contrats CME seulement, a leur
ouverture americaine) ; ses minutes 2014-2026 sont disponibles depuis ce soir (HistData GRXEUR, controle contre
Dukascopy et FDAX : nexus/perso/dax_cloture.py).
Sources :
 [ZA23]  [R, catalogue SSRN, deja teste sur NQ : rejete apres publication] C. Zarattini, A. Aziz, « Can Day Trading Really
         Be Profitable? », SSRN 4416622, 2023 : ORB 5 minutes sur QQQ 2016-2023. Regle (lue dans le papier pour la
         fiche ORB 2023 du depot) : bougie 9:30-9:35 haussiere -> achat a l ouverture de la bougie suivante, stop au plus
         bas de la bougie d ouverture (baissiere -> vente, stop au plus haut ; doji -> rien) ; sortie a la cloture ;
         risque 1 % du capital par trade, levier 4 au plus.
 [ZBA24] [T, fiche ORB du tableau de bord, nexus/orb.py] Zarattini, Barbon & Aziz 2024 (SSRN 4729284) : ordre stop au
         plus haut (plus bas) de la bougie, stop de protection a 10 % de l ATR 14 jours, filtre de volume relatif >= 100 %.
 [LSU22] [T] Li, Sakkas & Urquhart, JFM 2022 : momentum intrajournalier present sur le DAX (Allemagne, 2005-2017).
Adaptation : ouverture de Xetra 9:00 (heure de Berlin) ; bougie d ouverture 9:00-9:05 ; sortie a 17:30 (fin de la
seance continue de Xetra ; le FDAX continue jusqu a 22:00). HistData n a PAS de volume : le filtre de volume de [ZBA24]
est impossible, d ou la regle de [ZA23] pour V.
Donnees : CFD DAX HistData GRXEUR (prix BID, minutes), jours de Xetra, 02/01/2014 -> 28/08/2026 ; moities avant / apres le
01/01/2021. Execution : entree a l ouverture de la barre de 9:05 ; stop touche si le plus bas (plus haut) d une barre
atteint le niveau, sortie au niveau (ou a l ouverture de la barre si elle est deja au-dela) moins 1 tick ; sinon sortie
a l ouverture de la barre de 17:30. Taille : f = min(1 % / distance du stop en %, 4) du capital ; rendement du jour =
f x (rendement du trade - couts). Couts FDAX : 1 tick (0,5 point) + 2,50 $ par cote, 27,5 $ par point.
ETAPE 1 : rendement 9:05 -> 17:30 dans le sens de la bougie d ouverture (sans stop, 1 contrat), par moitie, et la meme
mesure pour une bougie de 12:00.
ETAPE 2 :
  V  = ORB [ZA23] sur le DAX (ci-dessus) ;
  R1 = regle [ZBA24] sans le filtre de volume : ordre stop au plus haut / plus bas de la bougie (actif des 9:05), stop a
       10 % de l ATR 14 jours de la seance de Xetra, sortie 17:30 ;
  R0 = anomalie brute : sens de la bougie d ouverture x rendement 9:05 -> 17:30, 1 contrat, sans stop ;
  temoin = V avec la bougie de 12:00-12:05 (milieu de seance, sans information d ouverture), entree 12:05, sortie 17:30.
  Essais ajoutes : V, R1, R0 -> N_ESSAIS = 387.
RESULTAT (2026-10-19 vers 22:54) : REJETEE (V +0,5 pb net, Sharpe 0,04 ; avant couts +8,7 pb en 2014-2020 puis +3,0 pb
en 2021-2026 ; stop touche 80 % des jours ; R1 Sharpe 0,22).

-------------------------------------------------------------------------------------------------------------------------
H4 - DAX : ZONE DE BRUIT (REGLE DE S1) SUR LA SEANCE DE XETRA (protocole ecrit le 2026-10-19 vers 22:55, avant tout calcul)
-------------------------------------------------------------------------------------------------------------------------
Pourquoi : S1 (zone de bruit, NQ) est la strategie validee du tableau de bord ; le groupe P1 l a essayee sur les 9
contrats CME (ES et CL >= 1 en 2016-2020 puis echec) mais jamais sur le DAX ; la matinee europeenne est vide.
Sources :
 [ZAB24] [T, fiche 16 et S1 du depot] Zarattini, Aziz & Barbon 2024, « Beat the Market: An Effective Intraday Momentum
         Strategy for S&P500 ETF (SPY) », SSRN 4824172 : bornes = max(ouverture, cloture de la veille) x (1 + sigma) et
         min(...) x (1 - sigma), sigma = ecart moyen absolu au prix d ouverture, a la meme minute, sur 14 seances ;
         controle toutes les 30 min ; au-dessus de la borne haute ET du VWAP -> achat, en dessous de la borne basse ET
         du VWAP -> vente, sinon a plat ; tout ferme le soir ; taille = 2 % de volatilite quotidienne visee, levier 4.
 [S1]    reglage valide sur NQ le 2026-10-15 : sigma sur 30 seances, bande x 1,2, controle toutes les 30 min.
 [LSU22] [T] momentum intrajournalier present sur le DAX 2005-2017.
Adaptation : seance de Xetra 9:00-17:30 (heure de Berlin), controles a 9:30, 10:00 ... 17:00, sortie a 17:30 ; cloture
de la veille = prix de 17:30 de la seance precedente. HistData n a PAS de volume : le VWAP est remplace par la moyenne
simple du prix typique (h + l + c) / 3 depuis 9:00 (TWAP) ; c est un ecart a la regle, annonce ici.
Execution : decision a la cloture de la barre du controle, execution a l ouverture de la barre suivante ; couts FDAX
(1 tick + 2,50 $ par cote et par contrat) sur chaque changement de position ; levier = min(4, 2 % / ecart-type des
rendements de cloture a cloture (17:30) des 14 seances precedentes). Jour retenu si au moins 90 % des minutes existent
(trous comblés par la derniere cloture).
ETAPE 1 : part des controles hors de la zone, et rendement moyen de la position prise jusqu au controle suivant, par
moitie.
ETAPE 2 :
  V  = reglage S1 (sigma 30 seances, bande x 1,2) ;
  R1 = reglage du papier (sigma 14 seances, bande x 1) ;
  R0 = V sans filtre de TWAP et a levier 1 (cassure de la zone seule) ;
  temoin = achat de 9:30 a 17:30 tous les jours, meme levier que V (la derive de la seance, sans signal).
  Essais ajoutes : V, R1, R0 -> N_ESSAIS = 390.
RESULTAT (2026-10-19 vers 22:58) : REJETEE (V +0,7 pb net, Sharpe 0,07 ; avant couts +7,8 pb en 2014-2020, -0,2 pb en
2021-2026 ; R1 0,08). Comme ES et CL dans le groupe P1 : le momentum intrajournalier des indices s est eteint apres 2020,
sauf sur NQ.

-------------------------------------------------------------------------------------------------------------------------
H5 - NQ : BOOMBITCH (TURTLE DONCHIAN) RENDU CONFORME A LA SEANCE (protocole ecrit le 2026-10-19 vers 23:20, avant calcul)
-------------------------------------------------------------------------------------------------------------------------
Pourquoi : la strategie la plus fiable du tableau de bord apres S1 et Gotobi est « boombitch, taille inverse a la
volatilite » (Sharpe 1,46, borne basse de l IC 0,90, Sharpe deflate 98,6 %) ; elle est exclue de l onglet Prop firm
parce que 18 % de ses positions traversent la cloture de 17:00 New York. Elle est en position la nuit (cassures du canal
de 160 barres de 15 min a toute heure) : la rendre conforme remplirait des heures vides.
Sources : [WZH26] [T, fichier boombitch.cs de l utilisateur] Wong Zhen Hao 2026 : Turtle Donchian 160/60 sur barres de
15 min, ATR(80), stop initial 1,5 ATR, stop suiveur 2 ATR, achat seulement ; etude des alternatives du 2026-10-09
(recherche/resultats_alternatives.txt : famille de 7 variantes, PBO 8 %, controles GC 0,75, YM 0,76, ES 0,19).
Regle conforme (aucun parametre nouveau) : memes trades que le runner (resultats/perso_*/trades_*), mais chaque position
encore ouverte a 17:00 New York est vendue a la cloture de 16:59 et rachetee a la reouverture de 18:00 (dimanche 18:00
pour le vendredi), au meme nombre de contrats. Ecart avec l original = - (saut 16:59 -> 18:00) x sens x contrats x
valeur du point - un aller-retour supplementaire par cloture traversee (commission MNQ 0,60 $ + 1 tick par cote, comme
le moteur). Calcul exact a partir des trades ; serie quotidienne = P&L du runner par seance CME corrige, sur 100 000 $.
ETAPE 1 : part des trades qui traversent 17:00, nombre de clotures traversees, part du gain d origine faite dans les
sauts de reouverture.
ETAPE 2 (criteres sur les P&L par trade conformes) :
  V  = « taille inverse a la volatilite (risque 300 $) » conforme ;
  R1 = boombitch d origine (1 MNQ) conforme ;
  R0 = « filtre de tendance 200 j » conforme ;
  temoin = achat d 1 MNQ chaque seance de 18:00 a 16:59 (la derive du Nasdaq, conforme aussi) ;
  Essais ajoutes : V, R1, R0 -> N_ESSAIS = 393.
RESULTAT (2026-10-19 vers 23:05) : RETENUE. V conforme : Sharpe 1,42 [0,86 ; 1,97], moities 1,58 / 1,27, +5,1 pb par
trade (t 4,8), Welch 2,8 contre le temoin, Sharpe deflate 0,98 ; les sauts de reouverture ne pesaient que 2 205 $ sur
132 374 $. R1 (0,95) et R0 (1,04) fiables au sens du tableau de bord mais Sharpe deflate < 0,95. Ajoutee au runner
(DonchianAlt fin_de_seance=True : Sharpe 1,48, 2 953 trades) et au tableau de bord (Sharpe 1,44, IC bas 0,88, deflate
0,983, intraday).

-------------------------------------------------------------------------------------------------------------------------
H6 - REPLIQUE DE H5 SUR LES HUIT AUTRES CONTRATS (protocole ecrit le 2026-10-19 vers 23:16, avant tout calcul)
-------------------------------------------------------------------------------------------------------------------------
Pourquoi : la methode demande une replique sur d autres marches ; ces contrats ne sont utilises par aucune strategie
fiable (profil horaire). Regle de H5 SANS AUCUN CHANGEMENT : Donchian 160 / 60 barres de 15 min, ATR(80), stop initial
1,5 ATR, stop suiveur 2 ATR, achat seulement, risque fixe de 300 $ par trade (taille = 300 $ / (1,5 ATR x valeur du
point), au moins 1 contrat), vendu a la derniere barre de chaque seance CME et rachete a la reouverture avec le meme
stop ; micros MES, MYM, MGC, MCL, M6E, M6B, MJY, M6A (moteur du runner : ordres a l ouverture suivante, 1 tick de
glissement, commission 0,60 $). Deja connu (etude des alternatives, 1 micro fixe, non conforme) : ES 0,19, YM 0,76
(1,24 / 0,44), GC 0,75 (0,44 / 0,95) ; le reste jamais calcule. A priori : l achat seul n a de raison economique que
sur les indices et l or (derive haussiere) ; sur les devises, rien ne justifie le sens acheteur.
Criteres par contrat (ceux du lot, sur les P&L par trade rapportes a 100 000 $) ; temoin = 1 micro achete de 18:00 a
16:59 chaque seance. Essais ajoutes : 8 -> N_ESSAIS = 401.
RESULTAT (2026-10-19 vers 23:20) : aucun contrat retenu. YM fiable au sens du tableau de bord (Sharpe 0,88 [0,32 ; 1,44],
moities 1,35 / 0,43, Welch 2,3) mais Sharpe deflate 0,54 et t 1,0 sur 2021-2026 ; GC 0,60 (IC bas -0,03) ; ES -0,10 ;
CL et les devises fortement negatifs (le sens acheteur n a pas de raison sur les devises, comme prevu). YM ajoute au
runner et au tableau de bord avec cette mention.

-------------------------------------------------------------------------------------------------------------------------
H7 - DAX : REGLE DE H5 SUR LE MICRO-DAX, HEURES DE L EUREX (protocole ecrit le 2026-10-19 vers 23:24, avant tout calcul)
-------------------------------------------------------------------------------------------------------------------------
Pourquoi : la matinee europeenne est vide ; replique supplementaire de la regle retenue, sur un marche hors CME.
Regle de H5 sans changement (Donchian 160 / 60 barres de 15 min, ATR(80), stops 1,5 / 2 ATR, achat seul, risque 300 $
par trade, vente a la derniere barre de chaque seance et rachat a la suivante avec le meme stop), micro-DAX FDXS (1 EUR
le point, 1,10 $ / EUR, tick 1 point, commission 0,60 $). Donnees : CFD DAX HistData (verifie contre Dukascopy et FDAX),
reduites aux heures de l Eurex 01:15-22:00 Berlin (19:15-16:00 New York : a plat avant 17:00 New York), jours de Xetra,
02/01/2014 -> 28/08/2026 ; moities avant / apres le 01/01/2021. Temoin : 1 FDXS achete a l ouverture et vendu a la
cloture de chaque seance. Essai ajoute : 1 -> N_ESSAIS = 402.
RESULTAT (2026-10-19 vers 23:27) : REJETEE (Sharpe 0,03 [-0,53 ; 0,54], moities 0,46 / -0,51 : comme H3 et H4, le DAX
ne garde rien apres 2020).

-------------------------------------------------------------------------------------------------------------------------
H8 - ES : RETOUR APRES LA SORTIE DE LA BANDE DE VOLATILITE IMPLICITE (protocole ecrit le 2026-10-19 vers 23:35, avant calcul)
-------------------------------------------------------------------------------------------------------------------------
Pourquoi : la seance americaine n est couverte que 33 a 37 % des jours, et seulement sur NQ ; ES n est utilise par
aucune strategie fiable. Cause exterieure au prix : la volatilite attendue (VIX), connue la veille.
Source : [SEE26b] [R, catalogue SSRN] L. Seeck, « Volatility as a Signal Switch: Regime-dependent Intraday Mean
Reversion in Nasdaq-100 Futures », SSRN 7364204, 2026 : bande = cloture de la veille x (1 +/- VXN / 16 %) (VXN / 16 =
ecart-type d un jour) ; 860 sorties de bande sur NQ 2018-2026, retour dans la seance 85 % du temps ; Sharpe 0,47 sur
2018-2022, 1,29 sur 2023-2026 (hors echantillon) ; -0,94 sur 2010-2017 sans filtre de regime ; avantage le plus fort
quand VXN >= 30 ; la version momentum (dans le sens de la sortie) est rejetee.
Regle (lecture du resume, au plus simple) : seance 9:30-16:00 New York ; cloture de la veille = derniere cloture de la
seance precedente ; indice de volatilite = cloture officielle CBOE de la veille ; a la premiere barre minute qui CLOT
au-dessus de la borne haute (au-dessous de la borne basse) entre 9:31 et 15:30, vente (achat) a l ouverture de la
minute suivante, sortie a la derniere cloture de la seance ; un trade par jour ; pas de stop (non decrit).
ETAPE 1 : part des sorties de bande, rendement de l entree a la cloture dans le sens du retour, par moitie et par
niveau de l indice (< 20, 20-30, >= 30).
ETAPE 2 :
  V  = ES avec le VIX (replique sur un autre indice : le papier est sur NQ) ;
  R1 = la regle du papier sur NQ avec le VXN (CBOE VXN_History) ;
  R0 = V seulement quand le VIX de la veille est >= 30 (le regime le plus fort du papier) ;
  temoin = la meme regle avec une bande deux fois plus etroite (VIX / 32 : mouvements ordinaires).
  Couts : 1 tick + 2,50 $ par cote, stress 2 ticks. Moities 2016-2020 / 2021-2026. Essais : V, R1, R0 -> N_ESSAIS = 405.
RESULTAT (2026-10-19 vers 23:40) : REJETEE (V -2,7 pb net, Sharpe -0,20 ; pas de retour apres la sortie de bande, ni sur
ES ni sur NQ avec la regle du papier : -0,64 ; le temoin perd aussi).

-------------------------------------------------------------------------------------------------------------------------
H9 - LE FLUX GOTOBI SUR LES AUTRES DEVISES (protocole ecrit le 2026-10-19 vers 23:33, avant tout calcul)
-------------------------------------------------------------------------------------------------------------------------
Pourquoi : la plage 18:00-22:00 New York n est couverte que par Gotobi (6J) ; 6E, 6B, 6A n y sont jamais utilises.
Sources : [IY17] [T, fiche Gotobi du tableau de bord, nexus/gotobi.py] Ito & Yamada 2017 : les jours gotobi, les
importateurs japonais achetent des dollars au fixing de 9:55 (Tokyo) ; les banques se couvrent avant : le dollar monte
avant le fixing et redescend apres. [KMW23] [T: resume, fx_trois.py] Krohn, Mueller & Whelan, Journal of Finance 2023 :
le dollar s apprecie avant les fixings et se deprecie apres, pour les NEUF grandes devises, avec un rendement en W
autour de l horloge. Hypothese : la demande de dollars des jours gotobi se voit aussi contre l euro, la livre et le
dollar australien (le dollar se renchérit contre toutes les devises).
Regle de Gotobi sans changement (heure de Tokyo, jours gotobi de nexus/gotobi.py) : vente de la devise contre dollar
(vente du future) de 08:00 a 09:55, achat de 09:55 a 11:00 ; prix a l ouverture de la minute qui commence a l heure
prevue ; couts 1 tick + 2,50 $ par cote pour chaque jambe.
  V  = 6E, 6B, 6A ensemble (parts egales), les deux jambes ;
  R1 = jambe d avant le fixing seulement (08:00 -> 09:55) ;
  temoin = la meme regle les jours ouvres japonais NON gotobi ;
  controle (pas un essai) : 6J avec la meme mecanique doit retrouver le Gotobi du tableau de bord.
  Moities 2016-2020 / 2021-2026. Essais : V, R1 -> N_ESSAIS = 407.
RESULTAT (2026-10-19 vers 23:33) : REJETEE (Sharpe -1,63 [-2,36 ; -0,92]). Brut +0,78 pb (t 1,99) sur 2016-2020
seulement, nul sur 2021-2026 et pas mieux que les autres jours ; les couts (2 allers-retours) emportent tout. Controle :
6J avec la meme mecanique +2,23 pb net (t 2,96) : on retrouve bien Gotobi, le flux reste propre au yen.

-------------------------------------------------------------------------------------------------------------------------
H10 - OR LA NUIT RENDU CONFORME A LA SEANCE (protocole ecrit le 2026-10-19 vers 23:40, avant ce calcul)
-------------------------------------------------------------------------------------------------------------------------
Pourquoi : la nuit (22:00-9:30 New York) n est couverte que 17 % des jours (NQ seulement). Or la nuit (candidate N1,
Blose & Gondhalekar 2014, Sharpe 1,11) tient l or toute la nuit mais traverse la pause 17:00-18:00 et le week-end.
ATTENTION, PAS UN TEST A L AVEUGLE : la session cloud a deja mesure la version intraday (LISEZMOI § 12 : Sharpe 0,65 ;
permanent 0,80). Ce qui n a jamais ete mesure : l IC vectorbt, les deux moities, le Sharpe deflate et les criteres de la
methode. Comme pour H5, la regle est la variante deja codee, sans aucun changement :
  V  = nexus/or_nuit.py, jambes="asie,soir" : achat 18:00 -> vente 8:20, achat 13:30 -> vente a la derniere minute de la
       seance (16:59), rien pendant la pause ni le week-end ; GC, 100 % du capital, couts du module ;
  R1 = jambe "asie" seule (18:00 -> 8:20) ;
  temoin = la seance du COMEX (jambes="pause", 8:20 -> 13:30), Welch par trade ;
  reference (pas un essai) : or garde toute la seance (jambes="tout", 18:00 -> 16:59) : V doit faire mieux que la simple
  detention de l or pour avoir un interet propre.
  Brut = rendement par trade avant commissions (le demi-tick de glissement reste). Essais : V, R1 -> N_ESSAIS = 409.
RESULTAT (2026-10-19 vers 23:43) : REJETEE par la methode (t 2,1 ; 2016-2020 t 1,1 ; Sharpe deflate 0,19) mais FIABLE au
sens du tableau de bord : Sharpe 0,65 [0,06 ; 1,22], moities 0,34 / 0,88, perte max -31 % ; Welch 2,25 contre la seance
du COMEX ; mieux que l or garde toute la seance (0,48). R1 (asie seule) 0,58, non fiable. Ajoutee au tableau de bord
comme N2 (OrNuit_GC_conforme, statut « testee »), comme la replique YM de H6 : candidate prop firm pour la nuit.
Controle de taille fait ensuite (pas un essai : memes regles, couts du micro) : avec MGC, Sharpe 0,34 [-0,31 ; 0,94],
moities -0,09 / 0,66 : PLUS fiable. N2 ne tient qu avec le contrat GC (environ 340 000 $ de notionnel), trop gros pour la
plupart des comptes prop firm (a 1 % de risque par jour, un compte de 50 000 a 150 000 $ tient 2 a 6 MGC). La fiche N2
du tableau de bord est donc calculee avec MGC : non fiable, hors des combinaisons prop firm. Lecon : verifier chaque
strategie avec le contrat qu un compte prop firm peut vraiment tenir (Gotobi : MJY 0,31, mais un 6J entier passe ;
ORB : MNQ 0,84, fiable).

-------------------------------------------------------------------------------------------------------------------------
H11 - CRYPTO : MICRO BITCOIN ET MICRO ETHER DU CME (MBT, MET) (protocole ecrit le 2026-10-20 vers 10:38, avant calcul)
-------------------------------------------------------------------------------------------------------------------------
Pourquoi : la nuit (22:00-9:30 New York) n est couverte que 17 % des jours ; les contrats de nuit en micro manquaient.
MBT (0,1 BTC) et MET (0,1 ETH) se traitent au CME de 18:00 a 17:00 New York, du dimanche soir au vendredi, et sont
autorises chez Topstep. Accord de l utilisateur le 2026-10-20 pour les donnees Binance.
Sources : [ZPB25] [R : resume et resume detaille de CXO Advisory] Zarattini, Pagani & Barbon 2025, « Catching Crypto
Trends » : ensemble de 9 canaux de Donchian sur les clotures journalieres (5, 10, 20, 30, 60, 90, 150, 250, 360 jours),
achat quand la cloture depasse le plus haut des clotures du canal, stop suiveur = max(stop de la veille, milieu du
canal), chaque position a 25 % de volatilite annuelle (ecart-type des rendements journaliers sur 90 jours), levier 200 %
au plus, moyenne a parts egales, reequilibrage quotidien ; couts etudies de 0,10 a 0,50 % par trade. Et H5 (retenue sur
NQ) : la regle de suivi de tendance 15 min deja validee, repliquee telle quelle, comme H6.
Donnees : Binance au comptant, BTCUSDT et ETHUSDT en barres 1 minute (nexus/binance.py, 08/2017 -> 09/2026), substitut
des futures CME (MBT et MET n existent que depuis 2021 ; en intraday le future suit le comptant, a une base pres).
Seance CME reconstituee : barres gardees du dimanche 18:00 au vendredi 17:00 New York, sans la pause 17:00-18:00 (les
jours feries americains ne sont pas retires : ecart mineur). Horodatage verifie AVANT le calcul contre les barres
Alpaca 15 min (2021-2026).
Couts par cote, en fraction du notionnel, constants (le micro n existait pas avant 2021 ; a son prix d aujourd hui) :
  MBT 3 pb (frais CME ~1,15 $ + compensation ~0,20 $ + courtage ~0,75 $ sur 0,1 BTC a ~80 000 $, + 1/2 tick de 5 $) ;
  MET 15 pb (~0,50 $ sur 0,1 ETH a ~3 500 $, + 1/2 tick de 0,50 $) ; stress : couts x 2.
Regles (aucun reglage nouveau) :
  V  = H5 sur MBT : DonchianAlt(fixed_risk=300, fin_de_seance=True), barres 15 min, reglages de boombitch ; position
       vendue a la derniere barre de la seance, rachetee a la reouverture avec le meme stop ;
  V2 = la meme regle sur MET ;
  R1 = regle ZPB25 sur le bitcoin rendue conforme : clotures journalieres prises a 16:59 New York (tous les jours, le
       comptant cotant le week-end) ; a chaque reouverture de 18:00, exposition = moyenne des 9 positions decidees a la
       cloture de 16:59 du jour ; position tenue jusqu a 16:59 le lendemain puis soldee (un aller-retour par seance,
       paye en entier) ; 365 jours par an pour la volatilite.
  temoin de V et V2 : le meme contrat achete a 18:00 et vendu a 16:59 chaque seance (rendement par seance, memes couts) ;
  temoin de R1 : exposition constante egale a la moyenne de celle de R1 (memes seances, memes couts).
  Mesures : rendement net par trade en fraction du notionnel (V, V2), du capital (R1) ; serie journaliere nette (P&L /
  100 000 $ pour V et V2, rendement du capital pour R1) ; moities 08/2017-2020 / 2021-2026 (coupure du tableau de bord).
  Essais : V, V2, R1 -> N_ESSAIS = 412.
RESULTAT (2026-10-20 vers 10:47) : aucune retenue. V (H5 sur MBT) : Sharpe 1,56 [1,05 ; 2,03], moities 1,40 / 1,71, t 4,07
(moities t 2,73 / 3,03), deflate 1,00, net sans les 3 meilleurs +10,5 pb : REJETEE sur un seul critere, le Welch contre
le temoin (1,39 ; il faut 2 : le bitcoin tenu chaque seance est tres bruite) ; FIABLE au sens du tableau de bord, et
encore avec couts x 2 (0,92). Ajoutee au tableau de bord comme la replique YM (runner : « boombitch conforme a la
seance, micro bitcoin MBT »). Controle sans essai : heure limite 16:10 (Topstep), Sharpe 1,61 [1,16 ; 2,05].
V2 (MET) : -0,74, les couts du micro ether (15 pb par cote) emportent tout. R1 (ZPB25 conforme) : 0,42, rien apres
2020 (moities 1,09 / 0,05), non fiable.

-------------------------------------------------------------------------------------------------------------------------
H12 - BITCOIN : FENETRES COURTES (MBT) (protocole ecrit le 2026-10-20 vers 10:55, avant calcul)
-------------------------------------------------------------------------------------------------------------------------
Pourquoi (demande de l utilisateur du 2026-10-20) : des strategies COURTES, fiables, peu correlees, jugees sur le
rendement par heure en position ; boombitch et H11 (MBT tenu des centaines d heures par an) rapportent trop peu par heure.
Sources : [WBXZ22] [R] Wen, Bouri, Xu & Zhao 2022, « Intraday Return Predictability in the Cryptocurrency Markets :
Momentum, Reversal, or Both » (SSRN 4080253) : bitcoin 2013-2020, la premiere demi-heure du jour prevoit la derniere
(momentum intraday, comme Gao et al. 2018) ; [PV22] [R + regle d une reproduction publique] Padysak & Vojtko 2022,
« Seasonality, Trend-following, and Mean reversion in Bitcoin » (SSRN 4081000) : tenir le bitcoin seulement deux heures
par jour, apres la cloture du NYSE (21:00 -> 23:00 UTC), capte l essentiel de son rendement.
Donnees, seance CME, couts : ceux de H11 (comptant Binance, MBT, 3 pb du notionnel par cote, stress x 2).
  V  = WBXZ22 : jour UTC ; signal = signe du rendement 00:00 -> 00:30 UTC ; position dans ce sens de 23:30 a 00:00 UTC
       (19:30-20:00 New York en ete, 18:30-19:00 en hiver) ; seulement quand la fenetre tombe dans la seance CME (soirs du
       dimanche au jeudi) ; temoin : achat de la meme demi-heure tous les jours ;
  R1 = PV22 : achat de 21:00 a 23:00 UTC, tous les jours ou la seance CME est ouverte, limite aux minutes de la seance
       (la pause 17:00-18:00 New York coupe la fenetre : ete 18:00-19:00, hiver 16:00-17:00 New York) ; temoin : achat de
       09:00 a 11:00 UTC les memes jours.
  Rendement par trade en fraction du notionnel ; serie journaliere a notionnel = capital ; moities 08/2017-2020 / 2021-2026.
  Essais : V, R1 -> N_ESSAIS = 414.
RESULTAT (2026-10-20 vers 11:00) : les deux REJETEES. V : brut -1,5 pb par demi-heure, pas mieux que l achat tous les jours
(Welch 0,18) ; net -7,5 pb. R1 : brut +2,2 pb sur 60 min (la pause du CME coupe la fenetre), net -3,8 pb, -1,08 de
Sharpe sur 2021-2026. Le momentum de la derniere demi-heure et la fenetre d apres la cloture du NYSE ne tiennent pas sur
2017-2026 apres les couts du micro.

-------------------------------------------------------------------------------------------------------------------------
H13 - NQ 1-A ETENDUE A D AUTRES GRANDES CAPITALISATIONS (protocole ecrit le 2026-10-20 vers 11:03, avant tout telechargement)
-------------------------------------------------------------------------------------------------------------------------
Pourquoi : NQ 1-A (strategie courte : 30 min, environ 16 jours par an) est fiable (Sharpe 0,69 [0,16 ; 1,20]) mais rare.
Le mecanisme (diffusion lente des resultats d une tres grande entreprise vers l indice : Hou 2007 ; NQ 1 de l etude des
60 strategies) vaut pour toute grosse valeur du Nasdaq-100 qui publie apres la cloture. Accord de l utilisateur le
2026-10-20 pour les heures des 8-K sur SEC EDGAR.
Liste FIXEE ICI, avant de voir une seule donnee : les valeurs qui ont fait partie des 15 plus gros poids du Nasdaq-100 a
une fin d annee entre 2016 et 2025 et qui publient leurs resultats trimestriels apres la cloture (8-K item 2.02) :
TSLA, AVGO (Broadcom Ltd puis Broadcom Inc.), NFLX, COST, ADBE, AMD, INTC, CSCO. (PEP, CMCSA, TMUS, publient avant
l ouverture ; ASML et AZN deposent des 6-K.)
Donnees : data.sec.gov/submissions (liste des depots, heure « acceptanceDateTime ») ; l heure est controlee AVANT le
calcul contre resultats_megacaps.csv (memes 8-K d AAPL et de NVDA, heure lue sur la page d index) : la difference doit
etre nulle, sinon arret. 8-K gardes : item 2.02, jour de bourse, accepte entre 16:00 et 16:43 New York.
Regle de NQ 1-A sans changement : T = premier 8-K de resultats du jour (toutes les valeurs de la liste) ; signal =
signe de r_NQ(16:00 -> T+15) ; position NQ de T+15 a min(T+45, 16:59) ; couts de l etude (0,68 pb l aller-retour).
  V  = les 6 d origine + les 8 nouvelles ;
  R1 = les 8 nouvelles seulement, les jours sans publication des 6 d origine (l effet s etend-il ?) ;
  temoin : comme NQ 1-A, les autres jours, signal 16:00 -> 16:20, position 16:20 -> 16:50.
  Serie journaliere a notionnel = capital ; moities 2016-2020 / 2021-2026. Essais : V, R1 -> N_ESSAIS = 416.
  Correction apres le telechargement, AVANT tout calcul de rendement (2026-10-20 vers 11:10) : le controle AAPL / NVDA
  passe (44/44, 45/45, ecart nul), mais le champ acceptanceDateTime n a pas la meme convention chez tous les deposants
  (NFLX, INTC, AVGO : UTC vrai ; AAPL, NVDA, CSCO : New York decale deux fois) ; les pages d index qui donnent l heure
  exacte refusent notre User-Agent. Convention choisie par societe et par annee a la majorite (le plus de 8-K de
  resultats entre 15:30 et 17:30) ; aucune donnee de marche n entre dans ce choix (nexus/perso/edgar.py).
RESULTAT (2026-10-20 vers 11:15) : les deux REJETEES. R1 (les 8 nouvelles seules, 156 jours) : -0,59 pb net, negatif sur
les deux moities : aucun effet. V (les 6 + les 8, 317 jours) : +1,36 pb, Sharpe 0,54 [-0,01 ; 1,05], non fiable : les
nouvelles diluent NQ 1-A (reference : 0,69 [0,16 ; 1,20]). L effet est propre aux 6 tres grandes capitalisations, assez
grosses pour faire bouger l indice : NQ 1-A reste telle quelle.
"""
from __future__ import annotations

import argparse
import math
import os
from datetime import datetime

import numpy as np
import pandas as pd

from .or_anomalies import instants
from .soixante import COMMISSION, COUTS, PY_DIR, contrats, exporter, marche, prix_a, tstat

N_ESSAIS, SEUIL_DSR = 427, 0.95
MOITIE = pd.Timestamp("2021-01-01")
UTC = "UTC"


# =============================================================================
#  Outils communs
# =============================================================================
def jours_bourse(m, debut="2016-01-04", fin="2026-08-28") -> pd.DatetimeIndex:
    """Jours UTC du lundi au vendredi avec au moins une barre."""
    j = pd.to_datetime(np.unique(m.t // 86_400_000_000_000) * 86_400_000_000_000)
    j = pd.DatetimeIndex([d for d in j if d.dayofweek < 5])
    return j[(j >= debut) & (j <= fin)]


def rendement(m, ta: np.ndarray, tb: np.ndarray) -> np.ndarray:
    """Rendement simple de A a B (instants ns UTC) : variation du prix ajuste / prix reel en A ; NaN si un prix manque
    ou si l echeance change entre A et B."""
    pa, ia = prix_a(m, ta)
    pb, ib = prix_a(m, tb)
    ok = np.isfinite(pa) & np.isfinite(pb) & (ia >= 0) & (ib >= 0) & (tb > ta)
    cid = contrats(m)
    roll = np.zeros(len(ta), bool)
    roll[ok] = cid[ib[ok]] != cid[ia[ok]]
    off = getattr(m, "offset", None)
    reel = pa - (off[np.clip(ia, 0, None)] if off is not None else 0.0)
    return np.where(ok & ~roll & (reel > 0), (pb - pa) / np.where(reel > 0, reel, np.nan), np.nan)


def prix_reel(m, t: np.ndarray) -> np.ndarray:
    p, i = prix_a(m, t)
    off = getattr(m, "offset", None)
    return p - (off[np.clip(i, 0, None)] if off is not None else 0.0)


def cout_ar(root: str, prix, ticks: float = 1.0):
    """Aller-retour d un contrat en fraction du notionnel."""
    tick, pv, _, _ = COUTS[root]
    return 2 * (ticks * tick + COMMISSION / pv) / prix


def welch(a: pd.Series, b: pd.Series) -> float:
    a, b = pd.Series(a).dropna(), pd.Series(b).dropna()
    if len(a) < 3 or len(b) < 3:
        return math.nan
    se = math.sqrt(a.var(ddof=1) / len(a) + b.var(ddof=1) / len(b))
    return float((a.mean() - b.mean()) / se) if se > 0 else math.nan


def criteres(brut: pd.Series, net: pd.Series, temoin: pd.Series | None) -> dict:
    x = brut.dropna()
    net = net.reindex(x.index)
    n = len(x)
    p1, p2 = x[x.index < MOITIE], x[x.index >= MOITIE]
    t, t1, t2 = tstat(x), tstat(p1), tstat(p2)
    w = welch(x, temoin) if temoin is not None else math.nan
    sans3 = net.drop(net.nlargest(3).index).mean() if n > 3 else math.nan
    annees = net.groupby(net.index.year).sum()
    part = float((annees > 0).mean()) if len(annees) else math.nan
    if n < 60:
        tests = {"t >= 2 (evenement rare)": t >= 2, "gain net positif >= 65 % des annees": part >= 0.65,
                 "t de Welch >= 2 contre le temoin": w >= 2, "gain net > 0 sans les 3 meilleurs trades": sans3 > 0}
    else:
        tests = {"t >= 3": t >= 3, "meme signe et t >= 1,5 sur chaque moitie": t1 >= 1.5 and t2 >= 1.5,
                 "t de Welch >= 2 contre le temoin": w >= 2, "gain moyen net > 0": net.mean() > 0,
                 "gain net > 0 sans les 3 meilleurs trades": sans3 > 0}
    return dict(n=n, moyenne=x.mean() * 1e4, t=t, m1=p1.mean() * 1e4, t1=t1, m2=p2.mean() * 1e4, t2=t2,
                temoin=(temoin.mean() * 1e4 if temoin is not None else None), welch=w, net=net.mean() * 1e4,
                sans3=sans3 * 1e4, part_annees=part, tests=tests, passe=all(tests.values()))


def resume(nom: str, net: pd.Series, jours: pd.DatetimeIndex, pr, quotidien: pd.Series | None = None) -> dict:
    """Statistiques vectorbt de la serie quotidienne nette (zero les jours sans trade) : celles du tableau de bord.
    quotidien : serie journaliere deja agregee (portefeuille de plusieurs jambes) ; net reste la liste des trades."""
    from .. import prop_combinaisons as PC
    x = net.dropna()
    q = quotidien if quotidien is not None else x.groupby(x.index.normalize()).sum().reindex(jours).fillna(0.0)
    m = PC.mesures(q, N_ESSAIS)
    d = dict(nom=nom, n=len(x), moyenne=x.mean() * 1e4, t=tstat(x), t1=tstat(x[x.index < MOITIE]), t2=tstat(x[x.index >= MOITIE]),
             sharpe=m["sharpe"], ic=(m["ic_bas"], m["ic_haut"]), sh1=m["sharpe_p1"], sh2=m["sharpe_p2"], dsr=m["dsr"],
             perte_max=m["perte_max"], fiable=m["fiable"], serie=q)
    pr(f"  {nom:<58} {d['n']:5d} trades | net {d['moyenne']:+6.2f} pb (t {d['t']:+.2f}) | moities t {d['t1']:+.2f} / {d['t2']:+.2f} | "
       f"Sharpe {d['sharpe']:+.2f} [{d['ic'][0]:+.2f} ; {d['ic'][1]:+.2f}] moities {d['sh1']:+.2f} / {d['sh2']:+.2f} | "
       f"deflate {d['dsr']:.2f} | perte max {d['perte_max']:.1%} | {'FIABLE' if d['fiable'] else 'non fiable'}")
    return d


def verdict(pr, nom: str, c: dict, d: dict) -> bool:
    pr(f"CRITERES {nom} ({c['n']} trades) : brut {c['moyenne']:+.2f} pb (t {c['t']:+.2f}) | 2016-2020 {c['m1']:+.2f} (t {c['t1']:+.2f}) | "
       f"2021-2026 {c['m2']:+.2f} (t {c['t2']:+.2f}) | temoin {c['temoin'] if c['temoin'] is None else round(c['temoin'], 2)} "
       f"(Welch {c['welch']:+.2f}) | net {c['net']:+.2f} | net sans 3 meilleurs {c['sans3']:+.2f}")
    for k, v in c["tests"].items():
        pr(f"  [{'x' if v else ' '}] {k}")
    pr(f"  [{'x' if d['dsr'] >= SEUIL_DSR else ' '}] Sharpe deflate >= {SEUIL_DSR} pour {N_ESSAIS} essais : {d['dsr']:.2f}")
    pr(f"  [{'x' if d['fiable'] else ' '}] fiable au sens du tableau de bord (IC du Sharpe > 0, deux moities > 0)")
    ok = c["passe"] and d["dsr"] >= SEUIL_DSR
    pr(f"VERDICT {nom} : {'RETENUE' if ok else 'REJETEE'}{' (mais fiable au sens du tableau de bord)' if (not ok and d['fiable']) else ''}")
    return ok


# =============================================================================
#  H1 - or, momentum de session (Wei 2026)
# =============================================================================
def sessions_or(m) -> pd.DataFrame:
    j = jours_bourse(m)
    us_a = instants(j, 14, 30, UTC)                       # session americaine du jour UTC d : 14:30 -> 00:00 du lendemain
    asie_a, asie_b = instants(j, 0, 0, UTC), instants(j, 8, 0, UTC)
    eu_b = instants(j, 14, 30, UTC)
    us = pd.Series(rendement(m, us_a, us_a + (9 * 60 + 30) * 60_000_000_000), index=j)
    us_prec = pd.Series(np.nan, index=j)                  # session americaine du jour de bourse precedent -> 00:00 du jour d
    us_prec.iloc[1:] = rendement(m, us_a[:-1], asie_a[1:])
    return pd.DataFrame(dict(us=us, us_prec=us_prec, asie=rendement(m, asie_a, asie_b), europe=rendement(m, asie_b, eu_b),
                             prix_asie=prix_reel(m, asie_a), prix_eu=prix_reel(m, asie_b)), index=j)


def h1(pr) -> dict:
    pr("")
    pr("H1 - OR : MOMENTUM D UNE SESSION A L AUTRE (Wei 2026), GC, sessions Asie 00:00-08:00 et Europe 08:00-14:30 UTC")
    m = marche("GC")
    s = sessions_or(m)
    s = s[s.index >= "2016-01-05"]
    jours = s.index
    pr(f"Seances : {len(s)} ({jours[0]:%d/%m/%Y} -> {jours[-1]:%d/%m/%Y})")
    pr("ETAPE 1 - rendement moyen par session (pb par jour, t) et lien avec la session precedente")
    per = (("2016-2020", s.index < MOITIE), ("2021-2026", s.index >= MOITIE), ("periode du papier 07/2024 ->", s.index >= "2024-07-22"))
    for nom, sel in per:
        x = s[sel]
        txt = " | ".join(f"{c} {x[c].mean() * 1e4:+.2f} (t {tstat(x[c]):+.2f})" for c in ("us", "asie", "europe"))
        a = x[["us_prec", "asie"]].dropna()
        b = x[["asie", "europe"]].dropna()
        pr(f"  {nom:<28} {txt} | corr. US -> Asie {a.us_prec.corr(a.asie):+.3f} (signe identique {(np.sign(a.us_prec) == np.sign(a.asie)).mean():.0%}) "
           f"| Asie -> Europe {b.asie.corr(b.europe):+.3f}")
    pr("ETAPE 2 - strategies nettes (1 tick + 2,50 $ par cote)")
    c_asie, c_eu = cout_ar("GC", s.prix_asie), cout_ar("GC", s.prix_eu)
    sig = s.us_prec > 0
    v_brut = s.asie[sig & s.asie.notna()]
    v_net = (s.asie - c_asie)[sig & s.asie.notna()]
    tem = s.asie[(~sig) & s.us_prec.notna() & s.asie.notna()]
    st = {}
    st["V"] = resume("V   achat Asie si la session US precedente a monte", v_net, jours, pr)
    st["V2"] = resume("V   couts 2 ticks", (s.asie - cout_ar("GC", s.prix_asie, 2.0))[sig & s.asie.notna()], jours, pr)
    st["T"] = resume("temoin : achat Asie apres une session US en baisse", (s.asie - c_asie)[(~sig) & s.us_prec.notna() & s.asie.notna()], jours, pr)
    eu = (s.europe - c_eu)[(s.asie > 0) & s.europe.notna()]
    r1 = pd.concat([v_net, eu]).groupby(level=0).sum()
    st["R1"] = resume("R1  regle acheteuse du papier (Asie + Europe, sans US)", r1, jours, pr)
    st["R0"] = resume("R0  achat Asie tous les jours (derive, sans signal)", (s.asie - c_asie).dropna(), jours, pr)
    c = criteres(v_brut, v_net, tem)
    ok = verdict(pr, "H1 (V)", c, st["V"])
    return dict(code="H1", titre="Or : momentum de session vers l Asie (Wei 2026)", strategies=st, criteres=c, retenue=ok,
                instruments=["GC"], heures="00:00-08:00 UTC (19:00/20:00 -> 3:00/4:00 New York)")


# =============================================================================
#  H2 - devises, retour du saut de reouverture de 18:00 (Tolusic 2026)
# =============================================================================
ET = "America/New_York"
NS_MIN = 60_000_000_000


def cloture_a(m, t: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Cloture de la barre qui FINIT a l instant t (ns UTC) -> (prix ajuste, indice) ; NaN / -1 sinon."""
    k = np.clip(np.searchsorted(m.t, t, side="right") - 1, 0, m.n - 1)
    ok = m.t[k] == t
    return np.where(ok, m.c[k], np.nan), np.where(ok, k, -1)


def reouvertures(m, root: str) -> pd.DataFrame:
    """Une ligne par reouverture de 18:00 New York (dimanche a jeudi) : saut, rendements de sortie, temoin."""
    loc = pd.DatetimeIndex(m.t).tz_localize("UTC").tz_convert(ET).tz_localize(None)
    jours = pd.DatetimeIndex(pd.unique(loc.normalize()))
    jours = jours[(jours.dayofweek == 6) | (jours.dayofweek <= 3)]
    prec = jours - pd.to_timedelta(np.where(jours.dayofweek == 6, 2, 0), unit="D")        # dimanche -> vendredi
    suiv = jours + pd.Timedelta(days=1)
    t_cl, t_op, t_19 = instants(prec, 17, 0, ET), instants(jours, 18, 0, ET), instants(jours, 19, 0, ET)
    t_fin = instants(suiv, 17, 0, ET)
    t_20, t_21 = instants(jours, 20, 0, ET), instants(jours, 21, 0, ET)
    cl, icl = prix_a(m, t_cl)                     # cloture de la barre 16:59 (pas de barre a 17:00 : repli sur la cloture)
    op, iop = prix_a(m, t_op)
    p19, i19 = prix_a(m, t_19)
    pfin, ifin = prix_a(m, t_fin)
    c20, ic20 = cloture_a(m, t_20)
    o20, io20 = prix_a(m, t_20)
    p21, i21 = prix_a(m, t_21)
    cid = contrats(m)
    off = m.offset

    def meme(*idx):
        ok = np.all([i >= 0 for i in idx], axis=0)
        out = np.zeros(len(jours), bool)
        out[ok] = np.all([cid[i[ok]] == cid[idx[0][ok]] for i in idx], axis=0)
        return out

    reel_op = op - off[np.clip(iop, 0, None)]
    reel_cl = cl - off[np.clip(icl, 0, None)]
    reel_20 = o20 - off[np.clip(io20, 0, None)]
    ok_gap = meme(icl, iop) & np.isfinite(cl) & np.isfinite(op)
    if root == "6J":
        pips = (1 / reel_op - 1 / reel_cl) * 100.0
    else:
        pips = (reel_op - reel_cl) / 1e-4
    sens = -np.sign(op - cl)                       # contre-pied du saut des futures
    r19 = np.where(meme(iop, i19), (p19 - op) / reel_op, np.nan)
    rfin = np.where(meme(iop, ifin), (pfin - op) / reel_op, np.nan)
    sens_t = -np.sign(o20 - c20)
    r21 = np.where(meme(ic20, io20, i21), (p21 - o20) / reel_20, np.nan)
    df = pd.DataFrame(dict(pips=np.where(ok_gap, pips, np.nan), sens=np.where(ok_gap, sens, np.nan), r19=r19, rfin=rfin,
                           sens_t=sens_t, r21=r21, prix=reel_op, prix20=reel_20), index=jours)
    return df[df.index >= "2016-01-04"]


def _pool(par: dict, col: str) -> pd.Series:
    """Jambes des devises -> une serie par trade (index unique : jour + quelques ns par devise)."""
    out = []
    for k, (root, s) in enumerate(par.items()):
        s = s.dropna()
        s.index = s.index + pd.to_timedelta(k, unit="ns")
        out.append(s)
    return pd.concat(out).sort_index() if out else pd.Series(dtype=float)


def _portefeuille(par: dict, jours: pd.DatetimeIndex) -> pd.Series:
    """Parts egales : somme des jambes du jour / nombre de devises."""
    tot = sum(s.dropna().groupby(level=0).sum().reindex(jours).fillna(0.0) for s in par.values())
    return tot / len(par)


def h2(pr) -> dict:
    pr("")
    pr("H2 - DEVISES : CONTRE-PIED DU SAUT DE REOUVERTURE DE 18:00 (Tolusic 2026), 6E 6B 6A 6J, 18:00 -> 19:00 New York")
    roots = ["6E", "6B", "6A", "6J"]
    R = {r: reouvertures(marche(r), r) for r in roots}
    jours = pd.DatetimeIndex(sorted(set().union(*[set(d.index) for d in R.values()])))
    pr(f"Reouvertures : {len(jours)} ({jours[0]:%d/%m/%Y} -> {jours[-1]:%d/%m/%Y})")
    pr("ETAPE 1 - sauts et retour dans l heure (pente du rendement 18:00-19:00 sur le saut, en pb par pip ; t de Newey-West)")
    import statsmodels.api as sm
    for root, d in R.items():
        txt = []
        for nom, sel in (("2016-2020", d.index < MOITIE), ("2021-2026", d.index >= MOITIE)):
            x = d[sel].dropna(subset=["pips", "r19"])
            X = sm.add_constant(x.pips.to_numpy())
            mod = sm.OLS(x.r19.to_numpy() * 1e4, X).fit(cov_type="HAC", cov_kwds={"maxlags": 5})
            txt.append(f"{nom} : |saut| moyen {x.pips.abs().mean():.1f} pips, >= 1 pip {(x.pips.abs() >= 1).mean():.0%}, "
                       f"pente {mod.params[1]:+.3f} (t {mod.tvalues[1]:+.2f})")
        pr(f"  {root} : " + " | ".join(txt))
    pr("ETAPE 2 - strategies nettes (1 tick + 2,50 $ par cote), portefeuille a parts egales des quatre devises")
    jb, jn, jn2, j0, j0n, jf, tm, tmn = {}, {}, {}, {}, {}, {}, {}, {}
    for root, d in R.items():
        sel = (d.pips.abs() >= 1) & d.r19.notna()
        c1, c2 = cout_ar(root, d.prix), cout_ar(root, d.prix, 2.0)
        jb[root] = (d.sens * d.r19)[sel]
        jn[root] = (d.sens * d.r19 - c1)[sel]
        jn2[root] = (d.sens * d.r19 - c2)[sel]
        s0 = d.pips.notna() & (d.pips != 0) & d.r19.notna()
        j0n[root] = (d.sens * d.r19 - c1)[s0]
        sf = (d.pips.abs() >= 1) & d.rfin.notna()
        jf[root] = (d.sens * d.rfin - c1)[sf]
        st_ = d.sens_t.notna() & (d.sens_t != 0) & d.r21.notna()
        tm[root] = (d.sens_t * d.r21)[st_]
        tmn[root] = (d.sens_t * d.r21 - cout_ar(root, d.prix20))[st_]
    st = {}
    st["V"] = resume("V   contre-pied saut >= 1 pip, 18:00 -> 19:00", _pool(jn, "n"), jours, pr, _portefeuille(jn, jours))
    st["V2"] = resume("V   couts 2 ticks", _pool(jn2, "n"), jours, pr, _portefeuille(jn2, jours))
    st["T"] = resume("temoin : micro-saut de 20:00, 20:00 -> 21:00", _pool(tmn, "n"), jours, pr, _portefeuille(tmn, jours))
    st["R1"] = resume("R1  meme entree tenue jusqu a 16:59", _pool(jf, "n"), jours, pr, _portefeuille(jf, jours))
    st["R0"] = resume("R0  contre-pied de tous les sauts, 18:00 -> 19:00", _pool(j0n, "n"), jours, pr, _portefeuille(j0n, jours))
    for root in roots:
        x = jn[root].dropna()
        pr(f"    replique {root} : {len(x)} trades, net {x.mean() * 1e4:+.2f} pb (t {tstat(x):+.2f}), brut {jb[root].mean() * 1e4:+.2f} pb, "
           f"moities t {tstat(x[x.index < MOITIE]):+.2f} / {tstat(x[x.index >= MOITIE]):+.2f}")
    c = criteres(_pool(jb, "b"), _pool(jn, "n"), _pool(tm, "t"))
    ok = verdict(pr, "H2 (V)", c, st["V"])
    return dict(code="H2", titre="Devises : contre-pied du saut de reouverture de 18:00 (Tolusic 2026)", strategies=st, criteres=c,
                retenue=ok, instruments=roots, heures="18:00-19:00 New York")


# =============================================================================
#  H3 - DAX, cassure du range d ouverture de Xetra (Zarattini & Aziz 2023)
# =============================================================================
TICK_FDAX, PV_FDAX = 0.5, 25.0 * 1.10


def minutes_dax() -> tuple[pd.DataFrame, pd.DatetimeIndex]:
    """Barres du CFD DAX (HistData) de la seance de Xetra, heure de Berlin du DEBUT de barre (colonnes jour, mn)."""
    from .dax_cloture import cfd, jours_xetra
    df = cfd("GRXEUR", "histdata")
    debut = pd.DatetimeIndex(df.index - pd.Timedelta(minutes=1)).tz_localize("UTC").tz_convert("Europe/Berlin").tz_localize(None)
    jours = jours_xetra("2014-01-02", "2026-08-28")
    d = df[["open", "high", "low", "close"]].copy()
    d["jour"] = debut.normalize()
    d["mn"] = debut.hour * 60 + debut.minute
    d = d[d.jour.isin(jours) & (d.mn >= 9 * 60) & (d.mn <= 17 * 60 + 35)]
    return d, jours


def cout_fdax(prix, ticks: float = 1.0):
    return 2 * (ticks * TICK_FDAX + COMMISSION / PV_FDAX) / prix


def _sortie_stop(apres: pd.DataFrame, sens: int, stop: float, depuis: int = 0):
    """Premier franchissement du stop a partir de la barre `depuis` -> (prix de sortie, True) ou (None, False)."""
    a = apres.iloc[depuis:]
    touche = (a.low.to_numpy() <= stop) if sens > 0 else (a.high.to_numpy() >= stop)
    if not touche.any():
        return None, False
    k = int(np.argmax(touche))
    o = a.open.to_numpy()[k]
    return (min(o, stop) if sens > 0 else max(o, stop)), True


def orb_dax(d: pd.DataFrame, jours: pd.DatetimeIndex, t0: int = 9 * 60, regle: str = "za23") -> pd.DataFrame:
    """Un trade par jour au plus. -> DataFrame (jour : sens, entree, sortie, f, brut, prix, stop_touche)."""
    fin = 17 * 60 + 30
    atr = None
    if regle == "zba24":
        g = d[d.mn < fin].groupby("jour")
        H, L, C = g.high.max(), g.low.min(), g.close.last()
        tr = pd.concat([H - L, (H - C.shift(1)).abs(), (L - C.shift(1)).abs()], axis=1).max(axis=1)
        atr = tr.rolling(14).mean().shift(1)
    out = {}
    for jour, g in d.groupby("jour", sort=True):
        b = g[(g.mn >= t0) & (g.mn < t0 + 5)]
        apres = g[(g.mn >= t0 + 5) & (g.mn < fin)]
        cl = g[g.mn >= fin]
        if len(b) < 3 or len(apres) < 30:
            continue
        o, c, h, l = b.open.iloc[0], b.close.iloc[-1], b.high.max(), b.low.min()
        sens = int(np.sign(c - o))
        if sens == 0:
            continue
        p_fin = cl.open.iloc[0] if len(cl) and cl.mn.iloc[0] <= fin + 5 else apres.close.iloc[-1]
        if regle == "za23":
            if apres.mn.iloc[0] > t0 + 10:
                continue
            entree = apres.open.iloc[0]
            stop = l if sens > 0 else h
            if (entree - stop) * sens <= 0:
                continue
            px, touche = _sortie_stop(apres, sens, stop)
        elif regle == "zba24":
            a_ = atr.get(jour, np.nan)
            if not np.isfinite(a_):
                continue
            niveau = h if sens > 0 else l
            franchi = (apres.high.to_numpy() >= niveau) if sens > 0 else (apres.low.to_numpy() <= niveau)
            if not franchi.any():
                continue
            k = int(np.argmax(franchi))
            ok_ = apres.open.to_numpy()[k]
            entree = max(ok_, niveau) if sens > 0 else min(ok_, niveau)
            stop = entree - sens * 0.10 * a_
            px, touche = _sortie_stop(apres, sens, stop, depuis=k + 1)
        else:                                                      # anomalie brute : sans stop
            entree = apres.open.iloc[0]
            stop, px, touche = np.nan, None, False
        sortie = px if touche else p_fin
        dist = abs(entree - stop) / entree if np.isfinite(stop) else np.nan
        f = min(0.01 / dist, 4.0) if np.isfinite(dist) and dist > 0 else 1.0
        out[jour] = dict(sens=sens, entree=entree, sortie=sortie, f=f, brut=sens * (sortie - entree) / entree, prix=entree,
                         stop_touche=touche)
    return pd.DataFrame.from_dict(out, orient="index").reindex(columns=["sens", "entree", "sortie", "f", "brut", "prix", "stop_touche"])


def h3(pr) -> dict:
    pr("")
    pr("H3 - DAX : CASSURE DU RANGE D OUVERTURE DE XETRA (Zarattini & Aziz 2023), bougie 9:00-9:05 Berlin, sortie 17:30")
    d, jours = minutes_dax()
    pr(f"Jours de Xetra avec barres : {d.jour.nunique()} ({jours[0]:%d/%m/%Y} -> {jours[-1]:%d/%m/%Y})")
    v = orb_dax(d, jours, 9 * 60, "za23")
    r1 = orb_dax(d, jours, 9 * 60, "zba24")
    r0 = orb_dax(d, jours, 9 * 60, "brut")
    tm = orb_dax(d, jours, 12 * 60, "za23")
    t0b = orb_dax(d, jours, 12 * 60, "brut")
    pr("ETAPE 1 - rendement 9:05 -> 17:30 dans le sens de la bougie d ouverture (pb, 1 contrat, sans stop ni couts)")
    for nom, x in (("bougie 9:00", r0.brut), ("bougie 12:00 (temoin)", t0b.brut)):
        pr(f"  {nom:<22} {len(x)} jours | moyenne {x.mean() * 1e4:+.2f} pb (t {tstat(x):+.2f}) | 2014-2020 {x[x.index < MOITIE].mean() * 1e4:+.2f} "
           f"(t {tstat(x[x.index < MOITIE]):+.2f}) | 2021-2026 {x[x.index >= MOITIE].mean() * 1e4:+.2f} (t {tstat(x[x.index >= MOITIE]):+.2f})")
    pr("ETAPE 2 - strategies nettes (1 tick + 2,50 $ par cote ; taille = 1 % de risque, levier 4 au plus)")
    net = lambda t, ticks=1.0: t.f * (t.brut - cout_fdax(t.prix, ticks))
    st = {}
    st["V"] = resume("V   ORB 2023 (bougie 9:00, stop au range)", net(v), jours, pr)
    pr(f"      stop touche {v.stop_touche.mean():.0%} des jours, levier moyen {v.f.mean():.2f}")
    st["V2"] = resume("V   couts 2 ticks", net(v, 2.0), jours, pr)
    st["T"] = resume("temoin : meme regle, bougie 12:00", net(tm), jours, pr)
    st["R1"] = resume("R1  ORB 2024 sans filtre de volume (stop 10 % ATR)", net(r1), jours, pr)
    st["R0"] = resume("R0  anomalie brute, 1 contrat, sans stop", r0.brut - cout_fdax(r0.prix), jours, pr)
    c = criteres(v.f * v.brut, net(v), tm.f * tm.brut)
    ok = verdict(pr, "H3 (V)", c, st["V"])
    return dict(code="H3", titre="DAX : cassure du range d ouverture de Xetra (Zarattini & Aziz 2023)", strategies=st, criteres=c,
                retenue=ok, instruments=["FDAX (CFD DAX)"], heures="9:00-17:30 Berlin (3:00-11:30 New York)")


# =============================================================================
#  H4 - DAX, zone de bruit (regle de S1) sur la seance de Xetra
# =============================================================================
NB_MIN = 511                               # barres qui commencent de 9:00 (0) a 17:30 (510), heure de Berlin


def grille_dax(d: pd.DataFrame, part_min: float = 0.9):
    """Barres de Xetra -> tableaux jour x minute (O, H, L, C), trous combles par la derniere cloture."""
    d = d[(d.mn >= 540) & (d.mn < 540 + NB_MIN)]
    jours = pd.DatetimeIndex(sorted(d.jour.unique()))
    pos_j = pd.Series(np.arange(len(jours)), index=jours)
    i, j = pos_j[d.jour].to_numpy(), (d.mn - 540).to_numpy()
    tab = {}
    for k in ("open", "high", "low", "close"):
        a = np.full((len(jours), NB_MIN), np.nan)
        a[i, j] = d[k].to_numpy()
        tab[k] = a
    present = np.isfinite(tab["close"]).mean(axis=1)
    C = pd.DataFrame(tab["close"]).ffill(axis=1).to_numpy()
    O = np.where(np.isfinite(tab["open"]), tab["open"], np.r_[np.nan] if False else np.roll(C, 1, axis=1))
    O[:, 0] = np.where(np.isfinite(tab["open"][:, 0]), tab["open"][:, 0], C[:, 0])
    H = np.where(np.isfinite(tab["high"]), tab["high"], C)
    L = np.where(np.isfinite(tab["low"]), tab["low"], C)
    ok = (present >= part_min) & np.isfinite(O).all(axis=1) & np.isfinite(C[:, :510]).all(axis=1)
    return O[ok], H[ok], L[ok], C[ok], jours[ok]


def zone_bruit(O, H, L, C, jours, lookback=30, bande=1.2, twap=True, cible=0.02, lev_max=4.0, lev_fixe=None, ticks=1.0,
               temoin=False):
    """-> (rendement net du jour, rendement brut du jour, jours avec position, rendement de chaque controle dans le
    sens de la cassure) ; DataFrames indexes par jour."""
    n = len(jours)
    o0 = O[:, 0]
    fin = O[:, 510]                                            # prix de 17:30
    prev = np.r_[np.nan, fin[:-1]]
    consec = np.r_[False, (jours[1:] - jours[:-1]).days <= 4]  # seance precedente proche (pas de trou de donnees)
    prev = np.where(consec, prev, np.nan)
    move = pd.DataFrame(np.abs(C[:, :510] / o0[:, None] - 1))
    sigma = move.rolling(lookback, min_periods=lookback).mean().shift(1).to_numpy()
    r_cc = pd.Series(fin / prev - 1)
    sd = r_cc.rolling(14, min_periods=14).std().shift(1).to_numpy()
    lev = np.full(n, float(lev_fixe)) if lev_fixe else np.minimum(lev_max, cible / sd)
    typ = (H + L + C) / 3.0
    tw = np.cumsum(typ, axis=1) / np.arange(1, NB_MIN + 1)
    checks = list(range(29, 480, 30))                          # clotures de 9:30 ... 17:00
    haut = np.maximum(o0, prev)[:, None] * (1 + bande * sigma[:, checks])
    bas = np.minimum(o0, prev)[:, None] * (1 - bande * sigma[:, checks])
    px = C[:, checks]
    if temoin:
        pos = np.ones((n, len(checks)))
        pos[:, 1:] = 1.0
    else:
        up = (px > haut) & ((px > tw[:, checks]) if twap else True)
        dn = (px < bas) & ((px < tw[:, checks]) if twap else True)
        pos = np.where(up, 1.0, np.where(dn, -1.0, 0.0))
    ex = [k + 1 for k in checks] + [510]
    po = O[:, ex]
    r_int = (po[:, 1:] - po[:, :-1]) / o0[:, None]             # nombre de contrats fixe sur la journee (taille a l ouverture)
    brut = np.nansum(pos * r_int, axis=1)
    chg = np.abs(np.diff(np.c_[np.zeros(n), pos, np.zeros(n)], axis=1)).sum(axis=1)
    cote = (ticks * TICK_FDAX + COMMISSION / PV_FDAX) / o0
    valide = np.isfinite(lev) & np.isfinite(sigma[:, checks]).all(axis=1) & np.isfinite(prev)
    net = pd.Series(np.where(valide, lev * (brut - chg * cote), np.nan), index=jours)
    br = pd.Series(np.where(valide, lev * brut, np.nan), index=jours)
    actif = pd.Series(valide & (np.abs(pos).sum(axis=1) > 0), index=jours)
    sens_r = pd.Series((pos * r_int)[valide][pos[valide] != 0])
    return net, br, actif, sens_r, (pos[valide] != 0).mean()


def h4(pr) -> dict:
    pr("")
    pr("H4 - DAX : ZONE DE BRUIT (REGLE DE S1) SUR LA SEANCE DE XETRA, controles 9:30 ... 17:00, sortie 17:30 Berlin")
    d, _ = minutes_dax()
    O, H, L, C, jours = grille_dax(d)
    pr(f"Seances completes : {len(jours)} ({jours[0]:%d/%m/%Y} -> {jours[-1]:%d/%m/%Y})")
    net, br, actif, sr, part = zone_bruit(O, H, L, C, jours, 30, 1.2)
    pr(f"ETAPE 1 - controles hors de la zone (avec le filtre de TWAP) : {part:.1%} ; rendement de l intervalle suivant dans le "
       f"sens de la cassure : {sr.mean() * 1e4:+.2f} pb (t {tstat(sr):+.2f}, {len(sr)} intervalles)")
    st = {}
    v_net, v_br = net[actif], br[actif]
    st["V"] = resume("V   reglage S1 (sigma 30 seances, bande x1,2, TWAP)", v_net, jours, pr)
    n2, _, a2, _, _ = zone_bruit(O, H, L, C, jours, 30, 1.2, ticks=2.0)
    st["V2"] = resume("V   couts 2 ticks", n2[a2], jours, pr)
    tn, tb, ta, _, _ = zone_bruit(O, H, L, C, jours, 30, 1.2, temoin=True)
    st["T"] = resume("temoin : achat 9:30 -> 17:30 tous les jours", tn[ta], jours, pr)
    r1n, _, r1a, _, _ = zone_bruit(O, H, L, C, jours, 14, 1.0)
    st["R1"] = resume("R1  reglage du papier (sigma 14 seances, bande x1)", r1n[r1a], jours, pr)
    r0n, _, r0a, _, _ = zone_bruit(O, H, L, C, jours, 30, 1.2, twap=False, lev_fixe=1.0)
    st["R0"] = resume("R0  cassure seule (sans TWAP), levier 1", r0n[r0a], jours, pr)
    c = criteres(v_br, v_net, tb[ta])
    ok = verdict(pr, "H4 (V)", c, st["V"])
    return dict(code="H4", titre="DAX : zone de bruit de S1 sur la seance de Xetra", strategies=st, criteres=c, retenue=ok,
                instruments=["FDAX (CFD DAX)"], heures="9:00-17:30 Berlin (3:00-11:30 New York)")


# =============================================================================
#  H5 - NQ, boombitch rendu conforme a la seance (cloture 16:59, rachat 18:00)
# =============================================================================
BOOM = {"V": "boombitch, taille inverse a la volatilite (alternative)", "R1": "boombitch (Turtle Donchian 160/60, M15)",
        "R0": "boombitch, filtre de tendance 200 j (alternative)"}
CAPITAL_RUNNER = 100_000.0
PV_MNQ, TICK_MNQ, COM_MNQ = 2.0, 0.25, 0.6


def _avant(m, t_ns: int) -> float:
    """Cloture de la derniere barre finie au plus tard a t."""
    k = np.searchsorted(m.t, t_ns, side="right") - 1
    return float(m.c[k]) if k >= 0 else np.nan


def _apres(m, t_ns: int) -> float:
    """Ouverture de la premiere barre qui commence a t ou apres."""
    j = np.searchsorted(m.t, t_ns + NS_MIN, side="left")
    return float(m.o[j]) if j < m.n else np.nan


def clotures_traversees(entree: pd.Timestamp, sortie: pd.Timestamp) -> list[tuple[pd.Timestamp, pd.Timestamp, pd.Timestamp]]:
    """Clotures de 17:00 New York strictement entre l entree et la sortie (UTC naifs) -> [(jour, 17:00 UTC, reouverture UTC)]."""
    e = pd.Timestamp(entree).tz_localize("UTC").tz_convert(ET)
    x = pd.Timestamp(sortie).tz_localize("UTC").tz_convert(ET)
    out = []
    for d in pd.date_range(e.normalize().tz_localize(None), x.normalize().tz_localize(None)):
        if d.dayofweek >= 5:
            continue
        b = pd.Timestamp(d + pd.Timedelta(hours=17)).tz_localize(ET)
        if not (e < b < x):
            continue
        r = pd.Timestamp(d + pd.Timedelta(days=2 if d.dayofweek == 4 else 0, hours=18)).tz_localize(ET)
        out.append((d, b.tz_convert("UTC").tz_localize(None), r.tz_convert("UTC").tz_localize(None)))
    return out


def conforme(t: pd.DataFrame, m) -> tuple[pd.DataFrame, pd.Series]:
    """Trades du runner -> (trades avec pnl conforme, corrections par jour de seance)."""
    corr = {}
    rows = []
    for tr in t.itertuples():
        cl = clotures_traversees(pd.Timestamp(tr.entry_time), pd.Timestamp(tr.exit_time))
        saut = 0.0
        for d, b, r in cl:
            g = _apres(m, pd.Timestamp(r).value) - _avant(m, pd.Timestamp(b).value)
            adj = -(tr.direction * tr.qty * PV_MNQ * g) - tr.qty * 2 * (COM_MNQ + TICK_MNQ * PV_MNQ)
            saut += tr.direction * tr.qty * PV_MNQ * g
            corr[d] = corr.get(d, 0.0) + adj
        cout = len(cl) * tr.qty * 2 * (COM_MNQ + TICK_MNQ * PV_MNQ)
        rows.append(dict(sortie=pd.Timestamp(tr.exit_time), pnl=tr.pnl, saut=saut, n=len(cl), pnl_c=tr.pnl - saut - cout))
    return pd.DataFrame(rows), pd.Series(corr, dtype=float)


def h5(pr) -> dict:
    from .portefeuille import _latest
    pr("")
    pr("H5 - NQ : BOOMBITCH (TURTLE DONCHIAN 160/60, 15 MIN) RENDU CONFORME : VENTE A 16:59, RACHAT A 18:00")
    m = marche("NQ")
    st, res = {}, {}
    jours = None
    for code, nom in BOOM.items():
        t = pd.read_csv(_latest("trades", nom), parse_dates=["entry_time", "exit_time"])
        eq = pd.read_csv(_latest("equity", nom), parse_dates=["date"], index_col="date")["equity"]
        tc, corr = conforme(t, m)
        pnl_j = eq.diff().fillna(0.0)
        pnl_c = pnl_j.add(corr.reindex(pnl_j.index).fillna(0.0), fill_value=0.0)
        jours = pnl_j.index if jours is None else jours
        part = (tc.n > 0).mean()
        pr(f"  {code} {nom} : {len(tc)} trades, {part:.0%} traversent 17:00 ({int(tc.n.sum())} clotures) ; P&L d origine "
           f"{tc.pnl.sum():+,.0f} $, dont sauts de reouverture {tc.saut.sum():+,.0f} $ ; conforme {tc.pnl_c.sum():+,.0f} $".replace(",", " "))
        x = pd.Series(tc.pnl_c.to_numpy() / CAPITAL_RUNNER, index=pd.DatetimeIndex(tc.sortie).normalize())
        x.index = x.index + pd.to_timedelta(np.arange(len(x)) % 1000, unit="ns")
        lib = {"V": "V   taille inverse a la vol. (300 $), conforme", "R1": "R1  boombitch d origine (1 MNQ), conforme",
               "R0": "R0  filtre de tendance 200 j, conforme"}[code]
        st[code] = resume(lib, x, pnl_c.index, pr, pnl_c / CAPITAL_RUNNER)
        res[code] = (x, pnl_c)
        if code == "V":
            st["V0"] = resume("    meme strategie NON conforme (reference)", x, pnl_j.index, pr, pnl_j / CAPITAL_RUNNER)
    # temoin : 1 MNQ achete a 18:00 et vendu a 16:59, chaque seance
    tem = {}
    for d in jours:
        if d.dayofweek >= 5:
            continue
        b = pd.Timestamp(d + pd.Timedelta(hours=17)).tz_localize(ET).tz_convert("UTC").tz_localize(None)
        prec = d - pd.Timedelta(days=3 if d.dayofweek == 0 else 1)
        r = pd.Timestamp(prec + pd.Timedelta(hours=18)).tz_localize(ET).tz_convert("UTC").tz_localize(None)
        g = _avant(m, b.value) - _apres(m, r.value)
        if np.isfinite(g):
            tem[d] = (PV_MNQ * g - 2 * (COM_MNQ + TICK_MNQ * PV_MNQ)) / CAPITAL_RUNNER
    tem = pd.Series(tem)
    st["T"] = resume("temoin : 1 MNQ de 18:00 a 16:59 chaque seance", tem, jours, pr, tem.reindex(jours).fillna(0.0))
    x, _ = res["V"]
    c = criteres(x, x, tem)
    ok = verdict(pr, "H5 (V)", c, st["V"])
    return dict(code="H5", titre="NQ : boombitch (Turtle Donchian) rendu conforme a la seance", strategies=st, criteres=c, retenue=ok,
                instruments=["NQ (MNQ)"], heures="toute la seance CME 18:00-17:00 New York, cassures a toute heure")


# =============================================================================
#  H6 - replique de H5 sur les huit autres contrats
# =============================================================================
MICROS = {"ES": "MES", "YM": "MYM", "GC": "MGC", "CL": "MCL", "6E": "M6E", "6B": "M6B", "6J": "MJY", "6A": "M6A"}


def _donchian_conforme(args):
    root, micro = args
    import warnings as _w
    from .qf import INSTRUMENTS, Engine, futures_minutes, resample
    from .user import DonchianAlt
    with _w.catch_warnings():
        _w.simplefilter("ignore")
        df = resample(futures_minutes(root), 15)
        e = Engine(df, INSTRUMENTS[micro])
        e.run(DonchianAlt(e, fixed_risk=300.0, fin_de_seance=True))
        t = pd.DataFrame([x.__dict__ for x in e.trades])
        return root, t, e.equity()


def _temoin_seances(m, jours, pv: float, com: float, tick: float) -> pd.Series:
    out = {}
    for d in jours:
        if d.dayofweek >= 5:
            continue
        b = pd.Timestamp(d + pd.Timedelta(hours=17)).tz_localize(ET).tz_convert("UTC").tz_localize(None)
        prec = d - pd.Timedelta(days=3 if d.dayofweek == 0 else 1)
        r = pd.Timestamp(prec + pd.Timedelta(hours=18)).tz_localize(ET).tz_convert("UTC").tz_localize(None)
        g = _avant(m, b.value) - _apres(m, r.value)
        if np.isfinite(g):
            out[d] = (pv * g - 2 * (com + tick * pv)) / CAPITAL_RUNNER
    return pd.Series(out)


def h6(pr) -> dict:
    from concurrent.futures import ProcessPoolExecutor
    from .qf import INSTRUMENTS
    pr("")
    pr("H6 - REPLIQUE DE H5 (DONCHIAN 160/60, 15 MIN, RISQUE 300 $, CONFORME A LA SEANCE) SUR LES HUIT AUTRES CONTRATS")
    with ProcessPoolExecutor(max_workers=4) as ex:
        res = list(ex.map(_donchian_conforme, list(MICROS.items())))
    st, crit, ok_all = {}, {}, {}
    for root, t, eq in res:
        inst = INSTRUMENTS[MICROS[root]]
        jours = pd.DatetimeIndex(eq.index)
        pnl_j = eq.diff().fillna(0.0)
        x = pd.Series(t.pnl.to_numpy() / CAPITAL_RUNNER, index=pd.DatetimeIndex(pd.to_datetime(t.exit_time)).normalize())
        x.index = x.index + pd.to_timedelta(np.arange(len(x)) % 1000, unit="ns")
        st[root] = resume(f"{root} ({MICROS[root]}), {len(t)} trades, P&L {t.pnl.sum():+,.0f} $".replace(",", " "), x, jours, pr,
                          pnl_j / CAPITAL_RUNNER)
        tem = _temoin_seances(marche(root), jours, inst.point_value, inst.commission, inst.tick)
        c = criteres(x, x, tem)
        ok = c["passe"] and st[root]["dsr"] >= SEUIL_DSR
        crit[root], ok_all[root] = c, ok
        rate = [k for k, v in c["tests"].items() if not v] + ([] if st[root]["dsr"] >= SEUIL_DSR else ["Sharpe deflate"])
        pr(f"      temoin {tem.mean() * 1e4:+.2f} pb (Welch {c['welch']:+.2f}) | {'RETENUE' if ok else 'rejetee : ' + ' ; '.join(rate)}"
           f"{' | FIABLE (tableau de bord)' if st[root]['fiable'] else ''}")
    retenues = [r for r, v in ok_all.items() if v]
    pr(f"VERDICT H6 : {len(retenues)} contrat(s) retenu(s) sur 8 : {', '.join(retenues) or 'aucun'} ; fiables au sens du tableau de bord : "
       f"{', '.join(r for r in st if st[r]['fiable']) or 'aucun'}")
    meilleur = max(st, key=lambda r: st[r]["sharpe"] if np.isfinite(st[r]["sharpe"]) else -9)
    stv = dict(st)
    stv["V"] = st[meilleur]
    return dict(code="H6", titre="Replique de H5 (Donchian conforme) sur ES, YM, GC, CL, 6E, 6B, 6J, 6A", strategies=stv,
                criteres=crit[meilleur], retenue=bool(retenues), instruments=list(MICROS.values()),
                heures="toute la seance CME 18:00-17:00 New York", retenues=retenues)


# =============================================================================
#  H7 - DAX, regle de H5 sur le micro-DAX (heures de l Eurex)
# =============================================================================
def minutes_dax_eurex() -> pd.DataFrame:
    """Minutes du CFD DAX limitees aux heures de l Eurex (01:15-22:00 Berlin) et aux jours de Xetra."""
    from .dax_cloture import cfd, jours_xetra
    df = cfd("GRXEUR", "histdata")
    loc = pd.DatetimeIndex(df.index - pd.Timedelta(minutes=1)).tz_localize("UTC").tz_convert("Europe/Berlin").tz_localize(None)
    mn = loc.hour * 60 + loc.minute
    jours = jours_xetra("2014-01-02", "2026-08-28")
    garde = (mn >= 75) & (mn < 22 * 60) & loc.normalize().isin(jours)
    out = df.loc[garde, ["open", "high", "low", "close"]].astype(float).copy()
    out["volume"] = 1.0
    return out


def h7(pr) -> dict:
    import warnings as _w
    from .qf import INSTRUMENTS, Engine, resample
    from .user import DonchianAlt
    pr("")
    pr("H7 - DAX : REGLE DE H5 (DONCHIAN CONFORME) SUR LE MICRO-DAX FDXS, HEURES DE L EUREX 01:15-22:00 BERLIN")
    df = resample(minutes_dax_eurex(), 15)
    inst = INSTRUMENTS["FDXS"]
    with _w.catch_warnings():
        _w.simplefilter("ignore")
        e = Engine(df, inst)
        e.run(DonchianAlt(e, fixed_risk=300.0, fin_de_seance=True))
    t = pd.DataFrame([x.__dict__ for x in e.trades])
    eq = e.equity()
    jours = pd.DatetimeIndex(eq.index)
    pnl_j = eq.diff().fillna(0.0)
    x = pd.Series(t.pnl.to_numpy() / CAPITAL_RUNNER, index=pd.DatetimeIndex(pd.to_datetime(t.exit_time)).normalize())
    x.index = x.index + pd.to_timedelta(np.arange(len(x)) % 1000, unit="ns")
    st = {"V": resume(f"V   FDXS, {len(t)} trades, P&L {t.pnl.sum():+,.0f} $".replace(",", " "), x, jours, pr, pnl_j / CAPITAL_RUNNER)}
    g = df.groupby(pd.DatetimeIndex(df.index - pd.Timedelta(minutes=15)).tz_localize("UTC").tz_convert("Europe/Berlin").normalize().tz_localize(None))
    tem = (inst.point_value * (g["close"].last() - g["open"].first()) - 2 * (inst.commission + inst.tick * inst.point_value)) / CAPITAL_RUNNER
    st["T"] = resume("temoin : 1 FDXS de l ouverture a la cloture de chaque seance", tem, jours, pr, tem.reindex(jours).fillna(0.0))
    sortie_ok = (pd.DatetimeIndex(pd.to_datetime(t.exit_time)).tz_localize("UTC").tz_convert("America/New_York").hour < 17).mean()
    pr(f"      sorties avant 17:00 New York : {sortie_ok:.1%}")
    c = criteres(x, x, tem)
    ok = verdict(pr, "H7 (V)", c, st["V"])
    return dict(code="H7", titre="DAX : Donchian conforme (regle de H5) sur le micro-DAX", strategies=st, criteres=c, retenue=ok,
                instruments=["FDXS (CFD DAX)"], heures="01:15-22:00 Berlin (19:15-16:00 New York)")


# =============================================================================
#  H8 - ES, retour apres la sortie de la bande de volatilite implicite (Seeck 2026)
# =============================================================================
def indice_vol(nom: str) -> pd.Series:
    """Cloture officielle CBOE (VIX_History.csv, VXN_History.csv), indexee par date."""
    c = pd.read_csv(os.path.join(PY_DIR, ".cache", "fred", f"{nom}_History.csv"))
    c.columns = [x.upper() for x in c.columns]
    return pd.Series(c["CLOSE"].astype(float).to_numpy(), index=pd.to_datetime(c["DATE"], format="%m/%d/%Y")).sort_index()


def bande_vol(m, vol: pd.Series, diviseur: float = 16.0) -> pd.DataFrame:
    """Une ligne par seance : sens du retour (+1 achat sous la borne basse, -1 vente au-dessus de la borne haute, 0 sans
    sortie), rendement de l entree a la cloture, niveau de l indice de la veille."""
    loc = pd.DatetimeIndex(m.t - NS_MIN).tz_localize("UTC").tz_convert(ET).tz_localize(None)     # debut de barre, New York
    mn = (loc.hour * 60 + loc.minute).to_numpy()
    jour = loc.normalize()
    rth = (mn >= 570) & (mn < 960) & (jour.dayofweek < 5)
    pos = np.flatnonzero(rth)
    groupes = pd.Series(pos).groupby(jour[pos].to_numpy())
    cid = contrats(m)
    off = m.offset
    prev_close, prev_cid = np.nan, -1
    res = {}
    for d, g in groupes:
        ii = g.to_numpy()
        if len(ii) < 300:
            prev_close, prev_cid = np.nan, -1
            continue
        d = pd.Timestamp(d)
        v = vol[vol.index < d]
        vix = float(v.iloc[-1]) if len(v) and (d - v.index[-1]).days <= 5 else np.nan
        close_j, cid_j = m.c[ii[-1]], cid[ii[-1]]
        if np.isfinite(prev_close) and np.isfinite(vix) and prev_cid == cid[ii[0]] == cid_j:
            larg = vix / 100.0 / diviseur
            haut, bas = prev_close * (1 + larg), prev_close * (1 - larg)
            fen = ii[(mn[ii] >= 571) & (mn[ii] <= 930)]
            c_ = m.c[fen]
            k = np.flatnonzero((c_ > haut) | (c_ < bas))
            if len(k) and fen[k[0]] + 1 <= ii[-1]:
                j = fen[k[0]]
                sens = -1.0 if c_[k[0]] > haut else 1.0
                entree = m.o[j + 1]
                reel = entree - off[j + 1]
                res[d] = dict(sens=sens, r=sens * (close_j - entree) / reel, prix=reel, vix=vix)
            else:
                res[d] = dict(sens=0.0, r=np.nan, prix=np.nan, vix=vix)
        prev_close, prev_cid = close_j, cid_j
    return pd.DataFrame.from_dict(res, orient="index")


def h8(pr) -> dict:
    pr("")
    pr("H8 - ES : RETOUR APRES LA SORTIE DE LA BANDE DE VOLATILITE IMPLICITE (Seeck 2026), seance 9:30-16:00 New York")
    vix, vxn = indice_vol("VIX"), indice_vol("VXN")
    es, nq = marche("ES"), marche("NQ")
    b = bande_vol(es, vix)
    t = bande_vol(es, vix, 32.0)
    bn = bande_vol(nq, vxn)
    jours = pd.DatetimeIndex(b.index)
    ev = b[b.sens != 0]
    pr(f"ETAPE 1 - seances : {len(b)} ; sorties de bande (VIX / 16) : {len(ev)} ({len(ev) / len(b):.0%})")
    for nom, sel in (("2016-2020", ev.index < MOITIE), ("2021-2026", ev.index >= MOITIE), ("VIX < 20", ev.vix < 20),
                     ("VIX 20-30", (ev.vix >= 20) & (ev.vix < 30)), ("VIX >= 30", ev.vix >= 30)):
        x = ev.r[sel]
        pr(f"  {nom:<10} {len(x):4d} sorties | retour moyen jusqu a la cloture {x.mean() * 1e4:+.2f} pb (t {tstat(x):+.2f}) | "
           f"part positive {(x > 0).mean():.0%}")
    pr("ETAPE 2 - strategies nettes (1 tick + 2,50 $ par cote)")
    net = lambda d, ticks=1.0, root="ES": (d.r - cout_ar(root, d.prix, ticks))[d.sens != 0].dropna()
    st = {}
    st["V"] = resume("V   ES, bande VIX / 16, retour jusqu a la cloture", net(b), jours, pr)
    st["V2"] = resume("V   couts 2 ticks", net(b, 2.0), jours, pr)
    st["T"] = resume("temoin : bande deux fois plus etroite (VIX / 32)", net(t), jours, pr)
    st["R1"] = resume("R1  regle du papier : NQ, bande VXN / 16", net(bn, root="NQ"), pd.DatetimeIndex(bn.index), pr)
    st["R0"] = resume("R0  V seulement si VIX >= 30", net(b[b.vix >= 30]), jours, pr)
    c = criteres(b.r[b.sens != 0].dropna(), net(b), t.r[t.sens != 0].dropna())
    ok = verdict(pr, "H8 (V)", c, st["V"])
    return dict(code="H8", titre="ES : retour apres la sortie de la bande de volatilite implicite (Seeck 2026)", strategies=st,
                criteres=c, retenue=ok, instruments=["ES"], heures="9:30-16:00 New York")


# =============================================================================
#  H9 - le flux gotobi sur les autres devises
# =============================================================================
TOKYO = "Asia/Tokyo"


def jambes_tokyo(m, jours: pd.DatetimeIndex) -> pd.DataFrame:
    """Rendements du future 08:00 -> 09:55 et 09:55 -> 11:00 (heure de Tokyo), prix reel a 08:00 et 09:55."""
    t8, t955, t11 = instants(jours, 8, 0, TOKYO), instants(jours, 9, 55, TOKYO), instants(jours, 11, 0, TOKYO)
    return pd.DataFrame(dict(avant=rendement(m, t8, t955), apres=rendement(m, t955, t11), p8=prix_reel(m, t8),
                             p955=prix_reel(m, t955)), index=jours)


def h9(pr) -> dict:
    from ..gotobi import jours_gotobi, jours_ouvres_japon
    pr("")
    pr("H9 - LE FLUX GOTOBI (Ito & Yamada 2017 ; Krohn, Mueller & Whelan 2023) SUR 6E, 6B, 6A : vente 08:00 -> 09:55, achat -> 11:00 Tokyo")
    goto = jours_gotobi("2016-01-04", "2026-08-28")
    ouvres = jours_ouvres_japon("2016-01-04", "2026-08-28")
    autres = ouvres.difference(goto)
    jours = ouvres
    v_b, v_n, r1_n, t_b, t_n = {}, {}, {}, {}, {}
    for root in ("6E", "6B", "6A", "6J"):
        m = marche(root)
        g, a = jambes_tokyo(m, goto), jambes_tokyo(m, autres)
        c8, c955 = cout_ar(root, g.p8), cout_ar(root, g.p955)
        brut = (-g.avant).add(g.apres, fill_value=0.0)
        net = (-g.avant - c8).add(g.apres - c955, fill_value=0.0)
        tb = (-a.avant).add(a.apres, fill_value=0.0)
        tn = (-a.avant - cout_ar(root, a.p8)).add(a.apres - cout_ar(root, a.p955), fill_value=0.0)
        pr(f"  {root} : jours gotobi {len(brut.dropna())} | avant le fixing {(-g.avant).mean() * 1e4:+.2f} pb (t {tstat(-g.avant):+.2f}), "
           f"apres {g.apres.mean() * 1e4:+.2f} pb (t {tstat(g.apres):+.2f}) | net des deux jambes {net.mean() * 1e4:+.2f} pb (t {tstat(net):+.2f}) "
           f"| autres jours, brut {tb.mean() * 1e4:+.2f} pb (t {tstat(tb):+.2f})")
        if root == "6J":
            continue
        v_b[root], v_n[root], r1_n[root] = brut.dropna(), net.dropna(), (-g.avant - c8).dropna()
        t_b[root], t_n[root] = tb.dropna(), tn.dropna()
    st = {}
    st["V"] = resume("V   6E 6B 6A, les deux jambes, jours gotobi", _pool(v_n, "n"), jours, pr, _portefeuille(v_n, jours))
    st["R1"] = resume("R1  jambe d avant le fixing seulement", _pool(r1_n, "n"), jours, pr, _portefeuille(r1_n, jours))
    st["T"] = resume("temoin : meme regle les autres jours ouvres", _pool(t_n, "n"), jours, pr, _portefeuille(t_n, jours))
    c = criteres(_pool(v_b, "b"), _pool(v_n, "n"), _pool(t_b, "t"))
    ok = verdict(pr, "H9 (V)", c, st["V"])
    return dict(code="H9", titre="Le flux gotobi sur 6E, 6B, 6A (Ito & Yamada 2017 ; Krohn et al. 2023)", strategies=st, criteres=c,
                retenue=ok, instruments=["6E", "6B", "6A"], heures="08:00-11:00 Tokyo (18:00/19:00-21:00/22:00 New York)")


# =============================================================================
#  H10 - or la nuit rendu conforme a la seance
# =============================================================================
def trades_or(pf) -> tuple[pd.Series, pd.Series]:
    """Rendement net et brut (avant commissions) de chaque trade vectorbt, date du jour de sortie a New York."""
    tr = pf.trades.records_readable
    sortie = pd.DatetimeIndex(tr["Exit Timestamp"]).tz_localize("UTC").tz_convert(ET).tz_localize(None).normalize()
    base = (tr["Size"] * tr["Avg Entry Price"]).to_numpy(float)
    net = pd.Series(tr["PnL"].to_numpy(float) / base, index=sortie)
    brut = pd.Series((tr["PnL"] + tr["Entry Fees"] + tr["Exit Fees"]).to_numpy(float) / base, index=sortie)
    return net, brut


def h10(pr) -> dict:
    from .. import or_nuit as ON
    from ..tableau import calendrier
    pr("")
    pr("H10 - OR LA NUIT RENDU CONFORME (Blose & Gondhalekar 2014) : achat 18:00 -> 8:20 et 13:30 -> 16:59, GC")
    m, _ = ON.charger(os.path.join(PY_DIR, "..", "Cotations"))
    seance = pd.DatetimeIndex(m["seance"].to_numpy())
    cal = calendrier(seance[0], seance[-1])
    st, tr = {}, {}
    for cle, jambes, nom in (("V", "asie,soir", "V   18:00 -> 8:20 et 13:30 -> 16:59"), ("R1", "asie", "R1  jambe asie seule (18:00 -> 8:20)"),
                             ("T", "pause", "temoin : seance du COMEX (8:20 -> 13:30)"), ("REF", "tout", "reference : or garde toute la seance")):
        pf = ON.portefeuille(m, compact=True, jambes=jambes)
        q = ON.valeur_journaliere(pf, cal).pct_change().fillna(0.0)
        tr[cle] = trades_or(pf)
        st[cle] = resume(nom, tr[cle][0], cal, pr, q)
    c = criteres(tr["V"][1], tr["V"][0], tr["T"][1])
    ok = verdict(pr, "H10 (V)", c, st["V"])
    pr(f"  V contre la simple detention de l or (meme seance) : Sharpe {st['V']['sharpe']:+.2f} contre {st['REF']['sharpe']:+.2f}")
    return dict(code="H10", titre="Or la nuit rendu conforme a la seance (Blose & Gondhalekar 2014)", strategies=st, criteres=c,
                retenue=ok, instruments=["GC"], heures="18:00-8:20 et 13:30-17:00 New York")


# =============================================================================
#  H11 - crypto : micro bitcoin et micro ether du CME (MBT, MET), donnees Binance au comptant
# =============================================================================
CRYPTO_CME = {"BTC": ("BTCUSDT", "MBT", 5.0, 3e-4), "ETH": ("ETHUSDT", "MET", 0.5, 15e-4)}   # paire, micro, tick, cout/cote
ZPB_FENETRES = (5, 10, 20, 30, 60, 90, 150, 250, 360)


def seance_cme(index: pd.DatetimeIndex) -> np.ndarray:
    """Barres (fin de barre, UTC naif) de la seance CME : dimanche 18:00 -> vendredi 17:00 New York, sans 17:00-18:00."""
    et = pd.DatetimeIndex(index).tz_localize("UTC").tz_convert(ET).tz_localize(None)
    mn = (et.hour * 60 + et.minute).to_numpy()
    jour = (et + pd.Timedelta(hours=6)).dayofweek.to_numpy()          # jour de la seance (18:00 -> 17:00, date de la fin)
    return ~((mn > 17 * 60) & (mn <= 18 * 60)) & (jour < 5)


def minutes_crypto(cle: str, seance: bool = True) -> pd.DataFrame:
    from .. import binance as B
    df = B.charger(CRYPTO_CME[cle][0])
    return df[seance_cme(df.index)] if seance else df


def verif_horodatage(pr) -> None:
    """Rendements 15 min Binance contre Alpaca (2021-2026) : la correlation doit culminer au decalage 0."""
    from .weekend_crypto import crypto
    a = crypto("BTCUSD").pct_change()
    b = minutes_crypto("BTC", seance=False)["close"].resample("15min", label="right", closed="right").last().pct_change()
    x = pd.concat([a.rename("alpaca"), b.rename("binance")], axis=1).dropna()
    cor = {k: x["alpaca"].corr(x["binance"].shift(k)) for k in (-2, -1, 0, 1, 2)}
    pr(f"  horodatage : correlation des rendements 15 min Binance / Alpaca (BTC, {len(x)} barres) par decalage : "
       + " ; ".join(f"{k:+d} : {v:.2f}" for k, v in cor.items()))
    if max(cor, key=cor.get) != 0:
        raise RuntimeError("horodatage Binance decale par rapport a Alpaca : arret avant le calcul")


def _donchian_crypto(cle: str):
    import warnings as _w
    from .qf import Engine, Inst, resample
    from .user import DonchianAlt
    paire, micro, tick, _ = CRYPTO_CME[cle]
    with _w.catch_warnings():
        _w.simplefilter("ignore")
        df = resample(minutes_crypto(cle), 15)
        df = df[seance_cme(df.index)]
        e = Engine(df, Inst(micro, cle, 0.1, tick, 0.0), slippage_ticks=0)
        e.run(DonchianAlt(e, fixed_risk=300.0, fin_de_seance=True))
        return pd.DataFrame([x.__dict__ for x in e.trades]), e.equity()


def _jour_seance(t) -> pd.DatetimeIndex:
    et = pd.DatetimeIndex(pd.to_datetime(t)).tz_localize("UTC").tz_convert(ET).tz_localize(None)
    return (et + pd.Timedelta(hours=6)).normalize()


def _net_crypto(t: pd.DataFrame, eq: pd.Series, c: float):
    """Couts par cote en fraction du notionnel -> (rendement net par trade en fraction du notionnel, P&L net par jour,
    notionnel moyen par trade)."""
    q = t.qty.abs().to_numpy(float) * 0.1
    ne, nx = q * t.entry_price.to_numpy(float), q * t.exit_price.to_numpy(float)
    net = t.pnl.to_numpy(float) - c * (ne + nx)
    x = pd.Series(net / ne, index=pd.DatetimeIndex(pd.to_datetime(t.exit_time)).normalize())
    x.index = x.index + pd.to_timedelta(np.arange(len(x)) % 1000, unit="ns")
    cout_j = (pd.Series(c * ne, index=_jour_seance(t.entry_time)).groupby(level=0).sum()
              .add(pd.Series(c * nx, index=_jour_seance(t.exit_time)).groupby(level=0).sum(), fill_value=0.0))
    pnl_j = eq.diff().fillna(0.0)
    return x, pnl_j.sub(cout_j.reindex(pnl_j.index).fillna(0.0)), float(np.mean(ne))


def prix_seances(cle: str) -> pd.DataFrame:
    """Par jour civil (heure de New York) : cloture de 17:00 (derniere minute avant 17:00, le comptant cote aussi le
    week-end) et ouverture de 18:00 (premiere minute apres 18:00)."""
    df = minutes_crypto(cle, seance=False)
    et = pd.DatetimeIndex(df.index).tz_localize("UTC").tz_convert(ET).tz_localize(None)
    mn = et.hour * 60 + et.minute
    c17 = pd.Series(df["close"].to_numpy(), index=et)[(mn > 16 * 60 + 50) & (mn <= 17 * 60)]
    c17 = c17.groupby(c17.index.normalize()).last()
    o18 = pd.Series(df["open"].to_numpy(), index=et)[(mn > 18 * 60) & (mn <= 18 * 60 + 10)]
    o18 = o18.groupby(o18.index.normalize()).first()
    return pd.DataFrame(dict(c17=c17, o18=o18))


def expositions_zpb(c17: pd.Series) -> pd.Series:
    """Regle ZPB25 sur les clotures journalieres : exposition (fraction du capital) decidee a chaque cloture."""
    c = c17.to_numpy(float)
    vol = pd.Series(c).pct_change().rolling(90).std().to_numpy() * math.sqrt(365)
    n = len(c)
    expo = np.zeros(n)
    for L in ZPB_FENETRES:
        dedans, stop = False, -np.inf
        hi = pd.Series(c).rolling(L).max().shift(1).to_numpy()
        lo = pd.Series(c).rolling(L).min().shift(1).to_numpy()
        for d in range(n):
            if not np.isfinite(hi[d]) or not np.isfinite(vol[d]) or vol[d] <= 0:
                continue
            mid = (hi[d] + lo[d]) / 2
            if dedans:
                stop = max(stop, mid)
                if c[d] < stop:
                    dedans = False
            elif c[d] > hi[d]:
                dedans, stop = True, mid
            if dedans:
                expo[d] += min(0.25 / vol[d], 2.0) / len(ZPB_FENETRES)
    return pd.Series(np.minimum(expo, 2.0), index=c17.index)


def rendements_seances(ps: pd.DataFrame) -> pd.Series:
    """Rendement de chaque seance CME (lundi a vendredi, datee de sa fin) : de l ouverture de 18:00 la veille a 17:00."""
    r = ps.c17 / ps.o18.shift(1, freq="D").reindex(ps.index) - 1
    return r[ps.index.dayofweek < 5].dropna()


def h11(pr) -> dict:
    pr("")
    pr("H11 - CRYPTO : MICRO BITCOIN ET MICRO ETHER DU CME (MBT, MET), comptant Binance 08/2017-09/2026, seance CME 18:00-17:00")
    verif_horodatage(pr)
    st, crit = {}, {}
    for cle, code in (("BTC", "V"), ("ETH", "V2")):
        paire, micro, tick, c = CRYPTO_CME[cle]
        t, eq = _donchian_crypto(cle)
        jours = pd.DatetimeIndex(eq.index)
        xv = None
        for k, nom in ((1.0, ""), (2.0, " couts x 2")):
            x, pnl, notio = _net_crypto(t, eq, c * k)
            st[code if k == 1.0 else code + "s"] = resume(f"{code:<3} regle de H5 sur {micro}{nom} ({len(t)} trades, {notio:.0f} $ par trade)",
                                                          x, jours, pr, pnl / CAPITAL_RUNNER)
            xv = x if xv is None else xv
        r = rendements_seances(prix_seances(cle))
        tem = r - 2 * c
        st["T" + code] = resume(f"    temoin : {micro} de 18:00 a 17:00 chaque seance", tem, pd.DatetimeIndex(tem.index), pr, tem)
        crit[code] = criteres(xv, xv, tem)
        verdict(pr, f"H11 ({code}, {micro})", crit[code], st[code])
    # R1 : regle ZPB25 sur le bitcoin, rendue conforme
    c = CRYPTO_CME["BTC"][3]
    ps = prix_seances("BTC")
    e = expositions_zpb(ps.c17.dropna())
    r_s = rendements_seances(ps)
    sig = e.shift(1, freq="D").reindex(r_s.index)                    # decidee a 17:00 la veille (jour de l ouverture)
    q1 = tr1 = None
    for k, nom in ((1.0, ""), (2.0, " couts x 2")):
        q = (sig * r_s - 2 * c * k * sig).dropna()
        tr = q[sig.reindex(q.index) > 0]
        st["R1" if k == 1.0 else "R1s"] = resume(f"R1  regle ZPB25 conforme (MBT){nom}, exposition moyenne {sig.mean():.2f}",
                                                 tr, pd.DatetimeIndex(q.index), pr, q)
        if q1 is None:
            q1, tr1 = q, tr
    moy = float(sig.reindex(q1.index).mean())
    tem_r = (moy * r_s - 2 * c * moy).reindex(q1.index).dropna()
    st["TR1"] = resume(f"    temoin de R1 : exposition constante {moy:.2f}", tem_r, pd.DatetimeIndex(tem_r.index), pr, tem_r)
    crit["R1"] = criteres(tr1, tr1, tem_r)
    verdict(pr, "H11 (R1, ZPB25 conforme)", crit["R1"], st["R1"])
    ret = [k for k in ("V", "V2", "R1") if crit[k]["passe"] and st[k]["dsr"] >= SEUIL_DSR]
    pr(f"VERDICT H11 : retenue(s) : {', '.join(ret) or 'aucune'} ; fiables au sens du tableau de bord : "
       f"{', '.join(k for k in ('V', 'V2', 'R1') if st[k]['fiable']) or 'aucune'}")
    best = max(("V", "V2", "R1"), key=lambda k: st[k]["sharpe"] if np.isfinite(st[k]["sharpe"]) else -9)
    stv = dict(st)
    stv["V"] = st[best]
    return dict(code="H11", titre="Crypto : micro bitcoin et micro ether du CME (H5 replique ; Zarattini, Pagani & Barbon 2025)",
                strategies=stv, criteres=crit[best], retenue=bool(ret), instruments=["MBT", "MET"],
                heures="toute la seance CME 18:00-17:00 New York", retenues=ret)


# =============================================================================
#  H12 - bitcoin, fenetres courtes (MBT)
# =============================================================================
def fenetres_utc(df: pd.DataFrame, a: int, b: int, seance: bool = True) -> pd.DataFrame:
    """Par jour UTC : morceaux continus de la fenetre [a, b) (minutes UTC, debut de barre) ; avec seance=True, seulement
    les minutes de la seance CME. -> une ligne par morceau : jour, debut, fin (minutes), prix d entree (ouverture de la
    premiere barre), de sortie (cloture de la derniere), rendement."""
    debut = pd.DatetimeIndex(df.index) - pd.Timedelta(minutes=1)
    mn = (debut.hour * 60 + debut.minute).to_numpy()
    garde = (mn >= a) & (mn < b)
    if seance:
        garde &= seance_cme(df.index)
    i = np.flatnonzero(garde)
    if not len(i):
        return pd.DataFrame(columns=["jour", "debut", "fin", "entree", "sortie", "r"])
    jour = debut[i].normalize()
    t = debut[i].as_unit("ns").asi8 // 60_000_000_000
    coupe = np.r_[True, (np.diff(t) != 1) | (jour[1:] != jour[:-1])]
    grp = np.cumsum(coupe)
    o, c = df["open"].to_numpy()[i], df["close"].to_numpy()[i]
    g = pd.DataFrame(dict(grp=grp, jour=jour, mn=mn[i], o=o, c=c))
    out = g.groupby("grp").agg(jour=("jour", "first"), debut=("mn", "first"), fin=("mn", "last"), entree=("o", "first"),
                               sortie=("c", "last"), n=("mn", "size"))
    out = out[out.n >= 30]
    out["r"] = out.sortie / out.entree - 1
    return out.reset_index(drop=True)


def h12(pr) -> dict:
    pr("")
    pr("H12 - BITCOIN : FENETRES COURTES (MBT) : momentum de la derniere demi-heure (Wen et al. 2022) ; deux heures apres "
       "la cloture du NYSE (Padysak & Vojtko 2022)")
    c = CRYPTO_CME["BTC"][3]
    df = minutes_crypto("BTC", seance=False)
    st, crit = {}, {}
    # V : signe de 00:00 -> 00:30 UTC, position 23:30 -> 00:00 UTC (seance CME)
    sig = fenetres_utc(df, 0, 30, seance=False).set_index("jour")
    pos = fenetres_utc(df, 23 * 60 + 30, 24 * 60).set_index("jour")
    pos = pos[pos.n == 30]
    sens = np.sign(sig["r"]).reindex(pos.index)
    ok = sens.notna() & (sens != 0)
    brut = (sens[ok] * pos.r[ok])
    jours = pd.DatetimeIndex(sorted(set(pd.DatetimeIndex(fenetres_utc(df, 0, 24 * 60).jour))))
    for k, nom in ((1.0, ""), (2.0, " couts x 2")):
        net = brut - 2 * c * k
        st["V" if k == 1.0 else "Vs"] = resume(f"V   derniere demi-heure dans le sens de la premiere{nom}", net, jours, pr,
                                               net.groupby(net.index).sum().reindex(jours).fillna(0.0))
    tem = pos.r - 2 * c
    st["TV"] = resume("    temoin : achat de 23:30 a 00:00 UTC chaque jour", tem, jours, pr, tem.groupby(tem.index).sum().reindex(jours).fillna(0.0))
    netv = brut - 2 * c
    crit["V"] = criteres(netv, netv, tem)
    verdict(pr, "H12 (V, demi-heure)", crit["V"], st["V"])
    pr(f"      heures en position par an : {len(netv) * 0.5 / 9.1:.0f}")
    # R1 : achat 21:00 -> 23:00 UTC, minutes de la seance CME
    w = fenetres_utc(df, 21 * 60, 23 * 60)
    x = pd.Series(w.r.to_numpy(), index=pd.DatetimeIndex(w.jour))
    x.index = x.index + pd.to_timedelta(np.arange(len(x)) % 1000, unit="ns")
    dur = float((w.fin - w.debut + 1).mean())
    for k, nom in ((1.0, ""), (2.0, " couts x 2")):
        net = x - 2 * c * k
        st["R1" if k == 1.0 else "R1s"] = resume(f"R1  achat 21:00 -> 23:00 UTC (seance CME, {dur:.0f} min en moyenne){nom}", net, jours, pr,
                                                 net.groupby(net.index.normalize()).sum().reindex(jours).fillna(0.0))
    w0 = fenetres_utc(df, 9 * 60, 11 * 60)
    w0 = w0[pd.DatetimeIndex(w0.jour).isin(pd.DatetimeIndex(w.jour))]
    t0 = pd.Series(w0.r.to_numpy() - 2 * c, index=pd.DatetimeIndex(w0.jour))
    st["TR1"] = resume("    temoin : achat de 09:00 a 11:00 UTC les memes jours", t0, jours, pr, t0.groupby(t0.index).sum().reindex(jours).fillna(0.0))
    netr = x - 2 * c
    crit["R1"] = criteres(netr, netr, t0)
    verdict(pr, "H12 (R1, deux heures apres le NYSE)", crit["R1"], st["R1"])
    pr(f"      heures en position par an : {len(netr) * dur / 60 / 9.1:.0f}")
    ret = [k for k in ("V", "R1") if crit[k]["passe"] and st[k]["dsr"] >= SEUIL_DSR]
    pr(f"VERDICT H12 : retenue(s) : {', '.join(ret) or 'aucune'} ; fiables au sens du tableau de bord : "
       f"{', '.join(k for k in ('V', 'R1') if st[k]['fiable']) or 'aucune'}")
    best = max(("V", "R1"), key=lambda k: st[k]["sharpe"] if np.isfinite(st[k]["sharpe"]) else -9)
    stv = dict(st)
    stv["V"] = st[best]
    return dict(code="H12", titre="Bitcoin : fenetres courtes (Wen et al. 2022 ; Padysak & Vojtko 2022)", strategies=stv,
                criteres=crit[best], retenue=bool(ret), instruments=["MBT"], heures="23:30-00:00 UTC ; 21:00-23:00 UTC", retenues=ret)


# =============================================================================
#  H13 - NQ 1-A etendue a d autres grandes capitalisations
# =============================================================================
NOUVELLES = ("TSLA", "AVGO", "NFLX", "COST", "ADBE", "AMD", "INTC", "CSCO")


def jours_resultats(fichier: str, symboles=None) -> pd.DataFrame:
    """Premier 8-K de resultats de chaque jour (minute entamee, New York) entre 16:00 et 16:43."""
    from . import calendriers as K
    c = K._csv(fichier)
    if symboles is not None:
        c = c[c.symbole.isin(symboles)]
    c = c[~((c.symbole == "GOOGL") & (c.date == "2023-04-20"))]
    hm = c.accepte.str.split(":", expand=True).astype(int)
    c = c.assign(date=pd.to_datetime(c.date), t=hm[0] * 60 + hm[1] + (hm[2] > 0))
    c = c[(c.t >= 16 * 60) & (c.t <= 16 * 60 + 43)]
    return c.groupby("date").agg(t=("t", "min"), symboles=("symbole", lambda x: "+".join(sorted(set(x))))).reset_index()


def h13(pr) -> dict:
    from .soixante import cout_bp, jours_ouvres_us
    from .soixante_bc import FIN_DONNEES, _rs
    pr("")
    pr("H13 - NQ 1-A ETENDUE : resultats de " + ", ".join(NOUVELLES) + " en plus des 6 d origine (8-K EDGAR)")
    nq = marche("NQ")
    orig = jours_resultats("resultats_megacaps.csv")
    nouv = jours_resultats("resultats_nasdaq_suite.csv", NOUVELLES)
    tous = pd.concat([orig, nouv]).groupby("date").agg(t=("t", "min"), symboles=("symboles", "+".join)).reset_index()
    seules = nouv[~nouv.date.isin(orig.date)]
    cout = cout_bp("NQ", float(np.nanmedian(nq.c[-500000:])), True)
    tj = jours_ouvres_us(nq)
    tj = tj[~tj.isin(pd.DatetimeIndex(tous.date))]
    tem = (np.sign(_rs(nq, tj, 16 * 60, 16 * 60 + 20, ET)) * _rs(nq, tj, 16 * 60 + 20, 16 * 60 + 50, ET) * 1e4 - cout).dropna() / 1e4
    jours = pd.bdate_range("2016-01-04", "2026-08-28")

    def regle(ev):
        ev = ev[ev.date <= FIN_DONNEES]
        d, T = pd.DatetimeIndex(ev.date), ev.t.to_numpy().astype(int)
        brut = np.sign(_rs(nq, d, 16 * 60, T + 15, ET)) * _rs(nq, d, T + 15, np.minimum(T + 45, 16 * 60 + 59), ET) * 1e4
        return ((brut - cout) / 1e4).dropna()

    st, crit = {}, {}
    pr(f"  jours d evenement : 6 d origine {len(orig)}, nouvelles {len(nouv)}, ensemble {len(tous)}, nouvelles seules {len(seules)} ; "
       f"cout {cout:.2f} pb l aller-retour")
    for code, ev, nom in (("A", orig, "A   NQ 1-A d origine (6 valeurs, reference, pas un essai)"), ("V", tous, "V   les 6 + les 8 nouvelles"),
                          ("R1", seules, "R1  les 8 nouvelles seules (jours sans les 6)")):
        x = regle(ev)
        st[code] = resume(nom, x, jours, pr, x.groupby(x.index).sum().reindex(jours).fillna(0.0))
        if code != "A":
            crit[code] = criteres(x, x, tem)
            verdict(pr, f"H13 ({code})", crit[code], st[code])
            pr(f"      {len(x) / 10.65:.0f} jours par an, environ {len(x) * 0.5 / 10.65:.0f} h en position par an")
    st["T"] = resume("    temoin : autres jours, 16:20 -> 16:50 dans le sens de 16:00 -> 16:20", tem, jours, pr,
                     tem.groupby(tem.index).sum().reindex(jours).fillna(0.0))
    ret = [k for k in ("V", "R1") if crit[k]["passe"] and st[k]["dsr"] >= SEUIL_DSR]
    pr(f"VERDICT H13 : retenue(s) : {', '.join(ret) or 'aucune'} ; fiables au sens du tableau de bord : "
       f"{', '.join(k for k in ('V', 'R1') if st[k]['fiable']) or 'aucune'}")
    stv = dict(st)
    best = max(("V", "R1"), key=lambda k: st[k]["sharpe"] if np.isfinite(st[k]["sharpe"]) else -9)
    stv["V"] = st[best]
    return dict(code="H13", titre="NQ 1-A etendue a TSLA, AVGO, NFLX, COST, ADBE, AMD, INTC, CSCO (8-K EDGAR)", strategies=stv,
                criteres=crit[best], retenue=bool(ret), instruments=["NQ (MNQ)"], heures="T+15 -> T+45 apres le 8-K (16:15-16:59 New York)",
                retenues=ret)


HYPOTHESES = {"H1": h1, "H2": h2, "H3": h3, "H4": h4, "H5": h5, "H6": h6, "H7": h7, "H8": h8, "H9": h9, "H10": h10, "H11": h11, "H12": h12,
              "H13": h13}


# =============================================================================
#  Lancement
# =============================================================================
def etude(codes=None, sortie: str | None = None, log=print) -> dict:
    t0 = datetime.now()
    L = []
    pr = L.append
    pr("=" * 118)
    pr(" LOT « CRENEAUX VIDES » : STRATEGIES FUTURES INTRADAY POUR LES HEURES SANS STRATEGIE FIABLE")
    pr("=" * 118)
    pr(f"Protocoles : en-tete de nexus/perso/creneaux.py (ecrits avant chaque calcul). Essais cumules : {N_ESSAIS}.")
    res = {}
    for code in (codes or list(HYPOTHESES)):
        res[code] = HYPOTHESES[code](pr)
    texte = "\n".join(L)
    sortie = sortie or os.path.join(PY_DIR, "recherche", "resultats_creneaux.txt")
    ancien = ""
    if codes and os.path.exists(sortie):
        with open(sortie, encoding="utf-8") as fh:
            ancien = fh.read() + "\n"
    with open(sortie, "w", encoding="utf-8") as fh:
        fh.write(ancien + texte + f"\n(calcule en {(datetime.now() - t0).seconds} s le {datetime.now():%Y-%m-%d %H:%M})\n")
    for code, r in res.items():
        st = r["strategies"]
        lignes = [dict(code=k, nom=v["nom"], n=v["n"], moyenne=v["moyenne"], t=v["t"], t1=v["t1"], t2=v["t2"],
                       temoin=r["criteres"]["temoin"] if k == "V" else None, welch=r["criteres"]["welch"] if k == "V" else None,
                       sharpe_an=v["sharpe"], dsr=v["dsr"]) for k, v in st.items()]
        echecs = [k for k, v in r["criteres"]["tests"].items() if not v] + ([] if st["V"]["dsr"] >= SEUIL_DSR else [f"Sharpe deflate >= {SEUIL_DSR}"])
        exporter(f"creneaux_{code}", dict(titre=r["titre"], sous=f"{r['heures']} ; {', '.join(r['instruments'])} ; net en pb par trade ; "
                                          f"moities avant / apres le 01/01/2021 ; {N_ESSAIS} essais.", lignes=lignes, echecs=echecs,
                                          retenue=r["retenue"], fiable=st["V"]["fiable"], n_essais=N_ESSAIS))
    log(texte)
    return res


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--hypotheses", help="codes separes par des virgules (par defaut : toutes)")
    ap.add_argument("--sortie")
    a = ap.parse_args(argv)
    etude(a.hypotheses.split(",") if a.hypotheses else None, a.sortie)


if __name__ == "__main__":
    main()
