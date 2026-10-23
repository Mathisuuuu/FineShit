"""Or (futures COMEX GC) : 10 strategies intraday fondees sur des anomalies documentees (fiche du 9 octobre 2026).

    python -m nexus.perso.or_anomalies [--sortie resultats_or.txt]

Ordre de travail de la fiche, suivi a la lettre :
  1. mesurer l EFFET BRUT de chaque anomalie, sans execution ni couts, annee par annee, contre sa fenetre temoin ;
  2. ne garder que celles dont le signe est stable sur les 3 dernieres annees et dont le t total depasse le seuil
     (3 plutot que 2 : tests multiples, Harvey, Liu & Zhu 2016) ;
  3. coder les regles de trading avec les couts ; les parametres sont ceux de la fiche, FIGES (aucune optimisation :
     c est un test hors echantillon des regles telles qu elles ont ete ecrites).
Donnees : GC et ES 1 minute (Databento, 2016-2026). Indisponible ici : rendement a 2 ans (strategie 4 : substitut =
mouvement du panier dollar 6E / 6B / 6J / 6A), consensus et dispersion des previsions (strategie 5 : non testable,
seule la derive brute apres les annonces est mesuree), calendrier du PCE et des annonces europeennes (filtres omis),
nombre de tours des encheres LBMA (filtre omis), sessions GLD (horaires de l ETF reproduits sur le future).
Execution : micro MGC (10 onces, tick 0,10 $ = 1 $), 1R = 250 $ (0,5 % d un compte de 50 000 $), taille = plancher(R /
risque du stop) ; glissement 1 tick (3 ticks autour du FOMC), commission 0,60 $ par cote ; stress a 3 ticks (0,30 $/once,
le spread courant de la fiche). sigma = ecart-type robuste (1,4826 x ecart absolu median) de la meme fenetre sur 60 jours.
"""
from __future__ import annotations

import argparse
import math
import os
from datetime import datetime

import numpy as np
import pandas as pd

from .fx_trois import FX, FxMarche, evenements, executer, fx
from .orderflow import FOMC, _fmt_stats, stats_r
from .qf import QUOTES

PY_DIR = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", ".."))
NS_MIN = 60_000_000_000
NS_JOUR = 86_400_000_000_000
FRAICHEUR = 10                     # minutes : dernier prix connu a l heure voulue, au plus 10 min d anciennete
JOURS_SIGMA = 60
SEUIL_T = 3.0                      # t total minimal pour retenir une anomalie (tests multiples)
FICHIER_ZT = os.path.join(QUOTES, "taux", "ZT_v0_1m.parquet")   # future 2 ans CBOT (Databento), facultatif
DURATION_ZT = 1.9                  # duration modifiee approchee du ZT : variation de taux = -variation de prix / duration
SEUIL_2ANS_PB = 4.0                # fiche : baisse du 2 ans de plus de 4 pb = surprise accommodante
ANNEES_RECENTES = (2024, 2025, 2026)


# =============================================================================
#  Outils
# =============================================================================
def gc() -> FxMarche:
    return fx("GC")


def instants(jours: pd.DatetimeIndex, hh: int, mm: int, tz: str) -> np.ndarray:
    """Heure locale (tz) de chaque jour -> instants UTC naifs en ns."""
    loc = pd.DatetimeIndex(jours) + pd.Timedelta(hours=hh, minutes=mm)
    utc = loc.tz_localize(tz, nonexistent="shift_forward", ambiguous=False).tz_convert("UTC").tz_localize(None)
    return pd.DatetimeIndex(utc).as_unit("ns").asi8


def asof(m: FxMarche, cibles: np.ndarray, fraicheur: int = FRAICHEUR) -> np.ndarray:
    """Indice du dernier prix connu a chaque instant (barre finissant au plus tard a l instant, au plus `fraicheur` min
    plus tot), -1 sinon."""
    k = np.clip(np.searchsorted(m.t, cibles, side="right") - 1, 0, m.n - 1)
    return np.where((m.t[k] <= cibles) & (m.t[k] > cibles - fraicheur * NS_MIN), k, -1)


def jours_ouvres(m: FxMarche) -> pd.DatetimeIndex:
    j = pd.to_datetime(np.unique(m.jour) * NS_JOUR)
    return j[j.dayofweek < 5]


def sigma_robuste(x: pd.Series, n: int = JOURS_SIGMA) -> pd.Series:
    """1,4826 x ecart absolu median sur les n observations PRECEDENTES (jours manquants ignores)."""
    return x.rolling(n, min_periods=n // 2).apply(lambda v: 1.4826 * np.nanmedian(np.abs(v - np.nanmedian(v))), raw=True).shift(1)


def sigma_glissant(m: FxMarche, minutes: int, jours: int = JOURS_SIGMA) -> np.ndarray:
    """sigma robuste du rendement sur `minutes`, estime sur les `jours` precedents (echantillon toutes les `minutes`),
    porte sur chaque minute : aucune donnee posterieure a la decision."""
    pts = np.arange(0, m.n - minutes, minutes)
    r = pd.Series(np.log(m.c[pts + minutes] / m.c[pts]))
    par_jour = max(1, int(round(23 * 60 / minutes)))
    s = sigma_robuste(r, jours * par_jour).to_numpy()
    k = np.searchsorted(pts + minutes, np.arange(m.n), side="right") - 1      # dernier rendement termine
    return np.where(k >= 0, s[np.clip(k, 0, None)], np.nan)


def lr(m: FxMarche, a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """log(prix b / prix a), NaN si un indice manque."""
    ok = (a >= 0) & (b >= 0)
    out = np.full(len(a), np.nan)
    out[ok] = np.log(m.c[b[ok]] / m.c[a[ok]])
    return out


def t_stat(x) -> float:
    x = pd.Series(x).dropna()
    return float(x.mean() / (x.std(ddof=1) / math.sqrt(len(x)))) if len(x) > 2 and x.std(ddof=1) > 0 else math.nan


def jours_annonces(types=("NFP", "CPI")) -> set:
    ev = evenements()
    return set(ev.loc[ev["evenement"].isin(types), "date"].dt.normalize())


def jours_fomc() -> set:
    return set(pd.DatetimeIndex(FOMC))


def bilan_annuel(serie: pd.Series) -> dict:
    """Moyenne (pb) et t par annee + t total, signe des 3 dernieres annees et verdict selon les criteres de la fiche."""
    s = serie.dropna() * 1e4
    par_an = {int(a): (g.mean(), t_stat(g), len(g)) for a, g in s.groupby(s.index.year)}
    t_tot = t_stat(s)
    signe = np.sign(s.mean()) if len(s) else 0
    stable = all(a in par_an and np.sign(par_an[a][0]) == signe for a in ANNEES_RECENTES if a in par_an) and \
        sum(a in par_an for a in ANNEES_RECENTES) >= 2
    verdict = ("RETENUE" if abs(t_tot) >= SEUIL_T and stable else
               "a confirmer (t >= 2 mais < 3, ou signe instable)" if abs(t_tot) >= 2 else "rejetee (t < 2)")
    return dict(moyenne=s.mean(), t=t_tot, n=len(s), par_an=par_an, stable=stable, verdict=verdict)


def _txt_annees(b: dict) -> str:
    return " | ".join(f"{a} {v[0]:+.1f} ({v[1]:+.1f})" for a, v in b["par_an"].items())


# =============================================================================
#  Fenetres journalieres (une ligne par jour ouvre ET)
# =============================================================================
def grille(m: FxMarche, heures: dict) -> pd.DataFrame:
    """heures : {nom: (hh, mm, fuseau)} -> indices as-of par jour."""
    jours = jours_ouvres(m)
    return pd.DataFrame({k: asof(m, instants(jours, h, mi, tz)) for k, (h, mi, tz) in heures.items()}, index=jours)


# =============================================================================
#  EFFETS BRUTS (sans execution ni couts)
# =============================================================================
def brut_1_nuit_jour(m: FxMarche) -> dict:
    """1. Rendement de 08:20 a 10:20 ET selon le rendement de la nuit (cloture COMEX 13:30 ET de la veille -> 08:20)."""
    g = grille(m, {"c1330": (13, 30, "America/New_York"), "o0820": (8, 20, "America/New_York"), "f1020": (10, 20, "America/New_York")})
    prev = g["c1330"].shift(1).fillna(-1).astype(np.int64).to_numpy()
    nuit = pd.Series(lr(m, prev, g["o0820"].to_numpy()), index=g.index)
    jour = pd.Series(lr(m, g["o0820"].to_numpy(), g["f1020"].to_numpy()), index=g.index)
    sig = sigma_robuste(nuit)
    ann = pd.Index(g.index.normalize()).isin(jours_annonces(("NFP", "CPI", "PCE")))          # filtre de la fiche
    haute = (nuit > 0.5 * sig) & ~ann
    return dict(nuit=bilan_annuel(nuit), jour=bilan_annuel(jour), jour_si_nuit_haute=bilan_annuel(jour[haute]),
                jour_autres=bilan_annuel(jour[~haute & ~ann & nuit.notna()]),
                ecart=bilan_annuel(jour[haute] - jour[~haute & ~ann & nuit.notna()].mean()), g=g, nuit_s=nuit, jour_s=jour,
                sig=sig, annonces=ann)


def brut_2_demi_heures(m: FxMarche) -> dict:
    """2. Signal cloture de la veille (16:00 ET) -> 10:00 ET ; cible 15:30 -> 16:00 ET. Rendement signe (signe du signal x
    rendement de la derniere demi-heure) et pente de regression, par annee."""
    g = grille(m, {"c1600": (16, 0, "America/New_York"), "s1000": (10, 0, "America/New_York"), "e1530": (15, 30, "America/New_York")})
    prev = g["c1600"].shift(1).fillna(-1).astype(np.int64).to_numpy()
    sig = pd.Series(lr(m, prev, g["s1000"].to_numpy()), index=g.index)
    fin = pd.Series(lr(m, g["e1530"].to_numpy(), g["c1600"].to_numpy()), index=g.index)
    sg = sigma_robuste(sig)
    fort = sig.abs() > 0.5 * sg
    signe = np.sign(sig) * fin
    d = pd.concat([sig, fin], axis=1).dropna()
    pente = {int(a): np.polyfit(x.iloc[:, 0], x.iloc[:, 1], 1)[0] for a, x in d.groupby(d.index.year) if len(x) > 20}
    return dict(signe=bilan_annuel(signe[fort]), pente=pente, g=g, sig=sig, fin=fin, sig_sigma=sg, fin_sigma=sigma_robuste(fin))


def panier_dollar(jours: pd.DatetimeIndex, a: tuple, b: tuple) -> pd.Series:
    """Rendement du dollar contre 6E / 6B / 6J / 6A (moyenne, = - rendement moyen des futures) entre deux heures ET."""
    mv = []
    for r in FX:
        mm = fx(r)
        ia, ib = asof(mm, instants(jours, *a, "America/New_York"), 3), asof(mm, instants(jours, *b, "America/New_York"), 3)
        mv.append(-lr(mm, ia, ib))
    return pd.Series(np.nanmean(np.vstack(mv), axis=0), index=jours)


def variation_2ans(jours: pd.DatetimeIndex) -> pd.Series | None:
    """Variation du rendement a 2 ans (pb) entre 13:59 et 14:05 ET, tiree du future ZT (prix reel, dernier prix connu a
    3 min pres) : -variation de prix / duration. None si le fichier ZT n est pas dans Cotations/taux."""
    if not os.path.exists(FICHIER_ZT):
        return None
    raw = pd.read_parquet(FICHIER_ZT)
    if raw.index.tz is not None:
        raw.index = raw.index.tz_convert("UTC").tz_localize(None)
    raw = raw.sort_index()
    t = pd.DatetimeIndex(raw.index + pd.Timedelta(minutes=1)).as_unit("ns").asi8      # heure de fin de barre
    c = raw["close"].to_numpy(float)

    class _Z:
        pass
    z = _Z()
    z.t, z.n, z.c = t, len(t), c
    a, b = asof(z, instants(jours, 13, 59, "America/New_York"), 3), asof(z, instants(jours, 14, 5, "America/New_York"), 3)
    dp = lr(z, a, b)
    return pd.Series(-dp * 1e4 / DURATION_ZT, index=jours)


def brut_4_fomc(m: FxMarche) -> dict:
    """4. Jours de FOMC (communique 14:00 ET) : surprise mesuree par le rendement a 2 ans (future ZT) entre 13:59 et 14:05
    s il est disponible (baisse > 4 pb = accommodante, fiche), sinon approchee par le dollar (z < -1) ; derive de l or
    14:05 -> 14:28 et 14:05 -> 15:05."""
    jours = pd.DatetimeIndex(sorted(jours_fomc()))
    jours = jours[(jours >= m.idx[0]) & (jours <= m.idx[-1])]
    usd = panier_dollar(jours, (13, 59), (14, 5))
    z = usd / usd.expanding(min_periods=8).std().shift(1)
    dy = variation_2ans(jours)
    i5, i28, i65 = (asof(m, instants(jours, 14, mi, "America/New_York"), 3) for mi in (5, 28, 65))
    d = pd.DataFrame({"usd_pb": usd * 1e4, "z": z, "or_1428": lr(m, i5, i28) * 1e4, "or_1505": lr(m, i5, i65) * 1e4}, index=jours)
    if dy is not None:
        d["dy_2ans_pb"] = dy
        d["accommodant"], d["restrictif"] = dy < -SEUIL_2ANS_PB, dy > SEUIL_2ANS_PB
        source = "rendement a 2 ans (future ZT), seuil 4 pb"
    else:
        d["accommodant"], d["restrictif"] = d["z"] < -1, d["z"] > 1
        source = "SUBSTITUT : dollar contre 6E / 6B / 6J / 6A (z < -1), le future ZT n est pas dans Cotations/taux"
    return dict(d=d, accommodant=d[d["accommodant"]], restrictif=d[d["restrictif"]], source=source)


def brut_5_annonces(m: FxMarche) -> dict:
    """5. (non testable sans consensus ni dispersion) Derive 08:32 -> 09:30 ET dans le sens des 2 premieres minutes, jours
    de NFP et CPI."""
    jours = pd.DatetimeIndex(sorted(jours_annonces(("NFP", "CPI", "PCE", "VENTES"))))     # annonces de la fiche
    i30, i32, i930 = (asof(m, instants(jours, 8, mi, "America/New_York"), 2) for mi in (30, 32, 90))
    deux = lr(m, i30, i32)
    derive = lr(m, i32, i930)
    return dict(signe=bilan_annuel(pd.Series(np.sign(deux) * derive, index=jours)))


def brut_fenetre_londres(m: FxMarche, debut: tuple, fin: tuple, temoins: list) -> dict:
    """6 / 7. Fenetre heure de Londres comparee a des fenetres temoins de meme duree."""
    def serie(a, b):
        g = grille(m, {"a": (*a, "Europe/London"), "b": (*b, "Europe/London")})
        return pd.Series(lr(m, g["a"].to_numpy(), g["b"].to_numpy()), index=g.index)
    f = serie(debut, fin)
    tem = pd.concat([serie(a, b) for a, b in temoins], axis=1).mean(axis=1)
    return dict(fenetre=bilan_annuel(f), temoin=bilan_annuel(tem), ecart=bilan_annuel(f - tem), serie=f)


def brut_9_refuge(m: FxMarche) -> dict:
    """9. Chute de l ES de plus de 4 sigma en 5 minutes (sigma du meme creneau, 60 seances) -> rendement de l or sur les
    60 minutes suivantes ; hors fenetre du communique FOMC."""
    es = fx("ES")
    b = es.b5
    sig, _ = es.creneau(60)
    with np.errstate(divide="ignore", invalid="ignore"):
        z = b["r"] / sig
    ok = np.isfinite(z) & (z < -4) & (b["pos1"] >= 0)
    t5 = b["t"][ok]
    jours_f = jours_fomc()
    ts = pd.DatetimeIndex(t5).tz_localize("UTC").tz_convert("America/New_York").tz_localize(None)
    hors_fed = ~(pd.Index(ts.normalize()).isin(jours_f) & (ts.hour >= 14) & (ts.hour < 15))
    t5, ts = t5[hors_fed], ts[hors_fed]
    i0, i1 = asof(m, t5, 5), asof(m, t5 + 60 * NS_MIN, 5)
    r = pd.Series(lr(m, i0, i1), index=ts)
    return dict(serie=r, total=bilan_annuel(r), avant=bilan_annuel(r[r.index < "2019-01-01"]),
                apres=bilan_annuel(r[r.index >= "2019-01-01"]), instants=t5)


def _niveaux_events(m: FxMarche, pas: float, decalage: float) -> pd.DataFrame:
    """8. Premiers contacts d un niveau (pas x k + decalage) dans la journee ET, sur barres 5 min du prix REEL ;
    ralentissement = amplitude < moyenne du creneau sur 20 jours. Rendement 60 min apres, signe pour un rebond."""
    raw = pd.DataFrame({"high": m.rh, "low": m.rl, "close": m.rc}, index=m.idx).dropna()
    rs = raw.resample("5min", label="right", closed="right")
    b = pd.DataFrame({"high": rs["high"].max(), "low": rs["low"].min(), "close": rs["close"].last()}).dropna()
    t5 = pd.DatetimeIndex(b.index).as_unit("ns").asi8
    et = pd.DatetimeIndex(b.index).tz_localize("UTC").tz_convert("America/New_York").tz_localize(None)
    jour = et.normalize()
    h, l, c = (b[k].to_numpy(float) for k in ("high", "low", "close"))
    lv = np.floor((c - decalage) / pas) * pas + decalage                     # niveau juste sous la cloture
    rng = h - l
    slot = et.hour * 60 + et.minute
    pv = pd.DataFrame({"j": jour, "s": slot, "r": rng}).pivot_table(index="j", columns="s", values="r")
    moy = pv.rolling(20, min_periods=10).mean().shift(1)
    moyr = moy.to_numpy()[pv.index.get_indexer(jour), pv.columns.get_indexer(slot)]
    rows, vus = [], set()
    for k in range(1, len(c)):
        for L in (lv[k - 1], lv[k - 1] + pas):                              # niveaux autour de la cloture precedente
            if not (l[k] <= L <= h[k]):
                continue
            cle = (jour[k], round(L, 2))
            if cle in vus:
                continue
            vus.add(cle)
            approche = 1 if c[k - 1] < L else -1
            rows.append((t5[k], approche, L, c[k], rng[k] < moyr[k] if np.isfinite(moyr[k]) else False))
    ev = pd.DataFrame(rows, columns=["t", "approche", "niveau", "close", "ralenti"])
    i0, i1 = asof(m, ev["t"].to_numpy(), 5), asof(m, ev["t"].to_numpy() + 60 * NS_MIN, 5)
    ev["rebond"] = -ev["approche"] * lr(m, i0, i1)                         # > 0 si le cours repart a l oppose du niveau
    ev.index = pd.DatetimeIndex(ev["t"].to_numpy())
    return ev


def brut_8_barrieres(m: FxMarche, pas: float = 100.0) -> dict:
    rond = _niveaux_events(m, pas, 0.0)
    hasard = _niveaux_events(m, pas, 37.0)
    r_rond, r_has = rond.loc[rond["ralenti"], "rebond"], hasard.loc[hasard["ralenti"], "rebond"]
    diff = r_rond.mean() - r_has.mean()
    se = math.sqrt(r_rond.var() / len(r_rond) + r_has.var() / len(r_has)) if len(r_rond) > 2 and len(r_has) > 2 else math.nan
    return dict(rond=bilan_annuel(r_rond), hasard=bilan_annuel(r_has), ecart_pb=diff * 1e4, t_ecart=diff / se if se else math.nan,
                n=(len(r_rond), len(r_has)))


def brut_3_retour(m: FxMarche) -> dict:
    """3. Mouvement de plus de 2 sigma en 15 minutes en seance US (08:30-16:00 ET), hors 30 min apres une annonce
    programmee ; rendement 60 min apres, signe pour un retournement ; faible volume contre fort volume."""
    ev = evenements_retour(m)
    rev = ev["retour60"]
    return dict(faible=bilan_annuel(rev[ev["faible_volume"]]), fort=bilan_annuel(rev[~ev["faible_volume"]]), ev=ev)


def barres15(m: FxMarche) -> pd.DataFrame:
    df = pd.DataFrame({"open": m.o, "high": m.h, "low": m.l, "close": m.c, "volume": m.v}, index=m.idx)
    r = df.resample("15min", label="right", closed="right")
    b = pd.DataFrame({"high": r["high"].max(), "low": r["low"].min(), "close": r["close"].last(), "volume": r["volume"].sum()}).dropna()
    b["t"] = pd.DatetimeIndex(b.index).as_unit("ns").asi8
    et = pd.DatetimeIndex(b.index).tz_localize("UTC").tz_convert("America/New_York").tz_localize(None)
    b["jour"], b["slot"] = et.normalize(), et.hour * 60 + et.minute
    b["r"] = np.log(b["close"] / b["close"].shift(1))
    b.loc[np.r_[True, np.diff(b["t"].to_numpy()) != 15 * NS_MIN], "r"] = np.nan
    return b


def evenements_retour(m: FxMarche) -> pd.DataFrame:
    b = barres15(m)
    us = b[(b["slot"] > 8 * 60 + 30) & (b["slot"] <= 16 * 60)].copy()
    pr = us.pivot_table(index="jour", columns="slot", values="r")
    pvol = us.pivot_table(index="jour", columns="slot", values="volume")
    sg = pr.apply(lambda col: sigma_robuste(col))
    vm = pvol.rolling(JOURS_SIGMA, min_periods=30).mean().shift(1)
    ri, ci = pr.index.get_indexer(us["jour"]), pr.columns.get_indexer(us["slot"])
    us["sigma"], us["vol_moy"] = sg.to_numpy()[ri, ci], vm.to_numpy()[ri, ci]
    ann, fed = jours_annonces(("NFP", "CPI", "PCE", "VENTES")), jours_fomc()
    apres_annonce = (us["jour"].isin(ann) & (us["slot"] > 8 * 60 + 30) & (us["slot"] <= 9 * 60)) | \
                    (us["jour"].isin(fed) & (us["slot"] > 14 * 60) & (us["slot"] <= 14 * 60 + 30))
    ev = us[(us["r"].abs() > 2 * us["sigma"]) & ~apres_annonce].copy()
    i0, i1 = asof(m, ev["t"].to_numpy(), 5), asof(m, ev["t"].to_numpy() + 60 * NS_MIN, 5)
    ev["retour60"] = -np.sign(ev["r"]) * lr(m, i0, i1)
    ev["faible_volume"] = ev["volume"] < ev["vol_moy"]
    ev.index = pd.DatetimeIndex(ev.index)
    return ev


# =============================================================================
#  REGLES DE TRADING (parametres de la fiche, figes)
# =============================================================================
def _dec(i: int, side: int, px: float, sigma_ret: float, k_stop: float, fin: int, part: float = 1.0, cible=np.nan):
    risque = px * k_stop * sigma_ret
    return (int(i), int(side), px - side * risque, cible, int(fin), risque, part)


def s1_ouverture(m, b1) -> list:
    g, nuit, sig, ann = b1["g"], b1["nuit_s"], b1["sig"], b1["annonces"]
    sd = sigma_robuste(b1["jour_s"])
    dec = []
    for k, d in enumerate(g.index):
        i, f = int(g["o0820"].iloc[k]), int(g["f1020"].iloc[k])
        if i < 0 or f <= i or ann[k] or not (nuit.iloc[k] > 0.5 * sig.iloc[k]) or not np.isfinite(sd.iloc[k]):
            continue
        dec.append(_dec(i, -1, m.c[i], sd.iloc[k], 1.5, f))
    return dec


def s2_momentum(m, b2, filtre=None, asym=None) -> list:
    g, sig, sg, fs = b2["g"], b2["sig"], b2["sig_sigma"], b2["fin_sigma"]
    dec = []
    for k, d in enumerate(g.index):
        i, f = int(g["e1530"].iloc[k]), int(g["c1600"].iloc[k])
        s = sig.iloc[k]
        if i < 0 or f <= i or not np.isfinite(s) or not abs(s) > 0.5 * sg.iloc[k] or not np.isfinite(fs.iloc[k]):
            continue
        if filtre is not None and not filtre.get(d, False):
            continue
        side = 1 if s > 0 else -1
        part = asym.get(d, 1.0) if (asym is not None and side < 0) else 1.0
        dec.append(_dec(i, side, m.c[i], fs.iloc[k], 1.5, f, part))
    return dec


def s3_retour(m, ev) -> list:
    dec = []
    vw_v, vw_pv = pd.Series(m.v).rolling(60).sum().to_numpy(), pd.Series(m.v * (m.h + m.l + m.c) / 3).rolling(60).sum().to_numpy()
    for t, r in zip(ev["t"].to_numpy(), ev.itertuples()):
        if not r.faible_volume or not np.isfinite(r.sigma):
            continue
        i = int(asof(m, np.array([t]), 2)[0])
        if i < 0:
            continue
        side = -1 if r.r > 0 else 1
        extreme = r.high if r.r > 0 else r.low                                   # extreme de la barre 15 min (prix ajuste)
        stop = extreme * (1 + r.sigma) if side < 0 else extreme * (1 - r.sigma)  # 1 sigma au-dela de l extreme
        vwap = vw_pv[i] / vw_v[i] if vw_v[i] > 0 else np.nan
        cible = vwap if np.isfinite(vwap) and (vwap - m.c[i]) * side > m.tick else np.nan
        risque = (m.c[i] - stop) * side
        if risque <= 0:
            continue
        dec.append((i, side, stop, cible, m.fin_apres(i + 1, 60), risque, 1.0))
    return dec


def s4_fomc(m, b4, fin_min: int = 28) -> list:
    d = b4["d"]
    hist = d[["or_1428", "or_1505"]] / 1e4
    sig = sigma_robuste(hist["or_1428" if fin_min == 28 else "or_1505"], 40)
    dec = []
    jours = d.index
    i5 = asof(m, instants(jours, 14, 5, "America/New_York"), 3)
    i_f = asof(m, instants(jours, 14, fin_min, "America/New_York"), 3)
    for k in range(len(d)):
        if not d["accommodant"].iloc[k] or i5[k] < 0 or i_f[k] <= i5[k] or not np.isfinite(sig.iloc[k]):
            continue
        dec.append(_dec(i5[k], 1, m.c[i5[k]], sig.iloc[k], 1.5, i_f[k]))
    return dec


def s_fenetre(m, debut: tuple, fin: tuple, side: int) -> list:
    g = grille(m, {"a": (*debut, "Europe/London"), "b": (*fin, "Europe/London")})
    a, b = g["a"].to_numpy(), g["b"].to_numpy()
    sig = sigma_robuste(pd.Series(lr(m, a, b), index=g.index)).to_numpy()
    return [_dec(a[k], side, m.c[a[k]], sig[k], 1.5, b[k]) for k in range(len(g)) if a[k] >= 0 and b[k] > a[k] and np.isfinite(sig[k])]


def s8_barrieres(m, pas: float = 100.0, decalage: float = 0.0) -> list:
    """Rebond au premier contact avec ralentissement (objectif 0,5 sigma) et cassure d une barre 15 min de plus de
    0,3 sigma (cascade) ; stop de l autre cote du niveau ; 2 h au plus. sigma = 2 h, robuste, 60 jours."""
    ev = _niveaux_events(m, pas, decalage)
    s2 = sigma_glissant(m, 120)
    dec = []
    for r in ev[ev["ralenti"]].itertuples():
        i = int(asof(m, np.array([r.t]), 2)[0])
        if i < 0 or not np.isfinite(s2[i]):
            continue
        side, s2h = -r.approche, s2[i]
        stop = r.niveau + m.offset[i] - side * 0.25 * s2h * r.niveau             # de l autre cote du niveau
        cible = m.c[i] + side * 0.5 * s2h * m.c[i]
        risque = (m.c[i] - stop) * side
        if risque > 0:
            dec.append((i, side, stop, cible, m.fin_apres(i + 1, 120), risque, 1.0))
    b = barres15(m)
    raw15 = pd.Series(m.rc, index=m.idx).resample("15min", label="right", closed="right").last().reindex(b.index)
    s15 = sigma_robuste(b["r"].fillna(0), 60 * 20).to_numpy()
    rc = raw15.to_numpy()
    prev = np.r_[np.nan, rc[:-1]]
    for k in range(1, len(b)):
        if not np.isfinite(rc[k]) or not np.isfinite(prev[k]) or not np.isfinite(s15[k]):
            continue
        L = math.floor((rc[k] - decalage) / pas) * pas + decalage
        for niv, sens in ((L, 1), (L + pas, -1)):
            casse = (prev[k] < niv and rc[k] > niv * (1 + 0.3 * s15[k])) if sens > 0 else \
                    (prev[k] > niv and rc[k] < niv * (1 - 0.3 * s15[k]))
            if not casse:
                continue
            i = int(asof(m, np.array([b["t"].iloc[k]]), 2)[0])
            if i < 0 or not np.isfinite(s2[i]):
                continue
            stop = niv + m.offset[i] - sens * 0.25 * s2[i] * niv
            risque = (m.c[i] - stop) * sens
            if risque > 0:
                dec.append((i, sens, stop, np.nan, m.fin_apres(i + 1, 120), risque, 1.0))
    return dec


def s9_refuge(m, b9) -> list:
    s60 = sigma_glissant(m, 60)
    dec = []
    for t in b9["instants"]:
        i = int(asof(m, np.array([t]), 3)[0])
        if i >= 0 and np.isfinite(s60[i]):
            dec.append(_dec(i, 1, m.c[i], s60[i], 1.5, m.fin_apres(i + 1, 60)))
    return dec


def jours_agites(m: FxMarche, b2) -> tuple[dict, dict]:
    """10. Jour agite : volatilite realisee 09:30 -> 10:00 ET dans les 20 % les plus hauts des 250 jours precedents, ou
    saut (rendement 1 min > 4 sigma robustes de la meme fenetre) avant 10:00. -> (agite par jour, taille cote vendeur)."""
    g = grille(m, {"a": (9, 30, "America/New_York"), "b": (10, 0, "America/New_York")})
    rv, saut = {}, {}
    r1 = np.r_[np.nan, np.diff(np.log(m.c))]
    for d, a, b in zip(g.index, g["a"].to_numpy(), g["b"].to_numpy()):
        if a < 0 or b <= a:
            continue
        x = r1[a + 1:b + 1]
        x = x[np.isfinite(x)]
        rv[d] = float(np.sum(x * x))
        saut[d] = x
    rv = pd.Series(rv)
    seuil = rv.rolling(250, min_periods=60).quantile(0.8).shift(1)
    absr = pd.Series({d: np.max(np.abs(x)) if len(x) else np.nan for d, x in saut.items()})
    sd1 = pd.Series({d: np.std(x) if len(x) > 2 else np.nan for d, x in saut.items()})
    sd_ref = sd1.rolling(JOURS_SIGMA, min_periods=30).median().shift(1)
    jump = absr > 4 * sd_ref
    agite = {d: bool((rv.get(d, np.nan) > seuil.get(d, np.nan)) or jump.get(d, False)) for d in rv.index}
    asym = {}
    for d, x in saut.items():
        if jump.get(d, False) and len(x):
            asym[d] = 1.5 if x[np.argmax(np.abs(x))] < 0 else 1.0
    return agite, asym


# =============================================================================
#  Etude
# =============================================================================
def etude(sortie: str | None = None, log=print) -> dict:
    t0 = datetime.now()
    m = gc()
    L = []
    pr = L.append
    pr("=" * 118)
    pr(" OR (futures COMEX GC) - 10 strategies intraday fondees sur des anomalies documentees - Databento 1 minute 2016-2026")
    pr("=" * 118)
    pr("Etape 1 : effet BRUT de chaque anomalie (points de base, t de Student), annee par annee. Criteres de la fiche :")
    pr(f"t total >= {SEUIL_T:g} (tests multiples) ET signe stable sur {ANNEES_RECENTES[0]}-{ANNEES_RECENTES[-1]} -> RETENUE.")
    pr("Etape 2 : regles de la fiche, parametres FIGES, micro MGC, 1R = 250 $, couts 1 tick (3 au FOMC) + 0,60 $ par cote.\n")
    res = {}

    log("[or] effets bruts")
    pr("=== ETAPE 1 : EFFETS BRUTS ===")
    b1 = brut_1_nuit_jour(m)
    res["b1"] = b1
    pr("1. Ouverture US surevaluee (fenetre 08:20 -> 10:20 ET)")
    pr(f"   rendement de la nuit (13:30 -> 08:20 ET) : {b1['nuit']['moyenne']:+.2f} pb (t {b1['nuit']['t']:+.1f}) ; "
       f"fenetre de jour : {b1['jour']['moyenne']:+.2f} pb (t {b1['jour']['t']:+.1f})")
    pr(f"   fenetre de jour apres une nuit > +0,5 sigma : {b1['jour_si_nuit_haute']['moyenne']:+.2f} pb (t {b1['jour_si_nuit_haute']['t']:+.1f},"
       f" {b1['jour_si_nuit_haute']['n']} j) ; autres jours : {b1['jour_autres']['moyenne']:+.2f} pb (t {b1['jour_autres']['t']:+.1f})")
    pr(f"   par annee (apres une nuit haute) : {_txt_annees(b1['jour_si_nuit_haute'])}")
    pr(f"   -> le signe attendu est NEGATIF ; verdict : {b1['jour_si_nuit_haute']['verdict']}" +
       (" (mais signe positif : anomalie absente)" if b1['jour_si_nuit_haute']['moyenne'] > 0 else ""))

    b2 = brut_2_demi_heures(m)
    res["b2"] = b2
    pr("2. Momentum : cloture de la veille -> 10:00 ET predit 15:30 -> 16:00 ET (|signal| > 0,5 sigma)")
    pr(f"   rendement signe de la derniere demi-heure : {b2['signe']['moyenne']:+.2f} pb (t {b2['signe']['t']:+.1f}, {b2['signe']['n']} j)")
    pr(f"   par annee : {_txt_annees(b2['signe'])}")
    pr("   pente de regression par annee : " + " | ".join(f"{a} {v:+.3f}" for a, v in b2["pente"].items()))
    pr(f"   verdict : {b2['signe']['verdict']}")

    b3 = brut_3_retour(m)
    res["b3"] = b3
    pr("3. Retour apres un mouvement > 2 sigma en 15 min (seance US, hors annonces) ; rendement 60 min dans le sens du retour")
    pr(f"   faible volume : {b3['faible']['moyenne']:+.2f} pb (t {b3['faible']['t']:+.1f}, {b3['faible']['n']}) ; fort volume : "
       f"{b3['fort']['moyenne']:+.2f} pb (t {b3['fort']['t']:+.1f}, {b3['fort']['n']})")
    pr(f"   par annee (faible volume) : {_txt_annees(b3['faible'])}")
    pr(f"   verdict (faible volume) : {b3['faible']['verdict']}")

    b4 = brut_4_fomc(m)
    res["b4"] = b4
    acc, rst = b4["accommodant"], b4["restrictif"]
    pr(f"4. FOMC : surprise entre 13:59 et 14:05 ET mesuree par : {b4['source']}")
    pr(f"   {len(b4['d'])} reunions ; accommodantes : {len(acc)} ; or 14:05 -> 14:28 : {acc['or_1428'].mean():+.1f} pb (t {t_stat(acc['or_1428']):+.1f}, "
       f"positif {int((acc['or_1428'] > 0).sum())}/{len(acc)}) ; -> 15:05 : {acc['or_1505'].mean():+.1f} pb (t {t_stat(acc['or_1505']):+.1f})")
    pr(f"   restrictives : {len(rst)} ; or 14:05 -> 14:28 : {rst['or_1428'].mean():+.1f} pb (t {t_stat(rst['or_1428']):+.1f})")
    pr("   verdict : echantillon trop petit pour un t de 3 ; regularite du signe donnee ci-dessus")
    if "dy_2ans_pb" in b4["d"]:
        pr(f"   (pour comparaison, le substitut dollar aurait retenu {int((b4['d']['z'] < -1).sum())} reunions accommodantes ; "
           f"accord avec le 2 ans : {int(((b4['d']['z'] < -1) & b4['d']['accommodant']).sum())})")

    b5 = brut_5_annonces(m)
    pr("5. Chiffres de 08:30 en desaccord : NON TESTABLE (consensus et dispersion des previsions absents). Pour memoire, derive")
    pr(f"   08:32 -> 09:30 dans le sens des 2 premieres minutes (NFP, CPI, PCE, ventes au detail ; toutes dispersions) : "
       f"{b5['signe']['moyenne']:+.2f} pb "
       f"(t {b5['signe']['t']:+.1f}, {b5['signe']['n']} annonces)")

    b6 = brut_fenetre_londres(m, (9, 30), (10, 30), [((8, 30), (9, 30)), ((10, 30), (11, 30))])
    res["b6"] = b6
    pr("6. Avant le fixing du matin : 09:30 -> 10:30 Londres contre 08:30 -> 09:30 et 10:30 -> 11:30 (signe attendu negatif)")
    pr(f"   fenetre {b6['fenetre']['moyenne']:+.2f} pb (t {b6['fenetre']['t']:+.1f}) ; temoins {b6['temoin']['moyenne']:+.2f} pb ; "
       f"ecart {b6['ecart']['moyenne']:+.2f} pb (t {b6['ecart']['t']:+.1f})")
    pr(f"   ecart par annee : {_txt_annees(b6['ecart'])} ; verdict (ecart) : {b6['ecart']['verdict']}")

    b7 = brut_fenetre_londres(m, (15, 5), (16, 35), [((16, 5), (17, 35))])
    res["b7"] = b7
    pr("7. Apres le fixing de l apres-midi : 15:05 -> 16:35 Londres contre la meme fenetre decalee d une heure (signe attendu +)")
    pr(f"   fenetre {b7['fenetre']['moyenne']:+.2f} pb (t {b7['fenetre']['t']:+.1f}) ; temoin {b7['temoin']['moyenne']:+.2f} pb ; "
       f"ecart {b7['ecart']['moyenne']:+.2f} pb (t {b7['ecart']['t']:+.1f})")
    pr(f"   ecart par annee : {_txt_annees(b7['ecart'])} ; verdict (ecart) : {b7['ecart']['verdict']}")

    log("[or] chiffres ronds")
    b8 = brut_8_barrieres(m, 100.0)
    b8b = brut_8_barrieres(m, 50.0)
    res["b8"] = b8
    pr("8. Barrieres des chiffres ronds : premier contact du jour avec ralentissement, rendement 60 min dans le sens du rebond")
    for nom, b in (("multiples de 100 $", b8), ("multiples de 50 $ (variante)", b8b)):
        pr(f"   {nom} : niveaux ronds {b['rond']['moyenne']:+.2f} pb ({b['n'][0]} contacts) ; niveaux au hasard (+37 $) "
           f"{b['hasard']['moyenne']:+.2f} pb ({b['n'][1]}) ; ecart {b['ecart_pb']:+.2f} pb (t {b['t_ecart']:+.1f})")
    pr("   verdict : effet barriere seulement si les niveaux ronds font nettement mieux que les niveaux au hasard")

    log("[or] refuge")
    b9 = brut_9_refuge(m)
    res["b9"] = b9
    pr("9. Fuite vers l or : ES < -4 sigma en 5 min -> or sur 60 min (signe attendu +)")
    pr(f"   2016-2026 : {b9['total']['moyenne']:+.2f} pb (t {b9['total']['t']:+.1f}, {b9['total']['n']} chocs) ; 2016-2018 : "
       f"{b9['avant']['moyenne']:+.2f} pb (t {b9['avant']['t']:+.1f}, {b9['avant']['n']}) ; 2019-2026 : {b9['apres']['moyenne']:+.2f} pb "
       f"(t {b9['apres']['t']:+.1f}, {b9['apres']['n']})")
    pr(f"   par annee : {_txt_annees(b9['total'])} ; verdict : {b9['total']['verdict']}")

    agite, asym = jours_agites(m, b2)
    sig2 = (np.sign(b2["sig"]) * b2["fin"])[(b2["sig"].abs() > 0.5 * b2["sig_sigma"])]
    ag = sig2[[agite.get(d, False) for d in sig2.index]]
    ca = sig2[[not agite.get(d, False) for d in sig2.index]]
    b10a, b10c = bilan_annuel(ag), bilan_annuel(ca)
    pr("10. Momentum des jours agites : strategie 2 separee entre jours agites et calmes")
    pr(f"   jours agites : {b10a['moyenne']:+.2f} pb (t {b10a['t']:+.1f}, {b10a['n']} j) ; jours calmes : {b10c['moyenne']:+.2f} pb "
       f"(t {b10c['t']:+.1f}, {b10c['n']} j) ; verdict (agites) : {b10a['verdict']}")

    # --- etape 2 : regles de trading -------------------------------------------------------------------------------
    log("[or] regles de trading")
    pr("\n=== ETAPE 2 : REGLES DE TRADING (parametres de la fiche, micro MGC) ===")
    strat = {
        "1 Ouverture US surevaluee": (s1_ouverture(m, b1), 1),
        "2 Momentum premiere demi-heure": (s2_momentum(m, b2), 1),
        "3 Retour apres exces non informe": (s3_retour(m, b3["ev"]), 1),
        "4 Fed accommodante (sortie 14:28)": (s4_fomc(m, b4, 28), 3),
        "4 variante sortie 15:05": (s4_fomc(m, b4, 65), 3),
        "6 Avant le fixing du matin": (s_fenetre(m, (9, 30), (10, 30), -1), 1),
        "7 Apres le fixing de l apres-midi": (s_fenetre(m, (15, 5), (16, 35), 1), 1),
        "8 Barrieres des chiffres ronds (100 $)": (s8_barrieres(m, 100.0), 1),
        "8 temoin : niveaux au hasard (+37 $)": (s8_barrieres(m, 100.0, 37.0), 1),
        "9 Fuite vers l or": (s9_refuge(m, b9), 1),
        "10 Momentum des jours agites": (s2_momentum(m, b2, filtre=agite, asym=asym), 1),
    }
    n_essais = len(strat)
    trades = {}
    for nom, (dec, gl) in strat.items():
        t = executer(m, nom, dec, gl, gl)
        ts = executer(m, nom, dec, gl + 2, gl + 2)
        tb = executer(m, nom, dec, gl, gl, frais=False)
        trades[nom] = t
        pr(_fmt_stats(nom, stats_r(t, n_essais)))
        sb, ss = stats_r(tb), stats_r(ts)
        pr(f"      sans couts : {sb.get('esperance', math.nan):+.3f}R | stress 0,30 $/once : {ss.get('esperance', math.nan):+.3f}R | "
           f"persistance : " + (" | ".join(f"{y} {v:+.1f}R" for y, v in t.groupby(t['entry_time'].dt.year)['r'].sum().items()) if len(t) else "-"))
        if len(t) >= 50:
            dern = t.sort_values("exit_time").tail(50)["r"].mean()
            pr(f"      critere d abandon de la fiche : gain moyen des 50 derniers trades {dern:+.3f}R -> "
               + ("ARRET" if dern < 0 else "continuer"))
    res["trades"] = trades
    pr("\nRappels de la fiche : les strategies 2 et 10 partagent la fenetre 15:30 -> 16:00 ET et ne s additionnent pas ;")
    pr("le marche haussier 2024-2026 penalise les strategies vendeuses (1, 6) meme si l anomalie existe : voir les temoins.")
    pr(f"\nCalcul en {(datetime.now() - t0).total_seconds():.0f} s.")
    out_dir = os.path.join(PY_DIR, "resultats", f"or_{datetime.now():%Y%m%d_%H%M%S}")
    os.makedirs(out_dir, exist_ok=True)
    for nom, t in trades.items():
        t.to_csv(os.path.join(out_dir, f"trades_{slug(nom)}.csv"), index=False)
    pr(f"Trades : {out_dir}")
    sortie = sortie or os.path.join(PY_DIR, "recherche", "resultats_or.txt")
    with open(sortie, "w", encoding="utf-8") as fh:
        fh.write("\n".join(L) + "\n")
    log("\n".join(L))
    return res


def slug(nom: str) -> str:
    return "".join(ch if ch.isalnum() else "_" for ch in nom)[:50]


def run_spec(spec: dict) -> tuple[dict, pd.DataFrame]:
    """Runner : relit les trades de la derniere etude (resultats/or_*) ; lance l etude si aucune n existe."""
    import glob
    f = sorted(glob.glob(os.path.join(PY_DIR, "resultats", "or_*", f"trades_{slug(spec['strategie'])}.csv")))
    if f:
        t = pd.read_csv(f[-1])
        for c in ("entry_time", "exit_time", "jour"):
            if c in t.columns:
                t[c] = pd.to_datetime(t[c])
    else:
        t = etude(log=lambda *a, **k: None)["trades"][spec["strategie"]]
    jours = pd.bdate_range("2016-01-04", "2026-08-28")
    if t.empty:
        eq, pnl = pd.Series(50000.0, index=jours), np.array([])
    else:
        d = t.groupby(t["exit_time"].dt.normalize())["pnl"].sum().reindex(jours, fill_value=0.0)
        eq, pnl = 50000.0 + d.cumsum(), t["pnl"].to_numpy()
    dd = eq.diff().dropna()
    wins, losses = pnl[pnl > 0].sum() if pnl.size else 0.0, -pnl[pnl < 0].sum() if pnl.size else 0.0
    s = dict(trades=len(pnl), win_rate=float((pnl > 0).mean()) if pnl.size else math.nan, net=float(pnl.sum()) if pnl.size else 0.0,
             profit_factor=float(wins / losses) if losses > 0 else math.nan, avg_trade=float(pnl.mean()) if pnl.size else math.nan,
             sharpe=float(dd.mean() / dd.std() * math.sqrt(252)) if dd.std() > 0 else math.nan,
             max_dd=float((eq.cummax() - eq).max()), start=eq.index[0], end=eq.index[-1], capital=50000.0,
             t_stat=float(pnl.mean() / (pnl.std(ddof=1) / math.sqrt(pnl.size))) if pnl.size > 2 and pnl.std(ddof=1) > 0 else math.nan,
             equity=eq, data="GC 1 min -> MGC, 1R = 250 $")
    return s, t


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--sortie", default=None)
    a = ap.parse_args(argv)
    etude(a.sortie)


if __name__ == "__main__":
    main()
