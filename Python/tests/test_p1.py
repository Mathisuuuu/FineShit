"""Groupe P1 : criteres d approbation (mise a l echelle 5 %/an, perte max, moities) et panier a risque egal."""
import numpy as np
import pandas as pd

from nexus import p1 as P


def _jours(n=2520):
    return pd.bdate_range("2016-01-04", periods=n)


def test_evaluer_strategie_reguliere_approuvee():
    rng = np.random.default_rng(1)
    r = pd.Series(0.0004 + 0.0015 * rng.standard_normal(2520), index=_jours())   # Sharpe annuel ~4
    e = P.evaluer(r, None, 10, r * 0.9)
    assert e["approuvee"] and e["criteres_v1"] == "VVVVV" and e["criteres"] == "-V"
    assert abs(e["levier"] - 0.05 / (r.mean() * 252)) < 1e-12
    assert e["dd_5pct"] < 0.055


def test_evaluer_rejette_le_bruit_et_les_pertes():
    rng = np.random.default_rng(2)
    r = pd.Series(0.01 * rng.standard_normal(2520), index=_jours())
    assert not P.evaluer(r, None, 200)["approuvee"]
    assert not P.evaluer(-r.abs() * 0.01, None, 1)["approuvee"]


def test_panier_risque_egal_sans_anticipation():
    j = _jours(600)
    a = pd.Series(np.tile([0.01, -0.01], 300), index=j)           # 10 fois plus volatile que b
    b = pd.Series(np.tile([0.001, -0.001], 300), index=j)
    p = P.panier({"a": a, "b": b})
    assert np.allclose(p.iloc[:60], (a + b).iloc[:60] / 2)        # poids egaux tant que l historique manque
    w_a = (p.iloc[400] - b.iloc[400] * 10 / 11) / a.iloc[400]
    assert abs(w_a - 1 / 11) < 1e-9                               # ensuite poids inverses de la volatilite passee


def test_criteres_v2_avant_et_apres_publication():
    rng = np.random.default_rng(3)
    j = _jours()
    bon = 0.0006 + 0.006 * rng.standard_normal(len(j))                     # Sharpe annuel ~1,6
    r = pd.Series(np.where(j < pd.Timestamp("2021-01-01"), bon, bon - 0.0006), index=j)   # disparait apres publication
    e = P.evaluer(r, "2021-01-01", 10)
    assert e["sharpe_avant_pub"] > 1 and e["criteres"][0] == "V" and e["criteres"][1] == "x" and not e["approuvee"]
    e2 = P.evaluer(pd.Series(bon, index=j), "2021-01-01", 10)
    assert e2["criteres"] == "VV" and e2["approuvee"]
    e3 = P.evaluer(pd.Series(bon, index=j), "2026-06-01", 10)               # moins d un an apres publication
    assert not e3["approuvee"]
