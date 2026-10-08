// =============================================================================
//  Nexus04B_CryptoIntradayReversal.cs   (NinjaTrader 8 / NinjaScript)
//
//  FICHE 4 - VARIANTE B : retournement intraday crypto (15 min a 1 h)
//  [arXiv] 2608.21888 (Kitron, Wengrowicz 2026).
//
//  FAIT CLE : retour a la moyenne significatif sur ~90 % des paires Binance a
//  15 min, mais avantage brut ~0.013 %/trade contre 0.2 % de frais aller-retour.
//  REGLE DE SURVIE : perdante seule aux frais standard -> mode "FiltreSeulement"
//  recommande (filtre de timing des strategies momentum, cf. registre de chocs).
//
//  REGLES
//   - Barre 15 minutes ; z = rendement de la derniere barre / ecart-type des
//     96 barres precedentes (24 h).
//   - Condition de flux : volume "taker" vendeur > 60 % sur la barre de choc.
//     Classement des transactions par la regle du tick (Lee-Ready) sur une
//     serie 1-tick : hausse = acheteur agressif, baisse = vendeur agressif,
//     prix inchange = meme sens que la transaction precedente.
//   - Entree long : z < -2 ET flux vendeur > 60 %. Ordre LIMITE (maker) au prix
//     de cloture de la barre de choc (capte la remuneration de liquidite) ou
//     au marche (pire cas, celui de Nexus).
//   - Sortie : retour au milieu de la barre de choc (limite) ou apres 4 barres.
//   - Couts : 0.1 %/ordre (0.075 % avec BNB) modelises par le module C.
//   - Mode FiltreSeulement : aucun ordre ; chaque choc est publie dans le
//     registre partage pendant 1 h ; les autres strategies (option "Filtre de
//     choc taker") differeront leurs entrees et entreront a cours limite.
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
    public enum Nexus04BMode { Strategie, FiltreSeulement }
    public enum Nexus04BTaker { RegleDuTick, Desactive }
    public enum Nexus04BEntry { LimiteMaker, Marche }

    public class Nexus04BCryptoIntradayReversal : NexusStrategyBase
    {
        private class TakerState
        {
            public double LastPrice = double.NaN;
            public int LastSign;
            public readonly Dictionary<DateTime, double[]> Buckets = new Dictionary<DateTime, double[]>();
            public DateTime LastPurge = DateTime.MinValue;
        }

        private class ShockInfo { public double Mid = double.NaN; public DateTime Time; }

        private readonly Dictionary<int, string> tickBipToSymbol = new Dictionary<int, string>();
        private readonly Dictionary<string, TakerState> taker = new Dictionary<string, TakerState>(StringComparer.OrdinalIgnoreCase);
        private readonly Dictionary<string, ShockInfo> shocks = new Dictionary<string, ShockInfo>(StringComparer.OrdinalIgnoreCase);
        private int shockCount, zOnlyCount, entriesSubmitted, midExits, timeExits;

        protected override void NxSetDefaults()
        {
            Name = "Nexus04B_CryptoIntradayReversal";
            Description = "Fiche 4B - Retournement crypto 15 min : z < -2 et flux taker vendeur > 60 %, entree limite maker, sortie au milieu de la barre de choc ou apres 4 barres. Mode filtre recommande.";
            Symbols = "BTCUSD,ETHUSD,SOLUSD,XRPUSD,ADAUSD,DOGEUSD,AVAXUSD,LINKUSD,DOTUSD,LTCUSD,BCHUSD,UNIUSD,XLMUSD,ATOMUSD,ETCUSD,FILUSD,AAVEUSD,ALGOUSD,NEARUSD,SHIBUSD";
            SizingMode = NxSizingMode.DemiKelly;
            MaxClassPct = 30.0;
            StopMode = NxStopMode.Logiciel;

            Mode = Nexus04BMode.FiltreSeulement;
            BarMinutes = 15;
            ZWindowBars = 96;
            ZEntry = 2.0;
            TakerSource = Nexus04BTaker.RegleDuTick;
            TakerSellThresholdPct = 60.0;
            EntryType = Nexus04BEntry.LimiteMaker;
            HoldBars = 4;
            ExitAtShockMid = true;
            ShockPublishMinutes = 60;
            UseAtrStop = false;
            AtrMultiplier = 3.0;
        }

        protected override bool NxBatchMode { get { return false; } }
        protected override BarsPeriodType NxUniverseBarsType { get { return BarsPeriodType.Minute; } }
        protected override int NxUniverseBarsValue { get { return Math.Max(1, BarMinutes); } }

        protected override void NxConfigure()
        {
            if (TakerSource != Nexus04BTaker.RegleDuTick) return;
            foreach (string sym in NxText.SplitList(Symbols))
            {
                int bip;
                if (NxAddSeries(sym, BarsPeriodType.Tick, 1, out bip)) tickBipToSymbol[bip] = sym;
            }
        }

        private DateTime BucketEnd(DateTime t)
        {
            long span = TimeSpan.FromMinutes(Math.Max(1, BarMinutes)).Ticks;
            long start = t.Ticks / span * span;   // un tick pile sur la frontiere appartient a la barre suivante
            return new DateTime(start + span);
        }

        protected override void NxOnExtraBar(int bip)
        {
            string sym;
            if (!tickBipToSymbol.TryGetValue(bip, out sym)) return;
            TakerState st;
            if (!taker.TryGetValue(sym, out st)) { st = new TakerState(); taker[sym] = st; }
            double px = Closes[bip][0];
            double vol = Volumes[bip][0];
            DateTime t = Times[bip][0];
            int sign = !NxMath.Ok(st.LastPrice) ? 0 : (px > st.LastPrice ? 1 : (px < st.LastPrice ? -1 : st.LastSign));
            st.LastPrice = px;
            if (sign != 0) st.LastSign = sign;
            if (sign == 0 || !(vol > 0)) return;
            DateTime key = BucketEnd(t);
            double[] b;
            if (!st.Buckets.TryGetValue(key, out b)) { b = new double[2]; st.Buckets[key] = b; }
            if (sign > 0) b[0] += vol; else b[1] += vol;
            if ((t - st.LastPurge).TotalHours >= 6)
            {
                st.LastPurge = t;
                foreach (DateTime k in st.Buckets.Keys.Where(k => k < t.AddDays(-2)).ToList()) st.Buckets.Remove(k);
            }
        }

        /// <summary>Part du volume taker vendeur sur la barre se terminant a barEnd (NaN si inconnue).</summary>
        private double SellShare(string sym, DateTime barEnd)
        {
            TakerState st;
            double[] b;
            if (!taker.TryGetValue(sym, out st) || !st.Buckets.TryGetValue(barEnd, out b)) return double.NaN;
            double tot = b[0] + b[1];
            return tot > 0 ? b[1] / tot : double.NaN;
        }

        protected override void NxOnSymbolBar(NxSym s, DateTime day)
        {
            if (!s.Traded) return;
            NxBarHistory h = s.Hist;
            int n = h.Count;

            // --- Gestion de la position ouverte : 4 barres max, ou retour au milieu de la barre de choc.
            if (s.Qty > 0)
            {
                ShockInfo si;
                shocks.TryGetValue(s.Name, out si);
                if (s.BarsHeld >= HoldBars)
                {
                    SetTarget(s, 0, double.NaN, HoldBars + " barres ecoulees");
                    timeExits++;
                    return;
                }
                if (ExitAtShockMid && si != null && NxMath.Ok(si.Mid) && s.TargetQty != 0)
                {
                    SetTarget(s, 0, s.StopPrice, "retour au milieu de la barre de choc", OrderType.Limit, si.Mid, Math.Max(1, HoldBars - s.BarsHeld));
                    midExits++;
                }
                return;
            }
            if (n < ZWindowBars + 2) return;

            // --- Detection du choc.
            double r = h.LogReturnAt(n - 1);
            List<double> prev = new List<double>(ZWindowBars);
            for (int i = n - 1 - ZWindowBars; i < n - 1; i++) prev.Add(h.LogReturnAt(i));
            double sd = NxMath.StdDev(prev);
            if (!NxMath.Ok(r) || !NxMath.Ok(sd) || sd <= 0) return;
            double z = r / sd;
            if (z >= -ZEntry) return;
            zOnlyCount++;
            DateTime barEnd = h.LastTime;
            double share = SellShare(s.Name, barEnd);
            bool flowOk = TakerSource == Nexus04BTaker.Desactive || (NxMath.Ok(share) && share > TakerSellThresholdPct / 100.0);
            if (!flowOk) return;

            shockCount++;
            double mid = 0.5 * (h.High[n - 1] + h.Low[n - 1]);
            shocks[s.Name] = new ShockInfo { Mid = mid, Time = barEnd };
            string why = string.Format(CultureInfo.InvariantCulture, "choc z={0:F2} flux vendeur {1:P0} milieu {2}", z, share, mid);
            NxSignal(NowNt, s.Name, "choc_taker", why);
            if (IsRt) NxShockRegistry.Mark(s.Name, DateTime.UtcNow.AddMinutes(ShockPublishMinutes), mid, -1);
            if (Mode == Nexus04BMode.FiltreSeulement || s.TargetQty != 0) return;

            string det;
            int q = SizeQty(s, MaxTradePct / 100.0, s.LastPrice, double.NaN, out det);
            double stop = UseAtrStop ? NxAtrStop.LongStop(s.LastPrice, h.Atr, AtrMultiplier, 0.002, 0.20) : double.NaN;
            if (EntryType == Nexus04BEntry.LimiteMaker) SetTarget(s, q, stop, why, OrderType.Limit, s.LastPrice, 1);
            else SetTarget(s, q, stop, why);
            if (q > 0) entriesSubmitted++;
        }

        protected override void NxReportExtras(List<string> lines)
        {
            lines.Add("Mode : " + Mode + " | flux taker : " + TakerSource + " | entree : " + EntryType);
            lines.Add(string.Format(CultureInfo.InvariantCulture, "Barres z < -{0} : {1} | chocs avec flux vendeur > {2}% : {3} | entrees soumises : {4} | trades fermes : {5}",
                ZEntry, zOnlyCount, TakerSellThresholdPct, shockCount, entriesSubmitted, ClosedTrades.Count));
            if (entriesSubmitted > 0)
                lines.Add(string.Format(CultureInfo.InvariantCulture, "Taux de remplissage des entrees : {0:P0} (limites maker)", (double)ClosedTrades.Count / entriesSubmitted));
            if (ClosedTrades.Count > 0)
            {
                double g = ClosedTrades.Average(t => t.GrossReturn), net = ClosedTrades.Average(t => t.NetReturn);
                lines.Add(string.Format(CultureInfo.InvariantCulture, "Avantage brut moyen {0:P3}/trade, net {1:P3}/trade, cout aller-retour modelise {2:P3}",
                    g, net, 2 * (Costs.SlippagePct + Costs.FeePct(NxAssetClass.Crypto)) / 100.0));
                lines.Add(g < 2 * (Costs.SlippagePct + Costs.FeePct(NxAssetClass.Crypto)) / 100.0
                    ? "REGLE DE SURVIE : l avantage brut ne couvre pas les frais -> utiliser le mode FiltreSeulement."
                    : "L avantage brut couvre les frais modelises sur cet echantillon (verifier la significativite).");
            }
            lines.Add(string.Format(CultureInfo.InvariantCulture, "Sorties : au milieu de la barre de choc {0} ordres, au temps {1}", midExits, timeExits));
        }

        #region Proprietes
        [NinjaScriptProperty]
        [Display(Name = "Mode", Description = "FiltreSeulement recommande par la fiche (aucun ordre, publication des chocs).", Order = 1, GroupName = "01. Fiche 4B - Crypto intraday")]
        public Nexus04BMode Mode { get; set; }

        [Range(1, 240)]
        [Display(Name = "Barre (minutes)", Order = 2, GroupName = "01. Fiche 4B - Crypto intraday")]
        public int BarMinutes { get; set; }

        [NinjaScriptProperty]
        [Range(10, 2000)]
        [Display(Name = "Fenetre du z-score (barres)", Description = "96 barres de 15 min = 24 h.", Order = 3, GroupName = "01. Fiche 4B - Crypto intraday")]
        public int ZWindowBars { get; set; }

        [NinjaScriptProperty]
        [Range(0.5, 10.0)]
        [Display(Name = "Seuil |z| d entree", Order = 4, GroupName = "01. Fiche 4B - Crypto intraday")]
        public double ZEntry { get; set; }

        [Display(Name = "Source du flux taker", Description = "RegleDuTick ajoute une serie 1-tick par symbole.", Order = 5, GroupName = "01. Fiche 4B - Crypto intraday")]
        public Nexus04BTaker TakerSource { get; set; }

        [NinjaScriptProperty]
        [Range(50.0, 100.0)]
        [Display(Name = "Flux vendeur min (%)", Order = 6, GroupName = "01. Fiche 4B - Crypto intraday")]
        public double TakerSellThresholdPct { get; set; }

        [Display(Name = "Type d entree", Order = 7, GroupName = "01. Fiche 4B - Crypto intraday")]
        public Nexus04BEntry EntryType { get; set; }

        [NinjaScriptProperty]
        [Range(1, 100)]
        [Display(Name = "Detention max (barres)", Order = 8, GroupName = "01. Fiche 4B - Crypto intraday")]
        public int HoldBars { get; set; }

        [Display(Name = "Sortie au milieu de la barre de choc", Order = 9, GroupName = "01. Fiche 4B - Crypto intraday")]
        public bool ExitAtShockMid { get; set; }

        [Range(1, 1440)]
        [Display(Name = "Publication du choc (minutes)", Order = 10, GroupName = "01. Fiche 4B - Crypto intraday")]
        public int ShockPublishMinutes { get; set; }

        [Display(Name = "Stop ATR (optionnel)", Order = 11, GroupName = "01. Fiche 4B - Crypto intraday")]
        public bool UseAtrStop { get; set; }

        [Range(0.5, 20.0)]
        [Display(Name = "Stop : multiplicateur ATR", Order = 12, GroupName = "01. Fiche 4B - Crypto intraday")]
        public double AtrMultiplier { get; set; }
        #endregion
    }
}
