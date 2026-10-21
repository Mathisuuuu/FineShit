"""Moteur du Groupe en direct : registre des strategies recharge a chaud, chauffe, cibles nettes par instrument.

Le moteur recoit les messages de la passerelle (sur_message), appelle les strategies, additionne leurs cibles
par instrument et envoie la cible nette. Il ne decide rien lui-meme, sauf :
  - une strategie qui leve une exception passe en "erreur" et ses cibles a 0 (les autres continuent) ;
  - verrou "perte du jour" ou "interrupteur" de la passerelle : toutes les cibles a 0 jusqu a la seance suivante
    (18:00 heure de New York), sans reprise automatique avant ;
  - plafond de contrats par strategie (parametre "max_contrats").

Registre (groupe.json) relu toutes les 5 s :
  - entree nouvelle ou reactivee : chargee, abonnee, chauffee, puis active ;
  - entree retiree ou "actif": false : cibles a 0 immediatement, puis supprimee ;
  - entree modifiee (parametres, ou fichier de la classe) : remplacee des que ses cibles sont toutes a 0
    (jamais de sortie forcee d une position en cours pour un changement de reglage).

Donnees NinjaTrader conservees (dossier .cache/live, si journal_dir) :
  - archive/<instrument>.parquet : historique 1 minute le plus long que NinjaTrader fournit (demande une fois par jour,
    apres "heure_et" de la cle "archive" du registre, ou au demarrage s il manque), puis lancement du rapport du Groupe
    (python -m nexus.live.rapport : rejeu des strategies + vectorbt -> Dashboard/donnees/groupe.json) ;
  - cibles.jsonl, ordres.jsonl, executions.jsonl : toutes les cibles envoyees et tous les ordres et executions du compte.

Fenetre « Groupe » de NinjaTrader : le moteur lui envoie l etat du Groupe toutes les 2 s (etat_groupe) et recoit ses
commandes (commande activer / desactiver), appliquees en modifiant "actif" dans groupe.json : le registre reste la
seule source de verite, que la modification vienne de NinjaTrader ou d un editeur de texte.
"""
from __future__ import annotations

import importlib
import importlib.util
import json
import os
import subprocess
import sys
import time
import traceback
from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import numpy as np

from .protocole import MINUTE_MS, Barre, barre, heure, ms, racine
from .strategie import StrategieLive

ICI = os.path.dirname(os.path.abspath(__file__))
PY_DIR = os.path.normpath(os.path.join(ICI, "..", ".."))
REGISTRE = os.path.join(ICI, "groupe.json")
ETAT = os.path.normpath(os.path.join(PY_DIR, "..", "Dashboard", "donnees", "live.json"))
JOURNAL = os.path.join(PY_DIR, ".cache", "live")
NY = ZoneInfo("America/New_York")
SUSPENSION = ("perte du jour", "interrupteur")


@dataclass
class Abo:
    instrument: str
    barres: int = 0                         # chauffe demandee a la passerelle
    demandees: int = 0                      # derniere demande envoyee
    historique: list = field(default_factory=list)
    tampon: list = field(default_factory=list)     # historique en cours de reception
    pret: bool = False
    dernier_t: int = 0
    info: dict = field(default_factory=dict)


@dataclass
class Entree:
    nom: str
    spec: dict
    signature: str
    strategie: StrategieLive | None = None
    ctx: "Contexte | None" = None
    statut: str = "chauffe"                 # chauffe | active | erreur
    cibles: dict = field(default_factory=dict)
    instruments: frozenset = frozenset()
    erreur: str = ""
    remplacement: dict | None = None


class Contexte:
    """Ce qu une strategie peut demander au moteur."""

    def __init__(self, moteur: "Moteur", nom: str):
        self._m = moteur
        self.nom = nom
        self.en_chauffe = False

    def cible(self, instrument: str, qty: int, motif: str = "") -> None:
        self._m._cible(self.nom, instrument, qty, motif)

    def maintenant(self) -> int:
        return self._m.maintenant

    def journal(self, texte: str, **donnees) -> None:
        if not self.en_chauffe:
            self._m.journal(texte, strategie=self.nom, **donnees)

    def info(self, instrument: str) -> dict:
        a = self._m.abos.get(instrument)
        return dict(a.info) if a else {}

    def derniere(self, instrument: str) -> Barre | None:
        a = self._m.abos.get(instrument)
        return a.historique[-1] if a and a.historique else None

    def valeur_liquidative(self) -> float | None:
        v = self._m.passerelle.get("valeur_liquidative")
        return float(v) if isinstance(v, (int, float)) else None


def _classe(chemin: str):
    """'nexus.live.strategies.s1:S1' -> classe ; le module est recharge si son fichier a change."""
    mod, _, nom = chemin.partition(":")
    if not nom:
        raise ValueError(f"classe attendue sous la forme module:Classe, recu {chemin!r}")
    if PY_DIR not in sys.path:
        sys.path.insert(0, PY_DIR)
    m = importlib.import_module(mod)
    f = getattr(m, "__file__", None)
    if f and os.path.exists(f) and getattr(m, "_nexus_mtime", None) not in (None, os.path.getmtime(f)):
        m = importlib.reload(m)
    if f and os.path.exists(f):
        m._nexus_mtime = os.path.getmtime(f)
    k = getattr(m, nom)
    if not (isinstance(k, type) and issubclass(k, StrategieLive)):
        raise TypeError(f"{chemin} n est pas une StrategieLive")
    return k


def _signature(spec: dict) -> str:
    mod = spec.get("classe", "").partition(":")[0]
    mt = 0.0
    try:
        spec_mod = importlib.util.find_spec(mod)
        if spec_mod and spec_mod.origin and os.path.exists(spec_mod.origin):
            mt = os.path.getmtime(spec_mod.origin)
    except (ImportError, ValueError):
        pass
    return json.dumps(dict(spec, _mtime=mt), sort_keys=True, ensure_ascii=False, default=str)


class Moteur:
    def __init__(self, registre=REGISTRE, lien=None, horloge=None, etat: str | None = ETAT,
                 journal_dir: str | None = JOURNAL, surveiller: bool = True, log=print):
        self.registre = registre                    # chemin de groupe.json, ou dict {"strategies": [...]}
        self.lien = lien                            # objet avec envoyer(dict)
        self.horloge = horloge or (lambda: int(time.time() * 1000))
        self.etat_path = etat
        self.journal_dir = journal_dir
        self.surveiller = surveiller
        self.log = log
        self.maintenant = self.horloge()
        self.entrees: dict[str, Entree] = {}
        self.abos: dict[str, Abo] = {}
        self.envoye: dict[str, int] = {}
        self.positions: dict[str, int] = {}
        self.passerelle: dict = dict(connecte=False)
        self.suspension = ""
        self.suspension_fin = 0
        self.lignes: deque = deque(maxlen=300)
        self.executions: deque = deque(maxlen=200)
        self._spec_registre = None
        self._mtime_registre = None
        self._prochain_registre = 0
        self._prochain_etat = 0
        self._erreur_registre = ""
        self._en_lot = 0
        self._prochain_groupe = 0
        self.archive_cfg = dict(barres=0, heure_et="16:20", rapport=True, intervalle_min=15)   # barres > 0 : historique demande a NinjaTrader
        self._archive_t: dict[str, int] = {}
        self._prochain_direct = 0
        self.archives: dict[str, dict] = {}
        self._rapport = None

    # ------------------------------------------------------------------ journal et etat
    def journal(self, texte: str, **donnees) -> None:
        t = self.maintenant
        ligne = dict(t=t, heure=heure(t, NY).strftime("%Y-%m-%d %H:%M:%S"), texte=texte, **donnees)
        self.lignes.append(ligne)
        if self.log:
            qui = f"[{donnees['strategie']}] " if donnees.get("strategie") else ""
            self.log(f"{ligne['heure']} ET  {qui}{texte}")
        if self.journal_dir:
            try:
                os.makedirs(self.journal_dir, exist_ok=True)
                f = os.path.join(self.journal_dir, f"journal_{heure(t, NY):%Y%m%d}.jsonl")
                with open(f, "a", encoding="utf-8") as fh:
                    fh.write(json.dumps(ligne, ensure_ascii=False) + "\n")
            except OSError:
                pass

    def ecrire_etat(self) -> None:
        if not self.etat_path:
            return
        net = defaultdict(int)
        for e in self.entrees.values():
            for i, q in e.cibles.items():
                net[i] += q
        strategies = []
        for e in self.entrees.values():
            try:
                et = e.strategie.etat() if e.strategie and e.statut == "active" else {}
            except Exception as ex:                                     # noqa: BLE001
                et = dict(erreur=repr(ex))
            strategies.append(dict(nom=e.nom, classe=e.spec.get("classe"), statut=e.statut, erreur=e.erreur,
                                   cibles=dict(e.cibles), params=e.spec.get("params", {}), etat=et,
                                   remplacement_en_attente=e.remplacement is not None,
                                   abonnements=sorted(e.strategie.abonnements()) if e.strategie else []))
        instruments = {}
        for i in sorted(set(self.abos) | set(self.envoye) | set(self.positions)):
            a = self.abos.get(i)
            d = a.historique[-1] if a and a.historique else None
            instruments[i] = dict(cible=self.envoye.get(i, 0), position=self.positions.get(i), nom=(a.info.get("instrument") if a else None),
                                  derniere_barre=(dict(t=d.t, heure=heure(d.t, NY).strftime("%Y-%m-%d %H:%M"), c=d.c) if d else None),
                                  pret=bool(a and a.pret))
        out = dict(genere=heure(self.horloge(), NY).strftime("%Y-%m-%d %H:%M:%S"), passerelle=self.passerelle,
                   suspension=self.suspension, strategies=strategies, instruments=instruments,
                   executions=list(self.executions)[-50:], journal=list(self.lignes)[-150:],
                   registre=self.registre if isinstance(self.registre, str) else None, erreur_registre=self._erreur_registre)
        try:
            os.makedirs(os.path.dirname(self.etat_path), exist_ok=True)
            tmp = self.etat_path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump(out, fh, ensure_ascii=False, indent=1, default=str)
            os.replace(tmp, self.etat_path)
        except OSError:
            pass

    # ------------------------------------------------------------------ registre
    def _lire_registre(self) -> list[dict] | None:
        if isinstance(self.registre, dict):
            return list(self.registre.get("strategies", []))
        try:
            mt = os.path.getmtime(self.registre)
            if mt == self._mtime_registre and self._spec_registre is not None:
                return self._spec_registre
            with open(self.registre, encoding="utf-8") as fh:
                d = json.load(fh)
            self._mtime_registre = mt
            self._spec_registre = list(d.get("strategies", []))
            if isinstance(d.get("archive"), dict):
                self.archive_cfg.update(d["archive"])
            if self._erreur_registre:
                self.journal("registre de nouveau lisible")
            self._erreur_registre = ""
            return self._spec_registre
        except (OSError, ValueError) as ex:
            msg = f"registre illisible ({ex}) : Groupe inchange"
            if msg != self._erreur_registre:
                self._erreur_registre = msg
                self.journal(msg)
            return None

    def charger_registre(self) -> None:
        specs = self._lire_registre()
        if specs is None:
            return
        voulues = {}
        for s in specs:
            nom = str(s.get("nom", "")).strip()
            if not nom or nom in voulues:
                if nom:
                    self.journal(f"nom en double dans le registre : {nom} (seule la premiere entree compte)")
                continue
            if s.get("actif", True):
                voulues[nom] = s
        avant = {n: (e.signature, e.statut) for n, e in self.entrees.items()}
        self._en_lot += 1
        try:
            for nom in list(self.entrees):
                if nom not in voulues:
                    self._retirer(nom, "retiree du registre ou desactivee")
            for nom, s in voulues.items():
                sig = _signature(s)
                e = self.entrees.get(nom)
                if e is None:
                    self._ajouter(s, sig)
                elif e.signature != sig:
                    if any(e.cibles.values()):
                        if e.remplacement is None or _signature(e.remplacement) != sig:
                            self.journal("modifiee : remplacement des que ses positions seront a plat", strategie=nom)
                        e.remplacement = s
                    else:
                        self._retirer(nom, "modifiee")
                        self._ajouter(s, sig)
        finally:
            self._en_lot -= 1
        self._abonner()
        self._pousser()
        if {n: (e.signature, e.statut) for n, e in self.entrees.items()} != avant:
            self._envoyer_etat_groupe()

    def _ajouter(self, spec: dict, sig: str) -> None:
        nom = spec["nom"]
        e = Entree(nom=nom, spec=spec, signature=sig)
        self.entrees[nom] = e
        try:
            k = _classe(spec["classe"])
            e.ctx = Contexte(self, nom)
            e.strategie = k(nom, spec.get("params", {}), e.ctx)
            besoins = e.strategie.abonnements()
            e.instruments = frozenset(besoins)
        except Exception as ex:                                         # noqa: BLE001
            e.statut, e.erreur = "erreur", f"chargement : {ex!r}"
            self.journal(f"chargement impossible : {ex!r}", strategie=nom)
            return
        for inst, n in besoins.items():
            a = self.abos.setdefault(inst, Abo(inst))
            if int(n) > a.barres:
                a.barres = int(n)
        self.journal(f"chargee ({spec['classe']}), abonnements {besoins}", strategie=nom)
        self._essayer_chauffe(e)

    def _retirer(self, nom: str, motif: str) -> None:
        e = self.entrees.pop(nom, None)
        if e is None:
            return
        if e.strategie:
            try:
                e.strategie.arreter()
            except Exception:                                            # noqa: BLE001
                pass
        self.journal(f"retiree ({motif}) ; ses cibles passent a 0", strategie=nom)
        self._pousser()

    # ------------------------------------------------------------------ abonnements et chauffe
    def _abonner(self) -> None:
        if not self.passerelle.get("connecte") or not self.passerelle.get("hello"):
            return
        for a in self.abos.values():
            if a.barres > a.demandees:
                a.demandees = a.barres
                a.pret = False
                self._envoyer(dict(type="subscribe", id=a.instrument, instrument=a.instrument, barres=a.barres))

    def _essayer_chauffe(self, e: Entree) -> None:
        if e.statut != "chauffe" or e.strategie is None:
            return
        besoins = e.strategie.abonnements()
        if not all(self.abos.get(i) and self.abos[i].pret and self.abos[i].demandees >= n for i, n in besoins.items()):
            return
        flux = sorted(((b.t, k, i, b) for k, i in enumerate(sorted(besoins)) for b in self.abos[i].historique), key=lambda x: (x[0], x[1]))
        e.ctx.en_chauffe = True
        try:
            for _, _, i, b in flux:
                e.strategie.sur_barre(i, b)
            e.ctx.en_chauffe = False
            e.cibles = {}
            e.strategie.apres_chauffe()
            e.statut = "active"
            self.journal(f"active apres chauffe sur {len(flux)} barres", strategie=e.nom)
        except Exception as ex:                                         # noqa: BLE001
            e.ctx.en_chauffe = False
            e.cibles = {}
            e.statut, e.erreur = "erreur", f"chauffe : {ex!r}"
            self.journal(f"erreur pendant la chauffe : {ex!r}\n{traceback.format_exc(limit=4)}", strategie=e.nom)
        self._envoyer_etat_groupe()

    # ------------------------------------------------------------------ cibles
    def _cible(self, nom: str, instrument: str, qty, motif: str) -> None:
        e = self.entrees.get(nom)
        if e is None or e.statut == "erreur":
            return
        q = int(round(float(qty)))
        if e.ctx and e.ctx.en_chauffe:
            e.cibles[instrument] = q
            return
        mx = e.spec.get("params", {}).get("max_contrats")
        if mx is not None and abs(q) > int(mx):
            self.journal(f"cible {instrument} {q} ecretee a {int(mx)} (max_contrats)", strategie=nom)
            q = int(mx) if q > 0 else -int(mx)
        if e.cibles.get(instrument, 0) != q:
            self.journal(f"cible {instrument} : {e.cibles.get(instrument, 0)} -> {q}" + (f" ({motif})" if motif else ""),
                         strategie=nom, instrument=instrument, qty=q, motif=motif)
        e.cibles[instrument] = q
        if not self._en_lot:
            self._pousser()

    def _pousser(self) -> None:
        net = defaultdict(int)
        qui = defaultdict(list)
        for e in self.entrees.values():
            if e.statut != "active":
                continue
            for i, q in e.cibles.items():
                net[i] += q
                if q:
                    qui[i].append(e.nom)
        for i in sorted(set(net) | set(self.envoye)):
            q = 0 if self.suspension else net.get(i, 0)
            if self.envoye.get(i) != q:
                self.envoye[i] = q
                self._envoyer(dict(type="target", instrument=i, qty=q, ref="+".join(sorted(qui[i]))))

    def _envoyer(self, msg: dict) -> None:
        if self.lien is not None:
            self.lien.envoyer(msg)
        if msg.get("type") == "target":
            self._consigner("cibles.jsonl", msg)

    def _consigner(self, fichier: str, m: dict) -> None:
        """Ajoute un message de la passerelle (ou une cible envoyee) au registre permanent des ordres."""
        if not self.journal_dir:
            return
        try:
            os.makedirs(self.journal_dir, exist_ok=True)
            x = dict(m, t_moteur=self.maintenant, heure_et=heure(self.maintenant, NY).strftime("%Y-%m-%d %H:%M:%S"))
            with open(os.path.join(self.journal_dir, fichier), "a", encoding="utf-8") as fh:
                fh.write(json.dumps(x, ensure_ascii=False) + "\n")
        except OSError:
            pass

    # ------------------------------------------------------------------ archive de l historique NinjaTrader
    @property
    def dossier_archive(self) -> str | None:
        return os.path.join(self.journal_dir, "archive") if self.journal_dir else None

    def _moment_archive(self) -> int:
        """Dernier instant ou l archive devait etre rafraichie (aujourd hui a heure_et ET, sinon la veille)."""
        n = heure(self.maintenant, NY)
        h, mi = (int(x) for x in str(self.archive_cfg.get("heure_et", "16:20")).split(":"))
        d = datetime(n.year, n.month, n.day, h, mi, tzinfo=NY)
        if n < d:
            d -= timedelta(days=1)
        return ms(d)

    def _verifier_archives(self) -> None:
        if not self.dossier_archive or not self.passerelle.get("hello") or not self.archive_cfg.get("barres"):
            return
        moment = self._moment_archive()
        for inst in list(self.abos):
            st = self.archives.get(inst, {})
            if st.get("etat") == "demande" and self.maintenant - st.get("depuis", 0) < 3_600_000:
                continue
            f = os.path.join(self.dossier_archive, f"{inst}.parquet")
            if os.path.exists(f) and os.path.getmtime(f) * 1000 >= moment:
                continue
            self.archives[inst] = dict(etat="demande", depuis=self.maintenant, morceaux=[])
            self._envoyer(dict(type="subscribe", id=f"archive:{inst}", instrument=inst, barres=int(self.archive_cfg["barres"])))
            self.journal(f"archive {inst} : historique 1 minute demande a NinjaTrader ({int(self.archive_cfg['barres']):,} barres au plus)")

    def _enregistrer_direct(self) -> None:
        """Forward test : toutes les intervalle_min minutes, ajoute a l archive les barres NinjaTrader recues en direct,
        consigne l etat du compte demo (compte.jsonl) et relance le rapport du Groupe."""
        if not self.dossier_archive or not self.passerelle.get("hello") or self.maintenant < self._prochain_direct:
            return
        if not self.abos or not all(a.pret for a in self.abos.values()):
            return                                                          # attendre l historique de chauffe
        self._prochain_direct = self.maintenant + int(self.archive_cfg.get("intervalle_min", 15)) * 60_000
        for inst, a in self.abos.items():
            neuves = [b for b in a.historique if b.t > self._archive_t.get(inst, 0)]
            if not neuves:
                continue
            try:
                self._ecrire_archive(inst, [np.array([[b.t, b.o, b.h, b.l, b.c, b.v] for b in neuves], dtype=float)])
                self._archive_t[inst] = neuves[-1].t
            except Exception as ex:                                     # noqa: BLE001
                self.journal(f"archive {inst} : ecriture impossible ({ex!r})")
        P = self.passerelle
        self._consigner("compte.jsonl", dict(type="compte", compte=P.get("compte"), valeur_liquidative=P.get("valeur_liquidative"),
                                             resultat_jour=P.get("resultat_jour"), verrou=P.get("verrou"),
                                             positions={k: v for k, v in self.positions.items() if v}))
        self._lancer_rapport()

    def _sur_archive(self, m: dict) -> None:
        inst = str(m.get("id", ""))[len("archive:"):]
        st = self.archives.get(inst)
        t = m.get("type")
        if st is None or st.get("etat") != "demande":
            return
        if t == "history":
            if m.get("barres"):
                st["morceaux"].append(np.asarray(m["barres"], dtype=float))
        elif t == "error":
            st["etat"] = "erreur"
            self.journal(f"archive {inst} : {m.get('msg')}")
        elif t == "history_done":
            self._envoyer(dict(type="unsubscribe", id=f"archive:{inst}"))
            try:
                n = self._ecrire_archive(inst, st.pop("morceaux"))
                st["etat"] = "recue"
                self.journal(f"archive {inst} : {n}")
            except Exception as ex:                                     # noqa: BLE001
                st["etat"] = "erreur"
                self.journal(f"archive {inst} : ecriture impossible ({ex!r})")
            if all(self.archives.get(i, {}).get("etat") in ("recue", "erreur") for i in self.abos):
                self._lancer_rapport()

    def _ecrire_archive(self, inst: str, morceaux: list) -> str:
        import pandas as pd
        os.makedirs(self.dossier_archive, exist_ok=True)
        a = np.concatenate(morceaux) if morceaux else np.empty((0, 6))
        df = pd.DataFrame(a, columns=["t", "open", "high", "low", "close", "volume"])
        f = os.path.join(self.dossier_archive, f"{inst}.parquet")
        if os.path.exists(f):
            df = pd.concat([pd.read_parquet(f), df], ignore_index=True)       # garde l historique deja archive
        df["t"] = df["t"].astype("int64")
        df = df.drop_duplicates("t", keep="last").sort_values("t").reset_index(drop=True)
        tmp = f + ".tmp"
        df.to_parquet(tmp, index=False)
        os.replace(tmp, f)
        if not len(df):
            return "aucune barre recue"
        return (f"{len(df):,} barres archivees, du {heure(int(df.t.iloc[0]), NY):%Y-%m-%d %H:%M} au "
                f"{heure(int(df.t.iloc[-1]), NY):%Y-%m-%d %H:%M} ET (fin de barre)")

    def _lancer_rapport(self) -> None:
        if not self.archive_cfg.get("rapport", True) or not self.journal_dir:
            return
        if self._rapport is not None and self._rapport.poll() is None:
            return
        try:
            opts = dict(creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)) if os.name == "nt" else {}
            self._rapport = subprocess.Popen([sys.executable, "-m", "nexus.live.rapport"], cwd=PY_DIR,
                                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, **opts)
            self.journal("rapport du forward lance (executions du compte demo + vectorbt)")
        except OSError as ex:
            self.journal(f"rapport du Groupe impossible a lancer : {ex!r}")

    # ------------------------------------------------------------------ evenements
    def sur_barre(self, instrument: str, b: Barre) -> None:
        self.maintenant = self.horloge()
        a = self.abos.get(instrument)
        if a is None or b.t <= a.dernier_t:
            return
        a.dernier_t = b.t
        a.historique.append(b)
        if len(a.historique) > a.barres + 5000:
            del a.historique[: len(a.historique) - a.barres - 2000]
        self._en_lot += 1
        try:
            for e in list(self.entrees.values()):
                if e.statut == "active" and instrument in e.instruments:
                    self._appel(e, "sur_barre", instrument, b)
        finally:
            self._en_lot -= 1
        self._pousser()

    def _appel(self, e: Entree, methode: str, *args) -> None:
        try:
            getattr(e.strategie, methode)(*args)
        except Exception as ex:                                         # noqa: BLE001
            e.statut, e.erreur = "erreur", f"{methode} : {ex!r}"
            e.cibles = {}
            self.journal(f"erreur dans {methode} : {ex!r} ; cibles a 0\n{traceback.format_exc(limit=4)}", strategie=e.nom)

    def sur_message(self, m: dict) -> None:
        self.maintenant = self.horloge()
        t = m.get("type")
        if str(m.get("id", "")).startswith("archive:"):
            self._sur_archive(m)
            return
        if t == "_connecte":
            self.passerelle.update(connecte=True, hello=False)
            self._envoyer(dict(type="hello", client="nexus.live", version=1))
        elif t == "_deconnecte":
            if self.passerelle.get("connecte"):
                self.journal("passerelle deconnectee (NinjaTrader met tout a plat) ; reconnexion automatique")
            self.passerelle.update(connecte=False, hello=False)
            for a in self.abos.values():
                a.demandees, a.pret = 0, False
            for st in self.archives.values():
                if st.get("etat") == "demande":
                    st["etat"] = ""
                    st.pop("morceaux", None)
        elif t == "hello":
            self.passerelle.update({k: v for k, v in m.items() if k != "type"}, hello=True, connecte=True)
            sim = m.get("simulation")
            self.journal(f"passerelle : compte {m.get('compte')} " + ("(simulation)" if sim else "(REEL ou introuvable)")
                         + f", coupure {m.get('coupure_et')} ET, plafonds {m.get('max_contrats')}")
            for a in self.abos.values():
                a.demandees, a.pret = 0, False
            self._abonner()
            self._renvoyer()
            self._envoyer_etat_groupe()
        elif t == "subscribed":
            a = self.abos.get(m.get("id"))
            if a:
                a.info = {k: v for k, v in m.items() if k not in ("type", "id")}
        elif t == "history":
            a = self.abos.get(m.get("id"))
            if a:
                for x in m.get("barres", []):
                    b = barre(x)
                    if a.dernier_t and b.t > a.dernier_t:
                        self.sur_barre(a.instrument, b)                    # rattrapage apres une deconnexion
                    else:
                        a.tampon.append(b)
        elif t == "history_done":
            a = self.abos.get(m.get("id"))
            if a:
                a.pret = True
                if a.tampon:
                    fusion = {b.t: b for b in a.tampon}
                    fusion.update({b.t: b for b in a.historique})
                    a.historique = [fusion[k] for k in sorted(fusion)]
                    a.tampon = []
                if a.historique:
                    a.dernier_t = max(a.dernier_t, a.historique[-1].t)
                self.journal(f"historique {a.instrument} : {len(a.historique)} barres"
                             + (f" ({a.info.get('instrument')})" if a.info.get("instrument") else ""))
                for e in list(self.entrees.values()):
                    self._essayer_chauffe(e)
        elif t == "bar":
            self.sur_barre(m.get("id"), barre(m["b"]))
        elif t == "position":
            self.positions[racine(m.get("instrument", ""))] = int(m.get("qty", 0))
        elif t == "execution":
            self._consigner("executions.jsonl", m)
            x = dict(t=m.get("t"), instrument=m.get("instrument"), qty=m.get("qty"), prix=m.get("prix"), ordre=m.get("ordre"))
            self.executions.append(x)
            self.journal(f"execution {m.get('instrument')} {m.get('qty'):+d} a {m.get('prix')}", **{k: v for k, v in x.items() if k != "t"})
        elif t == "order":
            self._consigner("ordres.jsonl", m)
            if m.get("etat") in ("Rejected", "Cancelled"):
                self.journal(f"ordre {m.get('etat')} sur {m.get('instrument')} : {m.get('texte')}")
        elif t == "target_ack":
            if m.get("qty") != m.get("demande"):
                self.journal(f"cible {m.get('instrument')} ecretee par la passerelle : {m.get('demande')} -> {m.get('qty')} "
                             f"(plafond {m.get('plafond')})")
        elif t == "heartbeat":
            pos = {racine(k): v for k, v in (m.get("positions") or {}).items()}
            self.positions.update(pos)
            self.passerelle.update(verrou=m.get("verrou"), valeur_liquidative=m.get("valeur_liquidative"),
                                   resultat_jour=m.get("resultat_jour"), dernier_coeur=m.get("t"))
        elif t == "guard":
            motif = m.get("motif")
            self.passerelle["verrou"] = "" if motif == "aucun" else motif
            if motif != "aucun":
                self.journal(f"garde-fou de la passerelle : {motif}")
            else:
                self._renvoyer()                       # la passerelle remet ses cibles a 0 a chaque verrou : on les renvoie
            if motif in SUSPENSION and not self.suspension:
                self.suspension = motif
                self.suspension_fin = self._prochaine_seance()
                self.journal(f"Groupe suspendu ({motif}) jusqu a {heure(self.suspension_fin, NY):%Y-%m-%d %H:%M} ET")
                self._pousser()
        elif t == "error":
            self.journal(f"passerelle : {m.get('msg')}")
        elif t == "commande":
            action, nom = m.get("action"), str(m.get("nom", ""))
            if action in ("activer", "desactiver"):
                self.basculer(nom, action == "activer", m.get("source", "NinjaTrader"))
            else:
                self.journal(f"commande inconnue de {m.get('source', 'la passerelle')} : {action}")

    def _renvoyer(self) -> None:
        """Renvoie toutes les cibles nettes (apres une reconnexion ou un verrou leve)."""
        self.envoye = {i: None for i in self.envoye}
        self._pousser()

    # ------------------------------------------------------------------ fenetre Groupe de NinjaTrader
    def etat_groupe(self) -> dict:
        """Une ligne par strategie du registre (desactivees comprises) pour la fenetre Groupe."""
        lignes, vus = [], set()
        for sp in self._lire_registre() or []:
            nom = str(sp.get("nom", "")).strip()
            if not nom or nom in vus:
                continue
            vus.add(nom)
            e = self.entrees.get(nom)
            if e is None:
                lignes.append(dict(nom=nom, actif=bool(sp.get("actif", True)), statut="desactivee" if not sp.get("actif", True) else "absente",
                                   cibles={}, resume=sp.get("classe", ""), erreur=""))
                continue
            try:
                et = e.strategie.etat() if e.strategie and e.statut == "active" else {}
            except Exception as ex:                                     # noqa: BLE001
                et = dict(erreur=repr(ex))
            resume = " · ".join(f"{k.replace('_', ' ')} : {v}" for k, v in et.items() if not isinstance(v, (dict, list, tuple)))
            if e.remplacement is not None:
                resume = "modifiee : remplacee une fois a plat · " + resume
            lignes.append(dict(nom=nom, actif=True, statut=e.statut, cibles={i: q for i, q in e.cibles.items() if q}, resume=resume[:220],
                               erreur=e.erreur))
        return dict(type="etat_groupe", t=self.maintenant, suspension=self.suspension, strategies=lignes)

    def _envoyer_etat_groupe(self) -> None:
        if self.passerelle.get("connecte") and self.passerelle.get("hello"):
            self._envoyer(self.etat_groupe())

    def basculer(self, nom: str, actif: bool, source: str = "") -> bool:
        """Active ou desactive une strategie en ecrivant "actif" dans le registre, puis le recharge."""
        if isinstance(self.registre, dict):
            sp = next((x for x in self.registre.get("strategies", []) if x.get("nom") == nom), None)
            if sp is not None:
                sp["actif"] = bool(actif)
        else:
            try:
                with open(self.registre, encoding="utf-8") as fh:
                    d = json.load(fh)
            except (OSError, ValueError) as ex:
                self.journal(f"commande {source} sur {nom} impossible : registre illisible ({ex})")
                return False
            sp = next((x for x in d.get("strategies", []) if x.get("nom") == nom), None)
            if sp is not None:
                sp["actif"] = bool(actif)
                tmp = self.registre + ".tmp"
                with open(tmp, "w", encoding="utf-8") as fh:
                    json.dump(d, fh, ensure_ascii=False, indent=2)
                    fh.write("\n")
                os.replace(tmp, self.registre)
                self._mtime_registre = None
        if sp is None:
            self.journal(f"commande {source} : strategie inconnue dans le registre : {nom}")
            return False
        self.journal(("activee" if actif else "desactivee") + (f" depuis {source}" if source else ""), strategie=nom)
        self.charger_registre()
        self._envoyer_etat_groupe()
        return True

    def _prochaine_seance(self) -> int:
        n = heure(self.maintenant, NY)
        d = datetime(n.year, n.month, n.day, 18, 0, tzinfo=NY)
        if n >= d:
            d = datetime(n.year, n.month, n.day, tzinfo=NY) + timedelta(days=1)
            d = d.replace(hour=18)
        return ms(d)

    def tic(self, t: int | None = None) -> None:
        """Horloge : chaque seconde en direct."""
        self.maintenant = self.horloge() if t is None else t
        if self.suspension and self.maintenant >= self.suspension_fin:
            self.journal(f"fin de la suspension ({self.suspension})")
            self.suspension = ""
        if self.surveiller and self.maintenant >= self._prochain_registre:
            self._prochain_registre = self.maintenant + 5000
            self.charger_registre()
        for e in list(self.entrees.values()):
            if e.remplacement is not None and not any(e.cibles.values()):
                s = e.remplacement
                self._retirer(e.nom, "modifiee")
                self._ajouter(s, _signature(s))
                self._abonner()
        self._en_lot += 1
        try:
            for e in list(self.entrees.values()):
                if e.statut == "active":
                    self._appel(e, "sur_horloge", self.maintenant)
        finally:
            self._en_lot -= 1
        self._pousser()
        if self.maintenant >= self._prochain_groupe:
            self._prochain_groupe = self.maintenant + 2000
            self._envoyer_etat_groupe()
            self._verifier_archives()
            self._enregistrer_direct()
        if self.etat_path and self.maintenant >= self._prochain_etat:
            self._prochain_etat = self.maintenant + 2000
            self.ecrire_etat()


__all__ = ["Moteur", "Contexte", "Abo", "Entree", "REGISTRE", "ETAT", "JOURNAL", "MINUTE_MS"]
