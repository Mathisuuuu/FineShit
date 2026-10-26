"""Tests des fiches 4B, 7, 8, 9, 10, 11, de la couche LLM / actualites, des futures et des profils.

Aucun appel reseau : les reponses LLM et FinBERT sont pre-remplies dans des caches temporaires
(memes cles que le C#), et http_request est remplace par une fonction qui echoue si elle est appelee."""
import json
from datetime import datetime, timedelta
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from nexus import data as D
from nexus import futures as F
from nexus import llm as L
from nexus import news as N
from nexus.profiles import profile_params
from nexus.strategies import get
from nexus.strategies.s04b_crypto import taker_sell_share_from_trades
from nexus.strategies.s08_judge import Nexus08LlmJudgeVeto
from nexus.strategies.s11_wheel import choose_expiry, third_friday

P = L.Prompts
HEADS = ("Apple unveils record iPhone sales", "Regulators approve Apple acquisition deal")


@pytest.fixture(autouse=True)
def isolation(tmp_path, monkeypatch):
    monkeypatch.setenv("NEXUS_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setattr(L, "NT_NEXUS_DIR", str(tmp_path / "nt"))
    monkeypatch.setattr(L, "keys_files", lambda: [])
    for k in ("ANTHROPIC_API_KEY", "DEEPSEEK_API_KEY", "GEMINI_API_KEY", "NEXUS_DATA_DELAY_MINUTES"):
        monkeypatch.delenv(k, raising=False)

    def no_network(*a, **k):
        raise AssertionError("appel reseau interdit dans les tests")
    monkeypatch.setattr(L, "http_request", no_network)
    L.LlmCache._instances.clear()
    yield


# =============================================================================
#  Texte, hachage, consignes
# =============================================================================
def test_hachage_et_cle_de_cache_compatibles_csharp():
    assert N.hash10("") == "da39a3ee5e6b4b0d3255"                    # SHA-1("")[:10 octets]
    assert N.normalize("Apple's Q3: +5%!") == "apple s q3 5"
    cfg = L.LlmConfig("Claude", "claude-opus-5-5")
    assert L.cache_key(cfg, "sys", "user", "nx-v1") == "Claude:claude-opus-5-5|nx-v1|" + N.hash10("sys") + "|" + N.hash10("user")
    assert L.FinBert.key_of("Apple beats!") == N.hash10("finbert|apple beats")


def test_analyse_des_reponses():
    assert P.parse_label3("GOOD\nbecause") == 1
    assert P.parse_label3("**Bad**") == -1
    assert P.parse_label3("No effect.") == 0
    assert P.parse_label3("NO") == -1
    assert P.parse_label3("I think this is GOOD news") == 1
    assert P.parse_label3("???") is None
    assert P.parse_score5("+2\nstrong") == 2
    assert P.parse_score5("-1") == -1
    assert P.parse_score5("Score: 0 because") == 0
    assert P.parse_score5("5") is None
    assert P.parse_judge('Voici : {"veto": true, "reason": "SEC probe", "confidence": 0.9}') == (True, "SEC probe", 0.9)
    assert P.parse_judge('```json\n{"veto": false}\n```') == (False, "", 0.0)
    assert P.parse_judge("pas de json") is None
    assert P.parse_risk('{"risk": 1.4, "reason": "x"}') == (1.0, "x")
    assert L.extract_first_object('a {b} {"x": "}"}') == {"x": "}"}


def test_consignes_identiques_au_csharp():
    u = P.headline3("AAPL", "Apple", "Hello", "")
    assert u == ("Is this headline good, bad, or of no effect for the price of Apple (AAPL) in the short term?\n"
                 "Headline: \"Hello\"\nAnswer on the first line with exactly one word: GOOD, BAD or NONE.\n"
                 "On the second line, give one short sentence of justification.")
    j = P.judge_user("XYZ", "", "union", 21, pd.Timestamp("2024-05-02"), "",
                     [N.NewsItem(datetime(2024, 5, 1, 9, 30), "XYZ", "csv", "Probe opened")])
    assert "Candidate trade: BUY XYZ, source: union, expected holding period about 21 trading days.\nDecision date: 2024-05-02\n" in j
    assert "- 2024-05-01 09:30 | csv | Probe opened\n" in j and j.endswith('"confidence": number between 0 and 1}')
    r = P.risk_rank_user("XYZ", "", "union", pd.Timestamp("2024-05-02"), "", [])
    assert "Respond with strict JSON only, no prose" not in r and r.endswith('"reason": "one sentence"}')


def test_cache_llm_aller_retour(tmp_path):
    path = str(tmp_path / "c.tsv")
    c = L.LlmCache(path)
    c.put("k1", "GOOD\nexplication é")
    c.put("k1", "autre")                                              # premiere reponse conservee
    line = open(path, encoding="utf-8").read().strip()
    assert line.startswith("k1\t") and "\n" not in line
    assert L.LlmCache(path).get("k1") == "GOOD\nexplication é"


# =============================================================================
#  Actualites
# =============================================================================
def test_dedoublonnage_et_fenetre():
    st = N.NewsStore()
    t = datetime(2024, 1, 2, 12)
    assert st.add(N.NewsItem(t, "AAPL", "a", "Apple beats earnings expectations in Q4"))
    assert not st.add(N.NewsItem(t + timedelta(hours=2), "AAPL", "b", "Apple beats earnings expectations for Q4"))
    assert st.add(N.NewsItem(t + timedelta(hours=30), "AAPL", "b", "Apple beats earnings expectations for Q4"))
    assert not st.add(N.NewsItem(t + timedelta(hours=40), "aapl", "c", "Apple beats earnings expectations in Q4"))  # meme cle
    assert st.duplicates == 2
    got = st.get("AAPL", t, t + timedelta(hours=30), False)
    assert [x.published_utc for x in got] == [t + timedelta(hours=30)]                 # ]from ; to]
    st.add(N.NewsItem(t + timedelta(hours=31), "AAPL", "reddit:r/stocks", "Totally different rumor about the CEO"))
    assert len(st.get("AAPL", t, t + timedelta(days=2), False)) == 1
    assert len(st.get("AAPL", t, t + timedelta(days=2), True)) == 2


def test_csv_actualites_diese_et_commentaires(tmp_path):
    p = tmp_path / "news.csv"
    p.write_text("# commentaire\npublished_utc,symbol,source,headline,url\n"
                 "2024-01-02T12:00:00Z,AAPL,newsapi:x,Apple #1 in smartphones,http://a\n"
                 "date illisible,AAPL,x,Autre titre,\n", encoding="utf-8")
    st = N.NewsStore()
    n, msg = st.load_csv(str(p), ["AAPL"])
    assert n == 1 and "1 dates illisibles" in msg
    assert st.get("AAPL", datetime(2024, 1, 1), datetime(2024, 1, 3), False)[0].headline == "Apple #1 in smartphones"


def test_debut_de_seance_suivante():
    stock = SimpleNamespace(name="AAPL", holidays=set(), seven_days=False, asset_class="Action")
    assert N.next_session_begin_utc(stock, "2024-01-05") == datetime(2024, 1, 8, 14, 30)     # vendredi -> lundi 9:30 NY (EST)
    assert N.next_session_begin_utc(stock, "2024-07-01") == datetime(2024, 7, 2, 13, 30)     # ete (EDT)
    crypto = SimpleNamespace(name="BTCUSD", holidays=set(), seven_days=True, asset_class="Crypto")
    assert N.next_session_begin_utc(crypto, "2024-01-05") == datetime(2024, 1, 6)
    es = SimpleNamespace(name="ES", holidays=set(), seven_days=False, asset_class="Future")
    assert N.next_session_begin_utc(es, "2024-01-05") == datetime(2024, 1, 7, 23, 0)         # dimanche 17:00 Chicago


def test_fear_greed_sans_information_future(tmp_path):
    p = tmp_path / "fg.csv"
    p.write_text("date,value,label\n2024-01-01,20,Extreme Fear\n2024-01-03,70,Greed\n", encoding="utf-8")
    fg = N.FearGreed(str(p))
    assert fg.load_cache() == 2
    assert fg.get("2024-01-02") == (20, "Extreme Fear") and fg.get("2024-01-03") == (70, "Greed")
    assert fg.get("2023-12-31") is None


# =============================================================================
#  Fiches 7, 9, 10 (regles evenementielles)
# =============================================================================
def _prices(sym="AAPL"):
    idx = pd.bdate_range("2024-01-01", "2024-03-29")
    o = 100 + np.arange(len(idx)) * 0.1
    return {sym: pd.DataFrame({"open": o, "high": o + 1, "low": o - 1, "close": o + 0.05, "volume": 1e6}, index=idx)}


def _news(tmp_path, heads=HEADS, day="2024-02-06"):
    p = tmp_path / "news.csv"
    rows = [f"{day}T{12 + i}:00:00Z,AAPL,newsapi:x,{h}," for i, h in enumerate(heads)]
    p.write_text("published_utc,symbol,source,headline,url\n" + "\n".join(rows) + "\n", encoding="utf-8")
    return str(p)


def _common(tmp_path, cache):
    return dict(symbols="AAPL", news_file=_news(tmp_path), llm_cache_file=cache, use_circuit_breakers=False,
                fear_greed_download=False, earnings_file="")


def test_fiche7_entree_a_l_ouverture_et_detention_un_jour(tmp_path):
    cache = str(tmp_path / "llm.tsv")
    c = L.LlmCache.get_instance(cache)
    cfg = L.LlmConfig("Claude", "claude-opus-5-5")
    for h in HEADS:
        c.put(L.cache_key(cfg, P.HEADLINE_SYSTEM, P.headline3("AAPL", "Apple", h, ""), P.VERSION), "GOOD\nStrong.")
    st = get("07")(**_common(tmp_path, cache))
    data = _prices()
    res = st.run(data)
    assert st.api_refusals == 0 and st.headlines_sent == 0 and st.label_counts == [0, 0, 2]
    assert len(res.trades) == 1
    t = res.trades[0]
    # Titres publies le 6 fevrier avant 9:30 NY -> decision a la cloture du 5, achat a l ouverture du 6, sortie a l ouverture du 7.
    assert pd.Timestamp(t.entry_time).normalize() == pd.Timestamp("2024-02-06")
    assert t.entry_price == pytest.approx(data["AAPL"].loc["2024-02-06", "open"])
    assert pd.Timestamp(t.exit_time).normalize() == pd.Timestamp("2024-02-07")
    assert "fin de detention" in t.exit_reason


def test_fiche7_cache_absent_pas_d_appel_ni_de_trade(tmp_path):
    st = get("07")(**_common(tmp_path, str(tmp_path / "vide.tsv")))
    res = st.run(_prices())
    assert not res.trades and st.api_refusals == 2 and st.unscored_days == 1
    assert "api_calls_in_backtest=true" in res.report


def test_fiche7_mauvaise_nouvelle_bloque(tmp_path):
    cache = str(tmp_path / "llm.tsv")
    c = L.LlmCache.get_instance(cache)
    cfg = L.LlmConfig("Claude", "claude-opus-5-5")
    for h, a in zip(HEADS, ("GOOD", "BAD")):
        c.put(L.cache_key(cfg, P.HEADLINE_SYSTEM, P.headline3("AAPL", "Apple", h, ""), P.VERSION), a)
    res = get("07")(**_common(tmp_path, cache)).run(_prices())
    assert not res.trades                                              # moyenne 0 < 0.5


@pytest.mark.parametrize("answers,trades", [(("+2", "1", "2"), 1), (("+2", "-1", "2"), 0)])
def test_fiche9_consensus_et_desaccord(tmp_path, answers, trades):
    cache = str(tmp_path / "llm.tsv")
    c = L.LlmCache.get_instance(cache)
    models = [L.LlmConfig("Claude", "claude-opus-5-5"), L.LlmConfig("DeepSeek", "deepseek-chat"), L.LlmConfig("Gemini", "gemini-2.5-flash")]
    for h in HEADS:
        u = P.headline5("AAPL", "Apple", h, "")
        for cfg, a in zip(models, answers):
            c.put(L.cache_key(cfg, P.HEADLINE_SYSTEM, u, P.VERSION), a + "\nreason")
    st = get("09")(**_common(tmp_path, cache), use_finbert_prefilter=False)
    res = st.run(_prices())
    assert len(res.trades) == trades
    if trades:
        assert st.agree_items == 2
    else:
        assert st.disagree_items == 2 and st.ambiguous_days == 1


def test_fiche10_finbert_depuis_le_cache(tmp_path):
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir(exist_ok=True)
    rows = "".join(f"{L.FinBert.key_of(h)},0.900000,0.050000,0.050000\n" for h in HEADS)
    (cache_dir / "finbert_cache.csv").write_text("key,positive,negative,neutral\n" + rows, encoding="utf-8")
    st = get("10")(**_common(tmp_path, str(tmp_path / "llm.tsv")), finbert_mode="serveur", finbert_url="http://127.0.0.1:1/score")
    res = st.run(_prices())
    assert len(res.trades) == 1 and st.headlines_scored == 2 and st.non_neutral == 2


# =============================================================================
#  Fiche 8 : juge et trades fantomes
# =============================================================================
class _Juge(Nexus08LlmJudgeVeto):
    def call_llm(self, cfg, system, user, purpose):
        veto = "BUY AAA," in user
        return L.LlmResult(True, json.dumps({"veto": veto, "reason": "enquete ouverte", "confidence": 0.9}), from_cache=True)


def test_fiche8_veto_et_suivi_fantome():
    syms = ["AAA", "BBB", "CCC", "DDD", "EEE", "FFF", "SPY"]
    data = D.synthetic_universe(syms, "2012-01-02", "2016-12-30")
    st = _Juge(symbols=",".join(syms[:-1]), source="tsmom_fiche1", fear_greed_download=False, news_file="", earnings_file="")
    res = st.run(data)
    assert st.vetoes > 0 and st.judge_errors == 0
    assert not [t for t in res.trades if t.symbol == "AAA"]
    assert [t for t in res.trades if t.symbol != "AAA"]
    blocked = [s for s in st.shadows if s.vetoed]
    assert blocked and all(s.symbol == "AAA" for s in blocked) and any(s.done for s in blocked)
    assert "Trades fantomes" in res.report


# =============================================================================
#  Fiche 4B : flux taker et retournement 15 min
# =============================================================================
def test_part_vendeuse_transactions():
    df = pd.DataFrame({"time": ["2024-01-01 00:01", "2024-01-01 00:02", "2024-01-01 00:16"], "price": [100, 99, 99],
                       "quantity": [1, 3, 2], "is_buyer_maker": [False, True, True]})
    sh = taker_sell_share_from_trades(df, 15)
    assert sh[pd.Timestamp("2024-01-01 00:15")] == pytest.approx(0.75) and sh[pd.Timestamp("2024-01-01 00:30")] == 1.0
    tick = taker_sell_share_from_trades(df.drop(columns="is_buyer_maker"), 15)       # regle du tick
    assert tick[pd.Timestamp("2024-01-01 00:15")] == 1.0 and tick[pd.Timestamp("2024-01-01 00:30")] == 1.0


def _crypto_bars(n=300, shock=200):
    rng = np.random.default_rng(3)
    idx = pd.date_range("2024-01-01 00:15", periods=n, freq="15min")
    c = 30000 * np.exp(np.cumsum(0.001 * rng.standard_normal(n)))
    c[shock:] *= 0.98                                                  # choc vendeur de -2 %
    c[shock + 2:] = c[shock] * 1.02                                    # rebond au-dessus du milieu
    o = np.r_[c[0], c[:-1]]
    o[shock + 1] = c[shock] * 0.999                                    # ouverture sous la cloture du choc : limite maker remplie
    hi, lo = np.maximum(o, c) * 1.0005, np.minimum(o, c) * 0.9995
    vol = np.full(n, 100.0)
    tbv = vol * 0.5
    tbv[shock] = 10.0                                                  # 90 % de flux vendeur
    return {"BTCUSD": pd.DataFrame({"open": o, "high": hi, "low": lo, "close": c, "volume": vol, "taker_buy_volume": tbv}, index=idx)}


def test_fiche4b_choc_entree_maker_sortie_au_milieu():
    st = get("04B")(symbols="BTCUSD", mode="strategie", use_circuit_breakers=False)
    data = _crypto_bars()
    res = st.run(data)
    assert st.shock_count == 1 and st.entries_submitted == 1
    assert len(res.trades) == 1
    t = res.trades[0]
    assert t.entry_price == pytest.approx(data["BTCUSD"]["open"].iloc[201], rel=1e-6)
    assert "milieu" in t.exit_reason and t.gross_pnl > 0
    assert t.max_qty * 0.0001 == pytest.approx(0.0001 * t.max_qty) and t.max_qty > 100      # quantites fractionnaires (crypto_unit)


def test_fiche4b_mode_filtre_mesure_l_avantage(tmp_path):
    out = tmp_path / "chocs.csv"
    st = get("04B")(symbols="BTCUSD", use_circuit_breakers=False, shocks_file=str(out))
    res = st.run(_crypto_bars())
    assert not res.trades and st.shock_count == 1 and len(st.fwd_returns) == 1 and st.fwd_mid_touch == [True]
    assert "Avantage a terme des chocs" in res.report and out.exists()


# =============================================================================
#  Fiche 11 : roue d options synthetique
# =============================================================================
def test_echeances():
    assert third_friday(2024, 3) == pd.Timestamp("2024-03-15")
    assert choose_expiry("2024-02-01", 30, 45) == pd.Timestamp("2024-03-15")
    assert choose_expiry("2024-02-20", 30, 45).weekday() == 4


def test_fiche11_comptabilite_coherente():
    data = D.synthetic_universe(["SPY", "F", "T"], "2012-01-02", "2017-12-29")
    st = get("11")(symbols="SPY,F,T", use_circuit_breakers=False)
    res = st.run(data)
    opts = [t for t in res.trades if t.asset_class == "Option"]
    assert len(opts) > 20
    assert sum(w.counters["assignments"] for w in st.wheels.values()) > 0
    # Tresorerie = PnL des trades fermes + primes encaissees des options ouvertes - base des actions detenues.
    fee = st.p.fee_per_contract
    open_prem = sum(w.option.premium * 100 * w.option.contracts - fee * w.option.contracts for w in st.wheels.values() if w.option)
    held = sum(w.stock_mark * w.shares for w in st.wheels.values())
    cash = sum(w.cash for w in st.wheels.values())
    assert cash == pytest.approx(sum(t.net_pnl for t in res.trades) + open_prem - held, abs=1e-6)
    assert "PIRE PERTE MENSUELLE" in res.report


# =============================================================================
#  Futures, roulements, profils
# =============================================================================
def _es_minutes():
    days = pd.date_range("2024-02-20", "2024-04-10", freq="D", tz="UTC")
    idx = pd.DatetimeIndex([d + pd.Timedelta(minutes=m) for d in days for m in range(1440) if not (21 * 60 <= m < 22 * 60)])
    rng = np.random.default_rng(5)
    c = 5000 * np.exp(np.cumsum(0.0001 * rng.standard_normal(len(idx))))
    roll = idx.get_loc(pd.Timestamp("2024-03-14", tz="UTC"))
    o = np.r_[c[0], c[:-1]]
    o[roll:] *= 1.01                                                   # changement d echeance : +1 % entre deux barres
    c[roll:] *= 1.01
    return pd.DataFrame({"open": o, "high": np.maximum(o, c), "low": np.minimum(o, c), "close": c, "volume": 10.0}, index=idx), roll


def test_roulement_heuristique_et_ajustement():
    df, roll = _es_minutes()
    r = F.detect_rolls(df, "ES")
    assert len(r) == 1 and r["time"].iloc[0] == pd.Timestamp("2024-03-14", tz="UTC") and r["methode"].iloc[0] == "heuristique"
    adj = F.back_adjust(df, r)
    assert adj["open"].iloc[roll] / adj["close"].iloc[roll - 1] == pytest.approx(1.0, abs=1e-12)        # saut retire
    assert adj["close"].iloc[-1] == df["close"].iloc[-1]                                                   # prix recents inchanges
    ident = df.assign(instrument_id=np.where(np.arange(len(df)) < roll, "ESH4", "ESM4"))
    r2 = F.detect_rolls(ident, "ES")
    assert len(r2) == 1 and r2["methode"].iloc[0] == "identifiant"


def test_jour_de_seance_cme():
    idx = pd.DatetimeIndex(["2024-03-13 21:30", "2024-03-13 22:30"]).tz_localize("UTC")
    td = F.trading_days(idx, F.contract_of("ES"))
    assert list(td) == [pd.Timestamp("2024-03-13"), pd.Timestamp("2024-03-14")]


def test_profils_et_classification():
    assert profile_params("futures", "01")["barometer"] == "ES"
    assert profile_params("futures", "07") is None and profile_params(None, "07") == {}
    assert D.classify("ES", micro=True).point_value == 5 and D.classify("ES").asset_class == "Future"
    assert D.classify("ES", is_future=False).asset_class == "Action"
    st = get("04B")(symbols="BTCUSD")
    st._prepare(_crypto_bars(120, shock=60))
    assert st.sym("BTCUSD").inst.point_value == pytest.approx(0.0001)


def test_fiche13_veto_claude_depuis_le_cache_et_repli(tmp_path):
    macro = tmp_path / "macro.csv"
    macro.write_text("datetime_utc,currency,impact,title\n2016-03-16T21:30:00Z,USD,High,FOMC statement\n", encoding="utf-8")
    data = D.synthetic_universe(["EURUSD"], "2015-01-01", "2016-06-30")
    cache = str(tmp_path / "llm.tsv")

    def prepared(mode):
        st = get("13")(symbols="EURUSD", veto_mode=mode, macro_file=str(macro), llm_cache_file=cache)
        st._prepare(data)
        st.on_data_loaded()
        s = st.sym("EURUSD")
        s.hist.count = s.hist.n
        s.hist.count = s.hist.index_of(pd.Timestamp("2016-03-16")) + 1
        return st, s

    st, s = prepared("claude")
    ev = st.macro.near(st._currencies_of(s), datetime(2016, 3, 16, 21), 0, 60, 3)
    assert len(ev) == 1 and str(ev[0]) == "2016-03-16 21:30Z USD [High] FOMC statement"
    veto, why = st._macro_veto(s, s.hist, 1)                       # pas de reponse en cache -> repli sur la regle
    assert veto and why.startswith("repli regle") and st.llm_refusals == 1
    user = P.macro_user("EURUSD", 1, datetime(2016, 3, 16, 21), ev)
    L.LlmCache.get_instance(cache).put(L.cache_key(st.claude, P.MACRO_SYSTEM, user, P.VERSION),
                                       '{"veto": false, "reason": "minor", "confidence": 0.2}')
    assert st._macro_veto(s, s.hist, 1) == (False, None)            # Claude laisse passer
    st2, s2 = prepared("regles")
    assert st2._macro_veto(s2, s2.hist, 1)[0]
