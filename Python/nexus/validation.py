"""MODULE C (partie validation) : Monte Carlo, bootstrap par blocs, Sharpe, PSR, Deflated Sharpe,
PBO par CSCV, walk-forward, cycle drawdown -> recuperation (port de NxValidation)."""
from __future__ import annotations

import math
from itertools import combinations

import numpy as np

from . import mathx as M


def equity_from_pnls(pnls, start: float) -> np.ndarray:
    return np.concatenate([[start], start + np.cumsum(np.asarray(pnls, float))])


def max_drawdown(equity) -> float:
    e = np.asarray(equity, float)
    e = e[np.isfinite(e)]
    if e.size == 0:
        return 0.0
    peak = np.maximum.accumulate(e)
    with np.errstate(divide="ignore", invalid="ignore"):
        dd = np.where(peak > 0, 1 - e / peak, 0.0)
    return float(max(0.0, dd.max()))


def _mdd_paths(paths: np.ndarray, start: float) -> np.ndarray:
    v = start + np.cumsum(paths, axis=1)
    v = np.concatenate([np.full((v.shape[0], 1), start), v], axis=1)
    peak = np.maximum.accumulate(v, axis=1)
    with np.errstate(divide="ignore", invalid="ignore"):
        dd = np.where(peak > 0, 1 - v / peak, 0.0)
    return dd.max(axis=1)


def monte_carlo_max_dd(pnls, start: float, sims: int = 1000, seed: int = 7) -> np.ndarray:
    """Tirage avec remise des trades, distribution (triee) du drawdown max."""
    p = np.asarray(pnls, float)
    if p.size == 0:
        return np.array([])
    rng = np.random.default_rng(seed)
    out = _mdd_paths(p[rng.integers(0, p.size, size=(sims, p.size))], start)
    return np.sort(out)


def block_bootstrap_max_dd(pnls, start: float, block_length: int = 0, sims: int = 1000, seed: int = 8) -> np.ndarray:
    """Bootstrap par blocs mobiles (conserve l autocorrelation des trades consecutifs)."""
    p = np.asarray(pnls, float)
    n = p.size
    if n == 0:
        return np.array([])
    L = max(1, min(block_length if block_length > 0 else int(round(math.sqrt(n))), n))
    rng = np.random.default_rng(seed)
    nb = int(math.ceil(n / L))
    starts = rng.integers(0, n - L + 1, size=(sims, nb))
    idx = (starts[:, :, None] + np.arange(L)[None, None, :]).reshape(sims, -1)[:, :n]
    return np.sort(_mdd_paths(p[idx], start))


def percentile(sorted_arr, q: float) -> float:
    return M.quantile(sorted_arr, q) if len(sorted_arr) else M.NAN


def sharpe_per_period(rets) -> float:
    m, s = M.mean(rets), M.std(rets)
    return m / s if M.ok(m) and M.ok(s) and s > 0 else M.NAN


def annualized_sharpe(rets, periods_per_year: float = M.TRADING_DAYS_PER_YEAR) -> float:
    sr = sharpe_per_period(rets)
    return sr * math.sqrt(periods_per_year) if M.ok(sr) else M.NAN


def probabilistic_sharpe(sr: float, sr_benchmark: float, n: int, skew: float, kurt: float) -> float:
    if not M.ok(sr) or n < 3:
        return M.NAN
    den = 1 - skew * sr + (kurt - 1) / 4.0 * sr * sr
    if den <= 0:
        return M.NAN
    return M.norm_cdf((sr - sr_benchmark) * math.sqrt(n - 1) / math.sqrt(den))


def expected_max_sharpe(n_trials: int, var_trials: float) -> float:
    if n_trials <= 1 or not M.ok(var_trials) or var_trials <= 0:
        return 0.0
    g = M.EULER_GAMMA
    return math.sqrt(var_trials) * ((1 - g) * M.norm_inv(1 - 1.0 / n_trials) + g * M.norm_inv(1 - 1.0 / (n_trials * math.e)))


def deflated_sharpe(rets, n_trials: int = 1, var_trials: float = M.NAN):
    """Deflated Sharpe Ratio (Bailey, Lopez de Prado). -> (dsr, sr0)."""
    r = np.asarray(rets, float)
    r = r[np.isfinite(r)]
    n = r.size
    if n < 10:
        return M.NAN, M.NAN
    sr, sk, ku = sharpe_per_period(r), M.skewness(r), M.kurtosis(r)
    if not M.ok(sr):
        return M.NAN, M.NAN
    if not M.ok(var_trials) or var_trials <= 0:
        var_trials = max(1e-12, (1 - sk * sr + (ku - 1) / 4.0 * sr * sr) / (n - 1))
    sr0 = expected_max_sharpe(max(1, n_trials), var_trials)
    return probabilistic_sharpe(sr, sr0, n, sk, ku), sr0


def _sharpe_from_agg(s: np.ndarray, q: np.ndarray, c: np.ndarray) -> np.ndarray:
    with np.errstate(divide="ignore", invalid="ignore"):
        m = s / c
        v = (q - c * m * m) / (c - 1)
        out = np.where(v > 0, m / np.sqrt(np.where(v > 0, v, 1.0)), np.where(m > 0, 1e6, -1e6))
    return np.where(c < 3, -np.inf, out)


def pbo(configs, S: int = 16, max_combos: int = 2000, seed: int = 11):
    """Probability of Backtest Overfitting par CSCV. configs : matrice (N configs x T dates). -> (pbo, combos)."""
    X = np.asarray(configs, float)
    if X.ndim != 2 or X.shape[0] < 2:
        return M.NAN, 0
    N, T = X.shape
    if S % 2 == 1:
        S -= 1
    if S < 2 or T < S * 5:
        return M.NAN, 0
    blk = T // S
    Xb = X[:, : blk * S].reshape(N, S, blk)
    fin = np.isfinite(Xb)
    Xz = np.where(fin, Xb, 0.0)
    sm, sq, cnt = Xz.sum(axis=2), (Xz * Xz).sum(axis=2), fin.sum(axis=2).astype(float)
    masks = list(combinations(range(S), S // 2))
    if max_combos > 0 and len(masks) > max_combos:
        rng = np.random.default_rng(seed)
        sel = rng.choice(len(masks), size=max_combos, replace=False)
        masks = [masks[i] for i in sel]
    below = 0
    for m in masks:
        ins = np.zeros(S, bool)
        ins[list(m)] = True
        is_perf = _sharpe_from_agg(sm[:, ins].sum(1), sq[:, ins].sum(1), cnt[:, ins].sum(1))
        oos_perf = _sharpe_from_agg(sm[:, ~ins].sum(1), sq[:, ~ins].sum(1), cnt[:, ~ins].sum(1))
        best = int(np.argmax(is_perf))
        rank = 1 + int(np.sum((np.arange(N) != best) & (oos_perf < oos_perf[best])))
        w = rank / (N + 1.0)
        if math.log(w / (1 - w)) <= 0:
            below += 1
    return (below / len(masks) if masks else M.NAN), len(masks)


def walk_forward_splits(n: int, train: int = 180, test: int = 30):
    """Fenetres [debut_entr, fin_entr, debut_test, fin_test) - 180/30 par defaut [Fil]."""
    return [(s, s + train, s + train, s + train + test) for s in range(0, n - train - test + 1, test)]


def has_drawdown_recovery_cycle(equity, min_dd: float = 0.05):
    """Au moins un cycle complet drawdown (>= min_dd) -> recuperation (nouveau plus haut). -> (bool, plus_profond, pas)."""
    deepest, bars = 0.0, 0
    peak = trough = M.NAN
    peak_idx = 0
    in_dd = found = False
    for i, v in enumerate(equity):
        if not M.ok(v):
            continue
        if not M.ok(peak) or v >= peak:
            if in_dd:
                found = True
                depth = 1 - trough / peak
                if depth > deepest:
                    deepest, bars = depth, i - peak_idx
                in_dd = False
            peak, peak_idx, trough = v, i, v
            continue
        if v < trough:
            trough = v
        if peak > 0 and 1 - v / peak >= min_dd:
            in_dd = True
    return found, deepest, bars
