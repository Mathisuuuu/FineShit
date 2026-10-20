"""Dates de publication des resultats trimestriels de Fast Retailing, Tokyo Electron, Advantest et SoftBank Group (2016-2026),
reconstituees depuis leurs pages investisseurs publiques (accord de l utilisateur du 2026-10-20) -> resultats_japon.csv.

    python -m nexus.perso.japon

  - Advantest : les archives de resultats portent la date dans leur nom (result/AAAAMMJJ.zip, result/JE_BIZ_AAMMJJ_slide.pdf) ;
    les trimestres sans archive datee : date lue sur la premiere page du PDF de resultats (E_FR_FY..._.Q.pdf).
  - Fast Retailing et SoftBank Group : PDF JAPONAIS du « kessan tanshin » (la page anglaise de Fast Retailing est au format de la
    bourse de Hong Kong, illisible avant 2018 ; celle de SoftBank ne porte pas la date) : la premiere date complete de la
    couverture est la date de publication (format japonais normalise, eres Heisei et Reiwa converties).
  - Tokyo Electron (fyNNqNtanshin-e.pdf, fy53-fy58 = exercices 2016-2021) et PDF anglais d Advantest : premiere date de la
    premiere page qui n est pas precedee de « ended / ending / as of / period / payment / dividend / filing / meeting /
    through / from » et qui tombe dans les 100 jours apres la fin de periode. Controle : la meme regle sur les PDF d Advantest
    dont la date est connue par le nom du fichier.
Les heures ne figurent pas sur ces pages : l etude J1 (nexus/perso/zones.py) prend 15:30 heure de Tokyo, fixe dans son protocole.
Les PDF telecharges ne sont que lus (pypdf), jamais executes.
"""
from __future__ import annotations

import io
import os
import re
import time
import urllib.parse
import urllib.request

import pandas as pd

ICI = os.path.dirname(__file__)
CACHE = os.path.normpath(os.path.join(ICI, "..", "..", ".cache", "japon"))
UA = {"User-Agent": "Mozilla/5.0 (recherche personnelle)"}
PAGES = {"Fast Retailing": "https://www.fastretailing.com/eng/ir/library/tanshin.html",
         "Tokyo Electron": "https://www.tel.com/ir/library/report/index.html",
         "Advantest": "https://www.advantest.com/en/investors/ir-library/result/",
         "SoftBank Group": "https://group.softbank/en/ir/financials/financial_reports"}
MOIS = {m: i + 1 for i, m in enumerate(["january", "february", "march", "april", "may", "june", "july", "august", "september",
                                        "october", "november", "december"])}
DATE = re.compile(r"(January|February|March|April|May|June|July|August|September|October|November|December)\s+(\d{1,2}),\s*(20\d\d)",
                  re.I)


def _lire(url: str) -> bytes:
    data = urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=90).read()
    time.sleep(0.5)
    return data


def _page(nom: str) -> str:
    os.makedirs(CACHE, exist_ok=True)
    f = os.path.join(CACHE, re.sub(r"\W+", "_", nom) + ".html")
    if not os.path.exists(f):
        with open(f, "wb") as fh:
            fh.write(_lire(PAGES[nom]))
    with open(f, encoding="utf-8", errors="ignore") as fh:
        return fh.read()


def _pdf(url: str) -> bytes:
    f = os.path.join(CACHE, "pdf", re.sub(r"[^\w.]+", "_", urllib.parse.urlparse(url).path)[-120:])
    os.makedirs(os.path.dirname(f), exist_ok=True)
    if not os.path.exists(f):
        data = _lire(url)
        if data[:4] != b"%PDF":
            raise ValueError(f"pas un PDF : {url}")
        with open(f, "wb") as fh:
            fh.write(data)
    with open(f, "rb") as fh:
        return fh.read()


DATE_JP = re.compile(r"(平成|令和)?\s*(\d{1,4})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日")
DATE_EN2 = re.compile(r"(\d{1,2})\s+(January|February|March|April|May|June|July|August|September|October|November|December)\s+(20\d\d)", re.I)
EXCLUS = re.compile(r"(ended|ending|as of|period|payment|dividend|filing|meeting|through|from|effective|to)\W*$", re.I)


def _texte(pdf: bytes) -> str:
    from pypdf import PdfReader
    return PdfReader(io.BytesIO(pdf)).pages[0].extract_text() or ""


def date_japonaise(pdf: bytes) -> pd.Timestamp | None:
    """Premiere date complete de la couverture d un tanshin japonais (eres Heisei / Reiwa converties)."""
    import unicodedata
    txt = unicodedata.normalize("NFKC", _texte(pdf))
    for m in DATE_JP.finditer(txt):
        an = int(m.group(2)) + {"平成": 1988, "令和": 2018}.get(m.group(1), 0)
        try:
            return pd.Timestamp(an, int(m.group(3)), int(m.group(4)))
        except ValueError:
            continue
    return None


def date_publication(pdf: bytes) -> pd.Timestamp | None:
    """PDF anglais : premiere date de la premiere page qui n est pas une date de periode, de paiement ou de depot, et qui
    tombe dans les 100 jours apres la fin de periode (la plus recente des dates precedees de ended / ending / as of)."""
    txt = _texte(pdf)
    dates = [(m.start(), pd.Timestamp(int(m.group(3)), MOIS[m.group(1).lower()], int(m.group(2)))) for m in DATE.finditer(txt)]
    dates += [(m.start(), pd.Timestamp(int(m.group(3)), MOIS[m.group(2).lower()], int(m.group(1)))) for m in DATE_EN2.finditer(txt)]
    dates.sort()
    if not dates:
        return None
    fins = [d for pos, d in dates if re.search(r"(ended|as of)\s*$", txt[max(0, pos - 25):pos].replace("\n", " "), re.I)]  # pas « ending » (prevision)
    fin = max(fins) if fins else min(d for _, d in dates)
    for pos, d in dates:
        avant = txt[max(0, pos - 45):pos].replace("\n", " ")
        if fin < d <= fin + pd.Timedelta(days=100) and not EXCLUS.search(avant):
            return d
    return None


PAGES_JP = {"SoftBank Group": "https://group.softbank/ir/financials/financial_reports"}


def liens(nom: str) -> list[str]:
    if nom == "Fast Retailing":                                        # PDF japonais, adresse reguliere
        return [f"https://www.fastretailing.com/jp/ir/library/pdf/tanshin{a}08_{q}q.pdf" for a in range(2016, 2027) for q in range(1, 5)]
    if nom == "SoftBank Group":
        html = _lire(PAGES_JP[nom]).decode("utf-8", "ignore")
        base = "https://group.softbank"
        return sorted({urllib.parse.urljoin(base, u) for u in re.findall(r'href="([^"]*financial-report_q\dfy20(?:1[5-9]|2\d)_01_ja\.pdf)"', html)})
    html = _page(nom)
    base = "{0.scheme}://{0.netloc}".format(urllib.parse.urlparse(PAGES[nom]))
    if nom == "Fast Retailing":
        pat = r'href="([^"]*tanshin20(?:1[6-9]|2\d)08_\dq_eng\.pdf)"'
    elif nom == "Tokyo Electron":
        pat = r'href="([^"]*fy(?:5[2-8]|2\d)q\dtanshin(?:_r1)?-e(?:_1)?\.pdf)"'          # fy53-fy58 = exercices 2016-2021 (numero d exercice)
    elif nom == "SoftBank Group":
        pat = r'href="([^"]*financial-report_q\dfy20(?:1[5-9]|2\d)_01_en\.pdf)"'
    else:
        pat = r'href="([^"]*E_FR_FY20(?:1[5-9]|2\d)_\dQ\.pdf)"'
    return sorted({urllib.parse.urljoin(base, u) for u in re.findall(pat, html)})


def advantest_noms() -> list[pd.Timestamp]:
    html = _page("Advantest")
    d = [pd.Timestamp(x) for x in re.findall(r"result/(20\d{6})\.zip", html)]
    d += [pd.Timestamp("20" + x) for x in re.findall(r"result/JE_BIZ_(\d{6})_slide\.pdf", html)]
    return sorted(set(d))


def construire(log=print) -> pd.DataFrame:
    rows = []
    for nom in PAGES:
        for u in liens(nom):
            try:
                d = (date_japonaise if nom in ("Fast Retailing", "SoftBank Group") else date_publication)(_pdf(u))
            except Exception as ex:                                     # noqa: BLE001
                log(f"[japon] {nom} : {u} illisible ({type(ex).__name__})")
                continue
            if d is None:
                log(f"[japon] {nom} : pas de date dans {u}")
                continue
            rows.append(dict(societe=nom, date=d, source=u, methode="pdf"))
        log(f"[japon] {nom} : {sum(r['societe'] == nom for r in rows)} dates lues dans les PDF")
    noms = advantest_noms()
    pdf_adv = {r["date"] for r in rows if r["societe"] == "Advantest"}
    proches = [d for d in noms if any(abs((d - p).days) <= 31 for p in pdf_adv)]       # le meme trimestre
    exacts = [d for d in proches if d in pdf_adv]
    log(f"[japon] controle Advantest : {len(noms)} dates par le nom des fichiers, {len(pdf_adv)} par les PDF ; meme trimestre "
        f"{len(proches)}, date identique {len(exacts)}")
    if proches and len(exacts) < 0.9 * len(proches):
        raise RuntimeError("lecture des dates des PDF anglais non conforme au controle Advantest : arret")
    rows = [r for r in rows if not (r["societe"] == "Advantest" and any(abs((r["date"] - d).days) <= 31 for d in noms))]
    for d in noms:
        rows.append(dict(societe="Advantest", date=d, source=PAGES["Advantest"], methode="nom du fichier"))
    out = pd.DataFrame(rows)
    out = out[(out.date >= "2016-01-01") & (out.date <= "2026-08-28") & (out.date.dt.dayofweek < 5)]   # une publication tombe un jour de semaine
    out = out.sort_values(["societe", "date"]).drop_duplicates(["societe", "date"])
    garde = out.groupby("societe").date.diff().dt.days.fillna(999) > 5                                 # un trimestre : la premiere date
    out = out[garde].sort_values(["date", "societe"])
    sortie = os.path.join(ICI, "resultats_japon.csv")
    with open(sortie, "w", encoding="utf-8", newline="") as fh:
        fh.write("# Publications de resultats trimestriels (dates, heure de Tokyo inconnue) : Fast Retailing, Tokyo Electron, Advantest,\n"
                 f"# SoftBank Group ; pages investisseurs publiques, lues le {pd.Timestamp.now():%Y-%m-%d} (nexus/perso/japon.py).\n")
        out.assign(date=out.date.dt.strftime("%Y-%m-%d")).to_csv(fh, index=False)
    log(f"[japon] {len(out)} publications -> {sortie}")
    log(out.groupby("societe").size().to_string())
    return out


if __name__ == "__main__":
    construire()
