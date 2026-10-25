// =============================================================================
//  NexusGroupeM2.cs   (NinjaTrader 8 / NinjaScript)
//
//  M2 : momentum 5 min de 9:30 avec le filtre M2 (strategie d un membre du
//  serveur Kairos, essai 440 de la recherche, regle K5 de
//  Python/nexus/perso/kairos_publiees.py). Logique : AddOns\NexusGroupeLogique.cs
//  (NxM2Logique), identique ordre par ordre a la recherche
//  (python -m nexus.live.parite_ninjascript).
//
//  ECRITE LE 2026-10-25, PAS DEPLOYEE : M2 passe les criteres 10-18 mais ses
//  seuils ont ete choisis par son auteur sur notre periode ; a confirmer hors
//  echantillon (forward en demo ou NQ 2010-2012) avant tout usage. Elle tient
//  NQ aux memes heures que S1 : jamais dans le meme compte que S1, et chez
//  Topstep jamais dans un autre compte du meme utilisateur non plus (S1 et M2
//  se retrouvent en sens contraire ~17 fois par an : couverture interdite).
//
//  Activer sur MNQ <echeance courante> (compte de demo) : la strategie charge
//  NQ de la meme echeance pour les barres 5 minutes (EMA 12, ATR 14). Decision
//  a la cloture de la minute 9:34-9:35 (New York) : sens de la barre 5 min de
//  9:30 par rapport a l EMA(12), trade seulement si |cloture - EMA| > 2,2 ATR
//  ou si la veille (9:35 -> 15:55) a perdu plus de 60 pb dans le sens du jour ;
//  sortie a 15:55. Pas de trade les demi-seances.
// =============================================================================

#region Using declarations
using System;
using System.ComponentModel.DataAnnotations;
using System.Globalization;
using NinjaTrader.Cbi;
using NinjaTrader.Data;
using NinjaTrader.NinjaScript;
using NinjaTrader.NinjaScript.AddOns.Nexus;
#endregion

namespace NinjaTrader.NinjaScript.Strategies
{
    public class NexusGroupeM2 : NexusGroupeBase
    {
        private NxM2Logique m2;
        private string nomDonnees;

        [NinjaScriptProperty]
        [Display(Name = "Contrats", Order = 1, GroupName = "M2")]
        public int Contrats { get; set; }

        [NinjaScriptProperty]
        [Display(Name = "Instrument de donnees (vide = NQ meme echeance)", Order = 2, GroupName = "M2")]
        public string InstrumentDonnees { get; set; }

        [NinjaScriptProperty]
        [Display(Name = "Minutes de chauffe", Order = 3, GroupName = "M2")]
        public int MinutesChauffe { get; set; }

        protected override void OnStateChange()
        {
            if (State == State.SetDefaults)
            {
                Name = "NexusGroupeM2";
                Description = "M2 (Kairos, a confirmer) : momentum 5 min de 9:30 filtre, decisions sur NQ, positions sur l instrument de la strategie (MNQ).";
                Calculate = Calculate.OnBarClose;
                IsUnmanaged = true;
                BarsRequiredToTrade = 0;
                IsExitOnSessionCloseStrategy = false;
                StartBehavior = StartBehavior.WaitUntilFlat;
                Contrats = 1;
                InstrumentDonnees = "";
                MinutesChauffe = 10000;
                MaxContrats = 12;
                AutoriserCompteReel = false;
            }
            else if (State == State.Configure)
            {
                nomDonnees = string.IsNullOrWhiteSpace(InstrumentDonnees) ? "NQ " + Instrument.Expiry.ToString("MM-yy", CultureInfo.InvariantCulture) : InstrumentDonnees.Trim();
                AddDataSeries(nomDonnees, new BarsPeriod { BarsPeriodType = BarsPeriodType.Minute, Value = 1 }, MinutesChauffe, "Default 24 x 7", null);
            }
            else if (State == State.DataLoaded)
            {
                m2 = new NxM2Logique { Contrats = Contrats };
                Initialiser("M2", nomDonnees, 0);
            }
        }

        protected override void OnBarUpdate()
        {
            if (BarsInProgress == 1)
            {
                if (CurrentBars[1] < 0) return;
                DateTime fin = NxTime.NtToUtc(Times[1][0]);
                ConsignerBarre(fin, Opens[1][0], Highs[1][0], Lows[1][0], Closes[1][0], Volumes[1][0]);
                foreach (NxDecision d in m2.SurBarre(fin, Opens[1][0], Highs[1][0], Lows[1][0], Closes[1][0]))
                    AllerA(d.Cible, d.Motif);
                EcrireEtat("\"jour\":" + Q(m2.Jour.ToString("yyyy-MM-dd", Inv)) + ",\"cible\":" + m2.Cible.ToString(Inv)
                           + ",\"ema12\":" + N(m2.Ema) + ",\"atr14\":" + N(m2.Atr) + ",\"ecart_atr\":" + N(m2.Ecart)
                           + ",\"rendement_veille\":" + N(m2.RVeille)
                           + ",\"derniere_barre\":" + Q(NxGroupeCalendrier.VersNewYork(fin).ToString("yyyy-MM-dd HH:mm", Inv)) + ",\"dernier_cours\":" + N(Closes[1][0]));
            }
            else if (BarsInProgress == 0 && CurrentBar >= 0)
            {
                foreach (NxDecision d in m2.SurHorloge(NxTime.NtToUtc(Time[0])))
                    AllerA(d.Cible, d.Motif);
                Reconcilier();
            }
        }
    }
}
