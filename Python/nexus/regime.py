"""MODULE A - Regime : HMM gaussien 3 etats a covariance diagonale + terciles de vol (fiche 12).
Port de AddOns/NexusModuleA_RegimeHmm.cs.

HMM : variables standardisees, fenetre 600 j, probabilites FILTREES (passe avant seule),
EMA 5 j, plafond 0.95, re-estimation hebdomadaire, 10 initialisations (graine fixe),
etats tries par volatilite moyenne -> Calme / Neutre / Stress.
Baum-Welch compile avec numba (meme algorithme que le C#, generateur aleatoire different).
"""
from __future__ import annotations

import math

import numpy as np

from . import mathx as M

try:
    from numba import njit
except ImportError:  # pragma: no cover
    def njit(*a, **k):
        def deco(f):
            return f
        return deco(a[0]) if a and callable(a[0]) else deco

CALME, NEUTRE, STRESS, INCONNU = "Calme", "Neutre", "Stress", "Inconnu"
VAR_FLOOR = 1e-3


@njit(cache=True)
def _emissions(X, mu, var):
    T, D = X.shape
    K = mu.shape[0]
    b = np.empty((T, K))
    shift = np.empty(T)
    for t in range(T):
        mx = -1e300
        for k in range(K):
            s = 0.0
            for d in range(D):
                v = max(var[k, d], VAR_FLOOR)
                e = X[t, d] - mu[k, d]
                s += -0.5 * (math.log(2 * math.pi * v) + e * e / v)
            b[t, k] = s
            if s > mx:
                mx = s
        for k in range(K):
            b[t, k] = math.exp(b[t, k] - mx)
        shift[t] = mx
    return b, shift


@njit(cache=True)
def _baum_welch(X, pi, A, mu, var, max_iter, tol):
    T, D = X.shape
    K = mu.shape[0]
    alpha = np.zeros((T, K))
    beta = np.zeros((T, K))
    c = np.zeros(T)
    prev_ll = -1e300
    ll = -1e300
    iters = 0
    for it in range(max_iter):
        b, shift = _emissions(X, mu, var)
        ll = 0.0
        for t in range(T):
            ll += shift[t]
        for t in range(T):
            s = 0.0
            for j in range(K):
                pred = 0.0
                if t == 0:
                    pred = pi[j]
                else:
                    for i in range(K):
                        pred += alpha[t - 1, i] * A[i, j]
                alpha[t, j] = pred * b[t, j]
                s += alpha[t, j]
            if not (s > 0):
                return pi, A, mu, var, -np.inf, it
            c[t] = s
            for j in range(K):
                alpha[t, j] /= s
            ll += math.log(s)
        for k in range(K):
            beta[T - 1, k] = 1.0
        for t in range(T - 2, -1, -1):
            for i in range(K):
                s = 0.0
                for j in range(K):
                    s += A[i, j] * b[t + 1, j] * beta[t + 1, j]
                beta[t, i] = s / c[t + 1]
        gamma = alpha * beta
        for t in range(T):
            s = 0.0
            for k in range(K):
                s += gamma[t, k]
            if s > 0:
                for k in range(K):
                    gamma[t, k] /= s
        xi_sum = np.zeros((K, K))
        for t in range(T - 1):
            s = 0.0
            xi = np.empty((K, K))
            for i in range(K):
                for j in range(K):
                    xi[i, j] = alpha[t, i] * A[i, j] * b[t + 1, j] * beta[t + 1, j]
                    s += xi[i, j]
            if s > 0:
                for i in range(K):
                    for j in range(K):
                        xi_sum[i, j] += xi[i, j] / s
        for k in range(K):
            pi[k] = max(gamma[0, k], 1e-6)
        pi /= pi.sum()
        for i in range(K):
            row = xi_sum[i].sum()
            for j in range(K):
                A[i, j] = max(xi_sum[i, j] / row, 1e-6) if row > 0 else 1.0 / K
            A[i] /= A[i].sum()
        for k in range(K):
            g = gamma[:, k].sum()
            if g < 1e-8:
                continue
            for d in range(D):
                m = (gamma[:, k] * X[:, d]).sum() / g
                v = (gamma[:, k] * (X[:, d] - m) ** 2).sum() / g
                mu[k, d] = m
                var[k, d] = max(v, VAR_FLOOR)
        iters = it + 1
        if abs(ll - prev_ll) < tol:
            break
        prev_ll = ll
    return pi, A, mu, var, ll, iters


class GaussianHmm:
    def __init__(self, k: int, d: int):
        self.K, self.D = k, d
        self.pi = np.full(k, 1.0 / k)
        self.A = np.full((k, k), 1.0 / k)
        self.mu = np.zeros((k, d))
        self.var = np.ones((k, d))
        self.log_likelihood = -math.inf
        self.iterations = 0

    def _random_init(self, X: np.ndarray, rng: np.random.Generator):
        T = X.shape[0]
        gv = np.maximum(X.var(axis=0), VAR_FLOOR)
        for k in range(self.K):
            p = X[rng.integers(T)]
            self.mu[k] = p + 0.1 * (rng.random(self.D) - 0.5) * np.sqrt(gv)
            self.var[k] = gv * (0.5 + rng.random(self.D))
            self.pi[k] = 1.0 / self.K
            row = np.array([(0.90 if j == k else 0.10 / (self.K - 1)) * (0.8 + 0.4 * rng.random()) for j in range(self.K)])
            self.A[k] = row / row.sum()

    @staticmethod
    def fit(X: np.ndarray, k: int, n_init: int, max_iter: int, tol: float, seed: int):
        if X is None or len(X) < 10 * k:
            return None
        rng = np.random.default_rng(seed)
        best = None
        for _ in range(max(1, n_init)):
            h = GaussianHmm(k, X.shape[1])
            h._random_init(X, rng)
            pi, A, mu, var, ll, it = _baum_welch(np.ascontiguousarray(X), h.pi.copy(), h.A.copy(), h.mu.copy(), h.var.copy(), max_iter, tol)
            h.pi, h.A, h.mu, h.var, h.log_likelihood, h.iterations = pi, A, mu, var, ll, it
            if M.ok(ll) and (best is None or ll > best.log_likelihood):
                best = h
        return best

    def forward_step(self, prev, x):
        b, _ = _emissions(np.asarray(x, float)[None, :], self.mu, self.var)
        pred = self.pi if prev is None else prev @ self.A
        a = pred * b[0]
        s = a.sum()
        if not s > 0 or math.isnan(s):
            return np.full(self.K, 1.0 / self.K)
        return a / s

    def filter_last(self, X):
        a = None
        for t in range(X.shape[0]):
            a = self.forward_step(a, X[t])
        return a


def cap_probabilities(p, cap: float):
    q = np.asarray(p, float).copy()
    s = q.sum()
    if s <= 0:
        return np.full(len(q), 1.0 / len(q))
    q /= s
    for _ in range(5):
        over = q > cap
        excess = float((q[over] - cap).sum())
        q[over] = cap
        free = float(q[~over].sum())
        if excess <= 1e-12:
            break
        mask = q < cap
        if free > 0:
            q[mask] += excess * q[mask] / free
        else:
            q[mask] += excess / (len(q) - 1)
    return q


class HmmRegimeDetector:
    def __init__(self, use_vix: bool = False, window=600, refit_every_days=5, n_init=10, max_iter=200, tol=1e-4,
                 smooth_span=5, cap=0.95, vol_window=20, seed=42, min_observations=250):
        self.use_vix = use_vix
        self.dims = 3 if use_vix else 2
        self.window, self.refit_every_days, self.n_init, self.max_iter, self.tol = window, refit_every_days, n_init, max_iter, tol
        self.smooth_span, self.cap, self.vol_window, self.seed, self.min_observations = smooth_span, cap, vol_window, seed, min_observations
        self.closes: list[float] = []
        self.rets: list[float] = []
        self.features: list[list[float]] = []
        self.model: GaussianHmm | None = None
        self.f_mean = self.f_std = None
        self.order = None
        self.filtered = None
        self.smoothed = None
        self.days_since_fit = 1 << 30
        self.fit_count = 0

    @property
    def is_ready(self) -> bool:
        return self.smoothed is not None

    @property
    def probabilities(self):
        return (M.NAN, M.NAN, M.NAN) if self.smoothed is None else tuple(self.smoothed)

    @property
    def regime(self) -> str:
        if self.smoothed is None:
            return INCONNU
        k = int(np.argmax(self.smoothed))
        return (CALME, NEUTRE, STRESS)[k]

    def update(self, close: float, vix: float = M.NAN):
        if not M.ok(close) or close <= 0:
            return
        if self.closes:
            self.rets.append(math.log(close / self.closes[-1]))
        self.closes.append(close)
        if len(self.rets) < self.vol_window:
            return
        vol = float(np.std(self.rets[-self.vol_window:], ddof=1)) * math.sqrt(M.TRADING_DAYS_PER_YEAR)
        r = self.rets[-1]
        if self.use_vix:
            if not M.ok(vix) or vix <= 0:
                vix = self.features[-1][2] if self.features else vol * 100
            f = [r, vol, vix]
        else:
            f = [r, vol]
        self.features.append(f)
        if len(self.features) > self.window * 2:
            del self.features[: len(self.features) - self.window * 2]
        self.days_since_fit += 1
        if len(self.features) >= self.min_observations and (self.model is None or self.days_since_fit >= self.refit_every_days):
            self._refit()
        elif self.model is not None:
            self.filtered = self.model.forward_step(self.filtered, self._std(f))
            self._publish()

    def _std(self, f):
        return np.where(self.f_std > 0, (np.asarray(f) - self.f_mean) / self.f_std, 0.0)

    def _refit(self):
        win = np.asarray(self.features[-min(self.window, len(self.features)):], float)
        self.f_mean = win.mean(axis=0)
        sd = win.std(axis=0, ddof=1)
        self.f_std = np.where(np.isfinite(sd) & (sd > 0), sd, 1.0)
        X = (win - self.f_mean) / self.f_std
        h = GaussianHmm.fit(X, 3, self.n_init, self.max_iter, self.tol, self.seed + self.fit_count)
        if h is None:
            return
        self.model = h
        self.order = np.argsort(h.mu[:, 1], kind="stable")    # variable 1 = volatilite realisee
        self.filtered = h.filter_last(X)
        self.days_since_fit = 0
        self.fit_count += 1
        self._publish()

    def _publish(self):
        p = np.array([self.filtered[self.order[i]] for i in range(3)])
        if self.smoothed is None:
            self.smoothed = p
        else:
            a = 2.0 / (self.smooth_span + 1.0)
            self.smoothed = a * p + (1 - a) * self.smoothed
        self.smoothed = cap_probabilities(self.smoothed, self.cap)

    def describe(self) -> str:
        if not self.is_ready:
            return f"HMM: en chauffage ({len(self.features)}/{self.min_observations} obs)"
        p = self.probabilities
        return f"HMM {self.regime} | P(calme)={p[0]:.2f} P(neutre)={p[1]:.2f} P(stress)={p[2]:.2f} | fits={self.fit_count}"


class VolTercileRegime:
    """Fiche 12 : terciles de la vol realisee 20 j sur 2 ans, anti-clignotement 5 jours."""

    def __init__(self, rv_window=20, lookback_days=504, confirm_days=5, min_history=120):
        self.rv_window, self.lookback_days, self.confirm_days, self.min_history = rv_window, lookback_days, confirm_days, min_history
        self.closes: list[float] = []
        self.rets: list[float] = []
        self.rv_hist: list[float] = []
        self.candidate = INCONNU
        self.candidate_count = 0
        self.regime = INCONNU
        self.raw_regime = INCONNU
        self.rv = self.low_cut = self.high_cut = M.NAN
        self.days_in_regime = 0

    @property
    def is_ready(self) -> bool:
        return self.regime != INCONNU

    def update(self, close: float):
        if not M.ok(close) or close <= 0:
            return
        if self.closes:
            self.rets.append(math.log(close / self.closes[-1]))
        self.closes.append(close)
        cap = self.lookback_days + self.rv_window + 10
        if len(self.closes) > cap:
            self.closes.pop(0)
        if len(self.rets) > cap:
            self.rets.pop(0)
        if len(self.rets) < self.rv_window:
            return
        self.rv = float(np.std(self.rets[-self.rv_window:], ddof=1)) * math.sqrt(M.TRADING_DAYS_PER_YEAR)
        self.rv_hist.append(self.rv)
        if len(self.rv_hist) > self.lookback_days:
            self.rv_hist.pop(0)
        if len(self.rv_hist) < self.min_history:
            return
        self.low_cut = M.quantile(self.rv_hist, 1 / 3)
        self.high_cut = M.quantile(self.rv_hist, 2 / 3)
        self.raw_regime = CALME if self.rv < self.low_cut else (STRESS if self.rv > self.high_cut else NEUTRE)
        if self.regime == INCONNU:
            self.regime, self.days_in_regime = self.raw_regime, 1
            return
        if self.raw_regime == self.regime:
            self.candidate, self.candidate_count = INCONNU, 0
            self.days_in_regime += 1
            return
        if self.raw_regime == self.candidate:
            self.candidate_count += 1
        else:
            self.candidate, self.candidate_count = self.raw_regime, 1
        if self.candidate_count >= self.confirm_days:
            self.regime, self.candidate, self.candidate_count, self.days_in_regime = self.candidate, INCONNU, 0, 1
        else:
            self.days_in_regime += 1

    def describe(self) -> str:
        return (f"VolTerciles {self.regime} (brut {self.raw_regime}) RV20={self.rv:.1%} "
                f"coupures [{self.low_cut:.1%} ; {self.high_cut:.1%}]")


class LazyHmm:
    """HMM evalue seulement si la strategie le demande (evite le cout quand la source est 'terciles')."""

    def __init__(self, enabled: bool, use_vix: bool):
        self.enabled = enabled
        self.det = HmmRegimeDetector(use_vix) if enabled else None

    def update(self, close, vix=M.NAN):
        if self.det is not None:
            self.det.update(close, vix)

    @property
    def regime(self):
        return self.det.regime if self.det is not None else INCONNU

    def describe(self):
        return self.det.describe() if self.det is not None else "HMM inactif"
