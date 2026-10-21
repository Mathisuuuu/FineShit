# Tableau de bord Nexus (Node.js)

Un seul tableau de bord pour **toutes les stratégies** : la stratégie validée (S1 Noise Area NQ), les candidates
étudiées dans les sessions cloud (Gotobi 6J, ORB 5 min NQ, or la nuit GC, fiche 15 LETF NQ / ES) et toutes les
stratégies testées en local par le runner (`Python/nexus/perso/runner.py`, environ 70). Toutes passent par **les
mêmes objets vectorbt** (`vbt.Portfolio`, accesseur `returns`) et **les mêmes tests**, et ont les mêmes pages :
courbe de capital, pertes, rendements par année et par mois, toutes les statistiques vectorbt (`returns.stats()`,
`drawdowns.stats()`, `trades.stats()`, `positions.stats()`, `orders.stats()`, `pf.stats()`), la liste des trades et
la batterie de tests.

Les stratégies du runner sont rejouées dans vectorbt à partir de leurs trades (`Python/nexus/tableau_runner.py`) :
deux ordres par trade, aux prix exécutés par leur moteur, frais = P&L brut − P&L net ; le P&L vectorbt est celui du
moteur, trade par trade (test « Rejeu vectorbt des trades du moteur »). Valorisation une fois par séance, à 17:00
New York (fin de séance CME), aux cours des mêmes données que le moteur.

Tests communs à toutes :

| Famille | Tests |
|---|---|
| Comptabilité | rejeu vectorbt des exécutions ou des trades du moteur, courbe vectorbt contre courbe du moteur |
| Performance | Sharpe complet, avant / après la coupure (publication, sinon 01/01/2021), 2 dernières années, années positives |
| Robustesse statistique | IC du Sharpe par bootstrap BCa (scipy), Sharpe probabiliste, **Sharpe déflaté du programme entier** (vectorbt, même nombre cumulé d'essais pour toutes, variance du Sharpe sous l'hypothèse nulle comme dans toute la recherche), test des signes (permutation scipy) |
| Monte Carlo | perte max (ordre mélangé, tirage avec remise), gain total, éventail des trajectoires |
| Sur-ajustement | stabilité sur 6 sous-périodes et par moitié, durée minimale de backtest |

Les candidates des sessions cloud ont en plus leurs tests propres, qui demandent de relancer la stratégie : biais
d'anticipation, sensibilité (coûts, latence, jambes), placebos, plateau de paramètres, PBO, walk-forward, test SPA,
Sharpe corrigé des essais multiples, test sur hasard, Sharpe déflaté avec les essais de leur propre recherche.

Pages :

| Page | Contenu |
|---|---|
| Groupe en direct | état du Groupe branché sur NinjaTrader (`python -m nexus.live` → `donnees/live.json`, relu toutes les 3 s) : passerelle et compte, garde-fou actif, valeur liquidative et résultat du jour, stratégies (statut, cibles, état), cible nette et position par instrument, exécutions, journal ; lecture seule, le Groupe se modifie dans `Python/nexus/live/groupe.json` (`public/direct.js`) |
| Comparaison | toutes les stratégies (tri par colonne, filtre de la barre de gauche), corrélations journalières et mensuelles et portefeuille combiné à risque égal des stratégies cochées, liste des non testées |
| Prop firm | la combinaison la plus **fiable** de stratégies **futures intraday** (positions soldées avant 17:00 New York) : statistiques vectorbt de chaque stratégie et de chaque combinaison (Sharpe et son IC à 95 % par bootstrap, Sharpe de chaque moitié, Sharpe déflaté comptant toutes les combinaisons essayées, perte max), classement par la borne basse de l'IC du Sharpe, combinaison recommandée, validation de la méthode de choix hors échantillon (choix sur 2016-2020, résultat sur 2021-2026) ; seules les stratégies **courtes** (au plus 400 h en position par an) entrent dans les combinaisons, colonnes « heures / an » et « % par 100 h » (rendement annuel à 10 % de volatilité pour 100 heures en position), tri possible par rendement par heure ; règles du compte et filtres modifiables, taux de réussite de l'évaluation recalculé dans le navigateur (`public/prop.js`, données de `Python/nexus/prop_combinaisons.py`) |
| Profil horaire | sur la dernière année, les heures (New York, pas de 30 min) où chaque stratégie futures intraday **fiable** est en position, la couverture de chaque créneau, les créneaux vides et les hypothèses testées pour les remplir (`public/profil.js`, données de `Python/nexus/profil_horaire.py`, lot `nexus/perso/creneaux.py`) |
| Études sur papiers | les « 60 stratégies intraday » (anomalies brutes) et les stratégies construites sur papiers (`Python/recherche/resultats_60.json`, `public/etudes.js`) |
| Une stratégie | vue d'ensemble, fonctionnement, statistiques vectorbt, trades, tests et Monte Carlo |

La barre de gauche liste toutes les stratégies (recherche par nom ou contrat ; filtres : toutes, futures intraday,
Sharpe ≥ 0,5, le moins d'alertes). Le badge indique le statut : validée, candidate, ou le verdict du runner.

## Lancer

Node.js 18 ou plus récent, aucune dépendance à installer. Côté Python, l'environnement `Python/.venv`
(`pip install -r requirements.txt`, voir `Python/LISEZMOI.md` § 2).

```
# 1. calculer les resultats (depuis le dossier Python/, environ 25 minutes ; lit ../Cotations par defaut)
cd Python
.venv\Scripts\python -m nexus tableau
#    --seulement R      : ne recalculer que les strategies du runner (les autres fiches sont reprises)
#    --seulement S1,G1  : seulement ces strategies

# 2. demarrer le serveur
cd ..\Dashboard
node serveur.js
# puis ouvrir http://localhost:3000
```

Les graphiques utilisent Plotly, chargé depuis cdn.jsdelivr.net (connexion Internet nécessaire au
premier affichage).

Le bouton **Recalculer** relance l'étape 1 depuis le navigateur. Par défaut il utilise `Python/.venv` et le
dossier `Cotations` du dépôt s'ils existent ; sinon, copier `config.exemple.json` en `config.json` et y
indiquer le chemin du dossier Cotations et la commande Python.

Options : `PORT=3001 node serveur.js`, `DONNEES=autre_dossier node serveur.js`. Le serveur n'écoute
que sur la machine locale (127.0.0.1) par défaut.

### Accès à distance (serveur du Groupe)

Sur le serveur Windows qui fait tourner NinjaTrader, le tableau de bord est joignable depuis n'importe où à
`http://<IP du serveur>:3000`, **avec mot de passe** :

| Réglage (`config.json`, non suivi par git) | Effet |
|---|---|
| `"hote": "0.0.0.0"`, `"port": 3000` | écoute sur l'IP publique ; le serveur **refuse de démarrer** sans `acces.json` |
| `"strategies": ["S1_NoiseAreaNQ", "Gotobi_6J"]` | seules ces fiches sont visibles, les autres sont introuvables (404) |
| `"pages": ["direct"]` | seule la page « Groupe en direct » (compte démo) est visible ; recalcul désactivé |

- Mot de passe : `node mot-de-passe.js` (identifiant + mot de passe d'au moins 12 caractères, saisis à la main).
  Il écrit `acces.json` : identifiant, sel et empreinte scrypt, jamais le mot de passe. Redémarrer ensuite le
  tableau de bord.
- Authentification HTTP Basic sur toutes les pages. Après 5 essais ratés depuis une même adresse, celle-ci est
  bloquée 15 minutes.
- **Sans HTTPS** : le mot de passe circule en clair sur le réseau. Choisir un mot de passe propre à ce tableau de
  bord.
- Sur le serveur, `donnees/` ne contient que l'index et les fiches du Groupe (les autres résultats, tirés des
  données sous licence, restent sur le PC). `live.json` y est écrit par `python -m nexus.live`.
- Démarrage automatique : tâche planifiée « Nexus - Tableau de bord » (au lancement du serveur, compte SYSTEM,
  relancée en cas d'arrêt) et règle de pare-feu « Nexus - tableau de bord (3000) ».

Fichiers lus dans `donnees/` : `index.json` (liste), un fichier par stratégie (`/api/strategies/<id>`), et quatre
annexes (`/api/annexe/<nom>`) : `rendements.json` (comparaison), `prop.json` (onglet Prop firm), `etudes.json`,
`profil.json` (profil horaire). Les fiches Gotobi, ORB et « or la nuit conforme » ont une famille de tests « Prop firms » :
la même stratégie avec le contrat qu'un compte de 50 000 à 150 000 $ peut tenir (micro MJY, MNQ, MGC).

## Ajouter une stratégie

- **Stratégie du runner** : l'ajouter à `TESTS` dans `Python/nexus/perso/runner.py` et la lancer ; elle entre
  dans le tableau au prochain `python -m nexus tableau` (ou `--seulement R`).
- **Stratégie validée** : dans le moteur Python, la classe porte `VALIDATED = "AAAA-MM-JJ"` (voir
  `Python/nexus/strategies/s1_noiseareanq.py`). `python -m nexus tableau` l'exporte automatiquement,
  avec ses textes (`TITRE`, `RESUME`, `FONCTIONNEMENT`, `POURQUOI`, `SOURCES`), sa grille (`GRILLE`) et
  ses scénarios de sensibilité (`SENSIBILITE`).
- **Candidate avec tests propres** : une fonction `fiche_...` dans `Python/nexus/tableau.py`, ajoutée à la liste
  `CANDIDATES` (code pour `--seulement`, identifiant, fonction), comme le Gotobi (G1), l'ORB (O1), l'or (N1) et la
  fiche 15 (L1).

## Données et licence

Le dossier `donnees/` contient des résultats calculés sur des cotations Databento sous licence
(usage privé). Il est exclu du dépôt (`.gitignore`) : ne pas le publier.

## Tests

```
npm test        # serveur : API, chemins refuses, interface, recalcul, annexes (/api/annexe/<nom>)
```
