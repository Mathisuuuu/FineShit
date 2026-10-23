// =============================================================================
//  NtScriptStub.cs - EMULATEUR MINIMAL de l API NinjaScript (NinjaTrader 8)
//
//  But : compiler NexusStrategyBase.cs et les strategies Nexus hors de
//  NinjaTrader (Linux / .NET 8) et les executer en "historique" sur des barres
//  fournies par le banc d essai. Seuls les membres utilises par le socle et la
//  fiche 15 sont reproduits, avec les conventions de NinjaTrader 8 :
//    - barres horodatees a leur CLOTURE, fuseau = Globals.GeneralOptions.TimeZoneInfo ;
//    - series traitees par horodatage croissant, puis par BarsInProgress croissant ;
//    - Calculate.OnBarClose : un ordre soumis pendant la barre n est evalue a
//      partir de la barre n+1 de sa serie (marche = ouverture de n+1 ; limite et
//      stop = toucher intrabar, ouverture si le prix saute le niveau) ;
//    - OnOrderUpdate (Submitted, Accepted, Working, Filled, Cancelled) puis
//      OnExecutionUpdate, appeles de facon synchrone comme en historique NT.
//  Ce n est PAS NinjaTrader : la validation finale reste un backtest dans le
//  Strategy Analyzer (voir LISEZMOI).
// =============================================================================
using System;
using System.Collections.Generic;
using System.Globalization;
using System.Linq;
using NinjaTrader.Cbi;
using NinjaTrader.Data;
using NinjaTrader.NinjaScript;

namespace System.Windows.Media
{
    public class Brush { }
    public static class Brushes
    {
        public static readonly Brush DarkRed = new Brush();
        public static readonly Brush White = new Brush();
    }
}

namespace NinjaTrader.Cbi
{
    public enum Currency { UsDollar, Euro, BritishPound, JapaneseYen, AustralianDollar, SwissFranc, CanadianDollar, NewZealandDollar, HongKongDollar, SwedishKrona, NorwayKrone, MexicanPeso, SingaporeDollar, Unknown }
    public enum InstrumentType { Stock, Future, Index, Forex, CryptoCurrency, Cfd, Option, Unknown }
    public enum OrderAction { Buy, BuyToCover, Sell, SellShort }
    public enum OrderType { Market, Limit, StopMarket, StopLimit, MIT, Unknown }
    public enum OrderState { Initialized, Submitted, Accepted, TriggerPending, Working, ChangePending, ChangeSubmitted, CancelPending, CancelSubmitted, Cancelled, PartFilled, Filled, Rejected, Unknown }
    public enum MarketPosition { Flat, Long, Short }
    public enum ErrorCode { NoError, OrderRejected, Panic, Unknown }
    public enum TimeInForce { Day, Gtc, Gtd, Ioc, Opg }
    public enum AccountItem { NetLiquidation, CashValue, BuyingPower, RealizedProfitLoss }
    public enum LogLevel { Information, Warning, Error, Alert }

    public class MasterInstrument
    {
        public string Name = "";
        public double PointValue = 1.0;
        public double TickSize = 0.01;
        public Currency Currency = Currency.UsDollar;
        public InstrumentType InstrumentType = InstrumentType.Stock;
        public double RoundToTickSize(double price) { return Math.Round(Math.Round(price / TickSize) * TickSize, 10); }
    }

    public class Instrument
    {
        public string FullName = "";
        public MasterInstrument MasterInstrument = new MasterInstrument();
        /// <summary>Base d instruments du simulateur (nom -> instrument, null si absent).</summary>
        public static Func<string, Instrument> Resolver;
        public static Instrument GetInstrument(string name, bool create) { return Resolver != null ? Resolver(name) : null; }
        public override string ToString() { return FullName; }
    }

    public class Order
    {
        private static long nextId;
        public readonly long Id = ++nextId;
        public string Name = "";
        public OrderAction OrderAction;
        public OrderType OrderType;
        public int Quantity;
        public int Filled;
        public double LimitPrice;
        public double StopPrice;
        public double AverageFillPrice;
        public OrderState OrderState = OrderState.Initialized;
        public int BarsInProgressIndex;
        public int SubmitBar;
        public int SimFillBar = -1;
        public string OrderId { get { return Id.ToString(CultureInfo.InvariantCulture); } }
        public static bool IsTerminalState(OrderState s) { return s == OrderState.Cancelled || s == OrderState.Filled || s == OrderState.Rejected || s == OrderState.Unknown; }
        public override string ToString() { return string.Format(CultureInfo.InvariantCulture, "{0} {1} {2} x{3} L{4} S{5} {6}", Name, OrderAction, OrderType, Quantity, LimitPrice, StopPrice, OrderState); }
    }

    public class Execution
    {
        public Order Order;
        public double Price;
        public int Quantity;
        public DateTime Time;
        public string ExecutionId = "";
    }

    public class Account
    {
        public string Name = "Backtest";
        public double Get(AccountItem item, Currency currency) { return 0.0; }
    }
}

namespace NinjaTrader.Data
{
    public enum BarsPeriodType { Tick, Volume, Range, Second, Minute, Day, Week, Month, Year }

    public class BarsPeriod
    {
        public BarsPeriodType BarsPeriodType;
        public int Value;
    }

    public class TradingHours
    {
        public string Name = "";
        public Dictionary<DateTime, string> Holidays = new Dictionary<DateTime, string>();
        public TimeSpan SessionEnd = new TimeSpan(16, 15, 0);
    }

    public struct SimBar
    {
        public DateTime Time;
        public double Open, High, Low, Close, Volume;
        public SimBar(DateTime t, double o, double h, double l, double c, double v) { Time = t; Open = o; High = h; Low = l; Close = c; Volume = v; }
    }

    public class Bars
    {
        public NinjaTrader.Cbi.Instrument Instrument;
        public BarsPeriod BarsPeriod;
        public TradingHours TradingHours = new TradingHours();
        public IList<SimBar> Data = new List<SimBar>();
        public int Count { get { return Data.Count; } }
        public DateTime GetTime(int index) { return Data[index].Time; }
    }

    /// <summary>Seances sans passage de minuit (barres RTH du simulateur) : jour de bourse = date de la barre.</summary>
    public class SessionIterator
    {
        private readonly Bars bars;
        public DateTime ActualSessionBegin;
        public DateTime ActualSessionEnd;
        public SessionIterator(Bars b) { bars = b; }
        public DateTime GetTradingDay(DateTime time) { return time.Date; }
        public DateTime GetTradingDayEndLocal(DateTime tradingDay) { return tradingDay.Date + (bars != null ? bars.TradingHours.SessionEnd : new TimeSpan(16, 15, 0)); }
        public bool GetNextSession(DateTime time, bool includesEndTimeStamp)
        {
            if (bars == null) return false;
            foreach (SimBar b in bars.Data)
                if (b.Time > time)
                {
                    DateTime d = b.Time.Date;
                    ActualSessionBegin = bars.Data.First(x => x.Time.Date == d).Time.AddMinutes(-1);
                    ActualSessionEnd = d + bars.TradingHours.SessionEnd;
                    return true;
                }
            return false;
        }
    }
}

namespace NinjaTrader.NinjaScript
{
    public enum State { SetDefaults, Configure, Active, DataLoaded, Historical, Transition, Realtime, Terminated, Finalized }
    public enum Calculate { OnBarClose, OnEachTick, OnPriceChange }
    public enum StartBehavior { WaitUntilFlat, WaitUntilFlatSynchronizeAccount, ImmediatelySubmit, ImmediatelySubmitSynchronizeAccount, AdoptAccountPosition }
    public enum RealtimeErrorHandling { StopCancelClose, StopCancelCloseIgnoreRejects, IgnoreAllErrors }
    public enum MaximumBarsLookBack { TwoHundredFiftySix, Infinite }
    public enum OrderFillResolution { Standard, High }
    public enum Category { Backtest, NinjaScript, Optimize, WalkForward, WalkForwardAnchored, MultiObjective, Playback, Realtime }
    public enum Priority { Low, Medium, High }

    [AttributeUsage(AttributeTargets.Property)]
    public class NinjaScriptPropertyAttribute : Attribute { }

    /// <summary>Vue "barsAgo" d une serie (index 0 = barre courante de la serie).</summary>
    public class SeriesView<T>
    {
        private readonly Func<int, T> at;
        public SeriesView(Func<int, T> at) { this.at = at; }
        public T this[int barsAgo] { get { return at(barsAgo); } }
    }
}

namespace NinjaTrader.NinjaScript.Strategies
{
    public abstract class Strategy
    {
        // --- Proprietes NinjaTrader utilisees par le socle -------------------
        public Calculate Calculate { get; set; }
        public bool IsUnmanaged { get; set; }
        public int EntriesPerDirection { get; set; }
        public bool IsExitOnSessionCloseStrategy { get; set; }
        public int BarsRequiredToTrade { get; set; }
        public MaximumBarsLookBack MaximumBarsLookBack { get; set; }
        public bool IsInstantiatedOnEachOptimizationIteration { get; set; }
        public StartBehavior StartBehavior { get; set; }
        public RealtimeErrorHandling RealtimeErrorHandling { get; set; }
        public TimeInForce TimeInForce { get; set; }
        public OrderFillResolution OrderFillResolution { get; set; }
        public bool IsFillLimitOnTouch { get; set; }
        public bool TraceOrders { get; set; }
        public int Slippage { get; set; }
        public string Name { get; set; }
        public string Description { get; set; }
        public State State { get; private set; }
        public Category Category { get; set; }
        public Account Account { get; set; }

        // --- Series ----------------------------------------------------------
        public Bars[] BarsArray { get; private set; }
        public int BarsInProgress { get; private set; }
        public int[] CurrentBars { get; private set; }
        public NinjaScript.SeriesView<DateTime>[] Times { get; private set; }
        public NinjaScript.SeriesView<double>[] Opens { get; private set; }
        public NinjaScript.SeriesView<double>[] Highs { get; private set; }
        public NinjaScript.SeriesView<double>[] Lows { get; private set; }
        public NinjaScript.SeriesView<double>[] Closes { get; private set; }
        public NinjaScript.SeriesView<double>[] Volumes { get; private set; }

        // --- Etat du simulateur ---------------------------------------------
        internal readonly List<KeyValuePair<string, BarsPeriod>> SimRequests = new List<KeyValuePair<string, BarsPeriod>>();
        internal readonly List<string> SimTradingHours = new List<string>();
        internal readonly List<Order> SimWorking = new List<Order>();
        internal readonly List<Order> SimAllOrders = new List<Order>();
        internal Action<string> SimPrint = Console.WriteLine;
        private long execId;

        protected Strategy() { Account = new Account(); Category = Category.Backtest; }

        protected virtual void OnStateChange() { }
        protected virtual void OnBarUpdate() { }
        protected virtual void OnOrderUpdate(Order order, double limitPrice, double stopPrice, int quantity, int filled, double averageFillPrice,
                                             OrderState orderState, DateTime time, ErrorCode error, string comment) { }
        protected virtual void OnExecutionUpdate(Execution execution, string executionId, double price, int quantity,
                                                 MarketPosition marketPosition, string orderId, DateTime time) { }

        public void AddDataSeries(string instrumentName, BarsPeriodType periodType, int period)
        {
            SimRequests.Add(new KeyValuePair<string, BarsPeriod>(instrumentName, new BarsPeriod { BarsPeriodType = periodType, Value = period }));
            SimTradingHours.Add(null);
        }

        public void AddDataSeries(string instrumentName, BarsPeriod barsPeriod, string tradingHoursName)
        {
            SimRequests.Add(new KeyValuePair<string, BarsPeriod>(instrumentName, barsPeriod));
            SimTradingHours.Add(tradingHoursName);
        }

        public void Print(object value) { if (SimPrint != null) SimPrint(Convert.ToString(value, CultureInfo.InvariantCulture)); }
        public void Alert(string id, Priority priority, string message, string soundLocation, int rearmSeconds, System.Windows.Media.Brush backBrush, System.Windows.Media.Brush foreBrush) { }
        public void Log(string message, LogLevel logLevel) { }
        public Order GetRealtimeOrder(Order order) { return order; }
        public void TriggerCustomEvent(Action<object> customEvent, object state) { customEvent(state); }
        public double GetCurrentBid(int barsSeriesIndex) { return double.NaN; }
        public double GetCurrentAsk(int barsSeriesIndex) { return double.NaN; }

        // --- Ordres non geres ---------------------------------------------------
        public Order SubmitOrderUnmanaged(int selectedBarsInProgress, OrderAction orderAction, OrderType orderType, int quantity, double limitPrice,
                                          double stopPrice, string oco, string signalName)
        {
            Order o = new Order
            {
                Name = signalName ?? "", OrderAction = orderAction, OrderType = orderType, Quantity = quantity, LimitPrice = limitPrice, StopPrice = stopPrice,
                BarsInProgressIndex = selectedBarsInProgress, SubmitBar = CurrentBars[selectedBarsInProgress]
            };
            SimAllOrders.Add(o);
            DateTime t = CurrentTime(selectedBarsInProgress);
            if (quantity <= 0) { SetState(o, OrderState.Rejected, t, ErrorCode.OrderRejected, "quantite nulle"); return o; }
            SetState(o, OrderState.Submitted, t, ErrorCode.NoError, "");
            SetState(o, OrderState.Accepted, t, ErrorCode.NoError, "");
            SimWorking.Add(o);
            SetState(o, OrderState.Working, t, ErrorCode.NoError, "");
            return o;
        }

        public void CancelOrder(Order order)
        {
            if (order == null || Order.IsTerminalState(order.OrderState)) return;
            DateTime t = CurrentTime(order.BarsInProgressIndex);
            SimWorking.Remove(order);
            SetState(order, OrderState.CancelPending, t, ErrorCode.NoError, "");
            SetState(order, OrderState.Cancelled, t, ErrorCode.NoError, "");
        }

        public void ChangeOrder(Order order, int quantity, double limitPrice, double stopPrice)
        {
            if (order == null || Order.IsTerminalState(order.OrderState)) return;
            DateTime t = CurrentTime(order.BarsInProgressIndex);
            order.Quantity = quantity; order.LimitPrice = limitPrice; order.StopPrice = stopPrice;
            SetState(order, OrderState.ChangePending, t, ErrorCode.NoError, "");
            SetState(order, OrderState.Working, t, ErrorCode.NoError, "");
        }

        private DateTime CurrentTime(int bip)
        {
            int i = CurrentBars != null && bip < CurrentBars.Length ? CurrentBars[bip] : -1;
            return i >= 0 ? BarsArray[bip].Data[i].Time : DateTime.MinValue;
        }

        private void SetState(Order o, OrderState s, DateTime t, ErrorCode e, string comment)
        {
            o.OrderState = s;
            OnOrderUpdate(o, o.LimitPrice, o.StopPrice, o.Quantity, o.Filled, o.AverageFillPrice, s, t, e, comment);
        }

        /// <summary>Remplissages sur la barre qui s ouvre (ordres soumis avant elle uniquement).</summary>
        private void ProcessFills(int bip, SimBar bar, int barIndex)
        {
            if (SimWorking.Count == 0) return;
            List<Order> snapshot = SimWorking.Where(o => o.BarsInProgressIndex == bip && o.SubmitBar < barIndex).ToList();
            foreach (Order o in snapshot)
            {
                if (Order.IsTerminalState(o.OrderState) || !SimWorking.Contains(o)) continue;
                bool buy = o.OrderAction == OrderAction.Buy || o.OrderAction == OrderAction.BuyToCover;
                double px = double.NaN;
                bool atOpen = false;
                switch (o.OrderType)
                {
                    case OrderType.Market: px = bar.Open; atOpen = true; break;
                    case OrderType.Limit:
                        if (buy) { if (bar.Open <= o.LimitPrice) { px = bar.Open; atOpen = true; } else if (bar.Low < o.LimitPrice || (IsFillLimitOnTouch && bar.Low <= o.LimitPrice)) px = o.LimitPrice; }
                        else { if (bar.Open >= o.LimitPrice) { px = bar.Open; atOpen = true; } else if (bar.High > o.LimitPrice || (IsFillLimitOnTouch && bar.High >= o.LimitPrice)) px = o.LimitPrice; }
                        break;
                    case OrderType.StopMarket:
                        if (buy) { if (bar.Open >= o.StopPrice) { px = bar.Open; atOpen = true; } else if (bar.High >= o.StopPrice) px = o.StopPrice; }
                        else { if (bar.Open <= o.StopPrice) { px = bar.Open; atOpen = true; } else if (bar.Low <= o.StopPrice) px = o.StopPrice; }
                        break;
                }
                if (double.IsNaN(px)) continue;
                DateTime t = atOpen ? bar.Time.AddMinutes(-1).AddSeconds(1) : bar.Time.AddSeconds(-30);
                int q = o.Quantity - o.Filled;
                SimWorking.Remove(o);
                o.Filled = o.Quantity;
                o.AverageFillPrice = px;
                o.SimFillBar = barIndex;
                SetState(o, OrderState.Filled, t, ErrorCode.NoError, "");
                Execution ex = new Execution { Order = o, Price = px, Quantity = q, Time = t, ExecutionId = (++execId).ToString(CultureInfo.InvariantCulture) };
                OnExecutionUpdate(ex, ex.ExecutionId, px, q, buy ? MarketPosition.Long : MarketPosition.Short, o.OrderId, t);
            }
        }

        // --- Pilotage par le simulateur -------------------------------------------
        internal void SimSetState(State s) { State = s; OnStateChange(); }

        internal void SimBind(Bars[] bars)
        {
            BarsArray = bars;
            int n = bars.Length;
            CurrentBars = Enumerable.Repeat(-1, n).ToArray();
            Times = new NinjaScript.SeriesView<DateTime>[n];
            Opens = new NinjaScript.SeriesView<double>[n]; Highs = new NinjaScript.SeriesView<double>[n]; Lows = new NinjaScript.SeriesView<double>[n];
            Closes = new NinjaScript.SeriesView<double>[n]; Volumes = new NinjaScript.SeriesView<double>[n];
            for (int k = 0; k < n; k++)
            {
                int kk = k;
                IList<SimBar> d = bars[k].Data;
                Times[k] = new NinjaScript.SeriesView<DateTime>(a => d[CurrentBars[kk] - a].Time);
                Opens[k] = new NinjaScript.SeriesView<double>(a => d[CurrentBars[kk] - a].Open);
                Highs[k] = new NinjaScript.SeriesView<double>(a => d[CurrentBars[kk] - a].High);
                Lows[k] = new NinjaScript.SeriesView<double>(a => d[CurrentBars[kk] - a].Low);
                Closes[k] = new NinjaScript.SeriesView<double>(a => d[CurrentBars[kk] - a].Close);
                Volumes[k] = new NinjaScript.SeriesView<double>(a => d[CurrentBars[kk] - a].Volume);
            }
        }

        internal void SimRunHistorical()
        {
            int n = BarsArray.Length;
            int[] next = new int[n];
            while (true)
            {
                DateTime tMin = DateTime.MaxValue;
                for (int k = 0; k < n; k++)
                    if (next[k] < BarsArray[k].Count && BarsArray[k].Data[next[k]].Time < tMin) tMin = BarsArray[k].Data[next[k]].Time;
                if (tMin == DateTime.MaxValue) break;
                for (int k = 0; k < n; k++)
                {
                    if (next[k] >= BarsArray[k].Count || BarsArray[k].Data[next[k]].Time != tMin) continue;
                    int i = next[k]++;
                    BarsInProgress = k;
                    ProcessFills(k, BarsArray[k].Data[i], i);
                    CurrentBars[k] = i;
                    BarsInProgress = k;
                    OnBarUpdate();
                }
            }
        }
    }
}

namespace NexusSim
{
    using NinjaTrader.NinjaScript.Strategies;

    public class SimInstrument
    {
        public string Name = "";
        public double PointValue = 1.0;
        public double TickSize = 0.01;
        public InstrumentType Type = InstrumentType.Stock;
        public IList<SimBar> Bars = new List<SimBar>();
        public TimeSpan SessionEnd = new TimeSpan(16, 15, 0);
    }

    public class SimMarket
    {
        public readonly Dictionary<string, SimInstrument> Instruments = new Dictionary<string, SimInstrument>(StringComparer.OrdinalIgnoreCase);
        public void Add(SimInstrument i) { Instruments[i.Name] = i; }
    }

    public static class SimRunner
    {
        /// <summary>Execute une strategie en historique : SetDefaults -> configuration -> Configure -> DataLoaded -> Historical -> Terminated.</summary>
        public static T Run<T>(T strategy, SimMarket market, string primary, Action<T> configure, Action<string> print) where T : Strategy
        {
            Instrument.Resolver = name =>
            {
                SimInstrument si;
                if (name == null || !market.Instruments.TryGetValue(name.Trim(), out si)) return null;
                return new Instrument
                {
                    FullName = si.Name,
                    MasterInstrument = new MasterInstrument { Name = si.Name, PointValue = si.PointValue, TickSize = si.TickSize, InstrumentType = si.Type, Currency = Currency.UsDollar }
                };
            };
            strategy.SimPrint = print;
            strategy.SimSetState(State.SetDefaults);
            if (configure != null) configure(strategy);
            strategy.SimSetState(State.Configure);
            List<Bars> bars = new List<Bars> { MakeBars(market, primary, new BarsPeriod { BarsPeriodType = BarsPeriodType.Minute, Value = 1 }, null) };
            for (int k = 0; k < strategy.SimRequests.Count; k++)
                bars.Add(MakeBars(market, strategy.SimRequests[k].Key, strategy.SimRequests[k].Value, strategy.SimTradingHours[k]));
            strategy.SimBind(bars.ToArray());
            strategy.SimSetState(State.DataLoaded);
            strategy.SimSetState(State.Historical);
            strategy.SimRunHistorical();
            strategy.SimSetState(State.Terminated);
            return strategy;
        }

        private static Bars MakeBars(SimMarket market, string name, BarsPeriod period, string tradingHours)
        {
            SimInstrument si = market.Instruments[name.Trim()];
            return new Bars
            {
                Instrument = Instrument.GetInstrument(name, false),
                BarsPeriod = period,
                TradingHours = new TradingHours { Name = tradingHours ?? "defaut", SessionEnd = si.SessionEnd },
                Data = si.Bars
            };
        }
    }
}
