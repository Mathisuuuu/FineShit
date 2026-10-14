"""Fiche 16 (Noise Area) : regles sur une seance construite a la main, absence de biais d anticipation,
fuseau et horodatage des barres, demi-seances, couts, taille, filtre gamma, rejeu vectorbt."""
import math

import numpy as np
import pandas as pd
import pytest

from nexus import data as D
from nexus import intraday as I
from nexus.strategies import get

NA = get("16")
FREE = dict(commission_per_unit=0.0, commission_min_per_order=0.0, slippage_ticks=0.0)


def _day(date, closes, opens=None, vol=1000.0):
    """Une seance 9:31 -> 16:00 (horodatage fin de barre) a partir des 390 clotures."""
    closes = np.asarray(closes, float)
    opens = np.r_[closes[0], closes[:-1]] if opens is None else np.asarray(opens, float)
    idx = pd.Timestamp(date) + pd.to_timedelta(np.arange(571, 571 + len(closes)), unit="min")
    return pd.DataFrame({"open": opens, "high": np.maximum(opens, closes), "low": np.minimum(opens, closes),
                         "close": closes, "volume": vol}, index=idx)


def _scenario(prev_level=100.2):
    """15 seances de chauffage : |Close(t)/Open - 1| = 0.2 % a chaque minute (sigma = 0.002), veille close a
    prev_level. Seance testee, Open 100 et veille 100.2 : Upper = 100.2 x 1.002 = 100.4004, Lower = 99.8."""
    days = pd.bdate_range("2024-01-02", periods=16)
    frames = []
    for i, d in enumerate(days[:-1]):
        lvl = prev_level if (len(days) - 2 - i) % 2 == 0 else 200.0 - prev_level
        c = np.full(390, lvl)
        frames.append(_day(d, c, opens=np.r_[100.0, c[:-1]]))
    c = np.full(390, 100.0)
    c[29] = 100.5                 # 10:00 : cassure haute (> Upper et > VWAP) -> long a l ouverture de 10:00-10:01
    c[30] = 100.6
    c[31:88] = 100.5
    c[88:119] = 100.38            # 11:00 : < Upper ajuste du gap (100.4004) mais > Open x 1.002 et > VWAP -> sortie
    c[119:] = 99.7                # 11:30 : < Lower et < VWAP -> short
    c[389] = 99.6                 # cloture : sortie MOC
    o = np.r_[100.0, c[:-1]]
    o[30], o[90], o[120] = 100.55, 100.29, 99.69
    frames.append(_day(days[-1], c, opens=o))
    return pd.concat(frames), days[-1]


def test_regles_sur_une_seance_construite():
    df, test_day = _scenario()
    res = NA(sizing="fixe", fixed_leverage=1.0, **FREE).run({"SPY": df}, trade_start=test_day)
    t = res.trades
    assert [x.direction for x in t] == [1, -1]
    assert t[0].entry_time == pd.Timestamp(f"{test_day:%Y-%m-%d} 10:00") and t[0].entry_price == 100.55
    assert t[0].exit_time == pd.Timestamp(f"{test_day:%Y-%m-%d} 11:00") and t[0].exit_price == 100.29
    assert t[0].exit_reason == "stop bande" and t[0].max_qty == 1000      # 100 000 x 1 / Open 100
    assert t[1].entry_time == pd.Timestamp(f"{test_day:%Y-%m-%d} 11:30") and t[1].entry_price == 99.69
    assert t[1].exit_time == pd.Timestamp(f"{test_day:%Y-%m-%d} 16:00") and t[1].exit_price == 99.6
    assert t[1].exit_reason == "fin de seance"
    assert res.equity.iloc[-1] == pytest.approx(100000 + 1000 * (100.29 - 100.55) + 1000 * (99.69 - 99.6))


def test_bande_ajustee_du_gap():
    """Veille a 99.8 : Upper = max(100, 99.8) x 1.002 = 100.2 -> 100.38 reste au-dessus, le long tient
    jusqu a 11:30 (sous le VWAP) ; Lower = 99.8 x 0.998 = 99.6004 -> pas de short a 99.7."""
    df, test_day = _scenario(prev_level=99.8)
    res = NA(sizing="fixe", **FREE).run({"SPY": df}, trade_start=test_day)
    assert len(res.trades) == 1 and res.trades[0].direction == 1
    assert res.trades[0].exit_time == pd.Timestamp(f"{test_day:%Y-%m-%d} 11:30")
    assert res.trades[0].exit_reason == "stop VWAP"


def test_execution_au_prix_du_franchissement_et_cloture_suivante():
    df, test_day = _scenario()
    res = NA(sizing="fixe", execution="cloture", **FREE).run({"SPY": df}, trade_start=test_day)
    assert res.trades[0].entry_price == 100.5 and res.trades[0].entry_time.minute == 0
    res = NA(sizing="fixe", execution="cloture_suivante", **FREE).run({"SPY": df}, trade_start=test_day)
    assert res.trades[0].entry_price == 100.6 and res.trades[0].entry_time == pd.Timestamp(f"{test_day:%Y-%m-%d} 10:01")


def test_sortie_avant_la_cloture_et_stop_minute():
    df, test_day = _scenario()
    res = NA(sizing="fixe", exit_minutes_before_close=10, **FREE).run({"SPY": df}, trade_start=test_day)
    assert res.trades[-1].exit_time == pd.Timestamp(f"{test_day:%Y-%m-%d} 15:50")
    # stop verifie chaque minute : cloture 100.38 a 10:59 -> sortie a l ouverture de la barre 10:59-11:00
    res = NA(sizing="fixe", stop_check="minute", **FREE).run({"SPY": df}, trade_start=test_day)
    assert res.trades[0].exit_time == pd.Timestamp(f"{test_day:%Y-%m-%d} 10:59")
    assert res.trades[0].exit_reason == "stop minute" and res.trades[0].exit_price == 100.38


def test_sigma_du_jour_exclu():
    move = np.array([[1.0], [2.0], [3.0], [np.nan], [5.0]])
    out = I.slot_mean_prev(move, 2)
    assert np.isnan(out[0, 0]) and np.isnan(out[1, 0])
    assert out[2, 0] == 1.5 and np.isnan(out[3, 0]) and out[4, 0] == 2.5


def test_pas_de_biais_d_anticipation():
    df = I.synthetic_minutes("2020-01-02", "2020-12-31", seed=11)
    res = NA().run({"SPY": df}, report=False)
    cut = pd.Timestamp("2020-09-15 12:00")
    df2 = df.copy()
    late = df2.index > cut
    df2.loc[late, ["open", "high", "low", "close"]] *= 1.07
    res2 = NA().run({"SPY": df2}, report=False)
    f1 = res.fills[res.fills["time"] < cut].reset_index(drop=True)
    f2 = res2.fills[res2.fills["time"] < cut].reset_index(drop=True)
    pd.testing.assert_frame_equal(f1, f2)
    before = res.equity.index < cut.normalize()
    assert np.allclose(res.equity[before], res2.equity[before])


def test_fuseau_paris_et_horodatage_debut(tmp_path):
    """Fichier NinjaTrader en heure de Paris, barres datees au debut : memes trades qu en heure de New York."""
    df = I.synthetic_minutes("2021-03-01", "2021-04-30", seed=2, extended_hours=True)
    ref = NA(lookback_days=5, vol_lookback_days=5).run({"SPY": df}, report=False)
    paris = df.copy()
    paris.index = (pd.DatetimeIndex(df.index) - pd.Timedelta(minutes=1)).tz_localize(I.NY).tz_convert("Europe/Paris").tz_localize(None)
    lines = [f"{t:%Y%m%d %H%M%S};{r.open:.6f};{r.high:.6f};{r.low:.6f};{r.close:.6f};{int(r.volume)}"
             for t, r in zip(paris.index, paris.itertuples())]
    (tmp_path / "SPY.Last.txt").write_text("\n".join(lines) + "\n")
    data = D.load_folder(str(tmp_path), daily=False, only=["SPY"])
    assert I.detect_bar_label(I.to_new_york(data["SPY"], "Europe/Paris"))[0] == "debut"
    res = NA(lookback_days=5, vol_lookback_days=5, data_timezone="Europe/Paris").run(data, report=False)
    assert len(res.trades) == len(ref.trades) > 0
    assert [t.entry_time for t in res.trades] == [t.entry_time for t in ref.trades]
    assert res.equity.iloc[-1] == pytest.approx(ref.equity.iloc[-1], rel=1e-4)
    with pytest.raises(ValueError, match="fuseau"):
        NA(lookback_days=5, data_timezone="Asia/Tokyo").run(data, report=False)


def test_demi_seance():
    df = I.synthetic_minutes("2022-11-01", "2022-11-30", seed=4)
    day = pd.Timestamp("2022-11-25")
    df = df[~((df.index.normalize() == day) & (df.index > day + pd.Timedelta(hours=13)))]
    g = I.build_grid(df)
    k = g.days.get_loc(day)
    assert g.half_day[k] and g.last_slot[k] == I.HALF_DAY_LAST_SLOT and g.valid[k]
    res = NA(lookback_days=5, vol_lookback_days=5).run({"SPY": df}, report=False)
    assert all(t.exit_time <= day + pd.Timedelta(hours=13) for t in res.trades if t.exit_time.normalize() == day)


def test_couts_futures_et_taille_vol_cible():
    df = I.synthetic_minutes("2019-01-02", "2019-12-31", seed=6)
    es = df.copy()
    es[["open", "high", "low", "close"]] *= 10
    res = NA(symbols="ES").run({"ES": es}, report=False)
    assert len(res.fills) and np.allclose(res.fills["cost"], np.abs(res.fills["qty"]) * (2.25 + 0.5 * 0.25 * 50))
    pan = res.daily_panel
    k = pan.index[pan["trade"]][20]
    lev = min(0.02 / pan.at[k, "vol_14j"], 4.0)
    prev_eq = pan["equity"].shift(1).at[k]
    assert pan.at[k, "levier"] == pytest.approx(lev)
    assert pan.at[k, "unites"] == math.floor(prev_eq * lev / (pan.at[k, "open"] * 50) + 0.5)
    spy = NA().run({"SPY": df}, report=False)
    f = spy.fills
    assert np.allclose(f["cost"], np.maximum(0.35, 0.0035 * f["qty"].abs()) + 0.001 * f["qty"].abs())


def test_momentum_plante_detecte_et_bruit_sans_avantage():
    planted = NA(**FREE).run({"SPY": I.synthetic_minutes("2016-01-04", "2020-12-31", seed=8, momentum=0.03)}, report=False)
    noise = NA(**FREE).run({"SPY": I.synthetic_minutes("2016-01-04", "2020-12-31", seed=8, momentum=0.0)}, report=False)
    sh = lambda r: r.mean() / r.std() * np.sqrt(252)
    assert sh(planted.returns) > 1.0
    assert abs(sh(noise.returns)) < 1.0


def test_filtre_gamma(tmp_path):
    df = I.synthetic_minutes("2020-01-02", "2020-06-30", seed=9)
    days = pd.bdate_range("2020-02-01", "2020-06-30")
    gex = pd.DataFrame({"date": days.strftime("%Y-%m-%d"), "underlying": "SPX",
                        "gex": np.where(np.arange(len(days)) % 2 == 0, -1e9, 1e9)})
    path = tmp_path / "gex.csv"
    path.write_text("# commentaire\n" + gex.to_csv(index=False))
    res = NA(gex_file=str(path), gamma_filter="court", gamma_unknown="pas_de_trade").run({"SPY": df})
    neg = set(days[::2])
    assert res.trades and all(t.entry_time.normalize() in neg for t in res.trades)
    assert "Regime gamma" in res.report and "court gamma" in res.report


def test_regime_vix_et_rapport():
    df = I.synthetic_minutes("2019-01-02", "2020-12-31", seed=12)
    vix = D.synthetic_universe(["^VIX"], "2018-12-01", "2020-12-31", seed=1)["^VIX"]
    res = NA().run({"SPY": df, "^VIX": vix})
    assert "Regime VIX" in res.report and "Criteres de rejet" in res.report and "Par annee" in res.report


def test_rejeu_vectorbt_identique():
    vb = pytest.importorskip("nexus.vbt_bridge")
    df = I.synthetic_minutes("2019-01-02", "2019-12-31", seed=13)
    for kw in (dict(), dict(execution="cloture_suivante", stop_check="minute"), dict(symbols="MES")):
        data = {"MES": df} if kw.get("symbols") == "MES" else {"SPY": df}
        res = NA(**kw).run(data, report=False)
        _, _, diff = vb.intraday_portfolio(res)
        assert diff < 1e-9


def test_series_futures_individuelles_refusees():
    df = I.synthetic_minutes("2019-01-02", "2019-02-28", seed=1)
    with pytest.raises(ValueError, match="Merge Back Adjusted"):
        NA(symbols="ES").run({"ES03-19": df, "ES06-19": df}, report=False)
    assert D.symbol_from_filename("ES ##-##.Last.txt") == "ES"


def test_entree_sans_filtre_vwap():
    """Close > Upper mais < VWAP a 10:00 : pas d entree par defaut (code des auteurs), entree avec la regle
    litterale de la fiche (vwap_entry_filter=false), puis stop max(Upper, VWAP) au controle suivant."""
    df, test_day = _scenario()
    day = df.index.normalize() == test_day
    c = df.loc[day, "close"].to_numpy().copy()
    c[:29] = 100.9                    # VWAP tire vers le haut avant 10:00
    c[29] = 100.5                     # > Upper 100.4004 mais < VWAP ~100.88
    c[30:89] = 100.45
    o = np.r_[100.0, c[:-1]]
    df.loc[day, "close"], df.loc[day, "open"] = c, o
    df.loc[day, "high"], df.loc[day, "low"] = np.maximum(o, c), np.minimum(o, c)
    res = NA(sizing="fixe", **FREE).run({"SPY": df}, trade_start=test_day)
    assert all(t.entry_time.hour * 60 + t.entry_time.minute > 600 for t in res.trades)
    res = NA(sizing="fixe", vwap_entry_filter=False, **FREE).run({"SPY": df}, trade_start=test_day)
    t = res.trades[0]
    assert t.direction == 1 and t.entry_time == pd.Timestamp(f"{test_day:%Y-%m-%d} 10:00")
    assert t.exit_time == pd.Timestamp(f"{test_day:%Y-%m-%d} 10:30") and t.exit_reason == "stop VWAP"


def _globex_utc(start, end, seed=3):
    """Barres 1 minute 24 h/24 en UTC (dimanche 23:00 -> vendredi 22:00), marche aleatoire."""
    idx = pd.date_range(start, end, freq="1min")
    idx = idx[(idx.dayofweek < 5) | ((idx.dayofweek == 6) & (idx.hour >= 23))]
    idx = idx[~((idx.dayofweek == 4) & (idx.hour >= 22))]
    rng = np.random.default_rng(seed)
    c = 4000 * np.exp(np.cumsum(rng.normal(0, 3e-4, len(idx))))
    o = np.r_[c[0], c[:-1]]
    return pd.DataFrame({"open": o, "high": np.maximum(o, c), "low": np.minimum(o, c), "close": c,
                         "volume": rng.integers(50, 500, len(idx)).astype(float)}, index=idx)


def test_roll_a_minuit_utc_ajuste():
    df = _globex_utc("2023-02-26 23:00", "2023-04-14 21:59")
    k = df.index.get_loc(pd.Timestamp("2023-03-15 00:00"))
    raw = df.copy()
    raw.iloc[k:, :4] *= 1.0105                                   # roll : +105 bp
    adj, rolls = I.adjust_rolls_midnight_utc(raw, "UTC")
    assert len(rolls) == 1 and rolls["utc"].iloc[0] == pd.Timestamp("2023-03-15")
    assert rolls["saut_bp"].iloc[0] == pytest.approx(104.5, abs=3)
    assert abs(math.log(adj["open"].iloc[k] / adj["close"].iloc[k - 1])) < 5e-4
    assert np.allclose(adj["close"].iloc[k:], raw["close"].iloc[k:])           # derniere echeance inchangee
    _, none = I.adjust_rolls_midnight_utc(df, "UTC")                            # serie deja continue
    assert none.empty


def test_parquet_utc_feries_et_noms_databento(tmp_path):
    pytest.importorskip("pyarrow")
    df = _globex_utc("2023-12-03 23:00", "2024-02-29 21:59", seed=5)
    utc = df.copy()
    utc.index = utc.index.tz_localize("UTC").rename("ts_event")
    utc.to_parquet(tmp_path / "ES_v0_1m.parquet")
    data = D.load_folder(str(tmp_path), daily=False, only=["ES"])
    assert list(data) == ["ES"] and data["ES"].attrs.get("fuseau") == "UTC"
    res = NA(symbols="ES", lookback_days=5, vol_lookback_days=5).run(data)       # fuseau lu dans le fichier
    pan = res.daily_panel
    assert pd.Timestamp("2024-01-15") not in pan.index                          # Martin Luther King : ferie NYSE
    assert pd.Timestamp("2024-01-16") in pan.index and "feries NYSE exclus" in res.report
    assert {"2024-01-15", "2024-03-29", "2022-06-20", "2025-01-09"} <= set(I.nyse_holidays("2022-01-01", "2025-12-31").strftime("%Y-%m-%d"))
    assert pd.Timestamp("2021-12-31") not in I.nyse_holidays("2021-12-01", "2022-01-31")


def test_recapitulatif_tout_avec_barres_minute(tmp_path):
    """`tout` : la fiche 16 tourne sur chaque instrument present en barres minute, les fiches journalieres
    sans donnees sont ignorees sans arreter le recapitulatif ; un -p inconnu d une fiche ne la bloque pas."""
    pytest.importorskip("pyarrow")
    from nexus.__main__ import main
    df = _globex_utc("2023-12-03 23:00", "2024-02-29 21:59", seed=7)
    df.index = df.index.tz_localize("UTC").rename("ts_event")
    (tmp_path / "minute").mkdir()
    df.to_parquet(tmp_path / "minute" / "ES_v0_1m.parquet")
    df.to_parquet(tmp_path / "minute" / "NQ_v0_1m.parquet")
    main(["tout", "-d", str(tmp_path / "minute"), "--sortie", str(tmp_path / "out"),
          "-p", "lookback_days=5", "-p", "vol_lookback_days=5", "-p", "initial_bankroll=1000000"])
    recap = pd.read_csv(next((tmp_path / "out").glob("tout_*")) / "recapitulatif.csv")
    assert list(recap["strategie"]) == ["Nexus16_NoiseAreaMomentum_ES", "Nexus16_NoiseAreaMomentum_NQ"]
    assert (recap["trades"] > 0).all()
