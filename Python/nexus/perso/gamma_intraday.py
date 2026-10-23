"""Momentum de fin de seance conditionne par le gamma des dealers d options (hypothese H2 de l arbre) sur ES.

    python -m nexus.perso.gamma_intraday [--sortie resultats_gamma_intraday.txt]

PROTOCOLE ECRIT LE 2026-10-12, AVANT TOUT CALCUL CONDITIONNEL (methode : memoire « methode-strategie-papiers » ;
hypothese H2 de C:\\Users\\Mathis\\Documents\\arbres\\market-intraday-momentum\\04_synthese.md).

TEST PARTIELLEMENT NON AVEUGLE, annonce avant le calcul : la version INCONDITIONNELLE (H1 = signe du rendement
cloture de la veille -> 15h30, tenu de 15h30 a 16h00) a deja ete mesuree sur ES dans les 60 strategies (« ES 5 » :
+0,46 pb par jour, t 1,0 ; 2016-2020 t 1,6 ; 2021-2026 t -0,4 ; net de couts -0,40 pb). Le decoupage par le signe du
gamma n a jamais ete calcule sur nos donnees ; les donnees de gamma n ont ete ouvertes que pour verifier leur format.

Sources (texte complet lu = [T], resume seulement = [R])
 [BDLM21] [T] G. Baltussen (Erasmus/Northern Trust), Z. Da (Notre Dame), S. Lammers, M. Martens (Robeco), « Hedging demand
         and market intraday momentum », Journal of Financial Economics 142, 2021 : plus de 60 futures 1974-2020 ; le
         rendement du « reste de la journee » r_ROD = P(cloture - 30 min, t) / P(cloture, t-1) - 1 predit la derniere
         demi-heure r_LH, puis s inverse les jours suivants ; cause : la couverture des vendeurs d options (et des ETF a
         levier) qui sont courts en gamma. Gamma net des teneurs de marche (NGE) = somme sur toutes les options SPX de
         gamma x OI x 100 x indice (calls comptes longs, puts comptes courts pour les teneurs de marche), divisee par la
         capitalisation ; 1996-2017 OptionMetrics, prolonge jusqu en 2020 avec SqueezeMetrics (« virtually identical »
         sur 2002-2017). Table 7 (1996-2020) : NGE(t-1) < 0 : pente 6,63 (t 4,78) ; NGE(t-1) >= 0 : pente 0,82 (t 1,03),
         c est-a-dire PAS de momentum mais pas de retournement significatif non plus. Table 8 : interaction
         1[NGE <= 0] x r_ROD = 5,05 (t 3,04).
 [SQZ17] [T] SqueezeMetrics (Prior Analytics), « Gamma Exposure (GEX) », 2016 revise 2017 : meme construction (calls
         longs, puts courts pour les teneurs de marche, couverture exacte au delta) ; GEX > 0 : les teneurs de marche
         achetent les baisses et vendent les hausses (volatilite amortie) ; GEX < 0 : l inverse (volatilite amplifiee).
 [DEV24] [R] C. Dim (Frankfurt School), B. Eraker (Wisconsin), G. Vilkov (Frankfurt School), « 0DTEs: Trading, Gamma
         Risk and Volatility Propagation », 2024 : a l ere des options du jour (0DTE), le gamma net des teneurs de marche
         est en moyenne POSITIF ; gamma positif -> retournement renforce, gamma negatif -> momentum renforce ; les chocs
         de volume 0DTE n amplifient pas les rendements passes. C est ce papier, pas BDLM21, qui fonde la jambe
         « retournement quand le gamma est positif ».
 [AFO24] [R] G. Adams, J.-S. Fontaine, C. Ornthanalai, « The Market for 0-Days-to-Expiration », 2024 : volatilite de
         l indice plus basse d environ 60 pb annualises les jours avec 0DTE (couverture des teneurs de marche).
 [BB20]  [R] A. Barbon (St. Gallen), A. Buraschi (Imperial), « Gamma Fragility », 2020 : momentum intrajournalier quand
         le gamma est negatif, retournement quand il est positif, plus fort sur les sous-jacents peu liquides.
 [YL22]  [R] X. Yuan, X. Li, Physica A 2022 : meme effet sur l ETF SSE 50 ; les jours a gamma positif les teneurs de
         marche ne compensent pas entierement le momentum.
 [WILL26] [T: resume complet] F. Willeboordse, « Does gamma survive the close? », Finance Research Letters 2026 :
         le gamma Black-Scholes est contamine par le vega a l horizon journalier (correlation gamma empirique /
         theorique de -0,25 a -0,47 sur 2020-2025) : les mesures publiques de type GEX sont fragiles.
 [PAZ26] [R] S. Paz, 2026 : la strategie de momentum intrajournalier de Zarattini et al. (2024) sur SPY tombe a un
         Sharpe de 0,39 hors echantillon (05/2024-03/2026) contre 1,34 avant.
 [MES26] [T] M. Mesfin, arXiv 2605.04004, 2026 : aucun des 14 signaux de momentum intrajournalier OHLCV ne survit sur le
         micro Nasdaq (MNQ) 2021-2025 apres couts.
Lecture commune : le momentum de fin de seance n existe que si les teneurs de marche sont courts en gamma (BDLM21,
SQZ17, BB20) ; depuis les 0DTE leur gamma est plus souvent positif, ce qui eteint le momentum moyen (DEV24, AFO24,
PAZ26, MES26) et devrait faire apparaitre un retournement (DEV24, BB20). Strategie demandee : H2 de l arbre.

Donnees
  ES (Databento, minutes, prix reels) : r_ROD = log(P 15h30 / P 16h00 de la veille), r_LH = log(P 16h00 / P 15h30),
  heure de New York, conventions et exclusions de « ES 5 » (jour exclu si un prix manque ou si l echeance change ;
  les seances courtes, sans cotation a 15h30-16h00, tombent d elles-memes).
  Gamma : GEX quotidien de SqueezeMetrics (.cache/gex/DIX.csv, telechargement public gratuit, jamais redistribue),
  la source qu utilisent BDLM21 apres 2017 ; on prend la derniere valeur datee AVANT le jour t (GEX(t-1), comme la
  Table 7 de BDLM21). Limites : la valeur repose sur l open interest du debut de journee, donc ignore les 0DTE ouverts
  dans la journee (DEV24, AFO24) ; pas de mise a jour a 15h30 ; le test de robustesse au biais vega demande par l arbre
  (WILL26 : proxy de couverture delta effective) est impossible sans donnees d options et n est pas fait.

ETAPE 1 - l anomalie et son mecanisme, par periode 2016-2020 / 2021-2026
  1a. part des jours a GEX(t-1) < 0 ;
  1b. Table 7 de BDLM21 : pente de r_LH sur r_ROD separement les jours GEX(t-1) < 0 et >= 0 (t de Newey-West, 5
      retards) ; prediction : pente > 0 si gamma negatif, <= 0 si positif (DEV24) ;
  1c. Table 8 de BDLM21 : r_LH = a + b r_ROD + c 1[GEX(t-1) < 0] r_ROD ; critere d invalidation de l arbre pour H2 :
      c avec t < 2 sur 2021-2026, ou de signe oppose ;
  1d. mecanisme SQZ17 : |r_LH| moyen plus grand les jours a gamma negatif.
ETAPE 2 - strategies (regles figees, une position par jour de 15h30 a 16h00, 1 contrat, rendements en pb)
  - V  = H2 : position = signe(r_ROD) si GEX(t-1) < 0, -signe(r_ROD) si GEX(t-1) > 0 ;
  - R0 = version fidele a BDLM21 : signe(r_ROD) si GEX(t-1) < 0, aucune position sinon ;
  - temoin = H1 inconditionnel : signe(r_ROD) tous les jours (benchmark de l arbre) ;
  - replication (contexte, ni critere ni essai) : la meme regle V sur NQ et YM avec le gamma du S&P 500 ;
  - couts : aller-retour 1 tick + 2,50 $ par cote (cout_bp des 60 strategies), stress 2 ticks.
  Criteres (fixes avant le calcul), sur les rendements par trade nets de V : t >= 3 ; meme signe et t >= 1,5 sur
  2016-2020 et 2021-2026 ; Welch >= 2 contre le temoin H1 ; net > 0 ; net > 0 sans les 3 meilleurs jours ; Sharpe
  deflate >= 0,95 pour 55 essais (53 precedents + V, R0), calcule sur la serie quotidienne nette.
Compatibilite prop firm : position de 30 minutes fermee a 16h00 ET : COMPATIBLE intraday.
"""
from __future__ import annotations

import argparse
import math
import os
from datetime import datetime

import numpy as np
import pandas as pd

from .alternatives import dsr
from .soixante import COUPURE, ET, PY_DIR, cout_bp, criteres, exporter, jours_ouvres_us, marche, r_fenetre, tstat

N_ESSAIS, SEUIL_DSR = 55, 0.95
FICHIER_GEX = os.path.join(PY_DIR, ".cache", "gex", "DIX.csv")


# =============================================================================
#  Donnees
# =============================================================================
def gex() -> pd.Series:
    """GEX quotidien de SqueezeMetrics (dollars par 1 % de mouvement), indexe par date."""
    d = pd.read_csv(FICHIER_GEX)
    return pd.Series(pd.to_numeric(d["gex"], errors="coerce").to_numpy(), index=pd.to_datetime(d["date"])).dropna().sort_index()


def gex_veille(g: pd.Series, jours: pd.DatetimeIndex) -> pd.Series:
    """Derniere valeur de GEX datee strictement avant chaque jour."""
    k = np.searchsorted(g.index.to_numpy(), jours.to_numpy(), side="left") - 1
    v = np.where(k >= 0, g.to_numpy()[np.clip(k, 0, None)], np.nan)
    return pd.Series(v, index=jours)


def fenetres(m) -> pd.DataFrame:
    """r_ROD (16h00 veille -> 15h30) et r_LH (15h30 -> 16h00), log, par jour ouvre US."""
    j = jours_ouvres_us(m)
    rod = r_fenetre(m, j, (16, 0), (15, 30), ET, decal_a=-1)
    lh = r_fenetre(m, j, (15, 30), (16, 0), ET)
    return pd.DataFrame({"rod": rod, "lh": lh}).dropna()


# =============================================================================
#  Regles
# =============================================================================
def positions(rod: pd.Series, g: pd.Series) -> pd.DataFrame:
    """V (H2), R0 (BDLM21) et temoin H1 : +1 / -1 / 0."""
    s = np.sign(rod)
    neg, pos = g < 0, g > 0
    return pd.DataFrame({"V": s.where(neg, -s).where(neg | pos, 0.0),
                         "R0": s.where(neg, 0.0),
                         "H1": s}, index=rod.index)


def ols_nw(y: np.ndarray, X: np.ndarray, lags: int = 5) -> tuple[np.ndarray, np.ndarray]:
    """Coefficients et t de Newey-West."""
    n = len(y)
    xtx = np.linalg.inv(X.T @ X)
    b = xtx @ X.T @ y
    u = (y - X @ b)[:, None] * X
    s = u.T @ u
    for k in range(1, lags + 1):
        g = u[k:].T @ u[:-k]
        s += (1 - k / (lags + 1)) * (g + g.T)
    v = xtx @ s @ xtx * n / (n - X.shape[1])
    return b, b / np.sqrt(np.diag(v))


# =============================================================================
#  Etude
# =============================================================================
def etude(sortie: str | None = None, log=print) -> dict:
    t0 = datetime.now()
    L = []
    pr = L.append
    pr("=" * 118)
    pr(" MOMENTUM DE FIN DE SEANCE CONDITIONNE PAR LE GAMMA DES DEALERS (H2 : BALTUSSEN, DA, LAMMERS & MARTENS 2021) SUR ES")
    pr("=" * 118)
    pr("Protocole et sources : en-tete de nexus/perso/gamma_intraday.py. TEST PARTIELLEMENT NON AVEUGLE (H1 deja vu : ES 5).\n")
    g = gex()
    pr(f"GEX SqueezeMetrics : {g.index[0].date()} -> {g.index[-1].date()} ({len(g)} jours).")
    es = marche("ES")
    f = fenetres(es)
    f["gex"] = gex_veille(g, f.index)
    f = f.dropna()
    per = {"2016-2020": f.index < COUPURE, "2021-2026": f.index >= COUPURE}

    pr("\nETAPE 1 - l anomalie et son mecanisme")
    for lib, sel in per.items():
        x = f[sel]
        neg = x.gex < 0
        pr(f"  {lib} : {len(x)} jours, gamma negatif {neg.mean():.0%}")
        for nom, s in (("gamma < 0", neg), ("gamma >= 0", ~neg)):
            y = x.lh[s].to_numpy() * 1e4
            b, t = ols_nw(y, np.c_[np.ones(s.sum()), x.rod[s].to_numpy() * 1e4])
            pr(f"      1b. {nom:<10} : pente r_LH / r_ROD {b[1] * 100:+.2f} (x100, t NW {t[1]:+.2f}, {s.sum()} jours) | "
               f"1d. |r_LH| moyen {np.abs(y).mean():.2f} pb")
        y = x.lh.to_numpy() * 1e4
        X = np.c_[np.ones(len(x)), x.rod.to_numpy() * 1e4, neg.to_numpy() * x.rod.to_numpy() * 1e4]
        b, t = ols_nw(y, X)
        pr(f"      1c. interaction 1[gamma<0] x r_ROD : {b[2] * 100:+.2f} (x100, t NW {t[2]:+.2f}) ; pente de base {b[1] * 100:+.2f} (t {t[1]:+.2f})")
    x2 = f[per["2021-2026"]]
    b, t = ols_nw(x2.lh.to_numpy() * 1e4, np.c_[np.ones(len(x2)), x2.rod.to_numpy() * 1e4,
                                                   (x2.gex < 0).to_numpy() * x2.rod.to_numpy() * 1e4])
    invalide_arbre = not (b[2] > 0 and t[2] >= 2)
    pr(f"  Critere d invalidation de l arbre (interaction sur 2021-2026, t >= 2 et positive) : "
       f"{'H2 INVALIDEE' if invalide_arbre else 'non invalidee'} (t {t[2]:+.2f})")

    pr("\nETAPE 2 - strategies (15h30 -> 16h00, 1 contrat, pb par trade)")
    pos = positions(f.rod, f.gex)
    prix = float(np.nanmedian(es.c[-500000:]))
    cout, cout2 = cout_bp("ES", prix, False), cout_bp("ES", prix, True)
    brut = pos.mul(f.lh * 1e4, axis=0)
    tem = brut["H1"]
    res = {}
    for code, nom in (("V", "V H2 : momentum si gamma < 0, retournement si gamma > 0"),
                      ("R0", "R0 BDLM21 : momentum si gamma < 0, rien sinon")):
        actif = pos[code] != 0
        x = brut[code][actif]
        c = criteres(x, tem, cout)
        quot = (brut[code] - cout * actif).reindex(f.index).fillna(0.0) / 1e4
        quot2 = (brut[code] - cout2 * actif).reindex(f.index).fillna(0.0) / 1e4
        sh = float(quot.mean() / quot.std() * math.sqrt(252))
        sh2 = float(quot2.mean() / quot2.std() * math.sqrt(252))
        p_dsr = dsr(quot, N_ESSAIS)
        res[code] = dict(c, dsr=p_dsr, sharpe_an=sh, stress=sh2, nom=nom, t_net=tstat(x - cout))
        pr(f"  --- {nom} : {c['n']} trades | brut {c['moyenne']:+.2f} pb (t {c['t']:+.2f}) | 2016-2020 t {c['t1']:+.2f} | 2021-2026 t {c['t2']:+.2f}")
        pr(f"      temoin H1 {c['temoin']:+.2f} pb, Welch {c['welch']:+.2f} | cout {cout:.2f} pb -> net {c['net']:+.2f} pb, sans les 3 meilleurs "
           f"jours {c['sans3']:+.2f} | Sharpe net {sh:.2f} (stress 2 ticks {sh2:.2f}) | Sharpe deflate ({N_ESSAIS} essais) {p_dsr:.2f}")
    t_h1 = tem.dropna()
    pr(f"      temoin H1 (tous les jours) : {t_h1.mean():+.2f} pb brut (t {tstat(t_h1):+.2f}), net {t_h1.mean() - cout:+.2f} pb")
    for root in ("NQ", "YM"):
        m = marche(root)
        fr = fenetres(m)
        fr["gex"] = gex_veille(g, fr.index)
        fr = fr.dropna()
        p = positions(fr.rod, fr.gex)["V"]
        xr = (p * fr.lh * 1e4)[p != 0]
        cr = cout_bp(root, float(np.nanmedian(m.c[-500000:])), False)
        a, b_ = xr[xr.index < COUPURE], xr[xr.index >= COUPURE]
        pr(f"      replication {root} (contexte) : brut {xr.mean():+.2f} pb (t {tstat(xr):+.2f}) | 2016-2020 t {tstat(a):+.2f} | "
           f"2021-2026 t {tstat(b_):+.2f} | net {xr.mean() - cr:+.2f} pb")
    vv = res["V"]
    echecs = [k for k, ok in vv["tests"].items() if not ok] + ([] if vv["dsr"] >= SEUIL_DSR else [f"Sharpe deflate >= {SEUIL_DSR:.2f}"])
    pr("\nVERDICT (V) : " + ("passe les criteres (indicatif : test partiellement non aveugle)" if not echecs
                            else "ECHOUE (" + " ; ".join(echecs) + ")"))
    pr(f"Calcul en {(datetime.now() - t0).total_seconds():.0f} s.")
    sortie = sortie or os.path.join(PY_DIR, "recherche", "resultats_gamma_intraday.txt")
    with open(sortie, "w", encoding="utf-8") as fh:
        fh.write("\n".join(L) + "\n")
    exporter("gamma_intraday", dict(
        titre="Momentum de fin de seance conditionne par le gamma des dealers (H2, ES)",
        sous="Baltussen, Da, Lammers & Martens (JFE 2021), SqueezeMetrics (2017), Dim, Eraker & Vilkov (2024), Adams, Fontaine & "
             "Ornthanalai (2024), Barbon & Buraschi (2020), Yuan & Li (2022), Willeboordse (2026), Paz (2026), Mesfin (2026). "
             "V = signe du rendement 16h00 veille -> 15h30, tenu jusqu a 16h00, inverse quand le gamma de la veille est "
             "positif ; temoin = sans conditionnement (H1). Gamma : GEX public de SqueezeMetrics. Protocole : "
             "nexus/perso/gamma_intraday.py.",
        lignes=[dict(code=k, nom=x["nom"], n=x["n"], moyenne=x["net"], t=x["t_net"], t1=x["t1"], t2=x["t2"], temoin=x["temoin"],
                     welch=x["welch"], sans3=x["sans3"], dsr=x["dsr"], sharpe_an=x["sharpe_an"], stress=x["stress"])
                for k, x in res.items()],
        invalide_arbre=invalide_arbre, echecs=echecs + (["critere d invalidation de l arbre"] if invalide_arbre else []),
        retenue=not echecs and not invalide_arbre))
    log("\n".join(L))
    return dict(etape2=res, echecs=echecs, invalide_arbre=invalide_arbre)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--sortie", default=None)
    a = ap.parse_args(argv)
    etude(a.sortie)


if __name__ == "__main__":
    main()
