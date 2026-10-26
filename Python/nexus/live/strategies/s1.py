"""S1 en direct : Noise Area Intraday Momentum sur NQ (S1_NoiseAreaNQ.py, valide le 2026-10-15, reglage FIGE).

Memes regles et memes constantes que le fichier autonome (importees de S1_NoiseAreaNQ.py, jamais recopiees) ;
seule l execution change : la decision est prise a la cloture de la minute de controle et l ordre part aussitot
(au lieu de l ouverture de la minute suivante dans le backtest : meme instant), la sortie de fin de seance part a
la cloture de la minute de 16:00 (13:00 les demi-seances).

Signal sur les barres de NQ, positions sur MNQ par defaut (2 $ le point au lieu de 20 $) :
  contrats = arrondi(capital x min(2 % / vol 14 j, 4) / (ouverture x valeur du point)).
Parametres (groupe.json) : donnees ("NQ"), negocie ("MNQ"), capital (en $, ou "compte" = valeur liquidative du
compte NinjaTrader), barres_chauffe (75 000 minutes : environ 54 seances, il en faut 45), max_contrats.
Demi-seances (cloture a 13:00) : veille du 4 juillet (du lundi au jeudi), lendemain de Thanksgiving, 24 decembre (du
lundi au jeudi) ; le rejeu de controle (python -m nexus.live --verifier) les compare aux demi-seances des donnees.
"""
from __future__ import annotations

import math
import os
import sys
from collections import deque
from datetime import date, timedelta
from zoneinfo import ZoneInfo

import numpy as np

from ..protocole import Barre, heure
from ..strategie import StrategieLive

_PY = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
if _PY not in sys.path:
    sys.path.insert(0, _PY)
import S1_NoiseAreaNQ as REF  # noqa: E402  (reglage fige et jours feries du fichier valide)

NY = ZoneInfo(REF.NY)
OUVERTURE = 570                     # 9:30 en minutes


def demi_seance(d: date) -> bool:
    """Seance actions de New York close a 13:00."""
    if d.month == 7 and d.day == 3 and d.weekday() <= 3:
        return True
    if d.month == 12 and d.day == 24 and d.weekday() <= 3:
        return True
    if d.month == 11 and d.weekday() == 4:
        premier_jeudi = 1 + (3 - date(d.year, 11, 1).weekday()) % 7
        return d.day == premier_jeudi + 22                              # lendemain du 4e jeudi
    return False


class S1(StrategieLive):
    def __init__(self, nom, params, ctx):
        super().__init__(nom, params, ctx)
        self.donnees = str(self.params.get("donnees", "NQ"))
        self.negocie = str(self.params.get("negocie", "MNQ"))
        self.capital = self.params.get("capital", 100_000.0)
        self.ecarts: deque = deque(maxlen=REF.SIGMA_SEANCES + 40)       # |C(m)/Open - 1| des seances valides, m = 1..390
        self.clotures: deque = deque(maxlen=REF.VOL_SEANCES + 2)        # cloture des seances valides
        self.feries = set(d.date() for d in REF.feries_nyse("2010-01-01", "2040-12-31"))
        self.jour: date | None = None
        self.valide = False
        self.decisions: list[dict] = []

    def abonnements(self):
        return {self.donnees: int(self.params.get("barres_chauffe", 75_000))}

    # ------------------------------------------------------------------ seance
    def _nouvelle_seance(self, d: date, m: int, b: Barre) -> None:
        self.jour = d
        self.valide = d.weekday() < 5 and d not in self.feries and m <= 5
        self.fin = 210 if demi_seance(d) else 390
        self.controles = list(range(REF.CONTROLE_MIN, self.fin, REF.CONTROLE_MIN))
        self.prochain = 0                                                # indice du prochain controle
        self.C = np.full(391, np.nan)
        self.m_dernier = 0
        self.pv = 0.0
        self.vol = 0.0
        self.ouv = b.o
        self.close_courant = b.o
        self.termine = False
        self.cible = 0
        self.pret = False
        self.contrats = 0
        if not self.valide:
            return
        veille = self.clotures[-1][1] if self.clotures else math.nan
        cl = np.array([c for _, c in self.clotures], float)
        r = cl[1:] / cl[:-1] - 1 if len(cl) >= 2 else np.array([])
        vol = float(np.std(r[-REF.VOL_SEANCES:], ddof=1)) if len(r) >= REF.VOL_SEANCES else math.nan
        self.levier = min(REF.VOL_CIBLE / vol, REF.LEVIER_MAX) if vol and np.isfinite(vol) else math.nan
        self.sigma = self._sigma()
        self.haut, self.bas = max(self.ouv, veille), min(self.ouv, veille)
        self.pret = (np.isfinite(self.levier) and np.isfinite(veille)
                     and all(np.isfinite(self.sigma[k]) for k in self.controles))
        if self.pret:
            cap = self.capital_du_jour(d)
            self.contrats = int(math.floor(cap * self.levier / (self.ouv * self.point(self.negocie)) + 0.5))
            self.ctx.journal(f"seance {d} : ouverture {self.ouv:.2f}, levier {self.levier:.2f}, {self.contrats} {self.negocie}"
                             + (" (demi-seance)" if self.fin == 210 else ""))

    def _sigma(self) -> np.ndarray:
        """Moyenne des 30 dernieres seances qui ont une valeur a la minute m (le jour courant n y entre jamais)."""
        out = np.full(391, np.nan)
        if not self.ecarts:
            return out
        E = np.vstack(list(self.ecarts))
        ok = np.isfinite(E)
        for m in range(1, 391):
            v = E[ok[:, m], m]
            if len(v) >= REF.SIGMA_SEANCES:
                out[m] = v[-REF.SIGMA_SEANCES:].mean()
        return out

    def capital_du_jour(self, d: date) -> float:
        if self.capital == "compte":
            v = self.ctx.valeur_liquidative()
            if v is None:
                raise RuntimeError("capital = compte, mais la valeur liquidative n est pas encore connue")
            return float(v)
        return float(self.capital)

    def _controle(self, k: int) -> None:
        """Controle a la minute k : C(k) et VWAP(k) = etat apres la derniere barre de minute <= k."""
        c = self.close_courant
        vw = self.pv / self.vol if self.vol > 0 else math.nan
        s = self.sigma[k]
        up, lo = self.haut * (1 + REF.BANDE * s), self.bas * (1 - REF.BANDE * s)
        cible = self.contrats if (c > up and c > vw) else (-self.contrats if (c < lo and c < vw) else 0)
        if cible != self.cible:
            self.decisions.append(dict(jour=self.jour, minute=k, cible=cible))
        self.cible = cible
        self.ctx.cible(self.negocie, cible, f"controle {(OUVERTURE + k) // 60}:{(OUVERTURE + k) % 60:02d} close {c:.2f} "
                                           f"bande [{lo:.2f} ; {up:.2f}] VWAP {vw:.2f}")

    def _clore(self) -> None:
        """Fin de seance : sortie, et la seance entre dans l historique (sigma, volatilite)."""
        self.termine = True
        if self.pret and self.cible != 0:
            self.decisions.append(dict(jour=self.jour, minute=self.fin, cible=0))
        self.cible = 0
        self.ctx.cible(self.negocie, 0, "fin de seance")
        C = self.C.copy()
        C[1:self.fin + 1] = _ffill(C[1:self.fin + 1], self.ouv)
        C[self.fin + 1:] = np.nan
        self.ecarts.append(np.abs(C / self.ouv - 1))
        self.clotures.append((self.jour, float(C[self.fin])))

    # ------------------------------------------------------------------ barres
    def sur_barre(self, instrument, b: Barre):
        if instrument != self.donnees:
            return
        n = heure(b.t, NY)
        m = n.hour * 60 + n.minute - OUVERTURE
        if m < 1 or m > 390 or n.weekday() >= 5:
            return
        d = n.date()
        if d != self.jour:
            self._fin_manquee()
            self._nouvelle_seance(d, m, b)
        if not self.valide or self.termine or m <= self.m_dernier:
            return
        # controles des minutes sans barre (prix inchange) avant d integrer cette barre
        while self.pret and self.prochain < len(self.controles) and self.controles[self.prochain] < m:
            self._controle(self.controles[self.prochain])
            self.prochain += 1
        if self.fin < m:
            self._clore()
            return
        self.C[m] = b.c
        self.close_courant = b.c
        self.pv += (b.h + b.l + b.c) / 3 * b.v
        self.vol += b.v
        self.m_dernier = m
        if self.pret and self.prochain < len(self.controles) and self.controles[self.prochain] == m:
            self._controle(m)
            self.prochain += 1
        if m == self.fin:
            self._clore()

    def _fin_manquee(self) -> None:
        """Seance sans barre de cloture (16:00 / 13:00) : sortie ; la seance n entre dans l historique que si ses barres
        vont jusqu a 4 minutes de la cloture (comme le backtest, qui ecarte les seances incompletes)."""
        if self.jour is None or not self.valide or self.termine:
            return
        if self.m_dernier >= self.fin - 4:
            self._clore()
        else:
            self.termine = True
            self.cible = 0
            self.ctx.cible(self.negocie, 0, "seance incomplete : sortie")

    def sur_horloge(self, t):
        if self.jour is None or not self.valide or self.termine:
            return
        n = heure(t, NY)
        if n.date() != self.jour or (n.hour * 60 + n.minute - OUVERTURE) * 60 + n.second >= self.fin * 60 + 10:
            self._fin_manquee()

    def apres_chauffe(self):
        self.cible = 0

    def etat(self):
        return dict(jour=str(self.jour), seance_valide=self.valide, pret=self.pret, contrats=self.contrats,
                    levier=round(self.levier, 3) if self.valide and np.isfinite(getattr(self, "levier", math.nan)) else None,
                    cible=self.cible, seances_historique=len(self.ecarts), fin=getattr(self, "fin", None),
                    haut=_arrondi(getattr(self, "haut", None)), bas=_arrondi(getattr(self, "bas", None)))


def _arrondi(x):
    return round(float(x), 2) if x is not None and np.isfinite(x) else None


def _ffill(x: np.ndarray, debut: float) -> np.ndarray:
    out = x.copy()
    dernier = debut
    for i in range(len(out)):
        if np.isfinite(out[i]):
            dernier = out[i]
        else:
            out[i] = dernier
    return out
