"""Rapport du forward test du Groupe -> Dashboard/donnees/groupe.json (page « Forward test » du tableau de bord).

    python -m nexus.live.rapport [--groupe "Documents/NinjaTrader 8/Nexus/groupe"] [--sortie Dashboard/donnees]

Les strategies tournent dans NinjaTrader (Strategies/NexusGroupeS1.cs, NexusGroupeGotobi.cs) sur le compte demo et
ecrivent, chacune dans groupe/<nom> : meta.json, barres.csv (barres 1 minute recues en temps reel), decisions.jsonl,
executions.jsonl ; l AddOn NexusTableau ecrit groupe/compte.jsonl (valeur du compte). Tous les calculs passent par
vectorbt : executions -> vbt.Portfolio.from_orders sur le prix en dollars (prix x valeur du point), frais = commission +
1/2 tick par cote ; combinaison = somme des resultats journaliers (New York) ; statistiques, drawdown, Sharpe cumule et
glissant (accesseur vbt.returns), correlation, Monte Carlo (bootstrap par blocs, ordre des trades melange) des 20 jours.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
from datetime import datetime, timezone

import numpy as np
import pandas as pd

from .moteur import ETAT
from .strategie import POINTS

NY = "America/New_York"
SORTIE = os.path.dirname(ETAT)
MICRO = {"MNQ": "NQ", "MES": "ES", "MYM": "YM", "M2K": "RTY", "MJY": "6J", "MGC": "GC", "M6E": "6E"}
COMMISSION = {"NQ": 2.25, "ES": 2.25, "YM": 2.25, "RTY": 2.25, "6J": 2.25, "6E": 2.25, "GC": 2.25,
              "MNQ": 0.62, "MES": 0.62, "MYM": 0.62, "M2K": 0.62, "MJY": 0.62, "M6E": 0.62, "MGC": 0.62}
TICK = {"NQ": 0.25, "MNQ": 0.25, "ES": 0.25, "MES": 0.25, "YM": 1.0, "MYM": 1.0, "RTY": 0.1, "M2K": 0.1,
        "6J": 0.0000005, "MJY": 0.000001, "6E": 0.00005, "M6E": 0.0001, "GC": 0.1, "MGC": 0.1}
RESERVE = 1e9                               # liquidites jamais investies (vectorbt ne gere pas la marge des futures)
MC_CHEMINS, MC_BLOC = 2000, 5


# ---------------------------------------------------------------------------------------------------- donnees
def _charger_archive(dossier: str, inst: str) -> pd.DataFrame | None:
    f = os.path.join(dossier, f"{inst}.parquet")
    if not os.path.exists(f):
        return None
    a = pd.read_parquet(f)
    if not len(a):
        return None
    idx = pd.to_datetime(a["t"].astype("int64") - 60_000, unit="ms", utc=True)        # debut de barre, UTC
    df = pd.DataFrame({k: a[k].to_numpy(float) for k in ("open", "high", "low", "close", "volume")}, index=idx)
    return df[~df.index.duplicated(keep="last")].sort_index()


def lire_jsonl(f: str) -> list[dict]:
    if not os.path.exists(f):
        return []
    out = []
    with open(f, encoding="utf-8") as fh:
        for ligne in fh:
            try:
                out.append(json.loads(ligne))
            except ValueError:
                pass
    return out


def cout_contrat(inst: str) -> float:
    r = inst.split(" ")[0]
    return COMMISSION.get(r, 2.25) + 0.5 * TICK.get(r, 0.0) * POINTS.get(r, 1.0)


def _js(x):
    if isinstance(x, (np.floating, float)):
        return None if not math.isfinite(float(x)) else round(float(x), 6)
    if isinstance(x, (np.integer,)):
        return int(x)
    if isinstance(x, (pd.Timestamp, datetime)):
        return x.isoformat()
    if isinstance(x, pd.Timedelta):
        return str(x)
    return x


def _serie(s: pd.Series, dec: int = 6) -> dict:
    s = s.dropna()
    return dict(x=[d.strftime("%Y-%m-%d") for d in s.index], y=[round(float(v), dec) for v in s.to_numpy()])


def _stats(st: pd.Series) -> list[list]:
    return [[str(k), _js(v)] for k, v in st.items()]


# ---------------------------------------------------------------------------------------------------- strategies
def portefeuille(fills: pd.DataFrame, prix: pd.DataFrame, inst: str, capital: float):
    """Ordres rejoues -> vbt.Portfolio.from_orders sur le prix en dollars (prix x valeur du point) de l instrument."""
    import vectorbt as vbt
    pv = POINTS.get(inst.split(" ")[0], 1.0)
    idx = pd.DatetimeIndex(prix.index).tz_convert("UTC").tz_localize(None)
    close = pd.Series(prix["close"].to_numpy(float) * pv, index=idx)
    t = pd.to_datetime(fills["t"].astype("int64"), unit="ms")
    g = pd.DataFrame(dict(t=t, q=fills["qty"].astype(float), p=fills["prix"].astype(float) * pv)).groupby("t")
    q = g["q"].sum()
    p = g.apply(lambda x: float(np.average(x["p"], weights=np.abs(x["q"]))) if np.abs(x["q"]).sum() else float(x["p"].iloc[-1]))
    taille = pd.Series(np.nan, index=idx)
    prix_o = pd.Series(np.nan, index=idx)
    taille.loc[q.index.intersection(idx)] = q.reindex(q.index.intersection(idx)).to_numpy()
    prix_o.loc[p.index.intersection(idx)] = p.reindex(p.index.intersection(idx)).to_numpy()
    frais = (taille.abs() * cout_contrat(inst)).fillna(0.0)
    pf = vbt.Portfolio.from_orders(close=close, size=taille, price=prix_o.fillna(close), size_type="amount",
                                   fixed_fees=frais, init_cash=RESERVE + capital, freq="1min")
    return pf, pv


def journalier(pf, capital: float) -> pd.Series:
    """Valeur vectorbt en fin de journee de New York (equity de la strategie, reserve retiree)."""
    v = pf.value() - RESERVE
    d = pd.DatetimeIndex(v.index).tz_localize("UTC").tz_convert(NY).tz_localize(None).normalize()
    j = pd.Series(v.to_numpy(), index=d).groupby(level=0).last()
    jours = pd.bdate_range(j.index[0], j.index[-1])
    return j.reindex(j.index.union(jours)).ffill().fillna(capital).reindex(jours)


def trades_lisibles(pf, pv: float, nom: str, inst: str) -> list[dict]:
    tr = pf.trades.records_readable
    out = []
    for r in tr.itertuples(index=False):
        e, x = pd.Timestamp(r[tr.columns.get_loc("Entry Timestamp")]), pd.Timestamp(r[tr.columns.get_loc("Exit Timestamp")])
        out.append(dict(strategie=nom, instrument=inst, sens="long" if str(r[tr.columns.get_loc("Direction")]) == "Long" else "short",
                        contrats=_js(r[tr.columns.get_loc("Size")]),
                        entree=e.tz_localize("UTC").isoformat(), sortie=x.tz_localize("UTC").isoformat(),
                        prix_entree=_js(r[tr.columns.get_loc("Avg Entry Price")] / pv), prix_sortie=_js(r[tr.columns.get_loc("Avg Exit Price")] / pv),
                        pnl=_js(r[tr.columns.get_loc("PnL")]), rendement=_js(r[tr.columns.get_loc("Return")]),
                        statut=str(r[tr.columns.get_loc("Status")])))
    return out


def ordres_lisibles(pf, pv: float, nom: str, inst: str) -> list[dict]:
    o = pf.orders.records_readable
    return [dict(strategie=nom, instrument=inst, t=pd.Timestamp(r["Timestamp"]).tz_localize("UTC").isoformat(),
                 cote="achat" if str(r["Side"]) == "Buy" else "vente", contrats=_js(r["Size"]), prix=_js(r["Price"] / pv),
                 frais=_js(r["Fees"])) for _, r in o.iterrows()]


# ---------------------------------------------------------------------------------------------------- combinaison
def mesures(rets: pd.Series) -> dict:
    import vectorbt as vbt  # noqa: F401  (accesseur .vbt)
    acc = rets.vbt.returns(freq="1D", year_freq="252 days")
    return dict(stats=_stats(acc.stats()),
                sharpe_cumule=_serie(acc.rolling_sharpe_ratio(len(rets), minp=60), 4),
                sharpe_glissant=_serie(acc.rolling_sharpe_ratio(252, minp=126), 4),
                drawdown=_serie(acc.drawdown(), 5),
                annuels={str(y): _js(float((1 + g).prod() - 1)) for y, g in rets.groupby(rets.index.year)})


def mensuels(rets: pd.Series) -> dict:
    m = (1 + rets).groupby([rets.index.year, rets.index.month]).prod() - 1
    out: dict = {}
    for (y, mo), v in m.items():
        out.setdefault(str(y), [None] * 12)[mo - 1] = _js(float(v))
    return out


def monte_carlo(rets: pd.Series, pnl_trades: np.ndarray, capital: float, seed: int = 7) -> dict:
    """Bootstrap par blocs des rendements journaliers (chemins d equity, rendement final, perte max) et ordre des trades
    melange (perte max)."""
    from .. import validation as V
    r = rets.to_numpy(float)
    n = len(r)
    rng = np.random.default_rng(seed)
    nb = int(math.ceil(n / MC_BLOC))
    debuts = rng.integers(0, max(1, n - MC_BLOC + 1), size=(MC_CHEMINS, nb))
    idx = (debuts[:, :, None] + np.arange(MC_BLOC)[None, None, :]).reshape(MC_CHEMINS, -1)[:, :n]
    chemins = np.cumprod(1 + r[idx], axis=1)
    pic = np.maximum.accumulate(chemins, axis=1)
    pmax = (1 - chemins / pic).max(axis=1)
    pas = np.unique(np.linspace(0, n - 1, min(n, 300)).astype(int))
    q = np.percentile(chemins[:, pas], [5, 25, 50, 75, 95], axis=0)
    jours = rets.index[pas]
    finaux = chemins[:, -1] - 1
    hist_f = np.histogram(finaux, bins=40)
    hist_d = np.histogram(pmax, bins=40)
    ordre = V.monte_carlo_max_dd(pnl_trades, capital, sims=MC_CHEMINS) if len(pnl_trades) > 2 else np.array([])
    return dict(chemins=MC_CHEMINS, bloc=MC_BLOC,
                eventail=dict(x=[d.strftime("%Y-%m-%d") for d in jours], p5=q[0].round(5).tolist(), p25=q[1].round(5).tolist(),
                              p50=q[2].round(5).tolist(), p75=q[3].round(5).tolist(), p95=q[4].round(5).tolist(),
                              reel=np.cumprod(1 + r)[pas].round(5).tolist()),
                final=dict(bords=hist_f[1].round(5).tolist(), n=hist_f[0].tolist(), p5=_js(np.percentile(finaux, 5)),
                           p50=_js(np.percentile(finaux, 50)), p95=_js(np.percentile(finaux, 95)), proba_perte=_js(float((finaux < 0).mean()))),
                perte_max=dict(bords=hist_d[1].round(5).tolist(), n=hist_d[0].tolist(), p50=_js(np.percentile(pmax, 50)),
                               p95=_js(np.percentile(pmax, 95)), p99=_js(np.percentile(pmax, 99))),
                ordre_trades=dict(p50=_js(np.percentile(ordre, 50)) if len(ordre) else None,
                                  p95=_js(np.percentile(ordre, 95)) if len(ordre) else None,
                                  p99=_js(np.percentile(ordre, 99)) if len(ordre) else None))


# ---------------------------------------------------------------------------------------------------- prix
def bougies_journalieres(df: pd.DataFrame) -> dict:
    d = df.copy()
    d.index = pd.DatetimeIndex(d.index).tz_convert(NY).tz_localize(None)
    j = d.groupby(d.index.normalize()).agg(open=("open", "first"), high=("high", "max"), low=("low", "min"), close=("close", "last"))
    return dict(x=[t.strftime("%Y-%m-%d") for t in j.index], o=j.open.round(7).tolist(), h=j.high.round(7).tolist(),
                l=j.low.round(7).tolist(), c=j.close.round(7).tolist())


def fenetres_intrajour(df: pd.DataFrame, trades: list[dict], marge_min: int = 60) -> dict:
    """{annee: {jour NY: [[t_ms debut de barre, o, h, l, c], ...]}} autour des trades (une heure avant et apres)."""
    out: dict = {}
    if not trades:
        return out
    idx = pd.DatetimeIndex(df.index)
    t_ms = idx.as_unit("ms").asi8
    garder = np.zeros(len(df), bool)
    for tr in trades:
        a = pd.Timestamp(tr["entree"]).value // 1_000_000 - marge_min * 60_000
        b = pd.Timestamp(tr["sortie"]).value // 1_000_000 + marge_min * 60_000
        garder[np.searchsorted(t_ms, a):np.searchsorted(t_ms, b, side="right")] = True
    sel = df[garder]
    jours = pd.DatetimeIndex(sel.index).tz_convert(NY).tz_localize(None).normalize()
    tt = pd.DatetimeIndex(sel.index).as_unit("ms").asi8
    for (j, grp) in pd.DataFrame(dict(t=tt, o=sel.open.to_numpy(), h=sel.high.to_numpy(), l=sel.low.to_numpy(),
                                      c=sel.close.to_numpy()), index=jours).groupby(level=0):
        out.setdefault(str(j.year), {})[j.strftime("%Y-%m-%d")] = grp[["t", "o", "h", "l", "c"]].round(7).values.tolist()
    return out


# ---------------------------------------------------------------------------------------------------- rapport
MC_JOURS_MIN = 20
GROUPE_NT = os.path.join(os.path.expanduser("~"), "Documents", "NinjaTrader 8", "Nexus", "groupe")


def charger_barres_csv(f: str) -> pd.DataFrame | None:
    """barres.csv ecrit par les strategies NinjaScript : t_fin_ms,o,h,l,c,v (barres 1 minute recues en temps reel)."""
    if not os.path.exists(f) or os.path.getsize(f) == 0:
        return None
    a = pd.read_csv(f, header=None, names=["t", "open", "high", "low", "close", "volume"])
    idx = pd.to_datetime(a["t"].astype("int64") - 60_000, unit="ms", utc=True)
    df = pd.DataFrame({k: a[k].to_numpy(float) for k in ("open", "high", "low", "close", "volume")}, index=idx)
    return df[~df.index.duplicated(keep="last")].sort_index()


def _resultat(nom, neg, source, capital, fills, prix_src) -> dict:
    pf, pv = portefeuille(fills, prix_src, neg, capital)
    eq = journalier(pf, capital)
    return dict(nom=nom, instrument=neg, source_prix=source, capital=capital, equity=eq, rets=eq.pct_change().fillna(0.0),
                pnl=eq.diff().fillna(eq.iloc[0] - capital), stats_pf=_stats(pf.stats()), stats_trades=_stats(pf.trades.stats()),
                trades=trades_lisibles(pf, pv, nom, neg), ordres=ordres_lisibles(pf, pv, nom, neg),
                pnl_trades=pf.trades.records_readable["PnL"].to_numpy(float))


def construire(groupe: str = GROUPE_NT, sortie: str = SORTIE, log=print) -> dict:
    """Forward test : pour chaque strategie NinjaScript du Groupe (dossier groupe/<nom> : meta.json, barres.csv,
    executions.jsonl, decisions.jsonl), executions reelles du compte demo valorisees par vectorbt sur ses barres."""
    os.makedirs(sortie, exist_ok=True)
    erreurs, notes, resultats = [], [], []
    prix: dict[str, pd.DataFrame] = {}
    executions, decisions = [], []
    metas = []
    for d in sorted(os.listdir(groupe)) if os.path.isdir(groupe) else []:
        rep = os.path.join(groupe, d)
        f = os.path.join(rep, "meta.json")
        if not os.path.isfile(f):
            continue
        try:
            with open(f, encoding="utf-8") as fh:
                metas.append((rep, json.load(fh)))
        except ValueError as ex:
            erreurs.append(f"{d} : meta.json illisible ({ex})")
    for rep, meta in metas:
        nom, neg = meta.get("nom", os.path.basename(rep)), str(meta.get("instrument_negocie", ""))
        source = str(meta.get("donnees") or neg).split(" ")[0]
        df = charger_barres_csv(os.path.join(rep, "barres.csv"))
        if df is not None:
            prix[source] = df if source not in prix else pd.concat([prix[source], df]).pipe(lambda x: x[~x.index.duplicated(keep="last")].sort_index())
        ex = lire_jsonl(os.path.join(rep, "executions.jsonl"))
        executions += ex
        decisions += lire_jsonl(os.path.join(rep, "decisions.jsonl"))
        if not ex:
            notes.append(f"{nom} : aucune execution sur le compte demo pour l instant")
            continue
        if source not in prix:
            erreurs.append(f"{nom} : pas encore de barres NinjaTrader enregistrees pour {source}")
            continue
        e = pd.DataFrame(ex)
        fills = pd.DataFrame(dict(t=(e["t"].astype("int64") // 60_000) * 60_000, qty=e["qty"].astype(float), prix=e["prix"].astype(float)))
        debut = pd.Timestamp(int(fills["t"].min()), unit="ms", tz="UTC").normalize() - pd.Timedelta(days=1)
        resultats.append(_resultat(nom, neg.split(" ")[0], source, float(meta.get("capital", 100_000)), fills, prix[source].loc[debut:]))
    comptes = {m.get("compte") for _, m in metas if m.get("compte")}   # courbe du seul compte des strategies (0 = deconnexion)
    compte = [c for c in lire_jsonl(os.path.join(groupe, "compte.jsonl"))
              if isinstance(c.get("valeur_liquidative"), (int, float)) and c["valeur_liquidative"] > 0
              and (not comptes or c.get("compte") in comptes)]
    debuts = [m.get("demarre_utc") for _, m in metas if m.get("demarre_utc")]
    out: dict = dict(genere=datetime.now(timezone.utc).isoformat(), mode="forward", erreurs=erreurs, notes=notes,
                     source="Forward test : strategies NinjaScript du Groupe sur le compte demo NinjaTrader (executions, barres 1 minute "
                            "recues en temps reel et valeur du compte ecrites par NinjaTrader). Calculs : vectorbt.",
                     debut_forward=min(debuts)[:10] if debuts else None,
                     compte=dict(x=[c.get("heure_et") for c in compte], y=[c.get("valeur_liquidative") for c in compte]),
                     donnees={i: dict(barres=int(len(d)), debut=d.index[0].isoformat(), fin=d.index[-1].isoformat()) for i, d in prix.items()})
    out["bougies"] = {i: bougies_journalieres(d) for i, d in prix.items()}
    if resultats:
        cap = max(r["capital"] for r in resultats)
        jours = resultats[0]["equity"].index
        for r in resultats[1:]:
            jours = jours.union(r["equity"].index)
        pnl = pd.DataFrame({r["nom"]: r["pnl"].reindex(jours).fillna(0.0) for r in resultats})
        eq_c = cap + pnl.sum(axis=1).cumsum()
        rets_c = eq_c.pct_change().fillna(float(eq_c.iloc[0] / cap - 1))
        rets_s = pd.DataFrame({r["nom"]: r["rets"].reindex(jours).fillna(0.0) for r in resultats})
        actifs = rets_s.loc[:, rets_s.abs().sum() > 0]
        corr = actifs.corr() if actifs.shape[1] > 1 and len(actifs) >= 5 else pd.DataFrame()
        roul = {}
        if actifs.shape[1] > 1 and len(actifs) >= 60:
            a, b = actifs.columns[:2]
            roul = dict(paire=[a, b], **_serie(actifs[a].rolling(126, min_periods=60).corr(actifs[b]), 4))
        pnl_tr = np.concatenate([r["pnl_trades"] for r in resultats])
        out["combinaison"] = dict(capital=cap, membres=[r["nom"] for r in resultats], jours=int(len(rets_c)), equity=_serie(eq_c, 2),
                                  mensuels=mensuels(rets_c),
                                  monte_carlo=monte_carlo(rets_c, pnl_tr, cap) if len(rets_c) >= MC_JOURS_MIN else None,
                                  correlation=dict(noms=list(corr.columns), m=[[_js(v) for v in row] for row in corr.to_numpy()]) if len(corr) else None,
                                  correlation_glissante=roul, **mesures(rets_c))
        out["strategies"] = [dict(nom=r["nom"], instrument=r["instrument"], source_prix=r["source_prix"], capital=r["capital"],
                                  equity=_serie(r["equity"], 2), stats_portefeuille=r["stats_pf"], stats_trades=r["stats_trades"],
                                  **mesures(r["rets"])) for r in resultats]
        out["trades"] = sorted([t for r in resultats for t in r["trades"]], key=lambda t: t["entree"])
        out["ordres_simules"] = sorted([o for r in resultats for o in r["ordres"]], key=lambda o: o["t"])
        par_source: dict[str, list] = {}
        for r in resultats:
            par_source.setdefault(r["source_prix"], []).extend(r["trades"])
        annees: dict[str, list] = {}
        for i, trs in par_source.items():
            for annee, jours_ in fenetres_intrajour(prix[i], trs).items():
                f = os.path.join(sortie, f"groupe_prix_{i}_{annee}.json")
                with open(f + ".tmp", "w", encoding="utf-8") as fh:
                    json.dump(jours_, fh, separators=(",", ":"))
                os.replace(f + ".tmp", f)
                annees.setdefault(i, []).append(annee)
        out["prix_intrajour"] = annees
    ny = lambda t: pd.Timestamp(int(t), unit="ms", tz="UTC").tz_convert(NY).strftime("%Y-%m-%d %H:%M:%S")
    out["demo"] = dict(cibles=[dict(x, heure_et=ny(x["t"]), qty=x.get("cible"), ref=x.get("strategie"), instrument=x.get("strategie")) for x in decisions if "t" in x],
                       ordres=[], executions=[dict(x, heure_et=ny(x["t"])) for x in sorted(executions, key=lambda x: x.get("t", 0)) if "t" in x])
    os.makedirs(sortie, exist_ok=True)
    f = os.path.join(sortie, "groupe.json")
    with open(f + ".tmp", "w", encoding="utf-8") as fh:
        json.dump(out, fh, ensure_ascii=False, separators=(",", ":"), default=_js)
    os.replace(f + ".tmp", f)
    log(f"[rapport] ecrit : {f} ({len(out.get('trades', []))} trades, {len(erreurs)} erreur(s))")
    for e in erreurs + notes:
        log(f"[rapport] {e}")
    return out


def main(argv=None) -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(prog="python -m nexus.live.rapport")
    ap.add_argument("--groupe", default=GROUPE_NT, help="dossier Nexus\\groupe de NinjaTrader")
    ap.add_argument("--sortie", default=SORTIE)
    a = ap.parse_args(argv)
    construire(a.groupe, a.sortie)


if __name__ == "__main__":
    main()
