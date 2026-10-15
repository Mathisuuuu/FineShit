# Tableau de bord Nexus (Node.js)

Tableau de bord local qui affiche, pour chaque stratégie **validée** (et pour les candidates à l'étude) :
la courbe de capital, les pertes, les rendements par année et par mois, **toutes les statistiques vectorbt**
(`returns.stats()`, `drawdowns.stats()`, `trades.stats()`, `positions.stats()`, `orders.stats()`,
`pf.stats()`), la liste des trades, et la batterie de tests :

| Famille | Tests |
|---|---|
| Comptabilité | rejeu vectorbt des exécutions du moteur, second programme indépendant, biais d'anticipation (prix futurs modifiés) |
| Performance | Sharpe complet, avant / après publication, 2 dernières années, années positives |
| Robustesse statistique | IC du Sharpe par bootstrap BCa (scipy), Sharpe probabiliste, Sharpe déflaté (vectorbt), test des signes (permutation scipy) |
| Monte Carlo | perte max (ordre mélangé, tirage avec remise), gain total, éventail des trajectoires |
| Sensibilité | coûts ×0 à ×3, latence, jambes de la stratégie |
| Placebo | mêmes heures, autres jours (Gotobi) |
| Sur-ajustement | plateau de paramètres (carte de chaleur), PBO, walk-forward 3 ans / 6 mois |

La page **Comparaison** montre toutes les stratégies côte à côte, leurs corrélations (journalières et
mensuelles) et un portefeuille combiné à risque égal.

## Lancer

Node.js 18 ou plus récent, aucune dépendance à installer.

```
# 1. calculer les resultats (depuis le dossier Python/, plusieurs minutes)
cd Python
python -m nexus tableau --cotations "C:\Users\Mathis\Desktop\Cotations"

# 2. demarrer le serveur
cd ..\Dashboard
node serveur.js
# puis ouvrir http://localhost:3000
```

Les graphiques utilisent Plotly, chargé depuis cdn.jsdelivr.net (connexion Internet nécessaire au
premier affichage).

Le bouton **Recalculer** relance l'étape 1 depuis le navigateur. Il faut d'abord copier
`config.exemple.json` en `config.json` et y indiquer le chemin du dossier Cotations et la commande Python.

Options : `PORT=3001 node serveur.js`, `DONNEES=autre_dossier node serveur.js`. Le serveur n'écoute
que sur la machine locale (127.0.0.1) ; `HOTE=0.0.0.0` l'ouvre au réseau local.

## Ajouter une stratégie

- **Stratégie validée** : dans le moteur Python, la classe porte `VALIDATED = "AAAA-MM-JJ"` (voir
  `Python/nexus/strategies/s1_noiseareanq.py`). `python -m nexus tableau` l'exporte automatiquement,
  avec ses textes (`TITRE`, `RESUME`, `FONCTIONNEMENT`, `POURQUOI`, `SOURCES`), sa grille (`GRILLE`) et
  ses scénarios de sensibilité (`SENSIBILITE`).
- **Candidate** : ajoutée à la main dans `Python/nexus/tableau.py` (fonction `exporter`), comme le Gotobi.

## Données et licence

Le dossier `donnees/` contient des résultats calculés sur des cotations Databento sous licence
(usage privé). Il est exclu du dépôt (`.gitignore`) : ne pas le publier.

## Tests

```
npm test        # serveur : API, chemins refuses, interface, recalcul
```
