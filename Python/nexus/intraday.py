"""Barres 1 minute et seance cash US (9:30-16:00 heure de New York) pour les fiches intrajournalieres.

  - prepare_minutes : conversion du fuseau des donnees vers New York, horodatage "fin de barre"
    (la barre 9:30-9:31 est datee 9:31, comme les exports NinjaTrader) ;
  - build_grid      : matrices jours x 390 minutes (open, high, low, close, volume) de la seance
    cash, demi-seances (13:00) et jours incomplets reperes ;
  - slot_mean_prev  : moyenne glissante, minute par minute, sur les N jours PRECEDENTS (jour courant exclu) ;
  - synthetic_minutes : marche minute synthetique (bruit, ou momentum intrajournalier plante).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

NY = "America/New_York"
SESSION_MINUTES = 390            # 9:30 -> 16:00
HALF_DAY_LAST_SLOT = 209         # barre 12:59-13:00 (cloture des demi-seances NYSE)
FULL_DAY_MIN_LAST_SLOT = 385     # barres presentes au moins jusqu a 15:56 -> seance complete
HALF_DAY_MIN_LAST_SLOT = 205     # jusqu a 12:56 au moins et rien apres 15:00 -> demi-seance
MAX_FIRST_SLOT = 4               # premiere barre au plus tard a 9:35, sinon jour incomplet


def slot_time(slot: int) -> str:
    """Heure de fin (New York) de la barre d indice slot (0 -> 09:31, 389 -> 16:00)."""
    m = 9 * 60 + 30 + int(slot) + 1
    return f"{m // 60:02d}:{m % 60:02d}"


def minute_of_day(idx: pd.DatetimeIndex) -> np.ndarray:
    return (idx.hour * 60 + idx.minute).to_numpy()


def is_intraday(df: pd.DataFrame) -> bool:
    idx = pd.DatetimeIndex(df.index)
    return len(idx) > 1 and bool((idx != idx.normalize()).any()) and bool(idx.normalize().duplicated().any())


def to_new_york(df: pd.DataFrame, tz: str | None) -> pd.DataFrame:
    """Convertit l index vers l heure de New York (naive). tz = fuseau des donnees (None ou New York = deja bon).
    Les heures ambigues ou inexistantes des changements d heure (la nuit) sont supprimees."""
    if df.empty:
        return df
    idx = pd.DatetimeIndex(df.index)
    if idx.tz is None and (tz is None or tz in (NY, "US/Eastern", "ET")):
        return df
    if idx.tz is None:
        idx = idx.tz_localize(tz, ambiguous="NaT", nonexistent="NaT")
    out = df.copy()
    out.index = idx.tz_convert(NY).tz_localize(None)
    out = out[~out.index.isna()]
    return out[~out.index.duplicated(keep="last")].sort_index()


def detect_bar_label(df: pd.DataFrame) -> tuple[str, str]:
    """'debut' (barre 9:30-9:31 datee 9:30) ou 'fin' (datee 9:31, NinjaTrader). -> (label, explication).
    Indices : seance cash seule (9:30 present et 16:00 absent, ou l inverse), sinon pic de volume de
    l ouverture (la premiere minute cash est la plus active)."""
    idx = pd.DatetimeIndex(df.index)
    mod = minute_of_day(idx)
    days = max(1, idx.normalize().nunique())
    n930, n1600 = int((mod == 570).sum()), int((mod == 960).sum())
    n0900, n1700 = int(((mod >= 480) & (mod < 570)).sum()), int(((mod > 960) & (mod <= 1020)).sum())
    if n0900 + n1700 < days * 0.5:                       # seance cash seule
        if n930 > 0.5 * days and n1600 < 0.05 * days:
            return "debut", "seance cash seule : barres 9:30 presentes, 16:00 absentes"
        if n1600 > 0.5 * days and n930 < 0.05 * days:
            return "fin", "seance cash seule : barres 16:00 presentes, 9:30 absentes"
    if "volume" in df and np.nansum(df["volume"].to_numpy(float)) > 0:
        # Saut de volume a l ouverture cash : sur la barre datee 9:30 si horodatage debut, 9:31 si fin.
        v = pd.Series(df["volume"].to_numpy(float), index=idx)
        day = idx.normalize()
        by = {m: pd.Series(v.to_numpy()[mod == m], index=day[mod == m]) for m in (569, 570, 571)}
        common = by[569].index.intersection(by[570].index).intersection(by[571].index)
        common = common[~common.duplicated()]
        if len(common) > 10:
            a, b, c = (by[m][~by[m].index.duplicated()].reindex(common).to_numpy() for m in (569, 570, 571))
            with np.errstate(divide="ignore", invalid="ignore"):
                j930 = float(np.nanmedian((b + 1) / (a + 1)))
                j931 = float(np.nanmedian((c + 1) / (b + 1)))
            if j930 > 2 * j931:
                return "debut", f"saut de volume sur la barre datee 9:30 (x{j930:.1f} contre x{j931:.1f} a 9:31)"
            if j931 > 2 * j930:
                return "fin", f"saut de volume sur la barre datee 9:31 (x{j931:.1f} contre x{j930:.1f} a 9:30)"
    return "fin", "indetermine : horodatage fin de barre suppose (convention NinjaTrader)"


def prepare_minutes(df: pd.DataFrame, tz: str | None = NY, bar_label: str = "auto") -> tuple[pd.DataFrame, str]:
    """Barres minute en heure de New York, horodatees en fin de barre. -> (DataFrame, note)."""
    out = to_new_york(df, tz)
    label, why = (bar_label, "impose") if bar_label in ("debut", "fin") else detect_bar_label(out)
    if label == "debut":
        out = out.copy()
        out.index = pd.DatetimeIndex(out.index) + pd.Timedelta(minutes=1)
    return out, f"horodatage '{label}' de barre ({why})"


class SessionGrid:
    """Seance cash en matrices (jours x 390). Colonne j = barre qui se termine a 9:31 + j minutes.
    Minutes manquantes dans la seance : barre plate au dernier prix (volume 0). Au-dela de la fin de seance : NaN."""

    def __init__(self, days, o, h, l, c, v, last_slot, valid, half_day, first_slot):
        self.days = pd.DatetimeIndex(days)
        self.o, self.h, self.l, self.c, self.v = o, h, l, c, v
        self.last_slot = last_slot
        self.valid = valid
        self.half_day = half_day
        self.first_slot = first_slot
        self.n_days = len(self.days)

    @property
    def day_open(self) -> np.ndarray:
        return self.o[:, 0]

    @property
    def day_close(self) -> np.ndarray:
        """Cloture de la seance cash (16:00, ou 13:00 les demi-seances)."""
        return self.c[np.arange(self.n_days), np.maximum(self.last_slot, 0)]

    def timestamps(self, d: int, slots) -> pd.DatetimeIndex:
        return self.days[d] + pd.to_timedelta(9 * 60 + 30 + np.asarray(slots) + 1, unit="min")


def build_grid(df: pd.DataFrame) -> SessionGrid:
    """df : barres minute en heure de New York, horodatees en fin de barre (voir prepare_minutes)."""
    idx = pd.DatetimeIndex(df.index)
    mod = minute_of_day(idx)
    keep = (mod > 570) & (mod <= 960) & (idx.dayofweek < 5)
    idx, mod = idx[keep], mod[keep]
    if len(idx) == 0:
        raise ValueError("aucune barre dans la seance cash 9:30-16:00 (New York) : verifier le fuseau des donnees")
    sub = df.loc[keep]
    slot = mod - 571
    day_codes, days = pd.factorize(idx.normalize(), sort=True)
    D, S = len(days), SESSION_MINUTES
    mats = {}
    for k in ("open", "high", "low", "close", "volume"):
        m = np.full((D, S), np.nan)
        m[day_codes, slot] = sub[k].to_numpy(float)
        mats[k] = m
    present = np.isfinite(mats["close"])
    any_bar = present.any(axis=1)
    first_slot = np.where(any_bar, present.argmax(axis=1), -1)
    last_present = np.where(any_bar, S - 1 - present[:, ::-1].argmax(axis=1), -1)
    after_15 = present[:, 330:].any(axis=1)
    full = last_present >= FULL_DAY_MIN_LAST_SLOT
    half = (~full) & (~after_15) & (last_present >= HALF_DAY_MIN_LAST_SLOT)
    last_slot = np.where(full, S - 1, np.where(half, HALF_DAY_LAST_SLOT, last_present))
    valid = any_bar & (first_slot >= 0) & (first_slot <= MAX_FIRST_SLOT) & (full | half)
    # Remplissage dans la seance : close -> dernier close connu ; open/high/low -> ce close ; volume 0.
    c = pd.DataFrame(mats["close"]).ffill(axis=1).to_numpy()
    first_open = np.where(any_bar, mats["open"][np.arange(D), np.maximum(first_slot, 0)], np.nan)
    c = np.where(np.isnan(c), first_open[:, None], c)           # minutes avant la premiere barre
    o = np.where(present, mats["open"], c)
    o[:, 0] = np.where(present[:, 0], mats["open"][:, 0], first_open)
    h = np.where(present, mats["high"], np.maximum(o, c))
    lo = np.where(present, mats["low"], np.minimum(o, c))
    v = np.where(present, np.nan_to_num(mats["volume"]), 0.0)
    beyond = np.arange(S)[None, :] > last_slot[:, None]
    for m in (o, h, lo, c, v):
        m[beyond] = np.nan
        m[~valid] = np.nan
    return SessionGrid(days, o, h, lo, c, v, last_slot.astype(np.int64), valid, half & valid, first_slot)


def slot_mean_prev(x: np.ndarray, n: int) -> np.ndarray:
    """Pour chaque colonne : moyenne des n dernieres valeurs disponibles STRICTEMENT avant la ligne courante
    (NaN tant que moins de n valeurs). Le jour courant n entre jamais dans sa propre moyenne."""
    out = np.full_like(x, np.nan, dtype=float)
    n = int(n)
    for j in range(x.shape[1]):
        col = x[:, j]
        ok = np.flatnonzero(np.isfinite(col))
        if len(ok) <= n:
            continue
        cs = np.concatenate([[0.0], np.cumsum(col[ok])])
        k = np.arange(n, len(ok))                  # rang de la ligne courante parmi les lignes disponibles
        out[ok[k], j] = (cs[k] - cs[k - n]) / n
    return out


def session_vwap(g: SessionGrid) -> np.ndarray:
    """VWAP cumule de la seance cash (prix typique (H+L+C)/3), NaN tant qu aucun volume."""
    tp = (g.h + g.l + g.c) / 3.0
    v = np.nan_to_num(g.v)
    num = np.cumsum(np.nan_to_num(tp) * v, axis=1)
    den = np.cumsum(v, axis=1)
    with np.errstate(invalid="ignore", divide="ignore"):
        out = np.where(den > 0, num / den, np.nan)
    out[np.isnan(g.c)] = np.nan
    return out


# =============================================================================
#  Donnees synthetiques
# =============================================================================
def synthetic_minutes(start="2019-01-02", end="2024-12-31", seed: int = 7, momentum: float = 0.0,
                      price0: float = 300.0, daily_vol: float = 0.011, extended_hours: bool = False) -> pd.DataFrame:
    """Barres 1 minute synthetiques (heure de New York, horodatage fin de barre).
    momentum > 0 plante un momentum intrajournalier : derive proportionnelle a tanh(mouvement depuis
    l ouverture / vol attendue), d autant plus forte que le prix sort de sa zone habituelle.
    extended_hours : ajoute des barres hors seance (8:00-9:30 et 16:00-17:00) comme un future."""
    rng = np.random.default_rng(seed)
    days = pd.bdate_range(start, end)
    D, S = len(days), SESSION_MINUTES
    lv = np.zeros(D)
    for i in range(1, D):                                    # log-vol AR(1) -> grappes de volatilite
        lv[i] = 0.97 * lv[i - 1] + 0.18 * rng.standard_normal()
    vol_d = daily_vol * np.exp(lv - lv.std() ** 2 / 2)
    t = (np.arange(S) + 0.5) / S
    shape = 1.0 + 1.6 * (t - 0.5) ** 2 * 4                    # profil en U de la volatilite intrajournaliere
    shape = shape / np.sqrt((shape ** 2).mean())
    sig = (vol_d[:, None] * np.sqrt(0.75) / np.sqrt(S)) * shape[None, :]
    gap = vol_d * np.sqrt(0.25) * rng.standard_normal(D)
    r = np.empty((D, S))
    cum = np.zeros(D)
    for j in range(S):
        z = cum / (vol_d * np.sqrt(0.75 * (j + 1) / S))
        r[:, j] = sig[:, j] * (rng.standard_normal(D) + momentum * np.tanh(z / 1.5))
        cum += r[:, j]
    day_open_log = np.log(price0) + np.cumsum(gap + np.r_[0.0, r.sum(axis=1)[:-1]])
    close_log = day_open_log[:, None] + np.cumsum(r, axis=1)
    open_log = np.concatenate([day_open_log[:, None], close_log[:, :-1]], axis=1)
    open_log[:, 1:] += 0.15 * sig[:, 1:] * rng.standard_normal((D, S - 1))   # l ouverture differe de la cloture precedente
    c, o = np.exp(close_log), np.exp(open_log)
    wick = np.abs(rng.standard_normal((D, S))) * sig * 0.5
    h = np.maximum(o, c) * np.exp(wick)
    lo = np.minimum(o, c) * np.exp(-np.abs(rng.standard_normal((D, S))) * sig * 0.5)
    vol_shape = 1.0 + 6.0 * np.exp(-np.arange(S) / 8.0) + 2.5 * np.exp(-(S - 1 - np.arange(S)) / 10.0)
    v = np.round(1000 * vol_shape[None, :] * rng.lognormal(0, 0.3, (D, S)))
    ts = (days.values[:, None] + (np.arange(S)[None, :] + 571) * np.timedelta64(1, "m")).ravel()
    df = pd.DataFrame({"open": o.ravel(), "high": h.ravel(), "low": lo.ravel(), "close": c.ravel(), "volume": v.ravel()},
                      index=pd.DatetimeIndex(ts))
    if extended_hours:
        extra = []
        for d in range(D):
            p_prev = c[d - 1, -1] if d > 0 else o[d, 0]
            pre = np.linspace(p_prev, o[d, 0], 90)
            post = np.full(60, c[d, -1])
            tpre = days[d] + pd.to_timedelta(np.arange(481, 571), unit="min")
            tpost = days[d] + pd.to_timedelta(np.arange(961, 1021), unit="min")
            extra.append(pd.DataFrame({"open": pre, "high": pre, "low": pre, "close": pre, "volume": 200.0}, index=tpre))
            extra.append(pd.DataFrame({"open": post, "high": post, "low": post, "close": post, "volume": 100.0}, index=tpost))
        df = pd.concat([df] + extra).sort_index()
    return df
