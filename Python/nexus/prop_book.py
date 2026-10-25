"""Book de plusieurs comptes de prop firm, « comme Kairos » (SEUL BUT depuis le 2026-10-25, CLAUDE.md) : plusieurs
comptes Topstep 50K (paiement Standard, perte journaliere de 1 000 $ choisie a l achat : le meilleur compte robuste de
nexus.prop_comptes) tenus en parallele, chacun avec son propre cycle de vie (evaluation -> finance -> payouts -> perdu
-> rachat).

Ce que l on mesure, pour le book entier sur une annee : gain net total (payouts - frais), probabilite de perdre de
l argent, et CAPITAL DE DEPART necessaire (pire tresorerie cumulee : frais payes avant les premiers payouts).

Comptes possibles (une seule taille par type, choisie sur les departs 2016-2020 comme dans nexus.prop_comptes) :
  A : S1 (MNQ) + Gotobi (6J), les deux strategies validees par les 24 criteres ;
  B : momentum 5 min M2 (K5, essai 440 : passe les criteres 10-18 mais seuils choisis par son auteur sur notre
      periode, A CONFIRMER hors echantillon) en MNQ + Gotobi (6J).
Regles officielles de Topstep qui comptent ici (help.topstep.com, lu le 2026-10-25) :
  - 5 comptes finances (XFA) actifs au plus ; le copieur de trades est permis sur les XFA ;
  - couverture interdite ENTRE comptes, suivie au niveau de l utilisateur : etre long et court en meme temps sur le
    meme instrument (ou un instrument correle) dans deux comptes, meme brievement. Un book qui melange A et B sur NQ
    n est donc permis que si S1 et M2 ne sont jamais en sens contraire au meme moment : mesure ci-dessous.
Books simules : n comptes A, n comptes B, et melanges, de 1 a 5 comptes ; departs simultanes (tous les comptes
ouverts le meme jour, ce que fait Kairos) ou echelonnes d un mois.

Donnees : celles de nexus.prop_comptes (S1 et Gotobi rejoues dans vectorbt sur 1 contrat) ; M2 : trades figes de
nexus.perso.kairos_publiees.trades(NQ, "K5") rejoues de meme dans vectorbt sur 1 MNQ (controle : P&L brut vectorbt =
P&L du moteur, trade par trade). Couts : 1 tick + commission par cote ; stress 2 ticks. IC : bootstrap par blocs de
21 seances sur 2021-2026, CHEMIN DE MARCHE COMMUN a tous les comptes du book (ils subissent les memes jours).

    python -m nexus.prop_book --cache <pickle de nexus.prop_comptes>
"""
from __future__ import annotations

import argparse
import math
import os
import time

import numpy as np
import pandas as pd

from . import prop_comptes as P

REGLE = "topstep_50k_dll"
MAX_COMPTES = 5                     # XFA actifs au plus chez Topstep
DECALAGE = 21                       # depart echelonne : un compte de plus chaque mois
TYPES = {"A": "S1 (MNQ) + Gotobi (6J)", "B": "M2 (MNQ) + Gotobi (6J)"}


# =============================================================================
#  M2 sur 1 MNQ dans vectorbt
# =============================================================================
def m2_un_contrat(df_brut: pd.DataFrame, df_adj: pd.DataFrame, f: pd.DataFrame, contrat: str, ticks: float):
    """Trades figes de K5 (entree a l ouverture de la barre de 9:35, sortie a celle de 15:55, sans stop) rejoues sur 1
    contrat -> (seances, pf vectorbt, controle)."""
    spec = P.CONTRATS[contrat]
    ok = f[f["motif"] == ""]
    idx = pd.DatetimeIndex(df_adj.index).tz_localize(None)
    brut = df_brut.reindex(df_adj.index)["close"].to_numpy(float)
    v_open, v_close = P.prix_dollar(brut, df_adj["open"].to_numpy(float), df_adj["close"].to_numpy(float), spec["point"])
    t_in = pd.to_datetime(ok["t_entree"].astype("int64"), unit="ns")
    t_out = pd.to_datetime(ok["t_sortie"].astype("int64"), unit="ns")
    p_in, ex_in = P._bar(idx, pd.DatetimeIndex(t_in))
    p_out, ex_out = P._bar(idx, pd.DatetimeIndex(t_out))
    cible = np.full(len(idx), np.nan)
    prix = np.full(len(idx), np.nan)
    cible[p_out] = 0.0
    prix[p_out] = np.where(ex_out, v_open[p_out], v_close[p_out])
    cible[p_in] = ok["sens"].to_numpy(float)
    prix[p_in] = np.where(ex_in, v_open[p_in], v_close[p_in])
    pf = P.rejouer(idx, v_open, v_close, cible, prix, spec, ticks)
    rec = pf.trades.records_readable
    brut_vbt = ((rec["Avg Exit Price"] - rec["Avg Entry Price"]) * np.where(rec["Direction"] == "Long", 1, -1)).to_numpy()
    brut_m2 = (ok["sens"] * (ok["ps"] - ok["pe"])).to_numpy(float) * spec["point"]
    n = min(len(brut_vbt), len(brut_m2))
    controle = dict(trades_m2=int(len(ok)), trades_vbt=int(len(rec)), barres_exactes=float(np.mean(ex_in & ex_out)),
                    ecart_moyen=float(np.abs(brut_vbt[:n] - brut_m2[:n]).mean()) if n else math.nan,
                    pnl_m2=float(brut_m2.sum()), pnl_vbt=float(brut_vbt.sum()))
    return P.par_seance(pf, idx), pf, controle


def couvertures(trades_s1: pd.DataFrame, f: pd.DataFrame) -> dict:
    """Jours et minutes ou S1 et M2 sont en position en sens CONTRAIRE au meme moment (couverture entre comptes)."""
    ok = f[f["motif"] == ""]
    m2 = pd.DataFrame({"a": pd.to_datetime(ok["t_entree"].astype("int64"), unit="ns"),
                       "b": pd.to_datetime(ok["t_sortie"].astype("int64"), unit="ns"), "s": ok["sens"].to_numpy()},
                      index=pd.DatetimeIndex(ok.index).normalize())
    j = pd.to_datetime(trades_s1["jour"]).dt.normalize()

    def utc(h):
        t = j + pd.to_timedelta(trades_s1[h] + ":00")
        return pd.DatetimeIndex(t).tz_localize(P.NY).tz_convert("UTC").tz_localize(None)

    s1 = pd.DataFrame({"a": utc("entree"), "b": utc("sortie"),
                       "s": np.where(trades_s1["sens"] == "long", 1, -1)}, index=pd.DatetimeIndex(j))
    communs = s1.index.intersection(m2.index).unique()
    jours_contraires, minutes, jours_meme = 0, 0.0, 0
    for d in communs:
        x = m2.loc[[d]].iloc[0]
        for _, y in s1.loc[[d]].iterrows():
            chev = (min(x["b"], y["b"]) - max(x["a"], y["a"])).total_seconds() / 60.0
            if chev <= 0:
                continue
            if x["s"] != y["s"]:
                jours_contraires += 1
                minutes += chev
            else:
                jours_meme += 1
    return dict(jours_m2=int(len(m2)), jours_s1=int(s1.index.nunique()), jours_communs=int(len(communs)),
                jours_contraires=jours_contraires, jours_meme_sens=jours_meme, minutes_contraires=minutes)


# =============================================================================
#  Book : n comptes sur un chemin de marche commun
# =============================================================================
def compte(L, H, C, W, eqv, idx, t_eval, t_fin, R) -> tuple[np.ndarray, np.ndarray]:
    flux = np.zeros(len(idx))
    x = P.cycle_flux(L, H, C, W, eqv, idx.astype(np.int64), t_eval, t_fin, R, flux)
    return x, flux


def book(chemin: np.ndarray, comptes: list[str], tailles: dict, mats: dict, R, decalage: int) -> dict:
    """Comptes du book sur le meme chemin de seances ; le compte i demarre a la seance i x decalage et dure HORIZON
    seances. -> net total, frais, payouts, pire tresorerie (capital de depart), nets par compte."""
    long_ = P.HORIZON + decalage * (len(comptes) - 1)
    treso = np.zeros(long_)
    nets, frais, payouts = [], 0.0, 0.0
    for i, typ in enumerate(comptes):
        L, H, C, W, eqv = mats[typ]
        te, tf = tailles[typ]
        a = i * decalage
        x, fl = compte(L, H, C, W, eqv, chemin[a:a + P.HORIZON], te, tf, R)
        treso[a:a + P.HORIZON] += fl
        treso[a + P.HORIZON:] += fl[-1]
        nets.append(x[0])
        frais += x[1]
        payouts += x[2]
    return dict(net=float(sum(nets)), frais=frais, payouts=payouts, capital=float(max(0.0, -treso.min())),
                nets=np.array(nets))


def bootstrap_book(comptes, tailles, mats, R, lignes, decalage, b=P.B_BOOT, seed=P.SEED) -> dict:
    rng = np.random.default_rng(seed)
    n = len(lignes)
    long_ = P.HORIZON + decalage * (len(comptes) - 1)
    res = []
    for _ in range(b):
        parts = [lignes[(s + np.arange(P.BLOC)) % n] for s in rng.integers(0, n, size=long_ // P.BLOC + 1)]
        chemin = np.concatenate(parts)[:long_].astype(np.int64)
        res.append(book(chemin, comptes, tailles, mats, R, decalage))
    net = np.array([r["net"] for r in res])
    cap = np.array([r["capital"] for r in res])
    nets = np.array([r["nets"] for r in res])
    corr = float(np.nanmean([np.corrcoef(nets[:, i], nets[:, j])[0, 1]
                             for i in range(nets.shape[1]) for j in range(i + 1, nets.shape[1])])) if nets.shape[1] > 1 else math.nan
    return dict(net_moyen=float(net.mean()), net_median=float(np.median(net)), p_perte=float((net < 0).mean()),
                net_p5=float(np.quantile(net, 0.05)), net_p95=float(np.quantile(net, 0.95)),
                frais=float(np.mean([r["frais"] for r in res])), payouts=float(np.mean([r["payouts"] for r in res])),
                capital_moyen=float(cap.mean()), capital_p95=float(np.quantile(cap, 0.95)), correlation_comptes=corr)


def choisir_taille(L, H, C, W, eqv, jours, R, TE) -> tuple[np.ndarray, np.ndarray]:
    """Meme methode que nexus.prop_comptes : taille d evaluation et taille financee choisies sur les departs 2016-2020."""
    seances = np.arange(len(jours))
    dep = seances[: len(jours) - P.HORIZON: P.PAS_DEPART]
    fin = np.array([jours[d + P.HORIZON - 1] for d in dep])
    g = P.grille(L, H, C, W, eqv, dep[fin < P.COUPURE], P.HORIZON, TE, TE, R)
    ia, ib = np.unravel_index(np.nanargmax(g), g.shape)
    return TE[ia], TE[ib]


def compositions(max_comptes=MAX_COMPTES):
    """Books testes : tous A, tous B, et melanges, de 1 a max_comptes comptes."""
    out = []
    for n in range(1, max_comptes + 1):
        for nb in range(n + 1):
            out.append(["A"] * (n - nb) + ["B"] * nb)
    return out


def main():
    ap = argparse.ArgumentParser(description="Book de plusieurs comptes Topstep avec S1 + Gotobi et M2 + Gotobi.")
    ap.add_argument("--cotations", default=os.path.join("..", "Cotations"))
    ap.add_argument("--cache", default="", help="pickle des donnees de nexus.prop_comptes (hors depot)")
    ap.add_argument("--sortie", default=os.path.join("recherche", "resultats_prop_book.txt"))
    a = ap.parse_args()
    t0 = time.time()
    lignes: list[str] = []

    def pr(s=""):
        print(s, flush=True)
        lignes.append(s)

    if a.cache and os.path.exists(a.cache):
        df_brut, df_adj, eq, trades_s1, m, brut6 = pd.read_pickle(a.cache)
    else:
        df_brut, df_adj, eq, trades_s1, m, brut6 = P.charger(a.cotations)
        if a.cache:
            pd.to_pickle((df_brut, df_adj, eq, trades_s1, m, brut6), a.cache)
    from .perso import kairos_publiees as KP
    from .perso.soixante import marche
    f_m2 = KP.trades(marche("NQ"), "K5")
    R = P.vecteur_regles(P.REGLES[REGLE])
    pr("Book de comptes Topstep 50K (Standard + perte journaliere 1 000 $), comme Kairos : plusieurs comptes en parallele")
    pr(f"(genere par python -m nexus.prop_book le {pd.Timestamp.now():%Y-%m-%d} ; regles relevees le 2026-10-25)")
    pr("  A = " + TYPES["A"] + " ; B = " + TYPES["B"] + " (M2 : a confirmer hors echantillon)")
    pr()
    cv = couvertures(trades_s1, f_m2)
    pr("Couverture entre comptes (interdite chez Topstep, suivie par utilisateur) : S1 et M2 en sens contraire au meme moment")
    pr(f"  jours de M2 {cv['jours_m2']}, jours de S1 {cv['jours_s1']}, jours communs {cv['jours_communs']} : "
       f"trades qui se chevauchent en sens CONTRAIRE {cv['jours_contraires']} ({cv['minutes_contraires'] / 60:,.0f} h), "
       f"dans le meme sens {cv['jours_meme_sens']}")
    melange_permis = cv["jours_contraires"] == 0
    pr("  -> " + ("aucun conflit : A et B peuvent cohabiter" if melange_permis else
                  "conflits : un book qui melange A et B chez Topstep enfreindrait la regle (melanges montres a titre "
                  "indicatif seulement)"))
    pr()
    for ticks, nom_cout in ((1.0, "couts de reference (1 tick + commission par cote)"), (2.0, "stress (2 ticks par cote)")):
        s1, w1, _, c1 = P.s1_un_contrat(df_brut, df_adj, eq, trades_s1, "MNQ", ticks)
        go, _, _ = P.gotobi_un_contrat(m, brut6, "6J", ticks)
        m2, _, cm = m2_un_contrat(df_brut, df_adj, f_m2, "MNQ", ticks)
        un = lambda b: pd.Series(1.0, index=b.index)
        cal = P.seances_cme(df_adj.index)
        cal = cal[(cal >= min(b.index.min() for b in (go, s1, m2))) & (cal <= max(b.index.max() for b in (go, s1, m2)))]
        jours, L, H, C, W = P.tableaux([go, s1, m2], [un(go), w1, un(m2)], cal)
        eqv = np.array([10.0, 1.0, 1.0])
        if ticks == 1.0:
            pr("Controles (critere 9)")
            pr(f"  M2 rejoue dans vectorbt sur 1 MNQ : {cm['trades_vbt']} trades vectorbt pour {cm['trades_m2']} trades du "
               f"moteur, barres exactes {cm['barres_exactes']:.1%}, ecart moyen du P&L brut par trade {cm['ecart_moyen']:.2f} $ ; "
               f"total {cm['pnl_vbt']:,.0f} $ (moteur : {cm['pnl_m2']:,.0f} $)")
            for nom_s, b in (("Gotobi 1 x 6J", go), ("S1 1 x MNQ", s1), ("M2 1 x MNQ", m2)):
                cl = b["clot"].reindex(jours).fillna(0.0)
                pr(f"  {nom_s} : {int((b['clot'] != 0).sum())} seances actives sur {len(jours)}, gain moyen {cl.mean():+.1f} $/seance, "
                   f"Sharpe {cl.mean() / cl.std() * math.sqrt(252):.2f}")
            pr(f"  calendrier : {len(jours)} seances CME de {jours[0]:%Y-%m-%d} a {jours[-1]:%Y-%m-%d} (avec ou sans trade)")
            c_sm = np.corrcoef(C[1], C[2])[0, 1]
            pr(f"  correlation journaliere S1 / M2 (1 contrat chacun) : {c_sm:.2f}")
            pr()
        # matrices par type de compte : la strategie absente a une taille nulle
        TE_A = np.array([[g, u, 0.0] for g in range(4) for u in np.arange(0, 6.01, 0.5)], float)
        TE_B = np.array([[g, 0.0, k] for g in range(4) for k in range(0, 13)], float)
        mats = {"A": (L, H, C, W, eqv), "B": (L, H, C, W, eqv)}
        tailles = {"A": choisir_taille(L, H, C, W, eqv, jours, R, TE_A), "B": choisir_taille(L, H, C, W, eqv, jours, R, TE_B)}
        lb = np.flatnonzero(np.asarray(jours >= P.COUPURE)).astype(np.int64)
        pr(f"=== {nom_cout} ===")
        for typ, (te, tf) in tailles.items():
            nom = "S1" if typ == "A" else "M2"
            k = 1 if typ == "A" else 2
            unite = " unite(s)" if typ == "A" else " MNQ"
            pr(f"  compte {typ} : taille choisie sur 2016-2020 : evaluation {int(te[0])} x 6J + {nom} {te[k]:g}{unite} ; "
               f"finance {int(tf[0])} x 6J + {nom} {tf[k]:g}{unite}")
        for decalage, nom_d in ((0, "departs simultanes"), (DECALAGE, "departs echelonnes d un mois")):
            pr(f"  -- {nom_d} (bootstrap 2021-2026, {P.B_BOOT} annees, chemin commun) --")
            pr(f"  {'book':<12}{'net moyen':>11}{'mediane':>10}{'5 %':>9}{'95 %':>9}{'perte':>7}{'frais':>9}"
               f"{'payouts':>10}{'capital moy.':>13}{'capital 95 %':>13}{'corr.':>7}")
            for comp in compositions():
                x = bootstrap_book(comp, tailles, mats, R, lb, decalage)
                nom_b = f"{comp.count('A')}A+{comp.count('B')}B"
                drap = "" if (melange_permis or comp.count("A") == 0 or comp.count("B") == 0) else " *"
                corr = f"{x['correlation_comptes']:.2f}" if np.isfinite(x["correlation_comptes"]) else "-"
                pr(f"  {nom_b:<12}{x['net_moyen']:>+11,.0f}{x['net_median']:>+10,.0f}{x['net_p5']:>+9,.0f}{x['net_p95']:>+9,.0f}"
                   f"{x['p_perte']:>7.0%}{x['frais']:>9,.0f}{x['payouts']:>10,.0f}{x['capital_moyen']:>13,.0f}"
                   f"{x['capital_p95']:>13,.0f}{corr:>7}{drap}")
            if decalage == 0:
                # temoin sans avantage pour le book le plus gros de chaque type
                L0, H0, C0 = P.sans_avantage(L, H, C)
                m0 = {"A": (L0, H0, C0, W, eqv), "B": (L0, H0, C0, W, eqv)}
                for comp in (["A"] * MAX_COMPTES, ["B"] * MAX_COMPTES):
                    x = bootstrap_book(comp, tailles, m0, R, lb, 0)
                    pr(f"  temoin sans avantage {MAX_COMPTES}{comp[0]} : net {x['net_moyen']:+,.0f} $ (mediane {x['net_median']:+,.0f}), "
                       f"perte {x['p_perte']:.0%}")
        pr("  (* : melange interdit chez Topstep si S1 et M2 se couvrent ; corr. : correlation moyenne des nets entre comptes)")
        pr()
    pr(f"(duree {time.time() - t0:.0f} s)")
    os.makedirs(os.path.dirname(a.sortie), exist_ok=True)
    with open(a.sortie, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lignes) + "\n")


if __name__ == "__main__":
    main()
