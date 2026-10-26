"""ORB 5 minutes sur NQ, version « Stocks in Play » : backtest construit directement dans vectorbt.

Source : Zarattini, Barbon & Aziz (2024), A Profitable Day Trading Strategy for the U.S. Equity Market, SSRN 4729284
(suite de Zarattini & Aziz 2023, Can Day Trading Really Be Profitable?, SSRN 4416622). Regles du papier appliquees
telles quelles a un seul contrat, le Nasdaq 100 E-mini (NQ) :
  1. bougie d ouverture 9:30-9:35 (heure de New York) ; volume relatif = son volume / moyenne des bougies 9:30-9:35
     des 14 seances precedentes ; on ne trade que si le volume relatif est d au moins 100 % ;
  2. bougie haussiere -> ordre stop d achat au plus haut de la bougie (baissiere -> vente au plus bas), actif apres 9:35 ;
     un prix d ouverture deja au-dela du niveau est execute a l ouverture ;
  3. stop de protection a 10 % de l ATR 14 jours du prix d execution ; sinon sortie a la cloture (16:00, 13:00 les
     demi-seances) ; un seul trade par jour ;
  4. taille : perte au stop = 1 % du capital, levier maximum 4 ; capital fixe (pas de reinvestissement).
Couts : 2,25 $ par contrat et par execution + 1/2 tick de glissement (stops compris).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from . import data as D
from . import intraday as I

try:
    import vectorbt as vbt
except ImportError:  # pragma: no cover
    vbt = None

SPEC = {"NQ": dict(multiplicateur=20.0, tick=0.25), "ES": dict(multiplicateur=50.0, tick=0.25)}
COMMISSION = 2.25
DEFAULTS = dict(symbole="NQ", minutes_ouverture=5, filtre_volume=True, volume_min=1.0, volume_jours=14, atr_jours=14,
                stop_atr=0.10, risque=0.01, levier_max=4.0, capital=1_000_000.0, reserve_mult=9.0, cout_mult=1.0,
                delai_min=0, jours_hasard=None)
PUBLICATION = "2024-02-15"   # SSRN 4729284
# Essais comptes pour le Sharpe deflate et les corrections : environ 140 hypotheses et variantes testees avant celle-ci
# (criblages du 2026-10-15) + 10 variantes SSRN (ORB 2023 et 2024, VWAP, premiere/derniere demi-heure, sur NQ et ES).
ESSAIS = 150
VAR_SHARPE_ESSAIS_ANNUALISE = 0.87


def charger(dossier: str, symbole: str = "NQ") -> tuple[pd.DataFrame, dict]:
    """Barres 1 minute de la seance cash (heure de New York, datees a leur fin), rolls ajustes, seances NYSE valides,
    avec frais et glissement en fraction du notionnel au prix brut."""
    df = D.load_folder(dossier, daily=False, only=[symbole])[symbole]
    adj, rolls = I.adjust_rolls_midnight_utc(df, "UTC")
    ny, note = I.prepare_minutes(adj, "UTC", "auto")
    brut, _ = I.prepare_minutes(df, "UTC", "auto")
    g = I.build_grid(ny)
    valides = pd.DatetimeIndex(g.days[g.valid])
    valides = valides.difference(I.nyse_holidays(valides[0], valides[-1]))     # seances futures raccourcies des feries NYSE
    t = pd.DatetimeIndex(ny.index)
    mod = t.hour * 60 + t.minute
    garde = (mod > 570) & (mod <= 960) & np.asarray(t.normalize().isin(valides))
    m = ny.loc[garde, ["open", "high", "low", "close", "volume"]].astype(float).copy()
    px = brut["close"].reindex(m.index).to_numpy(float)
    s = SPEC[symbole]
    m["frais"] = COMMISSION / (px * s["multiplicateur"])
    m["glissement"] = 0.5 * s["tick"] / px
    info = dict(symbole=f"{symbole}.v.0 (CME Globex, contrat continu roule au volume)", source="Databento GLBX.MDP3, ohlcv-1m (depot Cotations)",
                barres=int(len(df)), barres_seance=int(len(m)), seances=int(len(valides)), debut=f"{valides[0]:%Y-%m-%d}",
                fin=f"{valides[-1]:%Y-%m-%d}", rolls=int(len(rolls)), horodatage=note,
                ajustement="rolls a minuit UTC, ajustement proportionnel (rendements conserves)")
    return m, info


def _jours(m: pd.DataFrame, p: dict):
    jour = m.index.normalize()
    mn = (m.index.hour * 60 + m.index.minute - 570).to_numpy()
    k = int(p["minutes_ouverture"])
    ouv = m[mn <= k].groupby(jour[mn <= k])
    r_o, r_c = ouv["open"].first(), ouv["close"].last()
    r_h, r_l, r_v = ouv["high"].max(), ouv["low"].min(), ouv["volume"].sum()
    vol_rel = r_v / r_v.rolling(int(p["volume_jours"])).mean().shift(1)
    gj = m.groupby(jour)
    H, L, C = gj["high"].max(), gj["low"].min(), gj["close"].last()
    tr = pd.concat([H - L, (H - C.shift(1)).abs(), (L - C.shift(1)).abs()], axis=1).max(axis=1)
    atr = tr.rolling(int(p["atr_jours"])).mean().shift(1)
    return pd.DataFrame(dict(o=r_o, c=r_c, h=r_h, l=r_l, vol_rel=vol_rel, atr=atr)), jour.to_numpy(), mn


def signaux(m: pd.DataFrame, p: dict):
    """Ordres de la strategie -> tableaux pour vbt.Portfolio.from_signals (entrees, prix d execution, stops, tailles)."""
    tab, jour, mn = _jours(m, p)
    n = len(m)
    o, h, lo = (m[c].to_numpy(float) for c in ("open", "high", "low"))
    derniere = np.r_[jour[1:] != jour[:-1], True]
    fins = np.flatnonzero(derniere)
    E, SE = np.zeros(n, bool), np.zeros(n, bool)
    prix, sl, taille = o.copy(), np.full(n, np.nan), np.full(n, np.nan)
    k = int(p["minutes_ouverture"])
    retenus = set(pd.DatetimeIndex(p["jours_hasard"])) if p["jours_hasard"] is not None else None
    plan = []
    for i0 in np.flatnonzero(mn == k + 1):
        d = pd.Timestamp(jour[i0])
        if d not in tab.index:
            continue
        x = tab.loc[d]
        sens = np.sign(x.c - x.o)
        if not np.isfinite(sens) or sens == 0 or not (x.atr > 0):
            continue
        if retenus is not None:
            if d not in retenus:
                continue
        elif p["filtre_volume"] and not (x.vol_rel >= float(p["volume_min"])):
            continue
        i1 = fins[np.searchsorted(fins, i0)]
        niveau = x.h if sens > 0 else x.l
        touche = (h[i0:i1] >= niveau) if sens > 0 else (lo[i0:i1] <= niveau)
        if not touche.any():
            continue
        j = i0 + int(np.argmax(touche)) + int(p["delai_min"])
        if j >= i1:
            continue
        fill = (max(o[j], niveau) if sens > 0 else min(o[j], niveau)) if p["delai_min"] == 0 else o[j]
        (E if sens > 0 else SE)[j] = True
        prix[j] = fill
        dist = float(p["stop_atr"]) * x.atr
        sl[j] = dist / fill
        taille[j] = min(float(p["risque"]) * float(p["capital"]) / dist, float(p["levier_max"]) * float(p["capital"]) / fill)
        plan.append(d)
    return E, SE, derniere, prix, sl, taille, pd.DatetimeIndex(plan)


def portefeuille(m: pd.DataFrame, **params):
    if vbt is None:
        raise ImportError("vectorbt n est pas installe")
    p = {**DEFAULTS, **params}
    E, SE, X, prix, sl, taille, jours = signaux(m, p)
    k = float(p["cout_mult"])
    cap = float(p["capital"])
    pf = vbt.Portfolio.from_signals(m["close"], entries=E, exits=X, short_entries=SE, short_exits=X, price=prix,
                                    open=m["open"], high=m["high"], low=m["low"], size=taille, size_type="amount",
                                    sl_stop=sl, stop_entry_price="fillprice", fees=m["frais"] * k, slippage=m["glissement"] * k,
                                    init_cash=cap * (1 + float(p["reserve_mult"])), freq="1min")
    pf.nexus_reserve = cap * float(p["reserve_mult"])
    pf.nexus_jours = jours
    pf.nexus_params = p
    return pf


def valeur(pf) -> pd.Series:
    """Valeur du capital (valeur vectorbt moins la reserve de liquidites : vectorbt ne gere pas de marge)."""
    return pf.value() - getattr(pf, "nexus_reserve", 0.0)


def valeur_journaliere(pf, calendrier: pd.DatetimeIndex | None = None) -> pd.Series:
    v = valeur(pf)
    d = v.groupby(pd.DatetimeIndex(v.index).normalize()).last()
    if calendrier is not None:
        d = d.reindex(d.index.union(calendrier)).ffill().reindex(calendrier).bfill()
    return d
