// =============================================================================
//  Backtests.cs - protocole de backtest de la fiche 15 sur trois marches
//  synthetiques 2011-2026 (memes tirages aleatoires, seul l effet plante change) :
//    A. effet LETF plante (impact proportionnel a S, amplifie en court gamma,
//       reversal la nuit suivante) + momentum generique r(ouv->15:30) en confondant ;
//    B. momentum intraday generique seul (proportionnel a r_t, sans lien avec l AUM) ;
//    C. bruit pur.
//  Attendu : A passe H1 et les tests d identification ; B est detecte comme
//  momentum generique (tests AUM / NQ vs ES en echec) ; C ne montre rien.
//  NinjaTrader regle sur Paris pour A (conversion 21:30 Paris -> 15:30 ET).
// =============================================================================
using System;
using System.Collections.Generic;
using System.Globalization;
using System.Linq;
using NinjaTrader.NinjaScript.AddOns.Nexus;
using NinjaTrader.NinjaScript.Strategies;

namespace NexusSim
{
    public static class Backtests
    {
        static Nexus15LetfRebalancing RunOne(string tag, SynthConfig cfg, TimeZoneInfo nt, out SynthOutput mkt, out List<H.Fill> fills)
        {
            DateTime t0 = DateTime.Now;
            mkt = SyntheticMarket.Generate(cfg);
            List<string> output = new List<string>();
            Nexus15LetfRebalancing s = H.Run(mkt, tag, nt, null, output, false);
            fills = H.Fills(s, nt, mkt);
            Console.WriteLine();
            Console.WriteLine(string.Format(CultureInfo.InvariantCulture, "=== Backtest {0} : kappa {1}, momentum ouv->15:30 {2}, momentum r_t {3}, fuseau NT {4} ({5} seances, {6:F0} s) ===",
                tag, cfg.Kappa, cfg.MomentumOpen, cfg.MomentumDay, nt.Id, mkt.Days.Count, (DateTime.Now - t0).TotalSeconds));
            bool on = false;
            foreach (string line in output)
            {
                foreach (string l in line.Split('\n'))
                {
                    string x = l.TrimEnd('\r');
                    if (x.StartsWith("Trades fermes") || x.StartsWith("Taux de reussite") || x.StartsWith("PnL net") || x.StartsWith("Sharpe") || x.StartsWith("Drawdown max")
                        || x.StartsWith("Fiche 15 :") || x.StartsWith("Compteurs") || x.StartsWith("Jours exclus") || x.StartsWith("Ordre de grandeur")) Console.WriteLine("  " + x);
                    if (x.StartsWith("--- Fiche 15 : protocole")) on = true;
                    if (on) Console.WriteLine("  " + x);
                    if (x.StartsWith("Decision :")) on = false;
                }
            }
            return s;
        }

        static void Invariants(string tag, Nexus15LetfRebalancing s, List<H.Fill> fills)
        {
            List<NxLetfPanelRow> panel = s.LetfPanel;
            H.Check(tag + " : jamais de portage overnight", fills.GroupBy(f => f.BarEt.Date.ToString("yyyyMMdd") + f.Symbol).All(g => g.Sum(f => f.Signed) == 0));
            H.Check(tag + " : au plus une position par jour", fills.Where(f => !f.IsStop).GroupBy(f => f.BarEt.Date).All(g => g.Select(f => f.Symbol).Distinct().Count() == 1));
            HashSet<DateTime> excluded = new HashSet<DateTime>(panel.Where(r => r.Excluded != NxLetfExclusion.Aucune).Select(r => r.Date));
            H.Check(tag + " : aucun trade un jour exclu", fills.All(f => !excluded.Contains(f.BarEt.Date)));
            H.Check(tag + " : entrees decidees a 15:30 ET, sorties a 16:00 ET (hors stops)",
                fills.Where(f => !f.IsStop).All(f => f.DecisionEt.TimeOfDay == new TimeSpan(15, 30, 0) || f.DecisionEt.TimeOfDay == new TimeSpan(16, 0, 0)));
            DateTime first = fills.Count > 0 ? fills.Min(f => f.BarEt.Date) : DateTime.MaxValue;
            H.Check(tag + " : premier trade apres le chauffage (20 + 250 seances)", first >= new DateTime(2012, 1, 20), first.ToString("yyyy-MM-dd"));
        }

        /// <summary>
        /// Taille des tests : n marches de bruit pur (graines differentes) ; frequence de |t| >= 1.96 pour chaque statistique.
        /// Sous l hypothese nulle on attend ~5 % ; nettement plus = erreurs-types trop optimistes.
        /// </summary>
        public static Dictionary<string, double> SizeStudy(int n, bool print, int firstSeed = 1000)
        {
            TimeZoneInfo et = NxTime.Eastern;
            Dictionary<string, List<double>> t = new Dictionary<string, List<double>>();
            Action<string, double> add = (k, v) => { List<double> l; if (!t.TryGetValue(k, out l)) { l = new List<double>(); t[k] = l; } l.Add(v); };
            for (int i = 0; i < n; i++)
            {
                SynthOutput mkt = SyntheticMarket.Generate(new SynthConfig { Seed = firstSeed + i, NtZone = et });
                Nexus15LetfRebalancing s = H.Run(mkt, "taille", et, null, null, false);
                NxLetfResearchResult r = s.LetfResearch;
                add("b2 S (principale)", r.Main.TOf("S"));
                add("b3 S x court gamma", r.Main.TOf("S_x_court_gamma"));
                add("c2 r x AUM (test 1)", r.AumTest.TOf("r_x_aum"));
                add("b2 placebo 14:30-15:00 (test 3)", r.Placebo.TOf("S"));
                add("t(S) encompassing (test 4)", r.Encompassing.TOf("S"));
                add("b2 robustesse (+ r_t)", r.MainWithR.TOf("S"));
                add("reversal nuit (test 5)", r.ReversalOvernight.TOf("S"));
                add("z NQ - ES (test 2)", r.NqMinusEsZ);
                if (print) Console.WriteLine(string.Format(CultureInfo.InvariantCulture, "  graine {0} : b2 t={1:F2} b3 t={2:F2} AUM t={3:F2} placebo t={4:F2} encompassing t={5:F2} NQ-ES z={6:F2}",
                    firstSeed + i, r.Main.TOf("S"), r.Main.TOf("S_x_court_gamma"), r.AumTest.TOf("r_x_aum"), r.Placebo.TOf("S"), r.Encompassing.TOf("S"), r.NqMinusEsZ));
                s = null; mkt = null; GC.Collect();
            }
            Dictionary<string, double> rate = new Dictionary<string, double>();
            foreach (KeyValuePair<string, List<double>> kv in t)
            {
                rate[kv.Key] = kv.Value.Count(v => Math.Abs(v) >= 1.96) / (double)kv.Value.Count;
                double sd = NxMath.StdDev(kv.Value);
                // Binomiale(n, 5 %) : plus de 15 % de rejets a moins de 2 % de chances ; ecart-type des t ~ 1 (z NQ-ES conservateur : < 1).
                bool conservative = kv.Key.StartsWith("z NQ");
                H.Check(string.Format(CultureInfo.InvariantCulture, "taille {0,-34} rejet {1:P0}, ecart-type des t {2:F2}", kv.Key, rate[kv.Key], sd),
                    rate[kv.Key] <= 0.15 && sd <= 1.4 && (conservative || sd >= 0.6));
            }
            return rate;
        }

        public static void Run()
        {
            TimeZoneInfo et = NxTime.Eastern, paris = NxTime.Find("Romance Standard Time", NxTime.Find("Europe/Paris", et));
            SynthOutput mkt;
            List<H.Fill> fills;

            Nexus15LetfRebalancing a = RunOne("A_effet_LETF", new SynthConfig { Seed = 2015, Kappa = 0.02, MomentumOpen = 0.05, NtZone = paris }, paris, out mkt, out fills);
            NxLetfResearchResult ra = a.LetfResearch;
            Console.WriteLine("-- Verifications A (effet LETF plante)");
            H.Check("A : H1 validee (b2 > 0 et b3 > 0, t NW >= 1.96)", ra.H1, "b2 t=" + H.F(ra.Main.TOf("S"), "F2") + ", b3 t=" + H.F(ra.Main.TOf("S_x_court_gamma"), "F2"));
            H.Check("A : test 1 AUM positif", ra.AumOk, "t=" + H.F(ra.AumTest.TOf("r_x_aum"), "F2"));
            H.Check("A : test 2 effet NQ > ES", ra.NqEsOk, "z=" + H.F(ra.NqMinusEsZ, "F2"));
            Console.WriteLine("  (placebo 14:30-15:00 : t = " + H.F(ra.Placebo.TOf("S"), "F2") + " ; sa taille est controlee par l etude multi-graines, pas sur une graine)");
            H.Check("A : test 4 placebo de levier degrade l ajustement", ra.LeverageOk, "R2 " + H.F(ra.Main.R2, "F5") + " vs " + H.F(ra.LeveragePlacebo.R2, "F5"));
            H.Check("A : test 5 reversal la nuit suivante", ra.ReversalOk, "c=" + H.F(ra.ReversalOvernight.CoefOf("S")));
            H.Check("A : strategie gagnante net de couts (stress 2 ticks compris)", ra.NetPnl > 0 && ra.NetPnlStress > 0, H.F(ra.NetPnl, "F0") + " $ / stress " + H.F(ra.NetPnlStress, "F0") + " $");
            H.Check("A : Sharpe net hors echantillon > 0", ra.OosSharpeTrades > 0, H.F(ra.OosSharpeTrades, "F2"));
            Invariants("A", a, fills);
            a = null; mkt = null; fills = null; GC.Collect();

            Nexus15LetfRebalancing a2 = RunOne("A2_effet_LETF_fort", new SynthConfig { Seed = 1, Kappa = 0.08, MomentumOpen = 0.05, NtZone = et }, et, out mkt, out fills);
            NxLetfResearchResult ra2 = a2.LetfResearch;
            Console.WriteLine("-- Verifications A2 (effet LETF fort : chemin de decision GO)");
            H.Check("A2 : H1 et les 4 tests d identification passent", ra2.H1 && ra2.AumOk && ra2.NqEsOk && ra2.PlaceboOk && ra2.LeverageOk,
                string.Format(CultureInfo.InvariantCulture, "H1 {0} AUM {1} NQ/ES {2} placebo {3} levier {4}", ra2.H1, ra2.AumOk, ra2.NqEsOk, ra2.PlaceboOk, ra2.LeverageOk));
            H.Check("A2 : decision GO", ra2.Verdict.StartsWith("GO"), ra2.Verdict);
            Invariants("A2", a2, fills);
            a2 = null; mkt = null; fills = null; GC.Collect();

            Nexus15LetfRebalancing b = RunOne("B_momentum_generique", new SynthConfig { Seed = 2015, Kappa = 0, MomentumOpen = 0.05, MomentumDay = 0.04, NtZone = et }, et, out mkt, out fills);
            NxLetfResearchResult rb = b.LetfResearch;
            Console.WriteLine("-- Verifications B (momentum generique, aucun effet LETF)");
            H.Check("B : l effet est attribue au momentum generique (test AUM ou NQ/ES en echec)", !(rb.AumOk && rb.NqEsOk),
                "AUM t=" + H.F(rb.AumTest.TOf("r_x_aum"), "F2") + ", NQ-ES z=" + H.F(rb.NqMinusEsZ, "F2"));
            H.Check("B : pas d amplification en court gamma (b3 non significatif)", !(rb.Main.TOf("S_x_court_gamma") >= 1.96), "t=" + H.F(rb.Main.TOf("S_x_court_gamma"), "F2"));
            H.Check("B : decision NO-GO", rb.Verdict.StartsWith("NO-GO"), rb.Verdict);
            Invariants("B", b, fills);
            b = null; mkt = null; fills = null; GC.Collect();

            Nexus15LetfRebalancing c = RunOne("C_bruit", new SynthConfig { Seed = 2015, NtZone = et }, et, out mkt, out fills);
            NxLetfResearchResult rc = c.LetfResearch;
            Console.WriteLine("-- Verifications C (bruit pur)");
            H.Check("C : b2 non significatif", !(Math.Abs(rc.Main.TOf("S")) >= 1.96), "t=" + H.F(rc.Main.TOf("S"), "F2"));
            H.Check("C : H1 rejetee et decision NO-GO", !rc.H1 && rc.Verdict.StartsWith("NO-GO"), rc.Verdict);
            Invariants("C", c, fills);
        }
    }
}
