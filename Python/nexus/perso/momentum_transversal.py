"""Momentum transversal (12 mois moins le dernier) sur nos 9 futures : strategie construite sur sept travaux.

    python -m nexus.perso.momentum_transversal [--sortie resultats_momentum_transversal.txt]

PROTOCOLE ECRIT LE 2026-10-11, AVANT TOUT CALCUL DEDIE (methode : memoire « methode-strategie-papiers »).
Quatrieme des candidats classes « du plus prometteur au moins prometteur » apres la lecture des meta-etudes.

TEST NON AVEUGLE, annonce avant le calcul : une variante proche (rendement des 12 derniers mois SANS sauter le dernier,
poids = signal / somme des valeurs absolues, classes a parts egales, sans mise a l echelle par la volatilite) a deja ete
calculee comme temoin de nexus/perso/pression_cot.py : -4,4 pb/mois, t -0,19, Sharpe -0,06. Le verdict ci-dessous est
donc INDICATIF : meme s il passait tous les criteres, la strategie ne serait pas retenue sans nouvelles donnees.

Sources (texte complet lu = [T], resume seulement = [R])
 [AMP13] [T] C. Asness (AQR), T. Moskowitz (Chicago/Yale), L. H. Pedersen (NYU/CBS), « Value and Momentum Everywhere »,
         Journal of Finance 68, 2013 : momentum = rendement cumule des 12 derniers mois SAUF le dernier (MOM2-12), meme
         definition pour toutes les classes ; poids = c x (rang - rang moyen), 1 $ long / 1 $ court ; 1972-2011 : indices
         nationaux Sharpe 0,63 (t 3,57), devises 0,32 (t 1,77), matieres premieres 0,51 (t 3,14).
 [BSV21] [T] Baltussen, Swinkels, van Vliet (Erasmus, Robeco), « Global Factor Premiums », Journal of Financial Economics
         142, 2021 : sur 1800-2016, momentum transversal robuste dans les indices actions (Sharpe 0,40, 7/7 variantes) et
         les devises (0,32, 7/7), pas dans les matieres premieres (0,04, 0/7).
 [DM16]  [T] K. Daniel (Columbia), T. Moskowitz (Yale), « Momentum Crashes », Journal of Financial Economics 122, 2016 :
         le momentum s effondre par episodes (rebonds apres des marches baissiers) dans toutes les classes d actifs.
 [MSSS12] [R] L. Menkhoff, L. Sarno, M. Schmeling, A. Schrimpf, « Currency momentum strategies », Journal of Financial
         Economics 106, 2012 : le momentum de change vient surtout de devises mineures et couteuses ; instable dans le temps.
 [GJ18]  [R] A. Goyal (Lausanne/SFI), N. Jegadeesh (Emory), « Cross-Sectional and Time-Series Tests of Return
         Predictability: What Is the Difference? », Review of Financial Studies 31, 2018 : l avance du momentum temporel
         sur le transversal vient de son exposition nette acheteuse variable.
 [MOP12] [T] Moskowitz, Ooi, Pedersen, « Time series momentum », JFE 2012 (lu pour tendance.py) : volatilite ex ante
         (moyenne exponentielle des carres, centre de masse 60 jours).
 [HLWZ20] [R] Huang, Li, Wang, Zhou, « Time series momentum: Is it there? », JFE 2020 : preuve fragile actif par actif.
Lecture commune : le momentum transversal est documente partout jusqu en 2011 (AMP13) mais, sur deux siecles, il ne
tient que dans les indices actions et les devises (BSV21) ; il subit des krachs (DM16) et sa partie devises tient a des
devises que nous n avons pas (MSSS12). Strategie retenue : AMP13 telle quelle sur les classes robustes de BSV21 (indices
actions ES NQ YM, devises 6E 6B 6J 6A) ; reference : les trois classes (le « partout » d AMP13).

Donnees : futures Databento (cloture 16:00 ET au prix reel, jours de roulement exclus), rendements mensuels = somme des
rendements logarithmiques quotidiens ; signal du mois m = somme des rendements des mois m-12 a m-2 (11 mois requis) :
premier mois tenu 2017-01, donc premiere periode = 2017-2020.

ETAPE 1 - l anomalie : par classe, portefeuille long-court sans mise a l echelle (z = rang - rang moyen ramene a
  [-1, 1]), rendement mensuel et t par periode 2017-2020 / 2021-2026 ; AMP13 predisent > 0 partout, BSV21 ~0 pour les
  matieres premieres.
ETAPE 2 - strategies (regles figees, poids fixes pour le mois, rendements quotidiens nets de couts)
  - V  = MOM2-12 sur indices actions et devises : z par classe, position = z x 1 % / volatilite quotidienne ex ante de
         fin du mois precedent (BSV21 : positions a volatilite constante ; meme construction que saisonnalite.py) ;
  - R1 = la meme sur les trois classes (matieres premieres comprises) ;
  - temoin = toujours acheteur a risque egal sur les memes contrats (GJ18 : l alternative passive) ;
  - couts : |variation de poids| x (1 tick + 2,50 $) / prix par cote, plus le roulement (2 cotes x |poids|), stress
    2 ticks.
  Criteres (fixes avant le calcul), sur les rendements quotidiens nets de V : t >= 3 ; meme signe et t >= 1,5 sur
  2017-2020 et 2021-2026 ; Welch >= 2 contre le temoin ; net > 0 ; net > 0 sans les 3 meilleurs jours ; Sharpe deflate
  >= 0,95 pour 51 essais (49 precedents + V, R1).
Compatibilite prop firm : positions tenues un mois : NON compatible avec une prop firm intraday.
"""
from __future__ import annotations

import argparse
import os
from datetime import datetime

import pandas as pd

from .alternatives import dsr
from .saisonnalite import CLASSES, donnees, poids_quotidiens, rendement, vol_fin_de_mois, z_rang
from .soixante import PY_DIR, criteres, exporter, tstat
from .tendance import sharpe

COUPURE = pd.Timestamp("2021-01-01")
N_ESSAIS, SEUIL_DSR = 51, 0.95


def mom_2_12(rm: pd.DataFrame) -> pd.DataFrame:
    """Signal du mois m = somme des rendements mensuels m-12 .. m-2 (11 mois exiges)."""
    return rm.shift(2).rolling(11, min_periods=11).sum()


def _ligne(x: pd.Series) -> str:
    x = x.dropna()
    return f"{x.mean() * 100:+.2f} %/mois (t {tstat(x):+.2f}, {len(x)} mois)" if len(x) > 2 else "n/d"


def etude(sortie: str | None = None, log=print) -> dict:
    t0 = datetime.now()
    L = []
    pr = L.append
    pr("=" * 118)
    pr(" MOMENTUM TRANSVERSAL (12 MOIS MOINS LE DERNIER) SUR NOS 9 FUTURES : STRATEGIE CONSTRUITE SUR SEPT TRAVAUX (AQR...)")
    pr("=" * 118)
    pr("Protocole et sources : en-tete de nexus/perso/momentum_transversal.py. TEST NON AVEUGLE (voir l en-tete) : verdict indicatif.\n")
    d = donnees()
    jours = pd.DatetimeIndex(sorted(set().union(*[x.index for x in d.values()])))
    rf = pd.DataFrame({mk: x.r for mk, x in d.items()})
    rm = rf.groupby(rf.index.to_period("M")).sum(min_count=5)
    sig = mom_2_12(rm)

    pr("ETAPE 1 - l anomalie (long-court par classe, sans mise a l echelle)")
    for nom in CLASSES:
        p = (z_rang(sig, [nom]) * rm[list(CLASSES[nom])]).sum(axis=1, min_count=1)
        a, b = p[p.index < COUPURE.to_period("M")], p[p.index >= COUPURE.to_period("M")]
        pr(f"  {nom:<9} : 2017-2020 {_ligne(a)} | 2021-2026 {_ligne(b)}")

    pr("\nETAPE 2 - strategies (rendements quotidiens nets de couts, en pb du capital)")
    vol = vol_fin_de_mois(d)
    w_v = poids_quotidiens(z_rang(sig, ["actions", "devises"]), vol, jours)
    w_r1 = poids_quotidiens(z_rang(sig, list(CLASSES)), vol, jours)
    lo = pd.DataFrame(1.0, index=sig.index, columns=w_v.columns).where(sig[w_v.columns].notna())
    tem = rendement(poids_quotidiens(lo, vol, jours), d, 1)
    res = {}
    for code, w, nom in (("V", w_v, "V momentum AMP13 sur indices actions et devises"),
                         ("R1", w_r1, "R1 momentum AMP13 sur les trois classes")):
        s, s2 = rendement(w, d, 1), rendement(w, d, 2)
        s, s2 = s[s.index >= "2017-01-01"], s2[s2.index >= "2017-01-01"]
        c = criteres(s * 1e4, tem * 1e4, 0.0)
        p_dsr = dsr(s, N_ESSAIS)
        res[code] = dict(c, dsr=p_dsr, sharpe_an=sharpe(s), stress=sharpe(s2), nom=nom)
        pr(f"  --- {nom} : {c['n']} jours | net {c['moyenne']:+.2f} pb/j (t {c['t']:+.2f}) | 2017-2020 t {c['t1']:+.2f} | 2021-2026 t {c['t2']:+.2f}")
        pr(f"      temoin toujours acheteur {c['temoin']:+.2f} pb/j, Welch {c['welch']:+.2f} | sans les 3 meilleurs jours {c['sans3']:+.2f} | "
           f"Sharpe net {sharpe(s):.2f} (stress 2 ticks {sharpe(s2):.2f}) | Sharpe deflate ({N_ESSAIS} essais) {p_dsr:.2f}")
    pr(f"      temoin (toujours acheteur a risque egal, indices actions et devises) : Sharpe {sharpe(tem):+.2f}")
    vv = res["V"]
    echecs = [k for k, ok in vv["tests"].items() if not ok] + ([] if vv["dsr"] >= SEUIL_DSR else [f"Sharpe deflate >= {SEUIL_DSR:.2f}"])
    pr("\nVERDICT (V, indicatif car non aveugle) : " + ("passerait les criteres" if not echecs else "ECHOUE (" + " ; ".join(echecs) + ")"))
    pr(f"Calcul en {(datetime.now() - t0).total_seconds():.0f} s.")
    sortie = sortie or os.path.join(PY_DIR, "recherche", "resultats_momentum_transversal.txt")
    with open(sortie, "w", encoding="utf-8") as fh:
        fh.write("\n".join(L) + "\n")
    exporter("momentum_transversal", dict(
        titre="Momentum transversal 12 mois moins le dernier (sept travaux, test non aveugle)",
        sous="Asness, Moskowitz & Pedersen (JF 2013), Baltussen et al. (JFE 2021), Daniel & Moskowitz (JFE 2016), Menkhoff et al. "
             "(JFE 2012), Goyal & Jegadeesh (RFS 2018), Moskowitz et al. (JFE 2012), Huang et al. (JFE 2020). V = classement par le "
             "rendement des mois m-12 a m-2, indices actions et devises ; temoin = toujours acheteur. Une variante proche avait "
             "deja ete vue (temoin du module COT) : verdict indicatif. Protocole : nexus/perso/momentum_transversal.py.",
        lignes=[dict(code=k, nom=x["nom"], n=x["n"], moyenne=x["moyenne"], t=x["t"], t1=x["t1"], t2=x["t2"], temoin=x["temoin"],
                     welch=x["welch"], sans3=x["sans3"], dsr=x["dsr"], sharpe_an=x["sharpe_an"], stress=x["stress"])
                for k, x in res.items()],
        temoin_sharpe=sharpe(tem), echecs=echecs + ["test non aveugle"], retenue=False))
    log("\n".join(L))
    return dict(etape2=res, echecs=echecs)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--sortie", default=None)
    a = ap.parse_args(argv)
    etude(a.sortie)


if __name__ == "__main__":
    main()
