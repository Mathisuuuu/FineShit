// =============================================================================
//  Nexus12_VolRegimeConditional.cs   (NinjaTrader 8 / NinjaScript)
//
//  FICHE 12 - Regime par volatilite realisee + modeles conditionnels (loaded123)
//  Alternative directe au module A (HMM). Moreira, Muir ; Daniel, Moskowitz.
//
//  REGLES
//   - Barometre : SPY pour les actions, BTC pour la crypto (une instance par
//     classe d actifs : regler "Barometre").
//   - Mesure : volatilite realisee 20 jours, annualisee.
//   - 3 regimes (basse / moyenne / haute) coupes aux terciles de la vol des 2
//     dernieres annees ; changement de regime seulement apres 5 jours
//     consecutifs au-dela du seuil (anti-clignotement).
//   - Chaque strategie a 3 jeux de parametres, chacun calibre en WALK-FORWARD
//     uniquement sur les jours de son regime : fenetre d entrainement 180 jours,
//     recalibrage tous les 30 jours (module C), grille momentum {3, 6, 12 mois}
//     et retour a la moyenne {z 1.5, 2.0, 2.5} ; critere = Sharpe des jours du
//     regime ; moins de 30 jours de ce regime -> parametres par defaut.
//   - Allocation (depart) : basse vol : momentum plein ; moyenne : momentum
//     75 % ; haute : momentum 25 % + retour a la moyenne actif.
//   - Momentum : long si rendement (L mois, hors dernier mois) > 0, revu en fin
//     de mois ou au changement de regime. Retour a la moyenne : long si z du
//     rendement 5 jours < -seuil ; sortie si z > 0 ou apres 5 jours.
//   - Taille : volatilite cible 12 % / N, puis module B ; stop ATR x3 [2-8 %].
//
//  Point d attention : 3 jeux de parametres triplent le risque de sur-ajustement ;
//  le rapport donne les trades PAR REGIME (30 minimum chacun, module C).
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
    public enum Nexus12RegimeSource { TercilesVol_Fiche12, Hmm_ModuleA }

    public class Nexus12VolRegimeConditional : NexusStrategyBase
    {
        private NxVolTercileRegime terciles;
        private NxHmmRegimeDetector hmm;
        private readonly Dictionary<DateTime, NxRegime> regimeByDay = new Dictionary<DateTime, NxRegime>();
        private readonly int[] momL = { 252, 252, 252 };          // index 0 calme, 1 neutre, 2 stress
        private readonly double[] mrZ = { 2.0, 2.0, 2.0 };
        private readonly Dictionary<string, int> momSig = new Dictionary<string, int>(StringComparer.OrdinalIgnoreCase);
        private readonly Dictionary<string, int> mrHeldSince = new Dictionary<string, int>(StringComparer.OrdinalIgnoreCase);
        private NxRegime lastRegime = NxRegime.Inconnu;
        private int lastCalibration = int.MinValue / 2, calibrations, transitions;
        private readonly int[] regimeDays = new int[3];
        private List<int> gridL;
        private List<double> gridZ;

        protected override void NxSetDefaults()
        {
            Name = "Nexus12_VolRegimeConditional";
            Description = "Fiche 12 - Regime par terciles de vol realisee 20 j (2 ans, anti-clignotement 5 j) ; momentum 100/75/25 % et retour a la moyenne en haute vol ; parametres par regime calibres en walk-forward.";
            Symbols = "SPY,QQQ,XLF,XLV,XLE,XLI,XLY,XLP,XLU,XLB,XLRE,XLC,AAPL,MSFT,NVDA,AMZN,GOOGL,META,JPM,JNJ,XOM,UNH,V,PG,HD";
            SizingMode = NxSizingMode.Natif;

            RegimeSource = Nexus12RegimeSource.TercilesVol_Fiche12;
            Barometer = "SPY";
            VixSymbol = "";
            RvWindowDays = 20;
            TercileLookbackDays = 504;
            ConfirmDays = 5;
            MomCalmPct = 100.0;
            MomNeutralPct = 75.0;
            MomStressPct = 25.0;
            MrCalmPct = 0.0;
            MrNeutralPct = 0.0;
            MrStressPct = 100.0;
            MomGrid = "63,126,252";
            MrGrid = "1.5,2.0,2.5";
            DefaultMomLookback = 252;
            DefaultMrZ = 2.0;
            SkipDays = 21;
            MrMaxHoldDays = 5;
            MrVolDays = 60;
            TrainDays = 180;
            RecalibrateDays = 30;
            MinRegimeDays = 30;
            TargetVolPct = 12.0;
            VolWindowDays = 126;
            AtrMultiplier = 3.0;
            StopMinPct = 2.0;
            StopMaxPct = 8.0;
            ResizeThresholdPct = 20.0;
        }

        protected override IEnumerable<string> NxRequiredReferences()
        {
            List<string> r = new List<string> { Barometer };
            if (!string.IsNullOrWhiteSpace(VixSymbol)) r.Add(VixSymbol);
            return r;
        }

        protected override void NxDataLoaded()
        {
            terciles = new NxVolTercileRegime { RvWindow = RvWindowDays, LookbackDays = TercileLookbackDays, ConfirmDays = ConfirmDays };
            hmm = new NxHmmRegimeDetector(!string.IsNullOrWhiteSpace(VixSymbol) && Sym(VixSymbol) != null);
            gridL = NxText.SplitList(MomGrid).Select(x => (int)NxCsv.ParseDouble(x)).Where(x => x > SkipDays + 5).ToList();
            gridZ = NxText.SplitList(MrGrid).Select(NxCsv.ParseDouble).Where(x => NxMath.Ok(x) && x > 0).ToList();
            for (int i = 0; i < 3; i++) { momL[i] = DefaultMomLookback; mrZ[i] = DefaultMrZ; }
        }

        private static int Idx(NxRegime r) { return r == NxRegime.Calme ? 0 : (r == NxRegime.Neutre ? 1 : 2); }

        // --- Signal de retour a la moyenne : z du rendement 5 jours.
        private double MrZAt(NxBarHistory h, int i)
        {
            if (i < MrVolDays + 6 || i >= h.Count) return double.NaN;
            double s2 = 0, s1 = 0;
            for (int k = i - MrVolDays + 1; k <= i; k++) { double r = h.LogReturnAt(k); s1 += r; s2 += r * r; }
            double m = s1 / MrVolDays, v = s2 / MrVolDays - m * m;
            if (!(v > 0)) return double.NaN;
            double r5 = Math.Log(h.Close[i] / h.Close[i - 5]);
            return r5 / (Math.Sqrt(v) * Math.Sqrt(5.0));
        }

        protected override void NxOnBatch(DateTime day)
        {
            NxSym baro = Sym(Barometer);
            if (baro == null) { NxOnce("nobaro", "Barometre introuvable : " + Barometer); return; }
            NxSym vix = string.IsNullOrWhiteSpace(VixSymbol) ? null : Sym(VixSymbol);
            terciles.Update(baro.Hist.LastClose);
            hmm.Update(baro.Hist.LastClose, vix != null ? vix.Hist.LastClose : double.NaN);
            NxRegime regime = RegimeSource == Nexus12RegimeSource.Hmm_ModuleA ? hmm.Regime : terciles.Regime;
            if (regime == NxRegime.Inconnu) return;
            regimeByDay[day] = regime;
            regimeDays[Idx(regime)]++;
            bool changed = regime != lastRegime && lastRegime != NxRegime.Inconnu;
            if (changed)
            {
                transitions++;
                Nx(string.Format(CultureInfo.InvariantCulture, "{0:yyyy-MM-dd} changement de regime {1} -> {2} | {3}", day, lastRegime, regime,
                    RegimeSource == Nexus12RegimeSource.Hmm_ModuleA ? hmm.Describe() : terciles.Describe()));
            }

            if (BatchCount - lastCalibration >= RecalibrateDays) { Calibrate(day); lastCalibration = BatchCount; }

            List<NxSym> traded = TradedSyms;
            int ri = Idx(regime);
            bool monthly = IsRebalanceDay(day, NxRebalance.Mensuel, baro);
            int nValid = traded.Count(s => s.Hist.Count > momL[ri] + 1);
            if (nValid == 0) { lastRegime = regime; return; }

            double allocMom = (ri == 0 ? MomCalmPct : ri == 1 ? MomNeutralPct : MomStressPct) / 100.0;
            double allocMr = (ri == 0 ? MrCalmPct : ri == 1 ? MrNeutralPct : MrStressPct) / 100.0;
            foreach (NxSym s in traded)
            {
                NxBarHistory h = s.Hist;
                if (h.Count < Math.Max(momL[ri], MrVolDays) + 7) continue;
                if (monthly || changed || !momSig.ContainsKey(s.Name))
                {
                    double m = h.ReturnOver(momL[ri], SkipDays);
                    momSig[s.Name] = NxMath.Ok(m) && m > 0 ? 1 : 0;
                }
                double z = MrZAt(h, h.Count - 1);
                int heldSince;
                bool inMr = mrHeldSince.TryGetValue(s.Name, out heldSince);
                if (inMr && (allocMr <= 0 || (NxMath.Ok(z) && z > 0) || BatchCount - heldSince >= MrMaxHoldDays)) { mrHeldSince.Remove(s.Name); inMr = false; }
                else if (!inMr && allocMr > 0 && NxMath.Ok(z) && z < -mrZ[ri]) { mrHeldSince[s.Name] = BatchCount; inMr = true; }

                double baseW = NxMomentum.InverseVolWeight(h, TargetVolPct / 100.0, VolWindowDays, nValid, 0);
                if (!NxMath.Ok(baseW)) continue;
                double frac = baseW * (allocMom * momSig[s.Name] + (inMr ? allocMr : 0.0));
                int q = 0;
                string det = "";
                if (frac > 0) q = SizeQty(s, frac, s.LastPrice, double.NaN, out det);
                int cur = s.TargetQty;
                bool resize = (q == 0) != (cur == 0) || (cur > 0 && Math.Abs(q - cur) > ResizeThresholdPct / 100.0 * cur);
                if (!resize) continue;
                double stop = q > 0 ? NxAtrStop.LongStop(s.LastPrice, h.Atr, AtrMultiplier, StopMinPct / 100.0, StopMaxPct / 100.0) : double.NaN;
                if (q > 0 && s.Qty > 0 && NxMath.Ok(s.StopPrice)) stop = Math.Max(stop, s.StopPrice);
                if (s.Qty == 0) s.Regime = regime.ToString();
                SetTarget(s, q, stop, string.Format(CultureInfo.InvariantCulture, "regime {0} : mom {1}x{2:P0} (L={3}) + MR {4}x{5:P0} (z={6:F2}, seuil {7})",
                    regime, momSig[s.Name], allocMom, momL[ri], inMr ? 1 : 0, allocMr, z, mrZ[ri]));
            }
            lastRegime = regime;
        }

        // ---------------------------------------------------------------------
        //  Calibrage walk-forward par regime (jours du regime seulement)
        // ---------------------------------------------------------------------
        private void Calibrate(DateTime day)
        {
            List<NxSym> traded = TradedSyms.Where(s => s.Hist.Count > TrainDays + 260).ToList();
            if (traded.Count == 0) return;
            List<DateTime> window = regimeByDay.Keys.Where(d => d <= day).OrderByDescending(d => d).Take(TrainDays).OrderBy(d => d).ToList();
            calibrations++;
            List<string> log = new List<string>();
            // z de la veille pre-calcule une seule fois (reutilise pour chaque regime et chaque seuil).
            Dictionary<NxSym, double[]> zPrev = new Dictionary<NxSym, double[]>();
            foreach (NxSym s in traded)
            {
                double[] z = new double[window.Count];
                for (int w = 0; w < window.Count; w++) { int i = s.Hist.IndexOf(window[w]); z[w] = i >= MrVolDays + 8 ? MrZAt(s.Hist, i - 1) : double.NaN; }
                zPrev[s] = z;
            }
            foreach (NxRegime r in new[] { NxRegime.Calme, NxRegime.Neutre, NxRegime.Stress })
            {
                int ri = Idx(r);
                HashSet<DateTime> rd = new HashSet<DateTime>(window.Where(d => regimeByDay[d] == r));
                if (rd.Count < MinRegimeDays)
                {
                    momL[ri] = DefaultMomLookback; mrZ[ri] = DefaultMrZ;
                    log.Add(r + ": " + rd.Count + " j < " + MinRegimeDays + " -> defaut");
                    continue;
                }
                double best = double.NegativeInfinity;
                foreach (int L in gridL)
                {
                    double sh = EvalMomentum(traded, window, rd, L);
                    if (NxMath.Ok(sh) && sh > best) { best = sh; momL[ri] = L; }
                }
                double bestZ = double.NegativeInfinity;
                foreach (double k in gridZ)
                {
                    double sh = EvalMeanReversion(traded, window, rd, k, zPrev);
                    if (NxMath.Ok(sh) && sh > bestZ) { bestZ = sh; mrZ[ri] = k; }
                }
                log.Add(string.Format(CultureInfo.InvariantCulture, "{0}: {1} j -> L={2} (SR {3:F2}), z={4} (SR {5:F2})", r, rd.Count, momL[ri], best, mrZ[ri], bestZ));
            }
            NxV(string.Format(CultureInfo.InvariantCulture, "{0:yyyy-MM-dd} calibrage walk-forward : {1}", day, string.Join(" | ", log)));
        }

        private double EvalMomentum(List<NxSym> syms, List<DateTime> window, HashSet<DateTime> regimeDaysSet, int L)
        {
            List<double> daily = new List<double>();
            foreach (DateTime d in window)
            {
                if (!regimeDaysSet.Contains(d)) continue;
                double sum = 0; int n = 0;
                foreach (NxSym s in syms)
                {
                    NxBarHistory h = s.Hist;
                    int i = h.IndexOf(d);
                    if (i < L + 2) continue;
                    double sig = h.Close[i - 1 - SkipDays] / h.Close[i - 1 - L] - 1;
                    sum += (sig > 0 ? 1 : 0) * (h.Close[i] / h.Close[i - 1] - 1); n++;
                }
                if (n > 0) daily.Add(sum / n);
            }
            return daily.Count >= MinRegimeDays ? NxValidation.SharpePerPeriod(daily) : double.NaN;
        }

        private double EvalMeanReversion(List<NxSym> syms, List<DateTime> window, HashSet<DateTime> regimeDaysSet, double k, Dictionary<NxSym, double[]> zPrevBySym)
        {
            Dictionary<DateTime, double> sum = new Dictionary<DateTime, double>();
            Dictionary<DateTime, int> cnt = new Dictionary<DateTime, int>();
            foreach (NxSym s in syms)
            {
                NxBarHistory h = s.Hist;
                int pos = 0, held = 0;
                double[] zs = zPrevBySym[s];
                for (int w = 0; w < window.Count; w++)
                {
                    DateTime d = window[w];
                    int i = h.IndexOf(d);
                    if (i < MrVolDays + 8) continue;
                    double zPrev = zs[w];
                    if (pos == 1 && (held >= MrMaxHoldDays || (NxMath.Ok(zPrev) && zPrev > 0))) { pos = 0; held = 0; }
                    else if (pos == 0 && NxMath.Ok(zPrev) && zPrev < -k) { pos = 1; held = 0; }
                    if (pos == 1) held++;
                    if (!regimeDaysSet.Contains(d)) continue;
                    double r = pos * (h.Close[i] / h.Close[i - 1] - 1);
                    double cur;
                    sum[d] = (sum.TryGetValue(d, out cur) ? cur : 0) + r;
                    int c;
                    cnt[d] = (cnt.TryGetValue(d, out c) ? c : 0) + 1;
                }
            }
            List<double> daily = sum.Keys.OrderBy(d => d).Select(d => sum[d] / cnt[d]).ToList();
            return daily.Count >= MinRegimeDays ? NxValidation.SharpePerPeriod(daily) : double.NaN;
        }

        protected override void NxReportExtras(List<string> lines)
        {
            int tot = regimeDays.Sum();
            lines.Add(string.Format(CultureInfo.InvariantCulture, "Source de regime : {0} | jours calme/neutre/stress : {1}/{2}/{3} ({4:P0}/{5:P0}/{6:P0}) | transitions {7} | calibrages {8}",
                RegimeSource, regimeDays[0], regimeDays[1], regimeDays[2], tot > 0 ? (double)regimeDays[0] / tot : 0, tot > 0 ? (double)regimeDays[1] / tot : 0,
                tot > 0 ? (double)regimeDays[2] / tot : 0, transitions, calibrations));
            lines.Add(string.Format(CultureInfo.InvariantCulture, "Parametres courants : calme L={0} z={1} | neutre L={2} z={3} | stress L={4} z={5}", momL[0], mrZ[0], momL[1], mrZ[1], momL[2], mrZ[2]));
            foreach (string r in new[] { "Calme", "Neutre", "Stress" })
            {
                List<NxTradeRecord> t = ClosedTrades.Where(x => x.Regime == r).ToList();
                lines.Add(string.Format(CultureInfo.InvariantCulture, "Trades ouverts en regime {0,-7}: {1,4} | PnL net {2,10:F2} | reussite {3:P0}{4}",
                    r, t.Count, t.Sum(x => x.NetPnl), t.Count > 0 ? (double)t.Count(x => x.NetPnl > 0) / t.Count : 0, t.Count < 30 ? "  <- moins de 30 trades : non valide (module C)" : ""));
            }
            lines.Add("Avantage vs HMM : pas de probabilite bloquee a 1.0, regle lisible, seuils sur terciles glissants.");
        }

        #region Proprietes
        [NinjaScriptProperty]
        [Display(Name = "Source du regime", Order = 1, GroupName = "01. Fiche 12 - Regime de vol")]
        public Nexus12RegimeSource RegimeSource { get; set; }

        [Display(Name = "Barometre", Description = "SPY pour les actions, BTCUSD pour la crypto.", Order = 2, GroupName = "01. Fiche 12 - Regime de vol")]
        public string Barometer { get; set; }

        [Display(Name = "VIX (HMM, optionnel)", Order = 3, GroupName = "01. Fiche 12 - Regime de vol")]
        public string VixSymbol { get; set; }

        [Range(5, 120)]
        [Display(Name = "Vol realisee sur (jours)", Order = 4, GroupName = "01. Fiche 12 - Regime de vol")]
        public int RvWindowDays { get; set; }

        [Range(60, 5000)]
        [Display(Name = "Terciles sur (jours)", Order = 5, GroupName = "01. Fiche 12 - Regime de vol")]
        public int TercileLookbackDays { get; set; }

        [NinjaScriptProperty]
        [Range(1, 60)]
        [Display(Name = "Anti-clignotement (jours)", Order = 6, GroupName = "01. Fiche 12 - Regime de vol")]
        public int ConfirmDays { get; set; }

        [Range(0.0, 200.0)]
        [Display(Name = "Momentum en basse vol (%)", Order = 7, GroupName = "01. Fiche 12 - Regime de vol")]
        public double MomCalmPct { get; set; }

        [Range(0.0, 200.0)]
        [Display(Name = "Momentum en vol moyenne (%)", Order = 8, GroupName = "01. Fiche 12 - Regime de vol")]
        public double MomNeutralPct { get; set; }

        [Range(0.0, 200.0)]
        [Display(Name = "Momentum en haute vol (%)", Order = 9, GroupName = "01. Fiche 12 - Regime de vol")]
        public double MomStressPct { get; set; }

        [Range(0.0, 200.0)]
        [Display(Name = "Retour moyenne en basse vol (%)", Order = 10, GroupName = "01. Fiche 12 - Regime de vol")]
        public double MrCalmPct { get; set; }

        [Range(0.0, 200.0)]
        [Display(Name = "Retour moyenne en vol moyenne (%)", Order = 11, GroupName = "01. Fiche 12 - Regime de vol")]
        public double MrNeutralPct { get; set; }

        [Range(0.0, 200.0)]
        [Display(Name = "Retour moyenne en haute vol (%)", Order = 12, GroupName = "01. Fiche 12 - Regime de vol")]
        public double MrStressPct { get; set; }

        [Display(Name = "Grille momentum (jours)", Order = 13, GroupName = "01. Fiche 12 - Regime de vol")]
        public string MomGrid { get; set; }

        [Display(Name = "Grille retour moyenne (z)", Order = 14, GroupName = "01. Fiche 12 - Regime de vol")]
        public string MrGrid { get; set; }

        [Range(42, 1000)]
        [Display(Name = "Momentum par defaut (jours)", Order = 15, GroupName = "01. Fiche 12 - Regime de vol")]
        public int DefaultMomLookback { get; set; }

        [Range(0.5, 5.0)]
        [Display(Name = "Seuil z par defaut", Order = 16, GroupName = "01. Fiche 12 - Regime de vol")]
        public double DefaultMrZ { get; set; }

        [Range(0, 252)]
        [Display(Name = "Momentum : mois exclu (jours)", Order = 17, GroupName = "01. Fiche 12 - Regime de vol")]
        public int SkipDays { get; set; }

        [Range(1, 60)]
        [Display(Name = "Retour moyenne : detention max (jours)", Order = 18, GroupName = "01. Fiche 12 - Regime de vol")]
        public int MrMaxHoldDays { get; set; }

        [Range(10, 500)]
        [Display(Name = "Retour moyenne : vol sur (jours)", Order = 19, GroupName = "01. Fiche 12 - Regime de vol")]
        public int MrVolDays { get; set; }

        [NinjaScriptProperty]
        [Range(30, 3000)]
        [Display(Name = "Walk-forward : entrainement (jours)", Order = 20, GroupName = "01. Fiche 12 - Regime de vol")]
        public int TrainDays { get; set; }

        [NinjaScriptProperty]
        [Range(1, 500)]
        [Display(Name = "Walk-forward : recalibrage (jours)", Order = 21, GroupName = "01. Fiche 12 - Regime de vol")]
        public int RecalibrateDays { get; set; }

        [Range(5, 1000)]
        [Display(Name = "Jours min par regime", Order = 22, GroupName = "01. Fiche 12 - Regime de vol")]
        public int MinRegimeDays { get; set; }

        [Range(1.0, 100.0)]
        [Display(Name = "Volatilite cible (%)", Order = 23, GroupName = "01. Fiche 12 - Regime de vol")]
        public double TargetVolPct { get; set; }

        [Range(20, 756)]
        [Display(Name = "Fenetre de vol (jours)", Order = 24, GroupName = "01. Fiche 12 - Regime de vol")]
        public int VolWindowDays { get; set; }

        [Range(0.5, 20.0)]
        [Display(Name = "Stop : multiplicateur ATR(14)", Order = 25, GroupName = "01. Fiche 12 - Regime de vol")]
        public double AtrMultiplier { get; set; }

        [Range(0.1, 50.0)]
        [Display(Name = "Stop : borne basse (%)", Order = 26, GroupName = "01. Fiche 12 - Regime de vol")]
        public double StopMinPct { get; set; }

        [Range(0.1, 50.0)]
        [Display(Name = "Stop : borne haute (%)", Order = 27, GroupName = "01. Fiche 12 - Regime de vol")]
        public double StopMaxPct { get; set; }

        [Range(1.0, 100.0)]
        [Display(Name = "Seuil de redimensionnement (%)", Order = 28, GroupName = "01. Fiche 12 - Regime de vol")]
        public double ResizeThresholdPct { get; set; }
        #endregion
    }
}
