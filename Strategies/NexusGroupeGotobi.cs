// =============================================================================
//  NexusGroupeGotobi.cs   (NinjaTrader 8 / NinjaScript)
//
//  Gotobi du Groupe : yen (6J) autour du fixing de Tokyo les jours gotobi
//  (5, 10, 15, 20, 25, fin de mois ; feries japonais) : 08:00 vente, 09:55
//  achat, 11:00 sortie (heure de Tokyo). Logique : AddOns\NexusGroupeLogique.cs
//  (NxGotobiLogique), identique ordre par ordre a la recherche.
//
//  Activer sur 6J <echeance courante>, compte Sim101. Les ordres partent au
//  premier tick de la barre qui commence a l heure prevue (8:00 du fil de
//  donnees, differe ou non) : execution a l ouverture de cette barre, comme
//  dans la recherche. Taille : capital x exposition / notionnel d un contrat.
// =============================================================================

#region Using declarations
using System;
using System.ComponentModel.DataAnnotations;
using System.Linq;
using NinjaTrader.Cbi;
using NinjaTrader.Data;
using NinjaTrader.NinjaScript;
using NinjaTrader.NinjaScript.AddOns.Nexus;
#endregion

namespace NinjaTrader.NinjaScript.Strategies
{
    public class NexusGroupeGotobi : NexusGroupeBase
    {
        private NxGotobiLogique g;

        [NinjaScriptProperty]
        [Display(Name = "Capital ($)", Order = 1, GroupName = "Gotobi")]
        public double Capital { get; set; }

        [NinjaScriptProperty]
        [Display(Name = "Exposition (part du capital)", Order = 2, GroupName = "Gotobi")]
        public double Exposition { get; set; }

        [NinjaScriptProperty]
        [Display(Name = "Contrats fixes (0 = taille au capital)", Order = 3, GroupName = "Gotobi")]
        public int ContratsFixes { get; set; }

        protected override void OnStateChange()
        {
            if (State == State.SetDefaults)
            {
                Name = "NexusGroupeGotobi";
                Description = "Gotobi du Groupe : 6J vendu a 08:00, achete a 09:55, solde a 11:00 (Tokyo), jours gotobi.";
                Calculate = Calculate.OnPriceChange;
                IsUnmanaged = true;
                BarsRequiredToTrade = 0;
                IsExitOnSessionCloseStrategy = false;
                StartBehavior = StartBehavior.WaitUntilFlat;
                Capital = 100000;
                Exposition = 0.95;
                ContratsFixes = 0;
                MaxContrats = 2;
                AutoriserCompteReel = false;
            }
            else if (State == State.DataLoaded)
            {
                g = new NxGotobiLogique { Capital = Capital, Exposition = Exposition, ContratsFixes = ContratsFixes,
                                          ValeurPoint = Instrument.MasterInstrument.PointValue };
                Initialiser("Gotobi", Instrument.FullName, Capital);
            }
        }

        protected override void OnBarUpdate()
        {
            if (BarsInProgress != 0 || CurrentBar < 0 || !IsFirstTickOfBar) return;
            if (CurrentBar > 0) ConsignerBarre(NxTime.NtToUtc(Time[1]), Open[1], High[1], Low[1], Close[1], Volume[1]);
            DateTime debut = NxTime.NtToUtc(Time[0]).AddMinutes(-1);              // debut de la barre qui commence
            double dernier = CurrentBar > 0 ? Close[1] : Close[0];
            foreach (NxDecision d in g.SurInstant(debut, dernier))
                AllerA(d.Cible, d.Motif);
            Reconcilier();
            DateTime prochain = NxGroupeCalendrier.ProchainsGotobi(g.JourGotobi && !g.JambesFaites.Contains("entree") ? g.JourTokyo : g.JourTokyo.AddDays(1), 1)
                                                   .DefaultIfEmpty(DateTime.MinValue).First();
            EcrireEtat("\"jour_tokyo\":" + Q(g.JourTokyo.ToString("yyyy-MM-dd", Inv)) + ",\"jour_gotobi\":" + (g.JourGotobi ? "true" : "false")
                       + ",\"contrats\":" + g.Contrats.ToString(Inv) + ",\"taille_estimee\":" + g.Taille(dernier).ToString(Inv)
                       + ",\"jambes_faites\":" + Q(string.Join(" ", g.JambesFaites))
                       + ",\"prochaine_entree\":" + Q(prochain == DateTime.MinValue ? "" : prochain.ToString("yyyy-MM-dd", Inv) + " 08:00 Tokyo")
                       + ",\"derniere_barre\":" + Q(NxGroupeCalendrier.VersNewYork(debut).ToString("yyyy-MM-dd HH:mm", Inv)) + ",\"dernier_cours\":" + N(dernier));
        }
    }
}
