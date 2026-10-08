// =============================================================================
//  NexusModuleB_Sizing.cs   (NinjaTrader 8 / NinjaScript - bibliotheque)
//
//  MODULE B - Taille des positions : demi-Kelly et plafonds (regles du fil)
//
//    Base                 demi-Kelly (x0.5), avantage estime par la confiance   [Fil]
//    "Davey waiver"       < 30 trades resolus EN REEL : taille x0.5 en plus      [Fil]
//    Plafond par trade    3 % du bankroll (30 $ au depart sur 1 000 $)           [Fil]
//    Exposition totale    50 % du bankroll                                       [Fil]
//    Par classe d actifs  30 %                                                   [Fil]
//    Par symbole          10 % ; si deux strategies veulent le meme titre,
//                         une seule passe (registre inter-strategies, temps reel)[Fil]
//    Pas de budget par strategie : chaque signal est dimensionne seul            [Fil]
//
//  Formule de Kelly (gagnant/perdant) : f* = p - (1-p)/b.
//  Avec p = 0.472 (taux Nexus), f* > 0 seulement si b > 1.12.
//
//  Ajouts [Choix] documentes dans la fiche :
//    - correction de correlation : taille / (1 + somme des correlations > 0
//      avec les positions ouvertes) (Bluppy2947)
//    - Kelly sous contrainte de drawdown (Busseti, Ryu, Boyd - arXiv 1603.06183)
//    - borne basse de Wilson sur p (incertitude sur l avantage), optionnelle
//    - matrice de correlation hebdomadaire des rendements des strategies
// =============================================================================

#region Using declarations
using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Linq;
using System.Text;
#endregion

namespace NinjaTrader.NinjaScript.AddOns.Nexus
{
    /// <summary>Base de dimensionnement d un signal.</summary>
    public enum NxSizingMode
    {
        /// <summary>Taille propre a la fiche (volatilite cible, poids egal...), puis plafonds.</summary>
        Natif,
        /// <summary>Demi-Kelly [Fil], puis plafonds.</summary>
        DemiKelly,
        /// <summary>Kelly sous contrainte de probabilite de drawdown (Busseti et al.).</summary>
        KellyContraintDrawdown,
        /// <summary>Minimum entre la taille native et le demi-Kelly.</summary>
        MinNatifEtKelly
    }

    /// <summary>Lecture de la fraction de Kelly.</summary>
    public enum NxKellyLecture
    {
        /// <summary>f = fraction du bankroll investie (notionnel) - lecture du fil.</summary>
        FractionNotionnel,
        /// <summary>f = fraction du bankroll RISQUEE ; notionnel = f / perte moyenne en %.</summary>
        FractionRisquee
    }

    // =========================================================================
    //  Statistiques de trades d une strategie
    // =========================================================================
    public class NxTradeStats
    {
        private readonly List<double> rets = new List<double>();   // rendement net par trade (fraction du notionnel)
        public int MaxHistory = 1000;
        public int LiveResolved;                                     // trades resolus en reel (persistant)

        public int Count { get { return rets.Count; } }
        public IList<double> Returns { get { return rets; } }

        public void Add(double netReturn)
        {
            if (!NxMath.Ok(netReturn)) return;
            rets.Add(netReturn);
            if (rets.Count > MaxHistory) rets.RemoveAt(0);
        }

        public int Wins { get { return rets.Count(r => r > 0); } }
        public double WinRate { get { return Count > 0 ? (double)Wins / Count : double.NaN; } }
        public double AvgWin { get { List<double> w = rets.Where(r => r > 0).ToList(); return w.Count > 0 ? w.Average() : double.NaN; } }
        public double AvgLoss { get { List<double> l = rets.Where(r => r <= 0).ToList(); return l.Count > 0 ? -l.Average() : double.NaN; } }
        public double Payoff { get { double w = AvgWin, l = AvgLoss; return (NxMath.Ok(w) && NxMath.Ok(l) && l > 0) ? w / l : double.NaN; } }

        // --- Persistance du compteur de trades reels (Davey waiver) ---
        public static string LiveCountFile(string strategyId) { return Path.Combine(NxPaths.State, NxPaths.SafeFileName(strategyId) + "_trades_reels.txt"); }

        public void LoadLiveCount(string strategyId)
        {
            try
            {
                string s = NxCsv.ReadAllSafe(LiveCountFile(strategyId));
                int v;
                if (s != null && int.TryParse(s.Trim(), out v)) LiveResolved = v;
            }
            catch { }
        }

        public void SaveLiveCount(string strategyId) { NxCsv.WriteAll(LiveCountFile(strategyId), LiveResolved.ToString(CultureInfo.InvariantCulture)); }
    }

    // =========================================================================
    //  Kelly
    // =========================================================================
    public static class NxKelly
    {
        /// <summary>f* = p - (1-p)/b.</summary>
        public static double Fraction(double p, double b)
        {
            if (!NxMath.Ok(p) || !NxMath.Ok(b) || b <= 0) return double.NaN;
            return p - (1.0 - p) / b;
        }

        /// <summary>Rapport gain/perte minimal pour que Kelly soit positif : (1-p)/p.</summary>
        public static double BreakEvenPayoff(double p) { return p > 0 ? (1 - p) / p : double.NaN; }

        /// <summary>Intervalle de Wilson du taux de reussite.</summary>
        public static void Wilson(int wins, int n, double z, out double lo, out double hi)
        {
            lo = hi = double.NaN;
            if (n <= 0) return;
            double p = (double)wins / n;
            double den = 1 + z * z / n;
            double centre = (p + z * z / (2.0 * n)) / den;
            double half = z * Math.Sqrt(p * (1 - p) / n + z * z / (4.0 * n * n)) / den;
            lo = centre - half; hi = centre + half;
        }

        /// <summary>
        /// Kelly sous contrainte de risque (Busseti, Ryu, Boyd) pour un pari binaire :
        /// max p log(1+fb) + (1-p) log(1-f)  s.c.  p(1+fb)^-L + (1-p)(1-f)^-L &lt;= 1,
        /// L = log(beta)/log(alpha). Garantit P(richesse min &lt; alpha) &lt; beta.
        /// </summary>
        public static double RiskConstrained(double p, double b, double alpha, double beta)
        {
            double fk = Fraction(p, b);
            if (!NxMath.Ok(fk) || fk <= 0) return 0.0;
            fk = Math.Min(fk, 0.999);
            if (!(alpha > 0 && alpha < 1 && beta > 0 && beta < 1)) return fk;
            double lambda = Math.Log(beta) / Math.Log(alpha);
            Func<double, double> g = f => p * Math.Pow(1 + f * b, -lambda) + (1 - p) * Math.Pow(1 - f, -lambda) - 1.0;
            if (g(fk) <= 0) return fk;
            double lo = 0, hi = fk;
            for (int i = 0; i < 100; i++)
            {
                double mid = 0.5 * (lo + hi);
                if (g(mid) <= 0) lo = mid; else hi = mid;
            }
            return lo;
        }
    }

    // =========================================================================
    //  Configuration et calcul de taille
    // =========================================================================
    public class NxSizingConfig
    {
        public NxSizingMode Mode = NxSizingMode.DemiKelly;
        public NxKellyLecture Lecture = NxKellyLecture.FractionNotionnel;
        public double KellyMultiplier = 0.5;           // demi-Kelly
        public double PriorWinRate = 0.50;             // a priori tant que peu de trades
        public double PriorPayoff = 1.20;
        public double PriorAvgLoss = 0.04;             // perte moyenne a priori (fraction du notionnel)
        public int PriorStrength = 30;                 // pseudo-trades de l a priori
        public double ConfidenceWeight = 0.5;          // poids de la confiance du modele dans p
        public bool UseWilsonLowerBound = false;
        public double WilsonZ = 1.96;
        public double NoEdgeFraction = 0.0;            // taille "sonde" si Kelly <= 0 (0 = ne pas trader)
        public double RckAlpha = 0.70;                 // plancher de richesse
        public double RckBeta = 0.10;                  // probabilite max de le toucher
        public int WaiverTrades = 30;                  // Davey waiver
        public double WaiverMultiplier = 0.5;
        public double MaxTradeFraction = 0.03;         // plafond par trade (0 = desactive)
        public double MaxTradeDollars = 0.0;           // plafond absolu (0 = desactive)
        public double MaxSymbolFraction = 0.10;
        public double MaxClassFraction = 0.30;
        public double MaxTotalFraction = 0.50;
        public bool UseCorrelationDivisor = true;
    }

    public class NxSizingResult
    {
        public double Fraction;        // fraction finale du bankroll (notionnel, >= 0)
        public double Native = double.NaN;
        public double Kelly = double.NaN;
        public double P = double.NaN;
        public double B = double.NaN;
        public string Detail = "";
        public bool Blocked;
    }

    public static class NxSizer
    {
        /// <summary>p et b estimes (a priori bayesien + historique + confiance du modele).</summary>
        public static void EstimateEdge(NxSizingConfig c, NxTradeStats s, double modelConfidence, out double p, out double b, out double avgLoss)
        {
            int n = s == null ? 0 : s.Count;
            int k = Math.Max(0, c.PriorStrength);
            int wins = s == null ? 0 : s.Wins;
            p = (wins + c.PriorWinRate * k) / Math.Max(1.0, n + k);
            if (c.UseWilsonLowerBound && n >= 10)
            {
                double lo, hi;
                NxKelly.Wilson(wins, n, c.WilsonZ, out lo, out hi);
                p = Math.Min(p, lo);
            }
            double bObs = s == null ? double.NaN : s.Payoff;
            b = NxMath.Ok(bObs) ? (n * bObs + k * c.PriorPayoff) / Math.Max(1.0, n + k) : c.PriorPayoff;
            double lObs = s == null ? double.NaN : s.AvgLoss;
            avgLoss = NxMath.Ok(lObs) && lObs > 0 ? (n * lObs + k * c.PriorAvgLoss) / Math.Max(1.0, n + k) : c.PriorAvgLoss;
            if (NxMath.Ok(modelConfidence) && modelConfidence > 0 && modelConfidence < 1)
                p = c.ConfidenceWeight * modelConfidence + (1 - c.ConfidenceWeight) * p;
        }

        /// <summary>Fraction de Kelly (deja multipliee : demi-Kelly par defaut), exprimee en notionnel.</summary>
        public static double KellyNotional(NxSizingConfig c, NxTradeStats s, double modelConfidence, out double p, out double b, out string detail)
        {
            double avgLoss;
            EstimateEdge(c, s, modelConfidence, out p, out b, out avgLoss);
            double f = c.Mode == NxSizingMode.KellyContraintDrawdown
                ? NxKelly.RiskConstrained(p, b, c.RckAlpha, c.RckBeta)
                : NxKelly.Fraction(p, b);
            detail = string.Format(CultureInfo.InvariantCulture, "p={0:F3} b={1:F2} f*={2:F4}", p, b, f);
            if (!NxMath.Ok(f) || f <= 0) return f;
            f *= c.KellyMultiplier;
            if (c.Lecture == NxKellyLecture.FractionRisquee && avgLoss > 0) f /= avgLoss;
            return f;
        }

        /// <summary>
        /// Taille finale (fraction du bankroll en notionnel) d un signal :
        /// base -> waiver -> correlation -> plafonds trade / symbole / classe / total / dollars.
        /// </summary>
        public static NxSizingResult Size(NxSizingConfig c, NxTradeStats stats, double nativeFraction, double modelConfidence,
                                          double sumPositiveCorrelation, double equity,
                                          double otherSymbolExposure, double otherClassExposure, double otherTotalExposure)
        {
            NxSizingResult r = new NxSizingResult();
            StringBuilder d = new StringBuilder();
            r.Native = Math.Abs(nativeFraction);
            double f;
            string kd = "";
            double p = double.NaN, b = double.NaN;
            if (c.Mode == NxSizingMode.Natif) f = r.Native;
            else
            {
                double k = KellyNotional(c, stats, modelConfidence, out p, out b, out kd);
                r.Kelly = k; r.P = p; r.B = b;
                if (!NxMath.Ok(k) || k <= 0)
                {
                    if (c.NoEdgeFraction > 0) { k = c.NoEdgeFraction; d.Append("Kelly<=0 -> sonde; "); }
                    else
                    {
                        r.Blocked = true;
                        r.Fraction = 0;
                        r.Detail = "BLOQUE: Kelly <= 0 (" + kd + ")";
                        return r;
                    }
                }
                f = c.Mode == NxSizingMode.MinNatifEtKelly ? Math.Min(r.Native, k) : k;
                d.Append(kd).Append("; ");
            }
            d.AppendFormat(CultureInfo.InvariantCulture, "base={0:P2}", f);

            if (stats != null && stats.LiveResolved < c.WaiverTrades)
            {
                f *= c.WaiverMultiplier;
                d.AppendFormat(CultureInfo.InvariantCulture, "; waiver x{0} ({1}/{2} reels)", c.WaiverMultiplier, stats.LiveResolved, c.WaiverTrades);
            }
            if (c.UseCorrelationDivisor && NxMath.Ok(sumPositiveCorrelation) && sumPositiveCorrelation > 0)
            {
                f /= (1.0 + sumPositiveCorrelation);
                d.AppendFormat(CultureInfo.InvariantCulture, "; /(1+{0:F2}) corr", sumPositiveCorrelation);
            }
            if (c.MaxTradeFraction > 0 && f > c.MaxTradeFraction) { f = c.MaxTradeFraction; d.Append("; plafond trade"); }
            if (c.MaxSymbolFraction > 0 && f + otherSymbolExposure > c.MaxSymbolFraction) { f = Math.Max(0, c.MaxSymbolFraction - otherSymbolExposure); d.Append("; plafond symbole"); }
            if (c.MaxClassFraction > 0 && f + otherClassExposure > c.MaxClassFraction) { f = Math.Max(0, c.MaxClassFraction - otherClassExposure); d.Append("; plafond classe"); }
            if (c.MaxTotalFraction > 0 && f + otherTotalExposure > c.MaxTotalFraction) { f = Math.Max(0, c.MaxTotalFraction - otherTotalExposure); d.Append("; plafond total"); }
            if (c.MaxTradeDollars > 0 && equity > 0 && f * equity > c.MaxTradeDollars) { f = c.MaxTradeDollars / equity; d.Append("; plafond $"); }
            r.Fraction = Math.Max(0, f);
            d.AppendFormat(CultureInfo.InvariantCulture, " => {0:P2}", r.Fraction);
            r.Detail = d.ToString();
            return r;
        }
    }

    // =========================================================================
    //  Registre inter-strategies (TEMPS REEL uniquement, par compte)
    //  En backtest/optimisation, chaque instance est isolee : le registre n est
    //  pas utilise (sinon les iterations paralleles de l optimiseur se verraient).
    // =========================================================================
    public static class NxPortfolioRegistry
    {
        private class Entry
        {
            public string StrategyId;
            public double Notional;
            public NxAssetClass Class;
            public DateTime Updated;
        }

        private static readonly object sync = new object();
        // compte -> symbole -> entree
        private static readonly Dictionary<string, Dictionary<string, Entry>> book = new Dictionary<string, Dictionary<string, Entry>>(StringComparer.OrdinalIgnoreCase);
        // strategie -> (date -> rendement journalier)
        private static readonly Dictionary<string, SortedDictionary<DateTime, double>> stratReturns = new Dictionary<string, SortedDictionary<DateTime, double>>(StringComparer.OrdinalIgnoreCase);

        private static Dictionary<string, Entry> Acc(string account)
        {
            Dictionary<string, Entry> d;
            if (!book.TryGetValue(account ?? "", out d)) { d = new Dictionary<string, Entry>(StringComparer.OrdinalIgnoreCase); book[account ?? ""] = d; }
            return d;
        }

        /// <summary>Proprietaire actuel d un symbole sur ce compte (null si libre).</summary>
        public static string Owner(string account, string symbol)
        {
            lock (sync)
            {
                Entry e;
                return Acc(account).TryGetValue(symbol, out e) ? e.StrategyId : null;
            }
        }

        /// <summary>Reserve le symbole ; false si une AUTRE strategie le detient deja ("une seule passe").</summary>
        public static bool TryClaim(string account, string symbol, string strategyId, NxAssetClass cls)
        {
            lock (sync)
            {
                Dictionary<string, Entry> d = Acc(account);
                Entry e;
                if (d.TryGetValue(symbol, out e) && !string.Equals(e.StrategyId, strategyId, StringComparison.OrdinalIgnoreCase)) return false;
                if (e == null) d[symbol] = new Entry { StrategyId = strategyId, Class = cls, Updated = DateTime.UtcNow };
                return true;
            }
        }

        public static void UpdateNotional(string account, string symbol, string strategyId, double notional, NxAssetClass cls)
        {
            lock (sync)
            {
                Dictionary<string, Entry> d = Acc(account);
                Entry e;
                if (!d.TryGetValue(symbol, out e)) { e = new Entry { StrategyId = strategyId, Class = cls }; d[symbol] = e; }
                if (!string.Equals(e.StrategyId, strategyId, StringComparison.OrdinalIgnoreCase)) return;
                e.Notional = Math.Abs(notional); e.Class = cls; e.Updated = DateTime.UtcNow;
            }
        }

        public static void Release(string account, string symbol, string strategyId)
        {
            lock (sync)
            {
                Dictionary<string, Entry> d = Acc(account);
                Entry e;
                if (d.TryGetValue(symbol, out e) && string.Equals(e.StrategyId, strategyId, StringComparison.OrdinalIgnoreCase)) d.Remove(symbol);
            }
        }

        public static void ReleaseAll(string account, string strategyId)
        {
            lock (sync)
            {
                Dictionary<string, Entry> d = Acc(account);
                foreach (string k in d.Where(kv => string.Equals(kv.Value.StrategyId, strategyId, StringComparison.OrdinalIgnoreCase)).Select(kv => kv.Key).ToList()) d.Remove(k);
            }
        }

        /// <summary>Exposition (en devise) des AUTRES strategies : totale, de la classe, et du symbole.</summary>
        public static void OtherExposure(string account, string strategyId, string symbol, NxAssetClass cls, out double total, out double sameClass, out double sameSymbol)
        {
            total = sameClass = sameSymbol = 0;
            lock (sync)
            {
                foreach (KeyValuePair<string, Entry> kv in Acc(account))
                {
                    if (string.Equals(kv.Value.StrategyId, strategyId, StringComparison.OrdinalIgnoreCase)) continue;
                    total += kv.Value.Notional;
                    if (kv.Value.Class == cls) sameClass += kv.Value.Notional;
                    if (string.Equals(kv.Key, symbol, StringComparison.OrdinalIgnoreCase)) sameSymbol += kv.Value.Notional;
                }
            }
        }

        public static List<string> SymbolsHeldByOthers(string account, string strategyId)
        {
            lock (sync)
                return Acc(account).Where(kv => !string.Equals(kv.Value.StrategyId, strategyId, StringComparison.OrdinalIgnoreCase) && kv.Value.Notional > 0)
                                   .Select(kv => kv.Key).ToList();
        }

        public static void RecordStrategyReturn(string strategyId, DateTime day, double ret)
        {
            if (!NxMath.Ok(ret)) return;
            lock (sync)
            {
                SortedDictionary<DateTime, double> s;
                if (!stratReturns.TryGetValue(strategyId, out s)) { s = new SortedDictionary<DateTime, double>(); stratReturns[strategyId] = s; }
                s[day.Date] = ret;
                while (s.Count > 1000) s.Remove(s.Keys.First());
            }
        }

        /// <summary>Matrice de correlation des rendements journaliers des strategies actives (memoire).</summary>
        public static string CorrelationReport(int window)
        {
            Dictionary<string, SortedDictionary<DateTime, double>> copy;
            lock (sync) copy = stratReturns.ToDictionary(kv => kv.Key, kv => new SortedDictionary<DateTime, double>(kv.Value));
            return NxStrategyCorrelation.Report(copy, window);
        }
    }

    // =========================================================================
    //  Correlation entre strategies (Bluppy2947) - memoire ou fichiers
    // =========================================================================
    public static class NxStrategyCorrelation
    {
        /// <summary>Charge les rendements journaliers ecrits par chaque strategie (journal\returns_*.csv).</summary>
        public static Dictionary<string, SortedDictionary<DateTime, double>> LoadFromJournal(string folder)
        {
            Dictionary<string, SortedDictionary<DateTime, double>> res = new Dictionary<string, SortedDictionary<DateTime, double>>(StringComparer.OrdinalIgnoreCase);
            if (!Directory.Exists(folder)) return res;
            foreach (string f in Directory.GetFiles(folder, "returns_*.csv"))
            {
                string name = Path.GetFileNameWithoutExtension(f).Substring("returns_".Length);
                string[] h;
                List<string[]> rows = NxCsv.ReadRows(f, out h);
                int cd = NxCsv.Col(h, "date"), cr = NxCsv.Col(h, "return", "rendement");
                if (cd < 0 || cr < 0) continue;
                SortedDictionary<DateTime, double> s = new SortedDictionary<DateTime, double>();
                foreach (string[] r in rows)
                {
                    DateTime d;
                    if (!NxCsv.TryParseDate(NxCsv.Get(r, cd), out d)) continue;
                    double v = NxCsv.ParseDouble(NxCsv.Get(r, cr));
                    if (NxMath.Ok(v)) s[d.Date] = v;
                }
                if (s.Count > 0) res[name] = s;
            }
            return res;
        }

        public static double[,] Matrix(Dictionary<string, SortedDictionary<DateTime, double>> data, int window, out string[] names)
        {
            names = data.Keys.OrderBy(k => k).ToArray();
            int n = names.Length;
            double[,] m = new double[n, n];
            for (int i = 0; i < n; i++)
                for (int j = 0; j < n; j++)
                {
                    if (i == j) { m[i, j] = 1; continue; }
                    SortedDictionary<DateTime, double> a = data[names[i]], b = data[names[j]];
                    List<DateTime> common = a.Keys.Where(b.ContainsKey).OrderByDescending(d => d).Take(window).ToList();
                    m[i, j] = common.Count >= 10 ? NxMath.Correlation(common.Select(d => a[d]).ToList(), common.Select(d => b[d]).ToList()) : double.NaN;
                }
            return m;
        }

        public static string Report(Dictionary<string, SortedDictionary<DateTime, double>> data, int window)
        {
            string[] names;
            double[,] m = Matrix(data, window, out names);
            StringBuilder sb = new StringBuilder();
            sb.AppendLine("Matrice de correlation des rendements journaliers des strategies (" + window + " derniers jours communs)");
            if (names.Length < 2) { sb.AppendLine("  (moins de deux strategies avec des rendements)"); return sb.ToString(); }
            sb.Append(string.Format("{0,-28}", ""));
            for (int j = 0; j < names.Length; j++) sb.Append(string.Format("{0,8}", "#" + (j + 1)));
            sb.AppendLine();
            for (int i = 0; i < names.Length; i++)
            {
                string nm = names[i].Length > 24 ? names[i].Substring(0, 24) : names[i];
                sb.Append(string.Format("{0,-28}", "#" + (i + 1) + " " + nm));
                for (int j = 0; j < names.Length; j++)
                    sb.Append(NxMath.Ok(m[i, j]) ? string.Format(CultureInfo.InvariantCulture, "{0,8:F2}", m[i, j]) : string.Format("{0,8}", "n/a"));
                sb.AppendLine();
            }
            double maxOff = double.NaN;
            for (int i = 0; i < names.Length; i++) for (int j = i + 1; j < names.Length; j++)
                    if (NxMath.Ok(m[i, j]) && (!NxMath.Ok(maxOff) || m[i, j] > maxOff)) maxOff = m[i, j];
            if (NxMath.Ok(maxOff) && maxOff >= 0.3)
                sb.AppendLine(string.Format(CultureInfo.InvariantCulture,
                    "ALERTE : correlation max {0:F2} >= 0.30 -> les demi-Kelly additionnes surestiment le risque (fiche B).", maxOff));
            return sb.ToString();
        }
    }
}
