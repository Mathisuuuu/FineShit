// =============================================================================
//  NexusData.cs   (NinjaTrader 8 / NinjaScript - bibliotheque)
//
//  Donnees externes "point-in-time" utilisees par les fiches :
//    NxNewsStore         titres d actualite par symbole (fiches 7, 8, 9, 10)
//                        dedoublonnage : un meme evenement repris par plusieurs
//                        sources = 1 seul titre (Jaccard >= 0.6 sur 24 h)
//    NxFearGreed         indice Fear & Greed crypto (historique complet en cache)
//    NxEarningsCalendar  dates de resultats (fiches 8 et 14)
//    NxMacroCalendar     agenda macro (veto de la fiche 13)
//    NxFundamentals      bilans trimestriels point-in-time (fiche 3)
//    NxFactorFile        facteurs Fama-French (variante mensuelle de la fiche 4)
//
//  Toutes les dates d evenements sont en UTC ; une date SANS fuseau dans un
//  CSV est consideree comme UTC. Les fichiers sont attendus dans
//  Documents\NinjaTrader 8\Nexus\data\ (modeles fournis dans le dossier Data).
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
    // =========================================================================
    //  Actualites
    // =========================================================================
    public class NxNewsItem
    {
        public DateTime PublishedUtc;
        public string Symbol = "";
        public string Source = "";
        public string Headline = "";
        public string Url = "";
        private HashSet<string> tokens;

        public HashSet<string> Tokens { get { return tokens ?? (tokens = NxText.Tokens(Headline)); } }

        public string Key { get { return NxText.Hash(Symbol.ToUpperInvariant() + "|" + NxText.Normalize(Headline)); } }

        /// <summary>Reddit et reseaux sociaux : pas des nouvelles d entreprise (fiche 7).</summary>
        public bool IsSocial
        {
            get
            {
                string s = (Source ?? "").ToLowerInvariant();
                return s.Contains("reddit") || s.Contains("twitter") || s.Contains("stocktwits") || s.Contains("social");
            }
        }

        public static string CsvHeader { get { return "published_utc,symbol,source,headline,url"; } }

        public string ToCsv()
        {
            return string.Join(",", new[] { PublishedUtc.ToString("yyyy-MM-ddTHH:mm:ssZ", CultureInfo.InvariantCulture),
                NxCsv.Escape(Symbol), NxCsv.Escape(Source), NxCsv.Escape(NxText.OneLine(Headline, 500)), NxCsv.Escape(Url) });
        }
    }

    public class NxNewsStore
    {
        private readonly object sync = new object();
        private readonly Dictionary<string, List<NxNewsItem>> bySymbol = new Dictionary<string, List<NxNewsItem>>(StringComparer.OrdinalIgnoreCase);
        private readonly HashSet<string> keys = new HashSet<string>(StringComparer.Ordinal);

        public double DedupJaccard = 0.6;
        public double DedupWindowHours = 24;
        public int Duplicates { get; private set; }

        public int Count { get { lock (sync) return bySymbol.Values.Sum(l => l.Count); } }

        /// <summary>CSV : published_utc, symbol, source, headline [, url]. Retourne le nombre de titres retenus.</summary>
        public int LoadCsv(string path, ICollection<string> onlySymbols, out string message)
        {
            message = null;
            if (string.IsNullOrEmpty(path) || !File.Exists(path)) { message = "fichier d actualites introuvable : " + path; return 0; }
            string[] h;
            List<string[]> rows = NxCsv.ReadRows(path, out h);
            int ct = NxCsv.Col(h, "published_utc", "datetime_utc", "datetime", "published", "time", "date", "timestamp");
            int cs = NxCsv.Col(h, "symbol", "ticker", "symbole");
            int cso = NxCsv.Col(h, "source");
            int chl = NxCsv.Col(h, "headline", "title", "titre");
            int cu = NxCsv.Col(h, "url", "link");
            if (ct < 0 || cs < 0 || chl < 0) { message = "colonnes requises : published_utc, symbol, headline (source, url optionnelles)"; return 0; }
            HashSet<string> filter = onlySymbols == null ? null : new HashSet<string>(onlySymbols, StringComparer.OrdinalIgnoreCase);
            int added = 0, bad = 0;
            foreach (string[] r in rows.OrderBy(r => NxCsv.Get(r, ct)))
            {
                DateTime t;
                if (!NxCsv.TryParseDate(NxCsv.Get(r, ct), out t)) { bad++; continue; }
                if (t.Kind != DateTimeKind.Utc) t = DateTime.SpecifyKind(t, DateTimeKind.Utc);
                string sym = NxCsv.Get(r, cs).Trim();
                if (sym.Length == 0) continue;
                if (filter != null && !filter.Contains(sym)) continue;
                NxNewsItem it = new NxNewsItem
                {
                    PublishedUtc = t, Symbol = sym, Source = cso >= 0 ? NxCsv.Get(r, cso) : "csv",
                    Headline = NxCsv.Get(r, chl), Url = cu >= 0 ? NxCsv.Get(r, cu) : ""
                };
                if (Add(it)) added++;
            }
            message = string.Format(CultureInfo.InvariantCulture, "{0} titres charges ({1} doublons, {2} dates illisibles) depuis {3}", added, Duplicates, bad, Path.GetFileName(path));
            return added;
        }

        /// <summary>Ajoute un titre ; false si doublon (meme cle, ou meme evenement repris par une autre source).</summary>
        public bool Add(NxNewsItem it)
        {
            if (it == null || string.IsNullOrWhiteSpace(it.Headline) || string.IsNullOrWhiteSpace(it.Symbol)) return false;
            lock (sync)
            {
                string k = it.Key;
                if (keys.Contains(k)) { Duplicates++; return false; }
                List<NxNewsItem> l;
                if (!bySymbol.TryGetValue(it.Symbol, out l)) { l = new List<NxNewsItem>(); bySymbol[it.Symbol] = l; }
                // Recherche d un evenement proche dans le temps et dans les mots.
                DateTime lo = it.PublishedUtc.AddHours(-DedupWindowHours), hi = it.PublishedUtc.AddHours(DedupWindowHours);
                for (int i = l.Count - 1; i >= 0; i--)
                {
                    NxNewsItem o = l[i];
                    if (o.PublishedUtc < lo) break;   // liste triee : tout le reste est plus ancien
                    if (o.PublishedUtc > hi) continue;
                    if (NxText.Jaccard(o.Tokens, it.Tokens) >= DedupJaccard) { Duplicates++; return false; }
                }
                keys.Add(k);
                // Insertion triee par date.
                int pos = l.Count;
                while (pos > 0 && l[pos - 1].PublishedUtc > it.PublishedUtc) pos--;
                l.Insert(pos, it);
                return true;
            }
        }

        /// <summary>Titres de ]fromUtc ; toUtc] pour un symbole.</summary>
        public List<NxNewsItem> Get(string symbol, DateTime fromUtcExclusive, DateTime toUtcInclusive, bool includeSocial)
        {
            lock (sync)
            {
                List<NxNewsItem> l;
                if (!bySymbol.TryGetValue(symbol, out l)) return new List<NxNewsItem>();
                return l.Where(x => x.PublishedUtc > fromUtcExclusive && x.PublishedUtc <= toUtcInclusive && (includeSocial || !x.IsSocial)).ToList();
            }
        }

        public bool HasSymbol(string symbol) { lock (sync) return bySymbol.ContainsKey(symbol); }
    }

    // =========================================================================
    //  Fear & Greed crypto (alternative.me, l indice affiche par CoinGecko)
    // =========================================================================
    public class NxFearGreed
    {
        private readonly SortedDictionary<DateTime, int> values = new SortedDictionary<DateTime, int>();
        private readonly Dictionary<DateTime, string> labels = new Dictionary<DateTime, string>();
        private readonly object sync = new object();
        public string CachePath = Path.Combine(NxPaths.Cache, "fear_greed.csv");
        public DateTime LastRefreshUtc { get; private set; }

        public int Count { get { lock (sync) return values.Count; } }

        public void LoadCache()
        {
            string[] h;
            List<string[]> rows = NxCsv.ReadRows(CachePath, out h);
            int cd = NxCsv.Col(h, "date"), cv = NxCsv.Col(h, "value"), cl = NxCsv.Col(h, "label");
            if (cd < 0 || cv < 0) return;
            lock (sync)
                foreach (string[] r in rows)
                {
                    DateTime d;
                    double v = NxCsv.ParseDouble(NxCsv.Get(r, cv));
                    if (!NxCsv.TryParseDate(NxCsv.Get(r, cd), out d) || !NxMath.Ok(v)) continue;
                    values[d.Date] = (int)v;
                    labels[d.Date] = NxCsv.Get(r, cl);
                }
        }

        /// <summary>Telecharge l historique (limit=0 : tout) et met a jour le cache. Appel bloquant.</summary>
        public bool Refresh(string url, out string error)
        {
            error = null;
            int status;
            string body = NxHttp.Request("GET", url, null, null, 20000, out status, out error);
            if (body == null || status != 200) { error = error ?? ("HTTP " + status); return false; }
            object root;
            if (!NxJson.TryParse(body, out root)) { error = "JSON Fear&Greed illisible"; return false; }
            List<object> data = NxJson.At(root, "data") as List<object>;
            if (data == null) { error = "champ data absent"; return false; }
            StringBuilder sb = new StringBuilder("date,value,label\n");
            lock (sync)
            {
                foreach (object o in data)
                {
                    double ts = NxJson.Num(NxJson.At(o, "timestamp"));
                    double v = NxJson.Num(NxJson.At(o, "value"));
                    if (!NxMath.Ok(ts) || !NxMath.Ok(v)) continue;
                    DateTime d = new DateTime(1970, 1, 1, 0, 0, 0, DateTimeKind.Utc).AddSeconds(ts).Date;
                    values[d] = (int)v;
                    labels[d] = NxJson.Str(NxJson.At(o, "value_classification")) ?? "";
                }
                foreach (KeyValuePair<DateTime, int> kv in values)
                    sb.Append(kv.Key.ToString("yyyy-MM-dd", CultureInfo.InvariantCulture)).Append(',').Append(kv.Value).Append(',').Append(NxCsv.Escape(labels.ContainsKey(kv.Key) ? labels[kv.Key] : "")).Append('\n');
            }
            NxCsv.WriteAll(CachePath, sb.ToString());
            LastRefreshUtc = DateTime.UtcNow;
            return true;
        }

        /// <summary>Valeur publiee pour le jour UTC donne ou le dernier jour connu avant (pas d information future).</summary>
        public bool TryGet(DateTime dayUtc, out int value, out string label)
        {
            value = -1; label = "";
            lock (sync)
            {
                DateTime best = DateTime.MinValue;
                foreach (DateTime d in values.Keys)
                {
                    if (d > dayUtc.Date) break;
                    best = d;
                }
                if (best == DateTime.MinValue) return false;
                value = values[best];
                labels.TryGetValue(best, out label);
                return true;
            }
        }
    }

    // =========================================================================
    //  Calendrier des resultats trimestriels
    // =========================================================================
    public class NxEarningsCalendar
    {
        private readonly Dictionary<string, List<DateTime>> dates = new Dictionary<string, List<DateTime>>(StringComparer.OrdinalIgnoreCase);
        private readonly object sync = new object();
        public bool Loaded { get; private set; }
        public string Path { get; private set; }

        /// <summary>CSV : symbol, date (ou report_date). Format Alpha Vantage accepte.</summary>
        public int Load(string path, out string message)
        {
            Path = path;
            message = null;
            string[] h;
            List<string[]> rows = NxCsv.ReadRows(path, out h);
            if (rows.Count == 0) { message = "aucune date de resultats (" + path + ")"; return 0; }
            int cs = NxCsv.Col(h, "symbol", "ticker"), cd = NxCsv.Col(h, "date", "report_date", "reportdate", "earnings_date");
            if (cs < 0 || cd < 0) { message = "colonnes requises : symbol, date"; return 0; }
            int n = 0;
            lock (sync)
            {
                foreach (string[] r in rows)
                {
                    DateTime d;
                    string s = NxCsv.Get(r, cs).Trim();
                    if (s.Length == 0 || !NxCsv.TryParseDate(NxCsv.Get(r, cd), out d)) continue;
                    List<DateTime> l;
                    if (!dates.TryGetValue(s, out l)) { l = new List<DateTime>(); dates[s] = l; }
                    if (!l.Contains(d.Date)) { l.Add(d.Date); n++; }
                }
                foreach (List<DateTime> l in dates.Values) l.Sort();
                Loaded = dates.Count > 0;
            }
            message = n + " dates de resultats chargees pour " + dates.Count + " symboles";
            return n;
        }

        public bool HasData(string symbol) { lock (sync) return dates.ContainsKey(symbol); }

        /// <summary>Prochaine date de resultats &gt;= day (null si inconnue).</summary>
        public DateTime? Next(string symbol, DateTime day)
        {
            lock (sync)
            {
                List<DateTime> l;
                if (!dates.TryGetValue(symbol, out l)) return null;
                foreach (DateTime d in l) if (d >= day.Date) return d;
                return null;
            }
        }

        /// <summary>Resultats entre day (inclus) et day + n jours ouvres (inclus).</summary>
        public bool Within(string symbol, DateTime day, int businessDays)
        {
            DateTime? nx = Next(symbol, day);
            if (!nx.HasValue) return false;
            DateTime limit = day.Date;
            for (int i = 0; i < businessDays; i++) limit = NxCalendar.NextBusinessDay(limit, null);
            return nx.Value <= limit;
        }

        /// <summary>Rafraichit le fichier depuis Alpha Vantage (EARNINGS_CALENDAR, horizon 3 mois). Appel bloquant.</summary>
        public bool RefreshFromAlphaVantage(string apiKey, string path, out string error)
        {
            error = null;
            if (string.IsNullOrWhiteSpace(apiKey)) { error = "cle Alpha Vantage absente"; return false; }
            int status;
            string csv = NxHttp.Request("GET", "https://www.alphavantage.co/query?function=EARNINGS_CALENDAR&horizon=3month&apikey=" + Uri.EscapeDataString(apiKey),
                                        null, null, 30000, out status, out error);
            if (csv == null || status != 200 || !csv.StartsWith("symbol", StringComparison.OrdinalIgnoreCase)) { error = error ?? ("reponse inattendue HTTP " + status); return false; }
            HashSet<string> existing = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
            lock (sync) foreach (KeyValuePair<string, List<DateTime>> kv in dates) foreach (DateTime d in kv.Value) existing.Add(kv.Key + "|" + d.ToString("yyyy-MM-dd"));
            foreach (string line in csv.Split('\n').Skip(1))
            {
                string[] f = NxCsv.SplitLine(line.Trim(), ',');
                if (f.Length < 3) continue;
                DateTime d;
                if (!NxCsv.TryParseDate(f[2], out d)) continue;
                string key = f[0] + "|" + d.ToString("yyyy-MM-dd");
                if (existing.Contains(key)) continue;
                NxCsv.AppendLine(path, "symbol,date", f[0] + "," + d.ToString("yyyy-MM-dd", CultureInfo.InvariantCulture));
                existing.Add(key);
            }
            string msg;
            Load(path, out msg);
            return true;
        }
    }

    // =========================================================================
    //  Agenda macro (fiche 13)
    // =========================================================================
    public class NxMacroEvent
    {
        public DateTime Utc;
        public string Currency = "";
        public string Impact = "";
        public string Title = "";

        public int ImpactLevel
        {
            get
            {
                string s = (Impact ?? "").ToLowerInvariant();
                if (s.StartsWith("h") || s.StartsWith("fort") || s == "3") return 3;
                if (s.StartsWith("m") || s == "2") return 2;
                return 1;
            }
        }

        public override string ToString() { return Utc.ToString("yyyy-MM-dd HH:mm", CultureInfo.InvariantCulture) + "Z " + Currency + " [" + Impact + "] " + Title; }
    }

    public class NxMacroCalendar
    {
        private readonly List<NxMacroEvent> events = new List<NxMacroEvent>();
        public int Count { get { return events.Count; } }

        /// <summary>CSV : datetime_utc, currency, impact (high/medium/low), title.</summary>
        public int Load(string path, out string message)
        {
            message = null;
            events.Clear();
            string[] h;
            List<string[]> rows = NxCsv.ReadRows(path, out h);
            int ct = NxCsv.Col(h, "datetime_utc", "datetime", "time", "date"), cc = NxCsv.Col(h, "currency", "country", "devise");
            int ci = NxCsv.Col(h, "impact"), cti = NxCsv.Col(h, "title", "event", "titre");
            if (ct < 0 || cc < 0) { message = "agenda macro absent ou colonnes manquantes (datetime_utc, currency, impact, title) : " + path; return 0; }
            foreach (string[] r in rows)
            {
                DateTime t;
                if (!NxCsv.TryParseDate(NxCsv.Get(r, ct), out t)) continue;
                events.Add(new NxMacroEvent { Utc = DateTime.SpecifyKind(t, DateTimeKind.Utc), Currency = NxCsv.Get(r, cc).ToUpperInvariant(), Impact = NxCsv.Get(r, ci), Title = NxCsv.Get(r, cti) });
            }
            events.Sort((a, b) => a.Utc.CompareTo(b.Utc));
            message = events.Count + " evenements macro charges";
            return events.Count;
        }

        public List<NxMacroEvent> Near(ICollection<string> currencies, DateTime utc, int minutesBefore, int minutesAfter, int minImpact)
        {
            DateTime lo = utc.AddMinutes(-minutesBefore), hi = utc.AddMinutes(minutesAfter);
            return events.Where(e => e.Utc >= lo && e.Utc <= hi && e.ImpactLevel >= minImpact
                                     && (currencies == null || currencies.Contains(e.Currency))).ToList();
        }
    }

    // =========================================================================
    //  Fondamentaux point-in-time (fiche 3)
    // =========================================================================
    public class NxFundamentalRow
    {
        public DateTime Available;          // date de publication (disponibilite)
        public double BookEquity = double.NaN;
        public double NetIncome = double.NaN;     // 12 mois glissants
        public double GrossProfit = double.NaN;   // 12 mois glissants
        public double TotalAssets = double.NaN;
        public double TotalLiabilities = double.NaN;
        public double SharesOutstanding = double.NaN;

        public double Profitability { get { return NxMath.SafeDiv(GrossProfit, TotalAssets); } }
        public double Leverage { get { return NxMath.SafeDiv(TotalLiabilities, TotalAssets); } }
    }

    public class NxFundamentals
    {
        private readonly Dictionary<string, List<NxFundamentalRow>> rows = new Dictionary<string, List<NxFundamentalRow>>(StringComparer.OrdinalIgnoreCase);
        public bool Loaded { get { return rows.Count > 0; } }

        /// <summary>
        /// CSV : symbol, available_date, book_equity, net_income_ttm, gross_profit_ttm, total_assets,
        /// total_liabilities, shares_outstanding. available_date = date ou l information etait publique.
        /// </summary>
        public int Load(string path, out string message)
        {
            message = null;
            rows.Clear();
            string[] h;
            List<string[]> data = NxCsv.ReadRows(path, out h);
            int cs = NxCsv.Col(h, "symbol", "ticker");
            int cd = NxCsv.Col(h, "available_date", "filing_date", "report_date", "date");
            int cbe = NxCsv.Col(h, "book_equity", "total_equity", "equity");
            int cni = NxCsv.Col(h, "net_income_ttm", "net_income", "earnings");
            int cgp = NxCsv.Col(h, "gross_profit_ttm", "gross_profit");
            int cta = NxCsv.Col(h, "total_assets", "assets");
            int ctl = NxCsv.Col(h, "total_liabilities", "liabilities", "total_debt");
            int cso = NxCsv.Col(h, "shares_outstanding", "shares");
            if (cs < 0 || cd < 0) { message = "fondamentaux absents ou colonnes symbol/available_date manquantes : " + path; return 0; }
            int n = 0;
            foreach (string[] r in data)
            {
                DateTime d;
                string s = NxCsv.Get(r, cs).Trim();
                if (s.Length == 0 || !NxCsv.TryParseDate(NxCsv.Get(r, cd), out d)) continue;
                NxFundamentalRow f = new NxFundamentalRow
                {
                    Available = d.Date,
                    BookEquity = NxCsv.ParseDouble(NxCsv.Get(r, cbe)),
                    NetIncome = NxCsv.ParseDouble(NxCsv.Get(r, cni)),
                    GrossProfit = NxCsv.ParseDouble(NxCsv.Get(r, cgp)),
                    TotalAssets = NxCsv.ParseDouble(NxCsv.Get(r, cta)),
                    TotalLiabilities = NxCsv.ParseDouble(NxCsv.Get(r, ctl)),
                    SharesOutstanding = NxCsv.ParseDouble(NxCsv.Get(r, cso))
                };
                List<NxFundamentalRow> l;
                if (!rows.TryGetValue(s, out l)) { l = new List<NxFundamentalRow>(); rows[s] = l; }
                l.Add(f); n++;
            }
            foreach (List<NxFundamentalRow> l in rows.Values) l.Sort((a, b) => a.Available.CompareTo(b.Available));
            message = n + " lignes de fondamentaux pour " + rows.Count + " symboles";
            return n;
        }

        public bool Has(string symbol) { return rows.ContainsKey(symbol); }

        /// <summary>Derniere ligne publiee au plus tard le jour donne (aucune information future).</summary>
        public NxFundamentalRow AsOf(string symbol, DateTime day)
        {
            List<NxFundamentalRow> l;
            if (!rows.TryGetValue(symbol, out l)) return null;
            NxFundamentalRow best = null;
            foreach (NxFundamentalRow f in l) { if (f.Available <= day.Date) best = f; else break; }
            return best;
        }
    }

    // =========================================================================
    //  Facteurs Fama-French (fiche 4, variante mensuelle a 3 facteurs)
    // =========================================================================
    public class NxFactorFile
    {
        private readonly SortedDictionary<DateTime, double[]> monthly = new SortedDictionary<DateTime, double[]>();
        public bool Loaded { get { return monthly.Count > 0; } }
        public int Count { get { return monthly.Count; } }

        /// <summary>
        /// CSV : date (yyyyMM, yyyyMMdd ou ISO), mkt_rf, smb, hml [, rf]. En pourcents (format Ken French)
        /// ou en fractions (detection automatique). Les series journalieres sont composees par mois.
        /// </summary>
        public int Load(string path, out string message)
        {
            message = null;
            monthly.Clear();
            string[] h;
            List<string[]> rows = NxCsv.ReadRows(path, out h);
            int cd = NxCsv.Col(h, "date", "month", "yyyymm");
            int cm = NxCsv.Col(h, "mkt_rf", "mkt-rf", "mktrf", "market");
            int cs = NxCsv.Col(h, "smb"), ch = NxCsv.Col(h, "hml"), cr = NxCsv.Col(h, "rf");
            if (cd < 0 || cm < 0 || cs < 0 || ch < 0) { message = "facteurs absents ou colonnes date/mkt_rf/smb/hml manquantes : " + path; return 0; }
            List<KeyValuePair<DateTime, double[]>> raw = new List<KeyValuePair<DateTime, double[]>>();
            foreach (string[] r in rows)
            {
                DateTime d;
                if (!NxCsv.TryParseDate(NxCsv.Get(r, cd), out d)) continue;
                double[] f = { NxCsv.ParseDouble(NxCsv.Get(r, cm)), NxCsv.ParseDouble(NxCsv.Get(r, cs)), NxCsv.ParseDouble(NxCsv.Get(r, ch)), cr >= 0 ? NxCsv.ParseDouble(NxCsv.Get(r, cr)) : 0.0 };
                if (f.Take(3).Any(v => !NxMath.Ok(v))) continue;
                raw.Add(new KeyValuePair<DateTime, double[]>(d, f));
            }
            if (raw.Count == 0) { message = "aucune ligne de facteurs valide"; return 0; }
            double medAbs = NxMath.Median(raw.Select(x => Math.Abs(x.Value[0])));
            double scale = medAbs > 0.05 ? 0.01 : 1.0;
            foreach (KeyValuePair<DateTime, double[]> kv in raw)
            {
                DateTime m = new DateTime(kv.Key.Year, kv.Key.Month, 1);
                double[] cur;
                if (!monthly.TryGetValue(m, out cur)) { cur = new double[] { 0, 0, 0, 0 }; monthly[m] = cur; }
                for (int i = 0; i < 4; i++)
                {
                    double v = NxMath.Ok(kv.Value[i]) ? kv.Value[i] * scale : 0.0;
                    cur[i] = (1 + cur[i]) * (1 + v) - 1;   // composition si journalier
                }
            }
            message = monthly.Count + " mois de facteurs (echelle " + (scale < 1 ? "pourcents" : "fractions") + ")";
            return monthly.Count;
        }

        /// <summary>Facteurs du mois (mkt_rf, smb, hml, rf) ; false si absent.</summary>
        public bool TryGetMonth(int year, int month, out double[] f)
        {
            return monthly.TryGetValue(new DateTime(year, month, 1), out f);
        }
    }
}
