"""Actualites et donnees d evenements (port de NexusData.cs / NxText) : fiches 7, 8, 9, 10.

    normalize / tokens / jaccard / hash10   meme normalisation et meme hachage que le C# (NxText),
                                            pour partager les caches de reponses LLM et FinBERT
    NewsItem, NewsStore                     titres par symbole, dedoublonnage : un meme evenement repris
                                            par plusieurs sources = 1 seul titre (Jaccard >= 0.6 sur 24 h)
    FearGreed                               indice Fear & Greed crypto (alternative.me), cache disque
    next_session_begin_utc                  debut de la seance suivante (horodatage des titres, fiche 7)

Toutes les dates d evenements sont en UTC ; une date SANS fuseau dans un CSV est consideree comme UTC.
"""
from __future__ import annotations

import bisect
import hashlib
import os
import threading
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

import pandas as pd

from . import data as D

_STOP = {"the", "a", "an", "of", "to", "in", "on", "for", "and", "or", "is", "are", "at", "by", "with", "as", "its",
         "it", "from", "after", "le", "la", "les", "de", "des", "du", "et"}


# =============================================================================
#  Texte (NxText)
# =============================================================================
def normalize(s: str | None) -> str:
    """Minuscules, tout caractere non alphanumerique -> espace, espaces multiples reduits."""
    if not s:
        return ""
    return " ".join("".join(c if c.isalnum() else " " for c in s.lower()).split())


def tokens(s: str | None) -> frozenset:
    return frozenset(t for t in normalize(s).split(" ") if len(t) > 1 and t not in _STOP)


def jaccard(a, b) -> float:
    if not a or not b:
        return 0.0
    inter = len(a & b)
    uni = len(a) + len(b) - inter
    return inter / uni if uni > 0 else 0.0


def hash10(s: str | None) -> str:
    """SHA-1, 10 premiers octets en hexadecimal (20 caracteres) : NxText.Hash."""
    return hashlib.sha1((s or "").encode("utf-8")).hexdigest()[:20]


def one_line(s: str | None, max_len: int = 300) -> str:
    if s is None:
        return ""
    v = s.replace("\r", " ").replace("\n", " ").strip()
    return v[:max_len]


def read_csv_hash_lines(path: str) -> pd.DataFrame | None:
    """CSV dont les lignes commencant par # sont ignorees (un # au milieu d un titre est conserve)."""
    import io
    if not path or not os.path.exists(path):
        return None
    with open(path, encoding="utf-8-sig", errors="replace") as f:
        txt = "".join(l for l in f if not l.lstrip().startswith("#") and l.strip())
    if not txt:
        return None
    try:
        df = pd.read_csv(io.StringIO(txt), dtype=str, keep_default_na=False)
    except Exception:
        return None
    df.columns = [c.strip().lower() for c in df.columns]
    return df if len(df) else None


def to_utc(t) -> datetime:
    """Horodatage -> datetime UTC naif (une date sans fuseau est consideree comme UTC)."""
    ts = pd.Timestamp(t)
    if ts.tzinfo is not None:
        ts = ts.tz_convert("UTC").tz_localize(None)
    return ts.to_pydatetime()


# =============================================================================
#  Titres
# =============================================================================
@dataclass
class NewsItem:
    published_utc: datetime
    symbol: str
    source: str = ""
    headline: str = ""
    url: str = ""
    _tokens: frozenset | None = field(default=None, repr=False, compare=False)

    @property
    def tokens(self) -> frozenset:
        if self._tokens is None:
            self._tokens = tokens(self.headline)
        return self._tokens

    @property
    def key(self) -> str:
        return hash10(self.symbol.upper() + "|" + normalize(self.headline))

    @property
    def is_social(self) -> bool:
        """Reddit et reseaux sociaux : pas des nouvelles d entreprise (fiche 7)."""
        s = (self.source or "").lower()
        return any(k in s for k in ("reddit", "twitter", "stocktwits", "social"))

    CSV_HEADER = "published_utc,symbol,source,headline,url"

    def to_csv_row(self) -> list:
        return [self.published_utc.strftime("%Y-%m-%dT%H:%M:%SZ"), self.symbol, self.source, one_line(self.headline, 500), self.url]


class NewsStore:
    """Titres par symbole, tries par date, dedoublonnes (meme cle ou meme evenement repris ailleurs)."""

    def __init__(self, dedup_jaccard: float = 0.6, dedup_window_hours: float = 24.0):
        self.dedup_jaccard = dedup_jaccard
        self.dedup_window = timedelta(hours=dedup_window_hours)
        self.by_symbol: dict[str, list[NewsItem]] = {}
        self._times: dict[str, list[datetime]] = {}
        self.keys: set[str] = set()
        self.duplicates = 0
        self._lock = threading.Lock()

    @property
    def count(self) -> int:
        return sum(len(v) for v in self.by_symbol.values())

    def load_csv(self, path: str | None, only_symbols=None) -> tuple[int, str]:
        """CSV : published_utc, symbol, source, headline [, url]. -> (titres retenus, message)."""
        if not path or not os.path.exists(path):
            return 0, f"fichier d actualites introuvable : {path}"
        df = read_csv_hash_lines(path)
        if df is None or df.empty:
            return 0, f"aucun titre dans {os.path.basename(path)}"
        ct = D._col(df, "published_utc", "datetime_utc", "datetime", "published", "time", "date", "timestamp")
        cs = D._col(df, "symbol", "ticker", "symbole")
        cso = D._col(df, "source")
        chl = D._col(df, "headline", "title", "titre")
        cu = D._col(df, "url", "link")
        if ct is None or cs is None or chl is None:
            return 0, "colonnes requises : published_utc, symbol, headline (source, url optionnelles)"
        filt = {x.upper() for x in only_symbols} if only_symbols is not None else None
        times = pd.to_datetime(df[ct].astype(str), errors="coerce", utc=True)
        bad = int(times.isna().sum())
        df = df.assign(tparsed=times).dropna(subset=["tparsed"]).sort_values("tparsed", kind="stable")
        added = 0
        dup0 = self.duplicates
        for row in df.itertuples(index=False):
            sym = str(getattr(row, cs)).strip()
            if not sym or (filt is not None and sym.upper() not in filt):
                continue
            it = NewsItem(row.tparsed.tz_convert("UTC").tz_localize(None).to_pydatetime(), sym,
                          getattr(row, cso) if cso is not None else "csv", getattr(row, chl), getattr(row, cu) if cu is not None else "")
            if self.add(it):
                added += 1
        return added, (f"{added} titres charges ({self.duplicates - dup0} doublons, {bad} dates illisibles) "
                       f"depuis {os.path.basename(path)}")

    def add(self, it: NewsItem) -> bool:
        """Ajoute un titre ; False si doublon (meme cle, ou meme evenement repris par une autre source)."""
        if it is None or not (it.headline or "").strip() or not (it.symbol or "").strip():
            return False
        with self._lock:
            k = it.key
            if k in self.keys:
                self.duplicates += 1
                return False
            sym = it.symbol.upper()
            lst = self.by_symbol.setdefault(sym, [])
            tms = self._times.setdefault(sym, [])
            lo = bisect.bisect_left(tms, it.published_utc - self.dedup_window)
            hi = bisect.bisect_right(tms, it.published_utc + self.dedup_window)
            for o in lst[lo:hi]:
                if jaccard(o.tokens, it.tokens) >= self.dedup_jaccard:
                    self.duplicates += 1
                    return False
            self.keys.add(k)
            pos = bisect.bisect_right(tms, it.published_utc)
            tms.insert(pos, it.published_utc)
            lst.insert(pos, it)
            return True

    def get(self, symbol: str, from_utc_exclusive: datetime, to_utc_inclusive: datetime, include_social: bool) -> list[NewsItem]:
        """Titres de ]from ; to] pour un symbole."""
        with self._lock:
            sym = symbol.upper()
            tms = self._times.get(sym)
            if not tms:
                return []
            lo = bisect.bisect_right(tms, from_utc_exclusive)
            hi = bisect.bisect_right(tms, to_utc_inclusive)
            return [x for x in self.by_symbol[sym][lo:hi] if include_social or not x.is_social]

    def has_symbol(self, symbol: str) -> bool:
        return symbol.upper() in self.by_symbol

    def append_csv(self, path: str, items: list[NewsItem]):
        """Ajoute des titres a un CSV (cree avec l en-tete si besoin)."""
        if not items:
            return
        new = not os.path.exists(path)
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        pd.DataFrame([i.to_csv_row() for i in items], columns=NewsItem.CSV_HEADER.split(",")).to_csv(
            path, mode="a", header=new, index=False)


# =============================================================================
#  Fear & Greed crypto (alternative.me, l indice affiche par CoinGecko)
# =============================================================================
class FearGreed:
    URL = "https://api.alternative.me/fng/?limit=0&format=json"

    def __init__(self, cache_path: str | None = None):
        if cache_path is None:
            from .llm import cache_dir
            cache_path = os.path.join(cache_dir(), "fear_greed.csv")
        self.cache_path = cache_path
        self.values: dict[pd.Timestamp, int] = {}
        self.labels: dict[pd.Timestamp, str] = {}
        self._days: list[pd.Timestamp] = []

    @property
    def count(self) -> int:
        return len(self.values)

    def _reindex(self):
        self._days = sorted(self.values)

    def load_cache(self, extra_paths=()) -> int:
        for p in [self.cache_path, *extra_paths]:
            df = D._read_csv_comments(p) if p and os.path.exists(p) else None
            if df is None:
                continue
            cd, cv, cl = D._col(df, "date"), D._col(df, "value"), D._col(df, "label")
            if cd is None or cv is None:
                continue
            for d, v, l in zip(pd.to_datetime(df[cd], errors="coerce"), pd.to_numeric(df[cv], errors="coerce"),
                               df[cl] if cl is not None else [""] * len(df)):
                if pd.isna(d) or pd.isna(v):
                    continue
                self.values[d.normalize()] = int(v)
                self.labels[d.normalize()] = l if isinstance(l, str) else ""
        self._reindex()
        return self.count

    def refresh(self, url: str | None = None) -> tuple[bool, str | None]:
        """Telecharge l historique complet et met a jour le cache. Appel bloquant."""
        from .llm import http_request
        import json
        body, status, err = http_request("GET", url or self.URL, None, None, 20)
        if body is None or status != 200:
            return False, err or f"HTTP {status}"
        try:
            data = json.loads(body).get("data")
        except ValueError:
            return False, "JSON Fear&Greed illisible"
        if not isinstance(data, list):
            return False, "champ data absent"
        for o in data:
            try:
                d = pd.Timestamp(datetime.fromtimestamp(float(o["timestamp"]), tz=timezone.utc).date())
                self.values[d] = int(float(o["value"]))
                self.labels[d] = o.get("value_classification") or ""
            except (KeyError, TypeError, ValueError):
                continue
        self._reindex()
        os.makedirs(os.path.dirname(os.path.abspath(self.cache_path)), exist_ok=True)
        pd.DataFrame({"date": [d.strftime("%Y-%m-%d") for d in self._days],
                      "value": [self.values[d] for d in self._days],
                      "label": [self.labels.get(d, "") for d in self._days]}).to_csv(self.cache_path, index=False)
        return True, None

    def get(self, day_utc) -> tuple[int, str] | None:
        """Valeur publiee pour le jour UTC donne ou le dernier jour connu avant (pas d information future)."""
        if not self._days:
            return None
        d = pd.Timestamp(day_utc).normalize()
        i = bisect.bisect_right(self._days, d) - 1
        if i < 0:
            return None
        k = self._days[i]
        return self.values[k], self.labels.get(k, "")


# =============================================================================
#  Horodatage : debut de la seance suivante
# =============================================================================
def next_session_begin_utc(s, trading_day) -> datetime:
    """Debut (UTC) de la premiere seance qui suit le jour de bourse donne.

    Actions / ETF : 09:30 New York le jour ouvre suivant (jours feries du symbole respectes) ;
    crypto (7 j / 7) : minuit UTC le lendemain ; futures : ouverture de la seance suivante
    (CME 17:00 Chicago la veille, Eurex minuit Berlin)."""
    day = pd.Timestamp(trading_day).normalize()
    nd = D.next_business_day(day, s.holidays, s.seven_days)
    if s.seven_days:
        return nd.to_pydatetime()
    if s.asset_class == "Future":
        from . import futures as F
        tz, hour = F.session_spec(F.contract_of(s.name))
        start_day = nd - pd.Timedelta(days=1) if hour > 0 else nd
        local = pd.Timestamp(start_day.year, start_day.month, start_day.day, hour).tz_localize(tz)
    else:
        local = pd.Timestamp(nd.year, nd.month, nd.day, 9, 30).tz_localize("America/New_York")
    return local.tz_convert("UTC").tz_localize(None).to_pydatetime()
