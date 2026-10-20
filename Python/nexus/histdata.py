"""Historique minute gratuit de HistData.com (usage personnel) : ici le CFD sur le DAX (GRXEUR).

Utilise pour le DAX quand Dukascopy bloque les telechargements (nexus/dukascopy.py). Un zip par annee (un par mois pour
l annee en cours), obtenu par le formulaire public de chaque page (champ cache tk). Fichier CSV : « AAAAMMJJ HHMMSS;
open;high;low;close;volume », prix BID, volume nul. La specification du site annonce l heure de New York SANS heure
d ete ; en pratique (controle du 2026-10-20, vers_utc) : heure de New York avec l heure d ete americaine jusqu a fin
2018, avec l heure d ete EUROPEENNE depuis 2019. Le controle du 2026-10-19 (GRXEUR contre Dukascopy, 2014-2018) ne
voyait que la premiere periode ; les etudes DAX du 19/10/2026 avaient donc 3 a 4 semaines par an decalees d une heure
depuis 2019. L horodatage est le DEBUT de
la barre ; le parquet ecrit garde la convention du depot : index = heure de FIN de barre, UTC naif.

    python -m nexus.histdata GRXEUR 2014 2026-08          (telechargement + conversion -> .cache/histdata/GRXEUR_1m.parquet)
"""
from __future__ import annotations

import io
import os
import re
import sys
import time
import urllib.parse
import urllib.request
import zipfile

import numpy as np
import pandas as pd

from .data import DEFAULT_CACHE

BASE = "https://www.histdata.com"
PAGE = BASE + "/download-free-forex-historical-data/?/ascii/1-minute-bar-quotes/{sym}/{periode}"
UA = {"User-Agent": "Mozilla/5.0 (recherche personnelle)"}


def periodes(debut: str, fin: str) -> list[str]:
    """'2014', '2026-08' -> ['2014', ..., '2025', '2026/1', ..., '2026/8'] (annee en cours par mois)."""
    a0 = int(debut[:4])
    a1, m1 = int(fin[:4]), int(fin[5:7]) if len(fin) > 4 else 12
    return [str(a) for a in range(a0, a1)] + [f"{a1}/{m}" for m in range(1, m1 + 1)]


def telecharger(sym: str, debut: str, fin: str, dossier: str | None = None, pause: float = 3.0, log=print) -> str:
    dossier = dossier or os.path.join(DEFAULT_CACHE, "histdata", "zips")
    os.makedirs(dossier, exist_ok=True)
    for p in periodes(debut, fin):
        nom = os.path.join(dossier, f"{sym.upper()}_M1_{p.replace('/', '_')}.zip")
        if os.path.exists(nom) and os.path.getsize(nom) > 1000:
            continue
        url = PAGE.format(sym=sym.lower(), periode=p)
        html = urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=60).read().decode("utf-8", "ignore")
        form = html[html.index('id="file_down"'):]
        champs = dict(re.findall(r'name="([^"]+)"[^>]*value="([^"]*)"', form[:form.index("</form>")]))
        req = urllib.request.Request(BASE + "/get.php", data=urllib.parse.urlencode(champs).encode(),
                                     headers=dict(UA, Referer=url, **{"Content-Type": "application/x-www-form-urlencoded"}))
        data = urllib.request.urlopen(req, timeout=180).read()
        if data[:2] != b"PK":
            raise RuntimeError(f"{p} : reponse inattendue ({len(data)} octets)")
        with open(nom, "wb") as fh:
            fh.write(data)
        log(f"[histdata] {sym} {p} : {len(data) / 1e6:.1f} Mo", flush=True)
        time.sleep(pause)
    return dossier


def lire_zip(chemin: str) -> pd.DataFrame:
    """CSV du zip -> barres, index = FIN de barre en UTC naif (debut, heure de New York avec heure d ete, + 1 min)."""
    with zipfile.ZipFile(chemin) as z:
        noms = [n for n in z.namelist() if n.lower().endswith(".csv")]
        d = pd.concat([pd.read_csv(io.BytesIO(z.read(n)), sep=";", header=None,
                                   names=["t", "open", "high", "low", "close", "volume"], dtype={"t": str}) for n in noms])
    t = pd.DatetimeIndex(pd.to_datetime(d.pop("t"), format="%Y%m%d %H%M%S"))
    d.index = pd.DatetimeIndex(vers_utc(t) + pd.Timedelta(minutes=1)).as_unit("ns")
    return d[d.index.notna()].astype(float)


BASCULE = "2019-01-01"


def vers_utc(t: pd.DatetimeIndex) -> pd.DatetimeIndex:
    """Heure HistData -> UTC naif. Controle du 2026-10-20 (EURJPY contre 6E / 6J et JPXJPY contre NQ, semaine par
    semaine) : jusqu a fin 2018, heure de New York avec l heure d ete AMERICAINE ; depuis 2019, heure de New York (UTC-5)
    avec l heure d ete EUROPEENNE (UTC-4 du dernier dimanche de mars au dernier dimanche d octobre). Les 3 a 4 semaines
    par an entre les deux changements d heure sont decalees d une heure si l on se trompe de regle."""
    t = pd.DatetimeIndex(t)
    approx = t + pd.Timedelta(hours=5)
    lon = approx.tz_localize("UTC").tz_convert("Europe/London").tz_localize(None)
    ete_eu = (lon - approx) >= pd.Timedelta(minutes=30)
    ny = t.tz_localize("America/New_York", ambiguous="NaT", nonexistent="NaT").tz_convert("UTC").tz_localize(None)
    eu = pd.DatetimeIndex(np.where(ete_eu, approx - pd.Timedelta(hours=1), approx))
    return pd.DatetimeIndex(np.where(t < pd.Timestamp(BASCULE), ny, eu))


def convertir(sym: str = "GRXEUR", dossier: str | None = None, sortie: str | None = None, log=print) -> pd.DataFrame:
    dossier = dossier or os.path.join(DEFAULT_CACHE, "histdata", "zips")
    sortie = sortie or os.path.join(DEFAULT_CACHE, "histdata", f"{sym.upper()}_1m.parquet")
    fichiers = sorted(f for f in os.listdir(dossier) if f.upper().startswith(sym.upper()) and f.endswith(".zip"))
    df = pd.concat([lire_zip(os.path.join(dossier, f)) for f in fichiers])
    df = df[~df.index.duplicated(keep="last")].sort_index()
    df.to_parquet(sortie)
    log(f"[histdata] {sym} : {len(df)} barres {df.index[0]} -> {df.index[-1]} -> {sortie}")
    return df


if __name__ == "__main__":
    s = sys.argv[1] if len(sys.argv) > 1 else "GRXEUR"
    telecharger(s, sys.argv[2] if len(sys.argv) > 2 else "2014", sys.argv[3] if len(sys.argv) > 3 else "2026-08")
    convertir(s)
