"""MyCustomStrategy4.cs - ICT 2022 Model : contexte HTF (sweep / FVG 1H-4H), killzone NY, MSS + FVG 1 min, entree limite."""
from __future__ import annotations

import numpy as np
import pandas as pd

from .qf import NAN, Engine, ok, wilder_atr
from .user import UserBase, last_of_session


def htf_bars(e: Engine, minutes: int):
    """Barres 60 / 240 min alignees sur la seance CME (18:00 ET), construites depuis les barres 1 min.
    -> (h, l, heure de fin ET, indice de la barre 1 min qui cloture la barre HTF)."""
    df = pd.DataFrame({"h": e.h, "l": e.l, "k": np.arange(e.n)}, index=e.et)
    r = df.resample(f"{minutes}min", label="right", closed="right", origin="epoch",
                    offset=pd.Timedelta(hours=2) if minutes == 240 else pd.Timedelta(0))
    out = pd.DataFrame({"h": r["h"].max(), "l": r["l"].min(), "k": r["k"].last()}).dropna()
    return out["h"].to_numpy(), out["l"].to_numpy(), out.index.to_numpy(), out["k"].to_numpy().astype(np.int64)


class ICT2022(UserBase):
    NAME = "ICT2022Model (MyCustomStrategy4)"
    DEFAULTS = dict(use_h1=True, use_h4=True, use_sweep=True, use_htf_fvg=True, htf_swing_strength=2, htf_min_fvg_ticks=4,
                    htf_max_age_days=10, kz_start=830, kz_end=1100, flatten_time=1555, swing_strength_1m=2, context_expiry=60,
                    min_fvg_ticks_1m=2, displacement_atr_mult=1.0, quantity=1, trade_long=True, trade_short=True, entry_at_ce=False,
                    stop_offset_ticks=2, min_rr=2.0, use_fallback=True, fallback_rr=3.0, target_lookback=120, limit_expiry=20,
                    cancel_at_kz_end=True, max_trades_per_day=2, bars_required=20)

    def init(self):
        e, p = self.e, self.p
        self.atr = wilder_atr(e.h, e.l, e.c, 14)
        self.tick = e.inst.tick
        self.htf = {}
        self.htf_at = {}
        for s, m in ((1, 60), (2, 240)):
            if (s == 1 and p.use_h1) or (s == 2 and p.use_h4):
                h, l, t, k = htf_bars(e, m)
                self.htf[s] = (h, l, t)
                for j, kk in enumerate(k):
                    self.htf_at.setdefault(int(kk), []).append((s, j))
        self.et64 = e.et.to_numpy()
        self.fvgs, self.sw_hi, self.sw_lo = [], [], []
        self.last_sh = self.last_sl = NAN
        self.last_sh_bar = self.last_sl_bar = -1
        self.bull = self.bear = False
        self.day = None
        self.trades_today = 0
        self.entry_bar = 0
        self.pending_long = True
        self.pending_target = NAN
        self.prev_pos = 0
        self.last_sess = last_of_session(e.tday)
        self.max_age = np.timedelta64(int(p.htf_max_age_days * 86400), "s")
        self.stats = dict(contextes=0, mss=0, sans_fvg=0, ordres=0, remplis=0)

    def _round(self, px):
        return round(px / self.tick) * self.tick

    # --- contexte HTF ----------------------------------------------------------
    def _process_htf(self, s, j):
        p = self.p
        h, l, t = self.htf[s]
        n = p.htf_swing_strength
        if j < max(2, 2 * n):
            return
        if l[j] > h[j - 2] and l[j] - h[j - 2] >= p.htf_min_fvg_ticks * self.tick:
            self._add_zone([l[j], h[j - 2], True, t[j]])
        if h[j] < l[j - 2] and l[j - 2] - h[j] >= p.htf_min_fvg_ticks * self.tick:
            self._add_zone([l[j - 2], h[j], False, t[j]])
        c = j - n
        if all(h[c] > h[c - i] and h[c] >= h[c + i] for i in range(1, n + 1)):
            self.sw_hi.append((h[c], t[c]))
            if len(self.sw_hi) > 40:
                del self.sw_hi[0]
        if all(l[c] < l[c - i] and l[c] <= l[c + i] for i in range(1, n + 1)):
            self.sw_lo.append((l[c], t[c]))
            if len(self.sw_lo) > 40:
                del self.sw_lo[0]

    def _add_zone(self, z):
        self.fvgs.append(z)
        if len(self.fvgs) > 40:
            del self.fvgs[0]

    def _scan(self, i):
        e = self.e
        now = self.et64[i]
        bs = be = bt = st = False
        for k in range(len(self.sw_lo) - 1, -1, -1):
            px, created = self.sw_lo[k]
            if now - created > self.max_age:
                del self.sw_lo[k]
            elif e.l[i] < px:
                bs = True
                del self.sw_lo[k]
        for k in range(len(self.sw_hi) - 1, -1, -1):
            px, created = self.sw_hi[k]
            if now - created > self.max_age:
                del self.sw_hi[k]
            elif e.h[i] > px:
                be = True
                del self.sw_hi[k]
        for k in range(len(self.fvgs) - 1, -1, -1):
            top, bot, bull, created = self.fvgs[k]
            if now - created > self.max_age:
                del self.fvgs[k]
            elif bull:
                if e.c[i] < bot:
                    del self.fvgs[k]
                elif e.l[i] <= top:
                    bt = True
            else:
                if e.c[i] > top:
                    del self.fvgs[k]
                elif e.h[i] >= bot:
                    st = True
        return bs, be, bt, st

    # --- structure 1 min --------------------------------------------------------
    def _swings_1m(self, i):
        e, k = self.e, self.p.swing_strength_1m
        c = i - k
        if c - k < 0:
            return
        if all(e.h[c] > e.h[c - j] and e.h[c] >= e.h[c + j] for j in range(1, k + 1)):
            self.last_sh, self.last_sh_bar = e.h[c], c
        if all(e.l[c] < e.l[c - j] and e.l[c] <= e.l[c + j] for j in range(1, k + 1)):
            self.last_sl, self.last_sl_bar = e.l[c], c

    def _ref_high(self, i):
        e = self.e
        if self.last_sh_bar >= 0 and i - self.last_sh_bar <= self.p.context_expiry and self.last_sh > e.l[i]:
            return self.last_sh
        return float(e.h[max(0, i - 15):i].max())

    def _ref_low(self, i):
        e = self.e
        if self.last_sl_bar >= 0 and i - self.last_sl_bar <= self.p.context_expiry and self.last_sl < e.h[i]:
            return self.last_sl
        return float(e.l[max(0, i - 15):i].min())

    # --- entrees -----------------------------------------------------------------
    def _target(self, i, entry, risk, long):
        p, e = self.p, self.e
        lb = max(0, i - p.target_lookback)
        if long:
            lim = entry + p.min_rr * risk
            cands = [x[0] for x in self.sw_hi] + [z[1] for z in self.fvgs if not z[2]] + [float(e.h[lb:i].max())]
            good = [c for c in cands if c >= lim]
            if good:
                return min(good)
            return entry + p.fallback_rr * risk if p.use_fallback else NAN
        lim = entry - p.min_rr * risk
        cands = [x[0] for x in self.sw_lo] + [z[0] for z in self.fvgs if z[2]] + [float(e.l[lb:i].min())]
        good = [c for c in cands if c <= lim]
        if good:
            return max(good)
        return entry - p.fallback_rr * risk if p.use_fallback else NAN

    def _try_entry(self, i, long):
        e, p = self.e, self.p
        span = i - (self.bull_low_bar if long else self.bear_high_bar)
        if span < 1:
            return
        f = None
        for a in range(0, span):                   # a = barres en arriere (0 = barre courante)
            j0, j1, j2 = i - a, i - a - 1, i - a - 2
            if j2 < 0:
                break
            gap = (e.l[j0] - e.h[j2]) if long else (e.l[j2] - e.h[j0])
            if gap >= p.min_fvg_ticks_1m * self.tick:
                body = abs(e.c[j1] - e.o[j1])
                good_dir = e.c[j1] > e.o[j1] if long else e.c[j1] < e.o[j1]
                if p.displacement_atr_mult <= 0 or (good_dir and body >= p.displacement_atr_mult * self.atr[j1]):
                    f = (e.l[j0], e.h[j2]) if long else (e.l[j2], e.h[j0])
                    break
        if f is None:
            self.stats["sans_fvg"] += 1
            return
        top, bot = f
        if long:
            entry = self._round((top + bot) / 2 if p.entry_at_ce else top)
            stop = self._round(self.bull_low - p.stop_offset_ticks * self.tick)
            risk = entry - stop
        else:
            entry = self._round((top + bot) / 2 if p.entry_at_ce else bot)
            stop = self._round(self.bear_high + p.stop_offset_ticks * self.tick)
            risk = stop - entry
        if risk <= 0:
            return
        tgt = self._target(i, entry, risk, long)
        if not ok(tgt):
            return
        tgt = self._round(tgt)
        e.limit(p.quantity if long else -p.quantity, entry, 1 << 20, "ICT_Long" if long else "ICT_Short", stop=stop, target=tgt)
        self.entry_bar, self.pending_long, self.pending_target = i, long, tgt
        self.stats["ordres"] += 1

    def _manage_pending(self, i, in_kz):
        e, p = self.e, self.p
        if e.order is None or e.order.kind != "limit":
            return
        if (i - self.entry_bar >= p.limit_expiry or (p.cancel_at_kz_end and not in_kz)
                or (self.pending_long and e.h[i] >= self.pending_target)
                or (not self.pending_long and e.l[i] <= self.pending_target)):
            e.cancel()

    def __call__(self, i):
        e, p = self.e, self.p
        if self.prev_pos == 0 and e.pos != 0:
            self.trades_today += 1
            self.stats["remplis"] += 1
        if i >= max(p.bars_required, 2 * p.swing_strength_1m + 3):
            self._bar(i)
        for s, j in self.htf_at.get(i, ()):
            self._process_htf(s, j)
        if self.last_sess[i] and e.pos != 0:
            e.flatten_now(i)
        self.prev_pos = e.pos

    def _bar(self, i):
        e, p = self.e, self.p
        tod = e.tod[i]
        hm = int(tod // 60) * 100 + int(tod % 60)
        if e.date[i] != self.day:
            self.day, self.trades_today = e.date[i], 0
            self.bull = self.bear = False
        self._swings_1m(i)
        bs, be, bt, st = self._scan(i)
        in_kz = p.kz_start < hm <= p.kz_end
        self._manage_pending(i, in_kz)
        if hm >= p.flatten_time:
            if e.pos != 0:
                e.market(0, reason="EOD_Flatten")
            elif e.order is not None:
                e.cancel()
            self.bull = self.bear = False
            return
        if not in_kz or e.pos != 0 or e.order is not None or self.trades_today >= p.max_trades_per_day:
            self.bull = self.bear = False
            return
        if p.trade_long and not self.bull and ((p.use_sweep and bs) or (p.use_htf_fvg and bt)):
            self.bull, self.bull_arm, self.bull_low, self.bull_low_bar = True, i, e.l[i], i
            self.bull_ref = self._ref_high(i)
            self.stats["contextes"] += 1
        if p.trade_short and not self.bear and ((p.use_sweep and be) or (p.use_htf_fvg and st)):
            self.bear, self.bear_arm, self.bear_high, self.bear_high_bar = True, i, e.h[i], i
            self.bear_ref = self._ref_low(i)
            self.stats["contextes"] += 1
        if self.bull:
            if i - self.bull_arm > p.context_expiry:
                self.bull = False
            elif e.l[i] < self.bull_low:
                self.bull_low, self.bull_low_bar, self.bull_ref = e.l[i], i, self._ref_high(i)
            elif i > self.bull_low_bar and e.c[i] > self.bull_ref:
                self.stats["mss"] += 1
                self._try_entry(i, True)
                self.bull = False
        if self.bear and e.order is None:
            if i - self.bear_arm > p.context_expiry:
                self.bear = False
            elif e.h[i] > self.bear_high:
                self.bear_high, self.bear_high_bar, self.bear_ref = e.h[i], i, self._ref_low(i)
            elif i > self.bear_high_bar and e.c[i] < self.bear_ref:
                self.stats["mss"] += 1
                self._try_entry(i, False)
                self.bear = False
