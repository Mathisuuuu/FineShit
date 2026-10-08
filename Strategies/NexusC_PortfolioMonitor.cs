// =============================================================================
//  NexusC_PortfolioMonitor.cs   (NinjaTrader 8 / NinjaScript)
//
//  MODULES B + C - Moniteur de portefeuille multi-strategies. N envoie AUCUN
//  ordre ; l appliquer sur n importe quel graphique (ex. SPY journalier).
//
//  Il lit les journaux ecrits par les strategies Nexus (Nexus\journal) et
//  produit un rapport consolide (Output + Nexus\reports\PortfolioMonitor_*.txt) :
//   - matrice de correlation des rendements journaliers des strategies, a
//     recalculer CHAQUE SEMAINE (module B, Bluppy2947) : alerte si >= 0.30
//   - seuils avant passage en reel (consensus du fil) : 1 000 trades resolus
//     au total, 30 trades fermes ET un cycle drawdown -> recuperation par
//     strategie, frais modelises et PnL positif, remplissages reels compares
//     au paper (glissement moyen)
//   - DSR multi-essais et PBO (CSCV) de chaque strategie a partir des
//     rendements sauvegardes par configuration (option "Sauver rendements
//     pour PBO" + optimisation dans le Strategy Analyzer)
//   - cout des API IA par strategie rapporte a son PnL
//   - etat de l interrupteur global ; propriete pour l activer / le desactiver
//  En temps reel, le rapport est regenere toutes les N heures (168 = hebdo).
// =============================================================================

#region Using declarations
using System;
using System.Collections.Generic;
using System.ComponentModel.DataAnnotations;
using System.Globalization;
using System.IO;
using System.Linq;
using System.Text;
using System.Threading;
using NinjaTrader.Cbi;
using NinjaTrader.Data;
using NinjaTrader.NinjaScript;
using NinjaTrader.NinjaScript.AddOns.Nexus;
#endregion

namespace NinjaTrader.NinjaScript.Strategies
{
    public enum NxKillAction { Aucune, Activer, Desactiver }

    public class NexusC_PortfolioMonitor : Strategy
    {
        private Timer timer;
        private int busy;

        protected override void OnStateChange()
        {
            if (State == State.SetDefaults)
            {
                Name = "NexusC_PortfolioMonitor";
                Description = "Modules B+C - Rapport consolide des strategies Nexus : correlation hebdomadaire, seuils avant le reel, DSR/PBO, cout IA vs PnL, interrupteur global. Aucun ordre.";
                Calculate = Calculate.OnBarClose;
                IsOverlay = true;
                BarsRequiredToTrade = 1;
                IsInstantiatedOnEachOptimizationIteration = true;

                CorrelationWindow = 120;
                ReportEveryHours = 168;
                KillSwitch = NxKillAction.Aucune;
                MinTradesPerStrategy = 30;
                TotalTradesThreshold = 1000;
                MinDrawdownForCycle = 5.0;
            }
            else if (State == State.DataLoaded)
            {
                NxPaths.EnsureAll();
                if (KillSwitch == NxKillAction.Activer) { NxKillSwitch.Activate("NexusC_PortfolioMonitor"); Print("[NexusC] INTERRUPTEUR GLOBAL ACTIVE : " + NxPaths.KillSwitchFile); }
                else if (KillSwitch == NxKillAction.Desactiver)
                {
                    try { if (File.Exists(NxPaths.KillSwitchFile)) File.Delete(NxPaths.KillSwitchFile); Print("[NexusC] Interrupteur global desactive."); }
                    catch (Exception ex) { Print("[NexusC] Impossible de supprimer " + NxPaths.KillSwitchFile + " : " + ex.Message); }
                }
                if (Category != Category.Optimize && Category != Category.WalkForward && Category != Category.WalkForwardAnchored && Category != Category.MultiObjective)
                    Publish();
            }
            else if (State == State.Realtime)
            {
                int ms = Math.Max(1, ReportEveryHours) * 3600 * 1000;
                timer = new Timer(o =>
                {
                    if (Interlocked.Exchange(ref busy, 1) == 1) return;
                    try { TriggerCustomEvent(x => Publish(), null); } catch { }
                    finally { Interlocked.Exchange(ref busy, 0); }
                }, null, ms, ms);
            }
            else if (State == State.Terminated)
            {
                try { if (timer != null) { timer.Dispose(); timer = null; } } catch { }
            }
        }

        protected override void OnBarUpdate() { }

        private void Publish()
        {
            string txt;
            try { txt = BuildReport(); }
            catch (Exception ex) { txt = "[NexusC] Erreur de rapport : " + ex.Message; }
            Print(txt);
            string path = Path.Combine(NxPaths.Reports, "PortfolioMonitor_" + DateTime.Now.ToString("yyyyMMdd_HHmmss", CultureInfo.InvariantCulture) + ".txt");
            NxCsv.WriteAll(path, txt);
            Print("[NexusC] Rapport ecrit : " + path);
        }

        private class StratInfo
        {
            public string Name;
            public int Trades, RealTrades, Wins;
            public double Net, Costs;
            public double MaxDd = double.NaN, Deepest;
            public bool Cycle;
            public int RealFills;
            public double Slip = double.NaN;
            public double AiCost;
            public long AiCalls;
            public int Configs;
            public double Pbo = double.NaN, Dsr = double.NaN;
        }

        private string BuildReport()
        {
            CultureInfo ci = CultureInfo.InvariantCulture;
            StringBuilder sb = new StringBuilder();
            string line = new string('=', 100);
            sb.AppendLine(line);
            sb.AppendLine(" NEXUS - MONITEUR DE PORTEFEUILLE (modules B et C)   " + DateTime.Now.ToString("yyyy-MM-dd HH:mm", ci));
            sb.AppendLine(" Dossier : " + NxPaths.Root);
            sb.AppendLine(" Interrupteur global : " + (NxKillSwitch.IsActive() ? "ACTIF (" + NxPaths.KillSwitchFile + ")" : "inactif"));
            sb.AppendLine(line);

            Dictionary<string, StratInfo> map = new Dictionary<string, StratInfo>(StringComparer.OrdinalIgnoreCase);
            Func<string, StratInfo> get = n => { StratInfo s; if (!map.TryGetValue(n, out s)) { s = new StratInfo { Name = n }; map[n] = s; } return s; };

            if (Directory.Exists(NxPaths.Journal))
            {
                foreach (string f in Directory.GetFiles(NxPaths.Journal, "trades_*.csv"))
                {
                    StratInfo si = get(Path.GetFileNameWithoutExtension(f).Substring(7));
                    string[] h;
                    List<string[]> rows = NxCsv.ReadRows(f, out h);
                    int cn = NxCsv.Col(h, "net_pnl"), cc = NxCsv.Col(h, "costs"), cr = NxCsv.Col(h, "real_money");
                    foreach (string[] r in rows)
                    {
                        double n = NxCsv.ParseDouble(NxCsv.Get(r, cn));
                        if (!NxMath.Ok(n)) continue;
                        si.Trades++; si.Net += n; if (n > 0) si.Wins++;
                        double c = NxCsv.ParseDouble(NxCsv.Get(r, cc)); if (NxMath.Ok(c)) si.Costs += c;
                        if (NxCsv.Get(r, cr) == "1") si.RealTrades++;
                    }
                }
                foreach (string f in Directory.GetFiles(NxPaths.Journal, "returns_*.csv"))
                {
                    StratInfo si = get(Path.GetFileNameWithoutExtension(f).Substring(8));
                    string[] h;
                    List<string[]> rows = NxCsv.ReadRows(f, out h);
                    int ce = NxCsv.Col(h, "equity");
                    List<double> eq = rows.Select(r => NxCsv.ParseDouble(NxCsv.Get(r, ce))).Where(NxMath.Ok).ToList();
                    if (eq.Count < 2) continue;
                    si.MaxDd = NxValidation.MaxDrawdown(eq);
                    int bars;
                    si.Cycle = NxValidation.HasDrawdownRecoveryCycle(eq, MinDrawdownForCycle / 100.0, out si.Deepest, out bars);
                }
                foreach (string f in Directory.GetFiles(NxPaths.Journal, "fills_*.csv"))
                {
                    StratInfo si = get(Path.GetFileNameWithoutExtension(f).Substring(6));
                    NxJournal.RealFillSlippage(f, out si.RealFills, out si.Slip);
                }
                string[] ah;
                foreach (string[] r in NxCsv.ReadRows(NxAiLedger.FilePath, out ah))
                {
                    string strat = NxCsv.Get(r, NxCsv.Col(ah, "strategy"));
                    if (string.IsNullOrEmpty(strat)) continue;
                    StratInfo si = get(strat);
                    double c = NxCsv.ParseDouble(NxCsv.Get(r, NxCsv.Col(ah, "cost_usd")));
                    if (NxMath.Ok(c)) si.AiCost += c;
                    si.AiCalls++;
                }
            }
            if (Directory.Exists(NxPaths.Returns))
                foreach (string d in Directory.GetDirectories(NxPaths.Returns))
                {
                    string name = Path.GetFileName(d);
                    int n; double varSr;
                    List<double[]> conf = NxTrialStore.LoadAligned(name, out n, out varSr);
                    if (n == 0) continue;
                    StratInfo si = get(name);
                    si.Configs = n;
                    if (conf.Count >= 2) { int combos; si.Pbo = NxValidation.Pbo(conf, 16, 2000, 11, out combos); }
                    if (conf.Count >= 1)
                    {
                        double[] best = conf.OrderByDescending(x => NxValidation.SharpePerPeriod(x)).First();
                        double sr0;
                        si.Dsr = NxValidation.DeflatedSharpe(best, n, varSr, out sr0);
                    }
                }

            sb.AppendLine(string.Format(ci, "{0,-34}{1,8}{2,7}{3,8}{4,12}{5,10}{6,9}{7,7}{8,9}{9,10}{10,8}{11,8}",
                "Strategie", "Trades", "Reels", "Reuss.", "PnL net", "Couts", "DD max", "Cycle", "IA $", "Fills r.", "PBO", "DSR"));
            int total = 0;
            foreach (StratInfo s in map.Values.OrderBy(x => x.Name))
            {
                total += s.Trades;
                sb.AppendLine(string.Format(ci, "{0,-34}{1,8}{2,7}{3,8:P0}{4,12:F2}{5,10:F2}{6,9:P1}{7,7}{8,9:F2}{9,10}{10,8:P0}{11,8:P0}",
                    s.Name.Length > 33 ? s.Name.Substring(0, 33) : s.Name, s.Trades, s.RealTrades, s.Trades > 0 ? (double)s.Wins / s.Trades : 0, s.Net, s.Costs,
                    s.MaxDd, s.Cycle ? "oui" : "non", s.AiCost, s.RealFills, s.Pbo, s.Dsr));
            }
            if (map.Count == 0) sb.AppendLine("  (aucun journal : activer 'Journal CSV' sur les strategies, mode TempsReelSeulement ou Toujours)");
            sb.AppendLine();

            sb.AppendLine("--- Seuils avant passage en reel ---");
            sb.AppendLine((total >= TotalTradesThreshold ? "[x] " : "[ ] ") + string.Format(ci, "au moins {0} trades resolus au total : {1}", TotalTradesThreshold, total));
            foreach (StratInfo s in map.Values.Where(x => x.Trades > 0).OrderBy(x => x.Name))
            {
                bool ok = s.Trades >= MinTradesPerStrategy && s.Cycle;
                sb.AppendLine((ok ? "[x] " : "[ ] ") + string.Format(ci, "{0} : {1} trades (min {2}), cycle drawdown->recuperation {3}, PnL net {4:F2}{5}, glissement reel {6}",
                    s.Name, s.Trades, MinTradesPerStrategy, s.Cycle ? "oui" : "non", s.Net, s.AiCost > 0 ? string.Format(ci, " (apres IA {0:F2})", s.Net - s.AiCost) : "",
                    s.RealFills > 0 ? s.Slip.ToString("P3", ci) + " sur " + s.RealFills + " fills" : "aucun fill reel"));
            }
            sb.AppendLine("Rappel : premier objectif en reel = realite de l execution, pas le profit (gigikie) ; faire auditer la methode par une seconde IA.");
            sb.AppendLine();

            sb.AppendLine("--- Module B : correlation entre strategies (a revoir chaque semaine) ---");
            sb.AppendLine(NxStrategyCorrelation.Report(NxStrategyCorrelation.LoadFromJournal(NxPaths.Journal), CorrelationWindow));
            if (State == State.Realtime) sb.AppendLine(NxPortfolioRegistry.CorrelationReport(CorrelationWindow));
            sb.AppendLine("Si une correlation >= 0.3-0.4 : ne pas additionner les demi-Kelly ; la correction 'taille / (1 + somme des correlations positives)' est active dans chaque strategie.");
            sb.AppendLine(line);
            return sb.ToString();
        }

        #region Proprietes
        [Range(10, 2000)]
        [Display(Name = "Fenetre de correlation (jours)", Order = 1, GroupName = "01. Moniteur")]
        public int CorrelationWindow { get; set; }

        [Range(1, 10000)]
        [Display(Name = "Rapport toutes les (heures, temps reel)", Description = "168 = hebdomadaire (module B).", Order = 2, GroupName = "01. Moniteur")]
        public int ReportEveryHours { get; set; }

        [Display(Name = "Interrupteur global", Description = "Activer = cree Nexus\\KILL_SWITCH (toutes les strategies ferment et bloquent les entrees en reel).", Order = 3, GroupName = "01. Moniteur")]
        public NxKillAction KillSwitch { get; set; }

        [Range(1, 100000)]
        [Display(Name = "Trades min par strategie", Order = 4, GroupName = "01. Moniteur")]
        public int MinTradesPerStrategy { get; set; }

        [Range(1, 1000000)]
        [Display(Name = "Trades min au total", Order = 5, GroupName = "01. Moniteur")]
        public int TotalTradesThreshold { get; set; }

        [Range(0.5, 90.0)]
        [Display(Name = "Drawdown min d un cycle (%)", Order = 6, GroupName = "01. Moniteur")]
        public double MinDrawdownForCycle { get; set; }
        #endregion
    }
}
