// =============================================================================
//  SyntheticMarket.cs - marche synthetique pour le banc d essai de la fiche 15
//
//  Barres 1 minute RTH (heure de New York convertie dans le fuseau NinjaTrader
//  choisi) pour ^NDX, ^SP500, NQ et ES ; actif net quotidien des 10 LETF de la
//  fiche (parts x NAV, NAV a levier exact) ; GEX agrege (+ source "tierce"
//  bruitee) ; agenda macro (FOMC, CPI, NFP + leurres : minutes du FOMC, ADP).
//
//  Effets plantes (parametrables) sur la fenetre 15:30-16:00 :
//    impact LETF  = Kappa x S_vrai x (1 si G < 0, LongGammaDamping sinon), ou
//                   S_vrai = flux exact (NAV de la veille) / (multiplicateur x niveau x volume attendu) ;
//    momentum generique = MomentumOpen x r(9:30->15:30) + MomentumDay x r(J-1 -> 15:25) ;
//    reversal : la nuit suivante rend Reversal x impact LETF.
//  Les jours d evenements (FOMC, CPI, NFP, quatre sorcieres) ont une fenetre
//  plus bruitee (EventNoise). Demi-seances : indice jusqu a 13:00, futures 13:15.
// =============================================================================
using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Linq;
using System.Text;
using NinjaTrader.Cbi;
using NinjaTrader.Data;
using NinjaTrader.NinjaScript.AddOns.Nexus;

namespace NexusSim
{
    /// <summary>Forcage d une seance (scenarios deterministes).</summary>
    public class DayOverride
    {
        public double RNdx1525 = double.NaN;     // rendement force de ^NDX cloture J-1 -> 15:25
        public double RSpx1525 = double.NaN;     // idem ^SP500
        public double WindowMove = double.NaN;   // rendement ajoute sur 15:30 -> 16:00 (les deux indices)
        public double ShockAt1540 = double.NaN;  // saut sur la barre de 15:40 (les deux indices)
        public double Gex = double.NaN;          // GEX force du jour
    }

    public class SynthConfig
    {
        public int Seed = 42;
        public DateTime Start = new DateTime(2011, 1, 3);
        public DateTime End = new DateTime(2026, 10, 9);
        public double Kappa;
        public double LongGammaDamping = 0.3;
        public double MomentumOpen;
        public double MomentumDay;
        public double Reversal = 0.5;
        public double EventNoise = 1.8;
        public double NdxStart = 2200, SpxStart = 1270;   // niveaux au premier jour
        public TimeZoneInfo NtZone;
        public string NqName = "NQ 12-26", EsName = "ES 12-26", NdxName = "^NDX", SpxName = "^SP500";
        public Func<DateTime, DayOverride> Override;
    }

    public class SynthOutput
    {
        public SimMarket Market = new SimMarket();
        public readonly List<string> AumCsv = new List<string>();
        public readonly List<string> GexCsv = new List<string>();
        public readonly List<string> MacroCsv = new List<string>();
        public readonly List<string> ExcludedCsv = new List<string>();
        public readonly HashSet<DateTime> MacroDays = new HashSet<DateTime>();
        public readonly HashSet<DateTime> DecoyDays = new HashSet<DateTime>();
        public readonly List<DateTime> Days = new List<DateTime>();
        public readonly Dictionary<DateTime, double> Gex = new Dictionary<DateTime, double>();
        public readonly Dictionary<DateTime, double[]> TrueS = new Dictionary<DateTime, double[]>();   // [S_NQ, S_ES]
    }

    public static class SyntheticMarket
    {
        private static readonly string[] FundNames = { "TQQQ", "SQQQ", "QLD", "QID", "UPRO", "SPXU", "SPXL", "SPXS", "SSO", "SDS" };
        // Actif net de depart (2011) et d arrivee (2026), en dollars.
        // La composition derive (inverses lourds en 2011, TQQQ / UPRO / SPXL ensuite) : c est ce qui donne de la puissance au
        // placebo de levier ; l actif net varie aussi par cycles de quelques annees (puissance du test AUM).
        private static readonly double[] Aum0 = { 0.2e9, 2.0e9, 0.6e9, 0.4e9, 0.15e9, 0.6e9, 0.2e9, 0.4e9, 1.2e9, 2.5e9 };
        private static readonly double[] Aum1 = { 33.5e9, 2.2e9, 13e9, 0.25e9, 4e9, 0.6e9, 5.5e9, 0.5e9, 6e9, 0.5e9 };

        private class Rng
        {
            private readonly Random r;
            private bool has; private double spare;
            public Rng(int seed) { r = new Random(seed); }
            public double U() { return r.NextDouble(); }
            public double N()
            {
                if (has) { has = false; return spare; }
                double u1 = 1.0 - r.NextDouble(), u2 = r.NextDouble(), m = Math.Sqrt(-2.0 * Math.Log(u1));
                spare = m * Math.Sin(2 * Math.PI * u2); has = true;
                return m * Math.Cos(2 * Math.PI * u2);
            }
        }

        private static DateTime FirstFriday(int y, int m) { DateTime d = new DateTime(y, m, 1); while (d.DayOfWeek != DayOfWeek.Friday) d = d.AddDays(1); return d; }
        private static DateTime NextTrading(DateTime d) { while (!NxUsMarketCalendar.IsTradingDay(d)) d = d.AddDays(1); return d; }
        private static DateTime ThirdWednesday(int y, int m) { DateTime d = new DateTime(y, m, 1); while (d.DayOfWeek != DayOfWeek.Wednesday) d = d.AddDays(1); return d.AddDays(14); }

        private static string Iso(DateTime etLocal, TimeZoneInfo et)
        {
            return NxTime.ToUtc(etLocal, et).ToString("yyyy-MM-dd'T'HH:mm:ss'Z'", CultureInfo.InvariantCulture);
        }

        public static SynthOutput Generate(SynthConfig c)
        {
            SynthOutput o = new SynthOutput();
            Rng g = new Rng(c.Seed);
            TimeZoneInfo et = NxTime.Eastern, nt = c.NtZone ?? et;
            List<NxLetfFund> funds = NxLetfFlow.ParseFunds(NxLetfFlow.DefaultFunds);
            for (DateTime d = c.Start.Date; d <= c.End.Date; d = d.AddDays(1)) if (NxUsMarketCalendar.IsTradingDay(d)) o.Days.Add(d);
            int nd = o.Days.Count;

            // --- Agenda macro synthetique (8:30 ET pour CPI/NFP, 14:00 ET pour le FOMC) + leurres.
            o.MacroCsv.Add("datetime_utc,currency,impact,title");
            HashSet<DateTime> daySet = new HashSet<DateTime>(o.Days);
            for (int y = c.Start.Year; y <= c.End.Year; y++)
                for (int m = 1; m <= 12; m++)
                {
                    DateTime nfp = NextTrading(FirstFriday(y, m)), cpi = NextTrading(new DateTime(y, m, 12));
                    List<KeyValuePair<DateTime, string>> ev = new List<KeyValuePair<DateTime, string>>
                    {
                        new KeyValuePair<DateTime, string>(nfp.AddHours(8.5), "Nonfarm Payrolls"),
                        new KeyValuePair<DateTime, string>(cpi.AddHours(8.5), "CPI m/m")
                    };
                    if (new[] { 1, 3, 5, 6, 7, 9, 10, 12 }.Contains(m))
                    {
                        DateTime fomc = NextTrading(ThirdWednesday(y, m));
                        ev.Add(new KeyValuePair<DateTime, string>(fomc.AddHours(14), "FOMC Statement"));
                        DateTime minutes = NextTrading(fomc.AddDays(21));
                        o.MacroCsv.Add(Iso(minutes.AddHours(14), et) + ",USD,High,FOMC Meeting Minutes");
                        if (daySet.Contains(minutes)) o.DecoyDays.Add(minutes);
                    }
                    DateTime adp = NextTrading(nfp.AddDays(-2));
                    o.MacroCsv.Add(Iso(adp.AddHours(8.25), et) + ",USD,High,ADP Nonfarm Employment Change");
                    if (daySet.Contains(adp)) o.DecoyDays.Add(adp);
                    o.MacroCsv.Add(Iso(cpi.AddHours(10), et) + ",EUR,High,ECB Press Conference");
                    foreach (KeyValuePair<DateTime, string> kv in ev)
                    {
                        o.MacroCsv.Add(Iso(kv.Key, et) + ",USD,High," + kv.Value);
                        if (daySet.Contains(kv.Key.Date)) o.MacroDays.Add(kv.Key.Date);
                    }
                }
            o.DecoyDays.ExceptWith(o.MacroDays);
            o.ExcludedCsv.Add("# Jours exclus additionnels (banc d essai)");
            o.ExcludedCsv.Add("date,reason");
            o.ExcludedCsv.Add("2023-07-24,NDX special rebalance");
            o.ExcludedCsv.Add("2020-03-16,Autre : coupe-circuit");

            // --- Profils intrajournaliers (390 minutes : barres 9:31 ... 16:00).
            double[] uVar = new double[390], uVol = new double[390];
            for (int m = 0; m < 390; m++)
            {
                uVar[m] = 1.0 + 1.5 * Math.Exp(-m / 20.0) + 1.0 * Math.Exp(-(389 - m) / 25.0);
                uVol[m] = 1.0 + 2.0 * Math.Exp(-m / 15.0) + 2.5 * Math.Exp(-(389 - m) / 12.0);
            }
            double sVar = uVar.Sum(), sVol = uVol.Sum();
            for (int m = 0; m < 390; m++) { uVar[m] /= sVar; uVol[m] /= sVol; }
            double windowShare = uVol.Skip(360).Sum();

            List<SimBar> ndx = new List<SimBar>(nd * 391), spx = new List<SimBar>(nd * 391), nq = new List<SimBar>(nd * 406), es = new List<SimBar>(nd * 406);
            double pN = c.NdxStart, pS = c.SpxStart, h = 0, gNoise = 0;
            double prevImpactN = 0, prevImpactS = 0;
            double[] nav = Enumerable.Repeat(30.0, funds.Count).ToArray(), aumNoise = new double[funds.Count], aumPrev = new double[funds.Count];
            // Tendance de long terme 2011 -> 2026 (NDX 2 200 -> 25 000, SPX 1 270 -> 6 700) et rappel du log-niveau vers elle,
            // pour que les niveaux (donc S = N / V) restent realistes quel que soit le tirage.
            double span = (new DateTime(2026, 10, 9) - new DateTime(2011, 1, 3)).TotalDays;
            const double rho = 0.9, pull = 0.003;
            double muN = Math.Log(25000 / 2200.0) / (span * 252 / 365.25), muS = Math.Log(6700 / 1270.0) / (span * 252 / 365.25);
            o.AumCsv.Add("date,fund,shares_outstanding,nav");
            o.GexCsv.Add("date,gex,gex_ref");
            double[] retN = new double[420], retS = new double[420];
            Queue<double> winNq = new Queue<double>(), winEs = new Queue<double>();   // volumes 15:30-16:00 des 20 dernieres seances completes
            double[] phase = Enumerable.Range(0, funds.Count).Select(f => 2 * Math.PI * f / funds.Count).ToArray();

            for (int di = 0; di < nd; di++)
            {
                DateTime d = o.Days[di];
                DayOverride ov = c.Override != null ? c.Override(d) : null;
                double x = Math.Max(0, Math.Min(1, (d - new DateTime(2011, 1, 3)).TotalDays / (new DateTime(2026, 10, 9) - new DateTime(2011, 1, 3)).TotalDays));
                bool half = NxUsMarketCalendar.IsHalfDay(d);
                bool noisy = o.MacroDays.Contains(d) || NxUsMarketCalendar.IsQuadWitching(d);
                TimeSpan offset = TimeZoneInfo.ConvertTime(d.AddHours(12), et, nt) - d.AddHours(12);

                h = 0.98 * h + 0.08 * g.N();
                double sigN = 0.0125 * Math.Exp(h - 0.08), sigS = 0.0095 * Math.Exp(h - 0.08);
                gNoise = 0.7 * gNoise + 0.71 * g.N();
                double gex = 1.5e9 - 4.0e9 * h + 1.5e9 * gNoise;
                if (ov != null && !double.IsNaN(ov.Gex)) gex = ov.Gex;
                o.Gex[d] = gex;
                o.GexCsv.Add(d.ToString("yyyy-MM-dd", CultureInfo.InvariantCulture) + "," + gex.ToString("F0", CultureInfo.InvariantCulture) + ","
                             + (gex + 0.6e9 * g.N()).ToString("F0", CultureInfo.InvariantCulture));

                // Actif net de la veille et flux "vrai" par unite de rendement (formule exacte, NAV de la veille).
                double kN = 0, kS = 0;
                for (int f = 0; f < funds.Count; f++)
                {
                    if (di == 0) aumPrev[f] = Aum0[f] * Math.Pow(Aum1[f] / Aum0[f], x) * Math.Exp(0.35 * Math.Sin(2 * Math.PI * x * 15.8 / 5.0 + phase[f]));
                    if (funds[f].Index == "NDX") kN += aumPrev[f] * funds[f].LeverageFactor; else kS += aumPrev[f] * funds[f].LeverageFactor;
                }
                double vBaseNq = 250000 * Math.Pow(600000 / 250000.0, x), vBaseEs = 2.0e6 * Math.Pow(1.6e6 / 2.0e6, x);
                // Liquidite de reference = volume moyen 15:30-16:00 des 20 dernieres seances (premisse de la fiche).
                double vExpNq = winNq.Count >= 20 ? winNq.Average() : vBaseNq * windowShare, vExpEs = winEs.Count >= 20 ? winEs.Average() : vBaseEs * windowShare;
                double volWinNq = 0, volWinEs = 0;

                // Nuit : diffusion + reversal de l impact LETF de la veille.
                double z1 = g.N(), z2 = rho * z1 + Math.Sqrt(1 - rho * rho) * g.N();
                double tgtN = Math.Log(2200) + x * Math.Log(25000 / 2200.0), tgtS = Math.Log(1270) + x * Math.Log(6700 / 1270.0);
                double onN = muN * 0.2 - pull * (Math.Log(pN) - tgtN) + 0.4 * sigN * z1 - c.Reversal * prevImpactN;
                double onS = muS * 0.2 - pull * (Math.Log(pS) - tgtS) + 0.4 * sigS * z2 - c.Reversal * prevImpactS;
                int M = half ? 210 : 390;
                for (int m = 0; m < M; m++)
                {
                    double a = g.N(), b = rho * a + Math.Sqrt(1 - rho * rho) * g.N();
                    double ev = noisy && m >= 360 ? c.EventNoise : 1.0;
                    retN[m] = muN * 0.8 / 390 + sigN * Math.Sqrt(0.84 * uVar[m]) * a * ev;
                    retS[m] = muS * 0.8 / 390 + sigS * Math.Sqrt(0.84 * uVar[m]) * b * ev;
                }
                if (ov != null && M > 355)
                {
                    if (!double.IsNaN(ov.RNdx1525)) { double cum = onN; for (int m = 0; m <= 354; m++) cum += retN[m]; double adj = (Math.Log(1 + ov.RNdx1525) - cum) / 355; for (int m = 0; m <= 354; m++) retN[m] += adj; }
                    if (!double.IsNaN(ov.RSpx1525)) { double cum = onS; for (int m = 0; m <= 354; m++) cum += retS[m]; double adj = (Math.Log(1 + ov.RSpx1525) - cum) / 355; for (int m = 0; m <= 354; m++) retS[m] += adj; }
                }

                // Chemin minute par minute ; derive de fenetre calculee a 15:30 (apres la barre de 15:30).
                double openN = pN * Math.Exp(onN), openS = pS * Math.Exp(onS), prevCloseN = pN, prevCloseS = pS;
                double cN = openN, cS = openS, p1525N = double.NaN, p1525S = double.NaN, driftN = 0, driftS = 0, impactN = 0, impactS = 0;
                double basis = 0.0015 + 0.001 * Math.Sin(2 * Math.PI * di / 63.0);
                double vDayNq = vBaseNq * Math.Exp(0.25 * g.N()) * (0.7 + 0.3 * Math.Exp(h)), vDayEs = vBaseEs * Math.Exp(0.25 * g.N()) * (0.7 + 0.3 * Math.Exp(h));
                for (int m = 0; m < M; m++)
                {
                    double rn = retN[m] + (m >= 360 ? driftN / 30.0 : 0.0), rs = retS[m] + (m >= 360 ? driftS / 30.0 : 0.0);
                    if (ov != null && m >= 360 && !double.IsNaN(ov.WindowMove)) { rn += Math.Log(1 + ov.WindowMove) / 30.0; rs += Math.Log(1 + ov.WindowMove) / 30.0; }
                    if (ov != null && m == 369 && !double.IsNaN(ov.ShockAt1540)) { rn += Math.Log(1 + ov.ShockAt1540); rs += Math.Log(1 + ov.ShockAt1540); }
                    double oN = cN, oS = cS;
                    cN = oN * Math.Exp(rn); cS = oS * Math.Exp(rs);
                    double smN = sigN * Math.Sqrt(0.84 * uVar[Math.Min(m, 389)]), smS = sigS * Math.Sqrt(0.84 * uVar[Math.Min(m, 389)]);
                    double hN = Math.Max(oN, cN) * Math.Exp(Math.Abs(g.N()) * 0.3 * smN), lN = Math.Min(oN, cN) * Math.Exp(-Math.Abs(g.N()) * 0.3 * smN);
                    double hS = Math.Max(oS, cS) * Math.Exp(Math.Abs(g.N()) * 0.3 * smS), lS = Math.Min(oS, cS) * Math.Exp(-Math.Abs(g.N()) * 0.3 * smS);
                    DateTime tNt = d.Add(new TimeSpan(9, 31 + m, 0)) + offset;
                    ndx.Add(new SimBar(tNt, R2(oN), R2(hN), R2(lN), R2(cN), 0));
                    spx.Add(new SimBar(tNt, R2(oS), R2(hS), R2(lS), R2(cS), 0));
                    double eb = Math.Exp(basis);
                    double vn = Math.Max(1, Math.Round(vDayNq * uVol[Math.Min(m, 389)] * Math.Exp(0.3 * g.N() - 0.045)));
                    double ve = Math.Max(1, Math.Round(vDayEs * uVol[Math.Min(m, 389)] * Math.Exp(0.3 * g.N() - 0.045)));
                    nq.Add(Fut(tNt, oN * eb, hN * eb, lN * eb, cN * eb, vn));
                    es.Add(Fut(tNt, oS * eb, hS * eb, lS * eb, cS * eb, ve));
                    if (m >= 360) { volWinNq += vn; volWinEs += ve; }
                    if (m == 354) { p1525N = cN; p1525S = cS; }
                    if (m == 359)
                    {
                        double rtN = p1525N / prevCloseN - 1, rtS = p1525S / prevCloseS - 1;
                        double sN = kN * rtN / (20.0 * p1525N * vExpNq), sS = kS * rtS / (50.0 * p1525S * vExpEs);
                        double damp = gex < 0 ? 1.0 : c.LongGammaDamping;
                        impactN = c.Kappa * sN * damp; impactS = c.Kappa * sS * damp;
                        driftN = impactN + c.MomentumOpen * (cN / openN - 1) + c.MomentumDay * rtN;
                        driftS = impactS + c.MomentumOpen * (cS / openS - 1) + c.MomentumDay * rtS;
                        o.TrueS[d] = new[] { sN, sS };
                    }
                }
                // Futures : 15 minutes apres la cloture de l indice (RTH CME 9:30-16:15 ET, 13:15 les demi-seances).
                double fN = cN, fS = cS;
                for (int m = M; m < M + 15; m++)
                {
                    double a = g.N(), b = rho * a + Math.Sqrt(1 - rho * rho) * g.N();
                    double oN = fN, oS = fS;
                    fN = oN * Math.Exp(0.3 * sigN * Math.Sqrt(0.84 * uVar[389]) * a);
                    fS = oS * Math.Exp(0.3 * sigS * Math.Sqrt(0.84 * uVar[389]) * b);
                    DateTime tNt = d.Add(new TimeSpan(9, 31 + m, 0)) + offset;
                    double eb = Math.Exp(basis);
                    nq.Add(Fut(tNt, oN * eb, Math.Max(oN, fN) * eb, Math.Min(oN, fN) * eb, fN * eb, Math.Max(1, Math.Round(vDayNq * uVol[0] * 0.05))));
                    es.Add(Fut(tNt, oS * eb, Math.Max(oS, fS) * eb, Math.Min(oS, fS) * eb, fS * eb, Math.Max(1, Math.Round(vDayEs * uVol[0] * 0.05))));
                }

                if (M == 390) { winNq.Enqueue(volWinNq); winEs.Enqueue(volWinEs); while (winNq.Count > 20) winNq.Dequeue(); while (winEs.Count > 20) winEs.Dequeue(); }
                // Cloture, NAV a levier exacte, actif net (tendance + cycle + bruit persistant + co-mouvement avec la NAV).
                double rccN = cN / pN - 1, rccS = cS / pS - 1;
                pN = cN; pS = cS;
                prevImpactN = impactN; prevImpactS = impactS;
                for (int f = 0; f < funds.Count; f++)
                {
                    double r = funds[f].Index == "NDX" ? rccN : rccS;
                    nav[f] *= Math.Max(0.05, 1 + funds[f].Leverage * r);
                    aumNoise[f] = 0.995 * aumNoise[f] + 0.03 * g.N() + 0.5 * funds[f].Leverage * r;
                    double a = Aum0[f] * Math.Pow(Aum1[f] / Aum0[f], x) * Math.Exp(aumNoise[f] + 0.35 * Math.Sin(2 * Math.PI * x * 15.8 / 5.0 + phase[f]));
                    aumPrev[f] = a;
                    o.AumCsv.Add(string.Format(CultureInfo.InvariantCulture, "{0:yyyy-MM-dd},{1},{2:F0},{3:F6}", d, funds[f].Symbol, a / nav[f], nav[f]));
                }
            }

            o.Market.Add(new SimInstrument { Name = c.NdxName, PointValue = 1, TickSize = 0.01, Type = InstrumentType.Index, Bars = ndx, SessionEnd = new TimeSpan(16, 0, 0) });
            o.Market.Add(new SimInstrument { Name = c.SpxName, PointValue = 1, TickSize = 0.01, Type = InstrumentType.Index, Bars = spx, SessionEnd = new TimeSpan(16, 0, 0) });
            o.Market.Add(new SimInstrument { Name = c.NqName, PointValue = 20, TickSize = 0.25, Type = InstrumentType.Future, Bars = nq });
            o.Market.Add(new SimInstrument { Name = c.EsName, PointValue = 50, TickSize = 0.25, Type = InstrumentType.Future, Bars = es });
            return o;
        }

        private static double R2(double x) { return Math.Round(x, 2); }
        private static double Q(double x) { return Math.Round(x * 4.0) / 4.0; }

        private static SimBar Fut(DateTime t, double o, double h, double l, double c, double v)
        {
            double oo = Q(o), cc = Q(c);
            return new SimBar(t, oo, Math.Max(Q(h), Math.Max(oo, cc)), Math.Min(Q(l), Math.Min(oo, cc)), cc, v);
        }

        /// <summary>Ecrit letf_aum.csv, gex.csv, macro_events.csv, letf_excluded_days.csv dans le dossier de donnees Nexus.</summary>
        public static void WriteFiles(SynthOutput o, string dataDir, bool withGex = true)
        {
            Directory.CreateDirectory(dataDir);
            File.WriteAllLines(Path.Combine(dataDir, "letf_aum.csv"), o.AumCsv);
            string gexPath = Path.Combine(dataDir, "gex.csv");
            if (withGex) File.WriteAllLines(gexPath, o.GexCsv); else if (File.Exists(gexPath)) File.Delete(gexPath);
            File.WriteAllLines(Path.Combine(dataDir, "macro_events.csv"), o.MacroCsv);
            File.WriteAllLines(Path.Combine(dataDir, "letf_excluded_days.csv"), o.ExcludedCsv);
        }
    }
}
