"""Profil horaire sur un an des strategies futures intraday du tableau de bord (page « Profil horaire »).

    python -m nexus.profil_horaire [--donnees ../Dashboard/donnees]

Lit les fiches exportees (positions reconstruites depuis les trades, comme l onglet Prop firm) et prop.json (fiabilite
vectorbt de chaque strategie), puis ecrit donnees/profil.json :
  - la carte jour x demi-heure (heure de New York) des 365 derniers jours de donnees : nombre de strategies FIABLES en
    position, et lesquelles ;
  - pour chaque strategie futures intraday, la part des jours ouvres ou elle est en position, par demi-heure ;
  - la couverture des strategies fiables par demi-heure et les plages vides ;
  - les hypotheses testees pour remplir les plages vides (etudes « creneaux_* » de recherche/resultats_60.json).
Appele aussi a la fin de python -m nexus tableau.
"""
from __future__ import annotations

import argparse
import json
import os

import numpy as np
import pandas as pd

NY = "America/New_York"
PAS_MIN = 30
NB = 24 * 60 // PAS_MIN
SEUIL_VIDE = 0.02


def _lire(chemin: str):
    with open(chemin, encoding="utf-8") as fh:
        return json.load(fh)


def occupation(pos: pd.DataFrame, jours: pd.DatetimeIndex) -> np.ndarray:
    """Positions (debut, fin en UTC naif) -> matrice booleenne jour (New York) x demi-heure."""
    occ = np.zeros((len(jours), NB), bool)
    if not len(pos):
        return occ
    rang = {d: i for i, d in enumerate(jours)}
    a = pd.DatetimeIndex(pos["debut"]).tz_localize("UTC").tz_convert(NY).tz_localize(None)
    b = pd.DatetimeIndex(pos["fin"]).tz_localize("UTC").tz_convert(NY).tz_localize(None)
    for x, y in zip(a, b):
        if y <= x:
            continue
        t = x.floor(f"{PAS_MIN}min")
        while t < y:
            i = rang.get(t.normalize())
            if i is not None:
                occ[i, (t.hour * 60 + t.minute) // PAS_MIN] = True
            t += pd.Timedelta(minutes=PAS_MIN)
    return occ


def plages(vide: np.ndarray) -> list[str]:
    """Demi-heures vides consecutives -> ['22:00-09:30', ...] (la nuit est recollee d un jour a l autre)."""
    lab = lambda k: f"{(k * PAS_MIN) // 60:02d}:{(k * PAS_MIN) % 60:02d}"
    out, k = [], 0
    v = list(vide)
    if all(v):
        return ["toute la journee"]
    debut = next(i for i in range(NB) if not v[i])          # commencer apres une demi-heure occupee
    ordre = [(debut + i) % NB for i in range(NB)]
    while k < NB:
        if v[ordre[k]]:
            j = k
            while j + 1 < NB and v[ordre[j + 1]]:
                j += 1
            out.append(f"{lab(ordre[k])}-{lab((ordre[j] + 1) % NB)}")
            k = j + 1
        else:
            k += 1
    return out


def construire(donnees: str, jours_profil: int = 365) -> dict:
    from .tableau import positions_fiche
    prop = _lire(os.path.join(donnees, "prop.json"))
    cands = prop.get("candidats", [])
    fin = max(pd.Timestamp(c["fin"]) for c in cands) if cands else pd.Timestamp.today().normalize()
    jours = pd.date_range(fin - pd.Timedelta(days=jours_profil - 1), fin)
    jours = jours[jours.dayofweek != 5]                      # le samedi rien ne cote ; le dimanche, reouverture de 18:00
    profils, fiables, occ_f = {}, [], []
    for c in cands:
        f = os.path.join(donnees, f"{c['id']}.json")
        if not os.path.exists(f):
            continue
        occ = occupation(positions_fiche(_lire(f)), jours)
        profils[c["id"]] = [round(float(v), 4) for v in occ.mean(axis=0)]
        st = c.get("stats") or {}
        if st.get("fiable"):
            fiables.append(dict(id=c["id"], titre=c["titre"], instruments=c.get("instruments")))
            occ_f.append(occ)
    occ_f = np.array(occ_f) if occ_f else np.zeros((0, len(jours), NB), bool)
    masque = (occ_f * (2 ** np.arange(len(occ_f)))[:, None, None]).sum(axis=0).astype(int) if len(occ_f) else np.zeros((len(jours), NB), int)
    nb = occ_f.sum(axis=0).astype(int) if len(occ_f) else np.zeros((len(jours), NB), int)
    couverture = (nb > 0).mean(axis=0)
    hypo = []
    etudes = os.path.join(os.path.dirname(__file__), "..", "recherche", "resultats_60.json")
    if os.path.exists(etudes):
        for cle, e in _lire(etudes).items():
            if cle.startswith("creneaux_") and isinstance(e, dict):
                v = next((l for l in e.get("lignes", []) if l.get("code") == "V"), {})
                hypo.append(dict(code=cle.split("_", 1)[1], titre=e.get("titre"), heures=(e.get("sous") or "").split(" ; ")[0],
                                 retenue=e.get("retenue"), fiable=e.get("fiable"), sharpe=v.get("sharpe_an"), net=v.get("moyenne"),
                                 t=v.get("t"), echecs=e.get("echecs", []), genere=e.get("genere")))
    hypo.sort(key=lambda h: h["code"])
    return dict(genere=pd.Timestamp.now().strftime("%Y-%m-%d %H:%M"), debut=jours[0].strftime("%Y-%m-%d"), fin=jours[-1].strftime("%Y-%m-%d"),
                pas_minutes=PAS_MIN, creneaux=[f"{(k * PAS_MIN) // 60:02d}:{(k * PAS_MIN) % 60:02d}" for k in range(NB)],
                jours=[d.strftime("%Y-%m-%d") for d in jours], fiables=fiables, nombre=nb.tolist(), masque=masque.tolist(),
                couverture=[round(float(v), 4) for v in couverture], vides=plages(couverture < SEUIL_VIDE), seuil_vide=SEUIL_VIDE,
                profils=profils, titres={c["id"]: c["titre"] for c in cands},
                fiabilite={c["id"]: bool((c.get("stats") or {}).get("fiable")) for c in cands},
                instruments={c["id"]: c.get("instruments") for c in cands}, hypotheses=hypo)


def ecrire(donnees: str) -> str:
    d = construire(donnees)
    chemin = os.path.join(donnees, "profil.json")
    with open(chemin, "w", encoding="utf-8") as fh:
        json.dump(d, fh, ensure_ascii=False, separators=(",", ":"))
    return chemin


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--donnees", default=os.path.join(os.path.dirname(__file__), "..", "..", "Dashboard", "donnees"))
    a = ap.parse_args(argv)
    c = ecrire(a.donnees)
    d = _lire(c)
    print(f"[profil] {len(d['jours'])} jours, {len(d['fiables'])} strategies fiables, plages vides : {', '.join(d['vides'])} -> {c}")


if __name__ == "__main__":
    main()
