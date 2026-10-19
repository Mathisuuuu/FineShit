"""Tableau de bord HTML interactif des strategies personnelles, calcule avec vectorbt.

    python -m nexus.perso.tableau [--sortie ../Dashboard/donnees/recherche.html]

La page est servie par le tableau de bord Node (http://localhost:3000/recherche.html, lien « Archive de la recherche »).

Relit les derniers resultats du runner (resultats/perso_*, resultats_strategies.csv) ; a relancer apres chaque
backtest. La page est autonome (plotly.js integre, aucune connexion requise) et contient :
  1. toutes les strategies testees (tableau triable, filtre par verdict) ;
  2. un explorateur par strategie : statistiques vectorbt (returns accessor), gain cumule, drawdowns (records
     vectorbt), Sharpe sur 1 an glissant, P&L mensuel ;
  3. le portefeuille prop firm futures : strategies retenues, correlations, conflits de contrat, profil horaire,
     et la simulation d evaluation recalculee dans la page quand on change les regles du compte.
Les cotations elles-memes (licence Databento) ne sont pas dans la page : seulement des P&L de backtest.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import warnings
from datetime import datetime

import numpy as np
import pandas as pd

from .portefeuille import (MULTIPLICATEURS, Chevauchement, Diversification, Strategie, _is_futures, charger,
                           groupes_admissibles, retenir)
from .runner import PY_DIR, TESTS
from .statistiques import _arrondir, analyser, durees_trades, trades_pnl

PRESETS = [
    dict(nom="50 000 $", compte=50000, objectif=3000, perte_jour=1000, dd=2000),
    dict(nom="100 000 $", compte=100000, objectif=6000, perte_jour=2000, dd=3000),
    dict(nom="150 000 $", compte=150000, objectif=9000, perte_jour=3000, dd=4500),
]

STATS_VBT = [  # (cle vectorbt, libelle, format, explication) - libelles affiches tels quels dans la page
    ("Total Return [%]", "Rendement total", "pct", "Gain total rapporté au capital de départ du backtest"),
    ("Annualized Return [%]", "Rendement annualisé", "pct", "Rendement composé ramené à 252 jours de bourse"),
    ("Annualized Volatility [%]", "Volatilité annualisée", "pct", "Écart-type des rendements quotidiens × √252"),
    ("Sharpe Ratio", "Sharpe", "ratio", "Rendement moyen ÷ volatilité, annualisé (taux sans risque nul)"),
    ("Sortino Ratio", "Sortino", "ratio", "Comme le Sharpe, mais seule la volatilité des jours de baisse compte"),
    ("Calmar Ratio", "Calmar", "ratio", "Rendement annualisé ÷ drawdown maximal"),
    ("Omega Ratio", "Omega", "ratio", "Somme des gains ÷ somme des pertes quotidiennes (seuil 0)"),
    ("Max Drawdown [%]", "Drawdown max", "pct", "Plus forte baisse depuis un sommet de la courbe de capital"),
    ("Max Drawdown Duration", "Plus long drawdown", "jours", "Jours de bourse du sommet au retour au sommet, pour le drawdown le plus long"),
    ("Tail Ratio", "Tail ratio", "ratio", "95e centile des rendements ÷ |5e centile| : au-dessus de 1, queues favorables"),
    ("Value at Risk", "VaR 95 % sur 1 jour", "pct1", "Perte quotidienne dépassée 5 % des jours"),
    ("Skew", "Asymétrie", "ratio", "Positive : gains extrêmes plus fréquents que les pertes extrêmes"),
]


# Conclusions de l etude des alternatives (resultats_alternatives.txt, 2026-10-09) : performance expliquee par une
# reference naive, alpha non distinguable de zero. Elles priment sur la regression generique contre le SPY.
SURTOUT_BETA = {
    "S20-A Risk parity ERC multi-futures": "≈ 1/N des mêmes 4 jambes (alpha t +0,8 contre le 1/N)",
    "S20-B Risk parity inverse-vol multi-futures": "≈ 1/N des mêmes 4 jambes",
    "S20-A ERC, covariance sur 60 j (alternative)": "≈ 1/N des mêmes 4 jambes ; PBO de la famille 47 %",
    "S20 1/N, memes 4 jambes (reference naive)": "référence naïve elle-même (portefeuille de bêta)",
    "Fiche 2 XSMOM (futures)": "bêta 0,76 sur le 1/N long des mêmes futures (alpha t +0,7) ; PBO de la grille 70 %",
    "Fiche 5 Retour a la moyenne de vol (futures)": "bêta 0,43 sur ES + NQ (alpha t +1,1)",
    "Fiche 1 TSMOM 12-1 (25 actions/ETF US)": "alpha t +0,2 contre les 25 titres à poids égal",
    "Fiche 2 XSMOM quartile superieur (25 actions/ETF US)": "alpha t +0,8 contre les 25 titres à poids égal",
    "Fiche 3 Rotation multi-facteurs": "alpha t +0,3 contre les 25 titres à poids égal",
    "Fiche 4A Residu OU sectoriel": "alpha t +1,3 contre le SPY",
    "Fiche 11 Roue d options synthetique": "alpha t −0,3 contre le SPY",
}
CRITERES_TOP = [
    ("ic", "Sharpe significatif", "borne basse de l'intervalle de confiance à 95 % du Sharpe au-dessus de 0"),
    ("periodes", "Stable", "Sharpe positif sur 2016-2020 et sur 2021-2026"),
    ("alpha", "Pas seulement du bêta", "alpha contre le SPY avec t ≥ 2, et pas de verdict « surtout du bêta » dans l'étude des alternatives"),
    ("donnees", "Données fiables", "au moins 5 ans, univers sans biais du survivant, pas d'options synthétiques"),
]


def _sharpe(x: pd.Series) -> float | None:
    x = pd.Series(x).dropna()
    return float(x.mean() / x.std(ddof=1) * math.sqrt(252)) if len(x) >= 60 and x.std(ddof=1) > 0 else None


def alpha_spy(pnl: pd.Series, spy: pd.Series) -> dict:
    """Regression du P&L quotidien ($) sur le rendement quotidien du SPY : alpha annuel ($), t de l alpha, correlation."""
    d = pd.concat([pnl.rename("y"), spy.rename("x")], axis=1, join="inner").dropna()
    if len(d) < 60:
        return dict(alpha=None, t=None, corr=None)
    X = np.column_stack([np.ones(len(d)), d.x.to_numpy()])
    coef, *_ = np.linalg.lstsq(X, d.y.to_numpy(), rcond=None)
    res = d.y.to_numpy() - X @ coef
    cov = (res @ res / (len(d) - 2)) * np.linalg.inv(X.T @ X)
    return dict(alpha=_f(coef[0] * 252, 0), t=_f(coef[0] / math.sqrt(cov[0, 0]), 2), corr=_f(d.x.corr(d.y), 2))


def classement(strategies: list[dict], par_nom: dict) -> list[dict]:
    """Top des strategies : criteres remplis (CRITERES_TOP), puis borne basse de l IC du Sharpe."""
    from .fx_trois import etf_close
    spy = etf_close("SPY")
    spy.index = pd.DatetimeIndex(spy.index).tz_localize(None).normalize() if getattr(spy.index, "tz", None) else \
        pd.DatetimeIndex(spy.index).normalize()
    r_spy = spy.pct_change()
    out = []
    for d in strategies:
        s = par_nom.get(d["nom"])
        if s is None or d.get("serie") is None or not d.get("ic") or "tel que code" in d["nom"]:
            continue                                               # versions boguees : seule la version corrigee compte
        sh = d["ic"]["sharpe"]
        if sh.get("valeur") is None or sh["valeur"] <= 0:
            continue
        pnl = s.pnl.astype(float)
        pnl.index = pd.DatetimeIndex(pnl.index).normalize()
        p1, p2 = _sharpe(pnl[pnl.index < "2021-01-01"]), _sharpe(pnl[pnl.index >= "2021-01-01"])
        a = alpha_spy(pnl, r_spy)
        ans = (pnl.index[-1] - pnl.index[0]).days / 365.25
        note = (d.get("note") or "") + " " + d["nom"]
        drapeaux = []
        if "biais du survivant" in note:
            drapeaux.append("univers d'aujourd'hui : biais du survivant")
        if "SYNTHETIQUES" in note:
            drapeaux.append("options synthétiques (prime de variance supposée)")
        if ans < 5:
            drapeaux.append(f"{ans:.1f} ans de données seulement")
        beta = SURTOUT_BETA.get(d["nom"])
        remarques = ([f"surtout du bêta : {beta}"] if beta else []) + drapeaux
        if "(alternative)" in d["nom"]:
            remarques.append("variante retenue parmi plusieurs (biais de sélection modéré)")
        if d.get("permanent"):
            remarques.append("position permanente redimensionnée")
        crit = dict(ic=bool((sh["ic"][0] or -1) > 0), periodes=bool(p1 and p2 and p1 > 0 and p2 > 0),
                    alpha=bool(a["t"] is not None and a["t"] >= 2 and not beta), donnees=bool(not drapeaux))
        out.append(dict(id=d["id"], nom=d["nom"], court=d["court"], sharpe=sh["valeur"], sh_ic=sh["ic"], p1=_f(p1, 2),
                        p2=_f(p2, 2), alpha=a["alpha"], alpha_t=a["t"], corr_spy=a["corr"], criteres=crit,
                        score=int(sum(crit.values())), remarques=remarques, futures=bool(d["futures"]), trades=d.get("trades")))
    out.sort(key=lambda r: (-r["score"], -(r["sh_ic"][0] if r["sh_ic"][0] is not None else -9)))
    for i, r in enumerate(out):
        r["rang"] = i + 1
    return out


def recherche60(path: str | None = None) -> dict | None:
    path = path or os.path.join(PY_DIR, "recherche", "resultats_60.json")
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def _vbt():
    import vectorbt as vbt
    return vbt


def _f(x, nd=2):
    """Nombre arrondi pour le JSON ; None pour NaN, NaT, infini ou valeur non numerique."""
    try:
        x = float(x)
    except (TypeError, ValueError):
        return None
    return round(x, nd) if math.isfinite(x) else None


def _liste(a, nd):
    return [None if not np.isfinite(v) else round(float(v), nd) for v in np.asarray(a, dtype=float)]


def _nombre(txt):
    """'+11 968 $' / '43%' / '1.08' -> float (None si vide ou n/d)."""
    if txt is None:
        return None
    t = str(txt).replace(" ", "").replace(" ", "").replace("%", "").replace("$", "").replace(",", ".")
    try:
        return float(t)
    except ValueError:
        return None


def lire_resultats(path: str | None = None) -> dict:
    """Lignes de resultats_strategies.txt (ecrit par le runner) -> {nom: champs}."""
    path = path or os.path.join(PY_DIR, "recherche", "resultats_strategies.txt")
    out = {}
    if not os.path.exists(path):
        return out
    prefixes = [("reussite ", "reussite"), ("PnL net ", "pnl"), ("PF ", "pf"), ("Sharpe ", "sharpe"),
                ("DD max ", "dd"), ("t ", "t"), ("VERDICT ", "verdict")]
    with open(path, encoding="utf-8") as fh:
        for ligne in fh:
            ligne = ligne.rstrip("\n")
            if not ligne or ligne.startswith("#") or ligne.startswith("NON TESTEES") or " | " not in ligne:
                continue
            champs = ligne.split(" | ")
            d = dict(fichier=champs[1] if len(champs) > 1 else "", donnees=champs[2] if len(champs) > 2 else "",
                     periode=champs[3] if len(champs) > 3 else "", erreur=None)
            for c in champs[4:]:
                if c.endswith(" trades"):
                    d["trades"] = _nombre(c[:-7])
                elif c.startswith("ERREUR"):
                    d["verdict"], d["erreur"] = "ERREUR", c
                else:
                    for p, k in prefixes:
                        if c.startswith(p) and k not in d:
                            d[k] = c[len(p):] if k == "verdict" else _nombre(c[len(p):])
                            break
            out[champs[0]] = d
    return out


def non_testees(path: str | None = None) -> list[str]:
    path = path or os.path.join(PY_DIR, "recherche", "resultats_strategies.txt")
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as fh:
        return [l.strip()[len("NON TESTEES - "):] for l in fh if l.startswith("NON TESTEES")]


def noms_courts(noms: list[str]) -> list[str]:
    """Libelles courts et uniques pour les axes : 'S06-B corr.', 'Fiche 5 fut.', 'boombitch'..."""
    import re
    out = []
    for n in noms:
        m = re.match(r"(S\d\d-[A-Z]|Fiche \d+[A-Z]?|Test OPR)", n)
        fil = re.match(r"Fil ES/NQ fiche (\d)", n)
        orr = re.match(r"Or (\d+)", n)
        c = m.group(1) if m else (f"Fil F{fil.group(1)}" if fil else (f"Or {orr.group(1)}" if orr else re.split(r"[ (,]", n)[0]))
        for motif, suffixe in (("1/N", " 1/N"), ("covariance sur 60", " 60 j"), ("taille inverse", " vol."),
                               ("filtre de tendance", " tend."), ("small-cap : fade", " fade"), ("small-cap : reversal", " jump"),
                               ("FX fix flow", " fix"), ("FX post-annonce", " annonces"), ("FX cascade", " ronds"),
                               ("FX trois", " combinees"), ("Gotobi pre-fix", " pre-fix"), ("Gotobi seconde", " jambe 2")):
            if motif in n:
                c += suffixe
        sur = re.search(r" sur (\w+)$", n)
        if sur:
            c += " " + sur.group(1)
        if "(futures)" in n:
            c += " fut."
        if "tel que code" in n:
            c += " code"
        elif "corrige" in n:
            c += " corr."
        if "sans stop" in n:
            c += " sans stop"
        if "historique long" in n:
            c += " long"
        out.append(c)
    vus = {}
    for i, c in enumerate(out):                    # doublons restants : on numerote
        if out.count(c) > 1:
            vus[c] = vus.get(c, 0) + 1
            out[i] = f"{c} #{vus[c]}"
    return out


def analyse_vbt(s: Strategie) -> dict:
    """Statistiques et series calculees par vectorbt pour une strategie (P&L quotidien en $)."""
    _vbt()                                                         # enregistre l accesseur pandas .vbt
    pnl = s.pnl.astype(float)
    base = s.capital + pnl.cumsum().shift(1).fillna(0.0)          # capital en debut de journee
    if (base <= 0).any():                                          # compte ruine : rendements simples sur le capital
        base = pd.Series(s.capital, index=pnl.index)
    rets = pnl / base
    valeur = s.capital + pnl.cumsum()
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        ra = rets.vbt.returns(freq="1D", year_freq="252 days")
        st = ra.stats()
        dd = ra.drawdown()
        rs = ra.rolling_sharpe_ratio(252)
        rec = valeur.vbt.drawdowns.records_readable
    stats = []
    for cle, lib, fmt, aide in STATS_VBT:
        v = st.get(cle, np.nan)
        if isinstance(v, pd.Timedelta):
            v = v / pd.Timedelta(days=1)
        stats.append(dict(libelle=lib, valeur=_f(v, 4), format=fmt, aide=aide))
    pos = {t: i for i, t in enumerate(valeur.index)}
    dds = []
    if len(rec):
        rec = rec.assign(prof=(rec["Valley Value"] - rec["Peak Value"]) / rec["Peak Value"]).sort_values("prof").head(5)
        for _, r in rec.iterrows():
            fini = r["Status"] == "Recovered"
            pic = r["Peak Timestamp"]
            fin = r["End Timestamp"] if fini else valeur.index[-1]
            dds.append(dict(pic=f"{pic:%Y-%m-%d}", creux=f"{r['Valley Timestamp']:%Y-%m-%d}",
                            fin=f"{fin:%Y-%m-%d}" if fini else None, profondeur_pct=_f(r["prof"] * 100, 2),
                            profondeur_usd=_f(r["Peak Value"] - r["Valley Value"], 0), duree=int(pos[fin] - pos[pic])))
    m = pnl.groupby([pnl.index.year, pnl.index.month]).sum()
    annees = sorted({a for a, _ in m.index})
    mensuel = [[_f(m.get((a, mo), np.nan), 0) if (a, mo) in m.index else None for mo in range(1, 13)] for a in annees]
    return dict(stats=stats, drawdowns=dds, dd=dd, sharpe_1an=rs, mensuel=dict(annees=annees, valeurs=mensuel))


def _prop(toutes: list[Strategie], ids: dict, seuil_sharpe: float, seuil_corr: float, tol_conflit: float) -> dict:
    fut = [s for s in toutes if _is_futures(s.spec)]
    out, cache = {}, {}
    for p in PRESETS:
        dec = retenir(fut, p["compte"], seuil_sharpe)
        cands = [d for d in dec if not d["raison"]]
        noms = tuple(d["strategie"].nom for d in cands)
        echelles = {d["strategie"].nom: d["echelle"] for d in cands}
        cle = (noms, tuple(round(echelles[n], 6) for n in noms))
        if cle not in cache:
            strats = [d["strategie"] for d in cands]
            res = dict(groupes=[], corr=[], conflits=[], profil=[], temps=[])
            if len(strats) >= 2:
                div = Diversification(strats, echelles)
                chev = Chevauchement(strats)
                corr = div.correlation().loc[list(noms), list(noms)]
                conf = chev.part_conflit().reindex(index=list(noms), columns=list(noms))
                prof = chev.profil_horaire().reindex(list(noms))
                tp = chev.temps_en_position()
                res = dict(groupes=[[ids[n] for n in g] for g in groupes_admissibles(div, chev, list(noms), seuil_corr, tol_conflit)],
                           corr=[_liste(r, 3) for r in corr.to_numpy()], conflits=[_liste(r, 4) for r in conf.to_numpy()],
                           profil=[_liste(r, 4) for r in prof.to_numpy()], temps=[_f(tp.get(n, np.nan), 4) for n in noms])
            cache[cle] = res
        out[str(p["compte"])] = dict(
            candidates=[dict(id=ids[d["strategie"].nom], echelle=d["echelle"], description=d["description"]) for d in cands],
            exclues=[dict(id=ids[d["strategie"].nom], raison=d["raison"], description=d["description"]) for d in dec if d["raison"]],
            **cache[cle])
    return out


def construire(seuil_sharpe: float = 0.3, seuil_corr: float = 0.3, tol_conflit: float = 0.02) -> dict:
    toutes = charger(seulement_futures=False)
    par_nom = {s.nom: s for s in toutes}
    lignes = lire_resultats()
    axe = pd.DatetimeIndex(sorted(set().union(*[set(s.pnl.index) for s in toutes]))) if toutes else pd.DatetimeIndex([])
    rang = {t: i for i, t in enumerate(axe)}
    strategies, ids = [], {}
    courts = noms_courts([t[0] for t in TESTS])
    for i, (nom, src, spec, note) in enumerate(TESTS):
        r = lignes.get(nom, {})
        d = dict(id=i, nom=nom, court=courts[i], fichier=src, donnees=r.get("donnees", ""), periode=r.get("periode", ""),
                 trades=r.get("trades"), reussite=r.get("reussite"), pnl=r.get("pnl"), pf=r.get("pf"),
                 sharpe=r.get("sharpe"), dd=r.get("dd"), t=r.get("t"), verdict=r.get("verdict") or "PAS ENCORE LANCEE",
                 erreur=r.get("erreur"), note=note, futures=_is_futures(spec), serie=None, permanent=spec.get("permanent", False),
                 edge=None, edge_ic=None, p_edge=None, sh_ic=None, psr=None, duree=None, duree_moy=None)
        s = par_nom.get(nom)
        if s is not None and len(s.pnl) > 20:
            ids[nom] = i
            a = analyse_vbt(s)
            debut, fin = rang[s.pnl.index[0]], rang[s.pnl.index[-1]]
            sous = axe[debut:fin + 1]
            d["serie"] = dict(debut=debut, capital=s.capital,
                              pnl=_liste(s.pnl.reindex(sous).to_numpy(), 2),
                              dd=_liste(a["dd"].reindex(sous).to_numpy() * 100, 3),
                              sharpe_1an=_liste(a["sharpe_1an"].reindex(sous).to_numpy(), 3))
            d.update(stats=a["stats"], drawdowns=a["drawdowns"], mensuel=a["mensuel"])
            st = analyser(s.pnl, trades_pnl(nom), spec.get("permanent", False))
            e, sh = st["edge"], st["sharpe"]
            d["ic"] = _arrondir(st, 3)
            if e and "esperance" in e:
                d.update(edge=_f(e["esperance"], 2), edge_ic=[_f(e["ic"][0], 2), _f(e["ic"][1], 2)], p_edge=_f(e["p_pos"], 3))
            d.update(sh_ic=[_f(sh["ic"][0], 3), _f(sh["ic"][1], 3)], psr=_f(sh["p_pos"], 3))
            du = None if spec.get("permanent", False) else durees_trades(nom)
            if du:
                d.update(duree=_arrondir(du, 1), duree_moy=_f(du["moyenne"], 1))
        strategies.append(d)
    return dict(
        genere=f"{datetime.now():%Y-%m-%d %H:%M}", vectorbt=getattr(_vbt(), "__version__", "?"),
        dates=[f"{t:%Y-%m-%d}" for t in axe], strategies=strategies, non_testees=non_testees(),
        top=dict(criteres=[dict(cle=k, lib=l, aide=a) for k, l, a in CRITERES_TOP], lignes=classement(strategies, par_nom)),
        recherche60=recherche60(),
        prop=dict(presets=PRESETS, multiplicateurs=list(MULTIPLICATEURS), horizon=120, seuil_sharpe=seuil_sharpe,
                  seuil_correlation=seuil_corr, tolerance_conflit=tol_conflit,
                  comptes=_prop(toutes, ids, seuil_sharpe, seuil_corr, tol_conflit)))


def ecrire(data: dict, path: str) -> str:
    import plotly.offline
    gabarit = open(os.path.join(os.path.dirname(__file__), "tableau_gabarit.html"), encoding="utf-8").read()
    js = json.dumps(data, ensure_ascii=False, separators=(",", ":"), allow_nan=False).replace("</", "<\\/")
    html = (gabarit.replace("/*__PLOTLY__*/", plotly.offline.get_plotlyjs().replace("</script", "<\\/script"))
            .replace("/*__DONNEES__*/null", js))
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(html)
    return path


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--sortie", default=os.path.join(PY_DIR, "..", "Dashboard", "donnees", "recherche.html"),
                    help="page lue par le serveur Node (Dashboard/serveur.js, adresse /recherche.html)")
    ap.add_argument("--seuil-sharpe", type=float, default=0.3)
    ap.add_argument("--seuil-correlation", type=float, default=0.3)
    ap.add_argument("--tolerance-conflit", type=float, default=0.02)
    a = ap.parse_args(argv)
    data = construire(a.seuil_sharpe, a.seuil_correlation, a.tolerance_conflit)
    ecrire(data, a.sortie)
    n = sum(1 for s in data["strategies"] if s["serie"])
    print(f"[tableau] {len(data['strategies'])} strategies ({n} avec courbe), {os.path.getsize(a.sortie) / 1e6:.1f} Mo -> {a.sortie}")


if __name__ == "__main__":
    main()
