"""Outil de catalogue SSRN : requetes OpenAlex et Crossref simulees, fusion, filtre « au moins intraday », sorties."""
import csv
import importlib.util
import json
import os

spec = importlib.util.spec_from_file_location("ssrn_intraday", os.path.join(os.path.dirname(__file__), "..", "outils", "ssrn_intraday.py"))
S = importlib.util.module_from_spec(spec)
spec.loader.exec_module(S)


def _inv(texte):
    inv = {}
    for i, w in enumerate(texte.split()):
        inv.setdefault(w, []).append(i)
    return inv


def faux_get(url):
    if "/sources?" in url:
        return {"results": [{"id": "https://openalex.org/S111", "display_name": "SSRN Electronic Journal"},
                            {"id": "https://openalex.org/S222", "display_name": "Journal of Finance"}]}
    if "api.openalex.org/works" in url:
        assert "S111" in url and "S222" not in url
        if "cursor=%2A" in url or "cursor=*" in url:
            return {"meta": {"next_cursor": "p2"}, "results": [
                {"id": "W1", "doi": "https://doi.org/10.2139/ssrn.4824172", "title": "Beat the Market: An Effective Intraday Momentum Strategy",
                 "publication_year": 2024, "publication_date": "2024-05-20", "cited_by_count": 12,
                 "abstract_inverted_index": _inv("We document intraday momentum in SPY and E-mini futures with a Sharpe ratio of 1.33"),
                 "authorships": [{"author": {"display_name": "Carlo Zarattini"}}]},
                {"id": "W2", "doi": "https://doi.org/10.2139/ssrn.999", "title": "Corporate governance and board size",
                 "publication_year": 2019, "cited_by_count": 50, "abstract_inverted_index": _inv("Boards matter for firm value"),
                 "authorships": []}]}
        return {"meta": {"next_cursor": None}, "results": []}
    if "api.crossref.org/works" in url:
        if "cursor=%2A" in url or "cursor=*" in url:
            return {"message": {"next-cursor": "c2", "items": [
                {"DOI": "10.2139/ssrn.4824172", "title": ["Beat the Market"], "abstract": "<jats:p>Intraday momentum, longer abstract with more words about the noise area and futures.</jats:p>",
                 "issued": {"date-parts": [[2024, 5, 20]]}, "is-referenced-by-count": 15, "author": [{"given": "Carlo", "family": "Zarattini"}]},
                {"DOI": "10.2139/ssrn.555", "title": ["Gold returns around the overnight session"], "issued": {"date-parts": [[2018]]},
                 "is-referenced-by-count": 3, "author": []}]}}
        return {"message": {"next-cursor": "c3", "items": []}}
    raise AssertionError(url)


def test_catalogue_fusion_filtre_et_etiquettes(tmp_path):
    recs = S.catalogue(mots=["intraday"], get=faux_get, log=lambda *a: None)
    ids = {r["ssrn_id"]: r for r in recs}
    assert set(ids) == {"4824172", "555"}                     # l article de gouvernance n est pas intraday
    z = ids["4824172"]
    assert z["lien"] == "https://papers.ssrn.com/sol3/papers.cfm?abstract_id=4824172"
    assert z["citations"] == 15 and "noise area" in z["resume"] and z["source"] == "OpenAlex + Crossref"
    assert "intraday" in z["horizon"] and z["nos_actifs"] and z["strategie"] and z["statut"].startswith("teste")
    assert "nuit / seance" in ids["555"]["horizon"] and "or" in ids["555"]["actifs"]
    S.ecrire_csv(recs, str(tmp_path / "c.csv"))
    S.ecrire_html(recs, str(tmp_path / "c.html"))
    lignes = list(csv.DictReader(open(tmp_path / "c.csv", encoding="utf-8-sig")))
    assert len(lignes) == 2 and "note" in lignes[0]
    page = open(tmp_path / "c.html", encoding="utf-8").read()
    data = json.loads(page.split("const DATA = ")[1].split(";\nconst CLE")[0])
    assert len(data) == 2 and "</script" not in page.split("const DATA = ")[1].split(";\nconst CLE")[0]


def test_resume_inverse_et_identifiant():
    assert S._resume({"b": [1], "a": [0], "c": [2]}) == "a b c"
    assert S.ssrn_id("10.2139/ssrn.123456") == "123456" and S.ssrn_id("10.1111/jofi.1") is None
