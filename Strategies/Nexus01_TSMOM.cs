// =============================================================================
//  Nexus01_TSMOM.cs   (NinjaTrader 8 / NinjaScript)
//
//  FICHE 1 - Momentum series temporelles (TSMOM)
//  ~80 % du PnL de Nexus avec la fiche 2. [SSRN] Moskowitz, Ooi, Pedersen ;
//  [SSRN] Barroso, Santa-Clara ; [SSRN] Daniel, Moskowitz.
//
//  REGLES
//   1. Chaque jour (apres la cloture) : rendement 12-1 de chaque symbole.
//   2. Premier jour de bourse du mois : long sur tous les signaux > 0
//      (decision a la cloture du dernier jour du mois -> ordres a l ouverture).
//   3. Taille : volatilite cible 12 % annualisee, volatilite realisee sur 6 mois
//      de rendements quotidiens, poids = (12 % / vol) / N ; puis plafonds du
//      module B (3 %/trade, 10 %/symbole, 30 %/classe, 50 % total).
//   4. Sortie au stop ATR(14) x 3 borne a [2 % ; 8 %] du prix, ou au
//      reequilibrage suivant si le signal est devenu negatif. Un symbole
//      stoppe reste a plat jusqu au reequilibrage suivant.
//   5. Exposition / 2 en "etat de panique" : SPY sous son niveau d il y a
//      24 mois ET volatilite 1 mois au-dessus de sa mediane 1 an [Choix].
//
//  Long seulement (petit compte Alpaca). XLK exclu de l univers par defaut
//  (donnees IEX defaillantes chez Nexus). Option "Mise a l echelle par la vol"
//  pour tester la version sans volatilite cible (point d attention de la fiche).
//  ATTENTION : 25 symboles tres correles = presque un seul pari sur l indice.
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
    public class Nexus01TSMOM : NexusStrategyBase
    {
        private readonly Dictionary<string, double> lastSignal = new Dictionary<string, double>(StringComparer.OrdinalIgnoreCase);
        private bool lastPanic;
        private bool panicInit;
        private int panicDays, rebalances, totalDays;
        private string lastPanicDetail = "";

        protected override void NxSetDefaults()
        {
            Name = "Nexus01_TSMOM";
            Description = "Fiche 1 - Momentum series temporelles 12-1, rebalancement mensuel, vol cible 12 %, stop ATR x3 [2-8 %], exposition /2 en etat de panique.";
            Symbols = "SPY,QQQ,XLF,XLV,XLE,XLI,XLY,XLP,XLU,XLB,XLRE,XLC,AAPL,MSFT,NVDA,AMZN,GOOGL,META,JPM,JNJ,XOM,UNH,V,PG,HD";
            SizingMode = NxSizingMode.Natif;

            LookbackDays = 252;
            SkipDays = 21;
            UseVolScaling = true;
            TargetVolPct = 12.0;
            VolWindowDays = 126;
            AtrMultiplier = 3.0;
            StopMinPct = 2.0;
            StopMaxPct = 8.0;
            Barometer = "SPY";
            UsePanicState = true;
            PanicMultiplier = 0.5;
            PanicLookbackDays = 504;
            PanicVolDays = 21;
            PanicMedianDays = 252;
            PanicCheckDaily = true;
        }

        protected override IEnumerable<string> NxRequiredReferences() { return new[] { Barometer }; }

        protected override void NxOnBatch(DateTime day)
        {
            totalDays++;
            List<NxSym> traded = TradedSyms;
            NxSym baro = Sym(Barometer);

            // 1) Signal quotidien 12-1 (journalise).
            int nValid = 0;
            foreach (NxSym s in traded)
            {
                double sig = NxMomentum.Return12_1(s.Hist, LookbackDays, SkipDays);
                lastSignal[s.Name] = sig;
                if (NxMath.Ok(sig) && NxMath.Ok(s.Hist.RealizedVol(VolWindowDays))) nValid++;
            }

            // 2) Etat de panique.
            bool panic = false;
            if (UsePanicState && baro != null) panic = NxPanicState.Evaluate(baro.Hist, PanicLookbackDays, PanicVolDays, PanicMedianDays, out lastPanicDetail);
            if (panic) panicDays++;
            double mult = panic ? PanicMultiplier : 1.0;

            if (nValid == 0) return;   // chauffage : aucun symbole n a 12 mois d historique

            // 3) Reequilibrage mensuel.
            if (IsRebalanceDay(day, NxRebalance.Mensuel, baro ?? traded.FirstOrDefault()))
            {
                rebalances++;
                Nx(string.Format(CultureInfo.InvariantCulture, "{0:yyyy-MM-dd} reequilibrage mensuel ({1} signaux valides, panique={2}{3})",
                    day, nValid, panic, panic ? " : " + lastPanicDetail : ""));
                foreach (NxSym s in traded)
                {
                    double sig = lastSignal[s.Name];
                    s.StoppedOut = false;
                    if (!NxMath.Ok(sig)) continue;   // historique insuffisant : position inchangee
                    if (sig > 0)
                    {
                        double w = UseVolScaling
                            ? NxMomentum.InverseVolWeight(s.Hist, TargetVolPct / 100.0, VolWindowDays, nValid, 0)
                            : 1.0 / nValid;
                        if (!NxMath.Ok(w)) continue;
                        w *= mult;
                        string det;
                        int q = SizeQty(s, w, s.LastPrice, double.NaN, out det);
                        double stop = NxAtrStop.LongStop(s.LastPrice, s.Hist.Atr, AtrMultiplier, StopMinPct / 100.0, StopMaxPct / 100.0);
                        if (s.Qty > 0 && NxMath.Ok(s.StopPrice)) stop = Math.Max(stop, s.StopPrice);   // un stop ne recule jamais
                        SetTarget(s, q, stop, string.Format(CultureInfo.InvariantCulture, "TSMOM 12-1={0:P1} w={1:P2}", sig, w));
                        NxSignal(NowNt, s.Name, "tsmom_long", string.Format(CultureInfo.InvariantCulture, "12-1={0:P2} cible={1} stop={2:F2} | {3}", sig, q, stop, det));
                    }
                    else if (s.Qty != 0 || s.TargetQty != 0)
                    {
                        SetTarget(s, 0, double.NaN, string.Format(CultureInfo.InvariantCulture, "signal 12-1 <= 0 ({0:P1})", sig));
                        NxSignal(NowNt, s.Name, "tsmom_sortie", "12-1=" + sig.ToString("P2", CultureInfo.InvariantCulture));
                    }
                }
                lastPanic = panic;
                panicInit = true;
                return;
            }

            // 4) Changement d etat de panique en cours de mois : exposition x0.5 ou retour x2.
            if (UsePanicState && PanicCheckDaily && panicInit && panic != lastPanic)
            {
                double factor = panic ? PanicMultiplier : 1.0 / Math.Max(1e-9, PanicMultiplier);
                Nx(string.Format(CultureInfo.InvariantCulture, "{0:yyyy-MM-dd} etat de panique {1} -> positions x{2:F2} ({3})", day, panic ? "ACTIVE" : "leve", factor, lastPanicDetail));
                foreach (NxSym s in traded)
                {
                    if (s.TargetQty <= 0) continue;
                    int lot = Math.Max(1, LotSize);
                    int q = (int)Math.Floor(s.TargetQty * factor / lot) * lot;
                    if (!panic)
                    {
                        // Retour a la normale : repasser par le module B (plafonds) avant d augmenter.
                        string det;
                        double w = q * s.LastPrice * ValuePerPoint(s) / Math.Max(1.0, Bankroll());
                        q = Math.Min(q, SizeQtyRaw(s, w, out det));
                    }
                    SetTarget(s, q, s.StopPrice, panic ? "panique : exposition /2" : "fin de panique");
                }
                lastPanic = panic;
            }
        }

        private int SizeQtyRaw(NxSym s, double fraction, out string det)
        {
            NxSizingMode keep = SizingCfg.Mode;
            SizingCfg.Mode = NxSizingMode.Natif;
            int q = SizeQty(s, fraction, s.LastPrice, double.NaN, out det);
            SizingCfg.Mode = keep;
            return q;
        }

        protected override void NxReportExtras(List<string> lines)
        {
            lines.Add(string.Format(CultureInfo.InvariantCulture, "Reequilibrages mensuels : {0} | jours en etat de panique : {1}/{2} ({3:P1})",
                rebalances, panicDays, totalDays, totalDays > 0 ? (double)panicDays / totalDays : 0));
            lines.Add("Version " + (UseVolScaling ? "AVEC" : "SANS") + " mise a l echelle par la volatilite : relancer avec l autre valeur pour isoler l apport du signal seul (fiche 1).");
            lines.Add("Rappel : le TSMOM est structurellement plus 'long marche' que le XSMOM (Goyal-Jegadeesh) ; mesurer la correlation avec les fiches 2 et 3 avant d additionner les tailles.");
            List<string> pos = lastSignal.Where(kv => NxMath.Ok(kv.Value)).OrderByDescending(kv => kv.Value).Take(25)
                                         .Select(kv => kv.Key + " " + kv.Value.ToString("P1", CultureInfo.InvariantCulture)).ToList();
            lines.Add("Derniers signaux 12-1 : " + string.Join(", ", pos));
        }

        #region Proprietes
        [NinjaScriptProperty]
        [Range(42, 1000)]
        [Display(Name = "Fenetre du signal (jours)", Description = "12 mois = 252 jours de bourse.", Order = 1, GroupName = "01. Fiche 1 - TSMOM")]
        public int LookbackDays { get; set; }

        [NinjaScriptProperty]
        [Range(0, 252)]
        [Display(Name = "Mois exclu (jours)", Description = "Dernier mois exclu = 21 jours (signal 12-1).", Order = 2, GroupName = "01. Fiche 1 - TSMOM")]
        public int SkipDays { get; set; }

        [NinjaScriptProperty]
        [Display(Name = "Mise a l echelle par la vol", Order = 3, GroupName = "01. Fiche 1 - TSMOM")]
        public bool UseVolScaling { get; set; }

        [NinjaScriptProperty]
        [Range(1.0, 100.0)]
        [Display(Name = "Volatilite cible (%/an)", Order = 4, GroupName = "01. Fiche 1 - TSMOM")]
        public double TargetVolPct { get; set; }

        [NinjaScriptProperty]
        [Range(20, 756)]
        [Display(Name = "Fenetre de vol realisee (jours)", Description = "6 mois = 126 jours.", Order = 5, GroupName = "01. Fiche 1 - TSMOM")]
        public int VolWindowDays { get; set; }

        [NinjaScriptProperty]
        [Range(0.5, 20.0)]
        [Display(Name = "Stop : multiplicateur ATR(14)", Order = 6, GroupName = "01. Fiche 1 - TSMOM")]
        public double AtrMultiplier { get; set; }

        [Range(0.1, 50.0)]
        [Display(Name = "Stop : borne basse (%)", Order = 7, GroupName = "01. Fiche 1 - TSMOM")]
        public double StopMinPct { get; set; }

        [Range(0.1, 50.0)]
        [Display(Name = "Stop : borne haute (%)", Order = 8, GroupName = "01. Fiche 1 - TSMOM")]
        public double StopMaxPct { get; set; }

        [Display(Name = "Barometre", Order = 9, GroupName = "01. Fiche 1 - TSMOM")]
        public string Barometer { get; set; }

        [NinjaScriptProperty]
        [Display(Name = "Etat de panique actif", Order = 10, GroupName = "01. Fiche 1 - TSMOM")]
        public bool UsePanicState { get; set; }

        [Range(0.0, 1.0)]
        [Display(Name = "Panique : multiplicateur", Order = 11, GroupName = "01. Fiche 1 - TSMOM")]
        public double PanicMultiplier { get; set; }

        [Range(21, 2000)]
        [Display(Name = "Panique : comparaison a (jours)", Description = "24 mois = 504 jours.", Order = 12, GroupName = "01. Fiche 1 - TSMOM")]
        public int PanicLookbackDays { get; set; }

        [Range(5, 252)]
        [Display(Name = "Panique : vol 1 mois (jours)", Order = 13, GroupName = "01. Fiche 1 - TSMOM")]
        public int PanicVolDays { get; set; }

        [Range(21, 2000)]
        [Display(Name = "Panique : mediane sur (jours)", Order = 14, GroupName = "01. Fiche 1 - TSMOM")]
        public int PanicMedianDays { get; set; }

        [Display(Name = "Panique : controle quotidien", Description = "Reduire/retablir en cours de mois quand l etat change.", Order = 15, GroupName = "01. Fiche 1 - TSMOM")]
        public bool PanicCheckDaily { get; set; }
        #endregion
    }
}
