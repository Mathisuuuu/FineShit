"""Or la nuit (GC) : regle publiee (13:30 -> 8:20 la seance suivante, week-end compris), version intraday (heures,
fin de seance, seances raccourcies), taille (100 % du capital), mode compact et rolls."""
import numpy as np
import pandas as pd
import pytest

from nexus import or_nuit as N


def _seance(fin, prix, minutes=range(0, 1380)):
    """Barres 1 minute (UTC, datees a leur debut) de la seance CME qui se termine le jour `fin` a 17:00 New York.
    prix : minute depuis 18:00 la veille -> (open, close)."""
    t0 = pd.Timestamp(fin) - pd.Timedelta(hours=6)                        # 18:00 New York la veille
    rows = []
    for k in minutes:
        o, c = prix(k)
        ny = (t0 + pd.Timedelta(minutes=k)).tz_localize(N.NY)
        rows.append((ny.tz_convert("UTC").tz_localize(None), o, c))
    df = pd.DataFrame(rows, columns=["t", "open", "close"]).set_index("t")
    df["frais"] = 0.0
    df["glissement"] = 0.0
    return df


def _escalier(k):
    """100 jusqu a 8:19, 101 de 8:20 a 13:29, 102 ensuite ; la derniere minute (16:59) cloture a 103."""
    niveau = 100.0 if k < 860 else (101.0 if k < 1170 else 102.0)
    return (niveau, 103.0 if k == 1379 else niveau)


def test_heures_et_pnl():
    m = _seance("2024-01-08", _escalier)                                   # dimanche 18:00 -> lundi 17:00 (hiver, UTC-5)
    pf = N.portefeuille(m, capital=100_000.0, jambes="asie,soir")
    tr = pf.trades.records_readable
    assert len(tr) == 2
    e = pd.DatetimeIndex(tr["Entry Timestamp"]).tz_localize("UTC").tz_convert(N.NY).strftime("%a %H:%M").tolist()
    s = pd.DatetimeIndex(tr["Exit Timestamp"]).tz_localize("UTC").tz_convert(N.NY).strftime("%a %H:%M").tolist()
    assert e == ["Sun 18:00", "Mon 13:30"] and s == ["Mon 08:20", "Mon 16:59"]
    assert tr["Avg Entry Price"].tolist() == pytest.approx([100.0, 102.0])
    assert tr["Avg Exit Price"].tolist() == pytest.approx([101.0, 103.0])     # fin de seance : cloture de 16:59
    assert tr["Size"].iloc[0] == pytest.approx(1000.0)                        # 100 % du capital
    assert tr["Size"].iloc[1] == pytest.approx(101_000.0 / 102.0)            # gain reinvesti
    assert pf.value().iloc[-1] == pytest.approx(101_000.0 * 103.0 / 102.0)


def test_intraday_seances_raccourcies_et_week_end():
    vendredi = _seance("2024-01-12", _escalier)                            # jeudi 18:00 -> vendredi 17:00
    ferie = _seance("2024-01-16", _escalier, minutes=range(0, 1140))       # lundi raccourci : fin a 13:00
    tard = _seance("2024-01-17", _escalier, minutes=range(30, 1380))       # pas de barre avant 18:30
    m = pd.concat([vendredi, ferie, tard])
    pf = N.portefeuille(m, capital=100_000.0, jambes="asie,soir")
    tr = pf.trades.records_readable
    ent = pd.DatetimeIndex(tr["Entry Timestamp"])
    sor = pd.DatetimeIndex(tr["Exit Timestamp"])
    d_e, _ = N.seances(ent)
    d_s, _ = N.seances(sor)
    assert (d_e == d_s).all()                                              # jamais de position d une seance a l autre
    jours = pd.DatetimeIndex(d_e).strftime("%Y-%m-%d").tolist()
    assert jours.count("2024-01-12") == 2                                  # vendredi : les deux jambes
    assert jours.count("2024-01-16") == 1                                  # seance raccourcie : pas de jambe du soir
    assert jours.count("2024-01-17") == 1                                  # 18:00 absent : pas de jambe d Asie
    assert (tr["Status"] == "Closed").all()


def test_mode_compact_identique():
    m = pd.concat([_seance(d, _escalier) for d in ("2024-01-08", "2024-01-09", "2024-01-10")])
    m.loc[m.index[::7], "open"] *= 1.001                                    # du bruit pour que les prix varient
    cal = pd.DatetimeIndex(["2024-01-08", "2024-01-09", "2024-01-10"])
    for kw in ({}, dict(jambes="asie,soir"), dict(jambes="tout"), dict(jambes="pause"), dict(jambes="permanent"), dict(delai_min=2)):
        a = N.valeur_journaliere(N.portefeuille(m, **kw), cal)
        b = N.valeur_journaliere(N.portefeuille(m, compact=True, **kw), cal)
        assert np.allclose(a.to_numpy(), b.to_numpy())


def test_regle_publiee_nuit_et_week_end():
    m = pd.concat([_seance(d, _escalier) for d in ("2024-01-11", "2024-01-12", "2024-01-16")])   # jeudi, vendredi, lundi
    pf = N.portefeuille(m, capital=100_000.0)                                # reglage par defaut = regle publiee
    tr = pf.trades.records_readable
    loc = lambda c: pd.DatetimeIndex(tr[c]).tz_localize("UTC").tz_convert(N.NY).strftime("%a %H:%M").tolist()
    assert loc("Entry Timestamp") == ["Thu 13:30", "Fri 13:30"]
    assert loc("Exit Timestamp") == ["Fri 08:20", "Tue 08:20"]               # le vendredi : gardee tout le week-end
    assert tr["Avg Entry Price"].tolist() == pytest.approx([102.0, 102.0])
    assert tr["Avg Exit Price"].tolist() == pytest.approx([101.0, 101.0])
    assert tr["Size"].iloc[0] == pytest.approx(100_000.0 / 102.0)


def test_or_garde_en_permanence():
    m = pd.concat([_seance(d, _escalier) for d in ("2024-01-08", "2024-01-09")])
    tr = N.portefeuille(m, jambes="permanent").trades.records_readable
    assert len(tr) == 1 and tr["Avg Entry Price"].iloc[0] == pytest.approx(100.0) and tr["Avg Exit Price"].iloc[0] == pytest.approx(103.0)


def test_rolls_mensuels():
    idx = pd.date_range("2024-01-28 20:00", "2024-02-02 02:00", freq="1min")
    prix = np.full(len(idx), 100.0)
    roll = idx.get_loc(pd.Timestamp("2024-01-30 00:00"))
    prix[roll:] = 101.0                                                    # nouvelle echeance plus chere de 1 %
    df = pd.DataFrame({"open": prix, "high": prix, "low": prix, "close": prix}, index=idx)
    adj, rolls = N.ajuster_rolls(df)
    assert len(rolls) == 1 and pd.Timestamp(rolls["utc"].iloc[0]) == pd.Timestamp("2024-01-30 00:00")
    assert np.allclose(adj["close"].to_numpy(), 101.0)                     # rendement nul conserve


def test_heure_limite_prop_firm():
    m = _seance("2024-01-08", _escalier)
    tr = N.portefeuille(m, jambes="asie,soir", cloture="16:10").trades.records_readable
    s = pd.DatetimeIndex(tr["Exit Timestamp"]).tz_localize("UTC").tz_convert(N.NY).strftime("%H:%M").tolist()
    assert s == ["08:20", "16:10"]
    assert tr["Avg Exit Price"].tolist() == pytest.approx([101.0, 102.0])     # ouverture de la barre de 16:10, pas la cloture de 16:59


def test_fenetres_libres():
    m = pd.concat([_seance(d, _escalier) for d in ("2024-01-08", "2024-01-09")])
    f = [("18:00", "08:20", 1), ("08:20", "13:30", -1, [pd.Timestamp("2024-01-09")])]
    pf = N.portefeuille(m, fenetres=f, capital=100_000.0)
    tr = pf.trades.records_readable
    assert len(tr) == 3                                                   # 2 achats de nuit + 1 vente le 9 seulement
    assert tr["Direction"].tolist().count("Short") == 1
    v = tr[tr["Direction"] == "Short"]
    assert v["Avg Entry Price"].iloc[0] == pytest.approx(101.0) and v["Avg Exit Price"].iloc[0] == pytest.approx(102.0)
    a = N.valeur_journaliere(pf, pd.DatetimeIndex(["2024-01-08", "2024-01-09"]))
    b = N.valeur_journaliere(N.portefeuille(m, fenetres=f, capital=100_000.0, compact=True), pd.DatetimeIndex(["2024-01-08", "2024-01-09"]))
    assert np.allclose(a.to_numpy(), b.to_numpy())
    r_ref = N.portefeuille(m, jambes="asie,soir", cloture="16:10", compact=True)
    r_fen = N.portefeuille(m, fenetres=[("18:00", "08:20", 1), ("13:30", "17:00", 1)], cloture="16:10", compact=True)
    assert np.allclose(r_ref.value().iloc[-1], r_fen.value().iloc[-1])


def test_sans_week_end_contrats_et_swap():
    m = pd.concat([_seance(d, _escalier) for d in ("2024-01-11", "2024-01-12", "2024-01-15")])   # jeudi, vendredi, lundi
    tr = N.portefeuille(m, garder_weekend=False, cloture="16:10").trades.records_readable
    loc = lambda c: pd.DatetimeIndex(tr[c]).tz_localize("UTC").tz_convert(N.NY).strftime("%a %H:%M").tolist()
    assert loc("Entry Timestamp") == ["Thu 13:30", "Fri 13:30", "Sun 18:00"]
    assert loc("Exit Timestamp") == ["Fri 08:20", "Fri 16:10", "Mon 08:20"]
    m.attrs["multiplicateur"] = 10.0
    pf = N.portefeuille(m, contrats=2, capital=50_000.0)                    # 2 micros = 20 onces
    t2 = pf.trades.records_readable
    assert (t2["Size"] == 20.0).all()
    assert N.valeur(pf).iloc[0] == pytest.approx(50_000.0)
    assert N.valeur(pf).iloc[-1] == pytest.approx(50_000.0 + t2["PnL"].sum())
    sw = N.portefeuille(m, contrats=2, capital=50_000.0, swap_nuit=20.0).trades.records_readable
    # 20 $ par 100 onces et par nuit : 1 nuit (jeudi) + 3 nuits (vendredi -> lundi), pour 20 onces
    assert (t2["PnL"] - sw["PnL"]).sum() == pytest.approx(20.0 * 0.2 * (1 + 3), rel=1e-6)
