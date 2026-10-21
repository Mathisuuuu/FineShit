"""Gotobi en direct : yen (6J) autour du fixing de Tokyo les jours de reglement (nexus/gotobi.py, fiche du tableau de bord).

Memes regles et meme calendrier que la recherche (jours_gotobi de nexus/gotobi.py : 5, 10, 15, 20, 25 et dernier
jour ouvre du mois, jour non ouvre -> jour ouvre precedent, feries japonais) ; heures de Tokyo :
  08:00  vente de 6J ; 09:55  retournement a l achat ; 11:00  sortie.
Chaque ordre part a l heure prevue DU FIL DE DONNEES : horloge reelle moins le retard mesure du flux (mediane des 20
dernieres barres : nul en temps reel, ~10 min avec les cours differes du compte demo NinjaTrader), donc execute a
l ouverture de la barre suivante comme dans la recherche, et au meme decalage que les cours : coherent avec un broker. Au plus tard 10 minutes apres
(tolerance de la recherche) ; une jambe manquee (moteur lance trop tard) n est pas rattrapee. La sortie de 11:00 part toujours si une position reste.
Taille : notionnel = capital x exposition (95 000 $ pour 100 000 $) au dernier cours, arrondi au contrat (6J :
12,5 millions de yen) ; parametre "contrats" pour une taille fixe.
"""
from __future__ import annotations

from datetime import datetime, time as dtime, timedelta
from zoneinfo import ZoneInfo

from ... import gotobi as G
from ..protocole import heure
from ..strategie import StrategieLive

TOKYO = ZoneInfo(G.TOKYO)


def _hm(s: str) -> dtime:
    h, m = (int(x) for x in s.split(":"))
    return dtime(h, m)


class Gotobi(StrategieLive):
    def __init__(self, nom, params, ctx):
        super().__init__(nom, params, ctx)
        p = {**G.DEFAULTS, **self.params}
        self.negocie = str(p.get("negocie", "6J"))
        self.donnees = str(p.get("donnees", self.negocie))
        self.capital = float(p["capital"])
        self.exposition = float(p["exposition"])
        self.tolerance = timedelta(minutes=int(p["tolerance_min"]))
        self.heures = dict(entree=_hm(p["entree"]), fixing=_hm(p["fixing"]), sortie=_hm(p["sortie"]))
        self.contrats_fixes = p.get("contrats")
        self.annees: tuple[int, int] | None = None
        self.jours: set = set()
        self.jour = None
        self.faits: set = set()
        self.q = 0
        self.cible = 0
        self.retards: list[int] = []

    def abonnements(self):
        return {self.donnees: int(self.params.get("barres_chauffe", 1500))}

    def _calendrier(self, annee: int) -> None:
        if self.annees and self.annees[0] <= annee <= self.annees[1]:
            return
        self.annees = (annee - 1, annee + 1)
        self.jours = set(d.date() for d in G.jours_gotobi(f"{annee - 1}-01-01", f"{annee + 1}-12-31", True))

    def _taille(self) -> int:
        if self.contrats_fixes:
            return int(self.contrats_fixes)
        b = self.ctx.derniere(self.donnees)
        if b is None or not b.c > 0:
            return 0
        return int(round(self.capital * self.exposition / (b.c * self.point(self.negocie))))

    def _poser(self, q: int, motif: str) -> None:
        self.cible = q
        self.ctx.cible(self.negocie, q, motif)

    def sur_barre(self, instrument, b):
        """Mesure le retard du flux (heure reelle - fin de la barre recue) : nul en temps reel, ~10 min en differe."""
        if instrument != self.donnees or self.ctx is None or self.ctx.en_chauffe:
            return
        r = self.ctx.maintenant() - b.t
        if 0 <= r <= 2 * 3_600_000:                                       # un rattrapage apres coupure n est pas un retard
            self.retards.append(r)
            del self.retards[:-20]

    @property
    def retard(self) -> int:
        return int(sorted(self.retards)[len(self.retards) // 2]) if self.retards else 0

    def sur_horloge(self, t):
        self._avancer(t - self.retard)                                # heure du fil de donnees (flux differe compris)

    def _avancer(self, t):
        n = heure(t, TOKYO)
        d = n.date()
        self._calendrier(d.year)
        if d != self.jour:
            self.jour, self.faits, self.q = d, set(), 0
        if d not in self.jours:
            if self.cible:
                self._poser(0, "jour non gotobi : securite")
            return
        for jambe in ("entree", "fixing", "sortie"):
            if jambe in self.faits:
                continue
            h = datetime.combine(d, self.heures[jambe], TOKYO)
            if n < h:
                continue
            self.faits.add(jambe)
            if jambe == "sortie":
                if self.cible:
                    self._poser(0, "11:00 Tokyo : sortie")
                continue
            if n > h + self.tolerance:
                self.ctx.journal(f"jambe {jambe} manquee (moteur actif a {n:%H:%M} Tokyo)")
                if jambe == "fixing" and self.cible:
                    self._poser(0, "retournement manque : a plat")
                continue
            if not self.q or jambe == "entree":
                self.q = self._taille()
            if self.q <= 0:
                self.ctx.journal("taille nulle (capital trop faible pour un contrat, ou pas de cours) : jambe sautee")
                continue
            if jambe == "entree":
                self._poser(-self.q, "08:00 Tokyo : vente avant le fixing")
            else:
                self._poser(self.q, "09:55 Tokyo : achat apres le fixing")

    def apres_chauffe(self):
        self.cible = 0

    def etat(self):
        prochains = sorted(j for j in self.jours if self.jour is None or j >= self.jour)[:3]
        aujourd_hui = self.jour in self.jours
        suivant = next((j for j in prochains if j > self.jour or (j == self.jour and "entree" not in self.faits)), None) if self.jour else None
        entree = None
        if suivant is not None:
            h = datetime.combine(suivant, self.heures["entree"], TOKYO)
            entree = f"{h:%Y-%m-%d %H:%M} Tokyo ({h.astimezone(ZoneInfo('Europe/Paris')):%d/%m %H:%M} Paris)"
        try:
            estimee = self._taille()
        except Exception:                                                 # noqa: BLE001
            estimee = None
        return dict(jour_tokyo=str(self.jour), jour_gotobi_a_tokyo=aujourd_hui, jambes_faites=sorted(self.faits),
                    contrats=self.q if aujourd_hui else 0, cible=self.cible, prochaine_entree=entree,
                    taille_estimee=estimee, retard_flux_min=round(self.retard / 60_000, 1), prochains_jours=[str(j) for j in prochains])
