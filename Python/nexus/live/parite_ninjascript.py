"""Parite des strategies NinjaScript du Groupe avec la recherche (memes ordres ?).

    python -m nexus.live.parite_ninjascript [--cotations ../Cotations] [--debut 2016-01-01]

La logique des strategies NinjaTrader (AddOns/NexusGroupeLogique.cs, sans type NinjaTrader) est compilee dans le banc
Tests/PariteGroupe et rejouee sur les barres 1 minute de la recherche (Databento, depot Cotations) :
  S1     : comparee a S1_NoiseAreaNQ.backtest (memes rolls ajustes, meme capital du jour) : jour, heure, position ;
  Gotobi : comparee a gotobi.signaux (memes rolls ajustes) : instant et sens de chaque position ;
  M2     : comparee a perso.kairos_publiees.trades(NQ, "K5") (meme serie continue) : instant et sens (ajoute le
           2026-10-25 ; M2 est a confirmer hors echantillon, la strategie NinjaScript n est pas deployee).
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
import tempfile

import numpy as np
import pandas as pd

from .verification import COTATIONS, NY_S1, REF, _positions_reference

ICI = os.path.dirname(os.path.abspath(__file__))
BANC = os.path.normpath(os.path.join(ICI, "..", "..", "..", "Tests", "PariteGroupe"))


def _csv_barres(df: pd.DataFrame, f: str) -> None:
    t = pd.DatetimeIndex(df.index).tz_convert("UTC").as_unit("ms").asi8
    a = np.column_stack([t, df["open"].to_numpy(float), df["high"].to_numpy(float), df["low"].to_numpy(float),
                         df["close"].to_numpy(float), df["volume"].to_numpy(float)])
    np.savetxt(f, a, delimiter=",", fmt=["%d", "%.10g", "%.10g", "%.10g", "%.10g", "%.10g"])


def _banc(mode: str, barres: str, sortie: str, capital: str | None = None, log=print) -> pd.DataFrame:
    cmd = ["dotnet", "run", "-c", "Release", "--project", os.path.join(BANC, "PariteGroupe.csproj"), "--", mode, barres, sortie]
    if capital:
        cmd.append(capital)
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode:
        raise RuntimeError(r.stdout + r.stderr)
    log(f"[{mode}] banc C# : {r.stdout.strip().splitlines()[-1]}")
    return pd.read_csv(sortie)


def parite_s1(cotations: str, debut: str | None, dossier: str, log=print) -> dict:
    df, _ = REF.lire_minutes(os.path.join(cotations, "indices", "NQ_v0_1m.parquet"), REF.NY, "debut")
    df, _ = REF.ajuster_rolls(df)
    if debut:
        df = df[df.index >= pd.Timestamp(debut, tz="UTC")]
    eq, trades = REF.backtest(df, 1_000_000.0)
    ny = df.index.tz_convert(NY_S1)
    mn = ny.hour * 60 + ny.minute
    rth = df[(mn >= 9 * 60 + 25) & (mn <= 16 * 60 + 5)]
    fb, fc, fo = (os.path.join(dossier, x) for x in ("s1_barres.csv", "s1_capital.csv", "s1_ordres.csv"))
    _csv_barres(rth, fb)
    cap = eq["equity"].shift(1).fillna(1_000_000.0)
    pd.DataFrame(dict(j=[int(d.strftime("%Y%m%d")) for d in eq.index], c=cap.to_numpy())).to_csv(fc, header=False, index=False,
                                                                                                   float_format="%.17g")
    ex = _banc("s1", fb, fo, fc, log)
    h = pd.to_datetime(ex["t"], unit="ms", utc=True).dt.tz_convert(NY_S1)
    cs = pd.DataFrame(dict(jour=h.dt.normalize().dt.tz_localize(None).astype("datetime64[ns]"), heure=h.dt.strftime("%H:%M"), position=ex["position"]))
    ref = _positions_reference(trades)
    ref["jour"] = ref["jour"].astype("datetime64[ns]")
    fus = ref.merge(cs, on=["jour", "heure"], how="outer", suffixes=("_ref", "_cs"), indicator=True)
    egal = (fus["_merge"] == "both") & (fus["position_ref"] == fus["position_cs"])
    out = dict(reference=len(ref), csharp=len(cs), identiques=int(egal.sum()), parite=float(egal.sum() / max(1, len(fus))))
    log(f"[S1] ordres : recherche {len(ref)}, NinjaScript {len(cs)}, identiques {out['identiques']} ({out['parite']:.2%})")
    if not egal.all():
        log("[S1] premiers ecarts :\n" + fus[~egal].head(10).to_string(index=False))
    return out


def parite_gotobi(cotations: str, debut: str | None, dossier: str, log=print) -> dict:
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
    mi = m.copy()
    mi.index = mi.index.tz_convert("UTC").tz_localize(None)
    (E, X, SE, SX), _ = G.signaux(mi, dict(G.DEFAULTS))
    pos, ref = 0, []
    for t, e, x, se, sx in zip(mi.index, E.to_numpy(), X.to_numpy(), SE.to_numpy(), SX.to_numpy()):
        nv = pos
        if sx and nv < 0:
            nv = 0
        if x and nv > 0:
            nv = 0
        if se:
            nv = -1
        if e:
            nv = 1
        if nv != pos:
            ref.append((t, nv))
            pos = nv
    ref = pd.DataFrame(ref, columns=["t", "sens"])
    fb, fo = os.path.join(dossier, "g_barres.csv"), os.path.join(dossier, "g_ordres.csv")
    _csv_barres(m, fb)
    ex = _banc("gotobi", fb, fo, None, log)
    cs = pd.DataFrame(dict(t=pd.to_datetime(ex["t"], unit="ms"), sens=np.sign(ex["position"]).astype(int)))
    fus = ref.merge(cs, on="t", how="outer", suffixes=("_ref", "_cs"), indicator=True)
    egal = (fus["_merge"] == "both") & (fus["sens_ref"] == fus["sens_cs"])
    out = dict(reference=len(ref), csharp=len(cs), identiques=int(egal.sum()), parite=float(egal.sum() / max(1, len(fus))))
    log(f"[Gotobi] ordres : recherche {len(ref)}, NinjaScript {len(cs)}, identiques {out['identiques']} ({out['parite']:.2%})")
    if not egal.all():
        log("[Gotobi] ecarts :\n" + fus[~egal].head(10).to_string(index=False))
    return out


def parite_m2(debut: str | None, dossier: str, log=print) -> dict:
    from ..perso import kairos_publiees as KP
    from ..perso.soixante import NS_MIN, marche
    m = marche("NQ")
    f = KP.trades(m, "K5")
    ok = f[f["motif"] == ""]
    ref = pd.concat([pd.DataFrame(dict(t=ok["t_entree"].to_numpy(np.int64), sens=ok["sens"].to_numpy(int))),
                     pd.DataFrame(dict(t=ok["t_sortie"].to_numpy(np.int64), sens=0))]).sort_values("t")
    debut_ns = m.t - NS_MIN
    barres = pd.DataFrame(dict(t=debut_ns // 1_000_000, o=m.o, h=m.h, l=m.l, c=m.c, v=0.0, d=m.offset))
    if debut:
        coupe = pd.Timestamp(debut).value
        barres = barres[debut_ns >= coupe]
        ref = ref[ref["t"] >= coupe]
    ref["t"] = pd.to_datetime(ref["t"], unit="ns")
    fb, fo = os.path.join(dossier, "m2_barres.csv"), os.path.join(dossier, "m2_ordres.csv")
    barres.to_csv(fb, header=False, index=False, float_format="%.10g", na_rep="NaN")
    ex = _banc("m2", fb, fo, None, log)
    cs = pd.DataFrame(dict(t=pd.to_datetime(ex["t"], unit="ms"), sens=np.sign(ex["position"]).astype(int)))
    fus = ref.merge(cs, on="t", how="outer", suffixes=("_ref", "_cs"), indicator=True)
    egal = (fus["_merge"] == "both") & (fus["sens_ref"] == fus["sens_cs"])
    out = dict(reference=len(ref), csharp=len(cs), identiques=int(egal.sum()), parite=float(egal.sum() / max(1, len(fus))))
    log(f"[M2] ordres : recherche {len(ref)}, NinjaScript {len(cs)}, identiques {out['identiques']} ({out['parite']:.2%})")
    if not egal.all():
        log("[M2] ecarts :\n" + fus[~egal].head(10).to_string(index=False))
    return out


def main(argv=None) -> dict:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(prog="python -m nexus.live.parite_ninjascript")
    ap.add_argument("--cotations", default=COTATIONS)
    ap.add_argument("--debut", default=None)
    a = ap.parse_args(argv)
    with tempfile.TemporaryDirectory(prefix="parite_nt_") as d:
        return dict(S1=parite_s1(a.cotations, a.debut, d), Gotobi=parite_gotobi(a.cotations, a.debut, d),
                    M2=parite_m2(a.debut, d))


if __name__ == "__main__":
    main()
