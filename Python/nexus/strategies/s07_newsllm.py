"""FICHE 7 - Evenementielle : actualites notees par un LLM (port de Strategies/Nexus07_NewsLlmEvent.cs).

[arXiv] Lopez-Lira, Tang - "Can ChatGPT Forecast Stock Price Movements?"
  - Question : "Ce titre est-il bon, mauvais ou sans effet pour le cours de X a court terme ?"
    -> bon = +1, mauvais = -1, sans effet = 0 ; moyenne du jour par symbole, doublons = 1 titre.
  - Entree long : score moyen >= +0.5 avec au moins 2 titres ; <= -0.5 : sortie / entree interdite.
  - Detention 1 jour de bourse ; demi-Kelly, 3 % max (module B).
  - Reddit exclu du score par defaut ; Fear & Greed en contexte pour la crypto.
  - Cout des appels journalise (.cache/ai_costs.csv) et rapporte au PnL.
  - Option : pre-filtre FinBERT (fiche 10, role 1) : seuls les titres non neutres (|score| >= 0.4) partent au LLM.
Point d attention : l auteur conclut que le LLM marche mieux en JUGE qu en generateur de signaux (fiche 8).
"""
from __future__ import annotations

from .. import llm as L
from .. import news as N
from .llm_base import NewsEventStrategy, finbert_prefilter

STOCKS_CRYPTO = "SPY,QQQ,AAPL,MSFT,NVDA,AMZN,GOOGL,META,JPM,JNJ,XOM,UNH,V,PG,HD,BTCUSD,ETHUSD"


class Nexus07NewsLlmEvent(NewsEventStrategy):
    NAME = "Nexus07_NewsLlmEvent"
    DESCRIPTION = ("Fiche 7 - Titres notes par un LLM (bon +1 / mauvais -1 / sans effet 0), moyenne >= +0.5 sur 2 titres -> long 1 jour ; "
                   "<= -0.5 -> sortie. Pre-filtre FinBERT optionnel.")
    DEFAULTS = dict(
        symbols=STOCKS_CRYPTO,
        sizing_mode="demi_kelly",
        use_finbert_prefilter=False,
        finbert_neutral_threshold=0.4,
        finbert_in_backtest=True,           # calculer FinBERT pour les titres absents de son cache
    )

    def on_news_data_loaded(self):
        self.headlines_sent = self.finbert_filtered = self.unparseable = 0
        self.label_counts = [0, 0, 0]       # mauvais, sans effet, bon

    def label(self, s, items, allow_finbert: bool) -> list:
        lab = [None] * len(items)
        need = [True] * len(items)
        if self.p.use_finbert_prefilter:
            neutral = finbert_prefilter(self, items, allow_finbert, self.p.finbert_neutral_threshold, "fbpre7")
            for i, nz in enumerate(neutral):
                if nz:
                    lab[i], need[i] = 0, False
                    self.finbert_filtered += 1
        company = self.company_of(s.name)
        idx = [i for i in range(len(items)) if need[i]]
        jobs = []
        for i in idx:
            user = L.Prompts.headline3(s.name, company, items[i].headline, self.context_for(s, items[i].published_utc))
            jobs.append(lambda u=user: self.call_llm(self.main_llm, L.Prompts.HEADLINE_SYSTEM, u, "fiche7_titre"))
        res = self.run_all(jobs)
        for k, i in enumerate(idx):
            r = res[k]
            if r is None or not r.ok:
                continue
            if not r.from_cache:
                self.headlines_sent += 1
            v = L.Prompts.parse_label3(r.text)
            if v is None:
                self.unparseable += 1
                continue
            lab[i] = v
        return lab

    def score_items(self, s, day, items):
        lab = self.label(s, items, self.p.finbert_in_backtest)
        valid = [v for v in lab if v is not None]
        for v in valid:
            self.label_counts[v + 1] += 1
        score = sum(valid) / len(valid) if valid else float("nan")
        det = " | ".join(("?" if v is None else f"{v:+d}" if v else "0") + " " + N.one_line(it.headline, 90) for v, it in zip(lab, items))
        return len(valid) > 0, score, len(valid), False, det

    def report_extras(self, lines):
        self.add_news_report(lines)
        lines.append(f"Titres envoyes au LLM ({self.main_llm.label}) : {self.headlines_sent} | filtres par FinBERT : {self.finbert_filtered} | "
                     f"reponses illisibles : {self.unparseable}")
        lines.append(f"Repartition des notes : mauvais {self.label_counts[0]}, sans effet {self.label_counts[1]}, bon {self.label_counts[2]}")
        lines.append("Rappel (Lopez-Lira, Tang) : effet plus fort sur petites capitalisations et apres mauvaise nouvelle ; "
                     "il decroit a mesure que l usage des LLM se repand.")
