"""Moteur de backtest : port de Strategies/NexusStrategyBase.cs.

Semantique reproduite :
  - une serie par symbole (absente des donnees = ignoree avec un message) ;
  - calendrier maitre = union des dates ; en mode "par lot", on_batch(jour) est appele
    une fois par date quand toutes les series ont clos leur barre ; en mode "par symbole",
    on_symbol_bar(s, jour) a chaque barre de chaque symbole ;
  - moteur "position cible" : set_target() puis flush automatique en fin de lot ;
    reductions d abord, entrees ensuite ; ordres executes a l OUVERTURE de la barre
    suivante (aucune information future) ; ordres limites valables N barres ;
  - stops natifs (stop market) actifs des la barre d entree : ouverture si l ouverture
    franchit le stop (gap), sinon au prix du stop ; stop "logiciel" -> sortie a l ouverture
    suivante ; un stop deja franchi a la cloture -> sortie au marche ;
  - comptabilite interne nette des couts modelises (module C), equity marquee a la cloture,
    conversion de devise vers l USD par les paires chargees (ou taux de repli) ;
  - module B (sizing) et disjoncteurs (module C) comme dans le C#.
"""
from __future__ import annotations

import dataclasses
import math
from dataclasses import dataclass
from types import SimpleNamespace

import numpy as np
import pandas as pd

from . import data as D
from . import mathx as M
from .risk import CircuitBreaker, CostModel, StressPosition, TradeRecord, stress_test
from .sizing import SizingConfig, TradeStats, size as sizer_size

BASE_DEFAULTS = dict(
    # --- 00. Univers ---
    symbols="SPY,QQQ",
    reference_symbols="",
    etf_symbols=",".join(D.DEFAULT_ETFS),
    allow_short_selling=False,
    lot_size=1,
    fx_fallback="EUR=1.08;GBP=1.27;JPY=0.0067;AUD=0.66;CHF=1.12;CAD=0.73;NZD=0.60",
    instrument_overrides=None,          # {symbole: dict(asset_class=..., currency=..., point_value=...)}
    futures_micro=False,                # futures : multiplicateurs des contrats micro (MES, MNQ, MGC, M6E...)
    crypto_unit=0.0001,                 # crypto : 1 unite de quantite = 0.0001 piece (quantites entieres du moteur ; 0 = 1 piece, comme NinjaTrader)
    # --- Capital et module B ---
    initial_bankroll=100000.0,
    sizing_mode="demi_kelly",           # natif | demi_kelly | kelly_contraint | min_natif_kelly
    kelly_lecture="fraction_notionnel",
    kelly_multiplier=0.5,
    prior_win_rate=0.50,
    prior_payoff=1.20,
    prior_avg_loss_pct=4.0,
    prior_strength=30,
    confidence_weight=0.5,
    use_wilson_lower_bound=False,
    no_edge_fraction_pct=0.25,          # taille sonde si Kelly <= 0 (0 = blocage definitif)
    rck_alpha=0.70,
    rck_beta=0.10,
    waiver_trades=30,
    waiver_multiplier=0.5,
    waiver_in_backtest=False,           # Davey waiver : regle du temps reel ; en backtest le compteur de trades reels vaut 0
    live_resolved_trades=0,             # trades reels deja resolus (Davey waiver)
    max_trade_pct=3.0,
    max_trade_dollars=0.0,
    max_symbol_pct=10.0,
    max_class_pct=30.0,
    max_total_pct=50.0,
    use_correlation_divisor=True,
    correlation_window=60,
    # --- Module C ---
    use_circuit_breakers=True,
    drawdown_trip_pct=15.0,
    drawdown_cooldown_hours=12.0,
    daily_loss_pct=5.0,
    daily_cooldown_hours=24.0,
    reset_peak_after_cooldown=True,
    daily_breaker_ref="veille",         # veille (comme le temps reel) | ninja (backtest NinjaTrader)
    slippage_pct=0.05,
    equity_fee_pct=0.0,
    crypto_fee_pct=0.10,
    use_bnb_discount=False,
    other_fee_pct=0.0,
    per_contract_fee=0.0,
    stop_mode="natif",                  # natif | logiciel | aucun
    stress_shock_pct=10.0,
    stress_worst_n=10,
    monte_carlo_sims=1000,
    block_length=0,
    seed=7,
    instance_tag="",
    verbose=False,
)


@dataclass
class Order:
    delta: float          # quantite signee restant a executer
    kind: str             # market | limit
    limit: float
    expiry_count: int     # la barre de comptage a partir de laquelle l ordre limite expire
    reason: str


class Sym:
    """Etat d un symbole de l univers (port de NxSym)."""

    def __init__(self, name: str, inst: D.Instrument, hist: D.History, traded: bool):
        self.name = name
        self.inst = inst
        self.hist = hist
        self.traded = traded
        self.asset_class = inst.asset_class
        self.seven_days = inst.seven_days
        self.holidays: set = set()
        # execution
        self.target_qty = 0
        self.stop_price = M.NAN
        self.order_kind = "market"
        self.limit_price = M.NAN
        self.limit_expiry_count = 1 << 30
        self.pending_reason = ""
        self.dirty = False
        self.working: Order | None = None
        self.stop_rejected = False
        # comptabilite
        self.qty = 0
        self.avg_price = 0.0
        self.open_time = None
        self.entry_day = None
        self.entry_bar_count = 0
        self.trade_gross = 0.0
        self.trade_costs = 0.0
        self.max_notional = 0.0
        self.max_qty = 0
        self.direction = 0
        self.entry_reason = ""
        self.regime = ""
        self.last_price = M.NAN
        self.stopped_out = False
        self.stopped_time = None
        self.tag = None

    @property
    def bars_held(self) -> int:
        return 0 if self.qty == 0 else max(0, self.hist.count - self.entry_bar_count)

    @property
    def is_flat(self) -> bool:
        return self.qty == 0

    def __repr__(self):
        return self.name


class BacktestResult(SimpleNamespace):
    """Resultats d un run : equity, rendements, trades, fills, rapport texte, journal."""

    def trades_frame(self) -> pd.DataFrame:
        return pd.DataFrame([t.__dict__ for t in self.trades]) if self.trades else pd.DataFrame()


class NexusStrategy:
    """Classe de base des strategies (equivalent de NexusStrategyBase)."""

    NAME = "Nexus"
    DESCRIPTION = ""
    DEFAULTS: dict = {}
    BATCH_MODE = True

    def __init__(self, **params):
        merged = dict(BASE_DEFAULTS)
        for cls in reversed(type(self).__mro__):
            merged.update(getattr(cls, "DEFAULTS", {}) or {})
        unknown = [k for k in params if k not in merged]
        if unknown:
            raise ValueError(f"{self.NAME} : parametre(s) inconnu(s) {unknown}. Connus : {sorted(merged)}")
        merged.update(params)
        self.p = SimpleNamespace(**merged)
        self.params = merged
        self.name = self.NAME
        self.strategy_id = self.NAME + (("_" + self.p.instance_tag.strip()) if self.p.instance_tag else "")
        self.log: list[str] = []
        self.signals: list[tuple] = []
        self._warned: set = set()

    # =========================================================================
    #  Points d extension (a surcharger)
    # =========================================================================
    def required_references(self) -> list[str]:
        return []

    def on_data_loaded(self):
        pass

    def on_batch(self, day):
        pass

    def on_symbol_bar(self, s: Sym, day):
        pass

    def on_stopped(self, s: Sym):
        pass

    def on_fill(self, s: Sym, signed_qty, price, time):
        pass

    def on_trade_closed(self, s: Sym, r: TradeRecord):
        pass

    def report_extras(self, lines: list[str]):
        pass

    def allow_increase(self, s: Sym):
        return True, None

    def extra_equity(self) -> float:
        return 0.0

    def universe_bars(self) -> str:
        return "day"

    def bar_minutes(self) -> int:
        """0 = barres journalieres ; N > 0 = barres de N minutes (fiches intrajournalieres)."""
        return 0

    # =========================================================================
    #  Journal
    # =========================================================================
    def nx(self, msg: str):
        line = f"[{self.strategy_id}] {msg}"
        self.log.append(line)
        if self.p.verbose:
            print(line)

    def nx_once(self, key: str, msg: str):
        if key not in self._warned:
            self._warned.add(key)
            self.nx(msg)

    def signal(self, t, symbol: str, kind: str, detail: str):
        self.signals.append((t, symbol, kind, detail))

    # =========================================================================
    #  Preparation de l univers
    # =========================================================================
    def _prepare(self, data: dict, start=None, end=None, trade_start=None):
        p = self.p
        traded = D_split(p.symbols)
        refs = D_split(p.reference_symbols) + [x for x in self.required_references() if x and x.strip()]
        etfs = D_split(p.etf_symbols)
        self.syms: list[Sym] = []
        self.by_name: dict[str, Sym] = {}
        seen = set()
        frames = {}
        for name, is_traded in [(n, True) for n in traded] + [(n, False) for n in refs]:
            key = name.upper()
            if key in seen:
                continue
            seen.add(key)
            df = _lookup(data, name)
            if df is None or df.empty:
                self.nx(f"instrument introuvable dans les donnees, ignore -> '{name}'")
                continue
            is_future = df.attrs.get("future") if isinstance(getattr(df, "attrs", None), dict) else None
            df = df.sort_index()
            if start is not None:
                df = df[df.index >= pd.Timestamp(start)]
            if end is not None:
                df = df[df.index <= pd.Timestamp(end) + pd.Timedelta(hours=23, minutes=59)]
            if df.empty:
                self.nx(f"aucune barre dans la periode pour '{name}', ignore")
                continue
            inst = D.classify(name, etfs, p.instrument_overrides, micro=bool(p.futures_micro), is_future=is_future)
            if inst.asset_class == "Crypto" and p.crypto_unit and p.crypto_unit > 0 and not (p.instrument_overrides and name in p.instrument_overrides):
                inst = dataclasses.replace(inst, point_value=float(p.crypto_unit))
            s = Sym(name, inst, D.History(name, df), is_traded)
            if not inst.seven_days and len(df) > 1:
                days = pd.DatetimeIndex(df.index).normalize()
                allb = pd.bdate_range(days[0], days[-1])
                s.holidays = set(allb.difference(days))
            self.syms.append(s)
            self.by_name[name.upper()] = s
            frames[name] = df
        if not frames:
            raise ValueError(f"{self.NAME} : aucune serie chargee (verifier 'symbols' et le dossier de cotations)")
        master = pd.DatetimeIndex(sorted(set().union(*[set(pd.DatetimeIndex(f.index)) for f in frames.values()])))
        self.master = master
        self.pos = {}
        for s in self.syms:
            idx = pd.DatetimeIndex(s.hist.dates)
            arr = np.full(len(master), -1, dtype=np.int64)
            arr[master.get_indexer(idx)] = np.arange(len(idx))
            self.pos[s.name] = arr
        # Etat
        self.sizing_cfg = SizingConfig(
            mode=p.sizing_mode, lecture=p.kelly_lecture, kelly_multiplier=p.kelly_multiplier,
            prior_win_rate=p.prior_win_rate, prior_payoff=p.prior_payoff, prior_avg_loss=p.prior_avg_loss_pct / 100.0,
            prior_strength=p.prior_strength, confidence_weight=p.confidence_weight,
            use_wilson_lower_bound=p.use_wilson_lower_bound, no_edge_fraction=p.no_edge_fraction_pct / 100.0,
            rck_alpha=p.rck_alpha, rck_beta=p.rck_beta, waiver_trades=p.waiver_trades, waiver_multiplier=p.waiver_multiplier,
            apply_waiver=bool(p.waiver_in_backtest),
            max_trade_fraction=p.max_trade_pct / 100.0, max_trade_dollars=p.max_trade_dollars,
            max_symbol_fraction=p.max_symbol_pct / 100.0, max_class_fraction=p.max_class_pct / 100.0,
            max_total_fraction=p.max_total_pct / 100.0, use_correlation_divisor=p.use_correlation_divisor)
        self.costs = CostModel(slippage_pct=p.slippage_pct, equity_fee_pct=p.equity_fee_pct, crypto_fee_pct=p.crypto_fee_pct,
                               use_bnb=p.use_bnb_discount, other_fee_pct=p.other_fee_pct, per_contract_fee=p.per_contract_fee)
        self.breaker = CircuitBreaker(p.use_circuit_breakers, p.drawdown_trip_pct, p.drawdown_cooldown_hours,
                                      p.daily_loss_pct, p.daily_cooldown_hours, p.reset_peak_after_cooldown, p.daily_breaker_ref)
        self.stats = TradeStats()
        self.stats.live_resolved = int(p.live_resolved_trades)
        self.fx_fallback = {k.upper(): float(v) for k, v in _parse_map(p.fx_fallback).items()}
        self.closed_trades: list[TradeRecord] = []
        self.fills: list[tuple] = []
        self.equity_days: list = []
        self.equity_values: list[float] = []
        self.exposure_values: list[float] = []
        self.realized_net = 0.0
        self.probe_entries = 0
        self.batch_count = 0
        self.last_batch_day = None
        self.now = None
        self.trade_start = pd.Timestamp(trade_start) if trade_start is not None else None
        self._first_rebalance_done = False
        self._last_rebalance_key = -(1 << 30)
        n_traded = sum(1 for s in self.syms if s.traded)
        self.nx(f"{n_traded} symboles trades, {len(self.syms) - n_traded} de reference, capital initial {p.initial_bankroll:.0f}, id '{self.strategy_id}'")
        if n_traded == 0:
            self.nx("AUCUN symbole tradable trouve - verifier 'symbols' et les donnees.")

    # =========================================================================
    #  Acces pour les strategies filles
    # =========================================================================
    def sym(self, name: str | None) -> Sym | None:
        return self.by_name.get(name.upper()) if name else None

    @property
    def traded_syms(self) -> list[Sym]:
        return [s for s in self.syms if s.traded]

    @property
    def warming_up(self) -> bool:
        return self.trade_start is not None and self.now is not None and self.now < self.trade_start

    # --- devises ---
    def fx_to_usd(self, ccy: str) -> float:
        ccy = (ccy or "USD").upper()
        if ccy == "USD":
            return 1.0
        d = self.by_name.get(ccy + "USD")
        if d is not None and M.ok(d.last_price) and d.last_price > 0:
            return d.last_price
        d = self.by_name.get("USD" + ccy)
        if d is not None and M.ok(d.last_price) and d.last_price > 0:
            return 1.0 / d.last_price
        fb = self.fx_fallback.get(ccy)
        if fb and fb > 0:
            self.nx_once("fx" + ccy, f"Conversion {ccy}->USD : taux de repli {fb} (ajouter {ccy}USD en reference pour un taux reel)")
            return fb
        self.nx_once("fxnone" + ccy, f"Conversion {ccy}->USD inconnue : taux 1 suppose")
        return 1.0

    def value_per_point(self, s: Sym) -> float:
        return s.inst.point_value * self.fx_to_usd(s.inst.currency)

    def notional(self, s: Sym, qty, price) -> float:
        return abs(qty) * price * self.value_per_point(s)

    def round_price(self, s: Sym, px: float) -> float:
        if not M.ok(px):
            return px
        t = s.inst.tick_size if s.inst.tick_size > 0 else 0.01
        return round(px / t) * t

    # --- equity ---
    def unrealized_pnl(self) -> float:
        u = 0.0
        for s in self.syms:
            if s.traded and s.qty != 0 and M.ok(s.last_price):
                u += s.qty * (s.last_price - s.avg_price) * self.value_per_point(s)
        return u

    @property
    def equity(self) -> float:
        return self.p.initial_bankroll + self.realized_net + self.unrealized_pnl() + self.extra_equity()

    def bankroll(self) -> float:
        return max(0.0, self.equity)

    # --- calendrier ---
    def is_rebalance_day(self, day, freq: str, calendar: Sym | None) -> bool:
        """Mensuel = dernier jour de bourse du mois ; hebdomadaire = dernier de la semaine.
        Premier appel = reequilibrage immediat ; une fin de periode manquee est rattrapee."""
        if freq == "quotidien":
            return True
        hol = calendar.holidays if calendar is not None else None
        seven = calendar is not None and calendar.seven_days
        key = D.month_key(day) if freq == "mensuel" else D.week_key(day)
        last = (D.is_last_trading_day_of_month(day, hol, seven) if freq == "mensuel"
                else D.is_last_trading_day_of_week(day, hol, seven))
        if not self._first_rebalance_done:
            self._first_rebalance_done = True
            self._last_rebalance_key = key if last else key - 1
            return True
        if last and self._last_rebalance_key < key:
            self._last_rebalance_key = key
            return True
        if self._last_rebalance_key < key - 1:
            self._last_rebalance_key = key - 1
            return True
        return False

    # =========================================================================
    #  Module B : dimensionnement
    # =========================================================================
    def _planned_exposure(self, except_s: Sym, cls: str):
        total = same = 0.0
        for o in self.syms:
            if not o.traded or o is except_s:
                continue
            q = max(abs(o.target_qty), 0 if o.dirty else abs(o.qty))
            if q == 0 or not M.ok(o.last_price):
                continue
            n = self.notional(o, q, o.last_price)
            total += n
            if o.asset_class == cls:
                same += n
        return total, same

    def sum_positive_correlation(self, s: Sym, direction: int, mode: str | None = None) -> float:
        """Somme des correlations positives d un NOUVEAU signal avec les positions OUVERTES (module B).

        Seulement pour les signaux dimensionnes par Kelly (signaux independants). Les modes natifs
        (portefeuilles des fiches 1, 2, 3, 5, 12, 13) dimensionnent deja leurs positions ensemble :
        y appliquer le diviseur ecrasait l exposition et dependait de l ordre de traitement.
        Les cibles posees dans le lot en cours ne comptent pas (seules les positions ouvertes)."""
        if (mode or self.sizing_cfg.mode) == "natif" or s.qty != 0:
            return 0.0
        tot = 0.0
        for o in self.syms:
            if not o.traded or o is s or o.qty == 0:
                continue
            c = D.return_correlation(s.hist, o.hist, self.p.correlation_window)
            if not M.ok(c):
                continue
            signed = c * direction * (1 if o.qty > 0 else -1)
            if signed > 0:
                tot += signed
        return tot

    def size_qty(self, s: Sym, native_signed_fraction: float, price: float, model_confidence: float = M.NAN,
                 mode: str | None = None):
        """Quantite signee pour une fraction native signee du bankroll (notionnel), apres module B. -> (qty, detail)."""
        d = 1 if native_signed_fraction > 0 else (-1 if native_signed_fraction < 0 else 0)
        if d == 0 or s is None:
            return 0, ""
        if d < 0 and not self.p.allow_short_selling:
            return 0, "vente a decouvert desactivee"
        bank = self.bankroll()
        if not bank > 0 or not M.ok(price) or price <= 0:
            return 0, "bankroll ou prix invalide"
        tot, cls = self._planned_exposure(s, s.asset_class)
        corr = self.sum_positive_correlation(s, d, mode) if self.p.use_correlation_divisor else 0.0
        cfg = self.sizing_cfg
        if mode is not None and mode != cfg.mode:
            cfg = SizingConfig(**{**cfg.__dict__, "mode": mode})
        r = sizer_size(cfg, self.stats, abs(native_signed_fraction), model_confidence, corr, bank, 0.0, cls / bank, tot / bank)
        if "sonde" in (r.detail or ""):
            self.probe_entries += 1
        if r.blocked or r.fraction <= 0:
            return 0, r.detail
        units = r.fraction * bank / (price * self.value_per_point(s))
        lot = max(1, int(self.p.lot_size))
        q = int(math.floor(units / lot)) * lot
        detail = r.detail + (f" | quantite < {lot} (capital insuffisant pour 1 lot)" if q <= 0 else "")
        return d * q, detail

    def kelly_native_fraction(self) -> float:
        """Fraction native des fiches dimensionnees par Kelly (4A, 4B, 6, 7, 9, 10, 14) : le plafond par trade
        s il est actif, sinon 100 % (le demi-Kelly et les autres plafonds decident). Un plafond desactive (0)
        ne doit pas donner une taille nulle."""
        return self.p.max_trade_pct / 100.0 if self.p.max_trade_pct > 0 else 1.0

    def risk_qty(self, s: Sym, risk_fraction: float, stop_distance: float) -> int:
        if not stop_distance > 0 or not risk_fraction > 0:
            return 0
        units = risk_fraction * self.bankroll() / (stop_distance * self.value_per_point(s))
        lot = max(1, int(self.p.lot_size))
        return int(math.floor(units / lot)) * lot

    # =========================================================================
    #  Moteur "position cible"
    # =========================================================================
    def set_target(self, s: Sym, qty: int, stop: float, reason: str, kind: str = "market", limit: float = M.NAN, valid_bars: int = 1):
        if s is None or not s.traded:
            return
        qty = int(qty)
        if qty < 0 and not self.p.allow_short_selling:
            qty = 0
        s.target_qty = qty
        s.stop_price = M.NAN if qty == 0 else stop
        s.order_kind = "limit" if kind == "limit" and M.ok(limit) and limit > 0 else "market"
        s.limit_price = limit
        s.limit_expiry_count = s.hist.count + max(1, valid_bars)
        s.pending_reason = reason or ""
        s.dirty = True

    def update_stop(self, s: Sym, stop: float):
        if s is None:
            return
        s.stop_price = stop
        s.dirty = True

    def flat_all(self, reason: str):
        for s in self.syms:
            if s.traded and (s.qty != 0 or s.target_qty != 0 or s.working is not None):
                self.set_target(s, 0, M.NAN, reason)

    def _flush(self):
        dirty = [s for s in self.syms if s.traded and s.dirty]
        if self.warming_up:
            for s in dirty:
                s.dirty = False
                s.target_qty = s.qty
                s.working = None
            return
        for s in [x for x in dirty if abs(x.target_qty) < abs(x.qty) or x.target_qty * x.qty < 0]:
            s.dirty = False
            self._sync(s)
        for s in [x for x in dirty if x.dirty]:
            s.dirty = False
            self._sync(s)

    def _sync(self, s: Sym):
        if s.working is not None:
            same_kind = s.working.kind == s.order_kind
            if s.qty + s.working.delta == s.target_qty and same_kind:
                self._sync_stop(s)
                return
            s.working = None          # annulation (immediate en historique)
        cur = s.qty
        step = 0 if (cur != 0 and s.target_qty != 0 and (cur > 0) != (s.target_qty > 0)) else s.target_qty
        delta = step - cur
        if delta == 0:
            self._sync_stop(s)
            return
        if abs(step) > abs(cur):
            verdict, why = self._check_increase(s)
            if verdict:
                self.nx(f"Entree rejetee {s.name} : {why}")
                self.signal(self.now, s.name, "entree_rejetee", why)
                s.target_qty = cur
                self._sync_stop(s)
                return
        lim = self.round_price(s, s.limit_price) if s.order_kind == "limit" else M.NAN
        kind = "limit" if s.order_kind == "limit" and M.ok(lim) and lim > 0 else "market"
        s.working = Order(delta, kind, lim, s.limit_expiry_count, s.pending_reason)

    def _check_increase(self, s: Sym):
        ok_, why = self.breaker.can_open(self.now)
        if not ok_:
            return True, why
        allow, extra = self.allow_increase(s)
        if not allow:
            return True, extra or "veto de la strategie"
        return False, None

    def _sync_stop(self, s: Sym):
        if self.p.stop_mode != "natif" or s.stop_rejected:
            return
        cur = s.qty
        if cur == 0 or not M.ok(s.stop_price) or s.stop_price <= 0:
            return
        px = self.round_price(s, s.stop_price)
        breached = M.ok(s.last_price) and ((cur > 0 and s.last_price <= px) or (cur < 0 and s.last_price >= px))
        if breached:
            if s.working is not None:
                return
            self.nx(f"Stop {s.name} deja franchi ({s.last_price} vs stop {px}) -> sortie au marche")
            s.target_qty, s.stop_price, s.pending_reason, s.order_kind = 0, M.NAN, "stop franchi", "market"
            s.dirty = True

    # =========================================================================
    #  Barres : executions, historique, stops
    # =========================================================================
    def _bar_phase(self, s: Sym, k: int, now):
        if s.traded:
            self._fill_phase(s, k, now)
        s.hist.count = k + 1
        s.last_price = float(s.hist.close[k])
        if s.traded:
            self._expire_limit(s)
            self._soft_stop(s, k, now)

    def _fill_phase(self, s: Sym, k: int, now):
        h = s.hist
        o, hi, lo = float(h.open[k]), float(h.high[k]), float(h.low[k])
        held_side = s.qty
        entry_px = M.NAN
        w = s.working
        if w is not None:
            px = None
            if w.kind == "market":
                px = o
            elif w.delta > 0:
                px = o if o < w.limit else (w.limit if lo < w.limit else None)
            else:
                px = o if o > w.limit else (w.limit if hi > w.limit else None)
            if px is not None:
                s.working = None
                entry_px = px
                self._apply_fill(s, w.delta, px, now, w.reason)
                if s.target_qty != s.qty:
                    s.dirty = True        # inversion : la seconde etape partira au prochain flush
        if self.p.stop_mode == "natif" and not s.stop_rejected and s.qty != 0 and M.ok(s.stop_price) and s.stop_price > 0:
            st = self.round_price(s, s.stop_price)
            held_at_open = held_side != 0 and (held_side > 0) == (s.qty > 0)
            fill = None
            if s.qty > 0:
                if held_at_open and o <= st:
                    fill = o
                elif lo <= st:
                    fill = st if held_at_open or not M.ok(entry_px) else min(st, entry_px)
            else:
                if held_at_open and o >= st:
                    fill = o
                elif hi >= st:
                    fill = st if held_at_open or not M.ok(entry_px) else max(st, entry_px)
            if fill is not None:
                q = s.qty
                self._apply_fill(s, -q, fill, now, "stop")
                s.stopped_out, s.stopped_time = True, now
                s.target_qty = s.qty
                s.stop_price = M.NAN
                s.working = None
                self.nx(f"Stop execute {s.name} x{abs(q)} @ {fill:.4f}")
                self.on_stopped(s)

    def _expire_limit(self, s: Sym):
        w = s.working
        if w is None or w.kind != "limit":
            return
        if s.hist.count < w.expiry_count:
            return
        s.target_qty = s.qty
        s.working = None

    def _soft_stop(self, s: Sym, k: int, now):
        soft = self.p.stop_mode == "logiciel" or s.stop_rejected
        if not soft or s.qty == 0 or not M.ok(s.stop_price):
            return
        hit = s.hist.low[k] <= s.stop_price if s.qty > 0 else s.hist.high[k] >= s.stop_price
        if not hit:
            return
        self.nx(f"Stop logiciel touche {s.name} (stop {s.stop_price}) -> sortie au marche")
        s.stopped_out, s.stopped_time = True, now
        self.set_target(s, 0, M.NAN, "stop logiciel")
        self.on_stopped(s)

    # =========================================================================
    #  Comptabilite (ApplyFill / OpenTrade / CloseTrade)
    # =========================================================================
    def _apply_fill(self, s: Sym, signed_qty, price: float, time, reason: str):
        if signed_qty == 0:
            return
        vpp = self.value_per_point(s)
        cost = self.costs.cost(s.asset_class, abs(signed_qty) * price * vpp, abs(signed_qty))
        self.realized_net -= cost
        self.fills.append((time, s.name, signed_qty, price, cost, reason))
        if s.qty == 0:
            self._open_trade(s, signed_qty, price, time, cost)
        elif (signed_qty > 0) == (s.qty > 0):
            s.avg_price = (s.avg_price * abs(s.qty) + price * abs(signed_qty)) / (abs(s.qty) + abs(signed_qty))
            s.qty += signed_qty
            s.trade_costs += cost
            s.max_qty = max(s.max_qty, abs(s.qty))
            s.max_notional = max(s.max_notional, self.notional(s, s.qty, price))
        else:
            close_q = min(abs(signed_qty), abs(s.qty))
            sgn = 1 if s.qty > 0 else -1
            pnl = (price - s.avg_price) * close_q * vpp * sgn
            self.realized_net += pnl
            s.trade_gross += pnl
            s.trade_costs += cost
            remainder = abs(signed_qty) - close_q
            s.qty += (1 if signed_qty > 0 else -1) * close_q
            if s.qty == 0:
                self._close_trade(s, price, time, reason)
                if remainder > 0:
                    self._open_trade(s, (1 if signed_qty > 0 else -1) * remainder, price, time, 0.0)
        try:
            self.on_fill(s, signed_qty, price, time)
        except Exception as ex:  # pragma: no cover
            self.nx(f"Erreur on_fill : {ex}")

    def _open_trade(self, s: Sym, signed_qty, price, time, cost):
        s.qty = signed_qty
        s.avg_price = price
        s.open_time = time
        s.entry_day = s.hist.last_date
        s.entry_bar_count = s.hist.count
        s.trade_gross = 0.0
        s.trade_costs = cost
        s.max_qty = abs(signed_qty)
        s.max_notional = self.notional(s, signed_qty, price)
        s.direction = 1 if signed_qty > 0 else -1
        s.entry_reason = s.pending_reason or ""
        s.stopped_out = False

    def _close_trade(self, s: Sym, price, time, reason):
        net = s.trade_gross - s.trade_costs
        r = TradeRecord(self.strategy_id, s.name, s.asset_class, s.direction, s.max_qty, s.open_time, time,
                        s.avg_price, price, s.max_notional, s.trade_gross, s.trade_costs, net,
                        net / s.max_notional if s.max_notional > 0 else 0.0,
                        s.trade_gross / s.max_notional if s.max_notional > 0 else 0.0,
                        s.entry_reason, reason or "", s.regime)
        self.record_trade(r)
        self.on_trade_closed(s, r)

    def record_trade(self, r: TradeRecord):
        self.closed_trades.append(r)
        self.stats.add(r.net_return)

    # =========================================================================
    #  Boucle principale
    # =========================================================================
    def _update_equity(self, now, day):
        eq = self.equity
        if self.breaker.update(now.to_pydatetime() if hasattr(now, "to_pydatetime") else now, day, eq) and self.breaker.last_event:
            self.nx(self.breaker.last_event)

    def run(self, data: dict, start=None, end=None, trade_start=None, report: bool = True) -> BacktestResult:
        """Lance le backtest sur {symbole: DataFrame OHLCV}. start/end : bornes des donnees ;
        trade_start : premier jour ou les ordres sont autorises (chauffage avant)."""
        self._prepare(data, start, end, trade_start)
        self.on_data_loaded()
        order = self.syms
        pos = [self.pos[s.name] for s in order]
        for i, ts in enumerate(self.master):
            self.now = ts.to_pydatetime()
            day = ts.normalize()
            bar = [(s, pk[i]) for s, pk in zip(order, pos) if pk[i] >= 0]
            if not bar:
                continue
            if self.BATCH_MODE:
                for s, k in bar:
                    self._bar_phase(s, int(k), self.now)
                self._update_equity(self.now, day)
                self.batch_count += 1
                self.last_batch_day = day
                try:
                    self.on_batch(day)
                except Exception as ex:
                    self.nx(f"Erreur on_batch({day:%Y-%m-%d}) : {ex!r}")
                    raise
                self._flush()
            else:
                for s, k in bar:
                    self._bar_phase(s, int(k), self.now)
                    self._update_equity(self.now, day)
                    self.on_symbol_bar(s, day)
                    self._flush()
                self.batch_count += 1
                self.last_batch_day = day
            eq_now = self.equity
            gross = sum(abs(s.qty) * s.last_price * self.value_per_point(s) for s in order if s.traded and s.qty != 0)
            expo = gross / eq_now if eq_now > 0 else M.NAN
            if self.equity_days and self.equity_days[-1] == day:
                self.equity_values[-1] = eq_now
                self.exposure_values[-1] = expo
            else:
                self.equity_days.append(day)
                self.equity_values.append(eq_now)
                self.exposure_values.append(expo)
        return self._finalize(report)

    def _finalize(self, report: bool) -> BacktestResult:
        from .report import build_report
        eq = pd.Series(self.equity_values, index=pd.DatetimeIndex(self.equity_days), name="equity")
        if self.trade_start is not None:
            eq = eq[eq.index >= self.trade_start.normalize()]
        expo = pd.Series(self.exposure_values, index=pd.DatetimeIndex(self.equity_days), name="exposition_brute")
        expo = expo.reindex(eq.index)
        rets = eq.pct_change().dropna()
        fills = pd.DataFrame(self.fills, columns=["time", "symbol", "qty", "price", "cost", "reason"])
        res = BacktestResult(strategy=self, name=self.strategy_id, params=dict(self.params), equity=eq, returns=rets,
                             trades=list(self.closed_trades), fills=fills, log=list(self.log), signals=list(self.signals),
                             breaker_events=list(self.breaker.events), exposure=expo, report="")
        open_pos = [StressPosition(s.name, s.qty, s.last_price, s.stop_price, self.value_per_point(s))
                    for s in self.syms if s.traded and s.qty != 0 and M.ok(s.last_price)]
        res.open_positions = {s.name: s.qty for s in self.syms if s.traded and s.qty != 0}
        res.stress = stress_test(open_pos, self.equity, self.p.stress_shock_pct / 100.0, self.p.stress_worst_n)
        if report:
            extras: list[str] = []
            if self.probe_entries:
                extras.append(f"Entrees en taille sonde ({self.p.no_edge_fraction_pct:.2f} %) parce que Kelly <= 0 : {self.probe_entries} "
                              "-> l avantage estime est negatif ; la fiche B recommande de ne pas trader.")
            try:
                self.report_extras(extras)
            except Exception as ex:  # pragma: no cover
                extras.append(f"(erreur extras : {ex})")
            extras.append(res.stress)
            res.report = build_report(res, extras)
        return res


# ---------------------------------------------------------------------------
def D_split(s) -> list[str]:
    if s is None:
        return []
    if isinstance(s, (list, tuple)):
        items = s
    else:
        items = [x for x in str(s).replace(";", ",").replace("|", ",").replace("\n", ",").split(",")]
    out, seen = [], set()
    for x in items:
        x = str(x).strip()
        if x and x.upper() not in seen:
            seen.add(x.upper())
            out.append(x)
    return out


def _parse_map(s) -> dict:
    if isinstance(s, dict):
        return dict(s)
    out = {}
    for item in D_split(s):
        k = item.find("=")
        if k < 0:
            k = item.find(":")
        if k <= 0:
            continue
        out[item[:k].strip()] = item[k + 1:].strip()
    return out


parse_map = _parse_map
split_list = D_split


def _lookup(data: dict, name: str):
    if name in data:
        return data[name]
    up = name.upper()
    for k, v in data.items():
        if k.upper() == up:
            return v
    return None
