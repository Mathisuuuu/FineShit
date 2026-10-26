"""Strategies publiees par l equipe et les membres du serveur Kairos, testees TELLES QUE PUBLIEES : TROIS essais,
n° 438, 439 et 440 (critere 1 assoupli le 2026-10-25 : familles de praticiens testables sans papier).

    python -m nexus.perso.kairos_publiees [--sortie resultats_kairos_publiees.txt]

PROTOCOLE ECRIT LE 2026-10-25 AVANT LE CALCUL. Les regles sont celles publiees par leurs auteurs (aucun parametre
choisi par nous) ; la ou le texte publie laisse un choix, il est fixe ici avant le calcul et note « (choix) ».

Sources (serveur Discord Kairos, lu le 2026-10-25 ; resumes seulement, le serveur interdit la redistribution)
  - n° 346 du registre : « IntradayVolBreakout_NQ15 », strategie gratuite de l equipe (annonce du 14/07, en-tete du
    code NinjaTrader lu). Leur test : MNQ 2021 -> 2026-07, 2 ticks + 2 $ par aller-retour, PF 1,30 ; 2024-2025 :
    1,46. L equipe dit utiliser une version modifiee non publiee ; on teste la version publiee.
  - n° 347 : « NQ 5 min momentum » d un membre (supe, forum strategies). Variante C (sans stop) : PF 1,12, Sharpe 0,55,
    t de permutation 2,16 sur leurs donnees. Variante M2 : filtre ajoute APRES avoir vu les resultats (1 272 trades
    2013-2026, PF 1,52) ; nos donnees 2016-2026 sont DANS leur periode : M2 n est pas un test hors echantillon.
  - Site kairosterminal.live (lu le 2026-10-25) : « Kairos Max » = cassure d ouverture sans stop sur MNQ, MES, M2K,
    MYM, MGC, MCL, coupure de perte journaliere, a plat a 16:59 ; duree du range, declencheur et filtres NON publies :
    pas testable sans inventer les regles (pas d essai).
  Pas de calcul de puissance : aucun effet publie en points de base sur le meme objet (seulement des PF).
  Trois essais : ESSAIS_PROGRAMME 437 -> 440 (repliques et micros ne sont pas des essais).

Regles figees (heures de New York, barres 1 minute agregees ; « barre de H » = celle qui COMMENCE a H)
  K3 (essai 438) - IntradayVolBreakout, NQ (micro MNQ ; repliques ES, GC, pas des essais) :
    ancre = ouverture de la barre de 9:30 ; ATR(5) des barres journalieres de seance CME (18:00-17:00, lissage de
    Wilder comme l ATR de NinjaTrader (choix)) arrete a la veille ; filtre « jour calme » : vrai range de la veille
    < 1,0 x ATR(5) de la veille, sinon pas de trade ; controles sur les clotures 15 min de 9:45, 10:00 ... 11:00 :
    achat si cloture > ancre + 0,25 x ATR, vente si cloture < ancre - 0,25 x ATR ; entree a l ouverture de la barre
    suivante (choix : ordre au marche apres la cloture) ; stop a 0,25 x ATR du prix d entree ; un trade par jour ;
    sortie a l ouverture de la barre de 15:55.
  K4 (essai 439) - momentum 5 min de 9:30, variante C, NQ (micro MNQ ; replique ES) :
    barres 5 minutes continues (heures etendues), EMA(12) des clotures ; achat si la cloture de la barre 9:30-9:35
    > EMA(12) a cette barre, vente sinon ; entree a l ouverture de la barre de 9:35, sortie a l ouverture de celle de
    15:55, sans stop ; tous les jours de bourse.
  K5 (essai 440) - meme regle, filtre M2 de l auteur : ne trader que si |cloture - EMA| / ATR(14) > 2,2 (ATR de Wilder
    des barres 5 min (choix : meme graphique)) OU si le rendement de la veille 9:35 -> 15:55, dans le sens du signal
    du jour, est < -60 pb.
  Jour exclu : prix absent, changement d echeance entre l entree et la sortie, donnees manquantes pour le signal.
  Execution du stop : a son niveau, ou a l ouverture de la barre si elle s ouvre au-dela ; verifie des la barre d entree.
  Conformite prop (critere 21) : a plat avant 16:10, pas de week-end. Conflit de contrat (critere 19) : les trois
  tiennent NQ de 9:35-11:00 a 15:55, comme S1 (MNQ) : a remplacer S1 dans le compte, pas a ajouter.
  Temoin neutre (critere 12) : memes jours, meme instant d entree, sortie 15:55 sans stop, sens tire au hasard
  (graine 7). Pour K4 (sans stop, tous les jours) le temoin a la meme exposition exacte, seul le sens differe.
Couts (critere 8) : 1 tick + 2,50 $ par cote (stress 2 ticks) ; micros au meme tarif par cote.
Criteres : n° 10-14 (criteres() de soixante), n° 16-18 (mesures() de prop_combinaisons, Sharpe deflate avec 438, 439,
  440 essais), n° 19 (heures par an), n° 20 (correlation avec S1 et Gotobi) seulement si le reste passe.
Verification du calcul (critere 9, sans regarder le gain) : (a) horodatage (volume a 9:30) ; (b) anticipation : sur
  200 jours, prix des barres posterieures a l instant d entree x1,5 dans une fenetre de 40 jours -> sens, heure et prix
  d entree inchanges ; (c) rejeu vectorbt = P&L brut du moteur trade par trade ; (d) 5 trades au hasard (graine 7) ;
  (e) comptes.
"""
from __future__ import annotations

import argparse
import math
import os
from datetime import datetime

import numpy as np
import pandas as pd

from .. import prop_combinaisons as PC
from .kairos_jambes import cout_pb, serie_journaliere, verif_cinq, verif_vectorbt
from .or_anomalies import instants
from .ouverture_europe import correlations
from .soixante import COUTS, ET, NS_MIN, PY_DIR, contrats, criteres, jours_ouvres_us, marche

NS_5 = 5 * NS_MIN
REGLES = {
    "K3": dict(nom="IntradayVolBreakout (strategie gratuite Kairos)", essai=438, repliques=["ES", "GC"]),
    "K4": dict(nom="Momentum 5 min de 9:30, variante C (sans stop)", essai=439, repliques=["ES"]),
    "K5": dict(nom="Momentum 5 min de 9:30, filtre M2 (ajoute apres coup par l auteur)", essai=440, repliques=["ES"]),
}


class Fenetre:
    """Tranche d un marche (test d anticipation) avec des prix eventuellement modifies."""

    def __init__(self, m, a: int, b: int, o=None, h=None, l=None, c=None):
        self.root = m.root
        self.t = m.t[a:b]
        self.n = b - a
        self.o = (m.o if o is None else o)[a:b]
        self.h = (m.h if h is None else h)[a:b]
        self.l = (m.l if l is None else l)[a:b]
        self.c = (m.c if c is None else c)[a:b]
        self.v = m.v[a:b]
        self.offset = m.offset[a:b]
        self.rc = m.rc[a:b]
        self._contrat = contrats(m)[a:b]


# =============================================================================
#  Indicateurs (causaux)
# =============================================================================
def wilder(x: np.ndarray, n: int) -> np.ndarray:
    return pd.Series(x).ewm(alpha=1.0 / n, adjust=False).mean().to_numpy()


def journalieres(m) -> pd.DataFrame:
    """Barres de seance CME (18:00-17:00 ET), indexees par la date ET de la seance, vrai range et ATR(5) de Wilder."""
    et = pd.DatetimeIndex(m.t - NS_MIN).tz_localize("UTC").tz_convert(ET).tz_localize(None)
    seance = (et + pd.Timedelta(hours=6)).normalize()
    df = pd.DataFrame({"h": m.h, "l": m.l, "c": m.c}, index=seance)
    g = df.groupby(level=0).agg(h=("h", "max"), l=("l", "min"), c=("c", "last"))
    prev = g["c"].shift(1)
    g["tr"] = np.maximum(g["h"], prev.fillna(g["h"])) - np.minimum(g["l"], prev.fillna(g["l"]))
    g["atr5"] = wilder(g["tr"].to_numpy(), 5)
    return g


def barres5(m) -> pd.DataFrame:
    """Barres 5 minutes continues : cloture, EMA(12), ATR(14) de Wilder ; index = debut de barre (ns UTC)."""
    debut = (m.t - NS_MIN) // NS_5 * NS_5
    df = pd.DataFrame({"h": m.h, "l": m.l, "c": m.c}, index=debut)
    b = df.groupby(level=0).agg(h=("h", "max"), l=("l", "min"), c=("c", "last"))
    prev = b["c"].shift(1)
    tr = np.maximum(b["h"], prev.fillna(b["h"])) - np.minimum(b["l"], prev.fillna(b["l"]))
    b["ema12"] = b["c"].ewm(span=12, adjust=False).mean()
    b["atr14"] = wilder(tr.to_numpy(), 14)
    return b


# =============================================================================
#  Moteur
# =============================================================================
def _barre_debut(m, t: int) -> int:
    """Indice de la barre qui commence a t, ou -1."""
    k = int(np.searchsorted(m.t, t + NS_MIN))
    return k if k < m.n and m.t[k] == t + NS_MIN else -1


def _cloture_a(m, t: int) -> float:
    """Cloture de la barre qui finit a t (ou de la derniere finie dans les 5 minutes)."""
    j = int(np.searchsorted(m.t, t, side="right")) - 1
    return m.c[j] if j >= 0 and m.t[j] > t - 5 * NS_MIN else math.nan


def _tenir(m, sens, ie, stop, isx):
    """Position de ie (inclus) a isx (sortie a l ouverture) avec un stop eventuel -> (i_sortie, prix, raison)."""
    if stop is not None:
        for q in range(ie, isx):
            if sens > 0 and m.l[q] <= stop:
                return q, (min(m.o[q], stop) if q > ie else stop), "stop"
            if sens < 0 and m.h[q] >= stop:
                return q, (max(m.o[q], stop) if q > ie else stop), "stop"
    return isx, m.o[isx], "heure"


def trades(m, cle: str, seul=None) -> pd.DataFrame:
    tous = jours_ouvres_us(m)
    tous = tous[tous > pd.Timestamp(m.t[0], unit="ns").normalize() + pd.Timedelta(days=5)]
    cid = contrats(m)
    r_hier = {}
    if cle == "K5":                                    # rendement 9:35 -> 15:55 de la veille (jour de bourse precedent)
        prec = None
        for d, a_, b_ in zip(tous, instants(tous, 9, 35, ET), instants(tous, 15, 55, ET)):
            r_hier[d] = prec
            ia, ib = _barre_debut(m, a_), _barre_debut(m, b_)
            prec = (math.log((m.o[ib] - m.offset[ib]) / (m.o[ia] - m.offset[ia]))
                    if ia >= 0 and ib >= 0 and cid[ia] == cid[ib] else None)
    jours = tous if seul is None else tous[tous == seul]
    rng = np.random.default_rng(7)
    sens_temoin = dict(zip(jours_ouvres_us(m), rng.choice([-1, 1], size=len(jours_ouvres_us(m)))))
    t_ouv, t_935, t_1555 = instants(jours, 9, 30, ET), instants(jours, 9, 35, ET), instants(jours, 15, 55, ET)
    if cle == "K3":
        g = journalieres(m)
        controles = [instants(jours, 9 + (30 + 15 * k) // 60, (30 + 15 * k) % 60, ET) for k in range(1, 7)]
    else:
        b = barres5(m)
    lignes = []
    for k, d in enumerate(jours):
        row, motif, tr = dict(jour=d), "", None
        isx = _barre_debut(m, t_1555[k])
        if isx < 0:
            motif = "prix absent a la sortie"
        elif cle == "K3":
            io = _barre_debut(m, t_ouv[k])
            hier = g.index[g.index < d]
            if io < 0 or len(hier) < 6:
                motif = "donnees manquantes"
            else:
                atr, tr_h = g["atr5"].loc[hier[-1]], g["tr"].loc[hier[-1]]
                if not tr_h < atr:
                    motif = "jour agite (filtre)"
                else:
                    ancre = m.o[io]
                    for tc in (c[k] for c in controles):
                        px = _cloture_a(m, tc)
                        s = 1 if px > ancre + 0.25 * atr else (-1 if px < ancre - 0.25 * atr else 0)
                        if s:
                            ie = _barre_debut(m, tc)
                            if ie < 0:
                                break
                            pe = m.o[ie]
                            tr = (s, ie, pe) + _tenir(m, s, ie, pe - s * 0.25 * atr, isx)
                            break
                    if tr is None and not motif:
                        motif = "pas de signal"
        else:
            i5 = (t_ouv[k] // NS_5) * NS_5
            ie = _barre_debut(m, t_935[k])
            if i5 not in b.index or ie < 0:
                motif = "donnees manquantes"
            else:
                c5, ema, atr = b.at[i5, "c"], b.at[i5, "ema12"], b.at[i5, "atr14"]
                s = 1 if c5 > ema else -1
                ok = True
                if cle == "K5":
                    rh = r_hier.get(d)
                    ok = (abs(c5 - ema) / atr > 2.2) or (rh is not None and s * rh < -0.006)
                if ok:
                    tr = (s, ie, m.o[ie]) + _tenir(m, s, ie, None, isx)
                else:
                    motif = "filtre M2"
        if tr is not None and cid[tr[3]] != cid[tr[1]]:
            motif, tr = "changement d echeance", None
        row["motif"] = motif
        if tr is not None:
            s, ie, pe, q, ps, raison = tr
            re_, rs = pe - m.offset[ie], ps - m.offset[q]
            tem = sens_temoin[d] * math.log((m.o[isx] - m.offset[isx]) / re_)
            row.update(sens=s, t_entree=int(m.t[ie] - NS_MIN), t_sortie=int(m.t[q] - NS_MIN), pe=re_, ps=rs, raison=raison,
                       brut_pb=s * math.log(rs / re_) * 1e4, temoin_pb=tem * 1e4, minutes=(m.t[q] - m.t[ie]) / NS_MIN, ie=ie)
        lignes.append(row)
    return pd.DataFrame(lignes).set_index("jour")


# =============================================================================
#  Verifications (critere 9)
# =============================================================================
def verif_horodatage(m) -> str:
    debut = pd.DatetimeIndex(m.t - NS_MIN).tz_localize("UTC").tz_convert(ET)
    tod = np.asarray(debut.hour * 60 + debut.minute)
    sel = debut.dayofweek < 5
    vol = pd.Series(m.v[sel]).groupby(tod[sel]).median()
    k = 9 * 60 + 30
    return f"(a) horodatage : volume median de la barre de 9:30 = x{vol.get(k) / vol.reindex([k - 3, k - 2, k - 1]).mean():.1f} les 3 precedentes"


def verif_anticipation(m, cle: str, f: pd.DataFrame) -> str:
    t = f[f["motif"] == ""].sample(200, random_state=3)
    diff = 0
    for d in t.itertuples():
        a = max(0, int(d.ie) - 40 * 1380)
        b_ = min(m.n, int(d.ie) + 1380)
        base = trades(Fenetre(m, a, b_), cle, seul=d.Index)
        fut = (m.t - NS_MIN) > d.t_entree
        o2, h2, l2, c2 = (np.where(fut, x * 1.5, x) for x in (m.o, m.h, m.l, m.c))
        modif = trades(Fenetre(m, a, b_, o2, h2, l2, c2), cle, seul=d.Index)
        if len(base) != 1 or len(modif) != 1:
            diff += 1
            continue
        x, y = base.iloc[0], modif.iloc[0]
        if not (x["motif"] == y["motif"] == "" and x["t_entree"] == y["t_entree"] and x["sens"] == y["sens"]
                and math.isclose(x["pe"], y["pe"], abs_tol=1e-9)):
            diff += 1
    etat = "INCHANGES" if diff == 0 else f"DIFFERENTS (BUG : {diff} jours)"
    return f"(b) anticipation : prix apres l entree x1,5 sur 200 jours (fenetre de 40 jours) -> sens, heure et prix d entree {etat}"


# =============================================================================
#  Etude
# =============================================================================
def etude(sortie: str | None = None, log=print) -> dict:
    t0 = datetime.now()
    L: list[str] = []
    pr = L.append
    pr("=" * 116)
    pr(" STRATEGIES PUBLIEES SUR LE SERVEUR KAIROS, TESTEES TELLES QUE PUBLIEES - TROIS ESSAIS (n° 438, 439, 440)")
    pr("=" * 116)
    pr("K3 : IntradayVolBreakout (gratuite, equipe Kairos) ; K4 : momentum 5 min de 9:30, variante C ; K5 : filtre M2.")
    pr("Kairos Max (site) : regles non publiees, non testable. Temoin : meme entree, sortie 15:55, sens au hasard.\n")
    marches = {}
    res = {}
    for cle, p in REGLES.items():
        for root in ["NQ"] + p["repliques"]:
            m = marches.setdefault(root, marche(root))
            f = trades(m, cle)
            ok = f[f["motif"] == ""]
            prix = float(np.nanmedian(ok["pe"]))
            c1, c2, cm = cout_pb(root, prix), cout_pb(root, prix, ticks=2), cout_pb(root, prix, micro=True)
            crit = criteres(ok["brut_pb"], ok["temoin_pb"], c1)
            r = serie_journaliere(f, c1)
            x = PC.mesures(r, p["essai"])
            xm = PC.mesures(serie_journaliere(f, cm), p["essai"])
            ans = (f.index[-1] - f.index[0]).days / 365.25
            res[(cle, root)] = dict(f=f, crit=crit, mesures=x, micro=xm, cout=c1, stress=c2, cout_micro=cm, r=r,
                                    heures_an=float(ok["minutes"].sum() / 60 / ans))
    pr("Verification du calcul (critere 9)")
    nq = marches["NQ"]
    pr("  " + verif_horodatage(nq))
    for cle in REGLES:
        f = res[(cle, "NQ")]["f"]
        ok = f[f["motif"] == ""]
        ans = (f.index[-1] - f.index[0]).days / 365.25
        pr(f"  {cle} (NQ)")
        pr("    " + verif_anticipation(nq, cle, f))
        pr("    " + verif_vectorbt("NQ", f))
        for s in verif_cinq("NQ", f):
            pr("    " + s)
        motifs = f["motif"].replace("", "trade").value_counts()
        pr(f"    (e) comptes : {len(f)} jours {f.index[0]:%Y-%m-%d} -> {f.index[-1]:%Y-%m-%d} ; "
           + " ; ".join(f"{k} {v}" for k, v in motifs.items())
           + f" ; sorties au stop {int((ok['raison'] == 'stop').sum())} ; achats {int((ok['sens'] > 0).sum())} ; "
           f"{len(ok) / ans:.0f} trades par an, {res[(cle, 'NQ')]['heures_an']:.0f} h/an")
    pr("")
    for (cle, root), z in res.items():
        p = REGLES[cle]
        crit, x, xm, c1, c2, cm = z["crit"], z["mesures"], z["micro"], z["cout"], z["stress"], z["cout_micro"]
        net = z["f"].loc[z["f"]["motif"] == "", "brut_pb"] - c1
        essai = root == "NQ"
        micro = {"NQ": "MNQ", "ES": "MES", "GC": "MGC"}[root]
        pr(f"--- {cle} {p['nom']} - {root}{' (ESSAI n° ' + str(p['essai']) + ')' if essai else ' (replique, pas un essai)'} : "
           f"{crit['n']} trades")
        pr(f"    brut {crit['moyenne']:+.2f} pb (t {crit['t']:+.2f}) | 2016-2020 {crit['m1']:+.2f} (t {crit['t1']:+.2f}) | "
           f"2021-2026 {crit['m2']:+.2f} (t {crit['t2']:+.2f})")
        pr(f"    temoin (sens au hasard) {crit['temoin']:+.2f} pb -> Welch {crit['welch']:+.2f}")
        pr(f"    cout aller-retour {c1:.2f} pb -> net {crit['net']:+.2f} pb ; sans les 3 meilleurs jours {crit['sans3']:+.2f} pb ; "
           f"stress 2 ticks {crit['moyenne'] - c2:+.2f} pb")
        an = net.groupby(net.index.year).mean()
        pr("    net par annee (pb) : " + " ".join(f"{a}:{v:+.1f}" for a, v in an.items()))
        pr(f"    vectorbt ({root}, 1 tick) : Sharpe {x['sharpe']:+.2f} [IC 95 % {x['ic_bas']:+.2f} ; {x['ic_haut']:+.2f}] | "
           f"avant 2021 {x['sharpe_p1']:+.2f} | apres {x['sharpe_p2']:+.2f} | deflate ({p['essai']} essais) {x['dsr']:.2f} | "
           f"perte max {x['perte_max']:.1%}")
        pr(f"    micro {micro} (cout {cm:.2f} pb) : net {crit['moyenne'] - cm:+.2f} pb | Sharpe {xm['sharpe']:+.2f} "
           f"[IC bas {xm['ic_bas']:+.2f}] | deflate {xm['dsr']:.2f}")
        pr(f"    heures en position : {z['heures_an']:.0f} h/an")
        echecs = [k for k, v in crit["tests"].items() if not v]
        if not (x["ic_bas"] > 0):
            echecs.append("IC bas du Sharpe > 0")
        if not (x["sharpe_p1"] > 0 and x["sharpe_p2"] > 0):
            echecs.append("Sharpe > 0 avant ET apres 2021")
        if not (x["dsr"] >= 0.95):
            echecs.append("Sharpe deflate >= 0,95")
        z["echecs"] = echecs
        pr(f"    VERDICT : {'PASSE les criteres 10-18' if not echecs else 'ECHOUE (' + ' ; '.join(echecs) + ')'}")
        if not echecs:
            pr("    " + correlations(z["r"]))
        pr("")
    for cle in REGLES:
        v = res[(cle, "NQ")]["echecs"]
        pr(f"Synthese {cle} : " + ("passe les criteres 10-18 ; restent la correlation (n° 20) et la validation."
                                   if not v else "REJETEE. Aucune variante ne sera testee (pas de surajustement)."))
    pr(f"Calcul en {(datetime.now() - t0).total_seconds():.0f} s.")
    sortie = sortie or os.path.join(PY_DIR, "recherche", "resultats_kairos_publiees.txt")
    with open(sortie, "w", encoding="utf-8") as fh:
        fh.write("\n".join(L) + "\n")
    log("\n".join(L))
    return res


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--sortie", default=None)
    a = ap.parse_args(argv)
    etude(a.sortie)


if __name__ == "__main__":
    main()


# =============================================================================
#  Repliques supplementaires de M2 (2026-10-25, apres le calcul ; PAS des essais)
# =============================================================================
def repliques_m2(roots=("YM", "GC", "ES"), sortie: str | None = None, log=print) -> dict:
    """Regle K5 telle quelle sur des marches que l auteur n a pas utilises pour fixer ses seuils (il a regle M2 sur
    NQ) : test d independance partiel. Memes couts, memes criteres ; aucun nouvel essai, aucun reglage."""
    L: list[str] = []
    pr = L.append
    pr("Repliques de K5 (momentum 5 min, filtre M2) hors NQ - pas des essais (deflate avec 440 essais)")
    out = {}
    for root in roots:
        m = marche(root)
        f = trades(m, "K5")
        ok = f[f["motif"] == ""]
        prix = float(np.nanmedian(ok["pe"]))
        c1, cm = cout_pb(root, prix), cout_pb(root, prix, micro=True)
        crit = criteres(ok["brut_pb"], ok["temoin_pb"], c1)
        x = PC.mesures(serie_journaliere(f, c1), 440)
        xm = PC.mesures(serie_journaliere(f, cm), 440)
        out[root] = dict(crit=crit, mesures=x, micro=xm)
        pr(f"  {root} : {crit['n']} trades, net {crit['net']:+.2f} pb (t {crit['t']:+.2f} ; 2016-2020 t {crit['t1']:+.2f}, "
           f"2021-2026 t {crit['t2']:+.2f}), Welch {crit['welch']:+.2f} | Sharpe {x['sharpe']:+.2f} [{x['ic_bas']:+.2f} ; "
           f"{x['ic_haut']:+.2f}], avant / apres 2021 {x['sharpe_p1']:+.2f} / {x['sharpe_p2']:+.2f}, deflate {x['dsr']:.2f} | "
           f"micro Sharpe {xm['sharpe']:+.2f}")
    sortie = sortie or os.path.join(PY_DIR, "recherche", "resultats_kairos_m2_repliques.txt")
    with open(sortie, "w", encoding="utf-8") as fh:
        fh.write("\n".join(L) + "\n")
    log("\n".join(L))
    return out
