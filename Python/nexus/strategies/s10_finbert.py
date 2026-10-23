"""FICHE 10 - Sentiment FinBERT (port de Strategies/Nexus10_FinBertSentiment.cs).

[arXiv] Araci 1908.10063 (FinBERT) ; [arXiv] Lopez-Lira, Tang.
FinBERT = BERT pre-entraine sur un corpus financier et affine sur le sentiment ; gratuit, execute EN LOCAL :
  - finbert_mode="serveur" : Tools/finbert_server.py (protocole HTTP du C#) ;
  - finbert_mode="local"   : modele charge en memoire (pip install transformers torch) ;
  - finbert_mode="auto"    : serveur, puis modele en memoire s il est injoignable.
Sortie P(positif), P(negatif), P(neutre) ; score = P(pos) - P(neg) dans [-1 ; +1] ; non neutre si |score| >= 0.4.

ROLE 1 - pre-filtre : integre aux fiches 7 et 9 (use_finbert_prefilter).
ROLE 2 - signal autonome (cette strategie) : regles de la fiche 7 avec le score FinBERT.
TEST A FAIRE : comparer a la fiche 7 (compare_trades_file = trades.csv d un run de la fiche 7) ;
si le PnL est comparable, FinBERT supprime l essentiel du cout API, sinon il reste un filtre.
"""
from __future__ import annotations

import os

import pandas as pd

from .. import llm as L
from .. import mathx as M
from .. import news as N
from .llm_base import NewsEventStrategy
from .s07_newsllm import STOCKS_CRYPTO


class Nexus10FinBertSentiment(NewsEventStrategy):
    NAME = "Nexus10_FinBertSentiment"
    DESCRIPTION = ("Fiche 10 - Signal autonome FinBERT local : score P(pos)-P(neg), regles de la fiche 7 (>= +0.5 sur 2 titres, "
                   "<= -0.5 sortie, 1 jour). A comparer a la fiche 7.")
    DEFAULTS = dict(
        symbols=STOCKS_CRYPTO,
        sizing_mode="demi_kelly",
        non_neutral_threshold=0.4,
        count_neutral_headlines=True,
        finbert_in_backtest=True,
        compare_with_strategy="Nexus07_NewsLlmEvent",
        compare_trades_file="",             # trades.csv d un run de la fiche 7 (resultats/Nexus07_.../trades.csv)
    )

    def on_news_data_loaded(self):
        self.headlines_scored = self.non_neutral = self.server_errors = 0
        self.nx(f"FinBERT : mode {self.p.finbert_mode}, serveur {self.p.finbert_url} (Tools/finbert_server.py) ; "
                "scores mis en cache dans .cache/finbert_cache.csv")

    def score_items(self, s, day, items):
        p = self.p
        probs, err = self.finbert.score([i.headline for i in items], p.finbert_in_backtest)
        if err:
            self.server_errors += 1
            self.nx_once("fb" + err[:20], "FinBERT : " + err)
        sc, parts = [], []
        for it, pr in zip(items, probs):
            v = L.FinBert.score_of(pr)
            parts.append((f"{v:+.2f}" if M.ok(v) else "?") + " " + N.one_line(it.headline, 90))
            if not M.ok(v):
                continue
            self.headlines_scored += 1
            nn = abs(v) >= p.non_neutral_threshold
            if nn:
                self.non_neutral += 1
            if nn or p.count_neutral_headlines:
                sc.append(v)
        score = sum(sc) / len(sc) if sc else M.NAN
        return len(sc) > 0, score, len(sc), False, " | ".join(parts)

    def report_extras(self, lines):
        self.add_news_report(lines)
        p = self.p
        hs = self.headlines_scored
        lines.append(f"Titres notes par FinBERT : {hs} | non neutres (|score| >= {p.non_neutral_threshold}) : {self.non_neutral} "
                     f"({self.non_neutral / hs if hs else 0:.0%}) | erreurs : {self.server_errors}")
        lines.append("Cout par appel : 0 $ (execution locale).")
        lines.append(self.compare_with_llm())

    def compare_with_llm(self) -> str:
        """Comparaison avec la fiche 7 : trades.csv d un run de la fiche 7 + cout API journalise."""
        p = self.p
        mine = self.closed_trades
        m = (len(mine), sum(t.net_pnl for t in mine), (sum(1 for t in mine if t.net_pnl > 0) / len(mine)) if mine else M.NAN)
        path = p.compare_trades_file
        if not path or not os.path.exists(path):
            return ("Comparaison fiche 7 : indiquer -p compare_trades_file=resultats/Nexus07_.../trades.csv (meme periode, memes symboles) "
                    "pour comparer FinBERT au LLM.")
        try:
            df = pd.read_csv(path)
            v = pd.to_numeric(df["net_pnl"], errors="coerce").dropna()
        except Exception as ex:
            return f"Comparaison fiche 7 : lecture impossible de {path} ({ex})"
        o = (len(v), float(v.sum()), float((v > 0).mean()) if len(v) else M.NAN)
        cost = L.AiLedger.cost_of(p.compare_with_strategy)
        pct = lambda x: f"{x:.0%}" if M.ok(x) else "n/d"
        return (f"Comparaison : FinBERT {m[0]} trades, PnL net {m[1]:.2f}, reussite {pct(m[2])} | {p.compare_with_strategy} : "
                f"{o[0]} trades, PnL net {o[1]:.2f}, reussite {pct(o[2])}, cout API journalise {cost:.2f} $")
