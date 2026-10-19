"""NQ 1 (diffusion des resultats des grandes capitalisations) : deux variantes corrigees, protocole fixe AVANT le test.

    python -m nexus.perso.nq1_variantes [--sortie resultats_nq1_variantes.txt]

Point de depart (etape 2, resultats_60_niveaux_BC.txt) : la version d origine A echoue de peu (t 2,8 pour un seuil de 3 ;
Welch 3,0 ; net +3,3 pb). Elle a ete VUE : toute variante testee sur les memes donnees est un essai de plus, et la
meilleure de plusieurs variantes parait toujours meilleure qu elle n est. Protocole ecrit le 2026-10-10, avant tout calcul
sur les variantes ; chacune corrige un defaut identifie a l avance, aucune ne retouche un seuil :

  A  origine : T = premier 8-K de resultats accepte sur EDGAR (16:00-16:43 ET) ; signal r_NQ(16:00 -> T+15) ; position NQ
     T+15 -> min(T+45, 16:59) dans le sens du signal.
     Defaut 1 : le 8-K suit le communique de presse de 1 a 47 min (2 h le 30/07/2020) ; la fenetre est souvent decalee,
     voire coupee par l arret de 17:00.
     Defaut 2 : le signal est le NQ lui-meme, alors que le mecanisme (Hou 2007 ; Jiang et al.) est la diffusion LENTE de
     la nouvelle d une grande entreprise vers les autres : le signal naturel est la reaction de l action qui publie.
  B  heure du communique (corrige le defaut 1) : regle A, mais T = heure reelle de publication, reconstituee par le volume
     de l action qui publie : premiere minute de 16:00 a 16:45 ET ou son volume depasse 20 fois la mediane de la meme
     minute sur ses 20 seances precedentes sans resultats (detection au fil de l eau) ; a defaut, T du 8-K.
  C  reaction de l action (corrige les defauts 1 et 2) : T de B ; signal = somme des r_action(16:00 -> T+15) des
     entreprises qui publient ce jour-la ; position NQ T+15 -> min(T+45, 16:59) dans ce sens.
  Temoins : A et B, autres jours, signal r_NQ(16:00 -> 16:20), position 16:20 -> 16:50 (comme l etape 2) ; C, autres
  jours, signal = moyenne des 6 actions 16:00 -> 16:20, position NQ 16:20 -> 16:50.

Rien d autre n est essaye (ni seuil de taille de la surprise, ni autre sortie, ni filtre de regime) : chaque ajout serait un
essai de plus. Retenue = tous les criteres de la vue d ensemble ET Sharpe deflate >= 0,95 pour 33 essais (les 31 anomalies
deja testees sur les 60 strategies, plus B et C). Les deux variantes sont rapportees quel que soit leur resultat.

Ajout apres la premiere execution (2026-10-10) : controle de l heure reconstituee, qui manquait au protocole. AAPL, NVDA
et GOOGL deposent leur 8-K a la minute de leur communique : l heure detectee doit tomber entre 8-K - 3 min et 8-K + 1 min
dans au moins 90 % des cas pour chacune, sinon B et C sont INVALIDES (ils ne mesurent pas la reaction au communique).
La premiere execution a montre que la detection se declenche avant le communique (volume de positionnement d apres-
cloture : AAPL detectee vers 16:05 au lieu de 16:30), et une detection corrigee (volume SOUTENU sur 3 minutes, 20 fois la
normale et 8 fois le niveau du jour depuis 16:01) ne passe pas non plus ce controle. Arret ici : regler davantage la
detection apres avoir vu le resultat de B serait de la sur-optimisation.
"""
from __future__ import annotations

import argparse
import os
from datetime import datetime

import numpy as np
import pandas as pd

from . import calendriers as K
from .alternatives import dsr
from .soixante import ET, PY_DIR, Spy, cout_bp, criteres, exporter, jours_ouvres_us, marche, tstat
from .soixante_bc import FIN_DONNEES, _inst, _r, _rs

ACTIONS = ("AAPL", "MSFT", "AMZN", "GOOGL", "META", "NVDA")
NS_MIN = 60_000_000_000
SEUIL_VOLUME, BASE, FENETRE = 20.0, 20, (16 * 60, 16 * 60 + 45)
DERNIER_T = 16 * 60 + 43                     # T + 15 < 16:59
N_ESSAIS, SEUIL_DSR = 33, 0.95


def evenements_8k() -> pd.DataFrame:
    """Une ligne par (action, jour) de resultats apres la cloture, avec la minute du 8-K (minute entamee)."""
    c = K._csv("resultats_megacaps.csv")
    c = c[~((c.symbole == "GOOGL") & (c.date == "2023-04-20"))]
    hm = c.accepte.str.split(":", expand=True).astype(int)
    c = c.assign(date=pd.to_datetime(c.date), minute_8k=hm[0] * 60 + hm[1] + (hm[2] > 0))
    return c[c.minute_8k >= 16 * 60].reset_index(drop=True)


def volumes_minute(a: Spy, fin: int = FENETRE[1]) -> pd.DataFrame:
    """Volume par jour (lignes) et minute ET de DEBUT de barre (colonnes) de 16:00 a `fin` ; 0 si aucune transaction."""
    debut = pd.DatetimeIndex(a.t - NS_MIN).tz_localize("UTC").tz_convert(ET).tz_localize(None)
    mn = debut.hour * 60 + debut.minute
    sel = (mn >= FENETRE[0]) & (mn <= fin)
    df = pd.DataFrame({"jour": debut[sel].normalize(), "mn": mn[sel], "v": a.v[sel]})
    return df.pivot_table(index="jour", columns="mn", values="v", aggfunc="sum").reindex(
        columns=range(FENETRE[0], fin + 1)).fillna(0.0)


def heure_communique(a: Spy, jours_resultats: pd.DatetimeIndex) -> pd.Series:
    """Premiere minute (16:00-16:45 ET) ou le volume de l action depasse SEUIL_VOLUME fois la mediane de la meme minute sur
    ses BASE seances precedentes sans resultats. Index = jours de resultats ; NaN si aucune minute ne depasse."""
    v = volumes_minute(a)
    v = v[v.sum(axis=1) > 0]
    sans = v.copy()
    sans.loc[v.index.isin(jours_resultats)] = np.nan                       # jours de resultats hors de la reference
    base = sans.rolling(BASE, min_periods=10).median().shift(1)
    rap = (v / base.where(base > 0)).reindex(jours_resultats)
    passe = rap.ge(SEUIL_VOLUME)
    return passe.idxmax(axis=1).where(passe.any(axis=1)).astype(float)


def heure_communique_soutenue(a: Spy, jours_resultats: pd.DatetimeIndex, k_hist: float = 20.0, k_jour: float = 8.0) -> pd.Series:
    """Detection corrigee (essayee apres la premiere execution) : premiere minute m de 16:01 a 16:45 ET ou la mediane des
    volumes de m, m+1, m+2 depasse k_hist fois sa normale (20 seances precedentes sans resultats) ET k_jour fois le volume
    median du jour depuis 16:01 (un pic isole d une minute ou le positionnement d avant communique ne declenchent pas)."""
    v = volumes_minute(a, fin=16 * 60 + 47)
    v = v[v.sum(axis=1) > 0]
    sans = v.copy()
    sans.loc[v.index.isin(jours_resultats)] = np.nan
    med3 = v.T.rolling(3).median().shift(-2).T
    hist = sans.T.rolling(3).median().shift(-2).T.rolling(BASE, min_periods=10).median().shift(1)
    out = {}
    for d in pd.DatetimeIndex(jours_resultats):
        t = np.nan
        if d in v.index:
            x, h, m3 = v.loc[d], hist.loc[d], med3.loc[d]
            for m in range(16 * 60 + 1, 16 * 60 + 46):
                ref = np.median(x.loc[16 * 60 + 1: m - 1]) if m - (16 * 60 + 1) >= 2 else h[m]
                if m3[m] >= k_hist * h[m] and m3[m] >= k_jour * ref:
                    t = m
                    break
        out[d] = t
    return pd.Series(out, dtype=float)


def validation_heures(ev: pd.DataFrame, col: str) -> tuple[bool, list[str]]:
    """AAPL, NVDA, GOOGL : heure detectee dans [8-K - 3, 8-K + 1] min pour au moins 90 % des publications."""
    lignes, ok = [], True
    for s in ACTIONS:
        e = (ev.loc[ev.symbole == s, col] - ev.loc[ev.symbole == s, "minute_8k"])
        dans = ((e >= -3) & (e <= 1)).mean()
        med = ev.loc[ev.symbole == s, col].median()
        ref = s in ("AAPL", "NVDA", "GOOGL")
        ok &= (dans >= 0.9) or not ref
        lignes.append(f"{s:<5} detectee {e.notna().sum():>2}/{len(e)} | heure mediane "
                      f"{'-' if med != med else f'{int(med) // 60}:{int(med) % 60:02d}'} | ecart au 8-K median {e.median():+.0f} min | "
                      f"dans [-3, +1] : {dans:.0%}" + ("  (reference : 8-K a la minute du communique)" if ref else ""))
    return ok, lignes


def preparer(log=print) -> tuple[pd.DataFrame, dict, dict]:
    """Evenements par jour : T du 8-K (A), T du communique (B, C), actions qui publient, controle des heures."""
    ev = evenements_8k()
    actions = {s: Spy(s) for s in ACTIONS}
    ev["minute_com"], ev["minute_sout"] = np.nan, np.nan
    for s, a in actions.items():
        m = ev.symbole == s
        d = pd.DatetimeIndex(ev.loc[m, "date"])
        ev.loc[m, "minute_com"] = heure_communique(a, d).reindex(d).to_numpy()
        ev.loc[m, "minute_sout"] = heure_communique_soutenue(a, d).reindex(d).to_numpy()
    ev["minute_b"] = ev.minute_com.fillna(ev.minute_8k)
    jours = ev.groupby("date").agg(t_8k=("minute_8k", "min"), t_b=("minute_b", "min"),
                                   symboles=("symbole", lambda x: "+".join(sorted(x))))
    controle = {"protocole": validation_heures(ev, "minute_com"), "corrigee": validation_heures(ev, "minute_sout")}
    log(f"[NQ 1] {len(ev)} publications, heure du communique detectee pour {ev.minute_com.notna().sum()}")
    return jours.reset_index(), actions, controle


def variantes(nq, jours: pd.DataFrame, actions: dict) -> dict:
    jours = jours[jours.date <= FIN_DONNEES]
    tous = pd.DatetimeIndex(jours.date)
    tj = jours_ouvres_us(nq)
    tj = tj[~tj.isin(tous)]
    sortie = lambda T: np.minimum(T + 45, 16 * 60 + 59)

    def regle_nq(d, T):
        return np.sign(_rs(nq, d, 16 * 60, T + 15, ET)) * _rs(nq, d, T + 15, sortie(T), ET) * 1e4

    temoin_nq = np.sign(_rs(nq, tj, 16 * 60, 16 * 60 + 20, ET)) * _rs(nq, tj, 16 * 60 + 20, 16 * 60 + 50, ET) * 1e4
    out = {}
    a = jours[jours.t_8k <= DERNIER_T]
    out["A"] = dict(nom="A - origine (heure du 8-K, signal NQ)", serie=regle_nq(pd.DatetimeIndex(a.date), a.t_8k.to_numpy().astype(int)),
                    temoin=temoin_nq)
    b = jours[jours.t_b <= DERNIER_T]
    db, Tb = pd.DatetimeIndex(b.date), b.t_b.to_numpy().astype(int)
    out["B"] = dict(nom="B - heure du communique (volume de l action), signal NQ", serie=regle_nq(db, Tb), temoin=temoin_nq)
    # C : reaction des actions qui publient, de 16:00 a T+15
    reac = np.zeros(len(b))
    for k, (d, T, syms) in enumerate(zip(db, Tb, b.symboles)):
        r = [_r(actions[s], _inst([d], 16 * 60, ET), _inst([d], T + 15, ET))[0] for s in syms.split("+")]
        r = [x for x in r if np.isfinite(x)]
        reac[k] = np.sum(r) if r else np.nan
    cible = _rs(nq, db, Tb + 15, sortie(Tb), ET) * 1e4
    moy6 = np.nanmean(np.vstack([_r(actions[s], _inst(tj, 16 * 60, ET), _inst(tj, 16 * 60 + 20, ET)) for s in ACTIONS]), axis=0)
    temoin_c = pd.Series(np.sign(moy6), index=tj) * _rs(nq, tj, 16 * 60 + 20, 16 * 60 + 50, ET) * 1e4
    out["C"] = dict(nom="C - heure du communique, signal = reaction de l action", serie=pd.Series(np.sign(reac), index=db) * cible,
                    temoin=temoin_c)
    accord = pd.Series(np.sign(reac), index=db) == np.sign(_rs(nq, db, 16 * 60, Tb + 15, ET))
    out["C"]["complement"] = f"signal de l action et signal du NQ de meme sens : {accord.mean():.0%} des jours"
    return out


def etude(sortie: str | None = None, log=print) -> dict:
    t0 = datetime.now()
    nq = marche("NQ")
    jours, actions, controle = preparer(log)
    v = variantes(nq, jours, actions)
    heure_ok = controle["protocole"][0]
    cout = cout_bp("NQ", float(np.nanmedian(nq.c[-500000:])), True)
    L = []
    pr = L.append
    pr("=" * 118)
    pr(" NQ 1 - DIFFUSION DES RESULTATS DES GRANDES CAPITALISATIONS : VARIANTES CORRIGEES (protocole fixe avant le test)")
    pr("=" * 118)
    pr("Protocole : en-tete de nexus/perso/nq1_variantes.py. Retenue = criteres de la vue d ensemble ET Sharpe deflate")
    pr(f">= {SEUIL_DSR:.2f} pour {N_ESSAIS} essais. A a deja ete vue (etape 2) ; B et C sont des essais supplementaires.\n")
    pr("Controle de l heure du communique reconstituee par le volume de l action (B et C) :")
    for ligne in controle["protocole"][1]:
        pr("    " + ligne)
    pr("    -> " + ("valide" if heure_ok else "ECHEC : l heure detectee precede souvent le communique (positionnement d apres-cloture) ; "
                     "B et C ne mesurent pas la reaction au communique et sont INVALIDES, quel que soit leur resultat"))
    pr("Detection corrigee, essayee APRES la premiere execution (volume soutenu sur 3 min, 20 x la normale, 8 x le niveau du jour) :")
    for ligne in controle["corrigee"][1]:
        pr("    " + ligne)
    pr("    -> " + ("valide" if controle["corrigee"][0] else "ECHEC aussi : arret ; regler encore la detection apres avoir vu B "
                     "serait de la sur-optimisation"))
    pr("")
    res = {}
    for k in ("A", "B", "C"):
        d = v[k]
        x = pd.Series(d["serie"]).dropna()
        c = criteres(x, pd.Series(d["temoin"]).dropna(), cout)
        p_dsr = dsr(x - cout, N_ESSAIS)
        invalide = k in ("B", "C") and not heure_ok
        retenue = c["passe"] and p_dsr >= SEUIL_DSR and not invalide
        res[k] = dict(c, dsr=p_dsr, retenue=retenue, serie=x)
        pr(f"--- {d['nom']}")
        pr(f"    {c['n']} jours | moyenne {c['moyenne']:+.2f} pb (t {c['t']:+.1f}) | 2016-2020 {c['m1']:+.2f} (t {c['t1']:+.1f}) | "
           f"2021-2026 {c['m2']:+.2f} (t {c['t2']:+.1f})")
        pr(f"    temoin {c['temoin']:+.2f} pb, Welch {c['welch']:+.1f} | cout {c['cout']:.2f} pb -> net {c['net']:+.2f} pb, "
           f"sans les 3 meilleurs jours {c['sans3']:+.2f} pb | Sharpe deflate ({N_ESSAIS} essais) {p_dsr:.2f}")
        if d.get("complement"):
            pr(f"    {d['complement']}")
        an = x.groupby(x.index.year).agg(["mean", "count"])
        pr("    par annee (pb, nombre) : " + " ".join(f"{a}:{m:+.1f}({n})" for a, (m, n) in an.iterrows()))
        echecs = [t for t, ok in c["tests"].items() if not ok] + ([] if p_dsr >= SEUIL_DSR else [f"Sharpe deflate >= {SEUIL_DSR:.2f}"])
        if invalide:
            pr("    VERDICT : INVALIDE (heure du communique mal reconstituee, voir le controle)"
               + (" ; sinon il manquerait : " + " ; ".join(echecs) if echecs else "") + "\n")
        else:
            pr(f"    VERDICT : {'RETENUE' if retenue else 'ECHOUE (' + ' ; '.join(echecs) + ')'}\n")
    pr(f"Calcul en {(datetime.now() - t0).total_seconds():.0f} s.")
    sortie = sortie or os.path.join(PY_DIR, "recherche", "resultats_nq1_variantes.txt")
    with open(sortie, "w", encoding="utf-8") as fh:
        fh.write("\n".join(L) + "\n")
    lignes = []
    for k in ("A", "B", "C"):
        r = res[k]
        x, net = r["serie"], r["serie"] - cout
        sh = lambda s: float(s.mean() / s.std(ddof=1) * np.sqrt(len(x) / ((x.index.max() - x.index.min()).days / 365.25)))
        lignes.append(dict(code=k, nom=v[k]["nom"], n=r["n"], moyenne=r["moyenne"], t=r["t"], t1=r["t1"], t2=r["t2"],
                           welch=r["welch"], net=r["net"], sans3=r["sans3"], dsr=r["dsr"], sharpe_an=sh(net),
                           invalide=k in ("B", "C") and not heure_ok, retenue=r["retenue"],
                           echecs=[t for t, ok in r["tests"].items() if not ok]
                           + ([] if r["dsr"] >= SEUIL_DSR else [f"Sharpe deflate >= {SEUIL_DSR:.2f}"])))
    exporter("nq1", dict(lignes=lignes, n_essais=N_ESSAIS, seuil_dsr=SEUIL_DSR, heure_valide=heure_ok,
                         controle=controle["protocole"][1]))
    log("\n".join(L))
    return res


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--sortie", default=None)
    a = ap.parse_args(argv)
    etude(a.sortie)


if __name__ == "__main__":
    main()
