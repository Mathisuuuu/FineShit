"""Exposition aux futures d indices actions geree par la volatilite : strategie construite sur neuf papiers.

    python -m nexus.perso.vol_geree [--sortie resultats_vol_geree.txt]

PROTOCOLE ECRIT LE 2026-10-10, AVANT TOUT CALCUL SUR NOS DONNEES (methode : memoire « methode-strategie-papiers »).

Sources (texte complet lu = [T], resume seulement = [R])
 [MM17] [T] A. Moreira & T. Muir (Yale), « Volatility-Managed Portfolios », Journal of Finance 72 (4), 2017 (NBER w22208) :
        exposition du mois = c / variance realisee du mois precedent (22 rendements quotidiens) ; marche 1926-2015 : alpha
        4,86 % par an, beta 0,6 ; meme Sharpe en divisant par la volatilite plutot que la variance, ou avec un levier plafonne
        a 1 ou 1,5 ; la constante c est fixee sur tout l echantillon (selon eux sans effet sur le Sharpe).
 [CO20] [T] S. Cederburg, M. O Doherty, F. Wang & X. Yan, « On the performance of volatility-managed portfolios », Journal of
        Financial Economics 138, 2020 : marche 1926-2016, Sharpe 0,42 -> 0,51 en comparaison directe, ecart NON significatif
        (p = 0,30) ; en temps reel, la combinaison gere + non gere fait 0,42 contre 0,46 pour le marche seul ; cause :
        instabilite des regressions et des poids estimes ; 72 strategies sur 103 perdent en temps reel.
 [HA18] [T] C. Harvey (Duke), E. Hoyle, R. Korgaonkar, S. Rattray, M. Sargaison, O. Van Hemert (Man Group), « The Impact of
        Volatility Targeting », Journal of Portfolio Management 45 (1), 2018 : actions americaines 1927-2017, Sharpe 0,40 ->
        0,48-0,51, alpha quotidien 0,64 pb (t 3,05, Newey-West 30 retards) ; effet du « levier » (la volatilite monte quand
        les cours baissent) : gain pour les actions et le credit, NEGLIGEABLE pour les obligations, devises et matieres
        premieres ; queues de distribution reduites partout ; couts 1 pb par transaction sur les actions.
 [BK20] [T] D. Bongaerts, X. Kang & M. van Dijk (Erasmus), « Conditional Volatility Targeting », Financial Analysts Journal
        76 (4), 2020 : sans aucun regard vers le futur, la version classique n ameliore pas durablement les marches d actions
        (+0,15 de Sharpe aux Etats-Unis 1982-2019, quasi rien ailleurs) et augmente souvent les pertes extremes ; version
        CONDITIONNELLE : mois classe par le quintile de la volatilite du mois precedent parmi TOUS les mois passes ; quintile
        haut : exposition = cible / volatilite (reduite) ; quintile bas : min(cible / volatilite, 200 %) ; sinon 100 % ;
        cible = volatilite de long terme de toutes les donnees passees (au moins 10 ans) ; volatilite du mois precedent sans
        son dernier jour (connue la veille du reequilibrage) ; couts 3 a 5 pb ; moins de rotation et de pertes extremes.
 [WY21] [T] F. Wang & X. Yan, « Downside risk and the performance of volatility-managed portfolios », Journal of Banking and
        Finance 131, 2021 : la volatilite des seules baisses fait mieux ; des poids fixes evitent l instabilite des
        estimations.
 [DM24] [T, introduction] V. DeMiguel (LBS), A. Martin-Utrera, R. Uppal (EDHEC), « A Multifactor Perspective on
        Volatility-Managed Portfolios », Journal of Finance 2024 : seule une version multi-facteurs tient hors echantillon ;
        rappelle que Barroso & Detzel trouvent que les couts effacent le gain pour tous les facteurs sauf le marche.
 [BD21] [R] P. Barroso (UNSW) & A. Detzel (Denver), « Do limits to arbitrage explain the benefits of volatility-managed
        portfolios? », Journal of Financial Economics 140, 2021 : apres couts, seul le marche garde un alpha, et seulement
        en periode d optimisme eleve des investisseurs.
 [LT19] [R] F. Liu, X. Tang & G. Zhou, « Volatility-managed portfolio: Does it really work? », Journal of Portfolio Management
        46 (1), 2019 : la version de MM17 a un biais d anticipation (constante c) ; corrigee, pertes maximales de 68 a 93 %
        avec levier ; surperformance limitee a la crise financiere.
 [MM19] [R] A. Moreira & T. Muir, « Should long-term investors time volatility? », Journal of Financial Economics, 2019 :
        ignorer la volatilite coute environ 2,4 % de richesse par an a un investisseur de long terme.
Lecture commune : le gain existe surtout pour le MARCHE actions (HA18, BD21, BK20), il est faible et fragile en temps reel
(CO20, LT19), les choix faits sur tout l echantillon (constante c, poids optimaux) et le levier sans limite sont a
proscrire (CO20, LT19, BK20), et la version conditionnelle aux extremes de volatilite repond a ces critiques avec peu de
rotation (BK20). Strategie retenue : la version conditionnelle de BK20, telle quelle.

Donnees
  - marche americain, rendements quotidiens en exces du taux sans risque, juillet 1926 - aout 2026 : bibliotheque de
    Kenneth French (gratuite). Sert a l etape 1 (long historique, avant et APRES publication : 2017-2026 n a ete vu par
    aucun de ces papiers) et fournit l historique long dont BK20 a besoin (quintiles, cible) ;
  - futures ES, NQ, YM (actions) et GC, CL, 6E, 6B, 6J, 6A (temoin) : cloture a 16:00 ET des minutes Databento 2016-2026,
    prix reel du contrat, jour exclu au changement d echeance.

ETAPE 1 - l anomalie (sur le marche, 1926-2026, et par periode : 1936-2016 vu par les papiers / 2017-2026 jamais vu)
  1a. rendement et volatilite du mois suivant par quintile de volatilite du mois precedent (HA18 exhibit 4) : la
      volatilite persiste, le rendement ne suit pas proportionnellement ;
  1b. alpha de la version classique en temps reel (R1) et de la version conditionnelle (V) contre le marche ;
  1c. prediction de HA18 sur nos futures (2018-2026, volatilite propre de chaque contrat, historique croissant depuis 2016) :
      gain de Sharpe de la version classique pour ES, NQ, YM, et pas pour GC, CL, 6E, 6B, 6J, 6A.
ETAPE 2 - strategie V sur les futures d indices (regles figees, BK20) :
  - reequilibrage le premier jour de chaque mois ; vol_m-1 = ecart-type annualise des rendements quotidiens du mois
    precedent sans son dernier jour ; etat = quintile de vol_m-1 parmi tous les mois passes du marche americain (Ken
    French, depuis 1926) ; cible = volatilite de long terme de toutes les donnees passees du marche ;
  - exposition : quintile haut -> cible / vol_m-1 ; quintile bas -> min(cible / vol_m-1, 2) ; sinon 1 ;
  - la meme exposition s applique a ES, YM et NQ (etat du marche americain ; on verifie que la volatilite mensuelle de l ES
    suit celle du marche) ; reference R0 = exposition 1 en permanence ; R1 = version classique en temps reel (cible /
    vol_m-1, plafond 2) rapportee sans optimisation ;
  - couts : |variation d exposition| x (1 tick + 2,50 $) par cote, au prix median ; stress a 2 ticks.
  Criteres (fixes avant le calcul) pour V sur l ES, net de couts, 2016-2026 :
    C1 alpha de V contre l ES detenu en permanence (regression quotidienne, Newey-West 30 retards) : t >= 3 ;
    C2 alpha > 0 avec t >= 1,5 sur 2016-2020 ET sur 2021-2026 ;
    C3 temoin (HA18) : le gain de Sharpe de la version classique est plus grand en moyenne sur ES, NQ, YM que sur GC, CL,
       6E, 6B, 6J, 6A ;
    C4 Sharpe net de V > Sharpe de l ES detenu ET perte maximale de V < celle de l ES detenu (objectifs de BK20) ;
    C5 alpha encore > 0 sans les 3 meilleurs jours de la serie couverte (V - beta x ES) ;
    C6 Sharpe deflate de la serie couverte >= 0,95 pour 38 essais (36 precedents + R1 et V) ;
    C7 hors echantillon des papiers : sur le marche Ken French 2017-2026, alpha de V > 0 avec t >= 1,5.
  Retenue si les sept criteres passent. Rien n est retouche apres le calcul.
Compatibilite prop firm : position tenue en continu (nuits, week-ends) : NON compatible avec une prop firm intraday ;
utilisable comme regle de taille pour un compte personnel ou pour moduler l exposition d autres strategies.
"""
from __future__ import annotations

import argparse
import math
import os
from datetime import datetime

import numpy as np
import pandas as pd

from .alternatives import dsr
from .soixante import COMMISSION, COUTS, PY_DIR, contrats, exporter, marche

FRENCH = os.path.join(PY_DIR, ".cache", "french", "F-F_Research_Data_Factors_daily.csv")
PUBLICATION = pd.Timestamp("2017-01-01")          # MM17 publie en 2017 ; CO20 s arrete fin 2016
COUPURE = pd.Timestamp("2021-01-01")
LEVIER_MAX, Q_HAUT, Q_BAS, MOIS_MIN = 2.0, 0.8, 0.2, 120
N_ESSAIS, SEUIL_DSR, NW_RETARDS = 38, 0.95, 30
ACTIONS, TEMOINS = ("ES", "NQ", "YM"), ("GC", "CL", "6E", "6B", "6J", "6A")


# =============================================================================
#  Donnees
# =============================================================================
def marche_french() -> pd.Series:
    """Rendement quotidien du marche americain en exces du taux sans risque (decimal), 1926-2026."""
    lignes = []
    with open(FRENCH, encoding="utf-8", errors="ignore") as fh:
        for l in fh:
            p = l.strip().split(",")
            if len(p) >= 5 and p[0].strip().isdigit() and len(p[0].strip()) == 8:
                lignes.append((p[0].strip(), float(p[1])))
    s = pd.Series([v / 100 for _, v in lignes], index=pd.to_datetime([d for d, _ in lignes], format="%Y%m%d"))
    return s.sort_index()


def quotidien_futures(m) -> pd.Series:
    """Rendement quotidien cloture 16:00 ET -> 16:00 ET au prix reel du contrat ; NaN au changement d echeance."""
    sel = np.nonzero(m.tod <= 16 * 60)[0]
    df = pd.DataFrame({"jour": m.jour[sel], "i": sel})
    der = df.groupby("jour").i.max()
    idx = der.to_numpy()
    rc = np.where(np.isfinite(m.rc[idx]) & (m.rc[idx] > 0), m.rc[idx], np.nan)
    cid = contrats(m)[idx]
    r = np.r_[np.nan, np.log(rc[1:] / rc[:-1])]
    r[np.r_[False, cid[1:] != cid[:-1]]] = np.nan
    s = pd.Series(r, index=pd.to_datetime(der.index.to_numpy() * 86_400_000_000_000))
    return s[s.index.dayofweek < 5].dropna()


# =============================================================================
#  Signal mensuel (temps reel)
# =============================================================================
def vol_mensuelle(r: pd.Series) -> pd.DataFrame:
    """Par mois : volatilite annualisee sans le dernier jour du mois, et volatilite de long terme de tout le passe."""
    mois = r.index.to_period("M")
    out = []
    cum_n, cum_s2 = 0, 0.0
    for p, g in r.groupby(mois):
        x = g.to_numpy()
        sans_dernier = x[:-1]
        v = np.std(sans_dernier, ddof=1) * math.sqrt(252) if len(sans_dernier) >= 5 else np.nan
        cum_n += len(sans_dernier)
        cum_s2 += float(np.sum(sans_dernier ** 2))
        out.append((p, v, math.sqrt(cum_s2 / max(cum_n, 1) * 252)))
    d = pd.DataFrame(out, columns=["mois", "vol", "cible"]).set_index("mois")
    rang = [np.nan] * len(d)
    vols = d.vol.to_numpy()
    for k in range(len(d)):
        passe = vols[: k + 1]
        passe = passe[np.isfinite(passe)]
        if len(passe) >= MOIS_MIN:
            rang[k] = float((passe <= vols[k]).mean())                   # quantile de vol_m-1 parmi tous les mois passes
    d["rang"] = rang
    return d


def expositions(d: pd.DataFrame) -> pd.DataFrame:
    """Exposition du mois SUIVANT : R1 classique (plafond 2) et V conditionnelle (BK20)."""
    ratio = d.cible / d.vol
    r1 = np.minimum(ratio, LEVIER_MAX)
    v = np.where(d.rang >= Q_HAUT, ratio, np.where(d.rang <= Q_BAS, np.minimum(ratio, LEVIER_MAX), 1.0))
    e = pd.DataFrame({"R1": r1, "V": v, "etat": np.where(d.rang >= Q_HAUT, "haut", np.where(d.rang <= Q_BAS, "bas", "moyen"))},
                     index=d.index)
    e = e[d.rang.notna().to_numpy()]
    e.index = e.index + 1                                               # decision de fin de mois -> mois suivant
    return e


def appliquer(r: pd.Series, expo: pd.Series) -> pd.Series:
    w = expo.reindex(r.index.to_period("M")).to_numpy()
    return pd.Series(w, index=r.index)


# =============================================================================
#  Statistiques
# =============================================================================
def newey_west(y: pd.Series, x: pd.Series, lags: int = NW_RETARDS) -> dict:
    d = pd.concat([y.rename("y"), x.rename("x")], axis=1).dropna()
    X = np.column_stack([np.ones(len(d)), d.x.to_numpy()])
    yv = d.y.to_numpy()
    b, *_ = np.linalg.lstsq(X, yv, rcond=None)
    e = yv - X @ b
    Xe = X * e[:, None]
    S = Xe.T @ Xe
    for L in range(1, lags + 1):
        w = 1 - L / (lags + 1)
        G = Xe[L:].T @ Xe[:-L]
        S += w * (G + G.T)
    inv = np.linalg.inv(X.T @ X)
    cov = inv @ S @ inv
    return dict(alpha=b[0], t=b[0] / math.sqrt(cov[0, 0]), beta=b[1], n=len(d), residus=pd.Series(e + b[0], index=d.index))


def sharpe(x: pd.Series) -> float:
    x = x.dropna()
    return float(x.mean() / x.std(ddof=1) * math.sqrt(252)) if len(x) > 20 and x.std(ddof=1) > 0 else math.nan


def perte_max(x: pd.Series) -> float:
    v = np.exp(x.fillna(0).cumsum()) if (x.abs() < 1).all() else (1 + x).cumprod()
    return float((v / v.cummax() - 1).min())


# =============================================================================
#  Etapes
# =============================================================================
def etape1(mk: pd.Series, expo: pd.DataFrame, pr) -> dict:
    d = vol_mensuelle(mk)
    rm = mk.groupby(mk.index.to_period("M")).sum()
    vol_suiv = d.vol.shift(-1)
    rend_suiv = rm.reindex(d.index).shift(-1) * 12
    res = {}
    for lib, sel in (("1936-2016", (d.index >= pd.Period("1936-07", "M")) & (d.index < pd.Period("2017-01", "M"))),
                     ("2017-2026", d.index >= pd.Period("2017-01", "M"))):
        q = pd.qcut(d.vol[sel], 5, labels=False)
        tab = pd.DataFrame({"rend": rend_suiv[sel], "vol": vol_suiv[sel], "q": q}).groupby("q").mean()
        pr(f"  1a. {lib} - mois suivant par quintile de volatilite du mois (1 = calme, 5 = agite) : " +
           " | ".join(f"Q{int(k) + 1} rend. {r * 100:+.1f} %/an, vol {v * 100:.0f} %" for k, (r, v) in tab.iterrows()))
    for code in ("R1", "V"):
        w = appliquer(mk, expo[code])
        g = w * mk
        for lib, sel in (("1936-2016 (vu par les papiers)", (mk.index >= "1936-07-01") & (mk.index < PUBLICATION)),
                         ("2017-2026 (jamais vu)", mk.index >= PUBLICATION)):
            s = sel & w.notna().to_numpy()
            nw = newey_west(g[s], mk[s])
            pr(f"  1b. {code} {lib} : alpha {nw['alpha'] * 252 * 100:+.2f} %/an (t {nw['t']:+.2f}), beta {nw['beta']:.2f} | "
               f"Sharpe {sharpe(g[s]):.2f} contre {sharpe(mk[s]):.2f} | perte max {perte_max(g[s]) * 100:.0f} % contre "
               f"{perte_max(mk[s]) * 100:.0f} % | exposition moyenne {w[s].mean():.2f}")
            res[(code, lib[:9])] = nw
    etat = expo.etat.value_counts(normalize=True)
    pr(f"      part des mois par etat (V) : " + ", ".join(f"{k} {v:.0%}" for k, v in etat.items()))
    return res


def conventionnelle_propre(r: pd.Series, burn: int = 24) -> pd.Series:
    """Version classique en temps reel avec la volatilite propre du contrat (historique croissant depuis 2016)."""
    d = vol_mensuelle(r)
    ratio = np.minimum(d.cible / d.vol, LEVIER_MAX)
    ratio[np.arange(len(d)) < burn] = np.nan
    ratio.index = ratio.index + 1
    return appliquer(r, ratio)


def cout_unitaire(root: str, prix: float, ticks: int) -> float:
    tick, pv, _, _ = COUTS[root]
    return (ticks * tick + COMMISSION / pv) / prix                         # par cote, en fraction du notionnel


def etude(sortie: str | None = None, log=print) -> dict:
    t0 = datetime.now()
    L = []
    pr = L.append
    pr("=" * 118)
    pr(" EXPOSITION GEREE PAR LA VOLATILITE (futures d indices) : STRATEGIE CONSTRUITE SUR NEUF PAPIERS")
    pr("=" * 118)
    pr("Protocole et sources : en-tete de nexus/perso/vol_geree.py (ecrit avant le calcul).\n")
    mk = marche_french()
    expo = expositions(vol_mensuelle(mk))
    pr(f"Marche americain (Ken French) : {mk.index[0]:%Y-%m-%d} -> {mk.index[-1]:%Y-%m-%d}, {len(mk)} jours.")
    pr("ETAPE 1 - l anomalie")
    e1 = etape1(mk, expo, pr)

    pr("  1c. prediction de Harvey et al. sur nos futures (version classique, volatilite propre, 2018-2026) :")
    gains, rets = {}, {}
    for root in ACTIONS + TEMOINS:
        m = marche(root)
        r = quotidien_futures(m)
        rets[root] = (r, m)
        w = conventionnelle_propre(r)
        s = w.notna()
        gains[root] = sharpe((w * r)[s]) - sharpe(r[s])
        pr(f"      {root:<3} Sharpe {sharpe(r[s]):+.2f} -> {sharpe((w * r)[s]):+.2f} (gain {gains[root]:+.2f}) | perte max "
           f"{perte_max(r[s]) * 100:.0f} % -> {perte_max((w * r)[s]) * 100:.0f} %")
    g_act, g_tem = np.mean([gains[k] for k in ACTIONS]), np.mean([gains[k] for k in TEMOINS])
    c3 = g_act > g_tem
    pr(f"      gain moyen : actions {g_act:+.2f}, temoins {g_tem:+.2f} -> prediction {'verifiee' if c3 else 'NON verifiee'}")

    pr("\nETAPE 2 - strategie V (conditionnelle, BK20) sur les futures d indices, net de couts")
    res = {}
    mens = vol_mensuelle(mk)
    es_r = rets["ES"][0]
    ve = vol_mensuelle(es_r)
    commun = ve.index.intersection(mens.index)
    pr(f"  controle : correlation des volatilites mensuelles ES / marche americain {ve.vol[commun].corr(mens.vol[commun]):.2f}, "
       f"rapport moyen {(ve.vol[commun] / mens.vol[commun]).mean():.2f}")
    for root in ACTIONS:
        r, m = rets[root]
        prix = float(np.nanmedian(m.rc[-500000:]))
        for code in ("R1", "V"):
            w = appliquer(r, expo[code])
            s = w.notna()
            rw, ww = r[s], w[s]
            dw = ww.diff().abs().fillna(ww.abs().iloc[0])
            for ticks, lib in ((1, ""), (2, " stress")):
                net = rw * ww - dw * cout_unitaire(root, prix, ticks)
                if ticks == 1:
                    net1 = net
            nw = newey_west(net1, rw)
            p1, p2 = net1.index < COUPURE, net1.index >= COUPURE
            nw1, nw2 = newey_west(net1[p1], rw[p1]), newey_west(net1[p2], rw[p2])
            couv = nw["residus"]
            sans3 = couv.drop(couv.nlargest(3).index).mean()
            p_dsr = dsr(couv, N_ESSAIS)
            sh_v, sh_b = sharpe(net1), sharpe(rw)
            pm_v, pm_b = perte_max(net1), perte_max(rw)
            rot = dw.groupby(dw.index.year).sum().mean()
            res[(root, code)] = dict(alpha=nw["alpha"] * 252, t=nw["t"], t1=nw1["t"], t2=nw2["t"], a1=nw1["alpha"] * 252,
                                     a2=nw2["alpha"] * 252, sh=sh_v, sh_b=sh_b, pm=pm_v, pm_b=pm_b, sans3=sans3, dsr=p_dsr,
                                     beta=nw["beta"], rotation=rot, stress=sharpe(net))
            pr(f"  --- {root} {code} : alpha {nw['alpha'] * 252 * 100:+.2f} %/an (t {nw['t']:+.2f}), beta {nw['beta']:.2f} | "
               f"2016-2020 {nw1['alpha'] * 252 * 100:+.2f} (t {nw1['t']:+.2f}) | 2021-2026 {nw2['alpha'] * 252 * 100:+.2f} "
               f"(t {nw2['t']:+.2f})")
            pr(f"      Sharpe net {sh_v:.2f} (stress 2 ticks {sharpe(net):.2f}) contre {sh_b:.2f} detenu | perte max "
               f"{pm_v * 100:.0f} % contre {pm_b * 100:.0f} % | rotation {rot:.1f} fois l exposition par an | "
               f"Sharpe deflate couvert {p_dsr:.2f}")
    # verdict de V sur l ES
    v = res[("ES", "V")]
    post = e1[("V", "2017-2026")]
    crit = {"C1 alpha t >= 3 (ES 2016-2026)": v["t"] >= 3,
            "C2 alpha > 0 et t >= 1,5 sur 2016-2020 et 2021-2026": v["t1"] >= 1.5 and v["t2"] >= 1.5,
            "C3 temoin de Harvey et al. verifie": bool(c3),
            "C4 Sharpe net > detenu et perte max plus faible": v["sh"] > v["sh_b"] and v["pm"] > v["pm_b"],
            "C5 alpha > 0 sans les 3 meilleurs jours": v["sans3"] > 0,
            f"C6 Sharpe deflate >= {SEUIL_DSR:.2f} ({N_ESSAIS} essais)": v["dsr"] >= SEUIL_DSR,
            "C7 marche 2017-2026 : alpha > 0 et t >= 1,5": post["alpha"] > 0 and post["t"] >= 1.5}
    echecs = [k for k, ok in crit.items() if not ok]
    pr("\nVERDICT (V sur l ES) : " + ("RETENUE" if not echecs else "ECHOUE (" + " ; ".join(echecs) + ")"))
    pr(f"Calcul en {(datetime.now() - t0).total_seconds():.0f} s.")
    sortie = sortie or os.path.join(PY_DIR, "recherche", "resultats_vol_geree.txt")
    with open(sortie, "w", encoding="utf-8") as fh:
        fh.write("\n".join(L) + "\n")
    exporter("vol_geree", dict(
        lignes=[dict(marche=r_, code=c_, **{k: x[k] for k in ("alpha", "t", "t1", "t2", "sh", "sh_b", "pm", "pm_b", "dsr",
                                                               "rotation", "stress")}) for (r_, c_), x in res.items()],
        marche_post=dict(alpha=post["alpha"] * 252, t=post["t"]), temoin=dict(actions=g_act, autres=g_tem, gains=gains),
        criteres={k: bool(v_) for k, v_ in crit.items()}, retenue=not echecs))
    log("\n".join(L))
    return dict(etape1=e1, etape2=res, criteres=crit)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--sortie", default=None)
    a = ap.parse_args(argv)
    etude(a.sortie)


if __name__ == "__main__":
    main()
