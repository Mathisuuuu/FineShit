"""Noise Area Intraday Momentum sur NQ (Nasdaq 100 E-mini), meilleur reglage de la grille.

Fichier autonome : numpy + pandas (+ pyarrow pour le Parquet), aucun import du moteur nexus.
Zarattini, Aziz & Barbon (2024), SSRN 4824172, porte sur NQ ; reglage retenu sur la grille de
48 configurations 2016-2026 : sigma sur 30 seances, controle toutes les 30 min, bande x 1,2.

Regles (seance cash 9:30-16:00, heure de New York) :
  1. sigma(t) = moyenne des |Close(t) / Open - 1| des 30 seances PRECEDENTES, a la meme minute t ;
  2. Upper(t) = max(Open, cloture de la veille) x (1 + 1,2 sigma(t)),
     Lower(t) = min(Open, cloture de la veille) x (1 - 1,2 sigma(t)) ;
  3. controle a 10:00, 10:30 ... 15:30 sur la cloture de la minute :
     long si Close > Upper et Close > VWAP, short si Close < Lower et Close < VWAP, sinon a plat
     (le signal est recalcule a chaque controle : c est le stop suiveur max(Upper, VWAP)) ;
  4. ordre execute a l ouverture de la minute suivante ; tout est ferme a 16:00 (13:00 les demi-seances) ;
  5. taille fixee a l ouverture : capital de la veille x min(2 % / vol journaliere 14 j, 4) / (Open x 20 $) ;
  6. couts : 2,25 $ par contrat + 1/2 tick (0,125 point) par execution.

Donnees : barres 1 minute de NQ. Par defaut le Parquet Databento du depot Cotations
(horodatage UTC, barre datee a son debut, contrats raboutes sans ajustement -> rolls ajustes ici).
Export NinjaTrader : --fuseau Europe/Paris --horodatage fin --rolls aucun (serie Merge Back Adjusted).

    python noise_area_nq.py --donnees ../../cotations/indices/NQ_v0_1m.parquet
    python noise_area_nq.py --donnees NQ.Last.txt --fuseau Europe/Paris --horodatage fin --rolls aucun

Sorties : resume dans la console, trades et equity journaliere en CSV (--sortie).
Recherche, pas un conseil d investissement : valider en simulation avant tout compte reel.
"""
from __future__ import annotations

import argparse
import math
import os

import numpy as np
import pandas as pd

# ----------------------------------------------------------------------------- reglage retenu
SIGMA_SEANCES = 30          # sigma : moyenne sur les N seances precedentes
CONTROLE_MIN = 30           # un controle toutes les 30 minutes depuis l ouverture (10:00 ... 15:30)
BANDE = 1.2                 # largeur de la zone de bruit, en sigma
VOL_CIBLE = 0.02            # 2 % de volatilite journaliere visee
VOL_SEANCES = 14            # volatilite journaliere sur 14 seances (cloture a cloture)
LEVIER_MAX = 4.0
POINT = 20.0                # NQ : 20 $ par point
TICK = 0.25
COMMISSION = 2.25           # $ par contrat et par execution
GLISSEMENT_TICKS = 0.5      # par execution
PUBLICATION = "2024-06-01"  # pour le resultat avant / apres publication du papier
NY = "America/New_York"


# ----------------------------------------------------------------------------- donnees
def lire_minutes(chemin: str, fuseau: str, horodatage: str) -> tuple[pd.DataFrame, bool]:
    """Barres 1 minute -> (DataFrame indexe en UTC a l heure de debut de barre, fichier_horodate_en_utc)."""
    if chemin.lower().endswith(".parquet"):
        df = pd.read_parquet(chemin)
    else:   # export NinjaTrader "yyyyMMdd HHmmss;o;h;l;c;v" ou CSV avec en-tete Date,Open,...
        brut = pd.read_csv(chemin, sep=None, engine="python", header=None)
        if str(brut.iloc[0, 0])[:1].isdigit():
            df = pd.DataFrame({"open": brut[1], "high": brut[2], "low": brut[3], "close": brut[4], "volume": brut[5]})
            df.index = pd.to_datetime(brut[0].astype(str), format="%Y%m%d %H%M%S")
        else:
            df = pd.read_csv(chemin, sep=None, engine="python")
            df.columns = [c.strip().lower() for c in df.columns]
            df.index = pd.to_datetime(df.pop(df.columns[0]))
    df = df[["open", "high", "low", "close", "volume"]].astype(float).sort_index()
    idx = pd.DatetimeIndex(df.index)
    en_utc = idx.tz is not None
    if not en_utc:
        idx = idx.tz_localize(fuseau, ambiguous="NaT", nonexistent="NaT")
    df.index = idx.tz_convert("UTC")
    df = df[~df.index.isna()]
    if horodatage == "fin":            # on garde ici l heure de DEBUT de chaque barre (9:30 pour 9:30-9:31)
        df.index = df.index - pd.Timedelta(minutes=1)
    return df[~df.index.duplicated(keep="last")], en_utc


def ajuster_rolls(df: pd.DataFrame) -> tuple[pd.DataFrame, int]:
    """Contrat continu sans ajustement : le changement d echeance est le saut le plus fort a minuit UTC
    du mois d echeance (mars, juin, sept., dec.), >= 5 pb et >= 4 x le suivant. Les prix anterieurs
    sont multiplies par le rapport : les rendements sont conserves."""
    t = df.index.to_series()
    prec = t.shift(1)
    # premiere barre commencant apres minuit UTC, dans la meme session (pas apres une fermeture)
    cand = (t.dt.normalize() != prec.dt.normalize()) & ((t - prec) <= pd.Timedelta(minutes=30))
    saut = np.log(df["open"] / df["close"].shift(1))[cand.to_numpy()]
    saut = saut[(saut.index.month % 3 == 0) & (saut.index.day <= 25)]
    facteur = pd.Series(1.0, index=df.index)
    n = 0
    for _, g in saut.groupby([saut.index.year, saut.index.month]):
        a = g.abs().sort_values(ascending=False)
        if len(a) >= 2 and a.iloc[0] >= 5e-4 and a.iloc[0] >= 4 * a.iloc[1]:
            facteur[facteur.index < a.index[0]] *= math.exp(g[a.index[0]])
            n += 1
    out = df.copy()
    for c in ("open", "high", "low", "close"):
        out[c] = df[c] * facteur
    return out, n


def feries_nyse(debut, fin) -> pd.DatetimeIndex:
    """Jours sans seance actions a New York (les futures y ont une seance raccourcie a exclure)."""
    from pandas.tseries.holiday import (AbstractHolidayCalendar, GoodFriday, Holiday, USLaborDay,
                                        USMartinLutherKingJr, USMemorialDay, USPresidentsDay,
                                        USThanksgivingDay, nearest_workday, sunday_to_monday)

    class Nyse(AbstractHolidayCalendar):
        rules = [Holiday("Nouvel an", month=1, day=1, observance=sunday_to_monday), USMartinLutherKingJr,
                 USPresidentsDay, GoodFriday, USMemorialDay,
                 Holiday("Juneteenth", month=6, day=19, start_date="2022-01-01", observance=nearest_workday),
                 Holiday("Independance", month=7, day=4, observance=nearest_workday), USLaborDay,
                 USThanksgivingDay, Holiday("Noel", month=12, day=25, observance=nearest_workday)]

    h = Nyse().holidays(pd.Timestamp(debut), pd.Timestamp(fin))
    h = h[~((h.month == 12) & (h.day == 31))]
    exceptionnels = pd.DatetimeIndex(["2007-01-02", "2012-10-29", "2012-10-30", "2018-12-05", "2025-01-09"])
    return h.union(exceptionnels)


def seance_cash(df: pd.DataFrame):
    """Matrices seances x 390 minutes (9:31 ... 16:00, heure de New York), seances valides seulement."""
    ny = df.copy()
    ny.index = (df.index + pd.Timedelta(minutes=1)).tz_convert(NY).tz_localize(None)   # barre datee a sa fin
    minute = ny.index.hour * 60 + ny.index.minute - 570                    # 1 = barre 9:30-9:31
    ny = ny[(minute >= 1) & (minute <= 390) & (ny.index.dayofweek < 5)]
    ny["jour"] = ny.index.normalize()
    ny["m"] = ny.index.hour * 60 + ny.index.minute - 570
    ny = ny[~ny["jour"].isin(feries_nyse(ny["jour"].min(), ny["jour"].max()))]
    info = ny.groupby("jour")["m"].agg(["min", "max"])
    apres_15h = ny[ny["m"] > 330].groupby("jour").size().reindex(info.index).fillna(0)
    complete = info["max"] >= 386
    demi = ~complete & (apres_15h == 0) & (info["max"] >= 206)               # cloture a 13:00
    jours = info.index[(info["min"] <= 5) & (complete | demi)]
    fin = pd.Series(np.where(complete[jours], 390, 210), index=jours)
    cols = range(1, 391)
    P = {k: ny.pivot_table(index="jour", columns="m", values=k, aggfunc="last").reindex(index=jours, columns=cols)
         for k in ("open", "high", "low", "close", "volume")}
    C = P["close"].ffill(axis=1)                                             # minute sans echange : prix inchange
    ouv = P["open"].bfill(axis=1).iloc[:, 0]
    C = C.apply(lambda col: col.fillna(ouv))
    O = P["open"].where(P["open"].notna(), C.shift(1, axis=1))
    O.iloc[:, 0] = ouv
    for d in jours[fin[jours] == 210]:
        C.loc[d, 211:] = np.nan
        O.loc[d, 211:] = np.nan
    H = P["high"].where(P["high"].notna(), np.maximum(O, C))
    L = P["low"].where(P["low"].notna(), np.minimum(O, C))
    V = P["volume"].fillna(0.0)
    return jours, fin, O, H, L, C, V


# ----------------------------------------------------------------------------- strategie
def backtest(df: pd.DataFrame, capital: float):
    jours, fin, O, H, L, C, V = seance_cash(df)
    ouv = O.iloc[:, 0]
    cloture = pd.Series([C.loc[d, fin[d]] for d in jours], index=jours)
    veille = cloture.shift(1)
    # zone de bruit : 30 observations PRECEDENTES de la meme minute (le jour courant n y entre jamais)
    ecart = (C.div(ouv, axis=0) - 1).abs()
    sigma = pd.DataFrame({m: ecart[m].dropna().rolling(SIGMA_SEANCES).mean().shift(1).reindex(jours)
                          for m in ecart.columns})
    vwap = (((H + L + C) / 3) * V).cumsum(axis=1) / V.cumsum(axis=1)
    vol = (cloture / veille - 1).rolling(VOL_SEANCES).std().shift(1)
    levier = np.minimum(VOL_CIBLE / vol, LEVIER_MAX)
    cout_unitaire = COMMISSION + GLISSEMENT_TICKS * TICK * POINT

    equity, lignes, trades = capital, [], []
    for d in jours:
        controles = list(range(CONTROLE_MIN, fin[d], CONTROLE_MIN))           # 30, 60 ... (10:00, 10:30 ...)
        pret = np.isfinite(levier[d]) and np.isfinite(veille[d]) and all(np.isfinite(sigma.loc[d, m]) for m in controles)
        if not pret:
            lignes.append((d, equity, 0.0, 0, 0))
            continue
        contrats = math.floor(equity * levier[d] / (ouv[d] * POINT) + 0.5)
        haut, bas = max(ouv[d], veille[d]), min(ouv[d], veille[d])
        pos, entree, t_entree, pnl, couts, n = 0, 0.0, None, 0.0, 0.0, 0

        def heure(m):
            return f"{(570 + m) // 60:02d}:{(570 + m) % 60:02d}"

        def fermer(px, t, raison):
            nonlocal pnl, n
            g = pos * (px - entree) * POINT
            pnl += g
            n += 1
            trades.append(dict(jour=d.date(), entree=t_entree, sortie=t, sens="long" if pos > 0 else "short",
                               contrats=abs(pos), prix_entree=entree, prix_sortie=px, pnl_brut=g, raison=raison))

        for m in controles:
            c, vw, s = C.loc[d, m], vwap.loc[d, m], sigma.loc[d, m]
            upper, lower = haut * (1 + BANDE * s), bas * (1 - BANDE * s)
            cible = contrats if (c > upper and c > vw) else (-contrats if (c < lower and c < vw) else 0)
            if cible != pos:
                px = O.loc[d, m + 1]                                         # ouverture de la minute suivante
                if pos != 0:
                    fermer(px, heure(m), "inversion" if cible == -pos else "stop suiveur")
                couts += abs(cible - pos) * cout_unitaire
                pos, entree, t_entree = cible, px, heure(m)
        if pos != 0:                                                         # sortie a la cloture
            fermer(C.loc[d, fin[d]], heure(fin[d]), "fin de seance")
            couts += abs(pos) * cout_unitaire
        r = (pnl - couts) / equity
        equity += pnl - couts
        lignes.append((d, equity, r, n, contrats))
    eq = pd.DataFrame(lignes, columns=["jour", "equity", "rendement", "trades", "contrats"]).set_index("jour")
    return eq, pd.DataFrame(trades)


# ----------------------------------------------------------------------------- resume
def resume(eq: pd.DataFrame, trades: pd.DataFrame, capital: float, n_rolls: int) -> str:
    r = eq["rendement"]

    def sharpe(x):
        return float(x.mean() / x.std() * math.sqrt(252)) if len(x) > 2 and x.std() > 0 else float("nan")

    def perte_max(x):
        e = (1 + x).cumprod()
        return float((1 - e / e.cummax()).max())

    ans = len(r) / 252
    avant, apres = r[r.index < PUBLICATION], r[r.index >= PUBLICATION]
    lignes = [
        f"Noise Area NQ - sigma {SIGMA_SEANCES} seances, controle {CONTROLE_MIN} min, bande x{BANDE}",
        f"Periode      {r.index[0]:%Y-%m-%d} -> {r.index[-1]:%Y-%m-%d} ({len(r)} seances, {n_rolls} rolls ajustes)",
        f"Equity       {capital:,.0f} $ -> {eq['equity'].iloc[-1]:,.0f} $   rendement annuel {(eq['equity'].iloc[-1] / capital) ** (1 / ans) - 1:.1%}",
        f"Sharpe       {sharpe(r):.2f}   (avant publication {sharpe(avant):.2f} | apres {sharpe(apres):.2f}, {len(apres)} seances)",
        f"Perte max    {perte_max(r):.1%}",
        f"Trades       {len(trades)} allers-retours, {len(trades) / max(1, (eq['trades'] > 0).sum()):.2f} par seance tradee, "
        f"{(trades['pnl_brut'] > 0).mean():.0%} gagnants (brut)" if len(trades) else "Trades       aucun",
    ]
    return "\n".join(lignes)


def main():
    ap = argparse.ArgumentParser(description="Noise Area Intraday Momentum sur NQ (meilleur reglage).")
    ap.add_argument("--donnees", required=True, help="barres 1 minute de NQ (Parquet Databento, export NinjaTrader ou CSV)")
    ap.add_argument("--capital", type=float, default=1_000_000.0)
    ap.add_argument("--fuseau", default=NY, help="fuseau des horodatages si le fichier n en porte pas (ex. Europe/Paris)")
    ap.add_argument("--horodatage", choices=("debut", "fin"), default="debut",
                    help="barre datee a son debut (Databento) ou a sa fin (NinjaTrader)")
    ap.add_argument("--rolls", choices=("auto", "minuit_utc", "aucun"), default="auto",
                    help="auto : ajustement si le fichier est horodate en UTC (Databento) ; aucun pour une serie deja ajustee")
    ap.add_argument("--sortie", default="resultats_noise_area_nq", help="dossier des CSV")
    a = ap.parse_args()

    df, en_utc = lire_minutes(a.donnees, a.fuseau, a.horodatage)
    n_rolls = 0
    if a.rolls == "minuit_utc" or (a.rolls == "auto" and en_utc):
        df, n_rolls = ajuster_rolls(df)
    eq, trades = backtest(df, a.capital)
    print(resume(eq, trades, a.capital, n_rolls))
    os.makedirs(a.sortie, exist_ok=True)
    eq.to_csv(os.path.join(a.sortie, "equity.csv"))
    trades.to_csv(os.path.join(a.sortie, "trades.csv"), index=False)
    print(f"CSV ecrits dans {a.sortie}/")


if __name__ == "__main__":
    main()
