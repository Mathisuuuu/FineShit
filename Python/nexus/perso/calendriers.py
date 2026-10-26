"""Calendriers publics des fiches de niveau B et C (60 strategies) et controle par le volume.

    python -m nexus.perso.calendriers          -> taux de confirmation de chaque calendrier par le pic de volume

Fichiers (sources officielles, lues le 2026-10-10, detail en tete de chaque fichier) :
  banques_centrales.csv  BCE, Banque d Angleterre, Banque du Japon, Banque de reserve d Australie
  chine_nbs.csv          chiffres d activite chinois (NBS), date et heure de Pekin
  resultats_megacaps.csv resultats trimestriels (8-K item 2.02, SEC EDGAR) de AAPL, MSFT, AMZN, GOOGL, META, NVDA
  annonces_us.csv        NFP, CPI, PCE, ventes au detail (deja utilise par les fiches FX et or)
Calendriers par regle (pas de source officielle gratuite des dates passees) : ISM manufacturier (1er jour ouvre du mois)
et ISM services (3e jour ouvre), Conference Board (confiance des consommateurs, dernier mardi du mois), tous a 10:00 ET.

Controle : une date n est gardee que si le volume des 2 minutes qui suivent l heure annoncee depasse 2 fois la mediane
des 20 jours ouvres precedents sans evenement a la meme heure (le marche reagit toujours a une publication reelle). Le
volume des 2 premieres minutes ne sert qu a reconstituer un calendrier public connu a l avance ; il n entre dans aucun
signal.
"""
from __future__ import annotations

import os
from datetime import date, timedelta

import numpy as np
import pandas as pd

from .or_anomalies import instants
from .suite_s import us_holiday

ICI = os.path.dirname(__file__)
NS_MIN = 60_000_000_000
ET, FRANCFORT, LONDRES, TOKYO, SYDNEY, PEKIN = ("America/New_York", "Europe/Berlin", "Europe/London", "Asia/Tokyo",
                                                "Australia/Sydney", "Asia/Shanghai")
CHANGEMENT_BCE = pd.Timestamp("2022-07-21")            # decision 13:45 -> 14:15, conference 14:30 -> 14:45 (Francfort)
SEUIL_VOLUME = 2.0


# =============================================================================
#  Fichiers
# =============================================================================
def _csv(nom: str) -> pd.DataFrame:
    return pd.read_csv(os.path.join(ICI, nom), comment="#")


def banque(code: str, urgences: bool = False) -> pd.DatetimeIndex:
    """Dates des decisions (BCE, BOE, BOJ, RBA). Les reunions d urgence (hors calendrier) sont exclues par defaut."""
    c = _csv("banques_centrales.csv")
    c = c[(c.banque == code) & (urgences | (c.statut != "urgence"))]
    return pd.DatetimeIndex(pd.to_datetime(c.date)).sort_values()


def heures_bce(jours: pd.DatetimeIndex) -> tuple[np.ndarray, np.ndarray]:
    """(decision, conference) en minutes depuis minuit, heure de Francfort."""
    apres = np.asarray(pd.DatetimeIndex(jours) >= CHANGEMENT_BCE)
    return np.where(apres, 14 * 60 + 15, 13 * 60 + 45), np.where(apres, 14 * 60 + 45, 14 * 60 + 30)


def nbs() -> pd.DataFrame:
    """Chiffres d activite chinois : date (heure de Pekin) et minute de publication ; jours de semaine seulement."""
    c = _csv("chine_nbs.csv")
    c["date"] = pd.to_datetime(c.date)
    hm = c.heure.str.split(":", expand=True).astype(int)
    c["minute"] = hm[0] * 60 + hm[1]
    return c[c.date.dt.dayofweek < 5].reset_index(drop=True)


def megacaps(seulement_apres_cloture: bool = True) -> pd.DataFrame:
    """Resultats des 6 grandes capitalisations : un evenement par jour, heure = premier 8-K accepte de la journee.
    Exclus : 8-K hors publication trimestrielle (pre-annonces du matin de NVDA, GOOGL du 20/04/2023)."""
    c = _csv("resultats_megacaps.csv")
    c = c[~((c.symbole == "GOOGL") & (c.date == "2023-04-20"))]
    hm = c.accepte.str.split(":", expand=True).astype(int)
    c = c.assign(date=pd.to_datetime(c.date), minute=hm[0] * 60 + hm[1] + (hm[2] > 0))     # minute entamee
    if seulement_apres_cloture:
        c = c[c.minute >= 16 * 60]
    g = c.groupby("date").agg(minute=("minute", "min"), symboles=("symbole", lambda s: "+".join(sorted(s))))
    return g.reset_index()


def annonces_us(types=("NFP", "CPI")) -> pd.DatetimeIndex:
    c = _csv("annonces_us.csv")
    return pd.DatetimeIndex(pd.to_datetime(c[c.evenement.isin(types)].date)).unique().sort_values()


# =============================================================================
#  Calendriers par regle (ISM, Conference Board)
# =============================================================================
def _ouvres_du_mois(a: int, m: int) -> list[date]:
    d, out = date(a, m, 1), []
    while d.month == m:
        if d.weekday() < 5 and not us_holiday(d):
            out.append(d)
        d += timedelta(days=1)
    return out


def ism(services: bool = False, debut: int = 2016, fin: int = 2026) -> pd.DatetimeIndex:
    """ISM manufacturier : 1er jour ouvre du mois ; services : 3e jour ouvre. 10:00 ET."""
    k = 2 if services else 0
    return pd.DatetimeIndex([_ouvres_du_mois(a, m)[k] for a in range(debut, fin + 1) for m in range(1, 13)])


def conference_board(debut: int = 2016, fin: int = 2026) -> pd.DatetimeIndex:
    """Confiance des consommateurs du Conference Board : dernier mardi du mois, 10:00 ET (decembre parfois avance)."""
    out = []
    for a in range(debut, fin + 1):
        for m in range(1, 13):
            d = date(a + (m == 12), m % 12 + 1, 1) - timedelta(days=1)
            while d.weekday() != 1:
                d -= timedelta(days=1)
            out.append(d)
    return pd.DatetimeIndex(out)


# =============================================================================
#  Controle par le volume
# =============================================================================
def volume_apres(m, debut_ns: np.ndarray, minutes: int = 2) -> np.ndarray:
    """Volume des barres qui commencent dans [debut, debut + minutes) (nos barres sont horodatees a leur fin)."""
    if getattr(m, "_cumv", None) is None:
        m._cumv = np.r_[0.0, np.cumsum(np.nan_to_num(m.v))]
    i0 = np.searchsorted(m.t, debut_ns, side="right")
    i1 = np.searchsorted(m.t, debut_ns + minutes * NS_MIN, side="right")
    return m._cumv[i1] - m._cumv[i0]


def jours_semaine(debut: str = "2016-01-01", fin: str = "2026-09-30") -> pd.DatetimeIndex:
    return pd.bdate_range(debut, fin)


def rapport_volume(m, dates: pd.DatetimeIndex, minute: np.ndarray | int, tz: str, exclus: pd.DatetimeIndex | None = None,
                   minutes: int = 2) -> pd.Series:
    """Volume des `minutes` qui suivent l heure annoncee / mediane des 20 jours de semaine precedents (meme heure locale,
    sans evenement). `minute` : minute locale (scalaire ou une par date)."""
    dates = pd.DatetimeIndex(dates)
    minute = np.broadcast_to(np.asarray(minute), (len(dates),))
    tous = jours_semaine()
    exclus = dates.union(exclus) if exclus is not None else dates
    out = pd.Series(np.nan, index=dates)
    for mn in np.unique(minute):
        v = pd.Series(volume_apres(m, instants(tous, int(mn) // 60, int(mn) % 60, tz), minutes), index=tous)
        v[v <= 0] = np.nan
        base = v.where(~tous.isin(exclus)).rolling(20, min_periods=10).median().shift(1)
        sel = minute == mn
        d = dates[sel]
        vd = pd.Series(volume_apres(m, instants(d, int(mn) // 60, int(mn) % 60, tz), minutes), index=d)
        out[d] = (vd / base.reindex(d)).to_numpy()
    return out


def confirmes(m, dates, minute, tz, exclus=None) -> pd.DatetimeIndex:
    r = rapport_volume(m, dates, minute, tz, exclus)
    return pd.DatetimeIndex(r.index[r >= SEUIL_VOLUME])


def heure_boj(j6, dates: pd.DatetimeIndex, seuil: float = 10.0) -> pd.Series:
    """Heure de publication de la Banque du Japon (pas d heure fixe, horodatee par les agences au moment de la
    publication) reconstituee : minute de plus fort volume du 6J entre 11:00 et 14:30 (Tokyo), retenue si ce volume depasse
    `seuil` fois la mediane de la meme minute sur les 20 jours de semaine precedents sans reunion. Le premier passage d un
    seuil se declenche trop tot sur le bruit de la pause de midi (19/03/2024 : 11:45 au lieu de 12:35). -> minute de Tokyo
    ou NaN."""
    tous = jours_semaine()
    dates = pd.DatetimeIndex(dates)
    vol, rap = {}, {}
    for mn in range(11 * 60, 14 * 60 + 30):
        v = pd.Series(volume_apres(j6, instants(tous, mn // 60, mn % 60, TOKYO), 1), index=tous)
        v[v <= 0] = np.nan
        base = v.where(~tous.isin(dates)).rolling(20, min_periods=10).median().shift(1)
        vol[mn], rap[mn] = v.reindex(dates), (v / base).reindex(dates)
    vol, rap = pd.DataFrame(vol), pd.DataFrame(rap)
    pic = vol.fillna(-1).idxmax(axis=1).where(vol.notna().any(axis=1))
    ok = np.array([rap.loc[d, p] >= seuil if p == p else False for d, p in pic.items()])
    return pic.where(ok).astype(float)


# =============================================================================
#  Rapport de controle
# =============================================================================
def controle(log=print) -> dict:
    from .fx_trois import fx
    es, e6, b6, j6, a6 = (fx(r) for r in ("ES", "6E", "6B", "6J", "6A"))
    res = {}

    def ligne(nom, dates, r):
        r = r.dropna()
        ok = (r >= SEUIL_VOLUME).sum()
        log(f"  {nom:<34} {len(dates):>4} dates, {len(r):>4} avec donnees, {ok:>4} confirmees ({ok / max(len(r), 1):.0%}), "
            f"rapport median {r.median():5.1f}")
        res[nom] = r

    log("Controle par le pic de volume (2 premieres minutes / mediane des 20 jours precedents, seuil 2) :")
    for nom, d in (("ISM manufacturier (1er jour ouvre)", ism()), ("ISM services (3e jour ouvre)", ism(True)),
                   ("Conference Board (dernier mardi)", conference_board())):
        d = d[d <= pd.Timestamp("2026-08-28")]
        ligne(nom + " ES 10:00 ET", d, rapport_volume(es, d, 600, ET))
    d = banque("BCE")
    dec, _ = heures_bce(d)
    ligne("BCE 6E decision (Francfort)", d, rapport_volume(e6, d, dec, FRANCFORT))
    d = banque("BOE")
    ligne("BOE 6B 12:00 Londres", d, rapport_volume(b6, d, 720, LONDRES))
    d = banque("RBA")
    ligne("RBA 6A 14:30 Sydney", d, rapport_volume(a6, d, 870, SYDNEY))
    c = nbs()
    ligne("NBS 6A heure du calendrier (Pekin)", pd.DatetimeIndex(c.date), rapport_volume(a6, pd.DatetimeIndex(c.date), c.minute.to_numpy(), PEKIN))
    d = banque("BOJ")
    h = heure_boj(j6, d)
    log(f"  BOJ 6J heure detectee (Tokyo)     {len(d):>4} dates, {h.notna().sum():>4} detectees ; heures : "
        + ", ".join(f"{int(x) // 60:02d}:{int(x) % 60:02d}" for x in h.dropna().quantile([0.1, 0.5, 0.9])) + " (deciles 1, 5, 9)")
    res["BOJ"] = h
    return res


if __name__ == "__main__":
    controle()
