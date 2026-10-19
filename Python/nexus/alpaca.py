"""Telechargement des donnees de marche Alpaca (https://data.alpaca.markets).

Cles : APCA_API_KEY_ID et APCA_API_SECRET_KEY (variables d environnement, .env.txt ou Python/keys.txt).
Offre gratuite : historique SIP disponible sauf les 15 dernieres minutes ; 200 requetes / minute.

    stock_bars(symboles, debut, fin, "1Day" | "1Min" | "15Min", ...)  -> {symbole: DataFrame}
    crypto_bars(symboles, debut, fin, timeframe)                       -> {symbole: DataFrame}
    crypto_taker_buy(symbole, debut, fin, minutes)                     -> volume acheteur agressif par barre

Convention d horodatage : barres journalieres indexees par la DATE de seance (America/New_York pour
les actions, UTC pour la crypto) ; barres intrajournalieres indexees par l heure de FIN de barre en UTC
(comme NinjaTrader), pour que le moteur ne voie une barre qu une fois close.
Garde-fou IEX (module C) : avec feed=iex, une barre dont la cloture devie de plus de 35 % de la mediane
des 5 precedentes est rejetee (cotations IEX hors seance aberrantes).
"""
from __future__ import annotations

import json
import os
import time
import urllib.parse

import numpy as np
import pandas as pd

from . import llm as L

DATA_URL = "https://data.alpaca.markets"
_TF_MINUTES = {"1Min": 1, "5Min": 5, "15Min": 15, "30Min": 30, "1Hour": 60}


class AlpacaError(RuntimeError):
    pass


def keys() -> tuple[str, str]:
    kid = L.resolve_secret("", "APCA_API_KEY_ID") or L.resolve_secret("", "ALPACA_API_KEY_ID") or L.resolve_secret("", "ALPACA_API_KEY")
    sec = (L.resolve_secret("", "APCA_API_SECRET_KEY") or L.resolve_secret("", "ALPACA_API_SECRET_KEY")
           or L.resolve_secret("", "ALPACA_SECRET_KEY"))
    if not kid or not sec:
        raise AlpacaError("cles Alpaca absentes : APCA_API_KEY_ID et APCA_API_SECRET_KEY (.env.txt ou variables d environnement)")
    return kid, sec


def _get(path: str, params: dict, auth: tuple[str, str] | None) -> dict:
    q = urllib.parse.urlencode({k: v for k, v in params.items() if v is not None}, safe="/,:")
    h = {"Accept": "application/json"}
    if auth:
        h.update({"APCA-API-KEY-ID": auth[0], "APCA-API-SECRET-KEY": auth[1]})
    body, status, err = L.http_request("GET", f"{DATA_URL}{path}?{q}", h, None, 60, attempts=5)
    if status != 200:
        raise AlpacaError(f"Alpaca HTTP {status} sur {path} : {L.one_line(body or err or '', 300)}")
    try:
        return json.loads(body)
    except ValueError as ex:
        raise AlpacaError(f"reponse Alpaca illisible : {ex}")


def _iso(t) -> str:
    ts = pd.Timestamp(t)
    if ts.tzinfo is None:
        ts = ts.tz_localize("UTC")
    return ts.tz_convert("UTC").strftime("%Y-%m-%dT%H:%M:%SZ")


def _paged(path: str, params: dict, key: str, auth, log=None):
    """Itere sur les pages (next_page_token) ; renvoie {symbole: [barres]}."""
    out: dict[str, list] = {}
    token, pages = None, 0
    while True:
        js = _get(path, {**params, "page_token": token}, auth)
        for sym, rows in (js.get(key) or {}).items():
            out.setdefault(sym, []).extend(rows or [])
        pages += 1
        token = js.get("next_page_token")
        if log and pages % 20 == 0:
            log(f"  ... {pages} pages, {sum(len(v) for v in out.values())} barres")
        if not token:
            return out
        time.sleep(0.31)                          # < 200 requetes / minute


def _frame(rows: list, timeframe: str, daily_tz: str) -> pd.DataFrame:
    if not rows:
        return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])
    df = pd.DataFrame(rows)
    t = pd.to_datetime(df["t"], utc=True)
    if timeframe.endswith("Day"):
        idx = pd.DatetimeIndex(t.dt.tz_convert(daily_tz).dt.tz_localize(None).dt.normalize())
    else:
        idx = pd.DatetimeIndex((t + pd.Timedelta(minutes=_TF_MINUTES.get(timeframe, 1))).dt.tz_convert("UTC").dt.tz_localize(None))
    out = pd.DataFrame({"open": df["o"].astype(float).values, "high": df["h"].astype(float).values,
                        "low": df["l"].astype(float).values, "close": df["c"].astype(float).values,
                        "volume": df["v"].astype(float).values}, index=idx)
    out = out[~out.index.duplicated(keep="last")].sort_index()
    return out


def iex_guard(df: pd.DataFrame, max_dev: float = 0.35) -> pd.DataFrame:
    """Garde-fou IEX du module C : rejette les barres qui devient de plus de 35 % de la mediane recente."""
    if df.empty:
        return df
    med = df["close"].rolling(5, min_periods=1).median().shift(1).fillna(df["close"])
    ok = (df["close"] / med - 1).abs() <= max_dev
    return df[ok]


def stock_bars(symbols, start, end=None, timeframe="1Day", feed="sip", adjustment="all", batch=20, log=print) -> dict:
    auth = keys()
    end = end or (pd.Timestamp.now(tz="UTC") - pd.Timedelta(minutes=20))
    res = {}
    syms = list(symbols)
    for i in range(0, len(syms), batch):
        chunk = syms[i:i + batch]
        if log:
            log(f"[alpaca] actions {timeframe} {', '.join(chunk)}")
        raw = _paged("/v2/stocks/bars", dict(symbols=",".join(chunk), timeframe=timeframe, start=_iso(start), end=_iso(end),
                                             limit=10000, adjustment=adjustment, feed=feed, sort="asc"), "bars", auth, log)
        for s in chunk:
            df = _frame(raw.get(s, []), timeframe, "America/New_York")
            res[s] = iex_guard(df) if feed == "iex" else df
    return res


def to_alpaca_crypto(sym: str) -> str:
    s = sym.upper().replace("-", "").replace("/", "")
    for q in ("USDT", "USDC", "USD"):
        if s.endswith(q):
            return s[: -len(q)] + "/" + q
    return s + "/USD"


def crypto_bars(symbols, start, end=None, timeframe="1Day", log=print) -> dict:
    auth = None
    try:
        auth = keys()
    except AlpacaError:
        pass                                     # la crypto est accessible sans cle
    end = end or pd.Timestamp.now(tz="UTC")
    res = {}
    for s in symbols:
        a = to_alpaca_crypto(s)
        if log:
            log(f"[alpaca] crypto {timeframe} {a}")
        raw = _paged("/v1beta3/crypto/us/bars", dict(symbols=a, timeframe=timeframe, start=_iso(start), end=_iso(end), limit=10000, sort="asc"),
                     "bars", auth, log)
        res[s] = bad_print_guard(_frame(raw.get(a, []), timeframe, "UTC"))
    return res


def crypto_taker_buy(symbol: str, start, end, minutes: int = 15, log=print) -> pd.Series:
    """Volume taker ACHETEUR par barre (fin de barre UTC) depuis les transactions (champ tks = B / S)."""
    auth = None
    try:
        auth = keys()
    except AlpacaError:
        pass
    a = to_alpaca_crypto(symbol)
    raw = _paged("/v1beta3/crypto/us/trades", dict(symbols=a, start=_iso(start), end=_iso(end), limit=10000, sort="asc"), "trades", auth, log)
    rows = raw.get(a, [])
    if not rows:
        return pd.Series(dtype=float)
    df = pd.DataFrame(rows)
    t = pd.to_datetime(df["t"], utc=True).dt.tz_convert("UTC").dt.tz_localize(None)
    span = pd.Timedelta(minutes=minutes)
    ends = t.dt.floor(span) + span
    buy = np.where(df.get("tks", pd.Series([""] * len(df))).astype(str).str.upper() == "B", df["s"].astype(float), 0.0)
    return pd.Series(buy, index=ends).groupby(level=0).sum()


def save_csv(df: pd.DataFrame, path: str, intraday: bool):
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    out = df.copy()
    out.index.name = "Date"
    fmt = "%Y-%m-%d %H:%M:%S" if intraday else "%Y-%m-%d"
    out.index = out.index.strftime(fmt)
    out.rename(columns={"open": "Open", "high": "High", "low": "Low", "close": "Close", "volume": "Volume"}).to_csv(path)


def minutes_cache(sym: str, start="2016-01-01", end=None, cache_dir: str | None = None, log=print) -> str:
    """Barres 1 minute d une action / d un ETF (SIP, ajustees), mises en cache dans .cache/alpaca_minute/<SYM>.parquet
    au format du moteur intrajournalier (index = heure de FIN de barre, UTC naif). Annee par annee, reprise possible."""
    cache_dir = cache_dir or os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".cache", "alpaca_minute")
    os.makedirs(cache_dir, exist_ok=True)
    path = os.path.join(cache_dir, f"{sym.upper()}.parquet")
    have = pd.read_parquet(path) if os.path.exists(path) else None
    debut = pd.Timestamp(start) if have is None or have.empty else have.index.max().normalize()
    fin = pd.Timestamp(end) if end else pd.Timestamp.now().normalize()
    morceaux = [] if have is None else [have]
    for a in range(debut.year, fin.year + 1):
        d0, d1 = max(debut, pd.Timestamp(f"{a}-01-01")), min(fin, pd.Timestamp(f"{a + 1}-01-01"))
        if d0 >= d1:
            continue
        df = stock_bars([sym], d0, d1, timeframe="1Min", log=None)[sym]
        log(f"[alpaca] {sym} 1 min {a} : {len(df)} barres")
        morceaux.append(df)
        out = pd.concat(morceaux)
        out = out[~out.index.duplicated(keep="last")].sort_index()
        out.to_parquet(path)
    return path


def download_for_strategies(codes, quotes_dir: str, start="2016-01-01", log=print) -> dict:
    """Cotations journalieres Alpaca des actions / ETF / crypto des fiches Nexus (univers + references)."""
    from . import data as D
    from .engine import split_list
    from .strategies import get
    stocks, cryptos = set(), set()
    for code in codes:
        st = get(code)()
        for s in split_list(st.p.symbols) + list(st.required_references()) + split_list(st.p.reference_symbols):
            ins = D.classify(s)
            if ins.asset_class in ("Action", "Etf"):
                stocks.add(s.upper())
            elif ins.asset_class == "Crypto":
                cryptos.add(s.upper())
    done = {}
    if stocks:
        for s, df in stock_bars(sorted(stocks), start, timeframe="1Day", log=log).items():
            if len(df):
                save_csv(df, os.path.join(quotes_dir, "alpaca", "actions_jour", f"{s}.csv"), False)
                done[s] = len(df)
            elif log:
                log(f"[alpaca] {s} : aucune donnee")
    for s, df in crypto_bars(sorted(cryptos), max(pd.Timestamp(start), pd.Timestamp("2015-01-01")), timeframe="1Day", log=log).items():
        if len(df):
            save_csv(df, os.path.join(quotes_dir, "alpaca", "crypto_jour", f"{s}.csv"), False)
            done[s] = len(df)
    return done


def bad_print_guard(df: pd.DataFrame, max_wick: float = 0.5, max_jump: float = 3.0) -> pd.DataFrame:
    """Cotations aberrantes (plateformes crypto peu liquides) : meche a plus de 50 % au-dela du corps de la barre
    ramenee au corps ; barre dont la cloture saute d un facteur 3 puis revient a la barre suivante supprimee."""
    if df.empty:
        return df
    out = df.copy()
    body_hi = np.maximum(out["open"], out["close"])
    body_lo = np.minimum(out["open"], out["close"])
    out["high"] = np.where(out["high"] > body_hi * (1 + max_wick), body_hi, out["high"])
    out["low"] = np.where(out["low"] < body_lo / (1 + max_wick), body_lo, out["low"])
    c = out["close"]
    lj = np.log(c / c.shift(1)).abs()
    back = np.log(c.shift(-1) / c.shift(1)).abs()
    spike = (lj > np.log(max_jump)) & (back < np.log(1.5))
    return out[~spike.fillna(False)]
