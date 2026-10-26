"""FICHE 11 - Options : puts couverts par du cash + calls couverts, la "roue" (port de Strategies/Nexus11_OptionsWheel.cs).

Prime de variance : Bondarenko / Cboe, vol implicite moyenne S&P 500 ~19.3 % vs 15.1 % realisee (1990-2018).
Israelov, Nielsen : dans un call couvert, la jambe "vente de vol" a un Sharpe proche de 1 ; la jambe
"pari sur un retournement" pese ~25 % du risque.

REGLES
  - Cycle : vendre un put couvert par du cash ; si assigne, vendre des calls couverts sur les actions recues ;
    si appele, recommencer.
  - Echeance 30 a 45 jours (mensuelle du 3e vendredi de preference).
  - Strike du put : delta -0.20 a -0.30 ; du call : delta 0.20 a 0.30 ET au-dessus du prix de revient.
  - Prise de benefice : racheter a 50 % de la prime encaissee.
  - A 21 jours de l echeance : cloturer, rouler, ou (defaut) cloturer si hors de la monnaie et laisser aller a
    l echeance si dans la monnaie (la roue tourne).
  - Filtre de spread : (ask-bid)/mid <= 5 %, spread <= 0.10 $, prime >= 0.30 $.
  - GARDE-FOU : jamais de call sur des actions qui ont un ordre de vente en attente (call NU sinon).
  - Capital : un put couvert immobilise strike x 100 en cash.

MODES (pas de chaine d options historique dans les donnees) :
  - synthetique (defaut) : prix Black-Scholes, vol implicite = vol realisee 20 j x 1.28 (prime de variance) ou
    indice de vol (VIX, VXN...) ; spread modelise ; PnL suivi hors moteur d ordres (equity via extra_equity) ;
  - signal_seul : meme moteur, chaque "ticket" (vente, rachat, assignation) est aussi ecrit au journal
    pour une execution manuelle ou par un autre robot.
Le routage reel d ordres d options (mode CompteNT_Experimental du C#) n a pas d equivalent ici.

Points d attention : 80 % de trades gagnants ne dit rien du rendement - le rapport met en avant la PIRE PERTE
MENSUELLE ; il decompose aussi les options vendues en PnL brut vs couvert en delta (Israelov-Nielsen).
L assignation anticipee (options americaines) n est pas modelisee.

Comptabilite des trades : la jambe option porte la valeur intrinseque payee a l echeance (K - S pour un put
assigne, S - K pour un call appele) ; la jambe action va donc du cours a l assignation au cours a l appel.
(Le C# partait du strike : la perte intrinseque etait comptee deux fois dans les trades, pas dans l equity.)
La somme des PnL des trades fermes egale ainsi la variation de l equity hors positions ouvertes.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from .. import mathx as M
from ..engine import NexusStrategy, parse_map
from ..risk import TradeRecord

LIBRE, PUT_VENDU, ACTIONS, CALL_VENDU = "Libre", "PutVendu", "Actions", "CallVendu"


@dataclass
class Opt:
    is_call: bool
    k: float
    expiry: pd.Timestamp
    contracts: int
    premium: float              # par action, net du glissement
    open_iv: float
    open_day: pd.Timestamp
    last_s: float = M.NAN
    last_delta: float = 0.0
    hedge_pnl: float = 0.0      # PnL d une couverture en delta (analyse Israelov-Nielsen)
    label: str = ""


@dataclass
class Wheel:
    etat: str = LIBRE
    option: Opt | None = None
    shares: int = 0
    cost_basis: float = 0.0     # prix de revient de la fiche (strike, ou strike - prime) : plancher du strike des calls
    stock_mark: float = 0.0     # cours moyen a l assignation : base comptable de la jambe action (la jambe put a deja paye K - S)
    shares_since: object = None
    cash: float = 0.0           # flux cumules : primes, rachats, frais, achats/ventes d actions synthetiques
    last_s: float = M.NAN
    counters: dict = field(default_factory=lambda: dict(cycles=0, assignments=0, called_away=0, rolls=0, profit_takes=0,
                                                        spread_rejects=0, capital_rejects=0, guard_blocks=0))


def third_friday(year: int, month: int) -> pd.Timestamp:
    first = pd.Timestamp(year, month, 1)
    offset = (4 - first.weekday() + 7) % 7
    return first + pd.Timedelta(days=offset + 14)


def choose_expiry(day, dte_min: int, dte_max: int) -> pd.Timestamp:
    d0 = pd.Timestamp(day).normalize()
    for m in range(4):
        d = d0 + pd.DateOffset(months=m)
        tf = third_friday(d.year, d.month)
        dte = (tf - d0).days
        if dte_min <= dte <= dte_max:
            return tf
    f = d0 + pd.Timedelta(days=dte_min)
    while f.weekday() != 4:
        f += pd.Timedelta(days=1)
    return f


class Nexus11OptionsWheel(NexusStrategy):
    NAME = "Nexus11_OptionsWheel"
    DESCRIPTION = ("Fiche 11 - Wheel : put couvert (delta -0.25, 30-45 j) puis calls couverts au-dessus du prix de revient ; "
                   "rachat a 50 %, gestion a 21 j, filtre de spread, garde-fou d ordre de vente en attente.")
    BATCH_MODE = False
    DEFAULTS = dict(
        symbols="SPY,QQQ,IWM,AAPL,MSFT,F,T,SOFI",
        sizing_mode="natif",
        stop_mode="aucun",
        mode="synthetique",                 # synthetique | signal_seul
        dte_min=30,
        dte_max=45,
        put_delta=-0.25,
        put_delta_min=-0.30,
        put_delta_max=-0.20,
        call_delta=0.25,
        call_delta_min=0.20,
        call_delta_max=0.30,
        profit_take_pct=50.0,
        manage_at_dte=21,
        at_21_days="assignation_si_dans_la_monnaie",   # cloturer | rouler | assignation_si_dans_la_monnaie
        vol_source="vol_realisee_ratio",    # vol_realisee_ratio | indice_de_vol
        iv_to_rv_ratio=1.28,
        rv_window_days=20,
        iv_index_map="SPY=^VIX;QQQ=^VXN",
        risk_free_pct=4.0,
        dividend_yield_pct=0.0,
        strike_step=0.0,                    # 0 = pas automatique (0.5 / 1 / 5 / 10 selon le prix)
        spread_max_pct=5.0,
        max_spread_abs=0.10,
        min_premium=0.30,
        model_spread_abs=0.03,
        model_spread_pct=2.0,
        fill_penalty_pct=50.0,              # remplissage entre le mid (0 %) et le bid/ask (100 %)
        fee_per_contract=0.65,
        max_allocation_pct=25.0,
        max_contracts=5,
        use_adjusted_cost_basis=False,
        execute_stock_leg=False,            # True = les actions assignees passent par le moteur d ordres
    )

    def required_references(self):
        return list(parse_map(self.p.iv_index_map).values()) if self.p.vol_source == "indice_de_vol" else []

    def on_data_loaded(self):
        p = self.p
        if p.mode not in ("synthetique", "signal_seul"):
            raise ValueError("mode : synthetique | signal_seul (le routage reel d options n existe qu en NinjaTrader)")
        self.iv_map = {k.upper(): v for k, v in parse_map(p.iv_index_map).items()}
        self.wheels: dict[str, Wheel] = {s.name: Wheel() for s in self.traded_syms}
        self.call_pnl_raw = self.call_pnl_hedged = self.put_pnl_raw = self.put_pnl_hedged = 0.0
        self.iv_used: list[float] = []
        self.rv_after: list[float] = []
        self.iv_checks: list[tuple] = []        # (symbole, indice de barre, iv)
        bank = p.initial_bankroll
        self.nx(f"Un put couvert exige ~strike x 100 de cash : avec {bank:.0f} $ et {p.max_allocation_pct:.0f} % max par sous-jacent, "
                f"prix max du sous-jacent ~{bank * p.max_allocation_pct / 100.0 / 100.0:.2f} $.")

    def nxv(self, msg: str):
        if self.p.verbose:
            self.nx(msg)

    # =========================================================================
    #  Outils de prix
    # =========================================================================
    def iv(self, s) -> float:
        p = self.p
        if p.vol_source == "indice_de_vol":
            v = self.sym(self.iv_map.get(s.name.upper()))
            if v is not None and v.hist.count > 0 and v.hist.last_close > 0:
                return v.hist.last_close / 100.0
        rv = s.hist.realized_vol(p.rv_window_days)
        return max(0.05, rv * p.iv_to_rv_ratio) if M.ok(rv) and rv > 0 else M.NAN

    def step(self, price: float) -> float:
        if self.p.strike_step > 0:
            return self.p.strike_step
        return 0.5 if price < 25 else 1.0 if price < 200 else 5.0 if price < 1000 else 10.0

    @staticmethod
    def years(day, expiry) -> float:
        return max(0.0, (pd.Timestamp(expiry).normalize() - pd.Timestamp(day).normalize()).days) / 365.0

    def model_spread(self, mid: float) -> float:
        return self.p.model_spread_abs + self.p.model_spread_pct / 100.0 * mid

    def spread_filter(self, bid: float, ask: float) -> str | None:
        """Filtre de spread a plusieurs niveaux ; None si accepte, sinon la raison."""
        p = self.p
        mid, spr = 0.5 * (bid + ask), ask - bid
        if not mid > 0 or bid <= 0:
            return "cotation invalide"
        if mid < p.min_premium:
            return f"niveau 3 : prime {mid:.2f} $ < {p.min_premium:.2f} $"
        if spr > p.max_spread_abs:
            return f"niveau 2 : spread {spr:.2f} $ > {p.max_spread_abs:.2f} $"
        if spr / mid > p.spread_max_pct / 100.0:
            return f"niveau 1 : spread {spr / mid:.1%} du mid > {p.spread_max_pct:.1f} %"
        return None

    @staticmethod
    def option_label(s, is_call: bool, exp, k: float) -> str:
        return f"{s.name} {pd.Timestamp(exp):%Y-%m-%d} {'C' if is_call else 'P'}{k:g}"

    def bs(self, is_call, S, K, T, iv):
        return M.bs_price(is_call, S, K, T, self.p.risk_free_pct / 100.0, iv, self.p.dividend_yield_pct / 100.0)

    def delta(self, is_call, S, K, T, iv):
        return M.bs_delta(is_call, S, K, T, self.p.risk_free_pct / 100.0, iv, self.p.dividend_yield_pct / 100.0)

    # =========================================================================
    #  Boucle quotidienne
    # =========================================================================
    def on_symbol_bar(self, s, day):
        if not s.traded:
            return
        w = self.wheels.get(s.name)
        if w is None:
            return
        p = self.p
        S = s.hist.last_close
        if s.hist.count < p.rv_window_days + 5 or not S > 0:
            return
        iv = self.iv(s)
        if not M.ok(iv):
            return
        self.check_iv_after(s)
        # Analyse delta-couverte : PnL de la couverture depuis la veille.
        o = w.option
        if o is not None and M.ok(o.last_s):
            o.hedge_pnl += o.last_delta * (S - o.last_s) * 100.0 * o.contracts
        if o is not None:
            o.last_delta = self.delta(o.is_call, S, o.k, self.years(day, o.expiry), iv)
            o.last_s = S
        w.last_s = S
        if self.warming_up:
            return
        if w.etat == LIBRE:
            self.open_short(s, w, False, day, S, iv)
        elif w.etat == ACTIONS:
            self.open_short(s, w, True, day, S, iv)
        else:
            self.manage(s, w, day, S, iv)

    def committed_cash(self) -> float:
        c = 0.0
        for w in self.wheels.values():
            if w.option is not None and not w.option.is_call:
                c += w.option.k * 100.0 * w.option.contracts
            if w.shares > 0 and not self.p.execute_stock_leg and M.ok(w.last_s):
                c += w.shares * w.last_s
        return c

    def open_short(self, s, w: Wheel, is_call: bool, day, S: float, iv: float):
        p = self.p
        if not is_call:
            ok, br = self.breaker.can_open(self.now)
            if not ok:
                self.nxv(f"{s.name} : put non vendu ({br})")
                return
        exp = choose_expiry(day, p.dte_min, p.dte_max)
        T = self.years(day, exp)
        if T <= 0:
            return
        step = self.step(S)
        k = M.bs_strike_from_delta(is_call, S, T, p.risk_free_pct / 100.0, iv, p.call_delta if is_call else p.put_delta,
                                   p.dividend_yield_pct / 100.0)
        if not M.ok(k) or k <= 0:
            return
        k = math.ceil(k / step) * step if is_call else math.floor(k / step) * step
        # Bande en valeur absolue du delta : |delta| trop grand = trop pres de la monnaie -> s eloigner de S ;
        # trop petit = trop loin -> se rapprocher (call : K vers le bas, put : K vers le haut).
        lo_b, hi_b = (p.call_delta_min, p.call_delta_max) if is_call else (p.put_delta_min, p.put_delta_max)
        mag_lo, mag_hi = min(abs(lo_b), abs(hi_b)), max(abs(lo_b), abs(hi_b))
        for _ in range(8):
            m = abs(self.delta(is_call, S, k, T, iv))
            if m > mag_hi:
                k += step if is_call else -step
            elif m < mag_lo and k - step > 0:
                k += -step if is_call else step
            else:
                break
        final_mag = abs(self.delta(is_call, S, k, T, iv))
        call_above_basis_only = is_call and k < w.cost_basis       # le prix de revient prime sur la bande
        if not call_above_basis_only and (final_mag < mag_lo - 1e-9 or final_mag > mag_hi + 1e-9):
            w.counters["spread_rejects"] += 1
            self.nxv(f"{s.name} : aucun strike dans la bande |delta| {mag_lo:.2f}-{mag_hi:.2f} (pas {step}, |delta| {final_mag:.3f})")
            return
        if is_call:
            why = self.pending_sell(s)
            if why:
                w.counters["guard_blocks"] += 1
                self.nx(f"ALERTE GARDE-FOU {s.name} : {why} -> call NON vendu (eviterait un call nu)")
                return
            if k < w.cost_basis:
                k = math.ceil(w.cost_basis / step) * step         # au-dessus du prix de revient
            contracts = w.shares // 100
            if contracts <= 0:
                w.etat = LIBRE
                return
        else:
            bank = self.bankroll()
            avail = min(bank - self.committed_cash(), bank * p.max_allocation_pct / 100.0)
            contracts = min(p.max_contracts, int(math.floor(avail / (k * 100.0)))) if avail > 0 else 0
            if contracts <= 0:
                w.counters["capital_rejects"] += 1
                self.nx_once("cap" + s.name, f"{s.name} : capital insuffisant pour un put couvert (strike {k:g} x 100 = "
                                             f"{k * 100:.0f} $ > {max(0.0, avail):.0f} $ disponibles).")
                return
        mid = self.bs(is_call, S, k, T, iv)
        spr = self.model_spread(mid)
        bid, ask = mid - spr / 2, mid + spr / 2
        reject = self.spread_filter(bid, ask)
        label = self.option_label(s, is_call, exp, k)
        if reject is not None:
            w.counters["spread_rejects"] += 1
            self.nxv(f"{label} rejete par le filtre de spread : {reject}")
            return
        fill = mid - p.fill_penalty_pct / 100.0 * (mid - bid)
        o = Opt(is_call, k, exp, contracts, fill, iv, pd.Timestamp(day), S, self.delta(is_call, S, k, T, iv), label=label)
        w.cash += fill * 100.0 * contracts - contracts * p.fee_per_contract
        w.option = o
        w.etat = CALL_VENDU if is_call else PUT_VENDU
        if not is_call:
            w.counters["cycles"] += 1
        self.iv_checks.append((s.name, s.hist.count, iv))
        self.ticket(s, f"VENDRE {label} x{contracts} @ {fill:.2f} (mid {mid:.2f}, delta {o.last_delta:.2f}, IV {iv:.1%}, "
                       f"collateral {0 if is_call else k * 100 * contracts:.0f} $)")

    def manage(self, s, w: Wheel, day, S: float, iv: float):
        p = self.p
        o = w.option
        if o is None:
            w.etat = ACTIONS if w.shares > 0 else LIBRE
            return
        T = self.years(day, o.expiry)
        dte = (pd.Timestamp(o.expiry).normalize() - pd.Timestamp(day).normalize()).days
        itm = S > o.k if o.is_call else S < o.k
        if dte <= 0:
            self.settle(s, w, S, day)
            return
        value = self.bs(o.is_call, S, o.k, T, iv)
        buy = value + p.fill_penalty_pct / 100.0 * self.model_spread(value) / 2.0
        if buy <= (1 - p.profit_take_pct / 100.0) * o.premium:
            w.counters["profit_takes"] += 1
            self.close_option(s, w, buy, f"prise de benefice {p.profit_take_pct:g} %")
            return
        if dte <= p.manage_at_dte:
            if p.at_21_days == "cloturer" or (p.at_21_days == "assignation_si_dans_la_monnaie" and not itm):
                self.close_option(s, w, buy, f"gestion a {p.manage_at_dte} jours")
            elif p.at_21_days == "rouler":
                w.counters["rolls"] += 1
                was_call = o.is_call
                self.close_option(s, w, buy, f"roulement a {p.manage_at_dte} jours")
                self.open_short(s, w, was_call, day, S, iv)
            # assignation_si_dans_la_monnaie + dans la monnaie : on laisse aller a l echeance.

    def close_option(self, s, w: Wheel, buy_price: float, reason: str):
        p = self.p
        o = w.option
        w.cash -= buy_price * 100.0 * o.contracts + o.contracts * p.fee_per_contract
        pnl = (o.premium - buy_price) * 100.0 * o.contracts - 2.0 * o.contracts * p.fee_per_contract
        self.record_option_trade(s, o, buy_price, pnl, reason)
        self.ticket(s, f"RACHETER {o.label} x{o.contracts} @ {buy_price:.2f} ({reason}) PnL {pnl:.2f} $")
        w.option = None
        w.etat = ACTIONS if w.shares > 0 else LIBRE

    def settle(self, s, w: Wheel, S: float, day):
        p = self.p
        o = w.option
        itm = S > o.k if o.is_call else S < o.k
        intrinsic = abs(S - o.k) if itm else 0.0
        pnl = (o.premium - intrinsic) * 100.0 * o.contracts - o.contracts * p.fee_per_contract
        self.record_option_trade(s, o, intrinsic, pnl, ("appele a l echeance" if o.is_call else "assigne a l echeance") if itm
                                 else "expire sans valeur")
        shares = 100 * o.contracts
        if not o.is_call:
            if itm:
                # Assignation : achat de 100 x n actions au strike.
                w.counters["assignments"] += 1
                w.cost_basis = o.k - o.premium if p.use_adjusted_cost_basis else o.k
                w.stock_mark = (w.stock_mark * w.shares + S * shares) / (w.shares + shares)
                w.shares_since = day
                w.shares += shares
                if p.execute_stock_leg:
                    # Actions reelles achetees au marche (~S) : la perte intrinseque (K - S) est soldee cote option.
                    w.cash -= intrinsic * shares
                    self.set_target(s, s.target_qty + shares, M.NAN, "assignation du put " + o.label)
                else:
                    w.cash -= o.k * shares
                w.etat = ACTIONS
                self.ticket(s, f"ASSIGNATION {o.label} : +{shares} actions a {o.k:.2f} (cours {S:.2f})")
            else:
                w.etat = ACTIONS if w.shares > 0 else LIBRE
        else:
            if itm:
                # Appel : vente des actions au strike.
                w.counters["called_away"] += 1
                sold = min(w.shares, shares)
                # La jambe call a deja paye S - K a l echeance : la jambe action va du cours d assignation au cours d appel.
                stock_pnl = (S - w.stock_mark) * sold
                self.record_stock_trade(s, w, S, sold, day, stock_pnl)
                w.shares -= sold
                if p.execute_stock_leg:
                    w.cash -= intrinsic * sold
                    self.set_target(s, max(0, s.target_qty - sold), M.NAN, "actions appelees " + o.label)
                else:
                    w.cash += o.k * sold
                self.ticket(s, f"APPELE {o.label} : -{sold} actions a {o.k:.2f} (cours {S:.2f}, PnL jambe action {stock_pnl:.2f} $)")
            w.etat = ACTIONS if w.shares > 0 else LIBRE
        w.option = None

    # =========================================================================
    #  Comptabilite synthetique (equity du moteur via extra_equity)
    # =========================================================================
    def extra_equity(self) -> float:
        """Flux de tresorerie + actions synthetiques au marche - valeur des options vendues ouvertes."""
        if not hasattr(self, "wheels"):
            return 0.0
        e = 0.0
        for name, w in self.wheels.items():
            e += w.cash
            s = self.sym(name)
            S = s.last_price if s is not None and M.ok(s.last_price) else w.last_s
            if not M.ok(S):
                continue
            if w.shares > 0 and not self.p.execute_stock_leg:
                e += w.shares * S
            o = w.option
            if o is not None:
                iv = self.iv(s) if s is not None else M.NAN
                d = s.hist.last_date if s is not None and s.hist.count > 0 else o.open_day
                v = (self.bs(o.is_call, S, o.k, self.years(d, o.expiry), iv) if M.ok(iv)
                     else max(0.0, S - o.k if o.is_call else o.k - S))
                e -= v * 100.0 * o.contracts
        return e

    def record_option_trade(self, s, o: Opt, close_price: float, pnl: float, reason: str):
        p = self.p
        collateral = o.k * 100.0 * o.contracts            # capital immobilise (cash du put ou actions du call)
        hedged = pnl + o.hedge_pnl
        fees = (1.0 if reason.startswith("expire") or "echeance" in reason else 2.0) * o.contracts * p.fee_per_contract
        if o.is_call:
            self.call_pnl_raw += pnl
            self.call_pnl_hedged += hedged
        else:
            self.put_pnl_raw += pnl
            self.put_pnl_hedged += hedged
        self.record_trade(TradeRecord(
            self.strategy_id, o.label, "Option", -1, o.contracts, o.open_day, s.hist.last_date, o.premium, close_price, collateral,
            pnl + fees, fees, pnl, pnl / collateral if collateral > 0 else 0.0, (pnl + fees) / collateral if collateral > 0 else 0.0,
            ("call couvert" if o.is_call else "put couvert") + f" IV {o.open_iv:.1%}", reason))

    def record_stock_trade(self, s, w: Wheel, exit_price: float, qty: int, day, pnl: float):
        if self.p.execute_stock_leg or qty <= 0:
            return                                         # la jambe action reelle est comptee par le moteur
        notional = w.stock_mark * qty
        self.record_trade(TradeRecord(
            self.strategy_id, s.name + " (actions wheel)", s.asset_class, 1, qty, w.shares_since, day, w.stock_mark, exit_price,
            notional, pnl, 0.0, pnl, pnl / notional if notional > 0 else 0.0, pnl / notional if notional > 0 else 0.0,
            "assignation", "appele"))

    def check_iv_after(self, s):
        """Prime de variance : IV utilisee a l ouverture vs vol realisee sur les 21 jours suivants."""
        keep = []
        for name, k0, iv in self.iv_checks:
            if name != s.name or s.hist.count < k0 + 21:
                keep.append((name, k0, iv))
                continue
            rets = [s.hist.log_return_at(k) for k in range(k0 + 1, min(k0 + 22, s.hist.count))]
            rv = M.std(rets) * math.sqrt(252) if rets else M.NAN
            if M.ok(rv):
                self.iv_used.append(iv)
                self.rv_after.append(rv)
        self.iv_checks = keep

    # =========================================================================
    #  Garde-fou et tickets
    # =========================================================================
    def pending_sell(self, s) -> str | None:
        """Ordre de vente en attente sur le sous-jacent (jambe action executee par le moteur)."""
        w = s.working
        if w is not None and w.delta < 0:
            return f"ordre de vente de la strategie en attente ({w.reason})"
        if s.dirty and s.target_qty < s.qty:
            return "reduction de position en attente"
        return None

    def ticket(self, s, text: str):
        self.signal(self.now, s.name, "ticket_option", text)
        if self.p.mode == "signal_seul":
            self.nx("TICKET " + text)
        else:
            self.nxv(text)

    # =========================================================================
    #  Rapport
    # =========================================================================
    def report_extras(self, lines):
        p = self.p
        lines.append(f"Mode : {p.mode} | source de vol : {p.vol_source}" + (f" x{p.iv_to_rv_ratio}" if p.vol_source == "vol_realisee_ratio" else ""))
        for name, w in self.wheels.items():
            c = w.counters
            lines.append(f"{name:<6} etat {w.etat:<9} cycles {c['cycles']} assignations {c['assignments']} appels {c['called_away']} "
                         f"rachats 50% {c['profit_takes']} roulements {c['rolls']} rejets spread {c['spread_rejects']} capital "
                         f"{c['capital_rejects']} garde-fou {c['guard_blocks']} | actions {w.shares}")
        opts = [t for t in self.closed_trades if t.asset_class == "Option"]
        if opts:
            lines.append(f"Options fermees : {len(opts)} | gagnantes {sum(1 for t in opts if t.net_pnl > 0) / len(opts):.0%} | "
                         f"pire trade {min(t.net_pnl for t in opts):.2f} $ | meilleur {max(t.net_pnl for t in opts):.2f} $")
        # Pire perte mensuelle (metrique principale de la fiche).
        if self.equity_values:
            eq = pd.Series(self.equity_values, index=pd.DatetimeIndex(self.equity_days))
            if self.trade_start is not None:
                eq = eq[eq.index >= self.trade_start.normalize()]
            if len(eq) > 1:
                m_end = eq.groupby(eq.index.to_period("M")).last()
                m_start = eq.shift(1).fillna(eq.iloc[0]).groupby(eq.index.to_period("M")).first()
                mret = m_end / m_start - 1
                worst = mret.idxmin()
                lines.append(f"PIRE PERTE MENSUELLE : {mret.min():.2%} ({worst}) - le taux de reussite ne dit rien des pertes rares")
        lines.append(f"Israelov-Nielsen : calls vendus PnL brut {self.call_pnl_raw:.2f} $ vs couvert en delta {self.call_pnl_hedged:.2f} $ | "
                     f"puts brut {self.put_pnl_raw:.2f} $ vs couvert {self.put_pnl_hedged:.2f} $")
        lines.append("  (brut - couvert = pari directionnel non remunere ; couvrir cette exposition ameliore le Sharpe selon Israelov-Nielsen)")
        if self.iv_used:
            lines.append(f"Prime de variance observee : IV moyenne utilisee {np.mean(self.iv_used):.1%} vs vol realisee suivante "
                         f"{np.mean(self.rv_after):.1%} (n={len(self.iv_used)})")
        lines.append("RAPPEL : backtest SYNTHETIQUE (Black-Scholes, spread modelise) - pas de vraies cotations d options ; "
                     "valider en signal_seul / paper.")
