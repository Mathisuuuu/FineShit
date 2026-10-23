"""Moteurs de signaux partages (port de NexusSignals.cs) : momentum 12-1, etat de panique,
selection avec tampon, stop ATR, residus, moteur multi-facteurs (fiche 3)."""
from __future__ import annotations

import math

import numpy as np

from . import data as D
from . import mathx as M


# --- Momentum ---------------------------------------------------------------
def return_12_1(h: D.History, lookback: int = 252, skip: int = 21) -> float:
    if h is None or h.count <= lookback:
        return M.NAN
    return h.return_over(lookback, skip)


def inverse_vol_weight(h: D.History, target_vol: float, vol_window: int, n_assets: int, max_weight: float) -> float:
    vol = h.realized_vol(vol_window) if h is not None else M.NAN
    if not M.ok(vol) or vol <= 1e-6 or n_assets <= 0:
        return M.NAN
    w = target_vol / vol / n_assets
    return min(w, max_weight) if max_weight > 0 else w


# --- Etat de panique (Daniel-Moskowitz) --------------------------------------
def panic_state(spy: D.History, lookback_days: int, vol_days: int, median_days: int):
    """Barometre sous son niveau d il y a 24 mois ET vol 1 mois > sa mediane 1 an. -> (bool, detail)."""
    if spy is None or spy.count < max(lookback_days, median_days + vol_days) + 2:
        return False, "panique: historique insuffisant"
    now, then = spy.last_close, spy.close_ago(lookback_days)
    below = now < then
    rets = spy.returns(median_days + vol_days)
    if rets.size >= vol_days:
        win = np.lib.stride_tricks.sliding_window_view(rets, vol_days)
        vols = win.std(axis=1, ddof=1)
    else:
        vols = np.array([])
    cur = float(vols[-1]) if vols.size else M.NAN
    med = M.median(vols[-median_days:]) if vols.size else M.NAN
    high = M.ok(cur) and M.ok(med) and cur > med
    detail = (f"SPY {now:.2f} vs {then:.2f} il y a {lookback_days}j ; vol1m {cur * math.sqrt(252):.1%} "
              f"vs mediane {med * math.sqrt(252):.1%}") if M.ok(cur) and M.ok(med) else ""
    return below and high, detail


# --- Selection avec tampon ----------------------------------------------------
def select_with_buffer(scores: dict, held, top: int, buffer: int) -> list[str]:
    ranked = [k for k, v in sorted(((k, v) for k, v in scores.items() if M.ok(v)), key=lambda kv: -kv[1])]
    keep = [ranked[i] for i in range(min(len(ranked), buffer)) if held and ranked[i] in held]
    for s in ranked:
        if len(keep) >= top:
            break
        if s not in keep:
            keep.append(s)
    return keep


def rank_of(scores: dict, symbol: str) -> int:
    ranked = [k for k, v in sorted(((k, v) for k, v in scores.items() if M.ok(v)), key=lambda kv: -kv[1])]
    return ranked.index(symbol) + 1 if symbol in ranked else 1 << 30


# --- Stop ATR -----------------------------------------------------------------
def atr_stop_distance(price, atr, mult, min_pct, max_pct) -> float:
    if not M.ok(price) or price <= 0:
        return M.NAN
    d = atr * mult if M.ok(atr) and atr > 0 else max_pct * price
    return M.clamp(d, min_pct * price, max_pct * price)


def long_stop(price, atr, mult, min_pct, max_pct) -> float:
    d = atr_stop_distance(price, atr, mult, min_pct, max_pct)
    return price - d if M.ok(d) else M.NAN


def short_stop(price, atr, mult, min_pct, max_pct) -> float:
    d = atr_stop_distance(price, atr, mult, min_pct, max_pct)
    return price + d if M.ok(d) else M.NAN


# --- Residus ------------------------------------------------------------------
class ResidualFit:
    def __init__(self):
        self.alpha = M.NAN
        self.beta = M.NAN
        self.residuals = np.array([])
        self.ok = False


def residual_fit(stock: D.History, bench: D.History, n: int) -> ResidualFit:
    f = ResidualFit()
    ra, rb = D.aligned_returns(stock, bench, n, log=False)
    if ra.size < max(20, n // 2):
        return f
    o = M.ols_simple(ra, rb)
    if not o.ok:
        return f
    f.alpha, f.beta = float(o.coef[0]), float(o.coef[1])
    f.residuals = o.residuals
    f.ok = True
    return f


def beta(stock: D.History, bench: D.History, n: int) -> float:
    f = residual_fit(stock, bench, n)
    return f.beta if f.ok else M.NAN


# --- Moteur multi-facteurs (fiche 3) ------------------------------------------
class MultiFactorResult:
    def __init__(self):
        self.composite: dict[str, float] = {}
        self.z: dict[str, list[float]] = {}
        self.weights = [1 / 3, 1 / 3, 1 / 3]
        self.factor_12m = [M.NAN, M.NAN, M.NAN]
        self.scored = 0


class MultiFactorEngine:
    FACTOR_NAMES = ("momentum", "value", "qualite")

    def __init__(self, fundamentals: D.Fundamentals | None, mom_lookback=252, mom_skip=21, beta_window=252,
                 rotation_window=252, up_multiplier=1.5, down_multiplier=0.5, use_rotation=True, growth_years=5,
                 tercile_fraction=1 / 3):
        self.fund = fundamentals
        self.mom_lookback, self.mom_skip = mom_lookback, mom_skip
        self.beta_window, self.rotation_window = beta_window, rotation_window
        self.up_multiplier, self.down_multiplier = up_multiplier, down_multiplier
        self.use_rotation, self.growth_years = use_rotation, growth_years
        self.tercile_fraction = tercile_fraction
        self.base_weights = [1 / 3, 1 / 3, 1 / 3]
        self.factor_rets = [[], [], []]
        self.prev_top = self.prev_bottom = None
        self.prev_day = None

    def update(self, day, stocks: dict[str, D.History], market: D.History | None) -> MultiFactorResult:
        import pandas as pd
        res = MultiFactorResult()
        if self.prev_top is not None and self.prev_day is not None:
            for f in range(3):
                top = _mean_return(self.prev_top[f], stocks, self.prev_day, day)
                bot = _mean_return(self.prev_bottom[f], stocks, self.prev_day, day)
                if M.ok(top) and M.ok(bot):
                    self.factor_rets[f].append(top - bot)
                    if len(self.factor_rets[f]) > self.rotation_window * 2:
                        self.factor_rets[f].pop(0)
        names = list(stocks)
        n = len(names)
        mom, val, prof, growth, bet, lev = (np.full(n, M.NAN) for _ in range(6))
        for i, nm in enumerate(names):
            h = stocks[nm]
            mom[i] = return_12_1(h, self.mom_lookback, self.mom_skip)
            bet[i] = beta(h, market, self.beta_window) if market is not None else M.NAN
            fr = self.fund.as_of(nm, day) if self.fund is not None and self.fund.loaded else None
            if fr is not None:
                mcap = h.last_close * fr["shares"]
                if M.ok(mcap) and mcap > 0:
                    val[i] = fr["book_equity"] / mcap if fr["book_equity"] > 0 else M.safe_div(fr["net_income"], mcap)
                prof[i] = fr["profitability"]
                lev[i] = fr["leverage"]
                old = self.fund.as_of(nm, pd.Timestamp(day) - pd.DateOffset(years=self.growth_years))
                if old is not None and old is not fr:
                    growth[i] = fr["profitability"] - old["profitability"]
        z_mom, z_val = M.centered_rank_z(mom), M.centered_rank_z(val)
        z_prof, z_growth = M.centered_rank_z(prof), M.centered_rank_z(growth)
        z_b, z_l = M.centered_rank_z(-bet), M.centered_rank_z(-lev)
        safety = np.array([_mean_ok(z_b[i], z_l[i]) for i in range(n)])
        qual_raw = np.array([_mean_ok(z_prof[i], z_growth[i], safety[i]) for i in range(n)])
        z_qual = M.centered_rank_z(qual_raw)
        w = list(self.base_weights)
        for f in range(3):
            if len(self.factor_rets[f]) >= self.rotation_window:
                cum = float(np.prod(1 + np.asarray(self.factor_rets[f][-self.rotation_window:])))
                res.factor_12m[f] = cum - 1
                if self.use_rotation:
                    w[f] *= self.up_multiplier if cum - 1 > 0 else self.down_multiplier
        ws = sum(w)
        res.weights = [x / ws if ws > 0 else 1 / 3 for x in w]
        for i, nm in enumerate(names):
            z = [z_mom[i], z_val[i], z_qual[i]]
            res.z[nm] = z
            s = wsum = 0.0
            for f in range(3):
                if M.ok(z[f]):
                    s += res.weights[f] * z[f]
                    wsum += res.weights[f]
            if wsum > 0 and M.ok(z[0]):
                res.composite[nm] = s / wsum
                res.scored += 1
        self.prev_top, self.prev_bottom = [], []
        for zs in (z_mom, z_val, z_qual):
            idx = sorted([i for i in range(n) if M.ok(zs[i])], key=lambda i: -zs[i])
            k = max(1, int(math.floor(len(idx) * self.tercile_fraction)))
            self.prev_top.append([names[i] for i in idx[:k]] if len(idx) >= 3 else [])
            self.prev_bottom.append([names[i] for i in idx[len(idx) - k:]] if len(idx) >= 3 else [])
        self.prev_day = day
        return res


def _mean_return(syms, stocks, frm, to) -> float:
    if not syms:
        return M.NAN
    r = []
    for s in syms:
        h = stocks.get(s)
        if h is None:
            continue
        p0, p1 = h.close_on_or_before(frm), h.close_on_or_before(to)
        if M.ok(p0) and M.ok(p1) and p0 > 0:
            r.append(p1 / p0 - 1)
    return sum(r) / len(r) if r else M.NAN


def _mean_ok(*v) -> float:
    vals = [x for x in v if M.ok(x)]
    return sum(vals) / len(vals) if vals else M.NAN
