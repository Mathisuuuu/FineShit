"""Simulateur de challenge de prop firm : objectif, perte max suiveuse (plafonnee au solde de depart), perte
journaliere, jours minimum et coherence, sur des chemins construits a la main."""
import numpy as np
import pandas as pd

from nexus import prop as P


def _chemin(jours):
    """jours : liste de (bas, haut, cloture) en $ par rapport au solde de depart -> valeur minute (3 barres par seance)."""
    v, d = [0.0, 0.0, 0.0], ["2024-01-01"] * 3                       # seance de depart (cloture = 0)
    for k, (lo, hi, cl) in enumerate(jours):
        v += [hi, lo, cl]
        d += [str(pd.Timestamp("2024-01-02") + pd.Timedelta(days=k))[:10]] * 3
    return pd.Series(np.array(v) + 50_000.0), pd.DatetimeIndex(d).to_numpy()


REGLES = dict(taille=50_000, objectif=3_000, perte_max=2_000, type_perte="fin_de_jour", perte_jour=1_000, jours_min=1, coherence=0.5)


def _premier(jours, **kw):
    v, d = _chemin(jours + [(0, 0, 0)] * 2)
    return P.simuler(v, d, {**REGLES, **kw}).iloc[0]


def test_objectif_et_coherence():
    r = _premier([(0, 1000, 1000), (1000, 2000, 2000), (2000, 3000, 3000)])
    assert r.resultat == "reussi" and r.jours == 3
    r = _premier([(0, 2000, 2000), (2000, 3000, 3000), (3000, 3000, 3000), (3000, 4100, 4100)])
    assert r.resultat == "reussi" and r.jours == 4                    # meilleur jour 2 000 > 50 % de 3 000 : il faut 4 000


def test_perte_max_suiveuse_et_journaliere():
    r = _premier([(0, 1500, 1500), (600, 1500, 600), (-300, 600, -300), (-600, -300, -600)])
    assert r.raison == "perte max" and r.jours == 4                   # seuil monte a -500 apres la cloture a 1 500
    r = _premier([(-1100, 0, -900)])
    assert r.resultat == "perdu" and r.raison == "perte journaliere"
    r = _premier([(0, 2500, 2500), (0, 2600, 2600), (-10, 2600, -10)])
    assert r.raison == "perte max"                                    # le seuil ne depasse pas le solde de depart (0)
