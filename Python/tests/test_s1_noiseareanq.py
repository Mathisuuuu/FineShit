"""S1_NoiseAreaNQ (strategie validee) : reglage fige, identite avec la fiche 16 au meme reglage, identite du
fichier autonome S1_NoiseAreaNQ.py avec le moteur, et resultat de reference sur les donnees Cotations (si presentes)."""
import importlib.util
import os

import numpy as np
import pandas as pd
import pytest

from nexus import intraday as I
from nexus.strategies import get
from nexus.strategies.s1_noiseareanq import FROZEN, REFERENCE

ICI = os.path.dirname(__file__)
AUTONOME = os.path.join(ICI, "..", "S1_NoiseAreaNQ.py")
COTATIONS_NQ = os.environ.get("COTATIONS_NQ", next(
    (p for p in (os.path.join(ICI, "..", "..", "Cotations", "indices", "NQ_v0_1m.parquet"),         # dossier du depot
                 os.path.join(ICI, "..", "..", "..", "cotations", "indices", "NQ_v0_1m.parquet"))  # depot voisin
     if os.path.exists(p)), ""))


def _autonome():
    spec = importlib.util.spec_from_file_location("s1_autonome", AUTONOME)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def synth():
    """Deux ans de minutes synthetiques avec momentum (heure de New York, horodatage fin de barre)."""
    return I.synthetic_minutes("2019-01-02", "2020-12-31", seed=3, momentum=0.35, price0=2000.0)


def test_s1_enregistree_et_figee():
    k = get("S1")
    assert get("s1") is k and get("S1_NoiseAreaNQ") is k
    st = k()
    for key, v in FROZEN.items():
        assert st.params[key] == v
    assert (st.p.lookback_days, st.p.check_interval_min, st.p.band_mult) == (30, 30, 1.2)
    assert (st.p.target_daily_vol_pct, st.p.vol_lookback_days, st.p.max_leverage) == (2.0, 14, 4.0)


def test_s1_refuse_un_reglage_modifie():
    with pytest.raises(ValueError, match="fige"):
        get("S1")(band_mult=1.0)
    with pytest.raises(ValueError, match="fige"):
        get("S1")(symbols="ES")
    # reglages de donnees et capital : libres
    st = get("S1")(initial_bankroll=250_000.0, data_timezone="Europe/Paris", bar_label="fin", roll_adjust="aucun")
    assert st.p.initial_bankroll == 250_000.0


def test_s1_identique_a_la_fiche16_au_meme_reglage(synth):
    a = get("S1")(initial_bankroll=1e6).run({"NQ": synth}, report=False)
    b = get("16")(**FROZEN, initial_bankroll=1e6).run({"NQ": synth}, report=False)
    assert len(a.trades) == len(b.trades) > 50
    assert np.allclose(a.equity.to_numpy(), b.equity.to_numpy(), rtol=0, atol=1e-6)


def test_fichier_autonome_identique_au_moteur(synth):
    A = _autonome()
    assert (A.SIGMA_SEANCES, A.CONTROLE_MIN, A.BANDE) == (FROZEN["lookback_days"], FROZEN["check_interval_min"], FROZEN["band_mult"])
    assert (A.VOL_CIBLE * 100, A.VOL_SEANCES, A.LEVIER_MAX) == (FROZEN["target_daily_vol_pct"], FROZEN["vol_lookback_days"], FROZEN["max_leverage"])
    res = get("S1")(initial_bankroll=1e6).run({"NQ": synth}, report=False)
    df = synth.copy()                       # le fichier autonome lit des barres UTC datees a leur debut
    df.index = (pd.DatetimeIndex(df.index) - pd.Timedelta(minutes=1)).tz_localize(A.NY).tz_convert("UTC")
    eq, trades = A.backtest(df, 1e6)
    both = pd.concat([res.equity.rename("moteur"), eq["equity"].rename("autonome")], axis=1).dropna()
    assert len(both) > 400
    assert np.allclose(both["moteur"], both["autonome"], rtol=0, atol=1e-6)
    assert len(trades) == len(res.trades)


@pytest.mark.skipif(not os.path.exists(COTATIONS_NQ), reason="donnees Cotations absentes (licence Databento, hors depot)")
def test_resultat_de_reference_sur_cotations():
    A = _autonome()
    df, en_utc = A.lire_minutes(COTATIONS_NQ, A.NY, "debut")
    assert en_utc
    df, _ = A.ajuster_rolls(df)
    eq, trades = A.backtest(df, REFERENCE["capital"])
    assert f"{eq.index[0]:%Y-%m-%d}" == REFERENCE["debut"] and f"{eq.index[-1]:%Y-%m-%d}" == REFERENCE["fin"]
    assert eq["equity"].iloc[-1] == pytest.approx(REFERENCE["equity_finale"], abs=1.0)
    assert len(trades) == REFERENCE["allers_retours"]
    assert "CONFORME" in A.controle_reference(eq, trades, REFERENCE["capital"])
