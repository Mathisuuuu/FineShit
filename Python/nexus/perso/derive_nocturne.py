"""Derive nocturne des futures sur indices americains : strategie construite de toutes pieces sur deux travaux de
chercheurs de la Federal Reserve Bank of New York (et de la Copenhagen Business School).

    python -m nexus.perso.derive_nocturne [--sortie resultats_derive_nocturne.txt]

PROTOCOLE ECRIT LE 2026-10-10, AVANT TOUT CALCUL SUR NOS DONNEES.

Sources
 [P1] N. Boyarchenko, L. C. Larsen & P. Whelan, « The Overnight Drift », Review of Financial Studies 36 (9), 2023,
      p. 3502-3547 (Federal Reserve Bank of New York Staff Report 917, fevrier 2020, revise en aout 2022). Faits repris :
      - l E-mini S&P 500 gagne l essentiel de son rendement entre 2:00 et 3:00 ET, a l ouverture des marches europeens :
        +3,7 % par an (1,48 pb par jour) sur 1998-2020, positif 20 annees sur 23 ;
      - mecanisme de stock des teneurs de marche (Grossman & Miller 1988) : le desequilibre d ordres de la derniere heure
        avant la pause, RSV_close = (achats - ventes) / (achats + ventes) de 15:15 a 16:15 ET, predit le rendement de la
        nuit avec un signe NEGATIF, surtout de 2:00 a 4:00 ET (et a l ouverture de Tokyo) ; reaction asymetrique, forte
        apres une vague de ventes, faible apres une vague d achats ; desequilibre proche de 0 : pas de prime ;
      - l effet croit avec le VIX : pour un desequilibre d un ecart-type (6,55 %), ~0 pb avec un VIX a 12, 2,6 pb a 20,
        6,1 pb a 30 ;
      - les semaines ou l ecart d heure Etats-Unis - Europe n est pas le meme que d habitude (changements d heure
        decales), la prevision disparait de la fenetre 2:00-3:00 ET ;
      - strategie « buy the dip » (BtD) : achat de l ES de 1:30 a 3:30 ET apres une cloture a RSV_close < 0 : Sharpe 1,8
        avant couts, 1,1 apres (2004-2020) ; l achat systematique de 2:00 a 3:00 ne survit pas aux couts (Sharpe -0,5).
 [P2] Memes auteurs, « The Disappearing Overnight Drift », Liberty Street Economics (Federal Reserve Bank of New York),
      1er juillet 2026. Faits repris :
      - la fenetre 2:00-3:00 est plate sur 2021-2025, pour l ES comme pour le NQ et le YM ;
      - des trois termes du modele (desequilibre en dollars x variance / capacite des teneurs de marche), seul le
        desequilibre a change : son ecart-type est passe de 6,5 % a 2,9 %, les journees de fort desequilibre sont devenues
        rares ; le VIX et la part du volume de nuit n ont presque pas change ;
      - prediction des auteurs : la derive revient si la dispersion des desequilibres s elargit de nouveau.
Lecture commune : selon P2, la prime n a pas disparu, c est sa cause (les gros desequilibres vendeurs a la cloture) qui
se fait rare. Une strategie coherente avec les deux papiers ne prend donc la nuit QU APRES un gros desequilibre vendeur
mesure sur une echelle absolue (et non renormalise par sa dispersion recente, ce qui ferait passer les petits desequilibres
d apres 2021 pour des gros), de preference quand le VIX est eleve.

Donnees
  Minutes ES, NQ, YM (Databento, 2016-2026), sans le cote de l agresseur : RSV approche par la classification par paquets
  de volume (BVC, Easley, Lopez de Prado & O Hara 2012), RSV_bvc = somme v (2 Phi(dP / s) - 1) / somme v sur les barres
  de 15:15 a 16:15 ET, s = ecart-type des variations 1 min de la meme fenetre sur les 20 seances precedentes.
  VIX : cloture officielle du CBOE (VIX_History.csv, gratuit), controlee par FRED (VIXCLS).

ETAPE 1 - l anomalie et son mecanisme sur nos donnees (aucune regle de trading)
  1a. rendement moyen de 2:00 a 3:00 ET par annee et par periode (2016-2020 / 2021-2026), ES, NQ, YM ; P2 predit ~0
      depuis 2021 ;
  1b. regression de ce rendement sur le RSV_bvc de la cloture precedente (pente negative attendue), puis avec le VIX et
      leur produit (equation 8 de P1) ; moyennes par quintile de RSV_bvc (asymetrie de P1) ;
  1c. dispersion du RSV_bvc par annee : P2 predit une compression apres 2020.
ETAPE 2 - strategie « rachat nocturne des gros desequilibres » (V2), regles figees, une seule version :
  - achat a 1:30 ET si, a la cloture de la seance americaine precedente, RSV_bvc <= -1 sigma_ref ET VIX >= 20 ; sortie a
    3:30 ET (fenetre de P1) ; pas de stop (P1 n en a pas) ;
  - sigma_ref = ecart-type de RSV_bvc sur TOUTES les seances precedentes depuis 2016 (fenetre croissante, 250 au moins) :
    echelle absolue et temps reel ; 1 sigma et VIX 20 = les reperes chiffres de P1 (choc d un ecart-type, VIX moyen
    19,8) ;
  - nuits exclues : changement d echeance dans la fenetre (conventions des 60 strategies) et semaines ou l ecart d heure
    New York - Francfort n est pas de 6 h (P1 : la prevision quitte alors cette fenetre).
  Rapportees a cote, sans optimisation : R0 = achat de 2:00 a 3:00 ET chaque nuit (l anomalie brute) ; V1 = BtD exact de
  P1 (RSV_bvc < 0, 1:30 -> 3:30). Temoin : la meme fenetre apres RSV_bvc > 0 (P1 : reaction faible).
  Replication : memes regles, sans retouche, sur NQ et YM (P2 : meme signature).
  Couts : 1 tick par cote + 2,50 $ de commission par cote (P1 : ecart achat-vente de 1 tick la nuit depuis 2004) ;
  stress a 2 ticks par cote (tableau de la vue d ensemble, heures creuses).
  Criteres : ceux des 60 strategies (t >= 3 ; meme signe et t >= 1,5 sur 2016-2020 et 2021-2026 ; Welch >= 2 contre le
  temoin ; net > 0 ; net > 0 sans les 3 meilleurs jours ; moins de 60 cas : t >= 2 et net positif >= 65 % des annees)
  ET Sharpe deflate >= 0,95 pour 36 essais (31 anomalies des 60 strategies, NQ 1 B et C, R0, V1, V2).
  Ce que P2 predit pour V2 : moins de signaux depuis 2021, mais un gain par signal qui reste positif. Un gain nul depuis
  2021 sur les seuls gros desequilibres contredirait l explication de P2.
"""
from __future__ import annotations

import argparse
import math
import os
from datetime import datetime

import numpy as np
import pandas as pd
from scipy.special import ndtr

from .alternatives import dsr
from .soixante import COMMISSION, COUTS, ET, PY_DIR, contrats, criteres, exporter, jours_ouvres_us, marche, tstat
from .soixante_bc import _rs

FRANCFORT = "Europe/Berlin"
FIN_DONNEES = pd.Timestamp("2026-08-28")
COUPURE = pd.Timestamp("2021-01-01")
FENETRE_RSV = (15 * 60 + 15, 16 * 60 + 15)          # minutes ET, debut et fin
K_SIGMA, VIX_MIN, N_REF_MIN, N_SIGMA_BARRE = 1.0, 20.0, 250, 20
N_ESSAIS, SEUIL_DSR = 36, 0.95
CACHE_FRED = os.path.join(PY_DIR, ".cache", "fred")


# =============================================================================
#  Donnees : VIX et RSV approche (BVC)
# =============================================================================
def vix() -> pd.Series:
    """Cloture officielle du VIX (CBOE), controlee par FRED (VIXCLS) sur les dates communes."""
    c = pd.read_csv(os.path.join(CACHE_FRED, "VIX_History.csv"))
    s = pd.Series(c["CLOSE"].to_numpy(float), index=pd.to_datetime(c["DATE"], format="%m/%d/%Y")).sort_index()
    f = os.path.join(CACHE_FRED, "VIXCLS.csv")
    if os.path.exists(f):
        d = pd.read_csv(f)
        d.columns = ["date", "v"]
        fr = pd.Series(pd.to_numeric(d.v, errors="coerce").to_numpy(), index=pd.to_datetime(d.date)).dropna()
        commun = s.index.intersection(fr.index)
        ecart = (s[commun] - fr[commun]).abs()
        s.attrs["controle"] = f"{len(commun)} dates communes CBOE / FRED, ecart max {ecart.max():.2f}, ecarts > 0,01 : {(ecart > 0.01).sum()}"
    return s


def rsv_bvc(m) -> pd.Series:
    """RSV de cloture approche par BVC, un par jour calendaire ET (barres commencant de 15:15 a 16:14 ET)."""
    sel = (m.tod > FENETRE_RSV[0]) & (m.tod <= FENETRE_RSV[1])
    idx = np.nonzero(sel)[0]
    idx = idx[idx > 0]
    cid = contrats(m)
    dp = m.c[idx] - m.c[idx - 1]
    dp[cid[idx] != cid[idx - 1]] = np.nan                           # pas de variation a travers un roulement
    df = pd.DataFrame({"jour": m.jour[idx], "dp": dp, "v": m.v[idx]})
    var_j = df.groupby("jour").dp.var()
    s = np.sqrt(var_j.rolling(N_SIGMA_BARRE, min_periods=10).mean().shift(1))     # 20 seances precedentes
    df["s"] = df.jour.map(s)
    z = np.where(df.s > 0, df.dp / df.s, np.nan)
    df["d"] = df.v * (2.0 * ndtr(z) - 1.0)
    ok = np.isfinite(df.d)
    g = df[ok].groupby("jour").agg(d=("d", "sum"), v=("v", "sum"), r=("dp", "size"))
    rsv = (g.d / g.v).where(g.r >= 50)                              # au moins 50 barres sur 60
    rsv.index = pd.to_datetime(rsv.index * 86_400_000_000_000)
    return rsv.rename("rsv")


def rendement_derniere_heure(m, jours) -> pd.Series:
    return _rs(m, jours, FENETRE_RSV[0], FENETRE_RSV[1], ET)


def ecart_francfort(jours: pd.DatetimeIndex) -> np.ndarray:
    """Ecart d heure Francfort - New York (heures) a 2:00 ET de chaque jour."""
    t = (pd.DatetimeIndex(jours) + pd.Timedelta(hours=2)).tz_localize(ET, nonexistent="shift_forward", ambiguous=False)
    return np.array([(x.tz_convert(FRANCFORT).utcoffset() - x.utcoffset()).total_seconds() / 3600 for x in t])


def nuits(m, v: pd.Series) -> pd.DataFrame:
    """Une ligne par nuit (jour calendaire du matin) : RSV et VIX de la cloture precedente, rendements des fenetres."""
    j = jours_ouvres_us(m)
    j = j[j <= FIN_DONNEES]
    rsv = rsv_bvc(m)
    prec = pd.DatetimeIndex(np.r_[np.datetime64("NaT"), j.values[:-1]])
    d = pd.DataFrame(index=j)
    d["veille"] = prec
    d["rsv"] = rsv.reindex(prec).to_numpy()
    d["vix"] = v.reindex(prec).to_numpy()
    d["r_heure"] = rendement_derniere_heure(m, prec.fillna(j[0])).to_numpy() * 1e4
    d["od"] = _rs(m, j, 2 * 60, 3 * 60, ET) * 1e4                  # anomalie brute (P1)
    d["btd"] = _rs(m, j, 90, 210, ET) * 1e4                         # fenetre BtD (P1), 1:30 -> 3:30
    d["decale"] = ecart_francfort(j) != 6
    d.loc[d.decale, ["od", "btd"]] = np.nan
    sig = d.rsv.expanding(min_periods=N_REF_MIN).std().shift(1)    # echelle absolue, temps reel
    d["sigma_ref"] = sig
    return d


# =============================================================================
#  Etape 1 : anomalie et mecanisme
# =============================================================================
def ols(y: pd.Series, X: pd.DataFrame) -> tuple[np.ndarray, np.ndarray]:
    """Coefficients et t (erreurs robustes de White)."""
    d = pd.concat([y.rename("y"), X], axis=1).dropna()
    A = np.column_stack([np.ones(len(d))] + [d[c].to_numpy() for c in X.columns])
    yv = d.y.to_numpy()
    b, *_ = np.linalg.lstsq(A, yv, rcond=None)
    e = yv - A @ b
    inv = np.linalg.inv(A.T @ A)
    cov = inv @ (A.T * e ** 2) @ A @ inv
    return b, b / np.sqrt(np.diag(cov))


def etape1(nom: str, d: pd.DataFrame, pr) -> dict:
    od = d.od
    p1, p2 = od[od.index < COUPURE], od[od.index >= COUPURE]
    pr(f"  {nom} - 1a. 2:00 -> 3:00 ET : {od.notna().sum()} nuits, {od.mean():+.2f} pb (t {tstat(od):+.1f}) = {od.mean() * 252 / 100:+.1f} % par an"
       f" | 2016-2020 {p1.mean():+.2f} (t {tstat(p1):+.1f}) | 2021-2026 {p2.mean():+.2f} (t {tstat(p2):+.1f})")
    an = od.groupby(od.index.year).agg(["mean", "count"])
    pr("      par annee (pb) : " + " ".join(f"{a}:{m:+.2f}" for a, (m, n) in an.iterrows()))
    res = {}
    for lib, sous in (("2016-2026", d), ("2016-2020", d[d.index < COUPURE]), ("2021-2026", d[d.index >= COUPURE])):
        b, t = ols(sous.od, sous[["rsv"]])
        b2, t2 = ols(sous.od, pd.DataFrame({"rsv": sous.rsv, "vix": sous.vix, "rsv_vix": sous.rsv * sous.vix}))
        sd = sous.rsv.std()
        eff = {v: -sd * (b2[1] + b2[3] * v) for v in (12, 20, 30)}
        pr(f"      1b. {lib} : pente du RSV {b[1]:+.1f} (t {t[1]:+.1f}) ; avec le VIX : RSV {b2[1]:+.1f} (t {t2[1]:+.1f}), "
           f"RSV x VIX {b2[3]:+.2f} (t {t2[3]:+.1f}) -> effet d un RSV a -1 ecart-type : " +
           ", ".join(f"VIX {v} : {e:+.2f} pb" for v, e in eff.items()))
        res[lib] = dict(pente=b[1], t=t[1], pente_vix=b2[3], t_vix=t2[3])
    q = pd.qcut(d.rsv, 5, labels=False)
    moy = d.od.groupby(q).agg(["mean", "count"])
    pr("      quintiles de RSV (du plus vendeur au plus acheteur) : " +
       " | ".join(f"Q{int(k) + 1} {m:+.2f} pb (t {tstat(d.od[q == k]):+.1f})" for k, (m, n) in moy.iterrows()))
    disp = d.rsv.groupby(d.index.year).std()
    pr("      1c. ecart-type du RSV_bvc par annee : " + " ".join(f"{a}:{s:.3f}" for a, s in disp.items()) +
       f" | 2016-2020 {d.rsv[d.index < COUPURE].std():.3f} -> 2021-2026 {d.rsv[d.index >= COUPURE].std():.3f}")
    pr(f"      controle du RSV approche : correlation avec le rendement de la meme heure {d.rsv.corr(d.r_heure):+.2f}")
    return res


# =============================================================================
#  Etape 2 : strategie
# =============================================================================
def cout_pb(root: str, prix: float, ticks: int) -> float:
    tick, pv, _, _ = COUTS[root]
    return (2 * ticks * tick + 2 * COMMISSION / pv) / prix * 1e4


def strategies(d: pd.DataFrame) -> dict:
    fort = (d.rsv <= -K_SIGMA * d.sigma_ref) & (d.vix >= VIX_MIN)
    return {"R0": dict(nom="R0 achat 2:00 -> 3:00 ET chaque nuit (anomalie brute)", serie=d.od, temoin=None),
            "V1": dict(nom="V1 BtD de P1 : 1:30 -> 3:30 ET apres RSV < 0", serie=d.btd[d.rsv < 0], temoin=d.btd[d.rsv > 0]),
            "V2": dict(nom="V2 rachat des gros desequilibres : RSV <= -1 sigma_ref et VIX >= 20", serie=d.btd[fort],
                       temoin=d.btd[d.rsv > 0])}


def juger(root: str, m, d: pd.DataFrame, pr) -> dict:
    prix = float(np.nanmedian(m.c[-500000:]))
    c1, c2 = cout_pb(root, prix, 1), cout_pb(root, prix, 2)
    out = {}
    for k, s in strategies(d).items():
        x = s["serie"].dropna()
        c = criteres(x, None if s["temoin"] is None else s["temoin"].dropna(), c1)
        net, ans = x - c1, (x.index.max() - x.index.min()).days / 365.25
        p_dsr = dsr(net, N_ESSAIS)
        sh = net.mean() / net.std(ddof=1) * math.sqrt(len(x) / ans) if len(x) > 2 else math.nan
        retenue = c["passe"] and p_dsr >= SEUIL_DSR
        n1, n2 = (x.index < COUPURE).sum(), (x.index >= COUPURE).sum()
        pr(f"  --- {root} {s['nom']}")
        pr(f"      {c['n']} nuits ({n1} en 2016-2020, {n2} en 2021-2026 ; {len(x) / ans:.0f} par an) | brut {c['moyenne']:+.2f} pb "
           f"(t {c['t']:+.1f}) | 2016-2020 {c['m1']:+.2f} (t {c['t1']:+.1f}) | 2021-2026 {c['m2']:+.2f} (t {c['t2']:+.1f})")
        pr(f"      temoin {c['temoin']:+.2f} pb, Welch {c['welch']:+.1f} | couts 1 tick {c1:.2f} pb -> net {c['net']:+.2f} pb, "
           f"sans les 3 meilleures nuits {c['sans3']:+.2f} pb | stress 2 ticks ({c2:.2f} pb) -> net {x.mean() - c2:+.2f} pb")
        pr(f"      Sharpe net annualise {sh:.2f} | Sharpe deflate ({N_ESSAIS} essais) {p_dsr:.2f}"
           + (f" | annees nettes positives {c['part_annees']:.0%}" if c["rare"] else ""))
        an = net.groupby(net.index.year).agg(["mean", "count"])
        pr("      net par annee (pb, nuits) : " + " ".join(f"{a}:{v:+.1f}({n})" for a, (v, n) in an.iterrows()))
        echecs = [t for t, ok in c["tests"].items() if not ok] + ([] if p_dsr >= SEUIL_DSR else [f"Sharpe deflate >= {SEUIL_DSR:.2f}"])
        pr(f"      VERDICT : {'RETENUE' if retenue else 'ECHOUE (' + ' ; '.join(echecs) + ')'}")
        out[k] = dict(c, dsr=p_dsr, sharpe_an=sh, retenue=retenue, cout1=c1, cout2=c2, n1=n1, n2=n2, serie=x,
                      echecs=echecs, nom=s["nom"])
    return out


def etude(sortie: str | None = None, log=print) -> dict:
    t0 = datetime.now()
    v = vix()
    L = []
    pr = L.append
    pr("=" * 118)
    pr(" DERIVE NOCTURNE DES FUTURES SUR INDICES : STRATEGIE CONSTRUITE SUR BOYARCHENKO, LARSEN & WHELAN (FED DE NEW YORK)")
    pr("=" * 118)
    pr("Protocole et sources : en-tete de nexus/perso/derive_nocturne.py (ecrit avant le calcul). Heures de New York (ET).")
    pr(f"VIX : CBOE, {v.attrs.get('controle', 'pas de controle FRED')}.\n")
    res = {}
    for root in ("ES", "NQ", "YM"):
        m = marche(root)
        d = nuits(m, v)
        pr(f"[{root}] {d.od.notna().sum()} nuits utilisables ({d.decale.sum()} exclues : ecart d heure New York - Francfort different de 6 h)")
        pr(" ETAPE 1 - l anomalie et son mecanisme")
        e1 = etape1(root, d, pr)
        pr(" ETAPE 2 - strategies (regles figees)")
        e2 = juger(root, m, d, pr)
        res[root] = dict(etape1=e1, etape2=e2, nuits=d)
        pr("")
    pr(f"Calcul en {(datetime.now() - t0).total_seconds():.0f} s.")
    sortie = sortie or os.path.join(PY_DIR, "recherche", "resultats_derive_nocturne.txt")
    with open(sortie, "w", encoding="utf-8") as fh:
        fh.write("\n".join(L) + "\n")
    exporter("derive_nocturne", dict(lignes=[
        dict(marche=r, code=k, nom=x["nom"], n=x["n"], n1=x["n1"], n2=x["n2"], moyenne=x["moyenne"], t=x["t"], t1=x["t1"],
             t2=x["t2"], welch=x["welch"], net=x["net"], sans3=x["sans3"], dsr=x["dsr"], sharpe_an=x["sharpe_an"],
             retenue=x["retenue"], echecs=x["echecs"])
        for r, v_ in res.items() for k, x in v_["etape2"].items()]))
    log("\n".join(L))
    return res


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--sortie", default=None)
    a = ap.parse_args(argv)
    etude(a.sortie)


if __name__ == "__main__":
    main()
