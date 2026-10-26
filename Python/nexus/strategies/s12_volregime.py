"""FICHE 12 - Regime par vol realisee + modeles conditionnels (port de Nexus12_VolRegimeConditional.cs).

Terciles de la vol 20 j du barometre sur 2 ans (anti-clignotement 5 j) ou HMM du module A ;
momentum 100/75/25 % selon le regime + retour a la moyenne en haute vol ; parametres par
regime recalibres tous les 30 j sur 180 j, uniquement sur les jours du regime (walk-forward).
"""
from __future__ import annotations

import math

import numpy as np

from .. import mathx as M
from .. import regime as R
from .. import signals as S
from .. import validation as V
from ..engine import NexusStrategy, split_list
from .s01_tsmom import UNIVERSE_25

_IDX = {R.CALME: 0, R.NEUTRE: 1, R.STRESS: 2}


class Nexus12VolRegimeConditional(NexusStrategy):
    NAME = "Nexus12_VolRegimeConditional"
    DESCRIPTION = "Fiche 12 - Terciles de vol 20 j (2 ans, 5 j) ; momentum 100/75/25 % + MR en haute vol ; parametres par regime en walk-forward."
    DEFAULTS = dict(
        symbols=UNIVERSE_25,
        sizing_mode="natif",
        regime_source="terciles",      # terciles | hmm
        barometer="SPY",
        vix_symbol="",
        rv_window_days=20,
        tercile_lookback_days=504,
        confirm_days=5,
        mom_calm_pct=100.0,
        mom_neutral_pct=75.0,
        mom_stress_pct=25.0,
        mr_calm_pct=0.0,
        mr_neutral_pct=0.0,
        mr_stress_pct=100.0,
        mom_grid="63,126,252",
        mr_grid="1.5,2.0,2.5",
        default_mom_lookback=252,
        default_mr_z=2.0,
        skip_days=21,
        mr_max_hold_days=5,
        mr_vol_days=60,
        train_days=180,
        recalibrate_days=30,
        min_regime_days=30,
        target_vol_pct=12.0,
        vol_window_days=126,
        atr_multiplier=3.0,
        stop_min_pct=2.0,
        stop_max_pct=8.0,
        resize_threshold_pct=20.0,
    )

    def required_references(self):
        r = [self.p.barometer]
        if self.p.vix_symbol:
            r.append(self.p.vix_symbol)
        return r

    def on_data_loaded(self):
        p = self.p
        self.terciles = R.VolTercileRegime(p.rv_window_days, p.tercile_lookback_days, p.confirm_days)
        self.hmm = R.LazyHmm(p.regime_source == "hmm", bool(p.vix_symbol) and self.sym(p.vix_symbol) is not None)
        self.regime_by_day = {}
        self.mom_l = [p.default_mom_lookback] * 3
        self.mr_z = [p.default_mr_z] * 3
        self.mom_sig = {}
        self.mr_held_since = {}
        self.last_regime = R.INCONNU
        self.last_calibration = -(1 << 29)
        self.calibrations = self.transitions = 0
        self.regime_days = [0, 0, 0]
        self.grid_l = [int(float(x)) for x in split_list(p.mom_grid) if int(float(x)) > p.skip_days + 5]
        self.grid_z = [float(x) for x in split_list(p.mr_grid) if float(x) > 0]

    def _mr_z_at(self, h, i):
        p = self.p
        if i < p.mr_vol_days + 6 or i >= h.count:
            return M.NAN
        r = h.logret[i - p.mr_vol_days + 1: i + 1]
        m = r.sum() / p.mr_vol_days
        v = (r * r).sum() / p.mr_vol_days - m * m
        if not v > 0:
            return M.NAN
        r5 = math.log(h.close[i] / h.close[i - 5])
        return r5 / (math.sqrt(v) * math.sqrt(5.0))

    def on_batch(self, day):
        p = self.p
        baro = self.sym(p.barometer)
        if baro is None:
            self.nx_once("nobaro", "Barometre introuvable : " + p.barometer)
            return
        vix = self.sym(p.vix_symbol) if p.vix_symbol else None
        self.terciles.update(baro.hist.last_close)
        self.hmm.update(baro.hist.last_close, vix.hist.last_close if vix is not None else M.NAN)
        regime = self.hmm.regime if p.regime_source == "hmm" else self.terciles.regime
        if regime == R.INCONNU:
            return
        self.regime_by_day[day] = regime
        self.regime_days[_IDX[regime]] += 1
        changed = regime != self.last_regime and self.last_regime != R.INCONNU
        if changed:
            self.transitions += 1
            self.nx(f"{day:%Y-%m-%d} changement de regime {self.last_regime} -> {regime}")
        if self.batch_count - self.last_calibration >= p.recalibrate_days:
            self._calibrate(day)
            self.last_calibration = self.batch_count
        traded = self.traded_syms
        ri = _IDX[regime]
        monthly = self.is_rebalance_day(day, "mensuel", baro)
        n_valid = sum(1 for s in traded if s.hist.count > self.mom_l[ri] + 1)
        if n_valid == 0:
            self.last_regime = regime
            return
        alloc_mom = (p.mom_calm_pct, p.mom_neutral_pct, p.mom_stress_pct)[ri] / 100.0
        alloc_mr = (p.mr_calm_pct, p.mr_neutral_pct, p.mr_stress_pct)[ri] / 100.0
        for s in traded:
            h = s.hist
            if h.count < max(self.mom_l[ri], p.mr_vol_days) + 7:
                continue
            if monthly or changed or s.name not in self.mom_sig:
                m = h.return_over(self.mom_l[ri], p.skip_days)
                self.mom_sig[s.name] = 1 if M.ok(m) and m > 0 else 0
            z = self._mr_z_at(h, h.count - 1)
            held_since = self.mr_held_since.get(s.name)
            in_mr = held_since is not None
            if in_mr and (alloc_mr <= 0 or (M.ok(z) and z > 0) or self.batch_count - held_since >= p.mr_max_hold_days):
                del self.mr_held_since[s.name]
                in_mr = False
            elif not in_mr and alloc_mr > 0 and M.ok(z) and z < -self.mr_z[ri]:
                self.mr_held_since[s.name] = self.batch_count
                in_mr = True
            base_w = S.inverse_vol_weight(h, p.target_vol_pct / 100.0, p.vol_window_days, n_valid, 0)
            if not M.ok(base_w):
                continue
            frac = base_w * (alloc_mom * self.mom_sig[s.name] + (alloc_mr if in_mr else 0.0))
            q = self.size_qty(s, frac, s.last_price)[0] if frac > 0 else 0
            cur = s.target_qty
            resize = (q == 0) != (cur == 0) or (cur > 0 and abs(q - cur) > p.resize_threshold_pct / 100.0 * cur)
            if not resize:
                continue
            stop = S.long_stop(s.last_price, h.atr, p.atr_multiplier, p.stop_min_pct / 100, p.stop_max_pct / 100) if q > 0 else M.NAN
            if q > 0 and s.qty > 0 and M.ok(s.stop_price):
                stop = max(stop, s.stop_price)
            if s.qty == 0:
                s.regime = regime
            self.set_target(s, q, stop, f"regime {regime} : mom {self.mom_sig[s.name]}x{alloc_mom:.0%} (L={self.mom_l[ri]}) + "
                                        f"MR {int(in_mr)}x{alloc_mr:.0%} (z={z:.2f}, seuil {self.mr_z[ri]})")
        self.last_regime = regime

    # --- calibrage walk-forward par regime ------------------------------------
    def _calibrate(self, day):
        p = self.p
        traded = [s for s in self.traded_syms if s.hist.count > p.train_days + 260]
        if not traded:
            return
        window = sorted(d for d in self.regime_by_day if d <= day)[-p.train_days:]
        self.calibrations += 1
        z_prev = {}
        for s in traded:
            z = np.full(len(window), M.NAN)
            for w, d in enumerate(window):
                i = s.hist.index_of(d)
                z[w] = self._mr_z_at(s.hist, i - 1) if i >= p.mr_vol_days + 8 else M.NAN
            z_prev[s.name] = z
        for r in (R.CALME, R.NEUTRE, R.STRESS):
            ri = _IDX[r]
            rd = {d for d in window if self.regime_by_day[d] == r}
            if len(rd) < p.min_regime_days:
                self.mom_l[ri], self.mr_z[ri] = p.default_mom_lookback, p.default_mr_z
                continue
            best = -math.inf
            for L in self.grid_l:
                sh = self._eval_momentum(traded, window, rd, L)
                if M.ok(sh) and sh > best:
                    best, self.mom_l[ri] = sh, L
            best_z = -math.inf
            for k in self.grid_z:
                sh = self._eval_mean_reversion(traded, window, rd, k, z_prev)
                if M.ok(sh) and sh > best_z:
                    best_z, self.mr_z[ri] = sh, k

    def _eval_momentum(self, syms, window, rd, L):
        p = self.p
        daily = []
        for d in window:
            if d not in rd:
                continue
            tot, n = 0.0, 0
            for s in syms:
                h = s.hist
                i = h.index_of(d)
                if i < L + 2:
                    continue
                sig = h.close[i - 1 - p.skip_days] / h.close[i - 1 - L] - 1
                tot += (1 if sig > 0 else 0) * (h.close[i] / h.close[i - 1] - 1)
                n += 1
            if n > 0:
                daily.append(tot / n)
        return V.sharpe_per_period(daily) if len(daily) >= p.min_regime_days else M.NAN

    def _eval_mean_reversion(self, syms, window, rd, k, z_prev_by_sym):
        p = self.p
        sm, cnt = {}, {}
        for s in syms:
            h = s.hist
            pos = held = 0
            zs = z_prev_by_sym[s.name]
            for w, d in enumerate(window):
                i = h.index_of(d)
                if i < p.mr_vol_days + 8:
                    continue
                zp = zs[w]
                if pos == 1 and (held >= p.mr_max_hold_days or (M.ok(zp) and zp > 0)):
                    pos = held = 0
                elif pos == 0 and M.ok(zp) and zp < -k:
                    pos, held = 1, 0
                if pos == 1:
                    held += 1
                if d not in rd:
                    continue
                sm[d] = sm.get(d, 0.0) + pos * (h.close[i] / h.close[i - 1] - 1)
                cnt[d] = cnt.get(d, 0) + 1
        daily = [sm[d] / cnt[d] for d in sorted(sm)]
        return V.sharpe_per_period(daily) if len(daily) >= p.min_regime_days else M.NAN

    def report_extras(self, lines):
        tot = sum(self.regime_days) or 1
        rd = self.regime_days
        lines.append(f"Source de regime : {self.p.regime_source} | jours calme/neutre/stress : {rd[0]}/{rd[1]}/{rd[2]} "
                     f"({rd[0] / tot:.0%}/{rd[1] / tot:.0%}/{rd[2] / tot:.0%}) | transitions {self.transitions} | calibrages {self.calibrations}")
        lines.append(f"Parametres courants : calme L={self.mom_l[0]} z={self.mr_z[0]} | neutre L={self.mom_l[1]} z={self.mr_z[1]} | "
                     f"stress L={self.mom_l[2]} z={self.mr_z[2]}")
        for r in (R.CALME, R.NEUTRE, R.STRESS):
            t = [x for x in self.closed_trades if x.regime == r]
            wr = sum(1 for x in t if x.net_pnl > 0) / len(t) if t else 0
            lines.append(f"Trades ouverts en regime {r:<7}: {len(t):4d} | PnL net {sum(x.net_pnl for x in t):10.2f} | reussite {wr:.0%}"
                         + ("  <- moins de 30 trades : non valide (module C)" if len(t) < 30 else ""))
