"""Modele economique « arbitrage de prop firm » (SEUL BUT depuis le 2026-10-25, CLAUDE.md) : cycle de vie complet
d un compte de prop firm (evaluation -> compte finance -> payouts -> compte perdu -> nouvelle evaluation) sur une
annee de seances, avec les regles relevees de chaque firme, pour S1 (MNQ) + Gotobi (6J) en contrats entiers.

Ce que l on mesure, par compte et par annee : gain net = payouts recus (part du trader) - frais (evaluations,
remises a zero, activation). C est la grandeur que l equipe Kairos optimise (registre n° 344-349).

Donnees (rien n est recalcule a la main) :
  - S1 : regles figees de S1_NoiseAreaNQ.backtest (les trades) rejouees dans vectorbt (Portfolio.from_orders) sur
    le prix en dollars d UN contrat MNQ ; taille du jour = regle de S1 (2 % de vol visee, levier <= 4) pour un
    capital fictif de 10 000 $ par « unite », arrondie au micro ;
  - Gotobi : signaux figes de nexus.gotobi rejoues de meme sur UN contrat 6J ;
  - prix en dollars d un contrat : variations des prix ajustes des rolls appliquees au prix brut de la minute
    precedente (exact a l interieur d une seance ; la position Gotobi qui traverse minuit UTC un jour de roll garde
    le rendement ajuste) ;
  - couts (critere 8) : 1 tick + commission par cote (0,60 $ le micro, 2,50 $ le contrat de base) ; stress 2 ticks ;
  - seance CME : une barre apres 17:00 New York compte pour la seance du lendemain (Gotobi, 08:00-11:00 Tokyo, tombe
    le soir a New York : il precede S1 dans la meme seance ; les deux ne se chevauchent jamais, ce qui rend exacts le
    plus bas et le plus haut intraday de la combinaison, calcules a partir de ceux de chaque strategie).

Regles des firmes : relevees le 2026-10-25 sur des sites tiers (les pages officielles n etaient pas lisibles),
sources dans REGLES[...]["source"] ; prix catalogue sans code promo. A reverifier avant tout achat.

Choix de la mise : la taille (S1 en unites, Gotobi en contrats, separement en evaluation et en compte finance) est
choisie sur les departs 2016-2020 seulement, puis jugee sur 2021-2026 (hors echantillon). IC : bootstrap par blocs
de 21 seances (1 000 annees synthetiques).

    python -m nexus.prop_comptes --cotations ../Cotations
"""
from __future__ import annotations

import argparse
import math
import os
import sys
import time

import numpy as np
import pandas as pd

try:
    from numba import njit
except ImportError:  # pragma: no cover
    def njit(*a, **k):
        return (lambda f: f) if not a or not callable(a[0]) else a[0]

NY = "America/New_York"
COUPURE = pd.Timestamp("2021-01-01")
HORIZON = 252                    # une annee de seances par compte
PAS_DEPART = 21                  # un depart par mois
BLOC, B_BOOT, SEED = 21, 1000, 11

# contrats : valeur du point (ou multiplicateur), tick, commission par cote, equivalent en micros (plafond des firmes)
CONTRATS = {
    "NQ": dict(point=20.0, tick=0.25, commission=2.50, micros=10),
    "MNQ": dict(point=2.0, tick=0.25, commission=0.60, micros=1),
    "6J": dict(point=12_500_000.0, tick=0.0000005, commission=2.50, micros=10),
    "MJY": dict(point=1_250_000.0, tick=0.000001, commission=0.60, micros=1),
}

# ----------------------------------------------------------------------------- regles des firmes (comptes 50K)
# objectif, perte max (MLL) suiveuse en fin de journee qui s arrete a +verrou ; coherence : meilleur jour <= part du
# gain au moment de reussir ; perte_jour : la firme coupe la journee (pas d echec) ; plafonds en equivalent micros.
REGLES = {
    "lucid_flex_50k": dict(
        nom="Lucid Trading, LucidFlex 50K", objectif=3000, perte_max=2000, intraday=0, verrou_eval=100, perte_jour=0,
        coherence=0.5, jours_min=2, prix_eval=146, mensuel=0, prix_reset=146, activation=0,
        verrou_finance=100, jours_payout=5, gain_jour_payout=150, part_payout=0.5, plafond_payout=2000,
        min_payout=500, partage=0.9, plafond_eval=40, plafond_finance=20, intraday_finance=0, perte_jour_finance=0,
        source="quantvps.com/blog/lucid-trading-prop-firm-payout-rules ; mytradingbuddy.ai/blog/lucid-trading-flex-account-rules ; "
               "proptradingvibes.com/blog/lucid-trading-50k-account-rules (automatisation permise selon crosstrade.io/prop-firms/lucid-trading)"),
    "tradeify_select_flex_50k": dict(
        nom="Tradeify, Select 50K (financement Flex)", objectif=3000, perte_max=2000, intraday=0, verrou_eval=100,
        perte_jour=0, coherence=0.4, jours_min=3, prix_eval=165, mensuel=0, prix_reset=165, activation=0,
        verrou_finance=100, jours_payout=5, gain_jour_payout=150, part_payout=0.5, plafond_payout=2500,
        min_payout=250, partage=0.9, plafond_eval=40, plafond_finance=40, intraday_finance=0, perte_jour_finance=0,
        source="mytradingbuddy.ai/blog/tradeify-payout-rules ; rbtrading.site/prop-firms/tradeify-rules ; "
               "tradecovex.com/guides/tradeify-rules-2026 ; spicyfutures.com/tradeify-select-review-flex-vs-daily"),
    "topstep_50k": dict(
        nom="Topstep, Trading Combine 50K + XFA, paiement Standard (5 jours >= 150 $)", objectif=3000, perte_max=2000,
        intraday=0, verrou_eval=0, perte_jour=0, coherence=0.55, jours_min=2, prix_eval=49, mensuel=1, prix_reset=49,
        activation=149, verrou_finance=0, jours_payout=5, gain_jour_payout=150, part_payout=0.5, plafond_payout=2000,
        min_payout=125, partage=0.9, plafond_eval=50, plafond_finance=20, intraday_finance=0, perte_jour_finance=0,
        verrou_apres_payout=1, mode_payout=0, coherence_payout=0, palier1=1500, plafond_palier1=30, palier2=2000,
        plafond_palier2=50,
        source="help.topstep.com, lu le 2026-10-25 : articles 8284197 (Combine : coherence 55 %, 5 minis, automatisation "
               "permise sous conditions), 8284204 (MLL 2 000 $ fin de journee, verrou au depart, mis a 0 au 1er payout), "
               "8284233 (payouts), 10490293 (perte journaliere optionnelle), 14289835 (prix) ; echelle 2 / 3 / 5 lots : "
               "futureshive.com/blog/topstep-scaling-plan-explained (tableau officiel non lisible)"),
    "topstep_50k_consistency": dict(
        nom="Topstep, Trading Combine 50K + XFA, paiement Consistency (3 jours, meilleur jour <= 40 %)", objectif=3000,
        perte_max=2000, intraday=0, verrou_eval=0, perte_jour=0, coherence=0.55, jours_min=2, prix_eval=49, mensuel=1,
        prix_reset=49, activation=149, verrou_finance=0, jours_payout=3, gain_jour_payout=0, part_payout=0.5,
        plafond_payout=3000, min_payout=125, partage=0.9, plafond_eval=50, plafond_finance=20, intraday_finance=0,
        perte_jour_finance=0, verrou_apres_payout=1, mode_payout=1, coherence_payout=0.4, palier1=1500,
        plafond_palier1=30, palier2=2000, plafond_palier2=50,
        source="help.topstep.com, lu le 2026-10-25 : article 8284233 (chemin Consistency) ; le reste comme Standard"),
}
# option officielle de Topstep : perte journaliere fixee a l achat (1 000 $ en 50K, Combine et XFA ; la firme coupe la
# seance, ce n est pas un echec) ; offre a duree limitee (depuis le 2 juin) : plafonds de payout doubles
REGLES["topstep_50k_dll"] = {**REGLES["topstep_50k"], "perte_jour": 1000, "perte_jour_finance": 1000,
                             "nom": "Topstep 50K, paiement Standard, perte journaliere 1 000 $ choisie a l achat"}
REGLES["topstep_50k_dll_offre"] = {**REGLES["topstep_50k_dll"], "plafond_payout": 4000,
                                   "nom": "Topstep 50K, Standard + perte journaliere 1 000 $, offre limitee (plafond 4 000 $)"}
# comptes 100K et 150K (ajoutes le 2026-10-25 au soir) : help.topstep.com, articles 8284204 (MLL 3 000 / 4 500 $),
# 14289835 (99 / 199 $ par mois, activation 149 $), 8284233 (payout Standard 3 000 / 5 000 $, offre 6 000 / 10 000 $),
# 10490293 (perte journaliere optionnelle 2 000 / 3 000 $), 8284197 (10 / 15 minis en Combine) ; objectifs 6 000 /
# 9 000 $ (blog et article coherence de Topstep) ; echelle XFA 3/4/5/10 et 3/4/5/10/15 minis (futureshive.com, le
# tableau officiel est une image). Grille de reference pour ces tailles, fixee AVANT le calcul : la grille large
# (la grille initiale plafonne a 42 micros, sous les paliers de ces comptes).
for _cle, _t, _nom in (("topstep_100k_dll", dict(objectif=6000, perte_max=3000, perte_jour=2000, perte_jour_finance=2000,
                                                  prix_eval=99, prix_reset=99, plafond_payout=3000, plafond_eval=100,
                                                  plafond_finance=30, palier1=1500, plafond_palier1=40, palier2=2000,
                                                  plafond_palier2=50, palier3=3000, plafond_palier3=100),
                        "Topstep 100K, paiement Standard, perte journaliere 2 000 $ choisie a l achat"),
                       ("topstep_150k_dll", dict(objectif=9000, perte_max=4500, perte_jour=3000, perte_jour_finance=3000,
                                                  prix_eval=199, prix_reset=199, plafond_payout=5000, plafond_eval=150,
                                                  plafond_finance=30, palier1=1500, plafond_palier1=40, palier2=2000,
                                                  plafond_palier2=50, palier3=3000, plafond_palier3=100, palier4=4500,
                                                  plafond_palier4=150),
                        "Topstep 150K, paiement Standard, perte journaliere 3 000 $ choisie a l achat")):
    REGLES[_cle] = {**REGLES["topstep_50k_dll"], **_t, "nom": _nom,
                    "source": "help.topstep.com (articles 8284204, 14289835, 8284233, 10490293, 8284197), lus le 2026-10-25 ; "
                              "echelle XFA : futureshive.com/blog/topstep-scaling-plan-explained"}
    REGLES[_cle + "_offre"] = {**REGLES[_cle], "plafond_payout": 2 * _t["plafond_payout"],
                               "nom": _nom.replace("choisie a l achat", "+ offre limitee (plafond double)")}
# valeurs par defaut des regles ajoutees le 2026-10-25 (Lucid et Tradeify : plancher verrouille au 1er payout selon
# spicyfutures.com ; pas d echelle de contrats connue)
DEFAUTS = dict(verrou_apres_payout=1, mode_payout=0, coherence_payout=0, palier1=1e12, plafond_palier1=0,
               palier2=1e12, plafond_palier2=0, palier3=1e12, plafond_palier3=0, palier4=1e12, plafond_palier4=0)
CHAMPS = ["objectif", "perte_max", "intraday", "verrou_eval", "perte_jour", "coherence", "jours_min", "prix_eval",
          "mensuel", "prix_reset", "activation", "verrou_finance", "jours_payout", "gain_jour_payout", "part_payout",
          "plafond_payout", "min_payout", "partage", "plafond_eval", "plafond_finance", "intraday_finance",
          "perte_jour_finance", "verrou_apres_payout", "mode_payout", "coherence_payout", "palier1", "plafond_palier1",
          "palier2", "plafond_palier2", "palier3", "plafond_palier3", "palier4", "plafond_palier4"]
NON_SIMULEES = {
    "Apex Trader Funding": "automatisation interdite ou douteuse selon les sources 2026 (il.ly, quantcrawler) : a lire sur leurs CGU",
    "Take Profit Trader": "PRO : perte max suiveuse intraday et bots interdits selon plusieurs guides 2026 (proptradingvibes, pickmytrade)",
}


def vecteur_regles(r: dict) -> np.ndarray:
    r = {**DEFAUTS, **r}
    return np.array([float(r[c]) for c in CHAMPS])


# =============================================================================
#  Cycle de vie d un compte (une annee), seance par seance
# =============================================================================
@njit(cache=True)
def _jour(L, H, C, W, eq, tailles, plafond, d):
    """Plus bas, plus haut et cloture du jour d de la combinaison (strategies dans l ordre chronologique de la seance,
    jamais simultanees) ; contrats = arrondi(taille x W), plafond commun en equivalent micros."""
    cum, lo, hi, utilise = 0.0, 0.0, 0.0, 0.0
    for k in range(L.shape[0]):
        n = math.floor(tailles[k] * W[k, d] + 0.5)
        reste = math.floor((plafond - utilise) / eq[k])
        if n > reste:
            n = reste
        if n <= 0:
            continue
        utilise += n * eq[k]
        lo = min(lo, cum + n * L[k, d])
        hi = max(hi, cum + n * H[k, d])
        cum += n * C[k, d]
    return lo, hi, cum


@njit(cache=True)
def cycle(L, H, C, W, eq, idx, t_eval, t_fin, R):
    """Une annee de compte sur les seances idx. R : vecteur_regles. -> [net, frais, payouts_recus, n_payouts,
    evaluations_achetees, evaluations_reussies, comptes_finances_perdus, seance_du_1er_payout (-1 : aucun)]."""
    return cycle_flux(L, H, C, W, eq, idx, t_eval, t_fin, R, np.zeros(0))


@njit(cache=True)
def cycle_flux(L, H, C, W, eq, idx, t_eval, t_fin, R, flux):
    """cycle, et si flux a la longueur de idx : solde de tresorerie cumule (payouts recus - frais payes) a la fin de
    chaque seance (utilise par nexus.prop_book pour le capital de depart d un book de comptes)."""
    trace = flux.shape[0] == len(idx)
    obj, mll, intra_e, verrou_e, dll_e, coh, jmin = R[0], R[1], R[2], R[3], R[4], R[5], R[6]
    prix_eval, mensuel, prix_reset, activation = R[7], R[8], R[9], R[10]
    verrou_f, jpay, gjour, part, cap_pay, minp, partage = R[11], R[12], R[13], R[14], R[15], R[16], R[17]
    cap_e, cap_f, intra_f, dll_f = R[18], R[19], R[20], R[21]
    verrou_pay, mode_pay, coh_pay, pal1, cap1, pal2, cap2 = R[22], R[23], R[24], R[25], R[26], R[27], R[28]
    pal3, cap3, pal4, cap4 = R[29], R[30], R[31], R[32]
    frais, recus, npay, nevals, nok, nperdus, premier = prix_eval, 0.0, 0, 1, 0, 0, -1
    phase = 0                                       # 0 : evaluation, 1 : compte finance
    solde, seuil, pic, meilleur, jours, jours_mois, gagnants = 0.0, -mll, 0.0, 0.0, 0, 0, 0
    base, meilleur_pay, jours_pay = 0.0, 0.0, 0         # depuis le dernier payout : solde de reference, meilleur jour, jours
    for j in range(len(idx)):
        if trace and j > 0:
            flux[j - 1] = recus - frais
        d = idx[j]
        if phase == 0:
            lo, hi, cl = _jour(L, H, C, W, eq, t_eval, cap_e, d)
            intra, dll, verrou = intra_e, dll_e, verrou_e
        else:
            cap = cap4 if solde >= pal4 else (cap3 if solde >= pal3 else (cap2 if solde >= pal2 else
                                                                            (cap1 if solde >= pal1 else cap_f)))  # echelle (solde de la veille)
            lo, hi, cl = _jour(L, H, C, W, eq, t_fin, cap, d)
            intra, dll, verrou = intra_f, dll_f, verrou_f
        if dll > 0 and lo <= -dll:                  # la firme coupe la journee a la perte journaliere
            lo, cl = -dll, -dll
        if intra > 0:                               # approximation prudente : le plus haut compte avant le plus bas
            pic = max(pic, solde + hi)
            seuil = max(seuil, min(pic - mll, verrou))
        perdu = solde + lo <= seuil
        if not perdu:
            solde += cl
            jours += 1
            if intra == 0:
                pic = max(pic, solde)
                seuil = max(seuil, min(pic - mll, verrou))
        if phase == 0:
            jours_mois += 1
            if mensuel > 0 and jours_mois >= 21 and not perdu:
                frais += prix_eval
                jours_mois = 0
            if perdu:
                frais += prix_reset
                nevals += 1
                solde, seuil, pic, meilleur, jours = 0.0, -mll, 0.0, 0.0, 0
                continue
            meilleur = max(meilleur, cl)
            if solde >= obj and jours >= jmin and (coh <= 0 or meilleur <= coh * solde):
                nok += 1
                frais += activation
                phase = 1
                solde, seuil, pic, jours, gagnants = 0.0, -mll, 0.0, 0, 0
                base, meilleur_pay, jours_pay = 0.0, 0.0, 0
        else:
            if perdu:
                nperdus += 1
                frais += prix_eval
                nevals += 1
                phase = 0
                solde, seuil, pic, meilleur, jours, jours_mois = 0.0, -mll, 0.0, 0.0, 0, 0
                continue
            if cl >= gjour and cl > 0:
                gagnants += 1
            jours_pay += 1
            meilleur_pay = max(meilleur_pay, cl)
            depuis = solde - base
            if mode_pay == 0:
                eligible = gagnants >= jpay
            else:                                   # chemin « Consistency » : jours, meilleur jour <= part du gain
                eligible = jours_pay >= jpay and meilleur_pay <= coh_pay * depuis
            if eligible and solde > 0 and depuis > 0:
                dem = min(cap_pay, part * solde)
                if dem >= minp:
                    solde -= dem
                    recus += partage * dem
                    npay += 1
                    gagnants, jours_pay, meilleur_pay, base = 0, 0, 0.0, solde
                    if verrou_pay > 0:
                        seuil = max(seuil, verrou_f)
                    if premier < 0:
                        premier = j + 1
    if trace and len(idx) > 0:
        flux[len(idx) - 1] = recus - frais
    out = np.empty(8)
    out[0], out[1], out[2], out[3] = recus - frais, frais, recus, npay
    out[4], out[5], out[6], out[7] = nevals, nok, nperdus, premier
    return out


@njit(cache=True)
def departs(L, H, C, W, eq, debuts, horizon, t_eval, t_fin, R):
    """Une annee de compte depuis chaque seance de debuts -> tableau (departs x 8)."""
    out = np.empty((len(debuts), 8))
    for i in range(len(debuts)):
        idx = np.arange(debuts[i], debuts[i] + horizon)
        out[i] = cycle(L, H, C, W, eq, idx, t_eval, t_fin, R)
    return out


@njit(cache=True)
def grille(L, H, C, W, eq, debuts, horizon, TE, TF, R):
    """Gain net moyen par compte-annee pour chaque couple (taille d evaluation TE[a], taille financee TF[b])."""
    g = np.empty((TE.shape[0], TF.shape[0]))
    for a in range(TE.shape[0]):
        for b in range(TF.shape[0]):
            g[a, b] = departs(L, H, C, W, eq, debuts, horizon, TE[a], TF[b], R)[:, 0].mean()
    return g


def sans_avantage(L, H, C):
    """Temoin « sans avantage » (repris du simulateur du Kairos Terminal : meme compte, sans edge) : gain moyen des
    seances actives retire a chaque strategie ; plus bas et plus haut decales d autant (bornes a 0)."""
    L2, H2, C2 = L.copy(), H.copy(), C.copy()
    for k in range(C.shape[0]):
        actif = C[k] != 0
        mu = C[k, actif].mean() if actif.any() else 0.0
        C2[k, actif] = C[k, actif] - mu
        L2[k, actif] = np.minimum(np.minimum(L[k, actif] - mu, C2[k, actif]), 0.0)
        H2[k, actif] = np.maximum(np.maximum(H[k, actif] - mu, C2[k, actif]), 0.0)
    return L2, H2, C2


def bootstrap(L, H, C, W, eq, t_eval, t_fin, R, lignes: np.ndarray, b: int = B_BOOT, seed: int = SEED,
              horizon: int = HORIZON, bloc: int = BLOC) -> np.ndarray:
    """b annees synthetiques : blocs de `bloc` seances consecutives tires parmi `lignes` (bootstrap circulaire,
    toutes les strategies du meme jour gardees ensemble) -> tableau (b x 8)."""
    rng = np.random.default_rng(seed)
    n = len(lignes)
    out = np.empty((b, 8))
    for i in range(b):
        parts = [lignes[(s + np.arange(bloc)) % n] for s in rng.integers(0, n, size=horizon // bloc + 1)]
        idx = np.concatenate(parts)[:horizon].astype(np.int64)
        out[i] = cycle(L, H, C, W, eq, idx, t_eval, t_fin, R)
    return out


# =============================================================================
#  P&L d un contrat, minute par minute, dans vectorbt
# =============================================================================
def prix_dollar(brut_close: np.ndarray, adj_open: np.ndarray, adj_close: np.ndarray, point: float):
    """Prix en dollars d un contrat : rendements ajustes appliques au prix brut de la minute precedente."""
    prec_b = np.r_[brut_close[0], brut_close[:-1]]
    prec_a = np.r_[adj_close[0], adj_close[:-1]]
    d_close = point * prec_b * (adj_close / prec_a - 1.0)
    v_close = point * brut_close[0] + np.cumsum(d_close)
    v_open = np.r_[v_close[0], v_close[:-1]] + point * prec_b * (adj_open / prec_a - 1.0)
    return v_open, v_close


def rejouer(index: pd.DatetimeIndex, v_open, v_close, cible: np.ndarray, prix_ordre: np.ndarray, spec: dict, ticks: float):
    """vbt.Portfolio.from_orders sur 1 contrat : cible (NaN : pas d ordre), prix d execution en dollars, couts par
    contrat et par cote (commission + ticks) en frais proportionnels."""
    import vectorbt as vbt
    cout = spec["commission"] + ticks * spec["tick"] * spec["point"]
    px = np.where(np.isfinite(prix_ordre), prix_ordre, v_close)
    return vbt.Portfolio.from_orders(pd.Series(v_close, index=index), size=pd.Series(cible, index=index),
                                     size_type="targetamount", price=pd.Series(px, index=index),
                                     fees=pd.Series(cout / np.abs(px), index=index), init_cash=1e9, direction="both",
                                     freq="1min")


def par_seance(pf, index_utc: pd.DatetimeIndex) -> pd.DataFrame:
    """Plus bas, plus haut et cloture du P&L de chaque seance CME (17:00 New York), par rapport a la veille."""
    v = pf.value().to_numpy(float)
    ny = index_utc.tz_localize("UTC").tz_convert(NY).tz_localize(None)
    seance = (ny + pd.Timedelta(hours=7)).normalize()               # 17:00 New York -> seance du lendemain
    s = pd.Series(v, index=seance)
    g = s.groupby(level=0)
    clot = g.last()
    ref = clot.shift(1).fillna(v[0])
    out = pd.DataFrame({"bas": np.minimum(g.min() - ref, 0.0), "haut": np.maximum(g.max() - ref, 0.0), "clot": clot - ref})
    return out[(out != 0).any(axis=1)]


def _bar(index: pd.DatetimeIndex, t: pd.DatetimeIndex) -> tuple[np.ndarray, np.ndarray]:
    """Barre qui commence a t ; si elle manque, la derniere barre avant t (execution a sa cloture). -> (pos, exacte)."""
    pos = index.searchsorted(t, side="left")
    pos = np.minimum(pos, len(index) - 1)
    exacte = index[pos] == t
    pos = np.where(exacte, pos, np.maximum(pos - 1, 0))
    return pos, np.asarray(exacte)


def s1_un_contrat(df_brut: pd.DataFrame, df_adj: pd.DataFrame, eq: pd.DataFrame, trades: pd.DataFrame, contrat: str,
                  ticks: float):
    """Trades de S1 (backtest fige) rejoues sur 1 contrat -> (seances, poids par unite, pf vectorbt, controle)."""
    spec = CONTRATS[contrat]
    idx = pd.DatetimeIndex(df_adj.index).tz_localize(None)
    brut = df_brut.reindex(df_adj.index)["close"].to_numpy(float)
    brut_ouv = df_brut.reindex(df_adj.index)["open"].to_numpy(float)
    v_open, v_close = prix_dollar(brut, df_adj["open"].to_numpy(float), df_adj["close"].to_numpy(float), spec["point"])
    jours = pd.to_datetime(trades["jour"])

    def utc(h):
        t = jours + pd.to_timedelta(h + ":00")
        return pd.DatetimeIndex(t).tz_localize(NY).tz_convert("UTC").tz_localize(None)

    sens = np.where(trades["sens"] == "long", 1.0, -1.0)
    fin = trades["raison"].to_numpy() == "fin de seance"
    t_sortie = utc(trades["sortie"])
    t_sortie = t_sortie - pd.to_timedelta(np.where(fin, 1, 0), unit="min")   # cloture de la barre 15:59-16:00
    p_in, ex_in = _bar(idx, utc(trades["entree"]))
    p_out, ex_out = _bar(idx, t_sortie)
    cible = np.full(len(idx), np.nan)
    prix = np.full(len(idx), np.nan)
    prix[p_out] = np.where(ex_out & ~fin, v_open[p_out], v_close[p_out])
    cible[p_out] = 0.0
    prix[p_in] = np.where(ex_in, v_open[p_in], v_close[p_in])
    cible[p_in] = sens
    pf = rejouer(idx, v_open, v_close, cible, prix, spec, ticks)
    # controle : P&L brut vectorbt trade par trade = points de S1 (prix ajustes ramenes au brut) x valeur du point
    rec = pf.trades.records_readable
    brut_vbt = (rec["Avg Exit Price"] - rec["Avg Entry Price"]) * np.where(rec["Direction"] == "Long", 1, -1)
    ratio = brut[p_in] / df_adj["close"].to_numpy(float)[p_in]
    brut_s1 = sens * (trades["prix_sortie"] - trades["prix_entree"]).to_numpy() * ratio * spec["point"]
    n = min(len(brut_vbt), len(brut_s1))
    controle = dict(trades_s1=int(len(trades)), trades_vbt=int(len(rec)),
                    ecart_moyen=float(np.abs(brut_vbt.to_numpy()[:n] - brut_s1[:n]).mean()) if n else math.nan,
                    pnl_s1_par_contrat=float(brut_s1.sum()), pnl_vbt_brut=float(brut_vbt.sum()))
    seances = par_seance(pf, idx)
    # unite = capital de 10 000 $ avec la taille de S1 : contrats a 1 M$ (NQ, prix ajuste) / 100, ramenes au prix brut
    ouv = df_adj["open"].to_numpy(float)
    premier = pd.Series(np.arange(len(idx)), index=(idx.tz_localize("UTC").tz_convert(NY).tz_localize(None))) \
        .between_time("09:30", "09:30")
    r_adj_brut = pd.Series(ouv[premier.to_numpy()] / brut_ouv[premier.to_numpy()], index=premier.index.normalize())
    r_adj_brut = r_adj_brut[~r_adj_brut.index.duplicated()]
    w = eq["contrats"].astype(float) / 100.0 * r_adj_brut.reindex(eq.index).fillna(1.0) * (20.0 / spec["point"])
    return seances, w, pf, controle


def gotobi_un_contrat(m: pd.DataFrame, brut_close: np.ndarray, contrat: str, ticks: float):
    """Signaux figes du Gotobi rejoues sur 1 contrat -> (seances, pf vectorbt, controle)."""
    from . import gotobi as G
    spec = CONTRATS[contrat]
    (E, X, SE, SX), jours = G.signaux(m, dict(G.DEFAULTS))
    v_open, v_close = prix_dollar(brut_close, m["open"].to_numpy(float), m["close"].to_numpy(float), spec["point"])
    cible = np.full(len(m), np.nan)
    cible[(X | SX).to_numpy()] = 0.0
    cible[SE.to_numpy()] = -1.0
    cible[E.to_numpy()] = 1.0
    prix = np.where(np.isfinite(cible), v_open, np.nan)
    idx = pd.DatetimeIndex(m.index)
    pf = rejouer(idx, v_open, v_close, cible, prix, spec, ticks)
    ref = G.portefeuille(m)
    controle = dict(jours=int(len(jours)), trades_vbt=int(pf.trades.count()), trades_reference=int(ref.trades.count()),
                    correlation_rendements=float(np.corrcoef(pf.trades.records_readable["Return"],
                                                             ref.trades.records_readable["Return"])[0, 1])
                    if pf.trades.count() == ref.trades.count() else math.nan)
    return par_seance(pf, idx), pf, controle


# =============================================================================
#  Programme
# =============================================================================
def charger(cotations: str):
    """Barres minute brutes et ajustees de NQ et de 6J, trades de S1 (backtest fige, capital 1 M$)."""
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    import S1_NoiseAreaNQ as S1
    from . import data as D
    from . import gotobi as G
    df_brut, _ = S1.lire_minutes(os.path.join(cotations, "indices", "NQ_v0_1m.parquet"), NY, "debut")
    df_adj, _ = S1.ajuster_rolls(df_brut)
    eq, trades = S1.backtest(df_adj, 1_000_000.0)
    m, _ = G.charger_6j(cotations)
    j6 = D.load_folder(cotations, daily=False, only=["6J"])["6J"]
    brut6 = j6["close"].reindex(m.index).to_numpy(float)
    return df_brut, df_adj, eq, trades, m, brut6


def seances_cme(index_utc: pd.DatetimeIndex) -> pd.DatetimeIndex:
    """Toutes les seances CME (17:00 New York -> seance du lendemain, lundi a vendredi) ou le marche a cote, avec ou
    sans trade : une annee de compte = 252 de ces seances (calendrier reel, frais mensuels, jours de payout)."""
    ny = pd.DatetimeIndex(index_utc).tz_localize(None).tz_localize("UTC").tz_convert(NY).tz_localize(None)
    s = pd.DatetimeIndex((ny + pd.Timedelta(hours=7)).normalize().unique())
    return s[s.dayofweek < 5]


def tableaux(blocs: list[pd.DataFrame], poids: list[pd.Series], calendrier: pd.DatetimeIndex | None = None):
    """Seances (calendrier complet si fourni, sinon seances actives seulement) -> L, H, C, W (strategies x seances).
    Bug corrige le 2026-10-25 : sans calendrier, les seances sans aucun trade disparaissaient et « une annee » de 252
    seances durait en fait environ 1,6 annee civile."""
    jours = blocs[0].index if calendrier is None else calendrier
    for b in (blocs[1:] if calendrier is None else blocs):
        jours = jours.union(b.index)
    L = np.vstack([b["bas"].reindex(jours).fillna(0.0).to_numpy() for b in blocs])
    H = np.vstack([b["haut"].reindex(jours).fillna(0.0).to_numpy() for b in blocs])
    C = np.vstack([b["clot"].reindex(jours).fillna(0.0).to_numpy() for b in blocs])
    W = np.vstack([w.reindex(jours).ffill().fillna(0.0).to_numpy() for w in poids])
    return jours, L, H, C, W


def resume_cycles(x: np.ndarray) -> dict:
    net = x[:, 0]
    pay = x[:, 7]
    return dict(n=int(len(x)), net_moyen=float(net.mean()), net_median=float(np.median(net)),
                p_perte=float((net < 0).mean()), net_p5=float(np.quantile(net, 0.05)), net_p95=float(np.quantile(net, 0.95)),
                frais=float(x[:, 1].mean()), payouts=float(x[:, 2].mean()), n_payouts=float(x[:, 3].mean()),
                evaluations=float(x[:, 4].mean()), reussites=float(x[:, 5].mean()), finances_perdus=float(x[:, 6].mean()),
                jours_1er_payout=float(np.median(pay[pay > 0])) if (pay > 0).any() else math.nan,
                part_avec_payout=float((pay > 0).mean()))


def main():
    ap = argparse.ArgumentParser(description="Cycle de vie de comptes prop firm avec S1 (MNQ) + Gotobi (6J).")
    ap.add_argument("--cotations", default=os.path.join("..", "Cotations"))
    ap.add_argument("--sortie", default=os.path.join("recherche", "resultats_prop_comptes.txt"))
    ap.add_argument("--grille", choices=("initiale", "large"), default="initiale",
                    help="initiale : 0-3 x 6J, S1 0-6 unites (fixee avant le 1er calcul) ; large : 0-5 x 6J, S1 0-12")
    ap.add_argument("--cache", default="", help="pickle des donnees chargees (hors depot), pour relancer plus vite")
    a = ap.parse_args()
    t0 = time.time()
    lignes: list[str] = []

    def pr(s=""):
        print(s)
        lignes.append(s)

    if a.cache and os.path.exists(a.cache):
        df_brut, df_adj, eq, trades, m, brut6 = pd.read_pickle(a.cache)
    else:
        df_brut, df_adj, eq, trades, m, brut6 = charger(a.cotations)
        if a.cache:
            pd.to_pickle((df_brut, df_adj, eq, trades, m, brut6), a.cache)
    pr("Modele « arbitrage de prop firm » : S1 (MNQ) + Gotobi (6J), cycle de vie complet d un compte 50K sur 252 seances")
    pr(f"grille de tailles : {a.grille}")
    pr(f"(genere par python -m nexus.prop_comptes le {pd.Timestamp.now():%Y-%m-%d} ; regles relevees le 2026-10-25, prix catalogue)")
    pr()
    res = {}
    for ticks, nom_cout in ((1.0, "couts de reference (1 tick + commission par cote)"), (2.0, "stress (2 ticks par cote)")):
        s1, w1, pf1, c1 = s1_un_contrat(df_brut, df_adj, eq, trades, "MNQ", ticks)
        go, pfg, cg = gotobi_un_contrat(m, brut6, "6J", ticks)
        cal = seances_cme(df_adj.index)
        cal = cal[(cal >= min(go.index.min(), s1.index.min())) & (cal <= max(go.index.max(), s1.index.max()))]
        jours, L, H, C, W = tableaux([go, s1], [pd.Series(1.0, index=go.index), w1], cal)
        eqv = np.array([CONTRATS["6J"]["micros"], CONTRATS["MNQ"]["micros"]], float)
        if ticks == 1.0:
            pr("Controles (critere 9)")
            pr(f"  S1 rejoue dans vectorbt sur 1 MNQ : {c1['trades_vbt']} trades vectorbt pour {c1['trades_s1']} trades S1, "
               f"ecart moyen du P&L brut par trade {c1['ecart_moyen']:.4f} $ ; total {c1['pnl_vbt_brut']:,.0f} $ "
               f"(S1 : {c1['pnl_s1_par_contrat']:,.0f} $)")
            pr(f"  Gotobi rejoue sur 1 6J : {cg['trades_vbt']} trades vectorbt, {cg['trades_reference']} dans nexus.gotobi, "
               f"correlation des rendements par trade {cg['correlation_rendements']:.4f}")
            for nom_s, b in (("Gotobi 1 x 6J", go), ("S1 1 x MNQ", s1)):
                cl = b["clot"].reindex(jours).fillna(0.0)
                pr(f"  {nom_s} : {int((b['clot'] != 0).sum())} seances actives sur {len(jours)}, gain moyen {cl.mean():+.1f} $/seance, "
                   f"ecart-type {cl.std():.1f} $, Sharpe {cl.mean() / cl.std() * math.sqrt(252):.2f}")
            pr(f"  calendrier : {len(jours)} seances CME de {jours[0]:%Y-%m-%d} a {jours[-1]:%Y-%m-%d} (avec ou sans trade)")
            pr(f"  unite S1 = taille de S1 pour 10 000 $ : {w1.median():.2f} MNQ en mediane "
               f"({w1[w1.index >= '2025-01-01'].median():.2f} en 2025-2026)")
            pr()
        seances = np.arange(len(jours))
        dep = seances[: len(jours) - HORIZON: PAS_DEPART]
        fin_annee = np.array([jours[d + HORIZON - 1] for d in dep])
        dep_a = dep[fin_annee < COUPURE]
        dep_b = dep[np.array([jours[d] for d in dep]) >= COUPURE]
        g_max, u_max = (3, 6.0) if a.grille == "initiale" else (5, 12.0)
        TE = np.array([[g, u] for g in range(g_max + 1) for u in np.arange(0, u_max + 0.01, 0.5)], float)
        TF = TE.copy()
        pr(f"=== {nom_cout} ===")
        for cle, r in REGLES.items():
            R = vecteur_regles(r)
            ga = grille(L, H, C, W, eqv, dep_a, HORIZON, TE, TF, R)
            ia, ib = np.unravel_index(np.nanargmax(ga), ga.shape)
            te, tf = TE[ia], TF[ib]
            xa = departs(L, H, C, W, eqv, dep_a, HORIZON, te, tf, R)
            xb = departs(L, H, C, W, eqv, dep_b, HORIZON, te, tf, R)
            xt = departs(L, H, C, W, eqv, dep, HORIZON, te, tf, R)
            lb = np.flatnonzero(np.asarray(jours >= COUPURE))
            bo = bootstrap(L, H, C, W, eqv, te, tf, R, lb)
            L0, H0, C0 = sans_avantage(L, H, C)
            b0 = bootstrap(L0, H0, C0, W, eqv, te, tf, R, lb)
            res[(ticks, cle)] = dict(te=te, tf=tf, a=resume_cycles(xa), b=resume_cycles(xb), t=resume_cycles(xt), boot=resume_cycles(bo),
                                     sans_avantage=resume_cycles(b0))
            ra, rb, rbo = res[(ticks, cle)]["a"], res[(ticks, cle)]["b"], res[(ticks, cle)]["boot"]
            pr(f"{r['nom']}")
            pr(f"  taille choisie sur 2016-2020 : evaluation {int(te[0])} x 6J + S1 {te[1]:.1f} unite(s) ; "
               f"finance {int(tf[0])} x 6J + S1 {tf[1]:.1f} unite(s)")
            for nom_p, x in (("2016-2020 (choix)", ra), ("2021-2026 (hors echantillon)", rb), ("bootstrap 2021-2026", rbo),
                             ("temoin sans avantage (boot.)", res[(ticks, cle)]["sans_avantage"])):
                pr(f"  {nom_p:<29}: net {x['net_moyen']:+7,.0f} $/compte-an (mediane {x['net_median']:+,.0f}, "
                   f"5 % {x['net_p5']:+,.0f}, 95 % {x['net_p95']:+,.0f}), perte {x['p_perte']:.0%} ; frais {x['frais']:,.0f} $, "
                   f"payouts {x['payouts']:,.0f} $ ({x['n_payouts']:.1f}), evals {x['evaluations']:.1f}, "
                   f"reussies {x['reussites']:.1f}, finances perdus {x['finances_perdus']:.1f}, "
                   f"1er payout seance {x['jours_1er_payout']:.0f} ({x['part_avec_payout']:.0%} des annees)")
            pr()
    pr("Firmes non simulees")
    for k, v in NON_SIMULEES.items():
        pr(f"  {k} : {v}")
    pr()
    pr("Sources des regles")
    for r in REGLES.values():
        pr(f"  {r['nom']} : {r['source']}")
    pr(f"\n(duree {time.time() - t0:.0f} s)")
    os.makedirs(os.path.dirname(a.sortie), exist_ok=True)
    with open(a.sortie, "w", encoding="utf-8") as f:
        f.write("\n".join(lignes) + "\n")
    return res


if __name__ == "__main__":
    main()
