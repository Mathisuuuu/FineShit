"""Tableau de bord : tests de sur-ajustement sur des rendements construits (signal reel contre bruit pur)."""
import numpy as np
import pandas as pd

from nexus.tableau import bloc_surajustement


def _famille(derive, seed=0, n=2520, k=12):
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range("2016-01-04", periods=n)
    base = rng.normal(derive, 0.01, n)
    cols = {f"r={i}": base + rng.normal(0, 0.004, n) for i in range(k)}
    return pd.DataFrame(cols, index=idx)


def _verdicts(tests):
    return {t["test"].split(" (")[0].split(" :")[0]: t["verdict"] for t in tests}


def test_signal_reel_passe():
    R = _famille(0.0012)                        # Sharpe annuel ~1,9
    nul = dict(titre="Hasard", valeurs=list(np.random.default_rng(1).normal(0, 0.3, 500)), observe=1.9, detail="test")
    tests, out = bloc_surajustement(R["r=0"], R, "r=0", essais=12, nul=nul, reps=300)
    v = _verdicts(tests)
    assert v["Test SPA de Hansen"] == "ok" and v["Hasard"] == "ok" and v["Duree minimale de backtest"] == "ok"
    assert len(out["blocs"]) == 6 and out["nul"]["p"] < 0.01


def test_bruit_pur_echoue():
    R = _famille(0.0, seed=3)
    tests, out = bloc_surajustement(R["r=0"], R, "r=0", essais=100, reps=300)
    v = _verdicts(tests)
    assert v["Test SPA de Hansen"] == "alerte"
    assert v["Duree minimale de backtest"] == "alerte"
