"""Strategies du runner local (nexus/perso/runner.py) dans le tableau de bord : memes objets vectorbt, memes tests.

Chaque strategie testee en local a laisse ses trades (resultats/perso_*/trades_*.csv) et sa courbe de capital
(equity_*.csv). On en refait les ORDRES (entree et sortie de chaque trade, aux prix executes par le moteur, frais
= P&L brut - P&L net) et on les rejoue dans vbt.Portfolio.from_orders, comme le rejeu de S1 (tableau._replay_1col) :
la fiche JSON est ensuite construite par les memes blocs que les strategies du tableau (bloc_vectorbt, bloc_series,
bloc_trades, bloc_tests_communs, bloc_surajustement, _kpi).

Unites : quantite x valeur du point (futures), x 1 (actions, ETF, crypto) : le P&L vectorbt d un trade est le P&L
brut du moteur, a l euro pres. Valorisation : une fois par seance, a 17:00 heure de New York (fin de la seance CME,
la convention du moteur) ; une position tenue plusieurs jours est valorisee au cours de cloture des memes donnees
que son moteur (futures minute du depot, barres journalieres de nexus.data) ; sans donnees (options synthetiques
de la fiche 11), elle ne l est qu a la sortie (signale dans le test de comptabilite).
"""
from __future__ import annotations

import math
import os
import re
import warnings

import numpy as np
import pandas as pd

from . import tableau as TB

ET = "America/New_York"
NS_US = 1_000                                   # 1 microseconde : decalage des ordres qui tombent au meme instant


# =============================================================================
#  Trades du runner -> forme commune
# =============================================================================
def _mult_candidats(root: str) -> list[float]:
    from .perso.qf import INSTRUMENTS
    v = sorted({i.point_value for i in INSTRUMENTS.values() if i.root == root})
    return v or [1.0]


def normaliser(t: pd.DataFrame, spec: dict) -> pd.DataFrame:
    """Trades d un des formats du runner -> colonnes inst, sens, qty, mult, t_in, t_out, p_in, p_out, pnl, frais.
    mult = valeur du point ($ par point et par unite de qty) ; frais = P&L brut - P&L net (>= 0 a l arrondi pres)."""
    from .perso.qf import INSTRUMENTS
    k = spec["kind"]
    if "net_pnl" in t.columns:                                          # moteur nexus (fiches)
        n = pd.DataFrame(dict(inst=t["symbol"].astype(str), sens=t["direction"].astype(float), qty=t["max_qty"].abs().astype(float),
                              t_in=pd.to_datetime(t["entry_time"]), t_out=pd.to_datetime(t["exit_time"]),
                              p_in=t["entry_price"].astype(float), p_out=t["exit_price"].astype(float),
                              pnl=t["net_pnl"].astype(float), frais=t["costs"].astype(float)))
        # le moteur nexus redimensionne les positions en cours de trade (max_qty = taille maximale) : la valeur du point
        # de chaque trade est celle qui redonne son P&L brut exact (mediane de l instrument si le prix n a pas bouge)
        dp = n["sens"] * n["qty"] * (n["p_out"] - n["p_in"])
        m = (t["gross_pnl"].astype(float) / dp).where(dp.abs() > 1e-12)
        med = m.groupby(n["inst"]).transform("median")
        n["mult"] = m.where(m.notna() & np.isfinite(m), med).fillna(1.0)
        return n
    sens = t["direction"] if "direction" in t.columns else t["sens"]
    n = pd.DataFrame(dict(inst=t["instrument"].astype(str).str.upper(), sens=sens.astype(float), qty=t["qty"].abs().astype(float),
                          t_in=pd.to_datetime(t["entry_time"]), t_out=pd.to_datetime(t["exit_time"]),
                          p_in=t["entry_price"].astype(float), p_out=t["exit_price"].astype(float), pnl=t["pnl"].astype(float)))
    dp = n["sens"] * n["qty"] * (n["p_out"] - n["p_in"])
    if k in ("qf", "user"):
        n["mult"] = INSTRUMENTS[spec["inst"]].point_value
    elif k == "pairs":
        n["mult"] = 10000.0
    else:                                                               # or, fx, gotobi, orderflow : micro ou standard
        n["mult"] = 1.0
        for inst, g in n.groupby("inst"):
            c = _mult_candidats(inst)
            err = [float(np.nanmedian(np.abs(dp[g.index] * x - n.loc[g.index, "pnl"]) / n.loc[g.index, "qty"])) for x in c]
            n.loc[g.index, "mult"] = c[int(np.argmin(err))]
    n["frais"] = dp * n["mult"] - n["pnl"]
    return n


# =============================================================================
#  Ordres -> vbt.Portfolio
# =============================================================================
def instants_seance(debut, fin) -> tuple[pd.DatetimeIndex, pd.DatetimeIndex]:
    """Jours ouvres et instant de valorisation de chacun (17:00 New York, fin de la seance CME), en UTC naif."""
    jours = pd.bdate_range(pd.Timestamp(debut).normalize(), pd.Timestamp(fin).normalize() + pd.Timedelta(days=3))
    loc = (jours + pd.Timedelta(hours=17)).tz_localize(ET).tz_convert("UTC").tz_localize(None)
    return jours, pd.DatetimeIndex(loc).as_unit("ns")


def ordres(n: pd.DataFrame) -> pd.DataFrame:
    """Deux ordres par trade, ranges : a un meme instant, les sorties de trades plus anciens d abord, puis les entrees,
    puis les sorties des trades ouverts et fermes a cet instant ; instants rendus uniques (+1 microseconde)."""
    ent = pd.DataFrame(dict(t=n["t_in"], inst=n["inst"], size=n["sens"] * n["qty"] * n["mult"], px=n["p_in"], fee=n["frais"] / 2,
                            prio=1, k=n.index))
    zero = (n["t_out"] <= n["t_in"]).to_numpy()
    sor = pd.DataFrame(dict(t=np.where(zero, n["t_in"], n["t_out"]), inst=n["inst"], size=-n["sens"] * n["qty"] * n["mult"],
                            px=n["p_out"], fee=n["frais"] / 2, prio=np.where(zero, 2, 0), k=n.index))
    o = pd.concat([ent, sor], ignore_index=True).sort_values(["t", "prio", "k"], kind="stable").reset_index(drop=True)
    t = pd.DatetimeIndex(o["t"]).as_unit("ns")
    rang = o.groupby(t.asi8).cumcount().to_numpy()
    o["t"] = pd.DatetimeIndex(t.asi8 + rang * NS_US).as_unit("ns")
    return o


def portefeuille(n: pd.DataFrame, capital: float, marques: dict | None = None):
    """-> (pf vectorbt, matelas de liquidites, valeur journaliere en $ indexee par seance)."""
    vbt = TB.vbt
    o = ordres(n)
    cols = sorted(o["inst"].unique())
    jours, inst = instants_seance(o["t"].min(), o["t"].max())
    idx = pd.DatetimeIndex(np.union1d(o["t"].to_numpy(), inst.to_numpy())).as_unit("ns")
    size = pd.DataFrame(np.nan, index=idx, columns=cols)
    price, fees = size.copy(), pd.DataFrame(0.0, index=idx, columns=cols)
    close = size.copy()
    for c, g in o.groupby("inst"):
        size.loc[pd.DatetimeIndex(g["t"]), c] = g["size"].to_numpy()
        price.loc[pd.DatetimeIndex(g["t"]), c] = g["px"].to_numpy()
        fees.loc[pd.DatetimeIndex(g["t"]), c] = g["fee"].to_numpy()
        m = (marques or {}).get(c)
        if m is not None and len(m):
            mt = pd.DatetimeIndex(m.index).as_unit("ns").asi8
            j = np.searchsorted(mt, idx.asi8, side="right") - 1
            frais_ok = (j >= 0) & (idx.asi8 - mt[np.clip(j, 0, None)] <= 4 * 86_400_000_000_000)
            close[c] = np.where(frais_ok, m.to_numpy()[np.clip(j, 0, None)], np.nan)
        close[c] = close[c].fillna(price[c])
    close = close.ffill().bfill()
    # matelas : la valeur notionnelle des positions ouvertes ne doit jamais manquer de liquidites dans vectorbt
    pos = size.fillna(0.0).cumsum()
    buf = float((pos.abs() * close).sum(axis=1).max() * 2 + capital)
    pf = vbt.Portfolio.from_orders(close, size=size, price=price, fixed_fees=fees, size_type="amount", direction="both",
                                   init_cash=capital + buf, cash_sharing=True, group_by=True, freq="1min")
    v = pf.value() - buf
    daily = v.reindex(inst, method="ffill")
    daily.index = jours
    return pf, buf, daily


# =============================================================================
#  Donnees de valorisation (positions tenues d une seance a l autre)
# =============================================================================
_CACHE: dict = {}


def _journalier_nexus() -> dict:
    if "nexus" not in _CACHE:
        from . import data as D
        from .perso import qf
        _CACHE["nexus"] = {s: df["close"] for s, df in D.load_folder(qf.QUOTES).items()}
    return _CACHE["nexus"]


def _crypto() -> dict:
    if "crypto" not in _CACHE:
        from . import data as D
        from .perso import qf
        _CACHE["crypto"] = {s: df["close"] for s, df in D.load_folder(os.path.join(qf.QUOTES, "alpaca", "crypto_15min"), daily=False,
                                                                      intraday_minutes=15).items()}
    return _CACHE["crypto"]


def marques(n: pd.DataFrame, spec: dict) -> tuple[dict | None, str]:
    """Cours de valorisation des instruments tenus a 17:00 New York, avec les donnees du moteur de la strategie."""
    seance = lambda s: (s.dt.tz_localize("UTC").dt.tz_convert(ET) + pd.Timedelta(hours=6)).dt.normalize()   # seance CME
    nuit = float((seance(n["t_in"]) != seance(n["t_out"])).mean()) if len(n) else 0.0
    if nuit == 0.0:
        return None, "positions toutes soldees avant 17:00 New York : valorisation exacte aux prix des trades"
    k = spec["kind"]
    if k == "nexus":
        if "crypto" in str(spec) or n["inst"].str.endswith("USD").all():
            src = _crypto()
        else:
            src = _journalier_nexus()
        m = {i: src[i] for i in n["inst"].unique() if i in src}
        manq = sorted(set(n["inst"].unique()) - set(m))
        txt = f"{nuit:.0%} des trades tenus d une seance a l autre, valorises au cours de cloture des donnees du moteur"
        return m, txt + (f" ; sans cours pour {len(manq)} instrument(s) ({', '.join(manq[:3])}...) : valorises a la sortie" if manq else "")
    if k in ("qf", "user"):
        from .perso.qf import alpaca_minutes, futures_minutes
        m = {}
        for i in n["inst"].unique():
            try:
                df = alpaca_minutes(i) if i in ("SPY", "IWM") else futures_minutes(i)
                m[i] = df["close"]
            except Exception:                                            # noqa: BLE001 (donnees absentes)
                pass
        return m, f"{nuit:.0%} des trades tenus d une seance a l autre, valorises aux minutes du moteur"
    return None, f"{nuit:.0%} des trades tenus d une seance a l autre, valorises a la sortie seulement"


# =============================================================================
#  Fiche
# =============================================================================
def _ident(nom: str) -> str:
    return "R_" + re.sub(r"[^A-Za-z0-9]+", "_", nom).strip("_")[:60]


def charger(nom: str):
    from .perso.portefeuille import _latest
    ft, fe = _latest("trades", nom), _latest("equity", nom)
    t = pd.read_csv(ft) if ft and os.path.getsize(ft) > 5 else None
    eq = None
    if fe:
        eq = pd.read_csv(fe, index_col=0, parse_dates=True).iloc[:, 0]
        eq.index = pd.DatetimeIndex(eq.index).normalize()
        eq = eq.groupby(level=0).last()
    return t, eq


def fiche_runner(nom: str, src: str, spec: dict, note: str, ligne: dict, essais: int, n_sim: int, log=print) -> tuple[dict, pd.Series] | None:
    """Fiche au format du tableau de bord pour une strategie du runner (None si elle n a ni trades ni courbe)."""
    t, eq = charger(nom)
    if eq is None or float(eq.diff().abs().sum()) == 0.0:                 # jamais lancee, ou aucun trade
        return None
    capital = float(eq.iloc[0])
    pnl_moteur = eq.diff().fillna(0.0)
    dd_usd = float((eq.cummax() - eq).max())
    cap_ref = max(capital, 1.5 * dd_usd)
    note_cap = "" if cap_ref == capital else (f" ; le backtest a {capital:,.0f} $ perd jusqu a {dd_usd:,.0f} $ : capital de calcul porte a "
                                              f"{cap_ref:,.0f} $ pour garder des rendements definis").replace(",", " ")
    tests, permanent = [], bool(spec.get("permanent", False))
    if t is not None and "entry_time" in t.columns and len(t):
        n = normaliser(t, spec)
        courbe_moteur = spec["kind"] == "nexus"
        if courbe_moteur:      # positions redimensionnees en cours de trade : valorisation journaliere par le moteur
            mq, txt_marq = None, ("le moteur nexus redimensionne ses positions en cours de trade et le fichier ne garde que la taille "
                                  "maximale : chaque trade est rejoue a son P&L exact, mais la courbe journaliere (valorisation des "
                                  "positions ouvertes) est celle du moteur")
        else:
            mq, txt_marq = marques(n, spec)
        pf, buf, daily = portefeuille(n, cap_ref, mq)
        fin_vbt = float(np.asarray(pf.value(), float).ravel()[-1] - buf)
        if courbe_moteur:
            daily = (eq - capital + cap_ref).reindex(daily.index, method="ffill").fillna(cap_ref)
        tr = pf.trades.records_readable
        ecart_total = fin_vbt - cap_ref - float(n["pnl"].sum())
        tests.append(dict(famille="Comptabilite", test="Rejeu vectorbt des trades du moteur",
                          resultat="identique" if abs(ecart_total) < 1e-6 * max(1.0, abs(n["pnl"].sum())) + 0.01 else "ECART",
                          detail=f"{len(n)} trades rejoues (ordres aux prix executes, frais = brut - net) ; ecart du P&L total "
                                 f"{ecart_total:+.2f} $ ; frais moyens {n['frais'].mean():.2f} $ par trade",
                          verdict="ok" if abs(ecart_total) < 1.0 + 1e-6 * abs(n["pnl"].sum()) else "alerte"))
        if (n["frais"] < -0.01 * n["qty"]).mean() > 0.01:
            tests.append(dict(famille="Comptabilite", test="Frais negatifs", resultat=f"{(n['frais'] < 0).mean():.0%} des trades",
                              detail="P&L net superieur au brut recalcule : valeur du point mal reconnue", verdict="alerte"))
        tests.append(dict(famille="Comptabilite", test="Valorisation des positions", resultat="17:00 New York chaque seance",
                          detail=txt_marq, verdict="info"))
        fuseau = None if "net_pnl" in t.columns else "UTC"
    else:                                                                # pas de trades exploitables (S20 : P&L journalier)
        n = None
        v = cap_ref + pnl_moteur.cumsum()
        close = pd.DataFrame({"P&L": v.to_numpy()}, index=pd.DatetimeIndex(v.index) + pd.Timedelta(hours=21))
        size = pd.DataFrame({"P&L": np.r_[1.0, np.zeros(len(v) - 1)]}, index=close.index)
        pf = TB.vbt.Portfolio.from_orders(close, size=size, size_type="amount", init_cash=float(v.iloc[0]), freq="1D")
        buf = 0.0
        daily = pd.Series(np.asarray(pf.value(), float).ravel(), index=v.index)
        tests.append(dict(famille="Comptabilite", test="Rejeu vectorbt", resultat="P&L journalier",
                          detail="le runner n a garde que le P&L journalier (portefeuille permanent) : une position unique sur la "
                                 "courbe de capital", verdict="info"))
        fuseau = None
        permanent = True
    cal = TB.calendrier(daily.index[0], min(daily.index[-1], pd.Timestamp("2026-08-28")))
    valeur = daily.reindex(cal, method="ffill").ffill().bfill()
    r = valeur.pct_change().fillna(0.0)
    rows, td = TB.bloc_trades(pf, fuseau, ET, pf.value() - buf)
    insts = sorted(n["inst"].unique()) if n is not None else []
    if len(insts) > 1 and "Column" in td.columns:                       # strategie a plusieurs instruments
        for row, c in zip(rows, td["Column"]):
            row["actif"] = str(c)
    d_eq = eq.reindex(cal, method="ffill").ffill().bfill()
    corr = float(valeur.diff().corr(d_eq.diff())) if len(cal) > 20 else math.nan
    if not (n is not None and spec["kind"] == "nexus"):
        tests.append(dict(famille="Comptabilite", test="Courbe vectorbt contre courbe du moteur", resultat=f"correlation {corr:.3f}",
                          detail="variations journalieres ; un ecart vient de la date de rattachement des trades de nuit (seance CME / "
                                 "jour calendaire) ou de la valorisation des positions de plusieurs jours", verdict="ok" if corr > 0.95 else "info"))
    tc, mc = TB.bloc_tests_communs(r, td, "2021-01-01", essais, TB.VAR_SHARPE_PROGRAMME, n_sim, libelle="coupure du 01/01/2021")
    ts, so = TB.bloc_surajustement(r, None, None, essais, reps=n_sim)
    tests += tc + ts
    verdict = ligne.get("verdict") or "PAS ENCORE LANCEE"
    from .perso.portefeuille import _is_futures
    from .perso.tableau import SURTOUT_BETA
    beta = SURTOUT_BETA.get(nom)
    fiche = dict(
        id=_ident(nom), code=None, titre=nom, statut="testee", valide_le=None, verdict_runner=verdict,
        resume=(note or "") + (f" · Fichier {src}." if src else "") + (f" · A savoir : surtout du beta ({beta})." if beta else ""),
        instruments=insts, futures=bool(_is_futures(spec)),
        fonctionnement=[x for x in [f"Programme : {src}." if src else None, f"Donnees du backtest : {ligne.get('donnees', '')}." if ligne.get("donnees") else None,
                                    f"Periode : {ligne.get('periode', '')}." if ligne.get("periode") else None,
                                    f"Verdict du runner : {verdict}.", note or None] if x],
        pourquoi="Strategie de la recherche locale (nexus/perso/runner.py) : voir le programme d origine et Python/recherche/.",
        sources=[], parametres={k: TB._js(v) for k, v in (spec.get("params") or {}).items()},
        donnees=dict(source=ligne.get("donnees", ""), periode=ligne.get("periode", ""), moteur=spec["kind"],
                     calendrier="seances NYSE (feries exclus), valorisation a 17:00 New York"),
        capital=dict(initial=cap_ref, unite="$", note=f"capital du backtest {capital:,.0f} $, taille fixe du moteur".replace(",", " ") + note_cap),
        fuseau_trades=ET, publication=None, permanent=permanent,
        kpi=TB._kpi(valeur, td) if len(td) else TB._kpi_sans_trades(valeur),
        vectorbt=TB.bloc_vectorbt(pf, valeur), series=TB.bloc_series(valeur), trades=rows, tests=tests, monte_carlo=mc,
        surajustement=so)
    return fiche, r
