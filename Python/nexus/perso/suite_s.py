"""Suite "Quant Futures" S01..S20 (portage Python des fichiers S*.cs du dossier NinjaTrader).

Portees : S01 (A, B, D), S02 (A, B, C), S05 (A), S06 (A, B), S07 (A), S09 (A, B), S11 (A, B), S19 (A, B), S20 (A, B).
Non portees : variantes a ML (S01-C HMM, S07-B logistique), a actualites / evenements (S05-C, S17), sans ordre par
construction (S04, S08, S12, S15, S16, S18), ou dont les donnees manquent (S03, S05-B, S07-C gamma d options, S10 VIX,
S13 perpetuel BTC + CME, S14 funding, S06-C Russell).
"""
from __future__ import annotations

import math
from datetime import date, timedelta

import numpy as np
import pandas as pd

from .qf import NAN, QfBase, Ring, hhmm, ok

LONDON, TOKYO, BERLIN, UTC = "Europe/London", "Asia/Tokyo", "Europe/Berlin", "UTC"


# =============================================================================
#  Calendrier (QF_Calendar.cs)
# =============================================================================
def _observed(d: date) -> date:
    if d.weekday() == 5:
        return d - timedelta(days=1)
    if d.weekday() == 6:
        return d + timedelta(days=1)
    return d


def _nth(y, m, wd, n):
    d = date(y, m, 1)
    return d + timedelta(days=(wd - d.weekday()) % 7 + 7 * (n - 1))


def _last(y, m, wd):
    d = date(y + (m == 12), m % 12 + 1, 1) - timedelta(days=1)
    while d.weekday() != wd:
        d -= timedelta(days=1)
    return d


def _good_friday(y):
    a, b, c = y % 19, y // 100, y % 100
    d, e = b // 4, b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = c // 4, c % 4
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    month = (h + l - 7 * m + 114) // 31
    day = ((h + l - 7 * m + 114) % 31) + 1
    return date(y, month, day) - timedelta(days=2)


_HOL: dict = {}


def us_holiday(d: date) -> bool:
    y = d.year
    if y not in _HOL:
        s = {_observed(date(y, 1, 1)), _nth(y, 1, 0, 3), _nth(y, 2, 0, 3), _good_friday(y), _last(y, 5, 0),
             _observed(date(y, 7, 4)), _nth(y, 9, 0, 1), _nth(y, 11, 3, 4), _observed(date(y, 12, 25))}
        if y >= 2021:
            s.add(_observed(date(y, 6, 19)))
        _HOL[y] = s
    return d in _HOL[y]


def business_day(d: date) -> bool:
    return d.weekday() < 5 and not us_holiday(d)


def is_eia_day(d: date) -> bool:
    if d.weekday() not in (2, 3):
        return False
    monday = d - timedelta(days=d.weekday())
    early = any(us_holiday(monday + timedelta(days=i)) for i in range(3))
    return d.weekday() == (3 if early else 2)


def is_month_end_window(d: date, n: int) -> bool:
    if not business_day(d):
        return False
    n = max(1, n)
    x = date(d.year + (d.month == 12), d.month % 12 + 1, 1) - timedelta(days=1)
    found = 0
    while x >= d:
        if business_day(x):
            found += 1
            if x == d:
                return found <= n
            if found >= n:
                return False
        x -= timedelta(days=1)
    return False


def day_of(dnum: int) -> date:
    return date(1970, 1, 1) + timedelta(days=int(dnum))


def zone_arrays(engine, tz: str):
    """(minutes du jour, jour calendaire) des fins de barre dans un fuseau donne."""
    loc = engine.index.tz_localize("UTC").tz_convert(tz).tz_localize(None)
    tod = (loc.hour * 60 + loc.minute + loc.second / 60.0).to_numpy(float)
    dn = (loc.asi8 // 86_400_000_000_000).astype(np.int64)
    return tod, dn


# =============================================================================
#  S01 - Momentum intraday
# =============================================================================
class S01(QfBase):
    NAME = "S01 Momentum intraday"
    DEFAULTS = dict(variante="A", entree=1530, sortie=1600, derniere_entree=1530, stop_atr_mult=0.0, bande_mult=1.0,
                    noise_lookback_jours=14, premier_checkpoint=1000, intervalle_checkpoint=30, mode_trailing="bande_vwap",
                    trail_atr_mult=1.5, vol_cible_jour_pct=2.0, levier_max=4.0, facteur_vol_scale=1.0)

    def init(self):
        p = self.p
        self.entry_ts, self.exit_ts, self.last_entry_ts = hhmm(p.entree), hhmm(p.sortie), hhmm(p.derniere_entree)
        self.checkpoints = []
        t = hhmm(p.premier_checkpoint)
        while t <= self.rth_end:
            self.checkpoints.append(t)
            t += max(1, p.intervalle_checkpoint)
        self.noise = {}
        self.noise_day = None
        self.band_up = self.band_lo = NAN
        self.trail_anchor = NAN

    def on_quant_bar(self, i):
        if self.p.variante == "B":
            self._update_noise(i)
            self._run_vwap_band(i)
        else:
            self._run_last_half_hour(i)

    def _update_noise(self, i):
        e = self.e
        if self.sdate != self.noise_day:
            self.noise_day = self.sdate
            self.band_up = self.band_lo = NAN
        if not self.in_rth or not ok(self.rth_open) or self.rth_open <= 0:
            return
        for cp in self.checkpoints:
            if not self.crossed_tod(cp):
                continue
            hist = self.noise.setdefault(cp, Ring(max(2, self.p.noise_lookback_jours)))
            sigma = hist.mean() if len(hist) >= 2 else NAN
            if ok(sigma) and sigma > 0:
                hi = max(self.rth_open, self.prev_rth_close) if ok(self.prev_rth_close) else self.rth_open
                lo = min(self.rth_open, self.prev_rth_close) if ok(self.prev_rth_close) else self.rth_open
                self.band_up = hi * (1 + self.p.bande_mult * sigma)
                self.band_lo = lo * (1 - self.p.bande_mult * sigma)
            hist.add(abs(e.c[i] / self.rth_open - 1.0))
            return

    def _size_b(self):
        if len(self.daily_ret_ring) < 5:
            return self.compute_size(1.0)
        sd = self.daily_ret_ring.std()
        if not ok(sd) or sd <= 1e-8:
            return self.compute_size(1.0)
        lev = min(self.p.levier_max, self.p.vol_cible_jour_pct / 100.0 / sd)
        return int(min(max(int(math.floor(self.p.base_qty * lev + 0.5)), 1), self.p.max_qty))

    def _size_d(self, conv):
        if not ok(self.sigma_daily) or self.sigma_daily < 1e-6 or not ok(conv):
            return self.compute_size(1.0)
        q = self.p.base_qty * self.p.facteur_vol_scale * conv / self.sigma_daily
        return int(min(max(int(math.floor(q + 0.5)), 1), self.p.max_qty)) if ok(q) else self.compute_size(1.0)

    def _run_last_half_hour(self, i):
        e = self.e
        if self.crossed_tod(self.entry_ts):
            if self.has_first30 and ok(self.r_first30) and self.vol_filter_passes():
                d = int(np.sign(self.r_first30))
                if d:
                    qty = self._size_d(abs(self.r_first30)) if self.p.variante == "D" else self.compute_size(abs(self.r_first30))
                    stop = (e.c[i] - d * self.p.stop_atr_mult * self.atr_pts) if self.p.stop_atr_mult > 0 else NAN
                    self.enter(d, qty, "S01A", stop=stop)
        if self.sortie_temporelle(self.exit_ts) and e.pos != 0:
            self.go_flat("moc")

    def _stop_dyn(self, d, i):
        e = self.e
        if self.p.mode_trailing == "atr":
            if d > 0:
                self.trail_anchor = max(self.trail_anchor, e.h[i]) if ok(self.trail_anchor) else e.h[i]
                return self.trail_anchor - self.p.trail_atr_mult * self.atr_pts
            self.trail_anchor = min(self.trail_anchor, e.l[i]) if ok(self.trail_anchor) else e.l[i]
            return self.trail_anchor + self.p.trail_atr_mult * self.atr_pts
        return max(self.band_lo, self.vwap) if d > 0 else min(self.band_up, self.vwap)

    def _run_vwap_band(self, i):
        e = self.e
        if self.sortie_temporelle(self.exit_ts):
            if e.pos != 0:
                self.go_flat("moc")
            self.trail_anchor = NAN
            return
        if e.pos != 0:
            self.set_stop(self._stop_dyn(1 if e.pos > 0 else -1, i))
            return
        self.trail_anchor = NAN
        if not self.in_rth or self.tod > self.last_entry_ts or not ok(self.vwap) or not ok(self.band_up) or not ok(self.band_lo):
            return
        if not self.vol_filter_passes():
            return
        if not any(cp <= self.tod < cp + self.bar_span for cp in self.checkpoints):
            return
        px = e.c[i]
        d = 1 if (px > self.band_up and px > self.vwap) else (-1 if (px < self.band_lo and px < self.vwap) else 0)
        if d == 0:
            return
        self.trail_anchor = e.h[i] if d > 0 else e.l[i]
        self.enter(d, self._size_b(), "S01B", stop=self._stop_dyn(d, i))


# =============================================================================
#  S02 - Momentum cross-actifs
# =============================================================================
class S02(QfBase):
    NAME = "S02 Momentum cross-actifs"
    DEFAULTS = dict(variante="A", entree=1530, sortie=1600, stop_atr_mult=0.0, mode_eia="recalculer", eia_ref=1030, eia_fin=1100,
                    londres_open=800, londres_fenetre=30, londres_duree=240, inverser_signe=False,
                    nuit_debut=1800, nuit_fenetre=30, nuit_sortie=820, utiliser_ouverture_session=True)

    def init(self):
        p = self.p
        e = self.e
        self.entry_ts, self.exit_ts, self.eia_ref, self.eia_end = hhmm(p.entree), hhmm(p.sortie), hhmm(p.eia_ref), hhmm(p.eia_fin)
        self.eia_day, self.eia_ref_close, self.r_eia, self.has_r_eia = None, NAN, NAN, False
        self.lon_tod, self.lon_day = zone_arrays(e, LONDON)
        self.london_day, self.london_ref, self.london_ref_set, self.london_traded, self.london_exit = None, NAN, False, False, None
        self.night_ref, self.night_day, self.night_traded = NAN, None, False
        self.night_start = hhmm(p.nuit_debut)
        self.night_signal = (self.night_start + max(1, p.nuit_fenetre)) % 1440
        self.night_exit = hhmm(p.nuit_sortie)

    def on_quant_bar(self, i):
        {"A": self._wti, "B": self._london, "C": self._night}[self.p.variante](i)

    def _wti(self, i):
        e, p = self.e, self.p
        eia = is_eia_day(day_of(self.sdate))
        if eia and p.mode_eia == "recalculer":
            if self.sdate != self.eia_day:
                self.eia_day, self.eia_ref_close, self.r_eia, self.has_r_eia = self.sdate, NAN, NAN, False
            if self.crossed_tod(self.eia_ref):
                self.eia_ref_close = e.c[i]
            if self.crossed_tod(self.eia_end) and ok(self.eia_ref_close) and self.eia_ref_close > 0:
                self.r_eia, self.has_r_eia = e.c[i] / self.eia_ref_close - 1.0, True
        if self.crossed_tod(self.entry_ts):
            blocked = eia and p.mode_eia == "exclure"
            sig = NAN
            if not blocked:
                sig = (self.r_eia if self.has_r_eia else NAN) if (eia and p.mode_eia == "recalculer") else (self.r_first30 if self.has_first30 else NAN)
            if ok(sig) and self.vol_filter_passes():
                d = int(np.sign(sig))
                stop = (e.c[i] - d * p.stop_atr_mult * self.atr_pts) if p.stop_atr_mult > 0 else NAN
                if d:
                    self.enter(d, self.compute_size(abs(sig)), "S02A", stop=stop)
        if self.sortie_temporelle(self.exit_ts) and e.pos != 0:
            self.go_flat("moc")

    def _london(self, i):
        e, p = self.e, self.p
        tod, dn = self.lon_tod[i], self.lon_day[i]
        op, sig_ts = hhmm(p.londres_open), hhmm(p.londres_open) + max(1, p.londres_fenetre)
        if dn != self.london_day:
            self.london_day, self.london_ref, self.london_ref_set, self.london_traded = dn, NAN, False, False
        if not self.london_ref_set and tod >= op:
            self.london_ref, self.london_ref_set = e.c[i], True
        if e.pos != 0 and self.london_exit is not None and e.index[i] >= self.london_exit:
            self.go_flat("duree")
            self.london_exit = None
            return
        if not self.london_traded and self.london_ref_set and tod >= sig_ts and ok(self.london_ref) and self.london_ref > 0:
            self.london_traded = True
            r = e.c[i] / self.london_ref - 1.0
            d = int(np.sign(r)) * (-1 if p.inverser_signe else 1)
            if d and self.vol_filter_passes():
                stop = (e.c[i] - d * p.stop_atr_mult * self.atr_pts) if p.stop_atr_mult > 0 else NAN
                if self.enter(d, self.compute_size(abs(r)), "S02B", stop=stop):
                    self.london_exit = e.index[i] + pd.Timedelta(minutes=max(1, p.londres_duree))

    def _night(self, i):
        e, p = self.e, self.p
        first_of_session = i > 0 and e.tday[i] != e.tday[i - 1]
        if p.utiliser_ouverture_session:
            if first_of_session:
                self.night_ref, self.night_day, self.night_traded = e.o[i], e.tday[i], False
        elif e.tday[i] != self.night_day and self.crossed_tod(self.night_start):
            self.night_ref, self.night_day, self.night_traded = e.o[i], e.tday[i], False
        if self.final_bar_before(self.night_exit):
            if e.pos != 0:
                self.go_flat("fin-nuit")
            return
        if self.night_traded or not ok(self.night_ref) or self.night_ref <= 0 or e.tday[i] != self.night_day:
            return
        if not self.crossed_tod(self.night_signal):
            return
        self.night_traded = True
        r = e.c[i] / self.night_ref - 1.0
        d = int(np.sign(r))
        if d and self.vol_filter_passes():
            stop = (e.c[i] - d * p.stop_atr_mult * self.atr_pts) if p.stop_atr_mult > 0 else NAN
            self.enter(d, self.compute_size(abs(r)), "S02C", stop=stop)


# =============================================================================
#  S05 - Prime 0DTE (variante A : reversal de l opening range)
# =============================================================================
class S05(QfBase):
    NAME = "S05 Prime 0DTE (A)"
    DEFAULTS = dict(orb_minutes=5, bucket_minutes=5, buckets_autorises=3, biais="short", seuil_breach_ticks=1, max_trades_jour=1,
                    filtre_gap="tous", mode_r="range", facteur_r=1.0, r_ticks=40)

    def init(self):
        self.or_end = self.rth_start + max(1, self.p.orb_minutes)
        self.or_day = None
        self.or_hi = self.or_lo = NAN
        self.or_complete = self.br_hi = self.br_lo = False
        self.trades_today = 0

    def _update_or(self, i):
        e = self.e
        if self.sdate != self.or_day and self.in_rth:
            self.or_day, self.or_hi, self.or_lo = self.sdate, e.h[i], e.l[i]
            self.or_complete = self.br_hi = self.br_lo = False
            self.trades_today = 0
        if not self.in_rth or self.sdate != self.or_day:
            return
        if not self.or_complete:
            if self.tod <= self.or_end:
                self.or_hi, self.or_lo = max(self.or_hi, e.h[i]), min(self.or_lo, e.l[i])
            if self.tod >= self.or_end:
                self.or_complete = True
            return
        thr = self.p.seuil_breach_ticks * e.inst.tick
        if e.h[i] > self.or_hi + thr:
            self.br_hi = True
        if e.l[i] < self.or_lo - thr:
            self.br_lo = True

    def on_quant_bar(self, i):
        e, p = self.e, self.p
        self._update_or(i)
        if self.sortie_temporelle(self.rth_end):
            if e.pos != 0:
                self.go_flat("moc")
            return
        if not self.or_complete or not self.in_rth or e.pos != 0 or self.trades_today >= p.max_trades_jour:
            return
        bucket = int(math.floor((self.tod - self.or_end) / max(1, p.bucket_minutes)))
        if bucket < 0 or bucket >= p.buckets_autorises:
            return
        if p.filtre_gap != "tous":
            if not self.has_overnight or not ok(self.r_overnight):
                return
            if (p.filtre_gap == "gap_up") != (self.r_overnight > 0):
                return
        thr = p.seuil_breach_ticks * e.inst.tick
        d = 0
        if self.br_hi and e.c[i] < self.or_hi - thr:
            d = -1
        elif p.biais == "long_et_short" and self.br_lo and e.c[i] > self.or_lo + thr:
            d = 1
        if d == 0 or (d > 0 and p.biais == "short"):
            return
        if p.mode_r == "atr":
            r = max(e.inst.tick, p.facteur_r * self.atr_pts)
        elif p.mode_r == "ticks":
            r = max(e.inst.tick, p.r_ticks * e.inst.tick)
        else:
            rng = self.or_hi - self.or_lo
            r = max(e.inst.tick, p.facteur_r * rng) if ok(rng) and rng > 0 else max(e.inst.tick, self.atr_pts)
        px = e.c[i]
        if self.enter(d, self.compute_size(1.0), "S05A", stop=px - d * r, target=px + d * r):
            self.trades_today += 1


# =============================================================================
#  S06 - Overnight reversal
# =============================================================================
class S06(QfBase):
    NAME = "S06 Overnight reversal"
    DEFAULTS = dict(variante="A", seuil_jump=2.0, fenetre_jump_jours=60, duree_detention_min=60, seuil_min_overnight_pct=0.0,
                    stop_atr_mult=0.0, tp_atr_mult=0.0, corrige=False)

    def init(self):
        self.on_abs = Ring(max(10, self.p.fenetre_jump_jours))
        self.hold_exit = None
        self.pending_open = False

    def on_quant_bar(self, i):
        e, p = self.e, self.p
        if e.pos != 0 and self.hold_exit is not None and e.index[i] >= self.hold_exit:
            self.go_flat("horizon")
            self.hold_exit = None
            return
        if self.sortie_temporelle(self.rth_end):
            if e.pos != 0:
                self.go_flat("close")
            self.hold_exit = None
            return
        if p.corrige:
            # Correction : la barre qui cloture a 09:30 est encore pre-ouverture -> r_overnight du JOUR n est connu
            # qu a la premiere barre RTH ; on decide donc sur cette barre (le C# fade le gap de la VEILLE).
            fire = self.in_rth and self.current_rth_date == self.sdate and not self.pending_open and self.has_overnight
            if self.tod <= self.rth_start:
                self.pending_open = False
            if not fire:
                return
            self.pending_open = True
        elif not self.crossed_tod(self.rth_start):
            return
        if not self.has_overnight or not ok(self.r_overnight):
            return
        a = abs(self.r_overnight)
        self.on_abs.add(a)
        if a < p.seuil_min_overnight_pct / 100.0:
            return
        if p.variante == "B":
            if len(self.on_abs) < 20:
                return
            sd = self.overnight_ring.std() if len(self.overnight_ring) >= 20 else self.on_abs.std()
            if not ok(sd) or sd <= 0 or a <= p.seuil_jump * sd:
                return
        if not self.vol_filter_passes():
            return
        d = -int(np.sign(self.r_overnight))
        if d == 0:
            return
        px = e.c[i]
        stop = px - d * p.stop_atr_mult * self.atr_pts if p.stop_atr_mult > 0 else NAN
        tgt = px + d * p.tp_atr_mult * self.atr_pts if p.tp_atr_mult > 0 else NAN
        if self.enter(d, self.compute_size(a), "S06" + p.variante, stop=stop, target=tgt) and p.variante == "B":
            self.hold_exit = e.index[i] + pd.Timedelta(minutes=max(1, p.duree_detention_min))


# =============================================================================
#  S07 - Gap d ouverture, variante A (post-settle -> gap, regression ridge)
# =============================================================================
class Ridge:
    def __init__(self, k: int, window: int):
        self.k, self.window = k, max(k + 5, window)
        self.xs: list = []
        self.ys: list = []
        self.beta = np.zeros(k + 1)
        self.fitted = False
        self.r2 = NAN

    def push(self, x, y):
        if not ok(y) or not all(ok(v) for v in x):
            return
        self.xs.append(list(x))
        self.ys.append(y)
        if len(self.ys) > self.window:
            del self.xs[0]
            del self.ys[0]

    def fit(self, lam: float):
        n = len(self.ys)
        if n < self.k + 6:
            self.fitted = False
            return False
        X = np.column_stack([np.ones(n), np.asarray(self.xs)])
        y = np.asarray(self.ys)
        A = X.T @ X
        A[1:, 1:] += lam * np.eye(self.k)
        try:
            b = np.linalg.solve(A, X.T @ y)
        except np.linalg.LinAlgError:
            self.fitted = False
            return False
        self.beta, self.fitted = b, True
        res = y - X @ b
        sst = ((y - y.mean()) ** 2).sum()
        self.r2 = 1 - (res ** 2).sum() / sst if sst > 0 else 0.0
        return True

    def predict(self, x):
        return float(self.beta[0] + np.dot(self.beta[1:], x))

    @property
    def n(self):
        return len(self.ys)


def sharpe(arr, ppy=252.0):
    a = np.asarray(arr, float)
    if a.size < 2:
        return NAN
    sd = a.std(ddof=1)
    return 0.0 if sd < 1e-12 else a.mean() / sd * math.sqrt(ppy)


class S07(QfBase):
    NAME = "S07 Gap d ouverture (A)"
    DEFAULTS = dict(settle=1600, fin_post_settle=1700, fenetre_estimation=250, lambda_ridge=0.01, refit_jours=5,
                    seuil_qualite=0.10, seuil_gap_pred_pct=0.05, stop_atr_mult=3.0)

    def init(self):
        p = self.p
        self.settle_ts, self.ps_end = hhmm(p.settle), hhmm(p.fin_post_settle)
        self.ridge_mbi, self.ridge_gap = Ridge(1, p.fenetre_estimation), Ridge(1, p.fenetre_estimation)
        self.qualite = Ring(max(20, p.fenetre_estimation // 2))
        self.settle_px = self.ps_hi = self.ps_lo = self.close_reel = self.r_ps_pending = self.last_pred = NAN
        self.ps_open = self.gap_pending = False
        self.obs = 0

    def _qualite_ok(self):
        if not self.ridge_gap.fitted or len(self.qualite) < 20:
            return False
        sh, r2 = sharpe(self.qualite.array()), self.ridge_gap.r2
        return ok(sh) and ok(r2) and r2 > 0 and sh * r2 >= self.p.seuil_qualite

    def on_quant_bar(self, i):
        e, p = self.e, self.p
        if self.crossed_tod(self.settle_ts):
            self.settle_px, self.ps_hi, self.ps_lo, self.ps_open = e.c[i], e.h[i], e.l[i], True
        elif self.ps_open:
            self.ps_hi, self.ps_lo = max(self.ps_hi, e.h[i]), min(self.ps_lo, e.l[i])
        if self.ps_open and self.crossed_tod(self.ps_end):
            self.ps_open = False
            self.close_reel = e.c[i]
            if ok(self.settle_px) and self.settle_px > 0:
                r_ps = self.close_reel / self.settle_px - 1.0
                rng = self.ps_hi - self.ps_lo
                mbi = 2.0 * (self.close_reel - self.ps_lo) / rng - 1.0 if rng > 0 else 0.0
                self.ridge_mbi.push([mbi], r_ps)
                if self.ridge_mbi.n % max(1, p.refit_jours) == 0:
                    self.ridge_mbi.fit(p.lambda_ridge)
                self.last_pred = self.ridge_gap.predict([r_ps]) if self.ridge_gap.fitted else NAN
                self.r_ps_pending, self.gap_pending = r_ps, True
                if self._qualite_ok() and ok(self.last_pred) and abs(self.last_pred) * 100 >= p.seuil_gap_pred_pct:
                    d = int(np.sign(self.last_pred))
                    stop = e.c[i] - d * p.stop_atr_mult * self.atr_pts if p.stop_atr_mult > 0 else NAN
                    if d:
                        self.enter(d, self.compute_size(abs(self.last_pred) * 100), "S07A", stop=stop)
        if self.crossed_tod(self.rth_start):
            if self.gap_pending and ok(self.close_reel) and self.close_reel > 0:
                gap = e.o[i] / self.close_reel - 1.0
                self.ridge_gap.push([self.r_ps_pending], gap)
                self.obs += 1
                if self.obs % max(1, p.refit_jours) == 0:
                    self.ridge_gap.fit(p.lambda_ridge)
                if ok(self.last_pred):
                    self.qualite.add(np.sign(self.last_pred) * gap)
                self.gap_pending = False
            if e.pos != 0:
                self.go_flat("open")


# =============================================================================
#  S09 - London fix
# =============================================================================
class S09(QfBase):
    NAME = "S09 London fix"
    DEFAULTS = dict(variante="A", fix_debut=1559, fix_fin=1600, minutes_pre_fix=30, minutes_post_fix=15, jours_fin_de_mois=2,
                    filtre_volume_pre_fix=False, fenetre_volume_jours=60, stop_atr_mult_a=2.0, mode_entree_or="fixing_soir",
                    fix_soir=1500, fix_matin=1030, bollinger_periode=20, bollinger_k=2.0, sortie_retour_moyenne=True,
                    stop_atr_mult_b=3.0, corrige=False)

    def init(self):
        p, e = self.p, self.e
        self.lon_tod, self.lon_day = zone_arrays(e, LONDON)
        self.london_date = None
        self.pre_ref, self.pre_set, self.fix_done, self.pre_vol = NAN, False, False, 0.0
        self.pre_vol_ring = Ring(max(10, p.fenetre_volume_jours))
        self.exit_at = None
        self.window_open = self.entered = False
        c = pd.Series(e.c)
        self.sma = c.rolling(p.bollinger_periode).mean().to_numpy()
        self.sd = c.rolling(p.bollinger_periode).std(ddof=0).to_numpy()
        self.p.bars_required = max(self.p.bars_required, p.bollinger_periode + 2)

    def on_quant_bar(self, i):
        if self.lon_day[i] != self.london_date:
            self.london_date = self.lon_day[i]
            self.pre_ref, self.pre_set, self.fix_done, self.pre_vol = NAN, False, False, 0.0
        (self._fix if self.p.variante == "A" else self._gold)(i)

    def _fix(self, i):
        e, p = self.e, self.p
        tod = self.lon_tod[i]
        fs, fe = hhmm(p.fix_debut), hhmm(p.fix_fin)
        pre = fs - max(1, p.minutes_pre_fix)
        if e.pos != 0 and self.exit_at is not None and e.index[i] >= self.exit_at:
            self.go_flat("post-fix")
            self.exit_at = None
            return
        if not self.pre_set and pre <= tod < fe:
            self.pre_ref, self.pre_set, self.pre_vol = e.c[i], True, 0.0
        if self.pre_set and not self.fix_done and tod < fe:
            self.pre_vol += e.v[i]
        if self.fix_done or not self.pre_set or tod < fe:
            return
        self.fix_done = True
        vol_ok = True
        if p.filtre_volume_pre_fix:
            med = self.pre_vol_ring.median() if len(self.pre_vol_ring) >= 10 else NAN
            vol_ok = ok(med) and self.pre_vol > med
        self.pre_vol_ring.add(self.pre_vol)
        if not is_month_end_window(day_of(self.lon_day[i]), p.jours_fin_de_mois) or not vol_ok:
            return
        if not ok(self.pre_ref) or self.pre_ref <= 0:
            return
        move = e.c[i] / self.pre_ref - 1.0
        d = -int(np.sign(move))
        if d == 0:
            return
        stop = e.c[i] - d * p.stop_atr_mult_a * self.atr_pts if p.stop_atr_mult_a > 0 else NAN
        if self.enter(d, self.compute_size(abs(move)), "S09A", stop=stop):
            self.exit_at = e.index[i] + pd.Timedelta(minutes=max(1, p.minutes_post_fix))

    def _gold(self, i):
        e, p = self.e, self.p
        tod = self.lon_tod[i]
        soir, matin = hhmm(p.fix_soir), hhmm(p.fix_matin)
        ma, sd = self.sma[i], self.sd[i]
        lower = ma - p.bollinger_k * sd if ok(ma) and ok(sd) else NAN
        if e.pos != 0:
            sortie_fix = matin <= tod < soir
            sortie_moy = p.sortie_retour_moyenne and ok(ma) and e.c[i] >= ma
            if sortie_fix or sortie_moy:
                self.go_flat("fixing-matin" if sortie_fix else "retour-moyenne")
                if p.corrige and not sortie_fix:
                    self.window_open, self.entered = True, True      # correction : une seule entree par soiree
                else:
                    self.window_open = self.entered = False          # tel que code : la fenetre se rouvre aussitot
            return
        if not self.window_open and tod >= soir:
            self.window_open, self.entered = True, False
        if self.window_open and matin <= tod < soir:
            self.window_open = self.entered = False
            return
        if not self.window_open or self.entered or not self.can_long:
            return
        entrer = True if p.mode_entree_or == "fixing_soir" else (ok(lower) and e.c[i] < lower)
        if not entrer:
            return
        self.entered = True
        conv = max(1.0, (lower - e.c[i]) / sd + 1.0) if ok(lower) and ok(sd) and sd > 0 else 1.0
        stop = e.c[i] - p.stop_atr_mult_b * self.atr_pts if p.stop_atr_mult_b > 0 else NAN
        self.enter(1, self.compute_size(conv), "S09B", stop=stop)


# =============================================================================
#  S11 - Price discovery de l or (sessions Asie / Europe / US)
# =============================================================================
class S11(QfBase):
    NAME = "S11 Price discovery or"
    DEFAULTS = dict(variante="A", direction="long_uniquement", asie=0, europe=800, us=1430, inclure_jambe_us=False,
                    exclure_signal_us=False, seuil_min_rendement_pct=0.0, stop_atr_mult=3.0, corrige=False)

    def init(self):
        self.utc_tod, _ = zone_arrays(self.e, UTC)
        self.cur = -1
        self.sess_open = NAN

    def _idx(self, tod):
        p = self.p
        if tod >= hhmm(p.us):
            return 2
        if tod >= hhmm(p.europe):
            return 1
        if tod >= hhmm(p.asie):
            return 0
        return 2

    def on_quant_bar(self, i):
        e, p = self.e, self.p
        idx = self._idx(self.utc_tod[i])
        if self.cur < 0:
            self.cur, self.sess_open = idx, e.c[i]
            return
        if idx == self.cur:
            return
        r = e.c[i] / self.sess_open - 1.0 if ok(self.sess_open) and self.sess_open > 0 else NAN
        prev, self.cur, self.sess_open = self.cur, idx, e.c[i]
        if e.pos != 0:
            self.go_flat("fin-session")
        if (not p.inclure_jambe_us and self.cur == 2) or (p.exclure_signal_us and prev == 2) or not ok(r):
            return
        if abs(r) * 100 < p.seuil_min_rendement_pct:
            return
        d = int(np.sign(r))
        if d == 0 or (p.variante == "A" and d < 0):
            return
        stop = e.c[i] - d * p.stop_atr_mult * self.atr_pts if p.stop_atr_mult > 0 else NAN
        if p.corrige and e.pos != 0 and np.sign(e.pos) == d:
            # Correction : meme sens que la session precedente -> on garde la position (nouveau stop).
            e.market(d * self.compute_size(abs(r)), "S11", e.round_tick(stop) if ok(stop) else NAN, NAN, "entree S11")
        else:
            # Tel que code : GoFlat puis EnterDirectional, qui REFUSE l entree si la position (pas encore soldee)
            # est deja dans ce sens -> la strategie reste a plat pendant la session.
            self.enter(d, self.compute_size(abs(r)), "S11", stop=stop)


# =============================================================================
#  S19 - Rebalancement des ETF a levier
# =============================================================================
class S19(QfBase):
    NAME = "S19 Rebalancement LETF"
    DEFAULTS = dict(variante="A", us_ouverture=930, us_debut=1530, us_fin=1600, dax_ouverture=900, dax_debut=1700, dax_fin=1730,
                    sizing_amplitude=True, amplitude_ref_pct=0.50, seuil_min_rday_pct=0.0, stop_atr_mult=2.0)

    def init(self):
        p = self.p
        if p.variante == "A":
            self.loc_tod, self.loc_day = self.e.tod, self.e.date
            self.op, self.deb, self.fin = hhmm(p.us_ouverture), hhmm(p.us_debut), hhmm(p.us_fin)
        else:
            self.loc_tod, self.loc_day = zone_arrays(self.e, BERLIN)
            self.op, self.deb, self.fin = hhmm(p.dax_ouverture), hhmm(p.dax_debut), hhmm(p.dax_fin)
        self.day, self.open_ref, self.ref_set, self.done = None, NAN, False, False

    def on_quant_bar(self, i):
        e, p = self.e, self.p
        tod = self.loc_tod[i]
        if self.loc_day[i] != self.day:
            self.day, self.open_ref, self.ref_set, self.done = self.loc_day[i], NAN, False, False
        if not self.ref_set and self.op <= tod < self.deb:
            self.open_ref, self.ref_set = e.o[i], True
        if tod < self.fin <= tod + self.bar_span:
            if e.pos != 0:
                self.go_flat("fin-fenetre")
            return
        if tod >= self.fin and e.pos != 0:
            self.go_flat("hors-fenetre")
            return
        if self.done or not (tod < self.deb <= tod + self.bar_span):
            return
        self.done = True
        if not self.ref_set or not ok(self.open_ref) or self.open_ref <= 0:
            return
        r = e.c[i] / self.open_ref - 1.0
        if abs(r) * 100 < p.seuil_min_rday_pct or not self.vol_filter_passes():
            return
        d = int(np.sign(r))
        if d == 0:
            return
        if p.sizing_amplitude:
            ratio = abs(r) * 100 / max(0.01, p.amplitude_ref_pct)
            q = int(min(max(int(math.floor(p.base_qty * min(max(ratio, 0.25), 4.0) + 0.5)), 1), p.max_qty))
        else:
            q = self.compute_size(abs(r))
        stop = e.c[i] - d * p.stop_atr_mult * self.atr_pts if p.stop_atr_mult > 0 else NAN
        self.enter(d, q, "S19", stop=stop)


# =============================================================================
#  S20 - Risk parity multi-futures (simulation journaliere multi-jambes)
# =============================================================================
def erc_weights(cov: np.ndarray, budgets: np.ndarray, iters: int = 500, tol: float = 1e-10) -> np.ndarray:
    """Contributions au risque egales (ou proportionnelles aux budgets) : algorithme de point fixe (Spinu / cyclique)."""
    b = budgets / budgets.sum()
    w = 1.0 / np.sqrt(np.diag(cov))
    w /= w.sum()
    for _ in range(iters):
        sig = cov @ w
        vol = math.sqrt(max(w @ sig, 1e-18))
        rc = w * sig / vol
        w_new = w * (b * vol / np.maximum(rc, 1e-18)) ** 0.5
        w_new /= w_new.sum()
        if np.max(np.abs(w_new - w)) < tol:
            w = w_new
            break
        w = w_new
    return w


def run_s20(daily: dict, insts: dict, variante="A", capital=100000.0, fenetre=120, min_obs=60, levier=1.0, poids_max=0.60,
            contrats_max=20, slippage_ticks=1):
    """daily : {jambe: DataFrame journalier open/close} ; insts : {jambe: Inst}. Ordres au jour suivant (ouverture)."""
    legs = list(daily)
    df = pd.concat({k: daily[k][["open", "close"]] for k in legs}, axis=1).dropna()
    opens = df.xs("open", axis=1, level=1)[legs].to_numpy()
    closes = df.xs("close", axis=1, level=1)[legs].to_numpy()
    rets = np.log(closes[1:] / closes[:-1])
    pos = np.zeros(len(legs))
    cash = capital
    eq, trades, last_month, nreb = [], 0, None, 0
    pending = None
    pv = np.array([insts[k].point_value for k in legs])
    tick = np.array([insts[k].tick for k in legs])
    com = np.array([insts[k].commission for k in legs])
    avg = np.zeros(len(legs))
    pnl_trades = []
    for t in range(len(df)):
        if pending is not None:
            delta = pending - pos
            for j in np.nonzero(delta)[0]:
                px = opens[t, j] + np.sign(delta[j]) * slippage_ticks * tick[j]
                cash -= com[j] * abs(delta[j])
                # P&L realise sur la partie reduite
                if pos[j] != 0 and (np.sign(pending[j]) != np.sign(pos[j]) or abs(pending[j]) < abs(pos[j])):
                    q = abs(pos[j]) if np.sign(pending[j]) != np.sign(pos[j]) else abs(pos[j]) - abs(pending[j])
                    pnl_trades.append(np.sign(pos[j]) * (px - avg[j]) * q * pv[j] - com[j] * q)
                cash += -(delta[j]) * px * pv[j]
                if pending[j] != 0 and (pos[j] == 0 or np.sign(pending[j]) != np.sign(pos[j])):
                    avg[j] = px
                trades += 1
            pos = pending.copy()
            pending = None
        eq.append(cash + (pos * closes[t] * pv).sum())
        if t < min_obs:
            continue
        d = df.index[t]
        if last_month is not None and (d.year, d.month) == last_month:
            continue
        window = rets[max(0, t - fenetre):t]
        if len(window) < min_obs:
            continue
        cov = np.cov(window, rowvar=False)
        cov[np.diag_indices_from(cov)] = np.maximum(np.diag(cov), 1e-10)
        budgets = np.ones(len(legs))
        if variante == "B":
            w = budgets / np.sqrt(np.diag(cov))
            w /= w.sum()
        elif variante == "EW":                       # reference naive : meme notionnel par jambe (1/N)
            w = budgets / budgets.sum()
        else:
            w = erc_weights(cov, budgets)
        w = np.clip(w, 0, poids_max)
        w /= w.sum()
        target = np.clip(np.floor(w * capital * levier / (closes[t] * pv) + 0.5), 0, contrats_max)
        pending = target.astype(float)
        last_month = (d.year, d.month)
        nreb += 1
    eq = pd.Series(eq, index=df.index)
    return eq, trades, nreb, pnl_trades
