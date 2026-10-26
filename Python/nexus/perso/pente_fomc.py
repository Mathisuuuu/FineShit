"""Paris de pentification des speculateurs (COT) et ES le jour du FOMC, 9:30 -> 13:45 ET (UN essai, n° 435).

    python -m nexus.perso.pente_fomc [--sortie resultats_pente_fomc.txt]

PROTOCOLE ECRIT LE 2026-10-25 AVANT LE CALCUL. Aucun parametre n est choisi apres avoir vu un resultat.

Origine (hypothese n° 318 du registre, candidate : criteres 1 a 6 passes ; test demande par l utilisateur le 2026-10-25)
  Y.-H. Park (Reserve federale), « Information in Yield Spread Trades », FEDS 2019-025 (version d avril 2019) et version
  2018 « Spread Trades, Business Cycles, and Asset Prices » ; textes complets lus le 2026-10-25. Chiffres repris :
    - COT « Legacy, Futures Only » : SP_i = nombre de speculateurs (non-commerciaux) longs MOINS nombre de speculateurs
      courts (des NOMBRES de traders, pas des contrats), pour i = Eurodollar (3M), 10 ans (10Y), 30 ans (30Y) ;
      EXSP_i = SP_i - moyenne des trois ; binaire = 1 si EXSP_3M > 0 ET EXSP_30Y < 0 ; STEEP_t = moyenne du binaire sur
      les observations du dernier trimestre (equation 2) ;
    - rendement des futures S&P 500 de 9:30 ET le jour de l annonce a 15 min avant l annonce, regresse sur le STEEP de la
      reunion PRECEDENTE (« la prevision est faite environ 45 jours avant la prise de position ») : constante -0,01 %
      (t -0,15), STEEP 0,44 % (t 3,77), R2 12,8 %, 1997-2017 ; moyenne sans predicteur 0,19 % (t 3,24, ~160 reunions) ;
    - hors echantillon 2003-2017 : achat si le rendement prevu est positif, vente sinon, a 9:30, debouclage 15 min avant
      l annonce : Sharpe annuel 1,085, contre 0,748 pour l achat systematique.
  Papiers contraires : la derive d avant le FOMC (Lucca-Moench) est rejetee trois fois chez nous (n° 8) ; Park soutient
  justement que la derive est un effet de STEEP (constante non significative une fois STEEP present) : on teste SA regle.
  Calcul de puissance (critere 6, effet du papier sur l objet trade) : ecart-type 0,19 % x racine(160) / 3,24 = 74,2 pb ;
  gain par trade = Sharpe 1,085 / racine(8) x 74,2 = 28,5 pb ; ~86 reunions 2016-2026 : ES t 3,36 (cout 1,55 pb),
  MES 3,24 (2,5 pb) ; l achat systematique seul donnerait t 2,26.
  Le test compte pour UN essai : ESSAIS_PROGRAMME 434 -> 435 (les repliques et les micros ne sont pas des essais).

Regle unique, figee (aucune grille, aucune variante)
  Signal. Pour chaque reunion PROGRAMMEE du FOMC k (fomc_programmees.csv), signal = STEEP calcule a la date de la reunion
    programmee precedente k-1 :
      - un rapport COT (mesure du mardi) n est utilise que s il est publie avant ce jour : date de mesure + 6 jours <
        date de k-1 (publication du vendredi, lundi si ferie) ; fermetures de l Etat (publication suspendue) : rapports
        du 2018-12-25 au 2019-03-05 publies le 2019-03-08 (rattrapage annonce par la CFTC, communique 7864-19 ; date de
        fin d apres Saxo), rapports du 2025-09-30 au 2026-01-13 publies le 2026-01-23 (date de fin de la CFTC du
        2025-11-18 ; le communique du 2025-12-09 l avance au 2025-12-29 : on garde la plus tardive, sans anticipation) ;
      - trimestre = rapports dont la date de mesure est dans les 91 jours precedant la date de k-1 (Nt = leur nombre) ;
      - SUBSTITUT DU 3M (fige avant le calcul) : l Eurodollar (code CFTC 132741) disparait en 2023 ; le CME a converti
        tout l interet ouvert en SOFR 3 mois le 14/04/2023. 3M = Eurodollar pour les rapports dates jusqu au
        2023-04-11, puis SOFR 3 mois (code 134741) a partir du 2023-04-18. 10Y = 043602, 30Y = 020601 (bond classique,
        pas l ultra).
  Sens. Coefficients du papier figes (tableau 7, regression 2) : prevu = -0,01 + 0,44 x STEEP (%) ; ACHAT si prevu > 0,
    VENTE sinon (avec au plus ~13 rapports par trimestre, le plus petit STEEP non nul est 1/13 > 0,023 : achat des qu un
    rapport du trimestre montre la pentification, vente si aucun). Pas de regression recalculee sur nos donnees (ce
    serait un choix de fenetre de plus).
  Trade. Le jour de la reunion k : entree a 9:30 ET (ouverture de la barre qui commence a 9:30, `prix_a`), sortie a
    13:45 ET (15 min avant l annonce de 14:00, heure de toutes les reunions programmees de 2016 a 2026). Aucun stop.
    Exclus : prix absent, changement d echeance dans la fenetre, signal sans aucun rapport publie dans le trimestre.
  Conforme prop (critere 21) : intraday, a plat bien avant 16:10. Conflit de contrat (critere 19) : aucun sur l ES
    (S1 tient le MNQ, Gotobi le 6J) ; la replique NQ serait en conflit avec S1.
  Temoin neutre : la MEME operation (meme sens, meme fenetre 9:30 -> 13:45) 7 jours calendaires apres chaque reunion
    (meme jour de semaine, sans FOMC ; exclu si ferie ou prix absent).
  Reference donnee sans critere : l achat systematique 9:30 -> 13:45 les jours de FOMC (strategie naive du papier).
  Repliques (pas des essais) : NQ et YM, memes regles. Contrats du compte (critere 22) : MES, MNQ, MYM, leurs couts.
Couts (critere 8) : 1 tick + 2,50 $ par cote (stress 2 ticks par cote), au prix median des entrees.
Criteres : n° 10-14 (criteres() de soixante, ~86 cas donc pas le regime des evenements rares), n° 16-18 avec mesures()
  de prop_combinaisons (rendement net rattache au jour de la reunion, 0 les autres seances, Sharpe deflate avec 435
  essais), n° 19 (heures par an, rendement par heure), n° 20 (correlation avec S1 et Gotobi) seulement si le reste passe.
Verification du calcul (critere 9, sans regarder le gain) :
  (a) horodatage : volume median par minute ET les jours de FOMC ; pics attendus sur les barres qui commencent a 9:30
      (ouverture) et 14:00 (annonce) ;
  (b) anticipation : (b1) prix des barres qui commencent apres l entree (puis apres la sortie) x1,5 -> prix d entree (puis
      de sortie) inchanges ; (b2) rapports COT publies apres la date du signal remplaces par des valeurs au hasard ->
      STEEP inchange ;
  (c) rejeu vectorbt (Portfolio.from_orders, 1 contrat signe, sans frais) = P&L brut du moteur trade par trade ;
  (d) 5 trades tires au hasard (graine 7) imprimes en detail pour verification a la main ;
  (e) comptes : reunions, exclusions par motif, trades acheteurs / vendeurs, rapports COT par trimestre, substitut 3M.
"""
from __future__ import annotations

import argparse
import glob
import math
import os
import zipfile
from datetime import datetime

import numpy as np
import pandas as pd

from .. import prop_combinaisons as PC
from .cycle_fomc import fomc
from .or_anomalies import instants
from .ouverture_europe import correlations, cout_pb, reel
from .soixante import COMMISSION, COUTS, ET, NS_MIN, PY_DIR, contrats, criteres, jours_ouvres_us, marche, prix_a, \
    t_attendu

try:
    import vectorbt as vbt
except ImportError:  # pragma: no cover
    vbt = None

CFTC = os.path.join(PY_DIR, ".cache", "cftc")
CODES = {"132741": "ED", "134741": "SR3", "043602": "10Y", "020601": "30Y"}
DERNIER_ED, PREMIER_SR3 = pd.Timestamp("2023-04-11"), pd.Timestamp("2023-04-18")
FERMETURES = ((pd.Timestamp("2018-12-25"), pd.Timestamp("2019-03-05"), pd.Timestamp("2019-03-08")),
              (pd.Timestamp("2025-09-30"), pd.Timestamp("2026-01-13"), pd.Timestamp("2026-01-23")))
DELAI_PUBLICATION, TRIMESTRE = pd.Timedelta(days=6), pd.Timedelta(days=91)
B0, B1 = -0.01, 0.44                                   # % (tableau 7, regression 2)
ENTREE, SORTIE = (9, 30), (13, 45)
HEURES = 4.25
ESSAIS = 435
MICRO = {"ES": ("MES", 5.0), "NQ": ("MNQ", 2.0), "YM": ("MYM", 0.5)}
SD_PAPIER = 0.19 * math.sqrt(160) / 3.24 * 100        # 74,2 pb
EFFET_PB = 1.085 / math.sqrt(8) * SD_PAPIER            # 28,5 pb par reunion


# =============================================================================
#  Signal COT
# =============================================================================
def cot_traders() -> pd.DataFrame:
    """Rapports hebdomadaires : nombres de speculateurs longs et courts de l Eurodollar, du SOFR 3 mois, du 10 et du 30 ans."""
    morceaux = []
    for f in sorted(glob.glob(os.path.join(CFTC, "deacot*.zip"))):
        z = zipfile.ZipFile(f)
        d = pd.read_csv(z.open(z.namelist()[0]), low_memory=False)
        d.columns = [c.strip() for c in d.columns]
        code = d["CFTC Contract Market Code"].astype(str).str.strip()
        g = code.isin(CODES)
        morceaux.append(pd.DataFrame({
            "marche": code[g].map(CODES).to_numpy(), "date": pd.to_datetime(d.loc[g, "As of Date in Form YYYY-MM-DD"]).to_numpy(),
            "longs": d.loc[g, "Traders-Noncommercial-Long (All)"].astype(float).to_numpy(),
            "courts": d.loc[g, "Traders-Noncommercial-Short (All)"].astype(float).to_numpy()}))
    c = pd.concat(morceaux).drop_duplicates(["marche", "date"]).sort_values(["marche", "date"]).reset_index(drop=True)
    c["sp"] = c.longs - c.courts
    return c


def publication(dates: pd.Series) -> pd.Series:
    """Premier jour ou le rapport peut servir (strictement apres) : mesure + 6 jours, ou fin du rattrapage des fermetures."""
    p = dates + DELAI_PUBLICATION
    for debut, fin, pub in FERMETURES:
        p = p.where(~((dates >= debut) & (dates <= fin)), pub)
    return p


def binaire(c: pd.DataFrame) -> pd.DataFrame:
    """Binaire de pentification par rapport, avec le substitut 3M fige (Eurodollar puis SOFR 3 mois)."""
    w = c.pivot(index="date", columns="marche", values="sp")
    m3 = pd.Series(np.where(w.index <= DERNIER_ED, w.get("ED"), np.where(w.index >= PREMIER_SR3, w.get("SR3"), np.nan)),
                   index=w.index)
    x = pd.DataFrame({"3M": m3, "10Y": w["10Y"], "30Y": w["30Y"]}).dropna()
    moy = x.mean(axis=1)
    b = pd.DataFrame({"exsp3m": x["3M"] - moy, "exsp30y": x["30Y"] - moy}, index=x.index)
    b["binaire"] = ((b.exsp3m > 0) & (b.exsp30y < 0)).astype(float)
    b["source_3m"] = np.where(b.index <= DERNIER_ED, "ED", "SR3")
    b["publication"] = publication(pd.Series(b.index, index=b.index))
    return b


def steep(b: pd.DataFrame, jour: pd.Timestamp) -> tuple[float, int]:
    """STEEP connu le matin de `jour` : moyenne du binaire des rapports publies avant et mesures dans les 91 jours."""
    ok = (b.publication < jour) & (b.index > jour - TRIMESTRE) & (b.index <= jour)
    n = int(ok.sum())
    return (float(b.loc[ok, "binaire"].mean()) if n else math.nan), n


def signaux(b: pd.DataFrame, reunions: pd.DatetimeIndex) -> pd.DataFrame:
    """Pour chaque reunion k : STEEP a la reunion k-1, rendement prevu (%) et sens (+1 achat, -1 vente)."""
    lignes = []
    for k in range(1, len(reunions)):
        s, n = steep(b, reunions[k - 1])
        prevu = B0 + B1 * s if np.isfinite(s) else math.nan
        lignes.append(dict(reunion=reunions[k], date_signal=reunions[k - 1], steep=s, n_rapports=n, prevu=prevu,
                           sens=(1 if prevu > 0 else -1) if np.isfinite(prevu) else 0))
    return pd.DataFrame(lignes).set_index("reunion")


# =============================================================================
#  Trades
# =============================================================================
def fenetre(m, jours: pd.DatetimeIndex, sens: np.ndarray) -> pd.DataFrame:
    """Position `sens` de 9:30 a 13:45 ET chaque jour ; prix reels, motif d exclusion, rendement signe (pb)."""
    ta, tb = instants(jours, *ENTREE, ET), instants(jours, *SORTIE, ET)
    pa, ia = prix_a(m, ta)
    pb, ib = prix_a(m, tb)
    ok = np.isfinite(pa) & np.isfinite(pb) & (ia >= 0) & (ib >= 0)
    cid = contrats(m)
    roll = np.zeros(len(jours), bool)
    roll[ok] = cid[ib[ok]] != cid[ia[ok]]
    motif = np.where(sens == 0, "signal absent", np.where(~ok, "prix absent", np.where(roll, "changement d echeance", "")))
    f = pd.DataFrame(dict(ta=ta, tb=tb, pa=reel(m, pa, ia), pb=reel(m, pb, ib), sens=sens, motif=motif), index=jours)
    f["brut_pb"] = np.where(f["motif"] == "", f["sens"] * np.log(f["pb"] / f["pa"]) * 1e4, np.nan)
    return f


def jours_trades(m, sig: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Reunions dans les donnees (strategie, achat systematique) et temoin 7 jours plus tard."""
    ouvres = set(jours_ouvres_us(m))
    debut, fin = pd.Timestamp(m.t[0], unit="ns").normalize(), pd.Timestamp(m.t[-1], unit="ns").normalize()
    s = sig[(sig.index > debut) & (sig.index <= fin)]
    f = fenetre(m, pd.DatetimeIndex(s.index), s["sens"].to_numpy())
    naif = fenetre(m, pd.DatetimeIndex(s.index), np.ones(len(s), int))
    tj = pd.DatetimeIndex(s.index) + pd.Timedelta(days=7)
    garde = np.array([d in ouvres and d <= fin for d in tj])
    tem = fenetre(m, tj[garde], s["sens"].to_numpy()[garde])
    return f, naif, tem


def serie_journaliere(m, f: pd.DataFrame, cout: float) -> pd.Series:
    """Rendement net (fraction) rattache au jour de la reunion, 0 les autres seances de la periode."""
    j = jours_ouvres_us(m)
    j = j[(j >= f.index[0]) & (j <= f.index[-1])]
    r = pd.Series(0.0, index=j)
    t = f[f["motif"] == ""]
    r.loc[t.index] = (np.exp(t["brut_pb"] / 1e4) - 1) - cout / 1e4
    return r


# =============================================================================
#  Verifications (critere 9)
# =============================================================================
def verif_horodatage(m, jours: pd.DatetimeIndex) -> str:
    debut = pd.DatetimeIndex(m.t - NS_MIN).tz_localize("UTC").tz_convert(ET)
    sel = debut.tz_localize(None).normalize().isin(jours)
    tod = (debut.hour * 60 + debut.minute)[sel]
    vol = pd.Series(m.v[sel]).groupby(np.asarray(tod)).median()
    out = []
    for h, mi, lib in ((9, 30, "ouverture"), (13, 45, "sortie"), (14, 0, "annonce")):
        k = h * 60 + mi
        out.append(f"{h}:{mi:02d} {lib} x{vol.get(k, np.nan) / vol.reindex([k - 3, k - 2, k - 1]).mean():.1f}")
    top = vol.nlargest(4).index
    return ("(a) horodatage, jours de FOMC (volume median de la barre / 3 barres precedentes) : " + ", ".join(out)
            + " | 4 plus gros volumes medians : " + ", ".join(f"{k // 60}:{k % 60:02d}" for k in sorted(top)))


class _Copie:
    """Marche dont les prix des barres commencant apres un instant sont modifies (test d anticipation)."""

    def __init__(self, m, apres_ns: int):
        self.t, self.n, self.offset = m.t, m.n, m.offset
        self._contrat = contrats(m)
        fut = (m.t - NS_MIN) > apres_ns
        self.o, self.c = np.where(fut, m.o * 1.5, m.o), np.where(fut, m.c * 1.5, m.c)


def verif_anticipation(m, f: pd.DataFrame, b: pd.DataFrame, sig: pd.DataFrame) -> str:
    t = f[f["motif"] == ""]
    diff_a = diff_b = 0
    for d in t.itertuples():
        for instant, col in ((d.ta, "a"), (d.tb, "b")):
            c = _Copie(m, int(instant))
            px, idx = prix_a(c, np.array([instant]))
            v = reel(c, px, idx)[0]
            ref = d.pa if col == "a" else d.pb
            if not math.isclose(v, ref, abs_tol=1e-9):
                diff_a += col == "a"
                diff_b += col == "b"
    rng = np.random.default_rng(11)
    diff_s = 0
    echantillon = sig.dropna(subset=["steep"]).sample(min(30, len(sig)), random_state=5)
    for d in echantillon.itertuples():
        bb = b.copy()
        fut = bb.publication >= d.date_signal
        bb.loc[fut, "binaire"] = rng.integers(0, 2, int(fut.sum())).astype(float)
        s, _ = steep(bb, d.date_signal)
        diff_s += not math.isclose(s, d.steep, abs_tol=1e-12)
    etat = "INCHANGES" if diff_a == diff_b == 0 else f"DIFFERENTS (BUG : entree {diff_a}, sortie {diff_b})"
    etat_s = "INCHANGE" if diff_s == 0 else f"DIFFERENT (BUG : {diff_s} reunions)"
    return (f"(b) anticipation : (b1) prix futurs x1,5 sur les {len(t)} trades -> prix d entree et de sortie {etat} ; "
            f"(b2) rapports COT publies apres la date du signal tires au hasard sur {len(echantillon)} reunions -> STEEP {etat_s}")


def verif_vectorbt(root: str, f: pd.DataFrame) -> str:
    if vbt is None:
        return "(c) vectorbt absent : rejeu non fait"
    t = f[f["motif"] == ""]
    pv = COUTS[root][1]
    moteur = (t["sens"] * (t["pb"] - t["pa"]) * pv).to_numpy()
    ts = np.r_[t["ta"].to_numpy(), t["tb"].to_numpy()]
    px = np.r_[t["pa"].to_numpy(), t["pb"].to_numpy()]
    taille = np.r_[t["sens"].to_numpy(float), -t["sens"].to_numpy(float)]
    o = np.argsort(ts, kind="stable")
    prix = pd.Series(px[o] * pv, index=pd.to_datetime(ts[o]))
    pf = vbt.Portfolio.from_orders(prix, size=pd.Series(taille[o], index=prix.index), init_cash=1e9, fees=0.0,
                                   freq="1min")
    pnl_vbt = pf.trades.records_readable.sort_values("Entry Timestamp")["PnL"].to_numpy()
    ecart = float(np.max(np.abs(pnl_vbt - moteur))) if len(pnl_vbt) == len(moteur) else math.inf
    return (f"(c) rejeu vectorbt : {len(pnl_vbt)} trades contre {len(moteur)} au moteur, ecart maximal de P&L brut "
            f"{ecart:.6f} $ -> {'IDENTIQUE' if ecart < 1e-6 else 'DIFFERENT (BUG)'}")


def verif_cinq(root: str, f: pd.DataFrame, sig: pd.DataFrame) -> list[str]:
    t = f[f["motif"] == ""]
    tick, pv = COUTS[root][0], COUTS[root][1]
    out = ["(d) 5 trades tires au hasard (graine 7), a verifier a la main :"]
    for d in t.sample(5, random_state=7).sort_index().itertuples():
        ha = pd.Timestamp(d.ta).tz_localize("UTC").tz_convert(ET)
        hb = pd.Timestamp(d.tb).tz_localize("UTC").tz_convert(ET)
        s = sig.loc[d.Index]
        brut = d.sens * (d.pb - d.pa) * pv
        frais = 2 * (tick * pv + COMMISSION)
        out.append(f"    FOMC du {d.Index:%Y-%m-%d} : STEEP {s.steep:.3f} ({s.n_rapports} rapports au {s.date_signal:%Y-%m-%d}) "
                   f"-> prevu {s.prevu:+.3f} % -> {'ACHAT' if d.sens > 0 else 'VENTE'} {ha:%a %H:%M} ET a {d.pa:.2f} | "
                   f"debouclage {hb:%H:%M} ET a {d.pb:.2f} | brut {brut:+.2f} $ - frais {frais:.2f} $ = {brut - frais:+.2f} $")
    return out


# =============================================================================
#  Etude
# =============================================================================
def etude(sortie: str | None = None, log=print) -> dict:
    t0 = datetime.now()
    L: list[str] = []
    pr = L.append
    pr("=" * 116)
    pr(" PARIS DE PENTIFICATION (COT) ET ES LE JOUR DU FOMC, 9:30 -> 13:45 ET - PARK (FEDS 2019-025) - UN ESSAI (n° 435)")
    pr("=" * 116)
    pr("Regle figee : STEEP (moyenne sur 91 jours du binaire EXSP_3M > 0 et EXSP_30Y < 0, rapports publies) a la reunion")
    pr("precedente ; prevu = -0,01 + 0,44 x STEEP (%) ; achat si prevu > 0, vente sinon ; 3M = Eurodollar jusqu au 2023-04-11,")
    pr("SOFR 3 mois ensuite. Temoin : meme sens, meme fenetre, 7 jours apres la reunion.\n")
    b = binaire(cot_traders())
    sig = signaux(b, fomc())
    res = {}
    for root in ("ES", "NQ", "YM"):
        m = marche(root)
        f, naif, tem = jours_trades(m, sig)
        prix = float(np.nanmedian(f["pa"]))
        c1, c2, cm = cout_pb(root, prix), cout_pb(root, prix, ticks=2), cout_pb(root, prix, micro=True)
        n_ok = int((f["motif"] == "").sum())
        if root == "ES":
            pr(f"Calcul de puissance (critere 6, effet du papier {EFFET_PB:.1f} pb par reunion, ecart-type {SD_PAPIER:.1f} pb) :")
        pr(f"  {root} : t attendu {t_attendu(EFFET_PB, c1, SD_PAPIER, n_ok):+.2f} (cout {c1:.2f} pb, {n_ok} reunions) | "
           f"{MICRO[root][0]} {t_attendu(EFFET_PB, cm, SD_PAPIER, n_ok):+.2f} (cout {cm:.2f} pb)")
        crit = criteres(f["brut_pb"].dropna(), tem["brut_pb"].dropna(), c1)
        r = serie_journaliere(m, f, c1)
        x, xm = PC.mesures(r, ESSAIS), PC.mesures(serie_journaliere(m, f, cm), ESSAIS)
        ans = (r.index[-1] - r.index[0]).days / 365.25
        res[root] = dict(m=m, f=f, naif=naif, temoin=tem, crit=crit, mesures=x, micro=xm, cout=c1, stress=c2,
                         cout_micro=cm, r=r, heures_an=n_ok * HEURES / ans)
    pr("")
    pr("Verification du calcul (critere 9)")
    es, f = res["ES"]["m"], res["ES"]["f"]
    pr("  " + verif_horodatage(es, pd.DatetimeIndex(f.index)))
    pr("  " + verif_anticipation(es, f, b, sig))
    pr("  " + verif_vectorbt("ES", f))
    for s in verif_cinq("ES", f, sig):
        pr("  " + s)
    motifs = f["motif"].replace("", "retenue").value_counts()
    t = f[f["motif"] == ""]
    s_es = sig.loc[f.index]
    pr(f"  (e) comptes ES : {len(f)} reunions {f.index[0]:%Y-%m-%d} -> {f.index[-1]:%Y-%m-%d} ; "
       + " ; ".join(f"{k} {v}" for k, v in motifs.items())
       + f" ; achats {int((t.sens > 0).sum())}, ventes {int((t.sens < 0).sum())} ; temoin retenu "
       f"{int((res['ES']['temoin']['motif'] == '').sum())} ; rapports COT par signal : min {s_es.n_rapports.min()}, "
       f"median {s_es.n_rapports.median():.0f}, max {s_es.n_rapports.max()} ; rapports {b.index[0]:%Y-%m-%d} -> "
       f"{b.index[-1]:%Y-%m-%d} (3M : ED {int((b.source_3m == 'ED').sum())}, SR3 {int((b.source_3m == 'SR3').sum())}) ; "
       f"{res['ES']['heures_an']:.0f} h/an\n")
    for root in ("ES", "NQ", "YM"):
        z = res[root]
        crit, x, xm, c1, c2, cm = z["crit"], z["mesures"], z["micro"], z["cout"], z["stress"], z["cout_micro"]
        net = z["f"]["brut_pb"].dropna() - c1
        naif = z["naif"]["brut_pb"].dropna()
        pr(f"--- {root}{' (ESSAI)' if root == 'ES' else ' (replique, pas un essai)'} : {crit['n']} reunions")
        pr(f"    brut {crit['moyenne']:+.2f} pb (t {crit['t']:+.2f}) | 2016-2020 {crit['m1']:+.2f} (t {crit['t1']:+.2f}) | "
           f"2021-2026 {crit['m2']:+.2f} (t {crit['t2']:+.2f}) | papier 2003-2017 : +{EFFET_PB:.1f}")
        pr(f"    temoin (7 jours apres) {crit['temoin']:+.2f} pb -> Welch {crit['welch']:+.2f} | achat systematique (reference) "
           f"{naif.mean():+.2f} pb (t {naif.mean() / naif.std(ddof=1) * math.sqrt(len(naif)):+.2f})")
        pr(f"    cout aller-retour {c1:.2f} pb -> net {crit['net']:+.2f} pb ; sans les 3 meilleures reunions {crit['sans3']:+.2f} pb ; "
           f"stress 2 ticks {crit['moyenne'] - c2:+.2f} pb ; gain total {net.sum():+.0f} pb")
        an = net.groupby(net.index.year).mean()
        pr("    net par annee (pb) : " + " ".join(f"{a}:{v:+.1f}" for a, v in an.items()))
        pr(f"    vectorbt ({root}, 1 tick) : Sharpe {x['sharpe']:+.2f} [IC 95 % {x['ic_bas']:+.2f} ; {x['ic_haut']:+.2f}] | "
           f"avant 2021 {x['sharpe_p1']:+.2f} | apres {x['sharpe_p2']:+.2f} | deflate ({ESSAIS} essais) {x['dsr']:.2f} | "
           f"perte max {x['perte_max']:.1%}")
        pr(f"    micro {MICRO[root][0]} (cout {cm:.2f} pb) : net {crit['moyenne'] - cm:+.2f} pb | Sharpe {xm['sharpe']:+.2f} "
           f"[IC bas {xm['ic_bas']:+.2f}] | deflate {xm['dsr']:.2f}")
        pr(f"    heures en position : {z['heures_an']:.0f} h/an ; rendement net par heure {crit['net'] / HEURES:+.2f} pb")
        echecs = [k for k, v in crit["tests"].items() if not v]
        if not (x["ic_bas"] > 0):
            echecs.append("IC bas du Sharpe > 0")
        if not (x["sharpe_p1"] > 0 and x["sharpe_p2"] > 0):
            echecs.append("Sharpe > 0 avant ET apres 2021")
        if not (x["dsr"] >= 0.95):
            echecs.append("Sharpe deflate >= 0,95")
        z["echecs"] = echecs
        pr(f"    VERDICT : {'PASSE les criteres 10-18' if not echecs else 'ECHOUE (' + ' ; '.join(echecs) + ')'}")
        if not echecs:
            pr("    " + correlations(z["r"]))
        pr("")
    v = res["ES"]["echecs"]
    pr("Synthese : " + ("l essai ES passe les criteres 10-18 ; restent la correlation (n° 20) et la validation."
                        if not v else "REJETEE (l essai ES echoue). Aucune variante ne sera testee (pas de surajustement)."))
    pr(f"Calcul en {(datetime.now() - t0).total_seconds():.0f} s.")
    sortie = sortie or os.path.join(PY_DIR, "recherche", "resultats_pente_fomc.txt")
    with open(sortie, "w", encoding="utf-8") as fh:
        fh.write("\n".join(L) + "\n")
    log("\n".join(L))
    return res


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--sortie", default=None)
    a = ap.parse_args(argv)
    etude(a.sortie)


if __name__ == "__main__":
    main()
