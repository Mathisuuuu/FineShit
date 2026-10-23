"""Groupe en direct (nexus/live) : protocole, moteur (cibles nettes, registre a chaud), parite des strategies en direct
avec la recherche sur donnees synthetiques, essai de bout en bout avec la fausse passerelle TCP."""
from __future__ import annotations

import json
import os
import time

import numpy as np
import pandas as pd
import pytest

from nexus import gotobi as G
from nexus.live.essai import essai
from nexus.live.moteur import Moteur
from nexus.live.protocole import MINUTE_MS, Barre, barre, decoder, encoder, racine
from nexus.live.rejeu import rejouer
from nexus.live.strategies.s1 import REF, demi_seance
from nexus.live.verification import _positions_reference


class Lien:
    def __init__(self):
        self.envoyes = []

    def envoyer(self, m):
        self.envoyes.append(m)

    def cibles(self):
        out = {}
        for m in self.envoyes:
            if m["type"] == "target":
                out[m["instrument"]] = m["qty"]
        return out


def _brancher(m: Moteur, lien: Lien) -> None:
    m.sur_message({"type": "_connecte"})
    m.sur_message({"type": "hello", "compte": "Sim101", "simulation": True})
    for x in list(lien.envoyes):
        if x["type"] == "subscribe":
            m.sur_message({"type": "history_done", "id": x["id"], "n": 0})


def test_protocole():
    b = Barre(1_700_000_000_000, 1.0, 2.0, 0.5, 1.5, 10.0)
    m = decoder(encoder({"type": "bar", "id": "NQ", "b": list(b)}))
    assert barre(m["b"]) == b and b.debut == b.t - MINUTE_MS
    assert racine("MNQ 12-26") == "MNQ" and racine("6J") == "6J"
    with pytest.raises(ValueError):
        decoder(b'{"x": 1}')


def test_cibles_nettes_et_registre_a_chaud(tmp_path):
    reg = tmp_path / "groupe.json"
    spec = lambda nom, q: dict(nom=nom, classe="nexus.live.essai:StrategieEssai", params=dict(instrument="X", q=q))
    reg.write_text(json.dumps({"strategies": [spec("A", 1), spec("B", 2)]}), encoding="utf-8")
    lien = Lien()
    m = Moteur(str(reg), lien=lien, horloge=lambda: 0, etat=None, journal_dir=None, log=None)
    m.charger_registre()
    _brancher(m, lien)
    assert [x["barres"] for x in lien.envoyes if x["type"] == "subscribe"] == [20]
    assert m.entrees["A"].statut == m.entrees["B"].statut == "active"
    m.sur_barre("X", Barre(60_000, 1, 1, 1, 1.0, 1))
    m.sur_barre("X", Barre(120_000, 1, 1, 1, 2.0, 1))
    assert lien.cibles() == {"X": 3}
    # retrait de A : seule la cible de B reste
    reg.write_text(json.dumps({"strategies": [spec("B", 2)]}), encoding="utf-8")
    os.utime(reg, (time.time() + 5, time.time() + 5))
    m.charger_registre()
    assert "A" not in m.entrees and lien.cibles() == {"X": 2}
    # modification de B en position : remplacement differe jusqu a ce qu elle soit a plat
    reg.write_text(json.dumps({"strategies": [spec("B", 5)]}), encoding="utf-8")
    os.utime(reg, (time.time() + 10, time.time() + 10))
    m.charger_registre()
    assert m.entrees["B"].remplacement is not None and m.entrees["B"].strategie.q == 2
    m.entrees["B"].cibles = {"X": 0}
    m.tic(0)
    assert m.entrees["B"].strategie.q == 5 and m.entrees["B"].remplacement is None
    # registre illisible : Groupe inchange
    reg.write_text("{pas du json", encoding="utf-8")
    os.utime(reg, (time.time() + 15, time.time() + 15))
    m.charger_registre()
    assert "B" in m.entrees and m._erreur_registre


def test_fenetre_groupe_commandes_et_verrou(tmp_path):
    reg = tmp_path / "groupe.json"
    spec = lambda nom, q: dict(nom=nom, classe="nexus.live.essai:StrategieEssai", params=dict(instrument="X", q=q))
    reg.write_text(json.dumps({"commentaire": "garde", "strategies": [spec("A", 1), spec("B", 2)]}), encoding="utf-8")
    lien = Lien()
    m = Moteur(str(reg), lien=lien, horloge=lambda: 0, etat=None, journal_dir=None, log=None)
    m.charger_registre()
    _brancher(m, lien)
    m.sur_barre("X", Barre(60_000, 1, 1, 1, 1.0, 1))
    m.sur_barre("X", Barre(120_000, 1, 1, 1, 2.0, 1))
    assert lien.cibles() == {"X": 3}
    etats = [x for x in lien.envoyes if x["type"] == "etat_groupe"]
    assert etats and [s["nom"] for s in etats[-1]["strategies"]] == ["A", "B"]
    # bouton Desactiver de NinjaTrader : groupe.json modifie, cible de A a 0, etat renvoye
    m.sur_message({"type": "commande", "action": "desactiver", "nom": "A", "source": "NinjaTrader"})
    d = json.loads(reg.read_text(encoding="utf-8"))
    assert d["commentaire"] == "garde" and d["strategies"][0]["actif"] is False and "A" not in m.entrees
    assert lien.cibles() == {"X": 2}
    dernier = [x for x in lien.envoyes if x["type"] == "etat_groupe"][-1]
    assert [(s["nom"], s["statut"]) for s in dernier["strategies"]] == [("A", "desactivee"), ("B", "active")]
    m.sur_message({"type": "commande", "action": "activer", "nom": "A"})
    assert json.loads(reg.read_text(encoding="utf-8"))["strategies"][0]["actif"] is True and m.entrees["A"].statut == "active"
    assert not m.basculer("Inconnue", False)
    # verrou leve (« Reprendre », fin de coupure) : la passerelle a remis ses cibles a 0, le moteur les renvoie
    n = len(lien.envoyes)
    m.sur_message({"type": "guard", "motif": "inactif"})
    m.sur_message({"type": "guard", "motif": "aucun"})
    assert {x["instrument"]: x["qty"] for x in lien.envoyes[n:] if x["type"] == "target"} == {"X": 2}


def test_erreur_d_une_strategie_isolee(tmp_path):
    lien = Lien()
    reg = {"strategies": [dict(nom="A", classe="nexus.live.essai:StrategieEssai", params=dict(instrument="X", q=1)),
                          dict(nom="Z", classe="nexus.live.essai:Inexistante", params={})]}
    m = Moteur(reg, lien=lien, horloge=lambda: 0, etat=None, journal_dir=None, log=None)
    m.charger_registre()
    _brancher(m, lien)
    assert m.entrees["Z"].statut == "erreur" and m.entrees["A"].statut == "active"

    def panne(*_):
        raise RuntimeError("panne")

    m.sur_barre("X", Barre(60_000, 1, 1, 1, 1.0, 1))
    m.sur_barre("X", Barre(120_000, 1, 1, 1, 2.0, 1))
    assert lien.cibles() == {"X": 1}
    m.entrees["A"].strategie.sur_barre = panne
    m.sur_barre("X", Barre(180_000, 1, 1, 1, 3.0, 1))
    assert m.entrees["A"].statut == "erreur" and lien.cibles() == {"X": 0}


def test_suspension_perte_du_jour():
    lien = Lien()
    t = {"v": int(pd.Timestamp("2026-10-20 15:00", tz="America/New_York").value // 1_000_000)}
    reg = {"strategies": [dict(nom="A", classe="nexus.live.essai:StrategieEssai", params=dict(instrument="X", q=1))]}
    m = Moteur(reg, lien=lien, horloge=lambda: t["v"], etat=None, journal_dir=None, log=None)
    m.charger_registre()
    _brancher(m, lien)
    m.sur_barre("X", Barre(t["v"], 1, 1, 1, 1.0, 1))
    m.sur_barre("X", Barre(t["v"] + 60_000, 1, 1, 1, 2.0, 1))
    assert lien.cibles() == {"X": 1}
    m.sur_message({"type": "guard", "motif": "perte du jour"})
    assert lien.cibles() == {"X": 0}
    m.sur_barre("X", Barre(t["v"] + 120_000, 1, 1, 1, 3.0, 1))
    assert lien.cibles() == {"X": 0}
    t["v"] = int(pd.Timestamp("2026-10-20 18:00:01", tz="America/New_York").value // 1_000_000)
    m.tic()
    assert m.suspension == "" and lien.cibles() == {"X": 1}


def test_demi_seances():
    attendu = {"2018-07-03", "2018-11-23", "2018-12-24", "2020-11-27", "2020-12-24", "2023-07-03", "2024-07-03", "2024-11-29",
               "2024-12-24", "2025-07-03", "2025-11-28", "2025-12-24"}
    jours = pd.bdate_range("2018-01-01", "2025-12-31")
    trouves = {str(d.date()) for d in jours if demi_seance(d.date())}
    assert attendu <= trouves
    assert not demi_seance(pd.Timestamp("2020-07-03").date())          # 4 juillet un samedi : 3 juillet ferie
    assert not demi_seance(pd.Timestamp("2021-12-24").date())          # 24 decembre un vendredi : ferie


def _nq_synthetique(debut="2024-08-01", fin="2025-02-28", graine=7) -> pd.DataFrame:
    """Seances cash de NQ (9:30-16:00 New York ; 13:15 les demi-seances), avec tendances pour franchir la zone de bruit."""
    rng = np.random.default_rng(graine)
    feries = set(REF.feries_nyse(debut, fin))
    px, rows, idx = 20000.0, [], []
    for d in pd.bdate_range(debut, fin):
        if d in feries:
            continue
        n = 225 if demi_seance(d.date()) else 396                       # les futures cotent apres 16:00
        derive = rng.normal(0, 0.0004)
        px *= np.exp(rng.normal(0, 0.004))                              # ecart de nuit
        r = rng.normal(derive, 0.0006, n)
        c = px * np.exp(np.cumsum(r))
        o = np.r_[px, c[:-1]]
        px = c[-1]
        t0 = pd.Timestamp(d.date()).tz_localize("America/New_York") + pd.Timedelta(hours=9, minutes=30)
        idx.append(pd.date_range(t0, periods=n, freq="1min"))
        rows.append(np.column_stack([o, np.maximum(o, c) + 1, np.minimum(o, c) - 1, c, rng.integers(50, 500, n)]))
    df = pd.DataFrame(np.vstack(rows), columns=["open", "high", "low", "close", "volume"],
                      index=pd.DatetimeIndex(np.concatenate([i.tz_convert("UTC").as_unit("ns").asi8 for i in idx])).tz_localize("UTC"))
    keep = np.ones(len(df), bool)
    keep[rng.choice(len(df), 300, replace=False)] = False                 # quelques minutes sans transaction
    return df[keep]


def test_s1_parite_avec_le_fichier_autonome():
    df = _nq_synthetique()
    eq, trades = REF.backtest(df, 1_000_000.0)
    assert len(trades) > 20
    capital = dict(zip([str(d.date()) for d in eq.index], eq["equity"].shift(1).fillna(1_000_000.0).to_numpy()))
    reg = {"strategies": [dict(nom="S1", classe="nexus.live.verification:S1Rejeu",
                               params=dict(donnees="NQ", negocie="NQ", capital_par_jour=capital, barres_chauffe=10))]}
    ex, _ = rejouer(reg, {"NQ": df}, horloge=False)
    h = pd.to_datetime(ex["t"], unit="ms", utc=True).dt.tz_convert("America/New_York")
    live = pd.DataFrame(dict(jour=h.dt.normalize().dt.tz_localize(None), heure=h.dt.strftime("%H:%M"), position=ex["position"]))
    ref = _positions_reference(trades)
    for x in (ref, live):
        x["jour"] = x["jour"].astype("datetime64[ns]")
    pd.testing.assert_frame_equal(ref.reset_index(drop=True), live.reset_index(drop=True), check_dtype=False)
    # entrees au meme prix (ouverture de la minute qui suit le controle)
    jours, fin, O, *_ = REF.seance_cash(df)
    entrees = ex[ex["position"] != 0]
    hh = pd.to_datetime(entrees["t"], unit="ms", utc=True).dt.tz_convert("America/New_York")
    m = (hh.dt.hour * 60 + hh.dt.minute - 570 + 1).to_numpy()
    attendu = [O.loc[pd.Timestamp(j.date()), k] for j, k in zip(hh, m)]
    assert np.allclose(entrees["prix"].to_numpy(), attendu)


def _6j_synthetique(debut="2025-01-01", fin="2025-04-30", graine=11) -> pd.DataFrame:
    rng = np.random.default_rng(graine)
    idx = pd.date_range(debut, fin, freq="1min", tz="UTC")
    ny = idx.tz_convert("America/New_York")
    ouvert = ~(((ny.hour == 17)) | ((ny.dayofweek == 4) & (ny.hour >= 17)) | (ny.dayofweek == 5) | ((ny.dayofweek == 6) & (ny.hour < 18)))
    idx = idx[ouvert]
    c = 0.0066 * np.exp(np.cumsum(rng.normal(0, 0.0002, len(idx))))
    o = np.r_[0.0066, c[:-1]]
    return pd.DataFrame(dict(open=o, high=np.maximum(o, c), low=np.minimum(o, c), close=c, volume=5.0), index=idx)


def test_gotobi_parite_avec_la_recherche():
    m = _6j_synthetique()
    mi = m.copy()
    mi.index = mi.index.tz_localize(None)
    (E, X, SE, SX), jours = G.signaux(mi, dict(G.DEFAULTS))
    assert len(jours) > 15
    attendu = sorted([(t, -1) for t in mi.index[SE.to_numpy()]] + [(t, 1) for t in mi.index[E.to_numpy()]]
                     + [(t, 0) for t in mi.index[X.to_numpy()]])
    reg = {"strategies": [dict(nom="Gotobi", classe="nexus.live.strategies.gotobi:Gotobi", params=dict(negocie="6J", contrats=1))]}
    ex, _ = rejouer(reg, {"6J": m}, horloge=True)
    obtenu = sorted(zip(pd.to_datetime(ex["t"], unit="ms"), np.sign(ex["position"]).astype(int)))
    borne = mi.index[-1] - pd.Timedelta(days=1)                        # dernier jour : jambes coupees par la fin des donnees
    assert [x for x in obtenu if x[0] < borne] == [x for x in attendu if x[0] < borne]
    # heures de Tokyo : 08:00 vente, 09:55 achat, 11:00 sortie
    tk = pd.DatetimeIndex([t for t, _ in obtenu]).tz_localize("UTC").tz_convert("Asia/Tokyo").strftime("%H:%M")
    assert set(tk) == {"08:00", "09:55", "11:00"}


def test_essai_de_bout_en_bout():
    assert essai(log=lambda *_: None)


def test_archive_ninjatrader_et_journal_des_ordres(tmp_path):
    """Le moteur demande l historique 1 minute a NinjaTrader une fois par jour, l archive en Parquet, et consigne toutes
    les cibles, ordres et executions."""
    lien = Lien()
    t = {"v": int(pd.Timestamp("2026-10-20 17:00", tz="America/New_York").value // 1_000_000)}
    reg = {"strategies": [dict(nom="A", classe="nexus.live.essai:StrategieEssai", params=dict(instrument="X", q=1))]}
    m = Moteur(reg, lien=lien, horloge=lambda: t["v"], etat=None, journal_dir=str(tmp_path), log=None)
    m.archive_cfg.update(barres=1000, rapport=False)
    m.charger_registre()
    _brancher(m, lien)
    m.tic()
    dem = [x for x in lien.envoyes if x["type"] == "subscribe" and x["id"] == "archive:X"]
    assert dem and dem[0]["barres"] == 1000
    m.sur_message({"type": "history", "id": "archive:X", "barres": [[120_000, 1, 2, 0.5, 1.5, 10], [180_000, 1.5, 2, 1, 1.8, 5]]})
    m.sur_message({"type": "history_done", "id": "archive:X", "n": 2})
    a = pd.read_parquet(tmp_path / "archive" / "X.parquet")
    assert list(a["t"]) == [120_000, 180_000] and {"type": "unsubscribe", "id": "archive:X"} in lien.envoyes
    assert m.abos["X"].historique == []                                     # l archive ne touche pas aux strategies
    n = len(lien.envoyes)
    m.tic()
    assert not [x for x in lien.envoyes[n:] if x.get("id") == "archive:X"]  # deja a jour aujourd hui
    m.sur_barre("X", Barre(t["v"], 1, 1, 1, 1.0, 1))
    m.sur_barre("X", Barre(t["v"] + 60_000, 1, 1, 1, 2.0, 1))
    m.sur_message({"type": "order", "instrument": "X 12-26", "ordre": "1", "etat": "Filled", "rempli": 1, "prix_moyen": 2.0, "texte": ""})
    m.sur_message({"type": "execution", "instrument": "X 12-26", "qty": 1, "prix": 2.0, "t": t["v"], "ordre": "1", "nom": "Nexus A"})
    lus = {f: [json.loads(x) for x in (tmp_path / f).read_text(encoding="utf-8").splitlines()]
           for f in ("cibles.jsonl", "ordres.jsonl", "executions.jsonl")}
    assert lus["cibles.jsonl"][-1]["qty"] == 1 and lus["ordres.jsonl"][0]["etat"] == "Filled" and lus["executions.jsonl"][0]["prix"] == 2.0


def test_gotobi_suit_le_flux_differe():
    """Cours differes de 10 min (compte demo NinjaTrader) : Gotobi vend a 8:00 du fil de donnees, soit 8:10 a l horloge."""
    from nexus.live.strategies.gotobi import Gotobi

    class Ctx:
        en_chauffe = False
        t = 0
        cibles = []
        def maintenant(self): return self.t
        def cible(self, i, q, motif=""): self.cibles.append((self.t, q))
        def derniere(self, i): return None
        def info(self, i): return {}
        def journal(self, *a, **k): pass

    c = Ctx()
    g = Gotobi("G", dict(negocie="6J", contrats=1), c)
    h8 = int(pd.Timestamp("2025-01-10 08:00", tz="Asia/Tokyo").value // 1_000_000)   # jour gotobi
    for k in range(-30, 1):                                                         # barres recues avec 10 min de retard
        b = Barre(h8 - 600_000 + k * 60_000, 1, 1, 1, 0.0066, 1)
        c.t = b.t + 600_000
        g.sur_barre("6J", b)
    assert g.retard == 600_000
    c.t = h8
    g.sur_horloge(h8)
    assert c.cibles == []                                                           # 8:00 reelle = 7:50 du fil : rien
    c.t = h8 + 600_000
    g.sur_horloge(h8 + 600_000)
    assert c.cibles == [(h8 + 600_000, -1)]                                         # 8:00 du fil : vente
