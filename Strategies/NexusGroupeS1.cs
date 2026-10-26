// =============================================================================
//  NexusGroupeS1.cs   (NinjaTrader 8 / NinjaScript)
//
//  S1 du Groupe : Noise Area Intraday Momentum sur NQ (S1_NoiseAreaNQ,
//  reglage fige), positions sur l instrument de la strategie (MNQ conseille).
//  Logique : AddOns\NexusGroupeLogique.cs (NxS1Logique), identique ordre par
//  ordre a la recherche (python -m nexus.live.parite_ninjascript).
//
//  Activer sur MNQ <echeance courante> (Strategies > New Strategy), compte
//  Sim101 : la strategie charge elle-meme 75 000 minutes de NQ de la meme
//  echeance pour la chauffe (sigma sur 30 seances, volatilite 14 seances).
//  Decision a la cloture de la minute de controle (10:00 ... 15:30, heure de
//  New York, sur le fil de donnees : differe ou non), sortie a 16:00 (13:00
//  les demi-seances).
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
    public class NexusGroupeS1 : NexusGroupeBase
    {
        private NxS1Logique s1;
        private string nomDonnees;

        [NinjaScriptProperty]
        [Display(Name = "Capital ($)", Order = 1, GroupName = "S1")]
        public double Capital { get; set; }

        [NinjaScriptProperty]
        [Display(Name = "Instrument de donnees (vide = NQ meme echeance)", Order = 2, GroupName = "S1")]
        public string InstrumentDonnees { get; set; }

        [NinjaScriptProperty]
        [Display(Name = "Minutes de chauffe", Order = 3, GroupName = "S1")]
        public int MinutesChauffe { get; set; }

        protected override void OnStateChange()
        {
            if (State == State.SetDefaults)
            {
                Name = "NexusGroupeS1";
                Description = "S1 du Groupe (Noise Area NQ, reglage fige) : decisions sur NQ, positions sur l instrument de la strategie (MNQ).";
                Calculate = Calculate.OnBarClose;
                IsUnmanaged = true;
                BarsRequiredToTrade = 0;
                IsExitOnSessionCloseStrategy = false;
                StartBehavior = StartBehavior.WaitUntilFlat;
                Capital = 100000;
                InstrumentDonnees = "";
                MinutesChauffe = 75000;
                MaxContrats = 10;
                AutoriserCompteReel = false;
            }
            else if (State == State.Configure)
            {
                nomDonnees = string.IsNullOrWhiteSpace(InstrumentDonnees) ? "NQ " + Instrument.Expiry.ToString("MM-yy", CultureInfo.InvariantCulture) : InstrumentDonnees.Trim();
                AddDataSeries(nomDonnees, new BarsPeriod { BarsPeriodType = BarsPeriodType.Minute, Value = 1 }, MinutesChauffe, "Default 24 x 7", null);
            }
            else if (State == State.DataLoaded)
            {
                s1 = new NxS1Logique { Capital = Capital, ValeurPoint = Instrument.MasterInstrument.PointValue };
                Initialiser("S1", nomDonnees, Capital);
            }
        }

        protected override void OnBarUpdate()
        {
            if (BarsInProgress == 1)
            {
                if (CurrentBars[1] < 0) return;
                DateTime fin = NxTime.NtToUtc(Times[1][0]);
                ConsignerBarre(fin, Opens[1][0], Highs[1][0], Lows[1][0], Closes[1][0], Volumes[1][0]);
                foreach (NxDecision d in s1.SurBarre(fin, Opens[1][0], Highs[1][0], Lows[1][0], Closes[1][0], Volumes[1][0]))
                    AllerA(d.Cible, d.Motif);
                EcrireEtat("\"jour\":" + Q(s1.Jour.ToString("yyyy-MM-dd", Inv)) + ",\"pret\":" + (s1.Pret ? "true" : "false")
                           + ",\"contrats\":" + s1.Contrats.ToString(Inv) + ",\"levier\":" + N(s1.Levier) + ",\"haut\":" + N(s1.Haut) + ",\"bas\":" + N(s1.Bas)
                           + ",\"fin\":" + s1.Fin.ToString(Inv) + ",\"seances_historique\":" + s1.SeancesHistorique.ToString(Inv)
                           + ",\"derniere_barre\":" + Q(NxGroupeCalendrier.VersNewYork(fin).ToString("yyyy-MM-dd HH:mm", Inv)) + ",\"dernier_cours\":" + N(Closes[1][0]));
            }
            else if (BarsInProgress == 0 && CurrentBar >= 0)
            {
                foreach (NxDecision d in s1.SurHorloge(NxTime.NtToUtc(Time[0])))
                    AllerA(d.Cible, d.Motif);
                Reconcilier();
            }
        }
    }
}
