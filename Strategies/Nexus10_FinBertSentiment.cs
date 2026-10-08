// =============================================================================
//  Nexus10_FinBertSentiment.cs   (NinjaTrader 8 / NinjaScript)
//
//  FICHE 10 - Sentiment FinBERT (n00bForFun)
//  [arXiv] Araci 1908.10063 (FinBERT) ; [arXiv] Lopez-Lira, Tang.
//
//  FinBERT = BERT pre-entraine sur un corpus financier et affine sur le
//  sentiment ; gratuit, execute EN LOCAL (Tools\finbert_server.py, sans cout par
//  appel). Sortie : P(positif), P(negatif), P(neutre) par phrase.
//  Score = P(positif) - P(negatif), dans [-1 ; +1] ; non neutre si |score| >= 0.4.
//
//  ROLE 1 - pre-filtre : integre aux fiches 7 et 9 (option "Pre-filtre FinBERT").
//  ROLE 2 - signal autonome (cette strategie) : memes regles que la fiche 7
//           avec le score FinBERT a la place du score LLM.
//
//  Pourquoi pas en signal seul : les modeles de la generation BERT classent bien
//  le ton d une phrase mais ne predisent pas correctement les rendements
//  (Lopez-Lira, Tang). TEST A FAIRE : faire tourner cette strategie en
//  parallele de la fiche 7 pendant le paper ; si le PnL est comparable, FinBERT
//  supprime l essentiel du cout API, sinon il reste un filtre. Le rapport compare
//  automatiquement les journaux des deux strategies.
// =============================================================================

#region Using declarations
using System;
using System.Collections.Generic;
using System.ComponentModel.DataAnnotations;
using System.Globalization;
using System.IO;
using System.Linq;
using NinjaTrader.Cbi;
using NinjaTrader.Data;
using NinjaTrader.NinjaScript;
using NinjaTrader.NinjaScript.AddOns.Nexus;
#endregion

namespace NinjaTrader.NinjaScript.Strategies
{
    public class Nexus10FinBertSentiment : NexusNewsEventBase
    {
        private int headlinesScored, nonNeutral, serverErrors;

        protected override void NxLlmSetDefaults()
        {
            Name = "Nexus10_FinBertSentiment";
            Description = "Fiche 10 - Signal autonome FinBERT local : score P(pos)-P(neg), memes regles que la fiche 7 (>= +0.5 sur 2 titres, <= -0.5 sortie, 1 jour). A comparer a la fiche 7.";
            Symbols = "SPY,QQQ,AAPL,MSFT,NVDA,AMZN,GOOGL,META,JPM,JNJ,XOM,UNH,V,PG,HD,BTCUSD,ETHUSD";
            SizingMode = NxSizingMode.DemiKelly;
            SetNewsEventDefaults();

            NonNeutralThreshold = 0.4;
            CountNeutralHeadlines = true;
            FinBertInBacktest = true;
            CompareWithStrategy = "Nexus07_NewsLlmEvent";
        }

        protected override void NxLlmDataLoaded()
        {
            Nx("FinBERT : serveur " + FinBertUrl + " (lancer Tools\\finbert_server.py ; les scores sont mis en cache dans Nexus\\cache\\finbert_cache.csv)");
        }

        protected override bool ScoreItems(NxSym s, DateTime day, List<NxNewsItem> items, out double score, out int scored, out bool ambiguous, out string detail)
        {
            ambiguous = false;
            List<double[]> probs;
            string err;
            FinBert.Score(items.Select(i => i.Headline).ToList(), State == State.Realtime || FinBertInBacktest, out probs, out err);
            if (err != null) { serverErrors++; NxOnce("fb" + (err.Length > 20 ? err.Substring(0, 20) : err), "FinBERT : " + err); }
            List<double> sc = new List<double>();
            List<string> parts = new List<string>();
            for (int i = 0; i < items.Count; i++)
            {
                double v = NxFinBertClient.ScoreOf(probs[i]);
                parts.Add((NxMath.Ok(v) ? v.ToString("+0.00;-0.00;0", CultureInfo.InvariantCulture) : "?") + " " + NxText.OneLine(items[i].Headline, 90));
                if (!NxMath.Ok(v)) continue;
                headlinesScored++;
                bool nn = Math.Abs(v) >= NonNeutralThreshold;
                if (nn) nonNeutral++;
                if (nn || CountNeutralHeadlines) sc.Add(v);
            }
            scored = sc.Count;
            score = scored > 0 ? sc.Average() : double.NaN;
            detail = string.Join(" | ", parts);
            return scored > 0;
        }

        protected override void NxPrescore(List<NxNewsItem> fresh)
        {
            List<double[]> p;
            string err;
            FinBert.Score(fresh.Select(x => x.Headline).ToList(), true, out p, out err);
            if (err != null) BgLogOnce("fbpre10", "FinBERT : " + err);
        }

        protected override void NxReportExtras(List<string> lines)
        {
            AddNewsReport(lines);
            lines.Add(string.Format(CultureInfo.InvariantCulture, "Titres notes par FinBERT : {0} | non neutres (|score| >= {1}) : {2} ({3:P0}) | erreurs serveur : {4}",
                headlinesScored, NonNeutralThreshold, nonNeutral, headlinesScored > 0 ? (double)nonNeutral / headlinesScored : 0, serverErrors));
            lines.Add("Cout par appel : 0 $ (execution locale).");
            // Comparaison avec la fiche 7 (journaux paper / reel).
            string other = Path.Combine(NxPaths.Journal, "trades_" + NxPaths.SafeFileName(CompareWithStrategy) + ".csv");
            string mine = Journal != null ? Journal.TradesFile : null;
            lines.Add(CompareJournals(mine, other));
        }

        private string CompareJournals(string mine, string other)
        {
            if (string.IsNullOrEmpty(other) || !File.Exists(other))
                return "Comparaison fiche 7 : journal '" + Path.GetFileName(other) + "' absent (faire tourner les deux strategies en paper avec le journal actif).";
            Func<string, double[]> load = path =>
            {
                string[] h;
                List<string[]> rows = NxCsv.ReadRows(path, out h);
                int cn = NxCsv.Col(h, "net_pnl");
                List<double> v = rows.Select(r => NxCsv.ParseDouble(NxCsv.Get(r, cn))).Where(NxMath.Ok).ToList();
                return new[] { v.Count, v.Sum(), v.Count > 0 ? (double)v.Count(x => x > 0) / v.Count : double.NaN };
            };
            double[] o = load(other);
            double[] m = mine != null && File.Exists(mine) ? load(mine) : new double[] { ClosedTrades.Count, ClosedTrades.Sum(t => t.NetPnl), ClosedTrades.Count > 0 ? (double)ClosedTrades.Count(t => t.NetPnl > 0) / ClosedTrades.Count : double.NaN };
            double aiCost = 0;
            string[] hh;
            foreach (string[] r in NxCsv.ReadRows(NxAiLedger.FilePath, out hh))
                if (string.Equals(NxCsv.Get(r, NxCsv.Col(hh, "strategy")), CompareWithStrategy, StringComparison.OrdinalIgnoreCase))
                { double c = NxCsv.ParseDouble(NxCsv.Get(r, NxCsv.Col(hh, "cost_usd"))); if (NxMath.Ok(c)) aiCost += c; }
            return string.Format(CultureInfo.InvariantCulture,
                "Comparaison journaux : FinBERT {0} trades, PnL net {1:F2}, reussite {2:P0} | {3} : {4} trades, PnL net {5:F2}, reussite {6:P0}, cout API {7:F2} $",
                m[0], m[1], m[2], CompareWithStrategy, o[0], o[1], o[2], aiCost);
        }

        #region Proprietes
        [NinjaScriptProperty]
        [Range(0.0, 1.0)]
        [Display(Name = "Seuil non neutre |score|", Order = 1, GroupName = "02. Fiche 10 - FinBERT")]
        public double NonNeutralThreshold { get; set; }

        [Display(Name = "Compter les titres neutres dans la moyenne", Description = "Vrai = comme un LLM qui repond 'sans effet' (fiche 7).", Order = 2, GroupName = "02. Fiche 10 - FinBERT")]
        public bool CountNeutralHeadlines { get; set; }

        [Display(Name = "FinBERT en backtest", Order = 3, GroupName = "02. Fiche 10 - FinBERT")]
        public bool FinBertInBacktest { get; set; }

        [Display(Name = "Strategie comparee (journal)", Order = 4, GroupName = "02. Fiche 10 - FinBERT")]
        public string CompareWithStrategy { get; set; }
        #endregion
    }
}
