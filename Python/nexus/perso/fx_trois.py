"""Trois strategies FX combinees, sur futures de change CME (6E, 6B, 6J, 6A) executes en micros (M6E, M6B, MJY, M6A).

    python -m nexus.perso.fx_trois [--sortie resultats_fx.txt]

1. FIX FLOW (fix WM/R de 16:00 Londres, ~1 h 15 en position)
   Krohn, Mueller & Whelan : le dollar s apprecie avant les fixings et se deprecie apres. Melvin & Prins : en fin de
   mois, si les actions americaines ont fait mieux que les actions etrangeres (en dollars), les gerants etrangers
   couverts doivent VENDRE du dollar au fix pour se recouvrir (et l inverse). Fiche : fin de mois seulement, on ne prend
   que la jambe ou les deux signaux sont alignes. Stop = 2 x volatilite attendue de la fenetre a cette heure (Andersen &
   Bollerslev : saisonnalite intrajournaliere de la volatilite). Anomalie precise : AUCUN parametre optimise.
2. POST-ANNONCE + FLUX (NFP et CPI a 08:30 ET, 15 a 90 min en position)
   ABDV (Andersen, Bollerslev, Diebold, Vega) : le saut initial absorbe la nouvelle, on attend 5 a 15 min. Le consensus
   des economistes n est pas disponible ici : la surprise est mesuree par le marche, mouvement du panier dollar pendant
   l attente divise par son ecart-type sur les annonces PASSEES (ABDV : la reaction est proportionnelle a la surprise
   standardisee). Entree dans ce sens si le flux de la paire confirme (Love & Payne ; flux approche par classification
   en volume). Sortie : duree maximale ou multiple d ATR. Attente et duree : choisies en walk-forward.
3. CASCADE DE STOPS SUR CHIFFRES RONDS (30 min a 2 h)
   Osler : stops juste au-dela des niveaux ronds (00, 50) -> cassure nette + acceleration de la volatilite =
   continuation ; take-profits sur les niveaux -> approche sans cassure avec ralentissement = rebond. Filtre horaire de
   Ranaldo : la devise domestique se deprecie pendant ses heures de bourse ; on ne garde que les signaux dans ce sens.
   Niveaux lus sur le prix NON ajuste du future (EUR/USD, GBP/USD, AUD/USD) et sur 1 / prix pour USD/JPY : le future
   differe du spot des points de terme. Cassure, acceleration et duree : choisies en walk-forward.
Validation : couts (glissement elargi autour des annonces et du fix, commissions micro), walk-forward hors
echantillon (fenetre de 3 ans, choix annuel), Sharpe deflate, PBO, persistance par annee, combinaison des trois.
"""
from __future__ import annotations

import argparse
import math
import os
from dataclasses import dataclass
from datetime import datetime

import numpy as np
import pandas as pd
from numba import njit

from .orderflow import Marche, _trade, r_quotidien, stats_r
from .qf import INSTRUMENTS, _futures_file, wilder_atr

PY_DIR = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", ".."))
FX = ("6E", "6B", "6J", "6A")
MICRO_FX = {"6E": "M6E", "6B": "M6B", "6J": "MJY", "6A": "M6A", "GC": "MGC", "ES": "MES", "NQ": "MNQ", "YM": "MYM",
            "CL": "MCL"}            # GC, ES, NQ, YM, CL : etudes de l or et des 60 strategies
ETF = {"6E": "EZU", "6B": "EWU", "6J": "EWJ", "6A": "EWA"}          # actions etrangeres en dollars (Melvin & Prins)
R = 250.0
QTE_MAX = 60                       # micros par position au plus
NS_MIN = 60_000_000_000
NS_JOUR = 86_400_000_000_000
ANNEES_WF = 3                      # walk-forward : 3 ans d apprentissage, choix pour l annee suivante
DEBUT_OOS = 2019


# =============================================================================
#  Donnees
# =============================================================================
class FxMarche(Marche):
    def __init__(self, root: str):
        super().__init__(root)
        self.inst = INSTRUMENTS[MICRO_FX[root]]
        self.tick = self.inst.tick
        lon = self.idx.tz_localize("UTC").tz_convert("Europe/London").tz_localize(None).asi8
        self.tod_lon = ((lon // NS_MIN) % 1440).astype(np.int32)
        self.jour_lon = (lon // NS_JOUR).astype(np.int64)
        self.heure_utc = ((self.t // NS_MIN) % 1440 // 60).astype(np.int32)
        raw = pd.read_parquet(_futures_file(root))
        if raw.index.tz is not None:
            raw.index = raw.index.tz_convert("UTC").tz_localize(None)
        raw.index = pd.DatetimeIndex(raw.index + pd.Timedelta(minutes=1)).as_unit("ns")
        raw = raw[~raw.index.duplicated(keep="last")].reindex(self.idx)
        self.rh, self.rl, self.rc = (raw[k].to_numpy(float) for k in ("high", "low", "close"))
        self.offset = self.c - self.rc                          # prix ajuste - prix reel (constant par echeance)
        self._atr5 = None
        self._carte = None

    def indice(self, jour: int, tod: int):
        """Indice de la barre finissant a `tod` (minute ET) le jour calendaire ET `jour`, ou None (08:30 a 08:45)."""
        if self._carte is None:
            sel = np.nonzero((self.tod >= 510) & (self.tod <= 530) & (self.wd < 5))[0]
            self._carte = dict(zip((self.jour[sel] * 1440 + self.tod[sel]).tolist(), sel.tolist()))
        return self._carte.get(int(jour) * 1440 + int(tod))

    def fin_apres(self, i: int, minutes: int) -> int:
        """Dernier indice de la meme seance dont l heure est <= heure(i) + minutes."""
        k = int(np.searchsorted(self.t, self.t[i] + minutes * NS_MIN, side="right")) - 1
        return max(i, min(k, int(self.fin_tday[i])))

    def atr5(self) -> np.ndarray:
        """ATR(14) des barres 5 minutes, porte sur chaque minute (derniere barre 5 min terminee)."""
        if self._atr5 is None:
            b = self.b5
            a = wilder_atr(b["h"], b["l"], b["c"], 14)
            ok = b["pos1"] >= 0
            pos, val = b["pos1"][ok], a[ok]
            k = np.searchsorted(pos, np.arange(self.n), side="right") - 1
            self._atr5 = np.where(k >= 0, val[np.clip(k, 0, None)], np.nan)
        return self._atr5


_FX: dict[str, FxMarche] = {}


def fx(root: str) -> FxMarche:
    if root not in _FX:
        _FX[root] = FxMarche(root)
    return _FX[root]


def evenements() -> pd.DataFrame:
    return pd.read_csv(os.path.join(os.path.dirname(__file__), "annonces_us.csv"), comment="#", parse_dates=["date"])


def etf_close(sym: str) -> pd.Series:
    return pd.read_parquet(os.path.join(PY_DIR, ".cache", "alpaca_jour", f"{sym}.parquet"))["close"]


# =============================================================================
#  Execution (memes regles que qf.Engine : ordre marche a l ouverture suivante + glissement, stop prioritaire)
# =============================================================================
@njit(cache=True)
def _gerer_nb(o, h, l, c, j, side, stop, cible, fin, slip):
    for t in range(j, fin + 1):
        tenu = t > j
        if side > 0:
            hs = l[t] <= stop
        else:
            hs = h[t] >= stop
        if hs:
            px = stop
            if tenu and ((side > 0 and o[t] <= stop) or (side < 0 and o[t] >= stop)):
                px = o[t]
            return t, px - side * slip, 0
        if cible == cible:
            if side > 0:
                ht = h[t] > cible
            else:
                ht = l[t] < cible
            if ht:
                px = cible
                if tenu and ((side > 0 and o[t] >= cible) or (side < 0 and o[t] <= cible)):
                    px = o[t]
                return t, px, 1
    return fin, c[fin] - side * slip, 2


RAISONS = ("stop", "objectif", "temps")


def executer(m: FxMarche, nom: str, decisions: list, gl_entree: int, gl_sortie: int, frais: bool = True) -> pd.DataFrame:
    if not frais:
        gl_entree = gl_sortie = 0
    """decisions : (indice de decision, sens du future, stop, objectif, indice de fin, risque en prix, part de R).
    Une position a la fois ; entree au marche a l ouverture de la barre suivante."""
    rows, libre = [], 0
    se, ss = gl_entree * m.tick, gl_sortie * m.tick
    for i, side, stop, cible, fin, risque, part in sorted(decisions, key=lambda d: d[0]):
        j = i + 1
        if i < libre or j > fin or j >= m.n or m.tday[j] != m.tday[i] or not risque > 0:
            continue
        qty = min(QTE_MAX, int((R * part) // (risque * m.inst.point_value)))
        if qty < 1:
            continue
        px_e = m.o[j] + side * se
        k, px_s, code = _gerer_nb(m.o, m.h, m.l, m.c, j, side, stop if np.isfinite(stop) else np.nan,
                                  cible if np.isfinite(cible) else np.nan, fin, ss)
        rows.append(_trade(m, nom, side, qty, j, px_e, int(k), float(px_s), RAISONS[int(code)], R, frais))
        libre = int(k) + 1
    t = pd.DataFrame(rows)
    if len(t):
        t["instrument"] = m.root
    return t


# =============================================================================
#  1. Fix flow
# =============================================================================
@dataclass
class ParamsFix:
    mode: str = "aligne"           # fiche : fin de mois, jambes alignees ; "krohn" : tous les jours ; "non_aligne" : diagnostic
    debut: int = 15 * 60           # 15:00 Londres : debut de la jambe acheteuse de dollar (1 h avant le fix) [Choix]
    fix: int = 16 * 60             # 16:00 Londres : fix WM/R
    fin_apres: int = 16 * 60 + 15  # 16:15 : fin de la jambe vendeuse (~1 h 15 en tout, comme la fiche)
    k_stop: float = 2.0            # stop = 2 x volatilite attendue de la fenetre (Andersen & Bollerslev)
    jours_vol: int = 60
    gl_normal: int = 1
    gl_fix: int = 2                # spread elargi autour du fix


def signal_melvin_prins(root: str, jours: pd.DatetimeIndex) -> pd.Series:
    """+1 = acheter du dollar, -1 = vendre du dollar, au fix de fin de mois. Rendements du mois en dollars jusqu a la
    cloture de la VEILLE (le fix de 16:00 Londres a lieu avant la cloture de New York)."""
    us, fo = etf_close("SPY"), etf_close(ETF[root])
    out = {}
    for d in jours:
        fin_prec = d.replace(day=1) - pd.Timedelta(days=1)
        a, b = us[us.index <= fin_prec], fo[fo.index <= fin_prec]
        a1, b1 = us[us.index < d], fo[fo.index < d]
        if len(a) == 0 or len(b) == 0 or len(a1) == 0 or len(b1) == 0 or a1.index[-1] <= fin_prec:
            continue
        ecart = (a1.iloc[-1] / a.iloc[-1] - 1) - (b1.iloc[-1] / b.iloc[-1] - 1)
        out[d] = -1 if ecart > 0 else 1
    return pd.Series(out, dtype=float)


def diagnostic_fix(m: FxMarche, p: ParamsFix = ParamsFix()) -> pd.DataFrame:
    """Rendement moyen du DOLLAR (points de base, sans execution ni couts) avant le fix (15:00 -> 16:00 Londres) et apres
    (16:00 -> 16:15), tous les jours et en fin de mois, par periode, avec son t de Student."""
    bars = pd.DataFrame({"jour": m.jour_lon, "tod": m.tod_lon, "i": np.arange(m.n)})
    bars = bars[bars["tod"].isin((p.debut, p.fix, p.fin_apres))].drop_duplicates(["jour", "tod"], keep="last")
    piv = bars.pivot(index="jour", columns="tod", values="i").dropna().astype(np.int64)
    jours = pd.to_datetime(piv.index * NS_JOUR)
    piv, jours = piv[jours.dayofweek < 5], jours[jours.dayofweek < 5]
    i0, i1, i2 = (piv[k].to_numpy() for k in (p.debut, p.fix, p.fin_apres))
    fin_mois = pd.Series(jours, index=jours).groupby([jours.year, jours.month]).transform("max").to_numpy() == jours.to_numpy()
    d = pd.DataFrame({"avant": -np.log(m.c[i1] / m.c[i0]) * 1e4, "apres": -np.log(m.c[i2] / m.c[i1]) * 1e4,
                      "periode": np.where(jours < pd.Timestamp("2021-01-01"), "2016-2020", "2021-2026"), "fin_mois": fin_mois})
    rows = []
    for (per, fm), g in [((per, "tous les jours"), g) for per, g in d.groupby("periode")] +                         [((per, "fin de mois"), g[g["fin_mois"]]) for per, g in d.groupby("periode")]:
        for col in ("avant", "apres"):
            x = g[col].dropna()
            rows.append(dict(periode=per, jours=fm, jambe=col, n=len(x), moyenne_pb=x.mean(),
                             t=x.mean() / (x.std(ddof=1) / math.sqrt(len(x))) if len(x) > 2 else math.nan))
    return pd.DataFrame(rows)


def diagnostic_mp(m: FxMarche, p: ParamsFix = ParamsFix()) -> pd.DataFrame:
    """Fins de mois : rendement du dollar (pb) avant et apres le fix selon le signal de Melvin & Prins. Si le signal
    compte, le dollar doit monter quand il dit « acheter » et baisser quand il dit « vendre »."""
    bars = pd.DataFrame({"jour": m.jour_lon, "tod": m.tod_lon, "i": np.arange(m.n)})
    bars = bars[bars["tod"].isin((p.debut, p.fix, p.fin_apres))].drop_duplicates(["jour", "tod"], keep="last")
    piv = bars.pivot(index="jour", columns="tod", values="i").dropna().astype(np.int64)
    jours = pd.to_datetime(piv.index * NS_JOUR)
    piv, jours = piv[jours.dayofweek < 5], jours[jours.dayofweek < 5]
    fm = pd.Series(jours, index=jours).groupby([jours.year, jours.month]).transform("max").to_numpy() == jours.to_numpy()
    j = jours[fm]
    i0, i1, i2 = (piv[k].to_numpy()[fm] for k in (p.debut, p.fix, p.fin_apres))
    d = pd.DataFrame({"avant": -np.log(m.c[i1] / m.c[i0]) * 1e4, "apres": -np.log(m.c[i2] / m.c[i1]) * 1e4,
                      "mp": signal_melvin_prins(m.root, j).reindex(j).to_numpy()}).dropna()
    rows = []
    for sig, g in d.groupby("mp"):
        row = dict(signal="acheter du dollar" if sig > 0 else "vendre du dollar", n=len(g))
        for col in ("avant", "apres"):
            x = g[col]
            row[col] = x.mean()
            row["t_" + col] = x.mean() / (x.std(ddof=1) / math.sqrt(len(x))) if len(x) > 2 else math.nan
        rows.append(row)
    return pd.DataFrame(rows)


def backtest_fix(m: FxMarche, p: ParamsFix = ParamsFix(), nom: str = "Fix", gl_plus: int = 0, brut: bool = False) -> pd.DataFrame:
    bars = pd.DataFrame({"jour": m.jour_lon, "tod": m.tod_lon, "i": np.arange(m.n)})
    bars = bars[bars["tod"].isin((p.debut, p.fix, p.fin_apres))].drop_duplicates(["jour", "tod"], keep="last")
    piv = bars.pivot(index="jour", columns="tod", values="i").dropna().astype(np.int64)
    piv = piv[pd.to_datetime(piv.index * NS_JOUR).dayofweek < 5]
    i0, i1, i2 = (piv[k].to_numpy() for k in (p.debut, p.fix, p.fin_apres))
    r_av = pd.Series(np.log(m.c[i1] / m.c[i0]), index=piv.index)
    r_ap = pd.Series(np.log(m.c[i2] / m.c[i1]), index=piv.index)
    s_av = r_av.rolling(p.jours_vol, min_periods=20).std().shift(1).to_numpy()
    s_ap = r_ap.rolling(p.jours_vol, min_periods=20).std().shift(1).to_numpy()
    jours = pd.to_datetime(piv.index * NS_JOUR)
    fin_mois = pd.Series(jours, index=jours).groupby([jours.year, jours.month]).transform("max").to_numpy() == jours.to_numpy()
    mp = signal_melvin_prins(m.root, jours[fin_mois]) if p.mode != "krohn" else pd.Series(dtype=float)
    dec_av, dec_ap = [], []
    for k in range(len(piv)):
        if p.mode == "krohn":
            jambes = (+1, -1)
        else:
            if not fin_mois[k] or jours[k] not in mp.index:
                continue
            usd = int(mp[jours[k]])
            jambes = ((usd,) if p.mode == "aligne" else (-usd,))
        for usd_dir in jambes:
            side = -usd_dir                                    # futures cotes en dollars par devise : dollar haut = future bas
            if usd_dir > 0 and np.isfinite(s_av[k]):           # jambe avant le fix (dollar acheteur)
                d = p.k_stop * s_av[k] * m.c[i0[k]]
                dec_av.append((int(i0[k]), side, m.c[i0[k]] - side * d, np.nan, int(i1[k]), d, 1.0))
            elif usd_dir < 0 and np.isfinite(s_ap[k]):         # jambe apres le fix (dollar vendeur)
                d = p.k_stop * s_ap[k] * m.c[i1[k]]
                dec_ap.append((int(i1[k]), side, m.c[i1[k]] - side * d, np.nan, int(i2[k]), d, 1.0))
    t = [executer(m, nom, dec_av, p.gl_normal + gl_plus, p.gl_fix + gl_plus, not brut).assign(jambe="avant le fix"),
         executer(m, nom, dec_ap, p.gl_fix + gl_plus, p.gl_normal + gl_plus, not brut).assign(jambe="apres le fix")]
    t = [x for x in t if len(x)]
    return pd.concat(t, ignore_index=True).sort_values("entry_time") if t else pd.DataFrame()


# =============================================================================
#  2. Post-annonce + flux
# =============================================================================
@dataclass
class ParamsAnnonce:
    attente: int = 10              # minutes apres 08:30 [Fiche : 5 a 15] - walk-forward
    duree: int = 60                # minutes en position au plus [Fiche : <= 90] - walk-forward
    seuil_z: float = 1.0           # [Choix] surprise standardisee minimale
    k_stop: float = 2.0            # [Choix] stop a 2 ATR intraday (barres 5 min)
    k_cible: float = 3.0           # [Choix] objectif a 3 ATR
    gl_entree: int = 3             # spread encore elargi dans les minutes qui suivent l annonce [Choix]
    gl_sortie: int = 2


GRILLE_ANNONCE = [dict(attente=a, duree=d) for a in (5, 10, 15) for d in (30, 60, 90)]


def surprises(marches: dict, attente: int) -> pd.DataFrame:
    """Surprise implicite de chaque annonce : rendement du panier dollar entre 08:30 et 08:30 + attente, divise par
    l ecart-type de cette mesure sur les annonces precedentes (au moins 10)."""
    ev = evenements()
    ev = ev[ev["evenement"].isin(("NFP", "CPI"))]               # fiche FX : NFP et CPI seulement
    lignes = []
    for d, nom in zip(ev["date"], ev["evenement"]):
        jd = int(d.value // NS_JOUR)
        mv, idx = [], {}
        for r, m in marches.items():
            i0, i1 = m.indice(jd, 510), m.indice(jd, 510 + attente)
            if i0 is not None and i1 is not None:
                mv.append(-math.log(m.c[i1] / m.c[i0]))         # dollar haut = future bas
                idx[r] = (i0, i1)
        if len(mv) >= 2:
            lignes.append(dict(date=d, evenement=nom, usd=float(np.mean(mv)), idx=idx))
    s = pd.DataFrame(lignes)
    if s.empty:
        return s
    sd = s["usd"].expanding(min_periods=10).std().shift(1)
    s["z"] = s["usd"] / sd
    return s


def backtest_annonce(marches: dict, p: ParamsAnnonce = ParamsAnnonce(), nom: str = "Annonce", gl_plus: int = 0,
                     cache: dict | None = None, brut: bool = False) -> pd.DataFrame:
    key = p.attente
    if cache is not None and key in cache:
        s = cache[key]
    else:
        s = surprises(marches, p.attente)
        if cache is not None:
            cache[key] = s
    dec = {r: [] for r in marches}
    for row in s.itertuples():
        if not np.isfinite(row.z) or abs(row.z) < p.seuil_z:
            continue
        usd_dir = 1 if row.z > 0 else -1
        for r, (i0, i1) in row.idx.items():
            m = marches[r]
            flux_usd = -m.delta_bvc()[i0 + 1:i1 + 1].sum()        # Love & Payne : le flux confirme-t-il ?
            if np.sign(flux_usd) != usd_dir:
                continue
            a = m.atr5()[i1]
            if not np.isfinite(a) or a <= 0:
                continue
            side = -usd_dir
            px = m.c[i1]
            dec[r].append((i1, side, px - side * p.k_stop * a, px + side * p.k_cible * a, m.fin_apres(i1 + 1, p.duree),
                           p.k_stop * a, 1.0))
    t = [executer(marches[r], nom, dec[r], p.gl_entree + gl_plus, p.gl_sortie + gl_plus, not brut) for r in marches]
    t = [x for x in t if len(x)]
    return pd.concat(t, ignore_index=True).sort_values("entry_time") if t else pd.DataFrame()


# =============================================================================
#  3. Cascade de stops sur chiffres ronds
# =============================================================================
@dataclass
class ParamsRond:
    cassure_pips: float = 5.0      # cassure nette : cloture 5 min au-dela du niveau [Choix] - walk-forward {3, 6}
    accel: float = 1.5             # range des 15 dernieres minutes >= 1,5 x mediane du creneau - walk-forward {1.5, 2}
    duree: int = 60                # minutes [Fiche : 30 a 120] - walk-forward {30, 60, 120}
    approche_pips: float = 3.0     # rebond : extreme a moins de 3 pips du niveau, sans le toucher [Choix]
    ralenti: float = 0.7           # rebond : range 15 min <= 0,7 x mediane du creneau [Choix]
    stop_pips: float = 10.0        # stop a 10 pips de l autre cote du niveau [Choix]
    pas_pips: float = 50.0         # niveaux 00 et 50 (Osler)
    ranaldo: bool = True
    gl: int = 1


GRILLE_RONDS = [dict(cassure_pips=b, accel=a, duree=d) for b in (3.0, 6.0) for a in (1.5, 2.0) for d in (30, 60, 120)]


def biais_ranaldo(root: str, heure_utc: np.ndarray) -> np.ndarray:
    """Sens attendu du cours (devise de base / devise de cotation, USD/JPY pour 6J) selon l heure : la devise domestique
    se deprecie pendant ses heures de bourse (Ranaldo). Heures UTC approchees, 0 = pas de biais (signal ecarte)."""
    b = np.zeros(heure_utc.size, dtype=np.int8)
    europe, us = (heure_utc >= 7) & (heure_utc < 12), (heure_utc >= 17) & (heure_utc < 21)
    asie = (heure_utc >= 23) | (heure_utc < 6)
    if root in ("6E", "6B"):
        b[europe], b[us] = -1, 1                 # EUR / GBP baissent en Europe, le dollar baisse a New York
    elif root == "6A":
        b[asie], b[us] = -1, 1                   # AUD baisse a Sydney / Tokyo
    elif root == "6J":
        b[asie], b[us] = 1, -1                   # USD/JPY monte a Tokyo (yen domestique), baisse a New York
    return b


def _cotation_5min(m: FxMarche):
    """Barres 5 min du prix REEL, exprime dans la cotation usuelle (USD/JPY = 1 / prix du 6J)."""
    raw = pd.DataFrame({"high": m.rh, "low": m.rl, "close": m.rc}, index=m.idx).dropna()
    rs = raw.resample("5min", label="right", closed="right")
    b = pd.DataFrame({"high": rs["high"].max(), "low": rs["low"].min(), "close": rs["close"].last()}).dropna()
    if m.root == "6J":
        b = pd.DataFrame({"high": 1 / b["low"], "low": 1 / b["high"], "close": 1 / b["close"]}, index=b.index)
    return b


_PREP3: dict = {}


def _prep_ronds(m: FxMarche):
    if m.root in _PREP3:
        return _PREP3[m.root]
    b = _cotation_5min(m)
    t5 = pd.DatetimeIndex(b.index).as_unit("ns").asi8
    h, l, c = (b[k].to_numpy(float) for k in ("high", "low", "close"))
    n = len(c)
    cont3 = np.zeros(n, bool)
    cont3[3:] = (t5[3:] - t5[:-3]) == 15 * NS_MIN
    rng3 = np.full(n, np.nan)
    hh = pd.Series(h).rolling(3).max().to_numpy()
    ll = pd.Series(l).rolling(3).min().to_numpy()
    rng3[cont3] = (hh - ll)[cont3]
    et = pd.DatetimeIndex(t5).tz_localize("UTC").tz_convert("America/New_York").tz_localize(None).asi8
    slot = ((et // NS_MIN) % 1440).astype(np.int32)
    tday = ((et + 6 * 3_600_000_000_000) // NS_JOUR).astype(np.int64)
    f = pd.DataFrame({"tday": tday, "slot": slot, "r": rng3})
    pv = f.groupby(["tday", "slot"])["r"].last().unstack()
    med = pv.rolling(20, min_periods=10).median().shift(1)
    medr = med.to_numpy()[pv.index.get_indexer(tday), pv.columns.get_indexer(slot)]
    pos1 = np.searchsorted(m.t, t5, side="right") - 1
    okp = (pos1 >= 0) & (m.t[np.clip(pos1, 0, None)] > t5 - 5 * NS_MIN)
    heure = ((t5 // NS_MIN) % 1440 // 60).astype(np.int32)
    out = dict(h=h, l=l, c=c, rng3=rng3, med=medr, pos1=np.where(okp, pos1, -1),
               biais=biais_ranaldo(m.root, heure), pip=0.01 if m.root == "6J" else 0.0001)
    _PREP3[m.root] = out
    return out


def backtest_ronds(m: FxMarche, p: ParamsRond = ParamsRond(), nom: str = "Ronds", gl_plus: int = 0, brut: bool = False) -> pd.DataFrame:
    P = _prep_ronds(m)
    h, l, c, rng3, med, pip = P["h"], P["l"], P["c"], P["rng3"], P["med"], P["pip"]
    pas = p.pas_pips * pip
    n = len(c)
    k = np.arange(4, n)
    pc, cc = c[k - 1], c[k]
    ok = np.isfinite(rng3[k]) & np.isfinite(med[k]) & (med[k] > 0) & (P["pos1"][k] >= 0)
    # continuation : cassure nette d un niveau rond + acceleration de la volatilite (cascade de stops)
    L_up = np.floor(cc / pas) * pas
    up = ok & (pc < L_up) & (cc >= L_up + p.cassure_pips * pip) & (rng3[k] >= p.accel * med[k])
    L_dn = np.ceil(cc / pas) * pas
    dn = ok & (pc > L_dn) & (cc <= L_dn - p.cassure_pips * pip) & (rng3[k] >= p.accel * med[k])
    # rebond : approche du niveau sans le toucher, avec ralentissement (take-profits)
    L_ab = np.ceil(cc / pas) * pas
    reb_haut = ok & (h[k] < L_ab) & (L_ab - h[k] <= p.approche_pips * pip) & (cc > c[k - 3]) & (rng3[k] <= p.ralenti * med[k])
    L_be = np.floor(cc / pas) * pas
    reb_bas = ok & (l[k] > L_be) & (l[k] - L_be <= p.approche_pips * pip) & (cc < c[k - 3]) & (rng3[k] <= p.ralenti * med[k])
    sig = []                                                     # (indice 5 min, sens dans la cotation, stop dans la cotation)
    for mask, sens, niv, cote in ((up, 1, L_up, -1), (dn, -1, L_dn, 1), (reb_haut, -1, L_ab, 1), (reb_bas, 1, L_be, -1)):
        for kk in np.nonzero(mask)[0]:
            if p.ranaldo and P["biais"][k[kk]] != sens:
                continue
            sig.append((int(k[kk]), sens, niv[kk] + cote * p.stop_pips * pip))
    dec = []
    for k5, sens, stop_q in sig:
        i = int(P["pos1"][k5])
        stop_reel = 1.0 / stop_q if m.root == "6J" else stop_q
        side = -sens if m.root == "6J" else sens
        stop = stop_reel + m.offset[i]
        risque = (m.c[i] - stop) * side
        if not np.isfinite(risque) or risque <= 0:
            continue
        dec.append((i, side, stop, np.nan, m.fin_apres(i + 1, p.duree), risque, 1.0))
    return executer(m, nom, dec, p.gl + gl_plus, p.gl + gl_plus, not brut)


def diagnostic_ranaldo(m: FxMarche) -> pd.DataFrame:
    """Rendement moyen (pips) par plage horaire UTC, dans la cotation usuelle, avant / apres 2021 : le biais de Ranaldo
    tient-il encore ?"""
    P = _prep_ronds(m)
    c = P["c"]
    r = np.r_[np.nan, np.diff(c)] / P["pip"]
    b = _cotation_5min(m)
    heure = pd.DatetimeIndex(b.index).hour
    plage = np.select([(heure >= 23) | (heure < 6), (heure >= 7) & (heure < 12), (heure >= 12) & (heure < 17), (heure >= 17) & (heure < 21)],
                      ["Asie 23-06 h", "Europe 07-12 h", "chevauchement 12-17 h", "New York 17-21 h"], "autre")
    per = np.where(b.index < pd.Timestamp("2021-01-01"), "2016-2020", "2021-2026")
    d = pd.DataFrame({"plage": plage, "periode": per, "r": r})
    jours = pd.Series(b.index.normalize()).nunique() / 2
    return (d.groupby(["plage", "periode"])["r"].sum() / jours).unstack()


# =============================================================================
#  Walk-forward
# =============================================================================
def walk_forward(par_config: dict, debut_oos: int = DEBUT_OOS, annees: int = ANNEES_WF) -> tuple[pd.DataFrame, list]:
    """par_config : {libelle: trades}. Chaque annee hors echantillon, on prend la configuration au meilleur R total sur les
    `annees` precedentes, sans jamais regarder l annee testee. -> (trades hors echantillon, choix par annee)."""
    fin = max(t["entry_time"].max().year for t in par_config.values() if len(t))
    out, choix = [], []
    for an in range(debut_oos, fin + 1):
        a, b = pd.Timestamp(f"{an - annees}-01-01"), pd.Timestamp(f"{an}-01-01")
        scores = {lab: t.loc[(t["entry_time"] >= a) & (t["entry_time"] < b), "r"].sum() if len(t) else -np.inf
                  for lab, t in par_config.items()}
        best = max(scores, key=scores.get)
        t = par_config[best]
        sel = t[(t["entry_time"] >= b) & (t["entry_time"] < pd.Timestamp(f"{an + 1}-01-01"))] if len(t) else t
        out.append(sel)
        choix.append((an, best, scores[best]))
    out = [x for x in out if len(x)]
    return (pd.concat(out, ignore_index=True) if out else pd.DataFrame()), choix


def _pbo(par_config: dict, jours) -> float:
    from .. import validation as V
    mat = np.vstack([r_quotidien(t, jours).to_numpy() for t in par_config.values() if len(t)])
    v, _ = V.pbo(mat) if mat.shape[0] >= 2 else (math.nan, 0)
    return float(v)


# =============================================================================
#  Etude complete
# =============================================================================
def _ligne(nom, t, n):
    from .orderflow import _fmt_stats
    return _fmt_stats(nom, stats_r(t, n))


def _par_annee(t: pd.DataFrame) -> str:
    if t.empty:
        return "aucun trade"
    a = t.groupby(t["entry_time"].dt.year)["r"].sum()
    return " | ".join(f"{y} {v:+.1f}R" for y, v in a.items())


def strategies(log=print) -> dict:
    """Calcule les trois strategies (configurations de la fiche, grilles et walk-forward). -> dictionnaire de resultats."""
    M = {r: fx(r) for r in FX}
    res = {}
    log("[fx] 1. fix flow")
    res["fix"] = pd.concat([backtest_fix(m, ParamsFix(), "FX fix flow") for m in M.values()], ignore_index=True)
    res["fix_krohn"] = pd.concat([backtest_fix(m, ParamsFix(mode="krohn"), "Fix Krohn seul") for m in M.values()], ignore_index=True)
    res["fix_non_aligne"] = pd.concat([backtest_fix(m, ParamsFix(mode="non_aligne"), "Fix non aligne") for m in M.values()],
                                      ignore_index=True)
    res["fix_stress"] = pd.concat([backtest_fix(m, ParamsFix(), "FX fix flow", gl_plus=1) for m in M.values()], ignore_index=True)
    res["fix_brut"] = pd.concat([backtest_fix(m, ParamsFix(), "FX fix flow", brut=True) for m in M.values()], ignore_index=True)
    res["fix_diag"] = {r: diagnostic_fix(m) for r, m in M.items()}
    res["fix_mp"] = {r: diagnostic_mp(m) for r, m in M.items()}
    log("[fx] 2. post-annonce")
    cache = {}
    grille2 = {f"attente {g['attente']} min, duree {g['duree']} min": backtest_annonce(M, ParamsAnnonce(**g), "FX post-annonce", cache=cache)
               for g in GRILLE_ANNONCE}
    res["annonce_grille"] = grille2
    res["annonce"], res["annonce_choix"] = walk_forward(grille2)
    res["annonce_fiche"] = grille2["attente 10 min, duree 60 min"]
    res["annonce_brut"] = backtest_annonce(M, ParamsAnnonce(), "FX post-annonce", cache=cache, brut=True)
    grille2s = {lab: backtest_annonce(M, ParamsAnnonce(**g), "FX post-annonce", gl_plus=2, cache=cache)
                for lab, g in zip(grille2, GRILLE_ANNONCE)}
    res["annonce_stress"] = pd.concat([grille2s[b][grille2s[b]["entry_time"].dt.year == a] for a, b, _ in res["annonce_choix"]
                                       if len(grille2s[b])], ignore_index=True)
    log("[fx] 3. chiffres ronds")
    grille3 = {}
    for g in GRILLE_RONDS:
        lab = f"cassure {g['cassure_pips']:g} pips, acceleration {g['accel']:g}, duree {g['duree']} min"
        t = [backtest_ronds(m, ParamsRond(**g), "FX chiffres ronds") for m in M.values()]
        t = [x for x in t if len(x)]
        grille3[lab] = pd.concat(t, ignore_index=True) if t else pd.DataFrame()
    res["ronds_grille"] = grille3
    res["ronds"], res["ronds_choix"] = walk_forward(grille3)
    res["ronds_brut"] = pd.concat([backtest_ronds(m, ParamsRond(), "FX chiffres ronds", brut=True) for m in M.values()],
                                  ignore_index=True)
    res["ronds_sans_ranaldo"] = pd.concat([backtest_ronds(m, ParamsRond(ranaldo=False), "Ronds sans Ranaldo") for m in M.values()],
                                          ignore_index=True)
    st = []
    for a, b, _ in res["ronds_choix"]:
        g = GRILLE_RONDS[list(grille3).index(b)]
        for m in M.values():
            x = backtest_ronds(m, ParamsRond(**g), "FX chiffres ronds", gl_plus=1)
            if len(x):
                st.append(x[x["entry_time"].dt.year == a])
    res["ronds_stress"] = pd.concat(st, ignore_index=True) if st else pd.DataFrame()
    res["ranaldo"] = {r: diagnostic_ranaldo(m) for r, m in M.items()}
    oos = pd.Timestamp(f"{DEBUT_OOS}-01-01")
    parts = [res["fix"][res["fix"]["entry_time"] >= oos], res["annonce"], res["ronds"]]
    res["combine"] = pd.concat([x for x in parts if len(x)], ignore_index=True).sort_values("entry_time")
    return res


def etude(sortie: str | None = None, log=print) -> dict:
    t0 = datetime.now()
    res = strategies(log)
    L = []
    pr = L.append
    n2, n3 = len(GRILLE_ANNONCE), len(GRILLE_RONDS)
    n_tot = 3 + n2 + n3
    pr("=" * 118)
    pr(" TROIS STRATEGIES FX COMBINEES - futures CME 6E, 6B, 6J, 6A (micros), Databento 1 minute 2016-2026")
    pr("=" * 118)
    pr("1R = 250 $, taille = plancher(R / risque du stop) en micros (60 au plus). Couts : commission micro 0,60 $ par cote,")
    pr("glissement 1 tick (2 ticks a 16:00 Londres, 3 ticks a l entree apres une annonce, 2 a la sortie) ; stress : +1 a +2 ticks.")
    pr(f"Walk-forward : chaque annee a partir de {DEBUT_OOS}, configuration au meilleur R des {ANNEES_WF} annees precedentes.")
    pr(f"Sharpe deflate : {n_tot} essais comptes (3 variantes du fix, {n2} configurations post-annonce, {n3} chiffres ronds).\n")

    pr("=== 1. FIX FLOW (Krohn et al. + Melvin & Prins, stop Andersen & Bollerslev) - aucun parametre optimise ===")
    pr("Jambe avant le fix 15:00 -> 16:00 Londres (dollar acheteur), jambe apres 16:00 -> 16:15 (dollar vendeur) ; fin de mois,")
    pr("jambe alignee avec le signal de Melvin & Prins (SPY contre EZU / EWU / EWJ / EWA sur le mois, en dollars).")
    for nom, t in [("Fix flow (fiche : fin de mois, aligne)", res["fix"]), ("  stress +1 tick", res["fix_stress"]),
                   ("diagnostic : Krohn seul, tous les jours", res["fix_krohn"]),
                   ("diagnostic : fin de mois, jambes NON alignees", res["fix_non_aligne"]),
                   ("diagnostic : fiche sans aucun cout", res["fix_brut"])]:
        pr(_ligne(nom, t, n_tot))
    pr("L anomalie existe-t-elle ici, sans execution ? Rendement du DOLLAR en points de base (t de Student) :")
    for r, d in res["fix_diag"].items():
        pr(f"  {r} : " + " | ".join(f"{x.periode} {x.jours} {x.jambe} {x.moyenne_pb:+.2f} ({x.t:+.1f})" for x in d.itertuples()))
    pr("  (Krohn et al. : dollar en hausse AVANT le fix, en baisse APRES.)")
    pr("Fins de mois selon le signal de Melvin & Prins (dollar avant / apres le fix, pb) :")
    for r, d in res["fix_mp"].items():
        pr(f"  {r} : " + " | ".join(f"signal {x.signal} ({x.n} mois) : avant {x.avant:+.2f} (t {x.t_avant:+.1f}), apres {x.apres:+.2f} "
                                   f"(t {x.t_apres:+.1f})" for x in d.itertuples()))
    k = res["fix_krohn"]
    if len(k):
        av, ap = k[k["jambe"] == "avant le fix"], k[k["jambe"] == "apres le fix"]
        pr(f"  Krohn seul, par jambe : avant le fix {av['r'].mean():+.3f}R ({len(av)} trades) ; apres le fix {ap['r'].mean():+.3f}R ({len(ap)})")
    pr("  Persistance (fiche) : " + _par_annee(res["fix"]))
    pr("  Persistance (Krohn seul) : " + _par_annee(res["fix_krohn"]))

    pr("\n=== 2. POST-ANNONCE + FLUX (NFP, CPI ; ABDV, Love & Payne) ===")
    pr("Surprise implicite (consensus indisponible) : panier dollar entre 08:30 et 08:30 + attente, standardise sur les")
    pr("annonces passees ; |z| >= 1 ; flux de la paire (classification en volume) dans le meme sens ; stop 2 ATR, objectif 3 ATR.")
    pr("Grille (toute la periode, pour information) :")
    for lab, t in res["annonce_grille"].items():
        s = stats_r(t)
        pr(f"  {lab:32} {s.get('n', 0):5d} trades | esperance {s.get('esperance', math.nan):+.3f}R | total {s.get('total', math.nan):+7.1f}R")
    jours = pd.bdate_range("2016-01-01", "2026-10-01")
    pr(f"PBO de la grille : {_pbo(res['annonce_grille'], jours):.0%}")
    pr("Choix du walk-forward : " + " | ".join(f"{a} : {b}" for a, b, _ in res["annonce_choix"]))
    pr(_ligne(f"Post-annonce, walk-forward {DEBUT_OOS}-2026", res["annonce"], n_tot))
    pr(_ligne("  stress +2 ticks", res["annonce_stress"], n_tot))
    pr(_ligne("  configuration du milieu de la fiche (10 min, 60 min), toute la periode", res["annonce_fiche"], n_tot))
    pr(_ligne("  diagnostic : la meme sans aucun cout", res["annonce_brut"], n_tot))
    pr("  Persistance (walk-forward) : " + _par_annee(res["annonce"]))

    pr("\n=== 3. CASCADE DE STOPS SUR CHIFFRES RONDS (Osler, filtre horaire de Ranaldo) ===")
    pr("Niveaux 00 / 50 sur le prix reel (non ajuste) du future, USD/JPY = 1 / prix du 6J ; barres 5 min ; continuation apres")
    pr("une cassure nette avec acceleration, rebond apres une approche sans cassure avec ralentissement ; stop 10 pips de l autre")
    pr("cote du niveau ; sortie au bout de la duree.")
    pr("Grille (toute la periode, pour information) :")
    for lab, t in res["ronds_grille"].items():
        s = stats_r(t)
        pr(f"  {lab:52} {s.get('n', 0):5d} trades | esperance {s.get('esperance', math.nan):+.3f}R | total {s.get('total', math.nan):+8.1f}R")
    pr(f"PBO de la grille : {_pbo(res['ronds_grille'], jours):.0%}")
    pr("Choix du walk-forward : " + " | ".join(f"{a} : {b}" for a, b, _ in res["ronds_choix"]))
    pr(_ligne(f"Chiffres ronds, walk-forward {DEBUT_OOS}-2026", res["ronds"], n_tot))
    pr(_ligne("  stress +1 tick", res["ronds_stress"], n_tot))
    pr(_ligne("  sans filtre de Ranaldo (parametres par defaut)", res["ronds_sans_ranaldo"], n_tot))
    pr(_ligne("  diagnostic : parametres par defaut sans aucun cout", res["ronds_brut"], n_tot))
    pr("  Persistance (walk-forward) : " + _par_annee(res["ronds"]))
    pr("Biais horaire de Ranaldo dans ces donnees (pips par jour et par plage, cotation usuelle ; le filtre suppose : devise")
    pr("domestique en baisse pendant ses heures) :")
    for r, d in res["ranaldo"].items():
        pr(f"  {r} : " + " | ".join(f"{pl} {row.get('2016-2020', math.nan):+.2f} / {row.get('2021-2026', math.nan):+.2f}"
                                   for pl, row in d.iterrows() if pl != "autre") + "  (2016-2020 / 2021-2026)")

    pr(f"\n=== COMBINAISON DES TROIS ({DEBUT_OOS}-2026, hors echantillon pour 2 et 3) ===")
    c = res["combine"]
    pr(_ligne("Trois strategies combinees", c, n_tot))
    if len(c):
        jours_oos = pd.bdate_range(f"{DEBUT_OOS}-01-01", c["exit_time"].max())
        m = pd.DataFrame({nom: r_quotidien(t[t["entry_time"] >= pd.Timestamp(f"{DEBUT_OOS}-01-01")], jours_oos)
                          for nom, t in [("fix", res["fix"]), ("annonce", res["annonce"]), ("ronds", res["ronds"])] if len(t)})
        with pd.option_context("display.float_format", "{:+.2f}".format):
            pr("Correlation des R quotidiens :")
            pr(m.corr().to_string())
        pr("  Persistance : " + _par_annee(c))
    pr(f"\nCalcul en {(datetime.now() - t0).total_seconds():.0f} s.")
    out_dir = os.path.join(PY_DIR, "resultats", f"fx_{datetime.now():%Y%m%d_%H%M%S}")
    os.makedirs(out_dir, exist_ok=True)
    for nom in ("fix", "annonce", "ronds", "combine"):
        res[nom].to_csv(os.path.join(out_dir, f"trades_{nom}.csv"), index=False)
    pr(f"Trades : {out_dir}")
    sortie = sortie or os.path.join(PY_DIR, "recherche", "resultats_fx.txt")
    with open(sortie, "w", encoding="utf-8") as fh:
        fh.write("\n".join(L) + "\n")
    log("\n".join(L))
    return res


# =============================================================================
#  Integration au runner
# =============================================================================
_RES: dict = {}


def _derniers_trades(nom: str) -> pd.DataFrame | None:
    """Trades ecrits par la derniere etude (resultats/fx_*), pour ne pas tout recalculer dans chaque processus du runner."""
    import glob
    f = sorted(glob.glob(os.path.join(PY_DIR, "resultats", "fx_*", f"trades_{nom}.csv")))
    if not f:
        return None
    t = pd.read_csv(f[-1])
    for c in ("entry_time", "exit_time", "jour"):
        if c in t.columns:
            t[c] = pd.to_datetime(t[c])
    return t


def run_spec(spec: dict) -> tuple[dict, pd.DataFrame]:
    t = _derniers_trades(spec["strategie"])
    if t is None:
        if not _RES:
            _RES.update(strategies(log=lambda *a, **k: None))
        t = _RES[spec["strategie"]].copy()
    jours = pd.bdate_range("2016-01-04", "2026-08-28")
    if t.empty:
        eq = pd.Series(25000.0, index=jours)
        pnl = np.array([])
    else:
        d = t.groupby(t["exit_time"].dt.normalize())["pnl"].sum().reindex(jours, fill_value=0.0)
        eq = 25000.0 + d.cumsum()
        if spec["strategie"] in ("annonce", "ronds", "combine"):
            eq = eq[eq.index >= pd.Timestamp(f"{DEBUT_OOS}-01-01")]
        pnl = t["pnl"].to_numpy()
    dd = eq.diff().dropna()
    wins, losses = pnl[pnl > 0].sum() if pnl.size else 0.0, -pnl[pnl < 0].sum() if pnl.size else 0.0
    s = dict(trades=len(pnl), win_rate=float((pnl > 0).mean()) if pnl.size else math.nan, net=float(pnl.sum()) if pnl.size else 0.0,
             profit_factor=float(wins / losses) if losses > 0 else math.nan, avg_trade=float(pnl.mean()) if pnl.size else math.nan,
             sharpe=float(dd.mean() / dd.std() * math.sqrt(252)) if dd.std() > 0 else math.nan,
             max_dd=float((eq.cummax() - eq).max()), start=eq.index[0], end=eq.index[-1], capital=25000.0,
             t_stat=float(pnl.mean() / (pnl.std(ddof=1) / math.sqrt(pnl.size))) if pnl.size > 2 and pnl.std(ddof=1) > 0 else math.nan,
             equity=eq, data="6E 6B 6J 6A 1 min -> micros, 1R = 250 $")
    return s, t


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--sortie", default=None)
    a = ap.parse_args(argv)
    etude(a.sortie)


if __name__ == "__main__":
    main()
