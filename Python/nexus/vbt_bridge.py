"""Pont vectorbt :
  1. to_portfolio(res) : rejoue les executions du moteur dans un vbt.Portfolio (3 pas par jour :
     ouverture, intrajournalier pour stops/limites, cloture) -> statistiques, trades, graphiques ;
     l equity vectorbt est comparee a celle du moteur (controle croise de la comptabilite).
  2. html_report(res, chemin) : graphique interactif (equity, drawdowns, exposition) en HTML.
  3. Grilles de recherche rapides et vectorisees (signal seul, sans module B) pour les fiches 1 et 2 :
     tsmom_grid / xsmom_grid -> metriques par configuration + matrice de rendements pour PBO.
"""
from __future__ import annotations

import itertools

import numpy as np
import pandas as pd

from . import mathx as M
from . import validation as V

try:
    import vectorbt as vbt
except ImportError:  # pragma: no cover
    vbt = None


def _need_vbt():
    if vbt is None:
        raise ImportError("vectorbt n est pas installe : pip install -r requirements.txt")


# =============================================================================
#  1. Rejeu exact des executions
# =============================================================================
def to_portfolio(res):
    """Construit un vbt.Portfolio a partir des fills du moteur. -> (pf, valeur_journaliere, ecart_max_relatif)."""
    _need_vbt()
    st = res.strategy
    traded = [s for s in st.syms if s.traded]
    names = [s.name for s in traded]
    days = pd.DatetimeIndex(st.master.normalize().unique())
    t_open, t_mid, t_close = pd.Timedelta(hours=9, minutes=30), pd.Timedelta(hours=12), pd.Timedelta(hours=16)
    idx = pd.DatetimeIndex(np.sort(np.concatenate([(days + t_open).values, (days + t_mid).values, (days + t_close).values])))
    close = pd.DataFrame(np.nan, index=idx, columns=names)
    for s in traded:
        h = s.hist
        d = pd.DatetimeIndex(h.dates).normalize()
        close.loc[d + t_open, s.name] = h.open
        close.loc[d + t_mid, s.name] = h.close
        close.loc[d + t_close, s.name] = h.close
    close = close.ffill().bfill()
    size = pd.DataFrame(np.nan, index=idx, columns=names)
    price = pd.DataFrame(np.nan, index=idx, columns=names)
    fees = pd.DataFrame(0.0, index=idx, columns=names)
    opens = {s.name: pd.Series(s.hist.open, index=pd.DatetimeIndex(s.hist.dates).normalize()) for s in traded}
    fx_note = any(s.inst.currency != "USD" or s.inst.point_value != 1.0 for s in traded)
    if len(res.fills):
        f = res.fills.copy()
        f["day"] = pd.to_datetime(f["time"]).dt.normalize()
        f["is_open"] = [abs(px - opens[sym].get(dy, np.nan)) < 1e-12 and reason != "stop"
                        for sym, dy, px, reason in zip(f["symbol"], f["day"], f["price"], f["reason"])]
        f["ts"] = f["day"] + pd.to_timedelta(np.where(f["is_open"], t_open.value, t_mid.value))
        g = f.groupby(["ts", "symbol"])
        agg = pd.DataFrame({"qty": g["qty"].sum(), "notional": g.apply(lambda x: (x["qty"] * x["price"]).sum()),
                            "cost": g["cost"].sum(), "px": g["price"].last()})
        for (ts, sym), r in agg.iterrows():
            q = r["qty"]
            size.at[ts, sym] = q
            price.at[ts, sym] = r["notional"] / q if q != 0 else r["px"]
            fees.at[ts, sym] = r["cost"]
    init = float(st.p.initial_bankroll)
    kw = dict(size=size, price=price, fixed_fees=fees, size_type="amount", direction="both", cash_sharing=True,
              group_by=True, call_seq="auto", allow_partial=False, freq="8h")
    pf = vbt.Portfolio.from_orders(close, init_cash=init, **kw)
    value = pf.value()
    daily = value[value.index.isin(days + t_close)]
    daily.index = daily.index.normalize()
    eq = res.equity.reindex(daily.index).dropna()
    diff = float(np.nanmax(np.abs(daily.reindex(eq.index) / eq - 1))) if len(eq) else M.NAN
    if M.ok(diff) and diff > 1e-6:
        # Levier (> 100 % investi) : le cash vectorbt est insuffisant -> on ajoute un tampon puis on le retire.
        buf = init * 20
        pf = vbt.Portfolio.from_orders(close, init_cash=init + buf, **kw)
        value = pf.value() - buf
        daily = value[value.index.isin(days + t_close)]
        daily.index = daily.index.normalize()
        diff = float(np.nanmax(np.abs(daily.reindex(eq.index) / eq - 1))) if len(eq) else M.NAN
    pf.nexus_fx_note = fx_note
    return pf, daily.rename("valeur_vectorbt"), diff


def intraday_portfolio(res):
    """Rejeu vectorbt d un backtest minute (fiche 16) : une ligne par minute de seance des jours trades,
    deux colonnes a cash partage (executions a l ouverture / a la cloture de la barre) car vectorbt
    n accepte qu un ordre par barre et par colonne. -> (pf, valeur_journaliere, ecart_max_relatif)."""
    _need_vbt()
    g, f = res.grid, res.fills
    pv = float(res.point_value)
    init = float(res.strategy.p.initial_bankroll)
    if f is None or len(f) == 0:
        return None, res.equity.rename("valeur_vectorbt"), 0.0
    t = pd.DatetimeIndex(f["time"])
    day = t.normalize()
    rel = ((t - day) / pd.Timedelta(minutes=1)).to_numpy().astype(int) - (9 * 60 + 30)
    pos = g.days.get_indexer(day)
    at_open = (f["moment"] == "ouverture").to_numpy()
    slot = np.where(at_open, rel, rel - 1)          # ouverture de la barre s datee s ; cloture datee s + 1
    px = f["price"].to_numpy(float)
    tdays = np.unique(pos)
    rows = []
    for d in tdays:
        n = int(g.last_slot[d]) + 1
        rows.append(pd.DataFrame({"close": g.c[d, :n]}, index=g.timestamps(d, np.arange(n))))
    close1 = pd.concat(rows)["close"]
    close = pd.DataFrame({"ouverture": close1, "cloture": close1})
    size = pd.DataFrame(np.nan, index=close.index, columns=close.columns)
    price = size.copy()
    fees = pd.DataFrame(0.0, index=close.index, columns=close.columns)
    ts = g.days[pos] + pd.to_timedelta(9 * 60 + 30 + slot + 1, unit="min")
    for tsi, col, q, p_, c_ in zip(ts, np.where(at_open, "ouverture", "cloture"), f["qty"].to_numpy(float), px, f["cost"].to_numpy(float)):
        size.at[tsi, col] = q * pv
        price.at[tsi, col] = p_
        fees.at[tsi, col] = c_
    buf = init * 50
    pf = vbt.Portfolio.from_orders(close, size=size, price=price, fixed_fees=fees, size_type="amount", direction="both",
                                   cash_sharing=True, group_by=True, call_seq="auto", init_cash=init + buf, freq="1min")
    value = pf.value() - buf
    ends = pd.DatetimeIndex([g.timestamps(d, [int(g.last_slot[d])])[0] for d in tdays])
    daily = value.reindex(ends)
    daily.index = ends.normalize()
    eq = res.equity.reindex(daily.index)
    diff = float(np.nanmax(np.abs(daily / eq - 1))) if len(eq) else M.NAN
    # jours sans execution : equity inchangee (aucune position la nuit)
    full = daily.reindex(res.equity.index).ffill().fillna(init)
    return pf, full.rename("valeur_vectorbt"), diff


def daily_stats(daily_value: pd.Series) -> pd.Series:
    """Statistiques vectorbt sur une serie de valeurs journalieres (252 jours/an)."""
    _need_vbt()
    import warnings
    rets = daily_value.pct_change().dropna()
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return rets.vbt.returns(freq="1D", year_freq="252 days").stats()


def html_report(res, path: str) -> str:
    """Ecrit un graphique HTML interactif : equity moteur vs vectorbt, drawdown, exposition brute."""
    _need_vbt()
    from plotly.subplots import make_subplots
    import plotly.graph_objects as go
    pf, daily, diff = intraday_portfolio(res) if getattr(res, "intraday", False) else to_portfolio(res)
    eq = res.equity
    dd = eq / eq.cummax() - 1
    fig = make_subplots(rows=3, cols=1, shared_xaxes=True, row_heights=[0.55, 0.25, 0.20], vertical_spacing=0.04,
                        subplot_titles=(f"{res.name} - equity (moteur) et rejeu vectorbt (ecart max {diff:.2e})",
                                        "Drawdown", "Exposition brute (fraction de l equity)"))
    fig.add_trace(go.Scatter(x=eq.index, y=eq.values, name="equity moteur", line=dict(width=2)), 1, 1)
    fig.add_trace(go.Scatter(x=daily.index, y=daily.values, name="rejeu vectorbt", line=dict(width=1, dash="dot")), 1, 1)
    fig.add_trace(go.Scatter(x=dd.index, y=dd.values, name="drawdown", fill="tozeroy", line=dict(width=1)), 2, 1)
    if getattr(res, "exposure", None) is not None:
        fig.add_trace(go.Scatter(x=res.exposure.index, y=res.exposure.values, name="exposition", line=dict(width=1)), 3, 1)
    fig.update_layout(height=900, template="plotly_white", legend=dict(orientation="h"))
    fig.update_yaxes(tickformat=".0%", row=2, col=1)
    fig.update_yaxes(tickformat=".0%", row=3, col=1)
    fig.write_html(path, include_plotlyjs="cdn")
    return path


# =============================================================================
#  3. Grilles de recherche vectorisees (signal seul)
# =============================================================================
def _panel(data: dict, symbols: list[str]):
    cols = [s for s in symbols if s in data]
    close = pd.DataFrame({s: data[s]["close"] for s in cols}).sort_index()
    opn = pd.DataFrame({s: data[s]["open"] for s in cols}).reindex(close.index)
    return close, opn


def _month_end_mask(index: pd.DatetimeIndex) -> np.ndarray:
    m = index.to_period("M")
    return np.r_[m[1:] != m[:-1], True]


def tsmom_weights(close: pd.DataFrame, lookback=252, skip=21, use_vol_scaling=True, target_vol=0.12, vol_window=126) -> pd.DataFrame:
    """Poids cibles TSMOM (fiche 1, sans module B) decides le dernier jour du mois."""
    sig = close.shift(skip) / close.shift(lookback) - 1
    vol = np.log(close / close.shift(1)).rolling(vol_window).std() * np.sqrt(252)
    valid = sig.notna() & vol.notna()
    n = valid.sum(axis=1).replace(0, np.nan)
    w = (target_vol / vol).div(n, axis=0) if use_vol_scaling else valid.astype(float).div(n, axis=0)
    w = w.where(sig > 0, 0.0).where(valid)
    w[~_month_end_mask(close.index)] = np.nan
    return w


def xsmom_weights(close: pd.DataFrame, lookback=252, skip=21, top=None, target_vol=0.12, vol_window=126, max_basket=0.5) -> pd.DataFrame:
    """Poids cibles XSMOM (fiche 2, sans tampon ni module B) : top quartile a poids egal, panier a vol cible."""
    sig = close.shift(skip) / close.shift(lookback) - 1
    lr = np.log(close / close.shift(1))
    w = pd.DataFrame(np.nan, index=close.index, columns=close.columns)
    me = np.where(_month_end_mask(close.index))[0]
    for i in me:
        sc = sig.iloc[i].dropna()
        if len(sc) < 4:
            continue
        k = top or max(1, int(round(len(sc) / 4)))
        sel = sc.sort_values(ascending=False).index[:k]
        hist = lr[sel].iloc[max(0, i - vol_window + 1): i + 1].fillna(0.0)
        bvol = float(hist.mean(axis=1).std() * np.sqrt(252)) if len(hist) > 10 else np.nan
        expo = max_basket if not (bvol > 1e-6) else min(max_basket, target_vol / bvol)
        row = pd.Series(0.0, index=close.columns)
        row[sel] = expo / k
        w.iloc[i] = row
    return w


def run_weights(close: pd.DataFrame, opn: pd.DataFrame, weights: pd.DataFrame, fees=0.0005, init_cash=100000.0):
    """Execute des poids cibles decides a la cloture a l ouverture suivante (vectorbt, target percent)."""
    _need_vbt()
    size = weights.shift(1)
    return vbt.Portfolio.from_orders(close, size=size, size_type="targetpercent", price=opn.fillna(close), fees=fees,
                                     init_cash=init_cash, cash_sharing=True, group_by=True, call_seq="auto", freq="1D")


def grid(data: dict, symbols: list[str], kind: str = "tsmom", start=None, end=None, **ranges):
    """Grille vectorisee. ranges : listes de valeurs (lookback=[63,126,252], skip=[0,21]...).
    -> (DataFrame de metriques, DataFrame des rendements journaliers par configuration, (pbo, combos))."""
    close, opn = _panel(data, symbols)
    if start is not None:
        close, opn = close[close.index >= pd.Timestamp(start)], opn[opn.index >= pd.Timestamp(start)]
    if end is not None:
        close, opn = close[close.index <= pd.Timestamp(end)], opn[opn.index <= pd.Timestamp(end)]
    keys = list(ranges)
    rows, rets = [], {}
    for combo in itertools.product(*[ranges[k] for k in keys]):
        kw = dict(zip(keys, combo))
        w = tsmom_weights(close, **kw) if kind == "tsmom" else xsmom_weights(close, **kw)
        pf = run_weights(close, opn, w)
        r = pf.returns()
        label = ",".join(f"{k}={v}" for k, v in kw.items())
        rets[label] = r
        val = pf.value()
        rows.append(dict(config=label, **kw, rendement_total=float(val.iloc[-1] / val.iloc[0] - 1),
                         sharpe=V.annualized_sharpe(r.values), dd_max=V.max_drawdown(val.values),
                         trades=int(pf.trades.count())))
    table = pd.DataFrame(rows).sort_values("sharpe", ascending=False)
    rmat = pd.DataFrame(rets)
    pbo_val = V.pbo(rmat.T.values) if rmat.shape[1] >= 2 else (M.NAN, 0)
    return table, rmat, pbo_val
