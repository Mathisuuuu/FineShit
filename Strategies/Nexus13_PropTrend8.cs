// =============================================================================
//  Nexus13_PropTrend8.cs   (NinjaTrader 8 / NinjaScript)
//
//  FICHE 13 - Trend 8 actifs 24/5 pour comptes "prop" (Affectionate-Rip-568)
//  Strategie proposee : suivi de tendance multi-horizons [SSRN] Hurst, Ooi,
//  Pedersen (A Century of Evidence on Trend-Following Investing).
//
//  PIPELINE [Fil] transpose dans NinjaTrader :
//   1. Signal genere (ici : par la strategie, plus par TradingView)
//   2. Verification par Claude : VETO SEULEMENT (banque centrale, chiffre macro
//      dans l heure) - agenda Nexus\data\macro_events.csv
//   3. Filtre personnalise : regles prop codees en dur + garde-fous
//   4. Relais webhook (JSON signe X-Nexus-Secret) vers un service externe
//   5. Copie des trades vers d autres comptes NinjaTrader (comptes miroirs)
//   + INTERRUPTEUR GLOBAL (fichier Nexus\KILL_SWITCH) : un bug copie vers
//     plusieurs comptes est multiplie par le nombre de comptes.
//
//  REGLES
//   - Actifs : EURUSD, GBPUSD, USDJPY, AUDUSD, XAUUSD, US500, NAS100, GER40
//     (noms a adapter au fournisseur ; futures micro possibles, cf. LISEZMOI).
//   - Signal : moyenne des signes des rendements 1, 3 et 12 mois ;
//     long si > 0, court si < 0 (CFD et futures autorisent la vente).
//   - Taille : volatilite cible egale par actif ; risque max 0.5 % du compte
//     par position (stop ATR x3) ; position = taille pleine x |moyenne|.
//   - Recalcul quotidien a la cloture de la seance de New York (barres
//     journalieres des modeles forex/CME : fin de seance 17:00 ET).
//   - Regles prop codees en dur : perte journaliere max ~5 % et drawdown max
//     ~10 % (A VERIFIER chez la firme) ; statique ou suiveur ; marge de
//     securite (entrees bloquees a 80 % de la limite) ; depassement =>
//     tout fermer, arreter, et (option) activer l interrupteur global.
//
//  Points d attention : la tendance pure ne gagne qu une minorite de trades ;
//  les regles de drawdown peuvent couper le compte avant la tendance gagnante.
//  L auteur ne donne aucun chiffre de performance.
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
    public enum Nexus13Veto { Aucun, Regles, Claude, ReglesPuisClaude }
    public enum Nexus13Drawdown { Statique, Suiveur }

    public class Nexus13PropTrend8 : NexusStrategyBase
    {
        private Dictionary<string, int> lotMap;
        private Dictionary<string, string> ccyMap;
        private List<int> horizons;
        private NxMacroCalendar macro;
        private NxLlmConfig claude;
        private NxLlmCache cache;
        private bool propHalted;
        private string haltReason = "";
        private DateTime propDay = DateTime.MinValue;
        private double propDayStart = double.NaN, propPeak = double.NaN;
        private double worstDailyLoss, worstDrawdown;
        private int nearBreachDays, vetoes, vetoChecks, signalChanges;
        private DateTime lastNearBreachDay = DateTime.MinValue;

        protected override void NxSetDefaults()
        {
            Name = "Nexus13_PropTrend8";
            Description = "Fiche 13 - Tendance 1/3/12 mois sur 8 actifs 24/5 (long/court), vol cible egale, risque 0.5 %/position, regles prop codees en dur, veto macro (Claude), webhook, comptes miroirs, interrupteur global.";
            Symbols = "EURUSD,GBPUSD,USDJPY,AUDUSD,XAUUSD,US500,NAS100,GER40";
            AllowShortSelling = true;
            SizingMode = NxSizingMode.Natif;
            MaxTradePct = 0; MaxSymbolPct = 0; MaxClassPct = 0; MaxTotalPct = 0;
            UseCorrelationDivisor = false;
            InitialBankroll = 100000;
            DrawdownTripPct = 8.0;
            DailyLossPct = 4.0;

            HorizonDays = "21,63,252";
            TargetVolPerAssetPct = 10.0;
            VolWindowDays = 60;
            MaxRiskPerPositionPct = 0.5;
            AtrMultiplier = 3.0;
            RebalanceThresholdPct = 25.0;
            LotSizes = "EURUSD=1000;GBPUSD=1000;USDJPY=1000;AUDUSD=1000;XAUUSD=1;US500=1;NAS100=1;GER40=1";
            CurrencyMap = "XAUUSD=USD;US500=USD;NAS100=USD;GER40=EUR";
            PropDailyLossPct = 5.0;
            PropMaxDrawdownPct = 10.0;
            PropDrawdownType = Nexus13Drawdown.Statique;
            PropBufferPct = 80.0;
            PropBreachActivatesKillSwitch = true;
            VetoMode = Nexus13Veto.Regles;
            MacroFile = "macro_events.csv";
            VetoWindowMinutes = 60;
            VetoMinImpact = 3;
            ClaudeModel = "claude-opus-5-5";
            ClaudeApiKey = "";
            VetoConfidence = 0.7;
            ApiCallsInBacktest = false;
            WebhookUrl = "";
            WebhookSecret = "";
            MirrorAccounts = "";
            MirrorRatio = 1.0;
        }

        protected override bool NxBatchMode { get { return false; } }

        protected override void NxDataLoaded()
        {
            lotMap = NxText.ParseMap(LotSizes).ToDictionary(kv => kv.Key, kv => Math.Max(1, (int)NxCsv.ParseDouble(kv.Value)), StringComparer.OrdinalIgnoreCase);
            ccyMap = NxText.ParseMap(CurrencyMap);
            horizons = NxText.SplitList(HorizonDays).Select(x => (int)NxCsv.ParseDouble(x)).Where(x => x > 0).ToList();
            macro = new NxMacroCalendar();
            string msg;
            macro.Load(NxPaths.Resolve(MacroFile, NxPaths.Data), out msg);
            Nx("Agenda macro : " + msg);
            claude = new NxLlmConfig
            {
                Provider = NxLlmProvider.Claude, Model = ClaudeModel, ApiKey = NxSecrets.Resolve(ClaudeApiKey, "ANTHROPIC_API_KEY"),
                Temperature = 0.0, MaxTokens = 300, TimeoutSec = 30
            };
            cache = NxLlmCache.Get(Path.Combine(NxPaths.Cache, "llm_cache.tsv"));
            propPeak = InitialBankroll;
            Nx(string.Format(CultureInfo.InvariantCulture, "Regles prop : perte jour max {0:F1} %, drawdown max {1:F1} % ({2}), marge {3:F0} % - A VERIFIER chez la firme.",
                PropDailyLossPct, PropMaxDrawdownPct, PropDrawdownType, PropBufferPct));
        }

        private int Lot(NxSym s) { int l; return lotMap.TryGetValue(s.Name, out l) ? l : Math.Max(1, LotSize); }

        private List<string> CurrenciesOf(NxSym s)
        {
            List<string> c = new List<string> { "USD" };
            string m;
            if (ccyMap.TryGetValue(s.Name, out m)) c.AddRange(NxText.SplitList(m.Replace('/', ',')));
            else if (s.Name.Length == 6 && s.Name.All(char.IsLetter)) { c.Add(s.Name.Substring(0, 3).ToUpperInvariant()); c.Add(s.Name.Substring(3, 3).ToUpperInvariant()); }
            return c.Distinct().ToList();
        }

        // =====================================================================
        //  Regles prop
        // =====================================================================
        private void PropCheck(DateTime day)
        {
            double eq = Equity;
            if (day > propDay) { propDay = day; propDayStart = eq; }
            if (eq > propPeak) propPeak = eq;
            double ddRef = PropDrawdownType == Nexus13Drawdown.Statique ? InitialBankroll : propPeak;
            double dailyLoss = propDayStart > 0 ? Math.Max(0, 1 - eq / propDayStart) : 0;
            double dd = ddRef > 0 ? Math.Max(0, 1 - eq / ddRef) : 0;
            worstDailyLoss = Math.Max(worstDailyLoss, dailyLoss);
            worstDrawdown = Math.Max(worstDrawdown, dd);
            if ((dailyLoss >= PropDailyLossPct / 100.0 * PropBufferPct / 100.0 || dd >= PropMaxDrawdownPct / 100.0 * PropBufferPct / 100.0) && day != lastNearBreachDay)
            { nearBreachDays++; lastNearBreachDay = day; }
            if (propHalted) return;
            string why = null;
            if (dailyLoss >= PropDailyLossPct / 100.0) why = string.Format(CultureInfo.InvariantCulture, "perte du jour {0:P2} >= limite {1:F1} %", dailyLoss, PropDailyLossPct);
            else if (dd >= PropMaxDrawdownPct / 100.0) why = string.Format(CultureInfo.InvariantCulture, "drawdown {0} {1:P2} >= limite {2:F1} %", PropDrawdownType, dd, PropMaxDrawdownPct);
            if (why == null) return;
            propHalted = true;
            haltReason = why;
            NxAlert("REGLE PROP DEPASSEE : " + why + " -> fermeture de tout et arret");
            FlatAll("regle prop : " + why);
            if (State == State.Realtime && PropBreachActivatesKillSwitch) NxKillSwitch.Activate(StrategyId + " : " + why);
        }

        protected override bool NxAllowIncrease(NxSym s, out string reason)
        {
            reason = null;
            if (propHalted) { reason = "strategie arretee (regle prop : " + haltReason + ")"; return false; }
            double eq = Equity;
            double ddRef = PropDrawdownType == Nexus13Drawdown.Statique ? InitialBankroll : propPeak;
            double dailyLoss = propDayStart > 0 ? 1 - eq / propDayStart : 0;
            double dd = ddRef > 0 ? 1 - eq / ddRef : 0;
            if (dailyLoss >= PropDailyLossPct / 100.0 * PropBufferPct / 100.0) { reason = string.Format(CultureInfo.InvariantCulture, "marge prop : perte du jour {0:P2} >= {1:F0} % de la limite", dailyLoss, PropBufferPct); return false; }
            if (dd >= PropMaxDrawdownPct / 100.0 * PropBufferPct / 100.0) { reason = string.Format(CultureInfo.InvariantCulture, "marge prop : drawdown {0:P2} >= {1:F0} % de la limite", dd, PropBufferPct); return false; }
            return true;
        }

        protected override void NxOnTimer()
        {
            // Temps reel : surveillance continue des limites prop (equity marquee toutes les 5 s par le socle).
            DateTime day = NinjaTrader.Core.Globals.Now.Date;
            PropCheck(day > propDay ? propDay : day);
        }

        // =====================================================================
        //  Signal et taille
        // =====================================================================
        protected override void NxOnSymbolBar(NxSym s, DateTime day)
        {
            if (!s.Traded) return;
            PropCheck(day);
            NxBarHistory h = s.Hist;
            int maxH = horizons.Count > 0 ? horizons.Max() : 252;
            if (h.Count < Math.Max(maxH, VolWindowDays) + 2 || propHalted) return;

            double sum = 0; int n = 0;
            foreach (int hd in horizons) { double r = h.ReturnOver(hd, 0); if (NxMath.Ok(r)) { sum += Math.Sign(r); n++; } }
            if (n == 0) return;
            double avg = sum / n;

            double price = h.LastClose, vpp = ValuePerPoint(s), vol = h.RealizedVol(VolWindowDays), atr = h.Atr;
            if (!NxMath.Ok(vol) || vol <= 0 || !NxMath.Ok(atr) || atr <= 0 || vpp <= 0) return;
            double eq = Bankroll();
            double unitsVol = TargetVolPerAssetPct / 100.0 / vol * eq / (price * vpp);
            double dist = atr * AtrMultiplier;
            double unitsRisk = MaxRiskPerPositionPct / 100.0 * eq / (dist * vpp);
            int lot = Lot(s);
            int q = (int)Math.Floor(Math.Min(unitsVol, unitsRisk) * Math.Abs(avg) / lot) * lot;
            int target = Math.Sign(avg) * q;
            int cur = s.TargetQty;
            bool change = Math.Sign(target) != Math.Sign(cur) || (cur != 0 && Math.Abs(target - cur) > RebalanceThresholdPct / 100.0 * Math.Abs(cur));
            if (!change) return;
            bool increase = Math.Abs(target) > Math.Abs(cur) || Math.Sign(target) != Math.Sign(cur);
            if (increase && target != 0)
            {
                string vr;
                if (MacroVeto(s, Math.Sign(target), out vr))
                {
                    vetoes++;
                    NxSignal(NowNt, s.Name, "veto_macro", vr);
                    Nx("Veto macro " + s.Name + " : " + vr);
                    if (Math.Sign(cur) != Math.Sign(target) && cur != 0) target = 0; else return;
                }
            }
            double stop = target > 0 ? price - dist : (target < 0 ? price + dist : double.NaN);
            string why = string.Format(CultureInfo.InvariantCulture, "tendance {0:+0.00;-0.00} (1/3/12 mois) vol {1:P1} -> {2} unites (risque {3:P2})",
                avg, vol, target, target != 0 ? Math.Abs(target) * dist * vpp / eq : 0);
            SetTarget(s, target, stop, why);
            signalChanges++;
            if (State == State.Realtime) Relay(s, cur, target, stop, why);
        }

        private bool MacroVeto(NxSym s, int direction, out string reason)
        {
            reason = null;
            if (VetoMode == Nexus13Veto.Aucun) return false;
            vetoChecks++;
            DateTime nowUtc = State == State.Realtime ? DateTime.UtcNow : NxTime.NtToUtc(s.Hist.LastTime);
            List<NxMacroEvent> ev = macro.Near(CurrenciesOf(s), nowUtc, 0, VetoWindowMinutes, VetoMinImpact);
            if (VetoMode == Nexus13Veto.Regles)
            {
                if (ev.Count == 0) return false;
                reason = "evenement(s) dans l heure : " + string.Join(" ; ", ev.Select(e => e.ToString()));
                return true;
            }
            if (VetoMode == Nexus13Veto.ReglesPuisClaude && ev.Count == 0) return false;
            // Claude : veto seulement (jamais de creation de trade).
            string user = NxPrompts.MacroUser(s.Name, direction, nowUtc, ev);
            string cached;
            NxLlmResult r;
            if (cache.TryGet(NxLlm.CacheKey(claude, NxPrompts.MacroSystem, user, NxPrompts.Version), out cached)) r = new NxLlmResult { Ok = true, Text = cached, FromCache = true };
            else if (State != State.Realtime && !ApiCallsInBacktest) r = new NxLlmResult { Ok = false, Error = "API desactivee en backtest" };
            else
            {
                r = NxLlm.Complete(claude, NxPrompts.MacroSystem, user, cache, NxPrompts.Version);
                NxAiLedger.Record(StrategyId, claude, r, "fiche13_veto_macro", !IsOptimizing);
            }
            bool veto; string why; double conf;
            if (r.Ok && NxPrompts.ParseJudge(r.Text, out veto, out why, out conf))
            {
                if (veto && conf >= VetoConfidence) { reason = "Claude : " + why + string.Format(CultureInfo.InvariantCulture, " (confiance {0:F2})", conf); return true; }
                return false;
            }
            // Sans reponse : repli sur la regle (prudence prop).
            if (ev.Count > 0) { reason = "repli regle (Claude indisponible : " + r.Error + ") : " + string.Join(" ; ", ev.Select(e => e.ToString())); return true; }
            return false;
        }

        // =====================================================================
        //  Webhook et comptes miroirs
        // =====================================================================
        private void Relay(NxSym s, int from, int to, double stop, string why)
        {
            if (string.IsNullOrWhiteSpace(WebhookUrl)) return;
            if (UseKillSwitch && NxKillSwitch.IsActive()) return;
            string json = "{\"strategy\":" + NxJson.Q(StrategyId) + ",\"account\":" + NxJson.Q(Account != null ? Account.Name : "")
                        + ",\"symbol\":" + NxJson.Q(s.Name) + ",\"from\":" + from + ",\"to\":" + to + ",\"stop\":" + NxJson.N(stop)
                        + ",\"reason\":" + NxJson.Q(why) + ",\"time_utc\":" + NxJson.Q(DateTime.UtcNow.ToString("o")) + "}";
            NxWebhook.PostAsync(WebhookUrl, NxSecrets.Resolve(WebhookSecret, "NEXUS_WEBHOOK_SECRET"), json, null);
        }

        protected override void NxOnFill(NxSym s, int signedQty, double price, DateTime time)
        {
            if (State != State.Realtime || string.IsNullOrWhiteSpace(MirrorAccounts) || signedQty == 0) return;
            bool kill = UseKillSwitch && NxKillSwitch.IsActive();
            foreach (string name in NxText.SplitList(MirrorAccounts))
            {
                Account acc = null;
                try { lock (Account.All) acc = Account.All.FirstOrDefault(a => string.Equals(a.Name, name, StringComparison.OrdinalIgnoreCase)); } catch { }
                if (acc == null) { NxOnce("mir" + name, "Compte miroir introuvable : " + name); continue; }
                if (Account != null && acc.Name == Account.Name) continue;
                int lot = Lot(s);
                int q = (int)Math.Floor(Math.Abs(signedQty) * MirrorRatio / lot) * lot;
                if (q <= 0) continue;
                int mirrorPos = 0;
                try
                {
                    Position p;
                    lock (acc.Positions) p = acc.Positions.FirstOrDefault(x => x.Instrument != null && x.Instrument.FullName == s.Instrument.FullName);
                    if (p != null) mirrorPos = p.MarketPosition == MarketPosition.Long ? p.Quantity : (p.MarketPosition == MarketPosition.Short ? -p.Quantity : 0);
                }
                catch { }
                bool increasing = Math.Sign(signedQty) != -Math.Sign(mirrorPos) || mirrorPos == 0;
                if (kill && increasing) { NxV("Miroir " + name + " ignore (interrupteur global)"); continue; }
                OrderAction act = signedQty > 0 ? (mirrorPos < 0 ? OrderAction.BuyToCover : OrderAction.Buy) : (mirrorPos > 0 ? OrderAction.Sell : OrderAction.SellShort);
                if (signedQty > 0 && mirrorPos < 0) q = Math.Min(q, -mirrorPos);
                if (signedQty < 0 && mirrorPos > 0) q = Math.Min(q, mirrorPos);
                try
                {
                    Order o = acc.CreateOrder(s.Instrument, act, OrderType.Market, OrderEntry.Automated, TimeInForce.Gtc, q, 0, 0, "", "NxMirror_" + s.Name,
                                              NinjaTrader.Core.Globals.MaxDate, null);
                    acc.Submit(new[] { o });
                    Nx(string.Format(CultureInfo.InvariantCulture, "Miroir {0} : {1} {2} x{3}", name, act, s.Name, q));
                }
                catch (Exception ex) { NxAlert("Echec de copie vers " + name + " : " + ex.Message); }
            }
        }

        protected override void NxReportExtras(List<string> lines)
        {
            lines.Add(string.Format(CultureInfo.InvariantCulture, "Prop : pire perte journaliere {0:P2} (limite {1:F1} %) | drawdown max {2:P2} ({3}, limite {4:F1} %) | jours en marge de securite {5}{6}",
                worstDailyLoss, PropDailyLossPct, worstDrawdown, PropDrawdownType, PropMaxDrawdownPct, nearBreachDays, propHalted ? " | COMPTE ARRETE : " + haltReason : ""));
            lines.Add(string.Format(CultureInfo.InvariantCulture, "Changements de position : {0} | controles de veto : {1} | vetos : {2} (mode {3})", signalChanges, vetoChecks, vetoes, VetoMode));
            if (ClosedTrades.Count > 0)
                lines.Add(string.Format(CultureInfo.InvariantCulture, "Taux de reussite {0:P0} : la tendance pure gagne une minorite de trades ; c'est le ratio gain/perte qui compte.",
                    (double)ClosedTrades.Count(t => t.NetPnl > 0) / ClosedTrades.Count));
            lines.Add("Rappel : regles prop typiques ~5 %/jour et ~10 % de drawdown - verifier les chiffres exacts de la firme.");
        }

        #region Proprietes
        [NinjaScriptProperty]
        [Display(Name = "Horizons (jours)", Description = "1, 3 et 12 mois = 21, 63, 252.", Order = 1, GroupName = "01. Fiche 13 - Tendance prop")]
        public string HorizonDays { get; set; }

        [NinjaScriptProperty]
        [Range(0.5, 100.0)]
        [Display(Name = "Vol cible par actif (%/an)", Order = 2, GroupName = "01. Fiche 13 - Tendance prop")]
        public double TargetVolPerAssetPct { get; set; }

        [Range(10, 500)]
        [Display(Name = "Fenetre de vol (jours)", Order = 3, GroupName = "01. Fiche 13 - Tendance prop")]
        public int VolWindowDays { get; set; }

        [NinjaScriptProperty]
        [Range(0.01, 10.0)]
        [Display(Name = "Risque max par position (%)", Order = 4, GroupName = "01. Fiche 13 - Tendance prop")]
        public double MaxRiskPerPositionPct { get; set; }

        [Range(0.5, 20.0)]
        [Display(Name = "Stop : multiplicateur ATR(14)", Order = 5, GroupName = "01. Fiche 13 - Tendance prop")]
        public double AtrMultiplier { get; set; }

        [Range(1.0, 100.0)]
        [Display(Name = "Seuil de reequilibrage (%)", Order = 6, GroupName = "01. Fiche 13 - Tendance prop")]
        public double RebalanceThresholdPct { get; set; }

        [Display(Name = "Tailles de lot (SYM=lot)", Order = 7, GroupName = "01. Fiche 13 - Tendance prop")]
        public string LotSizes { get; set; }

        [Display(Name = "Devises des indices/or (SYM=DEV)", Order = 8, GroupName = "01. Fiche 13 - Tendance prop")]
        public string CurrencyMap { get; set; }

        [NinjaScriptProperty]
        [Range(0.1, 100.0)]
        [Display(Name = "Prop : perte journaliere max (%)", Order = 9, GroupName = "02. Regles prop")]
        public double PropDailyLossPct { get; set; }

        [NinjaScriptProperty]
        [Range(0.1, 100.0)]
        [Display(Name = "Prop : drawdown max (%)", Order = 10, GroupName = "02. Regles prop")]
        public double PropMaxDrawdownPct { get; set; }

        [Display(Name = "Prop : type de drawdown", Order = 11, GroupName = "02. Regles prop")]
        public Nexus13Drawdown PropDrawdownType { get; set; }

        [Range(10.0, 100.0)]
        [Display(Name = "Prop : marge (% de la limite)", Description = "Entrees bloquees au-dela de cette part de la limite.", Order = 12, GroupName = "02. Regles prop")]
        public double PropBufferPct { get; set; }

        [Display(Name = "Prop : depassement active l interrupteur", Order = 13, GroupName = "02. Regles prop")]
        public bool PropBreachActivatesKillSwitch { get; set; }

        [NinjaScriptProperty]
        [Display(Name = "Veto macro", Order = 14, GroupName = "03. Veto, webhook, miroirs")]
        public Nexus13Veto VetoMode { get; set; }

        [Display(Name = "Agenda macro (CSV)", Description = "datetime_utc,currency,impact,title (Nexus\\data).", Order = 15, GroupName = "03. Veto, webhook, miroirs")]
        public string MacroFile { get; set; }

        [Range(1, 1440)]
        [Display(Name = "Fenetre du veto (min)", Order = 16, GroupName = "03. Veto, webhook, miroirs")]
        public int VetoWindowMinutes { get; set; }

        [Range(1, 3)]
        [Display(Name = "Impact minimum (1-3)", Order = 17, GroupName = "03. Veto, webhook, miroirs")]
        public int VetoMinImpact { get; set; }

        [Display(Name = "Claude : modele", Order = 18, GroupName = "03. Veto, webhook, miroirs")]
        public string ClaudeModel { get; set; }

        [Display(Name = "Claude : cle (vide = ANTHROPIC_API_KEY)", Order = 19, GroupName = "03. Veto, webhook, miroirs")]
        public string ClaudeApiKey { get; set; }

        [Range(0.0, 1.0)]
        [Display(Name = "Claude : confiance min du veto", Order = 20, GroupName = "03. Veto, webhook, miroirs")]
        public double VetoConfidence { get; set; }

        [Display(Name = "Claude : appels en backtest", Order = 21, GroupName = "03. Veto, webhook, miroirs")]
        public bool ApiCallsInBacktest { get; set; }

        [Display(Name = "Webhook : URL (vide = desactive)", Order = 22, GroupName = "03. Veto, webhook, miroirs")]
        public string WebhookUrl { get; set; }

        [Display(Name = "Webhook : secret", Description = "Vide = variable NEXUS_WEBHOOK_SECRET.", Order = 23, GroupName = "03. Veto, webhook, miroirs")]
        public string WebhookSecret { get; set; }

        [Display(Name = "Comptes miroirs", Description = "Noms de comptes NinjaTrader separes par des virgules (vide = aucun).", Order = 24, GroupName = "03. Veto, webhook, miroirs")]
        public string MirrorAccounts { get; set; }

        [Range(0.01, 100.0)]
        [Display(Name = "Ratio de copie", Order = 25, GroupName = "03. Veto, webhook, miroirs")]
        public double MirrorRatio { get; set; }
        #endregion
    }
}
