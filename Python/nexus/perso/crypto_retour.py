"""Retournement du bitcoin sur 2 heures apres un grand mouvement (De Nicola, Ledger 2021) - UN essai (n° 433).

    python -m nexus.perso.crypto_retour [--sortie resultats_crypto_retour.txt]

PROTOCOLE ECRIT LE 2026-10-22 AVANT LE CALCUL. Aucun parametre n est choisi apres avoir vu un resultat.

Source (texte complet lu) : G. De Nicola (LMU Munich), « On the Intraday Behavior of Bitcoin », Ledger 6 (2021) 58-80
(revue a comite, University of Pittsburgh). Bitcoin 2015-2018 : autocorrelation NEGATIVE des rendements a 1, 2 et 4 h,
d autant plus forte que le mouvement precedent est grand (surreaction, exces de volatilite, cascades de liquidations).
Strategie du papier (tableau 5, sans frais) : barre de 2 h, si |rendement| >= k ecarts-types, position CONTRAIRE pendant
la barre suivante ; gain moyen par trade 0,05 % (tous), 0,18 % (1 sigma), 0,30 % (2), 0,49 % (3), 0,74 % (4).
Seuils choisis par l auteur « sans regarder les donnees ». Papiers contraires lus : Kitron & Wengrowicz 2026 (15 min :
1,3 pb brut, sous les frais) ; notre fiche 4B (15 min) rejetee ; aucun contre-papier sur 2 h apres un grand mouvement.
Notre echantillon (2019-2026) est entierement posterieur au sien : test hors echantillon.
Calcul de puissance (critere 6 : effet du papier ; ecart-type et nombre de cas mesures sur nos donnees SANS la moyenne ;
couts reels trade par trade au prix du moment) : seuil 3 sigma, MBT -> t attendu 3,82 sur 2019-2026 (478 cas, 5,25
depuis le lancement du MBT en 05/2021) ; 2 sigma -> 1,24 ; 1 sigma -> negatif (frais). Seule la version 3 sigma est testee.

Regle unique, figee
  Donnees : Binance BTCUSDT au comptant, minutes datees a leur FIN (verifie : la 1re minute 04:00-04:01 UTC du
  17/08/2017, ouverte a 4 261,48 $, porte l heure 04:01), substitut du future CME (base CME - comptant ignoree).
  Barres de 2 h sur la grille UTC (00:00, 02:00, ...) : cloture = cloture de la minute finissant a la fin de la barre.
  r = ln(cloture / cloture precedente) ; sigma = ecart-type des 360 barres PRECEDENTES (30 jours, strictement passe ;
  le papier utilisait l ecart-type de tout l echantillon, ce qui anticipe) ; signal si |r| >= 3 sigma.
  Trade : position CONTRAIRE au signe de r, entree a l ouverture de la minute qui commence a la fin de la barre signal,
  sortie a la cloture de la minute qui finit 2 h plus tard.
  Heures permises (prop firm, critere 21 ; CME : dimanche 18:00 -> vendredi 17:00 ET, pause 17:00-18:00) : le trade doit
  commencer et finir entre 18:00 ET et 16:10 ET le lendemain, du dimanche soir au vendredi 16:10 ; sinon pas de trade.
  Temoin neutre : la MEME operation (contraire pendant 2 h) apres les barres SANS grand mouvement (|r| < 3 sigma), aux
  memes heures permises.
Couts (critere 8), par trade au prix d entree : MBT (0,1 BTC, tick 5 $ -> 0,50 $) : 0,50 $ + 2,50 $ par cote ;
  BTC (5 BTC, tick 5 $ -> 25 $) : 25 $ + 2,50 $ par cote ; stress 2 ticks. Critere 22 : les deux sont donnes ; le compte
  prop ne peut tenir que le MBT (le BTC fait ~400 000 $ de nominal), le verdict porte sur le MBT.
Criteres : 10-14 (criteres() de soixante, sur le rendement brut avec le cout MOYEN des trades), 16-18 (mesures() de
  prop_combinaisons sur le rendement net journalier, jours sans trade = 0, Sharpe deflate avec 433 essais) ; moities
  2019-2020 / 2021-2026 (nos donnees commencent en 2019 pour ce test).
Verification du calcul (critere 9, sans regarder le gain) : horodatage (ci-dessus) ; anticipation (prix modifies apres
  l entree -> signal inchange ; apres la sortie -> gain inchange) ; rejeu vectorbt = P&L brut du moteur ; 5 trades tires
  au hasard ; comptes (barres, signaux, trades, refus pour heures).
"""
from __future__ import annotations

import argparse
import math
import os
from datetime import datetime

import numpy as np
import pandas as pd

from .. import prop_combinaisons as PC
from .soixante import PY_DIR, criteres

try:
    import vectorbt as vbt
except ImportError:  # pragma: no cover
    vbt = None

ESSAIS = 433
SEUIL, FENETRE, DEBUT = 3.0, 360, pd.Timestamp("2019-01-01", tz="UTC")
NY = "America/New_York"
CONTRATS = {"MBT": (0.1, 0.50), "BTC": (5.0, 25.0)}      # BTC par contrat, valeur d un tick en $
COMMISSION = 2.50


def minutes() -> pd.DataFrame:
    d = pd.read_parquet(os.path.join(PY_DIR, ".cache", "binance", "BTCUSDT_1m.parquet"))
    d.index = pd.DatetimeIndex(d.index).tz_localize("UTC")          # fin de minute
    return d[["open", "close"]]


def permis(debut: pd.DatetimeIndex, fin: pd.DatetimeIndex) -> np.ndarray:
    """Trade entre 18:00 ET et 16:10 ET le lendemain, du dimanche 18:00 au vendredi 16:10, jamais le samedi."""
    a, b = debut.tz_convert(NY), fin.tz_convert(NY)
    ma, mb = a.hour * 60 + a.minute, b.hour * 60 + b.minute
    ouvert = (a.dayofweek < 5) | ((a.dayofweek == 6) & (ma >= 1080))
    meme_jour = a.normalize() == b.normalize()
    traverse_pause = meme_jour & (ma < 1080) & (mb > 970)              # commence avant 18:00 et finit apres 16:10
    entre_pause = (ma >= 970) & (ma < 1080)                            # commence entre 16:10 et 18:00
    vendredi_soir = (b.dayofweek == 4) & (mb > 970)
    return np.asarray(ouvert & ~traverse_pause & ~entre_pause & ~vendredi_soir & (b.dayofweek != 5) & (a.dayofweek != 5))


def trades(d: pd.DataFrame) -> pd.DataFrame:
    """Une ligne par barre de 2 h : signal, puis prix d entree et de sortie de la barre suivante."""
    c = d["close"]
    bornes = pd.date_range(c.index[0].ceil("2h"), c.index[-1].floor("2h"), freq="2h")
    # cloture de la barre [T-2h, T) = cloture de la minute finissant a T (ou derniere avant)
    cl = c.reindex(bornes, method="ffill")
    r = np.log(cl).diff()
    sigma = r.rolling(FENETRE, min_periods=FENETRE).std().shift(1)
    z = r / sigma
    ouv = d["open"]
    debut = bornes                                                    # le trade commence a la fin de la barre signal
    fin = bornes + pd.Timedelta(hours=2)
    # entree : ouverture de la minute qui COMMENCE a `debut` = minute datee debut + 1 min
    pe = ouv.reindex(debut + pd.Timedelta(minutes=1)).to_numpy()
    ps = c.reindex(fin).to_numpy()
    f = pd.DataFrame(dict(r=r.to_numpy(), sigma=sigma.to_numpy(), z=z.to_numpy(), pe=pe, ps=ps), index=bornes)
    f["fin"] = fin
    f["permis"] = permis(pd.DatetimeIndex(debut), pd.DatetimeIndex(fin))
    f["sens"] = -np.sign(f["r"])
    f["brut_pb"] = f["sens"] * np.log(f["ps"] / f["pe"]) * 1e4
    f["valide"] = f["z"].notna() & np.isfinite(f["pe"]) & np.isfinite(f["ps"]) & (f.index >= DEBUT)
    f["signal"] = f["valide"] & (f["z"].abs() >= SEUIL)
    f["trade"] = f["signal"] & f["permis"]
    f["temoin"] = f["valide"] & (f["z"].abs() < SEUIL) & f["permis"]
    return f


def cout_pb(prix: pd.Series, contrat: str, ticks: int = 1) -> pd.Series:
    q, tick = CONTRATS[contrat]
    return 2 * (ticks * tick + COMMISSION) / (q * prix) * 1e4


def serie_journaliere(f: pd.DataFrame, contrat: str) -> pd.Series:
    """Rendement net (fraction) agrege par jour de bourse ET (le jour de la sortie), 0 les jours sans trade."""
    t = f[f["trade"]]
    net = (np.exp(t["brut_pb"] / 1e4) - 1) - cout_pb(t["pe"], contrat) / 1e4
    jour_sortie = pd.DatetimeIndex(t["fin"]).tz_convert(NY).tz_localize(None).normalize()
    r = pd.Series(net.to_numpy(), index=jour_sortie).groupby(level=0).sum()
    cal = pd.bdate_range(DEBUT.tz_localize(None), f.index[-1].tz_localize(None))
    return r.reindex(cal, fill_value=0.0)


# =============================================================================
#  Verifications (critere 9)
# =============================================================================
def verif_anticipation(d: pd.DataFrame, f: pd.DataFrame) -> str:
    t = f[f["trade"]]
    x = t.index[len(t) // 2]
    alt = d.copy()
    apres = alt.index > x + pd.Timedelta(minutes=1)
    alt.loc[apres, ["open", "close"]] *= 1.05
    g = trades(alt)
    a = bool(g.loc[x, "signal"] == f.loc[x, "signal"]) and math.isclose(g.loc[x, "z"], f.loc[x, "z"], rel_tol=1e-12)
    alt = d.copy()
    alt.loc[alt.index > f.loc[x, "fin"], ["open", "close"]] *= 1.05
    g = trades(alt)
    b = math.isclose(g.loc[x, "brut_pb"], f.loc[x, "brut_pb"], rel_tol=1e-12)
    return (f"(b) anticipation ({x:%Y-%m-%d %H:%M} UTC) : prix +5 % apres l entree -> signal {'INCHANGE' if a else 'CHANGE (BUG)'} ; "
            f"prix +5 % apres la sortie -> gain {'INCHANGE' if b else 'CHANGE (BUG)'}")


def verif_vectorbt(f: pd.DataFrame) -> str:
    if vbt is None:
        return "(c) vectorbt absent"
    t = f[f["trade"]]
    moteur = (t["sens"] * (t["ps"] - t["pe"])).to_numpy()
    ts = np.r_[t.index.asi8, (pd.DatetimeIndex(t["fin"]).asi8 - 1)]
    px = np.r_[t["pe"].to_numpy(), t["ps"].to_numpy()]
    tl = np.r_[t["sens"].to_numpy(), -t["sens"].to_numpy()]
    o = np.argsort(ts, kind="stable")
    idx = pd.to_datetime(ts[o])
    pf = vbt.Portfolio.from_orders(pd.Series(px[o], index=idx), size=pd.Series(tl[o], index=idx), init_cash=1e12,
                                   fees=0.0, freq="1min")
    pnl = pf.trades.records_readable.sort_values("Entry Timestamp")["PnL"].to_numpy()
    ecart = float(np.max(np.abs(pnl - moteur))) if len(pnl) == len(moteur) else math.inf
    return (f"(c) rejeu vectorbt : {len(pnl)} trades contre {len(moteur)} au moteur, ecart maximal de P&L brut "
            f"{ecart:.8f} $ par BTC -> {'IDENTIQUE' if ecart < 1e-6 else 'DIFFERENT (BUG)'}")


def verif_cinq(f: pd.DataFrame) -> list[str]:
    out = ["(d) 5 trades tires au hasard (graine 7), a verifier a la main (prix BTC au comptant, frais MBT) :"]
    for x in f[f["trade"]].sample(5, random_state=7).sort_index().itertuples():
        e = x.Index.tz_convert(NY)
        s = pd.Timestamp(x.fin).tz_convert(NY)
        q, tick = CONTRATS["MBT"]
        brut = x.sens * (x.ps - x.pe) * q
        frais = 2 * (tick + COMMISSION)
        out.append(f"    barre close a {x.Index:%Y-%m-%d %H:%M} UTC : r {x.r * 100:+.2f} % = {x.z:+.1f} sigma -> "
                   f"{'VENTE' if x.sens < 0 else 'ACHAT'} {e:%a %H:%M} ET a {x.pe:.2f} -> {s:%H:%M} ET a {x.ps:.2f} | "
                   f"MBT brut {brut:+.2f} $ - frais {frais:.2f} $ = {brut - frais:+.2f} $")
    return out


# =============================================================================
#  Etude
# =============================================================================
def etude(sortie: str | None = None, log=print) -> dict:
    t0 = datetime.now()
    L: list[str] = []
    pr = L.append
    d = minutes()
    f = trades(d)
    pr("=" * 116)
    pr(" RETOURNEMENT DU BITCOIN SUR 2 H APRES UN MOUVEMENT DE 3 ECARTS-TYPES (De Nicola, Ledger 2021) - UN ESSAI (n° 433)")
    pr("=" * 116)
    pr("Regle figee : barre de 2 h (UTC), |r| >= 3 sigma (sigma des 30 jours precedents) -> position contraire 2 h ;")
    pr("heures prop firm seulement ; temoin : meme operation apres les barres sans grand mouvement.\n")
    pr("Verification du calcul (critere 9)")
    pr("  (a) horodatage : 1re minute Binance (04:00-04:01 UTC le 17/08/2017, ouverture 4 261,48 $) datee 04:01 -> "
       f"{'OK' if d.index[0] == pd.Timestamp('2017-08-17 04:01', tz='UTC') and d['open'].iloc[0] == 4261.48 else 'ECART'}")
    pr("  " + verif_anticipation(d, f))
    pr("  " + verif_vectorbt(f))
    for s in verif_cinq(f):
        pr("  " + s)
    v = f[f["valide"]]
    pr(f"  (e) comptes : {len(v)} barres de 2 h depuis 2019 ; {int(v['signal'].sum())} signaux >= 3 sigma, dont "
       f"{int(v['trade'].sum())} aux heures permises ({int((v['signal'] & ~v['permis']).sum())} refuses) ; "
       f"{int(v['temoin'].sum())} barres temoins\n")
    res = {}
    t, g = f[f["trade"]], f[f["temoin"]]
    for contrat in ("MBT", "BTC"):
        c = cout_pb(t["pe"], contrat)
        c2 = cout_pb(t["pe"], contrat, 2)
        sans_tz = lambda s: s.set_axis(pd.DatetimeIndex(s.index).tz_localize(None))  # noqa: E731 (criteres : dates naives)
        crit = criteres(sans_tz(t["brut_pb"]), sans_tz(g["brut_pb"]), float(c.mean()))
        net = t["brut_pb"] - c
        crit_net = dict(n1=net[net.index < pd.Timestamp("2021-01-01", tz="UTC")].mean(),
                        n2=net[net.index >= pd.Timestamp("2021-01-01", tz="UTC")].mean())
        x = PC.mesures(serie_journaliere(f, contrat), ESSAIS)
        res[contrat] = dict(crit=crit, mesures=x)
        pr(f"--- {contrat}{' (contrat du compte : verdict)' if contrat == 'MBT' else ' (contrat de base, intenable en prop)'} : "
           f"{crit['n']} trades")
        pr(f"    brut {crit['moyenne']:+.2f} pb (t {crit['t']:+.2f}) | 2019-2020 {crit['m1']:+.2f} (t {crit['t1']:+.2f}) | "
           f"2021-2026 {crit['m2']:+.2f} (t {crit['t2']:+.2f})")
        pr(f"    temoin (sans grand mouvement) {crit['temoin']:+.2f} pb -> Welch {crit['welch']:+.2f}")
        pr(f"    couts moyens {c.mean():.1f} pb -> net {net.mean():+.2f} pb (t {net.mean() / net.std(ddof=1) * math.sqrt(len(net)):+.2f}) ; "
           f"2019-2020 {crit_net['n1']:+.2f} | 2021-2026 {crit_net['n2']:+.2f} ; sans les 3 meilleurs "
           f"{net.drop(net.nlargest(3).index).mean():+.2f} pb ; stress 2 ticks {(t['brut_pb'] - c2).mean():+.2f} pb")
        pr(f"    vectorbt : Sharpe {x['sharpe']:+.2f} [IC 95 % {x['ic_bas']:+.2f} ; {x['ic_haut']:+.2f}] | avant 2021 "
           f"{x['sharpe_p1']:+.2f} | apres {x['sharpe_p2']:+.2f} | deflate ({ESSAIS} essais) {x['dsr']:.2f} | perte max {x['perte_max']:.1%}")
        ans = net.groupby(net.index.year).sum()
        pr(f"    par annee (net, pb cumules) : " + " ; ".join(f"{a} {v:+.0f}" for a, v in ans.items()))
        pr(f"    heures en position : {crit['n'] * 2 / ((f.index[-1] - DEBUT).days / 365.25):.0f} h/an")
        echecs = [k for k, ok in crit["tests"].items() if not ok]
        echecs += [] if x["ic_bas"] > 0 else ["IC bas du Sharpe > 0"]
        echecs += [] if (x["sharpe_p1"] > 0 and x["sharpe_p2"] > 0) else ["Sharpe > 0 avant ET apres 2021"]
        echecs += [] if x["dsr"] >= 0.95 else ["Sharpe deflate >= 0,95"]
        res[contrat]["echecs"] = echecs
        pr(f"    VERDICT : {'PASSE les criteres 10-18' if not echecs else 'ECHOUE (' + ' ; '.join(echecs) + ')'}\n")
    pr("Synthese : " + ("l essai MBT passe les criteres 10-18 ; restent la correlation (n° 20) et ta validation."
                        if not res["MBT"]["echecs"] else "REJETEE (l essai MBT echoue). Aucune variante ne sera testee."))
    pr(f"Calcul en {(datetime.now() - t0).total_seconds():.0f} s.")
    sortie = sortie or os.path.join(PY_DIR, "recherche", "resultats_crypto_retour.txt")
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
