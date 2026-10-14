"""Tests du moteur : executions a l ouverture suivante, stops, limites, couts, absence de biais
d anticipation, rejeu vectorbt identique, chargement des fichiers de cotations."""
import math

import numpy as np
import pandas as pd
import pytest

from nexus import data as D
from nexus import mathx as M
from nexus.engine import NexusStrategy, split_list
from nexus.strategies import available, get


def _df(rows, start="2024-01-01"):
    idx = pd.bdate_range(start, periods=len(rows))
    return pd.DataFrame(rows, columns=["open", "high", "low", "close", "volume"], index=idx)


class Scripted(NexusStrategy):
    """Strategie pilotee par un script {indice de jour: (qty, stop, kind, limit)}."""
    NAME = "Test"
    DEFAULTS = dict(symbols="AAA", sizing_mode="natif", use_circuit_breakers=False, slippage_pct=0.0)

    def __init__(self, script, **kw):
        super().__init__(**kw)
        self.script = script

    def on_data_loaded(self):
        self.i = -1

    def on_batch(self, day):
        self.i += 1
        if self.i in self.script:
            q, stop, kind, lim = self.script[self.i]
            self.set_target(self.sym("AAA"), q, stop, f"jour {self.i}", kind, lim)


def test_ordre_execute_a_l_ouverture_suivante():
    rows = [(10, 10, 10, 10, 1)] * 2 + [(11, 12, 10.5, 11.5, 1), (12, 13, 11.5, 12.5, 1), (13, 13, 12, 12, 1)]
    st = Scripted({1: (10, M.NAN, "market", M.NAN), 3: (0, M.NAN, "market", M.NAN)})
    res = st.run({"AAA": _df(rows)})
    t = res.trades[0]
    assert t.entry_price == 11 and t.exit_price == 13          # ouvertures des jours 2 et 4
    assert abs(t.gross_pnl - 20) < 1e-9
    assert res.equity.iloc[2] == pytest.approx(100000 + 10 * (11.5 - 11))


def test_stop_au_prix_et_gap():
    rows = [(10, 10, 10, 10, 1), (10, 10, 10, 10, 1), (10, 10.2, 9.0, 9.5, 1), (9.5, 9.6, 9.4, 9.5, 1)]
    st = Scripted({1: (10, 9.5, "market", M.NAN)})
    res = st.run({"AAA": _df(rows)})
    t = res.trades[0]
    assert t.exit_reason == "stop" and t.exit_price == pytest.approx(9.5)   # touche dans la barre d entree
    rows = [(10, 10, 10, 10, 1), (10, 10, 10, 10, 1), (10, 10, 9.9, 10, 1), (8.0, 8.5, 7.5, 8.2, 1)]
    st = Scripted({1: (10, 9.5, "market", M.NAN)})
    res = st.run({"AAA": _df(rows)})
    assert res.trades[0].exit_price == 8.0                                 # gap sous le stop -> ouverture


def test_ordre_limite_valable_une_barre():
    rows = [(10, 10, 10, 10, 1), (10, 10, 10, 10, 1), (10.2, 10.5, 10.1, 10.3, 1), (9.8, 10, 9.7, 9.9, 1)]
    st = Scripted({1: (5, M.NAN, "limit", 10.0)})
    res = st.run({"AAA": _df(rows)})
    assert len(res.fills) == 0                                              # pas touchee le jour 2 -> expiree
    rows[2] = (10.2, 10.5, 9.9, 10.3, 1)
    st = Scripted({1: (5, M.NAN, "limit", 10.0)})
    res = st.run({"AAA": _df(rows)})
    assert res.fills.iloc[0]["price"] == 10.0


def test_couts_modelises():
    rows = [(100, 100, 100, 100, 1)] * 4
    st = Scripted({0: (10, M.NAN, "market", M.NAN), 1: (0, M.NAN, "market", M.NAN)}, slippage_pct=0.05)
    res = st.run({"AAA": _df(rows)})
    assert res.trades[0].costs == pytest.approx(2 * 1000 * 0.0005)
    assert res.equity.iloc[-1] == pytest.approx(100000 - 1.0)


def test_disjoncteur_drawdown_bloque_les_entrees():
    rows = [(100, 100, 100, 100, 1)] * 3 + [(100, 100, 50, 50, 1)] + [(50, 50, 50, 50, 1)] * 3
    st = Scripted({1: (1500, M.NAN, "market", M.NAN), 3: (1600, M.NAN, "market", M.NAN)},
                  use_circuit_breakers=True, drawdown_trip_pct=15.0)
    res = st.run({"AAA": _df(rows)})
    assert st.breaker.drawdown_trips == 1
    assert any("Entree rejetee" in l for l in res.log)


def test_pas_de_biais_d_anticipation():
    """Modifier les donnees APRES une date ne change aucune decision avant cette date."""
    syms = ["SPY", "QQQ", "AAPL", "MSFT", "XLF", "XLE"]
    u = D.synthetic_universe(syms, "2014-01-02", "2019-12-31", seed=11)
    cut = pd.Timestamp("2018-06-29")
    u2 = {}
    for k, v in u.items():
        v2 = v.copy()
        after = v2.index > cut
        v2.loc[after, ["open", "high", "low", "close"]] *= 3.0
        u2[k] = v2
    for code in ("01", "02", "14"):
        a = get(code)(symbols=",".join(syms)).run(u, report=False)
        b = get(code)(symbols=",".join(syms)).run(u2, report=False)
        fa = a.fills[pd.to_datetime(a.fills["time"]) <= cut]
        fb = b.fills[pd.to_datetime(b.fills["time"]) <= cut]
        pd.testing.assert_frame_equal(fa.reset_index(drop=True), fb.reset_index(drop=True))
        pd.testing.assert_series_equal(a.equity[:cut], b.equity[:cut])


def test_rejeu_vectorbt_identique():
    vb = pytest.importorskip("nexus.vbt_bridge")
    syms = ["SPY", "QQQ", "AAPL", "MSFT", "XLF", "XLE", "XLK", "JPM"]
    u = D.synthetic_universe(syms, "2014-01-02", "2019-12-31", seed=3)
    res = get("02")(symbols=",".join(syms[:-2])).run(u)
    pf, daily, diff = vb.to_portfolio(res)
    assert diff < 1e-9


@pytest.mark.parametrize("code", available())
def test_toutes_les_strategies_tournent(code):
    klass = get(code)
    st = klass()
    syms = set(split_list(st.p.symbols)) | set(st.required_references())
    if getattr(klass, "INTRADAY", False):
        from nexus import intraday as I
        u = {st.data_symbols()[0]: I.synthetic_minutes("2018-01-02", "2019-12-31", seed=5)}
    else:
        u = D.synthetic_universe(sorted(syms), "2016-01-04", "2019-12-31", seed=5)
    res = st.run(u)
    assert len(res.equity) > 100 and math.isfinite(res.equity.iloc[-1])
    assert "RAPPORT NEXUS" in res.report


def test_lecture_des_formats(tmp_path):
    (tmp_path / "SPY.Last.txt").write_text("20240102;470.1;472.0;469.5;471.2;1000\n20240103;471.0;473.0;470.0;472.5;1200\n")
    (tmp_path / "BTC-USD.csv").write_text("Date,Open,High,Low,Close,Adj Close,Volume\n2024-01-01,42000,43000,41000,42500,42500,10\n2024-01-02,42500,45000,42000,44900,44900,12\n")
    (tmp_path / "EURUSD_D1.csv").write_text("<DATE>\t<TIME>\t<OPEN>\t<HIGH>\t<LOW>\t<CLOSE>\t<TICKVOL>\n2024.01.02\t00:00:00\t1.10\t1.11\t1.09\t1.095\t100\n")
    (tmp_path / "aapl_daily.csv").write_text("date;ouverture;haut;bas;cloture;volume\n02/01/2024;185,5;188,4;183,9;185,6;1000\n")
    data = D.load_folder(str(tmp_path))
    assert set(data) == {"SPY", "BTCUSD", "EURUSD", "AAPL"}
    assert data["SPY"]["close"].iloc[-1] == 472.5
    assert data["AAPL"]["open"].iloc[0] == 185.5
    assert data["EURUSD"].index[0] == pd.Timestamp("2024-01-02")
