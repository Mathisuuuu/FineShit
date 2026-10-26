"""Jambes du book Kairos testees sans papier (critere 1 assoupli le 2026-10-25) : DEUX essais, n° 436 et 437.

    python -m nexus.perso.kairos_jambes [--sortie resultats_kairos_jambes.txt]

PROTOCOLE ECRIT LE 2026-10-25 AVANT LE CALCUL. Aucun parametre n est choisi apres avoir vu un resultat.

Origine (registre n° 344 et 345, serveur Discord de l equipe Kairos, lu le 2026-10-25)
  Leur book = 8-9 strategies simples (≈ 4 NQ, 3 or, 1 ES). Deux familles y sont nommees sans regle publiee :
    - n° 344 : or, « variante de la cassure Asie -> Londres » (range de la seance asiatique, cassure a l ouverture de
      Londres) ;
    - n° 345 : cassure de l « initial balance » (range de la 1re heure de New York) avec une mesure de « force » non
      publiee, environ 3 trades par semaine.
  Le filtre de « force » n etant pas publie, on teste la cassure SIMPLE, aux heures standard des praticiens. Aucun
  chiffre d effet mesure sur le meme objet : pas de calcul de puissance (critere 6 : « quand un chiffre existe » ; le
  blog MQL5 sur XAUUSD, PF 1,38 sur 715 trades, n est ni revu ni sur le future).
  Papier contraire connu : Fetna 2026 (SSRN 7428398, registre n° 122) : aucune cassure d ouverture simple ne survit
  aux couts sur 9 futures americains en 16 ans. Nos repliques de l ORB sur ES et YM ont deja echoue (n° 45).
  Deux essais : ESSAIS_PROGRAMME 435 -> 437 (repliques et micros ne sont pas des essais).

Regles figees (heures de New York, barres 1 minute ; une barre « a l heure H » est celle qui COMMENCE a H)
  K1 (essai 436) - or, cassure Asie -> Londres, GC (micro MGC) :
    range = plus haut et plus bas des barres de 19:00 (la veille au soir) a 03:00 ; fenetre d entree 03:00 -> 08:00 :
    ordre stop d achat au plus haut + 1 tick et de vente au plus bas - 1 tick, le premier touche annule l autre (un
    trade par jour) ; stop de protection a l autre borne du range ; sortie a l ouverture de la barre de 11:30
    (fermeture de Londres) si le stop n est pas touche. Matins du lundi au vendredi (range de la nuit du dimanche
    pour le lundi), hors fetes americaines.
  K2 (essai 437) - ES, cassure de l initial balance (micro MES ; replique NQ / MNQ, pas un essai) :
    IB = plus haut et plus bas des barres de 09:30 a 10:30 ; fenetre d entree 10:30 -> 15:00, memes ordres stop
    (+/- 1 tick, un trade par jour) ; stop au milieu de l IB ; sortie a l ouverture de la barre de 15:55.
  Execution : ordre stop rempli a son niveau, ou a l ouverture de la barre si elle s ouvre au-dela (pire prix) ; si les
  deux niveaux sont touches dans la meme barre, on prend celui qui est le plus proche de l ouverture de la barre ; le
  stop de protection est verifie des la barre d entree (prudent). Jour exclu : range incomplet (moins de 80 % des
  minutes), prix absent a la sortie, changement d echeance entre le debut du range et la sortie.
  Conformite prop (critere 21) : a plat avant 16:10, jamais de week-end. Conflit de contrat (critere 19) : aucun avec
  S1 (MNQ) ni Gotobi (6J) ; la replique NQ en aurait un avec S1.
  Temoin neutre (critere 12) : les MEMES jours, entree au MEME instant que le trade et sortie a l heure de sortie, sans
  stop, sens tire au hasard (graine 7) : meme exposition, sans la cassure.
Couts (critere 8) : 1 tick + 2,50 $ par cote (stress 2 ticks) ; micros au meme tarif par cote.
Criteres : n° 10-14 (criteres() de soixante, rendement du trade dans son sens, en pb), n° 16-18 (mesures() de
  prop_combinaisons sur le rendement net journalier, 0 les jours sans trade, Sharpe deflate avec 436 puis 437 essais),
  n° 19 (heures par an), n° 20 (correlation avec S1 et Gotobi) seulement si le reste passe.
Verification du calcul (critere 9, sans regarder le gain) : (a) horodatage (pics de volume a 3:00 Londres, 8:20
  COMEX, 9:30 New York) ; (b) anticipation (prix des barres apres l instant d entree x1,5 sur 200 jours -> entree
  inchangee) ; (c) rejeu vectorbt = P&L brut du moteur trade par trade ; (d) 5 trades tires au hasard (graine 7) ;
  (e) comptes (jours, exclusions, trades, sorties au stop, heures).
Bug trouve a la verification, AVANT tout calcul de gain (2026-10-25) : le range du lundi commencait le samedi soir
  (veille - 2 jours au lieu de dimanche) ; 499 lundis sur 2 679 jours etaient exclus pour « range incomplet ». Corrige
  (lundi - 1 jour = dimanche 19:00) ; aucun gain n avait ete calcule ni affiche.
"""
from __future__ import annotations

import argparse
import math
import os
from datetime import datetime

import numpy as np
import pandas as pd

from .. import prop_combinaisons as PC
from .or_anomalies import instants
from .ouverture_europe import correlations
from .soixante import COMMISSION, COUTS, ET, NS_MIN, PY_DIR, contrats, criteres, jours_ouvres_us, marche

try:
    import vectorbt as vbt
except ImportError:  # pragma: no cover
    vbt = None

MICRO = {"GC": ("MGC", 10.0), "ES": ("MES", 5.0), "NQ": ("MNQ", 2.0), "YM": ("MYM", 0.5), "CL": ("MCL", 100.0)}
JAMBES = {
    "K1": dict(nom="Or, cassure Asie -> Londres", root="GC", essai=436, range_=((19, 0), (3, 0)), veille=True,
               entree=((3, 0), (8, 0)), sortie=(11, 30), stop="borne"),
    "K2": dict(nom="ES, cassure de l initial balance (1re heure)", root="ES", essai=437, range_=((9, 30), (10, 30)),
               veille=False, entree=((10, 30), (15, 0)), sortie=(15, 55), stop="milieu"),
}
REPLIQUES = {"K2": ["NQ"]}
REGISTRE = dict(JAMBES)            # toutes les jambes connues de trades() (kairos_jambes2 y ajoute les siennes)
COUVERTURE_MIN = 0.8


# =============================================================================
#  Moteur
# =============================================================================
def _debuts(m) -> np.ndarray:
    return m.t - NS_MIN


def jour_trade(o, h, l, c, i0, i1, e0, e1, sortie, tick, mode):
    """Un jour : range sur [i0, i1), entree sur [e0, e1), sortie a l ouverture de la barre `sortie`.
    -> (sens, i_entree, prix_entree, i_sortie, prix_sortie, raison) ou None."""
    haut, bas = h[i0:i1].max(), l[i0:i1].min()
    up, dn = haut + tick, bas - tick
    stop_long = bas if mode == "borne" else (haut + bas) / 2
    stop_short = haut if mode == "borne" else (haut + bas) / 2
    for k in range(e0, e1):
        tu, td = h[k] >= up, l[k] <= dn
        if not (tu or td):
            continue
        if tu and td:
            tu = abs(up - o[k]) <= abs(o[k] - dn)
            td = not tu
        if tu:
            sens, px, stop = 1, max(o[k], up), stop_long
        else:
            sens, px, stop = -1, min(o[k], dn), stop_short
        for q in range(k, sortie):
            if sens > 0 and l[q] <= stop:
                return sens, k, px, q, (min(o[q], stop) if q > k else stop), "stop"
            if sens < 0 and h[q] >= stop:
                return sens, k, px, q, (max(o[q], stop) if q > k else stop), "stop"
        return sens, k, px, sortie, o[sortie], "heure"
    return None


def trades(m, cle: str, root: str | None = None, o=None, h=None, l=None, seul=None) -> pd.DataFrame:
    """Tous les jours de la jambe -> table (un jour par ligne, motif d exclusion, trade et temoin)."""
    p = REGISTRE[cle]
    root = root or p["root"]
    o = m.o if o is None else o
    h = m.h if h is None else h
    l = m.l if l is None else l
    tick = COUTS[root][0]
    deb = _debuts(m)
    jours = jours_ouvres_us(m)
    jours = jours[jours > pd.Timestamp(m.t[0], unit="ns").normalize() + pd.Timedelta(days=1)]
    ja = jours - pd.Timedelta(days=1) if p["veille"] else jours
    t_r0 = instants(ja, *p["range_"][0], ET)
    t_r1 = instants(jours, *p["range_"][1], ET)
    t_e0, t_e1 = instants(jours, *p["entree"][0], ET), instants(jours, *p["entree"][1], ET)
    t_s = instants(jours, *p["sortie"], ET)
    i0, i1 = np.searchsorted(deb, t_r0), np.searchsorted(deb, t_r1)
    e0, e1 = np.searchsorted(deb, t_e0), np.searchsorted(deb, t_e1)
    s = np.clip(np.searchsorted(deb, t_s), 0, m.n - 1)
    cid = contrats(m)
    off = m.offset
    rng = np.random.default_rng(7)
    sens_temoin = rng.choice([-1, 1], size=len(jours))
    lignes = []
    for k, d in enumerate(jours):
        if seul is not None and d != seul:
            continue
        attendu = (t_r1[k] - t_r0[k]) / NS_MIN
        motif, tr = "", None
        if i1[k] - i0[k] < COUVERTURE_MIN * attendu:
            motif = "range incomplet"
        elif deb[s[k]] != t_s[k]:
            motif = "prix absent a la sortie"
        elif cid[s[k]] != cid[i0[k]]:
            motif = "changement d echeance"
        else:
            tr = jour_trade(o, h, l, m.c, i0[k], i1[k], e0[k], e1[k], s[k], tick, p["stop"])
            if tr is None:
                motif = "pas de cassure"
        row = dict(jour=d, motif=motif)
        if tr is not None:
            sens, ie, pe, isx, ps, raison = tr
            reel_e, reel_s = pe - off[ie], ps - off[isx]
            temoin = sens_temoin[k] * math.log((o[s[k]] - off[s[k]]) / reel_e)
            row.update(sens=sens, t_entree=int(deb[ie]), t_sortie=int(deb[isx]), pe=reel_e, ps=reel_s, raison=raison,
                       brut_pb=sens * math.log(reel_s / reel_e) * 1e4, temoin_pb=temoin * 1e4,
                       minutes=(deb[isx] - deb[ie]) / NS_MIN, ie=ie)
        lignes.append(row)
    return pd.DataFrame(lignes).set_index("jour")


def cout_pb(root: str, prix: float, ticks: int = 1, micro: bool = False) -> float:
    tick, pv = COUTS[root][0], (MICRO[root][1] if micro else COUTS[root][1])
    return (2 * ticks * tick + 2 * COMMISSION / pv) / prix * 1e4


def serie_journaliere(f: pd.DataFrame, cout: float) -> pd.Series:
    r = pd.Series(0.0, index=f.index)
    t = f[f["motif"] == ""]
    r.loc[t.index] = (np.exp(t["brut_pb"] / 1e4) - 1) - cout / 1e4
    return r


# =============================================================================
#  Verifications (critere 9)
# =============================================================================
def verif_horodatage(m) -> str:
    debut = pd.DatetimeIndex(m.t - NS_MIN).tz_localize("UTC").tz_convert(ET)
    tod = np.asarray(debut.hour * 60 + debut.minute)
    vol = pd.Series(m.v[debut.dayofweek < 5]).groupby(tod[debut.dayofweek < 5]).median()
    out = []
    for hh, mi, lib in ((3, 0, "Londres"), (8, 20, "COMEX"), (8, 30, "chiffres US"), (9, 30, "New York")):
        k = hh * 60 + mi
        voisins = vol.reindex([k - 3, k - 2, k - 1]).mean()
        out.append(f"{hh}:{mi:02d} {lib} x{vol.get(k, np.nan) / voisins:.1f}")
    return "(a) horodatage (volume median de la barre / 3 barres precedentes) : " + ", ".join(out)


def verif_anticipation(m, cle: str, f: pd.DataFrame) -> str:
    t = f[f["motif"] == ""].sample(200, random_state=3)
    diff = 0
    deb = _debuts(m)
    for d in t.itertuples():
        fut = deb > d.t_entree
        o2, h2, l2 = (np.where(fut, x * 1.5, x) for x in (m.o, m.h, m.l))
        r = trades(m, cle, o=o2, h=h2, l=l2, seul=d.Index).iloc[0]
        if not (r["motif"] == "" and r["t_entree"] == d.t_entree and math.isclose(r["pe"], d.pe, abs_tol=1e-9)
                and r["sens"] == d.sens):
            diff += 1
    etat = "INCHANGEES" if diff == 0 else f"DIFFERENTES (BUG : {diff} jours)"
    return f"(b) anticipation : prix apres l entree x1,5 sur 200 jours -> heure, sens et prix d entree {etat}"


def verif_vectorbt(root: str, f: pd.DataFrame) -> str:
    if vbt is None:
        return "(c) vectorbt absent : rejeu non fait"
    t = f[f["motif"] == ""]
    pv = COUTS[root][1]
    moteur = (t["sens"] * (t["ps"] - t["pe"]) * pv).to_numpy()
    ts = np.r_[t["t_entree"].to_numpy(), t["t_sortie"].to_numpy() + 1]
    px = np.r_[t["pe"].to_numpy(), t["ps"].to_numpy()]
    taille = np.r_[t["sens"].to_numpy(float), -t["sens"].to_numpy(float)]
    o = np.argsort(ts, kind="stable")
    prix = pd.Series(px[o] * pv, index=pd.to_datetime(ts[o]))
    pf = vbt.Portfolio.from_orders(prix, size=pd.Series(taille[o], index=prix.index), init_cash=1e12, fees=0.0,
                                   freq="1min")
    pnl = pf.trades.records_readable.sort_values("Entry Timestamp")["PnL"].to_numpy()
    ecart = float(np.max(np.abs(pnl - moteur))) if len(pnl) == len(moteur) else math.inf
    return (f"(c) rejeu vectorbt : {len(pnl)} trades contre {len(moteur)} au moteur, ecart maximal de P&L brut "
            f"{ecart:.6f} $ -> {'IDENTIQUE' if ecart < 1e-6 else 'DIFFERENT (BUG)'}")


def verif_cinq(root: str, f: pd.DataFrame) -> list[str]:
    t = f[f["motif"] == ""]
    tick, pv = COUTS[root][0], COUTS[root][1]
    out = ["(d) 5 trades tires au hasard (graine 7), a verifier a la main :"]
    for d in t.sample(5, random_state=7).sort_index().itertuples():
        ha = pd.Timestamp(d.t_entree).tz_localize("UTC").tz_convert(ET)
        hb = pd.Timestamp(d.t_sortie).tz_localize("UTC").tz_convert(ET)
        brut = d.sens * (d.ps - d.pe) * pv
        frais = 2 * (tick * pv + COMMISSION)
        out.append(f"    {d.Index:%Y-%m-%d} : {'ACHAT' if d.sens > 0 else 'VENTE'} {ha:%a %H:%M} ET a {d.pe:.2f} | sortie "
                   f"({d.raison}) {hb:%a %H:%M} ET a {d.ps:.2f} | brut {brut:+.2f} $ - frais {frais:.2f} $ = {brut - frais:+.2f} $")
    return out


# =============================================================================
#  Etude
# =============================================================================
TITRE = [" JAMBES DU BOOK KAIROS SANS PAPIER (critere 1 assoupli le 2026-10-25) - DEUX ESSAIS (n° 436 et 437)",
         "K1 : or, range 19:00 -> 3:00 ET, cassure 3:00 -> 8:00, stop a l autre borne, sortie 11:30.",
         "K2 : ES, initial balance 9:30 -> 10:30, cassure 10:30 -> 15:00, stop au milieu de l IB, sortie 15:55."]


def etude(sortie: str | None = None, log=print, jambes=None, repliques=None, titre=None,
          fichier="resultats_kairos_jambes.txt") -> dict:
    jambes = JAMBES if jambes is None else jambes
    repliques = REPLIQUES if repliques is None else repliques
    titre = TITRE if titre is None else titre
    t0 = datetime.now()
    L: list[str] = []
    pr = L.append
    pr("=" * 116)
    pr(titre[0])
    pr("=" * 116)
    for ligne in titre[1:]:
        pr(ligne)
    pr("Temoin : meme jour, meme instant d entree, sortie a l heure, sans stop, sens au hasard (graine 7).\n")
    res = {}
    for cle, p in jambes.items():
        for root in [p["root"]] + repliques.get(cle, []):
            m = marche(root)
            f = trades(m, cle, root)
            ok = f[f["motif"] == ""]
            prix = float(np.nanmedian(ok["pe"]))
            c1, c2, cm = cout_pb(root, prix), cout_pb(root, prix, ticks=2), cout_pb(root, prix, micro=True)
            crit = criteres(ok["brut_pb"], ok["temoin_pb"], c1)
            r = serie_journaliere(f, c1)
            x = PC.mesures(r, p["essai"])
            xm = PC.mesures(serie_journaliere(f, cm), p["essai"])
            ans = (f.index[-1] - f.index[0]).days / 365.25
            res[(cle, root)] = dict(f=f, crit=crit, mesures=x, micro=xm, cout=c1, stress=c2, cout_micro=cm, r=r,
                                    heures_an=float(ok["minutes"].sum() / 60 / ans), m=m)
    pr("Verification du calcul (critere 9)")
    for cle, p in jambes.items():
        z = res[(cle, p["root"])]
        m, f = z["m"], z["f"]
        pr(f"  {cle} ({p['root']})")
        pr("    " + verif_horodatage(m))
        pr("    " + verif_anticipation(m, cle, f))
        pr("    " + verif_vectorbt(p["root"], f))
        for s in verif_cinq(p["root"], f):
            pr("    " + s)
        motifs = f["motif"].replace("", "trade").value_counts()
        ok = f[f["motif"] == ""]
        ans = (f.index[-1] - f.index[0]).days / 365.25
        pr(f"    (e) comptes : {len(f)} jours {f.index[0]:%Y-%m-%d} -> {f.index[-1]:%Y-%m-%d} ; "
           + " ; ".join(f"{k} {v}" for k, v in motifs.items())
           + f" ; sorties au stop {int((ok['raison'] == 'stop').sum())} ; achats {int((ok['sens'] > 0).sum())} ; "
           f"{len(ok) / ans:.0f} trades par an, {z['heures_an']:.0f} h/an")
    pr("")
    for (cle, root), z in res.items():
        p = REGISTRE[cle]
        crit, x, xm, c1, c2, cm = z["crit"], z["mesures"], z["micro"], z["cout"], z["stress"], z["cout_micro"]
        essai = root == p["root"]
        net = z["f"].loc[z["f"]["motif"] == "", "brut_pb"] - c1
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
        pr(f"    micro {MICRO[root][0]} (cout {cm:.2f} pb) : net {crit['moyenne'] - cm:+.2f} pb | Sharpe {xm['sharpe']:+.2f} "
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
    for cle, p in jambes.items():
        v = res[(cle, p["root"])]["echecs"]
        pr(f"Synthese {cle} : " + ("passe les criteres 10-18 ; restent la correlation (n° 20) et la validation."
                                   if not v else "REJETEE. Aucune variante ne sera testee (pas de surajustement)."))
    pr(f"Calcul en {(datetime.now() - t0).total_seconds():.0f} s.")
    sortie = sortie or os.path.join(PY_DIR, "recherche", fichier)
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
