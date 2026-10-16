"""Groupe P1 : strategies intraday visant environ 5 % par an avec une perte maximale inferieure a environ 5 %.

Cadre commun (fixe le 2026-10-15, avant les tests) :
  - actifs : ES, NQ, YM, GC, CL, 6E, 6B, 6J, 6A (seuls ou en panier), barres 1 minute Databento ;
  - intraday : chaque position est ouverte et fermee dans la meme seance CME (18:00 -> 17:00 New York), jamais a
    travers la cloture de 17:00 ni le week-end (moteur de fenetres de nexus.or_nuit) ;
  - backtest vectorbt, exposition 1 (notionnel = capital) puis mise a l echelle k = 5 % / rendement annuel moyen ;
  - criteres d approbation (tous requis) :
      1. perte maximale a l echelle 5 %/an <= 5,5 % sur 2016-2026 ;
      2. Sharpe >= 1,2 sur chaque moitie, >= 5 sous-periodes positives sur 6, 2 dernieres annees positives ;
      3. Sharpe apres publication >= 1 (tout l historique si la publication est anterieure) ;
      4. couts x 2 : Sharpe >= 1 et perte maximale a l echelle <= 7,5 % ;
      5. p-valeur corrigee de Bonferroni sur tous les essais depuis le debut < 5 % ;
      6. (ajoute le 2026-10-15 a la demande, avant tout resultat P1 approuve) correlation des rendements journaliers
         avec chacune des autres strategies P1 approuvees <= 0,3 en valeur absolue (CORR_MAX).
Couts : commission par contrat et par execution + 1/2 tick, en fraction du notionnel au prix brut.

Criteres revises le 2026-10-16 a la demande (version 2, celle qui decide desormais) :
  - abandon de l objectif 5 %/an et de la perte maximale ;
  - Sharpe >= 1 AVANT la publication (si au moins 1 an de donnees avant) ET >= 1 APRES (au moins 1 an apres ; tout
    l historique si la publication est anterieure aux donnees) ;
  - intraday, actifs du depot, correlation <= 0,3 entre strategies P1 (inchanges) ;
  - couts x 2, Bonferroni, perte maximale, moities : calcules et affiches pour information.
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd

from . import data as D
from . import intraday as I
from . import or_nuit as ON

# multiplicateur, tick, dossier, rolls trimestriels (True) ou mensuels (False)
SPECS = {"ES": (50.0, 0.25, "indices", True), "NQ": (20.0, 0.25, "indices", True), "YM": (5.0, 1.0, "indices", True),
         "GC": (100.0, 0.1, "metaux", False), "CL": (1000.0, 0.01, "energie", False),
         "6E": (125_000.0, 0.00005, "forex", True), "6B": (62_500.0, 0.0001, "forex", True),
         "6J": (12_500_000.0, 0.0000005, "forex", True), "6A": (100_000.0, 0.00005, "forex", True)}
COMMISSION = 2.25
ACTIFS = list(SPECS)
CIBLE, DD_MAX, DD_MAX_COUTS, CORR_MAX = 0.05, 0.055, 0.075, 0.30
SHARPE_MIN = 1.0          # criteres version 2 : Sharpe avant et apres publication
# essais comptes avant le groupe P1 (criblages du 2026-10-15 jusqu a l etude prop firms de l or)
ESSAIS_AVANT_P1 = 186


def charger(dossier: str, sym: str) -> pd.DataFrame:
    """Barres 1 minute (UTC, datees a leur debut) -> open/high/low/close/volume ajustes des rolls, frais, glissement,
    prix brut, date de seance CME et minute depuis 18:00 New York."""
    mult, tick, sous, trimestriel = SPECS[sym]
    df = D.load_folder(dossier, daily=False, only=[sym])[sym]
    if trimestriel:
        adj, _ = I.adjust_rolls_midnight_utc(df, "UTC")
    else:
        adj, _ = ON.ajuster_rolls(df)
    idx = pd.DatetimeIndex(df.index)
    idx = idx.tz_convert("UTC").tz_localize(None) if idx.tz is not None else idx
    px = df["close"].to_numpy(float)
    date, minute = ON.seances(idx)
    m = pd.DataFrame({c: adj[c].to_numpy(float) for c in ("open", "high", "low", "close")}, index=idx)
    m["volume"] = df["volume"].to_numpy(float)
    m["frais"] = COMMISSION / (px * mult)
    m["glissement"] = 0.5 * tick / px
    m["brut"] = px
    m["seance"] = date
    m["minute"] = minute
    m.attrs.update(symbole=sym, multiplicateur=mult)
    return m


def prix_a(m: pd.DataFrame, heure: str, tol: int = 10, col: str = "open") -> pd.Series:
    """Prix (ouverture de la premiere barre a l heure de New York, au plus `tol` minutes de retard) par seance CME."""
    cible = ON._minute(heure)
    mn = m["minute"].to_numpy()
    sel = (mn >= cible) & (mn <= cible + tol)
    s = pd.Series(m[col].to_numpy()[sel], index=pd.DatetimeIndex(m["seance"].to_numpy()[sel]))
    return s.groupby(level=0).first()


def seances(m: pd.DataFrame) -> pd.DatetimeIndex:
    return pd.DatetimeIndex(pd.unique(m["seance"].to_numpy()))


def rendements(m: pd.DataFrame, cal: pd.DatetimeIndex, **kw) -> pd.Series:
    """Rendements journaliers (calendrier NYSE) du portefeuille vectorbt des fenetres, exposition 1, mode compact."""
    pf = ON.portefeuille(m, compact=True, **kw)
    return ON.valeur_journaliere(pf, cal).pct_change().fillna(0.0)


def panier(rets: dict, fenetre: int = 252) -> pd.Series:
    """Panier a risque egal : poids inverses de la volatilite passee de chaque composante (252 seances, sans
    anticipation) ; poids egaux tant que l historique manque."""
    R = pd.DataFrame(rets).fillna(0.0)
    vol = R.rolling(fenetre, min_periods=60).std().shift(1)
    w = (1 / vol.replace(0, np.nan))
    w = w.div(w.sum(axis=1), axis=0).fillna(1.0 / R.shape[1])
    return (R * w).sum(axis=1)


def _acc(r: pd.Series):
    return r.vbt.returns(freq="1D", year_freq="252 days")


def evaluer(r: pd.Series, publication: str | None, essais: int, r_couts2: pd.Series | None = None) -> dict:
    """Mesures et verdict d une strategie P1 (rendements journaliers a exposition 1)."""
    from scipy import stats as SS
    r = r.fillna(0.0)
    moy = float(r.mean() * 252)
    out = dict(rend_an_x1=moy, sharpe=float(_acc(r).sharpe_ratio()))
    k = CIBLE / moy if moy > 0 else np.nan
    out["levier"] = k
    out["dd_5pct"] = float(-_acc(r * k).max_drawdown()) if moy > 0 else np.nan
    h = len(r) // 2
    out["sharpe_m1"], out["sharpe_m2"] = float(_acc(r.iloc[:h]).sharpe_ratio()), float(_acc(r.iloc[h:]).sharpe_ratio())
    blocs = [float(_acc(r.iloc[b]).sharpe_ratio()) for b in np.array_split(np.arange(len(r)), 6)]
    out["blocs_pos"] = int(np.sum(np.array(blocs) > 0))
    out["sharpe_2ans"] = float(_acc(r[r.index >= r.index[-1] - pd.DateOffset(years=2)]).sharpe_ratio())
    apres = r[r.index >= pd.Timestamp(publication)] if publication else r
    avant = r[r.index < pd.Timestamp(publication)] if publication else r.iloc[:0]
    out["sharpe_apres_pub"] = float(_acc(apres).sharpe_ratio()) if len(apres) >= 252 else np.nan
    out["sharpe_avant_pub"] = float(_acc(avant).sharpe_ratio()) if len(avant) >= 252 else np.nan
    p = SS.ttest_1samp(r, 0.0, alternative="greater").pvalue
    out["p_bonferroni"] = float(min(1.0, p * essais))
    if r_couts2 is not None:
        r2 = r_couts2.fillna(0.0)
        m2 = float(r2.mean() * 252)
        out["sharpe_couts2"] = float(_acc(r2).sharpe_ratio())
        out["dd_5pct_couts2"] = float(-_acc(r2 * (CIBLE / m2)).max_drawdown()) if m2 > 0 else np.nan
    ok = [moy > 0 and out["dd_5pct"] <= DD_MAX,
          min(out["sharpe_m1"], out["sharpe_m2"]) >= 1.2 and out["blocs_pos"] >= 5 and out["sharpe_2ans"] > 0,
          (out["sharpe_apres_pub"] if np.isfinite(out["sharpe_apres_pub"]) else out["sharpe"]) >= 1.0,
          r_couts2 is None or (out["sharpe_couts2"] >= 1.0 and np.isfinite(out["dd_5pct_couts2"]) and out["dd_5pct_couts2"] <= DD_MAX_COUTS),
          out["p_bonferroni"] < 0.05]
    out["criteres_v1"] = "".join("V" if x else "x" for x in ok)
    av, ap = out["sharpe_avant_pub"], out["sharpe_apres_pub"]
    c_av = "-" if not np.isfinite(av) else ("V" if av >= SHARPE_MIN else "x")
    c_ap = "V" if (np.isfinite(ap) and ap >= SHARPE_MIN) else "x"
    out["criteres"] = c_av + c_ap
    out["approuvee"] = c_av != "x" and c_ap == "V"
    return out


def rendements_fixes(m: pd.DataFrame, cal: pd.DatetimeIndex, capital: float, **kw) -> pd.Series:
    """Rendements journaliers = P&L du jour / capital de depart (taille en contrats, sans reinvestissement)."""
    pf = ON.portefeuille(m, compact=True, capital=capital, **kw)
    return (ON.valeur_journaliere(pf, cal).diff() / capital).fillna(0.0)


def _heure(minute: int) -> str:
    h, mi = divmod((ON.OUVERTURE + int(minute)) % 1440, 60)
    return f"{h:02d}:{mi:02d}"


def noise_area(m: pd.DataFrame, debut: str, fin: str, lookback: int = 14, bande: float = 1.0, pas: int = 30,
               vol_cible: float = 0.02, vol_jours: int = 14, levier_max: float = 4.0, capital: float = 1_000_000.0):
    """Zone de bruit (Zarattini, Aziz & Barbon 2024, regles du code des auteurs) sur la seance [debut, fin[ (New York) :
    sigma(t) = moyenne sur `lookback` seances precedentes de |Close(t)/Open - 1| ; bandes max/min(Open, cloture
    precedente) x (1 +/- bande x sigma) ; a chaque controle (toutes les `pas` minutes) : achat si Close > bande haute
    et > VWAP, vente si Close < bande basse et < VWAP, sinon a plat ; execution a l ouverture de la minute suivante ;
    sortie a `fin`. Taille fixee par seance : capital x min(vol cible / vol `vol_jours` j, levier max) / Open.
    -> (fenetres pour or_nuit.portefeuille, contrats par barre)."""
    a, b = ON._minute(debut), ON._minute(fin)
    mn = m["minute"].to_numpy()
    sel = (mn >= a) & (mn < b)
    sub = m.loc[sel]
    jours, code = np.unique(sub["seance"].to_numpy(), return_inverse=True)
    S = b - a
    slot = sub["minute"].to_numpy() - a
    mat = {}
    for k in ("open", "high", "low", "close", "volume"):
        x = np.full((len(jours), S), np.nan)
        x[code, slot] = sub[k].to_numpy(float)
        mat[k] = x
    O = mat["open"][:, 0]
    C = mat["close"]
    present = np.isfinite(C)
    last = np.where(present.any(axis=1), S - 1 - present[:, ::-1].argmax(axis=1), -1)
    clot = np.where(last >= 0, C[np.arange(len(jours)), np.maximum(last, 0)], np.nan)
    pc = pd.Series(clot).shift(1).to_numpy()
    with np.errstate(invalid="ignore", divide="ignore"):
        move = np.abs(C / O[:, None] - 1.0)
    sigma = I.slot_mean_prev(move, int(lookback))
    hi = np.maximum(O, pc)[:, None] * (1 + bande * sigma)
    lo = np.minimum(O, pc)[:, None] * (1 - bande * sigma)
    tp = (mat["high"] + mat["low"] + C) / 3.0
    v = np.nan_to_num(mat["volume"])
    with np.errstate(invalid="ignore", divide="ignore"):
        vw = np.where(np.cumsum(v, axis=1) > 0, np.cumsum(np.nan_to_num(tp) * v, axis=1) / np.cumsum(v, axis=1), np.nan)
    ret_j = pd.Series(clot / pc - 1.0)
    vol = ret_j.rolling(int(vol_jours)).std().shift(1).to_numpy()
    with np.errstate(invalid="ignore", divide="ignore"):
        lev = np.minimum(vol_cible / vol, levier_max)
    ok_j = np.isfinite(lev) & (lev > 0) & np.isfinite(O) & np.isfinite(pc)
    jours = pd.DatetimeIndex(jours)
    fen = []
    for k in range(pas - 1, S - 1, pas):                    # barre de controle k (se termine a a + k + 1)
        c, h_, l_, w = C[:, k], hi[:, k], lo[:, k], vw[:, k]
        haut = ok_j & (c > h_) & (c > w)
        bas = ok_j & (c < l_) & (c < w)
        t0, t1 = a + k + 1, min(a + k + 1 + pas, b)
        fen.append((_heure(t0), _heure(t1) if t1 < 1380 else "17:00", 1, jours[haut]))
        fen.append((_heure(t0), _heure(t1) if t1 < 1380 else "17:00", -1, jours[bas]))
    mult = float(m.attrs["multiplicateur"])
    taille = pd.Series(np.where(ok_j, capital * lev / (mult * O), 0.0), index=jours)
    contrats = taille.reindex(pd.DatetimeIndex(m["seance"].to_numpy())).fillna(0.0).to_numpy()
    return fen, contrats
