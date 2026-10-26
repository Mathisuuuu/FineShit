"""Groupe en direct.

    python -m nexus.live                      moteur en direct (NinjaTrader ouvert, AddOn NexusPasserelle compile)
    python -m nexus.live --verifier           parite avec la recherche sur les donnees Cotations (S1, Gotobi)
    python -m nexus.live --essai              essai de bout en bout avec une fausse passerelle (sans NinjaTrader)

Le registre (nexus/live/groupe.json) est relu toutes les 5 s : ajouter, retirer ou desactiver une strategie ne
demande aucun redemarrage. Etat en direct : Dashboard/donnees/live.json (page « Groupe en direct » du tableau de
bord) ; journal : Python/.cache/live/journal_AAAAMMJJ.jsonl.
"""
from __future__ import annotations

import argparse
import queue
import sys
import time

from .client import ClientPasserelle
from .moteur import REGISTRE, Moteur
from .protocole import PORT


def lancer(registre: str = REGISTRE, hote: str = "127.0.0.1", port: int = PORT) -> None:
    file: queue.Queue = queue.Queue()
    moteur = Moteur(registre)
    vu = {"t": time.time()}
    client = ClientPasserelle(file.put, hote, port, vivant=lambda: time.time() - vu["t"] < 30)
    moteur.lien = client
    moteur.journal(f"moteur demarre ; registre {registre} ; passerelle {hote}:{port}")
    moteur.charger_registre()
    client.demarrer()
    dernier = 0.0
    try:
        while True:
            try:
                m = file.get(timeout=0.2)
                moteur.sur_message(m)
                for _ in range(5000):
                    moteur.sur_message(file.get_nowait())
            except queue.Empty:
                pass
            maintenant = time.time()
            if maintenant - dernier >= 1.0:
                dernier = maintenant
                moteur.tic()
            vu["t"] = maintenant
    except KeyboardInterrupt:
        moteur.journal("arret demande (Ctrl+C) : NinjaTrader met tout a plat a la deconnexion")
    finally:
        client.arreter()
        moteur.passerelle["connecte"] = False
        moteur.ecrire_etat()


def main(argv=None) -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(prog="python -m nexus.live", description="Groupe en direct sur NinjaTrader (passerelle NexusPasserelle).")
    ap.add_argument("--registre", default=REGISTRE)
    ap.add_argument("--hote", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=PORT)
    ap.add_argument("--verifier", action="store_true", help="parite avec la recherche (donnees Cotations)")
    ap.add_argument("--cotations", default=None)
    ap.add_argument("--debut", default=None, help="debut du rejeu de --verifier (AAAA-MM-JJ)")
    ap.add_argument("--essai", action="store_true", help="essai de bout en bout avec une fausse passerelle")
    a = ap.parse_args(argv)
    if a.verifier:
        from . import verification as V
        V.main(a.cotations or V.COTATIONS, a.debut)
    elif a.essai:
        from .essai import essai
        essai()
    else:
        lancer(a.registre, a.hote, a.port)


if __name__ == "__main__":
    main()
