// =============================================================================
//  Nexus02_XSMOM.cs   (NinjaTrader 8 / NinjaScript)
//
//  FICHE 2 - Momentum transversal (XSMOM)
//  [SSRN] Asness, Moskowitz, Pedersen ; [SSRN] Barroso, Santa-Clara ;
//  [SSRN] Daniel, Moskowitz.
//
//  REGLES
//   1. Fin de mois : classer les 25 symboles par rendement 12-1.
//   2. Acheter le quartile superieur (6 sur 25) a poids egal.
//   3. Tampon de rotation : un symbole deja detenu ne sort que s il tombe hors
//      du top 9 (limite la rotation et les frais) [Choix].
//   4. Panier mis a l echelle a 12 % de volatilite annualisee (vol realisee
//      6 mois du panier) ; exposition totale plafonnee a 50 % du bankroll.
//   5. Meme reduction de moitie qu en fiche 1 en etat de panique.
//   Stop ATR(14) x 3 borne a [2 % ; 8 %]. Long uniquement.
//
//  Points d attention : Barroso et Santa-Clara rapportent un Sharpe qui passe de
//  ~0.53 a ~0.97 avec la gestion par volatilite realisee ; les signaux des
//  fiches 1, 2 et 3 viennent du meme mouvement de prix (mesurer la correlation).
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
    public class Nexus02XSMOM : NexusStrategyBase
    {
        private Dictionary<string, double> lastScores = new Dictionary<string, double>(StringComparer.OrdinalIgnoreCase);
        private List<string> selection = new List<string>();
        private bool lastPanic, panicInit;
        private int rebalances, replacements, panicDays, totalDays;
        private double lastBasketVol = double.NaN, lastExposure = double.NaN;
        private string lastPanicDetail = "";

        protected override void NxSetDefaults()
        {
            Name = "Nexus02_XSMOM";
            Description = "Fiche 2 - Momentum transversal 12-1 : quartile superieur a poids egal, tampon top 9, panier a 12 % de vol, 50 % max, panique /2.";
            Symbols = "SPY,QQQ,XLF,XLV,XLE,XLI,XLY,XLP,XLU,XLB,XLRE,XLC,AAPL,MSFT,NVDA,AMZN,GOOGL,META,JPM,JNJ,XOM,UNH,V,PG,HD";
            SizingMode = NxSizingMode.Natif;

            LookbackDays = 252;
            SkipDays = 21;
            TopCount = 0;
            BufferRank = 0;
            UseVolScaling = true;
            TargetVolPct = 12.0;
            VolWindowDays = 126;
            MaxBasketPct = 50.0;
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
            Dictionary<string, double> scores = new Dictionary<string, double>(StringComparer.OrdinalIgnoreCase);
            foreach (NxSym s in traded)
            {
                double sig = NxMomentum.Return12_1(s.Hist, LookbackDays, SkipDays);
                if (NxMath.Ok(sig)) scores[s.Name] = sig;
            }
            lastScores = scores;

            bool panic = false;
            if (UsePanicState && baro != null) panic = NxPanicState.Evaluate(baro.Hist, PanicLookbackDays, PanicVolDays, PanicMedianDays, out lastPanicDetail);
            if (panic) panicDays++;
            if (scores.Count < 4) return;   // chauffage

            if (IsRebalanceDay(day, NxRebalance.Mensuel, baro ?? traded.FirstOrDefault()))
            {
                rebalances++;
                int n = scores.Count;
                int top = TopCount > 0 ? TopCount : Math.Max(1, (int)Math.Round(n / 4.0));
                int buffer = BufferRank > 0 ? Math.Max(top, BufferRank) : Math.Max(top, (int)Math.Round(n * 0.36));
                HashSet<string> held = new HashSet<string>(traded.Where(s => s.Qty > 0 || s.TargetQty > 0).Select(s => s.Name), StringComparer.OrdinalIgnoreCase);
                List<string> sel = NxRankSelection.SelectWithBuffer(scores, held, top, buffer);
                replacements += sel.Count(x => !held.Contains(x));

                // Panier a poids egal, mis a l echelle de la vol cible.
                List<NxBarHistory> hs = sel.Select(x => Sym(x).Hist).ToList();
                double[] eqw = sel.Select(x => 1.0 / sel.Count).ToArray();
                double bvol = NxPanel.BasketVol(hs, eqw, VolWindowDays);
                double exposure = MaxBasketPct / 100.0;
                if (UseVolScaling && NxMath.Ok(bvol) && bvol > 1e-6) exposure = Math.Min(exposure, TargetVolPct / 100.0 / bvol);
                if (panic) exposure *= PanicMultiplier;
                lastBasketVol = bvol; lastExposure = exposure;
                Nx(string.Format(CultureInfo.InvariantCulture, "{0:yyyy-MM-dd} reequilibrage : top {1}/{2} (tampon {3}) vol panier {4:P1} -> exposition {5:P1}{6} : {7}",
                    day, top, n, buffer, bvol, exposure, panic ? " (PANIQUE)" : "", string.Join(", ", sel)));

                foreach (NxSym s in traded)
                {
                    s.StoppedOut = false;
                    if (sel.Contains(s.Name))
                    {
                        double w = exposure / sel.Count;
                        string det;
                        int q = SizeQty(s, w, s.LastPrice, double.NaN, out det);
                        double stop = NxAtrStop.LongStop(s.LastPrice, s.Hist.Atr, AtrMultiplier, StopMinPct / 100.0, StopMaxPct / 100.0);
                        if (s.Qty > 0 && NxMath.Ok(s.StopPrice)) stop = Math.Max(stop, s.StopPrice);
                        int rank = NxRankSelection.RankOf(scores, s.Name);
                        SetTarget(s, q, stop, string.Format(CultureInfo.InvariantCulture, "XSMOM rang {0} 12-1={1:P1}", rank, scores[s.Name]));
                        NxSignal(NowNt, s.Name, "xsmom_selection", string.Format(CultureInfo.InvariantCulture, "rang={0} w={1:P2} q={2} | {3}", rank, w, q, det));
                    }
                    else if (s.Qty != 0 || s.TargetQty != 0)
                    {
                        int rank = NxRankSelection.RankOf(scores, s.Name);
                        SetTarget(s, 0, double.NaN, "hors du top " + buffer + " (rang " + (rank == int.MaxValue ? "n/a" : rank.ToString()) + ")");
                    }
                }
                selection = sel;
                lastPanic = panic;
                panicInit = true;
                return;
            }

            if (UsePanicState && PanicCheckDaily && panicInit && panic != lastPanic)
            {
                double factor = panic ? PanicMultiplier : 1.0 / Math.Max(1e-9, PanicMultiplier);
                Nx(string.Format(CultureInfo.InvariantCulture, "{0:yyyy-MM-dd} etat de panique {1} -> panier x{2:F2} ({3})", day, panic ? "ACTIVE" : "leve", factor, lastPanicDetail));
                foreach (NxSym s in traded)
                {
                    if (s.TargetQty <= 0) continue;
                    int lot = Math.Max(1, LotSize);
                    int q = (int)Math.Floor(s.TargetQty * factor / lot) * lot;
                    if (!panic)
                    {
                        string det;
                        NxSizingMode keep = SizingCfg.Mode;
                        SizingCfg.Mode = NxSizingMode.Natif;
                        double w = q * s.LastPrice * ValuePerPoint(s) / Math.Max(1.0, Bankroll());
                        q = Math.Min(q, SizeQty(s, w, s.LastPrice, double.NaN, out det));
                        SizingCfg.Mode = keep;
                    }
                    SetTarget(s, q, s.StopPrice, panic ? "panique : exposition /2" : "fin de panique");
                }
                lastPanic = panic;
            }
        }

        protected override void NxReportExtras(List<string> lines)
        {
            lines.Add(string.Format(CultureInfo.InvariantCulture, "Reequilibrages : {0} | nouveaux titres entres : {1} ({2:F2} par reequilibrage) | jours de panique : {3}/{4}",
                rebalances, replacements, rebalances > 0 ? (double)replacements / rebalances : 0, panicDays, totalDays));
            lines.Add(string.Format(CultureInfo.InvariantCulture, "Derniere vol du panier : {0:P1} -> exposition {1:P1}", lastBasketVol, lastExposure));
            lines.Add("Selection courante : " + string.Join(", ", selection));
            lines.Add("Rappel : correler ce journal avec ceux des fiches 1 et 3 (module B) avant d additionner les tailles.");
        }

        #region Proprietes
        [NinjaScriptProperty]
        [Range(42, 1000)]
        [Display(Name = "Fenetre de classement (jours)", Order = 1, GroupName = "01. Fiche 2 - XSMOM")]
        public int LookbackDays { get; set; }

        [NinjaScriptProperty]
        [Range(0, 252)]
        [Display(Name = "Mois exclu (jours)", Order = 2, GroupName = "01. Fiche 2 - XSMOM")]
        public int SkipDays { get; set; }

        [NinjaScriptProperty]
        [Range(0, 500)]
        [Display(Name = "Nombre de titres (0 = quartile)", Description = "Quartile superieur : 6 sur 25.", Order = 3, GroupName = "01. Fiche 2 - XSMOM")]
        public int TopCount { get; set; }

        [NinjaScriptProperty]
        [Range(0, 500)]
        [Display(Name = "Tampon de rotation (0 = auto)", Description = "Un detenu reste tant qu il est dans ce top (9 sur 25).", Order = 4, GroupName = "01. Fiche 2 - XSMOM")]
        public int BufferRank { get; set; }

        [NinjaScriptProperty]
        [Display(Name = "Mise a l echelle par la vol", Order = 5, GroupName = "01. Fiche 2 - XSMOM")]
        public bool UseVolScaling { get; set; }

        [NinjaScriptProperty]
        [Range(1.0, 100.0)]
        [Display(Name = "Volatilite cible du panier (%)", Order = 6, GroupName = "01. Fiche 2 - XSMOM")]
        public double TargetVolPct { get; set; }

        [Range(20, 756)]
        [Display(Name = "Fenetre de vol du panier (jours)", Order = 7, GroupName = "01. Fiche 2 - XSMOM")]
        public int VolWindowDays { get; set; }

        [Range(1.0, 1000.0)]
        [Display(Name = "Exposition max du panier (%)", Order = 8, GroupName = "01. Fiche 2 - XSMOM")]
        public double MaxBasketPct { get; set; }

        [NinjaScriptProperty]
        [Range(0.5, 20.0)]
        [Display(Name = "Stop : multiplicateur ATR(14)", Order = 9, GroupName = "01. Fiche 2 - XSMOM")]
        public double AtrMultiplier { get; set; }

        [Range(0.1, 50.0)]
        [Display(Name = "Stop : borne basse (%)", Order = 10, GroupName = "01. Fiche 2 - XSMOM")]
        public double StopMinPct { get; set; }

        [Range(0.1, 50.0)]
        [Display(Name = "Stop : borne haute (%)", Order = 11, GroupName = "01. Fiche 2 - XSMOM")]
        public double StopMaxPct { get; set; }

        [Display(Name = "Barometre", Order = 12, GroupName = "01. Fiche 2 - XSMOM")]
        public string Barometer { get; set; }

        [NinjaScriptProperty]
        [Display(Name = "Etat de panique actif", Order = 13, GroupName = "01. Fiche 2 - XSMOM")]
        public bool UsePanicState { get; set; }

        [Range(0.0, 1.0)]
        [Display(Name = "Panique : multiplicateur", Order = 14, GroupName = "01. Fiche 2 - XSMOM")]
        public double PanicMultiplier { get; set; }

        [Range(21, 2000)]
        [Display(Name = "Panique : comparaison a (jours)", Order = 15, GroupName = "01. Fiche 2 - XSMOM")]
        public int PanicLookbackDays { get; set; }

        [Range(5, 252)]
        [Display(Name = "Panique : vol 1 mois (jours)", Order = 16, GroupName = "01. Fiche 2 - XSMOM")]
        public int PanicVolDays { get; set; }

        [Range(21, 2000)]
        [Display(Name = "Panique : mediane sur (jours)", Order = 17, GroupName = "01. Fiche 2 - XSMOM")]
        public int PanicMedianDays { get; set; }

        [Display(Name = "Panique : controle quotidien", Order = 18, GroupName = "01. Fiche 2 - XSMOM")]
        public bool PanicCheckDaily { get; set; }
        #endregion
    }
}
