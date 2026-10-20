// =============================================================================
//  NexusPasserelle.cs   (NinjaTrader 8 / NinjaScript - AddOn)
//
//  Passerelle entre NinjaTrader et le moteur Python du Groupe (Python/nexus/live).
//  La logique des strategies reste en Python ; NinjaTrader ne fait que :
//    1. diffuser les barres 1 minute des instruments demandes (historique de
//       chauffe puis temps reel), les executions, les ordres et les positions ;
//    2. amener chaque instrument a la POSITION CIBLE envoyee par Python, par
//       ordres au marche sur UN compte (Sim101 par defaut) ;
//    3. appliquer des garde-fous qui ne dependent pas de Python.
//
//  Ajout dynamique : Python s abonne a n importe quel instrument et envoie des
//  cibles a tout moment ; aucun redemarrage de NinjaTrader n est necessaire pour
//  ajouter une strategie, meme sur un nouvel instrument (BarsRequest, pas
//  AddDataSeries).
//
//  Protocole : TCP sur 127.0.0.1 (port 51888 par defaut), une ligne JSON par
//  message (UTF-8). Messages de Python : hello, subscribe, unsubscribe, target,
//  flatten, heartbeat, status. Messages vers Python : hello, subscribed, history,
//  history_done, bar, execution, order, position, heartbeat, guard, error.
//  Barres : t_fin = fin de la barre, millisecondes UTC (convention NinjaTrader).
//
//  GARDE-FOUS (fichier Documents\NinjaTrader 8\Nexus\passerelle.json, cree avec
//  les valeurs par defaut au premier lancement, relu a chaque modification) :
//    - un seul compte ; un compte non simule (Sim101, Playback) est REFUSE tant
//      que "compte_reel_autorise" n est pas a true ;
//    - plafond de contrats par racine (NQ, MNQ, 6J...) ; cible ecretee ;
//    - heure de coupure (heure de New York) : tout a plat de "coupure_et" a
//      "reprise_et" (16:10 -> 18:00 par defaut, limite Topstep) ;
//    - perte du jour (valeur liquidative depuis 18:00 ET) : tout a plat et
//      verrou jusqu a la seance suivante ;
//    - battement de coeur : sans message de Python pendant "delai_coeur_s"
//      secondes, ou a la deconnexion, toutes les cibles passent a 0 ;
//    - interrupteur global : fichier Nexus\KILL_SWITCH present -> tout a plat.
//  La passerelle ne touche qu aux instruments qui ont recu une cible : dedier le
//  compte au Groupe (une position manuelle sur le meme instrument serait
//  ramenee a la cible ; « Flatten » de NinjaTrader est donc annule : utiliser
//  « Tout arreter » de la fenetre Groupe).
//
//  FENETRE « Groupe » (Control Center > New > Groupe) : etat de la passerelle et
//  de Python, compte, garde-fou, valeur liquidative ; strategies du Groupe avec
//  un bouton Activer / Desactiver (la commande part a Python, qui modifie
//  groupe.json) ; cibles et positions par instrument ; journal ; bouton
//  « Tout arreter » (passerelle.json "actif": false : tout a plat, aucun ordre)
//  et « Reprendre ».
// =============================================================================

#region Using declarations
using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Linq;
using System.Net;
using System.Net.Sockets;
using System.Text;
using System.Threading;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Media;
using System.Windows.Threading;
using System.Xml.Linq;
using NinjaTrader.Cbi;
using NinjaTrader.Data;
using NinjaTrader.NinjaScript;
using NinjaTrader.Gui.Tools;
using NinjaTrader.NinjaScript.AddOns.Nexus;
#endregion

namespace NinjaTrader.NinjaScript.AddOns
{
    /// <summary>Reglages de la passerelle (passerelle.json).</summary>
    public class NxPasserelleConfig
    {
        public bool Actif = true;
        public int Port = 51888;
        public string Compte = "Sim101";
        public bool CompteReelAutorise = false;
        public Dictionary<string, int> MaxContrats = new Dictionary<string, int>(StringComparer.OrdinalIgnoreCase)
        {
            { "NQ", 1 }, { "MNQ", 10 }, { "ES", 1 }, { "MES", 10 }, { "6J", 2 }, { "MJY", 20 }, { "YM", 1 }, { "MYM", 10 }
        };
        public int MaxContratsDefaut = 1;
        public TimeSpan CoupureEt = new TimeSpan(16, 10, 0);
        public TimeSpan RepriseEt = new TimeSpan(18, 0, 0);
        public double PerteJourMax = 0.0;           // $ ; 0 = desactive
        public int DelaiCoeurS = 30;
        public int BarresMax = 100000;

        public static string Fichier { get { return Path.Combine(NxPaths.Root, "passerelle.json"); } }

        public string ToJson()
        {
            StringBuilder sb = new StringBuilder();
            sb.Append("{\n");
            sb.Append("  \"actif\": ").Append(Actif ? "true" : "false").Append(",\n");
            sb.Append("  \"port\": ").Append(Port.ToString(CultureInfo.InvariantCulture)).Append(",\n");
            sb.Append("  \"compte\": ").Append(NxJson.Q(Compte)).Append(",\n");
            sb.Append("  \"compte_reel_autorise\": ").Append(CompteReelAutorise ? "true" : "false").Append(",\n");
            sb.Append("  \"max_contrats\": {");
            sb.Append(string.Join(", ", MaxContrats.Select(kv => NxJson.Q(kv.Key) + ": " + kv.Value.ToString(CultureInfo.InvariantCulture))));
            sb.Append("},\n");
            sb.Append("  \"max_contrats_defaut\": ").Append(MaxContratsDefaut.ToString(CultureInfo.InvariantCulture)).Append(",\n");
            sb.Append("  \"coupure_et\": ").Append(NxJson.Q(CoupureEt.ToString(@"hh\:mm"))).Append(",\n");
            sb.Append("  \"reprise_et\": ").Append(NxJson.Q(RepriseEt.ToString(@"hh\:mm"))).Append(",\n");
            sb.Append("  \"perte_jour_max\": ").Append(NxJson.N(PerteJourMax)).Append(",\n");
            sb.Append("  \"delai_coeur_s\": ").Append(DelaiCoeurS.ToString(CultureInfo.InvariantCulture)).Append(",\n");
            sb.Append("  \"barres_max\": ").Append(BarresMax.ToString(CultureInfo.InvariantCulture)).Append("\n");
            sb.Append("}\n");
            return sb.ToString();
        }

        public static NxPasserelleConfig Lire(out string erreur)
        {
            erreur = null;
            NxPasserelleConfig c = new NxPasserelleConfig();
            string f = Fichier;
            try
            {
                if (!File.Exists(f))
                {
                    NxPaths.EnsureAll();
                    File.WriteAllText(f, c.ToJson(), new UTF8Encoding(false));
                    return c;
                }
                object o;
                if (!NxJson.TryParse(File.ReadAllText(f, Encoding.UTF8), out o) || !(o is Dictionary<string, object>))
                {
                    erreur = "passerelle.json illisible : valeurs par defaut";
                    return c;
                }
                Dictionary<string, object> d = (Dictionary<string, object>)o;
                object v;
                if (d.TryGetValue("actif", out v)) c.Actif = NxJson.Bool(v, c.Actif);
                if (d.TryGetValue("port", out v)) c.Port = (int)NxJson.Num(v);
                if (d.TryGetValue("compte", out v) && !string.IsNullOrWhiteSpace(NxJson.Str(v))) c.Compte = NxJson.Str(v).Trim();
                if (d.TryGetValue("compte_reel_autorise", out v)) c.CompteReelAutorise = NxJson.Bool(v, false);
                if (d.TryGetValue("max_contrats", out v) && v is Dictionary<string, object>)
                {
                    c.MaxContrats = new Dictionary<string, int>(StringComparer.OrdinalIgnoreCase);
                    foreach (KeyValuePair<string, object> kv in (Dictionary<string, object>)v)
                        c.MaxContrats[kv.Key.Trim()] = Math.Max(0, (int)NxJson.Num(kv.Value));
                }
                if (d.TryGetValue("max_contrats_defaut", out v)) c.MaxContratsDefaut = Math.Max(0, (int)NxJson.Num(v));
                if (d.TryGetValue("coupure_et", out v)) c.CoupureEt = NxTime.ParseHhmm(NxJson.Str(v), c.CoupureEt);
                if (d.TryGetValue("reprise_et", out v)) c.RepriseEt = NxTime.ParseHhmm(NxJson.Str(v), c.RepriseEt);
                if (d.TryGetValue("perte_jour_max", out v)) c.PerteJourMax = Math.Max(0.0, NxJson.Num(v));
                if (d.TryGetValue("delai_coeur_s", out v)) c.DelaiCoeurS = Math.Max(5, (int)NxJson.Num(v));
                if (d.TryGetValue("barres_max", out v)) c.BarresMax = Math.Max(1000, (int)NxJson.Num(v));
            }
            catch (Exception ex)
            {
                erreur = "passerelle.json : " + ex.Message;
            }
            return c;
        }

        public int Plafond(Instrument ins)
        {
            int m;
            string racine = ins.MasterInstrument.Name;
            return MaxContrats.TryGetValue(racine, out m) ? m : MaxContratsDefaut;
        }
    }

    /// <summary>Photographie de la passerelle pour la fenetre Groupe.</summary>
    public class NxGroupeInstantane
    {
        public bool Ecoute, PythonConnecte, CompteTrouve, Simulation, Actif;
        public int Port;
        public double SecondesDepuisPython = double.NaN, ValeurLiquidative = double.NaN, ResultatJour = double.NaN, AgeEtatGroupe = double.NaN;
        public string Compte = "", Verrou = "", Coupure = "", Reprise = "", Suspension = "";
        public List<NxGroupeStrategie> Strategies = new List<NxGroupeStrategie>();
        public List<NxGroupeInstrument> Instruments = new List<NxGroupeInstrument>();
        public List<string> Journal = new List<string>();
    }

    public class NxGroupeStrategie
    {
        public string Nom = "", Statut = "", Cibles = "", Resume = "", Erreur = "";
        public bool Actif = true;
    }

    public class NxGroupeInstrument
    {
        public string Nom = "";
        public int Cible, Position, Plafond;
    }

    public class NexusPasserelle : AddOnBase
    {
        private const int Version = 1;
        private static readonly object instanceSync = new object();
        private static NexusPasserelle enService;     // une seule instance ecoute

        private readonly object sync = new object();
        private readonly object ecritureSync = new object();
        private NxPasserelleConfig config;
        private DateTime configDate = DateTime.MinValue;
        private TcpListener ecoute;
        private Thread threadEcoute;
        private TcpClient client;
        private StreamWriter sortie;
        private System.Threading.Timer minuterie;
        private volatile bool arret;
        private DateTime dernierMessageUtc = DateTime.MinValue;
        private DateTime dernierCoeurEnvoyeUtc = DateTime.MinValue;
        private Account compte;
        private string verrou = "";
        private string verrouPrecedent = "";
        private DateTime jourPerte = DateTime.MinValue;
        private double liquidationDebutJour = double.NaN;
        private bool perteAtteinte;
        private readonly Queue<string> journalRecent = new Queue<string>();
        private Dictionary<string, object> etatGroupe;            // dernier etat du Groupe envoye par Python
        private DateTime etatGroupeUtc = DateTime.MinValue;
        private NTMenuItem menuNouveau, menuGroupe;

        /// <summary>Instance qui ecoute (null si l AddOn n est pas demarre).</summary>
        public static NexusPasserelle EnService { get { lock (instanceSync) return enService; } }

        private class Abonnement
        {
            public string Id;
            public Instrument Instrument;
            public BarsRequest Requete;
            public int ProchaineBarre;        // indice de la premiere barre pas encore envoyee
            public bool HistoriqueEnvoye;
            public EventHandler<BarsUpdateEventArgs> Gestionnaire;
        }

        private class Cible
        {
            public Instrument Instrument;
            public int Quantite;
            public string Ref = "";
            public DateTime PauseJusquUtc = DateTime.MinValue;
        }

        private readonly Dictionary<string, Abonnement> abonnements = new Dictionary<string, Abonnement>(StringComparer.Ordinal);
        private readonly Dictionary<string, Cible> cibles = new Dictionary<string, Cible>(StringComparer.Ordinal);

        protected override void OnStateChange()
        {
            if (State == State.SetDefaults)
            {
                Name = "NexusPasserelle";
                Description = "Passerelle TCP locale entre NinjaTrader et le moteur Python du Groupe (Python/nexus/live).";
            }
            else if (State == State.Active)
            {
                lock (instanceSync)
                {
                    if (enService != null) return;
                    enService = this;
                }
                Demarrer();
            }
            else if (State == State.Terminated)
            {
                lock (instanceSync)
                {
                    if (enService != this) return;
                    enService = null;
                }
                Arreter();
            }
        }

        // ------------------------------------------------------------------ demarrage / arret
        private void Demarrer()
        {
            string err;
            config = NxPasserelleConfig.Lire(out err);
            configDate = DateiModif();
            if (err != null) Journal(err);
            if (!config.Actif)
                Journal("Groupe arrete (\"actif\": false dans " + NxPasserelleConfig.Fichier + ") : aucun ordre avant « Reprendre »");
            arret = false;
            try
            {
                ecoute = new TcpListener(IPAddress.Loopback, config.Port);
                ecoute.Start();
            }
            catch (Exception ex)
            {
                Journal("impossible d ecouter sur 127.0.0.1:" + config.Port + " : " + ex.Message);
                ecoute = null;
                return;
            }
            threadEcoute = new Thread(BoucleEcoute) { IsBackground = true, Name = "NexusPasserelle" };
            threadEcoute.Start();
            minuterie = new System.Threading.Timer(Tic, null, 1000, 250);
            Journal("passerelle en ecoute sur 127.0.0.1:" + config.Port + ", compte " + config.Compte);
        }

        private void Arreter()
        {
            arret = true;
            try { if (minuterie != null) minuterie.Dispose(); } catch { }
            try { if (ecoute != null) ecoute.Stop(); } catch { }
            FermerClient("arret de la passerelle");
            lock (sync)
            {
                foreach (Abonnement a in abonnements.Values) Liberer(a);
                abonnements.Clear();
                DetacherCompte();
            }
        }

        private static DateTime DateiModif()
        {
            try { return File.Exists(NxPasserelleConfig.Fichier) ? File.GetLastWriteTimeUtc(NxPasserelleConfig.Fichier) : DateTime.MinValue; }
            catch { return DateTime.MinValue; }
        }

        // ------------------------------------------------------------------ reseau
        private void BoucleEcoute()
        {
            while (!arret)
            {
                TcpClient c;
                try { c = ecoute.AcceptTcpClient(); }
                catch { if (arret) return; Thread.Sleep(500); continue; }
                FermerClient("nouvelle connexion");
                lock (ecritureSync)
                {
                    client = c;
                    client.NoDelay = true;
                    sortie = new StreamWriter(client.GetStream(), new UTF8Encoding(false)) { AutoFlush = true, NewLine = "\n" };
                }
                dernierMessageUtc = DateTime.UtcNow;
                Journal("client Python connecte");
                Thread lecteur = new Thread(() => BoucleLecture(c)) { IsBackground = true, Name = "NexusPasserelleLecture" };
                lecteur.Start();
            }
        }

        private void BoucleLecture(TcpClient c)
        {
            try
            {
                StreamReader r = new StreamReader(c.GetStream(), new UTF8Encoding(false));
                string ligne;
                while (!arret && (ligne = r.ReadLine()) != null)
                {
                    dernierMessageUtc = DateTime.UtcNow;
                    if (ligne.Trim().Length == 0) continue;
                    object o;
                    if (!NxJson.TryParse(ligne, out o) || !(o is Dictionary<string, object>))
                    {
                        Envoyer("{\"type\":\"error\",\"msg\":\"JSON invalide\"}");
                        continue;
                    }
                    try { Traiter((Dictionary<string, object>)o); }
                    catch (Exception ex) { Envoyer("{\"type\":\"error\",\"msg\":" + NxJson.Q(ex.Message) + "}"); }
                }
            }
            catch (Exception) { }
            bool courant;
            lock (ecritureSync) courant = client == c;
            if (courant)
            {
                FermerClient("client deconnecte");
                ToutAPlat("deconnexion");
            }
        }

        private void FermerClient(string motif)
        {
            lock (ecritureSync)
            {
                if (client == null) return;
                try { client.Close(); } catch { }
                client = null;
                sortie = null;
            }
            Journal(motif);
            lock (sync)
            {
                foreach (Abonnement a in abonnements.Values) Liberer(a);
                abonnements.Clear();
            }
        }

        private void Envoyer(string json)
        {
            lock (ecritureSync)
            {
                if (sortie == null) return;
                try { sortie.WriteLine(json); }
                catch
                {
                    try { client.Close(); } catch { }
                    client = null;
                    sortie = null;
                }
            }
        }

        // ------------------------------------------------------------------ messages de Python
        private void Traiter(Dictionary<string, object> m)
        {
            string type = NxJson.Str(Val(m, "type")) ?? "";
            switch (type)
            {
                case "hello":
                    RelireConfig(true);
                    Envoyer(MessageHello());
                    break;
                case "heartbeat":
                    break;
                case "etat_groupe":
                    lock (sync) { etatGroupe = m; etatGroupeUtc = DateTime.UtcNow; }
                    break;
                case "status":
                    Envoyer(MessageCoeur());
                    break;
                case "subscribe":
                    Abonner(NxJson.Str(Val(m, "id")), NxJson.Str(Val(m, "instrument")), (int)Num(Val(m, "barres"), 0));
                    break;
                case "unsubscribe":
                    lock (sync)
                    {
                        Abonnement a;
                        string id = NxJson.Str(Val(m, "id")) ?? "";
                        if (abonnements.TryGetValue(id, out a)) { Liberer(a); abonnements.Remove(id); }
                    }
                    break;
                case "target":
                    FixerCible(NxJson.Str(Val(m, "instrument")), (int)Math.Round(Num(Val(m, "qty"), 0)), NxJson.Str(Val(m, "ref")) ?? "");
                    break;
                case "flatten":
                    ToutAPlat("demande de Python");
                    break;
                default:
                    Envoyer("{\"type\":\"error\",\"msg\":" + NxJson.Q("type inconnu : " + type) + "}");
                    break;
            }
        }

        private static object Val(Dictionary<string, object> m, string k) { object v; return m.TryGetValue(k, out v) ? v : null; }

        private static double Num(object v, double defaut)
        {
            if (v == null) return defaut;
            try { double x = NxJson.Num(v); return double.IsNaN(x) ? defaut : x; } catch { return defaut; }
        }

        // ------------------------------------------------------------------ instruments
        /// <summary>"NQ 12-26" tel quel ; "NQ" seul -> echeance courante selon le calendrier de roulement de NinjaTrader.</summary>
        private static Instrument Resoudre(string nom)
        {
            if (string.IsNullOrWhiteSpace(nom)) return null;
            nom = nom.Trim();
            if (nom.Contains(" ")) return Instrument.GetInstrument(nom);
            MasterInstrument mi = null;
            try { mi = MasterInstrument.DbGet(nom, InstrumentType.Future, false); } catch { }
            if (mi == null) return Instrument.GetInstrument(nom);
            DateTime auj = DateTime.Now.Date;
            Rollover r = mi.RolloverCollection.Where(x => x.Date.Date <= auj).OrderBy(x => x.Date).LastOrDefault();
            if (r == null) return null;
            return Instrument.GetInstrument(nom + " " + r.ContractMonth.ToString("MM-yy", CultureInfo.InvariantCulture));
        }

        private void Abonner(string id, string nom, int barres)
        {
            if (string.IsNullOrEmpty(id)) { Envoyer("{\"type\":\"error\",\"msg\":\"subscribe sans id\"}"); return; }
            Instrument ins = Resoudre(nom);
            if (ins == null)
            {
                Envoyer("{\"type\":\"error\",\"msg\":" + NxJson.Q("instrument introuvable : " + nom) + ",\"id\":" + NxJson.Q(id) + "}");
                return;
            }
            Abonnement a = new Abonnement { Id = id, Instrument = ins };
            int n = Math.Max(1, Math.Min(barres <= 0 ? 1 : barres, config.BarresMax));
            a.Requete = new BarsRequest(ins, n);
            a.Requete.BarsPeriod = new BarsPeriod { BarsPeriodType = BarsPeriodType.Minute, Value = 1 };
            a.Requete.TradingHours = TradingHours.Get("Default 24 x 7");
            if (ins.MasterInstrument.InstrumentType == InstrumentType.Future)
                a.Requete.MergePolicy = MergePolicy.MergeBackAdjusted;
            a.Gestionnaire = (s, e) => SurBarres(a);
            lock (sync)
            {
                Abonnement ancien;
                if (abonnements.TryGetValue(id, out ancien)) Liberer(ancien);
                abonnements[id] = a;
            }
            Envoyer("{\"type\":\"subscribed\",\"id\":" + NxJson.Q(id) + ",\"instrument\":" + NxJson.Q(ins.FullName)
                    + ",\"point_value\":" + NxJson.N(ins.MasterInstrument.PointValue) + ",\"tick\":" + NxJson.N(ins.MasterInstrument.TickSize) + "}");
            a.Requete.Update += a.Gestionnaire;
            a.Requete.Request((req, code, msg) =>
            {
                if (code != ErrorCode.NoError)
                {
                    Envoyer("{\"type\":\"error\",\"id\":" + NxJson.Q(id) + ",\"msg\":" + NxJson.Q("historique refuse : " + code + " " + msg) + "}");
                    return;
                }
                EnvoyerHistorique(a);
            });
        }

        private void Liberer(Abonnement a)
        {
            try
            {
                if (a.Requete != null)
                {
                    a.Requete.Update -= a.Gestionnaire;
                    a.Requete.Dispose();
                }
            }
            catch { }
            a.Requete = null;
        }

        private static long Ms(DateTime ntLocal)
        {
            DateTime u = NxTime.NtToUtc(ntLocal);
            return (long)(u - new DateTime(1970, 1, 1, 0, 0, 0, DateTimeKind.Utc)).TotalMilliseconds;
        }

        private static string Barre(Bars b, int i)
        {
            return "[" + Ms(b.GetTime(i)).ToString(CultureInfo.InvariantCulture) + "," + NxJson.N(b.GetOpen(i)) + "," + NxJson.N(b.GetHigh(i)) + ","
                   + NxJson.N(b.GetLow(i)) + "," + NxJson.N(b.GetClose(i)) + "," + b.GetVolume(i).ToString(CultureInfo.InvariantCulture) + "]";
        }

        /// <summary>Barres closes de l historique (toutes sauf la derniere, en formation), par paquets de 500.</summary>
        private void EnvoyerHistorique(Abonnement a)
        {
            lock (a)
            {
                if (a.Requete == null) return;
                Bars b = a.Requete.Bars;
                int fin = b.Count - 1;
                StringBuilder sb = new StringBuilder();
                int k = 0;
                for (int i = 0; i < fin; i++)
                {
                    if (k > 0) sb.Append(',');
                    sb.Append(Barre(b, i));
                    k++;
                    if (k == 500 || i == fin - 1)
                    {
                        Envoyer("{\"type\":\"history\",\"id\":" + NxJson.Q(a.Id) + ",\"barres\":[" + sb + "]}");
                        sb.Clear();
                        k = 0;
                    }
                }
                a.ProchaineBarre = Math.Max(0, fin);
                a.HistoriqueEnvoye = true;
                Envoyer("{\"type\":\"history_done\",\"id\":" + NxJson.Q(a.Id) + ",\"n\":" + Math.Max(0, fin).ToString(CultureInfo.InvariantCulture) + "}");
            }
        }

        /// <summary>Envoie chaque barre close une seule fois : celles qu une barre plus recente a remplacees.</summary>
        private void SurBarres(Abonnement a)
        {
            lock (a)
            {
                if (!a.HistoriqueEnvoye || a.Requete == null) return;
                Bars b = a.Requete.Bars;
                while (a.ProchaineBarre < b.Count - 1)
                {
                    EnvoyerBarre(a, b, a.ProchaineBarre, false);
                    a.ProchaineBarre++;
                }
            }
        }

        /// <summary>Barre en formation dont l heure de fin est passee depuis 2 s sans nouvelle transaction : envoyee close.</summary>
        private void CloreParHorloge()
        {
            List<Abonnement> l;
            lock (sync) l = abonnements.Values.ToList();
            DateTime maintenant = NxTime.UtcToNt(DateTime.UtcNow);
            foreach (Abonnement a in l)
            {
                lock (a)
                {
                    if (!a.HistoriqueEnvoye || a.Requete == null) continue;
                    Bars b = a.Requete.Bars;
                    int i = b.Count - 1;
                    if (i < 0 || a.ProchaineBarre != i) continue;
                    if (maintenant >= b.GetTime(i).AddSeconds(2))
                    {
                        EnvoyerBarre(a, b, i, true);
                        a.ProchaineBarre = i + 1;
                    }
                }
            }
        }

        private void EnvoyerBarre(Abonnement a, Bars b, int i, bool horloge)
        {
            Envoyer("{\"type\":\"bar\",\"id\":" + NxJson.Q(a.Id) + ",\"b\":" + Barre(b, i) + (horloge ? ",\"horloge\":true" : "") + "}");
        }

        // ------------------------------------------------------------------ compte
        private bool CompteSimule(Account a)
        {
            return a != null && (a.Provider == Provider.Simulator || a.Provider == Provider.Playback);
        }

        private void AttacherCompte()
        {
            if (compte != null && compte.Name == config.Compte) return;
            DetacherCompte();
            Account a;
            lock (Account.All) a = Account.All.FirstOrDefault(x => x.Name == config.Compte);
            if (a == null) return;
            compte = a;
            compte.ExecutionUpdate += SurExecution;
            compte.OrderUpdate += SurOrdre;
            compte.PositionUpdate += SurPosition;
            Journal("compte " + compte.Name + (CompteSimule(compte) ? " (simulation)" : " (REEL)"));
        }

        private void DetacherCompte()
        {
            if (compte == null) return;
            try
            {
                compte.ExecutionUpdate -= SurExecution;
                compte.OrderUpdate -= SurOrdre;
                compte.PositionUpdate -= SurPosition;
            }
            catch { }
            compte = null;
        }

        private bool Gere(Instrument ins)
        {
            lock (sync) return ins != null && cibles.ContainsKey(ins.FullName);
        }

        private void SurExecution(object s, ExecutionEventArgs e)
        {
            if (e.Execution == null || !Gere(e.Execution.Instrument)) return;
            Execution x = e.Execution;
            int q = x.MarketPosition == MarketPosition.Short ? -x.Quantity : x.Quantity;
            Envoyer("{\"type\":\"execution\",\"instrument\":" + NxJson.Q(x.Instrument.FullName) + ",\"qty\":" + q.ToString(CultureInfo.InvariantCulture)
                    + ",\"prix\":" + NxJson.N(x.Price) + ",\"t\":" + Ms(x.Time).ToString(CultureInfo.InvariantCulture)
                    + ",\"ordre\":" + NxJson.Q(x.OrderId ?? "") + ",\"nom\":" + NxJson.Q(x.Name ?? "") + "}");
        }

        private void SurOrdre(object s, OrderEventArgs e)
        {
            if (e.Order == null || !Gere(e.Order.Instrument)) return;
            Order o = e.Order;
            if (e.OrderState == OrderState.Rejected)
            {
                lock (sync)
                {
                    Cible c;
                    if (cibles.TryGetValue(o.Instrument.FullName, out c)) c.PauseJusquUtc = DateTime.UtcNow.AddSeconds(5);
                }
            }
            Envoyer("{\"type\":\"order\",\"instrument\":" + NxJson.Q(o.Instrument.FullName) + ",\"ordre\":" + NxJson.Q(o.OrderId ?? "")
                    + ",\"etat\":" + NxJson.Q(e.OrderState.ToString()) + ",\"rempli\":" + o.Filled.ToString(CultureInfo.InvariantCulture)
                    + ",\"prix_moyen\":" + NxJson.N(o.AverageFillPrice) + ",\"texte\":" + NxJson.Q(o.Text ?? "") + "}");
        }

        private void SurPosition(object s, PositionEventArgs e)
        {
            if (e.Position == null || !Gere(e.Position.Instrument)) return;
            int q = e.MarketPosition == MarketPosition.Short ? -e.Quantity : (e.MarketPosition == MarketPosition.Long ? e.Quantity : 0);
            Envoyer("{\"type\":\"position\",\"instrument\":" + NxJson.Q(e.Position.Instrument.FullName) + ",\"qty\":" + q.ToString(CultureInfo.InvariantCulture)
                    + ",\"prix_moyen\":" + NxJson.N(e.AveragePrice) + "}");
        }

        private int PositionSignee(Instrument ins)
        {
            if (compte == null) return 0;
            lock (compte.Positions)
            {
                foreach (Position p in compte.Positions)
                    if (p.Instrument == ins || p.Instrument.FullName == ins.FullName)
                        return p.MarketPosition == MarketPosition.Long ? p.Quantity : (p.MarketPosition == MarketPosition.Short ? -p.Quantity : 0);
            }
            return 0;
        }

        private static bool Actif(OrderState s)
        {
            return s == OrderState.Initialized || s == OrderState.Submitted || s == OrderState.Accepted || s == OrderState.Working
                   || s == OrderState.PartFilled || s == OrderState.ChangePending || s == OrderState.ChangeSubmitted
                   || s == OrderState.CancelPending || s == OrderState.CancelSubmitted || s == OrderState.TriggerPending
                   || s == OrderState.AcceptedByRisk || s == OrderState.Suspended;
        }

        /// <summary>Quantite signee restant a executer sur les ordres actifs de cet instrument (tous ordres du compte).</summary>
        private int OrdresEnCours(Instrument ins)
        {
            if (compte == null) return 0;
            int q = 0;
            bool aucun = true;
            lock (compte.Orders)
            {
                foreach (Order o in compte.Orders)
                {
                    if (o.Instrument.FullName != ins.FullName || !Actif(o.OrderState)) continue;
                    aucun = false;
                    int reste = o.Quantity - o.Filled;
                    q += (o.OrderAction == OrderAction.Buy || o.OrderAction == OrderAction.BuyToCover) ? reste : -reste;
                }
            }
            return aucun ? 0 : (q == 0 ? int.MaxValue : q);
        }

        // ------------------------------------------------------------------ cibles et garde-fous
        private void FixerCible(string nom, int qty, string reference)
        {
            Instrument ins = Resoudre(nom);
            if (ins == null)
            {
                Envoyer("{\"type\":\"error\",\"msg\":" + NxJson.Q("cible : instrument introuvable : " + nom) + "}");
                return;
            }
            int plafond = config.Plafond(ins);
            int q = Math.Max(-plafond, Math.Min(plafond, qty));
            lock (sync)
            {
                Cible c;
                if (!cibles.TryGetValue(ins.FullName, out c)) { c = new Cible { Instrument = ins }; cibles[ins.FullName] = c; }
                c.Quantite = q;
                c.Ref = reference;
            }
            Envoyer("{\"type\":\"target_ack\",\"instrument\":" + NxJson.Q(ins.FullName) + ",\"demande\":" + qty.ToString(CultureInfo.InvariantCulture)
                    + ",\"qty\":" + q.ToString(CultureInfo.InvariantCulture) + ",\"plafond\":" + plafond.ToString(CultureInfo.InvariantCulture)
                    + ",\"ref\":" + NxJson.Q(reference) + ",\"verrou\":" + NxJson.Q(verrou) + "}");
            if (q != qty) Journal("cible " + ins.FullName + " ecretee : " + qty + " -> " + q + " (plafond " + plafond + ")");
        }

        private void ToutAPlat(string motif)
        {
            bool change = false;
            lock (sync)
                foreach (Cible c in cibles.Values)
                    if (c.Quantite != 0) { c.Quantite = 0; change = true; }
            if (change)
            {
                Journal("tout a plat : " + motif);
                Envoyer("{\"type\":\"guard\",\"motif\":" + NxJson.Q(motif) + "}");
            }
        }

        private static DateTime HeureNewYork()
        {
            return NxTime.FromUtc(DateTime.UtcNow, NxTime.Eastern);
        }

        /// <summary>Verrou courant ("" = aucun) : toutes les cibles sont ramenees a 0 tant qu il dure.</summary>
        private string CalculerVerrou()
        {
            if (!config.Actif) return "inactif";
            if (File.Exists(NxPaths.KillSwitchFile)) return "interrupteur";
            if (compte == null) return "compte absent";
            if (!CompteSimule(compte) && !config.CompteReelAutorise) return "compte reel refuse";
            DateTime ny = HeureNewYork();
            TimeSpan h = ny.TimeOfDay;
            bool coupure = config.CoupureEt <= config.RepriseEt ? (h >= config.CoupureEt && h < config.RepriseEt)
                                                                 : (h >= config.CoupureEt || h < config.RepriseEt);
            if (coupure) return "coupure";
            // perte du jour : seance de 18:00 ET a 18:00 ET
            DateTime seance = h >= new TimeSpan(18, 0, 0) ? ny.Date.AddDays(1) : ny.Date;
            double liq = double.NaN;
            try { liq = compte.Get(AccountItem.NetLiquidation, Currency.UsDollar); } catch { }
            if (seance != jourPerte)
            {
                jourPerte = seance;
                liquidationDebutJour = liq;
                perteAtteinte = false;
            }
            else if (double.IsNaN(liquidationDebutJour) || liquidationDebutJour == 0) liquidationDebutJour = liq;
            if (config.PerteJourMax > 0 && !double.IsNaN(liq) && !double.IsNaN(liquidationDebutJour) && liq - liquidationDebutJour <= -config.PerteJourMax)
                perteAtteinte = true;
            if (perteAtteinte) return "perte du jour";
            if (client == null) return "python absent";
            if ((DateTime.UtcNow - dernierMessageUtc).TotalSeconds > config.DelaiCoeurS) return "battement de coeur perdu";
            return "";
        }

        private void Tic(object etat)
        {
            if (arret) return;
            try
            {
                RelireConfig(false);
                AttacherCompte();
                CloreParHorloge();
                string v = CalculerVerrou();
                verrou = v;
                if (v != verrouPrecedent)
                {
                    if (v != "")
                        ToutAPlat(v);                       // cibles remises a 0 : pas de reprise automatique apres le verrou
                    if (v != "") Journal("verrou : " + v);
                    else if (verrouPrecedent != "") Journal("verrou leve (" + verrouPrecedent + ")");
                    Envoyer("{\"type\":\"guard\",\"motif\":" + NxJson.Q(v == "" ? "aucun" : v) + "}");
                    verrouPrecedent = v;
                }
                Reconcilier(v);
                if ((DateTime.UtcNow - dernierCoeurEnvoyeUtc).TotalSeconds >= 5)
                {
                    dernierCoeurEnvoyeUtc = DateTime.UtcNow;
                    Envoyer(MessageCoeur());
                }
            }
            catch (Exception ex)
            {
                Journal("erreur minuterie : " + ex.Message);
            }
        }

        private void Reconcilier(string v)
        {
            if (compte == null) return;
            if (!CompteSimule(compte) && !config.CompteReelAutorise) return;      // jamais un ordre sur un compte reel non autorise
            List<Cible> l;
            lock (sync) l = cibles.Values.ToList();
            foreach (Cible c in l)
            {
                int voulu = v == "" ? c.Quantite : 0;
                if (DateTime.UtcNow < c.PauseJusquUtc) continue;
                if (OrdresEnCours(c.Instrument) != 0) continue;                    // attendre l ordre en cours
                int pos = PositionSignee(c.Instrument);
                int delta = voulu - pos;
                if (delta == 0) continue;
                Soumettre(c, delta);
            }
        }

        private void Soumettre(Cible c, int delta)
        {
            OrderAction action = delta > 0 ? OrderAction.Buy : OrderAction.Sell;
            Order o = compte.CreateOrder(c.Instrument, action, OrderType.Market, OrderEntry.Automated, TimeInForce.Day, Math.Abs(delta), 0, 0,
                                         string.Empty, "Nexus " + (c.Ref ?? ""), NinjaTrader.Core.Globals.MaxDate, null);
            c.PauseJusquUtc = DateTime.UtcNow.AddSeconds(1);                    // laisse le temps a l ordre d apparaitre
            compte.Submit(new[] { o });
            Journal("ordre " + action + " " + Math.Abs(delta) + " " + c.Instrument.FullName + " (" + c.Ref + ")");
        }

        private void RelireConfig(bool force)
        {
            DateTime d = DateiModif();
            if (!force && d == configDate) return;
            configDate = d;
            string err;
            NxPasserelleConfig c = NxPasserelleConfig.Lire(out err);
            if (err != null) { Journal(err); return; }
            if (c.Port != config.Port) Journal("changement de port pris en compte au prochain demarrage de NinjaTrader");
            c.Port = config.Port;
            config = c;
        }

        // ------------------------------------------------------------------ messages vers Python
        private string MessageHello()
        {
            return "{\"type\":\"hello\",\"passerelle\":\"NexusPasserelle\",\"version\":" + Version.ToString(CultureInfo.InvariantCulture)
                   + ",\"compte\":" + NxJson.Q(config.Compte) + ",\"compte_trouve\":" + (compte != null ? "true" : "false")
                   + ",\"simulation\":" + (CompteSimule(compte) ? "true" : "false")
                   + ",\"coupure_et\":" + NxJson.Q(config.CoupureEt.ToString(@"hh\:mm")) + ",\"reprise_et\":" + NxJson.Q(config.RepriseEt.ToString(@"hh\:mm"))
                   + ",\"perte_jour_max\":" + NxJson.N(config.PerteJourMax) + ",\"delai_coeur_s\":" + config.DelaiCoeurS.ToString(CultureInfo.InvariantCulture)
                   + ",\"max_contrats\":{" + string.Join(",", config.MaxContrats.Select(kv => NxJson.Q(kv.Key) + ":" + kv.Value.ToString(CultureInfo.InvariantCulture))) + "}"
                   + ",\"max_contrats_defaut\":" + config.MaxContratsDefaut.ToString(CultureInfo.InvariantCulture) + "}";
        }

        private string MessageCoeur()
        {
            StringBuilder pos = new StringBuilder(), cib = new StringBuilder();
            List<Cible> l;
            lock (sync) l = cibles.Values.ToList();
            foreach (Cible c in l)
            {
                if (pos.Length > 0) { pos.Append(','); cib.Append(','); }
                pos.Append(NxJson.Q(c.Instrument.FullName)).Append(':').Append(PositionSignee(c.Instrument).ToString(CultureInfo.InvariantCulture));
                cib.Append(NxJson.Q(c.Instrument.FullName)).Append(':').Append(c.Quantite.ToString(CultureInfo.InvariantCulture));
            }
            double liq = double.NaN;
            try { if (compte != null) liq = compte.Get(AccountItem.NetLiquidation, Currency.UsDollar); } catch { }
            double jour = double.IsNaN(liq) || double.IsNaN(liquidationDebutJour) ? double.NaN : liq - liquidationDebutJour;
            long t = (long)(DateTime.UtcNow - new DateTime(1970, 1, 1, 0, 0, 0, DateTimeKind.Utc)).TotalMilliseconds;
            return "{\"type\":\"heartbeat\",\"t\":" + t.ToString(CultureInfo.InvariantCulture) + ",\"verrou\":" + NxJson.Q(verrou)
                   + ",\"positions\":{" + pos + "},\"cibles\":{" + cib + "},\"valeur_liquidative\":" + NxJson.N(liq)
                   + ",\"resultat_jour\":" + NxJson.N(jour) + "}";
        }

        // ------------------------------------------------------------------ fenetre Groupe
        public NxGroupeInstantane Instantane()
        {
            NxGroupeInstantane s = new NxGroupeInstantane();
            NxPasserelleConfig c = config;
            s.Ecoute = ecoute != null && !arret;
            if (c != null)
            {
                s.Port = c.Port;
                s.Actif = c.Actif;
                s.Compte = c.Compte;
                s.Coupure = c.CoupureEt.ToString(@"hh\:mm");
                s.Reprise = c.RepriseEt.ToString(@"hh\:mm");
            }
            lock (ecritureSync) s.PythonConnecte = client != null;
            if (s.PythonConnecte) s.SecondesDepuisPython = (DateTime.UtcNow - dernierMessageUtc).TotalSeconds;
            Account a = compte;
            s.CompteTrouve = a != null;
            s.Simulation = CompteSimule(a);
            s.Verrou = verrou ?? "";
            try { if (a != null) s.ValeurLiquidative = a.Get(AccountItem.NetLiquidation, Currency.UsDollar); } catch { }
            if (!double.IsNaN(s.ValeurLiquidative) && !double.IsNaN(liquidationDebutJour)) s.ResultatJour = s.ValeurLiquidative - liquidationDebutJour;
            List<Cible> l;
            lock (sync) l = cibles.Values.ToList();
            foreach (Cible x in l)
                s.Instruments.Add(new NxGroupeInstrument { Nom = x.Instrument.FullName, Cible = x.Quantite, Position = PositionSignee(x.Instrument),
                                                          Plafond = c != null ? c.Plafond(x.Instrument) : 0 });
            Dictionary<string, object> g;
            DateTime gt;
            lock (sync) { g = etatGroupe; gt = etatGroupeUtc; }
            if (g != null)
            {
                s.AgeEtatGroupe = (DateTime.UtcNow - gt).TotalSeconds;
                s.Suspension = NxJson.Str(Val(g, "suspension")) ?? "";
                List<object> st = Val(g, "strategies") as List<object>;
                if (st != null)
                    foreach (object o in st)
                    {
                        Dictionary<string, object> d = o as Dictionary<string, object>;
                        if (d == null) continue;
                        NxGroupeStrategie r = new NxGroupeStrategie
                        {
                            Nom = NxJson.Str(Val(d, "nom")) ?? "", Actif = NxJson.Bool(Val(d, "actif"), true), Statut = NxJson.Str(Val(d, "statut")) ?? "",
                            Resume = NxJson.Str(Val(d, "resume")) ?? "", Erreur = NxJson.Str(Val(d, "erreur")) ?? ""
                        };
                        Dictionary<string, object> cb = Val(d, "cibles") as Dictionary<string, object>;
                        List<string> parts = new List<string>();
                        if (cb != null)
                            foreach (KeyValuePair<string, object> kv in cb)
                            {
                                int q = (int)Num(kv.Value, 0);
                                if (q != 0) parts.Add(kv.Key + " " + (q > 0 ? "+" : "") + q.ToString(CultureInfo.InvariantCulture));
                            }
                        r.Cibles = parts.Count > 0 ? string.Join(", ", parts) : "à plat";
                        s.Strategies.Add(r);
                    }
            }
            lock (journalRecent) s.Journal = journalRecent.Reverse().ToList();
            return s;
        }

        /// <summary>Commande pour Python (activer / desactiver une strategie). Faux si Python n est pas connecte.</summary>
        public bool Commande(string action, string nom)
        {
            bool ok;
            lock (ecritureSync) ok = sortie != null;
            if (!ok) return false;
            Envoyer("{\"type\":\"commande\",\"action\":" + NxJson.Q(action) + ",\"nom\":" + NxJson.Q(nom) + ",\"source\":\"NinjaTrader\"}");
            Journal("commande « " + action + " " + nom + " » envoyee a Python (fenetre Groupe)");
            return true;
        }

        /// <summary>« Tout arreter » (false) / « Reprendre » (true) : ecrit "actif" dans passerelle.json.</summary>
        public void DefinirActif(bool actif)
        {
            NxPasserelleConfig c = config;
            if (c == null) return;
            c.Actif = actif;
            try
            {
                NxPaths.EnsureAll();
                File.WriteAllText(NxPasserelleConfig.Fichier, c.ToJson(), new UTF8Encoding(false));
                configDate = DateiModif();
            }
            catch (Exception ex) { Journal("passerelle.json non ecrit : " + ex.Message); }
            Journal(actif ? "Groupe repris (fenetre Groupe)" : "TOUT ARRETER (fenetre Groupe) : tout a plat, aucun ordre avant « Reprendre »");
        }

        protected override void OnWindowCreated(Window window)
        {
            NinjaTrader.Gui.ControlCenter cc = window as NinjaTrader.Gui.ControlCenter;
            if (cc == null) return;
            NTMenuItem nouveau = cc.FindFirst("ControlCenterMenuItemNew") as NTMenuItem;
            if (nouveau == null) return;
            foreach (object o in nouveau.Items)
            {
                NTMenuItem x = o as NTMenuItem;
                if (x != null && (x.Tag as string) == "NexusGroupe") return;
            }
            menuNouveau = nouveau;
            menuGroupe = new NTMenuItem { Header = "Groupe", Tag = "NexusGroupe", Style = Application.Current.TryFindResource("MainMenuItem") as Style };
            menuGroupe.Click += OuvrirGroupe;
            nouveau.Items.Add(menuGroupe);
        }

        protected override void OnWindowDestroyed(Window window)
        {
            if (menuGroupe == null || !(window is NinjaTrader.Gui.ControlCenter)) return;
            if (menuNouveau != null && menuNouveau.Items.Contains(menuGroupe)) menuNouveau.Items.Remove(menuGroupe);
            menuGroupe.Click -= OuvrirGroupe;
            menuGroupe = null;
            menuNouveau = null;
        }

        private void OuvrirGroupe(object sender, RoutedEventArgs e)
        {
            NinjaTrader.Core.Globals.RandomDispatcher.BeginInvoke(new Action(() => new NexusGroupeFenetre().Show()));
        }

        // ------------------------------------------------------------------ journal
        private void Journal(string msg)
        {
            string ligne = DateTime.Now.ToString("yyyy-MM-dd HH:mm:ss", CultureInfo.InvariantCulture) + "  " + msg;
            lock (journalRecent)
            {
                journalRecent.Enqueue(ligne);
                while (journalRecent.Count > 80) journalRecent.Dequeue();
            }
            try { Print("[NexusPasserelle] " + msg); } catch { }
            try
            {
                NxPaths.EnsureAll();
                File.AppendAllText(Path.Combine(NxPaths.Journal, "passerelle_" + DateTime.Now.ToString("yyyyMMdd", CultureInfo.InvariantCulture) + ".log"),
                                   ligne + Environment.NewLine, new UTF8Encoding(false));
            }
            catch { }
        }
    }

    /// <summary>Fenetre « Groupe » (Control Center > New > Groupe).</summary>
    public class NexusGroupeFenetre : NTWindow, IWorkspacePersistence
    {
        private static readonly CultureInfo Fr = CultureInfo.GetCultureInfo("fr-FR");
        private readonly TextBlock titre, ligneConnexion, ligneCompte, ligneArgent, ligneAlerte;
        private readonly Button boutonArret, boutonTableau;
        private readonly Grid grilleStrategies, grilleInstruments;
        private readonly TextBox journal;
        private readonly DispatcherTimer minuterie;
        private string sigStrategies, sigInstruments;
        private readonly Brush texte;

        public NexusGroupeFenetre()
        {
            Caption = "Groupe";
            Width = 940;
            Height = 680;
            Brush theme = Application.Current.TryFindResource("FontControlBrush") as Brush;
            texte = theme != null && theme.IsFrozen ? theme : null;             // sinon : couleur heritee de la fenetre
            StackPanel racine = new StackPanel { Margin = new Thickness(14) };
            titre = Texte("Groupe", 18, true);
            racine.Children.Add(titre);
            ligneConnexion = Texte("", 13, false);
            ligneCompte = Texte("", 13, false);
            ligneArgent = Texte("", 13, false);
            ligneAlerte = Texte("", 13, true);
            ligneAlerte.Foreground = Brushes.OrangeRed;
            foreach (TextBlock t in new[] { ligneConnexion, ligneCompte, ligneArgent, ligneAlerte }) racine.Children.Add(t);

            StackPanel boutons = new StackPanel { Orientation = Orientation.Horizontal, Margin = new Thickness(0, 10, 0, 6) };
            boutonArret = new Button { Content = "Tout arrêter", Padding = new Thickness(14, 4, 14, 4), Margin = new Thickness(0, 0, 10, 0) };
            boutonArret.Click += SurArret;
            boutonTableau = new Button { Content = "Tableau de bord (navigateur)", Padding = new Thickness(14, 4, 14, 4) };
            boutonTableau.Click += (s, e) => { try { System.Diagnostics.Process.Start("http://localhost:3000/#/direct"); } catch { } };
            boutons.Children.Add(boutonArret);
            boutons.Children.Add(boutonTableau);
            racine.Children.Add(boutons);

            racine.Children.Add(Texte("Stratégies du Groupe", 15, true, new Thickness(0, 12, 0, 4)));
            racine.Children.Add(Texte("Ajouter une stratégie : un fichier Python et une ligne dans Python/nexus/live/groupe.json (relu toutes les 5 s, sans redémarrage).", 11, false));
            grilleStrategies = new Grid { Margin = new Thickness(0, 6, 0, 0) };
            racine.Children.Add(grilleStrategies);

            racine.Children.Add(Texte("Instruments", 15, true, new Thickness(0, 14, 0, 4)));
            grilleInstruments = new Grid();
            racine.Children.Add(grilleInstruments);

            racine.Children.Add(Texte("Journal de la passerelle", 15, true, new Thickness(0, 14, 0, 4)));
            journal = new TextBox { IsReadOnly = true, Height = 170, TextWrapping = TextWrapping.Wrap, VerticalScrollBarVisibility = ScrollBarVisibility.Auto,
                                    FontFamily = new FontFamily("Consolas"), FontSize = 11 };
            racine.Children.Add(journal);

            Content = new ScrollViewer { Content = racine, VerticalScrollBarVisibility = ScrollBarVisibility.Auto };
            minuterie = new DispatcherTimer { Interval = TimeSpan.FromSeconds(1) };
            minuterie.Tick += (s, e) => Rafraichir();
            Loaded += (s, e) =>
            {
                if (WorkspaceOptions == null) WorkspaceOptions = new WorkspaceOptions("NexusGroupe-" + Guid.NewGuid().ToString("N"), this);
                Rafraichir();
                minuterie.Start();
            };
            Closed += (s, e) => minuterie.Stop();
        }

        public void Restore(XDocument document, XElement element) { }
        public void Save(XDocument document, XElement element) { }
        public WorkspaceOptions WorkspaceOptions { get; set; }

        private TextBlock Texte(string t, double taille, bool gras, Thickness? marge = null)
        {
            TextBlock b = new TextBlock { Text = t, FontSize = taille, TextWrapping = TextWrapping.Wrap, Margin = marge ?? new Thickness(0, 2, 0, 2) };
            if (gras) b.FontWeight = FontWeights.SemiBold;
            if (texte != null) b.Foreground = texte;
            return b;
        }

        private static string Dollars(double v)
        {
            return double.IsNaN(v) ? "–" : v.ToString("N0", Fr) + " $";
        }

        private void Rafraichir()
        {
            NexusPasserelle p = NexusPasserelle.EnService;
            if (p == null)
            {
                ligneConnexion.Text = "Passerelle arrêtée : l'AddOn NexusPasserelle n'est pas démarré (compiler avec F5, puis redémarrer NinjaTrader).";
                ligneCompte.Text = ligneArgent.Text = ligneAlerte.Text = "";
                boutonArret.IsEnabled = false;
                return;
            }
            NxGroupeInstantane s = p.Instantane();
            titre.Text = s.Actif ? "Groupe" : "Groupe — ARRÊTÉ";
            ligneConnexion.Text = "Passerelle : " + (s.Ecoute ? "en écoute sur 127.0.0.1:" + s.Port : "n'écoute pas (port occupé ?)")
                                  + "   ·   Python : " + (s.PythonConnecte ? "connecté" + (double.IsNaN(s.SecondesDepuisPython) ? "" : " (dernier message il y a "
                                  + Math.Round(s.SecondesDepuisPython).ToString(Fr) + " s)") : "absent — lancer « python -m nexus.live » depuis Python\\");
            ligneCompte.Text = "Compte : " + s.Compte + (s.CompteTrouve ? (s.Simulation ? " (simulation)" : " (RÉEL)") : " (introuvable)")
                               + "   ·   Garde-fou : " + (string.IsNullOrEmpty(s.Verrou) ? "aucun" : s.Verrou)
                               + (string.IsNullOrEmpty(s.Suspension) ? "" : "   ·   Groupe suspendu : " + s.Suspension)
                               + "   ·   Coupure : " + s.Coupure + " → " + s.Reprise + " (heure de New York)";
            ligneArgent.Text = "Valeur liquidative : " + Dollars(s.ValeurLiquidative) + "   ·   Résultat depuis 18:00 ET : " + Dollars(s.ResultatJour);
            string alerte = "";
            if (!s.Actif) alerte = "Groupe arrêté depuis cette fenêtre : tout est à plat et aucun ordre ne part avant « Reprendre ».";
            else if (s.CompteTrouve && !s.Simulation) alerte = "Compte non simulé : ordres refusés tant que \"compte_reel_autorise\" n'est pas à true dans passerelle.json.";
            else if (!s.CompteTrouve) alerte = "Compte " + s.Compte + " introuvable : vérifier la connexion et \"compte\" dans passerelle.json.";
            ligneAlerte.Text = alerte;
            ligneAlerte.Visibility = alerte.Length > 0 ? Visibility.Visible : Visibility.Collapsed;
            boutonArret.IsEnabled = true;
            boutonArret.Content = s.Actif ? "Tout arrêter" : "Reprendre";

            string sig = s.PythonConnecte + "|" + string.Join("|", s.Strategies.Select(x => x.Nom + ";" + x.Actif + ";" + x.Statut + ";" + x.Cibles + ";" + x.Resume + ";" + x.Erreur));
            if (sig != sigStrategies)
            {
                sigStrategies = sig;
                RemplirStrategies(s);
            }
            sig = string.Join("|", s.Instruments.Select(x => x.Nom + ";" + x.Cible + ";" + x.Position + ";" + x.Plafond));
            if (sig != sigInstruments)
            {
                sigInstruments = sig;
                RemplirInstruments(s);
            }
            string j = string.Join(Environment.NewLine, s.Journal);
            if (journal.Text != j) journal.Text = j;
        }

        private void Colonnes(Grid g, params double[] largeurs)
        {
            g.Children.Clear();
            g.RowDefinitions.Clear();
            g.ColumnDefinitions.Clear();
            foreach (double w in largeurs)
                g.ColumnDefinitions.Add(new ColumnDefinition { Width = w > 0 ? new GridLength(w) : new GridLength(1, GridUnitType.Star) });
        }

        private void Cellule(Grid g, int ligne, int col, UIElement e)
        {
            while (g.RowDefinitions.Count <= ligne) g.RowDefinitions.Add(new RowDefinition { Height = GridLength.Auto });
            Grid.SetRow(e, ligne);
            Grid.SetColumn(e, col);
            g.Children.Add(e);
        }

        private TextBlock Case(string t, bool gras = false)
        {
            TextBlock b = Texte(t, 12.5, gras);
            b.Margin = new Thickness(0, 3, 12, 3);
            b.VerticalAlignment = VerticalAlignment.Center;
            return b;
        }

        private void RemplirStrategies(NxGroupeInstantane s)
        {
            Grid g = grilleStrategies;
            Colonnes(g, 120, 150, 140, 0, 110);
            string[] tetes = { "Stratégie", "Statut", "Cible", "État", "" };
            for (int k = 0; k < tetes.Length; k++) Cellule(g, 0, k, Case(tetes[k], true));
            if (s.Strategies.Count == 0)
            {
                Cellule(g, 1, 0, Case(s.PythonConnecte ? "(en attente de l'état du Groupe)" : "(Python absent)"));
                return;
            }
            int i = 1;
            foreach (NxGroupeStrategie x in s.Strategies)
            {
                Cellule(g, i, 0, Case(x.Nom, true));
                TextBlock st = Case(Statut(x));
                if (x.Statut == "erreur") st.Foreground = Brushes.OrangeRed;
                Cellule(g, i, 1, st);
                Cellule(g, i, 2, Case(x.Cibles));
                Cellule(g, i, 3, Case(string.IsNullOrEmpty(x.Erreur) ? x.Resume : x.Erreur));
                Button b = new Button { Content = x.Actif ? "Désactiver" : "Activer", Padding = new Thickness(8, 2, 8, 2), Margin = new Thickness(0, 2, 0, 2),
                                        IsEnabled = s.PythonConnecte, Tag = x };
                b.Click += SurBascule;
                Cellule(g, i, 4, b);
                i++;
            }
        }

        private static string Statut(NxGroupeStrategie x)
        {
            switch (x.Statut)
            {
                case "active": return "active";
                case "chauffe": return "chauffe (historique)";
                case "desactivee": return "désactivée";
                case "erreur": return "ERREUR (cibles à 0)";
                default: return x.Statut;
            }
        }

        private void RemplirInstruments(NxGroupeInstantane s)
        {
            Grid g = grilleInstruments;
            Colonnes(g, 160, 110, 110, 0);
            string[] tetes = { "Instrument", "Cible nette", "Position", "Plafond" };
            for (int k = 0; k < tetes.Length; k++) Cellule(g, 0, k, Case(tetes[k], true));
            int i = 1;
            foreach (NxGroupeInstrument x in s.Instruments)
            {
                Cellule(g, i, 0, Case(x.Nom, true));
                Cellule(g, i, 1, Case((x.Cible > 0 ? "+" : "") + x.Cible.ToString(Fr)));
                TextBlock pos = Case((x.Position > 0 ? "+" : "") + x.Position.ToString(Fr) + (x.Position != x.Cible ? "  (ordre en cours)" : ""));
                Cellule(g, i, 2, pos);
                Cellule(g, i, 3, Case(x.Plafond.ToString(Fr) + " contrat(s)"));
                i++;
            }
            if (i == 1) Cellule(g, 1, 0, Case("(aucune cible reçue)"));
        }

        private void SurBascule(object sender, RoutedEventArgs e)
        {
            NxGroupeStrategie x = (sender as Button)?.Tag as NxGroupeStrategie;
            NexusPasserelle p = NexusPasserelle.EnService;
            if (x == null || p == null) return;
            string action = x.Actif ? "desactiver" : "activer";
            string question = x.Actif ? "Désactiver " + x.Nom + " ? Ses positions sont mises à plat tout de suite (groupe.json : \"actif\": false)."
                                      : "Activer " + x.Nom + " ? Elle sera chauffée sur l'historique puis agira au point de décision suivant.";
            if (MessageBox.Show(this, question, "Groupe", MessageBoxButton.YesNo, MessageBoxImage.Question) != MessageBoxResult.Yes) return;
            if (!p.Commande(action, x.Nom))
                MessageBox.Show(this, "Python n'est pas connecté : commande impossible.", "Groupe", MessageBoxButton.OK, MessageBoxImage.Warning);
            sigStrategies = null;
        }

        private void SurArret(object sender, RoutedEventArgs e)
        {
            NexusPasserelle p = NexusPasserelle.EnService;
            if (p == null) return;
            bool actif = p.Instantane().Actif;
            string question = actif ? "Tout arrêter ? Toutes les positions du Groupe sont mises à plat et aucun ordre ne part avant « Reprendre »."
                                    : "Reprendre ? Les stratégies retrouvent leurs positions cibles actuelles.";
            if (MessageBox.Show(this, question, "Groupe", MessageBoxButton.YesNo, actif ? MessageBoxImage.Warning : MessageBoxImage.Question) != MessageBoxResult.Yes) return;
            p.DefinirActif(!actif);
            Rafraichir();
        }
    }
}
