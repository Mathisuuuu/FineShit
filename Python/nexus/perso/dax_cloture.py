"""Retournement du DAX avant la cloture de Xetra : S19-B jouee a l envers, vrai hors-echantillon 2014-2025.

    python -m nexus.perso.dax_cloture [--sortie recherche/resultats_dax_cloture.txt]

PROTOCOLE ECRIT LE 2026-10-19, AVANT TOUT CALCUL SUR 2014-2025 (methode : memoire « methode-strategie-papiers »).
Piste 2 de recherche/pistes.md.

Origine. S19-B (S19_LetfRebalance.cs, variante B) prend a 17:00 (Berlin) une position dans le sens du rendement du DAX
depuis 09:00 et la solde a 17:30. Sur FDAX (Databento, 11/03/2025 -> 28/08/2026) : 370 trades, -152 164 $ ; jouee a
l envers (nexus/perso/inversion.py : memes trades, sens oppose, frais payes une seconde fois) : +118 299 $, Sharpe 2,21.
C est une observation faite APRES COUP sur 1,5 an : elle ne prouve rien. Le test consiste a figer la regle inversee
telle quelle et a la juger sur 02/01/2014 -> 10/03/2025, une periode jamais regardee : aucun rendement du DAX n a ete
calcule dessus dans ce depot (« S19-B historique long » de runner.py et DAX 1 a 5 des 60 strategies attendaient ces
donnees ; les minutes 2014 -> 03/2018 etaient en cache depuis le 11/10 sans avoir servi : aucun fichier de trades
DAXCASH dans resultats/, aucune ligne dans recherche/).

Sources (texte complet lu = [T], resume seulement = [R])
 [LSU22] [T] Z. Li (Southampton), A. Sakkas (Nottingham), A. Urquhart (Reading), « Intraday time series momentum: Global
         evidence and links to market characteristics », Journal of Financial Markets 57, 2022 (version acceptee, depot
         CentAUR de Reading) : 16 marches developpes, 10/2005-12/2017, indices minute (TRTH). La derniere demi-heure de
         l Allemagne est 17:00-17:30 (DAX 09:00-17:30, Table 1). La premiere demi-heure, nuit comprise, predit
         POSITIVEMENT la derniere : Allemagne beta 2,97 (t 3,25), hors crise 1,63 (t 1,91) ; strategie ITSM (signe de la
         premiere demi-heure, tenu sur la derniere) : Sharpe 0,73 en dollars, alpha 4,2 % par an. Hors echantillon
         (2010-2017) pour l Allemagne : R2 -0,64 %, MSPE-adj 1,02, non significatif. Prediction CONTRAIRE a V.
 [BDLM21] [T, lu le 12/10 pour gamma_intraday.py] G. Baltussen, Z. Da, S. Lammers, M. Martens, « Hedging demand and market
         intraday momentum », JFE 2021 : plus de 60 futures 1974-2020 ; le rendement du reste de la journee predit la
         derniere demi-heure (momentum), a cause de la couverture des vendeurs d options courts en gamma et des ETF a
         levier. Prediction contraire a V (sauf gamma des teneurs de marche positif : retournement, Barbon-Buraschi 2020,
         Dim-Eraker-Vilkov 2024).
 [BDS25] [T] G. Baltussen, Z. Da, A. Soebhag, « End-of-Day Reversal », version d avril 2025 (www3.nd.edu/~zda/EOD.pdf) :
         actions americaines 1993-2019 ; retournement de fin de seance en COUPE TRANSVERSALE (t > 10), venu presque
         entierement des perdants du jour (achats « buy the dip » des particuliers, moins de nouvelles ventes a
         decouvert avant la nuit) ; la pression de la derniere demi-heure s inverse le lendemain. Au niveau du MARCHE ils
         retrouvent le momentum (autocorrelations croisees positives) : pas de prediction de retournement de l indice,
         mais un mecanisme asymetrique (apres une baisse).
 [BFS24] [T] R. Baule, B. Frijns, S. Schlie, « Feedback Trading: The Intraday Case of Retail Derivatives », Journal of
         Futures Markets 44, 2024 (econstor) : warrants sur le DAX a l EUWAX, 2014. Les particuliers allemands sont
         CONTRARIANTS sur les rendements des 2 dernieres heures (calls achetes apres une baisse) et soldent en fin de
         journee (desequilibre des calls negatif sur 17:15-17:30). Les emetteurs couvrent ces flux sur le DAX. Pas de
         test de prevision de l indice.
 [BM23]  [R] V. Bogousslavsky, D. Muravyev, « Who trades at the close? Implications for price discovery and liquidity »,
         Journal of Financial Markets 2023 : volume croissant a l enchere de cloture, prix de cloture moins informatif,
         distorsions qui se retournent ensuite (texte payant, non lu).
 [ROSA22] [R] C. Rosa, « Understanding intraday momentum strategies », Journal of Futures Markets 2022 : la prevision de la
         derniere demi-heure par la nuit disparait hors echantillon (Etats-Unis) ; elle depend de la force du signal.
 [ZH24]  [R] L. Zhang, L. Hua, « Market Predictability Before the Closing Bell Rings », Risks 2024 : effet nuit et momentum
         intrajournalier affaiblis avec le temps (Etats-Unis 2007-2018, puis 2022-2024).
 [LETF]  fiche 15 (Barbon et al., SSRN 3925725 ; nexus/letf.py, rejetee le 19/10) : le reequilibrage des ETF a levier va
         dans le sens du jour (momentum). Les ETF a levier sur le DAX (LevDAX, ShortDAX) sont petits.
Lecture commune : la litterature publiee predit du MOMENTUM sur la derniere demi-heure du DAX (LSU22, BDLM21), et ce
momentum s affaiblit hors echantillon (LSU22 pour l Allemagne, ROSA22, ZH24). Aucun papier lu ne predit un retournement
de l INDICE entre 17:00 et 17:30 ; des mecanismes de retournement existent (particuliers contrariants BFS24 / BDS25,
pression de cloture BM23, gamma positif) mais ils sont mesures en coupe transversale ou sans test de prevision.
A priori : V repose sur 1,5 an d observation ; l echec est le resultat attendu.

Donnees. MISE A JOUR DU 2026-10-19, AVANT TOUT CALCUL SUR 2014-2025 (accord de l utilisateur) : Dukascopy bloque les
telechargements (503 « No server is available » meme pour l EURUSD ; 1 jour recupere en 30 min sur 2 205), donc la
source est GRXEUR de HistData.com (nexus/histdata.py), CFD sur le DAX en minutes, prix BID, 02/01/2014 -> 31/08/2026.
Controles faits avant le calcul, sur la STRUCTURE des donnees seulement (aucune regle ni aucun signe d anomalie
calcule) : les horodatages sont l heure de New York AVEC heure d ete (et non sans, comme l annonce le site) ; ainsi
convertie, la serie se confond avec celle de Dukascopy sur le chevauchement 01/2014 -> 03/2018 (correlation des
rendements 09:00-17:00 0,999, 17:00-17:30 0,998, 12:00-12:30 0,999) : c est le meme flux. Contre les futures FDAX
(11/03/2025 -> 28/08/2026) : 09:00-17:00 0,989, 17:00-17:30 0,892 (meme signe 90 % des jours). Contre l ES sur la meme
demi-heure (2014-2018) : 0,751, comme Dukascopy (0,755) et FDAX (0,751 en 2025-2026). Jours de Xetra sans prix a 09:00,
17:00 ou 17:30 : 100 sur 3 226, dont 68 en 2023 (fevrier a juillet, trou du fichier HistData) : ils ne sont pas trades.
Ce qui suit vaut pour cette serie (le texte d origine parlait de DEUIDXEUR) :
DEUIDXEUR : CFD Dukascopy sur le DAX cash, prix BID, minutes (sans les minutes sans transaction), index = fin
de barre en UTC, heure de Berlin par conversion. Jours retenus : jours ouvres hors feries de Xetra (paquet holidays,
calendrier XETR). Taille : un contrat FDAX (25 EUR le point, 1,10 $ par euro), tick 0,5 ; couts 1 tick par cote +
2,50 $ par contrat et par cote ; stress 2 ticks. Le CFD n est pas le future : l ecart de base est constant dans la
demi-heure et ne change pas les rendements. Controle de coherence (periode DEJA VUE, pas un critere) : V calculee sur
le CFD et sur FDAX du 11/03/2025 au 28/08/2026 ; part des jours ou les deux prennent le meme sens et correlation des P&L
quotidiens (attendue >= 0,8).
Periode jugee : 02/01/2014 -> 10/03/2025 ; moities P1 avant le 01/07/2019, P2 a partir de cette date.

ETAPE 1 - l anomalie et son mecanisme (periode entiere puis P1 / P2), rendements log, pentes de Newey-West (5 retards).
  Prix a une heure H = ouverture de la barre qui commence a H, sinon cloture d une barre finie dans les 5 minutes avant.
  A1 (S19-B) : r(17:00 -> 17:30) sur r(09:00 -> 17:00) ; V suppose une pente negative ; pentes separees sur les parties
     negative et positive (asymetrie de BDS25 : retournement apres les baisses).
  A2 (LSU22) : r(17:00 -> 17:30) sur la premiere demi-heure nuit comprise r(17:30 la veille -> 09:30) ; LSU22 : positive.
  A3 (BDLM21) : r(17:00 -> 17:30) sur le reste de la journee r(17:30 la veille -> 17:00) ; BDLM21 : positive.
  A4 (pression passagere, BDS25 / BM23) : r(17:30 -> 09:00 le lendemain) sur r(17:00 -> 17:30) ; negative si la fin de
     seance est une pression qui se defait la nuit.
  A5 (specificite de la cloture) : r(12:00 -> 12:30) sur r(09:00 -> 12:00), la fenetre du temoin.
ETAPE 2 - strategies sur la meme periode (rendement d un trade = P&L / (prix d entree x valeur du point d UN contrat) :
la taille reste dans le rendement).
  V  = S19-B jouee a l envers, exactement l objet observe : moteur qf.Engine + suite_s.S19(variante="B") avec ses
       parametres par defaut (reference = ouverture de la premiere barre finissant a partir de 09:00 ; decision a la
       cloture de la barre qui finit a 16:59 ; taille = arrondi(min(max(|r| / 0,50 %, 0,25), 4)) contrats ; stop
       d origine a 2 ATR(14) des barres 1 min ; sortie a la barre de 17:29 ; un tick de glissement par ordre), puis
       chaque trade retourne comme dans inversion.py : P&L inverse = -(P&L brut) - frais (commission + 1 tick a l entree
       et a la sortie). Le stop d origine devient un objectif de gain. Jours de Xetra seulement.
  V2 = V avec 2 ticks par cote.
  T  = temoin : la meme chose sur la fenetre 12:00-12:30 (dax_debut=1200, dax_fin=1230) : un retournement de milieu de
       seance, loin de l enchere de cloture et de l ouverture americaine.
  R0 = anomalie brute : -signe(r 09:00 -> 17:00) x r(17:00 -> 17:30), 1 contrat, sans stop, nette des couts.
  R1 = strategie ITSM de LSU22 (momentum) : signe(r 17:30 la veille -> 09:30) x r(17:00 -> 17:30), nette.
  Contexte (pas un essai) : S19-B d origine sur le CFD (sens du jour), la ligne « historique long » attendue par runner.
  Replique : CAC 40 (FRAIDXEUR, cloture a 17:30 aussi) seulement si son historique Dukascopy est dans le cache ; sinon non
  faite (le 2026-10-19 : absent, non telecharge). L analogue americain (S19-A inversee, ES 15:30-16:00) est deja connu (negatif, resultats_inversees.txt) : ce
  n est pas un nouvel essai.
Criteres (fixes avant le calcul) sur les rendements par trade de V : t >= 3 (avant frais) ; meme signe et t >= 1,5 sur
chaque moitie ; Welch >= 2 contre T ; gain moyen net > 0 ; net > 0 sans les 3 meilleurs trades ; Sharpe deflate >= 0,95
pour 378 essais (375 + V, R0, R1), sur la serie quotidienne nette (zero les jours sans trade).
"""
from __future__ import annotations

import argparse
import math
import os
from datetime import datetime

import numpy as np
import pandas as pd

from .alternatives import dsr
from .or_anomalies import instants
from .qf import INSTRUMENTS, Engine, Inst
from .soixante import FRANCFORT, PY_DIR, exporter, prix_a, r_fenetre, tstat
from .suite_s import S19

DEBUT, FIN_TEST = pd.Timestamp("2014-01-02"), pd.Timestamp("2025-03-10")
DEBUT_FDAX, FIN_FDAX = pd.Timestamp("2025-03-11"), pd.Timestamp("2026-08-28")
MOITIE = pd.Timestamp("2019-07-01")
N_ESSAIS, SEUIL_DSR = 378, 0.95
FDAX = INSTRUMENTS["FDAX"]
FCE = Inst("FCE", "FCE", 10.0 * 1.10, 0.5, 2.5)          # CAC 40 (Euronext), 10 EUR le point
NOM_S19B = "S19-B Rebalancement LETF, DAX 17:00-17:30"


# =============================================================================
#  Donnees
# =============================================================================
def cfd(sym: str = "DEUIDXEUR", source: str = "dukascopy") -> pd.DataFrame | None:
    """Minutes d un CFD d indice en cache (source = dossier de .cache : dukascopy ou histdata)."""
    f = os.path.join(PY_DIR, ".cache", source, f"{sym}_1m.parquet")
    if not os.path.exists(f):
        return None
    df = pd.read_parquet(f)
    df.index = pd.DatetimeIndex(df.index).as_unit("ns")
    return df[~df.index.duplicated(keep="last")].sort_index()


class Marche:
    """Minutes au format de soixante.prix_a (t en ns UTC, fin de barre ; pas d echeance)."""

    def __init__(self, df: pd.DataFrame):
        self.t = pd.DatetimeIndex(df.index).as_unit("ns").asi8
        self.o, self.c = df["open"].to_numpy(float), df["close"].to_numpy(float)
        self.n = len(df)


def jours_xetra(debut, fin) -> pd.DatetimeIndex:
    import holidays
    j = pd.bdate_range(debut, fin)
    h = holidays.financial_holidays("XETR", years=range(j[0].year, j[-1].year + 1))
    return pd.DatetimeIndex([d for d in j if d.date() not in h])


def fenetres(m: Marche, jours: pd.DatetimeIndex) -> pd.DataFrame:
    """Rendements log des fenetres de l etape 1 (heure de Berlin), un par jour ; NaN si un prix manque."""
    def r(a, b, decal=0):
        return r_fenetre(m, jours, a, b, FRANCFORT, decal_a=decal)
    p17, _ = prix_a(m, instants(jours, 17, 0, FRANCFORT))
    return pd.DataFrame(dict(
        jour=r((9, 0), (17, 0)), lh=r((17, 0), (17, 30)), fh=r((17, 30), (9, 30), -1), rod=r((17, 30), (17, 0), -1),
        nuit_suiv=r((17, 30), (9, 0), -1).shift(-1), matin=r((9, 0), (12, 0)), midi=r((12, 0), (12, 30)),
        prix17=p17), index=jours)


def cout_ar(prix: pd.Series, ticks: float = 1.0, inst: Inst = FDAX) -> pd.Series:
    """Aller-retour d un contrat en fraction du notionnel : 2 x (ticks x tick + commission / valeur du point) / prix."""
    return 2 * (ticks * inst.tick + inst.commission / inst.point_value) / prix


# =============================================================================
#  S19-B et son miroir
# =============================================================================
def trades_s19(df: pd.DataFrame, debut: int = 1700, fin: int = 1730, glissement: int = 1, inst: Inst = FDAX) -> pd.DataFrame:
    e = Engine(df, inst, slippage_ticks=glissement)
    st = S19(e, variante="B", dax_debut=debut, dax_fin=fin)
    e.run(st)
    return pd.DataFrame([t.__dict__ for t in e.trades])


def miroir(t: pd.DataFrame, glissement: int = 1, inst: Inst = FDAX) -> pd.DataFrame:
    """Memes trades en sens oppose (inversion.py) : brut = -(P&L brut d origine), net = brut - frais ; rendements par
    rapport au notionnel d UN contrat ; index = jour de l entree, heure de Berlin."""
    q = t["qty"].astype(float)
    frais = q * (2 * inst.commission + 2 * glissement * inst.tick * inst.point_value)
    notion = t["entry_price"].astype(float) * inst.point_value
    jour = (pd.DatetimeIndex(pd.to_datetime(t["entry_time"])).tz_localize("UTC").tz_convert(FRANCFORT)
            .tz_localize(None).normalize())
    out = pd.DataFrame({"origine": t["pnl"].astype(float).to_numpy(), "frais": frais.to_numpy(),
                        "brut": (-t["pnl"] - frais).to_numpy(), "net": (-t["pnl"] - 2 * frais).to_numpy(),
                        "notion": notion.to_numpy(), "qty": q.to_numpy(), "sens": -t["direction"].to_numpy(),
                        "raison": t["reason"].astype(str).to_numpy()}, index=jour)
    out["r_brut"], out["r_net"] = out["brut"] / out["notion"], out["net"] / out["notion"]
    out["r_origine"] = out["origine"] / out["notion"]
    return out


def periode(x: pd.DataFrame | pd.Series, jours: pd.DatetimeIndex, debut, fin):
    sel = x.index.isin(jours) & (x.index >= debut) & (x.index <= fin)
    return x[sel]


# =============================================================================
#  Statistiques
# =============================================================================
def pente(y: pd.Series, x: pd.Series, lags: int = 5) -> dict:
    import statsmodels.api as sm
    d = pd.concat([y.rename("y"), x.rename("x")], axis=1).dropna()
    if len(d) < 30:
        return dict(n=len(d), b=math.nan, t=math.nan)
    m = sm.OLS(d["y"].to_numpy(), sm.add_constant(d["x"].to_numpy())).fit(cov_type="HAC", cov_kwds={"maxlags": lags})
    return dict(n=len(d), b=float(m.params[1]), t=float(m.tvalues[1]))


def pentes_asym(y: pd.Series, x: pd.Series, lags: int = 5) -> dict:
    """y = a + b- min(x, 0) + b+ max(x, 0)."""
    import statsmodels.api as sm
    d = pd.concat([y.rename("y"), x.rename("x")], axis=1).dropna()
    X = sm.add_constant(np.column_stack([np.minimum(d["x"], 0), np.maximum(d["x"], 0)]))
    m = sm.OLS(d["y"].to_numpy(), X).fit(cov_type="HAC", cov_kwds={"maxlags": lags})
    return dict(n=len(d), b_neg=float(m.params[1]), t_neg=float(m.tvalues[1]), b_pos=float(m.params[2]), t_pos=float(m.tvalues[2]))


def welch(a: pd.Series, b: pd.Series) -> float:
    a, b = pd.Series(a).dropna(), pd.Series(b).dropna()
    se = math.sqrt(a.var(ddof=1) / len(a) + b.var(ddof=1) / len(b))
    return float((a.mean() - b.mean()) / se) if se > 0 else math.nan


def quotidien(x: pd.Series, jours: pd.DatetimeIndex) -> pd.Series:
    """Somme des trades par jour, zero les jours de bourse sans trade."""
    return x.groupby(level=0).sum().reindex(jours).fillna(0.0)


def sharpe(q: pd.Series) -> float:
    sd = q.std(ddof=1)
    return float(q.mean() / sd * math.sqrt(252)) if sd > 0 else math.nan


def criteres_v(brut: pd.Series, net: pd.Series, temoin: pd.Series) -> dict:
    x, net = brut.dropna(), net.reindex(brut.dropna().index)
    n = len(x)
    p1, p2 = x[x.index < MOITIE], x[x.index >= MOITIE]
    t, t1, t2 = tstat(x), tstat(p1), tstat(p2)
    w = welch(x, temoin)
    sans3 = net.drop(net.nlargest(3).index).mean() if n > 3 else math.nan
    annees = net.groupby(net.index.year).sum()
    part = float((annees > 0).mean()) if len(annees) else math.nan
    if n < 60:
        tests = {"t >= 2 (evenement rare)": t >= 2, "gain net positif >= 65 % des annees": part >= 0.65,
                 "t de Welch >= 2 contre le temoin": w >= 2, "gain net > 0 sans les 3 meilleurs trades": sans3 > 0}
    else:
        tests = {"t >= 3": t >= 3, "meme signe et t >= 1,5 sur chaque moitie": t1 >= 1.5 and t2 >= 1.5,
                 "t de Welch >= 2 contre le temoin": w >= 2, "gain moyen net > 0": net.mean() > 0,
                 "gain net > 0 sans les 3 meilleurs trades": sans3 > 0}
    return dict(n=n, moyenne=x.mean() * 1e4, t=t, m1=p1.mean() * 1e4, t1=t1, m2=p2.mean() * 1e4, t2=t2,
                temoin=pd.Series(temoin).mean() * 1e4, welch=w, net=net.mean() * 1e4, sans3=sans3 * 1e4,
                part_annees=part, tests=tests, passe=all(tests.values()))


def resume(nom: str, net: pd.Series, jours: pd.DatetimeIndex, pr, dollars: pd.Series | None = None) -> dict:
    """net : rendements nets par trade (fraction du notionnel d un contrat), index = jour."""
    x = net.dropna()
    q = quotidien(x, jours)
    sh = sharpe(q)
    import vectorbt as vbt  # noqa: F401  (accesseur .vbt)
    st = q.vbt.returns(freq="1D", year_freq="252 days")
    d = dict(nom=nom, n=len(x), moyenne=x.mean() * 1e4, t=tstat(x), t1=tstat(x[x.index < MOITIE]),
             t2=tstat(x[x.index >= MOITIE]), sharpe=sh, perte_max=float(-st.max_drawdown()), dsr=dsr(q, N_ESSAIS),
             gagnants=float((x > 0).mean()))
    txt = (f"  {nom:<50} {d['n']:5d} trades | net {d['moyenne']:+6.2f} pb (t {d['t']:+.2f}) | moities t {d['t1']:+.2f} / "
           f"{d['t2']:+.2f} | gagnants {d['gagnants']:.0%} | Sharpe {sh:+.2f} | perte max {d['perte_max']:.1%}")
    if dollars is not None:
        dq = quotidien(dollars.dropna(), jours)
        d["total_usd"], d["sharpe_usd"] = float(dq.sum()), sharpe(dq)
        txt += f" | {d['total_usd']:+,.0f} $ (Sharpe en $ {d['sharpe_usd']:+.2f})".replace(",", " ")
    pr(txt)
    return d


def controle_fdax(m_cfd: pd.DataFrame, jours: pd.DatetimeIndex) -> dict | None:
    """V sur le CFD et sur FDAX (trades du runner) pendant le chevauchement : meme sens ? P&L correles ?"""
    from .inversion import _latest_trades
    f = _latest_trades(NOM_S19B)
    if f is None:
        return None
    m_f = periode(miroir(pd.read_csv(f)), jours, DEBUT_FDAX, FIN_FDAX)
    m_c = periode(m_cfd, jours, DEBUT_FDAX, FIN_FDAX)
    commun = m_f.index.intersection(m_c.index)
    meme = float((m_f.loc[commun, "sens"] == m_c.loc[commun, "sens"]).mean()) if len(commun) else math.nan
    a = quotidien(m_f["net"], jours[(jours >= DEBUT_FDAX) & (jours <= FIN_FDAX)])
    b = quotidien(m_c["net"], a.index)
    return dict(n_fdax=len(m_f), n_cfd=len(m_c), communs=len(commun), meme_sens=meme, correlation=float(a.corr(b)),
                total_fdax=float(m_f["net"].sum()), total_cfd=float(m_c["net"].sum()), sharpe_fdax=sharpe(a), sharpe_cfd=sharpe(b))


# =============================================================================
#  Etude
# =============================================================================
def etude(sortie: str | None = None, log=print) -> dict:
    t0 = datetime.now()
    L = []
    pr = L.append
    pr("=" * 118)
    pr(" RETOURNEMENT DU DAX AVANT LA CLOTURE DE XETRA : S19-B JOUEE A L ENVERS, HORS ECHANTILLON 02/01/2014 -> 10/03/2025")
    pr("=" * 118)
    pr("Protocole et sources : en-tete de nexus/perso/dax_cloture.py (ecrit avant le calcul). CFD DAX HistData GRXEUR,")
    pr("heure de Berlin, taille d un contrat FDAX (1,10 $ / EUR). Rendements en pb du notionnel d un contrat.")
    df = cfd("GRXEUR", "histdata")
    m = Marche(df)
    jours_tout = jours_xetra(DEBUT, min(FIN_FDAX, df.index[-1].normalize()))
    jours = jours_tout[jours_tout <= FIN_TEST]
    pr(f"Donnees : {len(df):,} minutes du {df.index[0]:%d/%m/%Y} au {df.index[-1]:%d/%m/%Y} ; ".replace(",", " ")
       + f"jours de Xetra juges : {len(jours)} ({jours[0]:%d/%m/%Y} -> {jours[-1]:%d/%m/%Y})")
    f = fenetres(m, jours)
    manque = int(f[["jour", "lh"]].isna().any(axis=1).sum())
    pr(f"Jours sans prix a 09:00, 17:00 ou 17:30 : {manque}")

    # ---------------------------------------------------------------- ETAPE 1
    pr("")
    pr("ETAPE 1 - pentes de Newey-West (5 retards) ; entier / P1 (avant 01/07/2019) / P2")
    e1 = {}
    tests = (("A1", "lh", "jour", "r 17:00-17:30 sur r 09:00-17:00 (V : < 0)"),
             ("A2", "lh", "fh", "r 17:00-17:30 sur 1re demi-heure nuit comprise (LSU22 : > 0)"),
             ("A3", "lh", "rod", "r 17:00-17:30 sur reste de la journee (BDLM21 : > 0)"),
             ("A4", "nuit_suiv", "lh", "r 17:30-09:00 suivant sur r 17:00-17:30 (pression : < 0)"),
             ("A5", "midi", "matin", "r 12:00-12:30 sur r 09:00-12:00 (fenetre du temoin)"))
    for code, y, x, titre in tests:
        res = {}
        for per, sel in (("entier", f.index >= DEBUT), ("P1", f.index < MOITIE), ("P2", f.index >= MOITIE)):
            res[per] = pente(f.loc[sel, y], f.loc[sel, x])
        e1[code] = res
        pr(f"  {code} {titre:<62} " + " | ".join(f"{k} {v['b']:+.4f} (t {v['t']:+.2f}, n {v['n']})" for k, v in res.items()))
    a = pentes_asym(f["lh"], f["jour"])
    e1["A1_asym"] = a
    neg, pos = f["jour"] < 0, f["jour"] > 0
    pr(f"  A1 asymetrie : partie negative {a['b_neg']:+.4f} (t {a['t_neg']:+.2f}), partie positive {a['b_pos']:+.4f} "
       f"(t {a['t_pos']:+.2f}) ; r 17:00-17:30 moyen apres un jour en baisse {f.loc[neg, 'lh'].mean() * 1e4:+.2f} pb, "
       f"en hausse {f.loc[pos, 'lh'].mean() * 1e4:+.2f} pb (Welch {welch(f.loc[neg, 'lh'], f.loc[pos, 'lh']):+.2f})")

    # ---------------------------------------------------------------- ETAPE 2
    pr("")
    pr("ETAPE 2 - strategies nettes (1 tick + 2,50 $ par cote et par contrat)")
    m1 = miroir(trades_s19(df))
    mV = periode(m1, jours, DEBUT, FIN_TEST)
    m2 = periode(miroir(trades_s19(df, glissement=2), glissement=2), jours, DEBUT, FIN_TEST)
    mT = periode(miroir(trades_s19(df, 1200, 1230)), jours, DEBUT, FIN_TEST)
    strat = {}
    strat["V"] = resume("V   S19-B a l envers (17:00-17:30)", mV["r_net"], jours, pr, mV["net"])
    strat["V2"] = resume("V   couts 2 ticks", m2["r_net"], jours, pr, m2["net"])
    strat["T"] = resume("temoin : meme regle 12:00-12:30", mT["r_net"], jours, pr, mT["net"])
    c1 = cout_ar(f["prix17"])
    s0 = -np.sign(f["jour"])
    r0 = (s0 * np.expm1(f["lh"]) - c1)[s0 != 0].dropna()
    strat["R0"] = resume("R0  anomalie brute, 1 contrat, sans stop", r0, jours, pr)
    s1 = np.sign(f["fh"])
    s1 = s1.where(s1 != 0, -1.0)                                          # LSU22 : vente si r_F <= 0
    r1 = (s1 * np.expm1(f["lh"]) - c1)[f["fh"].notna()].dropna()
    strat["R1"] = resume("R1  ITSM de LSU22 (momentum)", r1, jours, pr)
    ctx = resume("contexte : S19-B d origine (sens du jour)", mV["r_origine"], jours, pr, mV["origine"])
    pr(f"  V : sorties par l ancien stop (objectif) {(mV['raison'] == 'stop').mean():.0%}, taille moyenne "
       f"{mV['qty'].mean():.2f} contrat(s)")
    an = mV["net"].groupby(mV.index.year).sum()
    pr("  V par annee ($) : " + " ; ".join(f"{y} {v:+,.0f}".replace(",", " ") for y, v in an.items()))

    rep = None
    dcac = cfd("FRAIDXEUR")
    if dcac is not None:
        jc = jours_xetra(DEBUT, FIN_TEST)
        mc = periode(miroir(trades_s19(dcac, inst=FCE), inst=FCE), jc, DEBUT, FIN_TEST)
        rep = resume("replique : CAC 40 (FRAIDXEUR)", mc["r_net"], jc, pr, mc["net"])
        strat["CAC"] = rep
    else:
        pr("  replique CAC 40 : non faite (historique FRAIDXEUR absent du cache)")

    # ---------------------------------------------------------------- controle
    pr("")
    ctl = controle_fdax(m1, jours_tout)
    if ctl is None:
        pr("CONTROLE CFD / FDAX : trades FDAX du runner introuvables")
    else:
        pr(f"CONTROLE CFD / FDAX (11/03/2025 -> 28/08/2026, periode deja vue, pas un critere) : trades FDAX {ctl['n_fdax']}, "
           f"CFD {ctl['n_cfd']}, jours communs {ctl['communs']}, meme sens {ctl['meme_sens']:.0%}, correlation des P&L "
           f"quotidiens {ctl['correlation']:+.2f} ; V FDAX {ctl['total_fdax']:+,.0f} $ (Sharpe {ctl['sharpe_fdax']:+.2f}), "
           f"V CFD {ctl['total_cfd']:+,.0f} $ (Sharpe {ctl['sharpe_cfd']:+.2f})".replace(",", " "))

    # ---------------------------------------------------------------- criteres
    pr("")
    c = criteres_v(mV["r_brut"], mV["r_net"], mT["r_brut"])
    d = strat["V"]["dsr"]
    pr(f"CRITERES (V, {c['n']} trades) : avant frais {c['moyenne']:+.2f} pb (t {c['t']:+.2f}) | P1 {c['m1']:+.2f} "
       f"(t {c['t1']:+.2f}) | P2 {c['m2']:+.2f} (t {c['t2']:+.2f}) | temoin {c['temoin']:+.2f} (Welch {c['welch']:+.2f}) | "
       f"net {c['net']:+.2f} | net sans 3 meilleurs {c['sans3']:+.2f}")
    for k, v in c["tests"].items():
        pr(f"  [{'x' if v else ' '}] {k}")
    pr(f"  [{'x' if d >= SEUIL_DSR else ' '}] Sharpe deflate >= {SEUIL_DSR} pour {N_ESSAIS} essais : {d:.2f}")
    passe = c["passe"] and d >= SEUIL_DSR
    pr(f"VERDICT : {'RETENUE' if passe else 'REJETEE'}")
    texte = "\n".join(L)
    sortie = sortie or os.path.join(PY_DIR, "recherche", "resultats_dax_cloture.txt")
    with open(sortie, "w", encoding="utf-8") as fh:
        fh.write(texte + f"\n(calcule en {(datetime.now() - t0).seconds} s le {datetime.now():%Y-%m-%d %H:%M})\n")
    echecs = [k for k, v in c["tests"].items() if not v] + ([] if d >= SEUIL_DSR else [f"Sharpe deflate >= {SEUIL_DSR}"])
    lignes = [dict(code=k, nom=v["nom"].strip(), n=v["n"], moyenne=v["moyenne"], t=v["t"], t1=v["t1"], t2=v["t2"],
                   temoin=c["temoin"] if k == "V" else None, welch=c["welch"] if k == "V" else None,
                   sharpe_an=v["sharpe"], dsr=v["dsr"]) for k, v in strat.items()]
    exporter("dax_cloture", dict(
        titre="Retournement du DAX avant la cloture de Xetra (S19-B a l envers, hors echantillon 2014-2025)",
        sous=f"CFD DAX HistData GRXEUR (meme flux que Dukascopy), 17:00-17:30 heure de Berlin, taille FDAX ; net en pb du "
             f"notionnel d un contrat par trade ; "
             f"moities avant / apres le 01/07/2019 ; {N_ESSAIS} essais.",
        lignes=lignes, echecs=echecs, retenue=passe, criteres=c, dsr=d, n_essais=N_ESSAIS, etape1=e1, controle=ctl,
        contexte=ctx))
    log(texte)
    return dict(criteres=c, dsr=d, passe=passe, strategies=strat, etape1=e1, controle=ctl, contexte=ctx)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--sortie")
    a = ap.parse_args(argv)
    etude(a.sortie)


if __name__ == "__main__":
    main()
