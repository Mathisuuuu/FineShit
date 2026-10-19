"""FICHE 5 - Retour a la moyenne de la volatilite (port de Nexus05_VolatilityMeanReversion.cs).

w = c / variance realisee 21 j (Moreira-Muir, c GLISSANT sur 3 ans), plafonne a 1 ; w = 1 <-> 10 %
du bankroll. Pic (vol 5j/60j > 1.8) : exposition coupee a w ; retour (ratio < 1.2 et vol 5 j en baisse
3 jours) par paliers de 25 % / semaine ; jamais d ajout quand la vol courte monte. Mode par symbole.
"""
from __future__ import annotations

import numpy as np

from .. import data as D
from .. import mathx as M
from ..engine import NexusStrategy


class _VolState:
    def __init__(self):
        self.etat = "Normal"
        self.vol5: list[float] = []
        self.last_week_key = None
        self.exposure = 0.0
        self.last_w = self.last_c = M.NAN
        self.spikes = self.recoveries = 0


class Nexus05VolatilityMeanReversion(NexusStrategy):
    NAME = "Nexus05_VolatilityMeanReversion"
    DESCRIPTION = "Fiche 5 - w = c/variance (c glissant), coupure au pic 5j/60j > 1.8, retour par paliers de 25 %/semaine."
    BATCH_MODE = False
    DEFAULTS = dict(
        symbols="SPY,QQQ,BTCUSD,ETHUSD",
        sizing_mode="natif",
        max_trade_pct=10.0,
        max_symbol_pct=10.0,
        stop_mode="aucun",
        variance_window_days=21,
        calibration_days=756,
        min_calibration_days=252,
        max_weight=1.0,
        allocation_per_asset_pct=10.0,
        short_vol_days=5,
        long_vol_days=60,
        spike_ratio=1.8,
        calm_ratio=1.2,
        decline_days=3,
        recovery_step_pct=25.0,
        rebalance_threshold_pct=20.0,
    )

    def on_data_loaded(self):
        self.states = {}

    def _st(self, s) -> _VolState:
        return self.states.setdefault(s.name, _VolState())

    def _calibrate_c(self, h: D.History) -> float:
        """c glissant : sigma(r) / sigma(r_t / RV_{t-1}) sur la fenetre de calibration (aucune donnee future)."""
        p = self.p
        n = h.count
        start = max(p.variance_window_days + 2, n - p.calibration_days)
        if n - start < p.min_calibration_days:
            return M.NAN
        i = np.arange(start, n)
        r = h.logret[i]
        # rv = somme des r^2 de i-21 a i-1 (prefixe des carres, NaN = 0)
        rv = h.csum_r2[i] - h.csum_r2[i - p.variance_window_days]
        ok = np.isfinite(r) & (rv > 0)
        raw, managed = r[ok], r[ok] / rv[ok]
        sr, sm = M.std(raw), M.std(managed)
        return sr / sm if M.ok(sr) and M.ok(sm) and sm > 0 else M.NAN

    def on_symbol_bar(self, s, day):
        p = self.p
        if not s.traded:
            return
        h = s.hist
        if h.count < max(p.long_vol_days, p.variance_window_days) + 3:
            return
        v = self._st(s)
        rv = h.realized_variance(p.variance_window_days)
        c = self._calibrate_c(h)
        if not M.ok(c) or not rv > 0:
            return
        w = min(p.max_weight, c / rv)
        v.last_w, v.last_c = w, c
        rets = h.returns(p.long_vol_days)
        vol5 = M.std(rets[-p.short_vol_days:]) if rets.size >= p.short_vol_days else M.NAN
        vol60 = M.std(rets)
        ratio = vol5 / vol60 if M.ok(vol5) and M.ok(vol60) and vol60 > 0 else M.NAN
        vol5_rising = bool(v.vol5) and vol5 > v.vol5[-1]
        v.vol5.append(vol5)
        if len(v.vol5) > 30:
            v.vol5.pop(0)
        declining = len(v.vol5) > p.decline_days
        k = 0
        while declining and k < p.decline_days:
            declining = v.vol5[-1 - k] < v.vol5[-2 - k]
            k += 1
        # Exposition VISEE (fraction de l allocation, AVANT module B) : etat propre a la fiche, pour que
        # les regles comparent toujours des grandeurs avant module B. Resynchronisee a 0 si la position
        # a ete coupee de l exterieur (entree rejetee, disjoncteur).
        if s.target_qty == 0 and s.qty == 0:
            v.exposure = 0.0
        cur = v.exposure
        wk = D.week_key(day)
        week_end = D.is_last_trading_day_of_week(day, s.holidays, s.seven_days) or (v.last_week_key is not None and wk > v.last_week_key + 1)
        target, why = cur, None
        if M.ok(ratio) and ratio > p.spike_ratio:
            if v.etat != "Pic":
                v.etat = "Pic"
                v.spikes += 1
                self.nx(f"{s.name} {day:%Y-%m-%d} PIC de volatilite (ratio 5j/60j {ratio:.2f})")
            if cur > w:
                target, why = w, f"pic de vol (ratio {ratio:.2f}) -> exposition a w={w:.2f}"
        elif v.etat == "Pic":
            if cur > w:
                target, why = w, "pic en cours -> exposition a w"
            if M.ok(ratio) and ratio < p.calm_ratio and declining:
                v.etat = "Retour"
                v.recoveries += 1
        elif v.etat == "Retour":
            if week_end:
                target = min(w, cur + p.recovery_step_pct / 100.0 * w)
                why = f"retour par palier de {p.recovery_step_pct:.0f} % (w={w:.2f})"
            if cur > w:
                target, why = w, "retour : exposition ramenee a w"
            if target >= w - 1e-9:
                v.etat = "Normal"
        else:
            drift = cur > 0 and abs(cur - w) > p.rebalance_threshold_pct / 100.0 * max(w, 1e-6)
            if week_end or drift or cur == 0:
                target = w
                why = f"reequilibrage {'hebdomadaire' if week_end else 'au seuil'} w=c/var={w:.2f} (c={c:.4g})"
        if week_end:
            v.last_week_key = wk
        if target > cur and vol5_rising:
            target, why = cur, None
        if why is None or abs(target - cur) < 1e-9:
            return
        v.exposure = target
        q = 0 if target <= 0 else self.size_qty(s, target * p.allocation_per_asset_pct / 100.0, s.last_price)[0]
        if target > 0 and q == 0:
            self.nx_once("q0" + s.name, f"{s.name} : quantite nulle (capital ou plafonds) - augmenter le capital ou l allocation.")
        if q == s.target_qty:
            return          # aucune variation de quantite : pas d ordre
        self.set_target(s, q, M.NAN, why)

    def report_extras(self, lines):
        for name, v in self.states.items():
            lines.append(f"{name} : etat {v.etat} | pics {v.spikes} | retours {v.recoveries} | dernier w {v.last_w:.2f} (c={v.last_c:.4g}) | exposition visee {v.exposure:.2f}")
        lines.append("Rappel : c est estime en glissant (3 ans) ; le c de Moreira-Muir sur tout l echantillon utiliserait le futur.")
