// =============================================================================
//  NexusGroupeBase.cs   (NinjaTrader 8 / NinjaScript)
// compte de demo accepte si la connexion est en mode Simulation
//  Socle des strategies du Groupe (NexusGroupeS1, NexusGroupeGotobi) : la
//  logique de decision est dans AddOns\NexusGroupeLogique.cs (verifiee ordre
//  par ordre contre la recherche) ; ce socle ne fait que :
//    - amener la position du compte a la position voulue (ordres au marche,
//      mode non gere ; un retournement = deux ordres envoyes ensemble) ;
//    - refuser un compte non simule (sauf AutoriserCompteReel) et mettre a
//      plat si le fichier Nexus\KILL_SWITCH existe (interrupteur global) ;
//    - consigner pour le tableau de bord, dans Nexus\groupe\<strategie>\ :
//      meta.json, etat.json, barres.csv (barres 1 minute recues en temps reel),
//      decisions.jsonl, executions.jsonl.
// =============================================================================

#region Using declarations
using System;
using System.Collections.Generic;
using System.ComponentModel;
using System.ComponentModel.DataAnnotations;
using System.Globalization;
using System.IO;
using System.Linq;
using System.Text;
using NinjaTrader.Cbi;
using NinjaTrader.NinjaScript;
using NinjaTrader.NinjaScript.AddOns.Nexus;
#endregion

namespace NinjaTrader.NinjaScript.Strategies
{
    public abstract class NexusGroupeBase : Strategy
    {
        protected static readonly CultureInfo Inv = CultureInfo.InvariantCulture;
        private static readonly DateTime Epoque = new DateTime(1970, 1, 1, 0, 0, 0, DateTimeKind.Utc);
        private readonly List<Order> enCours = new List<Order>();
        private string dossier;
        private bool refusSignale;
        protected string NomGroupe = "";
        protected int CibleVoulue;
        protected string DernierMotif = "";

        [NinjaScriptProperty]
        [Display(Name = "Contrats au plus", Order = 90, GroupName = "Groupe")]
        public int MaxContrats { get; set; }

        [NinjaScriptProperty]
        [Display(Name = "Autoriser un compte reel", Order = 91, GroupName = "Groupe")]
        public bool AutoriserCompteReel { get; set; }

        protected static long Ms(DateTime utc) { return (long)(utc - Epoque).TotalMilliseconds; }
        protected static string Q(string s) { return NxJson.Q(s ?? ""); }
        protected static string N(double v) { return NxJson.N(v); }

        protected int PositionSignee()
        {
            if (Position == null) return 0;
            return Position.MarketPosition == MarketPosition.Long ? Position.Quantity : Position.MarketPosition == MarketPosition.Short ? -Position.Quantity : 0;
        }

        protected bool CompteSimule()
        {
            if (Account == null) return false;
            if (Account.Provider == Provider.Simulator || Account.Provider == Provider.Playback) return true;
            // compte de demo du courtier (ex. DEMO8920103) : connexion "Simulation" choisie a l'ouverture
            // de NinjaTrader (elle se declare mode=Live, IsDemo=false) et nom de compte en DEMO
            ConnectOptions o = Account.Connection != null ? Account.Connection.Options : null;
            if (o == null) return false;
            if (o.Mode == NinjaTrader.Cbi.Mode.Simulation || o.IsDemo) return true;
            return o.Name == "Simulation" && Account.Name.StartsWith("DEMO", StringComparison.OrdinalIgnoreCase);
        }

        // ------------------------------------------------------------------ journal pour le tableau de bord
        protected void Initialiser(string nom, string donnees, double capital)
        {
            NomGroupe = nom;
            try
            {
                NxPaths.EnsureAll();
                dossier = Path.Combine(NxPaths.Root, "groupe", nom);
                Directory.CreateDirectory(dossier);
                File.WriteAllText(Path.Combine(dossier, "meta.json"),
                    "{\"nom\":" + Q(nom) + ",\"strategie_ninja\":" + Q(Name) + ",\"instrument_negocie\":" + Q(Instrument.FullName)
                    + ",\"donnees\":" + Q(donnees) + ",\"valeur_point\":" + N(Instrument.MasterInstrument.PointValue) + ",\"capital\":" + N(capital)
                    + ",\"compte\":" + Q(Account != null ? Account.Name : "") + ",\"demarre_utc\":" + Q(DateTime.UtcNow.ToString("o", Inv)) + "}",
                    new UTF8Encoding(false));
            }
            catch (Exception ex) { Print(nom + " : dossier du Groupe inaccessible : " + ex.Message); dossier = null; }
        }

        private void Ajouter(string fichier, string ligne)
        {
            if (dossier == null || State != State.Realtime) return;
            try { File.AppendAllText(Path.Combine(dossier, fichier), ligne + "\n", new UTF8Encoding(false)); } catch { }
        }

        protected void ConsignerBarre(DateTime finUtc, double o, double h, double l, double c, double v)
        {
            Ajouter("barres.csv", Ms(finUtc).ToString(Inv) + "," + o.ToString("R", Inv) + "," + h.ToString("R", Inv) + "," + l.ToString("R", Inv) + ","
                                  + c.ToString("R", Inv) + "," + v.ToString("R", Inv));
        }

        protected void EcrireEtat(string champs)
        {
            if (dossier == null || State != State.Realtime) return;
            try
            {
                File.WriteAllText(Path.Combine(dossier, "etat.json"),
                    "{\"nom\":" + Q(NomGroupe) + ",\"maj_utc\":" + Q(DateTime.UtcNow.ToString("o", Inv)) + ",\"cible\":" + CibleVoulue.ToString(Inv)
                    + ",\"position\":" + PositionSignee().ToString(Inv) + ",\"instrument\":" + Q(Instrument.FullName) + ",\"motif\":" + Q(DernierMotif)
                    + (string.IsNullOrEmpty(champs) ? "" : "," + champs) + "}", new UTF8Encoding(false));
            }
            catch { }
        }

        // ------------------------------------------------------------------ ordres
        protected void AllerA(int cible, string motif)
        {
            int c = Math.Max(-MaxContrats, Math.Min(MaxContrats, cible));
            CibleVoulue = c;
            DernierMotif = motif ?? "";
            Ajouter("decisions.jsonl", "{\"t\":" + Ms(DateTime.UtcNow).ToString(Inv) + ",\"strategie\":" + Q(NomGroupe) + ",\"cible\":" + c.ToString(Inv)
                                       + ",\"demande\":" + cible.ToString(Inv) + ",\"motif\":" + Q(motif) + "}");
            Reconcilier();
        }

        private static bool Actif(OrderState s)
        {
            return s != OrderState.Filled && s != OrderState.Cancelled && s != OrderState.Rejected && s != OrderState.Unknown;
        }

        protected void Reconcilier()
        {
            if (State != State.Realtime && State != State.Historical) return;
            enCours.RemoveAll(o => o == null || !Actif(o.OrderState));
            if (enCours.Count > 0) return;
            int voulu = CibleVoulue;
            if (File.Exists(NxPaths.KillSwitchFile)) voulu = 0;
            if (State == State.Realtime && !CompteSimule() && !AutoriserCompteReel)
            {
                if (!refusSignale) { Print(Name + " : compte " + (Account != null ? Account.Name : "?") + " non simule : aucun ordre (AutoriserCompteReel)"); refusSignale = true; }
                return;
            }
            int pos = PositionSignee();
            if (voulu == pos) return;
            string nom = "Nexus " + NomGroupe;
            if (pos > 0 && voulu < 0)
            {
                enCours.Add(SubmitOrderUnmanaged(0, OrderAction.Sell, OrderType.Market, pos, 0, 0, "", nom));
                enCours.Add(SubmitOrderUnmanaged(0, OrderAction.SellShort, OrderType.Market, -voulu, 0, 0, "", nom));
            }
            else if (pos < 0 && voulu > 0)
            {
                enCours.Add(SubmitOrderUnmanaged(0, OrderAction.BuyToCover, OrderType.Market, -pos, 0, 0, "", nom));
                enCours.Add(SubmitOrderUnmanaged(0, OrderAction.Buy, OrderType.Market, voulu, 0, 0, "", nom));
            }
            else if (voulu > pos)
                enCours.Add(SubmitOrderUnmanaged(0, pos < 0 ? OrderAction.BuyToCover : OrderAction.Buy, OrderType.Market, voulu - pos, 0, 0, "", nom));
            else
                enCours.Add(SubmitOrderUnmanaged(0, pos > 0 ? OrderAction.Sell : OrderAction.SellShort, OrderType.Market, pos - voulu, 0, 0, "", nom));
        }

        protected override void OnOrderUpdate(Order order, double limitPrice, double stopPrice, int quantity, int filled, double averageFillPrice,
                                              OrderState orderState, DateTime time, ErrorCode error, string comment)
        {
            if (orderState == OrderState.Rejected) Print(Name + " : ordre rejete (" + error + ") " + comment);
        }

        protected override void OnExecutionUpdate(Execution execution, string executionId, double price, int quantity, MarketPosition marketPosition,
                                                  string orderId, DateTime time)
        {
            if (execution == null || execution.Order == null) return;
            bool achat = execution.Order.OrderAction == OrderAction.Buy || execution.Order.OrderAction == OrderAction.BuyToCover;
            Ajouter("executions.jsonl", "{\"t\":" + Ms(NxTime.NtToUtc(time)).ToString(Inv) + ",\"strategie\":" + Q(NomGroupe)
                                        + ",\"instrument\":" + Q(execution.Instrument.FullName) + ",\"qty\":" + (achat ? quantity : -quantity).ToString(Inv)
                                        + ",\"prix\":" + N(price) + ",\"ordre\":" + Q(orderId) + ",\"nom\":" + Q(execution.Order.Name) + "}");
        }
    }
}
