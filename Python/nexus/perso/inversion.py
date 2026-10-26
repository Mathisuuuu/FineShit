"""Strategies inversees : memes trades (memes heures d entree et de sortie, memes prix bruts), sens oppose,
frais payes une seconde fois. Repond a la question "si on inverse une strategie perdante, devient-elle gagnante ?".

    python -m nexus.perso.inversion

Calcul exact pour un miroir : PnL inverse = -(PnL brut d origine) - frais = -(PnL net) - 2 x frais.
Le resultat est aussi donne par moitie de periode (2016-2020 / 2021-2026) : un avantage reel doit tenir sur les deux.
"""
from __future__ import annotations

import glob
import math
import os

import numpy as np
import pandas as pd

from .qf import INSTRUMENTS, Inst
from .runner import PY_DIR, TESTS


def _safe(name: str) -> str:
    return "".join(ch if ch.isalnum() else "_" for ch in name)[:60]


def _latest_trades(name: str) -> str | None:
    files = glob.glob(os.path.join(PY_DIR, "resultats", "perso_*", f"trades_*_{_safe(name)}.csv"))
    return max(files, key=lambda f: os.path.basename(os.path.dirname(f))) if files else None


def _inst(spec) -> Inst | None:
    if spec["kind"] in ("qf", "user"):
        return INSTRUMENTS[spec["inst"]]
    if spec["kind"] == "pairs":
        return Inst("6B x10k", "6B", 10000.0, 0.0001, 0.6)
    return None


def mirror(name: str, spec: dict) -> pd.DataFrame | None:
    """-> DataFrame (date de sortie, pnl d origine, frais, pnl inverse) ou None."""
    f = _latest_trades(name)
    if f is None or os.path.getsize(f) < 5:
        return None
    t = pd.read_csv(f)
    if t.empty:
        return None
    if "net_pnl" in t.columns:                                   # moteur Nexus (fiches)
        return pd.DataFrame({"date": pd.to_datetime(t["exit_time"]), "net": t["net_pnl"], "frais": t["costs"],
                             "inverse": -t["gross_pnl"] - t["costs"]})
    inst = _inst(spec)
    if inst is None or "qty" not in t.columns:
        return None
    q = t["qty"].astype(float)
    com = 2 * inst.commission * q
    # glissement : entree au marche (sauf ordres limites de l ICT), sortie au marche / stop (sauf objectif = limite)
    entry_slip = np.where(t["tag"].astype(str).str.startswith("ICT"), 0, 1)
    exit_slip = np.where(t["reason"].astype(str) == "objectif", 0, 1)
    slip = (entry_slip + exit_slip) * inst.tick * inst.point_value * q
    frais = com + slip
    return pd.DataFrame({"date": pd.to_datetime(t["exit_time"]), "net": t["pnl"], "frais": frais, "inverse": -t["pnl"] - 2 * frais})


def _sharpe(df: pd.DataFrame, col: str) -> float:
    d = df.groupby(df["date"].dt.normalize())[col].sum()
    if len(d) < 2:
        return math.nan
    full = d.reindex(pd.bdate_range(d.index.min(), d.index.max()), fill_value=0.0)
    sd = full.std(ddof=1)
    return float(full.mean() / sd * math.sqrt(252)) if sd > 0 else math.nan


def main():
    lines = ["Strategie | trades | PnL net d origine | frais payes | PnL si inverse | Sharpe inverse | inverse 2016-2020 | "
             "inverse 2021-2026 | conclusion"]
    rows = []
    for name, src, spec, note in TESTS:
        m = mirror(name, spec)
        if m is None or m["net"].sum() >= 0:
            continue                                              # seulement les strategies negatives
        inv = m["inverse"].sum()
        h1 = m.loc[m["date"] < "2021-01-01", "inverse"].sum()
        h2 = m.loc[m["date"] >= "2021-01-01", "inverse"].sum()
        sh = _sharpe(m, "inverse")
        n1 = int((m["date"] < "2021-01-01").sum())
        if inv <= 0:
            concl = "reste NEGATIVE (les frais dominent)"
        elif n1 == 0:
            concl = "positive mais testee sur une seule periode (donnees recentes seulement) : non verifiable"
        elif h1 > 0 and h2 > 0 and sh >= 0.5:
            concl = "POSITIVE et stable sur les deux periodes"
        elif h1 > 0 and h2 > 0:
            concl = "positive sur les deux periodes mais faible"
        else:
            concl = "positive au total mais instable (une periode negative)"
        rows.append((sh if math.isfinite(sh) else -99, name, len(m), m["net"].sum(), m["frais"].sum(), inv, sh, h1, h2, concl))
    rows.sort(key=lambda r: -r[0])
    f = lambda x: f"{x:+,.0f} $".replace(",", " ")
    for _, name, n, net, fr, inv, sh, h1, h2, concl in rows:
        lines.append(f"{name} | {n} | {f(net)} | {fr:,.0f} $".replace(",", " ")
                     + f" | {f(inv)} | {sh:.2f} | {f(h1)} | {f(h2)} | {concl}")
    out = os.path.join(PY_DIR, "recherche", "resultats_inversees.txt")
    with open(out, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")
    print("\n".join(lines))
    print(f"\n-> {out}")


if __name__ == "__main__":
    main()
