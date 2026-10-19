"""Suivi de tendance sur nos futures : strategie construite sur sept travaux (AQR, Robeco, CFM, Yale...).

    python -m nexus.perso.tendance [--sortie resultats_tendance.txt]

PROTOCOLE ECRIT LE 2026-10-11, AVANT TOUT CALCUL SUR NOS DONNEES (methode : memoire « methode-strategie-papiers »).
Premier des candidats classes « du plus prometteur au moins prometteur » apres la lecture des meta-etudes.

Sources (texte complet lu = [T], resume seulement = [R])
 [MOP12] [T] T. Moskowitz (Yale/AQR), Y. H. Ooi (AQR), L. H. Pedersen (NYU/CBS/AQR), « Time series momentum », Journal of
         Financial Economics 104, 2012 : 58 futures 1985-2009 ; position = signe du rendement des 12 derniers mois,
         taille inversement proportionnelle a la volatilite ex ante (moyenne exponentielle des carres, centre de masse 60
         jours, cible 40 % par actif), tenue 1 mois ; profit positif sur chacun des 58 contrats.
 [HOP17] [T] B. Hurst, Y. H. Ooi, L. H. Pedersen (AQR), « A Century of Evidence on Trend-Following Investing », Journal of
         Portfolio Management 44 (1), 2017 : 67 marches 1880-2016, signaux 1, 3 et 12 mois ; positif chaque decennie,
         Sharpe moyen ~0,4 par marche.
 [BSV21] [T] G. Baltussen, L. Swinkels, P. van Vliet (Erasmus, Robeco), « Global Factor Premiums », Journal of Financial
         Economics 142, 2021 : sur des donnees neuves (1800-1980, 2012-2016), la tendance est significative dans les
         quatre classes (actions, obligations, matieres premieres, devises) et englobe le momentum.
 [KEBR26] [T] J. Kurth, Z. Eisler, A. Rej, J.-P. Bouchaud (Institut Louis Bachelier / Ecole polytechnique, Imperial
         College, Capital Fund Management), « Is Trend Still Your Friend? A Microstructural Account of the Demise of
         Short-Term Trend-Following », arXiv 2607.01550, juillet 2026 : ~100 futures 1995-2025. Depuis 2008-2009, la
         tendance s est effondree sur les contrats a PETIT tick rapporte a la volatilite (Sharpe ~0 apres la rupture)
         et a survecu sur les contrats a GROS tick (Sharpe 1,0-1,2, contre 1,4 avant) ; tous horizons confondus ; ni la
         classe d actifs ni la liquidite ne separent aussi bien. Mecanisme : les ordres des suiveurs de tendance poussent
         le prix dans le sens du signal ; sur un carnet clairseme (petit tick), les teneurs de marche haute frequence se
         retirent et cassent la boucle. Signal EWM-tau-4tau = moyenne exponentielle rapide (tau jours) moins lente (4 tau)
         des prix de la veille, divisee par son ecart-type exponentiel (16 tau), bornee a +-2 ; tau = 5, 10, 20, 50 ;
         position = signal / volatilite (moyenne exponentielle sur 16 tau des variations absolues) ; classement mensuel
         causal par tick / volatilite : moitie basse = petit tick, moitie haute = gros tick (classement aussi valable
         a l interieur d une classe d actifs).
 [HLWZ20] [R] D. Huang, J. Li, L. Wang (Singapore Management University), G. Zhou (Washington University), « Time series
         momentum: Is it there? », Journal of Financial Economics 135, 2020 : actif par actif, peu de preuve de momentum
         temporel ; le t eleve de la regression empilee n est pas fiable (bootstrap).
 [KTW16] [R] A. Kim, Y. Tse, J. Wald, « Time series momentum and volatility scaling », Journal of Financial Markets 30,
         2016 : les resultats de MOP12 viennent surtout de la mise a l echelle par la volatilite.
 [HO14]  [R] M. Hutchinson & J. O Brien (University College Cork), « Is this time different? Trend following and financial
         crises », 2014 : apres une crise financiere, le rendement du suivi de tendance tombe a moins de la moitie.
Lecture commune : la tendance existe sur deux siecles (HOP17, BSV21) mais, actif par actif, la preuve est fragile
(HLWZ20) et une partie vient de la mise a l echelle par la volatilite (KTW16) ; depuis 2009 elle a disparu des contrats a
petit tick et survit sur les gros (KEBR26), ce qui explique aussi la deception des CTA apres 2009 (HO14). Strategie
retenue : celle de KEBR26, telle quelle, sur la moitie « gros tick » de nos 9 futures.

Donnees
  futures ES NQ YM GC CL 6E 6B 6J 6A (Databento) : cloture 16:00 ET au prix reel, rendements quotidiens (jours de
  changement d echeance exclus) ; prix « continu » = exponentielle de la somme des rendements (sans saut de roulement).
  Les signaux sont calcules sur le logarithme de ce prix (KEBR26 travaillent en prix ; la normalisation par l ecart-type
  du signal rend les deux equivalents a un facteur pres). Tick : tableau des couts des 60 strategies.

ETAPE 1 - l anomalie
  1a. rapport tick / volatilite moyen de chaque contrat et appartenance aux tiers (moitie haute = gros tick) ;
  1b. Sharpe du portefeuille de tendance KEBR26 (4 horizons) par tier et par periode 2016-2020 / 2021-2026 ; KEBR26
      predisent ~0 pour les petits ticks et un Sharpe nettement positif pour les gros.
ETAPE 2 - strategies (regles figees, quotidiennes, nettes de couts)
  - V  = portefeuille KEBR26 sur les contrats du tier « gros tick » du mois (classement causal : rapport moyen du mois
         precedent), quatre horizons tau = 5, 10, 20, 50 a parts egales, risque egal par contrat ;
  - R1 = le meme sur les 9 contrats (l anomalie brute) ; R0 = momentum temporel 12 mois de MOP12 (signe du rendement des
         12 derniers mois, risque egal par contrat, reequilibre mensuel) sur les 9 contrats ;
  - temoin = le portefeuille KEBR26 du tier « petit tick » ; contexte : portefeuille toujours acheteur a risque egal
    (KTW16 : la mise a l echelle seule) ;
  - mise a l echelle : chaque contrat vise 1 % de risque quotidien par unite de signal (la volatilite est celle des
    rendements, moyenne exponentielle sur 16 tau) ; les rendements de la strategie sont ceux du capital, sans levier
    plafonne (seul le Sharpe et les t comptent) ; couts : |variation de poids| x (1 tick + 2,50 $) par cote, stress 2 ticks.
  Criteres (fixes avant le calcul), sur les rendements quotidiens nets de V : t >= 3 ; meme signe et t >= 1,5 sur
  2016-2020 et 2021-2026 ; Welch >= 2 contre le temoin petit tick ; net > 0 ; net > 0 sans les 3 meilleurs jours ;
  Sharpe deflate >= 0,95 pour 44 essais (41 precedents + R0, R1, V).
Compatibilite prop firm : positions tenues plusieurs jours : NON compatible avec une prop firm intraday.
"""
from __future__ import annotations

import argparse
import math
import os
from datetime import datetime

import numpy as np
import pandas as pd

from .alternatives import dsr
from .soixante import COMMISSION, COUTS, PY_DIR, contrats, criteres, exporter, marche, tstat

MARCHES = ("ES", "NQ", "YM", "GC", "CL", "6E", "6B", "6J", "6A")
TAUS = (5, 10, 20, 50)
COUPURE = pd.Timestamp("2021-01-01")
RISQUE_JOUR = 0.01
N_ESSAIS, SEUIL_DSR = 44, 0.95


# =============================================================================
#  Donnees
# =============================================================================
def quotidien(m) -> pd.DataFrame:
    """Cloture 16:00 ET au prix reel et rendement logarithmique (NaN au changement d echeance)."""
    sel = np.nonzero(m.tod <= 16 * 60)[0]
    der = pd.DataFrame({"jour": m.jour[sel], "i": sel}).groupby("jour").i.max()
    idx = der.to_numpy()
    rc = np.where(np.isfinite(m.rc[idx]) & (m.rc[idx] > 0), m.rc[idx], np.nan)
    cid = contrats(m)[idx]
    r = np.r_[np.nan, np.log(rc[1:] / rc[:-1])]
    r[np.r_[False, cid[1:] != cid[:-1]]] = np.nan
    d = pd.DataFrame({"prix": rc, "r": r}, index=pd.to_datetime(der.index.to_numpy() * 86_400_000_000_000))
    return d[d.index.dayofweek < 5]


def donnees() -> dict:
    return {mk: quotidien(marche(mk)) for mk in MARCHES}


# =============================================================================
#  Signaux et portefeuilles
# =============================================================================
def ewm(x: pd.Series, tau: float) -> pd.Series:
    return x.ewm(alpha=1.0 / tau, adjust=False).mean()


def signal_kebr(logp: pd.Series, tau: int) -> pd.Series:
    """EWM-tau-4tau sur les prix de la VEILLE, normalise par son ecart-type exponentiel (16 tau), borne a +-2."""
    p = logp.shift(1)
    s = ewm(p, tau) - ewm(p, 4 * tau)
    sd = s.ewm(alpha=1.0 / (16 * tau), adjust=False).std()
    return (s / sd).clip(-2, 2)


def vol_rel(r: pd.Series, tau: int) -> pd.Series:
    """Volatilite quotidienne relative : moyenne exponentielle (16 tau) des |rendements| de la veille, x sqrt(pi/2)."""
    return ewm(r.abs().shift(1), 16 * tau) * math.sqrt(math.pi / 2)


def poids_kebr(d: dict, marches) -> pd.DataFrame:
    """Poids quotidiens (fraction du capital) du portefeuille KEBR26 a quatre horizons, risque egal par contrat."""
    out = {}
    for mk in marches:
        r = d[mk].r
        logp = r.fillna(0).cumsum()
        w = 0
        for tau in TAUS:
            w = w + signal_kebr(logp, tau) * RISQUE_JOUR / vol_rel(r, tau)
        out[mk] = w / len(TAUS)
    return pd.DataFrame(out)


def poids_mop(d: dict, marches) -> pd.DataFrame:
    """MOP12 : signe du rendement des 12 derniers mois, fixe en fin de mois, taille = 1 % / volatilite ex ante (centre de
    masse 60 jours)."""
    out = {}
    for mk in marches:
        r = d[mk].r
        mois = r.index.to_period("M")
        r12 = r.fillna(0).rolling(252, min_periods=240).sum()
        vol = np.sqrt((r ** 2).ewm(com=60, adjust=False).mean())
        fin = r.groupby(mois).apply(lambda x: x.index[-1])
        sig = np.sign(r12.reindex(fin.values)) * RISQUE_JOUR / vol.reindex(fin.values)
        sig.index = fin.index + 1                                         # decision de fin de mois -> mois suivant
        out[mk] = sig.reindex(mois).set_axis(r.index)
    return pd.DataFrame(out)


def ratio_tick(d: dict) -> pd.DataFrame:
    """Rapport tick / volatilite quotidienne en prix (moyenne du mois), par contrat."""
    out = {}
    for mk in MARCHES:
        tick = COUTS[mk][0]
        sig = vol_rel(d[mk].r, 5) * d[mk].prix
        out[mk] = (tick / sig).groupby(sig.index.to_period("M")).mean()
    return pd.DataFrame(out)


def tiers(rt: pd.DataFrame) -> pd.DataFrame:
    """Classement causal : tier du mois m = rang du rapport moyen du mois m-1 ; moitie haute = gros tick (True)."""
    rang = rt.rank(axis=1, method="first")
    n = rt.notna().sum(axis=1)
    gros = rang.gt(np.floor(n / 2), axis=0)
    gros.index = gros.index + 1
    return gros


def rendement(w: pd.DataFrame, d: dict, ticks: int) -> pd.Series:
    r = pd.DataFrame({mk: d[mk].r for mk in w.columns}).reindex(w.index)
    brut = (w * r).sum(axis=1, min_count=1)
    prix = {mk: float(np.nanmedian(d[mk].prix.iloc[-500:])) for mk in w.columns}
    cu = pd.Series({mk: (ticks * COUTS[mk][0] + COMMISSION / COUTS[mk][1]) / prix[mk] for mk in w.columns})
    rot = w.fillna(0).diff().abs()
    return (brut - (rot * cu).sum(axis=1)).dropna()


def masque_tier(w: pd.DataFrame, gros: pd.DataFrame, garder_gros: bool) -> pd.DataFrame:
    g = gros.reindex(w.index.to_period("M")).set_axis(w.index)
    g = g.reindex(columns=w.columns)
    keep = g if garder_gros else ~g.astype(bool)
    return w.where(keep.fillna(False).astype(bool), 0.0).where(g.notna().any(axis=1), np.nan, axis=0)


def sharpe(x: pd.Series) -> float:
    x = x.dropna()
    return float(x.mean() / x.std(ddof=1) * math.sqrt(252)) if len(x) > 20 and x.std(ddof=1) > 0 else math.nan


def etude(sortie: str | None = None, log=print) -> dict:
    t0 = datetime.now()
    L = []
    pr = L.append
    pr("=" * 118)
    pr(" SUIVI DE TENDANCE SUR NOS 9 FUTURES : STRATEGIE CONSTRUITE SUR SEPT TRAVAUX (AQR, ROBECO, CFM / BOUCHAUD, YALE...)")
    pr("=" * 118)
    pr("Protocole et sources : en-tete de nexus/perso/tendance.py (ecrit avant le calcul).\n")
    d = donnees()
    rt = ratio_tick(d)
    gros = tiers(rt)
    pr("ETAPE 1 - l anomalie")
    moy = rt.mean().sort_values()
    part = gros.astype(float).mean()
    pr("  1a. rapport tick / volatilite quotidienne (moyenne) et part des mois classes « gros tick » :")
    pr("      " + " | ".join(f"{mk} {moy[mk]:.4f} ({part.get(mk, math.nan):.0%})" for mk in moy.index))
    w_all = poids_kebr(d, MARCHES)
    w_lt = masque_tier(w_all, gros, True)
    w_st = masque_tier(w_all, gros, False)
    v, tem, r1 = rendement(w_lt, d, 1), rendement(w_st, d, 1), rendement(w_all, d, 1)
    for lib, s in (("gros tick (V)", v), ("petit tick (temoin)", tem), ("les 9 (R1)", r1)):
        a, b = s[s.index < COUPURE], s[s.index >= COUPURE]
        pr(f"  1b. tendance KEBR26 {lib:<20} : Sharpe net {sharpe(s):+.2f} | 2016-2020 {sharpe(a):+.2f} | 2021-2026 {sharpe(b):+.2f}")
    for mk in MARCHES:
        s = rendement(w_all[[mk]], d, 1)
        a, b = s[s.index < COUPURE], s[s.index >= COUPURE]
        pr(f"      {mk:<3} seul : Sharpe {sharpe(s):+.2f} (2016-2020 {sharpe(a):+.2f}, 2021-2026 {sharpe(b):+.2f})")

    pr("\nETAPE 2 - strategies (rendements quotidiens nets de couts, en pb du capital)")
    r0 = rendement(poids_mop(d, MARCHES), d, 1)
    lo = pd.DataFrame({mk: RISQUE_JOUR / vol_rel(d[mk].r, 20) for mk in MARCHES})
    long_seul = rendement(lo, d, 1)
    res = {}
    for code, s, s2, tm, nom in (("V", v, rendement(w_lt, d, 2), tem, "V tendance KEBR26 sur le tier gros tick"),
                                 ("R1", r1, rendement(w_all, d, 2), tem, "R1 tendance KEBR26 sur les 9 contrats"),
                                 ("R0", r0, rendement(poids_mop(d, MARCHES), d, 2), tem, "R0 momentum 12 mois de MOP12 (9 contrats)")):
        x = s * 1e4
        c = criteres(x, tm * 1e4, 0.0)
        p_dsr = dsr(s, N_ESSAIS)
        res[code] = dict(c, dsr=p_dsr, sharpe_an=sharpe(s), stress=sharpe(s2), nom=nom)
        pr(f"  --- {nom} : {c['n']} jours | net {c['moyenne']:+.2f} pb/j (t {c['t']:+.2f}) | 2016-2020 t {c['t1']:+.2f} | 2021-2026 t {c['t2']:+.2f}")
        pr(f"      temoin petit tick {c['temoin']:+.2f} pb/j, Welch {c['welch']:+.2f} | sans les 3 meilleurs jours {c['sans3']:+.2f} | "
           f"Sharpe net {sharpe(s):.2f} (stress 2 ticks {sharpe(s2):.2f}) | Sharpe deflate ({N_ESSAIS} essais) {p_dsr:.2f}")
    pr(f"      contexte (KTW16) : toujours acheteur a risque egal, Sharpe {sharpe(long_seul):.2f} ; correlation V / long seul "
       f"{v.corr(long_seul.reindex(v.index)):+.2f}")
    vv = res["V"]
    echecs = [k for k, ok in vv["tests"].items() if not ok] + ([] if vv["dsr"] >= SEUIL_DSR else [f"Sharpe deflate >= {SEUIL_DSR:.2f}"])
    pr("\nVERDICT (V) : " + ("RETENUE" if not echecs else "ECHOUE (" + " ; ".join(echecs) + ")"))
    pr(f"Calcul en {(datetime.now() - t0).total_seconds():.0f} s.")
    sortie = sortie or os.path.join(PY_DIR, "recherche", "resultats_tendance.txt")
    with open(sortie, "w", encoding="utf-8") as fh:
        fh.write("\n".join(L) + "\n")
    exporter("tendance", dict(
        titre="Suivi de tendance sur nos 9 futures (sept travaux)",
        sous="Moskowitz, Ooi & Pedersen (JFE 2012), Hurst, Ooi & Pedersen (AQR 2017), Baltussen et al. (JFE 2021), Kurth, Eisler, "
             "Rej & Bouchaud (CFM, 2026), Huang et al. (JFE 2020), Kim, Tse & Wald (2016), Hutchinson & O'Brien (2014). V = tendance "
             "a 4 horizons sur les contrats a gros tick (Kurth et al.) ; temoin = petits ticks. Protocole : nexus/perso/tendance.py.",
        ratio_tick={mk: float(moy[mk]) for mk in moy.index}, part_gros={mk: float(part.get(mk, math.nan)) for mk in MARCHES},
        lignes=[dict(code=k, nom=x["nom"], n=x["n"], moyenne=x["moyenne"], t=x["t"], t1=x["t1"], t2=x["t2"], temoin=x["temoin"],
                     welch=x["welch"], sans3=x["sans3"], dsr=x["dsr"], sharpe_an=x["sharpe_an"], stress=x["stress"])
                for k, x in res.items()],
        long_seul=sharpe(long_seul), echecs=echecs, retenue=not echecs))
    log("\n".join(L))
    return dict(etape2=res, echecs=echecs)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--sortie", default=None)
    a = ap.parse_args(argv)
    etude(a.sortie)


if __name__ == "__main__":
    main()
