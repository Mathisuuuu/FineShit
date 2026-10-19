"""FICHE 14 - Swing a conditions strictes (port de Strategies/Nexus14_StrictSwing.cs).

1. 12-1 > 0  2. cloture > MM200  3. repli 5 j dans le decile bas (brut ou residuel)
4. volume moyen 20 j >= 5 M$ ET spread <= 0.05 % (colonne spread_pct des cotations, par exemple les
   spreads de cloture Alpaca ; sinon estimateur Abdi-Ranaldo sur demande)
5. pas de regime haute vol (terciles ou HMM)  6. pas de resultats < 3 j.
Entree : ordre LIMITE a la cloture de la veille, valable une seance. Sortie : cloture > MM5 ou 10 j.
Stop ATR x2.5 [2-8 %]. Demi-Kelly, 3 % max.
"""
from __future__ import annotations

import math
import os

import numpy as np

from .. import data as D
from .. import mathx as M
from .. import regime as R
from .. import signals as S
from ..engine import NexusStrategy
from .s01_tsmom import UNIVERSE_25


class Nexus14StrictSwing(NexusStrategy):
    NAME = "Nexus14_StrictSwing"
    DESCRIPTION = "Fiche 14 - Repli (decile 5 j) dans une tendance haussiere, liquidite, pas de haute vol ni de resultats < 3 j."
    DEFAULTS = dict(
        symbols=UNIVERSE_25,
        sizing_mode="demi_kelly",
        mom_lookback_days=252,
        skip_days=21,
        sma_long_days=200,
        pullback_days=5,
        pullback_decile_pct=10.0,
        pullback_mode="brut",            # brut | residuel
        beta_days=60,
        min_dollar_volume=5_000_000.0,
        max_spread_pct=0.05,
        spread_source="auto",            # auto (colonne spread_pct si presente) | estime (Abdi-Ranaldo, OHLC) | aucun
        spread_days=20,
        regime_source="terciles",        # aucun | terciles | hmm
        barometer="SPY",
        vix_symbol="",
        earnings_file="",
        earnings_days=3,
        exclude_if_no_earnings_data=True,
        limit_offset_pct=0.0,
        exit_sma_days=5,
        max_hold_days=10,
        atr_multiplier=2.5,
        stop_min_pct=2.0,
        stop_max_pct=8.0,
        max_trades_per_week=2.0,
    )

    def required_references(self):
        r = [self.p.barometer]
        if self.p.vix_symbol:
            r.append(self.p.vix_symbol)
        return r

    def on_data_loaded(self):
        p = self.p
        self.terciles = R.VolTercileRegime()
        self.hmm = R.LazyHmm(p.regime_source == "hmm", bool(p.vix_symbol) and self.sym(p.vix_symbol) is not None)
        self.earnings = D.Earnings(p.earnings_file if p.earnings_file and os.path.exists(p.earnings_file) else None)
        self.nx("Resultats : " + self.earnings.message + ("" if self.earnings.loaded else " -> condition 6 IGNOREE (aucun fichier)"))
        self.fail_count = [0] * 7
        self.spread_rejects = self.spread_unknown = 0
        self.entry_days = []
        self.candidates_seen = self.entries_submitted = self.exits_sma = self.exits_time = self.frequency_alerts = 0

    def on_batch(self, day):
        p = self.p
        baro = self.sym(p.barometer)
        vix = self.sym(p.vix_symbol) if p.vix_symbol else None
        if baro is not None:
            self.terciles.update(baro.hist.last_close)
            self.hmm.update(baro.hist.last_close, vix.hist.last_close if vix is not None else M.NAN)
        regime = (self.hmm.regime if p.regime_source == "hmm" else
                  self.terciles.regime if p.regime_source == "terciles" else R.CALME)
        traded = self.traded_syms
        for s in traded:
            if s.qty <= 0:
                continue
            sma5 = s.hist.sma(p.exit_sma_days)
            if M.ok(sma5) and s.hist.last_close > sma5:
                self.set_target(s, 0, M.NAN, f"cloture > MM{p.exit_sma_days}")
                self.exits_sma += 1
            elif s.bars_held >= p.max_hold_days:
                self.set_target(s, 0, M.NAN, f"{p.max_hold_days} jours ecoules")
                self.exits_time += 1
        pb = {}
        r_mkt = baro.hist.return_over(p.pullback_days, 0) if baro is not None else M.NAN
        for s in traded:
            r5 = s.hist.return_over(p.pullback_days, 0)
            if not M.ok(r5):
                continue
            if p.pullback_mode == "residuel":
                b = S.beta(s.hist, baro.hist, p.beta_days) if baro is not None and baro is not s else M.NAN
                if not M.ok(b) or not M.ok(r_mkt):
                    continue
                r5 -= b * r_mkt
            pb[s.name] = r5
        if len(pb) < 5:
            return
        threshold = M.quantile(list(pb.values()), p.pullback_decile_pct / 100.0)
        for s in traded:
            if s.qty != 0 or s.target_qty != 0 or s.name not in pb:
                continue
            h = s.hist
            if h.count < max(p.mom_lookback_days, p.sma_long_days) + 2:
                continue
            self.candidates_seen += 1
            mom = h.return_over(p.mom_lookback_days, p.skip_days)
            sma = h.sma(p.sma_long_days)
            adv = h.avg_dollar_volume(20)
            fail = 0
            if not (M.ok(mom) and mom > 0):
                fail = 1
            elif not h.last_close > sma:
                fail = 2
            elif not pb[s.name] <= threshold:
                fail = 3
            elif not adv >= p.min_dollar_volume:
                fail = 4
            elif not self._spread_ok(h):
                fail = 4
                self.spread_rejects += 1
            elif regime == R.STRESS or (p.regime_source != "aucun" and regime == R.INCONNU):
                fail = 5
            elif self._earnings_block(s, day):
                fail = 6
            self.fail_count[fail] += 1
            if fail:
                continue
            limit = self.round_price(s, h.last_close * (1 - p.limit_offset_pct / 100.0))
            q, det = self.size_qty(s, self.kelly_native_fraction(), limit)
            stop = S.long_stop(limit, h.atr, p.atr_multiplier, p.stop_min_pct / 100, p.stop_max_pct / 100)
            why = (f"6 conditions : 12-1 {mom:.1%}, > MM{p.sma_long_days}, repli {pb[s.name]:.2%} <= decile {threshold:.2%}, "
                   f"ADV {adv:.0f}, regime {regime}")
            self.set_target(s, q, stop, why, "limit", limit, 1)
            if q > 0:
                self.entries_submitted += 1
                self.entry_days.append(day)
        recent = sum(1 for d in self.entry_days if (day - d).days <= 28)
        if recent / 4.0 > p.max_trades_per_week:
            self.frequency_alerts += 1
            self.nx_once("freq" + day.strftime("%Y%m"), f"{day:%Y-%m-%d} {recent} entrees sur 4 semaines (> {p.max_trades_per_week}/semaine) : "
                                                       "conditions PAS ASSEZ STRICTES (fiche 14).")

    def spread_of(self, h) -> float:
        """Spread moyen (%) sur spread_days : colonne spread_pct, ou estimateur Abdi-Ranaldo (2017) sur OHLC."""
        p = self.p
        n = p.spread_days
        if p.spread_source == "aucun" or h.count < n + 2:
            return M.NAN
        col = h.extra.get("spread_pct")
        if col is not None and p.spread_source in ("auto", "colonne"):
            v = col[h.count - n:h.count]
            v = v[np.isfinite(v)]
            if v.size >= n // 2:
                return float(np.median(v))
        if p.spread_source != "estime":
            return M.NAN
        k = h.count
        c = np.log(h.close[k - n - 1:k])
        eta = 0.5 * (np.log(h.high[k - n - 1:k]) + np.log(h.low[k - n - 1:k]))
        # s^2 = 4 E[(c_t - eta_t)(c_t - eta_{t+1})] ; moyenne sur la fenetre, negatif -> 0
        prod = (c[:-1] - eta[:-1]) * (c[:-1] - eta[1:])
        s2 = 4.0 * float(np.mean(prod))
        return 100.0 * math.sqrt(s2) if s2 > 0 else 0.0

    def _spread_ok(self, h) -> bool:
        sp = self.spread_of(h)
        if not M.ok(sp):
            self.spread_unknown += 1
            return True                      # inconnu : condition non verifiable (signale dans le rapport)
        return sp <= self.p.max_spread_pct

    def _earnings_block(self, s, day) -> bool:
        if not self.earnings.loaded or s.asset_class == "Etf":
            return False
        if not self.earnings.has_data(s.name):
            return self.p.exclude_if_no_earnings_data
        return self.earnings.within(s.name, day, self.p.earnings_days)

    def report_extras(self, lines):
        p, f = self.p, self.fail_count
        lines.append(f"Repli : {p.pullback_mode} | regime : {p.regime_source} | candidats examines {self.candidates_seen} | entrees soumises "
                     f"{self.entries_submitted} | sorties MM{p.exit_sma_days} {self.exits_sma}, temps {self.exits_time}")
        lines.append(f"Rejets : 1-tendance {f[1]} | 2-MM200 {f[2]} | 3-repli {f[3]} | 4-liquidite {f[4]} (dont spread "
                     f"> {p.max_spread_pct} % : {self.spread_rejects}) | 5-regime {f[5]} | 6-resultats {f[6]} | acceptes {f[0]}")
        if self.spread_unknown:
            lines.append(f"Spread inconnu pour {self.spread_unknown} candidats (pas de colonne spread_pct) : condition 4b non verifiee. "
                         "Telecharger les spreads de cloture (python -m nexus alpaca --spreads-depuis ...) ou -p spread_source=estime.")
        if len(self.equity_days) > 1:
            weeks = max(1.0, (self.equity_days[-1] - self.equity_days[0]).days / 7.0)
            lines.append(f"Frequence : {self.entries_submitted / weeks:.2f} entrees/semaine (alertes > {p.max_trades_per_week}/sem : {self.frequency_alerts})")
        lines.append("Rappel (Blitz et al.) : le retournement sur rendements bruts est faible depuis 1990 ; relancer en mode residuel pour comparer.")
