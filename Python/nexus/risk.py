"""MODULE C (partie risque) : disjoncteurs, modele de couts, stress test (port de NexusModuleC_RiskValidation.cs)."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta

from . import mathx as M


class CircuitBreaker:
    """-15 % du plus haut -> entrees rejetees 12 h ; -5 % sur le jour -> entrees suspendues 24 h.

    daily_ref = "veille" : la perte du jour est mesuree depuis l equity de la cloture precedente
    (comportement du temps reel). daily_ref = "ninja" : reproduit exactement le C# en backtest,
    ou la reference du jour est prise a la premiere mise a jour du jour (le disjoncteur journalier
    ne peut alors presque jamais se declencher sur barres journalieres).
    """

    def __init__(self, enabled=True, drawdown_trip_pct=15.0, drawdown_cooldown_hours=12.0,
                 daily_loss_pct=5.0, daily_cooldown_hours=24.0, reset_peak_after_cooldown=True, daily_ref="veille"):
        self.enabled = enabled
        self.drawdown_trip_pct = drawdown_trip_pct
        self.drawdown_cooldown = timedelta(hours=drawdown_cooldown_hours)
        self.daily_loss_pct = daily_loss_pct
        self.daily_cooldown = timedelta(hours=daily_cooldown_hours)
        self.reset_peak_after_cooldown = reset_peak_after_cooldown
        self.daily_ref = daily_ref
        self.peak = M.NAN
        self.day_start = M.NAN
        self.day = None
        self.last_equity = M.NAN
        self.dd_until: datetime | None = None
        self.daily_until: datetime | None = None
        self.drawdown_trips = 0
        self.daily_trips = 0
        self.events: list[str] = []
        self.last_event: str | None = None

    def update(self, now: datetime, trading_day, equity: float) -> bool:
        if not self.enabled or not M.ok(equity):
            return False
        evt = False
        if trading_day != self.day:
            self.day = trading_day
            if self.daily_ref == "veille" and M.ok(self.last_equity):
                self.day_start = self.last_equity
            else:
                self.day_start = equity
        self.last_equity = equity
        if not M.ok(self.peak) or equity > self.peak:
            self.peak = equity
        if self.dd_until is not None and now >= self.dd_until:
            self.dd_until = None
            if self.reset_peak_after_cooldown:
                self.peak = equity
            self._event(f"{now:%Y-%m-%d %H:%M} disjoncteur drawdown rearme (nouvelle reference {self.peak:.2f})")
            evt = True
        if self.daily_until is not None and now >= self.daily_until:
            self.daily_until = None
            self.day_start = equity
            self._event(f"{now:%Y-%m-%d %H:%M} disjoncteur journalier rearme")
            evt = True
        if self.dd_until is None and self.peak > 0 and equity <= self.peak * (1 - self.drawdown_trip_pct / 100.0):
            self.dd_until = now + self.drawdown_cooldown
            self.drawdown_trips += 1
            self._event(f"{now:%Y-%m-%d %H:%M} DISJONCTEUR DRAWDOWN : equity {equity:.2f} <= {1 - self.drawdown_trip_pct / 100:.0%} "
                        f"du plus haut {self.peak:.2f} -> entrees rejetees jusqu au {self.dd_until:%Y-%m-%d %H:%M}")
            evt = True
        if self.daily_until is None and self.day_start > 0 and equity <= self.day_start * (1 - self.daily_loss_pct / 100.0):
            self.daily_until = now + self.daily_cooldown
            self.daily_trips += 1
            self._event(f"{now:%Y-%m-%d %H:%M} DISJONCTEUR JOURNALIER : PnL du jour {equity / self.day_start - 1:.2%} "
                        f"-> entrees suspendues jusqu au {self.daily_until:%Y-%m-%d %H:%M}")
            evt = True
        return evt

    def _event(self, s: str):
        self.last_event = s
        self.events.append(s)

    def can_open(self, now: datetime):
        if not self.enabled:
            return True, None
        if self.dd_until is not None and now < self.dd_until:
            return False, f"disjoncteur drawdown -{self.drawdown_trip_pct}% (jusqu au {self.dd_until:%Y-%m-%d %H:%M})"
        if self.daily_until is not None and now < self.daily_until:
            return False, f"disjoncteur journalier -{self.daily_loss_pct}% (jusqu au {self.daily_until:%Y-%m-%d %H:%M})"
        return True, None


@dataclass
class CostModel:
    slippage_pct: float = 0.05
    equity_fee_pct: float = 0.0
    crypto_fee_pct: float = 0.10
    crypto_bnb_fee_pct: float = 0.075
    use_bnb: bool = False
    other_fee_pct: float = 0.0
    per_contract_fee: float = 0.0

    def fee_pct(self, asset_class: str) -> float:
        if asset_class in ("Action", "Etf"):
            return self.equity_fee_pct
        if asset_class == "Crypto":
            return self.crypto_bnb_fee_pct if self.use_bnb else self.crypto_fee_pct
        return self.other_fee_pct

    def cost(self, asset_class: str, notional: float, qty: float) -> float:
        v = abs(notional) * (self.slippage_pct + self.fee_pct(asset_class)) / 100.0
        if asset_class in ("Future", "Option"):
            v += abs(qty) * self.per_contract_fee
        return v

    def describe(self) -> str:
        return (f"glissement {self.slippage_pct:.3f}%/ordre, frais actions {self.equity_fee_pct:.3f}%, crypto "
                f"{self.crypto_bnb_fee_pct if self.use_bnb else self.crypto_fee_pct:.3f}%, autres {self.other_fee_pct:.3f}%, "
                f"{self.per_contract_fee:.2f}$/contrat")


@dataclass
class TradeRecord:
    strategy: str
    symbol: str
    asset_class: str
    direction: int
    max_qty: float
    entry_time: object
    exit_time: object
    entry_price: float
    exit_price: float
    max_notional: float
    gross_pnl: float
    costs: float
    net_pnl: float
    net_return: float
    gross_return: float
    entry_reason: str = ""
    exit_reason: str = ""
    regime: str = ""
    extra: dict = field(default_factory=dict)


@dataclass
class StressPosition:
    symbol: str
    qty: float
    price: float
    stop: float
    value_per_point: float


def stress_test(pos: list[StressPosition], equity: float, shock_pct: float, worst_n: int) -> str:
    if not pos or not equity > 0:
        return "Stress test : aucune position ouverte."
    stop_loss = shock_loss = no_stop = 0.0
    for p in pos:
        notional = abs(p.qty) * p.price * p.value_per_point
        if M.ok(p.stop):
            stop_loss += abs(p.qty) * abs(p.price - p.stop) * p.value_per_point
        else:
            no_stop += notional
        shock_loss += notional * shock_pct
    exposures = sorted((abs(p.qty) * p.price * p.value_per_point for p in pos), reverse=True)
    worst = sum(exposures[: max(1, worst_n)]) * shock_pct
    lines = [f"Stress test ({len(pos)} positions, equity {equity:.0f}) :",
             f"  tous les stops touches ensemble      : -{stop_loss:.0f} ({stop_loss / equity:.1%})",
             f"  choc -{shock_pct:.0%} sur TOUTES les positions  : -{shock_loss:.0f} ({shock_loss / equity:.1%})",
             f"  choc -{shock_pct:.0%} sur les {worst_n} plus grosses : -{worst:.0f} ({worst / equity:.1%})"]
    if no_stop > 0:
        lines.append(f"  exposition sans stop : {no_stop:.0f} ({no_stop / equity:.1%})")
    return "\n".join(lines)
