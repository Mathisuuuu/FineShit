"""Sentiment de nuit des ETF sectoriels -> retournement des futures d indices pendant la seance (UN essai).

    python -m nexus.perso.etf_nuit [--sortie resultats_etf_nuit.txt]

PROTOCOLE ECRIT LE 2026-10-22 AVANT LE CALCUL. Aucun parametre n est choisi apres avoir vu un resultat.

Origine et derogation (demande de l utilisateur du 2026-10-22)
  Hypothese n° 39 du registre : Lee, Liao & Lee, « Overnight returns of industry exchange-traded funds, investor
  sentiment, and futures market returns », Journal of Futures Markets 42 (6), 2022 (doi 10.1002/fut.22321). Seul le
  RESUME est lu (texte payant) : le sentiment mesure par la « comouvement relative » des rendements de nuit des ETF
  sectoriels predit (Granger, hors echantillon) les rendements des futures d indices et des futures VIX. Le resume ne
  donne ni la formule exacte, ni le sens, ni l horizon, ni la taille de l effet.
  L utilisateur demande une version INTRADAY sans surajustement. Deux criteres de la methode ne sont donc PAS remplis
  et le test est fait par derogation explicite : n° 3 (texte complet non lu) et n° 6 (aucun effet publie sur notre objet
  pour le calcul de puissance). Le test compte pour UN essai : ESSAIS_PROGRAMME 430 -> 431.

Regle unique, figee (aucune grille, aucune variante)
  Mesure (formule la plus simple de « comouvement relative ») : pour les 9 Select Sector SPDR d origine (XLB XLE XLF XLI
  XLK XLP XLU XLV XLY ; XLRE et XLC exclus, historiques plus courts), rendement de nuit ON_i = ouverture(t) / cloture(t-1)
  - 1 (barres quotidiennes Alpaca ; ouverture = premier prix de 9:30, controle contre les minutes SPY) ;
      C_t = | moyenne_i ON_i | / moyenne_i | ON_i |  (entre 0 et 1 ; 1 = tous les secteurs ont bouge dans le meme sens) ;
      D_t = signe( moyenne_i ON_i )  (sens du sentiment de la nuit).
  Jour de sentiment : C_t >= 80e centile des C des 252 jours de bourse PRECEDENTS (fenetre glissante stricte, 252 jours
  d historique exiges : debut effectif en 2017).
  Sens : CONTRE le sentiment, position = -D_t. Fondement : les mouvements de nuit portes par le sentiment et l attention
  se retournent pendant la seance (Berkman, Koch, Tuttle & Zhang, JFQA 2012 ; Lou, Polk & Skouras, JFE 2019 « A tug of
  war »). Le sens n est PAS choisi sur nos donnees ; le sens oppose ne sera pas teste.
  Execution : ES, entree au prix de 9:35 ET (ouverture de la barre qui commence a 9:35 : 5 minutes apres l ouverture
  des ETF, signal connu), sortie au prix de 16:00 ET ; a plat avant 16:10, jamais la nuit ni le week-end (critere 21).
  Jours exclus : fetes et seances courtes (pas de prix a 16:00), changement d echeance entre 9:35 et 16:00, lundis de
  detachement trimestriel des SPDR (lundi entre le 18 et le 24 de mars, juin, septembre, decembre : une baisse commune
  de tous les secteurs y serait mecanique).
  Temoin neutre : la MEME operation (contre D_t, 9:35 -> 16:00) les jours SANS sentiment (C_t sous le 80e centile).
  Repliques (pas des essais) : NQ et YM, meme signal. Contrats du compte (critere 22) : MES, MNQ, MYM, leurs couts.
Couts (critere 8) : 1 tick + 2,50 $ par cote (stress 2 ticks par cote).
Criteres : n° 10-14 (criteres() de soixante), n° 16-18 avec mesures() de prop_combinaisons (rendements journaliers,
  jours sans position = 0, Sharpe deflate avec 431 essais), n° 19 (heures par an), n° 20 (correlation) seulement si le
  reste passe.
Verification du calcul (critere 9, sans regarder le gain) :
  (a) horodatage : ouverture quotidienne des ETF = ouverture de la minute 9:30-9:31 de SPY (Alpaca) ;
  (b) anticipation : les signaux jusqu a une date ne changent pas si l on modifie les prix des ETF et d ES APRES cette
      date ;
  (c) rejeu vectorbt (Portfolio.from_orders, 1 contrat, sans frais) = P&L brut du moteur trade par trade ;
  (d) 5 trades tires au hasard (graine 7) imprimes en detail pour verification a la main ;
  (e) comptes : jours, jours de signal, trades, exclusions par motif.
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
from .soixante import COMMISSION, COUTS, ET, PY_DIR, criteres, marche, prix_a, contrats, jours_ouvres_us

try:
    import vectorbt as vbt
except ImportError:  # pragma: no cover
    vbt = None

COTATIONS = os.path.normpath(os.path.join(PY_DIR, "..", "Cotations", "alpaca", "actions_jour"))
SECTEURS = "XLB XLE XLF XLI XLK XLP XLU XLV XLY".split()
CENTILE, FENETRE = 0.80, 252
ENTREE, SORTIE_H = (9, 35), (16, 0)
ESSAIS = 431
MICRO = {"ES": ("MES", 5.0), "NQ": ("MNQ", 2.0), "YM": ("MYM", 0.5)}


# =============================================================================
#  Signal
# =============================================================================
def etf_jour(sym: str) -> pd.DataFrame:
    d = pd.read_csv(os.path.join(COTATIONS, f"{sym}.csv"), parse_dates=["Date"]).set_index("Date").sort_index()
    return d[["Open", "Close"]]


def signal(etf: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """C_t, D_t, seuil (80e centile des 252 jours precedents) et jour de sentiment. N utilise que l ouverture du jour t
    et les clotures jusqu a t-1."""
    on = pd.DataFrame({s: d["Open"] / d["Close"].shift(1) - 1 for s, d in etf.items()}).dropna()
    moy, absmoy = on.mean(axis=1), on.abs().mean(axis=1)
    c = (moy.abs() / absmoy).where(absmoy > 0)
    seuil = c.shift(1).rolling(FENETRE, min_periods=FENETRE).quantile(CENTILE)
    return pd.DataFrame(dict(C=c, D=np.sign(moy), seuil=seuil, sentiment=(c >= seuil) & seuil.notna(), on_moy=moy))


def lundis_detachement(index: pd.DatetimeIndex) -> pd.DatetimeIndex:
    return pd.DatetimeIndex([x for x in index if x.month in (3, 6, 9, 12) and x.weekday() == 0 and 18 <= x.day <= 24])


# =============================================================================
#  Trades
# =============================================================================
def fenetre(m, jours: pd.DatetimeIndex) -> pd.DataFrame:
    """Prix reels d entree (9:35) et de sortie (16:00), instants, motif d exclusion."""
    ta, tb = instants(jours, *ENTREE, ET), instants(jours, *SORTIE_H, ET)
    pa, ia = prix_a(m, ta)
    pb, ib = prix_a(m, tb)
    ok = np.isfinite(pa) & np.isfinite(pb) & (ia >= 0) & (ib >= 0)
    cid = contrats(m)
    roll = np.zeros(len(jours), bool)
    roll[ok] = cid[ib[ok]] != cid[ia[ok]]
    off = getattr(m, "offset", np.zeros(m.n))
    reel_a = np.where(ok, pa - np.where(ia >= 0, off[np.clip(ia, 0, None)], 0), np.nan)
    reel_b = np.where(ok, pb - np.where(ib >= 0, off[np.clip(ib, 0, None)], 0), np.nan)
    motif = np.where(~ok, "prix absent (fete, seance courte)", np.where(roll, "changement d echeance", ""))
    return pd.DataFrame(dict(ta=ta, tb=tb, pa=reel_a, pb=reel_b, motif=motif), index=jours)


def cout_pb(root: str, prix: float, ticks: int = 1, micro: bool = False) -> float:
    tick, pv = COUTS[root][0], COUTS[root][1]
    if micro:
        pv = MICRO[root][1]
    return (2 * ticks * tick + 2 * COMMISSION / pv) / prix * 1e4


def construire(root: str, sig: pd.DataFrame, exclus: pd.DatetimeIndex):
    m = marche(root)
    jours = jours_ouvres_us(m)
    jours = jours[(jours >= sig.index[0]) & (jours <= sig.index[-1])]
    f = fenetre(m, jours).join(sig, how="left")
    f.loc[f.index.isin(exclus) & (f["motif"] == ""), "motif"] = "detachement trimestriel des SPDR"
    f.loc[f["seuil"].isna() & (f["motif"] == ""), "motif"] = "signal indisponible (historique < 252 j ou ETF absent)"
    f["r_pb"] = np.log(f["pb"] / f["pa"]) * 1e4
    f["sens"] = -f["D"]
    f["brut_pb"] = f["sens"] * f["r_pb"]
    return m, f


# =============================================================================
#  Verifications (critere 9)
# =============================================================================
def verif_horodatage() -> str:
    from .qf import alpaca_minutes
    d = pd.read_csv(os.path.join(COTATIONS, "SPY.csv"), parse_dates=["Date"]).set_index("Date")
    mm = alpaca_minutes("SPY")
    idx = pd.DatetimeIndex(mm.index).tz_localize("UTC").tz_convert(ET)
    sel = (idx.hour == 9) & (idx.minute == 31)
    s = pd.Series(mm["open"].to_numpy()[sel], index=idx[sel].tz_localize(None).normalize())
    j = d.join(s.rename("o"), how="inner")
    e = (j["Open"] / j["o"] - 1).abs()
    return (f"(a) ouverture quotidienne SPY = ouverture de la minute 9:30-9:31 : {len(j)} jours, ecart median "
            f"{e.median() * 1e4:.2f} pb, 95e centile {e.quantile(.95) * 1e4:.2f} pb")


def verif_anticipation(etf: dict, sig: pd.DataFrame) -> str:
    coupe = sig.index[len(sig) // 2]
    alt = {s: d.copy() for s, d in etf.items()}
    rng = np.random.default_rng(1)
    for d in alt.values():
        apres = d.index > coupe
        d.loc[apres, "Open"] *= rng.uniform(0.9, 1.1, apres.sum())
        d.loc[apres, "Close"] *= rng.uniform(0.9, 1.1, apres.sum())
    s2 = signal(alt)
    a = sig.loc[sig.index <= coupe, ["sentiment", "D"]]
    b = s2.loc[s2.index <= coupe, ["sentiment", "D"]]
    egal = a.equals(b)
    return (f"(b) anticipation : prix des ETF modifies apres le {coupe:%Y-%m-%d} -> signaux jusqu a cette date "
            f"{'IDENTIQUES' if egal else 'DIFFERENTS (BUG)'} ({len(a)} jours) ; ES n entre pas dans le signal")


def verif_vectorbt(root: str, f: pd.DataFrame) -> str:
    if vbt is None:
        return "(c) vectorbt absent : rejeu non fait"
    t = f[f["trade"]]
    pv = COUTS[root][1]
    moteur = (t["sens"] * (t["pb"] - t["pa"]) * pv).to_numpy()
    ts = np.r_[t["ta"].to_numpy(), t["tb"].to_numpy()]
    px = np.r_[t["pa"].to_numpy(), t["pb"].to_numpy()]
    taille = np.r_[t["sens"].to_numpy(), -t["sens"].to_numpy()]
    o = np.argsort(ts, kind="stable")
    prix = pd.Series(px[o] * pv, index=pd.to_datetime(ts[o]))
    pf = vbt.Portfolio.from_orders(prix, size=pd.Series(taille[o], index=prix.index), init_cash=1e9, fees=0.0,
                                   freq="1min")
    rec = pf.trades.records_readable
    pnl_vbt = rec.sort_values("Entry Timestamp")["PnL"].to_numpy()
    ecart = float(np.max(np.abs(pnl_vbt - moteur))) if len(pnl_vbt) == len(moteur) else math.inf
    return (f"(c) rejeu vectorbt : {len(pnl_vbt)} trades contre {len(moteur)} au moteur, ecart maximal de P&L brut "
            f"{ecart:.6f} $ -> {'IDENTIQUE' if ecart < 1e-6 else 'DIFFERENT (BUG)'}")


def verif_cinq(root: str, f: pd.DataFrame) -> list[str]:
    t = f[f["trade"]]
    tick, pv = COUTS[root][0], COUTS[root][1]
    out = ["(d) 5 trades tires au hasard (graine 7), a verifier a la main :"]
    for d in t.sample(5, random_state=7).sort_index().itertuples():
        ha = pd.Timestamp(d.ta).tz_localize("UTC").tz_convert(ET)
        hb = pd.Timestamp(d.tb).tz_localize("UTC").tz_convert(ET)
        brut = d.sens * (d.pb - d.pa) * pv
        frais = 2 * (tick * pv + COMMISSION)
        out.append(f"    {d.Index:%Y-%m-%d} | C {d.C:.3f} >= seuil {d.seuil:.3f} | nuit des secteurs {d.on_moy * 100:+.3f} % "
                   f"-> {'VENTE' if d.sens < 0 else 'ACHAT'} | entree {ha:%H:%M} ET a {d.pa:.2f} | sortie {hb:%H:%M} ET a "
                   f"{d.pb:.2f} | brut {brut:+.2f} $ - frais {frais:.2f} $ = {brut - frais:+.2f} $")
    return out


# =============================================================================
#  Etude
# =============================================================================
def serie_journaliere(f: pd.DataFrame, cout: float) -> pd.Series:
    """Rendement net du jour (fraction), 0 sans position, sur les jours de bourse observables."""
    base = f[f["motif"].isin(["", "detachement trimestriel des SPDR"]) | f["trade"]]
    r = pd.Series(0.0, index=base.index)
    t = f[f["trade"]]
    r.loc[t.index] = (np.exp(t["brut_pb"] / 1e4) - 1) - cout / 1e4
    return r


def etude(sortie: str | None = None, log=print) -> dict:
    t0 = datetime.now()
    L: list[str] = []
    pr = L.append
    etf = {s: etf_jour(s) for s in SECTEURS}
    sig = signal(etf)
    exclus = lundis_detachement(sig.index)
    pr("=" * 116)
    pr(" SENTIMENT DE NUIT DES ETF SECTORIELS -> RETOURNEMENT DES FUTURES D INDICES (9:35 -> 16:00 ET) - UN ESSAI (n° 431)")
    pr("=" * 116)
    pr("Derogation demandee par l utilisateur : texte complet non lu (critere 3), pas de calcul de puissance possible (critere 6).")
    pr(f"Regle figee : C = |moyenne| / moyenne des |rendements de nuit| des 9 SPDR sectoriels ; jour de sentiment si C >= "
       f"{CENTILE:.0%} centile des {FENETRE} jours precedents ; position CONTRE le sens de la nuit, 9:35 -> 16:00 ET.\n")
    pr("Verification du calcul (critere 9)")
    pr("  " + verif_horodatage())
    pr("  " + verif_anticipation(etf, sig))
    res = {}
    for root in ("ES", "NQ", "YM"):
        m, f = construire(root, sig, exclus)
        f["trade"] = (f["motif"] == "") & f["sentiment"].fillna(False).astype(bool) & f["brut_pb"].notna()
        temoin = (f["motif"] == "") & ~f["sentiment"].fillna(False).astype(bool) & f["brut_pb"].notna()
        prix = float(np.nanmedian(f.loc[f["trade"], "pa"]))
        c1, c2 = cout_pb(root, prix), cout_pb(root, prix, ticks=2)
        cm = cout_pb(root, prix, micro=True)
        crit = criteres(f.loc[f["trade"], "brut_pb"], f.loc[temoin, "brut_pb"], c1)
        r = serie_journaliere(f, c1)
        x = PC.mesures(r, ESSAIS)
        xm = PC.mesures(serie_journaliere(f, cm), ESSAIS)
        res[root] = dict(f=f, crit=crit, mesures=x, micro=xm, cout=c1, stress=c2, cout_micro=cm)
        if root == "ES":
            pr("  " + verif_vectorbt(root, f))
            for s in verif_cinq(root, f):
                pr("  " + s)
            motifs = f["motif"].replace("", "retenu").value_counts()
            pr(f"  (e) comptes ES : {len(f)} jours de bourse {f.index[0]:%Y-%m-%d} -> {f.index[-1]:%Y-%m-%d} ; "
               + " ; ".join(f"{k} {v}" for k, v in motifs.items()))
            pr(f"      jours de sentiment retenus (trades) {int(f['trade'].sum())}, jours temoins {int(temoin.sum())} ; "
               f"part des jours de sentiment {f['trade'].sum() / max(1, f['trade'].sum() + temoin.sum()):.1%} (attendu ~20 %)\n")
        net = f.loc[f["trade"], "brut_pb"] - c1
        pr(f"--- {root}{' (ESSAI)' if root == 'ES' else ' (replique, pas un essai)'} : {crit['n']} trades")
        pr(f"    brut {crit['moyenne']:+.2f} pb (t {crit['t']:+.2f}) | 2016-2020 {crit['m1']:+.2f} (t {crit['t1']:+.2f}) | "
           f"2021-2026 {crit['m2']:+.2f} (t {crit['t2']:+.2f})")
        pr(f"    temoin (jours sans sentiment) {crit['temoin']:+.2f} pb -> Welch {crit['welch']:+.2f}")
        pr(f"    cout aller-retour {c1:.2f} pb -> net {crit['net']:+.2f} pb ; sans les 3 meilleurs jours {crit['sans3']:+.2f} pb ; "
           f"stress 2 ticks {crit['moyenne'] - c2:+.2f} pb ; gain total {net.sum():+.0f} pb")
        pr(f"    vectorbt ({root}, 1 tick) : Sharpe {x['sharpe']:+.2f} [IC 95 % {x['ic_bas']:+.2f} ; {x['ic_haut']:+.2f}] | "
           f"avant 2021 {x['sharpe_p1']:+.2f} | apres {x['sharpe_p2']:+.2f} | deflate ({ESSAIS} essais) {x['dsr']:.2f} | "
           f"perte max {x['perte_max']:.1%}")
        pr(f"    micro {MICRO[root][0]} (cout {cm:.2f} pb) : Sharpe {xm['sharpe']:+.2f} [IC bas {xm['ic_bas']:+.2f}] | "
           f"deflate {xm['dsr']:.2f}")
        pr(f"    heures en position : {crit['n'] * 6.42 / max(1e-9, (f.index[-1] - f.index[0]).days / 365.25):.0f} h/an")
        echecs = [k for k, v in crit["tests"].items() if not v]
        if not (x["ic_bas"] > 0):
            echecs.append("IC bas du Sharpe > 0")
        if not (x["sharpe_p1"] > 0 and x["sharpe_p2"] > 0):
            echecs.append("Sharpe > 0 avant ET apres 2021")
        if not (x["dsr"] >= 0.95):
            echecs.append("Sharpe deflate >= 0,95")
        res[root]["echecs"] = echecs
        pr(f"    VERDICT : {'PASSE les criteres 10-18' if not echecs else 'ECHOUE (' + ' ; '.join(echecs) + ')'}\n")
    v = res["ES"]["echecs"]
    pr("Synthese : " + ("l essai ES passe les criteres 10-18 ; restent la correlation (n° 20) et la validation."
                        if not v else "REJETEE (l essai ES echoue). Aucune variante ne sera testee (pas de surajustement)."))
    pr(f"Calcul en {(datetime.now() - t0).total_seconds():.0f} s.")
    sortie = sortie or os.path.join(PY_DIR, "recherche", "resultats_etf_nuit.txt")
    with open(sortie, "w", encoding="utf-8") as fh:
        fh.write("\n".join(L) + "\n")
    log("\n".join(L))
    return res


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--sortie", default=None)
    a = ap.parse_args(argv)
    etude(a.sortie)


if __name__ == "__main__":
    main()
