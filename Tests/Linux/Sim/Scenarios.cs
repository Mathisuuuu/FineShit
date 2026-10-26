// =============================================================================
//  Scenarios.cs - regles de la fiche 15 verifiees une a une sur la VRAIE
//  strategie (emulateur NinjaScript), avec recalcul independant du signal, du
//  seuil q70, de la taille, du stop ATR et des heures de remplissage.
//
//  Marche synthetique 2025-01-02 -> 2026-10-09 : chauffage (20 seances de
//  volume + 250 seances de score), puis seances calmes (|r| = 0.2 %, aucun
//  trade attendu) sauf les jours de test forces ci-dessous.
// =============================================================================
using System;
using System.Collections.Generic;
using System.Globalization;
using System.Linq;
using NinjaTrader.Data;
using NinjaTrader.NinjaScript.AddOns.Nexus;
using NinjaTrader.NinjaScript.Strategies;

namespace NexusSim
{
    public static class Scenarios
    {
        static readonly DateTime D1 = new DateTime(2026, 3, 17);   // hausse, court gamma (semaine de decalage d heure d ete US/Europe)
        static readonly DateTime D2 = new DateTime(2026, 3, 24);   // baisse, court gamma -> vente
        static readonly DateTime D3 = new DateTime(2026, 4, 7);    // |r| = 0.3 % -> filtre de rendement
        static readonly DateTime D7 = new DateTime(2026, 4, 14);   // choc -3 % a 15:40 -> stop
        static readonly DateTime D8 = new DateTime(2026, 6, 16);   // NQ sous le seuil, ES au-dessus -> ES
        static readonly DateTime D9 = new DateTime(2026, 4, 28);   // baisse de 2.8 %, long gamma (w = 0.3) -> vente
        static readonly DateTime D4 = new DateTime(2026, 5, 20);   // FOMC (agenda macro) -> exclu
        static readonly DateTime D10 = new DateTime(2026, 6, 3);   // ADP (leurre) -> trade ; NQ et ES passent -> NQ seul
        static readonly DateTime D12 = new DateTime(2026, 7, 6);   // NFP -> exclu
        static readonly DateTime D11 = new DateTime(2026, 7, 13);  // CPI -> exclu
        static readonly DateTime D13 = new DateTime(2026, 8, 11);  // rebalancement NDX (fichier) -> exclu
        static readonly DateTime D14 = new DateTime(2026, 8, 18);  // |r| = 3.5 % -> plafond divise par 2
        static readonly DateTime D5 = new DateTime(2026, 9, 18);   // quatre sorcieres -> exclu
        static readonly DateTime D6 = new DateTime(2025, 11, 28);  // demi-seance -> pas de fenetre
        static readonly DateTime Calm0 = new DateTime(2026, 1, 15);

        static SynthOutput Market(TimeZoneInfo nt)
        {
            Dictionary<DateTime, DayOverride> ov = new Dictionary<DateTime, DayOverride>();
            Random rr = new Random(5);
            for (DateTime d = Calm0; d <= new DateTime(2026, 10, 9); d = d.AddDays(1))
            {
                double sgn = rr.NextDouble() < 0.5 ? -1 : 1;
                ov[d] = new DayOverride { RNdx1525 = 0.0045 * sgn, RSpx1525 = 0.0045 * sgn, Gex = -2e9 };
            }
            ov[D1] = new DayOverride { RNdx1525 = 0.02, RSpx1525 = 0.004, Gex = -2e9, WindowMove = 0.004 };
            ov[D2] = new DayOverride { RNdx1525 = -0.02, RSpx1525 = -0.004, Gex = -2e9 };
            ov[D3] = new DayOverride { RNdx1525 = 0.003, RSpx1525 = 0.003, Gex = -2e9 };
            ov[D7] = new DayOverride { RNdx1525 = 0.02, RSpx1525 = 0.004, Gex = -2e9, ShockAt1540 = -0.03 };
            ov[D8] = new DayOverride { RNdx1525 = 0.0055, RSpx1525 = 0.025, Gex = 2e9 };
            ov[D9] = new DayOverride { RNdx1525 = -0.028, RSpx1525 = -0.004, Gex = 2e9 };
            foreach (DateTime d in new[] { D4, D12, D11, D13, D5 }) ov[d] = new DayOverride { RNdx1525 = 0.02, RSpx1525 = 0.004, Gex = -2e9 };
            ov[D10] = new DayOverride { RNdx1525 = 0.02, RSpx1525 = 0.02, Gex = -2e9 };
            ov[D14] = new DayOverride { RNdx1525 = 0.035, RSpx1525 = 0.004, Gex = -2e9 };
            SynthConfig c = new SynthConfig { Seed = 11, Start = new DateTime(2025, 1, 2), End = new DateTime(2026, 10, 9), NtZone = nt, NdxStart = 21000, SpxStart = 5900 };
            c.Override = d => { DayOverride o; return ov.TryGetValue(d, out o) ? o : null; };
            return SyntheticMarket.Generate(c);
        }

        static double Quantile7(List<double> v, double q)
        {
            List<double> s = v.OrderBy(x => x).ToList();
            double hh = (s.Count - 1) * q;
            int lo = (int)Math.Floor(hh), hi = Math.Min(s.Count - 1, lo + 1);
            return s[lo] + (hh - lo) * (s[hi] - s[lo]);
        }

        public static void Run()
        {
            Console.WriteLine();
            Console.WriteLine("=== Fiche 15 - scenarios deterministes sur la strategie NinjaScript (emulateur) ===");
            TimeZoneInfo et = NxTime.Eastern, paris = NxTime.Find("Romance Standard Time", NxTime.Find("Europe/Paris", et));
            SynthOutput mkt = Market(et);
            string[] extra = { "2026-08-11,NDX special rebalance" };
            List<string> outEt = new List<string>();
            Nexus15LetfRebalancing s = H.Run(mkt, "regles_et", et, null, outEt, false, true, extra);
            List<H.Fill> fills = H.Fills(s, et, mkt);
            List<NxLetfPanelRow> panel = s.LetfPanel;
            Func<DateTime, string, NxLetfPanelRow> row = (d, sym) => panel.FirstOrDefault(r => r.Date == d && r.Instrument == sym);
            Func<DateTime, List<H.Fill>> fillsOn = d => fills.Where(f => f.BarEt.Date == d).ToList();

            Console.WriteLine("-- Chauffage et jours calmes");
            DateTime firstFill = fills.Count > 0 ? fills.Min(f => f.BarEt.Date) : DateTime.MaxValue;
            NxLetfPanelRow firstThr = panel.Where(r => r.Instrument == "NQ 12-26" && NxMath.Ok(r.Threshold)).OrderBy(r => r.Date).FirstOrDefault();
            int scoredBefore = firstThr == null ? -1 : panel.Count(r => r.Instrument == "NQ 12-26" && r.Date < firstThr.Date && NxMath.Ok(r.Score));
            H.Check("seuil q70 disponible apres exactement 250 scores", scoredBefore == 250, "scores avant le 1er seuil = " + scoredBefore);
            H.Check("aucun trade avant le premier jour de test", firstFill >= D1, "premier remplissage " + firstFill.ToString("yyyy-MM-dd"));
            HashSet<DateTime> testDays = new HashSet<DateTime> { D1, D2, D3, D4, D5, D7, D8, D9, D10, D11, D12, D13, D14 };
            int calmTrades = fills.Count(f => f.BarEt.Date >= Calm0 && !testDays.Contains(f.BarEt.Date));
            H.Check("aucun trade les jours calmes (|r| = 0.45 % < 0.5 %)", calmTrades == 0, calmTrades + " remplissages");

            Console.WriteLine("-- " + D1.ToString("yyyy-MM-dd") + " : hausse de 2 %, court gamma -> achat NQ 15:30, sortie 16:00");
            NxLetfPanelRow r1 = row(D1, "NQ 12-26");
            // Signal recalcule independamment : r_t, actif net de la veille, F, N, V, S, Score.
            List<KeyValuePair<TimeSpan, SimBar>> ndx1 = H.DayBars(mkt, "^NDX", D1, et), ndx0 = H.DayBars(mkt, "^NDX", NxUsMarketCalendar.PreviousTradingDay(D1), et);
            double prevClose = ndx0.Last(kv => kv.Key <= new TimeSpan(16, 0, 0)).Value.Close, level = ndx1.Last(kv => kv.Key <= new TimeSpan(15, 25, 0)).Value.Close;
            double r = level / prevClose - 1;
            Dictionary<string, double> aumVeille = new Dictionary<string, double>();
            foreach (string line in mkt.AumCsv.Skip(1))
            {
                string[] p = line.Split(',');
                DateTime d = DateTime.ParseExact(p[0], "yyyy-MM-dd", CultureInfo.InvariantCulture);
                if (d < D1) aumVeille[p[1]] = double.Parse(p[2], CultureInfo.InvariantCulture) * double.Parse(p[3], CultureInfo.InvariantCulture);
            }
            double F = 0;
            foreach (NxLetfFund f in NxLetfFlow.ParseFunds(NxLetfFlow.DefaultFunds).Where(f => f.Index == "NDX"))
                F += aumVeille[f.Symbol] * f.Leverage * (f.Leverage - 1) * r / (1 + f.Leverage * r);
            List<double> winVol = new List<double>();
            for (DateTime d = NxUsMarketCalendar.PreviousTradingDay(D1); winVol.Count < 20; d = NxUsMarketCalendar.PreviousTradingDay(d))
            {
                List<KeyValuePair<TimeSpan, SimBar>> b = H.DayBars(mkt, "NQ 12-26", d, et).Where(kv => kv.Key > new TimeSpan(15, 30, 0) && kv.Key <= new TimeSpan(16, 0, 0)).ToList();
                if (b.Count >= 24) winVol.Add(b.Sum(kv => kv.Value.Volume));
            }
            double vbar = winVol.Average(), N = F / (20.0 * level), S = N / vbar;
            H.Check("r_t = indice cloture J-1 -> 15:25", Math.Abs(r1.R - r) < 1e-12, H.F(r1.R) + " vs " + H.F(r));
            H.Check("S = F / (20 x niveau) / V (formule de la fiche)", Math.Abs(r1.S / S - 1) < 1e-9, "S " + H.F(r1.S) + " vs " + H.F(S) + ", N = " + H.F(N, "F0") + " contrats, V = " + H.F(vbar, "F0"));
            H.Check("court gamma : w = 1, Score = S", r1.W == 1.0 && Math.Abs(r1.Score - r1.S) < 1e-15);
            List<double> hist = panel.Where(x => x.Instrument == "NQ 12-26" && x.Date < D1 && NxMath.Ok(x.Score)).OrderBy(x => x.Date).Select(x => Math.Abs(x.Score)).ToList();
            double thr = Quantile7(hist.Skip(Math.Max(0, hist.Count - 250)).ToList(), 0.70);
            H.Check("seuil = q70 de |Score| sur les 250 seances precedentes", Math.Abs(r1.Threshold / thr - 1) < 1e-12, H.F(r1.Threshold) + " vs " + H.F(thr));
            List<H.Fill> f1 = fillsOn(D1);
            H.Fill entry = f1.FirstOrDefault(f => !f.IsStop && f.Signed > 0);
            H.Fill exit = f1.FirstOrDefault(f => !f.IsStop && f.Signed < 0);
            H.Check("entree long NQ decidee a la barre de 15:30, remplie a l ouverture de la barre suivante",
                entry != null && entry.Symbol == "NQ 12-26" && entry.DecisionEt.TimeOfDay == new TimeSpan(15, 30, 0) && entry.Price == entry.BarOpen,
                entry == null ? "aucune" : entry.DecisionEt.ToString("HH:mm") + " -> " + H.F(entry.Price));
            H.Check("sortie a 16:00 ET (au marche), meme quantite, position plate",
                exit != null && entry != null && exit.DecisionEt.TimeOfDay == new TimeSpan(16, 0, 0) && exit.Signed == -entry.Signed,
                exit == null ? "aucune" : exit.DecisionEt.ToString("HH:mm") + " x" + exit.Signed);
            H.Check("une seule position ce jour-la (pas d ES)", f1.All(f => f.Symbol == "NQ 12-26"));
            // Taille recalculee : cible de risque 0.5 % de 500 000 $, vol realisee 15:00-15:30, |Score|/seuil, plafond 2 % de V.
            List<KeyValuePair<TimeSpan, SimBar>> nq1 = H.DayBars(mkt, "NQ 12-26", D1, et);
            List<double> closes = nq1.Where(kv => kv.Key >= new TimeSpan(15, 0, 0) && kv.Key <= new TimeSpan(15, 30, 0)).Select(kv => kv.Value.Close).ToList();
            double ss = 0; for (int i = 1; i < closes.Count; i++) ss += Math.Pow(Math.Log(closes[i] / closes[i - 1]), 2);
            double rv = Math.Sqrt(ss / (closes.Count - 1) * 98280.0), price = closes[closes.Count - 1];
            double raw = 500000 * 0.005 / (price * 20 * rv * Math.Sqrt(30 / 98280.0)) * Math.Abs(r1.Score) / r1.Threshold;
            int qExp = (int)Math.Floor(Math.Min(raw, Math.Floor(0.02 * vbar)));
            H.Check("taille = cible de risque / vol 30 min x |Score|/seuil (plafond 2 % de V)", entry != null && entry.Signed == qExp,
                "attendu " + qExp + " (brut " + H.F(raw, "F3") + "), obtenu " + (entry != null ? entry.Signed.ToString() : "-"));
            // Stop : 1.5 x ATR(14) de barres 30 min RTH, recalcule.
            List<double[]> b30 = new List<double[]>();
            foreach (IGrouping<string, KeyValuePair<DateTime, SimBar>> grp in mkt.Market.Instruments["NQ 12-26"].Bars
                         .Select(b => new KeyValuePair<DateTime, SimBar>(H.ToEt(b.Time, et), b))
                         .Where(kv => kv.Key <= D1.AddHours(15.5) && kv.Key.TimeOfDay > new TimeSpan(9, 30, 0) && kv.Key.TimeOfDay <= new TimeSpan(16, 0, 0))
                         .GroupBy(kv => kv.Key.Date.ToString("yyyyMMdd") + ((int)Math.Ceiling((kv.Key.TimeOfDay - new TimeSpan(9, 30, 0)).TotalMinutes / 30.0)).ToString("D2")))
                b30.Add(new[] { grp.Max(kv => kv.Value.High), grp.Min(kv => kv.Value.Low), grp.Last().Value.Close });
            double atr = double.NaN, trSum = 0;
            for (int i = 0; i < b30.Count; i++)
            {
                double tr = i == 0 ? b30[i][0] - b30[i][1] : Math.Max(b30[i][0] - b30[i][1], Math.Max(Math.Abs(b30[i][0] - b30[i - 1][2]), Math.Abs(b30[i][1] - b30[i - 1][2])));
                if (i < 14) { trSum += tr; if (i == 13) atr = trSum / 14; } else atr = (atr * 13 + tr) / 14;
            }
            double stopExp = Math.Round((price - 1.5 * atr) * 4) / 4;
            NinjaTrader.Cbi.Order stopOrder = s.SimAllOrders.FirstOrDefault(o => o.Name == "NxS_NQ 12-26" && H.ToEt(mkt.Market.Instruments["NQ 12-26"].Bars[o.SubmitBar].Time, et).Date == D1);
            H.Check("stop natif = prix 15:30 - 1.5 x ATR 30 min (arrondi au tick)", stopOrder != null && Math.Abs(stopOrder.StopPrice - stopExp) < 1e-9,
                "attendu " + H.F(stopExp) + " (ATR " + H.F(atr, "F2") + "), obtenu " + (stopOrder != null ? H.F(stopOrder.StopPrice) : "-"));

            Console.WriteLine("-- Autres regles");
            List<H.Fill> f2 = fillsOn(D2);
            H.Check(D2.ToString("yyyy-MM-dd") + " baisse de 2 % -> vente NQ, rachat a 16:00", f2.Count == 2 && f2[0].Signed < 0 && f2[1].Signed == -f2[0].Signed && f2[0].Symbol == "NQ 12-26");
            H.Check(D3.ToString("yyyy-MM-dd") + " |r| = 0.3 % -> filtre de rendement, pas de trade", fillsOn(D3).Count == 0 && row(D3, "NQ 12-26").Decision.Contains("filtre de rendement"), row(D3, "NQ 12-26").Decision);
            List<H.Fill> f7 = fillsOn(D7);
            NxLetfTradeOutcome o7 = s.LetfTradeOutcomes.FirstOrDefault(t => t.Day == D7);
            H.Check(D7.ToString("yyyy-MM-dd") + " choc -3 % a 15:40 -> stop touche, pas de reentree, plat avant 16:00",
                f7.Count == 2 && f7[1].IsStop && f7[1].BarEt.TimeOfDay <= new TimeSpan(15, 41, 0) && o7 != null && o7.Stopped && o7.NetPnl < 0,
                string.Join(" ; ", f7.Select(f => (f.IsStop ? "stop " : "") + f.BarEt.ToString("HH:mm") + " x" + f.Signed + " @" + H.F(f.Price))));
            List<H.Fill> f8 = fillsOn(D8);
            H.Check(D8.ToString("yyyy-MM-dd") + " NQ sous le seuil, ES au-dessus -> ES seul (secours)", f8.Count == 2 && f8.All(f => f.Symbol == "ES 12-26") && f8[0].Signed > 0
                && row(D8, "NQ 12-26").Decision.Contains("< seuil"), row(D8, "NQ 12-26").Decision + " | " + row(D8, "ES 12-26").Decision);
            NxLetfPanelRow r9 = row(D9, "NQ 12-26");
            H.Check(D9.ToString("yyyy-MM-dd") + " long gamma : w = 0.3, Score = 0.3 x S, vente NQ", r9.W == 0.3 && Math.Abs(r9.Score - 0.3 * r9.S) < 1e-15 && fillsOn(D9).Count == 2 && fillsOn(D9)[0].Signed < 0,
                "S " + H.F(r9.S) + " Score " + H.F(r9.Score));
            foreach (KeyValuePair<DateTime, string> kv in new Dictionary<DateTime, string> { { D4, "Fomc" }, { D12, "Nfp" }, { D11, "Cpi" }, { D13, "RebalancementNdx" }, { D5, "QuatreSorcieres" } })
            {
                NxLetfPanelRow rr = row(kv.Key, "NQ 12-26");
                H.Check(kv.Key.ToString("yyyy-MM-dd") + " jour exclu " + kv.Value + " -> pas de trade malgre +2 %",
                    rr != null && NxLetfExclusionCalendar.Describe(rr.Excluded).Contains(kv.Value) && fillsOn(kv.Key).Count == 0, rr != null ? rr.Decision : "pas de ligne");
            }
            H.Check(D10.ToString("yyyy-MM-dd") + " ADP (leurre de l agenda) -> non exclu, trade", fillsOn(D10).Count == 2 && row(D10, "NQ 12-26").Excluded == NxLetfExclusion.Aucune);
            H.Check(D10.ToString("yyyy-MM-dd") + " NQ et ES passent le seuil -> NQ seul (une position par jour)", fillsOn(D10).All(f => f.Symbol == "NQ 12-26")
                && row(D10, "ES 12-26").Decision.Contains("une position par jour"), row(D10, "ES 12-26").Decision);
            H.Check(D6.ToString("yyyy-MM-dd") + " demi-seance -> pas de fenetre 15:30-16:00, aucun signal ni trade", row(D6, "NQ 12-26") == null && fillsOn(D6).Count == 0);
            NxLetfPanelRow r14 = row(D14, "NQ 12-26");
            H.Check(D14.ToString("yyyy-MM-dd") + " |r| = 3.5 % -> plafond de taille divise par 2", r14.Decision.Contains("divise par 2") && fillsOn(D14).Count == 2, r14.Decision);
            int decoys = mkt.DecoyDays.Count(d => panel.Any(x => x.Date == d && (x.Excluded & (NxLetfExclusion.Fomc | NxLetfExclusion.Nfp)) != 0));
            int macroMissed = mkt.MacroDays.Count(d => panel.Any(x => x.Date == d && x.Instrument == "NQ 12-26" && (x.Excluded & (NxLetfExclusion.Fomc | NxLetfExclusion.Cpi | NxLetfExclusion.Nfp)) == 0));
            H.Check("agenda macro (UTC -> ET) : tous les FOMC/CPI/NFP exclus, aucun leurre (minutes FOMC, ADP)", decoys == 0 && macroMissed == 0, "leurres exclus " + decoys + ", macro manques " + macroMissed);

            Console.WriteLine("-- Invariants");
            bool flat = fills.GroupBy(f => f.BarEt.Date.ToString("yyyyMMdd") + f.Symbol).All(g2 => g2.Sum(f => f.Signed) == 0);
            H.Check("jamais de portage overnight (position nulle chaque soir)", flat);
            H.Check("au plus une position par jour", fills.Where(f => !f.IsStop).GroupBy(f => f.BarEt.Date).All(g2 => g2.Select(f => f.Symbol).Distinct().Count() == 1));
            H.Check("toutes les sorties avant ou a 16:01 ET", fills.All(f => f.BarEt.TimeOfDay <= new TimeSpan(16, 1, 0)));
            H.Check("aucun trade un jour exclu", fills.All(f => panel.Where(x => x.Date == f.BarEt.Date).All(x => x.Excluded == NxLetfExclusion.Aucune)));
            foreach (string ins in new[] { "NQ 12-26", "ES 12-26" })
            {
                List<NxLetfPanelRow> rs = panel.Where(x => x.Instrument == ins && NxMath.Ok(x.S) && x.Date < new DateTime(2026, 10, 9)).ToList();
                int complete = rs.Count(x => NxMath.Ok(x.Y) && NxMath.Ok(x.ROpenEntry) && NxMath.Ok(x.YPlacebo) && NxMath.Ok(x.ROvernight));
                H.Check("panel " + ins + " : fenetre, placebo et reversal renseignes chaque jour", complete == rs.Count, complete + "/" + rs.Count);
            }
            H.Check("rapport de fin de run produit (protocole de backtest)", outEt.Any(l => l.Contains("Fiche 15 : protocole de backtest")) && s.LetfResearch != null);

            Console.WriteLine("-- Meme marche, NinjaTrader regle sur Paris (21:30 = 15:30 ET, 20:30 pendant le decalage d heure d ete)");
            SynthOutput mktP = Market(paris);
            Nexus15LetfRebalancing sp = H.Run(mktP, "regles_paris", paris, null, null, false, true, extra);
            List<H.Fill> fp = H.Fills(sp, paris, mktP);
            Func<List<H.Fill>, string> key = l => string.Join("|", l.Select(f => f.BarEt.ToString("yyyy-MM-dd HH:mm") + f.Symbol + f.Signed + "@" + H.F(f.Price)));
            H.Check("memes trades (heure ET, quantite, prix) qu avec le fuseau New York", key(fp) == key(fills), fp.Count + " vs " + fills.Count + " remplissages");
            H.Fill pEntry = fp.FirstOrDefault(f => f.BarEt.Date == D1 && f.Signed > 0);
            H.Check("le " + D1.ToString("yyyy-MM-dd") + " l entree NinjaTrader est horodatee 20:30 Paris (decalage DST)",
                pEntry != null && pEntry.Order != null && sp.SimAllOrders.Contains(pEntry.Order)
                && mktP.Market.Instruments["NQ 12-26"].Bars[pEntry.Order.SubmitBar].Time.TimeOfDay == new TimeSpan(20, 30, 0),
                pEntry != null ? mktP.Market.Instruments["NQ 12-26"].Bars[pEntry.Order.SubmitBar].Time.ToString("HH:mm") + " Paris" : "-");

            Console.WriteLine("-- Sortie TWAP 15:55-16:00");
            Nexus15LetfRebalancing st = H.Run(mkt, "regles_twap", et, x => x.ExitMode = Nexus15Exit.Twap1555_1600, null, false, true, extra);
            List<H.Fill> ft = H.Fills(st, et, mkt).Where(f => f.BarEt.Date == D1).ToList();
            List<H.Fill> exits = ft.Where(f => f.Signed < 0 && !f.IsStop).ToList();
            H.Check("le " + D1.ToString("yyyy-MM-dd") + " le stop n est pas touche (prerequis du test TWAP)", ft.All(f => !f.IsStop));
            H.Check("TWAP : tranches decidees de 15:55 a 15:59, position soldee avant 16:00",
                exits.Count >= 2 && exits.All(f => f.DecisionEt.TimeOfDay >= new TimeSpan(15, 55, 0) && f.DecisionEt.TimeOfDay <= new TimeSpan(15, 59, 0)) && ft.Sum(f => f.Signed) == 0,
                string.Join(" ", exits.Select(f => f.DecisionEt.ToString("HH:mm") + "x" + f.Signed)));
        }
    }
}
