"""Controle « ancre au hasard » de l ORB NQ (contre-papier Fetna 2026, SSRN 7428398) - controle de robustesse, PAS un essai.

    python -m nexus.perso.orb_ancre [--tirages 200]   -> recherche/resultats_orb_ancre.txt

Protocole ecrit le 2026-10-22 AVANT le calcul (aucune regle de l ORB n est modifiee) :
- Question : l avantage de l ORB (nexus/orb.py, regles figees, NQ 2016-2026) vient-il de l OUVERTURE (9:30), ou d une
  simple continuation des mouvements quand la volatilite monte, comme le conclut Fetna 2026 pour sa meilleure case ?
- Methode : memes regles exactement (bougie de 5 min, filtre de volume = volume de la bougie / moyenne de la bougie A LA
  MEME HEURE sur les 14 seances precedentes >= 1, ordre stop au plus haut / plus bas dans le sens de la bougie, stop a
  10 % de l ATR 14 jours, sortie a la cloture, risque 1 %, levier max 4, memes couts) ; seule l heure de debut de la
  bougie change. Ancres possibles : toutes les 5 minutes.
- Controle principal (A) : chaque seance recoit une ancre tiree au hasard entre 10:00 et 11:30 (duree jusqu a la
  cloture comparable a celle de l ORB) ; 200 tirages independants.
- Controle secondaire (B) : ancre au hasard entre 10:00 et 14:30 ; 200 tirages. Profil (C) : ancres fixes toutes les
  30 minutes de 10:00 a 14:30.
- Mesures : R moyen par trade (P&L net / 1 % du capital) et Sharpe vectorbt des rendements journaliers.
- Critere : l avantage vient de l ouverture si l ORB reelle (9:30) depasse le 95e centile des tirages de A sur LES DEUX
  mesures ; sinon on retient la lecture de Fetna (continuation de volatilite) et l achat de NQ 2010-2015 pour le rejeu
  n est pas justifie.
- Verification du calcul (critere 9) : l ancre 9:30 de cette fonction doit redonner exactement les trades de nexus.orb.
- Biais connu, dans le sens FAVORABLE a l ORB reelle : une ancre plus tardive laisse moins de temps jusqu a la cloture.
"""
from __future__ import annotations

import argparse
import os
import time

import numpy as np
import pandas as pd

from .. import orb as O

try:
    import vectorbt as vbt
except ImportError:  # pragma: no cover
    vbt = None

ICI = os.path.dirname(os.path.abspath(__file__))
COTATIONS = os.path.normpath(os.path.join(ICI, "..", "..", "..", "Cotations"))
SORTIE = os.path.normpath(os.path.join(ICI, "..", "..", "recherche", "resultats_orb_ancre.txt"))
ANCRES_A = list(range(30, 121, 5))        # 10:00 -> 11:30
ANCRES_B = list(range(30, 301, 5))        # 10:00 -> 14:30
ANCRES_C = list(range(30, 301, 30))


def tables(m: pd.DataFrame, p: dict, ancres: list[int]):
    """Pour chaque ancre a (minutes apres 9:30) : bougie de k minutes (a, a+k], volume relatif a la meme heure, ATR."""
    jour = m.index.normalize()
    mn = (m.index.hour * 60 + m.index.minute - 570).to_numpy()
    k = int(p["minutes_ouverture"])
    gj = m.groupby(jour)
    H, L, C = gj["high"].max(), gj["low"].min(), gj["close"].last()
    tr = pd.concat([H - L, (H - C.shift(1)).abs(), (L - C.shift(1)).abs()], axis=1).max(axis=1)
    atr = tr.rolling(int(p["atr_jours"])).mean().shift(1)
    out = {}
    for a in ancres:
        sel = (mn > a) & (mn <= a + k)
        g = m[sel].groupby(jour[sel])
        r_v = g["volume"].sum()
        out[a] = pd.DataFrame(dict(o=g["open"].first(), c=g["close"].last(), h=g["high"].max(), l=g["low"].min(),
                                   vol_rel=r_v / r_v.rolling(int(p["volume_jours"])).mean().shift(1), atr=atr.reindex(g.size().index)))
    return out, jour.to_numpy(), mn


def signaux_ancre(m, p, tabs, jour, mn, ancre_du_jour: dict):
    """Copie de nexus.orb.signaux, la bougie commencant a l ancre du jour (dict jour -> minutes apres 9:30)."""
    n = len(m)
    o, h, lo = (m[c].to_numpy(float) for c in ("open", "high", "low"))
    derniere = np.r_[jour[1:] != jour[:-1], True]
    fins = np.flatnonzero(derniere)
    debuts = np.r_[0, fins[:-1] + 1]
    E, SE = np.zeros(n, bool), np.zeros(n, bool)
    prix, sl, taille = o.copy(), np.full(n, np.nan), np.full(n, np.nan)
    k = int(p["minutes_ouverture"])
    for s0, i1 in zip(debuts, fins):
        d = pd.Timestamp(jour[s0])
        a = ancre_du_jour.get(d)
        if a is None or d not in tabs[a].index:
            continue
        cible = np.flatnonzero(mn[s0:i1 + 1] == a + k + 1)
        if not len(cible):
            continue
        i0 = s0 + int(cible[0])
        x = tabs[a].loc[d]
        sens = np.sign(x.c - x.o)
        if not np.isfinite(sens) or sens == 0 or not (x.atr > 0):
            continue
        if p["filtre_volume"] and not (x.vol_rel >= float(p["volume_min"])):
            continue
        niveau = x.h if sens > 0 else x.l
        touche = (h[i0:i1] >= niveau) if sens > 0 else (lo[i0:i1] <= niveau)
        if not touche.any():
            continue
        j = i0 + int(np.argmax(touche))
        fill = max(o[j], niveau) if sens > 0 else min(o[j], niveau)
        (E if sens > 0 else SE)[j] = True
        prix[j] = fill
        dist = float(p["stop_atr"]) * x.atr
        sl[j] = dist / fill
        taille[j] = min(float(p["risque"]) * float(p["capital"]) / dist, float(p["levier_max"]) * float(p["capital"]) / fill)
    return E, SE, derniere, prix, sl, taille


def mesurer(m, p, sig, cal):
    E, SE, X, prix, sl, taille = sig
    cap = float(p["capital"])
    pf = vbt.Portfolio.from_signals(m["close"], entries=E, exits=X, short_entries=SE, short_exits=X, price=prix,
                                    open=m["open"], high=m["high"], low=m["low"], size=taille, size_type="amount",
                                    sl_stop=sl, stop_entry_price="fillprice", fees=m["frais"], slippage=m["glissement"],
                                    init_cash=cap * (1 + float(p["reserve_mult"])), freq="1min")
    pnl = pf.trades.records_readable["PnL"].to_numpy(float)
    v = pf.value() - cap * float(p["reserve_mult"])
    d = v.groupby(pd.DatetimeIndex(v.index).normalize()).last().reindex(cal).ffill().bfill()
    r = d.pct_change().dropna()
    sh = float(r.vbt.returns(freq="1D", year_freq="252 days").sharpe_ratio())
    return dict(n=len(pnl), r_moyen=float(pnl.mean() / (0.01 * cap)) if len(pnl) else np.nan, sharpe=sh,
                pnl=float(pnl.sum())), pf


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--tirages", type=int, default=200)
    ap.add_argument("--verifier", action="store_true", help="verification de l ancre 9:30 seulement, sans controle")
    a = ap.parse_args(argv)
    t0 = time.time()
    lignes = []
    pr = lambda s="": (print(s, flush=True), lignes.append(s))
    m, info = O.charger(os.path.join(COTATIONS, "indices"), "NQ")
    p = dict(O.DEFAULTS)
    cal = pd.DatetimeIndex(sorted(set(m.index.normalize())))
    pr("CONTROLE « ANCRE AU HASARD » DE L ORB NQ (Fetna 2026, SSRN 7428398) - controle de robustesse, pas un essai")
    pr(f"donnees : {info['symbole']}, {info['debut']} -> {info['fin']}, {info['seances']} seances")
    pr()
    # verification : ancre 0 = ORB reelle de nexus.orb
    ref = O.portefeuille(m)
    pnl_ref = ref.trades.records_readable["PnL"].to_numpy(float)
    tabs0, jour, mn = tables(m, p, [0])
    reel, pf0 = mesurer(m, p, signaux_ancre(m, p, tabs0, jour, mn, {d: 0 for d in cal}), cal)
    pnl0 = pf0.trades.records_readable["PnL"].to_numpy(float)
    ok = len(pnl0) == len(pnl_ref) and np.allclose(pnl0, pnl_ref)
    pr(f"VERIFICATION : ancre 9:30 de ce module {len(pnl0)} trades, nexus.orb {len(pnl_ref)} trades, P&L identiques : {ok}")
    if not ok:
        raise SystemExit("verification echouee : arret avant tout resultat")
    if a.verifier:
        print(f"verification seule, {time.time() - t0:.0f} s (aucun resultat de controle calcule)")
        return
    pr(f"ORB REELLE (9:30) : {reel['n']} trades | R moyen {reel['r_moyen']:+.3f} | Sharpe {reel['sharpe']:+.2f}")
    pr()
    tabs, jour, mn = tables(m, p, sorted(set(ANCRES_B) | {0}))
    pr("C - PROFIL A ANCRES FIXES (toutes les seances a la meme heure)")
    for x in ANCRES_C:
        r, _ = mesurer(m, p, signaux_ancre(m, p, tabs, jour, mn, {d: x for d in cal}), cal)
        hh = 570 + x
        pr(f"   {hh // 60:02d}:{hh % 60:02d}  {r['n']:5d} trades | R moyen {r['r_moyen']:+.3f} | Sharpe {r['sharpe']:+.2f}")
    pr()
    for nom, anc in (("A - ancre au hasard 10:00-11:30 (controle principal)", ANCRES_A),
                     ("B - ancre au hasard 10:00-14:30", ANCRES_B)):
        rng = np.random.default_rng(20261022)
        res = []
        for _ in range(a.tirages):
            tir = dict(zip(cal, rng.choice(anc, size=len(cal))))
            r, _ = mesurer(m, p, signaux_ancre(m, p, tabs, jour, mn, tir), cal)
            res.append(r)
        R = np.array([x["r_moyen"] for x in res])
        S = np.array([x["sharpe"] for x in res])
        N = np.array([x["n"] for x in res])
        pr(nom + f" : {a.tirages} tirages")
        pr(f"   trades par tirage : mediane {np.median(N):.0f}")
        pr(f"   R moyen : mediane {np.median(R):+.3f}, 95e centile {np.percentile(R, 95):+.3f}, max {R.max():+.3f} ; "
           f"ORB reelle {reel['r_moyen']:+.3f} -> part des tirages >= reelle : {np.mean(R >= reel['r_moyen']):.1%}")
        pr(f"   Sharpe  : mediane {np.median(S):+.2f}, 95e centile {np.percentile(S, 95):+.2f}, max {S.max():+.2f} ; "
           f"ORB reelle {reel['sharpe']:+.2f} -> part des tirages >= reelle : {np.mean(S >= reel['sharpe']):.1%}")
        if nom.startswith("A"):
            verdict = reel["r_moyen"] > np.percentile(R, 95) and reel["sharpe"] > np.percentile(S, 95)
        pr()
    pr("VERDICT : " + ("l avantage vient de l OUVERTURE (l ORB reelle depasse le 95e centile du controle A sur les deux "
                        "mesures) : le rejeu 2010-2015 garde son sens" if verdict else
                        "l avantage NE vient PAS specifiquement de l ouverture (lecture de Fetna 2026 : continuation de "
                        "volatilite) : l achat de NQ 2010-2015 pour le rejeu n est pas justifie"))
    pr(f"(calcule en {time.time() - t0:.0f} s le {pd.Timestamp.now():%Y-%m-%d %H:%M})")
    with open(SORTIE, "w", encoding="utf-8") as fh:
        fh.write(__doc__.strip() + "\n\n" + "\n".join(lignes) + "\n")


if __name__ == "__main__":
    main()
