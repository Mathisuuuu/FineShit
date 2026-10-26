"""Fin de mois : ventes forcees (« dash for cash ») et reequilibrage des portefeuilles 60/40, sur ES (NQ, YM en replique).

    python -m nexus.perso.fin_de_mois [--sortie recherche/resultats_fin_de_mois.txt]

PROTOCOLE ECRIT LE 2026-10-19, AVANT TOUT CALCUL DEDIE (methode : memoire « methode-strategie-papiers »).
Lignee « tour de mois » de la demande du 2026-10-11 (suivre les mises a jour qui gardent l effet en vie).
Deja vu chez nous : YM 1 des 60 strategies (achat 14:00 -> 16:00 le dernier jour du mois, echec, famille calendrier
eliminee) ; rien d autre sur la fin de mois des indices. Test donc aveugle pour tout ce qui suit.

Sources (texte complet lu = [T], resume et introduction seulement = [R])
 [AR87]  [R] R. Ariel (Baruch), « A monthly effect in stock returns », JFE 18, 1987 : la hausse du marche se concentre
         du dernier jour du mois aux 9 premiers jours du mois suivant.
 [LS88]  [R] J. Lakonishok (Illinois), S. Smidt (Cornell), « Are seasonal anomalies real? A ninety-year perspective »,
         RFS 1, 1988 : rendements eleves du dernier jour du mois aux 3 premiers jours (T a T+3).
 [OG90]  [R] J. Ogden, JF 45, 1990 : explication par le reinvestissement des paiements (salaires, dividendes, interets)
         au tournant du mois.
 [MW00]  [R] E. Maberly (Canterbury), D. Waggoner (Fed d Atlanta), WP 2000-11 : CONTRE-PAPIER, l effet T..T+3 disparait
         des futures S&P 500 apres 1990 (et du comptant) ; ces regularites dependent de la microstructure et changent.
         (Texte complet bloque au telechargement ; resume et introduction lus.)
 [MX08]  [R] J. McConnell, W. Xu (Purdue), « Equity returns at the turn of the month », FAJ 64, 2008 : 1926-2005, toute la
         prime de marche est gagnee de T-1 a T+3 ; 31 pays sur 35 ; pas explique par le volume ni les flux.
 [ERSV20] [T] E. Etula (Goldman), K. Rinne, M. Suominen (Aalto), L. Vaittinen, « Dash for Cash: Monthly Market Impact
         of Institutional Liquidity Needs », RFS 33, 2020 (1995-2013) : pensions et dividendes payes en T et T+1 ; avec le
         reglement-livraison a 3 jours, un institutionnel qui doit payer le matin de T vend au plus tard a la cloture de
         T-4 : rendements FAIBLES de T-8 a T-4 (-37 pb anormaux par mois), ELEVES de T-3 a T-1 (+25 pb) puis de T a T+3,
         faibles de T+4 a T+8 ; correlation (T-8..T-4, T-3..T-1) = -0,38 sur le S&P 500 ; effet 2,5 fois plus fort quand
         T est un vendredi ; CAUSALITE par le reglement : le passage de 3 a 2 jours en Europe (octobre 2014) deplace le
         retournement d un jour (diff-in-diff, t -3,7). Les ventes ANcerno sont maximales en T-4.
 [GRA24] [T] G. Graziani (Bocconi), « Time Series Reversal: An End-of-the-Month Perspective », 2024 (SSRN 4349253) :
         le rendement du S&P 500 du 4e vendredi a la fin du mois predit NEGATIVEMENT le mois suivant (-0,35, t -3,8,
         1975-2019 ; Sharpe 0,40 de la regle simple) ; les fonds de pension (ANcerno) vendent de t-4 a t-2.
 [HMM26] [T] C. Harvey (Duke), M. Mazzoleni (Capital Group), A. Melone (Ohio State), « The Unintended Consequences of
         Rebalancing », version du 14/01/2026 (NBER w33554, mars 2025 ; SSRN 5122748), 1997-09 -> 2023-03 : un portefeuille
         60/40 S&P 500 / note a 10 ans simule ; signal Calendar = ecart du poids actions a 60 % depuis le dernier
         reequilibrage (dernier jour ouvre du mois), signal Threshold = moyenne des ecarts pour des seuils de 0 a 2,5 % ;
         coefficient de Calendar x derniere semaine (5 derniers jours) sur le rendement du LENDEMAIN : -0,27 sur ES seul,
         -0,30 sur ES - note a 10 ans (t -3,7) ; nul hors de la derniere semaine ; positif (retournement) en semaines 1
         et 3 ; plus fort en fin de trimestre et apres 2006 ; nul de 1961 a 1997 ; « encore plus fort » jusqu en 2025.
         Strategie du papier : poids = moyenne de (-Threshold / 1,5 %) et du Calendar modifie (signe de -Calendar les
         5 derniers jours ; signe de Calendar(T-4) le premier jour ouvre du mois ; 0 sinon) applique a ES - note :
         Sharpe 1,11 brut (environ 1 net), asymetrie 5,2, porte en partie par 2008 et mars 2020 (0,90 sans).
 Source secondaire : Quantseeker (2024, ETF) : l effet T..T+3 a « largement disparu » sur la derniere decennie,
 la fenetre T-3..T+3 « a beaucoup baisse ».
Lecture commune : l effet tour de mois n est pas une constante (MW00, Quantseeker) ; sa cause est le cycle des
paiements et la date limite de vente imposee par le reglement-livraison (ERSV20), modulee par le sens du
reequilibrage des portefeuilles diversifies (HMM26 : les pensions vendent surtout des actions quand les actions ont
surperforme). Deux predictions DATEES et refutables en decoulent pour 2016-2026, ou le reglement americain est passe de
3 jours a 2 (5 septembre 2017) puis a 1 jour (28 mai 2024) : la date limite de vente D recule de T-4 a T-3 puis T-2,
et le creux / rebond doit suivre ; l effet conditionnel de HMM26 doit survivre hors de leur echantillon (apres le
17/03/2023).

Donnees : futures Databento ES (NQ, YM en replique), prix a 16:00 ET (13:00 les demi-seances) pour les rendements
quotidiens, au prix ajuste des roulements (variation de points / prix reel de la veille : un roulement ne cree pas de
saut) ; jambe obligataire = IEF (iShares 7-10 ans, cloture ajustee des coupons, Yahoo) moins le taux du T-bill a 13
semaines (^IRX / 252) ; ZN=F de Yahoo n est pas raboute proprement, donc non utilise. Momentum de controle (HMM26) :
rendements du S&P 500 comptant (^GSPC) avant 2016 pour l historique, ES ensuite. Calendrier : seances NYSE ; T = dernier
jour ouvre du mois ; regime de reglement s = 3 avant le 05/09/2017, 2 jusqu au 27/05/2024, 1 ensuite, determine par
la date de la vente D = T-(s+1).

ETAPE 1 - l anomalie et son mecanisme, rendements cloture -> cloture de ES, par periode 2016-2020 / 2021-2026 :
  A1 (ERSV20, fenetres decalees selon le reglement) : vente forcee D-4..D, retournement D+1..T-1, achat T..T+3,
     retournement negatif T+4..T+8 ; moyenne quotidienne de chaque fenetre moins celle des autres jours (Welch) ;
     correlation et pente (Newey-West) entre la somme des rendements de la fenetre de vente et celle du retournement,
     predites < 0 ; meme mesure quand T est un vendredi.
  A2 : memes fenetres a l horaire FIXE du papier (T-8..T-4 / T-3..T-1) apres le 05/09/2017 : si le mecanisme est le
     reglement, l horaire decale doit mieux marcher que l horaire fixe (comparaison descriptive).
  A3 (HMM26) : regression du rendement du lendemain (ES seul, puis ES - IEF) sur Calendar, Calendar x 5 derniers jours,
     5 derniers jours, Threshold, Momentum (moyenne des signes des rendements cumules sur 11..20 jours et sur
     21, 42, 63, 126, 252 jours), rendement du jour ; ecarts-types robustes (HC1) ; sur 2016-2026, chaque periode, et
     HORS ECHANTILLON du papier (18/03/2023 -> fin).
ETAPE 2 - strategies (regles figees, nettes de couts : 1 tick + 2,50 $ par cote et par contrat, stress 2 ticks) ;
  signal a la cloture de 16:00, ordre a 16:10 ET (les futures traitent jusqu a 17:00), position tenue jusqu au lendemain
  16:10 ; taille = 1 fois le capital en notionnel (aucun levier) :
  - V  = la partie fin de mois de HMM26 telle que publiee, sur ES seul : poids = signe(-Calendar) chacun des 5 derniers
         jours ouvres du mois, signe(Calendar en T-4) le premier jour ouvre du mois suivant, 0 sinon ;
  - R0 = anomalie brute de ERSV20 : achat de ES a la date limite de vente D (16:10) jusqu a T+3 (16:10), fenetres
         decalees selon le reglement (note 13 du papier : « la fin de T-4 est le meilleur moment pour acheter ») ;
  - R1 = strategie exacte de HMM26 : moyenne de (-Threshold / 1,5 %) et du Calendar modifie, appliquee a ES - IEF ;
         couts ES ci-dessus, IEF 1 pb par cote ;
  - temoin de V = la meme regle decalee de 10 seances (5 jours finissant en T-10, puis T-9) : la deuxieme semaine, ou
    HMM26 (table D.12) ne trouvent pas d effet ;
  - replique de V sur NQ et YM.
  Criteres (fixes avant le calcul) sur les rendements quotidiens de V les jours en position : t >= 3 ; meme signe et
  t >= 1,5 sur 2016-2020 et 2021-2026 ; Welch >= 2 contre le temoin ; gain moyen net > 0 ; net > 0 sans les 3
  meilleurs jours ; ET Sharpe deflate >= 0,95 pour 372 essais (369 du programme entier au 2026-10-19 + V, R0, R1).
  Rapportes sans etre des criteres : hors echantillon du papier (apres le 17/03/2023), apres publication (03/2025),
  couts doubles, chaque regime de reglement.
Compatibilite prop firm : position de nuit (16:10 -> 16:10) : NON compatible telle quelle avec une prop firm intraday.
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
from .or_anomalies import instants
from .soixante import COMMISSION, COUTS, ET, PY_DIR, criteres, exporter, jours_ouvres_us, marche, prix_a, tstat

COUPURE = pd.Timestamp("2021-01-01")
T2 = pd.Timestamp("2017-09-05")          # reglement-livraison americain a 2 jours (SEC, regle 15c6-1)
T1 = pd.Timestamp("2024-05-28")          # puis a 1 jour
FIN_HMM = pd.Timestamp("2023-03-17")     # fin de l echantillon de HMM26
PUB_HMM = pd.Timestamp("2025-03-01")     # NBER w33554
N_ESSAIS, SEUIL_DSR = 372, 0.95
CIBLE, SEUILS = 0.60, np.round(np.arange(0.0, 0.02501, 0.001), 4)
CACHE_Y = os.path.join(PY_DIR, ".cache", "yahoo")


# =============================================================================
#  Donnees
# =============================================================================
def yahoo(sym: str, ajuste: bool = False) -> pd.Series:
    with open(os.path.join(CACHE_Y, f"{sym}.json"), encoding="utf-8") as fh:
        r = json.load(fh)["chart"]["result"][0]
    v = r["indicators"]["adjclose"][0]["adjclose"] if ajuste else r["indicators"]["quote"][0]["close"]
    s = pd.Series(v, index=pd.to_datetime(r["timestamp"], unit="s").normalize(), dtype=float)
    return s[~s.index.duplicated(keep="last")].dropna()


def prix_jour(m, jours: pd.DatetimeIndex, hh: int, mm: int) -> pd.DataFrame:
    """Prix ajuste et prix reel a hh:mm ET (13:mm les demi-seances, quand hh:mm n a pas de barre)."""
    pa, ia = prix_a(m, instants(jours, hh, mm, ET))
    pb, ib = prix_a(m, instants(jours, 13, mm, ET))
    manque = ~np.isfinite(pa) | (ia < 0)
    p = np.where(manque, pb, pa)
    i = np.where(manque, ib, ia)
    off = np.where(i >= 0, m.offset[np.clip(i, 0, None)], np.nan) if hasattr(m, "offset") else 0.0
    return pd.DataFrame({"adj": p, "reel": p - off}, index=jours)


def rendements(px: pd.DataFrame) -> pd.Series:
    """Rendement simple d un instant a l autre : variation de points ajustes / prix reel precedent."""
    return (px["adj"].diff() / px["reel"].shift(1)).rename("r")


def obligations(jours: pd.DatetimeIndex) -> pd.Series:
    """Rendement excedentaire quotidien d IEF (coupons compris) moins le T-bill, aligne sur nos seances."""
    ief = yahoo("IEF", ajuste=True).reindex(jours).ffill()
    rf = (yahoo("IRX") / 100 / 252).reindex(jours).ffill()
    return (ief.pct_change() - rf.shift(1)).rename("rb")


# =============================================================================
#  Calendrier : fin de mois et reglement-livraison
# =============================================================================
def calendrier(jours: pd.DatetimeIndex) -> pd.DataFrame:
    """Pour chaque seance : rang k par rapport a la fin du mois suivante (k <= 0, T = 0) et a la precedente (k > 0),
    regime de reglement s de la fin de mois a venir et date limite de vente D = T-(s+1) (en rangs)."""
    j = pd.DatetimeIndex(jours)
    mois = j.to_period("M")
    pos = np.arange(len(j))
    fin = pd.Series(pos, index=j).groupby(mois).transform("max").to_numpy()      # rang de T du mois de la seance
    k_av = pos - fin                                                              # <= 0
    fin_prec = pd.Series(np.where(pos == fin, pos, np.nan), index=j).ffill().shift(1).to_numpy()
    k_ap = pos - fin_prec                                                         # > 0 apres la fin precedente
    s = np.full(len(j), 3)
    for i in range(len(j)):
        for cand in (3, 2, 1):
            d = fin[i] - (cand + 1)
            if d < 0:
                break
            dd = j[d]
            if (cand == 3 and dd < T2) or (cand == 2 and T2 <= dd < T1) or (cand == 1 and dd >= T1):
                s[i] = cand
                break
    est_fin = pos == fin
    return pd.DataFrame(dict(k_av=k_av, k_ap=k_ap, s=s, fin=est_fin, vendredi_T=j[fin].dayofweek == 4), index=j)


def fenetres(cal: pd.DataFrame, fixe: bool = False) -> pd.Series:
    """Etiquette de chaque seance (ERSV20) : vente D-4..D, retour D+1..T-1, achat T..T+3, retour_neg T+4..T+8."""
    s = np.full(len(cal), 3) if fixe else cal["s"].to_numpy()
    k, kp = cal["k_av"].to_numpy(), cal["k_ap"].to_numpy()
    d = -(s + 1)
    lab = np.full(len(cal), "autre", dtype=object)
    lab[(k >= d - 4) & (k <= d)] = "vente"
    lab[(k > d) & (k <= -1)] = "retour"
    lab[k == 0] = "achat"
    lab[(kp >= 1) & (kp <= 3)] = "achat"
    lab[(kp >= 4) & (kp <= 8)] = "retour_neg"
    return pd.Series(lab, index=cal.index)


# =============================================================================
#  Signaux de reequilibrage (HMM26, annexe B)
# =============================================================================
def deriver(w: float, re: float, rb: float) -> float:
    return w * (1 + re) / (w * (1 + re) + (1 - w) * (1 + rb))


def signaux(re: pd.Series, rb: pd.Series, fin_mois: pd.Series) -> pd.DataFrame:
    """Calendar et Threshold a la cloture de chaque seance (ecart du poids actions a 60 %, avant reequilibrage).
    Calendar : reequilibre le dernier jour ouvre du mois ; Threshold(delta) : reequilibre quand |ecart| >= delta, moyenne
    sur delta = 0 ; 0,1 ; ... ; 2,5 %."""
    r1, r2, fm = re.fillna(0).to_numpy(), rb.fillna(0).to_numpy(), fin_mois.to_numpy()
    n = len(r1)
    cal = np.full(n, np.nan)
    w = CIBLE
    for i in range(n):
        w = deriver(w, r1[i], r2[i])
        cal[i] = w - CIBLE
        if fm[i]:
            w = CIBLE
    thr = np.zeros(n)
    for dl in SEUILS:
        w = CIBLE
        for i in range(n):
            w = deriver(w, r1[i], r2[i])
            thr[i] += w - CIBLE
            if abs(w - CIBLE) >= dl - 1e-12:
                w = CIBLE
    thr /= len(SEUILS)
    return pd.DataFrame(dict(calendar=cal, threshold=thr), index=re.index)


def momentum(rx: pd.Series) -> pd.Series:
    """HMM26 : moyenne des signes des rendements cumules (11..20 j) et (21, 42, 63, 126, 252 j), puis moyenne des deux."""
    lr = np.log1p(rx.fillna(0))
    cum = lr.cumsum()
    moy = sum(np.sign(cum - cum.shift(h)) for h in range(11, 21)) / 10
    lent = sum(np.sign(cum - cum.shift(h)) for h in (21, 42, 63, 126, 252)) / 5
    return ((moy + lent) / 2).rename("momentum")


def calendar_modifie(sig: pd.DataFrame, cal: pd.DataFrame, decalage: int = 0) -> pd.Series:
    """HMM26 section 4 : signe(-Calendar) les 5 derniers jours du mois, signe(Calendar en T-4) le premier jour du mois
    suivant, 0 sinon. decalage = -10 : temoin (meme regle 10 seances plus tot)."""
    k = cal["k_av"].to_numpy() - decalage
    c = sig["calendar"].to_numpy()
    w = np.zeros(len(c))
    sem4 = (k >= -4) & (k <= 0)
    w[sem4] = np.sign(-c[sem4])
    for e in np.flatnonzero(k == 0):                        # fin de la fenetre (T, ou T-10 pour le temoin)
        if e + 1 < len(c) and e - 4 >= 0:
            w[e + 1] = np.sign(c[e - 4])                    # jour suivant : signe du Calendar en fin - 4
    return pd.Series(w, index=sig.index)


# =============================================================================
#  Statistiques
# =============================================================================
def ols_hc(y: np.ndarray, X: np.ndarray, noms: list[str], hac: int = 0) -> dict:
    import statsmodels.api as sm
    ok = np.isfinite(y) & np.isfinite(X).all(axis=1)
    m = sm.OLS(y[ok], sm.add_constant(X[ok])).fit(cov_type="HAC" if hac else "HC1", **({"cov_kwds": {"maxlags": hac}} if hac else {}))
    return dict(n=int(ok.sum()), **{n_: (float(m.params[i + 1]), float(m.tvalues[i + 1])) for i, n_ in enumerate(noms)})


def welch(a: pd.Series, b: pd.Series) -> float:
    a, b = a.dropna(), b.dropna()
    se = math.sqrt(a.var(ddof=1) / len(a) + b.var(ddof=1) / len(b))
    return float((a.mean() - b.mean()) / se) if se > 0 else math.nan


def strategie(poids: pd.Series, r_exec: pd.Series, cout_cote: pd.Series) -> tuple[pd.Series, pd.Series, pd.Series]:
    """Rendement net du lendemain : poids decide a la seance t (ordre a 16:10) applique a r(16:10 t -> 16:10 t+1),
    moins les couts de la variation de poids (fraction du notionnel echange), imputes au lendemain de l ordre.
    -> (net, brut, cout)."""
    w = poids.fillna(0.0)
    brut = w.shift(1) * r_exec
    cout = ((w - w.shift(1).fillna(0.0)).abs() * cout_cote).shift(1).fillna(0.0)
    return (brut.fillna(0.0) - cout).rename("net"), brut.rename("brut"), cout.rename("cout")


def portefeuille_vbt(poids: pd.Series, r_exec: pd.Series, cout_cote: pd.Series):
    """Meme strategie dans vectorbt : indice de prix synthetique (rendements vrais), ordres en pourcentage cible."""
    import vectorbt as vbt
    idx = (1 + r_exec.fillna(0.0)).cumprod()
    return vbt.Portfolio.from_orders(idx, size=poids.fillna(0.0), size_type="targetpercent", fees=cout_cote.fillna(0.0),
                                     direction="both", init_cash=1.0, freq="1D")


def resume_strat(nom: str, net: pd.Series, actif: pd.Series, pr) -> dict:
    x = net[actif]
    a = (1 + net).groupby(net.index.year).prod() - 1
    sh = float(net.mean() / net.std(ddof=1) * math.sqrt(252)) if net.std() > 0 else math.nan
    d = dict(nom=nom, jours=int(actif.sum()), moyenne_pb=x.mean() * 1e4, t=tstat(x), sharpe=sh,
             t1=tstat(x[x.index < COUPURE]), t2=tstat(x[x.index >= COUPURE]), dsr=dsr(net, N_ESSAIS),
             sharpe_1=float(net[net.index < COUPURE].mean() / net[net.index < COUPURE].std() * math.sqrt(252)),
             sharpe_2=float(net[net.index >= COUPURE].mean() / net[net.index >= COUPURE].std() * math.sqrt(252)),
             sharpe_oos=float(net[net.index > FIN_HMM].mean() / net[net.index > FIN_HMM].std() * math.sqrt(252)),
             sharpe_pub=float(net[net.index >= PUB_HMM].mean() / net[net.index >= PUB_HMM].std() * math.sqrt(252)),
             total=float((1 + net).prod() - 1), annees=" ".join(f"{y}:{v:+.1%}" for y, v in a.items()))
    pr(f"  {nom:<44} {d['jours']:5d} j | {d['moyenne_pb']:+6.2f} pb/j (t {d['t']:+.2f}) | Sharpe {sh:+.2f} "
       f"[16-20 {d['sharpe_1']:+.2f} | 21-26 {d['sharpe_2']:+.2f} | apres 03/2023 {d['sharpe_oos']:+.2f} | "
       f"apres pub. {d['sharpe_pub']:+.2f}] | total {d['total']:+.1%}")
    return d


# =============================================================================
#  Etude
# =============================================================================
def cout_cote_serie(root: str, reel: pd.Series, ticks: float = 1.0) -> pd.Series:
    tick, pv, _, _ = COUTS[root]
    return (ticks * tick * pv + COMMISSION) / (reel * pv)


def etude(sortie: str | None = None, log=print) -> dict:
    t0 = datetime.now()
    L = []
    pr = L.append
    pr("=" * 118)
    pr(" FIN DE MOIS : VENTES FORCEES (ETULA ET AL. 2020) ET REEQUILIBRAGE 60/40 (HARVEY, MAZZOLENI & MELONE 2026) SUR ES")
    pr("=" * 118)
    pr("Protocole et sources : en-tete de nexus/perso/fin_de_mois.py (ecrit avant le calcul). Rendements en pb par jour.")
    m = marche("ES")
    jours = jours_ouvres_us(m)
    jours = jours[(jours >= "2016-01-04") & (jours <= "2026-08-28")]
    c16, c1610 = prix_jour(m, jours, 16, 0), prix_jour(m, jours, 16, 10)
    re, rx_exec = rendements(c16), rendements(c1610)
    rb = obligations(jours)
    cal = calendrier(jours)
    log(f"  donnees : {len(jours)} seances, rendements manquants {int(re.isna().sum())}")

    # ---------------------------------------------------------------- ETAPE 1 - A1 / A2
    pr("")
    pr("ETAPE 1 - A1 : fenetres de Etula et al., decalees selon le reglement (T+3 -> T+2 le 05/09/2017 -> T+1 le 28/05/2024)")
    res = {}
    for fixe, titre in ((False, "decalees"), (True, "fixes T+3")):
        lab = fenetres(cal, fixe)
        if fixe:
            sel = jours >= T2
            pr("")
            pr("A2 : memes fenetres a l horaire FIXE du papier (T-8..T-4, T-3..T-1), apres le 05/09/2017 seulement")
        else:
            sel = np.ones(len(jours), bool)
        r_, l_ = re[sel], lab[sel]
        autres = r_[l_ == "autre"]
        for f, signe in (("vente", -1), ("retour", +1), ("achat", +1), ("retour_neg", -1)):
            x = r_[l_ == f]
            p1, p2 = x[x.index < COUPURE], x[x.index >= COUPURE]
            o1, o2 = autres[autres.index < COUPURE], autres[autres.index >= COUPURE]
            pr(f"  {titre:<10} {f:<11} (attendu {'>' if signe > 0 else '<'} 0) : {x.mean() * 1e4:+6.2f} pb/j contre "
               f"{autres.mean() * 1e4:+5.2f} (Welch {welch(x, autres):+.2f}) | 2016-2020 {p1.mean() * 1e4:+6.2f} "
               f"(W {welch(p1, o1):+.2f}) | 2021-2026 {p2.mean() * 1e4:+6.2f} (W {welch(p2, o2):+.2f}) | n {len(x)}")
            res[(titre, f)] = dict(moy=x.mean() * 1e4, welch=welch(x, autres), w1=welch(p1, o1), w2=welch(p2, o2))
        # correlation vente -> retour, par mois
        mois = r_.index.to_period("M")
        v = r_[l_ == "vente"].groupby(mois[l_ == "vente"]).sum()
        rt = r_[l_ == "retour"].groupby(mois[l_ == "retour"]).sum()
        dfm = pd.concat([v.rename("v"), rt.rename("r")], axis=1).dropna()
        o = ols_hc(dfm["r"].to_numpy(), dfm[["v"]].to_numpy(), ["v"], hac=3)
        vend = cal["vendredi_T"].groupby(cal.index.to_period("M")).last().reindex(dfm.index).fillna(False).astype(bool)
        pr(f"  {titre:<10} correlation (vente, retour) par mois : {dfm['v'].corr(dfm['r']):+.2f} (pente {o['v'][0]:+.3f}, "
           f"t NW {o['v'][1]:+.2f}, {o['n']} mois ; ERSV20 : -0,38) ; T vendredi : {dfm[vend]['v'].corr(dfm[vend]['r']):+.2f} "
           f"({int(vend.sum())} mois), autres : {dfm[~vend]['v'].corr(dfm[~vend]['r']):+.2f}")
        res[(titre, "corr")] = dict(corr=dfm["v"].corr(dfm["r"]), t=o["v"][1])
        if not fixe:
            for nom_s, s_ in ((3, "T+3 (2016 -> 09/2017)"), (2, "T+2 (09/2017 -> 05/2024)"), (1, "T+1 (depuis 05/2024)")):
                q = cal["s"] == nom_s
                lv, lr = r_[(l_ == "vente") & q], r_[(l_ == "retour") & q]
                pr(f"    regime {s_:<24} : vente {lv.mean() * 1e4:+6.2f} pb/j (n {len(lv)}), retour {lr.mean() * 1e4:+6.2f} "
                   f"pb/j (n {len(lr)})")

    # ---------------------------------------------------------------- ETAPE 1 - A3 (HMM26)
    pr("")
    pr("ETAPE 1 - A3 : regressions de HMM26 sur le rendement du LENDEMAIN (coefficient x 1 ; HC1)")
    gspc = yahoo("GSPC")
    ief_long = yahoo("IEF", ajuste=True)
    rf_long = yahoo("IRX") / 100 / 252
    hist = pd.DataFrame({"re": gspc.pct_change(), "rb": ief_long.pct_change() - rf_long.reindex(ief_long.index).ffill().shift(1)})
    hist = hist[(hist.index >= "2014-01-03") & (hist.index < jours[0])].dropna()
    rx_long = pd.concat([hist["re"] - hist["rb"], (re - rb)])                    # momentum : historique avant 2016
    mom = momentum(rx_long).reindex(jours)
    sig = signaux(re, rb, cal["fin"])
    w4 = ((cal["k_av"] >= -4) & (cal["k_av"] <= 0)).astype(float)
    X = pd.DataFrame(dict(calendar=sig["calendar"], cal_w4=sig["calendar"] * w4, w4=w4, threshold=sig["threshold"],
                          momentum=mom, r_jour=re - rb))
    noms = list(X.columns)
    a3 = {}
    for cible, y in (("ES", re.shift(-1)), ("ES - IEF", (re - rb).shift(-1))):
        for per, sel in (("2016-2026", jours >= "2016-03-01"), ("2016-2020", (jours >= "2016-03-01") & (jours < COUPURE)),
                         ("2021-2026", jours >= COUPURE), ("apres 03/2023", jours > FIN_HMM)):
            o = ols_hc(y[sel].to_numpy(), X[sel].to_numpy(), noms)
            a3[(cible, per)] = o
            pr(f"  {cible:<9} {per:<14} n {o['n']:4d} | Calendar x 5 derniers j {o['cal_w4'][0]:+.3f} (t {o['cal_w4'][1]:+.2f}) "
               f"| Calendar {o['calendar'][0]:+.3f} (t {o['calendar'][1]:+.2f}) | Threshold {o['threshold'][0]:+.3f} "
               f"(t {o['threshold'][1]:+.2f}) | Momentum {o['momentum'][0] * 1e4:+.1f} pb (t {o['momentum'][1]:+.2f})")
    pr("  HMM26 (1997-2023) : Calendar x semaine 4 -0,27 (ES) / -0,30 (ES - note), t environ -3,5 ; Threshold -0,33 / -0,41.")

    # ---------------------------------------------------------------- ETAPE 2
    pr("")
    pr("ETAPE 2 - strategies nettes (ordre 16:10, 1 fois le capital, 1 tick + 2,50 $ par cote)")
    cc = cout_cote_serie("ES", c1610["reel"])
    cc2 = cout_cote_serie("ES", c1610["reel"], ticks=2.0)
    wV = calendar_modifie(sig, cal)
    wT = calendar_modifie(sig, cal, decalage=-10)
    kD = -(cal["s"] + 1)
    wR0 = pd.Series(((cal["k_av"] >= kD) & (cal["k_av"] <= -1)) | (cal["k_av"] == 0) | ((cal["k_ap"] >= 1) & (cal["k_ap"] <= 2)),
                    index=jours).astype(float)                                   # position tenue de D (16:10) a T+3 (16:10)
    netV, brutV, coutV = strategie(wV, rx_exec, cc)
    netV2, _, _ = strategie(wV, rx_exec, cc2)
    netT, brutT, _ = strategie(wT, rx_exec, cc)
    netR0, _, _ = strategie(wR0, rx_exec, cc)
    actV, actT, actR0 = wV.shift(1).fillna(0) != 0, wT.shift(1).fillna(0) != 0, wR0.shift(1).fillna(0) != 0
    # R1 : strategie exacte de HMM26 sur ES - IEF (IEF : cloture -> cloture, 1 pb par cote)
    wR1 = ((-sig["threshold"] / 0.015) + wV) / 2
    rb_exec = rb
    brut_R1 = wR1.shift(1) * (rx_exec - rb_exec)
    cout_R1 = (wR1 - wR1.shift(1).fillna(0)).abs() * (cc + 1e-4)
    netR1 = (brut_R1.fillna(0) - cout_R1.shift(1).fillna(0)).rename("net")
    actR1 = wR1.shift(1).fillna(0) != 0
    strat = {}
    strat["V"] = resume_strat("V   HMM26 fin de mois, ES seul", netV, actV, pr)
    strat["V2"] = resume_strat("V   couts 2 ticks", netV2, actV, pr)
    strat["T"] = resume_strat("temoin de V (meme regle, 10 seances plus tot)", netT, actT, pr)
    strat["R0"] = resume_strat("R0  ERSV20 : achat de D a T+3 (decale)", netR0, actR0, pr)
    strat["R1"] = resume_strat("R1  HMM26 exacte (Threshold + Calendar, ES - IEF)", netR1, actR1, pr)
    pf = portefeuille_vbt(wV, rx_exec, cc)
    st = pf.stats()
    pr(f"  controle vectorbt de V (Portfolio.from_orders) : rendement total {st['Total Return [%]']:+.1f} %, "
       f"Sharpe {st['Sharpe Ratio']:+.2f}, perte max {st['Max Drawdown [%]']:.1f} %, {int(st['Total Trades'])} trades")
    for root in ("NQ", "YM"):                     # meme signal (S&P 500 / 10 ans : les flux des 60/40), autre contrat
        p1610 = prix_jour(marche(root), jours, 16, 10)
        n_, _, _ = strategie(wV, rendements(p1610), cout_cote_serie(root, p1610["reel"]))
        strat[root] = resume_strat(f"replique de V sur {root}", n_, actV, pr)

    # ---------------------------------------------------------------- criteres
    pr("")
    xV = (brutV[actV]).rename("V")
    xT = (brutT[actT]).rename("T")
    cout_moy = float(coutV.sum() / max(1, int(actV.sum())) * 1e4)          # couts d entree ET de sortie par jour en position
    c = criteres(xV * 1e4, xT * 1e4, cout_moy)
    d = dsr(netV, N_ESSAIS)
    pr(f"CRITERES (V, {c['n']} jours en position ; cout moyen {cout_moy:.2f} pb par jour) : moyenne brute {c['moyenne']:+.2f} pb "
       f"(t {c['t']:+.2f}) | 2016-2020 {c['m1']:+.2f} (t {c['t1']:+.2f}) | 2021-2026 {c['m2']:+.2f} (t {c['t2']:+.2f}) | "
       f"temoin {c['temoin']:+.2f} (Welch {c['welch']:+.2f}) | net {c['net']:+.2f} | net sans 3 meilleurs {c['sans3']:+.2f}")
    for k_, v_ in c["tests"].items():
        pr(f"  [{'x' if v_ else ' '}] {k_}")
    pr(f"  [{'x' if d >= SEUIL_DSR else ' '}] Sharpe deflate >= {SEUIL_DSR} pour {N_ESSAIS} essais : {d:.2f}")
    passe = c["passe"] and d >= SEUIL_DSR
    pr(f"VERDICT : {'RETENUE' if passe else 'REJETEE'}")
    texte = "\n".join(L)
    sortie = sortie or os.path.join(PY_DIR, "recherche", "resultats_fin_de_mois.txt")
    with open(sortie, "w", encoding="utf-8") as fh:
        fh.write(texte + f"\n(calcule en {(datetime.now() - t0).seconds} s le {datetime.now():%Y-%m-%d %H:%M})\n")
    echecs = [k_ for k_, v_ in c["tests"].items() if not v_] + ([] if d >= SEUIL_DSR else [f"Sharpe deflate >= {SEUIL_DSR}"])
    lignes = [dict(code=k_, nom=v_["nom"].strip(), n=v_["jours"], moyenne=v_["moyenne_pb"], t=v_["t"], t1=v_["t1"], t2=v_["t2"],
                   temoin=c["temoin"] if k_ == "V" else None, welch=c["welch"] if k_ == "V" else None,
                   sharpe_an=v_["sharpe"], dsr=v_["dsr"]) for k_, v_ in strat.items()]
    exporter("fin_de_mois", dict(
        titre="Fin de mois : ventes forcees (Etula et al. 2020) et reequilibrage 60/40 (Harvey, Mazzoleni & Melone 2026)",
        sous=f"Lignee tour de mois (Ariel 1987, Lakonishok-Smidt 1988 -> Maberly-Waggoner 2000 -> McConnell-Xu 2008 -> "
             f"Etula et al. 2020 -> Graziani 2024 -> HMM 2026). Net en pb par jour en position ; ES 2016-2026 ; "
             f"{N_ESSAIS} essais.", lignes=lignes, echecs=echecs, retenue=passe, criteres=c, dsr=d, n_essais=N_ESSAIS))
    log(texte)
    return dict(criteres=c, dsr=d, passe=passe, strategies=strat, a1=res, a3=a3)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--sortie")
    a = ap.parse_args(argv)
    etude(a.sortie)


if __name__ == "__main__":
    main()
