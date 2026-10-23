"""Lecture des resultats du runner local pour le tableau de bord commun (nexus/tableau.py, nexus/tableau_runner.py).

Les strategies du runner (nexus/perso/runner.py) sont des fiches du tableau de bord Nexus comme les autres :
    python -m nexus tableau            (depuis Python/ ; --seulement R pour ne recalculer que celles du runner)
Ce module ne garde que ce qui lit leurs resultats : verdicts de resultats_strategies.txt, strategies non testees,
libelles courts, et les conclusions de l etude des alternatives (resultats_alternatives.txt).
(L ancienne page autonome « archive de la recherche » est remplacee par le tableau de bord commun, le 2026-10-19.)
"""
from __future__ import annotations

import math
import os

from .runner import PY_DIR


# Conclusions de l etude des alternatives (resultats_alternatives.txt, 2026-10-09) : performance expliquee par une
# reference naive, alpha non distinguable de zero. Elles priment sur la regression generique contre le SPY.
SURTOUT_BETA = {
    "S20-A Risk parity ERC multi-futures": "≈ 1/N des mêmes 4 jambes (alpha t +0,8 contre le 1/N)",
    "S20-B Risk parity inverse-vol multi-futures": "≈ 1/N des mêmes 4 jambes",
    "S20-A ERC, covariance sur 60 j (alternative)": "≈ 1/N des mêmes 4 jambes ; PBO de la famille 47 %",
    "S20 1/N, memes 4 jambes (reference naive)": "référence naïve elle-même (portefeuille de bêta)",
    "Fiche 2 XSMOM (futures)": "bêta 0,76 sur le 1/N long des mêmes futures (alpha t +0,7) ; PBO de la grille 70 %",
    "Fiche 5 Retour a la moyenne de vol (futures)": "bêta 0,43 sur ES + NQ (alpha t +1,1)",
    "Fiche 1 TSMOM 12-1 (25 actions/ETF US)": "alpha t +0,2 contre les 25 titres à poids égal",
    "Fiche 2 XSMOM quartile superieur (25 actions/ETF US)": "alpha t +0,8 contre les 25 titres à poids égal",
    "Fiche 3 Rotation multi-facteurs": "alpha t +0,3 contre les 25 titres à poids égal",
    "Fiche 4A Residu OU sectoriel": "alpha t +1,3 contre le SPY",
    "Fiche 11 Roue d options synthetique": "alpha t −0,3 contre le SPY",
}

def _f(x, nd=2):
    """Nombre arrondi pour le JSON ; None pour NaN, NaT, infini ou valeur non numerique."""
    try:
        x = float(x)
    except (TypeError, ValueError):
        return None
    return round(x, nd) if math.isfinite(x) else None


def _nombre(txt):
    """'+11 968 $' / '43%' / '1.08' -> float (None si vide ou n/d)."""
    if txt is None:
        return None
    t = str(txt).replace(" ", "").replace(" ", "").replace("%", "").replace("$", "").replace(",", ".")
    try:
        return float(t)
    except ValueError:
        return None


def lire_resultats(path: str | None = None) -> dict:
    """Lignes de resultats_strategies.txt (ecrit par le runner) -> {nom: champs}."""
    path = path or os.path.join(PY_DIR, "recherche", "resultats_strategies.txt")
    out = {}
    if not os.path.exists(path):
        return out
    prefixes = [("reussite ", "reussite"), ("PnL net ", "pnl"), ("PF ", "pf"), ("Sharpe ", "sharpe"),
                ("DD max ", "dd"), ("t ", "t"), ("VERDICT ", "verdict")]
    with open(path, encoding="utf-8") as fh:
        for ligne in fh:
            ligne = ligne.rstrip("\n")
            if not ligne or ligne.startswith("#") or ligne.startswith("NON TESTEES") or " | " not in ligne:
                continue
            champs = ligne.split(" | ")
            d = dict(fichier=champs[1] if len(champs) > 1 else "", donnees=champs[2] if len(champs) > 2 else "",
                     periode=champs[3] if len(champs) > 3 else "", erreur=None)
            for c in champs[4:]:
                if c.endswith(" trades"):
                    d["trades"] = _nombre(c[:-7])
                elif c.startswith("ERREUR"):
                    d["verdict"], d["erreur"] = "ERREUR", c
                else:
                    for p, k in prefixes:
                        if c.startswith(p) and k not in d:
                            d[k] = c[len(p):] if k == "verdict" else _nombre(c[len(p):])
                            break
            out[champs[0]] = d
    return out


def non_testees(path: str | None = None) -> list[str]:
    path = path or os.path.join(PY_DIR, "recherche", "resultats_strategies.txt")
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as fh:
        return [l.strip()[len("NON TESTEES - "):] for l in fh if l.startswith("NON TESTEES")]


def noms_courts(noms: list[str]) -> list[str]:
    """Libelles courts et uniques pour les axes : 'S06-B corr.', 'Fiche 5 fut.', 'boombitch'..."""
    import re
    out = []
    for n in noms:
        m = re.match(r"(S\d\d-[A-Z]|Fiche \d+[A-Z]?|Test OPR)", n)
        fil = re.match(r"Fil ES/NQ fiche (\d)", n)
        orr = re.match(r"Or (\d+)", n)
        c = m.group(1) if m else (f"Fil F{fil.group(1)}" if fil else (f"Or {orr.group(1)}" if orr else re.split(r"[ (,]", n)[0]))
        for motif, suffixe in (("1/N", " 1/N"), ("covariance sur 60", " 60 j"), ("taille inverse", " vol."),
                               ("filtre de tendance", " tend."), ("small-cap : fade", " fade"), ("small-cap : reversal", " jump"),
                               ("FX fix flow", " fix"), ("FX post-annonce", " annonces"), ("FX cascade", " ronds"),
                               ("FX trois", " combinees"), ("Gotobi pre-fix", " pre-fix"), ("Gotobi seconde", " jambe 2")):
            if motif in n:
                c += suffixe
        sur = re.search(r" sur (\w+)$", n)
        if sur:
            c += " " + sur.group(1)
        if "(futures)" in n:
            c += " fut."
        if "tel que code" in n:
            c += " code"
        elif "corrige" in n:
            c += " corr."
        if "sans stop" in n:
            c += " sans stop"
        if "historique long" in n:
            c += " long"
        out.append(c)
    vus = {}
    for i, c in enumerate(out):                    # doublons restants : on numerote
        if out.count(c) > 1:
            vus[c] = vus.get(c, 0) + 1
            out[i] = f"{c} #{vus[c]}"
    return out
