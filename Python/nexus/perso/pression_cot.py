"""Pression de couverture et pression speculative (rapports COT de la CFTC) : strategie construite sur huit travaux.

    python -m nexus.perso.pression_cot [--sortie resultats_pression_cot.txt]

PROTOCOLE ECRIT LE 2026-10-10, AVANT TOUT CALCUL SUR NOS DONNEES (methode : memoire « methode-strategie-papiers »).

Sources (texte complet lu = [T], resume seulement = [R])
 [KRT20] [T] W. Kang (SUFE), K. G. Rouwenhorst (Yale), K. Tang (Tsinghua), « A Tale of Two Premiums: The Role of Hedgers and
         Speculators in Commodity Futures Markets », Journal of Finance 75 (1), 2020 ; 26 matieres premieres, COT 1994-2014.
         Pression de couverture HP = (courts - longs des commerciaux) / interet ouvert ; achats nets Q = variation hebdomadaire
         de la position nette longue / interet ouvert de la semaine precedente. (1) Court terme : les speculateurs
         « impatients » demandent de la liquidite ; les matieres premieres que les commerciaux ont achetees la semaine
         precedente battent celles qu ils ont vendues de 0,30 % les jours 5 a 10 apres la mesure (t 3,6 ; rapport publie le
         vendredi, jour 4), 0,15 % les jours 11 a 20 (t 1,2), puis plus rien. (2) Long terme : la HP lissee sur 52 semaines
         predit positivement le rendement (t 3,35) : prime d assurance de la « normal backwardation ».
 [FFFM20] [T] J. H. Fan (Griffith), A. Fernandez-Perez (AUT), A.-M. Fuertes (Cass, City University of London), J. Miffre
         (Audencia), « Speculative Pressure », Journal of Futures Markets 40 (4), 2020 ; 84 futures, 1992-2018. Signal de fin
         de mois SP = moyenne sur 52 semaines de (longs - courts) / (longs + courts) des non-commerciaux ; signal standardise
         dans chaque classe (SP - moyenne) / ecart-type ; achat des signaux positifs, vente des negatifs, poids
         proportionnels, somme des valeurs absolues = 1 ; tenue 1 mois. Sharpe 0,61 (matieres premieres), 0,47 (devises),
         0,50 (indices actions), rien sur les taux ; « partout » 0,55. Instable selon les periodes (devises 0,03 en
         2008-2013, matieres premieres -0,19 en 2013-2018, actions 1,17 en 2013-2018).
 [HPE17] [T, resume] memes auteurs, « Hedging Pressure and Returns in Futures: Evidence Across Asset Classes », 2017 :
         prime de pression de couverture dans les matieres premieres, actions et devises, liee au momentum et au carry.
 [KW04]  [T] T. Klitgaard & L. Weir (Fed de New York), « Exchange Rate Changes and Net Positions of Speculators in the
         Futures Market », Economic Policy Review, 2004 ; devises CME 1993-2003 : la variation hebdomadaire des positions des
         speculateurs a le meme sens que le change de la meme semaine dans environ 75 % des cas, mais NE PREDIT PAS la
         semaine suivante.
 [KM04]  [R] J. Kearns & P. Manners (Banque de reserve d Australie), RDP 2004-07 : speculateurs sur 6 devises 1993-2003 :
         suiveurs de tendance (les rendements passes menent leurs positions) ; profits previsibles (prime de risque) mais
         pas de profit anormal.
 [SBM04] [R] D. Sanders, K. Boris & M. Manfredo, « Hedgers, funds, and small speculators in the energy futures markets »,
         Energy Economics 26, 2004 : les prix menent les positions ; les positions ne predisent pas les rendements
         hebdomadaires de l energie.
 [dRNV00] [R] F. de Roon, T. Nijman, C. Veld (Tilburg), « Hedging pressure effects in futures markets », Journal of Finance
         55 (3), 2000 : la pression de couverture (du marche et des marches voisins) explique les primes de 20 futures.
 [M23]   [R] L. Marechal, « A tale of two premiums revisited », Journal of Futures Markets 43 (5), 2023 : reprend KRT avec
         des ajustements de risque ; resultats non lus (resume seulement).
Lecture commune : a l horizon d une SEMAINE, les positions suivent les prix (KW04, KM04, SBM04, KRT) et ne predisent pas
les devises ni l energie (KW04, SBM04) ; seul l effet de liquidite de KRT existe, sur les matieres premieres. A l horizon
du MOIS, la pression speculative lissee sur 52 semaines (= pression de couverture lissee de KRT, vue de l autre cote) est
remuneree dans les matieres premieres, les devises et les indices actions (KRT, FFFM20, HPE17, dRNV00). Strategie
retenue : celle de FFFM20, telle quelle, sur nos 9 futures, la seule coherente avec tous les papiers a la fois.

Donnees
  - rapports COT « Legacy, Futures Only » de la CFTC (gratuits), 2014-2026 : E-mini S&P 500 (13874A), Nasdaq mini (209742),
    Dow x 5 $ (124603), or (088691), WTI (067651), euro (099741), livre (096742), yen (097741), dollar australien (232741) ;
    positions du mardi publiees le vendredi : un rapport n est utilise qu a partir de son vendredi de publication ;
  - futures ES NQ YM GC CL 6E 6B 6J 6A (Databento) : rendements quotidiens cloture 16:00 ET au prix reel, sans les jours
    de changement d echeance ; rendement mensuel = somme des rendements quotidiens du mois.

ETAPE 1 - l anomalie (par periode 2016-2020 / 2021-2026)
  1a. correlation entre la variation hebdomadaire de la position nette des speculateurs (Q) et le rendement du mardi au
      mardi : positive attendue (KW04 : ~75 % de meme sens) ;
  1b. prevision de la semaine qui suit la publication (vendredi -> vendredi) par Q : negative attendue sur GC et CL
      (KRT), nulle sur les devises (KW04) ;
  1c. prevision du mois suivant par le signal SP standardise dans sa classe : positive attendue (FFFM20).
ETAPE 2 - strategie V = portefeuille « partout » de FFFM20 (regles figees) :
  - fin de chaque mois : SP de chaque marche (52 derniers rapports publies), standardise dans sa classe (indices ES NQ YM,
    devises 6E 6B 6J 6A, matieres premieres GC CL) ; poids = signal / somme des valeurs absolues de la classe ;
    portefeuille partout = moyenne a parts egales des trois classes (FFFM20 ponderent les classes par moyenne-variance sur
    60 mois de rendements passes, que nous n avons pas avant 2016 : parts egales, sans estimation) ; tenu 1 mois ;
  - references rapportees sans optimisation : les trois portefeuilles par classe ; temoin = la meme construction avec le
    rendement des 12 derniers mois a la place de SP (FFFM20 affirment que SP apporte autre chose que le momentum) ;
  - couts : rotation mensuelle des poids x (1 tick + 2,50 $) par cote ; stress 2 ticks.
  Criteres (fixes avant le calcul), sur les rendements mensuels nets de V : t >= 3 ; meme signe et t >= 1,5 sur
  2016-2020 et 2021-2026 ; Welch >= 2 contre le temoin momentum ; net > 0 ; net > 0 sans les 3 meilleurs mois ; Sharpe
  deflate >= 0,95 pour 41 essais (40 precedents + V).
Compatibilite prop firm : positions tenues un mois : NON compatible avec une prop firm intraday.
"""
from __future__ import annotations

import argparse
import glob
import math
import os
import zipfile
from datetime import datetime

import numpy as np
import pandas as pd

from .alternatives import dsr
from .soixante import COMMISSION, COUTS, PY_DIR, criteres, exporter, marche, tstat
from .vol_geree import quotidien_futures

CFTC = os.path.join(PY_DIR, ".cache", "cftc")
CODES = {"13874A": "ES", "209742": "NQ", "124603": "YM", "088691": "GC", "067651": "CL",
         "099741": "6E", "096742": "6B", "097741": "6J", "232741": "6A"}
CLASSES = {"indices": ("ES", "NQ", "YM"), "devises": ("6E", "6B", "6J", "6A"), "matieres": ("GC", "CL")}
COUPURE = pd.Timestamp("2021-01-01")
FENETRE, N_ESSAIS, SEUIL_DSR = 52, 41, 0.95


# =============================================================================
#  Donnees COT
# =============================================================================
def cot() -> pd.DataFrame:
    """Rapports hebdomadaires (mardi) des 9 marches : interet ouvert, longs et courts des non-commerciaux et commerciaux."""
    morceaux = []
    for f in sorted(glob.glob(os.path.join(CFTC, "deacot*.zip"))):
        z = zipfile.ZipFile(f)
        d = pd.read_csv(z.open(z.namelist()[0]), low_memory=False)
        d.columns = [c.strip() for c in d.columns]
        code = d["CFTC Contract Market Code"].astype(str).str.strip()
        garde = code.isin(CODES)
        d = d.loc[garde, ["As of Date in Form YYYY-MM-DD", "Open Interest (All)", "Noncommercial Positions-Long (All)",
                          "Noncommercial Positions-Short (All)", "Commercial Positions-Long (All)",
                          "Commercial Positions-Short (All)"]].copy()
        d["code"] = code[garde].to_numpy()
        morceaux.append(pd.DataFrame({
            "marche": d.code.map(CODES), "date": pd.to_datetime(d["As of Date in Form YYYY-MM-DD"]),
            "oi": d["Open Interest (All)"].astype(float),
            "ncl": d["Noncommercial Positions-Long (All)"].astype(float), "ncs": d["Noncommercial Positions-Short (All)"].astype(float),
            "cl": d["Commercial Positions-Long (All)"].astype(float), "cs": d["Commercial Positions-Short (All)"].astype(float)}))
    c = pd.concat(morceaux).drop_duplicates(["marche", "date"]).sort_values(["marche", "date"]).reset_index(drop=True)
    c["publication"] = c.date + pd.Timedelta(days=3)                       # vendredi suivant le mardi de mesure
    c["net_spec"] = c.ncl - c.ncs
    c["q_spec"] = c.groupby("marche").net_spec.diff() / c.groupby("marche").oi.shift(1)
    c["sp_semaine"] = (c.ncl - c.ncs) / (c.ncl + c.ncs)
    return c


def signal_sp(c: pd.DataFrame, fins_de_mois: pd.DatetimeIndex) -> pd.DataFrame:
    """SP de FFFM20 a chaque fin de mois : moyenne des 52 derniers rapports PUBLIES (vendredi <= fin de mois)."""
    out = {}
    for mk, g in c.groupby("marche"):
        g = g.set_index("publication").sort_index()
        moy = g.sp_semaine.rolling(FENETRE, min_periods=FENETRE).mean()
        out[mk] = moy.reindex(fins_de_mois, method="ffill")
    return pd.DataFrame(out)


def poids_classe(signal: pd.DataFrame) -> pd.DataFrame:
    """Signal standardise dans chaque classe, poids = signal / somme des valeurs absolues ; portefeuille partout = moyenne
    a parts egales des classes."""
    w = pd.DataFrame(0.0, index=signal.index, columns=signal.columns)
    for cl, mks in CLASSES.items():
        s = signal[list(mks)]
        z = s.sub(s.mean(axis=1), axis=0).div(s.std(axis=1, ddof=0), axis=0)
        wc = z.div(z.abs().sum(axis=1), axis=0)
        w[list(mks)] = wc / len(CLASSES)
    return w.where(signal.notna().all(axis=1), np.nan, axis=0)


# =============================================================================
#  Rendements
# =============================================================================
def rendements() -> dict:
    out = {}
    for mk in CODES.values():
        m = marche(mk)
        out[mk] = (quotidien_futures(m), float(np.nanmedian(m.rc[-500000:])))
    return out


def mensuels(rq: dict) -> pd.DataFrame:
    return pd.DataFrame({mk: r.groupby(r.index.to_period("M")).sum() for mk, (r, _) in rq.items()})


def hebdo(rq: dict, jour: int) -> pd.DataFrame:
    """Rendement d une semaine se terminant le `jour` (0 = lundi) a la cloture, indexe par ce jour."""
    out = {}
    for mk, (r, _) in rq.items():
        cum = r.cumsum()
        fin = cum[cum.index.dayofweek == jour]
        out[mk] = fin.diff()
    return pd.DataFrame(out)


def cout_unitaire(mk: str, prix: float, ticks: int) -> float:
    tick, pv, _, _ = COUTS[mk]
    return (ticks * tick + COMMISSION / pv) / prix                           # par cote, fraction du notionnel


# =============================================================================
#  Etapes
# =============================================================================
def etape1(c: pd.DataFrame, rq: dict, rm: pd.DataFrame, sp: pd.DataFrame, pr) -> dict:
    res = {}
    mardi = hebdo(rq, 1)
    vendredi = hebdo(rq, 4)
    pr("  1a. variation hebdomadaire des positions des speculateurs (Q) et rendement mardi -> mardi de la meme semaine :")
    lignes = []
    for mk in CODES.values():
        g = c[c.marche == mk].set_index("date")
        x = pd.concat([g.q_spec, mardi[mk]], axis=1, join="inner").dropna()
        x.columns = ["q", "r"]
        meme = (np.sign(x.q) == np.sign(x.r)).mean()
        lignes.append(f"{mk} corr {x.q.corr(x.r):+.2f}, meme sens {meme:.0%}")
        res[("1a", mk)] = dict(corr=x.q.corr(x.r), meme_sens=meme)
    pr("      " + " | ".join(lignes))
    pr("  1b. Q publie le vendredi -> rendement du vendredi au vendredi suivant (pente en % de rendement par point de Q) :")
    for groupe, mks in (("matieres GC CL", ("GC", "CL")), ("devises", CLASSES["devises"]), ("indices", CLASSES["indices"])):
        lignes = []
        for lib, a, b in (("2016-2020", "2016-01-01", "2021-01-01"), ("2021-2026", "2021-01-01", "2027-01-01")):
            xs = []
            for mk in mks:
                g = c[c.marche == mk].set_index("publication").q_spec
                suiv = vendredi[mk].shift(-1)                                 # semaine qui suit la publication
                x = pd.concat([g, suiv], axis=1, join="inner").dropna()
                x.columns = ["q", "r"]
                xs.append(x[(x.index >= a) & (x.index < b)])
            x = pd.concat(xs)
            b_ = np.polyfit(x.q, x.r, 1)[0] if len(x) > 10 else math.nan
            res[("1b", groupe, lib)] = b_
            t_ = b_ / (np.std(x.r - np.polyval(np.polyfit(x.q, x.r, 1), x.q), ddof=2) / (x.q.std(ddof=1) * math.sqrt(len(x)))) if len(x) > 10 else math.nan
            lignes.append(f"{lib} pente {b_ * 100:+.2f} (t {t_:+.1f}, {len(x)} semaines)")
        pr(f"      {groupe:<15} " + " | ".join(lignes))
    pr("  1c. signal SP standardise dans sa classe -> rendement du mois suivant (regression empilee) :")
    z = pd.DataFrame(index=sp.index, columns=sp.columns, dtype=float)
    for cl, mks in CLASSES.items():
        s = sp[list(mks)]
        z[list(mks)] = s.sub(s.mean(axis=1), axis=0).div(s.std(axis=1, ddof=0), axis=0)
    zz = z.copy()
    zz.index = zz.index.to_period("M") + 1
    for lib, a, b in (("2016-2020", "2016-01", "2021-01"), ("2021-2026", "2021-01", "2027-01")):
        x = pd.concat([zz.stack().rename("z"), rm.stack().rename("r")], axis=1, join="inner").dropna()
        per = x.index.get_level_values(0)
        x = x[(per >= pd.Period(a, "M")) & (per < pd.Period(b, "M"))]
        pente = np.polyfit(x.z, x.r, 1)[0]
        resid = x.r - np.polyval(np.polyfit(x.z, x.r, 1), x.z)
        t_ = pente / (resid.std(ddof=2) / (x.z.std(ddof=1) * math.sqrt(len(x))))
        res[("1c", lib)] = dict(pente=pente, t=t_)
        pr(f"      {lib} : pente {pente * 100:+.2f} % de rendement mensuel par ecart-type de signal (t {t_:+.2f}, {len(x)} marche-mois)")
    return res


def portefeuille(w: pd.DataFrame, rm: pd.DataFrame, rq: dict, ticks: int) -> pd.Series:
    """Rendement mensuel net : poids decides a la fin du mois t, appliques au mois t+1 ; couts de rotation."""
    w = w.copy()
    w.index = w.index.to_period("M") + 1
    w = w.reindex(rm.index).dropna(how="all")
    brut = (w * rm.reindex(w.index)).sum(axis=1, min_count=1)
    cu = pd.Series({mk: cout_unitaire(mk, prix, ticks) for mk, (_, prix) in rq.items()})
    rot = w.fillna(0).diff().abs()
    rot.iloc[0] = w.iloc[0].abs().fillna(0)
    return (brut - (rot * cu).sum(axis=1)).dropna()


def etude(sortie: str | None = None, log=print) -> dict:
    t0 = datetime.now()
    L = []
    pr = L.append
    pr("=" * 118)
    pr(" PRESSION DE COUVERTURE / PRESSION SPECULATIVE (COT de la CFTC) : STRATEGIE CONSTRUITE SUR HUIT TRAVAUX")
    pr("=" * 118)
    pr("Protocole et sources : en-tete de nexus/perso/pression_cot.py (ecrit avant le calcul).\n")
    c = cot()
    rq = rendements()
    rm = mensuels(rq)
    fins = pd.DatetimeIndex([p.to_timestamp(how="end").normalize() for p in rm.index])
    sp = signal_sp(c, fins)
    pr(f"COT : {c.date.min():%Y-%m-%d} -> {c.date.max():%Y-%m-%d}, {len(c)} rapports ; rendements mensuels {rm.index[0]} -> {rm.index[-1]}.")
    pr("ETAPE 1 - l anomalie")
    e1 = etape1(c, rq, rm, sp, pr)

    pr("\nETAPE 2 - portefeuilles mensuels (poids de fin de mois, tenus le mois suivant), nets de couts")
    w_sp = poids_classe(sp)
    mom = pd.DataFrame({mk: rm[mk].rolling(12).sum() for mk in rm.columns})
    mom.index = fins
    w_mom = poids_classe(mom)
    res = {}
    v = portefeuille(w_sp, rm, rq, 1)
    v2 = portefeuille(w_sp, rm, rq, 2)
    tem = portefeuille(w_mom, rm, rq, 1)
    for code, serie, nom in (("V", v, "V partout (FFFM20, classes a parts egales)"),):
        x = serie * 1e4
        idx = serie.index.to_timestamp()
        x.index = idx
        tx = tem * 1e4
        tx.index = tem.index.to_timestamp()
        crit = criteres(x, tx, 0.0)                                     # x est deja net de couts
        p_dsr = dsr(serie, N_ESSAIS)
        sh = serie.mean() / serie.std(ddof=1) * math.sqrt(12)
        res[code] = dict(crit, dsr=p_dsr, sharpe_an=sh, stress=v2.mean() * 1e4, nom=nom)
        pr(f"  --- {nom} : {crit['n']} mois | net {crit['moyenne']:+.1f} pb/mois (t {crit['t']:+.2f}) | 2016-2020 {crit['m1']:+.1f} "
           f"(t {crit['t1']:+.2f}) | 2021-2026 {crit['m2']:+.1f} (t {crit['t2']:+.2f})")
        pr(f"      temoin momentum 12 mois {crit['temoin']:+.1f} pb/mois, Welch {crit['welch']:+.2f} | sans les 3 meilleurs mois "
           f"{crit['sans3']:+.1f} | stress 2 ticks {v2.mean() * 1e4:+.1f} | Sharpe annualise {sh:.2f} | Sharpe deflate "
           f"({N_ESSAIS} essais) {p_dsr:.2f}")
    for cl, mks in CLASSES.items():
        wc = w_sp.copy()
        wc[[m for m in wc.columns if m not in mks]] = 0.0
        s = portefeuille(wc * len(CLASSES), rm, rq, 1)
        sh = s.mean() / s.std(ddof=1) * math.sqrt(12)
        s1, s2 = s[s.index < pd.Period("2021-01", "M")], s[s.index >= pd.Period("2021-01", "M")]
        res[cl] = dict(moyenne=s.mean() * 1e4, t=tstat(s), sharpe_an=sh, t1=tstat(s1), t2=tstat(s2))
        pr(f"      classe {cl:<9} : {s.mean() * 1e4:+.1f} pb/mois (t {tstat(s):+.2f}), Sharpe {sh:.2f} | 2016-2020 t {tstat(s1):+.2f} | "
           f"2021-2026 t {tstat(s2):+.2f}")
    shm = tem.mean() / tem.std(ddof=1) * math.sqrt(12)
    pr(f"      temoin momentum partout : {tem.mean() * 1e4:+.1f} pb/mois (t {tstat(tem):+.2f}), Sharpe {shm:.2f} ; correlation V / "
       f"momentum {v.corr(tem.reindex(v.index)):+.2f}")
    vv = res["V"]
    echecs = [k for k, ok in vv["tests"].items() if not ok] + ([] if vv["dsr"] >= SEUIL_DSR else [f"Sharpe deflate >= {SEUIL_DSR:.2f}"])
    pr("\nVERDICT (V) : " + ("RETENUE" if not echecs else "ECHOUE (" + " ; ".join(echecs) + ")"))
    pr(f"Calcul en {(datetime.now() - t0).total_seconds():.0f} s.")
    sortie = sortie or os.path.join(PY_DIR, "recherche", "resultats_pression_cot.txt")
    with open(sortie, "w", encoding="utf-8") as fh:
        fh.write("\n".join(L) + "\n")
    exporter("pression_cot", dict(
        etape1={"1c_" + k[1]: v_ for k, v_ in e1.items() if k[0] == "1c"},
        contemporain={k[1]: v_ for k, v_ in e1.items() if k[0] == "1a"},
        semaine_suivante={f"{k[1]} {k[2]}": v_ for k, v_ in e1.items() if k[0] == "1b"},
        lignes=[dict(code="V", nom=vv["nom"], n=vv["n"], moyenne=vv["moyenne"], t=vv["t"], t1=vv["t1"], t2=vv["t2"],
                     temoin=vv["temoin"], welch=vv["welch"], sans3=vv["sans3"], dsr=vv["dsr"], sharpe_an=vv["sharpe_an"])]
        + [dict(code=cl, nom=f"classe {cl}", moyenne=x["moyenne"], t=x["t"], t1=x["t1"], t2=x["t2"], sharpe_an=x["sharpe_an"])
           for cl, x in res.items() if cl != "V"],
        echecs=echecs, retenue=not echecs))
    log("\n".join(L))
    return dict(etape1=e1, etape2=res, echecs=echecs)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--sortie", default=None)
    a = ap.parse_args(argv)
    etude(a.sortie)


if __name__ == "__main__":
    main()
