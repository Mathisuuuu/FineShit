"""Or hors seance de New York, version intraday (GC) : backtest construit directement dans vectorbt.

Source : Blose & Gondhalekar (2014), Overnight gold returns, Applied Economics Letters 21(18) ; Blose, Gondhalekar &
Kort (2018), Journal of Economics and Finance 42(3) : sur le COMEX (1985-2012), le rendement de l or se fait hors
de la seance de jour (8:20-13:30 heure de New York) ; pendant cette seance il est negatif en moyenne.

Regle publiee : etre acheteur d or de 13:30 (cloture COMEX) a 8:20 le lendemain (ouverture COMEX). Version
intraday retenue (fixee avant les tests, 2026-10-15) : la meme exposition, mais fermee a chaque fin de seance
Globex (17:00 New York, 23:00 Paris) et reprise a la reouverture (18:00 New York, minuit Paris). Aucune position
pendant la pause quotidienne 17:00-18:00 ni le week-end. Par seance Globex (18:00 la veille -> 17:00) :
  jambe « asie »  : achat a l ouverture de la seance (18:00), vente a 8:20 (ouverture du COMEX) ;
  jambe « soir »  : achat a 13:30 (cloture du COMEX), vente a la derniere minute de la seance (cloture 17:00).
Seance raccourcie (jour ferie) : sortie a sa derniere minute ; heure absente (au plus 10 min de retard) : jambe sautee.
Ordres a l ouverture de la premiere barre 1 minute de l heure prevue ; sortie de fin de seance a la cloture de la
derniere barre. Taille : 100 % du capital (notionnel = capital, sans levier), reinvesti. Couts : 2,25 $ par contrat
et par execution + 1/2 tick (0,10 $), en fraction du notionnel au prix brut du moment.
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd

from . import data as D

try:
    import vectorbt as vbt
except ImportError:  # pragma: no cover
    vbt = None

NY = "America/New_York"
SPEC_GC = dict(multiplicateur=100.0, tick=0.1, commission=2.25, glissement_ticks=0.5)
OUVERTURE = 18 * 60                       # debut de seance Globex : 18:00 New York (minute 0 de la seance)
DEFAULTS = dict(pause_debut="08:20", pause_fin="13:30", jambes="asie,soir", capital=1_000_000.0, exposition=1.0,
                cout_mult=1.0, tolerance_min=10, delai_min=0)
PUBLICATION = "2014-12-01"     # Blose & Gondhalekar, Overnight gold returns, Applied Economics Letters 21(18), dec. 2014
# Essais comptes pour le Sharpe deflate : 150 hypotheses et variantes avant l ORB, 14 essais de l ORB sur les autres
# contrats, 11 hypotheses sur l or et 3 versions intraday de la nuit (2026-10-15).
ESSAIS = 178
VAR_SHARPE_ESSAIS_ANNUALISE = 0.87


# =============================================================================
#  Donnees
# =============================================================================
def ajuster_rolls(df: pd.DataFrame, min_bp: float = 5.0, dominance: float = 4.0) -> tuple[pd.DataFrame, pd.DataFrame]:
    """GC.v.0 (Databento) raboute les echeances a 00:00 UTC, souvent les derniers jours du mois (premier avis de
    livraison). Pour chaque mois, le saut a minuit UTC le plus fort (>= min_bp et >= dominance x le second) est le
    roll ; les prix anterieurs sont multiplies par le rapport (ajustement proportionnel, rendements conserves)."""
    idx = pd.DatetimeIndex(df.index)
    t = (idx.tz_convert("UTC").tz_localize(None) if idx.tz is not None else idx).to_numpy()
    o, c = df["open"].to_numpy(float), df["close"].to_numpy(float)
    prev = np.r_[t[:1], t[:-1]]
    k = np.flatnonzero((t.astype("datetime64[D]") != prev.astype("datetime64[D]")) & ((t - prev) <= np.timedelta64(30, "m")))
    k = k[k > 0]
    gap = np.log(o[k] / c[k - 1])
    q = pd.DatetimeIndex(t[k])
    rows = []
    for _, sel in pd.Series(np.arange(len(k))).groupby([q.year, q.month]):
        sel = sel.to_numpy()
        a = np.abs(gap[sel])
        if len(a) < 2:
            continue
        ordre = np.argsort(a)[::-1]
        if a[ordre[0]] * 1e4 >= min_bp and a[ordre[0]] >= dominance * a[ordre[1]]:
            j = sel[ordre[0]]
            rows.append(dict(utc=q[j], bar=int(k[j]), saut_bp=float(gap[j] * 1e4), second_bp=float(a[ordre[1]] * 1e4)))
    rolls = pd.DataFrame(rows, columns=["utc", "bar", "saut_bp", "second_bp"])
    fac = np.ones(len(df))
    for r in rolls.itertuples():
        fac[: r.bar] *= math.exp(r.saut_bp / 1e4)
    out = df.copy()
    for col in ("open", "high", "low", "close"):
        if col in out:
            out[col] = out[col].to_numpy(float) * fac
    return out, rolls


def charger(dossier: str) -> tuple[pd.DataFrame, dict]:
    """Barres 1 minute de GC (Parquet Databento : UTC, barre datee a son debut) -> open/close ajustes des rolls,
    frais et glissement en fraction du notionnel au prix brut."""
    brut = D.load_folder(dossier, daily=False, only=["GC"])
    if "GC" not in brut:
        raise FileNotFoundError(f"aucun fichier GC (barres 1 minute) dans {dossier}")
    df = brut["GC"]
    if df.attrs.get("fuseau") is None:
        raise ValueError("GC : fichier sans fuseau ; attendu le Parquet Databento horodate en UTC (barre datee a son debut)")
    adj, rolls = ajuster_rolls(df)
    s = SPEC_GC
    px = df["close"].to_numpy(float)
    idx = pd.DatetimeIndex(df.index)
    idx = idx.tz_convert("UTC").tz_localize(None) if idx.tz is not None else idx
    date, minute = seances(idx)
    m = pd.DataFrame({"open": adj["open"].to_numpy(float), "close": adj["close"].to_numpy(float),
                      "frais": s["commission"] / (px * s["multiplicateur"]),
                      "glissement": s["glissement_ticks"] * s["tick"] / px, "seance": date, "minute": minute}, index=idx)
    info = dict(symbole="GC.v.0 (CME COMEX, or 100 onces, contrat continu roule au volume)",
                source="Databento GLBX.MDP3, ohlcv-1m (depot Cotations)", barres=int(len(df)),
                debut=f"{idx[0]:%Y-%m-%d %H:%M} UTC", fin=f"{idx[-1]:%Y-%m-%d %H:%M} UTC", rolls=int(len(rolls)),
                horodatage="UTC, barre datee a son debut",
                ajustement="rolls a minuit UTC (saut dominant du mois), ajustement proportionnel (rendements conserves)")
    return m, info


# =============================================================================
#  Strategie
# =============================================================================
def _minute(s: str) -> int:
    """Heure de New York -> minutes depuis l ouverture de la seance Globex (18:00 la veille)."""
    h, mi = (int(x) for x in s.split(":"))
    return (h * 60 + mi - OUVERTURE) % 1440


def seances(index: pd.DatetimeIndex) -> tuple[np.ndarray, np.ndarray]:
    """Pour chaque barre (UTC) : date de seance CME (la seance 18:00 -> 17:00 porte la date de sa fin) et minute
    depuis l ouverture de 18:00 (heure de New York, changements d heure compris)."""
    ny = pd.DatetimeIndex(index).tz_localize("UTC").tz_convert(NY).tz_localize(None)
    decale = ny + pd.Timedelta(minutes=1440 - OUVERTURE)
    date = decale.normalize()
    minute = ((decale - date) / pd.Timedelta(minutes=1)).to_numpy().astype(np.int64)
    return date.to_numpy(), minute


def _seances(m: pd.DataFrame):
    if "seance" in m and "minute" in m:
        return m["seance"].to_numpy(), m["minute"].to_numpy(np.int64)
    return seances(m.index)


def signaux(m: pd.DataFrame, p: dict):
    """Tableaux pour vbt.Portfolio.from_signals (une colonne) : entrees, sorties, prix d execution par barre.
    jambes : asie (ouverture 18:00 -> pause_debut), soir (pause_fin -> fin de seance) ; temoins : tout (seance
    entiere), pause (pause_debut -> pause_fin), nuit (regle publiee, garde la nuit : pause_fin -> pause_debut le
    lendemain)."""
    date, minute = _seances(m)
    n = len(m)
    E, X = np.zeros(n, bool), np.zeros(n, bool)
    prix = m["open"].to_numpy(float).copy()
    close = m["close"].to_numpy(float)
    tol, dl = int(p["tolerance_min"]), int(p["delai_min"])
    a, b = _minute(p["pause_debut"]), _minute(p["pause_fin"])
    jambes = {x.strip() for x in str(p["jambes"]).split(",") if x.strip()}
    inconnues = jambes - {"asie", "soir", "tout", "pause", "nuit"}
    if inconnues:
        raise ValueError(f"jambes inconnues : {sorted(inconnues)}")
    debut = np.r_[0, np.flatnonzero(date[1:] != date[:-1]) + 1]
    fin = np.r_[debut[1:], n]
    plan = []

    def premiere(i0, i1, lo, hi):              # premiere barre de la seance dont la minute est dans [lo, hi]
        k = i0 + np.searchsorted(minute[i0:i1], lo, side="left")
        return k if k < i1 and minute[k] <= hi else -1

    def trade(e, s, derniere):
        E[e] = True
        X[s] = True
        if s == derniere:                       # fin de seance : cloture de la derniere minute
            prix[s] = close[s]

    for j, (i0, i1) in enumerate(zip(debut, fin)):
        derniere = i1 - 1
        jour = False
        if "asie" in jambes or "tout" in jambes:
            e = premiere(i0, i1, dl, dl + tol)
            if e >= 0:
                s = derniere if "tout" in jambes else premiere(i0, i1, a + dl, 10 ** 6)
                s = derniere if s < 0 else s
                if s > e:
                    trade(e, s, derniere)
                    jour = True
        if "soir" in jambes:
            e = premiere(i0, i1, b + dl, b + dl + tol)
            if 0 <= e < derniere and not X[e]:
                trade(e, derniere, derniere)
                jour = True
        if "pause" in jambes:
            e = premiere(i0, i1, a + dl, a + dl + tol)
            if e >= 0:
                s = premiere(i0, i1, b + dl, 10 ** 6)
                s = derniere if s < 0 else s
                if s > e:
                    trade(e, s, derniere)
                    jour = True
        if "nuit" in jambes and j + 1 < len(debut):
            e = premiere(i0, i1, b + dl, b + dl + tol)
            k0, k1 = debut[j + 1], fin[j + 1]
            s = premiere(k0, k1, a + dl, 10 ** 6)
            s = k1 - 1 if s < 0 else s
            if e >= 0:
                E[e] = True
                X[s] = True
                jour = True
        if jour:
            plan.append(date[i0])
    return E, X, prix, pd.DatetimeIndex(plan)


def portefeuille(m: pd.DataFrame, compact: bool = False, **params):
    """vbt.Portfolio (une colonne) de la strategie sur les barres 1 minute de GC.
    compact=True : vectorbt ne recoit que les barres d ordres et les dernieres barres de chaque seance (memes trades,
    memes valeurs de fin de seance, beaucoup plus rapide ; pour les grilles et les tirages au hasard)."""
    if vbt is None:
        raise ImportError("vectorbt n est pas installe")
    p = {**DEFAULTS, **params}
    E, X, prix, jours = signaux(m, p)
    date, _ = _seances(m)
    if compact:
        garde = E | X | np.r_[date[1:] != date[:-1], True]
        garde[0] = True
        m, E, X, prix, date = m[garde], E[garde], X[garde], prix[garde], date[garde]
    k = float(p["cout_mult"])
    pf = vbt.Portfolio.from_signals(m["close"], entries=E, exits=X, price=prix, size=float(p["exposition"]),
                                    size_type="percent", fees=m["frais"] * k, slippage=m["glissement"] * k,
                                    init_cash=float(p["capital"]), freq="1min")
    pf.nexus_jours = jours
    pf.nexus_params = p
    pf.nexus_seance = date
    return pf


def valeur(pf) -> pd.Series:
    return pf.value()


def valeur_journaliere(pf, calendrier: pd.DatetimeIndex | None = None) -> pd.Series:
    """Valeur vectorbt a la fin de chaque seance CME (17:00 New York) ; une seance sans equivalent NYSE (jour
    ferie aux Etats-Unis) est reportee sur la seance NYSE suivante."""
    v = valeur(pf)
    date = getattr(pf, "nexus_seance", None)
    if date is None:
        date, _ = seances(v.index)
    d = pd.Series(v.to_numpy(), index=pd.DatetimeIndex(date)).groupby(level=0).last()
    if calendrier is not None:
        d = d.reindex(d.index.union(calendrier)).ffill().reindex(calendrier).bfill()
    return d
