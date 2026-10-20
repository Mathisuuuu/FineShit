"""Essai de bout en bout sans NinjaTrader : vrai client TCP + vrai moteur + fausse passerelle (rejeu.FaussePasserelleTCP).

    python -m nexus.live --essai

Scenario (registre temporaire, horloge simulee) :
  1. le Groupe demarre avec la strategie A sur ESSAI ; historique de chauffe servi par la passerelle ;
  2. barres en direct : A fixe ses cibles, la passerelle les execute a l ouverture de la barre suivante ;
  3. B est AJOUTEE au registre pendant que tout tourne : abonnement, chauffe et cibles additionnees a celles de A ;
  4. A est RETIREE : seule la cible de B reste ;
  5. fenetre Groupe de NinjaTrader : etat du Groupe recu, B desactivee puis reactivee par commande (groupe.json modifie) ;
  6. garde-fou « perte du jour » : toutes les cibles a 0 jusqu a la seance suivante.
"""
from __future__ import annotations

import json
import os
import queue
import tempfile
import threading
import time

import numpy as np
import pandas as pd

from .client import ClientPasserelle
from .moteur import Moteur
from .protocole import MINUTE_MS, Barre
from .rejeu import FaussePasserelleTCP
from .strategie import StrategieLive


class StrategieEssai(StrategieLive):
    """Cible = +q si la derniere cloture depasse la precedente, -q sinon (essai de plomberie uniquement)."""

    def __init__(self, nom, params, ctx):
        super().__init__(nom, params, ctx)
        self.inst = self.params.get("instrument", "ESSAI")
        self.q = int(self.params.get("q", 1))
        self.prec = None
        self.vues = 0

    def abonnements(self):
        return {self.inst: int(self.params.get("barres_chauffe", 20))}

    def sur_barre(self, instrument, b):
        self.vues += 1
        if self.prec is not None:
            self.ctx.cible(self.inst, self.q if b.c > self.prec else -self.q, "essai")
        self.prec = b.c

    def etat(self):
        return dict(barres_vues=self.vues)


def _barres(n: int, debut: str = "2026-10-19 14:00", graine: int = 3) -> pd.DataFrame:
    rng = np.random.default_rng(graine)
    c = 100 + np.cumsum(rng.normal(0, 0.2, n))
    idx = pd.date_range(debut, periods=n, freq="1min", tz="UTC")
    return pd.DataFrame(dict(open=np.r_[100.0, c[:-1]], high=c + 0.1, low=c - 0.1, close=c, volume=10.0), index=idx)


def _attendre(cond, delai: float = 5.0) -> bool:
    fin = time.time() + delai
    while time.time() < fin:
        if cond():
            return True
        time.sleep(0.02)
    return cond()


def essai(log=print) -> bool:
    df = _barres(60)
    hist, vivant = df.iloc[:30], df.iloc[30:]
    srv = FaussePasserelleTCP({"ESSAI": hist})
    dossier = tempfile.mkdtemp(prefix="nexus_live_essai_")
    reg = os.path.join(dossier, "groupe.json")
    spec = lambda nom, q: dict(nom=nom, classe="nexus.live.essai:StrategieEssai", params=dict(instrument="ESSAI", q=q))

    def ecrire(strategies):
        with open(reg, "w", encoding="utf-8") as fh:
            json.dump({"strategies": strategies}, fh)
        os.utime(reg, (time.time() + len(strategies), time.time() + len(strategies)))   # mtime change a coup sur

    ecrire([spec("A", 1)])
    simt = {"t": int(hist.index[-1].value // 1_000_000) + MINUTE_MS}
    file: queue.Queue = queue.Queue()
    m = Moteur(reg, horloge=lambda: simt["t"], etat=os.path.join(dossier, "live.json"), journal_dir=dossier, log=None)
    client = ClientPasserelle(file.put, "127.0.0.1", srv.port, log=lambda *_: None)
    m.lien = client
    arret = threading.Event()

    def boucle():
        m.charger_registre()
        while not arret.is_set():
            try:
                m.sur_message(file.get(timeout=0.05))
                while True:
                    m.sur_message(file.get_nowait())
            except queue.Empty:
                pass
            m._prochain_registre = 0                                  # registre relu a chaque tour (essai accelere)
            m.tic()

    f = threading.Thread(target=boucle, daemon=True)
    f.start()
    client.demarrer()
    resultats = []

    def verifier(nom, ok):
        resultats.append((nom, bool(ok)))
        log(f"  [{'ok' if ok else 'ECHEC'}] {nom}")

    try:
        verifier("connexion, hello et abonnement", _attendre(lambda: "ESSAI" in srv.abonnes and m.entrees.get("A") is not None
                                                                     and m.entrees["A"].statut == "active"))
        verifier("chauffe sur les 20 barres d historique demandees", m.entrees["A"].strategie.vues == 20)
        rows = list(vivant.itertuples())

        def pousser(r):
            b = Barre(int(r.Index.value // 1_000_000) + MINUTE_MS, r.open, r.high, r.low, r.close, r.volume)
            simt["t"] = b.t
            srv.pousser("ESSAI", b)
            _attendre(lambda: m.abos["ESSAI"].dernier_t >= b.t)
            time.sleep(0.05)

        for r in rows[:10]:
            pousser(r)
        verifier("cibles de A envoyees et executees", _attendre(lambda: abs(srv.cibles.get("ESSAI", 0)) == 1) and len(srv.executions) >= 1)
        ecrire([spec("A", 1), spec("B", 2)])
        verifier("B ajoutee a chaud : chargee et chauffee", _attendre(lambda: m.entrees.get("B") is not None and m.entrees["B"].statut == "active"))
        for r in rows[10:15]:
            pousser(r)
        verifier("cible nette = A + B", _attendre(lambda: abs(srv.cibles.get("ESSAI", 0)) == 3))
        ecrire([spec("B", 2)])
        verifier("A retiree : cible nette = B seule", _attendre(lambda: "A" not in m.entrees and abs(srv.cibles.get("ESSAI", 0)) == 2))
        verifier("fenetre Groupe : etat du Groupe recu", _attendre(lambda: (srv.etat_groupe() or {}).get("strategies", [{}])[0].get("nom") == "B"))
        srv.commande("desactiver", "B")
        lu = lambda: json.load(open(reg, encoding="utf-8"))["strategies"][0].get("actif")
        verifier("fenetre Groupe : B desactivee (groupe.json, cible 0)", _attendre(lambda: "B" not in m.entrees and srv.cibles.get("ESSAI", 1) == 0 and lu() is False))
        verifier("fenetre Groupe : etat « desactivee » renvoye", _attendre(lambda: any(x.get("statut") == "desactivee" for x in (srv.etat_groupe() or {}).get("strategies", []))))
        srv.commande("activer", "B")
        verifier("fenetre Groupe : B reactivee", _attendre(lambda: "B" in m.entrees and m.entrees["B"].statut == "active" and lu() is True))
        for r in rows[15:17]:
            pousser(r)
        verifier("B reprend ses cibles", _attendre(lambda: abs(srv.cibles.get("ESSAI", 0)) == 2))
        srv.garde("perte du jour")
        verifier("garde-fou perte du jour : cibles a 0", _attendre(lambda: srv.cibles.get("ESSAI", 1) == 0 and m.suspension == "perte du jour"))
        for r in rows[17:20]:
            pousser(r)
        verifier("suspension tenue jusqu a la seance suivante", srv.cibles.get("ESSAI", 1) == 0)
        verifier("etat ecrit (live.json)", _attendre(lambda: os.path.exists(os.path.join(dossier, "live.json"))))
    finally:
        arret.set()
        client.arreter()
        srv.fermer()
    ok = all(x for _, x in resultats)
    log(f"essai de bout en bout : {'REUSSI' if ok else 'ECHEC'} ({sum(x for _, x in resultats)}/{len(resultats)})")
    return ok
