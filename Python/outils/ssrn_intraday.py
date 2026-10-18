"""Catalogue des articles SSRN dont l hypothese est au moins intraday (intraday, haute frequence, nuit / seance,
ouverture / cloture, microstructure), avec leurs liens, filtrable et annotable.

Sources (API publiques et gratuites, sans cle) : OpenAlex (titres + resumes de la revue « SSRN Electronic
Journal ») et Crossref (tous les DOI SSRN, prefixe 10.2139). SSRN n a pas d API et interdit l aspiration de son
site : on passe donc par ces deux index, qui couvrent les articles SSRN dotes d un DOI.

    python outils/ssrn_intraday.py --sortie ssrn_intraday            # -> ssrn_intraday.csv et ssrn_intraday.html
    python outils/ssrn_intraday.py --sortie x --mailto vous@exemple.fr # file prioritaire d OpenAlex (facultatif)

Methode :
  1. une requete par mot-cle (MOTS_CLES) dans les titres et resumes, toutes les pages ;
  2. fusion par numero SSRN ;
  3. filtre « au moins intraday » : le titre ou le resume doit contenir un terme d horizon (HORIZONS) ;
  4. etiquettes : horizon, actifs (dont « nos actifs » : futures indices / or / petrole / devises), presence d une
     regle de trading ou d une predictibilite, nombre de citations ;
  5. page HTML autonome : recherche, filtres, tri, et pour chaque lien un statut et une note gardes dans le
     navigateur (exportables en CSV) ; les articles deja testes dans ce depot sont marques.
Seule la bibliotheque standard de Python est utilisee.
"""
from __future__ import annotations

import argparse
import csv
import html
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

OPENALEX = "https://api.openalex.org"
CROSSREF = "https://api.crossref.org"
UA = "FineShit-ssrn-intraday/1.0 (outil de recherche bibliographique)"

# Requetes : termes qui designent un horizon intraday ou plus court, ou un mecanisme qui s y joue.
MOTS_CLES = [
    "intraday", "intra-day", "high-frequency", "high frequency trading", "overnight returns", "overnight drift",
    "time-of-day", "time of day effect", "one-minute", "5-minute", "five-minute", "30-minute", "half-hour",
    "hourly returns", "opening range", "market open", "market close", "closing auction", "opening auction",
    "end-of-day", "last half hour", "first half hour", "market microstructure", "order flow", "order imbalance",
    "limit order book", "tick data", "day trading", "intraday momentum", "intraday reversal",
    "intraday seasonality", "intraday volatility", "intraday periodicity", "intraday liquidity", "fixing",
    "pre-announcement drift", "announcement window", "jump", "drift burst", "flash crash", "price impact",
    "liquidity provision", "VWAP", "trading hours", "night session", "after-hours", "pre-market",
    "futures intraday", "currency intraday", "gold intraday", "crude oil intraday", "E-mini",
]

HORIZONS = {
    "haute frequence": r"high[- ]frequency|milli ?seconds?|micro ?seconds?|nano ?seconds?|tick[- ]by[- ]tick|tick data|"
                       r"(limit )?order book|latency|co-?location",
    "intraday": r"intra[- ]?day|intra[- ]?daily|within[- ]the[- ]day|time[- ]of[- ](the[- ])?day|half[- ]hour|"
                r"\b\d+[- ]?min(ute)?s?\b|one[- ]minute|five[- ]minute|minute[- ](by|level|frequency)|hourly|"
                r"day[- ]trad|scalp",
    "nuit / seance": r"overnight|close[- ]to[- ]open|open[- ]to[- ]close|night[- ]session|non[- ]?trading hours|"
                     r"after[- ]hours|pre[- ]?market|trading[- ]hours",
    "ouverture / cloture": r"opening (range|auction|price|bell|hour|period)|market open(ing)?\b|closing (auction|price|bell|period)|"
                           r"market clos(e|ing)|end[- ]of[- ](the[- ])?day|last half[- ]hour|first half[- ]hour",
    "microstructure": r"microstructure|order flow|order imbalance|price impact|bid[- ]ask|quoted spread|effective spread|"
                      r"liquidity provi|market[- ]mak(er|ing)|flash crash|drift burst",
}
ANNONCES = r"announcement|fomc|macro(economic)? (news|release)|news release|fixing|\bfix(es)?\b"
ACTIFS = {
    "futures": r"\bfutures?\b",
    "indices actions": r"s\s?&\s?p\s?500|e-?mini|nasdaq|dow jones|stock index|index futures|\bspy\b|\bqqq\b|\bspx\b",
    "or": r"\bgold\b|precious metal",
    "petrole": r"crude|\boil\b|\bwti\b|\bbrent\b",
    "devises": r"foreign exchange|\bfx\b|currenc|exchange rates?\b|\beur ?/? ?usd\b|\busd ?/? ?jpy\b|\byen\b|sterling",
    "taux": r"treasur|\bbonds?\b|interest rate futures",
    "actions": r"\bstocks?\b|equit(y|ies)",
    "crypto": r"bitcoin|crypto",
    "options": r"\boptions?\b|0dte|zero[- ]days?[- ]to[- ]expir",
}
STRATEGIE = (r"trading (strateg|rule)|profitab|sharpe|abnormal returns?|excess returns?|return predictab|predict(s|ive|ability)|"
             r"anomal|backtest|momentum|reversal|drift|seasonal")

# Articles SSRN deja testes dans ce depot (numero SSRN -> resultat), pre-remplis dans la colonne statut.
DEJA_TESTES = {
    "4824172": "teste : zone de bruit, retenue sur NQ (S1), rejetee sur les autres actifs",
    "4729284": "teste : ORB 5 min Stocks in Play, candidate sur NQ, rejetee ailleurs",
    "4416622": "teste : ORB 2023, rejetee apres publication",
    "4631351": "teste : VWAP, rejetee",
    "2730304": "teste : retournement croise (Della Corte et al.), rejete",
    "3560269": "teste : derive de nuit (BLW), rejetee",
    "3596245": "teste : ouverture europeenne (Bondarenko & Muravyev), rejetee",
    "2842535": "teste : drift burst (Christensen et al.), rejete (meilleur YM 0,48)",
    "3925725": "non teste : gamma des teneurs de marche (donnees options absentes)",
    "7290621": "lu : hors echantillon de la zone de bruit (mise en garde S1)",
    "4934614": "teste : effet du dejeuner, rejete",
    "1716841": "teste : roll GSCI sur CL, rejete",
    "1695596": "lu : VPIN (filtre de volatilite)",
    "3286745": "teste : pre-FOMC filtre par la volatilite, rejete",
}


# =============================================================================
#  Acces aux API
# =============================================================================
def get_json(url: str, essais: int = 5) -> dict:
    for k in range(essais):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=60) as rep:
                return json.loads(rep.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as ex:
            if k == essais - 1:
                raise RuntimeError(f"echec de {url[:120]}... : {ex}") from ex
            time.sleep(2 ** k)
    return {}


def _q(d: dict) -> str:
    return urllib.parse.urlencode({k: v for k, v in d.items() if v is not None}, safe=":,|*\"")


def openalex_sources(get=get_json, mailto=None) -> list[str]:
    """Identifiants OpenAlex des sources SSRN (« SSRN Electronic Journal » et assimilees)."""
    r = get(f"{OPENALEX}/sources?{_q(dict(search='SSRN', per_page=50, mailto=mailto))}")
    ids = [s["id"].rsplit("/", 1)[-1] for s in r.get("results", []) if "ssrn" in (s.get("display_name") or "").lower()]
    if not ids:
        raise RuntimeError("source SSRN introuvable dans OpenAlex")
    return ids


def _resume(inv: dict | None) -> str:
    """OpenAlex donne le resume en index inverse (mot -> positions) : on le remet dans l ordre."""
    if not inv:
        return ""
    pos = sorted((p, w) for w, ps in inv.items() for p in ps)
    return " ".join(w for _, w in pos)


def openalex_mot(mot: str, sources: list[str], get=get_json, mailto=None, log=print) -> list[dict]:
    terme = f'"{mot}"' if " " in mot or "-" in mot else mot
    filtre = f"primary_location.source.id:{'|'.join(sources)},title_and_abstract.search:{terme}"
    champs = "id,doi,title,publication_year,publication_date,abstract_inverted_index,authorships,cited_by_count"
    out, curseur = [], "*"
    while curseur:
        r = get(f"{OPENALEX}/works?{_q(dict(filter=filtre, per_page=200, cursor=curseur, select=champs, mailto=mailto))}")
        for w in r.get("results", []):
            out.append(dict(doi=(w.get("doi") or "").lower().replace("https://doi.org/", ""), titre=w.get("title") or "",
                            resume=_resume(w.get("abstract_inverted_index")), annee=w.get("publication_year"),
                            date=w.get("publication_date") or "", citations=w.get("cited_by_count") or 0,
                            auteurs=", ".join((a.get("author") or {}).get("display_name", "") for a in w.get("authorships") or []),
                            openalex=w.get("id", ""), source="OpenAlex"))
        curseur = (r.get("meta") or {}).get("next_cursor")
        if not r.get("results"):
            break
    log(f"  OpenAlex « {mot} » : {len(out)}")
    return out


def crossref_mot(mot: str, get=get_json, mailto=None, maxi: int = 3000, log=print) -> list[dict]:
    champs = "DOI,title,abstract,author,issued,is-referenced-by-count"
    out, curseur = [], "*"
    while curseur and len(out) < maxi:
        r = get(f"{CROSSREF}/works?{_q({'filter': 'prefix:10.2139', 'query.bibliographic': mot, 'rows': 1000, 'cursor': curseur, 'select': champs, 'mailto': mailto})}")
        msg = r.get("message") or {}
        items = msg.get("items") or []
        for w in items:
            dp = ((w.get("issued") or {}).get("date-parts") or [[None]])[0]
            out.append(dict(doi=(w.get("DOI") or "").lower(), titre=" ".join(w.get("title") or []),
                            resume=re.sub(r"<[^>]+>", " ", w.get("abstract") or ""), annee=dp[0] if dp else None,
                            date="-".join(f"{x:02d}" if i else str(x) for i, x in enumerate(dp) if x) if dp and dp[0] else "",
                            citations=w.get("is-referenced-by-count") or 0,
                            auteurs=", ".join(" ".join(filter(None, [a.get("given"), a.get("family")])) for a in w.get("author") or []),
                            openalex="", source="Crossref"))
        curseur = msg.get("next-cursor") if items else None
    log(f"  Crossref « {mot} » : {len(out)}")
    return out


# =============================================================================
#  Fusion, filtre et etiquettes
# =============================================================================
def ssrn_id(doi: str) -> str | None:
    m = re.search(r"10\.2139/ssrn\.(\d+)", doi or "")
    return m.group(1) if m else None


def classer(rec: dict) -> dict | None:
    """Etiquettes d un article ; None s il n est pas au moins intraday."""
    texte = " ".join([rec["titre"], rec["resume"]] + rec.get("_textes", [])).lower()
    hz = [k for k, rx in HORIZONS.items() if re.search(rx, texte)]
    if not hz:
        return None
    act = [k for k, rx in ACTIFS.items() if re.search(rx, texte)]
    nos = ("futures" in act and any(a in act for a in ("indices actions", "or", "petrole", "devises"))) or \
          bool(re.search(r"e-?mini|\bgold\b|crude|\bwti\b|foreign exchange|\bfx\b|currency futures", texte))
    strat = bool(re.search(STRATEGIE, texte))
    ann = bool(re.search(ANNONCES, texte))
    mots = sorted({m.group(0) for rx in HORIZONS.values() for m in re.finditer(rx, texte)})[:8]
    sid = ssrn_id(rec["doi"])
    return dict(rec, ssrn_id=sid, lien=f"https://papers.ssrn.com/sol3/papers.cfm?abstract_id={sid}" if sid else f"https://doi.org/{rec['doi']}",
                horizon=" | ".join(hz), actifs=" | ".join(act), nos_actifs=nos, strategie=strat, annonces=ann,
                score=len(hz) + 2 * strat + 2 * nos + ann, mots_trouves=", ".join(mots),
                statut=DEJA_TESTES.get(sid or "", ""))


def fusionner(listes) -> list[dict]:
    par = {}
    for rec in (r for l in listes for r in l):
        cle = ssrn_id(rec["doi"]) or rec["doi"] or rec["titre"].lower()
        if not cle:
            continue
        old = par.get(cle)
        if old is None:
            par[cle] = dict(rec, _textes=[rec["titre"], rec["resume"]])
        else:                                       # garder le resume le plus long et le plus de citations ;
            old["_textes"] += [rec["titre"], rec["resume"]]   # le classement lit tous les titres et resumes
            if len(rec["resume"]) > len(old["resume"]):
                old["resume"] = rec["resume"]
            old["citations"] = max(old["citations"] or 0, rec["citations"] or 0)
            for k in ("titre", "auteurs", "annee", "date", "openalex"):
                old[k] = old[k] or rec[k]
            if rec["source"] not in old["source"]:
                old["source"] += " + " + rec["source"]
    return list(par.values())


def catalogue(mots=MOTS_CLES, get=get_json, mailto=None, crossref=True, maxi_crossref=3000, log=print) -> list[dict]:
    listes = []
    try:
        src = openalex_sources(get, mailto)
        log(f"OpenAlex : sources SSRN {src}")
        for mot in mots:
            listes.append(openalex_mot(mot, src, get, mailto, log))
    except RuntimeError as ex:
        log(f"OpenAlex indisponible : {ex}")
    if crossref:
        for mot in mots:
            try:
                listes.append(crossref_mot(mot, get, mailto, maxi_crossref, log))
            except RuntimeError as ex:
                log(f"Crossref indisponible pour « {mot} » : {ex}")
    recs = [c for c in (classer(r) for r in fusionner(listes)) if c is not None]
    recs.sort(key=lambda r: (-r["score"], -(r["citations"] or 0)))
    log(f"{len(recs)} articles au moins intraday (sur {sum(len(l) for l in listes)} reponses brutes)")
    return recs


# =============================================================================
#  Sorties
# =============================================================================
COLONNES = ["ssrn_id", "lien", "titre", "auteurs", "annee", "date", "citations", "horizon", "actifs", "nos_actifs",
            "strategie", "annonces", "score", "mots_trouves", "statut", "doi", "source", "resume"]


def ecrire_csv(recs: list[dict], chemin: str):
    with open(chemin, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=COLONNES + ["note"], extrasaction="ignore")
        w.writeheader()
        for r in recs:
            w.writerow(dict(r, note=""))


PAGE = """<!doctype html>
<html lang="fr"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>SSRN intraday</title>
<style>
:root{--fond:#f7f7f5;--carte:#fff;--texte:#1d1d1b;--doux:#6b6b66;--ligne:#e3e2dd;--accent:#2457c5;--ok:#1d7a46;--ko:#b3412c}
@media (prefers-color-scheme:dark){:root{--fond:#161615;--carte:#1f1f1d;--texte:#ecebe6;--doux:#a3a29b;--ligne:#33322e;--accent:#7aa2ff;--ok:#5fc48a;--ko:#ff8a73}}
*{box-sizing:border-box}body{margin:0;background:var(--fond);color:var(--texte);font:14px/1.45 system-ui,-apple-system,Segoe UI,sans-serif}
header{padding:16px;border-bottom:1px solid var(--ligne);background:var(--carte);position:sticky;top:0;z-index:2}
h1{font-size:18px;margin:0 0 8px}.outils{display:flex;flex-wrap:wrap;gap:8px;align-items:center}
input,select,button,textarea{font:inherit;color:inherit;background:var(--fond);border:1px solid var(--ligne);border-radius:6px;padding:5px 8px}
button{cursor:pointer}button:hover{border-color:var(--accent)}
.compte{color:var(--doux);margin-left:auto}main{padding:12px 16px}
.art{background:var(--carte);border:1px solid var(--ligne);border-radius:8px;padding:10px 12px;margin-bottom:8px}
.art h2{font-size:15px;margin:0 0 4px}.art h2 a{color:var(--accent);text-decoration:none}.art h2 a:hover{text-decoration:underline}
.meta{color:var(--doux);font-size:12.5px}.tags span{display:inline-block;font-size:11.5px;border:1px solid var(--ligne);border-radius:10px;padding:0 7px;margin:3px 4px 0 0}
.tags .nos{border-color:var(--ok);color:var(--ok)}.res{color:var(--doux);font-size:13px;margin-top:6px;display:none}.ouvert .res{display:block}
.note{display:flex;gap:8px;margin-top:8px;flex-wrap:wrap}.note textarea{flex:1;min-width:200px;height:34px}
details{margin:0}summary{cursor:pointer;color:var(--doux);font-size:12.5px}
</style></head><body>
<header><h1>Articles SSRN au moins intraday <span class="meta">— genere le __DATE__, __N__ articles</span></h1>
<div class="outils">
<input id="q" type="search" placeholder="chercher (titre, resume, auteurs)" size="32">
<select id="hz"><option value="">tout horizon</option>__HZ__</select>
<select id="ac"><option value="">tout actif</option>__AC__</select>
<select id="st"><option value="">tout statut</option><option>a lire</option><option>a tester</option><option>teste</option><option>rejete</option><option>retenu</option><option value="__vide">sans statut</option></select>
<label><input type="checkbox" id="nos"> nos actifs</label>
<label><input type="checkbox" id="strat"> regle / predictibilite</label>
<input id="an" type="number" placeholder="depuis l annee" style="width:120px">
<select id="tri"><option value="score">tri : pertinence</option><option value="annee">tri : plus recents</option><option value="citations">tri : plus cites</option></select>
<button id="exp">exporter mes notes (CSV)</button><span class="compte" id="compte"></span></div></header>
<main id="liste"></main>
<script>
const DATA = __DATA__;
const CLE = "ssrn_intraday_notes_v1";
let notes = {}; try { notes = JSON.parse(localStorage.getItem(CLE) || "{}"); } catch (e) {}
const sauver = () => { try { localStorage.setItem(CLE, JSON.stringify(notes)); } catch (e) {} };
const $ = (s) => document.querySelector(s);
const cle = (r) => r.ssrn_id || r.doi;
const statut = (r) => (notes[cle(r)] || {}).statut || (r.statut ? (r.statut.startsWith("teste") ? (r.statut.includes("retenue") ? "retenu" : "teste") : "a lire") : "");
const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));
function rendre() {
  const q = $("#q").value.toLowerCase(), hz = $("#hz").value, ac = $("#ac").value, st = $("#st").value, an = +$("#an").value || 0;
  let l = DATA.filter((r) => (!q || (r.titre + " " + r.resume + " " + r.auteurs).toLowerCase().includes(q)) && (!hz || r.horizon.includes(hz)) &&
    (!ac || r.actifs.includes(ac)) && (!$("#nos").checked || r.nos_actifs) && (!$("#strat").checked || r.strategie) && (!an || (r.annee || 0) >= an) &&
    (!st || (st === "__vide" ? !statut(r) : statut(r) === st)));
  const t = $("#tri").value; l.sort((a, b) => (b[t] || 0) - (a[t] || 0));
  $("#compte").textContent = l.length + " / " + DATA.length;
  $("#liste").innerHTML = l.slice(0, 1500).map((r) => { const n = notes[cle(r)] || {}; return `<div class="art" data-k="${esc(cle(r))}">
    <h2><a href="${esc(r.lien)}" target="_blank" rel="noopener">${esc(r.titre)}</a></h2>
    <div class="meta">${esc(r.auteurs)} · ${r.annee || "?"} · ${r.citations || 0} citations · SSRN ${esc(r.ssrn_id || "-")}${r.statut ? " · " + esc(r.statut) : ""}</div>
    <div class="tags">${r.horizon.split(" | ").map((x) => `<span>${esc(x)}</span>`).join("")}${r.actifs ? r.actifs.split(" | ").map((x) => `<span>${esc(x)}</span>`).join("") : ""}${r.nos_actifs ? '<span class="nos">nos actifs</span>' : ""}${r.strategie ? "<span>regle / predictibilite</span>" : ""}</div>
    <details><summary>resume</summary><div class="meta">${esc(r.resume || "(pas de resume dans l index)")}</div></details>
    <div class="note"><select class="s"><option value="">statut…</option>${["a lire","a tester","teste","rejete","retenu"].map((o) => `<option ${statut(r) === o ? "selected" : ""}>${o}</option>`).join("")}</select>
    <textarea class="n" placeholder="ma note">${esc(n.note || "")}</textarea></div></div>`; }).join("") +
    (l.length > 1500 ? `<p class="meta">${l.length - 1500} autres : affiner les filtres.</p>` : "");
}
$("#liste").addEventListener("change", (e) => { const d = e.target.closest(".art"); if (!d) return; const k = d.dataset.k;
  notes[k] = notes[k] || {}; if (e.target.classList.contains("s")) notes[k].statut = e.target.value; sauver(); });
$("#liste").addEventListener("input", (e) => { if (!e.target.classList.contains("n")) return; const k = e.target.closest(".art").dataset.k;
  notes[k] = notes[k] || {}; notes[k].note = e.target.value; sauver(); });
["#q","#hz","#ac","#st","#nos","#strat","#an","#tri"].forEach((s) => $(s).addEventListener("input", rendre));
$("#exp").addEventListener("click", () => {
  const lignes = [["ssrn_id","lien","titre","annee","statut","note"]].concat(DATA.filter((r) => statut(r) || (notes[cle(r)] || {}).note)
    .map((r) => [r.ssrn_id || "", r.lien, r.titre, r.annee || "", statut(r), (notes[cle(r)] || {}).note || ""]));
  const csv = lignes.map((l) => l.map((x) => '"' + String(x).replace(/"/g, '""') + '"').join(";")).join("\\n");
  const a = document.createElement("a"); a.href = URL.createObjectURL(new Blob(["\\ufeff" + csv], {type: "text/csv"})); a.download = "mes_notes_ssrn.csv"; a.click();
});
rendre();
</script></body></html>"""


def ecrire_html(recs: list[dict], chemin: str):
    champs = ["ssrn_id", "lien", "titre", "auteurs", "annee", "citations", "horizon", "actifs", "nos_actifs", "strategie",
              "score", "statut", "doi", "resume"]
    data = json.dumps([{k: r.get(k) for k in champs} for r in recs], ensure_ascii=False).replace("</", "<\\/")
    opt = lambda xs: "".join(f"<option>{html.escape(x)}</option>" for x in xs)
    page = (PAGE.replace("__DATA__", data).replace("__N__", str(len(recs))).replace("__DATE__", time.strftime("%Y-%m-%d"))
            .replace("__HZ__", opt(HORIZONS)).replace("__AC__", opt(ACTIFS)))
    with open(chemin, "w", encoding="utf-8") as f:
        f.write(page)


def main(argv=None):
    ap = argparse.ArgumentParser(description="Catalogue des articles SSRN au moins intraday (OpenAlex + Crossref).")
    ap.add_argument("--sortie", default="ssrn_intraday", help="prefixe des fichiers produits (.csv et .html)")
    ap.add_argument("--mailto", default=None, help="adresse transmise aux API (file prioritaire), facultatif")
    ap.add_argument("--sans-crossref", action="store_true", help="OpenAlex seulement (plus rapide)")
    ap.add_argument("--maxi-crossref", type=int, default=3000, help="reponses Crossref lues par mot-cle (classees par pertinence)")
    a = ap.parse_args(argv)
    recs = catalogue(mailto=a.mailto, crossref=not a.sans_crossref, maxi_crossref=a.maxi_crossref)
    ecrire_csv(recs, a.sortie + ".csv")
    ecrire_html(recs, a.sortie + ".html")
    print(f"ecrit : {a.sortie}.csv et {a.sortie}.html ({len(recs)} articles)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
