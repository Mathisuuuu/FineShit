"""Cycle de vie d un compte de prop firm (nexus.prop_comptes) sur des seances construites a la main : evaluation,
coherence, perte max suiveuse verrouillee, payouts (jours gagnants, part, plafond, partage), frais, plafond de
contrats, et prix en dollars d un contrat a travers un roll."""
import numpy as np
import pandas as pd

from nexus import prop_comptes as P

R0 = dict(objectif=3000, perte_max=2000, intraday=0, verrou_eval=100, perte_jour=0, coherence=0.5, jours_min=2,
          prix_eval=100, mensuel=0, prix_reset=100, activation=50, verrou_finance=100, jours_payout=5,
          gain_jour_payout=150, part_payout=0.5, plafond_payout=2000, min_payout=500, partage=0.9, plafond_eval=40,
          plafond_finance=40, intraday_finance=0, perte_jour_finance=0)


def _cycle(gains, bas=None, regles=None, taille=1.0):
    g = np.asarray(gains, float)
    lo = np.minimum(g, 0.0) if bas is None else np.asarray(bas, float)
    L, H, C = lo[None, :], np.maximum(g, 0.0)[None, :], g[None, :]
    W, eq = np.ones_like(C), np.array([1.0])
    R = P.vecteur_regles({**R0, **(regles or {})})
    t = np.array([taille])
    return P.cycle(L, H, C, W, eq, np.arange(len(g)), t, t, R)


def test_evaluation_puis_payouts():
    x = _cycle([1000] * 3 + [400] * 10)
    # eval reussie en 3 jours (meilleur jour 1 000 <= 50 % de 3 000) ; finance : 5 jours >= 150 -> payout de
    # min(2 000, 50 % de 2 000) = 1 000, puis 5 jours de plus : solde 1 000 + 2 000 = 3 000 -> payout 1 500
    net, frais, recus, npay, nevals, nok, nperdus, premier = x
    assert nok == 1 and npay == 2 and frais == 150 and nevals == 1 and nperdus == 0
    assert np.isclose(recus, 0.9 * (1000 + 1500)) and np.isclose(net, recus - 150) and premier == 8


def test_coherence_et_jours_min():
    x = _cycle([3000, 0, 0])
    assert x[5] == 0                                    # 3 000 en un jour : meilleur jour > 50 % du gain
    x = _cycle([2000, 2000])
    assert x[5] == 1                                    # 4 000 en 2 jours, meilleur 2 000 <= 50 %


def test_perte_max_suiveuse_et_verrou():
    x = _cycle([1500, -1000, -600])
    assert x[4] == 1                                    # seuil a -500 apres 1 500 : 500 puis -100, toujours au-dessus
    x = _cycle([1500, -1000, -1100])
    assert x[4] == 2 and x[1] == 200                    # -600 <= -500 : perdu, nouvelle evaluation payee
    x = _cycle([1500, 1500, -2000, -1500], regles=dict(objectif=10_000))
    # pic 3 000 -> seuil verrouille a +100 (et pas a +1 000) ; -2 000 laisse 1 000 > 100 ; -1 500 -> -500 : perdu
    assert x[4] == 2


def test_compte_finance_perdu_rachete():
    x = _cycle([1000] * 3 + [-2100])
    assert x[5] == 1 and x[6] == 1 and x[4] == 2 and x[1] == 100 + 50 + 100


def test_perte_journaliere_coupe_la_journee():
    x = _cycle([-1500, -1500], regles=dict(perte_jour=1000))
    assert x[4] == 2                                    # -1 000 puis -1 000 : seuil -2 000 touche le 2e jour


def test_plafond_de_contrats_et_arrondi():
    L = np.array([[-10.0], [-10.0]])
    C = np.array([[10.0], [10.0]])
    lo, hi, cl = P._jour(L, np.maximum(C, 0), C, np.array([[1.0], [2.0]]), np.array([10.0, 1.0]),
                         np.array([2.0, 7.4]), 25.0, 0)
    # 2 x 6J = 20 micros ; S1 : arrondi(7,4 x 2) = 15 micros, ramenes aux 5 restants
    assert np.isclose(cl, 2 * 10 + 5 * 10) and np.isclose(lo, 20 - 50)


def test_prix_dollar_a_travers_un_roll():
    brut = np.array([100.0, 101.0, 110.0, 111.0])        # roll : le brut saute de 101 a 110, l ajuste non
    adj_c = np.array([100.0, 101.0, 101.0 * 1.0, 101.0 * 111 / 110])
    adj_o = adj_c.copy()
    vo, vc = P.prix_dollar(brut, adj_o, adj_c, 10.0)
    assert np.allclose(np.diff(vc), [10.0, 0.0, 10.0])  # 1 point a 10 $, rien au roll, 1 point brut apres


def test_plancher_remonte_au_premier_payout():
    # finance : 5 jours de 400 -> payout 1 000 (solde 1 000), plancher mis a +100 : -950 fait sauter le compte
    x = _cycle([1000] * 3 + [400] * 5 + [-950])
    assert x[3] == 1 and x[6] == 1
    x = _cycle([1000] * 3 + [400] * 5 + [-950], regles=dict(verrou_apres_payout=0))
    assert x[3] == 1 and x[6] == 0                      # sans la regle : plancher suiveur a 0 (pic 2 000), 1 000 - 950 > 0


def test_chemin_consistency():
    r = dict(mode_payout=1, jours_payout=3, coherence_payout=0.4, gain_jour_payout=0, plafond_payout=3000)
    x = _cycle([1000] * 3 + [500, 500, 500], regles=r)
    assert x[3] == 1 and np.isclose(x[2], 0.9 * 750)    # 3 jours, meilleur 500 <= 40 % de 1 500 = 600 : payout 750
    x = _cycle([1000] * 3 + [900, 100, 100], regles=r)
    assert x[3] == 0                                    # meilleur jour 900 > 40 % de 1 100


def test_echelle_de_contrats():
    # finance plafonne a 1 contrat sous 1 500 $ de solde, 3 au-dessus : gains 1 000 / jour par contrat
    r = dict(plafond_finance=1, palier1=1500, plafond_palier1=3, palier2=1e12, plafond_palier2=0, jours_payout=99)
    g = np.array([1000.0] * 3 + [1000.0] * 3)
    L, H, C = np.zeros((1, 6)), g[None, :], g[None, :]
    R = P.vecteur_regles({**R0, **r})
    x = P.cycle(L, H, C, np.ones((1, 6)), np.array([1.0]), np.arange(6), np.array([1.0]), np.array([5.0]), R)
    assert x[5] == 1 and x[3] == 0                      # eval en 3 jours, puis finance sans payout (99 jours exiges)
    # 1 contrat les 2 premiers jours (solde 0 puis 1 000), 3 ensuite (solde 2 000) : on le lit dans le payout force
    x = P.cycle(L, H, C, np.ones((1, 6)), np.array([1.0]), np.arange(6), np.array([1.0]), np.array([5.0]),
                P.vecteur_regles({**R0, **r, "jours_payout": 3, "gain_jour_payout": 1, "plafond_payout": 1e9, "part_payout": 1.0}))
    assert np.isclose(x[2], 0.9 * (1000 + 1000 + 3000))
