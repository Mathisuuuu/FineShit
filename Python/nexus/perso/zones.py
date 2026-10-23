"""Recherche par zone horaire (page « Laboratoire » du tableau de bord) : hypotheses courtes tirees de papiers, une par
section, protocole ecrit ICI avant chaque calcul, test UNIQUEMENT dans vectorbt (nexus.labo : portefeuille vectorbt des
trades, statistiques vectorbt, trades vectorbt pour les criteres de la methode).

    python -m nexus.perso.zones --hypotheses Z1          -> recherche/resultats_zones.txt, labo.json (en direct)

Methode (memoire methode-strategie-papiers) : t >= 3 ; meme signe et t >= 1,5 sur 2016-2020 et 2021-2026 ; Welch >= 2
contre le temoin ; net > 0 ; net > 0 sans les 3 meilleurs trades ; Sharpe deflate >= 0,95 avec le nombre CUMULE d essais
(ESSAIS_PROGRAMME de nexus/tableau.py, tenu egal a N_ESSAIS de nexus/perso/creneaux.py). Le calendrier du mois de la
page Laboratoire ne prend que les strategies fiables (IC du Sharpe > 0, deux moities > 0), toujours vivantes (Sharpe > 0
sur les 24 derniers mois) et courtes (<= 400 h par an), deux a deux non correlees.

-------------------------------------------------------------------------------------------------------------------------
Z1 - PETROLE : MOMENTUM INTRADAY (zone « cloture US ») (protocole ecrit le 2026-10-20 vers 11:20, avant calcul)
-------------------------------------------------------------------------------------------------------------------------
Sources : [WCMX19] [R] Wen, Cho, Ma & Xu 2019, « Intraday Momentum : Evidence from the Crude Oil Market » (SSRN 3416022) ;
[WGMX20] [R] Wen, Gong, Ma & Xu 2020, « Intraday Momentum and Return Predictability : Evidence from the Crude Oil
Market » (SSRN 3553682) : USO 2006-2018, le rendement de la premiere demi-heure, mesure depuis la cloture de la veille,
prevoit positivement celui de la derniere demi-heure, dans et hors echantillon ; la part de nuit porte le plus
d information.
Traduction sur le future CL (heures de l ETF USO, New York) : jour de bourse J, veille ouvree J-1.
  V  = signal : signe de r(CL, 16:00 J-1 -> 10:00 J) ; position dans ce sens de 15:30 a 16:00 J ;
  R1 = signal : partie de nuit seulement, r(16:00 J-1 -> 9:30 J) ; meme position ;
  temoin : achat de CL de 15:30 a 16:00 chaque jour (la fenetre sans le signal).
  Couts : aller-retour de l etude des 60 strategies (cout_bp, CL, 1 tick + 2,50 $ par cote), stress x 2.
  Essais : V, R1 -> 418.
RESULTAT (2026-10-20 vers 11:22) : les deux REJETEES. V : net -4,14 pb par trade (t -7,6), Sharpe -2,28, 24 derniers mois
-3,10 ; R1 : -3,94 pb. Brut proche de 0 et pas mieux que l achat systematique de la meme demi-heure (Welch -0,7) : le
momentum intraday du petrole (USO 2006-2018) a disparu sur CL 2016-2026.

-------------------------------------------------------------------------------------------------------------------------
Z2 - VEILLES DE JOURS FERIES AMERICAINS (zones « seance » et « cloture US ») (protocole ecrit le 2026-10-20 vers 11:24)
-------------------------------------------------------------------------------------------------------------------------
Sources : [ARI90] [R] Ariel 1990, « High Stock Returns before Holidays : Existence and Evidence on Possible Causes »,
Journal of Finance 45(5) : la veille des jours feries, les actions americaines montent environ 9 a 14 fois plus qu un jour
ordinaire, surtout en fin de seance ; [KP94] [R] Kim & Park 1994 (JFQA) : meme effet au Royaume-Uni et au Japon, pas un
artefact de calendrier ; [MP04] [R] Meneu & Pardo 2004 : l effet tient a une moindre propension des petits porteurs a
vendre avant les fetes.
Regle (jours feries de la bourse de New York, nexus/perso/suite_s.us_holiday) : la veille ouvree d un jour ferie (le
dernier jour de bourse avant un jour de semaine ferme), achat a 12:00 New York, vente a 16:00 (13:00 les demi-seances du
3 juillet et du 24 decembre).
  V  = ES ;  R1 = NQ ;
  temoin : le meme achat (12:00 -> 16:00) tous les autres jours de bourse.
  Couts : aller-retour de l etude des 60 strategies (cout_bp), stress x 2. Essais : V, R1 -> 420.
RESULTAT (2026-10-20 vers 11:25) : les deux REJETEES. 100 veilles (9,4 par an) : ES +3,48 pb net (t 0,96), Sharpe 0,29
[-0,26 ; 0,91], 24 derniers mois -0,44 ; NQ +3,26 pb (t 0,82). L effet est encore positif mais trop faible et il s eteint.

-------------------------------------------------------------------------------------------------------------------------
N1-N2, E1-E3 - REGLES QUI MARCHENT, REPLIQUEES SUR DE NOUVEAUX MARCHES (protocole ecrit le 2026-10-20 vers 11:27, avant
que les donnees soient arrivees)
-------------------------------------------------------------------------------------------------------------------------
Pourquoi : remplir les zones vides du mois avec des marches independants des notres (accord de l utilisateur du
2026-10-20 pour HistData : JPXJPY, ETXEUR, UKXGBP, XAGUSD, EURJPY, AUDJPY ; CFD au prix acheteur, minutes, 2015-2026).
L horodatage de chaque serie est controle AVANT tout calcul (correlation des rendements 15 min par decalage contre un
marche connu : EURJPY et AUDJPY contre 6E / 6J, XAGUSD contre GC, ETXEUR et UKXGBP contre GRXEUR deja controle, JPXJPY
contre NQ la nuit) ; un decalage arrete tout.
Sources : [LSU22] [R] Li, Sakkas & Urquhart 2022, « Intraday time series momentum : Global evidence and links to market
characteristics », Journal of Financial Markets 57 : dans la plupart des marches developpes, le rendement de la
premiere demi-heure (depuis la cloture de la veille) prevoit celui de la derniere demi-heure, le Japon en tete (t 4,07) ;
[GHLZ18] Gao, Han, Li & Zhou 2018 (JFE) pour la regle ; [ZA23] [T : ORB_NQ, nexus/orb.py] Zarattini & Aziz 2023, « Can
Day Trading Really Be Profitable ? » (SSRN 4416622) : sens de la bougie des 5 premieres minutes, entree a la 6e minute,
stop a l extreme oppose de la bougie, sortie a la cloture (version 2023 : sans filtre de volume, HistData n a pas de
volume pour les indices).
Seances (heure locale) : Tokyo 9:00 -> 15:00, 15:30 depuis le 05/11/2024 ; EuroStoxx 9:00 -> 17:30 (Francfort) ;
FTSE 8:00 -> 16:30 (Londres). Jours : ceux ou le CFD cote a l ouverture et a la cloture locales.
  N1 = Nikkei, momentum intraday : signe de r(cloture J-1 -> ouverture + 30 min), position de cloture - 30 min a cloture ;
  N2 = Nikkei, ORB 2023 a l ouverture de Tokyo ;
  E1 = EuroStoxx 50, momentum intraday (meme regle que N1) ;
  E2 = FTSE 100, momentum intraday ;
  E3 = FTSE 100, ORB 2023 a l ouverture de Londres.
  Temoins : momentum : achat systematique de la derniere demi-heure ; ORB : meme entree et meme sortie dans le sens
  OPPOSE a la bougie (un sens au hasard ferait aussi bien si la bougie n apporte rien).
  Couts par cote, futures equivalents : Nikkei (NKD, 5 $ x indice, tick 5) 0,8 pb ; EuroStoxx (FESX, tick 1) 1,4 pb ;
  FTSE (Z, tick 0,5) 0,6 pb ; stress x 2. Essais : 5 -> 425.
  Reserve prop firm : FESX (Eurex) et Z (ICE) ne sont pas offerts par la plupart des prop firms CME ; NKD l est chez
  certaines, mais un contrat vaut environ 240 000 $.
  Avant calcul (2026-10-20 vers 11:45) : (1) HistData ne fournit plus l EuroStoxx 50 apres 02/2019 (fichier 2020 vide) :
  E1 n est pas testee, essais 424 ; (2) controle de l horodatage : HistData est en heure de New York avec l heure d ete
  americaine jusqu a fin 2018, europeenne depuis 2019 (nexus/histdata.vers_utc) ; apres correction, aucune semaine
  decalee (EURJPY contre 6E / 6J 0,989 ; AUDJPY 0,985 ; XAGUSD contre GC 0,75 ; JPXJPY contre NQ 0,64 ; UKXGBP contre ES
  0,67).
RESULTAT (2026-10-20 vers 11:38) : les quatre REJETEES. N1 Nikkei momentum : -1,65 pb net (t -3,8), Sharpe -1,16, brut
nul : l effet japonais de LSU22 (2000-2019) n existe plus en 2016-2026 ; N2 Nikkei ORB : -0,20 ; E2 FTSE momentum : -0,70 ;
E3 FTSE ORB : 0,04 (moities 0,42 / -0,37). Les regles qui marchent sur NQ (ORB) ne se transposent pas aux indices
europeens et japonais, comme deja sur le DAX (H3, H4).

-------------------------------------------------------------------------------------------------------------------------
A1 - ARGENT : MOMENTUM D UNE SESSION A L AUTRE (zone « Asie ») (protocole ecrit le 2026-10-20 vers 11:43, avant calcul)
-------------------------------------------------------------------------------------------------------------------------
Source : [WEI26] [R, catalogue SSRN] Wei 2026, « Who Moves the Price ? Trading-Session Return Decomposition and Cross-Session
Momentum in Gold and Silver Markets » (SSRN 7257240) : la session americaine annonce la session asiatique, pour l or ET
l argent. L or seul a ete rejete (H1, nexus/perso/creneaux.py) ; l argent n a jamais ete teste.
Regle de H1 sans changement, sur XAGUSD (HistData, horodatage controle contre GC : 0,75, aucune semaine decalee) : achat
de 00:00 a 08:00 UTC si la session americaine precedente (14:30 UTC -> 00:00) a monte ; temoin : la meme session
asiatique apres une session americaine en baisse. Couts : micro SIL (1 000 onces, tick 0,005 $ = 5 $) : 1,1 pb par cote,
stress x 2. Strategie de tous les jours (8 h a surveiller par jour). Essais : 425.
Note (sans essai) : la saisonnalite intraday du Brent (Ewald et al. 2025, Quantitative Finance ; SSRN 5037563) n est pas
testee : les heures exactes sont dans le texte payant (manuscrit sous embargo jusqu en 2027) ; les choisir nous-memes
serait de la fouille de donnees.
RESULTAT (2026-10-20 vers 11:44) : REJETEE. 1 383 trades, -2,51 pb net (t -0,96), Sharpe -0,29 [-0,88 ; 0,30] ; apres une
session americaine en BAISSE, l Asie fait mieux (+2,51 pb, Welch -1,24) : plutot un retournement, non significatif. Le
momentum de Wei 2026 ne tient ni sur l or (H1) ni sur l argent.

-------------------------------------------------------------------------------------------------------------------------
J1 - NIKKEI APRES LES RESULTATS DES GRANDES VALEURS JAPONAISES (zone « nuit », 22:00-10:00 New York, libre tous les jours)
(protocole ecrit le 2026-10-20 vers 11:47, AVANT de collecter les dates de publication)
-------------------------------------------------------------------------------------------------------------------------
Pourquoi (demande de l utilisateur du 2026-10-20 : un horaire que NQ 1-A, S1 et Gotobi ne prennent pas) : reprendre le
mecanisme de NQ 1-A, notre strategie la plus rentable par heure (diffusion lente des nouvelles des tres grandes
entreprises vers l indice : Hou 2007 ; NQ 1, etude des 60 strategies). Le Nikkei 225 est pondere par les PRIX : Fast
Retailing, Tokyo Electron, Advantest et SoftBank Group en font environ un quart ; elles publient leurs resultats apres la
cloture de Tokyo.
Donnees : dates et heures de publication des resultats trimestriels (« kessan tanshin ») de ces 4 societes, 2016-2026,
lues sur leurs pages investisseurs publiques (accord de l utilisateur du 2026-10-20) -> nexus/perso/resultats_japon.csv ;
Nikkei : CFD JPXJPY (HistData, horodatage controle contre NQ : 0,64, aucune semaine decalee ; cote 97 a 99 % des jours de
15:00 a 17:30 Tokyo) ; contrat negociable : NKD du CME (5 $ x indice), ouvert pendant la pause d Osaka.
Regle de NQ 1-A sans changement, transposee a Tokyo : T = heure de la premiere publication du jour parmi les 4 (heure de
Tokyo, entre la cloture et 17:30 ; une publication sans heure connue est exclue) ; signal = signe de r_Nikkei(cloture
de Tokyo -> T + 15 min) (cloture 15:00, 15:30 depuis le 05/11/2024) ; position de T + 15 a T + 45 dans ce sens.
  V = la regle ;
  temoin : les autres jours de bourse, signal r(cloture -> cloture + 20), position cloture + 20 -> cloture + 50 (comme le
  temoin de NQ 1-A).
  Couts : NKD, 0,8 pb par cote, stress x 2. Strategie d evenements (jours connus a l avance). Essais : 426.
  Amendement AVANT tout calcul (2026-10-20 vers 11:50, choix de l utilisateur) : les pages investisseurs ne donnent
  que les DATES (dans les PDF des resultats), pas l heure ; Kabutan et IR Bank refusent la lecture automatique (403) ;
  J-Quants demande un compte. Heure FIXE : T = 15:30 heure de Tokyo pour toutes les publications (la plupart des grandes
  valeurs publient entre 15:00 et 15:30). Signal : r(cloture de Tokyo -> 15:45) ; position 15:45 -> 16:15 Tokyo. Une
  publication plus tardive tombe hors de la fenetre : la regle est un substitut imprecis de NQ 1-A, a lire comme tel.
  Jours : dates des resultats trimestriels des 4 societes, lues sur la premiere page de chaque PDF (nexus/perso/japon.py).
RESULTAT (2026-10-20 vers 12:03) : REJETEE. 150 publications (145 jours, 13,6 par an ; Fast Retailing 43, Tokyo Electron 36,
Advantest 41, SoftBank Group 30, certains PDF anciens de SoftBank sans date lisible), 140 trades : -4,18 pb net (t -3,0),
Sharpe -0,89 [-1,43 ; -0,35], moities -0,28 / -1,34 ; les autres jours font aussi mal (-3,13 pb, Welch -0,74). Pas de
diffusion lente des resultats japonais dans le Nikkei a cette heure ; reserve : heure fixe 15:30 (l heure exacte manque).

-------------------------------------------------------------------------------------------------------------------------
D1 - DAX APRES LES RESULTATS DE SAP (zone « nuit » : 8:15-8:45 Francfort = 2:15-2:45 New York)
(protocole ecrit le 2026-10-20 vers 12:08, AVANT de collecter les dates de SAP)
-------------------------------------------------------------------------------------------------------------------------
Pourquoi : meme mecanisme que NQ 1-A (diffusion lente des nouvelles d une tres grande entreprise vers son indice) ; SAP
est le premier poids du DAX (10 a 15 %). Accord de l utilisateur du 2026-10-20 : dates et heures des resultats de SAP
depuis ses pages investisseurs publiques -> nexus/perso/resultats_sap.csv.
Cotation du CFD DAX (GRXEUR, horodatage controle) : 8:00-22:00 Francfort presque tous les jours ; avant 8:00, rien
jusqu a 2018 et la moitie des jours depuis ; rien apres 22:00. Regle de NQ 1-A, rendue negociable :
  T = heure de publication de SAP (heure de Francfort) ; hors de 8:00-22:00, T = 8:00 du jour de bourse suivant (ou du
  jour meme pour une publication avant 8:00) ; si l heure manque, publication supposee avant l ouverture (7:00), donc
  T = 8:00 ; signal = signe de r_DAX(cloture Xetra 17:30 precedente -> T + 15) ; position de T + 15 a T + 45.
  temoin : les autres jours de bourse, signal r(17:30 la veille -> 8:15), position 8:15 -> 8:45.
  Couts : FDAX (Eurex, 25 EUR par point, tick 1) environ 0,5 pb par cote ; FDXM / FDXS (micro) pour un compte prop firm
  qui offre l Eurex (la plupart des prop firms CME ne l offrent pas : reserve). Strategie d evenements. Essais : 427.
RESULTAT (2026-10-20 vers 15:20) : REJETEE. 43 publications (2016-2021 : calendrier financier archive, dates sans heure ;
depuis 07/2022 : salle de presse, heure exacte ; T = 8:00 pour 42), 40 trades : -1,17 pb net (t -0,57), Sharpe -0,17
[-0,73 ; 0,40], 24 derniers mois -0,24 ; pas mieux que les autres jours (Welch -0,37). Pas de diffusion lente des
resultats de SAP dans le DAX a l ouverture.
"""
from __future__ import annotations

import argparse
import math
import os
from datetime import datetime

import numpy as np
import pandas as pd

from .. import labo as L
from .creneaux import criteres
from .soixante import ET, PY_DIR, cout_bp, exporter, jours_ouvres_us, marche, tstat
from .soixante_bc import FIN_DONNEES, _inst, _r

N_ESSAIS, SEUIL_DSR = 427, 0.95
SORTIE = os.path.join(PY_DIR, "recherche", "resultats_zones.txt")


# =============================================================================
#  Outils communs
# =============================================================================
def veilles(jours: pd.DatetimeIndex) -> pd.DatetimeIndex:
    """Jour ouvre precedent de chaque jour de la liste (la liste elle-meme fait foi : le precedent dans la liste)."""
    j = pd.DatetimeIndex(jours)
    return pd.DatetimeIndex(np.r_[np.datetime64("NaT"), j.values[:-1]])


def trades_fenetre(m, jours: pd.DatetimeIndex, a: int, b: int, sens: np.ndarray, tz: str = ET) -> pd.DataFrame:
    """Une position par jour de a a b (minutes locales), dans le sens donne (+1 / -1, 0 ou NaN = pas de trade)."""
    ta, tb = _inst(jours, a, tz), _inst(jours, b, tz)
    lr = _r(m, ta, tb)
    ok = np.isfinite(lr) & np.isfinite(sens) & (sens != 0)
    return pd.DataFrame(dict(t_in=pd.to_datetime(ta[ok]), t_out=pd.to_datetime(tb[ok]), sens=np.sign(sens[ok]), r=np.expm1(lr[ok])))


def _signe(lr: np.ndarray) -> np.ndarray:
    return np.where(np.isfinite(lr), np.sign(lr), np.nan)


def tester(code: str, nom: str, trades: pd.DataFrame, cout: float, temoin: pd.DataFrame | None, pr, meta: dict) -> dict:
    """Portefeuille vectorbt (nexus.labo), criteres de la methode sur les trades vectorbt, labo.json mis a jour."""
    st, r, pos, net = L.evaluer(trades, cout / 2, N_ESSAIS)                     # cout = aller-retour : moitie par cote
    st2, _, _, _ = L.evaluer(trades, cout, N_ESSAIS)                            # stress : couts x 2
    tem = None
    if temoin is not None and len(temoin):
        _, _, _, tem = L.evaluer(temoin, cout / 2, N_ESSAIS)
    c = criteres(net, net, tem)
    retenue = bool(c["passe"] and st["dsr"] >= SEUIL_DSR)
    statut = "retenue" if retenue else ("fiable" if st["fiable"] else "rejetee")
    pr(f"  {code:<4} {nom:<62} {st['trades']:5d} trades | net {net.mean() * 1e4:+6.2f} pb (t {tstat(net):+.2f}) | Sharpe {st['sharpe']:+.2f} "
       f"[{st['ic_bas']:+.2f} ; {st['ic_haut']:+.2f}] moities {st['sharpe_p1']:+.2f} / {st['sharpe_p2']:+.2f} | 24 mois {st['sharpe_24m']:+.2f} | "
       f"deflate {st['dsr']:.2f} | {st['heures_an']:.0f} h/an | couts x 2 : {st2['sharpe']:+.2f} | {statut.upper()}")
    rate = [k for k, v in c["tests"].items() if not v] + ([] if st["dsr"] >= SEUIL_DSR else [f"Sharpe deflate >= {SEUIL_DSR}"])
    pr(f"       criteres : {'tous passes' if not rate else 'manque ' + ' ; '.join(rate)}"
       f"{' | temoin ' + format(tem.mean() * 1e4, '+.2f') + ' pb (Welch ' + format(c['welch'], '+.2f') + ')' if tem is not None else ''}")
    entree = dict(id=f"Z_{code}", nom=f"{code} {nom}", statut=statut, stats=dict(st, sharpe_couts_x2=st2["sharpe"]),
                  origine="recherche par zone (nexus/perso/zones.py)", criteres=dict(passe=c["passe"], manque=rate), **meta)
    e = L.etat()
    L.enregistrer(e, entree, r, pos)
    L.journal(f"{code} : {statut} (Sharpe {st['sharpe']:+.2f} [{st['ic_bas']:+.2f} ; {st['ic_haut']:+.2f}], 24 mois {st['sharpe_24m']:+.2f}, "
              f"{st['heures_an']:.0f} h/an)")
    return dict(code=code, nom=nom, stats=st, criteres=c, retenue=retenue, statut=statut)


# =============================================================================
#  Z1 - petrole, momentum intraday (Wen et al. 2019, 2020)
# =============================================================================
def z1(pr) -> list[dict]:
    titre = "Petrole : la nuit et la premiere demi-heure annoncent la derniere demi-heure (Wen et al. 2019, 2020)"
    L.debut("Z1", titre)
    pr("")
    pr("Z1 - " + titre.upper())
    cl = marche("CL")
    j = jours_ouvres_us(cl)
    j = j[j <= FIN_DONNEES]
    v = veilles(j)
    ok = ~pd.isna(v)
    j, v = j[ok], v[ok]
    cout = cout_bp("CL", float(np.nanmedian(cl.c[-500000:])), False) / 1e4
    s_v = _signe(_r(cl, _inst(v, 16 * 60, ET), _inst(j, 10 * 60, ET)))
    s_r = _signe(_r(cl, _inst(v, 16 * 60, ET), _inst(j, 9 * 60 + 30, ET)))
    tem = trades_fenetre(cl, j, 15 * 60 + 30, 16 * 60, np.ones(len(j)))
    meta = dict(source="Wen, Gong, Ma & Xu 2020 (SSRN 3553682) ; Wen, Cho, Ma & Xu 2019 (SSRN 3416022)",
                lien="https://papers.ssrn.com/sol3/papers.cfm?abstract_id=3553682", instruments=["CL"], heures="15:30-16:00 New York",
                hypothese="le rendement de la veille 16:00 a 10:00 (ou de la nuit) annonce celui de 15:30-16:00")
    pr(f"  cout aller-retour {cout * 1e4:.2f} pb ; jours {len(j)}")
    out = [tester("Z1", "CL 15:30-16:00 dans le sens de la veille 16:00 -> 10:00", trades_fenetre(cl, j, 15 * 60 + 30, 16 * 60, s_v), cout, tem, pr, meta),
           tester("Z1b", "CL 15:30-16:00 dans le sens de la nuit (16:00 -> 9:30)", trades_fenetre(cl, j, 15 * 60 + 30, 16 * 60, s_r), cout, tem, pr, meta)]
    L.fin()
    return out


# =============================================================================
#  Z2 - veilles de jours feries americains (Ariel 1990)
# =============================================================================
def veilles_feries(jours: pd.DatetimeIndex) -> pd.DatetimeIndex:
    from .suite_s import us_holiday
    j = pd.DatetimeIndex(jours)
    out = []
    for d, n in zip(j[:-1], j[1:]):
        k = d + pd.Timedelta(days=1)
        while k < n:
            if k.dayofweek < 5 and us_holiday(k.date()):
                out.append(d)
                break
            k += pd.Timedelta(days=1)
    return pd.DatetimeIndex(out)


def z2(pr) -> list[dict]:
    titre = "Veilles de jours feries americains : achat de 12:00 a la cloture (Ariel 1990)"
    L.debut("Z2", titre)
    pr("")
    pr("Z2 - " + titre.upper())
    out = []
    for code, root in (("Z2", "ES"), ("Z2b", "NQ")):
        m = marche(root)
        j = jours_ouvres_us(m)
        j = j[j <= FIN_DONNEES]
        pre = veilles_feries(j)
        fin_ = np.array([13 * 60 if (d.month, d.day) in ((7, 3), (12, 24)) else 16 * 60 for d in pre])
        autres = j[~j.isin(pre)]
        cout = cout_bp(root, float(np.nanmedian(m.c[-500000:])), False) / 1e4
        if code == "Z2":
            pr(f"  veilles de jours feries : {len(pre)} ({len(pre) / 10.65:.1f} par an) ; cout {cout * 1e4:.2f} pb (ES)")
        tr = trades_fenetre(m, pre, 12 * 60, fin_, np.ones(len(pre)))
        tem = trades_fenetre(m, autres, 12 * 60, 16 * 60, np.ones(len(autres)))
        meta = dict(source="Ariel 1990 (Journal of Finance 45(5)) ; Kim & Park 1994 (JFQA)", lien="https://doi.org/10.1111/j.1540-6261.1990.tb02446.x",
                    instruments=[root], heures="12:00-16:00 New York, veilles de jours feries",
                    hypothese="la veille d un jour ferie, les actions montent surtout l apres-midi")
        out.append(tester(code, f"{root} achat 12:00 -> cloture, veilles de jours feries", tr, cout, tem, pr, meta))
    L.fin()
    return out


# =============================================================================
#  N1-N2, E2-E3 - momentum intraday (Li, Sakkas & Urquhart 2022) et ORB 2023 sur le Nikkei et le FTSE (HistData)
# =============================================================================
def cfd(sym: str):
    """CFD HistData (index = fin de barre, UTC naif) -> objet marche compatible avec prix_a / _r (une seule echeance)."""
    from types import SimpleNamespace
    from ..data import DEFAULT_CACHE
    df = pd.read_parquet(os.path.join(DEFAULT_CACHE, "histdata", f"{sym}_1m.parquet"))
    return SimpleNamespace(t=pd.DatetimeIndex(df.index).as_unit("ns").asi8, o=df.open.to_numpy(float), h=df.high.to_numpy(float),
                           l=df.low.to_numpy(float), c=df.close.to_numpy(float), n=len(df), offset=np.zeros(len(df)))


SEANCES = {"JPXJPY": ("Asia/Tokyo", 9 * 60, lambda d: 15 * 60 if d < pd.Timestamp("2024-11-05") else 15 * 60 + 30),
           "UKXGBP": ("Europe/London", 8 * 60, lambda d: 16 * 60 + 30)}


def jours_seance(m, sym: str) -> tuple[pd.DatetimeIndex, np.ndarray]:
    """Jours ouvres ou le CFD cote a l ouverture, a ouverture + 30 min et a la cloture locales -> (jours, minute de cloture)."""
    from .soixante import prix_a
    tz, ouv, clo = SEANCES[sym]
    j = pd.bdate_range("2015-06-01", FIN_DONNEES)
    fin = np.array([clo(d) for d in j])
    ok = np.ones(len(j), bool)
    for minute in (ouv, ouv + 30, fin - 30, fin - 1):
        p, i = prix_a(m, _inst(j, minute, tz))
        ok &= np.isfinite(p) & (i >= 0)
    return j[ok], fin[ok]


def itsm(m, sym: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Momentum intraday : signe de r(cloture J-1 -> ouverture + 30) ; position de cloture - 30 a cloture ; temoin : achat."""
    tz, ouv, _ = SEANCES[sym]
    j, fin = jours_seance(m, sym)
    v = veilles(j)
    ok = ~pd.isna(v)
    idx = np.flatnonzero(ok)
    j, v, fin_v, fin = j[idx], v[idx], fin[idx - 1], fin[idx]
    sig = _signe(_r(m, _inst(v, fin_v, tz), _inst(j, ouv + 30, tz)))
    return trades_fenetre(m, j, fin - 30, fin, sig, tz), trades_fenetre(m, j, fin - 30, fin, np.ones(len(j)), tz)


def orb23(m, sym: str, miroir: bool = False) -> pd.DataFrame:
    """ORB 2023 (Zarattini & Aziz) : sens de la bougie ouverture -> ouverture + 5 min, entree a ouverture + 5, stop a l extreme
    oppose de la bougie, sortie a la cloture locale. miroir=True : sens oppose a la bougie, stop a l autre extreme (temoin)."""
    tz, ouv, _ = SEANCES[sym]
    j, fin = jours_seance(m, sym)
    t0, t5, tf = _inst(j, ouv, tz), _inst(j, ouv + 5, tz), _inst(j, fin, tz)
    debut = m.t - 60_000_000_000                                          # debut de barre
    rows = []
    for k in range(len(j)):
        a = np.searchsorted(debut, t0[k])
        b = np.searchsorted(debut, t5[k])
        e = np.searchsorted(debut, tf[k])
        if b - a < 3 or e - b < 10:
            continue
        o, c = m.o[a], m.c[b - 1]
        if c == o:
            continue
        sens = np.sign(c - o) * (-1 if miroir else 1)
        hi, lo = m.h[a:b].max(), m.l[a:b].min()
        stop = lo if sens > 0 else hi
        entree = m.o[b]
        if (sens > 0 and entree <= stop) or (sens < 0 and entree >= stop):
            continue
        L_, H_ = m.l[b:e], m.h[b:e]
        touche = np.flatnonzero(L_ <= stop) if sens > 0 else np.flatnonzero(H_ >= stop)
        if len(touche):
            i = b + touche[0]
            sortie = min(m.o[i], stop) if sens > 0 else max(m.o[i], stop)
            t_out = m.t[i]
        else:
            sortie, t_out = m.c[e - 1], m.t[e - 1]
        rows.append(dict(t_in=pd.Timestamp(m.t[b - 1]), t_out=pd.Timestamp(t_out), sens=sens, r=sortie / entree - 1))
    return pd.DataFrame(rows)


def n_e(pr) -> list[dict]:
    titre = "Regles qui marchent repliquees sur le Nikkei et le FTSE (Li, Sakkas & Urquhart 2022 ; Zarattini & Aziz 2023)"
    L.debut("N1-E3", titre)
    pr("")
    pr("N1-N2, E2-E3 - " + titre.upper())
    out = []
    lsu = dict(source="Li, Sakkas & Urquhart 2022 (Journal of Financial Markets 57)", lien="https://doi.org/10.1016/j.finmar.2021.100619",
               hypothese="la premiere demi-heure (depuis la cloture de la veille) annonce la derniere", type_jours="tous")
    za = dict(source="Zarattini & Aziz 2023 (SSRN 4416622), regle de l ORB_NQ", lien="https://papers.ssrn.com/sol3/papers.cfm?abstract_id=4416622",
              hypothese="la premiere bougie de 5 minutes donne le sens de la seance", type_jours="tous")
    for sym, nom, c_cote in (("JPXJPY", "Nikkei", 0.8e-4), ("UKXGBP", "FTSE", 0.6e-4)):
        m = cfd(sym)
        tr, tem = itsm(m, sym)
        code = "N1" if sym == "JPXJPY" else "E2"
        out.append(tester(code, f"{nom} : derniere demi-heure dans le sens de la veille -> ouverture + 30 min", tr, 2 * c_cote, tem, pr,
                          dict(lsu, instruments=[nom], heures="derniere demi-heure de la seance locale")))
        code = "N2" if sym == "JPXJPY" else "E3"
        out.append(tester(code, f"{nom} : ORB 2023 a l ouverture locale", orb23(m, sym), 2 * c_cote, orb23(m, sym, miroir=True), pr,
                          dict(za, instruments=[nom], heures="ouverture + 5 min -> cloture locale")))
    L.fin()
    return out


# =============================================================================
#  A1 - argent, momentum d une session a l autre (Wei 2026)
# =============================================================================
def a1(pr) -> list[dict]:
    titre = "Argent : la session americaine annonce la session asiatique (Wei 2026)"
    L.debut("A1", titre)
    pr("")
    pr("A1 - " + titre.upper())
    m = cfd("XAGUSD")
    j = pd.bdate_range("2016-01-04", FIN_DONNEES)
    v = veilles(j)
    ok = ~pd.isna(v)
    j, v = j[ok], v[ok]
    us = _r(m, _inst(v, 14 * 60 + 30, "UTC"), _inst(j, 0, "UTC"))
    sig = np.where(np.isfinite(us), np.where(us > 0, 1.0, np.nan), np.nan)
    tem = np.where(np.isfinite(us), np.where(us < 0, 1.0, np.nan), np.nan)
    meta = dict(source="Wei 2026 (SSRN 7257240)", lien="https://papers.ssrn.com/sol3/papers.cfm?abstract_id=7257240", instruments=["argent (SIL)"],
                heures="00:00-08:00 UTC", hypothese="la session americaine annonce la session asiatique (or et argent)", type_jours="tous")
    out = [tester("A1", "argent : achat de la session asiatique apres une session americaine en hausse",
                  trades_fenetre(m, j, 0, 8 * 60, sig, "UTC"), 2 * 1.1e-4, trades_fenetre(m, j, 0, 8 * 60, tem, "UTC"), pr, meta)]
    L.fin()
    return out


# =============================================================================
#  J1 - Nikkei apres les resultats des grandes valeurs japonaises (regle de NQ 1-A, heure fixe 15:30 Tokyo)
# =============================================================================
def j1(pr) -> list[dict]:
    from . import calendriers as K
    titre = "Nikkei apres les resultats de Fast Retailing, Tokyo Electron, Advantest, SoftBank (regle de NQ 1-A, 15:30 Tokyo)"
    L.debut("J1", titre)
    pr("")
    pr("J1 - " + titre.upper())
    tz = "Asia/Tokyo"
    m = cfd("JPXJPY")
    j, fin = jours_seance(m, "JPXJPY")
    ev = pd.DatetimeIndex(pd.to_datetime(K._csv("resultats_japon.csv").date).unique())
    est = j.isin(ev)
    T = 15 * 60 + 30
    s_ev = _signe(_r(m, _inst(j[est], fin[est], tz), _inst(j[est], T + 15, tz)))
    tr = trades_fenetre(m, j[est], T + 15, T + 45, s_ev, tz)
    au = ~est
    s_t = _signe(_r(m, _inst(j[au], fin[au], tz), _inst(j[au], fin[au] + 20, tz)))
    tem = trades_fenetre(m, j[au], fin[au] + 20, fin[au] + 50, s_t, tz)
    pr(f"  jours de publication : {len(ev)} dont {int(est.sum())} avec cotation ; temoin : {int(au.sum())} autres jours")
    meta = dict(source="regle de NQ 1-A (etude des 60 strategies ; Hou 2007) ; dates : pages investisseurs des 4 societes",
                lien="https://www.fastretailing.com/jp/ir/library/tanshin.html", instruments=["Nikkei (NKD)"],
                heures="15:45-16:15 Tokyo (1:45-2:15 New York l hiver)", type_jours="evenements",
                hypothese="le Nikkei met du temps a digerer les resultats de ses plus gros poids")
    out = [tester("J1", "Nikkei 15:45 -> 16:15 Tokyo dans le sens de cloture -> 15:45, jours de resultats", tr, 2 * 0.8e-4, tem, pr, meta)]
    L.fin()
    return out


# =============================================================================
#  D1 - DAX apres les resultats de SAP (regle de NQ 1-A, rendue negociable)
# =============================================================================
def evenements_sap(j: pd.DatetimeIndex) -> pd.DataFrame:
    """Une ligne par publication : jour de bourse E et minute T (Francfort) ou la regle s applique."""
    from . import calendriers as K
    c = K._csv("resultats_sap.csv")
    rows = []
    for v, connue in zip(c.francfort, c.heure_connue.astype(str) == "True"):
        t = pd.Timestamp(v)
        d = t.normalize()
        mn = t.hour * 60 + t.minute if connue else 7 * 60              # heure inconnue : avant l ouverture (7:00)
        if mn < 8 * 60:
            jour, T = d, 8 * 60
        elif mn <= 21 * 60 + 15:
            jour, T = d, mn
        else:
            jour, T = d + pd.Timedelta(days=1), 8 * 60                # apres 22:00 : 8:00 du jour de bourse suivant
        k = j.searchsorted(jour)
        if k < len(j):
            rows.append(dict(jour=j[k], T=T))
    return pd.DataFrame(rows).drop_duplicates("jour")


def d1(pr) -> list[dict]:
    from .dax_cloture import jours_xetra
    titre = "DAX apres les resultats de SAP (regle de NQ 1-A ; 8:15-8:45 Francfort le plus souvent)"
    L.debut("D1", titre)
    pr("")
    pr("D1 - " + titre.upper())
    tz = "Europe/Berlin"
    m = cfd("GRXEUR")
    j = jours_xetra("2016-01-04", FIN_DONNEES)
    ev = evenements_sap(j)
    k = j.searchsorted(pd.DatetimeIndex(ev.jour))
    veille = j[np.clip(k - 1, 0, None)]
    # cloture Xetra de reference : celle du jour meme si T est apres 17:30, sinon celle de la veille de bourse
    ref_j = pd.DatetimeIndex(np.where(ev["T"].to_numpy() > 17 * 60 + 30, pd.DatetimeIndex(ev.jour), veille))
    T = ev["T"].to_numpy()
    sig = _signe(_r(m, _inst(ref_j, 17 * 60 + 30, tz), _inst(pd.DatetimeIndex(ev.jour), T + 15, tz)))
    tr = trades_fenetre(m, pd.DatetimeIndex(ev.jour), T + 15, T + 45, sig, tz)
    autres = j[~j.isin(pd.DatetimeIndex(ev.jour))][1:]
    v_a = j[j.searchsorted(autres) - 1]
    s_t = _signe(_r(m, _inst(v_a, 17 * 60 + 30, tz), _inst(autres, 8 * 60 + 15, tz)))
    tem = trades_fenetre(m, autres, 8 * 60 + 15, 8 * 60 + 45, s_t, tz)
    pr(f"  publications : {len(ev)} ; T = 8:00 pour {int((ev['T'] == 480).sum())}, heure reelle pour {int((ev['T'] != 480).sum())} ; "
       f"temoin : {len(autres)} autres jours")
    meta = dict(source="regle de NQ 1-A (etude des 60 strategies ; Hou 2007) ; dates : salle de presse et calendrier financier de SAP",
                lien="https://news.sap.com/tags/earnings/", instruments=["DAX (FDAX / FDXM)"], heures="8:15-8:45 Francfort (2:15-2:45 New York)",
                type_jours="evenements", hypothese="le DAX met du temps a digerer les resultats de SAP, son premier poids")
    out = [tester("D1", "DAX T+15 -> T+45 dans le sens de la cloture Xetra -> T+15, jours de resultats de SAP", tr, 2 * 0.5e-4, tem, pr, meta)]
    L.fin()
    return out


HYPOTHESES = {"Z1": z1, "Z2": z2, "NE": n_e, "A1": a1, "J1": j1, "D1": d1}


def main(argv=None):
    ap = argparse.ArgumentParser(description="recherche par zone horaire (laboratoire)")
    ap.add_argument("--hypotheses", default=",".join(HYPOTHESES))
    a = ap.parse_args(argv)
    lignes = []

    def pr(x=""):
        print(x, flush=True)
        lignes.append(x)

    pr("=" * 118)
    pr(f" RECHERCHE PAR ZONE HORAIRE (nexus/perso/zones.py), essais cumules : {N_ESSAIS} - {datetime.now():%Y-%m-%d %H:%M}")
    pr("=" * 118)
    res = {}
    for h in [x.strip() for x in a.hypotheses.split(",") if x.strip()]:
        res[h] = HYPOTHESES[h](pr)
    with open(SORTIE, "a", encoding="utf-8") as fh:
        fh.write("\n".join(lignes) + "\n\n")
    for h, rs in res.items():
        exporter(f"zones_{h}", dict(code=h, resultats=[dict(code=x["code"], nom=x["nom"], statut=x["statut"], retenue=x["retenue"],
                                                            stats={k: v for k, v in x["stats"].items() if not isinstance(v, (list, dict))})
                                                       for x in rs]))


if __name__ == "__main__":
    main()
