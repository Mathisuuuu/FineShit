"""Tests du moteur intrajournalier des strategies NinjaScript personnelles (nexus/perso)."""
import math
from datetime import date

import numpy as np
import pandas as pd
import pytest

from nexus.perso import qf
from nexus.perso import suite_s as S
from nexus.perso import user as U

INST = qf.Inst("TEST", "TEST", 10.0, 0.25, 1.0)


def _bars(rows, start="2024-03-04 14:31", freq="1min"):
    idx = pd.date_range(start, periods=len(rows), freq=freq)          # fin de barre, UTC
    return pd.DataFrame(rows, columns=["open", "high", "low", "close", "volume"], index=idx)


class Script:
    """Strategie pilotee : {indice de barre: fonction(engine)}."""

    def __init__(self, e, script):
        self.e, self.script = e, script

    def __call__(self, i):
        f = self.script.get(i)
        if f:
            f(self.e)


def _run(rows, script, slip=1):
    e = qf.Engine(_bars(rows), INST, slippage_ticks=slip)
    e.run(Script(e, script))
    return e


def test_marche_a_l_ouverture_suivante_avec_glissement_et_commission():
    rows = [(100, 100, 100, 100, 1), (101, 102, 100, 101, 1), (103, 104, 102, 103, 1), (105, 105, 104, 104, 1)]
    e = _run(rows, {1: lambda e: e.market(2), 2: lambda e: e.market(0)})
    t = e.trades[0]
    assert t.entry_price == 103 + 0.25 and t.exit_price == 105 - 0.25          # ouvertures des barres 2 et 3
    assert t.pnl == pytest.approx((104.75 - 103.25) * 2 * 10 - 4 * 1.0)


def test_stop_dans_la_barre_d_entree_et_gap():
    rows = [(100, 100, 100, 100, 1)] * 2 + [(100, 100.5, 98, 99, 1), (99, 99, 99, 99, 1)]
    e = _run(rows, {1: lambda e: e.market(1, stop=99.0)})
    assert e.trades[0].reason == "stop" and e.trades[0].exit_price == pytest.approx(99.0 - 0.25)
    rows = [(100, 100, 100, 100, 1)] * 2 + [(100, 100.5, 99.5, 100, 1), (97, 98, 96, 97, 1)]
    e = _run(rows, {1: lambda e: e.market(1, stop=99.0)})
    assert e.trades[0].exit_price == pytest.approx(97 - 0.25)                   # gap sous le stop -> ouverture


def test_objectif_et_stop_meme_barre_stop_retenu():
    rows = [(100, 100, 100, 100, 1)] * 2 + [(100, 103, 97, 100, 1)]
    e = _run(rows, {1: lambda e: e.market(1, stop=98.0, target=102.0)})
    assert e.trades[0].reason == "stop"
    rows = [(100, 100, 100, 100, 1)] * 2 + [(100, 103, 99.5, 102.5, 1)]
    e = _run(rows, {1: lambda e: e.market(1, stop=98.0, target=102.0)}, slip=0)
    assert e.trades[0].reason == "objectif" and e.trades[0].exit_price == 102.0


def test_ordre_limite_traverse_et_expiration():
    rows = [(100, 100, 100, 100, 1), (100, 100, 100, 100, 1), (100, 100.2, 99.8, 100, 1), (100, 100, 99, 99.5, 1)]
    e = _run(rows, {1: lambda e: e.limit(1, 99.5, 5)})
    assert e.pos == 0 and e.trades[0].entry_price == 99.5                      # rempli a la barre 3 (99 < 99.5)
    e = _run(rows, {1: lambda e: e.limit(1, 99.5, 1)})
    assert not e.trades                                                         # expire avant de passer sous 99.5


def test_sortie_en_fin_de_seance_a_la_cloture():
    rows = [(100, 100, 100, 100, 1)] * 4
    e = qf.Engine(_bars(rows), INST, slippage_ticks=0)

    def f(i):                                   # le moteur appelle la strategie a partir de la barre 1
        if i == 1:
            e.market(1)
        if i == 3:
            e.flatten_now(i)
    e.run(f)
    assert e.trades[0].exit_price == 100 and e.trades[0].reason == "fin de seance"


def test_declencheurs_horaires_qf():
    idx = pd.date_range("2024-03-04 14:00", "2024-03-04 21:00", freq="1min")    # 09:00 -> 16:00 ET (EST)
    df = pd.DataFrame({"open": 100.0, "high": 101.0, "low": 99.0, "close": 100.0, "volume": 1.0}, index=idx)
    e = qf.Engine(df, INST)
    hits = {"c": [], "f": []}

    class T(qf.QfBase):
        def on_quant_bar(self, i):
            if self.crossed_tod(qf.hhmm(1530)):
                hits["c"].append(e.et[i])
            if self.final_bar_before(qf.hhmm(1600)):
                hits["f"].append(e.et[i])
    e.run(T(e))
    assert [str(x.time()) for x in hits["c"]] == ["15:30:00"]
    assert [str(x.time()) for x in hits["f"]] == ["15:59:00"]


def test_calendrier_qf():
    assert S.us_holiday(date(2024, 3, 29)) and S.us_holiday(date(2024, 6, 19)) and not S.us_holiday(date(2024, 3, 28))
    assert S.is_eia_day(date(2024, 3, 6))                                         # mercredi
    assert S.is_eia_day(date(2024, 1, 18)) and not S.is_eia_day(date(2024, 1, 17))  # semaine du MLK : jeudi
    assert S.is_month_end_window(date(2024, 2, 29), 2) and S.is_month_end_window(date(2024, 2, 28), 2)
    assert not S.is_month_end_window(date(2024, 2, 27), 2)


def test_parite_de_risque_erc():
    cov = np.array([[0.04, 0.006], [0.006, 0.01]])
    w = S.erc_weights(cov, np.ones(2))
    rc = w * (cov @ w)
    assert rc[0] == pytest.approx(rc[1], rel=1e-6) and w.sum() == pytest.approx(1.0)


def test_rth_et_sessions():
    idx = pd.DatetimeIndex(["2024-03-04 14:30", "2024-03-04 14:31", "2024-03-04 21:00", "2024-03-04 21:01"])
    df = pd.DataFrame({"open": 1.0, "high": 1.0, "low": 1.0, "close": 1.0, "volume": 1.0}, index=idx)
    r = U.rth_only(df)
    assert list(r.index) == [pd.Timestamp("2024-03-04 14:31"), pd.Timestamp("2024-03-04 21:00")]
    assert list(U.last_of_session(np.array([1, 1, 2, 2, 2]))) == [False, True, False, False, True]


def test_atr_ninjatrader():
    h, l, c = np.array([10.0, 11, 12]), np.array([9.0, 10, 10]), np.array([9.5, 10.5, 11])
    a = qf.wilder_atr(h, l, c, 14)
    assert a[0] == 1.0 and a[1] == pytest.approx((1.0 + 1.5) / 2) and a[2] == pytest.approx((2 * 1.25 + 2.0) / 3)


def _strat(nom, pnl, intervals):
    from nexus.perso.portefeuille import Strategie
    pos = pd.DataFrame(intervals, columns=["debut", "fin", "instrument"])
    pos["debut"], pos["fin"] = pd.to_datetime(pos["debut"]), pd.to_datetime(pos["fin"])
    return Strategie(nom, pnl, pos, set(pos["instrument"]))


def test_diversification_et_selection():
    from nexus.perso.portefeuille import Diversification
    idx = pd.bdate_range("2020-01-01", periods=600)
    rng = np.random.default_rng(1)
    a = pd.Series(rng.normal(10, 100, 600), idx)
    b = pd.Series(rng.normal(10, 100, 600), idx)
    s = [_strat("A", a, []), _strat("A bis", a * 2, []), _strat("B", b, [])]
    d = Diversification(s)
    c = d.correlation()
    assert c.loc["A", "A bis"] == pytest.approx(1.0) and abs(c.loc["A", "B"]) < 0.15
    sel = d.selection(0.3)
    assert "B" in sel and not ("A" in sel and "A bis" in sel)          # un seul des deux doublons
    assert d.ratio_diversification(["A", "B"]) == pytest.approx(math.sqrt(2), rel=0.1)


def test_chevauchement_et_conflits():
    from nexus.perso.portefeuille import Chevauchement, regle_prop
    idx = pd.bdate_range("2024-01-01", periods=5)
    z = pd.Series(0.0, idx)
    s = [_strat("matin ES", z, [("2024-01-02 14:30", "2024-01-02 16:00", "ES")]),
         _strat("matin ES bis", z, [("2024-01-02 15:00", "2024-01-02 16:00", "ES")]),
         _strat("soir GC", z, [("2024-01-02 23:00", "2024-01-03 01:00", "GC")])]
    ch = Chevauchement(s)
    m = ch.matrice()
    assert m.loc["matin ES", "matin ES bis"] == pytest.approx(1.0) and m.loc["matin ES", "soir GC"] == 0.0
    conf = ch.conflits_contrat()
    assert len(conf) == 1 and conf.iloc[0]["contrat"] == "ES" and conf.iloc[0]["heures_communes"] == pytest.approx(1.0)
    assert ch.groupe_sans_chevauchement(["matin ES", "matin ES bis", "soir GC"], 0.10) == ["matin ES", "soir GC"]
    r = regle_prop(pd.Series([200.0, -1500.0, 100.0], pd.bdate_range("2024-01-01", periods=3)), 50000, 1000, 2000)
    assert r["jours_perte_max"] == 1 and r["premiere_violation"] == pd.Timestamp("2024-01-02")


def test_taille_max_sans_violation():
    from nexus.perso.portefeuille import regle_prop, taille_max
    pnl = pd.Series([200.0, -500.0, 100.0, -300.0, 400.0], pd.bdate_range("2024-01-01", periods=5))
    k = taille_max(pnl, 50000, 1000, 2000)
    assert k == pytest.approx(2.0, rel=1e-3)                            # pire jour -500 $ -> limite 1 000 $ a x2
    assert regle_prop(pnl * k * 0.999, 50000, 1000, 2000)["premiere_violation"] is None
    assert regle_prop(pnl * k * 1.01, 50000, 1000, 2000)["premiere_violation"] is not None


def test_evaluation_prop():
    from nexus.perso.portefeuille import evaluation_prop
    idx = pd.bdate_range("2024-01-01", periods=100)
    r = evaluation_prop(pd.Series(100.0, idx), 50000, 3000, 1000, 2000, horizon=50)
    assert r["reussite"] == 1.0 and r["jours_median"] == 30                  # +100 $ par jour -> 3 000 $ en 30 jours
    r = evaluation_prop(pd.Series(-100.0, idx), 50000, 3000, 1000, 2000, horizon=50)
    assert r["echec"] == 1.0                                                 # -2 000 $ atteint au 21e jour
    r = evaluation_prop(pd.Series(10.0, idx), 50000, 3000, 1000, 2000, horizon=50)
    assert r["non_conclu"] == 1.0


def test_tableau_lecture_et_libelles(tmp_path):
    from nexus.perso.tableau import _f, lire_resultats, noms_courts
    f = tmp_path / "r.txt"
    f.write_text("# entete\n"
                 "S06-B Reversal (corrige) | S06.cs | NQ 1 min -> MNQ | 2016-01 -> 2026-08 | 172 trades | reussite 51% | "
                 "PnL net +3 636 $ | PF 1.28 | Sharpe 0.36 | DD max 1 433 $ | t +1.2 | VERDICT POSITIVE MAIS FAIBLE | note\n"
                 "S07-A Gap | S07.cs | ES | 2016-01 -> 2026-08 | 0 trades | reussite n/d | PnL net +0 $ | PF n/d | "
                 "Sharpe n/d | DD max 0 $ | VERDICT INSUFFISANT (< 30 trades)\n"
                 "NON TESTEES - Autres : exemple\n", encoding="utf-8")
    r = lire_resultats(str(f))
    a = r["S06-B Reversal (corrige)"]
    assert a["trades"] == 172 and a["pnl"] == 3636 and a["sharpe"] == 0.36 and a["dd"] == 1433 and a["t"] == 1.2
    assert a["verdict"] == "POSITIVE MAIS FAIBLE"
    assert r["S07-A Gap"]["sharpe"] is None and r["S07-A Gap"]["verdict"].startswith("INSUFFISANT")
    assert noms_courts(["S06-B X (tel que code)", "S06-B X (corrige)", "Fiche 5 Vol (futures)", "boombitch (M15)"]) == \
        ["S06-B code", "S06-B corr.", "Fiche 5 fut.", "boombitch"]
    assert _f(float("nan")) is None and _f(pd.NaT) is None and _f(1.23456, 2) == 1.23


class _FauxMarche:
    """Marche minimal pour tester l execution des fiches d order flow sur des barres synthetiques."""

    def __init__(self, rows):
        a = np.array(rows, float)
        self.o, self.h, self.l, self.c = a[:, 0], a[:, 1], a[:, 2], a[:, 3]


def test_orderflow_execution_identique_au_moteur():
    from nexus.perso.orderflow import _gerer
    rows = [(100, 100, 100, 100, 1), (100, 100.5, 99.5, 100, 1), (99.75, 100, 99, 99.5, 1), (99.5, 101, 99.5, 100.75, 1),
            (100.75, 101, 100.5, 101, 1)]
    for stop, cible in [(98.5, 100.5), (99.25, 102.0), (98.0, 103.0)]:
        e = qf.Engine(_bars(rows), INST, slippage_ticks=2)

        def f(i, e=e, stop=stop, cible=cible):
            if i == 1:
                e.limit(1, 99.75, 1, stop=stop, target=cible)
            if i == 4 and e.pos:
                e.flatten_now(i, "temps")
        e.run(f)
        k, px, raison = _gerer(_FauxMarche(rows), 2, 1, stop, cible, 4, 2 * INST.tick)
        t = e.trades[0]
        assert (t.entry_price, t.exit_price, t.reason) == (99.75, pytest.approx(px), raison)


def test_orderflow_module_a_et_statistiques():
    from nexus.perso.orderflow import ModuleA, _zone_valeur, ofi_cont, wilson
    T = pd.Timestamp
    tr = pd.DataFrame({"entry_time": [T("2024-01-02 15:00"), T("2024-01-02 15:01"), T("2024-01-02 15:02"), T("2024-01-02 16:00"),
                                      T("2024-01-02 17:00")],
                       "exit_time": [T("2024-01-02 15:30"), T("2024-01-02 15:30"), T("2024-01-02 15:10"), T("2024-01-02 16:30"),
                                     T("2024-01-02 17:30")],
                       "r": [-1.5, -1.6, 1.0, 2.0, 1.0], "jour": [T("2024-01-02")] * 5})
    acc, ev = ModuleA().appliquer(tr)
    assert ev["refus_positions"] == 1                        # 3e trade : deja 2 positions ouvertes
    assert ev["refus_perte_jour"] == 2                       # -3,1R realises a 15:30 -> plus rien ce jour-la
    assert list(acc["r"]) == [-1.5, -1.6]
    poc, lo, hi = _zone_valeur(np.array([1.0, 2.0, 10.0, 3.0, 1.0, 0.5]), 0.70)
    assert poc == 2 and (lo, hi) == (2, 3)                   # 10 + 3 = 13 / 17,5 = 74 % >= 70 %
    assert list(ofi_cont([100, 100, 100.25], [10, 12, 5], [100.25, 100.25, 100.5], [8, 8, 9])) == [0, 2, 13]
    lo, hi = wilson(55, 103)
    assert 0.43 < lo < 0.44 and 0.62 < hi < 0.64             # 53,4 % sur 103 trades : 43,8 % a 63,0 % (fiche)


def test_donchian_alt_identique_a_boombitch_par_defaut():
    rng = np.random.default_rng(3)
    c = 100 + np.cumsum(rng.normal(0, 0.5, 3000))
    rows = [(x, x + abs(rng.normal(0, 0.3)), x - abs(rng.normal(0, 0.3)), x + rng.normal(0, 0.1), 1) for x in c]
    df = _bars(rows, freq="15min")
    res = []
    for cls in (U.Boombitch, U.DonchianAlt):
        e = qf.Engine(df, INST)
        e.run(cls(e, entry_donchian=40, exit_donchian=15, atr_period=20))
        res.append([(t.entry_time, t.exit_time, round(t.pnl, 6)) for t in e.trades])
    assert res[0] and res[0] == res[1]


def test_statistiques_ic_edge_et_monte_carlo():
    from nexus.perso.statistiques import _dd_max, _serie_max, ic_edge, ic_sharpe, monte_carlo
    rng = np.random.default_rng(5)
    p = rng.normal(10.0, 100.0, 2000)
    e = ic_edge(p)
    assert e["ic"][0] < 10 < e["ic"][1] and e["ic_t"][0] < e["esperance"] < e["ic_t"][1]
    assert e["p_pos"] > 0.99 and e["pf"] > 1                           # edge positif net sur 2 000 trades
    assert _dd_max(np.array([[1.0, 3.0, 0.0, 2.0, -1.0]]))[0] == 4.0    # sommet 3 -> creux -1
    assert _serie_max(np.array([[1, 1, 0, 1, 1, 1, 0]]))[0] == 3
    d = pd.Series(rng.normal(50, 1000, 2520), pd.bdate_range("2016-01-04", periods=2520))
    s = ic_sharpe(d)
    assert s["ic"][0] < s["valeur"] < s["ic"][1] and abs(s["ic"][1] - s["ic"][0] - 2 * 1.96 * 0.316) < 0.05   # SE ~ 1/racine(10 ans)
    mc = monte_carlo(d, p, n_an=300, n_hist=200)
    c = mc["cone"]
    assert len(c) == 5 and len(c[0]) == 253 and all(c[0][k] <= c[2][k] <= c[4][k] for k in range(253))
    assert 0 <= mc["rang_dd"] <= 1 and mc["serie"]["mc"][0] <= mc["serie"]["mc"][1]


def test_format_des_durees():
    from nexus.perso.statistiques import fmt_duree
    assert [fmt_duree(x) for x in (0.4, 42, 59.6, 185, 1440 * 4.2, 1440 * 58)] == ["< 1 min", "42 min", "1 h", "3 h 05", "4,2 j", "58 j"]


def test_fx_execution_biais_et_walk_forward():
    from nexus.perso.fx_trois import _gerer_nb, biais_ranaldo, walk_forward
    from nexus.perso.orderflow import _gerer
    rows = [(100, 100, 100, 100, 1), (100, 100.5, 99.5, 100, 1), (99.75, 100, 99, 99.5, 1), (99.5, 101, 99.5, 100.75, 1),
            (100.75, 101, 100.5, 101, 1)]
    fm = _FauxMarche(rows)
    for side, stop, cible in [(1, 98.5, 100.5), (1, 99.25, 102.0), (-1, 101.5, 99.0), (-1, 100.25, np.nan)]:
        k1, px1, r1 = _gerer(fm, 2, side, stop, cible, 4, 0.5)
        k2, px2, code = _gerer_nb(fm.o, fm.h, fm.l, fm.c, 2, side, stop, cible, 4, 0.5)
        assert (k1, px1, r1) == (k2, pytest.approx(px2), ("stop", "objectif", "temps")[code])
    h = np.array([2, 9, 14, 18, 22])
    assert list(biais_ranaldo("6E", h)) == [0, -1, 0, 1, 0]          # EUR baisse en Europe, le dollar baisse a New York
    assert list(biais_ranaldo("6J", h)) == [1, 0, 0, -1, 0]          # USD/JPY monte a Tokyo (23 h - 6 h UTC)
    T = pd.Timestamp
    a = pd.DataFrame({"entry_time": [T("2017-03-01"), T("2018-03-01"), T("2019-03-01")], "r": [2.0, 2.0, -5.0]})
    b = pd.DataFrame({"entry_time": [T("2017-03-01"), T("2018-03-01"), T("2019-03-01")], "r": [-1.0, -1.0, 9.0]})
    oos, choix = walk_forward({"A": a, "B": b}, debut_oos=2019, annees=3)
    assert choix[0][:2] == (2019, "A") and list(oos["r"]) == [-5.0]  # choix sur 2016-2018 seulement, sans regarder 2019


def test_gotobi_calendrier_et_test_temoin():
    from nexus.perso.gotobi import jours_gotobi, test_anomalie
    g = sorted(str(x) for x in jours_gotobi("2019-04-01", "2019-04-30"))
    # 20 avril 2019 = samedi -> vendredi 19 ; 30 avril = jour ferie (Golden Week 2019) -> 26 ; 29 = jour ferie aussi
    assert g == ["2019-04-05", "2019-04-10", "2019-04-15", "2019-04-19", "2019-04-25", "2019-04-26"]
    assert "2024-02-29" in {str(x) for x in jours_gotobi("2024-02-01", "2024-02-29")}       # dernier jour de fevrier
    rng = np.random.default_rng(2)
    idx = pd.bdate_range("2020-01-01", periods=600)
    d = pd.DataFrame({"fenetre": rng.normal(0, 1e-4, 600), "gotobi": np.arange(600) % 3 == 0}, index=idx)
    d.loc[d["gotobi"], "fenetre"] += 1e-4                                                 # +1 pb les jours gotobi
    a = test_anomalie(d)
    assert a["ecart"] == pytest.approx(1.0, abs=0.4) and a["p_perm"] < 0.01


def test_or_heures_asof_sigma_et_verdict():
    from nexus.perso.or_anomalies import asof, bilan_annuel, instants, sigma_robuste
    j = pd.DatetimeIndex(["2024-01-10", "2024-07-10"])
    assert list(pd.to_datetime(instants(j, 8, 20, "America/New_York"))) == [pd.Timestamp("2024-01-10 13:20"), pd.Timestamp("2024-07-10 12:20")]
    assert list(pd.to_datetime(instants(j, 9, 30, "Europe/London"))) == [pd.Timestamp("2024-01-10 09:30"), pd.Timestamp("2024-07-10 08:30")]

    class M:
        t = pd.DatetimeIndex(["2024-01-10 13:00", "2024-01-10 13:15", "2024-01-10 13:40"]).as_unit("ns").asi8
        n = 3
    cibles = pd.DatetimeIndex(["2024-01-10 13:20", "2024-01-10 13:30", "2024-01-10 12:00"]).as_unit("ns").asi8
    assert list(asof(M, cibles, 10)) == [1, -1, -1]          # 13:15 a 5 min ; 13:30 : dernier prix trop ancien ; avant le debut
    x = pd.Series(np.r_[np.ones(30), 100.0 * np.ones(30)])
    s = sigma_robuste(x, 20)
    assert np.isnan(s.iloc[5]) and s.iloc[30] == 0.0          # a l indice 30, seule la periode precedente compte
    idx = pd.bdate_range("2021-01-04", "2026-06-30")
    rng = np.random.default_rng(4)
    bon = bilan_annuel(pd.Series(rng.normal(3e-4, 1e-3, len(idx)), idx))
    assert bon["verdict"] == "RETENUE" and bon["stable"]
    nul = bilan_annuel(pd.Series(rng.normal(0, 1e-3, len(idx)), idx))
    assert nul["verdict"] != "RETENUE"


def test_or_sigma_robuste_ignore_les_trous():
    from nexus.perso.or_anomalies import sigma_robuste
    x = pd.Series(np.random.default_rng(6).normal(0, 1, 200))
    x.iloc[::7] = np.nan
    assert sigma_robuste(x, 60).iloc[100:].notna().all()


def test_soixante_prix_a_et_criteres():
    from nexus.perso.soixante import criteres, prix_a

    class M:                                                     # barres horodatees a leur FIN
        t = pd.DatetimeIndex(["2024-01-10 14:31", "2024-01-10 14:32", "2024-01-10 14:40"]).as_unit("ns").asi8
        n = 3
        o = np.array([100.0, 101.0, 102.0])
        c = np.array([100.5, 101.5, 102.5])
    debut = pd.DatetimeIndex(["2024-01-10 14:30", "2024-01-10 14:34", "2024-01-10 14:50"]).as_unit("ns").asi8
    px, _ = prix_a(M, debut)
    assert px[0] == 100.0                                        # barre qui COMMENCE a 14:30 : son ouverture
    assert px[1] == 101.5                                        # pas de barre a 14:34 : cloture de 14:32 (moins de 5 min)
    assert np.isnan(px[2])                                       # 10 min sans barre : jour exclu
    idx = pd.bdate_range("2016-01-04", "2026-06-30")
    rng = np.random.default_rng(8)
    bon = pd.Series(rng.normal(3.0, 20.0, len(idx)), idx)
    c = criteres(bon, pd.Series(rng.normal(0.0, 20.0, len(idx)), idx), cout=0.5)
    assert c["passe"] and not c["rare"]
    rare = criteres(bon.iloc[:40], None, cout=0.5)
    assert rare["rare"] and not rare["tests"]["t de Welch >= 2 contre le temoin"]


def test_calendriers_fichiers_et_regles():
    from nexus.perso import calendriers as K
    bce = K.banque("BCE")
    assert len(bce) == 86 and pd.Timestamp("2020-03-18") not in bce               # PEPP du 18/03/2020 : urgence exclue
    assert pd.Timestamp("2020-03-18") in K.banque("BCE", urgences=True)
    dec, conf = K.heures_bce(pd.DatetimeIndex(["2022-06-09", "2022-07-21"]))
    assert list(dec) == [13 * 60 + 45, 14 * 60 + 15] and list(conf) == [14 * 60 + 30, 14 * 60 + 45]
    assert pd.Timestamp("2020-03-11") not in K.banque("BOE") and len(K.banque("RBA")) == 110
    assert pd.Timestamp("2020-05-22") not in K.banque("BOJ") and pd.Timestamp("2020-03-16") in K.banque("BOJ")
    ism = K.ism(debut=2017, fin=2017)
    assert ism[0] == pd.Timestamp("2017-01-03")                                 # 2 janvier 2017 : jour ferie observe
    assert K.ism(True, debut=2023, fin=2023)[6] == pd.Timestamp("2023-07-06")   # 3e jour ouvre (4 juillet ferie)
    cb = K.conference_board(debut=2024, fin=2024)
    assert (cb.dayofweek == 1).all() and cb[0] == pd.Timestamp("2024-01-30")
    n = K.nbs()
    assert (n.date.dt.dayofweek < 5).all() and n.loc[n.date == "2016-08-11", "minute"].iloc[0] == 13 * 60 + 30
    mc = K.megacaps()
    assert (mc.minute >= 16 * 60).all() and pd.Timestamp("2023-04-20") not in set(mc.date)
    jour = mc[mc.date == "2021-07-27"].iloc[0]                                    # AAPL 16:35:44, GOOGL 16:36, MSFT 16:41
    assert jour.minute == 16 * 60 + 36 and jour.symboles == "AAPL+GOOGL+MSFT"


def test_calendriers_volume_apres():
    from nexus.perso.calendriers import volume_apres

    class M:                                                     # barres horodatees a leur FIN
        t = pd.DatetimeIndex(["2024-01-10 14:30", "2024-01-10 14:31", "2024-01-10 14:32", "2024-01-10 14:33"]).as_unit("ns").asi8
        v = np.array([1.0, 10.0, 100.0, 1000.0])
    debut = pd.DatetimeIndex(["2024-01-10 14:30"]).as_unit("ns").asi8
    assert volume_apres(M, debut, 2)[0] == 110.0                 # barres qui COMMENCENT a 14:30 et 14:31


def test_soixante_bc_outils():
    from nexus.perso.soixante_bc import _inst, _premier, troisieme_vendredi
    assert troisieme_vendredi(2024, 3) == pd.Timestamp("2024-03-15")
    assert troisieme_vendredi(2019, 4) == pd.Timestamp("2019-04-18")           # vendredi saint : echeance le jeudi
    t = _inst(pd.DatetimeIndex(["2024-01-10", "2024-07-10"]), [-120, 9 * 60], "Europe/London")
    assert list(pd.DatetimeIndex(t)) == [pd.Timestamp("2024-01-09 22:00"), pd.Timestamp("2024-07-10 08:00")]
    j = pd.DatetimeIndex(["2024-01-10", "2024-01-11"])
    p = _premier([pd.Series([np.nan, 2.0], j), pd.Series([1.0, 3.0], j)])
    assert p.to_dict() == {j[0]: 1.0, j[1]: 2.0}                 # premiere barre declenchee de chaque jour


def test_nq1_heure_communique():
    from nexus.perso.nq1_variantes import heure_communique
    jours = pd.bdate_range("2024-01-02", periods=25)
    debuts = [d + pd.Timedelta(hours=16, minutes=k) for d in jours for k in range(46)]           # heure de New York
    t = (pd.DatetimeIndex(debuts).tz_localize("America/New_York").tz_convert("UTC").tz_localize(None)
         + pd.Timedelta(minutes=1)).as_unit("ns").asi8                                         # fin de barre, UTC
    v = np.full(len(debuts), 100.0)
    v[[i for i, x in enumerate(debuts) if x.minute == 0]] = 50_000.0                          # enchere de cloture a 16:00, tous les jours
    res = jours[-1]
    for i, x in enumerate(debuts):
        if x.normalize() == res and x.minute in (30, 31):
            v[i] = 5_000.0                                                                     # communique a 16:30

    class A:
        pass
    a = A()
    a.t, a.v = t, v
    h = heure_communique(a, pd.DatetimeIndex([res]))
    assert h.iloc[0] == 16 * 60 + 30                             # le pic quotidien de 16:00 ne declenche pas


def test_derive_nocturne_outils():
    from nexus.perso.derive_nocturne import ecart_francfort, rsv_bvc
    e = ecart_francfort(pd.DatetimeIndex(["2024-01-10", "2024-03-20", "2024-07-10", "2024-10-30"]))
    assert list(e) == [6, 5, 6, 5]                 # mi-mars et fin octobre : changements d heure decales

    class M:                                       # 25 seances, barres de 15:16 a 16:15 ET (minute de FIN)
        pass
    jours = np.arange(19723, 19748)                # jours ET (numero de jour depuis 1970)
    tod = np.tile(np.arange(15 * 60 + 16, 16 * 60 + 16), len(jours))
    jour = np.repeat(jours, 60)
    rng = np.random.default_rng(1)
    c = 5000 + np.cumsum(rng.normal(0, 1, len(tod)))
    c[-60:] = c[-61] - np.arange(1, 61) * 0.5       # derniere seance : baisse continue
    m = M()
    m.tod, m.jour, m.c, m.v, m.n = tod, jour, c, np.full(len(tod), 100.0), len(tod)
    m.t = (jour * 1440 + tod).astype(np.int64) * 60_000_000_000
    r = rsv_bvc(m)
    assert r.iloc[-1] < -0.3 and r.iloc[:-1].abs().max() < r.abs().iloc[-1]


def test_vol_geree_signal_temps_reel():
    from nexus.perso.vol_geree import expositions, newey_west, vol_mensuelle
    idx = pd.bdate_range("2000-01-03", "2014-12-31")
    rng = np.random.default_rng(5)
    sig = np.where(idx.year == 2014, 0.04, 0.01)                   # 2014 : volatilite quatre fois plus forte
    r = pd.Series(rng.normal(0, 1, len(idx)) * sig, idx)
    d = vol_mensuelle(r)
    assert d.rang.iloc[:119].isna().all() and d.rang.notna().iloc[119:].all()     # 120 mois d historique au minimum
    e = expositions(d)
    assert e.index[0] == d.index[119] + 1                          # la decision de fin de mois vaut pour le mois suivant
    jan14 = e.loc[pd.Period("2014-02", "M")]                       # janvier 2014 agite -> fevrier reduit
    assert jan14.etat == "haut" and jan14.V < 0.5
    calme = e.loc[pd.Period("2013-06", "M")]
    assert calme.V <= 2.0 and calme.R1 <= 2.0                      # levier plafonne a 2
    x = pd.Series(rng.normal(0, 0.01, 3000))
    y = 0.0004 + 0.5 * x + pd.Series(rng.normal(0, 0.002, 3000))
    nw = newey_west(y, x)
    assert abs(nw["beta"] - 0.5) < 0.02 and nw["t"] > 3


def test_cycle_fomc_semaines_et_fed_put():
    from nexus.perso.cycle_fomc import fed_put, semaine_cycle
    reunions = pd.DatetimeIndex(["2024-01-31", "2024-03-20"])
    j = pd.DatetimeIndex(["2024-01-30", "2024-01-31", "2024-02-05", "2024-02-06", "2024-02-13", "2024-03-12", "2024-03-18", "2024-03-19"])
    s = semaine_cycle(j, reunions)
    assert list(s) == [0, 0, 0, 1, 2, -1, -1, 0]        # veille = semaine 0 ; jours -6 a -2 = semaine -1
    idx = pd.bdate_range("2020-01-01", periods=400)
    r = pd.Series(np.random.default_rng(2).normal(0, 0.01, 400), idx)
    r.iloc[390:395] = -0.03                                # forte baisse sur 5 seances
    p = fed_put(r)
    assert not p.iloc[:250].any()                          # pas de seuil avant 250 valeurs passees
    assert p.iloc[395] and not p.iloc[390]                 # signal le lendemain des 5 seances, jamais pendant


def test_pression_cot_signal_et_poids():
    from nexus.perso.pression_cot import CLASSES, poids_classe, signal_sp
    dates = pd.date_range("2018-01-02", periods=60, freq="7D")           # mardis
    c = pd.DataFrame({"marche": "GC", "date": dates, "publication": dates + pd.Timedelta(days=3),
                      "sp_semaine": np.r_[np.zeros(52), np.ones(8)]})
    fins = pd.DatetimeIndex(["2018-12-20", "2019-01-31", "2019-02-28"])          # 20/12 : 51 rapports publies
    sp = signal_sp(c, fins)
    assert np.isnan(sp.GC.iloc[0])                                      # moins de 52 rapports publies
    pub = c.publication[c.publication <= fins[2]]
    assert sp.GC.iloc[2] == pytest.approx(c.sp_semaine[c.publication.isin(pub)].tail(52).mean())
    sig = pd.DataFrame([[1.0, 2.0, 3.0, 0.1, 0.2, 0.3, 0.4, 5.0, -5.0]], columns=["ES", "NQ", "YM", "6E", "6B", "6J", "6A", "GC", "CL"],
                       index=[pd.Timestamp("2020-01-31")])
    w = poids_classe(sig)
    for cl, mks in CLASSES.items():
        assert w[list(mks)].abs().sum(axis=1).iloc[0] == pytest.approx(1 / len(CLASSES))   # chaque classe pese 1/3
        assert abs(w[list(mks)].sum(axis=1).iloc[0]) < 1e-12                               # neutre dans sa classe
    assert w.GC.iloc[0] > 0 > w.CL.iloc[0]


def test_tendance_signal_et_tiers():
    from nexus.perso.tendance import signal_kebr, tiers
    idx = pd.bdate_range("2018-01-01", periods=600)
    logp = pd.Series(np.r_[np.linspace(0, 0.3, 300), np.linspace(0.3, 0.0, 300)], idx)
    s = signal_kebr(logp, 10)
    assert s.abs().max() <= 2.0                                     # borne a +-2
    assert s.iloc[250] > 0 and s.iloc[580] < 0                      # suit la tendance
    choc = logp.copy()
    choc.iloc[400] += 1.0
    assert signal_kebr(choc, 10).iloc[400] == s.iloc[400]           # le prix du jour n entre pas dans le signal du jour
    rt = pd.DataFrame({"A": [1.0, 1.0], "B": [2.0, 2.0], "C": [3.0, 3.0], "D": [4.0, 4.0]},
                      index=pd.period_range("2020-01", periods=2, freq="M"))
    g = tiers(rt)
    assert g.index[0] == pd.Period("2020-02", "M")                  # classement du mois precedent
    assert list(g.iloc[0]) == [False, False, True, True]            # moitie haute = gros tick


def test_carry_fx_poids_et_regression():
    from nexus.perso.carry_fx import ols_white, poids_eq, poids_eq0, poids_v, quotidiens
    mois = pd.period_range("2020-01", periods=2, freq="M")
    t = pd.DataFrame({"US": [2.0, 0.5], "EZ": [0.0, 0.0], "GB": [1.0, 1.0], "JP": [-0.1, -0.1], "AU": [3.0, 3.0]}, index=mois)
    v = poids_v(t)
    assert list(v.iloc[0]) == [-0.25] * 4 and list(v.iloc[1]) == [0.25] * 4   # moyenne etrangere 0,975 : sous puis au-dessus du dollar
    assert list(poids_eq(t).iloc[1]) == [-0.25, 0.25, -0.25, 0.25]           # signe(i_j - i_US) / 4
    assert list(poids_eq0(t).iloc[0]) == [-0.25, 0.25, -0.25, 0.25]          # au-dessus / en dessous de la mediane
    jours = pd.bdate_range("2020-02-03", "2020-03-31")
    w = quotidiens(v, jours)
    assert w.loc["2020-02-14", "6E"] == -0.25 and w.loc["2020-03-16", "6E"] == 0.25   # decision du mois m -> mois m+1
    rng = np.random.default_rng(0)
    x = rng.normal(size=400)
    b, tt, n = ols_white(2.0 * x + rng.normal(size=400) * 0.1, x)
    assert n == 400 and abs(b - 2.0) < 0.05 and tt > 50


def test_saisonnalite_signal_et_rangs():
    from nexus.perso.saisonnalite import signaux, z_rang
    idx = pd.period_range("2000-01", "2010-12", freq="M")
    base = np.where(idx.month == 3, 0.05, 0.0)                             # A gagne 5 % chaque mars, B rien
    rm = pd.DataFrame({mk: 0.0 for mk in ("ES", "NQ", "YM", "GC", "CL")}, index=idx)
    rm["ES"] = base
    meme, autre = signaux(rm)
    assert np.isnan(meme.loc[pd.Period("2004-03", "M"), "ES"])            # moins de 5 ans de mars
    assert meme.loc[pd.Period("2005-03", "M"), "ES"] == 0.05               # 5 mars passes (2000-2004)
    assert meme.loc[pd.Period("2005-04", "M"), "ES"] == 0.0                # avril : rien
    assert autre.loc[pd.Period("2005-03", "M"), "ES"] == 0.0               # autres mois que mars
    assert meme.index[-1] == pd.Period("2011-01", "M")                     # signal du mois suivant la derniere donnee
    z = z_rang(meme, ["actions", "matieres"]).loc[pd.Period("2006-03", "M")]
    assert z["ES"] == 1.0 and z["NQ"] == z["YM"] == -0.5                   # ex aequo : rang moyen
    assert z["GC"] == z["CL"] == 0.0


def test_momentum_transversal_signal():
    from nexus.perso.momentum_transversal import mom_2_12
    idx = pd.period_range("2016-01", periods=14, freq="M")
    rm = pd.DataFrame({"ES": np.arange(14, dtype=float)}, index=idx)
    s = mom_2_12(rm)
    assert s["ES"].iloc[:12].isna().all()                                  # 11 mois exiges, finissant en m-2
    assert s["ES"].iloc[12] == sum(range(0, 11))                          # mois 12 : mois 0 a 10 (m-12 .. m-2)
    assert s["ES"].iloc[13] == sum(range(1, 12))                          # le dernier mois (m-1) est saute


def test_rachat_baisse_signal_mac5():
    from nexus.perso.rachat_baisse import mac5, poids
    idx = pd.bdate_range("2020-01-01", periods=80)
    r = pd.Series(0.0, idx)
    r.iloc[70] = -0.02                                                     # forte baisse le jour 70
    m = mac5(r)
    assert m.iloc[70] == 0.0                                               # le rendement du jour n entre pas dans son signal
    assert m.iloc[71] == -0.08 and m.iloc[74] == -0.02 and m.iloc[75] == 0.0   # poids 4, 3, 2, 1 puis rien
    rr = r.copy()
    rr.iloc[:60] = np.tile([0.01, -0.01], 30)                              # volatilite de chauffe
    w = poids({"ES": pd.DataFrame({"r": rr, "prix": 100.0})}, ["ES"])["ES"]
    assert w.iloc[71] > 0 and w.iloc[70] == 0.0                            # achat apres la baisse


def test_gamma_intraday_positions_et_gex_veille():
    from nexus.perso.gamma_intraday import gex_veille, ols_nw, positions
    g = pd.Series([-1.0, 2.0, 3.0], index=pd.to_datetime(["2024-01-02", "2024-01-03", "2024-01-04"]))
    jours = pd.DatetimeIndex(["2024-01-02", "2024-01-03", "2024-01-05"])
    v = gex_veille(g, jours)
    assert np.isnan(v.iloc[0]) and v.iloc[1] == -1.0 and v.iloc[2] == 3.0   # valeur datee strictement avant le jour
    rod = pd.Series([0.01, 0.01, -0.02], index=jours)
    p = positions(rod, pd.Series([-1.0, 2.0, np.nan], index=jours))
    assert list(p["V"]) == [1.0, -1.0, 0.0]                                 # momentum si gamma < 0, retournement si > 0
    assert list(p["R0"]) == [1.0, 0.0, 0.0] and list(p["H1"]) == [1.0, 1.0, -1.0]
    rng = np.random.default_rng(1)
    x = rng.normal(size=500)
    b, t = ols_nw(3.0 * x + rng.normal(size=500) * 0.1, np.c_[np.ones(500), x])
    assert abs(b[1] - 3.0) < 0.02 and t[1] > 50


def test_bdlm_conditionnel_outils():
    from nexus.perso.bdlm_conditionnel import clark_west, holm, r2_oos
    p = holm({"a": 0.01, "b": 0.04, "c": 0.30})
    assert abs(p["a"] - 0.03) < 1e-12 and abs(p["b"] - 0.08) < 1e-12 and p["c"] == 0.30   # Holm : 3p, 2p, p (monotone)
    rng = np.random.default_rng(2)
    x = rng.normal(size=800)
    y = 0.5 * x + rng.normal(size=800)
    fm, fh = r2_oos(y, np.c_[np.ones(800), x], debut=500)
    assert np.isnan(fm[:500]).all() and np.isfinite(fm[500:]).all()        # fenetre expansive : rien avant 500 jours
    assert abs(fh[600] - y[:600].mean()) < 1e-12                             # moyenne historique sans la valeur du jour
    r2, cw = clark_west(y, fm, fh)
    assert r2 > 0.1 and cw > 3


def test_fin_de_mois_calendrier_et_reglement():
    from nexus.perso.fin_de_mois import calendrier, fenetres
    jours = pd.bdate_range("2017-07-03", "2017-10-31")
    cal = calendrier(jours)
    t_aout, t_sept = pd.Timestamp("2017-08-31"), pd.Timestamp("2017-09-29")
    assert cal.loc[t_aout, "k_av"] == 0 and cal.loc[t_sept, "fin"]
    assert cal.loc[t_aout, "s"] == 3 and cal.loc[t_sept, "s"] == 2          # T+2 des le 05/09/2017 (D = T-3 = 26/09)
    lab = fenetres(cal)
    # aout (T+3) : vente T-8..T-4, retour T-3..T-1 ; septembre (T+2) : vente T-7..T-3, retour T-2..T-1
    assert lab.loc["2017-08-21":"2017-08-25"].eq("vente").all() and lab.loc["2017-08-28":"2017-08-30"].eq("retour").all()
    assert lab.loc["2017-09-20":"2017-09-26"].eq("vente").all() and lab.loc["2017-09-27":"2017-09-28"].eq("retour").all()
    assert lab.loc[t_aout] == "achat" and lab.loc["2017-09-01":"2017-09-05"].eq("achat").all()   # T..T+3 (jours ouvres)
    assert lab.loc["2017-09-06":"2017-09-12"].eq("retour_neg").all() and lab.loc["2017-09-19"] == "autre"
    fixe = fenetres(cal, fixe=True)
    assert fixe.loc["2017-09-19":"2017-09-25"].eq("vente").all()            # horaire fixe : T-8..T-4
    j24 = pd.bdate_range("2024-04-01", "2024-06-28")
    assert calendrier(j24).loc["2024-05-31", "s"] == 1                        # T+1 : D = T-2 = 29/05 >= 28/05/2024


def test_fin_de_mois_signaux_hmm():
    from nexus.perso.fin_de_mois import calendar_modifie, calendrier, signaux
    jours = pd.bdate_range("2021-01-01", "2021-03-31")
    cal = calendrier(jours)
    re = pd.Series(0.0, jours)
    rb = pd.Series(0.0, jours)
    re.loc["2021-01-05"] = 0.10                                               # actions +10 %, obligations stables
    sig = signaux(re, rb, cal["fin"])
    assert abs(sig.loc["2021-01-05", "calendar"] - (0.66 / 1.06 - 0.6)) < 1e-12   # 62,26 % - 60 % (exemple du papier)
    assert sig.loc["2021-01-29", "calendar"] > 0.02 and sig.loc["2021-02-01", "calendar"] == 0.0   # remis a 60 % fin janvier
    assert abs(sig.loc["2021-01-05", "threshold"] - (0.66 / 1.06 - 0.6)) < 1e-12  # tous les seuils <= 2,26 % : meme ecart
    assert sig.loc["2021-01-06", "threshold"] > 0 and sig.loc["2021-01-06", "threshold"] < 0.0226   # delta = 0 remis a zero
    w = calendar_modifie(sig, cal)
    assert w.loc["2021-01-25":"2021-01-29"].eq(-1.0).all() and w.loc["2021-01-22"] == 0.0   # 5 derniers jours : vendre
    assert w.loc["2021-02-01"] == 1.0 and w.loc["2021-02-02"] == 0.0         # 1er jour : signe du Calendar en T-4
    wt = calendar_modifie(sig, cal, decalage=-10)
    assert wt.loc["2021-01-11":"2021-01-15"].eq(-1.0).all() and wt.loc["2021-01-18"] == 1.0   # temoin : 10 seances plus tot


def test_fin_de_mois_strategie_couts():
    from nexus.perso.fin_de_mois import strategie
    idx = pd.bdate_range("2022-01-03", periods=6)
    w = pd.Series([0, 1, 1, 0, 0, 0], idx, dtype=float)
    r = pd.Series([0, 0, 0.01, 0.02, 0.03, 0], idx, dtype=float)
    net, brut, cout = strategie(w, r, pd.Series(0.001, idx))
    assert list(brut.fillna(0).round(6)) == [0, 0, 0.01, 0.02, 0, 0]       # position du 2e jour : rendements des 3e et 4e
    assert list(cout.round(6)) == [0, 0, 0.001, 0, 0.001, 0]                # entree et sortie imputees le lendemain de l ordre


def test_weekend_crypto_semaines_et_heures():
    from types import SimpleNamespace
    from nexus.perso.weekend_crypto import cout_ar, fenetres_futures, prix_crypto, semaines
    from nexus.perso.soixante import jours_ouvres_us
    jours = pd.DatetimeIndex([d for d in pd.bdate_range("2024-01-01", "2024-04-05")])
    m0 = SimpleNamespace(t=pd.DatetimeIndex(jours).as_unit("ns").asi8)
    ouvres = jours_ouvres_us(m0)
    sem = semaines(ouvres)
    assert pd.Timestamp("2024-01-15") not in sem.index                       # lundi ferie (Martin Luther King)
    assert pd.Timestamp("2024-04-01") not in sem.index                       # vendredi saint le 29/03 : week-end exclu
    assert pd.Timestamp("2024-01-22") in sem.index and sem.loc["2024-01-22", "dimanche"] == pd.Timestamp("2024-01-21")
    # crypto : derniere barre FINIE au plus tard a l instant ; 16:00 ET = 21:00 UTC en hiver, 20:00 UTC en ete
    idx = pd.DatetimeIndex(["2024-01-19 20:45", "2024-01-19 21:00", "2024-01-19 21:15"])
    s = pd.Series([1.0, 2.0, 3.0], index=idx)
    t = pd.DatetimeIndex(["2024-01-19 21:00", "2024-01-19 21:10", "2024-01-20 12:00"]).as_unit("ns").asi8
    p = prix_crypto(s, t)
    assert p[0] == 2.0 and p[1] == 2.0 and np.isnan(p[2])                    # plus d une heure : manquant
    assert abs(cout_ar("ES", pd.Series([5000.0]))[0] - 2 * (0.25 + 2.5 / 50) / 5000) < 1e-15
    # futures : prix a dimanche 18:00 ET = ouverture de la barre 18:00-18:01 (datee 18:01, 23:01 UTC en hiver)
    fins = pd.DatetimeIndex(["2024-01-19 21:01", "2024-01-21 23:01", "2024-01-22 14:31", "2024-01-22 21:01"])
    m = SimpleNamespace(t=fins.as_unit("ns").asi8, o=np.array([100.0, 98.0, 99.0, 97.0]), c=np.array([100.0, 98.0, 99.0, 97.0]),
                        n=4, offset=np.zeros(4))
    f = fenetres_futures(m, sem.loc[["2024-01-22"]])
    assert abs(f["saut"].iloc[0] - (-0.02)) < 1e-12 and abs(f["V"].iloc[0] - (97 - 98) / 98) < 1e-12
    assert abs(f["seance"].iloc[0] - (97 - 99) / 99) < 1e-12 and abs(f["total"].iloc[0] - (-0.03)) < 1e-12


def test_dax_cloture_jours_fenetres_et_miroir():
    from nexus.perso.dax_cloture import FDAX, Marche, fenetres, jours_xetra, miroir, trades_s19
    j = jours_xetra("2024-12-20", "2025-01-03")
    for d in ("2024-12-24", "2024-12-25", "2024-12-31", "2025-01-01"):
        assert pd.Timestamp(d) not in j                                       # Xetra ferme
    assert pd.Timestamp("2024-12-23") in j and pd.Timestamp("2025-01-02") in j
    # deux jours d hiver (Berlin = UTC+1), barres 08:00-18:00 Berlin datees a leur fin, +0,1 point par minute
    fins = pd.DatetimeIndex(list(pd.date_range("2024-01-15 07:01", "2024-01-15 17:00", freq="1min"))
                            + list(pd.date_range("2024-01-16 07:01", "2024-01-16 17:00", freq="1min")))
    c = 100.0 + 0.1 * np.arange(1, len(fins) + 1)
    df = pd.DataFrame({"open": c - 0.1, "high": c + 0.05, "low": c - 0.15, "close": c, "volume": 1.0}, index=fins)
    jours = pd.DatetimeIndex(["2024-01-15", "2024-01-16"])
    f = fenetres(Marche(df), jours)
    o = df["open"]
    assert abs(f.loc["2024-01-16", "lh"] - math.log(o["2024-01-16 16:31"] / o["2024-01-16 16:01"])) < 1e-12
    assert abs(f.loc["2024-01-16", "jour"] - math.log(o["2024-01-16 16:01"] / o["2024-01-16 08:01"])) < 1e-12
    assert abs(f.loc["2024-01-16", "fh"] - math.log(o["2024-01-16 08:31"] / o["2024-01-15 16:31"])) < 1e-12
    assert np.isnan(f.loc["2024-01-15", "fh"]) and np.isnan(f.loc["2024-01-16", "nuit_suiv"])
    assert abs(f.loc["2024-01-15", "nuit_suiv"] - math.log(o["2024-01-16 08:01"] / o["2024-01-15 16:31"])) < 1e-12
    # S19-B : achat a 17:00 (jour en hausse), taille plafonnee a 4, sortie a la barre de 17:29 ; le miroir vend
    t = trades_s19(df)
    assert len(t) == 2 and (t["direction"] == 1).all() and (t["qty"] == 4).all() and (t["reason"] == "fin-fenetre").all()
    assert t["entry_time"].iloc[1] == pd.Timestamp("2024-01-16 16:00") and t["exit_time"].iloc[1] == pd.Timestamp("2024-01-16 16:30")
    m = miroir(t)
    assert list(m.index) == list(jours) and (m["sens"] == -1).all()
    frais = 4 * (2 * FDAX.commission + 2 * FDAX.tick * FDAX.point_value)
    brut_origine = (o["2024-01-16 16:30"] - o["2024-01-16 16:00"]) * 4 * FDAX.point_value     # prix sans glissement
    assert abs(m["frais"].iloc[1] - frais) < 1e-9
    assert abs(m["brut"].iloc[1] + brut_origine) < 1e-6 and abs(m["net"].iloc[1] + brut_origine + frais) < 1e-6
    assert abs(m["r_net"].iloc[1] - m["net"].iloc[1] / (t["entry_price"].iloc[1] * FDAX.point_value)) < 1e-15


def test_creneaux_rendement_et_sessions():
    from types import SimpleNamespace
    from nexus.perso.creneaux import rendement, sessions_or
    # minutes UTC du 05/01/2016 au 07/01/2016, prix +0,1 par minute, echeance unique (decalage nul)
    fins = pd.date_range("2016-01-05 00:01", "2016-01-07 23:59", freq="1min")
    c = 1000.0 + 0.1 * np.arange(len(fins))
    m = SimpleNamespace(t=fins.as_unit("ns").asi8, o=c - 0.1, c=c, n=len(c), offset=np.zeros(len(c)))
    ta = pd.DatetimeIndex(["2016-01-06 00:00"]).as_unit("ns").asi8
    tb = pd.DatetimeIndex(["2016-01-06 08:00"]).as_unit("ns").asi8
    r = rendement(m, ta, tb)
    o = pd.Series(m.o, index=fins)
    assert abs(r[0] - (o["2016-01-06 08:01"] - o["2016-01-06 00:01"]) / o["2016-01-06 00:01"]) < 1e-12
    m.rc = np.where(fins < pd.Timestamp("2016-01-06 04:00"), c - 5.0, c - 7.0)     # roulement a 04:00 : fenetre exclue
    m._contrat = None
    assert np.isnan(rendement(m, ta, tb)[0])
    del m.rc
    m._contrat = None
    s = sessions_or(m)
    d = pd.Timestamp("2016-01-06")
    assert abs(s.loc[d, "us_prec"] - (o["2016-01-06 00:01"] - o["2016-01-05 14:31"]) / o["2016-01-05 14:31"]) < 1e-12
    assert abs(s.loc[d, "europe"] - (o["2016-01-06 14:31"] - o["2016-01-06 08:01"]) / o["2016-01-06 08:01"]) < 1e-12
    assert np.isnan(s.loc[pd.Timestamp("2016-01-05"), "us_prec"])


def test_creneaux_saut_de_reouverture():
    from types import SimpleNamespace
    from nexus.perso.creneaux import reouvertures
    # vendredi 08/01/2016 16:00-16:59 New York (UTC-5) a 1,0800, dimanche 10/01 18:00-21:30 : ouverture 1,0810 (+10 pips) puis
    # retour lineaire a 1,0800 a 19:00
    t1 = pd.date_range("2016-01-08 21:01", "2016-01-08 22:00", freq="1min")             # fins de barre UTC (16:00-17:00 NY)
    t2 = pd.date_range("2016-01-10 23:01", "2016-01-11 02:30", freq="1min")             # 18:00-21:30 NY
    idx = t1.append(t2)
    o = np.r_[np.full(len(t1), 1.0800), 1.0810 - 0.0010 * np.clip(np.arange(len(t2)) / 60, 0, 1)]
    m = SimpleNamespace(t=idx.as_unit("ns").asi8, o=o, c=o.copy(), n=len(o), offset=np.zeros(len(o)))
    d = reouvertures(m, "6E")
    r = d.loc[pd.Timestamp("2016-01-10")]
    assert abs(r.pips - 10) < 1e-6 and r.sens == -1
    assert abs(r.r19 - (1.0800 - 1.0810) / 1.0810) < 1e-9                               # vente gagnante : sens x r19 > 0
    assert np.isnan(r.rfin)                                                              # pas de barre lundi 17:00


def test_creneaux_orb_dax_regles():
    from nexus.perso.creneaux import orb_dax
    # un jour : bougie 9:00-9:05 haussiere (100 -> 101, plus bas 99,5), puis hausse reguliere jusqu a 17:30
    mn = np.arange(9 * 60, 17 * 60 + 31)
    o = 100.0 + np.r_[np.linspace(0, 1, 5), 1 + 0.01 * np.arange(len(mn) - 5)]
    d = pd.DataFrame(dict(open=o, high=o + 0.2, low=o - 0.2, close=o + 0.05, jour=pd.Timestamp("2024-01-03"), mn=mn))
    d.loc[d.mn == 9 * 60 + 2, "low"] = 99.5
    t = orb_dax(d, pd.DatetimeIndex(["2024-01-03"]), 9 * 60, "za23").iloc[0]
    assert t.sens == 1 and t.entree == o[5] and not t.stop_touche
    assert t.sortie == o[mn == 17 * 60 + 30][0]
    assert abs(t.f - min(0.01 / ((o[5] - 99.5) / o[5]), 4)) < 1e-12
    # le meme jour avec une chute a 13:00 sous le plus bas de la bougie : sortie au stop
    d2 = d.copy()
    d2.loc[d2.mn == 13 * 60, ["open", "low"]] = [99.0, 98.9]
    t2 = orb_dax(d2, pd.DatetimeIndex(["2024-01-03"]), 9 * 60, "za23").iloc[0]
    assert t2.stop_touche and t2.sortie == 99.0                                        # ouverture deja sous le stop


def test_creneaux_zone_de_bruit_dax():
    from nexus.perso.creneaux import NB_MIN, zone_bruit
    rng = np.random.default_rng(1)
    n = 60
    jours = pd.bdate_range("2024-01-02", periods=n)
    base = 100 + np.cumsum(rng.normal(0, 0.5, n))
    pas = rng.normal(0, 0.0004, (n, NB_MIN)).cumsum(axis=1)
    C = base[:, None] * (1 + pas)
    O = np.c_[base, C[:, :-1]]
    H, L = np.maximum(O, C) * 1.0001, np.minimum(O, C) * 0.9999
    # dernier jour : forte hausse reguliere des 9:00 -> au-dessus de la zone a chaque controle : acheteur toute la journee
    C[-1] = base[-1] * (1 + 0.0001 * np.arange(1, NB_MIN + 1))
    O[-1] = np.r_[base[-1], C[-1, :-1]]
    H[-1], L[-1] = C[-1] * 1.00001, O[-1] * 0.99999
    net, br, actif, _, _ = zone_bruit(O, H, L, C, jours, lookback=30, bande=1.2, lev_fixe=1.0)
    j = jours[-1]
    assert actif[j]
    attendu = (O[-1, 510] - O[-1, 30]) / O[-1, 0]              # achete a 9:30, vendu a 17:30 ; taille fixee a l ouverture
    assert abs(br[j] - attendu) < 1e-9
    assert net[j] < br[j]                                      # un aller-retour paye
    assert np.isnan(net[jours[10]])                             # pas assez d historique (30 seances)


def test_creneaux_clotures_traversees():
    from nexus.perso.creneaux import clotures_traversees
    # mercredi 14:00 New York (19:00 UTC, hiver) -> lundi 10:00 : clotures mercredi, jeudi, vendredi (rachat dimanche 18:00)
    c = clotures_traversees(pd.Timestamp("2024-01-10 19:00"), pd.Timestamp("2024-01-15 15:00"))
    assert [d.strftime("%a") for d, _, _ in c] == ["Wed", "Thu", "Fri"]
    assert c[0][1] == pd.Timestamp("2024-01-10 22:00") and c[0][2] == pd.Timestamp("2024-01-10 23:00")
    assert c[2][2] == pd.Timestamp("2024-01-14 23:00")                               # dimanche 18:00 New York
    assert clotures_traversees(pd.Timestamp("2024-01-10 15:00"), pd.Timestamp("2024-01-10 21:00")) == []


def test_creneaux_bande_de_volatilite():
    from types import SimpleNamespace
    from nexus.perso.creneaux import bande_vol
    # deux seances (New York = UTC-5) : veille cloture a 100 ; jour J ouvre a 100, monte a 102 a 10:00 (au-dessus de
    # 100 x (1 + 16 % / 16) = 101), puis revient a 100,5 a la cloture -> vente a 10:01, gain (101,99 -> 100,5)
    def seance(d, prix):
        t = pd.date_range(f"{d} 14:31", f"{d} 21:00", freq="1min")     # 9:30-16:00 New York, fin de barre UTC
        return t, prix(np.arange(len(t)))
    t1, p1 = seance("2024-01-09", lambda k: np.full(len(k), 100.0))
    t2, p2 = seance("2024-01-10", lambda k: np.where(k < 30, 100.0 + 2.0 * k / 30, 102.0 - 1.5 * (k - 30) / (len(k) - 31)))
    t = t1.append(t2)
    c = np.r_[p1, p2]
    o = np.r_[c[:1], c[:-1]]
    m = SimpleNamespace(t=t.as_unit("ns").asi8, o=o, c=c, n=len(c), offset=np.zeros(len(c)))
    vol = pd.Series([16.0, 16.0], index=pd.DatetimeIndex(["2024-01-08", "2024-01-09"]))
    b = bande_vol(m, vol)
    r = b.loc[pd.Timestamp("2024-01-10")]
    assert r.sens == -1 and r.r > 0 and abs(r.r - (o[len(p1) + np.argmax(p2 > 101.0) + 1] - c[-1]) / o[len(p1) + np.argmax(p2 > 101.0) + 1]) < 1e-12


def test_creneaux_jambes_tokyo():
    from types import SimpleNamespace
    from nexus.perso.creneaux import jambes_tokyo
    # minutes UTC du 08/01/2024 ; Tokyo = UTC+9 : 08:00 Tokyo = 23:00 UTC la veille, 09:55 = 00:55, 11:00 = 02:00
    fins = pd.date_range("2024-01-07 22:01", "2024-01-08 03:00", freq="1min")
    c = 100.0 + 0.01 * np.arange(len(fins))
    m = SimpleNamespace(t=fins.as_unit("ns").asi8, o=c - 0.01, c=c, n=len(c), offset=np.zeros(len(c)))
    j = jambes_tokyo(m, pd.DatetimeIndex(["2024-01-08"]))
    o = pd.Series(m.o, index=fins)
    a, b, f = o["2024-01-07 23:01"], o["2024-01-08 00:56"], o["2024-01-08 02:01"]
    r = j.iloc[0]
    assert abs(r.avant - (b - a) / a) < 1e-12 and abs(r.apres - (f - b) / b) < 1e-12
    assert r.p8 == a and r.p955 == b


def test_donchian_alt_heure_limite_16h10():
    # barres 15 min d une seance CME (18:00 -> 17:00 New York, pause et week-end retires), marche en hausse : la position
    # est vendue avant 16:10, jamais tenue entre 16:10 et 18:00, et rachetee a la reouverture (meme stop)
    idx = pd.date_range("2024-03-04 00:00", "2024-04-26 00:00", freq="15min")          # fin de barre, UTC
    et = idx.tz_localize("UTC").tz_convert("America/New_York").tz_localize(None)
    mn = et.hour * 60 + et.minute
    dow = (et - pd.Timedelta(hours=18)).dayofweek                                       # jour de la seance en cours
    garde = ~((mn > 17 * 60) & (mn <= 18 * 60)) & (dow < 5)
    idx = idx[garde]
    rng = np.random.default_rng(11)
    c = 100 + np.cumsum(rng.normal(0.02, 0.3, len(idx)))
    rows = [(x, x + abs(rng.normal(0, 0.2)), x - abs(rng.normal(0, 0.2)), x + rng.normal(0, 0.05), 1) for x in c]
    df = pd.DataFrame(rows, columns=["open", "high", "low", "close", "volume"], index=idx)
    e = qf.Engine(df, INST)
    e.run(U.DonchianAlt(e, entry_donchian=40, exit_donchian=15, atr_period=20, fin_de_seance=True, heure_limite=970))
    assert len(e.trades) > 5
    tz = lambda t: pd.Timestamp(t).tz_localize("UTC").tz_convert("America/New_York").tz_localize(None)
    for t in e.trades:
        a, b = tz(t.entry_time), tz(t.exit_time)
        d = a.normalize()
        while d <= b.normalize():
            assert not (a < d + pd.Timedelta(hours=18) and b > d + pd.Timedelta(minutes=971)), (a, b)
            d += pd.Timedelta(days=1)
    assert any(t.reason == "heure limite" for t in e.trades) and any(t.tag == "Rachat" for t in e.trades)


def test_binance_lecture_millisecondes_et_microsecondes(tmp_path):
    import zipfile
    from nexus.binance import lire_zip
    for unite, f in (("ms", 1), ("us", 1000)):
        t0 = int(pd.Timestamp("2025-01-01 00:00").value // 10 ** 6) * f
        lignes = [f"{t0 + k * 60_000 * f},{100 + k},{101 + k},{99 + k},{100.5 + k},2.0,0,0,0,0,0,0" for k in range(3)]
        z = tmp_path / f"x_{unite}.zip"
        with zipfile.ZipFile(z, "w") as fh:
            fh.writestr("x.csv", "\n".join(lignes))
        d = lire_zip(str(z))
        assert list(d.index) == list(pd.date_range("2025-01-01 00:01", periods=3, freq="1min"))   # fin de barre, UTC
        assert d.close.iloc[1] == 101.5 and d.volume.iloc[0] == 2.0


def test_creneaux_seance_cme_et_seances_crypto():
    from nexus.perso.creneaux import rendements_seances, seance_cme
    # fins de barre UTC (New York = UTC-4 en juin 2024) : vendredi 16:59, vendredi 17:30, samedi midi, dimanche 18:15,
    # lundi 17:30, lundi 18:01
    t = pd.DatetimeIndex(["2024-06-07 20:59", "2024-06-07 21:30", "2024-06-08 16:00", "2024-06-09 22:15",
                          "2024-06-10 21:30", "2024-06-10 22:01"])
    assert list(seance_cme(t)) == [True, False, False, True, False, True]
    # seances : celle du lundi va du dimanche 18:00 au lundi 17:00 ; le week-end n est pas une seance
    j = pd.date_range("2024-06-07", "2024-06-11", freq="D")
    ps = pd.DataFrame(dict(c17=[10.0, 11.0, 12.0, 13.0, 14.0], o18=[1.0, 2.0, 4.0, 5.0, 6.0]), index=j)
    r = rendements_seances(ps)
    assert list(r.index) == [pd.Timestamp("2024-06-10"), pd.Timestamp("2024-06-11")]
    assert r.iloc[0] == 13.0 / 4.0 - 1 and r.iloc[1] == 14.0 / 5.0 - 1


def test_creneaux_expositions_zpb():
    from nexus.perso.creneaux import expositions_zpb
    rng = np.random.default_rng(2)
    j = pd.date_range("2018-01-01", periods=900, freq="D")
    hausse = pd.Series(100 * np.exp(np.cumsum(0.004 + rng.normal(0, 0.02, 900))), index=j)
    baisse = pd.Series(100 * np.exp(np.cumsum(-0.004 + rng.normal(0, 0.02, 900))), index=j)
    eh, eb = expositions_zpb(hausse), expositions_zpb(baisse)
    assert (eh.iloc[:90] == 0).all()                                   # pas de volatilite sur 90 jours : rien
    assert eh.iloc[400:].mean() > 0.5 and eb.iloc[400:].mean() < 0.1 and eh.max() <= 2.0
    # 25 % de volatilite cible : une fenetre seule en position vaut (0,25 / vol) / 9
    vol = hausse.pct_change().rolling(90).std() * np.sqrt(365)
    assert eh.iloc[-1] <= (0.25 / vol.iloc[-1]) + 1e-12


def test_moteur_frais_en_fraction_du_notionnel():
    # micro bitcoin : 0,1 BTC par contrat, frais 3 pb du notionnel par cote, pas de glissement en plus
    inst = qf.INSTRUMENTS["MBT"]
    rows = [(50000.0, 50010.0, 49990.0, 50000.0, 1)] * 3 + [(51000.0, 51010.0, 50990.0, 51000.0, 1)] * 3
    df = _bars(rows)
    e = qf.Engine(df, inst, slippage_ticks=0)
    e.run(Script(e, {1: lambda e: e.market(2), 4: lambda e: e.market(0)}))
    t = e.trades[0]
    brut = (t.exit_price - t.entry_price) * 2 * 0.1
    frais = 3e-4 * 0.1 * 2 * (t.entry_price + t.exit_price)
    assert abs(t.pnl - (brut - frais)) < 1e-9 and frais > 0


def test_creneaux_fenetres_utc():
    from nexus.perso.creneaux import fenetres_utc
    # minutes du mercredi 05/06/2024 (UTC, fin de barre), prix +1 par minute ; New York = UTC-4 : 21:00-22:00 UTC est la
    # pause du CME (17:00-18:00) : la fenetre 21:00-23:00 ne garde que 22:00-23:00
    idx = pd.date_range("2024-06-05 20:01", "2024-06-05 23:30", freq="1min")
    p = np.arange(len(idx), dtype=float) + 100
    df = pd.DataFrame(dict(open=p - 0.5, high=p, low=p - 1, close=p, volume=1.0), index=idx)
    w = fenetres_utc(df, 21 * 60, 23 * 60)
    assert len(w) == 1 and w.debut.iloc[0] == 22 * 60 and w.fin.iloc[0] == 23 * 60 - 1
    e, s_ = df.loc["2024-06-05 22:01", "open"], df.loc["2024-06-05 23:00", "close"]
    assert w.entree.iloc[0] == e and w.sortie.iloc[0] == s_ and abs(w.r.iloc[0] - (s_ / e - 1)) < 1e-12
    w2 = fenetres_utc(df, 21 * 60, 23 * 60, seance=False)
    assert len(w2) == 1 and w2.debut.iloc[0] == 21 * 60


def test_edgar_conventions_d_heure():
    from nexus.perso.edgar import heure_new_york
    # AAPL (New York decale deux fois) : 02:31:06Z le 27/01/2016 = 16:31:06 le 26/01 (hiver) ; 00:31:09Z le 27/04 = 16:31:09
    assert heure_new_york("2016-01-27T02:31:06.000Z") == pd.Timestamp("2016-01-26 16:31:06")
    assert heure_new_york("2016-04-27T00:31:09.000Z") == pd.Timestamp("2016-04-26 16:31:09")
    # NFLX (UTC vrai) : 20:03:19Z le 16/07/2026 = 16:03:19 (ete) ; 21:07:54Z le 20/01/2026 = 16:07:54 (hiver)
    assert heure_new_york("2026-07-16T20:03:19.000Z", double=False) == pd.Timestamp("2026-07-16 16:03:19")
    assert heure_new_york("2026-01-20T21:07:54.000Z", double=False) == pd.Timestamp("2026-01-20 16:07:54")


def test_zones_orb23_stop_et_cloture():
    from types import SimpleNamespace
    from nexus.perso import zones as Z
    # deux seances de Tokyo (9:00 JST = 0:00 UTC), fin de barre UTC ; jour 1 : bougie haussiere puis hausse (sortie a la
    # cloture de 15:00) ; jour 2 : bougie haussiere puis chute sous le plus bas de la bougie (sortie au stop)
    t, o, h, l, c = [], [], [], [], []
    for d, chute in (("2024-03-04", False), ("2024-03-05", True)):
        for k in range(360):                                            # 9:00 -> 15:00 JST
            p = 100 + 0.1 * k if (k < 5 or not chute) else 100.5 - 0.2 * (k - 5)
            t.append(pd.Timestamp(d) + pd.Timedelta(minutes=k + 1)); o.append(p - 0.05); c.append(p); h.append(p + 0.02); l.append(p - 0.07)
    m = SimpleNamespace(t=pd.DatetimeIndex(t).as_unit("ns").asi8, o=np.array(o), h=np.array(h), l=np.array(l), c=np.array(c), n=len(c),
                        offset=np.zeros(len(c)))
    Z.SEANCES["TEST"] = ("Asia/Tokyo", 9 * 60, lambda d: 15 * 60)
    Z.FIN_DONNEES = pd.Timestamp("2024-03-05")
    j0 = Z.jours_seance
    Z.jours_seance = lambda m_, s_: (pd.DatetimeIndex(["2024-03-04", "2024-03-05"]), np.array([900, 900]))
    try:
        tr = Z.orb23(m, "TEST")
    finally:
        Z.jours_seance = j0
    assert list(tr.sens) == [1, 1]
    lo = min(l[360:365])
    assert abs(tr.r.iloc[0] - (c[359] / o[5] - 1)) < 1e-12
    assert abs(tr.r.iloc[1] - (lo / o[365] - 1)) < 1e-9 or tr.r.iloc[1] < 0


def test_fin_de_mois_taux_fenetres():
    import pandas as pd
    from nexus.perso.fin_de_mois_taux import fenetre, quotidien, rang_fin
    idx = pd.bdate_range("2024-01-24", "2024-02-29")
    x = pd.Series(1.0, index=idx)
    j = rang_fin(idx)
    assert j.loc["2024-01-31"] == 1 and j.loc["2024-01-30"] == 2 and j.loc["2024-02-29"] == 1
    v = fenetre(x, 2, 1)                                   # deux seances par mois : T-1 et T
    assert list(v.index) == [pd.Timestamp("2024-01-31"), pd.Timestamp("2024-02-29")] and (v == 2.0).all()
    q = quotidien(x, 2, 1, cout=1.0)                       # 1 pb a l entree et 1 pb a la sortie
    assert q.loc["2024-01-30"] == 0.0 and q.loc["2024-01-31"] == 0.0 and q.loc["2024-01-29"] == 0.0


def test_t_attendu():
    from nexus.perso.soixante import t_attendu
    # cas de fin_de_mois_taux : ~8 pb publies sur 2015-2019, 2 pb de couts, ecart-type ~50 pb, 129 mois
    assert 1.3 < t_attendu(8.0, 2.0, 50.0, 129) < 1.5
    assert t_attendu(8.0, 2.0, 0.0, 129) != t_attendu(8.0, 2.0, 0.0, 129)   # nan


def test_orb_ancre_9h30_identique_a_orb():
    from nexus import orb as O
    from nexus.perso import orb_ancre as A
    # 20 seances synthetiques de 9:31 a 16:00 (barres datees a leur fin), marche aleatoire : l ancre 0 doit redonner
    # exactement les ordres de nexus.orb.signaux (memes entrees, prix, stops et tailles)
    rng = np.random.default_rng(3)
    idx, px = [], []
    p0 = 100.0
    for d in pd.bdate_range("2024-01-02", periods=20):
        for k in range(1, 391):
            idx.append(d + pd.Timedelta(minutes=570 + k))
            p0 *= 1 + rng.normal(0, 0.001)
            px.append(p0)
    c = np.array(px)
    m = pd.DataFrame(dict(open=c * (1 - 0.0002), high=c * 1.001, low=c * 0.999, close=c,
                          volume=rng.integers(50, 150, len(c)).astype(float)), index=pd.DatetimeIndex(idx))
    m["frais"], m["glissement"] = 1e-5, 1e-5
    p = dict(O.DEFAULTS, volume_jours=3, atr_jours=3)
    ref = O.signaux(m, p)[:6]
    tabs, jour, mn = A.tables(m, p, [0])
    cal = pd.DatetimeIndex(sorted(set(m.index.normalize())))
    sig = A.signaux_ancre(m, p, tabs, jour, mn, {d: 0 for d in cal})
    assert ref[0].sum() + ref[1].sum() > 0
    for x, y in zip(ref, sig):
        assert np.array_equal(np.nan_to_num(np.asarray(x, float)), np.nan_to_num(np.asarray(y, float)))


def test_etf_nuit_comouvement_et_anticipation():
    from nexus.perso import etf_nuit as E
    # 3 secteurs synthetiques : C = 1 quand toutes les nuits ont le meme signe, < 1 sinon ; le seuil n utilise que le passe
    idx = pd.bdate_range("2020-01-01", periods=300)
    rng = np.random.default_rng(5)
    etf = {}
    for s in ("A", "B", "C"):
        c = 100 * np.exp(np.cumsum(rng.normal(0, 0.01, len(idx))))
        o = np.r_[c[0], c[:-1]] * np.exp(rng.normal(0, 0.003, len(idx)))
        etf[s] = pd.DataFrame(dict(Open=o, Close=c), index=idx)
    sig = E.signal(etf)
    on = pd.DataFrame({s: d["Open"] / d["Close"].shift(1) - 1 for s, d in etf.items()}).dropna()
    meme = (np.sign(on).nunique(axis=1) == 1)
    assert np.allclose(sig.loc[meme[meme].index, "C"], 1.0)
    assert (sig.loc[meme[~meme].index, "C"] < 1).all()
    coupe = idx[280]
    alt = {s: d.assign(Open=np.where(d.index > coupe, d["Open"] * 1.05, d["Open"])) for s, d in etf.items()}
    s2 = E.signal(alt)
    assert sig.loc[:coupe, ["sentiment", "D"]].equals(s2.loc[:coupe, ["sentiment", "D"]])


def test_tiers_vendredi_echeances():
    from nexus.perso import tiers_vendredi as T
    # jours de bourse US de 2026 sans le 19 juin (Juneteenth) : l echeance de juin passe au jeudi 18
    jours = pd.bdate_range("2026-01-02", "2026-12-31")
    jours = jours[jours != pd.Timestamp("2026-06-19")]
    e = T.echeances(jours)
    assert list(e) == [pd.Timestamp(x) for x in ("2026-03-20", "2026-06-18", "2026-09-18", "2026-12-18")]
    assert len(T.echeances(jours, trimestrielles=False)) == 12


def test_crypto_retour_heures_permises():
    from nexus.perso import crypto_retour as C
    ny = "America/New_York"
    t = lambda s: pd.DatetimeIndex([pd.Timestamp(s, tz=ny).tz_convert("UTC")])  # noqa: E731
    two = pd.Timedelta(hours=2)
    # mardi 10:00 -> 12:00 : permis ; mardi 15:00 -> 17:00 : traverse 16:10 ; samedi : non ; dimanche 18:00 -> 20:00 : permis
    assert C.permis(t("2024-03-05 10:00"), t("2024-03-05 10:00") + two)[0]
    assert not C.permis(t("2024-03-05 15:00"), t("2024-03-05 15:00") + two)[0]
    assert not C.permis(t("2024-03-09 10:00"), t("2024-03-09 10:00") + two)[0]
    assert C.permis(t("2024-03-10 18:00"), t("2024-03-10 18:00") + two)[0]
    assert not C.permis(t("2024-03-08 15:00"), t("2024-03-08 15:00") + two)[0]


def test_ouverture_europe_nuit_de_la_veille():
    from types import SimpleNamespace
    from nexus.perso import ouverture_europe as O
    # barres 1 minute (fin de barre, UTC) du dimanche 7 au lundi 8 janvier 2024 ; prix = minute de la barre
    t = pd.date_range("2024-01-07 23:01", "2024-01-08 12:00", freq="1min").as_unit("ns").asi8
    px = np.arange(len(t), dtype=float)
    m = SimpleNamespace(t=t, o=px, c=px + 0.5, n=len(t), offset=np.zeros(len(t)), rc=np.full(len(t), np.nan))
    f = O.jambe(m, pd.DatetimeIndex(["2024-01-08"]), O.ENTREE, O.SORTIE_H, veille_a=True, veille_b=False)
    # lundi : achat le dimanche 23:30 ET (= lundi 4:30 UTC), vente le lundi 3:30 ET (= 8:30 UTC), ouverture de la barre
    a = (pd.Timestamp("2024-01-08 04:31") - pd.Timestamp("2024-01-07 23:01")) // pd.Timedelta(minutes=1)
    b = (pd.Timestamp("2024-01-08 08:31") - pd.Timestamp("2024-01-07 23:01")) // pd.Timedelta(minutes=1)
    assert f["motif"].iloc[0] == "" and f["pa"].iloc[0] == a and f["pb"].iloc[0] == b


def test_pente_fomc_signal_publie_et_substitut_sofr():
    from nexus.perso import pente_fomc as P
    # rapports du mardi : 3M au-dessus de la moyenne, 30 ans en dessous -> binaire 1 ; Eurodollar puis SOFR 3 mois
    dates = pd.date_range("2023-01-03", "2023-06-27", freq="7D")
    lignes = []
    for d in dates:
        ed = 50.0 if d <= P.DERNIER_ED else -500.0          # Eurodollar residuel apres la conversion : ignore
        sr3 = 50.0 if d >= P.PREMIER_SR3 else -500.0        # SOFR ignore avant la conversion
        for marche, sp in (("ED", ed), ("SR3", sr3), ("10Y", 0.0), ("30Y", -50.0)):
            lignes.append(dict(marche=marche, date=d, longs=100.0 + sp, courts=100.0, sp=sp))
    b = P.binaire(pd.DataFrame(lignes))
    assert (b.binaire == 1).all() and (b.loc[:P.DERNIER_ED, "source_3m"] == "ED").all()
    # un rapport ne sert qu apres son delai de publication (mesure + 6 jours) : le mercredi 2023-03-22, le rapport du
    # mardi 21 et celui du 14 (publie le 20, < 22) ; le 21 est exclu
    s, n = P.steep(b, pd.Timestamp("2023-03-22"))
    assert s == 1.0 and n == len([d for d in dates if d + pd.Timedelta(days=6) < pd.Timestamp("2023-03-22")
                                  and d > pd.Timestamp("2023-03-22") - pd.Timedelta(days=91)])
    # fermeture de l Etat 2025 : rapport du 2025-10-07 publie le 2026-01-23 seulement
    p = P.publication(pd.Series(pd.to_datetime(["2025-09-23", "2025-10-07"])))
    assert p.iloc[0] == pd.Timestamp("2025-09-29") and p.iloc[1] == pd.Timestamp("2026-01-23")
    # sens fige du papier : vente si STEEP = 0, achat des le premier rapport de pentification
    assert P.B0 + P.B1 * 0.0 < 0 < P.B0 + P.B1 / 13


def test_kairos_jambes_cassure_stop_et_sortie():
    from nexus.perso import kairos_jambes as K
    # range sur les barres 0-2 (haut 10, bas 8), entree sur 3-5, sortie a l ouverture de la barre 6
    o = np.array([9.0, 9.0, 9.0, 9.5, 10.5, 10.0, 11.0])
    h = np.array([10.0, 9.5, 9.5, 9.8, 10.8, 10.4, 11.2])
    l = np.array([8.0, 8.5, 8.5, 9.2, 10.2, 9.6, 10.8])
    c = o.copy()
    tr = K.jour_trade(o, h, l, c, 0, 3, 3, 6, 6, 0.25, "milieu")
    # cassure du haut + 1 tick (10,25) a la barre 4, ouverture 10,5 au-dela : rempli a 10,5 ; stop au milieu (9) jamais
    # touche ; sortie a l ouverture de la barre 6
    assert tr == (1, 4, 10.5, 6, 11.0, "heure")
    l2 = l.copy()
    l2[5] = 8.9
    tr = K.jour_trade(o, h, l2, c, 0, 3, 3, 6, 6, 0.25, "milieu")
    assert tr[0] == 1 and tr[3] == 5 and tr[4] == 9.0 and tr[5] == "stop"   # stop au milieu de l IB (ouverture 10 au-dessus)
    tr = K.jour_trade(o, h, l2, c, 0, 3, 3, 6, 6, 0.25, "borne")
    assert tr[5] == "heure"                                                 # stop a l autre borne (8) non touche
    assert K.jour_trade(o, np.minimum(h, 10.1), np.maximum(l, 7.9), c, 0, 3, 3, 6, 6, 0.25, "borne") is None


def test_kairos_publiees_stop_et_atr():
    from types import SimpleNamespace
    from nexus.perso import kairos_publiees as K
    m = SimpleNamespace(o=np.array([100.0, 101.0, 99.0, 102.0]), h=np.array([101.0, 102.0, 100.0, 103.0]),
                        l=np.array([99.5, 100.5, 97.0, 101.0]))
    assert K._tenir(m, 1, 0, None, 3) == (3, 102.0, "heure")
    assert K._tenir(m, 1, 0, 98.0, 3) == (2, 98.0, "stop")             # touche a la barre 2 (ouverture 99 au-dessus)
    assert K._tenir(m, -1, 0, 101.5, 3) == (1, 101.5, "stop")          # vente : haut 102 >= 101,5
    w = K.wilder(np.array([2.0, 2.0, 2.0, 7.0]), 5)
    assert np.isclose(w[-1], 2.0 + (7.0 - 2.0) / 5)
