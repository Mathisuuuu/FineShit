// =============================================================================
//  NexusStrategyBase.cs   (NinjaTrader 8 / NinjaScript)
//
//  Socle abstrait des 14 strategies "Nexus" (non visible dans la liste des
//  strategies). Il branche les trois modules transverses sur chaque strategie :
//    module B : taille (demi-Kelly, waiver, correlation, plafonds, registre)
//    module C : disjoncteurs, couts, garde de cotation, chien de garde des
//               ordres, interrupteur global, stops natifs ou logiciels,
//               journal CSV, rapport de validation de fin de run
//  et fournit :
//    - l univers multi-instruments (une serie par symbole, ignoree si absente)
//    - un historique OHLCV par symbole aligne par JOUR DE BOURSE
//    - un traitement "par lot" synchronise : NxOnBatch(jour) n est appele que
//      lorsque TOUTES les series attendues ce jour-la ont clos leur barre
//      (en historique on regarde l horodatage de la prochaine barre ; en temps
//      reel, attente bornee par RealtimeBatchWaitSeconds)
//    - un moteur d execution NON GERE "position cible" : SetTarget() puis
//      FlushTargets() ; reductions d abord, entrees ensuite ; un seul ordre
//      d entree et un seul stop par symbole ; jamais de double remplissage
//      stop + sortie (le stop est annule et confirme avant la sortie en reel)
//    - une comptabilite interne nette des couts modelises (PnL, equity,
//      rendements journaliers) independante des modeles de commission NT
//
//  Les classes filles implementent NxSetDefaults() et NxOnBatch() (ou
//  NxOnSymbolBar() en mode par symbole) et n appellent jamais OnBarUpdate().
//  Les ordres sont executes a l ouverture de la barre suivante (Calculate =
//  OnBarClose) : aucune information future n est utilisee.
// =============================================================================

#region Using declarations
using System;
using System.Collections.Generic;
using System.ComponentModel;
using System.ComponentModel.DataAnnotations;
using System.Globalization;
using System.Linq;
using System.Reflection;
using System.Text;
using System.Threading;
using System.Threading.Tasks;
using System.Xml.Serialization;
using NinjaTrader.Cbi;
using NinjaTrader.Data;
using NinjaTrader.NinjaScript;
using NinjaTrader.NinjaScript.AddOns.Nexus;
#endregion

namespace NinjaTrader.NinjaScript.Strategies
{
    public enum NxJournalMode { Desactive, TempsReelSeulement, Toujours }
    public enum NxStopMode { OrdreNatif, Logiciel, Aucun }
    public enum NxCapitalSource { Interne, CompteNetLiquidation }
    public enum NxRebalance { Quotidien, Hebdomadaire, Mensuel }

    /// <summary>Etat d un symbole de l univers (donnees, execution, comptabilite).</summary>
    public class NxSym
    {
        public string Name;
        public int Bip;
        public bool Traded;
        public NxAssetClass Class;
        public NinjaTrader.Cbi.Instrument Instrument;
        public NxBarHistory Hist;
        public double PointValue = 1.0;
        public double TickSize = 0.01;
        public Currency QuoteCurrency = Currency.UsDollar;
        public InstrumentType Type = InstrumentType.Stock;
        public bool IsDaily;
        public bool SevenDays;
        public SessionIterator Session;
        public SessionIterator SessionNext;     // iterateur dedie a la recherche de la seance suivante
        public HashSet<DateTime> Holidays = new HashSet<DateTime>();

        // --- Execution ---
        public int TargetQty;
        public double StopPrice = double.NaN;
        public OrderType OrderKind = OrderType.Market;
        public double LimitPrice = double.NaN;
        public int LimitExpiryBarCount = int.MaxValue;
        public string PendingReason = "";
        public bool Dirty;
        public bool InSync;
        public Order EntryOrder;
        public Order StopOrder;
        public DateTime EntrySubmitUtc = DateTime.MinValue;
        public double DecisionPrice = double.NaN;
        public bool WaitingStopCancel;
        public bool StopRejected;
        public int Rejections;
        public bool Deferred;
        public double DeferLimit = double.NaN;

        // --- Comptabilite (position reelle de la strategie, issue des executions) ---
        public int Qty;
        public double AvgPrice;
        public DateTime OpenTime;
        public DateTime EntryDay;
        public int EntryBarCount;
        public double TradeGross;
        public double TradeCosts;
        public double MaxNotional;
        public int MaxQty;
        public int Direction;
        public string EntryReason = "";
        public string Regime = "";
        public double LastPrice = double.NaN;
        public bool StoppedOut;
        public DateTime StoppedTime = DateTime.MinValue;
        public DateTime LastSoftCheckUtc = DateTime.MinValue;
        public object Tag;

        public int BarsHeld { get { return Qty == 0 || Hist == null ? 0 : Math.Max(0, Hist.Count - EntryBarCount); } }
        public bool IsFlat { get { return Qty == 0; } }
        public override string ToString() { return Name; }
    }

    public abstract class NexusStrategyBase : Strategy
    {
        // =====================================================================
        //  Etat interne
        // =====================================================================
        protected readonly List<NxSym> Syms = new List<NxSym>();
        private readonly Dictionary<int, NxSym> byBip = new Dictionary<int, NxSym>();
        private readonly Dictionary<string, NxSym> byName = new Dictionary<string, NxSym>(StringComparer.OrdinalIgnoreCase);
        private class ConfiguredSeries { public string Name; public bool Traded; public int Bip; }
        private readonly List<ConfiguredSeries> configuredNames = new List<ConfiguredSeries>();
        private int nextBip = 1;
        private bool nxReady;

        protected NxSizingConfig SizingCfg;
        protected readonly NxTradeStats Stats = new NxTradeStats();
        protected NxCostModel Costs;
        protected NxCircuitBreaker Breaker;
        protected NxJournal Journal;
        protected readonly List<NxTradeRecord> ClosedTrades = new List<NxTradeRecord>();
        protected readonly List<DateTime> EquityDays = new List<DateTime>();
        protected readonly List<double> EquityValues = new List<double>();
        protected readonly List<double> DailyReturns = new List<double>();
        protected int BatchCount;
        protected DateTime LastBatchDay = DateTime.MinValue;

        private double realizedNet;
        private DateTime curDay = DateTime.MinValue;
        private double curDayEquity = double.NaN;
        private DateTime pendingBatchDay = DateTime.MinValue;
        private DateTime pendingBatchTradingDay = DateTime.MinValue;
        private DateTime pendingSinceUtc = DateTime.MinValue;
        private Timer rtTimer;
        private int timerBusy;
        private DateTime lastMarkUtc = DateTime.MinValue;
        private bool killHandled;
        private int lastRebalanceKey = int.MinValue;
        private bool firstRebalanceDone;
        private readonly HashSet<string> warnedOnce = new HashSet<string>();
        private Dictionary<string, double> fxFallback;

        // =====================================================================
        //  Points d extension des strategies filles
        // =====================================================================
        /// <summary>Doit fixer Name, Description, Symbols et les parametres propres.</summary>
        protected abstract void NxSetDefaults();
        protected virtual void NxConfigure() { }
        protected virtual void NxDataLoaded() { }
        /// <summary>Mode par lot : appele une fois par jour de bourse quand toutes les series ont clos.</summary>
        protected virtual void NxOnBatch(DateTime day) { }
        /// <summary>Mode par symbole : appele a chaque barre close de chaque symbole de l univers.</summary>
        protected virtual void NxOnSymbolBar(NxSym s, DateTime day) { }
        /// <summary>Barres des series supplementaires ajoutees par NxAddSeries.</summary>
        protected virtual void NxOnExtraBar(int bip) { }
        protected virtual void NxOnStopped(NxSym s) { }
        /// <summary>Chaque execution de la strategie (quantite signee), apres mise a jour de la comptabilite.</summary>
        protected virtual void NxOnFill(NxSym s, int signedQty, double price, DateTime time) { }
        protected virtual void NxOnTradeClosed(NxSym s, NxTradeRecord r) { }
        protected virtual void NxOnRealtime() { }
        /// <summary>Minuterie temps reel (500 ms), sur le fil de la strategie.</summary>
        protected virtual void NxOnTimer() { }
        protected virtual void NxOnTerminated() { }
        protected virtual void NxReportExtras(List<string> lines) { }
        /// <summary>Veto propre a la strategie sur une augmentation de position.</summary>
        protected virtual bool NxAllowIncrease(NxSym s, out string reason) { reason = null; return true; }
        /// <summary>PnL hors ordres NinjaTrader (ex. options synthetiques de la fiche 11).</summary>
        protected virtual double NxExtraEquity() { return 0.0; }
        protected virtual bool NxBatchMode { get { return true; } }
        protected virtual BarsPeriodType NxUniverseBarsType { get { return BarsPeriodType.Day; } }
        protected virtual int NxUniverseBarsValue { get { return 1; } }
        /// <summary>Modele d horaires (Trading Hours) d une serie de l univers ; null ou vide = modele par defaut de l instrument.</summary>
        protected virtual string NxUniverseTradingHours(string instrumentName) { return null; }
        /// <summary>Cout supplementaire d une execution (devise du compte), ajoute au module C (ex. ticks par contrat de la fiche 15).</summary>
        protected virtual double NxExtraFillCost(NxSym s, int absQty, double price) { return 0.0; }
        /// <summary>Symboles de reference supplementaires (barometre, VIX...).</summary>
        protected virtual IEnumerable<string> NxRequiredReferences() { return new string[0]; }

        // =====================================================================
        //  Cycle de vie
        // =====================================================================
        protected override void OnStateChange()
        {
            if (State == State.SetDefaults)
            {
                Calculate = Calculate.OnBarClose;
                IsUnmanaged = true;
                EntriesPerDirection = 1;
                IsExitOnSessionCloseStrategy = false;
                BarsRequiredToTrade = 1;
                MaximumBarsLookBack = MaximumBarsLookBack.Infinite;
                IsInstantiatedOnEachOptimizationIteration = true;
                StartBehavior = StartBehavior.WaitUntilFlat;
                RealtimeErrorHandling = RealtimeErrorHandling.StopCancelClose;
                TimeInForce = TimeInForce.Gtc;
                OrderFillResolution = OrderFillResolution.Standard;
                IsFillLimitOnTouch = false;
                TraceOrders = false;
                Slippage = 0;

                Symbols = "SPY,QQQ";
                ReferenceSymbols = "";
                EtfSymbols = "SPY,QQQ,IWM,DIA,XLK,XLF,XLV,XLE,XLI,XLY,XLP,XLU,XLB,XLRE,XLC,GLD,SLV,TLT,IEF,HYG,LQD,EEM,EFA,VTI,VOO,SMH,ARKK,USO,UNG";
                AllowShortSelling = false;
                LotSize = 1;
                FxFallback = "EUR=1.08;GBP=1.27;JPY=0.0067;AUD=0.66;CHF=1.12;CAD=0.73;NZD=0.60";

                InitialBankroll = 100000;
                CapitalSource = NxCapitalSource.Interne;
                SizingMode = NxSizingMode.DemiKelly;
                KellyLecture = NxKellyLecture.FractionNotionnel;
                KellyMultiplier = 0.5;
                PriorWinRate = 0.50;
                PriorPayoff = 1.20;
                PriorAvgLossPct = 4.0;
                PriorStrength = 30;
                ConfidenceWeight = 0.5;
                UseWilsonLowerBound = false;
                NoEdgeFractionPct = 0.0;
                RckAlpha = 0.70;
                RckBeta = 0.10;
                WaiverTrades = 30;
                WaiverMultiplier = 0.5;
                MaxTradePct = 3.0;
                MaxTradeDollars = 0;
                MaxSymbolPct = 10.0;
                MaxClassPct = 30.0;
                MaxTotalPct = 50.0;
                UseCorrelationDivisor = true;
                CorrelationWindow = 60;
                UseRegistry = true;

                UseCircuitBreakers = true;
                DrawdownTripPct = 15.0;
                DrawdownCooldownHours = 12.0;
                DailyLossPct = 5.0;
                DailyCooldownHours = 24.0;
                ResetPeakAfterCooldown = true;
                SlippagePct = 0.05;
                EquityFeePct = 0.0;
                CryptoFeePct = 0.10;
                UseBnbDiscount = false;
                OtherFeePct = 0.0;
                PerContractFee = 0.0;
                StopMode = NxStopMode.OrdreNatif;
                SoftStopPollSecondsEquity = 60;
                SoftStopPollSecondsCrypto = 1;
                FillTimeoutSeconds = 5;
                LimitOrderTimeoutMinutes = 0;
                DataDelayMinutes = 0;
                QuoteMaxDeviationPct = 35.0;
                UseKillSwitch = true;
                UseShockFilter = false;
                RealtimeBatchWaitSeconds = 90;
                StressShockPct = 10.0;
                StressWorstN = 10;

                InstanceTag = "";
                JournalMode = NxJournalMode.TempsReelSeulement;
                WriteReport = true;
                SaveReturnsForPbo = false;
                MonteCarloSims = 1000;
                BlockLength = 0;
                AuditWithLlm = false;
                AuditProvider = NxLlmProvider.Gemini;
                AuditModel = "";
                AuditApiKey = "";
                VerboseLog = false;

                NxSetDefaults();
            }
            else if (State == State.Configure)
            {
                NxPaths.EnsureAll();
                BuildUniverse();
                NxConfigure();
            }
            else if (State == State.DataLoaded)
            {
                InitAfterDataLoaded();
                NxDataLoaded();
                nxReady = true;
            }
            else if (State == State.Realtime)
            {
                if (!nxReady) return;
                OnEnterRealtime();
                NxOnRealtime();
            }
            else if (State == State.Terminated)
            {
                try { if (rtTimer != null) { rtTimer.Dispose(); rtTimer = null; } } catch { }
                if (nxReady)
                {
                    try { FinalizeRun(); } catch (Exception ex) { Print("[Nexus] Erreur rapport final : " + ex.Message); }
                    try { if (Account != null) NxPortfolioRegistry.ReleaseAll(Account.Name, StrategyId); } catch { }
                }
                try { NxOnTerminated(); } catch { }
            }
        }

        // =====================================================================
        //  Univers et series
        // =====================================================================
        private void BuildUniverse()
        {
            configuredNames.Clear();
            nextBip = 1;
            List<string> traded = NxText.SplitList(Symbols);
            List<string> refs = NxText.SplitList(ReferenceSymbols);
            refs.AddRange(NxRequiredReferences().Where(x => !string.IsNullOrWhiteSpace(x)));
            foreach (string n in traded)
            {
                int bip;
                if (NxAddSeries(n, NxUniverseBarsType, NxUniverseBarsValue, NxUniverseTradingHours(n), out bip)) configuredNames.Add(new ConfiguredSeries { Name = n, Traded = true, Bip = bip });
            }
            foreach (string n in refs.Distinct(StringComparer.OrdinalIgnoreCase))
            {
                if (traded.Any(t => string.Equals(t, n, StringComparison.OrdinalIgnoreCase))) continue;
                int bip;
                if (NxAddSeries(n, NxUniverseBarsType, NxUniverseBarsValue, NxUniverseTradingHours(n), out bip)) configuredNames.Add(new ConfiguredSeries { Name = n, Traded = false, Bip = bip });
            }
        }

        /// <summary>Ajoute une serie (verifie l existence de l instrument) ; renvoie son indice BarsInProgress.</summary>
        protected bool NxAddSeries(string instrumentName, BarsPeriodType type, int value, out int bip)
        {
            return NxAddSeries(instrumentName, type, value, null, out bip);
        }

        /// <summary>Idem avec un modele d horaires explicite (ex. "CME US Index Futures RTH") ; null = modele de l instrument.</summary>
        protected bool NxAddSeries(string instrumentName, BarsPeriodType type, int value, string tradingHoursName, out int bip)
        {
            bip = -1;
            NinjaTrader.Cbi.Instrument ins = null;
            try { ins = NinjaTrader.Cbi.Instrument.GetInstrument(instrumentName, false); } catch { ins = null; }
            if (ins == null)
            {
                Print("[Nexus] " + Name + " : instrument introuvable dans la base NinjaTrader, ignore -> '" + instrumentName + "'");
                return false;
            }
            if (string.IsNullOrWhiteSpace(tradingHoursName)) AddDataSeries(instrumentName, type, value);
            else AddDataSeries(instrumentName, new BarsPeriod { BarsPeriodType = type, Value = value }, tradingHoursName.Trim());
            bip = nextBip++;
            return true;
        }

        private void InitAfterDataLoaded()
        {
            Syms.Clear(); byBip.Clear(); byName.Clear();
            HashSet<string> etfs = new HashSet<string>(NxText.SplitList(EtfSymbols), StringComparer.OrdinalIgnoreCase);
            foreach (ConfiguredSeries cs in configuredNames)
            {
                int bip = cs.Bip;
                if (bip < 0 || bip >= BarsArray.Length) continue;
                NxSym s = new NxSym { Name = cs.Name, Bip = bip, Traded = cs.Traded };
                try
                {
                    s.Instrument = BarsArray[bip].Instrument;
                    MasterInstrument mi = s.Instrument.MasterInstrument;
                    s.PointValue = mi.PointValue > 0 ? mi.PointValue : 1.0;
                    s.TickSize = mi.TickSize > 0 ? mi.TickSize : 0.01;
                    s.QuoteCurrency = mi.Currency;
                    s.Type = mi.InstrumentType;
                }
                catch { }
                s.Class = ClassOf(s.Name, s.Type, etfs);
                s.SevenDays = s.Class == NxAssetClass.Crypto;
                s.Hist = new NxBarHistory(s.Name, 14);
                BarsPeriodType bt = BarsArray[bip].BarsPeriod.BarsPeriodType;
                s.IsDaily = bt == BarsPeriodType.Day || bt == BarsPeriodType.Week || bt == BarsPeriodType.Month || bt == BarsPeriodType.Year;
                try { s.Session = new SessionIterator(BarsArray[bip]); } catch { s.Session = null; }
                try { s.SessionNext = new SessionIterator(BarsArray[bip]); } catch { s.SessionNext = null; }
                try { foreach (DateTime d in BarsArray[bip].TradingHours.Holidays.Keys) s.Holidays.Add(d.Date); } catch { }
                Syms.Add(s);
                byBip[bip] = s;
                byName[s.Name] = s;
            }

            SizingCfg = new NxSizingConfig
            {
                Mode = SizingMode, Lecture = KellyLecture, KellyMultiplier = KellyMultiplier,
                PriorWinRate = PriorWinRate, PriorPayoff = PriorPayoff, PriorAvgLoss = PriorAvgLossPct / 100.0, PriorStrength = PriorStrength,
                ConfidenceWeight = ConfidenceWeight, UseWilsonLowerBound = UseWilsonLowerBound, NoEdgeFraction = NoEdgeFractionPct / 100.0,
                RckAlpha = RckAlpha, RckBeta = RckBeta, WaiverTrades = WaiverTrades, WaiverMultiplier = WaiverMultiplier,
                MaxTradeFraction = MaxTradePct / 100.0, MaxTradeDollars = MaxTradeDollars, MaxSymbolFraction = MaxSymbolPct / 100.0,
                MaxClassFraction = MaxClassPct / 100.0, MaxTotalFraction = MaxTotalPct / 100.0, UseCorrelationDivisor = UseCorrelationDivisor
            };
            Costs = new NxCostModel
            {
                SlippagePct = SlippagePct, EquityFeePct = EquityFeePct, CryptoFeePct = CryptoFeePct, UseBnb = UseBnbDiscount,
                OtherFeePct = OtherFeePct, PerContractFee = PerContractFee
            };
            Breaker = new NxCircuitBreaker
            {
                Enabled = UseCircuitBreakers, DrawdownTripPct = DrawdownTripPct, DrawdownCooldownHours = DrawdownCooldownHours,
                DailyLossPct = DailyLossPct, DailyCooldownHours = DailyCooldownHours, ResetPeakAfterCooldown = ResetPeakAfterCooldown
            };
            Journal = new NxJournal(StrategyId, JournalMode == NxJournalMode.Toujours && !IsOptimizing);
            Stats.LoadLiveCount(StrategyId);
            fxFallback = NxText.ParseMap(FxFallback).ToDictionary(kv => kv.Key, kv => NxCsv.ParseDouble(kv.Value), StringComparer.OrdinalIgnoreCase);

            int nTraded = Syms.Count(x => x.Traded);
            Print(string.Format(CultureInfo.InvariantCulture, "[Nexus] {0} : {1} symboles trades, {2} de reference, capital initial {3:F0}, id '{4}'",
                Name, nTraded, Syms.Count - nTraded, InitialBankroll, StrategyId));
            if (nTraded == 0) Print("[Nexus] " + Name + " : AUCUN symbole tradable trouve - verifier la propriete 'Symboles' et la base d instruments.");
        }

        private static NxAssetClass ClassOf(string name, InstrumentType t, HashSet<string> etfs)
        {
            switch (t)
            {
                case InstrumentType.Stock: return etfs.Contains(name) ? NxAssetClass.Etf : NxAssetClass.Action;
                case InstrumentType.CryptoCurrency: return NxAssetClass.Crypto;
                case InstrumentType.Forex: return NxAssetClass.Forex;
                case InstrumentType.Future: return NxAssetClass.Future;
                case InstrumentType.Index: return NxAssetClass.Indice;
                case InstrumentType.Cfd: return NxAssetClass.Cfd;
                case InstrumentType.Option: return NxAssetClass.Option;
                default: return NxAssetClass.Autre;
            }
        }

        // =====================================================================
        //  Acces pour les strategies filles
        // =====================================================================
        protected NxSym Sym(string name) { NxSym s; return name != null && byName.TryGetValue(name, out s) ? s : null; }
        protected NxSym SymAtBip(int bip) { NxSym s; return byBip.TryGetValue(bip, out s) ? s : null; }
        protected List<NxSym> TradedSyms { get { return Syms.Where(x => x.Traded).ToList(); } }
        protected bool IsRt { get { return State == State.Realtime; } }
        protected bool IsOptimizing
        {
            get
            {
                try { return Category == Category.Optimize || Category == Category.WalkForward || Category == Category.WalkForwardAnchored || Category == Category.MultiObjective; }
                catch { return false; }
            }
        }
        protected bool IsRealMoney
        {
            get
            {
                if (State != State.Realtime || Account == null) return false;
                string n = Account.Name ?? "";
                return !(n.StartsWith("Sim", StringComparison.OrdinalIgnoreCase) || n.StartsWith("Playback", StringComparison.OrdinalIgnoreCase)
                         || n.StartsWith("Backtest", StringComparison.OrdinalIgnoreCase));
            }
        }
        protected bool JournalActive { get { return JournalMode == NxJournalMode.Toujours || (JournalMode == NxJournalMode.TempsReelSeulement && IsRt); } }
        protected string StrategyId { get { return (Name ?? GetType().Name) + (string.IsNullOrWhiteSpace(InstanceTag) ? "" : "_" + InstanceTag.Trim()); } }

        /// <summary>Heure courante dans le fuseau NinjaTrader (barre en cours en historique).</summary>
        protected DateTime NowNt
        {
            get
            {
                if (State == State.Realtime) return NinjaTrader.Core.Globals.Now;
                try { return Times[BarsInProgress][0]; } catch { return LastBatchDay; }
            }
        }

        private int dataDelayResolved = -1;

        /// <summary>
        /// Retard des donnees (minutes) : propriete si &gt; 0, sinon variable d environnement NEXUS_DATA_DELAY_MINUTES
        /// (SIP gratuit retarde : 16 = 15 de retard + 1 de marge, module C).
        /// </summary>
        protected int EffectiveDataDelayMinutes
        {
            get
            {
                if (DataDelayMinutes > 0) return DataDelayMinutes;
                if (dataDelayResolved < 0)
                {
                    int v;
                    string env = NxSecrets.Resolve(null, "NEXUS_DATA_DELAY_MINUTES");
                    dataDelayResolved = env != null && int.TryParse(env.Trim(), out v) && v > 0 && v < 1440 ? v : 0;
                }
                return dataDelayResolved;
            }
        }

        protected void Nx(string msg) { Print("[" + StrategyId + "] " + msg); }
        protected void NxV(string msg) { if (VerboseLog) Nx(msg); }
        protected void NxOnce(string key, string msg) { if (warnedOnce.Add(key)) Nx(msg); }

        protected void NxSignal(DateTime t, string symbol, string kind, string detail)
        {
            Journal.Enabled = JournalActive && !IsOptimizing;
            Journal.Signal(t, symbol, kind, detail);
        }

        protected void NxAlert(string msg)
        {
            Nx("ALERTE " + msg);
            if (State != State.Realtime) return;
            try
            {
                Alert("Nexus_" + StrategyId + "_" + DateTime.UtcNow.Ticks, Priority.High, StrategyId + " : " + msg, "", 0,
                      System.Windows.Media.Brushes.DarkRed, System.Windows.Media.Brushes.White);
                Log(StrategyId + " : " + msg, LogLevel.Warning);
            }
            catch { }
        }

        protected DateTime TradingDayOf(NxSym s, DateTime t)
        {
            if (s.IsDaily && t.TimeOfDay == TimeSpan.Zero) return t.Date;
            if (s.Session != null) { try { return s.Session.GetTradingDay(t).Date; } catch { } }
            return t.Date;
        }

        /// <summary>Debut (fuseau NinjaTrader) de la premiere seance qui suit la fin du jour de bourse donne.</summary>
        protected DateTime NextSessionBegin(NxSym s, DateTime tradingDay)
        {
            try
            {
                SessionIterator it = s.SessionNext ?? new SessionIterator(BarsArray[s.Bip]);
                DateTime end = it.GetTradingDayEndLocal(tradingDay.Date);
                DateTime probe = end.AddSeconds(1);
                for (int k = 0; k < 6; k++)
                {
                    if (!it.GetNextSession(probe, true)) break;
                    if (it.ActualSessionBegin > end) return it.ActualSessionBegin;
                    probe = it.ActualSessionEnd.AddSeconds(1);
                }
            }
            catch { }
            DateTime nd = NxCalendar.NextBusinessDay(tradingDay, s.Holidays, s.SevenDays);
            if (s.SevenDays) return NxTime.UtcToNt(DateTime.SpecifyKind(nd, DateTimeKind.Utc));
            return NxTime.FromUtc(NxTime.ToUtc(nd.Add(new TimeSpan(9, 30, 0)), NxTime.Eastern), NxTime.NtZone());
        }

        /// <summary>
        /// Reequilibrage : mensuel = dernier jour de bourse du mois (ordres a l ouverture du 1er jour du mois suivant),
        /// hebdomadaire = dernier jour de bourse de la semaine. Premier appel = reequilibrage immediat ;
        /// une fin de periode manquee est rattrapee au premier jour suivant. A n appeler qu une fois chaud.
        /// </summary>
        protected bool IsRebalanceDay(DateTime day, NxRebalance freq, NxSym calendar)
        {
            if (freq == NxRebalance.Quotidien) return true;
            ICollection<DateTime> hol = calendar != null ? calendar.Holidays : null;
            bool seven = calendar != null && calendar.SevenDays;
            int key = freq == NxRebalance.Mensuel ? NxCalendar.MonthKey(day) : (int)((NxCalendar.WeekStart(day) - new DateTime(2000, 1, 3)).TotalDays / 7);
            bool last = freq == NxRebalance.Mensuel ? NxCalendar.IsLastTradingDayOfMonth(day, hol, seven) : NxCalendar.IsLastTradingDayOfWeek(day, hol, seven);
            if (!firstRebalanceDone) { firstRebalanceDone = true; lastRebalanceKey = last ? key : key - 1; return true; }
            if (last && lastRebalanceKey < key) { lastRebalanceKey = key; return true; }
            if (lastRebalanceKey < key - 1) { lastRebalanceKey = key - 1; return true; }
            return false;
        }

        // =====================================================================
        //  Barres : historique, lot synchronise, mode par symbole
        // =====================================================================
        protected override void OnBarUpdate()
        {
            if (!nxReady) return;
            int bip = BarsInProgress;
            if (CurrentBars[bip] < 0) return;
            NxSym s;
            if (!byBip.TryGetValue(bip, out s))
            {
                try { NxOnExtraBar(bip); } catch (Exception ex) { NxOnce("extra" + ex.Message, "Erreur NxOnExtraBar : " + ex.Message); }
                return;
            }
            DateTime t = Times[bip][0];
            DateTime day = TradingDayOf(s, t);
            s.Hist.Add(day, t, Opens[bip][0], Highs[bip][0], Lows[bip][0], Closes[bip][0], Volumes[bip][0]);
            s.LastPrice = Closes[bip][0];
            if (s.Traded)
            {
                ExpireLimitOrder(s);
                SoftStopOnBar(s, bip);
            }
            if (NxBatchMode) TryRunBatch(s, s.IsDaily ? day : t, day);
            else
            {
                UpdateEquity(t, day);
                try { NxOnSymbolBar(s, day); }
                catch (Exception ex) { Nx("Erreur NxOnSymbolBar(" + s.Name + ") : " + ex.Message + " " + ex.StackTrace); }
                FlushTargets();
            }
        }

        /// <summary>
        /// Cle de lot = jour de bourse (series journalieres) ou horodatage de barre (series intraday).
        /// Le lot part quand aucune autre serie n attend encore une barre pour cette cle.
        /// </summary>
        private void TryRunBatch(NxSym s, DateTime key, DateTime day)
        {
            if (key <= LastBatchDay) return;
            foreach (NxSym o in Syms)
            {
                if (o == s) continue;
                if (o.Hist.Count > 0 && (o.IsDaily ? o.Hist.LastDate : o.Hist.LastTime) >= key) continue;   // deja a jour
                int k = o.Bip;
                if (State == State.Historical)
                {
                    int next = CurrentBars[k] + 1;
                    if (next < BarsArray[k].Count)
                    {
                        DateTime nt = BarsArray[k].GetTime(next);
                        if ((o.IsDaily ? TradingDayOf(o, nt) : nt) == key) return;   // cette serie va encore recevoir sa barre
                    }
                }
                else if (o.Hist.Count > 0 && (day - o.Hist.LastDate).TotalDays <= 5)
                {
                    if (pendingBatchDay != key) { pendingBatchDay = key; pendingBatchTradingDay = day; pendingSinceUtc = DateTime.UtcNow; }
                    return;   // attente bornee par la minuterie
                }
            }
            RunBatch(key, day);
        }

        private void RunBatch(DateTime key, DateTime day)
        {
            if (key <= LastBatchDay) return;
            LastBatchDay = key;
            pendingBatchDay = DateTime.MinValue;
            BatchCount++;
            UpdateEquity(NowNt, day);
            try { NxOnBatch(key); }
            catch (Exception ex) { Nx("Erreur NxOnBatch(" + key.ToString("yyyy-MM-dd HH:mm") + ") : " + ex.Message + " " + ex.StackTrace); }
            FlushTargets();
        }

        // =====================================================================
        //  Equity, rendements journaliers, disjoncteurs
        // =====================================================================
        protected double UnrealizedPnl()
        {
            double u = 0;
            foreach (NxSym s in Syms)
                if (s.Traded && s.Qty != 0 && NxMath.Ok(s.LastPrice)) u += s.Qty * (s.LastPrice - s.AvgPrice) * ValuePerPoint(s);
            return u;
        }

        protected double RealizedNet { get { return realizedNet; } }

        /// <summary>Equity interne : capital initial + PnL realise net + latent + PnL externe.</summary>
        protected double Equity { get { return InitialBankroll + realizedNet + UnrealizedPnl() + NxExtraEquity(); } }

        /// <summary>Capital servant au dimensionnement.</summary>
        protected double Bankroll()
        {
            if (CapitalSource == NxCapitalSource.CompteNetLiquidation && State == State.Realtime && Account != null)
            {
                try { double v = Account.Get(AccountItem.NetLiquidation, Currency.UsDollar); if (v > 0) return v; } catch { }
            }
            return Math.Max(0.0, Equity);
        }

        private void UpdateEquity(DateTime now, DateTime day)
        {
            double eq = Equity;
            if (Breaker.Update(now, day, eq) && Breaker.LastEvent != null)
            {
                Nx(Breaker.LastEvent);
                if (State == State.Realtime && Breaker.LastEvent.Contains("DISJONCTEUR")) NxAlert(Breaker.LastEvent);
            }
            if (curDay == DateTime.MinValue) { curDay = day; curDayEquity = eq; return; }
            if (day > curDay) FinalizeDay();
            if (day >= curDay) { curDay = day; curDayEquity = eq; }
        }

        private void FinalizeDay()
        {
            if (curDay == DateTime.MinValue || !NxMath.Ok(curDayEquity)) return;
            if (EquityDays.Count > 0 && EquityDays[EquityDays.Count - 1] >= curDay) return;
            EquityDays.Add(curDay);
            EquityValues.Add(curDayEquity);
            if (EquityValues.Count >= 2)
            {
                double prev = EquityValues[EquityValues.Count - 2];
                double r = prev > 0 ? curDayEquity / prev - 1 : 0;
                DailyReturns.Add(r);
                if (JournalActive && !IsOptimizing) { Journal.Enabled = true; Journal.DailyReturn(curDay, curDayEquity, r); }
                if (State == State.Realtime) NxPortfolioRegistry.RecordStrategyReturn(StrategyId, curDay, r);
            }
        }

        // =====================================================================
        //  Devises et valeur du point
        // =====================================================================
        private static string Iso(Currency c)
        {
            switch (c)
            {
                case Currency.Euro: return "EUR";
                case Currency.BritishPound: return "GBP";
                case Currency.JapaneseYen: return "JPY";
                case Currency.AustralianDollar: return "AUD";
                case Currency.SwissFranc: return "CHF";
                case Currency.CanadianDollar: return "CAD";
                case Currency.NewZealandDollar: return "NZD";
                case Currency.HongKongDollar: return "HKD";
                case Currency.SwedishKrona: return "SEK";
                case Currency.NorwayKrone: return "NOK";
                case Currency.MexicanPeso: return "MXN";
                case Currency.SingaporeDollar: return "SGD";
                default: return "USD";
            }
        }

        /// <summary>Taux de conversion d une devise de cotation vers le dollar (compte suppose en USD).</summary>
        protected double FxToUsd(Currency c)
        {
            if (c == Currency.UsDollar) return 1.0;
            string iso = Iso(c);
            NxSym d;
            if (byName.TryGetValue(iso + "USD", out d) && NxMath.Ok(d.LastPrice) && d.LastPrice > 0) return d.LastPrice;
            if (byName.TryGetValue("USD" + iso, out d) && NxMath.Ok(d.LastPrice) && d.LastPrice > 0) return 1.0 / d.LastPrice;
            double fb;
            if (fxFallback != null && fxFallback.TryGetValue(iso, out fb) && NxMath.Ok(fb) && fb > 0)
            {
                NxOnce("fx" + iso, "Conversion " + iso + "->USD : taux de repli " + fb.ToString(CultureInfo.InvariantCulture) + " (ajouter " + iso + "USD en reference pour un taux reel)");
                return fb;
            }
            NxOnce("fxnone" + iso, "Conversion " + iso + "->USD inconnue : taux 1 suppose");
            return 1.0;
        }

        /// <summary>Valeur en dollars d un point de prix pour une unite.</summary>
        protected double ValuePerPoint(NxSym s) { return s.PointValue * FxToUsd(s.QuoteCurrency); }

        protected double Notional(NxSym s, int qty, double price) { return Math.Abs(qty) * price * ValuePerPoint(s); }

        protected double RoundPrice(NxSym s, double px)
        {
            if (!NxMath.Ok(px)) return px;
            try { return s.Instrument.MasterInstrument.RoundToTickSize(px); } catch { return Math.Round(px / s.TickSize) * s.TickSize; }
        }

        // =====================================================================
        //  Module B : dimensionnement
        // =====================================================================
        private bool RegistryOn { get { return UseRegistry && State == State.Realtime && Account != null; } }

        private void PlannedExposure(NxSym except, NxAssetClass cls, out double total, out double sameClass)
        {
            total = sameClass = 0;
            foreach (NxSym o in Syms)
            {
                if (!o.Traded || o == except) continue;
                int q = Math.Max(Math.Abs(o.TargetQty), o.Dirty ? 0 : Math.Abs(o.Qty));
                if (q == 0 || !NxMath.Ok(o.LastPrice)) continue;
                double n = Notional(o, q, o.LastPrice);
                total += n;
                if (o.Class == cls) sameClass += n;
            }
        }

        /// <summary>Somme des correlations positives (signees par la direction) avec les positions cibles ouvertes.</summary>
        protected double SumPositiveCorrelation(NxSym s, int direction)
        {
            double sum = 0;
            foreach (NxSym o in Syms)
            {
                if (!o.Traded || o == s || o.TargetQty == 0) continue;
                double c = NxBarHistory.ReturnCorrelation(s.Hist, o.Hist, CorrelationWindow);
                if (!NxMath.Ok(c)) continue;
                double signed = c * direction * Math.Sign(o.TargetQty);
                if (signed > 0) sum += signed;
            }
            if (RegistryOn)
                foreach (string other in NxPortfolioRegistry.SymbolsHeldByOthers(Account.Name, StrategyId))
                {
                    NxSym o = Sym(other);
                    if (o == null || o == s) continue;
                    double c = NxBarHistory.ReturnCorrelation(s.Hist, o.Hist, CorrelationWindow);
                    if (NxMath.Ok(c) && c * direction > 0) sum += c * direction;
                }
            return sum;
        }

        /// <summary>
        /// Quantite signee pour une fraction native signee du bankroll (notionnel), apres module B :
        /// base (native / Kelly) -> waiver -> correlation -> plafonds trade/symbole/classe/total/$ -> lot.
        /// </summary>
        protected int SizeQty(NxSym s, double nativeSignedFraction, double price, double modelConfidence, out string detail)
        {
            detail = "";
            int dir = Math.Sign(nativeSignedFraction);
            if (dir == 0 || s == null) return 0;
            if (dir < 0 && !AllowShortSelling) { detail = "vente a decouvert desactivee"; return 0; }
            double bank = Bankroll();
            if (!(bank > 0) || !NxMath.Ok(price) || price <= 0) { detail = "bankroll ou prix invalide"; return 0; }
            double tot, cls;
            PlannedExposure(s, s.Class, out tot, out cls);
            double oTot = 0, oCls = 0, oSym = 0;
            if (RegistryOn) NxPortfolioRegistry.OtherExposure(Account.Name, StrategyId, s.Name, s.Class, out oTot, out oCls, out oSym);
            double corr = UseCorrelationDivisor ? SumPositiveCorrelation(s, dir) : 0.0;
            NxSizingResult r = NxSizer.Size(SizingCfg, Stats, Math.Abs(nativeSignedFraction), modelConfidence, corr, bank,
                                            oSym / bank, (cls + oCls) / bank, (tot + oTot) / bank);
            detail = r.Detail;
            if (r.Blocked || r.Fraction <= 0) return 0;
            double vpp = ValuePerPoint(s);
            double units = r.Fraction * bank / (price * vpp);
            int lot = Math.Max(1, LotSize);
            int q = (int)Math.Floor(units / lot) * lot;
            if (q <= 0) detail += " | quantite < " + lot + " (capital insuffisant pour 1 lot)";
            return dir * q;
        }

        /// <summary>Quantite pour un risque cible (fraction du bankroll perdue si le stop est touche).</summary>
        protected int RiskQty(NxSym s, double riskFraction, double stopDistance)
        {
            if (!(stopDistance > 0) || !(riskFraction > 0)) return 0;
            double vpp = ValuePerPoint(s);
            double units = riskFraction * Bankroll() / (stopDistance * vpp);
            int lot = Math.Max(1, LotSize);
            return (int)Math.Floor(units / lot) * lot;
        }

        // =====================================================================
        //  Moteur d execution "position cible" (mode non gere)
        // =====================================================================
        /// <summary>
        /// Fixe la position cible signee. stop = prix du stop de protection (NaN = aucun).
        /// kind = Market ou Limit (limit = prix limite, valable validBars barres du symbole).
        /// Les ordres partent au FlushTargets() automatique de fin de lot.
        /// </summary>
        protected void SetTarget(NxSym s, int qty, double stop, string reason, OrderType kind = OrderType.Market, double limit = double.NaN, int validBars = 1)
        {
            if (s == null || !s.Traded) return;
            if (qty < 0 && !AllowShortSelling) qty = 0;
            s.TargetQty = qty;
            s.StopPrice = qty == 0 ? double.NaN : stop;
            s.OrderKind = kind == OrderType.Limit && NxMath.Ok(limit) && limit > 0 ? OrderType.Limit : OrderType.Market;
            s.LimitPrice = limit;
            s.LimitExpiryBarCount = s.Hist.Count + Math.Max(1, validBars);
            s.PendingReason = reason ?? "";
            s.Dirty = true;
        }

        /// <summary>Change seulement le stop de la position existante.</summary>
        protected void UpdateStop(NxSym s, double stop)
        {
            if (s == null) return;
            s.StopPrice = stop;
            s.Dirty = true;
        }

        protected void FlatAll(string reason)
        {
            foreach (NxSym s in Syms) if (s.Traded && (s.Qty != 0 || s.TargetQty != 0 || IsActive(s.EntryOrder))) SetTarget(s, 0, double.NaN, reason);
        }

        /// <summary>Envoie les ordres : reductions d abord, entrees ensuite.</summary>
        protected void FlushTargets()
        {
            List<NxSym> dirty = Syms.Where(x => x.Traded && x.Dirty).ToList();
            foreach (NxSym s in dirty.Where(x => Math.Abs(x.TargetQty) < Math.Abs(x.Qty) || x.TargetQty * x.Qty < 0))
            {
                s.Dirty = false;
                Sync(s);
            }
            foreach (NxSym s in dirty.Where(x => x.Dirty))
            {
                s.Dirty = false;
                Sync(s);
            }
        }

        protected static bool IsActive(Order o) { return o != null && !Order.IsTerminalState(o.OrderState); }

        private static bool IsPendingState(Order o)
        {
            return o != null && (o.OrderState == OrderState.CancelPending || o.OrderState == OrderState.CancelSubmitted
                                 || o.OrderState == OrderState.ChangePending || o.OrderState == OrderState.ChangeSubmitted);
        }

        private static bool IsBuy(Order o) { return o.OrderAction == OrderAction.Buy || o.OrderAction == OrderAction.BuyToCover; }

        private static int SignedRemaining(Order o) { return o == null ? 0 : (IsBuy(o) ? 1 : -1) * Math.Max(0, o.Quantity - o.Filled); }

        private void Sync(NxSym s)
        {
            if (s == null || !s.Traded || s.InSync) return;
            s.InSync = true;
            try { SyncCore(s); }
            catch (Exception ex) { Nx("Erreur d execution " + s.Name + " : " + ex.Message); }
            finally { s.InSync = false; }
        }

        private void SyncCore(NxSym s)
        {
            if (IsActive(s.EntryOrder))
            {
                int pend = SignedRemaining(s.EntryOrder);
                bool sameKind = s.EntryOrder.OrderType == s.OrderKind;
                if (s.Qty + pend == s.TargetQty && sameKind) { SyncStop(s); return; }
                if (!IsPendingState(s.EntryOrder)) CancelOrder(s.EntryOrder);
                if (IsActive(s.EntryOrder)) return;   // reprise a la confirmation d annulation (OnOrderUpdate)
            }
            if (s.WaitingStopCancel && IsActive(s.StopOrder)) return;
            s.WaitingStopCancel = false;

            int cur = s.Qty;
            int step = (cur != 0 && s.TargetQty != 0 && Math.Sign(cur) != Math.Sign(s.TargetQty)) ? 0 : s.TargetQty;
            int delta = step - cur;
            if (delta == 0) { SyncStop(s); return; }

            bool increasing = Math.Abs(step) > Math.Abs(cur);
            if (increasing)
            {
                string why;
                int verdict = CheckIncrease(s, out why);
                if (verdict == 1)
                {
                    Nx("Entree rejetee " + s.Name + " : " + why);
                    NxSignal(NowNt, s.Name, "entree_rejetee", why);
                    s.TargetQty = cur;
                    s.Deferred = false;
                    SyncStop(s);
                    return;
                }
                if (verdict == 2) { s.Deferred = true; NxV("Entree differee " + s.Name + " : " + why); return; }
                s.Deferred = false;
            }
            else if (IsActive(s.StopOrder))
            {
                // Le stop protege plus que ce qui restera : l annuler AVANT d envoyer la reduction.
                int stopRemaining = Math.Max(0, s.StopOrder.Quantity - s.StopOrder.Filled);
                if (stopRemaining > Math.Abs(step))
                {
                    if (!IsPendingState(s.StopOrder)) CancelOrder(s.StopOrder);
                    if (State == State.Realtime && IsActive(s.StopOrder)) { s.WaitingStopCancel = true; return; }
                }
            }

            OrderAction act;
            int q;
            if (delta > 0) { act = cur < 0 ? OrderAction.BuyToCover : OrderAction.Buy; q = cur < 0 ? Math.Min(delta, -cur) : delta; }
            else { act = cur > 0 ? OrderAction.Sell : OrderAction.SellShort; q = cur > 0 ? Math.Min(-delta, cur) : -delta; }
            if (q <= 0) return;

            OrderType kind = s.OrderKind;
            double lim = 0;
            if (increasing && NxMath.Ok(s.DeferLimit) && s.DeferLimit > 0) { kind = OrderType.Limit; s.LimitPrice = s.DeferLimit; s.DeferLimit = double.NaN; }
            if (kind == OrderType.Limit)
            {
                lim = RoundPrice(s, s.LimitPrice);
                if (!(lim > 0)) kind = OrderType.Market;
            }
            s.DecisionPrice = kind == OrderType.Limit ? lim : s.LastPrice;
            s.EntrySubmitUtc = DateTime.UtcNow;
            s.EntryOrder = SubmitOrderUnmanaged(s.Bip, act, kind, q, kind == OrderType.Limit ? lim : 0, 0, "", "NxE_" + s.Name);
            NxV(string.Format(CultureInfo.InvariantCulture, "Ordre {0} {1} x{2} {3}{4} ({5})", act, s.Name, q, kind,
                kind == OrderType.Limit ? " @" + lim.ToString(CultureInfo.InvariantCulture) : "", s.PendingReason));
        }

        /// <summary>0 = autorise, 1 = rejete, 2 = differe.</summary>
        private int CheckIncrease(NxSym s, out string why)
        {
            why = null;
            if (State == State.Realtime && UseKillSwitch && NxKillSwitch.IsActive()) { why = "interrupteur global actif (" + NxPaths.KillSwitchFile + ")"; return 1; }
            string br;
            if (!Breaker.CanOpen(NowNt, out br)) { why = br; return 1; }
            if (RegistryOn && !NxPortfolioRegistry.TryClaim(Account.Name, s.Name, StrategyId, s.Class))
            {
                why = "symbole deja detenu par " + NxPortfolioRegistry.Owner(Account.Name, s.Name) + " (une seule strategie par titre)";
                return 1;
            }
            if (State == State.Realtime && UseShockFilter)
            {
                double mid; int dir;
                if (NxShockRegistry.IsInShock(s.Name, DateTime.UtcNow, out mid, out dir))
                {
                    s.DeferLimit = mid;
                    why = "bougie de choc taker recente (fiche 4B) : attente du retournement, puis limite au milieu " + mid.ToString("G6", CultureInfo.InvariantCulture);
                    return 2;
                }
            }
            string extra;
            if (!NxAllowIncrease(s, out extra)) { why = extra ?? "veto de la strategie"; return 1; }
            return 0;
        }

        private void SyncStop(NxSym s)
        {
            if (StopMode != NxStopMode.OrdreNatif || s.StopRejected)
            {
                if (IsActive(s.StopOrder) && !IsPendingState(s.StopOrder)) CancelOrder(s.StopOrder);
                return;
            }
            if (s.WaitingStopCancel) return;
            int cur = s.Qty;
            int protect = Math.Abs(cur);
            if (IsActive(s.EntryOrder))
            {
                int pend = SignedRemaining(s.EntryOrder);
                if (cur != 0 && Math.Sign(pend) == -Math.Sign(cur)) protect = Math.Max(0, Math.Abs(cur) - Math.Abs(pend));
            }
            bool want = protect > 0 && NxMath.Ok(s.StopPrice) && s.StopPrice > 0;
            if (!want)
            {
                if (IsActive(s.StopOrder) && !IsPendingState(s.StopOrder)) CancelOrder(s.StopOrder);
                return;
            }
            OrderAction act = cur > 0 ? OrderAction.Sell : OrderAction.BuyToCover;
            double px = RoundPrice(s, s.StopPrice);
            bool breached = NxMath.Ok(s.LastPrice) && ((cur > 0 && s.LastPrice <= px) || (cur < 0 && s.LastPrice >= px));
            if (breached)
            {
                if (IsActive(s.EntryOrder)) return;
                Nx(string.Format(CultureInfo.InvariantCulture, "Stop {0} deja franchi ({1} vs stop {2}) -> sortie au marche", s.Name, s.LastPrice, px));
                s.TargetQty = 0; s.StopPrice = double.NaN; s.PendingReason = "stop franchi"; s.OrderKind = OrderType.Market;
                if (IsActive(s.StopOrder) && !IsPendingState(s.StopOrder)) CancelOrder(s.StopOrder);
                s.Dirty = true;
                return;
            }
            if (IsActive(s.StopOrder))
            {
                if (IsPendingState(s.StopOrder)) return;
                if (s.StopOrder.OrderAction != act) { CancelOrder(s.StopOrder); return; }
                int remaining = s.StopOrder.Quantity - s.StopOrder.Filled;
                if (remaining != protect || Math.Abs(s.StopOrder.StopPrice - px) > s.TickSize * 0.5)
                    ChangeOrder(s.StopOrder, protect + s.StopOrder.Filled, 0, px);
                return;
            }
            s.StopOrder = SubmitOrderUnmanaged(s.Bip, act, OrderType.StopMarket, protect, 0, px, "", "NxS_" + s.Name);
        }

        private void ExpireLimitOrder(NxSym s)
        {
            if (!IsActive(s.EntryOrder) || s.EntryOrder.OrderType != OrderType.Limit) return;
            if (s.Hist.Count < s.LimitExpiryBarCount || IsPendingState(s.EntryOrder)) return;
            NxV("Ordre limite expire " + s.Name + " -> annule");
            s.TargetQty = s.Qty;   // les remplissages partiels sont deja dans Qty
            CancelOrder(s.EntryOrder);
        }

        private void SoftStopOnBar(NxSym s, int bip)
        {
            bool soft = StopMode == NxStopMode.Logiciel || s.StopRejected;
            if (!soft || s.Qty == 0 || !NxMath.Ok(s.StopPrice)) return;
            bool hit = s.Qty > 0 ? Lows[bip][0] <= s.StopPrice : Highs[bip][0] >= s.StopPrice;
            if (!hit) return;
            Nx(string.Format(CultureInfo.InvariantCulture, "Stop logiciel touche {0} (stop {1}) -> sortie au marche", s.Name, s.StopPrice));
            s.StoppedOut = true; s.StoppedTime = Times[bip][0];
            SetTarget(s, 0, double.NaN, "stop logiciel");
            NxOnStopped(s);
            if (!NxBatchMode || State == State.Realtime) FlushTargets();
        }

        // =====================================================================
        //  Evenements d ordres et d executions
        // =====================================================================
        private NxSym SymOfOrder(Order o)
        {
            if (o == null || o.Name == null || o.Name.Length < 5) return null;
            if (!o.Name.StartsWith("NxE_") && !o.Name.StartsWith("NxS_")) return null;
            return Sym(o.Name.Substring(4));
        }

        protected override void OnOrderUpdate(Order order, double limitPrice, double stopPrice, int quantity, int filled, double averageFillPrice,
                                              OrderState orderState, DateTime time, ErrorCode error, string comment)
        {
            if (!nxReady) return;
            NxSym s = SymOfOrder(order);
            if (s == null) return;
            bool isEntry = order.Name.StartsWith("NxE_");
            bool isStop = !isEntry;
            if (isEntry && (s.EntryOrder == null || !IsActive(s.EntryOrder) || s.EntryOrder == order)) s.EntryOrder = order;
            if (isStop && (s.StopOrder == null || !IsActive(s.StopOrder) || s.StopOrder == order)) s.StopOrder = order;

            if (orderState == OrderState.Rejected)
            {
                Nx("Ordre rejete " + order.Name + " : " + error + " " + comment);
                if (isEntry) { s.Rejections++; s.TargetQty = s.Qty; }
                else { s.StopRejected = true; Nx("Stop natif rejete pour " + s.Name + " -> stop logiciel active pour ce symbole"); }
                if (State == State.Realtime) NxAlert("ordre rejete " + order.Name + " : " + comment);
            }
            if (!Order.IsTerminalState(orderState)) return;
            if (isStop) s.WaitingStopCancel = false;
            if (s.InSync) return;
            if (isEntry && orderState == OrderState.Filled) { SyncStop(s); return; }
            Sync(s);
        }

        protected override void OnExecutionUpdate(Execution execution, string executionId, double price, int quantity,
                                                  MarketPosition marketPosition, string orderId, DateTime time)
        {
            if (!nxReady || execution == null || execution.Order == null) return;
            Order o = execution.Order;
            NxSym s = SymOfOrder(o);
            if (s == null) return;
            bool isStop = o.Name.StartsWith("NxS_");
            int signed = IsBuy(o) ? quantity : -quantity;
            double expected = isStop ? o.StopPrice : s.DecisionPrice;
            ApplyFill(s, signed, price, time, isStop ? "stop" : s.PendingReason);
            if (JournalActive && !IsOptimizing)
            {
                Journal.Enabled = true;
                Journal.Fill(time, s.Name, o.OrderAction.ToString(), quantity, expected, price, o.Name, State == State.Realtime, IsRealMoney);
            }
            if (isStop)
            {
                s.StoppedOut = true;
                s.StoppedTime = time;
                s.TargetQty = s.Qty;
                if (s.Qty == 0) s.StopPrice = double.NaN;
                Nx(string.Format(CultureInfo.InvariantCulture, "Stop execute {0} x{1} @ {2}", s.Name, quantity, price));
                try { NxOnStopped(s); } catch { }
            }
            if (RegistryOn)
            {
                if (s.Qty == 0) NxPortfolioRegistry.Release(Account.Name, s.Name, StrategyId);
                else NxPortfolioRegistry.UpdateNotional(Account.Name, s.Name, StrategyId, Notional(s, s.Qty, price), s.Class);
            }
            try { NxOnFill(s, signed, price, time); } catch (Exception ex) { Nx("Erreur NxOnFill : " + ex.Message); }
            if (s.InSync) return;
            SyncStop(s);
            if (!IsActive(s.EntryOrder) && s.TargetQty != s.Qty) Sync(s);
            if (s.Dirty && State == State.Realtime) FlushTargets();
        }

        private void ApplyFill(NxSym s, int signedQty, double price, DateTime time, string reason)
        {
            if (signedQty == 0) return;
            double vpp = ValuePerPoint(s);
            double cost = Costs.Cost(s.Class, Math.Abs(signedQty) * price * vpp, Math.Abs(signedQty)) + NxExtraFillCost(s, Math.Abs(signedQty), price);
            realizedNet -= cost;
            if (s.Qty == 0)
            {
                OpenTrade(s, signedQty, price, time, cost);
                return;
            }
            if (Math.Sign(signedQty) == Math.Sign(s.Qty))
            {
                s.AvgPrice = (s.AvgPrice * Math.Abs(s.Qty) + price * Math.Abs(signedQty)) / (Math.Abs(s.Qty) + Math.Abs(signedQty));
                s.Qty += signedQty;
                s.TradeCosts += cost;
                s.MaxQty = Math.Max(s.MaxQty, Math.Abs(s.Qty));
                s.MaxNotional = Math.Max(s.MaxNotional, Notional(s, s.Qty, price));
                return;
            }
            int closeQ = Math.Min(Math.Abs(signedQty), Math.Abs(s.Qty));
            double pnl = (price - s.AvgPrice) * closeQ * vpp * Math.Sign(s.Qty);
            realizedNet += pnl;
            s.TradeGross += pnl;
            s.TradeCosts += cost;
            int remainder = Math.Abs(signedQty) - closeQ;
            s.Qty += Math.Sign(signedQty) * closeQ;
            if (s.Qty == 0)
            {
                CloseTrade(s, price, time, reason);
                if (remainder > 0) OpenTrade(s, Math.Sign(signedQty) * remainder, price, time, 0.0);
            }
        }

        private void OpenTrade(NxSym s, int signedQty, double price, DateTime time, double cost)
        {
            s.Qty = signedQty;
            s.AvgPrice = price;
            s.OpenTime = time;
            s.EntryDay = s.Hist.Count > 0 ? s.Hist.LastDate : time.Date;
            s.EntryBarCount = s.Hist.Count;
            s.TradeGross = 0;
            s.TradeCosts = cost;
            s.MaxQty = Math.Abs(signedQty);
            s.MaxNotional = Notional(s, signedQty, price);
            s.Direction = Math.Sign(signedQty);
            s.EntryReason = s.PendingReason ?? "";
            s.StoppedOut = false;
        }

        private void CloseTrade(NxSym s, double price, DateTime time, string reason)
        {
            NxTradeRecord r = new NxTradeRecord
            {
                Strategy = StrategyId, Symbol = s.Name, Class = s.Class, Direction = s.Direction, MaxQty = s.MaxQty,
                EntryTime = s.OpenTime, ExitTime = time, EntryPrice = s.AvgPrice, ExitPrice = price, MaxNotional = s.MaxNotional,
                GrossPnl = s.TradeGross, Costs = s.TradeCosts, NetPnl = s.TradeGross - s.TradeCosts,
                EntryReason = s.EntryReason, ExitReason = reason ?? "", Regime = s.Regime,
                IsRealtime = State == State.Realtime, IsRealMoney = IsRealMoney
            };
            r.NetReturn = s.MaxNotional > 0 ? r.NetPnl / s.MaxNotional : 0.0;
            r.GrossReturn = s.MaxNotional > 0 ? r.GrossPnl / s.MaxNotional : 0.0;
            RecordTrade(r);
            try { NxOnTradeClosed(s, r); } catch (Exception ex) { Nx("Erreur NxOnTradeClosed : " + ex.Message); }
        }

        /// <summary>Enregistre un trade ferme (statistiques Kelly, waiver, journal, rapport).</summary>
        protected void RecordTrade(NxTradeRecord r)
        {
            ClosedTrades.Add(r);
            Stats.Add(r.NetReturn);
            if (r.IsRealMoney) { Stats.LiveResolved++; Stats.SaveLiveCount(StrategyId); }
            if (JournalActive && !IsOptimizing) { Journal.Enabled = true; Journal.Trade(r); }
        }

        // =====================================================================
        //  Temps reel : transition, minuterie, chien de garde, interrupteur
        // =====================================================================
        private void OnEnterRealtime()
        {
            foreach (NxSym s in Syms)
            {
                if (s.EntryOrder != null) s.EntryOrder = GetRealtimeOrder(s.EntryOrder);
                if (s.StopOrder != null) s.StopOrder = GetRealtimeOrder(s.StopOrder);
                if (s.Traded && s.Qty != 0 && RegistryOn && !NxPortfolioRegistry.TryClaim(Account.Name, s.Name, StrategyId, s.Class))
                    NxAlert("conflit : " + s.Name + " deja detenu par " + NxPortfolioRegistry.Owner(Account.Name, s.Name));
            }
            bool usStocks = Syms.Any(x => x.Traded && x.Type == InstrumentType.Stock);
            double bank = Bankroll();
            if (usStocks && bank < 25000)
                NxAlert(string.Format(CultureInfo.InvariantCulture,
                    "AVERTISSEMENT PDT : capital {0:F0} $ < 25 000 $ - la regle Pattern Day Trader limite les allers-retours intrajournaliers sur actions US.", bank));
            if (UseKillSwitch && NxKillSwitch.IsActive()) NxAlert("interrupteur global ACTIF : aucune nouvelle entree (supprimer " + NxPaths.KillSwitchFile + ")");
            Nx(string.Format(CultureInfo.InvariantCulture, "Passage en temps reel sur {0} - equity interne {1:F2}, trades reels resolus {2}/{3}",
                Account != null ? Account.Name : "?", Equity, Stats.LiveResolved, WaiverTrades));
            try { rtTimer = new Timer(OnTimerTick, null, 500, 500); } catch (Exception ex) { Nx("Minuterie indisponible : " + ex.Message); }
        }

        private void OnTimerTick(object state)
        {
            if (Interlocked.Exchange(ref timerBusy, 1) == 1) return;
            try
            {
                if (State != State.Realtime) { Interlocked.Exchange(ref timerBusy, 0); return; }
                TriggerCustomEvent(o =>
                {
                    try { TimerWork(); }
                    catch (Exception ex) { NxOnce("timer" + ex.Message, "Erreur minuterie : " + ex.Message); }
                    finally { Interlocked.Exchange(ref timerBusy, 0); }
                }, null);
            }
            catch { Interlocked.Exchange(ref timerBusy, 0); }
        }

        private void TimerWork()
        {
            if (State != State.Realtime) return;
            DateTime nowUtc = DateTime.UtcNow;

            // 1) Lot en attente : une serie illiquide n a pas encore clos -> on traite apres le delai.
            if (pendingBatchDay > LastBatchDay && (nowUtc - pendingSinceUtc).TotalSeconds >= RealtimeBatchWaitSeconds)
            {
                Nx("Lot du " + pendingBatchDay.ToString("yyyy-MM-dd HH:mm") + " traite apres " + RealtimeBatchWaitSeconds + " s d attente (series incompletes)");
                RunBatch(pendingBatchDay, pendingBatchTradingDay);
            }

            // 2) Chien de garde des remplissages (500 ms, 5 s max, puis annulation de secours).
            foreach (NxSym s in Syms)
            {
                if (!s.Traded || !IsActive(s.EntryOrder) || IsPendingState(s.EntryOrder)) continue;
                double age = (nowUtc - s.EntrySubmitUtc).TotalSeconds;
                bool isLimit = s.EntryOrder.OrderType == OrderType.Limit;
                bool timeout = (!isLimit && FillTimeoutSeconds > 0 && age > FillTimeoutSeconds)
                            || (isLimit && LimitOrderTimeoutMinutes > 0 && age > LimitOrderTimeoutMinutes * 60.0);
                if (!timeout) continue;
                Nx(string.Format(CultureInfo.InvariantCulture, "Chien de garde : {0} non rempli apres {1:F0} s -> annulation de secours", s.EntryOrder.Name, age));
                s.TargetQty = s.Qty;
                CancelOrder(s.EntryOrder);
            }

            // 3) Interrupteur global : tout aplatir une fois.
            if (UseKillSwitch && NxKillSwitch.IsActive())
            {
                if (!killHandled)
                {
                    killHandled = true;
                    NxAlert("INTERRUPTEUR GLOBAL ACTIVE -> fermeture de toutes les positions et blocage des entrees");
                    FlatAll("interrupteur global");
                    FlushTargets();
                }
            }
            else killHandled = false;

            // 4) Stops logiciels par sondage (60 s actions, 1 s crypto) et marquage au marche.
            bool mark = (nowUtc - lastMarkUtc).TotalSeconds >= 5;
            foreach (NxSym s in Syms)
            {
                if (!s.Traded) continue;
                bool soft = (StopMode == NxStopMode.Logiciel || s.StopRejected) && s.Qty != 0 && NxMath.Ok(s.StopPrice);
                int poll = s.Class == NxAssetClass.Crypto ? SoftStopPollSecondsCrypto : SoftStopPollSecondsEquity;
                bool doSoft = soft && (nowUtc - s.LastSoftCheckUtc).TotalSeconds >= poll;
                if (!doSoft && !(mark && s.Qty != 0)) continue;
                double px = LivePrice(s);
                if (mark && NxMath.Ok(px)) s.LastPrice = px;
                if (!doSoft) continue;
                s.LastSoftCheckUtc = nowUtc;
                if (!NxMath.Ok(px)) continue;
                if ((s.Qty > 0 && px <= s.StopPrice) || (s.Qty < 0 && px >= s.StopPrice))
                {
                    Nx(string.Format(CultureInfo.InvariantCulture, "Stop logiciel (sondage) {0} : {1} vs stop {2}", s.Name, px, s.StopPrice));
                    s.StoppedOut = true; s.StoppedTime = NowNt;
                    SetTarget(s, 0, double.NaN, "stop logiciel");
                    NxOnStopped(s);
                }
            }
            if (mark)
            {
                lastMarkUtc = nowUtc;
                DateTime day = Syms.Count > 0 ? Syms.Max(x => x.Hist.Count > 0 ? x.Hist.LastDate : DateTime.MinValue) : NowNt.Date;
                double eq = Equity;
                if (Breaker.Update(NowNt, NinjaTrader.Core.Globals.Now.Date > day ? NinjaTrader.Core.Globals.Now.Date : day, eq) && Breaker.LastEvent != null)
                {
                    Nx(Breaker.LastEvent);
                    if (Breaker.LastEvent.Contains("DISJONCTEUR")) NxAlert(Breaker.LastEvent);
                }
            }

            // 5) Entrees differees (filtre de choc) : nouvel essai.
            foreach (NxSym s in Syms) if (s.Deferred) s.Dirty = true;

            NxOnTimer();
            FlushTargets();
        }

        /// <summary>Prix courant sur (mid bid/ask filtre par la garde de cotation, sinon derniere cloture).</summary>
        protected double LivePrice(NxSym s)
        {
            if (State != State.Realtime) return s.LastPrice;
            double bid = double.NaN, ask = double.NaN;
            try { bid = GetCurrentBid(s.Bip); ask = GetCurrentAsk(s.Bip); } catch { }
            bool fb;
            return NxQuoteGuard.SafePrice(bid, ask, s.Hist.LastClose, QuoteMaxDeviationPct / 100.0, out fb);
        }

        /// <summary>Ecart bid/ask relatif courant (NaN hors temps reel).</summary>
        protected double LiveSpreadPct(NxSym s)
        {
            if (State != State.Realtime) return double.NaN;
            try { return NxQuoteGuard.SpreadPct(GetCurrentBid(s.Bip), GetCurrentAsk(s.Bip)); } catch { return double.NaN; }
        }

        // =====================================================================
        //  Fin de run : rendements par configuration, rapport, audit IA
        // =====================================================================
        private string ConfigKey()
        {
            StringBuilder sb = new StringBuilder(GetType().Name);
            foreach (PropertyInfo p in GetType().GetProperties(BindingFlags.Public | BindingFlags.Instance)
                                               .Where(p => p.IsDefined(typeof(NinjaScriptPropertyAttribute), true)).OrderBy(p => p.Name))
            {
                object v = null;
                try { v = p.GetValue(this, null); } catch { }
                sb.Append('|').Append(p.Name).Append('=').Append(Convert.ToString(v, CultureInfo.InvariantCulture));
            }
            return sb.ToString();
        }

        private void FinalizeRun()
        {
            FinalizeDay();
            if (SaveReturnsForPbo && EquityDays.Count > 20)
                NxTrialStore.Save(Name, ConfigKey(), EquityDays.Skip(1).ToList(), DailyReturns);
            if (!WriteReport || IsOptimizing) return;
            if (ClosedTrades.Count == 0 && DailyReturns.Count < 2) return;

            NxReportInput input = new NxReportInput
            {
                StrategyId = StrategyId, Title = Name, Parameters = ConfigKey().Replace("|", "  "), InitialEquity = InitialBankroll,
                Trades = ClosedTrades, Days = EquityDays, DailyReturns = DailyReturns, Equity = EquityValues, Costs = Costs,
                HasCrypto = Syms.Any(x => x.Traded && x.Class == NxAssetClass.Crypto), MonteCarloSims = MonteCarloSims, BlockLength = BlockLength,
                CircuitDdTrips = Breaker.DrawdownTrips, CircuitDailyTrips = Breaker.DailyTrips, FillsFile = Journal.FillsFile
            };
            int nConf; double varSr;
            List<double[]> conf = NxTrialStore.LoadAligned(Name, out nConf, out varSr);
            input.Trials = Math.Max(1, nConf);
            input.VarTrialsSharpe = varSr;
            if (conf.Count >= 2)
            {
                int combos;
                input.Pbo = NxValidation.Pbo(conf, 16, 2000, 11, out combos);
                input.PboConfigs = conf.Count;
                input.PboCombos = combos;
            }
            double[] ai = NxAiLedger.Totals(StrategyId);
            if (ai[3] > 0) { input.AiCostUsd = ai[2]; input.AiTokens = (long)(ai[0] + ai[1]); }

            List<string> extra = new List<string>();
            try { NxReportExtras(extra); } catch (Exception ex) { extra.Add("(erreur extras : " + ex.Message + ")"); }
            List<NxStressPosition> open = Syms.Where(x => x.Traded && x.Qty != 0 && NxMath.Ok(x.LastPrice))
                .Select(x => new NxStressPosition { Symbol = x.Name, Qty = x.Qty, Price = x.LastPrice, Stop = x.StopPrice, ValuePerPoint = ValuePerPoint(x) }).ToList();
            extra.Add(NxStressTest.Run(open, Equity, StressShockPct / 100.0, StressWorstN));
            if (State == State.Realtime || Category == Category.NinjaScript) extra.Add(NxPortfolioRegistry.CorrelationReport(CorrelationWindow));
            input.Extra = extra;

            string txt = NxReport.Build(input);
            string path = NxReport.Write(StrategyId, txt);
            Print(txt);
            Print("[Nexus] Rapport ecrit : " + path);

            if (AuditWithLlm)
            {
                NxLlmConfig cfg = new NxLlmConfig
                {
                    Provider = AuditProvider,
                    Model = string.IsNullOrWhiteSpace(AuditModel) ? NxLlmConfig.DefaultModel(AuditProvider) : AuditModel.Trim(),
                    ApiKey = NxSecrets.Resolve(AuditApiKey, NxLlmConfig.DefaultEnvVar(AuditProvider)),
                    MaxTokens = 1500, TimeoutSec = 120
                };
                string id = StrategyId;
                Task.Run(() =>
                {
                    NxLlmResult r = NxLlm.Complete(cfg, NxPrompts.AuditSystem, NxPrompts.AuditUser(txt), null, NxPrompts.Version);
                    NxAiLedger.Record(id, cfg, r, "audit_rapport", true);
                    NxCsv.WriteAll(path.Replace(".txt", "_audit_" + cfg.Provider + ".txt"), r.Ok ? r.Text : ("Audit impossible : " + r.Error));
                });
                Print("[Nexus] Audit du rapport demande a " + cfg.Label + " (fichier *_audit_*.txt a cote du rapport)");
            }
        }

        // =====================================================================
        //  Proprietes
        // =====================================================================
        #region 00. Univers
        [NinjaScriptProperty]
        [Display(Name = "Symboles trades", Description = "Instruments separes par des virgules (noms NinjaTrader). Absents de la base = ignores.", Order = 1, GroupName = "00. Univers")]
        public string Symbols { get; set; }

        [Display(Name = "Symboles de reference", Description = "Series chargees mais jamais tradees (barometre, ETF sectoriels, VIX, paires FX de conversion).", Order = 2, GroupName = "00. Univers")]
        public string ReferenceSymbols { get; set; }

        [Display(Name = "Liste des ETF", Description = "Tickers classes 'ETF' (classe d actifs) au lieu de 'Action'.", Order = 3, GroupName = "00. Univers")]
        public string EtfSymbols { get; set; }

        [Display(Name = "Vente a decouvert autorisee", Order = 4, GroupName = "00. Univers")]
        public bool AllowShortSelling { get; set; }

        [Range(1, int.MaxValue)]
        [Display(Name = "Taille de lot", Description = "Arrondi des quantites (1 action, 1 contrat, 1000 unites forex...).", Order = 5, GroupName = "00. Univers")]
        public int LotSize { get; set; }

        [Display(Name = "Taux de change de repli", Description = "Devise=valeur en USD, utilises si la paire XXXUSD n est pas chargee.", Order = 6, GroupName = "00. Univers")]
        public string FxFallback { get; set; }
        #endregion

        #region 80. Module B - capital et taille
        [Range(1, double.MaxValue)]
        [Display(Name = "Capital initial ($)", Order = 1, GroupName = "80. Module B - Capital et taille")]
        public double InitialBankroll { get; set; }

        [Display(Name = "Source du capital", Description = "Interne = capital initial + PnL de la strategie ; Compte = NetLiquidation en temps reel.", Order = 2, GroupName = "80. Module B - Capital et taille")]
        public NxCapitalSource CapitalSource { get; set; }

        [Display(Name = "Mode de taille", Order = 3, GroupName = "80. Module B - Capital et taille")]
        public NxSizingMode SizingMode { get; set; }

        [Display(Name = "Lecture de Kelly", Order = 4, GroupName = "80. Module B - Capital et taille")]
        public NxKellyLecture KellyLecture { get; set; }

        [Range(0.0, 1.0)]
        [Display(Name = "Multiplicateur Kelly", Description = "0.5 = demi-Kelly [Fil].", Order = 5, GroupName = "80. Module B - Capital et taille")]
        public double KellyMultiplier { get; set; }

        [Range(0.01, 0.99)]
        [Display(Name = "A priori : taux de reussite", Order = 6, GroupName = "80. Module B - Capital et taille")]
        public double PriorWinRate { get; set; }

        [Range(0.05, 20.0)]
        [Display(Name = "A priori : gain/perte (b)", Order = 7, GroupName = "80. Module B - Capital et taille")]
        public double PriorPayoff { get; set; }

        [Range(0.1, 100.0)]
        [Display(Name = "A priori : perte moyenne (%)", Order = 8, GroupName = "80. Module B - Capital et taille")]
        public double PriorAvgLossPct { get; set; }

        [Range(0, 10000)]
        [Display(Name = "A priori : poids (pseudo-trades)", Order = 9, GroupName = "80. Module B - Capital et taille")]
        public int PriorStrength { get; set; }

        [Range(0.0, 1.0)]
        [Display(Name = "Poids de la confiance du modele", Order = 10, GroupName = "80. Module B - Capital et taille")]
        public double ConfidenceWeight { get; set; }

        [Display(Name = "Borne basse de Wilson sur p", Order = 11, GroupName = "80. Module B - Capital et taille")]
        public bool UseWilsonLowerBound { get; set; }

        [Range(0.0, 100.0)]
        [Display(Name = "Taille sonde si Kelly<=0 (%)", Description = "0 = ne pas trader quand Kelly est negatif.", Order = 12, GroupName = "80. Module B - Capital et taille")]
        public double NoEdgeFractionPct { get; set; }

        [Range(0.01, 0.99)]
        [Display(Name = "Kelly contraint : plancher alpha", Order = 13, GroupName = "80. Module B - Capital et taille")]
        public double RckAlpha { get; set; }

        [Range(0.001, 0.99)]
        [Display(Name = "Kelly contraint : probabilite beta", Order = 14, GroupName = "80. Module B - Capital et taille")]
        public double RckBeta { get; set; }

        [Range(0, 100000)]
        [Display(Name = "Davey waiver : trades reels", Order = 15, GroupName = "80. Module B - Capital et taille")]
        public int WaiverTrades { get; set; }

        [Range(0.0, 1.0)]
        [Display(Name = "Davey waiver : multiplicateur", Order = 16, GroupName = "80. Module B - Capital et taille")]
        public double WaiverMultiplier { get; set; }

        [Range(0.0, 100000.0)]
        [Display(Name = "Plafond par trade (% bankroll)", Description = "0 = desactive.", Order = 17, GroupName = "80. Module B - Capital et taille")]
        public double MaxTradePct { get; set; }

        [Range(0.0, double.MaxValue)]
        [Display(Name = "Plafond par trade ($)", Description = "0 = desactive (30 $ au depart sur 1 000 $ dans le fil).", Order = 18, GroupName = "80. Module B - Capital et taille")]
        public double MaxTradeDollars { get; set; }

        [Range(0.0, 100000.0)]
        [Display(Name = "Plafond par symbole (%)", Order = 19, GroupName = "80. Module B - Capital et taille")]
        public double MaxSymbolPct { get; set; }

        [Range(0.0, 100000.0)]
        [Display(Name = "Plafond par classe d actifs (%)", Order = 20, GroupName = "80. Module B - Capital et taille")]
        public double MaxClassPct { get; set; }

        [Range(0.0, 100000.0)]
        [Display(Name = "Exposition totale max (%)", Order = 21, GroupName = "80. Module B - Capital et taille")]
        public double MaxTotalPct { get; set; }

        [Display(Name = "Correction de correlation", Description = "Taille / (1 + somme des correlations positives avec les positions ouvertes).", Order = 22, GroupName = "80. Module B - Capital et taille")]
        public bool UseCorrelationDivisor { get; set; }

        [Range(10, 1000)]
        [Display(Name = "Fenetre de correlation (jours)", Order = 23, GroupName = "80. Module B - Capital et taille")]
        public int CorrelationWindow { get; set; }

        [Display(Name = "Registre inter-strategies (temps reel)", Description = "Un titre = une seule strategie ; plafonds communs au compte.", Order = 24, GroupName = "80. Module B - Capital et taille")]
        public bool UseRegistry { get; set; }
        #endregion

        #region 81. Module C - risque et execution
        [Display(Name = "Disjoncteurs actifs", Order = 1, GroupName = "81. Module C - Risque et execution")]
        public bool UseCircuitBreakers { get; set; }

        [Range(0.1, 100.0)]
        [Display(Name = "Drawdown declencheur (%)", Order = 2, GroupName = "81. Module C - Risque et execution")]
        public double DrawdownTripPct { get; set; }

        [Range(0.0, 10000.0)]
        [Display(Name = "Pause apres drawdown (h)", Order = 3, GroupName = "81. Module C - Risque et execution")]
        public double DrawdownCooldownHours { get; set; }

        [Range(0.1, 100.0)]
        [Display(Name = "Perte journaliere declencheur (%)", Order = 4, GroupName = "81. Module C - Risque et execution")]
        public double DailyLossPct { get; set; }

        [Range(0.0, 10000.0)]
        [Display(Name = "Pause apres perte journaliere (h)", Order = 5, GroupName = "81. Module C - Risque et execution")]
        public double DailyCooldownHours { get; set; }

        [Display(Name = "Nouvelle reference apres pause", Description = "Le plus haut est remis a l equity courante a la fin de la pause (sinon blocage permanent).", Order = 6, GroupName = "81. Module C - Risque et execution")]
        public bool ResetPeakAfterCooldown { get; set; }

        [Range(0.0, 10.0)]
        [Display(Name = "Glissement modelise (%/ordre)", Order = 7, GroupName = "81. Module C - Risque et execution")]
        public double SlippagePct { get; set; }

        [Range(0.0, 10.0)]
        [Display(Name = "Frais actions/ETF (%/ordre)", Order = 8, GroupName = "81. Module C - Risque et execution")]
        public double EquityFeePct { get; set; }

        [Range(0.0, 10.0)]
        [Display(Name = "Frais crypto (%/ordre)", Order = 9, GroupName = "81. Module C - Risque et execution")]
        public double CryptoFeePct { get; set; }

        [Display(Name = "Remise BNB (0.075 %)", Order = 10, GroupName = "81. Module C - Risque et execution")]
        public bool UseBnbDiscount { get; set; }

        [Range(0.0, 10.0)]
        [Display(Name = "Frais autres classes (%/ordre)", Order = 11, GroupName = "81. Module C - Risque et execution")]
        public double OtherFeePct { get; set; }

        [Range(0.0, 1000.0)]
        [Display(Name = "Frais par contrat ($)", Order = 12, GroupName = "81. Module C - Risque et execution")]
        public double PerContractFee { get; set; }

        [Display(Name = "Mode des stops", Order = 13, GroupName = "81. Module C - Risque et execution")]
        public NxStopMode StopMode { get; set; }

        [Range(1, 3600)]
        [Display(Name = "Sondage stop logiciel actions (s)", Order = 14, GroupName = "81. Module C - Risque et execution")]
        public int SoftStopPollSecondsEquity { get; set; }

        [Range(1, 3600)]
        [Display(Name = "Sondage stop logiciel crypto (s)", Order = 15, GroupName = "81. Module C - Risque et execution")]
        public int SoftStopPollSecondsCrypto { get; set; }

        [Range(0, 3600)]
        [Display(Name = "Delai max de remplissage marche (s)", Description = "Sondage 500 ms puis annulation de secours (0 = jamais).", Order = 16, GroupName = "81. Module C - Risque et execution")]
        public int FillTimeoutSeconds { get; set; }

        [Range(0, 100000)]
        [Display(Name = "Delai max ordre limite (min)", Description = "0 = jusqu a expiration par barres.", Order = 17, GroupName = "81. Module C - Risque et execution")]
        public int LimitOrderTimeoutMinutes { get; set; }

        [Range(0, 1440)]
        [Display(Name = "Retard des donnees (min)", Description = "Decalage de fin de periode (SIP gratuit retarde : 16 = 15 + 1 de marge). 0 = variable d environnement NEXUS_DATA_DELAY_MINUTES.", Order = 18, GroupName = "81. Module C - Risque et execution")]
        public int DataDelayMinutes { get; set; }

        [Range(1.0, 100.0)]
        [Display(Name = "Garde de cotation (% d ecart max)", Order = 19, GroupName = "81. Module C - Risque et execution")]
        public double QuoteMaxDeviationPct { get; set; }

        [Display(Name = "Interrupteur global (fichier KILL_SWITCH)", Order = 20, GroupName = "81. Module C - Risque et execution")]
        public bool UseKillSwitch { get; set; }

        [Display(Name = "Filtre de choc taker (fiche 4B)", Description = "Temps reel : differer une entree apres une bougie de choc et entrer a cours limite.", Order = 21, GroupName = "81. Module C - Risque et execution")]
        public bool UseShockFilter { get; set; }

        [Range(1, 3600)]
        [Display(Name = "Attente max du lot en reel (s)", Order = 22, GroupName = "81. Module C - Risque et execution")]
        public int RealtimeBatchWaitSeconds { get; set; }

        [Range(0.1, 100.0)]
        [Display(Name = "Stress test : choc (%)", Order = 23, GroupName = "81. Module C - Risque et execution")]
        public double StressShockPct { get; set; }

        [Range(1, 100)]
        [Display(Name = "Stress test : positions", Order = 24, GroupName = "81. Module C - Risque et execution")]
        public int StressWorstN { get; set; }
        #endregion

        #region 82. Module C - validation et journal
        [Display(Name = "Etiquette d instance", Description = "Suffixe des fichiers (plusieurs instances de la meme strategie).", Order = 1, GroupName = "82. Module C - Validation et journal")]
        public string InstanceTag { get; set; }

        [Display(Name = "Journal CSV", Order = 2, GroupName = "82. Module C - Validation et journal")]
        public NxJournalMode JournalMode { get; set; }

        [Display(Name = "Rapport de fin de run", Order = 3, GroupName = "82. Module C - Validation et journal")]
        public bool WriteReport { get; set; }

        [Display(Name = "Sauver rendements pour PBO", Description = "Chaque run/iteration d optimisation ecrit ses rendements journaliers (DSR multi-essais et PBO).", Order = 4, GroupName = "82. Module C - Validation et journal")]
        public bool SaveReturnsForPbo { get; set; }

        [Range(100, 100000)]
        [Display(Name = "Monte Carlo : tirages", Order = 5, GroupName = "82. Module C - Validation et journal")]
        public int MonteCarloSims { get; set; }

        [Range(0, 10000)]
        [Display(Name = "Bootstrap par blocs : longueur", Description = "0 = racine du nombre de trades.", Order = 6, GroupName = "82. Module C - Validation et journal")]
        public int BlockLength { get; set; }

        [Display(Name = "Audit du rapport par une 2e IA", Order = 7, GroupName = "82. Module C - Validation et journal")]
        public bool AuditWithLlm { get; set; }

        [Display(Name = "Audit : fournisseur", Order = 8, GroupName = "82. Module C - Validation et journal")]
        public NxLlmProvider AuditProvider { get; set; }

        [Display(Name = "Audit : modele (vide = defaut)", Order = 9, GroupName = "82. Module C - Validation et journal")]
        public string AuditModel { get; set; }

        [Display(Name = "Audit : cle API (vide = variable d env.)", Order = 10, GroupName = "82. Module C - Validation et journal")]
        public string AuditApiKey { get; set; }

        [Display(Name = "Journal detaille (Output)", Order = 11, GroupName = "82. Module C - Validation et journal")]
        public bool VerboseLog { get; set; }
        #endregion
    }
}
