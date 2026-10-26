"""Rendement de l ES autour de l ouverture europeenne (23:30 -> 3:30 ET), creneau vide du groupe (UN essai, n° 434).

    python -m nexus.perso.ouverture_europe [--sortie resultats_ouverture_europe.txt]

PROTOCOLE ECRIT LE 2026-10-24 AVANT LE CALCUL. Aucun parametre n est choisi apres avoir vu un resultat.

Origine et derogation (demande de l utilisateur du 2026-10-24)
  Hypothese n° 172 du registre : O. Bondarenko & D. Muravyev, « Market Return Around the Clock: A Puzzle », Journal of
  Financial and Quantitative Analysis 58 (3), 2023, p. 939-967 (doi 10.1017/S0022109022000783). Lus : le resume publie,
  l annexe en ligne (Internet Appendix du 25/08/2021) et le resume d Alpha Architect. Chiffres repris :
    - E-mini S&P 500, 2004-2018 : la fenetre « EU-open », de 23:30 a 3:30 ET, rapporte 7,6 % par an, Sharpe 1,6 (1,67
      selon Alpha Architect, t 6,4), positive chaque annee ; les 20 autres heures rapportent un zero bruite (-0,8 %) ;
    - l heure 1:30-2:30 ET (ouverture de Francfort) fait a elle seule 5,0 des 7,6 points ;
    - explication : les investisseurs europeens qui arrivent resolvent l incertitude accumulee la nuit (le VIX des
      futures monte la nuit et baisse a l ouverture europeenne).
  Papier contraire : Boyarchenko, Larsen & Whelan, « The Disappearing Overnight Drift », Liberty Street Economics (Fed de
  New York), juillet 2026 : la fenetre 2:00-3:00 ET est plate sur 2021-2025 pour ES, NQ et YM ; chez nous aussi
  (`derive_nocturne`, ES 2:00-3:00 2021-2026 : -0,04 pb, t -0,1).
  Trois criteres de la methode ne sont PAS remplis ; le test est fait par derogation explicite de l utilisateur :
    n° 3 (texte complet non lu : payant, SSRN derriere une verification anti-robot non contournee),
    n° 4 (papier contraire pour 2021-2026),
    n° 6 (puissance sous 3 sur l ES). Calcul de puissance (t_attendu, effet du papier 7,6 % / 252 = 3,02 pb par nuit,
      ecart-type 3,02 / (1,67 / racine(252)) = 28,7 pb, 2 680 nuits, couts au prix median 2016-2026) :
      ES 2,64 (cout 1,55 pb), MES -1,56 (3,88 pb) ; repliques NQ 4,32 (0,62 pb), MNQ 0,96, YM 3,72, MYM -1,45.
  Le test compte pour UN essai : ESSAIS_PROGRAMME 433 -> 434 (les repliques et les micros ne sont pas des essais).

Regle unique, figee (celle du papier, aucune grille, aucune variante)
  Chaque nuit dont le matin est un jour de bourse americain (lundi au vendredi, hors fetes) : ACHAT d un contrat au prix
  de 23:30 ET la veille au soir (dimanche soir pour le lundi), VENTE au prix de 3:30 ET. Prix = ouverture de la barre
  1 minute qui commence a l heure dite (sinon cloture de la derniere barre finie dans les 5 minutes, `prix_a`). Aucun
  stop, aucun filtre (le papier n en a pas). Heures de New York, celles du papier ; les semaines ou l ecart New York -
  Francfort n est pas de 6 h sont GARDEES (le papier ne les retire pas ; leur nombre est seulement compte).
  Conforme prop (critere 21) : position de nuit seulement (permise), a plat bien avant 16:10, jamais du vendredi soir au
  dimanche soir. Pas de conflit de contrat avec le groupe (critere 19) : S1 tient le MNQ de 9:30 a 16:00, Gotobi le 6J.
  Nuits exclues : prix absent a l une des deux heures, changement d echeance entre les deux heures.
  Temoin neutre : la MEME operation (achat, 4 h) la MEME nuit, de 19:30 a 23:30 ET (seance asiatique, avant l arrivee
  des Europeens ; le papier y mesure un zero bruite).
  Repliques (pas des essais) : NQ et YM, memes regles. Contrats du compte (critere 22) : MES, MNQ, MYM, leurs couts.
Couts (critere 8) : 1 tick + 2,50 $ par cote (stress 2 ticks par cote).
Criteres : n° 10-14 (criteres() de soixante), n° 16-18 avec mesures() de prop_combinaisons (rendement net de chaque nuit
  rattache au jour du matin, 0 les nuits exclues, Sharpe deflate avec 434 essais), n° 19 (heures par an, rendement par
  heure), n° 20 (correlation avec S1 et Gotobi) seulement si le reste passe.
Verification du calcul (critere 9, sans regarder le gain) :
  (a) horodatage : volume median par minute ET ; les pics connus doivent tomber sur les barres qui commencent a 2:00
      (ouverture de Francfort a 8:00), 3:00 (Londres a 8:00), 8:30 (chiffres americains) et 9:30 (ouverture New York),
      semaines a ecart normal de 6 h ;
  (b) anticipation : prix de toutes les barres qui commencent APRES l heure d entree (puis apres l heure de sortie)
      multiplies par 1,5 sur 200 nuits tirees au hasard -> prix d entree (puis de sortie) inchanges ;
  (c) rejeu vectorbt (Portfolio.from_orders, 1 contrat, sans frais) = P&L brut du moteur trade par trade ;
  (d) 5 trades tires au hasard (graine 7) imprimes en detail pour verification a la main ;
  (e) comptes : nuits, exclusions par motif, nuits par an, heures par an.
"""
from __future__ import annotations

import argparse
import glob
import json
import math
import os
from datetime import datetime

import numpy as np
import pandas as pd

from .. import prop_combinaisons as PC
from .or_anomalies import instants
from .soixante import COMMISSION, COUTS, ET, FRANCFORT, NS_MIN, PY_DIR, contrats, criteres, jours_ouvres_us, marche, \
    prix_a, t_attendu

try:
    import vectorbt as vbt
except ImportError:  # pragma: no cover
    vbt = None

ENTREE, SORTIE_H = (23, 30), (3, 30)          # entree la veille au soir, sortie le matin
TEMOIN_A, TEMOIN_B = (19, 30), (23, 30)       # meme nuit, avant l arrivee des Europeens
HEURES = 4.0
ESSAIS = 434
MICRO = {"ES": ("MES", 5.0), "NQ": ("MNQ", 2.0), "YM": ("MYM", 0.5)}
EFFET_PB, SHARPE_PAPIER = 7.6 / 252 * 100, 1.67     # 3,02 pb par nuit ; ecart-type deduit du Sharpe


# =============================================================================
#  Nuits et trades
# =============================================================================
def nuits(m) -> pd.DatetimeIndex:
    """Jours de bourse americains (matin de chaque nuit), avec une veille dans les donnees."""
    j = jours_ouvres_us(m)
    return j[j > pd.Timestamp(m.t[0], unit="ns").normalize() + pd.Timedelta(days=1)]


def reel(m, px: np.ndarray, idx: np.ndarray) -> np.ndarray:
    off = getattr(m, "offset", np.zeros(m.n))
    return np.where(idx >= 0, px - off[np.clip(idx, 0, None)], np.nan)


def jambe(m, jours: pd.DatetimeIndex, a: tuple, b: tuple, veille_a: bool, veille_b: bool) -> pd.DataFrame:
    """Achat a l heure a, vente a l heure b ; a et b le jour meme ou la veille calendaire. Prix reels, motif d exclusion."""
    ja = jours - pd.Timedelta(days=1) if veille_a else jours
    jb = jours - pd.Timedelta(days=1) if veille_b else jours
    ta, tb = instants(ja, *a, ET), instants(jb, *b, ET)
    pa, ia = prix_a(m, ta)
    pb, ib = prix_a(m, tb)
    ok = np.isfinite(pa) & np.isfinite(pb) & (ia >= 0) & (ib >= 0)
    cid = contrats(m)
    roll = np.zeros(len(jours), bool)
    roll[ok] = cid[ib[ok]] != cid[ia[ok]]
    motif = np.where(~ok, "prix absent", np.where(roll, "changement d echeance", ""))
    f = pd.DataFrame(dict(ta=ta, tb=tb, pa=reel(m, pa, ia), pb=reel(m, pb, ib), motif=motif), index=jours)
    f["brut_pb"] = np.where(f["motif"] == "", np.log(f["pb"] / f["pa"]) * 1e4, np.nan)
    return f


def ecart_francfort(jours: pd.DatetimeIndex) -> np.ndarray:
    t = (pd.DatetimeIndex(jours) + pd.Timedelta(hours=2)).tz_localize(ET, nonexistent="shift_forward", ambiguous=False)
    return np.array([(x.tz_convert(FRANCFORT).utcoffset() - x.utcoffset()).total_seconds() / 3600 for x in t])


def cout_pb(root: str, prix: float, ticks: int = 1, micro: bool = False) -> float:
    tick, pv = COUTS[root][0], (MICRO[root][1] if micro else COUTS[root][1])
    return (2 * ticks * tick + 2 * COMMISSION / pv) / prix * 1e4


def serie_journaliere(f: pd.DataFrame, cout: float) -> pd.Series:
    """Rendement net de la nuit (fraction) rattache au jour du matin, 0 les nuits exclues."""
    r = pd.Series(0.0, index=f.index)
    t = f[f["motif"] == ""]
    r.loc[t.index] = (np.exp(t["brut_pb"] / 1e4) - 1) - cout / 1e4
    return r


# =============================================================================
#  Verifications (critere 9)
# =============================================================================
def verif_horodatage(m) -> str:
    debut = pd.DatetimeIndex(m.t - NS_MIN).tz_localize("UTC").tz_convert(ET)
    jours = debut.tz_localize(None).normalize()
    uniques = pd.DatetimeIndex(np.unique(jours))
    sel = jours.isin(uniques[ecart_francfort(uniques) == 6]) & (debut.dayofweek < 5)
    tod = (debut.hour * 60 + debut.minute)[sel]
    vol = pd.Series(m.v[sel]).groupby(np.asarray(tod)).median()
    out = []
    for h, mi, lib in ((2, 0, "Francfort"), (3, 0, "Londres"), (8, 30, "chiffres US"), (9, 30, "New York")):
        k = h * 60 + mi
        voisins = vol.reindex([k - 3, k - 2, k - 1]).mean()
        out.append(f"{h}:{mi:02d} {lib} x{vol.get(k, np.nan) / voisins:.1f}")
    top = vol.nlargest(6).index
    return ("(a) horodatage (volume median de la barre / 3 barres precedentes, semaines a 6 h) : " + ", ".join(out)
            + " | 6 plus gros volumes medians : " + ", ".join(f"{k // 60}:{k % 60:02d}" for k in sorted(top)))


class _Copie:
    """Marche dont les prix des barres commencant apres un instant sont modifies (test d anticipation)."""

    def __init__(self, m, apres_ns: int):
        self.t, self.n, self.offset = m.t, m.n, m.offset
        self._contrat = contrats(m)
        fut = (m.t - NS_MIN) > apres_ns
        self.o, self.c = np.where(fut, m.o * 1.5, m.o), np.where(fut, m.c * 1.5, m.c)


def verif_anticipation(m, f: pd.DataFrame) -> str:
    t = f[f["motif"] == ""].sample(200, random_state=3)
    diff_a = diff_b = 0
    for d in t.itertuples():
        for instant, col in ((d.ta, "a"), (d.tb, "b")):
            c = _Copie(m, int(instant))
            px, idx = prix_a(c, np.array([instant]))
            v = reel(c, px, idx)[0]
            if col == "a" and not math.isclose(v, d.pa, abs_tol=1e-9):
                diff_a += 1
            if col == "b" and not math.isclose(v, d.pb, abs_tol=1e-9):
                diff_b += 1
    etat = "INCHANGES" if diff_a == diff_b == 0 else f"DIFFERENTS (BUG : entree {diff_a}, sortie {diff_b})"
    return f"(b) anticipation : prix futurs x1,5 sur 200 nuits -> prix d entree et de sortie {etat}"


def verif_vectorbt(root: str, f: pd.DataFrame) -> str:
    if vbt is None:
        return "(c) vectorbt absent : rejeu non fait"
    t = f[f["motif"] == ""]
    pv = COUTS[root][1]
    moteur = ((t["pb"] - t["pa"]) * pv).to_numpy()
    ts = np.r_[t["ta"].to_numpy(), t["tb"].to_numpy()]
    px = np.r_[t["pa"].to_numpy(), t["pb"].to_numpy()]
    taille = np.r_[np.ones(len(t)), -np.ones(len(t))]
    o = np.argsort(ts, kind="stable")
    prix = pd.Series(px[o] * pv, index=pd.to_datetime(ts[o]))
    pf = vbt.Portfolio.from_orders(prix, size=pd.Series(taille[o], index=prix.index), init_cash=1e9, fees=0.0,
                                   freq="1min")
    pnl_vbt = pf.trades.records_readable.sort_values("Entry Timestamp")["PnL"].to_numpy()
    ecart = float(np.max(np.abs(pnl_vbt - moteur))) if len(pnl_vbt) == len(moteur) else math.inf
    return (f"(c) rejeu vectorbt : {len(pnl_vbt)} trades contre {len(moteur)} au moteur, ecart maximal de P&L brut "
            f"{ecart:.6f} $ -> {'IDENTIQUE' if ecart < 1e-6 else 'DIFFERENT (BUG)'}")


def verif_cinq(root: str, f: pd.DataFrame) -> list[str]:
    t = f[f["motif"] == ""]
    tick, pv = COUTS[root][0], COUTS[root][1]
    out = ["(d) 5 trades tires au hasard (graine 7), a verifier a la main :"]
    for d in t.sample(5, random_state=7).sort_index().itertuples():
        ha = pd.Timestamp(d.ta).tz_localize("UTC").tz_convert(ET)
        hb = pd.Timestamp(d.tb).tz_localize("UTC").tz_convert(ET)
        brut = (d.pb - d.pa) * pv
        frais = 2 * (tick * pv + COMMISSION)
        out.append(f"    nuit du {d.Index:%Y-%m-%d} : ACHAT {ha:%a %Y-%m-%d %H:%M} ET a {d.pa:.2f} | VENTE "
                   f"{hb:%a %Y-%m-%d %H:%M} ET a {d.pb:.2f} | brut {brut:+.2f} $ - frais {frais:.2f} $ = {brut - frais:+.2f} $")
    return out


# =============================================================================
#  Correlation (critere 20), seulement si les criteres 10-18 passent
# =============================================================================
def correlations(r: pd.Series) -> str:
    out = []
    for chemin in sorted(glob.glob(os.path.join(PY_DIR, "..", "Dashboard", "donnees", "*.json"))):
        try:
            d = json.load(open(chemin, encoding="utf-8"))
            s = d.get("series") or {}
            if not s.get("dates"):
                continue
            x = pd.Series(s["rendement"], index=pd.to_datetime(s["dates"]))
        except Exception:
            continue
        nom = os.path.basename(chemin)[:-5]
        if any(k in nom.lower() for k in ("s1", "gotobi")):
            j = pd.concat([r, x], axis=1, join="inner").dropna()
            out.append(f"{nom} {j.corr().iloc[0, 1]:+.2f} ({len(j)} jours)")
    return "correlation journaliere : " + (" ; ".join(out) if out else "series S1 / Gotobi introuvables")


# =============================================================================
#  Etude
# =============================================================================
def etude(sortie: str | None = None, log=print) -> dict:
    t0 = datetime.now()
    L: list[str] = []
    pr = L.append
    pr("=" * 116)
    pr(" ES AUTOUR DE L OUVERTURE EUROPEENNE (23:30 -> 3:30 ET), BONDARENKO & MURAVYEV (JFQA 2023) - UN ESSAI (n° 434)")
    pr("=" * 116)
    pr("Derogation demandee par l utilisateur : texte complet non lu (critere 3), papier contraire pour 2021-2026 (critere 4),")
    pr("puissance sous 3 sur l ES (critere 6). Regle figee : achat 23:30 ET la veille, vente 3:30 ET, chaque nuit de semaine.")
    pr("Temoin : meme achat de 4 h la meme nuit, 19:30 -> 23:30 ET.\n")
    res = {}
    for root in ("ES", "NQ", "YM"):
        m = marche(root)
        j = nuits(m)
        f = jambe(m, j, ENTREE, SORTIE_H, veille_a=True, veille_b=False)
        tem = jambe(m, j, TEMOIN_A, TEMOIN_B, veille_a=True, veille_b=True)
        prix = float(np.nanmedian(f["pa"]))
        c1, c2, cm = cout_pb(root, prix), cout_pb(root, prix, ticks=2), cout_pb(root, prix, micro=True)
        sd = EFFET_PB / (SHARPE_PAPIER / math.sqrt(252))
        n_ok = int((f["motif"] == "").sum())
        if root == "ES":
            pr("Calcul de puissance (critere 6, effet du papier 3,02 pb par nuit, ecart-type 28,7 pb) :")
        pr(f"  {root} : t attendu {t_attendu(EFFET_PB, c1, sd, n_ok):+.2f} (cout {c1:.2f} pb) | {MICRO[root][0]} "
           f"{t_attendu(EFFET_PB, cm, sd, n_ok):+.2f} (cout {cm:.2f} pb)")
        crit = criteres(f["brut_pb"].dropna(), tem["brut_pb"].dropna(), c1)
        r = serie_journaliere(f, c1)
        x, xm = PC.mesures(r, ESSAIS), PC.mesures(serie_journaliere(f, cm), ESSAIS)
        ans = (f.index[-1] - f.index[0]).days / 365.25
        res[root] = dict(f=f, temoin=tem, crit=crit, mesures=x, micro=xm, cout=c1, stress=c2, cout_micro=cm, r=r,
                         heures_an=n_ok * HEURES / ans)
    pr("")
    pr("Verification du calcul (critere 9)")
    es = marche("ES")
    f = res["ES"]["f"]
    pr("  " + verif_horodatage(es))
    pr("  " + verif_anticipation(es, f))
    pr("  " + verif_vectorbt("ES", f))
    for s in verif_cinq("ES", f):
        pr("  " + s)
    motifs = f["motif"].replace("", "retenue").value_counts()
    ans = (f.index[-1] - f.index[0]).days / 365.25
    decale = int((ecart_francfort(f.index) != 6).sum())
    pr(f"  (e) comptes ES : {len(f)} nuits {f.index[0]:%Y-%m-%d} -> {f.index[-1]:%Y-%m-%d} ; "
       + " ; ".join(f"{k} {v}" for k, v in motifs.items())
       + f" ; temoin retenu {int((res['ES']['temoin']['motif'] == '').sum())} ; {motifs.get('retenue', 0) / ans:.0f} nuits par an, "
       f"{res['ES']['heures_an']:.0f} h/an ; nuits a ecart New York - Francfort different de 6 h (gardees) {decale}\n")
    for root in ("ES", "NQ", "YM"):
        z = res[root]
        crit, x, xm, c1, c2, cm = z["crit"], z["mesures"], z["micro"], z["cout"], z["stress"], z["cout_micro"]
        net = z["f"]["brut_pb"].dropna() - c1
        pr(f"--- {root}{' (ESSAI)' if root == 'ES' else ' (replique, pas un essai)'} : {crit['n']} nuits")
        pr(f"    brut {crit['moyenne']:+.2f} pb (t {crit['t']:+.2f}) | 2016-2020 {crit['m1']:+.2f} (t {crit['t1']:+.2f}) | "
           f"2021-2026 {crit['m2']:+.2f} (t {crit['t2']:+.2f}) | papier 2004-2018 : +{EFFET_PB:.2f}")
        pr(f"    temoin 19:30 -> 23:30 {crit['temoin']:+.2f} pb -> Welch {crit['welch']:+.2f}")
        pr(f"    cout aller-retour {c1:.2f} pb -> net {crit['net']:+.2f} pb ; sans les 3 meilleures nuits {crit['sans3']:+.2f} pb ; "
           f"stress 2 ticks {crit['moyenne'] - c2:+.2f} pb ; gain total {net.sum():+.0f} pb")
        an = net.groupby(net.index.year).mean()
        pr("    net par annee (pb) : " + " ".join(f"{a}:{v:+.1f}" for a, v in an.items()))
        pr(f"    vectorbt ({root}, 1 tick) : Sharpe {x['sharpe']:+.2f} [IC 95 % {x['ic_bas']:+.2f} ; {x['ic_haut']:+.2f}] | "
           f"avant 2021 {x['sharpe_p1']:+.2f} | apres {x['sharpe_p2']:+.2f} | deflate ({ESSAIS} essais) {x['dsr']:.2f} | "
           f"perte max {x['perte_max']:.1%}")
        pr(f"    micro {MICRO[root][0]} (cout {cm:.2f} pb) : net {crit['moyenne'] - cm:+.2f} pb | Sharpe {xm['sharpe']:+.2f} "
           f"[IC bas {xm['ic_bas']:+.2f}] | deflate {xm['dsr']:.2f}")
        pr(f"    heures en position : {z['heures_an']:.0f} h/an ; rendement net par heure {crit['net'] / HEURES:+.2f} pb")
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
    v = res["ES"]["echecs"]
    pr("Synthese : " + ("l essai ES passe les criteres 10-18 ; restent la correlation (n° 20) et la validation."
                        if not v else "REJETEE (l essai ES echoue). Aucune variante ne sera testee (pas de surajustement)."))
    pr(f"Calcul en {(datetime.now() - t0).total_seconds():.0f} s.")
    sortie = sortie or os.path.join(PY_DIR, "recherche", "resultats_ouverture_europe.txt")
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
