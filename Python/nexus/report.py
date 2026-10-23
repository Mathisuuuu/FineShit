"""Rapport de fin de backtest (port de NxReport.Build) : trades, Kelly, couts, portefeuille,
Monte Carlo, bootstrap par blocs, Deflated Sharpe, PBO, extras, check-list avant le reel."""
from __future__ import annotations

from datetime import datetime

import numpy as np

from . import mathx as M
from . import validation as V
from .sizing import break_even_payoff, kelly_fraction, wilson


def _pct(x, d=1):
    return f"{x:.{d}%}" if M.ok(x) else "n/a"


def _f(x, d=2):
    return f"{x:.{d}f}" if M.ok(x) else "n/a"


def _exposure_line(res) -> str:
    e = getattr(res, "exposure", None)
    if e is None or len(e) == 0:
        return "Exposition brute       : n/a"
    e = e.dropna()
    inv = e[e > 1e-9]
    return (f"Exposition brute       : moyenne {_pct(e.mean())} | max {_pct(e.max())} | "
            f"moyenne quand investi {_pct(inv.mean() if len(inv) else M.NAN)} | jours investis {_pct(len(inv) / len(e) if len(e) else M.NAN)}")


def build_report(res, extras: list[str] | None = None, trials: int = 1, var_trials_sharpe: float = M.NAN,
                 pbo: float = M.NAN, pbo_configs: int = 0, pbo_combos: int = 0) -> str:
    st = res.strategy
    p = st.p
    t = res.trades
    n = len(t)
    line = "=" * 78
    out = [line, f" RAPPORT NEXUS (Python) - {st.name}",
           f" Genere le {datetime.now():%Y-%m-%d %H:%M:%S}  |  id : {st.strategy_id}", line]
    changed = {k: v for k, v in res.params.items() if k not in ("verbose",)}
    out.append("Parametres : " + "  ".join(f"{k}={v}" for k, v in sorted(changed.items()) if v not in (None, "")))
    out.append("")

    net = sum(x.net_pnl for x in t)
    gross = sum(x.gross_pnl for x in t)
    costs = sum(x.costs for x in t)
    wins = sum(1 for x in t if x.net_pnl > 0)
    pw = wins / n if n else M.NAN
    w_r = [x.net_return for x in t if x.net_return > 0]
    l_r = [x.net_return for x in t if x.net_return <= 0]
    avg_w = float(np.mean(w_r)) if w_r else M.NAN
    avg_l = -float(np.mean(l_r)) if l_r else M.NAN
    b = avg_w / avg_l if M.ok(avg_w) and M.ok(avg_l) and avg_l > 0 else M.NAN
    kelly = kelly_fraction(pw, b)
    lo, hi = wilson(wins, n, 1.96)
    out += ["--- Trades -------------------------------------------------------------------",
            f"Trades fermes          : {n}  (gagnants {wins})",
            f"Taux de reussite       : {_pct(pw)}  IC95% Wilson [{_pct(lo)} ; {_pct(hi)}]",
            f"Gain moyen / perte moy.: {_pct(avg_w, 2)} / {_pct(avg_l, 2)}  -> b = {_f(b)}  (b mini pour Kelly>0 : {_f(break_even_payoff(pw))})",
            f"Kelly f* (point)       : {_f(kelly, 4)}   [p bas -> {_f(kelly_fraction(lo, b), 4)} ; p haut -> {_f(kelly_fraction(hi, b), 4)}]",
            f"PnL brut / couts / net : {gross:.2f} / {costs:.2f} / {net:.2f}",
            "Couts modelises        : " + st.costs.describe()]
    if gross != 0:
        out.append(f"Effet des couts        : le PnL sans couts serait surestime de {costs:.2f} ({costs / abs(gross):.1%} du brut)")
    out.append("")

    eq = res.equity.to_numpy(float)
    mdd = V.max_drawdown(eq)
    sh = V.annualized_sharpe(res.returns.to_numpy(float))
    total = eq[-1] / eq[0] - 1 if eq.size > 1 and eq[0] > 0 else M.NAN
    years = (res.equity.index[-1] - res.equity.index[0]).days / 365.25 if len(res.equity) > 1 else M.NAN
    cagr = (1 + total) ** (1 / years) - 1 if M.ok(years) and years > 0.1 and total > -1 else M.NAN
    cycle, deepest, bars = V.has_drawdown_recovery_cycle(eq, 0.05)
    out += ["--- Portefeuille --------------------------------------------------------------",
            f"Periode                : {res.equity.index[0]:%Y-%m-%d} -> {res.equity.index[-1]:%Y-%m-%d}",
            f"Rendement total / CAGR : {_pct(total, 2)} / {_pct(cagr, 2)}  sur {_f(years, 1)} ans",
            f"Sharpe annualise       : {_f(sh)}   Drawdown max : {_pct(mdd, 2)}",
            _exposure_line(res),
            f"Cycle drawdown->recup. : {'oui' if cycle else 'non'}" + (f" (plus profond {deepest:.1%}, {bars} pas)" if cycle else ""),
            f"Disjoncteurs           : drawdown x{st.breaker.drawdown_trips}, journalier x{st.breaker.daily_trips}"
            f"  (reference journaliere : {p.daily_breaker_ref})"]
    if any(s.traded and s.asset_class in ("Action", "Etf") for s in st.syms) and p.initial_bankroll < 25000:
        out.append(f"AVERTISSEMENT PDT (US) : capital {p.initial_bankroll:,.0f} $ < 25 000 $ -> au plus 3 allers-retours "
                   "intrajournaliers sur 5 jours glissants en reel (module C)")
    out.append("")

    out.append(f"--- Monte Carlo ({p.monte_carlo_sims} tirages) -------------------------------------------")
    pnls = [x.net_pnl for x in t]
    if len(pnls) >= 5:
        mc = V.monte_carlo_max_dd(pnls, p.initial_bankroll, p.monte_carlo_sims, p.seed)
        bb = V.block_bootstrap_max_dd(pnls, p.initial_bankroll, p.block_length, p.monte_carlo_sims, p.seed + 1)
        L = p.block_length if p.block_length > 0 else int(round(len(pnls) ** 0.5))
        out.append(f"DD max, tirage simple  : mediane {_pct(V.percentile(mc, .5))} | 95% {_pct(V.percentile(mc, .95))} | 99% {_pct(V.percentile(mc, .99))}")
        out.append(f"DD max, blocs mobiles  : mediane {_pct(V.percentile(bb, .5))} | 95% {_pct(V.percentile(bb, .95))} | 99% {_pct(V.percentile(bb, .99))}  (bloc {L})")
    else:
        out.append("  (moins de 5 trades : simulation non significative)")
    out.append("")

    out.append("--- Sur-ajustement -------------------------------------------------------------")
    dsr, sr0 = V.deflated_sharpe(res.returns.to_numpy(float), max(1, trials), var_trials_sharpe)
    out.append(f"Deflated Sharpe        : {_pct(dsr)} (probabilite que le Sharpe vrai > SR0={_f(sr0, 4)}/jour, {max(1, trials)} essai(s))")
    if M.ok(pbo):
        out.append(f"PBO (CSCV)             : {pbo:.1%} sur {pbo_configs} configurations, {pbo_combos} combinaisons"
                   + ("  -> SUR-AJUSTEMENT PROBABLE" if pbo > 0.5 else ""))
    else:
        out.append("PBO (CSCV)             : n/a (lancer une grille : python -m nexus grille ...)")
    out.append("Walk-forward           : python -m nexus grille -s FICHE -p ... --walkforward 180/30 [Fil]")
    out.append("")

    if extras:
        out.append("--- Specifique a la strategie -------------------------------------------------")
        out += extras
        out.append("")

    out.append("--- Seuils avant passage en reel (consensus du fil) ---------------------------")
    has_crypto = any(s.traded and s.asset_class == "Crypto" for s in st.syms)
    out.append(("[x] " if n >= 1000 else "[ ] ") + f"au moins 1 000 trades resolus au total (ce run {n})")
    out.append(("[x] " if n >= 30 and cycle else "[ ] ") + f"au moins 30 trades fermes ({n}) ET un cycle drawdown -> recuperation ({'oui' if cycle else 'non'})")
    out.append(("[x] " if net > 0 else "[ ] ") + f"frais {'Binance ' if has_crypto else ''}modelises et PnL encore positif (net {net:.2f})")
    out.append("[ ] remplissages reels compares au paper (a faire en Sim101 puis en reel)")
    out.append("Rappel : un backtest ne remplace pas le paper trading ; faire auditer la methode par une seconde IA.")
    out.append(line)
    return "\n".join(out)
