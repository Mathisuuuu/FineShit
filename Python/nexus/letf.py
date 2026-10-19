"""Fiche 15 : rebalancement des ETF a levier (LETF) sur NQ / ES, de 15:30 a 16:00 New York, construit dans vectorbt.

Portage Python du NinjaScript Strategies/Nexus15_LetfRebalancing.cs + AddOns/NexusLetf.cs (session cloud du 2026-10-14,
branche claude/adoring-cray-8l3ug8), memes regles et memes valeurs par defaut.

Source : Barbon, Beckmeyer, Buraschi & Moerke, Liquidity Provision to Leveraged ETFs and Equity Options Rebalancing
Flows, SSRN 3925725. Un LETF de levier L doit chaque soir ramener son exposition a L x son actif net : il achete apres
une hausse et vend apres une baisse (flux F = A L(L-1) r / (1 + L r)) ; les teneurs de marche d options courts gamma
couvrent dans le meme sens et amplifient l impact en fin de seance.

Regles (heure de New York, barres 1 minute datees a leur fin) :
  1. signal a 15:25 : r = niveau a 15:25 / cloture de la veille - 1 ; F = somme des flux des fonds de l indice
     (TQQQ, SQQQ, QLD, QID pour NQ ; UPRO, SPXU, SPXL, SPXS, SSO, SDS pour ES) ; N = F / (multiplicateur x niveau) ;
     S = N / V, V = volume moyen 15:30-16:00 des 20 dernieres seances completes ;
  2. Score = S x w(G) : w = 1 si les teneurs de marche sont courts gamma (GEX < 0) ou si le GEX est inconnu, 0,3 sinon ;
  3. trade si |r| >= 0,5 %, |Score| >= q70 des |Score| des 250 seances precedentes et jour non exclu (FOMC, CPI, NFP,
     demi-seances, quatre sorcieres = rebalancement trimestriel du Nasdaq-100, rebalancement special) ;
  4. NQ en priorite ; ES seulement si NQ n est pas retenu et que son propre score passe ; une position par jour ;
  5. entree au marche a 15:30 (ouverture de la barre 15:30-15:31) dans le sens de r ; stop 1,5 x ATR(14) des barres
     de 30 minutes de la seance ; sortie a 16:00 (cloture) ; jamais de portage de nuit ;
  6. taille = capital x 0,5 % / (prix x $/point x vol realisee des 30 dernieres minutes ramenee a 30 min) x |Score| /
     seuil, arrondie au contrat inferieur, plafonnee a 2 % du volume attendu sur la fenetre (moitie si |r| > 3 %) ;
  7. couts : 1 tick aller-retour (1/2 tick par execution) + 2,50 $ par contrat et par execution.

Ecarts avec le NinjaScript (donnees) :
  - actif net des fonds : le C# lit Data/letf_aum.csv (parts x NAV de la veille), vide dans le depot. Sans ce fichier,
    l actif net de chaque fonds est une CONSTANTE (ordre de grandeur 2024, AUM_PROXY) : le seuil q70 glissant est
    invariant a l echelle, seule la croissance des encours depuis 2016 n est pas modelisee. Un letf_aum.csv rempli
    (meme format que le C#) est utilise s il existe ;
  - indice : le future (NQ, ES) remplace ^NDX / ^SP500 (le C# fait de meme, avec un avertissement, s ils manquent) ;
  - GEX : SqueezeMetrics (indice S&P 500 seul, .cache/gex/DIX.csv, telechargement public), derniere valeur datee
    strictement avant la seance (5 jours au plus), au lieu de la somme SPX + NDX + QQQ ;
  - taille calculee sur le capital initial (pas de reinvestissement), comme les autres candidates du tableau de bord.
"""
from __future__ import annotations

import math
import os

import numpy as np
import pandas as pd

from . import data as D
from . import intraday as I

try:
    import vectorbt as vbt
except ImportError:  # pragma: no cover
    vbt = None

ICI = os.path.dirname(__file__)
PERSO = os.path.join(ICI, "perso")
DATA = os.path.normpath(os.path.join(ICI, "..", "..", "Data"))
FICHIER_GEX = os.path.normpath(os.path.join(ICI, "..", ".cache", "gex", "DIX.csv"))

SPEC = {"NQ": dict(multiplicateur=20.0, tick=0.25, indice="NDX"), "ES": dict(multiplicateur=50.0, tick=0.25, indice="SPX")}
FONDS = {"NDX": [("TQQQ", 3), ("SQQQ", -3), ("QLD", 2), ("QID", -2)],
         "SPX": [("UPRO", 3), ("SPXU", -3), ("SPXL", 3), ("SPXS", -3), ("SSO", 2), ("SDS", -2)]}
# Actif net (milliards de $), ordre de grandeur 2024, utilise faute d historique (voir l en-tete).
AUM_PROXY = {"TQQQ": 22.0, "SQQQ": 3.5, "QLD": 7.0, "QID": 0.3, "UPRO": 3.5, "SPXU": 0.5, "SPXL": 5.0, "SPXS": 0.5,
             "SSO": 5.5, "SDS": 0.6}
COMMISSION = 2.50
MINUTES_AN = 252.0 * 390.0
# Rebalancement special du Nasdaq-100 (effectif a l ouverture du lundi 24/07/2023 : fonds indiciels au close du 21).
REBALANCEMENTS_SPECIAUX = ("2023-07-21",)

DEFAULTS = dict(symboles=("NQ", "ES"), capital=500_000.0, signal="15:25", entree="15:30", sortie="16:00",
                volume_jours=20, filtre_gamma=True, poids_gamma_court=1.0, poids_gamma_long=0.3, gex_jours_max=5,
                quantile=70.0, fenetre_seuil=250, min_rendement_pct=0.5, cible_risque_pct=0.5, rv_minutes=30,
                plafond_volume_pct=2.0, mouvement_extreme_pct=3.0, levier_max=0.0, atr_mult=1.5, atr_minutes=30, atr_periode=14,
                exclusions=True, formule="fiche", decalage_min=0, delai_min=0, cout_mult=1.0,
                jours_hasard=None, taille_fixe=False)
PUBLICATION = "2021-09-01"     # SSRN 3925725 (premiere mise en ligne, septembre 2021)
# Essais comptes pour le Sharpe deflate et les corrections : 186 avant le groupe P1 + 58 hypotheses et 66 essais
# de microstructure du groupe P1 (sessions cloud) + 58 essais des sessions locales (nexus/perso) + cette fiche.
ESSAIS = 369
VAR_SHARPE_ESSAIS_ANNUALISE = 0.87


def _slot(hhmm: str, decalage: int = 0) -> int:
    """Colonne de la grille de seance de la barre qui se TERMINE a hh:mm (9:31 -> 0, 16:00 -> 389)."""
    h, m = (int(x) for x in hhmm.split(":"))
    return h * 60 + m + int(decalage) - 571


# =============================================================================
#  Donnees
# =============================================================================
def charger(dossier: str, symboles=("NQ", "ES")) -> tuple[dict, dict]:
    """Grilles de seance (jours x 390) par symbole : prix ajustes des rolls (signal, ATR) et prix bruts (execution)."""
    out, info = {}, {}
    for sym in symboles:
        df = D.load_folder(dossier, daily=False, only=[sym])[sym]
        adj, rolls = I.adjust_rolls_midnight_utc(df, "UTC")
        ny, note = I.prepare_minutes(adj, "UTC", "auto")
        brut, _ = I.prepare_minutes(df, "UTC", "auto")
        out[sym] = dict(adj=I.build_grid(ny), brut=I.build_grid(brut))
        g = out[sym]["adj"]
        info[sym] = dict(symbole=f"{sym}.v.0 (CME Globex, contrat continu roule au volume)", barres=int(len(df)),
                         seances=int(g.valid.sum()), debut=f"{g.days[g.valid][0]:%Y-%m-%d}", fin=f"{g.days[g.valid][-1]:%Y-%m-%d}",
                         rolls=int(len(rolls)), horodatage=note)
    return out, info


def gex(fichier: str = FICHIER_GEX) -> pd.Series:
    """GEX quotidien SqueezeMetrics (dollars par 1 % de mouvement), vide si le fichier manque."""
    if not os.path.exists(fichier):
        return pd.Series(dtype=float)
    d = pd.read_csv(fichier)
    return pd.Series(pd.to_numeric(d["gex"], errors="coerce").to_numpy(), index=pd.to_datetime(d["date"])).dropna().sort_index()


def gex_veille(g: pd.Series, jours: pd.DatetimeIndex, max_jours: int = 5) -> np.ndarray:
    """Derniere valeur datee strictement avant chaque jour, au plus max_jours jours calendaires plus tot (sinon NaN)."""
    if g.empty:
        return np.full(len(jours), np.nan)
    k = np.searchsorted(g.index.to_numpy(), jours.to_numpy(), side="left") - 1
    v = np.where(k >= 0, g.to_numpy()[np.clip(k, 0, None)], np.nan)
    age = (jours.to_numpy() - g.index.to_numpy()[np.clip(k, 0, None)]) / np.timedelta64(1, "D")
    return np.where((k >= 0) & (age <= max_jours), v, np.nan)


def aum(jours: pd.DatetimeIndex, fichier: str = os.path.join(DATA, "letf_aum.csv"), max_jours: int = 7) -> tuple[pd.DataFrame, str]:
    """Actif net de chaque fonds la VEILLE de chaque seance (jours x fonds) et l origine des valeurs."""
    fonds = [f for lst in FONDS.values() for f, _ in lst]
    if os.path.exists(fichier):
        t = pd.read_csv(fichier, comment="#")
        if len(t):
            t["date"] = pd.to_datetime(t["date"])
            a = t["aum"] if "aum" in t else pd.Series(np.nan, index=t.index)
            t["a"] = a.fillna(pd.to_numeric(t.get("shares_outstanding"), errors="coerce") * pd.to_numeric(t.get("nav"), errors="coerce"))
            out = pd.DataFrame(index=jours)
            for f in fonds:
                s = t.loc[t["fund"].str.upper() == f, ["date", "a"]].dropna().set_index("date")["a"].sort_index()
                out[f] = gex_veille(s, jours, max_jours) if len(s) else np.nan
            return out, f"{os.path.basename(fichier)} (parts x NAV de la veille)"
    return (pd.DataFrame({f: AUM_PROXY[f] * 1e9 for f in fonds}, index=jours),
            "constantes (ordre de grandeur 2024, AUM_PROXY) : Data/letf_aum.csv vide")


def _lire_dates(chemin: str, filtre=None) -> pd.DatetimeIndex:
    if not os.path.exists(chemin):
        return pd.DatetimeIndex([])
    t = pd.read_csv(chemin, comment="#")
    if filtre is not None:
        t = t[t.iloc[:, 1].astype(str).str.upper().isin(filtre)]
    return pd.DatetimeIndex(pd.to_datetime(t["date"], errors="coerce").dropna())


def quatre_sorcieres(debut, fin) -> pd.DatetimeIndex:
    """3e vendredi de mars, juin, septembre, decembre (veille ouvree si ferie NYSE) : echeances et rebalancement
    trimestriel du Nasdaq-100."""
    out = []
    feries = I.nyse_holidays(pd.Timestamp(debut) - pd.Timedelta(days=7), pd.Timestamp(fin) + pd.Timedelta(days=7))
    for y in range(pd.Timestamp(debut).year, pd.Timestamp(fin).year + 1):
        for m in (3, 6, 9, 12):
            d = pd.Timestamp(y, m, 1)
            d = d + pd.Timedelta(days=(4 - d.dayofweek) % 7 + 14)
            while d in feries:
                d -= pd.Timedelta(days=1)
            out.append(d)
    return pd.DatetimeIndex(out)


def jours_exclus(debut, fin) -> pd.DataFrame:
    """Jours exclus et motif : FOMC (communiques programmes), CPI, NFP (BLS), quatre sorcieres, rebalancement special du
    Nasdaq-100, et Data/letf_excluded_days.csv s il est rempli."""
    lignes = [(d, "FOMC") for d in _lire_dates(os.path.join(PERSO, "fomc_programmees.csv"))]
    t = os.path.join(PERSO, "annonces_us.csv")
    lignes += [(d, "CPI") for d in _lire_dates(t, {"CPI"})] + [(d, "NFP") for d in _lire_dates(t, {"NFP"})]
    lignes += [(d, "quatre sorcieres / NDX") for d in quatre_sorcieres(debut, fin)]
    lignes += [(pd.Timestamp(d), "NDX rebalancement special") for d in REBALANCEMENTS_SPECIAUX]
    autre = os.path.join(DATA, "letf_excluded_days.csv")
    if os.path.exists(autre):
        x = pd.read_csv(autre, comment="#")
        lignes += [(pd.Timestamp(d), str(r)) for d, r in zip(x.get("date", []), x.get("reason", []))]
    e = pd.DataFrame(lignes, columns=["date", "motif"])
    e = e[(e["date"] >= pd.Timestamp(debut)) & (e["date"] <= pd.Timestamp(fin))]
    return e.groupby("date")["motif"].agg(" + ".join).to_frame()


def seances(g) -> np.ndarray:
    """Seances completes de la grille : valides, pas demi-seance, pas ferie NYSE (seance CME raccourcie)."""
    ferie = np.asarray(g.days.isin(I.nyse_holidays(g.days[0], g.days[-1])))
    return g.valid & ~g.half_day & ~ferie


# =============================================================================
#  Signal par seance
# =============================================================================
def _atr_30min(g, minutes: int, periode: int) -> np.ndarray:
    """ATR de Wilder des barres de `minutes` minutes de la seance (ajustee), continu d un jour a l autre ;
    renvoie, pour chaque jour, la matrice (jours x barres) de l ATR connu a la fin de chaque barre."""
    k = 390 // minutes
    D_, S = g.n_days, k * minutes
    h = g.h[:, :S].reshape(D_, k, minutes).max(axis=2)
    lo = g.l[:, :S].reshape(D_, k, minutes).min(axis=2)
    c = g.c[:, minutes - 1:S:minutes]
    ok = seances(g)
    hh, ll, cc = h[ok].ravel(), lo[ok].ravel(), c[ok].ravel()
    pc = np.r_[np.nan, cc[:-1]]
    tr = np.where(np.isfinite(pc), np.maximum(hh - ll, np.maximum(np.abs(hh - pc), np.abs(ll - pc))), hh - ll)
    atr = np.full(len(tr), np.nan)
    if len(tr) >= periode:
        a = float(np.nanmean(tr[:periode]))
        atr[periode - 1] = a
        for i in range(periode, len(tr)):
            if np.isfinite(tr[i]):
                a = (a * (periode - 1) + tr[i]) / periode
            atr[i] = a
    out = np.full((D_, k), np.nan)
    out[ok] = atr.reshape(-1, k)
    return out


# Parametres dont dependent les caracteristiques (calcul lourd) ; les autres ne changent que les decisions.
CLES_BASE = ("symboles", "signal", "entree", "sortie", "volume_jours", "gex_jours_max", "rv_minutes", "atr_minutes",
             "atr_periode", "formule", "decalage_min")


def caracteristiques(grilles: dict, p: dict, gex_s: pd.Series | None = None) -> pd.DataFrame:
    """Une ligne par (jour, symbole) : r, flux, N, V, S, G, motif d exclusion, vol realisee, ATR, prix d entree.
    Toutes les grandeurs n utilisent que l information disponible a l heure du signal."""
    gex_s = gex() if gex_s is None else gex_s
    dec = int(p["decalage_min"])
    s_sig, s_ent, s_fin = _slot(p["signal"], dec), _slot(p["entree"], dec) + 1, _slot(p["sortie"], dec)
    duree = s_fin - s_ent + 1
    rows = []
    jours_communs = None
    for sym in p["symboles"]:
        g = grilles[sym]["adj"]
        jours = pd.DatetimeIndex(g.days[seances(g)])
        jours_communs = jours if jours_communs is None else jours_communs.intersection(jours)
    excl = jours_exclus(jours_communs[0], jours_communs[-1])
    A, origine = aum(jours_communs)
    G = gex_veille(gex_s, jours_communs, int(p["gex_jours_max"]))
    for sym in p["symboles"]:
        g, gb = grilles[sym]["adj"], grilles[sym]["brut"]
        spec = SPEC[sym]
        pos = pd.Series(np.arange(g.n_days), index=g.days)
        complet = seances(g)
        cl = g.day_close
        ouvre = g.valid & ~np.asarray(g.days.isin(I.nyse_holidays(g.days[0], g.days[-1])))   # demi-seances comprises
        prev_close = pd.Series(np.where(ouvre, cl, np.nan), index=g.days).ffill().shift(1).to_numpy()
        vfen = np.nansum(g.v[:, s_ent:s_fin + 1], axis=1)
        nbar = (g.v[:, s_ent:s_fin + 1] > 0).sum(axis=1)
        ok_v = complet & (nbar >= math.floor(0.8 * duree)) & (vfen > 0)
        vser = pd.Series(np.where(ok_v, vfen, np.nan), index=g.days)
        vbar = vser.shift(1).rolling(int(p["volume_jours"]) * 3, min_periods=1).apply(
            lambda x: np.mean(x[np.isfinite(x)][-int(p["volume_jours"]):]) if np.isfinite(x).sum() >= int(p["volume_jours"]) else np.nan, raw=True).to_numpy()
        atr = _atr_30min(g, int(p["atr_minutes"]), int(p["atr_periode"]))
        k_atr = (s_ent - 1 + 1) // int(p["atr_minutes"]) - 1       # derniere barre de 30 min complete avant l entree
        lr = np.diff(np.log(g.c), axis=1)
        for j, d in enumerate(jours_communs):
            i = int(pos[d])
            lvl, lvl_brut, pc = g.c[i, s_sig], gb.c[i, s_sig], prev_close[i]
            r = lvl / pc - 1 if pc > 0 and np.isfinite(lvl) else np.nan
            fl = 0.0
            for f, L in FONDS[spec["indice"]]:
                a = A.iloc[j][f]
                if np.isfinite(a) and np.isfinite(r):
                    fl += a * L * (L - 1) * r / ((1 + L * r) if p["formule"] == "fiche" else 1.0)
            N = fl / (spec["multiplicateur"] * lvl_brut) if lvl_brut > 0 else np.nan
            V = vbar[i]
            S = N / V if V > 0 else np.nan
            rv_r = lr[i, s_ent - 1 - int(p["rv_minutes"]):s_ent - 1]
            rv_r = rv_r[np.isfinite(rv_r)]
            rv = math.sqrt(np.mean(rv_r ** 2) * MINUTES_AN) if len(rv_r) >= max(2, int(p["rv_minutes"]) // 2) else np.nan
            rows.append(dict(date=d, symbole=sym, r=r, flux=fl, N=N, V=V, S=S, G=G[j],
                             motif=excl["motif"].get(d, "") if len(excl) else "", rv=rv,
                             atr1=(atr[i, k_atr] / g.c[i, s_ent - 1]) if k_atr >= 0 else np.nan,
                             prix_brut=gb.o[i, s_ent], i=i))
    t = pd.DataFrame(rows)
    t.attrs.update(aum=origine, duree=duree)
    return t


def decisions(base: pd.DataFrame, p: dict) -> pd.DataFrame:
    """Score, seuil glissant, filtres, regle d instrument et taille, a partir des caracteristiques."""
    t = base.copy()
    duree = base.attrs["duree"]
    gneg = ~np.isfinite(t["G"]) | (t["G"] < 0)            # GEX inconnu : poids 1 (regle PoidsUn du NinjaScript)
    t["w"] = np.where(gneg, p["poids_gamma_court"], p["poids_gamma_long"]) if p["filtre_gamma"] else 1.0
    t["score"] = t["S"] * t["w"]
    t["exclu"] = t["motif"] if p["exclusions"] else ""
    t["atr_frac"] = float(p["atr_mult"]) * t["atr1"]
    t["seuil"] = np.nan
    for sym, x in t.groupby("symbole"):
        a = x["score"].abs()
        ok = a.dropna()
        q = ok.rolling(int(p["fenetre_seuil"]), min_periods=int(p["fenetre_seuil"])).quantile(float(p["quantile"]) / 100.0, interpolation="linear")
        t.loc[ok.index, "seuil"] = q.shift(1)
        t.loc[x.index, "seuil"] = t.loc[x.index, "seuil"].ffill()
    t["passe"] = (t["exclu"] == "") & (t["r"].abs() >= float(p["min_rendement_pct"]) / 100) & (t["score"].abs() >= t["seuil"]) \
        & (t["seuil"] > 0) & np.isfinite(t["score"])
    if p["jours_hasard"] is not None:          # test sur hasard : jours imposes, sens de r, memes tailles
        t["passe"] = t["date"].isin(pd.DatetimeIndex(p["jours_hasard"])) & np.isfinite(t["r"]) & (t["r"] != 0) \
            & (t["seuil"] > 0) & np.isfinite(t["score"])
    # une position par jour : NQ prioritaire, ES en secours
    t["retenu"] = False
    for d, x in t.groupby("date", sort=False):
        for k in x.index:
            if t.at[k, "passe"]:
                t.at[k, "retenu"] = True
                break
    # taille (contrats) : cible de risque x |Score| / seuil, plafond de volume
    pv = t["symbole"].map(lambda s: SPEC[s]["multiplicateur"])
    sigma = t["rv"] * np.sqrt(duree / MINUTES_AN)
    base = float(p["capital"]) * float(p["cible_risque_pct"]) / 100 / (t["prix_brut"] * pv * sigma)
    brut = base * (1.0 if p["taille_fixe"] else t["score"].abs() / t["seuil"])    # taille_fixe : test sur hasard
    cap = t["V"] * float(p["plafond_volume_pct"]) / 100 * np.where(t["r"].abs() > float(p["mouvement_extreme_pct"]) / 100, 0.5, 1.0)
    if float(p["levier_max"]) > 0:             # 0 = pas de plafond de levier (valeur du NinjaScript)
        cap = np.minimum(cap, float(p["levier_max"]) * float(p["capital"]) / (t["prix_brut"] * pv))
    t["contrats"] = np.floor(np.minimum(brut, cap)).where(t["retenu"], 0).fillna(0).clip(lower=0).astype(int)
    t.loc[t["contrats"] < 1, "retenu"] = False
    t["levier"] = np.where(t["retenu"], t["contrats"] * pv * t["prix_brut"] / float(p["capital"]), 0.0)
    return t


def panneau(grilles: dict, p: dict, gex_s: pd.Series | None = None, base: pd.DataFrame | None = None) -> pd.DataFrame:
    """Caracteristiques (ou `base` deja calculee pour les memes CLES_BASE) puis decisions."""
    return decisions(caracteristiques(grilles, p, gex_s) if base is None else base, p)


# =============================================================================
#  vectorbt
# =============================================================================
def cadre(grilles: dict, p: dict) -> dict:
    """Barres 1 minute de la fenetre (15:30-16:00 par defaut), prix BRUTS (aucun roll dans la fenetre), une colonne
    par symbole, sur les seances completes communes."""
    dec = int(p["decalage_min"])
    s_ent, s_fin = _slot(p["entree"], dec) + 1, _slot(p["sortie"], dec)
    jours = None
    for sym in p["symboles"]:
        g = grilles[sym]["adj"]
        j = pd.DatetimeIndex(g.days[seances(g)])
        jours = j if jours is None else jours.intersection(j)
    slots = np.arange(s_ent, s_fin + 1)
    idx = pd.DatetimeIndex((jours.to_numpy()[:, None] + pd.to_timedelta(9 * 60 + 30 + slots + 1, unit="min").to_numpy()[None, :]).ravel())
    out = {k: pd.DataFrame(index=idx) for k in ("open", "high", "low", "close")}
    for sym in p["symboles"]:
        gb = grilles[sym]["brut"]
        pos = pd.Series(np.arange(gb.n_days), index=gb.days).reindex(jours).to_numpy()
        for k, m in (("open", gb.o), ("high", gb.h), ("low", gb.l), ("close", gb.c)):
            out[k][sym] = m[pos][:, slots].ravel()
    for k in out:
        out[k] = out[k].ffill().bfill()
    out["jours"], out["n"] = jours, len(slots)
    return out


def portefeuille(grilles: dict, panel: pd.DataFrame | None = None, gex_s: pd.Series | None = None,
                 base: pd.DataFrame | None = None, **params):
    if vbt is None:
        raise ImportError("vectorbt n est pas installe")
    p = {**DEFAULTS, **params}
    if panel is None:
        panel = panneau(grilles, p, gex_s, base)
    fr = cadre(grilles, p)
    o, c = fr["open"], fr["close"]
    n, jours = fr["n"], fr["jours"]
    cols = list(o.columns)
    E, SE, X = (pd.DataFrame(False, index=o.index, columns=cols) for _ in range(3))
    prix = o.copy()
    sl = pd.DataFrame(np.nan, index=o.index, columns=cols)
    taille = pd.DataFrame(np.nan, index=o.index, columns=cols)
    rang = pd.Series(np.arange(len(jours)), index=jours)
    delai = int(p["delai_min"])
    for x in panel[panel["retenu"]].itertuples():
        b = int(rang[x.date]) * n
        e = b + delai
        if e >= b + n - 1:
            continue
        col = cols.index(x.symbole)
        (E if x.r > 0 else SE).iat[e, col] = True
        sl.iat[e, col] = x.atr_frac if np.isfinite(x.atr_frac) and x.atr_frac > 0 else np.nan
        taille.iat[e, col] = x.contrats * SPEC[x.symbole]["multiplicateur"]
    fin = np.arange(n - 1, len(o), n)
    X.iloc[fin, :] = True
    prix.iloc[fin, :] = c.iloc[fin, :].to_numpy()          # sortie a la cloture de 16:00
    mult = np.array([SPEC[s]["multiplicateur"] for s in cols])
    tick = np.array([SPEC[s]["tick"] for s in cols])
    k = float(p["cout_mult"])
    frais = COMMISSION / (c * mult) * k
    gliss = 0.5 * tick / c * k
    cap = float(p["capital"])
    # vectorbt ne gere pas de marge : une reserve de liquidites couvre le notionnel du plus gros trade (x 1,5),
    # puis elle est retiree de la valeur du capital (valeur()).
    reserve = cap * max(9.0, 1.5 * float(panel["levier"].max() if len(panel) else 0.0))
    pf = vbt.Portfolio.from_signals(c, entries=E, exits=X, short_entries=SE, short_exits=X, price=prix, open=o,
                                    high=fr["high"], low=fr["low"], size=taille, size_type="amount", sl_stop=sl,
                                    stop_entry_price="fillprice", fees=frais, slippage=gliss, group_by=True,
                                    cash_sharing=True, init_cash=cap + reserve, freq="1min")
    pf.nexus_reserve = reserve
    pf.nexus_panel = panel
    pf.nexus_params = p
    return pf


def valeur(pf) -> pd.Series:
    """Valeur du capital (valeur vectorbt moins la reserve de liquidites : vectorbt ne gere pas de marge)."""
    return pf.value() - getattr(pf, "nexus_reserve", 0.0)


def valeur_journaliere(pf, calendrier: pd.DatetimeIndex | None = None) -> pd.Series:
    v = valeur(pf)
    d = v.groupby(pd.DatetimeIndex(v.index).normalize()).last()
    if calendrier is not None:
        d = d.reindex(d.index.union(calendrier)).ffill().reindex(calendrier).bfill()
    return d


# =============================================================================
#  Mecanisme : regression r(15:30 -> 16:00) sur r(veille -> 15:25), erreurs de Newey-West
# =============================================================================
def mecanisme(grilles: dict, panel: pd.DataFrame, p: dict | None = None) -> list[dict]:
    """Pente et t de Newey-West de la derniere demi-heure sur le rendement du jour, par symbole et par periode,
    et interaction avec le regime gamma (GEX < 0), comme le protocole du NinjaScript (tests 1 et 3)."""
    import statsmodels.api as sm
    p = {**DEFAULTS, **(p or {})}
    dec = int(p["decalage_min"])
    s_ent, s_fin = _slot(p["entree"], dec), _slot(p["sortie"], dec)
    out = []
    for sym, x in panel.groupby("symbole"):
        g = grilles[sym]["adj"]
        y = g.c[x["i"].to_numpy(), s_fin] / g.c[x["i"].to_numpy(), s_ent] - 1
        f = pd.DataFrame(dict(date=x["date"].to_numpy(), y=y, r=x["r"].to_numpy(), neg=(x["G"] < 0).to_numpy().astype(float),
                              exclu=(x["exclu"] != "").to_numpy())).dropna()
        f = f[~f["exclu"]]
        for nom, sel in (("2016-2020", f["date"] < "2021-01-01"), ("2021-2026", f["date"] >= "2021-01-01"), ("tout", f["date"] > "1900")):
            z = f[sel]
            if len(z) < 100:
                continue
            Xm = sm.add_constant(np.column_stack([z["r"], z["r"] * z["neg"]]))
            m = sm.OLS(z["y"].to_numpy(), Xm).fit(cov_type="HAC", cov_kwds=dict(maxlags=int(4 * (len(z) / 100) ** (2 / 9))))
            out.append(dict(symbole=sym, periode=nom, n=int(len(z)), beta=float(m.params[1]), t=float(m.tvalues[1]),
                            beta_gamma_neg=float(m.params[2]), t_gamma_neg=float(m.tvalues[2]), part_gamma_neg=float(z["neg"].mean())))
    return out
