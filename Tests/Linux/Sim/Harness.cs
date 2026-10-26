// =============================================================================
//  Harness.cs - outils communs du banc d essai (verification, execution)
// =============================================================================
using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Linq;
using NinjaTrader.Cbi;
using NinjaTrader.Data;
using NinjaTrader.NinjaScript.AddOns.Nexus;
using NinjaTrader.NinjaScript.Strategies;

namespace NexusSim
{
    public static class H
    {
        public static int Pass, Fail;
        public static readonly List<string> Failures = new List<string>();

        public static void Check(string name, bool ok, string detail = "")
        {
            if (ok) Pass++; else { Fail++; Failures.Add(name + (detail.Length > 0 ? " [" + detail + "]" : "")); }
            Console.WriteLine((ok ? "  OK   " : "  FAIL ") + name + (detail.Length > 0 ? "  [" + detail + "]" : ""));
        }

        public static string F(double x, string fmt = "G6") { return x.ToString(fmt, CultureInfo.InvariantCulture); }

        /// <summary>Execute la vraie strategie de la fiche 15 sur un marche synthetique (dossier Nexus isole).</summary>
        public static Nexus15LetfRebalancing Run(SynthOutput mkt, string tag, TimeZoneInfo ntZone, Action<Nexus15LetfRebalancing> configure,
                                                 List<string> output, bool echo, bool withGex = true, IEnumerable<string> extraExcluded = null)
        {
            string dir = Path.Combine(Path.GetTempPath(), "nexus_sim", tag);
            if (Directory.Exists(dir)) Directory.Delete(dir, true);
            NinjaTrader.Core.Globals.UserDataDir = dir;
            NinjaTrader.Core.Globals.GeneralOptions.TimeZoneInfo = ntZone;
            string data = Path.Combine(dir, "Nexus", "data");
            SyntheticMarket.WriteFiles(mkt, data, withGex);
            if (extraExcluded != null) File.AppendAllLines(Path.Combine(data, "letf_excluded_days.csv"), extraExcluded);
            Nexus15LetfRebalancing s = new Nexus15LetfRebalancing();
            SimRunner.Run(s, mkt.Market, "NQ 12-26", x =>
            {
                x.Symbols = "NQ 12-26,ES 12-26";
                if (configure != null) configure(x);
            }, line => { if (output != null) output.Add(line); if (echo) Console.WriteLine(line); });
            return s;
        }

        public static DateTime ToEt(DateTime nt, TimeZoneInfo ntZone) { return TimeZoneInfo.ConvertTime(nt, ntZone, NxTime.Eastern); }

        /// <summary>Ordres remplis de la strategie (entrees NxE_ et stops NxS_), heure de remplissage en ET.</summary>
        public static List<Fill> Fills(Strategy s, TimeZoneInfo ntZone, SynthOutput mkt)
        {
            List<Fill> fills = new List<Fill>();
            foreach (Order o in s.SimAllOrders.Where(x => x.OrderState == OrderState.Filled))
            {
                SimInstrument si = mkt.Market.Instruments[o.Name.Substring(4)];
                SimBar bar = si.Bars[o.SimFillBar];
                fills.Add(new Fill
                {
                    Order = o, Symbol = o.Name.Substring(4), IsStop = o.Name.StartsWith("NxS_"), Price = o.AverageFillPrice,
                    Signed = (o.OrderAction == OrderAction.Buy || o.OrderAction == OrderAction.BuyToCover ? 1 : -1) * o.Quantity,
                    BarEt = ToEt(bar.Time, ntZone), BarOpen = bar.Open, DecisionEt = ToEt(si.Bars[o.SubmitBar].Time, ntZone)
                });
            }
            return fills;
        }

        public class Fill
        {
            public Order Order;
            public string Symbol;
            public bool IsStop;
            public double Price;
            public int Signed;
            public DateTime BarEt;
            public DateTime DecisionEt;
            public double BarOpen;
        }

        /// <summary>Barres d une seance (ET) d un instrument du marche synthetique.</summary>
        public static List<KeyValuePair<TimeSpan, SimBar>> DayBars(SynthOutput mkt, string name, DateTime day, TimeZoneInfo ntZone)
        {
            return mkt.Market.Instruments[name].Bars.Select(b => new KeyValuePair<DateTime, SimBar>(ToEt(b.Time, ntZone), b))
                      .Where(kv => kv.Key.Date == day.Date).Select(kv => new KeyValuePair<TimeSpan, SimBar>(kv.Key.TimeOfDay, kv.Value)).ToList();
        }
    }
}
