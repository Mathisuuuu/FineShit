"""Dates et heures des publications de resultats de SAP (2016-2026) -> resultats_sap.csv (etude D1, nexus/perso/zones.py).

    python -m nexus.perso.sap

Accord de l utilisateur du 2026-10-20 (pages investisseurs publiques de SAP). Les pages www.sap.com/investors refusent la
lecture automatique (403) ; les 6-K de SAP sur EDGAR sont deposes plusieurs jours apres la publication. Source retenue :
la salle de presse officielle de SAP (news.sap.com, etiquette « earnings ») : chaque communique « SAP Announces Q.. Results »
porte son heure de publication (champ datePublished, UTC). La salle de presse n a plus les communiques d avant 2022
(adresses redirigees vers des pages supprimees) : pour 2016-2021, DATES lues dans les copies archivees (Wayback Machine) du
calendrier financier de SAP (www.sap.com/investors/en/calendar.html, « Past Events »), sans heure. Pages lues : l etiquette « earnings » (depuis 2022) et la recherche du site (« announces results », « preliminary results »,
« pre-announces », « quarter results ») pour 2016-2021 ; communiques de resultats seulement (trimestriels, annuels,
preliminaires), pas les annonces de date. Les pages telechargees ne sont que lues (texte), jamais executees.
"""
from __future__ import annotations

import json
import os
import re
import time
import urllib.error
import urllib.request

import pandas as pd

ICI = os.path.dirname(__file__)
CACHE = os.path.normpath(os.path.join(ICI, "..", "..", ".cache", "sap"))
UA = {"User-Agent": "Mozilla/5.0 (recherche personnelle)"}
ETIQUETTE = "https://news.sap.com/tags/earnings/"
RESULTATS = re.compile(r"(q[1-4]-20\d\d|quarter|full-year|fiscal-year|preliminary|results|half-year)", re.I)


def _lire(url: str) -> str | None:
    os.makedirs(CACHE, exist_ok=True)
    f = os.path.join(CACHE, re.sub(r"[^\w]+", "_", url)[-150:] + ".html")
    if os.path.exists(f):
        with open(f, encoding="utf-8", errors="ignore") as fh:
            return fh.read()
    data = None
    for essai in range(3):                                            # l archive coupe parfois la connexion : pause et nouvel essai
        try:
            data = urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=90).read().decode("utf-8", "ignore")
            break
        except urllib.error.HTTPError as ex:
            if ex.code == 404:
                return None
            time.sleep(10 * (essai + 1))
        except (urllib.error.URLError, ConnectionError, TimeoutError):
            time.sleep(10 * (essai + 1))
    if data is None:
        return None
    time.sleep(2.0 if "archive.org" in url else 0.7)
    with open(f, "w", encoding="utf-8") as fh:
        fh.write(data)
    return data


RECHERCHES = ("announces+results", "preliminary+results", "pre-announces", "quarter+results")


def _pages(base: str, pages_max: int = 40) -> list[str]:
    vus = []
    for k in range(1, pages_max + 1):
        html = _lire(base(k))
        if html is None:
            break
        liens = re.findall(r'href="(https://news\.sap\.com/20\d\d/\d\d/[^"#?]+/)"', html)
        nouveaux = [u for u in dict.fromkeys(liens) if u not in vus]
        if not nouveaux:
            break
        vus += nouveaux
    return vus


def est_resultat(u: str) -> bool:
    """Communique de resultats (trimestriels, annuels ou preliminaires), pas une annonce de date ni un changement d heure."""
    slug = u.rsplit("/", 2)[-2]
    return (bool(re.search(r"announces|pre-announces|reports", slug)) and bool(RESULTATS.search(slug))
            and not re.search(r"to-release|to-announce|updated-time|date|conference|webcast|dividend", slug))


def articles() -> list[str]:
    tous = _pages(lambda k: ETIQUETTE if k == 1 else f"{ETIQUETTE}page/{k}/")
    for q in RECHERCHES:
        tous += _pages(lambda k, q=q: f"https://news.sap.com/?s={q}" if k == 1 else f"https://news.sap.com/page/{k}/?s={q}")
    return sorted({u for u in tous if est_resultat(u)})


def publication(url: str) -> pd.Timestamp | None:
    html = _lire(url)
    if not html:
        return None
    m = re.search(r'"datePublished":"([^"]+)"', html) or re.search(r'article:published_time" content="([^"]+)"', html)
    return pd.Timestamp(m.group(1)).tz_convert("UTC").tz_localize(None) if m else None


# copies archivees (Wayback Machine) du calendrier financier de SAP : dates des resultats, sans heure. Jusqu a 2019, la
# copie liste les evenements passes ; ensuite seulement le dernier, plus les evenements A VENIR (dates prevues).
CAL = "https://www.sap.com/investors/en/calendar.html"
MOIS_EN = "(?:January|February|March|April|May|June|July|August|September|October|November|December)"
TITRE = r"([^/]{0,90}?(?:Financial Results|Preliminary Results|Interim Report|Quarterly Statement|Year Results))"
A_VENIR = re.compile(rf"({MOIS_EN} \d{{1,2}}\s*,\s*20\d\d) / {TITRE}")
PASSE = re.compile(rf"{TITRE} Walldorf, ({MOIS_EN} \d{{1,2}}\s*,\s*20\d\d)")


def instantanes() -> list[str]:
    t = _lire(f"http://web.archive.org/cdx/search/cdx?url=sap.com/investors/en/calendar.html&from=2016&to=2022"
              f"&output=json&filter=statuscode:200&collapse=timestamp:6")
    return [r[1] for r in json.loads(t)[1:]] if t else []


def calendrier_archive() -> pd.DataFrame:
    import html as H
    rows = []
    for ts in instantanes():
        t = _lire(f"http://web.archive.org/web/{ts}/{CAL}")
        if not t:
            continue
        t = re.sub(r"<script.*?</script>|<style.*?</style>", " ", t, flags=re.S)
        t = " ".join(H.unescape(re.sub(r"<[^>]+>", " ", t)).split())
        quand = pd.Timestamp(ts[:8])
        for m in A_VENIR.finditer(t):
            d = pd.Timestamp(re.sub(r"\s*,", ",", m.group(1)))
            if "Debt" not in m.group(2):
                rows.append(dict(date=d, titre=m.group(2).strip()[:80], instantane=quand, passe=d <= quand))
        for m in PASSE.finditer(t):
            rows.append(dict(date=pd.Timestamp(re.sub(r"\s*,", ",", m.group(2))), titre=m.group(1).strip()[:80], instantane=quand, passe=True))
    r = pd.DataFrame(rows).sort_values("date")
    out = []
    r["groupe"] = (r.date.diff().dt.days.fillna(999) > 20).cumsum()       # un trimestre = des dates a moins de 20 jours
    for _, g in r.groupby("groupe"):
        conf = g[g.passe & (g.instantane >= g.date)]
        if len(conf):
            ligne = conf.sort_values("instantane").iloc[0]
            source = "confirmee (evenement passe)"
        else:
            avant = g[g.instantane < g.date]
            if not len(avant):
                continue
            ligne = avant.sort_values("instantane").iloc[-1]                   # le plan le plus recent avant la date
            source = "prevue (derniere copie avant la date)"
        out.append(dict(slug=ligne.titre, date=ligne.date, source=f"web.archive.org calendrier SAP, {source}"))
    return pd.DataFrame(out).sort_values("date")


def construire(log=print) -> pd.DataFrame:
    rows = []
    for u in articles():
        t = publication(u)
        if t is not None:
            rows.append(dict(slug=u.rsplit("/", 2)[-2], publie_utc=t, url=u))
    out = pd.DataFrame(rows).sort_values("publie_utc")
    out["francfort"] = pd.DatetimeIndex(out.publie_utc).tz_localize("UTC").tz_convert("Europe/Berlin").tz_localize(None)
    cal = calendrier_archive()
    connus = set(pd.DatetimeIndex(out.francfort).normalize())
    cal = cal[~cal.date.isin(connus) & (cal.date < pd.DatetimeIndex(out.francfort).min().normalize())]
    log(f"[sap] calendriers archives : {len(cal)} publications datees (sans heure) avant {pd.DatetimeIndex(out.francfort).min():%Y-%m-%d}")
    out = pd.concat([out, pd.DataFrame(dict(slug=cal.slug, publie_utc=pd.NaT, url=cal.source, francfort=cal.date))], ignore_index=True)
    out["heure_connue"] = out.publie_utc.notna()
    out = out.sort_values("francfort")
    out = out[(out.francfort >= "2016-01-01") & (out.francfort <= "2026-08-28")]
    sortie = os.path.join(ICI, "resultats_sap.csv")
    with open(sortie, "w", encoding="utf-8", newline="") as fh:
        fh.write("# Communiques de resultats de SAP (news.sap.com, etiquette earnings) : heure de publication (datePublished) en UTC\n"
                 f"# et a Francfort ; lus le {pd.Timestamp.now():%Y-%m-%d} (nexus/perso/sap.py).\n")
        out.assign(publie_utc=out.publie_utc.dt.strftime("%Y-%m-%d %H:%M:%S"),
                   francfort=[x.strftime("%Y-%m-%d %H:%M:%S") if k else x.strftime("%Y-%m-%d") for x, k in zip(out.francfort, out.heure_connue)]
                   ).to_csv(fh, index=False)
    log(f"[sap] {len(out)} communiques -> {sortie}")
    return out


if __name__ == "__main__":
    construire()
