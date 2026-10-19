"""Historique minute gratuit Dukascopy (https://www.dukascopy.com) : CFD d indices et devises, usage personnel.

Utilise ici pour le DAX (DEUIDXEUR = CFD sur l indice cash DAX 40) : Databento n a l Eurex que depuis mars 2025.
Un fichier par jour : datafeed/<SYMBOLE>/<annee>/<mois-1>/<jour>/BID_candles_min_1.bi5 (LZMA, 24 octets par minute :
seconde du jour UTC, open, close, low, high en milliemes de point, volume). Les minutes sans transaction (volume nul)
sont ecartees, comme NinjaTrader ne cree pas de barre sans tick. Index = heure de FIN de barre, UTC naif.

    python -m nexus.dukascopy DEUIDXEUR 2014-01-01 2026-08-28
"""
from __future__ import annotations

import lzma
import os
import struct
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor

import pandas as pd

from .data import DEFAULT_CACHE

URL = "https://datafeed.dukascopy.com/datafeed/{sym}/{y}/{m:02d}/{d:02d}/BID_candles_min_1.bi5"
SCALE = {"DEUIDXEUR": 1000.0}


def _day(sym: str, day: pd.Timestamp, tries: int = 6, pause: float = 1.0):
    url = URL.format(sym=sym, y=day.year, m=day.month - 1, d=day.day)
    err = None
    for k in range(tries):
        time.sleep(pause)                # le serveur repond 429 (trop de requetes) si on va trop vite
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (recherche personnelle)"})
            raw = urllib.request.urlopen(req, timeout=40).read()
            if not raw:
                return day, []
            data = lzma.decompress(raw, format=lzma.FORMAT_ALONE)
            return day, [struct.unpack(">5if", data[i:i + 24]) for i in range(0, len(data) - 23, 24)]
        except urllib.error.HTTPError as ex:
            if ex.code == 404:
                return day, []
            err = ex
            if ex.code == 429:           # limite de debit : longue pause avant de reessayer
                time.sleep(120 * (k + 1))
                continue
        except Exception as ex:          # 503, delais : on ralentit et on recommence
            err = ex
        time.sleep(2 * (k + 1))
    return day, err


def _save(path: str, have: pd.DataFrame | None, rows: list) -> pd.DataFrame:
    df = pd.DataFrame(rows, columns=["t", "open", "high", "low", "close", "volume"]).set_index("t")
    if have is not None:
        df = pd.concat([have, df])
    df = df[~df.index.duplicated(keep="last")].sort_index()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    df.to_parquet(path + ".tmp")
    os.replace(path + ".tmp", path)
    return df


def download(sym: str, start, end, path: str | None = None, threads: int = 1, chunk: int = 20, log=print) -> pd.DataFrame:
    """Reprend la ou il s est arrete : sauvegarde toutes les `chunk` journees (le serveur limite fortement le debit)."""
    scale = SCALE.get(sym.upper(), 1000.0)
    path = path or os.path.join(DEFAULT_CACHE, "dukascopy", f"{sym.upper()}_1m.parquet")
    days = pd.bdate_range(start, end)
    have = None
    if os.path.exists(path):
        have = pd.read_parquet(path)
        done = set(pd.DatetimeIndex(have.index - pd.Timedelta(minutes=1)).normalize())
        days = pd.DatetimeIndex([d for d in days if d not in done])
    log(f"[dukascopy] {sym} : {len(days)} jours a telecharger", flush=True)
    failed, t0 = [], time.time()
    with ThreadPoolExecutor(max_workers=threads) as ex:
        for k in range(0, len(days), chunk):
            rows = []
            for day, recs in ex.map(lambda d: _day(sym, d), days[k:k + chunk]):
                if isinstance(recs, Exception):
                    failed.append(day)
                    continue
                for sec, o, c, lo, hi, vol in recs:
                    if vol > 0:
                        rows.append((day + pd.Timedelta(seconds=sec + 60), o / scale, hi / scale, lo / scale, c / scale, vol))
            have = _save(path, have, rows)
            fait = min(k + chunk, len(days))
            log(f"  ... {fait}/{len(days)} jours (jusqu au {days[fait - 1]:%Y-%m-%d}), {len(failed)} en echec, "
                f"{(time.time() - t0) / 60:.0f} min", flush=True)
    log(f"[dukascopy] {sym} : {len(have)} barres {have.index[0]} -> {have.index[-1]} ; jours en echec : {len(failed)} "
        f"(relancer la commande pour les recuperer) -> {path}", flush=True)
    return have


if __name__ == "__main__":
    download(sys.argv[1], sys.argv[2], sys.argv[3])
