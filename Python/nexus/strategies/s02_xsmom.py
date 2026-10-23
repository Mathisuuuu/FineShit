"""FICHE 2 - Momentum transversal (port de Strategies/Nexus02_XSMOM.cs).

Quartile superieur du 12-1 (6/25) a poids egal, tampon top 9, panier mis a 12 % de vol,
50 % max, panique /2, stop ATR x3 [2-8 %]. Mensuel.
"""
from __future__ import annotations

import math

from .. import data as D
from .. import mathx as M
from .. import signals as S
from ..engine import NexusStrategy
from .s01_tsmom import UNIVERSE_25


class Nexus02XSMOM(NexusStrategy):
    NAME = "Nexus02_XSMOM"
    DESCRIPTION = "Fiche 2 - Momentum transversal 12-1 : quartile superieur, tampon top 9, panier 12 % de vol, 50 % max, panique /2."
    DEFAULTS = dict(
        symbols=UNIVERSE_25,
        sizing_mode="natif",
        lookback_days=252,
        skip_days=21,
        top_count=0,
        buffer_rank=0,
        use_vol_scaling=True,
        target_vol_pct=12.0,
        vol_window_days=126,
        max_basket_pct=50.0,
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
        self.selection = []
        self.last_scores = {}
        self.last_panic = self.panic_init = False
        self.rebalances = self.replacements = self.panic_days = self.total_days = 0
        self.last_basket_vol = self.last_exposure = M.NAN

    def on_batch(self, day):
        p = self.p
        self.total_days += 1
        traded = self.traded_syms
        baro = self.sym(p.barometer)
        scores = {}
        for s in traded:
            sig = S.return_12_1(s.hist, p.lookback_days, p.skip_days)
            if M.ok(sig):
                scores[s.name] = sig
        self.last_scores = scores
        panic = False
        if p.use_panic_state and baro is not None:
            panic, _ = S.panic_state(baro.hist, p.panic_lookback_days, p.panic_vol_days, p.panic_median_days)
        if panic:
            self.panic_days += 1
        if len(scores) < 4:
            return

        if self.is_rebalance_day(day, "mensuel", baro or (traded[0] if traded else None)):
            self.rebalances += 1
            n = len(scores)
            top = p.top_count if p.top_count > 0 else max(1, int(_round_half_even(n / 4.0)))
            buffer = max(top, p.buffer_rank) if p.buffer_rank > 0 else max(top, int(_round_half_even(n * 0.36)))
            held = {s.name for s in traded if s.qty > 0 or s.target_qty > 0}
            sel = S.select_with_buffer(scores, held, top, buffer)
            self.replacements += sum(1 for x in sel if x not in held)
            hs = [self.sym(x).hist for x in sel]
            bvol = D.basket_vol(hs, [1.0 / len(sel)] * len(sel), p.vol_window_days)
            exposure = p.max_basket_pct / 100.0
            if p.use_vol_scaling and M.ok(bvol) and bvol > 1e-6:
                exposure = min(exposure, p.target_vol_pct / 100.0 / bvol)
            if panic:
                exposure *= p.panic_multiplier
            self.last_basket_vol, self.last_exposure = bvol, exposure
            self.nx(f"{day:%Y-%m-%d} reequilibrage : top {top}/{n} (tampon {buffer}) vol panier {bvol:.1%} -> exposition "
                    f"{exposure:.1%}{' (PANIQUE)' if panic else ''} : {', '.join(sel)}")
            for s in traded:
                s.stopped_out = False
                if s.name in sel:
                    w = exposure / len(sel)
                    q, det = self.size_qty(s, w, s.last_price)
                    stop = S.long_stop(s.last_price, s.hist.atr, p.atr_multiplier, p.stop_min_pct / 100, p.stop_max_pct / 100)
                    if s.qty > 0 and M.ok(s.stop_price):
                        stop = max(stop, s.stop_price)
                    rank = S.rank_of(scores, s.name)
                    self.set_target(s, q, stop, f"XSMOM rang {rank} 12-1={scores[s.name]:.1%}")
                elif s.qty != 0 or s.target_qty != 0:
                    rank = S.rank_of(scores, s.name)
                    self.set_target(s, 0, M.NAN, f"hors du top {buffer} (rang {'n/a' if rank >= 1 << 30 else rank})")
            self.selection = sel
            self.last_panic = panic
            self.panic_init = True
            return

        if p.use_panic_state and p.panic_check_daily and self.panic_init and panic != self.last_panic:
            factor = p.panic_multiplier if panic else 1.0 / max(1e-9, p.panic_multiplier)
            self.nx(f"{day:%Y-%m-%d} etat de panique {'ACTIVE' if panic else 'leve'} -> panier x{factor:.2f}")
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
        r = self.rebalances
        lines.append(f"Reequilibrages : {r} | nouveaux titres entres : {self.replacements} "
                     f"({self.replacements / r if r else 0:.2f} par reequilibrage) | jours de panique : {self.panic_days}/{self.total_days}")
        lines.append(f"Derniere vol du panier : {self.last_basket_vol:.1%} -> exposition {self.last_exposure:.1%}")
        lines.append("Selection courante : " + ", ".join(self.selection))


def _round_half_even(x: float) -> float:
    """Math.Round du C# (arrondi bancaire), comme Python round()."""
    return round(x)
