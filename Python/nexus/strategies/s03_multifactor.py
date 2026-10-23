"""FICHE 3 - Rotation multi-facteurs (port de Strategies/Nexus03_MultiFactorRotation.cs).

Momentum + value + qualite (z-scores par rang centre), rotation des facteurs x1.5 / x0.5
selon leur rendement long-short 12 mois, top 5 a poids egal, sortie hors du top 8.
Sans fondamentaux : momentum + securite (beta) seulement (signale dans le rapport).
"""
from __future__ import annotations

import os

from .. import data as D
from .. import mathx as M
from .. import signals as S
from ..engine import NexusStrategy
from .s01_tsmom import UNIVERSE_25


class Nexus03MultiFactorRotation(NexusStrategy):
    NAME = "Nexus03_MultiFactorRotation"
    DESCRIPTION = "Fiche 3 - Momentum + value + qualite (QMJ), rotation x1.5 / x0.5, top 5 a poids egal, sortie hors top 8."
    DEFAULTS = dict(
        symbols=UNIVERSE_25,
        sizing_mode="natif",
        fundamentals_file="",          # chemin du CSV point-in-time (Data/fundamentals.csv)
        market_symbol="SPY",
        top_count=5,
        buffer_rank=8,
        target_exposure_pct=30.0,
        use_rotation=True,
        up_multiplier=1.5,
        down_multiplier=0.5,
        rotation_window_days=252,
        mom_lookback_days=252,
        mom_skip_days=21,
        growth_years=5,
        beta_window_days=252,
        min_scored=8,
        require_fundamentals=False,
        use_atr_stop=False,
        atr_multiplier=3.0,
        stop_min_pct=2.0,
        stop_max_pct=8.0,
    )

    def required_references(self):
        return [self.p.market_symbol]

    def on_data_loaded(self):
        p = self.p
        self.fund = D.Fundamentals(p.fundamentals_file if p.fundamentals_file and os.path.exists(p.fundamentals_file) else None)
        self.nx("Fondamentaux : " + self.fund.message)
        if not self.fund.loaded:
            self.nx("ATTENTION : pas de fondamentaux -> value et rentabilite/croissance indisponibles ; score = momentum + securite (beta).")
        self.engine = S.MultiFactorEngine(self.fund, p.mom_lookback_days, p.mom_skip_days, p.beta_window_days,
                                          p.rotation_window_days, p.up_multiplier, p.down_multiplier, p.use_rotation, p.growth_years)
        self.last = None
        self.scored_days = self.changes = self.rotation_active_days = 0
        self.weight_sum = [0.0, 0.0, 0.0]

    def on_batch(self, day):
        p = self.p
        stocks = [s for s in self.traded_syms if s.asset_class == "Action" and (not p.require_fundamentals or self.fund.has(s.name))]
        if not stocks:
            self.nx_once("nostock", "Aucune action individuelle dans l univers (les ETF sont exclus).")
            return
        mp = {s.name: s.hist for s in stocks}
        mkt = self.sym(p.market_symbol)
        self.last = self.engine.update(day, mp, mkt.hist if mkt is not None else None)
        if self.last.scored < min(p.min_scored, len(stocks)):
            return
        self.scored_days += 1
        for f in range(3):
            self.weight_sum[f] += self.last.weights[f]
        if M.ok(self.last.factor_12m[0]):
            self.rotation_active_days += 1
        held = {s.name for s in stocks if s.qty > 0 or s.target_qty > 0}
        sel = S.select_with_buffer(self.last.composite, held, p.top_count, p.buffer_rank)
        for s in stocks:
            in_sel, is_held = s.name in sel, s.name in held
            if in_sel and not is_held:
                w = p.target_exposure_pct / 100.0 / max(1, p.top_count)
                q, det = self.size_qty(s, w, s.last_price)
                stop = (S.long_stop(s.last_price, s.hist.atr, p.atr_multiplier, p.stop_min_pct / 100, p.stop_max_pct / 100)
                        if p.use_atr_stop else M.NAN)
                z = self.last.z[s.name]
                why = (f"composite={self.last.composite[s.name]:.2f} rang {S.rank_of(self.last.composite, s.name)} "
                       f"(z mom {z[0]:.2f} val {z[1]:.2f} qual {z[2]:.2f})")
                self.set_target(s, q, stop, why)
                self.changes += 1
            elif not in_sel and is_held:
                rank = S.rank_of(self.last.composite, s.name)
                self.set_target(s, 0, M.NAN, f"sorti du top {p.buffer_rank} (rang {'n/a' if rank >= 1 << 30 else rank})")
                self.changes += 1

    def report_extras(self, lines):
        lines.append(f"Jours notes : {self.scored_days} | changements de position : {self.changes} | rotation active {self.rotation_active_days} jours")
        if self.scored_days:
            w = [x / self.scored_days for x in self.weight_sum]
            lines.append(f"Poids moyens des facteurs : momentum {w[0]:.1%}, value {w[1]:.1%}, qualite {w[2]:.1%}")
        if self.last is not None:
            f = self.last.factor_12m
            lines.append(f"Derniers rendements 12 mois long-short : momentum {f[0]:.1%}, value {f[1]:.1%}, qualite {f[2]:.1%}")
            top = sorted(self.last.composite.items(), key=lambda kv: -kv[1])[:8]
            lines.append("Top actuel : " + ", ".join(f"{k} {v:.2f}" for k, v in top))
        lines.append("Fondamentaux charges (point-in-time)." if self.fund.loaded else
                     "SANS fondamentaux : value et qualite partielles - resultat a ne pas confondre avec la fiche 3 complete.")
