// =============================================================================
//  NexusLlmStrategyBase.cs   (NinjaTrader 8 / NinjaScript)
//
//  Deux socles abstraits pour les fiches qui utilisent des actualites et des LLM :
//
//  NexusLlmStrategyBase (fiches 7, 8, 9, 10)
//    - configuration du LLM principal (Claude par defaut), cles API resolues
//      depuis la propriete, la variable d environnement ou Nexus\keys.txt
//    - cache disque des reponses : un backtest deja paye se rejoue gratuitement
//    - budget d appels par run ; appels en backtest desactives par defaut
//      (seules les reponses en cache sont utilisees)
//    - appels paralleles bornes en temps (temps reel : RealtimeMaxWaitSeconds)
//    - stock d actualites (CSV historique + news_live.csv alimente en reel),
//      dedoublonnage, Fear & Greed crypto, calendrier des resultats
//    - collecte temps reel NewsAPI (requetes groupees) et Reddit, puis
//      pre-notation en tache de fond (le cache est chaud au moment de decider)
//
//  NexusNewsEventBase (fiches 7, 9, 10) - regles communes de la fiche 7 :
//    - horodatage : titre publie avant l ouverture -> trade a l ouverture du jour ;
//      apres -> ouverture du lendemain. La fenetre d un jour de decision est donc
//      ]ouverture precedente - marge ; ouverture suivante - marge], la marge
//      valant NewsCutoffMinutes + DataDelayMinutes.
//    - agregation : moyenne des scores du jour par symbole
//    - entree long : score >= +0.5 avec au moins 2 titres distincts
//    - score <= -0.5 : sortie de la position existante / entree interdite
//    - detention : 1 jour de bourse (ouverture -> ouverture suivante)
//    - Reddit separe du flux NewsAPI et exclu du score par defaut
// =============================================================================

#region Using declarations
using System;
using System.Collections.Concurrent;
using System.Collections.Generic;
using System.ComponentModel.DataAnnotations;
using System.Globalization;
using System.IO;
using System.Linq;
using System.Threading;
using System.Threading.Tasks;
using NinjaTrader.Cbi;
using NinjaTrader.Data;
using NinjaTrader.NinjaScript;
using NinjaTrader.NinjaScript.AddOns.Nexus;
#endregion

namespace NinjaTrader.NinjaScript.Strategies
{
    public abstract class NexusLlmStrategyBase : NexusStrategyBase
    {
        protected NxLlmConfig MainLlm;
        protected NxLlmCache LlmCache;
        protected NxNewsStore News;
        protected NxFearGreed FearGreed;
        protected NxEarningsCalendar Earnings;
        protected NxFinBertClient FinBert;
        protected Dictionary<string, string> Companies;
        private readonly ConcurrentQueue<string> bgLog = new ConcurrentQueue<string>();
        private readonly HashSet<string> bgOnce = new HashSet<string>();
        private int apiCalls, apiRefusals;
        private Timer newsTimer;
        private int newsBusy;
        private DateTime lastNewsFetchUtc = DateTime.MinValue, lastFgRefreshUtc = DateTime.MinValue, lastEarnRefreshUtc = DateTime.MinValue;
        private List<string> liveSymbols = new List<string>();

        protected int ApiCalls { get { return apiCalls; } }
        protected int ApiRefusals { get { return apiRefusals; } }
        protected string LiveNewsFile { get { return Path.Combine(NxPaths.Data, "news_live.csv"); } }

        // ----- Points d extension -----
        protected abstract void NxLlmSetDefaults();
        protected virtual void NxLlmDataLoaded() { }
        protected virtual void NxLlmOnRealtime() { }
        protected virtual void NxLlmOnTimer() { }
        protected virtual void NxLlmOnTerminated() { }
        /// <summary>Titres frais recus en temps reel (fil de fond) : pre-noter pour chauffer le cache.</summary>
        protected virtual void NxPrescore(List<NxNewsItem> fresh) { }

        protected sealed override void NxSetDefaults()
        {
            LlmProvider = NxLlmProvider.Claude;
            LlmModel = "claude-opus-5-5";
            LlmApiKey = "";
            LlmTemperature = 0.0;
            LlmMaxTokens = 300;
            LlmTimeoutSec = 60;
            LlmPriceInPerMTok = 0.0;
            LlmPriceOutPerMTok = 0.0;
            ApiCallsInHistorical = false;
            MaxApiCallsPerRun = 500;
            MaxParallelCalls = 4;
            RealtimeMaxWaitSeconds = 25;

            NewsFile = "news.csv";
            CompanyNames = "SPY=S&P 500;QQQ=Nasdaq 100;AAPL=Apple;MSFT=Microsoft;NVDA=Nvidia;AMZN=Amazon;GOOGL=Alphabet;META=Meta Platforms;JPM=JPMorgan;JNJ=Johnson & Johnson;"
                         + "XOM=Exxon Mobil;UNH=UnitedHealth;V=Visa;PG=Procter & Gamble;HD=Home Depot;TSLA=Tesla;BTCUSD=Bitcoin;ETHUSD=Ethereum;SOLUSD=Solana;XRPUSD=XRP";
            UseNewsApiLive = false;
            NewsApiKey = "";
            NewsPollMinutes = 60;
            UseRedditLive = false;
            RedditSubs = "stocks,investing,wallstreetbets,CryptoCurrency";
            IncludeSocialInScore = false;
            UseFearGreed = true;
            FearGreedUrl = "https://api.alternative.me/fng/?limit=0&format=json";
            NewsCutoffMinutes = 5;
            DedupJaccardPct = 60.0;
            EarningsFile = "earnings.csv";
            AlphaVantageKey = "";
            FinBertUrl = "http://127.0.0.1:8765/score";

            NxLlmSetDefaults();
        }

        protected sealed override void NxDataLoaded()
        {
            MainLlm = BuildConfig(LlmProvider, LlmModel, LlmApiKey, LlmTemperature, LlmMaxTokens, LlmTimeoutSec, LlmPriceInPerMTok, LlmPriceOutPerMTok);
            LlmCache = NxLlmCache.Get(Path.Combine(NxPaths.Cache, "llm_cache.tsv"));
            FinBert = new NxFinBertClient(Path.Combine(NxPaths.Cache, "finbert_cache.csv")) { Url = FinBertUrl };
            Companies = NxText.ParseMap(CompanyNames);
            NxAiLedger.Reset(StrategyId);

            News = new NxNewsStore { DedupJaccard = DedupJaccardPct / 100.0 };
            List<string> names = Syms.Select(x => x.Name).ToList();
            string msg;
            News.LoadCsv(NxPaths.Resolve(NewsFile, NxPaths.Data), names, out msg);
            Nx("Actualites : " + msg);
            if (File.Exists(LiveNewsFile)) { News.LoadCsv(LiveNewsFile, names, out msg); Nx("Actualites collectees en reel : " + msg); }

            FearGreed = new NxFearGreed();
            FearGreed.LoadCache();
            if (UseFearGreed && Syms.Any(x => x.Class == NxAssetClass.Crypto) && FearGreed.Count == 0 && !IsOptimizing)
            {
                string err = null;
                Task<bool> t = Task.Run(() => FearGreed.Refresh(FearGreedUrl, out err));
                if (t.Wait(15000) && t.Result) Nx("Fear & Greed : " + FearGreed.Count + " jours charges");
                else Nx("Fear & Greed indisponible : " + (err ?? "delai depasse"));
            }

            Earnings = new NxEarningsCalendar();
            Earnings.Load(NxPaths.Resolve(EarningsFile, NxPaths.Data), out msg);
            Nx("Resultats : " + msg);

            string key = MainLlm.ApiKey;
            Nx(string.Format(CultureInfo.InvariantCulture, "LLM principal {0} (cle {1}) | appels en backtest : {2} | budget {3} appels | cache {4} reponses",
                MainLlm.Label, NxSecrets.Mask(key), ApiCallsInHistorical ? "OUI" : "non (cache seul)", MaxApiCallsPerRun, LlmCache.Count));
            NxLlmDataLoaded();
        }

        protected sealed override void NxOnRealtime()
        {
            liveSymbols = TradedSyms.Select(x => x.Name).ToList();
            if ((UseNewsApiLive || UseRedditLive || !string.IsNullOrWhiteSpace(AlphaVantageKey) || UseFearGreed) && newsTimer == null)
            {
                try { newsTimer = new Timer(o => PollNews(), null, 3000, Math.Max(5, NewsPollMinutes) * 60000); }
                catch (Exception ex) { Nx("Collecte d actualites indisponible : " + ex.Message); }
            }
            NxLlmOnRealtime();
        }

        protected sealed override void NxOnTimer()
        {
            FlushBgLog();
            NxLlmOnTimer();
        }

        protected sealed override void NxOnTerminated()
        {
            try { if (newsTimer != null) { newsTimer.Dispose(); newsTimer = null; } } catch { }
            NxLlmOnTerminated();
        }

        // =====================================================================
        //  Appels LLM
        // =====================================================================
        protected NxLlmConfig BuildConfig(NxLlmProvider p, string model, string key, double temp, int maxTok, int timeoutSec, double priceIn, double priceOut)
        {
            return new NxLlmConfig
            {
                Provider = p,
                Model = string.IsNullOrWhiteSpace(model) ? NxLlmConfig.DefaultModel(p) : model.Trim(),
                ApiKey = NxSecrets.Resolve(key, NxLlmConfig.DefaultEnvVar(p)),
                Temperature = temp, MaxTokens = maxTok, TimeoutSec = timeoutSec,
                PriceInPerMTok = priceIn, PriceOutPerMTok = priceOut
            };
        }

        protected bool ApiAllowed(out string why)
        {
            why = null;
            if (State != State.Realtime && !ApiCallsInHistorical) { why = "appels API desactives en backtest (reponse absente du cache)"; return false; }
            if (MaxApiCallsPerRun > 0 && apiCalls >= MaxApiCallsPerRun) { why = "budget d appels atteint (" + MaxApiCallsPerRun + ")"; return false; }
            return true;
        }

        /// <summary>Cache d abord ; sinon appel reel si autorise. Utilisable depuis un fil de fond.</summary>
        protected NxLlmResult CallLlm(NxLlmConfig cfg, string system, string user, string purpose)
        {
            string cached;
            if (LlmCache.TryGet(NxLlm.CacheKey(cfg, system, user, NxPrompts.Version), out cached))
                return new NxLlmResult { Ok = true, Text = cached, FromCache = true, Status = 200 };
            string why;
            if (!ApiAllowed(out why)) { Interlocked.Increment(ref apiRefusals); return new NxLlmResult { Ok = false, Error = why }; }
            Interlocked.Increment(ref apiCalls);
            NxLlmResult r = NxLlm.Complete(cfg, system, user, LlmCache, NxPrompts.Version);
            NxAiLedger.Record(StrategyId, cfg, r, purpose, !IsOptimizing);
            if (!r.Ok) BgLogOnce("llm" + cfg.Provider + (r.Status), "Erreur " + cfg.Label + " : " + r.Error);
            return r;
        }

        /// <summary>Execute des travaux en parallele (MaxParallelCalls) avec un delai global ; default(T) si non termine.</summary>
        protected List<T> RunAll<T>(List<Func<T>> jobs)
        {
            List<T> results = new List<T>(new T[jobs.Count]);
            if (jobs.Count == 0) return results;
            SemaphoreSlim sem = new SemaphoreSlim(Math.Max(1, MaxParallelCalls));
            Task[] tasks = new Task[jobs.Count];
            for (int i = 0; i < jobs.Count; i++)
            {
                int k = i;
                tasks[k] = Task.Run(() =>
                {
                    sem.Wait();
                    try { results[k] = jobs[k](); }
                    catch (Exception ex) { BgLogOnce("job" + ex.GetType().Name, "Erreur d appel : " + ex.Message); }
                    finally { sem.Release(); }
                });
            }
            int timeoutMs = State == State.Realtime ? RealtimeMaxWaitSeconds * 1000
                          : Math.Max(30, LlmTimeoutSec * 4 + 10) * 1000 * Math.Max(1, (jobs.Count + MaxParallelCalls - 1) / Math.Max(1, MaxParallelCalls));
            try { Task.WaitAll(tasks, timeoutMs); } catch { }
            return results;
        }

        protected void BgLog(string m) { bgLog.Enqueue(m); }

        protected void BgLogOnce(string key, string m)
        {
            lock (bgOnce) { if (!bgOnce.Add(key)) return; }
            bgLog.Enqueue(m);
        }

        protected void FlushBgLog()
        {
            string m;
            int k = 0;
            while (k++ < 50 && bgLog.TryDequeue(out m)) Nx(m);
        }

        // =====================================================================
        //  Contexte et donnees
        // =====================================================================
        protected string CompanyOf(string symbol)
        {
            string c;
            return Companies != null && Companies.TryGetValue(symbol, out c) ? c : "";
        }

        /// <summary>Contexte passe au LLM : indice Fear & Greed pour la crypto.</summary>
        protected string ContextFor(NxSym s, DateTime day)
        {
            if (s == null || s.Class != NxAssetClass.Crypto || !UseFearGreed) return "";
            int v; string lbl;
            return FearGreed.TryGet(day, out v, out lbl) ? "Crypto Fear & Greed index on " + day.ToString("yyyy-MM-dd") + ": " + v + " (" + lbl + ")" : "";
        }

        /// <summary>Titres des n derniers jours avant le moment de decision (fiche 8).</summary>
        protected List<NxNewsItem> RecentHeadlines(NxSym s, DateTime day, int days)
        {
            DateTime to = NxTime.NtToUtc(NextSessionBegin(s, day)).AddMinutes(-(NewsCutoffMinutes + EffectiveDataDelayMinutes));
            if (State == State.Realtime) to = DateTime.UtcNow.AddMinutes(-EffectiveDataDelayMinutes) < to ? DateTime.UtcNow.AddMinutes(-EffectiveDataDelayMinutes) : to;
            return News.Get(s.Name, to.AddDays(-days), to, IncludeSocialInScore);
        }

        // =====================================================================
        //  Collecte temps reel (fil de fond)
        // =====================================================================
        private void PollNews()
        {
            if (Interlocked.Exchange(ref newsBusy, 1) == 1) return;
            try
            {
                DateTime now = DateTime.UtcNow;
                DateTime from = lastNewsFetchUtc == DateTime.MinValue ? now.AddHours(-24) : lastNewsFetchUtc.AddMinutes(-30);
                List<NxNewsItem> fresh = new List<NxNewsItem>();
                if (UseNewsApiLive)
                {
                    string key = NxSecrets.Resolve(NewsApiKey, "NEWSAPI_KEY");
                    List<KeyValuePair<string, string>> q = liveSymbols.Select(sy => new KeyValuePair<string, string>(sy, string.IsNullOrWhiteSpace(CompanyOf(sy)) ? sy : CompanyOf(sy))).ToList();
                    for (int i = 0; i < q.Count; i += 8)
                    {
                        string err;
                        Dictionary<string, string> chunk = q.Skip(i).Take(8).ToDictionary(kv => kv.Key, kv => kv.Value, StringComparer.OrdinalIgnoreCase);
                        foreach (NxNewsItem it in NxNewsFetchers.NewsApiBatch(key, chunk, from, out err)) if (News.Add(it)) fresh.Add(it);
                        if (err != null) BgLogOnce("newsapi" + err.Length, "NewsAPI : " + err);
                    }
                }
                if (UseRedditLive)
                {
                    List<string> subs = NxText.SplitList(RedditSubs);
                    foreach (string sy in liveSymbols)
                    {
                        string err;
                        foreach (NxNewsItem it in NxNewsFetchers.Reddit(sy, subs, out err)) if (News.Add(it)) fresh.Add(it);
                        if (err != null) BgLogOnce("reddit", "Reddit : " + err);
                    }
                }
                foreach (NxNewsItem it in fresh) NxCsv.AppendLine(LiveNewsFile, NxNewsItem.CsvHeader, it.ToCsv());
                lastNewsFetchUtc = now;

                if (UseFearGreed && (now - lastFgRefreshUtc).TotalHours >= 12)
                {
                    string err;
                    if (FearGreed.Refresh(FearGreedUrl, out err)) lastFgRefreshUtc = now; else BgLogOnce("fg", "Fear & Greed : " + err);
                }
                if (!string.IsNullOrWhiteSpace(AlphaVantageKey) && (now - lastEarnRefreshUtc).TotalHours >= 24)
                {
                    string err;
                    if (Earnings.RefreshFromAlphaVantage(NxSecrets.Resolve(AlphaVantageKey, "ALPHAVANTAGE_KEY"), NxPaths.Resolve(EarningsFile, NxPaths.Data), out err)) lastEarnRefreshUtc = now;
                    else BgLogOnce("av", "Alpha Vantage : " + err);
                }
                if (fresh.Count > 0)
                {
                    BgLog(fresh.Count + " nouveaux titres collectes (" + string.Join(", ", fresh.Select(x => x.Symbol).Distinct()) + ") -> pre-notation");
                    NxPrescore(fresh);
                }
            }
            catch (Exception ex) { BgLog("Erreur de collecte : " + ex.Message); }
            finally { Interlocked.Exchange(ref newsBusy, 0); }
        }

        #region 70. LLM principal
        [NinjaScriptProperty]
        [Display(Name = "Fournisseur", Order = 1, GroupName = "70. LLM principal")]
        public NxLlmProvider LlmProvider { get; set; }

        [NinjaScriptProperty]
        [Display(Name = "Modele", Description = "claude-opus-5-5 par defaut ; claude-haiku-5-5 pour reduire le cout.", Order = 2, GroupName = "70. LLM principal")]
        public string LlmModel { get; set; }

        [Display(Name = "Cle API (vide = variable d env.)", Description = "ANTHROPIC_API_KEY / DEEPSEEK_API_KEY / GEMINI_API_KEY ou Nexus\\keys.txt.", Order = 3, GroupName = "70. LLM principal")]
        public string LlmApiKey { get; set; }

        [Range(-1.0, 2.0)]
        [Display(Name = "Temperature (-1 = omise)", Order = 4, GroupName = "70. LLM principal")]
        public double LlmTemperature { get; set; }

        [Range(16, 32000)]
        [Display(Name = "Tokens de sortie max", Order = 5, GroupName = "70. LLM principal")]
        public int LlmMaxTokens { get; set; }

        [Range(5, 600)]
        [Display(Name = "Delai par appel (s)", Order = 6, GroupName = "70. LLM principal")]
        public int LlmTimeoutSec { get; set; }

        [Range(0.0, 1000.0)]
        [Display(Name = "Prix entree ($ / M tokens)", Description = "Pour rapporter le cout API au PnL (0 = tokens seulement).", Order = 7, GroupName = "70. LLM principal")]
        public double LlmPriceInPerMTok { get; set; }

        [Range(0.0, 1000.0)]
        [Display(Name = "Prix sortie ($ / M tokens)", Order = 8, GroupName = "70. LLM principal")]
        public double LlmPriceOutPerMTok { get; set; }

        [Display(Name = "Appels API en backtest", Description = "Faux = seules les reponses en cache sont utilisees en historique.", Order = 9, GroupName = "70. LLM principal")]
        public bool ApiCallsInHistorical { get; set; }

        [Range(0, 1000000)]
        [Display(Name = "Budget d appels par run (0 = illimite)", Order = 10, GroupName = "70. LLM principal")]
        public int MaxApiCallsPerRun { get; set; }

        [Range(1, 32)]
        [Display(Name = "Appels paralleles max", Order = 11, GroupName = "70. LLM principal")]
        public int MaxParallelCalls { get; set; }

        [Range(1, 600)]
        [Display(Name = "Attente max en reel (s)", Order = 12, GroupName = "70. LLM principal")]
        public int RealtimeMaxWaitSeconds { get; set; }
        #endregion

        #region 71. Actualites et donnees
        [Display(Name = "Fichier d actualites", Description = "published_utc,symbol,source,headline,url (Nexus\\data).", Order = 1, GroupName = "71. Actualites et donnees")]
        public string NewsFile { get; set; }

        [Display(Name = "Noms des societes", Description = "SYMBOLE=Nom ; utilises dans les consignes et les requetes NewsAPI.", Order = 2, GroupName = "71. Actualites et donnees")]
        public string CompanyNames { get; set; }

        [Display(Name = "NewsAPI en temps reel", Order = 3, GroupName = "71. Actualites et donnees")]
        public bool UseNewsApiLive { get; set; }

        [Display(Name = "Cle NewsAPI (vide = NEWSAPI_KEY)", Order = 4, GroupName = "71. Actualites et donnees")]
        public string NewsApiKey { get; set; }

        [Range(5, 1440)]
        [Display(Name = "Collecte toutes les (min)", Description = "Offre gratuite NewsAPI : ~100 requetes/jour (requetes groupees par 8 symboles).", Order = 5, GroupName = "71. Actualites et donnees")]
        public int NewsPollMinutes { get; set; }

        [Display(Name = "Reddit en temps reel", Order = 6, GroupName = "71. Actualites et donnees")]
        public bool UseRedditLive { get; set; }

        [Display(Name = "Subreddits", Order = 7, GroupName = "71. Actualites et donnees")]
        public string RedditSubs { get; set; }

        [Display(Name = "Inclure Reddit dans le score", Description = "La fiche 7 recommande de l exclure (pas des nouvelles d entreprise).", Order = 8, GroupName = "71. Actualites et donnees")]
        public bool IncludeSocialInScore { get; set; }

        [Display(Name = "Fear & Greed crypto", Order = 9, GroupName = "71. Actualites et donnees")]
        public bool UseFearGreed { get; set; }

        [Display(Name = "URL Fear & Greed", Order = 10, GroupName = "71. Actualites et donnees")]
        public string FearGreedUrl { get; set; }

        [Range(0, 600)]
        [Display(Name = "Marge avant l ouverture (min)", Order = 11, GroupName = "71. Actualites et donnees")]
        public int NewsCutoffMinutes { get; set; }

        [Range(10.0, 100.0)]
        [Display(Name = "Doublons : similarite min (%)", Order = 12, GroupName = "71. Actualites et donnees")]
        public double DedupJaccardPct { get; set; }

        [Display(Name = "Fichier des resultats", Description = "symbol,date (Nexus\\data).", Order = 13, GroupName = "71. Actualites et donnees")]
        public string EarningsFile { get; set; }

        [Display(Name = "Cle Alpha Vantage (resultats)", Description = "Vide = pas de mise a jour automatique (ou ALPHAVANTAGE_KEY).", Order = 14, GroupName = "71. Actualites et donnees")]
        public string AlphaVantageKey { get; set; }

        [Display(Name = "URL du serveur FinBERT", Order = 15, GroupName = "71. Actualites et donnees")]
        public string FinBertUrl { get; set; }
        #endregion
    }

    // =========================================================================
    //  Regles evenementielles communes (fiches 7, 9, 10)
    // =========================================================================
    public abstract class NexusNewsEventBase : NexusLlmStrategyBase
    {
        private class NewsState { public DateTime LastCutoffUtc = DateTime.MinValue; }

        private readonly Dictionary<string, NewsState> nstates = new Dictionary<string, NewsState>(StringComparer.OrdinalIgnoreCase);
        protected int DaysWithNews, ScoredDays, UnscoredDays, AmbiguousDays, EntrySignals, BadNewsExits, HoldExits;

        protected override bool NxBatchMode { get { return false; } }

        /// <summary>
        /// Note les titres d un symbole pour un jour de decision. score dans [-1 ; +1] ; scored = titres notes ;
        /// ambiguous = desaccord (fiche 9) -> pas de trade ce jour. false si rien n a pu etre note.
        /// </summary>
        protected abstract bool ScoreItems(NxSym s, DateTime day, List<NxNewsItem> items, out double score, out int scored, out bool ambiguous, out string detail);

        /// <summary>Apres chaque jour de decision (statistiques propres a la fiche).</summary>
        protected virtual void AfterSymbolDay(NxSym s, DateTime day, bool ok, double score, int scored, bool ambiguous) { }

        protected void SetNewsEventDefaults()
        {
            EntryThreshold = 0.5;
            ExitThreshold = -0.5;
            MinHeadlines = 2;
            HoldDays = 1;
            UseScoreAsConfidence = false;
            UseAtrStop = false;
            AtrMultiplier = 3.0;
            StopMinPct = 2.0;
            StopMaxPct = 8.0;
        }

        protected override void NxOnSymbolBar(NxSym s, DateTime day)
        {
            if (!s.Traded) return;
            NewsState st;
            if (!nstates.TryGetValue(s.Name, out st)) { st = new NewsState(); nstates[s.Name] = st; }

            DateTime toUtc = NxTime.NtToUtc(NextSessionBegin(s, day)).AddMinutes(-(NewsCutoffMinutes + EffectiveDataDelayMinutes));
            if (State == State.Realtime)
            {
                DateTime lim = DateTime.UtcNow.AddMinutes(-EffectiveDataDelayMinutes);
                if (lim < toUtc) toUtc = lim;
            }
            DateTime fromUtc = st.LastCutoffUtc == DateTime.MinValue ? toUtc.AddHours(-24) : st.LastCutoffUtc;
            if (toUtc <= fromUtc) return;
            st.LastCutoffUtc = toUtc;

            List<NxNewsItem> items = News.Get(s.Name, fromUtc, toUtc, IncludeSocialInScore);
            double score = double.NaN;
            int n = 0;
            bool amb = false, ok = false;
            string det = "";
            if (items.Count > 0)
            {
                DaysWithNews++;
                ok = ScoreItems(s, day, items, out score, out n, out amb, out det);
                FlushBgLog();
                if (ok) ScoredDays++; else UnscoredDays++;
                if (amb) AmbiguousDays++;
                NxSignal(NowNt, s.Name, "actualites", string.Format(CultureInfo.InvariantCulture, "fenetre {0:yyyy-MM-dd HH:mm}Z-{1:yyyy-MM-dd HH:mm}Z titres={2} notes={3} score={4:F2}{5} | {6}",
                    fromUtc, toUtc, items.Count, n, score, amb ? " AMBIGU" : "", det));
            }

            bool good = ok && !amb && n >= MinHeadlines && score >= EntryThreshold;
            bool bad = ok && n >= 1 && score <= ExitThreshold;
            try { AfterSymbolDay(s, day, ok, score, n, amb); } catch { }

            if (s.Qty > 0 || s.TargetQty > 0)
            {
                if (bad) { SetTarget(s, 0, double.NaN, string.Format(CultureInfo.InvariantCulture, "mauvaise nouvelle (score {0:F2})", score)); BadNewsExits++; }
                else if (s.Qty > 0 && s.BarsHeld >= HoldDays && !good) { SetTarget(s, 0, double.NaN, "fin de detention (" + HoldDays + " j)"); HoldExits++; }
                return;
            }
            if (!good || bad) return;

            double conf = UseScoreAsConfidence ? NxMath.Clamp(0.5 + 0.5 * score, 0.5, 0.95) : double.NaN;
            string sd;
            int q = SizeQty(s, MaxTradePct / 100.0, s.LastPrice, conf, out sd);
            double stop = UseAtrStop ? NxAtrStop.LongStop(s.LastPrice, s.Hist.Atr, AtrMultiplier, StopMinPct / 100.0, StopMaxPct / 100.0) : double.NaN;
            SetTarget(s, q, stop, string.Format(CultureInfo.InvariantCulture, "actualites : score {0:F2} sur {1} titres", score, n));
            EntrySignals++;
            NxSignal(NowNt, s.Name, "entree_actualites", string.Format(CultureInfo.InvariantCulture, "score={0:F2} n={1} q={2} | {3}", score, n, q, sd));
        }

        protected void AddNewsReport(List<string> lines)
        {
            FlushBgLog();
            lines.Add(string.Format(CultureInfo.InvariantCulture, "Jours-symbole avec titres : {0} | notes : {1} | non notes (cache absent / budget) : {2} | ambigus : {3}",
                DaysWithNews, ScoredDays, UnscoredDays, AmbiguousDays));
            lines.Add(string.Format(CultureInfo.InvariantCulture, "Signaux d entree : {0} | sorties sur mauvaise nouvelle : {1} | sorties fin de detention : {2}",
                EntrySignals, BadNewsExits, HoldExits));
            lines.Add(string.Format(CultureInfo.InvariantCulture, "Appels API reels : {0} | refuses (backtest sans API / budget) : {1} | titres en memoire : {2} (doublons ecartes : {3})",
                ApiCalls, ApiRefusals, News.Count, News.Duplicates));
            if (UnscoredDays > 0 && !ApiCallsInHistorical)
                lines.Add("NOTE : des titres n ont pas ete notes en backtest. Activer 'Appels API en backtest' UNE fois (cache rempli), puis relancer gratuitement.");
        }

        #region 01. Regles evenementielles
        [NinjaScriptProperty]
        [Range(0.0, 1.0)]
        [Display(Name = "Seuil d entree (score moyen >=)", Order = 1, GroupName = "01. Regles evenementielles")]
        public double EntryThreshold { get; set; }

        [NinjaScriptProperty]
        [Range(-1.0, 0.0)]
        [Display(Name = "Seuil mauvaise nouvelle (<=)", Order = 2, GroupName = "01. Regles evenementielles")]
        public double ExitThreshold { get; set; }

        [NinjaScriptProperty]
        [Range(1, 100)]
        [Display(Name = "Titres distincts minimum", Order = 3, GroupName = "01. Regles evenementielles")]
        public int MinHeadlines { get; set; }

        [NinjaScriptProperty]
        [Range(1, 60)]
        [Display(Name = "Detention (jours de bourse)", Order = 4, GroupName = "01. Regles evenementielles")]
        public int HoldDays { get; set; }

        [Display(Name = "Score comme confiance (Kelly)", Description = "p du demi-Kelly melange avec 0.5 + score/2.", Order = 5, GroupName = "01. Regles evenementielles")]
        public bool UseScoreAsConfidence { get; set; }

        [Display(Name = "Stop ATR (optionnel)", Order = 6, GroupName = "01. Regles evenementielles")]
        public bool UseAtrStop { get; set; }

        [Range(0.5, 20.0)]
        [Display(Name = "Stop : multiplicateur ATR(14)", Order = 7, GroupName = "01. Regles evenementielles")]
        public double AtrMultiplier { get; set; }

        [Range(0.1, 50.0)]
        [Display(Name = "Stop : borne basse (%)", Order = 8, GroupName = "01. Regles evenementielles")]
        public double StopMinPct { get; set; }

        [Range(0.1, 50.0)]
        [Display(Name = "Stop : borne haute (%)", Order = 9, GroupName = "01. Regles evenementielles")]
        public double StopMaxPct { get; set; }
        #endregion
    }
}
