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


# =============================================================================
#  Strategies du runner local : memes objets vectorbt (nexus.tableau_runner)
# =============================================================================
def test_runner_trades_rejoues_dans_vectorbt():
    from nexus.tableau_runner import normaliser, ordres, portefeuille
    t = pd.DataFrame(dict(direction=[1, -1, 1], qty=[2, 1, 1],
                          entry_time=["2024-03-04 15:00", "2024-03-04 16:00", "2024-03-05 15:00"],
                          exit_time=["2024-03-04 16:00", "2024-03-04 16:00", "2024-03-05 15:00"],
                          entry_price=[5000.0, 5010.0, 5020.0], exit_price=[5010.0, 5005.0, 5020.0],
                          pnl=[2 * 10 * 5 - 2 * 2 * 0.6, 5 * 5 - 2 * 0.6, -2 * 0.6], reason="x", tag="t", instrument="ES"))
    n = normaliser(t, dict(kind="qf", inst="MES"))
    assert (n["mult"] == 5.0).all() and np.allclose(n["frais"], [2.4, 1.2, 1.2])          # commission 0,60 $ par cote
    o = ordres(n)
    assert o["t"].is_unique and len(o) == 6
    # a 16:00 : sortie du 1er trade, puis entree et sortie du 2e (ouvert et ferme au meme instant pres)
    seize = o[o["t"].dt.floor("min") == pd.Timestamp("2024-03-04 16:00")]
    assert list(seize["size"]) == [-10.0, -5.0, 5.0]
    pf, buf, daily = portefeuille(n, 10000.0)
    fin = float(np.asarray(pf.value(), float).ravel()[-1] - buf)
    assert abs(fin - 10000.0 - t["pnl"].sum()) < 1e-6                                   # P&L vectorbt = P&L du moteur
    assert len(pf.trades.records_readable) >= 3
    assert daily.index[0] == pd.Timestamp("2024-03-04")                                   # valorisation par seance


def test_runner_valeur_du_point_reconnue():
    from nexus.tableau_runner import normaliser
    t = pd.DataFrame(dict(strategie="x", instrument=["GC", "GC"], sens=[-1, 1], qty=[9, 10],
                          entry_time=["2016-02-19 20:31", "2016-02-23 20:31"], entry_price=[1879.1, 1873.7],
                          exit_time=["2016-02-19 21:00", "2016-02-23 21:00"], exit_price=[1879.4, 1875.7],
                          reason="temps", pnl=[-37.8, 188.0], r=0.0, jour="2016-02-19"))
    n = normaliser(t, dict(kind="or"))
    assert (n["mult"] == 10.0).all() and np.allclose(n["frais"], [10.8, 12.0])           # micro-or MGC : 10 $ le point


def test_drapeaux_intraday_par_seance_cme():
    from nexus.tableau import drapeaux, positions_fiche
    f = dict(origine="tableau", instruments=["NQ"], fuseau_trades="America/New_York",
             trades=[dict(entree="2024-03-04 09:31", sortie="2024-03-04 15:59"), dict(entree="2024-03-04 18:05", sortie="2024-03-05 10:00")])
    p = positions_fiche(f)
    d = drapeaux(f, p)
    assert d["futures"] and d["intraday"] and d["part_nuit"] == 0.0                        # 18:05 -> 10:00 : meme seance CME
    f["trades"].append(dict(entree="2024-03-05 13:30", sortie="2024-03-06 08:20"))          # tenue a travers 17:00
    d = drapeaux(f, positions_fiche(f))
    assert not d["intraday"] and d["part_nuit"] > 0.3


def test_prop_fiabilite_statistiques_vectorbt():
    from nexus import prop_combinaisons as PC
    from nexus import validation as V
    rng = np.random.default_rng(3)
    idx = pd.bdate_range("2016-01-04", periods=2600)
    bon = pd.Series(rng.normal(0.0008, 0.01, len(idx)), idx)            # Sharpe vrai ~1,3
    nul = pd.Series(rng.normal(0.0, 0.01, len(idx)), idx)
    # Sharpe deflate vectorbt avec la variance nulle = controle nexus.validation (meme definition que la recherche)
    for r in (bon, nul):
        d_vbt, (d_val, _) = PC.dsr(r, 378), V.deflated_sharpe(r.to_numpy(), 378)
        assert abs(d_vbt - d_val) < 0.02
    m_bon, m_nul = PC.mesures(bon, 378, b=300), PC.mesures(nul, 378, b=300)
    assert m_bon["fiable"] and m_bon["ic_bas"] > 0 and m_bon["ic_bas"] < m_bon["sharpe"] < m_bon["ic_haut"]
    assert not m_nul["fiable"]
    # combinaison : moyenne des strategies ramenees au meme risque, seulement les seances ou toutes existent
    R = pd.DataFrame({"a": bon, "b": nul * 2})
    R.loc[idx[:10], "b"] = np.nan
    vols = {c: float(R[c].std(ddof=1)) for c in R}
    s = PC.serie_combo(R, vols, ["a", "b"])
    assert len(s) == len(idx) - 10
    t = idx[20]
    assert abs(s[t] - (R.loc[t, "a"] * 0.01 / vols["a"] + R.loc[t, "b"] * 0.01 / vols["b"]) / 2) < 1e-15
    corr = R.corr()
    conf = pd.DataFrame(0.0, index=["a", "b"], columns=["a", "b"])
    cb = PC.enumerer(["a", "b"], corr, conf)
    assert [c["ids"] for c in cb] == [["a"], ["b"], ["a", "b"]] and cb[2]["corr_max"] == abs(corr.loc["a", "b"])


def test_prop_evaluation_regles():
    from nexus import prop_combinaisons as PC
    regles = dict(compte=50000, objectif=300, perte_jour=1000, dd=2000, horizon=50)
    gain = np.full(200, 100.0)                     # objectif atteint au 3e jour, toujours
    assert PC.reussite(gain, 1.0, regles) == 1.0
    perte = np.full(200, -100.0)                   # drawdown suiveur de 2 000 $ franchi au 21e jour
    assert PC.reussite(perte, 1.0, regles) == 0.0
    choc = np.r_[np.full(100, 10.0), -1500.0, np.full(99, 10.0)]
    k, rs = PC.meilleure_taille(choc, dict(regles, objectif=500), [0.5, 1.0, 2.0])
    assert k == 2.0 and 0 < rs < 1                 # plus grande taille : objectif plus vite, avant la perte du jour
