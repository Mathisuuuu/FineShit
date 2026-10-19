"""Strategies NinjaScript personnelles (hors suite S) portees en Python.

    IntradayMomentumMES   (MyCustomStrategy1.cs)   bande VWAP +/- moyenne |C-O| 60 barres, trailing ATR, MES
    Test / OPR            (MyCustomStrategy2.cs)   cassure de la 1re barre de seance (tel que code + corrige)
    ZarattiniSPYMomentum  (MyCustomStrategy3.cs)   "Beat the Market" (Zarattini et al.) sur SPY minute
    ICT2022Model          (MyCustomStrategy4.cs)   sweep / FVG 1H-4H, killzone NY, MSS + FVG 1 min, entree limite
    ZarattiniEnvelope     (ZarattiniEnvelope.cs)   enveloppe de bruit, controles toutes les 30 min, taille vol-cible
    IntradayMomentumGamma (IntradayMomentumC01.cs) Noise Area + VWAP (filtre gamma desactive par defaut, comme le code)
    boombitch             (boombitch.cs)           Turtle Donchian 160/60, ATR(80), M15, long seulement
    AUDusd                (AUDusd.cs)              paires : z-score du spread suiveur - beta x meneur, 15 min
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd

from .qf import NAN, Engine, ok, wilder_atr


def last_of_session(sess: np.ndarray) -> np.ndarray:
    out = np.zeros(len(sess), bool)
    if len(sess):
        out[:-1] = sess[1:] != sess[:-1]
        out[-1] = True
    return out


def rth_only(df: pd.DataFrame, start=930, end=1600) -> pd.DataFrame:
    """Barres du modele d horaires US RTH (fin de barre dans ]09:30 ; 16:00] ET)."""
    et = pd.DatetimeIndex(df.index).tz_localize("UTC").tz_convert("America/New_York")
    m = et.hour * 60 + et.minute
    return df[(m > (start // 100) * 60 + start % 100) & (m <= (end // 100) * 60 + end % 100) & (et.dayofweek < 5)]


class UserBase:
    NAME = "?"
    DEFAULTS: dict = {}

    def __init__(self, e: Engine, **kw):
        p = {}
        for cls in reversed(type(self).__mro__):
            p.update(cls.__dict__.get("DEFAULTS", {}) or {})
        bad = [k for k in kw if k not in p]
        if bad:
            raise ValueError(f"{self.NAME} : parametres inconnus {bad}")
        p.update(kw)
        self.p = type("P", (), p)
        self.e = e
        self.init()

    def init(self):
        pass


# =============================================================================
#  MyCustomStrategy1 - IntradayMomentumMES
# =============================================================================
class IntradayMomentumMES(UserBase):
    NAME = "IntradayMomentumMES (MyCustomStrategy1)"
    DEFAULTS = dict(flat_before_close_min=5, band_multiplier=1.0, sigma_lookback=60, atr_period=14, atr_trail_mult=3.0,
                    contracts=1, one_trade_per_direction=True, bars_required=20)

    def init(self):
        e = self.e
        self.atr = wilder_atr(e.h, e.l, e.c, self.p.atr_period)
        self.sess = e.date                       # ancrage CashOpen : jour calendaire ET
        self.last_sess = last_of_session(e.tday)  # fin de seance CME (17:00 ET) : IsExitOnSessionCloseStrategy
        self.cur = None
        self.moves = []
        self.cum_tv = self.cum_v = 0.0
        self.took_l = self.took_s = False
        self.trail = 0.0

    def __call__(self, i):
        e, p = self.e, self.p
        if i >= p.bars_required:
            self._bar(i)
        if self.last_sess[i] and e.pos != 0:
            e.flatten_now(i)

    def _bar(self, i):
        e, p = self.e, self.p
        if self.sess[i] != self.cur:
            self.cur = self.sess[i]
            self.cum_tv = self.cum_v = 0.0
            self.moves = []
            self.took_l = self.took_s = False
            self.trail = 0.0
        typ = (e.h[i] + e.l[i] + e.c[i]) / 3.0
        vol = e.v[i] if e.v[i] > 0 else 1.0
        self.cum_tv += typ * vol
        self.cum_v += vol
        vwap = self.cum_tv / self.cum_v
        self.moves.append(abs(e.c[i] - e.o[i]))
        if len(self.moves) > p.sigma_lookback:
            del self.moves[0]
        sig = sum(self.moves) / len(self.moves)
        up, lo = vwap + p.band_multiplier * sig, vwap - p.band_multiplier * sig
        tod = e.tod[i]
        if 960 - p.flat_before_close_min <= tod < 960:
            if e.pos != 0:
                e.market(0, reason="EOD_flat")
            return
        if not (570 <= tod < 960):
            return
        a = self.atr[i]
        if e.pos > 0:
            self.trail = max(self.trail, e.c[i] - p.atr_trail_mult * a)
            if e.l[i] <= self.trail or e.c[i] < vwap:
                e.market(0, reason="TrailExitL")
            return
        if e.pos < 0:
            cand = e.c[i] + p.atr_trail_mult * a
            self.trail = cand if self.trail == 0 else min(self.trail, cand)
            if e.h[i] >= self.trail or e.c[i] > vwap:
                e.market(0, reason="TrailExitS")
            return
        if e.order is not None:
            return
        can_l = not (p.one_trade_per_direction and self.took_l)
        can_s = not (p.one_trade_per_direction and self.took_s)
        if can_l and e.c[i] > up:
            e.market(p.contracts, "LongMomo")
            self.took_l, self.trail = True, e.c[i] - p.atr_trail_mult * a
        elif can_s and e.c[i] < lo:
            e.market(-p.contracts, "ShortMomo")
            self.took_s, self.trail = True, e.c[i] + p.atr_trail_mult * a


# =============================================================================
#  MyCustomStrategy2 - "Test" (cassure de la premiere barre de seance)
# =============================================================================
class OprTest(UserBase):
    NAME = "Test OPR (MyCustomStrategy2)"
    DEFAULTS = dict(corrige=False, bars_required=20)

    def init(self):
        e = self.e
        self.sess = e.date
        self.last_sess = last_of_session(self.sess)
        self.opr_hi = self.opr_lo = 0.0
        self.trades = 0
        self.stop_px = 0.0

    def __call__(self, i):
        e, p = self.e, self.p
        first = i == 0 or self.sess[i] != self.sess[i - 1]
        if first:
            self.opr_hi, self.opr_lo, self.trades = e.h[i], e.l[i], 0
        if i >= p.bars_required and i >= 1 and e.pos == 0 and e.order is None and self.trades < 1:
            if e.h[i] > self.opr_hi and e.h[i - 1] < self.opr_hi:
                self.stop_px = self.opr_lo
                tgt = NAN
                if p.corrige:
                    tgt = e.c[i] + 2 * (e.c[i] - self.stop_px)            # 2R (calcule sur le prix moyen apres remplissage en C#)
                e.market(1, "OPR long", stop=self.stop_px if p.corrige else NAN, target=tgt)
                self.trades += 1
            elif e.l[i] < self.opr_lo and e.l[i - 1] > self.opr_lo:
                self.stop_px = self.opr_hi
                if p.corrige:
                    tgt = e.c[i] - 2 * (self.stop_px - e.c[i])
                    e.market(-1, "OPR short", stop=self.stop_px, target=tgt)
                else:
                    e.market(1, "OPR long (bug : achat sur cassure basse)")
                self.trades += 1
        if p.corrige and e.pos != 0 and ok(e.stop):
            # objectif = prix moyen + 2 x (prix moyen - stop), comme ExitLongLimit / ExitShortLimit du C#
            e.target = e.round_tick(e.avg + 2 * (e.avg - self.stop_px))
        if self.last_sess[i] and e.pos != 0:
            e.flatten_now(i)


# =============================================================================
#  MyCustomStrategy3 - ZarattiniSPYMomentum
# =============================================================================
class ZarattiniSPY(UserBase):
    NAME = "ZarattiniSPYMomentum (MyCustomStrategy3)"
    DEFAULTS = dict(lookback_days=14, notional=100000.0)

    def init(self):
        self.cur = None
        self.hist = []
        self.day_moves = np.zeros(391)
        self.open = self.prev_close = 0.0
        self.cum_v = self.cum_tv = 0.0
        self.last_sess = last_of_session(self.e.date)

    def __call__(self, i):
        e = self.e
        self._bar(i)
        if self.last_sess[i] and e.pos != 0:
            e.flatten_now(i)

    def _bar(self, i):
        e, p = self.e, self.p
        if i < p.lookback_days * 390:
            return
        tod = e.tod[i]
        t = int(tod // 60) * 100 + int(tod % 60)
        if t < 930 or t > 1600:
            return
        if e.date[i] != self.cur:
            if self.cur is not None:
                self.hist.append(self.day_moves.copy())
                if len(self.hist) > p.lookback_days:
                    del self.hist[0]
            self.cur = e.date[i]
            self.day_moves[:] = 0.0
            self.open = e.o[i]
            self.cum_v = self.cum_tv = 0.0
            if self.prev_close == 0:
                self.prev_close = e.o[i]
        k = min(max(int((tod // 60 - 9) * 60 + tod % 60 - 30), 0), 390)
        self.cum_v += e.v[i]
        self.cum_tv += (e.h[i] + e.l[i] + e.c[i]) / 3.0 * e.v[i]
        vwap = self.cum_tv / self.cum_v if self.cum_v > 0 else e.c[i]
        if self.open > 0:
            self.day_moves[k] = abs(e.c[i] / self.open - 1.0)
        if t == 1600:
            self.prev_close = e.c[i]
        if len(self.hist) < p.lookback_days:
            return
        sigma = sum(h[k] for h in self.hist) / len(self.hist)
        up = max(self.open, self.prev_close) * (1 + sigma)
        lo = min(self.open, self.prev_close) * (1 - sigma)
        if t >= 1555:
            if e.pos != 0:
                e.market(0, reason="EOD Exit")
            return
        if e.pos == 0:
            if e.order is not None:
                return
            q = max(1, int(p.notional / e.c[i]))
            if e.c[i] > up:
                e.market(q, "Long Entry")
            elif e.c[i] < lo:
                e.market(-q, "Short Entry")
        elif e.pos > 0 and e.c[i] <= max(up, vwap):
            e.market(0, reason="Trailing Stop")
        elif e.pos < 0 and e.c[i] >= min(lo, vwap):
            e.market(0, reason="Trailing Stop")


# =============================================================================
#  ZarattiniEnvelope
# =============================================================================
class ZarattiniEnvelope(UserBase):
    NAME = "ZarattiniEnvelope"
    DEFAULTS = dict(seances_calibration=60, pas_controles=30, multiplicateur_largeur=1.5, derniere_minute_entree=385,
                    cible_volatilite=0.02, multiplicateur_max=4.0, contrats_base=1, bars_required=20)

    def init(self):
        self.hist = []
        self.closes = []
        self.cur_moves = np.full(390, np.nan)
        self.sigma = None
        self.day = None
        self.open = self.prev_close = self.last_close = 0.0
        self.cum_pv = self.cum_v = 0.0
        self.size = 0
        self.tradable = False
        self.last_sess = last_of_session(self.e.date)

    def _sigma(self):
        p = self.p
        if len(self.hist) < p.seances_calibration:
            return None
        h = np.vstack(self.hist)
        n = np.sum(~np.isnan(h), axis=0)
        s = np.nansum(h, axis=0) / np.maximum(n, 1)
        s[n < p.seances_calibration] = np.nan
        return s

    def _size(self):
        p = self.p
        if len(self.closes) < p.seances_calibration + 1:
            return 0
        r = np.diff(np.log(np.asarray(self.closes)))
        sd = r.std(ddof=1)
        if sd <= 0:
            return 0
        return max(1, int(round(min(p.multiplicateur_max, p.cible_volatilite / sd) * p.contrats_base)))

    def __call__(self, i):
        e, p = self.e, self.p
        if i >= p.bars_required:
            self._bar(i)
        if self.last_sess[i] and e.pos != 0:
            e.flatten_now(i)

    def _bar(self, i):
        e, p = self.e, self.p
        m = int(e.tod[i]) - 570 - 1
        if not (0 <= m < 390):
            return
        if e.date[i] != self.day:
            if self.day is not None:
                self.hist.append(self.cur_moves)
                if len(self.hist) > p.seances_calibration:
                    del self.hist[0]
                self.closes.append(self.last_close)
                if len(self.closes) > p.seances_calibration + 1:
                    del self.closes[0]
            self.day = e.date[i]
            self.open = e.o[i]
            self.prev_close = self.last_close if self.last_close > 0 else e.o[i]
            self.cum_pv = self.cum_v = 0.0
            self.cur_moves = np.full(390, np.nan)
            self.sigma = self._sigma()
            self.size = self._size()
            self.tradable = self.sigma is not None and self.size > 0
        self.last_close = e.c[i]
        self.cum_pv += (e.h[i] + e.l[i] + e.c[i]) / 3.0 * e.v[i]
        self.cum_v += e.v[i]
        vwap = self.cum_pv / self.cum_v if self.cum_v > 0 else e.c[i]
        if self.open > 0:
            self.cur_moves[m] = abs(e.c[i] / self.open - 1.0)
        if m >= 389 or self.last_sess[i]:
            if e.pos != 0:
                e.flatten_now(i, "cloture")
            return
        if not self.tradable or not ok(self.sigma[m]):
            return
        hi = max(self.open, self.prev_close) * (1.0 + p.multiplicateur_largeur * self.sigma[m])
        lo = min(self.open, self.prev_close) * (1.0 - p.multiplicateur_largeur * self.sigma[m])
        if e.pos > 0:
            if e.c[i] < max(lo, vwap):
                e.market(0, reason="stop")
                return
        elif e.pos < 0:
            if e.c[i] > min(hi, vwap):
                e.market(0, reason="stop")
                return
        if e.pos != 0 or m % p.pas_controles != 0 or m == 0 or m >= p.derniere_minute_entree or e.order is not None:
            return
        if e.c[i] > hi and e.c[i] > vwap:
            e.market(self.size, "Rupture haute")
        elif e.c[i] < lo and e.c[i] < vwap:
            e.market(-self.size, "Rupture basse")


# =============================================================================
#  IntradayMomentumC01 - IntradayMomentumGamma (filtre gamma desactive par defaut)
# =============================================================================
class IntradayMomentumGamma(UserBase):
    NAME = "IntradayMomentumGamma (IntradayMomentumC01)"
    DEFAULTS = dict(lookback_days=14, min_observations=8, sigma_multiplier=1.0, first_entry=1000, last_entry=1530,
                    max_trades_per_day=3, use_vwap_confirmation=True, equity_usd=100000.0, target_daily_vol_pct=2.0,
                    vol_lookback_days=20, max_contracts=10, min_contracts=1, use_fixed_size=False, fixed_size=1, bars_required=20)

    def init(self):
        self.sess = self.e.date
        self.last_sess = last_of_session(self.sess)
        self.rel: dict = {}
        self.closes = []
        self.init_ok = False
        self.s_open = self.prev_close = 0.0
        self.cum_tv = self.cum_v = 0.0
        self.trades = 0

    def _qty(self, i):
        p, e = self.p, self.e
        if p.use_fixed_size:
            return p.fixed_size
        if len(self.closes) < 5:
            return p.min_contracts
        n = min(p.vol_lookback_days, len(self.closes) - 1)
        c = np.asarray(self.closes[-(n + 1):])
        r = c[1:] / c[:-1] - 1
        if r.size < 3:
            return p.min_contracts
        dv = r.std(ddof=1)
        notional = e.c[i] * e.inst.point_value
        if dv <= 0 or notional <= 0:
            return p.min_contracts
        q = int(math.floor(p.equity_usd * p.target_daily_vol_pct / 100.0 / (dv * notional) + 0.5))
        return int(min(max(q, p.min_contracts), p.max_contracts))

    def __call__(self, i):
        e, p = self.e, self.p
        if i >= p.bars_required:
            self._bar(i)
        if self.last_sess[i] and e.pos != 0:
            e.flatten_now(i)

    def _bar(self, i):
        e, p = self.e, self.p
        if i == 0 or self.sess[i] != self.sess[i - 1]:
            self.prev_close = e.c[i - 1] if i > 0 else e.c[i]
            if i > 0:
                self.closes.append(e.c[i - 1])
                if len(self.closes) > p.vol_lookback_days + 5:
                    del self.closes[0]
            self.s_open, self.cum_tv, self.cum_v, self.trades, self.init_ok = e.o[i], 0.0, 0.0, 0, True
        if not self.init_ok:
            return
        vol = e.v[i] if e.v[i] > 0 else 1.0
        self.cum_tv += (e.h[i] + e.l[i] + e.c[i]) / 3.0 * vol
        self.cum_v += vol
        vwap = self.cum_tv / self.cum_v
        key = int(e.tod[i])
        hist = self.rel.get(key)
        sigma = NAN
        if hist is not None and len(hist) >= p.min_observations:
            n = min(p.lookback_days, len(hist))
            sigma = sum(hist[-n:]) / n
        self.rel.setdefault(key, []).append(abs(e.c[i] / self.s_open - 1.0))
        if len(self.rel[key]) > p.lookback_days + 10:
            del self.rel[key][0]
        if not ok(sigma) or sigma <= 0:
            return
        sigma *= p.sigma_multiplier
        up = max(self.s_open, self.prev_close) * (1 + sigma)
        lo = min(self.s_open, self.prev_close) * (1 - sigma)
        hhmm_ = int(e.tod[i] // 60) * 100 + int(e.tod[i] % 60)
        if e.pos > 0:
            if e.c[i] < (max(lo, vwap) if p.use_vwap_confirmation else lo):
                e.market(0, reason="IM_Exit_L")
                return
        elif e.pos < 0:
            if e.c[i] > (min(up, vwap) if p.use_vwap_confirmation else up):
                e.market(0, reason="IM_Exit_S")
                return
        if e.pos != 0 or e.order is not None:
            return
        if hhmm_ < p.first_entry or hhmm_ > p.last_entry or self.trades >= p.max_trades_per_day:
            return
        lb = e.c[i] > up and (not p.use_vwap_confirmation or e.c[i] > vwap)
        sb = e.c[i] < lo and (not p.use_vwap_confirmation or e.c[i] < vwap)
        if not lb and not sb:
            return
        q = self._qty(i)
        e.market(q if lb else -q, "IM_Long" if lb else "IM_Short")
        self.trades += 1


# =============================================================================
#  boombitch - Turtle Donchian (Wong Zhen Hao 2026)
# =============================================================================
class Boombitch(UserBase):
    NAME = "boombitch (Turtle Donchian)"
    DEFAULTS = dict(entry_donchian=160, exit_donchian=60, atr_period=80, atr_stop_mult=1.5, atr_trail_mult=2.0,
                    spread_to_atr_filter=0.20, risk_mode="fixed", fixed_risk=10.0, dynamic_risk_pct=1.75, starting_capital=1000.0,
                    backtest_spread=0.0, allow_min_one=True)

    def init(self):
        e, p = self.e, self.p
        self.atr = wilder_atr(e.h, e.l, e.c, p.atr_period)
        h, l = pd.Series(e.h), pd.Series(e.l)
        self.upper = h.rolling(p.entry_donchian).max().shift(1).to_numpy()
        self.lower = l.rolling(p.exit_donchian).min().shift(1).to_numpy()
        self.prev_pos = 0
        self.stop_level = NAN
        self.need = max(p.entry_donchian, p.exit_donchian, p.atr_period) + 1

    def _qty(self, a):
        p, e = self.p, self.e
        dist = p.atr_stop_mult * a
        if dist <= 0:
            return 0
        bal = p.starting_capital + sum(t.pnl for t in e.trades)
        risk = p.fixed_risk if p.risk_mode == "fixed" else bal * p.dynamic_risk_pct / 100.0
        q = int(math.floor(risk / (dist * e.inst.point_value)))
        return 1 if q < 1 and p.allow_min_one else q

    def __call__(self, i):
        e, p = self.e, self.p
        if i < self.need:
            return
        a = self.atr[i]
        if a <= 0:
            return
        up, lo = self.upper[i], self.lower[i]
        if e.pos > 0 and self.prev_pos <= 0:
            self.stop_level = e.avg - p.atr_stop_mult * a
        if e.pos == 0:
            if p.backtest_spread <= p.spread_to_atr_filter * a:
                q = self._qty(a)
                if q >= 1:
                    if e.c[i] < up:
                        e.stop_market(q, up, "TurtleEntry", valid_bars=1)
                    else:
                        e.market(q, "TurtleEntry")
        elif e.pos > 0:
            self.stop_level = max(self.stop_level, e.c[i] - p.atr_trail_mult * a)
            eff = max(self.stop_level, lo)
            if eff >= e.c[i]:
                eff = e.c[i] - e.inst.tick
            e.stop = e.round_tick(eff)
        self.prev_pos = e.pos


class DonchianAlt(Boombitch):
    """boombitch + options : cassures a la baisse (short=True), filtre de tendance (cloture de la veille au-dessus /
    au-dessous de la moyenne de sma_jours seances). Avec les reglages par defaut : identique a Boombitch."""
    NAME = "Donchian (boombitch generalise)"
    DEFAULTS = dict(short=False, sma_jours=0)

    def init(self):
        super().init()
        e, p = self.e, self.p
        h, l = pd.Series(e.h), pd.Series(e.l)
        self.lower_e = l.rolling(p.entry_donchian).min().shift(1).to_numpy()
        self.upper_x = h.rolling(p.exit_donchian).max().shift(1).to_numpy()
        self.up_ok = self.dn_ok = np.ones(e.n, bool)
        if p.sma_jours:
            cl = pd.Series(e.c).groupby(e.tday).last()
            prev = cl.shift(1)
            sma = cl.rolling(p.sma_jours).mean().shift(1)
            self.up_ok = (prev > sma).reindex(e.tday).to_numpy(bool)
            self.dn_ok = (prev < sma).reindex(e.tday).to_numpy(bool)

    def __call__(self, i):
        e, p = self.e, self.p
        if i < self.need:
            return
        a = self.atr[i]
        if a <= 0:
            return
        if e.pos > 0 and self.prev_pos <= 0:
            self.stop_level = e.avg - p.atr_stop_mult * a
        if e.pos < 0 and self.prev_pos >= 0:
            self.stop_level = e.avg + p.atr_stop_mult * a
        if e.pos == 0:
            q = self._qty(a)
            if q >= 1:
                up, lo = self.upper[i], self.lower_e[i]
                long_ok = bool(self.up_ok[i])
                short_ok = p.short and bool(self.dn_ok[i]) and np.isfinite(lo)
                # un seul ordre en attente dans le moteur : on arme la cassure la plus proche du prix
                if long_ok and (not short_ok or up - e.c[i] <= e.c[i] - lo):
                    e.stop_market(q, up, "TurtleEntry", valid_bars=1) if e.c[i] < up else e.market(q, "TurtleEntry")
                elif short_ok:
                    e.stop_market(-q, lo, "TurtleShort", valid_bars=1) if e.c[i] > lo else e.market(-q, "TurtleShort")
        elif e.pos > 0:
            self.stop_level = max(self.stop_level, e.c[i] - p.atr_trail_mult * a)
            eff = max(self.stop_level, self.lower[i])
            if eff >= e.c[i]:
                eff = e.c[i] - e.inst.tick
            e.stop = e.round_tick(eff)
        else:
            self.stop_level = min(self.stop_level, e.c[i] + p.atr_trail_mult * a)
            eff = min(self.stop_level, self.upper_x[i])
            if eff <= e.c[i]:
                eff = e.c[i] + e.inst.tick
            e.stop = e.round_tick(eff)
        self.prev_pos = e.pos


# =============================================================================
#  AUDusd - paires (z-score du spread suiveur - beta x meneur)
# =============================================================================
class AUDusd(UserBase):
    NAME = "AUDusd (paires lead-lag)"
    DEFAULTS = dict(beta_lookback=100, zscore_lookback=100, entry_z=2.0, exit_z=0.5, stop_z=3.5, use_rolling_beta=True,
                    fixed_beta=1.0, quantity=1)

    def init(self):
        self.leader = None                        # tableau des clotures du meneur alignees (fourni par le lanceur)
        self.spread = np.zeros(self.e.n)
        self.last_sess = last_of_session(self.e.tday)
        self.warm = max(self.p.beta_lookback, self.p.zscore_lookback)

    def __call__(self, i):
        e, p = self.e, self.p
        x = self.leader
        if x is not None and i >= self.warm and ok(x[i]):
            n = p.beta_lookback
            if p.use_rolling_beta:
                xs, ys = x[i - n + 1:i + 1], e.c[i - n + 1:i + 1]
                den = n * (xs * xs).sum() - xs.sum() ** 2
                beta = (n * (xs * ys).sum() - xs.sum() * ys.sum()) / den if abs(den) > 1e-12 else p.fixed_beta
            else:
                beta = p.fixed_beta
            self.spread[i] = e.c[i] - beta * x[i]
            w = self.spread[i - p.zscore_lookback + 1:i + 1]
            mean, sd = w.mean(), w.std()
            if sd > 1e-12:
                z = (self.spread[i] - mean) / sd
                if e.pos > 0 and (z >= -p.exit_z or z <= -p.stop_z):
                    e.market(0, reason="xLong")
                elif e.pos < 0 and (z <= p.exit_z or z >= p.stop_z):
                    e.market(0, reason="xShort")
                if e.pos == 0 and e.order is None:
                    if -p.stop_z < z <= -p.entry_z:
                        e.market(p.quantity, "longSpread")
                    elif p.entry_z <= z < p.stop_z:
                        e.market(-p.quantity, "shortSpread")
        if self.last_sess[i] and e.pos != 0:
            e.flatten_now(i)
