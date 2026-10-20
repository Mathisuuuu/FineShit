"""Laboratoire de recherche en direct : page « Laboratoire » du tableau de bord (Dashboard/donnees/labo.json).

Chaque hypothese testee (papier SSRN ou autre, regle fixee avant le calcul) devient un portefeuille VECTORBT : un ordre a
l entree (exposition +100 % ou -100 % du capital), un ordre a la sortie, frais par cote en fraction du notionnel. Tout ce
qui est affiche en vient : serie journaliere (valeur vectorbt en fin de journee de New York), trades vectorbt, statistiques
vectorbt de nexus.prop_combinaisons.mesures (Sharpe et IC bootstrap, moities, 12 et 24 derniers mois, Sharpe deflate,
perte max), heures en position, profil par demi-heure sur un an, zone horaire.

Une strategie est retenue pour la combinaison si elle est :
  - fiable : borne basse de l IC du Sharpe > 0 et Sharpe > 0 sur 2016-2020 et 2021-2026 ;
  - toujours vivante : Sharpe > 0 sur les 24 derniers mois de donnees ;
  - courte : au plus HEURES_MAX heures en position par an (nexus.prop_combinaisons) ;
et la combinaison (jusqu a 4, correlation <= 0,3, conflit de contrat <= 2 %) est classee par la borne basse de l IC du
Sharpe, comme l onglet Prop firm. Le fichier est recrit a chaque etape (ecriture atomique) : la page le relit toutes les
5 secondes.

    python -m nexus.labo --remplir        (strategies du tableau de bord + hypotheses deja testees -> labo.json)
"""
from __future__ import annotations

import argparse
import json
import math
import os
from datetime import datetime

import numpy as np
import pandas as pd

from . import prop_combinaisons as PC

ICI = os.path.dirname(__file__)
DONNEES = os.path.normpath(os.path.join(ICI, "..", "..", "Dashboard", "donnees"))
FICHIER = os.path.join(DONNEES, "labo.json")
CACHE = os.path.normpath(os.path.join(ICI, "..", ".cache", "labo"))
NY = "America/New_York"
JOURS = pd.bdate_range("2016-01-04", "2026-08-28")
# temps a surveiller (demande du 2026-10-20) : une strategie qui peut se declencher TOUS les jours occupe sa fenetre chaque
# jour de bourse, meme sans position ; seules les strategies d evenements connus a l avance (jours gotobi, resultats) ne
# coutent que leurs jours. Seuils de temps (heures de surveillance par an) proposes sur la page.
EVENEMENTIELLES = {"Gotobi_6J", "R_NQ_1_A_resultats_des_grandes_capitalisations_30_min_apres_le", "R_Or_4_Fed_accommodante_sortie_14_28",
                   "R_Gotobi_pre_fix_USD_JPY_Ito_Yamada", "R_Gotobi_seconde_jambe_vente_apres_le_fixing_hypothese",
                   "R_FX_fix_flow_fin_de_mois_Krohn_Melvin_Prins", "R_S09_A_Fade_du_fix_WM_R_fin_de_mois_sur_6B",
                   "R_S09_A_Fade_du_fix_WM_R_fin_de_mois_sur_6E", "R_FX_post_annonce_NFP_CPI_flux_walk_forward",
                   "R_S19_A_Rebalancement_LETF_derniere_1_2_h_US"}
SEUILS = (400, 800, 1600, None)
JOURS_BOURSE_AN = 252.0
ZONES = [("asie", "Asie", 18 * 60, 2 * 60), ("europe", "Europe", 2 * 60, 8 * 60), ("ouverture", "Ouverture US", 8 * 60, 10 * 60 + 30),
         ("seance", "Seance US", 10 * 60 + 30, 15 * 60), ("cloture", "Cloture US", 15 * 60, 16 * 60),
         ("apres", "Apres la cloture", 16 * 60, 17 * 60)]


def _essais() -> int:
    from .tableau import ESSAIS_PROGRAMME
    return ESSAIS_PROGRAMME


def _js(x):
    if isinstance(x, dict):
        return {k: _js(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [_js(v) for v in x]
    if isinstance(x, (np.floating, float)):
        return None if not math.isfinite(float(x)) else round(float(x), 6)
    if isinstance(x, (np.integer,)):
        return int(x)
    if isinstance(x, (np.bool_,)):
        return bool(x)
    if isinstance(x, (pd.Timestamp, datetime)):
        return x.strftime("%Y-%m-%d %H:%M")
    return x


# =============================================================================
#  Etat (labo.json) et journal
# =============================================================================
def etat() -> dict:
    if os.path.exists(FICHIER):
        with open(FICHIER, encoding="utf-8") as fh:
            return json.load(fh)
    return dict(genere=None, en_cours=None, journal=[], strategies=[], combinaison=None, par_zone={},
                zones=[dict(code=c, nom=n, debut=a, fin=b) for c, n, a, b in ZONES],
                criteres=dict(heures_max=PC.HEURES_MAX, corr_max=PC.CORR_MAX, conflit_max=PC.CONFLIT_MAX, taille_max=PC.TAILLE_MAX))


def ecrire(e: dict) -> None:
    os.makedirs(DONNEES, exist_ok=True)
    e["genere"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    e["essais_programme"] = _essais()
    tmp = FICHIER + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(_js(e), fh, ensure_ascii=False, separators=(",", ":"))
    os.replace(tmp, FICHIER)


def journal(msg: str, e: dict | None = None, ecrit: bool = True) -> dict:
    e = e or etat()
    e["journal"] = (e.get("journal") or [])[-299:] + [dict(t=datetime.now().strftime("%H:%M:%S"), msg=msg)]
    print(f"[labo] {msg}", flush=True)
    if ecrit:
        ecrire(e)
    return e


def debut(code: str, titre: str, etape: str = "protocole ecrit, calcul en cours") -> None:
    e = etat()
    e["en_cours"] = dict(code=code, titre=titre, etape=etape, depuis=datetime.now().strftime("%H:%M:%S"))
    journal(f"{code} : {titre} - {etape}", e)


def fin() -> None:
    e = etat()
    e["en_cours"] = None
    ecrire(e)


# =============================================================================
#  Evaluation vectorbt d une liste de trades
# =============================================================================
def portefeuille(trades: pd.DataFrame, cout: float):
    """trades : t_in, t_out (UTC naif), sens (+1 / -1), r (rendement brut du prix entre l entree et la sortie).
    -> vbt.Portfolio : prix synthetiques (1 a l entree, 1 + r a la sortie), exposition cible sens x 100 % puis 0, frais =
    cout par cote. Les positions ne se chevauchent pas (une sortie avant l entree suivante)."""
    import vectorbt as vbt
    t = trades.sort_values("t_in").reset_index(drop=True)
    t_in = pd.DatetimeIndex(t.t_in)
    t_out = pd.DatetimeIndex(t.t_out)
    chev = t_in[1:] <= t_out[:-1]
    if chev.any():
        raise ValueError(f"{int(chev.sum())} trades se chevauchent")
    idx = t_in.append(t_out)
    prix = np.r_[np.ones(len(t)), 1.0 + t.r.to_numpy(float)]
    taille = np.r_[t.sens.to_numpy(float), np.zeros(len(t))]
    o = np.argsort(idx.asi8, kind="stable")
    idx, prix, taille = idx[o], prix[o], taille[o]
    dup = np.r_[False, idx.asi8[1:] == idx.asi8[:-1]]          # sortie et entree a la meme minute : entree 1 ns apres
    if dup.any():
        idx = pd.DatetimeIndex(idx.asi8 + dup.astype(np.int64))
    close = pd.Series(prix, index=idx)
    return vbt.Portfolio.from_orders(close, size=pd.Series(taille, index=idx), size_type="targetpercent", direction="both",
                                     fees=cout, init_cash=1e6, freq="1min")


def serie_journaliere(pf, jours: pd.DatetimeIndex = JOURS) -> pd.Series:
    v = pf.value()
    d = pd.DatetimeIndex(v.index).tz_localize("UTC").tz_convert(NY).tz_localize(None).normalize()
    j = pd.Series(v.to_numpy(), index=d).groupby(level=0).last()
    j = j.reindex(j.index.union(jours)).ffill().fillna(1e6).reindex(jours)
    return j.pct_change().fillna(0.0)


def profil(pos: pd.DataFrame, fin_donnees: pd.Timestamp, jours_profil: int = 365) -> np.ndarray:
    from .profil_horaire import occupation
    jours = pd.bdate_range(fin_donnees - pd.Timedelta(days=jours_profil - 1), fin_donnees)
    occ = occupation(pos, jours)
    return occ.mean(axis=0) if len(jours) else np.zeros(48)


def occupation_an(pos: pd.DataFrame, fin_donnees: pd.Timestamp, jours_profil: int = 366) -> dict:
    """{date : [demi-heures en position]} sur la derniere annee (jours actifs seulement) : vue du mois de la page."""
    from .profil_horaire import occupation
    jours = pd.date_range(fin_donnees - pd.Timedelta(days=jours_profil - 1), fin_donnees)
    occ = occupation(pos, jours)
    return {d.strftime("%Y-%m-%d"): [int(k) for k in np.flatnonzero(occ[i])] for i, d in enumerate(jours) if occ[i].any()}


def zone(pr: np.ndarray) -> str:
    masse = {}
    for c, _, a, b in ZONES:
        k = [(m // 30) for m in range(0, 1440, 30) if ((a <= m < b) if a < b else (m >= a or m < b))]
        masse[c] = float(np.sum(pr[k]))
    return max(masse, key=masse.get) if max(masse.values()) > 0 else "?"


def heures_an(pos: pd.DataFrame, r: pd.Series) -> float:
    if not len(pos):
        return math.nan
    h = float(np.sum(np.asarray((pd.DatetimeIndex(pos["fin"]) - pd.DatetimeIndex(pos["debut"])).total_seconds(), float))) / 3600
    ans = max((r.index[-1] - r.index[0]).days / 365.25, 0.5)
    return h / ans


def evaluer(trades: pd.DataFrame, cout: float, essais: int | None = None):
    """-> (statistiques vectorbt, serie journaliere, positions, rendements nets par trade vectorbt)."""
    pf = portefeuille(trades, cout)
    r = serie_journaliere(pf)
    m = PC.mesures(r, essais or _essais())
    tr = pf.trades.records_readable
    net = pd.Series(tr["Return"].to_numpy(float), index=pd.DatetimeIndex(tr["Exit Timestamp"]).tz_localize("UTC").tz_convert(NY).tz_localize(None).normalize())
    net.index = net.index + pd.to_timedelta(np.arange(len(net)) % 1000, unit="ns")
    pos = pd.DataFrame(dict(debut=pd.DatetimeIndex(trades.t_in), fin=pd.DatetimeIndex(trades.t_out)))
    actifs = r[r != 0]
    rr = r.loc[actifs.index[0]:] if len(actifs) else r
    h = heures_an(pos, rr)
    m.update(trades=int(len(tr)), heures_an=h, par_100h=m["sharpe"] * 0.10 / h * 100 if h and math.isfinite(h) and h > 0 else math.nan,
             courte=bool(math.isfinite(h) and h <= PC.HEURES_MAX))
    return m, r, pos, net


# =============================================================================
#  Registre des strategies et combinaison
# =============================================================================
def _sauver_serie(i: str, r: pd.Series, pos: pd.DataFrame) -> None:
    os.makedirs(CACHE, exist_ok=True)
    f = os.path.join(CACHE, "rendements.parquet")
    R = pd.read_parquet(f) if os.path.exists(f) else pd.DataFrame(index=JOURS)
    R[i] = r.reindex(R.index)
    R.to_parquet(f)
    pos.to_parquet(os.path.join(CACHE, f"pos_{i}.parquet"))


def surveillance(entree: dict, pos: pd.DataFrame, r: pd.Series) -> None:
    """Fenetre (demi-heures ou la strategie peut etre en position), type de jours et heures de surveillance par an."""
    from .profil_horaire import occupation
    t = entree.get("type_jours") or ("evenements" if entree["id"] in EVENEMENTIELLES else "tous")
    jours = pd.bdate_range(r.index[0], r.index[-1])
    occ = occupation(pos, jours)
    fen = [int(k) for k in np.flatnonzero(occ.mean(axis=0) > 0.002)] or [int(k) for k in np.flatnonzero(occ.any(axis=0))]
    ans = max((r.index[-1] - r.index[0]).days / 365.25, 0.5)
    jours_an = JOURS_BOURSE_AN if t == "tous" else float(occ.any(axis=1).sum()) / ans
    h = len(fen) * 0.5 * jours_an
    entree.update(type_jours=t, fenetre=fen, jours_par_an=round(jours_an, 1))
    st = entree["stats"]
    st.update(heures_surveillance=h, par_100h=st["sharpe"] * 0.10 / h * 100 if h > 0 and st.get("sharpe") is not None else math.nan,
              courte=bool(h <= PC.HEURES_MAX))


def enregistrer(e: dict, entree: dict, r: pd.Series | None = None, pos: pd.DataFrame | None = None, ecrit: bool = True) -> dict:
    """Ajoute (ou remplace) une strategie testee ; recalcule la combinaison si elle a une serie."""
    if r is not None and pos is not None:
        _sauver_serie(entree["id"], r, pos)
        entree["profil"] = [round(float(x), 4) for x in profil(pos, r.index[-1])]
        entree["occupation"] = occupation_an(pos, r.index[-1])
        entree["zone"] = zone(np.asarray(entree["profil"]))
        entree["serie"] = True
        surveillance(entree, pos, r)
    entree.setdefault("teste_le", datetime.now().strftime("%Y-%m-%d %H:%M"))
    e["strategies"] = [x for x in e.get("strategies", []) if x["id"] != entree["id"]] + [entree]
    if r is not None:
        combiner(e)
    if ecrit:
        ecrire(e)
    return e


def admissible(x: dict, seuil: float | None = PC.HEURES_MAX) -> bool:
    """Fiable, toujours vivante, et au plus `seuil` heures de surveillance par an (None : sans limite de temps)."""
    s = x.get("stats") or {}
    h = s.get("heures_surveillance")
    court = seuil is None or (h is not None and h <= seuil)
    return bool(x.get("serie") and s.get("fiable") and s.get("vivante") and court)


def combiner(e: dict) -> None:
    from .perso.portefeuille import Chevauchement, Strategie
    f = os.path.join(CACHE, "rendements.parquet")
    if not os.path.exists(f):
        return
    R = pd.read_parquet(f)
    tous = [x["id"] for x in e["strategies"] if admissible(x, None) and x["id"] in R.columns]
    ids = [x["id"] for x in e["strategies"] if admissible(x) and x["id"] in R.columns]
    e["admissibles"] = ids
    e["admissibles_par_seuil"] = {str(sl): [i for i in tous if admissible(next(x for x in e["strategies"] if x["id"] == i), sl)] for sl in SEUILS}
    e["seuils"] = [str(sl) for sl in SEUILS]
    e["par_zone"] = {}
    for c, _, _, _ in ZONES:
        cand = [x for x in e["strategies"] if admissible(x, None) and x.get("zone") == c]
        if cand:
            best = max(cand, key=lambda x: x["stats"]["ic_bas"])
            e["par_zone"][c] = best["id"]
    if not tous:
        e["ensembles"] = {}
        return
    X = R[tous].copy()
    for i in tous:                                                    # hors de sa periode, une strategie n existe pas
        nz = X[i][X[i] != 0]
        if len(nz):
            X.loc[X.index < nz.index[0], i] = np.nan
    pos = {i: pd.read_parquet(os.path.join(CACHE, f"pos_{i}.parquet")).assign(instrument=_instrument(e, i)) for i in tous}
    ch = Chevauchement([Strategie(i, X[i].fillna(0.0), pos[i]) for i in tous if len(pos[i])])
    conf = ch.part_conflit().reindex(index=tous, columns=tous).fillna(0.0)
    corr = X.corr(min_periods=120)
    vols = {i: float(X[i].std(ddof=1)) for i in tous}
    e["ensembles"] = {str(sl): ensemble(X, e["admissibles_par_seuil"][str(sl)], corr, conf, vols, e) for sl in SEUILS}
    if not ids:
        e["combinaison"], e["ensemble"] = None, e["ensembles"]["400"]
        e["correlation"] = dict(ids=tous, matrice=[[None if not math.isfinite(v) else round(float(v), 3) for v in row] for row in corr.to_numpy()])
        return
    combos = [c for c in PC.enumerer(ids, corr, conf) if c["corr_max"] <= PC.CORR_MAX and c["conflit_max"] <= PC.CONFLIT_MAX]
    essais = _essais() + len(combos)
    best = None
    for c in combos:
        s = PC.serie_combo(X, vols, c["ids"])
        if len(s) < PC.MIN_SEANCES:
            continue
        m = PC.mesures(s, essais, 300)
        if not (m["fiable"] and m["vivante"]):
            continue
        if best is None or m["ic_bas"] > best["ic_bas"]:
            hs = sum(next(x for x in e["strategies"] if x["id"] == i)["stats"].get("heures_surveillance") or 0.0 for i in c["ids"])
            best = dict(m, ids=list(c["ids"]), corr_max=c["corr_max"], conflit_max=c["conflit_max"], heures_an=hs,
                        par_100h=m["sharpe"] * 0.10 / hs * 100 if hs else math.nan)
    e["ensemble"] = e["ensembles"]["400"]
    if best is not None:                                              # IC plus precis pour la combinaison retenue
        s = PC.serie_combo(X, vols, best["ids"])
        best.update({k: v for k, v in PC.mesures(s, essais).items() if k in ("ic_bas", "ic_haut", "dsr")})
    e["combinaison"] = best
    e["correlation"] = dict(ids=tous, matrice=[[None if not math.isfinite(v) else round(float(v), 3) for v in row] for row in corr.to_numpy()])
    e["combinaisons_essayees"] = len(combos)


def ensemble(X: pd.DataFrame, ids: list, corr: pd.DataFrame, conf: pd.DataFrame, vols: dict, e: dict) -> dict | None:
    """Le PLUS GRAND groupe de strategies admissibles deux a deux non correlees (|correlation| <= CORR_MAX) et sans
    conflit de contrat (<= CONFLIT_MAX) ; a nombre egal, la meilleure borne basse d IC du groupe. Recherche exhaustive
    jusqu a 18 candidates, gloutonne au-dela (par borne basse d IC decroissante)."""
    import itertools
    if not ids:
        return None
    ok = lambda a, b: (not math.isfinite(corr.loc[a, b]) or abs(corr.loc[a, b]) <= PC.CORR_MAX) and conf.loc[a, b] <= PC.CONFLIT_MAX
    ic = {i: next(x for x in e["strategies"] if x["id"] == i)["stats"]["ic_bas"] for i in ids}
    groupes = []
    if len(ids) <= 18:
        for k in range(len(ids), 0, -1):
            groupes = [g for g in itertools.combinations(ids, k) if all(ok(a, b) for a, b in itertools.combinations(g, 2))]
            if groupes:
                break
    else:
        g = []
        for i in sorted(ids, key=lambda i: -ic[i]):
            if all(ok(i, j) for j in g):
                g.append(i)
        groupes = [tuple(g)]
    essais = _essais() + len(groupes)
    best = None
    for g in groupes:
        s = PC.serie_combo(X, vols, g)
        if len(s) < PC.MIN_SEANCES:
            continue
        m = PC.mesures(s, essais, 300)
        if best is None or m["ic_bas"] > best["ic_bas"]:
            best = dict(m, ids=list(g))
    if best is None:
        return None
    s = PC.serie_combo(X, vols, best["ids"])
    best.update({k: v for k, v in PC.mesures(s, essais).items() if k in ("ic_bas", "ic_haut", "dsr")})
    paires = list(itertools.combinations(best["ids"], 2))
    hs = sum(next(x for x in e["strategies"] if x["id"] == i)["stats"].get("heures_surveillance") or 0.0 for i in best["ids"])
    best.update(corr_max=max((abs(corr.loc[a, b]) for a, b in paires if math.isfinite(corr.loc[a, b])), default=0.0),
                heures_an=hs, par_100h=best["sharpe"] * 0.10 / hs * 100 if hs else math.nan, groupes_essayes=len(groupes))
    return best


def _instrument(e: dict, i: str) -> str:
    x = next(x for x in e["strategies"] if x["id"] == i)
    return (x.get("instruments") or ["?"])[0]


# =============================================================================
#  Remplissage initial : strategies du tableau de bord et hypotheses deja testees
# =============================================================================
def remplir(log=print) -> dict:
    from .tableau import positions_fiche
    e = etat()
    e = journal("remplissage : strategies futures intraday du tableau de bord et hypotheses deja testees", e, ecrit=False)
    with open(os.path.join(DONNEES, "prop.json"), encoding="utf-8") as fh:
        prop = json.load(fh)
    for c in prop["candidats"]:
        with open(os.path.join(DONNEES, f"{c['id']}.json"), encoding="utf-8") as fh:
            f = json.load(fh)
        ser = f["series"]
        r = pd.Series(ser["rendement"], index=pd.DatetimeIndex(ser["dates"]), dtype=float).fillna(0.0)
        pos = positions_fiche(f)[["debut", "fin"]]
        m = PC.mesures(r, _essais())
        h = heures_an(pos, r)
        m.update(trades=int((f.get("kpi") or {}).get("trades") or len(pos)), heures_an=h,
                 par_100h=m["sharpe"] * 0.10 / h * 100 if h and math.isfinite(h) and h > 0 else math.nan,
                 courte=bool(math.isfinite(h) and h <= PC.HEURES_MAX))
        src = (f.get("sources") or [{}])[0]
        statut = "retenue" if f.get("statut") == "validee" else ("fiable" if m["fiable"] else "rejetee")
        enregistrer(e, dict(id=c["id"], nom=f["titre"], hypothese=f.get("resume", "")[:300], source=src.get("titre"), lien=src.get("lien"),
                            origine="tableau de bord", instruments=c.get("instruments") or f.get("instruments"), statut=statut, stats=m),
                    r, pos, ecrit=False)
    with open(os.path.join(ICI, "..", "recherche", "resultats_60.json"), encoding="utf-8") as fh:
        etudes = json.load(fh)
    for k, v in etudes.items():
        if not k.startswith("creneaux_") or not isinstance(v, dict):
            continue
        st = (v.get("strategies") or {}).get("V") or {}
        statut = "retenue" if v.get("retenue") else ("fiable" if st.get("fiable") else "rejetee")
        if any(x["id"] == "H_" + v.get("code", k) for x in e["strategies"]):
            continue
        e["strategies"].append(dict(id="H_" + v.get("code", k), nom=f"{v.get('code', '')} {v.get('titre', '')}", hypothese=v.get("titre"),
                                    origine="lot creneaux (nexus/perso/creneaux.py)", heures=v.get("heures"), instruments=v.get("instruments"),
                                    statut=statut, stats=dict(sharpe=st.get("sharpe"), fiable=st.get("fiable")),
                                    teste_le=v.get("genere", "2026-10-19")))
    f = os.path.join(CACHE, "rendements.parquet")
    R = pd.read_parquet(f) if os.path.exists(f) else pd.DataFrame()
    for x in e["strategies"]:                                         # entrees deja testees : temps de surveillance a jour
        fp = os.path.join(CACHE, f"pos_{x['id']}.parquet")
        if x.get("serie") and x.get("origine") != "tableau de bord" and x["id"] in R.columns and os.path.exists(fp):
            r = R[x["id"]].dropna()
            surveillance(x, pd.read_parquet(fp), r)
    combiner(e)
    e["en_cours"] = None
    journal(f"remplissage termine : {len(e['strategies'])} strategies, {len(e.get('admissibles') or [])} admissibles "
            f"(fiables, vivantes, courtes)", e)
    return e


def main(argv=None):
    ap = argparse.ArgumentParser(description="laboratoire de recherche en direct (labo.json)")
    ap.add_argument("--remplir", action="store_true")
    a = ap.parse_args(argv)
    if a.remplir:
        remplir()


if __name__ == "__main__":
    main()
