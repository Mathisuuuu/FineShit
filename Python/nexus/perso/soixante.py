"""60 strategies intraday par actif (vue d ensemble du 9 octobre 2026) - ETAPE 1 : anomalies brutes de niveau A.

    python -m nexus.perso.soixante [--sortie resultats_60_niveau_A.txt]

Ordre de travail de la vue d ensemble : tester d abord l anomalie BRUTE (sans regles, stop ni taille) des strategies de
niveau A et A conteste, avec les criteres fixes avant le test ; ne coder les regles que pour celles qui passent, puis
passer aux niveaux B et C par familles.
Les onglets par actif (signal, seuils, stop, exclusions, temoin) n ont pas ete fournis : chaque definition ci-dessous
est MA lecture du papier cite, au plus simple (signe du signal, sans seuil quand c est possible), et son temoin est
indique. Elles seront remplacees par celles des onglets.

Conventions communes appliquees :
  - « prix a HH:MM » = ouverture de la barre qui COMMENCE a HH:MM (nos barres sont horodatees a leur fin) ; barre absente :
    cloture de la derniere barre des 5 minutes precedentes ; au-dela, jour exclu ;
  - heures dans le fuseau de la place (base IANA), jamais en UTC fixe ;
  - r(A -> B) = ln(P_B / P_A) ; futures : jour exclu si le changement de contrat tombe dans la fenetre (signal ou detention) ;
  - couts du tableau (contrat standard ; glissement d heures liquides ou creuses, commission 2,50 $ par cote ; SPY 0,01 $).
Criteres (fixes avant le test) : t >= 3 sur 2016-2026 ; meme signe sur 2016-2020 et 2021-2026 avec t >= 1,5 dans chacune ;
t de Welch >= 2 contre le temoin ; gain moyen net de couts > 0 ; encore > 0 sans les 3 meilleurs jours. Evenements rares
(< 60 cas) : t >= 2 et gain net positif dans au moins 65 % des annees.
"""
from __future__ import annotations

import argparse
import math
import os
from datetime import datetime

import numpy as np
import pandas as pd

from .fx_trois import fx
from .or_anomalies import instants, jours_fomc
from .qf import alpaca_minutes
from .suite_s import us_holiday

PY_DIR = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", ".."))
NS_MIN = 60_000_000_000
NS_JOUR = 86_400_000_000_000
ET, FRANCFORT = "America/New_York", "Europe/Berlin"
COUPURE = pd.Timestamp("2021-01-01")

# Couts du tableau de la vue d ensemble (contrat standard) : tick, valeur du point, glissement par cote (liquide, creux)
COUTS = {"ES": (0.25, 50.0, 1, 2), "NQ": (0.25, 20.0, 1, 3), "YM": (1.0, 5.0, 1, 3), "GC": (0.10, 100.0, 1, 3),
         "CL": (0.01, 1000.0, 1, 3), "6E": (0.00005, 125000.0, 1, 2), "6B": (0.0001, 62500.0, 1, 3),
         "6J": (0.0000005, 12500000.0, 1, 3), "6A": (0.00005, 100000.0, 1, 3)}
COMMISSION = 2.50


# =============================================================================
#  Donnees et prix aux heures de la fiche
# =============================================================================
class Spy:
    """Minutes Alpaca de SPY (ou IWM) au format des marches futures (t en ns UTC, fin de barre)."""

    def __init__(self, sym: str = "SPY"):
        df = alpaca_minutes(sym)
        idx = pd.DatetimeIndex(df.index).as_unit("ns")
        self.root, self.t, self.n = sym, idx.asi8, len(df)
        self.o, self.h, self.l, self.c = (df[k].to_numpy(float) for k in ("open", "high", "low", "close"))
        self.v = df["volume"].to_numpy(float) if "volume" in df else np.zeros(self.n)
        self.offset = np.zeros(self.n)


def marche(root: str):
    return Spy(root) if root in ("SPY", "IWM") else fx(root)


def prix_a(m, debut_barre: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Prix a l instant (ns UTC) : ouverture de la barre qui commence a cet instant, sinon cloture de la derniere barre
    finie dans les 5 minutes precedentes, sinon NaN. -> (prix, indice de la barre utilisee)."""
    fin = debut_barre + NS_MIN
    k = np.clip(np.searchsorted(m.t, fin), 0, m.n - 1)
    exact = m.t[k] == fin
    j = np.clip(np.searchsorted(m.t, debut_barre, side="right") - 1, 0, m.n - 1)
    recent = (m.t[j] <= debut_barre) & (m.t[j] > debut_barre - 5 * NS_MIN)
    px = np.where(exact, m.o[k], np.where(recent, m.c[j], np.nan))
    idx = np.where(exact, k, np.where(recent, j, -1))
    return px, idx


def contrats(m) -> np.ndarray:
    """Numero de l echeance de chaque minute. Ajustement additif : prix ajuste - prix reel constant par echeance ;
    proportionnel (CL) : prix ajuste / prix reel constant. Un roulement change les DEUX a la fois."""
    if getattr(m, "_contrat", None) is None:
        if not hasattr(m, "rc"):
            m._contrat = np.zeros(m.n, np.int64)
        else:
            rc = np.where(np.isfinite(m.rc) & (m.rc != 0), m.rc, np.nan)
            ecart, rapport = pd.Series(m.c - rc).ffill().to_numpy(), pd.Series(m.c / rc).ffill().to_numpy()
            change = np.r_[False, (np.abs(np.diff(ecart)) > 1e-9) & (np.abs(np.diff(rapport)) > 1e-12)]
            m._contrat = np.cumsum(change)
    return m._contrat


def r_fenetre(m, jours: pd.DatetimeIndex, a: tuple, b: tuple, tz: str, decal_a: int = 0) -> pd.Series:
    """r(A -> B) par jour ; A peut etre la veille (decal_a = -1 : jour ouvre precedent de la liste). Jour exclu si un
    prix manque ou si le contrat change entre A et B (le decalage prix ajuste - prix reel change)."""
    ta, tb = instants(jours, *a, tz), instants(jours, *b, tz)
    if decal_a:
        ta = np.r_[np.full(-decal_a, np.iinfo(np.int64).min // 2), ta[:decal_a]]
    pa, ia = prix_a(m, ta)
    pb, ib = prix_a(m, tb)
    ok = np.isfinite(pa) & np.isfinite(pb) & (ia >= 0) & (ib >= 0)
    roll = np.zeros(len(jours), bool)
    cid = contrats(m)
    roll[ok] = cid[ib[ok]] != cid[ia[ok]]
    r = np.where(ok & ~roll, np.log(pb / np.where(pa > 0, pa, np.nan)), np.nan)
    return pd.Series(r, index=jours)


def jours_ouvres_us(m) -> pd.DatetimeIndex:
    j = pd.to_datetime(np.unique(m.t // NS_JOUR) * NS_JOUR)
    return pd.DatetimeIndex([d for d in j if d.dayofweek < 5 and not us_holiday(d.date())])


def cout_bp(root: str, prix: float, creux: bool) -> float:
    """Aller-retour en points de base : 2 x glissement + 2 x commission, au prix median de la fenetre."""
    if root in ("SPY", "IWM"):
        return 2 * (0.02 if creux else 0.01) / prix * 1e4
    tick, pv, gl_liq, gl_creux = COUTS[root]
    gl = gl_creux if creux else gl_liq
    return (2 * gl * tick + 2 * COMMISSION / pv) / prix * 1e4


# =============================================================================
#  Criteres de validation (vue d ensemble, fixes avant le test)
# =============================================================================
def tstat(x: pd.Series) -> float:
    x = pd.Series(x).dropna()
    return float(x.mean() / (x.std(ddof=1) / math.sqrt(len(x)))) if len(x) > 2 and x.std(ddof=1) > 0 else math.nan


def criteres(brut_pb: pd.Series, temoin_pb: pd.Series | None, cout: float) -> dict:
    """brut_pb : rendement de la fenetre DANS LE SENS PREVU (pb), un par jour qualifie ; temoin_pb : meme mesure sur le
    groupe temoin ; cout : aller-retour en pb."""
    x = brut_pb.dropna()
    n = len(x)
    rare = n < 60
    p1, p2 = x[x.index < COUPURE], x[x.index >= COUPURE]
    t, t1, t2 = tstat(x), tstat(p1), tstat(p2)
    net = x - cout
    welch = math.nan
    if temoin_pb is not None and len(temoin_pb.dropna()) > 2 and n > 2:
        y = temoin_pb.dropna()
        se = math.sqrt(x.var(ddof=1) / n + y.var(ddof=1) / len(y))
        welch = (x.mean() - y.mean()) / se if se > 0 else math.nan
    sans3 = net.drop(net.nlargest(3).index).mean() if n > 3 else math.nan
    annees = net.groupby(net.index.year).sum()
    part_ann = float((annees > 0).mean()) if len(annees) else math.nan
    if rare:
        tests = {"t >= 2 (evenement rare)": t >= 2, "gain net positif >= 65 % des annees": part_ann >= 0.65,
                 "t de Welch >= 2 contre le temoin": welch >= 2 if np.isfinite(welch) else False,
                 "gain net > 0 sans les 3 meilleurs jours": sans3 > 0}
    else:
        tests = {"t >= 3": t >= 3, "meme signe et t >= 1,5 sur 2016-2020 et 2021-2026": t1 >= 1.5 and t2 >= 1.5,
                 "t de Welch >= 2 contre le temoin": welch >= 2 if np.isfinite(welch) else False,
                 "gain moyen net > 0": net.mean() > 0, "gain net > 0 sans les 3 meilleurs jours": sans3 > 0}
    return dict(n=n, moyenne=x.mean(), t=t, m1=p1.mean(), t1=t1, m2=p2.mean(), t2=t2, temoin=temoin_pb.mean() if temoin_pb is not None else math.nan,
                welch=welch, cout=cout, net=net.mean(), sans3=sans3, part_annees=part_ann, rare=rare, tests=tests,
                passe=all(tests.values()))


def _propre(o):
    """Valeurs JSON : NaN et infinis -> None, types numpy -> types Python."""
    if isinstance(o, dict):
        return {k: _propre(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_propre(v) for v in o]
    if isinstance(o, (bool, np.bool_)):
        return bool(o)
    if isinstance(o, (int, np.integer)):
        return int(o)
    if isinstance(o, (float, np.floating)):
        return round(float(o), 4) if math.isfinite(o) else None
    return o


def ligne_json(d: dict, c: dict, **autres) -> dict:
    """Une anomalie testee, au format lu par le tableau de bord."""
    return _propre(dict(code=d["code"], definition=d["definition"], sens=d["sens"], n=c["n"], moyenne=c["moyenne"], t=c["t"],
                        m1=c["m1"], t1=c["t1"], m2=c["m2"], t2=c["t2"], temoin=c["temoin"], welch=c["welch"], cout=c["cout"],
                        net=c["net"], sans3=c["sans3"], rare=c["rare"], passe=c["passe"],
                        echecs=[k for k, v in c["tests"].items() if not v], **autres))


def exporter(cle: str, contenu: dict, chemin: str | None = None) -> str:
    """Ecrit une partie de resultats_60.json (niveau_A, niveaux_BC, nq1) sans toucher aux autres."""
    import json
    chemin = chemin or os.path.join(PY_DIR, "recherche", "resultats_60.json")
    try:
        with open(chemin, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        data = {}
    data[cle] = _propre(dict(genere=f"{datetime.now():%Y-%m-%d %H:%M}", **contenu))
    with open(chemin, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=1)
    return chemin


def _rv20(m, jours: pd.DatetimeIndex) -> pd.Series:
    """Regime de volatilite : ecart-type des rendements cloture -> cloture (16:00 ET) sur 20 seances, compare a sa
    mediane des 252 seances precedentes (forte = au-dessus)."""
    pc, _ = prix_a(m, instants(jours, 16, 0, ET))
    r = pd.Series(np.log(pc), index=jours).diff()
    rv = r.rolling(20, min_periods=15).std()
    med = rv.rolling(252, min_periods=120).median().shift(1)
    return rv.shift(1) > med                                    # connu avant la seance


# =============================================================================
#  Les 10 anomalies de niveau A et A conteste (lecture des papiers, onglets absents)
# =============================================================================
def es1(es) -> dict:
    """ES 1 - Ouverture europeenne apres une baisse (Boyarchenko, Larsen & Whelan 2023 : la derive nocturne des futures
    americains se concentre a l ouverture europeenne, plus forte apres une baisse). Achat 08:00 -> 10:00 Francfort si la
    seance americaine de la veille (cloture 16:00 -> cloture 16:00 ET) a baisse. Temoin : la meme fenetre apres une hausse."""
    j = jours_ouvres_us(es)
    fen = r_fenetre(es, j, (8, 0), (10, 0), FRANCFORT) * 1e4
    veille = r_fenetre(es, j, (16, 0), (16, 0), ET, decal_a=-1).shift(1)          # seance terminee la veille au soir
    qual, tem = fen[veille < 0], fen[veille > 0]
    return dict(code="ES 1", sens="+1 (achat)", serie=qual, temoin=tem, creux=True,
                definition="achat 08:00 -> 10:00 Francfort apres une seance americaine en baisse (veille) ; temoin : apres une hausse")


def es4(es) -> dict:
    """ES 4 - Pre-FOMC en forte volatilite (Lucca & Moench 2015 ; contre : Kurov et al. 2021). Achat 12:00 -> 13:55 ET les
    jours de FOMC en regime de forte volatilite. Temoin : meme fenetre, autres jours de forte volatilite."""
    j = jours_ouvres_us(es)
    fen = r_fenetre(es, j, (12, 0), (13, 55), ET) * 1e4
    forte = _rv20(es, j).reindex(j).fillna(False).to_numpy(bool)
    fomc = pd.Index(j).isin(jours_fomc())
    return dict(code="ES 4", sens="+1 (achat)", serie=fen[fomc & forte], temoin=fen[~fomc & forte], creux=False,
                definition="achat 12:00 -> 13:55 ET les jours de FOMC en forte volatilite (RV 20 j > mediane des 252 j) ; "
                           "temoin : autres jours de forte volatilite",
                complement=f"tous les jours de FOMC : {fen[fomc].mean():+.2f} pb (t {tstat(fen[fomc]):+.1f}, {fen[fomc].notna().sum()} j)")


def _momentum_couverture(m, root: str, regl: tuple, fin: tuple, code: str) -> dict:
    """Baltussen, Da, Lammers & Martens (2021) : le rendement depuis le reglement de la veille predit la derniere
    demi-heure (couverture des vendeurs d options). Sens = signe du signal. Temoin placebo : la meme demi-heure signee par
    le signal de la VEILLE (un signal perime ne doit rien predire)."""
    j = jours_ouvres_us(m)
    sig = r_fenetre(m, j, regl, (fin[0], fin[1] - 30) if fin[1] >= 30 else (fin[0] - 1, fin[1] + 30), ET, decal_a=-1)
    debut = (fin[0], fin[1] - 30) if fin[1] >= 30 else (fin[0] - 1, fin[1] + 30)
    cible = r_fenetre(m, j, debut, fin, ET) * 1e4
    signe = np.sign(sig)
    return dict(code=code, sens="signe du signal", serie=signe * cible, temoin=signe.shift(1) * cible, creux=root.startswith("6"),
                definition=f"signal : reglement de la veille ({regl[0]:02d}:{regl[1]:02d} ET) -> {debut[0]:02d}:{debut[1]:02d} ET ; "
                           f"cible {debut[0]:02d}:{debut[1]:02d} -> {fin[0]:02d}:{fin[1]:02d} ET dans le sens du signal ; "
                           "temoin : meme cible signee par le signal de la veille")


def es5(es) -> dict:
    return _momentum_couverture(es, "ES", (16, 0), (16, 0), "ES 5")


def e64(e6) -> dict:
    return _momentum_couverture(e6, "6E", (15, 0), (15, 0), "6E 4")


def ym1(ym) -> dict:
    """YM 1 - Dernier jour du mois (Etula, Rinne, Suominen & Vaittinen 2020, « Dash for cash »). Fenetre 14:00 -> 16:00
    ET du dernier jour ouvre du mois. Le SENS n est pas donne dans la vue d ensemble : teste a l achat (effet de tournant de
    mois), a confirmer avec l onglet. Temoin : la meme fenetre les autres jours."""
    j = jours_ouvres_us(ym)
    fen = r_fenetre(ym, j, (14, 0), (16, 0), ET) * 1e4
    dernier = pd.Series(j, index=j).groupby([j.year, j.month]).transform("max").to_numpy() == j.to_numpy()
    return dict(code="YM 1", sens="+1 (achat, a confirmer)", serie=fen[dernier], temoin=fen[~dernier], creux=False,
                definition="14:00 -> 16:00 ET le dernier jour ouvre du mois, sens suppose acheteur (vue d ensemble muette) ; "
                           "temoin : autres jours")


def spy2(spy) -> dict:
    """SPY 2 - Amortissement par les options 0DTE (Amaya et al. 2025 : la couverture des teneurs de marche, acheteurs de
    gamma, freine les mouvements). Declencheur : barre de 30 min (12:30-15:00 ET) de plus de 2 sigma (meme barre, 60
    seances) ; position contraire pendant 60 min. Temoin : le meme declencheur les jours SANS expiration SPY (mardi et
    jeudi avant le 15 novembre 2022, date d ajout des echeances quotidiennes)."""
    j = jours_ouvres_us(spy)
    lignes = []
    for h, mi in ((12, 30), (13, 0), (13, 30), (14, 0), (14, 30)):
        fin_h, fin_m = (h, mi + 30) if mi == 0 else (h + 1, 0)
        r30 = r_fenetre(spy, j, (h, mi), (fin_h, fin_m), ET)
        sig = (r30.abs().rolling(60, min_periods=40).median() * 1.4826).shift(1)
        sortie = (fin_h + 1, fin_m)
        apres = r_fenetre(spy, j, (fin_h, fin_m), sortie, ET)
        ok = r30.abs() > 2 * sig
        lignes.append(pd.DataFrame({"r": -np.sign(r30[ok]) * apres[ok] * 1e4}))
    d = pd.concat(lignes).dropna()
    d = d[~d.index.duplicated(keep="first")]                     # au plus une entree par jour
    quot = pd.Timestamp("2022-11-15")                            # echeances SPY du mardi et du jeudi : 15 et 17/11/2022
    expir = np.array([x.dayofweek == 4 or x >= quot for x in d.index])               # vendredi : echeance depuis 2005
    sans = np.array([x.dayofweek in (1, 3) and x < quot for x in d.index])           # mardi, jeudi avant : aucune echeance
    return dict(code="SPY 2", sens="contre le mouvement", serie=d["r"][expir], temoin=d["r"][sans], creux=False,
                definition="barre de 30 min (12:30-15:00 ET) > 2 sigma -> position contraire 60 min, jours d expiration SPY "
                           "certains (vendredis, puis tous les jours depuis le 15/11/2022) ; temoin : mardis et jeudis avant le "
                           "15/11/2022 (aucune echeance) ; lundis et mercredis d avant exclus (date d introduction incertaine)")


def _cl_wen(cl, eia: bool, code: str) -> dict:
    """Wen et al. (2023) : momentum intraday du petrole ; les jours de rapport EIA, la demi-heure qui suit la publication
    (10:30 -> 11:00 ET) predit la fin de seance ; les autres jours, la premiere demi-heure (09:00 -> 09:30 ET). Cible
    14:00 -> 14:27 ET dans le sens du signal. Temoin : le meme signal les jours de l autre type."""
    j = jours_ouvres_us(cl)
    lundi = [d - pd.Timedelta(days=d.dayofweek) for d in j]
    decalee = np.array([any(us_holiday((l + pd.Timedelta(days=i)).date()) for i in range(5)) for l in lundi])  # semaine avec ferie
    jours_eia = np.array([d.dayofweek == 2 for d in j]) & ~decalee
    debut, fin = ((10, 30), (11, 0)) if eia else ((9, 0), (9, 30))
    sig = r_fenetre(cl, j, debut, fin, ET)
    cible = r_fenetre(cl, j, (14, 0), (14, 27), ET) * 1e4
    signe = np.sign(sig) * cible
    autres = ~jours_eia & ~decalee
    sel, tem = (jours_eia, autres) if eia else (autres, jours_eia)
    return dict(code=code, sens="signe du signal", serie=signe[sel], temoin=signe[tem], creux=False,
                definition=f"signal {debut[0]:02d}:{debut[1]:02d} -> {fin[0]:02d}:{fin[1]:02d} ET, cible 14:00 -> 14:27 ET, "
                           f"jours {'EIA (mercredi, hors semaines feriees)' if eia else 'sans rapport EIA'} ; temoin : l autre type de jours")


def cl1(cl) -> dict:
    return _cl_wen(cl, True, "CL 1")


def cl4(cl) -> dict:
    return _cl_wen(cl, False, "CL 4")


def j61(j6, es) -> dict:
    """6J 1 - Le yen refuge (Ranaldo & Soderlind 2010 ; contre : Park & Fang 2025). Barre ES de 15 min (alignee sur :00,
    :15, :30, :45, fin entre 09:45 et 16:00 ET) en baisse de plus de 2 sigma (meme barre, 60 seances) -> achat du yen (6J)
    pendant 60 min. Temoin : le yen apres une HAUSSE de plus de 2 sigma de l ES."""
    j = jours_ouvres_us(es)
    out, tem = [], []
    for k in range(25):                                          # barres finissant de 09:45 a 15:45 ET
        h, mi = divmod(9 * 60 + 30 + 15 * k, 60)
        fh, fm = divmod(9 * 60 + 45 + 15 * k, 60)
        if fh * 60 + fm > 16 * 60 - 60:
            break
        r15 = r_fenetre(es, j, (h, mi), (fh, fm), ET)
        sig = (r15.abs().rolling(60, min_periods=40).median() * 1.4826).shift(1)
        sh, sm = divmod(fh * 60 + fm + 60, 60)
        yen = r_fenetre(j6, j, (fh, fm), (sh, sm), ET) * 1e4
        out.append(yen[r15 < -2 * sig])
        tem.append(yen[r15 > 2 * sig])
    s = pd.concat(out).dropna()
    s = s[~s.index.duplicated(keep="first")]
    t = pd.concat(tem).dropna()
    t = t[~t.index.duplicated(keep="first")]
    return dict(code="6J 1", sens="+1 (achat du yen)", serie=s, temoin=t, creux=True,
                definition="ES 15 min < -2 sigma (09:45-15:00 ET) -> achat du 6J 60 min ; temoin : apres une hausse > 2 sigma")


FAMILLES = {"ES 5": "momentum ou retournement de fin de seance (ES 5, NQ 3, 6E 4, IWM 4)",
            "6J 1": "choc sur les actions -> refuge ou carry (6J 1, 6B 4, 6A 3, GC 3)",
            "YM 1": "calendrier (YM 1, YM 3, NQ 4, SPY 3, IWM 3, IWM 5, 6J 5)"}


# =============================================================================
#  Rapport
# =============================================================================
def etude(sortie: str | None = None, log=print) -> list:
    t0 = datetime.now()
    log("[60] chargement des marches")
    es, ym, cl, e6, j6, spy = (marche(r) for r in ("ES", "YM", "CL", "6E", "6J", "SPY"))
    tests = [es1(es), es4(es), es5(es), ym1(ym), spy2(spy), cl1(cl), cl4(cl), e64(e6), j61(j6, es)]
    L = []
    pr = L.append
    pr("=" * 118)
    pr(" 60 STRATEGIES INTRADAY - ETAPE 1 : ANOMALIES BRUTES DE NIVEAU A ET A CONTESTE (sans regles, stop ni taille)")
    pr("=" * 118)
    pr("Onglets par actif non fournis : les definitions sont ma lecture des papiers (signe seul, sans seuil quand c est possible).")
    pr("Criteres fixes avant le test : t >= 3 ; meme signe et t >= 1,5 sur 2016-2020 et 2021-2026 ; Welch >= 2 contre le temoin ;")
    pr("gain moyen net de couts > 0 ; > 0 sans les 3 meilleurs jours. Evenements rares (< 60) : t >= 2, net positif >= 65 % des annees.")
    pr("DAX 1 (New York predit la fin de Francfort) : en attente des minutes Dukascopy (telechargement en cours).\n")
    res = []
    for d in tests:
        x = d["serie"].dropna()
        px_ref = {"ES 1": "ES", "ES 4": "ES", "ES 5": "ES", "YM 1": "YM", "SPY 2": "SPY", "CL 1": "CL", "CL 4": "CL",
                  "6E 4": "6E", "6J 1": "6J"}[d["code"]]
        m = {"ES": es, "YM": ym, "CL": cl, "6E": e6, "6J": j6, "SPY": spy}[px_ref]
        prix = float(np.nanmedian(m.c[-500000:]))
        if px_ref == "6J":
            prix = float(np.nanmedian(m.c[-500000:]))
        c = criteres(x, d["temoin"], cout_bp(px_ref, prix, d["creux"]))
        res.append((d, c))
        pr(f"--- {d['code']} : {d['definition']}")
        pr(f"    sens prevu : {d['sens']} | {c['n']} cas | moyenne {c['moyenne']:+.2f} pb (t {c['t']:+.1f}) | 2016-2020 {c['m1']:+.2f} (t {c['t1']:+.1f})"
           f" | 2021-2026 {c['m2']:+.2f} (t {c['t2']:+.1f})")
        pr(f"    temoin {c['temoin']:+.2f} pb, Welch {c['welch']:+.1f} | cout aller-retour {c['cout']:.2f} pb -> net {c['net']:+.2f} pb, "
           f"sans les 3 meilleurs jours {c['sans3']:+.2f} pb" + (f" | annees nettes positives {c['part_annees']:.0%}" if c["rare"] else ""))
        if d.get("complement"):
            pr(f"    {d['complement']}")
        echecs = [k for k, v in c["tests"].items() if not v]
        pr(f"    VERDICT : {'PASSE - coder les regles' if c['passe'] else 'ECHOUE (' + ' ; '.join(echecs) + ')'}")
        if d["code"] in FAMILLES and not c["passe"]:
            pr(f"    -> famille eliminee selon la vue d ensemble (actif le mieux place) : {FAMILLES[d['code']]}")
        pr("")
    n_ok = sum(c["passe"] for _, c in res)
    pr(f"Bilan : {n_ok} anomalie(s) de niveau A sur {len(res)} passent tous les criteres.")
    pr(f"Calcul en {(datetime.now() - t0).total_seconds():.0f} s.")
    sortie = sortie or os.path.join(PY_DIR, "recherche", "resultats_60_niveau_A.txt")
    with open(sortie, "w", encoding="utf-8") as fh:
        fh.write("\n".join(L) + "\n")
    exporter("niveau_A", dict(lignes=[ligne_json(d, c, niveau="A", groupe="Niveau A et A contesté",
                                                 famille=FAMILLES.get(d["code"])) for d, c in res]))
    log("\n".join(L))
    return res


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--sortie", default=None)
    a = ap.parse_args(argv)
    etude(a.sortie)


if __name__ == "__main__":
    main()
