// =============================================================================
//  Nexus14_StrictSwing.cs   (NinjaTrader 8 / NinjaScript)
//
//  FICHE 14 - Swing a conditions strictes (pigorg01)
//  Acheter un repli court terme, mais seulement dans une tendance de fond
//  haussiere : la tendance (fiche 1) donne la direction, le retour a la moyenne
//  court terme (fiche 4) donne le point d entree. [SSRN] Moskowitz-Ooi-Pedersen ;
//  [SSRN] Blitz, Huij, Lansdorp, Verbeek.
//
//  CONDITIONS (toutes requises)
//   1. Tendance de fond : rendement 12-1 > 0
//   2. Tendance moyenne : cloture > moyenne mobile 200 jours
//   3. Repli : rendement 5 jours dans le decile le plus bas de l univers
//      (brut, ou residuel corrige du marche - "tester les deux")
//   4. Liquidite : volume moyen 20 j >= 5 M$ ET spread <= 0.05 % (le spread
//      n est mesurable qu en temps reel)
//   5. Regime : pas de regime "haute volatilite" (fiche 12 ou module A)
//   6. Pas de resultat trimestriel dans les 3 prochains jours
//  ENTREE : ordre LIMITE a l ouverture suivante (cloture de la veille), valable
//  une seance, seulement si les 6 conditions sont remplies.
//  SORTIE : cloture au-dessus de la moyenne mobile 5 jours, ou 10 jours.
//  STOP : ATR(14) x 2.5, borne a [2 % ; 8 %]. TAILLE : demi-Kelly, 3 % max.
//
//  OBJECTIF DE FREQUENCE : quelques trades par mois sur 25 symboles ; plus de
//  2 par semaine = conditions pas assez strictes (alerte dans le journal).
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
    public enum Nexus14Pullback { RendementBrut, Residuel }
    public enum Nexus14Regime { Aucun, TercilesVol_Fiche12, Hmm_ModuleA }

    public class Nexus14StrictSwing : NexusStrategyBase
    {
        private NxVolTercileRegime terciles;
        private NxHmmRegimeDetector hmm;
        private NxEarningsCalendar earnings;
        private readonly int[] failCount = new int[7];
        private readonly List<DateTime> entryDays = new List<DateTime>();
        private int candidatesSeen, entriesSubmitted, exitsSma, exitsTime, frequencyAlerts;

        protected override void NxSetDefaults()
        {
            Name = "Nexus14_StrictSwing";
            Description = "Fiche 14 - Repli (decile 5 j) dans une tendance haussiere (12-1 > 0, > MM200), liquidite, pas de haute vol ni de resultats < 3 j ; limite a l ouverture, sortie > MM5 ou 10 j, stop ATR x2.5.";
            Symbols = "SPY,QQQ,XLF,XLV,XLE,XLI,XLY,XLP,XLU,XLB,XLRE,XLC,AAPL,MSFT,NVDA,AMZN,GOOGL,META,JPM,JNJ,XOM,UNH,V,PG,HD";
            SizingMode = NxSizingMode.DemiKelly;

            MomLookbackDays = 252;
            SkipDays = 21;
            SmaLongDays = 200;
            PullbackDays = 5;
            PullbackDecilePct = 10.0;
            PullbackMode = Nexus14Pullback.RendementBrut;
            BetaDays = 60;
            MinDollarVolume = 5000000;
            MaxSpreadPct = 0.05;
            RegimeSource = Nexus14Regime.TercilesVol_Fiche12;
            Barometer = "SPY";
            VixSymbol = "";
            EarningsFile = "earnings.csv";
            EarningsDays = 3;
            ExcludeIfNoEarningsData = true;
            LimitOffsetPct = 0.0;
            ExitSmaDays = 5;
            MaxHoldDays = 10;
            AtrMultiplier = 2.5;
            StopMinPct = 2.0;
            StopMaxPct = 8.0;
            MaxTradesPerWeek = 2.0;
        }

        protected override IEnumerable<string> NxRequiredReferences()
        {
            List<string> r = new List<string> { Barometer };
            if (!string.IsNullOrWhiteSpace(VixSymbol)) r.Add(VixSymbol);
            return r;
        }

        protected override void NxDataLoaded()
        {
            terciles = new NxVolTercileRegime();
            hmm = new NxHmmRegimeDetector(!string.IsNullOrWhiteSpace(VixSymbol) && Sym(VixSymbol) != null);
            earnings = new NxEarningsCalendar();
            string msg;
            earnings.Load(NxPaths.Resolve(EarningsFile, NxPaths.Data), out msg);
            Nx("Resultats : " + msg + (earnings.Loaded ? "" : " -> condition 6 IGNOREE (aucun fichier)"));
        }

        protected override void NxOnBatch(DateTime day)
        {
            NxSym baro = Sym(Barometer);
            NxSym vix = string.IsNullOrWhiteSpace(VixSymbol) ? null : Sym(VixSymbol);
            if (baro != null)
            {
                terciles.Update(baro.Hist.LastClose);
                hmm.Update(baro.Hist.LastClose, vix != null ? vix.Hist.LastClose : double.NaN);
            }
            NxRegime regime = RegimeSource == Nexus14Regime.Hmm_ModuleA ? hmm.Regime : (RegimeSource == Nexus14Regime.TercilesVol_Fiche12 ? terciles.Regime : NxRegime.Calme);
            List<NxSym> traded = TradedSyms;

            // --- Sorties.
            foreach (NxSym s in traded)
            {
                if (s.Qty <= 0) continue;
                double sma5 = s.Hist.Sma(ExitSmaDays);
                if (NxMath.Ok(sma5) && s.Hist.LastClose > sma5) { SetTarget(s, 0, double.NaN, "cloture > MM" + ExitSmaDays); exitsSma++; }
                else if (s.BarsHeld >= MaxHoldDays) { SetTarget(s, 0, double.NaN, MaxHoldDays + " jours ecoules"); exitsTime++; }
            }

            // --- Condition 3 : repli dans le decile le plus bas (brut ou residuel).
            Dictionary<NxSym, double> pb = new Dictionary<NxSym, double>();
            double rMkt = baro != null ? baro.Hist.ReturnOver(PullbackDays, 0) : double.NaN;
            foreach (NxSym s in traded)
            {
                double r5 = s.Hist.ReturnOver(PullbackDays, 0);
                if (!NxMath.Ok(r5)) continue;
                if (PullbackMode == Nexus14Pullback.Residuel)
                {
                    double beta = baro != null && baro != s ? NxResidual.Beta(s.Hist, baro.Hist, BetaDays) : double.NaN;
                    if (!NxMath.Ok(beta) || !NxMath.Ok(rMkt)) continue;
                    r5 -= beta * rMkt;
                }
                pb[s] = r5;
            }
            if (pb.Count < 5) return;
            double threshold = NxMath.Quantile(pb.Values, PullbackDecilePct / 100.0);

            foreach (NxSym s in traded)
            {
                if (s.Qty != 0 || s.TargetQty != 0 || !pb.ContainsKey(s)) continue;
                NxBarHistory h = s.Hist;
                if (h.Count < Math.Max(MomLookbackDays, SmaLongDays) + 2) continue;
                candidatesSeen++;
                double mom = h.ReturnOver(MomLookbackDays, SkipDays);
                double sma = h.Sma(SmaLongDays);
                double adv = h.AvgDollarVolume(20);
                double spr = LiveSpreadPct(s);
                int fail = 0;
                if (!(NxMath.Ok(mom) && mom > 0)) fail = 1;
                else if (!(h.LastClose > sma)) fail = 2;
                else if (!(pb[s] <= threshold)) fail = 3;
                else if (!(adv >= MinDollarVolume) || (NxMath.Ok(spr) && spr > MaxSpreadPct / 100.0)) fail = 4;
                else if (regime == NxRegime.Stress || (RegimeSource != Nexus14Regime.Aucun && regime == NxRegime.Inconnu)) fail = 5;
                else if (EarningsBlock(s, day)) fail = 6;
                failCount[fail]++;
                if (fail != 0) continue;

                double limit = RoundPrice(s, h.LastClose * (1 - LimitOffsetPct / 100.0));
                string det;
                int q = SizeQty(s, MaxTradePct / 100.0, limit, double.NaN, out det);
                double stop = NxAtrStop.LongStop(limit, h.Atr, AtrMultiplier, StopMinPct / 100.0, StopMaxPct / 100.0);
                string why = string.Format(CultureInfo.InvariantCulture, "6 conditions : 12-1 {0:P1}, > MM{1}, repli {2:P2} <= decile {3:P2}, ADV {4:F0}, regime {5}",
                    mom, SmaLongDays, pb[s], threshold, adv, regime);
                SetTarget(s, q, stop, why, OrderType.Limit, limit, 1);
                NxSignal(NowNt, s.Name, "swing_entree", why + " | " + det);
                if (q > 0) { entriesSubmitted++; entryDays.Add(day); }
            }

            // --- Controle de frequence (4 dernieres semaines).
            int recent = entryDays.Count(d => (day - d).TotalDays <= 28);
            if (recent / 4.0 > MaxTradesPerWeek)
            {
                frequencyAlerts++;
                NxOnce("freq" + day.ToString("yyyyMM"), string.Format(CultureInfo.InvariantCulture,
                    "{0:yyyy-MM-dd} {1} entrees sur 4 semaines (> {2}/semaine) : conditions PAS ASSEZ STRICTES (fiche 14).", day, recent, MaxTradesPerWeek));
            }
        }

        private bool EarningsBlock(NxSym s, DateTime day)
        {
            if (!earnings.Loaded) return false;                         // aucun fichier : condition ignoree (annonce au chargement)
            if (s.Class == NxAssetClass.Etf) return false;               // pas de resultats trimestriels pour un ETF
            if (!earnings.HasData(s.Name)) return ExcludeIfNoEarningsData;
            return earnings.Within(s.Name, day, EarningsDays);
        }

        protected override void NxReportExtras(List<string> lines)
        {
            lines.Add(string.Format(CultureInfo.InvariantCulture, "Repli : {0} | regime : {1} | candidats examines {2} | entrees soumises {3} | sorties MM{4} {5}, temps {6}",
                PullbackMode, RegimeSource, candidatesSeen, entriesSubmitted, ExitSmaDays, exitsSma, exitsTime));
            lines.Add(string.Format(CultureInfo.InvariantCulture, "Rejets : 1-tendance {0} | 2-MM200 {1} | 3-repli {2} | 4-liquidite {3} | 5-regime {4} | 6-resultats {5} | acceptes {6}",
                failCount[1], failCount[2], failCount[3], failCount[4], failCount[5], failCount[6], failCount[0]));
            if (EquityDays.Count > 1)
            {
                double weeks = Math.Max(1, (EquityDays[EquityDays.Count - 1] - EquityDays[0]).TotalDays / 7.0);
                lines.Add(string.Format(CultureInfo.InvariantCulture, "Frequence : {0:F2} entrees/semaine (objectif : quelques-unes par mois ; alertes > {1}/sem : {2})",
                    entriesSubmitted / weeks, MaxTradesPerWeek, frequencyAlerts));
            }
            lines.Add("Rappel (Blitz et al.) : le retournement sur rendements bruts est faible depuis 1990 ; relancer en mode Residuel pour comparer.");
            lines.Add("Peu de trades : prevoir plusieurs mois de paper avant 30 trades fermes.");
        }

        #region Proprietes
        [NinjaScriptProperty]
        [Range(42, 1000)]
        [Display(Name = "1. Tendance : fenetre (jours)", Order = 1, GroupName = "01. Fiche 14 - Swing strict")]
        public int MomLookbackDays { get; set; }

        [Range(0, 252)]
        [Display(Name = "1. Tendance : mois exclu (jours)", Order = 2, GroupName = "01. Fiche 14 - Swing strict")]
        public int SkipDays { get; set; }

        [NinjaScriptProperty]
        [Range(20, 500)]
        [Display(Name = "2. Moyenne mobile longue (jours)", Order = 3, GroupName = "01. Fiche 14 - Swing strict")]
        public int SmaLongDays { get; set; }

        [NinjaScriptProperty]
        [Range(1, 60)]
        [Display(Name = "3. Repli : horizon (jours)", Order = 4, GroupName = "01. Fiche 14 - Swing strict")]
        public int PullbackDays { get; set; }

        [NinjaScriptProperty]
        [Range(1.0, 50.0)]
        [Display(Name = "3. Repli : quantile bas (%)", Order = 5, GroupName = "01. Fiche 14 - Swing strict")]
        public double PullbackDecilePct { get; set; }

        [NinjaScriptProperty]
        [Display(Name = "3. Repli : mesure", Order = 6, GroupName = "01. Fiche 14 - Swing strict")]
        public Nexus14Pullback PullbackMode { get; set; }

        [Range(20, 500)]
        [Display(Name = "3. Residuel : beta sur (jours)", Order = 7, GroupName = "01. Fiche 14 - Swing strict")]
        public int BetaDays { get; set; }

        [Range(0, double.MaxValue)]
        [Display(Name = "4. Volume moyen 20 j min ($)", Order = 8, GroupName = "01. Fiche 14 - Swing strict")]
        public double MinDollarVolume { get; set; }

        [Range(0.0, 10.0)]
        [Display(Name = "4. Spread max (%)", Order = 9, GroupName = "01. Fiche 14 - Swing strict")]
        public double MaxSpreadPct { get; set; }

        [NinjaScriptProperty]
        [Display(Name = "5. Source du regime", Order = 10, GroupName = "01. Fiche 14 - Swing strict")]
        public Nexus14Regime RegimeSource { get; set; }

        [Display(Name = "5. Barometre", Order = 11, GroupName = "01. Fiche 14 - Swing strict")]
        public string Barometer { get; set; }

        [Display(Name = "5. VIX (HMM, optionnel)", Order = 12, GroupName = "01. Fiche 14 - Swing strict")]
        public string VixSymbol { get; set; }

        [Display(Name = "6. Fichier des resultats", Order = 13, GroupName = "01. Fiche 14 - Swing strict")]
        public string EarningsFile { get; set; }

        [Range(0, 30)]
        [Display(Name = "6. Pas de resultats sous (jours ouvres)", Order = 14, GroupName = "01. Fiche 14 - Swing strict")]
        public int EarningsDays { get; set; }

        [Display(Name = "6. Exclure les actions sans date connue", Order = 15, GroupName = "01. Fiche 14 - Swing strict")]
        public bool ExcludeIfNoEarningsData { get; set; }

        [Range(0.0, 10.0)]
        [Display(Name = "Entree : limite sous la cloture (%)", Order = 16, GroupName = "01. Fiche 14 - Swing strict")]
        public double LimitOffsetPct { get; set; }

        [NinjaScriptProperty]
        [Range(2, 50)]
        [Display(Name = "Sortie : moyenne mobile (jours)", Order = 17, GroupName = "01. Fiche 14 - Swing strict")]
        public int ExitSmaDays { get; set; }

        [NinjaScriptProperty]
        [Range(1, 100)]
        [Display(Name = "Sortie : detention max (jours)", Order = 18, GroupName = "01. Fiche 14 - Swing strict")]
        public int MaxHoldDays { get; set; }

        [NinjaScriptProperty]
        [Range(0.5, 20.0)]
        [Display(Name = "Stop : multiplicateur ATR(14)", Order = 19, GroupName = "01. Fiche 14 - Swing strict")]
        public double AtrMultiplier { get; set; }

        [Range(0.1, 50.0)]
        [Display(Name = "Stop : borne basse (%)", Order = 20, GroupName = "01. Fiche 14 - Swing strict")]
        public double StopMinPct { get; set; }

        [Range(0.1, 50.0)]
        [Display(Name = "Stop : borne haute (%)", Order = 21, GroupName = "01. Fiche 14 - Swing strict")]
        public double StopMaxPct { get; set; }

        [Range(0.1, 50.0)]
        [Display(Name = "Alerte au-dela de (trades/semaine)", Order = 22, GroupName = "01. Fiche 14 - Swing strict")]
        public double MaxTradesPerWeek { get; set; }
        #endregion
    }
}
