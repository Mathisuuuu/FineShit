"""FICHE 13 - Tendance 1/3/12 mois sur 8 actifs 24/5 (port de Nexus13_PropTrend8.cs).

Signal = moyenne des signes des rendements 21/63/252 j (long/court), taille = min(vol cible 10 %,
risque 0.5 % au stop ATR x3) x |signal|, lots par symbole, regles prop codees en dur (perte du
jour 5 %, drawdown 10 % statique ou suiveur, marge 80 %), veto macro par regles (agenda CSV).
Le veto Claude, le webhook et les comptes miroirs sont propres au temps reel NinjaTrader.
"""
from __future__ import annotations

import math
import os
from datetime import datetime, timedelta

from .. import data as D
from .. import mathx as M
from ..engine import NexusStrategy, parse_map, split_list


class Nexus13PropTrend8(NexusStrategy):
    NAME = "Nexus13_PropTrend8"
    DESCRIPTION = "Fiche 13 - Tendance 1/3/12 mois, 8 actifs 24/5, vol cible egale, risque 0.5 %/position, regles prop."
    BATCH_MODE = False
    DEFAULTS = dict(
        symbols="EURUSD,GBPUSD,USDJPY,AUDUSD,XAUUSD,US500,NAS100,GER40",
        allow_short_selling=True,
        sizing_mode="natif",
        max_trade_pct=0.0, max_symbol_pct=0.0, max_class_pct=0.0, max_total_pct=0.0,
        use_correlation_divisor=False,
        initial_bankroll=100000.0,
        drawdown_trip_pct=8.0,
        daily_loss_pct=4.0,
        horizon_days="21,63,252",
        target_vol_per_asset_pct=10.0,
        vol_window_days=60,
        max_risk_per_position_pct=0.5,
        atr_multiplier=3.0,
        rebalance_threshold_pct=25.0,
        lot_sizes="EURUSD=1000;GBPUSD=1000;USDJPY=1000;AUDUSD=1000;XAUUSD=1;US500=1;NAS100=1;GER40=1",
        currency_map="XAUUSD=USD;US500=USD;NAS100=USD;GER40=EUR",
        prop_daily_loss_pct=5.0,
        prop_max_drawdown_pct=10.0,
        prop_drawdown_type="statique",   # statique | suiveur
        prop_buffer_pct=80.0,
        veto_mode="regles",              # aucun | regles
        macro_file="",
        veto_window_minutes=60,
        veto_min_impact=3,
        bar_close_utc_hour=21,           # heure UTC de cloture des barres journalieres (veto macro)
    )

    def on_data_loaded(self):
        p = self.p
        self.lot_map = {k.upper(): max(1, int(float(v))) for k, v in parse_map(p.lot_sizes).items()}
        self.ccy_map = {k.upper(): v for k, v in parse_map(p.currency_map).items()}
        self.horizons = [int(float(x)) for x in split_list(p.horizon_days) if int(float(x)) > 0]
        self.macro = D.MacroCalendar(p.macro_file if p.macro_file and os.path.exists(p.macro_file) else None)
        self.nx("Agenda macro : " + self.macro.message)
        self.prop_halted = False
        self.halt_reason = ""
        self.prop_day = None
        self.prop_day_start = M.NAN
        self.prop_peak = p.initial_bankroll
        self.worst_daily_loss = self.worst_drawdown = 0.0
        self.near_breach_days = self.vetoes = self.veto_checks = self.signal_changes = 0
        self.last_near_breach_day = None

    def _lot(self, s):
        return self.lot_map.get(s.name.upper(), max(1, int(self.p.lot_size)))

    def _currencies_of(self, s):
        c = ["USD"]
        m = self.ccy_map.get(s.name.upper())
        if m:
            c += split_list(m.replace("/", ","))
        elif len(s.name) == 6 and s.name.isalpha():
            c += [s.name[:3].upper(), s.name[3:].upper()]
        return list(dict.fromkeys(c))

    # --- regles prop ---
    def _prop_check(self, day):
        p = self.p
        eq = self.equity
        if self.prop_day is None or day > self.prop_day:
            self.prop_day, self.prop_day_start = day, eq
        if eq > self.prop_peak:
            self.prop_peak = eq
        dd_ref = p.initial_bankroll if p.prop_drawdown_type == "statique" else self.prop_peak
        daily_loss = max(0.0, 1 - eq / self.prop_day_start) if self.prop_day_start > 0 else 0.0
        dd = max(0.0, 1 - eq / dd_ref) if dd_ref > 0 else 0.0
        self.worst_daily_loss = max(self.worst_daily_loss, daily_loss)
        self.worst_drawdown = max(self.worst_drawdown, dd)
        buf = p.prop_buffer_pct / 100.0
        if (daily_loss >= p.prop_daily_loss_pct / 100 * buf or dd >= p.prop_max_drawdown_pct / 100 * buf) and day != self.last_near_breach_day:
            self.near_breach_days += 1
            self.last_near_breach_day = day
        if self.prop_halted:
            return
        why = None
        if daily_loss >= p.prop_daily_loss_pct / 100.0:
            why = f"perte du jour {daily_loss:.2%} >= limite {p.prop_daily_loss_pct:.1f} %"
        elif dd >= p.prop_max_drawdown_pct / 100.0:
            why = f"drawdown {p.prop_drawdown_type} {dd:.2%} >= limite {p.prop_max_drawdown_pct:.1f} %"
        if why is None:
            return
        self.prop_halted, self.halt_reason = True, why
        self.nx("ALERTE REGLE PROP DEPASSEE : " + why + " -> fermeture de tout et arret")
        self.flat_all("regle prop : " + why)

    def allow_increase(self, s):
        p = self.p
        if self.prop_halted:
            return False, f"strategie arretee (regle prop : {self.halt_reason})"
        eq = self.equity
        dd_ref = p.initial_bankroll if p.prop_drawdown_type == "statique" else self.prop_peak
        daily_loss = 1 - eq / self.prop_day_start if self.prop_day_start > 0 else 0.0
        dd = 1 - eq / dd_ref if dd_ref > 0 else 0.0
        buf = p.prop_buffer_pct / 100.0
        if daily_loss >= p.prop_daily_loss_pct / 100.0 * buf:
            return False, f"marge prop : perte du jour {daily_loss:.2%} >= {p.prop_buffer_pct:.0f} % de la limite"
        if dd >= p.prop_max_drawdown_pct / 100.0 * buf:
            return False, f"marge prop : drawdown {dd:.2%} >= {p.prop_buffer_pct:.0f} % de la limite"
        return True, None

    # --- signal et taille ---
    def on_symbol_bar(self, s, day):
        p = self.p
        if not s.traded:
            return
        self._prop_check(day)
        h = s.hist
        max_h = max(self.horizons) if self.horizons else 252
        if h.count < max(max_h, p.vol_window_days) + 2 or self.prop_halted:
            return
        signs = [math.copysign(1, r) if r != 0 else 0 for r in (h.return_over(hd, 0) for hd in self.horizons) if M.ok(r)]
        if not signs:
            return
        avg = sum(signs) / len(signs)
        price, vpp, vol, atr = h.last_close, self.value_per_point(s), h.realized_vol(p.vol_window_days), h.atr
        if not M.ok(vol) or vol <= 0 or not M.ok(atr) or atr <= 0 or vpp <= 0:
            return
        eq = self.bankroll()
        units_vol = p.target_vol_per_asset_pct / 100.0 / vol * eq / (price * vpp)
        dist = atr * p.atr_multiplier
        units_risk = p.max_risk_per_position_pct / 100.0 * eq / (dist * vpp)
        lot = self._lot(s)
        q = int(math.floor(min(units_vol, units_risk) * abs(avg) / lot)) * lot
        target = (1 if avg > 0 else -1 if avg < 0 else 0) * q
        cur = s.target_qty
        sign = lambda x: (x > 0) - (x < 0)
        change = sign(target) != sign(cur) or (cur != 0 and abs(target - cur) > p.rebalance_threshold_pct / 100.0 * abs(cur))
        if not change:
            return
        increase = abs(target) > abs(cur) or sign(target) != sign(cur)
        if increase and target != 0:
            veto, vr = self._macro_veto(s, h)
            if veto:
                self.vetoes += 1
                self.nx(f"Veto macro {s.name} : {vr}")
                if sign(cur) != sign(target) and cur != 0:
                    target = 0
                else:
                    return
        stop = price - dist if target > 0 else (price + dist if target < 0 else M.NAN)
        self.set_target(s, target, stop, f"tendance {avg:+.2f} (1/3/12 mois) vol {vol:.1%} -> {target} unites")
        self.signal_changes += 1

    def _macro_veto(self, s, h):
        p = self.p
        if p.veto_mode == "aucun":
            return False, None
        self.veto_checks += 1
        d = h.last_date
        now_utc = datetime(d.year, d.month, d.day) + timedelta(hours=p.bar_close_utc_hour)
        ev = self.macro.near(self._currencies_of(s), now_utc, 0, p.veto_window_minutes, p.veto_min_impact)
        if not ev:
            return False, None
        return True, "evenement(s) dans l heure : " + " ; ".join(f"{e.utc:%Y-%m-%d %H:%M} {e.currency} {e.title}" for e in ev)

    def report_extras(self, lines):
        p = self.p
        lines.append(f"Prop : pire perte journaliere {self.worst_daily_loss:.2%} (limite {p.prop_daily_loss_pct:.1f} %) | drawdown max "
                     f"{self.worst_drawdown:.2%} ({p.prop_drawdown_type}, limite {p.prop_max_drawdown_pct:.1f} %) | jours en marge de securite "
                     f"{self.near_breach_days}" + (f" | COMPTE ARRETE : {self.halt_reason}" if self.prop_halted else ""))
        lines.append(f"Changements de position : {self.signal_changes} | controles de veto : {self.veto_checks} | vetos : {self.vetoes} (mode {p.veto_mode})")
        lines.append("Regles prop A VERIFIER chez la firme ; noms CFD dependants du fournisseur (alias : ^GSPC->US500, ^NDX->NAS100, ^GDAXI->GER40).")
