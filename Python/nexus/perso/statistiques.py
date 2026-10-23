"""Intervalles de confiance, edge et Monte Carlo des strategies (tableau de bord et rapport texte).

    python -m nexus.perso.statistiques [--sortie resultats_ic_montecarlo.txt]

Edge = esperance de gain par trade, nette de couts = reussite x gain moyen - (1 - reussite) x perte moyenne.
Intervalles de confiance a 95 % :
  - edge : t de Student et bootstrap (2 000 tirages des trades avec remise) ; P(edge > 0) = part des tirages > 0 ;
  - taux de reussite : Wilson ; profit factor : bootstrap ;
  - Sharpe annualise : erreur type de Mertens (2002), valable pour des rendements non normaux,
    SE = racine((1 + SR^2 / 2 - asymetrie x SR + (kurtosis - 3) / 4 x SR^2) / T) sur le Sharpe quotidien, x racine(252) ;
    P(Sharpe > 0) = Sharpe probabiliste (Bailey, Lopez de Prado).
Monte Carlo : bootstrap par blocs de 10 jours du P&L quotidien (garde l autocorrelation et les grappes de pertes) :
  - 2 000 trajectoires d un an : cone des centiles 5 / 25 / 50 / 75 / 95, P(perte sur un an), drawdown a 95 % ;
  - 1 000 trajectoires de la longueur de l historique : distribution du drawdown max, rang du drawdown historique ;
  - pire serie de pertes consecutives : trades tires avec remise, meme nombre que l historique.
Le bootstrap suppose que le passe est representatif : il mesure le hasard du tirage, pas un changement de regime.
Une position permanente (S20, fiche 5) n a pas d edge par trade : seuls le Sharpe et le Monte Carlo s appliquent.
"""
from __future__ import annotations

import argparse
import math
import os

import numpy as np
import pandas as pd

PY_DIR = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", ".."))
CENTILES = (5, 25, 50, 75, 95)
BLOC = 10


def trades_pnl(nom: str) -> pd.Series | None:
    """P&L net par trade (en $), indexe par la sortie ; None si le fichier n a pas de trades au sens propre."""
    from .portefeuille import _latest
    f = _latest("trades", nom)
    if f is None or os.path.getsize(f) < 5:
        return None
    t = pd.read_csv(f)
    if t.empty or "exit_time" not in t.columns:
        return None
    col = "net_pnl" if "net_pnl" in t.columns else "pnl"
    return pd.Series(t[col].to_numpy(float), index=pd.to_datetime(t["exit_time"])).sort_index()


def durees_trades(nom: str) -> dict | None:
    """Temps en position par trade (minutes, temps calendaire de l entree a la sortie : nuits et week-ends compris
    pour une position gardee). Barres horodatees a leur fin : precision d une barre (1 min, 15 min, 1 jour...).
    -> moyenne, mediane, moyenne des gagnants et des perdants, plus long ; None sans heures d entree et de sortie."""
    from .portefeuille import _latest
    f = _latest("trades", nom)
    if f is None or os.path.getsize(f) < 5:
        return None
    t = pd.read_csv(f)
    if t.empty or "entry_time" not in t.columns or "exit_time" not in t.columns:
        return None
    e, x = pd.to_datetime(t["entry_time"]), pd.to_datetime(t["exit_time"])
    d = ((x - e).dt.total_seconds() / 60.0).to_numpy(float)
    pnl = t["net_pnl" if "net_pnl" in t.columns else "pnl"].to_numpy(float)
    ok = np.isfinite(d) & (d >= 0)
    d, pnl = d[ok], pnl[ok]
    if d.size == 0:
        return None
    journalier = bool((e.dt.normalize() == e).all() and (x.dt.normalize() == x).all())
    moy = lambda v: float(v.mean()) if v.size else math.nan
    return dict(n=int(d.size), moyenne=moy(d), mediane=float(np.median(d)), gagnants=moy(d[pnl > 0]), perdants=moy(d[pnl < 0]),
                max=float(d.max()), journalier=journalier)


def fmt_duree(minutes) -> str:
    """'< 1 min', '42 min', '3 h 05', '4,2 j'."""
    if minutes is None or not math.isfinite(minutes):
        return "n/d"
    if minutes < 1:
        return "< 1 min"
    if round(minutes) < 60:
        return f"{minutes:.0f} min"
    if round(minutes) < 1440:
        h, m = divmod(int(round(minutes)), 60)
        return f"{h} h {m:02d}" if m else f"{h} h"
    j = minutes / 1440
    return f"{j:.1f} j".replace(".", ",") if j < 10 else f"{j:.0f} j"


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return math.nan, math.nan
    p = k / n
    den = 1 + z * z / n
    c = (p + z * z / (2 * n)) / den
    w = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return c - w, c + w


def ic_edge(p: np.ndarray, B: int = 2000, seed: int = 1) -> dict:
    p = np.asarray(p, float)
    p = p[np.isfinite(p)]
    n = p.size
    if n < 5:
        return dict(n=n)
    m, sd = float(p.mean()), float(p.std(ddof=1))
    se = sd / math.sqrt(n)
    rng = np.random.default_rng(seed)
    moy, pf = np.empty(B), np.empty(B)
    pas = max(1, int(2e7 // n))
    for a in range(0, B, pas):
        b = min(B, a + pas)
        x = p[rng.integers(0, n, size=(b - a, n))]
        moy[a:b] = x.mean(axis=1)
        g, q = np.where(x > 0, x, 0).sum(axis=1), -np.where(x < 0, x, 0).sum(axis=1)
        with np.errstate(divide="ignore", invalid="ignore"):
            pf[a:b] = np.where(q > 0, g / q, np.nan)
    gains, pertes = p[p > 0], p[p < 0]
    k = int((p > 0).sum())
    return dict(n=n, esperance=m, ic_t=[m - 1.96 * se, m + 1.96 * se], ic=[float(np.percentile(moy, 2.5)), float(np.percentile(moy, 97.5))],
                p_pos=float((moy > 0).mean()), t=m / se if se > 0 else math.nan, reussite=k / n, ic_reussite=list(wilson(k, n)),
                gain_moy=float(gains.mean()) if gains.size else math.nan, perte_moy=float(pertes.mean()) if pertes.size else math.nan,
                payoff=float(gains.mean() / -pertes.mean()) if gains.size and pertes.size else math.nan,
                pf=float(gains.sum() / -pertes.sum()) if pertes.size else math.nan,
                ic_pf=[float(np.nanpercentile(pf, 2.5)), float(np.nanpercentile(pf, 97.5))])


def ic_sharpe(daily: pd.Series) -> dict:
    from .. import mathx as M
    from .. import validation as V
    x = pd.Series(daily).dropna().to_numpy(float)
    T = x.size
    sd = x.std(ddof=1) if T > 2 else 0.0
    if T < 30 or sd <= 0:
        return dict(valeur=math.nan, ic=[math.nan, math.nan], p_pos=math.nan)
    sr = x.mean() / sd
    sk, ku = M.skewness(x), M.kurtosis(x)
    var = (1 + 0.5 * sr * sr - sk * sr + (ku - 3) / 4.0 * sr * sr) / T
    se = math.sqrt(max(var, 1e-18))
    a = math.sqrt(252)
    return dict(valeur=sr * a, ic=[(sr - 1.96 * se) * a, (sr + 1.96 * se) * a], p_pos=V.probabilistic_sharpe(sr, 0.0, T, sk, ku))


def _blocs(x: np.ndarray, n: int, longueur: int, rng, bloc: int = BLOC) -> np.ndarray:
    """Bootstrap par blocs circulaires : n trajectoires de `longueur` jours."""
    T = x.size
    nb = -(-longueur // bloc)
    debuts = rng.integers(0, T, size=(n, nb))
    idx = (debuts[:, :, None] + np.arange(bloc)) % T
    return x[idx.reshape(n, nb * bloc)[:, :longueur]]


def _dd_max(cum: np.ndarray) -> np.ndarray:
    c = np.concatenate([np.zeros((cum.shape[0], 1)), cum], axis=1)
    return (np.maximum.accumulate(c, axis=1) - c).max(axis=1)


def _serie_max(neg: np.ndarray) -> np.ndarray:
    c = np.cumsum(neg, axis=1)
    reset = np.maximum.accumulate(np.where(neg == 0, c, 0), axis=1)
    return (c - reset).max(axis=1)


def monte_carlo(daily: pd.Series, trades: np.ndarray | None = None, n_an: int = 2000, n_hist: int = 1000,
                horizon: int = 252, seed: int = 7) -> dict:
    x = pd.Series(daily).dropna().to_numpy(float)
    if x.size < 60:
        return {}
    rng = np.random.default_rng(seed)
    cum = _blocs(x, n_an, horizon, rng).cumsum(axis=1)
    cone = np.percentile(np.concatenate([np.zeros((n_an, 1)), cum], axis=1), CENTILES, axis=0)
    fin = cum[:, -1]
    dd1 = _dd_max(cum)
    ch = _blocs(x, n_hist, x.size, rng).cumsum(axis=1)
    ddh = _dd_max(ch)
    eq = np.cumsum(x)
    dd_reel = float(_dd_max(eq[None, :])[0])
    comptes, bords = np.histogram(ddh, bins=30)
    out = dict(cone=[[round(float(v), 1) for v in row] for row in cone],
               fin_1an=[float(np.percentile(fin, q)) for q in (5, 50, 95)], p_perte_1an=float((fin < 0).mean()),
               dd_1an=[float(np.percentile(dd1, q)) for q in (50, 95)],
               dd_hist=dd_reel, dd_mc=[float(np.percentile(ddh, q)) for q in (5, 50, 95)],
               rang_dd=float((ddh <= dd_reel).mean()), hist=dict(bords=[round(float(b), 1) for b in bords], comptes=comptes.tolist()),
               pnl_hist_mc=[float(np.percentile(ch[:, -1], q)) for q in (5, 50, 95)])
    if trades is not None and len(trades) >= 20:
        tr = np.asarray(trades, float)
        neg = (tr[rng.integers(0, tr.size, size=(1000, tr.size))] < 0).astype(np.int32)
        sm = _serie_max(neg)
        out["serie"] = dict(historique=int(_serie_max((tr < 0).astype(np.int32)[None, :])[0]),
                            mc=[int(np.percentile(sm, 50)), int(np.percentile(sm, 95))])
    return out


def analyser(daily: pd.Series, trades: pd.Series | None, permanent: bool = False) -> dict:
    """Tout ce que le tableau de bord affiche pour une strategie (P&L quotidien en $, P&L par trade en $)."""
    pt = None if (trades is None or permanent) else trades.to_numpy(float)
    return dict(edge=ic_edge(pt) if pt is not None and pt.size >= 5 else None, sharpe=ic_sharpe(daily),
                mc=monte_carlo(daily, pt))


def _arrondir(o, nd=2):
    if isinstance(o, float):
        return round(o, nd) if math.isfinite(o) else None
    if isinstance(o, dict):
        return {k: _arrondir(v, nd) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_arrondir(v, nd) for v in o]
    return o


def main(argv=None):
    from .portefeuille import charger
    from .runner import TESTS
    ap = argparse.ArgumentParser()
    ap.add_argument("--sortie", default=os.path.join(PY_DIR, "recherche", "resultats_ic_montecarlo.txt"))
    a = ap.parse_args(argv)
    perm = {n: spec.get("permanent", False) for n, _, spec, _ in TESTS}
    f = lambda v: f"{v:+,.0f}".replace(",", " ") if v is not None and math.isfinite(v) else "n/d"
    L = ["Strategie | edge par trade [IC 95 % bootstrap] | P(edge > 0) | reussite [IC Wilson] | temps en position par trade : "
         "moyenne (mediane ; gagnants / perdants) | Sharpe [IC 95 %] | P(Sharpe > 0) | "
         "Monte Carlo 1 an : PnL median [5 % ; 95 %], P(perte), drawdown a 95 % | drawdown historique : centile du Monte Carlo",
         "# Bootstrap des trades (2 000 tirages) et du P&L quotidien par blocs de 10 jours. En $, a la taille du backtest.",
         "# Temps en position : calendaire, de l entree a la sortie (nuits et week-ends compris), a une barre pres.", ""]
    rows = []
    for s in charger(seulement_futures=False):
        r = analyser(s.pnl, trades_pnl(s.nom), perm.get(s.nom, False))
        r["duree"] = durees_trades(s.nom)
        rows.append((r["sharpe"]["valeur"] if math.isfinite(r["sharpe"]["valeur"]) else -99, s.nom, r, perm.get(s.nom, False)))
    for _, nom, r, permanent in sorted(rows, key=lambda x: -x[0]):
        e, sh, mc, du = r["edge"], r["sharpe"], r["mc"], r["duree"]
        dtxt = ("position permanente" if permanent else "n/d") if (permanent or du is None) else (
            f"{fmt_duree(du['moyenne'])} ({fmt_duree(du['mediane'])} ; {fmt_duree(du['gagnants'])} / {fmt_duree(du['perdants'])})")
        if e and "esperance" in e:
            ed = (f"{f(e['esperance'])} $ [{f(e['ic'][0])} ; {f(e['ic'][1])}] | {e['p_pos']:.0%} | {e['reussite']:.0%} "
                  f"[{e['ic_reussite'][0]:.0%}-{e['ic_reussite'][1]:.0%}]")
        else:
            ed = ("position permanente : pas d edge par trade" if permanent else "moins de 5 trades") + " | - | -"
        if not math.isfinite(sh["valeur"]):
            L.append(f"{nom} | {ed} | {dtxt} | Sharpe n/d | - | n/d")
            continue
        m = (f"{f(mc['fin_1an'][1])} $ [{f(mc['fin_1an'][0])} ; {f(mc['fin_1an'][2])}], {mc['p_perte_1an']:.0%}, {f(mc['dd_1an'][1])} $ | "
             f"{mc['rang_dd']:.0%}") if mc else "n/d"
        L.append(f"{nom} | {ed} | {dtxt} | {sh['valeur']:+.2f} [{sh['ic'][0]:+.2f} ; {sh['ic'][1]:+.2f}] | {sh['p_pos']:.0%} | {m}")
    with open(a.sortie, "w", encoding="utf-8") as fh:
        fh.write("\n".join(L) + "\n")
    print("\n".join(L))
    print(f"\n-> {a.sortie}")


if __name__ == "__main__":
    main()
