"""Port de NexusCore.cs : NxMath, NxRegression, NxAdf (MacKinnon), NxOu, NxBlackScholes.

Memes conventions que le C# : NaN ignores, variance d echantillon (n-1),
quantile de type 7, kurtosis NON excedentaire (loi normale = 3).
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

TRADING_DAYS_PER_YEAR = 252.0
EULER_GAMMA = 0.5772156649015329
NAN = float("nan")


def ok(x) -> bool:
    try:
        return x is not None and math.isfinite(x)
    except TypeError:
        return False


def clamp(x, lo, hi):
    return lo if x < lo else (hi if x > hi else x)


def safe_div(a, b, fallback=NAN):
    if not ok(a) or not ok(b) or b == 0.0:
        return fallback
    return a / b


def _valid(x) -> np.ndarray:
    a = np.asarray(x, dtype=float)
    return a[np.isfinite(a)]


def mean(x) -> float:
    v = _valid(x)
    return float(v.mean()) if v.size else NAN


def variance(x) -> float:
    v = _valid(x)
    return float(v.var(ddof=1)) if v.size > 1 else NAN


def std(x) -> float:
    var = variance(x)
    return math.sqrt(var) if ok(var) and var >= 0 else NAN


def quantile(x, q: float) -> float:
    v = np.sort(_valid(x))
    if v.size == 0:
        return NAN
    if v.size == 1:
        return float(v[0])
    q = clamp(q, 0.0, 1.0)
    h = (v.size - 1) * q
    lo = int(math.floor(h))
    hi = min(v.size - 1, lo + 1)
    return float(v[lo] + (h - lo) * (v[hi] - v[lo]))


def median(x) -> float:
    return quantile(x, 0.5)


def correlation(a, b) -> float:
    a = np.asarray(a, dtype=float)
    b = np.asarray(b, dtype=float)
    n = min(a.size, b.size)
    a, b = a[:n], b[:n]
    m = np.isfinite(a) & np.isfinite(b)
    if m.sum() < 3:
        return NAN
    da = a[m] - a[m].mean()
    db = b[m] - b[m].mean()
    saa, sbb = float((da * da).sum()), float((db * db).sum())
    if saa <= 0 or sbb <= 0:
        return NAN
    return float((da * db).sum() / math.sqrt(saa * sbb))


def skewness(x) -> float:
    v = _valid(x)
    if v.size < 3:
        return 0.0
    e = v - v.mean()
    m2, m3 = float((e * e).mean()), float((e ** 3).mean())
    return m3 / m2 ** 1.5 if m2 > 0 else 0.0


def kurtosis(x) -> float:
    v = _valid(x)
    if v.size < 4:
        return 3.0
    e = v - v.mean()
    m2, m4 = float((e * e).mean()), float((e ** 4).mean())
    return m4 / (m2 * m2) if m2 > 0 else 3.0


def zscore(x) -> np.ndarray:
    x = np.asarray(x, dtype=float)
    m, s = mean(x), std(x)
    out = np.full(x.shape, NAN)
    fin = np.isfinite(x)
    if ok(s) and s > 0:
        out[fin] = (x[fin] - m) / s
    else:
        out[fin] = 0.0
    return out


def ranks(x) -> np.ndarray:
    """Rangs 1..n (moyenne des ex aequo), NaN -> NaN."""
    x = np.asarray(x, dtype=float)
    r = np.full(x.shape, NAN)
    idx = [i for i in np.argsort(x, kind="mergesort") if math.isfinite(x[i])]
    k = 0
    while k < len(idx):
        j = k
        while j + 1 < len(idx) and x[idx[j + 1]] == x[idx[k]]:
            j += 1
        avg = (k + j) / 2.0 + 1.0
        for t in range(k, j + 1):
            r[idx[t]] = avg
        k = j + 1
    return r


def centered_rank_z(x) -> np.ndarray:
    """"Rang centre puis z-score" (fiche 3)."""
    rk = ranks(x)
    m = mean(rk)
    c = np.where(np.isfinite(rk), rk - m, NAN)
    return zscore(c)


def norm_cdf(x: float) -> float:
    """Meme approximation que NxMath.NormCdf (|erreur| < 1.2e-7)."""
    if math.isnan(x):
        return NAN
    if x > 40:
        return 1.0
    if x < -40:
        return 0.0
    z = abs(x) / math.sqrt(2.0)
    t = 1.0 / (1.0 + 0.5 * z)
    erfc = t * math.exp(-z * z - 1.26551223 + t * (1.00002368 + t * (0.37409196 + t * (0.09678418
           + t * (-0.18628806 + t * (0.27886807 + t * (-1.13520398 + t * (1.48851587
           + t * (-0.82215223 + t * 0.17087277)))))))))
    return 1.0 - 0.5 * erfc if x >= 0 else 0.5 * erfc


def norm_pdf(x: float) -> float:
    return math.exp(-0.5 * x * x) / math.sqrt(2.0 * math.pi)


_A = (-3.969683028665376e+01, 2.209460984245205e+02, -2.759285104469687e+02, 1.383577518672690e+02, -3.066479806614716e+01, 2.506628277459239e+00)
_B = (-5.447609879822406e+01, 1.615858368580409e+02, -1.556989798598866e+02, 6.680131188771972e+01, -1.328068155288572e+01)
_C = (-7.784894002430293e-03, -3.223964580411365e-01, -2.400758277161838e+00, -2.549732539343734e+00, 4.374664141464968e+00, 2.938163982698783e+00)
_D = (7.784695709041462e-03, 3.224671290700398e-01, 2.445134137142996e+00, 3.754408661907416e+00)


def norm_inv(p: float) -> float:
    """Quantile de la loi normale (Acklam + une iteration de Newton)."""
    if math.isnan(p):
        return NAN
    if p <= 0:
        return -math.inf
    if p >= 1:
        return math.inf
    plow, phigh = 0.02425, 1 - 0.02425
    a, b, c, d = _A, _B, _C, _D
    if p < plow:
        q = math.sqrt(-2 * math.log(p))
        x = (((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1)
    elif p <= phigh:
        q = p - 0.5
        r = q * q
        x = (((((a[0] * r + a[1]) * r + a[2]) * r + a[3]) * r + a[4]) * r + a[5]) * q / (((((b[0] * r + b[1]) * r + b[2]) * r + b[3]) * r + b[4]) * r + 1)
    else:
        q = math.sqrt(-2 * math.log(1 - p))
        x = -(((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1)
    e = norm_cdf(x) - p
    u = e * math.sqrt(2 * math.pi) * math.exp(x * x / 2)
    return x - u / (1 + x * u / 2)


def welch_t(a, b) -> float:
    a, b = _valid(a), _valid(b)
    if a.size < 2 or b.size < 2:
        return NAN
    se = math.sqrt(a.var(ddof=1) / a.size + b.var(ddof=1) / b.size)
    return float((a.mean() - b.mean()) / se) if se > 0 else NAN


# =============================================================================
#  Moindres carres ordinaires (lignes avec NaN ignorees)
# =============================================================================
@dataclass
class OlsResult:
    coef: np.ndarray | None = None
    se: np.ndarray | None = None
    residuals: np.ndarray | None = None   # meme longueur que y (NaN sur les lignes ignorees)
    rss: float = NAN
    r2: float = NAN
    n: int = 0
    k: int = 0
    ok: bool = False

    def t(self, i: int) -> float:
        if self.se is None or i >= len(self.se) or not (self.se[i] > 0):
            return NAN
        return float(self.coef[i] / self.se[i])


def ols(y, X, intercept: bool = True) -> OlsResult:
    y = np.asarray(y, dtype=float)
    X = np.asarray(X, dtype=float)
    if X.ndim == 1:
        X = X[:, None]
    res = OlsResult()
    n_all = min(len(y), len(X))
    if n_all == 0:
        return res
    y, X = y[:n_all], X[:n_all]
    rows = np.isfinite(y) & np.all(np.isfinite(X), axis=1)
    Xd = X[rows]
    if intercept:
        Xd = np.column_stack([np.ones(Xd.shape[0]), Xd])
    yd = y[rows]
    n, p = Xd.shape
    res.n, res.k = n, p
    if n <= p:
        return res
    xtx = Xd.T @ Xd
    try:
        # Pivot minimal comme NxRegression.Invert (singuliere -> echec).
        if np.linalg.cond(xtx) > 1e14:
            return res
        inv = np.linalg.inv(xtx)
    except np.linalg.LinAlgError:
        return res
    beta = inv @ (Xd.T @ yd)
    fit = Xd @ beta
    e = yd - fit
    rss = float(e @ e)
    tss = float(((yd - yd.mean()) ** 2).sum())
    s2 = rss / (n - p)
    diag = np.diag(inv) * s2
    se = np.where(diag > 0, np.sqrt(np.abs(diag)), NAN)
    resid = np.full(n_all, NAN)
    resid[rows] = e
    res.coef, res.se, res.residuals, res.rss = beta, se, resid, rss
    res.r2 = 1 - rss / tss if tss > 0 else NAN
    res.ok = True
    return res


def ols_simple(y, x) -> OlsResult:
    """y = a + b x + e. coef[0]=a, coef[1]=b."""
    n = min(len(y), len(x))
    return ols(np.asarray(y, dtype=float)[:n], np.asarray(x, dtype=float)[:n], True)


# =============================================================================
#  ADF + p-values MacKinnon (regression avec constante)
# =============================================================================
_TAU_MAX_C = (2.74, 0.92, 0.55, 0.61, 0.79, 1.0)
_TAU_MIN_C = (-18.83, -18.86, -23.48, -28.07, -25.96, -23.27)
_TAU_STAR_C = (-1.61, -2.62, -3.13, -3.47, -3.78, -3.93)
_TAU_C_SMALLP = ((2.1659, 1.4412, 0.038269), (2.92, 1.5012, 0.039796), (3.4699, 1.4856, 0.03164),
                 (3.9673, 1.4777, 0.026315), (4.5509, 1.5338, 0.029545), (5.1399, 1.6036, 0.034445))
_TAU_C_LARGEP = ((1.7339, 0.93202, -0.12745, -0.010368), (2.1945, 0.64695, -0.29198, -0.042377),
                 (2.5893, 0.45168, -0.36529, -0.050074), (3.0387, 0.45452, -0.33666, -0.041921),
                 (3.5049, 0.52098, -0.29158, -0.033468), (3.9489, 0.58933, -0.25359, -0.02721))


def mackinnon_p(t: float, n_vars: int = 1) -> float:
    if not ok(t):
        return NAN
    k = max(1, min(6, n_vars)) - 1
    if t > _TAU_MAX_C[k]:
        return 1.0
    if t < _TAU_MIN_C[k]:
        return 0.0
    c = _TAU_C_SMALLP[k] if t <= _TAU_STAR_C[k] else _TAU_C_LARGEP[k]
    poly, pw = 0.0, 1.0
    for ci in c:
        poly += ci * pw
        pw *= t
    return norm_cdf(poly)


@dataclass
class AdfResult:
    tstat: float = NAN
    pvalue: float = NAN
    lags: int = 0
    nobs: int = 0
    gamma: float = NAN
    ok: bool = False


def _adf_design(y: np.ndarray, dy: np.ndarray, p: int, start: int):
    n = len(y)
    rows = n - start
    if rows <= p + 3:
        return None, None
    t = np.arange(start, n)
    cols = [y[t - 1]] + [dy[t - i] for i in range(1, p + 1)]
    return dy[t], np.column_stack(cols)


def adf_test(y, max_lag: int = -1, auto_lag: bool = True, n_vars: int = 1) -> AdfResult:
    r = AdfResult()
    s = _valid(y)
    n = s.size
    if n < 20:
        return r
    if max_lag < 0:
        max_lag = int(math.floor(12.0 * (n / 100.0) ** 0.25))
    max_lag = max(0, min(max_lag, n // 3 - 2))
    dy = np.empty(n)
    dy[0] = NAN
    dy[1:] = np.diff(s)
    best_lag = max_lag
    if auto_lag and max_lag > 0:
        best_aic = math.inf
        for p in range(max_lag + 1):
            yy, X = _adf_design(s, dy, p, max_lag + 1)
            if yy is None:
                continue
            o = ols(yy, X, True)
            if not o.ok:
                continue
            aic = o.n * math.log(o.rss / o.n) + 2.0 * o.k
            if aic < best_aic:
                best_aic, best_lag = aic, p
    yy, X = _adf_design(s, dy, best_lag, best_lag + 1)
    if yy is None:
        return r
    fit = ols(yy, X, True)
    if not fit.ok:
        return r
    r.gamma = float(fit.coef[1])
    r.tstat = fit.t(1)
    r.pvalue = mackinnon_p(r.tstat, n_vars)
    r.lags = best_lag
    r.nobs = fit.n
    r.ok = ok(r.tstat)
    return r


def engle_granger(log_a, log_b, use_eg_critical_values: bool = True):
    """log(A) = a + b log(B) + e, puis ADF(e) avec valeurs critiques N=2. -> (adf, alpha, beta, residus)."""
    o = ols_simple(log_a, log_b)
    if not o.ok:
        return AdfResult(), NAN, NAN, None
    alpha, beta = float(o.coef[0]), float(o.coef[1])
    resid = o.residuals
    return adf_test(resid, -1, True, 2 if use_eg_critical_values else 1), alpha, beta, resid


# =============================================================================
#  Ornstein-Uhlenbeck discretise (Avellaneda-Lee)
# =============================================================================
@dataclass
class OuFit:
    a: float = NAN
    b: float = NAN
    kappa: float = NAN
    half_life: float = NAN
    mean: float = NAN
    sigma_eq: float = NAN
    s_score: float = NAN
    valid: bool = False


def ou_fit(x) -> OuFit:
    f = OuFit()
    x = np.asarray(x, dtype=float)
    if x.size < 10:
        return f
    o = ols(x[1:], x[:-1], True)
    if not o.ok:
        return f
    f.a, f.b = float(o.coef[0]), float(o.coef[1])
    if not (0 < f.b < 1):
        return f
    f.kappa = -math.log(f.b)
    f.half_life = math.log(2.0) / f.kappa
    f.mean = f.a / (1 - f.b)
    var_z = o.rss / max(1, o.n - 2)
    f.sigma_eq = math.sqrt(var_z / (1 - f.b * f.b))
    if f.sigma_eq > 0:
        f.s_score = (x[-1] - f.mean) / f.sigma_eq
    f.valid = ok(f.s_score)
    return f


# =============================================================================
#  Black-Scholes (dividende continu q)
# =============================================================================
def bs_price(is_call: bool, S, K, T, r, sigma, q=0.0) -> float:
    if T <= 0 or sigma <= 0:
        return max(0.0, S - K if is_call else K - S)
    sq = sigma * math.sqrt(T)
    d1 = (math.log(S / K) + (r - q + 0.5 * sigma * sigma) * T) / sq
    d2 = d1 - sq
    if is_call:
        return S * math.exp(-q * T) * norm_cdf(d1) - K * math.exp(-r * T) * norm_cdf(d2)
    return K * math.exp(-r * T) * norm_cdf(-d2) - S * math.exp(-q * T) * norm_cdf(-d1)


def bs_delta(is_call: bool, S, K, T, r, sigma, q=0.0) -> float:
    if T <= 0 or sigma <= 0:
        return (1.0 if S > K else 0.0) if is_call else (-1.0 if S < K else 0.0)
    d1 = (math.log(S / K) + (r - q + 0.5 * sigma * sigma) * T) / (sigma * math.sqrt(T))
    return math.exp(-q * T) * norm_cdf(d1) if is_call else math.exp(-q * T) * (norm_cdf(d1) - 1.0)


def bs_strike_from_delta(is_call: bool, S, T, r, sigma, delta, q=0.0) -> float:
    if T <= 0 or sigma <= 0:
        return S
    eq = math.exp(q * T)
    target = delta * eq if is_call else 1.0 + delta * eq
    target = clamp(target, 1e-6, 1 - 1e-6)
    d1 = norm_inv(target)
    return S * math.exp(-d1 * sigma * math.sqrt(T) + (r - q + 0.5 * sigma * sigma) * T)


def bs_implied_vol(is_call: bool, price, S, K, T, r, q=0.0) -> float:
    if price <= 0 or T <= 0:
        return NAN
    lo, hi = 1e-4, 5.0
    if price < bs_price(is_call, S, K, T, r, lo, q) or price > bs_price(is_call, S, K, T, r, hi, q):
        return NAN
    for _ in range(100):
        mid = 0.5 * (lo + hi)
        if bs_price(is_call, S, K, T, r, mid, q) > price:
            hi = mid
        else:
            lo = mid
        if hi - lo < 1e-6:
            break
    return 0.5 * (lo + hi)


