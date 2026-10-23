# Pistes « taux » : contrats sur le Trésor américain (ZN, ZB et voisins)

Brouillon du 2026-10-21, à faire valider par l'utilisateur AVANT tout achat de données et tout calcul.
Méthode : [methode-strategie-papiers] — lire chaque papier en entier, chercher les papiers contraires, figer les
règles dans l'en-tête du module avant le calcul, ne rien retoucher ensuite.

## Les contrats (CME, CBOT)

| Code | Sous-jacent | Valeur d'un point | Tick | Micro |
|---|---|---|---|---|
| ZT | Treasury 2 ans | 2 000 $ | 1/8 de 1/32 | — |
| ZF | Treasury 5 ans | 1 000 $ | 1/4 de 1/32 | — |
| ZN | Treasury 10 ans | 1 000 $ | 1/2 de 1/32 (15,625 $) | 10Y Micro Yield (rendement, autre mécanique) |
| TN | Ultra 10 ans | 1 000 $ | 1/2 de 1/32 | — |
| ZB | Treasury 30 ans (« bond ») | 1 000 $ | 1/32 (31,25 $) | — |
| UB | Ultra bond | 1 000 $ | 1/32 | — |

Pour un compte prop de 50 000 à 150 000 $ : un ZN (~110 000 $ de nominal, ~4-6 % de vol annuelle) se tient, un ZB
(~115 000 $, vol ~2x ZN) aussi à petite taille. À vérifier dans chaque test, comme pour MGC / MJY.

## Pourquoi les taux

- Classe d'actifs absente de nos 9 contrats : corrélation attendue faible avec S1 / ORB (Nasdaq) et Gotobi (yen).
- Le marché est rythmé par un calendrier PUBLIC et OBLIGÉ : adjudications du Trésor (le Trésor doit emprunter),
  publications de 8:30 ET, FOMC, roulement trimestriel, fin de mois des indices obligataires.
- Les fenêtres sont courtes et tombent sur des jours précis : profil des stratégies courtes recherché.

## Verdict après lecture (2026-10-21)

Textes lus en entier : Fleming-Liu-Nguyen, NY Fed Staff Report 1188 (mars 2026, révisé juillet 2026) ;
Hartley-Schwarz, « Predictable End-of-Month Treasury Returns » (2019) ; Kurov-Sancetta-Strasser-Wolfe, BCE WP 1901
(2016, publié JFQA). Lus en partie / en résumé : Dyer-Fleming-Shachar, Liberty Street Economics (sept. 2024) ;
Somogyi (FRBSF) ; Somogyi-Wallen-Xu (HBS WP 26-033) ; Sigaux (BCE WP 2208, JBF 2024).

| Piste | Verdict | Pourquoi |
|---|---|---|
| T3 fin de mois | **À tester en premier, gratuitement d'abord** | Sharpe ≈ 1 sur 1990-2018, présent dans chaque tranche de 5 ans y compris 2015-2019, confirmé sur les futures ; cause (indices obligataires, assureurs, fonds passifs) qui GRANDIT : volume du dernier jour +46 % depuis 2020, nul avant 2015 (NY Fed 2024). Le papier s'arrête en 2018 : 2019-2026 est un vrai hors échantillon. |
| T1 adjudications | Seconde, seulement en version conditionnelle | Effet causal confirmé (forme en V centrée sur 13:00) mais divisé par plus de 2 depuis 2015 (Fleming 2026, tableau 3 : 10 ans 5,2 pb de prix sur les 6 h, 30 ans 14,2 pb, 5 ans 4,5 pb, significatifs à 10 % seulement pour 10 et 30 ans). Par contrat ZN : environ 55 $ bruts pour les deux jambes contre environ 70 $ de coûts (2 allers-retours à 1 tick + commission) ; ZB : environ 160 $ contre 135 $. Ne vaut que si la pression est plus forte : MOVE élevé (+0,43 pb de rendement par écart-type), demande peu élastique (dispersion des offres, publiée à 13:0x). |
| T2 publications 8:30 | **Rejetée à la lecture** | La dérive avant publication (Kurov et al.) suit le signe de la surprise, inconnu avant 8:30 sans information privée, et elle est plus faible pour l'emploi et le CPI (procédures PFEI strictes). Après publication, Fleming 2026 (annexe A5) ne trouve aucune dérive des taux après l'emploi. |
| T4 FOMC | Inchangé (pas prioritaire) | Note : Fleming 2026 retrouve une baisse persistante des taux de 0,5-1,5 pb dans les 3 h après le FOMC (Brooks-Katz-Lustig 2018, Indriawan et al. 2021) : nouvelle piste possible, pas encore lue. |
| T5 roulement | Non lue | Aucune source trouvée. |

Plan qui en découle :
1. T3 sur données GRATUITES journalières (IEF / TLT ajustés, moins le T-bill ; ZN=F de Yahoo pas raboutable) :
   règle de Hartley-Schwarz figée (achat t = 2 jours avant la fin du mois, vente à la clôture du dernier jour),
   2016-2026, puis 2019-2026 seul (hors échantillon). Compte comme un essai. IEF avait servi de jambe dans
   fin_de_mois.py (écart ES - IEF), jamais seul en fin de mois : test encore aveugle sur ce point.
2. Si T3 passe : acheter les minutes ZN / ZB / ZF pour la version contrat à terme et séparer la part du jour (16:59 ->
   15:00 ou clôture le dernier jour) de la nuit, pour les comptes qui doivent être à plat le soir.
3. T1 conditionnelle seulement si les minutes sont achetées pour T3 (même jeu de données, pas d'achat de plus).

## Hypothèses (lot fermé, ordre de priorité)

Repère sur les sources : [S] référence sûre, à lire en entier ; [T] travail récent ou contraire à TROUVER et lire
avant de figer quoi que ce soit (aucune règle ne sera écrite sans ce papier).

### T1. Cycle des adjudications (priorité 1)
- Mécanisme : avant une grosse adjudication, les teneurs de marché doivent absorber l'offre ; le prix baisse avant
  et remonte après (pression d'offre anticipée, arbitrage limité par le capital des intermédiaires).
- Sources : [S] Lou, Yan, Zhang, « Anticipated and Repeated Shocks in Liquid Markets », Review of Financial Studies
  2013 ; [T] mises à jour post-2016 (cycle encore présent ? déplacé dans la journée ?) et papiers sur la hausse des
  volumes émis depuis 2020.
- Version courte à tester : jours d'adjudication 10, 30 ans (et 2, 5, 7 ans pour le témoin), vendre ZN/ZB le matin,
  racheter à l'heure de l'adjudication (13:00 ET), ou acheter juste après le résultat. Fenêtres et horaires repris des
  papiers, calendrier officiel du Trésor (gratuit, TreasuryDirect).
- Témoin : mêmes heures les jours sans adjudication.

### T2. Réaction aux publications de 8:30 ET (emploi, CPI)
- Mécanisme : le prix s'ajuste en quelques minutes à la surprise, puis le flux d'ordres et la liquidité qui revient
  peuvent prolonger ou corriger le mouvement.
- Sources : [S] Fleming et Remolona, Journal of Finance 1999 ; [S] Balduzzi, Elton, Green, JFQA 2001 ;
  [S] Brandt et Kavajecz, Journal of Finance 2004 (flux d'ordres) ; [T] travaux récents sur la continuation ou le
  retournement 30-120 min après la publication.
- Version courte : entrer 5-15 min après 8:30 dans le sens du premier mouvement (ou à l'inverse si les papiers récents
  disent retournement), sortir à 10:00 ou 11:00. Jours : premier vendredi (emploi), jour du CPI.
- Remarque : la surprise elle-même (consensus) n'est pas dans nos données gratuites ; on n'utilise que le prix.

### T3. Fin de mois : allongement de duration des indices obligataires
- Mécanisme : chaque fin de mois, les indices obligataires (Bloomberg US Aggregate / Treasury) ajoutent les nouvelles
  émissions ; les fonds indiciels doivent acheter de la duration dans les dernières heures du dernier jour ouvré.
- Sources : [T] papier académique à trouver (effet surtout décrit par les praticiens) ; le test ne se fait que si une
  source sérieuse existe. Différent de fin_de_mois.py (rééquilibrage 60/40 actions, rejeté).
- Version courte : acheter ZN/ZB/UB l'après-midi du dernier jour ouvré, revendre à 15:00 ET (heure de fixation des
  indices) ou au plus tard le lendemain matin.

### T4. Veille et matin des réunions de la Fed sur les taux
- Sources : [S] Lucca et Moench, Journal of Finance 2015 (actions) ; Pan et Peng 2026 (dérive des obligations la
  veille, déjà lue le 2026-10-19 : effet jugé petit).
- Statut : PAS prioritaire. Le cycle FOMC a déjà échoué 3 fois sur les actions ; un test ne vaut que si T1-T3
  échouent et seulement avec la règle exacte de Pan et Peng.

### T5. Roulement trimestriel des contrats
- Mécanisme : fin février, mai, août, novembre, la position ouverte passe d'une échéance à la suivante ; les gros
  porteurs (fonds, CTA) roulent sur quelques jours.
- Sources : [T] à trouver ; sans source sérieuse, abandonnée.
- Test sur l'écart entre échéances : demande les deux échéances (pas seulement le continu), coût de données en plus.

### Écartées d'emblée
- Zone de bruit / ORB recopiées sur ZN : nouvel essai sans papier propre, baisse le Sharpe déflaté de tout le reste.
- FOMC « 8 h après » et surprise de la Fed : déjà couverts (fiche or n° 4 avec ZT, cycle_fomc).

## Données nécessaires

- Databento GLBX.MDP3, barres 1 minute, contrat continu roulé au volume (.v.0), 2016-01-01 -> aujourd'hui, même
  format que Cotations/ : au minimum ZN et ZB ; idéalement ZF et UB pour la réplication ; ZT si absent.
- Calendriers gratuits : adjudications (TreasuryDirect), publications (BLS), FOMC (déjà dans le dépôt).
- Coût exact : `python -m nexus.databento_dl cout ZN.v.0 2016-01-01 2026-10-21` (n'achète rien). Il faut la clé
  DATABENTO_API_KEY dans .env.txt : elle n'est pas sur ce poste au 2026-10-21.

## Budget d'essais

N_ESSAIS du programme : 424 au 2026-10-20. Ce lot ajoute au plus 5 hypothèses x (référence + version) ; chaque essai
compte, réussi ou non. Les 12 derniers mois (2025-10 -> 2026-10) restent verrouillés et ne sont regardés qu'une fois,
à la fin du lot.
