using System;
using System.Collections.Generic;
using System.Globalization;
using System.Linq;
using NinjaTrader.NinjaScript.AddOns.Nexus;

static class T
{
    static int pass, fail;
    static void Check(string name, bool ok, string detail = "")
    {
        if (ok) pass++; else fail++;
        Console.WriteLine((ok ? "  OK   " : "  FAIL ") + name + (detail.Length > 0 ? "  [" + detail + "]" : ""));
    }
    static string F(double x) { return x.ToString("G6", CultureInfo.InvariantCulture); }
    static double Gauss(Random r) { double u1 = 1.0 - r.NextDouble(), u2 = r.NextDouble(); return Math.Sqrt(-2 * Math.Log(u1)) * Math.Cos(2 * Math.PI * u2); }

    static void Main()
    {
        System.Threading.Thread.CurrentThread.CurrentCulture = CultureInfo.InvariantCulture;
        Console.WriteLine("== Loi normale");
        Check("NormCdf(1.96)=0.9750021", Math.Abs(NxMath.NormCdf(1.96) - 0.9750021) < 2e-7, F(NxMath.NormCdf(1.96)));
        Check("NormCdf(-3)=0.0013499", Math.Abs(NxMath.NormCdf(-3) - 0.0013499) < 2e-7, F(NxMath.NormCdf(-3)));
        Check("NormInv(0.975)=1.959964", Math.Abs(NxMath.NormInv(0.975) - 1.959964) < 1e-5, F(NxMath.NormInv(0.975)));
        Check("NormInv(0.001)=-3.090232", Math.Abs(NxMath.NormInv(0.001) + 3.090232) < 1e-5, F(NxMath.NormInv(0.001)));

        Console.WriteLine("== MacKinnon (valeurs critiques publiees)");
        Check("ADF N=1 t=-2.86 -> p~0.05", Math.Abs(NxAdf.MacKinnonP(-2.86, 1) - 0.05) < 0.003, F(NxAdf.MacKinnonP(-2.86, 1)));
        Check("ADF N=1 t=-3.43 -> p~0.01", Math.Abs(NxAdf.MacKinnonP(-3.43, 1) - 0.01) < 0.002, F(NxAdf.MacKinnonP(-3.43, 1)));
        Check("ADF N=1 t=-2.57 -> p~0.10", Math.Abs(NxAdf.MacKinnonP(-2.57, 1) - 0.10) < 0.005, F(NxAdf.MacKinnonP(-2.57, 1)));
        Check("EG N=2 t=-3.34 -> p~0.05", Math.Abs(NxAdf.MacKinnonP(-3.34, 2) - 0.05) < 0.004, F(NxAdf.MacKinnonP(-3.34, 2)));
        Check("EG N=2 t=-3.90 -> p~0.01", Math.Abs(NxAdf.MacKinnonP(-3.90, 2) - 0.01) < 0.003, F(NxAdf.MacKinnonP(-3.90, 2)));
        Check("p monotone", NxAdf.MacKinnonP(-1.0, 1) > NxAdf.MacKinnonP(-2.0, 1) && NxAdf.MacKinnonP(-2.0, 1) > NxAdf.MacKinnonP(-3.0, 1));

        Console.WriteLine("== ADF / Engle-Granger sur donnees simulees");
        Random rng = new Random(1);
        int rwReject = 0, arReject = 0, trials = 200;
        for (int k = 0; k < trials; k++)
        {
            double[] rw = new double[400], ar = new double[400];
            for (int t = 1; t < 400; t++) { rw[t] = rw[t - 1] + Gauss(rng); ar[t] = 0.7 * ar[t - 1] + Gauss(rng); }
            if (NxAdf.Test(rw).PValue < 0.05) rwReject++;
            if (NxAdf.Test(ar).PValue < 0.05) arReject++;
        }
        Check("Marche aleatoire : taux de rejet ~5 %", rwReject / (double)trials < 0.11, (rwReject / (double)trials).ToString("P1"));
        Check("AR(1) phi=0.7 : puissance ~100 %", arReject / (double)trials > 0.95, (arReject / (double)trials).ToString("P1"));
        int egCoint = 0, egIndep = 0;
        for (int k = 0; k < trials; k++)
        {
            double[] a = new double[300], b = new double[300], c = new double[300];
            double x = 0, e = 0, y = 0;
            for (int t = 0; t < 300; t++) { x += 0.01 * Gauss(rng); e = 0.8 * e + 0.005 * Gauss(rng); y += 0.01 * Gauss(rng); b[t] = 4 + x; a[t] = 0.5 + 1.2 * b[t] + e; c[t] = 4 + y; }
            double al, be; double[] res;
            if (NxAdf.EngleGranger(a, b, out al, out be, out res).PValue < 0.05) egCoint++;
            if (NxAdf.EngleGranger(a, c, out al, out be, out res).PValue < 0.05) egIndep++;
        }
        Check("EG : paire co-integree detectee", egCoint / (double)trials > 0.9, (egCoint / (double)trials).ToString("P1"));
        Check("EG N=2 : fausse co-integration ~5 %", egIndep / (double)trials < 0.11, (egIndep / (double)trials).ToString("P1"));

        Console.WriteLine("== Ornstein-Uhlenbeck");
        double[] ou = new double[3000];
        for (int t = 1; t < ou.Length; t++) ou[t] = 0.2 + 0.9 * ou[t - 1] + 0.1 * Gauss(rng);
        NxOuFit fit = NxOu.Fit(ou);
        Check("b ~ 0.9", Math.Abs(fit.B - 0.9) < 0.02, F(fit.B));
        Check("demi-vie ~ 6.58", Math.Abs(fit.HalfLife - Math.Log(2) / -Math.Log(0.9)) < 1.0, F(fit.HalfLife));
        Check("moyenne ~ 2.0", Math.Abs(fit.Mean - 2.0) < 0.15, F(fit.Mean));
        Check("sigma_eq ~ 0.229", Math.Abs(fit.SigmaEq - 0.1 / Math.Sqrt(1 - 0.81)) < 0.02, F(fit.SigmaEq));

        Console.WriteLine("== Black-Scholes");
        double S = 100, K = 95, Tt = 35 / 365.0, r = 0.04, v = 0.25;
        double c0 = NxBlackScholes.Price(true, S, K, Tt, r, v), p0 = NxBlackScholes.Price(false, S, K, Tt, r, v);
        Check("parite call-put", Math.Abs(c0 - p0 - (S - K * Math.Exp(-r * Tt))) < 1e-9, F(c0 - p0));
        double kp = NxBlackScholes.StrikeFromDelta(false, S, Tt, r, v, -0.25);
        Check("strike du delta -0.25 -> delta -0.25", Math.Abs(NxBlackScholes.Delta(false, S, kp, Tt, r, v) + 0.25) < 1e-6, "K=" + F(kp));
        double kc = NxBlackScholes.StrikeFromDelta(true, S, Tt, r, v, 0.25);
        Check("strike du delta 0.25 -> delta 0.25", Math.Abs(NxBlackScholes.Delta(true, S, kc, Tt, r, v) - 0.25) < 1e-6, "K=" + F(kc));
        Check("vol implicite inversee", Math.Abs(NxBlackScholes.ImpliedVol(false, p0, S, K, Tt, r) - v) < 1e-4);
        // Algorithme de la fiche 11 (strike arrondi puis ramene dans la bande |delta| 0.20-0.30).
        int inBand = 0, cases = 0, skipped = 0;
        foreach (double spot in new[] { 8.0, 23.0, 95.0, 180.0, 450.0, 1200.0 })
            foreach (double vol in new[] { 0.12, 0.25, 0.60 })
                foreach (int dte in new[] { 30, 38, 45 })
                    foreach (bool isCall in new[] { false, true })
                    {
                        double T2 = dte / 365.0, step = spot < 25 ? 0.5 : (spot < 200 ? 1.0 : (spot < 1000 ? 5.0 : 10.0));
                        double k = NxBlackScholes.StrikeFromDelta(isCall, spot, T2, 0.04, vol, isCall ? 0.25 : -0.25);
                        k = isCall ? Math.Ceiling(k / step) * step : Math.Floor(k / step) * step;
                        for (int g = 0; g < 8; g++)
                        {
                            double m = Math.Abs(NxBlackScholes.Delta(isCall, spot, k, T2, 0.04, vol));
                            if (m > 0.30) k += isCall ? step : -step;
                            else if (m < 0.20 && k - step > 0) k += isCall ? -step : step;
                            else break;
                        }
                        double mf = Math.Abs(NxBlackScholes.Delta(isCall, spot, k, T2, 0.04, vol));
                        cases++;
                        if (mf >= 0.20 - 1e-9 && mf <= 0.30 + 1e-9) { inBand++; continue; }
                        // Hors bande : acceptable SEULEMENT si aucun strike de la grille n est dans la bande (la strategie s abstient).
                        bool reachable = false;
                        for (double kk = step; kk < spot * 3; kk += step)
                        {
                            double mm = Math.Abs(NxBlackScholes.Delta(isCall, spot, kk, T2, 0.04, vol));
                            if (mm >= 0.20 && mm <= 0.30) { reachable = true; break; }
                        }
                        if (!reachable) { inBand++; skipped++; }
                        else Console.WriteLine("     ECHEC : bande atteignable mais manquee " + (isCall ? "call" : "put") + " S=" + spot + " vol=" + vol + " dte=" + dte);
                    }
        Check("fiche 11 : strike dans la bande |delta| 0.20-0.30, sinon abstention justifiee", inBand == cases, (inBand - skipped) + " dans la bande, " + skipped + " abstentions (grille trop grossiere) / " + cases);

        Console.WriteLine("== Kelly (module B)");
        double lo, hi;
        NxKelly.Wilson(227, 480, 1.96, out lo, out hi);
        Check("IC Wilson 480 trades p=0.472 ~ [42.7 % ; 51.7 %]", Math.Abs(lo - 0.427) < 0.004 && Math.Abs(hi - 0.517) < 0.004, lo.ToString("P1") + " ; " + hi.ToString("P1"));
        Check("b mini = 1.12 pour p=0.472", Math.Abs(NxKelly.BreakEvenPayoff(0.472) - 1.1186) < 0.001, F(NxKelly.BreakEvenPayoff(0.472)));
        Check("f* <= 0 si b = 1.1", NxKelly.Fraction(0.472, 1.1) <= 0);
        double fk = NxKelly.Fraction(0.55, 1.5), rck = NxKelly.RiskConstrained(0.55, 1.5, 0.7, 0.1);
        Check("Kelly contraint <= Kelly", rck <= fk + 1e-12 && rck > 0, "f*=" + F(fk) + " rck=" + F(rck));
        double lam = Math.Log(0.1) / Math.Log(0.7);
        Check("contrainte de drawdown saturee", Math.Abs(0.55 * Math.Pow(1 + rck * 1.5, -lam) + 0.45 * Math.Pow(1 - rck, -lam) - 1) < 1e-6 || Math.Abs(rck - fk) < 1e-12);
        NxSizingConfig cfg = new NxSizingConfig();
        NxTradeStats st = new NxTradeStats();
        NxSizingResult sr = NxSizer.Size(cfg, st, 0.05, double.NaN, 0.0, 100000, 0, 0, 0);
        Check("demi-Kelly + waiver + plafond 3 %", Math.Abs(sr.Fraction - Math.Min(0.03, 0.5 * 0.5 * NxKelly.Fraction(0.5, 1.2))) < 1e-9, sr.Detail);
        sr = NxSizer.Size(cfg, st, 0.05, double.NaN, 1.0, 100000, 0, 0.29, 0.4);
        Check("plafond classe 30 %", sr.Fraction <= 0.01 + 1e-9, sr.Detail);

        Console.WriteLine("== HMM 3 etats (module A)");
        Random hr = new Random(7);
        int n = 900; double[][] X = new double[n][]; int[] truth = new int[n];
        int stt = 0;
        double[] mus = { 0.05, 0.0, -0.1 }, sds = { 0.5, 1.0, 2.0 }, vm = { -1.0, 0.0, 1.5 };
        for (int t = 0; t < n; t++)
        {
            if (hr.NextDouble() < 0.02) stt = hr.Next(3);
            truth[t] = stt;
            X[t] = new[] { mus[stt] + sds[stt] * Gauss(hr), vm[stt] + 0.3 * Gauss(hr) };
        }
        NxGaussianHmm h = NxGaussianHmm.Fit(X, 3, 10, 200, 1e-4, 42);
        int[] ord = h.OrderByFeature(1);
        int good = 0; double[] a2 = null;
        for (int t = 0; t < n; t++)
        {
            a2 = h.ForwardStep(a2, X[t]);
            int best = 0; for (int k = 1; k < 3; k++) if (a2[k] > a2[best]) best = k;
            int lbl = Array.IndexOf(ord, best);
            if (lbl == truth[t]) good++;
        }
        Check("etats retrouves (filtre avant) > 85 %", good / (double)n > 0.85, (good / (double)n).ToString("P1"));
        Check("plafond 0.95 respecte", NxHmmRegimeDetector.CapProbabilities(new[] { 0.999, 0.0005, 0.0005 }, 0.95).Max() <= 0.95 + 1e-12);
        NxHmmRegimeDetector det = new NxHmmRegimeDetector(false) { Window = 500, MinObservations = 250 };
        double px = 100; Random dr = new Random(3);
        for (int t = 0; t < 900; t++) { double vol = t % 300 < 200 ? 0.007 : 0.025; px *= Math.Exp(vol * Gauss(dr)); det.Update(px, double.NaN); }
        Check("detecteur pret + regime stress en fin de periode agitee", det.IsReady && det.Regime == NxRegime.Stress, det.Describe());

        Console.WriteLine("== Terciles de vol (fiche 12)");
        NxVolTercileRegime vt = new NxVolTercileRegime();
        px = 100; int flips = 0, rawFlips = 0; NxRegime prev = NxRegime.Inconnu, prevRaw = NxRegime.Inconnu;
        for (int t = 0; t < 1500; t++)
        {
            double vol = (t / 150) % 2 == 0 ? 0.006 : 0.02; px *= Math.Exp(vol * Gauss(dr)); vt.Update(px);
            if (vt.Regime != prev && prev != NxRegime.Inconnu) flips++; prev = vt.Regime;
            if (vt.RawRegime != prevRaw && prevRaw != NxRegime.Inconnu) rawFlips++; prevRaw = vt.RawRegime;
        }
        Check("anti-clignotement : la confirmation 5 j retire > 40 % des franchissements bruts", flips < 0.6 * rawFlips, "confirmes=" + flips + " bruts=" + rawFlips);
        NxVolTercileRegime v2 = new NxVolTercileRegime();
        px = 100; bool sawStress = false, sawCalm = false;
        for (int t = 0; t < 1200; t++) { double vol = t < 900 ? 0.008 : 0.03; px *= Math.Exp(vol * Gauss(dr)); v2.Update(px); if (t == 890 && v2.Regime == NxRegime.Calme) sawCalm = true; if (t > 960 && v2.Regime == NxRegime.Stress) sawStress = true; }
        Check("choc de vol -> regime stress confirme", sawStress, v2.Describe());

        Console.WriteLine("== Validation (module C)");
        List<double[]> noise = new List<double[]>();
        Random pr = new Random(5);
        for (int c = 0; c < 20; c++) noise.Add(Enumerable.Range(0, 800).Select(i => 0.01 * Gauss(pr)).ToArray());
        int combos;
        double pboNoise = 0; int nsets = 40;
        for (int ds = 0; ds < nsets; ds++)
        {
            Random prr = new Random(100 + ds);
            List<double[]> nz = new List<double[]>();
            for (int c = 0; c < 20; c++) nz.Add(Enumerable.Range(0, 800).Select(i => 0.01 * Gauss(prr)).ToArray());
            pboNoise += NxValidation.Pbo(nz, 16, 500, ds, out combos) / nsets;
        }
        Check("PBO bruit pur ~ 0.5 (moyenne sur 40 jeux)", pboNoise > 0.4 && pboNoise < 0.6, F(pboNoise));
        List<double[]> withSkill = noise.Select(x => (double[])x.Clone()).ToList();
        withSkill[0] = withSkill[0].Select(x => x + 0.004).ToArray();
        double pboSkill = NxValidation.Pbo(withSkill, 16, 2000, 1, out combos);
        Check("PBO avec une vraie config ~ 0", pboSkill < 0.1, F(pboSkill));
        double sr0;
        double dsrGood = NxValidation.DeflatedSharpe(withSkill[0], 20, double.NaN, out sr0);
        double dsrBad = NxValidation.DeflatedSharpe(noise.OrderByDescending(x => NxValidation.SharpePerPeriod(x)).First(), 20, double.NaN, out sr0);
        Check("DSR : vraie competence > 95 %", dsrGood > 0.95, F(dsrGood));
        Check("DSR : meilleur de 20 bruits < 90 %", dsrBad < 0.9, F(dsrBad));
        double[] mc = NxValidation.MonteCarloMaxDD(Enumerable.Range(0, 200).Select(i => i % 3 == 0 ? -100.0 : 80.0).ToList(), 10000, 1000, 1);
        Check("Monte Carlo : 1000 tirages tries", mc.Length == 1000 && mc[0] <= mc[999]);
        double[] bb = NxValidation.BlockBootstrapMaxDD(Enumerable.Range(0, 200).Select(i => i % 3 == 0 ? -100.0 : 80.0).ToList(), 10000, 0, 1000, 1);
        Check("bootstrap par blocs", bb.Length == 1000 && bb[999] > 0);
        double dd; int bars;
        Check("cycle drawdown -> recuperation", NxValidation.HasDrawdownRecoveryCycle(new double[] { 100, 110, 95, 100, 112 }, 0.05, out dd, out bars) && Math.Abs(dd - (1 - 95 / 110.0)) < 1e-9);
        Check("pas de cycle sans recuperation", !NxValidation.HasDrawdownRecoveryCycle(new double[] { 100, 110, 95, 100, 105 }, 0.05, out dd, out bars));
        Check("walk-forward 180/30", NxValidation.WalkForwardSplits(400, 180, 30).Count == 7);
        NxCircuitBreaker cb = new NxCircuitBreaker();
        DateTime d0 = new DateTime(2026, 1, 5, 16, 0, 0);
        cb.Update(d0, d0.Date, 100000); string why;
        cb.Update(d0.AddDays(1), d0.Date.AddDays(1), 100000);
        cb.Update(d0.AddDays(1).AddHours(1), d0.Date.AddDays(1), 94000);
        Check("disjoncteur journalier -5 %", !cb.CanOpen(d0.AddDays(1).AddHours(2), out why), why ?? "");
        cb.Update(d0.AddDays(3), d0.Date.AddDays(3), 84000);
        Check("disjoncteur drawdown -15 %", !cb.CanOpen(d0.AddDays(3).AddHours(1), out why) && why.Contains("drawdown"), why ?? "");
        cb.Update(d0.AddDays(5), d0.Date.AddDays(5), 84500);
        Check("rearmement apres la pause", cb.CanOpen(d0.AddDays(5).AddHours(1), out why), why ?? "ok");

        Console.WriteLine("== JSON / prompts");
        object root = NxJson.Parse("{\"content\":[{\"type\":\"text\",\"text\":\"GOOD\\nBeat estimates \\u00e9\"}],\"usage\":{\"input_tokens\":12,\"output_tokens\":5}}");
        Check("chemin content[0].text", NxJson.Str(NxJson.At(root, "content[0].text")).StartsWith("GOOD"));
        Check("usage.output_tokens", NxJson.Num(NxJson.At(root, "usage.output_tokens")) == 5);
        Check("echappement aller-retour", NxJson.Str(NxJson.Parse(NxJson.Q("a\"b\\c\nd\u0001"))) == "a\"b\\c\nd\u0001");
        bool veto; string reason; double conf;
        Check("juge : JSON dans des balises", NxPrompts.ParseJudge("Voici :\n```json\n{\"veto\": true, \"reason\": \"SEC probe\", \"confidence\": 0.82}\n```", out veto, out reason, out conf) && veto && Math.Abs(conf - 0.82) < 1e-9);
        Check("label GOOD", NxPrompts.ParseLabel3("GOOD\nbecause") == 1);
        Check("label BAD", NxPrompts.ParseLabel3("**BAD** - lawsuit") == -1);
        Check("label NONE", NxPrompts.ParseLabel3("NONE") == 0);
        Check("label NO EFFECT -> 0", NxPrompts.ParseLabel3("No effect") == 0);
        Check("score +2", NxPrompts.ParseScore5("+2\nStrong beat") == 2);
        Check("score -1", NxPrompts.ParseScore5("-1") == -1);
        Check("score dans du texte", NxPrompts.ParseScore5("Score: 1 (mildly positive)") == 1);
        double risk; string rr;
        Check("risque", NxPrompts.ParseRisk("{\"risk\": 0.4, \"reason\": \"x\"}", out risk, out rr) && Math.Abs(risk - 0.4) < 1e-9);

        Console.WriteLine("== CSV / dates");
        DateTime dt;
        Check("ISO Z -> UTC", NxCsv.TryParseDate("2026-03-05T14:30:00Z", out dt) && dt.Kind == DateTimeKind.Utc && dt.Hour == 14);
        Check("ISO avec decalage", NxCsv.TryParseDate("2026-03-05T09:30:00-05:00", out dt) && dt.Hour == 14);
        Check("yyyyMMdd", NxCsv.TryParseDate("20260305", out dt) && dt.Day == 5 && dt.Month == 3);
        Check("yyyyMM (Ken French)", NxCsv.TryParseDate("202603", out dt) && dt.Month == 3);
        Check("unix secondes", NxCsv.TryParseDate("1696636800", out dt) && dt.Year == 2023);
        string[] q3 = NxCsv.SplitLine("a,\"b, c\",\"d \"\"e\"\"\"", ',');
        Check("CSV guillemets", q3[1] == "b, c" && q3[2] == "d \"e\"");
        Check("nombre virgule decimale", Math.Abs(NxCsv.ParseDouble("1,5") - 1.5) < 1e-12);

        Console.WriteLine("== Actualites (dedoublonnage)");
        NxNewsStore ns = new NxNewsStore();
        DateTime u = new DateTime(2026, 3, 5, 12, 0, 0, DateTimeKind.Utc);
        ns.Add(new NxNewsItem { PublishedUtc = u, Symbol = "AAPL", Source = "newsapi:Reuters", Headline = "Apple beats quarterly revenue estimates on iPhone strength" });
        bool dup = ns.Add(new NxNewsItem { PublishedUtc = u.AddHours(2), Symbol = "AAPL", Source = "newsapi:CNBC", Headline = "Apple beats quarterly revenue estimates, iPhone strength" });
        bool other = ns.Add(new NxNewsItem { PublishedUtc = u.AddHours(3), Symbol = "AAPL", Source = "newsapi:WSJ", Headline = "Apple faces new EU antitrust probe over App Store" });
        Check("meme evenement = 1 titre", !dup && other && ns.Count == 2);
        Check("fenetre ]from ; to]", ns.Get("AAPL", u, u.AddHours(5), false).Count == 1);

        Console.WriteLine("== Panel / signaux");
        NxBarHistory ha = new NxBarHistory("A"), hb = new NxBarHistory("B");
        double pa = 100, pb = 50; Random sr2 = new Random(11);
        DateTime day = new DateTime(2020, 1, 1);
        for (int t = 0; t < 400; t++)
        {
            day = day.AddDays(1); if (day.DayOfWeek == DayOfWeek.Saturday) day = day.AddDays(2);
            double m = 0.01 * Gauss(sr2); pa *= Math.Exp(m + 0.002 * Gauss(sr2)); pb *= Math.Exp(m + 0.002 * Gauss(sr2));
            ha.Add(day, day, pa, pa * 1.01, pa * 0.99, pa, 1e6); if (t % 50 != 7) hb.Add(day, day, pb, pb * 1.01, pb * 0.99, pb, 1e6);
        }
        Check("correlation alignee ~ 0.96", NxBarHistory.ReturnCorrelation(ha, hb, 120) > 0.9, F(NxBarHistory.ReturnCorrelation(ha, hb, 120)));
        Check("beta ~ 1", Math.Abs(NxResidual.Beta(ha, hb, 120) - 1) < 0.1, F(NxResidual.Beta(ha, hb, 120)));
        Check("ATR de Wilder positif", ha.Atr > 0);
        Check("12-1 calculable", NxMath.Ok(NxMomentum.Return12_1(ha)));
        Check("selection avec tampon", string.Join(",", NxRankSelection.SelectWithBuffer(new Dictionary<string, double> { { "a", 9 }, { "b", 8 }, { "c", 7 }, { "d", 6 }, { "e", 5 } }, new HashSet<string> { "d" }, 2, 4)) == "d,a");
        Check("fin de mois de bourse", NxCalendar.IsLastTradingDayOfMonth(new DateTime(2026, 7, 31), null) && !NxCalendar.IsLastTradingDayOfMonth(new DateTime(2026, 7, 30), null));
        Check("3e vendredi", NxCalendar.ThirdFriday(2026, 11) == new DateTime(2026, 11, 20));
        double bv = NxPanel.BasketVol(new List<NxBarHistory> { ha, hb }, new[] { 0.5, 0.5 }, 120);
        Check("vol de panier ~ 16 %", bv > 0.12 && bv < 0.20, F(bv));

        Console.WriteLine();
        Console.WriteLine("RESULTAT : " + pass + " OK, " + fail + " ECHEC(S)");
        Environment.Exit(fail == 0 ? 0 : 1);
    }
}
