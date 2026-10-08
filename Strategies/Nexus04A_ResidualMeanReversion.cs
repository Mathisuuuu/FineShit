// =============================================================================
//  Nexus04A_ResidualMeanReversion.cs   (NinjaTrader 8 / NinjaScript)
//
//  FICHE 4 - VARIANTE A : retour a la moyenne court terme sur ACTIONS
//  [arXiv] 2402.08233 (cadre Avellaneda-Lee) ; [SSRN] Blitz, Huij, Lansdorp, Verbeek.
//
//  MODE QUOTIDIEN (Avellaneda-Lee)
//   - Residu : rendement de l action - beta x rendement de son ETF sectoriel
//     (ou SPY), regression sur 60 jours.
//   - Residu cumule X ajuste en Ornstein-Uhlenbeck (AR(1)) :
//     s-score = (X - m) / sigma_eq ; moyennes m centrees sur l univers (option).
//   - Filtre : demi-vie < 15 jours.
//   - Entree long : s < -1.25. Sortie : s > -0.5, ou 10 jours, ou stop ATR.
//   - Taille : demi-Kelly, 3 % max du bankroll (module B).
//
//  MODE MENSUEL (variante simple de Blitz et al.)
//   - Residus d un modele a 3 facteurs (Fama-French, fichier Nexus\data\
//     ff_factors.csv) estime sur 36 mois ; a defaut, modele de marche (SPY).
//   - Residu du dernier mois standardise ; achat du decile le plus perdant,
//     detention 1 mois. Point mort rapporte : ~0.56 % de frais aller-retour.
//
//  Long seulement. Les ETF sectoriels de reference sont charges mais non trades.
// =============================================================================

#region Using declarations
using System;
using System.Collections.Generic;
using System.ComponentModel.DataAnnotations;
using System.Globalization;
using System.Linq;
using NinjaTrader.Cbi;
using NinjaTrader.Data;
using NinjaTrader.NinjaScript;
using NinjaTrader.NinjaScript.AddOns.Nexus;
#endregion

namespace NinjaTrader.NinjaScript.Strategies
{
    public enum Nexus04AMode { QuotidienOU, MensuelDecile }

    public class Nexus04AResidualMeanReversion : NexusStrategyBase
    {
        private Dictionary<string, string> benchMap;
        private NxFactorFile factors;
        private readonly List<double> entryScores = new List<double>();
        private readonly List<double> entryHalfLives = new List<double>();
        private int validFitsTotal, fitDays, monthlyRebalances;

        protected override void NxSetDefaults()
        {
            Name = "Nexus04A_ResidualMeanReversion";
            Description = "Fiche 4A - Retour a la moyenne du residu sectoriel (s-score OU Avellaneda-Lee, demi-vie < 15 j) ou variante mensuelle decile (Blitz et al.).";
            Symbols = "AAPL,MSFT,NVDA,AMZN,GOOGL,META,JPM,JNJ,XOM,UNH,V,PG,HD";
            SizingMode = NxSizingMode.DemiKelly;

            Mode = Nexus04AMode.QuotidienOU;
            SectorMap = "AAPL=XLK;MSFT=XLK;NVDA=XLK;AMZN=XLY;GOOGL=XLC;META=XLC;JPM=XLF;JNJ=XLV;XOM=XLE;UNH=XLV;V=XLF;PG=XLP;HD=XLY";
            DefaultBenchmark = "SPY";
            RegressionDays = 60;
            MaxHalfLifeDays = 15.0;
            EntryS = -1.25;
            ExitS = -0.5;
            MaxHoldDays = 10;
            CenterMeans = true;
            AtrMultiplier = 3.0;
            StopMinPct = 2.0;
            StopMaxPct = 8.0;
            FactorsFile = "ff_factors.csv";
            EstimationMonths = 36;
            DecilePct = 10.0;
        }

        protected override IEnumerable<string> NxRequiredReferences()
        {
            List<string> r = new List<string> { DefaultBenchmark };
            r.AddRange(NxText.ParseMap(SectorMap).Values);
            return r.Distinct(StringComparer.OrdinalIgnoreCase);
        }

        protected override void NxDataLoaded()
        {
            benchMap = NxText.ParseMap(SectorMap);
            if (Mode == Nexus04AMode.MensuelDecile)
            {
                factors = new NxFactorFile();
                string msg;
                factors.Load(NxPaths.Resolve(FactorsFile, NxPaths.Data), out msg);
                Nx("Facteurs : " + msg + (factors.Loaded ? "" : " -> repli sur le modele de marche (" + DefaultBenchmark + ")"));
            }
        }

        private NxSym BenchOf(NxSym s)
        {
            string b;
            NxSym bs = null;
            if (benchMap.TryGetValue(s.Name, out b)) bs = Sym(b);
            return bs ?? Sym(DefaultBenchmark);
        }

        protected override void NxOnBatch(DateTime day)
        {
            if (Mode == Nexus04AMode.QuotidienOU) DailyOu(day);
            else Monthly(day);
        }

        // ---------------------------------------------------------------------
        //  Mode quotidien : s-score OU
        // ---------------------------------------------------------------------
        private void DailyOu(DateTime day)
        {
            Dictionary<NxSym, NxOuFit> fits = new Dictionary<NxSym, NxOuFit>();
            Dictionary<NxSym, double> lastX = new Dictionary<NxSym, double>();
            foreach (NxSym s in TradedSyms)
            {
                NxSym bench = BenchOf(s);
                if (bench == null || bench == s) continue;
                NxResidualFit rf = NxResidual.Fit(s.Hist, bench.Hist, RegressionDays);
                if (!rf.Ok || rf.Residuals.Count < RegressionDays / 2) continue;
                List<double> x = new List<double>(rf.Residuals.Count);
                double cum = 0;
                foreach (double e in rf.Residuals) { cum += NxMath.Ok(e) ? e : 0; x.Add(cum); }
                NxOuFit ou = NxOu.Fit(x);
                if (!ou.Valid) continue;
                fits[s] = ou;
                lastX[s] = x[x.Count - 1];
            }
            if (fits.Count > 0) { fitDays++; validFitsTotal += fits.Count; }
            double mAvg = CenterMeans && fits.Count > 1 ? fits.Values.Average(f => f.Mean) : 0.0;

            foreach (NxSym s in TradedSyms)
            {
                NxOuFit ou;
                bool has = fits.TryGetValue(s, out ou);
                double score = has ? (lastX[s] - (ou.Mean - mAvg)) / ou.SigmaEq : double.NaN;

                if (s.Qty > 0 || s.TargetQty > 0)
                {
                    if (s.Qty > 0 && has && score > ExitS) SetTarget(s, 0, double.NaN, string.Format(CultureInfo.InvariantCulture, "s-score {0:F2} > {1:F2}", score, ExitS));
                    else if (s.Qty > 0 && s.BarsHeld >= MaxHoldDays) SetTarget(s, 0, double.NaN, MaxHoldDays + " jours ecoules");
                    continue;
                }
                if (!has || s.StoppedOut && s.StoppedTime.Date == day.Date) continue;
                if (ou.HalfLife >= MaxHalfLifeDays || score >= EntryS) continue;

                string det;
                int q = SizeQty(s, MaxTradePct / 100.0, s.LastPrice, double.NaN, out det);
                double stop = NxAtrStop.LongStop(s.LastPrice, s.Hist.Atr, AtrMultiplier, StopMinPct / 100.0, StopMaxPct / 100.0);
                string why = string.Format(CultureInfo.InvariantCulture, "s-score {0:F2} < {1:F2}, demi-vie {2:F1} j", score, EntryS, ou.HalfLife);
                SetTarget(s, q, stop, why);
                NxSignal(NowNt, s.Name, "residu_entree", why + " | " + det);
                if (q > 0) { entryScores.Add(score); entryHalfLives.Add(ou.HalfLife); }
            }
        }

        // ---------------------------------------------------------------------
        //  Mode mensuel : decile perdant des residus a 3 facteurs
        // ---------------------------------------------------------------------
        private void Monthly(DateTime day)
        {
            NxSym mkt = Sym(DefaultBenchmark);
            if (mkt == null || mkt.Hist.Count < 21 * (EstimationMonths + 2)) return;
            if (!IsRebalanceDay(day, NxRebalance.Mensuel, mkt)) return;
            monthlyRebalances++;

            List<KeyValuePair<DateTime, double>> mktM = NxPanel.MonthlyReturns(mkt.Hist, EstimationMonths + 1);
            Dictionary<DateTime, double> mktByMonth = mktM.ToDictionary(kv => kv.Key, kv => kv.Value);
            Dictionary<NxSym, double> stdResid = new Dictionary<NxSym, double>();
            foreach (NxSym s in TradedSyms)
            {
                List<KeyValuePair<DateTime, double>> m = NxPanel.MonthlyReturns(s.Hist, EstimationMonths + 1);
                if (m.Count < EstimationMonths + 1) continue;
                List<double> y = new List<double>();
                List<double[]> X = new List<double[]>();
                foreach (KeyValuePair<DateTime, double> kv in m)
                {
                    double[] f;
                    if (factors != null && factors.Loaded && factors.TryGetMonth(kv.Key.Year, kv.Key.Month, out f))
                    {
                        y.Add(kv.Value - f[3]);
                        X.Add(new[] { f[0], f[1], f[2] });
                    }
                    else if (mktByMonth.ContainsKey(kv.Key))
                    {
                        y.Add(kv.Value);
                        X.Add(new[] { mktByMonth[kv.Key] });
                    }
                }
                if (y.Count < EstimationMonths / 2 + 2 || X.Select(r => r.Length).Distinct().Count() != 1) continue;
                int last = y.Count - 1;
                NxOlsResult o = NxRegression.Multi(y.Take(last).ToArray(), X.Take(last).ToArray(), true);
                if (!o.Ok) continue;
                double fit = o.Coef[0];
                for (int k = 0; k < X[last].Length; k++) fit += o.Coef[k + 1] * X[last][k];
                double sd = Math.Sqrt(o.Rss / Math.Max(1, o.N - o.K));
                if (sd > 0) stdResid[s] = (y[last] - fit) / sd;
            }
            if (stdResid.Count < 3) return;
            int k10 = Math.Max(1, (int)Math.Round(stdResid.Count * DecilePct / 100.0));
            HashSet<NxSym> losers = new HashSet<NxSym>(stdResid.OrderBy(kv => kv.Value).Take(k10).Select(kv => kv.Key));
            Nx(string.Format(CultureInfo.InvariantCulture, "{0:yyyy-MM-dd} decile perdant ({1} titres, modele {2}) : {3}", day, k10,
                factors != null && factors.Loaded ? "3 facteurs" : "marche", string.Join(", ", losers.Select(x => x.Name + " " + stdResid[x].ToString("F2", CultureInfo.InvariantCulture)))));
            foreach (NxSym s in TradedSyms)
            {
                if (losers.Contains(s))
                {
                    string det;
                    int q = SizeQty(s, MaxTradePct / 100.0, s.LastPrice, double.NaN, out det);
                    double stop = NxAtrStop.LongStop(s.LastPrice, s.Hist.Atr, AtrMultiplier, StopMinPct / 100.0, StopMaxPct / 100.0);
                    SetTarget(s, q, stop, "residu mensuel standardise " + stdResid[s].ToString("F2", CultureInfo.InvariantCulture));
                    entryScores.Add(stdResid[s]);
                }
                else if (s.Qty != 0 || s.TargetQty != 0) SetTarget(s, 0, double.NaN, "fin de detention mensuelle");
            }
        }

        protected override void NxReportExtras(List<string> lines)
        {
            lines.Add("Mode : " + Mode);
            if (Mode == Nexus04AMode.QuotidienOU)
            {
                lines.Add(string.Format(CultureInfo.InvariantCulture, "Ajustements OU valides : {0:F1} par jour en moyenne sur {1} jours",
                    fitDays > 0 ? (double)validFitsTotal / fitDays : 0, fitDays));
                if (entryScores.Count > 0)
                    lines.Add(string.Format(CultureInfo.InvariantCulture, "Entrees : {0} | s-score moyen {1:F2} | demi-vie mediane {2:F1} j",
                        entryScores.Count, entryScores.Average(), NxMath.Median(entryHalfLives)));
            }
            else lines.Add(string.Format(CultureInfo.InvariantCulture, "Reequilibrages mensuels : {0} | selections : {1}", monthlyRebalances, entryScores.Count));
            if (ClosedTrades.Count > 0)
            {
                double avgGross = ClosedTrades.Average(t => t.GrossReturn);
                lines.Add(string.Format(CultureInfo.InvariantCulture, "Avantage brut moyen par trade : {0:P3} (point mort Blitz et al. ~0.56 % aller-retour)", avgGross));
            }
        }

        #region Proprietes
        [NinjaScriptProperty]
        [Display(Name = "Mode", Order = 1, GroupName = "01. Fiche 4A - Residu actions")]
        public Nexus04AMode Mode { get; set; }

        [Display(Name = "ETF sectoriel par action", Description = "SYMBOLE=ETF separes par des points-virgules.", Order = 2, GroupName = "01. Fiche 4A - Residu actions")]
        public string SectorMap { get; set; }

        [Display(Name = "Benchmark par defaut", Order = 3, GroupName = "01. Fiche 4A - Residu actions")]
        public string DefaultBenchmark { get; set; }

        [NinjaScriptProperty]
        [Range(20, 500)]
        [Display(Name = "Regression (jours)", Order = 4, GroupName = "01. Fiche 4A - Residu actions")]
        public int RegressionDays { get; set; }

        [NinjaScriptProperty]
        [Range(1.0, 250.0)]
        [Display(Name = "Demi-vie max (jours)", Order = 5, GroupName = "01. Fiche 4A - Residu actions")]
        public double MaxHalfLifeDays { get; set; }

        [NinjaScriptProperty]
        [Range(-10.0, 0.0)]
        [Display(Name = "Entree : s-score <", Order = 6, GroupName = "01. Fiche 4A - Residu actions")]
        public double EntryS { get; set; }

        [NinjaScriptProperty]
        [Range(-10.0, 10.0)]
        [Display(Name = "Sortie : s-score >", Order = 7, GroupName = "01. Fiche 4A - Residu actions")]
        public double ExitS { get; set; }

        [NinjaScriptProperty]
        [Range(1, 250)]
        [Display(Name = "Detention max (jours)", Order = 8, GroupName = "01. Fiche 4A - Residu actions")]
        public int MaxHoldDays { get; set; }

        [Display(Name = "Centrer les moyennes m (A-L)", Order = 9, GroupName = "01. Fiche 4A - Residu actions")]
        public bool CenterMeans { get; set; }

        [Range(0.5, 20.0)]
        [Display(Name = "Stop : multiplicateur ATR(14)", Order = 10, GroupName = "01. Fiche 4A - Residu actions")]
        public double AtrMultiplier { get; set; }

        [Range(0.1, 50.0)]
        [Display(Name = "Stop : borne basse (%)", Order = 11, GroupName = "01. Fiche 4A - Residu actions")]
        public double StopMinPct { get; set; }

        [Range(0.1, 50.0)]
        [Display(Name = "Stop : borne haute (%)", Order = 12, GroupName = "01. Fiche 4A - Residu actions")]
        public double StopMaxPct { get; set; }

        [Display(Name = "Mensuel : fichier de facteurs", Description = "Format Ken French (date, mkt_rf, smb, hml, rf).", Order = 13, GroupName = "01. Fiche 4A - Residu actions")]
        public string FactorsFile { get; set; }

        [Range(12, 120)]
        [Display(Name = "Mensuel : estimation (mois)", Order = 14, GroupName = "01. Fiche 4A - Residu actions")]
        public int EstimationMonths { get; set; }

        [Range(1.0, 50.0)]
        [Display(Name = "Mensuel : decile achete (%)", Order = 15, GroupName = "01. Fiche 4A - Residu actions")]
        public double DecilePct { get; set; }
        #endregion
    }
}
