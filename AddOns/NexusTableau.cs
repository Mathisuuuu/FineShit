// =============================================================================
//  NexusTableau.cs   (NinjaTrader 8 / NinjaScript - AddOn)
//
//  Etat du Groupe pour le tableau de bord, ecrit par NinjaTrader lui-meme
//  (les strategies NexusGroupeS1 / NexusGroupeGotobi tournent dans
//  NinjaTrader ; plus de moteur Python ni de passerelle TCP) :
//    - toutes les 2 s : live.json (compte, positions, strategies, executions,
//      journal) dans le dossier "sortie" de Nexus\tableau.json ;
//    - toutes les 15 min : une ligne dans Nexus\groupe\compte.jsonl (valeur
//      liquidative du compte), pour la courbe du compte dans le rapport.
//  Fenetre « Groupe » (Control Center > New > Groupe) : compte, strategies du
//  Groupe (etat, position, cible), journal, bouton Tout arreter / Reprendre
//  (fichier Nexus\KILL_SWITCH : les strategies mettent tout a plat).
//  Activer / desactiver une strategie : onglet Strategies du Control Center.
// =============================================================================

#region Using declarations
using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Linq;
using System.Text;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Media;
using System.Windows.Threading;
using System.Xml.Linq;
using NinjaTrader.Cbi;
using NinjaTrader.Gui.Tools;
using NinjaTrader.NinjaScript;
using NinjaTrader.NinjaScript.AddOns.Nexus;
#endregion

namespace NinjaTrader.NinjaScript.AddOns
{
    /// <summary>Photographie du Groupe (compte + strategies) pour live.json et la fenetre.</summary>
    public class NxTableauInstantane
    {
        public string Compte = "", Verrou = "", Connexion = "";
        public bool CompteTrouve, Simulation, Connecte, Arrete;
        public double ValeurLiquidative = double.NaN, ResultatJour = double.NaN;
        public List<NxTableauStrategie> Strategies = new List<NxTableauStrategie>();
        public Dictionary<string, int> Positions = new Dictionary<string, int>();
        public List<string> Journal = new List<string>();
    }

    public class NxTableauStrategie
    {
        public string Nom = "", NomNinja = "", Statut = "", Instrument = "", Resume = "", EtatJson = "{}";
        public int Cible, Position;
    }

    public class NexusTableau : AddOnBase
    {
        private static readonly object instanceSync = new object();
        private static NexusTableau enService;
        private static readonly CultureInfo Inv = CultureInfo.InvariantCulture;
        private System.Threading.Timer minuterie;
        private string compteNom = "Sim101", sortie;
        private DateTime prochainCompte = DateTime.MinValue, jourLiq = DateTime.MinValue;
        private double liqDebutJour = double.NaN;
        private readonly Queue<string> journal = new Queue<string>();
        private NTMenuItem menuNouveau, menuGroupe;

        public static NexusTableau EnService { get { lock (instanceSync) return enService; } }
        public static string DossierGroupe { get { return Path.Combine(NxPaths.Root, "groupe"); } }

        protected override void OnStateChange()
        {
            if (State == State.SetDefaults)
            {
                Name = "NexusTableau";
                Description = "Etat du Groupe (compte demo, strategies) pour le tableau de bord, et fenetre Groupe.";
            }
            else if (State == State.Active)
            {
                lock (instanceSync) { if (enService != null) return; enService = this; }
                LireConfig();
                minuterie = new System.Threading.Timer(Tic, null, 2000, 2000);
                Journal("tableau du Groupe actif : compte " + compteNom + ", sortie " + sortie);
            }
            else if (State == State.Terminated)
            {
                lock (instanceSync) { if (enService != this) return; enService = null; }
                try { if (minuterie != null) minuterie.Dispose(); } catch { }
            }
        }

        private void LireConfig()
        {
            NxPaths.EnsureAll();
            string f = Path.Combine(NxPaths.Root, "tableau.json");
            string defaut = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.MyDocuments), "FichesEtCode", "Dashboard", "donnees");
            sortie = Directory.Exists(defaut) ? Path.Combine(defaut, "live.json") : Path.Combine(DossierGroupe, "live.json");
            try
            {
                if (!File.Exists(f))
                {
                    File.WriteAllText(f, "{\n  \"compte\": " + NxJson.Q(compteNom) + ",\n  \"sortie\": " + NxJson.Q(sortie) + "\n}\n", new UTF8Encoding(false));
                    return;
                }
                object o;
                if (NxJson.TryParse(File.ReadAllText(f), out o) && o is Dictionary<string, object>)
                {
                    Dictionary<string, object> d = (Dictionary<string, object>)o;
                    object v;
                    if (d.TryGetValue("compte", out v) && !string.IsNullOrWhiteSpace(NxJson.Str(v))) compteNom = NxJson.Str(v).Trim();
                    if (d.TryGetValue("sortie", out v) && !string.IsNullOrWhiteSpace(NxJson.Str(v))) sortie = NxJson.Str(v).Trim();
                }
            }
            catch (Exception ex) { Journal("tableau.json : " + ex.Message); }
        }

        // ------------------------------------------------------------------ photographie
        private Account Compte()
        {
            lock (Account.All) return Account.All.FirstOrDefault(a => a.Name == compteNom);
        }

        private static string Lire(string f) { try { return File.Exists(f) ? File.ReadAllText(f) : null; } catch { return null; } }

        private static List<string> Queue(string f, int n)
        {
            try { return File.Exists(f) ? File.ReadLines(f).Reverse().Take(n).Reverse().ToList() : new List<string>(); } catch { return new List<string>(); }
        }

        public NxTableauInstantane Instantane()
        {
            NxTableauInstantane s = new NxTableauInstantane { Compte = compteNom, Arrete = File.Exists(NxPaths.KillSwitchFile) };
            s.Verrou = s.Arrete ? "interrupteur" : "";
            Account a = Compte();
            if (a != null)
            {
                s.CompteTrouve = true;
                s.Simulation = a.Provider == Provider.Simulator || a.Provider == Provider.Playback
                    || (a.Connection != null && a.Connection.Options != null
                        && (a.Connection.Options.Mode == NinjaTrader.Cbi.Mode.Simulation || a.Connection.Options.IsDemo
                            || (a.Connection.Options.Name == "Simulation" && a.Name.StartsWith("DEMO", StringComparison.OrdinalIgnoreCase))));
                if (a.Connection != null && a.Connection.Options != null)
                    s.Connexion = a.Connection.Options.Name + " | mode=" + a.Connection.Options.Mode + " | demo=" + a.Connection.Options.IsDemo
                        + " | fournisseur=" + a.Provider + " | marque=" + a.Connection.Options.BrandName;
                s.Connecte = a.ConnectionStatus == ConnectionStatus.Connected;
                try { s.ValeurLiquidative = a.Get(AccountItem.NetLiquidation, Currency.UsDollar); } catch { }
                DateTime ny = NxTime.FromUtc(DateTime.UtcNow, NxTime.Eastern);
                DateTime seance = ny.Hour >= 18 ? ny.Date.AddDays(1) : ny.Date;
                if (seance != jourLiq || double.IsNaN(liqDebutJour)) { jourLiq = seance; liqDebutJour = s.ValeurLiquidative; }
                s.ResultatJour = s.ValeurLiquidative - liqDebutJour;
                lock (a.Positions)
                    foreach (Position p in a.Positions)
                        s.Positions[p.Instrument.FullName] = p.MarketPosition == MarketPosition.Long ? p.Quantity : p.MarketPosition == MarketPosition.Short ? -p.Quantity : 0;
            }
            Dictionary<string, string> etats = new Dictionary<string, string>();
            if (a != null)
                lock (a.Strategies)
                    foreach (StrategyBase st in a.Strategies)
                        etats[st.Name] = st.State.ToString();
            if (Directory.Exists(DossierGroupe))
                foreach (string d in Directory.GetDirectories(DossierGroupe))
                {
                    string meta = Lire(Path.Combine(d, "meta.json"));
                    if (meta == null) continue;
                    object mo, eo = null;
                    if (!NxJson.TryParse(meta, out mo) || !(mo is Dictionary<string, object>)) continue;
                    Dictionary<string, object> m = (Dictionary<string, object>)mo;
                    string etat = Lire(Path.Combine(d, "etat.json")) ?? "{}";
                    NxJson.TryParse(etat, out eo);
                    Dictionary<string, object> e = eo as Dictionary<string, object> ?? new Dictionary<string, object>();
                    NxTableauStrategie r = new NxTableauStrategie
                    {
                        Nom = NxJson.Str(V(m, "nom")) ?? Path.GetFileName(d), NomNinja = NxJson.Str(V(m, "strategie_ninja")) ?? "",
                        Instrument = NxJson.Str(V(e, "instrument")) ?? NxJson.Str(V(m, "instrument_negocie")) ?? "", EtatJson = etat,
                        Cible = (int)Num(V(e, "cible")), Position = (int)Num(V(e, "position"))
                    };
                    string st;
                    r.Statut = etats.TryGetValue(r.NomNinja, out st) ? (st == "Realtime" ? "active" : st == "Historical" || st == "Transition" ? "chauffe" : st) : "arretee";
                    r.Resume = string.Join(" · ", e.Where(kv => !(kv.Value is Dictionary<string, object>) && kv.Key != "nom" && kv.Key != "maj_utc" && kv.Key != "instrument")
                                                     .Select(kv => kv.Key.Replace('_', ' ') + " : " + Convert.ToString(kv.Value, Inv)));
                    s.Strategies.Add(r);
                }
            lock (journal) s.Journal = journal.Reverse().ToList();
            return s;
        }

        private static object V(Dictionary<string, object> d, string k) { object v; return d != null && d.TryGetValue(k, out v) ? v : null; }
        private static double Num(object v) { try { return v == null ? 0 : NxJson.Num(v); } catch { return 0; } }

        // ------------------------------------------------------------------ live.json (format de la page « Groupe en direct »)
        private void Tic(object o)
        {
            try
            {
                NxTableauInstantane s = Instantane();
                StringBuilder sb = new StringBuilder();
                DateTime ny = NxTime.FromUtc(DateTime.UtcNow, NxTime.Eastern);
                sb.Append("{\"genere\":").Append(NxJson.Q(ny.ToString("yyyy-MM-dd HH:mm:ss", Inv)));
                sb.Append(",\"source\":\"NinjaTrader (AddOn NexusTableau)\"");
                sb.Append(",\"passerelle\":{\"connecte\":").Append(s.Connecte ? "true" : "false").Append(",\"hello\":true,\"compte\":").Append(NxJson.Q(s.Compte))
                  .Append(",\"compte_trouve\":").Append(s.CompteTrouve ? "true" : "false").Append(",\"simulation\":").Append(s.Simulation ? "true" : "false")
                  .Append(",\"connexion\":").Append(NxJson.Q(s.Connexion)).Append(",\"verrou\":").Append(NxJson.Q(s.Verrou)).Append(",\"valeur_liquidative\":").Append(NxJson.N(s.ValeurLiquidative))
                  .Append(",\"resultat_jour\":").Append(NxJson.N(s.ResultatJour)).Append("},\"suspension\":\"\"");
                sb.Append(",\"strategies\":[").Append(string.Join(",", s.Strategies.Select(x =>
                    "{\"nom\":" + NxJson.Q(x.Nom) + ",\"classe\":" + NxJson.Q(x.NomNinja + " (NinjaScript)") + ",\"statut\":" + NxJson.Q(x.Statut)
                    + ",\"erreur\":\"\",\"cibles\":{" + NxJson.Q(Racine(x.Instrument)) + ":" + x.Cible.ToString(Inv) + "},\"params\":{},\"etat\":" + x.EtatJson
                    + ",\"abonnements\":[" + NxJson.Q(x.Instrument) + "]}"))).Append("]");
                sb.Append(",\"instruments\":{").Append(string.Join(",", s.Strategies.Select(x =>
                {
                    object eo;
                    NxJson.TryParse(x.EtatJson, out eo);
                    Dictionary<string, object> e = eo as Dictionary<string, object>;
                    int pos;
                    s.Positions.TryGetValue(x.Instrument, out pos);
                    return NxJson.Q(Racine(x.Instrument)) + ":{\"cible\":" + x.Cible.ToString(Inv) + ",\"position\":" + pos.ToString(Inv) + ",\"nom\":" + NxJson.Q(x.Instrument)
                           + ",\"pret\":true,\"derniere_barre\":{\"heure\":" + NxJson.Q(NxJson.Str(V(e, "derniere_barre")) ?? "") + ",\"c\":" + NxJson.N(Num(V(e, "dernier_cours"))) + "}}";
                }).Distinct())).Append("}");
                List<string> ex = new List<string>();
                if (Directory.Exists(DossierGroupe))
                    foreach (string d in Directory.GetDirectories(DossierGroupe)) ex.AddRange(Queue(Path.Combine(d, "executions.jsonl"), 50));
                sb.Append(",\"executions\":[").Append(string.Join(",", ex.Where(l => l.StartsWith("{")))).Append("]");
                List<string> dec = new List<string>();
                if (Directory.Exists(DossierGroupe))
                    foreach (string d in Directory.GetDirectories(DossierGroupe)) dec.AddRange(Queue(Path.Combine(d, "decisions.jsonl"), 60));
                sb.Append(",\"journal\":[").Append(string.Join(",", dec.Where(l => l.StartsWith("{")).Select(l =>
                {
                    object jo;
                    NxJson.TryParse(l, out jo);
                    Dictionary<string, object> j = jo as Dictionary<string, object>;
                    long t = (long)Num(V(j, "t"));
                    string h = NxTime.FromUtc(new DateTime(1970, 1, 1, 0, 0, 0, DateTimeKind.Utc).AddMilliseconds(t), NxTime.Eastern).ToString("yyyy-MM-dd HH:mm:ss", Inv);
                    return "{\"t\":" + t.ToString(Inv) + ",\"heure\":" + NxJson.Q(h) + ",\"strategie\":" + NxJson.Q(NxJson.Str(V(j, "strategie")) ?? "")
                           + ",\"texte\":" + NxJson.Q("cible " + Convert.ToString(V(j, "cible"), Inv) + " : " + (NxJson.Str(V(j, "motif")) ?? "")) + "}";
                }).OrderBy(x => x))).Append("]}");
                Directory.CreateDirectory(Path.GetDirectoryName(sortie));
                File.WriteAllText(sortie + ".tmp", sb.ToString(), new UTF8Encoding(false));
                File.Copy(sortie + ".tmp", sortie, true);
                File.Delete(sortie + ".tmp");
                if (DateTime.UtcNow >= prochainCompte && !double.IsNaN(s.ValeurLiquidative))
                {
                    prochainCompte = DateTime.UtcNow.AddMinutes(15);
                    Directory.CreateDirectory(DossierGroupe);
                    File.AppendAllText(Path.Combine(DossierGroupe, "compte.jsonl"),
                        "{\"type\":\"compte\",\"compte\":" + NxJson.Q(s.Compte) + ",\"valeur_liquidative\":" + NxJson.N(s.ValeurLiquidative)
                        + ",\"resultat_jour\":" + NxJson.N(s.ResultatJour) + ",\"heure_et\":" + NxJson.Q(ny.ToString("yyyy-MM-dd HH:mm:ss", Inv)) + "}\n", new UTF8Encoding(false));
                }
            }
            catch (Exception ex) { Journal("ecriture de l etat impossible : " + ex.Message); }
        }

        private static string Racine(string nom) { return string.IsNullOrEmpty(nom) ? "" : nom.Split(' ')[0]; }

        public void DefinirArret(bool arreter)
        {
            try
            {
                if (arreter) File.WriteAllText(NxPaths.KillSwitchFile, "Tout arreter (fenetre Groupe) " + DateTime.Now.ToString("o", Inv));
                else if (File.Exists(NxPaths.KillSwitchFile)) File.Delete(NxPaths.KillSwitchFile);
                Journal(arreter ? "TOUT ARRETER : les strategies du Groupe mettent tout a plat" : "Groupe repris");
            }
            catch (Exception ex) { Journal("interrupteur : " + ex.Message); }
        }

        private void Journal(string msg)
        {
            string l = DateTime.Now.ToString("yyyy-MM-dd HH:mm:ss", Inv) + "  " + msg;
            lock (journal) { journal.Enqueue(l); while (journal.Count > 60) journal.Dequeue(); }
            try { Print("[NexusTableau] " + msg); } catch { }
        }

        // ------------------------------------------------------------------ menu
        protected override void OnWindowCreated(Window window)
        {
            NinjaTrader.Gui.ControlCenter cc = window as NinjaTrader.Gui.ControlCenter;
            if (cc == null) return;
            NTMenuItem nouveau = cc.FindFirst("ControlCenterMenuItemNew") as NTMenuItem;
            if (nouveau == null) return;
            foreach (object o in nouveau.Items) { NTMenuItem x = o as NTMenuItem; if (x != null && (x.Tag as string) == "NexusGroupe") return; }
            menuNouveau = nouveau;
            menuGroupe = new NTMenuItem { Header = "Groupe", Tag = "NexusGroupe", Style = Application.Current.TryFindResource("MainMenuItem") as Style };
            menuGroupe.Click += (s, e) => NinjaTrader.Core.Globals.RandomDispatcher.BeginInvoke(new Action(() => new NexusGroupeFenetre().Show()));
            nouveau.Items.Add(menuGroupe);
        }

        protected override void OnWindowDestroyed(Window window)
        {
            if (menuGroupe == null || !(window is NinjaTrader.Gui.ControlCenter)) return;
            if (menuNouveau != null && menuNouveau.Items.Contains(menuGroupe)) menuNouveau.Items.Remove(menuGroupe);
            menuGroupe = null;
            menuNouveau = null;
        }
    }

    /// <summary>Fenetre « Groupe » (Control Center > New > Groupe).</summary>
    public class NexusGroupeFenetre : NTWindow, IWorkspacePersistence
    {
        private static readonly CultureInfo Fr = CultureInfo.GetCultureInfo("fr-FR");
        private readonly TextBlock titre, ligne1, ligne2, alerte;
        private readonly Button bouton;
        private readonly Grid grille;
        private readonly TextBox journal;
        private readonly DispatcherTimer minuterie;
        private readonly Brush texte;
        private string signature;

        public NexusGroupeFenetre()
        {
            Caption = "Groupe";
            Width = 900;
            Height = 600;
            Brush theme = Application.Current.TryFindResource("FontControlBrush") as Brush;
            texte = theme != null && theme.IsFrozen ? theme : null;
            StackPanel racine = new StackPanel { Margin = new Thickness(14) };
            titre = T("Groupe", 18, true);
            ligne1 = T("", 13, false);
            ligne2 = T("", 13, false);
            alerte = T("", 13, true);
            alerte.Foreground = Brushes.OrangeRed;
            foreach (TextBlock t in new[] { titre, ligne1, ligne2, alerte }) racine.Children.Add(t);
            bouton = new Button { Content = "Tout arrêter", Padding = new Thickness(14, 4, 14, 4), Margin = new Thickness(0, 10, 0, 6), HorizontalAlignment = HorizontalAlignment.Left };
            bouton.Click += SurBouton;
            racine.Children.Add(bouton);
            racine.Children.Add(T("Stratégies du Groupe (activer / désactiver : onglet Strategies du Control Center)", 14, true, new Thickness(0, 12, 0, 4)));
            grille = new Grid();
            racine.Children.Add(grille);
            racine.Children.Add(T("Journal", 14, true, new Thickness(0, 14, 0, 4)));
            journal = new TextBox { IsReadOnly = true, Height = 160, TextWrapping = TextWrapping.Wrap, VerticalScrollBarVisibility = ScrollBarVisibility.Auto,
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

        private TextBlock T(string t, double taille, bool gras, Thickness? marge = null)
        {
            TextBlock b = new TextBlock { Text = t, FontSize = taille, TextWrapping = TextWrapping.Wrap, Margin = marge ?? new Thickness(0, 2, 0, 2) };
            if (gras) b.FontWeight = FontWeights.SemiBold;
            if (texte != null) b.Foreground = texte;
            return b;
        }

        private void Rafraichir()
        {
            NexusTableau a = NexusTableau.EnService;
            if (a == null) { ligne1.Text = "AddOn NexusTableau non démarré (compiler avec F5)."; return; }
            NxTableauInstantane s = a.Instantane();
            titre.Text = s.Arrete ? "Groupe — ARRÊTÉ" : "Groupe";
            ligne1.Text = "Compte : " + s.Compte + (s.CompteTrouve ? (s.Simulation ? " (simulation)" : " (RÉEL)") : " (introuvable)")
                          + "   ·   connexion : " + (s.Connecte ? "connectée" : "déconnectée");
            ligne2.Text = "Valeur liquidative : " + (double.IsNaN(s.ValeurLiquidative) ? "–" : s.ValeurLiquidative.ToString("N0", Fr) + " $")
                          + "   ·   résultat depuis 18:00 ET : " + (double.IsNaN(s.ResultatJour) ? "–" : s.ResultatJour.ToString("N0", Fr) + " $");
            alerte.Text = s.Arrete ? "Tout arrêté : les stratégies du Groupe restent à plat jusqu'à « Reprendre »." : "";
            alerte.Visibility = s.Arrete ? Visibility.Visible : Visibility.Collapsed;
            bouton.Content = s.Arrete ? "Reprendre" : "Tout arrêter";
            string sig = string.Join("|", s.Strategies.Select(x => x.Nom + x.Statut + x.Cible + x.Position + x.Resume));
            if (sig != signature)
            {
                signature = sig;
                grille.Children.Clear();
                grille.RowDefinitions.Clear();
                grille.ColumnDefinitions.Clear();
                foreach (double w in new double[] { 110, 110, 150, 90, 90, 0 })
                    grille.ColumnDefinitions.Add(new ColumnDefinition { Width = w > 0 ? new GridLength(w) : new GridLength(1, GridUnitType.Star) });
                string[] tetes = { "Stratégie", "Statut", "Instrument", "Cible", "Position", "État" };
                Ligne(0, tetes, true);
                int i = 1;
                foreach (NxTableauStrategie x in s.Strategies)
                    Ligne(i++, new[] { x.Nom, x.Statut, x.Instrument, x.Cible.ToString(Fr), x.Position.ToString(Fr), x.Resume }, false);
                if (i == 1) Ligne(1, new[] { "(aucune stratégie du Groupe n'a encore démarré)", "", "", "", "", "" }, false);
            }
            string j = string.Join(Environment.NewLine, s.Journal);
            if (journal.Text != j) journal.Text = j;
        }

        private void Ligne(int r, string[] valeurs, bool gras)
        {
            grille.RowDefinitions.Add(new RowDefinition { Height = GridLength.Auto });
            for (int k = 0; k < valeurs.Length; k++)
            {
                TextBlock b = T(valeurs[k], 12.5, gras);
                b.Margin = new Thickness(0, 3, 10, 3);
                Grid.SetRow(b, r);
                Grid.SetColumn(b, k);
                grille.Children.Add(b);
            }
        }

        private void SurBouton(object sender, RoutedEventArgs e)
        {
            NexusTableau a = NexusTableau.EnService;
            if (a == null) return;
            bool arrete = a.Instantane().Arrete;
            string q = arrete ? "Reprendre ? Les stratégies retrouvent leur position voulue." : "Tout arrêter ? Les stratégies du Groupe mettent tout à plat et n'ouvrent plus rien.";
            if (MessageBox.Show(this, q, "Groupe", MessageBoxButton.YesNo, MessageBoxImage.Question) != MessageBoxResult.Yes) return;
            a.DefinirArret(!arrete);
            Rafraichir();
        }
    }
}
