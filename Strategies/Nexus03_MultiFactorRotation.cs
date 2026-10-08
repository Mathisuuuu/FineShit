// =============================================================================
//  Nexus03_MultiFactorRotation.cs   (NinjaTrader 8 / NinjaScript)
//
//  FICHE 3 - Rotation multi-facteurs (momentum + value + qualite, top 5)
//  ~16 % du PnL de Nexus. [SSRN] Asness, Moskowitz, Pedersen (value/momentum),
//  [SSRN] Asness, Frazzini, Pedersen (QMJ), [SSRN] Ehsani, Linnainmaa (rotation).
//
//  REGLES
//   1. Chaque soir : 3 z-scores par action (rang centre puis z-score) :
//        momentum = rendement 12-1
//        value    = book-to-market (earnings-to-price si fonds propres negatifs)
//        qualite  = moyenne de rentabilite (marge brute / actifs), croissance
//                   (variation 5 ans de la rentabilite), securite (beta faible
//                   ET levier faible)
//   2. Rendement 12 mois de chaque facteur (tiers haut - tiers bas, recalcule
//      chaque jour) : positif -> poids x1.5, negatif -> x0.5, puis renormalise.
//   3. Score composite = somme ponderee des z-scores.
//   4. Detenir le top 5 a poids egal ; remplacer un titre seulement s il sort
//      du top 8.
//   5. Plafonds du module B (10 %/symbole, 30 %/classe d actifs).
//
//  DONNEES : les ETF n ont pas de bilan -> exclus automatiquement (classe ETF).
//  Fondamentaux POINT-IN-TIME dans Nexus\data\fundamentals.csv (modele fourni) :
//  symbol, available_date, book_equity, net_income_ttm, gross_profit_ttm,
//  total_assets, total_liabilities, shares_outstanding. Sans fichier, la
//  strategie tourne en momentum + securite (beta) seulement et le signale.
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
    public class Nexus03MultiFactorRotation : NexusStrategyBase
    {
        private NxFundamentals fund;
        private NxMultiFactorEngine engine;
        private NxMultiFactorResult last;
        private int scoredDays, changes, rotationActiveDays;
        private readonly double[] weightSum = new double[3];

        protected override void NxSetDefaults()
        {
            Name = "Nexus03_MultiFactorRotation";
            Description = "Fiche 3 - Momentum + value + qualite (QMJ), rotation des facteurs x1.5 / x0.5, top 5 a poids egal, sortie hors top 8.";
            Symbols = "SPY,QQQ,XLF,XLV,XLE,XLI,XLY,XLP,XLU,XLB,XLRE,XLC,AAPL,MSFT,NVDA,AMZN,GOOGL,META,JPM,JNJ,XOM,UNH,V,PG,HD";
            SizingMode = NxSizingMode.Natif;

            FundamentalsFile = "fundamentals.csv";
            MarketSymbol = "SPY";
            TopCount = 5;
            BufferRank = 8;
            TargetExposurePct = 30.0;
            UseRotation = true;
            UpMultiplier = 1.5;
            DownMultiplier = 0.5;
            RotationWindowDays = 252;
            MomLookbackDays = 252;
            MomSkipDays = 21;
            GrowthYears = 5;
            BetaWindowDays = 252;
            MinScored = 8;
            RequireFundamentals = false;
            UseAtrStop = false;
            AtrMultiplier = 3.0;
            StopMinPct = 2.0;
            StopMaxPct = 8.0;
        }

        protected override IEnumerable<string> NxRequiredReferences() { return new[] { MarketSymbol }; }

        protected override void NxDataLoaded()
        {
            fund = new NxFundamentals();
            string msg;
            fund.Load(NxPaths.Resolve(FundamentalsFile, NxPaths.Data), out msg);
            Nx("Fondamentaux : " + msg);
            if (!fund.Loaded) Nx("ATTENTION : pas de fondamentaux -> value et rentabilite/croissance indisponibles ; score = momentum + securite (beta).");
            engine = new NxMultiFactorEngine(fund)
            {
                MomLookback = MomLookbackDays, MomSkip = MomSkipDays, BetaWindow = BetaWindowDays, RotationWindow = RotationWindowDays,
                UpMultiplier = UpMultiplier, DownMultiplier = DownMultiplier, UseRotation = UseRotation, GrowthYears = GrowthYears
            };
        }

        protected override void NxOnBatch(DateTime day)
        {
            List<NxSym> stocks = TradedSyms.Where(s => s.Class == NxAssetClass.Action && (!RequireFundamentals || fund.Has(s.Name))).ToList();
            if (stocks.Count == 0) { NxOnce("nostock", "Aucune action individuelle dans l univers (les ETF sont exclus)."); return; }
            Dictionary<string, NxBarHistory> map = stocks.ToDictionary(s => s.Name, s => s.Hist, StringComparer.OrdinalIgnoreCase);
            NxSym mkt = Sym(MarketSymbol);
            last = engine.Update(day, map, mkt != null ? mkt.Hist : null);
            if (last.Scored < Math.Min(MinScored, stocks.Count)) return;
            scoredDays++;
            for (int f = 0; f < 3; f++) weightSum[f] += last.Weights[f];
            if (NxMath.Ok(last.Factor12m[0])) rotationActiveDays++;

            HashSet<string> held = new HashSet<string>(stocks.Where(s => s.Qty > 0 || s.TargetQty > 0).Select(s => s.Name), StringComparer.OrdinalIgnoreCase);
            List<string> sel = NxRankSelection.SelectWithBuffer(last.Composite, held, TopCount, BufferRank);

            foreach (NxSym s in stocks)
            {
                bool inSel = sel.Contains(s.Name);
                bool isHeld = held.Contains(s.Name);
                if (inSel && !isHeld)
                {
                    double w = TargetExposurePct / 100.0 / Math.Max(1, TopCount);
                    string det;
                    int q = SizeQty(s, w, s.LastPrice, double.NaN, out det);
                    double stop = UseAtrStop ? NxAtrStop.LongStop(s.LastPrice, s.Hist.Atr, AtrMultiplier, StopMinPct / 100.0, StopMaxPct / 100.0) : double.NaN;
                    double[] z = last.Z[s.Name];
                    string why = string.Format(CultureInfo.InvariantCulture, "composite={0:F2} rang {1} (z mom {2:F2} val {3:F2} qual {4:F2})",
                        last.Composite[s.Name], NxRankSelection.RankOf(last.Composite, s.Name), z[0], z[1], z[2]);
                    SetTarget(s, q, stop, why);
                    NxSignal(NowNt, s.Name, "multifacteur_entree", why + " | " + det);
                    changes++;
                }
                else if (!inSel && isHeld)
                {
                    int rank = NxRankSelection.RankOf(last.Composite, s.Name);
                    SetTarget(s, 0, double.NaN, "sorti du top " + BufferRank + " (rang " + (rank == int.MaxValue ? "n/a" : rank.ToString()) + ")");
                    changes++;
                }
            }
        }

        protected override void NxReportExtras(List<string> lines)
        {
            lines.Add(string.Format(CultureInfo.InvariantCulture, "Jours notes : {0} | changements de position : {1} | rotation active {2} jours",
                scoredDays, changes, rotationActiveDays));
            if (scoredDays > 0)
                lines.Add(string.Format(CultureInfo.InvariantCulture, "Poids moyens des facteurs : momentum {0:P1}, value {1:P1}, qualite {2:P1}",
                    weightSum[0] / scoredDays, weightSum[1] / scoredDays, weightSum[2] / scoredDays));
            if (last != null)
            {
                lines.Add(string.Format(CultureInfo.InvariantCulture, "Derniers rendements 12 mois long-short : momentum {0:P1}, value {1:P1}, qualite {2:P1}",
                    last.Factor12m[0], last.Factor12m[1], last.Factor12m[2]));
                lines.Add("Top actuel : " + string.Join(", ", last.Composite.OrderByDescending(kv => kv.Value).Take(8)
                    .Select(kv => kv.Key + " " + kv.Value.ToString("F2", CultureInfo.InvariantCulture))));
            }
            lines.Add(fund != null && fund.Loaded ? "Fondamentaux charges (point-in-time)." : "SANS fondamentaux : value et qualite partielles - resultat a ne pas confondre avec la fiche 3 complete.");
            lines.Add("Rappel : ~20 actions -> classement bruite ; fort recouvrement avec la fiche 2 via le pilier momentum.");
        }

        #region Proprietes
        [Display(Name = "Fichier de fondamentaux", Description = "Relatif a Documents\\NinjaTrader 8\\Nexus\\data ou chemin absolu.", Order = 1, GroupName = "01. Fiche 3 - Multi-facteurs")]
        public string FundamentalsFile { get; set; }

        [Display(Name = "Marche (beta)", Order = 2, GroupName = "01. Fiche 3 - Multi-facteurs")]
        public string MarketSymbol { get; set; }

        [NinjaScriptProperty]
        [Range(1, 100)]
        [Display(Name = "Titres detenus (top N)", Order = 3, GroupName = "01. Fiche 3 - Multi-facteurs")]
        public int TopCount { get; set; }

        [NinjaScriptProperty]
        [Range(1, 200)]
        [Display(Name = "Tampon : sortie hors du top", Order = 4, GroupName = "01. Fiche 3 - Multi-facteurs")]
        public int BufferRank { get; set; }

        [NinjaScriptProperty]
        [Range(1.0, 1000.0)]
        [Display(Name = "Exposition cible du panier (%)", Description = "Divisee a parts egales entre les N titres, puis plafonds du module B.", Order = 5, GroupName = "01. Fiche 3 - Multi-facteurs")]
        public double TargetExposurePct { get; set; }

        [NinjaScriptProperty]
        [Display(Name = "Rotation des facteurs", Order = 6, GroupName = "01. Fiche 3 - Multi-facteurs")]
        public bool UseRotation { get; set; }

        [Range(1.0, 5.0)]
        [Display(Name = "Rotation : multiplicateur si positif", Order = 7, GroupName = "01. Fiche 3 - Multi-facteurs")]
        public double UpMultiplier { get; set; }

        [Range(0.0, 1.0)]
        [Display(Name = "Rotation : multiplicateur si negatif", Order = 8, GroupName = "01. Fiche 3 - Multi-facteurs")]
        public double DownMultiplier { get; set; }

        [Range(21, 1000)]
        [Display(Name = "Rotation : fenetre (jours)", Order = 9, GroupName = "01. Fiche 3 - Multi-facteurs")]
        public int RotationWindowDays { get; set; }

        [NinjaScriptProperty]
        [Range(42, 1000)]
        [Display(Name = "Momentum : fenetre (jours)", Order = 10, GroupName = "01. Fiche 3 - Multi-facteurs")]
        public int MomLookbackDays { get; set; }

        [Range(0, 252)]
        [Display(Name = "Momentum : mois exclu (jours)", Order = 11, GroupName = "01. Fiche 3 - Multi-facteurs")]
        public int MomSkipDays { get; set; }

        [Range(1, 20)]
        [Display(Name = "Qualite : croissance sur (annees)", Order = 12, GroupName = "01. Fiche 3 - Multi-facteurs")]
        public int GrowthYears { get; set; }

        [Range(20, 1000)]
        [Display(Name = "Securite : fenetre du beta (jours)", Order = 13, GroupName = "01. Fiche 3 - Multi-facteurs")]
        public int BetaWindowDays { get; set; }

        [Range(2, 500)]
        [Display(Name = "Minimum de titres notes", Order = 14, GroupName = "01. Fiche 3 - Multi-facteurs")]
        public int MinScored { get; set; }

        [Display(Name = "Exiger des fondamentaux", Description = "Exclure les actions absentes du fichier de fondamentaux.", Order = 15, GroupName = "01. Fiche 3 - Multi-facteurs")]
        public bool RequireFundamentals { get; set; }

        [Display(Name = "Stop ATR (optionnel)", Description = "La fiche 3 ne prevoit pas de stop.", Order = 16, GroupName = "01. Fiche 3 - Multi-facteurs")]
        public bool UseAtrStop { get; set; }

        [Range(0.5, 20.0)]
        [Display(Name = "Stop : multiplicateur ATR(14)", Order = 17, GroupName = "01. Fiche 3 - Multi-facteurs")]
        public double AtrMultiplier { get; set; }

        [Range(0.1, 50.0)]
        [Display(Name = "Stop : borne basse (%)", Order = 18, GroupName = "01. Fiche 3 - Multi-facteurs")]
        public double StopMinPct { get; set; }

        [Range(0.1, 50.0)]
        [Display(Name = "Stop : borne haute (%)", Order = 19, GroupName = "01. Fiche 3 - Multi-facteurs")]
        public double StopMaxPct { get; set; }
        #endregion
    }
}
