// =============================================================================
//  NexusModuleC_RiskValidation.cs   (NinjaTrader 8 / NinjaScript - bibliotheque)
//
//  MODULE C - Disjoncteurs, execution, couts et validation
//
//  Disjoncteurs [Fil]
//    - portefeuille a -15 % de son plus haut : nouvelles entrees rejetees, 12 h
//    - PnL du jour a -5 %                   : nouvelles entrees suspendues, 24 h
//    - lancement reel < 25 000 $            : avertissement regle PDT (US)
//  Execution [Fil]
//    - confirmation de remplissage : sondage 500 ms pendant 5 s puis annulation
//      (implemente dans NexusStrategyBase, minuterie temps reel)
//    - garde de cotation : rejeter toute cotation qui devie de plus de 35 %
//    - decalage de fin de periode (SIP retarde) : DataDelayMinutes
//    - suivi des stops : ordres natifs, ou "logiciel" (1 s crypto / 60 s actions)
//    - stress test : 8 a 10 positions correlees contre soi en meme temps
//  Couts [Fil] : glissement 0.05 %/trade, commission actions 0, frais Binance
//    0.1 %/ordre (0.075 % avec BNB)
//  Validation : walk-forward 180/30 [Fil], Monte Carlo 1 000 tirages [Fil],
//    bootstrap par blocs [arXiv 2608.21888], Deflated Sharpe [SSRN Bailey,
//    Lopez de Prado], PBO par CSCV [SSRN Bailey, Borwein, Lopez de Prado, Zhu],
//    seuils avant passage en reel (consensus du fil).
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
    //  Disjoncteurs
    // =========================================================================
    public class NxCircuitBreaker
    {
        public bool Enabled = true;
        public double DrawdownTripPct = 15.0;
        public double DrawdownCooldownHours = 12.0;
        public double DailyLossPct = 5.0;
        public double DailyCooldownHours = 24.0;
        public bool ResetPeakAfterCooldown = true;

        private double peak = double.NaN;
        private double dayStart = double.NaN;
        private DateTime day = DateTime.MinValue;
        private DateTime ddUntil = DateTime.MinValue;
        private DateTime dailyUntil = DateTime.MinValue;

        public int DrawdownTrips { get; private set; }
        public int DailyTrips { get; private set; }
        public string LastEvent { get; private set; }
        public double Peak { get { return peak; } }
        public double DayStartEquity { get { return dayStart; } }

        /// <summary>Retourne true si un nouvel evenement (declenchement / rearmement) vient d avoir lieu.</summary>
        public bool Update(DateTime now, DateTime tradingDay, double equity)
        {
            if (!Enabled || !NxMath.Ok(equity)) return false;
            bool evt = false;
            if (tradingDay.Date != day) { day = tradingDay.Date; dayStart = equity; }
            if (!NxMath.Ok(peak) || equity > peak) peak = equity;

            if (ddUntil != DateTime.MinValue && now >= ddUntil)
            {
                ddUntil = DateTime.MinValue;
                if (ResetPeakAfterCooldown) peak = equity;
                LastEvent = string.Format(CultureInfo.InvariantCulture, "{0:yyyy-MM-dd HH:mm} disjoncteur drawdown rearme (nouvelle reference {1:F2})", now, peak);
                evt = true;
            }
            if (dailyUntil != DateTime.MinValue && now >= dailyUntil)
            {
                dailyUntil = DateTime.MinValue;
                dayStart = equity;
                LastEvent = string.Format(CultureInfo.InvariantCulture, "{0:yyyy-MM-dd HH:mm} disjoncteur journalier rearme", now);
                evt = true;
            }
            if (ddUntil == DateTime.MinValue && peak > 0 && equity <= peak * (1 - DrawdownTripPct / 100.0))
            {
                ddUntil = now.AddHours(DrawdownCooldownHours);
                DrawdownTrips++;
                LastEvent = string.Format(CultureInfo.InvariantCulture,
                    "{0:yyyy-MM-dd HH:mm} DISJONCTEUR DRAWDOWN : equity {1:F2} <= {2:P0} du plus haut {3:F2} -> entrees rejetees jusqu au {4:yyyy-MM-dd HH:mm}",
                    now, equity, 1 - DrawdownTripPct / 100.0, peak, ddUntil);
                evt = true;
            }
            if (dailyUntil == DateTime.MinValue && dayStart > 0 && equity <= dayStart * (1 - DailyLossPct / 100.0))
            {
                dailyUntil = now.AddHours(DailyCooldownHours);
                DailyTrips++;
                LastEvent = string.Format(CultureInfo.InvariantCulture,
                    "{0:yyyy-MM-dd HH:mm} DISJONCTEUR JOURNALIER : PnL du jour {1:P2} -> entrees suspendues jusqu au {2:yyyy-MM-dd HH:mm}",
                    now, equity / dayStart - 1, dailyUntil);
                evt = true;
            }
            return evt;
        }

        public bool CanOpen(DateTime now, out string reason)
        {
            reason = null;
            if (!Enabled) return true;
            if (ddUntil != DateTime.MinValue && now < ddUntil) { reason = "disjoncteur drawdown -" + DrawdownTripPct + "% (jusqu au " + ddUntil.ToString("yyyy-MM-dd HH:mm") + ")"; return false; }
            if (dailyUntil != DateTime.MinValue && now < dailyUntil) { reason = "disjoncteur journalier -" + DailyLossPct + "% (jusqu au " + dailyUntil.ToString("yyyy-MM-dd HH:mm") + ")"; return false; }
            return true;
        }
    }

    // =========================================================================
    //  Modele de couts
    // =========================================================================
    public class NxCostModel
    {
        public double SlippagePct = 0.05;     // par ordre [Fil]
        public double EquityFeePct = 0.0;     // Alpaca : 0 $ [Fil]
        public double CryptoFeePct = 0.10;    // Binance : 0.1 % par ordre [Fil]
        public double CryptoBnbFeePct = 0.075;
        public bool UseBnb = false;
        public double OtherFeePct = 0.0;      // forex / futures / CFD (en %)
        public double PerContractFee = 0.0;   // futures / options ($ par contrat)

        public double FeePct(NxAssetClass c)
        {
            switch (c)
            {
                case NxAssetClass.Action:
                case NxAssetClass.Etf: return EquityFeePct;
                case NxAssetClass.Crypto: return UseBnb ? CryptoBnbFeePct : CryptoFeePct;
                default: return OtherFeePct;
            }
        }

        /// <summary>Cout modelise d un ordre execute (en devise du compte).</summary>
        public double Cost(NxAssetClass c, double notional, int qty)
        {
            double v = Math.Abs(notional) * (SlippagePct + FeePct(c)) / 100.0;
            if (c == NxAssetClass.Future || c == NxAssetClass.Option) v += Math.Abs(qty) * PerContractFee;
            return v;
        }

        public string Describe()
        {
            return string.Format(CultureInfo.InvariantCulture,
                "glissement {0:F3}%/ordre, frais actions {1:F3}%, crypto {2:F3}%, autres {3:F3}%, {4:F2}$/contrat",
                SlippagePct, EquityFeePct, UseBnb ? CryptoBnbFeePct : CryptoFeePct, OtherFeePct, PerContractFee);
        }
    }

    // =========================================================================
    //  Garde de cotation (bid = 0 hors seance IEX, prix aberrants)
    // =========================================================================
    public static class NxQuoteGuard
    {
        /// <summary>Prix de reference sur : mid si bid/ask coherents et proches de la reference, sinon la reference.</summary>
        public static double SafePrice(double bid, double ask, double reference, double maxDeviation, out bool usedFallback)
        {
            usedFallback = true;
            if (!NxMath.Ok(reference) || reference <= 0) reference = double.NaN;
            if (NxMath.Ok(bid) && NxMath.Ok(ask) && bid > 0 && ask > 0 && ask >= bid)
            {
                double mid = 0.5 * (bid + ask);
                if (!NxMath.Ok(reference) || Math.Abs(mid / reference - 1.0) <= maxDeviation) { usedFallback = false; return mid; }
            }
            return reference;
        }

        public static bool IsValid(double price, double reference, double maxDeviation)
        {
            if (!NxMath.Ok(price) || price <= 0) return false;
            if (!NxMath.Ok(reference) || reference <= 0) return true;
            return Math.Abs(price / reference - 1.0) <= maxDeviation;
        }

        /// <summary>Ecart relatif (ask-bid)/mid ; NaN si cotation invalide.</summary>
        public static double SpreadPct(double bid, double ask)
        {
            if (!NxMath.Ok(bid) || !NxMath.Ok(ask) || bid <= 0 || ask <= 0 || ask < bid) return double.NaN;
            return (ask - bid) / (0.5 * (ask + bid));
        }
    }

    // =========================================================================
    //  Interrupteur global (fichier Nexus\KILL_SWITCH) - fiche 13 / module C
    // =========================================================================
    public static class NxKillSwitch
    {
        private static DateTime lastCheck = DateTime.MinValue;
        private static bool cached;
        private static readonly object sync = new object();

        public static bool IsActive()
        {
            lock (sync)
            {
                if ((DateTime.UtcNow - lastCheck).TotalSeconds >= 2)
                {
                    try { cached = File.Exists(NxPaths.KillSwitchFile); } catch { cached = false; }
                    lastCheck = DateTime.UtcNow;
                }
                return cached;
            }
        }

        public static void Activate(string reason)
        {
            NxCsv.WriteAll(NxPaths.KillSwitchFile, DateTime.UtcNow.ToString("o") + " " + (reason ?? ""));
            lock (sync) { cached = true; lastCheck = DateTime.UtcNow; }
        }
    }

    // =========================================================================
    //  Registre des chocs taker (fiche 4B utilisee comme filtre de timing)
    // =========================================================================
    public static class NxShockRegistry
    {
        private class Shock { public DateTime UntilUtc; public double Mid; public int Direction; }
        private static readonly Dictionary<string, Shock> shocks = new Dictionary<string, Shock>(StringComparer.OrdinalIgnoreCase);
        private static readonly object sync = new object();

        public static void Mark(string symbol, DateTime untilUtc, double shockBarMid, int direction)
        {
            lock (sync) shocks[symbol] = new Shock { UntilUtc = untilUtc, Mid = shockBarMid, Direction = direction };
        }

        /// <summary>true si une bougie de choc portee par le flux taker est recente ; mid = milieu de la barre de choc.</summary>
        public static bool IsInShock(string symbol, DateTime nowUtc, out double mid, out int direction)
        {
            mid = double.NaN; direction = 0;
            lock (sync)
            {
                Shock s;
                if (!shocks.TryGetValue(symbol, out s)) return false;
                if (nowUtc > s.UntilUtc) { shocks.Remove(symbol); return false; }
                mid = s.Mid; direction = s.Direction;
                return true;
            }
        }
    }

    // =========================================================================
    //  Trade cloture (aller-retour plat -> plat)
    // =========================================================================
    public class NxTradeRecord
    {
        public string Strategy;
        public string Symbol;
        public NxAssetClass Class;
        public int Direction;                 // +1 long, -1 court
        public int MaxQty;
        public DateTime EntryTime;
        public DateTime ExitTime;
        public double EntryPrice;
        public double ExitPrice;
        public double MaxNotional;
        public double GrossPnl;
        public double Costs;
        public double NetPnl;
        public double NetReturn;              // NetPnl / notionnel max
        public double GrossReturn;
        public string EntryReason = "";
        public string ExitReason = "";
        public string Regime = "";
        public bool IsRealtime;
        public bool IsRealMoney;

        public static string CsvHeader
        {
            get { return "strategy,symbol,class,direction,max_qty,entry_time,exit_time,entry_price,exit_price,max_notional,gross_pnl,costs,net_pnl,net_return,gross_return,entry_reason,exit_reason,regime,realtime,real_money"; }
        }

        public string ToCsv()
        {
            return string.Join(",", new[]
            {
                NxCsv.Escape(Strategy), NxCsv.Escape(Symbol), Class.ToString(), Direction.ToString(CultureInfo.InvariantCulture),
                MaxQty.ToString(CultureInfo.InvariantCulture), NxCsv.D(EntryTime), NxCsv.D(ExitTime), NxCsv.F(EntryPrice), NxCsv.F(ExitPrice),
                NxCsv.F(MaxNotional, 2), NxCsv.F(GrossPnl, 2), NxCsv.F(Costs, 2), NxCsv.F(NetPnl, 2), NxCsv.F(NetReturn), NxCsv.F(GrossReturn),
                NxCsv.Escape(EntryReason), NxCsv.Escape(ExitReason), NxCsv.Escape(Regime), IsRealtime ? "1" : "0", IsRealMoney ? "1" : "0"
            });
        }
    }

    // =========================================================================
    //  Journal CSV par strategie (trades, remplissages, signaux, rendements)
    // =========================================================================
    public class NxJournal
    {
        public readonly string StrategyId;
        public bool Enabled;
        private readonly string tradesFile, fillsFile, signalsFile, returnsFile;

        public NxJournal(string strategyId, bool enabled)
        {
            StrategyId = NxPaths.SafeFileName(strategyId);
            Enabled = enabled;
            tradesFile = Path.Combine(NxPaths.Journal, "trades_" + StrategyId + ".csv");
            fillsFile = Path.Combine(NxPaths.Journal, "fills_" + StrategyId + ".csv");
            signalsFile = Path.Combine(NxPaths.Journal, "signals_" + StrategyId + ".csv");
            returnsFile = Path.Combine(NxPaths.Journal, "returns_" + StrategyId + ".csv");
        }

        public string TradesFile { get { return tradesFile; } }
        public string FillsFile { get { return fillsFile; } }

        public void Trade(NxTradeRecord r) { if (Enabled) NxCsv.AppendLine(tradesFile, NxTradeRecord.CsvHeader, r.ToCsv()); }

        public void Fill(DateTime t, string symbol, string action, int qty, double expected, double fill, string orderName, bool realtime, bool realMoney)
        {
            if (!Enabled) return;
            double slip = (NxMath.Ok(expected) && expected > 0 && NxMath.Ok(fill)) ? (fill / expected - 1.0) : double.NaN;
            NxCsv.AppendLine(fillsFile, "time,symbol,action,qty,expected_price,fill_price,slippage,order,realtime,real_money",
                string.Join(",", new[] { NxCsv.D(t), NxCsv.Escape(symbol), action, qty.ToString(CultureInfo.InvariantCulture),
                    NxCsv.F(expected), NxCsv.F(fill), NxCsv.F(slip), NxCsv.Escape(orderName), realtime ? "1" : "0", realMoney ? "1" : "0" }));
        }

        public void Signal(DateTime t, string symbol, string kind, string detail)
        {
            if (!Enabled) return;
            NxCsv.AppendLine(signalsFile, "time,symbol,kind,detail",
                string.Join(",", new[] { NxCsv.D(t), NxCsv.Escape(symbol), NxCsv.Escape(kind), NxCsv.Escape(NxText.OneLine(detail, 1000)) }));
        }

        public void DailyReturn(DateTime day, double equity, double ret)
        {
            if (!Enabled) return;
            NxCsv.AppendLine(returnsFile, "date,equity,return",
                day.ToString("yyyy-MM-dd", CultureInfo.InvariantCulture) + "," + NxCsv.F(equity, 2) + "," + NxCsv.F(ret, 8));
        }

        /// <summary>Nombre total de trades fermes dans tous les journaux (seuil des 1 000 trades).</summary>
        public static int CountAllJournalTrades(out int strategies)
        {
            strategies = 0;
            int total = 0;
            try
            {
                if (!Directory.Exists(NxPaths.Journal)) return 0;
                foreach (string f in Directory.GetFiles(NxPaths.Journal, "trades_*.csv"))
                {
                    int n = File.ReadLines(f).Count(l => l.Trim().Length > 0) - 1;
                    if (n > 0) { total += n; strategies++; }
                }
            }
            catch { }
            return total;
        }

        /// <summary>Statistiques de glissement reel (fills temps reel sur compte reel) : nombre et moyenne.</summary>
        public static void RealFillSlippage(string fillsFile, out int n, out double meanAbsSlip)
        {
            n = 0; meanAbsSlip = double.NaN;
            string[] h;
            List<string[]> rows = NxCsv.ReadRows(fillsFile, out h);
            int cs = NxCsv.Col(h, "slippage"), cr = NxCsv.Col(h, "real_money");
            if (cs < 0 || cr < 0) return;
            List<double> v = new List<double>();
            foreach (string[] r in rows)
                if (NxCsv.Get(r, cr) == "1") { double s = NxCsv.ParseDouble(NxCsv.Get(r, cs)); if (NxMath.Ok(s)) v.Add(Math.Abs(s)); }
            n = v.Count;
            if (n > 0) meanAbsSlip = v.Average();
        }
    }

    // =========================================================================
    //  Outils de validation statistique
    // =========================================================================
    public static class NxValidation
    {
        public static List<double> EquityFromPnls(IList<double> pnls, double start)
        {
            List<double> e = new List<double>(pnls.Count + 1) { start };
            double v = start;
            foreach (double p in pnls) { v += p; e.Add(v); }
            return e;
        }

        /// <summary>Drawdown maximal (fraction positive) d une courbe d equity.</summary>
        public static double MaxDrawdown(IList<double> equity)
        {
            double peak = double.NaN, mdd = 0;
            foreach (double v in equity)
            {
                if (!NxMath.Ok(v)) continue;
                if (!NxMath.Ok(peak) || v > peak) peak = v;
                if (peak > 0) mdd = Math.Max(mdd, 1 - v / peak);
            }
            return mdd;
        }

        public static double Percentile(double[] sorted, double q)
        {
            if (sorted == null || sorted.Length == 0) return double.NaN;
            return NxMath.Quantile(sorted, q);
        }

        /// <summary>Monte Carlo : tirage avec remise des trades, distribution du drawdown max (triee).</summary>
        public static double[] MonteCarloMaxDD(IList<double> pnls, double start, int sims, int seed)
        {
            int n = pnls.Count;
            if (n == 0) return new double[0];
            Random rng = new Random(seed);
            double[] res = new double[sims];
            for (int s = 0; s < sims; s++)
            {
                double v = start, peak = start, mdd = 0;
                for (int i = 0; i < n; i++)
                {
                    v += pnls[rng.Next(n)];
                    if (v > peak) peak = v;
                    if (peak > 0) mdd = Math.Max(mdd, 1 - v / peak);
                }
                res[s] = mdd;
            }
            Array.Sort(res);
            return res;
        }

        /// <summary>Bootstrap par blocs mobiles (conserve l autocorrelation des trades consecutifs).</summary>
        public static double[] BlockBootstrapMaxDD(IList<double> pnls, double start, int blockLength, int sims, int seed)
        {
            int n = pnls.Count;
            if (n == 0) return new double[0];
            int L = Math.Max(1, Math.Min(blockLength <= 0 ? (int)Math.Round(Math.Sqrt(n)) : blockLength, n));
            Random rng = new Random(seed);
            double[] res = new double[sims];
            for (int s = 0; s < sims; s++)
            {
                double v = start, peak = start, mdd = 0;
                int taken = 0;
                while (taken < n)
                {
                    int b = rng.Next(n - L + 1);
                    for (int k = 0; k < L && taken < n; k++, taken++)
                    {
                        v += pnls[b + k];
                        if (v > peak) peak = v;
                        if (peak > 0) mdd = Math.Max(mdd, 1 - v / peak);
                    }
                }
                res[s] = mdd;
            }
            Array.Sort(res);
            return res;
        }

        public static double SharpePerPeriod(IList<double> rets)
        {
            double m = NxMath.Mean(rets), s = NxMath.StdDev(rets);
            return (NxMath.Ok(m) && NxMath.Ok(s) && s > 0) ? m / s : double.NaN;
        }

        public static double AnnualizedSharpe(IList<double> rets, double periodsPerYear = NxMath.TradingDaysPerYear)
        {
            double sr = SharpePerPeriod(rets);
            return NxMath.Ok(sr) ? sr * Math.Sqrt(periodsPerYear) : double.NaN;
        }

        /// <summary>Probabilistic Sharpe Ratio : P(SR vrai &gt; srBenchmark), SR par periode.</summary>
        public static double ProbabilisticSharpe(double sr, double srBenchmark, int n, double skew, double kurt)
        {
            if (!NxMath.Ok(sr) || n < 3) return double.NaN;
            double den = 1 - skew * sr + (kurt - 1) / 4.0 * sr * sr;
            if (den <= 0) return double.NaN;
            return NxMath.NormCdf((sr - srBenchmark) * Math.Sqrt(n - 1) / Math.Sqrt(den));
        }

        /// <summary>SR0 : Sharpe maximal attendu sous l hypothese nulle apres N essais (variance des SR des essais V).</summary>
        public static double ExpectedMaxSharpe(int nTrials, double varTrials)
        {
            if (nTrials <= 1 || !NxMath.Ok(varTrials) || varTrials <= 0) return 0.0;
            double g = NxMath.EulerGamma;
            return Math.Sqrt(varTrials) * ((1 - g) * NxMath.NormInv(1 - 1.0 / nTrials) + g * NxMath.NormInv(1 - 1.0 / (nTrials * Math.E)));
        }

        /// <summary>
        /// Deflated Sharpe Ratio (Bailey, Lopez de Prado). varTrials = variance des SR (par periode) des essais ;
        /// NaN => approximation par la variance d estimation du SR.
        /// </summary>
        public static double DeflatedSharpe(IList<double> rets, int nTrials, double varTrials, out double sr0)
        {
            sr0 = double.NaN;
            List<double> r = rets.Where(NxMath.Ok).ToList();
            int n = r.Count;
            if (n < 10) return double.NaN;
            double sr = SharpePerPeriod(r), sk = NxMath.Skewness(r), ku = NxMath.Kurtosis(r);
            if (!NxMath.Ok(sr)) return double.NaN;
            if (!NxMath.Ok(varTrials) || varTrials <= 0)
                varTrials = Math.Max(1e-12, (1 - sk * sr + (ku - 1) / 4.0 * sr * sr) / (n - 1));
            sr0 = ExpectedMaxSharpe(Math.Max(1, nTrials), varTrials);
            return ProbabilisticSharpe(sr, sr0, n, sk, ku);
        }

        /// <summary>
        /// Probability of Backtest Overfitting par CSCV. configs[i][t] = rendement de la config i a la date t
        /// (series alignees, meme longueur). S blocs (pair). Renvoie NaN si donnees insuffisantes.
        /// </summary>
        public static double Pbo(List<double[]> configs, int S, int maxCombos, int seed, out int combosUsed)
        {
            combosUsed = 0;
            if (configs == null || configs.Count < 2) return double.NaN;
            int N = configs.Count;
            int T = configs.Min(c => c.Length);
            if (S % 2 == 1) S--;
            if (S < 2 || T < S * 5) return double.NaN;
            int blk = T / S;
            // Agregats par bloc : somme, somme des carres, effectif.
            double[,] sum = new double[N, S], sq = new double[N, S];
            int[,] cnt = new int[N, S];
            for (int i = 0; i < N; i++)
                for (int s = 0; s < S; s++)
                    for (int t = s * blk; t < (s + 1) * blk; t++)
                    {
                        double v = configs[i][t];
                        if (!NxMath.Ok(v)) continue;
                        sum[i, s] += v; sq[i, s] += v * v; cnt[i, s]++;
                    }
            List<int> masks = new List<int>();
            for (int m = 0; m < (1 << S); m++) if (PopCount(m) == S / 2) masks.Add(m);
            if (masks.Count > maxCombos && maxCombos > 0)
            {
                Random rng = new Random(seed);
                masks = masks.OrderBy(x => rng.Next()).Take(maxCombos).ToList();
            }
            int below = 0;
            foreach (int m in masks)
            {
                double[] isPerf = new double[N], oosPerf = new double[N];
                for (int i = 0; i < N; i++)
                {
                    double s1 = 0, q1 = 0, s2 = 0, q2 = 0; int c1 = 0, c2 = 0;
                    for (int s = 0; s < S; s++)
                    {
                        if ((m & (1 << s)) != 0) { s1 += sum[i, s]; q1 += sq[i, s]; c1 += cnt[i, s]; }
                        else { s2 += sum[i, s]; q2 += sq[i, s]; c2 += cnt[i, s]; }
                    }
                    isPerf[i] = SharpeFromAgg(s1, q1, c1);
                    oosPerf[i] = SharpeFromAgg(s2, q2, c2);
                }
                int best = 0;
                for (int i = 1; i < N; i++) if (isPerf[i] > isPerf[best]) best = i;
                // Rang relatif hors echantillon (1 = plus mauvais).
                int rank = 1;
                for (int i = 0; i < N; i++) if (i != best && oosPerf[i] < oosPerf[best]) rank++;
                double w = rank / (N + 1.0);
                double lambda = Math.Log(w / (1 - w));
                if (lambda <= 0) below++;
                combosUsed++;
            }
            return combosUsed > 0 ? (double)below / combosUsed : double.NaN;
        }

        private static double SharpeFromAgg(double s, double q, int c)
        {
            if (c < 3) return double.NegativeInfinity;
            double m = s / c;
            double v = (q - c * m * m) / (c - 1);
            return v > 0 ? m / Math.Sqrt(v) : (m > 0 ? 1e6 : -1e6);
        }

        private static int PopCount(int x) { int c = 0; while (x != 0) { c += x & 1; x >>= 1; } return c; }

        /// <summary>Fenetres walk-forward [debutEntr, finEntr, debutTest, finTest) - 180/30 par defaut [Fil].</summary>
        public static List<int[]> WalkForwardSplits(int n, int train = 180, int test = 30)
        {
            List<int[]> res = new List<int[]>();
            for (int start = 0; start + train + test <= n; start += test)
                res.Add(new[] { start, start + train, start + train, start + train + test });
            return res;
        }

        /// <summary>Au moins un cycle complet drawdown (&gt;= minDd) -&gt; recuperation (nouveau plus haut).</summary>
        public static bool HasDrawdownRecoveryCycle(IList<double> equity, double minDd, out double deepest, out int bars)
        {
            deepest = 0; bars = 0;
            double peak = double.NaN, trough = double.NaN;
            int peakIdx = 0;
            bool inDd = false, found = false;
            for (int i = 0; i < equity.Count; i++)
            {
                double v = equity[i];
                if (!NxMath.Ok(v)) continue;
                if (!NxMath.Ok(peak) || v >= peak)
                {
                    if (inDd)
                    {
                        found = true;
                        double depth = 1 - trough / peak;
                        if (depth > deepest) { deepest = depth; bars = i - peakIdx; }
                        inDd = false;
                    }
                    peak = v; peakIdx = i; trough = v;
                    continue;
                }
                if (v < trough) trough = v;
                if (peak > 0 && 1 - v / peak >= minDd) inDd = true;
            }
            return found;
        }
    }

    // =========================================================================
    //  Stress test : positions correlees qui vont toutes contre soi
    // =========================================================================
    public class NxStressPosition
    {
        public string Symbol;
        public int Qty;              // signe
        public double Price;
        public double Stop;          // NaN si aucun
        public double ValuePerPoint; // PointValue * conversion devise
    }

    public static class NxStressTest
    {
        public static string Run(List<NxStressPosition> pos, double equity, double shockPct, int worstN)
        {
            StringBuilder sb = new StringBuilder();
            if (pos == null || pos.Count == 0 || !(equity > 0)) return "Stress test : aucune position ouverte.";
            double stopLoss = 0, shockLoss = 0, noStopExposure = 0;
            foreach (NxStressPosition p in pos)
            {
                double notional = Math.Abs(p.Qty) * p.Price * p.ValuePerPoint;
                if (NxMath.Ok(p.Stop)) stopLoss += Math.Abs(p.Qty) * Math.Abs(p.Price - p.Stop) * p.ValuePerPoint;
                else noStopExposure += notional;
                shockLoss += notional * shockPct;
            }
            List<double> exposures = pos.Select(p => Math.Abs(p.Qty) * p.Price * p.ValuePerPoint).OrderByDescending(x => x).ToList();
            double worst = exposures.Take(Math.Max(1, worstN)).Sum() * shockPct;
            sb.AppendLine(string.Format(CultureInfo.InvariantCulture, "Stress test ({0} positions, equity {1:F0}) :", pos.Count, equity));
            sb.AppendLine(string.Format(CultureInfo.InvariantCulture, "  tous les stops touches ensemble      : -{0:F0} ({1:P1})", stopLoss, stopLoss / equity));
            sb.AppendLine(string.Format(CultureInfo.InvariantCulture, "  choc -{0:P0} sur TOUTES les positions  : -{1:F0} ({2:P1})", shockPct, shockLoss, shockLoss / equity));
            sb.AppendLine(string.Format(CultureInfo.InvariantCulture, "  choc -{0:P0} sur les {1} plus grosses : -{2:F0} ({3:P1})", shockPct, worstN, worst, worst / equity));
            if (noStopExposure > 0) sb.AppendLine(string.Format(CultureInfo.InvariantCulture, "  exposition sans stop : {0:F0} ({1:P1})", noStopExposure, noStopExposure / equity));
            return sb.ToString();
        }
    }

    // =========================================================================
    //  Rapport de fin de backtest (validation + checklist avant reel)
    // =========================================================================
    public class NxReportInput
    {
        public string StrategyId;
        public string Title;
        public string Parameters;
        public double InitialEquity;
        public List<NxTradeRecord> Trades = new List<NxTradeRecord>();
        public List<DateTime> Days = new List<DateTime>();
        public List<double> DailyReturns = new List<double>();
        public List<double> Equity = new List<double>();
        public NxCostModel Costs;
        public bool HasCrypto;
        public int MonteCarloSims = 1000;
        public int BlockLength = 0;
        public int Seed = 7;
        public int Trials = 1;
        public double VarTrialsSharpe = double.NaN;
        public double Pbo = double.NaN;
        public int PboConfigs;
        public int PboCombos;
        public int CircuitDdTrips;
        public int CircuitDailyTrips;
        public double AiCostUsd = double.NaN;
        public long AiTokens;
        public string FillsFile;
        public List<string> Extra = new List<string>();
    }

    public static class NxReport
    {
        public static string Build(NxReportInput r)
        {
            CultureInfo ci = CultureInfo.InvariantCulture;
            StringBuilder sb = new StringBuilder();
            string line = new string('=', 78);
            sb.AppendLine(line);
            sb.AppendLine(" RAPPORT NEXUS - " + r.Title);
            sb.AppendLine(" Genere le " + DateTime.Now.ToString("yyyy-MM-dd HH:mm:ss", ci) + "  |  id : " + r.StrategyId);
            sb.AppendLine(line);
            if (!string.IsNullOrEmpty(r.Parameters)) { sb.AppendLine("Parametres : " + r.Parameters); sb.AppendLine(); }

            List<NxTradeRecord> t = r.Trades ?? new List<NxTradeRecord>();
            int n = t.Count;
            double net = t.Sum(x => x.NetPnl), gross = t.Sum(x => x.GrossPnl), costs = t.Sum(x => x.Costs);
            int wins = t.Count(x => x.NetPnl > 0);
            double p = n > 0 ? (double)wins / n : double.NaN;
            double avgW = t.Where(x => x.NetReturn > 0).Select(x => x.NetReturn).DefaultIfEmpty(double.NaN).Average();
            double avgL = -t.Where(x => x.NetReturn <= 0).Select(x => x.NetReturn).DefaultIfEmpty(double.NaN).Average();
            double b = (NxMath.Ok(avgW) && NxMath.Ok(avgL) && avgL > 0) ? avgW / avgL : double.NaN;
            double kelly = NxKelly.Fraction(p, b);
            double lo, hi;
            NxKelly.Wilson(wins, n, 1.96, out lo, out hi);

            sb.AppendLine("--- Trades -------------------------------------------------------------------");
            sb.AppendLine(string.Format(ci, "Trades fermes          : {0}  (gagnants {1})", n, wins));
            sb.AppendLine(string.Format(ci, "Taux de reussite       : {0:P1}  IC95% Wilson [{1:P1} ; {2:P1}]", p, lo, hi));
            sb.AppendLine(string.Format(ci, "Gain moyen / perte moy.: {0:P2} / {1:P2}  -> b = {2:F2}  (b mini pour Kelly>0 : {3:F2})", avgW, avgL, b, NxKelly.BreakEvenPayoff(p)));
            sb.AppendLine(string.Format(ci, "Kelly f* (point)       : {0:F4}   [p bas -> {1:F4} ; p haut -> {2:F4}]", kelly, NxKelly.Fraction(lo, b), NxKelly.Fraction(hi, b)));
            sb.AppendLine(string.Format(ci, "PnL brut / couts / net : {0:F2} / {1:F2} / {2:F2}", gross, costs, net));
            if (r.Costs != null) sb.AppendLine("Couts modelises        : " + r.Costs.Describe());
            if (gross != 0) sb.AppendLine(string.Format(ci, "Effet des couts        : le PnL sans couts serait surestime de {0:F2} ({1:P1} du brut)", costs, costs / Math.Abs(gross)));
            if (NxMath.Ok(r.AiCostUsd) || r.AiTokens > 0)
                sb.AppendLine(string.Format(ci, "Cout API IA            : {0:F2} $ ({1} tokens) -> PnL net apres IA : {2:F2}", NxMath.Ok(r.AiCostUsd) ? r.AiCostUsd : 0, r.AiTokens, net - (NxMath.Ok(r.AiCostUsd) ? r.AiCostUsd : 0)));
            sb.AppendLine();

            List<double> eq = r.Equity != null && r.Equity.Count > 1 ? r.Equity : NxValidation.EquityFromPnls(t.Select(x => x.NetPnl).ToList(), r.InitialEquity);
            double mdd = NxValidation.MaxDrawdown(eq);
            double sh = NxValidation.AnnualizedSharpe(r.DailyReturns);
            double totalRet = eq.Count > 1 && eq[0] > 0 ? eq[eq.Count - 1] / eq[0] - 1 : double.NaN;
            double years = r.Days != null && r.Days.Count > 1 ? (r.Days[r.Days.Count - 1] - r.Days[0]).TotalDays / 365.25 : double.NaN;
            double cagr = NxMath.Ok(years) && years > 0.1 && totalRet > -1 ? Math.Pow(1 + totalRet, 1 / years) - 1 : double.NaN;
            sb.AppendLine("--- Portefeuille --------------------------------------------------------------");
            sb.AppendLine(string.Format(ci, "Rendement total / CAGR : {0:P2} / {1:P2}  sur {2:F1} ans", totalRet, cagr, years));
            sb.AppendLine(string.Format(ci, "Sharpe annualise       : {0:F2}   Drawdown max : {1:P2}", sh, mdd));
            double dd; int bars;
            bool cycle = NxValidation.HasDrawdownRecoveryCycle(eq, 0.05, out dd, out bars);
            sb.AppendLine(string.Format(ci, "Cycle drawdown->recup. : {0}{1}", cycle ? "oui" : "non", cycle ? string.Format(ci, " (plus profond {0:P1}, {1} pas)", dd, bars) : ""));
            sb.AppendLine(string.Format(ci, "Disjoncteurs           : drawdown x{0}, journalier x{1}", r.CircuitDdTrips, r.CircuitDailyTrips));
            sb.AppendLine();

            sb.AppendLine("--- Monte Carlo (" + r.MonteCarloSims + " tirages) -------------------------------------------");
            List<double> pnls = t.Select(x => x.NetPnl).ToList();
            if (pnls.Count >= 5)
            {
                double[] mc = NxValidation.MonteCarloMaxDD(pnls, r.InitialEquity, r.MonteCarloSims, r.Seed);
                double[] bb = NxValidation.BlockBootstrapMaxDD(pnls, r.InitialEquity, r.BlockLength, r.MonteCarloSims, r.Seed + 1);
                sb.AppendLine(string.Format(ci, "DD max, tirage simple  : mediane {0:P1} | 95% {1:P1} | 99% {2:P1}", NxValidation.Percentile(mc, 0.5), NxValidation.Percentile(mc, 0.95), NxValidation.Percentile(mc, 0.99)));
                sb.AppendLine(string.Format(ci, "DD max, blocs mobiles  : mediane {0:P1} | 95% {1:P1} | 99% {2:P1}  (bloc {3})", NxValidation.Percentile(bb, 0.5), NxValidation.Percentile(bb, 0.95), NxValidation.Percentile(bb, 0.99),
                    r.BlockLength > 0 ? r.BlockLength : (int)Math.Round(Math.Sqrt(pnls.Count))));
            }
            else sb.AppendLine("  (moins de 5 trades : simulation non significative)");
            sb.AppendLine();

            sb.AppendLine("--- Sur-ajustement -------------------------------------------------------------");
            double sr0;
            double dsr = NxValidation.DeflatedSharpe(r.DailyReturns, Math.Max(1, r.Trials), r.VarTrialsSharpe, out sr0);
            sb.AppendLine(string.Format(ci, "Deflated Sharpe        : {0:P1} (probabilite que le Sharpe vrai > SR0={1:F4}/jour, {2} essai(s))", dsr, sr0, Math.Max(1, r.Trials)));
            if (NxMath.Ok(r.Pbo))
                sb.AppendLine(string.Format(ci, "PBO (CSCV)             : {0:P1} sur {1} configurations, {2} combinaisons{3}", r.Pbo, r.PboConfigs, r.PboCombos, r.Pbo > 0.5 ? "  -> SUR-AJUSTEMENT PROBABLE" : ""));
            else sb.AppendLine("PBO (CSCV)             : n/a (activer 'Sauver rendements pour PBO' et lancer une optimisation)");
            sb.AppendLine("Walk-forward           : utiliser l optimisation walk-forward NinjaTrader 180 j / 30 j [Fil]");
            sb.AppendLine();

            if (r.Extra != null && r.Extra.Count > 0)
            {
                sb.AppendLine("--- Specifique a la strategie -------------------------------------------------");
                foreach (string s in r.Extra) sb.AppendLine(s);
                sb.AppendLine();
            }

            sb.AppendLine("--- Seuils avant passage en reel (consensus du fil) ---------------------------");
            int nStrat;
            int journalTrades = NxJournal.CountAllJournalTrades(out nStrat);
            int fillN; double fillSlip;
            NxJournal.RealFillSlippage(r.FillsFile, out fillN, out fillSlip);
            sb.AppendLine(Check(journalTrades + n >= 1000, string.Format(ci, "au moins 1 000 trades resolus au total (journaux {0} + ce run {1})", journalTrades, n)));
            sb.AppendLine(Check(n >= 30 && cycle, string.Format(ci, "au moins 30 trades fermes ({0}) ET un cycle drawdown -> recuperation ({1})", n, cycle ? "oui" : "non")));
            sb.AppendLine(Check(net > 0, string.Format(ci, "frais {0}modelises et PnL encore positif (net {1:F2})", r.HasCrypto ? "Binance " : "", net)));
            sb.AppendLine(Check(fillN >= 20, string.Format(ci, "remplissages reels compares au paper ({0} fills reels, glissement moyen {1:P3})", fillN, fillSlip)));
            sb.AppendLine("Rappel : faire auditer la methode par une seconde IA (markwmke y a trouve un filtre tautologique).");
            sb.AppendLine(line);
            return sb.ToString();
        }

        private static string Check(bool ok, string text) { return (ok ? "[x] " : "[ ] ") + text; }

        public static string Write(string strategyId, string content)
        {
            string path = Path.Combine(NxPaths.Reports, NxPaths.SafeFileName(strategyId) + "_" + DateTime.Now.ToString("yyyyMMdd_HHmmss", CultureInfo.InvariantCulture) + ".txt");
            NxCsv.WriteAll(path, content);
            return path;
        }
    }

    // =========================================================================
    //  Rendements par configuration (PBO / DSR multi-essais)
    // =========================================================================
    public static class NxTrialStore
    {
        public static string Folder(string strategyName) { return Path.Combine(NxPaths.Returns, NxPaths.SafeFileName(strategyName)); }

        public static void Save(string strategyName, string configKey, List<DateTime> days, List<double> rets)
        {
            if (days == null || rets == null || days.Count == 0) return;
            StringBuilder sb = new StringBuilder();
            sb.AppendLine("# config: " + configKey.Replace("\n", " "));
            sb.AppendLine("date,return");
            for (int i = 0; i < Math.Min(days.Count, rets.Count); i++)
                sb.AppendLine(days[i].ToString("yyyy-MM-dd", CultureInfo.InvariantCulture) + "," + NxCsv.F(rets[i], 8));
            NxCsv.WriteAll(Path.Combine(Folder(strategyName), NxText.Hash(configKey) + ".csv"), sb.ToString());
        }

        /// <summary>Charge toutes les configurations et les aligne sur les dates communes.</summary>
        public static List<double[]> LoadAligned(string strategyName, out int nConfigs, out double varSharpe)
        {
            nConfigs = 0; varSharpe = double.NaN;
            string dir = Folder(strategyName);
            List<double[]> res = new List<double[]>();
            if (!Directory.Exists(dir)) return res;
            List<Dictionary<DateTime, double>> all = new List<Dictionary<DateTime, double>>();
            foreach (string f in Directory.GetFiles(dir, "*.csv"))
            {
                string[] h;
                List<string[]> rows = NxCsv.ReadRows(f, out h);
                int cd = NxCsv.Col(h, "date"), cr = NxCsv.Col(h, "return");
                if (cd < 0 || cr < 0) continue;
                Dictionary<DateTime, double> d = new Dictionary<DateTime, double>();
                foreach (string[] r in rows)
                {
                    DateTime dt;
                    if (NxCsv.TryParseDate(NxCsv.Get(r, cd), out dt)) d[dt.Date] = NxCsv.ParseDouble(NxCsv.Get(r, cr));
                }
                if (d.Count > 20) all.Add(d);
            }
            nConfigs = all.Count;
            if (all.Count == 0) return res;
            HashSet<DateTime> common = new HashSet<DateTime>(all[0].Keys);
            foreach (Dictionary<DateTime, double> d in all.Skip(1)) common.IntersectWith(d.Keys);
            List<DateTime> dates = common.OrderBy(x => x).ToList();
            List<double> srs = new List<double>();
            foreach (Dictionary<DateTime, double> d in all)
            {
                double[] arr = dates.Select(x => d[x]).ToArray();
                res.Add(arr);
                double sr = NxValidation.SharpePerPeriod(arr);
                if (NxMath.Ok(sr)) srs.Add(sr);
            }
            if (srs.Count >= 2) varSharpe = NxMath.Variance(srs);
            return res;
        }
    }
}
