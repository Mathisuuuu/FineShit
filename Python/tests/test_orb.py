"""ORB 5 minutes (NQ) : volume relatif, ordre stop au plus haut de la bougie, stop a 10 % de l ATR, taille, sortie."""
import numpy as np
import pandas as pd
import pytest

from nexus import orb as O


def _seance(jour, prix, vol_ouverture=1000.0):
    """390 barres 9:31 -> 16:00 (datees a leur fin) ; prix : fonction de la minute (1 = 9:30-9:31) -> (o, h, l, c)."""
    rows = []
    for k in range(1, 391):
        o, h, l, c = prix(k)
        rows.append((pd.Timestamp(jour) + pd.Timedelta(minutes=570 + k), o, h, l, c, vol_ouverture if k <= 5 else 100.0))
    df = pd.DataFrame(rows, columns=["t", "open", "high", "low", "close", "volume"]).set_index("t")
    df["frais"] = 0.0
    df["glissement"] = 0.0
    return df


def _historique(n=16):
    jours = pd.bdate_range("2024-01-02", periods=n + 1)
    calme = lambda k: (100.0, 100.5, 99.5, 100.0)                  # TR = 1 point chaque jour -> ATR = 1
    return [_seance(d, calme) for d in jours[:-1]], jours[-1]


def _test_jour(vol):
    def prix(k):
        if k <= 5:                                                  # bougie d ouverture haussiere 100 -> 101, plus haut 101.2
            return (100.0, 101.2, 99.9, 101.0) if k == 5 else (100.0 + 0.2 * (k - 1), 100.2 + 0.2 * (k - 1), 99.9, 100.2 * 1 + 0.2 * (k - 1))
        if k < 20:
            return (101.0, 101.1, 100.9, 101.0)
        if k == 20:
            return (101.1, 101.6, 101.0, 101.5)                     # franchit 101.2 -> achat a 101.2
        if k == 30:
            return (101.3, 101.3, 101.0, 101.1)                     # touche le stop 101.2 - 0.1 = 101.1
        return (101.5, 101.6, 101.4, 101.5)
    return prix, vol


def test_entree_stop_taille():
    hist, jour = _historique()
    prix, _ = _test_jour(None)
    m = pd.concat(hist + [_seance(jour, prix, vol_ouverture=2000.0)])
    pf = O.portefeuille(m, capital=100_000.0)
    tr = pf.trades.records_readable
    assert len(tr) == 1 and tr["Direction"].iloc[0] == "Long"
    assert pd.Timestamp(tr["Entry Timestamp"].iloc[0]) == pd.Timestamp(jour) + pd.Timedelta(minutes=570 + 20)
    assert tr["Avg Entry Price"].iloc[0] == pytest.approx(101.2)
    assert tr["Avg Exit Price"].iloc[0] == pytest.approx(101.1)      # stop a 10 % de l ATR (1 point)
    attendu = min(0.01 * 100_000 / 0.1, 4 * 100_000 / 101.2)        # 1 % du capital au stop, levier max 4
    assert tr["Size"].iloc[0] == pytest.approx(attendu)


def test_filtre_volume_relatif():
    hist, jour = _historique()
    prix, _ = _test_jour(None)
    m = pd.concat(hist + [_seance(jour, prix, vol_ouverture=900.0)])  # 90 % de la moyenne -> pas de trade
    assert len(O.portefeuille(m, capital=100_000.0).trades.records_readable) == 0
    assert len(O.portefeuille(m, capital=100_000.0, filtre_volume=False).trades.records_readable) == 1
