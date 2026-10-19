// =============================================================================
//  NtCoreStub.cs - substitut MINIMAL de NinjaTrader.Core pour compiler et
//  executer le socle Nexus hors de NinjaTrader (Linux / .NET 8).
//  Seuls les membres reellement utilises par AddOns\*.cs sont fournis.
// =============================================================================
using System;
using System.IO;

namespace NinjaTrader.Core
{
    public class GeneralOptionsStub
    {
        /// <summary>Fuseau d affichage NinjaTrader (Options > General). Par defaut : heure de New York.</summary>
        public TimeZoneInfo TimeZoneInfo = FindEastern();

        private static TimeZoneInfo FindEastern()
        {
            foreach (string id in new[] { "Eastern Standard Time", "America/New_York" })
                try { return TimeZoneInfo.FindSystemTimeZoneById(id); } catch { }
            return TimeZoneInfo.Local;
        }
    }

    public static class Globals
    {
        /// <summary>Dossier utilisateur NinjaTrader (Nexus\ est cree dessous). Surcharge par NEXUS_SIM_DIR.</summary>
        public static string UserDataDir = Environment.GetEnvironmentVariable("NEXUS_SIM_DIR")
                                           ?? Path.Combine(Path.GetTempPath(), "nexus_sim_userdata");

        public static GeneralOptionsStub GeneralOptions = new GeneralOptionsStub();

        /// <summary>Heure courante du moteur (le simulateur la fait avancer en temps reel simule).</summary>
        public static DateTime Now { get { return SimNow ?? DateTime.Now; } }
        public static DateTime? SimNow;
    }
}
