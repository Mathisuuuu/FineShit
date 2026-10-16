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


def test_intervalles_desequilibre_et_volume():
    from nexus import or_nuit as ON
    rows = []
    for j, jour in enumerate(pd.bdate_range("2024-01-02", periods=25)):
        t0 = (pd.Timestamp(jour) + pd.Timedelta(hours=9, minutes=30)).tz_localize(ON.NY).tz_convert("UTC").tz_localize(None)
        for k in range(60):                                   # 9:30-10:30 ; montee reguliere la 2e demi-heure
            p = 100.0 + (0.01 * (k - 29) if k >= 30 else 0.001 * ((-1) ** k))
            rows.append((t0 + pd.Timedelta(minutes=k), p, p, p, p, 10.0 if k < 30 else (50.0 if j == 24 else 10.0)))
    df = pd.DataFrame(rows, columns=["t", "open", "high", "low", "close", "volume"]).set_index("t")
    df["seance"], df["minute"] = ON.seances(df.index)
    mes = P.intervalles(df, "09:30", "10:30", pas=30)
    assert mes["heures"] == ["09:30", "10:00", "10:30"]
    assert mes["oi"][-1, 1] > 0.5                              # montee reguliere : desequilibre acheteur
    assert abs(mes["vol_anorm"][-1, 1] - 5.0) < 1e-9           # volume 5 fois la moyenne des 20 seances precedentes
    pos = np.zeros((25, 2)); pos[-1, 1] = 1
    fen = P.fenetres_positions(mes, pos)
    assert fen[2][:3] == ("10:00", "10:30", 1) and list(fen[2][3]) == [mes["jours"][-1]]
