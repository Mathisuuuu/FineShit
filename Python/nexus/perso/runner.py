"""Lance tous les backtests des strategies NinjaScript portees (suite S, scripts personnels, fiches Nexus sans ML ni
actualites) et ecrit une ligne par strategie dans un fichier texte.

    python -m nexus.perso.runner [--sortie resultats_strategies.txt] [--processus 4] [--seulement S01-A,boombitch] [--sauf "historique long"]
"""
from __future__ import annotations

import argparse
import math
import os
import time
import traceback
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime

import numpy as np
import pandas as pd

from . import qf
from .qf import INSTRUMENTS, Engine, Inst, futures_minutes, alpaca_minutes, resample, summarize, to_daily_et

PY_DIR = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", ".."))


# =============================================================================
#  Definitions des tests
# =============================================================================
def _qf(cls_name, root, inst, minutes=1, **params):
    return dict(kind="qf", cls=cls_name, root=root, inst=inst, minutes=minutes, params=params)


def _user(cls_name, src, inst, minutes=1, rth=False, **params):
    return dict(kind="user", cls=cls_name, src=src, inst=inst, minutes=minutes, rth=rth, params=params)


def _nexus(code, profile=None, **params):
    return dict(kind="nexus", code=code, profile=profile, params=params)


TESTS = [
    # --- Suite S (QF) ---------------------------------------------------------------------------------------------
    ("S01-A Momentum intraday : derniere 1/2 h dans le sens de r_first30", "S01_MomentumIntraday.cs", _qf("S01", "ES", "MES", variante="A"), ""),
    ("S01-B Momentum intraday : bande de bruit + VWAP, trailing", "S01_MomentumIntraday.cs", _qf("S01", "ES", "MES", variante="B"), ""),
    ("S01-D Momentum intraday : derniere 1/2 h, taille vol-scale", "S01_MomentumIntraday.cs", _qf("S01", "ES", "MES", variante="D"), ""),
    ("S02-A Momentum WTI 1re 1/2 h (filtre EIA)", "S02_MomentumCrossAssets.cs", _qf("S02", "CL", "MCL", variante="A"), ""),
    ("S02-B Momentum 6J ouverture de Londres", "S02_MomentumCrossAssets.cs", _qf("S02", "6J", "6J", variante="B"), ""),
    ("S02-C Momentum or session de nuit", "S02_MomentumCrossAssets.cs", _qf("S02", "GC", "MGC", variante="C"), ""),
    ("S05-A Reversal de l opening range 5 min (Dow)", "S05_Prime0DTE.cs", _qf("S05", "YM", "MYM"), ""),
    ("S06-A Fade de l overnight (tel que code)", "S06_OvernightReversal.cs", _qf("S06", "NQ", "MNQ", variante="A"),
     "BUG : declenche sur la barre de 09:30 (pre-ouverture) -> fade le gap de la VEILLE"),
    ("S06-A Fade de l overnight (corrige : gap du jour)", "S06_OvernightReversal.cs", _qf("S06", "NQ", "MNQ", variante="A", corrige=True), ""),
    ("S06-B Reversal de jump overnight (tel que code)", "S06_OvernightReversal.cs", _qf("S06", "NQ", "MNQ", variante="B"),
     "BUG : meme decalage d un jour que S06-A"),
    ("S06-B Reversal de jump overnight (corrige)", "S06_OvernightReversal.cs", _qf("S06", "NQ", "MNQ", variante="B", corrige=True), ""),
    ("S06-C Tilt small-cap : fade de l overnight (corrige, IWM ~ RTY)", "S06_OvernightReversal.cs",
     _qf("S06", "IWM", "IWM", variante="A", corrige=True, seuil_min_overnight_pct=0.15),
     "RTY / M2K absents des donnees Databento : IWM (ETF Russell 2000, minutes Alpaca), 500 parts ~ 1 RTY ; |r_overnight| >= 0,15 %"),
    ("S06-C Tilt small-cap : reversal de jump (corrige, IWM ~ RTY)", "S06_OvernightReversal.cs",
     _qf("S06", "IWM", "IWM", variante="B", corrige=True, seuil_min_overnight_pct=0.15),
     "RTY / M2K absents des donnees Databento : IWM (ETF Russell 2000, minutes Alpaca), 500 parts ~ 1 RTY ; |r_overnight| >= 0,15 %"),
    ("S07-A Post-settle 16:00-17:00 -> gap (regression ridge)", "S07_OvernightGap.cs", _qf("S07", "ES", "MES"), "regression lineaire (statistique, pas de ML) ; filtre de qualite Sharpe x R2 >= 0.10 jamais atteint en 10 ans -> aucun trade"),
    ("S09-A Fade du fix WM/R fin de mois sur 6E", "S09_LondonFix.cs", _qf("S09", "6E", "M6E", variante="A"), ""),
    ("S09-A Fade du fix WM/R fin de mois sur 6B", "S09_LondonFix.cs", _qf("S09", "6B", "M6B", variante="A"), ""),
    ("S09-B Or entre fixings de Londres", "S09_LondonFix.cs", _qf("S09", "GC", "MGC", variante="B"),
     "BUG : sortie au retour a la moyenne puis reouverture immediate de la fenetre -> re-entrees en boucle le soir"),
    ("S09-B Or entre fixings de Londres (corrige : 1 entree par soiree)", "S09_LondonFix.cs",
     _qf("S09", "GC", "MGC", variante="B", corrige=True), ""),
    ("S11-A Price discovery or, long seul (tel que code)", "S11_GoldPriceDiscovery.cs", _qf("S11", "GC", "MGC", variante="A"),
     "BUG : 2 sessions de suite dans le meme sens -> GoFlat puis entree refusee, reste a plat"),
    ("S11-A Price discovery or, long seul (corrige)", "S11_GoldPriceDiscovery.cs", _qf("S11", "GC", "MGC", variante="A", corrige=True),
     "stop 3 x ATR des barres 1 min : la plupart des trades sont stoppes en quelques minutes"),
    ("S11-A Price discovery or, long seul (corrige, sans stop)", "S11_GoldPriceDiscovery.cs",
     _qf("S11", "GC", "MGC", variante="A", corrige=True, stop_atr_mult=0.0), "signal seul, comme dans le papier [44]"),
    ("S11-B Price discovery or, long-short (corrige)", "S11_GoldPriceDiscovery.cs",
     _qf("S11", "GC", "MGC", variante="B", direction="long_et_short", corrige=True), "le fichier impose LongUniquement : B identique a A sans ce reglage"),
    ("S19-A Rebalancement LETF, derniere 1/2 h US", "S19_LetfRebalance.cs", _qf("S19", "ES", "MES", variante="A"), ""),
    ("S19-B Rebalancement LETF, DAX 17:00-17:30", "S19_LetfRebalance.cs", _qf("S19", "FDAX", "FDAX", variante="B"),
     "futures FDAX Databento, seulement depuis 03/2025 ; P&L converti EUR->USD a 1.10"),
    ("S19-B Rebalancement LETF, DAX 17:00-17:30 (historique long)", "S19_LetfRebalance.cs", _qf("S19", "DAXCASH", "FDAX", variante="B"),
     "prix du DAX cash (CFD Dukascopy, 2014-2026) avec la taille d un contrat FDAX ; P&L converti EUR->USD a 1.10"),
    ("S20-A Risk parity ERC multi-futures", "S20_RiskParity.cs", dict(kind="s20", variante="A", permanent=True), "univers ES, GC, CL, 6E en micros (HG et ZN absents des donnees)"),
    ("S20-B Risk parity inverse-vol multi-futures", "S20_RiskParity.cs", dict(kind="s20", variante="B", permanent=True), "univers ES, GC, CL, 6E en micros"),
    ("S20-A ERC, covariance sur 60 j (alternative)", "S20_RiskParity.cs",
     dict(kind="s20", variante="A", params=dict(fenetre=60, min_obs=40), permanent=True),
     "alternative retenue de justesse (resultats_alternatives.txt) : PBO de la famille 47 %, prudence"),
    ("S20 1/N, memes 4 jambes (reference naive)", "S20_RiskParity.cs", dict(kind="s20", variante="EW", permanent=True),
     "reference : meme notionnel par jambe, reequilibrage mensuel ; l ERC ne fait pas mieux"),
    # --- Scripts personnels -------------------------------------------------------------------------------------------
    ("IntradayMomentumMES (bande VWAP, trailing ATR)", "MyCustomStrategy1.cs", _user("IntradayMomentumMES", "ES", "MES"), ""),
    ("Test OPR cassure 1re barre (tel que code)", "MyCustomStrategy2.cs", _user("OprTest", "ES", "ES", minutes=5, rth=True),
     "BUG : achat aussi sur cassure basse ; stop/objectif jamais armes (noms de signaux) -> sortie en fin de seance seulement"),
    ("Test OPR cassure 1re barre (corrige : short, stop, objectif 2R)", "MyCustomStrategy2.cs",
     _user("OprTest", "ES", "ES", minutes=5, rth=True, corrige=True), ""),
    ("ZarattiniSPYMomentum (Beat the Market)", "MyCustomStrategy3.cs", _user("ZarattiniSPY", "SPY", "SPY", rth=True),
     "code : 1 action, teste avec 100 000 $ de notionnel ; entree testee CHAQUE minute (le papier : toutes les 30 min) -> sur-trading"),
    ("ICT2022Model (sweep/FVG HTF, killzone, MSS + FVG 1 min)", "MyCustomStrategy4.cs", _user("ICT2022", "NQ", "NQ"), ""),
    ("ZarattiniEnvelope (enveloppe de bruit, vol-cible)", "ZarattiniEnvelope.cs", _user("ZarattiniEnvelope", "ES", "ES", rth=True), ""),
    ("IntradayMomentumGamma (Noise Area + VWAP, sans gamma)", "IntradayMomentumC01.cs", _user("IntradayMomentumGamma", "ES", "ES", rth=True),
     "filtre gamma desactive par defaut dans le code (pas de chaine d options)"),
    ("boombitch (Turtle Donchian 160/60, M15)", "boombitch.cs", _user("Boombitch", "NQ", "MNQ", minutes=15),
     "taille 'risque 10 $' < 1 contrat -> 1 MNQ force (AllowMinOneContract) ; long seul sur un Nasdaq en forte hausse : "
     "comparer a l achat-conservation de 1 MNQ (+42 600 $ sur la periode, avec un drawdown bien plus profond)"),
    ("boombitch, taille inverse a la volatilite (alternative)", "boombitch.cs",
     _user("DonchianAlt", "NQ", "MNQ", minutes=15, fixed_risk=300.0),
     "alternative retenue : risque constant de 300 $ par trade (1,5 ATR) au lieu de 1 MNQ fixe ; une partie du gain vient "
     "de ce qu un contrat fixe prenait ~4 fois moins de risque en 2016 qu en 2026"),
    ("boombitch, filtre de tendance 200 j (alternative)", "boombitch.cs",
     _user("DonchianAlt", "NQ", "MNQ", minutes=15, sma_jours=200),
     "alternative retenue par la regle mais gain en validation dans le bruit (+0,04 de Sharpe)"),
    ("AUDusd (paires z-score, 15 min)", "AUDusd.cs", dict(kind="pairs", leader="6E", follower="6B", minutes=15),
     "NZD/USD et AUD/USD absents (pas de forex chez Alpaca) : teste sur 6B suiveur / 6E meneur, 10 000 unites"),
    # --- Fiches Nexus (sans ML ni actualites) --------------------------------------------------------------------------
    ("Fiche 1 TSMOM 12-1 (25 actions/ETF US)", "Nexus01_TSMOM.cs", _nexus("01"), "univers = grandes capitalisations d aujourd hui (biais du survivant : resultat surestime)"),
    ("Fiche 2 XSMOM quartile superieur (25 actions/ETF US)", "Nexus02_XSMOM.cs", _nexus("02"), "univers = grandes capitalisations d aujourd hui (biais du survivant : resultat surestime)"),
    ("Fiche 3 Rotation multi-facteurs", "Nexus03_MultiFactorRotation.cs", _nexus("03"),
     "sans fondamentaux (fundamentals.csv vide) : momentum + securite seulement ; univers = grandes capitalisations d aujourd hui (biais du survivant : resultat surestime)"),
    ("Fiche 4A Residu OU sectoriel", "Nexus04A_ResidualMeanReversion.cs", _nexus("04A"), "univers = grandes capitalisations d aujourd hui (biais du survivant : resultat surestime)"),
    ("Fiche 4B Retournement crypto 15 min (mode strategie)", "Nexus04B_CryptoIntradayReversal.cs",
     _nexus("04B", mode="strategie", taker_source="desactive"),
     "flux taker indisponible chez Alpaca -> condition de flux desactivee ; crypto Alpaca peu liquide (cotations aberrantes filtrees) ; "
     "17 cryptos sur 20 ; depuis 2021"),
    ("Fiche 5 Retour a la moyenne de volatilite", "Nexus05_VolatilityMeanReversion.cs", dict(_nexus("05"), permanent=True),
     "position permanente redimensionnee (SPY, QQQ, BTC, ETH) : le nombre de trades n a pas de sens, verdict sur le Sharpe"),
    ("Fiche 6 Paires co-integrees (long seul)", "Nexus06_PairsCointegration.cs", _nexus("06"), "univers = grandes capitalisations d aujourd hui (biais du survivant : resultat surestime)"),
    ("Fiche 11 Roue d options synthetique", "Nexus11_OptionsWheel.cs", _nexus("11"),
     "ATTENTION : options SYNTHETIQUES (Black-Scholes, vol implicite supposee = vol realisee x 1.28) : la prime de variance est "
     "une hypothese, pas une mesure ; a valider avec de vraies cotations d options"),
    ("Fiche 12 Regime de vol (terciles)", "Nexus12_VolRegimeConditional.cs", _nexus("12"), "univers = grandes capitalisations d aujourd hui (biais du survivant : resultat surestime)"),
    ("Fiche 13 Trend 8 actifs (futures)", "Nexus13_PropTrend8.cs", _nexus("13", profile="futures"), "8 marches en futures Databento"),
    ("Fiche 1 TSMOM (futures)", "Nexus01_TSMOM.cs", _nexus("01", profile="futures"), "10 futures Databento, micros, capital 1 M$"),
    ("Fiche 2 XSMOM (futures)", "Nexus02_XSMOM.cs", _nexus("02", profile="futures"), "10 futures Databento, micros, capital 1 M$"),
    ("Fiche 5 Retour a la moyenne de vol (futures)", "Nexus05_VolatilityMeanReversion.cs", dict(_nexus("05", profile="futures"), permanent=True),
     "ES + NQ micros, capital 1 M$ ; position permanente redimensionnee"),
    ("Fiche 6 Paires co-integrees (futures)", "Nexus06_PairsCointegration.cs", _nexus("06", profile="futures"), "paires de futures, capital 1 M$"),
    ("Fiche 12 Regime de vol (futures)", "Nexus12_VolRegimeConditional.cs", _nexus("12", profile="futures"), "10 futures, capital 1 M$"),
    ("Fiche 14 Swing strict (futures)", "Nexus14_StrictSwing.cs", _nexus("14", profile="futures"), "10 futures, capital 1 M$"),
    ("Fiche 14 Swing strict", "Nexus14_StrictSwing.cs", _nexus("14"), "sans calendrier de resultats (earnings.csv vide) : condition 6 ignoree ; univers = grandes capitalisations d aujourd hui (biais du survivant : resultat surestime)"),
    # --- Trois strategies FX combinees (nexus/perso/fx_trois.py) --------------------------------------------------------
    ("FX fix flow fin de mois (Krohn + Melvin & Prins)", "fiche FX (3 strategies)", dict(kind="fx", strategie="fix"),
     "6E 6B 6J 6A en micros ; aucun parametre optimise ; detail et diagnostics : resultats_fx.txt"),
    ("FX post-annonce NFP / CPI + flux (walk-forward)", "fiche FX (3 strategies)", dict(kind="fx", strategie="annonce"),
     "hors echantillon 2019-2026 ; surprise implicite (consensus indisponible), flux approche ; detail : resultats_fx.txt"),
    ("FX cascade de stops sur chiffres ronds (walk-forward)", "fiche FX (3 strategies)", dict(kind="fx", strategie="ronds"),
     "hors echantillon 2019-2026 ; niveaux 00 / 50 du future non ajuste, filtre horaire de Ranaldo ; detail : resultats_fx.txt"),
    ("FX trois strategies combinees", "fiche FX (3 strategies)", dict(kind="fx", strategie="combine"),
     "fix 2019-2026 + post-annonce et chiffres ronds hors echantillon ; detail : resultats_fx.txt"),
    # --- Or : 10 strategies intraday (nexus/perso/or_anomalies.py) ----------------------------------------------------
    ("Or 1 Ouverture US surevaluee", "fiche or (10 strategies)", dict(kind="or", strategie="1 Ouverture US surevaluee"),
     "vente 08:20 -> 10:20 ET apres une nuit > +0,5 sigma (Blose et al.) ; detail : resultats_or.txt"),
    ("Or 2 Momentum premiere demi-heure", "fiche or (10 strategies)", dict(kind="or", strategie="2 Momentum premiere demi-heure"),
     "cloture -> 10:00 ET predit 15:30 -> 16:00 ET (Xu et al., Gao et al.) ; detail : resultats_or.txt"),
    ("Or 3 Retour apres exces non informe", "fiche or (10 strategies)", dict(kind="or", strategie="3 Retour apres exces non informe"),
     "mouvement > 2 sigma en 15 min sur faible volume, retour au VWAP (Ma et al.) ; detail : resultats_or.txt"),
    ("Or 4 Fed accommodante (sortie 14:28)", "fiche or (10 strategies)", dict(kind="or", strategie="4 Fed accommodante (sortie 14:28)"),
     "surprise approchee par le dollar (rendement a 2 ans absent) ; Awartani et al. ; detail : resultats_or.txt"),
    ("Or 6 Avant le fixing du matin", "fiche or (10 strategies)", dict(kind="or", strategie="6 Avant le fixing du matin"),
     "vente 09:30 -> 10:30 Londres (Nilsson) ; detail : resultats_or.txt"),
    ("Or 7 Apres le fixing de l apres-midi", "fiche or (10 strategies)", dict(kind="or", strategie="7 Apres le fixing de l apres-midi"),
     "achat 15:05 -> 16:35 Londres (Nilsson ; contre : Caminschi & Heaney) ; detail : resultats_or.txt"),
    ("Or 8 Barrieres des chiffres ronds (100 $)", "fiche or (10 strategies)", dict(kind="or", strategie="8 Barrieres des chiffres ronds (100 $)"),
     "rebond et cascade sur les multiples de 100 $ (Aggarwal & Lucey) ; detail : resultats_or.txt"),
    ("Or 9 Fuite vers l or", "fiche or (10 strategies)", dict(kind="or", strategie="9 Fuite vers l or"),
     "achat d or 60 min apres une chute de l ES < -4 sigma en 5 min (Baur & Kuck) ; detail : resultats_or.txt"),
    ("Or 10 Momentum des jours agites", "fiche or (10 strategies)", dict(kind="or", strategie="10 Momentum des jours agites"),
     "strategie 2 les jours agites ou avec saut (Xu et al., Sobti) ; meme fenetre que la 2 ; detail : resultats_or.txt"),
    # --- Gotobi Pre-Fix Drift (nexus/perso/gotobi.py) -------------------------------------------------------------------
    ("Gotobi pre-fix USD/JPY (Ito & Yamada)", "fiche gotobi", dict(kind="gotobi", jambe="avant", nom="Gotobi pre-fix"),
     "achat de USD/JPY 09:00 -> 09:55 Tokyo les jours gotobi, micro MJY, regles de la fiche ; anomalie et groupe temoin : "
     "resultats_gotobi.txt"),
    ("Gotobi seconde jambe : vente apres le fixing (hypothese)", "fiche gotobi", dict(kind="gotobi", jambe="apres", nom="Gotobi apres"),
     "vente de USD/JPY 09:55 -> 11:00 Tokyo les jours gotobi (reflux de Krohn et al.), mesuree a part"),
    # --- Fil ES/NQ « 6 mois de simulation » (order flow, nexus/perso/orderflow.py) -------------------------------------
    ("Fil ES/NQ fiche 1 : choc prix + volume", "fil ES/NQ (fiches md)", dict(kind="orderflow", fiche="F1"),
     "parametres de la fiche (4 sigma, volume 2x, retour 25 %, 5 min) ; detail et validation : resultats_orderflow.txt"),
    ("Fil ES/NQ fiche 3 : retour au POC", "fil ES/NQ (fiches md)", dict(kind="orderflow", fiche="F3"),
     "profil de volume reconstruit sur les minutes, delta approche (BVC) ; detail : resultats_orderflow.txt"),
]

NON_TESTEES = [
    ("Exclues (ML ou actualites, a ta demande)", "S01-C (HMM), S05-C (score FOMC multimodal), S07-B (regression logistique ; le "
     "Nikkei NKD manque aussi), S17 (trading des annonces FOMC / macro ; il faudrait aussi les futures fed funds ZQ, VIX VX ou BTC "
     "MBT), Nexus07-10 (LLM, actualites, FinBERT), NexusA_RegimeMonitor (HMM), veto Claude de la fiche 13"),
    ("Sans ordre par construction (modules)", "S04, S08 (prevision de volatilite), S10-B (detecteur de fenetre), S12, S15, S16, S18, "
     "SolVolSpreadSignalEngine (signal IV vs GARCH, pas d execution), NexusC_PortfolioMonitor"),
    ("Donnees indisponibles", "S03 et S05-B / S07-C (chaine d options SPX / gamma), S10-A (futures VIX VX), S13 (perpetuel BTC + future "
     "CME), S14 (funding des perpetuels), fil ES/NQ fiche 2 et desequilibre du carnet de la fiche 4 (carnet d ordres ES / NQ : "
     "Databento mbp-1 ou tbbo)"),
    ("En attente de donnees", "S19-B historique long (minutes DAX Dukascopy depuis 2014 : telechargement partiel, a relancer) ; "
     "or n° 4 avec le vrai rendement a 2 ans (future ZT, Databento payant : python -m nexus.databento_dl, substitut dollar en "
     "attendant) ; or n° 9 avant 2016 (GC et ES Databento depuis 2010, payant)"),
    ("Donnees payantes ou non publiques", "or n° 5 (consensus et dispersion des previsions : Bloomberg, Econoday...) ; filtres "
     "de l or : annonces europeennes (n° 6) et nombre de tours de l enchere LBMA (n° 7)"),
    ("Autres", "MyCustomStrategy.cs (fichier vide), @Sample*.cs (exemples fournis par NinjaTrader)"),
]


# =============================================================================
#  Execution d un test
# =============================================================================
def _minutes(src: str) -> pd.DataFrame:
    if src == "DAXCASH":                      # DAX cash (CFD Dukascopy), historique minute depuis 2014
        return pd.read_parquet(os.path.join(PY_DIR, ".cache", "dukascopy", "DEUIDXEUR_1m.parquet"))
    return alpaca_minutes(src) if src in ("SPY", "IWM") else futures_minutes(src)


def _verdict(trades, net, sharpe, permanent=False):
    if trades < 30 and not permanent:
        return "INSUFFISANT (< 30 trades)"
    if net <= 0:
        return "NEGATIVE"
    if math.isfinite(sharpe) and sharpe >= 0.5:
        return "PROMETTEUSE"
    return "POSITIVE MAIS FAIBLE"


def run_test(spec: dict, out_dir: str) -> dict:
    t0 = time.time()
    kind = spec["kind"]
    if kind in ("qf", "user"):
        from . import ict, suite_s, user
        src = spec["root"] if kind == "qf" else spec["src"]
        df = _minutes(src)
        if spec["minutes"] > 1:
            df = resample(df, spec["minutes"])
        if spec.get("rth"):
            df = user.rth_only(df)
        e = Engine(df, INSTRUMENTS[spec["inst"]])
        mod = suite_s if kind == "qf" else (ict if spec["cls"] == "ICT2022" else user)
        st = getattr(mod, spec["cls"])(e, **spec["params"])
        e.run(st)
        s = summarize(e)
        trades_df = pd.DataFrame([t.__dict__ for t in e.trades])
        trades_df["instrument"] = "FDAX" if src == "DAXCASH" else src
        s["equity"] = e.equity()
        data_txt = f"{src} {spec['minutes']} min{' RTH' if spec.get('rth') else ''} -> {spec['inst']}"
    elif kind == "pairs":
        from . import user
        fol = resample(futures_minutes(spec["follower"]), spec["minutes"])
        lea = resample(futures_minutes(spec["leader"]), spec["minutes"])
        inst = Inst("6B x10k", "6B", 10000.0, 0.0001, 0.6)
        e = Engine(fol, inst)
        st = user.AUDusd(e)
        st.leader = lea["close"].reindex(fol.index, method="ffill").to_numpy()
        e.run(st)
        s = summarize(e)
        trades_df = pd.DataFrame([t.__dict__ for t in e.trades])
        trades_df["instrument"] = spec["follower"]
        s["equity"] = e.equity()
        data_txt = f"{spec['follower']} suiveur / {spec['leader']} meneur, {spec['minutes']} min"
    elif kind == "s20":
        from .suite_s import run_s20
        legs = {"MES": "ES", "MGC": "GC", "MCL": "CL", "M6E": "6E"}
        daily = {k: to_daily_et(futures_minutes(r)) for k, r in legs.items()}
        eq, nfills, nreb, pnls = run_s20(daily, {k: INSTRUMENTS[k] for k in legs}, spec["variante"], **spec.get("params", {}))
        d = eq.diff().dropna()
        pnls = np.asarray(pnls)
        wins, losses = pnls[pnls > 0].sum(), -pnls[pnls < 0].sum()
        s = dict(trades=nfills, win_rate=float((pnls > 0).mean()) if pnls.size else math.nan, net=float(eq.iloc[-1] - eq.iloc[0]),
                 profit_factor=float(wins / losses) if losses > 0 else math.nan, avg_trade=float(pnls.mean()) if pnls.size else math.nan,
                 sharpe=float(d.mean() / d.std() * math.sqrt(252)) if d.std() > 0 else math.nan,
                 max_dd=float((eq.cummax() - eq).max()), start=eq.index[0], end=eq.index[-1], capital=100000.0, t_stat=math.nan)
        trades_df = pd.DataFrame({"pnl": pnls})
        s["equity"] = eq
        data_txt = f"journalier ES/GC/CL/6E (micros), {nreb} reequilibrages ({nfills} ordres de jambe)"
    elif kind == "or":
        from .or_anomalies import run_spec as or_spec
        s, trades_df = or_spec(spec)
        data_txt = s.pop("data")
    elif kind == "gotobi":
        from .gotobi import run_spec as gotobi_spec
        s, trades_df = gotobi_spec(spec)
        data_txt = s.pop("data")
    elif kind == "fx":
        from .fx_trois import run_spec as fx_spec
        s, trades_df = fx_spec(spec)
        data_txt = s.pop("data")
    elif kind == "orderflow":
        from .orderflow import run_spec
        s, trades_df = run_spec(spec)
        trades_df = trades_df.assign(instrument=trades_df["instrument"].map({"MES": "ES", "MNQ": "NQ"})) if len(trades_df) else trades_df
        data_txt = s.pop("data")
    else:
        return run_nexus(spec, out_dir, t0)
    s["data"] = data_txt
    s["secs"] = time.time() - t0
    s["permanent"] = spec.get("permanent", False)
    return s, trades_df


def run_nexus(spec, out_dir, t0):
    from .. import data as D
    from .. import validation as V
    from ..profiles import profile_params
    from ..strategies import get
    klass = get(spec["code"])
    params = dict(profile_params(spec["profile"], spec["code"]) or {}) if spec["profile"] else {}
    params.update(spec["params"])
    st = klass(**params)
    if st.bar_minutes() > 0:
        data = D.load_folder(os.path.join(qf.QUOTES, "alpaca", "crypto_15min"), daily=False, intraday_minutes=st.bar_minutes())
    else:
        data = D.load_folder(qf.QUOTES)
    res = st.run(data, report=True)
    eq = res.equity
    pnls = np.array([t.net_pnl for t in res.trades])
    wins, losses = pnls[pnls > 0].sum() if pnls.size else 0.0, -pnls[pnls < 0].sum() if pnls.size else 0.0
    s = dict(trades=len(pnls), win_rate=float((pnls > 0).mean()) if pnls.size else math.nan, net=float(pnls.sum()) if pnls.size else 0.0,
             profit_factor=float(wins / losses) if losses > 0 else math.nan, avg_trade=float(pnls.mean()) if pnls.size else math.nan,
             sharpe=V.annualized_sharpe(res.returns.values), max_dd=V.max_drawdown(eq.values) * st.p.initial_bankroll,
             max_dd_pct=V.max_drawdown(eq.values), ret_pct=float(eq.iloc[-1] / eq.iloc[0] - 1) if len(eq) else math.nan,
             start=eq.index[0], end=eq.index[-1], capital=st.p.initial_bankroll,
             t_stat=float(pnls.mean() / (pnls.std(ddof=1) / math.sqrt(pnls.size))) if pnls.size > 2 and pnls.std(ddof=1) > 0 else math.nan)
    s["data"] = ("futures Databento (profil futures)" if spec["profile"] else
                 ("crypto Alpaca 15 min" if st.bar_minutes() > 0 else "actions/ETF Alpaca journalier"))
    s["secs"] = time.time() - t0
    s["permanent"] = spec.get("permanent", False)
    s["equity"] = eq
    with open(os.path.join(out_dir, f"rapport_{klass.NAME}.txt"), "w", encoding="utf-8") as f:
        f.write(res.report)
    return s, res.trades_frame()


def _job(args):
    idx, name, src, spec, note, out_dir = args
    try:
        s, trades = run_test(spec, out_dir)
        safe = "".join(ch if ch.isalnum() else "_" for ch in name)[:60]
        trades.to_csv(os.path.join(out_dir, f"trades_{idx:02d}_{safe}.csv"), index=False)
        eq = s.pop("equity", None)
        if eq is not None:
            eq.rename("equity").to_csv(os.path.join(out_dir, f"equity_{idx:02d}_{safe}.csv"), index_label="date")
        return idx, name, src, note, s, None
    except Exception as ex:
        return idx, name, src, note, None, f"{type(ex).__name__}: {ex}\n{traceback.format_exc()}"


def fmt_line(name, src, note, s, err) -> str:
    if err:
        return f"{name} | {src} | ERREUR : {err.splitlines()[0]}"
    sh = s["sharpe"]
    parts = [name, src, s["data"],
             f"{pd.Timestamp(s['start']):%Y-%m} -> {pd.Timestamp(s['end']):%Y-%m}",
             f"{s['trades']} trades",
             f"reussite {s['win_rate']:.0%}" if math.isfinite(s["win_rate"]) else "reussite n/d",
             f"PnL net {s['net']:+,.0f} $".replace(",", " "),
             f"PF {s['profit_factor']:.2f}" if math.isfinite(s["profit_factor"]) else "PF n/d",
             f"Sharpe {sh:.2f}" if math.isfinite(sh) else "Sharpe n/d",
             f"DD max {s['max_dd']:,.0f} $".replace(",", " ")]
    if "ret_pct" in s:
        parts.append(f"rendement {s['ret_pct']:+.1%} / DD {s['max_dd_pct']:.1%}")
    if math.isfinite(s.get("t_stat", math.nan)):
        parts.append(f"t {s['t_stat']:+.1f}")
    parts.append("VERDICT " + _verdict(s["trades"], s["net"], sh, s.get("permanent", False)))
    if note:
        parts.append(note)
    return " | ".join(parts)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--sortie", default=os.path.join(PY_DIR, "recherche", "resultats_strategies.txt"))
    ap.add_argument("--processus", type=int, default=max(1, min(4, (os.cpu_count() or 2) - 1)))
    ap.add_argument("--seulement", default="")
    ap.add_argument("--sauf", default="", help="strategies a ne pas relancer (meme syntaxe que --seulement)")
    a = ap.parse_args(argv)
    out_dir = os.path.join(PY_DIR, "resultats", f"perso_{datetime.now():%Y%m%d_%H%M%S}")
    os.makedirs(out_dir, exist_ok=True)
    only = [x.strip().lower() for x in a.seulement.split(",") if x.strip()]
    sauf = [x.strip().lower() for x in a.sauf.split(",") if x.strip()]
    jobs = [(i, n, src, spec, note, out_dir) for i, (n, src, spec, note) in enumerate(TESTS)
            if (not only or any(o in n.lower() or o in src.lower() for o in only))
            and not any(o in n.lower() for o in sauf)]
    print(f"[perso] {len(jobs)} backtests, {a.processus} processus -> {out_dir}", flush=True)
    results = {}
    with ProcessPoolExecutor(max_workers=a.processus) as ex:
        futs = [ex.submit(_job, j) for j in jobs]
        for f in as_completed(futs):
            idx, name, src, note, s, err = f.result()
            results[idx] = fmt_line(name, src, note, s, err)
            print(f"[perso] {results[idx]}" + (f"  ({s['secs']:.0f} s)" if s else ""), flush=True)
            if err:
                print(err, flush=True)
    lines = [f"# Backtests des strategies NinjaScript portees en Python - {datetime.now():%Y-%m-%d %H:%M}",
             "# Execution a l ouverture de la barre suivante, commission par contrat (0.60 $ micro / 2.50 $ standard par cote),",
             "# 1 tick de glissement par ordre marche/stop, capital de reference 100 000 $. Futures : Databento (ajustement additif",
             "# aux roulements, proportionnel pour le CL) ; actions, ETF, SPY minute et crypto : Alpaca. Une ligne par strategie.",
             "# VERDICT : PROMETTEUSE = PnL net > 0 et Sharpe >= 0.5 sur au moins 30 trades ; POSITIVE MAIS FAIBLE = PnL net > 0 sans",
             "# atteindre ce seuil ; NEGATIVE = PnL net <= 0. Ce tri ne remplace pas la validation walk-forward / PBO / DSR du module C.",
             "# nom | fichier | donnees | periode | trades | reussite | PnL net | profit factor | Sharpe | drawdown max | ... | verdict | remarque",
             ""]
    body = [results[i] for i in sorted(results)]
    if (only or sauf) and os.path.exists(a.sortie):
        # re-run partiel : on remplace seulement les lignes des strategies relancees, dans l ordre de TESTS
        new_by_name = {l.split(" | ")[0]: l for l in body}
        old_by_name = {}
        with open(a.sortie, encoding="utf-8") as f:
            for l in f:
                l = l.rstrip()
                if l and not l.startswith("#") and not l.startswith("NON TESTEES") and " | " in l:
                    old_by_name[l.split(" | ")[0]] = l
        body = [new_by_name.get(n) or old_by_name.get(n) for n, _, _, _ in TESTS if new_by_name.get(n) or old_by_name.get(n)]
    lines += body
    lines.append("")
    lines += [f"NON TESTEES - {k} : {v}" for k, v in NON_TESTEES]
    with open(a.sortie, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    print(f"[perso] resultats ecrits dans {a.sortie} (trades et rapports dans {out_dir})")


if __name__ == "__main__":
    main()
