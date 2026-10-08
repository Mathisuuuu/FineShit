// =============================================================================
//  NexusSignals.cs   (NinjaTrader 8 / NinjaScript - bibliotheque)
//
//  Moteurs de signaux partages entre fiches (pour que la fiche 8 juge
//  exactement les memes candidats que les fiches 1, 2 et 3) :
//    NxMomentum          rendement "12-1", poids inverse a la volatilite
//    NxPanicState        etat de panique (fiches 1 et 2)
//    NxRankSelection     top N avec tampon de rotation (fiches 2 et 3)
//    NxAtrStop           stop ATR x k borne entre 2 % et 8 % du prix
//    NxResidual          residus d une regression sur un ETF/indice (fiches 4A, 14)
//    NxMultiFactorEngine momentum + value + qualite avec rotation des facteurs (fiche 3)
// =============================================================================

#region Using declarations
using System;
using System.Collections.Generic;
using System.Globalization;
using System.Linq;
#endregion

namespace NinjaTrader.NinjaScript.AddOns.Nexus
{
    public static class NxMomentum
    {
        /// <summary>Rendement 12-1 : de t-lookback a t-skip (jours de bourse).</summary>
        public static double Return12_1(NxBarHistory h, int lookbackDays = 252, int skipDays = 21)
        {
            if (h == null || h.Count <= lookbackDays) return double.NaN;
            return h.ReturnOver(lookbackDays, skipDays);
        }

        /// <summary>Poids = (vol cible / vol realisee) / N (formulation Moskowitz-Ooi-Pedersen).</summary>
        public static double InverseVolWeight(NxBarHistory h, double targetVol, int volWindow, int nAssets, double maxWeight)
        {
            double vol = h == null ? double.NaN : h.RealizedVol(volWindow);
            if (!NxMath.Ok(vol) || vol <= 1e-6 || nAssets <= 0) return double.NaN;
            double w = targetVol / vol / nAssets;
            return maxWeight > 0 ? Math.Min(w, maxWeight) : w;
        }
    }

    /// <summary>
    /// Etat de panique (Daniel et Moskowitz) : barometre sous son niveau d il y a 24 mois
    /// ET volatilite 1 mois au-dessus de sa mediane sur 1 an. [Choix] de la fiche 1.
    /// </summary>
    public static class NxPanicState
    {
        public static bool Evaluate(NxBarHistory spy, int lookbackDays, int volDays, int medianDays, out string detail)
        {
            detail = "";
            if (spy == null || spy.Count < Math.Max(lookbackDays, medianDays + volDays) + 2) { detail = "panique: historique insuffisant"; return false; }
            double now = spy.LastClose, then = spy.CloseAgo(lookbackDays);
            bool below = now < then;
            List<double> rets = spy.Returns(medianDays + volDays);
            List<double> vols = new List<double>();
            for (int end = volDays; end <= rets.Count; end++) vols.Add(NxMath.StdDev(rets, end - volDays, volDays));
            double cur = vols.Count > 0 ? vols[vols.Count - 1] : double.NaN;
            double med = NxMath.Median(vols.Skip(Math.Max(0, vols.Count - medianDays)));
            bool highVol = NxMath.Ok(cur) && NxMath.Ok(med) && cur > med;
            detail = string.Format(CultureInfo.InvariantCulture, "SPY {0:F2} vs {1:F2} il y a {2}j ; vol1m {3:P1} vs mediane {4:P1}",
                now, then, lookbackDays, cur * Math.Sqrt(252), med * Math.Sqrt(252));
            return below && highVol;
        }
    }

    public static class NxRankSelection
    {
        /// <summary>
        /// Garde les detenus encore dans le top "buffer", puis complete avec les meilleurs jusqu a "top".
        /// scores : symbole -> score (plus grand = meilleur), NaN exclus.
        /// </summary>
        public static List<string> SelectWithBuffer(Dictionary<string, double> scores, ICollection<string> held, int top, int buffer)
        {
            List<string> ranked = scores.Where(kv => NxMath.Ok(kv.Value)).OrderByDescending(kv => kv.Value).Select(kv => kv.Key).ToList();
            List<string> keep = new List<string>();
            for (int i = 0; i < ranked.Count && i < buffer; i++)
                if (held != null && held.Contains(ranked[i])) keep.Add(ranked[i]);
            foreach (string s in ranked)
            {
                if (keep.Count >= top) break;
                if (!keep.Contains(s)) keep.Add(s);
            }
            return keep;
        }

        public static int RankOf(Dictionary<string, double> scores, string symbol)
        {
            List<string> ranked = scores.Where(kv => NxMath.Ok(kv.Value)).OrderByDescending(kv => kv.Value).Select(kv => kv.Key).ToList();
            int i = ranked.IndexOf(symbol);
            return i < 0 ? int.MaxValue : i + 1;
        }
    }

    /// <summary>Operations sur plusieurs historiques alignes par jour de bourse.</summary>
    public static class NxPanel
    {
        /// <summary>
        /// Rendements log alignes : une ligne par date commune (n dernieres), une colonne par historique.
        /// </summary>
        public static List<double[]> AlignedReturnRows(IList<NxBarHistory> hs, int n)
        {
            List<double[]> rows = new List<double[]>();
            if (hs == null || hs.Count == 0 || hs.Any(h => h == null || h.Count < 2)) return rows;
            NxBarHistory refH = hs.OrderBy(h => h.Count).First();
            List<int[]> idx = new List<int[]>();
            for (int i = refH.Count - 1; i >= 0 && idx.Count < n + 1; i--)
            {
                DateTime d = refH.Dates[i];
                int[] row = new int[hs.Count];
                bool all = true;
                for (int k = 0; k < hs.Count; k++) { row[k] = hs[k].IndexOf(d); if (row[k] < 0) { all = false; break; } }
                if (all) idx.Add(row);
            }
            idx.Reverse();
            for (int t = 1; t < idx.Count; t++)
            {
                double[] r = new double[hs.Count];
                for (int k = 0; k < hs.Count; k++)
                {
                    double p0 = hs[k].Close[idx[t - 1][k]], p1 = hs[k].Close[idx[t][k]];
                    r[k] = p0 > 0 ? Math.Log(p1 / p0) : double.NaN;
                }
                rows.Add(r);
            }
            return rows;
        }

        /// <summary>Volatilite annualisee d un panier pondere (rendements alignes sur n jours).</summary>
        public static double BasketVol(IList<NxBarHistory> hs, IList<double> weights, int n)
        {
            List<double[]> rows = AlignedReturnRows(hs, n);
            if (rows.Count < Math.Max(10, n / 3)) return double.NaN;
            List<double> b = rows.Select(r => { double s = 0; for (int k = 0; k < r.Length; k++) s += weights[k] * (NxMath.Ok(r[k]) ? r[k] : 0); return s; }).ToList();
            double sd = NxMath.StdDev(b);
            return NxMath.Ok(sd) ? sd * Math.Sqrt(NxMath.TradingDaysPerYear) : double.NaN;
        }

        /// <summary>Rendements mensuels (cloture de fin de mois a fin de mois), du plus ancien au plus recent.</summary>
        public static List<KeyValuePair<DateTime, double>> MonthlyReturns(NxBarHistory h, int months)
        {
            List<KeyValuePair<DateTime, double>> res = new List<KeyValuePair<DateTime, double>>();
            if (h == null || h.Count < 2) return res;
            List<KeyValuePair<DateTime, double>> ends = new List<KeyValuePair<DateTime, double>>();
            for (int i = 0; i < h.Count; i++)
            {
                DateTime m = new DateTime(h.Dates[i].Year, h.Dates[i].Month, 1);
                if (ends.Count > 0 && ends[ends.Count - 1].Key == m) ends[ends.Count - 1] = new KeyValuePair<DateTime, double>(m, h.Close[i]);
                else ends.Add(new KeyValuePair<DateTime, double>(m, h.Close[i]));
            }
            for (int k = Math.Max(1, ends.Count - months); k < ends.Count; k++)
            {
                double p0 = ends[k - 1].Value, p1 = ends[k].Value;
                if (p0 > 0) res.Add(new KeyValuePair<DateTime, double>(ends[k].Key, p1 / p0 - 1));
            }
            return res;
        }
    }

    public static class NxAtrStop
    {
        /// <summary>Distance de stop = clamp(k * ATR, minPct * prix, maxPct * prix).</summary>
        public static double Distance(double price, double atr, double mult, double minPct, double maxPct)
        {
            if (!NxMath.Ok(price) || price <= 0) return double.NaN;
            double d = NxMath.Ok(atr) && atr > 0 ? atr * mult : maxPct * price;
            return NxMath.Clamp(d, minPct * price, maxPct * price);
        }

        public static double LongStop(double price, double atr, double mult, double minPct, double maxPct)
        {
            double d = Distance(price, atr, mult, minPct, maxPct);
            return NxMath.Ok(d) ? price - d : double.NaN;
        }

        public static double ShortStop(double price, double atr, double mult, double minPct, double maxPct)
        {
            double d = Distance(price, atr, mult, minPct, maxPct);
            return NxMath.Ok(d) ? price + d : double.NaN;
        }
    }

    public class NxResidualFit
    {
        public double Alpha = double.NaN, Beta = double.NaN;
        public List<double> Residuals = new List<double>();
        public bool Ok;
    }

    public static class NxResidual
    {
        /// <summary>Regression des rendements journaliers alignes de l action sur ceux du benchmark (fenetre n).</summary>
        public static NxResidualFit Fit(NxBarHistory stock, NxBarHistory bench, int n)
        {
            NxResidualFit f = new NxResidualFit();
            List<double> ra, rb;
            NxBarHistory.AlignedReturns(stock, bench, n, out ra, out rb, false);
            if (ra.Count < Math.Max(20, n / 2)) return f;
            NxOlsResult o = NxRegression.Simple(ra, rb);
            if (!o.Ok) return f;
            f.Alpha = o.Coef[0]; f.Beta = o.Coef[1];
            f.Residuals = o.Residuals.ToList();
            f.Ok = true;
            return f;
        }

        public static double Beta(NxBarHistory stock, NxBarHistory bench, int n)
        {
            NxResidualFit f = Fit(stock, bench, n);
            return f.Ok ? f.Beta : double.NaN;
        }
    }

    // =========================================================================
    //  FICHE 3 - Moteur multi-facteurs avec rotation (Ehsani-Linnainmaa)
    // =========================================================================
    public class NxMultiFactorResult
    {
        public Dictionary<string, double> Composite = new Dictionary<string, double>(StringComparer.OrdinalIgnoreCase);
        public Dictionary<string, double[]> Z = new Dictionary<string, double[]>(StringComparer.OrdinalIgnoreCase);  // [mom, value, qualite]
        public double[] Weights = { 1.0 / 3, 1.0 / 3, 1.0 / 3 };
        public double[] Factor12m = { double.NaN, double.NaN, double.NaN };
        public int Scored;
    }

    public class NxMultiFactorEngine
    {
        public static readonly string[] FactorNames = { "momentum", "value", "qualite" };

        public int MomLookback = 252, MomSkip = 21;
        public int BetaWindow = 252;
        public int RotationWindow = 252;
        public double UpMultiplier = 1.5, DownMultiplier = 0.5;
        public double[] BaseWeights = { 1.0 / 3, 1.0 / 3, 1.0 / 3 };
        public bool UseRotation = true;
        public int GrowthYears = 5;
        public double TercileFraction = 1.0 / 3.0;

        private readonly NxFundamentals fund;
        private readonly List<double>[] factorRets = { new List<double>(), new List<double>(), new List<double>() };
        private List<string>[] prevTop, prevBottom;
        private DateTime prevDay = DateTime.MinValue;

        public NxMultiFactorEngine(NxFundamentals fundamentals) { fund = fundamentals; }

        public int FactorHistory { get { return factorRets[0].Count; } }

        /// <summary>Calcule les scores du jour. stocks : symbole -> historique ; market : barometre (beta).</summary>
        public NxMultiFactorResult Update(DateTime day, Dictionary<string, NxBarHistory> stocks, NxBarHistory market)
        {
            NxMultiFactorResult res = new NxMultiFactorResult();
            // 1) Rendement long-short d hier des terciles de chaque facteur.
            if (prevTop != null && prevDay != DateTime.MinValue)
                for (int f = 0; f < 3; f++)
                {
                    double top = MeanReturn(prevTop[f], stocks, prevDay, day), bot = MeanReturn(prevBottom[f], stocks, prevDay, day);
                    if (NxMath.Ok(top) && NxMath.Ok(bot))
                    {
                        factorRets[f].Add(top - bot);
                        if (factorRets[f].Count > RotationWindow * 2) factorRets[f].RemoveAt(0);
                    }
                }

            // 2) Valeurs brutes.
            List<string> names = stocks.Keys.ToList();
            int n = names.Count;
            double[] mom = new double[n], val = new double[n], prof = new double[n], growth = new double[n], beta = new double[n], lev = new double[n];
            for (int i = 0; i < n; i++)
            {
                NxBarHistory h = stocks[names[i]];
                mom[i] = NxMomentum.Return12_1(h, MomLookback, MomSkip);
                val[i] = prof[i] = growth[i] = lev[i] = double.NaN;
                beta[i] = market != null ? NxResidual.Beta(h, market, BetaWindow) : double.NaN;
                NxFundamentalRow fr = fund != null ? fund.AsOf(names[i], day) : null;
                if (fr != null)
                {
                    double mcap = h.LastClose * fr.SharesOutstanding;
                    if (NxMath.Ok(mcap) && mcap > 0)
                        val[i] = fr.BookEquity > 0 ? fr.BookEquity / mcap : NxMath.SafeDiv(fr.NetIncome, mcap);   // B/M, repli E/P
                    prof[i] = fr.Profitability;
                    lev[i] = fr.Leverage;
                    NxFundamentalRow old = fund.AsOf(names[i], day.AddYears(-GrowthYears));
                    if (old != null && old != fr) growth[i] = fr.Profitability - old.Profitability;
                }
            }

            // 3) Normalisation : rang centre puis z-score.
            double[] zMom = NxMath.CenteredRankZ(mom), zVal = NxMath.CenteredRankZ(val);
            double[] zProf = NxMath.CenteredRankZ(prof), zGrowth = NxMath.CenteredRankZ(growth);
            double[] negBeta = beta.Select(b => NxMath.Ok(b) ? -b : double.NaN).ToArray();
            double[] negLev = lev.Select(l => NxMath.Ok(l) ? -l : double.NaN).ToArray();
            double[] zB = NxMath.CenteredRankZ(negBeta), zL = NxMath.CenteredRankZ(negLev);
            double[] safety = new double[n], qualRaw = new double[n];
            for (int i = 0; i < n; i++)
            {
                safety[i] = MeanOk(zB[i], zL[i]);
                qualRaw[i] = MeanOk(zProf[i], zGrowth[i], safety[i]);
            }
            double[] zQual = NxMath.CenteredRankZ(qualRaw);

            // 4) Poids avec rotation (rendement long-short 12 mois du facteur).
            double[] w = (double[])BaseWeights.Clone();
            for (int f = 0; f < 3; f++)
            {
                if (factorRets[f].Count >= RotationWindow)
                {
                    double cum = 1;
                    foreach (double r in factorRets[f].Skip(factorRets[f].Count - RotationWindow)) cum *= 1 + r;
                    res.Factor12m[f] = cum - 1;
                    if (UseRotation) w[f] *= cum - 1 > 0 ? UpMultiplier : DownMultiplier;
                }
            }
            double ws = w.Sum();
            for (int f = 0; f < 3; f++) w[f] = ws > 0 ? w[f] / ws : 1.0 / 3;
            res.Weights = w;

            // 5) Score composite (renormalise sur les facteurs disponibles).
            for (int i = 0; i < n; i++)
            {
                double[] z = { zMom[i], zVal[i], zQual[i] };
                res.Z[names[i]] = z;
                double s = 0, wsum = 0;
                for (int f = 0; f < 3; f++) if (NxMath.Ok(z[f])) { s += w[f] * z[f]; wsum += w[f]; }
                if (wsum > 0 && NxMath.Ok(z[0])) { res.Composite[names[i]] = s / wsum; res.Scored++; }
            }

            // 6) Terciles du jour pour le rendement factoriel de demain.
            prevTop = new List<string>[3]; prevBottom = new List<string>[3];
            double[][] zs = { zMom, zVal, zQual };
            for (int f = 0; f < 3; f++)
            {
                List<int> idx = Enumerable.Range(0, n).Where(i => NxMath.Ok(zs[f][i])).OrderByDescending(i => zs[f][i]).ToList();
                int k = Math.Max(1, (int)Math.Floor(idx.Count * TercileFraction));
                prevTop[f] = idx.Count >= 3 ? idx.Take(k).Select(i => names[i]).ToList() : new List<string>();
                prevBottom[f] = idx.Count >= 3 ? idx.Skip(idx.Count - k).Select(i => names[i]).ToList() : new List<string>();
            }
            prevDay = day;
            return res;
        }

        private static double MeanReturn(List<string> syms, Dictionary<string, NxBarHistory> stocks, DateTime from, DateTime to)
        {
            if (syms == null || syms.Count == 0) return double.NaN;
            List<double> r = new List<double>();
            foreach (string s in syms)
            {
                NxBarHistory h;
                if (!stocks.TryGetValue(s, out h)) continue;
                double p0 = h.CloseOnOrBefore(from), p1 = h.CloseOnOrBefore(to);
                if (NxMath.Ok(p0) && NxMath.Ok(p1) && p0 > 0) r.Add(p1 / p0 - 1);
            }
            return r.Count > 0 ? r.Average() : double.NaN;
        }

        private static double MeanOk(params double[] v)
        {
            double s = 0; int c = 0;
            foreach (double x in v) if (NxMath.Ok(x)) { s += x; c++; }
            return c > 0 ? s / c : double.NaN;
        }
    }
}
