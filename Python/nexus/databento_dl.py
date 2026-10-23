"""Telechargement Databento (PAYANT) avec estimation du cout avant tout achat.

    python -m nexus.databento_dl cout ZT.v.0 2016-01-01 2026-08-29
    python -m nexus.databento_dl telecharger ZT.v.0 2016-01-01 2026-08-29 --dossier taux --confirmer

- Cle : DATABENTO_API_KEY dans .env.txt (racine du depot, jamais commite) ou variable d environnement. Elle n est
  jamais affichee.
- Paquet : pip install databento.
- Meme format que le reste de Cotations : jeu GLBX.MDP3 (CME Globex), schema ohlcv-1m, contrat continu roule au volume
  (.v.0), index ts_event en UTC, colonnes open, high, low, close, volume. Le fichier va dans Cotations/<dossier>/,
  dossier sous licence Databento : jamais redistribue ni commite (Cotations/ est dans .gitignore).
- Sans --confirmer, rien n est achete : le cout estime par Databento est affiche et le programme s arrete.

Donnees utiles aux fiches :
  ZT.v.0 (2 ans americain, CBOT)  -> strategie or n° 4 (surprise du FOMC), Cotations/taux/ZT_v0_1m.parquet
  GC.v.0 / ES.v.0 avant 2016       -> strategie or n° 9 (comparaison avant / apres 2018 ; GLBX.MDP3 commence en 2010)
"""
from __future__ import annotations

import argparse
import os
import sys

from . import llm as L
from .perso.qf import QUOTES

JEU = "GLBX.MDP3"
SCHEMA = "ohlcv-1m"


def cle() -> str:
    k = L.resolve_secret("", "DATABENTO_API_KEY")
    if not k:
        raise SystemExit("cle Databento absente : ajouter DATABENTO_API_KEY=... dans .env.txt (racine du depot)")
    return k


def client():
    try:
        import databento as db
    except ImportError:
        raise SystemExit("paquet absent : pip install databento")
    return db.Historical(cle())


def cout(symbole: str, debut: str, fin: str) -> float:
    """Cout estime par Databento (dollars) pour les barres 1 minute du symbole continu sur la periode."""
    return float(client().metadata.get_cost(dataset=JEU, symbols=[symbole], stype_in="continuous", schema=SCHEMA,
                                            start=debut, end=fin))


def telecharger(symbole: str, debut: str, fin: str, dossier: str, confirmer: bool = False, log=print) -> str | None:
    c = cout(symbole, debut, fin)
    log(f"[databento] {symbole} {SCHEMA} {debut} -> {fin} : cout estime {c:.2f} $")
    if not confirmer:
        log("[databento] rien n a ete achete : relancer avec --confirmer pour telecharger")
        return None
    data = client().timeseries.get_range(dataset=JEU, symbols=[symbole], stype_in="continuous", schema=SCHEMA,
                                         start=debut, end=fin)
    try:
        df = data.to_df(price_type="float")
    except TypeError:                                    # anciennes versions du paquet
        df = data.to_df(pretty_px=True)
    df = df[["open", "high", "low", "close", "volume"]].astype(float)
    df = df[~df.index.duplicated(keep="last")].sort_index()
    racine = symbole.split(".")[0].upper()
    out_dir = os.path.join(QUOTES, dossier)
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, f"{racine}_v0_1m.parquet")
    df.to_parquet(path)
    log(f"[databento] {len(df)} barres {df.index[0]} -> {df.index[-1]} -> {path}")
    return path


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("action", choices=("cout", "telecharger"))
    ap.add_argument("symbole")
    ap.add_argument("debut")
    ap.add_argument("fin")
    ap.add_argument("--dossier", default="taux")
    ap.add_argument("--confirmer", action="store_true", help="accepte le cout affiche et telecharge")
    a = ap.parse_args(argv)
    if a.action == "cout":
        print(f"{a.symbole} {SCHEMA} {a.debut} -> {a.fin} : cout estime {cout(a.symbole, a.debut, a.fin):.2f} $")
    else:
        telecharger(a.symbole, a.debut, a.fin, a.dossier, a.confirmer)


if __name__ == "__main__":
    sys.exit(main())
