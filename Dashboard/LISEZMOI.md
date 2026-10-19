# Tableau de bord Nexus (Node.js)

Tableau de bord local qui affiche la stratégie **validée** (S1 Noise Area NQ) et les candidates à l'étude
(Gotobi 6J, ORB 5 min NQ, or la nuit GC, fiche 15 LETF NQ / ES) : la courbe de capital, les pertes, les
rendements par année et par mois, **toutes les statistiques vectorbt** (`returns.stats()`, `drawdowns.stats()`,
`trades.stats()`, `positions.stats()`, `orders.stats()`, `pf.stats()`), la liste des trades, et la batterie de tests :

| Famille | Tests |
|---|---|
| Comptabilité | rejeu vectorbt des exécutions du moteur, second programme indépendant, biais d'anticipation (prix futurs modifiés) |
| Performance | Sharpe complet, avant / après publication, 2 dernières années, années positives |
| Robustesse statistique | IC du Sharpe par bootstrap BCa (scipy), Sharpe probabiliste, Sharpe déflaté (vectorbt), test des signes (permutation scipy) |
| Monte Carlo | perte max (ordre mélangé, tirage avec remise), gain total, éventail des trajectoires |
| Sensibilité | coûts ×0 à ×3, latence, jambes ou variantes de la stratégie |
| Placebo | mêmes heures, autres jours (Gotobi) ; témoins de l'or : or gardé en permanence, séance du COMEX seule, version intraday ; mêmes règles dans une autre demi-heure (LETF) |
| Mécanisme | LETF : pente de la dernière demi-heure sur le rendement du jour et interaction avec le régime gamma (Newey-West), par période |
| Sur-ajustement | réglage **figé** (rien n'est rechoisi) : stabilité sur 6 sous-périodes et par moitié, plateau de paramètres (carte de chaleur), PBO, walk-forward 3 ans / 6 mois, test SPA de Hansen (`arch`), Sharpe corrigé des essais multiples (Bonferroni, Holm, BHY via `statsmodels`), durée minimale de backtest, prime du choix du réglage, test sur hasard (marchés simulés sans momentum pour S1, faux jours gotobi pour le Gotobi, jours tirés au hasard pour l'ORB et la LETF, pause du COMEX déplacée dans la séance pour l'or) |

La page **Comparaison** montre toutes les stratégies côte à côte, leurs corrélations (journalières et
mensuelles) et un portefeuille combiné à risque égal. Le lien **Archive de la recherche** (barre de gauche)
ouvre `donnees/recherche.html` : la page autonome des 74 stratégies testées dans les sessions locales,
écrite par `python -m nexus.perso.tableau` (depuis `Python/`).

## Lancer

Node.js 18 ou plus récent, aucune dépendance à installer. Côté Python, l'environnement `Python/.venv`
(`pip install -r requirements.txt`, voir `Python/LISEZMOI.md` § 2).

```
# 1. calculer les resultats (depuis le dossier Python/, environ 10 minutes ; lit ../Cotations par defaut)
cd Python
.venv\Scripts\python -m nexus tableau
.venv\Scripts\python -m nexus.perso.tableau      # archive de la recherche locale (1 minute)

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
que sur la machine locale (127.0.0.1) ; `HOTE=0.0.0.0` l'ouvre au réseau local.

## Ajouter une stratégie

- **Stratégie validée** : dans le moteur Python, la classe porte `VALIDATED = "AAAA-MM-JJ"` (voir
  `Python/nexus/strategies/s1_noiseareanq.py`). `python -m nexus tableau` l'exporte automatiquement,
  avec ses textes (`TITRE`, `RESUME`, `FONCTIONNEMENT`, `POURQUOI`, `SOURCES`), sa grille (`GRILLE`) et
  ses scénarios de sensibilité (`SENSIBILITE`).
- **Candidate** : une fonction `fiche_...` dans `Python/nexus/tableau.py`, ajoutée à la liste `CANDIDATES`
  (code pour `--seulement`, identifiant, fonction), comme le Gotobi (G1), l'ORB (O1), l'or (N1) et la
  fiche 15 (L1).

## Données et licence

Le dossier `donnees/` contient des résultats calculés sur des cotations Databento sous licence
(usage privé). Il est exclu du dépôt (`.gitignore`) : ne pas le publier.

## Tests

```
npm test        # serveur : API, chemins refuses, interface, recalcul, archive
```
