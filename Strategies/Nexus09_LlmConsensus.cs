// =============================================================================
//  Nexus09_LlmConsensus.cs   (NinjaTrader 8 / NinjaScript)
//
//  FICHE 9 - Consensus de 3 LLM (commentateur page 10)
//  [arXiv] 2603.22567 TrustTrade (selective consensus in LLM trading agents).
//
//  REGLES
//   - Trois modeles notent la MEME nouvelle : Claude + DeepSeek + Gemini.
//   - Meme consigne, meme titre, temperature 0, appels independants (aucun
//     modele ne voit la reponse des autres).
//   - Score par modele : entier de -2 (tres mauvais) a +2 (tres bon).
//   - Accord : meme signe pour les 3 ET chaque |score| >= 1. Les 3 a 0 = neutre.
//   - Desaccord : signal d ambiguite -> ne pas trader ce symbole ce jour-la.
//   - Score final = moyenne des 3, ramenee dans [-1 ; +1] (divisee par 2), puis
//     memes regles que la fiche 7 (>= +0.5 sur 2 titres, <= -0.5 sortie,
//     detention 1 jour).
//   - Cout x3 : pre-filtre FinBERT (fiche 10) ACTIF par defaut ; seuls les
//     titres non neutres partent aux 3 LLM (repli : tout envoyer si le serveur
//     FinBERT est absent).
//   - Mesure : les jours de desaccord sont-ils suivis de mouvements plus
//     volatils ? (rendement absolu du lendemain, desaccord vs accord).
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
    public class Nexus09LlmConsensus : NexusNewsEventBase
    {
        private NxLlmConfig deepSeek, gemini;
        private int agreeItems, neutralItems, disagreeItems, incompleteItems, finbertFiltered;
        private readonly Dictionary<string, int> pendingFlag = new Dictionary<string, int>(StringComparer.OrdinalIgnoreCase); // 1 accord, 2 desaccord
        private readonly List<double> nextAbsAfterAgree = new List<double>();
        private readonly List<double> nextAbsAfterDisagree = new List<double>();

        protected override void NxLlmSetDefaults()
        {
            Name = "Nexus09_LlmConsensus";
            Description = "Fiche 9 - Consensus Claude + DeepSeek + Gemini (-2..+2) : action seulement si les 3 sont d accord ; desaccord = pas de trade ce jour. Pre-filtre FinBERT.";
            Symbols = "SPY,QQQ,AAPL,MSFT,NVDA,AMZN,GOOGL,META,JPM,JNJ,XOM,UNH,V,PG,HD,BTCUSD,ETHUSD";
            SizingMode = NxSizingMode.DemiKelly;
            SetNewsEventDefaults();

            DeepSeekModel = "deepseek-chat";
            DeepSeekApiKey = "";
            DeepSeekPriceIn = 0.0;
            DeepSeekPriceOut = 0.0;
            GeminiModel = "gemini-2.5-flash";
            GeminiApiKey = "";
            GeminiPriceIn = 0.0;
            GeminiPriceOut = 0.0;
            GeminiMaxTokens = 1024;
            MinAbsScore = 1;
            UseFinBertPrefilter = true;
            FinBertNeutralThreshold = 0.4;
            FinBertInBacktest = true;
        }

        protected override void NxLlmDataLoaded()
        {
            deepSeek = BuildConfig(NxLlmProvider.DeepSeek, DeepSeekModel, DeepSeekApiKey, 0.0, LlmMaxTokens, LlmTimeoutSec, DeepSeekPriceIn, DeepSeekPriceOut);
            gemini = BuildConfig(NxLlmProvider.Gemini, GeminiModel, GeminiApiKey, 0.0, Math.Max(LlmMaxTokens, GeminiMaxTokens), LlmTimeoutSec, GeminiPriceIn, GeminiPriceOut);
            MainLlm.Temperature = 0.0;
            Nx(string.Format("Consensus : {0} (cle {1}) + {2} (cle {3}) + {4} (cle {5})", MainLlm.Label, NxSecrets.Mask(MainLlm.ApiKey),
                deepSeek.Label, NxSecrets.Mask(deepSeek.ApiKey), gemini.Label, NxSecrets.Mask(gemini.ApiKey)));
        }

        /// <summary>Par titre : 1 accord, 0 neutre, 2 desaccord, -1 incomplet ; final dans [-1 ; +1].</summary>
        private int[] Consensus(NxSym s, List<NxNewsItem> items, bool allowFinBertNetwork, out double[] finals)
        {
            int n = items.Count;
            finals = Enumerable.Repeat(double.NaN, n).ToArray();
            int[] kind = Enumerable.Repeat(-1, n).ToArray();
            bool[] send = Enumerable.Repeat(true, n).ToArray();
            if (UseFinBertPrefilter)
            {
                List<double[]> probs;
                string err;
                FinBert.Score(items.Select(i => i.Headline).ToList(), allowFinBertNetwork, out probs, out err);
                if (err != null) BgLogOnce("fbpre9", "Pre-filtre FinBERT partiel : " + err + " (titres non notes envoyes aux 3 LLM)");
                for (int i = 0; i < n; i++)
                    if (probs[i] != null && Math.Abs(NxFinBertClient.ScoreOf(probs[i])) < FinBertNeutralThreshold)
                    {
                        send[i] = false; kind[i] = 0; finals[i] = 0.0;
                        System.Threading.Interlocked.Increment(ref finbertFiltered);
                    }
            }
            string company = CompanyOf(s.Name);
            NxLlmConfig[] models = { MainLlm, deepSeek, gemini };
            List<int> idx = Enumerable.Range(0, n).Where(i => send[i]).ToList();
            List<Func<NxLlmResult>> jobs = new List<Func<NxLlmResult>>();
            foreach (int i in idx)
            {
                string user = NxPrompts.Headline5(s.Name, company, items[i].Headline, ContextFor(s, items[i].PublishedUtc.Date));
                foreach (NxLlmConfig m in models)
                {
                    NxLlmConfig cfg = m;
                    jobs.Add(() => CallLlm(cfg, NxPrompts.HeadlineSystem, user, "fiche9_" + cfg.Provider));
                }
            }
            List<NxLlmResult> res = RunAll(jobs);
            for (int k = 0; k < idx.Count; k++)
            {
                int i = idx[k];
                int[] sc = new int[3];
                bool complete = true;
                for (int m = 0; m < 3; m++)
                {
                    NxLlmResult r = res[k * 3 + m];
                    sc[m] = r != null && r.Ok ? NxPrompts.ParseScore5(r.Text) : int.MinValue;
                    if (sc[m] == int.MinValue) complete = false;
                }
                if (!complete) { kind[i] = -1; continue; }
                bool allPos = sc.All(v => v >= MinAbsScore), allNeg = sc.All(v => v <= -MinAbsScore), allZero = sc.All(v => v == 0);
                if (allPos || allNeg) { kind[i] = 1; finals[i] = sc.Average() / 2.0; }
                else if (allZero) { kind[i] = 0; finals[i] = 0.0; }
                else kind[i] = 2;
            }
            return kind;
        }

        protected override bool ScoreItems(NxSym s, DateTime day, List<NxNewsItem> items, out double score, out int scored, out bool ambiguous, out string detail)
        {
            double[] finals;
            int[] kind = Consensus(s, items, State == State.Realtime || FinBertInBacktest, out finals);
            agreeItems += kind.Count(k => k == 1);
            neutralItems += kind.Count(k => k == 0);
            disagreeItems += kind.Count(k => k == 2);
            incompleteItems += kind.Count(k => k == -1);
            ambiguous = kind.Any(k => k == 2);
            List<double> valid = Enumerable.Range(0, kind.Length).Where(i => kind[i] == 0 || kind[i] == 1).Select(i => finals[i]).ToList();
            scored = valid.Count;
            score = scored > 0 ? valid.Average() : double.NaN;
            string[] lbl = { "neutre", "accord", "DESACCORD" };
            detail = string.Join(" | ", items.Select((it, i) => (kind[i] < 0 ? "incomplet" : lbl[kind[i]]) + (NxMath.Ok(finals[i]) ? " " + finals[i].ToString("+0.00;-0.00;0", CultureInfo.InvariantCulture) : "") + " " + NxText.OneLine(it.Headline, 80)));
            return scored > 0 || ambiguous;
        }

        protected override void AfterSymbolDay(NxSym s, DateTime day, bool ok, double score, int scored, bool ambiguous)
        {
            // Rendement absolu du lendemain selon le jour precedent (accord / desaccord).
            int prev;
            if (pendingFlag.TryGetValue(s.Name, out prev) && s.Hist.Count >= 2)
            {
                double r = Math.Abs(s.Hist.LogReturnAt(s.Hist.Count - 1));
                if (NxMath.Ok(r)) { if (prev == 2) nextAbsAfterDisagree.Add(r); else nextAbsAfterAgree.Add(r); }
                pendingFlag.Remove(s.Name);
            }
            if (ambiguous) pendingFlag[s.Name] = 2;
            else if (ok && scored > 0) pendingFlag[s.Name] = 1;
        }

        protected override void NxPrescore(List<NxNewsItem> fresh)
        {
            foreach (IGrouping<string, NxNewsItem> g in fresh.Where(x => IncludeSocialInScore || !x.IsSocial).GroupBy(x => x.Symbol))
            {
                NxSym s = Sym(g.Key);
                double[] f;
                if (s != null) Consensus(s, g.ToList(), true, out f);
            }
        }

        protected override void NxReportExtras(List<string> lines)
        {
            AddNewsReport(lines);
            lines.Add(string.Format(CultureInfo.InvariantCulture, "Titres : accord {0} | neutres {1} | desaccord {2} | incomplets {3} | filtres FinBERT {4}",
                agreeItems, neutralItems, disagreeItems, incompleteItems, finbertFiltered));
            double ma = nextAbsAfterAgree.Count > 0 ? nextAbsAfterAgree.Average() : double.NaN;
            double md = nextAbsAfterDisagree.Count > 0 ? nextAbsAfterDisagree.Average() : double.NaN;
            double t = NxMath.WelchT(nextAbsAfterDisagree, nextAbsAfterAgree);
            lines.Add(string.Format(CultureInfo.InvariantCulture, "|Rendement| du lendemain : apres desaccord {0:P2} (n={1}) vs apres accord {2:P2} (n={3}), t de Welch {4:F2}",
                md, nextAbsAfterDisagree.Count, ma, nextAbsAfterAgree.Count, t));
            if (NxMath.Ok(t) && t > 2) lines.Add("-> Le desaccord precede des mouvements plus volatils : l utiliser comme filtre de risque (fiche 9).");
            lines.Add("Le consensus reduit fortement le nombre de signaux : prevoir plus de semaines de paper pour atteindre 30 trades.");
        }

        #region Proprietes
        [Display(Name = "DeepSeek : modele", Order = 1, GroupName = "02. Fiche 9 - Consensus")]
        public string DeepSeekModel { get; set; }

        [Display(Name = "DeepSeek : cle (vide = DEEPSEEK_API_KEY)", Order = 2, GroupName = "02. Fiche 9 - Consensus")]
        public string DeepSeekApiKey { get; set; }

        [Range(0.0, 1000.0)]
        [Display(Name = "DeepSeek : prix entree ($/M)", Order = 3, GroupName = "02. Fiche 9 - Consensus")]
        public double DeepSeekPriceIn { get; set; }

        [Range(0.0, 1000.0)]
        [Display(Name = "DeepSeek : prix sortie ($/M)", Order = 4, GroupName = "02. Fiche 9 - Consensus")]
        public double DeepSeekPriceOut { get; set; }

        [Display(Name = "Gemini : modele", Order = 5, GroupName = "02. Fiche 9 - Consensus")]
        public string GeminiModel { get; set; }

        [Display(Name = "Gemini : cle (vide = GEMINI_API_KEY)", Order = 6, GroupName = "02. Fiche 9 - Consensus")]
        public string GeminiApiKey { get; set; }

        [Range(0.0, 1000.0)]
        [Display(Name = "Gemini : prix entree ($/M)", Order = 7, GroupName = "02. Fiche 9 - Consensus")]
        public double GeminiPriceIn { get; set; }

        [Range(0.0, 1000.0)]
        [Display(Name = "Gemini : prix sortie ($/M)", Order = 8, GroupName = "02. Fiche 9 - Consensus")]
        public double GeminiPriceOut { get; set; }

        [Range(64, 32000)]
        [Display(Name = "Gemini : tokens max", Description = "Les modeles 2.5 comptent leur reflexion dans ce budget.", Order = 9, GroupName = "02. Fiche 9 - Consensus")]
        public int GeminiMaxTokens { get; set; }

        [NinjaScriptProperty]
        [Range(1, 2)]
        [Display(Name = "Accord : |score| minimum", Order = 10, GroupName = "02. Fiche 9 - Consensus")]
        public int MinAbsScore { get; set; }

        [NinjaScriptProperty]
        [Display(Name = "Pre-filtre FinBERT (fiche 10)", Order = 11, GroupName = "02. Fiche 9 - Consensus")]
        public bool UseFinBertPrefilter { get; set; }

        [Range(0.0, 1.0)]
        [Display(Name = "FinBERT : seuil non neutre |score|", Order = 12, GroupName = "02. Fiche 9 - Consensus")]
        public double FinBertNeutralThreshold { get; set; }

        [Display(Name = "FinBERT en backtest", Order = 13, GroupName = "02. Fiche 9 - Consensus")]
        public bool FinBertInBacktest { get; set; }
        #endregion
    }
}
