"""Rejeu de l historique dans le moteur en direct, et fausse passerelle TCP pour les essais.

rejouer(...) : passerelle simulee en memoire. Les barres de tous les instruments sont donnees au moteur dans
l ordre du temps, comme en direct ; une cible modifiee a l instant t est executee a l OUVERTURE de la premiere
barre de l instrument qui commence a t ou apres (en direct : ordre au marche envoye a t). L horloge (sur_horloge)
bat a chaque minute ronde, y compris pendant les trous de cotation (ex. reouverture de 18:00 a New York).
Sert a verifier que les strategies en direct reproduisent les trades de la recherche (python -m nexus.live --verifier).

FaussePasserelleTCP : serveur qui parle le protocole de NexusPasserelle.cs (historique, barres, cibles executees a
l ouverture de la barre suivante, positions, battement de coeur) pour essayer le moteur de bout en bout sans
NinjaTrader.
"""
from __future__ import annotations

import socket
import threading
from collections import deque

import numpy as np
import pandas as pd

from .moteur import Moteur
from .protocole import MINUTE_MS, Barre, decoder, encoder, racine


def tableau_barres(df: pd.DataFrame) -> np.ndarray:
    """DataFrame (index = DEBUT de barre, UTC ; colonnes open, high, low, close, volume) -> tableau (t_fin ms, o, h, l, c, v)."""
    idx = pd.DatetimeIndex(df.index)
    if idx.tz is None:
        idx = idx.tz_localize("UTC")
    t = idx.tz_convert("UTC").as_unit("ms").asi8 + MINUTE_MS
    return np.column_stack([t.astype(float), df["open"].to_numpy(float), df["high"].to_numpy(float), df["low"].to_numpy(float),
                            df["close"].to_numpy(float), df["volume"].to_numpy(float)])


class SimPasserelle:
    """Passerelle en memoire : repond aux abonnements (sans historique) et execute les cibles a l ouverture suivante."""

    def __init__(self):
        self.t = 0
        self.moteur: Moteur | None = None
        self.file: deque = deque()
        self.cibles: dict[str, int] = {}
        self.t_cible: dict[str, int] = {}
        self.positions: dict[str, int] = {}
        self.executions: list[dict] = []
        self.refs: dict[str, str] = {}

    def envoyer(self, msg: dict) -> None:
        t = msg.get("type")
        if t == "hello":
            self.file.append(dict(type="hello", compte="Sim101", compte_trouve=True, simulation=True, coupure_et="16:10",
                                  reprise_et="18:00", max_contrats={}, max_contrats_defaut=999))
        elif t == "subscribe":
            self.file.append(dict(type="subscribed", id=msg["id"], instrument=msg["instrument"]))
            self.file.append(dict(type="history_done", id=msg["id"], n=0))
        elif t == "target":
            i = racine(msg["instrument"])
            self.cibles[i] = int(msg["qty"])
            self.t_cible[i] = self.t
            self.refs[i] = msg.get("ref", "")

    def vider(self) -> None:
        while self.file:
            self.moteur.sur_message(self.file.popleft())

    def executer(self, instrument: str, t_debut: int, prix: float) -> None:
        """Cibles fixees avant (ou a) t_debut executees au prix d ouverture de la barre qui commence a t_debut."""
        i = racine(instrument)
        if i not in self.cibles or self.t_cible.get(i, 0) > t_debut:
            return
        d = self.cibles[i] - self.positions.get(i, 0)
        if d == 0:
            return
        self.positions[i] = self.cibles[i]
        self.executions.append(dict(t=t_debut, instrument=i, qty=d, prix=prix, position=self.positions[i], ref=self.refs.get(i, "")))
        self.file.append(dict(type="position", instrument=i, qty=self.positions[i]))


def rejouer(registre: dict, donnees: dict[str, pd.DataFrame], negocie: dict[str, str] | None = None, horloge: bool = True,
            log=None) -> tuple[pd.DataFrame, Moteur]:
    """Rejoue `donnees` ({instrument: barres 1 minute}) dans le moteur avec les strategies de `registre`.

    negocie : instrument negocie -> instrument dont les barres servent de prix d execution (ex. {"MNQ": "NQ"}).
    Retour : executions (t = debut de la barre d execution, ms UTC) et le moteur (etat final des strategies)."""
    sim = SimPasserelle()
    m = Moteur(registre, lien=sim, horloge=lambda: sim.t, etat=None, journal_dir=None, surveiller=False, log=log)
    sim.moteur = m
    noms = sorted(donnees)
    tabs = [tableau_barres(donnees[i]) for i in noms]
    if not tabs or sum(len(x) for x in tabs) == 0:
        raise ValueError("aucune barre a rejouer")
    t0 = int(min(x[0, 0] for x in tabs if len(x))) - MINUTE_MS
    sim.t = t0
    m.maintenant = t0
    m.charger_registre()
    sim.file.append({"type": "_connecte"})
    sim.vider()
    sim.vider()
    # executions : l instrument negocie s execute aux prix de l instrument de donnees
    prix_de = {}
    for neg, src in (negocie or {}).items():
        prix_de.setdefault(src, []).append(neg)
    tout = np.concatenate([np.column_stack([x, np.full(len(x), k, float)]) for k, x in enumerate(tabs)])
    ordre = np.lexsort((tout[:, 6], tout[:, 0]))
    dernier_tic = t0
    for r in tout[ordre]:
        t_fin = int(r[0])
        inst = noms[int(r[6])]
        debut = t_fin - MINUTE_MS
        if horloge and debut > dernier_tic:
            tt = dernier_tic + MINUTE_MS
            if debut - dernier_tic > 4 * 24 * 60 * MINUTE_MS:
                tt = debut
            while tt <= debut:
                sim.t = tt
                m.tic(tt)
                sim.vider()
                tt += MINUTE_MS
            dernier_tic = debut
        sim.t = debut
        sim.executer(inst, debut, float(r[1]))
        for neg in prix_de.get(inst, ()):
            sim.executer(neg, debut, float(r[1]))
        sim.vider()
        sim.t = t_fin
        m.sur_barre(inst, Barre(t_fin, float(r[1]), float(r[2]), float(r[3]), float(r[4]), float(r[5])))
        sim.vider()
        if horloge and t_fin > dernier_tic:
            m.tic(t_fin)
            sim.vider()
            dernier_tic = t_fin
    ex = pd.DataFrame(sim.executions, columns=["t", "instrument", "qty", "prix", "position", "ref"])
    if len(ex):
        ex["heure_utc"] = pd.to_datetime(ex["t"], unit="ms", utc=True)
    return ex, m


class FaussePasserelleTCP:
    """Serveur TCP local qui imite NexusPasserelle.cs (un client a la fois).

    historique : {instrument: DataFrame de barres (index = debut de barre UTC)} servi a l abonnement ;
    pousser(instrument, barre) envoie une barre close et execute d abord, a son ouverture, la cible en attente."""

    def __init__(self, historique: dict[str, pd.DataFrame] | None = None, port: int = 0):
        self.historique = historique or {}
        self.srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.srv.bind(("127.0.0.1", port))
        self.srv.listen(1)
        self.port = self.srv.getsockname()[1]
        self.conn: socket.socket | None = None
        self.recus: list[dict] = []
        self.cibles: dict[str, int] = {}
        self.positions: dict[str, int] = {}
        self.executions: list[dict] = []
        self.abonnes: dict[str, str] = {}
        self._verrou = threading.Lock()
        self._fini = threading.Event()
        threading.Thread(target=self._servir, daemon=True).start()

    def _envoyer(self, msg: dict) -> None:
        with self._verrou:
            if self.conn is not None:
                try:
                    self.conn.sendall(encoder(msg))
                except OSError:
                    self.conn = None

    def _servir(self) -> None:
        while not self._fini.is_set():
            try:
                c, _ = self.srv.accept()
            except OSError:
                return
            with self._verrou:
                self.conn = c
            tampon = b""
            try:
                while True:
                    x = c.recv(65536)
                    if not x:
                        break
                    tampon += x
                    while b"\n" in tampon:
                        ligne, tampon = tampon.split(b"\n", 1)
                        if ligne.strip():
                            self._traiter(decoder(ligne))
            except OSError:
                pass
            with self._verrou:
                self.conn = None
            self.cibles = {k: 0 for k in self.cibles}          # comme NinjaTrader : deconnexion -> tout a plat

    def _traiter(self, m: dict) -> None:
        self.recus.append(m)
        t = m["type"]
        if t == "hello":
            self._envoyer(dict(type="hello", passerelle="FaussePasserelleTCP", version=1, compte="Sim101", compte_trouve=True, simulation=True,
                               coupure_et="16:10", reprise_et="18:00", max_contrats={"MNQ": 10, "6J": 2}, max_contrats_defaut=1))
        elif t == "subscribe":
            i = m["id"]
            self.abonnes[i] = m["instrument"]
            self._envoyer(dict(type="subscribed", id=i, instrument=f"{m['instrument']} 12-26", point_value=None, tick=None))
            df = self.historique.get(m["instrument"])
            n = 0
            if df is not None and len(df):
                tab = tableau_barres(df.iloc[-int(m.get("barres", len(df))):])
                for k in range(0, len(tab), 500):
                    self._envoyer(dict(type="history", id=i, barres=[[int(r[0]), *map(float, r[1:])] for r in tab[k:k + 500]]))
                n = len(tab)
            self._envoyer(dict(type="history_done", id=i, n=n))
        elif t == "target":
            i = racine(m["instrument"])
            self.cibles[i] = int(m["qty"])
            self._envoyer(dict(type="target_ack", instrument=f"{i} 12-26", demande=m["qty"], qty=m["qty"], plafond=10, ref=m.get("ref", ""), verrou=""))

    def pousser(self, instrument: str, b: Barre, negocies: tuple[str, ...] = ()) -> None:
        for i in (instrument, *negocies):
            d = self.cibles.get(i, 0) - self.positions.get(i, 0)
            if d:
                self.positions[i] = self.cibles[i]
                x = dict(t=b.debut, instrument=i, qty=d, prix=b.o)
                self.executions.append(x)
                self._envoyer(dict(type="execution", instrument=f"{i} 12-26", qty=d, prix=b.o, t=b.debut, ordre=str(len(self.executions)), nom="Nexus"))
                self._envoyer(dict(type="position", instrument=f"{i} 12-26", qty=self.positions[i], prix_moyen=b.o))
        self._envoyer(dict(type="bar", id=instrument, b=list(b)))

    def coeur(self, verrou: str = "") -> None:
        self._envoyer(dict(type="heartbeat", t=0, verrou=verrou, positions={f"{k} 12-26": v for k, v in self.positions.items()},
                           cibles={f"{k} 12-26": v for k, v in self.cibles.items()}, valeur_liquidative=100000.0, resultat_jour=0.0))

    def garde(self, motif: str) -> None:
        self._envoyer(dict(type="guard", motif=motif))

    def commande(self, action: str, nom: str) -> None:
        """Bouton Activer / Desactiver de la fenetre Groupe."""
        self._envoyer(dict(type="commande", action=action, nom=nom, source="NinjaTrader"))

    def etat_groupe(self) -> dict | None:
        x = [m for m in self.recus if m.get("type") == "etat_groupe"]
        return x[-1] if x else None

    def fermer(self) -> None:
        self._fini.set()
        try:
            self.srv.close()
        except OSError:
            pass
        with self._verrou:
            if self.conn is not None:
                try:
                    self.conn.close()
                except OSError:
                    pass
