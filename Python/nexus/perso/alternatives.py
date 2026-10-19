"""Alternatives aux strategies prometteuses, sans sur-interpreter le passe.

    python -m nexus.perso.alternatives [--processus 4] [--sortie resultats_alternatives.txt]

Protocole, fixe AVANT les calculs (il est ecrit ici, dans le code, et n a pas ete change apres) :
  1. Reference naive. Chaque strategie est comparee a ce qu elle trade, simplement detenu (achat-conservation, ou 1/N
     pour un portefeuille). Regression des rendements quotidiens sur la reference : beta, alpha annualise et son t.
     Un « avantage » qui n est que du beta n est pas un avantage.
  2. Familles courtes (8 variantes au plus), chacune motivee par la litterature ou par la logique de la strategie ;
     pas de recherche fine de parametres.
  3. Decouverte = 2016-2020, validation = 2021-2026. Une variante n est RETENUE que si elle bat l originale sur les deux
     periodes (Sharpe) ET que son Sharpe deflate, toutes les variantes de la famille comptees, depasse 0,90.
  4. PBO (CSCV) de chaque famille ; marches de controle avec les memes regles, sans re-optimisation.
Les strategies sur actions (fiches 1, 2, 3, 4A, 11) ne recoivent que le point 1 : elles ne se traitent pas en prop
firm futures, et leur univers (grandes capitalisations d aujourd hui) a un biais du survivant.
"""
from __future__ import annotations

import argparse
import math
import os
import warnings
from concurrent.futures import ProcessPoolExecutor
from datetime import datetime

import numpy as np
import pandas as pd

from .qf import INSTRUMENTS, Engine, futures_minutes, resample, to_daily_et
from .user import DonchianAlt

PY_DIR = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", ".."))
COUPURE = pd.Timestamp("2021-01-01")
SEUIL_DSR = 0.90


# =============================================================================
#  Outils
# =============================================================================
def sharpe(x: pd.Series) -> float:
    x = pd.Series(x).dropna()
    sd = x.std(ddof=1)
    return float(x.mean() / sd * math.sqrt(252)) if len(x) > 20 and sd > 0 else math.nan


def periodes(x: pd.Series) -> tuple[float, float, float]:
    """Sharpe sur tout l historique, la decouverte (2016-2020) et la validation (2021-2026)."""
    return sharpe(x), sharpe(x[x.index < COUPURE]), sharpe(x[x.index >= COUPURE])


def alpha_beta(r: pd.Series, b: pd.Series) -> dict:
    """MCO r = a + beta x b sur les jours communs. Alpha annualise (x 252) et son t (erreurs MCO)."""
    d = pd.concat([r, b], axis=1, join="inner").dropna()
    if len(d) < 60:
        return dict(beta=math.nan, alpha=math.nan, t_alpha=math.nan, r2=math.nan)
    y, x = d.iloc[:, 0].to_numpy(), d.iloc[:, 1].to_numpy()
    X = np.column_stack([np.ones(len(x)), x])
    coef, *_ = np.linalg.lstsq(X, y, rcond=None)
    res = y - X @ coef
    s2 = res @ res / (len(y) - 2)
    cov = s2 * np.linalg.inv(X.T @ X)
    r2 = 1 - (res @ res) / ((y - y.mean()) @ (y - y.mean())) if y.std() > 0 else math.nan
    return dict(beta=float(coef[1]), alpha=float(coef[0] * 252), t_alpha=float(coef[0] / math.sqrt(cov[0, 0])), r2=float(r2))


def dsr(x: pd.Series, n: int) -> float:
    from .. import validation as V
    v, _ = V.deflated_sharpe(pd.Series(x).dropna().to_numpy(), n_trials=n)
    return float(v)


def pbo_famille(series: dict) -> float:
    from .. import validation as V
    m = pd.DataFrame(series).dropna(how="all").fillna(0.0)
    if m.shape[1] < 2:
        return math.nan
    v, _ = V.pbo(m.T.to_numpy())
    return float(v)


def pnl_bh(root: str, micro: str) -> pd.Series:
    """P&L quotidien de 1 micro detenu en permanence (seance CME, cloture a cloture)."""
    d = to_daily_et(futures_minutes(root))
    return (d["close"].diff() * INSTRUMENTS[micro].point_value).dropna()


# =============================================================================
#  Famille boombitch : Donchian generalise (user.DonchianAlt)
# =============================================================================
def _run_donchian(args):
    root, micro, params = args
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        df = resample(futures_minutes(root), 15)
        e = Engine(df, INSTRUMENTS[micro])
        e.run(DonchianAlt(e, **params))
        eq = e.equity()
        return eq.diff().dropna(), len(e.trades)


FAMILLE_BOOMBITCH = [  # (libelle, marche, micro, parametres, candidate au remplacement ?)
    ("originale : NQ, long seul, canaux 160/60", "NQ", "MNQ", {}, True),
    ("long + short (cassures symetriques)", "NQ", "MNQ", dict(short=True), True),
    ("canaux divises par 2 (80/30)", "NQ", "MNQ", dict(entry_donchian=80, exit_donchian=30), True),
    ("canaux multiplies par 2 (320/120)", "NQ", "MNQ", dict(entry_donchian=320, exit_donchian=120), True),
    ("filtre de tendance : cloture > moyenne 200 j", "NQ", "MNQ", dict(sma_jours=200), True),
    ("taille inverse a la volatilite (risque 300 $)", "NQ", "MNQ", dict(fixed_risk=300.0), True),
    ("controle : memes regles sur ES", "ES", "MES", {}, False),
    ("controle : memes regles sur YM", "YM", "MYM", {}, False),
    ("controle : memes regles sur GC", "GC", "MGC", {}, False),
]


# =============================================================================
#  Rapport
# =============================================================================
def _ligne(lib: str, x: pd.Series, n: int, ref: tuple | None, extra: str = "") -> tuple[str, bool]:
    s, s1, s2 = periodes(x)
    d = dsr(x, n)
    retenue = ref is not None and s1 > ref[1] and s2 > ref[2] and d >= SEUIL_DSR
    txt = (f"  {lib:48} Sharpe {s:+.2f} | 2016-2020 {s1:+.2f} | 2021-2026 {s2:+.2f} | Sharpe deflate {d:4.0%} | "
           f"PnL {x.sum():+12,.0f} $".replace(",", " ") + extra + (" | RETENUE" if retenue else ""))
    return txt, retenue


def _equity_runner(nom: str) -> pd.Series | None:
    from .portefeuille import _latest
    f = _latest("equity", nom)
    if f is None:
        return None
    eq = pd.read_csv(f, index_col=0, parse_dates=True).iloc[:, 0]
    return eq


def etude(processus: int = 4, sortie: str | None = None, log=print):
    from .. import data as D
    from .. import vbt_bridge as VB
    from . import qf
    from .suite_s import run_s20
    t0 = datetime.now()
    L = []
    pr = L.append
    pr("=" * 118)
    pr(" ALTERNATIVES AUX STRATEGIES PROMETTEUSES - protocole fixe avant les calculs (voir l en-tete de alternatives.py)")
    pr("=" * 118)
    pr("1. reference naive (beta / alpha) ; 2. familles courtes motivees ; 3. decouverte 2016-2020 / validation 2021-2026 :")
    pr(f"   une variante est RETENUE si elle bat l originale sur les deux periodes ET a un Sharpe deflate >= {SEUIL_DSR:.0%} ;")
    pr("4. PBO de chaque famille, marches de controle sans re-optimisation. Sharpe = P&L quotidien annualise (252 j).\n")
    retenues = []

    # --- boombitch -----------------------------------------------------------------------------------------
    log("[alternatives] boombitch")
    with ProcessPoolExecutor(max_workers=processus) as ex:
        res = list(ex.map(_run_donchian, [(r, m, p) for _, r, m, p, _ in FAMILLE_BOOMBITCH]))
    pnl = {lib: x for (lib, *_), (x, _) in zip(FAMILLE_BOOMBITCH, res)}
    ntr = {lib: n for (lib, *_), (_, n) in zip(FAMILLE_BOOMBITCH, res)}
    orig = FAMILLE_BOOMBITCH[0][0]
    port = pd.concat([pnl[orig]] + [pnl[l] for l, *_ in FAMILLE_BOOMBITCH if l.startswith("controle")], axis=1).fillna(0).sum(axis=1)
    pnl["portefeuille NQ + ES + YM + GC (memes regles)"] = port
    cands = [l for l, *_, c in FAMILLE_BOOMBITCH if c] + ["portefeuille NQ + ES + YM + GC (memes regles)"]
    nfam = len(cands)
    bh = pnl_bh("NQ", "MNQ")
    ab = alpha_beta(pnl[orig] / 100000, bh / 100000)
    pr("=== boombitch (Donchian 160/60, NQ 15 min, 1 MNQ) ===")
    pr(f"Reference : 1 MNQ detenu en permanence, Sharpe {sharpe(bh):+.2f}, PnL {bh.sum():+,.0f} $. Regression de boombitch sur cette".replace(",", " "))
    pr(f"reference : beta {ab['beta']:.2f}, alpha {ab['alpha'] * 100000:+,.0f} $/an (t {ab['t_alpha']:+.1f}), R2 {ab['r2']:.0%}.".replace(",", " "))
    ref = periodes(pnl[orig])
    for lib in cands + [l for l, *_ in FAMILLE_BOOMBITCH if l.startswith("controle")]:
        extra = f" | {ntr[lib]} trades" if lib in ntr else ""
        txt, ok = _ligne(lib, pnl[lib], nfam, None if lib == orig or lib.startswith("controle") else ref, extra)
        pr(txt)
        if ok:
            retenues.append(("boombitch", lib))
    pr(f"PBO de la famille ({nfam} variantes) : {pbo_famille({l: pnl[l] for l in cands}):.0%}")

    # --- S20 ---------------------------------------------------------------------------------------------------
    log("[alternatives] S20")
    legs = {"MES": "ES", "MGC": "GC", "MCL": "CL", "M6E": "6E"}
    daily = {k: to_daily_et(futures_minutes(r)) for k, r in {**legs, "MNQ": "NQ", "M6B": "6B"}.items()}
    ins = {k: INSTRUMENTS[k] for k in daily}
    base = {k: daily[k] for k in legs}
    fam20 = [("A ERC originale (fenetre 120 j, plafond 60 %)", base, dict(variante="A"), True),
             ("B inverse-volatilite originale", base, dict(variante="B"), True),
             ("ERC, covariance sur 60 j", base, dict(variante="A", fenetre=60, min_obs=40), True),
             ("ERC, covariance sur 250 j", base, dict(variante="A", fenetre=250, min_obs=120), True),
             ("ERC sans plafond de poids", base, dict(variante="A", poids_max=1.0), True),
             ("ERC a 6 jambes (+ MNQ, M6B)", {k: daily[k] for k in list(legs) + ["MNQ", "M6B"]}, dict(variante="A"), True),
             ("reference naive : 1/N, memes 4 jambes", base, dict(variante="EW"), False)]
    p20 = {}
    for lib, dd, kw, _ in fam20:
        eq, *_ = run_s20(dd, {k: ins[k] for k in dd}, **kw)
        p20[lib] = eq.diff().dropna()
    o20 = fam20[0][0]
    n20 = sum(1 for *_, c in fam20 if c)
    ref = periodes(p20[o20])
    ew = p20["reference naive : 1/N, memes 4 jambes"]
    pr("\n=== S20 parite de risque (ES, GC, CL, 6E en micros, reequilibrage mensuel) ===")
    ab = alpha_beta(p20[o20], ew)
    pr(f"Reference naive 1/N (DeMiguel et al. 2009 : difficile a battre) : Sharpe {sharpe(ew):+.2f}. Regression de l ERC sur le 1/N :")
    pr(f"beta {ab['beta']:.2f}, alpha {ab['alpha']:+,.0f} $/an (t {ab['t_alpha']:+.1f}).".replace(",", " "))
    for lib, *_, c in fam20:
        txt, ok = _ligne(lib, p20[lib], n20, ref if (c and lib != o20) else None)
        pr(txt)
        if ok:
            retenues.append(("S20", lib))
    pr(f"PBO de la famille : {pbo_famille({l: p20[l] for l, *_, c in fam20 if c}):.0%}")

    # --- Fiche 2 XSMOM futures (grille vectorbt) ---------------------------------------------------------------
    log("[alternatives] fiche 2 XSMOM futures (vectorbt)")
    data = D.load_folder(qf.QUOTES)
    fut = [s for s in "ES,NQ,YM,GC,CL,6E,6B,6J,6A".split(",") if s in data]       # FDAX : 1,5 an seulement
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        table, rets, (pbo_x, _) = VB.grid(data, fut, kind="xsmom", lookback=[126, 252], skip=[0, 21], top=[2, 3])
        close, opn = VB._panel(data, fut)
        w_ew = pd.DataFrame(0.5 / len(fut), index=close.index, columns=close.columns)
        w_ew[~VB._month_end_mask(close.index)] = np.nan
        ew_r = VB.run_weights(close, opn, w_ew).returns()
    pr("\n=== Fiche 2 XSMOM futures (vectorbt, signal seul : panier du quartile superieur, vol cible 12 %, mensuel) ===")
    eqx = _equity_runner("Fiche 2 XSMOM (futures)")
    if eqx is not None:
        rx = eqx.pct_change().dropna()
        abx = alpha_beta(rx, ew_r)
        pr(f"Version du runner (moteur Nexus, modules A-C) : Sharpe {sharpe(rx):+.2f} ; regression sur un panier 1/N long des memes")
        pr(f"futures a 50 % d exposition : beta {abx['beta']:.2f}, alpha {abx['alpha']:+.1%}/an (t {abx['t_alpha']:+.1f}).")
    pr(f"Reference 1/N long, 50 % d exposition, mensuel : Sharpe {sharpe(ew_r):+.2f}.")
    cols = list(rets.columns)
    o_x = next((c for c in cols if c == "lookback=252,skip=21,top=2"), cols[0])
    ref = periodes(rets[o_x])
    for c in cols:
        lib = ("originale : " if c == o_x else "") + c.replace(",", " ")
        txt, ok = _ligne(lib, rets[c] * 1e6, len(cols), None if c == o_x else ref, "")
        pr(txt.replace(" $", " $ (sur 1 M$)"))
        if ok:
            retenues.append(("Fiche 2 futures", c))
    pr(f"PBO de la grille (vectorbt / CSCV) : {pbo_x:.0%}")

    # --- references naives des autres strategies prometteuses --------------------------------------------------
    log("[alternatives] references naives")
    pr("\n=== Les autres strategies prometteuses face a leur reference naive ===")
    univ = "SPY,QQQ,XLF,XLV,XLE,XLI,XLY,XLP,XLU,XLB,XLRE,XLC,AAPL,MSFT,NVDA,AMZN,GOOGL,META,JPM,JNJ,XOM,UNH,V,PG,HD".split(",")
    px = pd.DataFrame({s: data[s]["close"] for s in univ if s in data})
    ew25 = px.pct_change().mean(axis=1).dropna()
    spy = data["SPY"]["close"].pct_change().dropna()
    es_nq = (data["ES"]["close"].pct_change() + data["NQ"]["close"].pct_change()).div(2).dropna()
    for nom, refr, lab in [("Fiche 5 Retour a la moyenne de vol (futures)", es_nq, "ES+NQ moitie-moitie"),
                           ("Fiche 1 TSMOM 12-1 (25 actions/ETF US)", ew25, "les 25 titres a poids egal"),
                           ("Fiche 2 XSMOM quartile superieur (25 actions/ETF US)", ew25, "les 25 titres a poids egal"),
                           ("Fiche 3 Rotation multi-facteurs", ew25, "les 25 titres a poids egal"),
                           ("Fiche 4A Residu OU sectoriel", spy, "SPY"),
                           ("Fiche 11 Roue d options synthetique", spy, "SPY")]:
        eq = _equity_runner(nom)
        if eq is None:
            pr(f"  {nom} : pas de courbe")
            continue
        r = eq.pct_change().dropna()
        r = r[r.index >= r.ne(0).idxmax()]
        a = alpha_beta(r, refr)
        sref = sharpe(refr[refr.index >= r.index[0]])
        verdict = ("alpha non distinguable de zero : surtout du beta" if abs(a["t_alpha"]) < 2
                   else "alpha positif significatif" if a["alpha"] > 0 else "alpha negatif")
        pr(f"  {nom[:52]:52} Sharpe {sharpe(r):+.2f} vs reference ({lab}) {sref:+.2f} | beta {a['beta']:.2f} | "
           f"alpha {a['alpha']:+.1%}/an (t {a['t_alpha']:+.1f}) -> {verdict}")

    pr("\n=== Synthese ===")
    if retenues:
        for f, l in retenues:
            pr(f"  RETENUE : {f} -> {l}")
    else:
        pr("  Aucune variante ne bat son originale sur les deux periodes avec un Sharpe deflate suffisant.")
    pr(f"\nCalcul en {(datetime.now() - t0).total_seconds():.0f} s.")
    sortie = sortie or os.path.join(PY_DIR, "recherche", "resultats_alternatives.txt")
    with open(sortie, "w", encoding="utf-8") as fh:
        fh.write("\n".join(L) + "\n")
    log("\n".join(L))
    return dict(boombitch=pnl, s20=p20, xsmom=rets, retenues=retenues)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--processus", type=int, default=4)
    ap.add_argument("--sortie", default=None)
    a = ap.parse_args(argv)
    etude(a.processus, a.sortie)


if __name__ == "__main__":
    main()
