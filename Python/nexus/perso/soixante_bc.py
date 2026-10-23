"""60 strategies intraday (vue d ensemble du 9 octobre 2026) - ETAPE 2 : anomalies brutes des niveaux B et C.

    python -m nexus.perso.soixante_bc [--sortie resultats_60_niveaux_BC.txt]

Meme methode que l etape 1 (nexus.perso.soixante) : anomalie BRUTE (sans regles, stop ni taille), criteres fixes avant
le test, et test PAR FAMILLES : l actif le mieux place d abord ; s il echoue, la famille entiere est eliminee.
Les onglets par actif n ont pas ete fournis : chaque definition est MA lecture du papier cite, au plus simple (signe du
signal, sans seuil quand c est possible ; seuil de 2 sigma quand la vue d ensemble parle de choc), avec un temoin.

Calendriers : nexus.perso.calendriers (sources officielles, voir chaque fichier). Les heures sont celles de la place
(base IANA). Le DAX (Dukascopy) est encore en telechargement : DAX 1 a 5 et 6E 1 attendent.
"""
from __future__ import annotations

import argparse
import os
from datetime import date, datetime, timedelta

import holidays
import numpy as np
import pandas as pd

from . import calendriers as K
from .or_anomalies import jours_fomc
from .soixante import ET, FRANCFORT, PY_DIR, _rv20, contrats, cout_bp, criteres, exporter, jours_ouvres_us, ligne_json, \
    marche, prix_a, r_fenetre, tstat
from .suite_s import us_holiday

LONDRES, TOKYO, SYDNEY, PEKIN = K.LONDRES, K.TOKYO, K.SYDNEY, K.PEKIN
FIN_DONNEES = pd.Timestamp("2026-08-28")
CHGT_IMBALANCE = pd.Timestamp("2019-01-01")          # desequilibres de cloture NYSE : 15:45 -> 15:50 ET (vue d ensemble)
QUOTIDIENNES_SPY = pd.Timestamp("2022-11-15")        # echeances SPY du mardi et du jeudi


# =============================================================================
#  Outils
# =============================================================================
def _inst(jours, minute, tz: str) -> np.ndarray:
    """Instants UTC (ns) : jour local + `minute` minutes (scalaire ou une par jour ; negative = la veille)."""
    jours = pd.DatetimeIndex(jours)
    minute = np.broadcast_to(np.asarray(minute, dtype=np.int64), (len(jours),))
    loc = jours + pd.to_timedelta(minute, unit="m")
    return loc.tz_localize(tz, nonexistent="shift_forward", ambiguous=False).tz_convert("UTC").tz_localize(None).as_unit("ns").asi8


def _r(m, ta: np.ndarray, tb: np.ndarray) -> np.ndarray:
    """ln(P_B / P_A) entre deux instants ; NaN si un prix manque ou si l echeance change entre A et B."""
    pa, ia = prix_a(m, ta)
    pb, ib = prix_a(m, tb)
    ok = np.isfinite(pa) & np.isfinite(pb) & (ia >= 0) & (ib >= 0) & (pa > 0)
    roll = np.zeros(len(ta), bool)
    cid = contrats(m)
    roll[ok] = cid[ib[ok]] != cid[ia[ok]]
    return np.where(ok & ~roll, np.log(pb / np.where(pa > 0, pa, np.nan)), np.nan)


def _rs(m, jours, a, b, tz) -> pd.Series:
    return pd.Series(_r(m, _inst(jours, a, tz), _inst(jours, b, tz)), index=pd.DatetimeIndex(jours))


def _sigma(r: pd.Series, n: int = 60, mini: int = 40) -> pd.Series:
    """sigma robuste de la meme fenetre sur les n observations precedentes (1,4826 x ecart absolu median)."""
    return (r.abs().rolling(n, min_periods=mini).median() * 1.4826).shift(1)


def _semaine(debut: str = "2016-01-01", fin=FIN_DONNEES) -> pd.DatetimeIndex:
    return pd.bdate_range(debut, fin)


def _premier(par_barre: list[pd.Series]) -> pd.Series:
    """Premiere valeur non manquante de chaque jour (les barres sont donnees dans l ordre chronologique)."""
    s = pd.concat([x.dropna() for x in par_barre])
    s = s.iloc[np.argsort(s.index.values, kind="stable")]
    return s[~s.index.duplicated(keep="first")]


def declencheur(m_sig, m_pos, jours, debuts, tz, k: float = 2.0, barre: int = 15, tenue: int = 60, regle=None):
    """Chocs glissants : barre de `barre` minutes commencant a chaque minute locale de `debuts` (ordre chronologique,
    negative = la veille), sigma de la meme barre sur 60 seances. -> dict de Series (premier declenchement du jour) :
    'haut' (r > k sigma) et 'bas' (r < -k sigma) = rendement de m_pos sur la tenue qui suit la barre, et le signe du choc
    dans 'signe_haut' / 'signe_bas'. `regle(r, sig)` peut remplacer la condition de choc (renvoie un masque)."""
    haut, bas = [], []
    for s in debuts:
        r15 = _rs(m_sig, jours, s, s + barre, tz)
        sig = _sigma(r15)
        apres = _rs(m_pos, jours, s + barre, s + barre + tenue, tz) * 1e4
        if regle is None:
            haut.append(apres[r15 > k * sig])
            bas.append(apres[r15 < -k * sig])
        else:
            msk = regle(r15, sig)
            haut.append((np.sign(r15) * apres)[msk])
    return {"haut": _premier(haut), "bas": _premier(bas) if bas else None}


def troisieme_vendredi(a: int, m: int) -> pd.Timestamp:
    d = date(a, m, 15)
    d += timedelta(days=(4 - d.weekday()) % 7)
    while us_holiday(d):                                    # vendredi saint : echeance avancee au jeudi
        d -= timedelta(days=1)
    return pd.Timestamp(d)


def feries_chine() -> set:
    return set(pd.Timestamp(d) for d in holidays.China(years=range(2015, 2027)).keys())


# =============================================================================
#  Familles : actif le mieux place d abord
# =============================================================================
def es2(es) -> dict:
    """ES 2 - Derive avant les chiffres de 10:00 (Kurov, Sancetta, Strasser & Wolfe 2019 : le prix derive dans le sens de la
    surprise dans les minutes qui precedent certaines publications, dont l ISM et la confiance du Conference Board).
    Signal : r(9:30 -> 9:59) ET ; position 9:59 -> 10:30 dans le sens du signal, les jours d ISM manufacturier, d ISM
    services ou du Conference Board (hors decembre, date variable). Temoin : la meme regle les autres jours."""
    j = jours_ouvres_us(es)
    cb = K.conference_board()
    ev = K.ism().union(K.ism(True)).union(cb[cb.month != 12])
    sig = r_fenetre(es, j, (9, 30), (9, 59), ET)
    x = np.sign(sig) * r_fenetre(es, j, (9, 59), (10, 30), ET) * 1e4
    qual, tem = j.isin(ev), ~j.isin(ev.union(cb))
    return dict(code="ES 2", root="ES", creux=False, sens="signe de la derive 9:30 -> 9:59", serie=x[qual], temoin=x[tem],
                definition="signal r(9:30 -> 9:59 ET), position 9:59 -> 10:30 dans son sens, jours d ISM manufacturier (1er jour "
                           "ouvre), d ISM services (3e) et du Conference Board (dernier mardi, hors decembre) ; temoin : autres jours")


def iwm2(spy, iwm) -> dict:
    """IWM 2 - Retard des petites capitalisations (Lo & MacKinlay 1990 ; Chordia & Swaminathan 2000). Declencheur : barre de
    15 min du SPY (fin entre 9:45 et 15:30 ET) de plus de 2 sigma ; position IWM 30 min dans le sens du choc. Temoin : la
    continuation du SPY LUI-MEME sur les memes 30 min (un vrai retard se voit sur l IWM en plus de l elan commun)."""
    j = jours_ouvres_us(spy)
    debuts = list(range(9 * 60 + 30, 15 * 60 + 16, 15))
    r_iwm, r_spy = [], []
    for s in debuts:
        r15 = _rs(spy, j, s, s + 15, ET)
        choc = r15.abs() > 2 * _sigma(r15)
        sg = np.sign(r15)
        r_iwm.append((sg * _rs(iwm, j, s + 15, s + 45, ET) * 1e4)[choc])
        r_spy.append((sg * _rs(spy, j, s + 15, s + 45, ET) * 1e4)[choc])
    return dict(code="IWM 2", root="IWM", creux=False, sens="sens du choc du SPY", serie=_premier(r_iwm), temoin=_premier(r_spy),
                definition="barre SPY de 15 min > 2 sigma (fin 9:45-15:30 ET) -> IWM 30 min dans le sens du choc ; "
                           "temoin : le SPY lui-meme sur les memes 30 min")


def es3(es) -> dict:
    """ES 3 - Retour apres la pression de cloture (Bogousslavsky & Muravyev 2020 : la pression des ordres de cloture
    deplace le prix, qui revient ensuite). Signal : r(publication des desequilibres NYSE -> 16:00 ET), 15:45 avant 2019,
    15:50 depuis ; position contraire 16:00 -> 16:14. Temoin : la meme structure une heure plus tot (14:45/50 -> 15:00,
    position 15:00 -> 15:14), sans enchere."""
    j = jours_ouvres_us(es)
    imb = np.where(j < CHGT_IMBALANCE, 45, 50)
    sig = _rs(es, j, 15 * 60 + imb, 16 * 60, ET)
    x = -np.sign(sig) * _rs(es, j, 16 * 60, 16 * 60 + 14, ET) * 1e4
    sig0 = _rs(es, j, 14 * 60 + imb, 15 * 60, ET)
    x0 = -np.sign(sig0) * _rs(es, j, 15 * 60, 15 * 60 + 14, ET) * 1e4
    return dict(code="ES 3", root="ES", creux=True, sens="contre les 10-15 dernieres minutes", serie=x, temoin=x0,
                definition="signal r(15:45 avant 2019, 15:50 depuis -> 16:00 ET), position contraire 16:00 -> 16:14 ; "
                           "temoin : meme structure 14:45/50 -> 15:00, position 15:00 -> 15:14")


def ym2(ym, es) -> dict:
    """YM 2 - Ecart YM-ES (Gatev, Goetzmann & Rouwenhorst 2006, paires). Ecart s = r_YM(9:30 -> t) - r_ES(9:30 -> t) aux
    quarts d heure de 10:00 a 15:00 ET ; si |s| > 2 sigma (meme heure, 60 seances) : vente de l actif en avance, achat de
    l autre, 90 min (sortie au plus tard 16:00). Temoin : la meme position les jours SANS ecart > 2 sigma, prise a
    10:00 (convergence ordinaire d un petit ecart)."""
    j = jours_ouvres_us(ym)
    out, ecart10 = [], None
    for t in range(10 * 60, 15 * 60 + 1, 15):
        s = _rs(ym, j, 9 * 60 + 30, t, ET) - _rs(es, j, 9 * 60 + 30, t, ET)
        fin = min(t + 90, 16 * 60)
        conv = -np.sign(s) * (_rs(ym, j, t, fin, ET) - _rs(es, j, t, fin, ET)) * 1e4
        out.append(conv[s.abs() > 2 * _sigma(s)])
        if t == 10 * 60:
            ecart10 = conv
    qual = _premier(out)
    tem = ecart10[~ecart10.index.isin(qual.index)]
    return dict(code="YM 2", root="YM+ES", creux=False, sens="convergence de l ecart", serie=qual, temoin=tem,
                definition="ecart r_YM - r_ES depuis 9:30 > 2 sigma (10:00-15:00 ET) -> paire contraire 90 min ; "
                           "temoin : paire prise a 10:00 les jours sans ecart > 2 sigma")


# =============================================================================
#  Derive apres une banque centrale (DAX 2 en attente des donnees)
# =============================================================================
def e63(e6) -> dict:
    """6E 3 - Apres la conference de la BCE (Valentin 2022 ; contre : Fanta 2026). Signal : reaction a la conference,
    r(C -> C + 60 min) ; position C + 60 -> 17:30 Francfort dans ce sens (C = 14:30, 14:45 depuis le 21/07/2022).
    Temoin : les memes fenetres les autres jeudis."""
    d = K.banque("BCE")
    d = d[d <= FIN_DONNEES]
    _, c = K.heures_bce(d)
    x = np.sign(_rs(e6, d, c, c + 60, FRANCFORT)) * _rs(e6, d, c + 60, 17 * 60 + 30, FRANCFORT) * 1e4
    tj = _semaine()
    tj = tj[(tj.dayofweek == 3) & ~tj.isin(K.banque("BCE", True))]
    _, ct = K.heures_bce(tj)
    t = np.sign(_rs(e6, tj, ct, ct + 60, FRANCFORT)) * _rs(e6, tj, ct + 60, 17 * 60 + 30, FRANCFORT) * 1e4
    return dict(code="6E 3", root="6E", creux=False, sens="sens de la reaction a la conference", serie=x, temoin=t,
                definition="signal r(C -> C+60), position C+60 -> 17:30 Francfort, jours de BCE ; temoin : autres jeudis")


def b63(b6) -> dict:
    """6B 3 - Apres la Banque d Angleterre (Valentin 2022, transpose). Signal r(11:59 -> 12:45) Londres (annonce 12:00) ;
    position 12:45 -> 13:25 dans ce sens. Temoin : les autres jeudis."""
    d = K.banque("BOE")
    d = d[d <= FIN_DONNEES]
    f = lambda jj: np.sign(_rs(b6, jj, 11 * 60 + 59, 12 * 60 + 45, LONDRES)) * _rs(b6, jj, 12 * 60 + 45, 13 * 60 + 25, LONDRES) * 1e4
    tj = _semaine()
    tj = tj[(tj.dayofweek == 3) & ~tj.isin(K.banque("BOE", True))]
    return dict(code="6B 3", root="6B", creux=False, sens="sens de la reaction a 12:00", serie=f(d), temoin=f(tj),
                definition="signal r(11:59 -> 12:45 Londres), position 12:45 -> 13:25, jours de MPC ; temoin : autres jeudis")


def j64(j6) -> dict:
    """6J 4 - Apres la Banque du Japon (Valentin 2022, transpose). T = heure de publication reconstituee (pic de volume du
    6J entre 11:00 et 14:30 Tokyo) ; signal r(T-1 -> T+15) ; position T+15 -> 15:25 Tokyo dans ce sens. Temoin : les autres
    jours de semaine avec T = 12:00."""
    d = K.banque("BOJ")
    d = d[d <= FIN_DONNEES]
    T = K.heure_boj(j6, d)
    ok = T.notna() & (T + 15 < 15 * 60 + 25)
    d, T = d[ok.to_numpy()], T[ok].to_numpy().astype(int)
    x = np.sign(_rs(j6, d, T - 1, T + 15, TOKYO)) * _rs(j6, d, T + 15, 15 * 60 + 25, TOKYO) * 1e4
    tj = _semaine()
    tj = tj[~tj.isin(K.banque("BOJ", True))]
    t = np.sign(_rs(j6, tj, 12 * 60 - 1, 12 * 60 + 15, TOKYO)) * _rs(j6, tj, 12 * 60 + 15, 15 * 60 + 25, TOKYO) * 1e4
    return dict(code="6J 4", root="6J", creux=True, sens="sens de la reaction a la BoJ", serie=x, temoin=t,
                definition=f"T = pic de volume du 6J (11:00-14:30 Tokyo, {len(d)} reunions datees) ; signal r(T-1 -> T+15), "
                           "position T+15 -> 15:25 Tokyo ; temoin : autres jours avec T = 12:00")


def a64(a6) -> dict:
    """6A 4 - Apres la Banque de reserve d Australie (Valentin 2022, transpose). Signal r(14:29 -> 15:15) Sydney (annonce
    14:30) ; position 15:15 -> 16:45 dans ce sens. Temoin : les autres mardis."""
    d = K.banque("RBA")
    d = d[d <= FIN_DONNEES]
    f = lambda jj: np.sign(_rs(a6, jj, 14 * 60 + 29, 15 * 60 + 15, SYDNEY)) * _rs(a6, jj, 15 * 60 + 15, 16 * 60 + 45, SYDNEY) * 1e4
    tj = _semaine()
    tj = tj[(tj.dayofweek == 1) & ~tj.isin(K.banque("RBA", True))]
    return dict(code="6A 4", root="6A", creux=True, sens="sens de la reaction a 14:30", serie=f(d), temoin=f(tj),
                definition="signal r(14:29 -> 15:15 Sydney), position 15:15 -> 16:45, jours de RBA ; temoin : autres mardis")


# =============================================================================
#  Fiches isolees
# =============================================================================
def nq1(nq) -> dict:
    """NQ 1 - Diffusion des resultats des grandes capitalisations (Jiang et al. 2012 ; Hou 2007). T = premier 8-K de
    resultats accepte sur EDGAR (AAPL, MSFT, AMZN, GOOGL, META, NVDA), entre 16:00 et 16:44 ET. Signal r(16:00 -> T+15) ;
    position T+15 -> T+45 (au plus tard 16:59, avant l arret de 17:00) dans ce sens. Temoin : les autres jours avec
    T = 16:05."""
    ev = K.megacaps()
    tous = pd.DatetimeIndex(ev.date)
    ev = ev[ev.minute <= 16 * 60 + 43]
    d, T = pd.DatetimeIndex(ev.date), ev.minute.to_numpy()
    x = np.sign(_rs(nq, d, 16 * 60, T + 15, ET)) * _rs(nq, d, T + 15, np.minimum(T + 45, 16 * 60 + 59), ET) * 1e4
    tj = jours_ouvres_us(nq)
    tj = tj[~tj.isin(tous)]
    t = np.sign(_rs(nq, tj, 16 * 60, 16 * 60 + 20, ET)) * _rs(nq, tj, 16 * 60 + 20, 16 * 60 + 50, ET) * 1e4
    return dict(code="NQ 1", root="NQ", creux=True, sens="sens de la reaction aux resultats", serie=x, temoin=t,
                definition="T = 1er 8-K de resultats (16:00-16:44 ET) ; signal r(16:00 -> T+15), position T+15 -> T+45 "
                           "(<= 16:59) ; temoin : autres jours, T = 16:05")


def nq2(nq) -> dict:
    """NQ 2 - Prime avant les resultats (Savor & Wilson 2016 : prime de risque les jours d annonces attendues). Achat
    14:00 -> 16:00 ET les jours ou une des six grandes capitalisations publie apres la cloture. Temoin : autres jours."""
    d = pd.DatetimeIndex(K.megacaps().date)
    j = jours_ouvres_us(nq)
    x = r_fenetre(nq, j, (14, 0), (16, 0), ET) * 1e4
    return dict(code="NQ 2", root="NQ", creux=False, sens="+1 (achat)", serie=x[j.isin(d)], temoin=x[~j.isin(d)],
                definition="achat 14:00 -> 16:00 ET les jours de resultats apres cloture (AAPL, MSFT, AMZN, GOOGL, META, NVDA) ; "
                           "temoin : autres jours")


def ym4(ym) -> dict:
    """YM 4 - Ouverture d echeance trimestrielle (Stoll & Whaley 1987 : la pression du reglement a l ouverture se defait
    ensuite). Signal r(9:30 -> 9:45) ET le 3e vendredi de mars, juin, septembre et decembre ; position contraire
    9:45 -> 11:00. Temoin : les autres 3es vendredis (echeances mensuelles d options seulement)."""
    tv = pd.DatetimeIndex([troisieme_vendredi(a, m) for a in range(2016, 2027) for m in range(1, 13)])
    tv = tv[tv <= FIN_DONNEES]
    x = -np.sign(_rs(ym, tv, 9 * 60 + 30, 9 * 60 + 45, ET)) * _rs(ym, tv, 9 * 60 + 45, 11 * 60, ET) * 1e4
    trim = tv.month.isin([3, 6, 9, 12])
    return dict(code="YM 4", root="YM", creux=False, sens="contre le premier quart d heure", serie=x[trim], temoin=x[~trim],
                definition="signal r(9:30 -> 9:45 ET), position contraire 9:45 -> 11:00, 3es vendredis trimestriels ; "
                           "temoin : 3es vendredis mensuels")


def ym5(ym) -> dict:
    """YM 5 - Liquidite en forte volatilite (Nagel 2012 : la fourniture de liquidite rapporte plus quand la volatilite est
    forte). Barre de 15 min (10:00-15:00 ET) > 2 sigma -> position contraire 60 min, en regime de forte volatilite (RV 20 j
    au-dessus de sa mediane des 252 j). Temoin : le meme declencheur en faible volatilite."""
    j = jours_ouvres_us(ym)
    rv = _rv20(ym, j).reindex(j).fillna(False).to_numpy(bool)
    out = []
    for s in range(10 * 60, 14 * 60 + 46, 15):
        r15 = _rs(ym, j, s, s + 15, ET)
        x = -np.sign(r15) * _rs(ym, j, s + 15, s + 75, ET) * 1e4
        out.append(x[r15.abs() > 2 * _sigma(r15)])
    p = _premier(out)
    forte = pd.Series(rv, index=j).reindex(p.index).to_numpy(bool)
    return dict(code="YM 5", root="YM", creux=False, sens="contre le choc", serie=p[forte], temoin=p[~forte],
                definition="barre de 15 min > 2 sigma (10:00-15:00 ET) -> contraire 60 min, forte volatilite ; temoin : faible")


def spy1(spy) -> dict:
    """SPY 1 - Epinglage les jours d expiration (Golez & Jackwerth 2012). A 14:30 ET, prix d exercice le plus proche
    K = dollar rond (pas de 1 $ des options SPY) ; position vers K de 14:30 a 15:55, les 3es vendredis (echeance mensuelle,
    la plus grosse position ouverte). Temoin : mardis et jeudis avant le 15/11/2022 (aucune echeance SPY)."""
    j = jours_ouvres_us(spy)
    p, _ = prix_a(spy, _inst(j, 14 * 60 + 30, ET))
    x = np.sign(np.round(p) - p) * _rs(spy, j, 14 * 60 + 30, 15 * 60 + 55, ET) * 1e4
    tv = pd.DatetimeIndex([troisieme_vendredi(a, m) for a in range(2016, 2027) for m in range(1, 13)])
    sans = (j.dayofweek.isin([1, 3])) & (j < QUOTIDIENNES_SPY)
    ven = x[j.dayofweek == 4]
    return dict(code="SPY 1", root="SPY", creux=False, sens="vers le dollar rond le plus proche", serie=x[j.isin(tv)], temoin=x[sans],
                definition="position vers le dollar rond le plus proche, 14:30 -> 15:55 ET, 3es vendredis ; temoin : mardis et "
                           "jeudis avant le 15/11/2022",
                complement=f"tous les vendredis : {ven.mean():+.2f} pb (t {tstat(ven):+.1f}, {ven.notna().sum()} j)")


def spy5(spy) -> dict:
    """SPY 5 - Prime des jours d annonce macro (Savor & Wilson 2013 : les actions rapportent davantage les jours d emploi,
    d inflation et de FOMC). Achat 9:45 -> 11:45 ET les jours de NFP, CPI ou FOMC. Temoin : autres jours."""
    j = jours_ouvres_us(spy)
    ev = K.annonces_us(("NFP", "CPI")).union(pd.DatetimeIndex(sorted(jours_fomc())))
    x = r_fenetre(spy, j, (9, 45), (11, 45), ET) * 1e4
    return dict(code="SPY 5", root="SPY", creux=False, sens="+1 (achat)", serie=x[j.isin(ev)], temoin=x[~j.isin(ev)],
                definition="achat 9:45 -> 11:45 ET les jours de NFP, CPI ou FOMC ; temoin : autres jours")


def iwm1(iwm) -> dict:
    """IWM 1 - Retour de l ecart de nuit (Branch & Ma ; Berkman et al. 2012 : les hausses de nuit se defont en seance).
    Ecart = r(cloture 16:00 de la veille -> ouverture 9:30) ; position contraire 9:45 -> 11:45 ET. Temoin placebo : la
    meme cible signee par l ecart de la VEILLE."""
    j = jours_ouvres_us(iwm)
    gap = r_fenetre(iwm, j, (16, 0), (9, 30), ET, decal_a=-1)
    cible = r_fenetre(iwm, j, (9, 45), (11, 45), ET) * 1e4
    return dict(code="IWM 1", root="IWM", creux=False, sens="contre l ecart de nuit", serie=-np.sign(gap) * cible,
                temoin=-np.sign(gap.shift(1)) * cible,
                definition="position contraire a l ecart 16:00 (veille) -> 9:30, de 9:45 a 11:45 ET ; temoin : signe de l ecart de la veille")


def cl2(cl) -> dict:
    """CL 2 - Quand l EIA contredit l API (Ye & Karali 2016). Sans les chiffres de stocks, la surprise est mesuree par la
    premiere reaction : API = r(mardi 16:30 -> 16:45 ET), EIA = r(mercredi 10:30 -> 10:32). Les jours ou les signes
    different, position 10:32 -> 12:00 dans le sens de l EIA. Temoin : les jours ou ils concordent. Semaines avec un jour
    ferie exclues (publications decalees)."""
    me = _semaine()
    me = me[me.dayofweek == 2]
    lundi = me - pd.to_timedelta(2, unit="D")
    ferie = np.array([any(us_holiday((l + timedelta(days=i)).date()) for i in range(5)) for l in lundi])
    me = me[~ferie]
    ma = me - pd.Timedelta(days=1)
    api = pd.Series(_r(cl, _inst(ma, 16 * 60 + 30, ET), _inst(ma, 16 * 60 + 45, ET)), index=me)
    eia = _rs(cl, me, 10 * 60 + 30, 10 * 60 + 32, ET)
    x = np.sign(eia) * _rs(cl, me, 10 * 60 + 32, 12 * 60, ET) * 1e4
    ok = (api != 0) & (eia != 0) & api.notna() & eia.notna()
    contra = ok & (np.sign(api) != np.sign(eia))
    return dict(code="CL 2", root="CL", creux=True, sens="sens de la reaction a l EIA", serie=x[contra], temoin=x[ok & ~contra],
                definition="API r(mar. 16:30 -> 16:45), EIA r(mer. 10:30 -> 10:32) de signes opposes -> 10:32 -> 12:00 ET dans "
                           "le sens de l EIA ; temoin : signes concordants")


def gc1(gc) -> dict:
    """GC 1 - Lundi matin a Shanghai (Wang et al. 2019). La Bourse de l or de Shanghai (SGE) n a pas de seance de nuit
    avant le lundi : a 9:00 (Pekin) le lundi, elle decouvre tout le mouvement depuis sa cloture du samedi 2:30. Ma lecture :
    rattrapage, position 9:00 -> 11:00 Pekin dans le sens du mouvement du GC entre samedi 2:30 et lundi 9:00. Temoin : la
    meme regle du mardi au vendredi (mouvement depuis la fin de la seance de nuit, 2:30 -> 9:00). Feries chinois exclus."""
    fc = feries_chine()
    j = _semaine()
    j = j[~j.isin(fc)]
    lun = j[j.dayofweek == 0]
    autres = j[(j.dayofweek > 0) & ~(j - pd.Timedelta(days=1)).isin(fc)]
    sig_l = pd.Series(_r(gc, _inst(lun - pd.Timedelta(days=2), 150, PEKIN), _inst(lun, 9 * 60, PEKIN)), index=lun)
    x = np.sign(sig_l) * _rs(gc, lun, 9 * 60, 11 * 60, PEKIN) * 1e4
    t = np.sign(_rs(gc, autres, 150, 9 * 60, PEKIN)) * _rs(gc, autres, 9 * 60, 11 * 60, PEKIN) * 1e4
    return dict(code="GC 1", root="GC", creux=True, sens="sens du mouvement manque par Shanghai", serie=x, temoin=t,
                definition="lundi : signal r(sam. 2:30 -> lun. 9:00 Pekin), position 9:00 -> 11:00 dans son sens ; temoin : "
                           "mardi-vendredi, signal 2:30 -> 9:00")


def e62(e6) -> dict:
    """6E 2 - Coupure de New York (Golez & Jackwerth 2012, transpose). Les options CME sur le 6E expirent a 10:00 ET
    (9:00 Chicago) le vendredi, prix d exercice tous les 0,005 sur le prix du FUTURE : position vers le prix d exercice le
    plus proche (prix reel du contrat, pas le prix ajuste) de 9:00 a 10:00 ET le vendredi. Temoin : lundi-jeudi."""
    j = jours_ouvres_us(e6)
    p, i = prix_a(e6, _inst(j, 9 * 60, ET))
    reel = np.where(i >= 0, p - e6.offset[np.clip(i, 0, None)], np.nan)             # prix reel = ajuste - decalage
    k = np.round(reel / 0.005) * 0.005
    x = np.sign(k - reel) * _rs(e6, j, 9 * 60, 10 * 60, ET) * 1e4
    ven = j.dayofweek == 4
    return dict(code="6E 2", root="6E", creux=False, sens="vers le prix d exercice le plus proche", serie=x[ven], temoin=x[~ven],
                definition="position vers le multiple de 0,005 le plus proche (prix reel du future), 9:00 -> 10:00 ET, vendredi ; "
                           "temoin : lundi-jeudi (des echeances hebdomadaires y existent aussi depuis quelques annees)")


def b62(b6) -> dict:
    """6B 2 - Chocs de la seance asiatique (BIS 2017 ; Nagel 2012 : liquidite rare la nuit, retour plus fort). Barre de 15
    min > 2 sigma entre 22:00 (veille) et 6:00 Londres -> position contraire 60 min. Temoin : le meme declencheur en seance
    de Londres (8:00-16:00)."""
    j = _semaine()
    nuit = declencheur(b6, b6, j, list(range(-120, 6 * 60 - 14, 15)), LONDRES,
                       regle=lambda r, s: r.abs() > 2 * s)["haut"]
    jour = declencheur(b6, b6, j, list(range(8 * 60, 16 * 60 - 14, 15)), LONDRES,
                       regle=lambda r, s: r.abs() > 2 * s)["haut"]
    return dict(code="6B 2", root="6B", creux=True, sens="contre le choc", serie=-nuit, temoin=-jour,
                definition="barre de 15 min > 2 sigma de 22:00 a 6:00 Londres -> contraire 60 min ; temoin : 8:00-16:00 Londres")


def j62(j6) -> dict:
    """6J 2 - Denouement du carry trade (Brunnermeier, Nagel & Pedersen 2008 : les ventes forcees prolongent les hausses
    brutales du yen). Barre de 15 min du 6J > +3 sigma (hausse du yen, seuil de krach), a toute heure -> achat du yen 60 min.
    Temoin : apres une BAISSE du yen de plus de 3 sigma, vente du yen 60 min (simple elan, sans denouement)."""
    j = _semaine()
    d = declencheur(j6, j6, j, list(range(0, 24 * 60 - 14, 15)), LONDRES, k=3.0)
    return dict(code="6J 2", root="6J", creux=True, sens="+1 apres une hausse brutale du yen", serie=d["haut"], temoin=-d["bas"],
                definition="barre 6J de 15 min > +3 sigma (24 h) -> achat 60 min ; temoin : < -3 sigma -> vente 60 min")


def j63(j6) -> dict:
    """6J 3 - Les particuliers japonais (Banque du Japon 2023 ; Kaourma et al. 2025 : les particuliers, actifs le soir a
    Tokyo, vont contre le mouvement). Barre de 15 min > 2 sigma entre 18:00 et 23:00 Tokyo -> position contraire 60 min.
    Temoin : le meme declencheur en journee a Tokyo (9:00-15:00)."""
    j = _semaine()
    soir = declencheur(j6, j6, j, list(range(18 * 60, 23 * 60 - 14, 15)), TOKYO, regle=lambda r, s: r.abs() > 2 * s)["haut"]
    jour = declencheur(j6, j6, j, list(range(9 * 60, 15 * 60 - 14, 15)), TOKYO, regle=lambda r, s: r.abs() > 2 * s)["haut"]
    return dict(code="6J 3", root="6J", creux=True, sens="contre le choc", serie=-soir, temoin=-jour,
                definition="barre de 15 min > 2 sigma de 18:00 a 23:00 Tokyo -> contraire 60 min ; temoin : 9:00-15:00 Tokyo")


def a61(a6) -> dict:
    """6A 1 - Statistiques chinoises d activite (Baum, Kurov & Wolfe 2015 ; Mathews 2016). T = heure du calendrier NBS
    (10:00 Pekin le plus souvent) ; signal r(T-1 -> T+2) ; position T+2 -> T+30 dans ce sens. Temoin : les autres jours de
    semaine, T = 10:00."""
    c = K.nbs()
    c = c[c.date <= FIN_DONNEES]
    d, T = pd.DatetimeIndex(c.date), c.minute.to_numpy()
    x = np.sign(_rs(a6, d, T - 1, T + 2, PEKIN)) * _rs(a6, d, T + 2, T + 30, PEKIN) * 1e4
    tj = _semaine()
    tj = tj[~tj.isin(d)]
    t = np.sign(_rs(a6, tj, 599, 602, PEKIN)) * _rs(a6, tj, 602, 630, PEKIN) * 1e4
    return dict(code="6A 1", root="6A", creux=True, sens="sens de la premiere reaction", serie=x, temoin=t,
                definition="signal r(T-1 -> T+2), position T+2 -> T+30, T = publication NBS (heure de Pekin) ; temoin : "
                           "autres jours a 10:00")


# =============================================================================
#  Organisation par familles et rapport
# =============================================================================
FAMILLES_BC = [
    ("Derive avant une publication", "ES 2", ["NQ 5", "CL 5", "6E 5", "6A 5"]),
    ("Retard d un actif sur un autre", "IWM 2", ["DAX 3", "GC 2", "GC 4", "GC 5", "6A 2", "6B 5"]),
    ("Pression d enchere", "ES 3", ["SPY 4", "DAX 5"]),
    ("Ecarts entre actifs lies", "YM 2", ["6B 1"]),
]
DEJA_ELIMINEES = {"NQ 3": "ES 5", "IWM 4": "ES 5", "6B 4": "6J 1", "6A 3": "6J 1", "GC 3": "6J 1",
                  "YM 3": "YM 1", "NQ 4": "YM 1", "SPY 3": "YM 1", "IWM 3": "YM 1", "IWM 5": "YM 1", "6J 5": "YM 1"}
NIVEAUX = {"ES 2": "B", "IWM 2": "B", "ES 3": "B", "YM 2": "B", "6E 3": "C", "6B 3": "C", "6J 4": "C", "6A 4": "C",
           "NQ 1": "C", "NQ 2": "C", "YM 4": "B", "YM 5": "C", "SPY 1": "B", "SPY 5": "C", "IWM 1": "B", "CL 2": "B",
           "GC 1": "B", "6E 2": "C", "6B 2": "C", "6J 2": "B", "6J 3": "C", "6A 1": "B"}     # tableau de la vue d ensemble
EN_ATTENTE = {"DAX 1": "minutes DAX (Dukascopy) en telechargement", "DAX 2": "idem (actif le mieux place de la famille banque centrale)",
              "DAX 4": "idem", "6E 1": "idem (rendement des actions europeennes)",
              "CL 3": "contrat qui expire (symbole brut) : non disponible dans nos donnees continues"}


def _juge(d: dict, marches: dict) -> dict:
    roots = d["root"].split("+")
    cout = 0.0
    for r in roots:
        m = marches[r]
        prix = float(np.nanmedian(m.c[-500000:]))
        cout += cout_bp(r, prix, d["creux"])
    return criteres(pd.Series(d["serie"]).dropna(), None if d["temoin"] is None else pd.Series(d["temoin"]).dropna(), cout)


def _bloc(pr, d, c):
    pr(f"--- {d['code']} : {d['definition']}")
    pr(f"    sens prevu : {d['sens']} | {c['n']} cas | moyenne {c['moyenne']:+.2f} pb (t {c['t']:+.1f}) | 2016-2020 {c['m1']:+.2f} "
       f"(t {c['t1']:+.1f}) | 2021-2026 {c['m2']:+.2f} (t {c['t2']:+.1f})")
    pr(f"    temoin {c['temoin']:+.2f} pb, Welch {c['welch']:+.1f} | cout aller-retour {c['cout']:.2f} pb -> net {c['net']:+.2f} pb, "
       f"sans les 3 meilleurs jours {c['sans3']:+.2f} pb" + (f" | annees nettes positives {c['part_annees']:.0%}" if c["rare"] else ""))
    if d.get("complement"):
        pr(f"    {d['complement']}")
    echecs = [k for k, v in c["tests"].items() if not v]
    pr(f"    VERDICT : {'PASSE - coder les regles' if c['passe'] else 'ECHOUE (' + ' ; '.join(echecs) + ')'}")


def etude(sortie: str | None = None, log=print) -> list:
    t0 = datetime.now()
    log("[60 B/C] chargement des marches")
    mk = {r: marche(r) for r in ("ES", "NQ", "YM", "GC", "CL", "6E", "6B", "6J", "6A", "SPY", "IWM")}
    L = []
    pr = L.append
    pr("=" * 118)
    pr(" 60 STRATEGIES INTRADAY - ETAPE 2 : ANOMALIES BRUTES DES NIVEAUX B ET C (sans regles, stop ni taille)")
    pr("=" * 118)
    pr("Onglets par actif non fournis : definitions = ma lecture des papiers (signe seul ; 2 sigma quand la fiche parle de choc).")
    pr("Criteres identiques a l etape 1, fixes avant le test : t >= 3 ; meme signe et t >= 1,5 sur 2016-2020 et 2021-2026 ;")
    pr("Welch >= 2 contre le temoin ; gain moyen net de couts > 0 ; > 0 sans les 3 meilleurs jours. Rares (< 60) : t >= 2, net > 0")
    pr(">= 65 % des annees. Calendriers officiels : nexus/perso/calendriers.py (BCE, BoE, BoJ, RBA, NBS, SEC EDGAR, BLS, ALFRED).\n")
    res = []

    pr("#" * 118)
    pr("# 1. FAMILLES : l actif le mieux place d abord ; s il echoue, la famille entiere est eliminee")
    pr("#" * 118)
    tetes = {"ES 2": lambda: es2(mk["ES"]), "IWM 2": lambda: iwm2(mk["SPY"], mk["IWM"]), "ES 3": lambda: es3(mk["ES"]),
             "YM 2": lambda: ym2(mk["YM"], mk["ES"])}
    eliminees = {}
    for nom, tete, membres in FAMILLES_BC:
        d = tetes[tete]()
        c = _juge(d, mk)
        res.append((d, c, dict(groupe=f"Famille : {nom}", role="actif teste en premier", membres=membres)))
        pr(f"\n[{nom}] actif teste en premier : {tete} ; membres : {', '.join(membres)}")
        _bloc(pr, d, c)
        if c["passe"]:
            pr(f"    -> {tete} passe : tester ensuite les membres ({', '.join(membres)})")
        else:
            pr(f"    -> famille eliminee : {', '.join(membres)}")
            eliminees.update({m: tete for m in membres})

    pr("\n" + "#" * 118)
    pr("# 2. DERIVE APRES UNE BANQUE CENTRALE : DAX 2 (actif le mieux place) attend les minutes du DAX ; membres testes")
    pr("#    un par un en attendant. Si DAX 2 echoue, la famille sera eliminee quels que soient ces resultats.")
    pr("#" * 118)
    for f in (lambda: e63(mk["6E"]), lambda: b63(mk["6B"]), lambda: j64(mk["6J"]), lambda: a64(mk["6A"])):
        d = f()
        c = _juge(d, mk)
        res.append((d, c, dict(groupe="Derive apres une banque centrale (DAX 2 en attente)", role="membre")))
        pr("")
        _bloc(pr, d, c)

    pr("\n" + "#" * 118)
    pr("# 3. FICHES ISOLEES (hors familles)")
    pr("#" * 118)
    for f in (lambda: nq1(mk["NQ"]), lambda: nq2(mk["NQ"]), lambda: ym4(mk["YM"]), lambda: ym5(mk["YM"]),
              lambda: spy1(mk["SPY"]), lambda: spy5(mk["SPY"]), lambda: iwm1(mk["IWM"]), lambda: cl2(mk["CL"]),
              lambda: gc1(mk["GC"]), lambda: e62(mk["6E"]), lambda: b62(mk["6B"]), lambda: j62(mk["6J"]),
              lambda: j63(mk["6J"]), lambda: a61(mk["6A"])):
        d = f()
        c = _juge(d, mk)
        res.append((d, c, dict(groupe="Fiches isolees", role="isolee")))
        pr("")
        _bloc(pr, d, c)

    pr("\n" + "#" * 118)
    pr("# 4. BILAN")
    pr("#" * 118)
    ok = [d["code"] for d, c, _ in res if c["passe"]]
    pr(f"Testees : {len(res)} ; passent tous les criteres : {len(ok)}" + (f" ({', '.join(ok)})" if ok else ""))
    pr("Eliminees avec leur famille a cette etape : " + (", ".join(f"{m} ({t})" for m, t in eliminees.items()) or "aucune"))
    pr("Eliminees avec leur famille a l etape 1 : " + ", ".join(f"{m} ({t})" for m, t in DEJA_ELIMINEES.items()))
    pr("En attente : " + " ; ".join(f"{k} : {v}" for k, v in EN_ATTENTE.items()))
    pr(f"Calcul en {(datetime.now() - t0).total_seconds():.0f} s.")
    sortie = sortie or os.path.join(PY_DIR, "recherche", "resultats_60_niveaux_BC.txt")
    with open(sortie, "w", encoding="utf-8") as fh:
        fh.write("\n".join(L) + "\n")
    exporter("niveaux_BC", dict(lignes=[ligne_json(d, c, niveau=NIVEAUX.get(d["code"]), **x) for d, c, x in res],
                                eliminees_ici=eliminees, eliminees_etape1=DEJA_ELIMINEES, en_attente=EN_ATTENTE))
    log("\n".join(L))
    return res


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--sortie", default=None)
    a = ap.parse_args(argv)
    etude(a.sortie)


if __name__ == "__main__":
    main()
