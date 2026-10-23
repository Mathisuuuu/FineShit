"""Heures des 8-K de resultats (item 2.02) sur SEC EDGAR (data.sec.gov/submissions, donnees publiques).

    python -m nexus.perso.edgar TSLA AVGO NFLX COST ADBE AMD INTC CSCO      -> nexus/perso/resultats_nasdaq_suite.csv

Le champ acceptanceDateTime des fichiers « submissions » porte le suffixe Z, mais selon le deposant c est soit l heure
UTC vraie (NFLX, INTC, AVGO : 20:03Z = 16:03 a New York), soit l heure de New York decalee DEUX fois (AAPL, NVDA, CSCO :
00:30Z le lendemain = 16:30 ; controle exact du 2026-10-20 contre les heures « Accepted » des pages d index de
resultats_megacaps.csv, AAPL 44/44 et NVDA 45/45). Les pages d index (www.sec.gov) refusent un User-Agent sans adresse
de contact : la convention est donc choisie par societe et par annee, a la majorite : celle qui place le plus de 8-K de
resultats apres la cloture (15:30-17:30 New York). Aucune donnee de marche n entre dans ce choix. Le controle AAPL / NVDA
est refait a chaque execution (arret s il echoue). Les fichiers telecharges ne sont que lus (json), jamais executes.
"""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.request

import pandas as pd

ICI = os.path.dirname(__file__)
UA = {"User-Agent": "FichesEtCode recherche personnelle"}
CACHE = os.path.normpath(os.path.join(ICI, "..", "..", ".cache", "edgar"))
CIK = {"AAPL": [320193], "NVDA": [1045810], "TSLA": [1318605], "AVGO": [1649338, 1730168], "NFLX": [1065280], "COST": [909832],
       "ADBE": [796343], "AMD": [2488], "INTC": [50863], "CSCO": [858877]}


def _json(nom: str) -> dict:
    os.makedirs(CACHE, exist_ok=True)
    f = os.path.join(CACHE, nom)
    if not os.path.exists(f):
        data = urllib.request.urlopen(urllib.request.Request("https://data.sec.gov/submissions/" + nom, headers=UA), timeout=60).read()
        with open(f, "wb") as fh:
            fh.write(data)
        time.sleep(0.2)                                        # moins de 10 requetes par seconde (regle de la SEC)
    with open(f, encoding="utf-8") as fh:
        return json.load(fh)


def depots(cik: int) -> pd.DataFrame:
    d = _json(f"CIK{cik:010d}.json")
    parts = [pd.DataFrame(d["filings"]["recent"])]
    for f in d["filings"].get("files", []):
        if f.get("filingTo", "") >= "2015-01-01":
            parts.append(pd.DataFrame(_json(f["name"])))
    return pd.concat(parts, ignore_index=True)


def heure_new_york(valeur: str, double: bool = True) -> pd.Timestamp:
    """acceptanceDateTime -> heure de New York (naive). double=True : valeur moins deux fois le decalage New York / UTC
    (AAPL, NVDA, CSCO) ; double=False : heure UTC vraie, convertie normalement (NFLX, INTC, AVGO)."""
    v = pd.Timestamp(valeur.replace("Z", "")).tz_localize(None)
    if not double:
        return v.tz_localize("UTC").tz_convert("America/New_York").tz_localize(None)
    for dec in (5, 4):
        et = v - pd.Timedelta(hours=2 * dec)
        if -et.tz_localize("America/New_York", ambiguous=True, nonexistent="shift_forward").utcoffset().total_seconds() / 3600 == dec:
            return et
    return v - pd.Timedelta(hours=10)


def _apres_cloture(t: pd.Timestamp) -> bool:
    m = t.hour * 60 + t.minute
    return 15 * 60 + 30 <= m <= 17 * 60 + 30


CONVENTIONS: dict = {}


def resultats(symbole: str) -> pd.DataFrame:
    out = []
    for cik in CIK[symbole]:
        d = depots(cik)
        d = d[(d.form == "8-K") & d["items"].astype(str).str.contains("2.02", regex=False)]
        vals = list(d.acceptanceDateTime)
        annees = sorted({v[:4] for v in vals})
        for an in annees:
            vs = [v for v in vals if v[:4] == an]
            n2 = sum(_apres_cloture(heure_new_york(v, True)) for v in vs)
            n1 = sum(_apres_cloture(heure_new_york(v, False)) for v in vs)
            double = n2 >= n1
            CONVENTIONS[(symbole, an)] = ("double" if double else "UTC", max(n1, n2), len(vs))
            for v in vs:
                et = heure_new_york(v, double)
                out.append(dict(symbole=symbole, date=et.strftime("%Y-%m-%d"), accepte=et.strftime("%H:%M:%S")))
    r = pd.DataFrame(out).drop_duplicates().sort_values("date")
    return r[(r.date >= "2016-01-01")].reset_index(drop=True)


def controle(log=print) -> None:
    ref = pd.read_csv(os.path.join(ICI, "resultats_megacaps.csv"), comment="#")
    for s in ("AAPL", "NVDA"):
        a = ref[ref.symbole == s].set_index("date").accepte
        b = resultats(s).drop_duplicates("date").set_index("date").accepte
        com = a.index.intersection(b.index)
        ecarts = (pd.to_timedelta(a[com]) - pd.to_timedelta(b[com])).abs()
        log(f"[edgar] controle {s} : {len(com)} dates communes sur {len(a)}, ecart max {ecarts.max()}")
        if len(com) < 0.9 * len(a) or ecarts.max() > pd.Timedelta(0):
            raise RuntimeError(f"heures EDGAR differentes de la reference pour {s} : arret")


def main(argv=None):
    syms = (argv or sys.argv[1:]) or ["TSLA", "AVGO", "NFLX", "COST", "ADBE", "AMD", "INTC", "CSCO"]
    controle()
    r = pd.concat([resultats(s) for s in syms], ignore_index=True)
    sortie = os.path.join(ICI, "resultats_nasdaq_suite.csv")
    with open(sortie, "w", encoding="utf-8", newline="") as fh:
        fh.write("# Publications de resultats (8-K item 2.02) de " + ", ".join(syms) + " : SEC EDGAR, data.sec.gov/submissions,\n"
                 "# heure acceptanceDateTime convertie en heure de New York (nexus/perso/edgar.py, controle contre\n"
                 f"# resultats_megacaps.csv), lues le {pd.Timestamp.now():%Y-%m-%d}. Tous les 8-K item 2.02 (le filtre 16:00-16:43 est fait par l etude).\n")
        r.to_csv(fh, index=False)
    print(f"[edgar] {len(r)} depots -> {sortie}")
    conv = pd.DataFrame([(s, a, c, n, t) for (s, a), (c, n, t) in CONVENTIONS.items()], columns=["symbole", "annee", "convention", "apres_cloture", "depots"])
    print(conv[conv.annee >= "2016"].groupby(["symbole", "convention"]).agg(annees=("annee", "size"), apres_cloture=("apres_cloture", "sum"),
                                                                            depots=("depots", "sum")).to_string())
    print(r.groupby("symbole").size().to_string())


if __name__ == "__main__":
    main()
