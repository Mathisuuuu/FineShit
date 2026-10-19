"""FICHE 4 variante A - Retour a la moyenne du residu sectoriel (port de Nexus04A_ResidualMeanReversion.cs).

Quotidien (Avellaneda-Lee) : residu vs ETF sectoriel sur 60 j, residu cumule ajuste en OU,
s-score (moyennes centrees), demi-vie < 15 j ; entree s < -1.25, sortie s > -0.5 ou 10 j ou stop ATR.
Mensuel (Blitz et al.) : residu standardise du dernier mois (3 facteurs FF ou modele de marche),
achat du decile perdant, detention 1 mois. Long seulement, demi-Kelly 3 % max.
"""
from __future__ import annotations

import math
import os

import numpy as np

from .. import data as D
from .. import mathx as M
from .. import signals as S
from ..engine import NexusStrategy, parse_map


class Nexus04AResidualMeanReversion(NexusStrategy):
    NAME = "Nexus04A_ResidualMeanReversion"
    DESCRIPTION = "Fiche 4A - s-score OU du residu sectoriel (demi-vie < 15 j) ou decile mensuel des residus (Blitz et al.)."
    DEFAULTS = dict(
        symbols="AAPL,MSFT,NVDA,AMZN,GOOGL,META,JPM,JNJ,XOM,UNH,V,PG,HD",
        sizing_mode="demi_kelly",
        mode="quotidien_ou",            # quotidien_ou | mensuel_decile
        sector_map="AAPL=XLK;MSFT=XLK;NVDA=XLK;AMZN=XLY;GOOGL=XLC;META=XLC;JPM=XLF;JNJ=XLV;XOM=XLE;UNH=XLV;V=XLF;PG=XLP;HD=XLY",
        default_benchmark="SPY",
        regression_days=60,
        max_half_life_days=15.0,
        entry_s=-1.25,
        exit_s=-0.5,
        max_hold_days=10,
        center_means=True,
        atr_multiplier=3.0,
        stop_min_pct=2.0,
        stop_max_pct=8.0,
        factors_file="",
        estimation_months=36,
        decile_pct=10.0,
    )

    def required_references(self):
        r = [self.p.default_benchmark] + list(parse_map(self.p.sector_map).values())
        return list(dict.fromkeys(r))

    def on_data_loaded(self):
        p = self.p
        self.bench_map = {k.upper(): v for k, v in parse_map(p.sector_map).items()}
        self.factors = None
        if p.mode == "mensuel_decile":
            self.factors = D.FactorFile(p.factors_file if p.factors_file and os.path.exists(p.factors_file) else None)
            self.nx("Facteurs : " + self.factors.message + ("" if self.factors.loaded else f" -> repli sur le modele de marche ({p.default_benchmark})"))
        self.entry_scores, self.entry_half_lives = [], []
        self.valid_fits_total = self.fit_days = self.monthly_rebalances = 0

    def bench_of(self, s):
        b = self.bench_map.get(s.name.upper())
        bs = self.sym(b) if b else None
        return bs or self.sym(self.p.default_benchmark)

    def on_batch(self, day):
        if self.p.mode == "quotidien_ou":
            self._daily_ou(day)
        else:
            self._monthly(day)

    def _daily_ou(self, day):
        p = self.p
        fits, last_x = {}, {}
        for s in self.traded_syms:
            bench = self.bench_of(s)
            if bench is None or bench is s:
                continue
            rf = S.residual_fit(s.hist, bench.hist, p.regression_days)
            if not rf.ok or rf.residuals.size < p.regression_days // 2:
                continue
            x = np.cumsum(np.where(np.isfinite(rf.residuals), rf.residuals, 0.0))
            ou = M.ou_fit(x)
            if not ou.valid:
                continue
            fits[s.name] = ou
            last_x[s.name] = float(x[-1])
        if fits:
            self.fit_days += 1
            self.valid_fits_total += len(fits)
        m_avg = float(np.mean([f.mean for f in fits.values()])) if p.center_means and len(fits) > 1 else 0.0
        for s in self.traded_syms:
            ou = fits.get(s.name)
            score = (last_x[s.name] - (ou.mean - m_avg)) / ou.sigma_eq if ou is not None else M.NAN
            if s.qty > 0 or s.target_qty > 0:
                if s.qty > 0 and ou is not None and score > p.exit_s:
                    self.set_target(s, 0, M.NAN, f"s-score {score:.2f} > {p.exit_s:.2f}")
                elif s.qty > 0 and s.bars_held >= p.max_hold_days:
                    self.set_target(s, 0, M.NAN, f"{p.max_hold_days} jours ecoules")
                continue
            if ou is None or (s.stopped_out and s.stopped_time is not None and s.stopped_time.date() == day.date()):
                continue
            if ou.half_life >= p.max_half_life_days or score >= p.entry_s:
                continue
            q, det = self.size_qty(s, self.kelly_native_fraction(), s.last_price)
            stop = S.long_stop(s.last_price, s.hist.atr, p.atr_multiplier, p.stop_min_pct / 100, p.stop_max_pct / 100)
            self.set_target(s, q, stop, f"s-score {score:.2f} < {p.entry_s:.2f}, demi-vie {ou.half_life:.1f} j")
            if q > 0:
                self.entry_scores.append(score)
                self.entry_half_lives.append(ou.half_life)

    def _monthly(self, day):
        p = self.p
        mkt = self.sym(p.default_benchmark)
        if mkt is None or mkt.hist.count < 21 * (p.estimation_months + 2):
            return
        if not self.is_rebalance_day(day, "mensuel", mkt):
            return
        self.monthly_rebalances += 1
        mkt_by_month = dict(D.monthly_returns(mkt.hist, p.estimation_months + 1))
        std_resid = {}
        use_ff = self.factors is not None and self.factors.loaded
        for s in self.traded_syms:
            m = D.monthly_returns(s.hist, p.estimation_months + 1)
            if len(m) < p.estimation_months + 1:
                continue
            y, X = [], []
            for key, ret in m:
                f = self.factors.get_month(key.year, key.month) if use_ff else None
                if f is not None:
                    y.append(ret - f[3])
                    X.append(f[:3])
                elif key in mkt_by_month:
                    y.append(ret)
                    X.append([mkt_by_month[key]])
            if len(y) < p.estimation_months // 2 + 2 or len({len(r) for r in X}) != 1:
                continue
            last = len(y) - 1
            o = M.ols(np.array(y[:last]), np.array(X[:last]), True)
            if not o.ok:
                continue
            fit = o.coef[0] + sum(o.coef[k + 1] * X[last][k] for k in range(len(X[last])))
            sd = math.sqrt(o.rss / max(1, o.n - o.k))
            if sd > 0:
                std_resid[s.name] = (y[last] - fit) / sd
        if len(std_resid) < 3:
            return
        k10 = max(1, int(round(len(std_resid) * p.decile_pct / 100.0)))
        losers = {k for k, _ in sorted(std_resid.items(), key=lambda kv: kv[1])[:k10]}
        self.nx(f"{day:%Y-%m-%d} decile perdant ({k10} titres, modele {'3 facteurs' if use_ff else 'marche'}) : "
                + ", ".join(f"{x} {std_resid[x]:.2f}" for x in losers))
        for s in self.traded_syms:
            if s.name in losers:
                q, _ = self.size_qty(s, self.kelly_native_fraction(), s.last_price)
                stop = S.long_stop(s.last_price, s.hist.atr, p.atr_multiplier, p.stop_min_pct / 100, p.stop_max_pct / 100)
                self.set_target(s, q, stop, f"residu mensuel standardise {std_resid[s.name]:.2f}")
                self.entry_scores.append(std_resid[s.name])
            elif s.qty != 0 or s.target_qty != 0:
                self.set_target(s, 0, M.NAN, "fin de detention mensuelle")

    def report_extras(self, lines):
        lines.append("Mode : " + self.p.mode)
        if self.p.mode == "quotidien_ou":
            lines.append(f"Ajustements OU valides : {self.valid_fits_total / self.fit_days if self.fit_days else 0:.1f} par jour en moyenne sur {self.fit_days} jours")
            if self.entry_scores:
                lines.append(f"Entrees : {len(self.entry_scores)} | s-score moyen {np.mean(self.entry_scores):.2f} | demi-vie mediane {M.median(self.entry_half_lives):.1f} j")
        else:
            lines.append(f"Reequilibrages mensuels : {self.monthly_rebalances} | selections : {len(self.entry_scores)}")
        if self.closed_trades:
            g = float(np.mean([t.gross_return for t in self.closed_trades]))
            lines.append(f"Avantage brut moyen par trade : {g:.3%} (point mort Blitz et al. ~0.56 % aller-retour)")
