"""Parite : les strategies en direct, rejouees minute par minute dans le moteur, refont-elles les trades de la recherche ?

    python -m nexus.live --verifier [--cotations ../Cotations] [--debut 2016-01-01]

S1     : rejeu des barres 1 minute de NQ (Parquet Databento du depot Cotations, rolls ajustes comme S1_NoiseAreaNQ.py)
         dans nexus.live.strategies.s1, positions en NQ et capital du jour = equity du backtest autonome a la veille
         (pour comparer aussi le nombre de contrats). Compare (jour, heure, position) a S1_NoiseAreaNQ.backtest, et
         les demi-seances du calendrier en direct a celles detectees dans les donnees.
Gotobi : rejeu des barres de 6J (rolls ajustes comme nexus/gotobi.py) dans nexus.live.strategies.gotobi ;
         compare les instants et le sens des positions a gotobi.signaux (meme calendrier, memes heures).
Seule difference attendue : le prix de sortie de fin de seance de S1 (ouverture de la minute de 16:00 en direct,
cloture de la minute de 15:59-16:00 dans le backtest).
"""
from __future__ import annotations

import os
import sys
from datetime import date

import numpy as np
import pandas as pd

from .rejeu import rejouer
from .strategies.s1 import NY as NY_S1, REF, S1, demi_seance

ICI = os.path.dirname(os.path.abspath(__file__))
COTATIONS = os.path.normpath(os.path.join(ICI, "..", "..", "..", "Cotations"))


class S1Rejeu(S1):
    """S1 avec le capital du jour impose (equity du backtest autonome a la veille)."""

    def capital_du_jour(self, d: date) -> float:
        return float(self.params["capital_par_jour"][str(d)])


def _positions_reference(trades: pd.DataFrame) -> pd.DataFrame:
    """Trades du backtest autonome -> (jour, heure, position apres l evenement)."""
    ev = []
    for r in trades.itertuples():
        sens = 1 if r.sens == "long" else -1
        ev.append((pd.Timestamp(r.jour), r.entree, 1, sens * int(r.contrats)))
        ev.append((pd.Timestamp(r.jour), r.sortie, 0, 0))
    df = pd.DataFrame(ev, columns=["jour", "heure", "ordre", "position"]).sort_values(["jour", "heure", "ordre"])
    return df.groupby(["jour", "heure"], as_index=False).last()[["jour", "heure", "position"]]


def verifier_s1(cotations: str = COTATIONS, debut: str | None = None, log=print) -> dict:
    f = os.path.join(cotations, "indices", "NQ_v0_1m.parquet")
    df, _ = REF.lire_minutes(f, REF.NY, "debut")
    df, n_rolls = REF.ajuster_rolls(df)
    if debut:
        df = df[df.index >= pd.Timestamp(debut, tz="UTC")]
    log(f"[S1] {len(df):,} barres NQ, {n_rolls} rolls ajustes ; backtest autonome...")
    eq, trades = REF.backtest(df, 1_000_000.0)
    jours, fin, *_ = REF.seance_cash(df)
    demi_donnees = set(d.date() for d in jours[fin[jours] == 210])
    demi_cal = set(d.date() for d in jours if demi_seance(d.date()))
    capital = dict(zip([str(d.date()) for d in eq.index], eq["equity"].shift(1).fillna(1_000_000.0).to_numpy()))
    ny = df.index.tz_convert(NY_S1)
    mn = ny.hour * 60 + ny.minute
    rth = df[(mn >= 9 * 60 + 25) & (mn <= 16 * 60 + 5)]
    log(f"[S1] rejeu de {len(rth):,} barres (9:25-16:05 New York) dans le moteur en direct...")
    reg = {"strategies": [dict(nom="S1", classe="nexus.live.verification:S1Rejeu", params=dict(
        donnees="NQ", negocie="NQ", capital_par_jour=capital, barres_chauffe=10))]}
    ex, _ = rejouer(reg, {"NQ": rth}, horloge=False)
    h = pd.to_datetime(ex["t"], unit="ms", utc=True).dt.tz_convert(NY_S1)
    live = pd.DataFrame(dict(jour=h.dt.normalize().dt.tz_localize(None), heure=h.dt.strftime("%H:%M"), position=ex["position"]))
    ref = _positions_reference(trades)
    k = ["jour", "heure"]
    fus = ref.merge(live, on=k, how="outer", suffixes=("_ref", "_live"), indicator=True)
    egal = (fus["_merge"] == "both") & (fus["position_ref"] == fus["position_live"])
    meme_sens = (fus["_merge"] == "both") & (np.sign(fus["position_ref"]) == np.sign(fus["position_live"]))
    # prix : entrees identiques (ouverture de la minute suivante) ; sorties de 16:00 a l ouverture de 16:00 en direct
    out = dict(trades_reference=len(trades), evenements_reference=len(ref), evenements_direct=len(live),
               identiques=int(egal.sum()), meme_sens=int(meme_sens.sum()),
               seulement_reference=int((fus["_merge"] == "left_only").sum()), seulement_direct=int((fus["_merge"] == "right_only").sum()),
               demi_seances_donnees=len(demi_donnees), demi_seances_calendrier=len(demi_cal),
               demi_seances_ecarts=sorted(str(d) for d in demi_donnees ^ demi_cal))
    out["parite"] = out["identiques"] / max(1, len(fus))
    ecarts = fus[~egal].head(12)
    log(f"[S1] evenements : reference {out['evenements_reference']}, direct {out['evenements_direct']}, identiques "
        f"{out['identiques']} ({out['parite']:.2%}), meme sens {out['meme_sens']}, seulement reference {out['seulement_reference']}, "
        f"seulement direct {out['seulement_direct']}")
    log(f"[S1] demi-seances : donnees {len(demi_donnees)}, calendrier {len(demi_cal)}, ecarts {out['demi_seances_ecarts'] or 'aucun'}")
    if len(ecarts):
        log("[S1] premiers ecarts :\n" + ecarts.to_string(index=False))
    out["ecarts"] = ecarts
    return out


def verifier_gotobi(cotations: str = COTATIONS, debut: str | None = None, log=print) -> dict:
    from .. import data as D
    from .. import gotobi as G
    from .. import intraday as I
    brut = D.load_folder(os.path.join(cotations, "forex"), daily=False, only=["6J"])["6J"]
    adj, _ = I.adjust_rolls_midnight_utc(brut, "UTC")
    m = pd.DataFrame({k: adj[k].to_numpy(float) for k in ("open", "high", "low", "close")}, index=pd.DatetimeIndex(brut.index))
    m["volume"] = brut["volume"].to_numpy(float) if "volume" in brut else 1.0
    if m.index.tz is None:
        m.index = m.index.tz_localize("UTC")
    if debut:
        m = m[m.index >= pd.Timestamp(debut, tz="UTC")]
    p = dict(G.DEFAULTS)
    mi = m.copy()
    mi.index = mi.index.tz_convert("UTC").tz_localize(None)
    (E, X, SE, SX), jours = G.signaux(mi, p)
    pos, ref = 0, []
    for t, e, x, se, sx in zip(mi.index, E.to_numpy(), X.to_numpy(), SE.to_numpy(), SX.to_numpy()):
        nouveau = pos
        if sx and nouveau < 0:
            nouveau = 0
        if x and nouveau > 0:
            nouveau = 0
        if se:
            nouveau = -1
        if e:
            nouveau = 1
        if nouveau != pos:
            ref.append((t, nouveau))
            pos = nouveau
    ref = pd.DataFrame(ref, columns=["t", "sens"])
    log(f"[Gotobi] {len(m):,} barres 6J, {len(jours)} jours gotobi traites par la recherche ; rejeu dans le moteur en direct...")
    reg = {"strategies": [dict(nom="Gotobi", classe="nexus.live.strategies.gotobi:Gotobi", params=dict(negocie="6J", contrats=1, barres_chauffe=10))]}
    ex, _ = rejouer(reg, {"6J": m}, horloge=True)
    live = pd.DataFrame(dict(t=pd.to_datetime(ex["t"], unit="ms"), sens=np.sign(ex["position"]).astype(int)))
    fus = ref.merge(live, on="t", how="outer", suffixes=("_ref", "_live"), indicator=True)
    egal = (fus["_merge"] == "both") & (fus["sens_ref"] == fus["sens_live"])
    out = dict(evenements_reference=len(ref), evenements_direct=len(live), identiques=int(egal.sum()),
               seulement_reference=int((fus["_merge"] == "left_only").sum()), seulement_direct=int((fus["_merge"] == "right_only").sum()))
    out["parite"] = out["identiques"] / max(1, len(fus))
    ecarts = fus[~egal].head(12)
    log(f"[Gotobi] evenements : reference {len(ref)}, direct {len(live)}, identiques {out['identiques']} ({out['parite']:.2%}), "
        f"seulement reference {out['seulement_reference']}, seulement direct {out['seulement_direct']}")
    if len(ecarts):
        log("[Gotobi] premiers ecarts :\n" + ecarts.to_string(index=False))
    out["ecarts"] = ecarts
    return out


def main(cotations: str = COTATIONS, debut: str | None = None, log=print) -> dict:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    return dict(S1=verifier_s1(cotations, debut, log), Gotobi=verifier_gotobi(cotations, debut, log))
