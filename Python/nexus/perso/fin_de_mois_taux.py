"""Fin de mois sur les obligations du Tresor (piste T3 de recherche/pistes_taux.md), en journalier gratuit.

    python -m nexus.perso.fin_de_mois_taux [--sortie recherche/resultats_fin_de_mois_taux.txt]

PROTOCOLE ECRIT LE 2026-10-21, AVANT TOUT CALCUL DEDIE (methode : memoire « methode-strategie-papiers »).
Deja vu chez nous : IEF a servi de jambe obligataire de fin_de_mois.py (ecart ES - IEF, signal de reequilibrage
60/40), jamais seul en fin de mois ; TLT jamais utilise. Test aveugle pour tout ce qui suit.

Sources (texte complet lu = [T], resume ou partie = [R])
 [HS19]  [T] J. Hartley (Harvard Kennedy School), K. Schwarz (Wharton), « Predictable End-of-Month Treasury Returns »,
         22/11/2019 (SSRN 3440417), 1990-2018 : rendement excedentaire (sur le repo) positif et tres significatif les
         derniers jours du mois, nul les autres jours ; 10 ans : +0,14 % le dernier jour, +0,20 % les 2 derniers,
         +0,25 % les 3 derniers ; Sharpe annualise 0,85 / 0,87 / 0,88 (t = 1 / 2 / 3) ; strategie « optimalement
         sur les 2 a 3 derniers jours » ; present dans chaque tranche de 5 ans, plus faible mais significatif en
         2015-2019 ; pas de rupture (Bai-Perron) ; meme effet sur les futures 5, 10, 30 ans et les swaps ; cause : achats
         des assureurs (surtout vie) des titres ajoutes a l indice Bloomberg Barclays US Treasury, reequilibre le
         dernier jour ouvre du mois ; ventes au debut du mois suivant.
 [DFS24] [R] H. Dyer, M. Fleming, O. Shachar (NY Fed), « End-of-Month Liquidity in the Treasury Market », Liberty
         Street Economics, 24/09/2024 : depuis 2020, volume des titres de reference +46 % le dernier jour du mois (+51 %
         hors decembre), « quasiment inexistant avant 2015 » ; impact de prix -28 % ; piste : fonds indiciels passifs.
         Ne mesure pas les rendements.
 [FLN26] [T] M. Fleming, W. Liu, G. Nguyen (NY Fed SR 1188, 2026) : pression des adjudications sur 6 h, distincte de la
         fin de mois (HS19, section 3.1 : la fin de mois survit au controle des adjudications).
 Contre-papier : aucun trouve qui teste les rendements apres 2018 (recherches du 2026-10-21) ; c est l objet du test.
Lecture commune : la cause (reequilibrage mensuel des indices, gestion passive) n a pas disparu et grandit (DFS24) ;
prediction refutable : l effet doit subsister sur 2019-2026, hors de l echantillon de HS19.

Donnees (gratuites, Yahoo, cache .cache/yahoo/*_2610.json, telecharge le 2026-10-21) : IEF (iShares 7-10 ans,
duree ~7,5 ans, proche du ZN) et TLT (20 ans et plus, proche du ZB / UB), clotures ajustees des coupons ; taux sans
risque = T-bill 13 semaines (^IRX / 100 / 252 par seance, de la veille). Jours = seances de l ETF ; T = derniere seance
du mois ; mois incomplet (octobre 2026) exclu. Approximation : cloture de l ETF (16:00 ET) au lieu du prix de fin de
journee du papier ; le financement au repo est remplace par le T-bill (ecart faible et sans calendrier).

ETAPE 1 - l anomalie, par periode (2016-2020 / 2021-2026, puis 2019-2026 seul) : rendement excedentaire moyen par
  position j-avant-la-fin (j = 1..10, une seance chacune) d IEF et de TLT, t de Student ; prediction : positif et
  significatif pour j = 1 (et j = 2), nul ailleurs (HS19, tableau 5).
ETAPE 2 - strategies (regles figees, achat a la cloture, vente a la cloture, taille = 1 fois le capital) :
  - V  = regle de HS19 a t = 2 : achat d IEF a la cloture de T-2, vente a la cloture de T (2 seances en position) ;
  - R0 = dernier jour seul (t = 1, HS19 tableau 5) : achat a la cloture de T-1, vente a la cloture de T ;
  - R3 = t = 3 (achat a la cloture de T-3) ;
  - temoin de V = meme fenetre de 2 seances finissant en T-10 (milieu de mois, sans fin de mois) ;
  - replique de V sur TLT.
  Couts : 1 pb par cote (ETF tres liquides, ecart d un cent), stress 2 pb par cote.
  Criteres (fixes avant le calcul, ceux des 60 strategies) sur le rendement net par trade de V (un par mois) :
  t >= 3 ; meme signe et t >= 1,5 sur 2016-2020 et 2021-2026 ; Welch >= 2 contre le temoin ; gain moyen net > 0 ;
  net > 0 sans les 3 meilleurs mois ; ET Sharpe deflate >= 0,95 pour N_ESSAIS = 430 (427 du programme au 2026-10-21
  + V, R0, R3).
  Fiabilite vectorbt (tableau de bord) : serie quotidienne de V (0 hors position), Sharpe annualise par l accesseur
  .vbt.returns, IC 95 % bootstrap BCa (scipy) : borne basse > 0 ; Sharpe > 0 sur les deux moities.
  Rapportes sans etre des criteres : 2019-2026 (hors echantillon de HS19), apres publication (09/2019), couts doubles.
Compatibilite prop firm : position de nuit (2 nuits) : NON compatible telle quelle avec une prop firm intraday ;
seule la version futures (minutes ZN / ZB, a acheter) pourrait isoler la partie de jour.
"""
from __future__ import annotations

import argparse
import json
import math
import os

import numpy as np
import pandas as pd

from .alternatives import dsr
from .soixante import COUPURE, PY_DIR, criteres, exporter, tstat

N_ESSAIS, SEUIL_DSR = 430, 0.95
HS_FIN = pd.Timestamp("2019-01-01")       # fin de l echantillon de HS19 (1990-2018)
HS_PUB = pd.Timestamp("2019-09-01")       # SSRN 3440417 (aout 2019)
COUT, STRESS = 1.0, 2.0                   # pb par cote
CACHE_Y = os.path.join(PY_DIR, ".cache", "yahoo")


def serie(sym: str, ajuste: bool = True) -> pd.Series:
    with open(os.path.join(CACHE_Y, f"{sym}_2610.json"), encoding="utf-8") as fh:
        r = json.load(fh)["chart"]["result"][0]
    v = r["indicators"]["adjclose"][0]["adjclose"] if ajuste else r["indicators"]["quote"][0]["close"]
    s = pd.Series(v, index=pd.to_datetime(r["timestamp"], unit="s").normalize(), dtype=float)
    return s[~s.index.duplicated(keep="last")].dropna()


def excedents(sym: str) -> pd.Series:
    """Rendement excedentaire quotidien (en pb) de l ETF sur le T-bill, 2016 -> dernier mois complet."""
    p = serie(sym)
    rf = (serie("IRX", ajuste=False) / 100 / 252).reindex(p.index).ffill().shift(1)
    x = (p.pct_change() - rf) * 1e4
    x = x[(x.index >= "2016-01-01")].dropna()
    dernier = x.index[-1]
    if (dernier + pd.offsets.BDay(1)).month == dernier.month:          # mois en cours incomplet
        x = x[x.index < dernier.replace(day=1)]
    return x.rename(sym)


def rang_fin(idx: pd.DatetimeIndex) -> pd.Series:
    """j = 1 pour la derniere seance du mois, 2 pour l avant-derniere..."""
    s = pd.Series(1, index=idx)
    return s.groupby([idx.year, idx.month]).cumsum().groupby([idx.year, idx.month]).transform(lambda v: v.max() - v + 1)


def fenetre(x: pd.Series, debut: int, fin: int) -> pd.Series:
    """Somme par mois des rendements des seances j = fin..debut (tenue de la cloture de j = debut+1 ... a j = fin)."""
    j = rang_fin(x.index)
    m = (j <= debut) & (j >= fin)
    g = x[m].groupby([x[m].index.year, x[m].index.month])
    out = g.sum()
    out.index = [x[m].index[(x[m].index.year == a) & (x[m].index.month == b)][-1] for a, b in out.index]
    return out[g.size().to_numpy() == debut - fin + 1]


def quotidien(x: pd.Series, debut: int, fin: int, cout: float) -> pd.Series:
    """Serie quotidienne de la strategie (fraction), 0 hors position, couts preleves le jour de sortie et d entree."""
    j = rang_fin(x.index)
    pos = (j <= debut) & (j >= fin)
    r = x.where(pos, 0.0).copy()
    r[pos & (j == debut)] -= cout
    r[pos & (j == fin)] -= cout
    return r / 1e4


def fiabilite(r: pd.Series) -> dict:
    import scipy.stats as SS
    import vectorbt as vbt  # noqa: F401 (accesseur .vbt)
    from .. import validation as V
    sh = lambda s: float(s.vbt.returns(freq="D", year_freq="252D").sharpe_ratio())  # noqa: E731
    b = SS.bootstrap((r.to_numpy(),), V.annualized_sharpe, method="BCa", n_resamples=2000, random_state=7)
    return dict(sharpe=sh(r), ic_bas=float(b.confidence_interval.low), ic_haut=float(b.confidence_interval.high),
                sharpe_1=sh(r[r.index < COUPURE]), sharpe_2=sh(r[r.index >= COUPURE]),
                sharpe_hs=sh(r[r.index >= HS_FIN]))


def etude(log=print) -> dict:
    res: dict = {}
    for sym in ("IEF", "TLT"):
        x = excedents(sym)
        j = rang_fin(x.index)
        log(f"\n=== ETAPE 1 - {sym} : rendement excedentaire moyen par seance j-avant-la-fin (pb), {x.index[0]:%Y-%m-%d} -> {x.index[-1]:%Y-%m-%d}")
        for k in range(1, 11):
            s = x[j == k]
            a, b, c = s[s.index < COUPURE], s[s.index >= COUPURE], s[s.index >= HS_FIN]
            log(f"  j={k:2d}  n {len(s):3d} | {s.mean():+6.2f} (t {tstat(s):+5.2f}) | 16-20 {a.mean():+6.2f} (t {tstat(a):+5.2f})"
                f" | 21-26 {b.mean():+6.2f} (t {tstat(b):+5.2f}) | 19-26 {c.mean():+6.2f} (t {tstat(c):+5.2f})")
        autres = x[j > 3]
        log(f"  autres jours (j > 3) : {autres.mean():+6.2f} pb (t {tstat(autres):+5.2f})")
        res[sym] = x
    x = res["IEF"]
    log("\n=== ETAPE 2 - strategies (rendement net par trade, pb ; couts 1 pb par cote)")
    temoin = fenetre(x, 11, 10)
    out = {}
    for code, (deb, fin, sym) in {"V": (2, 1, "IEF"), "R0": (1, 1, "IEF"), "R3": (3, 1, "IEF"), "V_TLT": (2, 1, "TLT")}.items():
        xs = res[sym]
        brut = fenetre(xs, deb, fin)
        c = criteres(brut, fenetre(xs, deb + 9, fin + 9) if code != "V" else temoin, 2 * COUT)
        net = brut - 2 * COUT
        d = dsr(net, N_ESSAIS)
        f = fiabilite(quotidien(xs, deb, fin, COUT))
        hs = net[net.index >= HS_FIN]
        pub = net[net.index >= HS_PUB]
        stress = (brut - 2 * STRESS).mean()
        log(f"  {code:6s} {sym}  t={deb}  n {c['n']:3d} | brut {c['moyenne']:+6.2f} (t {c['t']:+5.2f}) | 16-20 {c['m1']:+6.2f} (t {c['t1']:+5.2f})"
            f" | 21-26 {c['m2']:+6.2f} (t {c['t2']:+5.2f}) | temoin {c['temoin']:+6.2f} | net {net.mean():+6.2f} | stress {stress:+6.2f}")
        log(f"         19-26 net {hs.mean():+6.2f} (t {tstat(hs):+5.2f}) | apres pub. {pub.mean():+6.2f} (t {tstat(pub):+5.2f})"
            f" | % mois > 0 {100 * (net > 0).mean():.0f} | DSR {d:.3f}")
        log(f"         vectorbt : Sharpe {f['sharpe']:+.2f} IC95 [{f['ic_bas']:+.2f} ; {f['ic_haut']:+.2f}] | 16-20 {f['sharpe_1']:+.2f}"
            f" | 21-26 {f['sharpe_2']:+.2f} | 19-26 {f['sharpe_hs']:+.2f}")
        for k, v in c["tests"].items():
            log(f"           [{'OK' if v else '--'}] {k}")
        out[code] = dict(**{k: v for k, v in c.items() if k not in ("tests", "net")}, tests=c["tests"], net=net.mean(), dsr=d, stress=stress,
                         net_19_26=hs.mean(), t_19_26=tstat(hs), **f)
    v = out["V"]
    ok = all(v["tests"].values()) and v["dsr"] >= SEUIL_DSR
    fiable = v["ic_bas"] > 0 and v["sharpe_1"] > 0 and v["sharpe_2"] > 0
    log(f"\nVERDICT V : {'RETENUE' if ok else 'REJETEE'} (criteres + DSR >= {SEUIL_DSR}, N = {N_ESSAIS}) ;"
        f" fiabilite vectorbt : {'oui' if fiable else 'non'}")
    out["verdict"] = dict(retenue=ok, fiable=fiable, n_essais=N_ESSAIS)
    return out


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--sortie", default=os.path.join(PY_DIR, "recherche", "resultats_fin_de_mois_taux.txt"))
    a = ap.parse_args(argv)
    lignes: list[str] = []
    log = lambda s="": (print(s), lignes.append(s))  # noqa: E731
    out = etude(log)
    with open(a.sortie, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lignes) + "\n")
    exporter("fin_de_mois_taux", {k: v for k, v in out.items()})
    print(f"-> {a.sortie}")


if __name__ == "__main__":
    main()
