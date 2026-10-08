// =============================================================================
//  Nexus08_LlmJudgeVeto.cs   (NinjaTrader 8 / NinjaScript)
//
//  FICHE 8 - LLM juge et veto sur les candidats momentum
//  Les maths choisissent le trade, le LLM ne peut que le BLOQUER (auteur v2 +
//  LordWeirdDude : "pessimiste strict"). [arXiv] Lopez-Lira, Tang.
//
//  REGLES
//   - Entree du juge : candidats des fiches 1 (TSMOM), 2 (XSMOM) et 3 (multi-
//     facteurs) ayant deja passe leurs filtres de prix - memes moteurs de
//     signaux que ces fiches (NexusSignals.cs).
//   - Role : chercher ce que les maths ne voient pas (litiges, revision de
//     previsions, enquete, dilution, changement de direction, fusion).
//   - Donnees fournies : titres des 7 derniers jours + prochaine date de resultats.
//   - Sortie : JSON strict {veto, raison en une phrase, confiance 0..1}.
//   - Veto applique si confiance >= 0.7 ; sinon le trade passe tel quel.
//   - Pouvoir : bloquer ou reduire de moitie ; jamais augmenter, jamais creer.
//   - Option classement (markwmke) : classer les candidats par risque et
//     retirer le quart le plus risque.
//
//  MESURER SI LE JUGE SERT A QUELQUE CHOSE
//   1. Chaque veto est journalise avec le trade "fantome" qu il a bloque.
//   2. Les trades acceptes sont suivis avec EXACTEMENT les memes regles
//      fantomes (entree a l ouverture suivante, stop ATR, sortie a N jours).
//   3. Apres au moins 30 vetos : comparaison des rendements moyens (t de Welch).
//   4. Garder le juge seulement si les trades bloques font nettement moins bien.
//   Alerte si le taux de veto depasse 25 % des candidats (revoir la consigne).
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
    public enum Nexus08Source { TSMOM_Fiche1, XSMOM_Fiche2, MultiFacteur_Fiche3, Union }
    public enum Nexus08VetoAction { Bloquer, ReduireDeMoitie }
    public enum Nexus08JudgeMode { Veto, Classement, VetoPuisClassement }

    public class Nexus08LlmJudgeVeto : NexusLlmStrategyBase
    {
        private class Shadow
        {
            public string Symbol;
            public DateTime Decision;
            public int StartIndex;
            public double StopDistance;
            public double Entry = double.NaN, Exit = double.NaN, Stop = double.NaN;
            public int EntryIndex = -1;
            public bool Done, Vetoed;
            public string Reason = "";
            public double Confidence;
            public double Return { get { return Done && Entry > 0 ? Exit / Entry - 1 : double.NaN; } }
        }

        private class Verdict { public bool Ok, Veto; public string Reason = ""; public double Confidence; public double Risk = double.NaN; }

        private NxFundamentals fund;
        private NxMultiFactorEngine mfEngine;
        private readonly HashSet<string> tsSet = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        private readonly HashSet<string> xsSet = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        private readonly HashSet<string> mfSet = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        private readonly List<Shadow> shadows = new List<Shadow>();
        private int candidates, vetoes, halved, rankRemoved, judgeErrors, rebalances;

        protected override void NxLlmSetDefaults()
        {
            Name = "Nexus08_LlmJudgeVeto";
            Description = "Fiche 8 - Candidats momentum (fiches 1-3) soumis a un LLM 'pessimiste strict' : veto si confiance >= 0.7 (bloquer ou /2), option classement ; suivi fantome des trades bloques vs acceptes.";
            Symbols = "SPY,QQQ,XLF,XLV,XLE,XLI,XLY,XLP,XLU,XLB,XLRE,XLC,AAPL,MSFT,NVDA,AMZN,GOOGL,META,JPM,JNJ,XOM,UNH,V,PG,HD";
            SizingMode = NxSizingMode.Natif;
            LlmMaxTokens = 400;

            Source = Nexus08Source.Union;
            JudgeMode = Nexus08JudgeMode.Veto;
            VetoAction = Nexus08VetoAction.Bloquer;
            VetoConfidence = 0.7;
            RankRemovePct = 25.0;
            HeadlineDays = 7;
            MaxVetoRatePct = 25.0;
            MinVetosForTest = 30;
            ShadowHoldDays = 21;
            LookbackDays = 252;
            SkipDays = 21;
            TargetVolPct = 12.0;
            VolWindowDays = 126;
            XsTop = 0;
            XsBuffer = 0;
            MfTop = 5;
            MfBuffer = 8;
            FundamentalsFile = "fundamentals.csv";
            AtrMultiplier = 3.0;
            StopMinPct = 2.0;
            StopMaxPct = 8.0;
            Barometer = "SPY";
            UsePanicState = true;
            PanicMultiplier = 0.5;
        }

        protected override IEnumerable<string> NxRequiredReferences() { return new[] { Barometer }; }

        protected override void NxLlmDataLoaded()
        {
            if (Source == Nexus08Source.MultiFacteur_Fiche3 || Source == Nexus08Source.Union)
            {
                fund = new NxFundamentals();
                string msg;
                fund.Load(NxPaths.Resolve(FundamentalsFile, NxPaths.Data), out msg);
                Nx("Fondamentaux (fiche 3) : " + msg);
                mfEngine = new NxMultiFactorEngine(fund);
            }
        }

        private bool Uses(Nexus08Source s) { return Source == s || Source == Nexus08Source.Union; }

        protected override void NxOnBatch(DateTime day)
        {
            UpdateShadows();
            List<NxSym> traded = TradedSyms;
            NxSym baro = Sym(Barometer);
            Dictionary<string, double> mom = new Dictionary<string, double>(StringComparer.OrdinalIgnoreCase);
            foreach (NxSym s in traded) { double m = NxMomentum.Return12_1(s.Hist, LookbackDays, SkipDays); if (NxMath.Ok(m)) mom[s.Name] = m; }
            if (mom.Count < 4) return;
            string pd;
            bool panic = UsePanicState && baro != null && NxPanicState.Evaluate(baro.Hist, 504, 21, 252, out pd);

            // --- Ensembles desires par source (memes regles que les fiches 1, 2, 3).
            bool monthly = (Uses(Nexus08Source.TSMOM_Fiche1) || Uses(Nexus08Source.XSMOM_Fiche2)) && IsRebalanceDay(day, NxRebalance.Mensuel, baro ?? traded[0]);
            HashSet<string> held = new HashSet<string>(traded.Where(s => s.Qty > 0 || s.TargetQty > 0).Select(s => s.Name), StringComparer.OrdinalIgnoreCase);
            if (monthly)
            {
                rebalances++;
                foreach (NxSym s in traded) s.StoppedOut = false;
                if (Uses(Nexus08Source.TSMOM_Fiche1)) { tsSet.Clear(); foreach (KeyValuePair<string, double> kv in mom) if (kv.Value > 0) tsSet.Add(kv.Key); }
                if (Uses(Nexus08Source.XSMOM_Fiche2))
                {
                    int n = mom.Count;
                    int top = XsTop > 0 ? XsTop : Math.Max(1, (int)Math.Round(n / 4.0));
                    int buf = XsBuffer > 0 ? Math.Max(top, XsBuffer) : Math.Max(top, (int)Math.Round(n * 0.36));
                    List<string> sel = NxRankSelection.SelectWithBuffer(mom, new HashSet<string>(held.Where(xsSet.Contains), StringComparer.OrdinalIgnoreCase), top, buf);
                    xsSet.Clear(); foreach (string x in sel) xsSet.Add(x);
                }
            }
            if (Uses(Nexus08Source.MultiFacteur_Fiche3) && mfEngine != null)
            {
                Dictionary<string, NxBarHistory> stocks = traded.Where(s => s.Class == NxAssetClass.Action).ToDictionary(s => s.Name, s => s.Hist, StringComparer.OrdinalIgnoreCase);
                NxMultiFactorResult res = mfEngine.Update(day, stocks, baro != null ? baro.Hist : null);
                if (res.Scored >= Math.Min(8, stocks.Count))
                {
                    List<string> sel = NxRankSelection.SelectWithBuffer(res.Composite, new HashSet<string>(held.Where(mfSet.Contains), StringComparer.OrdinalIgnoreCase), MfTop, MfBuffer);
                    mfSet.Clear(); foreach (string x in sel) mfSet.Add(x);
                }
            }
            HashSet<string> desired = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
            if (Uses(Nexus08Source.TSMOM_Fiche1)) desired.UnionWith(tsSet);
            if (Uses(Nexus08Source.XSMOM_Fiche2)) desired.UnionWith(xsSet);
            if (Uses(Nexus08Source.MultiFacteur_Fiche3)) desired.UnionWith(mfSet);

            // --- Sorties : le juge n intervient pas (il ne peut que bloquer des entrees).
            foreach (NxSym s in traded)
                if ((s.Qty > 0 || s.TargetQty > 0) && !desired.Contains(s.Name)) SetTarget(s, 0, double.NaN, "plus candidat (" + Source + ")");

            // --- Nouveaux candidats -> juge.
            List<NxSym> cands = traded.Where(s => desired.Contains(s.Name) && s.Qty == 0 && s.TargetQty == 0 && !s.StoppedOut).ToList();
            if (cands.Count == 0) return;
            candidates += cands.Count;
            Dictionary<NxSym, Verdict> verdicts = Judge(cands, day);
            HashSet<NxSym> removedByRank = new HashSet<NxSym>();
            if (JudgeMode != Nexus08JudgeMode.Veto)
            {
                List<NxSym> ranked = cands.Where(c => verdicts[c].Ok && NxMath.Ok(verdicts[c].Risk)).OrderByDescending(c => verdicts[c].Risk).ToList();
                int k = (int)Math.Ceiling(ranked.Count * RankRemovePct / 100.0);
                foreach (NxSym c in ranked.Take(k)) removedByRank.Add(c);
            }

            int nValid = mom.Count;
            foreach (NxSym s in cands)
            {
                Verdict v = verdicts[s];
                bool vetoed = (JudgeMode != Nexus08JudgeMode.Classement) && v.Ok && v.Veto && v.Confidence >= VetoConfidence;
                bool ranked = removedByRank.Contains(s);
                double dist = NxAtrStop.Distance(s.LastPrice, s.Hist.Atr, AtrMultiplier, StopMinPct / 100.0, StopMaxPct / 100.0);
                bool blocked = ranked || (vetoed && VetoAction == Nexus08VetoAction.Bloquer);
                shadows.Add(new Shadow
                {
                    Symbol = s.Name, Decision = day, StartIndex = s.Hist.Count, StopDistance = dist, Vetoed = blocked,
                    Reason = ranked ? "classement : quart le plus risque (risque " + v.Risk.ToString("F2", CultureInfo.InvariantCulture) + ")" : v.Reason,
                    Confidence = v.Confidence
                });
                if (vetoed) vetoes++;
                if (ranked) rankRemoved++;
                if (blocked)
                {
                    NxSignal(NowNt, s.Name, "veto", string.Format(CultureInfo.InvariantCulture, "{0} (confiance {1:F2})", ranked ? "classement" : v.Reason, v.Confidence));
                    Nx(string.Format(CultureInfo.InvariantCulture, "VETO {0} : {1} (confiance {2:F2})", s.Name, ranked ? "quart le plus risque" : v.Reason, v.Confidence));
                    continue;
                }
                double w = NxMomentum.InverseVolWeight(s.Hist, TargetVolPct / 100.0, VolWindowDays, nValid, 0);
                if (!NxMath.Ok(w)) continue;
                if (panic && (Uses(Nexus08Source.TSMOM_Fiche1) || Uses(Nexus08Source.XSMOM_Fiche2))) w *= PanicMultiplier;
                if (vetoed && VetoAction == Nexus08VetoAction.ReduireDeMoitie) { w *= 0.5; halved++; }
                string det;
                int q = SizeQty(s, w, s.LastPrice, double.NaN, out det);
                SetTarget(s, q, s.LastPrice - dist, string.Format(CultureInfo.InvariantCulture, "candidat {0} accepte par le juge{1}", Source, vetoed ? " (taille /2)" : ""));
                NxSignal(NowNt, s.Name, "juge_ok", string.Format(CultureInfo.InvariantCulture, "veto={0} conf={1:F2} risque={2:F2} | {3} | {4}", v.Veto, v.Confidence, v.Risk, v.Reason, det));
            }
            double rate = candidates > 0 ? (double)(vetoes + rankRemoved) / candidates : 0;
            if (candidates >= 8 && rate > MaxVetoRatePct / 100.0)
                NxOnce("vetorate" + (int)(rate * 10), string.Format(CultureInfo.InvariantCulture, "ATTENTION : taux de veto {0:P0} > {1:F0} % des candidats -> le juge transforme le momentum en faible exposition ; revoir la consigne.", rate, MaxVetoRatePct));
        }

        private Dictionary<NxSym, Verdict> Judge(List<NxSym> cands, DateTime day)
        {
            Dictionary<NxSym, Verdict> res = new Dictionary<NxSym, Verdict>();
            List<Func<Verdict>> jobs = new List<Func<Verdict>>();
            foreach (NxSym s in cands)
            {
                NxSym c = s;
                List<NxNewsItem> heads = RecentHeadlines(c, day, HeadlineDays);
                DateTime? nx = Earnings.Next(c.Name, day);
                string earn = nx.HasValue ? nx.Value.ToString("yyyy-MM-dd", CultureInfo.InvariantCulture) : "";
                string src = Source.ToString();
                jobs.Add(() =>
                {
                    Verdict v = new Verdict();
                    if (JudgeMode != Nexus08JudgeMode.Classement)
                    {
                        NxLlmResult r = CallLlm(MainLlm, NxPrompts.JudgeSystem, NxPrompts.JudgeUser(c.Name, CompanyOf(c.Name), src, 21, day, earn, heads), "fiche8_veto");
                        bool veto; string reason; double conf;
                        if (r.Ok && NxPrompts.ParseJudge(r.Text, out veto, out reason, out conf)) { v.Ok = true; v.Veto = veto; v.Reason = reason; v.Confidence = conf; }
                        else v.Reason = r.Ok ? "JSON illisible" : r.Error;
                    }
                    if (JudgeMode != Nexus08JudgeMode.Veto)
                    {
                        NxLlmResult r = CallLlm(MainLlm, NxPrompts.JudgeSystem, NxPrompts.RiskRankUser(c.Name, CompanyOf(c.Name), src, day, earn, heads), "fiche8_classement");
                        double risk; string reason;
                        if (r.Ok && NxPrompts.ParseRisk(r.Text, out risk, out reason)) { v.Ok = true; v.Risk = risk; if (string.IsNullOrEmpty(v.Reason)) v.Reason = reason; }
                    }
                    return v;
                });
            }
            List<Verdict> out_ = RunAll(jobs);
            FlushBgLog();
            for (int i = 0; i < cands.Count; i++)
            {
                Verdict v = out_[i] ?? new Verdict { Reason = "delai depasse" };
                if (!v.Ok) judgeErrors++;   // pas de reponse : le trade passe tel quel (le juge ne fait que bloquer)
                res[cands[i]] = v;
            }
            return res;
        }

        private void UpdateShadows()
        {
            foreach (Shadow sh in shadows)
            {
                if (sh.Done) continue;
                NxSym s = Sym(sh.Symbol);
                if (s == null) { sh.Done = true; continue; }
                NxBarHistory h = s.Hist;
                if (sh.EntryIndex < 0)
                {
                    if (h.Count <= sh.StartIndex) continue;
                    sh.EntryIndex = sh.StartIndex;
                    sh.Entry = h.Open[sh.EntryIndex];
                    sh.Stop = sh.Entry - (NxMath.Ok(sh.StopDistance) ? sh.StopDistance : 0.08 * sh.Entry);
                }
                for (int i = sh.EntryIndex; i < h.Count && !sh.Done; i++)
                {
                    if (h.Low[i] <= sh.Stop) { sh.Exit = Math.Min(h.Open[i], sh.Stop); sh.Done = true; }
                    else if (i - sh.EntryIndex + 1 >= ShadowHoldDays) { sh.Exit = h.Close[i]; sh.Done = true; }
                }
            }
        }

        protected override void NxReportExtras(List<string> lines)
        {
            UpdateShadows();
            List<double> blocked = shadows.Where(x => x.Vetoed && x.Done).Select(x => x.Return).Where(NxMath.Ok).ToList();
            List<double> accepted = shadows.Where(x => !x.Vetoed && x.Done).Select(x => x.Return).Where(NxMath.Ok).ToList();
            double rate = candidates > 0 ? (double)(vetoes + rankRemoved) / candidates : 0;
            lines.Add(string.Format(CultureInfo.InvariantCulture, "Source : {0} | mode : {1} / {2} | reequilibrages {3}", Source, JudgeMode, VetoAction, rebalances));
            lines.Add(string.Format(CultureInfo.InvariantCulture, "Candidats juges : {0} | vetos (conf >= {1:F2}) : {2} | retires par classement : {3} | tailles /2 : {4} | sans reponse : {5} | taux {6:P1}",
                candidates, VetoConfidence, vetoes, rankRemoved, halved, judgeErrors, rate));
            if (rate > MaxVetoRatePct / 100.0) lines.Add("ALERTE : taux de veto > " + MaxVetoRatePct + " % -> revoir la consigne (juge trop severe).");
            double t = NxMath.WelchT(blocked, accepted);
            lines.Add(string.Format(CultureInfo.InvariantCulture, "Trades fantomes ({0} j, stop ATR) : bloques {1} (moy {2:P2}) vs acceptes {3} (moy {4:P2}) | t de Welch {5:F2}",
                ShadowHoldDays, blocked.Count, blocked.Count > 0 ? blocked.Average() : double.NaN, accepted.Count, accepted.Count > 0 ? accepted.Average() : double.NaN, t));
            if (blocked.Count < MinVetosForTest) lines.Add("Moins de " + MinVetosForTest + " vetos resolus : pas encore de conclusion sur l utilite du juge.");
            else if (NxMath.Ok(t) && t < -2) lines.Add("CONCLUSION : les trades bloques font nettement moins bien -> GARDER le juge.");
            else lines.Add("CONCLUSION : pas de difference nette -> le juge ne fait que reduire l exposition au hasard ; le retirer.");
            foreach (Shadow sh in shadows.Where(x => x.Vetoed).Skip(Math.Max(0, shadows.Count(x => x.Vetoed) - 10)))
                lines.Add(string.Format(CultureInfo.InvariantCulture, "  veto {0:yyyy-MM-dd} {1,-6} {2,8} : {3}", sh.Decision, sh.Symbol, NxMath.Ok(sh.Return) ? sh.Return.ToString("P2", CultureInfo.InvariantCulture) : "en cours", NxText.OneLine(sh.Reason, 100)));
        }

        #region Proprietes
        [NinjaScriptProperty]
        [Display(Name = "Source des candidats", Order = 1, GroupName = "01. Fiche 8 - Juge LLM")]
        public Nexus08Source Source { get; set; }

        [NinjaScriptProperty]
        [Display(Name = "Mode du juge", Order = 2, GroupName = "01. Fiche 8 - Juge LLM")]
        public Nexus08JudgeMode JudgeMode { get; set; }

        [NinjaScriptProperty]
        [Display(Name = "Action du veto", Order = 3, GroupName = "01. Fiche 8 - Juge LLM")]
        public Nexus08VetoAction VetoAction { get; set; }

        [NinjaScriptProperty]
        [Range(0.0, 1.0)]
        [Display(Name = "Confiance minimale du veto", Order = 4, GroupName = "01. Fiche 8 - Juge LLM")]
        public double VetoConfidence { get; set; }

        [Range(0.0, 100.0)]
        [Display(Name = "Classement : part retiree (%)", Order = 5, GroupName = "01. Fiche 8 - Juge LLM")]
        public double RankRemovePct { get; set; }

        [Range(1, 60)]
        [Display(Name = "Titres sur (jours)", Order = 6, GroupName = "01. Fiche 8 - Juge LLM")]
        public int HeadlineDays { get; set; }

        [Range(1.0, 100.0)]
        [Display(Name = "Alerte taux de veto (%)", Order = 7, GroupName = "01. Fiche 8 - Juge LLM")]
        public double MaxVetoRatePct { get; set; }

        [Range(1, 10000)]
        [Display(Name = "Vetos avant conclusion", Order = 8, GroupName = "01. Fiche 8 - Juge LLM")]
        public int MinVetosForTest { get; set; }

        [Range(1, 252)]
        [Display(Name = "Fantomes : horizon (jours)", Order = 9, GroupName = "01. Fiche 8 - Juge LLM")]
        public int ShadowHoldDays { get; set; }

        [Range(42, 1000)]
        [Display(Name = "Momentum : fenetre (jours)", Order = 10, GroupName = "01. Fiche 8 - Juge LLM")]
        public int LookbackDays { get; set; }

        [Range(0, 252)]
        [Display(Name = "Momentum : mois exclu (jours)", Order = 11, GroupName = "01. Fiche 8 - Juge LLM")]
        public int SkipDays { get; set; }

        [Range(1.0, 100.0)]
        [Display(Name = "Volatilite cible (%)", Order = 12, GroupName = "01. Fiche 8 - Juge LLM")]
        public double TargetVolPct { get; set; }

        [Range(20, 756)]
        [Display(Name = "Fenetre de vol (jours)", Order = 13, GroupName = "01. Fiche 8 - Juge LLM")]
        public int VolWindowDays { get; set; }

        [Range(0, 500)]
        [Display(Name = "XSMOM : titres (0 = quartile)", Order = 14, GroupName = "01. Fiche 8 - Juge LLM")]
        public int XsTop { get; set; }

        [Range(0, 500)]
        [Display(Name = "XSMOM : tampon (0 = auto)", Order = 15, GroupName = "01. Fiche 8 - Juge LLM")]
        public int XsBuffer { get; set; }

        [Range(1, 100)]
        [Display(Name = "Multi-facteurs : top N", Order = 16, GroupName = "01. Fiche 8 - Juge LLM")]
        public int MfTop { get; set; }

        [Range(1, 200)]
        [Display(Name = "Multi-facteurs : tampon", Order = 17, GroupName = "01. Fiche 8 - Juge LLM")]
        public int MfBuffer { get; set; }

        [Display(Name = "Fichier de fondamentaux", Order = 18, GroupName = "01. Fiche 8 - Juge LLM")]
        public string FundamentalsFile { get; set; }

        [Range(0.5, 20.0)]
        [Display(Name = "Stop : multiplicateur ATR(14)", Order = 19, GroupName = "01. Fiche 8 - Juge LLM")]
        public double AtrMultiplier { get; set; }

        [Range(0.1, 50.0)]
        [Display(Name = "Stop : borne basse (%)", Order = 20, GroupName = "01. Fiche 8 - Juge LLM")]
        public double StopMinPct { get; set; }

        [Range(0.1, 50.0)]
        [Display(Name = "Stop : borne haute (%)", Order = 21, GroupName = "01. Fiche 8 - Juge LLM")]
        public double StopMaxPct { get; set; }

        [Display(Name = "Barometre", Order = 22, GroupName = "01. Fiche 8 - Juge LLM")]
        public string Barometer { get; set; }

        [Display(Name = "Etat de panique (fiches 1-2)", Order = 23, GroupName = "01. Fiche 8 - Juge LLM")]
        public bool UsePanicState { get; set; }

        [Range(0.0, 1.0)]
        [Display(Name = "Panique : multiplicateur", Order = 24, GroupName = "01. Fiche 8 - Juge LLM")]
        public double PanicMultiplier { get; set; }
        #endregion
    }
}
