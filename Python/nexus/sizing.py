"""MODULE B - Taille des positions (port de NexusModuleB_Sizing.cs).

Base (native ou demi-Kelly) -> "Davey waiver" -> correction de correlation ->
plafonds trade / symbole / classe / total / dollars.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from . import mathx as M

SIZING_MODES = ("natif", "demi_kelly", "kelly_contraint", "min_natif_kelly")


class TradeStats:
    """Rendements nets par trade (fraction du notionnel max) d une strategie."""

    def __init__(self, max_history: int = 1000):
        self.rets: list[float] = []
        self.max_history = max_history
        self.live_resolved = 0          # trades resolus en reel (0 en backtest -> waiver toujours actif)

    def add(self, net_return: float):
        if not M.ok(net_return):
            return
        self.rets.append(net_return)
        if len(self.rets) > self.max_history:
            self.rets.pop(0)

    @property
    def count(self) -> int:
        return len(self.rets)

    @property
    def wins(self) -> int:
        return sum(1 for r in self.rets if r > 0)

    @property
    def win_rate(self) -> float:
        return self.wins / self.count if self.count else M.NAN

    @property
    def avg_win(self) -> float:
        w = [r for r in self.rets if r > 0]
        return sum(w) / len(w) if w else M.NAN

    @property
    def avg_loss(self) -> float:
        l = [r for r in self.rets if r <= 0]
        return -sum(l) / len(l) if l else M.NAN

    @property
    def payoff(self) -> float:
        w, l = self.avg_win, self.avg_loss
        return w / l if M.ok(w) and M.ok(l) and l > 0 else M.NAN


def kelly_fraction(p: float, b: float) -> float:
    """f* = p - (1-p)/b."""
    if not M.ok(p) or not M.ok(b) or b <= 0:
        return M.NAN
    return p - (1.0 - p) / b


def break_even_payoff(p: float) -> float:
    return (1 - p) / p if p > 0 else M.NAN


def wilson(wins: int, n: int, z: float = 1.96):
    if n <= 0:
        return M.NAN, M.NAN
    p = wins / n
    den = 1 + z * z / n
    centre = (p + z * z / (2.0 * n)) / den
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4.0 * n * n)) / den
    return centre - half, centre + half


def risk_constrained_kelly(p: float, b: float, alpha: float, beta: float) -> float:
    """Kelly sous contrainte de drawdown (Busseti, Ryu, Boyd) pour un pari binaire."""
    fk = kelly_fraction(p, b)
    if not M.ok(fk) or fk <= 0:
        return 0.0
    fk = min(fk, 0.999)
    if not (0 < alpha < 1 and 0 < beta < 1):
        return fk
    lam = math.log(beta) / math.log(alpha)

    def g(f):
        return p * (1 + f * b) ** (-lam) + (1 - p) * (1 - f) ** (-lam) - 1.0

    if g(fk) <= 0:
        return fk
    lo, hi = 0.0, fk
    for _ in range(100):
        mid = 0.5 * (lo + hi)
        if g(mid) <= 0:
            lo = mid
        else:
            hi = mid
    return lo


@dataclass
class SizingConfig:
    mode: str = "demi_kelly"
    lecture: str = "fraction_notionnel"     # ou "fraction_risquee"
    kelly_multiplier: float = 0.5
    prior_win_rate: float = 0.50
    prior_payoff: float = 1.20
    prior_avg_loss: float = 0.04
    prior_strength: int = 30
    confidence_weight: float = 0.5
    use_wilson_lower_bound: bool = False
    wilson_z: float = 1.96
    no_edge_fraction: float = 0.0025
    rck_alpha: float = 0.70
    rck_beta: float = 0.10
    waiver_trades: int = 30
    waiver_multiplier: float = 0.5
    apply_waiver: bool = True               # faux en backtest (compteur de trades reels nul)
    max_trade_fraction: float = 0.03
    max_trade_dollars: float = 0.0
    max_symbol_fraction: float = 0.10
    max_class_fraction: float = 0.30
    max_total_fraction: float = 0.50
    use_correlation_divisor: bool = True


@dataclass
class SizingResult:
    fraction: float = 0.0
    native: float = M.NAN
    kelly: float = M.NAN
    p: float = M.NAN
    b: float = M.NAN
    detail: str = ""
    blocked: bool = False


def estimate_edge(c: SizingConfig, s: TradeStats | None, model_confidence: float):
    n = s.count if s else 0
    k = max(0, c.prior_strength)
    wins = s.wins if s else 0
    p = (wins + c.prior_win_rate * k) / max(1.0, n + k)
    if c.use_wilson_lower_bound and n >= 10:
        lo, _ = wilson(wins, n, c.wilson_z)
        p = min(p, lo)
    b_obs = s.payoff if s else M.NAN
    b = (n * b_obs + k * c.prior_payoff) / max(1.0, n + k) if M.ok(b_obs) else c.prior_payoff
    l_obs = s.avg_loss if s else M.NAN
    avg_loss = (n * l_obs + k * c.prior_avg_loss) / max(1.0, n + k) if M.ok(l_obs) and l_obs > 0 else c.prior_avg_loss
    if M.ok(model_confidence) and 0 < model_confidence < 1:
        p = c.confidence_weight * model_confidence + (1 - c.confidence_weight) * p
    return p, b, avg_loss


def kelly_notional(c: SizingConfig, s: TradeStats | None, model_confidence: float):
    p, b, avg_loss = estimate_edge(c, s, model_confidence)
    f = risk_constrained_kelly(p, b, c.rck_alpha, c.rck_beta) if c.mode == "kelly_contraint" else kelly_fraction(p, b)
    detail = f"p={p:.3f} b={b:.2f} f*={f:.4f}"
    if not M.ok(f) or f <= 0:
        return f, p, b, detail
    f *= c.kelly_multiplier
    if c.lecture == "fraction_risquee" and avg_loss > 0:
        f /= avg_loss
    return f, p, b, detail


def size(c: SizingConfig, stats: TradeStats | None, native_fraction: float, model_confidence: float,
         sum_positive_correlation: float, equity: float, other_symbol: float, other_class: float, other_total: float) -> SizingResult:
    """Fraction finale du bankroll (notionnel) d un signal."""
    r = SizingResult(native=abs(native_fraction))
    d = []
    if c.mode == "natif":
        f = r.native
    else:
        k, p, b, kd = kelly_notional(c, stats, model_confidence)
        r.kelly, r.p, r.b = k, p, b
        if not M.ok(k) or k <= 0:
            if c.no_edge_fraction > 0:
                k = c.no_edge_fraction
                d.append("Kelly<=0 -> sonde")
            else:
                r.blocked, r.fraction = True, 0.0
                r.detail = f"BLOQUE: Kelly <= 0 ({kd})"
                return r
        f = min(r.native, k) if c.mode == "min_natif_kelly" else k
        d.append(kd)
    d.append(f"base={f:.2%}")
    if c.apply_waiver and stats is not None and stats.live_resolved < c.waiver_trades:
        f *= c.waiver_multiplier
        d.append(f"waiver x{c.waiver_multiplier} ({stats.live_resolved}/{c.waiver_trades} reels)")
    if c.use_correlation_divisor and M.ok(sum_positive_correlation) and sum_positive_correlation > 0:
        f /= 1.0 + sum_positive_correlation
        d.append(f"/(1+{sum_positive_correlation:.2f}) corr")
    if c.max_trade_fraction > 0 and f > c.max_trade_fraction:
        f = c.max_trade_fraction
        d.append("plafond trade")
    if c.max_symbol_fraction > 0 and f + other_symbol > c.max_symbol_fraction:
        f = max(0.0, c.max_symbol_fraction - other_symbol)
        d.append("plafond symbole")
    if c.max_class_fraction > 0 and f + other_class > c.max_class_fraction:
        f = max(0.0, c.max_class_fraction - other_class)
        d.append("plafond classe")
    if c.max_total_fraction > 0 and f + other_total > c.max_total_fraction:
        f = max(0.0, c.max_total_fraction - other_total)
        d.append("plafond total")
    if c.max_trade_dollars > 0 and equity > 0 and f * equity > c.max_trade_dollars:
        f = c.max_trade_dollars / equity
        d.append("plafond $")
    r.fraction = max(0.0, f)
    r.detail = "; ".join(d) + f" => {r.fraction:.2%}"
    return r


def strategy_correlation_matrix(returns: dict[str, "np.ndarray | list"], window: int = 60):
    """Matrice de correlation des rendements journaliers de plusieurs strategies (pandas Series par nom)."""
    import pandas as pd
    df = pd.DataFrame(returns).dropna(how="any").tail(window)
    return df.corr() if len(df) >= 10 else None
