"""Rachat apres baisse (retournement de court terme des indices) sur ES NQ YM : strategie construite sur six travaux.

    python -m nexus.perso.rachat_baisse [--sortie resultats_rachat_baisse.txt]

PROTOCOLE ECRIT LE 2026-10-11, AVANT TOUT CALCUL DEDIE (methode : memoire « methode-strategie-papiers »).
Dernier candidat de la liste « du plus prometteur au moins prometteur » ; idee notee APRES COUP pendant cycle_fomc.py.

TEST PARTIELLEMENT NON AVEUGLE, annonce avant le calcul : cycle_fomc.py a deja mesure le rendement de ES le jour qui
suit une baisse des 5 dernieres seances dans le quintile bas (2016-2026 : environ +7 pb/j en moyenne, +14 pb en semaine
impaire, -2 pb en semaine paire). La strategie lineaire ci-dessous (tous les jours, dans les deux sens, ponderee) n a
jamais ete calculee, mais le verdict reste INDICATIF : meme s il passait, il faudrait de nouvelles donnees pour la retenir.

Sources (texte complet lu = [T], resume seulement = [R])
 [BVBD19] [T] G. Baltussen (Erasmus/Northern Trust), S. van Bekkum (Erasmus), Z. Da (Notre Dame), « Indexing and stock
         market serial dependence around the world », Journal of Financial Economics 132, 2019 : 20 indices de 15 pays ;
         l autocorrelation des rendements d indices, positive jusqu aux annees 1990, est NEGATIVE depuis les annees 2000,
         en lien avec l essor des produits indiciels (futures, ETF : arbitrage indice / actions) ; elle est negative sur
         les futures et les ETF depuis leur creation. Mesure MAC(5) = strategie qui prend chaque jour la position
         -(4 r(t-1) + 3 r(t-2) + 2 r(t-3) + r(t-4)) : Sharpe annuel 0,67 sur le S&P 500 apres le 2 mars 1999 (0,63 sur
         tous les indices), jusqu a fin 2016 ; Sharpe semblables sur futures et ETF.
 [NAG12] [T] S. Nagel (Stanford/Chicago), « Evaporating Liquidity », Review of Financial Studies 25, 2012 (NBER w17653) :
         les gains des strategies de retournement de court terme remunerent la fourniture de liquidite ; leur esperance
         est fortement predite par le VIX (elle monte avec lui, crise 2007-2009).
 [CMVJ19] [T] A. Cieslak (Duke), A. Morse (Berkeley), A. Vissing-Jorgensen (Berkeley), « Stock Returns over the FOMC
         Cycle », Journal of Finance 74, 2019 (lu pour cycle_fomc.py) : apres une baisse des actions, la Fed reagit
         (« Fed put ») ; sur nos donnees 2017-2026 la version « semaine paire » echoue (cycle_fomc.py).
 [LM90]  [R] A. Lo (MIT), C. MacKinlay (Wharton), « When are contrarian profits due to stock market overreaction? »,
         Review of Financial Studies 3, 1990 : les indices avaient une autocorrelation POSITIVE (avant 2000).
 [LEH90] [R] B. Lehmann (UCSD/NBER), « Fads, Martingales, and Market Efficiency », Quarterly Journal of Economics 105,
         1990 : retournement hebdomadaire des actions individuelles.
 [CMVJ/UPP25] [R] contre-papier deja lu pour cycle_fomc.py (Uppal, Imperial, 2025) : le cycle du FOMC ne se replique pas
         apres 2016, ce qui pousse a ne PAS conditionner sur la semaine du cycle.
Lecture commune : depuis 2000, et a cause de l arbitrage des produits indiciels, les indices se retournent a court terme
(BVBD19) ; le gain est une prime de liquidite qui grandit avec le VIX (NAG12) ; l ancienne autocorrelation positive
(LM90) a disparu. Strategie retenue : MAC(5) de BVBD19 telle quelle sur nos trois indices ; reference : la meme modulee
par le VIX (NAG12) ; temoin : la meme sur nos futures NON indiciels (or, petrole, devises), ou le mecanisme d arbitrage
indice / actions n existe pas.

Donnees : futures Databento, cloture 16:00 ET au prix reel, rendements quotidiens (jours de roulement exclus, comptes
comme nuls dans le signal) ; VIX : cloture officielle du CBOE (.cache/fred/VIX_History.csv).

ETAPE 1 - l anomalie : autocorrelation d ordre 1 des rendements quotidiens et MAC(5) brute (moyenne de
  r(t) x -(4 r(t-1) + 3 r(t-2) + 2 r(t-3) + r(t-4)), t robuste) par contrat et par periode 2016-2020 / 2021-2026 ;
  BVBD19 predisent < 0 pour l autocorrelation et > 0 pour MAC(5) sur les indices.
ETAPE 2 - strategies (regles figees, quotidiennes, nettes de couts)
  - V  = MAC(5) de BVBD19 sur ES NQ YM : signal z(t) = (4 r(t-1) + 3 r(t-2) + 2 r(t-3) + r(t-4)) / (racine(30) sigma),
         sigma = volatilite quotidienne ex ante de la veille (moyenne exponentielle des carres, centre de masse 60 j) ;
         position = -z x 1 % / sigma (lineaire comme dans le papier, sans borne), risque egal par contrat ;
  - R1 = V multipliee par VIX(t-1) / moyenne du VIX des 252 seances precedentes (NAG12) ;
  - temoin = la construction de V sur GC CL 6E 6B 6J 6A, ramenee au meme budget de risque (poids x 3/6) ;
  - couts : |variation de poids| x (1 tick + 2,50 $) / prix par cote, plus le roulement (2 cotes x |poids|), stress
    2 ticks.
  Criteres (fixes avant le calcul), sur les rendements quotidiens nets de V : t >= 3 ; meme signe et t >= 1,5 sur
  2016-2020 et 2021-2026 ; Welch >= 2 contre le temoin ; net > 0 ; net > 0 sans les 3 meilleurs jours ; Sharpe deflate
  >= 0,95 pour 53 essais (51 precedents + V, R1).
Compatibilite prop firm : position tenue d une cloture a l autre (nuit comprise) : NON compatible avec une prop firm
intraday telle quelle.
"""
from __future__ import annotations

import argparse
import math
import os
from datetime import datetime

import numpy as np
import pandas as pd

from .alternatives import dsr
from .derive_nocturne import vix
from .saisonnalite import rendement
from .soixante import PY_DIR, criteres, exporter, marche
from .tendance import quotidien, sharpe

INDICES = ("ES", "NQ", "YM")
AUTRES = ("GC", "CL", "6E", "6B", "6J", "6A")
COUPURE = pd.Timestamp("2021-01-01")
RISQUE_JOUR = 0.01
N_ESSAIS, SEUIL_DSR = 53, 0.95


def mac5(r: pd.Series) -> pd.Series:
    """4 r(t-1) + 3 r(t-2) + 2 r(t-3) + r(t-4) (rendements manquants comptes comme nuls)."""
    x = r.fillna(0.0)
    return 4 * x.shift(1) + 3 * x.shift(2) + 2 * x.shift(3) + x.shift(4)


def vol_veille(r: pd.Series) -> pd.Series:
    """Volatilite quotidienne ex ante connue a la cloture de la veille."""
    return np.sqrt((r ** 2).ewm(com=60, adjust=False, min_periods=20).mean()).shift(1)


def poids(d: dict, marches) -> pd.DataFrame:
    out = {}
    for mk in marches:
        r = d[mk].r
        sig = vol_veille(r)
        z = mac5(r) / (math.sqrt(30) * sig)
        out[mk] = -z * RISQUE_JOUR / sig
    return pd.DataFrame(out)


def t_newey_west(x: pd.Series, lags: int = 5) -> float:
    x = x.dropna().to_numpy()
    n = len(x)
    if n < 30:
        return math.nan
    e = x - x.mean()
    v = e @ e / n
    for k in range(1, lags + 1):
        v += 2 * (1 - k / (lags + 1)) * (e[k:] @ e[:-k]) / n
    return float(x.mean() / math.sqrt(v / n)) if v > 0 else math.nan


def etude(sortie: str | None = None, log=print) -> dict:
    t0 = datetime.now()
    L = []
    pr = L.append
    pr("=" * 118)
    pr(" RACHAT APRES BAISSE : RETOURNEMENT DE COURT TERME DES INDICES (MAC(5) DE BALTUSSEN, VAN BEKKUM & DA 2019) SUR ES NQ YM")
    pr("=" * 118)
    pr("Protocole et sources : en-tete de nexus/perso/rachat_baisse.py. TEST PARTIELLEMENT NON AVEUGLE : verdict indicatif.\n")
    d = {mk: quotidien(marche(mk)) for mk in INDICES + AUTRES}

    pr("ETAPE 1 - l anomalie (autocorrelation d ordre 1 | t de Newey-West de la MAC(5) brute r(t) x -signal)")
    for mk in INDICES + AUTRES:
        r = d[mk].r
        brut = r * -mac5(r)
        parts = []
        for lib, sel in (("2016-2020", r.index < COUPURE), ("2021-2026", r.index >= COUPURE)):
            rr = r[sel]
            ac = rr.autocorr(1)
            parts.append(f"{lib} : ac1 {ac:+.3f}, MAC5 t {t_newey_west(brut[sel]):+.2f}")
        pr(f"  {mk:<3} " + " | ".join(parts))

    pr("\nETAPE 2 - strategies (rendements quotidiens nets de couts, en pb du capital)")
    w_v = poids(d, INDICES)
    v = vix().shift(1)
    mod = (v / v.rolling(252, min_periods=200).mean().shift(1)).reindex(w_v.index).ffill()
    w_r1 = w_v.mul(mod, axis=0)
    w_t = poids(d, AUTRES) * len(INDICES) / len(AUTRES)
    tem = rendement(w_t, d, 1)
    res = {}
    for code, w, nom in (("V", w_v, "V MAC(5) de BVBD19 sur ES NQ YM"),
                         ("R1", w_r1, "R1 MAC(5) modulee par le VIX (Nagel 2012)")):
        s, s2 = rendement(w, d, 1), rendement(w, d, 2)
        c = criteres(s * 1e4, tem * 1e4, 0.0)
        p_dsr = dsr(s, N_ESSAIS)
        res[code] = dict(c, dsr=p_dsr, sharpe_an=sharpe(s), stress=sharpe(s2), nom=nom)
        pr(f"  --- {nom} : {c['n']} jours | net {c['moyenne']:+.2f} pb/j (t {c['t']:+.2f}) | 2016-2020 t {c['t1']:+.2f} | 2021-2026 t {c['t2']:+.2f}")
        pr(f"      temoin non indiciel {c['temoin']:+.2f} pb/j, Welch {c['welch']:+.2f} | sans les 3 meilleurs jours {c['sans3']:+.2f} | "
           f"Sharpe net {sharpe(s):.2f} (stress 2 ticks {sharpe(s2):.2f}) | Sharpe deflate ({N_ESSAIS} essais) {p_dsr:.2f}")
    a, b = tem[tem.index < COUPURE], tem[tem.index >= COUPURE]
    pr(f"      temoin (MAC(5) sur or, petrole et devises) : Sharpe {sharpe(tem):+.2f} (2016-2020 {sharpe(a):+.2f}, 2021-2026 {sharpe(b):+.2f})")
    vv = res["V"]
    echecs = [k for k, ok in vv["tests"].items() if not ok] + ([] if vv["dsr"] >= SEUIL_DSR else [f"Sharpe deflate >= {SEUIL_DSR:.2f}"])
    pr("\nVERDICT (V, indicatif car partiellement non aveugle) : " + ("passerait les criteres" if not echecs else "ECHOUE (" + " ; ".join(echecs) + ")"))
    pr(f"Calcul en {(datetime.now() - t0).total_seconds():.0f} s.")
    sortie = sortie or os.path.join(PY_DIR, "recherche", "resultats_rachat_baisse.txt")
    with open(sortie, "w", encoding="utf-8") as fh:
        fh.write("\n".join(L) + "\n")
    exporter("rachat_baisse", dict(
        titre="Rachat apres baisse : retournement de court terme des indices (six travaux, test partiellement non aveugle)",
        sous="Baltussen, van Bekkum & Da (JFE 2019), Nagel (RFS 2012), Cieslak, Morse & Vissing-Jorgensen (JF 2019), Lo & MacKinlay "
             "(RFS 1990), Lehmann (QJE 1990), Uppal (2025). V = position contraire a 4 r(t-1) + 3 r(t-2) + 2 r(t-3) + r(t-4) sur ES NQ "
             "YM ; temoin = la meme sur or, petrole et devises. Idee notee apres coup : verdict indicatif. Protocole : "
             "nexus/perso/rachat_baisse.py.",
        lignes=[dict(code=k, nom=x["nom"], n=x["n"], moyenne=x["moyenne"], t=x["t"], t1=x["t1"], t2=x["t2"], temoin=x["temoin"],
                     welch=x["welch"], sans3=x["sans3"], dsr=x["dsr"], sharpe_an=x["sharpe_an"], stress=x["stress"])
                for k, x in res.items()],
        temoin_sharpe=sharpe(tem), echecs=echecs + ["test partiellement non aveugle"], retenue=False))
    log("\n".join(L))
    return dict(etape2=res, echecs=echecs)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--sortie", default=None)
    a = ap.parse_args(argv)
    etude(a.sortie)


if __name__ == "__main__":
    main()
