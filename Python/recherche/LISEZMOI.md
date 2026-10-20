# Rapports de recherche

Un fichier par étude, écrit par le module indiqué (depuis `Python/`). Les protocoles sont dans l'en-tête de
chaque module, écrits avant le calcul. Toutes les stratégies (celles des sessions cloud et celles du runner local)
sont dans le tableau de bord Nexus, avec les mêmes tests (`python -m nexus tableau`, résultats dans
`../../Dashboard/donnees/`) ; les études ci-dessous sont dans sa page « Études sur papiers » : une nouvelle étude
exportée dans `resultats_60.json` (format commun) y apparaît d'elle-même au prochain export.

| Fichier | Module | Étude |
|---|---|---|
| `resultats_strategies.txt` / `.csv` | `nexus.perso.runner` | backtest des stratégies NinjaScript personnelles et des fiches (une ligne par stratégie, verdict) |
| `resultats_inversees.txt` | `nexus.perso.inversion` | stratégies perdantes jouées à l'envers |
| `resultats_alternatives.txt` | `nexus.perso.alternatives` | références naïves (bêta / alpha) des stratégies prometteuses |
| `resultats_ic_montecarlo.txt` | `nexus.perso.statistiques` | intervalles de confiance, edge par trade, Monte Carlo |
| `resultats_portefeuille_prop.txt`, `_150k.txt` | `nexus.perso.portefeuille` | portefeuille prop firm futures (50 000 $ et 150 000 $) |
| `resultats_orderflow.txt` | `nexus.perso.orderflow` | fiches du fil ES/NQ « 6 mois de simulation » |
| `resultats_fx.txt` | `nexus.perso.fx_trois` | trois stratégies FX combinées (6E, 6B, 6J, 6A) |
| `resultats_gotobi.txt` | `nexus.perso.gotobi` | Gotobi pre-fix drift (version locale, différente de la candidate du tableau de bord) |
| `resultats_or.txt` | `nexus.perso.or_anomalies` | dix anomalies intraday de l'or (GC) |
| `resultats_60.json`, `resultats_60_niveau_A.txt`, `resultats_60_niveaux_BC.txt` | `nexus.perso.soixante`, `soixante_bc` | les « 60 stratégies intraday » : anomalies brutes par niveau |
| `resultats_nq1_variantes.txt` | `nexus.perso.nq1_variantes` | NQ 1, diffusion des résultats des méga-capitalisations |
| `resultats_derive_nocturne.txt` | `nexus.perso.derive_nocturne` | dérive nocturne des futures d'indices (Fed de New York) |
| `resultats_vol_geree.txt` | `nexus.perso.vol_geree` | exposition gérée par la volatilité |
| `resultats_cycle_fomc.txt` | `nexus.perso.cycle_fomc` | cycle du FOMC et « Fed put » |
| `resultats_pression_cot.txt` | `nexus.perso.pression_cot` | pression de couverture / spéculative (COT de la CFTC) |
| `resultats_tendance.txt` | `nexus.perso.tendance` | suivi de tendance sur 9 futures |
| `resultats_carry_fx.txt` | `nexus.perso.carry_fx` | portage de devises (carry) |
| `resultats_saisonnalite.txt` | `nexus.perso.saisonnalite` | saisonnalité du même mois calendaire |
| `resultats_momentum_transversal.txt` | `nexus.perso.momentum_transversal` | momentum transversal 12-1 sur 9 futures |
| `resultats_rachat_baisse.txt` | `nexus.perso.rachat_baisse` | rachat après baisse (MAC(5)) |
| `resultats_gamma_intraday.txt` | `nexus.perso.gamma_intraday` | momentum de fin de séance conditionné au gamma des dealers |
| `resultats_bdlm_conditionnel.txt` | `nexus.perso.bdlm_conditionnel` | BDLM 2021 conditionné au gamma (spécification de l'arbre) |
| `resultats_fin_de_mois.txt` | `nexus.perso.fin_de_mois` | fin de mois : ventes forcées (Etula 2020) et rééquilibrage 60/40 (Harvey et al. 2026) |
| `resultats_weekend_crypto.txt` | `nexus.perso.weekend_crypto` | week-end crypto → lundi des futures d'indices (Mourey et al. 2025) |
| `resultats_dax_cloture.txt` | `nexus.perso.dax_cloture` | DAX 17:00-17:30 : S19-B jouée à l'envers, hors échantillon 2014-2025 (CFD HistData) |
| `resultats_creneaux.txt` | `nexus.perso.creneaux` | lot « créneaux vides » : hypothèses pour les heures sans stratégie fiable (H1-H11 : une retenue, boombitch conforme ; fiables en plus : réplique YM, micro bitcoin MBT) |

Pistes à tester (proposées le 19/10/2026, papiers après 2020) : `pistes.md`. Catalogue des articles SSRN au moins
intraday (5 185, filtrable et annotable dans le navigateur) : `ssrn_intraday.html` (`ssrn_intraday.csv`).

Les sessions cloud ont leur propre suivi dans `../LISEZMOI.md` (§ 8 à 15 : fiche 16, S1, Gotobi, ORB, or la nuit,
fiche 15 LETF, groupe P1, catalogue SSRN).
