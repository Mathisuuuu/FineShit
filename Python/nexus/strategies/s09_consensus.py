"""FICHE 9 - Consensus de 3 LLM (port de Strategies/Nexus09_LlmConsensus.cs).

[arXiv] 2603.22567 TrustTrade (selective consensus in LLM trading agents).
  - Claude + DeepSeek + Gemini notent la MEME nouvelle : meme consigne, temperature 0, appels independants.
  - Score par modele : entier de -2 (tres mauvais) a +2 (tres bon).
  - Accord : meme signe pour les 3 ET chaque |score| >= 1 ; les 3 a 0 = neutre.
  - Desaccord : signal d ambiguite -> pas de trade sur ce symbole ce jour-la.
  - Score final = moyenne des 3 / 2 (dans [-1 ; +1]), puis regles de la fiche 7.
  - Cout x3 : pre-filtre FinBERT ACTIF par defaut (repli : tout envoyer si FinBERT est indisponible).
  - Mesure : les jours de desaccord sont-ils suivis de mouvements plus volatils ?
"""
from __future__ import annotations

from .. import llm as L
from .. import mathx as M
from .. import news as N
from .llm_base import NewsEventStrategy, finbert_prefilter, mean_or_nan
from .s07_newsllm import STOCKS_CRYPTO


class Nexus09LlmConsensus(NewsEventStrategy):
    NAME = "Nexus09_LlmConsensus"
    DESCRIPTION = ("Fiche 9 - Consensus Claude + DeepSeek + Gemini (-2..+2) : action seulement si les 3 sont d accord ; "
                   "desaccord = pas de trade ce jour. Pre-filtre FinBERT.")
    DEFAULTS = dict(
        symbols=STOCKS_CRYPTO,
        sizing_mode="demi_kelly",
        deepseek_model="deepseek-chat",
        deepseek_api_key="",
        deepseek_price_in=0.0,
        deepseek_price_out=0.0,
        gemini_model="gemini-2.5-flash",
        gemini_api_key="",
        gemini_price_in=0.0,
        gemini_price_out=0.0,
        gemini_max_tokens=1024,             # les modeles "thinking" consomment des tokens de reflexion
        min_abs_score=1,
        use_finbert_prefilter=True,
        finbert_neutral_threshold=0.4,
        finbert_in_backtest=True,
    )

    def on_news_data_loaded(self):
        p = self.p
        self.deepseek = self.build_config("deepseek", p.deepseek_model, p.deepseek_api_key, 0.0, p.llm_max_tokens, p.llm_timeout_sec,
                                          p.deepseek_price_in, p.deepseek_price_out)
        self.gemini = self.build_config("gemini", p.gemini_model, p.gemini_api_key, 0.0, max(p.llm_max_tokens, p.gemini_max_tokens),
                                        p.llm_timeout_sec, p.gemini_price_in, p.gemini_price_out)
        self.main_llm.temperature = 0.0
        self.nx(f"Consensus : {self.main_llm.label} (cle {L.mask(self.main_llm.api_key)}) + {self.deepseek.label} "
                f"(cle {L.mask(self.deepseek.api_key)}) + {self.gemini.label} (cle {L.mask(self.gemini.api_key)})")
        self.agree_items = self.neutral_items = self.disagree_items = self.incomplete_items = self.finbert_filtered = 0
        self.pending_flag: dict[str, int] = {}          # 1 accord, 2 desaccord
        self.next_abs_after_agree: list[float] = []
        self.next_abs_after_disagree: list[float] = []

    def consensus(self, s, items, allow_finbert: bool):
        """Par titre : 1 accord, 0 neutre, 2 desaccord, -1 incomplet ; finals dans [-1 ; +1]."""
        n = len(items)
        finals = [M.NAN] * n
        kind = [-1] * n
        send = [True] * n
        if self.p.use_finbert_prefilter:
            for i, nz in enumerate(finbert_prefilter(self, items, allow_finbert, self.p.finbert_neutral_threshold, "fbpre9")):
                if nz:
                    send[i], kind[i], finals[i] = False, 0, 0.0
                    self.finbert_filtered += 1
        company = self.company_of(s.name)
        models = (self.main_llm, self.deepseek, self.gemini)
        idx = [i for i in range(n) if send[i]]
        jobs = []
        for i in idx:
            user = L.Prompts.headline5(s.name, company, items[i].headline, self.context_for(s, items[i].published_utc))
            for cfg in models:
                jobs.append(lambda c=cfg, u=user: self.call_llm(c, L.Prompts.HEADLINE_SYSTEM, u, "fiche9_" + c.provider))
        res = self.run_all(jobs)
        mn = self.p.min_abs_score
        for k, i in enumerate(idx):
            sc = []
            for m in range(3):
                r = res[k * 3 + m]
                sc.append(L.Prompts.parse_score5(r.text) if r is not None and r.ok else None)
            if any(v is None for v in sc):
                kind[i] = -1
                continue
            if all(v >= mn for v in sc) or all(v <= -mn for v in sc):
                kind[i], finals[i] = 1, sum(sc) / 3.0 / 2.0
            elif all(v == 0 for v in sc):
                kind[i], finals[i] = 0, 0.0
            else:
                kind[i] = 2
        return kind, finals

    def score_items(self, s, day, items):
        kind, finals = self.consensus(s, items, self.p.finbert_in_backtest)
        self.agree_items += kind.count(1)
        self.neutral_items += kind.count(0)
        self.disagree_items += kind.count(2)
        self.incomplete_items += kind.count(-1)
        amb = 2 in kind
        valid = [finals[i] for i in range(len(kind)) if kind[i] in (0, 1)]
        score = sum(valid) / len(valid) if valid else M.NAN
        lbl = {0: "neutre", 1: "accord", 2: "DESACCORD", -1: "incomplet"}
        det = " | ".join(lbl[kind[i]] + (f" {finals[i]:+.2f}" if M.ok(finals[i]) else "") + " " + N.one_line(it.headline, 80)
                         for i, it in enumerate(items))
        return (len(valid) > 0 or amb), score, len(valid), amb, det

    def after_symbol_day(self, s, day, ok, score, scored, ambiguous):
        # Rendement absolu du lendemain selon le jour precedent (accord / desaccord).
        prev = self.pending_flag.pop(s.name, None)
        if prev is not None and s.hist.count >= 2:
            r = abs(s.hist.log_return_at(s.hist.count - 1))
            if M.ok(r):
                (self.next_abs_after_disagree if prev == 2 else self.next_abs_after_agree).append(r)
        if ambiguous:
            self.pending_flag[s.name] = 2
        elif ok and scored > 0:
            self.pending_flag[s.name] = 1

    def report_extras(self, lines):
        self.add_news_report(lines)
        lines.append(f"Titres : accord {self.agree_items} | neutres {self.neutral_items} | desaccord {self.disagree_items} | "
                     f"incomplets {self.incomplete_items} | filtres FinBERT {self.finbert_filtered}")
        ma, md = mean_or_nan(self.next_abs_after_agree), mean_or_nan(self.next_abs_after_disagree)
        t = M.welch_t(self.next_abs_after_disagree, self.next_abs_after_agree)
        fmt = lambda x: f"{x:.2%}" if M.ok(x) else "n/d"
        lines.append(f"|Rendement| du lendemain : apres desaccord {fmt(md)} (n={len(self.next_abs_after_disagree)}) vs apres accord "
                     f"{fmt(ma)} (n={len(self.next_abs_after_agree)}), t de Welch {f'{t:.2f}' if M.ok(t) else 'n/d'}")
        if M.ok(t) and t > 2:
            lines.append("-> Le desaccord precede des mouvements plus volatils : l utiliser comme filtre de risque (fiche 9).")
        lines.append("Le consensus reduit fortement le nombre de signaux : prevoir plus de semaines de paper pour atteindre 30 trades.")
