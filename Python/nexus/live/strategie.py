"""Base des strategies du Groupe en direct.

Une strategie ne parle jamais a NinjaTrader : elle lit des barres 1 minute closes (sur_barre) et l horloge
(sur_horloge), et fixe des POSITIONS CIBLES par instrument (self.ctx.cible). Le moteur additionne les cibles de
toutes les strategies par instrument et envoie la cible nette a la passerelle.

Ajouter une strategie au Groupe = un fichier Python avec une classe derivee de StrategieLive + une ligne dans
nexus/live/groupe.json ; le moteur la charge sans redemarrer (ni lui, ni NinjaTrader).

    class MaStrategie(StrategieLive):
        def abonnements(self):            # instruments dont il faut les barres, et combien pour la chauffe
            return {"NQ": 5000}
        def sur_barre(self, instrument, b):   # b : Barre (t = fin de barre en ms UTC, o, h, l, c, v)
            ...
            self.ctx.cible("MNQ", 2, "cassure")   # position voulue, signee ; 0 = a plat

Chauffe : au chargement, le moteur rejoue l historique recu de NinjaTrader dans sur_barre (self.ctx.en_chauffe
vaut True) ; les cibles fixees pendant la chauffe sont ignorees, la strategie agit au point de decision suivant.
"""
from __future__ import annotations

from .protocole import Barre

# valeur du point par racine (pour les tailles) ; la passerelle donne celle des instruments abonnes
POINTS = {"NQ": 20.0, "MNQ": 2.0, "ES": 50.0, "MES": 5.0, "YM": 5.0, "MYM": 0.5, "RTY": 50.0, "M2K": 5.0,
          "6J": 12_500_000.0, "MJY": 1_250_000.0, "6E": 125_000.0, "M6E": 12_500.0, "GC": 100.0, "MGC": 10.0}


class StrategieLive:
    """Classe de base. Les parametres viennent de groupe.json (cle "params")."""

    def __init__(self, nom: str, params: dict, ctx):
        self.nom = nom
        self.params = dict(params or {})
        self.ctx = ctx

    # --- a redefinir -------------------------------------------------------------------------------------------
    def abonnements(self) -> dict[str, int]:
        """{instrument: nombre de barres 1 minute de chauffe}."""
        return {}

    def sur_barre(self, instrument: str, b: Barre) -> None:
        """Barre close de `instrument`."""

    def sur_horloge(self, t: int) -> None:
        """Appel chaque seconde en direct (chaque minute en rejeu) ; t = ms UTC."""

    def apres_chauffe(self) -> None:
        """Fin de la chauffe : la strategie est reputee a plat."""

    def etat(self) -> dict:
        """Etat lisible pour le tableau de bord (live.json)."""
        return {}

    def arreter(self) -> None:
        """Retrait du Groupe."""

    # --- outils ------------------------------------------------------------------------------------------------
    def point(self, instrument: str) -> float:
        info = self.ctx.info(instrument) or {}
        pv = self.params.get("point") or info.get("point_value") or POINTS.get(instrument.split(" ")[0])
        if not pv:
            raise ValueError(f"valeur du point inconnue pour {instrument} : ajouter \"point\" aux parametres")
        return float(pv)
