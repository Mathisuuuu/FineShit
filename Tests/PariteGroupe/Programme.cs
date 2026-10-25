// Banc de parite : rejoue des barres 1 minute (t_debut_ms,o,h,l,c,v ; UTC) dans NxS1Logique / NxGotobiLogique et ecrit
// chaque execution simulee (t_debut_ms de la barre d execution, position apres). Memes conventions que le rejeu Python :
//  - S1 : decision a la cloture de la barre, execution a l ouverture de la barre suivante ;
//  - Gotobi : decision au debut de la barre (premiere barre qui commence a l heure prevue), execution a son ouverture ;
//  - M2 : comme S1 (7e colonne des barres : prix ajuste - prix reel, pour le rendement de la veille).
using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using NinjaTrader.NinjaScript.AddOns.Nexus;

static class Programme
{
    static int Main(string[] args)
    {
        if (args.Length < 3) { Console.Error.WriteLine("usage : s1|gotobi|m2 barres.csv ordres.csv [capital.csv]"); return 1; }
        CultureInfo ci = CultureInfo.InvariantCulture;
        DateTime epoque = new DateTime(1970, 1, 1, 0, 0, 0, DateTimeKind.Utc);
        Dictionary<int, double> capital = new Dictionary<int, double>();
        if (args.Length > 3)
            foreach (string l in File.ReadLines(args[3]))
            {
                string[] p = l.Split(',');
                capital[int.Parse(p[0], ci)] = double.Parse(p[1], ci);
            }
        NxS1Logique s1 = new NxS1Logique { ValeurPoint = 20.0 };
        if (capital.Count > 0) s1.CapitalDuJour = d => capital.TryGetValue(NxGroupeCalendrier.Cle(d), out double c) ? c : 1e6;
        NxGotobiLogique g = new NxGotobiLogique { ContratsFixes = 1 };
        NxM2Logique m2 = new NxM2Logique { Contrats = 1 };
        bool estS1 = args[0] == "s1", estM2 = args[0] == "m2";
        int position = 0, enAttente = int.MinValue, n = 0;
        double dernier = double.NaN;
        using (StreamWriter w = new StreamWriter(args[2]))
        {
            w.WriteLine("t,position");
            foreach (string l in File.ReadLines(args[1]))
            {
                string[] p = l.Split(',');
                long t = long.Parse(p[0], ci);
                double o = double.Parse(p[1], ci), h = double.Parse(p[2], ci), lo = double.Parse(p[3], ci), c = double.Parse(p[4], ci), v = double.Parse(p[5], ci);
                DateTime debut = epoque.AddMilliseconds(t);
                n++;
                if (!estS1 && !estM2)
                {
                    foreach (NxDecision x in g.SurInstant(debut, dernier)) enAttente = x.Cible;
                }
                if (enAttente != int.MinValue && enAttente != position)
                {
                    position = enAttente;
                    w.WriteLine(t.ToString(ci) + "," + position.ToString(ci));
                }
                enAttente = int.MinValue;
                if (estS1)
                    foreach (NxDecision x in s1.SurBarre(debut.AddMinutes(1), o, h, lo, c, v)) enAttente = x.Cible;
                if (estM2)
                    foreach (NxDecision x in m2.SurBarre(debut.AddMinutes(1), o, h, lo, c, p.Length > 6 ? double.Parse(p[6], ci) : 0.0)) enAttente = x.Cible;
                dernier = c;
            }
        }
        Console.WriteLine(n + " barres rejouees");
        return 0;
    }
}
