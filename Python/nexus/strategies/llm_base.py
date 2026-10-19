"""Socles des fiches qui utilisent des actualites et des LLM (port de Strategies/NexusLlmStrategyBase.cs).

NexusLlmStrategy (fiches 7, 8, 9, 10)
  - LLM principal (Claude par defaut) ; cles API : parametre, variable d environnement ou Python/keys.txt
  - cache disque des reponses (format et cles du C#) : un backtest deja paye se rejoue gratuitement
  - appels API en backtest DESACTIVES par defaut (seules les reponses en cache servent) ;
    api_calls_in_backtest=True les autorise, dans la limite de max_api_calls_per_run
  - appels paralleles (max_parallel_calls), journal des couts (.cache/ai_costs.csv) rapporte au PnL
  - stock d actualites (Data/news.csv + news_live.csv alimente par "python -m nexus actualites"),
    dedoublonnage, Fear & Greed crypto, calendrier des resultats, FinBERT (serveur ou local)

NewsEventStrategy (fiches 7, 9, 10) - regles communes de la fiche 7 :
  - horodatage : un titre publie avant l ouverture est trade a l ouverture du jour ; apres, a l ouverture
    du lendemain. La fenetre d un jour de decision est ]ouverture precedente - marge ; ouverture suivante - marge],
    marge = news_cutoff_minutes + data_delay_minutes
  - agregation : moyenne des scores du jour par symbole
  - entree long : score >= +0.5 avec au moins 2 titres distincts ; score <= -0.5 : sortie / entree interdite
  - detention : 1 jour de bourse (ouverture -> ouverture suivante)
  - Reddit separe du flux d actualites et exclu du score par defaut

Le moteur Python n a pas de temps reel : la collecte (NewsAPI, Reddit, Fear & Greed, Alpha Vantage)
se fait avec la commande "python -m nexus actualites", qui alimente news_live.csv et pre-note les titres
(le cache est chaud au backtest suivant).
"""
from __future__ import annotations

import os
import threading
from concurrent.futures import ThreadPoolExecutor

import numpy as np

from .. import data as D
from .. import llm as L
from .. import mathx as M
from .. import news as N
from .. import signals as S
from ..engine import NexusStrategy, Sym, parse_map

COMPANY_NAMES = ("SPY=S&P 500;QQQ=Nasdaq 100;AAPL=Apple;MSFT=Microsoft;NVDA=Nvidia;AMZN=Amazon;GOOGL=Alphabet;META=Meta Platforms;"
                 "JPM=JPMorgan;JNJ=Johnson & Johnson;XOM=Exxon Mobil;UNH=UnitedHealth;V=Visa;PG=Procter & Gamble;HD=Home Depot;"
                 "TSLA=Tesla;BTCUSD=Bitcoin;ETHUSD=Ethereum;SOLUSD=Solana;XRPUSD=XRP")


class NexusLlmStrategy(NexusStrategy):
    DEFAULTS = dict(
        # --- 70. LLM principal ---
        llm_provider="claude",              # claude | deepseek | gemini | openai (compatible OpenAI)
        llm_model="claude-opus-5-5",        # claude-haiku-5-5 pour reduire le cout
        llm_api_key="",                     # vide = ANTHROPIC_API_KEY / DEEPSEEK_API_KEY / GEMINI_API_KEY ou keys.txt
        llm_endpoint="",
        llm_temperature=0.0,                # -1 = parametre omis
        llm_max_tokens=300,
        llm_timeout_sec=60,
        llm_price_in_per_mtok=0.0,          # $ / million de tokens (0 = tokens seulement dans le rapport)
        llm_price_out_per_mtok=0.0,
        api_calls_in_backtest=False,        # False = seules les reponses en cache sont utilisees
        max_api_calls_per_run=500,          # 0 = illimite
        max_parallel_calls=4,
        llm_cache_file="",                  # vide = Python/.cache/llm_cache.tsv (+ relecture du cache NinjaTrader)
        # --- 71. Actualites et donnees ---
        news_file="",                       # published_utc,symbol,source,headline,url (Data/news.csv)
        news_live_file="",                  # titres collectes par "python -m nexus actualites"
        company_names=COMPANY_NAMES,
        include_social_in_score=False,      # la fiche 7 recommande d exclure Reddit
        use_fear_greed=True,
        fear_greed_url=N.FearGreed.URL,
        fear_greed_download=True,           # telechargement si le cache est vide et l univers contient de la crypto
        news_cutoff_minutes=5,
        data_delay_minutes=0,               # 0 = variable d env. NEXUS_DATA_DELAY_MINUTES (SIP gratuit : 16)
        dedup_jaccard_pct=60.0,
        earnings_file="",
        finbert_url="http://127.0.0.1:8765/score",
        finbert_mode="auto",                # serveur | local | auto (serveur puis modele en memoire)
    )

    # ----- Points d extension -----
    def on_llm_data_loaded(self):
        pass

    # =========================================================================
    def on_data_loaded(self):
        p = self.p
        self._bg_lock = threading.Lock()
        self._bg_log: list[str] = []
        self._bg_once: set = set()
        self.api_calls = self.api_refusals = 0
        self.main_llm = self.build_config(p.llm_provider, p.llm_model, p.llm_api_key, p.llm_temperature, p.llm_max_tokens,
                                          p.llm_timeout_sec, p.llm_price_in_per_mtok, p.llm_price_out_per_mtok, p.llm_endpoint)
        self.llm_cache = L.LlmCache.get_instance(p.llm_cache_file or None)
        self.finbert = L.FinBert(p.finbert_url, mode=p.finbert_mode)
        self.companies = {k.upper(): v for k, v in parse_map(p.company_names).items()}
        L.AiLedger.reset(self.strategy_id)

        self.news = N.NewsStore(p.dedup_jaccard_pct / 100.0)
        names = [s.name for s in self.syms]
        if p.news_file:
            _, msg = self.news.load_csv(p.news_file, names)
            self.nx("Actualites : " + msg)
        else:
            self.nx("Actualites : aucun fichier (parametre news_file ou Data/news.csv)")
        if p.news_live_file and os.path.exists(p.news_live_file):
            _, msg = self.news.load_csv(p.news_live_file, names)
            self.nx("Actualites collectees : " + msg)

        self.fear_greed = N.FearGreed()
        self.fear_greed.load_cache([os.path.join(L.NT_NEXUS_DIR, "cache", "fear_greed.csv")])
        if p.use_fear_greed and any(s.asset_class == "Crypto" for s in self.syms) and self.fear_greed.count == 0 and p.fear_greed_download:
            ok, err = self.fear_greed.refresh(p.fear_greed_url)
            self.nx(f"Fear & Greed : {self.fear_greed.count} jours charges" if ok else f"Fear & Greed indisponible : {err}")

        self.earnings = D.Earnings(p.earnings_file if p.earnings_file and os.path.exists(p.earnings_file) else None)
        self.nx("Resultats : " + self.earnings.message)
        self.nx(f"LLM principal {self.main_llm.label} (cle {L.mask(self.main_llm.api_key)}) | appels en backtest : "
                f"{'OUI' if p.api_calls_in_backtest else 'non (cache seul)'} | budget {p.max_api_calls_per_run} appels | "
                f"cache {self.llm_cache.count} reponses")
        self.on_llm_data_loaded()

    # =========================================================================
    #  Appels LLM
    # =========================================================================
    @staticmethod
    def build_config(provider, model, key, temperature, max_tokens, timeout_sec, price_in, price_out, endpoint="") -> L.LlmConfig:
        return L.LlmConfig.build(provider, model, key, temperature, max_tokens, timeout_sec, price_in, price_out, endpoint)

    def api_allowed(self):
        p = self.p
        if not p.api_calls_in_backtest:
            return False, "appels API desactives en backtest (reponse absente du cache)"
        if p.max_api_calls_per_run > 0 and self.api_calls >= p.max_api_calls_per_run:
            return False, f"budget d appels atteint ({p.max_api_calls_per_run})"
        return True, None

    def call_llm(self, cfg: L.LlmConfig, system: str, user: str, purpose: str) -> L.LlmResult:
        """Cache d abord ; sinon appel reel si autorise. Utilisable depuis un fil secondaire."""
        hit = self.llm_cache.get(L.cache_key(cfg, system, user, L.Prompts.VERSION))
        if hit is not None:
            return L.LlmResult(True, hit, None, 200, from_cache=True)
        with self._bg_lock:
            ok, why = self.api_allowed()
            if not ok:
                self.api_refusals += 1
                return L.LlmResult(False, "", why)
            self.api_calls += 1
        r = L.complete(cfg, system, user, self.llm_cache, L.Prompts.VERSION)
        L.AiLedger.record(self.strategy_id, cfg, r, purpose)
        if not r.ok:
            self.bg_log_once(f"llm{cfg.provider}{r.status}", f"Erreur {cfg.label} : {r.error}")
        return r

    def run_all(self, jobs: list) -> list:
        """Execute des travaux en parallele (max_parallel_calls) ; None pour un travail en erreur."""
        if not jobs:
            return []
        out = [None] * len(jobs)

        def run(i):
            try:
                out[i] = jobs[i]()
            except Exception as ex:  # pragma: no cover
                self.bg_log_once("job" + type(ex).__name__, f"Erreur d appel : {ex}")

        if len(jobs) == 1 or self.p.max_parallel_calls <= 1:
            for i in range(len(jobs)):
                run(i)
        else:
            with ThreadPoolExecutor(max_workers=max(1, int(self.p.max_parallel_calls))) as ex:
                list(ex.map(run, range(len(jobs))))
        return out

    def bg_log_once(self, key: str, msg: str):
        with self._bg_lock:
            if key in self._bg_once:
                return
            self._bg_once.add(key)
            self._bg_log.append(msg)

    def flush_bg_log(self):
        with self._bg_lock:
            msgs, self._bg_log = self._bg_log, []
        for m in msgs:
            self.nx(m)

    # =========================================================================
    #  Contexte et donnees
    # =========================================================================
    def company_of(self, symbol: str) -> str:
        return self.companies.get(symbol.upper(), "")

    def context_for(self, s: Sym, day) -> str:
        """Contexte passe au LLM : indice Fear & Greed pour la crypto."""
        if s is None or s.asset_class != "Crypto" or not self.p.use_fear_greed:
            return ""
        v = self.fear_greed.get(day)
        return "" if v is None else f"Crypto Fear & Greed index on {L.pd_date(day)}: {v[0]} ({v[1]})"

    @property
    def effective_data_delay_minutes(self) -> int:
        if self.p.data_delay_minutes > 0:
            return int(self.p.data_delay_minutes)
        try:
            v = int(os.environ.get("NEXUS_DATA_DELAY_MINUTES", "0").strip())
            return v if 0 < v < 1440 else 0
        except ValueError:
            return 0

    def decision_cutoff_utc(self, s: Sym, day):
        """Heure limite (UTC) des titres utilisables pour l ouverture qui suit le jour de bourse `day`."""
        import datetime as _dt
        return N.next_session_begin_utc(s, day) - _dt.timedelta(minutes=self.p.news_cutoff_minutes + self.effective_data_delay_minutes)

    def recent_headlines(self, s: Sym, day, days: int) -> list:
        """Titres des n derniers jours avant le moment de decision (fiche 8)."""
        import datetime as _dt
        to = self.decision_cutoff_utc(s, day)
        return self.news.get(s.name, to - _dt.timedelta(days=days), to, self.p.include_social_in_score)

    def llm_cost_lines(self) -> list[str]:
        t = L.AiLedger.totals(self.strategy_id)
        net = sum(r.net_pnl for r in self.closed_trades)
        lines = [f"Cout API de ce run : {int(t[3])} appels, {int(t[0])} tokens entree / {int(t[1])} sortie, {t[2]:.2f} $"
                 + ("" if t[2] > 0 or t[3] == 0 else " (prix par token non renseignes : llm_price_in_per_mtok / llm_price_out_per_mtok)")]
        if t[2] > 0:
            lines.append(f"PnL net des trades {net:.2f} $ - cout API {t[2]:.2f} $ = {net - t[2]:.2f} $")
        return lines


# =============================================================================
#  Regles evenementielles communes (fiches 7, 9, 10)
# =============================================================================
class NewsEventStrategy(NexusLlmStrategy):
    BATCH_MODE = False
    DEFAULTS = dict(
        entry_threshold=0.5,
        exit_threshold=-0.5,
        min_headlines=2,
        hold_days=1,
        use_score_as_confidence=False,      # p du demi-Kelly melange avec 0.5 + score/2
        use_atr_stop=False,
        atr_multiplier=3.0,
        stop_min_pct=2.0,
        stop_max_pct=8.0,
    )

    def score_items(self, s: Sym, day, items: list):
        """-> (ok, score dans [-1 ; +1], titres notes, ambigu, detail). ok = False si rien n a pu etre note."""
        raise NotImplementedError

    def after_symbol_day(self, s: Sym, day, ok: bool, score: float, scored: int, ambiguous: bool):
        pass

    def on_llm_data_loaded(self):
        self.last_cutoff: dict[str, object] = {}
        self.days_with_news = self.scored_days = self.unscored_days = self.ambiguous_days = 0
        self.entry_signals = self.bad_news_exits = self.hold_exits = 0
        self.on_news_data_loaded()

    def on_news_data_loaded(self):
        pass

    def on_symbol_bar(self, s: Sym, day):
        if not s.traded:
            return
        import datetime as _dt
        p = self.p
        to_utc = self.decision_cutoff_utc(s, day)
        frm = self.last_cutoff.get(s.name) or (to_utc - _dt.timedelta(hours=24))
        if to_utc <= frm:
            return
        self.last_cutoff[s.name] = to_utc
        items = self.news.get(s.name, frm, to_utc, p.include_social_in_score)
        score, n, amb, ok, det = M.NAN, 0, False, False, ""
        if items:
            self.days_with_news += 1
            ok, score, n, amb, det = self.score_items(s, day, items)
            self.flush_bg_log()
            if ok:
                self.scored_days += 1
            else:
                self.unscored_days += 1
            if amb:
                self.ambiguous_days += 1
            self.signal(self.now, s.name, "actualites",
                        f"fenetre {frm:%Y-%m-%d %H:%M}Z-{to_utc:%Y-%m-%d %H:%M}Z titres={len(items)} notes={n} score={score:.2f}"
                        f"{' AMBIGU' if amb else ''} | {det}")
        good = ok and not amb and n >= p.min_headlines and score >= p.entry_threshold
        bad = ok and n >= 1 and score <= p.exit_threshold
        try:
            self.after_symbol_day(s, day, ok, score, n, amb)
        except Exception as ex:  # pragma: no cover
            self.nx_once("after" + type(ex).__name__, f"Erreur after_symbol_day : {ex}")

        if s.qty > 0 or s.target_qty > 0:
            if bad:
                self.set_target(s, 0, M.NAN, f"mauvaise nouvelle (score {score:.2f})")
                self.bad_news_exits += 1
            elif s.qty > 0 and s.bars_held >= p.hold_days and not good:
                self.set_target(s, 0, M.NAN, f"fin de detention ({p.hold_days} j)")
                self.hold_exits += 1
            return
        if not good or bad:
            return
        conf = M.clamp(0.5 + 0.5 * score, 0.5, 0.95) if p.use_score_as_confidence else M.NAN
        q, sd = self.size_qty(s, self.kelly_native_fraction(), s.last_price, conf)
        stop = S.long_stop(s.last_price, s.hist.atr, p.atr_multiplier, p.stop_min_pct / 100, p.stop_max_pct / 100) if p.use_atr_stop else M.NAN
        self.set_target(s, q, stop, f"actualites : score {score:.2f} sur {n} titres")
        self.entry_signals += 1
        self.signal(self.now, s.name, "entree_actualites", f"score={score:.2f} n={n} q={q} | {sd}")

    def add_news_report(self, lines: list[str]):
        self.flush_bg_log()
        lines.append(f"Jours-symbole avec titres : {self.days_with_news} | notes : {self.scored_days} | "
                     f"non notes (cache absent / budget) : {self.unscored_days} | ambigus : {self.ambiguous_days}")
        lines.append(f"Signaux d entree : {self.entry_signals} | sorties sur mauvaise nouvelle : {self.bad_news_exits} | "
                     f"sorties fin de detention : {self.hold_exits}")
        lines.append(f"Appels API reels : {self.api_calls} | refuses (backtest sans API / budget) : {self.api_refusals} | "
                     f"titres en memoire : {self.news.count} (doublons ecartes : {self.news.duplicates})")
        if self.news.count == 0:
            lines.append("AUCUN TITRE : remplir Data/news.csv (published_utc,symbol,source,headline,url) ou collecter avec "
                         "'python -m nexus actualites' -> aucun trade possible sans actualites.")
        if self.unscored_days > 0 and not self.p.api_calls_in_backtest:
            lines.append("NOTE : des titres n ont pas ete notes. Relancer UNE fois avec -p api_calls_in_backtest=true "
                         "(le cache se remplit), puis les backtests suivants sont gratuits.")
        lines += self.llm_cost_lines()


def finbert_prefilter(strategy: NexusLlmStrategy, items: list, allow_compute: bool, threshold: float, log_key: str):
    """Role 1 de FinBERT (fiches 7 et 9) : True = titre neutre (|P(pos) - P(neg)| < seuil) -> pas envoye au LLM."""
    probs, err = strategy.finbert.score([i.headline for i in items], allow_compute)
    if err:
        strategy.bg_log_once(log_key, f"Pre-filtre FinBERT partiel : {err} (les titres non notes partent au LLM)")
    return [p is not None and abs(L.FinBert.score_of(p)) < threshold for p in probs]


def mean_or_nan(v) -> float:
    return float(np.mean(v)) if len(v) else M.NAN
