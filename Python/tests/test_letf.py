"""Fiche 15 (LETF NQ / ES) : heures, flux, seuil glissant sans anticipation, regle d instrument, executions vectorbt."""
import numpy as np
import pandas as pd
import pytest

from nexus import intraday as I
from nexus import letf as L


def _grilles(n_jours=320, seed=3):
    """NQ et ES synthetiques (heure de New York, barres datees a leur fin) -> grilles de seance ajustees et brutes."""
    out = {}
    for k, (sym, p0) in enumerate((("NQ", 15000.0), ("ES", 4500.0))):
        df = I.synthetic_minutes("2023-01-02", pd.bdate_range("2023-01-02", periods=n_jours)[-1], seed=seed + k, price0=p0)
        g = I.build_grid(df)
        out[sym] = dict(adj=g, brut=g)
    return out


def test_heures_de_la_grille():
    assert L._slot("09:31") == 0 and L._slot("15:25") == 354 and L._slot("15:30") == 359 and L._slot("16:00") == 389
    assert L._slot("15:30", -60) == 299


def test_quatre_sorcieres_2024():
    q = L.quatre_sorcieres("2024-01-01", "2024-12-31")
    assert list(q.strftime("%Y-%m-%d")) == ["2024-03-15", "2024-06-21", "2024-09-20", "2024-12-20"]


def test_flux_dans_le_sens_du_marche():
    """F = A L(L-1) r / (1 + L r) : meme signe que r pour les fonds haussiers ET baissiers (L hors [0, 1])."""
    for lev in (3, -3, 2, -2):
        for r in (0.01, -0.01):
            assert np.sign(lev * (lev - 1) * r / (1 + lev * r)) == np.sign(r)


def test_seuil_sans_anticipation_et_regle_d_instrument():
    gr = _grilles()
    p = {**L.DEFAULTS, "fenetre_seuil": 60, "volume_jours": 5, "exclusions": False}
    base = L.caracteristiques(gr, p, pd.Series(dtype=float))
    t = L.decisions(base, p)
    # le seuil d un jour ne depend que des jours precedents : changer le score du dernier jour ne le modifie pas
    b2 = base.copy()
    dernier = b2["date"] == b2["date"].max()
    b2.loc[dernier, "S"] *= 50
    t2 = L.decisions(b2, p)
    assert np.allclose(t.loc[dernier, "seuil"], t2.loc[dernier, "seuil"])
    assert not t2.loc[dernier & (t2["symbole"] == "NQ"), "passe"].isna().any()
    # une position par jour au plus, NQ prioritaire
    pris = t[t["retenu"]]
    assert pris["date"].is_unique
    es = pris[pris["symbole"] == "ES"]
    nq_ces_jours = t[(t["symbole"] == "NQ") & t["date"].isin(es["date"])]
    assert not nq_ces_jours["passe"].any()
    # filtre de rendement et seuil respectes
    assert (pris["r"].abs() >= 0.005).all() and (pris["score"].abs() >= pris["seuil"]).all()
    # GEX inconnu -> poids 1 (regle PoidsUn du NinjaScript)
    assert (t["w"] == 1.0).all()


def test_execution_vectorbt_entree_15h30_sortie_16h():
    vbt = pytest.importorskip("vectorbt")
    gr = _grilles(n_jours=40)
    p = {**L.DEFAULTS, "symboles": ("NQ",), "cout_mult": 0.0}
    g = gr["NQ"]["brut"]
    j = 30
    d = g.days[j]
    panel = pd.DataFrame([dict(date=d, symbole="NQ", r=0.01, retenu=True, contrats=3, atr_frac=np.nan, levier=1.0)])
    pf = L.portefeuille(gr, panel, **p)
    tr = pf.trades.records_readable
    assert len(tr) == 1
    x = tr.iloc[0]
    assert x["Entry Timestamp"] == d + pd.Timedelta(hours=15, minutes=31)          # barre 15:30-15:31, a son ouverture
    assert x["Exit Timestamp"] == d + pd.Timedelta(hours=16)
    assert x["Size"] == pytest.approx(3 * 20.0)
    assert x["Avg Entry Price"] == pytest.approx(g.o[j, 360])
    assert x["Avg Exit Price"] == pytest.approx(g.c[j, 389])
    assert x["PnL"] == pytest.approx(3 * 20.0 * (g.c[j, 389] - g.o[j, 360]))
    assert x["Direction"] == "Long"
