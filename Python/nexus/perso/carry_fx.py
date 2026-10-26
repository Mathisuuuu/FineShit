"""Portage de devises (carry) sur 6E 6B 6J 6A : strategie construite sur neuf travaux (NBER, Columbia, MIT, Chicago...).

    python -m nexus.perso.carry_fx [--sortie resultats_carry_fx.txt]

PROTOCOLE ECRIT LE 2026-10-11, AVANT TOUT CALCUL SUR NOS DONNEES (methode : memoire « methode-strategie-papiers »).
Deuxieme des candidats classes « du plus prometteur au moins prometteur » apres la lecture des meta-etudes.

Sources (texte complet lu = [T], resume seulement = [R])
 [LRV14] [T] H. Lustig (UCLA/Stanford), N. Roussanov (Wharton), A. Verdelhan (MIT), « Countercyclical Currency Risk Premia »,
         Journal of Financial Economics 111, 2014 (NBER w16427) : « dollar carry trade » = acheter TOUTES les devises
         etrangeres contre le dollar quand le taux moyen etranger (pays developpes) depasse le taux court americain, les
         vendre sinon ; 1983-2010, 5,60 % par an, Sharpe 0,66 (pays developpes), faible asymetrie (-0,27) ; le carry
         « devise par devise » ne fait presque rien (0,5 %/an, Sharpe ~0 apres couts) ; le carry HML sans dollar :
         Sharpe ~0,3.
 [DHL17] [T] K. Daniel (Columbia), R. Hodrick (Columbia), Z. Lu, « The Carry Trade: Risks and Drawdowns », Critical Finance
         Review 6, 2017 : G10 contre le dollar 1976-2013. EQ (eq. 9) = +1/N sur chaque devise dont le taux depasse celui
         du dollar, -1/N sinon : 3,96 %/an, Sharpe 0,78. EQ-0$ (eq. 12, sans dollar) = +1/N au-dessus de la mediane des
         taux etrangers, -1/N en dessous : 1,61 %/an, Sharpe 0,49, entierement explique par les facteurs actions et
         obligations. EQ-D$ (« dollar dynamique », version G10 de LRV14 avec la mediane) : 5,54 %/an, Sharpe 0,68, alpha
         significatif quels que soient les facteurs. Conclusion : l anomalie tient surtout a l exposition CONDITIONNELLE
         au dollar.
 [KMPV18] [T] R. Koijen (Chicago), T. Moskowitz (Yale/AQR), L. H. Pedersen (CBS/AQR), E. Vrugt, « Carry », Journal of
         Financial Economics 127, 2018 (NBER w19325) : carry d une devise = (taux etranger - taux local) / (1 + taux
         local), lu sur le terme ; carry devises 1983-2012 Sharpe 0,68, asymetrie negative.
 [HM19]  [T] T. Hassan (Chicago/Boston U.), R. Mano (FMI), « Forward and Spot Exchange Rates in a Multi-Currency World »,
         Quarterly Journal of Economics 134, 2019 (NBER w20294) : le carry vient surtout de differences PERMANENTES entre
         devises (« static trade », ~70 % du carry) ; le « dollar trade » (variation dans le temps du differentiel moyen,
         = LRV14) explique la plupart du « forward premium puzzle » mais son coefficient est imprecis (significatif a 5 %
         dans 1 specification sur 16 ; Sharpe 0,25 avant couts).
 [ACCG20] [T] S. Andrews, R. Colacito (UNC), M. Croce (Bocconi), F. Gavazzoni (INSEAD), « Concealed Carry », 2020 (publie
         au Journal of Financial Economics 2024) : carry traditionnel 3 portefeuilles G10 : 8,86 %/an (Sharpe 1,16)
         avant 08/2007 ; 1,62 %/an (t 0,60, Sharpe 0,18) apres ; baisse expliquee par la compression des taux courts.
 [FPQZ22] [R] Z. Fan, A. Paseka, Z. Qi, Q. Zhang, « Currency carry trade: The decline in performance after the 2008 Global
         Financial Crisis », Journal of International Financial Markets, Institutions and Money 76, 2022 : baisse apres
         2008 expliquee par la disparition du risque de baisse (downside risk) du portefeuille de carry.
 [HTWL24] [R] P.-H. Hsu (NTHU), M. P. Taylor (Washington University), Z. Wang, Y. Li, « The out-of-sample performance of
         carry trades », Journal of International Money and Finance 143, 2024 : 48 pays, 36 ans, corrections de
         « data snooping » : les carry rentables sur une periode ne le sont generalement pas ensuite ; la seule periode
         coherente est 1998-2005 ; grande part de chance.
 [BNP08] [R] M. Brunnermeier (Princeton), S. Nagel (Stanford), L. H. Pedersen (NYU), « Carry Trades and Currency Crashes »,
         NBER Macroeconomics Annual 2008 : asymetrie negative, krachs quand la liquidite se tarit (VIX en hausse).
 [BP20]  [R] G. Bekaert (Columbia), G. Panayotov, « Good Carry, Bad Carry », Journal of Financial and Quantitative
         Analysis 55, 2020 : une partie du carry G10 (portefeuilles avec AUD et JPY aux extremes) concentre le risque
         de krach ; d autres combinaisons ont un meilleur Sharpe (non reproductible avec 4 devises).
Lecture commune : le carry classique sans dollar (HML, EQ-0$) est explique par des facteurs de risque et s est
effondre apres 2008 (ACCG20, FPQZ22, HTWL24) ; la partie qui resiste aux facteurs est le « dollar carry » (LRV14,
DHL17), mais sa preuve statistique est fragile (HM19). Strategie retenue : le dollar carry de LRV14 tel quel, sur nos
quatre devises (EUR, GBP, JPY, AUD), le seul candidat que les contre-papiers n attaquent pas directement apres 2008.

Donnees
  futures 6E 6B 6J 6A (Databento, cotes en dollars par devise : acheter le contrat = acheter la devise) : cloture 16:00 ET
  au prix reel, rendement quotidien (jours de changement d echeance exclus). Le rendement d un future de change est deja
  un rendement EXCEDENTAIRE de devise (il incorpore le differentiel de taux : KMPV18, eq. 7), comme les rendements a
  terme des papiers.
  Taux : taux interbancaires a 3 mois de l OCDE publies par la FRED (IR3TIB01{US,EZ,GB,JP,AU}M156N, moyennes
  mensuelles), en remplacement des points a terme a 1 mois des papiers (le signe du differentiel est le meme a ces
  horizons). Les series s arretent avant nos prix (zone euro et Royaume-Uni : 2026-01 ; Japon : 2026-07) : derniere
  valeur prolongee, signale dans le rapport.
  Decision : la moyenne du mois m (connue a la fin du mois m) fixe les positions de tout le mois m+1.

ETAPE 1 - l anomalie
  1a. differentiels de taux moyens contre le dollar par periode (2016-2020 / 2021-2026) ; part des mois ou le dollar
      carry est vendeur du dollar ; composition du carry sans dollar.
  1b. regression de Fama sous forme de rendement excedentaire (mensuel) : rx(j, m+1) = a + b x (i_j - i_US)(m) / 12,
      par devise et empilee, et regression de LRV14 du panier sur le differentiel moyen (AFD), par periode, t robustes
      (White). Carry present <=> b > 0 (b = 0 sous la parite des taux non couverte, b = 1 si le change ne bouge pas).
ETAPE 2 - strategies (regles figees, poids constants dans le mois, rendements quotidiens nets de couts)
  - V  = dollar carry de LRV14 : poids +1/4 sur chaque devise si la moyenne des 4 taux etrangers depasse le taux
         americain, -1/4 sinon ;
  - R1 = EQ de DHL17 (anomalie brute, carry devise par devise contre le dollar) : signe(i_j - i_US) / 4 ;
  - R0 = EQ-0$ de DHL17 (carry classique sans dollar) : signe(i_j - mediane des 4 taux) / 4 ;
  - temoin = panier toujours acheteur, +1/4 sur chaque devise (facteur dollar RX de Lustig et al., l exposition
    passive d un investisseur americain) ;
  - couts : |variation de poids| x (1 tick + 2,50 $) / prix par cote, plus le roulement trimestriel (2 cotes x |poids|),
    stress 2 ticks.
  Criteres (fixes avant le calcul), sur les rendements quotidiens nets de V : t >= 3 ; meme signe et t >= 1,5 sur
  2016-2020 et 2021-2026 ; Welch >= 2 contre le temoin ; net > 0 ; net > 0 sans les 3 meilleurs jours ; Sharpe deflate
  >= 0,95 pour 47 essais (44 precedents + V, R0, R1).
  Limite annoncee avant le calcul : depuis 2016 le taux americain a ete le plus souvent au-dessus de la moyenne
  etrangere ; si le signe de V change rarement, V est presque un pari fixe « acheteur de dollar » et le test mesure la
  derive du dollar plus que le mecanisme de LRV14. Le rapport donne la part des mois de chaque signe et, a titre de
  contexte seulement (ni critere ni essai), la position fixe de meme signe moyen (« static trade » de HM19).
Compatibilite prop firm : positions tenues un mois : NON compatible avec une prop firm intraday.
"""
from __future__ import annotations

import argparse
import math
import os
from datetime import datetime

import numpy as np
import pandas as pd

from .alternatives import dsr
from .soixante import COMMISSION, COUTS, PY_DIR, criteres, exporter, marche
from .tendance import quotidien, sharpe

DEVISES = {"6E": "EZ", "6B": "GB", "6J": "JP", "6A": "AU"}
COUPURE = pd.Timestamp("2021-01-01")
N_ESSAIS, SEUIL_DSR = 47, 0.95
FRED_DIR = os.path.join(PY_DIR, ".cache", "fred")


# =============================================================================
#  Donnees
# =============================================================================
def taux(fin: pd.Period | None = None) -> pd.DataFrame:
    """Taux a 3 mois (% par an), mensuels (PeriodIndex), colonnes US EZ GB JP AU ; derniere valeur prolongee jusqu a fin."""
    out = {}
    for pays in ("US", *DEVISES.values()):
        f = pd.read_csv(os.path.join(FRED_DIR, f"IR3TIB01{pays}M156N.csv"))
        s = pd.to_numeric(f.iloc[:, 1], errors="coerce")
        s.index = pd.to_datetime(f.iloc[:, 0]).dt.to_period("M")
        out[pays] = s.dropna()
    t = pd.DataFrame(out).sort_index()
    if fin is not None and fin > t.index[-1]:
        t = t.reindex(pd.period_range(t.index[0], fin, freq="M"))
    return t.ffill()


def donnees() -> dict:
    return {mk: quotidien(marche(mk)) for mk in DEVISES}


# =============================================================================
#  Poids mensuels (decision avec les taux du mois m -> positions du mois m+1)
# =============================================================================
def differentiels(t: pd.DataFrame) -> pd.DataFrame:
    """i_j - i_US par contrat (points de %)."""
    return pd.DataFrame({mk: t[p] - t["US"] for mk, p in DEVISES.items()})


def poids_v(t: pd.DataFrame) -> pd.DataFrame:
    """LRV14 : +1/4 sur chaque devise si le taux moyen etranger depasse le taux americain, -1/4 sinon."""
    afd = t[list(DEVISES.values())].mean(axis=1) - t["US"]
    sgn = np.where(afd > 0, 1.0, -1.0)
    return pd.DataFrame({mk: sgn / 4 for mk in DEVISES}, index=t.index)


def poids_eq(t: pd.DataFrame) -> pd.DataFrame:
    """DHL17 EQ : signe(i_j - i_US) / 4."""
    return np.sign(differentiels(t)) / 4


def poids_eq0(t: pd.DataFrame) -> pd.DataFrame:
    """DHL17 EQ-0$ : signe(i_j - mediane des taux etrangers) / 4."""
    f = pd.DataFrame({mk: t[p] for mk, p in DEVISES.items()})
    return np.sign(f.sub(f.median(axis=1), axis=0)) / 4


def quotidiens(wm: pd.DataFrame, index: pd.DatetimeIndex) -> pd.DataFrame:
    """Poids du mois m+1 = decision du mois m, etales sur les jours de bourse."""
    w = wm.copy()
    w.index = w.index + 1
    return w.reindex(index.to_period("M")).set_axis(index)


# =============================================================================
#  Rendements
# =============================================================================
def rendements(d: dict) -> pd.DataFrame:
    return pd.DataFrame({mk: d[mk].r for mk in DEVISES})


def roulements(d: dict) -> pd.DataFrame:
    """Jours de changement d echeance : rendement manquant alors que les deux clotures existent."""
    return pd.DataFrame({mk: d[mk].r.isna() & d[mk].prix.notna() & d[mk].prix.shift(1).notna() for mk in DEVISES})


def rendement(w: pd.DataFrame, d: dict, ticks: int) -> pd.Series:
    r = rendements(d).reindex(w.index)
    brut = (w * r).sum(axis=1, min_count=1)
    prix = {mk: float(np.nanmedian(d[mk].prix.iloc[-500:])) for mk in w.columns}
    cu = pd.Series({mk: (ticks * COUTS[mk][0] + COMMISSION / COUTS[mk][1]) / prix[mk] for mk in w.columns})
    rot = w.fillna(0).diff().abs()
    rot = rot + 2 * w.abs().where(roulements(d).reindex(w.index).fillna(False).astype(bool), 0.0)
    return (brut - (rot * cu).sum(axis=1)).dropna()


def ols_white(y: np.ndarray, x: np.ndarray) -> tuple[float, float, int]:
    """Pente et t de White de y = a + b x."""
    ok = np.isfinite(y) & np.isfinite(x)
    y, x = y[ok], x[ok]
    n = len(y)
    if n < 10:
        return math.nan, math.nan, n
    X = np.c_[np.ones(n), x]
    xtx = np.linalg.inv(X.T @ X)
    b = xtx @ X.T @ y
    e = y - X @ b
    v = xtx @ (X.T * e ** 2) @ X @ xtx * n / (n - 2)
    return float(b[1]), float(b[1] / math.sqrt(v[1, 1])), n


def regressions(rm: pd.DataFrame, dif: pd.DataFrame, periode) -> list:
    """Fama (forme excedentaire) par devise, empilee, et LRV14 (panier sur le differentiel moyen)."""
    x = (dif / 1200).shift(1).reindex(rm.index)                           # differentiel du mois m, en fraction mensuelle
    sel = periode(rm.index)
    lignes = []
    for mk in DEVISES:
        lignes.append((mk,) + ols_white(rm[mk][sel].to_numpy(), x[mk][sel].to_numpy()))
    lignes.append(("empile",) + ols_white(rm[sel].to_numpy().ravel(), x[sel].to_numpy().ravel()))
    lignes.append(("panier/AFD",) + ols_white(rm[sel].mean(axis=1).to_numpy(), x[sel].mean(axis=1).to_numpy()))
    return lignes


# =============================================================================
#  Etude
# =============================================================================
def etude(sortie: str | None = None, log=print) -> dict:
    t0 = datetime.now()
    L = []
    pr = L.append
    pr("=" * 118)
    pr(" PORTAGE DE DEVISES (CARRY) SUR 6E 6B 6J 6A : STRATEGIE CONSTRUITE SUR NEUF TRAVAUX (LRV, DANIEL-HODRICK-LU, KMPV...)")
    pr("=" * 118)
    pr("Protocole et sources : en-tete de nexus/perso/carry_fx.py (ecrit avant le calcul).\n")
    d = donnees()
    r = rendements(d)
    jours = r.dropna(how="all").index
    t = taux(jours[-1].to_period("M"))
    derniers = {p: str(pd.read_csv(os.path.join(FRED_DIR, f"IR3TIB01{p}M156N.csv")).iloc[-1, 0])[:7] for p in t.columns}
    pr("Taux FRED : derniere observation " + ", ".join(f"{p} {m}" for p, m in derniers.items()) +
       f" ; prolonges jusqu a {t.index[-1]}.")
    dif = differentiels(t)
    mois = jours.to_period("M").unique()
    decis = dif.reindex(mois - 1)                                          # differentiels qui decident chaque mois tenu
    decis.index = mois

    pr("\nETAPE 1 - l anomalie")
    pr("  1a. differentiel moyen contre le dollar (points de %) :")
    for lib, sel in (("2016-2020", decis.index < COUPURE.to_period("M")), ("2021-2026", decis.index >= COUPURE.to_period("M"))):
        pr(f"      {lib} : " + " | ".join(f"{mk} {decis[mk][sel].mean():+.2f}" for mk in DEVISES) +
           f" | moyenne {decis[sel].mean(axis=1).mean():+.2f}")
    wv_m, weq_m, weq0_m = poids_v(t), poids_eq(t), poids_eq0(t)
    sv = np.sign(wv_m["6E"].reindex(mois - 1)).to_numpy()
    pr(f"      dollar carry (V) : vendeur du dollar {np.mean(sv > 0):.0%} des {len(sv)} mois, acheteur {np.mean(sv < 0):.0%} ; "
       f"changements de signe : {int(np.sum(sv[1:] != sv[:-1]))}")
    f = pd.DataFrame({mk: t[p] for mk, p in DEVISES.items()})
    med = np.sign((f.sub(f.median(axis=1), axis=0)).reindex(mois - 1))
    pr("      carry sans dollar (R0) : part des mois achete / vendu : " +
       " | ".join(f"{mk} {np.mean(med[mk] > 0):.0%}/{np.mean(med[mk] < 0):.0%}" for mk in DEVISES))
    regle_med = np.where(f.median(axis=1) > t["US"], 1.0, -1.0)
    accord = float(np.mean(regle_med[np.isin(t.index, mois - 1)] == np.sign(wv_m["6E"].reindex(mois - 1)).to_numpy()))
    pr(f"      la regle de DHL17 (mediane) et celle de LRV14 (moyenne) donnent le meme signe {accord:.0%} des mois")

    rm = r.groupby(r.index.to_period("M")).sum(min_count=5)
    pr("  1b. regression rx(j, m+1) = a + b x differentiel(m) (b > 0 = carry ; t de White) :")
    for lib, per in (("2016-2026", lambda ix: np.ones(len(ix), bool)),
                     ("2016-2020", lambda ix: ix < COUPURE.to_period("M")),
                     ("2021-2026", lambda ix: ix >= COUPURE.to_period("M"))):
        reg = regressions(rm, dif, per)
        pr(f"      {lib} : " + " | ".join(f"{k} b {b:+.1f} (t {tt:+.2f})" for k, b, tt, n in reg))

    pr("\nETAPE 2 - strategies (rendements quotidiens nets de couts, en pb du capital)")
    wv, weq, weq0 = (quotidiens(w, jours) for w in (wv_m, weq_m, weq0_m))
    wrx = pd.DataFrame(0.25, index=jours, columns=list(DEVISES))
    tem = rendement(wrx, d, 1)
    v = rendement(wv, d, 1)
    res = {}
    for code, w, nom in (("V", wv, "V dollar carry de Lustig, Roussanov & Verdelhan"),
                         ("R1", weq, "R1 carry devise par devise contre le dollar (EQ de Daniel et al.)"),
                         ("R0", weq0, "R0 carry sans dollar (EQ-0$ de Daniel et al.)")):
        s, s2 = rendement(w, d, 1), rendement(w, d, 2)
        c = criteres(s * 1e4, tem * 1e4, 0.0)
        p_dsr = dsr(s, N_ESSAIS)
        res[code] = dict(c, dsr=p_dsr, sharpe_an=sharpe(s), stress=sharpe(s2), nom=nom)
        pr(f"  --- {nom} : {c['n']} jours | net {c['moyenne']:+.2f} pb/j (t {c['t']:+.2f}) | 2016-2020 t {c['t1']:+.2f} | 2021-2026 t {c['t2']:+.2f}")
        pr(f"      temoin panier acheteur {c['temoin']:+.2f} pb/j, Welch {c['welch']:+.2f} | sans les 3 meilleurs jours {c['sans3']:+.2f} | "
           f"Sharpe net {sharpe(s):.2f} (stress 2 ticks {sharpe(s2):.2f}) | Sharpe deflate ({N_ESSAIS} essais) {p_dsr:.2f}")
    a, b = tem[tem.index < COUPURE], tem[tem.index >= COUPURE]
    pr(f"      temoin (panier toujours acheteur, facteur RX) : Sharpe {sharpe(tem):+.2f} (2016-2020 {sharpe(a):+.2f}, 2021-2026 {sharpe(b):+.2f})")
    signe_fixe = 1.0 if float(np.nanmean(sv)) > 0 else -1.0
    fixe = rendement(pd.DataFrame(0.25 * signe_fixe, index=jours, columns=list(DEVISES)), d, 1)
    pr(f"      contexte (HM19, ni critere ni essai) : position fixe {'vendeuse' if signe_fixe > 0 else 'acheteuse'} de dollar "
       f"(signe moyen de V), Sharpe {sharpe(fixe):+.2f} ; correlation V / position fixe {v.corr(fixe.reindex(v.index)):+.2f}")
    vv = res["V"]
    echecs = [k for k, ok in vv["tests"].items() if not ok] + ([] if vv["dsr"] >= SEUIL_DSR else [f"Sharpe deflate >= {SEUIL_DSR:.2f}"])
    pr("\nVERDICT (V) : " + ("RETENUE" if not echecs else "ECHOUE (" + " ; ".join(echecs) + ")"))
    pr(f"Calcul en {(datetime.now() - t0).total_seconds():.0f} s.")
    sortie = sortie or os.path.join(PY_DIR, "recherche", "resultats_carry_fx.txt")
    with open(sortie, "w", encoding="utf-8") as fh:
        fh.write("\n".join(L) + "\n")
    exporter("carry_fx", dict(
        titre="Portage de devises (carry) sur 6E 6B 6J 6A (neuf travaux)",
        sous="Lustig, Roussanov & Verdelhan (JFE 2014), Daniel, Hodrick & Lu (CFR 2017), Koijen et al. (JFE 2018), Hassan & Mano "
             "(QJE 2019), Andrews et al. (2020), Fan et al. (2022), Hsu et al. (JIMF 2024), Brunnermeier et al. (2008), Bekaert & "
             "Panayotov (2020). V = dollar carry (toutes les devises contre le dollar selon le differentiel moyen) ; temoin = panier "
             "toujours acheteur. Protocole : nexus/perso/carry_fx.py.",
        part_vendeur_dollar=float(np.mean(sv > 0)), changements_signe=int(np.sum(sv[1:] != sv[:-1])),
        lignes=[dict(code=k, nom=x["nom"], n=x["n"], moyenne=x["moyenne"], t=x["t"], t1=x["t1"], t2=x["t2"], temoin=x["temoin"],
                     welch=x["welch"], sans3=x["sans3"], dsr=x["dsr"], sharpe_an=x["sharpe_an"], stress=x["stress"])
                for k, x in res.items()],
        temoin_sharpe=sharpe(tem), fixe_sharpe=sharpe(fixe), echecs=echecs, retenue=not echecs))
    log("\n".join(L))
    return dict(etape2=res, echecs=echecs)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--sortie", default=None)
    a = ap.parse_args(argv)
    etude(a.sortie)


if __name__ == "__main__":
    main()
