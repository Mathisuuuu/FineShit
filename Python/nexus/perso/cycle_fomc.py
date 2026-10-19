"""Cycle du FOMC et « Fed put » : strategie construite sur six travaux (Fed, Imperial College, Duke, Berkeley).

    python -m nexus.perso.cycle_fomc [--sortie resultats_cycle_fomc.txt]

PROTOCOLE ECRIT LE 2026-10-10, AVANT TOUT CALCUL SUR NOS DONNEES (methode : memoire « methode-strategie-papiers »).

Sources (texte complet lu = [T], resume ou introduction seulement = [R])
 [CMVJ] [T] A. Cieslak (Duke), A. Morse (Berkeley), A. Vissing-Jorgensen (Berkeley, puis Reserve federale),
        « Stock Returns over the FOMC Cycle », Journal of Finance 74 (5), 2019. Temps du cycle compte en jours de semaine
        (feries inclus avec un rendement nul), jour 0 = annonce d une reunion PROGRAMMEE : semaine 0 = jours -1 a 3,
        semaine 2 = 9 a 13, semaine 4 = 19 a 23, semaine 6 = 29 a 33 ; semaine -1 = jours -6 a -2 avant la reunion suivante.
        1994-2016 : toute la prime des actions est gagnee en semaines paires (+0,57 %, +0,33 %, +0,46 %, +0,60 % par
        semaine, semaines impaires ~0 ou negatives) ; regression : +14,1 pb par jour en semaine 0 et +10,9 pb en
        semaines 2-4-6 contre les semaines impaires ; strategie « semaines paires seulement » : Sharpe 0,92 contre 0,45.
        Mecanisme : informations de la Fed diffusees en semaines paires (reunions bimensuelles du conseil des gouverneurs
        sur le taux d escompte). « Fed put » : en classant les jours par le rendement en exces des 5 seances precedentes
        (t-5 a t-1), le quintile le plus bas est suivi de +30 pb par jour en semaine paire et d environ -5 pb en semaine
        impaire ; effet plus fort encore si le mois et les 3 mois precedents sont aussi dans leur quintile le plus bas.
 [UP25] [T] A. Uppal (Imperial College London ; passe par la Banque d Angleterre et la Fed), « Does the FOMC Cycle Still
        Drive Stock Returns? New Evidence from the US, UK, and Japan », document de travail, mars 2025 : hors echantillon,
        2017-2023, semaine 0 : -13,9 pb (t -1,58), semaines 2-4-6 : -0,8 pb (t -0,13) ; deja non significatif en
        2004-2013 ; avant 2004, quelques journees aberrantes portent le resultat ; les reunions du conseil ne sont plus
        bimensuelles apres 2004 (fin du canal propose) ; aucun effet sur les taux ; Royaume-Uni et Japon : rien une fois
        l effet d avant-annonce retire. Il ne teste PAS la version conditionnelle (« Fed put ») de CMVJ.
 [CV21] [T, resume et introduction] A. Cieslak & A. Vissing-Jorgensen, « The Economics of the Fed Put », Review of
        Financial Studies 34 (9), 2021 : depuis le milieu des annees 1990, les baisses de la bourse precedent des
        assouplissements de la Fed (via ses previsions de croissance) ; la Fed reagit aux rendements d au moins deux
        intervalles entre reunions.
 [LM15] [T, resume] D. Lucca & E. Moench (Fed de New York), « The Pre-FOMC Announcement Drift », Journal of Finance 2015
        (Staff Report 512) : +49 pb de 14:00 la veille a 14:00 le jour de l annonce, 1994-2011.
 [KW21] [R] A. Kurov, M. Wolfe & T. Gilbert, « The disappearing pre-FOMC announcement drift », Finance Research Letters 2021 :
        la derive d avant-annonce disparait apres 2015.
 [FN20] [T] J. McCoy, M. Modugno, D. Palazzo, S. Sharpe (Reserve federale), FEDS Notes, 14/10/2020 : entre deux reunions,
        les surprises macroeconomiques expliquent environ 20 % des rendements de la bourse (activite +, prix -).
Lecture commune : la version simple (semaines paires) est refutee hors echantillon par UP25, avec un mecanisme eteint
depuis 2004 ; la seule partie de CMVJ que personne n a refutee est sa version conditionnelle (« Fed put »), dont le
mecanisme de fond (la Fed soutient apres les baisses, CV21) existe toujours. Strategie retenue : la version « Fed put »
de CMVJ, telle quelle. Les deux lectures font des predictions opposees, ce qui rend le test informatif : si la Fed
soutient toujours le marche apres une baisse et que l information arrive en semaine paire, V survit apres 2004 ; si UP25
a raison sur le mecanisme, V disparait comme la version simple.

Donnees
  - marche americain, rendement quotidien en exces du taux sans risque (bibliotheque de Kenneth French, gratuite) :
    1994-2026, decoupe d UP25 (1994-2003 / 2004-2016) puis 2017-2026 qu aucun papier n a vu ;
  - futures ES (Databento), cloture 16:00 ET -> 16:00 ET au prix reel du contrat, 2016-2026 (instrument negociable) ;
  - reunions programmees du FOMC 1994-2026 : fomc_programmees.csv (site de la Reserve federale).

ETAPE 1 - l anomalie
  1a. regression des rendements quotidiens sur une variable semaine 0 et une variable semaines 2-4-6 (CMVJ tableau 1,
      UP25 tableau 3), erreurs robustes, par periode ;
  1b. « Fed put » : rendement moyen des jours de semaine paire et impaire apres un rendement des 5 seances precedentes
      dans le quintile le plus bas (seuil calcule sur toutes les seances PASSEES, au moins 250), par periode.
ETAPE 2 - strategie V (regles figees, CMVJ section b.4) :
  - etre achete le jour t (cloture t-1 -> cloture t) si t est en semaine 0, 2, 4 ou 6 du cycle ET si le rendement des
    seances t-5 a t-1 est dans le quintile le plus bas de toutes les seances passees ; sinon a plat ;
  - reference R0 = semaines paires seulement, sans condition (strategie B de CMVJ) ; temoin = jours de semaine impaire
    apres la meme baisse (CMVJ : environ -5 pb) ;
  - sur l ES : seuil de quintile calcule sur l historique propre de l ES (croissant depuis 2016, 250 seances au moins) ;
    couts : 1 tick + 2,50 $ par cote a chaque entree et sortie, stress 2 ticks.
  Criteres (fixes avant le calcul) pour V sur l ES, net de couts : criteres des 60 strategies (t >= 3 ; meme signe et
  t >= 1,5 sur 2016-2020 et 2021-2026 ; Welch >= 2 contre le temoin ; net > 0 ; net > 0 sans les 3 meilleurs jours ;
  moins de 60 cas : t >= 2 et net positif >= 65 % des annees) ET Sharpe deflate >= 0,95 pour 40 essais (38 precedents +
  R0 et V) ET, sur le marche Ken French 2017-2026 jamais vu, jours V : moyenne > 0 avec t >= 1,5.
Compatibilite prop firm : position tenue de cloture a cloture (nuits comprises) : NON compatible avec une prop firm
intraday ; une version intraday serait un autre essai.
"""
from __future__ import annotations

import argparse
import math
import os
from datetime import datetime

import numpy as np
import pandas as pd

from .alternatives import dsr
from .soixante import COMMISSION, COUTS, PY_DIR, criteres, exporter, marche, tstat
from .vol_geree import marche_french, quotidien_futures

ICI = os.path.dirname(__file__)
PERIODES = (("1994-2003", "1994-01-01", "2004-01-01"), ("2004-2016", "2004-01-01", "2017-01-01"),
            ("2017-2026", "2017-01-01", "2027-01-01"))
N_ESSAIS, SEUIL_DSR, Q_BAS, N_MIN = 40, 0.95, 0.2, 250
PAIRES = (0, 2, 4, 6)


def fomc() -> pd.DatetimeIndex:
    return pd.DatetimeIndex(pd.to_datetime(pd.read_csv(os.path.join(ICI, "fomc_programmees.csv"), comment="#").date))


# =============================================================================
#  Temps du cycle (CMVJ)
# =============================================================================
def semaine_cycle(jours: pd.DatetimeIndex, reunions: pd.DatetimeIndex | None = None) -> pd.Series:
    """Semaine du cycle du FOMC de chaque jour, comptee en jours de semaine (feries inclus) : 0 = jours -1 a 3 ; 1 = 4 a 8 ;
    2 = 9 a 13 ; ... ; -1 = jours -6 a -2 avant la reunion suivante (prioritaire). NaN avant la premiere reunion."""
    reunions = fomc() if reunions is None else pd.DatetimeIndex(reunions)
    jours = pd.DatetimeIndex(jours)
    cal = pd.bdate_range(min(jours.min(), reunions.min()) - pd.Timedelta(days=60), max(jours.max(), reunions.max()) + pd.Timedelta(days=60))
    pos = pd.Series(np.arange(len(cal)), index=cal)
    pj = pos.reindex(jours).to_numpy()
    pr_ = pos.reindex(reunions).to_numpy()
    out = np.full(len(jours), np.nan)
    for k, p in enumerate(pj):
        if not np.isfinite(p):
            continue
        suiv = pr_[pr_ >= p]
        prec = pr_[pr_ <= p]
        if len(suiv):
            avant = suiv[0] - p                          # jours de semaine jusqu a la prochaine annonce
            if avant <= 1:
                out[k] = 0
                continue
            if avant <= 6:
                out[k] = -1
                continue
        if len(prec):
            d = p - prec[-1]
            out[k] = (d + 1) // 5
    return pd.Series(out, index=jours)


def fed_put(r: pd.Series) -> pd.Series:
    """True si le rendement des 5 seances precedentes (t-5 a t-1) est dans le quintile le plus bas de toutes les seances
    passees (temps reel, au moins N_MIN valeurs)."""
    r5 = r.rolling(5).sum().shift(1)
    seuil = r5.expanding(min_periods=N_MIN).quantile(Q_BAS).shift(1)
    return (r5 <= seuil) & seuil.notna()


# =============================================================================
#  Statistiques
# =============================================================================
def regression_robuste(y: pd.Series, X: pd.DataFrame) -> tuple[np.ndarray, np.ndarray]:
    d = pd.concat([y.rename("y"), X], axis=1).dropna()
    A = np.column_stack([np.ones(len(d))] + [d[c].to_numpy(float) for c in X.columns])
    b, *_ = np.linalg.lstsq(A, d.y.to_numpy(), rcond=None)
    e = d.y.to_numpy() - A @ b
    inv = np.linalg.inv(A.T @ A)
    cov = inv @ (A.T * e ** 2) @ A @ inv
    return b, b / np.sqrt(np.diag(cov))


def etape1(nom: str, r: pd.Series, periodes, pr) -> dict:
    sem = semaine_cycle(r.index)
    put = fed_put(r)
    paire = sem.isin(PAIRES)
    impaire = sem.notna() & ~paire
    res = {}
    for lib, a, b in periodes:
        sel = (r.index >= a) & (r.index < b) & sem.notna().to_numpy()
        if sel.sum() < 100:
            continue
        x = r[sel] * 1e4
        X = pd.DataFrame({"s0": (sem[sel] == 0).astype(float), "s246": sem[sel].isin([2, 4, 6]).astype(float)})
        coef, t = regression_robuste(x, X)
        dp, di = x[(paire & put)[sel]], x[(impaire & put)[sel]]
        res[lib] = dict(s0=coef[1], t0=t[1], s246=coef[2], t246=t[2], put_paire=dp.mean(), t_pp=tstat(dp), n_pp=len(dp),
                        put_impaire=di.mean(), t_pi=tstat(di), n_pi=len(di))
        pr(f"  {nom} {lib} : semaine 0 {coef[1]:+.1f} pb/j (t {t[1]:+.2f}) | semaines 2-4-6 {coef[2]:+.1f} pb/j (t {t[2]:+.2f}) "
           f"| Fed put : paire {dp.mean():+.1f} pb (t {tstat(dp):+.1f}, {len(dp)} j), impaire {di.mean():+.1f} pb "
           f"(t {tstat(di):+.1f}, {len(di)} j)")
    return res


def cout_unitaire(root: str, prix: float, ticks: int) -> float:
    tick, pv, _, _ = COUTS[root]
    return (ticks * tick + COMMISSION / pv) / prix * 1e4                 # par cote, en pb


def net_des_entrees(pos: pd.Series, r_pb: pd.Series, c: float) -> pd.Series:
    """Rendement net par jour investi : cout d un cote le jour d entree et d un cote le jour de sortie."""
    p = pos.astype(int)
    entree = (p.diff().fillna(p) == 1)
    sortie = (p.shift(-1).fillna(0) - p == -1)
    net = r_pb - c * entree.astype(float) - c * sortie.astype(float)
    return net[p == 1]


def etude(sortie: str | None = None, log=print) -> dict:
    t0 = datetime.now()
    L = []
    pr = L.append
    pr("=" * 118)
    pr(" CYCLE DU FOMC ET « FED PUT » : STRATEGIE CONSTRUITE SUR SIX TRAVAUX (CMVJ 2019, UPPAL 2025, CIESLAK & VJ 2021...)")
    pr("=" * 118)
    pr("Protocole et sources : en-tete de nexus/perso/cycle_fomc.py (ecrit avant le calcul).\n")
    mk = marche_french()
    m = marche("ES")
    es = quotidien_futures(m)
    pr("ETAPE 1 - l anomalie (pb par jour)")
    e1_mk = etape1("marche", mk, PERIODES, pr)                   # seuil du quintile : tout l historique depuis 1926
    e1_es = etape1("ES", es, (("2016-2020", "2016-01-01", "2021-01-01"), ("2021-2026", "2021-01-01", "2027-01-01"),
                              ("2016-2026", "2016-01-01", "2027-01-01")), pr)

    pr("\nETAPE 2 - strategies sur l ES (cloture -> cloture), nettes de couts")
    sem = semaine_cycle(es.index)
    put = fed_put(es)
    paire = sem.isin(PAIRES)
    impaire = sem.notna() & ~paire
    prix = float(np.nanmedian(m.rc[-500000:]))
    c1, c2 = cout_unitaire("ES", prix, 1), cout_unitaire("ES", prix, 2)
    r_pb = es * 1e4
    res = {}
    for code, pos, tem, nom in (("R0", paire, impaire, "R0 semaines paires seulement (CMVJ, strategie B)"),
                                ("V", paire & put, impaire & put, "V Fed put : semaine paire apres une baisse (quintile bas des 5 seances)")):
        net1 = net_des_entrees(pos, r_pb, c1)
        net2 = net_des_entrees(pos, r_pb, c2)
        brut = r_pb[pos]
        c = criteres(brut, r_pb[tem], (brut.mean() - net1.mean()))
        p_dsr = dsr(net1 / 1e4, N_ESSAIS)
        ans = (es.index[-1] - es.index[0]).days / 365.25
        sh = net1.mean() / net1.std(ddof=1) * math.sqrt(len(net1) / ans) if len(net1) > 2 else math.nan
        sh_bh = r_pb.mean() / r_pb.std(ddof=1) * math.sqrt(252)
        entrees = int((pos.astype(int).diff().fillna(pos.astype(int)) == 1).sum())
        res[code] = dict(c, dsr=p_dsr, sharpe_an=sh, n_entrees=entrees, net_stress=net2.mean(), nom=nom)
        pr(f"  --- {nom}")
        pr(f"      {c['n']} jours investis ({entrees} entrees) | brut {c['moyenne']:+.2f} pb/j (t {c['t']:+.1f}) | 2016-2020 "
           f"{c['m1']:+.2f} (t {c['t1']:+.1f}) | 2021-2026 {c['m2']:+.2f} (t {c['t2']:+.1f})")
        pr(f"      temoin (semaine impaire, meme condition) {c['temoin']:+.2f} pb, Welch {c['welch']:+.1f} | cout moyen "
           f"{c['cout']:.2f} pb/j -> net {c['net']:+.2f} pb/j, sans les 3 meilleurs jours {c['sans3']:+.2f} | stress {net2.mean():+.2f}")
        pr(f"      Sharpe net annualise {sh:.2f} (ES detenu {sh_bh:.2f}) | Sharpe deflate ({N_ESSAIS} essais) {p_dsr:.2f}"
           + (f" | annees nettes positives {c['part_annees']:.0%}" if c["rare"] else ""))
    v = res["V"]
    post = e1_mk.get("2017-2026", {})
    hors = post.get("put_paire", math.nan) > 0 and post.get("t_pp", math.nan) >= 1.5
    echecs = [k for k, ok in v["tests"].items() if not ok]
    if v["dsr"] < SEUIL_DSR:
        echecs.append(f"Sharpe deflate >= {SEUIL_DSR:.2f}")
    if not hors:
        echecs.append("marche 2017-2026 : jours V > 0 avec t >= 1,5")
    pr("\nVERDICT (V sur l ES) : " + ("RETENUE" if not echecs else "ECHOUE (" + " ; ".join(echecs) + ")"))
    pr(f"Calcul en {(datetime.now() - t0).total_seconds():.0f} s.")
    sortie = sortie or os.path.join(PY_DIR, "recherche", "resultats_cycle_fomc.txt")
    with open(sortie, "w", encoding="utf-8") as fh:
        fh.write("\n".join(L) + "\n")
    exporter("cycle_fomc", dict(
        etape1_marche=e1_mk, etape1_es=e1_es,
        lignes=[dict(code=k, nom=x["nom"], n=x["n"], moyenne=x["moyenne"], t=x["t"], t1=x["t1"], t2=x["t2"], temoin=x["temoin"],
                     welch=x["welch"], net=x["net"], sans3=x["sans3"], dsr=x["dsr"], sharpe_an=x["sharpe_an"],
                     entrees=x["n_entrees"]) for k, x in res.items()],
        echecs=echecs, retenue=not echecs))
    log("\n".join(L))
    return dict(etape1_marche=e1_mk, etape1_es=e1_es, etape2=res, echecs=echecs)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--sortie", default=None)
    a = ap.parse_args(argv)
    etude(a.sortie)


if __name__ == "__main__":
    main()
