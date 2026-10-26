"""ORB 5 minutes NQ : tous les controles possibles avec les donnees actuelles, REGLES FIGEES (nexus/orb.py).

    python -m nexus.perso.orb_robustesse [--sortie recherche/resultats_orb_robustesse.txt]

ECRIT LE 2026-10-21 AVANT LE CALCUL. Aucun reglage n est choisi ni modifie : ce sont des diagnostics de la meme
strategie (pas de nouvel essai, N du programme inchange). Ils completent les 29 tests de la fiche ORB_NQ du tableau de
bord (couts, latence, MNQ, plateau, PBO, walk-forward, SPA, Monte Carlo, jours au hasard...) par ce qui n y est pas :

 A. Execution
   A1 barre d entree : l ordre stop et le stop de protection peuvent etre touches dans la MEME barre d une minute ;
      on ne connait pas l ordre des prix dans la barre. Hypothese prudente : si l extreme defavorable de la barre
      d entree atteint le stop, le trade perd 1 R (plus les couts). Sharpe recalcule.
   A2 sorties au-dela du stop (ecarts de prix) : pire perte en multiple de R ; part des pertes < -1,2 R.
 B. Distribution des trades (en R = gain / risque au stop) : taux de reussite, gain moyen / perte moyenne, plus longue
   serie de pertes, part du gain apportee par les 5 % meilleurs trades, gain net sans les 10 meilleurs.
 C. Sens : achats et ventes separes, par moitie (2016-2020 / 2021-2026).
 D. Mecanisme « Stocks in Play » (Zarattini-Barbon-Aziz 2024) : memes regles sur les jours ECARTES par le filtre de
   volume (volume relatif < 100 %) ; prediction du papier : moins bons que les jours retenus (Welch sur R par trade).
 E. Calendrier (descriptif) : jour de la semaine, annee.
 F. Regime : terciles de l ATR 14 jours connu avant la seance (R moyen par tercile).
 G. Prop firm : pertes journalieres en % du capital (pire jour, jours < -1 %, < -2 %), perte max en R.
Seuils d alerte fixes avant le calcul : A1 Sharpe < 0,6 ; D jours ecartes au moins aussi bons (mecanisme non confirme) ;
C un sens negatif sur une moitie ; B plus de 50 % du gain dans les 5 % meilleurs trades.
"""
from __future__ import annotations

import argparse
import math
import os
import warnings

import numpy as np
import pandas as pd

from .. import orb as OR
from .soixante import COUPURE, PY_DIR, tstat


def _sharpe(r: pd.Series) -> float:
    import vectorbt as vbt  # noqa: F401
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return float(r.vbt.returns(freq="1D", year_freq="252D").sharpe_ratio())


def _cal(m: pd.DataFrame) -> pd.DatetimeIndex:
    from ..tableau import calendrier
    return calendrier(m.index[0].normalize(), m.index[-1].normalize())


def trades_r(m: pd.DataFrame, pf) -> pd.DataFrame:
    """Trades vectorbt avec le risque au stop (dollars) et le gain en R."""
    p = pf.nexus_params
    E, SE, _, prix, sl, taille, _ = OR.signaux(m, p)
    t = pf.trades.records_readable.copy()
    pos = m.index.get_indexer(pd.DatetimeIndex(t["Entry Timestamp"]))
    t["i"] = pos
    t["risque"] = taille[pos] * sl[pos] * prix[pos]
    t["R"] = t["PnL"] / t["risque"]
    t["long"] = t["Direction"].astype(str).str.lower().str.startswith("long")
    t["jour"] = pd.DatetimeIndex(t["Entry Timestamp"]).normalize()
    t["stop"] = np.where(t["long"], prix[pos] * (1 - sl[pos]), prix[pos] * (1 + sl[pos]))
    return t


def etude(dossier: str, log=print) -> dict:
    m, info = OR.charger(dossier, "NQ")
    cal = _cal(m)
    pf = OR.portefeuille(m)
    r = OR.valeur_journaliere(pf, cal).pct_change().fillna(0.0)
    cap = OR.DEFAULTS["capital"]
    t = trades_r(m, pf)
    out: dict = dict(sharpe=_sharpe(r), trades=len(t))
    log(f"ORB NQ (regles figees) : {info['debut']} -> {info['fin']}, {len(t)} trades, Sharpe vectorbt {out['sharpe']:.2f}")

    # A1 barre d entree
    lo, hi = m["low"].to_numpy(float), m["high"].to_numpy(float)
    touche = np.where(t["long"], lo[t["i"]] <= t["stop"], hi[t["i"]] >= t["stop"])
    deja = t["R"] <= -0.9                                   # deja sortis au stop dans la simulation
    a_corriger = touche & ~deja
    pnl = t["PnL"].where(~a_corriger, -t["risque"] - t["Entry Fees"].abs() * 2)
    jour_pnl = pd.Series(pnl.to_numpy(), index=t["jour"]).groupby(level=0).sum().reindex(cal).fillna(0.0)
    jour_ref = pd.Series(t["PnL"].to_numpy(), index=t["jour"]).groupby(level=0).sum().reindex(cal).fillna(0.0)
    r_a1 = r + (jour_pnl - jour_ref) / cap
    sh_a1 = _sharpe(r_a1)
    log(f"\nA1 barre d entree : stop atteignable dans la barre d entree pour {int(touche.sum())} trades "
        f"({100 * touche.mean():.1f} %), dont {int(a_corriger.sum())} non sortis au stop dans la simulation")
    log(f"   hypothese prudente (perte de 1 R pour ces trades) : Sharpe {sh_a1:.2f} (reference {out['sharpe']:.2f})"
        f"{'  ALERTE' if sh_a1 < 0.6 else ''}")
    # lecture realiste (ajoutee le 2026-10-21 apres la premiere execution, documentee dans le rapport) : convention
    # habituelle du chemin dans la barre (l extreme le plus proche de l ouverture est atteint en premier) ; le stop
    # n est touche apres l entree que si le prix y revient apres le point d entree.
    op, cl = m["open"].to_numpy(float), m["close"].to_numpy(float)
    n_conv = 0
    for _, x in t[a_corriger].iterrows():
        i = x["i"]
        bas_dabord = (op[i] - lo[i]) <= (hi[i] - op[i])
        if x["long"]:
            n_conv += (cl[i] if bas_dabord else lo[i]) <= x["stop"]
        else:
            n_conv += (cl[i] if not bas_dabord else hi[i]) >= x["stop"]
    log(f"   lecture realiste (chemin O-L-H-C / O-H-L-C) : {int(n_conv)} de ces {int(a_corriger.sum())} trades touchent le stop APRES"
        f" l entree -> {'resultat inchange' if n_conv == 0 else 'a corriger'} ; seules des donnees a la seconde trancheraient")
    out["A1"] = dict(touche=int(touche.sum()), corriges=int(a_corriger.sum()), sharpe=sh_a1, convention=int(n_conv))

    # A2 sorties au-dela du stop
    pertes = t.loc[t["R"] < 0, "R"]
    log(f"\nA2 pertes : pire {pertes.min():.2f} R ; pertes < -1,2 R : {int((pertes < -1.2).sum())} ({100 * (pertes < -1.2).mean():.1f} % des pertes)")
    out["A2"] = dict(pire=float(pertes.min()), au_dela=int((pertes < -1.2).sum()))

    # B distribution
    R = t["R"]
    gains, pertes = R[R > 0], R[R <= 0]
    serie, pire_serie = 0, 0
    for x in R:
        serie = serie + 1 if x <= 0 else 0
        pire_serie = max(pire_serie, serie)
    top = t["PnL"].nlargest(max(1, int(0.05 * len(t)))).sum() / t["PnL"].sum()
    sans10 = t["PnL"].drop(t["PnL"].nlargest(10).index).sum()
    log(f"\nB trades : reussite {100 * (R > 0).mean():.1f} % ; gain moyen {gains.mean():+.2f} R, perte moyenne {pertes.mean():+.2f} R ;"
        f" esperance {R.mean():+.3f} R (t {tstat(R):.2f})")
    log(f"   plus longue serie de pertes : {pire_serie} ; part du gain des 5 % meilleurs trades : {100 * top:.0f} %"
        f"{'  ALERTE' if top > 0.5 else ''} ; gain net sans les 10 meilleurs : {sans10 / cap * 100:+.1f} % du capital")
    out["B"] = dict(reussite=float((R > 0).mean()), esperance=float(R.mean()), t=tstat(R), serie=pire_serie, top5=float(top), sans10=float(sans10))

    # C sens
    log("\nC sens (R moyen par trade) :")
    out["C"] = {}
    for nom, s in (("achats", t[t["long"]]), ("ventes", t[~t["long"]])):
        p1, p2 = s[s["jour"] < COUPURE]["R"], s[s["jour"] >= COUPURE]["R"]
        alerte = p1.mean() < 0 or p2.mean() < 0
        log(f"   {nom:6s} n {len(s):4d} | {s['R'].mean():+.3f} R (t {tstat(s['R']):+.2f}) | 16-20 {p1.mean():+.3f} (t {tstat(p1):+.2f})"
            f" | 21-26 {p2.mean():+.3f} (t {tstat(p2):+.2f}){'  ALERTE' if alerte else ''}")
        out["C"][nom] = dict(n=len(s), R=float(s["R"].mean()), t=tstat(s["R"]), R1=float(p1.mean()), R2=float(p2.mean()))

    # D mecanisme : jours ecartes par le filtre de volume
    tab, _, _ = OR._jours(m, OR.DEFAULTS)
    pf_tous = OR.portefeuille(m, filtre_volume=False)
    tt = trades_r(m, pf_tous)
    vr = tab["vol_rel"].reindex(tt["jour"]).to_numpy()
    dedans, dehors = tt.loc[vr >= 1.0, "R"], tt.loc[vr < 1.0, "R"]
    se = math.sqrt(dedans.var(ddof=1) / len(dedans) + dehors.var(ddof=1) / len(dehors))
    welch = (dedans.mean() - dehors.mean()) / se
    log(f"\nD mecanisme (memes regles sans filtre) : jours retenus n {len(dedans)} {dedans.mean():+.3f} R (t {tstat(dedans):+.2f}) ;"
        f" jours ecartes n {len(dehors)} {dehors.mean():+.3f} R (t {tstat(dehors):+.2f}) ; Welch {welch:+.2f}"
        f"{'  ALERTE (mecanisme non confirme)' if dehors.mean() >= dedans.mean() else ''}")
    q = pd.qcut(pd.Series(vr, index=tt.index).dropna(), 3, labels=["bas", "moyen", "haut"])
    log("   R moyen par tercile de volume relatif : " + " ; ".join(f"{g} {tt.loc[q.index[q == g], 'R'].mean():+.3f}" for g in ("bas", "moyen", "haut")))
    out["D"] = dict(dedans=float(dedans.mean()), dehors=float(dehors.mean()), welch=float(welch))

    # E calendrier
    log("\nE jour de la semaine (R moyen) : " + " ; ".join(
        f"{n} {t.loc[t['jour'].dt.dayofweek == d, 'R'].mean():+.3f} (n {int((t['jour'].dt.dayofweek == d).sum())})"
        for d, n in enumerate(("lun", "mar", "mer", "jeu", "ven"))))
    log("  annee (R moyen) : " + " ; ".join(f"{a} {g['R'].mean():+.3f}" for a, g in t.groupby(t["jour"].dt.year)))

    # F regime de volatilite
    atr = tab["atr"].reindex(t["jour"]).to_numpy() / tab["o"].reindex(t["jour"]).to_numpy()
    q = pd.qcut(pd.Series(atr, index=t.index), 3, labels=["basse", "moyenne", "haute"])
    log("\nF ATR relatif connu avant la seance (R moyen) : " + " ; ".join(
        f"{g} {t.loc[q == g, 'R'].mean():+.3f} (t {tstat(t.loc[q == g, 'R']):+.2f})" for g in ("basse", "moyenne", "haute")))

    # G prop firm
    jr = r[r != 0]
    v = OR.valeur_journaliere(pf, cal)
    dd_r = ((v.cummax() - v) / (cap * OR.DEFAULTS["risque"])).max()
    log(f"\nG pertes journalieres (capital fixe, risque 1 % par trade) : pire jour {100 * jr.min():+.2f} % ; jours < -1 % : "
        f"{int((jr < -0.01).sum())} ; jours < -2 % : {int((jr < -0.02).sum())} ; perte max {dd_r:.1f} R")
    out["G"] = dict(pire_jour=float(jr.min()), sous_1=int((jr < -0.01).sum()), sous_2=int((jr < -0.02).sum()), dd_R=float(dd_r))
    return out


def main(argv=None):
    from ..__main__ import REPO_QUOTES
    ap = argparse.ArgumentParser()
    ap.add_argument("--cotations", default=REPO_QUOTES)
    ap.add_argument("--sortie", default=os.path.join(PY_DIR, "recherche", "resultats_orb_robustesse.txt"))
    a = ap.parse_args(argv)
    lignes: list[str] = []
    log = lambda s="": (print(s), lignes.append(s))  # noqa: E731
    etude(a.cotations, log)
    with open(a.sortie, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lignes) + "\n")
    print(f"-> {a.sortie}")


if __name__ == "__main__":
    main()
