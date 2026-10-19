"""Fiches du fil ES/NQ « 6 mois de simulation » : order flow et retour a la moyenne, sur barres 1 minute Databento.

    python -m nexus.perso.orderflow [--sortie resultats_orderflow.txt]

Donnees disponibles : OHLCV 1 minute (Cotations), sans ticks, sans cote agresseur ni carnet. Consequences :
  - Fiche 1 (choc de prix et de volume) : testee telle que decrite ;
  - Fiche 3 (retour au POC) : profil de volume reconstruit (volume de chaque minute reparti sur son range), delta
    approche par classification en volume (BVC : part acheteuse = Phi(dP / sigma), Easley, Lopez de Prado, O'Hara) ;
  - Fiche 4 (filtres) : VPIN calcule par BVC sur barres de volume (methode du papier) et exclusion des annonces ;
    le desequilibre du carnet (OBI) n est PAS testable ;
  - Fiche 2 (absorption) : NON testable. Elle compare la variation de prix a l OFI des meilleures limites ; un delta
    BVC est lui-meme deduit du prix, le residu serait circulaire. ofi_cont() et absorption() sont prets pour des
    donnees de carnet (Databento mbp-1 / tbbo).
Module A : taille en R (micros), 2 positions max, perte du jour 3R, seuils d arret (12,6R, 9 pertes de suite).
Module B : validation (intervalles de confiance, concentration, periodes, couts, regimes, Sharpe deflate, PBO).

Execution identique au moteur qf : decision a la cloture d une barre, ordre marche a l ouverture suivante + glissement,
limite remplie seulement si le prix la TRAVERSE (pas au simple contact), stop prioritaire sur l objectif.
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
from scipy.special import ndtr

from .qf import INSTRUMENTS, futures_minutes, resample

PY_DIR = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", ".."))
MICRO = {"ES": "MES", "NQ": "MNQ"}
NS_MIN = 60_000_000_000
NS_JOUR = 86_400_000_000_000
R_DEFAUT = 250.0                 # 1R du post (compte simule de 25 000 $)
CAPITAL = 25000.0
PERIODE_POST = ("2026-03-16", "2026-09-30")

# Decisions FOMC (communique 14:00 ET, conference 14:30 ET depuis 2019) ; 2020-03-03 : baisse d urgence a 10:00 ET.
FOMC = """2016-01-27 2016-03-16 2016-04-27 2016-06-15 2016-07-27 2016-09-21 2016-11-02 2016-12-14
2017-02-01 2017-03-15 2017-05-03 2017-06-14 2017-07-26 2017-09-20 2017-11-01 2017-12-13
2018-01-31 2018-03-21 2018-05-02 2018-06-13 2018-08-01 2018-09-26 2018-11-08 2018-12-19
2019-01-30 2019-03-20 2019-05-01 2019-06-19 2019-07-31 2019-09-18 2019-10-30 2019-12-11
2020-01-29 2020-04-29 2020-06-10 2020-07-29 2020-09-16 2020-11-05 2020-12-16
2021-01-27 2021-03-17 2021-04-28 2021-06-16 2021-07-28 2021-09-22 2021-11-03 2021-12-15
2022-01-26 2022-03-16 2022-05-04 2022-06-15 2022-07-27 2022-09-21 2022-11-02 2022-12-14
2023-02-01 2023-03-22 2023-05-03 2023-06-14 2023-07-26 2023-09-20 2023-11-01 2023-12-13
2024-01-31 2024-03-20 2024-05-01 2024-06-12 2024-07-31 2024-09-18 2024-11-07 2024-12-18
2025-01-29 2025-03-19 2025-05-07 2025-06-18 2025-07-30 2025-09-17 2025-10-29 2025-12-10
2026-01-28 2026-03-18 2026-04-29 2026-06-17 2026-07-29 2026-09-16 2026-10-28 2026-12-09""".split()


# =============================================================================
#  Donnees d un marche (minutes, barres 5 min, statistiques par creneau horaire)
# =============================================================================
class Marche:
    def __init__(self, root: str):
        df = futures_minutes(root)
        self.root = root
        self.inst = INSTRUMENTS[MICRO.get(root, root)]
        self.tick = self.inst.tick
        idx = pd.DatetimeIndex(df.index).as_unit("ns")
        self.idx, self.t = idx, idx.asi8
        self.o, self.h, self.l, self.c, self.v = (df[k].to_numpy(float) for k in ("open", "high", "low", "close", "volume"))
        self.n = len(self.c)
        et_ns = idx.tz_localize("UTC").tz_convert("America/New_York").tz_localize(None).asi8
        self.tod = ((et_ns // NS_MIN) % 1440).astype(np.int32)          # minute ET de FIN de barre
        self.jour = (et_ns // NS_JOUR).astype(np.int64)                  # jour calendaire ET
        self.tday = ((et_ns + 6 * 3_600_000_000_000) // NS_JOUR).astype(np.int64)
        self.wd = ((self.jour + 3) % 7).astype(np.int8)                  # 0 = lundi
        chg = np.r_[np.nonzero(np.diff(self.tday))[0], self.n - 1]
        self.fin_tday = np.repeat(chg, np.diff(np.r_[-1, chg]))          # dernier indice de la seance de chaque minute
        self._df = df
        self._b5 = None
        self._creneau = {}
        self._delta = None
        self._vpin = {}

    def arrondi(self, px: float) -> float:
        return round(px / self.tick) * self.tick

    # --- barres 5 minutes -----------------------------------------------------------------------------------
    @property
    def b5(self):
        if self._b5 is None:
            b = resample(self._df, 5)
            t5 = pd.DatetimeIndex(b.index).as_unit("ns").asi8
            c5 = b["close"].to_numpy(float)
            cont = np.r_[False, np.diff(t5) == 5 * NS_MIN]
            r = np.full(len(c5), np.nan)
            mv = np.full(len(c5), np.nan)
            r[1:] = np.log(c5[1:] / c5[:-1])
            mv[1:] = c5[1:] - c5[:-1]
            r[~cont], mv[~cont] = np.nan, np.nan
            et_ns = pd.DatetimeIndex(t5).tz_localize("UTC").tz_convert("America/New_York").tz_localize(None).asi8
            pos1 = np.searchsorted(self.t, t5, side="right") - 1
            okp = (pos1 >= 0) & (self.t[np.clip(pos1, 0, None)] > t5 - 5 * NS_MIN)
            self._b5 = dict(t=t5, o=b["open"].to_numpy(float), h=b["high"].to_numpy(float), l=b["low"].to_numpy(float),
                            c=c5, v=b["volume"].to_numpy(float), r=r, move=mv, pos1=np.where(okp, pos1, -1),
                            slot=((et_ns // NS_MIN) % 1440).astype(np.int32),
                            tday=((et_ns + 6 * 3_600_000_000_000) // NS_JOUR).astype(np.int64))
        return self._b5

    def creneau(self, fenetre: int = 20):
        """Ecart-type du rendement 5 min et volume 5 min moyen au MEME creneau horaire sur les `fenetre` seances
        precedentes (seance courante exclue). -> (sigma, volume moyen), alignes sur les barres 5 min."""
        if fenetre not in self._creneau:
            b = self.b5
            f = pd.DataFrame({"tday": b["tday"], "slot": b["slot"], "r": b["r"], "v": b["v"]})
            pr = f.groupby(["tday", "slot"])["r"].last().unstack()
            pv = f.groupby(["tday", "slot"])["v"].last().unstack()
            sig = pr.rolling(fenetre, min_periods=15).std().shift(1)
            vm = pv.rolling(fenetre, min_periods=15).mean().shift(1)
            ri, ci = pr.index.get_indexer(b["tday"]), pr.columns.get_indexer(b["slot"])
            self._creneau[fenetre] = (sig.to_numpy()[ri, ci], vm.to_numpy()[ri, ci])
        return self._creneau[fenetre]

    # --- annonces macro -----------------------------------------------------------------------------------------
    def exclusion_macro(self, avant: int, apres: int) -> np.ndarray:
        """True si la minute (heure de fin de barre) tombe entre `avant` min avant et `apres` min apres une annonce
        programmee : 08:30 et 10:00 ET chaque jour ouvre (statistiques US), 14:00-14:30 ET les jours de FOMC.
        Approximation sans calendrier detaille : couvre emploi, inflation, PIB, ISM, confiance, inscriptions..."""
        tod, ouvre = self.tod, self.wd < 5
        ex = np.zeros(self.n, bool)
        for h in (510, 600):
            ex |= ouvre & (tod >= h - avant) & (tod <= h + apres)
        fomc = np.isin(self.jour, (pd.DatetimeIndex(FOMC).asi8 // NS_JOUR))
        ex |= fomc & (tod >= 840 - avant) & (tod <= 870 + apres)
        urgence = self.jour == pd.Timestamp("2020-03-03").value // NS_JOUR
        ex |= urgence & (tod >= 600 - avant) & (tod <= 600 + apres)
        return ex

    # --- delta approche (BVC) et VPIN ----------------------------------------------------------------------------
    def delta_bvc(self) -> np.ndarray:
        """Delta par minute = volume x (2 Phi(dP / sigma) - 1), sigma = ecart-type des variations 1 min de la seance
        precedente (pas de regard vers le futur)."""
        if self._delta is None:
            dp = np.r_[np.nan, np.diff(self.c)]
            dp[np.r_[True, np.diff(self.tday) != 0]] = np.nan
            sd = pd.Series(dp).groupby(self.tday).std()
            sig = sd.shift(1).reindex(self.tday).to_numpy()
            with np.errstate(divide="ignore", invalid="ignore"):
                z = np.where(sig > 0, dp / sig, 0.0)
            self._delta = self.v * (2.0 * ndtr(np.nan_to_num(z)) - 1.0)
        return self._delta

    def vpin_toxique(self, seaux_jour: int = 50, fenetre: int = 50, jours: int = 20, q: float = 0.90) -> np.ndarray:
        """Fiche 4 : VPIN sur barres de volume (taille = volume journalier moyen des 20 seances precedentes / 50),
        classification BVC ; True quand le VPIN du dernier seau termine depasse son 90e centile des 20 seances."""
        cle = (seaux_jour, fenetre, jours, q)
        if cle in self._vpin:
            return self._vpin[cle]
        delta = self.delta_bvc()
        buy = (self.v + delta) / 2.0
        vjour = pd.Series(self.v).groupby(self.tday).sum()
        taille = (vjour.rolling(jours, min_periods=5).mean().shift(1) / seaux_jour).reindex(self.tday).to_numpy()
        cum = pd.Series(self.v).groupby(self.tday).cumsum().to_numpy() - self.v       # volume avant la minute
        with np.errstate(divide="ignore", invalid="ignore"):
            seau_jour = np.where(taille > 0, np.floor(cum / taille), -1).astype(np.int64)
        cle_seau = self.tday * 100000 + seau_jour
        valide = seau_jour >= 0
        g = pd.DataFrame({"k": cle_seau[valide], "buy": buy[valide], "v": self.v[valide],
                          "fin": np.nonzero(valide)[0]}).groupby("k", sort=True)
        agg = g.agg(buy=("buy", "sum"), v=("v", "sum"), fin=("fin", "max"))
        oi = (2 * agg["buy"] - agg["v"]).abs() / agg["v"].where(agg["v"] > 0)
        vp = oi.rolling(fenetre, min_periods=fenetre // 2).mean()
        seuil = vp.rolling(jours * seaux_jour, min_periods=200).quantile(q).shift(1)
        tox_seau = (vp > seuil).to_numpy()
        fins = agg["fin"].to_numpy()
        k = np.searchsorted(fins, np.arange(self.n), side="right") - 1    # dernier seau termine a cette minute
        out = np.where(k >= 0, tox_seau[np.clip(k, 0, None)], False)
        self._vpin[cle] = out
        return out


_MARCHES: dict[str, Marche] = {}


def marche(root: str) -> Marche:
    if root not in _MARCHES:
        _MARCHES[root] = Marche(root)
    return _MARCHES[root]


# =============================================================================
#  Execution d un trade (memes regles que qf.Engine)
# =============================================================================
def _gerer(m: Marche, j: int, side: int, stop: float, cible: float, fin: int, slip: float):
    """Position ouverte pendant la barre j ; stops/objectifs actifs des la barre j. -> (barre, prix, raison)."""
    o, h, l, c = m.o, m.h, m.l, m.c
    for t in range(j, fin + 1):
        tenu = t > j
        if (l[t] <= stop) if side > 0 else (h[t] >= stop):
            px = stop
            if tenu and ((side > 0 and o[t] <= stop) or (side < 0 and o[t] >= stop)):
                px = o[t]
            return t, px - side * slip, "stop"
        if math.isfinite(cible) and ((h[t] > cible) if side > 0 else (l[t] < cible)):
            px = cible
            if tenu and ((side > 0 and o[t] >= cible) or (side < 0 and o[t] <= cible)):
                px = o[t]
            return t, px, "objectif"
    return fin, c[fin] - side * slip, "temps"


def _trade(m: Marche, strat: str, side: int, qty: int, j: int, px_e: float, k: int, px_s: float, raison: str, R: float,
           frais: bool = True):
    pv, com = m.inst.point_value, (m.inst.commission if frais else 0.0)
    pnl = side * (px_s - px_e) * qty * pv - 2 * com * qty
    return dict(strategie=strat, instrument=m.inst.name, sens=side, qty=qty, entry_time=m.idx[j], entry_price=px_e,
                exit_time=m.idx[k], exit_price=px_s, reason=raison, pnl=pnl, r=pnl / R,
                jour=pd.Timestamp(int(m.tday[j]) * NS_JOUR))


# =============================================================================
#  Fiche 1 - retournement apres un choc de prix et de volume
# =============================================================================
@dataclass
class ParamsF1:
    seuil_sigma: float = 4.0          # [arXiv 2601.08974] tirage a ~4 sigma
    mult_volume: float = 2.0          # [Choix] volume 5 min >= 2 x moyenne du creneau
    retour: float = 0.25              # [arXiv] pente de retour b ~ -0,2 a -0,36
    duree_min: int = 5                # [arXiv] horizon 5 min
    ventes: bool = True
    taille_vente: float = 0.5         # [Choix] ventes apres une hausse : demi-taille
    fenetre: int = 20                 # [Choix] seances pour l ecart-type du creneau
    macro_avant: int = 15             # fiche 1 : pas d entree 15 min autour d une annonce
    macro_apres: int = 15
    vpin: bool = False                # fiche 4 en filtre
    validite_limite: int = 1          # fiche 4 : limite annulee si non remplie (10 s -> 1 barre de 1 min)
    entree: str = "limite"            # fiche : limite au prix de cloture du choc ; "marche" = diagnostic (selection adverse)


def backtest_f1(m: Marche, p: ParamsF1 = ParamsF1(), R: float = R_DEFAUT, glissement: int = 2, nom: str = "F1",
                frais: bool = True) -> pd.DataFrame:
    b = m.b5
    sig, vm = m.creneau(p.fenetre)
    with np.errstate(divide="ignore", invalid="ignore"):
        z = b["r"] / sig
    cand = np.nonzero(np.isfinite(z) & (np.abs(z) >= p.seuil_sigma) & (b["v"] >= p.mult_volume * vm) & (b["pos1"] >= 0))[0]
    excl = m.exclusion_macro(p.macro_avant, p.macro_apres) if p.macro_avant is not None else None
    tox = m.vpin_toxique() if p.vpin else None
    tick, pv, slip = m.tick, m.inst.point_value, glissement * m.tick
    rows, libre = [], 0
    for s in cand:
        i = int(b["pos1"][s])
        if i < libre or i + 1 >= m.n or (excl is not None and excl[i]) or (tox is not None and tox[i]):
            continue
        side = 1 if b["r"][s] < 0 else -1
        if side < 0 and not p.ventes:
            continue
        P = m.c[i]
        stop = b["l"][s] - 2 * tick if side > 0 else b["h"][s] + 2 * tick
        risque = (P - stop) * side
        if risque <= 0:
            continue
        qty = int((R * (1.0 if side > 0 else p.taille_vente)) // (risque * pv))
        if qty < 1:
            continue
        cible = m.arrondi(P + side * p.retour * abs(b["move"][s]))
        if (cible - P) * side < tick:
            cible = P + side * tick
        j = px_e = None
        if p.entree == "marche" and m.tday[i + 1] == m.tday[i]:
            j, px_e = i + 1, m.o[i + 1] + side * slip
        for jj in range(i + 1, min(i + 1 + p.validite_limite, m.n)):
            if j is not None:
                break
            if m.tday[jj] != m.tday[i]:
                break
            if side > 0 and m.o[jj] < P:
                j, px_e = jj, m.o[jj]
            elif side > 0 and m.l[jj] < P:
                j, px_e = jj, P
            elif side < 0 and m.o[jj] > P:
                j, px_e = jj, m.o[jj]
            elif side < 0 and m.h[jj] > P:
                j, px_e = jj, P
            if j is not None:
                break
        if j is None:
            libre = i + 1 + p.validite_limite
            continue
        fin = min(j + p.duree_min - 1, int(m.fin_tday[j]))
        k, px_s, raison = _gerer(m, j, side, stop, cible, fin, slip)
        rows.append(_trade(m, nom, side, qty, j, px_e, k, px_s, raison, R, frais))
        libre = k + 1
    return pd.DataFrame(rows)


def diagnostic_chocs(m: Marche, p: ParamsF1 = ParamsF1()) -> pd.DataFrame:
    """Le phenomene du papier existe-t-il dans ces donnees, AVANT toute execution ? Pour chaque choc (|rendement 5 min|
    >= seuil x sigma du creneau), rendement des 5 minutes suivantes (cloture a cloture des barres 5 min), en points de
    base. Ventile par sens, volume (>= mult x creneau ou non) et seance (US 09:30-16:00 ET ou nuit)."""
    b = m.b5
    sig, vm = m.creneau(p.fenetre)
    with np.errstate(divide="ignore", invalid="ignore"):
        z = b["r"] / sig
    nxt = np.r_[b["t"][1:] - b["t"][:-1] == 5 * NS_MIN, False]
    fwd = np.full(len(z), np.nan)
    fwd[:-1] = np.log(b["c"][1:] / b["c"][:-1])
    fwd[~nxt] = np.nan
    ok = np.isfinite(z) & (np.abs(z) >= p.seuil_sigma) & np.isfinite(fwd) & np.isfinite(vm)
    d = pd.DataFrame({"sens": np.where(b["r"] < 0, "chute", "hausse")[ok],
                      "volume": np.where(b["v"] >= p.mult_volume * vm, f"volume >= {p.mult_volume:g}x", "volume normal")[ok],
                      "seance": np.where((b["slot"] > 570) & (b["slot"] <= 960), "US 09:30-16:00", "nuit")[ok],
                      "choc_pb": b["r"][ok] * 1e4, "suite_pb": fwd[ok] * 1e4})
    d["retour"] = np.sign(d["suite_pb"]) == -np.sign(d["choc_pb"])
    g = d.groupby(["sens", "volume", "seance"])
    return g.agg(chocs=("choc_pb", "size"), choc_moyen_pb=("choc_pb", "mean"), suite_moyenne_pb=("suite_pb", "mean"),
                 part_retour=("retour", "mean")).reset_index()


# =============================================================================
#  Fiche 3 - retour vers le POC du profil de volume
# =============================================================================
@njit(cache=True)
def _zone_valeur(prof, part):
    n = prof.size
    tot = prof.sum()
    if tot <= 0.0:
        return -1, -1, -1
    poc = int(np.argmax(prof))
    lo = poc
    hi = poc
    acc = prof[poc]
    cible = part * tot
    while acc < cible and (lo > 0 or hi < n - 1):
        up = prof[hi + 1] if hi < n - 1 else -1.0
        dn = prof[lo - 1] if lo > 0 else -1.0
        if up >= dn:
            hi += 1
            acc += up
        else:
            lo -= 1
            acc += dn
    return poc, lo, hi


@dataclass
class ParamsF3:
    mode: str = "sans_volume"         # fiche : sortie SANS volume ; "avec_volume" = test recommande (filtre inverse)
    part_valeur: float = 0.70
    attente_min: int = 60             # pas de trade avant 60 min de seance (10:30 ET)
    seuil_volume: float = 0.8         # volume de la sortie < 0,8 x moyenne du creneau
    seuil_delta: float = 0.20         # |delta| < 20 % du volume
    derniere_entree: int = 930        # [Choix] pas de nouvelle entree apres 15:30 ET
    fenetre: int = 20
    macro_avant: int | None = 5       # fiche 4 : 5 min avant, 15 min apres
    macro_apres: int = 15
    vpin: bool = False


def backtest_f3(m: Marche, p: ParamsF3 = ParamsF3(), R: float = R_DEFAUT, glissement: int = 2, nom: str = "F3",
                frais: bool = True) -> pd.DataFrame:
    tick, pv, slip = m.tick, m.inst.point_value, glissement * m.tick
    _, vm5 = m.creneau(p.fenetre)
    b = m.b5
    vm_min = np.full(m.n, np.nan)                         # volume moyen du creneau 5 min, porte sur la minute de fin
    okb = b["pos1"] >= 0
    vm_min[b["pos1"][okb]] = vm5[okb]
    delta = m.delta_bvc()
    excl = m.exclusion_macro(p.macro_avant, p.macro_apres) if p.macro_avant is not None else None
    tox = m.vpin_toxique() if p.vpin else None
    rth = np.nonzero((m.tod > 570) & (m.tod <= 960) & (m.wd < 5))[0]
    coupes = np.nonzero(np.diff(m.jour[rth]))[0] + 1
    rows, libre = [], 0
    for ix in np.split(rth, coupes):
        if ix.size < 90:
            continue
        lo_d = m.l[ix].min()
        nb = int(round((m.h[ix].max() - lo_d) / tick)) + 1
        prof = np.zeros(nb)
        etat, extreme = 0, np.nan
        dernier = int(ix[-1])
        for q, i in enumerate(ix):
            a = int(round((m.l[i] - lo_d) / tick))
            z = int(round((m.h[i] - lo_d) / tick))
            prof[a:z + 1] += m.v[i] / (z - a + 1)
            tod = m.tod[i]
            if tod % 5 != 0 or tod < 570 + p.attente_min:
                continue
            poc, va_lo, va_hi = _zone_valeur(prof, p.part_valeur)
            if poc < 0:
                continue
            vah, val, ppoc = lo_d + va_hi * tick, lo_d + va_lo * tick, lo_d + poc * tick
            der5 = ix[max(0, q - 4):q + 1]
            v5, d5 = m.v[der5].sum(), delta[der5].sum()
            ci = m.c[i]
            if ci > vah or ci < val:
                sens = 1 if ci > vah else -1
                vmo = vm_min[i]
                if not np.isfinite(vmo) or v5 <= 0:
                    etat = 0
                    continue
                if p.mode == "sans_volume":
                    qual = v5 < p.seuil_volume * vmo and abs(d5) < p.seuil_delta * v5
                else:
                    qual = v5 >= vmo / p.seuil_volume and abs(d5) >= p.seuil_delta * v5
                if not qual:
                    etat = 0
                    continue
                ext5 = m.h[der5].max() if sens > 0 else m.l[der5].min()
                extreme = ext5 if etat != sens else (max(extreme, ext5) if sens > 0 else min(extreme, ext5))
                etat = sens
                continue
            if etat == 0:
                continue
            side, arme = -etat, etat
            etat = 0
            if i < libre or tod > p.derniere_entree or i + 1 > dernier:
                continue
            if (excl is not None and excl[i]) or (tox is not None and tox[i]):
                continue
            stop = extreme + 2 * tick if arme > 0 else extreme - 2 * tick
            risque = (ci - stop) * side
            if risque <= 0 or (ppoc - ci) * side < tick:
                continue
            qty = int(R // (risque * pv))
            if qty < 1:
                continue
            j = i + 1
            px_e = m.o[j] + side * slip
            k, px_s, raison = _gerer(m, j, side, stop, ppoc, dernier, slip)
            rows.append(_trade(m, nom, side, qty, j, px_e, k, px_s, raison if raison != "temps" else "fin de seance", R, frais))
            libre = k + 1
    return pd.DataFrame(rows)


# =============================================================================
#  Fiche 2 - absorption (pret pour des donnees de carnet ; non testable sur OHLCV)
# =============================================================================
def ofi_cont(bid_px, bid_sz, ask_px, ask_sz) -> np.ndarray:
    """OFI de Cont, Kukanov, Stoikov (arXiv 1011.6402) evenement par evenement, a partir des meilleures limites
    (ex. Databento mbp-1 : bid_px_00, bid_sz_00, ask_px_00, ask_sz_00). Sommer sur une barre de volume."""
    bp, bs, ap, az = (np.asarray(x, float) for x in (bid_px, bid_sz, ask_px, ask_sz))
    e = np.zeros(bp.size)
    e[1:] = (np.where(bp[1:] >= bp[:-1], bs[1:], 0.0) - np.where(bp[1:] <= bp[:-1], bs[:-1], 0.0)
             - np.where(ap[1:] <= ap[:-1], az[1:], 0.0) + np.where(ap[1:] >= ap[:-1], az[:-1], 0.0))
    return e


def absorption(dprix, ofi, beta, sd_residu, seuil: float = 2.0) -> np.ndarray:
    """Fiche 2 : residu standardise (dprix - beta x OFI) / sd ; -1 = vendre (OFI acheteur absorbe), +1 = acheter."""
    dprix, ofi = np.asarray(dprix, float), np.asarray(ofi, float)
    z = (dprix - np.asarray(beta, float) * ofi) / np.asarray(sd_residu, float)
    return np.where((z <= -seuil) & (ofi > 0), -1, np.where((z >= seuil) & (ofi < 0), 1, 0))


# =============================================================================
#  Module A - taille, positions simultanees, perte du jour, seuils d arret
# =============================================================================
@dataclass
class ModuleA:
    R: float = R_DEFAUT
    positions_max: int = 2            # [Fil]
    perte_jour_R: float = 3.0         # [Choix] arret jusqu au lendemain
    dd_arret_R: float = 12.6          # [Choix] 2 x drawdown max de la simulation (6,3R)
    serie_arret: int = 9              # [Choix] au-dela des ~8 pertes de suite attendues sur 1 000 trades

    def appliquer(self, trades: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
        """Rejoue les trades de toutes les strategies dans l ordre d entree et refuse ceux qui violent les regles.
        -> (trades acceptes, evenements : refus par regle, dates ou les seuils d arret auraient ete atteints)."""
        if trades.empty:
            return trades, dict(refus_positions=0, refus_perte_jour=0, arret_dd=None, arret_serie=None)
        import heapq
        t = trades.sort_values("entry_time").reset_index(drop=True)
        ent, sor = t["entry_time"].to_numpy(), t["exit_time"].to_numpy()
        rr, jr = t["r"].to_numpy(float), t["jour"].to_numpy()
        ouverts, realise, garde = [], {}, []          # tas des sorties des trades acceptes ; R realise par jour
        refus_pos = refus_jour = 0
        for k in range(len(t)):
            while ouverts and ouverts[0][0] <= ent[k]:
                _, x = heapq.heappop(ouverts)
                realise[jr[x]] = realise.get(jr[x], 0.0) + rr[x]
            if len(ouverts) >= self.positions_max:
                refus_pos += 1
                continue
            if realise.get(jr[k], 0.0) <= -self.perte_jour_R:
                refus_jour += 1
                continue
            garde.append(k)
            heapq.heappush(ouverts, (sor[k], k))
        acc = t.loc[garde].sort_values("exit_time")
        cum = acc["r"].cumsum()
        dd = cum.cummax().clip(lower=0) - cum
        arret_dd = acc["exit_time"][dd >= self.dd_arret_R].min() if (dd >= self.dd_arret_R).any() else None
        perte = (acc["r"] < 0).astype(int).to_numpy()
        serie, arret_serie = 0, None
        for x, ts in zip(perte, acc["exit_time"]):
            serie = serie + 1 if x else 0
            if serie >= self.serie_arret and arret_serie is None:
                arret_serie = ts
        return acc.sort_values("entry_time"), dict(refus_positions=refus_pos, refus_perte_jour=refus_jour,
                                                   arret_dd=arret_dd, arret_serie=arret_serie)


# =============================================================================
#  Module B - validation
# =============================================================================
def r_quotidien(trades: pd.DataFrame, jours: pd.DatetimeIndex | None = None) -> pd.Series:
    if trades.empty:
        return pd.Series(dtype=float)
    d = trades.groupby(trades["exit_time"].dt.normalize())["r"].sum()
    jours = jours if jours is not None else pd.bdate_range(d.index.min(), d.index.max())
    return d.reindex(jours, fill_value=0.0)


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return math.nan, math.nan
    p = k / n
    den = 1 + z * z / n
    c = (p + z * z / (2 * n)) / den
    w = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return c - w, c + w


def stats_r(trades: pd.DataFrame, n_essais: int = 1) -> dict:
    """Statistiques en R d une liste de trades (une ligne par trade, colonne r)."""
    from .. import validation as V
    n = len(trades)
    if n == 0:
        return dict(n=0)
    r = trades["r"].to_numpy(float)
    gains, pertes = r[r > 0].sum(), -r[r < 0].sum()
    sd = r.std(ddof=1) if n > 1 else math.nan
    cum = np.cumsum(r[np.argsort(trades["exit_time"].to_numpy())])
    serie = mx = 0
    for x in r[np.argsort(trades["exit_time"].to_numpy())]:
        serie = serie + 1 if x < 0 else 0
        mx = max(mx, serie)
    rq = r_quotidien(trades)
    sh = float(rq.mean() / rq.std(ddof=1) * math.sqrt(252)) if len(rq) > 2 and rq.std(ddof=1) > 0 else math.nan
    dsr, _ = V.deflated_sharpe(rq.to_numpy(), n_trials=n_essais) if len(rq) > 10 else (math.nan, math.nan)
    mois = trades.groupby(trades["exit_time"].dt.to_period("M"))["r"].sum()
    lo, hi = wilson(int((r > 0).sum()), n)
    return dict(n=n, reussite=float((r > 0).mean()), reussite_ic=(lo, hi), esperance=float(r.mean()),
                esperance_ic=(float(r.mean() - 1.96 * sd / math.sqrt(n)), float(r.mean() + 1.96 * sd / math.sqrt(n))) if n > 1 else (math.nan, math.nan),
                sd=float(sd), total=float(r.sum()), pf=float(gains / pertes) if pertes > 0 else math.nan,
                dd=float((np.maximum.accumulate(np.r_[0.0, cum]) - np.r_[0.0, cum]).max()), serie_pertes=mx,
                sharpe=sh, dsr=dsr, sans_5_meilleurs=float(np.sort(r)[:-5].sum()) if n > 5 else math.nan,
                sans_meilleur_mois=float(mois.sum() - mois.max()) if len(mois) else math.nan,
                mois_positifs=f"{int((mois > 0).sum())}/{len(mois)}", gain_moy=float(r[r > 0].mean()) if (r > 0).any() else math.nan,
                perte_moy=float(r[r < 0].mean()) if (r < 0).any() else math.nan)


def regimes_vol(m: Marche, trades: pd.DataFrame) -> pd.Series:
    """R moyen par tercile de volatilite realisee (20 seances, rendements journaliers du marche) au jour du trade."""
    cl = pd.Series(m.c).groupby(m.tday).last()
    vol = np.log(cl).diff().rolling(20).std().shift(1)
    vol.index = pd.to_datetime(vol.index.to_numpy() * NS_JOUR)
    terc = pd.qcut(vol.dropna(), 3, labels=["calme", "moyen", "agite"])
    lab = terc.reindex(trades["jour"]).to_numpy()
    return trades.assign(regime=lab).groupby("regime", observed=False)["r"].agg(["count", "mean", "sum"])


# =============================================================================
#  Rapport
# =============================================================================
def _fmt_stats(nom: str, s: dict) -> str:
    if not s or s.get("n", 0) == 0:
        return f"  {nom:38} aucun trade"
    lo, hi = s["reussite_ic"]
    elo, ehi = s["esperance_ic"]
    return (f"  {nom:38} {s['n']:5d} trades | reussite {s['reussite']:5.1%} [{lo:.0%}-{hi:.0%}] | esperance {s['esperance']:+.3f}R "
            f"[{elo:+.2f} ; {ehi:+.2f}] | total {s['total']:+8.1f}R | PF {s['pf']:.2f} | DD {s['dd']:5.1f}R | "
            f"serie de pertes {s['serie_pertes']:2d} | Sharpe {s['sharpe']:+.2f} | mois positifs {s['mois_positifs']}")


def _periode(t: pd.DataFrame, a=None, b=None) -> pd.DataFrame:
    if t.empty:
        return t
    x = t
    if a:
        x = x[x["entry_time"] >= pd.Timestamp(a)]
    if b:
        x = x[x["entry_time"] < pd.Timestamp(b)]
    return x


def etude(sortie: str | None = None, marches=("ES", "NQ"), log=print) -> dict:
    from .. import validation as V
    t0 = datetime.now()
    L = []
    pr = L.append
    M = {r: marche(r) for r in marches}
    pr("=" * 118)
    pr(" FICHES DU FIL ES/NQ « 6 MOIS DE SIMULATION » - backtest Databento 1 minute, ES et NQ (micros MES / MNQ)")
    pr("=" * 118)
    debut = min(pd.Timestamp(mm.idx[0]) for mm in M.values())
    fin = max(pd.Timestamp(mm.idx[-1]) for mm in M.values())
    pr(f"Periode {debut:%Y-%m-%d} -> {fin:%Y-%m-%d}. 1R = {R_DEFAUT:.0f} $ (compte simule de {CAPITAL:,.0f} $ comme le post), "
       "taille = plancher(R / risque du stop) en micros.".replace(",", " "))
    pr("Couts : 2 ticks de glissement sur les ordres marche et stop (base du post), commission 0,60 $ par micro et par cote ;")
    pr("stress : 4 ticks. Limites remplies seulement si le prix les traverse (module B, point 2).")
    pr("Parametres principaux = ceux des fiches, figes AVANT le test. Les grilles ne servent qu a mesurer la robustesse.\n")

    res = {}

    def tous(fonction, params, nom, gl=2, frais=True):
        out = [fonction(mm, params, glissement=gl, nom=nom, frais=frais) for mm in M.values()]
        out = [x for x in out if not x.empty]
        return pd.concat(out, ignore_index=True) if out else pd.DataFrame()

    # --- Fiche 1 ---------------------------------------------------------------------------------------------
    log("[orderflow] fiche 1")
    f1 = tous(backtest_f1, ParamsF1(), "F1 choc prix+volume")
    f1_4 = tous(backtest_f1, ParamsF1(), "F1", gl=4)
    f1_f4 = tous(backtest_f1, ParamsF1(macro_avant=5, macro_apres=15, vpin=True), "F1 + filtres F4")
    f1_brut = tous(backtest_f1, ParamsF1(), "F1 sans couts", gl=0, frais=False)
    f1_mkt = tous(backtest_f1, ParamsF1(entree="marche"), "F1 entree au marche")
    f1_ach = f1[f1["sens"] > 0] if not f1.empty else f1
    f1_ven = f1[f1["sens"] < 0] if not f1.empty else f1
    grille1 = []
    for k in (3.0, 3.5, 4.0, 4.5):
        for mv in (1.5, 2.0, 3.0):
            for rt in (0.25, 0.5):
                g = tous(backtest_f1, ParamsF1(seuil_sigma=k, mult_volume=mv, retour=rt), f"F1 k={k} vol={mv} retour={rt}")
                grille1.append((f"k={k} vol={mv} retour={rt}", g))
    # --- Fiche 3 ---------------------------------------------------------------------------------------------
    log("[orderflow] fiche 3")
    f3 = tous(backtest_f3, ParamsF3(), "F3 POC sans volume")
    f3_4 = tous(backtest_f3, ParamsF3(), "F3", gl=4)
    f3_inv = tous(backtest_f3, ParamsF3(mode="avec_volume"), "F3 POC avec volume")
    f3_f4 = tous(backtest_f3, ParamsF3(vpin=True), "F3 + VPIN")
    f3_brut = tous(backtest_f3, ParamsF3(), "F3 sans couts", gl=0, frais=False)
    n_essais = len(grille1) + 6
    jours = pd.bdate_range(debut.normalize(), fin.normalize())

    pr("=== FICHE 1 - retournement apres un choc de prix et de volume ===")
    pr("Choc : rendement 5 min >= 4 ecarts-types du meme creneau (20 seances) ET volume >= 2 x la moyenne du creneau ;")
    pr("achat apres une chute, vente apres une hausse en demi-taille ; limite au prix de cloture du choc (1 minute) ;")
    pr("objectif 25 % du choc, stop au-dela de l extreme + 2 ticks, sortie au bout de 5 min ; pas d entree +-15 min")
    pr("autour de 08:30 / 10:00 ET (jours ouvres) et du FOMC.")
    pr("\nLe phenomene existe-t-il ici, AVANT execution et couts ? Rendement des 5 min suivant un choc >= 4 sigma (points de base) :")
    for mm in M.values():
        dg = diagnostic_chocs(mm)
        px = float(np.nanmedian(mm.c[-250000:]))
        cout = (2 * mm.tick + 2 * mm.inst.commission / mm.inst.point_value) / px * 1e4
        pr(f"  {mm.root} (cout d un aller-retour avec 2 ticks a la sortie et commissions : ~{cout:.1f} pb) :")
        for r in dg.itertuples():
            pr(f"    {r.sens:6} {r.volume:15} {r.seance:15} {r.chocs:6d} chocs | choc moyen {r.choc_moyen_pb:+7.1f} pb | "
               f"5 min suivantes {r.suite_moyenne_pb:+6.2f} pb | retour {r.part_retour:.0%}")
    pr("  (papier, ES 2010-2017 : apres une chute moyenne de -37 pb, +8 pb ; +13 pb a fort volume, +5 pb a faible volume.)\n")
    s_f1 = stats_r(f1, n_essais)
    for nom, t in [("F1 ES+NQ (parametres de la fiche)", f1), ("  dont achats (apres une chute)", f1_ach),
                   ("  dont ventes (apres une hausse)", f1_ven)] + \
                  [(f"  dont {mm.inst.name}", f1[f1["instrument"] == mm.inst.name] if not f1.empty else f1) for mm in M.values()] + \
                  [("F1 avec 4 ticks de glissement", f1_4), ("F1 + filtres fiche 4 (VPIN, annonces)", f1_f4),
                   ("diagnostic : F1 sans aucun cout", f1_brut), ("diagnostic : F1 entree au marche", f1_mkt)]:
        pr(_fmt_stats(nom, stats_r(t, n_essais)))
    pr("\nRobustesse (grille 4 seuils x 3 volumes x 2 objectifs, ES+NQ, 2 ticks) :")
    for lab, g in grille1:
        s = stats_r(g)
        pr(f"  {lab:28} {s.get('n', 0):5d} trades | esperance {s.get('esperance', math.nan):+.3f}R | total {s.get('total', math.nan):+7.1f}R"
           f" | Sharpe {s.get('sharpe', math.nan):+.2f}")
    mat = np.vstack([r_quotidien(g, jours).to_numpy() for _, g in grille1 if not g.empty]) if grille1 else np.empty((0, 0))
    pbo1, nc = V.pbo(mat) if mat.shape[0] >= 2 else (math.nan, 0)
    pr(f"Probabilite de surajustement (PBO, CSCV {nc} combinaisons) sur la grille : {pbo1:.0%} (le PBO mesure la stabilite du")
    pr("classement des variantes entre periodes, pas leur rentabilite : un PBO faible avec des variantes toutes negatives ne")
    pr("rend pas la strategie rentable)")

    pr("\n=== FICHE 3 - retour vers le POC (profil de volume reconstruit sur les minutes) ===")
    pr("Seance US 09:30-16:00 ET, profil = volume de chaque minute reparti sur son range ; zone de valeur 70 % ; declencheur :")
    pr("cloture 5 min hors zone de valeur, sortie « sans volume » (< 0,8 x creneau, |delta BVC| < 20 %) ; entree au retour")
    pr("dans la zone (marche), objectif POC, stop extreme + 2 ticks ; pas avant 10:30 ni apres 15:30 ; sortie a 16:00.")
    for nom, t in [("F3 ES+NQ (filtre de la fiche)", f3)] + \
                  [(f"  dont {mm.inst.name}", f3[f3["instrument"] == mm.inst.name] if not f3.empty else f3) for mm in M.values()] + \
                  [("F3 avec 4 ticks de glissement", f3_4), ("F3 filtre inverse (sorties AVEC volume)", f3_inv),
                   ("F3 + VPIN (fiche 4)", f3_f4), ("diagnostic : F3 sans aucun cout", f3_brut)]:
        pr(_fmt_stats(nom, stats_r(t, n_essais)))

    pr("\n=== FICHE 2 - absorption : NON TESTEE ===")
    pr("Il faut l OFI aux meilleures limites (taille et prix bid/ask a chaque evenement). Les barres 1 minute n ont ni carnet")
    pr("ni cote agresseur ; un delta deduit du prix (BVC) rendrait le residu « prix - OFI » circulaire. Le code (ofi_cont,")
    pr("absorption) est pret pour des donnees Databento mbp-1 ou tbbo d ES / NQ.")

    pr("\n=== FICHE 4 - filtres ===")
    pr("VPIN : teste ci-dessus (lignes « + filtres fiche 4 » et « + VPIN »). Desequilibre du carnet (OBI, 3 niveaux) : non testable")
    pr("sans carnet. Execution limite annulee apres 10 s : approchee par une validite d une barre de 1 minute.")

    # --- Module A ------------------------------------------------------------------------------------------
    log("[orderflow] modules A et B")
    pr("\n=== MODULE A - portefeuille F1 + F3 sur ES et NQ : 2 positions max, perte du jour 3R, seuils d arret ===")
    tout = pd.concat([x for x in (f1, f3) if not x.empty], ignore_index=True) if not (f1.empty and f3.empty) else pd.DataFrame()
    acc, ev = ModuleA().appliquer(tout)
    s_pf = stats_r(acc, n_essais)
    pr(_fmt_stats("Portefeuille apres module A", s_pf))
    pr(f"  refus : {ev['refus_positions']} trades (2 positions deja ouvertes), {ev['refus_perte_jour']} (perte du jour >= 3R)")
    pr("  seuil d arret 12,6R de drawdown : " + (f"atteint le {ev['arret_dd']:%Y-%m-%d}" if ev["arret_dd"] is not None else "jamais atteint"))
    pr("  seuil d arret 9 pertes de suite : " + (f"atteint le {ev['arret_serie']:%Y-%m-%d}" if ev["arret_serie"] is not None else "jamais atteint"))

    # --- Module B ------------------------------------------------------------------------------------------
    pr("\n=== MODULE B - validation ===")
    for nom, t in [("F1", f1), ("F3", f3), ("Portefeuille", acc)]:
        s = stats_r(t, n_essais)
        if s.get("n", 0) == 0:
            continue
        pr(f"{nom} :")
        pr(f"  sans les 5 meilleurs trades : {s['sans_5_meilleurs']:+.1f}R (total {s['total']:+.1f}R) ; sans le meilleur mois : "
           f"{s['sans_meilleur_mois']:+.1f}R")
        pr(f"  Sharpe deflate ({n_essais} essais comptes) : probabilite que le vrai Sharpe soit > 0 = {s['dsr']:.0%}"
           if math.isfinite(s["dsr"]) else "  Sharpe deflate : n/d")
        for lab, a, b in [("2016-2020 (avant)", None, "2021-01-01"), ("2021-2026 (apres)", "2021-01-01", None),
                          ("periode du post 16/03-28/08/2026", PERIODE_POST[0], PERIODE_POST[1])]:
            pr(_fmt_stats("  " + lab, stats_r(_periode(t, a, b))))
        if nom != "Portefeuille":
            for mm in M.values():
                sub = t[t["instrument"] == mm.inst.name]
                if len(sub):
                    rg = regimes_vol(mm, sub)
                    pr(f"  regimes de volatilite {mm.inst.name} : " + " | ".join(
                        f"{i} {int(r['count'])} trades {r['mean']:+.3f}R" for i, r in rg.iterrows()))
    post = _periode(acc, *PERIODE_POST)
    if len(post):
        mois = post.groupby(post["exit_time"].dt.to_period("M"))["r"].sum()
        pr("Par mois sur la periode du post (portefeuille) : " + " | ".join(f"{p.strftime('%m/%Y')} {v:+.1f}R" for p, v in mois.items()))
    pr("Post (pour memoire) : 103 trades, 53,4 % de reussite, +0,59R par trade, +60,8R, 7 mois positifs sur 7 (auto-declare).")
    pr(f"\nCalcul en {(datetime.now() - t0).total_seconds():.0f} s.")

    out_dir = os.path.join(PY_DIR, "resultats", f"orderflow_{datetime.now():%Y%m%d_%H%M%S}")
    os.makedirs(out_dir, exist_ok=True)
    for nom, t in [("f1", f1), ("f1_filtres_f4", f1_f4), ("f3", f3), ("f3_avec_volume", f3_inv), ("portefeuille_module_a", acc)]:
        t.to_csv(os.path.join(out_dir, f"trades_{nom}.csv"), index=False)
    pr(f"Trades : {out_dir}")
    sortie = sortie or os.path.join(PY_DIR, "recherche", "resultats_orderflow.txt")
    with open(sortie, "w", encoding="utf-8") as fh:
        fh.write("\n".join(L) + "\n")
    log("\n".join(L))
    res.update(f1=f1, f3=f3, portefeuille=acc, pbo_f1=pbo1, stats_f1=s_f1, stats_portefeuille=s_pf)
    return res


# =============================================================================
#  Integration au runner (une ligne par strategie dans resultats_strategies.txt et le tableau de bord)
# =============================================================================
def run_spec(spec: dict) -> tuple[dict, pd.DataFrame]:
    ms = [marche(r) for r in spec.get("marches", ("ES", "NQ"))]
    if spec["fiche"] == "F1":
        p = ParamsF1(**spec.get("params", {}))
        trades = [backtest_f1(m, p) for m in ms]
    else:
        p = ParamsF3(**spec.get("params", {}))
        trades = [backtest_f3(m, p) for m in ms]
    t = pd.concat([x for x in trades if not x.empty], ignore_index=True) if any(not x.empty for x in trades) else pd.DataFrame()
    jours = pd.to_datetime(np.unique(np.concatenate([m.tday for m in ms])) * NS_JOUR)
    jours = jours[jours.dayofweek < 5]
    if t.empty:
        eq = pd.Series(CAPITAL, index=jours)
        pnl = np.array([])
    else:
        d = t.groupby("jour")["pnl"].sum().reindex(jours, fill_value=0.0)
        eq = CAPITAL + d.cumsum()
        pnl = t["pnl"].to_numpy()
    dd = eq.diff().dropna()
    wins, losses = pnl[pnl > 0].sum() if pnl.size else 0.0, -pnl[pnl < 0].sum() if pnl.size else 0.0
    s = dict(trades=len(pnl), win_rate=float((pnl > 0).mean()) if pnl.size else math.nan, net=float(pnl.sum()) if pnl.size else 0.0,
             profit_factor=float(wins / losses) if losses > 0 else math.nan, avg_trade=float(pnl.mean()) if pnl.size else math.nan,
             sharpe=float(dd.mean() / dd.std() * math.sqrt(252)) if dd.std() > 0 else math.nan,
             max_dd=float((eq.cummax() - eq).max()), start=eq.index[0], end=eq.index[-1], capital=CAPITAL,
             t_stat=float(pnl.mean() / (pnl.std(ddof=1) / math.sqrt(pnl.size))) if pnl.size > 2 and pnl.std(ddof=1) > 0 else math.nan,
             equity=eq)
    s["data"] = "ES + NQ 1 min -> MES + MNQ, 1R = 250 $, 2 ticks"
    return s, t


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--sortie", default=None)
    a = ap.parse_args(argv)
    etude(a.sortie)


if __name__ == "__main__":
    main()
