// =============================================================================
//  NexusModuleA_RegimeHmm.cs   (NinjaTrader 8 / NinjaScript - bibliotheque)
//
//  MODULE A - Detection de regime par HMM gaussien a 3 etats (barometre SPY)
//  + l alternative de la FICHE 12 (terciles de volatilite realisee).
//
//  Corrections appliquees par rapport a Nexus [Fil] (colonne "Correction" de la fiche) :
//    - covariance DIAGONALE (au lieu de "full")             -> 3 etats x 3 variables :
//      9 moyennes + 9 variances + 6 transitions + 2 initiales = 26 parametres
//    - variables STANDARDISEES (z-score sur la fenetre d estimation)
//    - fenetre 500-750 jours (defaut 600) au lieu de 100
//    - probabilites FILTREES (passe avant seule, aucune information future),
//      lissees par moyenne exponentielle 5 jours, plafonnees a 0.95
//    - apres chaque re-estimation, etats tries par volatilite moyenne :
//      Calme / Neutre / Stress
//    - re-estimation hebdomadaire, 10 initialisations aleatoires, meilleure
//      vraisemblance conservee (graine fixe -> backtests reproductibles)
//
//  BIAIS D ANTICIPATION : le detecteur ne lit JAMAIS une probabilite lissee
//  (avant-arriere). Entre deux re-estimations, la probabilite du jour est
//  obtenue par une seule etape de la recursion avant, avec les parametres et
//  la standardisation figes a la derniere estimation (donc connus a la date).
// =============================================================================

#region Using declarations
using System;
using System.Collections.Generic;
using System.Linq;
#endregion

namespace NinjaTrader.NinjaScript.AddOns.Nexus
{
    // =========================================================================
    //  HMM gaussien a covariance diagonale (Baum-Welch avec normalisation)
    // =========================================================================
    public class NxGaussianHmm
    {
        public int K;                 // nombre d etats
        public int D;                 // dimension des observations
        public double[] Pi;           // probabilites initiales
        public double[,] A;           // transitions A[i,j] = P(s_t=j | s_{t-1}=i)
        public double[,] Mu;          // moyennes [k,d]
        public double[,] Var;         // variances [k,d] (diagonale)
        public double LogLikelihood = double.NegativeInfinity;
        public int Iterations;
        public const double VarFloor = 1e-3;

        public NxGaussianHmm(int k, int d)
        {
            K = k; D = d;
            Pi = new double[k];
            A = new double[k, k];
            Mu = new double[k, d];
            Var = new double[k, d];
        }

        public NxGaussianHmm Clone()
        {
            NxGaussianHmm h = new NxGaussianHmm(K, D);
            Array.Copy(Pi, h.Pi, K);
            Array.Copy(A, h.A, A.Length);
            Array.Copy(Mu, h.Mu, Mu.Length);
            Array.Copy(Var, h.Var, Var.Length);
            h.LogLikelihood = LogLikelihood;
            h.Iterations = Iterations;
            return h;
        }

        public double LogEmission(int k, double[] x)
        {
            double s = 0;
            for (int d = 0; d < D; d++)
            {
                double v = Math.Max(Var[k, d], VarFloor);
                double e = x[d] - Mu[k, d];
                s += -0.5 * (Math.Log(2 * Math.PI * v) + e * e / v);
            }
            return s;
        }

        private double[] Emissions(double[] x, out double shift)
        {
            double[] le = new double[K];
            double mx = double.NegativeInfinity;
            for (int k = 0; k < K; k++) { le[k] = LogEmission(k, x); if (le[k] > mx) mx = le[k]; }
            double[] b = new double[K];
            for (int k = 0; k < K; k++) b[k] = Math.Exp(le[k] - mx);
            shift = mx;
            return b;
        }

        /// <summary>Une etape de filtrage : alpha_t proportionnel a (alpha_{t-1} A) * b(x_t). prev null => Pi.</summary>
        public double[] ForwardStep(double[] prev, double[] x)
        {
            double shift;
            double[] b = Emissions(x, out shift);
            double[] a = new double[K];
            double s = 0;
            for (int j = 0; j < K; j++)
            {
                double pred = 0;
                if (prev == null) pred = Pi[j];
                else for (int i = 0; i < K; i++) pred += prev[i] * A[i, j];
                a[j] = pred * b[j];
                s += a[j];
            }
            if (!(s > 0) || double.IsNaN(s))
            {
                for (int j = 0; j < K; j++) a[j] = 1.0 / K;
                return a;
            }
            for (int j = 0; j < K; j++) a[j] /= s;
            return a;
        }

        /// <summary>Probabilites filtrees du DERNIER point (passe avant seule).</summary>
        public double[] FilterLast(double[][] X)
        {
            double[] a = null;
            for (int t = 0; t < X.Length; t++) a = ForwardStep(a, X[t]);
            return a;
        }

        /// <summary>Log-vraisemblance par passe avant normalisee.</summary>
        public double Score(double[][] X)
        {
            double ll = 0;
            double[] prev = null;
            for (int t = 0; t < X.Length; t++)
            {
                double shift;
                double[] b = Emissions(X[t], out shift);
                double s = 0;
                double[] a = new double[K];
                for (int j = 0; j < K; j++)
                {
                    double pred = 0;
                    if (prev == null) pred = Pi[j];
                    else for (int i = 0; i < K; i++) pred += prev[i] * A[i, j];
                    a[j] = pred * b[j];
                    s += a[j];
                }
                if (!(s > 0)) return double.NegativeInfinity;
                for (int j = 0; j < K; j++) a[j] /= s;
                ll += Math.Log(s) + shift;
                prev = a;
            }
            return ll;
        }

        /// <summary>Estimation Baum-Welch a partir de plusieurs initialisations aleatoires.</summary>
        public static NxGaussianHmm Fit(double[][] X, int k, int nInit, int maxIter, double tol, int seed)
        {
            if (X == null || X.Length < 10 * k) return null;
            int d = X[0].Length;
            NxGaussianHmm best = null;
            Random rng = new Random(seed);
            for (int init = 0; init < Math.Max(1, nInit); init++)
            {
                NxGaussianHmm h = new NxGaussianHmm(k, d);
                h.RandomInit(X, rng);
                h.BaumWelch(X, maxIter, tol);
                if (NxMath.Ok(h.LogLikelihood) && (best == null || h.LogLikelihood > best.LogLikelihood)) best = h;
            }
            return best;
        }

        private void RandomInit(double[][] X, Random rng)
        {
            int T = X.Length;
            // Moyennes : points de donnees tires au hasard ; variances : variance globale.
            double[] gm = new double[D], gv = new double[D];
            for (int d = 0; d < D; d++)
            {
                double s = 0; for (int t = 0; t < T; t++) s += X[t][d];
                gm[d] = s / T;
                double v = 0; for (int t = 0; t < T; t++) v += (X[t][d] - gm[d]) * (X[t][d] - gm[d]);
                gv[d] = Math.Max(v / T, VarFloor);
            }
            for (int k = 0; k < K; k++)
            {
                double[] p = X[rng.Next(T)];
                for (int d = 0; d < D; d++)
                {
                    Mu[k, d] = p[d] + 0.1 * (rng.NextDouble() - 0.5) * Math.Sqrt(gv[d]);
                    Var[k, d] = gv[d] * (0.5 + rng.NextDouble());
                }
                Pi[k] = 1.0 / K;
                double rowSum = 0;
                for (int j = 0; j < K; j++)
                {
                    A[k, j] = (j == k ? 0.90 : 0.10 / (K - 1)) * (0.8 + 0.4 * rng.NextDouble());
                    rowSum += A[k, j];
                }
                for (int j = 0; j < K; j++) A[k, j] /= rowSum;
            }
        }

        private void BaumWelch(double[][] X, int maxIter, double tol)
        {
            int T = X.Length;
            double[,] alpha = new double[T, K], beta = new double[T, K], b = new double[T, K];
            double[] c = new double[T];
            double prevLl = double.NegativeInfinity;
            for (int it = 0; it < maxIter; it++)
            {
                double ll = 0;
                for (int t = 0; t < T; t++)
                {
                    double shift;
                    double[] bt = Emissions(X[t], out shift);
                    for (int k = 0; k < K; k++) b[t, k] = bt[k];
                    ll += shift;
                }
                // Passe avant normalisee.
                for (int t = 0; t < T; t++)
                {
                    double s = 0;
                    for (int j = 0; j < K; j++)
                    {
                        double pred = 0;
                        if (t == 0) pred = Pi[j];
                        else for (int i = 0; i < K; i++) pred += alpha[t - 1, i] * A[i, j];
                        alpha[t, j] = pred * b[t, j];
                        s += alpha[t, j];
                    }
                    if (!(s > 0)) { LogLikelihood = double.NegativeInfinity; return; }
                    c[t] = s;
                    for (int j = 0; j < K; j++) alpha[t, j] /= s;
                    ll += Math.Log(s);
                }
                // Passe arriere (meme normalisation).
                for (int k = 0; k < K; k++) beta[T - 1, k] = 1.0;
                for (int t = T - 2; t >= 0; t--)
                {
                    for (int i = 0; i < K; i++)
                    {
                        double s = 0;
                        for (int j = 0; j < K; j++) s += A[i, j] * b[t + 1, j] * beta[t + 1, j];
                        beta[t, i] = s / c[t + 1];
                    }
                }
                // Etape E.
                double[,] gamma = new double[T, K];
                double[,] xiSum = new double[K, K];
                for (int t = 0; t < T; t++)
                {
                    double s = 0;
                    for (int k = 0; k < K; k++) { gamma[t, k] = alpha[t, k] * beta[t, k]; s += gamma[t, k]; }
                    if (s > 0) for (int k = 0; k < K; k++) gamma[t, k] /= s;
                }
                for (int t = 0; t < T - 1; t++)
                {
                    double s = 0;
                    double[,] xi = new double[K, K];
                    for (int i = 0; i < K; i++)
                        for (int j = 0; j < K; j++)
                        {
                            xi[i, j] = alpha[t, i] * A[i, j] * b[t + 1, j] * beta[t + 1, j];
                            s += xi[i, j];
                        }
                    if (s > 0) for (int i = 0; i < K; i++) for (int j = 0; j < K; j++) xiSum[i, j] += xi[i, j] / s;
                }
                // Etape M.
                for (int k = 0; k < K; k++) Pi[k] = Math.Max(gamma[0, k], 1e-6);
                double piSum = Pi.Sum();
                for (int k = 0; k < K; k++) Pi[k] /= piSum;
                for (int i = 0; i < K; i++)
                {
                    double row = 0;
                    for (int j = 0; j < K; j++) row += xiSum[i, j];
                    for (int j = 0; j < K; j++) A[i, j] = row > 0 ? Math.Max(xiSum[i, j] / row, 1e-6) : 1.0 / K;
                    double rs = 0; for (int j = 0; j < K; j++) rs += A[i, j];
                    for (int j = 0; j < K; j++) A[i, j] /= rs;
                }
                for (int k = 0; k < K; k++)
                {
                    double g = 0;
                    for (int t = 0; t < T; t++) g += gamma[t, k];
                    if (g < 1e-8) continue;
                    for (int d = 0; d < D; d++)
                    {
                        double m = 0;
                        for (int t = 0; t < T; t++) m += gamma[t, k] * X[t][d];
                        m /= g;
                        double v = 0;
                        for (int t = 0; t < T; t++) v += gamma[t, k] * (X[t][d] - m) * (X[t][d] - m);
                        Mu[k, d] = m;
                        Var[k, d] = Math.Max(v / g, VarFloor);
                    }
                }
                LogLikelihood = ll;
                Iterations = it + 1;
                if (Math.Abs(ll - prevLl) < tol) break;
                prevLl = ll;
            }
        }

        /// <summary>Ordre des etats par moyenne croissante de la variable featureIndex.</summary>
        public int[] OrderByFeature(int featureIndex)
        {
            return Enumerable.Range(0, K).OrderBy(k => Mu[k, featureIndex]).ToArray();
        }
    }

    // =========================================================================
    //  Detecteur de regime HMM (module A)
    // =========================================================================
    public class NxHmmRegimeDetector
    {
        // --- Configuration (valeurs "Correction proposee" de la fiche A) ---
        public int Window = 600;            // 500-750 jours
        public int RefitEveryDays = 5;      // hebdomadaire
        public int NInit = 10;
        public int MaxIter = 200;
        public double Tol = 1e-4;
        public int SmoothSpan = 5;          // moyenne exponentielle 5 jours
        public double Cap = 0.95;
        public int VolWindow = 20;          // volatilite realisee utilisee comme variable
        public int Seed = 42;
        public int MinObservations = 250;

        // --- Etat ---
        private readonly List<double> closes = new List<double>();
        private readonly List<double> rets = new List<double>();
        private readonly List<double[]> features = new List<double[]>();
        private NxGaussianHmm model;
        private double[] fMean, fStd;
        private int[] order;                 // order[0] = calme, order[K-1] = stress
        private double[] filtered;           // probabilites filtrees (indices du modele)
        private double[] smoothed;           // dans l ordre calme/neutre/stress
        private int daysSinceFit = int.MaxValue;
        private int dims;

        public bool UseVix { get; private set; }
        public int FitCount { get; private set; }
        public double LastLogLikelihood { get { return model == null ? double.NaN : model.LogLikelihood; } }

        public NxHmmRegimeDetector(bool useVix) { UseVix = useVix; dims = useVix ? 3 : 2; }

        public bool IsReady { get { return smoothed != null; } }

        /// <summary>[P(calme), P(neutre), P(stress)] lissees et plafonnees.</summary>
        public double[] Probabilities { get { return smoothed == null ? new[] { double.NaN, double.NaN, double.NaN } : (double[])smoothed.Clone(); } }

        public NxRegime Regime
        {
            get
            {
                if (smoothed == null) return NxRegime.Inconnu;
                int k = 0;
                for (int i = 1; i < smoothed.Length; i++) if (smoothed[i] > smoothed[k]) k = i;
                return k == 0 ? NxRegime.Calme : (k == 1 ? NxRegime.Neutre : NxRegime.Stress);
            }
        }

        public double StressProbability { get { return smoothed == null ? double.NaN : smoothed[2]; } }

        /// <summary>A appeler une fois par jour de bourse avec la cloture du barometre (et du VIX si utilise).</summary>
        public void Update(double close, double vix)
        {
            if (!NxMath.Ok(close) || close <= 0) return;
            if (closes.Count > 0) rets.Add(Math.Log(close / closes[closes.Count - 1]));
            closes.Add(close);
            if (rets.Count < VolWindow) return;

            double vol = NxMath.StdLast(rets, VolWindow) * Math.Sqrt(NxMath.TradingDaysPerYear);
            double r = rets[rets.Count - 1];
            double[] f;
            if (UseVix)
            {
                if (!NxMath.Ok(vix) || vix <= 0) vix = features.Count > 0 ? features[features.Count - 1][2] : vol * 100;
                f = new[] { r, vol, vix };
            }
            else f = new[] { r, vol };
            features.Add(f);
            if (features.Count > Window * 2) features.RemoveRange(0, features.Count - Window * 2);

            daysSinceFit++;
            if (features.Count >= MinObservations && (model == null || daysSinceFit >= RefitEveryDays)) Refit();
            else if (model != null) Step(f);
        }

        private double[] Standardize(double[] f)
        {
            double[] z = new double[dims];
            for (int d = 0; d < dims; d++) z[d] = fStd[d] > 0 ? (f[d] - fMean[d]) / fStd[d] : 0.0;
            return z;
        }

        private void Refit()
        {
            int n = Math.Min(Window, features.Count);
            List<double[]> win = features.GetRange(features.Count - n, n);
            fMean = new double[dims]; fStd = new double[dims];
            for (int d = 0; d < dims; d++)
            {
                List<double> col = win.Select(x => x[d]).ToList();
                fMean[d] = NxMath.Mean(col);
                fStd[d] = NxMath.StdDev(col);
                if (!NxMath.Ok(fStd[d]) || fStd[d] <= 0) fStd[d] = 1.0;
            }
            double[][] X = win.Select(Standardize).ToArray();
            NxGaussianHmm h = NxGaussianHmm.Fit(X, 3, NInit, MaxIter, Tol, Seed + FitCount);
            if (h == null) return;
            model = h;
            order = model.OrderByFeature(1);   // variable 1 = volatilite realisee
            filtered = model.FilterLast(X);      // passe avant seule sur la fenetre
            daysSinceFit = 0;
            FitCount++;
            Publish();
        }

        private void Step(double[] f)
        {
            if (model == null || filtered == null) return;
            filtered = model.ForwardStep(filtered, Standardize(f));
            Publish();
        }

        private void Publish()
        {
            double[] p = new double[3];
            for (int i = 0; i < 3; i++) p[i] = filtered[order[i]];
            if (smoothed == null) smoothed = p;
            else
            {
                double a = 2.0 / (SmoothSpan + 1.0);
                for (int i = 0; i < 3; i++) smoothed[i] = a * p[i] + (1 - a) * smoothed[i];
            }
            smoothed = CapProbabilities(smoothed, Cap);
        }

        /// <summary>Plafonne chaque probabilite a cap et redistribue l exces proportionnellement.</summary>
        public static double[] CapProbabilities(double[] p, double cap)
        {
            double[] q = (double[])p.Clone();
            double s = q.Sum();
            if (s <= 0) return new[] { 1.0 / 3, 1.0 / 3, 1.0 / 3 };
            for (int i = 0; i < q.Length; i++) q[i] /= s;
            for (int guard = 0; guard < 5; guard++)
            {
                double excess = 0, freeMass = 0;
                for (int i = 0; i < q.Length; i++)
                {
                    if (q[i] > cap) { excess += q[i] - cap; q[i] = cap; }
                    else freeMass += q[i];
                }
                if (excess <= 1e-12) break;
                for (int i = 0; i < q.Length; i++)
                    if (q[i] < cap) q[i] += freeMass > 0 ? excess * q[i] / freeMass : excess / (q.Length - 1);
            }
            return q;
        }

        public string Describe()
        {
            if (!IsReady) return "HMM: en chauffage (" + features.Count + "/" + MinObservations + " obs)";
            double[] p = Probabilities;
            return string.Format(System.Globalization.CultureInfo.InvariantCulture,
                "HMM {0} | P(calme)={1:F2} P(neutre)={2:F2} P(stress)={3:F2} | LL={4:F1} fits={5}",
                Regime, p[0], p[1], p[2], LastLogLikelihood, FitCount);
        }
    }

    // =========================================================================
    //  Registre des regimes publies en temps reel (moniteur du module A)
    // =========================================================================
    public static class NxRegimeRegistry
    {
        public class Entry
        {
            public NxRegime Hmm;
            public double[] HmmProbabilities;
            public NxRegime VolTerciles;
            public DateTime Time;
        }

        private static readonly Dictionary<string, Entry> entries = new Dictionary<string, Entry>(StringComparer.OrdinalIgnoreCase);
        private static readonly object sync = new object();

        public static void Publish(string barometer, NxRegime hmmRegime, double[] probs, NxRegime volRegime, DateTime time)
        {
            lock (sync) entries[barometer] = new Entry { Hmm = hmmRegime, HmmProbabilities = probs, VolTerciles = volRegime, Time = time };
        }

        public static bool TryGet(string barometer, out Entry e)
        {
            lock (sync) return entries.TryGetValue(barometer, out e);
        }
    }

    // =========================================================================
    //  FICHE 12 - Regime par terciles de volatilite realisee
    // =========================================================================
    public class NxVolTercileRegime
    {
        public int RvWindow = 20;          // volatilite realisee 20 jours, annualisee
        public int LookbackDays = 504;     // terciles sur 2 ans
        public int ConfirmDays = 5;        // anti-clignotement
        public int MinHistory = 120;       // jours de vol realisee minimum avant de classer

        private readonly List<double> closes = new List<double>();
        private readonly List<double> rets = new List<double>();
        private readonly List<double> rvHist = new List<double>();
        private NxRegime candidate = NxRegime.Inconnu;
        private int candidateCount;

        public NxRegime Regime { get; private set; }
        public NxRegime RawRegime { get; private set; }
        public double Rv { get; private set; }
        public double LowCut { get; private set; }
        public double HighCut { get; private set; }
        public int DaysInRegime { get; private set; }

        public NxVolTercileRegime() { Regime = NxRegime.Inconnu; RawRegime = NxRegime.Inconnu; Rv = double.NaN; LowCut = double.NaN; HighCut = double.NaN; }

        public bool IsReady { get { return Regime != NxRegime.Inconnu; } }

        public void Update(double close)
        {
            if (!NxMath.Ok(close) || close <= 0) return;
            if (closes.Count > 0) rets.Add(Math.Log(close / closes[closes.Count - 1]));
            closes.Add(close);
            if (closes.Count > LookbackDays + RvWindow + 10) closes.RemoveAt(0);
            if (rets.Count > LookbackDays + RvWindow + 10) rets.RemoveAt(0);
            if (rets.Count < RvWindow) return;

            Rv = NxMath.StdLast(rets, RvWindow) * Math.Sqrt(NxMath.TradingDaysPerYear);
            rvHist.Add(Rv);
            if (rvHist.Count > LookbackDays) rvHist.RemoveAt(0);
            if (rvHist.Count < MinHistory) return;

            LowCut = NxMath.Quantile(rvHist, 1.0 / 3.0);
            HighCut = NxMath.Quantile(rvHist, 2.0 / 3.0);
            RawRegime = Rv < LowCut ? NxRegime.Calme : (Rv > HighCut ? NxRegime.Stress : NxRegime.Neutre);

            if (Regime == NxRegime.Inconnu) { Regime = RawRegime; DaysInRegime = 1; return; }
            if (RawRegime == Regime) { candidate = NxRegime.Inconnu; candidateCount = 0; DaysInRegime++; return; }
            if (RawRegime == candidate) candidateCount++;
            else { candidate = RawRegime; candidateCount = 1; }
            if (candidateCount >= ConfirmDays)
            {
                Regime = candidate;
                candidate = NxRegime.Inconnu;
                candidateCount = 0;
                DaysInRegime = 1;
            }
            else DaysInRegime++;
        }

        public string Describe()
        {
            return string.Format(System.Globalization.CultureInfo.InvariantCulture,
                "VolTerciles {0} (brut {1}) RV20={2:P1} coupures [{3:P1} ; {4:P1}]", Regime, RawRegime, Rv, LowCut, HighCut);
        }
    }
}
