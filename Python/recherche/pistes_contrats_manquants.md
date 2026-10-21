# Hypothèses bloquées par un contrat ou des données qui nous manquent

Inventaire du 2026-10-21, classé de la plus fiable à la moins fiable. Fiabilité = force de la source (revue, institution,
réplique indépendante) + ce que nos propres tests en disent déjà + compatibilité avec nos critères (futures intraday,
courte, prop firm, calcul de puissance t ≥ 3). Chaque test hors du n° 1 compte comme essai.

**Correction du 2026-10-21 (soir)** : les pistes 2, 3 et 6 étaient **déjà testées** le 2026-10-20, avec les données
gratuites déjà téléchargées (`Python/.cache/binance` : BTCUSDT et ETHUSDT 08/2017-09/2026 ; `Python/.cache/histdata` :
JPXJPY, XAGUSD, ETXEUR, UKXGBP, EURJPY, AUDJPY 2015-2026). Les relancer serait refaire un essai sur des résultats déjà
vus : elles sortent de la liste des pistes ouvertes.

| # | Hypothèse | Source | Données manquantes | Coût | Fiabilité | Limite |
|---|---|---|---|---|---|---|
| 1 | **ORB NQ rejouée sur 2010-2015** (confirmation, pas un nouvel essai) | Zarattini-Barbon-Aziz 2024 ; nos 29 + 10 contrôles | NQ minutes 2010-2015 | Databento (clé à créer, prix à chiffrer) | ★★★★★ | aucune : t attendu ≈ 2,3 sur la période, ≈ 3,7 sur 2010-2026 |
| 2 | ~~Tendance crypto (Donchian, taille à la volatilité) sur MBT / MET~~ **DÉJÀ TESTÉE** (H11, `resultats_creneaux.txt`, Binance 2017-2026) | Zarattini-Pagani-Barbon 2025 | — (téléchargé le 2026-10-20) | — | — | boombitch MBT : Sharpe 1,56 [1,05 ; 2,03], moitiés 1,40 / 1,71, déflaté 1,00, **fiable** mais rejetée par la méthode (Welch 1,39 < 2) et trop longue (486 h/an) ; règle exacte ZPB25 : 0,42 ; MET : −0,74 |
| 3 | ~~Momentum intraday du Nikkei~~ **DÉJÀ TESTÉE** (N1, N2, J1, `resultats_zones.txt`, HistData JPXJPY) | Li-Sakkas-Urquhart, *JFM* 2022 ; Zarattini-Aziz 2023 | — (téléchargé le 2026-10-20) | — | — | N1 momentum : Sharpe −1,16 (moitiés −0,79 / −1,57) ; N2 ORB : −0,20 ; J1 après les résultats japonais : −0,89 ; toutes rejetées |
| 4 | **Cycle des adjudications du Trésor, version conditionnelle** (MOVE élevé, demande peu élastique) | Fleming-Liu-Nguyen, NY Fed SR 1188 (2026), causal sur 33 ans | ZN / ZB minutes | Databento | ★★ | depuis 2015 le gain brut ≈ les coûts (ZN 55 $ contre 70 $) ; ne vaut que sous conditions |
| 5 | **Fin de mois sur futures ZN / ZB, partie de jour seule** | Hartley-Schwarz 2019 | ZN / ZB minutes | Databento | ★★ | rejetée en journalier (déflaté 0,10) ; R3 prometteuse mais vue après coup ; puissance < 3 avec 129 mois |
| 6 | ~~Momentum de séance sur l'argent (SIL micro)~~ **DÉJÀ TESTÉE** (A1, `resultats_zones.txt`, HistData XAGUSD) | Wei 2026 | — (téléchargé le 2026-10-20) | — | — | Sharpe −0,29 [−0,88 ; 0,30], rejetée ; l'or (H1) l'était aussi |
| 7 | **Saisonnalité intraday du Brent / CL** | Ewald et al., *Quantitative Finance* 2025 | pas les données : les heures exactes (texte payant, embargo jusqu'en 2027) | — | ★★ | choisir les heures nous-mêmes = fouille de données |
| 8 | **Or n° 4 « Fed accommodante » avec le vrai rendement à 2 ans** | Awartani et al. | ZT minutes | Databento | ★ | 9 trades : puissance très loin du seuil |
| 9 | **Fade de la nuit sur petites capitalisations, vrai RTY / M2K** | S06-C | RTY minutes | Databento | ★ | sur IWM : Sharpe 0,19-0,23, t 0,6-0,8 |
| 10 | Carnet d'ordres ES / NQ (déséquilibre, absorption), VIX VX, perpétuels BTC | fiches S10-A, S13, S14, fil ES/NQ 2 et 4 | Databento mbp-1 / tbbo, VX, Binance perps | cher (carnet) | ★ | sources faibles ou non publiées |

## Ordre conseillé
1. **Clé Databento** → chiffrer puis jouer le n° 1 (seul test qui ne coûte aucun essai et peut faire passer l'ORB au-dessus
   de 0,95). Le même achat peut couvrir ZN / ZB pour les n° 4-5 seulement si le calcul de puissance le justifie.
2. ~~Micro bitcoin (suite du n° 2), version courte~~ **CLOSE le 2026-10-21** : Zarattini-Pagani-Barbon 2025 lu en
   ENTIER (PDF des auteurs, concretumgroup.com, version du 9 avril 2025, 38 pages). Le papier ne propose AUCUNE version
   courte : barres journalières, positions de plusieurs jours à plusieurs mois, bitcoin 24 h / 24, aucune sortie de
   séance. Temps en position de chaque modèle du papier, mesuré sur Binance 2017-2026 (structure seulement, aucun
   rendement calculé ; script dans le scratchpad de la session) : 5 j → 3 923 h/an (durée médiane 4 j), 10 j → 3 604,
   20 j → 3 465, 30 j → 3 375, 60 à 360 j → 3 344 à 3 460 ; soit 8 à 10 fois la limite de 400 h. Calcul de puissance
   sans objet (aucune règle courte à tester) : aucun essai compté. Écart interne du papier noté : Sortino du Combo BTC
   2,03 (tableau 1, sans coûts) contre 1,23 (tableau 3, coûts 10 pb) pour un Sharpe presque égal (1,58 / 1,56). La
   version « séance CME » (R1 de H11, 0,42) reste la seule adaptation prop firm possible, déjà rejetée.
3. Rien d'autre n'est gratuit et ouvert : les n° 7 à 10 sont trop faibles ou sans données.
