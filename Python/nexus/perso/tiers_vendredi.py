"""Pic du 3e vendredi trimestriel (« Third Friday Price Spike ») sur les futures d indices - UN essai (n° 432).

    python -m nexus.perso.tiers_vendredi [--sortie resultats_tiers_vendredi.txt]

PROTOCOLE ECRIT LE 2026-10-22 AVANT LE CALCUL. Aucun parametre n est choisi apres avoir vu un resultat.

Source (texte complet lu, version de mai 2024, 70 p.) : G. Baltussen (Erasmus University Rotterdam), J. Terstegge
(Copenhagen Business School), P. Whelan (CUHK), « The Derivative Payoff Bias » (SSRN 4562800, auparavant « The Third
Friday Price Spike », presente a l AFA). Flux force : une grande partie des derives sur le S&P 500 se regle le matin du
3e vendredi sur le prix d ouverture des actions (SOQ) ; la couverture des teneurs de marche pendant la nuit, peu liquide,
pousse les prix vers le haut de la cloture du jeudi a l ouverture du vendredi, puis tout est rendu avant midi.
Chiffres du papier (2003-2021) : ES, achat a la cloture du jeudi, vente a l ouverture du vendredi et vente a decouvert
jusqu a la cloture : +27,5 pb brut, +24,2 pb apres l ecart achat-vente (t 3,47, ecart-type 104,6 pb), 16 annees
positives sur 19 ; rien les autres jours (-3,2 pb). Echeances TRIMESTRIELLES (quatre sorcieres, tableau III) : nuit
+26,4 pb (t 4,36, ecart-type 52,5), seance -37,2 pb (t -3,54, ecart-type 91,0) ; mensuelles hors trimestre : +14,5 / -6,7.
Meme profil sur le Nasdaq 100 et le Dow (14 et 12 pb la nuit, retournement de meme taille). Papiers contraires :
aucun trouve (recherche du 2026-10-22). Deja teste chez nous : YM 4 (contre-pied du premier quart d heure, 9:45-11:00,
quatre sorcieres) - regle DIFFERENTE, sans rapport avec le pic de nuit.
Calcul de puissance (critere 6, chiffres du papier, ~42 echeances trimestrielles de 2016 a 2026, evenement rare : seuil
t = 2) : nuit + seance, effet ~63,6 pb, ecart-type ~105 pb, couts ~3,2 pb -> t attendu ~3,7 ; seance seule -> ~2,5.
Version mensuelle : t attendu 2,2 a 2,6 sous le seuil de 3 -> non testee.

Regle unique, figee (version trimestrielle, rendue conforme prop firm : a plat a 16:10 ET, nuit permise, pas de week-end)
  Jour d echeance E : 3e vendredi de mars, juin, septembre, decembre ; si ce n est pas un jour de bourse, le jour de bourse
  precedent. Veille V : le jour de bourse precedant E.
  Jambe 1 (nuit) : ACHAT a 18:00 ET le jour V (reouverture apres la pause ; la cloture du jeudi 16:00 du papier n est pas
  tenable : il faut etre a plat a 16:10), sortie a 9:30 ET le jour E.
  Jambe 2 (seance) : VENTE a 9:30 ET le jour E, rachat a 16:00 ET le jour E.
  Prix a HH:MM = ouverture de la barre qui commence a HH:MM (barres datees a leur fin). Contrat : serie continue .v.0
  (roulement au volume, deja passe sur l echeance suivante une semaine avant : l echeance qui expire n est pas tradee) ;
  jambe exclue si le contrat change dans la fenetre ou si un prix manque.
  Gain d un evenement = r(18:00 V -> 9:30 E) - r(9:30 E -> 16:00 E) ; couts = 2 allers-retours (4 cotes).
Temoin neutre : la MEME operation sur tous les autres vendredis (veille = jeudi) qui ne sont pas un 3e vendredi.
Repliques (pas des essais) : NQ et YM (le papier trouve le meme pic). Micros MES, MNQ, MYM avec leurs couts (critere 22).
Couts (critere 8) : 1 tick + 2,50 $ par cote ; stress 2 ticks.
Criteres : evenement rare (< 60) : t >= 2, net positif >= 65 % des annees, Welch >= 2 contre le temoin, net > 0 sans les
  3 meilleurs ; vectorbt : IC bas du Sharpe > 0, Sharpe > 0 avant ET apres 2021, Sharpe deflate >= 0,95 avec 432 essais ;
  puis correlation <= 0,3 avec S1 et Gotobi si le reste passe.
Verification du calcul (critere 9, sans regarder le gain) : dates d echeance contre le calendrier connu (dont le jeudi
  18/06/2026, Juneteenth le 19) ; anticipation (prix modifies apres 9:30 E -> jambe 1 inchangee ; prix modifies apres 16:00 E
  -> gain inchange) ; rejeu vectorbt = P&L brut du moteur jambe par jambe ; 5 evenements tires au hasard imprimes ; comptes.
"""
from __future__ import annotations

import argparse
import math
import os
from datetime import datetime

import numpy as np
import pandas as pd

from .. import prop_combinaisons as PC
from .or_anomalies import instants
from .soixante import COMMISSION, COUTS, ET, PY_DIR, contrats, criteres, jours_ouvres_us, marche, prix_a

try:
    import vectorbt as vbt
except ImportError:  # pragma: no cover
    vbt = None

ESSAIS = 432
MICRO = {"ES": ("MES", 5.0), "NQ": ("MNQ", 2.0), "YM": ("MYM", 0.5)}


def echeances(jours: pd.DatetimeIndex, trimestrielles: bool = True) -> pd.DatetimeIndex:
    """3e vendredi (de mars, juin, septembre, decembre si trimestrielles), ou le jour de bourse precedent."""
    ens = set(jours)
    out = []
    for an in range(jours[0].year, jours[-1].year + 1):
        for mois in ((3, 6, 9, 12) if trimestrielles else range(1, 13)):
            d = pd.Timestamp(an, mois, 1)
            v = d + pd.Timedelta(days=(4 - d.dayofweek) % 7 + 14)
            while v not in ens and v > d:
                v -= pd.Timedelta(days=1)
            if v in ens and jours[0] < v <= jours[-1]:
                out.append(v)
    return pd.DatetimeIndex(out)


def jambes(m, jours: pd.DatetimeIndex, cibles: pd.DatetimeIndex) -> pd.DataFrame:
    """Prix et instants des deux jambes pour chaque jour cible (la veille = jour de bourse precedent de `jours`)."""
    pos = jours.get_indexer(cibles)
    veilles = jours[pos - 1]
    t1, t2, t3 = instants(veilles, 18, 0, ET), instants(cibles, 9, 30, ET), instants(cibles, 16, 0, ET)
    (p1, i1), (p2, i2), (p3, i3) = prix_a(m, t1), prix_a(m, t2), prix_a(m, t3)
    cid = contrats(m)
    ok1 = np.isfinite(p1) & np.isfinite(p2) & (i1 >= 0) & (i2 >= 0)
    ok2 = np.isfinite(p2) & np.isfinite(p3) & (i2 >= 0) & (i3 >= 0)
    ok1[ok1] &= cid[i1[ok1]] == cid[i2[ok1]]
    ok2[ok2] &= cid[i2[ok2]] == cid[i3[ok2]]
    off = getattr(m, "offset", np.zeros(m.n))
    reel = lambda p, i: np.where(i >= 0, p - off[np.clip(i, 0, None)], np.nan)  # noqa: E731
    f = pd.DataFrame(dict(veille=veilles, t1=t1, t2=t2, t3=t3, p1=reel(p1, i1), p2=reel(p2, i2), p3=reel(p3, i3),
                          ok1=ok1, ok2=ok2), index=cibles)
    f["r1"] = np.where(ok1, np.log(f["p2"] / f["p1"]) * 1e4, np.nan)          # nuit, achat
    f["r2"] = np.where(ok2, -np.log(f["p3"] / f["p2"]) * 1e4, np.nan)         # seance, vente
    f["ok"] = ok1 & ok2
    f["brut_pb"] = np.where(f["ok"], f["r1"] + f["r2"], np.nan)
    return f


def cout_pb(root: str, prix: float, ticks: int = 1, micro: bool = False) -> float:
    """Deux allers-retours (4 cotes), en pb."""
    tick, pv = COUTS[root][0], (MICRO[root][1] if micro else COUTS[root][1])
    return 2 * (2 * ticks * tick + 2 * COMMISSION / pv) / prix * 1e4


def serie_journaliere(f: pd.DataFrame, jours: pd.DatetimeIndex, cout: float) -> pd.Series:
    """Rendement net rattache au jour d echeance (fraction), 0 les autres jours de bourse."""
    r = pd.Series(0.0, index=jours)
    t = f[f["ok"]]
    r.loc[t.index] = (np.exp(t["brut_pb"] / 1e4) - 1) - cout / 1e4
    return r


# =============================================================================
#  Verifications (critere 9)
# =============================================================================
def verif_dates(jours: pd.DatetimeIndex) -> str:
    e = echeances(jours)
    connus = [pd.Timestamp(x) for x in ("2016-03-18", "2020-12-18", "2022-06-17", "2025-03-21", "2026-06-18")]
    manq = [x.date().isoformat() for x in connus if x not in e]
    return (f"(a) dates : {len(e)} echeances trimestrielles {e[0]:%Y-%m-%d} -> {e[-1]:%Y-%m-%d} ; controles connus "
            f"(dont jeudi 18/06/2026, Juneteenth) : {'TOUS PRESENTS' if not manq else 'MANQUENT ' + ', '.join(manq)}")


def verif_anticipation(m, jours: pd.DatetimeIndex, cibles: pd.DatetimeIndex, f: pd.DataFrame) -> str:
    """Prix modifies apres 9:30 E -> jambe 1 inchangee ; apres 16:00 E -> gain inchange (sur un evenement)."""
    d = f[f["ok"]].index[len(f[f["ok"]]) // 2]
    t2, t3 = int(f.loc[d, "t2"]), int(f.loc[d, "t3"])
    sauv = m.o, m.c                                            # tableaux en lecture seule : on travaille sur des copies
    try:
        apres = m.t > t2 + 60_000_000_000                      # barres finies apres 9:31
        m.o, m.c = np.where(apres, sauv[0] * 1.07, sauv[0]), np.where(apres, sauv[1] * 1.07, sauv[1])
        g1 = jambes(m, jours, pd.DatetimeIndex([d]))
        apres = m.t > t3 + 60_000_000_000
        m.o, m.c = np.where(apres, sauv[0] * 1.07, sauv[0]), np.where(apres, sauv[1] * 1.07, sauv[1])
        g2 = jambes(m, jours, pd.DatetimeIndex([d]))
    finally:
        m.o, m.c = sauv
    a = math.isclose(g1["r1"].iloc[0], f.loc[d, "r1"], abs_tol=1e-9)
    b = math.isclose(g2["brut_pb"].iloc[0], f.loc[d, "brut_pb"], abs_tol=1e-9)
    return (f"(b) anticipation ({d:%Y-%m-%d}) : prix +7 % apres 9:31 -> jambe de nuit {'INCHANGEE' if a else 'CHANGEE (BUG)'} ; "
            f"prix +7 % apres 16:01 -> gain {'INCHANGE' if b else 'CHANGE (BUG)'}")


def verif_vectorbt(root: str, f: pd.DataFrame) -> str:
    if vbt is None:
        return "(c) vectorbt absent"
    t = f[f["ok"]]
    pv = COUTS[root][1]
    moteur = np.r_[(t["p2"] - t["p1"]).to_numpy(), -(t["p3"] - t["p2"]).to_numpy()] * pv
    # chaque jambe sur sa propre colonne de prix : ordres d entree et de sortie aux instants de la jambe
    ts = np.r_[t["t1"], t["t2"], t["t2"] + 1, t["t3"]].astype(np.int64)
    px = np.r_[t["p1"], t["p2"], t["p2"], t["p3"]] * pv
    tl = np.r_[np.ones(len(t)), -np.ones(len(t)), -np.ones(len(t)), np.ones(len(t))]
    o = np.argsort(ts, kind="stable")
    idx = pd.to_datetime(ts[o])
    pf = vbt.Portfolio.from_orders(pd.Series(px[o], index=idx), size=pd.Series(tl[o], index=idx), init_cash=1e9,
                                   fees=0.0, freq="1min")
    pnl = pf.trades.records_readable.sort_values("Entry Timestamp")["PnL"].to_numpy()
    ref = np.sort(moteur)
    ecart = float(np.max(np.abs(np.sort(pnl) - ref))) if len(pnl) == len(ref) else math.inf
    return (f"(c) rejeu vectorbt : {len(pnl)} jambes contre {len(ref)} au moteur, ecart maximal de P&L brut {ecart:.6f} $ -> "
            f"{'IDENTIQUE' if ecart < 1e-6 else 'DIFFERENT (BUG)'}")


def verif_cinq(root: str, f: pd.DataFrame) -> list[str]:
    tick, pv = COUTS[root][0], COUTS[root][1]
    out = ["(d) 5 evenements tires au hasard (graine 7), a verifier a la main :"]
    h = lambda t: pd.Timestamp(int(t)).tz_localize("UTC").tz_convert(ET)  # noqa: E731
    for d in f[f["ok"]].sample(5, random_state=7).sort_index().itertuples():
        g1, g2 = (d.p2 - d.p1) * pv, -(d.p3 - d.p2) * pv
        frais = 4 * (tick * pv + COMMISSION)
        out.append(f"    echeance {d.Index:%a %Y-%m-%d} | ACHAT {h(d.t1):%a %H:%M} a {d.p1:.2f} -> {h(d.t2):%a %H:%M} a {d.p2:.2f} "
                   f"({g1:+.2f} $) | VENTE {h(d.t2):%H:%M} a {d.p2:.2f} -> {h(d.t3):%H:%M} a {d.p3:.2f} ({g2:+.2f} $) | "
                   f"frais {frais:.2f} $ | net {g1 + g2 - frais:+.2f} $")
    return out


# =============================================================================
#  Etude
# =============================================================================
def etude(sortie: str | None = None, log=print) -> dict:
    t0 = datetime.now()
    L: list[str] = []
    pr = L.append
    pr("=" * 116)
    pr(" PIC DU 3e VENDREDI TRIMESTRIEL (Baltussen, Terstegge & Whelan 2024) - UN ESSAI (n° 432)")
    pr("=" * 116)
    pr("Regle figee : achat 18:00 ET la veille de l echeance -> 9:30 ; vente 9:30 -> 16:00 le jour de l echeance ;")
    pr("echeances trimestrielles seulement (calcul de puissance) ; temoin : meme operation les autres vendredis.\n")
    res = {}
    for root in ("ES", "NQ", "YM"):
        m = marche(root)
        jours = jours_ouvres_us(m)
        ech = echeances(jours)
        autres = pd.DatetimeIndex([d for d in jours[1:] if d.dayofweek == 4 and d not in set(echeances(jours, False))])
        f, g = jambes(m, jours, ech), jambes(m, jours, autres)
        if root == "ES":
            pr("Verification du calcul (critere 9)")
            pr("  " + verif_dates(jours))
            pr("  " + verif_anticipation(m, jours, ech, f))
            pr("  " + verif_vectorbt(root, f))
            for s in verif_cinq(root, f):
                pr("  " + s)
            pr(f"  (e) comptes ES : {len(ech)} echeances, {int(f['ok'].sum())} retenues ({int((~f['ok1']).sum())} sans nuit "
               f"valable, {int((~f['ok2']).sum())} sans seance valable) ; temoin : {int(g['ok'].sum())} autres vendredis\n")
        prix = float(np.nanmedian(f["p2"]))
        c1, c2, cm = cout_pb(root, prix), cout_pb(root, prix, 2), cout_pb(root, prix, micro=True)
        crit = criteres(f.loc[f["ok"], "brut_pb"], g.loc[g["ok"], "brut_pb"], c1)
        x = PC.mesures(serie_journaliere(f, jours, c1), ESSAIS)
        xm = PC.mesures(serie_journaliere(f, jours, cm), ESSAIS)
        res[root] = dict(f=f, crit=crit, mesures=x, micro=xm)
        ok = f[f["ok"]]
        pr(f"--- {root}{' (ESSAI)' if root == 'ES' else ' (replique, pas un essai)'} : {crit['n']} echeances")
        pr(f"    nuit {ok['r1'].mean():+.2f} pb | seance {ok['r2'].mean():+.2f} pb | total brut {crit['moyenne']:+.2f} pb "
           f"(t {crit['t']:+.2f}) | 2016-2020 {crit['m1']:+.2f} (t {crit['t1']:+.2f}) | 2021-2026 {crit['m2']:+.2f} (t {crit['t2']:+.2f})")
        pr(f"    temoin (autres vendredis) {crit['temoin']:+.2f} pb -> Welch {crit['welch']:+.2f}")
        pr(f"    couts {c1:.2f} pb (2 allers-retours) -> net {crit['net']:+.2f} pb ; sans les 3 meilleurs {crit['sans3']:+.2f} pb ; "
           f"stress 2 ticks {crit['moyenne'] - c2:+.2f} pb ; annees nettes positives {crit['part_annees']:.0%}")
        pr(f"    vectorbt : Sharpe {x['sharpe']:+.2f} [IC 95 % {x['ic_bas']:+.2f} ; {x['ic_haut']:+.2f}] | avant 2021 "
           f"{x['sharpe_p1']:+.2f} | apres {x['sharpe_p2']:+.2f} | deflate ({ESSAIS} essais) {x['dsr']:.2f} | perte max {x['perte_max']:.1%}")
        pr(f"    micro {MICRO[root][0]} (couts {cm:.2f} pb) : Sharpe {xm['sharpe']:+.2f} [IC bas {xm['ic_bas']:+.2f}] | deflate {xm['dsr']:.2f}")
        pr(f"    heures en position : {crit['n'] * (15.5 + 6.5) / max(1e-9, (jours[-1] - jours[0]).days / 365.25):.0f} h/an "
           f"(15 h 30 de nuit + 6 h 30 de seance, 4 fois par an)")
        echecs = [k for k, v in crit["tests"].items() if not v]
        echecs += [] if x["ic_bas"] > 0 else ["IC bas du Sharpe > 0"]
        echecs += [] if (x["sharpe_p1"] > 0 and x["sharpe_p2"] > 0) else ["Sharpe > 0 avant ET apres 2021"]
        echecs += [] if x["dsr"] >= 0.95 else ["Sharpe deflate >= 0,95"]
        res[root]["echecs"] = echecs
        pr(f"    VERDICT : {'PASSE les criteres 10-18' if not echecs else 'ECHOUE (' + ' ; '.join(echecs) + ')'}\n")
    pr("Synthese : " + ("l essai ES passe les criteres 10-18 ; restent la correlation (n° 20) et ta validation."
                        if not res["ES"]["echecs"] else "REJETEE (l essai ES echoue). Aucune variante ne sera testee."))
    pr(f"Calcul en {(datetime.now() - t0).total_seconds():.0f} s.")
    sortie = sortie or os.path.join(PY_DIR, "recherche", "resultats_tiers_vendredi.txt")
    with open(sortie, "w", encoding="utf-8") as fh:
        fh.write("\n".join(L) + "\n")
    log("\n".join(L))
    return res


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--sortie", default=None)
    etude(ap.parse_args(argv).sortie)


if __name__ == "__main__":
    main()
