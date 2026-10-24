"""Onglet « Prop firm » du tableau de bord : combinaisons de strategies futures intraday classees par FIABILITE.

Toutes les mesures viennent d objets vectorbt (accesseur de rendements .vbt.returns) construits sur les rendements
journaliers exportes par python -m nexus tableau ; rien n est repris d un autre calcul.

Pourquoi ce classement (demande du 2026-10-19 : « la combinaison la plus fiable, toujours fondee sur les statistiques
vectorbt ») : l ancienne recherche gardait les strategies au Sharpe brut >= 0,3 puis prenait, parmi des centaines de
combinaisons, celle qui avait le mieux reussi l evaluation sur le meme historique. C est un maximum choisi sur les
donnees memes qui servent a le juger : il surestime la reussite future. Ici :
  1. chaque strategie recoit ses statistiques vectorbt : Sharpe, Sortino, perte max, Sharpe de chaque moitie (avant /
     apres le 01/01/2021, les deux periodes de la methode de recherche), intervalle de confiance a 95 % du Sharpe
     (bootstrap : le Sharpe vectorbt de 1 000 tirages avec remise des seances), probabilite que le Sharpe vrai soit > 0
     et Sharpe deflate pour le nombre CUMULE d essais du programme ; elle est FIABLE si la borne basse de l IC est
     > 0 et si le Sharpe est positif sur les deux moities ;
  2. chaque combinaison (1 a 4 strategies, chacune ramenee au meme risque) est un portefeuille de rendements
     journaliers ; on mesure les memes statistiques, le Sharpe deflate comptant en plus toutes les combinaisons
     essayees ; le classement suit la BORNE BASSE de l IC du Sharpe : ce que l historique permet de garantir, pas le
     resultat le plus flatteur ;
  3. la methode de choix est elle-meme validee hors echantillon : choix sur 2016-2020 seulement (fiabilite des membres,
     correlations, IC, taille), puis resultat sur 2021-2026, compare a l ancienne methode (meilleur taux de reussite).
Sharpe deflate : variance des Sharpe sous l hypothese nulle (variance d echantillonnage du Sharpe estime, asymetrie
et queues comprises), comme dans tous les modules de la recherche (alternatives.dsr) ; la variance des Sharpe des
strategies exportees, dominee par quelques versions boguees tres negatives, rendait le seuil inatteignable.
"""
from __future__ import annotations

import itertools
import math
import warnings

import numpy as np
import pandas as pd
import vectorbt  # noqa: F401  (enregistre l accesseur pandas .vbt)

try:
    from numba import njit
except ImportError:  # pragma: no cover
    def njit(*a, **k):
        return (lambda f: f) if not a or not callable(a[0]) else a[0]

COUPURE = pd.Timestamp("2021-01-01")
SIGMA_REF = 0.01                 # a la taille x1, chaque strategie vaut 1 % du compte d ecart-type journalier
TAILLE_MAX = 4
CORR_MAX, CONFLIT_MAX = 0.3, 0.02
HEURES_MAX = math.inf            # plus de plafond d heures en position (critere 19 valide le 2026-10-21 ; c etait 400 h/an
                                 # depuis le 2026-10-20) : classement au rendement par heure, conflit de contrat <= CONFLIT_MAX
# Seules les strategies qui passent les 24 criteres de la methode (CLAUDE.md, valides le 2026-10-21) entrent dans les
# combinaisons ; les autres restent affichees. Source : tableau « Ce qui tient » de CLAUDE.md et les verdicts des modules.
RETENUES_METHODE = frozenset({
    "S1_NoiseAreaNQ",                                                   # validee le 2026-10-15, deflate 0,96
    "Gotobi_6J",                                                        # deflate 0,97 ; en 6J (le micro MJY echoue)
    "R_boombitch_taille_inverse_a_la_volatilite_conforme_a_la_seanc",  # H5 de creneaux.py : RETENUE (Welch 2,81)
})
B_BOOT, B_BOOT_WF = 1000, 500
SEED = 11
MIN_SEANCES = 250


# =============================================================================
#  Statistiques vectorbt
# =============================================================================
def _acc(r: pd.Series):
    return r.vbt.returns(freq="1D", year_freq="252 days")


def sharpe(r: pd.Series) -> float:
    if len(r) < 60 or not np.isfinite(r).all() or r.std() == 0:
        return math.nan
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return float(_acc(r).sharpe_ratio())


def var_nulle_ann(r: pd.Series) -> float:
    """Variance (annualisee) du Sharpe estime sous l hypothese nulle : (1 - g3 SR + (g4 - 1) / 4 SR^2) / (n - 1) par
    seance, x 252 ; c est la variance des essais utilisee par nexus.validation.deflated_sharpe et alternatives.dsr."""
    x = r.to_numpy(float)
    n = len(x)
    sd = x.std(ddof=1)
    if n < 10 or sd <= 0:
        return math.nan
    sr = x.mean() / sd
    from scipy import stats as SS
    g3, g4 = SS.skew(x), SS.kurtosis(x, fisher=False)
    return 252.0 * max(1e-12, (1 - g3 * sr + (g4 - 1) / 4.0 * sr * sr) / (n - 1))


def dsr(r: pd.Series, essais: int) -> float:
    """Sharpe deflate vectorbt pour `essais` essais, variance nulle des essais."""
    v = var_nulle_ann(r)
    if not math.isfinite(v):
        return math.nan
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return float(_acc(r).deflated_sharpe_ratio(var_sharpe=v, nb_trials=int(essais)))


def psr0(r: pd.Series) -> float:
    """Probabilite que le Sharpe vrai soit > 0 (Sharpe probabiliste, asymetrie et queues comprises)."""
    from scipy import stats as SS
    x = r.to_numpy(float)
    n = len(x)
    if n < 10 or x.std(ddof=1) <= 0:
        return math.nan
    sr = x.mean() / x.std(ddof=1)
    g3, g4 = SS.skew(x), SS.kurtosis(x, fisher=False)
    den = math.sqrt(max(1e-12, 1 - g3 * sr + (g4 - 1) / 4.0 * sr * sr))
    return float(SS.norm.cdf(sr * math.sqrt(n - 1) / den))


def ic_sharpe(r: pd.Series, b: int = B_BOOT, seed: int = SEED) -> tuple[float, float]:
    """IC 95 % du Sharpe : Sharpe vectorbt de b tirages avec remise des seances (centiles 2,5 et 97,5)."""
    x = r.to_numpy(float)
    n = len(x)
    if n < 60 or x.std() == 0:
        return math.nan, math.nan
    rng = np.random.default_rng(seed)
    m = x[rng.integers(0, n, size=(n, b))]
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        s = pd.DataFrame(m, index=r.index).vbt.returns(freq="1D", year_freq="252 days").sharpe_ratio().to_numpy(float)
    s = s[np.isfinite(s)]
    return float(np.quantile(s, 0.025)), float(np.quantile(s, 0.975))


def mesures(r: pd.Series, essais: int, b: int = B_BOOT) -> dict:
    """Toutes les statistiques d une serie de rendements journaliers (strategie seule ou combinaison)."""
    r = r.dropna()
    acc = _acc(r)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        sortino, dd = float(acc.sortino_ratio()), float(acc.max_drawdown())
        ann, vol = float(acc.annualized()), float(acc.annualized_volatility())
    p1, p2 = r[r.index < COUPURE], r[r.index >= COUPURE]
    lo, hi = ic_sharpe(r, b)
    sh1, sh2 = sharpe(p1), sharpe(p2)
    # « toujours vivante » (demande du 2026-10-20) : Sharpe vectorbt des 12 et des 24 derniers mois de donnees
    sh12 = sharpe(r[r.index > r.index[-1] - pd.Timedelta(days=365)])
    sh24 = sharpe(r[r.index > r.index[-1] - pd.Timedelta(days=730)])
    return dict(n=int(len(r)), debut=r.index[0].strftime("%Y-%m-%d"), fin=r.index[-1].strftime("%Y-%m-%d"),
                sharpe=sharpe(r), sortino=sortino, perte_max=dd, rendement_annuel=ann, volatilite=vol,
                sharpe_p1=sh1, sharpe_p2=sh2, ic_bas=lo, ic_haut=hi, psr=psr0(r), dsr=dsr(r, essais),
                sharpe_12m=sh12, sharpe_24m=sh24, vivante=bool(math.isfinite(sh24) and sh24 > 0),
                fiable=bool(math.isfinite(lo) and lo > 0 and math.isfinite(sh1) and sh1 > 0 and math.isfinite(sh2) and sh2 > 0))


# =============================================================================
#  Combinaisons
# =============================================================================
def serie_combo(R: pd.DataFrame, vols: dict, ids) -> pd.Series:
    """Moyenne des strategies ramenees au meme risque, sur les seances ou TOUTES existent."""
    X = R[list(ids)].dropna()
    w = np.array([SIGMA_REF / vols[i] for i in ids])
    return pd.Series((X.to_numpy() * w).mean(axis=1), index=X.index)


def enumerer(ids: list, corr: pd.DataFrame, conf: pd.DataFrame, kmax: int = TAILLE_MAX) -> list[dict]:
    out = []
    for k in range(1, kmax + 1):
        for cb in itertools.combinations(ids, k):
            paires = list(itertools.combinations(cb, 2))
            cmax = max((abs(corr.loc[a, b]) for a, b in paires if pd.notna(corr.loc[a, b])), default=0.0)
            fmax = max((conf.loc[a, b] for a, b in paires), default=0.0)
            out.append(dict(ids=list(cb), corr_max=float(cmax), conflit_max=float(fmax)))
    return out


@njit(cache=True)
def _evaluer(x, k, objectif, perte, dd, horizon):
    """Evaluation prop rejouee depuis chaque seance (memes regles que nexus/perso/portefeuille.py et prop.js)."""
    n = len(x) - horizon
    if n < 20:
        return np.nan, np.nan, np.nan
    ok = 0
    ko = 0
    for s in range(n):
        cum = 0.0
        pic = 0.0
        for t in range(horizon):
            v = x[s + t] * k
            cum += v
            if cum > pic:
                pic = cum
            if cum < min(pic, dd) - dd or v < -perte:
                ko += 1
                break
            if cum >= objectif:
                ok += 1
                break
    return ok / n, ko / n, (n - ok - ko) / n


def meilleure_taille(x: np.ndarray, regles: dict, mults) -> tuple[float, float]:
    """Taille (multiplicateur) au meilleur taux de reussite -> (taille, reussite)."""
    best = (mults[0], -1.0)
    for k in mults:
        rs, _, _ = _evaluer(x, float(k), float(regles["objectif"]), float(regles["perte_jour"]), float(regles["dd"]), int(regles["horizon"]))
        if np.isfinite(rs) and rs > best[1]:
            best = (k, rs)
    return best


def reussite(x: np.ndarray, k: float, regles: dict) -> float:
    rs, _, _ = _evaluer(x, float(k), float(regles["objectif"]), float(regles["perte_jour"]), float(regles["dd"]), int(regles["horizon"]))
    return float(rs)


# =============================================================================
#  Validation de la methode de choix (choix sur 2016-2020, resultat sur 2021-2026)
# =============================================================================
def validation_choix(R: pd.DataFrame, positions_conf: pd.DataFrame, regles: dict, mults, essais: int, log=print,
                     autorises=None) -> dict:
    A = R[R.index < COUPURE]
    Bp = R[R.index >= COUPURE]
    ids_a = [i for i in R.columns if A[i].notna().sum() >= MIN_SEANCES and Bp[i].notna().sum() >= MIN_SEANCES
             and (autorises is None or i in autorises)]
    vols = {i: float(A[i].std(ddof=1)) for i in ids_a}
    corr_a = A[ids_a].corr(min_periods=120)
    out = {}
    # methode fiable : membres a l IC > 0 sur 2016-2020, combinaison a la meilleure borne basse d IC sur 2016-2020
    fiables = [i for i in ids_a if ic_sharpe(A[i].dropna(), B_BOOT_WF)[0] > 0]
    # ancienne methode : membres au Sharpe >= 0,3 sur 2016-2020, combinaison au meilleur taux de reussite sur 2016-2020
    anciens = [i for i in ids_a if sharpe(A[i].dropna()) >= 0.3]
    for nom, membres, critere in (("fiable", fiables, "ic"), ("ancienne", anciens, "reussite")):
        combos = [c for c in enumerer(membres, corr_a, positions_conf.loc[membres, membres] if membres else positions_conf, TAILLE_MAX)
                  if c["corr_max"] <= CORR_MAX and c["conflit_max"] <= CONFLIT_MAX]
        meilleur = None
        for c in combos:
            sa = serie_combo(A, vols, c["ids"])
            if len(sa) < MIN_SEANCES:
                continue
            if critere == "ic":
                score = ic_sharpe(sa, B_BOOT_WF)[0]
            else:
                score = meilleure_taille(regles["compte"] * sa.to_numpy(), regles, mults)[1]
            if math.isfinite(score) and (meilleur is None or score > meilleur[0]):
                meilleur = (score, c, sa)
        if meilleur is None:
            out[nom] = dict(membres=len(membres), combinaisons=len(combos), choix=None)
            continue
        score, c, sa = meilleur
        k, rs_a = meilleure_taille(regles["compte"] * sa.to_numpy(), regles, mults)
        sb = serie_combo(Bp, vols, c["ids"])
        out[nom] = dict(membres=len(membres), combinaisons=len(combos), choix=c["ids"], score=score, taille=k,
                        sharpe_a=sharpe(sa), reussite_a=rs_a, sharpe_b=sharpe(sb), ic_b=list(ic_sharpe(sb, B_BOOT_WF)),
                        reussite_b=reussite(regles["compte"] * sb.to_numpy(), k, regles), perte_max_b=float(_acc(sb).max_drawdown()),
                        seances_b=int(len(sb)))
        log(f"  validation du choix ({nom}) : {c['ids']} -> Sharpe 2021-2026 {out[nom]['sharpe_b']:.2f}")
    out["regles"] = dict(regles)
    return out


# =============================================================================
#  Annexe complete
# =============================================================================
def analyser(R: pd.DataFrame, corr: pd.DataFrame, conf: pd.DataFrame, essais: int, regles_ref: dict, mults, log=print,
             heures: dict | None = None, retenues=RETENUES_METHODE, essais_membres: dict | None = None) -> dict:
    """R : rendements journaliers des candidates (NaN hors de leur periode). -> statistiques des strategies, de toutes
    les combinaisons, recommandation et validation du choix. heures : heures en position par an de chaque candidate ;
    seules les strategies courtes (<= HEURES_MAX) et retenues par la methode (`retenues`, None : toutes) entrent dans
    les combinaisons et la validation. essais_membres : nombre d essais propre a une strategie (fige a sa date de
    validation), sinon `essais` ; les combinaisons gardent `essais` + leur nombre."""
    ids = list(R.columns)
    h = heures or {}
    membres = {i: mesures(R[i], (essais_membres or {}).get(i, essais)) for i in ids}
    for i in ids:
        hi = h.get(i, math.nan)
        membres[i].update(heures_an=hi, courte=bool(heures is None or (math.isfinite(hi) and hi <= HEURES_MAX)),
                          retenue=bool(retenues is None or i in retenues),
                          par_100h=membres[i]["sharpe"] * 0.10 / hi * 100 if math.isfinite(hi) and hi > 0 else math.nan)
    vols = {i: float(R[i].std(ddof=1)) for i in ids}
    pool = [i for i in ids if math.isfinite(membres[i]["sharpe"]) and membres[i]["sharpe"] > 0 and membres[i]["courte"]
            and membres[i]["retenue"]]
    combos = enumerer(pool, corr, conf)
    n_essais = essais + len(combos)
    log(f"  prop : {len(ids)} candidates, {len(pool)} au Sharpe > 0, {len(combos)} combinaisons (essais comptes : {n_essais})")
    lignes = []
    for c in combos:
        s = serie_combo(R, vols, c["ids"])
        if len(s) < MIN_SEANCES:
            continue
        m = mesures(s, n_essais)
        m.update(c, membres_fiables=int(sum(membres[i]["fiable"] for i in c["ids"])))
        hs = float(sum(h.get(i, math.nan) for i in c["ids"]))
        m.update(heures_an=hs, par_100h=m["sharpe"] * 0.10 / hs * 100 if math.isfinite(hs) and hs > 0 else math.nan)
        lignes.append(m)
    lignes.sort(key=lambda m: -(m["ic_bas"] if math.isfinite(m["ic_bas"]) else -99))
    ok = lambda m: m["corr_max"] <= CORR_MAX and m["conflit_max"] <= CONFLIT_MAX
    vivants = lambda m: m["vivante"] and all(membres[i]["vivante"] for i in m["ids"])
    reco = next((m for m in lignes if ok(m) and m["fiable"] and m["membres_fiables"] == len(m["ids"]) and vivants(m)), None)
    if reco is not None:
        s = serie_combo(R, vols, reco["ids"])
        k, rs = meilleure_taille(regles_ref["compte"] * s.to_numpy(), regles_ref, mults)
        reco = dict(ids=reco["ids"], taille=k, reussite=rs, regles=regles_ref)
    val = validation_choix(R, conf, regles_ref, mults, essais, log, autorises=set(pool) if heures is not None or retenues is not None else None)
    return dict(membres=membres, combinaisons=lignes, recommandee=reco, validation=val, essais_combinaisons=n_essais,
                filtres=dict(corr_max=CORR_MAX, conflit_max=CONFLIT_MAX, taille_max=TAILLE_MAX,
                             heures_max=HEURES_MAX if math.isfinite(HEURES_MAX) else None,
                             retenues=sorted(retenues) if retenues is not None else None),
                coupure=COUPURE.strftime("%Y-%m-%d"),
                bootstrap=B_BOOT)
