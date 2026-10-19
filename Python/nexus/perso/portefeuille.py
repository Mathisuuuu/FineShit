"""Choix d un groupe de strategies futures pour un compte de prop firm.

    Diversification  correlations des P&L quotidiens (globale, sur les jours de baisse, glissante sur 1 an),
                     ratio de diversification, selection gloutonne de strategies peu correlees.
    Chevauchement    temps en position (tranches de 15 min), chevauchement dans le temps, CONFLITS DE CONTRAT
                     (deux strategies sur le meme contrat au meme moment : sur un compte unique, les positions
                     s additionnent ou s annulent), profil horaire, groupe sans chevauchement.
    taille_prop      mise a la taille d un compte prop : contrat standard -> micro (1/10, FDAX -> FDXS 1/25),
                     strategies dimensionnees en capital ramenees au compte (alerte si moins d un micro).
    regle_prop       perte journaliere max et drawdown suiveur (fin de journee) sur le P&L combine.
    meilleurs_groupes  recherche exhaustive des groupes sans conflit de contrat et peu correles, classes par Sharpe.

    python -m nexus.perso.portefeuille [--compte 50000] [--perte-jour 1000] [--dd-suiveur 2000]
                                       [--seuil-sharpe 0.3] [--seuil-correlation 0.3] [--tolerance-conflit 0.02]

Sources : equity_*.csv et trades_*.csv ecrits par nexus.perso.runner (dernier run de chaque strategie).
Seules les strategies executables en FUTURES sont candidates (une prop firm futures ne trade ni actions ni options).
"""
from __future__ import annotations

import argparse
import glob
import itertools
import math
import os
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from .qf import INSTRUMENTS
from .runner import PY_DIR, TESTS
from .statistiques import durees_trades, fmt_duree

FUTURES_ROOTS = {"ES", "NQ", "YM", "GC", "CL", "6E", "6B", "6J", "6A", "FDAX", "IWM"}    # IWM : substitut du future RTY
S20_LEGS = ["ES", "GC", "CL", "6E"]
MICRO = {"ES": "MES", "NQ": "MNQ", "YM": "MYM", "GC": "MGC", "CL": "MCL", "6E": "M6E", "6B": "M6B", "6A": "M6A", "6J": "MJY",
         "IWM": "M2K"}


def _safe(name: str) -> str:
    return "".join(ch if ch.isalnum() else "_" for ch in name)[:60]


def _latest(prefix: str, name: str) -> str | None:
    files = glob.glob(os.path.join(PY_DIR, "resultats", "perso_*", f"{prefix}_*_{_safe(name)}.csv"))
    return max(files, key=lambda f: os.path.basename(os.path.dirname(f))) if files else None


def _is_futures(spec: dict) -> bool:
    k = spec["kind"]
    if k in ("qf", "user"):
        src = spec.get("root") or spec.get("src")
        return src in FUTURES_ROOTS or src == "DAXCASH"
    if k in ("pairs", "s20", "orderflow", "fx", "gotobi", "or"):
        return True
    return k == "nexus" and spec.get("profile") == "futures"


@dataclass
class Strategie:
    nom: str
    pnl: pd.Series                                   # P&L quotidien en $ (taille du backtest)
    positions: pd.DataFrame                          # debut, fin (UTC naif), instrument
    instruments: set = field(default_factory=set)
    spec: dict = field(default_factory=dict)
    qte_moy: float = math.nan                        # contrats moyens par trade (taille du backtest)
    capital: float = 100000.0                        # capital de depart du backtest (premier point d equity)

    @property
    def sharpe(self) -> float:
        d = self.pnl
        sd = d.std(ddof=1)
        return float(d.mean() / sd * math.sqrt(252)) if len(d) > 2 and sd > 0 else math.nan

    @property
    def net(self) -> float:
        return float(self.pnl.sum())

    def moities(self) -> tuple[float, float]:
        return float(self.pnl[self.pnl.index < "2021-01-01"].sum()), float(self.pnl[self.pnl.index >= "2021-01-01"].sum())

    def max_dd(self) -> float:
        eq = self.pnl.cumsum()
        return float((eq.cummax() - eq).max())


MANQUANTES: list[str] = []


def charger(seulement_futures: bool = True) -> list[Strategie]:
    out = []
    MANQUANTES.clear()
    for name, src, spec, note in TESTS:
        if seulement_futures and not _is_futures(spec):
            continue
        fe, ft = _latest("equity", name), _latest("trades", name)
        if fe is None:
            MANQUANTES.append(name)
            continue
        eq = pd.read_csv(fe, index_col=0, parse_dates=True).iloc[:, 0]
        eq.index = pd.DatetimeIndex(eq.index).normalize()
        eq = eq.groupby(level=0).last()
        pnl = eq.diff().fillna(0.0)
        # jours de week-end (anciens fichiers dates au jour calendaire) : dimanche soir -> seance du lundi, samedi -> vendredi
        dow = pnl.index.dayofweek
        pnl = pnl.groupby(pnl.index + pd.to_timedelta(np.where(dow == 6, 1, np.where(dow == 5, -1, 0)), unit="D")).sum()
        pos = pd.DataFrame(columns=["debut", "fin", "instrument"])
        qte = math.nan
        if spec["kind"] == "s20":
            active = pnl[pnl != 0]
            if len(active):
                pos = pd.DataFrame([(active.index[0], pnl.index[-1] + pd.Timedelta(days=1), leg) for leg in S20_LEGS],
                                   columns=["debut", "fin", "instrument"])
        elif ft is not None and os.path.getsize(ft) > 5:
            t = pd.read_csv(ft)
            if "entry_time" in t.columns and len(t):
                inst = t["instrument"] if "instrument" in t.columns else t.get("symbol", pd.Series([src] * len(t)))
                pos = pd.DataFrame({"debut": pd.to_datetime(t["entry_time"]), "fin": pd.to_datetime(t["exit_time"]),
                                    "instrument": inst.astype(str).str.upper()})
                qcol = "qty" if "qty" in t.columns else ("max_qty" if "max_qty" in t.columns else None)
                if qcol:
                    qte = float(pd.to_numeric(t[qcol], errors="coerce").abs().mean())
        out.append(Strategie(name, pnl, pos, set(pos["instrument"]) if len(pos) else set(), spec, qte, float(eq.iloc[0])))
    return out


# =============================================================================
#  Taille pour un compte de prop firm
# =============================================================================
def taille_prop(s: Strategie, compte: float) -> tuple[float, str, bool]:
    """-> (echelle a appliquer au P&L du backtest, description, deployable)."""
    k = s.spec.get("kind")
    if k in ("qf", "user"):
        inst = s.spec["inst"]
        root = INSTRUMENTS[inst].root
        if inst == "FDAX":
            return 1 / 25, "FDAX -> FDXS (1/25)", True
        if inst == root and root in MICRO:
            return 0.1, f"{inst} -> {MICRO[root]} (1/10), {s.qte_moy:.1f} contrat(s) en moyenne", True
        return 1.0, f"{inst}, {s.qte_moy:.1f} contrat(s) en moyenne", True
    if k == "pairs":
        return 1.0, "10 000 unites (~1 M6B)", True
    if k == "or":
        e = compte / 50000.0                          # 1R = 250 $ = 0,5 % d un compte de 50 000 $
        return e, f"1R = {250 * e:,.0f} $ en MGC".replace(",", " "), True
    if k in ("orderflow", "fx", "gotobi"):
        e = compte / 25000.0                          # 1R = 1 % du compte, comme le post (250 $ pour 25 000 $)
        return e, f"1R = {250 * e:,.0f} $ en micros".replace(",", " "), True
    if k == "s20":
        e = compte / 100000.0
        return e, f"capital 100 000 $ -> x{e:.2f}", e >= 1.0
    if k == "nexus":
        e = compte / 1_000_000.0
        q = s.qte_moy * e if math.isfinite(s.qte_moy) else math.nan
        return e, f"capital 1 M$ -> x{e:.3f} ({q:.1f} micro par position)", math.isfinite(q) and q >= 1.0
    return 1.0, "?", False


# =============================================================================
#  Diversification
# =============================================================================
class Diversification:
    def __init__(self, strategies: list[Strategie], echelles: dict | None = None):
        self.strats = strategies
        self.noms = [s.nom for s in strategies]
        m = pd.concat({s.nom: s.pnl * (echelles or {}).get(s.nom, 1.0) for s in strategies}, axis=1)
        for s in strategies:                      # hors de sa periode, une strategie n existe pas (NaN, pas zero)
            m.loc[(m.index < s.pnl.index.min()) | (m.index > s.pnl.index.max()), s.nom] = np.nan
        self.pnl = m.sort_index()

    def correlation(self) -> pd.DataFrame:
        return self.pnl.corr(min_periods=250)

    def correlation_baisse(self) -> pd.DataFrame:
        """Correlation sur les seuls jours ou la paire perd au total (risque de pertes simultanees)."""
        n = len(self.noms)
        c = np.full((n, n), np.nan)
        for i in range(n):
            for j in range(n):
                a, b = self.pnl.iloc[:, i], self.pnl.iloc[:, j]
                ok = a.notna() & b.notna() & ((a + b) < 0)
                if ok.sum() >= 100 and a[ok].std() > 0 and b[ok].std() > 0:
                    c[i, j] = np.corrcoef(a[ok], b[ok])[0, 1]
        return pd.DataFrame(c, index=self.noms, columns=self.noms)

    def correlation_glissante(self, jours: int = 252) -> pd.DataFrame:
        rows = []
        for i, a in enumerate(self.noms):
            for b in self.noms[i + 1:]:
                r = self.pnl[a].rolling(jours, min_periods=jours // 2).corr(self.pnl[b]).dropna()
                if len(r):
                    rows.append((a, b, float(r.min()), float(r.max())))
        return pd.DataFrame(rows, columns=["A", "B", "corr_min_1an", "corr_max_1an"])

    def combine(self, noms: list[str] | None = None) -> pd.Series:
        """P&L quotidien du groupe, sur les jours ou au moins une de ses strategies existe."""
        return self.pnl[noms or self.noms].dropna(how="all").sum(axis=1)

    def ratio_diversification(self, noms: list[str] | None = None) -> float:
        noms = noms or self.noms
        m = self.pnl[noms].dropna()
        if len(m) < 50 or len(noms) < 2:
            return 1.0
        w = 1.0 / m.std()
        port = (m * w).sum(axis=1)
        return float((w * m.std()).sum() / port.std())

    def selection(self, seuil_correlation: float = 0.3) -> list[str]:
        corr = self.correlation()
        keep = []
        for s in sorted(self.strats, key=lambda s: -s.sharpe):
            if all(not (abs(corr.loc[s.nom, k]) >= seuil_correlation) for k in keep):
                keep.append(s.nom)
        return keep


# =============================================================================
#  Chevauchement
# =============================================================================
class Chevauchement:
    PAS = "15min"

    def __init__(self, strategies: list[Strategie]):
        self.strats = [s for s in strategies if len(s.positions)]
        self.noms = [s.nom for s in self.strats]
        t0 = min(s.positions["debut"].min() for s in self.strats).floor("D")
        t1 = max(s.positions["fin"].max() for s in self.strats).ceil("D")
        self.grille = pd.date_range(t0, t1, freq=self.PAS).as_unit("ns")
        self.occ, self.occ_inst = {}, {}
        g = self.grille.asi8
        for s in self.strats:
            tot = np.zeros(len(g), bool)
            for inst, grp in s.positions.groupby("instrument"):
                a = np.zeros(len(g) + 1, np.int32)
                i0 = np.searchsorted(g, pd.DatetimeIndex(grp["debut"]).as_unit("ns").asi8, "left")
                i1 = np.searchsorted(g, pd.DatetimeIndex(grp["fin"]).as_unit("ns").asi8, "left")
                np.add.at(a, i0, 1)
                np.add.at(a, i1, -1)
                occ = np.cumsum(a)[:-1] > 0
                self.occ_inst[(s.nom, inst)] = occ
                tot |= occ
            self.occ[s.nom] = tot

    def temps_en_position(self) -> pd.Series:
        return pd.Series({n: float(o.mean()) for n, o in self.occ.items()})

    def matrice(self) -> pd.DataFrame:
        """Part du temps en position de la moins exposee des deux pendant laquelle l autre l est aussi."""
        n = len(self.noms)
        m = np.zeros((n, n))
        for i, a in enumerate(self.noms):
            for j, b in enumerate(self.noms):
                den = min(self.occ[a].sum(), self.occ[b].sum())
                m[i, j] = (self.occ[a] & self.occ[b]).sum() / den if den else 0.0
        return pd.DataFrame(m, index=self.noms, columns=self.noms)

    def conflits_contrat(self) -> pd.DataFrame:
        """Paires en position au meme moment sur le meme contrat ; part = heures communes / temps en position de la
        moins exposee des deux."""
        rows = []
        for i, a in enumerate(self.noms):
            for b in self.noms[i + 1:]:
                common = {k[1] for k in self.occ_inst if k[0] == a} & {k[1] for k in self.occ_inst if k[0] == b}
                for inst in common:
                    both = int((self.occ_inst[(a, inst)] & self.occ_inst[(b, inst)]).sum())
                    if both:
                        den = min(self.occ[a].sum(), self.occ[b].sum())
                        rows.append((a, b, inst, both * 0.25, both / den if den else 0.0))
        return pd.DataFrame(rows, columns=["A", "B", "contrat", "heures_communes", "part"])

    def part_conflit(self) -> pd.DataFrame:
        """Matrice : part maximale de conflit de contrat par paire."""
        m = pd.DataFrame(0.0, index=self.noms, columns=self.noms)
        for r in self.conflits_contrat().itertuples():
            m.loc[r.A, r.B] = max(m.loc[r.A, r.B], r.part)
            m.loc[r.B, r.A] = m.loc[r.A, r.B]
        return m

    def profil_horaire(self) -> pd.DataFrame:
        et = self.grille.tz_localize("UTC").tz_convert("America/New_York").hour
        return pd.DataFrame({n: pd.Series(o).groupby(et).mean().values for n, o in self.occ.items()}, index=range(24)).T

    def groupe_sans_chevauchement(self, priorite: list[str], seuil: float = 0.10) -> list[str]:
        """Strict : jamais en position en meme temps (au-dela du seuil), quel que soit le contrat, et aucun conflit
        de contrat."""
        mat = self.matrice()
        conf = self.conflits_contrat()
        pairs_conf = {(r.A, r.B) for r in conf.itertuples()} | {(r.B, r.A) for r in conf.itertuples()}
        keep = []
        for n in priorite:
            if n in self.occ and all(mat.loc[n, k] <= seuil and (n, k) not in pairs_conf for k in keep):
                keep.append(n)
        return keep


# =============================================================================
#  Regles de prop firm (fin de journee)
# =============================================================================
def regle_prop(pnl: pd.Series, compte: float, perte_jour: float, dd_suiveur: float) -> dict:
    eq = compte + pnl.cumsum()
    pic = eq.cummax().clip(upper=compte + dd_suiveur)       # le seuil suiveur se bloque au capital de depart (usage courant)
    viol_dd = eq < pic - dd_suiveur
    viol_jour = pnl < -perte_jour
    v = viol_dd | viol_jour
    return dict(pire_jour=float(pnl.min()), jours_perte_max=int(viol_jour.sum()), violations_dd=int(viol_dd.sum()),
                premiere_violation=v.idxmax() if v.any() else None, dd_max=float((eq.cummax() - eq).max()),
                pnl_total=float(pnl.sum()))


def taille_max(pnl: pd.Series, compte: float, perte_jour: float, dd_suiveur: float, k_max: float = 50.0) -> float:
    """Plus grand multiplicateur de taille (1 = taille prop de base) sans aucune violation des regles sur l historique.
    Mesure EN ECHANTILLON : en pratique, n en utiliser qu une fraction (50 % conseille)."""
    def ok(k):
        return regle_prop(pnl * k, compte, perte_jour, dd_suiveur)["premiere_violation"] is None
    if ok(k_max):
        return k_max
    lo, hi = 0.0, k_max
    for _ in range(30):
        mid = 0.5 * (lo + hi)
        lo, hi = (mid, hi) if ok(mid) else (lo, mid)
    return lo


def _annees(pnl: pd.Series) -> float:
    return max(0.25, (pnl.index.max() - pnl.index.min()).days / 365.25)


MULTIPLICATEURS = (0.5, 1.0, 1.5, 2.0, 3.0, 4.0, 5.0, 6.0, 8.0, 10.0)


def evaluation_prop(pnl: pd.Series, compte: float, objectif: float, perte_jour: float, dd_suiveur: float,
                    horizon: int = 120) -> dict:
    """Rejoue une evaluation prop a partir de CHAQUE jour de l historique : reussie si le profit atteint l objectif
    avant toute violation (perte du jour > perte_jour, ou equity sous le seuil suiveur en fin de journee, seuil bloque
    au capital de depart), echouee si une violation arrive d abord, non conclue apres `horizon` jours de bourse.
    Les departs se recouvrent : c est une estimation, pas des essais independants."""
    x = pnl.to_numpy(dtype=float)
    n = len(x) - horizon                      # seulement les departs qui disposent de tout l horizon
    if n < 20:
        return dict(reussite=math.nan, echec=math.nan, non_conclu=math.nan, jours_median=math.nan, departs=0)
    ok = ko = 0
    jours = []
    for s in range(n):
        seg = x[s:s + horizon]
        cum = np.cumsum(seg)
        seuil = np.minimum(np.maximum.accumulate(np.maximum(cum, 0.0)), dd_suiveur) - dd_suiveur
        viol = np.flatnonzero((cum < seuil) | (seg < -perte_jour))
        gain = np.flatnonzero(cum >= objectif)
        iv = viol[0] if len(viol) else len(seg)
        if len(gain) and gain[0] < iv:
            ok += 1
            jours.append(gain[0] + 1)
        elif len(viol):
            ko += 1
    return dict(reussite=ok / n, echec=ko / n, non_conclu=(n - ok - ko) / n,
                jours_median=float(np.median(jours)) if jours else math.nan, departs=n,
                avantage=ok / (ok + ko) - dd_suiveur / (objectif + dd_suiveur) if ok + ko else math.nan)


def hasard_prop(objectif: float, dd_suiveur: float) -> float:
    """Probabilite de reussite d une marche aleatoire SANS avantage (atteindre +objectif avant -dd) : la reference
    a battre. Une grosse taille sur une strategie quelconque s en approche : c est du pile ou face, pas un avantage."""
    return dd_suiveur / (objectif + dd_suiveur)


def meilleure_taille_evaluation(pnl: pd.Series, compte: float, objectif: float, perte_jour: float, dd_suiveur: float,
                                horizon: int = 120, grille=MULTIPLICATEURS) -> tuple[float, dict, dict]:
    """Multiplicateur de la grille qui maximise le taux de reussite (a egalite : le plus rapide).
    -> (multiplicateur, resultat a ce multiplicateur, resultat a la taille de base x1)."""
    res = {k: evaluation_prop(pnl * k, compte, objectif, perte_jour, dd_suiveur, horizon) for k in grille}
    best = max(grille, key=lambda k: (res[k]["reussite"], -(res[k]["jours_median"] if math.isfinite(res[k]["jours_median"]) else 1e9)))
    base = res.get(1.0) or evaluation_prop(pnl, compte, objectif, perte_jour, dd_suiveur, horizon)
    return best, res[best], base


def retenir(toutes: list[Strategie], compte: float, seuil_sharpe: float = 0.3) -> list[dict]:
    """Toutes les strategies, de la meilleure a la pire (Sharpe), avec la decision pour ce compte :
    {strategie, echelle, description, raison} ; raison vide = retenue."""
    out = []
    noms = {s.nom for s in toutes}
    for s in sorted(toutes, key=lambda x: -(x.sharpe if math.isfinite(x.sharpe) else -9)):
        h1, h2 = s.moities()
        e, desc, deploy = taille_prop(s, compte)
        deux = s.pnl.index.min() < pd.Timestamp("2020-06-01")
        base = s.nom.split(" (tel que code)")[0]
        boguee = "(tel que code)" in s.nom and any(n.startswith(base + " (corrige") for n in noms)
        raison = ("version boguee (la version corrigee est evaluee)" if boguee
                  else "PnL negatif" if s.net <= 0 else f"Sharpe < {seuil_sharpe}" if not s.sharpe >= seuil_sharpe
                  else "une des deux periodes est negative" if (h2 <= 0 or (deux and h1 <= 0))
                  else "non deployable a cette taille de compte" if not deploy else "")
        out.append(dict(strategie=s, echelle=e, description=desc, raison=raison))
    return out


def groupes_admissibles(div: Diversification, chev: Chevauchement, noms: list[str], seuil_corr: float,
                        tol_conflit: float, taille_max_groupe: int = 6) -> list[tuple]:
    """Groupes de 2 a 6 strategies sans conflit de contrat (part <= tolerance) et peu correles deux a deux."""
    corr = div.correlation()
    conf = chev.part_conflit()
    return [g for k in range(2, min(taille_max_groupe, len(noms)) + 1) for g in itertools.combinations(noms, k)
            if not any(abs(corr.loc[a, b]) >= seuil_corr or conf.loc[a, b] > tol_conflit
                       for a, b in itertools.combinations(g, 2))]


def meilleurs_groupes(div: Diversification, chev: Chevauchement, noms: list[str], seuil_corr: float, tol_conflit: float,
                      compte: float, perte_jour: float, dd_suiveur: float, top: int = 6) -> list[dict]:
    """Groupes admissibles classes par PnL annuel a la taille conseillee (50 % de la taille max sans violation)."""
    res = []
    for g in groupes_admissibles(div, chev, noms, seuil_corr, tol_conflit):
        p = div.combine(list(g))
        sd = p.std()
        sh = p.mean() / sd * math.sqrt(252) if sd > 0 else math.nan
        rp = regle_prop(p, compte, perte_jour, dd_suiveur)
        km = taille_max(p, compte, perte_jour, dd_suiveur)
        res.append(dict(groupe=g, sharpe=sh, pnl=float(p.sum()), dd=float((p.cumsum().cummax() - p.cumsum()).max()),
                        pire_jour=rp["pire_jour"], ok_prop=rp["premiere_violation"] is None, premiere=rp["premiere_violation"],
                        ratio_div=div.ratio_diversification(list(g)), k_max=km,
                        pnl_an_conseille=float(p.sum()) * 0.5 * km / _annees(p)))
    res.sort(key=lambda r: -r["pnl_an_conseille"])
    return res[:top]


# =============================================================================
#  Rapport
# =============================================================================
def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--compte", type=float, default=50000.0)
    ap.add_argument("--perte-jour", type=float, default=1000.0)
    ap.add_argument("--dd-suiveur", type=float, default=2000.0)
    ap.add_argument("--seuil-sharpe", type=float, default=0.3)
    ap.add_argument("--seuil-correlation", type=float, default=0.3)
    ap.add_argument("--tolerance-conflit", type=float, default=0.02)
    ap.add_argument("--seuil-chevauchement", type=float, default=0.10)
    ap.add_argument("--objectif", type=float, default=None, help="profit a atteindre pour reussir l evaluation (defaut 6 %% du compte)")
    ap.add_argument("--horizon", type=int, default=120, help="jours de bourse max pour reussir l evaluation")
    ap.add_argument("--sortie", default=os.path.join(PY_DIR, "recherche", "resultats_portefeuille_prop.txt"))
    a = ap.parse_args(argv)
    a.objectif = a.objectif or 0.06 * a.compte
    L = []
    pr = L.append
    fmt = lambda x: f"{x:+,.0f} $".replace(",", " ")
    toutes = charger()
    pr("=" * 110)
    pr(f" PORTEFEUILLE PROP FIRM FUTURES - compte {a.compte:,.0f} $, perte journaliere max {a.perte_jour:,.0f} $, "
       f"drawdown suiveur {a.dd_suiveur:,.0f} $ (fin de journee)".replace(",", " "))
    pr("=" * 110)
    pr(f"Strategie retenue si : PnL net > 0, Sharpe >= {a.seuil_sharpe}, positive sur 2016-2020 ET sur 2021-2026, "
       "et deployable a la taille du compte (au moins 1 micro par position).")
    if MANQUANTES:
        pr("Non chargees (negatives, voir resultats_strategies.txt) : " + " ; ".join(MANQUANTES))
    pr("")
    pr("Temps en position : moyenne par trade, en temps calendaire de l entree a la sortie (nuits et week-ends compris).")
    pr("")
    candidates, echelles, durees = [], {}, {}
    for d in retenir(toutes, a.compte, a.seuil_sharpe):
        s, e, desc, raison = d["strategie"], d["echelle"], d["description"], d["raison"]
        ok = raison == ""
        du = None if s.spec.get("permanent") else durees_trades(s.nom)
        durees[s.nom] = du
        dtxt = "permanente" if s.spec.get("permanent") else (fmt_duree(du["moyenne"]) if du else "n/d")
        dd_txt = f"{s.max_dd() * e:8,.0f}".replace(",", " ")
        pr(f"  {'[x]' if ok else '[ ]'} {s.nom:64} Sharpe {s.sharpe:5.2f} | {desc:50} | en position {dtxt:>10} | "
           f"PnL prop {fmt(s.net * e):>11} | DD prop {dd_txt} $" + (f" | {raison}" if raison else ""))
        if ok:
            candidates.append(s)
            echelles[s.nom] = e
    if len(candidates) < 2:
        pr("\nMoins de 2 strategies retenues : rien a combiner.")
        _ecrire(a.sortie, L)
        return
    div = Diversification(candidates, echelles)
    noms = [s.nom for s in candidates]
    court = {n: f"S{i + 1}" for i, n in enumerate(noms)}
    pr("\nLegende (temps en position par trade : moyenne, mediane, gagnants / perdants) :")
    for n in noms:
        du = durees.get(n)
        dtxt = ("position permanente" if next(s.spec.get("permanent") for s in candidates if s.nom == n) else
                f"en position {fmt_duree(du['moyenne'])} (mediane {fmt_duree(du['mediane'])}, gagnants {fmt_duree(du['gagnants'])} / "
                f"perdants {fmt_duree(du['perdants'])})" if du else "temps en position n/d")
        pr(f"  {court[n]} = {n} ({', '.join(sorted(next(s.instruments for s in candidates if s.nom == n)))}) - {dtxt}")

    pr("\n=== 1. DIVERSIFICATION ===")
    with pd.option_context("display.float_format", "{:+.2f}".format, "display.width", 250, "display.max_columns", 50):
        pr("Correlation des P&L quotidiens :")
        pr(div.correlation().rename(index=court, columns=court).to_string())
        pr("\nCorrelation sur les jours ou la paire perd (pertes simultanees) :")
        pr(div.correlation_baisse().rename(index=court, columns=court).to_string())
    g = div.correlation_glissante()
    if len(g):
        pr("\nStabilite (correlation sur 1 an glissant, min / max) :")
        for r in g.itertuples():
            pr(f"  {court[r.A]} / {court[r.B]} : {r.corr_min_1an:+.2f} a {r.corr_max_1an:+.2f}")
    sel_div = div.selection(a.seuil_correlation)
    pr(f"\nRatio de diversification de l ensemble : {div.ratio_diversification():.2f} (1 = aucune diversification)")
    pr(f"Groupe peu correle (|corr| < {a.seuil_correlation}, glouton par Sharpe) : " + ", ".join(court[n] for n in sel_div))

    pr("\n=== 2. CHEVAUCHEMENT ===")
    chev = Chevauchement(candidates)
    tp = chev.temps_en_position()
    pr("Temps en position : " + " | ".join(f"{court[n]} {tp[n]:.1%}" for n in noms if n in tp))
    with pd.option_context("display.float_format", "{:.0%}".format, "display.width", 250, "display.max_columns", 50):
        pr("\nChevauchement dans le temps (tous contrats confondus) :")
        pr(chev.matrice().rename(index=court, columns=court).to_string())
        pr("\nConflits de contrat (meme contrat au meme moment), part du temps de la moins exposee :")
        pr(chev.part_conflit().rename(index=court, columns=court).to_string())
        pr("\nProfil horaire (part du temps en position par heure ET) :")
        pr(chev.profil_horaire().rename(index=court).to_string())
    prio = sorted(noms, key=lambda n: -next(s.sharpe for s in candidates if s.nom == n))
    strict = chev.groupe_sans_chevauchement(prio, a.seuil_chevauchement)
    pr(f"\nGroupe strictement sans chevauchement (jamais en position en meme temps, <= {a.seuil_chevauchement:.0%}) : "
       + ", ".join(court[n] for n in strict))

    pr("\n=== 3. MEILLEURS GROUPES POUR LE COMPTE PROP ===")
    pr(f"Contraintes : aucun conflit de contrat (<= {a.tolerance_conflit:.0%} du temps), |correlation| < {a.seuil_correlation} "
       "entre chaque paire. Taille max = plus grand multiplicateur de la taille de base sans violation des regles sur 2016-2026 ;")
    pr("taille conseillee = 50 % de ce maximum (marge : le maximum est mesure sur le meme historique). Classement par PnL annuel")
    pr("a la taille conseillee.")
    best = meilleurs_groupes(div, chev, noms, a.seuil_correlation, a.tolerance_conflit, a.compte, a.perte_jour, a.dd_suiveur)
    if not best:
        pr("  aucun groupe de 2 strategies ou plus ne respecte les contraintes")
    for i, r in enumerate(best, 1):
        pr(f"  {i}. {' + '.join(court[n] for n in r['groupe']):20} Sharpe {r['sharpe']:.2f} | diversification {r['ratio_div']:.2f} | "
           f"taille de base : PnL {fmt(r['pnl'])}, DD {r['dd']:,.0f} $, pire jour {r['pire_jour']:+,.0f} $ | ".replace(",", " ")
           + f"taille max x{r['k_max']:.2f}, conseillee x{0.5 * r['k_max']:.2f} -> {fmt(r['pnl_an_conseille'])} par an")
    pr("\nSeules :")
    for s in candidates:
        p1 = s.pnl * echelles[s.nom]
        rp = regle_prop(p1, a.compte, a.perte_jour, a.dd_suiveur)
        km = taille_max(p1, a.compte, a.perte_jour, a.dd_suiveur)
        pr(f"  {court[s.nom]:4} taille de base : pire jour {rp['pire_jour']:+8,.0f} $, DD {rp['dd_max']:8,.0f} $, ".replace(",", " ")
           + ("regles respectees" if rp["premiere_violation"] is None else f"violation le {rp['premiere_violation']:%Y-%m-%d}")
           + f" | taille max x{km:.2f}, conseillee x{0.5 * km:.2f} -> {fmt(float(p1.sum()) * 0.5 * km / _annees(p1))} par an")
    pr(f"\n=== 4. SIMULATION DE L EVALUATION (objectif {fmt(a.objectif)}, {a.horizon} jours de bourse max) ===")
    pr("Evaluation rejouee en partant de chaque jour 2016-2026. Taille = multiplicateur du nombre de contrats de base (arrondi")
    pr("au contrat entier en pratique : x2 = 2 MNQ au lieu de 1 ; x0.5 n existe pas pour une strategie a 1 contrat).")
    pr("Taille retenue = celle qui maximise le taux de reussite sur la grille " + ", ".join(f"x{k:g}" for k in MULTIPLICATEURS) + ".")
    pr(f"Reference a battre : une strategie SANS avantage reussit ~{hasard_prop(a.objectif, a.dd_suiveur):.0%} des evaluations "
       "conclues (objectif contre drawdown, pile ou face).")
    pr("'avantage' = reussite parmi les evaluations conclues moins cette reference ; une duree mediane de 1 a 3 jours = pari, pas strategie.")
    lignes = [(" + ".join(court[n] for n in r["groupe"]), div.combine(list(r["groupe"]))) for r in best]
    lignes += [(court[s.nom], s.pnl * echelles[s.nom]) for s in candidates]
    ev = []
    for nom, p in lignes:
        k, r, r1 = meilleure_taille_evaluation(p, a.compte, a.objectif, a.perte_jour, a.dd_suiveur, a.horizon)
        ev.append((r["reussite"], nom, k, r, r1))
    ev.sort(key=lambda t: -t[0])
    pct = lambda x: f"{x:4.0%}" if math.isfinite(x) else "  - "
    jr = lambda x: f"{x:4.0f} j" if math.isfinite(x) else "   - "
    for _, nom, k, r, r1 in ev:
        pr(f"  {nom:20} x1 : reussite {pct(r1['reussite'])} echec {pct(r1['echec'])} | meilleure taille x{k:<4g}: reussite "
           f"{pct(r['reussite'])}, echec {pct(r['echec'])}, non conclu {pct(r['non_conclu'])}, duree mediane {jr(r['jours_median'])}, "
           f"avantage {r['avantage']:+.0%}")
    pr("\nNotes : regles evaluees en fin de journee (une firme qui suit le drawdown en intrajournalier est plus severe) ;")
    pr("drawdown suiveur bloque au capital de depart une fois atteint (regle la plus courante). Adapter --compte, --perte-jour,")
    pr("--dd-suiveur a ta firme. Un backtest favorable doit encore passer le walk-forward et une periode de paper trading.")
    _ecrire(a.sortie, L)


def _ecrire(path, L):
    txt = "\n".join(L)
    with open(path, "w", encoding="utf-8") as f:
        f.write(txt + "\n")
    print(txt)
    print(f"\n-> {path}")


if __name__ == "__main__":
    main()
