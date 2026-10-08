// =============================================================================
//  NexusA_RegimeMonitor.cs   (NinjaTrader 8 / NinjaScript)
//
//  MODULE A - Moniteur de regime (HMM gaussien 3 etats + terciles de vol fiche 12)
//  N envoie AUCUN ordre. A appliquer sur un graphique JOURNALIER du barometre
//  (SPY par defaut ; BTCUSD pour la crypto). Le VIX est optionnel.
//
//  Trace : P(calme), P(neutre), P(stress) du HMM (probabilites FILTREES,
//  lissees 5 jours, plafonnees a 0.95) et le regime des terciles de vol
//  (0 = calme, 1 = neutre, 2 = stress). Publie le regime courant dans un
//  registre partage (NxRegimeRegistry) en temps reel.
//
//  Le rapport de fin de run donne la duree moyenne des regimes, le rendement
//  moyen du barometre le lendemain par regime et la part des jours "colles"
//  au plafond (diagnostic du defaut de Nexus : confiance bloquee a 1.0).
// =============================================================================

#region Using declarations
using System;
using System.Collections.Generic;
using System.ComponentModel.DataAnnotations;
using System.Globalization;
using System.Linq;
using System.Text;
using System.Windows.Media;
using NinjaTrader.Cbi;
using NinjaTrader.Data;
using NinjaTrader.NinjaScript;
using NinjaTrader.NinjaScript.AddOns.Nexus;
#endregion

namespace NinjaTrader.NinjaScript.Strategies
{
    public class NexusA_RegimeMonitor : Strategy
    {
        private NxHmmRegimeDetector hmm;
        private NxVolTercileRegime terc;
        private int vixBip = -1;
        private NxRegime lastHmm = NxRegime.Inconnu, lastVol = NxRegime.Inconnu;
        private readonly int[] hmmDays = new int[3], volDays = new int[3];
        private int hmmTransitions, volTransitions, cappedDays, readyDays;
        private readonly List<double>[] nextRet = { new List<double>(), new List<double>(), new List<double>() };
        private int prevHmmIdx = -1;
        private double prevClose = double.NaN;

        protected override void OnStateChange()
        {
            if (State == State.SetDefaults)
            {
                Name = "NexusA_RegimeMonitor";
                Description = "Module A - Moniteur de regime : HMM 3 etats (diag, fenetre 600 j, filtre avant, EMA 5 j, plafond 0.95, re-estimation hebdo, 10 initialisations) + terciles de vol (fiche 12). Aucun ordre.";
                Calculate = Calculate.OnBarClose;
                IsOverlay = false;
                BarsRequiredToTrade = 1;
                MaximumBarsLookBack = MaximumBarsLookBack.Infinite;
                IsInstantiatedOnEachOptimizationIteration = true;

                VixSymbol = "^VIX";
                WindowDays = 600;
                RefitEveryDays = 5;
                Initializations = 10;
                SmoothSpan = 5;
                CapProbability = 0.95;
                VolWindowDays = 20;
                Seed = 42;
                TercileLookbackDays = 504;
                ConfirmDays = 5;

                AddPlot(Brushes.SeaGreen, "P_Calme");
                AddPlot(Brushes.Orange, "P_Neutre");
                AddPlot(Brushes.Crimson, "P_Stress");
                AddPlot(Brushes.SteelBlue, "RegimeVol");
            }
            else if (State == State.Configure)
            {
                if (!string.IsNullOrWhiteSpace(VixSymbol))
                {
                    NinjaTrader.Cbi.Instrument ins = null;
                    try { ins = NinjaTrader.Cbi.Instrument.GetInstrument(VixSymbol.Trim(), false); } catch { }
                    if (ins != null) { AddDataSeries(VixSymbol.Trim(), BarsPeriodType.Day, 1); vixBip = 1; }
                    else Print("[NexusA] VIX '" + VixSymbol + "' introuvable : HMM sur 2 variables (rendement, vol realisee).");
                }
            }
            else if (State == State.DataLoaded)
            {
                hmm = new NxHmmRegimeDetector(vixBip > 0)
                {
                    Window = WindowDays, RefitEveryDays = RefitEveryDays, NInit = Initializations, SmoothSpan = SmoothSpan,
                    Cap = CapProbability, VolWindow = VolWindowDays, Seed = Seed
                };
                terc = new NxVolTercileRegime { RvWindow = VolWindowDays, LookbackDays = TercileLookbackDays, ConfirmDays = ConfirmDays };
            }
            else if (State == State.Terminated && hmm != null)
            {
                Print(Summary());
            }
        }

        private static int Idx(NxRegime r) { return r == NxRegime.Calme ? 0 : (r == NxRegime.Neutre ? 1 : (r == NxRegime.Stress ? 2 : -1)); }

        protected override void OnBarUpdate()
        {
            if (BarsInProgress != 0 || hmm == null) return;
            double vix = double.NaN;
            if (vixBip > 0 && CurrentBars[vixBip] >= 0)
            {
                vix = Closes[vixBip][0];
                if (State == State.Historical)
                {
                    // Barre VIX du MEME jour (pas encore traitee car indice de serie superieur) : lecture de sa cloture.
                    int nx = CurrentBars[vixBip] + 1;
                    if (nx < BarsArray[vixBip].Count && BarsArray[vixBip].GetTime(nx).Date == Time[0].Date) vix = BarsArray[vixBip].GetClose(nx);
                }
            }
            double c = Close[0];
            if (prevHmmIdx >= 0 && NxMath.Ok(prevClose) && prevClose > 0) nextRet[prevHmmIdx].Add(c / prevClose - 1);
            prevClose = c;

            hmm.Update(c, vix);
            terc.Update(c);

            if (hmm.IsReady)
            {
                double[] p = hmm.Probabilities;
                Values[0][0] = p[0]; Values[1][0] = p[1]; Values[2][0] = p[2];
                readyDays++;
                if (p.Max() >= CapProbability - 1e-6) cappedDays++;
                NxRegime r = hmm.Regime;
                int i = Idx(r);
                if (i >= 0) hmmDays[i]++;
                prevHmmIdx = i;
                if (r != lastHmm && lastHmm != NxRegime.Inconnu)
                {
                    hmmTransitions++;
                    Print(string.Format(CultureInfo.InvariantCulture, "[NexusA] {0:yyyy-MM-dd} HMM {1} -> {2} | {3}", Time[0], lastHmm, r, hmm.Describe()));
                }
                lastHmm = r;
            }
            if (terc.IsReady)
            {
                int j = Idx(terc.Regime);
                Values[3][0] = j;
                if (j >= 0) volDays[j]++;
                if (terc.Regime != lastVol && lastVol != NxRegime.Inconnu)
                {
                    volTransitions++;
                    Print(string.Format(CultureInfo.InvariantCulture, "[NexusA] {0:yyyy-MM-dd} terciles {1} -> {2} | {3}", Time[0], lastVol, terc.Regime, terc.Describe()));
                }
                lastVol = terc.Regime;
            }
            if (State == State.Realtime)
                NxRegimeRegistry.Publish(Instrument.MasterInstrument.Name, hmm.Regime, hmm.Probabilities, terc.Regime, NinjaTrader.Core.Globals.Now);
        }

        private string Summary()
        {
            CultureInfo ci = CultureInfo.InvariantCulture;
            StringBuilder sb = new StringBuilder();
            string[] names = { "calme", "neutre", "stress" };
            sb.AppendLine("=== Module A - resume du moniteur de regime (" + (Instrument != null ? Instrument.FullName : "?") + ") ===");
            sb.AppendLine(hmm.Describe());
            sb.AppendLine(terc.Describe());
            int th = hmmDays.Sum(), tv = volDays.Sum();
            for (int i = 0; i < 3; i++)
                sb.AppendLine(string.Format(ci, "  {0,-7} HMM {1,5} j ({2:P0}) duree moy. {3,6:F1} j | rendement moyen du lendemain {4:P3} | terciles {5,5} j ({6:P0})",
                    names[i], hmmDays[i], th > 0 ? (double)hmmDays[i] / th : 0, hmmTransitions > 0 ? (double)hmmDays[i] / Math.Max(1, hmmTransitions / 3.0) : hmmDays[i],
                    nextRet[i].Count > 0 ? nextRet[i].Average() : double.NaN, volDays[i], tv > 0 ? (double)volDays[i] / tv : 0));
            sb.AppendLine(string.Format(ci, "  transitions HMM {0} | terciles {1} | jours au plafond {2:F2} : {3:P0} des jours (Nexus : bloque a 1.0)",
                hmmTransitions, volTransitions, CapProbability, readyDays > 0 ? (double)cappedDays / readyDays : 0));
            return sb.ToString();
        }

        #region Proprietes
        [Display(Name = "VIX (vide = sans)", Order = 1, GroupName = "01. Module A - HMM")]
        public string VixSymbol { get; set; }

        [NinjaScriptProperty]
        [Range(100, 5000)]
        [Display(Name = "Fenetre d estimation (jours)", Description = "500-750 recommande (100 chez Nexus = sur-ajustement).", Order = 2, GroupName = "01. Module A - HMM")]
        public int WindowDays { get; set; }

        [NinjaScriptProperty]
        [Range(1, 252)]
        [Display(Name = "Re-estimation tous les (jours)", Order = 3, GroupName = "01. Module A - HMM")]
        public int RefitEveryDays { get; set; }

        [Range(1, 100)]
        [Display(Name = "Initialisations aleatoires", Order = 4, GroupName = "01. Module A - HMM")]
        public int Initializations { get; set; }

        [Range(1, 60)]
        [Display(Name = "Lissage EMA (jours)", Order = 5, GroupName = "01. Module A - HMM")]
        public int SmoothSpan { get; set; }

        [Range(0.34, 1.0)]
        [Display(Name = "Plafond des probabilites", Order = 6, GroupName = "01. Module A - HMM")]
        public double CapProbability { get; set; }

        [Range(5, 120)]
        [Display(Name = "Vol realisee (jours)", Order = 7, GroupName = "01. Module A - HMM")]
        public int VolWindowDays { get; set; }

        [Range(0, 1000000)]
        [Display(Name = "Graine aleatoire", Order = 8, GroupName = "01. Module A - HMM")]
        public int Seed { get; set; }

        [Range(60, 5000)]
        [Display(Name = "Terciles sur (jours)", Order = 9, GroupName = "02. Fiche 12 - Terciles")]
        public int TercileLookbackDays { get; set; }

        [Range(1, 60)]
        [Display(Name = "Anti-clignotement (jours)", Order = 10, GroupName = "02. Fiche 12 - Terciles")]
        public int ConfirmDays { get; set; }
        #endregion
    }
}
