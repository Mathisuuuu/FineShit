# Hypothèses bloquées par un contrat ou des données qui nous manquent

Inventaire du 2026-10-21, classé de la plus fiable à la moins fiable. Fiabilité = force de la source (revue, institution,
réplique indépendante) + ce que nos propres tests en disent déjà + compatibilité avec nos critères (futures intraday,
courte, prop firm, calcul de puissance t ≥ 3). Rien de ceci n'est testé ; chaque test hors du n° 1 compte comme essai.

| # | Hypothèse | Source | Données manquantes | Coût | Fiabilité | Limite |
|---|---|---|---|---|---|---|
| 1 | **ORB NQ rejouée sur 2010-2015** (confirmation, pas un nouvel essai) | Zarattini-Barbon-Aziz 2024 ; nos 29 + 10 contrôles | NQ minutes 2010-2015 | Databento (clé à créer, prix à chiffrer) | ★★★★★ | aucune : t attendu ≈ 2,3 sur la période, ≈ 3,7 sur 2010-2026 |
| 2 | **Tendance crypto (Donchian, taille à la volatilité) sur MBT / MET** | Zarattini-Pagani-Barbon 2025 (Sharpe > 1,5 net) ; notre boombitch MBT : Sharpe 1,37, déflaté 1,00, mais depuis 2021 seulement | BTC / ETH minutes 2017-2020 (moitié 2016-2020 du filtre vide) | gratuit : Binance data.binance.vision (~250 Mo), proxy du future CME | ★★★★ | 486 h/an en position (> 400 h), à rendre plus courte |
| 3 | **Momentum intraday du Nikkei** (réplique S1 / ORB à l'ouverture de Tokyo) | Li-Sakkas-Urquhart, *JFM* 2022 (t = 4,07 au Japon) | Nikkei minutes | gratuit : HistData JPXJPY (CFD, même source que le DAX) | ★★★ | NKD ≈ 240 000 $ de notionnel, trop gros pour un compte de 50 000 $ ; les signaux de prix intraday hors NQ se sont éteints chez nous après 2020 (DAX, ES) |
| 4 | **Cycle des adjudications du Trésor, version conditionnelle** (MOVE élevé, demande peu élastique) | Fleming-Liu-Nguyen, NY Fed SR 1188 (2026), causal sur 33 ans | ZN / ZB minutes | Databento | ★★ | depuis 2015 le gain brut ≈ les coûts (ZN 55 $ contre 70 $) ; ne vaut que sous conditions |
| 5 | **Fin de mois sur futures ZN / ZB, partie de jour seule** | Hartley-Schwarz 2019 | ZN / ZB minutes | Databento | ★★ | rejetée en journalier (déflaté 0,10) ; R3 prometteuse mais vue après coup ; puissance < 3 avec 129 mois |
| 6 | **Momentum de séance sur l'argent (SIL micro)** | Wei 2026 (prépublication, or ET argent) | XAG minutes | gratuit : HistData XAGUSD | ★★ | source faible ; l'or seul a été rejeté (H1) |
| 7 | **Saisonnalité intraday du Brent / CL** | Ewald et al., *Quantitative Finance* 2025 | pas les données : les heures exactes (texte payant, embargo jusqu'en 2027) | — | ★★ | choisir les heures nous-mêmes = fouille de données |
| 8 | **Or n° 4 « Fed accommodante » avec le vrai rendement à 2 ans** | Awartani et al. | ZT minutes | Databento | ★ | 9 trades : puissance très loin du seuil |
| 9 | **Fade de la nuit sur petites capitalisations, vrai RTY / M2K** | S06-C | RTY minutes | Databento | ★ | sur IWM : Sharpe 0,19-0,23, t 0,6-0,8 |
| 10 | Carnet d'ordres ES / NQ (déséquilibre, absorption), VIX VX, perpétuels BTC | fiches S10-A, S13, S14, fil ES/NQ 2 et 4 | Databento mbp-1 / tbbo, VX, Binance perps | cher (carnet) | ★ | sources faibles ou non publiées |

## Ordre conseillé
1. **Clé Databento** → chiffrer puis jouer le n° 1 (seul test qui ne coûte aucun essai et peut faire passer l'ORB au-dessus
   de 0,95). Le même achat peut couvrir ZN / ZB pour les n° 4-5 seulement si le calcul de puissance le justifie.
2. **Binance (gratuit, accord à donner)** → n° 2 : la seule piste où nos chiffres sont déjà au niveau de S1 / Gotobi ;
   reste à la rendre courte (≤ 400 h/an) en suivant le papier, pas nos résultats.
3. **HistData JPXJPY (gratuit, accord à donner)** → n° 3, en sachant que le contrat est trop gros pour une petite prop.
