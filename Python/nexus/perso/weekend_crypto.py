"""Week-end crypto -> lundi des futures d indices (ES, replique NQ et YM).

    python -m nexus.perso.weekend_crypto [--sortie recherche/resultats_weekend_crypto.txt]

PROTOCOLE ECRIT LE 2026-10-19, AVANT TOUT CALCUL DEDIE (methode : memoire « methode-strategie-papiers »).
Piste 1 de recherche/pistes.md. Test AVEUGLE : aucun module de ce depot n a utilise la crypto comme signal pour les
indices ; P1 (cloud) a teste « lundi matin » et « week-end » avec le prix des futures seulement.

Sources. Textes complets inaccessibles sans franchir une verification anti-robots (HAL, SSRN, Napier, ScienceDirect) :
lecture du RESUME et des points cles publies seulement ([R]) ; les definitions ci-dessous sont donc MA lecture, au plus
simple, comme pour les 60 strategies.
 [MSS25] [R] M. Mourey, M. H. Shahrour, F. Soiman, « A crypto-stock weekend effect: Predicting Monday stock returns using
         weekend cryptocurrency returns », Finance Research Letters, 2025 (doi 10.1016/j.frl.2025.108661, HAL
         hal-05415054) : 20 grandes cryptomonnaies (85 % de la capitalisation), cadre bayesien et filtre de Kalman ; les
         rendements NEGATIFS du week-end predisent une baisse des actions le lundi, les positifs n ont pas d effet
         (asymetrie) ; robuste sur Nasdaq, Russell 2000, secteurs du S&P ; lien renforce apres l effondrement de LUNA
         (mai 2022) puis FTX (rupture confirmee par un HMM).
 [ADM25] [R] F. Ali, A. M. Du, M. A. Majeed, « Reevaluating intermarket connectedness: The impact of Monday return
         calculations on cryptocurrencies and traditional assets », Finance Research Letters 77, 2025 : CONTRE-PAPIER
         de methode ; le prix de reference du week-end (vendredi, samedi, dimanche, moyenne) change la taille et meme le
         sens des liens crypto -> S&P 500 (72 cryptos, 2018-2024) ; des choix « anodins » font les conclusions.
 [LY26]  [R] X. Li, J. Yuan, « Price Discovery When the Benchmark Is Closed: Evidence from 24/7 Perpetual Futures »,
         SSRN 7543402, 2026 : quand le marche de reference est ferme, un prix forme ailleurs pendant le week-end est
         repris a 70-90 % a la reouverture ; le reste est du bruit d un carnet mince.
 Mise en garde (presse specialisee, Kaiko cite par InvestingLive) : le volume crypto du week-end est faible et les
 ecarts plus larges, donc du bruit dans le signal.
Lecture commune : le week-end, la crypto est le seul grand marche ouvert ; les mauvaises nouvelles qu elle absorbe
(risque systemique, MSS25) doivent passer dans les actions a leur reouverture. Les futures CME rouvrent le DIMANCHE a
18:00 ET : l information est donc en grande partie dans le prix de reouverture (LY26 : 70-90 %). Le rendement « du
lundi » de MSS25 (cloture du vendredi -> cloture du lundi, a mon avis) contient ce saut, que personne ne peut capter.
La question tradable est de savoir s il reste une suite APRES la reouverture. ADM25 impose de figer les heures de
reference avant le calcul.

Donnees : BTC/USD 15 minutes (Alpaca, UTC, barres datees a leur fin, depuis 01/2021) : BTC seul, la plus grosse des
20 de MSS25 (environ la moitie de la capitalisation), pour eviter le bruit des petites cryptos ; futures Databento
ES, NQ, YM au prix ajuste des roulements (variation de points / prix reel d entree). Semaines retenues : vendredi ET
lundi ouvres a la NYSE (les week-ends de jours feries sont exclus). Prix crypto a une heure H = cloture de la derniere
barre finie au plus tard a H (60 min au plus tot) ; prix des futures a H = ouverture de la barre qui commence a H.

Heures de reference (figees ici, ADM25) : signal W = ln(BTC dimanche 18:00 ET / BTC vendredi 16:00 ET), du dernier prix
de la seance cash americaine a la reouverture du CME.

ETAPE 1 - l anomalie et ou elle passe (ES ; puis NQ, YM) :
  A1 (MSS25, anomalie brute) : rendement de ES du vendredi 16:00 au lundi 16:00 apres un week-end negatif (W < 0)
     contre positif ; pentes separees de ce rendement sur min(W, 0) et max(W, 0) (Newey-West) ; MSS25 predisent une
     pente positive sur la partie negative et nulle sur la partie positive.
  A2 (LY26, ou l information passe) : memes mesures sur trois morceaux : saut de reouverture (vendredi 16:00 ->
     dimanche 18:00), nuit (dimanche 18:00 -> lundi 9:30), seance (lundi 9:30 -> 16:00).
  Par moitie de l echantillon (avant / apres le 01/11/2023) et avant / apres LUNA (09/05/2022, prediction de MSS25).
ETAPE 2 - strategies (regles figees, nettes : 1 tick + 2,50 $ par cote et par contrat, stress 2 ticks) :
  - V  = vente de ES du dimanche 18:00 (reouverture) au lundi 16:00 quand W < 0, rien sinon ; c est la journee de
         lundi du CME (elle commence le dimanche a 18:00), donc compatible avec une prop firm intraday ;
  - R1 = la meme vente seulement pendant la seance cash du lundi (9:30 -> 16:00) ;
  - R0 = anomalie brute A1 jouee comme une strategie (vente du vendredi 16:00 au lundi 16:00 si W < 0) : NON
         executable (le signal n est connu que dimanche), reference de MSS25 seulement ;
  - temoin de V = la meme vente apres un week-end POSITIF (MSS25 : sans effet) ;
  - replique de V sur NQ (Nasdaq, teste par MSS25) et YM.
  Criteres (fixes avant le calcul) sur les rendements de V par trade, dans le sens vendeur : t >= 3 ; meme signe et
  t >= 1,5 sur chaque moitie (avant / apres le 01/11/2023) ; Welch >= 2 contre le temoin ; gain moyen net > 0 ; net > 0
  sans les 3 meilleurs trades ; ET Sharpe deflate >= 0,95 pour 375 essais (372 + V, R1, R0). Moins de 60 trades :
  t >= 2 et net positif au moins 65 % des annees.
"""
from __future__ import annotations

import argparse
import math
import os
from datetime import datetime

import numpy as np
import pandas as pd

from .alternatives import dsr
from .or_anomalies import instants
from .soixante import COMMISSION, COUTS, ET, PY_DIR, exporter, jours_ouvres_us, marche, prix_a, tstat

LUNA = pd.Timestamp("2022-05-09")
MOITIE = pd.Timestamp("2023-11-01")
N_ESSAIS, SEUIL_DSR = 375, 0.95
CRYPTO = os.path.normpath(os.path.join(PY_DIR, "..", "Cotations", "alpaca", "crypto_15min"))


# =============================================================================
#  Donnees
# =============================================================================
def crypto(sym: str = "BTCUSD") -> pd.Series:
    """Clotures 15 minutes, index = fin de barre en UTC naif."""
    d = pd.read_csv(os.path.join(CRYPTO, f"{sym}.csv"), parse_dates=[0], index_col=0)
    s = d["Close"].astype(float)
    return s[~s.index.duplicated(keep="last")].sort_index()


def prix_crypto(s: pd.Series, t_utc: np.ndarray, fraicheur_min: int = 60) -> np.ndarray:
    """Cloture de la derniere barre finie au plus tard a l instant (ns UTC), au plus `fraicheur_min` plus tot."""
    t = s.index.as_unit("ns").asi8
    k = np.searchsorted(t, t_utc, side="right") - 1
    ok = (k >= 0) & (t_utc - t[np.clip(k, 0, None)] <= fraicheur_min * 60_000_000_000)
    return np.where(ok, s.to_numpy()[np.clip(k, 0, None)], np.nan)


def semaines(jours_ouvres: pd.DatetimeIndex) -> pd.DataFrame:
    """Vendredis ouvres suivis d un lundi ouvre (week-ends sans jour ferie)."""
    js = set(pd.DatetimeIndex(jours_ouvres))
    ven = [d for d in jours_ouvres if d.dayofweek == 4 and (d + pd.Timedelta(days=3)) in js]
    v = pd.DatetimeIndex(ven)
    return pd.DataFrame(dict(vendredi=v, dimanche=v + pd.Timedelta(days=2), lundi=v + pd.Timedelta(days=3)), index=v + pd.Timedelta(days=3))


def prix_futures(m, jours: pd.DatetimeIndex, hh: int, mm: int) -> pd.DataFrame:
    p, i = prix_a(m, instants(jours, hh, mm, ET))
    off = np.where(i >= 0, m.offset[np.clip(i, 0, None)], np.nan)
    return pd.DataFrame({"adj": p, "reel": p - off}, index=jours)


def fenetres_futures(m, sem: pd.DataFrame) -> pd.DataFrame:
    """Rendements (variation de points ajustes / prix reel du debut) des morceaux du week-end, indexes par le lundi."""
    pts = {
        "ven16": prix_futures(m, pd.DatetimeIndex(sem["vendredi"]), 16, 0),
        "dim18": prix_futures(m, pd.DatetimeIndex(sem["dimanche"]), 18, 0),
        "lun930": prix_futures(m, pd.DatetimeIndex(sem["lundi"]), 9, 30),
        "lun16": prix_futures(m, pd.DatetimeIndex(sem["lundi"]), 16, 0),
    }
    for k in pts:
        pts[k].index = sem.index

    def r(a, b):
        return (pts[b]["adj"] - pts[a]["adj"]) / pts[a]["reel"]
    return pd.DataFrame(dict(total=r("ven16", "lun16"), saut=r("ven16", "dim18"), nuit=r("dim18", "lun930"),
                             seance=r("lun930", "lun16"), V=r("dim18", "lun16"), prix=pts["dim18"]["reel"],
                             prix930=pts["lun930"]["reel"], prix_ven=pts["ven16"]["reel"]))


def signal_weekend(sem: pd.DataFrame, s: pd.Series) -> pd.Series:
    """W = ln(BTC dimanche 18:00 ET / BTC vendredi 16:00 ET)."""
    a = prix_crypto(s, instants(pd.DatetimeIndex(sem["vendredi"]), 16, 0, ET))
    b = prix_crypto(s, instants(pd.DatetimeIndex(sem["dimanche"]), 18, 0, ET))
    return pd.Series(np.log(b / a), index=sem.index, name="W")


def cout_ar(root: str, prix: pd.Series, ticks: float = 1.0) -> pd.Series:
    """Aller-retour (fraction du notionnel) : 2 x (ticks x tick + commission / valeur du point) / prix."""
    tick, pv, _, _ = COUTS[root]
    return 2 * (ticks * tick + COMMISSION / pv) / prix


# =============================================================================
#  Statistiques
# =============================================================================
def pentes(y: pd.Series, w: pd.Series) -> dict:
    """y = a + b- min(W, 0) + b+ max(W, 0), erreurs de Newey-West (4 retards)."""
    import statsmodels.api as sm
    d = pd.concat([y.rename("y"), w.rename("w")], axis=1).dropna()
    X = sm.add_constant(np.column_stack([np.minimum(d["w"], 0), np.maximum(d["w"], 0)]))
    m = sm.OLS(d["y"].to_numpy(), X).fit(cov_type="HAC", cov_kwds={"maxlags": 4})
    return dict(n=len(d), b_neg=float(m.params[1]), t_neg=float(m.tvalues[1]), b_pos=float(m.params[2]), t_pos=float(m.tvalues[2]))


def welch(a: pd.Series, b: pd.Series) -> float:
    a, b = a.dropna(), b.dropna()
    se = math.sqrt(a.var(ddof=1) / len(a) + b.var(ddof=1) / len(b))
    return float((a.mean() - b.mean()) / se) if se > 0 else math.nan


def criteres_v(brut: pd.Series, temoin: pd.Series, cout: pd.Series) -> dict:
    """Criteres de la methode, periodes = moities de l echantillon crypto (avant / apres MOITIE)."""
    x = brut.dropna()
    c = cout.reindex(x.index)
    net = x - c
    n = len(x)
    p1, p2 = x[x.index < MOITIE], x[x.index >= MOITIE]
    t, t1, t2 = tstat(x), tstat(p1), tstat(p2)
    w = welch(x, temoin)
    sans3 = net.drop(net.nlargest(3).index).mean() if n > 3 else math.nan
    annees = net.groupby(net.index.year).sum()
    part = float((annees > 0).mean()) if len(annees) else math.nan
    if n < 60:
        tests = {"t >= 2 (evenement rare)": t >= 2, "gain net positif >= 65 % des annees": part >= 0.65,
                 "t de Welch >= 2 contre le temoin": w >= 2, "gain net > 0 sans les 3 meilleurs trades": sans3 > 0}
    else:
        tests = {"t >= 3": t >= 3, "meme signe et t >= 1,5 sur chaque moitie": t1 >= 1.5 and t2 >= 1.5,
                 "t de Welch >= 2 contre le temoin": w >= 2, "gain moyen net > 0": net.mean() > 0,
                 "gain net > 0 sans les 3 meilleurs trades": sans3 > 0}
    return dict(n=n, moyenne=x.mean() * 1e4, t=t, m1=p1.mean() * 1e4, t1=t1, m2=p2.mean() * 1e4, t2=t2,
                temoin=temoin.mean() * 1e4, welch=w, cout=c.mean() * 1e4, net=net.mean() * 1e4, sans3=sans3 * 1e4,
                part_annees=part, tests=tests, passe=all(tests.values()))


def serie_quotidienne(trades: pd.Series, jours: pd.DatetimeIndex) -> pd.Series:
    """Rendement net de chaque trade porte au jour de sa sortie, zero les autres seances (pour le Sharpe deflate)."""
    return trades.reindex(jours).fillna(0.0)


def resume(nom: str, net: pd.Series, jours: pd.DatetimeIndex, pr) -> dict:
    x = net.dropna()
    q = serie_quotidienne(x, jours)
    with np.errstate(all="ignore"):
        sh = float(q.mean() / q.std(ddof=1) * math.sqrt(252)) if q.std() > 0 else math.nan
    import vectorbt as vbt  # noqa: F401  (accesseur .vbt)
    st = q.vbt.returns(freq="1D", year_freq="252 days")
    d = dict(nom=nom, n=len(x), moyenne=x.mean() * 1e4, t=tstat(x), t1=tstat(x[x.index < MOITIE]),
             t2=tstat(x[x.index >= MOITIE]), sharpe=sh, perte_max=float(-st.max_drawdown()), total=float((1 + x).prod() - 1),
             apres_luna=x[x.index >= LUNA].mean() * 1e4, avant_luna=x[x.index < LUNA].mean() * 1e4, dsr=dsr(q, N_ESSAIS))
    pr(f"  {nom:<46} {d['n']:4d} trades | net {d['moyenne']:+7.2f} pb (t {d['t']:+.2f}) | moities t {d['t1']:+.2f} / "
       f"{d['t2']:+.2f} | avant / apres LUNA {d['avant_luna']:+6.1f} / {d['apres_luna']:+6.1f} pb | Sharpe {sh:+.2f} | "
       f"perte max {d['perte_max']:.1%} | total {d['total']:+.1%}")
    return d


# =============================================================================
#  Etude
# =============================================================================
def etude(sortie: str | None = None, log=print) -> dict:
    t0 = datetime.now()
    L = []
    pr = L.append
    pr("=" * 118)
    pr(" WEEK-END CRYPTO -> LUNDI DES FUTURES D INDICES (MOUREY, SHAHROUR & SOIMAN 2025) : ES, REPLIQUE NQ ET YM")
    pr("=" * 118)
    pr("Protocole et sources : en-tete de nexus/perso/weekend_crypto.py (ecrit avant le calcul). Signal W = ln(BTC dim. 18:00 /")
    pr("BTC ven. 16:00), heure de New York. Rendements des futures en pb.")
    btc = crypto("BTCUSD")
    m = marche("ES")
    jours = jours_ouvres_us(m)
    jours = jours[(jours >= btc.index[0].normalize() + pd.Timedelta(days=3)) & (jours <= "2026-08-28")]
    sem = semaines(jours)
    W = signal_weekend(sem, btc)
    f = fenetres_futures(m, sem)
    ok = W.notna() & f[["total", "saut", "nuit", "seance", "V"]].notna().all(axis=1)
    sem, W, f = sem[ok], W[ok], f[ok]
    neg = W < 0
    pr(f"Semaines retenues : {len(W)} (week-ends negatifs : {int(neg.sum())}, positifs : {int((~neg).sum())}) ; "
       f"{sem.index[0]:%d/%m/%Y} -> {sem.index[-1]:%d/%m/%Y}")

    # ---------------------------------------------------------------- ETAPE 1
    pr("")
    pr("ETAPE 1 - A1 / A2 : rendement de ES apres un week-end negatif ou positif, et pentes sur W (Newey-West)")
    a12 = {}
    for col, titre in (("total", "A1 vendredi 16:00 -> lundi 16:00"), ("saut", "A2 saut de reouverture (ven. 16 -> dim. 18)"),
                       ("nuit", "A2 nuit (dim. 18 -> lun. 9:30)"), ("seance", "A2 seance (lun. 9:30 -> 16:00)")):
        y = f[col]
        p = pentes(y, W)
        a12[col] = dict(p, neg=y[neg].mean() * 1e4, pos=y[~neg].mean() * 1e4, welch=welch(y[neg], y[~neg]))
        pr(f"  {titre:<44} apres W<0 {y[neg].mean() * 1e4:+7.2f} pb, apres W>0 {y[~neg].mean() * 1e4:+7.2f} pb "
           f"(Welch {welch(y[neg], y[~neg]):+.2f}) | pente partie negative {p['b_neg']:+.3f} (t {p['t_neg']:+.2f}), "
           f"positive {p['b_pos']:+.3f} (t {p['t_pos']:+.2f})")
    for per, sel in (("avant LUNA", W.index < LUNA), ("apres LUNA", W.index >= LUNA), ("1re moitie", W.index < MOITIE),
                     ("2e moitie", W.index >= MOITIE)):
        p = pentes(f["total"][sel], W[sel])
        pv = pentes(f["V"][sel], W[sel])
        pr(f"    {per:<11} (n {p['n']:3d}) : A1 pente partie negative {p['b_neg']:+.3f} (t {p['t_neg']:+.2f}) ; "
           f"apres la reouverture (dim. 18 -> lun. 16) {pv['b_neg']:+.3f} (t {pv['t_neg']:+.2f})")

    # ---------------------------------------------------------------- ETAPE 2
    pr("")
    pr("ETAPE 2 - strategies nettes (vente si W < 0 ; 1 tick + 2,50 $ par cote)")
    c_es = cout_ar("ES", f["prix"])
    strat = {}
    brut_V = -f["V"][neg]
    strat["V"] = resume("V   vente dim. 18:00 -> lun. 16:00 si W < 0", brut_V - c_es[neg], jours, pr)
    strat["V2"] = resume("V   couts 2 ticks", brut_V - cout_ar("ES", f["prix"], 2.0)[neg], jours, pr)
    brut_T = -f["V"][~neg]
    strat["T"] = resume("temoin : meme vente apres W > 0", brut_T - c_es[~neg], jours, pr)
    strat["R1"] = resume("R1  vente lun. 9:30 -> 16:00 si W < 0", -f["seance"][neg] - cout_ar("ES", f["prix930"])[neg], jours, pr)
    strat["R0"] = resume("R0  vente ven. 16:00 -> lun. 16:00 (non executable)", -f["total"][neg] - cout_ar("ES", f["prix_ven"])[neg],
                         jours, pr)
    for root in ("NQ", "YM"):
        mm = marche(root)
        ff = fenetres_futures(mm, sem)
        x = (-ff["V"][neg] - cout_ar(root, ff["prix"])[neg]).dropna()
        strat[root] = resume(f"replique de V sur {root}", x, jours, pr)

    # ---------------------------------------------------------------- criteres
    pr("")
    c = criteres_v(brut_V, brut_T, c_es[neg])
    d = strat["V"]["dsr"]
    pr(f"CRITERES (V, {c['n']} trades ; cout moyen {c['cout']:.2f} pb) : brut {c['moyenne']:+.2f} pb (t {c['t']:+.2f}) | "
       f"1re moitie {c['m1']:+.2f} (t {c['t1']:+.2f}) | 2e moitie {c['m2']:+.2f} (t {c['t2']:+.2f}) | temoin {c['temoin']:+.2f} "
       f"(Welch {c['welch']:+.2f}) | net {c['net']:+.2f} | net sans 3 meilleurs {c['sans3']:+.2f}")
    for k, v in c["tests"].items():
        pr(f"  [{'x' if v else ' '}] {k}")
    pr(f"  [{'x' if d >= SEUIL_DSR else ' '}] Sharpe deflate >= {SEUIL_DSR} pour {N_ESSAIS} essais : {d:.2f}")
    passe = c["passe"] and d >= SEUIL_DSR
    pr(f"VERDICT : {'RETENUE' if passe else 'REJETEE'}")
    texte = "\n".join(L)
    sortie = sortie or os.path.join(PY_DIR, "recherche", "resultats_weekend_crypto.txt")
    with open(sortie, "w", encoding="utf-8") as fh:
        fh.write(texte + f"\n(calcule en {(datetime.now() - t0).seconds} s le {datetime.now():%Y-%m-%d %H:%M})\n")
    echecs = [k for k, v in c["tests"].items() if not v] + ([] if d >= SEUIL_DSR else [f"Sharpe deflate >= {SEUIL_DSR}"])
    lignes = [dict(code=k, nom=v["nom"].strip(), n=v["n"], moyenne=v["moyenne"], t=v["t"], t1=v["t1"], t2=v["t2"],
                   temoin=c["temoin"] if k == "V" else None, welch=c["welch"] if k == "V" else None,
                   sharpe_an=v["sharpe"], dsr=v["dsr"]) for k, v in strat.items()]
    exporter("weekend_crypto", dict(
        titre="Week-end crypto -> lundi des futures d indices (Mourey, Shahrour & Soiman 2025)",
        sous=f"Signal : BTC du vendredi 16:00 au dimanche 18:00 ET ; vente si negatif. Net en pb par trade ; moities avant / "
             f"apres le 01/11/2023 ; 2021-2026 ; {N_ESSAIS} essais. Papiers lus en resume seulement (textes bloques).",
        lignes=lignes, echecs=echecs, retenue=passe, criteres=c, dsr=d, n_essais=N_ESSAIS, etape1=a12))
    log(texte)
    return dict(criteres=c, dsr=d, passe=passe, strategies=strat, etape1=a12)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--sortie")
    a = ap.parse_args(argv)
    etude(a.sortie)


if __name__ == "__main__":
    main()
