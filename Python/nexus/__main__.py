"""Ligne de commande Nexus (Python + vectorbt).

    python -m nexus liste
    python -m nexus verifier   --donnees C:/Users/Mathis/Desktop/Cotations
    python -m nexus backtest   --strategie 01 --donnees DOSSIER [--debut 2012-01-01] [--param target_vol_pct=10] [--html]
    python -m nexus backtest   --strategie 01 --synthetique          (demonstration sans donnees)
    python -m nexus tout       --donnees DOSSIER                     (toutes les fiches, tableau recapitulatif)
    python -m nexus grille     --strategie 01 --donnees DOSSIER --param lookback_days=126,252 --param skip_days=0,21
    python -m nexus recherche  --type tsmom --donnees DOSSIER --param lookback=63,126,252 --param skip=0,21
"""
from __future__ import annotations

import argparse
import itertools
import math
import os
import sys
import time
from datetime import datetime

import numpy as np
import pandas as pd

from . import data as D
from . import mathx as M
from . import validation as V
from .engine import split_list
from .report import build_report
from .strategies import available, get

REPO_DATA = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "..", "Data"))
EXTERNAL_FILES = {"fundamentals_file": "fundamentals.csv", "factors_file": "ff_factors.csv",
                  "earnings_file": "earnings.csv", "macro_file": "macro_events.csv", "gex_file": "gex.csv"}


def _value(v: str):
    s = v.strip()
    if s.lower() in ("true", "vrai", "oui", "yes"):
        return True
    if s.lower() in ("false", "faux", "non", "no"):
        return False
    try:
        return int(s)
    except ValueError:
        pass
    try:
        return float(s)
    except ValueError:
        return s


def _params(items, grid=False):
    out = {}
    for it in items or []:
        if "=" not in it:
            raise SystemExit(f"--param attendu sous la forme nom=valeur : {it}")
        k, v = it.split("=", 1)
        k = k.strip()
        if grid:
            out[k] = [_value(x) for x in v.split(",")] if "," in v and k not in ("symbols", "reference_symbols") else [_value(v)]
        else:
            out[k] = _value(v)
    return out


def _external_params(klass, folder):
    """Branche les fichiers Data/*.csv (fondamentaux, facteurs, resultats, agenda macro) s ils existent."""
    out = {}
    defaults = {}
    for c in reversed(klass.__mro__):
        defaults.update(getattr(c, "DEFAULTS", {}) or {})
    for key, fname in EXTERNAL_FILES.items():
        p = os.path.join(folder, fname) if folder else None
        if key in defaults and p and os.path.exists(p):
            out[key] = p
    return out


def _load(args, klass=None, params=None):
    if getattr(args, "synthetique", False):
        return None
    if not args.donnees:
        raise SystemExit("indiquer --donnees DOSSIER (ou --synthetique pour une demonstration)")
    if klass is not None and getattr(klass, "INTRADAY", False):
        # Barres minute : seuls les fichiers des symboles utiles sont lus, sans agregation en jour.
        need = klass(**(params or {})).data_symbols()
        data = D.load_folder(args.donnees, daily=False, verbose=getattr(args, "verbeux", False), only=need)
    else:
        data = D.load_folder(args.donnees, verbose=getattr(args, "verbeux", False))
    if not data:
        raise SystemExit(f"aucun fichier de cotations lisible dans {args.donnees}")
    return data


def _synthetic_for(klass, params):
    st = klass(**params)
    if getattr(klass, "INTRADAY", False):
        from . import intraday as I
        print("ATTENTION : barres minute SYNTHETIQUES (marche aleatoire, demonstration du moteur) - aucun resultat n est significatif.")
        return {st.data_symbols()[0]: I.synthetic_minutes("2016-01-04", "2025-12-31")}
    syms = set(split_list(st.p.symbols)) | set(st.required_references()) | set(split_list(st.p.reference_symbols))
    print("ATTENTION : donnees SYNTHETIQUES (demonstration du moteur) - aucun resultat n est significatif.")
    return D.synthetic_universe(sorted(syms), "2010-01-04", "2025-12-31")


def _out_dir(base, name):
    d = os.path.join(base, f"{name}_{datetime.now():%Y%m%d_%H%M%S}")
    os.makedirs(d, exist_ok=True)
    return d


def _save(res, folder, html=False):
    with open(os.path.join(folder, "rapport.txt"), "w", encoding="utf-8") as f:
        f.write(res.report)
    res.trades_frame().to_csv(os.path.join(folder, "trades.csv"), index=False)
    res.fills.to_csv(os.path.join(folder, "fills.csv"), index=False)
    pd.DataFrame({"equity": res.equity, "exposition_brute": res.exposure}).to_csv(os.path.join(folder, "equity.csv"))
    with open(os.path.join(folder, "journal.txt"), "w", encoding="utf-8") as f:
        f.write("\n".join(res.log + [""] + res.breaker_events))
    if getattr(res, "daily_panel", None) is not None:
        res.daily_panel.to_csv(os.path.join(folder, "jours.csv"))
    if html:
        from .vbt_bridge import html_report
        html_report(res, os.path.join(folder, "graphique.html"))


# =============================================================================
def cmd_liste(args):
    for code in available():
        k = get(code)
        print(f"{code:4} {k.NAME:36} {k.DESCRIPTION}")
        if args.details:
            for key, v in sorted(k().params.items()):
                print(f"       {key} = {v}")


def cmd_verifier(args):
    data = D.load_folder(args.donnees, verbose=True)
    found = {k.upper() for k in data}
    print(f"\n{len(data)} series lues dans {args.donnees}\n")
    missing_all = {}
    for code in available():
        k = get(code)
        st = k()
        need = list(dict.fromkeys(split_list(st.p.symbols) + st.required_references()))
        miss = [s for s in need if s.upper() not in found]
        short = []
        for s in need:
            df = data.get(s) if s in data else next((v for kk, v in data.items() if kk.upper() == s.upper()), None)
            if df is not None and len(df) and (df.index[-1] - df.index[0]).days < 3 * 365:
                short.append(f"{s} ({(df.index[-1] - df.index[0]).days / 365.25:.1f} ans)")
        status = "OK" if not miss else f"{len(miss)} manquant(s)"
        print(f"{code:4} {k.NAME:36} {len(need) - len(miss)}/{len(need)} {status}")
        if miss:
            print("       manquants : " + ", ".join(miss))
        if short:
            print("       historique < 3 ans (chauffage insuffisant) : " + ", ".join(short))
        for s in miss:
            missing_all.setdefault(s, []).append(code)
    if missing_all:
        print("\nA ajouter au dossier (symbole -> fiches) :")
        for s, codes in sorted(missing_all.items()):
            print(f"  {s:10} -> {', '.join(codes)}")
    else:
        print("\nToutes les cotations requises sont presentes.")


def cmd_backtest(args):
    klass = get(args.strategie)
    params = {**_external_params(klass, args.externes), **_params(args.param)}
    data = _load(args, klass, params) if not args.synthetique else _synthetic_for(klass, params)
    t = time.time()
    st = klass(**params)
    res = st.run(data, start=args.debut, end=args.fin, trade_start=args.debut_trading)
    print(res.report)
    folder = _out_dir(args.sortie, st.strategy_id)
    _save(res, folder, args.html)
    print(f"[nexus] {time.time() - t:.1f} s - resultats ecrits dans {folder}")


def cmd_tout(args):
    data = _load(args)
    rows = []
    folder = _out_dir(args.sortie, "tout")
    for code in available():
        klass = get(code)
        if getattr(klass, "INTRADAY", False):
            print(f"{code} ignoree : barres 1 minute requises (python -m nexus backtest -s {code} -d DOSSIER_MINUTE)")
            continue
        st = klass(**_external_params(klass, args.externes))
        try:
            res = st.run(data, start=args.debut, end=args.fin, trade_start=args.debut_trading)
        except ValueError as ex:
            print(f"{code} ignoree : {ex}")
            continue
        sub = os.path.join(folder, st.strategy_id)
        os.makedirs(sub, exist_ok=True)
        _save(res, sub, args.html)
        eq = res.equity
        rows.append(dict(fiche=code, strategie=st.NAME, trades=len(res.trades),
                         rendement=eq.iloc[-1] / eq.iloc[0] - 1, sharpe=V.annualized_sharpe(res.returns.values),
                         dd_max=V.max_drawdown(eq.values), expo_moy=float(res.exposure.mean()),
                         pnl_net=sum(x.net_pnl for x in res.trades)))
        print(f"{code} termine")
    tab = pd.DataFrame(rows)
    tab.to_csv(os.path.join(folder, "recapitulatif.csv"), index=False)
    with pd.option_context("display.float_format", "{:.4f}".format, "display.width", 200):
        print(tab.to_string(index=False))
    print(f"[nexus] resultats ecrits dans {folder}")


def cmd_grille(args):
    klass = get(args.strategie)
    grid = _params(args.param, grid=True)
    base = {**_external_params(klass, args.externes), **{k: v[0] for k, v in grid.items() if len(v) == 1}}
    grid = {k: v for k, v in grid.items() if len(v) > 1}          # parametres fixes : hors des libelles
    first = {**base, **{k: v[0] for k, v in grid.items()}}
    data = _load(args, klass, first) if not args.synthetique else _synthetic_for(klass, first)
    keys = list(grid)
    rets, rows, results = {}, [], {}
    combos = list(itertools.product(*[grid[k] for k in keys])) or [()]
    print(f"[nexus] {len(combos)} configurations")
    for combo in combos:
        kw = dict(zip(keys, combo))
        st = klass(**base, **kw)
        res = st.run(data, start=args.debut, end=args.fin, trade_start=args.debut_trading, report=False)
        label = ",".join(f"{k}={v}" for k, v in kw.items()) or "defaut"
        rets[label] = res.returns
        results[label] = res
        eq = res.equity
        rows.append(dict(config=label, trades=len(res.trades), rendement=eq.iloc[-1] / eq.iloc[0] - 1,
                         sharpe=V.annualized_sharpe(res.returns.values), dd_max=V.max_drawdown(eq.values),
                         expo_moy=float(res.exposure.mean())))
        print(f"  {label:60} sharpe {rows[-1]['sharpe']:.2f}  trades {len(res.trades)}")
    raw = pd.DataFrame(rows)
    tab = raw.sort_values("sharpe", ascending=False)
    rmat = pd.DataFrame(rets).dropna()
    srs = [V.sharpe_per_period(rmat[c].values) for c in rmat]
    var_sr = float(np.var([s for s in srs if M.ok(s)], ddof=1)) if len(srs) > 1 else M.NAN
    pbo, combos_used = V.pbo(rmat.T.values) if rmat.shape[1] >= 2 else (M.NAN, 0)
    best = tab.iloc[0]["config"]
    res = results[best]
    extras = []
    res.strategy.report_extras(extras)
    res.report = build_report(res, extras + [res.stress], trials=len(combos), var_trials_sharpe=var_sr,
                              pbo=pbo, pbo_configs=rmat.shape[1], pbo_combos=combos_used)
    print(res.report)
    folder = _out_dir(args.sortie, res.strategy.strategy_id + "_grille")
    tab.to_csv(os.path.join(folder, "grille.csv"), index=False)
    rmat.to_csv(os.path.join(folder, "rendements_par_config.csv"))
    _save(res, folder, args.html)
    if args.walkforward:
        train, test = (int(x) for x in args.walkforward.split("/"))
        oos = []
        chosen = []
        for a, b, c, d in V.walk_forward_splits(len(rmat), train, test):
            tr = rmat.iloc[a:b]
            pick = max(tr.columns, key=lambda col: (V.sharpe_per_period(tr[col].values) if M.ok(V.sharpe_per_period(tr[col].values)) else -1e9))
            chosen.append(pick)
            oos.append(rmat[pick].iloc[c:d])
        if oos:
            o = pd.concat(oos)
            sr_oos = V.annualized_sharpe(o.values)
            wf = (f"Walk-forward {train}/{test} : {len(oos)} fenetres, Sharpe hors echantillon {sr_oos:.2f} "
                  f"(meilleure config en echantillon : {tab.iloc[0]['sharpe']:.2f}) ; configurations choisies : "
                  + ", ".join(f"{k} x{v}" for k, v in pd.Series(chosen).value_counts().items()))
            print(wf)
            o.to_csv(os.path.join(folder, "walkforward_oos.csv"))
            with open(os.path.join(folder, "rapport.txt"), "a", encoding="utf-8") as f:
                f.write("\n" + wf + "\n")
    with pd.option_context("display.float_format", "{:.4f}".format, "display.width", 200):
        print(tab.to_string(index=False))
    if len(keys) >= 1 and len(combos) > 1:
        plateau = _plateau(raw, combos, keys, grid, folder, args.html)
        print(plateau)
        with open(os.path.join(folder, "rapport.txt"), "a", encoding="utf-8") as f:
            f.write("\n" + plateau + "\n")
    print(f"[nexus] PBO {pbo:.1%} sur {rmat.shape[1]} configurations - resultats dans {folder}" if M.ok(pbo) else f"[nexus] resultats dans {folder}")


def _plateau(raw, combos, keys, grid, folder, html=False) -> str:
    """Plateau de parametres : Sharpe des configurations voisines (un pas sur un seul parametre) de la
    meilleure, part des configurations proches de la meilleure, tableaux croises (moyenne sur les autres
    parametres) et cartes de chaleur HTML."""
    sh = dict(zip(combos, raw["sharpe"].to_numpy(float)))
    best = max(sh, key=lambda k: sh[k] if M.ok(sh[k]) else -1e9)
    pos = [list(grid[k]).index(v) for k, v in zip(keys, best)]
    neigh = []
    for i, k in enumerate(keys):
        for step in (-1, 1):
            j = pos[i] + step
            if 0 <= j < len(grid[k]):
                c = list(best)
                c[i] = grid[k][j]
                if tuple(c) in sh and M.ok(sh[tuple(c)]):
                    neigh.append(sh[tuple(c)])
    b = sh[best]
    vals = np.array([v for v in sh.values() if M.ok(v)])
    out = ["--- Plateau de parametres -----------------------------------------------------",
           f"Meilleure : {', '.join(f'{k}={v}' for k, v in zip(keys, best))} (Sharpe {b:.2f})"]
    if neigh:
        out.append(f"Voisins ({len(neigh)}) : Sharpe moyen {np.mean(neigh):.2f}, minimum {np.min(neigh):.2f}"
                   + (f" -> {np.mean(neigh) / b:.0%} du meilleur" if b > 0 else "")
                   + ("  -> PIC ISOLE (pas de plateau)" if b > 0 and np.mean(neigh) < 0.7 * b else ""))
    if b > 0 and len(vals):
        out.append(f"Configurations a >= 75 % du meilleur Sharpe : {(vals >= 0.75 * b).mean():.0%} ; Sharpe > 0 : {(vals > 0).mean():.0%}")
    frame = pd.DataFrame(list(sh.keys()), columns=keys)
    frame["sharpe"] = list(sh.values())
    figs = []
    for a, c in itertools.combinations([k for k in keys if len(grid[k]) > 1], 2):
        pv = frame.pivot_table(index=a, columns=c, values="sharpe", aggfunc="mean")
        out.append(f"Sharpe moyen {a} (lignes) x {c} (colonnes) :")
        out.append(pv.to_string(float_format=lambda x: f"{x:6.2f}"))
        figs.append((a, c, pv))
    if html and figs:
        import plotly.graph_objects as go
        from plotly.subplots import make_subplots
        fig = make_subplots(rows=len(figs), cols=1, subplot_titles=[f"Sharpe : {a} x {c}" for a, c, _ in figs])
        for i, (a, c, pv) in enumerate(figs, 1):
            fig.add_trace(go.Heatmap(z=pv.values, x=[str(x) for x in pv.columns], y=[str(y) for y in pv.index],
                                     colorscale="RdYlGn", zmid=0, text=np.round(pv.values, 2), texttemplate="%{text}",
                                     showscale=(i == 1)), i, 1)
            fig.update_xaxes(title_text=c, row=i, col=1)
            fig.update_yaxes(title_text=a, row=i, col=1)
        fig.update_layout(height=380 * len(figs), template="plotly_white")
        fig.write_html(os.path.join(folder, "plateau.html"), include_plotlyjs="cdn")
        out.append(f"Cartes de chaleur : {os.path.join(folder, 'plateau.html')}")
    return "\n".join(out)


def cmd_recherche(args):
    from . import vbt_bridge as VB
    from .strategies.s01_tsmom import UNIVERSE_25
    syms = split_list(args.symboles or UNIVERSE_25)
    if args.synthetique:
        print("ATTENTION : donnees SYNTHETIQUES - aucun resultat n est significatif.")
        data = D.synthetic_universe(syms, "2010-01-04", "2025-12-31")
    else:
        data = _load(args)
    grid = _params(args.param, grid=True)
    tab, rmat, (pbo, combos) = VB.grid(data, syms, args.type, start=args.debut, end=args.fin, **grid)
    with pd.option_context("display.float_format", "{:.4f}".format, "display.width", 200):
        print(tab.to_string(index=False))
    print(f"PBO (CSCV) : {pbo:.1%} sur {rmat.shape[1]} configurations ({combos} combinaisons)" if M.ok(pbo) else "PBO : n/a")
    print("Rappel : grille vectorbt SIGNAL SEUL (sans module B ni stops) - pour explorer, pas pour valider.")


def main(argv=None):
    ap = argparse.ArgumentParser(prog="python -m nexus", description="Backtests Nexus en Python (vectorbt).")
    sub = ap.add_subparsers(dest="cmd", required=True)

    def common(p, strategy=True):
        if strategy:
            p.add_argument("--strategie", "-s", required=True, help="numero de fiche (01, 02, 03, 4A, 05, 06, 12, 13, 14, 16)")
        p.add_argument("--donnees", "-d", help="dossier des cotations (CSV/TXT)")
        p.add_argument("--synthetique", action="store_true", help="donnees synthetiques (demonstration)")
        p.add_argument("--debut", help="premiere date chargee (AAAA-MM-JJ)")
        p.add_argument("--fin", help="derniere date chargee")
        p.add_argument("--debut-trading", dest="debut_trading", help="premier jour de trading (chauffage avant)")
        p.add_argument("--param", "-p", action="append", help="parametre nom=valeur (repetable)")
        p.add_argument("--externes", default=REPO_DATA if os.path.isdir(REPO_DATA) else None,
                       help="dossier des fichiers Data/*.csv (fondamentaux, facteurs, resultats, agenda)")
        p.add_argument("--sortie", default="resultats", help="dossier de sortie")
        p.add_argument("--html", action="store_true", help="graphique interactif (vectorbt/plotly)")
        p.add_argument("--verbeux", action="store_true")

    p = sub.add_parser("liste", help="strategies disponibles")
    p.add_argument("--details", action="store_true")
    p.set_defaults(func=cmd_liste)
    p = sub.add_parser("verifier", help="cotations presentes / manquantes par strategie")
    p.add_argument("--donnees", "-d", required=True)
    p.set_defaults(func=cmd_verifier)
    p = sub.add_parser("backtest", help="un backtest complet + rapport")
    common(p)
    p.set_defaults(func=cmd_backtest)
    p = sub.add_parser("tout", help="toutes les strategies sur le meme dossier")
    common(p, strategy=False)
    p.set_defaults(func=cmd_tout)
    p = sub.add_parser("grille", help="grille de parametres (moteur complet) + PBO / DSR / walk-forward")
    common(p)
    p.add_argument("--walkforward", help="fenetres entrainement/test en jours, ex. 180/30")
    p.set_defaults(func=cmd_grille)
    p = sub.add_parser("recherche", help="grille vectorbt rapide, signal seul (tsmom | xsmom)")
    common(p, strategy=False)
    p.add_argument("--type", choices=("tsmom", "xsmom"), default="tsmom")
    p.add_argument("--symboles")
    p.set_defaults(func=cmd_recherche)
    args = ap.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
