"""Tests numeriques du socle : memes controles que Tests/Unit/Tests.cs (C#)."""
import math

import numpy as np
import pytest

from nexus import mathx as M
from nexus import regime as R
from nexus import sizing as B
from nexus import validation as V


def test_loi_normale():
    assert abs(M.norm_cdf(1.96) - 0.9750021) < 2e-7
    assert abs(M.norm_cdf(-3) - 0.0013499) < 2e-7
    assert abs(M.norm_inv(0.975) - 1.959964) < 1e-5
    assert abs(M.norm_inv(0.001) + 3.090232) < 1e-5


@pytest.mark.parametrize("t,n,p,tol", [(-2.86, 1, 0.05, 0.003), (-3.43, 1, 0.01, 0.002), (-2.57, 1, 0.10, 0.005),
                                       (-3.34, 2, 0.05, 0.004), (-3.90, 2, 0.01, 0.003)])
def test_mackinnon(t, n, p, tol):
    assert abs(M.mackinnon_p(t, n) - p) < tol


def test_mackinnon_monotone():
    assert M.mackinnon_p(-1.0) > M.mackinnon_p(-2.0) > M.mackinnon_p(-3.0)


def test_adf_taille_et_puissance():
    rng = np.random.default_rng(1)
    rw_rej = ar_rej = 0
    trials = 120
    for _ in range(trials):
        e = rng.standard_normal(400)
        rw = np.cumsum(e)
        ar = np.zeros(400)
        for t in range(1, 400):
            ar[t] = 0.7 * ar[t - 1] + e[t]
        rw_rej += M.adf_test(rw).pvalue < 0.05
        ar_rej += M.adf_test(ar).pvalue < 0.05
    assert rw_rej / trials < 0.11
    assert ar_rej / trials > 0.95


def test_engle_granger():
    rng = np.random.default_rng(2)
    coint = indep = 0
    trials = 100
    for _ in range(trials):
        x = np.cumsum(0.01 * rng.standard_normal(300))
        y = np.cumsum(0.01 * rng.standard_normal(300))
        e = np.zeros(300)
        for t in range(1, 300):
            e[t] = 0.8 * e[t - 1] + 0.005 * rng.standard_normal()
        b = 4 + x
        a = 0.5 + 1.2 * b + e
        c = 4 + y
        coint += M.engle_granger(a, b)[0].pvalue < 0.05
        indep += M.engle_granger(a, c)[0].pvalue < 0.05
    assert coint / trials > 0.9
    assert indep / trials < 0.11


def test_ornstein_uhlenbeck():
    rng = np.random.default_rng(3)
    x = np.zeros(5000)
    x[0] = 2.0
    for t in range(1, 5000):
        x[t] = 0.2 + 0.9 * x[t - 1] + 0.1 * rng.standard_normal()
    f = M.ou_fit(x)
    assert abs(f.b - 0.9) < 0.02
    assert abs(f.half_life - math.log(2) / -math.log(0.9)) < 1.0
    assert abs(f.mean - 2.0) < 0.15
    assert abs(f.sigma_eq - 0.1 / math.sqrt(1 - 0.81)) < 0.02


def test_black_scholes():
    S, K, T, r, v = 100.0, 95.0, 30 / 365, 0.04, 0.3
    c0, p0 = M.bs_price(True, S, K, T, r, v), M.bs_price(False, S, K, T, r, v)
    assert abs(c0 - p0 - (S - K * math.exp(-r * T))) < 1e-9
    kp = M.bs_strike_from_delta(False, S, T, r, v, -0.25)
    assert abs(M.bs_delta(False, S, kp, T, r, v) + 0.25) < 1e-6
    kc = M.bs_strike_from_delta(True, S, T, r, v, 0.25)
    assert abs(M.bs_delta(True, S, kc, T, r, v) - 0.25) < 1e-6
    assert abs(M.bs_implied_vol(False, p0, S, K, T, r) - v) < 1e-4


def test_kelly_fiche_b():
    lo, hi = B.wilson(227, 480)
    assert abs(lo - 0.427) < 0.004 and abs(hi - 0.517) < 0.004
    assert abs(B.break_even_payoff(0.472) - 1.1186) < 0.001
    assert B.kelly_fraction(0.472, 1.1) <= 0
    fk = B.kelly_fraction(0.55, 1.5)
    rck = B.risk_constrained_kelly(0.55, 1.5, 0.7, 0.1)
    assert 0 < rck <= fk + 1e-12
    cfg = B.SizingConfig()
    sr = B.size(cfg, B.TradeStats(), 0.1, M.NAN, 0.0, 1000.0, 0.0, 0.0, 0.0)
    assert abs(sr.fraction - min(0.03, 0.5 * 0.5 * B.kelly_fraction(0.5, 1.2))) < 1e-9
    sr = B.size(cfg, B.TradeStats(), 0.1, M.NAN, 0.0, 1000.0, 0.0, 0.29, 0.0)
    assert sr.fraction <= 0.01 + 1e-9


def test_kelly_negatif_taille_sonde_par_defaut():
    """Kelly <= 0 : taille sonde de 0.25 % (l estimation peut remonter) ; sans waiver en backtest."""
    st = B.TradeStats()
    for r in [-0.03] * 6 + [0.01] * 2:
        st.add(r)
    sr = B.size(B.SizingConfig(apply_waiver=False), st, 0.03, M.NAN, 0.0, 1e5, 0, 0, 0)
    assert not sr.blocked and abs(sr.fraction - 0.0025) < 1e-12 and "sonde" in sr.detail


def test_kelly_negatif_bloque_si_sonde_nulle():
    """no_edge_fraction = 0 : blocage definitif (comportement d origine, sur demande)."""
    st = B.TradeStats()
    for r in [-0.03] * 6 + [0.01] * 2:
        st.add(r)
    sr = B.size(B.SizingConfig(no_edge_fraction=0.0), st, 0.03, M.NAN, 0.0, 1e5, 0, 0, 0)
    assert sr.blocked and sr.fraction == 0


def test_waiver_seulement_si_demande():
    """Davey waiver : regle du temps reel ; en backtest il ne s applique que si apply_waiver=True."""
    libre = dict(max_trade_fraction=0.0, max_symbol_fraction=0.0, max_class_fraction=0.0, max_total_fraction=0.0)
    sans = B.size(B.SizingConfig(apply_waiver=False, **libre), B.TradeStats(), 0.02, M.NAN, 0.0, 1e5, 0, 0, 0)
    avec = B.size(B.SizingConfig(apply_waiver=True, **libre), B.TradeStats(), 0.02, M.NAN, 0.0, 1e5, 0, 0, 0)
    assert abs(avec.fraction - 0.5 * sans.fraction) < 1e-12


def test_hmm_retrouve_les_etats():
    rng = np.random.default_rng(7)
    n = 900
    mus, sds, vm = (0.05, 0.0, -0.1), (0.5, 1.0, 2.0), (-1.0, 0.0, 1.5)
    X = np.zeros((n, 2))
    truth = np.zeros(n, int)
    stt = 0
    for t in range(n):
        if rng.random() < 0.02:
            stt = rng.integers(3)
        truth[t] = stt
        X[t] = [mus[stt] + sds[stt] * rng.standard_normal(), vm[stt] + 0.3 * rng.standard_normal()]
    h = R.GaussianHmm.fit(X, 3, 10, 200, 1e-4, 42)
    order = list(np.argsort(h.mu[:, 1]))
    a, good = None, 0
    for t in range(n):
        a = h.forward_step(a, X[t])
        good += order.index(int(np.argmax(a))) == truth[t]
    assert good / n > 0.85
    assert R.cap_probabilities([0.999, 0.0005, 0.0005], 0.95).max() <= 0.95 + 1e-12


def test_hmm_detecteur_stress():
    rng = np.random.default_rng(3)
    det = R.HmmRegimeDetector(False, window=500, min_observations=250)
    px = 100.0
    for t in range(900):
        vol = 0.007 if t % 300 < 200 else 0.025
        px *= math.exp(vol * rng.standard_normal())
        det.update(px)
    assert det.is_ready and det.regime == R.STRESS


def test_terciles_anti_clignotement():
    rng = np.random.default_rng(4)
    vt = R.VolTercileRegime()
    px, flips, raw_flips, prev, prev_raw = 100.0, 0, 0, R.INCONNU, R.INCONNU
    for t in range(1500):
        vol = 0.006 if (t // 150) % 2 == 0 else 0.02
        px *= math.exp(vol * rng.standard_normal())
        vt.update(px)
        flips += vt.regime != prev and prev != R.INCONNU
        raw_flips += vt.raw_regime != prev_raw and prev_raw != R.INCONNU
        prev, prev_raw = vt.regime, vt.raw_regime
    assert flips < 0.6 * raw_flips
    v2 = R.VolTercileRegime()
    px, saw_stress = 100.0, False
    for t in range(1200):
        px *= math.exp((0.008 if t < 900 else 0.03) * rng.standard_normal())
        v2.update(px)
        saw_stress |= t > 960 and v2.regime == R.STRESS
    assert saw_stress


def test_pbo_et_dsr():
    rng = np.random.default_rng(5)
    pbo_noise = np.mean([V.pbo(0.01 * np.random.default_rng(100 + ds).standard_normal((20, 800)), 16, 500, ds)[0] for ds in range(20)])
    assert 0.4 < pbo_noise < 0.6
    noise = 0.01 * rng.standard_normal((20, 800))
    skill = noise.copy()
    skill[0] += 0.004
    assert V.pbo(skill, 16, 2000, 1)[0] < 0.1
    assert V.deflated_sharpe(skill[0], 20)[0] > 0.95
    best_noise = noise[np.argmax([V.sharpe_per_period(x) for x in noise])]
    assert V.deflated_sharpe(best_noise, 20)[0] < 0.9


def test_monte_carlo_et_cycles():
    pnls = [-100.0 if i % 3 == 0 else 80.0 for i in range(200)]
    mc = V.monte_carlo_max_dd(pnls, 10000, 1000, 1)
    assert len(mc) == 1000 and mc[0] <= mc[-1]
    bb = V.block_bootstrap_max_dd(pnls, 10000, 0, 1000, 1)
    assert len(bb) == 1000 and bb[-1] > 0
    ok, dd, _ = V.has_drawdown_recovery_cycle([100, 110, 95, 100, 112], 0.05)
    assert ok and abs(dd - (1 - 95 / 110.0)) < 1e-9
    assert not V.has_drawdown_recovery_cycle([100, 110, 95, 100, 105], 0.05)[0]
    assert len(V.walk_forward_splits(400, 180, 30)) == 7
