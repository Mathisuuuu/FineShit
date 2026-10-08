// =============================================================================
//  NexusCore.cs   (NinjaTrader 8 / NinjaScript - bibliotheque partagee)
//
//  Socle commun des fiches "Nexus" (fil r/algotrading). Aucun type NinjaScript
//  ici : uniquement des outils purs, testables et sans etat global.
//
//    NxMath        statistiques robustes aux NaN, rangs, z-scores, loi normale
//    NxRegression  MCO simple et multiple (erreurs-types)
//    NxAdf         test ADF + p-values MacKinnon (ADF N=1, Engle-Granger N=2..6)
//    NxOu          ajustement Ornstein-Uhlenbeck (AR(1)), s-score, demi-vie
//    NxBlackScholes prix, delta, strike a partir d un delta, vol implicite
//    NxPaths       dossiers  Documents\NinjaTrader 8\Nexus\...
//    NxCsv         lecture/ecriture CSV tolerante (separateur, guillemets, dates)
//    NxJson        mini parseur JSON (aucune dependance externe)
//    NxText        normalisation de titres, Jaccard, hachage
//    NxBarHistory  historique OHLCV par symbole, aligne par jour de bourse
//    NxCalendar    fin de mois / de semaine de bourse, jours ouvres
//    NxTime        conversions fuseau NinjaTrader <-> UTC
//
//  Toutes les dates manipulees par les strategies sont des "jours de bourse"
//  (DateTime.Date) ; les horodatages d actualites sont en UTC.
// =============================================================================

#region Using declarations
using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Linq;
using System.Security.Cryptography;
using System.Text;
#endregion

namespace NinjaTrader.NinjaScript.AddOns.Nexus
{
    /// <summary>Classe d actifs utilisee par les plafonds du module B.</summary>
    public enum NxAssetClass { Action, Etf, Crypto, Forex, Indice, Future, Cfd, Option, Autre }

    /// <summary>Regime de marche commun au module A (HMM) et a la fiche 12 (terciles).</summary>
    public enum NxRegime { Inconnu, Calme, Neutre, Stress }

    // =========================================================================
    //  NxMath
    // =========================================================================
    public static class NxMath
    {
        public const double TradingDaysPerYear = 252.0;
        public const double EulerGamma = 0.5772156649015329;

        public static bool Ok(double x) { return !double.IsNaN(x) && !double.IsInfinity(x); }

        public static double Clamp(double x, double lo, double hi) { return x < lo ? lo : (x > hi ? hi : x); }

        public static double SafeDiv(double a, double b, double fallback = double.NaN)
        {
            if (!Ok(a) || !Ok(b) || b == 0.0) return fallback;
            return a / b;
        }

        public static int Sign(double x) { return x > 0 ? 1 : (x < 0 ? -1 : 0); }

        public static double Mean(IList<double> x) { return x == null ? double.NaN : Mean(x, 0, x.Count); }

        public static double Mean(IList<double> x, int start, int count)
        {
            if (x == null || count <= 0) return double.NaN;
            double s = 0; int n = 0;
            int end = Math.Min(x.Count, start + count);
            for (int i = Math.Max(0, start); i < end; i++)
            {
                double v = x[i];
                if (Ok(v)) { s += v; n++; }
            }
            return n > 0 ? s / n : double.NaN;
        }

        /// <summary>Variance d echantillon (n-1), NaN ignores.</summary>
        public static double Variance(IList<double> x, int start, int count)
        {
            if (x == null || count <= 1) return double.NaN;
            double m = Mean(x, start, count);
            if (!Ok(m)) return double.NaN;
            double s = 0; int n = 0;
            int end = Math.Min(x.Count, start + count);
            for (int i = Math.Max(0, start); i < end; i++)
            {
                double v = x[i];
                if (Ok(v)) { s += (v - m) * (v - m); n++; }
            }
            return n > 1 ? s / (n - 1) : double.NaN;
        }

        public static double Variance(IList<double> x) { return x == null ? double.NaN : Variance(x, 0, x.Count); }

        public static double StdDev(IList<double> x, int start, int count)
        {
            double v = Variance(x, start, count);
            return Ok(v) && v >= 0 ? Math.Sqrt(v) : double.NaN;
        }

        public static double StdDev(IList<double> x) { return x == null ? double.NaN : StdDev(x, 0, x.Count); }

        public static double MeanLast(IList<double> x, int n) { return x == null ? double.NaN : Mean(x, x.Count - n, n); }

        public static double StdLast(IList<double> x, int n) { return x == null ? double.NaN : StdDev(x, x.Count - n, n); }

        public static double Sum(IEnumerable<double> x)
        {
            double s = 0;
            if (x == null) return 0;
            foreach (double v in x) if (Ok(v)) s += v;
            return s;
        }

        public static double Median(IEnumerable<double> x) { return Quantile(x, 0.5); }

        /// <summary>Quantile interpole (type 7, comme numpy/R par defaut).</summary>
        public static double Quantile(IEnumerable<double> x, double q)
        {
            if (x == null) return double.NaN;
            List<double> v = x.Where(Ok).ToList();
            if (v.Count == 0) return double.NaN;
            v.Sort();
            if (v.Count == 1) return v[0];
            q = Clamp(q, 0, 1);
            double h = (v.Count - 1) * q;
            int lo = (int)Math.Floor(h);
            int hi = Math.Min(v.Count - 1, lo + 1);
            return v[lo] + (h - lo) * (v[hi] - v[lo]);
        }

        public static double Covariance(IList<double> a, IList<double> b)
        {
            if (a == null || b == null) return double.NaN;
            int n = Math.Min(a.Count, b.Count);
            double sa = 0, sb = 0; int m = 0;
            for (int i = 0; i < n; i++) if (Ok(a[i]) && Ok(b[i])) { sa += a[i]; sb += b[i]; m++; }
            if (m < 2) return double.NaN;
            double ma = sa / m, mb = sb / m, s = 0;
            for (int i = 0; i < n; i++) if (Ok(a[i]) && Ok(b[i])) s += (a[i] - ma) * (b[i] - mb);
            return s / (m - 1);
        }

        /// <summary>Correlation de Pearson sur les paires valides.</summary>
        public static double Correlation(IList<double> a, IList<double> b)
        {
            if (a == null || b == null) return double.NaN;
            int n = Math.Min(a.Count, b.Count);
            double sa = 0, sb = 0; int m = 0;
            for (int i = 0; i < n; i++) if (Ok(a[i]) && Ok(b[i])) { sa += a[i]; sb += b[i]; m++; }
            if (m < 3) return double.NaN;
            double ma = sa / m, mb = sb / m, sab = 0, saa = 0, sbb = 0;
            for (int i = 0; i < n; i++)
            {
                if (!Ok(a[i]) || !Ok(b[i])) continue;
                double da = a[i] - ma, db = b[i] - mb;
                sab += da * db; saa += da * da; sbb += db * db;
            }
            if (saa <= 0 || sbb <= 0) return double.NaN;
            return sab / Math.Sqrt(saa * sbb);
        }

        /// <summary>Asymetrie d echantillon (biaisee, comme scipy par defaut).</summary>
        public static double Skewness(IList<double> x)
        {
            List<double> v = x == null ? new List<double>() : x.Where(Ok).ToList();
            if (v.Count < 3) return 0.0;
            double m = v.Average(), m2 = 0, m3 = 0;
            foreach (double d in v) { double e = d - m; m2 += e * e; m3 += e * e * e; }
            m2 /= v.Count; m3 /= v.Count;
            return m2 > 0 ? m3 / Math.Pow(m2, 1.5) : 0.0;
        }

        /// <summary>Kurtosis NON excedentaire (loi normale = 3).</summary>
        public static double Kurtosis(IList<double> x)
        {
            List<double> v = x == null ? new List<double>() : x.Where(Ok).ToList();
            if (v.Count < 4) return 3.0;
            double m = v.Average(), m2 = 0, m4 = 0;
            foreach (double d in v) { double e = d - m; m2 += e * e; m4 += e * e * e * e; }
            m2 /= v.Count; m4 /= v.Count;
            return m2 > 0 ? m4 / (m2 * m2) : 3.0;
        }

        /// <summary>z-score transversal ; les NaN restent NaN.</summary>
        public static double[] ZScore(double[] x)
        {
            double[] r = new double[x.Length];
            double m = Mean(x), s = StdDev(x);
            for (int i = 0; i < x.Length; i++)
                r[i] = (Ok(x[i]) && Ok(s) && s > 0) ? (x[i] - m) / s : (Ok(x[i]) ? 0.0 : double.NaN);
            return r;
        }

        /// <summary>Rangs 1..n (moyenne des ex aequo), NaN -> NaN.</summary>
        public static double[] Ranks(double[] x)
        {
            double[] r = new double[x.Length];
            for (int i = 0; i < r.Length; i++) r[i] = double.NaN;
            List<int> idx = Enumerable.Range(0, x.Length).Where(i => Ok(x[i])).OrderBy(i => x[i]).ToList();
            int k = 0;
            while (k < idx.Count)
            {
                int j = k;
                while (j + 1 < idx.Count && x[idx[j + 1]] == x[idx[k]]) j++;
                double avg = (k + j) / 2.0 + 1.0;
                for (int t = k; t <= j; t++) r[idx[t]] = avg;
                k = j + 1;
            }
            return r;
        }

        /// <summary>"Rang centre puis z-score" (fiche 3) : robuste aux valeurs extremes.</summary>
        public static double[] CenteredRankZ(double[] x)
        {
            double[] rk = Ranks(x);
            double m = Mean(rk);
            double[] c = new double[rk.Length];
            for (int i = 0; i < rk.Length; i++) c[i] = Ok(rk[i]) ? rk[i] - m : double.NaN;
            return ZScore(c);
        }

        /// <summary>Fonction de repartition de la loi normale (|erreur| &lt; 1.2e-7).</summary>
        public static double NormCdf(double x)
        {
            if (double.IsNaN(x)) return double.NaN;
            if (x > 40) return 1.0;
            if (x < -40) return 0.0;
            double z = Math.Abs(x) / Math.Sqrt(2.0);
            double t = 1.0 / (1.0 + 0.5 * z);
            double erfc = t * Math.Exp(-z * z - 1.26551223 + t * (1.00002368 + t * (0.37409196 + t * (0.09678418
                        + t * (-0.18628806 + t * (0.27886807 + t * (-1.13520398 + t * (1.48851587
                        + t * (-0.82215223 + t * 0.17087277)))))))));
            return x >= 0 ? 1.0 - 0.5 * erfc : 0.5 * erfc;
        }

        public static double NormPdf(double x) { return Math.Exp(-0.5 * x * x) / Math.Sqrt(2.0 * Math.PI); }

        /// <summary>Quantile de la loi normale (algorithme d Acklam + une iteration de Newton).</summary>
        public static double NormInv(double p)
        {
            if (double.IsNaN(p)) return double.NaN;
            if (p <= 0) return double.NegativeInfinity;
            if (p >= 1) return double.PositiveInfinity;
            double[] a = { -3.969683028665376e+01, 2.209460984245205e+02, -2.759285104469687e+02, 1.383577518672690e+02, -3.066479806614716e+01, 2.506628277459239e+00 };
            double[] b = { -5.447609879822406e+01, 1.615858368580409e+02, -1.556989798598866e+02, 6.680131188771972e+01, -1.328068155288572e+01 };
            double[] c = { -7.784894002430293e-03, -3.223964580411365e-01, -2.400758277161838e+00, -2.549732539343734e+00, 4.374664141464968e+00, 2.938163982698783e+00 };
            double[] d = { 7.784695709041462e-03, 3.224671290700398e-01, 2.445134137142996e+00, 3.754408661907416e+00 };
            const double plow = 0.02425, phigh = 1 - 0.02425;
            double x, q, r;
            if (p < plow)
            {
                q = Math.Sqrt(-2 * Math.Log(p));
                x = (((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1);
            }
            else if (p <= phigh)
            {
                q = p - 0.5; r = q * q;
                x = (((((a[0] * r + a[1]) * r + a[2]) * r + a[3]) * r + a[4]) * r + a[5]) * q / (((((b[0] * r + b[1]) * r + b[2]) * r + b[3]) * r + b[4]) * r + 1);
            }
            else
            {
                q = Math.Sqrt(-2 * Math.Log(1 - p));
                x = -(((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1);
            }
            // Raffinement de Newton (precision ~1e-9).
            double e = NormCdf(x) - p;
            double u = e * Math.Sqrt(2 * Math.PI) * Math.Exp(x * x / 2);
            x = x - u / (1 + x * u / 2);
            return x;
        }

        /// <summary>Volatilite annualisee des n derniers rendements (ecart-type * racine(periodes/an)).</summary>
        public static double AnnualizedVol(IList<double> rets, int n, double periodsPerYear = TradingDaysPerYear)
        {
            double s = StdLast(rets, n);
            return Ok(s) ? s * Math.Sqrt(periodsPerYear) : double.NaN;
        }

        /// <summary>Statistique t de Welch pour comparer deux moyennes.</summary>
        public static double WelchT(IList<double> a, IList<double> b)
        {
            double ma = Mean(a), mb = Mean(b), va = Variance(a), vb = Variance(b);
            int na = a == null ? 0 : a.Count(Ok), nb = b == null ? 0 : b.Count(Ok);
            if (na < 2 || nb < 2 || !Ok(va) || !Ok(vb)) return double.NaN;
            double se = Math.Sqrt(va / na + vb / nb);
            return se > 0 ? (ma - mb) / se : double.NaN;
        }
    }

    // =========================================================================
    //  NxRegression : moindres carres ordinaires
    // =========================================================================
    public class NxOlsResult
    {
        public double[] Coef;       // [constante?, b1, b2, ...]
        public double[] Se;         // erreurs-types
        public double[] Residuals;
        public double Rss;
        public double R2;
        public int N;
        public int K;
        public bool Ok;
        public double T(int i) { return (Se != null && i < Se.Length && Se[i] > 0) ? Coef[i] / Se[i] : double.NaN; }
    }

    public static class NxRegression
    {
        /// <summary>y = a + b x + e. Coef[0]=a, Coef[1]=b.</summary>
        public static NxOlsResult Simple(IList<double> y, IList<double> x)
        {
            int n = Math.Min(y.Count, x.Count);
            double[][] X = new double[n][];
            double[] yy = new double[n];
            for (int i = 0; i < n; i++) { X[i] = new[] { x[i] }; yy[i] = y[i]; }
            return Multi(yy, X, true);
        }

        /// <summary>MCO multiple via equations normales (pivot partiel). Lignes avec NaN ignorees.</summary>
        public static NxOlsResult Multi(double[] y, double[][] X, bool intercept)
        {
            NxOlsResult res = new NxOlsResult();
            int nAll = Math.Min(y.Length, X.Length);
            if (nAll == 0) return res;
            int p = X[0].Length + (intercept ? 1 : 0);
            List<int> rows = new List<int>();
            for (int i = 0; i < nAll; i++)
            {
                bool ok = NxMath.Ok(y[i]) && X[i] != null && X[i].Length == p - (intercept ? 1 : 0);
                if (ok) foreach (double v in X[i]) if (!NxMath.Ok(v)) { ok = false; break; }
                if (ok) rows.Add(i);
            }
            int n = rows.Count;
            res.N = n; res.K = p;
            if (n <= p) return res;

            double[,] xtx = new double[p, p];
            double[] xty = new double[p];
            double[] row = new double[p];
            foreach (int i in rows)
            {
                FillRow(row, X[i], intercept);
                for (int a = 0; a < p; a++)
                {
                    xty[a] += row[a] * y[i];
                    for (int b = 0; b < p; b++) xtx[a, b] += row[a] * row[b];
                }
            }
            double[,] inv = Invert(xtx);
            if (inv == null) return res;
            double[] beta = new double[p];
            for (int a = 0; a < p; a++) { double s = 0; for (int b = 0; b < p; b++) s += inv[a, b] * xty[b]; beta[a] = s; }

            double[] resid = new double[nAll];
            for (int i = 0; i < nAll; i++) resid[i] = double.NaN;
            double rss = 0, ym = 0;
            foreach (int i in rows) ym += y[i];
            ym /= n;
            double tss = 0;
            foreach (int i in rows)
            {
                FillRow(row, X[i], intercept);
                double fit = 0; for (int a = 0; a < p; a++) fit += row[a] * beta[a];
                double e = y[i] - fit;
                resid[i] = e; rss += e * e; tss += (y[i] - ym) * (y[i] - ym);
            }
            double s2 = rss / (n - p);
            double[] se = new double[p];
            for (int a = 0; a < p; a++) se[a] = inv[a, a] * s2 > 0 ? Math.Sqrt(inv[a, a] * s2) : double.NaN;

            res.Coef = beta; res.Se = se; res.Residuals = resid; res.Rss = rss;
            res.R2 = tss > 0 ? 1 - rss / tss : double.NaN;
            res.Ok = true;
            return res;
        }

        private static void FillRow(double[] row, double[] x, bool intercept)
        {
            int k = 0;
            if (intercept) row[k++] = 1.0;
            for (int j = 0; j < x.Length; j++) row[k++] = x[j];
        }

        /// <summary>Inversion Gauss-Jordan avec pivot partiel ; null si singuliere.</summary>
        public static double[,] Invert(double[,] m)
        {
            int n = m.GetLength(0);
            double[,] a = new double[n, 2 * n];
            for (int i = 0; i < n; i++)
            {
                for (int j = 0; j < n; j++) a[i, j] = m[i, j];
                a[i, n + i] = 1.0;
            }
            for (int c = 0; c < n; c++)
            {
                int piv = c; double best = Math.Abs(a[c, c]);
                for (int r = c + 1; r < n; r++) if (Math.Abs(a[r, c]) > best) { best = Math.Abs(a[r, c]); piv = r; }
                if (best < 1e-14) return null;
                if (piv != c) for (int j = 0; j < 2 * n; j++) { double t = a[c, j]; a[c, j] = a[piv, j]; a[piv, j] = t; }
                double d = a[c, c];
                for (int j = 0; j < 2 * n; j++) a[c, j] /= d;
                for (int r = 0; r < n; r++)
                {
                    if (r == c) continue;
                    double f = a[r, c];
                    if (f == 0) continue;
                    for (int j = 0; j < 2 * n; j++) a[r, j] -= f * a[c, j];
                }
            }
            double[,] inv = new double[n, n];
            for (int i = 0; i < n; i++) for (int j = 0; j < n; j++) inv[i, j] = a[i, n + j];
            return inv;
        }
    }

    // =========================================================================
    //  NxAdf : Augmented Dickey-Fuller + p-values MacKinnon (regression "c")
    // =========================================================================
    public class NxAdfResult
    {
        public double TStat = double.NaN;
        public double PValue = double.NaN;
        public int Lags;
        public int NObs;
        public double Gamma = double.NaN;
        public bool Ok;
    }

    public static class NxAdf
    {
        // Tables de surface de reponse MacKinnon (1994/2010), regression avec constante.
        // Index = nombre de variables N (1 = ADF classique, 2 = residu Engle-Granger a 2 series...).
        private static readonly double[] TauMaxC = { 2.74, 0.92, 0.55, 0.61, 0.79, 1.0 };
        private static readonly double[] TauMinC = { -18.83, -18.86, -23.48, -28.07, -25.96, -23.27 };
        private static readonly double[] TauStarC = { -1.61, -2.62, -3.13, -3.47, -3.78, -3.93 };
        private static readonly double[][] TauCSmallP =
        {
            new[] { 2.1659, 1.4412, 0.038269 },
            new[] { 2.92,   1.5012, 0.039796 },
            new[] { 3.4699, 1.4856, 0.03164 },
            new[] { 3.9673, 1.4777, 0.026315 },
            new[] { 4.5509, 1.5338, 0.029545 },
            new[] { 5.1399, 1.6036, 0.034445 },
        };
        private static readonly double[][] TauCLargeP =
        {
            new[] { 1.7339, 0.93202, -0.12745, -0.010368 },
            new[] { 2.1945, 0.64695, -0.29198, -0.042377 },
            new[] { 2.5893, 0.45168, -0.36529, -0.050074 },
            new[] { 3.0387, 0.45452, -0.33666, -0.041921 },
            new[] { 3.5049, 0.52098, -0.29158, -0.033468 },
            new[] { 3.9489, 0.58933, -0.25359, -0.02721 },
        };

        /// <summary>p-value approchee de MacKinnon pour la statistique t (regression "c").</summary>
        public static double MacKinnonP(double t, int nVars)
        {
            if (!NxMath.Ok(t)) return double.NaN;
            int k = Math.Max(1, Math.Min(6, nVars)) - 1;
            if (t > TauMaxC[k]) return 1.0;
            if (t < TauMinC[k]) return 0.0;
            double[] c = t <= TauStarC[k] ? TauCSmallP[k] : TauCLargeP[k];
            double poly = 0, pw = 1;
            for (int i = 0; i < c.Length; i++) { poly += c[i] * pw; pw *= t; }
            return NxMath.NormCdf(poly);
        }

        /// <summary>
        /// Test ADF avec constante. maxLag &lt; 0 => regle de Schwert 12*(n/100)^0.25.
        /// autoLag => choix du retard par AIC sur echantillon commun puis re-estimation.
        /// nVars = 1 pour un ADF classique, 2 pour un residu Engle-Granger a deux series.
        /// </summary>
        public static NxAdfResult Test(IList<double> y, int maxLag = -1, bool autoLag = true, int nVars = 1)
        {
            NxAdfResult r = new NxAdfResult();
            if (y == null) return r;
            List<double> s = y.Where(NxMath.Ok).ToList();
            int n = s.Count;
            if (n < 20) return r;
            if (maxLag < 0) maxLag = (int)Math.Floor(12.0 * Math.Pow(n / 100.0, 0.25));
            maxLag = Math.Max(0, Math.Min(maxLag, n / 3 - 2));

            double[] dy = new double[n];
            dy[0] = double.NaN;
            for (int t = 1; t < n; t++) dy[t] = s[t] - s[t - 1];

            int bestLag = maxLag;
            if (autoLag && maxLag > 0)
            {
                double bestAic = double.PositiveInfinity;
                for (int p = 0; p <= maxLag; p++)
                {
                    NxOlsResult o = Fit(s, dy, p, maxLag + 1);
                    if (!o.Ok) continue;
                    double aic = o.N * Math.Log(o.Rss / o.N) + 2.0 * o.K;
                    if (aic < bestAic) { bestAic = aic; bestLag = p; }
                }
            }
            NxOlsResult fit = Fit(s, dy, bestLag, bestLag + 1);
            if (!fit.Ok) return r;
            r.Gamma = fit.Coef[1];
            r.TStat = fit.T(1);
            r.PValue = MacKinnonP(r.TStat, nVars);
            r.Lags = bestLag;
            r.NObs = fit.N;
            r.Ok = NxMath.Ok(r.TStat);
            return r;
        }

        // dy_t = c + g*y_{t-1} + sum_i phi_i dy_{t-i}, t >= start
        private static NxOlsResult Fit(List<double> y, double[] dy, int p, int start)
        {
            int n = y.Count;
            int rows = n - start;
            if (rows <= p + 3) return new NxOlsResult();
            double[] yy = new double[rows];
            double[][] X = new double[rows][];
            for (int k = 0; k < rows; k++)
            {
                int t = start + k;
                yy[k] = dy[t];
                double[] x = new double[1 + p];
                x[0] = y[t - 1];
                for (int i = 1; i <= p; i++) x[i] = dy[t - i];
                X[k] = x;
            }
            return NxRegression.Multi(yy, X, true);
        }

        /// <summary>Engle-Granger en 2 etapes : log(A) = a + b log(B) + e, puis ADF(e) avec valeurs critiques N=2.</summary>
        public static NxAdfResult EngleGranger(IList<double> logA, IList<double> logB, out double alpha, out double beta,
                                               out double[] residuals, bool useEgCriticalValues = true)
        {
            alpha = double.NaN; beta = double.NaN; residuals = null;
            NxOlsResult o = NxRegression.Simple(logA, logB);
            if (!o.Ok) return new NxAdfResult();
            alpha = o.Coef[0]; beta = o.Coef[1]; residuals = o.Residuals;
            return Test(residuals, -1, true, useEgCriticalValues ? 2 : 1);
        }
    }

    // =========================================================================
    //  NxOu : processus d Ornstein-Uhlenbeck discretise (cadre Avellaneda-Lee)
    // =========================================================================
    public class NxOuFit
    {
        public double A = double.NaN, B = double.NaN;
        public double Kappa = double.NaN;        // vitesse de retour (par barre)
        public double HalfLife = double.NaN;     // en barres
        public double Mean = double.NaN;         // m = a/(1-b)
        public double SigmaEq = double.NaN;      // ecart-type d equilibre
        public double SScore = double.NaN;       // (x_dernier - m)/sigma_eq
        public bool Valid;
    }

    public static class NxOu
    {
        /// <summary>AR(1) x_{t+1} = a + b x_t + z ; valide si 0 &lt; b &lt; 1.</summary>
        public static NxOuFit Fit(IList<double> x)
        {
            NxOuFit f = new NxOuFit();
            if (x == null || x.Count < 10) return f;
            int n = x.Count;
            double[] y = new double[n - 1];
            double[][] X = new double[n - 1][];
            for (int t = 0; t < n - 1; t++) { y[t] = x[t + 1]; X[t] = new[] { x[t] }; }
            NxOlsResult o = NxRegression.Multi(y, X, true);
            if (!o.Ok) return f;
            f.A = o.Coef[0]; f.B = o.Coef[1];
            if (!(f.B > 0 && f.B < 1)) return f;
            f.Kappa = -Math.Log(f.B);
            f.HalfLife = Math.Log(2.0) / f.Kappa;
            f.Mean = f.A / (1 - f.B);
            double varZ = o.Rss / Math.Max(1, o.N - 2);
            f.SigmaEq = Math.Sqrt(varZ / (1 - f.B * f.B));
            if (f.SigmaEq > 0) f.SScore = (x[n - 1] - f.Mean) / f.SigmaEq;
            f.Valid = NxMath.Ok(f.SScore);
            return f;
        }
    }

    // =========================================================================
    //  NxBlackScholes (sous-jacent action, dividende continu q)
    // =========================================================================
    public static class NxBlackScholes
    {
        public static double Price(bool isCall, double S, double K, double T, double r, double sigma, double q = 0.0)
        {
            if (T <= 0 || sigma <= 0) return Math.Max(0.0, isCall ? S - K : K - S);
            double sq = sigma * Math.Sqrt(T);
            double d1 = (Math.Log(S / K) + (r - q + 0.5 * sigma * sigma) * T) / sq;
            double d2 = d1 - sq;
            if (isCall) return S * Math.Exp(-q * T) * NxMath.NormCdf(d1) - K * Math.Exp(-r * T) * NxMath.NormCdf(d2);
            return K * Math.Exp(-r * T) * NxMath.NormCdf(-d2) - S * Math.Exp(-q * T) * NxMath.NormCdf(-d1);
        }

        public static double Delta(bool isCall, double S, double K, double T, double r, double sigma, double q = 0.0)
        {
            if (T <= 0 || sigma <= 0) return isCall ? (S > K ? 1.0 : 0.0) : (S < K ? -1.0 : 0.0);
            double d1 = (Math.Log(S / K) + (r - q + 0.5 * sigma * sigma) * T) / (sigma * Math.Sqrt(T));
            return isCall ? Math.Exp(-q * T) * NxMath.NormCdf(d1) : Math.Exp(-q * T) * (NxMath.NormCdf(d1) - 1.0);
        }

        /// <summary>Strike donnant le delta vise (delta call &gt; 0, delta put &lt; 0).</summary>
        public static double StrikeFromDelta(bool isCall, double S, double T, double r, double sigma, double delta, double q = 0.0)
        {
            if (T <= 0 || sigma <= 0) return S;
            double eq = Math.Exp(q * T);
            double target = isCall ? delta * eq : 1.0 + delta * eq;
            target = NxMath.Clamp(target, 1e-6, 1 - 1e-6);
            double d1 = NxMath.NormInv(target);
            return S * Math.Exp(-d1 * sigma * Math.Sqrt(T) + (r - q + 0.5 * sigma * sigma) * T);
        }

        /// <summary>Volatilite implicite par dichotomie (NaN si hors bornes).</summary>
        public static double ImpliedVol(bool isCall, double price, double S, double K, double T, double r, double q = 0.0)
        {
            if (price <= 0 || T <= 0) return double.NaN;
            double lo = 1e-4, hi = 5.0;
            double plo = Price(isCall, S, K, T, r, lo, q), phi = Price(isCall, S, K, T, r, hi, q);
            if (price < plo || price > phi) return double.NaN;
            for (int i = 0; i < 100; i++)
            {
                double mid = 0.5 * (lo + hi);
                double pm = Price(isCall, S, K, T, r, mid, q);
                if (pm > price) hi = mid; else lo = mid;
                if (hi - lo < 1e-6) break;
            }
            return 0.5 * (lo + hi);
        }
    }

    // =========================================================================
    //  NxPaths : arborescence de travail Nexus
    // =========================================================================
    public static class NxPaths
    {
        private static readonly object sync = new object();

        public static string Root
        {
            get
            {
                string baseDir;
                try { baseDir = NinjaTrader.Core.Globals.UserDataDir; }
                catch { baseDir = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.MyDocuments), "NinjaTrader 8"); }
                return Path.Combine(baseDir, "Nexus");
            }
        }

        public static string Data { get { return Path.Combine(Root, "data"); } }
        public static string Journal { get { return Path.Combine(Root, "journal"); } }
        public static string Reports { get { return Path.Combine(Root, "reports"); } }
        public static string Cache { get { return Path.Combine(Root, "cache"); } }
        public static string Returns { get { return Path.Combine(Root, "returns"); } }
        public static string State { get { return Path.Combine(Root, "state"); } }
        public static string KillSwitchFile { get { return Path.Combine(Root, "KILL_SWITCH"); } }
        public static string KeysFile { get { return Path.Combine(Root, "keys.txt"); } }

        public static void EnsureAll()
        {
            lock (sync)
            {
                foreach (string d in new[] { Root, Data, Journal, Reports, Cache, Returns, State })
                    try { if (!Directory.Exists(d)) Directory.CreateDirectory(d); } catch { }
            }
        }

        /// <summary>Chemin absolu tel quel ; sinon relatif au dossier par defaut.</summary>
        public static string Resolve(string fileOrPath, string defaultDir)
        {
            if (string.IsNullOrWhiteSpace(fileOrPath)) return null;
            string f = fileOrPath.Trim().Trim('"');
            return Path.IsPathRooted(f) ? f : Path.Combine(defaultDir, f);
        }

        public static string SafeFileName(string s)
        {
            if (string.IsNullOrEmpty(s)) return "x";
            StringBuilder sb = new StringBuilder();
            foreach (char c in s) sb.Append(Path.GetInvalidFileNameChars().Contains(c) || c == ' ' ? '_' : c);
            return sb.ToString();
        }
    }

    // =========================================================================
    //  NxCsv
    // =========================================================================
    public static class NxCsv
    {
        private static readonly Dictionary<string, object> fileLocks = new Dictionary<string, object>(StringComparer.OrdinalIgnoreCase);

        private static object LockFor(string path)
        {
            lock (fileLocks)
            {
                object o;
                if (!fileLocks.TryGetValue(path, out o)) { o = new object(); fileLocks[path] = o; }
                return o;
            }
        }

        public static char DetectSeparator(string headerLine)
        {
            if (headerLine == null) return ',';
            int sc = headerLine.Count(c => c == ';'), cc = headerLine.Count(c => c == ','), tc = headerLine.Count(c => c == '\t');
            if (tc > cc && tc > sc) return '\t';
            return sc > cc ? ';' : ',';
        }

        public static string[] SplitLine(string line, char sep)
        {
            List<string> res = new List<string>();
            if (line == null) return res.ToArray();
            StringBuilder cur = new StringBuilder();
            bool inQ = false;
            for (int i = 0; i < line.Length; i++)
            {
                char c = line[i];
                if (inQ)
                {
                    if (c == '"')
                    {
                        if (i + 1 < line.Length && line[i + 1] == '"') { cur.Append('"'); i++; }
                        else inQ = false;
                    }
                    else cur.Append(c);
                }
                else
                {
                    if (c == '"') inQ = true;
                    else if (c == sep) { res.Add(cur.ToString().Trim()); cur.Clear(); }
                    else cur.Append(c);
                }
            }
            res.Add(cur.ToString().Trim());
            return res.ToArray();
        }

        /// <summary>Lit un CSV avec en-tete. Lignes vides et commentaires (#) ignores.</summary>
        public static List<string[]> ReadRows(string path, out string[] header)
        {
            header = new string[0];
            List<string[]> rows = new List<string[]>();
            if (string.IsNullOrEmpty(path) || !File.Exists(path)) return rows;
            string[] lines;
            lock (LockFor(path))
            {
                using (FileStream fs = new FileStream(path, FileMode.Open, FileAccess.Read, FileShare.ReadWrite))
                using (StreamReader sr = new StreamReader(fs, Encoding.UTF8, true))
                    lines = sr.ReadToEnd().Split(new[] { "\r\n", "\n" }, StringSplitOptions.None);
            }
            char sep = ',';
            bool gotHeader = false;
            foreach (string raw in lines)
            {
                string line = raw.TrimEnd();
                if (line.Length == 0 || line.StartsWith("#")) continue;
                if (!gotHeader)
                {
                    sep = DetectSeparator(line);
                    header = SplitLine(line, sep).Select(h => h.Trim().ToLowerInvariant()).ToArray();
                    gotHeader = true;
                    continue;
                }
                rows.Add(SplitLine(line, sep));
            }
            return rows;
        }

        /// <summary>Indice de colonne (insensible a la casse), -1 si absente.</summary>
        public static int Col(string[] header, params string[] names)
        {
            foreach (string n in names)
            {
                string k = n.ToLowerInvariant();
                for (int i = 0; i < header.Length; i++) if (header[i] == k) return i;
            }
            return -1;
        }

        public static string Get(string[] row, int col) { return (col >= 0 && col < row.Length) ? row[col] : ""; }

        public static double ParseDouble(string s)
        {
            if (string.IsNullOrWhiteSpace(s)) return double.NaN;
            s = s.Trim().Replace(" ", "").Replace(" ", "");
            if (s.EndsWith("%")) s = s.Substring(0, s.Length - 1);
            double v;
            if (double.TryParse(s, NumberStyles.Float, CultureInfo.InvariantCulture, out v)) return v;
            if (s.Contains(",") && !s.Contains(".") && double.TryParse(s.Replace(',', '.'), NumberStyles.Float, CultureInfo.InvariantCulture, out v)) return v;
            return double.NaN;
        }

        private static readonly string[] DateFormats =
        {
            "yyyy-MM-ddTHH:mm:ssZ", "yyyy-MM-ddTHH:mm:ss.fffZ", "yyyy-MM-ddTHH:mm:ss", "yyyy-MM-ddTHH:mm:ss.fff",
            "yyyy-MM-ddTHH:mmZ", "yyyy-MM-ddTHH:mm", "yyyy-MM-dd HH:mm:ss", "yyyy-MM-dd HH:mm", "yyyy-MM-dd",
            "yyyyMMdd", "yyyyMMdd HHmmss", "dd/MM/yyyy HH:mm:ss", "dd/MM/yyyy HH:mm", "dd/MM/yyyy", "yyyy/MM/dd", "yyyy-MM",
            "yyyyMM"
        };

        /// <summary>
        /// Date tolerante : ISO 8601 (avec ou sans Z / decalage), formats usuels, ou timestamp unix (s ou ms).
        /// Les valeurs avec Z ou decalage sont renvoyees en UTC ; les autres sont "non specifiees".
        /// </summary>
        public static bool TryParseDate(string s, out DateTime dt)
        {
            dt = DateTime.MinValue;
            if (string.IsNullOrWhiteSpace(s)) return false;
            s = s.Trim();
            double unix;
            if (s.All(ch => char.IsDigit(ch) || ch == '.') && s.Length >= 9 && s.Length != 8 && double.TryParse(s, NumberStyles.Float, CultureInfo.InvariantCulture, out unix))
            {
                if (unix > 1e11) unix /= 1000.0;
                dt = new DateTime(1970, 1, 1, 0, 0, 0, DateTimeKind.Utc).AddSeconds(unix);
                return true;
            }
            DateTimeOffset dto;
            if ((s.EndsWith("Z") || s.Contains("+") || (s.Length > 19 && s.LastIndexOf('-') > 10))
                && DateTimeOffset.TryParse(s, CultureInfo.InvariantCulture, DateTimeStyles.AssumeUniversal, out dto))
            {
                dt = dto.UtcDateTime;
                return true;
            }
            if (DateTime.TryParseExact(s, DateFormats, CultureInfo.InvariantCulture, DateTimeStyles.AllowWhiteSpaces, out dt))
            {
                if (s.EndsWith("Z")) dt = DateTime.SpecifyKind(dt, DateTimeKind.Utc);
                return true;
            }
            return DateTime.TryParse(s, CultureInfo.InvariantCulture, DateTimeStyles.AllowWhiteSpaces, out dt);
        }

        public static string Escape(string s)
        {
            if (s == null) return "";
            bool need = s.IndexOfAny(new[] { ',', ';', '"', '\n', '\r' }) >= 0;
            string v = s.Replace("\r", " ").Replace("\n", " ");
            return need ? "\"" + v.Replace("\"", "\"\"") + "\"" : v;
        }

        public static string F(double v, int decimals = 6)
        {
            if (!NxMath.Ok(v)) return "";
            return v.ToString("F" + decimals, CultureInfo.InvariantCulture);
        }

        public static string D(DateTime d) { return d.ToString("yyyy-MM-dd HH:mm:ss", CultureInfo.InvariantCulture); }

        /// <summary>Ajoute une ligne (cree le fichier avec l en-tete si besoin). Thread-safe par fichier.</summary>
        public static void AppendLine(string path, string header, string line)
        {
            if (string.IsNullOrEmpty(path)) return;
            lock (LockFor(path))
            {
                try
                {
                    string dir = Path.GetDirectoryName(path);
                    if (!string.IsNullOrEmpty(dir) && !Directory.Exists(dir)) Directory.CreateDirectory(dir);
                    bool exists = File.Exists(path);
                    using (StreamWriter sw = new StreamWriter(path, true, new UTF8Encoding(false)))
                    {
                        if (!exists && !string.IsNullOrEmpty(header)) sw.WriteLine(header);
                        sw.WriteLine(line);
                    }
                }
                catch { }
            }
        }

        public static void WriteAll(string path, string content)
        {
            if (string.IsNullOrEmpty(path)) return;
            lock (LockFor(path))
            {
                try
                {
                    string dir = Path.GetDirectoryName(path);
                    if (!string.IsNullOrEmpty(dir) && !Directory.Exists(dir)) Directory.CreateDirectory(dir);
                    File.WriteAllText(path, content, new UTF8Encoding(false));
                }
                catch { }
            }
        }

        public static string ReadAllSafe(string path)
        {
            if (string.IsNullOrEmpty(path) || !File.Exists(path)) return null;
            lock (LockFor(path))
            {
                try { return File.ReadAllText(path); } catch { return null; }
            }
        }
    }

    // =========================================================================
    //  NxJson : parseur minimal (objets -> Dictionary, tableaux -> List)
    // =========================================================================
    public static class NxJson
    {
        public static object Parse(string s)
        {
            if (s == null) throw new FormatException("JSON nul");
            int i = 0;
            object v = ParseValue(s, ref i);
            SkipWs(s, ref i);
            return v;
        }

        public static bool TryParse(string s, out object v)
        {
            try { v = Parse(s); return true; } catch { v = null; return false; }
        }

        private static void SkipWs(string s, ref int i) { while (i < s.Length && char.IsWhiteSpace(s[i])) i++; }

        private static object ParseValue(string s, ref int i)
        {
            SkipWs(s, ref i);
            if (i >= s.Length) throw new FormatException("JSON tronque");
            char c = s[i];
            if (c == '{') return ParseObject(s, ref i);
            if (c == '[') return ParseArray(s, ref i);
            if (c == '"') return ParseString(s, ref i);
            if (c == 't' && string.CompareOrdinal(s, i, "true", 0, 4) == 0) { i += 4; return true; }
            if (c == 'f' && string.CompareOrdinal(s, i, "false", 0, 5) == 0) { i += 5; return false; }
            if (c == 'n' && string.CompareOrdinal(s, i, "null", 0, 4) == 0) { i += 4; return null; }
            return ParseNumber(s, ref i);
        }

        private static Dictionary<string, object> ParseObject(string s, ref int i)
        {
            Dictionary<string, object> d = new Dictionary<string, object>(StringComparer.Ordinal);
            i++;
            SkipWs(s, ref i);
            if (i < s.Length && s[i] == '}') { i++; return d; }
            while (true)
            {
                SkipWs(s, ref i);
                string k = ParseString(s, ref i);
                SkipWs(s, ref i);
                if (i >= s.Length || s[i] != ':') throw new FormatException("':' attendu");
                i++;
                d[k] = ParseValue(s, ref i);
                SkipWs(s, ref i);
                if (i >= s.Length) throw new FormatException("objet non termine");
                if (s[i] == ',') { i++; continue; }
                if (s[i] == '}') { i++; return d; }
                throw new FormatException("',' ou '}' attendu");
            }
        }

        private static List<object> ParseArray(string s, ref int i)
        {
            List<object> l = new List<object>();
            i++;
            SkipWs(s, ref i);
            if (i < s.Length && s[i] == ']') { i++; return l; }
            while (true)
            {
                l.Add(ParseValue(s, ref i));
                SkipWs(s, ref i);
                if (i >= s.Length) throw new FormatException("tableau non termine");
                if (s[i] == ',') { i++; continue; }
                if (s[i] == ']') { i++; return l; }
                throw new FormatException("',' ou ']' attendu");
            }
        }

        private static string ParseString(string s, ref int i)
        {
            if (s[i] != '"') throw new FormatException("chaine attendue");
            i++;
            StringBuilder sb = new StringBuilder();
            while (i < s.Length)
            {
                char c = s[i++];
                if (c == '"') return sb.ToString();
                if (c == '\\')
                {
                    if (i >= s.Length) break;
                    char e = s[i++];
                    switch (e)
                    {
                        case '"': sb.Append('"'); break;
                        case '\\': sb.Append('\\'); break;
                        case '/': sb.Append('/'); break;
                        case 'b': sb.Append('\b'); break;
                        case 'f': sb.Append('\f'); break;
                        case 'n': sb.Append('\n'); break;
                        case 'r': sb.Append('\r'); break;
                        case 't': sb.Append('\t'); break;
                        case 'u':
                            if (i + 4 > s.Length) throw new FormatException("\\u tronque");
                            sb.Append((char)Convert.ToInt32(s.Substring(i, 4), 16));
                            i += 4;
                            break;
                        default: sb.Append(e); break;
                    }
                }
                else sb.Append(c);
            }
            throw new FormatException("chaine non terminee");
        }

        private static object ParseNumber(string s, ref int i)
        {
            int st = i;
            while (i < s.Length && "+-0123456789.eE".IndexOf(s[i]) >= 0) i++;
            if (i == st) throw new FormatException("valeur JSON invalide a la position " + st);
            double v;
            if (!double.TryParse(s.Substring(st, i - st), NumberStyles.Float, CultureInfo.InvariantCulture, out v))
                throw new FormatException("nombre invalide");
            return v;
        }

        /// <summary>Acces par chemin : "content[0].text", "choices[0].message.content".</summary>
        public static object At(object root, string path)
        {
            object cur = root;
            if (string.IsNullOrEmpty(path)) return cur;
            foreach (string part in path.Split('.'))
            {
                string name = part;
                List<int> idx = new List<int>();
                int b = part.IndexOf('[');
                if (b >= 0)
                {
                    name = part.Substring(0, b);
                    string rest = part.Substring(b);
                    foreach (string seg in rest.Split(new[] { '[', ']' }, StringSplitOptions.RemoveEmptyEntries))
                    {
                        int k;
                        if (int.TryParse(seg, out k)) idx.Add(k);
                    }
                }
                if (name.Length > 0)
                {
                    Dictionary<string, object> d = cur as Dictionary<string, object>;
                    if (d == null || !d.TryGetValue(name, out cur)) return null;
                }
                foreach (int k in idx)
                {
                    List<object> l = cur as List<object>;
                    if (l == null || k < 0 || k >= l.Count) return null;
                    cur = l[k];
                }
            }
            return cur;
        }

        public static string Str(object o) { return o == null ? null : (o is string ? (string)o : Convert.ToString(o, CultureInfo.InvariantCulture)); }

        public static double Num(object o)
        {
            if (o == null) return double.NaN;
            if (o is double) return (double)o;
            if (o is bool) return (bool)o ? 1 : 0;
            return NxCsv.ParseDouble(Convert.ToString(o, CultureInfo.InvariantCulture));
        }

        public static bool Bool(object o, bool fallback = false)
        {
            if (o is bool) return (bool)o;
            string s = Str(o);
            if (s == null) return fallback;
            s = s.Trim().ToLowerInvariant();
            if (s == "true" || s == "yes" || s == "oui" || s == "1") return true;
            if (s == "false" || s == "no" || s == "non" || s == "0") return false;
            return fallback;
        }

        public static string Escape(string s)
        {
            if (s == null) return "";
            StringBuilder sb = new StringBuilder(s.Length + 8);
            foreach (char c in s)
            {
                switch (c)
                {
                    case '"': sb.Append("\\\""); break;
                    case '\\': sb.Append("\\\\"); break;
                    case '\n': sb.Append("\\n"); break;
                    case '\r': sb.Append("\\r"); break;
                    case '\t': sb.Append("\\t"); break;
                    case '\b': sb.Append("\\b"); break;
                    case '\f': sb.Append("\\f"); break;
                    default:
                        if (c < 0x20) sb.Append("\\u").Append(((int)c).ToString("x4"));
                        else sb.Append(c);
                        break;
                }
            }
            return sb.ToString();
        }

        public static string Q(string s) { return "\"" + Escape(s) + "\""; }

        public static string N(double v) { return NxMath.Ok(v) ? v.ToString("R", CultureInfo.InvariantCulture) : "null"; }

        /// <summary>Premier objet {...} equilibre d un texte (les LLM entourent parfois le JSON de prose ou de ```).</summary>
        public static string ExtractFirstObject(string text)
        {
            if (string.IsNullOrEmpty(text)) return null;
            int start = text.IndexOf('{');
            while (start >= 0)
            {
                int depth = 0; bool inStr = false;
                for (int i = start; i < text.Length; i++)
                {
                    char c = text[i];
                    if (inStr)
                    {
                        if (c == '\\') { i++; continue; }
                        if (c == '"') inStr = false;
                        continue;
                    }
                    if (c == '"') inStr = true;
                    else if (c == '{') depth++;
                    else if (c == '}')
                    {
                        depth--;
                        if (depth == 0)
                        {
                            string cand = text.Substring(start, i - start + 1);
                            object o;
                            if (TryParse(cand, out o)) return cand;
                            break;
                        }
                    }
                }
                start = text.IndexOf('{', start + 1);
            }
            return null;
        }
    }

    // =========================================================================
    //  NxText
    // =========================================================================
    public static class NxText
    {
        private static readonly HashSet<string> Stop = new HashSet<string>(StringComparer.Ordinal)
        { "the", "a", "an", "of", "to", "in", "on", "for", "and", "or", "is", "are", "at", "by", "with", "as", "its", "it", "from", "after", "le", "la", "les", "de", "des", "du", "et" };

        public static string Normalize(string s)
        {
            if (string.IsNullOrEmpty(s)) return "";
            StringBuilder sb = new StringBuilder(s.Length);
            foreach (char c in s.ToLowerInvariant()) sb.Append(char.IsLetterOrDigit(c) ? c : ' ');
            return string.Join(" ", sb.ToString().Split(new[] { ' ' }, StringSplitOptions.RemoveEmptyEntries));
        }

        public static HashSet<string> Tokens(string s)
        {
            return new HashSet<string>(Normalize(s).Split(' ').Where(t => t.Length > 1 && !Stop.Contains(t)), StringComparer.Ordinal);
        }

        public static double Jaccard(HashSet<string> a, HashSet<string> b)
        {
            if (a == null || b == null || a.Count == 0 || b.Count == 0) return 0.0;
            int inter = a.Count(b.Contains);
            int uni = a.Count + b.Count - inter;
            return uni > 0 ? (double)inter / uni : 0.0;
        }

        public static string Hash(string s)
        {
            using (SHA1 sha = SHA1.Create())
            {
                byte[] h = sha.ComputeHash(Encoding.UTF8.GetBytes(s ?? ""));
                StringBuilder sb = new StringBuilder();
                for (int i = 0; i < 10; i++) sb.Append(h[i].ToString("x2"));
                return sb.ToString();
            }
        }

        public static string OneLine(string s, int maxLen = 300)
        {
            if (s == null) return "";
            string v = s.Replace("\r", " ").Replace("\n", " ").Trim();
            return v.Length > maxLen ? v.Substring(0, maxLen) : v;
        }

        public static List<string> SplitList(string s)
        {
            if (string.IsNullOrWhiteSpace(s)) return new List<string>();
            return s.Split(new[] { ',', ';', '\n', '\r', '\t', '|' }, StringSplitOptions.RemoveEmptyEntries)
                    .Select(x => x.Trim()).Where(x => x.Length > 0)
                    .Distinct(StringComparer.OrdinalIgnoreCase).ToList();
        }

        /// <summary>"AAPL=Apple;MSFT=Microsoft" ou "AAPL:XLK,MSFT:XLK" -> dictionnaire (cle en majuscules).</summary>
        public static Dictionary<string, string> ParseMap(string s)
        {
            Dictionary<string, string> d = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);
            foreach (string item in SplitList(s))
            {
                int k = item.IndexOf('=');
                if (k < 0) k = item.IndexOf(':');
                if (k <= 0) continue;
                d[item.Substring(0, k).Trim()] = item.Substring(k + 1).Trim();
            }
            return d;
        }
    }

    // =========================================================================
    //  NxBarHistory : historique OHLCV d un symbole (independant de MaximumBarsLookBack)
    // =========================================================================
    public class NxBarHistory
    {
        public readonly string Symbol;
        public readonly List<DateTime> Dates = new List<DateTime>();     // jour de bourse
        public readonly List<DateTime> Times = new List<DateTime>();     // horodatage de la barre
        public readonly List<double> Open = new List<double>();
        public readonly List<double> High = new List<double>();
        public readonly List<double> Low = new List<double>();
        public readonly List<double> Close = new List<double>();
        public readonly List<double> Volume = new List<double>();
        public readonly List<double> AtrSeries = new List<double>();
        private readonly Dictionary<DateTime, int> dateIndex = new Dictionary<DateTime, int>();
        private readonly int atrPeriod;
        private double atr = double.NaN;
        private double trSum;
        private int trCount;

        public NxBarHistory(string symbol, int atrPeriod = 14)
        {
            Symbol = symbol;
            this.atrPeriod = Math.Max(1, atrPeriod);
        }

        public int Count { get { return Close.Count; } }
        public double LastClose { get { return Count > 0 ? Close[Count - 1] : double.NaN; } }
        public DateTime LastDate { get { return Count > 0 ? Dates[Count - 1] : DateTime.MinValue; } }
        public DateTime LastTime { get { return Count > 0 ? Times[Count - 1] : DateTime.MinValue; } }
        /// <summary>ATR de Wilder courant (NaN pendant le chauffage).</summary>
        public double Atr { get { return atr; } }

        public void Add(DateTime day, DateTime time, double o, double h, double l, double c, double v)
        {
            if (!NxMath.Ok(c) || c <= 0) return;
            if (!NxMath.Ok(o) || o <= 0) o = c;
            if (!NxMath.Ok(h) || h < Math.Max(o, c)) h = Math.Max(o, c);
            if (!NxMath.Ok(l) || l <= 0 || l > Math.Min(o, c)) l = Math.Min(o, c);
            double prev = Count > 0 ? Close[Count - 1] : double.NaN;
            double tr = NxMath.Ok(prev) ? Math.Max(h - l, Math.Max(Math.Abs(h - prev), Math.Abs(l - prev))) : h - l;
            if (trCount < atrPeriod)
            {
                trSum += tr; trCount++;
                if (trCount == atrPeriod) atr = trSum / atrPeriod;
            }
            else atr = (atr * (atrPeriod - 1) + tr) / atrPeriod;

            Dates.Add(day.Date); Times.Add(time); Open.Add(o); High.Add(h); Low.Add(l); Close.Add(c);
            Volume.Add(NxMath.Ok(v) ? v : 0.0); AtrSeries.Add(atr);
            dateIndex[day.Date] = Count - 1;
        }

        /// <summary>Cloture il y a k barres (k=0 : derniere).</summary>
        public double CloseAgo(int k) { int i = Count - 1 - k; return (i >= 0 && i < Count) ? Close[i] : double.NaN; }

        /// <summary>Rendement P(t-skip)/P(t-lookback) - 1 ; "12-1" = ReturnOver(252, 21).</summary>
        public double ReturnOver(int lookback, int skip)
        {
            double pEnd = CloseAgo(skip), pStart = CloseAgo(lookback);
            return (NxMath.Ok(pEnd) && NxMath.Ok(pStart) && pStart > 0) ? pEnd / pStart - 1.0 : double.NaN;
        }

        public double LogReturnAt(int i) { return (i >= 1 && i < Count && Close[i - 1] > 0) ? Math.Log(Close[i] / Close[i - 1]) : double.NaN; }

        public double SimpleReturnAt(int i) { return (i >= 1 && i < Count && Close[i - 1] > 0) ? Close[i] / Close[i - 1] - 1.0 : double.NaN; }

        /// <summary>Les n derniers rendements (du plus ancien au plus recent).</summary>
        public List<double> Returns(int n, bool log = true)
        {
            List<double> r = new List<double>(Math.Max(0, n));
            for (int i = Math.Max(1, Count - n); i < Count; i++) r.Add(log ? LogReturnAt(i) : SimpleReturnAt(i));
            return r;
        }

        /// <summary>Volatilite realisee annualisee sur n rendements log.</summary>
        public double RealizedVol(int n, double periodsPerYear = NxMath.TradingDaysPerYear)
        {
            if (Count < n + 1) return double.NaN;
            return NxMath.AnnualizedVol(Returns(n), n, periodsPerYear);
        }

        /// <summary>Variance realisee (somme des carres des rendements log) sur n jours.</summary>
        public double RealizedVariance(int n)
        {
            if (Count < n + 1) return double.NaN;
            double s = 0;
            foreach (double r in Returns(n)) if (NxMath.Ok(r)) s += r * r;
            return s;
        }

        public double Sma(int n)
        {
            if (Count < n || n <= 0) return double.NaN;
            return NxMath.Mean(Close, Count - n, n);
        }

        public double SmaAt(int n, int endIndexInclusive)
        {
            if (endIndexInclusive + 1 < n || n <= 0) return double.NaN;
            return NxMath.Mean(Close, endIndexInclusive - n + 1, n);
        }

        /// <summary>Volume moyen en devise (prix * volume) sur n barres.</summary>
        public double AvgDollarVolume(int n)
        {
            if (Count < n || n <= 0) return double.NaN;
            double s = 0;
            for (int i = Count - n; i < Count; i++) s += Close[i] * Volume[i];
            return s / n;
        }

        public int IndexOf(DateTime day) { int i; return dateIndex.TryGetValue(day.Date, out i) ? i : -1; }

        public double CloseOn(DateTime day) { int i = IndexOf(day); return i >= 0 ? Close[i] : double.NaN; }

        /// <summary>Indice de la derniere barre dont la date est &lt;= day (recherche binaire), -1 sinon.</summary>
        public int IndexOnOrBefore(DateTime day)
        {
            int lo = 0, hi = Count - 1, ans = -1;
            DateTime d = day.Date;
            while (lo <= hi)
            {
                int mid = (lo + hi) / 2;
                if (Dates[mid] <= d) { ans = mid; lo = mid + 1; } else hi = mid - 1;
            }
            return ans;
        }

        public double CloseOnOrBefore(DateTime day) { int i = IndexOnOrBefore(day); return i >= 0 ? Close[i] : double.NaN; }

        /// <summary>
        /// Rendements alignes par jour de bourse entre deux historiques (dates communes uniquement),
        /// sur au plus n intervalles, du plus ancien au plus recent.
        /// </summary>
        public static void AlignedReturns(NxBarHistory a, NxBarHistory b, int n, out List<double> ra, out List<double> rb, bool log = true)
        {
            ra = new List<double>(); rb = new List<double>();
            if (a == null || b == null || a.Count < 2 || b.Count < 2) return;
            List<int> ia = new List<int>(), ib = new List<int>();
            for (int i = a.Count - 1; i >= 0 && ia.Count < n + 1; i--)
            {
                int j = b.IndexOf(a.Dates[i]);
                if (j >= 0) { ia.Add(i); ib.Add(j); }
            }
            ia.Reverse(); ib.Reverse();
            for (int k = 1; k < ia.Count; k++)
            {
                double pa0 = a.Close[ia[k - 1]], pa1 = a.Close[ia[k]], pb0 = b.Close[ib[k - 1]], pb1 = b.Close[ib[k]];
                if (pa0 <= 0 || pb0 <= 0) continue;
                ra.Add(log ? Math.Log(pa1 / pa0) : pa1 / pa0 - 1);
                rb.Add(log ? Math.Log(pb1 / pb0) : pb1 / pb0 - 1);
            }
        }

        /// <summary>Correlation des rendements journaliers alignes sur n jours.</summary>
        public static double ReturnCorrelation(NxBarHistory a, NxBarHistory b, int n)
        {
            List<double> ra, rb;
            AlignedReturns(a, b, n, out ra, out rb);
            return ra.Count >= 10 ? NxMath.Correlation(ra, rb) : double.NaN;
        }
    }

    // =========================================================================
    //  NxCalendar
    // =========================================================================
    public static class NxCalendar
    {
        /// <summary>Prochain jour ouvre (week-ends et jours feries exclus, sauf marche 7j/7).</summary>
        public static DateTime NextBusinessDay(DateTime d, ICollection<DateTime> holidays, bool sevenDays = false)
        {
            DateTime n = d.Date.AddDays(1);
            for (int guard = 0; guard < 15; guard++)
            {
                bool weekend = !sevenDays && (n.DayOfWeek == DayOfWeek.Saturday || n.DayOfWeek == DayOfWeek.Sunday);
                bool hol = holidays != null && holidays.Contains(n);
                if (!weekend && !hol) return n;
                n = n.AddDays(1);
            }
            return n;
        }

        public static bool IsLastTradingDayOfMonth(DateTime d, ICollection<DateTime> holidays, bool sevenDays = false)
        {
            return NextBusinessDay(d, holidays, sevenDays).Month != d.Month;
        }

        public static DateTime WeekStart(DateTime d)
        {
            int diff = ((int)d.DayOfWeek + 6) % 7;   // lundi = 0
            return d.Date.AddDays(-diff);
        }

        public static bool IsLastTradingDayOfWeek(DateTime d, ICollection<DateTime> holidays, bool sevenDays = false)
        {
            return WeekStart(NextBusinessDay(d, holidays, sevenDays)) != WeekStart(d);
        }

        public static int MonthKey(DateTime d) { return d.Year * 12 + d.Month; }

        /// <summary>Troisieme vendredi du mois (echeance mensuelle standard des options US).</summary>
        public static DateTime ThirdFriday(int year, int month)
        {
            DateTime first = new DateTime(year, month, 1);
            int offset = ((int)DayOfWeek.Friday - (int)first.DayOfWeek + 7) % 7;
            return first.AddDays(offset + 14);
        }
    }

    // =========================================================================
    //  NxTime : fuseau NinjaTrader <-> UTC
    // =========================================================================
    public static class NxTime
    {
        public static TimeZoneInfo NtZone()
        {
            try
            {
                TimeZoneInfo tz = NinjaTrader.Core.Globals.GeneralOptions.TimeZoneInfo;
                return tz ?? TimeZoneInfo.Local;
            }
            catch { return TimeZoneInfo.Local; }
        }

        public static TimeZoneInfo Find(string id, TimeZoneInfo fallback)
        {
            if (string.IsNullOrWhiteSpace(id)) return fallback;
            try { return TimeZoneInfo.FindSystemTimeZoneById(id.Trim()); } catch { return fallback; }
        }

        public static TimeZoneInfo Eastern { get { return Find("Eastern Standard Time", TimeZoneInfo.Local); } }

        public static DateTime ToUtc(DateTime local, TimeZoneInfo zone)
        {
            if (local.Kind == DateTimeKind.Utc) return local;
            DateTime u = DateTime.SpecifyKind(local, DateTimeKind.Unspecified);
            try { return TimeZoneInfo.ConvertTimeToUtc(u, zone ?? TimeZoneInfo.Local); }
            catch (ArgumentException) { return TimeZoneInfo.ConvertTimeToUtc(u.AddHours(1), zone ?? TimeZoneInfo.Local); }
        }

        public static DateTime FromUtc(DateTime utc, TimeZoneInfo zone)
        {
            DateTime u = DateTime.SpecifyKind(utc, DateTimeKind.Utc);
            return TimeZoneInfo.ConvertTimeFromUtc(u, zone ?? TimeZoneInfo.Local);
        }

        public static DateTime NtToUtc(DateTime ntLocal) { return ToUtc(ntLocal, NtZone()); }

        public static DateTime UtcToNt(DateTime utc) { return FromUtc(utc, NtZone()); }

        /// <summary>"0930" ou "9:30" -> TimeSpan.</summary>
        public static TimeSpan ParseHhmm(string s, TimeSpan fallback)
        {
            if (string.IsNullOrWhiteSpace(s)) return fallback;
            string v = s.Trim().Replace(":", "").Replace("h", "");
            int x;
            if (!int.TryParse(v, out x)) return fallback;
            int h = x / 100, m = x % 100;
            if (h < 0 || h > 23 || m < 0 || m > 59) return fallback;
            return new TimeSpan(h, m, 0);
        }
    }
}
