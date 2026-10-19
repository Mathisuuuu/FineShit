"""Moteur intrajournalier des strategies NinjaScript personnelles (dossier NinjaTrader 8/bin/Custom/Strategies).

Reproduit les conventions NinjaTrader utilisees par ces scripts :
  - Calculate = OnBarClose : la decision est prise a la CLOTURE de la barre i, un ordre marche est rempli a
    l OUVERTURE de la barre i+1 (+ glissement en ticks, comme Slippage de NinjaTrader) ;
  - barres horodatees a leur heure de FIN (NinjaTrader), heures converties en ET (America/New_York) ;
  - stops (SetStopLoss) et objectifs (SetProfitTarget) en prix absolu, actifs des la barre de remplissage ;
    stop et objectif touches dans la meme barre -> le stop est retenu (hypothese prudente) ;
  - ordres limites : remplis si le prix traverse la limite (IsFillLimitOnTouch = false), sans glissement ;
  - commission par contrat et par cote ; P&L en dollars (valeur du point du contrat).

QfBase reproduit QuantStrategyBase (QF_Core.cs) : seance RTH 09:30-16:00 ET, r_first30, r_overnight,
VWAP prix-typique, sigma_RV, RV journaliere, ATR(14), CrossedTod, FinalBarBefore, SortieTemporelleAtteinte,
ComputeSize (fixe / vol-target / conviction), filtre directionnel.
"""
from __future__ import annotations

import math
import os
from dataclasses import dataclass

import numpy as np
import pandas as pd

NAN = float("nan")
CACHE = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "..", ".cache"))
QUOTES = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "..", "..", "Cotations"))


def ok(x) -> bool:
    return x is not None and isinstance(x, (int, float, np.floating)) and math.isfinite(x)


# =============================================================================
#  Instruments
# =============================================================================
@dataclass
class Inst:
    name: str
    root: str
    point_value: float          # $ par point
    tick: float
    commission: float           # $ par contrat et par cote


INSTRUMENTS = {
    "ES": Inst("ES", "ES", 50.0, 0.25, 2.5), "MES": Inst("MES", "ES", 5.0, 0.25, 0.6),
    "NQ": Inst("NQ", "NQ", 20.0, 0.25, 2.5), "MNQ": Inst("MNQ", "NQ", 2.0, 0.25, 0.6),
    "YM": Inst("YM", "YM", 5.0, 1.0, 2.5), "MYM": Inst("MYM", "YM", 0.5, 1.0, 0.6),
    "GC": Inst("GC", "GC", 100.0, 0.1, 2.5), "MGC": Inst("MGC", "GC", 10.0, 0.1, 0.6),
    "CL": Inst("CL", "CL", 1000.0, 0.01, 2.5), "MCL": Inst("MCL", "CL", 100.0, 0.01, 0.6),
    "6E": Inst("6E", "6E", 125000.0, 0.00005, 2.5), "M6E": Inst("M6E", "6E", 12500.0, 0.0001, 0.6),
    "6B": Inst("6B", "6B", 62500.0, 0.0001, 2.5), "M6B": Inst("M6B", "6B", 6250.0, 0.0001, 0.6),
    "6J": Inst("6J", "6J", 12500000.0, 0.0000005, 2.5), "MJY": Inst("MJY", "6J", 1250000.0, 0.000001, 0.6),
    "6A": Inst("6A", "6A", 100000.0, 0.00005, 2.5),
    "M6A": Inst("M6A", "6A", 10000.0, 0.0001, 0.6),
    "FDAX": Inst("FDAX", "FDAX", 25.0 * 1.10, 0.5, 2.5), "FDXS": Inst("FDXS", "FDAX", 1.0 * 1.10, 1.0, 0.6),
    "SPY": Inst("SPY", "SPY", 1.0, 0.01, 0.0),
    # IWM (ETF Russell 2000) en substitut du future RTY absent des donnees : 500 parts ~ 1 RTY (50 $ x indice ~ 10 x IWM),
    # tick 0,01 $ x 500 = 5 $ comme le RTY, commission d un future standard ; la version micro (M2K) vaut 1/10.
    "IWM": Inst("IWM", "IWM", 500.0, 0.01, 2.5),
}


# =============================================================================
#  Donnees minute
# =============================================================================
def _futures_file(root: str) -> str | None:
    for dirpath, _, files in os.walk(QUOTES):
        for f in files:
            if f.lower().endswith(".parquet") and f.upper().startswith(root.upper() + "_"):
                return os.path.join(dirpath, f)
    return None


def futures_minutes(root: str, adjust: str = "additif") -> pd.DataFrame:
    """Barres 1 minute d un future continu Databento, ajustees aux roulements (additif = points exacts, comme
    le MergeBackAdjusted de NinjaTrader). Index = heure de FIN de barre, UTC naif. Mise en cache."""
    from .. import futures as F
    path = _futures_file(root)
    if path is None:
        raise FileNotFoundError(f"aucun fichier minute pour {root} dans {QUOTES}")
    st = os.stat(path)
    cp = os.path.join(CACHE, f"min_{root}_{int(st.st_mtime)}_{st.st_size}_{adjust}.parquet")
    if os.path.exists(cp):
        return pd.read_parquet(cp)
    raw = pd.read_parquet(path)
    if raw.index.tz is None:
        raw.index = raw.index.tz_localize("UTC")
    raw = raw.sort_index()
    raw = raw[~raw.index.duplicated(keep="last")]
    rolls = F.detect_rolls(raw, root)
    adj = F.back_adjust(raw[["open", "high", "low", "close", "volume"]], rolls, adjust)
    if adjust == "additif" and float(adj["low"].min()) <= 0:
        # Ajustement additif -> prix negatifs (CL : contango cumule) : rendements impossibles, repli proportionnel.
        adj = F.back_adjust(raw[["open", "high", "low", "close", "volume"]], rolls, "proportionnel")
    adj.index = (adj.index + pd.Timedelta(minutes=1)).tz_convert("UTC").tz_localize(None)    # fin de barre
    os.makedirs(CACHE, exist_ok=True)
    adj.to_parquet(cp)
    return adj


def alpaca_minutes(sym: str) -> pd.DataFrame:
    p = os.path.join(CACHE, "alpaca_minute", f"{sym.upper()}.parquet")
    if not os.path.exists(p):
        raise FileNotFoundError(f"minutes Alpaca absentes pour {sym} ({p})")
    return pd.read_parquet(p)


def resample(df: pd.DataFrame, minutes: int) -> pd.DataFrame:
    """Barres de N minutes horodatees a leur fin (les barres 1 min sont deja horodatees a leur fin)."""
    if minutes <= 1:
        return df
    r = df.resample(f"{int(minutes)}min", label="right", closed="right")
    out = pd.DataFrame({"open": r["open"].first(), "high": r["high"].max(), "low": r["low"].min(),
                        "close": r["close"].last(), "volume": r["volume"].sum()})
    return out.dropna(subset=["close"])


def to_daily_et(df: pd.DataFrame, session: str = "cme") -> pd.DataFrame:
    """Barres journalieres par jour de bourse (CME : 18:00 ET -> 17:00 ET, rattache au lendemain)."""
    et = pd.DatetimeIndex(df.index).tz_localize("UTC").tz_convert("America/New_York").tz_localize(None)
    day = (et + pd.Timedelta(hours=6)).normalize() if session == "cme" else et.normalize()
    g = df.groupby(day)
    out = pd.DataFrame({"open": g["open"].first(), "high": g["high"].max(), "low": g["low"].min(),
                        "close": g["close"].last(), "volume": g["volume"].sum()})
    return out[out.index.dayofweek < 5]


# =============================================================================
#  Moteur
# =============================================================================
@dataclass
class Trade:
    direction: int
    qty: int
    entry_time: object
    entry_price: float
    exit_time: object = None
    exit_price: float = NAN
    pnl: float = 0.0            # net de commission, en $
    reason: str = ""
    tag: str = ""


@dataclass
class Order:
    kind: str                   # market | limit | stopmkt
    target_pos: int             # position visee apres remplissage
    price: float = NAN
    expiry: int = 1 << 30       # indice de barre a partir duquel l ordre limite est annule
    tag: str = ""
    stop: float = NAN           # stop / objectif a armer au remplissage
    target: float = NAN
    reason: str = ""


class Engine:
    def __init__(self, df: pd.DataFrame, inst: Inst, slippage_ticks: int = 1, capital: float = 100000.0,
                 session: str = "cme"):
        self.inst = inst
        self.slip = slippage_ticks * inst.tick
        self.capital = capital
        df = df.dropna(subset=["close"])
        self.index = pd.DatetimeIndex(df.index).as_unit("ns")      # pandas 3 : index parfois en microsecondes
        self.o = df["open"].to_numpy(float)
        self.h = df["high"].to_numpy(float)
        self.l = df["low"].to_numpy(float)
        self.c = df["close"].to_numpy(float)
        self.v = df["volume"].to_numpy(float)
        self.n = len(self.c)
        et = self.index.tz_localize("UTC").tz_convert("America/New_York").tz_localize(None)
        self.et = et
        self.et_ns = et.asi8
        self.tod = (et.hour * 60 + et.minute + et.second / 60.0).to_numpy(float)
        self.date = (self.et_ns // 86_400_000_000_000).astype(np.int64)      # jour calendaire ET
        if session == "cme":
            self.tday = ((self.et_ns + 6 * 3_600_000_000_000) // 86_400_000_000_000).astype(np.int64)
        else:
            self.tday = self.date
        d = np.diff(self.index.asi8)
        self.bar_minutes = float(np.median(d)) / 6e10 if d.size else 1.0
        self.pos = 0
        self.avg = 0.0
        self.order: Order | None = None
        self.stop = NAN
        self.target = NAN
        self.trades: list[Trade] = []
        self.open_trade: Trade | None = None
        self.realized = 0.0
        self.eq_dates: list = []
        self.eq_vals: list = []
        self.i = 0

    # --- ordres ---------------------------------------------------------------
    def market(self, target_pos: int, tag: str = "", stop=NAN, target=NAN, reason=""):
        self.order = Order("market", int(target_pos), tag=tag, stop=stop, target=target, reason=reason)

    def limit(self, target_pos: int, price: float, valid_bars: int, tag="", stop=NAN, target=NAN):
        self.order = Order("limit", int(target_pos), price, self.i + 1 + max(1, valid_bars), tag, stop, target)

    def stop_market(self, target_pos: int, price: float, tag="", stop=NAN, target=NAN, valid_bars: int = 1):
        self.order = Order("stopmkt", int(target_pos), price, self.i + 1 + max(1, valid_bars), tag, stop, target)

    def cancel(self):
        self.order = None

    def flatten_now(self, i: int, reason: str = "fin de seance"):
        """Sortie a la cloture de la barre i (IsExitOnSessionCloseStrategy de NinjaTrader)."""
        self.order = None
        if self.pos != 0:
            px = self.c[i] - self.slip if self.pos > 0 else self.c[i] + self.slip
            self._fill(0, px, i, reason)

    def round_tick(self, px: float) -> float:
        return round(px / self.inst.tick) * self.inst.tick if ok(px) else px

    # --- execution --------------------------------------------------------------
    def _fill(self, new_pos: int, price: float, i: int, reason: str, tag: str = ""):
        if new_pos == self.pos:
            return
        pv, com = self.inst.point_value, self.inst.commission
        t = self.index[i]
        if self.pos != 0 and (new_pos == 0 or np.sign(new_pos) != np.sign(self.pos) or abs(new_pos) < abs(self.pos)):
            close_q = abs(self.pos) if (new_pos == 0 or np.sign(new_pos) != np.sign(self.pos)) else abs(self.pos) - abs(new_pos)
            pnl = np.sign(self.pos) * (price - self.avg) * close_q * pv - com * close_q
            self.realized += pnl
            tr = self.open_trade
            if tr is not None:
                tr.pnl += pnl
                if abs(self.pos) == close_q:
                    tr.exit_time, tr.exit_price, tr.reason = t, price, reason
                    self.trades.append(tr)
                    self.open_trade = None
            self.pos = int(np.sign(self.pos) * (abs(self.pos) - close_q))
            if self.pos == 0:
                self.stop = self.target = NAN
        if new_pos != self.pos:
            add = new_pos - self.pos
            self.realized -= com * abs(add)
            if self.pos == 0:
                self.avg = price
                self.open_trade = Trade(int(np.sign(new_pos)), abs(new_pos), t, price, pnl=-com * abs(add), tag=tag)
            else:
                self.avg = (self.avg * abs(self.pos) + price * abs(add)) / (abs(self.pos) + abs(add))
                if self.open_trade is not None:
                    self.open_trade.qty = abs(new_pos)
                    self.open_trade.pnl -= com * abs(add)
            self.pos = new_pos

    def _process(self, i: int):
        o, h, l = self.o[i], self.h[i], self.l[i]
        held_before = self.pos
        od = self.order
        if od is not None:
            filled = None
            up = od.target_pos > self.pos
            if od.kind == "market":
                filled = o + self.slip if up else o - self.slip
            elif od.kind == "limit":
                if i >= od.expiry:
                    self.order = None
                    od = None
                elif up and o < od.price:
                    filled = o
                elif up and l < od.price:
                    filled = od.price
                elif not up and o > od.price:
                    filled = o
                elif not up and h > od.price:
                    filled = od.price
            elif od.kind == "stopmkt":
                if i >= od.expiry:
                    self.order = None
                    od = None
                elif up and o >= od.price:
                    filled = o + self.slip
                elif up and h >= od.price:
                    filled = od.price + self.slip
                elif not up and o <= od.price:
                    filled = o - self.slip
                elif not up and l <= od.price:
                    filled = od.price - self.slip
            if od is not None and filled is not None:
                self.order = None
                was_flat = self.pos == 0
                self._fill(od.target_pos, filled, i, od.reason or ("entree" if od.target_pos else "sortie"), od.tag)
                if self.pos != 0 and (was_flat or np.sign(self.pos) != np.sign(held_before)):
                    self.stop, self.target = od.stop, od.target
                    held_before = 0
        if self.pos != 0 and (ok(self.stop) or ok(self.target)):
            long = self.pos > 0
            hit_stop = ok(self.stop) and ((l <= self.stop) if long else (h >= self.stop))
            hit_tgt = ok(self.target) and ((h > self.target) if long else (l < self.target))
            if hit_stop:
                px = self.stop
                if held_before != 0 and ((long and o <= self.stop) or (not long and o >= self.stop)):
                    px = o
                self._fill(0, px - self.slip if long else px + self.slip, i, "stop")
            elif hit_tgt:
                px = self.target
                if held_before != 0 and ((long and o >= self.target) or (not long and o <= self.target)):
                    px = o
                self._fill(0, px, i, "objectif")

    def run(self, on_bar, start_index: int = 1):
        n = self.n
        c = self.c
        last_date = None
        for i in range(n):
            self.i = i
            if i >= start_index:
                self._process(i)
                on_bar(i)
            d = self.tday[i]                 # jour de seance (CME : 18:00 ET -> 17:00 ET), comme les regles prop
            eq = self.capital + self.realized + (self.pos * (c[i] - self.avg) * self.inst.point_value if self.pos else 0.0)
            if d != last_date:
                self.eq_dates.append(d)
                self.eq_vals.append(eq)
                last_date = d
            else:
                self.eq_vals[-1] = eq
        if self.pos != 0:
            self._fill(0, c[n - 1], n - 1, "fin des donnees")
            self.eq_vals[-1] = self.capital + self.realized

    def equity(self) -> pd.Series:
        return pd.Series(self.eq_vals, index=pd.to_datetime(np.array(self.eq_dates) * 86_400_000_000_000))


# =============================================================================
#  QuantStrategyBase (QF_Core.cs)
# =============================================================================
class Ring:
    def __init__(self, cap: int):
        self.cap = max(1, cap)
        self.buf: list[float] = []

    def add(self, v):
        if v is None or not math.isfinite(v):
            return
        self.buf.append(v)
        if len(self.buf) > self.cap:
            del self.buf[0]

    def __len__(self):
        return len(self.buf)

    def __getitem__(self, k):            # 0 = plus recent
        return self.buf[-1 - k] if 0 <= k < len(self.buf) else NAN

    @property
    def full(self):
        return len(self.buf) >= self.cap

    def sum(self):
        return float(sum(self.buf))

    def mean(self):
        return float(np.mean(self.buf)) if self.buf else NAN

    def std(self):
        return float(np.std(self.buf, ddof=1)) if len(self.buf) >= 2 else NAN

    def median(self):
        return float(np.median(self.buf)) if self.buf else NAN

    def array(self):
        return np.asarray(self.buf, float)


def wilder_atr(h, l, c, period: int) -> np.ndarray:
    """ATR de NinjaTrader : moyenne croissante sur les premieres barres puis lissage de Wilder."""
    n = len(c)
    tr = np.empty(n)
    if n == 0:
        return tr
    tr[0] = h[0] - l[0]
    tr[1:] = np.maximum(h[1:] - l[1:], np.maximum(np.abs(h[1:] - c[:-1]), np.abs(l[1:] - c[:-1])))
    atr = np.empty(n)
    a = tr[0]
    atr[0] = a
    for i in range(1, n):
        k = min(i + 1, period)
        a = ((k - 1) * a + tr[i]) / k
        atr[i] = a
    return atr


def hhmm(x: int) -> float:
    return (x // 100) * 60 + (x % 100)


class QfBase:
    """Etat de seance et helpers de QuantStrategyBase. Les classes filles definissent on_quant_bar(i)."""
    NAME = "QF"
    DEFAULTS: dict = {}
    BASE = dict(rth_start=930, rth_end=1600, first30_end=1000, base_qty=1, max_qty=10, sizing="fixe", target_vol_pct=15.0,
                direction="long_et_short", rv_lookback_bars=78, atr_period=14, daily_vol_window=60, use_vol_filter=False,
                bars_required=20)

    def __init__(self, engine: Engine, **params):
        p = dict(self.BASE)
        for cls in reversed(type(self).__mro__):
            p.update(cls.__dict__.get("DEFAULTS", {}) or {})
        unknown = [k for k in params if k not in p]
        if unknown:
            raise ValueError(f"{self.NAME} : parametres inconnus {unknown}")
        p.update(params)
        self.p = type("P", (), p)
        self.e = engine
        self.rth_start, self.rth_end = hhmm(self.p.rth_start), hhmm(self.p.rth_end)
        self.first30_end = hhmm(self.p.first30_end)
        self.bar_span = engine.bar_minutes
        self.atr = wilder_atr(engine.h, engine.l, engine.c, self.p.atr_period)
        self.rv_ring = Ring(max(2, self.p.rv_lookback_bars))
        self.bar_ret_ring = Ring(max(2, self.p.rv_lookback_bars))
        self.daily_rv_ring = Ring(max(5, self.p.daily_vol_window))
        self.daily_ret_ring = Ring(max(5, self.p.daily_vol_window * 4))
        self.overnight_ring = Ring(max(5, self.p.daily_vol_window * 4))
        self.rth_open = self.rth_high = self.rth_low = self.last_rth_close = self.prev_rth_close = NAN
        self.first30_close = self.r_first30 = self.r_overnight = self.vwap = NAN
        self.sigma_rv_bar = self.sigma_move = self.sigma_daily = self.sigma_annual = NAN
        self.prev_day_rv = self.daily_rv_median = NAN
        self.has_first30 = self.has_overnight = self.in_rth = False
        self.cum_tpv = self.cum_vol = self.day_rv_accum = 0.0
        self.current_rth_date = None
        self._cross: dict = {}
        self._final: dict = {}
        self.tod = 0.0
        self.sdate = 0
        self.init()

    def init(self):
        pass

    def on_quant_bar(self, i: int):
        raise NotImplementedError

    # --- boucle ---------------------------------------------------------------
    def __call__(self, i: int):
        self._update_session(i)
        self._update_vol(i)
        if i < self.p.bars_required:
            return
        self.on_quant_bar(i)

    def _update_session(self, i):
        e = self.e
        self.i = i
        self.tod = e.tod[i]
        self.sdate = e.date[i]
        now_in = self.rth_start < self.tod <= self.rth_end
        if now_in and self.sdate != self.current_rth_date:
            self.prev_rth_close = self.last_rth_close
            self.current_rth_date = self.sdate
            self.rth_open, self.rth_high, self.rth_low = e.o[i], e.h[i], e.l[i]
            self.has_first30, self.first30_close, self.r_first30 = False, NAN, NAN
            self.cum_tpv = self.cum_vol = 0.0
            if ok(self.prev_rth_close) and self.prev_rth_close > 0:
                self.r_overnight = self.rth_open / self.prev_rth_close - 1.0
                self.has_overnight = True
                self.overnight_ring.add(self.r_overnight)
            else:
                self.r_overnight, self.has_overnight = NAN, False
            if ok(self.day_rv_accum) and self.day_rv_accum > 0:
                self.prev_day_rv = math.sqrt(self.day_rv_accum)
                self.daily_rv_ring.add(self.prev_day_rv)
                self.daily_rv_median = self.daily_rv_ring.median() if len(self.daily_rv_ring) >= 5 else NAN
            self.day_rv_accum = 0.0
        self.in_rth = now_in
        if now_in:
            self.rth_high = max(self.rth_high, e.h[i])
            self.rth_low = min(self.rth_low, e.l[i])
            prev = self.last_rth_close
            self.last_rth_close = e.c[i]
            if ok(prev) and prev > 0:
                ratio = e.c[i] / prev
                # C# : Math.Log d un nombre <= 0 vaut NaN (pas d exception) et contamine l accumulateur du jour
                self.day_rv_accum = self.day_rv_accum + math.log(ratio) ** 2 if ratio > 0 else NAN
            if not self.has_first30 and self.tod >= self.first30_end:
                self.first30_close = e.c[i]
                self.has_first30 = True
                self.r_first30 = self.first30_close / self.prev_rth_close - 1.0 if ok(self.prev_rth_close) and self.prev_rth_close > 0 else NAN
        if self.final_bar_before(self.rth_end) and ok(self.prev_rth_close) and self.prev_rth_close > 0:
            self.daily_ret_ring.add(e.c[i] / self.prev_rth_close - 1.0)
        if now_in:
            tp = (e.h[i] + e.l[i] + e.c[i]) / 3.0
            vol = e.v[i] if e.v[i] > 0 else 1.0
            self.cum_tpv += tp * vol
            self.cum_vol += vol
            self.vwap = self.cum_tpv / self.cum_vol

    def _update_vol(self, i):
        e = self.e
        if i < 1 or e.c[i - 1] <= 0 or e.c[i] <= 0:
            return
        r = math.log(e.c[i] / e.c[i - 1])
        self.rv_ring.add(r * r)
        self.bar_ret_ring.add(r)
        if len(self.rv_ring) >= 5:
            self.sigma_rv_bar = math.sqrt(self.rv_ring.sum())
            self.sigma_move = self.bar_ret_ring.std()
            scale = self.bars_per_rth_day() / max(1.0, len(self.rv_ring))
            self.sigma_daily = self.sigma_rv_bar * math.sqrt(scale)
            self.sigma_annual = self.sigma_daily * math.sqrt(252.0)

    def bars_per_rth_day(self):
        m = self.rth_end - self.rth_start
        return max(1.0, (m if m > 0 else 390.0) / max(0.25, self.bar_span))

    # --- helpers horaires --------------------------------------------------------
    def crossed_tod(self, target: float) -> bool:
        if self.tod < target:
            return False
        key = ("c", target)
        st = self._cross.get(key)
        if st is not None and st[0] == self.i:
            return True
        if self.tod - target > self.bar_span * 3:
            self._cross[key] = (-1, self.sdate)
            return False
        if st is not None and st[1] == self.sdate:
            return False
        self._cross[key] = (self.i, self.sdate)
        return True

    def final_bar_before(self, deadline: float) -> bool:
        if self.tod >= deadline or self.tod + self.bar_span < deadline:
            return False
        st = self._final.get(deadline)
        if st is not None and st[0] == self.i:
            return True
        if st is not None and st[1] == self.sdate:
            return False
        self._final[deadline] = (self.i, self.sdate)
        return True

    def sortie_temporelle(self, deadline: float) -> bool:
        if self.final_bar_before(deadline):
            return True
        if self.e.pos == 0 or self.tod < deadline or self.tod >= deadline + 120:
            return False
        return True

    def in_tod_window(self, a: float, b: float) -> bool:
        return (a <= self.tod <= b) if a <= b else (self.tod >= a or self.tod <= b)

    # --- taille et execution ---------------------------------------------------------
    @property
    def atr_pts(self) -> float:
        a = self.atr[self.i]
        t = self.e.inst.tick
        return a if ok(a) and a > t and self.i >= self.p.atr_period else t * 4.0

    def compute_size(self, conviction: float = 1.0) -> int:
        p = self.p
        q = float(p.base_qty)
        if p.sizing == "vol_target":
            if not ok(self.sigma_annual) or self.sigma_annual < 1e-4:
                return int(min(max(p.base_qty, 1), p.max_qty))
            q = p.base_qty * (p.target_vol_pct / 100.0) / self.sigma_annual
        elif p.sizing == "conviction":
            if not ok(self.sigma_daily) or self.sigma_daily < 1e-6 or not ok(conviction):
                return int(min(max(p.base_qty, 1), p.max_qty))
            q = p.base_qty * abs(conviction) / self.sigma_daily
        if not ok(q):
            q = p.base_qty
        return int(min(max(int(math.floor(q + 0.5)), 1), p.max_qty))

    def vol_filter_passes(self) -> bool:
        if not self.p.use_vol_filter:
            return True
        return ok(self.prev_day_rv) and ok(self.daily_rv_median) and self.prev_day_rv > self.daily_rv_median

    @property
    def can_long(self):
        return self.p.direction != "short_uniquement"

    @property
    def can_short(self):
        return self.p.direction != "long_uniquement"

    def enter(self, d: int, qty: int, tag: str = "", stop=NAN, target=NAN) -> bool:
        """EnterDirectional : +1 long, -1 short ; inversion si position opposee ; stop / objectif armes au remplissage."""
        e = self.e
        if d == 0 or qty <= 0 or (d > 0 and not self.can_long) or (d < 0 and not self.can_short):
            return False
        if (d > 0 and e.pos > 0) or (d < 0 and e.pos < 0):
            return False
        e.market(d * qty, tag, e.round_tick(stop) if ok(stop) else NAN, e.round_tick(target) if ok(target) else NAN, "entree " + tag)
        return True

    def go_flat(self, reason: str):
        if self.e.pos != 0:
            self.e.market(0, reason=reason)

    def set_stop(self, price: float):
        if ok(price) and price > 0:
            self.e.stop = self.e.round_tick(price)
            if self.e.order is not None and self.e.order.target_pos != 0:
                self.e.order.stop = self.e.stop

    def set_target(self, price: float):
        if ok(price) and price > 0:
            self.e.target = self.e.round_tick(price)
            if self.e.order is not None and self.e.order.target_pos != 0:
                self.e.order.target = self.e.target

    @property
    def flat(self):
        return self.e.pos == 0


# =============================================================================
#  Statistiques d un run
# =============================================================================
def summarize(e: Engine, start=None) -> dict:
    tr = [t for t in e.trades if start is None or pd.Timestamp(t.entry_time) >= pd.Timestamp(start)]
    eq = e.equity()
    pnl = np.array([t.pnl for t in tr])
    daily = eq.diff().dropna()
    wins = pnl[pnl > 0].sum() if pnl.size else 0.0
    losses = -pnl[pnl < 0].sum() if pnl.size else 0.0
    peak = eq.cummax()
    dd = (peak - eq).max() if len(eq) else 0.0
    sd = daily.std(ddof=1) if len(daily) > 2 else NAN
    return dict(trades=len(tr), win_rate=float((pnl > 0).mean()) if pnl.size else NAN, net=float(pnl.sum()) if pnl.size else 0.0,
                profit_factor=float(wins / losses) if losses > 0 else (math.inf if wins > 0 else NAN),
                avg_trade=float(pnl.mean()) if pnl.size else NAN,
                sharpe=float(daily.mean() / sd * math.sqrt(252)) if ok(sd) and sd > 0 else NAN,
                max_dd=float(dd), start=eq.index[0] if len(eq) else None, end=eq.index[-1] if len(eq) else None,
                capital=e.capital, t_stat=float(pnl.mean() / (pnl.std(ddof=1) / math.sqrt(pnl.size))) if pnl.size > 2 and pnl.std(ddof=1) > 0 else NAN)
