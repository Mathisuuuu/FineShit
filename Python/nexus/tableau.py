"""Export du tableau de bord (Dashboard/, serveur Node.js) : un fichier JSON par strategie, TOUTES les strategies.

Strategies exportees, au meme format et avec les memes tests : celles du registre marquees VALIDATED (S1_NoiseAreaNQ),
les candidates etudiees dans les sessions cloud (Gotobi 6J, ORB NQ, or la nuit, fiche 15 LETF NQ / ES), et toutes les
strategies du runner local (nexus/perso/runner.py), rejouees dans vectorbt par nexus/tableau_runner.py. Les candidates
ont en plus leurs tests propres (grille de reglages, placebos, latence...). Tous les chiffres viennent de vectorbt (portefeuilles, statistiques, trades,
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
from . import letf as LT
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
VERSION = 2
# Nombre CUMULE d essais du programme de recherche (sessions cloud + locales, voir la memoire « methode-strategie-papiers »)
# et variance des Sharpe annualises des essais : le Sharpe deflate de TOUTES les strategies du tableau est calcule avec ces
# deux valeurs (memes tests pour toutes). La variance est remplacee a l export par celle des strategies exportees.
ESSAIS_PROGRAMME = 434        # 431e etf_nuit, 432e tiers_vendredi, 433e crypto_retour (2026-10-22), 434e ouverture_europe (2026-10-24), tous rejetes
VAR_SHARPE_PROGRAMME = 0.5


# =============================================================================
#  Mise en forme JSON
# =============================================================================
def _js(x):
    if x is None or x is pd.NaT or x is pd.NA:
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


def unites_mc(t: pd.DataFrame, r: pd.Series, max_trades: int = 4000) -> tuple[pd.DataFrame, str]:
    """Unites du test des signes et du Monte Carlo : les trades ; regroupes par jour au-dela de max_trades trades
    (memoire) ; les rendements journaliers s il n y a pas de trades (portefeuille permanent)."""
    if t is None or len(t) < 20:
        return pd.DataFrame({"brut": r.to_numpy(), "net": r.to_numpy()}), "rendements journaliers (pas de trades)"
    if len(t) > max_trades:
        j = pd.DatetimeIndex(t["sortie"]).normalize()
        g = t[["brut", "net"]].groupby(j).sum()
        return g, f"trades regroupes par jour ({len(t)} trades, {len(g)} jours)"
    return t, f"{len(t)} trades"


def bloc_tests_communs(r: pd.Series, t: pd.DataFrame, publication: str, essais: int, var_sharpe_ann: float,
                       n_sim: int = 2000, seed: int = 7, libelle: str | None = None) -> tuple[list, dict]:
    """Batterie commune : Sharpe par periode, IC bootstrap BCa, PSR, Sharpe deflate, test des signes, Monte Carlo.
    libelle : nom de la coupure (par defaut « publication ») ; les strategies sans date de publication sont coupees au
    01/01/2021, comme les deux periodes de la methode de recherche."""
    nom_coupure = libelle or f"publication {publication}"
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
    add("Performance", "Sharpe sur tout l historique (vectorbt)", f"{sh:.2f}", f"{len(r)} seances, {r.index[0]:%Y-%m-%d} -> {r.index[-1]:%Y-%m-%d}",
        "ok" if sh >= 1 else ("alerte" if sh < 0.5 else "info"))
    if len(avant) >= 20:
        add("Performance", "Sharpe avant / apres la coupure", f"{sh_av:.2f} / {sh_ap:.2f}", f"{nom_coupure}, {len(apres)} seances apres",
            "ok" if sh_ap >= 0.5 else "alerte")
    else:
        add("Performance", "Sharpe apres la coupure", f"{sh_ap:.2f}",
            f"{nom_coupure}, avant les donnees : tout l historique ({len(apres)} seances) est posterieur", "ok" if sh_ap >= 0.5 else "alerte")
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
        add("Robustesse statistique", "IC 95 % du Sharpe apres la coupure", f"[{bp.confidence_interval.low:.2f} ; {bp.confidence_interval.high:.2f}]",
            f"{len(apres)} seances", "ok" if bp.confidence_interval.low > 0 else "alerte")
    psr = V.probabilistic_sharpe(x.mean() / x.std(ddof=1), 0.0, len(x), SS.skew(x), SS.kurtosis(x, fisher=False))
    add("Robustesse statistique", "Probabilite que le Sharpe vrai soit > 0", f"{psr:.1%}", "Sharpe probabiliste (asymetrie et queues comprises)",
        "ok" if psr >= 0.95 else "alerte")
    if len(apres) > 60:
        y = apres.to_numpy()
        p0 = V.probabilistic_sharpe(y.mean() / y.std(ddof=1), 0.0, len(y), SS.skew(y), SS.kurtosis(y, fisher=False))
        p5 = V.probabilistic_sharpe(y.mean() / y.std(ddof=1), 0.5 / math.sqrt(252), len(y), SS.skew(y), SS.kurtosis(y, fisher=False))
        add("Robustesse statistique", "Apres la coupure : P(Sharpe > 0) / P(Sharpe > 0,5)", f"{p0:.1%} / {p5:.1%}", nom_coupure, "ok" if p0 >= 0.9 else "alerte")
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        dsr = acc.deflated_sharpe_ratio(var_sharpe=var_sharpe_ann, nb_trials=int(essais))   # variance des Sharpe ANNUALISES
    dsr_n, sr0 = V.deflated_sharpe(x, int(essais), var_sharpe_ann / 252.0)
    add("Robustesse statistique", "Sharpe deflate (vectorbt, essais comptes)", f"{dsr:.1%}",
        f"{essais} essais, variance des Sharpe annualises {var_sharpe_ann:.2f} ; Sharpe a battre {sr0 * math.sqrt(252):.2f} "
        f"(controle nexus.validation : {dsr_n:.1%})", "ok" if dsr >= 0.95 else "alerte")

    u, quoi = unites_mc(t, r)
    brut = u["brut"].to_numpy()
    pt = SS.permutation_test((brut,), np.mean, permutation_type="samples", n_resamples=max(n_sim * 5, 10000),
                             alternative="greater", random_state=seed)
    add("Robustesse statistique", "Test des signes (permutation scipy)", f"p = {pt.pvalue:.4f}",
        f"{quoi}, sens tires au hasard ; gain brut moyen {brut.mean() * 1e4:.2f} bp", "ok" if pt.pvalue < 0.05 else "alerte")

    rt = u["net"].to_numpy()
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        obs = -pd.Series(rt).vbt.returns(freq="1D").max_drawdown()
        dd_perm = -_dd_paths(rt, n_sim, rng, False).vbt.returns(freq="1D").max_drawdown().to_numpy()
        boot = _dd_paths(rt, n_sim, rng, True)
        dd_boot = -boot.vbt.returns(freq="1D").max_drawdown().to_numpy()
        fin_boot = (1 + boot).prod().to_numpy() - 1
    q = lambda a, p: float(np.quantile(a, p))
    add("Monte Carlo", f"Perte max, ordre melange ({quoi})", f"mediane {np.median(dd_perm):.1%}",
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
        "Sharpe " + " ; ".join(f"{b['debut'][:7]} -> {b['fin'][:7]} : " + ("–" if b["sharpe"] is None else f"{b['sharpe']:.2f}") for b in blocs),
        "ok" if (v > 0).all() else "alerte")
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


def _kpi_sans_trades(valeur: pd.Series) -> dict:
    vide = pd.DataFrame({"entree": pd.to_datetime([]), "sortie": pd.to_datetime([]), "PnL": [], "net_notionnel": [], "net": []})
    return _kpi(valeur, vide)


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
    # prop firms : le micro MJY (1 250 000 yens, tick 0,000001, 0,60 $ par cote) double le tick rapporte au notionnel
    from . import prop_combinaisons as PC
    px_ = 2.25 / (m["frais"] * 12_500_000)
    mj = m.assign(frais=0.6 / (px_ * 1_250_000), glissement=0.5 * 0.000001 / px_)
    x_ = PC.mesures(GT.valeur_journaliere(GT.portefeuille(mj), cal).pct_change().fillna(0.0), ESSAIS_PROGRAMME)
    tests.append(dict(famille="Prop firms", test="Micro MJY au lieu de 6J",
                      resultat=f"Sharpe {x_['sharpe']:.2f} [{x_['ic_bas']:.2f} ; {x_['ic_haut']:.2f}], moities {x_['sharpe_p1']:.2f} / {x_['sharpe_p2']:.2f}",
                      detail="couts du micro (tick deux fois plus gros rapporte au notionnel, commission 0,60 $ pour 12 fois moins de "
                             "notionnel) ; " + ("toujours fiable" if x_["fiable"] else "PLUS fiable : en prop firm, trader le contrat 6J "
                             "(environ 84 000 $ de notionnel, environ 500 $ d ecart-type par jour, compatible avec un compte de 50 000 $)"),
                      verdict="ok" if x_["fiable"] else "alerte"))
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
    # prop firms : le micro MNQ (multiplicateur 2, 0,60 $ par cote) : meme tick rapporte au notionnel, commission plus lourde
    from . import prop_combinaisons as PC
    px_ = OR.COMMISSION / (m["frais"] * 20.0)
    x_ = PC.mesures(OR.valeur_journaliere(OR.portefeuille(m.assign(frais=0.6 / (px_ * 2.0))), cal).pct_change().fillna(0.0), ESSAIS_PROGRAMME)
    tests.append(dict(famille="Prop firms", test="Micro MNQ au lieu de NQ",
                      resultat=f"Sharpe {x_['sharpe']:.2f} [{x_['ic_bas']:.2f} ; {x_['ic_haut']:.2f}], moities {x_['sharpe_p1']:.2f} / {x_['sharpe_p2']:.2f}",
                      detail="commission de 0,60 $ par cote pour un dixieme du notionnel de NQ ; " + ("toujours fiable" if x_["fiable"] else "PLUS fiable"),
                      verdict="ok" if x_["fiable"] else "alerte"))
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
#  Candidate : or la nuit, regle publiee (vectorbt direct)
# =============================================================================
def _heure(minute: int) -> str:
    h, mi = divmod((ON.OUVERTURE + int(minute)) % 1440, 60)
    return f"{h:02d}:{mi:02d}"


def _prop_or_nuit(m, cotations, cal, pf, r, sens, log) -> list:
    """Prop firms : versions conformes (intraday, sans week-end, CFD avec financement), variantes intraday tirees des
    articles, challenges simules sur l historique reel (micros MGC). Ajoute les Sharpe a `sens`, renvoie les tests."""
    from . import prop as PR
    mg, _ = ON.charger(cotations, "MGC")
    toutes = pd.DatetimeIndex(pd.unique(m["seance"].to_numpy()))
    hors_fomc = toutes.difference(ON.FOMC)
    base = [("18:00", "08:20", 1), ("13:30", "17:00", 1, hors_fomc)]
    faibles, lendemains = ON.seances_comex_faibles(m)
    pub = pd.Timestamp(ON.PUBLICATION)

    def sh(mm, **kw):
        if not kw and mm is m:
            rr = r
        else:
            rr = ON.valeur_journaliere(ON.portefeuille(mm, compact=True, **kw), cal).pct_change().fillna(0.0)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            return float(_acc(rr).sharpe_ratio()), float(_acc(rr[rr.index >= pub]).sharpe_ratio())

    res = {}
    for famille, cas in {
        "Prop firms": [("regle publiee, GC", m, {}), ("regle publiee, micro MGC", mg, {}),
                       ("sans week-end, MGC", mg, dict(garder_weekend=False, cloture="16:10")),
                       ("CFD 5 $ / nuit", m, dict(swap_nuit=5.0)), ("CFD 20 $ / nuit", m, dict(swap_nuit=20.0)),
                       ("CFD 45 $ / nuit", m, dict(swap_nuit=45.0)),
                       ("intraday 16:10, GC", m, dict(fenetres=base, cloture="16:10")),
                       ("intraday 16:10, MGC", mg, dict(fenetres=base, cloture="16:10"))],
        "Articles (intraday)": [
            ("apres une seance COMEX faible", m, dict(fenetres=[("18:00", "08:20", 1, lendemains),
                                                                ("13:30", "17:00", 1, faibles.intersection(hors_fomc))], cloture="16:10")),
            ("Asie 18:00 -> 3:00", m, dict(fenetres=[("18:00", "03:00", 1)])),
            ("Europe 3:00 -> 8:20", m, dict(fenetres=[("03:00", "08:20", 1)])),
            ("vente 8:20 -> 11:00", m, dict(fenetres=[("08:20", "11:00", -1)])),
            ("achat 11:00 -> 16:10", m, dict(fenetres=[("11:00", "17:00", 1)], cloture="16:10")),
            ("achat 2:00 -> 4:00", m, dict(fenetres=[("02:00", "04:00", 1)]))]}.items():
        for lab, mm, kw in cas:
            a, b = sh(mm, **kw)
            res[lab] = a
            sens.append(dict(famille=famille, cas=lab, sharpe=_js(a), sharpe_apres=_js(b)))
    tests = [
        dict(famille="Prop firms", test="Version intraday a plat a 16:10 (Topstep, MyFundedFutures, FundedNext)",
             resultat=f"Sharpe {res['intraday 16:10, GC']:.2f} (GC) / {res['intraday 16:10, MGC']:.2f} (MGC)",
             detail="achat 18:00 -> vente 8:20, achat 13:30 -> vente 16:10 (pas de jambe du soir les jours de FOMC), rien le "
                    "week-end : perd le rendement des fermetures et paie deux allers-retours par jour ; les micros coutent "
                    "environ 3 fois plus cher par once", verdict="ok" if res["intraday 16:10, MGC"] >= 0.5 else "alerte"),
        dict(famille="Prop firms", test="Sans week-end (nuit permise, week-end interdit : The5ers Futures)",
             resultat=f"Sharpe {res['sans week-end, MGC']:.2f} (MGC)", detail="vendu le vendredi a 16:10, rachete le dimanche a 18:00, vendu le lundi a 8:20",
             verdict="ok" if res["sans week-end, MGC"] >= 0.5 else "alerte"),
        dict(famille="Prop firms", test="CFD XAUUSD (FTMO Swing, The5ers, FundedNext, E8) : financement de nuit",
             resultat=f"Sharpe {res['CFD 5 $ / nuit']:.2f} / {res['CFD 20 $ / nuit']:.2f} / {res['CFD 45 $ / nuit']:.2f}",
             detail="5 / 20 / 45 $ par 100 onces et par nuit (x 3 du vendredi au lundi), fourchette relevee chez les courtiers ; "
                    "le financement de l achat d or est negatif partout", verdict="ok" if res["CFD 20 $ / nuit"] >= 0.5 else "alerte"),
    ]
    art = [x for x in sens if x["famille"] == "Articles (intraday)"]
    tests.append(dict(famille="Prop firms", test="Variantes intraday tirees des articles", resultat=f"meilleure : Sharpe {max(x['sharpe'] for x in art):.2f}",
                      detail=" ; ".join(f"{x['cas']} {x['sharpe']:.2f}" for x in art)
                             + " (Boyarchenko, Larsen & Whelan 2023 ; Bondarenko & Muravyev 2023 ; Berkman et al. 2012 ; "
                               "Krohn, Mueller & Whelan 2024 ; Donati & Jung 2019) ; aucune ne rend la version intraday viable",
                      verdict="info"))
    log("  prop firms (versions conformes, articles) : ok")
    brut = mg["brut"].to_numpy(float)
    for cle, kw, notionnels in (("elite_diamond_100k", {}, (50_000, 100_000, 150_000)),
                                ("topstep_50k", dict(fenetres=base, cloture="16:10"), (25_000, 50_000, 75_000))):
        regles = PR.CHALLENGES[cle]
        lignes = []
        for notio in notionnels:
            nb = np.maximum(1, np.round(notio / (ON.SPEC_MGC["multiplicateur"] * brut)))
            v = ON.valeur(ON.portefeuille(mg, contrats=nb, capital=regles["taille"], **kw))
            x = PR.resume(PR.simuler(v, mg["seance"].to_numpy(), regles))
            lignes.append(f"{notio:,.0f} $ (~{np.mean(nb):.1f} MGC) : {x['reussite']:.0%} reussis, {x['echec']:.0%} perdus"
                          f" (en {x['jours_median_reussite']:.0f} seances en mediane)")
        hasard = regles["perte_max"] / (regles["perte_max"] + regles["objectif"])
        tests.append(dict(famille="Prop firms", test=f"Challenge simule : {regles['nom']}",
                          resultat=lignes[0].split(" : ")[1].split(" (")[0],
                          detail=f"{'regle publiee' if not kw else 'version intraday 16:10'}, un depart a chaque seance 2016-2026, "
                                 f"chemin minute reel ; notionnel vise " + " ; ".join(lignes)
                                 + f". Repere : sans avantage ni frais, avec une perte max fixe, on reussirait environ {hasard:.0%}",
                          verdict="info"))
    log("  challenges simules : ok")
    return tests


def fiche_or_nuit(cotations: str, n_sim: int, grille: bool, log=print, variante: str | None = None) -> tuple[dict, pd.Series]:
    """variante="conforme" : la version intraday (achat 18:00 -> 8:20, achat 13:30 -> derniere minute de la seance),
    candidate N2 du lot « creneaux vides » (nexus/perso/creneaux.py, H10) ; memes tests que la regle publiee."""
    from arch.bootstrap import StationaryBootstrap
    conforme = variante == "conforme"
    P = dict(jambes="asie,soir") if conforme else {}
    m, info = ON.charger(cotations, "MGC" if conforme else "GC")      # compte prop firm : le micro (un GC = environ 340 000 $)
    p0 = {**ON.DEFAULTS, **P}
    cap = p0["capital"]
    t0 = time.time()
    pf = ON.portefeuille(m, **P)
    log(f"  vectorbt : {len(pf.trades.records_readable)} trades ({time.time() - t0:.0f} s)")
    seance = pd.DatetimeIndex(m["seance"].to_numpy())
    cal = calendrier(seance[0], seance[-1])

    def run(**kw):
        p_ = ON.portefeuille(m, compact=True, **{**P, **kw})      # memes trades et memes valeurs de fin de seance, plus rapide
        return p_, ON.valeur_journaliere(p_, cal).pct_change().fillna(0.0)

    valeur = ON.valeur_journaliere(pf, cal)
    r = valeur.pct_change().fillna(0.0)
    rows, t = bloc_trades(pf, "UTC", "America/New_York", ON.valeur(pf))
    tests = [dict(famille="Comptabilite", test="Comptabilite vectorbt (heures, week-end, taille)", resultat="tests unitaires",
                  detail="tests/test_or_nuit.py : achat 13:30, vente 8:20 a la seance suivante (lundi apres un vendredi), 100 % du "
                         "capital reinvesti, version intraday et seances raccourcies, mode compact identique, rolls", verdict="ok")]
    cut = m.index[int(len(m) * 0.6)]
    m2 = m.copy()
    m2.loc[m2.index > cut, ["open", "close"]] *= 1.25
    a = pf.trades.records_readable
    b = ON.portefeuille(m2, **P).trades.records_readable
    a, b = a[a["Exit Timestamp"] < cut].reset_index(drop=True), b[b["Exit Timestamp"] < cut].reset_index(drop=True)
    ok = len(a) == len(b) and np.allclose(a["PnL"], b["PnL"]) and (a["Entry Timestamp"] == b["Entry Timestamp"]).all()
    tests.append(dict(famille="Comptabilite", test="Biais d anticipation (prix futurs x 1,25)", resultat="aucun" if ok else "PROBLEME",
                      detail=f"{len(a)} trades avant le {cut:%d/%m/%Y} inchanges", verdict="ok" if ok else "alerte"))
    tr = pf.trades.records_readable
    loc = lambda c: pd.DatetimeIndex(tr[c]).tz_localize("UTC").tz_convert(ON.NY).tz_localize(None)
    he, hs = loc("Entry Timestamp"), loc("Exit Timestamp")
    mn_e, mn_s = he.hour * 60 + he.minute, hs.hour * 60 + hs.minute
    duree = (hs - he).total_seconds() / 3600
    if conforme:
        ok_e = np.mean(((mn_e >= 1080) & (mn_e <= 1090)) | ((mn_e >= 810) & (mn_e <= 820)))
        ok_s = np.mean(((mn_s >= 500) & (mn_s <= 510)) | ((mn_s >= 1000) & (mn_s < 1020)))
        tests.append(dict(famille="Comptabilite", test="Heures d execution (New York)",
                          resultat=f"{ok_e:.1%} des achats a 18:00 ou 13:30, {ok_s:.1%} des ventes a 8:20 ou en fin de seance",
                          detail=f"{len(tr)} trades (au plus 10 min de retard) ; fin de seance = derniere minute avant 17:00 ; "
                                 f"duree mediane {np.median(duree):.1f} h, max {duree.max():.1f} h (jamais a travers la pause de 17:00)",
                          verdict="ok" if ok_e > 0.99 and ok_s > 0.99 and duree.max() < 23 else "alerte"))
    else:
        ok_e, ok_s = np.mean((mn_e >= 810) & (mn_e <= 820)), np.mean((mn_s >= 500) & (mn_s <= 510))
        tests.append(dict(famille="Comptabilite", test="Heures d execution (New York)", resultat=f"{ok_e:.1%} des achats a 13:30, {ok_s:.1%} des ventes a 8:20",
                          detail=f"{len(tr)} trades (au plus 10 min de retard) ; les autres ventes : derniere minute d une seance sans 8:20 ; "
                                 f"duree mediane {np.median(duree):.1f} h, max {duree.max():.0f} h (week-end prolonge)",
                          verdict="ok" if ok_e > 0.99 and ok_s > 0.99 else "alerte"))
    # temoins : l or garde en permanence, la seance du COMEX seule, la version intraday
    plac, temoins = [], {}
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        lab_s = "version intraday (18:00 -> 8:20 + 13:30 -> 17:00)" if conforme else "nuit 13:30 -> 8:20 (strategie)"
        for lab, kw in [("nuit 13:30 -> 8:20 (strategie)", dict(jambes="nuit")), ("or garde en permanence", dict(jambes="permanent")),
                        ("seance du COMEX seule (8:20 -> 13:30)", dict(jambes="pause")),
                        ("version intraday (18:00 -> 8:20 + 13:30 -> 17:00)", dict(jambes="asie,soir")),
                        ("or achete toute la seance, intraday (18:00 -> 17:00)", dict(jambes="tout"))]:
            _, rr = (pf, r) if lab == lab_s else run(**kw)
            temoins[lab] = rr
            plac.append(dict(cas=lab, sharpe=_js(_acc(rr).sharpe_ratio())))
    sh = {x["cas"]: x["sharpe"] for x in plac}
    tests.append(dict(famille="Placebo", test="Temoin : la seance du COMEX seule", resultat=f"Sharpe {sh['seance du COMEX seule (8:20 -> 13:30)']:.2f}",
                      detail="l idee du papier : l or ne gagne rien (ou perd) pendant la seance de jour de New York ; "
                             + " ; ".join(f"{x['cas']} {x['sharpe']:.2f}" for x in plac),
                      verdict="ok" if sh["seance du COMEX seule (8:20 -> 13:30)"] < 0 else "alerte"))
    ref_or = "or achete toute la seance, intraday (18:00 -> 17:00)" if conforme else "or garde en permanence"
    x_, y_ = r.to_numpy(), temoins[ref_or].to_numpy()
    f_sh = lambda z: z.mean() / z.std(ddof=1) * math.sqrt(252)
    ecart = f_sh(x_) - f_sh(y_)
    dist = np.array([f_sh(u) - f_sh(w) for (u, w), _ in StationaryBootstrap(10, x_, y_, seed=7).bootstrap(n_sim)])
    p_ec = float(np.mean(dist - ecart >= ecart))
    reg = SS.linregress(y_, x_)
    tests.append(dict(famille="Placebo", test="Bat-elle l or garde toute la seance ?" if conforme else "Bat-elle l or garde en permanence ?",
                      resultat=f"{ecart:+.2f} de Sharpe, p = {p_ec:.3f}",
                      detail=f"bootstrap stationnaire (arch), {n_sim} tirages, IC 95 % [{np.quantile(dist, .025):.2f} ; {np.quantile(dist, .975):.2f}] ; "
                             f"rendement hors exposition a l or {reg.intercept * 252:+.1%} par an (t = {reg.intercept / reg.intercept_stderr:.2f}), "
                             f"beta {reg.slope:.2f}", verdict="ok" if p_ec < 0.05 else "alerte"))
    tests.append(dict(famille="Placebo", test="Regle publiee (gardee a travers la pause et le week-end)" if conforme else
                      "Version intraday (fermee a 17:00, reprise a 18:00)",
                      resultat=f"Sharpe {sh['version intraday (18:00 -> 8:20 + 13:30 -> 17:00)']:.2f} contre {sh['nuit 13:30 -> 8:20 (strategie)']:.2f}",
                      detail="sans la pause 17:00-18:00 ni le week-end, et avec deux allers-retours par seance au lieu d un : "
                             "une grande partie du rendement disparait", verdict="info"))
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
    if not conforme:
        tests += _prop_or_nuit(m, cotations, cal, pf, r, sens, log)
    else:
        from . import prop_combinaisons as PC
        mg, _ = ON.charger(cotations, "GC")
        rm = ON.valeur_journaliere(ON.portefeuille(mg, compact=True, **P), cal).pct_change().fillna(0.0)
        x = PC.mesures(rm, ESSAIS_PROGRAMME)
        tests.append(dict(famille="Prop firms", test="Avec le contrat GC au lieu du micro MGC",
                          resultat=f"Sharpe {x['sharpe']:.2f} [{x['ic_bas']:.2f} ; {x['ic_haut']:.2f}], moities {x['sharpe_p1']:.2f} / {x['sharpe_p2']:.2f}",
                          detail="fiche calculee avec le micro MGC (10 onces, 0,85 $ par cote) : a 1 % de risque par jour, un compte de 50 000 "
                                 "a 150 000 $ tient 2 a 6 MGC, jamais un GC (environ 340 000 $ de notionnel). Avec GC, couts environ 3 fois "
                                 "plus faibles par once : " + ("fiable" if x["fiable"] else "pas fiable non plus"),
                          verdict="info"))
        log("  contrat GC : ok")
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
    vals = np.array(vals)
    vals = vals[np.isfinite(vals)]
    nul = dict(titre="Pause de 5 h 10 placee ailleurs dans la journee", valeurs=vals, observe=obs,
               detail=f"{len(vals)} positions de la pause (toutes les 10 min, de 18:00 a 11:40), or garde le reste du temps "
                      "(pause 17:00-18:00 et week-end compris), memes couts")
    log("  pauses deplacees : ok")
    ts, so = bloc_surajustement(r, rmat, ref_lab if rmat is not None else None, ON.ESSAIS, nul=nul, reps=n_sim)
    tests += ts
    extra["surajustement"] = so
    fiche = dict(
        id="OrNuit_GC", code="N1", titre="Or la nuit · GC", statut="candidate", valide_le=None,
        resume="Acheter l or a la cloture du COMEX (13:30 a New York, 19:30 a Paris) et le revendre a son ouverture "
               "suivante (8:20, 14:20 a Paris) : garde la nuit et le week-end, jamais pendant la seance de New York.",
        fonctionnement=[
            "13:30 New York (19:30 a Paris), cloture de la seance du COMEX : achat de GC.",
            "8:20 New York (14:20 a Paris) a la seance suivante, ouverture du COMEX : vente. Le vendredi, la position est "
            "gardee tout le week-end et vendue le lundi a 8:20.",
            "En position environ 18 h 50 par jour (pause de 17:00-18:00 comprise), environ 2,5 jours le week-end ; jamais "
            "pendant la seance du COMEX (8:20-13:30). Un aller-retour par jour.",
            "Pas de barre a 13:30 (seance raccourcie, plus de 10 min de retard) : pas d achat ce jour-la ; seance suivante "
            "sans 8:20 : vente a sa derniere minute.",
            f"Taille : 100 % du capital ({cap:,.0f} $, notionnel = capital, sans levier), gains reinvestis. Couts : 2,25 $ par "
            "contrat et par execution + 1/2 tick (0,10 $).",
            "Regle des auteurs appliquee telle quelle (la toute premiere version testee, G1a). La version intraday (fermee a "
            "17:00, reprise a 18:00) est dans les temoins.",
        ],
        pourquoi="Sur le COMEX de 1985 a 2012, les auteurs trouvent un rendement de nuit significativement positif et un "
                 "rendement de seance (8:20-13:30) significativement negatif ; l ecart s est reduit avec le temps mais reste "
                 "present. De 2016 a 2026, la seance du COMEX a encore perdu en moyenne alors que le reste du temps a porte "
                 "la hausse de l or.",
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
        placebo_titre="Temoins : l or garde en permanence, la seance du COMEX, la version intraday", **extra)
    if conforme:
        fiche.update(
            id="OrNuit_GC_conforme", code="N2", statut="testee",
            titre="Or la nuit, conforme a la seance · MGC",
            resume="Or la nuit sans traverser la pause de 17:00 ni le week-end, en micro MGC (taille d un compte prop firm) : achat a "
                   "la reouverture de 18:00, vente a 8:20 (ouverture du COMEX) ; nouvel achat a 13:30, vente a 16:59. Avec les couts "
                   "du micro, elle n est pas fiable (avec le contrat GC, elle l etait de justesse).",
            fonctionnement=[
                "18:00 New York (reouverture du CME, 0:00 a Paris) : achat de MGC (micro or) ; 8:20 (ouverture du COMEX) : vente.",
                "13:30 (cloture du COMEX) : achat ; derniere minute de la seance (16:59) : vente. Rien pendant la pause 17:00-18:00 "
                "ni le week-end : la position est toujours soldee dans la seance CME (regle des prop firms).",
                "Deux allers-retours par seance. Pas de barre a l heure prevue (plus de 10 min de retard) : pas de trade.",
                f"Taille : 100 % du capital ({cap:,.0f} $, notionnel = capital, sans levier), gains reinvestis. Couts du micro MGC : "
                "0,85 $ par contrat et par execution + 1/2 tick (0,10 $), environ 3 fois plus par once qu avec GC.",
                "Regle deja codee dans nexus/or_nuit.py (jambes=\"asie,soir\"), temoin de la candidate N1 ; mesuree avec la methode "
                "le 2026-10-19 (nexus/perso/creneaux.py, H10) : Sharpe 0,65 [0,06 ; 1,22], moities 0,34 / 0,88, Sharpe deflate "
                "0,19 pour 409 essais, t 2,1 : REJETEE par la methode, fiable au sens du tableau de bord. Pas un test a l aveugle "
                "(Sharpe deja vu par la session cloud).",
                "Avec le contrat GC (environ 340 000 $ de notionnel, trop gros pour un compte prop firm a 1 % de risque par jour), "
                "elle etait fiable de justesse (0,65) ; avec le micro MGC, Sharpe 0,34 [-0,31 ; 0,94], premiere moitie -0,09.",
            ],
            pourquoi="Version prop firm de la candidate N1 (Blose & Gondhalekar 2014 : l or gagne hors de la seance du COMEX et perd "
                     "pendant). Elle tient l or la nuit (18:00-8:20), les heures que les autres strategies fiables couvrent le moins. "
                     "La pause 17:00-18:00 et le week-end, qu elle abandonne, portaient une bonne part du rendement de N1.",
            placebo_titre="Temoins : la regle publiee, l or garde toute la seance, la seance du COMEX")
        fiche["parametres"] = {k: _js(v) for k, v in p0.items()}
    return fiche, r


# =============================================================================
#  Candidate : fiche 15, rebalancement des ETF a levier sur NQ / ES (vectorbt direct)
# =============================================================================
def fiche_letf(cotations: str, n_sim: int, grille: bool, log=print) -> tuple[dict, pd.Series]:
    import copy
    import itertools
    gr, info = LT.charger(cotations)
    gx = LT.gex()
    bases = {}

    def base_de(kw):
        p = {**LT.DEFAULTS, **kw}
        cle = tuple(str(p[k]) for k in LT.CLES_BASE)
        if cle not in bases:
            bases[cle] = LT.caracteristiques(gr, p, gx)
        return bases[cle]

    def run(**kw):
        p_ = LT.portefeuille(gr, gex_s=gx, base=base_de(kw), **kw)
        return p_, LT.valeur_journaliere(p_, cal).pct_change().fillna(0.0)

    t0 = time.time()
    pf = LT.portefeuille(gr, gex_s=gx, base=base_de({}))
    panel = pf.nexus_panel
    log(f"  vectorbt : {len(pf.trades.records_readable)} trades ({time.time() - t0:.0f} s)")
    cap = LT.DEFAULTS["capital"]
    jours = pd.DatetimeIndex(panel["date"].unique())
    cal = calendrier(jours[0], jours[-1])
    valeur = LT.valeur_journaliere(pf, cal)
    r = valeur.pct_change().fillna(0.0)
    rows, t = bloc_trades(pf, None, "America/New_York", LT.valeur(pf))
    for row, actif, taille in zip(rows, t["Column"], t["Size"]):
        row["actif"] = actif
        row["quantite"] = int(round(taille / LT.SPEC[actif]["multiplicateur"]))       # en contrats (vectorbt : contrats x $/point)
    pris = panel[panel["retenu"]]
    tests = []
    tr = pf.trades.records_readable
    entiers = np.allclose(tr["Size"] / tr["Column"].map(lambda s: LT.SPEC[s]["multiplicateur"]),
                          (tr["Size"] / tr["Column"].map(lambda s: LT.SPEC[s]["multiplicateur"])).round())
    h_ent = pd.DatetimeIndex(tr["Entry Timestamp"]).strftime("%H:%M").value_counts()
    tests.append(dict(famille="Comptabilite", test="Executions vectorbt (contrats entiers, heures, une position par jour)",
                      resultat="conforme" if entiers and pris["date"].is_unique else "PROBLEME",
                      detail=f"{len(tr)} trades ; entrees {', '.join(f'{k} x{v}' for k, v in h_ent.items())} (barre datee a sa fin : "
                             f"15:31 = ouverture de 15:30) ; tailles multiples du multiplicateur ; tests/test_letf.py",
                      verdict="ok" if entiers and pris["date"].is_unique else "alerte"))
    cut = jours[int(len(jours) * 0.6)]
    gr2 = copy.deepcopy(gr)
    for sym in gr2:
        for cle in ("adj", "brut"):
            g = gr2[sym][cle]
            apres = np.asarray(g.days > cut)
            for mat in (g.o, g.h, g.l, g.c):
                mat[apres] *= 1.25
    a = tr
    b = LT.portefeuille(gr2, gex_s=gx).trades.records_readable
    a, b = a[a["Exit Timestamp"] < cut].reset_index(drop=True), b[b["Exit Timestamp"] < cut].reset_index(drop=True)
    ok = len(a) == len(b) and np.allclose(a["PnL"], b["PnL"]) and (a["Entry Timestamp"] == b["Entry Timestamp"]).all()
    tests.append(dict(famille="Comptabilite", test="Biais d anticipation (prix futurs x 1,25)", resultat="aucun" if ok else "PROBLEME",
                      detail=f"{len(a)} trades avant le {cut:%d/%m/%Y} inchanges (seuil glissant, volume moyen et ATR calcules sur le passe)",
                      verdict="ok" if ok else "alerte"))
    tests.append(dict(famille="Donnees", test="Actif net des ETF a levier", resultat="approximation",
                      detail=f"{panel.attrs.get('aum', '')} ; le seuil q70 glissant est invariant a l echelle : seule la croissance des encours "
                             "depuis 2016 n est pas modelisee", verdict="alerte" if "constantes" in panel.attrs.get("aum", "") else "info"))
    tests.append(dict(famille="Donnees", test="Regime gamma (GEX SqueezeMetrics, S&P 500)",
                      resultat=f"G < 0 : {np.mean(panel.drop_duplicates('date')['G'] < 0):.0%} des seances",
                      detail="derniere valeur publiee avant la seance (5 jours au plus) ; G inconnu -> poids 1 ; NDX et QQQ non inclus",
                      verdict="info"))
    # mecanisme : la derniere demi-heure prolonge-t-elle le mouvement du jour ?
    for m_ in LT.mecanisme(gr, panel):
        tests.append(dict(famille="Mecanisme", test=f"{m_['symbole']} {m_['periode']} : r(15:30-16:00) sur r(veille-15:25)",
                          resultat=f"pente {m_['beta']:+.3f} (t {m_['t']:+.2f}) ; x gamma<0 {m_['beta_gamma_neg']:+.3f} (t {m_['t_gamma_neg']:+.2f})",
                          detail=f"{m_['n']} seances non exclues, erreurs de Newey-West ; gamma < 0 sur {m_['part_gamma_neg']:.0%} des seances",
                          verdict="ok" if m_["t"] >= 2 or m_["t_gamma_neg"] >= 2 else "alerte"))
    # placebos : memes regles dans une autre demi-heure de la seance
    plac = []
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        for lab, kw in [("15:30-16:00 (strategie)", {}), ("14:30-15:00 (placebo du NinjaScript)", dict(decalage_min=-60)),
                        ("13:30-14:00", dict(decalage_min=-120)), ("12:30-13:00", dict(decalage_min=-180))]:
            _, rr = run(**kw) if kw else (pf, r)
            plac.append(dict(cas=lab, sharpe=_js(_acc(rr).sharpe_ratio())))
    pl = [x["sharpe"] for x in plac[1:]]
    tests.append(dict(famille="Placebo", test="Memes regles, autre demi-heure", resultat=f"Sharpe {max(pl):.2f} au mieux",
                      detail=" ; ".join(f"{x['cas']} {x['sharpe']:.2f}" for x in plac), verdict="ok" if max(pl) < 0.3 else "alerte"))
    log("  mecanisme, placebos : ok")
    # sensibilite
    sens = []
    pub = pd.Timestamp(LT.PUBLICATION)
    for famille, cas in {"Couts": [("x0", dict(cout_mult=0.0)), ("x1 (reference)", {}), ("x2 (stress 2 ticks)", dict(cout_mult=2.0)),
                                   ("x3", dict(cout_mult=3.0))],
                         "Latence": [("15:30 (reference)", {}), ("+1 min", dict(delai_min=1)), ("+2 min", dict(delai_min=2)),
                                     ("+5 min", dict(delai_min=5))],
                         "Variantes": [("levier max 4", dict(levier_max=4.0)), ("sans filtre gamma", dict(filtre_gamma=False)),
                                       ("NQ seul", dict(symboles=("NQ",))), ("ES seul", dict(symboles=("ES",))),
                                       ("flux sans 1/(1+Lr)", dict(formule="nav_veille")), ("sans jours exclus", dict(exclusions=False))]}.items():
        for lab, kw in cas:
            _, rr = run(**kw) if kw else (pf, r)
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                sens.append(dict(famille=famille, cas=lab, sharpe=_js(_acc(rr).sharpe_ratio()), sharpe_apres=_js(_acc(rr[rr.index >= pub]).sharpe_ratio())))
    for famille in ("Couts", "Latence", "Variantes"):
        cas_ = [x for x in sens if x["famille"] == famille]
        pire = min(cas_, key=lambda x: x["sharpe"])
        tests.append(dict(famille="Sensibilite", test=f"{famille} : pire cas ({pire['cas']})", resultat=f"Sharpe {pire['sharpe']:.2f}",
                          detail=" ; ".join(f"{x['cas']} {x['sharpe']:.2f} (apres pub. {x['sharpe_apres']:.2f})" for x in cas_),
                          verdict="ok" if pire["sharpe"] >= 0.5 else "alerte"))
    log("  couts, latence, variantes : ok")
    extra, rmat = {}, None
    ref = dict(quantile=70.0, min_rendement_pct=0.5, atr_mult=1.5)
    ref_lab = ",".join(f"{k}={v}" for k, v in ref.items())
    if grille:
        axes = dict(quantile=[60.0, 70.0, 80.0], min_rendement_pct=[0.25, 0.5, 1.0], atr_mult=[1.0, 1.5, 2.0])
        rets, pts = {}, []
        for combo in itertools.product(*axes.values()):
            kw = dict(zip(axes, combo))
            _, rr = run(**kw)
            rets[",".join(f"{k}={v}" for k, v in kw.items())] = rr
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                pts.append(dict(kw, sharpe=_js(_acc(rr).sharpe_ratio())))
        log(f"  grille : {len(pts)} reglages")
        rmat = pd.DataFrame(rets)
        tg, extra = _grille_pbo_wf(rmat, ref_lab)
        shs = np.array([x["sharpe"] for x in pts], float)
        tg.insert(0, dict(famille="Sur-ajustement", test="Plateau (quantile du seuil x |r| minimum x stop ATR)",
                          resultat=f"{shs.min():.2f} a {shs.max():.2f}",
                          detail=f"{len(shs)} reglages ; {np.mean(shs > 0):.0%} positifs ; reglage de la fiche q70 / 0,5 % / 1,5 ATR",
                          verdict="ok" if np.mean(shs > 0) >= 0.8 else "alerte"))
        tests += tg
        extra["grille"] = dict(axes=list(axes), valeurs={k: list(map(_js, v)) for k, v in axes.items()}, points=pts, reference=ref)
    tc, mc = bloc_tests_communs(r, t, LT.PUBLICATION, LT.ESSAIS, LT.VAR_SHARPE_ESSAIS_ANNUALISE, n_sim)
    tests = tests[:2] + tc + tests[2:]
    # hasard : memes regles et meme taille de base les jours ou le signal est calculable, puis tirages de jours au hasard
    tous = dict(taille_fixe=True, jours_hasard=jours)
    pf_tous = LT.portefeuille(gr, gex_s=gx, base=base_de({}), **tous)
    tt = pf_tous.trades.records_readable
    par_jour = pd.Series(tt["PnL"].to_numpy() / cap, index=pd.DatetimeIndex(tt["Exit Timestamp"]).normalize()).groupby(level=0).sum()
    x = par_jour.reindex(cal).fillna(0.0)
    choisis = pd.DatetimeIndex(pris["date"])
    pool = np.flatnonzero(np.asarray(x.index.isin(par_jour.index)))
    rng = np.random.default_rng(17)
    M = np.zeros((len(x), n_sim))
    for k in range(n_sim):
        pick = rng.choice(pool, size=min(len(choisis), len(pool)), replace=False)
        M[pick, k] = x.to_numpy()[pick]
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        vals = pd.DataFrame(M, index=x.index).vbt.returns(freq="1D", year_freq=ANNEE).sharpe_ratio().to_numpy()
        obs = float(pd.Series(np.where(x.index.isin(choisis), x.to_numpy(), 0.0), index=x.index).vbt.returns(freq="1D", year_freq=ANNEE).sharpe_ratio())
    nul = dict(titre="Jours tires au hasard au lieu du score LETF", valeurs=vals, observe=obs,
               detail=f"{n_sim} tirages de {len(choisis)} jours parmi les {len(pool)} jours tradables (sens de r, taille de base, "
                      "memes stops) ; Sharpe observe = memes jours que la strategie, a taille de base")
    log("  jours au hasard : ok")
    ts, so = bloc_surajustement(r, rmat, ref_lab if rmat is not None else None, LT.ESSAIS, nul=nul, reps=n_sim)
    tests += ts
    extra["surajustement"] = so
    lev = pris["levier"]
    fiche = dict(
        id="LETF_NQ_ES", code="L1", titre="Fiche 15 · LETF NQ / ES", statut="candidate", valide_le=None,
        resume="En fin de seance, suivre le mouvement du jour sur le Nasdaq (le S&P en secours) quand les ETF a levier "
               "doivent acheter ou vendre beaucoup par rapport a la liquidite et que les teneurs de marche sont courts gamma.",
        fonctionnement=[
            "15:25 a New York : rendement du jour r (cloture de la veille -> 15:25). Les ETF a levier (TQQQ, SQQQ, QLD, QID pour le "
            "Nasdaq ; UPRO, SPXU, SPXL, SPXS, SSO, SDS pour le S&P) devront acheter (r > 0) ou vendre (r < 0) A x L(L-1) x r / (1 + L r) "
            "dollars a la cloture.",
            "Ce flux est converti en contrats (N) puis rapporte au volume moyen du future entre 15:30 et 16:00 sur 20 seances (S).",
            "Score = S x 1 si les teneurs de marche sont courts gamma (GEX < 0), x 0,3 sinon.",
            "Trade si |r| >= 0,5 % et |Score| >= 70e centile des 250 seances precedentes ; jamais les jours de FOMC, CPI, NFP, "
            "quatre sorcieres (rebalancement du Nasdaq-100) ni les demi-seances.",
            "Entree au marche a 15:30 dans le sens de r sur NQ (ES seulement si NQ ne passe pas) ; stop a 1,5 ATR des barres de 30 min ; "
            "sortie a 16:00 ; jamais de position la nuit.",
            f"Taille : 0,5 % du capital ({cap:,.0f} $) par ecart-type du mouvement attendu en 30 min, multiplie par |Score| / seuil, "
            f"sans plafond de levier (comme le NinjaScript) : levier median {lev.median():.1f}, maximum {lev.max():.1f}.",
            "Couts : 2,50 $ par contrat et par execution + 1/2 tick de glissement (1 tick aller-retour).",
        ],
        pourquoi="Les ETF a levier doivent re-exposer leur actif chaque soir dans le sens du marche du jour, quel que soit le sens "
                 "de leur levier ; quand ce flux previsible est grand devant la liquidite de fin de seance et que les teneurs de "
                 "marche d options amplifient le mouvement (courts gamma), le prix continue dans le sens du jour jusqu a la cloture.",
        sources=[dict(titre="Barbon, Beckmeyer, Buraschi & Moerke, Liquidity Provision to Leveraged ETFs and Equity Options Rebalancing Flows, SSRN 3925725",
                      lien="https://papers.ssrn.com/abstract=3925725"),
                 dict(titre="Baltussen, Da, Lammers & Martens (2021), Hedging demand and market intraday momentum, Journal of Financial Economics",
                      lien="https://doi.org/10.1016/j.jfineco.2021.04.029"),
                 dict(titre="NinjaScript d origine : Strategies/Nexus15_LetfRebalancing.cs (branche claude/adoring-cray-8l3ug8)",
                      lien="https://github.com/Mathisuuuu/FineShit/tree/claude/adoring-cray-8l3ug8")],
        parametres={k: _js(v) for k, v in LT.DEFAULTS.items() if k not in ("jours_hasard",)},
        donnees={"NQ": f"{info['NQ']['symbole']}, {info['NQ']['debut']} -> {info['NQ']['fin']}, {info['NQ']['rolls']} rolls",
                 "ES": f"{info['ES']['symbole']}, {info['ES']['debut']} -> {info['ES']['fin']}, {info['ES']['rolls']} rolls",
                 "source": "Databento GLBX.MDP3, ohlcv-1m (depot Cotations)", "horodatage": info["NQ"]["horodatage"],
                 "actif net LETF": panel.attrs.get("aum", ""), "GEX": "SqueezeMetrics (DIX.csv), valeur de la veille",
                 "jours exclus": "FOMC (Fed), CPI et NFP (BLS), quatre sorcieres, rebalancement special NDX 2023",
                 "calendrier": "seances NYSE completes communes a NQ et ES (feries et demi-seances exclus)"},
        capital=dict(initial=cap, unite="$", note="taille sur le capital initial (pas de reinvestissement), sans plafond de levier"),
        fuseau_trades="America/New_York", publication=LT.PUBLICATION,
        kpi=_kpi(valeur, t), vectorbt=bloc_vectorbt(pf, valeur), series=bloc_series(valeur), trades=rows,
        tests=tests, monte_carlo=mc, sensibilite=sens, placebo=plac, placebo_titre="Placebo : memes regles, autre demi-heure", **extra)
    return fiche, r


# =============================================================================
#  Export
# =============================================================================
# candidates a l etude : (code pour --seulement, identifiant de la fiche, fonction d export)
CANDIDATES = [("G1", "Gotobi_6J", fiche_gotobi), ("O1", "ORB_NQ", fiche_orb), ("N1", "OrNuit_GC", fiche_or_nuit),
              ("N2", "OrNuit_GC_conforme", lambda c, n, g, log=print: fiche_or_nuit(c, n, g, log, variante="conforme")),
              ("L1", "LETF_NQ_ES", fiche_letf)]


def strategies_validees() -> list[str]:
    return [c for c in available() if getattr(get(c), "VALIDATED", None)]




# =============================================================================
#  Export commun : toutes les strategies, memes objets vectorbt, memes tests
# =============================================================================
INSTRUMENTS_FICHE = {"S1": ["NQ"], "G1": ["6J"], "O1": ["NQ"], "N1": ["GC"], "N2": ["GC"], "L1": ["NQ", "ES"]}
FUTURES = {"ES", "NQ", "YM", "GC", "CL", "6E", "6B", "6J", "6A", "FDAX", "IWM"}       # IWM : substitut du future RTY
PRESETS_PROP = [dict(nom="50 000 $", compte=50000, objectif=3000, perte_jour=1000, dd=2000),
                dict(nom="100 000 $", compte=100000, objectif=6000, perte_jour=2000, dd=3000),
                dict(nom="150 000 $", compte=150000, objectif=9000, perte_jour=3000, dd=4500)]
MULTIPLICATEURS_PROP = [0.25, 0.5, 0.75, 1.0, 1.5, 2.0, 3.0, 4.0, 6.0, 8.0]


def _ecrire_json(obj, chemin: str):
    """JSON compact ; tout type inconnu (pd.NA, numpy...) passe par _js, sinon en texte."""
    def defaut(o):
        v = _js(o)
        return v if v is not o else str(o)
    with open(chemin, "w", encoding="utf-8") as fh:
        json.dump(obj, fh, ensure_ascii=False, separators=(",", ":"), default=defaut)


def positions_fiche(fiche: dict) -> pd.DataFrame:
    """Positions (debut, fin en UTC naif, instrument) a partir des trades de la fiche (heure locale fuseau_trades)."""
    rows = fiche.get("trades") or []
    if not rows:
        return pd.DataFrame(columns=["debut", "fin", "instrument"])
    defaut = (fiche.get("instruments") or ["?"])[0]
    tz = fiche.get("fuseau_trades") or "America/New_York"
    conv = lambda col: pd.DatetimeIndex(pd.to_datetime([x[col] for x in rows])).tz_localize(
        tz, ambiguous="NaT", nonexistent="shift_forward").tz_convert("UTC").tz_localize(None)
    p = pd.DataFrame({"debut": conv("entree"), "fin": conv("sortie"), "instrument": [x.get("actif") or defaut for x in rows]})
    return p.dropna()


def drapeaux(fiche: dict, pos: pd.DataFrame) -> dict:
    """futures : tous les instruments sont des futures ; intraday : chaque position est soldee dans sa seance CME
    (17:00 New York), comme l exigent les prop firms futures."""
    insts = sorted(set(pos["instrument"])) if len(pos) else list(fiche.get("instruments") or [])
    fut = fiche.get("futures", True) if fiche.get("origine") == "runner" else all(i in FUTURES for i in insts)
    if len(pos):
        seance = lambda s: (pd.DatetimeIndex(s).tz_localize("UTC").tz_convert("America/New_York") + pd.Timedelta(hours=6)).normalize()
        nuit = float((seance(pos["debut"]) != seance(pos["fin"])).mean())
    else:
        nuit = 1.0
    return dict(instruments=insts, futures=bool(fut), part_nuit=round(nuit, 4),
                intraday=bool(len(pos) and nuit <= 0.01 and not fiche.get("permanent")))


def _sharpe_ann(r: pd.Series) -> float:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return float(_acc(r).sharpe_ratio())


def dsr_uniforme(fiche: dict, r: pd.Series, essais: int = ESSAIS_PROGRAMME) -> float:
    """Sharpe deflate de la strategie avec le nombre CUMULE d essais du programme : meme ligne de test pour toutes.
    Variance des essais = variance du Sharpe estime sous l hypothese nulle (asymetrie et queues comprises), comme dans
    toute la recherche (alternatives.dsr) ; calcul vectorbt, controle par nexus.validation. (Jusqu au 2026-10-19 la
    variance etait celle des Sharpe des strategies exportees, 5,3, gonflee par des versions boguees tres negatives :
    le Sharpe a battre montait a 6,7 et toutes les strategies tombaient a 0.) La ligne calculee avec le nombre
    d essais propre a la strategie (strategies du tableau d origine) est gardee et renommee."""
    from . import prop_combinaisons as PC
    v0 = PC.var_nulle_ann(r)
    dsr = PC.dsr(r, essais)
    dsr_n, sr0 = V.deflated_sharpe(r.to_numpy(), int(essais))
    ligne = dict(famille="Robustesse statistique", test="Sharpe deflate (programme entier, vectorbt)", resultat=f"{dsr:.1%}",
                 detail=f"{essais} essais cumules du programme de recherche ; variance nulle du Sharpe {v0:.3f} (annualisee) ; "
                        f"Sharpe a battre {sr0 * math.sqrt(252):.2f} (controle nexus.validation : {dsr_n:.1%})",
                 verdict="ok" if dsr >= 0.95 else "alerte")
    tests = []
    for x in fiche["tests"]:
        if x["test"].startswith("Sharpe deflate (programme entier"):
            continue
        if x["test"].startswith("Sharpe deflate (vectorbt, essais comptes)"):
            if fiche.get("origine") == "runner":
                continue                                        # remplacee par la ligne commune
            x = dict(x, test="Sharpe deflate (essais de sa propre recherche)")
        tests.append(x)
    i = next((k for k, x in enumerate(tests) if x["test"].startswith("Probabilite que le Sharpe")), len(tests) - 1)
    tests.insert(i + 1, ligne)
    fiche["tests"] = tests
    fiche["dsr_programme"] = _js(dsr)
    return dsr


def _ic_bas(fiche: dict):
    for x in fiche["tests"]:
        if x["test"].startswith("IC 95 % du Sharpe (bootstrap"):
            try:
                return float(x["resultat"].strip("[]").split(";")[0].replace(",", "."))
            except ValueError:
                return None
    return None


def entree_index(fiche: dict) -> dict:
    return dict(id=fiche["id"], titre=fiche["titre"], statut=fiche["statut"], valide_le=fiche.get("valide_le"),
                verdict=fiche.get("verdict_runner"), origine=fiche.get("origine"), resume=fiche["resume"], kpi=fiche["kpi"],
                instruments=fiche.get("instruments"), futures=fiche.get("futures"), intraday=fiche.get("intraday"),
                part_nuit=fiche.get("part_nuit"), dsr_programme=fiche.get("dsr_programme"), sharpe_ic_bas=_js(_ic_bas(fiche)),
                capital=fiche["capital"]["initial"], alertes=sum(1 for x in fiche["tests"] if x["verdict"] == "alerte"),
                ok=sum(1 for x in fiche["tests"] if x["verdict"] == "ok"), tests=len(fiche["tests"]))


def annexe_prop(fiches: dict, rets: dict, positions: dict, log=print) -> dict:
    """Donnees de l onglet Prop firm : strategies futures intraday, rendements journaliers, correlations, conflits de
    contrat, profil horaire, et statistiques vectorbt de chaque strategie et de chaque combinaison classees par
    fiabilite (nexus/prop_combinaisons.py). Les taux de reussite pour des regles de compte modifiees se recalculent
    dans l interface (Dashboard/public/prop.js)."""
    from . import prop_combinaisons as PC
    from .perso.portefeuille import Chevauchement, Strategie
    ids = [i for i, f in fiches.items() if f.get("futures") and f.get("intraday") and i in rets]
    if not ids:
        return dict(candidats=[], presets=PRESETS_PROP, multiplicateurs=MULTIPLICATEURS_PROP)
    R = pd.DataFrame({i: rets[i] for i in ids}).sort_index()
    for i in ids:                                               # hors de sa periode, une strategie n existe pas
        r = rets[i]
        R.loc[(R.index < r.index[0]) | (R.index > r.index[-1]), i] = np.nan
    strats = [Strategie(i, R[i].fillna(0.0), positions[i]) for i in ids if len(positions[i])]
    ch = Chevauchement(strats)
    conf = ch.part_conflit().reindex(index=ids, columns=ids).fillna(0.0)
    prof = ch.profil_horaire().reindex(ids)
    tps = ch.temps_en_position()
    corr = R.corr(min_periods=120)
    p0 = PRESETS_PROP[0]
    fiab = PC.analyser(R, corr, conf, ESSAIS_PROGRAMME, dict(compte=p0["compte"], objectif=p0["objectif"],
                       perte_jour=p0["perte_jour"], dd=p0["dd"], horizon=120), MULTIPLICATEURS_PROP, log,
                       heures={i: float(tps.get(i, np.nan)) * 365.25 * 24 for i in ids})
    cands = []
    for i in ids:
        f, r = fiches[i], R[i]
        ok = r.notna()
        cands.append(dict(id=i, titre=f["titre"], statut=f["statut"], instruments=f.get("instruments"), sharpe=_js(_sharpe_ann(r[ok])),
                          vol=_js(float(r[ok].std(ddof=1))), debut=_js(r[ok].index[0]), fin=_js(r[ok].index[-1]),
                          capital=f["capital"]["initial"], temps_en_position=_js(tps.get(i, np.nan)),
                          dsr_programme=f.get("dsr_programme"), profil=_round(prof.loc[i].to_numpy(), 4) if i in prof.index else None,
                          stats=_js(fiab["membres"][i])))
    return dict(dates=[d.strftime("%Y-%m-%d") for d in R.index], candidats=cands,
                rendements={i: _round(R[i].to_numpy(), 7) for i in ids},
                correlation=[[_js(v) for v in row] for row in corr.to_numpy()],
                conflits=[[_js(v) for v in row] for row in conf.to_numpy()],
                presets=PRESETS_PROP, multiplicateurs=MULTIPLICATEURS_PROP, horizon=120,
                combinaisons=_js(fiab["combinaisons"]), recommandee=_js(fiab["recommandee"]), validation=_js(fiab["validation"]),
                essais_combinaisons=fiab["essais_combinaisons"], filtres=fiab["filtres"], coupure=fiab["coupure"],
                sigma_ref=PC.SIGMA_REF,
                note="Taille : chaque strategie est ramenee au meme risque (ecart-type journalier), puis le groupe est mis a "
                     "l echelle du compte par un multiplicateur ; tailles continues (l arrondi au micro-contrat n est pas modelise).")


def exporter(cotations: str, sortie: str, n_sim: int = 2000, grille: bool = True, seulement=None, log=print) -> dict:
    """Toutes les strategies (celles du tableau d origine et toutes celles du runner local) -> une fiche JSON chacune,
    au meme format, avec les memes tests ; puis index.json, rendements.json (comparaison), prop.json (onglet Prop firm)
    et etudes.json (etudes sur papiers). seulement : codes (S1, G1, O1, N1, L1), « R » (tout le runner) ou identifiants."""
    from . import tableau_runner as TR
    from .perso.runner import TESTS
    from .perso.tableau import lire_resultats
    if vbt is None:
        raise ImportError("vectorbt n est pas installe")
    os.makedirs(sortie, exist_ok=True)
    lignes = lire_resultats()
    taches = [(c, "tableau", lambda c=c: fiche_nexus(c, cotations, n_sim, grille, log)) for c in strategies_validees()]
    taches += [(code, "tableau", lambda f=f: f(cotations, n_sim, grille, log)) for code, _, f in CANDIDATES]
    taches += [(TR._ident(nom), "runner", lambda a=(nom, src, spec, note): TR.fiche_runner(*a, lignes.get(a[0], {}), ESSAIS_PROGRAMME, n_sim, log))
               for nom, src, spec, note in TESTS]
    fiches, rets = {}, {}
    for code, origine, f in taches:
        if seulement and not (code in seulement or (origine == "runner" and "R" in seulement)):
            continue
        log(f"[tableau] {code}")
        t0 = time.time()
        try:
            res = f()
        except Exception as ex:                                          # noqa: BLE001 : une fiche en erreur n arrete pas l export
            import traceback
            log(f"[tableau] {code} : ERREUR {type(ex).__name__} : {ex}")
            log(traceback.format_exc(limit=4))
            continue
        if res is None:
            log(f"[tableau] {code} : pas de resultats du runner, ignoree")
            continue
        fiche, r = res
        fiche["origine"] = origine
        if origine == "tableau":
            fiche.setdefault("instruments", INSTRUMENTS_FICHE.get(code, []))
        fiche["genere_le"] = dt.datetime.now().strftime("%Y-%m-%d %H:%M")
        fiches[fiche["id"]] = fiche
        rets[fiche["id"]] = r
        _ecrire_json(fiche, os.path.join(sortie, f"{fiche['id']}.json"))     # ecrite tout de suite, recrite apres la passe commune
        log(f"[tableau] {code} calcule ({time.time() - t0:.0f} s)")
    if seulement and os.path.exists(os.path.join(sortie, "index.json")):     # export partiel : reprendre les autres fiches
        with open(os.path.join(sortie, "index.json"), encoding="utf-8") as fh:
            ancien = json.load(fh)
        for e in ancien.get("strategies", []):
            f_ = os.path.join(sortie, f"{e['id']}.json")
            if e["id"] in fiches or not os.path.exists(f_):
                continue
            with open(f_, encoding="utf-8") as fh:
                fiche = json.load(fh)
            fiche.setdefault("origine", "tableau" if e["id"] in {i for _, i, _ in CANDIDATES} or fiche.get("statut") == "validee" else "runner")
            fiches[e["id"]] = fiche
            ser = fiche["series"]
            rets[e["id"]] = pd.Series(ser["rendement"], index=pd.DatetimeIndex(ser["dates"]), dtype=float).fillna(0.0)
    # memes tests pour toutes : Sharpe deflate sur le nombre cumule d essais et la variance des Sharpe du tableau
    shs = np.array([_sharpe_ann(r) for r in rets.values()], float)
    var_ann = float(np.nanvar(shs[np.isfinite(shs)], ddof=1)) if np.isfinite(shs).sum() > 2 else VAR_SHARPE_PROGRAMME
    positions = {}
    for i, fiche in fiches.items():
        dsr_uniforme(fiche, rets[i])
        positions[i] = positions_fiche(fiche)
        fiche.update(drapeaux(fiche, positions[i]))
        _ecrire_json(fiche, os.path.join(sortie, f"{i}.json"))
    liste = [entree_index(f) for f in fiches.values()]
    rang = {"validee": 0, "candidate": 1}
    liste.sort(key=lambda e: (rang.get(e["statut"], 2), -(e["kpi"].get("sharpe") or -99)))
    R = pd.DataFrame(rets).sort_index()
    for i, r in rets.items():
        R.loc[(R.index < r.index[0]) | (R.index > r.index[-1]), i] = np.nan
    R = R[[e["id"] for e in liste]]
    _ecrire_json(dict(dates=[d.strftime("%Y-%m-%d") for d in R.index], rendements={c: _round(R[c].to_numpy(), 7) for c in R}),
                 os.path.join(sortie, "rendements.json"))
    prop = annexe_prop(fiches, rets, positions, log)
    _ecrire_json(prop, os.path.join(sortie, "prop.json"))
    etudes = os.path.join(os.path.dirname(__file__), "..", "recherche", "resultats_60.json")
    if os.path.exists(etudes):
        with open(etudes, encoding="utf-8") as fh, open(os.path.join(sortie, "etudes.json"), "w", encoding="utf-8") as out:
            json.dump(json.load(fh), out, ensure_ascii=False, separators=(",", ":"))
    from .perso.tableau import non_testees
    index = dict(version=VERSION, genere_le=dt.datetime.now().strftime("%Y-%m-%d %H:%M"), strategies=liste, non_testees=non_testees(),
                 essais_programme=ESSAIS_PROGRAMME, variance_sharpe=_js(var_ann), prop_candidats=len(prop["candidats"]),
                 note="Resultats calcules sur des donnees sous licence (usage prive) : ne pas publier ce dossier.")
    _ecrire_json(index, os.path.join(sortie, "index.json"))
    from . import profil_horaire
    profil_horaire.ecrire(sortie)                                      # page Profil horaire (strategies fiables sur un an)
    return index
