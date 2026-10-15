"""Or la nuit (GC) : backtest construit directement dans vectorbt.

Source : Blose & Gondhalekar (2014), Overnight gold returns, Applied Economics Letters 21(18) ; Blose, Gondhalekar &
Kort (2018), Journal of Economics and Finance 42(3) : sur le COMEX (1985-2012), le rendement de l or se fait hors
de la seance de jour (8:20-13:30 heure de New York) ; pendant cette seance il est negatif en moyenne.

Regle publiee, appliquee telle quelle (jambes="nuit") : achat de GC a 13:30 (cloture du COMEX), vente a 8:20
(ouverture du COMEX) a la seance suivante. La position traverse la pause 17:00-18:00 et, le vendredi, le week-end.
Pas de barre a 13:30 (seance raccourcie, au plus 10 min de retard) : pas d achat ce jour-la ; seance suivante sans
barre apres 8:20 : vente a sa derniere minute (cloture).
Variantes et temoins : version intraday (jambes="asie,soir" : achat 18:00 -> vente 8:20, achat 13:30 -> vente a
la cloture de 17:00, rien pendant la pause ni le week-end), seance entiere intraday ("tout"), seance du COMEX
seule ("pause"), or garde en permanence ("permanent").
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
# micro or (10 onces) : commission par cote supposee (ordre de grandeur des prop firms, a ajuster a son compte)
SPEC_MGC = dict(multiplicateur=10.0, tick=0.1, commission=0.85, glissement_ticks=0.5)
SPECS = {"GC": SPEC_GC, "MGC": SPEC_MGC}
OUVERTURE = 18 * 60                       # debut de seance Globex : 18:00 New York (minute 0 de la seance)
DEFAULTS = dict(pause_debut="08:20", pause_fin="13:30", jambes="nuit", cloture="17:00", fenetres=None, garder_weekend=True,
                contrats=None, swap_nuit=0.0, capital=1_000_000.0, exposition=1.0,
                cout_mult=1.0, tolerance_min=10, delai_min=0)
PUBLICATION = "2014-12-01"     # Blose & Gondhalekar, Overnight gold returns, Applied Economics Letters 21(18), dec. 2014
# Essais comptes pour le Sharpe deflate : 150 hypotheses et variantes avant l ORB, 14 essais de l ORB sur les autres
# contrats, 11 hypotheses sur l or et 3 versions intraday de la nuit (2026-10-15).
ESSAIS = 178
VAR_SHARPE_ESSAIS_ANNUALISE = 0.87
# Decisions du FOMC (reunions programmees ; 2020 : decision d urgence du dimanche 15 mars -> seance du lundi 16 mars).
# Certaines prop firms interdisent d etre en position autour de 14:00 New York ces jours-la.
FOMC = pd.DatetimeIndex("""2016-01-27 2016-03-16 2016-04-27 2016-06-15 2016-07-27 2016-09-21 2016-11-02 2016-12-14
2017-02-01 2017-03-15 2017-05-03 2017-06-14 2017-07-26 2017-09-20 2017-11-01 2017-12-13
2018-01-31 2018-03-21 2018-05-02 2018-06-13 2018-08-01 2018-09-26 2018-11-08 2018-12-19
2019-01-30 2019-03-20 2019-05-01 2019-06-19 2019-07-31 2019-09-18 2019-10-30 2019-12-11
2020-01-29 2020-03-16 2020-04-29 2020-06-10 2020-07-29 2020-09-16 2020-11-05 2020-12-16
2021-01-27 2021-03-17 2021-04-28 2021-06-16 2021-07-28 2021-09-22 2021-11-03 2021-12-15
2022-01-26 2022-03-16 2022-05-04 2022-06-15 2022-07-27 2022-09-21 2022-11-02 2022-12-14
2023-02-01 2023-03-22 2023-05-03 2023-06-14 2023-07-26 2023-09-20 2023-11-01 2023-12-13
2024-01-31 2024-03-20 2024-05-01 2024-06-12 2024-07-31 2024-09-18 2024-11-07 2024-12-18
2025-01-29 2025-03-19 2025-05-07 2025-06-18 2025-07-30 2025-09-17 2025-10-29 2025-12-10
2026-01-28 2026-03-18 2026-04-29 2026-06-17 2026-07-29 2026-09-16""".split())


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


def charger(dossier: str, contrat: str = "GC", commission: float | None = None) -> tuple[pd.DataFrame, dict]:
    """Barres 1 minute de GC (Parquet Databento : UTC, barre datee a son debut) -> open/close ajustes des rolls,
    frais et glissement en fraction du notionnel au prix brut. contrat="MGC" : memes prix (le micro suit GC), couts
    et multiplicateur du micro (10 onces) ; commission par cote modifiable."""
    brut = D.load_folder(dossier, daily=False, only=["GC"])
    if "GC" not in brut:
        raise FileNotFoundError(f"aucun fichier GC (barres 1 minute) dans {dossier}")
    df = brut["GC"]
    if df.attrs.get("fuseau") is None:
        raise ValueError("GC : fichier sans fuseau ; attendu le Parquet Databento horodate en UTC (barre datee a son debut)")
    adj, rolls = ajuster_rolls(df)
    s = dict(SPECS[contrat])
    if commission is not None:
        s["commission"] = float(commission)
    px = df["close"].to_numpy(float)
    idx = pd.DatetimeIndex(df.index)
    idx = idx.tz_convert("UTC").tz_localize(None) if idx.tz is not None else idx
    date, minute = seances(idx)
    m = pd.DataFrame({"open": adj["open"].to_numpy(float), "close": adj["close"].to_numpy(float),
                      "frais": s["commission"] / (px * s["multiplicateur"]),
                      "glissement": s["glissement_ticks"] * s["tick"] / px, "brut": px, "seance": date, "minute": minute}, index=idx)
    m.attrs.update(contrat=contrat, multiplicateur=s["multiplicateur"], commission=s["commission"])
    info = dict(symbole="GC.v.0 (CME COMEX, or 100 onces, contrat continu roule au volume)"
                + (f" ; couts et taille du micro MGC (10 onces, {s['commission']:.2f} $ par cote)" if contrat == "MGC" else ""),
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
    jambes : nuit (regle publiee : pause_fin -> pause_debut de la seance suivante) ; version intraday : asie
    (ouverture 18:00 -> pause_debut) et soir (pause_fin -> fin de seance) ; temoins : tout (seance entiere),
    pause (pause_debut -> pause_fin), permanent (achat a la premiere barre, vente a la derniere)."""
    if p.get("fenetres"):
        return _signaux_fenetres(m, p)
    date, minute = _seances(m)
    n = len(m)
    E, X = np.zeros(n, bool), np.zeros(n, bool)
    prix = m["open"].to_numpy(float).copy()
    close = m["close"].to_numpy(float)
    tol, dl = int(p["tolerance_min"]), int(p["delai_min"])
    a, b = _minute(p["pause_debut"]), _minute(p["pause_fin"])
    cl = _minute(p["cloture"]) if p["cloture"] != "17:00" else 1440     # heure limite des jambes intraday (prop firms)
    jambes = {x.strip() for x in str(p["jambes"]).split(",") if x.strip()}
    inconnues = jambes - {"asie", "soir", "tout", "pause", "nuit", "permanent"}
    if inconnues:
        raise ValueError(f"jambes inconnues : {sorted(inconnues)}")
    debut = np.r_[0, np.flatnonzero(date[1:] != date[:-1]) + 1]
    fin = np.r_[debut[1:], n]
    plan = []

    def premiere(i0, i1, lo, hi):              # premiere barre de la seance dont la minute est dans [lo, hi]
        k = i0 + np.searchsorted(minute[i0:i1], lo, side="left")
        return k if k < i1 and minute[k] <= hi else -1

    fin_seance = set((fin - 1).tolist())
    t_utc = pd.DatetimeIndex(m.index).to_numpy()

    def trade(e, s, derniere):
        E[e] = True
        X[s] = True
        if s == derniere and s in fin_seance:   # fin de seance : cloture de la derniere minute
            prix[s] = close[s]

    for j, (i0, i1) in enumerate(zip(debut, fin)):
        derniere = i1 - 1
        if cl < 1440:                           # sortie forcee a l heure limite (ouverture de la barre), sinon fin de seance
            k = premiere(i0, i1, cl, 10 ** 6)
            derniere = k if k >= 0 else derniere
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
            longue = (t_utc[k0] - t_utc[i1 - 1]) > np.timedelta64(3, "h")      # week-end ou fermeture de jour ferie
            if not p["garder_weekend"] and longue:
                if 0 <= e < derniere:                                         # vendredi : vente a l heure limite
                    trade(e, derniere, derniere)
                    jour = True
                e2 = premiere(k0, k1, dl, dl + tol)                           # dimanche 18:00 : rachat jusqu a 8:20
                if 0 <= e2 < s:
                    trade(e2, s, k1 - 1)
            elif e >= 0:
                trade(e, s, k1 - 1)
                jour = True
        if jour:
            plan.append(date[i0])
    if "permanent" in jambes and n > 1:
        trade(0, n - 1, n - 1)
        plan = list(pd.unique(date))
    return E, X, prix, pd.DatetimeIndex(plan)


def _signaux_fenetres(m: pd.DataFrame, p: dict):
    """Fenetres libres dans chaque seance CME : liste de (debut, fin, sens) ou (debut, fin, sens, seances) en heure de
    New York ; sens +1 achat, -1 vente ; seances = dates de seance CME autorisees (None : toutes). Entree a l ouverture
    de la premiere barre de `debut` (au plus tolerance_min de retard), sortie a l ouverture de la premiere barre de
    `fin` ou de l heure limite `cloture` si elle est plus tot, sinon a la cloture de la derniere barre de la seance.
    Les fenetres d une meme seance ne doivent pas se chevaucher."""
    date, minute = _seances(m)
    n = len(m)
    E, X, SE, SX = (np.zeros(n, bool) for _ in range(4))
    prix = m["open"].to_numpy(float).copy()
    close = m["close"].to_numpy(float)
    tol, dl = int(p["tolerance_min"]), int(p["delai_min"])
    cl = _minute(p["cloture"]) if p["cloture"] != "17:00" else 1440
    debut = np.r_[0, np.flatnonzero(date[1:] != date[:-1]) + 1]
    fin = np.r_[debut[1:], n]
    jours = pd.DatetimeIndex(date[debut])
    fen = []
    for f in p["fenetres"]:
        d0, d1, sens = f[0], f[1], int(f[2])
        ok = None if len(f) < 4 or f[3] is None else np.asarray(jours.isin(pd.DatetimeIndex(f[3])))
        fen.append((_minute(d0) + dl, (_minute(d1) if d1 != "17:00" else 1440) + dl, sens, ok))
    plan = set()
    for j, (i0, i1) in enumerate(zip(debut, fin)):
        mn = minute[i0:i1]
        for a, b, sens, ok in fen:
            if ok is not None and not ok[j]:
                continue
            k = int(np.searchsorted(mn, a, side="left"))
            if k >= len(mn) or mn[k] > a + tol:
                continue
            e = i0 + k
            ks = int(np.searchsorted(mn, min(b, cl), side="left"))
            s = i0 + ks if ks < len(mn) else i1 - 1
            if s <= e:
                continue
            if ks >= len(mn):
                prix[s] = close[s]
            (E if sens > 0 else SE)[e] = True
            (X if sens > 0 else SX)[s] = True
            plan.add(jours[j])
    return (E, X, SE, SX), prix, pd.DatetimeIndex(sorted(plan))


def seances_comex_faibles(m: pd.DataFrame, fenetre: int = 252, part: float = 1 / 3) -> tuple[pd.DatetimeIndex, pd.DatetimeIndex]:
    """Seances dont le rendement du COMEX (8:20 -> 13:30, connu a 13:30) est dans le tiers le plus bas des `fenetre`
    seances precedentes, et les seances qui les suivent."""
    date, minute = _seances(m)
    op = m["open"].to_numpy(float)

    def a(heure):
        sel = minute >= _minute(heure)
        return pd.Series(op[sel], index=pd.DatetimeIndex(date[sel])).groupby(level=0).first()

    r = np.log(a("13:30") / a("08:20")).dropna()
    seuil = r.rolling(fenetre).quantile(part).shift(1)
    faibles = r.index[(r <= seuil).to_numpy()]
    toutes = pd.DatetimeIndex(pd.unique(date))
    pos = toutes.get_indexer(faibles)
    return faibles, toutes[pos[(pos >= 0) & (pos + 1 < len(toutes))] + 1]


def portefeuille(m: pd.DataFrame, compact: bool = False, **params):
    """vbt.Portfolio (une colonne) de la strategie sur les barres 1 minute de GC.
    compact=True : vectorbt ne recoit que les barres d ordres et les dernieres barres de chaque seance (memes trades,
    memes valeurs de fin de seance, beaucoup plus rapide ; pour les grilles et les tirages au hasard)."""
    if vbt is None:
        raise ImportError("vectorbt n est pas installe")
    p = {**DEFAULTS, **params}
    if p.get("fenetres"):
        (E, X, SE, SX), prix, jours = _signaux_fenetres(m, p)
    else:
        E, X, prix, jours = signaux(m, p)
        SE, SX = np.zeros(len(m), bool), np.zeros(len(m), bool)
    date, _ = _seances(m)
    mult = float(m.attrs.get("multiplicateur", SPEC_GC["multiplicateur"]))
    if compact:
        garde = E | X | SE | SX | np.r_[date[1:] != date[:-1], True]
        garde[0] = True
        m, E, X, SE, SX, prix, date = m[garde], E[garde], X[garde], SE[garde], SX[garde], prix[garde], date[garde]
    k = float(p["cout_mult"])
    frais = m["frais"].to_numpy(float) * k
    if p["swap_nuit"]:
        # financement d un CFD (dollars par 100 onces et par nuit, x 3 du vendredi au lundi) : ajoute aux frais d entree
        e_i, s_i = np.flatnonzero(E | SE), np.flatnonzero(X | SX)
        if len(e_i):
            s_de_e = s_i[np.searchsorted(s_i, e_i, side="right").clip(max=len(s_i) - 1)]
            nuits = (pd.DatetimeIndex(date[s_de_e]) - pd.DatetimeIndex(date[e_i])).days.to_numpy()
            brut = m["brut"].to_numpy(float) if "brut" in m else prix
            frais[e_i] += float(p["swap_nuit"]) * nuits / (100.0 * brut[e_i])
    fixe = p["contrats"] is not None
    reserve = 1e9 if fixe else 0.0
    cash = float(p["capital"]) + reserve
    if fixe:            # nombre de contrats : constant, ou un nombre par barre (meme longueur que les barres d origine)
        c_ = np.asarray(p["contrats"], float)
        c_ = c_[garde] if (compact and c_.ndim and len(c_) == len(garde)) else c_
        q = np.broadcast_to(c_ * mult, (len(m),))
    if p.get("fenetres") or fixe:
        # exposition cible : % du capital (retournements possibles sur une meme barre) ou nombre fixe de contrats
        cible = np.full(len(m), np.nan)
        cible[X | SX] = 0.0
        haut = q if fixe else np.full(len(m), float(p["exposition"]))
        cible[E] = haut[E]
        cible[SE] = -haut[SE]
        pf = vbt.Portfolio.from_orders(m["close"], size=cible, size_type="targetamount" if fixe else "targetpercent", price=prix,
                                       fees=frais, slippage=m["glissement"] * k, init_cash=cash, direction="both", freq="1min")
    else:
        pf = vbt.Portfolio.from_signals(m["close"], entries=E, exits=X, price=prix, size=float(p["exposition"]),
                                        size_type="percent", fees=frais, slippage=m["glissement"] * k,
                                        init_cash=cash, freq="1min")
    pf.nexus_reserve = reserve
    pf.nexus_jours = jours
    pf.nexus_params = p
    pf.nexus_seance = date
    return pf


def valeur(pf) -> pd.Series:
    """Valeur du compte (valeur vectorbt moins la reserve de liquidites utilisee pour les contrats fixes)."""
    return pf.value() - getattr(pf, "nexus_reserve", 0.0)


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
