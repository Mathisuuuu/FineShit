"""Protocole de la passerelle NinjaTrader (AddOns/NexusPasserelle.cs).

TCP sur 127.0.0.1 (port 51888 par defaut), une ligne JSON UTF-8 par message, champ "type" obligatoire.

Python -> NinjaTrader
  hello       {client, version}
  subscribe   {id, instrument, barres}        barres 1 minute ; "NQ" seul = echeance courante (calendrier NinjaTrader)
  unsubscribe {id}
  target      {instrument, qty, ref}          position CIBLE signee (la passerelle passe les ordres au marche)
  flatten     {}                              toutes les cibles a 0
  heartbeat   {t}                             toutes les 5 s ; sans message pendant delai_coeur_s, tout est mis a plat
  status      {}
  etat_groupe {suspension, strategies: [{nom, actif, statut, cibles, resume, erreur}]}   toutes les 2 s (fenetre Groupe)

NinjaTrader -> Python
  hello        {compte, compte_trouve, simulation, coupure_et, reprise_et, max_contrats, ...}
  subscribed   {id, instrument, point_value, tick}
  history      {id, barres: [[t_fin, o, h, l, c, v], ...]}   barres closes, historique de chauffe (paquets de 500)
  history_done {id, n}
  bar          {id, b: [t_fin, o, h, l, c, v], horloge?}     une barre close, une seule fois
  target_ack   {instrument, demande, qty, plafond, ref, verrou}
  execution    {instrument, qty, prix, t, ordre, nom}
  order        {instrument, ordre, etat, rempli, prix_moyen, texte}
  position     {instrument, qty, prix_moyen}
  heartbeat    {t, verrou, positions, cibles, valeur_liquidative, resultat_jour}
  guard        {motif}                       verrou pose ("coupure", "perte du jour", "inactif"...) ou "aucun"
  error        {msg}
  commande     {action, nom, source}         fenetre Groupe : action = activer | desactiver (Python modifie groupe.json)

t_fin : fin de la barre en millisecondes UTC (la barre 9:30-9:31 de New York porte 9:31).
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import NamedTuple

PORT = 51888
VERSION = 1
MINUTE_MS = 60_000


class Barre(NamedTuple):
    t: int          # fin de la barre, ms UTC
    o: float
    h: float
    l: float
    c: float
    v: float

    @property
    def debut(self) -> int:
        return self.t - MINUTE_MS


def barre(x) -> Barre:
    return Barre(int(x[0]), float(x[1]), float(x[2]), float(x[3]), float(x[4]), float(x[5]))


def encoder(msg: dict) -> bytes:
    return (json.dumps(msg, separators=(",", ":"), ensure_ascii=False) + "\n").encode("utf-8")


def decoder(ligne: bytes | str) -> dict:
    if isinstance(ligne, bytes):
        ligne = ligne.decode("utf-8")
    m = json.loads(ligne)
    if not isinstance(m, dict) or "type" not in m:
        raise ValueError("message sans type")
    return m


def racine(nom: str) -> str:
    """'MNQ 12-26' -> 'MNQ' ; 'MNQ' -> 'MNQ'."""
    return str(nom).strip().split(" ")[0]


def heure(t_ms: int, tz) -> datetime:
    """Instant (ms UTC) -> datetime dans le fuseau tz (zoneinfo)."""
    return datetime.fromtimestamp(t_ms / 1000.0, tz)


def ms(dt: datetime) -> int:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return int(round(dt.timestamp() * 1000))
