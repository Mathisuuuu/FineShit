"""Client TCP de la passerelle NinjaTrader : reconnexion automatique, battement de coeur, file de messages.

Les messages recus sont deposes dans `depot` (ex. queue.Queue.put) ; le moteur les traite dans son fil principal.
Messages internes ajoutes : {"type": "_connecte"} et {"type": "_deconnecte"}.
Le battement de coeur part d un fil separe, mais seulement si `vivant()` est vrai (boucle principale du moteur
active depuis moins de 30 s) : si le moteur se bloque, NinjaTrader cesse de recevoir le coeur et met tout a plat.
"""
from __future__ import annotations

import socket
import threading
import time

from .protocole import PORT, decoder, encoder


class ClientPasserelle:
    def __init__(self, depot, hote: str = "127.0.0.1", port: int = PORT, vivant=None, log=print):
        self.depot = depot
        self.hote, self.port = hote, int(port)
        self.vivant = vivant or (lambda: True)
        self.log = log
        self._sock: socket.socket | None = None
        self._verrou = threading.Lock()
        self._arret = threading.Event()
        self._fils: list[threading.Thread] = []

    def demarrer(self) -> None:
        for cible, nom in ((self._boucle, "passerelle-lecture"), (self._coeur, "passerelle-coeur")):
            f = threading.Thread(target=cible, name=nom, daemon=True)
            f.start()
            self._fils.append(f)

    def arreter(self) -> None:
        self._arret.set()
        self._fermer()

    @property
    def connecte(self) -> bool:
        return self._sock is not None

    def envoyer(self, msg: dict) -> bool:
        with self._verrou:
            s = self._sock
            if s is None:
                return False
            try:
                s.sendall(encoder(msg))
                return True
            except OSError:
                pass
        self._fermer()
        return False

    def _fermer(self) -> None:
        with self._verrou:
            s, self._sock = self._sock, None
        if s is not None:
            try:
                s.close()
            except OSError:
                pass

    def _boucle(self) -> None:
        attente, deja_dit = 1.0, False
        while not self._arret.is_set():
            try:
                s = socket.create_connection((self.hote, self.port), timeout=5)
            except OSError:
                if not deja_dit:
                    self.log(f"passerelle NinjaTrader injoignable sur {self.hote}:{self.port} (NinjaTrader ouvert, AddOn compile ?) ; nouvel essai...")
                    deja_dit = True
                self._arret.wait(attente)
                attente = min(attente * 2, 15.0)
                continue
            if s.getsockname() == s.getpeername():
                # auto-connexion TCP : sans passerelle a l ecoute, Windows peut donner au client le port vise lui-meme ;
                # le client parlerait a lui-meme et bloquerait le port de NinjaTrader
                s.close()
                self._arret.wait(attente)
                attente = min(attente * 2, 15.0)
                continue
            attente, deja_dit = 1.0, False
            s.settimeout(None)
            s.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            with self._verrou:
                self._sock = s
            self.depot({"type": "_connecte"})
            tampon = b""
            try:
                while not self._arret.is_set():
                    morceau = s.recv(65536)
                    if not morceau:
                        break
                    tampon += morceau
                    while b"\n" in tampon:
                        ligne, tampon = tampon.split(b"\n", 1)
                        if ligne.strip():
                            try:
                                self.depot(decoder(ligne))
                            except ValueError as ex:
                                self.log(f"message illisible de la passerelle : {ex}")
            except OSError:
                pass
            self._fermer()
            self.depot({"type": "_deconnecte"})
            self._arret.wait(1.0)

    def _coeur(self) -> None:
        while not self._arret.wait(5.0):
            if self.connecte and self.vivant():
                self.envoyer({"type": "heartbeat", "t": int(time.time() * 1000)})
