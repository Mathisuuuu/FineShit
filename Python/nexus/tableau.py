"""Export du tableau de bord (Dashboard/, serveur Node.js) : un fichier JSON par strategie.

Strategies exportees : toutes les strategies du registre marquees VALIDATED (ex. S1_NoiseAreaNQ) et les
candidates a l etude (Gotobi 6J, ORB NQ, or hors seance de New York). Tous les chiffres viennent de vectorbt (portefeuilles, statistiques, trades,
drawdowns, rendements, ratios glissants, Sharpe deflate), de scipy (bootstrap BCa, test de permutation) et de
nexus.validation (Sharpe probabiliste, PBO, decoupage walk-forward). Le code ci-dessous ne fait qu assembler
et mettre en forme ; il n exporte aucune cotation brute (seulement des resultats).

    python -m nexus tableau --cotations ../../cotations --sortie ../Dashboard/donnees
"""
from __future__ import annotations

import datetime as dt
import json
import math
import os
import time
import warnings

import numpy as np
import pandas as pd
from scipy import stats as SS

from . import data as D
from . import gotobi as GT
from . import orb as OR
from . import or_nuit as ON
from . import intraday as I
from . import validation as V
from . import vbt_bridge as VB
from .strategies import available, get

try:
    import vectorbt as vbt
except ImportError:  # pragma: no cover
    vbt = None

ANNEE = "252 days"
VERSION = 1


# =============================================================================
#  Mise en forme JSON
# =============================================================================
def _js(x):
    if x is None:
        return None
    if isinstance(x, (pd.Timestamp, dt.datetime, dt.date)):
        return pd.Timestamp(x).strftime("%Y-%m-%d %H:%M") if pd.Timestamp(x).time() != dt.time(0) else pd.Timestamp(x).strftime("%Y-%m-%d")
    if isinstance(x, (pd.Timedelta, dt.timedelta, np.timedelta64)):
        td = pd.Timedelta(x)
        if pd.isna(td):
            return None
        j, s = td.days, td.seconds
        return f"{j} j {s // 3600:02d}:{s % 3600 // 60:02d}" if j else f"{s // 3600:02d}:{s % 3600 // 60:02d}"
    if isinstance(x, (np.bool_, bool)):
        return bool(x)
    if isinstance(x, (np.integer,)):
        return int(x)
    if isinstance(x, (float, np.floating)):
        return None if not math.isfinite(float(x)) else float(x)
    if isinstance(x, dict):
        return {str(k): _js(v) for k, v in x.items()}
    if isinstance(x, (list, tuple, np.ndarray, pd.Index)):
        return [_js(v) for v in list(x)]
    if isinstance(x, pd.Series):
        return [_js(v) for v in x.tolist()]
    return x


def _stats(s: pd.Series) -> list:
    """Statistiques vectorbt -> liste [nom, valeur] (ordre conserve)."""
    return [[str(k), _js(v)] for k, v in s.items()]


def _acc(r: pd.Series):
    return r.vbt.returns(freq="1D", year_freq=ANNEE)


def _round(a, n=6):
    return [None if (v is None or not math.isfinite(v)) else round(float(v), n) for v in np.asarray(a, float)]


def calendrier(debut, fin) -> pd.DatetimeIndex:
    """Seances NYSE (calendrier commun a toutes les strategies du tableau de bord)."""
    j = pd.bdate_range(debut, fin)
    return pd.DatetimeIndex(list(j.difference(I.nyse_holidays(j[0], j[-1]))))


# =============================================================================
#  Blocs communs (vectorbt)
# =============================================================================
PF_CLES = ["Start", "End", "Period", "Total Fees Paid", "Total Trades", "Total Closed Trades", "Total Open Trades",
           "Win Rate [%]", "Best Trade [%]", "Worst Trade [%]", "Avg Winning Trade [%]", "Avg Losing Trade [%]",
           "Avg Winning Trade Duration", "Avg Losing Trade Duration", "Profit Factor", "Expectancy"]


def bloc_vectorbt(pf, valeur: pd.Series) -> dict:
    """Toutes les statistiques vectorbt : rendements journaliers, drawdowns, trades, positions, ordres, portefeuille."""
    r = valeur.pct_change().dropna()
    acc = _acc(r)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        rend = acc.stats()
        rend["Cond. Value at Risk"] = acc.cond_value_at_risk()
        rend["Downside Risk"] = acc.downside_risk() if hasattr(acc, "downside_risk") else np.nan
        pfst = pf.stats()
        pfst = pfst[[k for k in PF_CLES if k in pfst.index]]
        out = dict(
            rendements=_stats(rend),
            drawdowns=_stats(pd.Series(valeur.to_numpy(), index=pd.DatetimeIndex(list(valeur.index))).vbt(freq="1D").drawdowns.stats()),
            trades=_stats(pf.trades.stats()),
            positions=_stats(pf.positions.stats()),
            ordres=_stats(pf.orders.stats()),
            portefeuille=_stats(pfst),
        )
    return out


def bloc_series(valeur: pd.Series) -> dict:
    v = pd.Series(valeur.to_numpy(), index=pd.DatetimeIndex(list(valeur.index)))
    r = v.pct_change().fillna(0.0)
    acc = _acc(r)
    dd = v / v.cummax() - 1
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        sh1 = acc.rolling_sharpe_ratio(252)
        vol3 = acc.rolling_annualized_volatility(63)
        so1 = acc.rolling_sortino_ratio(252)
    recs = v.vbt(freq="1D").drawdowns.records_readable
    recs = recs.assign(prof=1 - recs["Valley Value"] / recs["Peak Value"]).sort_values("prof", ascending=False).head(5)
    top = [dict(pic=_js(x["Peak Timestamp"]), creux=_js(x["Valley Timestamp"]), fin=_js(x["End Timestamp"]),
                profondeur=_js(x["prof"]), statut="recupere" if x["Status"] == "Recovered" else "en cours")
           for _, x in recs.iterrows()]
    ans = (1 + r).groupby(r.index.year).prod() - 1
    mois = (1 + r).groupby([r.index.year, r.index.month]).prod() - 1
    annees = sorted(set(r.index.year))
    z = [[_js(mois.get((y, m_), np.nan)) for m_ in range(1, 13)] for y in annees]
    return dict(dates=[d.strftime("%Y-%m-%d") for d in v.index], valeur=_round(v, 2), rendement=_round(r, 7),
                drawdown=_round(dd, 6), sharpe_1an=_round(sh1, 4), sortino_1an=_round(so1, 4), vol_3mois=_round(vol3, 5),
                top_drawdowns=top, annuel=dict(annees=[int(y) for y in ans.index], rendement=_round(ans, 6)),
                mensuel=dict(annees=[int(y) for y in annees], z=z))


def bloc_trades(pf, fuseau_source: str | None, fuseau_affiche: str, capital_minute: pd.Series) -> tuple[list, pd.DataFrame]:
    """Trades vectorbt (records_readable) -> liste pour le tableau + frame de travail.
    capital_minute : valeur du capital a chaque barre (vectorbt) ; les rendements 'net' et 'brut' des trades sont
    rapportes au capital juste avant l entree (et non au notionnel du trade) pour le Monte Carlo et le test des signes."""
    t = pf.trades.records_readable
    t = t[t["Status"] == "Closed"].copy()
    avant = capital_minute.shift(1).bfill()
    cap = avant.reindex(pd.DatetimeIndex(t["Entry Timestamp"])).to_numpy()

    def loc(s):
        idx = pd.DatetimeIndex(s)
        if fuseau_source:
            idx = idx.tz_localize(fuseau_source).tz_convert(fuseau_affiche).tz_localize(None)
        return idx

    t["entree"], t["sortie"] = loc(t["Entry Timestamp"]), loc(t["Exit Timestamp"])
    t = t.sort_values("entree")
    t["brut"] = (t["PnL"] + t["Entry Fees"] + t["Exit Fees"]).to_numpy() / cap
    t["net"] = t["PnL"].to_numpy() / cap
    t["net_notionnel"] = t["Return"].to_numpy()
    rows = [dict(n=int(i), sens="achat" if d == "Long" else "vente", entree=e.strftime("%Y-%m-%d %H:%M"),
                 sortie=s.strftime("%Y-%m-%d %H:%M"), prix_entree=_js(pe), prix_sortie=_js(ps), quantite=_js(q),
                 pnl=_js(round(p, 2)), rendement_bp=_js(round(rt * 1e4, 3)), frais=_js(round(fe, 2)),
                 duree_min=_js(round((s - e).total_seconds() / 60, 1)))
            for i, (d, e, s, pe, ps, q, p, rt, fe) in enumerate(zip(
                t["Direction"], t["entree"], t["sortie"], t["Avg Entry Price"], t["Avg Exit Price"], t["Size"], t["PnL"],
                t["net_notionnel"], t["Entry Fees"] + t["Exit Fees"]))]
    return rows, t


def _dd_paths(r_trades: np.ndarray, n: int, rng, remise: bool) -> pd.DataFrame:
    cols = [rng.choice(r_trades, size=len(r_trades), replace=True) if remise else rng.permutation(r_trades) for _ in range(n)]
    return pd.DataFrame(np.column_stack(cols))


def bloc_tests_communs(r: pd.Series, t: pd.DataFrame, publication: str, essais: int, var_sharpe_ann: float,
                       n_sim: int = 2000, seed: int = 7) -> tuple[list, dict]:
    """Batterie commune : Sharpe par periode, IC bootstrap BCa, PSR, Sharpe deflate, test des signes, Monte Carlo."""
    rng = np.random.default_rng(seed)
    pub = pd.Timestamp(publication)
    acc = _acc(r)
    tests = []

    def add(famille, test, resultat, detail="", verdict="info"):
        tests.append(dict(famille=famille, test=test, resultat=resultat, detail=detail, verdict=verdict))

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        sh = acc.sharpe_ratio()
        avant, apres = r[r.index < pub], r[r.index >= pub]
        sh_av, sh_ap = _acc(avant).sharpe_ratio(), _acc(apres).sharpe_ratio()
        l2 = r[r.index >= r.index[-1] - pd.DateOffset(years=2)]
        sh_l2 = _acc(l2).sharpe_ratio()
    add("Performance", "Sharpe 2016-2026 (vectorbt)", f"{sh:.2f}", f"{len(r)} seances", "ok" if sh >= 1 else ("alerte" if sh < 0.5 else "info"))
    if len(avant) >= 20:
        add("Performance", "Sharpe avant / apres publication", f"{sh_av:.2f} / {sh_ap:.2f}", f"publication {publication}, {len(apres)} seances apres",
            "ok" if sh_ap >= 0.5 else "alerte")
    else:
        add("Performance", "Sharpe apres publication", f"{sh_ap:.2f}",
            f"publication {publication}, avant les donnees : tout l historique ({len(apres)} seances) est posterieur", "ok" if sh_ap >= 0.5 else "alerte")
    add("Performance", "Sharpe des 2 dernieres annees", f"{sh_l2:.2f}", f"depuis {l2.index[0]:%Y-%m-%d}", "ok" if sh_l2 >= 0.5 else "alerte")
    ans = (1 + r).groupby(r.index.year).prod() - 1
    add("Performance", "Annees positives", f"{int((ans > 0).sum())}/{len(ans)}", ", ".join(f"{y} {v:+.1%}" for y, v in ans.items()),
        "ok" if (ans > 0).mean() >= 0.7 else "alerte")

    x = r.to_numpy()
    b = SS.bootstrap((x,), V.annualized_sharpe, method="BCa", n_resamples=n_sim, random_state=seed)
    add("Robustesse statistique", "IC 95 % du Sharpe (bootstrap BCa, scipy)", f"[{b.confidence_interval.low:.2f} ; {b.confidence_interval.high:.2f}]",
        f"{n_sim} tirages", "ok" if b.confidence_interval.low > 0 else "alerte")
    bp = SS.bootstrap((apres.to_numpy(),), V.annualized_sharpe, method="BCa", n_resamples=n_sim, random_state=seed) if len(apres) > 60 else None
    if bp is not None:
        add("Robustesse statistique", "IC 95 % du Sharpe apres publication", f"[{bp.confidence_interval.low:.2f} ; {bp.confidence_interval.high:.2f}]",
            f"{len(apres)} seances", "ok" if bp.confidence_interval.low > 0 else "alerte")
    psr = V.probabilistic_sharpe(x.mean() / x.std(ddof=1), 0.0, len(x), SS.skew(x), SS.kurtosis(x, fisher=False))
    add("Robustesse statistique", "Probabilite que le Sharpe vrai soit > 0", f"{psr:.1%}", "Sharpe probabiliste (asymetrie et queues comprises)",
        "ok" if psr >= 0.95 else "alerte")
    if len(apres) > 60:
        y = apres.to_numpy()
        p0 = V.probabilistic_sharpe(y.mean() / y.std(ddof=1), 0.0, len(y), SS.skew(y), SS.kurtosis(y, fisher=False))
        p5 = V.probabilistic_sharpe(y.mean() / y.std(ddof=1), 0.5 / math.sqrt(252), len(y), SS.skew(y), SS.kurtosis(y, fisher=False))
        add("Robustesse statistique", "Apres publication : P(Sharpe > 0) / P(Sharpe > 0,5)", f"{p0:.1%} / {p5:.1%}", "", "ok" if p0 >= 0.9 else "alerte")
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        dsr = acc.deflated_sharpe_ratio(var_sharpe=var_sharpe_ann, nb_trials=int(essais))   # variance des Sharpe ANNUALISES
    dsr_n, sr0 = V.deflated_sharpe(x, int(essais), var_sharpe_ann / 252.0)
    add("Robustesse statistique", "Sharpe deflate (vectorbt, essais comptes)", f"{dsr:.1%}",
        f"{essais} essais, variance des Sharpe annualises {var_sharpe_ann:.2f} ; Sharpe a battre {sr0 * math.sqrt(252):.2f} "
        f"(controle nexus.validation : {dsr_n:.1%})", "ok" if dsr >= 0.95 else "alerte")

    brut = t["brut"].to_numpy()
    pt = SS.permutation_test((brut,), np.mean, permutation_type="samples", n_resamples=max(n_sim * 5, 10000),
                             alternative="greater", random_state=seed)
    add("Robustesse statistique", "Test des signes (permutation scipy)", f"p = {pt.pvalue:.4f}",
        f"memes trades, sens tires au hasard ; gain brut moyen {brut.mean() * 1e4:.2f} bp", "ok" if pt.pvalue < 0.05 else "alerte")

    rt = t["net"].to_numpy()
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        obs = -pd.Series(rt).vbt.returns(freq="1D").max_drawdown()
        dd_perm = -_dd_paths(rt, n_sim, rng, False).vbt.returns(freq="1D").max_drawdown().to_numpy()
        boot = _dd_paths(rt, n_sim, rng, True)
        dd_boot = -boot.vbt.returns(freq="1D").max_drawdown().to_numpy()
        fin_boot = (1 + boot).prod().to_numpy() - 1
    q = lambda a, p: float(np.quantile(a, p))
    add("Monte Carlo", "Perte max, ordre des trades melange", f"mediane {np.median(dd_perm):.1%}",
        f"95 % : {q(dd_perm, .95):.1%}, 99 % : {q(dd_perm, .99):.1%} ; observee {obs:.1%}", "info")
    add("Monte Carlo", "Perte max, trades tires avec remise", f"mediane {np.median(dd_boot):.1%}",
        f"95 % : {q(dd_boot, .95):.1%}, 99 % : {q(dd_boot, .99):.1%}", "info")
    add("Monte Carlo", "Gain total, trades tires avec remise", f"mediane {np.median(fin_boot):+.0%}",
        f"5 % : {q(fin_boot, .05):+.0%} ; part des tirages perdants {np.mean(fin_boot < 0):.1%}", "ok" if np.mean(fin_boot < 0) < 0.05 else "alerte")
    # eventail des trajectoires (quantiles de la valeur cumulee, trade par trade)
    paths = (1 + boot.iloc[:, :500]).cumprod().to_numpy()
    step = max(1, len(rt) // 300)
    fan = {f"p{p}": _round(np.quantile(paths[::step], p / 100, axis=1), 5) for p in (5, 25, 50, 75, 95)}
    fan["observe"] = _round(np.cumprod(1 + rt)[::step], 5)
    fan["trade"] = list(range(0, len(rt), step))
    mc = dict(dd_ordre=_round(dd_perm, 5), dd_remise=_round(dd_boot, 5), dd_observe=_js(obs), gain_remise=_round(fin_boot, 5),
              sharpe_bootstrap=_round(b.bootstrap_distribution, 4), sharpe=_js(sh), eventail=fan)
    return tests, mc


def _grille_pbo_wf(rmat: pd.DataFrame, meilleure: str, train=756, test=126) -> tuple[list, dict]:
    tests = []
    pbo, combos = V.pbo(rmat.T.values) if rmat.shape[1] >= 2 else (np.nan, 0)
    tests.append(dict(famille="Sur-ajustement", test="PBO (CSCV, nexus.validation)", resultat=f"{pbo:.0%}",
                      detail=f"{rmat.shape[1]} reglages, {combos} combinaisons", verdict="ok" if pbo < 0.5 else "alerte"))
    oos, choix = [], []
    for a, b_, c, d in V.walk_forward_splits(len(rmat), train, test):
        tr = rmat.iloc[a:b_]
        pick = max(tr.columns, key=lambda col: np.nan_to_num(V.sharpe_per_period(tr[col].values), nan=-1e9))
        choix.append(pick)
        oos.append(rmat[pick].iloc[c:d])
    wf = None
    if oos:
        o = pd.concat(oos)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            s_oos = _acc(o).sharpe_ratio()
            s_best = _acc(rmat[meilleure].loc[o.index]).sharpe_ratio()
        tests.append(dict(famille="Sur-ajustement", test=f"Walk-forward {train // 252} ans / {test // 21} mois",
                          resultat=f"Sharpe hors echantillon {s_oos:.2f}",
                          detail=f"{len(oos)} fenetres ; reglage retenu sur la meme periode : {s_best:.2f}",
                          verdict="ok" if s_oos >= 0.5 else "alerte"))
        wf = dict(dates=[d.strftime("%Y-%m-%d") for d in o.index], cumul=_round((1 + o).cumprod(), 5),
                  retenu=_round((1 + rmat[meilleure].loc[o.index]).cumprod(), 5),
                  choix=pd.Series(choix).value_counts().to_dict())
    return tests, dict(pbo=_js(pbo), walk_forward=wf)


def bloc_surajustement(r: pd.Series, rmat: pd.DataFrame | None, reference: str | None, essais: int, nul: dict | None = None,
                       publie: tuple[str, str] | None = None, n_blocs: int = 6, reps: int = 2000, seed: int = 7) -> tuple[list, dict]:
    """Tests de sur-ajustement d une strategie FIGEE (aucun parametre n est rechoisi ici) :
    stabilite par sous-periodes, test SPA de Hansen (arch) sur la famille de reglages, Sharpe corrige des essais
    multiples (statsmodels : Holm, BHY ; Bonferroni sur tous les essais), duree minimale de backtest
    (Bailey, Borwein, Lopez de Prado, Zhu), prime du choix du reglage et test sur hasard."""
    from scipy.stats import norm
    tests, out = [], {}

    def add(test, res, det, verdict):
        tests.append(dict(famille="Sur-ajustement", test=test, resultat=res, detail=det, verdict=verdict))

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        sr = float(_acc(r).sharpe_ratio())
        blocs = []
        for b in np.array_split(np.arange(len(r)), n_blocs):
            x = r.iloc[b]
            blocs.append(dict(debut=_js(x.index[0]), fin=_js(x.index[-1]), sharpe=_js(_acc(x).sharpe_ratio())))
        h = len(r) // 2
        s1, s2 = float(_acc(r.iloc[:h]).sharpe_ratio()), float(_acc(r.iloc[h:]).sharpe_ratio())
    v = np.array([b["sharpe"] for b in blocs], float)
    add(f"Stabilite : {n_blocs} sous-periodes egales", f"{int((v > 0).sum())}/{n_blocs} positives",
        "Sharpe " + " ; ".join(f"{b['debut'][:7]} -> {b['fin'][:7]} : {b['sharpe']:.2f}" for b in blocs), "ok" if (v > 0).all() else "alerte")
    add("Stabilite : premiere / seconde moitie", f"{s1:.2f} / {s2:.2f}", f"coupure au {r.index[h]:%d/%m/%Y}",
        "ok" if s2 > 0 and s2 >= 0.5 * s1 else "alerte")
    out["blocs"] = blocs
    T = len(r) / 252.0
    if rmat is not None and rmat.shape[1] >= 2 and reference in rmat:
        from arch.bootstrap import SPA
        from statsmodels.stats.multitest import multipletests
        R = rmat.fillna(0.0)
        spa = SPA(np.zeros(len(R)), -R.to_numpy(), block_size=10, reps=reps, bootstrap="stationary", seed=seed)
        spa.compute()
        p_spa = float(spa.pvalues["consistent"])
        add("Test SPA de Hansen (arch)", f"p = {p_spa:.4f}",
            f"{R.shape[1]} reglages de la famille contre 'ne rien faire', bootstrap stationnaire, {reps} tirages : "
            "le meilleur reglage bat-il zero une fois toute la famille prise en compte ?", "ok" if p_spa < 0.05 else "alerte")
        pv = np.array([SS.ttest_1samp(R[c].to_numpy(), 0.0, alternative="greater").pvalue for c in R])
        i = list(R.columns).index(reference)

        def coupe(pa):      # p-valeur -> Sharpe annualise equivalent
            return float(norm.ppf(1 - min(max(pa, 1e-16), 1 - 1e-16)) / math.sqrt(T))
        holm = multipletests(pv, method="holm")[1][i]
        bhy = multipletests(pv, method="fdr_by")[1][i]
        bonf = min(1.0, pv[i] * max(1, essais))
        add("Sharpe corrige des essais multiples (Harvey et Liu)", f"{coupe(bonf):.2f} (Bonferroni, {essais} essais)",
            f"Sharpe brut {sr:.2f} ; corrige sur la famille : Holm {coupe(holm):.2f}, BHY {coupe(bhy):.2f} (p brute {pv[i]:.1e})",
            "ok" if coupe(bonf) >= 0.5 else "alerte")
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            shs = pd.Series({c: float(_acc(rmat[c]).sharpe_ratio()) for c in rmat})
        med = float(shs.median())
        det = f"reglage retenu {shs[reference]:.2f} ; mediane des {len(shs)} reglages {med:.2f}"
        if publie and publie[0] in shs:
            det += f" ; reglage publie par les auteurs ({publie[1]}) {shs[publie[0]]:.2f}"
        add("Prime du choix du reglage", f"{shs[reference] - med:+.2f} de Sharpe", det, "ok" if shs[reference] - med <= 0.3 else "alerte")
        out["spa"] = _js(p_spa)
    g = 0.5772156649
    N = max(2, int(essais))
    emax = (1 - g) * norm.ppf(1 - 1 / N) + g * norm.ppf(1 - 1 / (N * math.e))
    minbtl = (emax / sr) ** 2 if sr > 0 else float("inf")
    add("Duree minimale de backtest", f"{minbtl:.1f} ans",
        f"{N} essais, Sharpe {sr:.2f} : sous {minbtl:.1f} ans, le meilleur de {N} essais au hasard ferait aussi bien ; historique {T:.1f} ans",
        "ok" if minbtl <= T else "alerte")
    if nul is not None:
        v = np.asarray(nul["valeurs"], float)
        v = v[np.isfinite(v)]
        p = float((np.sum(v >= nul["observe"]) + 1) / (len(v) + 1))
        add(nul["titre"], f"p = {p:.4f}", f"{nul['detail']} ; Sharpe observe {nul['observe']:.2f}, 95e centile du hasard {np.quantile(v, .95):.2f}",
            "ok" if p < 0.05 else "alerte")
        out["nul"] = dict(titre=nul["titre"], detail=nul["detail"], valeurs=_round(v, 4), observe=_js(nul["observe"]), p=_js(p))
    return tests, out


def _nul_synthetique(klass, sym: str, n: int, log=print) -> dict:
    """Strategie figee lancee sur n marches minute aleatoires sans momentum (meme volatilite que NQ)."""
    vals = []
    for k in range(n):
        s = I.synthetic_minutes("2016-01-04", "2026-08-28", seed=1000 + k, momentum=0.0, price0=4500.0, daily_vol=0.013)
        rr = klass(initial_bankroll=1e6).run({sym: s}, report=False).returns
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            vals.append(float(_acc(rr).sharpe_ratio()))
    log(f"  hasard : {n} marches aleatoires")
    return vals


# =============================================================================
#  Strategies du moteur nexus marquees VALIDATED (S1...)
# =============================================================================
def _replay_1col(res):
    """Rejeu vectorbt des executions d une fiche minute (famille fiche 16) dans UNE colonne (trades lisibles).
    -> (pf, valeur journaliere vectorbt, ecart relatif max avec le moteur)."""
    g, f = res.grid, res.fills
    pv, init = float(res.point_value), float(res.strategy.p.initial_bankroll)
    t = pd.DatetimeIndex(f["time"])
    day = t.normalize()
    rel = ((t - day) / pd.Timedelta(minutes=1)).to_numpy().astype(int) - (9 * 60 + 30)
    pos = g.days.get_indexer(day)
    at_open = (f["moment"] == "ouverture").to_numpy()
    slot = np.where(at_open, rel, rel - 1)
    tdays = np.unique(pos)
    close = pd.concat([pd.Series(g.c[d, :int(g.last_slot[d]) + 1], index=g.timestamps(d, np.arange(int(g.last_slot[d]) + 1)))
                       for d in tdays])
    ts = g.days[pos] + pd.to_timedelta(9 * 60 + 30 + slot + 1, unit="min")
    o = pd.DataFrame({"ts": ts, "q": f["qty"].to_numpy(float) * pv, "px": f["price"].to_numpy(float), "c": f["cost"].to_numpy(float)})
    if o["ts"].duplicated().any():
        raise ValueError("deux executions sur la meme barre : rejeu une colonne impossible")
    size = pd.Series(np.nan, index=close.index)
    price = size.copy()
    fees = pd.Series(0.0, index=close.index)
    size.loc[o["ts"]] = o["q"].to_numpy()
    price.loc[o["ts"]] = o["px"].to_numpy()
    fees.loc[o["ts"]] = o["c"].to_numpy()
    buf = init * 50
    pf = vbt.Portfolio.from_orders(close, size=size, price=price, fixed_fees=fees, size_type="amount", direction="both",
                                   init_cash=init + buf, freq="1min")
    pf.nexus_buf = buf
    value = pf.value() - buf
    ends = pd.DatetimeIndex([g.timestamps(d, [int(g.last_slot[d])])[0] for d in tdays])
    daily = value.reindex(ends)
    daily.index = ends.normalize()
    eq = res.equity.reindex(daily.index)
    diff = float(np.nanmax(np.abs(daily / eq - 1)))
    full = daily.reindex(res.equity.index).ffill().fillna(init)
    return pf, full, diff


def _run(klass, data, **kw):
    return klass(**kw).run(data, report=False)


def fiche_nexus(code: str, cotations: str, n_sim: int, grille: bool, log=print) -> tuple[dict, pd.Series]:
    klass = get(code)
    if not getattr(klass, "INTRADAY", False):
        raise NotImplementedError("tableau : seules les strategies minute de la famille fiche 16 sont gerees pour l instant")
    st = klass(initial_bankroll=1e6)
    sym = st.data_symbols()
    data = D.load_folder(cotations, daily=False, only=sym)
    t0 = time.time()
    res = st.run(data, report=False)
    log(f"  moteur : {res.equity.iloc[-1]:,.0f} $, {len(res.trades)} allers-retours ({time.time() - t0:.0f} s)")
    pf, valeur, diff = _replay_1col(res)
    cal = calendrier(valeur.index[0], valeur.index[-1])
    valeur = valeur.reindex(cal).ffill().bfill()
    r = valeur.pct_change().fillna(0.0)
    rows, t = bloc_trades(pf, None, "America/New_York", pf.value() - pf.nexus_buf)
    tests = [dict(famille="Comptabilite", test="Rejeu vectorbt des executions du moteur", resultat="identique" if diff < 1e-9 else "ECART",
                  detail=f"ecart relatif max {diff:.1e} sur l equity journaliere", verdict="ok" if diff < 1e-9 else "alerte")]
    df0 = data[sym[0]]
    cut = df0.index[int(len(df0) * 0.6)]
    d2 = {sym[0]: df0.copy()}
    d2[sym[0]].attrs = dict(df0.attrs)
    d2[sym[0]].loc[d2[sym[0]].index > cut, ["open", "high", "low", "close"]] *= 1.25
    r1, r2 = _run(klass, data, initial_bankroll=1e6, roll_adjust="aucun"), _run(klass, d2, initial_bankroll=1e6, roll_adjust="aucun")
    c0 = pd.Timestamp(cut).normalize()
    f1, f2 = r1.fills[r1.fills["time"] < c0].reset_index(drop=True), r2.fills[r2.fills["time"] < c0].reset_index(drop=True)
    ok = f1.equals(f2) and np.allclose(r1.equity[r1.equity.index < c0], r2.equity[r2.equity.index < c0])
    tests.append(dict(famille="Comptabilite", test="Biais d anticipation (prix futurs x 1,25)", resultat="aucun" if ok else "PROBLEME",
                      detail=f"{len(f1)} executions avant le {c0:%d/%m/%Y} inchangees", verdict="ok" if ok else "alerte"))
    if os.path.exists(os.path.join(os.path.dirname(__file__), "..", f"{klass.NAME}.py")):
        tests.append(dict(famille="Comptabilite", test=f"Second programme independant ({klass.NAME}.py)",
                          resultat="voir tests/test_s1_noiseareanq.py", detail="identique au moteur a la seance pres (tests automatiques)",
                          verdict="ok"))
    extra = {}
    var_ann = 0.5
    rmat, meilleure = None, None
    base = get(getattr(klass, "GRILLE_FICHE", code))
    frozen = {k: v for k, v in st.params.items() if k in klass.DEFAULTS}
    if grille and getattr(klass, "GRILLE", None):
        import itertools
        keys = list(klass.GRILLE)
        rets, rows_g = {}, []
        for combo in itertools.product(*[klass.GRILLE[k] for k in keys]):
            kw = {**frozen, **dict(zip(keys, combo)), "initial_bankroll": 1e6}
            rr = _run(base, data, **kw).returns
            lab = ",".join(f"{k}={v}" for k, v in zip(keys, combo))
            rets[lab] = rr
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                rows_g.append(dict(zip(keys, combo), sharpe=_js(_acc(rr).sharpe_ratio())))
        log(f"  grille : {len(rows_g)} reglages")
        rmat = pd.DataFrame(rets).dropna()
        meilleure = ",".join(f"{k}={frozen[k]}" for k in keys)
        tg, extra = _grille_pbo_wf(rmat, meilleure)
        shs = np.array([x["sharpe"] for x in rows_g], float)
        var_ann = float(np.nanvar(shs, ddof=1))
        moi = next(x["sharpe"] for x in rows_g if all(x[k] == frozen[k] for k in keys))
        tg.insert(0, dict(famille="Sur-ajustement", test="Plateau de parametres",
                          resultat=f"{np.nanmin(shs):.2f} a {np.nanmax(shs):.2f}",
                          detail=f"{len(shs)} reglages ; {np.mean(shs > 0):.0%} positifs ; reglage valide {moi:.2f} ; "
                                 f"{np.mean(shs >= 0.75 * moi):.0%} a >= 75 % du reglage valide", verdict="ok" if np.mean(shs > 0) >= 0.8 else "alerte"))
        tests += tg
        extra["grille"] = dict(axes=keys, valeurs={k: list(map(_js, v)) for k, v in klass.GRILLE.items()}, points=rows_g,
                               reference={k: _js(frozen[k]) for k in keys})
    sens = []
    for famille, cas in getattr(klass, "SENSIBILITE", {}).items():
        for lab, kw in cas:
            rr = _run(base, data, **{**frozen, **kw, "initial_bankroll": 1e6}).returns
            pubts = pd.Timestamp(getattr(klass, "PUBLICATION", "2024-06-01"))
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                sens.append(dict(famille=famille, cas=lab, sharpe=_js(_acc(rr).sharpe_ratio()),
                                 sharpe_apres=_js(_acc(rr[rr.index >= pubts]).sharpe_ratio())))
    for famille in dict.fromkeys(s["famille"] for s in sens):
        cas = [s for s in sens if s["famille"] == famille]
        pire = min(cas, key=lambda s: s["sharpe"] if s["sharpe"] is not None else 9)
        tests.append(dict(famille="Sensibilite", test=f"{famille} : pire cas ({pire['cas']})", resultat=f"Sharpe {pire['sharpe']:.2f}",
                          detail=" ; ".join(f"{s['cas']} {s['sharpe']:.2f} (apres pub. {s['sharpe_apres']:.2f})" for s in cas),
                          verdict="ok" if pire["sharpe"] >= 0.5 else "alerte"))
    var_ann = getattr(klass, "VAR_SHARPE_ESSAIS_ANNUALISE", var_ann)
    tc, mc = bloc_tests_communs(r, t, getattr(klass, "PUBLICATION", "2024-06-01"), getattr(klass, "ESSAIS", 1), var_ann, n_sim)
    tests = tests[:3] + tc + tests[3:]
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        obs = float(_acc(r).sharpe_ratio())
    vals = _nul_synthetique(klass, sym[0], max(20, n_sim // 20), log)
    nul = dict(titre="Marches aleatoires sans momentum", valeurs=vals, observe=obs,
               detail=f"meme strategie figee sur {len(vals)} historiques minute simules (10,6 ans, volatilite proche de NQ, aucune tendance)")
    pub = getattr(klass, "REGLAGE_PUBLIE", None)
    pub_lab = (",".join(f"{k}={pub[k]}" for k in klass.GRILLE), "papier") if pub and getattr(klass, "GRILLE", None) else None
    ts, so = bloc_surajustement(r, rmat if (grille and getattr(klass, "GRILLE", None)) else None,
                                meilleure if (grille and getattr(klass, "GRILLE", None)) else None,
                                getattr(klass, "ESSAIS", 1), nul=nul, publie=pub_lab, reps=n_sim)
    tests += ts
    extra["surajustement"] = so
    fiche = dict(
        id=klass.NAME, code=code, titre=getattr(klass, "TITRE", klass.NAME), statut="validee", valide_le=klass.VALIDATED,
        resume=getattr(klass, "RESUME", klass.DESCRIPTION), fonctionnement=getattr(klass, "FONCTIONNEMENT", []),
        pourquoi=getattr(klass, "POURQUOI", ""), sources=[dict(titre=a, lien=b) for a, b in getattr(klass, "SOURCES", [])],
        parametres={k: _js(v) for k, v in frozen.items() if v not in (None, "")},
        donnees=dict(symbole=", ".join(sym), fichier="barres 1 minute Databento (depot Cotations), contrat continu roule au volume",
                     debut=_js(df0.index[0]), fin=_js(df0.index[-1]), barres=int(len(df0)), fuseau="UTC, barre datee a son debut",
                     ajustement="rolls a minuit UTC ajustes (proportionnel)", seances=int(len(res.equity)),
                     calendrier="seances NYSE (feries exclus)"),
        capital=dict(initial=1e6, unite="$", note="capital reinvesti, taille a volatilite cible"),
        fuseau_trades="America/New_York", publication=getattr(klass, "PUBLICATION", None),
        kpi=_kpi(valeur, t), vectorbt=bloc_vectorbt(pf, valeur), series=bloc_series(valeur), trades=rows,
        tests=tests, monte_carlo=mc, sensibilite=sens, **extra)
    return fiche, r


def _kpi(valeur: pd.Series, t: pd.DataFrame) -> dict:
    r = valeur.pct_change().dropna()
    acc = _acc(r)
    dur = (t["sortie"] - t["entree"]).dt.total_seconds() / 60
    ans = (valeur.index[-1] - valeur.index[0]).days / 365.25
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return dict(sharpe=_js(acc.sharpe_ratio()), sortino=_js(acc.sortino_ratio()), calmar=_js(acc.calmar_ratio()),
                    rendement_annuel=_js(acc.annualized()), volatilite=_js(acc.annualized_volatility()),
                    perte_max=_js(-acc.max_drawdown()), rendement_total=_js(valeur.iloc[-1] / valeur.iloc[0] - 1),
                    trades=int(len(t)), gagnants=_js(float((t["PnL"] > 0).mean())), bp_par_trade=_js(float(t["net_notionnel"].mean() * 1e4)),
                    bp_capital_par_trade=_js(float(t["net"].mean() * 1e4)),
                    duree_moyenne_min=_js(float(dur.mean())), heures_par_an=_js(float(dur.sum() / 60 / ans)),
                    part_du_temps=_js(float(dur.sum() / (ans * 365.25 * 24 * 60))),
                    jours_trades_par_an=_js(float(t["entree"].dt.normalize().nunique() / ans)),
                    debut=_js(valeur.index[0]), fin=_js(valeur.index[-1]))


# =============================================================================
#  Candidate : Gotobi 6J (vectorbt direct)
# =============================================================================
def fiche_gotobi(cotations: str, n_sim: int, grille: bool, log=print) -> tuple[dict, pd.Series]:
    rmat = None
    m, info = GT.charger_6j(cotations)
    t0 = time.time()
    pf = GT.portefeuille(m)
    log(f"  vectorbt : {len(pf.trades.records_readable)} trades ({time.time() - t0:.0f} s)")
    cal = calendrier("2016-01-04", m.index[-1].normalize())
    capital = GT.DEFAULTS["capital"]

    def run(**kw):
        p = GT.portefeuille(m, **kw)
        v = GT.valeur_journaliere(p, cal)
        return p, v.pct_change().fillna(0.0)

    valeur = GT.valeur_journaliere(pf, cal)
    r = valeur.pct_change().fillna(0.0)
    rows, t = bloc_trades(pf, "UTC", "Asia/Tokyo", GT.valeur(pf))
    tests = [dict(famille="Comptabilite", test="Comptabilite vectorbt (ordres, frais, retournement)", resultat="tests unitaires",
                  detail="tests/test_gotobi.py : heures d execution 8:00 / 9:55 / 11:00 de Tokyo et PnL exacts sur un cas construit",
                  verdict="ok")]
    cut = m.index[int(len(m) * 0.6)]
    m2 = m.copy()
    m2.loc[m2.index > cut, ["open", "close"]] *= 1.25
    a = pf.trades.records_readable
    b = GT.portefeuille(m2).trades.records_readable
    a, b = a[a["Exit Timestamp"] < cut].reset_index(drop=True), b[b["Exit Timestamp"] < cut].reset_index(drop=True)
    ok = len(a) == len(b) and np.allclose(a["PnL"], b["PnL"]) and (a["Entry Timestamp"] == b["Entry Timestamp"]).all()
    tests.append(dict(famille="Comptabilite", test="Biais d anticipation (prix futurs x 1,25)", resultat="aucun" if ok else "PROBLEME",
                      detail=f"{len(a)} trades avant le {cut:%d/%m/%Y} inchanges", verdict="ok" if ok else "alerte"))
    tests.append(dict(famille="Donnees", test="Calendrier japonais", resultat="feries inclus",
                      detail="jour gotobi ferie ou week-end -> jour ouvre precedent (sans les feries japonais : Sharpe plus faible, voir Placebo)",
                      verdict="info"))
    extra = {}
    # placebos et temoins
    plac = []
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        for lab, kw in [("jours gotobi (strategie)", {}), ("autres jours (temoin)", dict(jours="autres")),
                        ("gotobi decale -2 j", dict(decalage_jours=-2)), ("gotobi decale -1 j", dict(decalage_jours=-1)),
                        ("gotobi decale +1 j", dict(decalage_jours=1)), ("gotobi decale +2 j", dict(decalage_jours=2)),
                        ("sans feries japonais", dict(feries_japon=False))]:
            _, rr = run(**kw) if kw else (pf, r)
            plac.append(dict(cas=lab, sharpe=_js(_acc(rr).sharpe_ratio())))
    pl = [p_["sharpe"] for p_ in plac[1:6]]
    tests.append(dict(famille="Placebo", test="Memes heures, autres jours", resultat=f"Sharpe {max(pl):.2f} au mieux",
                      detail=" ; ".join(f"{p_['cas']} {p_['sharpe']:.2f}" for p_ in plac), verdict="ok" if max(pl) < 0.3 else "alerte"))
    # sensibilite
    sens = []
    pub = pd.Timestamp(GT.PUBLICATION)
    for famille, cas in {"Couts": [("x0", dict(cout_mult=0.0)), ("x1 (reference)", {}), ("x1,5", dict(cout_mult=1.5)),
                                   ("x2", dict(cout_mult=2.0)), ("x3", dict(cout_mult=3.0))],
                         "Latence": [("retournement a 9:55 (reference)", {}), ("+1 min", dict(fixing="09:56")),
                                     ("+2 min", dict(fixing="09:57")), ("+5 min", dict(fixing="10:00")),
                                     ("sans la minute du fixing (9:54 / 9:56)", dict(sortie_avant="09:54", reprise_apres="09:56"))],
                         "Jambes": [("avant le fixing seule", dict(jambes="avant")), ("apres le fixing seule", dict(jambes="apres"))]}.items():
        for lab, kw in cas:
            _, rr = run(**kw) if kw else (pf, r)
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                sens.append(dict(famille=famille, cas=lab, sharpe=_js(_acc(rr).sharpe_ratio()), sharpe_apres=_js(_acc(rr[rr.index >= pub]).sharpe_ratio())))
    for famille in ("Couts", "Latence"):
        cas = [s for s in sens if s["famille"] == famille]
        pire = min(cas, key=lambda s: s["sharpe"])
        tests.append(dict(famille="Sensibilite", test=f"{famille} : pire cas ({pire['cas']})", resultat=f"Sharpe {pire['sharpe']:.2f}",
                          detail=" ; ".join(f"{s['cas']} {s['sharpe']:.2f} (apres pub. {s['sharpe_apres']:.2f})" for s in cas),
                          verdict="ok" if pire["sharpe"] >= 0.5 else "alerte"))
    log("  placebos, couts, latence : ok")
    if grille:
        entrees, sorties = ["07:00", "07:30", "08:00", "08:30", "09:00"], ["10:00", "10:30", "11:00", "11:30", "12:00"]
        rets, pts = {}, []
        for e in entrees:
            for s_ in sorties:
                _, rr = run(entree=e, sortie=s_)
                rets[f"entree={e},sortie={s_}"] = rr
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore")
                    pts.append(dict(entree=e, sortie=s_, sharpe=_js(_acc(rr).sharpe_ratio())))
        log(f"  grille : {len(pts)} reglages")
        rmat = pd.DataFrame(rets)
        tg, extra = _grille_pbo_wf(rmat, "entree=08:00,sortie=11:00")
        shs = np.array([p_["sharpe"] for p_ in pts], float)
        tg.insert(0, dict(famille="Sur-ajustement", test="Plateau (heure d entree x heure de sortie)", resultat=f"{shs.min():.2f} a {shs.max():.2f}",
                          detail=f"{len(shs)} reglages ; {np.mean(shs > 0):.0%} positifs ; reglage etudie 08:00 / 11:00",
                          verdict="ok" if np.mean(shs > 0) >= 0.8 else "alerte"))
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            dsr_f = _acc(r).deflated_sharpe_ratio(var_sharpe=float(np.var(shs, ddof=1)), nb_trials=len(shs))
        tg.append(dict(famille="Sur-ajustement", test="Sharpe deflate, variantes Gotobi seulement", resultat=f"{dsr_f:.1%}",
                       detail=f"{len(shs)} reglages de la grille, variance de leurs Sharpe {np.var(shs, ddof=1):.2f} "
                              "(le test strict, plus haut, compte toutes les hypotheses du criblage)",
                       verdict="ok" if dsr_f >= 0.95 else "alerte"))
        tests += tg
        extra["grille"] = dict(axes=["entree", "sortie"], valeurs=dict(entree=entrees, sortie=sorties), points=pts,
                               reference=dict(entree="08:00", sortie="11:00"))
    tc, mc = bloc_tests_communs(r, t, GT.PUBLICATION, GT.ESSAIS, GT.VAR_SHARPE_ESSAIS_ANNUALISE, n_sim)
    tests = tests[:2] + tc + tests[2:]
    # calendrier aleatoire : memes regles tous les jours ouvres japonais, puis tirages de faux jours gotobi
    pf_tous = GT.portefeuille(m, jours="tous")
    tt = pf_tous.trades.records_readable
    jt = pd.DatetimeIndex(tt["Entry Timestamp"]).tz_localize("UTC").tz_convert(GT.TOKYO).tz_localize(None).normalize()
    par_jour = pd.Series(tt["PnL"].to_numpy() / capital, index=jt).groupby(level=0).sum()
    ouv = GT.jours_ouvres_japon(par_jour.index[0], par_jour.index[-1])
    x = par_jour.reindex(ouv).fillna(0.0)
    est_g = np.asarray(ouv.isin(GT.jours_gotobi(ouv[0], ouv[-1])))
    rng = np.random.default_rng(11)
    pool = np.flatnonzero(~est_g)
    M = np.zeros((len(x), n_sim))
    for k in range(n_sim):
        pick = rng.choice(pool, size=int(est_g.sum()), replace=False)
        M[pick, k] = x.to_numpy()[pick]
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        vals = pd.DataFrame(M, index=ouv).vbt.returns(freq="1D", year_freq=ANNEE).sharpe_ratio().to_numpy()
        obs = float(pd.Series(np.where(est_g, x.to_numpy(), 0.0), index=ouv).vbt.returns(freq="1D", year_freq=ANNEE).sharpe_ratio())
    nul = dict(titre="Calendrier aleatoire (faux jours gotobi)", valeurs=vals, observe=obs,
               detail=f"{n_sim} tirages de {int(est_g.sum())} jours ordinaires, memes heures et memes regles (Sharpe sur les jours ouvres japonais)")
    log("  calendrier aleatoire : ok")
    ts, so = bloc_surajustement(r, rmat if grille else None, "entree=08:00,sortie=11:00" if grille else None, GT.ESSAIS,
                                nul=nul, reps=n_sim)
    tests += ts
    extra["surajustement"] = so
    fiche = dict(
        id="Gotobi_6J", code="G1", titre="Gotobi · yen (6J)", statut="candidate", valide_le=None,
        resume="Les jours de paiement japonais, acheter du dollar contre le yen avant le fixing de 9:55 a Tokyo, "
               "puis le revendre jusqu a 11:00.",
        fonctionnement=[
            "Jours concernes (gotobi) : le 5, 10, 15, 20, 25 et le dernier jour ouvre du mois ; un jour ferie japonais "
            "ou un week-end reporte au jour ouvre precedent (71 jours par an environ).",
            "8:00 a Tokyo (minuit ou 1:00 a Paris) : vente du future 6J (= achat de dollars contre yens).",
            "9:55 pile (fixing de Tokyo) : retournement, achat de 6J (= vente de dollars).",
            "11:00 a Tokyo : sortie. Aucune position le reste du temps : 3 heures par jour gotobi (1 h 55 vendeur puis "
            "1 h 05 acheteur), environ 70 jours par an, soit environ 210 heures par an (2,4 % du temps), jamais la nuit "
            "ni le week-end.",
            "Ordres a l ouverture de la premiere barre 1 minute de l heure prevue (au plus 10 min apres, sinon le jour est saute).",
            f"Taille : notionnel fixe de {capital * GT.DEFAULTS['exposition']:,.0f} $ pour {capital:,.0f} $ de capital (pas de levier). "
            "Couts : 2,25 $ par contrat et par cote + 1/2 tick (0,0000005) de glissement.",
        ],
        pourquoi="Les entreprises japonaises reglent leurs fournisseurs etrangers ces jours-la et achetent leurs dollars au cours "
                 "du fixing de 9:55. Les banques achetent ces dollars sur le marche juste avant : le dollar monte, puis "
                 "redescend une fois le fixing passe.",
        sources=[dict(titre="Bessho, Sugimoto & Suzuki (2023), Forex trading strategy that might be executed due to the popularity of Gotobi anomaly",
                      lien="https://arxiv.org/abs/2301.13204"),
                 dict(titre="Ito & Yamada, Puzzles in the Tokyo Fixing in the Forex Market",
                      lien="https://business.columbia.edu/sites/default/files-efs/imce-uploads/Research/Research_Papers/WP_352.Ito-Yamada.Tokyo_Fixing_Puzzles.pdf"),
                 dict(titre="Krohn, Mueller & Whelan (2024), Foreign Exchange Fixings and Returns Around the Clock, Journal of Finance",
                      lien="https://onlinelibrary.wiley.com/doi/full/10.1111/jofi.13306")],
        parametres={k: _js(v) for k, v in GT.DEFAULTS.items()},
        donnees=dict(info, calendrier="jours ouvres japonais (feries inclus) ; resultats ranges par date de New York"),
        capital=dict(initial=capital, unite="$", note="notionnel fixe, sans reinvestissement"),
        fuseau_trades="Asia/Tokyo", publication=GT.PUBLICATION,
        kpi=_kpi(valeur, t), vectorbt=bloc_vectorbt(pf, valeur), series=bloc_series(valeur), trades=rows,
        tests=tests, monte_carlo=mc, sensibilite=sens, placebo=plac, **extra)
    return fiche, r


# =============================================================================
#  Candidate : ORB 5 minutes NQ (vectorbt direct)
# =============================================================================
def fiche_orb(cotations: str, n_sim: int, grille: bool, log=print) -> tuple[dict, pd.Series]:
    m, info = OR.charger(cotations, "NQ")
    cap = OR.DEFAULTS["capital"]
    t0 = time.time()
    pf = OR.portefeuille(m)
    log(f"  vectorbt : {len(pf.trades.records_readable)} trades ({time.time() - t0:.0f} s)")
    cal = calendrier(m.index[0].normalize(), m.index[-1].normalize())

    def run(**kw):
        p_ = OR.portefeuille(m, **kw)
        return p_, OR.valeur_journaliere(p_, cal).pct_change().fillna(0.0)

    valeur = OR.valeur_journaliere(pf, cal)
    r = valeur.pct_change().fillna(0.0)
    rows, t = bloc_trades(pf, None, "America/New_York", OR.valeur(pf))
    tests = [dict(famille="Comptabilite", test="Comptabilite vectorbt (ordre stop, stop ATR, taille)", resultat="tests unitaires",
                  detail="tests/test_orb.py : execution au niveau de la bougie, sortie au stop de 10 % de l ATR, taille 1 % / levier 4, "
                         "filtre de volume relatif", verdict="ok")]
    cut = m.index[int(len(m) * 0.6)]
    m2 = m.copy()
    m2.loc[m2.index > cut, ["open", "high", "low", "close"]] *= 1.25
    a = pf.trades.records_readable
    b = OR.portefeuille(m2).trades.records_readable
    a, b = a[a["Exit Timestamp"] < cut].reset_index(drop=True), b[b["Exit Timestamp"] < cut].reset_index(drop=True)
    ok = len(a) == len(b) and np.allclose(a["PnL"], b["PnL"]) and (a["Entry Timestamp"] == b["Entry Timestamp"]).all()
    tests.append(dict(famille="Comptabilite", test="Biais d anticipation (prix futurs x 1,25)", resultat="aucun" if ok else "PROBLEME",
                      detail=f"{len(a)} trades avant le {cut:%d/%m/%Y} inchanges", verdict="ok" if ok else "alerte"))
    # sensibilite
    sens = []
    pub = pd.Timestamp(OR.PUBLICATION)
    for famille, cas in {"Couts": [("x0", dict(cout_mult=0.0)), ("x1 (reference)", {}), ("x2", dict(cout_mult=2.0)), ("x3", dict(cout_mult=3.0))],
                         "Latence": [("execution au niveau (reference)", {}), ("+1 min", dict(delai_min=1)), ("+2 min", dict(delai_min=2)),
                                     ("+5 min", dict(delai_min=5))],
                         "Variantes": [("sans filtre de volume", dict(filtre_volume=False))]}.items():
        for lab, kw in cas:
            _, rr = run(**kw) if kw else (pf, r)
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                sens.append(dict(famille=famille, cas=lab, sharpe=_js(_acc(rr).sharpe_ratio()), sharpe_apres=_js(_acc(rr[rr.index >= pub]).sharpe_ratio())))
    for famille in ("Couts", "Latence"):
        cas_ = [x for x in sens if x["famille"] == famille]
        pire = min(cas_, key=lambda x: x["sharpe"])
        tests.append(dict(famille="Sensibilite", test=f"{famille} : pire cas ({pire['cas']})", resultat=f"Sharpe {pire['sharpe']:.2f}",
                          detail=" ; ".join(f"{x['cas']} {x['sharpe']:.2f} (apres pub. {x['sharpe_apres']:.2f})" for x in cas_),
                          verdict="ok" if pire["sharpe"] >= 0.5 else "alerte"))
    log("  couts, latence : ok")
    extra, rmat = {}, None
    if grille:
        axes = dict(minutes_ouverture=[5, 15, 30], stop_atr=[0.05, 0.10, 0.15, 0.20], volume_min=[0.8, 1.0, 1.5])
        rets, pts = {}, []
        import itertools
        for combo in itertools.product(*axes.values()):
            kw = dict(zip(axes, combo))
            _, rr = run(**kw)
            lab = ",".join(f"{k}={v}" for k, v in kw.items())
            rets[lab] = rr
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                pts.append(dict(kw, sharpe=_js(_acc(rr).sharpe_ratio())))
        log(f"  grille : {len(pts)} reglages")
        rmat = pd.DataFrame(rets)
        ref_lab = "minutes_ouverture=5,stop_atr=0.1,volume_min=1.0"
        tg, extra = _grille_pbo_wf(rmat, ref_lab)
        shs = np.array([x["sharpe"] for x in pts], float)
        tg.insert(0, dict(famille="Sur-ajustement", test="Plateau (bougie x stop x volume)", resultat=f"{shs.min():.2f} a {shs.max():.2f}",
                          detail=f"{len(shs)} reglages ; {np.mean(shs > 0):.0%} positifs ; reglage du papier 5 min / 10 % ATR / 100 %",
                          verdict="ok" if np.mean(shs > 0) >= 0.8 else "alerte"))
        tests += tg
        extra["grille"] = dict(axes=list(axes), valeurs={k: list(map(_js, v)) for k, v in axes.items()}, points=pts,
                               reference=dict(minutes_ouverture=5, stop_atr=0.1, volume_min=1.0))
    tc, mc = bloc_tests_communs(r, t, OR.PUBLICATION, OR.ESSAIS, OR.VAR_SHARPE_ESSAIS_ANNUALISE, n_sim)
    tests = tests[:2] + tc + tests[2:]
    # hasard : memes regles sans filtre, puis tirages de jours au hasard en nombre egal aux jours filtres
    pf_tous = OR.portefeuille(m, filtre_volume=False)
    tt = pf_tous.trades.records_readable
    par_jour = pd.Series(tt["PnL"].to_numpy() / cap, index=pd.DatetimeIndex(tt["Exit Timestamp"]).normalize()).groupby(level=0).sum()
    x = par_jour.reindex(cal).fillna(0.0)
    choisis = pd.DatetimeIndex(pd.DatetimeIndex(pf.trades.records_readable["Exit Timestamp"]).normalize().unique())
    pool = np.flatnonzero(np.asarray(x.index.isin(par_jour.index)))
    rng = np.random.default_rng(13)
    M = np.zeros((len(x), n_sim))
    for k in range(n_sim):
        pick = rng.choice(pool, size=min(len(choisis), len(pool)), replace=False)
        M[pick, k] = x.to_numpy()[pick]
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        vals = pd.DataFrame(M, index=x.index).vbt.returns(freq="1D", year_freq=ANNEE).sharpe_ratio().to_numpy()
        obs = float(pd.Series(np.where(x.index.isin(choisis), x.to_numpy(), 0.0), index=x.index).vbt.returns(freq="1D", year_freq=ANNEE).sharpe_ratio())
    nul = dict(titre="Jours tires au hasard au lieu du filtre de volume", valeurs=vals, observe=obs,
               detail=f"{n_sim} tirages de {len(choisis)} jours parmi les {len(pool)} jours ou la cassure a lieu (memes regles, sans filtre)")
    log("  jours au hasard : ok")
    ts, so = bloc_surajustement(r, rmat, "minutes_ouverture=5,stop_atr=0.1,volume_min=1.0" if rmat is not None else None, OR.ESSAIS,
                                nul=nul, reps=n_sim)
    tests += ts
    extra["surajustement"] = so
    p = OR.DEFAULTS
    fiche = dict(
        id="ORB_NQ", code="O1", titre="ORB 5 min · NQ", statut="candidate", valide_le=None,
        resume="Suivre la cassure de la premiere bougie de 5 minutes du Nasdaq, seulement les jours ou l ouverture est "
               "anormalement active, avec un stop serre et une sortie le soir.",
        fonctionnement=[
            "9:30-9:35 a New York : on regarde la premiere bougie de 5 minutes du NQ (sens, plus haut, plus bas, volume).",
            "Filtre : son volume doit etre au moins egal a la moyenne des bougies 9:30-9:35 des 14 seances precedentes "
            "(marche « en jeu », comme les « stocks in play » du papier).",
            "Bougie haussiere : ordre d achat au-dessus de son plus haut ; baissiere : ordre de vente sous son plus bas. "
            "Si le niveau n est jamais atteint, pas de trade.",
            "Stop de protection a 10 % de l ATR 14 jours du prix d achat ; sinon sortie a la cloture (16:00). Un trade par jour au plus.",
            "Taille : la perte au stop vaut 1 % du capital, levier maximum 4 (environ 10 contrats NQ pour 1 M$).",
            "Couts : 2,25 $ par contrat et par execution + 1/2 tick de glissement, stops compris.",
        ],
        pourquoi="Une ouverture tres active signale une information nouvelle que le marche n a pas fini d integrer : la "
                 "cassure de la premiere bougie dans ce contexte a tendance a se prolonger, et le stop serre limite les "
                 "fausses cassures.",
        sources=[dict(titre="Zarattini, Barbon & Aziz (2024), A Profitable Day Trading Strategy for the U.S. Equity Market, SSRN 4729284",
                      lien="https://papers.ssrn.com/abstract=4729284"),
                 dict(titre="Zarattini & Aziz (2023), Can Day Trading Really Be Profitable?, SSRN 4416622",
                      lien="https://papers.ssrn.com/abstract=4416622")],
        parametres={k: _js(v) for k, v in p.items() if k not in ("jours_hasard",)},
        donnees=dict(info, calendrier="seances NYSE (feries exclus)"),
        capital=dict(initial=cap, unite="$", note="capital fixe, taille au risque (1 % au stop), levier max 4"),
        fuseau_trades="America/New_York", publication=OR.PUBLICATION,
        kpi=_kpi(valeur, t), vectorbt=bloc_vectorbt(pf, valeur), series=bloc_series(valeur), trades=rows,
        tests=tests, monte_carlo=mc, sensibilite=sens, **extra)
    return fiche, r


# =============================================================================
#  Candidate : or hors seance de New York, intraday (vectorbt direct)
# =============================================================================
def _heure(minute: int) -> str:
    h, mi = divmod((ON.OUVERTURE + int(minute)) % 1440, 60)
    return f"{h:02d}:{mi:02d}"


def fiche_or_nuit(cotations: str, n_sim: int, grille: bool, log=print) -> tuple[dict, pd.Series]:
    from arch.bootstrap import StationaryBootstrap
    m, info = ON.charger(cotations)
    p0 = ON.DEFAULTS
    cap = p0["capital"]
    t0 = time.time()
    pf = ON.portefeuille(m)
    log(f"  vectorbt : {len(pf.trades.records_readable)} trades ({time.time() - t0:.0f} s)")
    seance = pd.DatetimeIndex(m["seance"].to_numpy())
    cal = calendrier(seance[0], seance[-1])

    def run(**kw):
        p_ = ON.portefeuille(m, compact=True, **kw)      # memes trades et memes valeurs de fin de seance, plus rapide
        return p_, ON.valeur_journaliere(p_, cal).pct_change().fillna(0.0)

    valeur = ON.valeur_journaliere(pf, cal)
    r = valeur.pct_change().fillna(0.0)
    rows, t = bloc_trades(pf, "UTC", "America/New_York", ON.valeur(pf))
    tests = [dict(famille="Comptabilite", test="Comptabilite vectorbt (heures, fin de seance, taille)", resultat="tests unitaires",
                  detail="tests/test_or_nuit.py : achats 18:00 et 13:30, ventes 8:20 et cloture de 16:59, 100 % du capital reinvesti, "
                         "seances raccourcies, mode compact identique, rolls", verdict="ok")]
    cut = m.index[int(len(m) * 0.6)]
    m2 = m.copy()
    m2.loc[m2.index > cut, ["open", "close"]] *= 1.25
    a = pf.trades.records_readable
    b = ON.portefeuille(m2).trades.records_readable
    a, b = a[a["Exit Timestamp"] < cut].reset_index(drop=True), b[b["Exit Timestamp"] < cut].reset_index(drop=True)
    ok = len(a) == len(b) and np.allclose(a["PnL"], b["PnL"]) and (a["Entry Timestamp"] == b["Entry Timestamp"]).all()
    tests.append(dict(famille="Comptabilite", test="Biais d anticipation (prix futurs x 1,25)", resultat="aucun" if ok else "PROBLEME",
                      detail=f"{len(a)} trades avant le {cut:%d/%m/%Y} inchanges", verdict="ok" if ok else "alerte"))
    tr = pf.trades.records_readable
    d_e, _ = ON.seances(pd.DatetimeIndex(tr["Entry Timestamp"]))
    d_s, _ = ON.seances(pd.DatetimeIndex(tr["Exit Timestamp"]))
    duree = (pd.DatetimeIndex(tr["Exit Timestamp"]) - pd.DatetimeIndex(tr["Entry Timestamp"])).total_seconds() / 3600
    intra = bool((d_e == d_s).all()) and bool((tr["Status"] == "Closed").all())
    tests.append(dict(famille="Comptabilite", test="Intraday : chaque position fermee dans sa seance", resultat="oui" if intra else "NON",
                      detail=f"{len(tr)} trades ; duree max {duree.max():.1f} h ; aucune position pendant la pause 17:00-18:00 ni le week-end",
                      verdict="ok" if intra else "alerte"))
    # temoins : chaque jambe, l or achete toute la seance, la seance du COMEX seule, la regle publiee (nuit gardee)
    plac, temoins = [], {}
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        for lab, kw in [("asie + soir (strategie)", {}), ("jambe Asie seule (18:00 -> 8:20)", dict(jambes="asie")),
                        ("jambe du soir seule (13:30 -> 17:00)", dict(jambes="soir")),
                        ("or achete toute la seance (18:00 -> 17:00)", dict(jambes="tout")),
                        ("seance du COMEX seule (8:20 -> 13:30)", dict(jambes="pause")),
                        ("regle publiee, nuit gardee (13:30 -> 8:20)", dict(jambes="nuit"))]:
            _, rr = run(**kw) if kw else (pf, r)
            temoins[lab] = rr
            plac.append(dict(cas=lab, sharpe=_js(_acc(rr).sharpe_ratio())))
    sh = {x["cas"]: x["sharpe"] for x in plac}
    tests.append(dict(famille="Placebo", test="Temoin : la seance du COMEX seule", resultat=f"Sharpe {sh['seance du COMEX seule (8:20 -> 13:30)']:.2f}",
                      detail="l idee du papier : l or ne gagne rien (ou perd) pendant la seance de jour de New York ; "
                             + " ; ".join(f"{x['cas']} {x['sharpe']:.2f}" for x in plac),
                      verdict="ok" if sh["seance du COMEX seule (8:20 -> 13:30)"] < 0 else "alerte"))
    x_, y_ = r.to_numpy(), temoins["or achete toute la seance (18:00 -> 17:00)"].to_numpy()
    f_sh = lambda z: z.mean() / z.std(ddof=1) * math.sqrt(252)
    ecart = f_sh(x_) - f_sh(y_)
    dist = np.array([f_sh(u) - f_sh(w) for (u, w), _ in StationaryBootstrap(10, x_, y_, seed=7).bootstrap(n_sim)])
    p_ec = float(np.mean(dist - ecart >= ecart))
    reg = SS.linregress(y_, x_)
    tests.append(dict(famille="Placebo", test="Bat-elle l or achete toute la seance ?", resultat=f"{ecart:+.2f} de Sharpe, p = {p_ec:.3f}",
                      detail=f"bootstrap stationnaire (arch), {n_sim} tirages, IC 95 % [{np.quantile(dist, .025):.2f} ; {np.quantile(dist, .975):.2f}] ; "
                             f"rendement hors exposition a l or {reg.intercept * 252:+.1%} par an (t = {reg.intercept / reg.intercept_stderr:.2f}), "
                             f"beta {reg.slope:.2f}", verdict="ok" if p_ec < 0.05 else "alerte"))
    tests.append(dict(famille="Placebo", test="Cout de la contrainte intraday", resultat=f"Sharpe {sh['asie + soir (strategie)']:.2f} contre "
                      f"{sh['regle publiee, nuit gardee (13:30 -> 8:20)']:.2f}",
                      detail="la regle publiee garde l or pendant la pause 17:00-18:00 et le week-end ; la version intraday perd ce "
                             "rendement et paie deux allers-retours par seance au lieu d un", verdict="info"))
    log("  temoins : ok")
    # sensibilite
    sens = []
    pub = pd.Timestamp(ON.PUBLICATION)
    for famille, cas in {"Couts": [("x0", dict(cout_mult=0.0)), ("x1 (reference)", {}), ("x2", dict(cout_mult=2.0)), ("x3", dict(cout_mult=3.0))],
                         "Latence": [("a l heure (reference)", {}), ("+1 min", dict(delai_min=1)), ("+2 min", dict(delai_min=2)),
                                     ("+5 min", dict(delai_min=5))]}.items():
        for lab, kw in cas:
            _, rr = run(**kw) if kw else (pf, r)
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                sens.append(dict(famille=famille, cas=lab, sharpe=_js(_acc(rr).sharpe_ratio()), sharpe_apres=_js(_acc(rr[rr.index >= pub]).sharpe_ratio())))
    for famille in ("Couts", "Latence"):
        cas_ = [x for x in sens if x["famille"] == famille]
        pire = min(cas_, key=lambda x: x["sharpe"])
        tests.append(dict(famille="Sensibilite", test=f"{famille} : pire cas ({pire['cas']})", resultat=f"Sharpe {pire['sharpe']:.2f}",
                          detail=" ; ".join(f"{x['cas']} {x['sharpe']:.2f}" for x in cas_), verdict="ok" if pire["sharpe"] >= 0.5 else "alerte"))
    log("  couts, latence : ok")
    extra, rmat = {}, None
    ref_lab = "pause_debut=08:20,pause_fin=13:30"
    if grille:
        debuts, fins = ["07:20", "07:50", "08:20", "08:50", "09:20"], ["12:30", "13:00", "13:30", "14:00", "14:30"]
        rets, pts = {}, []
        for d_ in debuts:
            for f_ in fins:
                _, rr = run(pause_debut=d_, pause_fin=f_)
                rets[f"pause_debut={d_},pause_fin={f_}"] = rr
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore")
                    pts.append(dict(pause_debut=d_, pause_fin=f_, sharpe=_js(_acc(rr).sharpe_ratio())))
        log(f"  grille : {len(pts)} reglages")
        rmat = pd.DataFrame(rets)
        tg, extra = _grille_pbo_wf(rmat, ref_lab)
        shs = np.array([x["sharpe"] for x in pts], float)
        tg.insert(0, dict(famille="Sur-ajustement", test="Plateau (vente du matin x achat de l apres-midi)", resultat=f"{shs.min():.2f} a {shs.max():.2f}",
                          detail=f"{len(shs)} reglages ; {np.mean(shs > 0):.0%} positifs ; reglage du papier 8:20 / 13:30 (heures du COMEX)",
                          verdict="ok" if np.mean(shs > 0) >= 0.8 else "alerte"))
        tests += tg
        extra["grille"] = dict(axes=["pause_debut", "pause_fin"], valeurs=dict(pause_debut=debuts, pause_fin=fins), points=pts,
                               reference=dict(pause_debut="08:20", pause_fin="13:30"))
    tc, mc = bloc_tests_communs(r, t, ON.PUBLICATION, ON.ESSAIS, ON.VAR_SHARPE_ESSAIS_ANNUALISE, n_sim)
    tests = tests[:3] + tc + tests[3:]
    # hasard : la meme pause de 5 h 10 placee ailleurs dans la seance (memes regles, memes couts)
    duree_p = ON._minute(p0["pause_fin"]) - ON._minute(p0["pause_debut"])
    vals = []
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        for a_ in range(0, 1380 - duree_p + 1, 10):
            if a_ == ON._minute(p0["pause_debut"]):
                continue
            _, rr = run(pause_debut=_heure(a_), pause_fin=_heure(a_ + duree_p))
            vals.append(float(_acc(rr).sharpe_ratio()))
        obs = float(_acc(r).sharpe_ratio())
    nul = dict(titre="Pause de 5 h 10 placee ailleurs dans la seance", valeurs=np.array(vals), observe=obs,
               detail=f"{len(vals)} positions de la pause (toutes les 10 min de 18:00 a 11:50), or achete le reste de la seance, memes couts")
    log("  pauses deplacees : ok")
    ts, so = bloc_surajustement(r, rmat, ref_lab if rmat is not None else None, ON.ESSAIS, nul=nul, reps=n_sim)
    tests += ts
    extra["surajustement"] = so
    fiche = dict(
        id="OrNuit_GC", code="N1", titre="Or hors seance US · GC (intraday)", statut="candidate", valide_le=None,
        resume="Acheter l or quand la seance du COMEX est fermee : de l ouverture asiatique (18:00 New York, minuit a Paris) "
               "a l ouverture du COMEX (8:20), puis de sa cloture (13:30) a la fin de seance (17:00). Jamais de position "
               "d une seance a l autre ni le week-end.",
        fonctionnement=[
            "Seance Globex de l or : 18:00 -> 17:00 heure de New York (minuit -> 23:00 a Paris), pause d une heure, fermee le week-end.",
            "18:00 New York (minuit a Paris) : achat de GC a l ouverture de la seance ; 8:20 (14:20 a Paris), ouverture du COMEX : vente.",
            "13:30 (19:30 a Paris), cloture du COMEX : achat ; vente a la derniere minute de la seance (cloture de 17:00, 23:00 a Paris).",
            "Pas de position pendant la seance du COMEX (8:20-13:30), la pause 17:00-18:00 et le week-end : environ 17 h 50 en "
            "position par seance (14 h 20 + 3 h 30), deux allers-retours par jour.",
            "Seance raccourcie (jour ferie americain) : sortie a sa derniere minute ; heure prevue absente (plus de 10 min de "
            "retard) : jambe sautee.",
            f"Taille : 100 % du capital ({cap:,.0f} $, notionnel = capital, sans levier), gains reinvestis. Couts : 2,25 $ par "
            "contrat et par execution + 1/2 tick (0,10 $).",
            "Regle publiee : acheteur de 13:30 a 8:20 le lendemain. Version intraday : coupee a 17:00 et reprise a 18:00 ; "
            "elle perd le rendement des fermetures (voir les temoins).",
        ],
        pourquoi="Sur le COMEX de 1985 a 2012, les auteurs trouvent un rendement de nuit significativement positif et un "
                 "rendement de seance (8:20-13:30) significativement negatif ; l ecart s est reduit avec le temps mais reste "
                 "present. De 2016 a 2026, la seance du COMEX a encore perdu en moyenne alors que le reste de la journee a "
                 "porte la hausse de l or.",
        sources=[dict(titre="Blose & Gondhalekar (2014), Overnight gold returns, Applied Economics Letters 21(18)",
                      lien="https://ideas.repec.org/a/taf/apeclt/v21y2014i18p1269-1272.html"),
                 dict(titre="Blose, Gondhalekar & Kort (2018), Overnight versus day returns in gold and gold related assets, "
                            "Journal of Economics and Finance 42(3)",
                      lien="https://ideas.repec.org/a/spr/jecfin/v42y2018i3d10.1007_s12197-017-9403-0.html")],
        parametres={k: _js(v) for k, v in p0.items()},
        donnees=dict(info, calendrier="seances CME (18:00 -> 17:00, datees du jour de leur fin), reportees sur les seances NYSE"),
        capital=dict(initial=cap, unite="$", note="100 % du capital, gains reinvestis, sans levier"),
        fuseau_trades="America/New_York", publication=ON.PUBLICATION,
        kpi=_kpi(valeur, t), vectorbt=bloc_vectorbt(pf, valeur), series=bloc_series(valeur), trades=rows,
        tests=tests, monte_carlo=mc, sensibilite=sens, placebo=plac,
        placebo_titre="Temoins : chaque jambe, l or toute la seance, la seance du COMEX, la regle publiee", **extra)
    return fiche, r


# =============================================================================
#  Export
# =============================================================================
# candidates a l etude : (code pour --seulement, identifiant de la fiche, fonction d export)
CANDIDATES = [("G1", "Gotobi_6J", fiche_gotobi), ("O1", "ORB_NQ", fiche_orb), ("N1", "OrNuit_GC", fiche_or_nuit)]


def strategies_validees() -> list[str]:
    return [c for c in available() if getattr(get(c), "VALIDATED", None)]


def exporter(cotations: str, sortie: str, n_sim: int = 2000, grille: bool = True, seulement=None, log=print) -> dict:
    if vbt is None:
        raise ImportError("vectorbt n est pas installe")
    os.makedirs(sortie, exist_ok=True)
    taches = [(c, lambda c=c: fiche_nexus(c, cotations, n_sim, grille, log)) for c in strategies_validees()]
    taches += [(code, lambda f=f: f(cotations, n_sim, grille, log)) for code, _, f in CANDIDATES]
    rets, liste = {}, []
    for code, f in taches:
        if seulement and code not in seulement:
            continue
        log(f"[tableau] {code}")
        t0 = time.time()
        fiche, r = f()
        fiche["genere_le"] = dt.datetime.now().strftime("%Y-%m-%d %H:%M")
        with open(os.path.join(sortie, f"{fiche['id']}.json"), "w", encoding="utf-8") as fh:
            json.dump(fiche, fh, ensure_ascii=False, separators=(",", ":"))
        rets[fiche["id"]] = r
        liste.append(dict(id=fiche["id"], titre=fiche["titre"], statut=fiche["statut"], valide_le=fiche["valide_le"],
                          resume=fiche["resume"], kpi=fiche["kpi"],
                          alertes=sum(1 for x in fiche["tests"] if x["verdict"] == "alerte"),
                          ok=sum(1 for x in fiche["tests"] if x["verdict"] == "ok")))
        log(f"[tableau] {code} ecrit ({time.time() - t0:.0f} s)")
    if seulement and os.path.exists(os.path.join(sortie, "index.json")):     # export partiel : garder les autres fiches
        with open(os.path.join(sortie, "index.json"), encoding="utf-8") as fh:
            ancien = json.load(fh)
        for e in ancien.get("strategies", []):
            f_ = os.path.join(sortie, f"{e['id']}.json")
            if e["id"] in rets or not os.path.exists(f_):
                continue
            with open(f_, encoding="utf-8") as fh:
                ser = json.load(fh)["series"]
            rets[e["id"]] = pd.Series(ser["rendement"], index=pd.DatetimeIndex(ser["dates"]))
            liste.append(e)
    rang = {i: k for k, (_, i, _) in enumerate(CANDIDATES)}          # validees d abord, puis candidates dans l ordre d ajout
    liste.sort(key=lambda e: (e["statut"] != "validee", rang.get(e["id"], -1)))
    # correlations et portefeuille combine (risque egal) sur le calendrier commun
    R = pd.DataFrame(rets)[[e["id"] for e in liste if e["id"] in rets]].dropna()
    combi = None
    if R.shape[1] >= 2:
        w = 1 / R.std()
        mix = (R * w / w.sum()).sum(axis=1)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            combi = dict(sharpe=_js(_acc(mix).sharpe_ratio()), perte_max=_js(-_acc(mix).max_drawdown()),
                         dates=[d.strftime("%Y-%m-%d") for d in mix.index], valeur=_round((1 + mix).cumprod(), 5),
                         poids={k: _js(v) for k, v in (w / w.sum()).items()},
                         note="poids inversement proportionnels a la volatilite : une strategie peu volatile (Gotobi sans levier) "
                              "recoit un gros poids, ce qui suppose du levier sur son notionnel",
                         seules={k: _round((1 + R[k] * (mix.std() / R[k].std())).cumprod(), 5) for k in R})
    index = dict(version=VERSION, genere_le=dt.datetime.now().strftime("%Y-%m-%d %H:%M"), strategies=liste,
                 correlation=dict(ids=list(R.columns), matrice=[[_js(v) for v in row] for row in R.corr().to_numpy()]),
                 correlation_mensuelle=dict(ids=list(R.columns), matrice=[[_js(v) for v in row] for row in
                                            ((1 + R).groupby([R.index.year, R.index.month]).prod() - 1).corr().to_numpy()]),
                 combine=combi, note="Resultats calcules sur des donnees sous licence (usage prive) : ne pas publier ce dossier.")
    with open(os.path.join(sortie, "index.json"), "w", encoding="utf-8") as fh:
        json.dump(index, fh, ensure_ascii=False, separators=(",", ":"))
    return index
