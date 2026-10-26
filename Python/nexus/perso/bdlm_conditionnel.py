"""BDLM 2021 conditionne au gamma des dealers : implementation de la specification
C:\\Users\\Mathis\\Documents\\arbres\\market-intraday-momentum\\strategie_BDLM_conditionnelle.md (variantes V0 a V4).

    python -m nexus.perso.bdlm_conditionnel [--sortie resultats_bdlm_conditionnel.txt]

PROTOCOLE ECRIT LE 2026-10-12, AVANT LE CALCUL DE CE MODULE. Il reprend la specification telle quelle ; les ecarts
imposes par nos donnees sont listes ci-dessous. Sources lues : celles de nexus/perso/gamma_intraday.py (BDLM21 en
texte complet, SqueezeMetrics 2017, Dim-Eraker-Vilkov 2024, Willeboordse 2026, etc.) ; dates des SPXW du mardi et du
jeudi : communiques Cboe du 13/04/2022 (mardi des le 18/04/2022, jeudi des le 11/05/2022).

TEST NON AVEUGLE, annonce avant le calcul : V0 a ete mesuree dans les 60 strategies (« ES 5 ») et une version tres
proche de V1 (R0 de gamma_intraday.py, signal et entree au meme prix de 15h30, couts 1 tick par cote) a donne sur
2016-2026 : +7,02 pb net par trade, t 2,28, Sharpe net 0,71. Ce module ne peut donc pas confirmer V1 de facon
independante : il applique la specification et donne les statistiques qu elle demande.

Donnees et definitions (specification, section 2)
  ES, minutes Databento, contrat continu « .v.0 » = roulement au croisement des volumes (comme le papier), prix REELS.
  Nos barres sont horodatees a leur FIN, en heure de New York.
  P_c(t)   = cloture de la barre finissant a 16h00 (dernier prix <= 15:59:59) ;
  signal   = cloture de la barre finissant a 15h30 (dernier prix <= 15:29:59) ;
  entree   = ouverture de la barre finissant a 15h31 (premier prix >= 15:30:00) : jamais le meme prix que le signal ;
  sortie   = P_c(t), 16h00 precises (pas de prolongation jusqu a 16h15) ;
  r_ROD(t) = signal / P_c(t-1) - 1 ; r_LH(t) = P_c(t) / P(15:30) - 1 (regressions) ; trade = sortie / entree - 1.
  Jours exclus : non ouvres, seances courtes (pas de barre a 16h00 le jour t ou la veille), volume 9h30-16h00 < 100
  contrats, changement d echeance entre deux prix utilises (meme contrat exige).
  NGE : GEX quotidien de SqueezeMetrics (source du papier apres 2017), valeur datee de la veille (NGE_{t-1}, Table 7).
  Seul le signe sert aux regles binaires ; pour V2, NGE = GEX / niveau du S&P 500 (proxy de GEX / capitalisation :
  le diviseur de l indice varie lentement ; les coefficients etant reestimes, l echelle est sans effet).

Ecarts a la specification imposes par nos donnees (annonces avant le calcul)
  - Etalonnage : la specification demande 01/1996-05/2020 ; nos minutes ES commencent en 2016. Etalonnage sur le
    recouvrement 01/2016-05/2020 seulement (4,4 ans au lieu de 24) : le critere « beta conditionnel a +-30 % de la
    Table 7 » y est fragile. ES 2010-2015 existe chez Databento (payant, avec accord).
  - Variantes de NGE (SPX seul, SPX + SPXW, + SPY) : impossibles, nous n avons que la serie agregee de SqueezeMetrics.
  - V4 (filtre LETF) : NAV et encours quotidiens des LETF non disponibles gratuitement sur 2016-2026 : non testee.
  - Test vega de Willeboordse (2026) : impossible sans donnees d options.

Phases : etalonnage 2016-01-04 -> 2020-05-29 ; OOS 1 2020-06-01 -> 2022-05-10 ; OOS 2 (ere 0DTE) 2022-05-11 -> fin.

Variantes (section 5)
  V0 = signe(r_ROD) tous les jours (reference ; deja comptee dans les 60 strategies) ;
  V1 = signe(r_ROD) si NGE_{t-1} < 0, sinon pas de position (coeur de l hypothese) ;
  V2 = version continue : r_LH = a + b r_ROD + c NGE r_ROD + d NGE estimee en fenetre expansive (>= 500 jours passes),
       prevision f_t ; position = f_t / ecart-type des previsions passees, bornee a +-2 contrats [CHOIX de ce module] ;
  V3 = -signe(r_ROD) si NGE_{t-1} > 0, sinon pas de position (retournement seul, hypothese de Dim et al. 2024) ;
  V4 = non testee (donnees).
Couts (section 6) : base 1 tick ALLER-RETOUR (12,50 $) + 2 x 2,50 $ de commission ; stress 1 tick PAR COTE + 5 $.

Statistiques (section 7), par phase : betas conditionnels (Newey-West 5) ; interaction 1[NGE<0] r_ROD ; R2 hors
echantillon en fenetre expansive (>= 500 jours) avec test de Clark-West, contre la moyenne historique, pour le modele
inconditionnel et le modele conditionnel ; part des jours NGE < 0 par annee ; par variante : trades, trades par an,
taux de succes, rendement brut et net, Sharpe brut et net (serie quotidienne, jours sans position = 0) ; p-values
corrigees de Holm sur V0-V3 (test unilateral : rendement net moyen > 0).
Critere d invalidation de H2 (specification) : sur OOS 2, interaction t < 2 ou de signe oppose, OU Sharpe net de V1
< 0,3. Criteres de la methode en plus, sur V1 : t >= 3 ; meme signe et t >= 1,5 sur 2016-2020 et 2021-2026 ; Welch >= 2
contre V0 ; net > 0 ; net > 0 sans les 3 meilleurs jours ; Sharpe deflate >= 0,95 pour 58 essais (55 + V1, V2, V3).
Compatibilite prop firm : 30 minutes, fermee a 16h00 ET : COMPATIBLE intraday.
"""
from __future__ import annotations

import argparse
import math
import os
from datetime import datetime

import numpy as np
import pandas as pd
from scipy import stats

from .alternatives import dsr
from .gamma_intraday import gex, gex_veille, ols_nw
from .soixante import COMMISSION, COUTS, PY_DIR, contrats, criteres, exporter, jours_ouvres_us, marche, tstat

PHASES = (("etalonnage 2016-01 -> 2020-05", "2016-01-01", "2020-05-29"),
          ("OOS 1 2020-06 -> 2022-05-10", "2020-06-01", "2022-05-10"),
          ("OOS 2 ere 0DTE 2022-05-11 ->", "2022-05-11", "2099-01-01"))
TABLE7 = {"neg": (6.63, 4.78), "pos": (0.82, 1.03)}                      # beta x100 et t de la Table 7 (1996-2020)
MIN_FENETRE = 500
N_ESSAIS, SEUIL_DSR = 58, 0.95


# =============================================================================
#  Prix et fenetres
# =============================================================================
def barres_par_minute(m, jours: pd.DatetimeIndex, tod: int) -> np.ndarray:
    """Indice de la barre finissant a la minute ET `tod` de chaque jour (-1 si absente)."""
    cle = m.jour * 1440 + m.tod
    ordre = np.argsort(cle, kind="stable")
    cherche = (jours.asi8 // 86_400_000_000_000) * 1440 + tod
    k = np.searchsorted(cle[ordre], cherche)
    k = np.clip(k, 0, len(ordre) - 1)
    trouve = cle[ordre][k] == cherche
    return np.where(trouve, ordre[k], -1)


def volume_seance(m, jours: pd.DatetimeIndex) -> np.ndarray:
    """Volume 9h30-16h00 ET de chaque jour."""
    sel = (m.tod > 570) & (m.tod <= 960)
    v = pd.Series(m.v[sel]).groupby(m.jour[sel]).sum()
    return v.reindex(jours.asi8 // 86_400_000_000_000).fillna(0).to_numpy()


def fenetres(m) -> pd.DataFrame:
    """r_ROD, r_LH, rendement du trade (entree 15:30:00, sortie 16h00), par jour ouvre retenu."""
    j = jours_ouvres_us(m)
    i16, i1530, i1531 = (barres_par_minute(m, j, t) for t in (960, 930, 931))
    i16_veille = np.r_[-1, i16[:-1]]
    cid = contrats(m)
    rc = np.where(np.isfinite(m.rc) & (m.rc > 0), m.rc, np.nan)
    ouv = m.o - m.offset if hasattr(m, "offset") else m.o
    ok = (i16 >= 0) & (i1530 >= 0) & (i1531 >= 0) & (i16_veille >= 0) & (volume_seance(m, j) >= 100)
    idx = [np.clip(a, 0, None) for a in (i16, i1530, i1531, i16_veille)]
    meme = (cid[idx[0]] == cid[idx[1]]) & (cid[idx[1]] == cid[idx[2]]) & (cid[idx[2]] == cid[idx[3]])
    ok &= meme
    p16, p1530, e1530, p16v = rc[idx[0]], rc[idx[1]], ouv[idx[2]], rc[idx[3]]
    d = pd.DataFrame({"rod": p1530 / p16v - 1, "lh": p16 / p1530 - 1, "trade": p16 / e1530 - 1, "prix": p16}, index=j)
    return d[ok].dropna()


# =============================================================================
#  Statistiques
# =============================================================================
def r2_oos(y: np.ndarray, X: np.ndarray, debut: int = MIN_FENETRE) -> tuple[np.ndarray, np.ndarray]:
    """Previsions en fenetre expansive (modele X et moyenne historique), a partir de l observation `debut`."""
    n = len(y)
    f_mod, f_moy = np.full(n, np.nan), np.full(n, np.nan)
    for t in range(debut, n):
        b, *_ = np.linalg.lstsq(X[:t], y[:t], rcond=None)
        f_mod[t] = X[t] @ b
        f_moy[t] = y[:t].mean()
    return f_mod, f_moy


def clark_west(y, f_mod, f_moy) -> tuple[float, float]:
    """R2 hors echantillon et t de Clark-West (unilateral : le modele bat la moyenne historique)."""
    ok = np.isfinite(f_mod)
    y, a, b = y[ok], f_mod[ok], f_moy[ok]
    if len(y) < 30:
        return math.nan, math.nan
    r2 = 1 - np.sum((y - a) ** 2) / np.sum((y - b) ** 2)
    f = (y - b) ** 2 - ((y - a) ** 2 - (b - a) ** 2)
    return float(r2), float(f.mean() / (f.std(ddof=1) / math.sqrt(len(f))))


def holm(p: dict) -> dict:
    """p-values corrigees de Holm."""
    cles = sorted(p, key=lambda k: p[k])
    out, mx = {}, 0.0
    for r, k in enumerate(cles):
        mx = max(mx, min(1.0, (len(cles) - r) * p[k]))
        out[k] = mx
    return out


def positions(f: pd.DataFrame) -> pd.DataFrame:
    """V0, V1, V3 (+1/-1/0) et V2 (continue, bornee a +-2)."""
    s = np.sign(f.rod)
    neg, pos = f.nge < 0, f.nge > 0
    out = pd.DataFrame({"V0": s, "V1": s.where(neg, 0.0), "V3": (-s).where(pos, 0.0)}, index=f.index)
    x = f.nge / f.prix_spx / 1e6
    X = np.c_[np.ones(len(f)), f.rod * 1e4, x * f.rod * 1e4, x]
    prev, _ = r2_oos(f.lh.to_numpy() * 1e4, X)
    prev = pd.Series(prev, index=f.index)
    sd = prev.expanding(min_periods=60).std().shift(1)
    out["V2"] = (prev / sd).clip(-2, 2).fillna(0.0)
    return out


def couts_pb(prix: float, ticks_aller_retour: float) -> float:
    tick, pv = COUTS["ES"][0], COUTS["ES"][1]
    return (ticks_aller_retour * tick + 2 * COMMISSION / pv) / prix * 1e4


# =============================================================================
#  Etude
# =============================================================================
def etude(sortie: str | None = None, log=print) -> dict:
    t0 = datetime.now()
    L = []
    pr = L.append
    pr("=" * 118)
    pr(" BDLM 2021 CONDITIONNE AU GAMMA DES DEALERS : SPECIFICATION arbres/market-intraday-momentum/strategie_BDLM_conditionnelle.md")
    pr("=" * 118)
    pr("Protocole : en-tete de nexus/perso/bdlm_conditionnel.py. TEST NON AVEUGLE (V0 = ES 5 ; V1 tres proche de R0 de gamma_intraday).\n")
    g = gex()
    spx = pd.read_csv(os.path.join(PY_DIR, ".cache", "gex", "DIX.csv"), parse_dates=["date"]).set_index("date")["price"]
    es = marche("ES")
    f = fenetres(es)
    f["nge"] = gex_veille(g, f.index)
    f["prix_spx"] = gex_veille(spx, f.index)
    f = f.dropna()
    phases = {lib: (f.index >= a) & (f.index <= b) for lib, a, b in PHASES}
    pr(f"Jours retenus : {len(f)} ({f.index[0].date()} -> {f.index[-1].date()}).")

    pr("\n1. Etalonnage et betas conditionnels (x100, t de Newey-West 5 retards)")
    etal = {}
    for lib, sel in phases.items():
        x = f[sel]
        y, r = x.lh.to_numpy() * 1e4, x.rod.to_numpy() * 1e4
        neg = (x.nge < 0).to_numpy()
        b0, t0_ = ols_nw(y, np.c_[np.ones(len(y)), r])
        bn, tn = ols_nw(y[neg], np.c_[np.ones(neg.sum()), r[neg]])
        bp, tp = ols_nw(y[~neg], np.c_[np.ones((~neg).sum()), r[~neg]])
        bi, ti = ols_nw(y, np.c_[np.ones(len(y)), r, neg * r])
        etal[lib] = dict(n=len(x), part_neg=float(neg.mean()), b_inc=b0[1] * 100, t_inc=t0_[1], b_neg=bn[1] * 100, t_neg=tn[1],
                         n_neg=int(neg.sum()), b_pos=bp[1] * 100, t_pos=tp[1], b_int=bi[2] * 100, t_int=ti[2])
        e = etal[lib]
        pr(f"  {lib} : {e['n']} jours, NGE<0 {e['part_neg']:.0%} | inconditionnel {e['b_inc']:+.2f} (t {e['t_inc']:+.2f}) | "
           f"NGE<0 {e['b_neg']:+.2f} (t {e['t_neg']:+.2f}, {e['n_neg']} j) | NGE>=0 {e['b_pos']:+.2f} (t {e['t_pos']:+.2f}) | "
           f"interaction {e['b_int']:+.2f} (t {e['t_int']:+.2f})")
    e = etal[PHASES[0][0]]
    ok_neg = e["b_neg"] > 0 and abs(e["b_neg"] / TABLE7["neg"][0] - 1) <= 0.30
    ok_pos = abs(e["b_pos"] - TABLE7["pos"][0]) <= 0.30 * abs(TABLE7["pos"][0]) or (abs(e["t_pos"]) < 2 and abs(TABLE7["pos"][1]) < 2)
    pr(f"  Critere d etalonnage (+-30 % de la Table 7 : NGE<0 6,63 t 4,78 ; NGE>=0 0,82 t 1,03) : NGE<0 "
       f"{'CONFORME' if ok_neg else 'NON CONFORME'} ({e['b_neg']:+.2f}) ; NGE>=0 {'conforme (non significatif des deux cotes)' if ok_pos else 'NON CONFORME'}")
    covid = (f.index >= "2020-02-15") & (f.index <= "2020-04-30")
    x = f[phases[PHASES[0][0]] & ~covid]
    neg = (x.nge < 0).to_numpy()
    bn, tn = ols_nw(x.lh.to_numpy()[neg] * 1e4, np.c_[np.ones(neg.sum()), x.rod.to_numpy()[neg] * 1e4])
    pr(f"  Diagnostic (pas un reglage) : etalonnage hors 15/02-30/04/2020 : NGE<0 {bn[1] * 100:+.2f} (t {tn[1]:+.2f}, {neg.sum()} j)")
    pr("  Diagnostic signe du NGE : SqueezeMetrics compte les calls en gamma long et les puts en gamma court pour les teneurs "
       "de marche, comme les eq. (13)-(14) du papier ; amplitude moyenne |r_LH| NGE<0 / NGE>=0 : "
       f"{np.abs(f.lh[f.nge < 0]).mean() * 1e4:.1f} / {np.abs(f.lh[f.nge >= 0]).mean() * 1e4:.1f} pb.")
    parts = (f.nge < 0).groupby(f.index.year).mean()
    pr("  Part des jours NGE<0 par annee : " + " | ".join(f"{a} {p:.0%}" for a, p in parts.items()))

    pr("\n2. R2 hors echantillon (fenetre expansive, >= 500 jours ; Clark-West unilateral)")
    y = f.lh.to_numpy() * 1e4
    r = f.rod.to_numpy() * 1e4
    neg = (f.nge < 0).to_numpy()
    mods = {"inconditionnel": np.c_[np.ones(len(y)), r], "conditionnel": np.c_[np.ones(len(y)), r, neg * r]}
    prev = {k: r2_oos(y, X) for k, X in mods.items()}
    r2tab = {}
    for lib, sel in phases.items():
        s = sel.to_numpy() if hasattr(sel, "to_numpy") else sel
        parts_ = []
        for k, (fm, fh) in prev.items():
            r2, cw = clark_west(y[s], fm[s], fh[s])
            r2tab[(lib, k)] = (r2, cw)
            parts_.append(f"{k} R2 {r2 * 100:+.2f} % (CW t {cw:+.2f})")
        pr(f"  {lib} : " + " | ".join(parts_))

    pr("\n3. Variantes (1 contrat ; base = 1 tick aller-retour + 5 $ ; stress = 1 tick par cote + 5 $)")
    pos = positions(f)
    prix = float(np.nanmedian(es.rc[-500000:]))
    c_base, c_stress = couts_pb(prix, 1), couts_pb(prix, 2)
    pr(f"  cout par contrat aller-retour : base {c_base:.2f} pb, stress {c_stress:.2f} pb")
    tr = f.trade * 1e4
    res, pval = {}, {}
    for v in ("V0", "V1", "V2", "V3"):
        w = pos[v]
        brut = w * tr
        net = brut - c_base * w.abs()
        net2 = brut - c_stress * w.abs()
        actif = w != 0
        ligne = {}
        for lib, sel in [("tout", np.ones(len(f), bool))] + list(phases.items()):
            a = actif & sel
            n = int(a.sum())
            ans = (f.index[sel][-1] - f.index[sel][0]).days / 365.25 if sel.any() else math.nan
            sh_b = brut[sel].mean() / brut[sel].std() * math.sqrt(252) if n > 2 else math.nan
            sh_n = net[sel].mean() / net[sel].std() * math.sqrt(252) if n > 2 else math.nan
            sh_s = net2[sel].mean() / net2[sel].std() * math.sqrt(252) if n > 2 else math.nan
            succes = float((brut[a] > 0).mean()) if n else math.nan
            ligne[lib] = dict(n=n, par_an=n / ans if ans else math.nan, succes=succes, brut=brut[a].mean() if n else math.nan,
                              net=net[a].mean() if n else math.nan, t_net=tstat(net[a]) if n > 2 else math.nan,
                              sh_brut=sh_b, sh_net=sh_n, sh_stress=sh_s)
        res[v] = ligne
        tt = ligne["tout"]["t_net"]
        pval[v] = float(stats.t.sf(tt, max(ligne["tout"]["n"] - 1, 1))) if np.isfinite(tt) else 1.0
        pr(f"  --- {v} :")
        for lib, d in ligne.items():
            pr(f"      {lib:<30} {d['n']:>5} trades ({d['par_an']:.0f}/an) | succes {d['succes']:.0%} | brut {d['brut']:+.2f} pb | "
               f"net {d['net']:+.2f} pb (t {d['t_net']:+.2f}) | Sharpe brut {d['sh_brut']:+.2f}, net {d['sh_net']:+.2f}, stress {d['sh_stress']:+.2f}")
    ph = holm(pval)
    pr("  p-values unilaterales (net > 0, tout l echantillon) brutes -> Holm : " +
       " | ".join(f"{v} {pval[v]:.3f} -> {ph[v]:.3f}" for v in pval))

    pr("\n4. Verdicts")
    e2 = etal[PHASES[2][0]]
    sh_v1_oos2 = res["V1"][PHASES[2][0]]["sh_net"]
    inval = (e2["t_int"] < 2 or e2["b_int"] <= 0) or not (sh_v1_oos2 >= 0.3)
    pr(f"  Critere d invalidation de la specification (OOS 2 : interaction t >= 2 et positive, Sharpe net V1 >= 0,3) : "
       f"interaction {e2['b_int']:+.2f} (t {e2['t_int']:+.2f}), Sharpe net V1 {sh_v1_oos2:+.2f} -> {'H2 INVALIDEE' if inval else 'H2 non invalidee'}")
    w1 = pos["V1"]
    x1 = (w1 * tr)[w1 != 0]
    c = criteres(x1, (pos["V0"] * tr)[pos["V0"] != 0], c_stress)
    quot = ((w1 * tr) - c_stress * w1.abs()) / 1e4
    p_dsr = dsr(quot, N_ESSAIS)
    echecs = [k for k, ok in c["tests"].items() if not ok] + ([] if p_dsr >= SEUIL_DSR else [f"Sharpe deflate >= {SEUIL_DSR:.2f}"])
    pr(f"  Criteres de la methode sur V1 (cout 1 tick par cote, comme les autres modules) : {c['n']} trades, net {c['net']:+.2f} pb, "
       f"t brut {c['t']:+.2f}, 2016-2020 t {c['t1']:+.2f}, 2021-2026 t {c['t2']:+.2f}, Welch {c['welch']:+.2f} contre V0, sans les 3 "
       f"meilleurs jours {c['sans3']:+.2f} | Sharpe deflate ({N_ESSAIS} essais) {p_dsr:.2f}")
    pr("  VERDICT (V1) : " + ("passe les criteres (indicatif : non aveugle)" if not echecs else "ECHOUE (" + " ; ".join(echecs) + ")"))
    pr(f"Calcul en {(datetime.now() - t0).total_seconds():.0f} s.")
    sortie = sortie or os.path.join(PY_DIR, "recherche", "resultats_bdlm_conditionnel.txt")
    with open(sortie, "w", encoding="utf-8") as fh:
        fh.write("\n".join(L) + "\n")

    def _ligne(v, nom):
        d, d1, d2 = res[v]["tout"], res[v][PHASES[0][0]], res[v][PHASES[2][0]]
        return dict(code=v, nom=nom, n=d["n"], moyenne=d["net"], t=d["t_net"], t1=d1["t_net"], t2=d2["t_net"],
                    temoin=res["V0"]["tout"]["net"], welch=c["welch"] if v == "V1" else None, sharpe_an=d["sh_net"],
                    dsr=p_dsr if v == "V1" else None, stress=d["sh_stress"])
    exporter("bdlm_conditionnel", dict(
        titre="BDLM 2021 conditionne au gamma : specification de l arbre (V0-V3)",
        sous="Specification arbres/market-intraday-momentum/strategie_BDLM_conditionnelle.md. Colonnes t : tout / etalonnage "
             "2016-05/2020 / ere 0DTE depuis le 11/05/2022 ; net = 1 tick aller-retour + 5 $. Test non aveugle (V1 tres proche "
             "de R0 de gamma_intraday). V4 (LETF) non testee faute de donnees.",
        lignes=[_ligne("V0", "V0 inconditionnel"), _ligne("V1", "V1 momentum si NGE<0, sinon rien"),
                _ligne("V2", "V2 continue reestimee (fenetre expansive)"), _ligne("V3", "V3 retournement si NGE>0")],
        invalide=inval, echecs=echecs + (["critere d invalidation de la specification"] if inval else []) + ["test non aveugle"],
        retenue=False))
    log("\n".join(L))
    return dict(res=res, etal=etal, invalide=inval, echecs=echecs)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--sortie", default=None)
    a = ap.parse_args(argv)
    etude(a.sortie)


if __name__ == "__main__":
    main()
