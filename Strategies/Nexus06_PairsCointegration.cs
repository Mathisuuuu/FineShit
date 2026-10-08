// =============================================================================
//  Nexus06_PairsCointegration.cs   (NinjaTrader 8 / NinjaScript)
//
//  FICHE 6 - Pairs trading / co-integration (bloquee chez Nexus : reconstruite)
//  [Fil] livre de Chan ; Gatev, Goetzmann, Rouwenhorst ; [arXiv] 2109.10662.
//
//  REGLES (mode Actions, barres journalieres)
//   - Paires candidates uniquement a l interieur d une classe d actifs.
//   - Engle-Granger 2 etapes : log(A) = a + b log(B), puis ADF sur le residu,
//     p-value < 0.05 avec les valeurs critiques de co-integration (MacKinnon
//     N=2, plus strictes que l ADF classique ; option pour revenir a N=1).
//   - Formation 12 mois, trading 6 mois, puis nouvelle selection (les positions
//     encore ouvertes sont fermees a la fin de la periode de trading).
//   - Entree : |ecart| > 2 ecarts-types de la formation.
//   - Sortie : retour de l ecart a 0, ou 20 jours de bourse sans convergence.
//   - Stop : |ecart| > 4 ecarts-types, ou p-value > 0.10 au recalcul mensuel.
//  MODE CryptoHoraire : bougies 1 h, formation 30 jours, recalcul hebdomadaire.
//
//  PETIT COMPTE : une paire exige une jambe vendeuse (compte marge / futures).
//  Par defaut "Vente a decouvert autorisee" = faux -> version LONG SEUL : on
//  n achete que la jambe sous-evaluee (ce n est plus neutre au marche).
//  Frais crypto : 0.1 % par jambe et par ordre -> 0.4 % aller-retour par paire.
// =============================================================================

#region Using declarations
using System;
using System.Collections.Generic;
using System.ComponentModel.DataAnnotations;
using System.Globalization;
using System.Linq;
using NinjaTrader.Cbi;
using NinjaTrader.Data;
using NinjaTrader.NinjaScript;
using NinjaTrader.NinjaScript.AddOns.Nexus;
#endregion

namespace NinjaTrader.NinjaScript.Strategies
{
    public enum Nexus06Mode { ActionsJournalier, CryptoHoraire }

    public class Nexus06PairsCointegration : NexusStrategyBase
    {
        private class Pair
        {
            public NxSym A, B;
            public double Alpha, Beta, Mu, Sd, P;
            public int Pos;                 // +1 : A sous-evalue (long A / court B) ; -1 : B sous-evalue
            public int EntryBatch;
            public double EntryZ;
            public string Key { get { return A.Name + "/" + B.Name; } }
        }

        private List<Pair> pairs = new List<Pair>();
        private int barsSinceSelection = int.MaxValue / 2, barsSinceRecheck;
        private int selections, entries, exitsZero, exitsTime, exitsStop, exitsAdf, testedPairs;

        protected override void NxSetDefaults()
        {
            Name = "Nexus06_PairsCointegration";
            Description = "Fiche 6 - Paires co-integrees (Engle-Granger, MacKinnon N=2), formation 12 mois / trading 6 mois, entree 2 sigma, sortie 0 ou 20 j, stop 4 sigma ou p > 0.10. Long seul par defaut.";
            Symbols = "KO,PEP,XOM,CVX,JPM,BAC,V,MA,HD,LOW,WMT,COST,UNH,CVS,MSFT,AAPL,GOOGL,META";
            SizingMode = NxSizingMode.DemiKelly;
            AllowShortSelling = false;
            StopMode = NxStopMode.Aucun;

            Mode = Nexus06Mode.ActionsJournalier;
            PairsList = "";
            FormationBars = 0;
            TradingBars = 0;
            RecheckBars = 0;
            MaxHoldBars = 0;
            PValueMax = 0.05;
            RecheckPValueMax = 0.10;
            EntryZ = 2.0;
            ExitZ = 0.0;
            StopZ = 4.0;
            MaxPairs = 5;
            UseEgCriticalValues = true;
        }

        protected override BarsPeriodType NxUniverseBarsType { get { return Mode == Nexus06Mode.CryptoHoraire ? BarsPeriodType.Minute : BarsPeriodType.Day; } }
        protected override int NxUniverseBarsValue { get { return Mode == Nexus06Mode.CryptoHoraire ? 60 : 1; } }

        private int Formation { get { return FormationBars > 0 ? FormationBars : (Mode == Nexus06Mode.CryptoHoraire ? 30 * 24 : 252); } }
        private int Trading { get { return TradingBars > 0 ? TradingBars : (Mode == Nexus06Mode.CryptoHoraire ? 7 * 24 : 126); } }
        private int Recheck { get { return RecheckBars > 0 ? RecheckBars : (Mode == Nexus06Mode.CryptoHoraire ? 7 * 24 : 21); } }
        private int MaxHold { get { return MaxHoldBars > 0 ? MaxHoldBars : (Mode == Nexus06Mode.CryptoHoraire ? 20 * 24 : 20); } }

        /// <summary>Log-prix alignes par horodatage de barre (n derniers points communs).</summary>
        private static bool AlignedLogs(NxBarHistory a, NxBarHistory b, int n, out double[] la, out double[] lb)
        {
            la = lb = null;
            Dictionary<DateTime, int> ib = new Dictionary<DateTime, int>();
            for (int j = Math.Max(0, b.Count - n * 2); j < b.Count; j++) ib[b.Times[j]] = j;
            List<double> xa = new List<double>(), xb = new List<double>();
            for (int i = a.Count - 1; i >= 0 && xa.Count < n; i--)
            {
                int j;
                if (!ib.TryGetValue(a.Times[i], out j)) continue;
                if (a.Close[i] <= 0 || b.Close[j] <= 0) continue;
                xa.Add(Math.Log(a.Close[i])); xb.Add(Math.Log(b.Close[j]));
            }
            if (xa.Count < n * 0.8) return false;
            xa.Reverse(); xb.Reverse();
            la = xa.ToArray(); lb = xb.ToArray();
            return true;
        }

        private List<KeyValuePair<NxSym, NxSym>> Candidates()
        {
            List<KeyValuePair<NxSym, NxSym>> res = new List<KeyValuePair<NxSym, NxSym>>();
            if (!string.IsNullOrWhiteSpace(PairsList))
            {
                foreach (string p in NxText.SplitList(PairsList))
                {
                    string[] ab = p.Split('/');
                    if (ab.Length != 2) continue;
                    NxSym a = Sym(ab[0].Trim()), b = Sym(ab[1].Trim());
                    if (a != null && b != null && a.Traded && b.Traded && a.Class == b.Class) res.Add(new KeyValuePair<NxSym, NxSym>(a, b));
                    else NxOnce("pair" + p, "Paire ignoree (symbole absent ou classes differentes) : " + p);
                }
                return res;
            }
            List<NxSym> t = TradedSyms;
            for (int i = 0; i < t.Count; i++)
                for (int j = i + 1; j < t.Count; j++)
                    if (t[i].Class == t[j].Class) res.Add(new KeyValuePair<NxSym, NxSym>(t[i], t[j]));
            return res;
        }

        private bool TestPair(NxSym a, NxSym b, out Pair pair)
        {
            pair = null;
            double[] la, lb;
            if (!AlignedLogs(a.Hist, b.Hist, Formation, out la, out lb)) return false;
            double alpha, beta;
            double[] resid;
            NxAdfResult adf = NxAdf.EngleGranger(la, lb, out alpha, out beta, out resid, UseEgCriticalValues);
            if (!adf.Ok || resid == null || !(beta > 0)) return false;
            double mu = NxMath.Mean(resid), sd = NxMath.StdDev(resid);
            if (!(sd > 0)) return false;
            pair = new Pair { A = a, B = b, Alpha = alpha, Beta = beta, Mu = mu, Sd = sd, P = adf.PValue };
            return true;
        }

        private void SelectPairs(DateTime key)
        {
            foreach (Pair p in pairs) ClosePair(p, "fin de la periode de trading");
            pairs = new List<Pair>();
            List<Pair> ok = new List<Pair>();
            foreach (KeyValuePair<NxSym, NxSym> c in Candidates())
            {
                Pair p;
                testedPairs++;
                if (TestPair(c.Key, c.Value, out p) && p.P < PValueMax) ok.Add(p);
            }
            HashSet<NxSym> used = new HashSet<NxSym>();
            foreach (Pair p in ok.OrderBy(x => x.P))
            {
                if (pairs.Count >= MaxPairs) break;
                if (used.Contains(p.A) || used.Contains(p.B)) continue;   // une jambe = une seule paire
                pairs.Add(p); used.Add(p.A); used.Add(p.B);
            }
            selections++;
            barsSinceSelection = 0;
            barsSinceRecheck = 0;
            Nx(string.Format(CultureInfo.InvariantCulture, "{0:yyyy-MM-dd HH:mm} selection : {1} paires co-integrees sur {2} candidates -> {3}",
                key, ok.Count, Candidates().Count, string.Join(", ", pairs.Select(p => p.Key + " (p=" + p.P.ToString("F3", CultureInfo.InvariantCulture) + ", b=" + p.Beta.ToString("F2", CultureInfo.InvariantCulture) + ")"))));
        }

        private double ZOf(Pair p)
        {
            if (p.A.Hist.LastClose <= 0 || p.B.Hist.LastClose <= 0) return double.NaN;
            double spread = Math.Log(p.A.Hist.LastClose) - (p.Alpha + p.Beta * Math.Log(p.B.Hist.LastClose));
            return (spread - p.Mu) / p.Sd;
        }

        private void OpenPair(Pair p, double z)
        {
            NxSym longLeg = z < 0 ? p.A : p.B;
            NxSym shortLeg = z < 0 ? p.B : p.A;
            string det;
            int qLong = SizeQty(longLeg, MaxTradePct / 100.0, longLeg.LastPrice, double.NaN, out det);
            if (qLong <= 0) { NxV("Paire " + p.Key + " : jambe longue nulle (" + det + ")"); return; }
            string why = string.Format(CultureInfo.InvariantCulture, "paire {0} z={1:F2} -> long {2}", p.Key, z, longLeg.Name);
            SetTarget(longLeg, qLong, double.NaN, why);
            if (AllowShortSelling)
            {
                // Couverture en valeur : |valeur B| = beta x valeur A (regression en log-prix).
                double longValue = qLong * longLeg.LastPrice * ValuePerPoint(longLeg);
                double shortValue = shortLeg == p.B ? p.Beta * longValue : longValue / p.Beta;
                int lot = Math.Max(1, LotSize);
                int qShort = (int)Math.Floor(shortValue / (shortLeg.LastPrice * ValuePerPoint(shortLeg)) / lot) * lot;
                if (qShort > 0) SetTarget(shortLeg, -qShort, double.NaN, why + " / court " + shortLeg.Name);
            }
            p.Pos = z < 0 ? 1 : -1;
            p.EntryBatch = BatchCount;
            p.EntryZ = z;
            entries++;
            NxSignal(NowNt, p.Key, "paire_entree", why + " | " + det);
        }

        private void ClosePair(Pair p, string reason)
        {
            if (p.Pos == 0) return;
            if (p.A.Qty != 0 || p.A.TargetQty != 0) SetTarget(p.A, 0, double.NaN, reason);
            if (p.B.Qty != 0 || p.B.TargetQty != 0) SetTarget(p.B, 0, double.NaN, reason);
            NxSignal(NowNt, p.Key, "paire_sortie", reason);
            p.Pos = 0;
        }

        protected override void NxOnBatch(DateTime key)
        {
            barsSinceSelection++;
            barsSinceRecheck++;
            List<NxSym> traded = TradedSyms;
            if (traded.Count(s => s.Hist.Count >= Formation) < 2) return;   // chauffage (les symboles trop jeunes sont ecartes au test)

            if (barsSinceSelection >= Trading) { SelectPairs(key); return; }

            if (barsSinceRecheck >= Recheck)
            {
                barsSinceRecheck = 0;
                foreach (Pair p in pairs.ToList())
                {
                    Pair fresh;
                    double pv = TestPair(p.A, p.B, out fresh) ? fresh.P : 1.0;
                    if (pv > RecheckPValueMax)
                    {
                        if (p.Pos != 0) exitsAdf++;
                        ClosePair(p, string.Format(CultureInfo.InvariantCulture, "co-integration perdue (p={0:F3} > {1:F2})", pv, RecheckPValueMax));
                        pairs.Remove(p);
                        Nx("Paire abandonnee " + p.Key + " (p=" + pv.ToString("F3", CultureInfo.InvariantCulture) + ")");
                    }
                }
            }

            foreach (Pair p in pairs)
            {
                double z = ZOf(p);
                if (!NxMath.Ok(z)) continue;
                if (p.Pos == 0)
                {
                    if (Math.Abs(z) > EntryZ && Math.Abs(z) < StopZ) OpenPair(p, z);
                    continue;
                }
                int held = BatchCount - p.EntryBatch;
                if (Math.Abs(z) > StopZ) { exitsStop++; ClosePair(p, string.Format(CultureInfo.InvariantCulture, "stop : |z|={0:F2} > {1:F1}", Math.Abs(z), StopZ)); }
                else if ((p.Pos > 0 && z >= -ExitZ) || (p.Pos < 0 && z <= ExitZ)) { exitsZero++; ClosePair(p, string.Format(CultureInfo.InvariantCulture, "convergence z={0:F2}", z)); }
                else if (held >= MaxHold) { exitsTime++; ClosePair(p, held + " barres sans convergence"); }
            }
        }

        protected override void NxReportExtras(List<string> lines)
        {
            lines.Add(string.Format(CultureInfo.InvariantCulture, "Mode {0} | formation {1} / trading {2} / recalcul {3} barres | vente a decouvert : {4}",
                Mode, Formation, Trading, Recheck, AllowShortSelling ? "oui (neutre au marche)" : "NON (long seul, pas neutre au marche)"));
            lines.Add(string.Format(CultureInfo.InvariantCulture, "Selections : {0} | paires testees : {1} | entrees : {2} | sorties : convergence {3}, temps {4}, stop 4 sigma {5}, p>0.10 {6}",
                selections, testedPairs, entries, exitsZero, exitsTime, exitsStop, exitsAdf));
            lines.Add("Paires actives : " + (pairs.Count == 0 ? "(aucune)" : string.Join(", ", pairs.Select(p => p.Key + (p.Pos != 0 ? " [en position]" : "")))));
            if (ClosedTrades.Count < 30) lines.Add("Moins de 30 trades : aucune conclusion statistique possible (cf. 20 trades seulement du commentateur page 10).");
        }

        #region Proprietes
        [NinjaScriptProperty]
        [Display(Name = "Mode", Order = 1, GroupName = "01. Fiche 6 - Paires")]
        public Nexus06Mode Mode { get; set; }

        [Display(Name = "Paires imposees (A/B, ...)", Description = "Vide = toutes les combinaisons a l interieur d une classe d actifs.", Order = 2, GroupName = "01. Fiche 6 - Paires")]
        public string PairsList { get; set; }

        [NinjaScriptProperty]
        [Range(0, 100000)]
        [Display(Name = "Formation (barres, 0 = auto)", Description = "Auto : 252 jours (actions) / 720 h (crypto).", Order = 3, GroupName = "01. Fiche 6 - Paires")]
        public int FormationBars { get; set; }

        [NinjaScriptProperty]
        [Range(0, 100000)]
        [Display(Name = "Trading (barres, 0 = auto)", Description = "Auto : 126 jours / 168 h.", Order = 4, GroupName = "01. Fiche 6 - Paires")]
        public int TradingBars { get; set; }

        [Range(0, 100000)]
        [Display(Name = "Recalcul ADF (barres, 0 = auto)", Description = "Auto : 21 jours / 168 h.", Order = 5, GroupName = "01. Fiche 6 - Paires")]
        public int RecheckBars { get; set; }

        [Range(0, 100000)]
        [Display(Name = "Detention max (barres, 0 = auto)", Description = "Auto : 20 jours / 480 h.", Order = 6, GroupName = "01. Fiche 6 - Paires")]
        public int MaxHoldBars { get; set; }

        [NinjaScriptProperty]
        [Range(0.001, 0.5)]
        [Display(Name = "p-value max (selection)", Order = 7, GroupName = "01. Fiche 6 - Paires")]
        public double PValueMax { get; set; }

        [Range(0.001, 1.0)]
        [Display(Name = "p-value max (recalcul)", Order = 8, GroupName = "01. Fiche 6 - Paires")]
        public double RecheckPValueMax { get; set; }

        [NinjaScriptProperty]
        [Range(0.5, 10.0)]
        [Display(Name = "Entree : |z| >", Order = 9, GroupName = "01. Fiche 6 - Paires")]
        public double EntryZ { get; set; }

        [Range(-5.0, 5.0)]
        [Display(Name = "Sortie : retour a z", Order = 10, GroupName = "01. Fiche 6 - Paires")]
        public double ExitZ { get; set; }

        [NinjaScriptProperty]
        [Range(1.0, 20.0)]
        [Display(Name = "Stop : |z| >", Order = 11, GroupName = "01. Fiche 6 - Paires")]
        public double StopZ { get; set; }

        [Range(1, 100)]
        [Display(Name = "Paires actives max", Order = 12, GroupName = "01. Fiche 6 - Paires")]
        public int MaxPairs { get; set; }

        [Display(Name = "Valeurs critiques Engle-Granger (N=2)", Description = "Faux = ADF classique (N=1), trop permissif pour un residu estime.", Order = 13, GroupName = "01. Fiche 6 - Paires")]
        public bool UseEgCriticalValues { get; set; }
        #endregion
    }
}
