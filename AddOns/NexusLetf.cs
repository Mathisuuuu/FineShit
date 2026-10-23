// =============================================================================
//  NexusLetf.cs   (NinjaTrader 8 / NinjaScript - bibliotheque partagee)
//
//  Outils purs de la FICHE 15 - rebalancement des ETF a levier (LETF), NQ/ES
//  en fin de seance. Aucun type NinjaScript : tout est testable hors NinjaTrader.
//
//    NxLetfFund / NxLetfFlow     fonds sources, flux F = A L(L-1) r / (1 + L r), contrats
//    NxLetfAumStore              actif net de la veille (parts x NAV), creations nettes, tendance 5 j
//    NxGexStore                  GEX agrege des dealers (SPX + NDX + QQQ) et regime gamma
//    NxUsMarketCalendar          feries NYSE, demi-seances, quatre sorcieres
//    NxLetfExclusionCalendar     jours exclus (FOMC, CPI, NFP, demi-seances, quad witching, NDX)
//    NxMinuteDay / NxBarAggregator   barres 1 min d une seance (prix a heure fixe, volume de
//                                fenetre, vol realisee) et barres 30 min (ATR de Wilder)
//    NxRollingQuantile           seuil q70 glissant sur 250 seances
//    NxLetfSignal / NxLetfSizing S_t, Score_t, taille
//    NxNeweyWest                 MCO + erreurs-types HAC de Newey-West (noyau de Bartlett)
//    NxLetfResearch              regression principale, 5 tests d identification, IS/OOS,
//                                walk-forward, criteres d acceptation, suivi des risques
//
//  Source : Barbon, Beckmeyer, Buraschi, Moerke, "Liquidity Provision to Leveraged
//  ETFs and Equity Options Rebalancing Flows" (SSRN 3925725) ; Cheng & Madhavan
//  (2009) pour le flux de rebalancement.
// =============================================================================

#region Using declarations
using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Linq;
using System.Text;
#endregion

namespace NinjaTrader.NinjaScript.AddOns.Nexus
{
    /// <summary>Formule du flux de rebalancement d un LETF (A = parts x NAV de la veille).</summary>
    public enum NxLetfFlowFormula
    {
        /// <summary>Fiche 15, etape 1 : F = A L(L-1) r / (1 + L r).</summary>
        Fiche,
        /// <summary>F = A L(L-1) r : exact quand A est l actif net de la VEILLE (Cheng-Madhavan 2009).</summary>
        NavVeilleExacte
    }

    public enum NxLetfGammaRegime { Inconnu, Court, Long }

    /// <summary>Traitement d un jour sans GEX connu.</summary>
    public enum NxLetfGammaUnknown { PoidsUn, PoidsRegimeLong, PasDeTrade }

    /// <summary>Regle d instrument : une position par jour (NQ prioritaire, ES en secours) ou les deux.</summary>
    public enum NxLetfInstrumentRule { PrioritaireEtSecours, PrioritairePuisSecondSiLesDeux, PrioritaireSeulement }

    // =========================================================================
    //  Fonds et flux
    // =========================================================================
    public class NxLetfFund
    {
        public string Symbol = "";
        public double Leverage;
        public string Index = "";

        /// <summary>L(L-1) : 6 pour +3, 2 pour +2, 6 pour -2, 12 pour -3.</summary>
        public double LeverageFactor { get { return Leverage * (Leverage - 1.0); } }

        public override string ToString() { return Symbol + "(" + Leverage.ToString("+0.##;-0.##", CultureInfo.InvariantCulture) + "x " + Index + ")"; }
    }

    public static class NxLetfFlow
    {
        /// <summary>Minutes de seance reguliere par an (252 x 390) : annualisation des rendements 1 minute.</summary>
        public const double RthMinutesPerYear = 252.0 * 390.0;

        public const string DefaultFunds = "TQQQ=3:NDX;SQQQ=-3:NDX;QLD=2:NDX;QID=-2:NDX;UPRO=3:SPX;SPXU=-3:SPX;SPXL=3:SPX;SPXS=-3:SPX;SSO=2:SPX;SDS=-2:SPX";

        /// <summary>Flux de rebalancement en dollars (signe = sens des achats ; meme signe que r pour tout L hors [0 ; 1]).</summary>
        public static double Flow(double aum, double leverage, double r, NxLetfFlowFormula formula)
        {
            return FlowWithFactor(aum, leverage, leverage * (leverage - 1.0), r, formula);
        }

        /// <summary>Meme flux avec un facteur impose a la place de L(L-1) (placebo de levier, test 4).</summary>
        public static double FlowWithFactor(double aum, double leverage, double factor, double r, NxLetfFlowFormula formula)
        {
            if (!NxMath.Ok(aum) || !NxMath.Ok(leverage) || !NxMath.Ok(factor) || !NxMath.Ok(r)) return double.NaN;
            if (formula == NxLetfFlowFormula.NavVeilleExacte) return aum * factor * r;
            double d = 1.0 + leverage * r;
            return d > 1e-9 ? aum * factor * r / d : double.NaN;
        }

        /// <summary>N = F / (multiplicateur x niveau de l indice) : 20 $/point pour NQ, 50 $/point pour ES.</summary>
        public static double Contracts(double flowUsd, double multiplier, double indexLevel)
        {
            if (!NxMath.Ok(flowUsd) || !(multiplier > 0) || !(indexLevel > 0)) return double.NaN;
            return flowUsd / (multiplier * indexLevel);
        }

        /// <summary>"TQQQ=3:NDX;SQQQ=-3:NDX" -> fonds (indice en majuscules). Entrees invalides ignorees.</summary>
        public static List<NxLetfFund> ParseFunds(string spec)
        {
            List<NxLetfFund> list = new List<NxLetfFund>();
            foreach (KeyValuePair<string, string> kv in NxText.ParseMap(spec))
            {
                string v = kv.Value ?? "";
                int k = v.IndexOf(':');
                if (k <= 0) continue;
                double lev = NxCsv.ParseDouble(v.Substring(0, k));
                string idx = v.Substring(k + 1).Trim().ToUpperInvariant();
                if (!NxMath.Ok(lev) || lev == 0 || idx.Length == 0) continue;
                list.Add(new NxLetfFund { Symbol = kv.Key.Trim().ToUpperInvariant(), Leverage = lev, Index = idx });
            }
            return list;
        }
    }

    // =========================================================================
    //  Actif net des LETF (parts en circulation x NAV), creations nettes
    // =========================================================================
    public class NxLetfAumRow
    {
        public DateTime Date;
        public double Shares = double.NaN;
        public double Nav = double.NaN;
        public double Aum = double.NaN;
        public double NetFlowUsd = double.NaN;

        /// <summary>Actif net : colonne aum si fournie, sinon parts x NAV.</summary>
        public double Value { get { return NxMath.Ok(Aum) ? Aum : (NxMath.Ok(Shares) && NxMath.Ok(Nav) ? Shares * Nav : double.NaN); } }
    }

    public class NxLetfAumStore
    {
        private readonly Dictionary<string, List<NxLetfAumRow>> rows = new Dictionary<string, List<NxLetfAumRow>>(StringComparer.OrdinalIgnoreCase);
        public bool Loaded { get { return rows.Count > 0; } }
        public bool HasNetFlows { get; private set; }
        public IEnumerable<string> Funds { get { return rows.Keys; } }

        /// <summary>
        /// CSV : date, fund, shares_outstanding, nav [, aum] [, net_flow_usd].
        /// date = jour de la NAV et des parts ; utilisees pour les seances STRICTEMENT posterieures (veille).
        /// net_flow_usd = creations - rachats estimes du jour date (connus a 15:25), en dollars ; optionnel.
        /// </summary>
        public int Load(string path, out string message)
        {
            rows.Clear();
            HasNetFlows = false;
            string[] h;
            List<string[]> data = NxCsv.ReadRows(path, out h);
            int cd = NxCsv.Col(h, "date", "as_of", "nav_date", "trade_date");
            int cf = NxCsv.Col(h, "fund", "symbol", "ticker", "etf");
            int cs = NxCsv.Col(h, "shares_outstanding", "shares", "parts", "so");
            int cn = NxCsv.Col(h, "nav", "nav_per_share", "vl");
            int ca = NxCsv.Col(h, "aum", "net_assets", "total_net_assets", "actif_net");
            int cflow = NxCsv.Col(h, "net_flow_usd", "net_creations_usd", "flow_usd", "creations_nettes");
            if (cd < 0 || cf < 0 || ((cs < 0 || cn < 0) && ca < 0))
            {
                message = "actif net LETF absent ou colonnes manquantes (date, fund, shares_outstanding, nav [, aum, net_flow_usd]) : " + path;
                return 0;
            }
            int n = 0;
            foreach (string[] r in data)
            {
                DateTime d;
                if (!NxCsv.TryParseDate(NxCsv.Get(r, cd), out d)) continue;
                string f = NxCsv.Get(r, cf).Trim();
                if (f.Length == 0) continue;
                NxLetfAumRow row = new NxLetfAumRow
                {
                    Date = d.Date,
                    Shares = cs >= 0 ? NxCsv.ParseDouble(NxCsv.Get(r, cs)) : double.NaN,
                    Nav = cn >= 0 ? NxCsv.ParseDouble(NxCsv.Get(r, cn)) : double.NaN,
                    Aum = ca >= 0 ? NxCsv.ParseDouble(NxCsv.Get(r, ca)) : double.NaN,
                    NetFlowUsd = cflow >= 0 ? NxCsv.ParseDouble(NxCsv.Get(r, cflow)) : double.NaN
                };
                Add(f, row);
                n++;
            }
            Sort();
            message = string.Format(CultureInfo.InvariantCulture, "{0} lignes d actif net pour {1} fonds{2}", n, rows.Count,
                HasNetFlows ? " (creations nettes du jour fournies)" : " (pas de creations nettes : tendance des parts 5 j en variable de controle)");
            return n;
        }

        public void Add(string fund, NxLetfAumRow row)
        {
            if (string.IsNullOrWhiteSpace(fund) || row == null) return;
            List<NxLetfAumRow> l;
            if (!rows.TryGetValue(fund.Trim(), out l)) { l = new List<NxLetfAumRow>(); rows[fund.Trim()] = l; }
            l.Add(row);
            if (NxMath.Ok(row.NetFlowUsd)) HasNetFlows = true;
        }

        public void Sort()
        {
            foreach (List<NxLetfAumRow> l in rows.Values)
            {
                l.Sort((a, b) => a.Date.CompareTo(b.Date));
                for (int i = l.Count - 1; i > 0; i--) if (l[i].Date == l[i - 1].Date) l.RemoveAt(i - 1);   // doublon : derniere ligne gardee
            }
        }

        /// <summary>Indice de la derniere ligne datee STRICTEMENT avant day (-1 si aucune).</summary>
        private static int LastBefore(List<NxLetfAumRow> l, DateTime day)
        {
            int lo = 0, hi = l.Count - 1, best = -1;
            while (lo <= hi)
            {
                int mid = (lo + hi) / 2;
                if (l[mid].Date < day.Date) { best = mid; lo = mid + 1; } else hi = mid - 1;
            }
            return best;
        }

        /// <summary>A_i = parts x NAV de la veille (derniere ligne avant day, au plus maxStaleDays jours calendaires).</summary>
        public double AumBefore(string fund, DateTime day, int maxStaleDays)
        {
            List<NxLetfAumRow> l;
            if (fund == null || !rows.TryGetValue(fund, out l)) return double.NaN;
            int i = LastBefore(l, day);
            if (i < 0) return double.NaN;
            if (maxStaleDays > 0 && (day.Date - l[i].Date).TotalDays > maxStaleDays) return double.NaN;
            return l[i].Value;
        }

        /// <summary>Creations nettes estimees du jour (dollars, + = creations), NaN si inconnues.</summary>
        public double NetFlowOn(string fund, DateTime day)
        {
            List<NxLetfAumRow> l;
            if (fund == null || !rows.TryGetValue(fund, out l)) return double.NaN;
            int i = LastBefore(l, day.Date.AddDays(1));
            return i >= 0 && l[i].Date == day.Date ? l[i].NetFlowUsd : double.NaN;
        }

        /// <summary>
        /// Variation d exposition due aux parts sur n seances (dollars) : L x (parts(t-1) - parts(t-1-n)) x NAV(t-1).
        /// Variable de controle quand les creations du jour sont inconnues.
        /// </summary>
        public double ExposureTrend(string fund, double leverage, DateTime day, int n)
        {
            List<NxLetfAumRow> l;
            if (fund == null || !rows.TryGetValue(fund, out l)) return double.NaN;
            int i = LastBefore(l, day);
            int j = i - n;
            if (i < 0 || j < 0) return double.NaN;
            double si = l[i].Shares, sj = l[j].Shares, nav = l[i].Nav;
            if (!NxMath.Ok(si) || !NxMath.Ok(sj) || !NxMath.Ok(nav)) return double.NaN;
            return leverage * (si - sj) * nav;
        }
    }

    // =========================================================================
    //  GEX agrege des dealers et regime gamma
    // =========================================================================
    public class NxGexStore
    {
        private readonly List<DateTime> dates = new List<DateTime>();
        private readonly List<double> gex = new List<double>();
        private readonly List<double> gexRef = new List<double>();
        public int Count { get { return dates.Count; } }
        public bool Loaded { get { return dates.Count > 0; } }
        public bool HasReference { get { return gexRef.Any(NxMath.Ok); } }

        /// <summary>
        /// CSV : date, gex [, gex_ref] [, underlying]. date = seance a laquelle la valeur s applique (calculee avant
        /// l ouverture, OI de la veille). gex en $ par mouvement de 1 % ; plusieurs sous-jacents (SPX, NDX, QQQ) sont sommes.
        /// gex_ref = source tierce (SpotGamma, SqueezeMetrics) pour controler la reconstruction maison.
        /// </summary>
        public int Load(string path, out string message)
        {
            dates.Clear(); gex.Clear(); gexRef.Clear();
            string[] h;
            List<string[]> data = NxCsv.ReadRows(path, out h);
            int cd = NxCsv.Col(h, "date", "available_date", "trade_date");
            int cg = NxCsv.Col(h, "gex", "gex_usd", "gex_usd_per_pct", "net_gex", "gamma", "value");
            int cr = NxCsv.Col(h, "gex_ref", "gex_reference", "gex_tiers", "gex_spotgamma", "gex_squeezemetrics");
            int cu = NxCsv.Col(h, "underlying", "symbol", "index", "sous_jacent");
            if (cd < 0 || cg < 0) { message = "GEX absent ou colonnes manquantes (date, gex [, gex_ref, underlying]) : " + path; return 0; }
            SortedDictionary<DateTime, double[]> agg = new SortedDictionary<DateTime, double[]>();
            foreach (string[] r in data)
            {
                DateTime d;
                if (!NxCsv.TryParseDate(NxCsv.Get(r, cd), out d)) continue;
                double g = NxCsv.ParseDouble(NxCsv.Get(r, cg));
                double gr = cr >= 0 ? NxCsv.ParseDouble(NxCsv.Get(r, cr)) : double.NaN;
                if (!NxMath.Ok(g)) continue;
                double[] a;
                if (!agg.TryGetValue(d.Date, out a)) { a = new[] { 0.0, double.NaN }; agg[d.Date] = a; }
                if (cu >= 0) { a[0] += g; if (NxMath.Ok(gr)) a[1] = (NxMath.Ok(a[1]) ? a[1] : 0.0) + gr; }
                else { a[0] = g; a[1] = gr; }
            }
            foreach (KeyValuePair<DateTime, double[]> kv in agg) Add(kv.Key, kv.Value[0], kv.Value[1]);
            message = string.Format(CultureInfo.InvariantCulture, "{0} jours de GEX ({1:P0} en regime court gamma){2}", dates.Count,
                dates.Count > 0 ? gex.Count(x => x < 0) / (double)dates.Count : 0.0, HasReference ? ", source tierce fournie" : "");
            return dates.Count;
        }

        /// <summary>Ajout chronologique (simulateur, tests).</summary>
        public void Add(DateTime day, double g, double gRef)
        {
            if (dates.Count > 0 && day.Date <= dates[dates.Count - 1]) return;
            dates.Add(day.Date); gex.Add(g); gexRef.Add(gRef);
        }

        /// <summary>Derniere valeur datee au plus tard day (au plus maxStaleDays jours calendaires).</summary>
        public bool TryGet(DateTime day, int maxStaleDays, out double g, out double gRef)
        {
            g = gRef = double.NaN;
            int lo = 0, hi = dates.Count - 1, best = -1;
            while (lo <= hi)
            {
                int mid = (lo + hi) / 2;
                if (dates[mid] <= day.Date) { best = mid; lo = mid + 1; } else hi = mid - 1;
            }
            if (best < 0) return false;
            if (maxStaleDays > 0 && (day.Date - dates[best]).TotalDays > maxStaleDays) return false;
            g = gex[best]; gRef = gexRef[best];
            return NxMath.Ok(g);
        }

        public static NxLetfGammaRegime Regime(double g)
        {
            if (!NxMath.Ok(g)) return NxLetfGammaRegime.Inconnu;
            return g < 0 ? NxLetfGammaRegime.Court : NxLetfGammaRegime.Long;
        }

        /// <summary>w(G) : 1 en court gamma, 0.3 en long gamma (a calibrer) ; regle choisie si inconnu.</summary>
        public static double Weight(NxLetfGammaRegime regime, bool useFilter, double wShort, double wLong, NxLetfGammaUnknown unknown, out bool tradeAllowed)
        {
            tradeAllowed = true;
            if (!useFilter) return 1.0;
            switch (regime)
            {
                case NxLetfGammaRegime.Court: return wShort;
                case NxLetfGammaRegime.Long: return wLong;
                default:
                    if (unknown == NxLetfGammaUnknown.PasDeTrade) { tradeAllowed = false; return 1.0; }
                    return unknown == NxLetfGammaUnknown.PoidsRegimeLong ? wLong : 1.0;
            }
        }
    }

    // =========================================================================
    //  Calendrier du marche actions US (NYSE) : feries, demi-seances, echeances
    // =========================================================================
    public static class NxUsMarketCalendar
    {
        private static readonly HashSet<DateTime> SpecialClosures = new HashSet<DateTime>
        {
            new DateTime(2012, 10, 29), new DateTime(2012, 10, 30),   // ouragan Sandy
            new DateTime(2018, 12, 5),                                // obseques G. H. W. Bush
            new DateTime(2025, 1, 9)                                  // obseques J. Carter
        };

        /// <summary>Dimanche de Paques (algorithme gregorien anonyme).</summary>
        public static DateTime Easter(int y)
        {
            int a = y % 19, b = y / 100, c = y % 100, d = b / 4, e = b % 4, f = (b + 8) / 25, g = (b - f + 1) / 3;
            int h = (19 * a + b - d - g + 15) % 30, i = c / 4, k = c % 4, l = (32 + 2 * e + 2 * i - h - k) % 7;
            int m = (a + 11 * h + 22 * l) / 451;
            int month = (h + l - 7 * m + 114) / 31, day = ((h + l - 7 * m + 114) % 31) + 1;
            return new DateTime(y, month, day);
        }

        private static DateTime NthWeekday(int y, int month, DayOfWeek dow, int n)
        {
            DateTime first = new DateTime(y, month, 1);
            int offset = ((int)dow - (int)first.DayOfWeek + 7) % 7;
            return first.AddDays(offset + 7 * (n - 1));
        }

        private static DateTime LastWeekday(int y, int month, DayOfWeek dow)
        {
            DateTime last = new DateTime(y, month, DateTime.DaysInMonth(y, month));
            int offset = ((int)last.DayOfWeek - (int)dow + 7) % 7;
            return last.AddDays(-offset);
        }

        /// <summary>Jour ferie observe (samedi -> vendredi, dimanche -> lundi ; 1er janvier un samedi : pas de report).</summary>
        private static DateTime Observed(DateTime d, bool allowFridayBefore)
        {
            if (d.DayOfWeek == DayOfWeek.Sunday) return d.AddDays(1);
            if (d.DayOfWeek == DayOfWeek.Saturday) return allowFridayBefore ? d.AddDays(-1) : DateTime.MinValue;
            return d;
        }

        public static DateTime Thanksgiving(int y) { return NthWeekday(y, 11, DayOfWeek.Thursday, 4); }

        public static bool IsHoliday(DateTime day)
        {
            DateTime d = day.Date;
            int y = d.Year;
            if (SpecialClosures.Contains(d)) return true;
            if (d == Observed(new DateTime(y, 1, 1), false)) return true;
            if (d == NthWeekday(y, 1, DayOfWeek.Monday, 3)) return true;          // Martin Luther King
            if (d == NthWeekday(y, 2, DayOfWeek.Monday, 3)) return true;          // Presidents Day
            if (d == Easter(y).AddDays(-2)) return true;                           // Vendredi saint
            if (d == LastWeekday(y, 5, DayOfWeek.Monday)) return true;             // Memorial Day
            if (y >= 2022 && d == Observed(new DateTime(y, 6, 19), true)) return true;   // Juneteenth
            if (d == Observed(new DateTime(y, 7, 4), true)) return true;
            if (d == NthWeekday(y, 9, DayOfWeek.Monday, 1)) return true;           // Labor Day
            if (d == Thanksgiving(y)) return true;
            if (d == Observed(new DateTime(y, 12, 25), true)) return true;
            return false;
        }

        public static bool IsTradingDay(DateTime day)
        {
            DateTime d = day.Date;
            return d.DayOfWeek != DayOfWeek.Saturday && d.DayOfWeek != DayOfWeek.Sunday && !IsHoliday(d);
        }

        public static DateTime NextTradingDay(DateTime day)
        {
            DateTime d = day.Date.AddDays(1);
            while (!IsTradingDay(d)) d = d.AddDays(1);
            return d;
        }

        public static DateTime PreviousTradingDay(DateTime day)
        {
            DateTime d = day.Date.AddDays(-1);
            while (!IsTradingDay(d)) d = d.AddDays(-1);
            return d;
        }

        /// <summary>Demi-seance NYSE (cloture 13:00 ET) : 3 juillet (si le 4 tombe du mardi au vendredi), lendemain de Thanksgiving, 24 decembre (lundi-jeudi).</summary>
        public static bool IsHalfDay(DateTime day)
        {
            DateTime d = day.Date;
            if (!IsTradingDay(d)) return false;
            if (d.Month == 7 && d.Day == 3)
            {
                DayOfWeek w = new DateTime(d.Year, 7, 4).DayOfWeek;
                return w >= DayOfWeek.Tuesday && w <= DayOfWeek.Friday;
            }
            if (d == Thanksgiving(d.Year).AddDays(1)) return true;
            if (d.Month == 12 && d.Day == 24) return d.DayOfWeek >= DayOfWeek.Monday && d.DayOfWeek <= DayOfWeek.Thursday;
            return false;
        }

        /// <summary>Echeance mensuelle : 3e vendredi, avancee au jour de bourse precedent s il est ferie.</summary>
        public static DateTime MonthlyExpiration(int y, int month)
        {
            DateTime d = NxCalendar.ThirdFriday(y, month);
            while (!IsTradingDay(d)) d = d.AddDays(-1);
            return d;
        }

        /// <summary>Quatre sorcieres : echeance trimestrielle (mars, juin, septembre, decembre).</summary>
        public static bool IsQuadWitching(DateTime day)
        {
            DateTime d = day.Date;
            return d.Month % 3 == 0 && d == MonthlyExpiration(d.Year, d.Month);
        }

        public static bool IsMonthlyOpex(DateTime day) { return day.Date == MonthlyExpiration(day.Year, day.Month); }

        public static bool IsLastTradingDayOfMonth(DateTime day) { return NextTradingDay(day).Month != day.Month; }
    }

    // =========================================================================
    //  Jours exclus de la fiche 15
    // =========================================================================
    [Flags]
    public enum NxLetfExclusion
    {
        Aucune = 0,
        Fomc = 1,
        Cpi = 2,
        Nfp = 4,
        DemiSeance = 8,
        QuatreSorcieres = 16,
        RebalancementNdx = 32,
        Autre = 64
    }

    public class NxLetfExclusionCalendar
    {
        private readonly Dictionary<DateTime, NxLetfExclusion> days = new Dictionary<DateTime, NxLetfExclusion>();
        public bool UseMacro = true;
        public bool UseHalfDays = true;
        public bool UseQuadWitching = true;
        public bool UseNdxRebalance = true;
        public bool UseOther = true;

        public int MacroDays { get { return days.Count(kv => (kv.Value & (NxLetfExclusion.Fomc | NxLetfExclusion.Cpi | NxLetfExclusion.Nfp)) != 0); } }
        public int FileDays { get { return days.Count; } }

        public void Add(DateTime day, NxLetfExclusion what)
        {
            if (what == NxLetfExclusion.Aucune) return;
            NxLetfExclusion cur;
            days.TryGetValue(day.Date, out cur);
            days[day.Date] = cur | what;
        }

        /// <summary>Categorie d apres un libelle (FOMC, CPI, NFP, demi-seance, quad witching, NDX).</summary>
        public static NxLetfExclusion Classify(string text)
        {
            string s = (text ?? "").ToUpperInvariant();
            NxLetfExclusion e = NxLetfExclusion.Aucune;
            bool notDecision = s.Contains("MINUTES") || s.Contains("COMPTE RENDU") || s.Contains("SPEAK") || s.Contains("MEMBER") || s.Contains("TESTIF") || s.Contains("DISCOURS");
            if (!notDecision && (s.Contains("FOMC") || s.Contains("FEDERAL FUNDS") || s.Contains("FED INTEREST") || s.Contains("INTEREST RATE DECISION")
                                 || s.Contains("FED RATE") || s.Contains("TAUX FED")))
                e |= NxLetfExclusion.Fomc;
            if (s.Contains("CPI") || s.Contains("CONSUMER PRICE") || s.Contains("IPC") || s.Contains("PRIX A LA CONSOMMATION"))
                e |= NxLetfExclusion.Cpi;
            if (!s.Contains("ADP") && (s.Contains("NFP") || s.Contains("NONFARM") || s.Contains("NON-FARM") || s.Contains("NON FARM") || s.Contains("PAYROLL")
                                       || s.Contains("EMPLOYMENT SITUATION") || s.Contains("EMPLOI")))
                e |= NxLetfExclusion.Nfp;
            if (s.Contains("HALF") || s.Contains("DEMI") || s.Contains("EARLY CLOSE"))
                e |= NxLetfExclusion.DemiSeance;
            if (s.Contains("QUAD") || s.Contains("WITCHING") || s.Contains("SORCIER"))
                e |= NxLetfExclusion.QuatreSorcieres;
            if (s.Contains("NDX") || s.Contains("NASDAQ-100") || s.Contains("NASDAQ 100") || s.Contains("REBAL") || s.Contains("RECONSTITUTION"))
                e |= NxLetfExclusion.RebalancementNdx;
            return e == NxLetfExclusion.Aucune ? NxLetfExclusion.Autre : e;
        }

        /// <summary>CSV : date, reason (FOMC, CPI, NFP, demi-seance, quad witching, NDX rebalance, autre).</summary>
        public int LoadExclusionFile(string path, out string message)
        {
            string[] h;
            List<string[]> data = NxCsv.ReadRows(path, out h);
            int cd = NxCsv.Col(h, "date", "day", "jour");
            int cr = NxCsv.Col(h, "reason", "type", "category", "label", "motif", "title");
            if (cd < 0) { message = "jours exclus : fichier absent ou colonne date manquante : " + path; return 0; }
            int n = 0;
            foreach (string[] r in data)
            {
                DateTime d;
                if (!NxCsv.TryParseDate(NxCsv.Get(r, cd), out d)) continue;
                Add(d.Date, Classify(cr >= 0 ? NxCsv.Get(r, cr) : ""));
                n++;
            }
            message = n + " jours exclus lus dans " + Path.GetFileName(path);
            return n;
        }

        /// <summary>Agenda macro des autres fiches (datetime_utc, currency, impact, title) : evenements USD forts FOMC/CPI/NFP.</summary>
        public int LoadMacroFile(string path, TimeZoneInfo eastern, out string message)
        {
            NxMacroCalendar cal = new NxMacroCalendar();
            string msg;
            cal.Load(path, out msg);
            int n = 0;
            foreach (NxMacroEvent ev in cal.Near(new[] { "USD", "US" }, new DateTime(2100, 1, 1), 200 * 366 * 1440, 0, 3))
            {
                NxLetfExclusion c = Classify(ev.Title) & (NxLetfExclusion.Fomc | NxLetfExclusion.Cpi | NxLetfExclusion.Nfp);
                if (c == NxLetfExclusion.Aucune) continue;
                Add(NxTime.FromUtc(ev.Utc, eastern).Date, c);
                n++;
            }
            message = n + " evenements FOMC/CPI/NFP retenus dans " + Path.GetFileName(path);
            return n;
        }

        /// <summary>Motifs d exclusion actifs pour une seance (fichier + regles : demi-seance, quad witching, rebalancement NDX trimestriel).</summary>
        public NxLetfExclusion Check(DateTime day)
        {
            NxLetfExclusion e;
            days.TryGetValue(day.Date, out e);
            if (NxUsMarketCalendar.IsHalfDay(day)) e |= NxLetfExclusion.DemiSeance;
            if (NxUsMarketCalendar.IsQuadWitching(day)) e |= NxLetfExclusion.QuatreSorcieres | NxLetfExclusion.RebalancementNdx;
            NxLetfExclusion active = NxLetfExclusion.Aucune;
            if (UseMacro) active |= NxLetfExclusion.Fomc | NxLetfExclusion.Cpi | NxLetfExclusion.Nfp;
            if (UseHalfDays) active |= NxLetfExclusion.DemiSeance;
            if (UseQuadWitching) active |= NxLetfExclusion.QuatreSorcieres;
            if (UseNdxRebalance) active |= NxLetfExclusion.RebalancementNdx;
            if (UseOther) active |= NxLetfExclusion.Autre;
            return e & active;
        }

        public static string Describe(NxLetfExclusion e) { return e == NxLetfExclusion.Aucune ? "" : e.ToString().Replace(", ", "+"); }
    }

    // =========================================================================
    //  Barres 1 minute d une seance (heure de New York)
    // =========================================================================
    public class NxMinuteDay
    {
        public DateTime Date;
        public readonly List<TimeSpan> T = new List<TimeSpan>(420);
        public readonly List<double> O = new List<double>(420), H = new List<double>(420), L = new List<double>(420), C = new List<double>(420), V = new List<double>(420);

        public NxMinuteDay(DateTime date) { Date = date.Date; }
        public int Count { get { return C.Count; } }
        public TimeSpan LastTime { get { return T.Count > 0 ? T[T.Count - 1] : TimeSpan.Zero; } }

        /// <summary>Barre horodatee a sa cloture (convention NinjaTrader), heures croissantes.</summary>
        public void Add(TimeSpan t, double o, double h, double l, double c, double v)
        {
            if (!NxMath.Ok(c) || c <= 0) return;
            if (T.Count > 0 && t <= T[T.Count - 1]) return;
            T.Add(t); O.Add(NxMath.Ok(o) && o > 0 ? o : c); H.Add(NxMath.Ok(h) ? Math.Max(h, c) : c); L.Add(NxMath.Ok(l) && l > 0 ? Math.Min(l, c) : c);
            C.Add(c); V.Add(NxMath.Ok(v) ? v : 0.0);
        }

        private int LastAtOrBefore(TimeSpan t)
        {
            int lo = 0, hi = T.Count - 1, best = -1;
            while (lo <= hi)
            {
                int mid = (lo + hi) / 2;
                if (T[mid] <= t) { best = mid; lo = mid + 1; } else hi = mid - 1;
            }
            return best;
        }

        /// <summary>Dernier prix connu a l heure t (cloture de la derniere barre horodatee &lt;= t).</summary>
        public double PriceAsOf(TimeSpan t) { int i = LastAtOrBefore(t); return i >= 0 ? C[i] : double.NaN; }

        /// <summary>Prix d ouverture a l heure t : ouverture de la premiere barre horodatee apres t (ex. 9:30 -> barre 9:31).</summary>
        public double OpenAfter(TimeSpan t) { int i = LastAtOrBefore(t) + 1; return i < T.Count ? O[i] : double.NaN; }

        public double VolumeIn(TimeSpan from, TimeSpan to)
        {
            double s = 0;
            for (int i = LastAtOrBefore(from) + 1; i < T.Count && T[i] <= to; i++) s += V[i];
            return s;
        }

        public int CountIn(TimeSpan from, TimeSpan to)
        {
            int n = 0;
            for (int i = LastAtOrBefore(from) + 1; i < T.Count && T[i] <= to; i++) n++;
            return n;
        }

        /// <summary>Vol realisee annualisee des rendements log 1 min des barres de ]from ; to] (moyenne des carres).</summary>
        public double RealizedVolAnn(TimeSpan from, TimeSpan to, double periodsPerYear, int minReturns)
        {
            double ss = 0; int n = 0;
            for (int i = Math.Max(1, LastAtOrBefore(from) + 1); i < T.Count && T[i] <= to; i++)
            {
                double r = Math.Log(C[i] / C[i - 1]);
                if (!NxMath.Ok(r)) continue;
                ss += r * r; n++;
            }
            return n >= Math.Max(1, minReturns) ? Math.Sqrt(ss / n * periodsPerYear) : double.NaN;
        }

        public double ReturnBetween(TimeSpan a, TimeSpan b)
        {
            double pa = PriceAsOf(a), pb = PriceAsOf(b);
            return NxMath.Ok(pa) && NxMath.Ok(pb) && pa > 0 ? pb / pa - 1.0 : double.NaN;
        }
    }

    /// <summary>Agrege des barres 1 min en barres de N minutes de seance reguliere (ATR de Wilder sur ces barres).</summary>
    public class NxBarAggregator
    {
        public readonly NxBarHistory Hist;
        private readonly TimeSpan span, start, end;
        private bool has;
        private DateTime curDay;
        private TimeSpan curEnd;
        private double o, h, l, c, v;

        public NxBarAggregator(string name, int minutes, int atrPeriod, TimeSpan sessionStart, TimeSpan sessionEnd)
        {
            Hist = new NxBarHistory(name, atrPeriod);
            span = TimeSpan.FromMinutes(Math.Max(1, minutes));
            start = sessionStart;
            end = sessionEnd;
        }

        public void Add(DateTime day, TimeSpan t, double bo, double bh, double bl, double bc, double bv)
        {
            if (t <= start || t > end || !NxMath.Ok(bc)) return;
            long k = (long)Math.Ceiling((t - start).Ticks / (double)span.Ticks);
            TimeSpan bucketEnd = start + TimeSpan.FromTicks(k * span.Ticks);
            if (bucketEnd > end) bucketEnd = end;
            if (has && (day.Date != curDay || bucketEnd != curEnd)) Flush();
            if (!has) { has = true; curDay = day.Date; curEnd = bucketEnd; o = bo; h = bh; l = bl; v = 0; }
            h = Math.Max(h, bh); l = Math.Min(l, bl); c = bc; v += bv;
            if (t == bucketEnd) Flush();   // barre complete des sa derniere minute : disponible a l heure de decision
        }

        public void Flush()
        {
            if (!has) return;
            has = false;
            Hist.Add(curDay, curDay + curEnd, o, h, l, c, v);
        }
    }

    /// <summary>Distribution glissante (n dernieres valeurs) et son quantile type 7.</summary>
    public class NxRollingQuantile
    {
        private readonly Queue<double> q = new Queue<double>();
        public readonly int Window;
        public NxRollingQuantile(int window) { Window = Math.Max(1, window); }
        public int Count { get { return q.Count; } }
        public void Add(double v) { if (!NxMath.Ok(v)) return; q.Enqueue(v); while (q.Count > Window) q.Dequeue(); }
        public double Quantile(double p) { return NxMath.Quantile(q, p); }
    }

    // =========================================================================
    //  Signal : flux par fonds -> contrats -> S_t -> Score_t
    // =========================================================================
    public class NxLetfSignalInput
    {
        public DateTime Day;
        public string Index = "";
        public double PrevClose = double.NaN;          // cloture de l indice J-1
        public double LevelAtSignal = double.NaN;      // niveau de l indice a 15:25
        public double Multiplier = double.NaN;         // $ par point du future
        public double AvgWindowVolume = double.NaN;    // V-barre : volume moyen 15:30-16:00 des 20 dernieres seances
        public double Gex = double.NaN;
        public IList<NxLetfFund> Funds;
        public NxLetfAumStore Aum;
        public NxLetfFlowFormula Formula = NxLetfFlowFormula.Fiche;
        public bool PrimaryFlowCorrection = true;
        public int AumMaxStaleDays = 7;
        public bool UseGammaFilter = true;
        public double WeightShortGamma = 1.0;
        public double WeightLongGamma = 0.3;
        public NxLetfGammaUnknown GammaUnknown = NxLetfGammaUnknown.PoidsUn;
        public double PlaceboFactor = 1.0;
        public int TrendDays = 5;
    }

    public class NxLetfSignal
    {
        public bool Ok;
        public string Why = "";
        public double R = double.NaN;
        public double Level = double.NaN;
        public double RebalanceFlowUsd = double.NaN;
        public double PrimaryFlowUsd;
        public double FlowUsd = double.NaN;
        public double Contracts = double.NaN;
        public double S = double.NaN;
        public double SConst = double.NaN;
        public double M = double.NaN;                  // sum A L(L-1) / (mult x niveau x V) : flux par unite de r
        public double SharesTrend = double.NaN;        // tendance d exposition 5 j / (mult x niveau x V)
        public double Weight = double.NaN;
        public double Score = double.NaN;
        public NxLetfGammaRegime Regime = NxLetfGammaRegime.Inconnu;
        public bool GammaAllowsTrade = true;
        public int FundsUsed;
        public int FundsMissing;
        public string TopFund = "";
        public double TopFundShare = double.NaN;

        public static NxLetfSignal Compute(NxLetfSignalInput x)
        {
            NxLetfSignal s = new NxLetfSignal();
            s.Level = x.LevelAtSignal;
            if (!(x.PrevClose > 0) || !(x.LevelAtSignal > 0)) { s.Why = "indice : cloture de la veille ou niveau a l heure du signal indisponible"; return s; }
            s.R = x.LevelAtSignal / x.PrevClose - 1.0;
            double rebal = 0, prim = 0, cons = 0, mult = 0, trend = 0, absSum = 0, top = 0;
            int trendN = 0;
            foreach (NxLetfFund f in x.Funds ?? new List<NxLetfFund>())
            {
                if (!string.Equals(f.Index, x.Index, StringComparison.OrdinalIgnoreCase)) continue;
                double a = x.Aum != null ? x.Aum.AumBefore(f.Symbol, x.Day, x.AumMaxStaleDays) : double.NaN;
                if (!NxMath.Ok(a)) { s.FundsMissing++; continue; }
                s.FundsUsed++;
                double fi = NxLetfFlow.Flow(a, f.Leverage, s.R, x.Formula);
                double pi = 0;
                if (x.PrimaryFlowCorrection)
                {
                    double cr = x.Aum.NetFlowOn(f.Symbol, x.Day);
                    if (NxMath.Ok(cr)) pi = f.Leverage * cr;    // creations nettes C : le fonds doit acheter L x C d exposition (rachats : C < 0)
                }
                if (!NxMath.Ok(fi)) continue;
                rebal += fi; prim += pi;
                cons += NxLetfFlow.FlowWithFactor(a, f.Leverage, x.PlaceboFactor, s.R, x.Formula);
                mult += a * f.LeverageFactor;
                double tr = x.Aum.ExposureTrend(f.Symbol, f.Leverage, x.Day, x.TrendDays);
                if (NxMath.Ok(tr)) { trend += tr; trendN++; }
                double ab = Math.Abs(fi + pi);
                absSum += ab;
                if (ab > top) { top = ab; s.TopFund = f.Symbol; }
            }
            if (s.FundsUsed == 0) { s.Why = "aucun actif net LETF connu pour " + x.Index; return s; }
            s.RebalanceFlowUsd = rebal;
            s.PrimaryFlowUsd = prim;
            s.FlowUsd = rebal + prim;
            s.TopFundShare = absSum > 0 ? top / absSum : double.NaN;
            s.Contracts = NxLetfFlow.Contracts(s.FlowUsd, x.Multiplier, x.LevelAtSignal);
            bool allowed;
            s.Regime = NxGexStore.Regime(x.Gex);
            s.Weight = NxGexStore.Weight(s.Regime, x.UseGammaFilter, x.WeightShortGamma, x.WeightLongGamma, x.GammaUnknown, out allowed);
            s.GammaAllowsTrade = allowed;
            if (!(x.AvgWindowVolume > 0) || !NxMath.Ok(s.Contracts)) { s.Why = "volume moyen de la fenetre indisponible (chauffage)"; return s; }
            double liq = x.Multiplier * x.LevelAtSignal * x.AvgWindowVolume;
            s.S = s.Contracts / x.AvgWindowVolume;
            s.SConst = cons / liq;
            s.M = mult / liq;
            s.SharesTrend = trendN > 0 ? trend / liq : double.NaN;
            s.Score = s.S * s.Weight;
            s.Ok = NxMath.Ok(s.Score);
            if (!s.Ok) s.Why = "score non calculable";
            return s;
        }
    }

    public static class NxLetfSizing
    {
        /// <summary>
        /// Taille (contrats) : cible de risque fixe (fraction du capital = 1 ecart-type du mouvement sur la duree de detention,
        /// estime par la vol realisee 30 min annualisee) x |Score| / seuil, plafonnee a capPct du volume attendu sur la
        /// fenetre (plafond divise par 2 si |r| &gt; extremeMovePct).
        /// </summary>
        public static int Contracts(double absScore, double threshold, double price, double pointValue, double rvAnn, double holdMinutes,
                                    double bankroll, double riskTargetPct, double avgWindowVolume, double volumeCapPct, double absR, double extremeMovePct,
                                    out double raw, out int cap, out string detail)
        {
            raw = double.NaN; cap = 0; detail = "";
            if (!(absScore > 0) || !(threshold > 0)) { detail = "score ou seuil invalide"; return 0; }
            if (!(price > 0) || !(pointValue > 0) || !(rvAnn > 0) || !(holdMinutes > 0)) { detail = "prix ou vol realisee indisponible"; return 0; }
            if (!(bankroll > 0) || !(riskTargetPct > 0)) { detail = "capital ou cible de risque invalide"; return 0; }
            double sigmaHold = rvAnn * Math.Sqrt(holdMinutes / NxLetfFlow.RthMinutesPerYear);
            double riskPerContract = price * pointValue * sigmaHold;
            double baseQty = bankroll * riskTargetPct / 100.0 / riskPerContract;
            raw = baseQty * absScore / threshold;
            bool extreme = extremeMovePct > 0 && absR > extremeMovePct / 100.0;
            double capD = avgWindowVolume > 0 && volumeCapPct > 0 ? avgWindowVolume * volumeCapPct / 100.0 * (extreme ? 0.5 : 1.0) : double.PositiveInfinity;
            cap = double.IsPositiveInfinity(capD) ? int.MaxValue : (int)Math.Floor(capD);
            int q = (int)Math.Floor(Math.Min(raw, capD));
            detail = string.Format(CultureInfo.InvariantCulture, "risque/contrat {0:F0} $ (sigma {1:P3} sur {2:F0} min), base {3:F2} x score/seuil {4:F2} = {5:F2}, plafond {6}{7}",
                riskPerContract, sigmaHold, holdMinutes, baseQty, absScore / threshold, raw, cap == int.MaxValue ? "aucun" : cap.ToString(CultureInfo.InvariantCulture),
                extreme ? " (divise par 2 : |r| > " + extremeMovePct.ToString(CultureInfo.InvariantCulture) + " %)" : "");
            return Math.Max(0, q);
        }
    }

    // =========================================================================
    //  MCO avec erreurs-types de Newey-West
    // =========================================================================
    public class NxHacResult
    {
        public bool Ok;
        public int N;
        public int K;
        public int Lags;
        public string[] Names = new string[0];
        public double[] Coef = new double[0];
        public double[] Se = new double[0];
        public double R2 = double.NaN;
        public double AdjR2 = double.NaN;
        public double Aic = double.NaN;
        public string Note = "";

        public int Index(string name) { return Array.IndexOf(Names, name); }
        public double T(int i) { return i >= 0 && i < Se.Length && Se[i] > 0 ? Coef[i] / Se[i] : double.NaN; }
        public double CoefOf(string name) { int i = Index(name); return i >= 0 ? Coef[i] : double.NaN; }
        public double TOf(string name) { return T(Index(name)); }

        public string Line(string name, string label)
        {
            int i = Index(name);
            if (!Ok || i < 0) return string.Format(CultureInfo.InvariantCulture, "  {0,-28} non estime{1}", label ?? name, Ok ? "" : " (" + Note + ")");
            return string.Format(CultureInfo.InvariantCulture, "  {0,-28} {1,12:G4}  t(NW) = {2,6:F2}", label ?? name, Coef[i], T(i));
        }
    }

    public static class NxNeweyWest
    {
        /// <summary>Regle de Newey-West (1994) : floor(4 (n/100)^(2/9)).</summary>
        public static int AutoLags(int n) { return n <= 1 ? 0 : (int)Math.Floor(4.0 * Math.Pow(n / 100.0, 2.0 / 9.0)); }

        /// <summary>
        /// y = a + X b + e ; lignes avec NaN ignorees ; colonnes constantes retirees ; covariance HAC de Bartlett.
        /// names = noms des colonnes de X ("const" est ajoute en tete). lags &lt; 0 : regle automatique.
        /// </summary>
        public static NxHacResult Ols(IList<double> y, IList<double[]> X, string[] names, int lags)
        {
            NxHacResult res = new NxHacResult();
            int nAll = Math.Min(y.Count, X.Count);
            int kx = names.Length;
            List<int> rows = new List<int>();
            for (int i = 0; i < nAll; i++)
            {
                if (!NxMath.Ok(y[i]) || X[i] == null || X[i].Length != kx) continue;
                bool ok = true;
                for (int j = 0; j < kx; j++) if (!NxMath.Ok(X[i][j])) { ok = false; break; }
                if (ok) rows.Add(i);
            }
            List<int> cols = new List<int>();
            for (int j = 0; j < kx; j++)
            {
                double first = double.NaN; bool varies = false;
                foreach (int i in rows) { double v = X[i][j]; if (!NxMath.Ok(first)) first = v; else if (Math.Abs(v - first) > 1e-15 * Math.Max(1.0, Math.Abs(first))) { varies = true; break; } }
                if (varies) cols.Add(j);
            }
            int p = cols.Count + 1, n = rows.Count;
            res.N = n; res.K = p;
            res.Names = new[] { "const" }.Concat(cols.Select(j => names[j])).ToArray();
            if (n <= p + 1) { res.Note = "echantillon trop petit (" + n + " obs.)"; return res; }

            double[][] Z = new double[n][];
            double[] yy = new double[n];
            for (int r = 0; r < n; r++)
            {
                int i = rows[r];
                double[] z = new double[p];
                z[0] = 1.0;
                for (int c = 0; c < cols.Count; c++) z[c + 1] = X[i][cols[c]];
                Z[r] = z; yy[r] = y[i];
            }
            double[,] xtx = new double[p, p];
            double[] xty = new double[p];
            for (int r = 0; r < n; r++)
                for (int a = 0; a < p; a++)
                {
                    xty[a] += Z[r][a] * yy[r];
                    for (int b = 0; b < p; b++) xtx[a, b] += Z[r][a] * Z[r][b];
                }
            double[,] inv = NxRegression.Invert(xtx);
            if (inv == null) { res.Note = "matrice singuliere"; return res; }
            double[] beta = new double[p];
            for (int a = 0; a < p; a++) { double s = 0; for (int b = 0; b < p; b++) s += inv[a, b] * xty[b]; beta[a] = s; }
            double[] e = new double[n];
            double rss = 0, ym = yy.Average(), tss = 0;
            for (int r = 0; r < n; r++)
            {
                double fit = 0; for (int a = 0; a < p; a++) fit += Z[r][a] * beta[a];
                e[r] = yy[r] - fit; rss += e[r] * e[r]; tss += (yy[r] - ym) * (yy[r] - ym);
            }
            int L = lags < 0 ? AutoLags(n) : Math.Min(lags, n - 1);
            double[,] S = new double[p, p];
            for (int r = 0; r < n; r++)
                for (int a = 0; a < p; a++)
                    for (int b = 0; b < p; b++) S[a, b] += e[r] * e[r] * Z[r][a] * Z[r][b];
            for (int l = 1; l <= L; l++)
            {
                double w = 1.0 - l / (L + 1.0);
                for (int r = l; r < n; r++)
                {
                    double ee = e[r] * e[r - l] * w;
                    for (int a = 0; a < p; a++)
                        for (int b = 0; b < p; b++) S[a, b] += ee * (Z[r][a] * Z[r - l][b] + Z[r - l][a] * Z[r][b]);
                }
            }
            double[] se = new double[p];
            for (int a = 0; a < p; a++)
            {
                double v = 0;
                for (int b = 0; b < p; b++) for (int c = 0; c < p; c++) v += inv[a, b] * S[b, c] * inv[c, a];
                se[a] = v > 0 ? Math.Sqrt(v) : double.NaN;
            }
            res.Coef = beta; res.Se = se; res.Lags = L;
            res.R2 = tss > 0 ? 1.0 - rss / tss : double.NaN;
            res.AdjR2 = NxMath.Ok(res.R2) && n - p > 0 ? 1.0 - (1.0 - res.R2) * (n - 1) / (n - p) : double.NaN;
            res.Aic = rss > 0 ? n * Math.Log(rss / n) + 2.0 * p : double.NaN;
            res.Ok = true;
            return res;
        }
    }

    // =========================================================================
    //  Panel quotidien et protocole de backtest de la fiche 15
    // =========================================================================
    /// <summary>Une ligne par instrument et par seance : signal, controles, rendements de fenetre, reversal, trade.</summary>
    public class NxLetfPanelRow
    {
        public DateTime Date;
        public string Instrument = "";
        public string Index = "";
        public int Priority;
        public NxLetfExclusion Excluded;
        public double R = double.NaN;             // indice : cloture J-1 -> 15:25
        public double RPlacebo = double.NaN;      // indice : cloture J-1 -> 14:25
        public double ROpenEntry = double.NaN;    // future : ouverture 9:30 -> 15:30
        public double ROpenPlacebo = double.NaN;  // future : ouverture 9:30 -> 14:30
        public double Y = double.NaN;             // future : 15:30 -> 16:00
        public double YPlacebo = double.NaN;      // future : 14:30 -> 15:00
        public double S = double.NaN, SPlacebo = double.NaN, SConst = double.NaN, M = double.NaN, SharesTrend = double.NaN;
        public double G = double.NaN, GRef = double.NaN, W = double.NaN, Score = double.NaN, Threshold = double.NaN;
        public double RvEntry = double.NaN;       // vol realisee 30 min avant l entree (annualisee)
        public double RvDay = double.NaN;         // vol realisee 9:30 -> 15:30 (annualisee)
        public double LogVolumeRel = double.NaN;  // log(volume 9:30-15:30 / moyenne 20 seances)
        public double TopFundShare = double.NaN;
        public string TopFund = "";
        public double IndexLevel = double.NaN, FuturePrice = double.NaN, PointValue = double.NaN, TickSize = double.NaN, AvgWindowVolume = double.NaN;
        public double ROvernight = double.NaN;    // future : 16:00 -> ouverture J+1
        public double RMorning = double.NaN;      // future : ouverture J+1 -> 10:30 J+1
        public int Dow;
        public bool MonthEnd;
        public bool Opex;
        public string Decision = "";
        public bool Traded;
        public int Direction;
        public int Qty;
        public double GrossPnl = double.NaN, NetPnl = double.NaN;

        public bool ShortGamma { get { return NxMath.Ok(G) && G < 0; } }

        public static string CsvHeader
        {
            get
            {
                return "date,instrument,index,priority,excluded,r_close_1525,r_close_1425,r_open_1530,r_open_1430,y_1530_1600,y_1430_1500,s,s_placebo,s_const,m,shares_trend,"
                     + "gex,gex_ref,w,score,threshold,rv_entry,rv_day,log_volume_rel,top_fund,top_fund_share,index_level,future_price,avg_window_volume,"
                     + "r_overnight,r_morning,dow,month_end,opex,decision,traded,direction,qty,gross_pnl,net_pnl";
            }
        }

        public string ToCsv()
        {
            return string.Join(",", new[]
            {
                Date.ToString("yyyy-MM-dd", CultureInfo.InvariantCulture), NxCsv.Escape(Instrument), Index, Priority.ToString(CultureInfo.InvariantCulture),
                NxLetfExclusionCalendar.Describe(Excluded), NxCsv.F(R, 8), NxCsv.F(RPlacebo, 8), NxCsv.F(ROpenEntry, 8), NxCsv.F(ROpenPlacebo, 8),
                NxCsv.F(Y, 8), NxCsv.F(YPlacebo, 8), NxCsv.F(S, 8), NxCsv.F(SPlacebo, 8), NxCsv.F(SConst, 8), NxCsv.F(M, 8), NxCsv.F(SharesTrend, 8),
                NxCsv.F(G, 0), NxCsv.F(GRef, 0), NxCsv.F(W, 3), NxCsv.F(Score, 8), NxCsv.F(Threshold, 8), NxCsv.F(RvEntry, 6), NxCsv.F(RvDay, 6),
                NxCsv.F(LogVolumeRel, 6), TopFund, NxCsv.F(TopFundShare, 4), NxCsv.F(IndexLevel, 2), NxCsv.F(FuturePrice, 2), NxCsv.F(AvgWindowVolume, 0),
                NxCsv.F(ROvernight, 8), NxCsv.F(RMorning, 8), Dow.ToString(CultureInfo.InvariantCulture), MonthEnd ? "1" : "0", Opex ? "1" : "0",
                NxCsv.Escape(Decision), Traded ? "1" : "0", Direction.ToString(CultureInfo.InvariantCulture), Qty.ToString(CultureInfo.InvariantCulture),
                NxCsv.F(GrossPnl, 2), NxCsv.F(NetPnl, 2)
            });
        }
    }

    /// <summary>Trade ferme de la fiche 15 (pour les criteres d acceptation et le stress de couts).</summary>
    public class NxLetfTradeOutcome
    {
        public DateTime Day;
        public string Instrument = "";
        public int Direction;
        public int Qty;
        public double GrossPnl;
        public double NetPnl;
        public double ScoreRatio = double.NaN;     // |Score| / seuil
        public double TickValue;                   // $ par tick et par contrat
        public bool Stopped;
    }

    public class NxLetfResearchConfig
    {
        public DateTime OosStart = new DateTime(2021, 1, 1);
        public int WalkForwardYears = 3;
        public int NwLags = -1;
        public double ThresholdQuantile = 0.70;
        public int ThresholdWindow = 250;
        public int MinThresholdHistory = 250;
        public double MinAbsR = 0.005;
        public bool UseGammaFilter = true;
        public double WeightShortGamma = 1.0;
        public double WeightLongGamma = 0.3;
        public NxLetfGammaUnknown GammaUnknown = NxLetfGammaUnknown.PoidsUn;
        public double CostTicksRoundTrip = 1.0;
        public double StressTicksRoundTrip = 2.0;
        public double CommissionPerSide = 2.5;
        public NxLetfInstrumentRule InstrumentRule = NxLetfInstrumentRule.PrioritaireEtSecours;
        public bool HasNetFlows;
        public double SharpeTarget = 1.0;
        public double WinRateTarget = 0.55;
        public double[] WeightGrid = { 0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0 };
    }

    public class NxLetfResearchResult
    {
        public string MainInstrument = "", ControlInstrument = "";
        public NxHacResult Main, MainWithR, AumTest, Placebo, LeveragePlacebo, Encompassing, ReversalOvernight, ReversalMorning;
        public readonly Dictionary<string, NxHacResult> SlopeByInstrument = new Dictionary<string, NxHacResult>();
        public NxHacResult Control;
        public bool HasGammaTerm;
        public double NqMinusEs = double.NaN, NqMinusEsZ = double.NaN;
        public bool H1, AumOk, NqEsOk, PlaceboOk, LeverageOk, ReversalOk;
        public double IsWeight = double.NaN, IsSharpePanel = double.NaN, OosSharpePanel = double.NaN, WfOosSharpePanel = double.NaN;
        public double OosSharpeTrades = double.NaN, IsSharpeTrades = double.NaN, WinRate = double.NaN, WinRateTopHalf = double.NaN;
        public int Trades, OosTrades;
        public double NetPnl = double.NaN, NetPnlStress = double.NaN;
        public bool SignStable;
        public bool AbandonFlag;
        public string Verdict = "";
    }

    public static class NxLetfResearch
    {
        private static readonly string[] DowNames = { "lundi", "mardi", "mercredi", "jeudi" };

        private static double Annualized(IList<double> daily)
        {
            if (daily == null || daily.Count < 2) return double.NaN;
            double sd = NxMath.StdDev(daily);
            return sd > 0 ? NxMath.Mean(daily) / sd * Math.Sqrt(NxMath.TradingDaysPerYear) : double.NaN;
        }

        private static double Ind(bool b) { return b ? 1.0 : 0.0; }

        /// <summary>Controles X_t : vol realisee, volume du jour, indicatrices calendaires (+ tendance des parts sans creations du jour).</summary>
        private static List<double> Controls(NxLetfPanelRow r, bool sharesTrend)
        {
            List<double> x = new List<double> { r.RvDay, r.LogVolumeRel };
            for (int d = 1; d <= 4; d++) x.Add(Ind(r.Dow == d));
            x.Add(Ind(r.MonthEnd));
            x.Add(Ind(r.Opex));
            if (sharesTrend) x.Add(r.SharesTrend);
            return x;
        }

        private static List<string> ControlNames(bool sharesTrend)
        {
            List<string> n = new List<string> { "vol_realisee_jour", "log_volume_rel" };
            n.AddRange(DowNames);
            n.Add("fin_de_mois");
            n.Add("echeance_mensuelle");
            if (sharesTrend) n.Add("tendance_parts_5j");
            return n;
        }

        /// <summary>y = a + b1 r_open + b2 S + b3 S x 1[G&lt;0] + g'X (+ termes supplementaires).</summary>
        private static NxHacResult MainModel(List<NxLetfPanelRow> rows, Func<NxLetfPanelRow, double> y, Func<NxLetfPanelRow, double> rOpen,
                                             Func<NxLetfPanelRow, double> s, bool gammaTerm, bool sharesTrend, int lags,
                                             Func<NxLetfPanelRow, double[]> extra, string[] extraNames)
        {
            List<double> yy = new List<double>();
            List<double[]> X = new List<double[]>();
            List<string> names = new List<string> { "r_open", "S" };
            if (gammaTerm) names.Add("S_x_court_gamma");
            names.AddRange(ControlNames(sharesTrend));
            if (extraNames != null) names.AddRange(extraNames);
            foreach (NxLetfPanelRow r in rows)
            {
                if (gammaTerm && !NxMath.Ok(r.G)) continue;
                List<double> x = new List<double> { rOpen(r), s(r) };
                if (gammaTerm) x.Add(s(r) * Ind(r.ShortGamma));
                x.AddRange(Controls(r, sharesTrend));
                if (extra != null) x.AddRange(extra(r));
                yy.Add(y(r));
                X.Add(x.ToArray());
            }
            return NxNeweyWest.Ols(yy, X, names.ToArray(), lags);
        }

        private static NxHacResult Simple(List<NxLetfPanelRow> rows, Func<NxLetfPanelRow, double> y, Func<NxLetfPanelRow, double[]> x, string[] names, int lags)
        {
            return NxNeweyWest.Ols(rows.Select(y).ToList(), rows.Select(x).ToList(), names, lags);
        }

        /// <summary>
        /// PnL quotidien simplifie de la regle de trading a partir du panel (sans stop ni arrondi), en unites de risque :
        /// taille = (|Score|/seuil) / vol realisee ; cout = ticks aller-retour + commissions, rapportes au notionnel.
        /// Sert a calibrer w(long gamma) en echantillon et en walk-forward.
        /// </summary>
        public static List<KeyValuePair<DateTime, double>> PanelPnl(List<NxLetfPanelRow> rows, NxLetfResearchConfig cfg, double wLong, double ticks)
        {
            Dictionary<string, NxRollingQuantile> hist = new Dictionary<string, NxRollingQuantile>();
            List<KeyValuePair<DateTime, double>> pnl = new List<KeyValuePair<DateTime, double>>();
            foreach (IGrouping<DateTime, NxLetfPanelRow> day in rows.GroupBy(r => r.Date).OrderBy(g => g.Key))
            {
                double dayPnl = 0;
                bool first = true, firstPassed = false, positioned = false;
                foreach (NxLetfPanelRow r in day.OrderBy(x => x.Priority))
                {
                    NxRollingQuantile q;
                    if (!hist.TryGetValue(r.Instrument, out q)) { q = new NxRollingQuantile(cfg.ThresholdWindow); hist[r.Instrument] = q; }
                    bool allowed;
                    double w = NxGexStore.Weight(NxGexStore.Regime(r.G), cfg.UseGammaFilter, cfg.WeightShortGamma, wLong, cfg.GammaUnknown, out allowed);
                    double score = r.S * w;
                    if (!NxMath.Ok(score)) { first = false; continue; }
                    double thr = q.Count >= cfg.MinThresholdHistory ? q.Quantile(cfg.ThresholdQuantile) : double.NaN;
                    q.Add(Math.Abs(score));
                    bool pass = r.Excluded == NxLetfExclusion.Aucune && Math.Abs(r.R) >= cfg.MinAbsR && NxMath.Ok(thr) && thr > 0
                                && Math.Abs(score) >= thr && allowed && NxMath.Ok(r.Y) && r.RvEntry > 0;
                    bool take = pass;
                    if (cfg.InstrumentRule == NxLetfInstrumentRule.PrioritaireEtSecours) take = pass && !positioned;
                    else if (cfg.InstrumentRule == NxLetfInstrumentRule.PrioritaireSeulement) take = pass && first;
                    else take = pass && (first || firstPassed);
                    if (first) firstPassed = pass;
                    first = false;
                    if (!take) continue;
                    positioned = true;
                    double units = Math.Abs(score) / thr / r.RvEntry;
                    double cost = NxMath.Ok(r.FuturePrice) && r.FuturePrice > 0 && r.PointValue > 0
                        ? (ticks * r.TickSize * r.PointValue + 2.0 * cfg.CommissionPerSide) / (r.FuturePrice * r.PointValue) : 0.0;
                    dayPnl += units * (Math.Sign(r.R) * r.Y - cost);
                }
                pnl.Add(new KeyValuePair<DateTime, double>(day.Key, dayPnl));
            }
            return pnl;
        }

        private static double SharpeBetween(List<KeyValuePair<DateTime, double>> pnl, DateTime from, DateTime to)
        {
            return Annualized(pnl.Where(kv => kv.Key >= from && kv.Key < to).Select(kv => kv.Value).ToList());
        }

        private static double BestWeight(Dictionary<double, List<KeyValuePair<DateTime, double>>> byW, DateTime from, DateTime to, double fallback)
        {
            double best = double.NegativeInfinity, wBest = fallback;
            foreach (KeyValuePair<double, List<KeyValuePair<DateTime, double>>> kv in byW.OrderBy(k => Math.Abs(k.Key - fallback)))
            {
                double sr = SharpeBetween(kv.Value, from, to);
                if (NxMath.Ok(sr) && sr > best + 1e-12) { best = sr; wBest = kv.Key; }
            }
            return wBest;
        }

        /// <summary>
        /// Protocole de backtest de la fiche 15 : regression principale (Newey-West), cinq tests d identification,
        /// IS/OOS, walk-forward 3 ans de w(long gamma), criteres d acceptation et suivi du risque de declin.
        /// </summary>
        public static NxLetfResearchResult Analyze(List<NxLetfPanelRow> panel, List<NxLetfTradeOutcome> trades, IList<DateTime> equityDays,
                                                   IList<double> dailyReturns, NxLetfResearchConfig cfg, List<string> lines)
        {
            CultureInfo ci = CultureInfo.InvariantCulture;
            NxLetfResearchResult res = new NxLetfResearchResult();
            List<string> instruments = panel.OrderBy(r => r.Priority).Select(r => r.Instrument).Distinct().ToList();
            lines.Add("--- Fiche 15 : protocole de backtest -----------------------------------------");
            if (instruments.Count == 0) { lines.Add("Panel vide : aucune seance avec signal."); return res; }
            res.MainInstrument = instruments[0];
            res.ControlInstrument = instruments.Count > 1 ? instruments[1] : "";
            bool trend = !cfg.HasNetFlows;
            int lags = cfg.NwLags;

            Func<string, List<NxLetfPanelRow>> sample = name => panel.Where(r => r.Instrument == name && r.Excluded == NxLetfExclusion.Aucune
                                                                               && NxMath.Ok(r.S) && NxMath.Ok(r.Y) && NxMath.Ok(r.ROpenEntry)).OrderBy(r => r.Date).ToList();
            List<NxLetfPanelRow> main = sample(res.MainInstrument);
            double gammaCoverage = main.Count > 0 ? main.Count(r => NxMath.Ok(r.G)) / (double)main.Count : 0.0;
            res.HasGammaTerm = gammaCoverage >= 0.5;
            lines.Add(string.Format(ci, "Echantillon {0} : {1} seances hors jours exclus ({2:yyyy-MM-dd} -> {3:yyyy-MM-dd}), GEX connu {4:P0}, lags Newey-West {5}",
                res.MainInstrument, main.Count, main.Count > 0 ? main[0].Date : DateTime.MinValue, main.Count > 0 ? main[main.Count - 1].Date : DateTime.MinValue,
                gammaCoverage, lags >= 0 ? lags.ToString(ci) : "auto (" + NxNeweyWest.AutoLags(main.Count) + ")"));
            if (!res.HasGammaTerm) lines.Add("  GEX absent ou trop lacunaire : terme S x 1[G<0] retire (beta3 non estime, H1 jugee sur beta2 seul).");
            if (trend) lines.Add("  Creations nettes du jour inconnues : tendance des parts sur 5 j ajoutee aux controles X_t.");

            // --- Regression principale.
            res.Main = MainModel(main, r => r.Y, r => r.ROpenEntry, r => r.S, res.HasGammaTerm, trend, lags, null, null);
            res.MainWithR = MainModel(main, r => r.Y, r => r.ROpenEntry, r => r.S, res.HasGammaTerm, trend, lags, r => new[] { r.R }, new[] { "r_cloture_1525" });
            double b2 = res.Main.CoefOf("S"), t2 = res.Main.TOf("S"), b3 = res.Main.CoefOf("S_x_court_gamma"), t3 = res.Main.TOf("S_x_court_gamma");
            res.H1 = res.Main.Ok && b2 > 0 && t2 >= 1.96 && (!res.HasGammaTerm || (b3 > 0 && t3 >= 1.96));
            lines.Add("Regression principale  r(15:30->16:00) = a + b1 r(ouv->15:30) + b2 S + b3 S.1[G<0] + g'X   [" + res.MainInstrument + "]");
            lines.Add(res.Main.Line("r_open", "b1 r(ouverture->15:30)"));
            lines.Add(res.Main.Line("S", "b2 S"));
            lines.Add(res.Main.Line("S_x_court_gamma", "b3 S x 1[G<0]"));
            lines.Add(string.Format(ci, "  N = {0}, R2 = {1:F4}, R2 ajuste = {2:F4}", res.Main.N, res.Main.R2, res.Main.AdjR2));
            lines.Add("  Robustesse (+ r_t cloture->15:25 en controle) : " + res.MainWithR.Line("S", "b2").Trim() + " | " + res.MainWithR.Line("r_cloture_1525", "r_t").Trim());
            lines.Add("  => H1 " + (res.H1 ? "VALIDEE (b2 > 0 et b3 > 0 significatifs, Newey-West)" : "NON validee"));

            // --- Instrument de controle.
            if (res.ControlInstrument.Length > 0)
            {
                List<NxLetfPanelRow> ctl = sample(res.ControlInstrument);
                res.Control = MainModel(ctl, r => r.Y, r => r.ROpenEntry, r => r.S, res.HasGammaTerm && ctl.Count(r => NxMath.Ok(r.G)) >= ctl.Count / 2, trend, lags, null, null);
                lines.Add("Meme regression sur " + res.ControlInstrument + " : " + res.Control.Line("S", "b2").Trim() + " | " + res.Control.Line("S_x_court_gamma", "b3").Trim());
            }

            // --- Test 1 : variation de l AUM (r x M standardise).
            double mMean = NxMath.Mean(main.Select(r => r.M).Where(NxMath.Ok).ToList()), mSd = NxMath.StdDev(main.Select(r => r.M).Where(NxMath.Ok).ToList());
            if (mSd > 0)
            {
                // Le regime gamma module aussi la pente (w) et peut etre lie a la liquidite : r x 1[G<0] en controle s il est connu.
                List<NxLetfPanelRow> aumRows = res.HasGammaTerm ? main.Where(r => NxMath.Ok(r.G)).ToList() : main;
                res.AumTest = res.HasGammaTerm
                    ? Simple(aumRows, r => r.Y, r => new[] { r.R, r.R * (r.M - mMean) / mSd, (r.M - mMean) / mSd, r.ROpenEntry, r.R * Ind(r.ShortGamma) },
                             new[] { "r", "r_x_aum", "aum", "r_open", "r_x_court_gamma" }, lags)
                    : Simple(aumRows, r => r.Y, r => new[] { r.R, r.R * (r.M - mMean) / mSd, (r.M - mMean) / mSd, r.ROpenEntry },
                             new[] { "r", "r_x_aum", "aum", "r_open" }, lags);
                res.AumOk = res.AumTest.Ok && res.AumTest.CoefOf("r_x_aum") > 0 && res.AumTest.TOf("r_x_aum") >= 1.96;
            }
            lines.Add("Test 1 - variation de l AUM : y = a + c1 r + c2 r.M~ + c3 M~ + c4 r_open" + (res.HasGammaTerm ? " + c5 r.1[G<0]" : "")
                      + " (M~ = flux LETF par unite de r / liquidite, standardise)");
            lines.Add(res.AumTest != null ? res.AumTest.Line("r_x_aum", "c2 r x AUM") : "  AUM constante : test impossible");
            lines.Add("  => " + (res.AumOk ? "OK : le meme rendement a plus d effet quand l AUM LETF est elevee" : "ECHEC : pas d effet AUM distinct du momentum generique"));

            // --- Test 2 : differentiel NQ vs ES.
            foreach (string ins in instruments)
            {
                List<NxLetfPanelRow> rs = sample(ins).Where(r => NxMath.Ok(r.R)).ToList();
                res.SlopeByInstrument[ins] = Simple(rs, r => r.Y, r => new[] { r.R, r.ROpenEntry }, new[] { "r", "r_open" }, lags);
            }
            if (res.ControlInstrument.Length > 0 && res.SlopeByInstrument[res.MainInstrument].Ok && res.SlopeByInstrument[res.ControlInstrument].Ok)
            {
                NxHacResult a = res.SlopeByInstrument[res.MainInstrument], b = res.SlopeByInstrument[res.ControlInstrument];
                int ia = a.Index("r"), ib = b.Index("r");
                res.NqMinusEs = a.Coef[ia] - b.Coef[ib];
                double se = Math.Sqrt(a.Se[ia] * a.Se[ia] + b.Se[ib] * b.Se[ib]);
                res.NqMinusEsZ = se > 0 ? res.NqMinusEs / se : double.NaN;
                res.NqEsOk = res.NqMinusEs > 0 && res.NqMinusEsZ >= 1.645;
                lines.Add(string.Format(ci, "Test 2 - differentiel {0} vs {1} : pente de y sur r_t {2:G4} vs {3:G4}, difference {4:G4} (z = {5:F2}, ecarts-types supposes independants)",
                    res.MainInstrument, res.ControlInstrument, a.Coef[ia], b.Coef[ib], res.NqMinusEs, res.NqMinusEsZ));
                lines.Add("  => " + (res.NqEsOk ? "OK : effet plus marque sur " + res.MainInstrument : "ECHEC : pas d effet plus marque sur " + res.MainInstrument));
            }

            // --- Test 3 : placebo de fenetre (14:30 -> 15:00).
            List<NxLetfPanelRow> plc = panel.Where(r => r.Instrument == res.MainInstrument && r.Excluded == NxLetfExclusion.Aucune
                                                         && NxMath.Ok(r.SPlacebo) && NxMath.Ok(r.YPlacebo) && NxMath.Ok(r.ROpenPlacebo)).OrderBy(r => r.Date).ToList();
            res.Placebo = MainModel(plc, r => r.YPlacebo, r => r.ROpenPlacebo, r => r.SPlacebo, res.HasGammaTerm, trend, lags, null, null);
            double pt2 = res.Placebo.TOf("S"), pt3 = res.Placebo.TOf("S_x_court_gamma");
            res.PlaceboOk = res.Placebo.Ok && !(Math.Abs(pt2) >= 1.96) && !(res.HasGammaTerm && Math.Abs(pt3) >= 1.96);
            lines.Add("Test 3 - placebo de fenetre 14:30->15:00 : " + res.Placebo.Line("S", "b2").Trim() + " | " + res.Placebo.Line("S_x_court_gamma", "b3").Trim());
            lines.Add("  => " + (res.PlaceboOk ? "OK : rien sur la fenetre placebo" : "ECHEC : effet aussi sur la fenetre placebo (signal non specifique a la cloture)"));

            // --- Test 4 : placebo de levier (L(L-1) -> constante).
            res.LeveragePlacebo = MainModel(main, r => r.Y, r => r.ROpenEntry, r => r.SConst, res.HasGammaTerm, trend, lags, null, null);
            res.Encompassing = MainModel(main.Where(r => NxMath.Ok(r.SConst)).ToList(), r => r.Y, r => r.ROpenEntry, r => r.S, false, trend, lags,
                                         r => new[] { r.SConst }, new[] { "S_const" });
            if (res.Main.Ok && res.LeveragePlacebo.Ok)
            {
                // "Doit degrader l ajustement" : R2 plus faible avec la constante ET, dans la regression d emboitement,
                // le flux pondere par L(L-1) domine (coefficient positif, t superieur a celui de la version constante).
                double tS = res.Encompassing.TOf("S"), tC = res.Encompassing.TOf("S_const");
                res.LeverageOk = res.Main.R2 > res.LeveragePlacebo.R2 && res.Encompassing.CoefOf("S") > 0 && tS > tC;
                lines.Add(string.Format(ci, "Test 4 - placebo de levier : R2 {0:F5} (L(L-1)) vs {1:F5} (constante), AIC {2:F1} vs {3:F1} ; encompassing : t(S) = {4:F2}, t(S_const) = {5:F2}",
                    res.Main.R2, res.LeveragePlacebo.R2, res.Main.Aic, res.LeveragePlacebo.Aic, res.Encompassing.TOf("S"), res.Encompassing.TOf("S_const")));
                lines.Add("  => " + (res.LeverageOk ? "OK : remplacer L(L-1) par une constante degrade l ajustement (et L(L-1) domine l emboitement)"
                                                       : "ECHEC : la constante ajuste aussi bien, ou L(L-1) ne domine pas l emboitement (pas de signature du levier)"));
            }

            // --- Test 5 : reversal a l ouverture suivante.
            List<NxLetfPanelRow> rev = main.Where(r => NxMath.Ok(r.ROvernight) && NxMath.Ok(r.RMorning)).ToList();
            res.ReversalOvernight = Simple(rev, r => r.ROvernight, r => new[] { r.S }, new[] { "S" }, lags);
            res.ReversalMorning = Simple(rev, r => r.RMorning, r => new[] { r.S }, new[] { "S" }, lags);
            List<NxLetfPanelRow> strong = rev.Where(r => NxMath.Ok(r.Threshold) && NxMath.Ok(r.Score) && Math.Abs(r.Score) >= r.Threshold).ToList();
            double ovSigned = strong.Count > 0 ? strong.Average(r => Math.Sign(r.R) * r.ROvernight) : double.NaN;
            double moSigned = strong.Count > 0 ? strong.Average(r => Math.Sign(r.R) * r.RMorning) : double.NaN;
            res.ReversalOk = res.ReversalOvernight.Ok && res.ReversalOvernight.CoefOf("S") < 0;
            lines.Add("Test 5 - reversal : r(16:00->ouverture J+1) sur S : " + res.ReversalOvernight.Line("S", "c").Trim()
                      + " | r(ouverture->10:30 J+1) sur S : " + res.ReversalMorning.Line("S", "c").Trim());
            lines.Add(string.Format(ci, "  Jours a fort score ({0}) : rendement moyen dans le sens du trade, nuit {1:F2} pb, matin J+1 {2:F2} pb",
                strong.Count, ovSigned * 1e4, moSigned * 1e4));
            lines.Add("  => " + (res.ReversalOk ? "reversal present : la sortie au close est justifiee" : "pas de reversal mesure (la sortie au close reste une regle)"));

            // --- Validation hors echantillon (panel) : calibration de w(long gamma) puis walk-forward 3 ans.
            List<NxLetfPanelRow> allRows = panel.Where(r => instruments.Contains(r.Instrument)).ToList();
            Dictionary<double, List<KeyValuePair<DateTime, double>>> byW = new Dictionary<double, List<KeyValuePair<DateTime, double>>>();
            foreach (double w in cfg.WeightGrid.Concat(new[] { cfg.WeightLongGamma }).Distinct()) byW[w] = PanelPnl(allRows, cfg, w, cfg.CostTicksRoundTrip);
            DateTime first = allRows.Min(r => r.Date), last = allRows.Max(r => r.Date).AddDays(1);
            res.IsWeight = BestWeight(byW, first, cfg.OosStart, cfg.WeightLongGamma);
            res.IsSharpePanel = SharpeBetween(byW[res.IsWeight], first, cfg.OosStart);
            res.OosSharpePanel = SharpeBetween(byW[res.IsWeight], cfg.OosStart, last);
            List<double> wf = new List<double>();
            List<string> wfLog = new List<string>();
            for (int y = first.Year + cfg.WalkForwardYears; y <= last.Year; y++)
            {
                DateTime ys = new DateTime(y, 1, 1);
                double wy = BestWeight(byW, ys.AddYears(-cfg.WalkForwardYears), ys, cfg.WeightLongGamma);
                List<double> part = byW[wy].Where(kv => kv.Key >= ys && kv.Key < ys.AddYears(1)).Select(kv => kv.Value).ToList();
                wf.AddRange(part);
                wfLog.Add(string.Format(ci, "{0}:w={1:F1}/SR={2:F2}", y, wy, Annualized(part)));
            }
            res.WfOosSharpePanel = Annualized(wf);
            lines.Add(string.Format(ci, "Calibration {0:yyyy}-{1:yyyy} (panel, sans stop) : w(long gamma) = {2:F1} (fiche : {3:F1}), Sharpe IS {4:F2} -> OOS {5:F2} ({6:yyyy}-{7:yyyy})",
                first, cfg.OosStart.AddDays(-1), res.IsWeight, cfg.WeightLongGamma, res.IsSharpePanel, res.OosSharpePanel, cfg.OosStart, last.AddDays(-1)));
            lines.Add(string.Format(ci, "Walk-forward fenetre glissante {0} ans : Sharpe OOS {1:F2}  [{2}]", cfg.WalkForwardYears, res.WfOosSharpePanel, string.Join(" ", wfLog)));

            // --- Trades reels de la strategie : IS/OOS, taux de reussite, stress de couts.
            List<NxLetfTradeOutcome> tr = trades ?? new List<NxLetfTradeOutcome>();
            res.Trades = tr.Count;
            res.OosTrades = tr.Count(t => t.Day >= cfg.OosStart);
            res.NetPnl = tr.Sum(t => t.NetPnl);
            res.NetPnlStress = tr.Sum(t => t.NetPnl - t.Qty * (cfg.StressTicksRoundTrip - cfg.CostTicksRoundTrip) * t.TickValue);
            res.WinRate = tr.Count > 0 ? tr.Count(t => t.NetPnl > 0) / (double)tr.Count : double.NaN;
            List<NxLetfTradeOutcome> top = tr.Where(t => NxMath.Ok(t.ScoreRatio)).ToList();
            double medRatio = NxMath.Median(top.Select(t => t.ScoreRatio));
            top = top.Where(t => t.ScoreRatio >= medRatio).ToList();
            res.WinRateTopHalf = top.Count > 0 ? top.Count(t => t.NetPnl > 0) / (double)top.Count : double.NaN;
            List<double> isR = new List<double>(), oosR = new List<double>();
            if (equityDays != null && dailyReturns != null)
                for (int i = 0; i < dailyReturns.Count && i + 1 < equityDays.Count; i++) (equityDays[i + 1] >= cfg.OosStart ? oosR : isR).Add(dailyReturns[i]);
            res.IsSharpeTrades = Annualized(isR);
            res.OosSharpeTrades = Annualized(oosR);
            lines.Add(string.Format(ci, "Strategie (trades reels, net de {0:F0} tick A/R + {1:F2} $/cote) : {2} trades ({3} hors echantillon), PnL net {4:F0} $, stress {5:F0} ticks : {6:F0} $",
                cfg.CostTicksRoundTrip, cfg.CommissionPerSide, res.Trades, res.OosTrades, res.NetPnl, cfg.StressTicksRoundTrip, res.NetPnlStress));
            lines.Add(string.Format(ci, "  Sharpe net IS {0:F2} | OOS {1:F2} ; trades gagnants {2:P1} (moitie des scores les plus forts : {3:P1})",
                res.IsSharpeTrades, res.OosSharpeTrades, res.WinRate, res.WinRateTopHalf));

            // --- Stabilite de b2 par sous-periode de 2 ans et suivi annuel (critere d abandon).
            List<string> sub = new List<string>();
            res.SignStable = true;
            int nSub = 0;
            if (main.Count > 0)
                for (int y = main[0].Date.Year; y <= main[main.Count - 1].Date.Year; y += 2)
                {
                    List<NxLetfPanelRow> part = main.Where(r => r.Date.Year == y || r.Date.Year == y + 1).ToList();
                    if (part.Count < 100) continue;
                    NxHacResult m = MainModel(part, r => r.Y, r => r.ROpenEntry, r => r.S, res.HasGammaTerm, trend, lags, null, null);
                    double b = m.CoefOf("S");
                    nSub++;
                    if (!(b > 0)) res.SignStable = false;
                    sub.Add(string.Format(ci, "{0}-{1}:{2}{3:F1}", y, (y + 1) % 100, b > 0 ? "+" : "-", m.TOf("S")));
                }
            if (nSub == 0) res.SignStable = false;
            List<string> yearly = new List<string>();
            int consecutive = 0;
            if (main.Count > 0)
                for (int y = main[0].Date.Year; y <= main[main.Count - 1].Date.Year; y++)
                {
                    List<NxLetfPanelRow> part = main.Where(r => r.Date.Year == y).ToList();
                    if (part.Count < 100) continue;
                    NxHacResult m = MainModel(part, r => r.Y, r => r.ROpenEntry, r => r.S, res.HasGammaTerm, trend, lags, null, null);
                    bool sig = m.CoefOf("S") > 0 && m.TOf("S") >= 1.96;
                    consecutive = sig ? 0 : consecutive + 1;
                    if (consecutive >= 2) res.AbandonFlag = true;
                    yearly.Add(string.Format(ci, "{0}:t={1:F1}{2}", y, m.TOf("S"), sig ? "" : "*"));
                }
            lines.Add("Signe de b2 par sous-periode de 2 ans (t NW) : " + string.Join(" ", sub) + " => " + (res.SignStable ? "stable" : "INSTABLE"));
            lines.Add("Suivi annuel de b2 (* = non significatif) : " + string.Join(" ", yearly)
                      + (res.AbandonFlag ? " => CRITERE D ABANDON ATTEINT (2 ans de suite non significatif)" : ""));

            // --- Concentration et controle du GEX.
            List<NxLetfPanelRow> withTop = main.Where(r => NxMath.Ok(r.TopFundShare)).ToList();
            if (withTop.Count > 0)
            {
                string topName = withTop.GroupBy(r => r.TopFund).OrderByDescending(g => g.Count()).First().Key;
                lines.Add(string.Format(ci, "Concentration : {0} premier contributeur {1:P0} des jours, part moyenne du flux {2:P1}, derniere {3:P1}",
                    topName, withTop.Count(r => r.TopFund == topName) / (double)withTop.Count, withTop.Average(r => r.TopFundShare), withTop[withTop.Count - 1].TopFundShare));
            }
            List<NxLetfPanelRow> gr = main.Where(r => NxMath.Ok(r.G) && NxMath.Ok(r.GRef)).ToList();
            if (gr.Count > 10)
                lines.Add(string.Format(ci, "GEX maison vs source tierce : correlation {0:F2}, meme regime {1:P1} des jours ({2} jours)",
                    NxMath.Correlation(gr.Select(r => r.G).ToList(), gr.Select(r => r.GRef).ToList()), gr.Count(r => Math.Sign(r.G) == Math.Sign(r.GRef)) / (double)gr.Count, gr.Count));
            double noGamma = SharpeBetween(PanelPnl(allRows, new NxLetfResearchConfig
            {
                OosStart = cfg.OosStart, ThresholdQuantile = cfg.ThresholdQuantile, ThresholdWindow = cfg.ThresholdWindow, MinThresholdHistory = cfg.MinThresholdHistory,
                MinAbsR = cfg.MinAbsR, UseGammaFilter = false, CommissionPerSide = cfg.CommissionPerSide, InstrumentRule = cfg.InstrumentRule
            }, 1.0, cfg.CostTicksRoundTrip), cfg.OosStart, last);
            lines.Add(string.Format(ci, "Version sans filtre gamma (panel) : Sharpe OOS {0:F2} vs {1:F2} avec filtre (w = {2:F1})", noGamma, res.OosSharpePanel, res.IsWeight));

            // --- Criteres d acceptation et verdict.
            bool c1 = res.OosSharpeTrades >= cfg.SharpeTarget;
            bool c2 = res.WinRate >= cfg.WinRateTarget;
            bool ident = res.AumOk && res.NqEsOk && res.PlaceboOk && res.LeverageOk;
            lines.Add(string.Format(ci, "Criteres : Sharpe net OOS >= {0:F1} : {1} | trades gagnants >= {2:P0} : {3} | signe de b2 stable : {4} | H1 : {5} | identification (AUM, NQ/ES, placebos) : {6}",
                cfg.SharpeTarget, c1 ? "OK" : "ECHEC", cfg.WinRateTarget, c2 ? "OK" : "ECHEC", res.SignStable ? "OK" : "ECHEC", res.H1 ? "OK" : "ECHEC", ident ? "OK" : "ECHEC"));
            res.Verdict = c1 && c2 && res.SignStable && res.H1 && ident && !res.AbandonFlag ? "GO (criteres de la fiche remplis)"
                        : (res.H1 && !ident ? "NO-GO : effet compatible avec le momentum intraday generique, pas specifiquement LETF" : "NO-GO");
            lines.Add("Decision : " + res.Verdict);
            return res;
        }
    }
}
