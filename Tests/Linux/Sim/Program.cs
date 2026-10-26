// =============================================================================
//  Program.cs - banc d essai de la fiche 15 hors NinjaTrader
//    dotnet run -c Release            tout (scenarios + backtests + taille des tests, ~5 min)
//    dotnet run -c Release regles     scenarios deterministes seulement
//    dotnet run -c Release stats      backtests statistiques seulement
//    dotnet run -c Release taille     taille des tests sous H0 (20 marches de bruit pur)
//    dotnet run -c Release diag       placebo 14:30-15:00 par graine et par force d effet (diagnostic)
// =============================================================================
using System;
using System.Globalization;
using System.Linq;
using System.Threading;

namespace NexusSim
{
    public static class Program
    {
        public static int Main(string[] args)
        {
            Thread.CurrentThread.CurrentCulture = CultureInfo.InvariantCulture;
            bool rules = args.Length == 0 || args.Contains("regles");
            bool stats = args.Length == 0 || args.Contains("stats");
            DateTime t0 = DateTime.Now;
            if (rules) Scenarios.Run();
            if (stats) Backtests.Run();
            if (args.Contains("diag"))
            {
                foreach (double k in new[] { 0.0, 0.02, 0.08 })
                    foreach (int seed in new[] { 7, 2015, 1, 2 })
                    {
                        SynthOutput m = SyntheticMarket.Generate(new SynthConfig { Seed = seed, Kappa = k, MomentumOpen = 0.05, NtZone = NinjaTrader.NinjaScript.AddOns.Nexus.NxTime.Eastern });
                        var s = H.Run(m, "diag", NinjaTrader.NinjaScript.AddOns.Nexus.NxTime.Eastern, null, null, false);
                        var r = s.LetfResearch;
                        Console.WriteLine(string.Format(CultureInfo.InvariantCulture, "kappa {0} graine {1} : placebo b2 t={2:F2} b3 t={3:F2} | principale b2 t={4:F2} | ROpenPlacebo t={5:F2} vol_jour t={6:F2} log_vol t={7:F2}",
                            k, seed, r.Placebo.TOf("S"), r.Placebo.TOf("S_x_court_gamma"), r.Main.TOf("S"), r.Placebo.TOf("r_open"), r.Placebo.TOf("vol_realisee_jour"), r.Placebo.TOf("log_volume_rel")));
                    }
            }
            string big = args.FirstOrDefault(a => a.StartsWith("taille="));
            if (args.Length == 0 || args.Contains("taille") || big != null)
            {
                int n = big != null ? int.Parse(big.Substring(7), CultureInfo.InvariantCulture) : 20;
                Console.WriteLine();
                Console.WriteLine("=== Taille des tests (bruit pur, " + n + " graines) ===");
                Backtests.SizeStudy(n, true, big != null ? 2000 : 1000);
            }
            Console.WriteLine();
            Console.WriteLine(string.Format(CultureInfo.InvariantCulture, "RESULTAT : {0} OK, {1} ECHEC(S)  ({2:F0} s)", H.Pass, H.Fail, (DateTime.Now - t0).TotalSeconds));
            foreach (string f in H.Failures) Console.WriteLine("  ECHEC : " + f);
            return H.Fail == 0 ? 0 : 1;
        }
    }
}
