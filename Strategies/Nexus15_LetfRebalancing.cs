// =============================================================================
//  Nexus15_LetfRebalancing.cs   (NinjaTrader 8 / NinjaScript)
//
//  FICHE 15 - Strategie LETF Rebalancing : NQ/ES en fin de session
//  [SSRN 3925725] Barbon, Beckmeyer, Buraschi, Moerke, "Liquidity Provision to
//  Leveraged ETFs and Equity Options Rebalancing Flows".
//
//  MECANISME : un LETF de levier L doit chaque soir ramener son exposition a
//  L x son actif net : il achete apres une hausse et vend apres une baisse,
//  quel que soit le signe de L (flux F = A L(L-1) r / (1 + L r)). Les dealers
//  d options courts gamma couvrent dans le meme sens et amplifient l impact.
//  Contreparties perdantes : les LETF (mandat strict) et les dealers courts gamma.
//
//  SIGNAL (15:25 ET, heure de New York quel que soit le fuseau NinjaTrader)
//   1. F_i = A_i L_i(L_i-1) r_t / (1 + L_i r_t) ; A_i = parts x NAV de la veille ;
//      r_t = rendement NDX (ou SPX) de la cloture J-1 a 15:25.
//   2. F_NQ = somme des fonds Nasdaq-100 (TQQQ, SQQQ, QLD, QID) ; F_ES = fonds
//      S&P 500 (UPRO, SPXU, SPXL, SPXS, SSO, SDS).
//   3. N = F / (multiplicateur x niveau de l indice) : 20 $/pt NQ, 50 $/pt ES.
//   4. S_t = N / V, V = volume moyen du future sur 15:30-16:00 des 20 dernieres
//      seances.
//   5. Creations/rachats nets du jour : ajoutes (L x C) s ils sont connus ;
//      sinon tendance des parts sur 5 j en variable de controle (recherche).
//   6. G_t = GEX agrege des dealers (SPX, NDX, QQQ), $ par 1 % ; Score_t =
//      S_t x w(G_t), w = 1 si G < 0 (court gamma), 0.3 si G > 0 (a calibrer).
//
//  REGLES : une position par jour au maximum, dans le sens de r_t, fermee au
//  close. Entree 15:30 ET (limite au mid, ou marche si spread <= 1 tick) ;
//  seuil |Score| >= q70 glissant sur 250 seances ; |r_t| >= 0.5 % ; taille
//  proportionnelle a |Score|, divisee par la vol realisee 30 min annualisee
//  (cible de risque fixe), plafonnee a 2 % du volume attendu sur la fenetre
//  (plafond / 2 si |r| > 3 %) ; stop 1.5 x ATR 30 min ; sortie 16:00 ET (au
//  marche = MOC, ou TWAP 15:55-16:00), jamais de portage overnight ; NQ en
//  priorite, ES seulement si son propre score passe le seuil.
//  JOURS EXCLUS : FOMC, CPI, NFP, demi-seances, quatre sorcieres, rebalancement
//  du Nasdaq-100 (regles + Nexus\data\letf_excluded_days.csv + macro_events.csv).
//
//  PROTOCOLE DE BACKTEST (rapport de fin de run, AddOns\NexusLetf.cs) :
//  regression r(15:30->16:00) = a + b1 r(ouv->15:30) + b2 S + b3 S.1[G<0] + g'X
//  (Newey-West) ; tests d identification : AUM, NQ vs ES, placebo 14:30-15:00,
//  placebo de levier, reversal ; IS 2012-2020 / OOS 2021+, walk-forward 3 ans ;
//  couts 1 tick A/R + commissions, stress 2 ticks ; criteres d acceptation.
//  Le panel quotidien est ecrit dans Nexus\reports (*_panel_*.csv).
//
//  DONNEES (Nexus\data) : letf_aum.csv (date, fund, shares_outstanding, nav
//  [, net_flow_usd]) ; gex.csv (date, gex [, gex_ref, underlying]) ;
//  letf_excluded_days.csv (date, reason). Series : futures 1 min (modele
//  d horaires RTH par defaut) + indices ^NDX / ^SP500 1 min (le future contient
//  le basis, l indice non ; a defaut, le future est utilise avec un avertissement).
//
//  CHOIX D INTERPRETATION (voir LISEZMOI) : formule du flux de la fiche par
//  defaut (option NavVeilleExacte = Cheng-Madhavan) ; taille = capital x cible
//  de risque / (prix x $/pt x vol 30 min annualisee x racine(30/98280)) x
//  |Score| / seuil ; en backtest l entree est au marche (pas de carnet) ;
//  ES en secours d un NQ non retenu (une position par jour).
// =============================================================================

#region Using declarations
using System;
using System.Collections.Generic;
using System.ComponentModel;
using System.ComponentModel.DataAnnotations;
using System.Globalization;
using System.IO;
using System.Linq;
using System.Text;
using System.Xml.Serialization;
using NinjaTrader.Cbi;
using NinjaTrader.Data;
using NinjaTrader.NinjaScript;
using NinjaTrader.NinjaScript.AddOns.Nexus;
#endregion

namespace NinjaTrader.NinjaScript.Strategies
{
    public enum Nexus15Entry { LimiteMidOuMarche, Marche }
    public enum Nexus15Exit { MarcheA16h, Twap1555_1600 }
    public enum Nexus15PrimaryFlows { Auto, Ignorer }

    public class Nexus15LetfRebalancing : NexusStrategyBase
    {
        private class SeriesState
        {
            public NxSym Sym;
            public NxMinuteDay Today;
            public NxMinuteDay Previous;
            public double PrevClose = double.NaN;     // cloture (<= 16:00 ET) de la seance precedente
        }

        private class DaySummary
        {
            public DateTime Date;
            public double WindowVolume, PlaceboVolume, DayVolume;
            public int WindowBars, PlaceboBars;
        }

        private class Leg
        {
            public NxSym Fut;
            public string Index = "";
            public int Priority;
            public SeriesState F, I;
            public bool IndexIsFuture;
            public readonly List<DaySummary> Past = new List<DaySummary>();
            public NxBarAggregator Bars30;
            public NxRollingQuantile Scores;
            // --- seance en cours
            public DateTime Day = DateTime.MinValue;
            public bool SignalDone, Planned, EntryDone, ExitDone;
            public NxLetfSignal Signal;
            public NxLetfExclusion Excl;
            public double Threshold = double.NaN, PrevCloseUsed = double.NaN, Gex = double.NaN, GexRef = double.NaN;
            public string Decision = "";
            public NxLetfPanelRow Row;
            public NxLetfPanelRow LastRow;           // ligne du dernier signal (non remise a zero au changement de jour)
            public int TwapBase, TwapStep;
            public double EntryScoreRatio = double.NaN;
            // --- reversal
            public NxLetfPanelRow PrevRow;
            public double PrevRowClose = double.NaN;
            public DateTime LastFinalized = DateTime.MinValue;
        }

        private readonly Dictionary<NxSym, SeriesState> states = new Dictionary<NxSym, SeriesState>();
        private readonly Dictionary<NxSym, Leg> legByFut = new Dictionary<NxSym, Leg>();
        private readonly List<Leg> legs = new List<Leg>();
        private readonly List<NxLetfPanelRow> panel = new List<NxLetfPanelRow>();
        private readonly List<NxLetfTradeOutcome> outcomes = new List<NxLetfTradeOutcome>();
        private readonly List<string> decisionLog = new List<string>();
        private readonly Dictionary<string, int> counters = new Dictionary<string, int>();
        private List<NxLetfFund> funds = new List<NxLetfFund>();
        private NxLetfAumStore aum;
        private NxGexStore gexStore;
        private NxLetfExclusionCalendar excl;
        private TimeZoneInfo ntZone, eastern;
        private TimeSpan tSignal, tEntry, tExit, tTwap, tPlaceboSignal, tPlaceboStart, tPlaceboEnd, keepFrom, keepTo;
        private readonly TimeSpan tRthOpen = new TimeSpan(9, 30, 0), tMorning = new TimeSpan(10, 30, 0), tRthClose = new TimeSpan(16, 0, 0);
        private DateTime decisionDay = DateTime.MinValue;
        private bool finalized;
        private NxLetfResearchResult research;

        // =====================================================================
        //  Acces en lecture (diagnostic, tests hors NinjaTrader)
        // =====================================================================
        [Browsable(false)] [XmlIgnore] public List<NxLetfPanelRow> LetfPanel { get { return panel; } }
        [Browsable(false)] [XmlIgnore] public List<NxLetfTradeOutcome> LetfTradeOutcomes { get { return outcomes; } }
        [Browsable(false)] [XmlIgnore] public List<string> LetfDecisionLog { get { return decisionLog; } }
        [Browsable(false)] [XmlIgnore] public NxLetfResearchResult LetfResearch { get { return research; } }
        [Browsable(false)] [XmlIgnore] public Dictionary<string, int> LetfCounters { get { return counters; } }

        protected override void NxSetDefaults()
        {
            Name = "Nexus15_LetfRebalancing";
            Description = "Fiche 15 - Rebalancement des ETF a levier : NQ (ES en secours) dans le sens du rendement du jour de 15:30 a 16:00 ET quand le flux LETF estime est grand devant la liquidite (q70) et que les dealers sont courts gamma ; sortie au close, jamais de portage.";
            Symbols = "NQ 12-26,ES 12-26";
            AllowShortSelling = true;
            SizingMode = NxSizingMode.Natif;
            MaxTradePct = 0; MaxSymbolPct = 0; MaxClassPct = 0; MaxTotalPct = 0;
            UseCorrelationDivisor = false;
            SlippagePct = 0.0; OtherFeePct = 0.0; PerContractFee = 0.0;
            InitialBankroll = 500000;
            StopMode = NxStopMode.OrdreNatif;

            RootToIndex = "NQ=NDX;MNQ=NDX;ES=SPX;MES=SPX";
            IndexInstruments = "NDX=^NDX;SPX=^SP500";
            FuturesTradingHours = "CME US Index Futures RTH";
            Funds = NxLetfFlow.DefaultFunds;
            AumFile = "letf_aum.csv";
            GexFile = "gex.csv";
            ExcludedDaysFile = "letf_excluded_days.csv";
            MacroFile = "macro_events.csv";
            FlowFormula = NxLetfFlowFormula.Fiche;
            PrimaryFlows = Nexus15PrimaryFlows.Auto;
            AumMaxStaleDays = 7;
            SignalTime = "15:25";
            EntryTime = "15:30";
            ExitTime = "16:00";
            TwapStartTime = "15:55";
            EntryToleranceMinutes = 5;
            VolumeLookbackDays = 20;
            UseGammaFilter = true;
            GammaShortWeight = 1.0;
            GammaLongWeight = 0.3;
            GammaUnknown = NxLetfGammaUnknown.PoidsUn;
            GexMaxStaleDays = 5;
            ThresholdQuantilePct = 70.0;
            ThresholdWindow = 250;
            MinThresholdHistory = 250;
            MinAbsReturnPct = 0.5;
            RiskTargetPct = 0.5;
            RvMinutes = 30;
            VolumeCapPct = 2.0;
            ExtremeMovePct = 3.0;
            MaxLeverage = 0.0;
            AtrMultiplier = 1.5;
            AtrBarMinutes = 30;
            AtrPeriod = 14;
            EntryMode = Nexus15Entry.LimiteMidOuMarche;
            LimitValidMinutes = 5;
            ExitMode = Nexus15Exit.MarcheA16h;
            InstrumentRule = NxLetfInstrumentRule.PrioritaireEtSecours;
            ExcludeMacroDays = true;
            ExcludeHalfDays = true;
            ExcludeQuadWitching = true;
            ExcludeNdxRebalance = true;
            ExcludeOtherDays = true;
            CostTicksRoundTrip = 1.0;
            StressTicksRoundTrip = 2.0;
            CommissionPerSide = 2.5;
            OosStart = "2021-01-01";
            WalkForwardYears = 3;
            NeweyWestLags = -1;
            PlaceboSignalTime = "14:25";
            PlaceboStartTime = "14:30";
            PlaceboEndTime = "15:00";
            LeveragePlaceboConstant = 1.0;
            WritePanel = true;
        }

        protected override bool NxBatchMode { get { return false; } }
        protected override BarsPeriodType NxUniverseBarsType { get { return BarsPeriodType.Minute; } }
        protected override int NxUniverseBarsValue { get { return 1; } }

        private static string RootOf(string instrument)
        {
            string s = (instrument ?? "").Trim();
            int k = s.IndexOf(' ');
            return (k > 0 ? s.Substring(0, k) : s).ToUpperInvariant();
        }

        private Dictionary<string, string> RootMap { get { return NxText.ParseMap(RootToIndex); } }
        private Dictionary<string, string> IndexMap { get { return NxText.ParseMap(IndexInstruments); } }

        protected override IEnumerable<string> NxRequiredReferences()
        {
            Dictionary<string, string> roots = RootMap, idx = IndexMap;
            List<string> refs = new List<string>();
            foreach (string sym in NxText.SplitList(Symbols))
            {
                string index, ins;
                if (roots.TryGetValue(RootOf(sym), out index) && idx.TryGetValue(index, out ins) && !string.IsNullOrWhiteSpace(ins)) refs.Add(ins.Trim());
            }
            return refs.Distinct(StringComparer.OrdinalIgnoreCase);
        }

        protected override string NxUniverseTradingHours(string instrumentName)
        {
            bool traded = NxText.SplitList(Symbols).Any(x => string.Equals(x, instrumentName, StringComparison.OrdinalIgnoreCase));
            return traded && !string.IsNullOrWhiteSpace(FuturesTradingHours) ? FuturesTradingHours : null;
        }

        /// <summary>Couts de la fiche : CostTicksRoundTrip / 2 ticks + commission, par contrat et par cote.</summary>
        protected override double NxExtraFillCost(NxSym s, int absQty, double price)
        {
            return absQty * (CostTicksRoundTrip / 2.0 * s.TickSize * ValuePerPoint(s) + CommissionPerSide);
        }

        // =====================================================================
        //  Initialisation
        // =====================================================================
        protected override void NxDataLoaded()
        {
            ntZone = NxTime.NtZone();
            eastern = NxTime.Eastern;
            tSignal = NxTime.ParseHhmm(SignalTime, new TimeSpan(15, 25, 0));
            tEntry = NxTime.ParseHhmm(EntryTime, new TimeSpan(15, 30, 0));
            tExit = NxTime.ParseHhmm(ExitTime, new TimeSpan(16, 0, 0));
            tTwap = NxTime.ParseHhmm(TwapStartTime, new TimeSpan(15, 55, 0));
            tPlaceboSignal = NxTime.ParseHhmm(PlaceboSignalTime, new TimeSpan(14, 25, 0));
            tPlaceboStart = NxTime.ParseHhmm(PlaceboStartTime, new TimeSpan(14, 30, 0));
            tPlaceboEnd = NxTime.ParseHhmm(PlaceboEndTime, new TimeSpan(15, 0, 0));
            keepFrom = tRthOpen.Add(TimeSpan.FromMinutes(-30));
            keepTo = (tExit > tRthClose ? tExit : tRthClose).Add(TimeSpan.FromMinutes(15));
            if (!(tSignal < tEntry && tEntry < tExit && tTwap > tEntry && tTwap < tExit))
                Nx("ATTENTION : heures incoherentes (signal < entree < TWAP < sortie attendu).");

            funds = NxLetfFlow.ParseFunds(Funds);
            string msg;
            aum = new NxLetfAumStore();
            aum.Load(NxPaths.Resolve(AumFile, NxPaths.Data), out msg);
            Nx("Actif net LETF : " + msg);
            gexStore = new NxGexStore();
            gexStore.Load(NxPaths.Resolve(GexFile, NxPaths.Data), out msg);
            Nx("GEX : " + msg + (gexStore.Loaded ? "" : (UseGammaFilter ? " -> regime inconnu chaque jour (" + GammaUnknown + ")" : "")));
            excl = new NxLetfExclusionCalendar
            {
                UseMacro = ExcludeMacroDays, UseHalfDays = ExcludeHalfDays, UseQuadWitching = ExcludeQuadWitching,
                UseNdxRebalance = ExcludeNdxRebalance, UseOther = ExcludeOtherDays
            };
            excl.LoadExclusionFile(NxPaths.Resolve(ExcludedDaysFile, NxPaths.Data), out msg);
            Nx("Jours exclus : " + msg);
            if (!string.IsNullOrWhiteSpace(MacroFile))
            {
                excl.LoadMacroFile(NxPaths.Resolve(MacroFile, NxPaths.Data), eastern, out msg);
                Nx("Agenda macro : " + msg);
            }
            if (ExcludeMacroDays && excl.MacroDays == 0)
                Nx("ATTENTION : aucun jour FOMC/CPI/NFP connu -> exclusion macro INACTIVE (remplir " + ExcludedDaysFile + " ou " + MacroFile + ").");

            Dictionary<string, string> roots = RootMap, idx = IndexMap;
            int prio = 0;
            foreach (NxSym s in Syms) states[s] = new SeriesState { Sym = s };
            foreach (NxSym s in TradedSyms)
            {
                string index;
                if (!roots.TryGetValue(RootOf(s.Name), out index)) { Nx("ATTENTION : racine " + RootOf(s.Name) + " absente de 'Racine -> indice' : " + s.Name + " ignore."); continue; }
                index = index.Trim().ToUpperInvariant();
                string insName;
                NxSym isym = idx.TryGetValue(index, out insName) ? Sym(insName) : null;
                Leg leg = new Leg
                {
                    Fut = s, Index = index, Priority = prio++, F = states[s], I = isym != null ? states[isym] : states[s], IndexIsFuture = isym == null,
                    Bars30 = new NxBarAggregator(s.Name + "_" + AtrBarMinutes + "m", AtrBarMinutes, AtrPeriod, tRthOpen, tRthClose),
                    Scores = new NxRollingQuantile(ThresholdWindow)
                };
                if (leg.IndexIsFuture) Nx("ATTENTION : indice " + index + " introuvable (" + insName + ") -> r_t calcule sur " + s.Name + " (contient le basis).");
                int nf = funds.Count(f => f.Index == index);
                if (nf == 0) Nx("ATTENTION : aucun fonds LETF declare pour l indice " + index + ".");
                legs.Add(leg);
                legByFut[s] = leg;
            }
            Nx(string.Format(CultureInfo.InvariantCulture, "Fiche 15 : {0} instrument(s) [{1}], {2} fonds LETF, fuseau NinjaTrader '{3}' -> heure de New York ; signal {4:hh\\:mm}, entree {5:hh\\:mm}, sortie {6:hh\\:mm} ({7}).",
                legs.Count, string.Join(", ", legs.Select(l => l.Fut.Name + "/" + l.Index)), funds.Count, ntZone.Id, tSignal, tEntry, tExit, ExitMode));
        }

        // =====================================================================
        //  Horloge (heure de New York)
        // =====================================================================
        private DateTime ToEt(DateTime nt) { return NxTime.FromUtc(NxTime.ToUtc(nt, ntZone), eastern); }

        private static NxMinuteDay DayOf(SeriesState st, DateTime d)
        {
            if (st == null) return null;
            if (st.Today != null && st.Today.Date == d.Date) return st.Today;
            if (st.Previous != null && st.Previous.Date == d.Date) return st.Previous;
            return null;
        }

        private void Bump(string key) { int n; counters.TryGetValue(key, out n); counters[key] = n + 1; }

        private void Note(DateTime d, string msg)
        {
            string line = d.ToString("yyyy-MM-dd", CultureInfo.InvariantCulture) + " " + msg;
            decisionLog.Add(line);
            NxV(line);
        }

        protected override void NxOnSymbolBar(NxSym s, DateTime day)
        {
            SeriesState st;
            if (!states.TryGetValue(s, out st)) return;
            int bip = s.Bip;
            DateTime et = ToEt(Times[bip][0]);
            DateTime d = et.Date;
            TimeSpan tod = et.TimeOfDay;
            if (st.Today == null || st.Today.Date != d) RollSeries(st, d);
            if (tod >= keepFrom && tod <= keepTo) st.Today.Add(tod, Opens[bip][0], Highs[bip][0], Lows[bip][0], Closes[bip][0], Volumes[bip][0]);
            Leg own;
            legByFut.TryGetValue(s, out own);
            if (own != null) own.Bars30.Add(d, tod, Opens[bip][0], Highs[bip][0], Lows[bip][0], Closes[bip][0], Volumes[bip][0]);
            Clock(s, own, d, tod);
        }

        private void RollSeries(SeriesState st, DateTime d)
        {
            if (st.Today != null && st.Today.Count > 0)
            {
                double c = st.Today.PriceAsOf(tRthClose);
                if (NxMath.Ok(c)) st.PrevClose = c;
                st.Previous = st.Today;
                Leg leg;
                if (legByFut.TryGetValue(st.Sym, out leg)) FinalizeLegDay(leg, st.Today);
            }
            st.Today = new NxMinuteDay(d);
        }

        private void Clock(NxSym src, Leg own, DateTime d, TimeSpan tod)
        {
            foreach (Leg leg in legs)
            {
                if (leg.Day != d) StartLegDay(leg, d);
                if (!leg.SignalDone && (tod > tSignal || (tod == tSignal && src == leg.I.Sym))) ComputeSignal(leg, d);
            }
            if (own != null && decisionDay != d && tod >= tEntry && legs.All(l => l.SignalDone)) DecideDay(d);
            if (own == null) return;
            if (own.Planned && !own.EntryDone && tod >= tEntry) SubmitEntry(own, d, tod);
            ManageExit(own, tod);
        }

        private void StartLegDay(Leg leg, DateTime d)
        {
            if (leg.Fut.Qty != 0 || IsActive(leg.Fut.EntryOrder))
            {
                Bump("garde_overnight");
                NxAlert(string.Format(CultureInfo.InvariantCulture, "{0} : position {1} encore ouverte au debut de la seance {2:yyyy-MM-dd} -> sortie immediate (jamais de portage overnight)", leg.Fut.Name, leg.Fut.Qty, d));
                SetTarget(leg.Fut, 0, double.NaN, "garde : jamais de portage overnight");
            }
            leg.Day = d;
            leg.SignalDone = leg.Planned = leg.EntryDone = leg.ExitDone = false;
            leg.Signal = null; leg.Row = null; leg.Excl = NxLetfExclusion.Aucune; leg.Decision = "";
            leg.Threshold = leg.PrevCloseUsed = leg.Gex = leg.GexRef = leg.EntryScoreRatio = double.NaN;
            leg.TwapBase = leg.TwapStep = 0;
        }

        // =====================================================================
        //  Signal 15:25
        // =====================================================================
        private double AvgPast(Leg leg, Func<DaySummary, double> value, Func<DaySummary, bool> valid)
        {
            List<double> v = new List<double>();
            for (int i = leg.Past.Count - 1; i >= 0 && v.Count < VolumeLookbackDays; i--)
                if (valid(leg.Past[i])) v.Add(value(leg.Past[i]));
            return v.Count >= VolumeLookbackDays ? v.Average() : double.NaN;
        }

        private double AvgWindowVolume(Leg leg, bool placebo)
        {
            int minMain = (int)Math.Floor(0.8 * (tExit - tEntry).TotalMinutes), minPlc = (int)Math.Floor(0.8 * (tPlaceboEnd - tPlaceboStart).TotalMinutes);
            return placebo ? AvgPast(leg, x => x.PlaceboVolume, x => x.PlaceboBars >= minPlc && x.PlaceboVolume > 0)
                           : AvgPast(leg, x => x.WindowVolume, x => x.WindowBars >= minMain && x.WindowVolume > 0);
        }

        private NxLetfSignalInput BuildInput(Leg leg, DateTime d, double prevClose, double level, double avgVolume, double g)
        {
            return new NxLetfSignalInput
            {
                Day = d, Index = leg.Index, PrevClose = prevClose, LevelAtSignal = level, Multiplier = ValuePerPoint(leg.Fut), AvgWindowVolume = avgVolume, Gex = g,
                Funds = funds, Aum = aum, Formula = FlowFormula, PrimaryFlowCorrection = PrimaryFlows == Nexus15PrimaryFlows.Auto, AumMaxStaleDays = AumMaxStaleDays,
                UseGammaFilter = UseGammaFilter, WeightShortGamma = GammaShortWeight, WeightLongGamma = GammaLongWeight, GammaUnknown = GammaUnknown,
                PlaceboFactor = LeveragePlaceboConstant
            };
        }

        private void ComputeSignal(Leg leg, DateTime d)
        {
            leg.SignalDone = true;
            NxMinuteDay idx = DayOf(leg.I, d);
            double level = idx != null ? idx.PriceAsOf(tSignal) : double.NaN;
            double prev = idx != null && idx == leg.I.Today ? leg.I.PrevClose : double.NaN;
            double vbar = AvgWindowVolume(leg, false);
            double g, gRef;
            if (!gexStore.TryGet(d, GexMaxStaleDays, out g, out gRef)) { g = double.NaN; gRef = double.NaN; }
            NxLetfSignal sig = NxLetfSignal.Compute(BuildInput(leg, d, prev, level, vbar, g));
            leg.Signal = sig;
            leg.PrevCloseUsed = prev;
            leg.Gex = g; leg.GexRef = gRef;
            leg.Excl = excl.Check(d);
            leg.Threshold = leg.Scores.Count >= MinThresholdHistory ? leg.Scores.Quantile(ThresholdQuantilePct / 100.0) : double.NaN;
            if (sig.Ok) leg.Scores.Add(Math.Abs(sig.Score));
            NxLetfPanelRow row = new NxLetfPanelRow
            {
                Date = d, Instrument = leg.Fut.Name, Index = leg.Index, Priority = leg.Priority, Excluded = leg.Excl,
                R = sig.R, S = sig.S, SConst = sig.SConst, M = sig.M, SharesTrend = sig.SharesTrend, G = g, GRef = gRef, W = sig.Weight, Score = sig.Score,
                Threshold = leg.Threshold, TopFund = sig.TopFund, TopFundShare = sig.TopFundShare, IndexLevel = level,
                PointValue = ValuePerPoint(leg.Fut), TickSize = leg.Fut.TickSize, AvgWindowVolume = vbar,
                Dow = (int)d.DayOfWeek, MonthEnd = NxUsMarketCalendar.IsLastTradingDayOfMonth(d),
                Opex = NxUsMarketCalendar.IsMonthlyOpex(d) && !NxUsMarketCalendar.IsQuadWitching(d)
            };
            leg.Row = row;
            leg.LastRow = row;
            panel.Add(row);
            Bump(sig.Ok ? "signaux" : "signaux_incalculables");
            string txt = sig.Ok
                ? string.Format(CultureInfo.InvariantCulture, "{0} signal {1:hh\\:mm} : r {2:P2}, flux {3:F0} M$ (rebal. {4:F0}, primaire {5:F0}), N {6:F0} ctr, V {7:F0}, S {8:F4}, G {9}, w {10:F2}, Score {11:F4}, seuil q{12:F0} {13}{14}",
                    leg.Fut.Name, tSignal, sig.R, sig.FlowUsd / 1e6, sig.RebalanceFlowUsd / 1e6, sig.PrimaryFlowUsd / 1e6, sig.Contracts, vbar, sig.S,
                    NxMath.Ok(g) ? (g / 1e9).ToString("F2", CultureInfo.InvariantCulture) + " Md$" : "inconnu", sig.Weight, sig.Score, ThresholdQuantilePct,
                    NxMath.Ok(leg.Threshold) ? leg.Threshold.ToString("F4", CultureInfo.InvariantCulture) : "(chauffage " + leg.Scores.Count + "/" + MinThresholdHistory + ")",
                    leg.Excl != NxLetfExclusion.Aucune ? " | jour exclu : " + NxLetfExclusionCalendar.Describe(leg.Excl) : "")
                : leg.Fut.Name + " signal incalculable : " + sig.Why;
            Note(d, txt);
            NxSignal(NowNt, leg.Fut.Name, "letf_signal", txt);
        }

        // =====================================================================
        //  Decision 15:30 : seuil, filtres, regle d instrument (une position par jour)
        // =====================================================================
        private bool Passes(Leg leg, out string why, out string key)
        {
            NxLetfSignal s = leg.Signal;
            if (s == null || !s.Ok) { why = "pas de signal (" + (s != null ? s.Why : "donnees absentes a " + tSignal.ToString(@"hh\:mm") + ")") + ")"; key = "rejet_signal"; return false; }
            if (leg.Excl != NxLetfExclusion.Aucune) { why = "jour exclu : " + NxLetfExclusionCalendar.Describe(leg.Excl); key = "rejet_jour_exclu"; return false; }
            if (Math.Abs(s.R) < MinAbsReturnPct / 100.0)
            {
                why = string.Format(CultureInfo.InvariantCulture, "filtre de rendement |r| {0:P2} < {1:F2} %", Math.Abs(s.R), MinAbsReturnPct);
                key = "rejet_rendement"; return false;
            }
            if (!NxMath.Ok(leg.Threshold) || !(leg.Threshold > 0))
            {
                why = "chauffage du seuil (" + Math.Max(0, leg.Scores.Count - 1) + "/" + MinThresholdHistory + " seances)";
                key = "rejet_chauffage"; return false;
            }
            if (Math.Abs(s.Score) < leg.Threshold)
            {
                why = string.Format(CultureInfo.InvariantCulture, "|Score| {0:F4} < seuil q{1:F0} {2:F4}", Math.Abs(s.Score), ThresholdQuantilePct, leg.Threshold);
                key = "rejet_seuil"; return false;
            }
            if (!s.GammaAllowsTrade) { why = "GEX inconnu (regle PasDeTrade)"; key = "rejet_gex_inconnu"; return false; }
            why = string.Format(CultureInfo.InvariantCulture, "|Score| {0:F4} >= seuil {1:F4}, r {2:P2}, regime gamma {3}", Math.Abs(s.Score), leg.Threshold, s.R, s.Regime);
            key = "retenu";
            return true;
        }

        private void DecideDay(DateTime d)
        {
            decisionDay = d;
            bool first = true, firstPassed = false;
            Leg positioned = null;
            foreach (Leg leg in legs)
            {
                string why, key;
                bool pass = Passes(leg, out why, out key);
                bool take;
                if (InstrumentRule == NxLetfInstrumentRule.PrioritaireEtSecours) take = pass && positioned == null;
                else if (InstrumentRule == NxLetfInstrumentRule.PrioritaireSeulement) take = pass && first;
                else take = pass && (first || firstPassed);
                if (first) firstPassed = pass;
                first = false;
                if (take)
                {
                    leg.Planned = true;
                    if (positioned == null) positioned = leg;
                    leg.Decision = "retenu : " + why;
                }
                else if (pass)
                {
                    key = "non_retenu_regle_instrument";
                    leg.Decision = InstrumentRule == NxLetfInstrumentRule.PrioritaireEtSecours && positioned != null
                        ? "seuil passe mais non retenu : une position par jour (" + positioned.Fut.Name + ")"
                        : "seuil passe mais non retenu (regle " + InstrumentRule + ")";
                }
                else leg.Decision = why;
                Bump(key);
                if (leg.Row != null) leg.Row.Decision = leg.Decision;
                Note(d, leg.Fut.Name + " decision : " + leg.Decision);
            }
        }

        // =====================================================================
        //  Entree 15:30, sortie 16:00 (marche ou TWAP), stop ATR
        // =====================================================================
        private void SubmitEntry(Leg leg, DateTime d, TimeSpan tod)
        {
            leg.EntryDone = true;
            NxSym s = leg.Fut;
            if (tod > tEntry.Add(TimeSpan.FromMinutes(EntryToleranceMinutes)) || tod >= tExit)
            {
                leg.Decision += " ; entree abandonnee (premiere barre a " + tod.ToString(@"hh\:mm") + ")";
                Bump("entree_manquee");
                Note(d, s.Name + " " + leg.Decision);
                return;
            }
            double price = Closes[s.Bip][0];
            double rv = leg.F.Today.RealizedVolAnn(tEntry.Add(TimeSpan.FromMinutes(-RvMinutes)), tEntry, NxLetfFlow.RthMinutesPerYear, Math.Max(2, RvMinutes / 2));
            double atr = leg.Bars30.Hist.Atr;
            double absScore = Math.Abs(leg.Signal.Score), raw;
            int cap;
            string det;
            int q = NxLetfSizing.Contracts(absScore, leg.Threshold, price, ValuePerPoint(s), rv, (tExit - tEntry).TotalMinutes, Bankroll(), RiskTargetPct,
                                           leg.Row != null ? leg.Row.AvgWindowVolume : double.NaN, VolumeCapPct, Math.Abs(leg.Signal.R), ExtremeMovePct, out raw, out cap, out det);
            if (MaxLeverage > 0 && q > 0)
            {
                int qLev = (int)Math.Floor(MaxLeverage * Bankroll() / (price * ValuePerPoint(s)));
                if (qLev < q) { det += string.Format(CultureInfo.InvariantCulture, ", levier max {0:F1} -> {1}", MaxLeverage, qLev); q = qLev; }
            }
            if (!(atr > 0))
            {
                leg.Decision += " ; pas d entree : ATR " + AtrBarMinutes + " min indisponible (chauffage)";
                Bump("rejet_atr");
            }
            else if (q < 1)
            {
                leg.Decision += " ; pas d entree : taille < 1 contrat (" + det + ")";
                Bump("rejet_taille");
            }
            if (!(atr > 0) || q < 1)
            {
                if (leg.Row != null) leg.Row.Decision = leg.Decision;
                Note(d, s.Name + " " + leg.Decision);
                return;
            }
            int dir = Math.Sign(leg.Signal.R);
            double stop = RoundPrice(s, price - dir * AtrMultiplier * atr);
            OrderType kind = OrderType.Market;
            double lim = double.NaN;
            string how = "marche (backtest : pas de carnet)";
            if (IsRt && EntryMode == Nexus15Entry.LimiteMidOuMarche)
            {
                double bid = double.NaN, ask = double.NaN;
                try { bid = GetCurrentBid(s.Bip); ask = GetCurrentAsk(s.Bip); } catch { }
                if (bid > 0 && ask >= bid && ask - bid > s.TickSize * 1.0001)
                {
                    kind = OrderType.Limit;
                    lim = RoundPrice(s, 0.5 * (bid + ask));
                    how = string.Format(CultureInfo.InvariantCulture, "limite au mid {0} (spread {1:F0} ticks, valable {2} min)", lim, (ask - bid) / s.TickSize, LimitValidMinutes);
                }
                else how = "marche (spread <= 1 tick)";
            }
            else if (IsRt) how = "marche";
            string why = string.Format(CultureInfo.InvariantCulture, "LETF {0} {1} x{2} @~{3} stop {4} (ATR30 {5:F2} x {6}) ; {7} ; {8}",
                dir > 0 ? "achat" : "vente", s.Name, q, price, stop, atr, AtrMultiplier, how, det);
            s.Regime = leg.Signal.Regime.ToString();
            SetTarget(s, dir * q, stop, why, kind, lim, LimitValidMinutes);
            leg.EntryScoreRatio = absScore / leg.Threshold;
            leg.Decision += string.Format(CultureInfo.InvariantCulture, " ; {0} x{1} ({2})", dir > 0 ? "achat" : "vente", q, det);
            if (leg.Row != null) { leg.Row.Direction = dir; leg.Row.Qty = q; leg.Row.Decision = leg.Decision; }
            Bump("entrees");
            Note(d, s.Name + " entree : " + why);
            NxSignal(NowNt, s.Name, "letf_entree", why);
        }

        private void ManageExit(Leg leg, TimeSpan tod)
        {
            NxSym s = leg.Fut;
            if (s.Qty == 0 && s.TargetQty == 0 && !IsActive(s.EntryOrder)) return;
            if (ExitMode == Nexus15Exit.Twap1555_1600 && tod >= tTwap && tod < tExit)
            {
                int slices = Math.Max(1, (int)Math.Round((tExit - tTwap).TotalMinutes));
                int k = Math.Min(slices, (int)Math.Floor((tod - tTwap).TotalMinutes) + 1);
                if (k <= leg.TwapStep) return;
                if (leg.TwapStep == 0) leg.TwapBase = Math.Abs(s.Qty);
                leg.TwapStep = k;
                int remaining = Math.Min(Math.Abs(s.Qty), (int)Math.Round(leg.TwapBase * (slices - k) / (double)slices));
                SetTarget(s, Math.Sign(s.Qty) * remaining, remaining > 0 ? s.StopPrice : double.NaN,
                          string.Format(CultureInfo.InvariantCulture, "TWAP {0}/{1} ({2:hh\\:mm}-{3:hh\\:mm})", k, slices, tTwap, tExit));
                return;
            }
            if (tod < tExit) return;
            if (!leg.ExitDone)
            {
                leg.ExitDone = true;
                SetTarget(s, 0, double.NaN, "sortie au close " + tExit.ToString(@"hh\:mm") + " ET");
                return;
            }
            if (tod >= tExit.Add(TimeSpan.FromMinutes(5)) && (s.Qty != 0 || s.TargetQty != 0))
            {
                Bump("garde_sortie_forcee");
                SetTarget(s, 0, double.NaN, "garde : sortie forcee apres le close");
            }
        }

        protected override void NxOnStopped(NxSym s)
        {
            Leg leg;
            if (!legByFut.TryGetValue(s, out leg)) return;
            Bump("stops");
            Note(leg.Day, s.Name + " stop " + AtrMultiplier + " x ATR touche");
        }

        protected override void NxOnTradeClosed(NxSym s, NxTradeRecord r)
        {
            Leg leg;
            legByFut.TryGetValue(s, out leg);
            DateTime d = ToEt(r.EntryTime).Date;
            NxLetfTradeOutcome o = new NxLetfTradeOutcome
            {
                Day = d, Instrument = s.Name, Direction = r.Direction, Qty = r.MaxQty, GrossPnl = r.GrossPnl, NetPnl = r.NetPnl,
                ScoreRatio = leg != null && leg.Day == d ? leg.EntryScoreRatio : double.NaN, TickValue = s.TickSize * ValuePerPoint(s),
                Stopped = (r.ExitReason ?? "").IndexOf("stop", StringComparison.OrdinalIgnoreCase) >= 0
            };
            outcomes.Add(o);
            NxLetfPanelRow row = panel.LastOrDefault(x => x.Date == d && x.Instrument == s.Name);
            if (row != null)
            {
                row.Traded = true; row.Direction = r.Direction; row.Qty = r.MaxQty;
                row.GrossPnl = (NxMath.Ok(row.GrossPnl) ? row.GrossPnl : 0) + r.GrossPnl;
                row.NetPnl = (NxMath.Ok(row.NetPnl) ? row.NetPnl : 0) + r.NetPnl;
            }
            Note(d, string.Format(CultureInfo.InvariantCulture, "{0} trade ferme ({1}) : {2} x{3}, {4} -> {5}, net {6:F2} $", s.Name, r.ExitReason,
                r.Direction > 0 ? "long" : "court", r.MaxQty, r.EntryPrice, r.ExitPrice, r.NetPnl));
        }

        // =====================================================================
        //  Fin de seance : rendements de fenetre, placebo, reversal (panel)
        // =====================================================================
        private static double Ret(double a, double b) { return NxMath.Ok(a) && NxMath.Ok(b) && a > 0 ? b / a - 1.0 : double.NaN; }

        private void FinalizeLegDay(Leg leg, NxMinuteDay fd)
        {
            if (fd == null || fd.Count == 0 || fd.Date <= leg.LastFinalized) return;
            leg.LastFinalized = fd.Date;
            DateTime D = fd.Date;
            DaySummary sum = new DaySummary
            {
                Date = D, WindowVolume = fd.VolumeIn(tEntry, tExit), WindowBars = fd.CountIn(tEntry, tExit),
                PlaceboVolume = fd.VolumeIn(tPlaceboStart, tPlaceboEnd), PlaceboBars = fd.CountIn(tPlaceboStart, tPlaceboEnd),
                DayVolume = fd.VolumeIn(tRthOpen, tEntry)
            };
            double open = fd.OpenAfter(tRthOpen);
            // Ligne du signal de D : l ordre des series au changement de jour peut deja avoir reinitialise leg.Row.
            NxLetfPanelRow row = leg.LastRow != null && leg.LastRow.Date == D ? leg.LastRow : null;
            if (row != null)
            {
                double pEntry = fd.PriceAsOf(tEntry), pExit = fd.PriceAsOf(tExit), pPs = fd.PriceAsOf(tPlaceboStart), pPe = fd.PriceAsOf(tPlaceboEnd);
                row.FuturePrice = pEntry;
                row.Y = Ret(pEntry, pExit);
                row.ROpenEntry = Ret(open, pEntry);
                row.YPlacebo = Ret(pPs, pPe);
                row.ROpenPlacebo = Ret(open, pPs);
                row.RvEntry = fd.RealizedVolAnn(tEntry.Add(TimeSpan.FromMinutes(-RvMinutes)), tEntry, NxLetfFlow.RthMinutesPerYear, Math.Max(2, RvMinutes / 2));
                row.RvDay = fd.RealizedVolAnn(tRthOpen, tEntry, NxLetfFlow.RthMinutesPerYear, 30);
                double avgDay = AvgPast(leg, x => x.DayVolume, x => x.DayVolume > 0);
                row.LogVolumeRel = sum.DayVolume > 0 && avgDay > 0 ? Math.Log(sum.DayVolume / avgDay) : double.NaN;
                NxMinuteDay idx = DayOf(leg.I, D);
                double lvl = idx != null ? idx.PriceAsOf(tPlaceboSignal) : double.NaN;
                NxLetfSignal sp = NxLetfSignal.Compute(BuildInput(leg, D, leg.PrevCloseUsed, lvl, AvgWindowVolume(leg, true), row.G));
                row.RPlacebo = sp.R;
                row.SPlacebo = sp.S;
            }
            if (leg.PrevRow != null && NxMath.Ok(leg.PrevRowClose))
            {
                leg.PrevRow.ROvernight = Ret(leg.PrevRowClose, open);
                leg.PrevRow.RMorning = Ret(open, fd.PriceAsOf(tMorning));
            }
            leg.PrevRow = row;
            leg.PrevRowClose = fd.PriceAsOf(tExit);
            leg.Past.Add(sum);
            if (leg.Past.Count > 4 * VolumeLookbackDays + 20) leg.Past.RemoveRange(0, leg.Past.Count - (2 * VolumeLookbackDays + 20));
        }

        private void FinalizeAll()
        {
            if (finalized) return;
            finalized = true;
            foreach (Leg leg in legs) FinalizeLegDay(leg, leg.F.Today);
        }

        // =====================================================================
        //  Rapport
        // =====================================================================
        protected override void NxReportExtras(List<string> lines)
        {
            FinalizeAll();
            CultureInfo ci = CultureInfo.InvariantCulture;
            lines.Add(string.Format(ci, "Fiche 15 : formule du flux {0}, filtre gamma {1} (w court {2:F2}, long {3:F2}, inconnu {4}), seuil q{5:F0}/{6} seances, |r| >= {7:F2} %, regle {8}, sortie {9}",
                FlowFormula, UseGammaFilter ? "actif" : "inactif", GammaShortWeight, GammaLongWeight, GammaUnknown, ThresholdQuantilePct, ThresholdWindow, MinAbsReturnPct, InstrumentRule, ExitMode));
            lines.Add("Compteurs : " + string.Join(" | ", counters.OrderBy(kv => kv.Key).Select(kv => kv.Key + " " + kv.Value)));
            Dictionary<NxLetfExclusion, int> byExcl = new Dictionary<NxLetfExclusion, int>();
            foreach (NxLetfPanelRow r in panel.Where(x => x.Priority == 0 && x.Excluded != NxLetfExclusion.Aucune))
                foreach (NxLetfExclusion e in Enum.GetValues(typeof(NxLetfExclusion)).Cast<NxLetfExclusion>().Where(e => e != NxLetfExclusion.Aucune && (r.Excluded & e) != 0))
                {
                    int n; byExcl.TryGetValue(e, out n); byExcl[e] = n + 1;
                }
            lines.Add("Jours exclus (instrument principal) : " + (byExcl.Count == 0 ? "aucun" : string.Join(", ", byExcl.Select(kv => kv.Key + " " + kv.Value)))
                      + (excl.MacroDays == 0 && ExcludeMacroDays ? " - ATTENTION : aucun jour FOMC/CPI/NFP fourni" : ""));
            foreach (Leg leg in legs)
            {
                NxLetfPanelRow last = panel.LastOrDefault(x => x.Instrument == leg.Fut.Name && NxMath.Ok(x.M) && NxMath.Ok(x.IndexLevel));
                if (last == null) continue;
                double flow1 = last.M * last.AvgWindowVolume * last.PointValue * last.IndexLevel * 0.01;
                lines.Add(string.Format(ci, "Ordre de grandeur {0:yyyy-MM-dd} ({1}) : +1 % de l indice -> ~{2:F2} Md$ de flux LETF ~ {3:F0} contrats {4} ({5:P1} du volume moyen 15:30-16:00)",
                    last.Date, leg.Index, flow1 / 1e9, flow1 / (last.PointValue * last.IndexLevel), RootOf(leg.Fut.Name), last.M * 0.01));
            }
            DateTime oos;
            if (!NxCsv.TryParseDate(OosStart, out oos)) oos = new DateTime(2021, 1, 1);
            NxLetfResearchConfig cfg = new NxLetfResearchConfig
            {
                OosStart = oos.Date, WalkForwardYears = WalkForwardYears, NwLags = NeweyWestLags, ThresholdQuantile = ThresholdQuantilePct / 100.0,
                ThresholdWindow = ThresholdWindow, MinThresholdHistory = MinThresholdHistory, MinAbsR = MinAbsReturnPct / 100.0, UseGammaFilter = UseGammaFilter,
                WeightShortGamma = GammaShortWeight, WeightLongGamma = GammaLongWeight, GammaUnknown = GammaUnknown, CostTicksRoundTrip = CostTicksRoundTrip,
                StressTicksRoundTrip = StressTicksRoundTrip, CommissionPerSide = CommissionPerSide, InstrumentRule = InstrumentRule,
                HasNetFlows = aum.HasNetFlows && PrimaryFlows == Nexus15PrimaryFlows.Auto
            };
            research = NxLetfResearch.Analyze(panel, outcomes, EquityDays, DailyReturns, cfg, lines);
            if (WritePanel && !IsOptimizing && panel.Count > 0)
            {
                try
                {
                    string path = Path.Combine(NxPaths.Reports, NxPaths.SafeFileName(StrategyId) + "_panel_" + DateTime.Now.ToString("yyyyMMdd_HHmmss", ci) + ".csv");
                    StringBuilder sb = new StringBuilder();
                    sb.AppendLine(NxLetfPanelRow.CsvHeader);
                    foreach (NxLetfPanelRow r in panel) sb.AppendLine(r.ToCsv());
                    NxCsv.WriteAll(path, sb.ToString());
                    lines.Add("Panel quotidien (regressions hors NinjaTrader) : " + path);
                }
                catch (Exception ex) { lines.Add("Panel non ecrit : " + ex.Message); }
            }
        }

        #region Proprietes
        [Display(Name = "Racine -> indice", Description = "Racine du future -> cle d indice des fonds (NQ=NDX;ES=SPX).", Order = 1, GroupName = "01. Fiche 15 - Univers et donnees")]
        public string RootToIndex { get; set; }

        [Display(Name = "Indices (series 1 min)", Description = "Cle -> instrument NinjaTrader de l indice (r_t sans basis). Absent = future utilise.", Order = 2, GroupName = "01. Fiche 15 - Univers et donnees")]
        public string IndexInstruments { get; set; }

        [Display(Name = "Horaires des futures", Description = "Modele Trading Hours des futures (RTH : 2 a 3 fois moins de barres en memoire). Vide = modele de l instrument.", Order = 3, GroupName = "01. Fiche 15 - Univers et donnees")]
        public string FuturesTradingHours { get; set; }

        [Display(Name = "Fonds LETF (symbole=levier:indice)", Order = 4, GroupName = "01. Fiche 15 - Univers et donnees")]
        public string Funds { get; set; }

        [Display(Name = "Actif net LETF (CSV)", Description = "date, fund, shares_outstanding, nav [, aum, net_flow_usd] (Nexus\\data).", Order = 5, GroupName = "01. Fiche 15 - Univers et donnees")]
        public string AumFile { get; set; }

        [Display(Name = "GEX (CSV)", Description = "date, gex [, gex_ref, underlying] en $ par 1 % (Nexus\\data).", Order = 6, GroupName = "01. Fiche 15 - Univers et donnees")]
        public string GexFile { get; set; }

        [Display(Name = "Jours exclus (CSV)", Description = "date, reason : FOMC, CPI, NFP, NDX rebalance, demi-seance, autre (Nexus\\data).", Order = 7, GroupName = "01. Fiche 15 - Univers et donnees")]
        public string ExcludedDaysFile { get; set; }

        [Display(Name = "Agenda macro (CSV, optionnel)", Description = "macro_events.csv : evenements USD forts FOMC/CPI/NFP ajoutes aux jours exclus.", Order = 8, GroupName = "01. Fiche 15 - Univers et donnees")]
        public string MacroFile { get; set; }

        [Range(1, 60)]
        [Display(Name = "Actif net : anciennete max (jours)", Order = 9, GroupName = "01. Fiche 15 - Univers et donnees")]
        public int AumMaxStaleDays { get; set; }

        [NinjaScriptProperty]
        [Display(Name = "1. Formule du flux", Description = "Fiche = A L(L-1) r / (1 + L r) ; NavVeilleExacte = A L(L-1) r (exact avec la NAV de la veille).", Order = 1, GroupName = "02. Fiche 15 - Signal")]
        public NxLetfFlowFormula FlowFormula { get; set; }

        [Display(Name = "5. Flux primaires", Description = "Auto : creations nettes du jour ajoutees (L x C) si net_flow_usd est fourni, sinon tendance 5 j en controle.", Order = 2, GroupName = "02. Fiche 15 - Signal")]
        public Nexus15PrimaryFlows PrimaryFlows { get; set; }

        [Display(Name = "Heure du signal (ET)", Order = 3, GroupName = "02. Fiche 15 - Signal")]
        public string SignalTime { get; set; }

        [Range(1, 250)]
        [Display(Name = "4. Volume moyen de fenetre (seances)", Order = 4, GroupName = "02. Fiche 15 - Signal")]
        public int VolumeLookbackDays { get; set; }

        [NinjaScriptProperty]
        [Display(Name = "6. Filtre gamma", Description = "Faux = version sans filtre gamma (risque d erreur de mesure du GEX).", Order = 5, GroupName = "02. Fiche 15 - Signal")]
        public bool UseGammaFilter { get; set; }

        [Range(0.0, 10.0)]
        [Display(Name = "6. w court gamma (G < 0)", Order = 6, GroupName = "02. Fiche 15 - Signal")]
        public double GammaShortWeight { get; set; }

        [NinjaScriptProperty]
        [Range(0.0, 10.0)]
        [Display(Name = "6. w long gamma (G > 0)", Description = "0.3 = point de depart a calibrer in-sample.", Order = 7, GroupName = "02. Fiche 15 - Signal")]
        public double GammaLongWeight { get; set; }

        [Display(Name = "6. GEX inconnu", Order = 8, GroupName = "02. Fiche 15 - Signal")]
        public NxLetfGammaUnknown GammaUnknown { get; set; }

        [Range(0, 30)]
        [Display(Name = "6. GEX : anciennete max (jours)", Order = 9, GroupName = "02. Fiche 15 - Signal")]
        public int GexMaxStaleDays { get; set; }

        [NinjaScriptProperty]
        [Range(1.0, 99.0)]
        [Display(Name = "Seuil : quantile de |Score| (%)", Order = 1, GroupName = "03. Fiche 15 - Regles de trading")]
        public double ThresholdQuantilePct { get; set; }

        [Range(20, 5000)]
        [Display(Name = "Seuil : fenetre glissante (seances)", Order = 2, GroupName = "03. Fiche 15 - Regles de trading")]
        public int ThresholdWindow { get; set; }

        [Range(1, 5000)]
        [Display(Name = "Seuil : historique minimal (seances)", Order = 3, GroupName = "03. Fiche 15 - Regles de trading")]
        public int MinThresholdHistory { get; set; }

        [NinjaScriptProperty]
        [Range(0.0, 20.0)]
        [Display(Name = "Filtre de rendement |r| min (%)", Order = 4, GroupName = "03. Fiche 15 - Regles de trading")]
        public double MinAbsReturnPct { get; set; }

        [Display(Name = "Heure d entree (ET)", Order = 5, GroupName = "03. Fiche 15 - Regles de trading")]
        public string EntryTime { get; set; }

        [Range(0, 25)]
        [Display(Name = "Entree : retard toleré (min)", Order = 6, GroupName = "03. Fiche 15 - Regles de trading")]
        public int EntryToleranceMinutes { get; set; }

        [Display(Name = "Entree : ordre", Description = "Temps reel : limite au mid, ou marche si spread <= 1 tick. Backtest : marche.", Order = 7, GroupName = "03. Fiche 15 - Regles de trading")]
        public Nexus15Entry EntryMode { get; set; }

        [Range(1, 25)]
        [Display(Name = "Entree : validite de la limite (min)", Order = 8, GroupName = "03. Fiche 15 - Regles de trading")]
        public int LimitValidMinutes { get; set; }

        [NinjaScriptProperty]
        [Range(0.01, 100.0)]
        [Display(Name = "Taille : cible de risque (% capital, 1 sigma)", Description = "Perte a 1 ecart-type sur 15:30-16:00 au seuil (|Score| = seuil).", Order = 9, GroupName = "03. Fiche 15 - Regles de trading")]
        public double RiskTargetPct { get; set; }

        [Range(5, 240)]
        [Display(Name = "Taille : vol realisee (minutes)", Order = 10, GroupName = "03. Fiche 15 - Regles de trading")]
        public int RvMinutes { get; set; }

        [Range(0.0, 100.0)]
        [Display(Name = "Taille : plafond (% du volume de fenetre)", Order = 11, GroupName = "03. Fiche 15 - Regles de trading")]
        public double VolumeCapPct { get; set; }

        [Range(0.0, 50.0)]
        [Display(Name = "Mouvement extreme |r| (%) : plafond / 2", Order = 12, GroupName = "03. Fiche 15 - Regles de trading")]
        public double ExtremeMovePct { get; set; }

        [Range(0.0, 100.0)]
        [Display(Name = "Taille : levier max (0 = aucun)", Description = "Hors fiche : notionnel max / capital. 0 = taille exacte de la fiche (seul le plafond de volume s applique).", Order = 13, GroupName = "03. Fiche 15 - Regles de trading")]
        public double MaxLeverage { get; set; }

        [NinjaScriptProperty]
        [Range(0.1, 20.0)]
        [Display(Name = "Stop : multiplicateur ATR", Order = 13, GroupName = "03. Fiche 15 - Regles de trading")]
        public double AtrMultiplier { get; set; }

        [Range(1, 240)]
        [Display(Name = "Stop : barres ATR (minutes)", Order = 14, GroupName = "03. Fiche 15 - Regles de trading")]
        public int AtrBarMinutes { get; set; }

        [Range(1, 200)]
        [Display(Name = "Stop : periode ATR", Order = 15, GroupName = "03. Fiche 15 - Regles de trading")]
        public int AtrPeriod { get; set; }

        [Display(Name = "Heure de sortie (ET)", Order = 16, GroupName = "03. Fiche 15 - Regles de trading")]
        public string ExitTime { get; set; }

        [NinjaScriptProperty]
        [Display(Name = "Sortie", Description = "MarcheA16h (equivalent MOC) ou TWAP 15:55-16:00 en tranches d une minute.", Order = 17, GroupName = "03. Fiche 15 - Regles de trading")]
        public Nexus15Exit ExitMode { get; set; }

        [Display(Name = "Debut du TWAP (ET)", Order = 18, GroupName = "03. Fiche 15 - Regles de trading")]
        public string TwapStartTime { get; set; }

        [NinjaScriptProperty]
        [Display(Name = "Instrument", Description = "PrioritaireEtSecours : NQ, sinon ES si son score passe le seuil (une position par jour).", Order = 19, GroupName = "03. Fiche 15 - Regles de trading")]
        public NxLetfInstrumentRule InstrumentRule { get; set; }

        [Display(Name = "Exclure FOMC / CPI / NFP", Order = 20, GroupName = "03. Fiche 15 - Regles de trading")]
        public bool ExcludeMacroDays { get; set; }

        [Display(Name = "Exclure les demi-seances", Order = 21, GroupName = "03. Fiche 15 - Regles de trading")]
        public bool ExcludeHalfDays { get; set; }

        [Display(Name = "Exclure les quatre sorcieres", Order = 22, GroupName = "03. Fiche 15 - Regles de trading")]
        public bool ExcludeQuadWitching { get; set; }

        [Display(Name = "Exclure le rebalancement NDX", Order = 23, GroupName = "03. Fiche 15 - Regles de trading")]
        public bool ExcludeNdxRebalance { get; set; }

        [Display(Name = "Exclure les autres jours du fichier", Order = 24, GroupName = "03. Fiche 15 - Regles de trading")]
        public bool ExcludeOtherDays { get; set; }

        [Range(0.0, 20.0)]
        [Display(Name = "Couts : ticks aller-retour / contrat", Description = "1 tick minimum (fiche) ; 2 = stress.", Order = 1, GroupName = "04. Fiche 15 - Protocole de backtest")]
        public double CostTicksRoundTrip { get; set; }

        [Range(0.0, 20.0)]
        [Display(Name = "Couts : stress (ticks aller-retour)", Order = 2, GroupName = "04. Fiche 15 - Protocole de backtest")]
        public double StressTicksRoundTrip { get; set; }

        [Range(0.0, 100.0)]
        [Display(Name = "Commission par contrat et par cote ($)", Order = 3, GroupName = "04. Fiche 15 - Protocole de backtest")]
        public double CommissionPerSide { get; set; }

        [Display(Name = "Debut hors echantillon", Description = "Calibration avant, test apres (fiche : 2012-2020 / 2021-2026).", Order = 4, GroupName = "04. Fiche 15 - Protocole de backtest")]
        public string OosStart { get; set; }

        [Range(1, 20)]
        [Display(Name = "Walk-forward : fenetre (annees)", Order = 5, GroupName = "04. Fiche 15 - Protocole de backtest")]
        public int WalkForwardYears { get; set; }

        [Range(-1, 100)]
        [Display(Name = "Newey-West : lags (-1 = auto)", Order = 6, GroupName = "04. Fiche 15 - Protocole de backtest")]
        public int NeweyWestLags { get; set; }

        [Display(Name = "Placebo : heure du signal (ET)", Order = 7, GroupName = "04. Fiche 15 - Protocole de backtest")]
        public string PlaceboSignalTime { get; set; }

        [Display(Name = "Placebo : debut de fenetre (ET)", Order = 8, GroupName = "04. Fiche 15 - Protocole de backtest")]
        public string PlaceboStartTime { get; set; }

        [Display(Name = "Placebo : fin de fenetre (ET)", Order = 9, GroupName = "04. Fiche 15 - Protocole de backtest")]
        public string PlaceboEndTime { get; set; }

        [Range(0.001, 1000.0)]
        [Display(Name = "Placebo de levier : constante", Order = 10, GroupName = "04. Fiche 15 - Protocole de backtest")]
        public double LeveragePlaceboConstant { get; set; }

        [Display(Name = "Ecrire le panel quotidien (CSV)", Order = 11, GroupName = "04. Fiche 15 - Protocole de backtest")]
        public bool WritePanel { get; set; }
        #endregion
    }
}
