// =============================================================================
//  Nexus05_VolatilityMeanReversion.cs   (NinjaTrader 8 / NinjaScript)
//
//  FICHE 5 - Retour a la moyenne de la volatilite (portefeuilles geres par la vol)
//  Moreira, Muir (Volatility Managed Portfolios) : la variance se prevoit bien,
//  les rendements mal -> reduire l exposition quand la vol est haute ameliore
//  le Sharpe. Sortir pendant le pic, revenir progressivement quand il s estompe.
//
//  REGLES
//   1. Chaque jour : variance realisee du mois ecoule (21 rendements quotidiens)
//      et ratio vol 5 j / vol 60 j.
//   2. Exposition cible w = c / variance, plafonnee a 1 (pas de levier).
//      c calibre pour que la vol moyenne du portefeuille gere egale celle du
//      buy-and-hold. ICI c est estime en GLISSANT sur les jours passes (3 ans)
//      au lieu de l echantillon complet (qui utiliserait le futur).
//   3. Pic (ratio > 1.8) : couper immediatement l exposition a w.
//   4. Retour (ratio < 1.2 ET vol 5 j en baisse 3 jours de suite) : remonter par
//      paliers de 25 % de w par semaine jusqu a w.
//   5. Ne jamais ajouter d exposition pendant que la vol courte monte encore.
//   Reequilibrage hebdomadaire ou au franchissement d un seuil d ecart. Aucun stop
//   prix : la taille gere le risque.
//
//  ALLOCATION : w = 1 correspond a "Allocation max par actif" du bankroll
//  (10 % par defaut = plafond par symbole du module B). Mode par symbole :
//  chaque actif garde son propre calendrier (SPY/QQQ en semaine, BTC/ETH 7j/7).
//  NE PAS appliquer cette logique en plus de la mise a l echelle des fiches 1-2
//  sur le meme actif (le registre inter-strategies l interdit en temps reel).
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
    public enum Nexus05Etat { Normal, Pic, Retour }

    public class Nexus05VolatilityMeanReversion : NexusStrategyBase
    {
        private class VolState
        {
            public Nexus05Etat Etat = Nexus05Etat.Normal;
            public readonly List<double> Vol5 = new List<double>();
            public int LastWeekKey = int.MinValue;
            public double Exposure;           // fraction de l allocation actuellement visee (0..1)
            public double LastW = double.NaN;
            public double LastC = double.NaN;
            public int Spikes, Recoveries;
            public readonly List<double> SqPrefix = new List<double>();   // SqPrefix[i] = somme des r_k^2, k <= i
        }

        private readonly Dictionary<string, VolState> states = new Dictionary<string, VolState>(StringComparer.OrdinalIgnoreCase);

        protected override void NxSetDefaults()
        {
            Name = "Nexus05_VolatilityMeanReversion";
            Description = "Fiche 5 - Exposition w = c/variance (Moreira-Muir, c glissant), coupure au pic de vol (5j/60j > 1.8), retour par paliers de 25 %/semaine, jamais d ajout quand la vol courte monte.";
            Symbols = "SPY,QQQ,BTCUSD,ETHUSD";
            SizingMode = NxSizingMode.Natif;
            MaxTradePct = 10.0;
            MaxSymbolPct = 10.0;
            StopMode = NxStopMode.Aucun;

            VarianceWindowDays = 21;
            CalibrationDays = 756;
            MinCalibrationDays = 252;
            MaxWeight = 1.0;
            AllocationPerAssetPct = 10.0;
            ShortVolDays = 5;
            LongVolDays = 60;
            SpikeRatio = 1.8;
            CalmRatio = 1.2;
            DeclineDays = 3;
            RecoveryStepPct = 25.0;
            RebalanceThresholdPct = 20.0;
        }

        protected override bool NxBatchMode { get { return false; } }

        private VolState St(NxSym s)
        {
            VolState v;
            if (!states.TryGetValue(s.Name, out v)) { v = new VolState(); states[s.Name] = v; }
            return v;
        }

        /// <summary>c glissant : sigma(r) / sigma(r_t / RV_{t-1}) sur la fenetre de calibration (aucune donnee future).</summary>
        private double CalibrateC(NxBarHistory h, VolState v)
        {
            int n = h.Count;
            for (int i = v.SqPrefix.Count; i < n; i++)
            {
                double x = h.LogReturnAt(i);
                double prev = i > 0 ? v.SqPrefix[i - 1] : 0.0;
                v.SqPrefix.Add(prev + (NxMath.Ok(x) ? x * x : 0.0));
            }
            int start = Math.Max(VarianceWindowDays + 2, n - CalibrationDays);
            if (n - start < MinCalibrationDays) return double.NaN;
            List<double> raw = new List<double>(), managed = new List<double>();
            for (int i = start; i < n; i++)
            {
                double r = h.LogReturnAt(i);
                double rv = v.SqPrefix[i - 1] - v.SqPrefix[i - 1 - VarianceWindowDays];   // r_{i-21} .. r_{i-1}
                if (!NxMath.Ok(r) || rv <= 0) continue;
                raw.Add(r);
                managed.Add(r / rv);
            }
            double sr = NxMath.StdDev(raw), sm = NxMath.StdDev(managed);
            return (NxMath.Ok(sr) && NxMath.Ok(sm) && sm > 0) ? sr / sm : double.NaN;
        }

        protected override void NxOnSymbolBar(NxSym s, DateTime day)
        {
            if (!s.Traded) return;
            NxBarHistory h = s.Hist;
            if (h.Count < Math.Max(LongVolDays, VarianceWindowDays) + 3) return;
            VolState v = St(s);

            double rv = h.RealizedVariance(VarianceWindowDays);
            double c = CalibrateC(h, v);
            if (!NxMath.Ok(c) || !(rv > 0)) return;
            double w = Math.Min(MaxWeight, c / rv);
            v.LastW = w; v.LastC = c;

            List<double> rets = h.Returns(LongVolDays);
            double vol5 = NxMath.StdLast(rets, ShortVolDays), vol60 = NxMath.StdDev(rets);
            double ratio = (NxMath.Ok(vol5) && NxMath.Ok(vol60) && vol60 > 0) ? vol5 / vol60 : double.NaN;
            bool vol5Rising = v.Vol5.Count > 0 && vol5 > v.Vol5[v.Vol5.Count - 1];
            v.Vol5.Add(vol5);
            if (v.Vol5.Count > 30) v.Vol5.RemoveAt(0);
            bool declining = v.Vol5.Count > DeclineDays;
            for (int k = 0; declining && k < DeclineDays; k++)
                declining = v.Vol5[v.Vol5.Count - 1 - k] < v.Vol5[v.Vol5.Count - 2 - k];

            // Exposition actuelle (fraction de l allocation) d apres la position cible.
            double alloc = AllocationPerAssetPct / 100.0 * Math.Max(1.0, Bankroll());
            double unitValue = s.LastPrice * ValuePerPoint(s);
            double cur = alloc > 0 && unitValue > 0 ? s.TargetQty * unitValue / alloc : 0.0;

            int wk = (int)((NxCalendar.WeekStart(day) - new DateTime(2000, 1, 3)).TotalDays / 7);
            bool weekEnd = NxCalendar.IsLastTradingDayOfWeek(day, s.Holidays, s.SevenDays) || (v.LastWeekKey != int.MinValue && wk > v.LastWeekKey + 1);
            double target = cur;
            string why = null;

            if (NxMath.Ok(ratio) && ratio > SpikeRatio)
            {
                if (v.Etat != Nexus05Etat.Pic) { v.Etat = Nexus05Etat.Pic; v.Spikes++; Nx(string.Format(CultureInfo.InvariantCulture, "{0} {1:yyyy-MM-dd} PIC de volatilite (ratio 5j/60j {2:F2})", s.Name, day, ratio)); }
                if (cur > w) { target = w; why = string.Format(CultureInfo.InvariantCulture, "pic de vol (ratio {0:F2}) -> exposition a w={1:F2}", ratio, w); }
            }
            else if (v.Etat == Nexus05Etat.Pic)
            {
                if (cur > w) { target = w; why = "pic en cours -> exposition a w"; }
                if (NxMath.Ok(ratio) && ratio < CalmRatio && declining)
                {
                    v.Etat = Nexus05Etat.Retour; v.Recoveries++;
                    Nx(string.Format(CultureInfo.InvariantCulture, "{0} {1:yyyy-MM-dd} debut du retour (ratio {2:F2}, vol 5j en baisse {3} jours)", s.Name, day, ratio, DeclineDays));
                }
            }
            else if (v.Etat == Nexus05Etat.Retour)
            {
                if (weekEnd)
                {
                    target = Math.Min(w, cur + RecoveryStepPct / 100.0 * w);
                    why = string.Format(CultureInfo.InvariantCulture, "retour par palier de {0:F0} % (w={1:F2})", RecoveryStepPct, w);
                }
                if (cur > w) { target = w; why = "retour : exposition ramenee a w"; }
                if (target >= w - 1e-9) v.Etat = Nexus05Etat.Normal;
            }
            else
            {
                bool drift = cur > 0 && Math.Abs(cur - w) > RebalanceThresholdPct / 100.0 * Math.Max(w, 1e-6);
                if (weekEnd || drift || cur == 0)
                {
                    target = w;
                    why = string.Format(CultureInfo.InvariantCulture, "reequilibrage {0} w=c/var={1:F2} (c={2:G4})", weekEnd ? "hebdomadaire" : "au seuil", w, c);
                }
            }
            if (weekEnd) v.LastWeekKey = wk;

            // Regle 5 : jamais d ajout pendant que la vol courte monte.
            if (target > cur && vol5Rising) { target = cur; why = null; }
            v.Exposure = target;
            if (why == null || Math.Abs(target - cur) < 1e-6) return;

            string det;
            int q = target <= 0 ? 0 : SizeQty(s, target * AllocationPerAssetPct / 100.0, s.LastPrice, double.NaN, out det);
            if (target > 0 && q == 0) NxOnce("q0" + s.Name, s.Name + " : quantite nulle (" + "capital ou plafonds) - augmenter le capital ou l allocation.");
            SetTarget(s, q, double.NaN, why);
            NxSignal(NowNt, s.Name, "vol_" + v.Etat, why);
        }

        protected override void NxReportExtras(List<string> lines)
        {
            foreach (KeyValuePair<string, VolState> kv in states)
                lines.Add(string.Format(CultureInfo.InvariantCulture, "{0,-10} etat {1,-7} w={2:F2} c={3:G4} expo={4:F2} pics={5} retours={6}",
                    kv.Key, kv.Value.Etat, kv.Value.LastW, kv.Value.LastC, kv.Value.Exposure, kv.Value.Spikes, kv.Value.Recoveries));
            lines.Add("Rappel : c'est l'inverse de 'acheter la panique' ; sur crypto la vol est 3-4x celle des actions, w y est mecaniquement petit.");
        }

        #region Proprietes
        [NinjaScriptProperty]
        [Range(5, 252)]
        [Display(Name = "Variance realisee sur (jours)", Order = 1, GroupName = "01. Fiche 5 - Vol mean reversion")]
        public int VarianceWindowDays { get; set; }

        [Range(100, 5000)]
        [Display(Name = "Calibration de c sur (jours)", Order = 2, GroupName = "01. Fiche 5 - Vol mean reversion")]
        public int CalibrationDays { get; set; }

        [Range(60, 5000)]
        [Display(Name = "Calibration minimale (jours)", Order = 3, GroupName = "01. Fiche 5 - Vol mean reversion")]
        public int MinCalibrationDays { get; set; }

        [Range(0.05, 1.0)]
        [Display(Name = "Plafond de levier w", Order = 4, GroupName = "01. Fiche 5 - Vol mean reversion")]
        public double MaxWeight { get; set; }

        [Range(0.1, 1000.0)]
        [Display(Name = "Allocation max par actif (%)", Description = "Exposition pour w = 1.", Order = 5, GroupName = "01. Fiche 5 - Vol mean reversion")]
        public double AllocationPerAssetPct { get; set; }

        [Range(2, 60)]
        [Display(Name = "Vol courte (jours)", Order = 6, GroupName = "01. Fiche 5 - Vol mean reversion")]
        public int ShortVolDays { get; set; }

        [Range(10, 500)]
        [Display(Name = "Vol longue (jours)", Order = 7, GroupName = "01. Fiche 5 - Vol mean reversion")]
        public int LongVolDays { get; set; }

        [NinjaScriptProperty]
        [Range(1.0, 10.0)]
        [Display(Name = "Seuil de pic (ratio)", Order = 8, GroupName = "01. Fiche 5 - Vol mean reversion")]
        public double SpikeRatio { get; set; }

        [NinjaScriptProperty]
        [Range(0.1, 5.0)]
        [Display(Name = "Seuil de retour (ratio)", Order = 9, GroupName = "01. Fiche 5 - Vol mean reversion")]
        public double CalmRatio { get; set; }

        [Range(1, 20)]
        [Display(Name = "Baisse de la vol courte (jours)", Order = 10, GroupName = "01. Fiche 5 - Vol mean reversion")]
        public int DeclineDays { get; set; }

        [NinjaScriptProperty]
        [Range(1.0, 100.0)]
        [Display(Name = "Palier de retour (% de w / semaine)", Order = 11, GroupName = "01. Fiche 5 - Vol mean reversion")]
        public double RecoveryStepPct { get; set; }

        [Range(1.0, 100.0)]
        [Display(Name = "Seuil de reequilibrage (% d ecart)", Order = 12, GroupName = "01. Fiche 5 - Vol mean reversion")]
        public double RebalanceThresholdPct { get; set; }
        #endregion
    }
}
