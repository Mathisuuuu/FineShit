"""Gotobi Pre-Fix Drift : USD/JPY avant le fixing de Tokyo (09:55 heure de Tokyo), les jours gotobi.

    python -m nexus.perso.gotobi [--sortie resultats_gotobi.txt]

Anomalie : Ito & Yamada (Journal of International Economics, 2017). Le fixing de 09:55 a Tokyo est tire des transactions
interbancaires ; avant lui, le flux d ordres est biaise a l achat de dollars (importateurs japonais qui paient en dollars,
surtout les jours de reglement « gotobi » : 5, 10, 15, 20, 25, 30 et dernier jour du mois). Krohn, Mueller & Whelan : le
dollar reflue apres les fixings. Les regles ci-dessous sont celles de la fiche, AUCUNE n est optimisee :
  - jours gotobi seulement, decales au jour ouvre precedent (week-end, jour ferie japonais, fermeture des banques) ;
  - achat de USD/JPY a 09:00 Tokyo (00:00 UTC : le Japon n a pas d heure d ete), sortie a 09:55 (00:55 UTC) ;
  - pas de trade si le dollar a deja monte de plus d une volatilite habituelle entre 08:00 et 09:00 Tokyo ;
  - stop a 1,5 volatilite typique de la fenetre, estimee de facon robuste (ecart absolu median) sur 60 jours ;
  - groupe temoin : meme fenetre les jours NON gotobi ; seconde jambe (vente 09:55 -> 11:00) mesuree a part.
Execution sur le future 6J (dollars par yen) : USD/JPY = 1 / prix, acheter USD/JPY = vendre le 6J. Le micro MJY a un tick
de 1,25 $ (environ 1,5 point de base) ; le 6J standard (tick environ 0,75 point de base) est aussi teste.
"""
from __future__ import annotations

import argparse
import math
import os
from datetime import datetime

import numpy as np
import pandas as pd

from .fx_trois import FxMarche, executer, fx
from .orderflow import _fmt_stats, stats_r
from .qf import INSTRUMENTS

PY_DIR = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", ".."))
NS_MIN = 60_000_000_000
NS_JOUR = 86_400_000_000_000
# Heures UTC (Tokyo = UTC + 9 toute l annee) : 08:00, 09:00, 09:55 et 11:00 a Tokyo.
H0800, H0900, H0955, H1100 = -60, 0, 55, 120          # minutes depuis 00:00 UTC du jour de Tokyo
K_FILTRE, K_STOP, JOURS_VOL = 1.0, 1.5, 60
FRAICHEUR = 10                     # minutes : dernier prix connu a l heure voulue, au plus 10 min d anciennete


def feries_japon() -> set:
    f = os.path.join(os.path.dirname(__file__), "feries_japon.csv")
    return set(pd.read_csv(f, comment="#", parse_dates=["date"])["date"].dt.date)


def jours_gotobi(debut, fin, feries: set | None = None) -> set:
    """Jours de reglement gotobi (5, 10, 15, 20, 25, 30 et dernier jour du mois), decales au jour ouvre precedent si le
    jour tombe un week-end ou un jour ferie japonais."""
    feries = feries_japon() if feries is None else feries
    ouvre = lambda d: d.weekday() < 5 and d not in feries
    out = set()
    for m in pd.date_range(pd.Timestamp(debut).replace(day=1), fin, freq="MS"):
        dernier = (m + pd.offsets.MonthEnd(0)).day
        for j in sorted({5, 10, 15, 20, 25, 30, dernier}):
            if j > dernier:
                continue
            d = m.replace(day=j).date()
            while not ouvre(d):
                d -= pd.Timedelta(days=1).to_pytimedelta()
            out.add(d)
    return out


def fenetres(m: FxMarche) -> pd.DataFrame:
    """Une ligne par jour ouvre de Tokyo : indice du dernier prix connu a 08:00, 09:00, 09:55 et 11:00 (heure de Tokyo ;
    Databento ne cree pas de barre sans transaction, et le 6J est peu traite le matin a Tokyo) et rendements de USD/JPY
    (log, = -log du 6J) avant 09:00, dans la fenetre 09:00 -> 09:55 et apres le fixing."""
    feries = feries_japon()
    jours = pd.to_datetime(np.unique(m.t // NS_JOUR) * NS_JOUR)
    jours = jours[(jours.dayofweek < 5) & ~pd.Index(jours.date).isin(feries)]
    base = jours.asi8
    pos = {}
    for nom, h in (("i0800", H0800), ("i0900", H0900), ("i0955", H0955), ("i1100", H1100)):
        cible = base + h * NS_MIN
        k = np.clip(np.searchsorted(m.t, cible, side="right") - 1, 0, m.n - 1)
        pos[nom] = np.where((m.t[k] <= cible) & (m.t[k] > cible - FRAICHEUR * NS_MIN), k, -1)
    d = pd.DataFrame(pos, index=jours)
    d = d[(d >= 0).all(axis=1) & (d["i0955"] > d["i0900"]) & (d["i1100"] > d["i0955"])]
    usdjpy = lambda a, b: -np.log(m.c[d[b].to_numpy()] / m.c[d[a].to_numpy()])
    d["avant"] = usdjpy("i0800", "i0900")
    d["fenetre"] = usdjpy("i0900", "i0955")
    d["apres"] = usdjpy("i0955", "i1100")
    robuste = lambda x: x.rolling(JOURS_VOL, min_periods=30).apply(lambda v: 1.4826 * np.median(np.abs(v - np.median(v))), raw=True).shift(1)
    d["vol_avant"], d["vol_fenetre"], d["vol_apres"] = robuste(d["avant"]), robuste(d["fenetre"]), robuste(d["apres"])
    gotobi = jours_gotobi(d.index.min(), d.index.max(), feries)
    d["gotobi"] = pd.Index(d.index.date).isin(gotobi)
    return d


def test_anomalie(d: pd.DataFrame, col: str = "fenetre") -> dict:
    """Moyenne (points de base) les jours gotobi et les autres jours, ecart et t de Welch ; p bilateral par permutation."""
    g, a = d.loc[d["gotobi"], col].dropna() * 1e4, d.loc[~d["gotobi"], col].dropna() * 1e4
    if len(g) < 10 or len(a) < 10:
        return dict(n_g=len(g), n_a=len(a))
    se = math.sqrt(g.var(ddof=1) / len(g) + a.var(ddof=1) / len(a))
    ecart = g.mean() - a.mean()
    rng = np.random.default_rng(3)
    x = np.concatenate([g.to_numpy(), a.to_numpy()])
    perm = np.empty(2000)
    for k in range(perm.size):
        rng.shuffle(x)
        perm[k] = x[:len(g)].mean() - x[len(g):].mean()
    return dict(n_g=len(g), n_a=len(a), gotobi=g.mean(), t_gotobi=g.mean() / (g.std(ddof=1) / math.sqrt(len(g))),
                autres=a.mean(), t_autres=a.mean() / (a.std(ddof=1) / math.sqrt(len(a))), ecart=ecart, t_ecart=ecart / se,
                p_perm=float((np.abs(perm) >= abs(ecart)).mean()))


def _decisions(m: FxMarche, d: pd.DataFrame, jambe: str = "avant", filtre: bool = True, k_stop: float = K_STOP) -> list:
    """Decisions pour fx_trois.executer : vendre le 6J (= acheter USD/JPY) de 09:00 a 09:55, ou le racheter de 09:55 a 11:00."""
    dec = []
    for r in d[d["gotobi"]].itertuples():
        if jambe == "avant":
            if filtre and np.isfinite(r.vol_avant) and r.avant > K_FILTRE * r.vol_avant:
                continue                                       # flux deja anticipe : on s abstient
            sig, i, fin, side = r.vol_fenetre, int(r.i0900), int(r.i0955), -1
        else:
            sig, i, fin, side = r.vol_apres, int(r.i0955), int(r.i1100), 1
        if not np.isfinite(sig) or sig <= 0:
            continue
        risque = m.c[i] * (math.exp(k_stop * sig) - 1)         # le dollar baisse de k_stop x sigma = le 6J monte d autant
        dec.append((i, side, m.c[i] - side * risque, np.nan, fin, risque, 1.0))
    return dec


def backtest(jambe: str = "avant", filtre: bool = True, standard: bool = False, gl_plus: int = 0, brut: bool = False,
             nom: str | None = None) -> pd.DataFrame:
    from . import fx_trois as FT
    m = fx("6J")
    d = fenetres(m)
    inst, tick, r0 = m.inst, m.tick, FT.R
    if standard:          # 6J standard : tick deux fois plus fin, commission plus forte ; 1R = 1 000 $ (1 contrat risque souvent > 250 $)
        m.inst, m.tick, FT.R = INSTRUMENTS["6J"], INSTRUMENTS["6J"].tick, 1000.0
    try:
        t = executer(m, nom or f"Gotobi {jambe}", _decisions(m, d, jambe, filtre), 1 + gl_plus, 1 + gl_plus, not brut)
    finally:
        m.inst, m.tick, FT.R = inst, tick, r0
    return t


def etude(sortie: str | None = None, log=print) -> dict:
    t0 = datetime.now()
    m = fx("6J")
    d = fenetres(m)
    L = []
    pr = L.append
    pr("=" * 118)
    pr(" GOTOBI PRE-FIX DRIFT - USD/JPY avant le fixing de Tokyo (09:55), future 6J Databento 1 minute 2016-2026")
    pr("=" * 118)
    pr("Regles de la fiche, sans optimisation : jours gotobi (decales au jour ouvre precedent), achat 09:00 -> 09:55 Tokyo,")
    pr(f"abstention si le dollar a deja monte de plus de {K_FILTRE:g} volatilite habituelle entre 08:00 et 09:00, stop a {K_STOP:g}")
    pr(f"volatilite typique de la fenetre (ecart absolu median, {JOURS_VOL} jours). 1R = 250 $. Couts : 1 tick de glissement par")
    pr("ordre + commission (micro MJY : 0,60 $ par cote, tick 1,25 $ ; 6J standard : 2,50 $, tick 6,25 $).\n")
    ng, na = int(d["gotobi"].sum()), int((~d["gotobi"]).sum())
    pr(f"Jours ouvres de Tokyo avec un prix a 08:00, 09:00, 09:55 et 11:00 (au plus {FRAICHEUR} min d anciennete) : {len(d)} "
       f"({ng} jours gotobi, {na} autres), "
       f"{d.index.min():%Y-%m-%d} -> {d.index.max():%Y-%m-%d}.\n")

    pr("=== 1. L ANOMALIE EXISTE-T-ELLE ? (rendement de USD/JPY en points de base, sans execution ni couts) ===")
    pr("Groupe temoin : la meme fenetre les jours non gotobi. Ecart : t de Welch et p par permutation (2 000 tirages).")
    res = {}
    for col, lib in (("fenetre", "09:00 -> 09:55 (la strategie)"), ("avant", "08:00 -> 09:00 (avant l entree)"),
                     ("apres", "09:55 -> 11:00 (apres le fixing)")):
        for per, sel in (("2016-2026", slice(None)), ("2016-2020", d.index < "2021-01-01"), ("2021-2026", d.index >= "2021-01-01")):
            a = test_anomalie(d[sel], col)
            res[(col, per)] = a
            if "gotobi" not in a:
                continue
            pr(f"  {lib:32} {per} : gotobi {a['gotobi']:+.2f} pb (t {a['t_gotobi']:+.1f}, {a['n_g']} j) | autres jours "
               f"{a['autres']:+.2f} pb (t {a['t_autres']:+.1f}, {a['n_a']} j) | ecart {a['ecart']:+.2f} pb, t {a['t_ecart']:+.1f}, "
               f"p {a['p_perm']:.3f}")
    fm = d[d["gotobi"]]
    dernier = fm.groupby([fm.index.year, fm.index.month]).tail(1)
    autres_g = fm.drop(dernier.index)
    pr(f"  dont dernier jour gotobi du mois : {dernier['fenetre'].mean() * 1e4:+.2f} pb ({len(dernier)} j) ; autres jours gotobi : "
       f"{autres_g['fenetre'].mean() * 1e4:+.2f} pb ({len(autres_g)} j)")
    pr("  Par annee (fenetre 09:00 -> 09:55, gotobi - autres jours, pb) : " + " | ".join(
        f"{y} {g.loc[g['gotobi'], 'fenetre'].mean() * 1e4 - g.loc[~g['gotobi'], 'fenetre'].mean() * 1e4:+.1f}"
        for y, g in d.groupby(d.index.year)))
    px = float(np.nanmedian(m.c[-200000:]))
    pr(f"  Pour memoire, un tick vaut {m.tick / px * 1e4:.2f} pb sur le micro MJY et {INSTRUMENTS['6J'].tick / px * 1e4:.2f} pb sur le "
       "6J standard ; un aller-retour coute donc environ 2 ticks plus la commission.")

    pr("\n=== 2. LA STRATEGIE (regles de la fiche) ===")
    log("[gotobi] backtests")
    essais = 4
    lignes = [("Gotobi pre-fix, micro MJY (fiche)", backtest()),
              ("  stress +1 tick", backtest(gl_plus=1)),
              ("  sur le 6J standard (1R = 1 000 $)", backtest(standard=True)),
              ("  diagnostic : sans aucun cout", backtest(brut=True)),
              ("  diagnostic : sans le filtre anti-anticipation", backtest(filtre=False)),
              ("Seconde jambe : vente 09:55 -> 11:00 (hypothese), MJY", backtest("apres")),
              ("  seconde jambe sans aucun cout", backtest("apres", brut=True))]
    for nom, t in lignes:
        pr(_fmt_stats(nom, stats_r(t, essais)))
    principal = lignes[0][1]
    if len(principal):
        a = principal.groupby(principal["entry_time"].dt.year)["r"].sum()
        pr("  Persistance (fiche, MJY) : " + " | ".join(f"{y} {v:+.1f}R" for y, v in a.items()))
        filt = int(d["gotobi"].sum()) - len(_decisions(m, d, "avant", True))
        pr(f"  Jours gotobi ecartes par le filtre anti-anticipation : {filt} sur {int(d['gotobi'].sum())}")
    pr(f"\nCalcul en {(datetime.now() - t0).total_seconds():.0f} s.")
    out_dir = os.path.join(PY_DIR, "resultats", f"gotobi_{datetime.now():%Y%m%d_%H%M%S}")
    os.makedirs(out_dir, exist_ok=True)
    principal.to_csv(os.path.join(out_dir, "trades_gotobi.csv"), index=False)
    lignes[5][1].to_csv(os.path.join(out_dir, "trades_gotobi_apres.csv"), index=False)
    pr(f"Trades : {out_dir}")
    sortie = sortie or os.path.join(PY_DIR, "recherche", "resultats_gotobi.txt")
    with open(sortie, "w", encoding="utf-8") as fh:
        fh.write("\n".join(L) + "\n")
    log("\n".join(L))
    return dict(fenetres=d, tests=res, trades=principal)


def run_spec(spec: dict) -> tuple[dict, pd.DataFrame]:
    t = backtest(spec.get("jambe", "avant"), nom=spec.get("nom"))
    jours = pd.bdate_range("2016-01-04", "2026-08-28")
    if t.empty:
        eq, pnl = pd.Series(25000.0, index=jours), np.array([])
    else:
        d = t.groupby(t["exit_time"].dt.normalize())["pnl"].sum().reindex(jours, fill_value=0.0)
        eq, pnl = 25000.0 + d.cumsum(), t["pnl"].to_numpy()
    dd = eq.diff().dropna()
    wins, losses = pnl[pnl > 0].sum() if pnl.size else 0.0, -pnl[pnl < 0].sum() if pnl.size else 0.0
    s = dict(trades=len(pnl), win_rate=float((pnl > 0).mean()) if pnl.size else math.nan, net=float(pnl.sum()) if pnl.size else 0.0,
             profit_factor=float(wins / losses) if losses > 0 else math.nan, avg_trade=float(pnl.mean()) if pnl.size else math.nan,
             sharpe=float(dd.mean() / dd.std() * math.sqrt(252)) if dd.std() > 0 else math.nan,
             max_dd=float((eq.cummax() - eq).max()), start=eq.index[0], end=eq.index[-1], capital=25000.0,
             t_stat=float(pnl.mean() / (pnl.std(ddof=1) / math.sqrt(pnl.size))) if pnl.size > 2 and pnl.std(ddof=1) > 0 else math.nan,
             equity=eq, data="6J 1 min -> MJY, 1R = 250 $")
    return s, t


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--sortie", default=None)
    a = ap.parse_args(argv)
    etude(a.sortie)


if __name__ == "__main__":
    main()
