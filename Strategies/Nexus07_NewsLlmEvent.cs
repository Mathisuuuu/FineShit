// =============================================================================
//  Nexus07_NewsLlmEvent.cs   (NinjaTrader 8 / NinjaScript)
//
//  FICHE 7 - Evenementielle : actualites notees par un LLM (Claude)
//  [arXiv] Lopez-Lira, Tang - "Can ChatGPT Forecast Stock Price Movements?"
//
//  REGLES
//   - Sources : NewsAPI + Reddit + indice Fear & Greed (contexte crypto) [Fil].
//     Backtest : fichier Nexus\data\news.csv ; temps reel : collecte NewsAPI /
//     Reddit (ajoutee a news_live.csv pour les backtests suivants).
//   - Question : "Ce titre est-il bon, mauvais ou sans effet pour le cours de X
//     a court terme ?" -> bon = +1, mauvais = -1, sans effet = 0.
//   - Agregation : moyenne des scores du jour par symbole ; doublons = 1 titre.
//   - Horodatage : avant l ouverture -> trade a l ouverture du jour ; apres ->
//     ouverture du lendemain.
//   - Entree long : score moyen >= +0.5 avec au moins 2 titres distincts.
//   - Score <= -0.5 : sortie de la position existante ou entree interdite (pas
//     de vente a decouvert).
//   - Detention : 1 jour de bourse. Taille : demi-Kelly, 3 % max (module B).
//   - Reddit garde separe du flux NewsAPI et exclu du score par defaut.
//   - Cout des appels API journalise (Nexus\journal\ai_costs.csv) et rapporte
//     au PnL dans le rapport de fin de run.
//   - Option : pre-filtre FinBERT (fiche 10, role 1) -> seuls les titres non
//     neutres (|score FinBERT| >= 0.4) partent vers le LLM.
//
//  Point d attention : l auteur conclut que le LLM marche mieux en JUGE qu en
//  generateur de signaux -> voir la fiche 8.
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
    public class Nexus07NewsLlmEvent : NexusNewsEventBase
    {
        private int headlinesSent, finbertFiltered, unparseable;
        private readonly int[] labelCounts = new int[3];   // mauvais, sans effet, bon

        protected override void NxLlmSetDefaults()
        {
            Name = "Nexus07_NewsLlmEvent";
            Description = "Fiche 7 - Titres notes par un LLM (bon +1 / mauvais -1 / sans effet 0), moyenne du jour >= +0.5 sur 2 titres -> long 1 jour ; <= -0.5 -> sortie. Pre-filtre FinBERT optionnel.";
            Symbols = "SPY,QQQ,AAPL,MSFT,NVDA,AMZN,GOOGL,META,JPM,JNJ,XOM,UNH,V,PG,HD,BTCUSD,ETHUSD";
            SizingMode = NxSizingMode.DemiKelly;
            SetNewsEventDefaults();

            UseFinBertPrefilter = false;
            FinBertNeutralThreshold = 0.4;
            FinBertInBacktest = true;
        }

        private int[] Label(NxSym s, List<NxNewsItem> items, bool allowFinBertNetwork)
        {
            int[] lab = Enumerable.Repeat(int.MinValue, items.Count).ToArray();
            bool[] needLlm = Enumerable.Repeat(true, items.Count).ToArray();
            if (UseFinBertPrefilter)
            {
                List<double[]> probs;
                string err;
                FinBert.Score(items.Select(i => i.Headline).ToList(), allowFinBertNetwork, out probs, out err);
                if (err != null) BgLogOnce("fbpre", "Pre-filtre FinBERT partiel : " + err + " (les titres non notes partent au LLM)");
                for (int i = 0; i < items.Count; i++)
                {
                    if (probs[i] == null) continue;
                    if (Math.Abs(NxFinBertClient.ScoreOf(probs[i])) < FinBertNeutralThreshold) { lab[i] = 0; needLlm[i] = false; System.Threading.Interlocked.Increment(ref finbertFiltered); }
                }
            }
            string company = CompanyOf(s.Name);
            List<int> idx = Enumerable.Range(0, items.Count).Where(i => needLlm[i]).ToList();
            List<Func<NxLlmResult>> jobs = idx.Select(i =>
            {
                string user = NxPrompts.Headline3(s.Name, company, items[i].Headline, ContextFor(s, items[i].PublishedUtc.Date));
                return (Func<NxLlmResult>)(() => CallLlm(MainLlm, NxPrompts.HeadlineSystem, user, "fiche7_titre"));
            }).ToList();
            List<NxLlmResult> res = RunAll(jobs);
            for (int k = 0; k < idx.Count; k++)
            {
                NxLlmResult r = res[k];
                if (r == null || !r.Ok) continue;
                if (!r.FromCache) System.Threading.Interlocked.Increment(ref headlinesSent);
                int v = NxPrompts.ParseLabel3(r.Text);
                if (v == int.MinValue) { System.Threading.Interlocked.Increment(ref unparseable); continue; }
                lab[idx[k]] = v;
            }
            return lab;
        }

        protected override bool ScoreItems(NxSym s, DateTime day, List<NxNewsItem> items, out double score, out int scored, out bool ambiguous, out string detail)
        {
            ambiguous = false;
            int[] lab = Label(s, items, State == State.Realtime || FinBertInBacktest);
            List<int> valid = lab.Where(v => v != int.MinValue).ToList();
            foreach (int v in valid) labelCounts[v + 1]++;
            scored = valid.Count;
            score = scored > 0 ? valid.Average() : double.NaN;
            detail = string.Join(" | ", items.Select((it, i) => (lab[i] == int.MinValue ? "?" : lab[i].ToString("+0;-0;0")) + " " + NxText.OneLine(it.Headline, 90)));
            return scored > 0;
        }

        protected override void NxPrescore(List<NxNewsItem> fresh)
        {
            foreach (IGrouping<string, NxNewsItem> g in fresh.Where(x => IncludeSocialInScore || !x.IsSocial).GroupBy(x => x.Symbol))
            {
                NxSym s = Sym(g.Key);
                if (s != null) Label(s, g.ToList(), true);
            }
        }

        protected override void NxReportExtras(List<string> lines)
        {
            AddNewsReport(lines);
            lines.Add(string.Format(CultureInfo.InvariantCulture, "Titres envoyes au LLM ({0}) : {1} | filtres par FinBERT : {2} | reponses illisibles : {3}",
                MainLlm != null ? MainLlm.Label : "?", headlinesSent, finbertFiltered, unparseable));
            lines.Add(string.Format(CultureInfo.InvariantCulture, "Repartition des notes : mauvais {0}, sans effet {1}, bon {2}", labelCounts[0], labelCounts[1], labelCounts[2]));
            lines.Add("Rappel (Lopez-Lira, Tang) : effet plus fort sur petites capitalisations et apres mauvaise nouvelle ; il decroit a mesure que l usage des LLM se repand.");
        }

        #region Proprietes
        [NinjaScriptProperty]
        [Display(Name = "Pre-filtre FinBERT (fiche 10)", Description = "Seuls les titres non neutres partent au LLM (serveur Tools\\finbert_server.py).", Order = 1, GroupName = "02. Fiche 7 - LLM")]
        public bool UseFinBertPrefilter { get; set; }

        [Range(0.0, 1.0)]
        [Display(Name = "FinBERT : seuil non neutre |score|", Order = 2, GroupName = "02. Fiche 7 - LLM")]
        public double FinBertNeutralThreshold { get; set; }

        [Display(Name = "FinBERT en backtest", Description = "Appeler le serveur local en historique (gratuit).", Order = 3, GroupName = "02. Fiche 7 - LLM")]
        public bool FinBertInBacktest { get; set; }
        #endregion
    }
}
