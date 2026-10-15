"""Gotobi (6J) : calendrier japonais, jours gotobi, placement des ordres et comptabilite vectorbt."""
import datetime as dt

import numpy as np
import pandas as pd
import pytest

from nexus import gotobi as G


def test_feries_japon_2025_2026():
    f = G.feries_japon(2025, 2026)
    attendus_2025 = ["01-01", "01-02", "01-03", "01-13", "02-11", "02-23", "02-24", "03-20", "04-29", "05-03", "05-04",
                     "05-05", "05-06", "07-21", "08-11", "09-15", "09-23", "10-13", "11-03", "11-23", "11-24", "12-31"]
    assert sorted(d.strftime("%m-%d") for d in f if d.year == 2025) == attendus_2025
    assert {dt.date(2026, 9, 21), dt.date(2026, 9, 22), dt.date(2026, 9, 23), dt.date(2026, 5, 6)} <= f   # jour entre deux feries


def test_feries_japon_cas_particuliers():
    f = G.feries_japon(2018, 2021)
    assert {dt.date(2019, 4, 30), dt.date(2019, 5, 1), dt.date(2019, 5, 2), dt.date(2019, 10, 22)} <= f   # intronisation
    assert dt.date(2018, 12, 24) in f and dt.date(2019, 12, 23) not in f and dt.date(2020, 2, 24) in f   # empereur
    assert {dt.date(2020, 7, 23), dt.date(2020, 7, 24), dt.date(2020, 8, 10)} <= f                      # Jeux de Tokyo
    assert {dt.date(2021, 7, 22), dt.date(2021, 7, 23), dt.date(2021, 8, 9)} <= f


def test_jours_gotobi_reportes_au_jour_ouvre_precedent():
    g = set(G.jours_gotobi("2025-01-01", "2025-12-31"))
    assert pd.Timestamp("2025-03-19") in g and pd.Timestamp("2025-03-20") not in g      # 20 mars ferie
    assert pd.Timestamp("2025-03-14") in g                                               # 15 = samedi
    assert pd.Timestamp("2025-05-02") in g                                               # 5 mai ferie (Golden Week)
    assert pd.Timestamp("2025-02-28") in g and pd.Timestamp("2025-08-29") in g           # fins de mois
    assert len(g) == 71
    sans = set(G.jours_gotobi("2025-01-01", "2025-12-31", feries=False))
    assert pd.Timestamp("2025-03-20") in sans


def _minutes(jours_prix):
    """Barres 1 minute UTC (datees a leur debut) de 22:00 a 03:00 UTC autour des jours donnes, prix par heure de Tokyo."""
    rows = []
    for jour, prix in jours_prix.items():
        t0 = (pd.Timestamp(jour) + pd.Timedelta(hours=7)).tz_localize("Asia/Tokyo").tz_convert("UTC").tz_localize(None)
        for k in range(5 * 60):
            t = t0 + pd.Timedelta(minutes=k)
            hm = (t + pd.Timedelta(hours=9))
            p = prix(hm.hour * 60 + hm.minute)
            rows.append((t, p, p))
    df = pd.DataFrame(rows, columns=["t", "open", "close"]).set_index("t")
    df["frais"] = 0.0
    df["glissement"] = 0.0
    return df


def test_ordres_aux_heures_de_tokyo_et_pnl_vectorbt():
    # 5 mars 2025 (gotobi) : 0,00700 jusqu a 8:59, 0,00690 de 9:00 a 9:54, 0,00695 a partir de 9:55
    def prix(minute_tokyo):
        return 0.00700 if minute_tokyo < 9 * 60 else (0.00690 if minute_tokyo < 9 * 60 + 55 else 0.00695)
    m = _minutes({"2025-03-05": prix, "2025-03-06": lambda _: 0.007})
    pf = G.portefeuille(m, capital=100_000.0, exposition=1.0)
    tr = pf.trades.records_readable.sort_values("Entry Timestamp")
    assert list(tr["Direction"]) == ["Short", "Long"]                       # le 6 mars n est pas gotobi
    tok = lambda s: pd.DatetimeIndex(s).tz_localize("UTC").tz_convert("Asia/Tokyo").strftime("%H:%M").tolist()
    assert tok(tr["Entry Timestamp"]) == ["08:00", "09:55"] and tok(tr["Exit Timestamp"]) == ["09:55", "11:00"]
    q_short = 100_000.0 / 0.00700
    q_long = 100_000.0 / 0.00695
    assert tr["PnL"].iloc[0] == pytest.approx(q_short * (0.00700 - 0.00695))  # vente 8:00, rachat a l ouverture de 9:55
    assert tr["PnL"].iloc[1] == pytest.approx(q_long * (0.00695 - 0.00695))
    assert G.valeur(pf).iloc[-1] == pytest.approx(100_000.0 + q_short * 0.00005)


def test_barre_manquante_tolerance():
    def prix(minute_tokyo):
        return 0.007
    m = _minutes({"2025-03-05": prix})
    trou = m.index[(m.index >= pd.Timestamp("2025-03-04 23:00")) & (m.index < pd.Timestamp("2025-03-04 23:12"))]
    pf = G.portefeuille(m.drop(trou))                                       # 8:00-8:11 manquantes (> 10 min)
    assert pf.trades.records_readable["Direction"].tolist() == ["Long"]      # seule la jambe apres reste
    trou = m.index[(m.index >= pd.Timestamp("2025-03-04 23:00")) & (m.index < pd.Timestamp("2025-03-04 23:04"))]
    pf = G.portefeuille(m.drop(trou))                                       # 4 min : premiere barre a 8:04
    tr = pf.trades.records_readable.sort_values("Entry Timestamp")
    assert pd.Timestamp(tr["Entry Timestamp"].iloc[0]) == pd.Timestamp("2025-03-04 23:04")
