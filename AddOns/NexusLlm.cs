// =============================================================================
//  NexusLlm.cs   (NinjaTrader 8 / NinjaScript - bibliotheque)
//
//  Connectivite externe des fiches 7, 8, 9, 10, 13 et du module C :
//    NxHttp          requetes HTTP(S) avec relances (429 / 5xx / reseau)
//    NxSecrets       cles API : propriete -> variable d environnement -> keys.txt
//    NxLlm           Claude (Anthropic Messages API), DeepSeek (compatible OpenAI),
//                    Gemini (generateContent), ou tout point compatible OpenAI
//    NxLlmCache      cache disque des reponses (backtests rejouables sans cout)
//    NxAiLedger      journal des couts API ("onglet AI" de Nexus) -> ai_costs.csv
//    NxPrompts       consignes et analyseurs de reponses (fiches 7, 8, 9, 13, C)
//    NxFinBertClient client du serveur FinBERT local (Tools\finbert_server.py)
//    NxNewsFetchers  NewsAPI et Reddit (temps reel)
//    NxWebhook       relais des signaux (pipeline de la fiche 13)
//
//  SECURITE : ne jamais laisser une cle API dans un fichier partage. Les
//  proprietes de strategie sont enregistrees en clair dans les workspaces ;
//  preferer la variable d environnement (ANTHROPIC_API_KEY, DEEPSEEK_API_KEY,
//  GEMINI_API_KEY, NEWSAPI_KEY, ALPHAVANTAGE_KEY) ou Nexus\keys.txt (NOM=valeur).
// =============================================================================

#region Using declarations
using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Linq;
using System.Net;
using System.Text;
using System.Text.RegularExpressions;
using System.Threading;
using System.Threading.Tasks;
#endregion

namespace NinjaTrader.NinjaScript.AddOns.Nexus
{
    // =========================================================================
    //  HTTP
    // =========================================================================
    public static class NxHttp
    {
        public static int MaxAttempts = 3;

        static NxHttp()
        {
            try { ServicePointManager.SecurityProtocol |= SecurityProtocolType.Tls12; } catch { }
        }

        /// <summary>Requete synchrone ; renvoie le corps (meme en cas d erreur HTTP) ou null si echec reseau.</summary>
        public static string Request(string method, string url, Dictionary<string, string> headers, string body, int timeoutMs, out int status, out string error)
        {
            status = -1; error = null;
            string result = null;
            for (int attempt = 1; attempt <= Math.Max(1, MaxAttempts); attempt++)
            {
                int retryAfterSec = 0;
                result = Once(method, url, headers, body, timeoutMs, out status, out error, out retryAfterSec);
                bool retryable = status == -1 || status == 429 || status == 500 || status == 502 || status == 503 || status == 504 || status == 529;
                if (!retryable || attempt == MaxAttempts) break;
                int waitMs = retryAfterSec > 0 ? Math.Min(30, retryAfterSec) * 1000 : 1000 * attempt * attempt;
                Thread.Sleep(waitMs);
            }
            return result;
        }

        private static string Once(string method, string url, Dictionary<string, string> headers, string body, int timeoutMs,
                                   out int status, out string error, out int retryAfterSec)
        {
            status = -1; error = null; retryAfterSec = 0;
            try
            {
                HttpWebRequest req = (HttpWebRequest)WebRequest.Create(url);
                req.Method = method;
                req.Timeout = timeoutMs;
                req.ReadWriteTimeout = timeoutMs;
                req.UserAgent = "NexusNinjaScript/1.0";
                req.AutomaticDecompression = DecompressionMethods.GZip | DecompressionMethods.Deflate;
                if (headers != null)
                    foreach (KeyValuePair<string, string> h in headers)
                    {
                        if (string.Equals(h.Key, "Content-Type", StringComparison.OrdinalIgnoreCase)) req.ContentType = h.Value;
                        else if (string.Equals(h.Key, "User-Agent", StringComparison.OrdinalIgnoreCase)) req.UserAgent = h.Value;
                        else if (string.Equals(h.Key, "Accept", StringComparison.OrdinalIgnoreCase)) req.Accept = h.Value;
                        else req.Headers[h.Key] = h.Value;
                    }
                if (body != null)
                {
                    byte[] bytes = Encoding.UTF8.GetBytes(body);
                    if (string.IsNullOrEmpty(req.ContentType)) req.ContentType = "application/json";
                    req.ContentLength = bytes.Length;
                    using (Stream s = req.GetRequestStream()) s.Write(bytes, 0, bytes.Length);
                }
                using (HttpWebResponse resp = (HttpWebResponse)req.GetResponse())
                {
                    status = (int)resp.StatusCode;
                    using (StreamReader sr = new StreamReader(resp.GetResponseStream(), Encoding.UTF8)) return sr.ReadToEnd();
                }
            }
            catch (WebException ex)
            {
                HttpWebResponse r = ex.Response as HttpWebResponse;
                if (r != null)
                {
                    status = (int)r.StatusCode;
                    int ra;
                    if (int.TryParse(r.Headers["Retry-After"], out ra)) retryAfterSec = ra;
                    try
                    {
                        using (StreamReader sr = new StreamReader(r.GetResponseStream(), Encoding.UTF8))
                        {
                            string b = sr.ReadToEnd();
                            error = "HTTP " + status + " " + NxText.OneLine(b, 400);
                            return b;
                        }
                    }
                    catch { error = "HTTP " + status; return null; }
                }
                error = ex.Status + " " + ex.Message;
                return null;
            }
            catch (Exception ex)
            {
                error = ex.GetType().Name + " " + ex.Message;
                return null;
            }
        }
    }

    // =========================================================================
    //  Cles API
    // =========================================================================
    public static class NxSecrets
    {
        public static string Resolve(string propertyValue, string envName)
        {
            if (!string.IsNullOrWhiteSpace(propertyValue)) return propertyValue.Trim();
            if (string.IsNullOrEmpty(envName)) return null;
            foreach (EnvironmentVariableTarget t in new[] { EnvironmentVariableTarget.Process, EnvironmentVariableTarget.User, EnvironmentVariableTarget.Machine })
            {
                try
                {
                    string v = Environment.GetEnvironmentVariable(envName, t);
                    if (!string.IsNullOrWhiteSpace(v)) return v.Trim();
                }
                catch { }
            }
            string txt = NxCsv.ReadAllSafe(NxPaths.KeysFile);
            if (txt != null)
                foreach (string line in txt.Split('\n'))
                {
                    string l = line.Trim();
                    int k = l.IndexOf('=');
                    if (k > 0 && string.Equals(l.Substring(0, k).Trim(), envName, StringComparison.OrdinalIgnoreCase))
                        return l.Substring(k + 1).Trim();
                }
            return null;
        }

        public static string Mask(string key)
        {
            if (string.IsNullOrEmpty(key)) return "(aucune)";
            return key.Length <= 8 ? "****" : key.Substring(0, 4) + "..." + key.Substring(key.Length - 4);
        }
    }

    // =========================================================================
    //  LLM
    // =========================================================================
    public enum NxLlmProvider { Claude, DeepSeek, Gemini, CompatibleOpenAI }

    public class NxLlmConfig
    {
        public NxLlmProvider Provider = NxLlmProvider.Claude;
        public string Model = "claude-opus-5-5";
        public string ApiKey;
        public string Endpoint;                // vide = point par defaut du fournisseur
        public double Temperature = 0.0;       // < 0 => parametre omis
        public int MaxTokens = 512;
        public int TimeoutSec = 60;
        public double PriceInPerMTok = 0.0;    // $ par million de tokens en entree (0 = inconnu)
        public double PriceOutPerMTok = 0.0;

        public string Label { get { return Provider + ":" + Model; } }

        public static string DefaultEnvVar(NxLlmProvider p)
        {
            switch (p)
            {
                case NxLlmProvider.Claude: return "ANTHROPIC_API_KEY";
                case NxLlmProvider.DeepSeek: return "DEEPSEEK_API_KEY";
                case NxLlmProvider.Gemini: return "GEMINI_API_KEY";
                default: return "OPENAI_API_KEY";
            }
        }

        public static string DefaultModel(NxLlmProvider p)
        {
            switch (p)
            {
                case NxLlmProvider.Claude: return "claude-opus-5-5";
                case NxLlmProvider.DeepSeek: return "deepseek-chat";
                case NxLlmProvider.Gemini: return "gemini-2.5-flash";
                default: return "gpt-4o-mini";
            }
        }
    }

    public class NxLlmResult
    {
        public bool Ok;
        public string Text;
        public string Error;
        public int Status;
        public long InTokens;
        public long OutTokens;
        public double CostUsd;
        public bool FromCache;
    }

    public static class NxLlm
    {
        /// <summary>Appel bloquant (a lancer hors du fil NinjaTrader en temps reel). Utilise le cache si fourni.</summary>
        public static string CacheKey(NxLlmConfig cfg, string system, string user, string promptVersion)
        {
            return cfg.Label + "|" + (promptVersion ?? "") + "|" + NxText.Hash(system ?? "") + "|" + NxText.Hash(user ?? "");
        }

        public static NxLlmResult Complete(NxLlmConfig cfg, string system, string user, NxLlmCache cache, string promptVersion)
        {
            string key = CacheKey(cfg, system, user, promptVersion);
            string cached;
            if (cache != null && cache.TryGet(key, out cached))
                return new NxLlmResult { Ok = true, Text = cached, FromCache = true, Status = 200 };
            if (string.IsNullOrWhiteSpace(cfg.ApiKey))
                return new NxLlmResult { Ok = false, Error = "cle API absente pour " + cfg.Label + " (variable " + NxLlmConfig.DefaultEnvVar(cfg.Provider) + ")" };
            NxLlmResult r;
            switch (cfg.Provider)
            {
                case NxLlmProvider.Claude: r = CallClaude(cfg, system, user, cfg.Temperature >= 0); break;
                case NxLlmProvider.Gemini: r = CallGemini(cfg, system, user); break;
                default: r = CallOpenAiLike(cfg, system, user); break;
            }
            r.CostUsd = (r.InTokens * cfg.PriceInPerMTok + r.OutTokens * cfg.PriceOutPerMTok) / 1e6;
            if (r.Ok && cache != null && !string.IsNullOrEmpty(r.Text)) cache.Put(key, r.Text);
            return r;
        }

        private static NxLlmResult CallClaude(NxLlmConfig cfg, string system, string user, bool withTemperature)
        {
            string url = string.IsNullOrWhiteSpace(cfg.Endpoint) ? "https://api.anthropic.com/v1/messages" : cfg.Endpoint;
            StringBuilder b = new StringBuilder();
            b.Append("{\"model\":").Append(NxJson.Q(cfg.Model))
             .Append(",\"max_tokens\":").Append(Math.Max(16, cfg.MaxTokens));
            if (withTemperature) b.Append(",\"temperature\":").Append(NxJson.N(cfg.Temperature));
            if (!string.IsNullOrEmpty(system)) b.Append(",\"system\":").Append(NxJson.Q(system));
            b.Append(",\"messages\":[{\"role\":\"user\",\"content\":").Append(NxJson.Q(user)).Append("}]}");
            Dictionary<string, string> h = new Dictionary<string, string>
            {
                { "x-api-key", cfg.ApiKey }, { "anthropic-version", "2023-06-01" }, { "Content-Type", "application/json" }
            };
            int status; string err;
            string body = NxHttp.Request("POST", url, h, b.ToString(), cfg.TimeoutSec * 1000, out status, out err);
            NxLlmResult r = new NxLlmResult { Status = status };
            object root = null;
            if (body != null) NxJson.TryParse(body, out root);
            if (status != 200)
            {
                string msg = NxJson.Str(NxJson.At(root, "error.message")) ?? err ?? "erreur inconnue";
                // Certains modeles refusent "temperature" : nouvel essai sans ce parametre.
                if (withTemperature && status == 400 && msg.IndexOf("temperature", StringComparison.OrdinalIgnoreCase) >= 0)
                    return CallClaude(cfg, system, user, false);
                r.Error = "Claude HTTP " + status + " : " + msg;
                return r;
            }
            StringBuilder text = new StringBuilder();
            List<object> content = NxJson.At(root, "content") as List<object>;
            if (content != null)
                foreach (object c in content)
                    if (NxJson.Str(NxJson.At(c, "type")) == "text") text.Append(NxJson.Str(NxJson.At(c, "text")));
            r.Text = text.ToString();
            r.InTokens = (long)Num0(NxJson.At(root, "usage.input_tokens"));
            r.OutTokens = (long)Num0(NxJson.At(root, "usage.output_tokens"));
            r.Ok = r.Text.Length > 0;
            if (!r.Ok) r.Error = "reponse Claude vide (stop_reason=" + NxJson.Str(NxJson.At(root, "stop_reason")) + ")";
            return r;
        }

        private static NxLlmResult CallOpenAiLike(NxLlmConfig cfg, string system, string user)
        {
            string url = !string.IsNullOrWhiteSpace(cfg.Endpoint) ? cfg.Endpoint
                       : (cfg.Provider == NxLlmProvider.DeepSeek ? "https://api.deepseek.com/chat/completions" : "https://api.openai.com/v1/chat/completions");
            StringBuilder b = new StringBuilder();
            b.Append("{\"model\":").Append(NxJson.Q(cfg.Model)).Append(",\"stream\":false")
             .Append(",\"max_tokens\":").Append(Math.Max(16, cfg.MaxTokens));
            if (cfg.Temperature >= 0) b.Append(",\"temperature\":").Append(NxJson.N(cfg.Temperature));
            b.Append(",\"messages\":[");
            if (!string.IsNullOrEmpty(system)) b.Append("{\"role\":\"system\",\"content\":").Append(NxJson.Q(system)).Append("},");
            b.Append("{\"role\":\"user\",\"content\":").Append(NxJson.Q(user)).Append("}]}");
            Dictionary<string, string> h = new Dictionary<string, string> { { "Authorization", "Bearer " + cfg.ApiKey }, { "Content-Type", "application/json" } };
            int status; string err;
            string body = NxHttp.Request("POST", url, h, b.ToString(), cfg.TimeoutSec * 1000, out status, out err);
            NxLlmResult r = new NxLlmResult { Status = status };
            object root = null;
            if (body != null) NxJson.TryParse(body, out root);
            if (status != 200)
            {
                r.Error = cfg.Provider + " HTTP " + status + " : " + (NxJson.Str(NxJson.At(root, "error.message")) ?? err ?? "erreur inconnue");
                return r;
            }
            r.Text = NxJson.Str(NxJson.At(root, "choices[0].message.content")) ?? "";
            r.InTokens = (long)Num0(NxJson.At(root, "usage.prompt_tokens"));
            r.OutTokens = (long)Num0(NxJson.At(root, "usage.completion_tokens"));
            r.Ok = r.Text.Length > 0;
            if (!r.Ok) r.Error = "reponse vide";
            return r;
        }

        private static NxLlmResult CallGemini(NxLlmConfig cfg, string system, string user)
        {
            string url = !string.IsNullOrWhiteSpace(cfg.Endpoint) ? cfg.Endpoint
                       : "https://generativelanguage.googleapis.com/v1beta/models/" + Uri.EscapeDataString(cfg.Model) + ":generateContent";
            StringBuilder b = new StringBuilder("{");
            if (!string.IsNullOrEmpty(system)) b.Append("\"systemInstruction\":{\"parts\":[{\"text\":").Append(NxJson.Q(system)).Append("}]},");
            b.Append("\"contents\":[{\"role\":\"user\",\"parts\":[{\"text\":").Append(NxJson.Q(user)).Append("}]}],");
            b.Append("\"generationConfig\":{\"maxOutputTokens\":").Append(Math.Max(16, cfg.MaxTokens));
            if (cfg.Temperature >= 0) b.Append(",\"temperature\":").Append(NxJson.N(cfg.Temperature));
            b.Append("}}");
            Dictionary<string, string> h = new Dictionary<string, string> { { "x-goog-api-key", cfg.ApiKey }, { "Content-Type", "application/json" } };
            int status; string err;
            string body = NxHttp.Request("POST", url, h, b.ToString(), cfg.TimeoutSec * 1000, out status, out err);
            NxLlmResult r = new NxLlmResult { Status = status };
            object root = null;
            if (body != null) NxJson.TryParse(body, out root);
            if (status != 200)
            {
                r.Error = "Gemini HTTP " + status + " : " + (NxJson.Str(NxJson.At(root, "error.message")) ?? err ?? "erreur inconnue");
                return r;
            }
            StringBuilder text = new StringBuilder();
            List<object> parts = NxJson.At(root, "candidates[0].content.parts") as List<object>;
            if (parts != null)
                foreach (object p in parts)
                    if (!NxJson.Bool(NxJson.At(p, "thought"))) text.Append(NxJson.Str(NxJson.At(p, "text")));
            r.Text = text.ToString();
            r.InTokens = (long)Num0(NxJson.At(root, "usageMetadata.promptTokenCount"));
            r.OutTokens = (long)(Num0(NxJson.At(root, "usageMetadata.candidatesTokenCount")) + Num0(NxJson.At(root, "usageMetadata.thoughtsTokenCount")));
            r.Ok = r.Text.Length > 0;
            if (!r.Ok) r.Error = "reponse Gemini vide (finishReason=" + NxJson.Str(NxJson.At(root, "candidates[0].finishReason")) + ") : augmenter MaxTokens";
            return r;
        }

        private static double Num0(object o) { double v = NxJson.Num(o); return NxMath.Ok(v) ? v : 0.0; }
    }

    // =========================================================================
    //  Cache disque des reponses LLM (cle -> texte, base64)
    // =========================================================================
    public class NxLlmCache
    {
        private static readonly Dictionary<string, NxLlmCache> instances = new Dictionary<string, NxLlmCache>(StringComparer.OrdinalIgnoreCase);
        private readonly Dictionary<string, string> map = new Dictionary<string, string>(StringComparer.Ordinal);
        private readonly object sync = new object();
        public readonly string Path;

        private NxLlmCache(string path)
        {
            Path = path;
            string txt = NxCsv.ReadAllSafe(path);
            if (txt == null) return;
            foreach (string line in txt.Split('\n'))
            {
                int k = line.IndexOf('\t');
                if (k <= 0) continue;
                try { map[line.Substring(0, k)] = Encoding.UTF8.GetString(Convert.FromBase64String(line.Substring(k + 1).Trim())); } catch { }
            }
        }

        public static NxLlmCache Get(string path)
        {
            lock (instances)
            {
                NxLlmCache c;
                if (!instances.TryGetValue(path, out c)) { c = new NxLlmCache(path); instances[path] = c; }
                return c;
            }
        }

        public int Count { get { lock (sync) return map.Count; } }

        public bool TryGet(string key, out string text) { lock (sync) return map.TryGetValue(key, out text); }

        public void Put(string key, string text)
        {
            lock (sync)
            {
                if (map.ContainsKey(key)) return;
                map[key] = text;
            }
            NxCsv.AppendLine(Path, null, key + "\t" + Convert.ToBase64String(Encoding.UTF8.GetBytes(text ?? "")));
        }
    }

    // =========================================================================
    //  Journal des couts API (equivalent de l onglet "AI" de Nexus)
    // =========================================================================
    public static class NxAiLedger
    {
        private static readonly Dictionary<string, double[]> totals = new Dictionary<string, double[]>(StringComparer.OrdinalIgnoreCase);
        private static readonly object sync = new object();
        public static string FilePath { get { return System.IO.Path.Combine(NxPaths.Journal, "ai_costs.csv"); } }

        public static void Record(string strategyId, NxLlmConfig cfg, NxLlmResult r, string purpose, bool writeFile)
        {
            if (r == null || r.FromCache) return;
            lock (sync)
            {
                double[] t;
                if (!totals.TryGetValue(strategyId, out t)) { t = new double[4]; totals[strategyId] = t; }
                t[0] += r.InTokens; t[1] += r.OutTokens; t[2] += r.CostUsd; t[3] += 1;
            }
            if (writeFile)
                NxCsv.AppendLine(FilePath, "time_utc,strategy,provider,model,purpose,in_tokens,out_tokens,cost_usd,ok,error",
                    string.Join(",", new[] { DateTime.UtcNow.ToString("yyyy-MM-dd HH:mm:ss", CultureInfo.InvariantCulture), NxCsv.Escape(strategyId),
                        cfg.Provider.ToString(), NxCsv.Escape(cfg.Model), NxCsv.Escape(purpose), r.InTokens.ToString(CultureInfo.InvariantCulture),
                        r.OutTokens.ToString(CultureInfo.InvariantCulture), NxCsv.F(r.CostUsd, 6), r.Ok ? "1" : "0", NxCsv.Escape(NxText.OneLine(r.Error, 200)) }));
        }

        /// <summary>[tokens entree, tokens sortie, cout $, appels] de la strategie depuis le chargement.</summary>
        public static double[] Totals(string strategyId)
        {
            lock (sync)
            {
                double[] t;
                return totals.TryGetValue(strategyId, out t) ? (double[])t.Clone() : new double[4];
            }
        }

        public static void Reset(string strategyId) { lock (sync) totals.Remove(strategyId); }
    }

    // =========================================================================
    //  Consignes (prompts) et analyse des reponses
    // =========================================================================
    public static class NxPrompts
    {
        public const string Version = "nx-v1";

        public const string HeadlineSystem =
            "You are a financial expert with stock and crypto recommendation experience. " +
            "You judge only the short-term (next trading day) price impact of a single headline on the named asset. " +
            "Follow the requested output format exactly.";

        /// <summary>Fiches 7 et 10 : bon / mauvais / sans effet (Lopez-Lira et Tang).</summary>
        public static string Headline3(string symbol, string company, string headline, string context)
        {
            string name = string.IsNullOrWhiteSpace(company) ? symbol : company + " (" + symbol + ")";
            return "Is this headline good, bad, or of no effect for the price of " + name + " in the short term?\n"
                 + "Headline: \"" + headline + "\"\n"
                 + (string.IsNullOrWhiteSpace(context) ? "" : "Context: " + context + "\n")
                 + "Answer on the first line with exactly one word: GOOD, BAD or NONE.\n"
                 + "On the second line, give one short sentence of justification.";
        }

        /// <summary>+1 / -1 / 0 ; int.MinValue si illisible.</summary>
        public static int ParseLabel3(string text)
        {
            if (string.IsNullOrWhiteSpace(text)) return int.MinValue;
            string first = text.Trim().Split('\n')[0].Trim().Trim('*', '"', '\'', '.', ':', ' ').ToUpperInvariant();
            // Les mots neutres d abord ("NO EFFECT" commence par "NO").
            if (first.StartsWith("NONE") || first.StartsWith("UNKNOWN") || first.StartsWith("NEUTRAL") || first.StartsWith("SANS") || first.StartsWith("NO EFFECT") || first.StartsWith("IRRELEVANT")) return 0;
            if (first.StartsWith("GOOD") || first.StartsWith("YES") || first.StartsWith("BON") || first.StartsWith("POSITIVE")) return 1;
            if (first.StartsWith("BAD") || first.StartsWith("NO ") || first == "NO" || first.StartsWith("MAUVAIS") || first.StartsWith("NEGATIVE")) return -1;
            Match m = Regex.Match(text.ToUpperInvariant(), @"\b(GOOD|BAD|NONE)\b");
            if (m.Success) return m.Value == "GOOD" ? 1 : (m.Value == "BAD" ? -1 : 0);
            return int.MinValue;
        }

        /// <summary>Fiche 9 : entier de -2 (tres mauvais) a +2 (tres bon).</summary>
        public static string Headline5(string symbol, string company, string headline, string context)
        {
            string name = string.IsNullOrWhiteSpace(company) ? symbol : company + " (" + symbol + ")";
            return "Rate the likely short-term (next trading day) impact of this headline on the price of " + name
                 + " on an integer scale from -2 (very bad) to +2 (very good), where 0 means no effect.\n"
                 + "Headline: \"" + headline + "\"\n"
                 + (string.IsNullOrWhiteSpace(context) ? "" : "Context: " + context + "\n")
                 + "Answer on the first line with only the integer (-2, -1, 0, 1 or 2).\n"
                 + "On the second line, give one short sentence of justification.";
        }

        public static int ParseScore5(string text)
        {
            if (string.IsNullOrWhiteSpace(text)) return int.MinValue;
            Match m = Regex.Match(text.Trim(), @"^[\s\*""']*([+-]?\s?[0-2])\b");
            if (!m.Success) m = Regex.Match(text, @"(?<![\d])([+-]?[0-2])(?![\d])");
            if (!m.Success) return int.MinValue;
            int v;
            return int.TryParse(m.Groups[1].Value.Replace(" ", ""), NumberStyles.AllowLeadingSign, CultureInfo.InvariantCulture, out v) && v >= -2 && v <= 2 ? v : int.MinValue;
        }

        /// <summary>Fiche 8 : le juge "pessimiste strict" (LordWeirdDude).</summary>
        public const string JudgeSystem =
            "You are a strict risk officer acting as a strict pessimist. A quantitative momentum model has ALREADY selected this trade. " +
            "You can only BLOCK it; you can never create a trade or increase its size. Look for what price-based models cannot see: " +
            "litigation, guidance cuts or forecast revisions, regulatory or criminal investigations, share dilution or large equity offerings, " +
            "management changes (CEO/CFO departure), mergers and acquisitions, accounting problems, earnings imminent within the holding period. " +
            "If the provided information contains no concrete evidence of such a risk, do not veto. Output strict JSON only.";

        public static string JudgeUser(string symbol, string company, string source, int horizonDays, DateTime day, string nextEarnings, IList<NxNewsItem> headlines)
        {
            StringBuilder sb = new StringBuilder();
            sb.Append("Candidate trade: BUY ").Append(string.IsNullOrWhiteSpace(company) ? symbol : company + " (" + symbol + ")")
              .Append(", source: ").Append(source).Append(", expected holding period about ").Append(horizonDays).Append(" trading days.\n");
            sb.Append("Decision date: ").Append(day.ToString("yyyy-MM-dd", CultureInfo.InvariantCulture)).Append('\n');
            sb.Append("Next earnings date: ").Append(string.IsNullOrEmpty(nextEarnings) ? "unknown" : nextEarnings).Append('\n');
            sb.Append("Headlines from the last 7 days (UTC time | source | title):\n");
            if (headlines == null || headlines.Count == 0) sb.Append("(none)\n");
            else foreach (NxNewsItem h in headlines.OrderBy(x => x.PublishedUtc).Take(40))
                    sb.Append("- ").Append(h.PublishedUtc.ToString("yyyy-MM-dd HH:mm", CultureInfo.InvariantCulture)).Append(" | ").Append(h.Source).Append(" | ").Append(NxText.OneLine(h.Headline, 250)).Append('\n');
            sb.Append("\nRespond with strict JSON only, no prose and no code fence: ")
              .Append("{\"veto\": true or false, \"reason\": \"one sentence\", \"confidence\": number between 0 and 1}");
            return sb.ToString();
        }

        public static string RiskRankUser(string symbol, string company, string source, DateTime day, string nextEarnings, IList<NxNewsItem> headlines)
        {
            string u = JudgeUser(symbol, company, source, 21, day, nextEarnings, headlines);
            int k = u.LastIndexOf("Respond with strict JSON", StringComparison.Ordinal);
            if (k > 0) u = u.Substring(0, k);
            return u + "Rate the event risk of this long trade. Respond with strict JSON only: {\"risk\": number between 0 (no identifiable risk) and 1 (severe risk), \"reason\": \"one sentence\"}";
        }

        /// <summary>Analyse du JSON du juge. false si illisible.</summary>
        public static bool ParseJudge(string text, out bool veto, out string reason, out double confidence)
        {
            veto = false; reason = ""; confidence = 0;
            string js = NxJson.ExtractFirstObject(text);
            object o;
            if (js == null || !NxJson.TryParse(js, out o)) return false;
            veto = NxJson.Bool(NxJson.At(o, "veto"));
            reason = NxJson.Str(NxJson.At(o, "reason")) ?? "";
            confidence = NxJson.Num(NxJson.At(o, "confidence"));
            if (!NxMath.Ok(confidence)) confidence = veto ? 1.0 : 0.0;
            confidence = NxMath.Clamp(confidence, 0, 1);
            return true;
        }

        public static bool ParseRisk(string text, out double risk, out string reason)
        {
            risk = double.NaN; reason = "";
            string js = NxJson.ExtractFirstObject(text);
            object o;
            if (js == null || !NxJson.TryParse(js, out o)) return false;
            risk = NxMath.Clamp(NxJson.Num(NxJson.At(o, "risk")), 0, 1);
            reason = NxJson.Str(NxJson.At(o, "reason")) ?? "";
            return NxMath.Ok(risk);
        }

        /// <summary>Fiche 13 : veto macro (banque centrale, chiffre macro dans l heure).</summary>
        public const string MacroSystem =
            "You are an event-risk filter for a systematic multi-horizon trend-following strategy on FX, gold and equity index CFDs " +
            "traded under prop-firm drawdown rules. You can only veto a new position, never create or enlarge one. Output strict JSON only.";

        public static string MacroUser(string symbol, int direction, DateTime utc, IList<NxMacroEvent> events)
        {
            StringBuilder sb = new StringBuilder();
            sb.Append("New position: ").Append(direction > 0 ? "LONG " : "SHORT ").Append(symbol).Append(" at ")
              .Append(utc.ToString("yyyy-MM-dd HH:mm", CultureInfo.InvariantCulture)).Append(" UTC.\n");
            sb.Append("Scheduled macro events within one hour of entry:\n");
            if (events == null || events.Count == 0) sb.Append("(none)\n");
            else foreach (NxMacroEvent e in events) sb.Append("- ").Append(e).Append('\n');
            sb.Append("Should this new position be vetoed because of event risk (central bank decision, major macro release within the hour)?\n");
            sb.Append("Respond with strict JSON only: {\"veto\": true or false, \"reason\": \"one sentence\", \"confidence\": number between 0 and 1}");
            return sb.ToString();
        }

        /// <summary>Module C : relecture de la methode par une seconde IA.</summary>
        public const string AuditSystem =
            "You are a skeptical quantitative reviewer auditing a backtest report produced by an automated trading strategy. " +
            "Identify methodological flaws: look-ahead bias, tautological filters, survivorship bias, data snooping, too few trades, " +
            "unrealistic costs or fills, overfitting, regime dependence. Answer in French, as at most 15 short bullet points, most serious first.";

        public static string AuditUser(string report) { return "Rapport a auditer :\n\n" + report; }
    }

    // =========================================================================
    //  FinBERT local (fiche 10) - protocole du serveur Tools\finbert_server.py
    //  POST {"texts": [...]} -> {"results": [{"positive":p,"negative":n,"neutral":z}, ...]}
    // =========================================================================
    public class NxFinBertClient
    {
        public string Url = "http://127.0.0.1:8765/score";
        public int TimeoutMs = 30000;
        public int BatchSize = 32;
        private readonly Dictionary<string, double[]> cache = new Dictionary<string, double[]>(StringComparer.Ordinal);
        private readonly object sync = new object();
        private readonly string cachePath;

        public NxFinBertClient(string cachePath)
        {
            this.cachePath = cachePath;
            string[] h;
            List<string[]> rows = NxCsv.ReadRows(cachePath, out h);
            int ck = NxCsv.Col(h, "key"), cp = NxCsv.Col(h, "positive"), cn = NxCsv.Col(h, "negative"), cz = NxCsv.Col(h, "neutral");
            if (ck < 0) return;
            foreach (string[] r in rows)
                cache[NxCsv.Get(r, ck)] = new[] { NxCsv.ParseDouble(NxCsv.Get(r, cp)), NxCsv.ParseDouble(NxCsv.Get(r, cn)), NxCsv.ParseDouble(NxCsv.Get(r, cz)) };
        }

        public static string KeyOf(string text) { return NxText.Hash("finbert|" + NxText.Normalize(text)); }

        public bool TryGetCached(string text, out double[] probs) { lock (sync) return cache.TryGetValue(KeyOf(text), out probs); }

        /// <summary>Probabilites [positif, negatif, neutre] ; appel bloquant pour les textes non caches.</summary>
        public bool Score(IList<string> texts, bool allowNetwork, out List<double[]> probs, out string error)
        {
            error = null;
            probs = new List<double[]>();
            List<int> missing = new List<int>();
            for (int i = 0; i < texts.Count; i++)
            {
                double[] p;
                if (TryGetCached(texts[i], out p)) probs.Add(p); else { probs.Add(null); missing.Add(i); }
            }
            if (missing.Count == 0) return true;
            if (!allowNetwork) { error = missing.Count + " titres non scores (cache FinBERT)"; return false; }
            for (int start = 0; start < missing.Count; start += BatchSize)
            {
                List<int> batch = missing.Skip(start).Take(BatchSize).ToList();
                string body = "{\"texts\":[" + string.Join(",", batch.Select(i => NxJson.Q(texts[i]))) + "]}";
                int status; string err;
                string resp = NxHttp.Request("POST", Url, new Dictionary<string, string> { { "Content-Type", "application/json" } }, body, TimeoutMs, out status, out err);
                object root;
                if (resp == null || status != 200 || !NxJson.TryParse(resp, out root)) { error = "serveur FinBERT injoignable (" + Url + ") : " + (err ?? ("HTTP " + status)); return false; }
                List<object> res = NxJson.At(root, "results") as List<object>;
                if (res == null || res.Count != batch.Count) { error = "reponse FinBERT inattendue"; return false; }
                for (int k = 0; k < batch.Count; k++)
                {
                    double[] p = { NxJson.Num(NxJson.At(res[k], "positive")), NxJson.Num(NxJson.At(res[k], "negative")), NxJson.Num(NxJson.At(res[k], "neutral")) };
                    probs[batch[k]] = p;
                    string key = KeyOf(texts[batch[k]]);
                    lock (sync) cache[key] = p;
                    NxCsv.AppendLine(cachePath, "key,positive,negative,neutral", key + "," + NxCsv.F(p[0]) + "," + NxCsv.F(p[1]) + "," + NxCsv.F(p[2]));
                }
            }
            return true;
        }

        /// <summary>Score fiche 10 : P(positif) - P(negatif), entre -1 et +1.</summary>
        public static double ScoreOf(double[] p) { return p == null ? double.NaN : p[0] - p[1]; }
    }

    // =========================================================================
    //  Collecte d actualites en temps reel
    // =========================================================================
    public static class NxNewsFetchers
    {
        /// <summary>NewsAPI /v2/everything (titres en anglais, tries par date). Appel bloquant.</summary>
        public static List<NxNewsItem> NewsApi(string apiKey, string symbol, string query, DateTime fromUtc, out string error)
        {
            List<NxNewsItem> res = new List<NxNewsItem>();
            error = null;
            if (string.IsNullOrWhiteSpace(apiKey)) { error = "cle NewsAPI absente"; return res; }
            string q = string.IsNullOrWhiteSpace(query) ? symbol : query;
            string url = "https://newsapi.org/v2/everything?q=" + Uri.EscapeDataString(q) + "&language=en&sortBy=publishedAt&pageSize=50&from="
                       + Uri.EscapeDataString(fromUtc.ToString("yyyy-MM-ddTHH:mm:ss", CultureInfo.InvariantCulture));
            int status;
            string body = NxHttp.Request("GET", url, new Dictionary<string, string> { { "X-Api-Key", apiKey } }, null, 20000, out status, out error);
            object root;
            if (body == null || !NxJson.TryParse(body, out root)) { error = error ?? "reponse NewsAPI illisible"; return res; }
            if (status != 200) { error = "NewsAPI HTTP " + status + " " + NxJson.Str(NxJson.At(root, "message")); return res; }
            List<object> arts = NxJson.At(root, "articles") as List<object>;
            if (arts == null) return res;
            foreach (object a in arts)
            {
                DateTime t;
                string title = NxJson.Str(NxJson.At(a, "title"));
                if (string.IsNullOrWhiteSpace(title) || title == "[Removed]") continue;
                if (!NxCsv.TryParseDate(NxJson.Str(NxJson.At(a, "publishedAt")), out t)) continue;
                res.Add(new NxNewsItem
                {
                    PublishedUtc = t.Kind == DateTimeKind.Utc ? t : DateTime.SpecifyKind(t, DateTimeKind.Utc),
                    Symbol = symbol,
                    Source = "newsapi:" + (NxJson.Str(NxJson.At(a, "source.name")) ?? ""),
                    Headline = title,
                    Url = NxJson.Str(NxJson.At(a, "url")) ?? ""
                });
            }
            return res;
        }

        /// <summary>
        /// NewsAPI groupe : une requete "nom1 OR nom2 OR ..." pour plusieurs symboles ; chaque article est
        /// attribue aux symboles dont le nom (ou le ticker en majuscules) figure dans le titre ou la description.
        /// </summary>
        public static List<NxNewsItem> NewsApiBatch(string apiKey, Dictionary<string, string> symbolToQuery, DateTime fromUtc, out string error)
        {
            List<NxNewsItem> res = new List<NxNewsItem>();
            error = null;
            if (string.IsNullOrWhiteSpace(apiKey)) { error = "cle NewsAPI absente"; return res; }
            if (symbolToQuery == null || symbolToQuery.Count == 0) return res;
            string q = string.Join(" OR ", symbolToQuery.Values.Select(v => v.Contains(" ") ? "\"" + v + "\"" : v));
            string url = "https://newsapi.org/v2/everything?q=" + Uri.EscapeDataString(q) + "&language=en&sortBy=publishedAt&pageSize=100&searchIn=title,description&from="
                       + Uri.EscapeDataString(fromUtc.ToString("yyyy-MM-ddTHH:mm:ss", CultureInfo.InvariantCulture));
            int status;
            string body = NxHttp.Request("GET", url, new Dictionary<string, string> { { "X-Api-Key", apiKey } }, null, 20000, out status, out error);
            object root;
            if (body == null || !NxJson.TryParse(body, out root)) { error = error ?? "reponse NewsAPI illisible"; return res; }
            if (status != 200) { error = "NewsAPI HTTP " + status + " " + NxJson.Str(NxJson.At(root, "message")); return res; }
            List<object> arts = NxJson.At(root, "articles") as List<object>;
            if (arts == null) return res;
            foreach (object a in arts)
            {
                string title = NxJson.Str(NxJson.At(a, "title"));
                DateTime t;
                if (string.IsNullOrWhiteSpace(title) || title == "[Removed]" || !NxCsv.TryParseDate(NxJson.Str(NxJson.At(a, "publishedAt")), out t)) continue;
                string text = title + " " + (NxJson.Str(NxJson.At(a, "description")) ?? "");
                foreach (KeyValuePair<string, string> kv in symbolToQuery)
                {
                    bool byName = text.IndexOf(kv.Value, StringComparison.OrdinalIgnoreCase) >= 0;
                    bool byTicker = kv.Key.Length >= 2 && Regex.IsMatch(text, @"(?<![A-Za-z])\$?" + Regex.Escape(kv.Key) + @"(?![A-Za-z])");
                    if (!byName && !byTicker) continue;
                    res.Add(new NxNewsItem
                    {
                        PublishedUtc = t.Kind == DateTimeKind.Utc ? t : DateTime.SpecifyKind(t, DateTimeKind.Utc),
                        Symbol = kv.Key, Source = "newsapi:" + (NxJson.Str(NxJson.At(a, "source.name")) ?? ""),
                        Headline = title, Url = NxJson.Str(NxJson.At(a, "url")) ?? ""
                    });
                }
            }
            return res;
        }

        /// <summary>Recherche Reddit (titres de posts) dans les subreddits donnes, sur 24 h. Appel bloquant.</summary>
        public static List<NxNewsItem> Reddit(string symbol, IEnumerable<string> subreddits, out string error)
        {
            List<NxNewsItem> res = new List<NxNewsItem>();
            error = null;
            foreach (string sub in subreddits)
            {
                string url = "https://www.reddit.com/r/" + Uri.EscapeDataString(sub.Trim()) + "/search.json?q=" + Uri.EscapeDataString(symbol)
                           + "&restrict_sr=1&sort=new&t=day&limit=25";
                int status; string err;
                string body = NxHttp.Request("GET", url, new Dictionary<string, string> { { "User-Agent", "NexusNinjaScript/1.0 (research)" } }, null, 20000, out status, out err);
                object root;
                if (body == null || status != 200 || !NxJson.TryParse(body, out root)) { error = err ?? ("Reddit HTTP " + status); continue; }
                List<object> ch = NxJson.At(root, "data.children") as List<object>;
                if (ch == null) continue;
                foreach (object c in ch)
                {
                    double ts = NxJson.Num(NxJson.At(c, "data.created_utc"));
                    string title = NxJson.Str(NxJson.At(c, "data.title"));
                    if (!NxMath.Ok(ts) || string.IsNullOrWhiteSpace(title)) continue;
                    res.Add(new NxNewsItem
                    {
                        PublishedUtc = new DateTime(1970, 1, 1, 0, 0, 0, DateTimeKind.Utc).AddSeconds(ts),
                        Symbol = symbol,
                        Source = "reddit:r/" + sub.Trim(),
                        Headline = title,
                        Url = "https://www.reddit.com" + (NxJson.Str(NxJson.At(c, "data.permalink")) ?? "")
                    });
                }
            }
            return res;
        }
    }

    // =========================================================================
    //  Webhook (relais de signaux, fiche 13)
    // =========================================================================
    public static class NxWebhook
    {
        /// <summary>POST JSON asynchrone ; l en-tete X-Nexus-Secret porte le secret partage.</summary>
        public static void PostAsync(string url, string secret, string json, Action<string> log)
        {
            if (string.IsNullOrWhiteSpace(url)) return;
            Task.Run(() =>
            {
                int status; string err;
                Dictionary<string, string> h = new Dictionary<string, string> { { "Content-Type", "application/json" } };
                if (!string.IsNullOrEmpty(secret)) h["X-Nexus-Secret"] = secret;
                NxHttp.Request("POST", url, h, json, 10000, out status, out err);
                if ((status < 200 || status >= 300) && log != null) log("[Webhook] echec " + status + " " + err);
            });
        }
    }
}
