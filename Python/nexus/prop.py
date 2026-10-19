"""Simulation d un challenge de prop firm sur l historique reel (un depart a chaque seance), a partir de la valeur
minute d un portefeuille vectorbt en contrats entiers. Regles : objectif de gain, perte max (statique, suiveuse en fin
de journee ou intraday, qui cesse de monter au solde de depart), perte journaliere eliminatoire (ecarts compris),
nombre minimum de jours, regle de coherence (meilleur jour <= une part du gain).

Toutes les valeurs viennent de pf.value() (vectorbt, a la minute) : le simulateur ne recalcule aucun P&L, il ne fait
que lire le plus haut, le plus bas et la cloture de chaque seance."""
import numpy as np
import pandas as pd

# Regles relevees le 2026-10-15 sur les pages des prop firms (a reverifier avant de s inscrire : elles changent souvent).
CHALLENGES = {
    "elite_diamond_100k": dict(nom="Elite Trader Funding, Diamond Hands 100K (nuit et week-end permis)", taille=100_000,
                               objectif=5_000, perte_max=3_500, type_perte="fin_de_jour", perte_jour=1_500, jours_min=5,
                               coherence=None, source="https://elitetraderfunding.com/diamondhands/"),
    "topstep_50k": dict(nom="Topstep 50K (a plat a 16:10 New York, pas de week-end)", taille=50_000, objectif=3_000,
                        perte_max=2_000, type_perte="fin_de_jour", perte_jour=1_000, jours_min=1, coherence=0.5,
                        source="https://help.topstep.com/en/articles/8284204-what-is-the-maximum-loss-limit"),
}


def simuler(valeur_minute: pd.Series, date_seance: np.ndarray, regles: dict, max_jours: int = 250) -> pd.DataFrame:
    """valeur_minute : pf.value() (minute) ; date_seance : date de seance CME de chaque barre (meme longueur).
    regles : taille, objectif, perte_max, type_perte ('statique' | 'fin_de_jour' | 'intraday'), perte_jour (ou None),
    jours_min. -> une ligne par jour de depart : resultat ('reussi', 'perdu', 'en cours'), jours, raison."""
    v = valeur_minute.to_numpy(float)
    d = np.asarray(date_seance)
    debut = np.r_[0, np.flatnonzero(d[1:] != d[:-1]) + 1]
    fin = np.r_[debut[1:], len(d)] - 1
    jours = pd.DatetimeIndex(d[debut])
    hauts = np.maximum.reduceat(v, debut)                      # plus haut intraday de chaque seance
    bas = np.minimum.reduceat(v, debut)                        # plus bas intraday
    clot = v[fin]
    taille, obj, mll = regles["taille"], regles["objectif"], regles["perte_max"]
    typ, dll, jmin = regles["type_perte"], regles.get("perte_jour"), regles.get("jours_min", 1)
    coh = regles.get("coherence")                               # meilleur jour <= coh x gain total (None : pas de regle)
    sorties = []
    for s in range(1, len(debut) - 1):
        ref = clot[s - 1]                                      # depart a la cloture de la seance precedente
        seuil = -mll
        pic_eod, pic_intra = 0.0, 0.0
        res, raison, nj = "en cours", "", 0
        veille, meilleur = 0.0, 0.0
        for k in range(s, min(len(debut), s + max_jours)):
            nj += 1
            lo, hi, cl = bas[k] - ref, hauts[k] - ref, clot[k] - ref
            if typ == "intraday":
                pic_intra = max(pic_intra, hi)
                seuil = min(0.0, max(seuil, pic_intra - mll))  # approximation : le pic du jour est compte avant le creux
            if lo <= seuil:
                res, raison = "perdu", "perte max"
                break
            if dll is not None and lo <= veille - dll:
                res, raison = "perdu", "perte journaliere"
                break
            if typ == "fin_de_jour":
                pic_eod = max(pic_eod, cl)
                seuil = min(0.0, max(seuil, pic_eod - mll))
            meilleur = max(meilleur, cl - veille)
            veille = cl
            if cl >= obj and nj >= jmin and (coh is None or meilleur <= coh * cl):
                res, raison = "reussi", "objectif"
                break
        sorties.append(dict(depart=jours[s], resultat=res, jours=nj, raison=raison))
    return pd.DataFrame(sorties)


def resume(df: pd.DataFrame) -> dict:
    fini = df[df.resultat != "en cours"]
    return dict(departs=len(df), reussite=float((df.resultat == "reussi").mean()), echec=float((df.resultat == "perdu").mean()),
                en_cours=float((df.resultat == "en cours").mean()),
                jours_median_reussite=float(df.loc[df.resultat == "reussi", "jours"].median()) if (df.resultat == "reussi").any() else np.nan,
                reussite_si_fini=float((fini.resultat == "reussi").mean()) if len(fini) else np.nan)
