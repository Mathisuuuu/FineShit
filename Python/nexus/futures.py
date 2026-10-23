"""Futures : specifications des contrats, seances, detection des roulements et ajustement des prix.

Les contrats continus Databento ".v.0" (roulement au basculement du volume) ne sont PAS ajustes :
a chaque changement d echeance, le prix saute de l ecart entre les deux echeances (ex. ES le
13/03/2024 a 00:00 UTC : +63.25 points, soit +1.2 %). Sans correction, ces sauts faussent les
rendements (signaux 12-1, volatilite) et le PnL. Ce module :

  1. detecte les roulements :
       - EXACT si le fichier contient une colonne d identifiant de contrat
         (instrument_id, symbol, raw_symbol, contract...) ;
       - sinon par heuristique : Databento change d echeance a minuit UTC ; on cherche, dans la
         fenetre calendaire de roulement propre a chaque contrat, la frontiere de minuit UTC (entre
         deux minutes consecutives) dont le saut est le plus anormal par rapport au bruit minute ;
  2. ajuste les prix en arriere (proportionnel par defaut : les rendements sont exacts) ;
  3. agrege les minutes en barres journalieres de SEANCE (CME : 17:00 -> 16:00 heure de Chicago,
     la seance du dimanche soir appartient au lundi ; Eurex : jour calendaire de Francfort).

Les multiplicateurs "micro" (MES, MNQ, MGC, M6E...) permettent de dimensionner des positions
realistes sur un petit compte en gardant les prix des contrats standards.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class Contract:
    root: str
    name: str
    point_value: float          # devise par point de prix (contrat standard)
    tick_size: float
    currency: str
    exchange: str               # CME | EUREX
    schedule: str               # calendrier de roulement (voir ROLL_WINDOWS)
    micro_root: str = ""
    micro_point_value: float = 0.0


# Multiplicateurs : specifications officielles CME / Eurex (contrats standards et micros).
CONTRACTS: dict[str, Contract] = {c.root: c for c in [
    Contract("ES", "E-mini S&P 500", 50.0, 0.25, "USD", "CME", "trimestriel_indice", "MES", 5.0),
    Contract("NQ", "E-mini Nasdaq-100", 20.0, 0.25, "USD", "CME", "trimestriel_indice", "MNQ", 2.0),
    Contract("YM", "E-mini Dow", 5.0, 1.0, "USD", "CME", "trimestriel_indice", "MYM", 0.5),
    Contract("RTY", "E-mini Russell 2000", 50.0, 0.1, "USD", "CME", "trimestriel_indice", "M2K", 5.0),
    Contract("FDAX", "DAX", 25.0, 0.5, "EUR", "EUREX", "trimestriel_indice", "FDXS", 1.0),
    Contract("GC", "Or", 100.0, 0.1, "USD", "CME", "or", "MGC", 10.0),
    Contract("SI", "Argent", 5000.0, 0.005, "USD", "CME", "metaux_5", "SIL", 1000.0),
    Contract("HG", "Cuivre", 25000.0, 0.0005, "USD", "CME", "metaux_5", "MHG", 2500.0),
    Contract("CL", "Petrole WTI", 1000.0, 0.01, "USD", "CME", "mensuel_energie", "MCL", 100.0),
    Contract("NG", "Gaz naturel", 10000.0, 0.001, "USD", "CME", "mensuel_energie", "QG", 2500.0),
    Contract("6E", "EUR/USD", 125000.0, 0.00005, "USD", "CME", "trimestriel_devise", "M6E", 12500.0),
    Contract("6B", "GBP/USD", 62500.0, 0.0001, "USD", "CME", "trimestriel_devise", "M6B", 6250.0),
    Contract("6J", "JPY/USD", 12500000.0, 0.0000005, "USD", "CME", "trimestriel_devise", "MJY", 1250000.0),
    Contract("6A", "AUD/USD", 100000.0, 0.00005, "USD", "CME", "trimestriel_devise", "M6A", 10000.0),
    Contract("6C", "CAD/USD", 100000.0, 0.00005, "USD", "CME", "trimestriel_devise", "MCD", 10000.0),
    Contract("6S", "CHF/USD", 125000.0, 0.00005, "USD", "CME", "trimestriel_devise", "MSF", 12500.0),
    Contract("6N", "NZD/USD", 100000.0, 0.00005, "USD", "CME", "trimestriel_devise"),
    Contract("6M", "MXN/USD", 500000.0, 0.00001, "USD", "CME", "trimestriel_devise"),
    Contract("ZN", "T-Note 10 ans", 1000.0, 1 / 64, "USD", "CME", "obligataire", "", 0.0),
    Contract("ZB", "T-Bond 30 ans", 1000.0, 1 / 32, "USD", "CME", "obligataire"),
    Contract("ZF", "T-Note 5 ans", 1000.0, 1 / 128, "USD", "CME", "obligataire"),
    Contract("ZT", "T-Note 2 ans", 2000.0, 1 / 256, "USD", "CME", "obligataire"),
    Contract("ZC", "Mais", 50.0, 0.25, "USD", "CME", "cereales"),
    Contract("ZS", "Soja", 50.0, 0.25, "USD", "CME", "cereales"),
    Contract("ZW", "Ble", 50.0, 0.25, "USD", "CME", "cereales"),
]}

# Fenetres de roulement : (mois, jour_debut, jour_fin) ; jour_fin > 31 deborde sur le mois suivant.
# Calibrees sur les donnees (roulement au volume Databento) : indices autour de la 2e/3e semaine des
# mois trimestriels, devises la semaine d echeance, or fin janvier/mars/mai/juillet/novembre,
# energie chaque mois avant l echeance, taux et cereales fin de mois avant la livraison.
ROLL_WINDOWS: dict[str, list[tuple[int, int, int]]] = {
    "trimestriel_indice": [(m, 4, 24) for m in (3, 6, 9, 12)],
    "trimestriel_devise": [(m, 6, 24) for m in (3, 6, 9, 12)],
    "or": [(m, 20, 34) for m in (1, 3, 5, 7, 9, 11)],
    "metaux_5": [(m, 18, 34) for m in (2, 4, 6, 8, 11)],
    "mensuel_energie": [(m, 8, 27) for m in range(1, 13)],
    "obligataire": [(m, 18, 34) for m in (2, 5, 8, 11)],
    "cereales": [(m, 15, 34) for m in (2, 4, 6, 8, 11)],
}

ID_COLUMNS = ("instrument_id", "raw_symbol", "symbol", "contract", "contrat", "expiration", "echeance")


def contract_of(name: str) -> Contract | None:
    return CONTRACTS.get(str(name).upper().strip())


def session_spec(c: Contract | None) -> tuple[str, int]:
    """(fuseau, heure de debut de seance) : CME 17:00 Chicago, Eurex jour calendaire de Francfort."""
    if c is not None and c.exchange == "EUREX":
        return "Europe/Berlin", 0
    return "America/Chicago", 17


def trading_days(idx: pd.DatetimeIndex, c: Contract | None) -> pd.DatetimeIndex:
    """Jour de seance de chaque barre (UTC -> seance locale). CME : a partir de 17:00 = lendemain."""
    tz, start_hour = session_spec(c)
    if idx.tz is None:
        idx = idx.tz_localize("UTC")
    local = idx.tz_convert(tz)
    if start_hour:
        local = local + pd.Timedelta(hours=24 - start_hour)
    return pd.DatetimeIndex(local.tz_localize(None).normalize())


# =============================================================================
#  Detection des roulements
# =============================================================================
def _window_mask(days: pd.DatetimeIndex, schedule: str) -> np.ndarray:
    m = np.zeros(len(days), dtype=bool)
    for month, d0, d1 in ROLL_WINDOWS.get(schedule, []):
        for year in range(days.min().year - 1, days.max().year + 2):
            start = pd.Timestamp(year, month, 1) + pd.Timedelta(days=d0 - 1)
            end = pd.Timestamp(year, month, 1) + pd.Timedelta(days=d1 - 1)
            m |= (days >= start) & (days <= end)
    return m


def detect_rolls(df: pd.DataFrame, root: str, z_min: float = 6.0, abs_min: float = 0.0004,
                 max_pause_min: float = 120.0) -> pd.DataFrame:
    """Roulements d un contrat continu en barres minute. -> DataFrame(time, prev_close, new_open, jump, methode).

    Exact si une colonne d identifiant de contrat est presente ; sinon heuristique : au plus un roulement
    par fenetre calendaire, a la frontiere de minuit UTC la plus anormale (|saut| / bruit minute >= z_min).
    """
    cols = {c.lower(): c for c in df.columns}
    idcol = next((cols[c] for c in ID_COLUMNS if c in cols), None)
    o, c = df["open"].to_numpy(float), df["close"].to_numpy(float)
    idx = df.index
    if idcol is not None:
        ids = df[idcol].astype(str).to_numpy()
        chg = np.where(ids[1:] != ids[:-1])[0] + 1
        return pd.DataFrame({"time": idx[chg], "prev_close": c[chg - 1], "new_open": o[chg],
                             "jump": o[chg] / c[chg - 1] - 1, "methode": "identifiant"})
    if len(df) < 1000:
        return pd.DataFrame(columns=["time", "prev_close", "new_open", "jump", "methode"])
    utc = (idx.tz_convert("UTC") if idx.tz is not None else idx).as_unit("ns")
    day = utc.normalize()
    first = np.where(np.r_[False, day[1:] != day[:-1]])[0]
    pause = (utc.asi8[first] - utc.asi8[first - 1]) / 6e10
    jump = o[first] / c[first - 1] - 1
    lr = np.abs(np.diff(np.log(c)))
    step = np.diff(utc.asi8) / 6e10
    noise = float(np.median(lr[step <= 1.5])) if np.any(step <= 1.5) else float(np.median(lr))
    ctr = contract_of(root)
    sched = ctr.schedule if ctr else ""
    if ctr is not None and ctr.exchange == "EUREX":
        # Eurex est ferme a minuit UTC : le changement d echeance tombe dans le gap de nuit.
        # Bruit de reference = gap de nuit median ; seuil plus bas (z >= 4) car ce bruit est plus large.
        max_pause_min = max(max_pause_min, 300.0)
        night = np.abs(jump[(pause > 60) & (pause <= 300) & np.isfinite(jump)])
        noise = float(np.median(night)) if night.size >= 20 else noise
        z_min = min(z_min, 4.0)
    noise = max(noise, 1e-6)
    cand = (pause <= max_pause_min) & np.isfinite(jump)
    z = np.abs(jump) / noise
    rows = []
    if sched in ROLL_WINDOWS:
        inwin = _window_mask(pd.DatetimeIndex(day[first]).tz_localize(None) if day.tz is not None else pd.DatetimeIndex(day[first]), sched)
        # Un roulement par fenetre : on regroupe les candidats par (annee, mois de debut de fenetre).
        dts = pd.DatetimeIndex(day[first]).tz_localize(None) if day.tz is not None else pd.DatetimeIndex(day[first])
        groups: dict[tuple, list[int]] = {}
        for k in np.where(cand & inwin)[0]:
            d = dts[k]
            for month, d0, d1 in ROLL_WINDOWS[sched]:
                start = pd.Timestamp(d.year if not (month == 12 and d.month == 1) else d.year - 1, month, 1) + pd.Timedelta(days=d0 - 1)
                end = start + pd.Timedelta(days=d1 - d0)
                if start <= d <= end:
                    groups.setdefault((start.year, month), []).append(k)
                    break
        for _, ks in groups.items():
            best = max(ks, key=lambda k: z[k])
            if z[best] >= z_min and abs(jump[best]) >= abs_min:
                rows.append(best)
    else:
        rows = list(np.where(cand & (z >= max(z_min, 25.0)) & (np.abs(jump) >= 0.0015))[0])
    rows = sorted(rows)
    i = first[rows] if rows else np.array([], int)
    return pd.DataFrame({"time": idx[i], "prev_close": c[i - 1], "new_open": o[i],
                         "jump": o[i] / c[i - 1] - 1, "methode": "heuristique"})


def back_adjust(df: pd.DataFrame, rolls: pd.DataFrame, method: str = "proportionnel") -> pd.DataFrame:
    """Ajustement arriere des prix aux roulements. proportionnel (rendements exacts) | additif (points exacts) | aucun."""
    if method == "aucun" or rolls is None or rolls.empty:
        return df
    out = df.copy()
    px = ["open", "high", "low", "close"]
    pos = out.index.get_indexer(pd.DatetimeIndex(rolls["time"]))
    vals = np.array(out[px].to_numpy(float), dtype=float, copy=True)   # copie modifiable (pandas 3 : vues en lecture seule)
    for p, prev_c, new_o in sorted(zip(pos, rolls["prev_close"], rolls["new_open"]), key=lambda t: -t[0]):
        if p <= 0:
            continue
        if method == "additif":
            vals[:p] += (new_o - prev_c)
        else:
            vals[:p] *= new_o / prev_c
    out[px] = vals
    return out


# =============================================================================
#  Agregation en barres de seance
# =============================================================================
def to_session_bars(df: pd.DataFrame, root: str, minutes: int = 0) -> pd.DataFrame:
    """Barres journalieres de seance (minutes=0) ou barres de N minutes (horodatees en fin de barre, UTC naif)."""
    c = contract_of(root)
    if minutes and minutes > 0:
        x = df.copy()
        if x.index.tz is not None:
            x.index = x.index.tz_convert("UTC").tz_localize(None)
        r = x.resample(f"{int(minutes)}min", label="right", closed="right")
        out = pd.DataFrame({"open": r["open"].first(), "high": r["high"].max(), "low": r["low"].min(),
                            "close": r["close"].last(), "volume": r["volume"].sum()})
        return out.dropna(subset=["close"])
    days = trading_days(df.index, c)
    g = df.groupby(days)
    out = pd.DataFrame({"open": g["open"].first(), "high": g["high"].max(), "low": g["low"].min(),
                        "close": g["close"].last(), "volume": g["volume"].sum(), "n": g["close"].size()})
    out = out[out.index.dayofweek < 5]
    # Seances tronquees (ex. fragment isole) : moins de 5 % d une seance normale -> ignorees.
    med = out["n"].median() if len(out) else 0
    out = out[out["n"] >= max(1, 0.05 * med)].drop(columns="n")
    out.index.name = None
    return out


# =============================================================================
#  Lecture d un fichier Parquet de futures (avec cache disque)
# =============================================================================
def root_of(path: str, df: pd.DataFrame | None = None, manifest: dict | None = None) -> str:
    if df is not None and isinstance(getattr(df, "attrs", None), dict) and df.attrs.get("racine"):
        return str(df.attrs["racine"]).upper()
    if manifest:
        key = os.path.normcase(os.path.normpath(path))
        for k, v in manifest.items():
            if key.endswith(os.path.normcase(os.path.normpath(k))):
                return v.upper()
    base = os.path.basename(path).split(".")[0]
    head = base.split("_")[0].upper()
    return head


def load_manifest(folder: str) -> dict:
    """manifeste.json (generateur Databento du depot Cotations) : fichier relatif -> racine."""
    p = os.path.join(folder, "manifeste.json")
    if not os.path.exists(p):
        return {}
    try:
        with open(p, "r", encoding="utf-8") as fh:
            m = json.load(fh)
        return {s["fichier"]: s.get("racine", "") for s in m.get("series", []) if s.get("fichier")}
    except Exception:
        return {}


def read_futures_parquet(path: str, minutes: int = 0, adjust: str = "proportionnel", cache_dir: str | None = None,
                         manifest: dict | None = None, report: list | None = None):
    """-> (racine, DataFrame OHLCV de seance ajuste, roulements detectes)."""
    st = os.stat(path)
    key = f"{os.path.basename(path)}_{int(st.st_mtime)}_{st.st_size}_{minutes}_{adjust}_v2"
    if cache_dir:
        cp = os.path.join(cache_dir, key + ".parquet")
        rp = os.path.join(cache_dir, key + "_rolls.csv")
        if os.path.exists(cp) and os.path.exists(rp):
            out = pd.read_parquet(cp)
            rolls = pd.read_csv(rp, parse_dates=["time"])
            root = str(out.attrs.get("racine") or root_of(path, None, manifest))
            if report is not None:
                report.append((root, rolls))
            return root, out, rolls
    raw = pd.read_parquet(path)
    root = root_of(path, raw, manifest)
    if not isinstance(raw.index, pd.DatetimeIndex):
        tcol = next((c for c in raw.columns if c.lower() in ("ts_event", "timestamp", "time", "date", "datetime")), None)
        raw = raw.set_index(pd.to_datetime(raw[tcol], utc=True)).drop(columns=[tcol])
    if raw.index.tz is None:
        raw.index = raw.index.tz_localize("UTC")
    raw = raw.sort_index()
    raw = raw[~raw.index.duplicated(keep="last")]
    rolls = detect_rolls(raw, root)
    adj = back_adjust(raw[["open", "high", "low", "close", "volume"]], rolls, adjust)
    out = to_session_bars(adj, root, minutes)
    out.attrs["racine"] = root
    if cache_dir:
        os.makedirs(cache_dir, exist_ok=True)
        out.to_parquet(cp)
        rolls.to_csv(rp, index=False)
    if report is not None:
        report.append((root, rolls))
    return root, out, rolls
