"""Saisonnalite des rendements (meme mois calendaire) sur nos 9 futures : strategie construite sur huit travaux.

    python -m nexus.perso.saisonnalite [--sortie resultats_saisonnalite.txt]

PROTOCOLE ECRIT LE 2026-10-11, AVANT TOUT CALCUL SUR NOS DONNEES (methode : memoire « methode-strategie-papiers »).
Troisieme des candidats classes « du plus prometteur au moins prometteur » apres la lecture des meta-etudes.

Sources (texte complet lu = [T], resume seulement = [R])
 [KLN16] [T] M. Keloharju (Aalto), J. Linnainmaa (USC/Chicago), P. Nyberg (Aalto), « Return Seasonalities », Journal of
         Finance 71, 2016 (NBER w20815) : un actif qui a bien (mal) rendu dans un mois calendaire donne, relativement aux
         autres, rend encore bien (mal) ce mois-la les annees suivantes, jusqu a 20 ans. Signal = rendement moyen du meme
         mois calendaire sur les 20 annees precedentes (au moins 5 ans d historique) ; temoin = rendement moyen des AUTRES
         mois calendaires ; 24 matieres premieres 1975-2011 : 0,93 %/mois (t 1,93), autres mois -0,22 % (t -0,58),
         difference t 1,97 ; 15 indices actions nationaux : 0,48 %/mois (t 2,20), difference t 2,76 ; valable hors janvier ;
         correlations faibles entre classes d actifs.
 [KLN21] [R] Keloharju, Linnainmaa, Nyberg, « Are return seasonalities due to risk or mispricing? », Journal of Financial
         Economics 139, 2021 (version 2018 lue en resume et introduction) : les saisonnalites sont compensees par des
         « retournements saisonniers » les autres mois (somme nulle sur l annee) : erreur de prix temporaire ; facteur
         combine meme mois / autres mois robuste sur 1963-2016.
 [BSV21] [T] G. Baltussen, L. Swinkels, P. van Vliet (Erasmus, Robeco), « Global Factor Premiums », Journal of Financial
         Economics 142, 2021 : saisonnalite = rendement d un actif dans le meme mois sur les 20 annees precedentes ;
         portefeuille = rang moins rang moyen dans chaque classe, positions a volatilite ex ante constante. 1981-2011 :
         indices actions Sharpe 0,36 (t 2,00), matieres premieres 0,48 (t 2,67), devises 0,00, obligations -0,09 ;
         echantillon long 1800-2016 : actions 0,42, matieres premieres 0,71, devises 0,22. Decaler le signal d un mois
         annule la prime (l effet est propre au mois).
 [HS08]  [R] S. Heston (Maryland), R. Sadka (Boston College), « Seasonality in the cross-section of stock returns », Journal
         of Financial Economics 87, 2008 : autocorrelation aux retards de 12, 24, ... 240 mois.
 [BAL16] [R] N. Baltas (Imperial College / UBS), « Multi-Asset Seasonality and Trend-Following Strategies », Bankers,
         Markets & Investors 140, 2016 : 1992-2015, saisonnalite significative dans les matieres premieres et (moins) les
         indices actions, pas dans les obligations ni les devises ; couteuse a trader seule.
 [HK21]  [R] P. Hofmann, K. Keiber, « Seasonalities in the German stock market », Financial Markets and Portfolio Management
         35, 2021 : hors echantillon 1998-2017, les strategies saisonnieres restent rentables (actions allemandes).
 [MP16]  [T] R. D. McLean (Alberta/DePaul), J. Pontiff (Boston College), « Does Academic Research Destroy Stock Return
         Predictability? », Journal of Finance 71, 2016 : -26 % hors echantillon, -58 % apres publication en moyenne.
 [JM20]  [R] H. Jacobs (Duisburg-Essen), S. Mueller (TU Munich), « Anomalies across the globe: Once public, no longer
         existent? », Journal of Financial Economics 135, 2020 : baisse apres publication fiable seulement aux Etats-Unis.
Lecture commune : la saisonnalite existe dans les indices actions et les matieres premieres (KLN16, BSV21, BAL16), pas
dans les devises (BSV21 1981-2011, BAL16) ; elle releve plutot d une erreur de prix (KLN21) et a resiste apres 2011 sur
d autres donnees (HK21), avec l erosion habituelle apres publication (MP16). Strategie retenue : la saisonnalite de BSV21
telle quelle sur nos classes ou les papiers la trouvent (indices actions ES NQ YM, matieres premieres GC CL) ; les
devises servent de reference (prediction des papiers : rien).

Donnees
  Signal : series GRATUITES Yahoo Finance (une seule source pour tout l historique, cache .cache/yahoo/) : S&P 500
  (^GSPC, 1970-), Nasdaq-100 (^NDX, 1985-), Dow Jones (^DJI, 1992-), or (ETF GLD, 2004-, sans saut de roulement),
  petrole (CL=F, 2000-, premier contrat raccorde sans ajustement : le saut de roulement tombe chaque mois, donc biais de
  niveau commun a tous les mois), devises EURUSD, GBPUSD, JPY (inverse), AUDUSD (2003-2006-). Rendements mensuels =
  cloture de fin de mois ; indices hors dividendes ; devises + differentiel de taux a 3 mois OCDE / 12 (.cache/fred/,
  Japon avant 2002-04 = premiere valeur connue) pour obtenir un rendement excedentaire comme BSV21. La FRED (series de
  change depuis 1971) etait inaccessible le 2026-10-11 (connexion coupee) : non utilisee.
  Signal du mois m = moyenne des rendements du meme mois calendaire sur les 20 annees precedentes, au moins 5 ans
  (KLN16) ; temoin = moyenne des 11 autres mois calendaires sur la meme fenetre de 20 ans (KLN16).
  Rendements de la strategie : futures Databento (cloture 16:00 ET au prix reel, jours de roulement exclus).

ETAPE 1 - l anomalie
  1a. sur les series gratuites, avant nos futures : portefeuilles long-court par classe (poids = rang - rang moyen,
      ramenes a [-1, 1], sans mise a l echelle, comme KLN16) en mois meme / autres mois, rendement mensuel et t, sur
      l echantillon des papiers (jusqu a 2011) et apres (2012-2015) ;
  1b. sur nos futures : la meme chose par periode 2016-2020 / 2021-2026.
ETAPE 2 - strategies (regles figees, poids fixes pour le mois, rendements quotidiens nets de couts)
  - V  = saisonnalite BSV21 sur indices actions (ES NQ YM) et matieres premieres (GC CL) : dans chaque classe, z = (rang
         du signal - rang moyen) ramene a [-1, 1] ; position = z x 1 % / volatilite quotidienne ex ante (moyenne
         exponentielle des carres, centre de masse 60 jours, MOP12/BSV21) mesuree a la fin du mois precedent ;
  - R1 = la meme sur les trois classes, devises comprises (le « multi-actifs » de BSV21 sans obligations) ;
  - temoin = V construite avec le signal « autres mois » (KLN16 : meme - autres) ;
  - couts : |variation de poids| x (1 tick + 2,50 $) / prix par cote, plus le roulement (2 cotes x |poids|), stress
    2 ticks. Simplification : pas de mise a l echelle au niveau de la classe (risque egal par contrat).
  Criteres (fixes avant le calcul), sur les rendements quotidiens nets de V : t >= 3 ; meme signe et t >= 1,5 sur
  2016-2020 et 2021-2026 ; Welch >= 2 contre le temoin ; net > 0 ; net > 0 sans les 3 meilleurs jours ; Sharpe deflate
  >= 0,95 pour 49 essais (47 precedents + V, R1).
  Limite annoncee avant le calcul : nos classes sont minces (3 indices americains tres correles, 2 matieres premieres
  contre 15 pays et 24 matieres premieres chez KLN16) ; la puissance du test est faible.
Compatibilite prop firm : positions tenues un mois : NON compatible avec une prop firm intraday.
"""
from __future__ import annotations

import argparse
import json
import math
import os
from datetime import datetime

import numpy as np
import pandas as pd

from .alternatives import dsr
from .soixante import COMMISSION, COUTS, PY_DIR, criteres, exporter, marche, tstat
from .tendance import quotidien, sharpe

CLASSES = {"actions": ("ES", "NQ", "YM"), "matieres": ("GC", "CL"), "devises": ("6E", "6B", "6J", "6A")}
YAHOO = {"ES": "GSPC", "NQ": "NDX", "YM": "DJI", "GC": "GLD", "CL": "CL=F",
         "6E": "EURUSD=X", "6B": "GBPUSD=X", "6J": "JPY=X", "6A": "AUDUSD=X"}
TAUX = {"6E": "EZ", "6B": "GB", "6J": "JP", "6A": "AU"}
COUPURE = pd.Timestamp("2021-01-01")
FIN_PAPIERS = pd.Period("2011-12", "M")
FENETRE, MIN_ANS = 20, 5
RISQUE_JOUR = 0.01
N_ESSAIS, SEUIL_DSR = 49, 0.95
CACHE_Y = os.path.join(PY_DIR, ".cache", "yahoo")
CACHE_F = os.path.join(PY_DIR, ".cache", "fred")


# =============================================================================
#  Donnees gratuites (signal)
# =============================================================================
def yahoo(sym: str) -> pd.Series:
    """Clotures quotidiennes d un fichier JSON de l API chart de Yahoo."""
    with open(os.path.join(CACHE_Y, f"{sym}.json"), encoding="utf-8") as fh:
        r = json.load(fh)["chart"]["result"][0]
    s = pd.Series(r["indicators"]["quote"][0]["close"], index=pd.to_datetime(r["timestamp"], unit="s").normalize(), dtype=float)
    return s[~s.index.duplicated(keep="last")].dropna()


def taux_oecd() -> pd.DataFrame:
    out = {}
    for p in ("US", *TAUX.values()):
        f = pd.read_csv(os.path.join(CACHE_F, f"IR3TIB01{p}M156N.csv"))
        s = pd.to_numeric(f.iloc[:, 1], errors="coerce")
        s.index = pd.to_datetime(f.iloc[:, 0]).dt.to_period("M")
        out[p] = s.dropna()
    return pd.DataFrame(out).sort_index()


def mensuels_gratuits() -> pd.DataFrame:
    """Rendements mensuels (log) des series gratuites ; devises en rendement excedentaire (spot + differentiel / 12)."""
    out = {}
    t = taux_oecd()
    for mk, sym in YAHOO.items():
        p = yahoo(sym)
        if mk == "6J":
            p = 1.0 / p                                                    # JPY=X : yens par dollar -> dollars par yen
        fin = p.groupby(p.index.to_period("M")).last()
        r = np.log(fin).diff()
        if mk in TAUX:
            tt = t.reindex(pd.period_range(min(t.index[0], r.index[0]), r.index[-1], freq="M")).ffill().bfill()
            dif = (tt[TAUX[mk]] - tt["US"]).shift(1)                       # taux connu au debut du mois tenu
            r = r + dif.reindex(r.index) / 1200
        out[mk] = r
    return pd.DataFrame(out).sort_index()


# =============================================================================
#  Signaux et poids
# =============================================================================
def signaux(rm: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Pour chaque mois m : moyenne des rendements du meme mois calendaire sur les 20 annees precedentes (>= 5 ans) et
    moyenne des 11 autres mois calendaires sur la meme fenetre."""
    idx = pd.period_range(rm.index[0], rm.index[-1] + 1, freq="M")
    rm = rm.reindex(idx)
    meme = pd.DataFrame(np.nan, index=idx, columns=rm.columns)
    autre = meme.copy()
    for k, m in enumerate(idx):
        fen = rm.iloc[max(0, k - 12 * FENETRE):k]
        if fen.empty:
            continue
        cal = fen.index.month == m.month
        ms, nb = fen[cal].mean(), fen[cal].notna().sum()
        ao, na = fen[~cal].mean(), fen[~cal].notna().sum()
        meme.iloc[k] = ms.where(nb >= MIN_ANS)
        autre.iloc[k] = ao.where(nb >= MIN_ANS)
    return meme, autre


def z_rang(sig: pd.DataFrame, classes) -> pd.DataFrame:
    """Dans chaque classe : rang - rang moyen, ramene a [-1, 1] (0 si un seul actif valide)."""
    out = []
    for nom in classes:
        cols = list(CLASSES[nom])
        s = sig[cols]
        rg = s.rank(axis=1, method="average")
        c = rg.sub(rg.mean(axis=1), axis=0)
        mx = c.abs().max(axis=1).replace(0, np.nan)
        z = c.div(mx, axis=0).mask(c == 0, 0.0)                         # tous ex aequo : pas de position
        out.append(z.where(s.notna().sum(axis=1) >= 2, np.nan))
    return pd.concat(out, axis=1)


def portefeuille_brut(z: pd.DataFrame, rm: pd.DataFrame) -> pd.Series:
    """Rendement mensuel brut d un portefeuille de poids z (sans mise a l echelle) : moyenne par classe active."""
    x = (z * rm.reindex(z.index)[z.columns])
    return x.sum(axis=1, min_count=1)


# =============================================================================
#  Futures (rendements de la strategie)
# =============================================================================
def donnees() -> dict:
    return {mk: quotidien(marche(mk)) for cl in CLASSES.values() for mk in cl}


def vol_fin_de_mois(d: dict) -> pd.DataFrame:
    """Volatilite quotidienne ex ante (moyenne exponentielle des carres, centre de masse 60 j) au dernier jour du mois."""
    out = {}
    for mk, x in d.items():
        v = np.sqrt((x.r ** 2).ewm(com=60, adjust=False, min_periods=20).mean())
        out[mk] = v.groupby(v.index.to_period("M")).last()
    return pd.DataFrame(out)


def poids_quotidiens(z: pd.DataFrame, vol: pd.DataFrame, jours: pd.DatetimeIndex) -> pd.DataFrame:
    """Poids du mois m = z du mois m (signal connu fin m-1) x 1 % / volatilite de fin m-1."""
    v = vol.copy()
    v.index = v.index + 1
    w = z * RISQUE_JOUR / v.reindex(z.index)[z.columns]
    return w.reindex(jours.to_period("M")).set_axis(jours)


def rendement(w: pd.DataFrame, d: dict, ticks: int) -> pd.Series:
    r = pd.DataFrame({mk: d[mk].r for mk in w.columns}).reindex(w.index)
    brut = (w * r).sum(axis=1, min_count=1)
    prix = {mk: float(np.nanmedian(d[mk].prix.iloc[-500:])) for mk in w.columns}
    cu = pd.Series({mk: (ticks * COUTS[mk][0] + COMMISSION / COUTS[mk][1]) / prix[mk] for mk in w.columns})
    roul = pd.DataFrame({mk: d[mk].r.isna() & d[mk].prix.notna() & d[mk].prix.shift(1).notna() for mk in w.columns})
    rot = w.fillna(0).diff().abs() + 2 * w.abs().where(roul.reindex(w.index).fillna(False).astype(bool), 0.0)
    return (brut - (rot * cu).sum(axis=1)).dropna()


# =============================================================================
#  Etude
# =============================================================================
def _ligne(x: pd.Series) -> str:
    x = x.dropna()
    return f"{x.mean() * 100:+.2f} %/mois (t {tstat(x):+.2f}, {len(x)} mois)" if len(x) > 2 else "n/d"


def etude(sortie: str | None = None, log=print) -> dict:
    t0 = datetime.now()
    L = []
    pr = L.append
    pr("=" * 118)
    pr(" SAISONNALITE DES RENDEMENTS (MEME MOIS CALENDAIRE) SUR NOS 9 FUTURES : STRATEGIE CONSTRUITE SUR HUIT TRAVAUX")
    pr("=" * 118)
    pr("Protocole et sources : en-tete de nexus/perso/saisonnalite.py (ecrit avant le calcul).\n")
    rg = mensuels_gratuits()
    meme, autre = signaux(rg)
    pr("Series gratuites (Yahoo) : debut " + ", ".join(f"{mk} {rg[mk].first_valid_index()}" for mk in rg.columns) +
       f" ; fin {rg.index[-1]}.")

    pr("\nETAPE 1 - l anomalie")
    pr("  1a. series gratuites, portefeuilles long-court par classe sans mise a l echelle (meme mois | autres mois | meme - autres) :")
    for nom in CLASSES:
        zm, za = z_rang(meme, [nom]), z_rang(autre, [nom])
        pm, pa = portefeuille_brut(zm, rg), portefeuille_brut(za, rg)
        for lib, sel in (("jusqu a 2011", lambda ix: ix <= FIN_PAPIERS),
                         ("2012-2015", lambda ix: (ix > FIN_PAPIERS) & (ix < pd.Period("2016-01", "M")))):
            a, b = pm[sel(pm.index)], pa[sel(pa.index)]
            pr(f"      {nom:<9} {lib:<12} : {_ligne(a)} | {_ligne(b)} | {_ligne((a - b).dropna())}")

    d = donnees()
    jours = pd.DatetimeIndex(sorted(set().union(*[x.index for x in d.values()])))
    rf = pd.DataFrame({mk: x.r for mk, x in d.items()})
    rfm = rf.groupby(rf.index.to_period("M")).sum(min_count=5)
    pr("  1b. futures, memes portefeuilles (meme mois | autres mois | meme - autres) :")
    for nom in CLASSES:
        zm, za = z_rang(meme, [nom]).reindex(rfm.index), z_rang(autre, [nom]).reindex(rfm.index)
        pm, pa = portefeuille_brut(zm, rfm), portefeuille_brut(za, rfm)
        for lib, sel in (("2016-2020", lambda ix: ix < COUPURE.to_period("M")), ("2021-2026", lambda ix: ix >= COUPURE.to_period("M"))):
            a, b = pm[sel(pm.index)], pa[sel(pa.index)]
            pr(f"      {nom:<9} {lib:<12} : {_ligne(a)} | {_ligne(b)} | {_ligne((a - b).dropna())}")

    pr("\nETAPE 2 - strategies (rendements quotidiens nets de couts, en pb du capital)")
    vol = vol_fin_de_mois(d)
    mois = rfm.index
    w_v = poids_quotidiens(z_rang(meme, ["actions", "matieres"]).reindex(mois), vol, jours)
    w_t = poids_quotidiens(z_rang(autre, ["actions", "matieres"]).reindex(mois), vol, jours)
    w_r1 = poids_quotidiens(z_rang(meme, list(CLASSES)).reindex(mois), vol, jours)
    tem = rendement(w_t, d, 1)
    res = {}
    for code, w, nom in (("V", w_v, "V saisonnalite BSV21 sur actions et matieres premieres"),
                         ("R1", w_r1, "R1 saisonnalite sur les trois classes (devises comprises)")):
        s, s2 = rendement(w, d, 1), rendement(w, d, 2)
        c = criteres(s * 1e4, tem * 1e4, 0.0)
        p_dsr = dsr(s, N_ESSAIS)
        res[code] = dict(c, dsr=p_dsr, sharpe_an=sharpe(s), stress=sharpe(s2), nom=nom)
        pr(f"  --- {nom} : {c['n']} jours | net {c['moyenne']:+.2f} pb/j (t {c['t']:+.2f}) | 2016-2020 t {c['t1']:+.2f} | 2021-2026 t {c['t2']:+.2f}")
        pr(f"      temoin autres mois {c['temoin']:+.2f} pb/j, Welch {c['welch']:+.2f} | sans les 3 meilleurs jours {c['sans3']:+.2f} | "
           f"Sharpe net {sharpe(s):.2f} (stress 2 ticks {sharpe(s2):.2f}) | Sharpe deflate ({N_ESSAIS} essais) {p_dsr:.2f}")
    pr(f"      temoin (signal autres mois, actions et matieres premieres) : Sharpe {sharpe(tem):+.2f}")
    vv = res["V"]
    echecs = [k for k, ok in vv["tests"].items() if not ok] + ([] if vv["dsr"] >= SEUIL_DSR else [f"Sharpe deflate >= {SEUIL_DSR:.2f}"])
    pr("\nVERDICT (V) : " + ("RETENUE" if not echecs else "ECHOUE (" + " ; ".join(echecs) + ")"))
    pr(f"Calcul en {(datetime.now() - t0).total_seconds():.0f} s.")
    sortie = sortie or os.path.join(PY_DIR, "recherche", "resultats_saisonnalite.txt")
    with open(sortie, "w", encoding="utf-8") as fh:
        fh.write("\n".join(L) + "\n")
    exporter("saisonnalite", dict(
        titre="Saisonnalite des rendements, meme mois calendaire (huit travaux)",
        sous="Keloharju, Linnainmaa & Nyberg (JF 2016, JFE 2021), Baltussen, Swinkels & van Vliet (JFE 2021), Heston & Sadka (JFE "
             "2008), Baltas (2016), Hofmann & Keiber (2021), McLean & Pontiff (JF 2016), Jacobs & Mueller (JFE 2020). V = classement "
             "par le rendement moyen du meme mois sur 20 ans, indices actions et matieres premieres ; temoin = signal des autres "
             "mois. Protocole : nexus/perso/saisonnalite.py.",
        lignes=[dict(code=k, nom=x["nom"], n=x["n"], moyenne=x["moyenne"], t=x["t"], t1=x["t1"], t2=x["t2"], temoin=x["temoin"],
                     welch=x["welch"], sans3=x["sans3"], dsr=x["dsr"], sharpe_an=x["sharpe_an"], stress=x["stress"])
                for k, x in res.items()],
        temoin_sharpe=sharpe(tem), echecs=echecs, retenue=not echecs))
    log("\n".join(L))
    return dict(etape2=res, echecs=echecs)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--sortie", default=None)
    a = ap.parse_args(argv)
    etude(a.sortie)


if __name__ == "__main__":
    main()
