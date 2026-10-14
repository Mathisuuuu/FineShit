"""Donnees : instruments, chargement du dossier de cotations, historiques, donnees synthetiques,
fichiers externes (fondamentaux, resultats, facteurs Fama-French, agenda macro).

Formats de cotations reconnus (detection automatique, separateur , ; ou tabulation) :
  - export NinjaTrader (Tools > Historical Data > Export) : "yyyyMMdd;open;high;low;close;volume"
    ou "yyyyMMdd HHmmss;open;high;low;close;volume" (barres minute -> agregees en jour)
  - Yahoo / Stooq / generique avec en-tete : Date, Open, High, Low, Close[, Adj Close], Volume
    (noms francais acceptes : ouverture, haut, plus_haut, bas, cloture, dernier...)
  - MetaTrader : <DATE> <TIME> <OPEN> <HIGH> <LOW> <CLOSE> <TICKVOL> ...
  - klines Binance sans en-tete (open_time en ms, open, high, low, close, volume, ...)
Le symbole vient du nom de fichier ("SPY.Last.txt" -> SPY, "BTC-USD.csv" -> BTCUSD,
"EURUSD=X.csv" -> EURUSD, "SPY_daily.csv" -> SPY) puis de la table d alias.
"""
from __future__ import annotations

import math
import os
import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

import numpy as np
import pandas as pd

from . import mathx as M

# =============================================================================
#  Instruments
# =============================================================================
ASSET_CLASSES = ("Action", "Etf", "Crypto", "Forex", "Indice", "Future", "Cfd", "Option", "Autre")

DEFAULT_ETFS = ("SPY,QQQ,IWM,DIA,XLK,XLF,XLV,XLE,XLI,XLY,XLP,XLU,XLB,XLRE,XLC,GLD,SLV,TLT,IEF,HYG,LQD,"
                "EEM,EFA,VTI,VOO,SMH,ARKK,USO,UNG").split(",")
CRYPTO_BASES = set(("BTC,ETH,SOL,XRP,ADA,DOGE,AVAX,LINK,DOT,LTC,BCH,UNI,XLM,ATOM,ETC,FIL,AAVE,ALGO,NEAR,SHIB,"
                    "BNB,MATIC,POL,TRX,TON,SUI,APT,ARB,OP,PEPE,XMR,HBAR,ICP,INJ").split(","))
FX_CODES = set("USD,EUR,GBP,JPY,AUD,CHF,CAD,NZD,HKD,SEK,NOK,MXN,SGD,DKK,PLN,ZAR,TRY,CNH,XAU,XAG".split(","))
CFD_CURRENCY = {"US500": "USD", "US30": "USD", "NAS100": "USD", "US2000": "USD", "GER40": "EUR", "DE40": "EUR",
                "FRA40": "EUR", "EU50": "EUR", "UK100": "GBP", "JPN225": "JPY", "AUS200": "AUD", "HK50": "HKD"}

# Alias des noms de fichiers courants vers les noms utilises par les strategies.
DEFAULT_ALIASES = {
    "^GSPC": "US500", "GSPC": "US500", "SPX": "US500", "SPX500": "US500", "SPX500USD": "US500",
    "^NDX": "NAS100", "NDX": "NAS100", "NAS100USD": "NAS100", "USTEC": "NAS100",
    "^GDAXI": "GER40", "GDAXI": "GER40", "DAX": "GER40", "DE30EUR": "GER40", "DE40EUR": "GER40",
    "GC=F": "XAUUSD", "GOLD": "XAUUSD", "XAU": "XAUUSD",
    "VIX": "^VIX", "VXN": "^VXN",
    "BRK.B": "BRK-B",
}

_SUFFIX_TOKENS = {"LAST", "BID", "ASK", "DAILY", "DAY", "JOUR", "JOURNALIER", "D1", "1D", "D", "HIST", "HISTORY",
                  "HISTORIQUE", "DATA", "DONNEES", "OHLC", "OHLCV", "QUOTES", "COTATIONS", "PRICES", "M1", "M15",
                  "1MIN", "15MIN", "H1", "1H", "60MIN", "MINUTE", "TICK", "TICKS", "US", "USA"}


@dataclass
class Instrument:
    name: str
    asset_class: str = "Action"
    currency: str = "USD"          # devise de cotation
    point_value: float = 1.0
    tick_size: float = 0.01
    seven_days: bool = False       # marche 7 j / 7 (crypto)

    @property
    def is_crypto(self) -> bool:
        return self.asset_class == "Crypto"


def is_crypto_name(name: str) -> bool:
    n = name.upper().replace("-", "").replace("/", "")
    for quote in ("USDT", "USDC", "USD", "EUR"):
        if n.endswith(quote) and n[: -len(quote)] in CRYPTO_BASES:
            return True
    return n in CRYPTO_BASES


def classify(name: str, etfs=DEFAULT_ETFS, overrides: dict | None = None) -> Instrument:
    """Classe d actifs, devise et 7j/7 deduits du nom (surcharges possibles)."""
    n = name.strip()
    up = n.upper()
    if overrides and n in overrides:
        o = overrides[n]
        return Instrument(name=n, **o) if isinstance(o, dict) else o
    if is_crypto_name(up):
        return Instrument(n, "Crypto", "USD", 1.0, 0.01, True)
    if len(up) == 6 and up[:3] in FX_CODES and up[3:] in FX_CODES:
        return Instrument(n, "Forex", up[3:], 1.0, 0.0001 if up[3:] != "JPY" else 0.01, False)
    if up in CFD_CURRENCY:
        return Instrument(n, "Cfd", CFD_CURRENCY[up], 1.0, 0.1, False)
    if up.startswith("^"):
        return Instrument(n, "Indice", "USD", 1.0, 0.01, False)
    if up in {e.upper() for e in etfs}:
        return Instrument(n, "Etf", "USD", 1.0, 0.01, False)
    return Instrument(n, "Action", "USD", 1.0, 0.01, False)


# =============================================================================
#  Nettoyage d une serie OHLCV (memes regles que NxBarHistory.Add)
# =============================================================================
def clean_ohlcv(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    for c in ("open", "high", "low", "close", "volume"):
        if c not in df.columns:
            df[c] = np.nan
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df = df[np.isfinite(df["close"]) & (df["close"] > 0)]
    c = df["close"]
    o = df["open"].where(np.isfinite(df["open"]) & (df["open"] > 0), c)
    hi_min = np.maximum(o, c)
    lo_max = np.minimum(o, c)
    h = df["high"].where(np.isfinite(df["high"]) & (df["high"] >= hi_min), hi_min)
    lo = df["low"].where(np.isfinite(df["low"]) & (df["low"] > 0) & (df["low"] <= lo_max), lo_max)
    out = pd.DataFrame({"open": o, "high": h, "low": lo, "close": c,
                        "volume": df["volume"].where(np.isfinite(df["volume"]), 0.0)}, index=df.index)
    out = out[~out.index.duplicated(keep="last")].sort_index()
    return out


# =============================================================================
#  Lecture des fichiers de cotations
# =============================================================================
def symbol_from_filename(path: str, aliases: dict | None = None) -> str:
    base = os.path.basename(path)
    for ext in (".csv", ".txt", ".tsv", ".dat", ".gz", ".zip"):
        if base.lower().endswith(ext):
            base = base[: -len(ext)]
    stem = base
    up = stem.upper()
    al = {k.upper(): v for k, v in {**DEFAULT_ALIASES, **(aliases or {})}.items()}
    if up in al:
        return al[up]
    up = up.replace("=X", "")
    if "." in up and not up.startswith("^"):
        head = up.split(".")[0]
        up = head if head else up
    parts = [p for p in re.split(r"[_\s]+", up) if p]
    while len(parts) > 1 and (parts[-1] in _SUFFIX_TOKENS or parts[-1] == "##-##"):
        parts.pop()                      # "ES ##-##" = contrat continu NinjaTrader -> "ES"
    up = "".join(parts)
    if up in al:
        return al[up]
    nodash = up.replace("-", "").replace("/", "")
    if is_crypto_name(nodash) or (len(nodash) == 6 and nodash[:3] in FX_CODES and nodash[3:] in FX_CODES):
        up = nodash
        if up.endswith("USDT") or up.endswith("USDC"):
            up = up[:-4] + "USD"
    return al.get(up, up)


_COLS = {
    "date": ("date", "datetime", "time", "timestamp", "<date>", "day", "jour", "open_time", "opentime", "date_time"),
    "time": ("<time>", "heure", "hour"),
    "open": ("open", "<open>", "o", "ouverture", "ouv", "premier", "first"),
    "high": ("high", "<high>", "h", "haut", "plus_haut", "plushaut", "max"),
    "low": ("low", "<low>", "l", "bas", "plus_bas", "plusbas", "min"),
    "close": ("close", "<close>", "c", "cloture", "clôture", "fermeture", "dernier", "last", "price", "prix"),
    "adjclose": ("adj close", "adj_close", "adjclose", "adjusted_close", "cloture_ajustee"),
    "volume": ("volume", "<vol>", "<tickvol>", "vol", "v", "tickvol", "<volume>", "qty"),
}


def _match_col(cols: list[str], key: str) -> str | None:
    norm = {c: c.strip().lower() for c in cols}
    for cand in _COLS[key]:
        for c, n in norm.items():
            if n == cand:
                return c
    return None


def _parse_dates(s: pd.Series) -> pd.DatetimeIndex:
    s = s.astype(str).str.strip()
    sample = s.iloc[0] if len(s) else ""
    if re.fullmatch(r"\d{13}", sample):
        return pd.to_datetime(s.astype("int64"), unit="ms")
    if re.fullmatch(r"\d{10}", sample):
        return pd.to_datetime(s.astype("int64"), unit="s")
    if re.fullmatch(r"\d{8}", sample):
        return pd.to_datetime(s, format="%Y%m%d")
    if re.fullmatch(r"\d{8} \d{6}", sample):
        return pd.to_datetime(s, format="%Y%m%d %H%M%S")
    if re.fullmatch(r"\d{8} \d{6} \d{7}", sample):
        return pd.to_datetime(s.str.slice(0, 15), format="%Y%m%d %H%M%S")
    if re.fullmatch(r"\d{4}\.\d{2}\.\d{2}.*", sample):
        return pd.to_datetime(s.str.replace(".", "-", n=2, regex=False), errors="coerce")
    if re.fullmatch(r"\d{2}/\d{2}/\d{4}.*", sample):
        return pd.to_datetime(s, dayfirst=True, errors="coerce")
    return pd.DatetimeIndex(pd.to_datetime(s, errors="coerce", utc=True)).tz_convert(None)


def _read_csv(path: str, **kw) -> pd.DataFrame:
    """Lecteur C de pandas (rapide sur les fichiers minute de plusieurs millions de lignes), lecteur python en repli."""
    try:
        return pd.read_csv(path, encoding="utf-8-sig", engine="c", **kw)
    except (ValueError, pd.errors.ParserError):
        return pd.read_csv(path, encoding="utf-8-sig", engine="python", **kw)


def read_quotes_file(path: str, use_adjusted: bool = True) -> pd.DataFrame:
    """Lit un fichier de cotations et renvoie un DataFrame open/high/low/close/volume indexe par date."""
    with open(path, "r", encoding="utf-8-sig", errors="replace") as fh:
        head = [fh.readline() for _ in range(5)]
    first = next((l for l in head if l.strip()), "")
    sep = ";" if first.count(";") >= 3 else ("\t" if first.count("\t") >= 3 else ",")
    has_header = bool(re.search(r"[A-Za-z<]", first.split(sep)[0])) and not re.fullmatch(r"\d{8}( \d{6})?", first.split(sep)[0].strip())
    decimal = "," if sep == ";" and re.search(r"\d,\d", "".join(head)) else "."
    if has_header:
        df = _read_csv(path, sep=sep, decimal=decimal)
        cols = list(df.columns)
        cd, ct = _match_col(cols, "date"), _match_col(cols, "time")
        if cd is None:
            cd = cols[0]
        dates = df[cd].astype(str)
        if ct is not None:
            dates = dates + " " + df[ct].astype(str)
        idx = pd.DatetimeIndex(_parse_dates(dates))
        out = pd.DataFrame(index=idx)
        for k in ("open", "high", "low", "close", "volume"):
            c = _match_col(cols, k)
            out[k] = pd.to_numeric(df[c], errors="coerce").values if c is not None else np.nan
        ca = _match_col(cols, "adjclose")
        if use_adjusted and ca is not None:
            adj = pd.to_numeric(df[ca], errors="coerce").values
            ratio = np.where(np.isfinite(adj) & (out["close"].values > 0), adj / out["close"].values, 1.0)
            for k in ("open", "high", "low", "close"):
                out[k] = out[k].values * ratio
    else:
        df = _read_csv(path, sep=sep, decimal=decimal, header=None)
        idx = pd.DatetimeIndex(_parse_dates(df[0]))
        n = df.shape[1]
        if n >= 6:
            out = pd.DataFrame({"open": df[1].values, "high": df[2].values, "low": df[3].values,
                                "close": df[4].values, "volume": df[5].values}, index=idx)
        elif n >= 5:
            out = pd.DataFrame({"open": df[1].values, "high": df[2].values, "low": df[3].values,
                                "close": df[4].values, "volume": 0.0}, index=idx)
        else:
            # Ticks NinjaTrader : temps;prix;volume -> barres agregees plus bas
            px = pd.to_numeric(df[1], errors="coerce").values
            vol = pd.to_numeric(df[n - 1], errors="coerce").values if n >= 3 else np.zeros(len(df))
            out = pd.DataFrame({"open": px, "high": px, "low": px, "close": px, "volume": vol}, index=idx)
    out = out[~out.index.isna()]
    return out.sort_index()


def to_daily(df: pd.DataFrame) -> pd.DataFrame:
    """Agrege des barres intrajournalieres en barres journalieres (jour calendaire de l horodatage)."""
    if df.empty:
        return df
    idx = pd.DatetimeIndex(df.index)
    if (idx.normalize() == idx).all() and not idx.normalize().duplicated().any():
        out = df.copy()
        out.index = idx.normalize()
        return out
    g = df.groupby(idx.normalize())
    return pd.DataFrame({"open": g["open"].first(), "high": g["high"].max(), "low": g["low"].min(),
                         "close": g["close"].last(), "volume": g["volume"].sum()})


def resample_bars(df: pd.DataFrame, minutes: int) -> pd.DataFrame:
    rule = f"{int(minutes)}min"
    r = df.resample(rule, label="right", closed="right")
    out = pd.DataFrame({"open": r["open"].first(), "high": r["high"].max(), "low": r["low"].min(),
                        "close": r["close"].last(), "volume": r["volume"].sum()})
    return out.dropna(subset=["close"])


def load_folder(folder: str, aliases: dict | None = None, daily: bool = True, verbose: bool = False,
                only=None) -> dict[str, pd.DataFrame]:
    """Charge tous les fichiers de cotations d un dossier (recursif). Retourne {symbole: DataFrame}.
    only : symboles a lire (les autres fichiers ne sont pas ouverts), utile pour les barres minute."""
    res: dict[str, pd.DataFrame] = {}
    keep = {x.upper() for x in only} if only else None
    for root, _, files in os.walk(folder):
        for f in sorted(files):
            if not re.search(r"\.(csv|txt|tsv)$", f, re.I):
                continue
            p = os.path.join(root, f)
            if keep is not None:
                key = symbol_from_filename(p, aliases).upper()
                if key not in keep and re.sub(r"\d{2}-\d{2}$", "", key) not in keep:
                    continue
            try:
                df = read_quotes_file(p)
            except Exception as ex:  # fichier illisible : on continue
                if verbose:
                    print(f"[data] ignore {p} : {ex}")
                continue
            if df.empty:
                continue
            if daily:
                df = to_daily(df)
            df = clean_ohlcv(df)
            sym = symbol_from_filename(p, aliases)
            if sym in res:
                df = pd.concat([res[sym], df])
                df = df[~df.index.duplicated(keep="last")].sort_index()
            res[sym] = df
            if verbose:
                print(f"[data] {sym:<10} {len(df):6d} barres {df.index[0].date()} -> {df.index[-1].date()} ({f})")
    return res


# =============================================================================
#  Historique d un symbole aligne sur le calendrier maitre (vue "NxBarHistory")
# =============================================================================
class History:
    """Historique OHLCV complet d un symbole ; seules les `count` premieres barres sont visibles.

    Les indicateurs sont pre-calcules de facon causale (aucune information future)
    et lus a l indice count-1, comme NxBarHistory dans NinjaScript.
    """

    def __init__(self, name: str, df: pd.DataFrame, atr_period: int = 14):
        self.name = name
        self.dates = pd.DatetimeIndex(df.index)
        self.open = df["open"].to_numpy(float)
        self.high = df["high"].to_numpy(float)
        self.low = df["low"].to_numpy(float)
        self.close = df["close"].to_numpy(float)
        self.volume = df["volume"].to_numpy(float)
        self.n = len(self.close)
        self.count = 0
        c = self.close
        self.logret = np.full(self.n, np.nan)
        self.logret[1:] = np.log(c[1:] / c[:-1])
        self.simpret = np.full(self.n, np.nan)
        self.simpret[1:] = c[1:] / c[:-1] - 1.0
        self.atr_series = self._wilder_atr(atr_period)
        self.csum_close = np.concatenate([[0.0], np.cumsum(c)])
        self.csum_dv = np.concatenate([[0.0], np.cumsum(c * self.volume)])
        lr0 = np.where(np.isfinite(self.logret), self.logret, 0.0)
        self.csum_r2 = np.concatenate([[0.0], np.cumsum(lr0 * lr0)])
        self.date_pos = {d: i for i, d in enumerate(self.dates)}
        self.day_ordinals = np.array([d.toordinal() for d in self.dates.date]) if self.n else np.array([], int)

    def _wilder_atr(self, period: int) -> np.ndarray:
        h, l, c = self.high, self.low, self.close
        n = self.n
        atr = np.full(n, np.nan)
        tr = np.empty(n)
        if n == 0:
            return atr
        tr[0] = h[0] - l[0]
        if n > 1:
            pc = c[:-1]
            tr[1:] = np.maximum(h[1:] - l[1:], np.maximum(np.abs(h[1:] - pc), np.abs(l[1:] - pc)))
        if n >= period:
            a = tr[:period].sum() / period
            atr[period - 1] = a
            for i in range(period, n):
                a = (a * (period - 1) + tr[i]) / period
                atr[i] = a
        return atr

    # --- acces "dernier" ---
    @property
    def last(self) -> int:
        return self.count - 1

    @property
    def last_close(self) -> float:
        return float(self.close[self.count - 1]) if self.count > 0 else M.NAN

    @property
    def last_date(self):
        return self.dates[self.count - 1] if self.count > 0 else None

    @property
    def atr(self) -> float:
        return float(self.atr_series[self.count - 1]) if self.count > 0 else M.NAN

    def close_ago(self, k: int) -> float:
        i = self.count - 1 - k
        return float(self.close[i]) if 0 <= i < self.count else M.NAN

    def return_over(self, lookback: int, skip: int) -> float:
        p_end, p_start = self.close_ago(skip), self.close_ago(lookback)
        return p_end / p_start - 1.0 if M.ok(p_end) and M.ok(p_start) and p_start > 0 else M.NAN

    def returns(self, n: int, log: bool = True) -> np.ndarray:
        """Les n derniers rendements (du plus ancien au plus recent)."""
        lo = max(1, self.count - n)
        src = self.logret if log else self.simpret
        return src[lo:self.count]

    def realized_vol(self, n: int) -> float:
        if self.count < n + 1:
            return M.NAN
        r = self.returns(n)
        s = M.std(r)
        return s * math.sqrt(M.TRADING_DAYS_PER_YEAR) if M.ok(s) else M.NAN

    def realized_variance(self, n: int) -> float:
        if self.count < n + 1:
            return M.NAN
        k = self.count
        return float(self.csum_r2[k] - self.csum_r2[k - n])

    def sma(self, n: int) -> float:
        if self.count < n or n <= 0:
            return M.NAN
        k = self.count
        return float((self.csum_close[k] - self.csum_close[k - n]) / n)

    def sma_at(self, n: int, end_inclusive: int) -> float:
        if end_inclusive + 1 < n or n <= 0:
            return M.NAN
        return float((self.csum_close[end_inclusive + 1] - self.csum_close[end_inclusive + 1 - n]) / n)

    def avg_dollar_volume(self, n: int) -> float:
        if self.count < n or n <= 0:
            return M.NAN
        k = self.count
        return float((self.csum_dv[k] - self.csum_dv[k - n]) / n)

    def index_of(self, day) -> int:
        i = self.date_pos.get(pd.Timestamp(day), -1)
        return i if 0 <= i < self.count else -1

    def index_on_or_before(self, day) -> int:
        i = int(np.searchsorted(self.dates.values[: self.count], np.datetime64(pd.Timestamp(day)), side="right")) - 1
        return i

    def close_on_or_before(self, day) -> float:
        i = self.index_on_or_before(day)
        return float(self.close[i]) if i >= 0 else M.NAN

    def log_return_at(self, i: int) -> float:
        return float(self.logret[i]) if 1 <= i < self.count else M.NAN


def aligned_returns(a: History, b: History, n: int, log: bool = True):
    """Rendements alignes par jour de bourse (dates communes, n intervalles au plus)."""
    if a.count < 2 or b.count < 2:
        return np.array([]), np.array([])
    da = a.dates.values[: a.count][-(n + 1) * 3:]
    db = b.dates.values[: b.count]
    common = np.intersect1d(da, db, assume_unique=True)[-(n + 1):]
    if common.size < 2:
        return np.array([]), np.array([])
    ia = np.searchsorted(a.dates.values[: a.count], common)
    ib = np.searchsorted(db, common)
    pa, pb = a.close[ia], b.close[ib]
    if log:
        return np.log(pa[1:] / pa[:-1]), np.log(pb[1:] / pb[:-1])
    return pa[1:] / pa[:-1] - 1.0, pb[1:] / pb[:-1] - 1.0


def return_correlation(a: History, b: History, n: int) -> float:
    ra, rb = aligned_returns(a, b, n)
    return M.correlation(ra, rb) if ra.size >= 10 else M.NAN


def aligned_return_rows(hs: list[History], n: int) -> np.ndarray:
    """Matrice (dates communes x historiques) des rendements log sur les n derniers intervalles."""
    if not hs or any(h.count < 2 for h in hs):
        return np.empty((0, len(hs)))
    common = hs[0].dates.values[: hs[0].count]
    for h in hs[1:]:
        common = np.intersect1d(common, h.dates.values[: h.count], assume_unique=True)
    common = common[-(n + 1):]
    if common.size < 2:
        return np.empty((0, len(hs)))
    cols = []
    for h in hs:
        p = h.close[np.searchsorted(h.dates.values[: h.count], common)]
        cols.append(np.log(p[1:] / p[:-1]))
    return np.column_stack(cols)


def basket_vol(hs: list[History], weights, n: int) -> float:
    rows = aligned_return_rows(hs, n)
    if rows.shape[0] < max(10, n // 3):
        return M.NAN
    b = np.nan_to_num(rows) @ np.asarray(weights, float)
    sd = M.std(b)
    return sd * math.sqrt(M.TRADING_DAYS_PER_YEAR) if M.ok(sd) else M.NAN


def monthly_returns(h: History, months: int) -> list[tuple[pd.Timestamp, float]]:
    """Rendements mensuels (fin de mois a fin de mois), du plus ancien au plus recent."""
    if h.count < 2:
        return []
    d = h.dates[: h.count]
    s = pd.Series(h.close[: h.count], index=d)
    ends = s.groupby([d.year, d.month]).last()
    keys = [pd.Timestamp(y, m, 1) for (y, m) in ends.index]
    vals = ends.to_numpy()
    out = []
    for k in range(max(1, len(vals) - months), len(vals)):
        if vals[k - 1] > 0:
            out.append((keys[k], vals[k] / vals[k - 1] - 1))
    return out


# =============================================================================
#  Fichiers externes (Data/*.csv du depot)
# =============================================================================
def _read_csv_comments(path: str) -> pd.DataFrame | None:
    if not path or not os.path.exists(path):
        return None
    try:
        df = pd.read_csv(path, comment="#", skip_blank_lines=True)
    except Exception:
        return None
    df.columns = [c.strip().lower() for c in df.columns]
    return df if len(df) else None


def _col(df: pd.DataFrame, *names):
    for n in names:
        if n in df.columns:
            return n
    return None


class Fundamentals:
    """Fondamentaux point-in-time (fiche 3) : derniere ligne publiee au plus tard le jour donne."""

    def __init__(self, path: str | None = None):
        self.rows: dict[str, list[dict]] = {}
        self.message = "aucun fichier"
        if path:
            self.load(path)

    @property
    def loaded(self) -> bool:
        return bool(self.rows)

    def load(self, path: str) -> int:
        df = _read_csv_comments(path)
        self.rows = {}
        if df is None:
            self.message = "fondamentaux absents : " + str(path)
            return 0
        cs, cd = _col(df, "symbol", "ticker"), _col(df, "available_date", "filing_date", "report_date", "date")
        if cs is None or cd is None:
            self.message = "colonnes symbol/available_date manquantes"
            return 0
        m = {"book_equity": _col(df, "book_equity", "total_equity", "equity"),
             "net_income": _col(df, "net_income_ttm", "net_income", "earnings"),
             "gross_profit": _col(df, "gross_profit_ttm", "gross_profit"),
             "total_assets": _col(df, "total_assets", "assets"),
             "total_liabilities": _col(df, "total_liabilities", "liabilities", "total_debt"),
             "shares": _col(df, "shares_outstanding", "shares")}
        n = 0
        for _, r in df.iterrows():
            d = pd.to_datetime(str(r[cd]), errors="coerce")
            s = str(r[cs]).strip()
            if not s or pd.isna(d):
                continue
            row = {"available": d.normalize()}
            for k, c in m.items():
                row[k] = float(pd.to_numeric(r[c], errors="coerce")) if c else M.NAN
            ta = row["total_assets"]
            row["profitability"] = M.safe_div(row["gross_profit"], ta)
            row["leverage"] = M.safe_div(row["total_liabilities"], ta)
            self.rows.setdefault(s.upper(), []).append(row)
            n += 1
        for l in self.rows.values():
            l.sort(key=lambda x: x["available"])
        self.message = f"{n} lignes de fondamentaux pour {len(self.rows)} symboles"
        return n

    def has(self, sym: str) -> bool:
        return sym.upper() in self.rows

    def as_of(self, sym: str, day):
        best = None
        for f in self.rows.get(sym.upper(), []):
            if f["available"] <= pd.Timestamp(day):
                best = f
            else:
                break
        return best


class Earnings:
    """Dates de resultats (fiches 8 et 14)."""

    def __init__(self, path: str | None = None):
        self.dates: dict[str, list[pd.Timestamp]] = {}
        self.message = "aucun fichier"
        if path:
            self.load(path)

    @property
    def loaded(self) -> bool:
        return bool(self.dates)

    def load(self, path: str) -> int:
        df = _read_csv_comments(path)
        if df is None:
            self.message = "aucune date de resultats (" + str(path) + ")"
            return 0
        cs, cd = _col(df, "symbol", "ticker"), _col(df, "date", "report_date", "reportdate", "earnings_date")
        if cs is None or cd is None:
            self.message = "colonnes requises : symbol, date"
            return 0
        n = 0
        for s, d in zip(df[cs].astype(str), pd.to_datetime(df[cd], errors="coerce")):
            if pd.isna(d) or not s.strip():
                continue
            l = self.dates.setdefault(s.strip().upper(), [])
            if d.normalize() not in l:
                l.append(d.normalize())
                n += 1
        for l in self.dates.values():
            l.sort()
        self.message = f"{n} dates de resultats chargees pour {len(self.dates)} symboles"
        return n

    def has_data(self, sym: str) -> bool:
        return sym.upper() in self.dates

    def within(self, sym: str, day, business_days: int) -> bool:
        nxt = next((d for d in self.dates.get(sym.upper(), []) if d >= pd.Timestamp(day)), None)
        if nxt is None:
            return False
        limit = pd.Timestamp(day)
        for _ in range(business_days):
            limit = next_business_day(limit)
        return nxt <= limit


class FactorFile:
    """Facteurs Fama-French mensuels (mkt_rf, smb, hml, rf), en fractions."""

    def __init__(self, path: str | None = None):
        self.monthly: dict[tuple[int, int], list[float]] = {}
        self.message = "aucun fichier"
        if path:
            self.load(path)

    @property
    def loaded(self) -> bool:
        return bool(self.monthly)

    def load(self, path: str) -> int:
        df = _read_csv_comments(path)
        if df is None:
            self.message = "facteurs absents : " + str(path)
            return 0
        cd = _col(df, "date", "month", "yyyymm")
        cm, cs, ch, cr = _col(df, "mkt_rf", "mkt-rf", "mktrf", "market"), _col(df, "smb"), _col(df, "hml"), _col(df, "rf")
        if None in (cd, cm, cs, ch):
            self.message = "colonnes date/mkt_rf/smb/hml manquantes"
            return 0
        raw = []
        for _, r in df.iterrows():
            ds = str(r[cd]).strip().split(".")[0]
            if re.fullmatch(r"\d{6}", ds):
                d = pd.Timestamp(int(ds[:4]), int(ds[4:]), 1)
            else:
                d = pd.to_datetime(ds, errors="coerce")
            if pd.isna(d):
                continue
            f = [float(pd.to_numeric(r[c], errors="coerce")) for c in (cm, cs, ch)]
            f.append(float(pd.to_numeric(r[cr], errors="coerce")) if cr else 0.0)
            if not all(M.ok(v) for v in f[:3]):
                continue
            raw.append((d, f))
        if not raw:
            self.message = "aucune ligne de facteurs valide"
            return 0
        scale = 0.01 if M.median([abs(f[0]) for _, f in raw]) > 0.05 else 1.0
        for d, f in raw:
            cur = self.monthly.setdefault((d.year, d.month), [0.0, 0.0, 0.0, 0.0])
            for i in range(4):
                v = f[i] * scale if M.ok(f[i]) else 0.0
                cur[i] = (1 + cur[i]) * (1 + v) - 1
        self.message = f"{len(self.monthly)} mois de facteurs"
        return len(self.monthly)

    def get_month(self, year: int, month: int):
        return self.monthly.get((year, month))


@dataclass
class MacroEvent:
    utc: datetime
    currency: str
    impact: str
    title: str

    @property
    def level(self) -> int:
        s = (self.impact or "").strip().lower()
        if s in ("high", "haut", "fort", "3"):
            return 3
        if s in ("medium", "moyen", "2"):
            return 2
        if s in ("low", "faible", "bas", "1"):
            return 1
        try:
            return int(float(s))
        except ValueError:
            return 0


class MacroCalendar:
    def __init__(self, path: str | None = None):
        self.events: list[MacroEvent] = []
        self.message = "aucun fichier"
        if path:
            self.load(path)

    def load(self, path: str) -> int:
        df = _read_csv_comments(path)
        if df is None:
            self.message = "agenda macro absent : " + str(path)
            return 0
        ct, cc = _col(df, "datetime_utc", "datetime", "time", "date"), _col(df, "currency", "country", "devise")
        ci, cti = _col(df, "impact"), _col(df, "title", "event", "titre")
        if ct is None or cc is None:
            self.message = "colonnes manquantes (datetime_utc, currency, impact, title)"
            return 0
        for _, r in df.iterrows():
            t = pd.to_datetime(str(r[ct]), errors="coerce", utc=True)
            if pd.isna(t):
                continue
            self.events.append(MacroEvent(t.tz_convert(None).to_pydatetime(), str(r[cc]).upper(),
                                          str(r[ci]) if ci else "", str(r[cti]) if cti else ""))
        self.events.sort(key=lambda e: e.utc)
        self.message = f"{len(self.events)} evenements macro charges"
        return len(self.events)

    def near(self, currencies, utc: datetime, minutes_before: int, minutes_after: int, min_impact: int):
        lo, hi = utc - timedelta(minutes=minutes_before), utc + timedelta(minutes=minutes_after)
        return [e for e in self.events if lo <= e.utc <= hi and e.level >= min_impact
                and (currencies is None or e.currency in currencies)]


# =============================================================================
#  Calendrier (NxCalendar)
# =============================================================================
def next_business_day(d, holidays=None, seven_days: bool = False) -> pd.Timestamp:
    n = pd.Timestamp(d).normalize() + pd.Timedelta(days=1)
    for _ in range(15):
        weekend = (not seven_days) and n.weekday() >= 5
        hol = holidays is not None and n in holidays
        if not weekend and not hol:
            return n
        n += pd.Timedelta(days=1)
    return n


def is_last_trading_day_of_month(d, holidays=None, seven_days=False) -> bool:
    return next_business_day(d, holidays, seven_days).month != pd.Timestamp(d).month


def week_start(d) -> pd.Timestamp:
    d = pd.Timestamp(d).normalize()
    return d - pd.Timedelta(days=d.weekday())


def is_last_trading_day_of_week(d, holidays=None, seven_days=False) -> bool:
    return week_start(next_business_day(d, holidays, seven_days)) != week_start(d)


def month_key(d) -> int:
    d = pd.Timestamp(d)
    return d.year * 12 + d.month


def week_key(d) -> int:
    return int((week_start(d) - pd.Timestamp(2000, 1, 3)).days // 7)


# =============================================================================
#  Donnees synthetiques (tests du moteur sans vraies cotations)
# =============================================================================
def synthetic_universe(symbols, start="2012-01-02", end="2025-12-31", seed: int = 7,
                       etfs=DEFAULT_ETFS) -> dict[str, pd.DataFrame]:
    """Univers synthetique realiste : facteur marche a regimes de vol (calme/neutre/stress),
    facteurs sectoriels, idiosyncratique a queues epaisses, derive de tendance lente.
    Crypto 7j/7, forex/CFD 5j/7, ^VIX derive de la vol du marche. Reproductible (graine)."""
    rng = np.random.default_rng(seed)
    bdays = pd.bdate_range(start, end)
    alldays = pd.date_range(start, end, freq="D")
    nd = len(alldays)
    # Regimes du marche (chaine de Markov sur jours calendaires).
    P = np.array([[0.995, 0.005, 0.0], [0.006, 0.990, 0.004], [0.0, 0.03, 0.97]])
    vols = np.array([0.10, 0.17, 0.38]) / math.sqrt(252)
    drift = np.array([0.12, 0.06, -0.25]) / 252
    st = np.zeros(nd, int)
    for t in range(1, nd):
        st[t] = rng.choice(3, p=P[st[t - 1]])
    mkt = drift[st] + vols[st] * rng.standard_t(5, nd) / math.sqrt(5 / 3)
    sectors = {k: rng.normal(0, 0.007, nd) for k in range(8)}
    out: dict[str, pd.DataFrame] = {}
    for j, sym in enumerate(symbols):
        ins = classify(sym, etfs)
        r_rng = np.random.default_rng(seed * 1000 + j)
        if ins.asset_class == "Crypto":
            beta, idio, mu = 1.6, 0.035, 0.0006
            days = alldays
        elif ins.asset_class in ("Forex",):
            beta, idio, mu = 0.05, 0.005, 0.0
            days = bdays
        elif ins.asset_class in ("Cfd", "Indice") and not sym.upper().startswith("^V"):
            beta, idio, mu = 1.0, 0.004, 0.0002
            days = bdays
        elif ins.asset_class == "Etf":
            beta, idio, mu = r_rng.uniform(0.7, 1.15), 0.004, 0.0001
            days = bdays
        else:
            beta, idio, mu = r_rng.uniform(0.7, 1.5), 0.013, r_rng.normal(0.0002, 0.0003)
            days = bdays
        sec = sectors[j % 8]
        trend = np.cumsum(r_rng.normal(0, 0.000003, nd))  # derive lente (un peu de momentum)
        r = mu + trend + beta * mkt + 0.6 * sec + idio * r_rng.standard_t(4, nd) / math.sqrt(2)
        if sym.upper() in ("^VIX", "^VXN"):
            rv = pd.Series(mkt).rolling(21, min_periods=5).std().bfill().to_numpy() * math.sqrt(252) * 100
            close = np.maximum(9.0, rv * 1.15 + r_rng.normal(0, 1.0, nd))
        else:
            up = sym.upper()
            if ins.asset_class == "Forex":
                level = 145.0 if up.endswith("JPY") else (1900.0 if up.startswith("XAU") else 0.7 + 0.6 * r_rng.random())
            elif ins.asset_class == "Cfd":
                level = 3000 + 12000 * r_rng.random()
            elif ins.asset_class == "Crypto":
                level = 30000.0 if up.startswith("BTC") else (2000.0 if up.startswith("ETH") else 0.1 + 100 * r_rng.random())
            else:
                level = 20 + 200 * r_rng.random()
            close = level * np.exp(np.cumsum(r) - r[0])
        s = pd.Series(close, index=alldays).reindex(days)
        c = s.to_numpy()
        prev = np.concatenate([[c[0]], c[:-1]])
        gap = r_rng.normal(0, 0.3, len(c)) * np.abs(np.log(c / prev))
        o = prev * np.exp(gap)
        spread = np.abs(r_rng.normal(0, 0.6, len(c))) * np.abs(np.log(c / prev)) + 0.002
        hi = np.maximum(o, c) * (1 + spread * r_rng.random(len(c)))
        lo = np.minimum(o, c) * (1 - spread * r_rng.random(len(c)))
        vol = r_rng.lognormal(16, 0.4, len(c))
        out[sym] = clean_ohlcv(pd.DataFrame({"open": o, "high": hi, "low": lo, "close": c, "volume": vol}, index=days))
    return out
