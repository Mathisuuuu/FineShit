// =============================================================================
//  Nexus11_OptionsWheel.cs   (NinjaTrader 8 / NinjaScript)
//
//  FICHE 11 - Options : puts couverts par du cash + calls couverts ("wheel")
//  Prime de variance (markwmke, API Schwab, comptes retraite). Bondarenko /
//  Cboe : vol implicite moyenne S&P 500 ~19.3 % vs 15.1 % realisee (1990-2018).
//  Israelov, Nielsen : dans un call couvert, la jambe "vente de vol" a un Sharpe
//  proche de 1 ; la jambe "pari sur un retournement" pese ~25 % du risque.
//
//  REGLES
//   - Cycle : vendre un put couvert par du cash ; si assigne, vendre des calls
//     couverts sur les actions recues ; si appele, recommencer.
//   - Echeance 30 a 45 jours (mensuelle du 3e vendredi de preference).
//   - Strike du put : delta -0.20 a -0.30 ; du call : delta 0.20 a 0.30 ET
//     au-dessus du prix de revient.
//   - Prise de benefice : racheter a 50 % de la prime encaissee.
//   - Gestion du temps : a 21 jours de l echeance, cloturer ou rouler
//     (par defaut : cloturer si hors de la monnaie, laisser aller a l echeance
//     pour l assignation si dans la monnaie, afin que la roue tourne).
//   - Filtre de spread a plusieurs niveaux : (ask-bid)/mid <= 5 %, spread absolu
//     <= 0.10 $, prime >= 0.30 $ ("une option a 0.25 $ avec 0.10 $ de spread
//     perd 40 % de son avantage en aller-retour").
//   - GARDE-FOU D ETAT : ne jamais vendre un call sur une action qui a un ordre
//     de vente en attente (sinon call NU dans un IRA - incident reel de markwmke).
//   - Contrainte de capital : un put couvert immobilise strike x 100 en cash ;
//     avec 1 000 $, seul un sous-jacent sous 10 $ est possible.
//
//  MODES (NinjaScript ne fournit pas de chaine d options) :
//   - Synthetique (defaut, backtest) : prix Black-Scholes, vol implicite =
//     vol realisee 20 j x 1.28 (ratio de prime de variance) ou indice de vol
//     (VIX...) ; spread modelise ; PnL suivi hors ordres NinjaTrader.
//   - SignalSeul (temps reel) : meme moteur, emission de "tickets" (Output,
//     alerte, journal) a executer a la main ou par un autre robot.
//   - CompteNT_Experimental : routage reel des options par l API Account de
//     NinjaTrader (courtier compatible options, ex. Interactive Brokers) ; le
//     nom d instrument est construit depuis un format parametrable ; cotations
//     reelles pour le filtre de spread. A valider sur compte simule.
//
//  Points d attention : 80 % de trades gagnants ne dit rien du rendement - le
//  rapport met en avant la PIRE PERTE MENSUELLE ; il decompose aussi les calls
//  vendus en PnL brut vs PnL couvert en delta (Israelov-Nielsen). L assignation
//  anticipee (options americaines) n est pas modelisee.
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
    public enum Nexus11Mode { Synthetique, SignalSeul, CompteNT_Experimental }
    public enum Nexus11Etat { Libre, PutVendu, Actions, CallVendu }
    public enum Nexus11A21Jours { Cloturer, Rouler, AssignationSiDansLaMonnaie }
    public enum Nexus11SourceVol { VolRealiseeRatio, IndiceDeVol }

    public class Nexus11OptionsWheel : NexusStrategyBase
    {
        private class Opt
        {
            public bool IsCall;
            public double K;
            public DateTime Expiry;
            public int Contracts;
            public double Premium;          // par action, net du glissement
            public double OpenIv;
            public DateTime OpenDay;
            public double LastS = double.NaN;
            public double LastDelta;
            public double HedgePnl;          // PnL d une couverture en delta (analyse Israelov-Nielsen)
            public string Label;
            public Order LiveOrder;          // mode CompteNT
            public NinjaTrader.Cbi.Instrument LiveInstrument;
        }

        private class Wheel
        {
            public Nexus11Etat Etat = Nexus11Etat.Libre;
            public Opt Option;
            public int Shares;
            public double CostBasis;
            public DateTime SharesSince;
            public double Cash;              // flux de tresorerie cumules (primes, rachats, frais, achats/ventes d actions synthetiques)
            public double LastS = double.NaN;
            public int Cycles, Assignments, CalledAway, Rolls, ProfitTakes, SpreadRejects, CapitalRejects, GuardBlocks;
        }

        private readonly Dictionary<string, Wheel> wheels = new Dictionary<string, Wheel>(StringComparer.OrdinalIgnoreCase);
        private Dictionary<string, string> ivMap;
        private readonly Dictionary<string, MarketData> liveFeeds = new Dictionary<string, MarketData>();
        private readonly Dictionary<string, EventHandler<MarketDataEventArgs>> liveHandlers = new Dictionary<string, EventHandler<MarketDataEventArgs>>();
        private readonly Dictionary<string, double[]> liveQuotes = new Dictionary<string, double[]>();
        private double callPnlRaw, callPnlHedged, putPnlRaw, putPnlHedged;
        private readonly List<double> ivUsed = new List<double>(), rvAfter = new List<double>();
        private readonly List<KeyValuePair<NxSym, KeyValuePair<int, double>>> ivChecks = new List<KeyValuePair<NxSym, KeyValuePair<int, double>>>();

        protected override void NxSetDefaults()
        {
            Name = "Nexus11_OptionsWheel";
            Description = "Fiche 11 - Wheel : put couvert (delta -0.25, 30-45 j) puis calls couverts au-dessus du prix de revient ; rachat a 50 %, gestion a 21 j, filtre de spread, garde-fou d ordre de vente en attente.";
            Symbols = "SPY,QQQ,IWM,AAPL,MSFT,F,T,SOFI";
            SizingMode = NxSizingMode.Natif;
            StopMode = NxStopMode.Aucun;

            Mode = Nexus11Mode.Synthetique;
            DteMin = 30;
            DteMax = 45;
            PutDelta = -0.25;
            PutDeltaMin = -0.30;
            PutDeltaMax = -0.20;
            CallDelta = 0.25;
            CallDeltaMin = 0.20;
            CallDeltaMax = 0.30;
            ProfitTakePct = 50.0;
            ManageAtDte = 21;
            At21Days = Nexus11A21Jours.AssignationSiDansLaMonnaie;
            VolSource = Nexus11SourceVol.VolRealiseeRatio;
            IvToRvRatio = 1.28;
            RvWindowDays = 20;
            IvIndexMap = "SPY=^VIX;QQQ=^VXN";
            RiskFreePct = 4.0;
            DividendYieldPct = 0.0;
            StrikeStep = 0.0;
            SpreadMaxPct = 5.0;
            MaxSpreadAbs = 0.10;
            MinPremium = 0.30;
            ModelSpreadAbs = 0.03;
            ModelSpreadPct = 2.0;
            FillPenaltyPct = 50.0;
            FeePerContract = 0.65;
            MaxAllocationPct = 25.0;
            MaxContracts = 5;
            UseAdjustedCostBasis = false;
            ExecuteStockLeg = false;
            OptionNameFormat = "{SYM} {MM}-{DD}-{YYYY} {STRIKE} {CALLPUT}";
            LiveOrderTimeoutMinutes = 30;
        }

        protected override bool NxBatchMode { get { return false; } }

        protected override IEnumerable<string> NxRequiredReferences()
        {
            return VolSource == Nexus11SourceVol.IndiceDeVol ? NxText.ParseMap(IvIndexMap).Values : new string[0];
        }

        protected override void NxDataLoaded()
        {
            ivMap = NxText.ParseMap(IvIndexMap);
            foreach (NxSym s in TradedSyms) wheels[s.Name] = new Wheel();
            if (Mode != Nexus11Mode.Synthetique) Nx("Mode " + Mode + " : les ordres d options ne partent qu en temps reel ; l historique est simule.");
            double bank = InitialBankroll;
            foreach (NxSym s in TradedSyms)
                if (s.Hist != null && s.Hist.Count == 0)
                    Nx(string.Format(CultureInfo.InvariantCulture, "{0} : un put couvert exige ~strike x 100 de cash ; avec {1:F0} $ et {2:F0} % max par sous-jacent, prix max ~{3:F2} $.",
                        s.Name, bank, MaxAllocationPct, bank * MaxAllocationPct / 100.0 / 100.0));
        }

        // =====================================================================
        //  Outils de prix
        // =====================================================================
        private double Iv(NxSym s)
        {
            if (VolSource == Nexus11SourceVol.IndiceDeVol)
            {
                string idx;
                NxSym v = ivMap.TryGetValue(s.Name, out idx) ? Sym(idx) : null;
                if (v != null && v.Hist.Count > 0 && v.Hist.LastClose > 0) return v.Hist.LastClose / 100.0;
            }
            double rv = s.Hist.RealizedVol(RvWindowDays);
            return NxMath.Ok(rv) && rv > 0 ? Math.Max(0.05, rv * IvToRvRatio) : double.NaN;
        }

        private double Step(double price)
        {
            if (StrikeStep > 0) return StrikeStep;
            if (price < 25) return 0.5;
            if (price < 200) return 1.0;
            if (price < 1000) return 5.0;
            return 10.0;
        }

        private static DateTime ChooseExpiry(DateTime day, int dteMin, int dteMax)
        {
            for (int m = 0; m < 4; m++)
            {
                DateTime d = day.AddMonths(m);
                DateTime tf = NxCalendar.ThirdFriday(d.Year, d.Month);
                double dte = (tf - day.Date).TotalDays;
                if (dte >= dteMin && dte <= dteMax) return tf;
            }
            DateTime f = day.Date.AddDays(dteMin);
            while (f.DayOfWeek != DayOfWeek.Friday) f = f.AddDays(1);
            return f;
        }

        private double Years(DateTime day, DateTime expiry) { return Math.Max(0.0, (expiry.Date - day.Date).TotalDays) / 365.0; }

        private double ModelSpread(double mid) { return ModelSpreadAbs + ModelSpreadPct / 100.0 * mid; }

        /// <summary>Filtre de spread a plusieurs niveaux ; renvoie null si accepte, sinon la raison.</summary>
        private string SpreadFilter(double bid, double ask)
        {
            double mid = 0.5 * (bid + ask), spr = ask - bid;
            if (!(mid > 0) || bid <= 0) return "cotation invalide";
            if (mid < MinPremium) return string.Format(CultureInfo.InvariantCulture, "niveau 3 : prime {0:F2} $ < {1:F2} $", mid, MinPremium);
            if (spr > MaxSpreadAbs) return string.Format(CultureInfo.InvariantCulture, "niveau 2 : spread {0:F2} $ > {1:F2} $", spr, MaxSpreadAbs);
            if (spr / mid > SpreadMaxPct / 100.0) return string.Format(CultureInfo.InvariantCulture, "niveau 1 : spread {0:P1} du mid > {1:F1} %", spr / mid, SpreadMaxPct);
            return null;
        }

        private string OptionLabel(NxSym s, bool isCall, DateTime exp, double k)
        {
            return string.Format(CultureInfo.InvariantCulture, "{0} {1:yyyy-MM-dd} {2}{3}", s.Name, exp, isCall ? "C" : "P", k);
        }

        // =====================================================================
        //  Boucle quotidienne
        // =====================================================================
        protected override void NxOnSymbolBar(NxSym s, DateTime day)
        {
            if (!s.Traded) return;
            Wheel w;
            if (!wheels.TryGetValue(s.Name, out w)) return;
            double S = s.Hist.LastClose;
            if (s.Hist.Count < RvWindowDays + 5 || !(S > 0)) return;
            double iv = Iv(s);
            if (!NxMath.Ok(iv)) return;
            CheckIvAfter(s);

            // Analyse delta-couverte : PnL de la couverture depuis la veille.
            if (w.Option != null && NxMath.Ok(w.Option.LastS))
                w.Option.HedgePnl += w.Option.LastDelta * (S - w.Option.LastS) * 100.0 * w.Option.Contracts;
            if (w.Option != null)
            {
                double T = Years(day, w.Option.Expiry);
                w.Option.LastDelta = NxBlackScholes.Delta(w.Option.IsCall, S, w.Option.K, T, RiskFreePct / 100.0, iv, DividendYieldPct / 100.0);
                w.Option.LastS = S;
            }
            w.LastS = S;

            if (Mode == Nexus11Mode.CompteNT_Experimental && State == State.Realtime && w.Option != null && w.Option.LiveOrder != null) { PollLiveOrder(s, w); return; }

            switch (w.Etat)
            {
                case Nexus11Etat.Libre: OpenShort(s, w, false, day, S, iv); break;
                case Nexus11Etat.PutVendu: Manage(s, w, day, S, iv); break;
                case Nexus11Etat.Actions: OpenShort(s, w, true, day, S, iv); break;
                case Nexus11Etat.CallVendu: Manage(s, w, day, S, iv); break;
            }
        }

        private double CommittedCash(NxSym except)
        {
            double c = 0;
            foreach (KeyValuePair<string, Wheel> kv in wheels)
            {
                Wheel w = kv.Value;
                if (w.Option != null && !w.Option.IsCall) c += w.Option.K * 100.0 * w.Option.Contracts;
                if (w.Shares > 0 && !ExecuteStockLeg && NxMath.Ok(w.LastS)) c += w.Shares * w.LastS;
            }
            return c;
        }

        private void OpenShort(NxSym s, Wheel w, bool isCall, DateTime day, double S, double iv)
        {
            string br;
            if (!isCall && !Breaker.CanOpen(NowNt, out br)) { NxV(s.Name + " : put non vendu (" + br + ")"); return; }
            if (State == State.Realtime && UseKillSwitch && NxKillSwitch.IsActive()) return;

            DateTime exp = ChooseExpiry(day, DteMin, DteMax);
            double T = Years(day, exp), r = RiskFreePct / 100.0, q = DividendYieldPct / 100.0;
            if (T <= 0) return;
            double step = Step(S);
            double target = isCall ? CallDelta : PutDelta;
            double k = NxBlackScholes.StrikeFromDelta(isCall, S, T, r, iv, target, q);
            k = isCall ? Math.Ceiling(k / step) * step : Math.Floor(k / step) * step;
            // Bande en valeur absolue du delta : |delta| trop grand = trop pres de la monnaie -> s eloigner de S ;
            // |delta| trop petit = trop loin -> se rapprocher de S (call : K vers le bas, put : K vers le haut).
            double magLo = Math.Min(Math.Abs(isCall ? CallDeltaMin : PutDeltaMin), Math.Abs(isCall ? CallDeltaMax : PutDeltaMax));
            double magHi = Math.Max(Math.Abs(isCall ? CallDeltaMin : PutDeltaMin), Math.Abs(isCall ? CallDeltaMax : PutDeltaMax));
            for (int guard = 0; guard < 8; guard++)
            {
                double m = Math.Abs(NxBlackScholes.Delta(isCall, S, k, T, r, iv, q));
                if (m > magHi) k += isCall ? step : -step;
                else if (m < magLo && k - step > 0) k += isCall ? -step : step;
                else break;
            }
            double finalMag = Math.Abs(NxBlackScholes.Delta(isCall, S, k, T, r, iv, q));
            bool callAboveBasisOnly = isCall && k < w.CostBasis;   // le prix de revient prime sur la bande (traite plus bas)
            if (!callAboveBasisOnly && (finalMag < magLo - 1e-9 || finalMag > magHi + 1e-9))
            {
                // Grille de strikes trop grossiere : aucun strike dans la bande de delta -> pas de vente aujourd hui.
                w.SpreadRejects++;
                NxV(string.Format(CultureInfo.InvariantCulture, "{0} : aucun strike dans la bande |delta| {1:F2}-{2:F2} (pas {3}, |delta| {4:F3}) -> pas de vente",
                    s.Name, magLo, magHi, step, finalMag));
                return;
            }
            int contracts;
            if (isCall)
            {
                // GARDE-FOU : jamais de call sur des actions avec un ordre de vente en attente.
                string guardWhy;
                if (HasPendingSell(s, out guardWhy)) { w.GuardBlocks++; NxAlert("GARDE-FOU " + s.Name + " : " + guardWhy + " -> call NON vendu (eviterait un call nu)"); return; }
                double basis = w.CostBasis;
                if (k < basis) k = Math.Ceiling(basis / step) * step;          // au-dessus du prix de revient
                contracts = w.Shares / 100;
                if (contracts <= 0) { w.Etat = Nexus11Etat.Libre; return; }
            }
            else
            {
                double bank = Bankroll();
                double avail = Math.Min(bank - CommittedCash(s), bank * MaxAllocationPct / 100.0);
                contracts = Math.Min(MaxContracts, (int)Math.Floor(avail / (k * 100.0)));
                if (contracts <= 0)
                {
                    w.CapitalRejects++;
                    NxOnce("cap" + s.Name, string.Format(CultureInfo.InvariantCulture, "{0} : capital insuffisant pour un put couvert (strike {1} x 100 = {2:F0} $ > {3:F0} $ disponibles).", s.Name, k, k * 100, avail));
                    return;
                }
            }
            double mid = NxBlackScholes.Price(isCall, S, k, T, r, iv, q);
            double spr = ModelSpread(mid), bid = mid - spr / 2, ask = mid + spr / 2;
            if (Mode == Nexus11Mode.CompteNT_Experimental && State == State.Realtime)
            {
                NinjaTrader.Cbi.Instrument ins = OptionInstrument(s, isCall, exp, k);
                if (ins == null) return;
                double[] qt;
                if (!liveQuotes.TryGetValue(ins.FullName, out qt) || !(qt[0] > 0) || !(qt[1] > 0)) { NxV("Pas encore de cotation pour " + ins.FullName); return; }
                bid = qt[0]; ask = qt[1]; mid = 0.5 * (bid + ask);
            }
            string reject = SpreadFilter(bid, ask);
            string label = OptionLabel(s, isCall, exp, k);
            if (reject != null) { w.SpreadRejects++; NxV(label + " rejete par le filtre de spread : " + reject); return; }

            double fill = mid - FillPenaltyPct / 100.0 * (mid - bid);
            Opt o = new Opt
            {
                IsCall = isCall, K = k, Expiry = exp, Contracts = contracts, Premium = fill, OpenIv = iv, OpenDay = day,
                LastS = S, LastDelta = NxBlackScholes.Delta(isCall, S, k, T, r, iv, q), Label = label
            };
            w.Cash += fill * 100.0 * contracts - contracts * FeePerContract;
            w.Option = o;
            w.Etat = isCall ? Nexus11Etat.CallVendu : Nexus11Etat.PutVendu;
            if (!isCall) w.Cycles++;
            ivChecks.Add(new KeyValuePair<NxSym, KeyValuePair<int, double>>(s, new KeyValuePair<int, double>(s.Hist.Count, iv)));
            string why = string.Format(CultureInfo.InvariantCulture, "VENDRE {0} x{1} @ {2:F2} (mid {3:F2}, delta {4:F2}, IV {5:P1}, collateral {6:F0} $)",
                label, contracts, fill, mid, o.LastDelta, iv, isCall ? 0 : k * 100 * contracts);
            Ticket(s, why);
            if (Mode == Nexus11Mode.CompteNT_Experimental && State == State.Realtime) SubmitLive(s, o, true, mid);
        }

        private void Manage(NxSym s, Wheel w, DateTime day, double S, double iv)
        {
            Opt o = w.Option;
            if (o == null) { w.Etat = w.Shares > 0 ? Nexus11Etat.Actions : Nexus11Etat.Libre; return; }
            double T = Years(day, o.Expiry), r = RiskFreePct / 100.0, q = DividendYieldPct / 100.0;
            int dte = (int)Math.Round((o.Expiry.Date - day.Date).TotalDays);
            bool itm = o.IsCall ? S > o.K : S < o.K;

            if (dte <= 0)
            {
                Settle(s, w, S, day);
                return;
            }
            double value = NxBlackScholes.Price(o.IsCall, S, o.K, T, r, iv, q);
            double buy = value + FillPenaltyPct / 100.0 * ModelSpread(value) / 2.0;
            if (buy <= (1 - ProfitTakePct / 100.0) * o.Premium)
            {
                w.ProfitTakes++;
                CloseOption(s, w, buy, "prise de benefice " + ProfitTakePct + " %");
                return;
            }
            if (dte <= ManageAtDte)
            {
                if (At21Days == Nexus11A21Jours.Cloturer || (At21Days == Nexus11A21Jours.AssignationSiDansLaMonnaie && !itm))
                {
                    CloseOption(s, w, buy, "gestion a " + ManageAtDte + " jours");
                }
                else if (At21Days == Nexus11A21Jours.Rouler)
                {
                    w.Rolls++;
                    bool wasCall = o.IsCall;
                    CloseOption(s, w, buy, "roulement a " + ManageAtDte + " jours");
                    OpenShort(s, w, wasCall, day, S, iv);
                }
                // AssignationSiDansLaMonnaie + dans la monnaie : on laisse aller a l echeance.
            }
        }

        private void CloseOption(NxSym s, Wheel w, double buyPrice, string reason)
        {
            Opt o = w.Option;
            w.Cash -= buyPrice * 100.0 * o.Contracts + o.Contracts * FeePerContract;
            double pnl = (o.Premium - buyPrice) * 100.0 * o.Contracts - 2.0 * o.Contracts * FeePerContract;
            RecordOptionTrade(s, o, buyPrice, pnl, reason);
            Ticket(s, string.Format(CultureInfo.InvariantCulture, "RACHETER {0} x{1} @ {2:F2} ({3}) PnL {4:F2} $", o.Label, o.Contracts, buyPrice, reason, pnl));
            if (Mode == Nexus11Mode.CompteNT_Experimental && State == State.Realtime) SubmitLive(s, o, false, buyPrice);
            w.Option = null;
            w.Etat = w.Shares > 0 ? Nexus11Etat.Actions : Nexus11Etat.Libre;
        }

        private void Settle(NxSym s, Wheel w, double S, DateTime day)
        {
            Opt o = w.Option;
            bool itm = o.IsCall ? S > o.K : S < o.K;
            double intrinsic = itm ? Math.Abs(S - o.K) : 0.0;
            double pnl = (o.Premium - intrinsic) * 100.0 * o.Contracts - o.Contracts * FeePerContract;
            RecordOptionTrade(s, o, intrinsic, pnl, itm ? (o.IsCall ? "appele a l echeance" : "assigne a l echeance") : "expire sans valeur");
            int shares = 100 * o.Contracts;
            if (!o.IsCall)
            {
                if (itm)
                {
                    // Assignation : achat de 100 x n actions au strike.
                    w.Assignments++;
                    w.CostBasis = UseAdjustedCostBasis ? o.K - o.Premium : o.K;
                    w.SharesSince = day;
                    w.Shares += shares;
                    if (ExecuteStockLeg)
                    {
                        // Actions reelles achetees au marche (~S) : la perte intrinseque (K - S) est soldee cote option.
                        w.Cash -= intrinsic * shares;
                        SetTarget(s, s.TargetQty + shares, double.NaN, "assignation du put " + o.Label);
                    }
                    else w.Cash -= o.K * shares;
                    w.Etat = Nexus11Etat.Actions;
                    Ticket(s, string.Format(CultureInfo.InvariantCulture, "ASSIGNATION {0} : +{1} actions a {2:F2} (cours {3:F2})", o.Label, shares, o.K, S));
                }
                else w.Etat = w.Shares > 0 ? Nexus11Etat.Actions : Nexus11Etat.Libre;
            }
            else
            {
                if (itm)
                {
                    // Appel : vente des actions au strike.
                    w.CalledAway++;
                    int sold = Math.Min(w.Shares, shares);
                    double stockPnl = (o.K - w.CostBasis) * sold;
                    RecordStockTrade(s, w, o.K, sold, day, stockPnl);
                    w.Shares -= sold;
                    if (ExecuteStockLeg)
                    {
                        w.Cash -= intrinsic * sold;
                        SetTarget(s, Math.Max(0, s.TargetQty - sold), double.NaN, "actions appelees " + o.Label);
                    }
                    else w.Cash += o.K * sold;
                    Ticket(s, string.Format(CultureInfo.InvariantCulture, "APPELE {0} : -{1} actions a {2:F2} (PnL actions {3:F2} $)", o.Label, sold, o.K, stockPnl));
                }
                w.Etat = w.Shares > 0 ? Nexus11Etat.Actions : Nexus11Etat.Libre;
            }
            w.Option = null;
        }

        // =====================================================================
        //  Comptabilite synthetique (equity du socle via NxExtraEquity)
        // =====================================================================
        protected override double NxExtraEquity()
        {
            // Contribution = flux de tresorerie + actions synthetiques au marche - valeur des options vendues ouvertes.
            double e = 0;
            foreach (KeyValuePair<string, Wheel> kv in wheels)
            {
                Wheel w = kv.Value;
                e += w.Cash;
                NxSym s = Sym(kv.Key);
                double S = s != null && NxMath.Ok(s.LastPrice) ? s.LastPrice : w.LastS;
                if (!NxMath.Ok(S)) continue;
                if (w.Shares > 0 && !ExecuteStockLeg) e += w.Shares * S;
                if (w.Option != null)
                {
                    double iv = s != null ? Iv(s) : double.NaN;
                    DateTime d = s != null && s.Hist.Count > 0 ? s.Hist.LastDate : w.Option.OpenDay;
                    double v = NxMath.Ok(iv) ? NxBlackScholes.Price(w.Option.IsCall, S, w.Option.K, Years(d, w.Option.Expiry), RiskFreePct / 100.0, iv, DividendYieldPct / 100.0)
                                             : Math.Max(0, w.Option.IsCall ? S - w.Option.K : w.Option.K - S);
                    e -= v * 100.0 * w.Option.Contracts;
                }
            }
            return e;
        }

        private void RecordOptionTrade(NxSym s, Opt o, double closePrice, double pnl, string reason)
        {
            double collateral = o.K * 100.0 * o.Contracts;   // capital immobilise (cash du put ou actions du call)
            double hedged = pnl + o.HedgePnl;
            double fees = (reason.StartsWith("expire") || reason.Contains("echeance") ? 1.0 : 2.0) * o.Contracts * FeePerContract;
            if (o.IsCall) { callPnlRaw += pnl; callPnlHedged += hedged; } else { putPnlRaw += pnl; putPnlHedged += hedged; }
            NxTradeRecord r = new NxTradeRecord
            {
                Strategy = StrategyId, Symbol = o.Label, Class = NxAssetClass.Option, Direction = -1, MaxQty = o.Contracts,
                EntryTime = o.OpenDay, ExitTime = s.Hist.LastDate, EntryPrice = o.Premium, ExitPrice = closePrice, MaxNotional = collateral,
                GrossPnl = pnl + fees, Costs = fees, NetPnl = pnl,
                NetReturn = collateral > 0 ? pnl / collateral : 0, GrossReturn = collateral > 0 ? (pnl + fees) / collateral : 0,
                EntryReason = (o.IsCall ? "call couvert" : "put couvert") + string.Format(CultureInfo.InvariantCulture, " IV {0:P1}", o.OpenIv),
                ExitReason = reason, IsRealtime = State == State.Realtime, IsRealMoney = false
            };
            RecordTrade(r);
        }

        private void RecordStockTrade(NxSym s, Wheel w, double exitPrice, int qty, DateTime day, double pnl)
        {
            if (ExecuteStockLeg) return;   // la jambe action reelle est comptee par le socle
            RecordTrade(new NxTradeRecord
            {
                Strategy = StrategyId, Symbol = s.Name + " (actions wheel)", Class = s.Class, Direction = 1, MaxQty = qty,
                EntryTime = w.SharesSince, ExitTime = day, EntryPrice = w.CostBasis, ExitPrice = exitPrice, MaxNotional = w.CostBasis * qty,
                GrossPnl = pnl, Costs = 0, NetPnl = pnl, NetReturn = w.CostBasis > 0 ? pnl / (w.CostBasis * qty) : 0,
                GrossReturn = w.CostBasis > 0 ? pnl / (w.CostBasis * qty) : 0, EntryReason = "assignation", ExitReason = "appele",
                IsRealtime = State == State.Realtime
            });
        }

        private void CheckIvAfter(NxSym s)
        {
            // Prime de variance : IV utilisee a l ouverture vs vol realisee sur les 21 jours suivants.
            for (int i = ivChecks.Count - 1; i >= 0; i--)
            {
                KeyValuePair<NxSym, KeyValuePair<int, double>> c = ivChecks[i];
                if (c.Key != s || s.Hist.Count < c.Value.Key + 21) continue;
                List<double> rets = new List<double>();
                for (int k = c.Value.Key + 1; k <= c.Value.Key + 21 && k < s.Hist.Count; k++) rets.Add(s.Hist.LogReturnAt(k));
                double rv = NxMath.StdDev(rets) * Math.Sqrt(252);
                if (NxMath.Ok(rv)) { ivUsed.Add(c.Value.Value); rvAfter.Add(rv); }
                ivChecks.RemoveAt(i);
            }
        }

        // =====================================================================
        //  Garde-fou, tickets et routage reel (experimental)
        // =====================================================================
        private bool HasPendingSell(NxSym s, out string why)
        {
            why = null;
            if (IsActive(s.EntryOrder) && (s.EntryOrder.OrderAction == OrderAction.Sell || s.EntryOrder.OrderAction == OrderAction.SellShort))
            { why = "ordre de vente de la strategie en attente (" + s.EntryOrder.Name + ")"; return true; }
            if (State == State.Realtime && Account != null)
            {
                try
                {
                    lock (Account.Orders)
                        foreach (Order o in Account.Orders)
                            if (o.Instrument != null && s.Instrument != null && o.Instrument.FullName == s.Instrument.FullName && !Order.IsTerminalState(o.OrderState)
                                && (o.OrderAction == OrderAction.Sell || o.OrderAction == OrderAction.SellShort))
                            { why = "ordre de vente en attente sur le compte (" + o.Name + ")"; return true; }
                }
                catch { }
            }
            return false;
        }

        private void Ticket(NxSym s, string text)
        {
            NxSignal(NowNt, s.Name, "ticket_option", text);
            if (State == State.Realtime && Mode != Nexus11Mode.Synthetique) NxAlert("TICKET " + text);
            else NxV(text);
        }

        private NinjaTrader.Cbi.Instrument OptionInstrument(NxSym s, bool isCall, DateTime exp, double k)
        {
            string name = OptionNameFormat.Replace("{SYM}", s.Name).Replace("{YYYY}", exp.ToString("yyyy")).Replace("{YY}", exp.ToString("yy"))
                .Replace("{MM}", exp.ToString("MM")).Replace("{DD}", exp.ToString("dd")).Replace("{STRIKE}", k.ToString("0.##", CultureInfo.InvariantCulture))
                .Replace("{CP}", isCall ? "C" : "P").Replace("{CALLPUT}", isCall ? "CALL" : "PUT");
            NinjaTrader.Cbi.Instrument ins = null;
            try { ins = NinjaTrader.Cbi.Instrument.GetInstrument(name, false); } catch { }
            if (ins == null) { NxOnce("opt" + name, "Instrument option introuvable '" + name + "' -> verifier 'Format du nom d option' (ticket seulement)."); return null; }
            if (!liveFeeds.ContainsKey(ins.FullName))
            {
                try
                {
                    MarketData md = new MarketData(ins);
                    string key = ins.FullName;
                    liveQuotes[key] = new[] { double.NaN, double.NaN };
                    EventHandler<MarketDataEventArgs> h = (sender, e) =>
                    {
                        double[] q;
                        if (!liveQuotes.TryGetValue(key, out q)) return;
                        if (e.MarketDataType == MarketDataType.Bid) q[0] = e.Price;
                        else if (e.MarketDataType == MarketDataType.Ask) q[1] = e.Price;
                    };
                    md.Update += h;
                    liveFeeds[key] = md;
                    liveHandlers[key] = h;
                }
                catch (Exception ex) { Nx("Abonnement aux cotations impossible pour " + name + " : " + ex.Message); }
            }
            return ins;
        }

        private void SubmitLive(NxSym s, Opt o, bool open, double price)
        {
            NinjaTrader.Cbi.Instrument ins = OptionInstrument(s, o.IsCall, o.Expiry, o.K);
            if (ins == null || Account == null) return;
            try
            {
                double px = ins.MasterInstrument.RoundToTickSize(price);
                Order ord = Account.CreateOrder(ins, open ? OrderAction.SellShort : OrderAction.BuyToCover, OrderType.Limit, OrderEntry.Automated,
                                                TimeInForce.Day, o.Contracts, px, 0, "", "NxOpt_" + s.Name, NinjaTrader.Core.Globals.MaxDate, null);
                Account.Submit(new[] { ord });
                o.LiveOrder = ord;
                o.LiveInstrument = ins;
                Nx(string.Format(CultureInfo.InvariantCulture, "Ordre option envoye : {0} {1} x{2} @ {3}", open ? "VENTE" : "RACHAT", ins.FullName, o.Contracts, px));
            }
            catch (Exception ex) { NxAlert("Echec d envoi de l ordre d option " + o.Label + " : " + ex.Message); }
        }

        private void PollLiveOrder(NxSym s, Wheel w)
        {
            Order ord = w.Option.LiveOrder;
            if (ord.OrderState == OrderState.Filled) { w.Option.Premium = ord.AverageFillPrice > 0 ? ord.AverageFillPrice : w.Option.Premium; w.Option.LiveOrder = null; return; }
            if (ord.OrderState == OrderState.Cancelled || ord.OrderState == OrderState.Rejected)
            {
                NxAlert("Ordre d option " + ord.OrderState + " : " + w.Option.Label + " -> etat remis a zero");
                w.Etat = w.Shares > 0 ? Nexus11Etat.Actions : Nexus11Etat.Libre;
                w.Option = null;
                return;
            }
            if ((NinjaTrader.Core.Globals.Now - ord.Time).TotalMinutes > LiveOrderTimeoutMinutes)
            {
                try { Account.Cancel(new[] { ord }); } catch { }
                NxV("Ordre d option non rempli apres " + LiveOrderTimeoutMinutes + " min -> annule");
            }
        }

        protected override void NxOnTerminated()
        {
            foreach (KeyValuePair<string, MarketData> kv in liveFeeds)
            {
                EventHandler<MarketDataEventArgs> h;
                if (liveHandlers.TryGetValue(kv.Key, out h)) { try { kv.Value.Update -= h; } catch { } }
            }
            liveFeeds.Clear();
            liveHandlers.Clear();
        }

        // =====================================================================
        //  Rapport
        // =====================================================================
        protected override void NxReportExtras(List<string> lines)
        {
            lines.Add("Mode : " + Mode + " | source de vol : " + VolSource + (VolSource == Nexus11SourceVol.VolRealiseeRatio ? " x" + IvToRvRatio.ToString(CultureInfo.InvariantCulture) : ""));
            foreach (KeyValuePair<string, Wheel> kv in wheels)
            {
                Wheel w = kv.Value;
                lines.Add(string.Format(CultureInfo.InvariantCulture, "{0,-6} etat {1,-9} cycles {2} assignations {3} appels {4} rachats 50% {5} roulements {6} rejets spread {7} capital {8} garde-fou {9} | actions {10}",
                    kv.Key, w.Etat, w.Cycles, w.Assignments, w.CalledAway, w.ProfitTakes, w.Rolls, w.SpreadRejects, w.CapitalRejects, w.GuardBlocks, w.Shares));
            }
            List<NxTradeRecord> opts = ClosedTrades.Where(t => t.Class == NxAssetClass.Option).ToList();
            if (opts.Count > 0)
                lines.Add(string.Format(CultureInfo.InvariantCulture, "Options fermees : {0} | gagnantes {1:P0} | pire trade {2:F2} $ | meilleur {3:F2} $",
                    opts.Count, (double)opts.Count(t => t.NetPnl > 0) / opts.Count, opts.Min(t => t.NetPnl), opts.Max(t => t.NetPnl)));
            // Pire perte mensuelle (metrique principale de la fiche).
            Dictionary<int, double> monthStart = new Dictionary<int, double>(), monthEnd = new Dictionary<int, double>();
            for (int i = 0; i < EquityDays.Count; i++)
            {
                int key = NxCalendar.MonthKey(EquityDays[i]);
                if (!monthStart.ContainsKey(key)) monthStart[key] = i > 0 ? EquityValues[i - 1] : EquityValues[i];
                monthEnd[key] = EquityValues[i];
            }
            if (monthEnd.Count > 0)
            {
                KeyValuePair<int, double> worst = monthEnd.Select(kv => new KeyValuePair<int, double>(kv.Key, kv.Value / monthStart[kv.Key] - 1)).OrderBy(kv => kv.Value).First();
                lines.Add(string.Format(CultureInfo.InvariantCulture, "PIRE PERTE MENSUELLE : {0:P2} ({1}-{2:00}) - le taux de reussite ne dit rien des pertes rares",
                    worst.Value, (worst.Key - 1) / 12, (worst.Key - 1) % 12 + 1));
            }
            lines.Add(string.Format(CultureInfo.InvariantCulture, "Israelov-Nielsen : calls vendus PnL brut {0:F2} $ vs couvert en delta {1:F2} $ | puts brut {2:F2} $ vs couvert {3:F2} $",
                callPnlRaw, callPnlHedged, putPnlRaw, putPnlHedged));
            lines.Add("  (la difference brut - couvert = pari directionnel non remunere ; couvrir cette exposition ameliore le Sharpe selon Israelov-Nielsen)");
            if (ivUsed.Count > 0)
                lines.Add(string.Format(CultureInfo.InvariantCulture, "Prime de variance observee : IV moyenne utilisee {0:P1} vs vol realisee suivante {1:P1} (n={2})", ivUsed.Average(), rvAfter.Average(), ivUsed.Count));
            if (Mode == Nexus11Mode.Synthetique) lines.Add("RAPPEL : backtest SYNTHETIQUE (Black-Scholes, spread modelise) - pas de vraies cotations d options ; valider en SignalSeul / paper.");
        }

        #region Proprietes
        [NinjaScriptProperty]
        [Display(Name = "Mode", Order = 1, GroupName = "01. Fiche 11 - Wheel")]
        public Nexus11Mode Mode { get; set; }

        [NinjaScriptProperty]
        [Range(1, 365)]
        [Display(Name = "Echeance min (jours)", Order = 2, GroupName = "01. Fiche 11 - Wheel")]
        public int DteMin { get; set; }

        [NinjaScriptProperty]
        [Range(1, 365)]
        [Display(Name = "Echeance max (jours)", Order = 3, GroupName = "01. Fiche 11 - Wheel")]
        public int DteMax { get; set; }

        [NinjaScriptProperty]
        [Range(-0.99, -0.01)]
        [Display(Name = "Put : delta vise", Order = 4, GroupName = "01. Fiche 11 - Wheel")]
        public double PutDelta { get; set; }

        [Range(-0.99, -0.01)]
        [Display(Name = "Put : delta min", Order = 5, GroupName = "01. Fiche 11 - Wheel")]
        public double PutDeltaMin { get; set; }

        [Range(-0.99, -0.01)]
        [Display(Name = "Put : delta max", Order = 6, GroupName = "01. Fiche 11 - Wheel")]
        public double PutDeltaMax { get; set; }

        [NinjaScriptProperty]
        [Range(0.01, 0.99)]
        [Display(Name = "Call : delta vise", Order = 7, GroupName = "01. Fiche 11 - Wheel")]
        public double CallDelta { get; set; }

        [Range(0.01, 0.99)]
        [Display(Name = "Call : delta min", Order = 8, GroupName = "01. Fiche 11 - Wheel")]
        public double CallDeltaMin { get; set; }

        [Range(0.01, 0.99)]
        [Display(Name = "Call : delta max", Order = 9, GroupName = "01. Fiche 11 - Wheel")]
        public double CallDeltaMax { get; set; }

        [NinjaScriptProperty]
        [Range(1.0, 100.0)]
        [Display(Name = "Prise de benefice (% de la prime)", Order = 10, GroupName = "01. Fiche 11 - Wheel")]
        public double ProfitTakePct { get; set; }

        [Range(0, 365)]
        [Display(Name = "Gestion a (jours de l echeance)", Order = 11, GroupName = "01. Fiche 11 - Wheel")]
        public int ManageAtDte { get; set; }

        [Display(Name = "Action a 21 jours", Order = 12, GroupName = "01. Fiche 11 - Wheel")]
        public Nexus11A21Jours At21Days { get; set; }

        [Display(Name = "Source de volatilite implicite", Order = 13, GroupName = "01. Fiche 11 - Wheel")]
        public Nexus11SourceVol VolSource { get; set; }

        [Range(0.5, 3.0)]
        [Display(Name = "IV / vol realisee", Description = "19.3 / 15.1 ~ 1.28 (Bondarenko, S&P 500 1990-2018).", Order = 14, GroupName = "01. Fiche 11 - Wheel")]
        public double IvToRvRatio { get; set; }

        [Range(5, 252)]
        [Display(Name = "Vol realisee sur (jours)", Order = 15, GroupName = "01. Fiche 11 - Wheel")]
        public int RvWindowDays { get; set; }

        [Display(Name = "Indices de vol (SYM=INDICE)", Order = 16, GroupName = "01. Fiche 11 - Wheel")]
        public string IvIndexMap { get; set; }

        [Range(0.0, 20.0)]
        [Display(Name = "Taux sans risque (%)", Order = 17, GroupName = "01. Fiche 11 - Wheel")]
        public double RiskFreePct { get; set; }

        [Range(0.0, 20.0)]
        [Display(Name = "Rendement du dividende (%)", Order = 18, GroupName = "01. Fiche 11 - Wheel")]
        public double DividendYieldPct { get; set; }

        [Range(0.0, 100.0)]
        [Display(Name = "Pas de strike (0 = auto)", Order = 19, GroupName = "01. Fiche 11 - Wheel")]
        public double StrikeStep { get; set; }

        [NinjaScriptProperty]
        [Range(0.1, 100.0)]
        [Display(Name = "Filtre 1 : spread max (% du mid)", Order = 20, GroupName = "01. Fiche 11 - Wheel")]
        public double SpreadMaxPct { get; set; }

        [Range(0.0, 100.0)]
        [Display(Name = "Filtre 2 : spread max ($)", Order = 21, GroupName = "01. Fiche 11 - Wheel")]
        public double MaxSpreadAbs { get; set; }

        [Range(0.0, 100.0)]
        [Display(Name = "Filtre 3 : prime min ($)", Order = 22, GroupName = "01. Fiche 11 - Wheel")]
        public double MinPremium { get; set; }

        [Range(0.0, 10.0)]
        [Display(Name = "Spread modelise : fixe ($)", Order = 23, GroupName = "01. Fiche 11 - Wheel")]
        public double ModelSpreadAbs { get; set; }

        [Range(0.0, 100.0)]
        [Display(Name = "Spread modelise : % du mid", Order = 24, GroupName = "01. Fiche 11 - Wheel")]
        public double ModelSpreadPct { get; set; }

        [Range(0.0, 100.0)]
        [Display(Name = "Glissement (% du demi-spread)", Order = 25, GroupName = "01. Fiche 11 - Wheel")]
        public double FillPenaltyPct { get; set; }

        [Range(0.0, 100.0)]
        [Display(Name = "Frais par contrat ($)", Order = 26, GroupName = "01. Fiche 11 - Wheel")]
        public double FeePerContract { get; set; }

        [Range(1.0, 100.0)]
        [Display(Name = "Collateral max par sous-jacent (%)", Order = 27, GroupName = "01. Fiche 11 - Wheel")]
        public double MaxAllocationPct { get; set; }

        [Range(1, 1000)]
        [Display(Name = "Contrats max", Order = 28, GroupName = "01. Fiche 11 - Wheel")]
        public int MaxContracts { get; set; }

        [Display(Name = "Prix de revient ajuste des primes", Order = 29, GroupName = "01. Fiche 11 - Wheel")]
        public bool UseAdjustedCostBasis { get; set; }

        [Display(Name = "Jambe action en ordres NT", Description = "Acheter/vendre reellement les actions a l assignation/l appel (sinon suivi synthetique).", Order = 30, GroupName = "01. Fiche 11 - Wheel")]
        public bool ExecuteStockLeg { get; set; }

        [Display(Name = "Format du nom d option (CompteNT)", Description = "Jetons : {SYM} {YYYY} {YY} {MM} {DD} {STRIKE} {CP} {CALLPUT}.", Order = 31, GroupName = "01. Fiche 11 - Wheel")]
        public string OptionNameFormat { get; set; }

        [Range(1, 1440)]
        [Display(Name = "Delai max ordre d option (min)", Order = 32, GroupName = "01. Fiche 11 - Wheel")]
        public int LiveOrderTimeoutMinutes { get; set; }
        #endregion
    }
}
