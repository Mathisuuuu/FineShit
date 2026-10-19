"""Ligne de commande Nexus (Python + vectorbt).

    python -m nexus liste [--details]
    python -m nexus verifier   -d DOSSIER [--profil futures]
    python -m nexus backtest   -s 01 -d DOSSIER [--profil futures] [-p target_vol_pct=10] [--html]
    python -m nexus backtest   -s 01 --synthetique                      (demonstration sans donnees)
    python -m nexus tout       -d DOSSIER [--profil futures] [--donnees-minute DOSSIER]  (toutes les fiches + portefeuille)
    python -m nexus grille     -s 01 -d DOSSIER -p lookback_days=126,252 --walkforward 180/30
    python -m nexus valider    [-s 01] [--profil futures] [--audit claude]  (module C complet, verdict par fiche)
    python -m nexus recherche  --type tsmom -d DOSSIER -p lookback=63,126,252 -p skip=0,21
    python -m nexus regime     -d DOSSIER [--barometre ES] [--html]      (module A : HMM + terciles)
    python -m nexus portefeuille --resultats resultats/tout_...          (module C : correlation, check-list)
    python -m nexus actualites -s 07 [--reddit] [--resultats-av] [--prenoter]   (collecte NewsAPI / Reddit / Fear & Greed)
    python -m nexus audit      --rapport resultats/.../rapport.txt [--fournisseur claude]  (module C : seconde IA)
    python -m nexus tableau    [--cotations ../Cotations] [--seulement S1,G1]  (export du tableau de bord Node.js)
"""
from __future__ import annotations

import argparse
import glob
import itertools
import os
import time
from datetime import datetime
from types import SimpleNamespace

import numpy as np
import pandas as pd

from . import data as D
from . import mathx as M
from . import validation as V
from .engine import split_list
from .profiles import DESCRIPTIONS, available_profiles, profile_codes, profile_params
from .report import build_report
from .strategies import available, get

REPO_DATA = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "..", "Data"))
REPO_QUOTES = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "..", "Cotations"))
EXTERNAL_FILES = {"fundamentals_file": "fundamentals.csv", "factors_file": "ff_factors.csv",
                  "earnings_file": "earnings.csv", "macro_file": "macro_events.csv", "news_file": "news.csv",
                  "news_live_file": "news_live.csv", "gex_file": "gex.csv"}


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
            out[k] = [_value(x) for x in v.split(",")] if "," in v and k not in ("symbols", "reference_symbols", "pairs_list") else [_value(v)]
        else:
            out[k] = _value(v)
    return out


def _defaults(klass) -> dict:
    defaults = {}
    for c in reversed(klass.__mro__):
        defaults.update(getattr(c, "DEFAULTS", {}) or {})
    return defaults


def _external_params(klass, folder):
    """Branche les fichiers Data/*.csv (fondamentaux, facteurs, resultats, agenda, actualites) s ils existent."""
    out = {}
    defaults = _defaults(klass)
    for key, fname in EXTERNAL_FILES.items():
        p = os.path.join(folder, fname) if folder else None
        if key in defaults and p and os.path.exists(p):
            out[key] = p
    return out


def _strategy_params(code, klass, args, user=None):
    """Parametres d une fiche : fichiers externes < profil < ligne de commande."""
    prof = profile_params(getattr(args, "profil", None), code)
    if prof is None:
        return None
    return {**_external_params(klass, getattr(args, "externes", None)), **prof, **(user if user is not None else _params(getattr(args, "param", None)))}


_DATA_CACHE: dict = {}


def _load(args, minutes: int = 0):
    """Charge le dossier de cotations (memoire partagee entre fiches d une meme commande)."""
    if getattr(args, "synthetique", False):
        return None
    folder = args.donnees or (REPO_QUOTES if os.path.isdir(REPO_QUOTES) else None)
    if not folder:
        raise SystemExit("indiquer --donnees DOSSIER (ou --synthetique pour une demonstration)")
    key = (os.path.abspath(folder), minutes, getattr(args, "ajustement", "proportionnel"))
    if key in _DATA_CACHE:
        return _DATA_CACHE[key]
    t = time.time()
    data = D.load_folder(folder, verbose=getattr(args, "verbeux", False), daily=minutes <= 0,
                         intraday_minutes=minutes, adjust=getattr(args, "ajustement", "proportionnel"))
    if not data:
        raise SystemExit(f"aucun fichier de cotations lisible dans {folder}")
    print(f"[nexus] {len(data)} series chargees depuis {folder} en {time.time() - t:.1f} s"
          + (f" (barres {minutes} min)" if minutes > 0 else " (barres de seance)"))
    _DATA_CACHE[key] = data
    return data


def _load_intraday(args, st):
    """Fiche minute (INTRADAY : fiche 16, S1) : seuls les fichiers des symboles utiles, barres 1 minute brutes
    (la fiche ajuste elle-meme les roulements)."""
    folder = getattr(args, "donnees_minute", None) or args.donnees or (REPO_QUOTES if os.path.isdir(REPO_QUOTES) else None)
    if not folder:
        raise SystemExit("indiquer --donnees DOSSIER (ou --synthetique pour une demonstration)")
    key = (os.path.abspath(folder), "brut", tuple(st.data_symbols()))
    if key not in _DATA_CACHE:
        data = D.load_folder(folder, daily=False, verbose=getattr(args, "verbeux", False), only=st.data_symbols())
        if not data:
            raise SystemExit(f"aucune serie {', '.join(st.data_symbols())} dans {folder}")
        _DATA_CACHE[key] = data
    return _DATA_CACHE[key]


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
    if getattr(res, "signals", None):
        pd.DataFrame(res.signals, columns=["time", "symbol", "kind", "detail"]).to_csv(os.path.join(folder, "signaux.csv"), index=False)
    if getattr(res, "daily_panel", None) is not None:
        res.daily_panel.to_csv(os.path.join(folder, "jours.csv"))
    if html:
        try:
            from .vbt_bridge import html_report
            html_report(res, os.path.join(folder, "graphique.html"))
        except Exception as ex:  # pragma: no cover
            print(f"[nexus] graphique HTML impossible : {ex}")


def _run_one(code, args, data_by_minutes=None, report=True):
    klass = get(code)
    params = _strategy_params(code, klass, args)
    if params is None:
        return None, None
    st = klass(**params)
    if args.synthetique:
        data = _synthetic_for(klass, params)
    elif getattr(klass, "INTRADAY", False):
        data = _load_intraday(args, st)
    else:
        data = _load(args, st.bar_minutes())
    res = st.run(data, start=args.debut, end=args.fin, trade_start=args.debut_trading, report=report)
    return st, res


# =============================================================================
def cmd_liste(args):
    for code in available():
        k = get(code)
        print(f"{code:4} {k.NAME:36} {k.DESCRIPTION}")
        if args.details:
            for key, v in sorted(k().params.items()):
                print(f"       {key} = {v}")
    print("\nProfils : " + "; ".join(f"{p} = {DESCRIPTIONS.get(p, '')} (fiches {', '.join(profile_codes(p))})" for p in available_profiles()))


def cmd_verifier(args):
    rolls: list = []
    folder = args.donnees or REPO_QUOTES
    data = D.load_folder(folder, verbose=True, adjust=args.ajustement, roll_report=rolls)
    found = {k.upper() for k in data}
    print(f"\n{len(data)} series lues dans {folder}\n")
    if rolls:
        print("Roulements de futures detectes et ajustes (" + args.ajustement + ") :")
        for root, r in rolls:
            drift = float(np.prod(1 + r["jump"].astype(float))) - 1 if len(r) else 0.0
            meth = r["methode"].iloc[0] if len(r) else "-"
            print(f"  {root:6} {len(r):3d} roulements ({meth}) ; derive artificielle retiree {drift:+.1%}")
        print("  (detection exacte si le fichier contient une colonne instrument_id / symbol : re-exporter depuis Databento)\n")
    missing_all = {}
    codes = profile_codes(args.profil) or available()
    for code in codes:
        k = get(code)
        prof = profile_params(args.profil, code) or {}
        st = k(**prof)
        need = list(dict.fromkeys(split_list(st.p.symbols) + st.required_references()))
        miss = [s for s in need if s.upper() not in found]
        short = []
        for s in need:
            df = next((v for kk, v in data.items() if kk.upper() == s.upper()), None)
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
        for s, cs in sorted(missing_all.items()):
            print(f"  {s:10} -> {', '.join(cs)}")
    else:
        print("\nToutes les cotations requises sont presentes.")


def cmd_backtest(args):
    t = time.time()
    st, res = _run_one(args.strategie, args)
    if st is None:
        raise SystemExit(f"la fiche {args.strategie} ne fait pas partie du profil '{args.profil}'")
    print(res.report)
    folder = _out_dir(args.sortie, st.strategy_id + (f"_{args.profil}" if args.profil else ""))
    _save(res, folder, args.html)
    print(f"[nexus] {time.time() - t:.1f} s - resultats ecrits dans {folder}")
    if getattr(args, "audit", None):
        from .collect import audit_report
        audit_report(os.path.join(folder, "rapport.txt"), args.audit)


def _prepared(code, args, symbols):
    """Fiche preparee sans cotations (une barre factice par symbole) : collecte et pre-notation."""
    klass = get(code)
    params = _strategy_params(code, klass, args) or {}
    params.update(symbols=",".join(symbols), api_calls_in_backtest=True, max_api_calls_per_run=args.budget)
    st = klass(**params)
    today = pd.Timestamp.now().normalize()
    one = pd.DataFrame({"open": [1.0], "high": [1.0], "low": [1.0], "close": [1.0], "volume": [0.0]}, index=[today])
    st._prepare({s: one for s in symbols})
    st.on_data_loaded()
    return st


def cmd_actualites(args):
    from .collect import collect_news, prescore
    code = get(args.strategie).NAME[5:7] if args.strategie else "07"
    klass = get(code)
    symbols = split_list(args.symboles) if args.symboles else split_list(_defaults(klass).get("symbols", ""))
    data_dir = args.externes or REPO_DATA
    fresh = collect_news(symbols, data_dir, _defaults(klass).get("company_names", ""), use_newsapi=not args.sans_newsapi,
                         use_reddit=args.reddit, hours=args.heures, fear_greed=not args.sans_fear_greed, alpha_vantage=args.resultats_av)
    if args.prenoter and fresh:
        if code not in ("07", "09", "10"):
            raise SystemExit("--prenoter : fiche 07, 09 ou 10")
        prescore(_prepared(code, args, symbols), fresh)


def cmd_audit(args):
    from .collect import audit_report
    if not os.path.exists(args.rapport):
        raise SystemExit(f"rapport introuvable : {args.rapport}")
    audit_report(args.rapport, args.fournisseur, args.modele or "")


def _symbol_conflicts(trades_by: dict) -> list[str]:
    """Module B : "si deux strategies veulent le meme titre, une seule passe". Les backtests sont independants :
    on mesure ici les chevauchements (meme symbole detenu en meme temps par deux strategies) qu il faudra arbitrer."""
    iv = []
    for name, trades in trades_by.items():
        for t in trades:
            if t.asset_class == "Option" or t.entry_time is None or t.exit_time is None:
                continue
            iv.append((str(t.symbol).upper(), pd.Timestamp(t.entry_time).normalize(), pd.Timestamp(t.exit_time).normalize(), name))
    pairs: dict = {}
    by_sym: dict = {}
    for x in iv:
        by_sym.setdefault(x[0], []).append(x)
    for sym, lst in by_sym.items():
        lst.sort(key=lambda x: x[1])
        for i, a in enumerate(lst):
            for b in lst[i + 1:]:
                if b[1] > a[2]:
                    break
                if b[3] == a[3]:
                    continue
                days = (min(a[2], b[2]) - b[1]).days
                if days <= 0:
                    continue
                k = tuple(sorted((a[3], b[3])))
                c = pairs.setdefault(k, [0, 0, set()])
                c[0] += 1
                c[1] += days
                c[2].add(sym)
    out = ["", "Conflits de titres (module B : une seule strategie par titre en reel) :"]
    if not pairs:
        out.append("  aucun chevauchement entre strategies")
        return out
    for (a, b), (n, days, syms) in sorted(pairs.items(), key=lambda kv: -kv[1][1])[:10]:
        out.append(f"  {a} / {b} : {n} chevauchements, {days} jours-titre ({', '.join(sorted(syms)[:8])})")
    out.append("  -> en reel, la seconde strategie serait refusee sur ces titres : l exposition combinee des backtests est surestimee.")
    return out


def _portfolio_report(rows, returns: dict, trades_by: dict) -> str:
    """Module C (moniteur de portefeuille) : correlation des strategies, totaux, check-list avant le reel."""
    lines = ["=" * 90, " PORTEFEUILLE NEXUS - modules B et C", "=" * 90]
    rmat = pd.DataFrame(returns).dropna(how="all")
    if rmat.shape[1] >= 2:
        corr = rmat.dropna().tail(252 * 3).corr()
        lines.append("Correlation des rendements journaliers des strategies (3 derniers ans communs) :")
        with pd.option_context("display.float_format", "{:.2f}".format, "display.width", 200):
            lines.append(corr.to_string())
        off = corr.where(~np.eye(len(corr), dtype=bool)).stack()
        if len(off) and off.max() >= 0.3:
            a, b = off.idxmax()
            lines.append(f"ALERTE : correlation max {off.max():.2f} ({a} / {b}) >= 0.30 -> les demi-Kelly additionnes surestiment le risque (fiche B).")
    lines += _symbol_conflicts(trades_by)
    total = sum(len(t) for t in trades_by.values())
    lines.append("")
    lines.append("Seuils avant passage en reel (consensus du fil) :")
    lines.append(("[x] " if total >= 1000 else "[ ] ") + f"au moins 1 000 trades resolus au total : {total}")
    for name, trades in trades_by.items():
        eq = rows.get(name, {}).get("equity")
        cycle = V.has_drawdown_recovery_cycle(eq.values, 0.05)[0] if eq is not None and len(eq) > 2 else False
        net = sum(t.net_pnl for t in trades)
        ok = len(trades) >= 30 and cycle and net > 0
        lines.append(("[x] " if ok else "[ ] ") + f"{name} : {len(trades)} trades (min 30), cycle drawdown->recuperation "
                     f"{'oui' if cycle else 'non'}, PnL net {net:,.0f}")
    lines.append("Rappel : premier objectif en reel = realite de l execution, pas le profit ; faire auditer la methode par une seconde IA.")
    return "\n".join(lines)


def _known(klass, params: dict) -> dict:
    """Parametres de la ligne de commande que la strategie connait (les autres sont ignores pour elle)."""
    keys = set(klass().params)
    return {k: v for k, v in params.items() if k in keys}


def _tout_runs(code, args):
    """Executions d une fiche dans le recapitulatif : une seule, ou une par instrument present en barres minute
    pour les fiches intrajournalieres (fiche 16 sur SPY, ES, NQ, YM... ; S1 sur NQ)."""
    klass = get(code)
    if not getattr(klass, "INTRADAY", False):
        st, res = _run_one(code, args)
        return [] if st is None else [(st, res)]
    params = _strategy_params(code, klass, args)
    if params is None:
        return []
    mfolder = args.donnees_minute or args.donnees or (REPO_QUOTES if os.path.isdir(REPO_QUOTES) else None)
    present = D.list_symbols(mfolder) if mfolder else set()
    wanted = split_list(params["symbols"]) if "symbols" in params else list(getattr(klass, "TOUT_SYMBOLS", ()))
    todo = [s for s in wanted if s.upper() in present]
    if not todo:
        print(f"{code} ignoree : aucune serie minute parmi {', '.join(wanted)} dans {mfolder}")
        return []
    runs = []
    for sym in todo:
        kw = {**_known(klass, params), "symbols": sym}
        kw.setdefault("instance_tag", sym)
        try:
            st = klass(**kw)               # une strategie figee (S1) refuse les parametres modifies
            res = st.run(_load_intraday(args, st), start=args.debut, end=args.fin, trade_start=args.debut_trading)
        except ValueError as ex:
            print(f"{code} {sym} ignoree : {ex}")
            continue
        runs.append((st, res))
    return runs


def _tout_row(code, st, res, folder, args, rows, returns, trades_by, eqs):
    sub = os.path.join(folder, st.strategy_id)
    os.makedirs(sub, exist_ok=True)
    _save(res, sub, args.html)
    eq = res.equity
    returns[st.strategy_id] = res.returns
    trades_by[st.strategy_id] = res.trades
    eqs[st.strategy_id] = {"equity": eq}
    rows.append(dict(fiche=code, strategie=st.strategy_id, trades=len(res.trades),
                     rendement=eq.iloc[-1] / eq.iloc[0] - 1 if len(eq) else M.NAN,
                     sharpe=V.annualized_sharpe(res.returns.values), dd_max=V.max_drawdown(eq.values),
                     expo_moy=float(res.exposure.mean()), pnl_net=sum(x.net_pnl for x in res.trades)))
    print(f"{code} {st.strategy_id} termine ({len(res.trades)} trades)")


def cmd_tout(args):
    rows, returns, trades_by, eqs = [], {}, {}, {}
    folder = _out_dir(args.sortie, "tout" + (f"_{args.profil}" if args.profil else ""))
    codes = profile_codes(args.profil) or available()
    for code in codes:
        try:
            runs = _tout_runs(code, args)
        except ValueError as ex:
            print(f"{code} ignoree : {ex}")
            continue
        for st, res in runs:
            _tout_row(code, st, res, folder, args, rows, returns, trades_by, eqs)
    tab = pd.DataFrame(rows)
    tab.to_csv(os.path.join(folder, "recapitulatif.csv"), index=False)
    with pd.option_context("display.float_format", "{:.4f}".format, "display.width", 200):
        print(tab.to_string(index=False))
    port = _portfolio_report(eqs, returns, trades_by)
    with open(os.path.join(folder, "portefeuille.txt"), "w", encoding="utf-8") as f:
        f.write(port)
    print(port)
    print(f"[nexus] resultats ecrits dans {folder}")


def cmd_portefeuille(args):
    """Recalcule le rapport de portefeuille a partir d un dossier produit par 'tout'."""
    returns, trades_by, eqs = {}, {}, {}
    for eqf in sorted(glob.glob(os.path.join(args.resultats, "*", "equity.csv"))):
        name = os.path.basename(os.path.dirname(eqf))
        eq = pd.read_csv(eqf, index_col=0, parse_dates=True)["equity"]
        returns[name] = eq.pct_change().dropna()
        eqs[name] = {"equity": eq}
        tf = os.path.join(os.path.dirname(eqf), "trades.csv")
        t = pd.read_csv(tf) if os.path.exists(tf) and os.path.getsize(tf) > 2 else pd.DataFrame()
        cols = ("symbol", "asset_class", "entry_time", "exit_time", "net_pnl")
        trades_by[name] = ([SimpleNamespace(**{c: r.get(c) for c in cols}) for r in t.to_dict("records")]
                           if "net_pnl" in t else [])
    if not returns:
        raise SystemExit(f"aucun equity.csv dans {args.resultats}")
    print(_portfolio_report(eqs, returns, trades_by))


# Grilles de validation par fiche (parametres [Choix] des fiches ; la valeur par defaut est toujours incluse).
VALIDATION_GRIDS = {
    "01": {"lookback_days": [126, 252], "atr_multiplier": [2.5, 3.0, 3.5]},
    "02": {"lookback_days": [126, 252], "target_vol_pct": [10.0, 12.0, 15.0]},
    "03": {"top_count": [3, 5, 8], "use_rotation": [True, False]},
    "04A": {"entry_s": [-1.0, -1.25, -1.5], "max_half_life_days": [10.0, 15.0]},
    "04B": {"z_entry": [2.0, 2.5, 3.0], "taker_sell_threshold_pct": [55.0, 60.0, 65.0]},
    "05": {"spike_ratio": [1.5, 1.8, 2.1], "calm_ratio": [1.1, 1.2]},
    "06": {"entry_z": [1.5, 2.0, 2.5], "max_hold_bars": [10, 20]},
    "07": {"entry_threshold": [0.5, 0.75], "min_headlines": [1, 2]},
    "08": {"veto_confidence": [0.6, 0.7, 0.8]},
    "09": {"min_abs_score": [1, 2], "entry_threshold": [0.5, 0.75]},
    "10": {"non_neutral_threshold": [0.3, 0.4, 0.5], "entry_threshold": [0.5, 0.75]},
    "11": {"put_delta": [-0.20, -0.25, -0.30], "profit_take_pct": [50.0, 75.0]},
    "12": {"confirm_days": [3, 5, 10], "mom_stress_pct": [0.0, 25.0, 50.0]},
    "13": {"rebalance_threshold_pct": [15.0, 25.0, 35.0], "target_vol_per_asset_pct": [8.0, 10.0, 12.0]},
    "14": {"pullback_decile_pct": [10.0, 20.0], "atr_multiplier": [2.0, 2.5, 3.0]},
}


def _grid_run(code, args, grid: dict, folder: str, walkforward, html=False, log=print):
    """Moteur complet pour chaque configuration, puis PBO (CSCV), Deflated Sharpe (nombre d essais) et walk-forward."""
    klass = get(code)
    base = _strategy_params(code, klass, args, user={})
    if base is None:
        return None
    base.update({k: v[0] for k, v in grid.items() if len(v) == 1})
    grid = {k: v for k, v in grid.items() if len(v) > 1}          # parametres fixes : hors des libelles
    if getattr(klass, "INTRADAY", False) and "symbols" in base:      # une grille par instrument
        base.setdefault("instance_tag", str(base["symbols"]))
    first = {k: v[0] for k, v in grid.items()}
    probe = klass(**base, **first)
    if args.synthetique:
        data = _synthetic_for(klass, {**base, **first})
    elif getattr(klass, "INTRADAY", False):
        data = _load_intraday(args, probe)
    else:
        data = _load(args, probe.bar_minutes())
    keys = list(grid)
    rets, rows, results = {}, [], {}
    combos = list(itertools.product(*[grid[k] for k in keys])) or [()]
    log(f"[nexus] {klass.NAME} : {len(combos)} configurations")
    for combo in combos:
        kw = dict(zip(keys, combo))
        st = klass(**{**base, **kw})
        res = st.run(data, start=args.debut, end=args.fin, trade_start=args.debut_trading, report=False)
        label = ",".join(f"{k}={v}" for k, v in kw.items()) or "defaut"
        rets[label] = res.returns
        results[label] = res
        eq = res.equity
        rows.append(dict(config=label, trades=len(res.trades), rendement=eq.iloc[-1] / eq.iloc[0] - 1,
                         sharpe=V.annualized_sharpe(res.returns.values), dd_max=V.max_drawdown(eq.values),
                         expo_moy=float(res.exposure.mean())))
        log(f"  {label:60} sharpe {rows[-1]['sharpe']:.2f}  trades {len(res.trades)}")
    raw = pd.DataFrame(rows)
    tab = raw.sort_values("sharpe", ascending=False, na_position="last")
    rmat = pd.DataFrame(rets).dropna()
    srs = [V.sharpe_per_period(rmat[c].values) for c in rmat]
    var_sr = float(np.var([x for x in srs if M.ok(x)], ddof=1)) if len(srs) > 1 else M.NAN
    pbo, combos_used = V.pbo(rmat.T.values) if rmat.shape[1] >= 2 and len(rmat) >= 32 else (M.NAN, 0)
    best = tab.iloc[0]["config"]
    res = results[best]
    extras = []
    res.strategy.report_extras(extras)
    res.report = build_report(res, extras + [res.stress], trials=len(combos), var_trials_sharpe=var_sr,
                              pbo=pbo, pbo_configs=rmat.shape[1], pbo_combos=combos_used)
    tab.to_csv(os.path.join(folder, "grille.csv"), index=False)
    rmat.to_csv(os.path.join(folder, "rendements_par_config.csv"))
    _save(res, folder, html)
    out = dict(name=klass.NAME, tab=tab, rmat=rmat, best=best, res=res, pbo=pbo, var_sr=var_sr,
               trials=len(combos), wf_sharpe=M.NAN, wf_text="", plateau="")
    if keys and len(combos) > 1:
        out["plateau"] = _plateau(raw, combos, keys, grid, folder, html)
        with open(os.path.join(folder, "rapport.txt"), "a", encoding="utf-8") as f:
            f.write("\n" + out["plateau"] + "\n")
    if walkforward:
        train, test = (int(x) for x in walkforward.split("/"))
        oos, chosen = [], []
        for a, b, c, d in V.walk_forward_splits(len(rmat), train, test):
            tr = rmat.iloc[a:b]
            pick = max(tr.columns, key=lambda col: (V.sharpe_per_period(tr[col].values) if M.ok(V.sharpe_per_period(tr[col].values)) else -1e9))
            chosen.append(pick)
            oos.append(rmat[pick].iloc[c:d])
        if oos:
            o = pd.concat(oos)
            out["wf_sharpe"] = V.annualized_sharpe(o.values)
            out["wf_text"] = (f"Walk-forward {train}/{test} : {len(oos)} fenetres, Sharpe hors echantillon {out['wf_sharpe']:.2f} "
                              f"(meilleure config en echantillon : {tab.iloc[0]['sharpe']:.2f}) ; configurations choisies : "
                              + ", ".join(f"{k} x{v}" for k, v in pd.Series(chosen).value_counts().items()))
            o.to_csv(os.path.join(folder, "walkforward_oos.csv"))
            with open(os.path.join(folder, "rapport.txt"), "a", encoding="utf-8") as f:
                f.write("\n" + out["wf_text"] + "\n")
    return out


def cmd_grille(args):
    grid = _params(args.param, grid=True)
    folder = _out_dir(args.sortie, get(args.strategie).NAME + "_grille")
    g = _grid_run(args.strategie, args, grid, folder, args.walkforward, args.html)
    if g is None:
        raise SystemExit(f"la fiche {args.strategie} ne fait pas partie du profil '{args.profil}'")
    print(g["res"].report)
    if g["wf_text"]:
        print(g["wf_text"])
    with pd.option_context("display.float_format", "{:.4f}".format, "display.width", 200):
        print(g["tab"].to_string(index=False))
    if g["plateau"]:
        print(g["plateau"])
    pbo = g["pbo"]
    print(f"[nexus] PBO {pbo:.1%} sur {g['rmat'].shape[1]} configurations - resultats dans {folder}" if M.ok(pbo) else f"[nexus] resultats dans {folder}")


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


def _verdict(g):
    """Criteres du module C : walk-forward, PBO, Deflated Sharpe, 30 trades + cycle, PnL net."""
    res = g["res"]
    eq = res.equity.to_numpy(float)
    dsr, _ = V.deflated_sharpe(res.returns.to_numpy(float), max(1, g["trials"]), g["var_sr"])
    cycle = V.has_drawdown_recovery_cycle(eq, 0.05)[0]
    n = len(res.trades)
    net = sum(t.net_pnl for t in res.trades)
    checks = [("walk-forward 180/30 : Sharpe hors echantillon > 0", M.ok(g["wf_sharpe"]) and g["wf_sharpe"] > 0,
               f"{g['wf_sharpe']:.2f}" if M.ok(g["wf_sharpe"]) else "n/a"),
              ("PBO < 50 %", M.ok(g["pbo"]) and g["pbo"] < 0.5, f"{g['pbo']:.0%}" if M.ok(g["pbo"]) else "n/a"),
              (f"Deflated Sharpe > 95 % ({g['trials']} essais)", M.ok(dsr) and dsr > 0.95, f"{dsr:.0%}" if M.ok(dsr) else "n/a"),
              ("au moins 30 trades fermes", n >= 30, str(n)),
              ("cycle drawdown -> recuperation", cycle, "oui" if cycle else "non"),
              ("PnL net (frais modelises) > 0", net > 0, f"{net:,.0f}")]
    lines = [("[x] " if good else "[ ] ") + f"{label} : {val}" for label, good, val in checks]
    passed = sum(good for _, good, _ in checks)
    return ("VALIDEE" if passed == len(checks) else f"NON VALIDEE ({len(checks) - passed} critere(s) en echec)"), lines


def cmd_valider(args):
    """Validation complete du module C pour une ou toutes les fiches."""
    codes = [args.strategie] if args.strategie else (profile_codes(args.profil) or available())
    top = _out_dir(args.sortie, "validation" + (f"_{args.profil}" if args.profil else ""))
    summary = ["=" * 90, " VALIDATION NEXUS - module C (walk-forward, PBO, Deflated Sharpe, Monte Carlo, seuils)", "=" * 90]
    rows = []
    for code in codes:
        klass = get(code)
        code = next((c for c in available() if get(c) is klass), code)
        grid = {k: list(v) for k, v in VALIDATION_GRIDS.get(code, {}).items()}
        base = _strategy_params(code, klass, args, user={})
        if base is None:
            continue
        defaults = {**_defaults(klass), **base}
        for k in grid:
            if defaults.get(k) not in grid[k]:
                grid[k].insert(0, defaults.get(k))
        sub = os.path.join(top, klass.NAME)
        os.makedirs(sub, exist_ok=True)
        try:
            g = _grid_run(code, args, grid, sub, args.walkforward)
        except ValueError as ex:
            print(f"{code} ignoree : {ex}")
            continue
        if g is None:
            continue
        verdict, lines = _verdict(g)
        block = ["", f"{code} {klass.NAME} : {verdict}", f"  meilleure configuration : {g['best']}"] + ["  " + l for l in lines]
        if g["wf_text"]:
            block.append("  " + g["wf_text"])
        summary += block
        print("\n".join(block))
        with open(os.path.join(sub, "validation.txt"), "w", encoding="utf-8") as f:
            f.write("\n".join(block) + "\n")
        rows.append(dict(fiche=code, strategie=klass.NAME, verdict=verdict, configs=g["trials"], trades=len(g["res"].trades),
                         sharpe_is=float(g["tab"].iloc[0]["sharpe"]), sharpe_wf=g["wf_sharpe"], pbo=g["pbo"]))
        if args.audit:
            from .collect import audit_report
            audit_report(os.path.join(sub, "rapport.txt"), args.audit)
    summary += ["", "Une fiche VALIDEE en backtest doit encore passer le paper trading et la comparaison des remplissages reels."]
    with open(os.path.join(top, "validation.txt"), "w", encoding="utf-8") as f:
        f.write("\n".join(summary) + "\n")
    if rows:
        pd.DataFrame(rows).to_csv(os.path.join(top, "validation.csv"), index=False)
    print(f"[nexus] validation ecrite dans {top}")


def cmd_recherche(args):
    from . import vbt_bridge as VB
    from .profiles import FUTURES_ALL
    from .strategies.s01_tsmom import UNIVERSE_25
    default_syms = FUTURES_ALL if args.profil == "futures" else UNIVERSE_25
    syms = split_list(args.symboles or default_syms)
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
    print("Rappel : grille vectorbt SIGNAL SEUL (sans module B ni stops), en poids de notionnel - pour explorer, pas pour valider.")


def cmd_regime(args):
    """Module A : HMM 3 etats (probabilites filtrees, EMA 5 j, plafond 0.95) + terciles de vol (fiche 12)."""
    from .regime import HmmRegimeDetector, VolTercileRegime
    data = _load(args)
    baro = args.barometre or ("ES" if any(k.upper() == "ES" for k in data) else "SPY")
    df = next((v for k, v in data.items() if k.upper() == baro.upper()), None)
    if df is None:
        raise SystemExit(f"barometre '{baro}' absent des donnees")
    vix = next((v for k, v in data.items() if k.upper() == (args.vix or "^VIX").upper()), None)
    hmm = HmmRegimeDetector(use_vix=vix is not None)
    terc = VolTercileRegime()
    rows = []
    vix_close = vix["close"].reindex(df.index).ffill() if vix is not None else None
    for d, c in df["close"].items():
        hmm.update(float(c), float(vix_close.loc[d]) if vix_close is not None and M.ok(vix_close.loc[d]) else M.NAN)
        terc.update(float(c))
        p = hmm.probabilities
        rows.append(dict(date=d, close=float(c), p_calme=p[0], p_neutre=p[1], p_stress=p[2], regime_hmm=hmm.regime,
                         regime_terciles=terc.regime, rv20=terc.rv))
    out = pd.DataFrame(rows).set_index("date")
    folder = _out_dir(args.sortie, f"regime_{baro}")
    out.to_csv(os.path.join(folder, "regime.csv"))
    ok = out.dropna(subset=["p_calme"])
    nxt = out["close"].pct_change().shift(-1)
    lines = [f"Module A - regime de {baro} ({'avec' if vix is not None else 'sans'} VIX) : {len(ok)} jours classes",
             hmm.describe(), terc.describe()]
    for col in ("regime_hmm", "regime_terciles"):
        g = ok.groupby(col)
        part = g.size() / len(ok)
        trans = int((ok[col] != ok[col].shift()).sum() - 1)
        lines.append(f"{col} : " + ", ".join(f"{k} {v:.0%} (rendement du lendemain {nxt.reindex(g.get_group(k).index).mean():+.3%})" for k, v in part.items())
                     + f" | {trans} transitions")
    capped = (ok[["p_calme", "p_neutre", "p_stress"]].max(axis=1) >= 0.95 - 1e-9).mean()
    lines.append(f"Jours au plafond 0.95 : {capped:.0%} (le HMM de Nexus restait bloque a 1.0)")
    txt = "\n".join(lines)
    print(txt)
    with open(os.path.join(folder, "rapport.txt"), "w", encoding="utf-8") as f:
        f.write(txt)
    if args.html:
        try:
            import plotly.graph_objects as go
            from plotly.subplots import make_subplots
            fig = make_subplots(rows=2, cols=1, shared_xaxes=True, row_heights=[0.5, 0.5])
            fig.add_trace(go.Scatter(x=out.index, y=out["close"], name=baro), 1, 1)
            for col in ("p_calme", "p_neutre", "p_stress"):
                fig.add_trace(go.Scatter(x=out.index, y=out[col], name=col, stackgroup="p"), 2, 1)
            fig.update_layout(height=800, template="plotly_white", title=f"Module A - regime {baro}")
            fig.write_html(os.path.join(folder, "regime.html"), include_plotlyjs="cdn")
        except Exception as ex:  # pragma: no cover
            print(f"[nexus] graphique impossible : {ex}")
    print(f"[nexus] resultats dans {folder}")


def cmd_tableau(args):
    from .tableau import exporter
    seul = [x.strip() for x in args.seulement.split(",")] if args.seulement else None
    t = time.time()
    idx = exporter(args.cotations, args.sortie, n_sim=args.simulations, grille=not args.sans_grille, seulement=seul)
    for s in idx["strategies"]:
        k = s["kpi"]
        print(f"  {s['id']:<20} {s['statut']:<10} Sharpe {k['sharpe']:.2f}  tests ok {s['ok']}  alertes {s['alertes']}")
    print(f"[nexus] tableau de bord : {len(idx['strategies'])} strategie(s) dans {args.sortie} ({time.time() - t:.0f} s)")
    print("        lancer ensuite : node Dashboard/serveur.js  puis ouvrir http://localhost:3000")


def main(argv=None):
    ap = argparse.ArgumentParser(prog="python -m nexus", description="Backtests Nexus en Python (vectorbt).")
    sub = ap.add_subparsers(dest="cmd", required=True)

    def data_args(p):
        p.add_argument("--donnees", "-d", help="dossier des cotations (CSV/TXT/Parquet) ; defaut : ../Cotations")
        p.add_argument("--ajustement", default="proportionnel", choices=("proportionnel", "additif", "aucun"),
                       help="ajustement des prix aux roulements de futures")
        p.add_argument("--profil", choices=available_profiles(), help="parametres adaptes a un jeu de donnees (futures)")
        p.add_argument("--verbeux", action="store_true")

    def common(p, strategy=True):
        if strategy:
            p.add_argument("--strategie", "-s", required=True, help="numero de fiche (" + ", ".join(available()) + ")")
        data_args(p)
        p.add_argument("--synthetique", action="store_true", help="donnees synthetiques (demonstration)")
        p.add_argument("--debut", help="premiere date chargee (AAAA-MM-JJ)")
        p.add_argument("--fin", help="derniere date chargee")
        p.add_argument("--debut-trading", dest="debut_trading", help="premier jour de trading (chauffage avant)")
        p.add_argument("--param", "-p", action="append", help="parametre nom=valeur (repetable)")
        p.add_argument("--externes", default=REPO_DATA if os.path.isdir(REPO_DATA) else None,
                       help="dossier des fichiers Data/*.csv (fondamentaux, facteurs, resultats, agenda, actualites)")
        p.add_argument("--sortie", default="resultats", help="dossier de sortie")
        p.add_argument("--html", action="store_true", help="graphique interactif (vectorbt/plotly)")

    p = sub.add_parser("liste", help="strategies et profils disponibles")
    p.add_argument("--details", action="store_true")
    p.set_defaults(func=cmd_liste)
    p = sub.add_parser("verifier", help="cotations presentes / manquantes par strategie, roulements detectes")
    data_args(p)
    p.set_defaults(func=cmd_verifier)
    p = sub.add_parser("backtest", help="un backtest complet + rapport")
    common(p)
    p.add_argument("--audit", metavar="FOURNISSEUR", help="faire relire le rapport par une seconde IA (claude, deepseek, gemini)")
    p.set_defaults(func=cmd_backtest)
    p = sub.add_parser("tout", help="toutes les strategies (du profil) + rapport de portefeuille")
    common(p, strategy=False)
    p.add_argument("--donnees-minute", dest="donnees_minute",
                   help="dossier des barres 1 minute des fiches intrajournalieres (defaut : --donnees)")
    p.set_defaults(func=cmd_tout)
    p = sub.add_parser("grille", help="grille de parametres (moteur complet) + PBO / DSR / walk-forward")
    common(p)
    p.add_argument("--walkforward", help="fenetres entrainement/test en jours, ex. 180/30")
    p.set_defaults(func=cmd_grille)
    p = sub.add_parser("valider", help="module C complet par fiche : grille, walk-forward 180/30, PBO, DSR, seuils (+ audit IA)")
    common(p, strategy=False)
    p.add_argument("--strategie", "-s", help="une fiche (defaut : toutes celles du profil)")
    p.add_argument("--walkforward", default="180/30", help="fenetres entrainement/test en jours [Fil] 180/30")
    p.add_argument("--audit", metavar="FOURNISSEUR", help="faire relire chaque rapport par une seconde IA (cle API requise)")
    p.set_defaults(func=cmd_valider)
    p = sub.add_parser("recherche", help="grille vectorbt rapide, signal seul (tsmom | xsmom)")
    common(p, strategy=False)
    p.add_argument("--type", choices=("tsmom", "xsmom"), default="tsmom")
    p.add_argument("--symboles")
    p.set_defaults(func=cmd_recherche)
    p = sub.add_parser("regime", help="module A : regime HMM 3 etats + terciles de vol du barometre")
    data_args(p)
    p.add_argument("--barometre", help="symbole du barometre (defaut ES si present, sinon SPY)")
    p.add_argument("--vix", help="symbole du VIX (defaut ^VIX s il est present)")
    p.add_argument("--sortie", default="resultats")
    p.add_argument("--html", action="store_true")
    p.set_defaults(func=cmd_regime, synthetique=False)
    p = sub.add_parser("portefeuille", help="module C : correlation des strategies et check-list (dossier de 'tout')")
    p.add_argument("--resultats", required=True)
    p.set_defaults(func=cmd_portefeuille)
    p = sub.add_parser("actualites", help="collecte NewsAPI / Reddit / Fear & Greed / resultats -> Data/news_live.csv (+ pre-notation)")
    p.add_argument("--strategie", "-s", help="fiche dont on reprend l univers et la consigne (07 par defaut ; 09, 10 pour --prenoter)")
    p.add_argument("--symboles", help="symboles separes par des virgules (defaut : univers de la fiche)")
    p.add_argument("--externes", default=REPO_DATA if os.path.isdir(REPO_DATA) else None, help="dossier Data (news.csv, news_live.csv, earnings.csv)")
    p.add_argument("--heures", type=int, default=24, help="profondeur de la recherche NewsAPI (heures)")
    p.add_argument("--reddit", action="store_true", help="ajouter les titres Reddit (exclus du score par defaut)")
    p.add_argument("--sans-newsapi", dest="sans_newsapi", action="store_true")
    p.add_argument("--sans-fear-greed", dest="sans_fear_greed", action="store_true")
    p.add_argument("--resultats-av", dest="resultats_av", action="store_true", help="calendrier des resultats Alpha Vantage")
    p.add_argument("--prenoter", action="store_true", help="noter les nouveaux titres maintenant (appels API payants) -> cache chaud")
    p.add_argument("--budget", type=int, default=500, help="appels API max pour la pre-notation")
    p.add_argument("--param", "-p", action="append", help="parametre de la fiche nom=valeur (modele, cles...)")
    p.add_argument("--profil", default=None)
    p.set_defaults(func=cmd_actualites)
    p = sub.add_parser("audit", help="module C : relecture d un rapport par une seconde IA (cle API requise)")
    p.add_argument("--rapport", required=True, help="chemin du rapport.txt")
    p.add_argument("--fournisseur", default="claude", help="claude | deepseek | gemini | openai")
    p.add_argument("--modele", help="modele (defaut : celui du fournisseur)")
    p.set_defaults(func=cmd_audit)
    p = sub.add_parser("tableau", help="export du tableau de bord Node.js (strategies validees + candidates, vectorbt)")
    p.add_argument("--cotations", "-d", default=REPO_QUOTES, help="dossier racine des barres 1 minute (defaut : ../Cotations)")
    p.add_argument("--sortie", default=os.path.join(os.path.dirname(__file__), "..", "..", "Dashboard", "donnees"),
                   help="dossier des fichiers JSON lus par Dashboard/serveur.js")
    p.add_argument("--simulations", type=int, default=2000, help="tirages Monte Carlo / bootstrap")
    p.add_argument("--sans-grille", dest="sans_grille", action="store_true", help="sans grille de parametres (plus rapide)")
    p.add_argument("--seulement", help="codes a exporter : S1 (validees), G1 Gotobi, O1 ORB, N1 or la nuit, L1 LETF ; ex. S1,G1")
    p.set_defaults(func=cmd_tableau)
    args = ap.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
