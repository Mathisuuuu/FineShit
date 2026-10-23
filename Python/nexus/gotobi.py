"""Gotobi sur le yen (6J) : backtest construit directement dans vectorbt (Portfolio.from_signals).

Idee : les jours de reglement japonais (5, 10, 15, 20, 25 et fin de mois, dits « gotobi »), les importateurs
achetent des dollars a leur banque au cours du fixing de 9:55 heure de Tokyo. Les banques couvrent ces achats
sur le marche avant 9:55 : le dollar monte contre le yen avant le fixing, puis redescend apres.
Sources : Ito & Yamada (Tokyo fixing puzzles, 2017) ; Bessho, Sugimoto & Suzuki (arXiv 2301.13204, 2023) ;
Krohn, Mueller & Whelan (Journal of Finance, 2024) pour la forme en V autour des fixings.

Regles (heure de Tokyo, jours gotobi seulement ; 6J = prix du yen en dollars, acheter du dollar = vendre 6J) :
  08:00  vente de 6J (le dollar va monter jusqu au fixing) ;
  09:55  retournement : achat de 6J (le dollar redescend apres le fixing) ;
  11:00  sortie.
Jour gotobi tombant un samedi, un dimanche ou un jour ferie japonais -> jour ouvre precedent ; fin de mois =
dernier jour ouvre japonais du mois. Ordres executes a l ouverture de la premiere barre 1 minute qui commence
a l heure prevue (au plus 10 min apres, sinon le jour est saute). Couts : 2,25 $ par contrat et par cote +
1/2 tick de glissement, convertis en fraction du notionnel au prix brut (non ajuste) du moment.
Taille : notionnel fixe = capital x exposition (95 000 $ pour 100 000 $), sans levier ni reinvestissement
(vectorbt n accepte pas le retournement en pourcentage du capital). vectorbt ne gerant pas de marge, une reserve
de liquidites jamais investie (9 x le capital) est ajoutee au depart puis retiree de la valeur (fonction valeur()).
"""
from __future__ import annotations

import datetime as dt

import numpy as np
import pandas as pd

from . import data as D
from . import intraday as I

try:
    import vectorbt as vbt
except ImportError:  # pragma: no cover
    vbt = None

TOKYO, NY = "Asia/Tokyo", "America/New_York"
SPEC_6J = dict(multiplicateur=12_500_000, tick=0.0000005, commission=2.25, glissement_ticks=0.5)
DEFAULTS = dict(entree="08:00", fixing="09:55", sortie="11:00", sortie_avant="", reprise_apres="", jambes="avant,apres",
                capital=100_000.0, exposition=0.95, reserve_mult=9.0, cout_mult=1.0, feries_japon=True, tolerance_min=10,
                jours="gotobi", decalage_jours=0)
PUBLICATION = "2023-01-31"      # arXiv 2301.13204 (strategie Gotobi publiee)
# Essais comptes pour le Sharpe deflate : criblage du 2026-10-15 (environ 110 hypotheses et variantes mono-actif
# testees avant de retenir le Gotobi), variance des Sharpe annualises de ces essais = 0,873.
ESSAIS = 110
VAR_SHARPE_ESSAIS_ANNUALISE = 0.873


# =============================================================================
#  Calendrier japonais
# =============================================================================
def _nieme_lundi(y: int, m: int, n: int) -> dt.date:
    d = dt.date(y, m, 1)
    d += dt.timedelta(days=(7 - d.weekday()) % 7)
    return d + dt.timedelta(weeks=n - 1)


def _equinoxes(y: int) -> tuple[dt.date, dt.date]:
    k = y - 1980
    return (dt.date(y, 3, int(20.8431 + 0.242194 * k - k // 4)), dt.date(y, 9, int(23.2488 + 0.242194 * k - k // 4)))


def feries_japon(debut: int, fin: int) -> set[dt.date]:
    """Jours sans banque au Japon (feries nationaux, jours de remplacement, jours entre deux feries,
    2 et 3 janvier, 31 decembre). Regles valables de 2016 a 2030 environ."""
    out: set[dt.date] = set()
    for y in range(debut, fin + 1):
        h = {dt.date(y, 1, 1), _nieme_lundi(y, 1, 2), dt.date(y, 2, 11), dt.date(y, 4, 29), dt.date(y, 5, 3),
             dt.date(y, 5, 4), dt.date(y, 5, 5), _nieme_lundi(y, 9, 3), dt.date(y, 11, 3), dt.date(y, 11, 23)}
        h |= set(_equinoxes(y))
        if y <= 2018:
            h.add(dt.date(y, 12, 23))                       # anniversaire de l empereur Akihito
        elif y >= 2020:
            h.add(dt.date(y, 2, 23))                        # anniversaire de l empereur Naruhito
        if y == 2019:                                       # intronisation
            h |= {dt.date(2019, 4, 30), dt.date(2019, 5, 1), dt.date(2019, 5, 2), dt.date(2019, 10, 22)}
        special = {2020: (dt.date(2020, 7, 23), dt.date(2020, 8, 10), dt.date(2020, 7, 24)),     # Jeux de Tokyo
                   2021: (dt.date(2021, 7, 22), dt.date(2021, 8, 8), dt.date(2021, 7, 23))}
        mer, montagne, sport = special.get(y, (_nieme_lundi(y, 7, 3), dt.date(y, 8, 11), _nieme_lundi(y, 10, 2)))
        h |= {mer, montagne, sport}
        for d in sorted(h):                                 # ferie un dimanche -> prochain jour non ferie
            if d.weekday() == 6:
                n = d + dt.timedelta(days=1)
                while n in h:
                    n += dt.timedelta(days=1)
                h.add(n)
        for d in [dt.date(y, 1, 1) + dt.timedelta(days=i) for i in range(366)]:   # jour pris entre deux feries
            if d.year == y and d not in h and d.weekday() < 6 and (d - dt.timedelta(days=1)) in h and (d + dt.timedelta(days=1)) in h:
                h.add(d)
        h |= {dt.date(y, 1, 2), dt.date(y, 1, 3), dt.date(y, 12, 31)}
        out |= h
    return out


def jours_ouvres_japon(debut, fin, feries=True) -> pd.DatetimeIndex:
    jours = pd.bdate_range(debut, fin)
    if feries:
        f = feries_japon(jours[0].year, jours[-1].year)
        jours = jours[~np.isin(jours.date, list(f))]
    return jours


def jours_gotobi(debut, fin, feries=True) -> pd.DatetimeIndex:
    """5, 10, 15, 20, 25 de chaque mois et dernier jour ouvre du mois ; jour non ouvre -> jour ouvre precedent."""
    ouv = jours_ouvres_japon(pd.Timestamp(debut) - pd.Timedelta(days=10), pd.Timestamp(fin) + pd.Timedelta(days=40), feries)
    out = set()
    for y in range(pd.Timestamp(debut).year, pd.Timestamp(fin).year + 1):
        for m in range(1, 13):
            for d in (5, 10, 15, 20, 25):
                p = ouv.searchsorted(pd.Timestamp(y, m, d), side="right") - 1
                if p >= 0:
                    out.add(ouv[p])
            fin_mois = pd.Timestamp(y, m, 1) + pd.offsets.MonthEnd(0)
            p = ouv.searchsorted(fin_mois, side="right") - 1
            if p >= 0:
                out.add(ouv[p])
    g = pd.DatetimeIndex(sorted(out))
    return g[(g >= pd.Timestamp(debut)) & (g <= pd.Timestamp(fin))]


# =============================================================================
#  Donnees
# =============================================================================
def charger_6j(dossier: str) -> tuple[pd.DataFrame, dict]:
    """Barres 1 minute de 6J (Parquet Databento : UTC, barre datee a son debut) -> open/close ajustes des rolls
    (moteur : adjust_rolls_midnight_utc), frais et glissement en fraction du notionnel au prix brut."""
    brut = D.load_folder(dossier, daily=False, only=["6J"])
    if "6J" not in brut:
        raise FileNotFoundError(f"aucun fichier 6J (barres 1 minute) dans {dossier}")
    df = brut["6J"]
    if df.attrs.get("fuseau") is None:
        raise ValueError("6J : fichier sans fuseau ; attendu le Parquet Databento horodate en UTC (barre datee a son debut)")
    adj, rolls = I.adjust_rolls_midnight_utc(df, "UTC")
    s = SPEC_6J
    px = df["close"].to_numpy(float)
    m = pd.DataFrame({"open": adj["open"].to_numpy(float), "close": adj["close"].to_numpy(float),
                      "frais": s["commission"] / (px * s["multiplicateur"]),
                      "glissement": s["glissement_ticks"] * s["tick"] / px}, index=pd.DatetimeIndex(df.index))
    info = dict(symbole="6J.v.0 (CME Globex, yen japonais en dollars US, contrat continu roule au volume)",
                source="Databento GLBX.MDP3, ohlcv-1m (depot Cotations)", barres=int(len(df)),
                debut=f"{df.index[0]:%Y-%m-%d %H:%M} UTC", fin=f"{df.index[-1]:%Y-%m-%d %H:%M} UTC", rolls=int(len(rolls)),
                horodatage="UTC, barre datee a son debut", ajustement="rolls a minuit UTC, ajustement proportionnel (rendements conserves)")
    return m, info


# =============================================================================
#  Strategie
# =============================================================================
def _hm(s: str) -> pd.Timedelta:
    h, mi = (int(x) for x in s.split(":"))
    return pd.Timedelta(hours=h, minutes=mi)


def _vers_utc(jours, heure: str) -> pd.DatetimeIndex:
    return (pd.DatetimeIndex(jours) + _hm(heure)).tz_localize(TOKYO).tz_convert("UTC").tz_localize(None)


def _barre(index: pd.DatetimeIndex, t: pd.DatetimeIndex, tol: pd.Timedelta) -> np.ndarray:
    pos = index.searchsorted(t, side="left")
    ok = pos < len(index)
    p = np.where(ok, pos, 0)
    ecart = np.asarray(index[p] - t)
    ok &= (ecart >= np.timedelta64(0, "ns")) & (ecart <= tol.to_timedelta64())
    return np.where(ok, pos, -1)


def jours_trades(m: pd.DataFrame, p: dict) -> pd.DatetimeIndex:
    debut, fin = m.index[0].normalize() + pd.Timedelta(days=1), m.index[-1].normalize()
    if p["jours"] == "gotobi":
        j = jours_gotobi(debut, fin, p["feries_japon"])
    elif p["jours"] == "autres":
        j = jours_ouvres_japon(debut, fin, p["feries_japon"]).difference(jours_gotobi(debut, fin, p["feries_japon"]))
    elif p["jours"] == "tous":
        j = jours_ouvres_japon(debut, fin, p["feries_japon"])
    else:
        raise ValueError("jours : gotobi | autres | tous")
    if p["decalage_jours"]:
        ouv = jours_ouvres_japon(debut - pd.Timedelta(days=15), fin + pd.Timedelta(days=15), p["feries_japon"])
        i = ouv.get_indexer(j) + int(p["decalage_jours"])
        j = ouv[i[(i >= 0) & (i < len(ouv))]].difference(jours_gotobi(debut, fin, p["feries_japon"]))
    return j


def signaux(m: pd.DataFrame, p: dict):
    """Tableaux de signaux (une colonne) pour vbt.Portfolio.from_signals + table des trades prevus."""
    j = jours_trades(m, p)
    tol = pd.Timedelta(minutes=int(p["tolerance_min"]))
    jambes = [x.strip() for x in str(p["jambes"]).split(",") if x.strip()]
    t_in = _barre(m.index, _vers_utc(j, p["entree"]), tol)
    t_fx_out = _barre(m.index, _vers_utc(j, p["sortie_avant"] or p["fixing"]), tol)
    t_fx_in = _barre(m.index, _vers_utc(j, p["reprise_apres"] or p["fixing"]), tol)
    t_out = _barre(m.index, _vers_utc(j, p["sortie"]), tol)
    n = len(m)
    E, X, SE, SX = (np.zeros(n, bool) for _ in range(4))
    plan = []
    for k, d in enumerate(j):
        a, b, c, e = t_in[k], t_fx_out[k], t_fx_in[k], t_out[k]
        avant = "avant" in jambes and a >= 0 and b > a
        apres = "apres" in jambes and c >= 0 and e > c
        if avant and apres and c < b:
            continue
        if avant:
            SE[a] = True
            if not (apres and c == b):          # meme barre : le retournement ferme la vente
                SX[b] = True
        if apres:
            E[c] = True
            X[e] = True
        if avant or apres:
            plan.append(d)
    idx = m.index
    return [pd.Series(x, index=idx) for x in (E, X, SE, SX)], pd.DatetimeIndex(plan)


def portefeuille(m: pd.DataFrame, **params):
    """vbt.Portfolio (une colonne) de la strategie Gotobi sur les barres 1 minute de 6J."""
    if vbt is None:
        raise ImportError("vectorbt n est pas installe")
    p = {**DEFAULTS, **params}
    (E, X, SE, SX), jours = signaux(m, p)
    k = float(p["cout_mult"])
    pf = vbt.Portfolio.from_signals(
        m["close"], entries=E, exits=X, short_entries=SE, short_exits=SX, price=m["open"],
        size=float(p["capital"]) * float(p["exposition"]), size_type="value", fees=m["frais"] * k, slippage=m["glissement"] * k,
        init_cash=float(p["capital"]) * (1 + float(p["reserve_mult"])), upon_opposite_entry="reverse",
        allow_partial=False, raise_reject=True, freq="1min")
    pf.nexus_jours = jours
    pf.nexus_params = p
    pf.nexus_reserve = float(p["capital"]) * float(p["reserve_mult"])
    return pf


def valeur(pf) -> pd.Series:
    """Valeur du capital de la strategie (valeur vectorbt moins la reserve de liquidites)."""
    return pf.value() - getattr(pf, "nexus_reserve", 0.0)


def valeur_journaliere(pf, calendrier: pd.DatetimeIndex | None = None) -> pd.Series:
    """Valeur vectorbt en fin de journee de New York (le P&L de la nuit d Asie tombe sur la date de New York)."""
    v = valeur(pf)
    idx = pd.DatetimeIndex(v.index).tz_localize("UTC").tz_convert(NY).tz_localize(None)
    s = pd.Series(v.to_numpy(), index=idx)
    d = s.groupby(s.index.normalize()).last()
    if calendrier is not None:
        d = d.reindex(d.index.union(calendrier)).ffill().reindex(calendrier).bfill()
    return d
