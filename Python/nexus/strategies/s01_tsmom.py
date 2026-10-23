"""FICHE 1 - Momentum series temporelles (port de Strategies/Nexus01_TSMOM.cs).

12-1 quotidien, decision le dernier jour de bourse du mois (ordres a l ouverture du 1er jour),
vol cible 12 % / N, plafonds du module B, stop ATR(14) x3 borne [2 % ; 8 %] qui ne recule jamais,
exposition /2 en etat de panique (controle aussi en cours de mois). Long seulement.
"""
from __future__ import annotations

import math

from .. import mathx as M
from .. import signals as S
from ..engine import NexusStrategy

UNIVERSE_25 = "SPY,QQQ,XLF,XLV,XLE,XLI,XLY,XLP,XLU,XLB,XLRE,XLC,AAPL,MSFT,NVDA,AMZN,GOOGL,META,JPM,JNJ,XOM,UNH,V,PG,HD"


class Nexus01TSMOM(NexusStrategy):
    NAME = "Nexus01_TSMOM"
    DESCRIPTION = "Fiche 1 - Momentum series temporelles 12-1, mensuel, vol cible 12 %, stop ATR x3 [2-8 %], panique /2."
    DEFAULTS = dict(
        symbols=UNIVERSE_25,
        sizing_mode="natif",
        lookback_days=252,
        skip_days=21,
        use_vol_scaling=True,
        target_vol_pct=12.0,
        vol_window_days=126,
        atr_multiplier=3.0,
        stop_min_pct=2.0,
        stop_max_pct=8.0,
        barometer="SPY",
        use_panic_state=True,
        panic_multiplier=0.5,
        panic_lookback_days=504,
        panic_vol_days=21,
        panic_median_days=252,
        panic_check_daily=True,
    )

    def required_references(self):
        return [self.p.barometer]

    def on_data_loaded(self):
        self.last_signal = {}
        self.last_panic = False
        self.panic_init = False
        self.panic_days = self.rebalances = self.total_days = 0
        self.last_panic_detail = ""

    def on_batch(self, day):
        p = self.p
        self.total_days += 1
        traded = self.traded_syms
        baro = self.sym(p.barometer)
        n_valid = 0
        for s in traded:
            sig = S.return_12_1(s.hist, p.lookback_days, p.skip_days)
            self.last_signal[s.name] = sig
            if M.ok(sig) and M.ok(s.hist.realized_vol(p.vol_window_days)):
                n_valid += 1
        panic = False
        if p.use_panic_state and baro is not None:
            panic, self.last_panic_detail = S.panic_state(baro.hist, p.panic_lookback_days, p.panic_vol_days, p.panic_median_days)
        if panic:
            self.panic_days += 1
        mult = p.panic_multiplier if panic else 1.0
        if n_valid == 0:
            return

        if self.is_rebalance_day(day, "mensuel", baro or (traded[0] if traded else None)):
            self.rebalances += 1
            self.nx(f"{day:%Y-%m-%d} reequilibrage mensuel ({n_valid} signaux valides, panique={panic})")
            for s in traded:
                sig = self.last_signal[s.name]
                s.stopped_out = False
                if not M.ok(sig):
                    continue
                if sig > 0:
                    w = (S.inverse_vol_weight(s.hist, p.target_vol_pct / 100.0, p.vol_window_days, n_valid, 0)
                         if p.use_vol_scaling else 1.0 / n_valid)
                    if not M.ok(w):
                        continue
                    w *= mult
                    q, det = self.size_qty(s, w, s.last_price)
                    stop = S.long_stop(s.last_price, s.hist.atr, p.atr_multiplier, p.stop_min_pct / 100, p.stop_max_pct / 100)
                    if s.qty > 0 and M.ok(s.stop_price):
                        stop = max(stop, s.stop_price)       # un stop ne recule jamais
                    self.set_target(s, q, stop, f"TSMOM 12-1={sig:.1%} w={w:.2%}")
                    self.signal(self.now, s.name, "tsmom_long", f"12-1={sig:.2%} cible={q} stop={stop:.2f} | {det}")
                elif s.qty != 0 or s.target_qty != 0:
                    self.set_target(s, 0, M.NAN, f"signal 12-1 <= 0 ({sig:.1%})")
            self.last_panic = panic
            self.panic_init = True
            return

        if p.use_panic_state and p.panic_check_daily and self.panic_init and panic != self.last_panic:
            factor = p.panic_multiplier if panic else 1.0 / max(1e-9, p.panic_multiplier)
            self.nx(f"{day:%Y-%m-%d} etat de panique {'ACTIVE' if panic else 'leve'} -> positions x{factor:.2f}")
            for s in traded:
                if s.target_qty <= 0:
                    continue
                lot = max(1, int(p.lot_size))
                q = int(math.floor(s.target_qty * factor / lot)) * lot
                if not panic:
                    w = q * s.last_price * self.value_per_point(s) / max(1.0, self.bankroll())
                    q = min(q, self.size_qty(s, w, s.last_price, mode="natif")[0])
                self.set_target(s, q, s.stop_price, "panique : exposition /2" if panic else "fin de panique")
            self.last_panic = panic

    def report_extras(self, lines):
        td = self.total_days
        lines.append(f"Reequilibrages mensuels : {self.rebalances} | jours en etat de panique : {self.panic_days}/{td} "
                     f"({self.panic_days / td if td else 0:.1%})")
        lines.append("Version " + ("AVEC" if self.p.use_vol_scaling else "SANS") + " mise a l echelle par la volatilite "
                     ": relancer avec l autre valeur pour isoler l apport du signal seul (fiche 1).")
        pos = sorted(((k, v) for k, v in self.last_signal.items() if M.ok(v)), key=lambda kv: -kv[1])[:25]
        lines.append("Derniers signaux 12-1 : " + ", ".join(f"{k} {v:.1%}" for k, v in pos))
