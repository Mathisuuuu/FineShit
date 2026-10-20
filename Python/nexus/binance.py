"""Historique minute gratuit de Binance (data.binance.vision, donnees publiques) : BTCUSDT et ETHUSDT au comptant.

Sert de substitut aux micro-futures crypto du CME (MBT = 0,1 BTC, MET = 0,1 ETH), dont l historique ne commence qu en
2021 : en intraday, le future suit le comptant a une base pres qui varie lentement. Un zip par mois
(data/spot/monthly/klines/<SYM>/1m/<SYM>-1m-AAAA-MM.zip), verifie par son empreinte SHA-256 publiee a cote (.CHECKSUM).
CSV sans en-tete : open_time, open, high, low, close, volume, close_time, ... ; open_time en millisecondes UTC jusqu a
2024, en MICROsecondes depuis le 01/01/2025 (changement de Binance) : l unite est detectee fichier par fichier.
L horodatage est le DEBUT de la barre ; le parquet ecrit garde la convention du depot : index = heure de FIN de barre,
UTC naif. Les zips sont des donnees telechargees : ils ne sont que lus (zipfile + pandas), jamais executes.

    python -m nexus.binance BTCUSDT ETHUSDT --debut 2017-08 --fin 2026-09     (-> .cache/binance/<SYM>_1m.parquet)
"""
from __future__ import annotations

import argparse
import hashlib
import io
import os
import time
import urllib.error
import urllib.request
import zipfile

import pandas as pd

from .data import DEFAULT_CACHE

BASE = "https://data.binance.vision/data/spot/monthly/klines/{sym}/1m/{sym}-1m-{mois}.zip"
UA = {"User-Agent": "Mozilla/5.0 (recherche personnelle)"}
DOSSIER = os.path.join(DEFAULT_CACHE, "binance")


def mois(debut: str, fin: str) -> list[str]:
    return [p.strftime("%Y-%m") for p in pd.period_range(debut, fin, freq="M")]


def _lire(url: str) -> bytes:
    return urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=120).read()


def telecharger(sym: str, debut: str, fin: str, pause: float = 0.3, log=print) -> str:
    zips = os.path.join(DOSSIER, "zips", sym)
    os.makedirs(zips, exist_ok=True)
    for m in mois(debut, fin):
        nom = os.path.join(zips, f"{sym}-1m-{m}.zip")
        if os.path.exists(nom) and os.path.getsize(nom) > 1000:
            continue
        url = BASE.format(sym=sym, mois=m)
        try:
            data = _lire(url)
        except urllib.error.HTTPError as ex:
            if ex.code == 404:
                log(f"[binance] {sym} {m} : absent (404)")
                continue
            raise
        attendu = _lire(url + ".CHECKSUM").decode("ascii", "ignore").split()[0].lower()
        if hashlib.sha256(data).hexdigest() != attendu or data[:2] != b"PK":
            raise RuntimeError(f"{sym} {m} : empreinte SHA-256 differente de celle publiee")
        with open(nom, "wb") as fh:
            fh.write(data)
        log(f"[binance] {sym} {m} : {len(data) / 1e6:.1f} Mo", flush=True)
        time.sleep(pause)
    return zips


def lire_zip(chemin: str) -> pd.DataFrame:
    """Un zip mensuel -> barres 1 minute, index = FIN de barre (UTC naif)."""
    with zipfile.ZipFile(chemin) as z:
        brut = z.read(z.namelist()[0])
    d = pd.read_csv(io.BytesIO(brut), header=None, usecols=range(6), names=["t", "open", "high", "low", "close", "volume"])
    if not str(d.iloc[0, 0]).strip().lstrip("-").isdigit():          # en-tete eventuel
        d = d.iloc[1:]
    t = pd.to_numeric(d["t"]).astype("int64")
    unite = "us" if t.iloc[0] > 10 ** 14 else "ms"
    idx = pd.to_datetime(t, unit=unite) + pd.Timedelta(minutes=1)
    out = d[["open", "high", "low", "close", "volume"]].astype(float)
    out.index = pd.DatetimeIndex(idx.to_numpy()).as_unit("ns")
    return out


def convertir(sym: str, log=print) -> str:
    zips = os.path.join(DOSSIER, "zips", sym)
    parts = [lire_zip(os.path.join(zips, f)) for f in sorted(os.listdir(zips)) if f.endswith(".zip")]
    df = pd.concat(parts).sort_index()
    df = df[~df.index.duplicated(keep="last")]
    df.attrs["fuseau"] = "UTC"
    sortie = os.path.join(DOSSIER, f"{sym}_1m.parquet")
    df.to_parquet(sortie)
    log(f"[binance] {sym} : {len(df):,} barres, {df.index[0]} -> {df.index[-1]} (fin de barre, UTC) -> {sortie}")
    return sortie


def charger(sym: str) -> pd.DataFrame:
    return pd.read_parquet(os.path.join(DOSSIER, f"{sym}_1m.parquet"))


def main(argv=None):
    ap = argparse.ArgumentParser(description="historique minute Binance (comptant) -> parquet")
    ap.add_argument("symboles", nargs="+")
    ap.add_argument("--debut", default="2017-08")
    ap.add_argument("--fin", default="2026-09")
    a = ap.parse_args(argv)
    for s in a.symboles:
        telecharger(s.upper(), a.debut, a.fin)
        convertir(s.upper())


if __name__ == "__main__":
    main()
