"""Recalcul independant de la fiche 16 (Noise Area), pour verifier le moteur.

Second programme ecrit sans le noyau numba ni nexus.intraday (seul le calendrier des feries NYSE est
partage) : rolls, heure de New York, zone de bruit, VWAP, taille, controles toutes les 30 min, ordres a
l ouverture de la minute suivante, sortie a la cloture, couts. Compare ensuite seance par seance avec le
moteur lance sur les memes donnees (reglage du papier, 1 M$).

    python outils/recalcul_independant_fiche16.py --donnees ../../cotations/indices --symbole NQ

Attendu : 0 seance differente et la meme equity finale.
"""
import argparse, math, os, sys
import numpy as np, pandas as pd
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from nexus import data as D
from nexus.intraday import nyse_holidays          # seul emprunt : la liste des feries
from nexus.strategies import get
from nexus.strategies.s16_noisearea import SPECS

ap = argparse.ArgumentParser()
ap.add_argument("--donnees", required=True, help="dossier des barres 1 minute Parquet (ex. Cotations/indices)")
ap.add_argument("--symbole", default="NQ")
args = ap.parse_args()
SYM = args.symbole.upper()
_, PV, _, COMM, _, SLIP_TICKS = SPECS[SYM]
SLIP_PT = SLIP_TICKS * SPECS[SYM][2]
fichier = next(os.path.join(r, f) for r, _, fs in os.walk(args.donnees) for f in fs
               if f.lower().endswith(".parquet") and D.symbol_from_filename(f).upper() == SYM)
raw = pd.read_parquet(fichier)[["open", "high", "low", "close", "volume"]]
# 1. rolls : saut a minuit UTC dominant dans le mois d echeance -> prix anterieurs x rapport
t = raw.index
prev = t.to_series().shift(1)
cand = (t.normalize() != prev.dt.normalize()) & ((t.to_series() - prev) <= pd.Timedelta(minutes=30))
g = np.log(raw["open"] / raw["close"].shift(1))[cand.values]
fac = pd.Series(1.0, index=raw.index)
nroll = 0
for (y, m), grp in g[(g.index.month % 3 == 0) & (g.index.day <= 25)].groupby([g.index[(g.index.month % 3 == 0) & (g.index.day <= 25)].year, g.index[(g.index.month % 3 == 0) & (g.index.day <= 25)].month]):
    a = grp.abs().sort_values(ascending=False)
    if len(a) >= 2 and a.iloc[0] >= 5e-4 and a.iloc[0] >= 4 * a.iloc[1]:
        fac[fac.index < a.index[0]] *= math.exp(grp[a.index[0]])
        nroll += 1
adj = raw.copy()
for c in ("open", "high", "low", "close"):
    adj[c] = raw[c] * fac
# 2. heure de New York, barre datee a sa fin, seance 9:31-16:00
ny = adj.copy()
ny.index = (adj.index + pd.Timedelta(minutes=1)).tz_convert("America/New_York").tz_localize(None)
mins = ny.index.hour * 60 + ny.index.minute
ny = ny[(mins > 570) & (mins <= 960) & (ny.index.dayofweek < 5)]
ny["jour"] = ny.index.normalize()
ny["m"] = ny.index.hour * 60 + ny.index.minute - 570          # 1..390
ny = ny[~ny["jour"].isin(nyse_holidays("2016-01-01", "2026-12-31"))]
info = ny.groupby("jour")["m"].agg(["min", "max"])
apres15 = ny[ny["m"] > 330].groupby("jour").size().reindex(info.index).fillna(0)
complet = info["max"] >= 386
demi = (~complet) & (apres15 == 0) & (info["max"] >= 206)
ok = (info["min"] <= 5) & (complet | demi)
jours = info.index[ok]
fin = pd.Series(np.where(complet[ok], 390, 210), index=jours)
P = {k: ny.pivot_table(index="jour", columns="m", values=k, aggfunc="last").reindex(index=jours, columns=range(1, 391)) for k in ("open", "high", "low", "close", "volume")}
C = P["close"].ffill(axis=1)
first_open = P["open"].bfill(axis=1).iloc[:, 0]
O = P["open"].where(P["open"].notna(), C.shift(1, axis=1))
O.iloc[:, 0] = first_open
C = C.fillna(pd.DataFrame(np.repeat(first_open.values[:, None], 390, 1), index=jours, columns=C.columns))
for d in jours:                                                   # rien apres la fin de seance
    if fin[d] == 210:
        C.loc[d, 211:] = np.nan; O.loc[d, 211:] = np.nan
H = P["high"].where(P["high"].notna(), np.maximum(O, C)); L = P["low"].where(P["low"].notna(), np.minimum(O, C))
V = P["volume"].fillna(0.0)
# 3. zone de bruit (14 observations PRECEDENTES par minute), VWAP, vol 14 j
ouv = O.iloc[:, 0]
cl = pd.Series([C.loc[d, fin[d]] for d in jours], index=jours)
pc = cl.shift(1)
move = (C.div(ouv, axis=0) - 1).abs()
sig = pd.DataFrame({c: move[c].dropna().rolling(14).mean().shift(1).reindex(jours) for c in move.columns})
tp = (H + L + C) / 3
vwap = (tp * V).cumsum(axis=1) / V.cumsum(axis=1)
vol = (cl / pc - 1).rolling(14).std().shift(1)
lev = np.minimum(0.02 / vol, 4.0)
# 4. simulation : un controle par demi-heure, ordre a l ouverture de la minute suivante, sortie a la cloture
eq, rets, trades = 1e6, {}, 0
for d in jours:
    if not (np.isfinite(lev[d]) and np.isfinite(pc[d])):
        rets[d] = 0.0; continue
    ctrl = [m for m in range(30, fin[d], 30)]
    if not all(np.isfinite(sig.loc[d, m]) for m in ctrl):
        rets[d] = 0.0; continue
    u = math.floor(eq * lev[d] / (ouv[d] * PV) + 0.5)
    haut, bas = max(ouv[d], pc[d]), min(ouv[d], pc[d])
    pos, pnl, cout = 0, 0.0, 0.0
    entree = None
    for m in ctrl:
        c, vw, s = C.loc[d, m], vwap.loc[d, m], sig.loc[d, m]
        ub, lb = haut * (1 + s), bas * (1 - s)
        cible = u if (c > ub and c > vw) else (-u if (c < lb and c < vw) else 0)
        if cible != pos:
            px = O.loc[d, m + 1]
            if pos != 0:
                pnl += pos * (px - entree) * PV; trades += 1
            cout += abs(cible - pos) * (COMM + SLIP_PT * PV)
            pos, entree = cible, px
    if pos != 0:
        px = C.loc[d, fin[d]]
        pnl += pos * (px - entree) * PV; trades += 1
        cout += abs(pos) * (COMM + SLIP_PT * PV)
    rets[d] = (pnl - cout) / eq
    eq += pnl - cout
r_ind = pd.Series(rets)
data = D.load_folder(args.donnees, daily=False, only=[SYM])
res = get("16")(symbols=SYM, initial_bankroll=1e6).run(data, report=False)
pan = res.daily_panel
r_mot = pan.loc[pan["valide"], "rendement"]
common = r_mot.index.intersection(r_ind.index)
diff = (r_mot[common] - r_ind[common]).abs()
sh = lambda r: r.mean() / r.std() * np.sqrt(252)
print(f"{SYM} : {nroll} rolls ajustes, {len(jours)} seances (moteur {len(r_mot)}), {trades} allers-retours (moteur {len(res.trades)})")
print(f"  equity finale independante {eq:,.0f} $ | moteur {res.equity.iloc[-1]:,.0f} $")
print(f"  Sharpe independant {sh(r_ind[common]):.4f} | moteur {sh(r_mot[common]):.4f}")
print(f"  ecart journalier max {diff.max():.2e} | seances avec ecart > 1e-9 : {(diff > 1e-9).sum()} / {len(common)}")
sys.exit(0 if (diff > 1e-9).sum() == 0 else 1)
