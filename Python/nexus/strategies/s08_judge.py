"""FICHE 8 - LLM juge et veto sur les candidats momentum (port de Strategies/Nexus08_LlmJudgeVeto.cs).

Les maths choisissent le trade, le LLM ne peut que le BLOQUER ("pessimiste strict"). [arXiv] Lopez-Lira, Tang.
  - Candidats : fiches 1 (TSMOM), 2 (XSMOM) et 3 (multi-facteurs), memes moteurs de signaux.
  - Role : chercher ce que les maths ne voient pas (litiges, revision de previsions, enquete, dilution,
    changement de direction, fusion) ; donnees : titres des 7 derniers jours + prochaine date de resultats.
  - Sortie JSON stricte {veto, raison, confiance} ; veto applique si confiance >= 0.7.
  - Pouvoir : bloquer ou reduire de moitie ; jamais augmenter, jamais creer.
  - Option classement : classer les candidats par risque et retirer le quart le plus risque.

MESURER SI LE JUGE SERT A QUELQUE CHOSE
  1. chaque veto est journalise avec le trade "fantome" qu il a bloque ;
  2. les trades acceptes sont suivis avec EXACTEMENT les memes regles fantomes
     (entree a l ouverture suivante, stop ATR, sortie a N jours) ;
  3. apres au moins 30 vetos : comparaison des rendements moyens (t de Welch) ;
  4. garder le juge seulement si les trades bloques font nettement moins bien.
  Alerte si le taux de veto depasse 25 % des candidats (revoir la consigne).
"""
from __future__ import annotations

import os
from dataclasses import dataclass

import numpy as np

from .. import data as D
from .. import llm as L
from .. import mathx as M
from .. import news as N
from .. import signals as S
from .llm_base import NexusLlmStrategy

SOURCES = ("tsmom_fiche1", "xsmom_fiche2", "multifacteur_fiche3", "union")


@dataclass
class Shadow:
    symbol: str
    decision: object
    start_index: int
    stop_distance: float
    vetoed: bool
    reason: str = ""
    confidence: float = 0.0
    entry: float = M.NAN
    exit: float = M.NAN
    stop: float = M.NAN
    entry_index: int = -1
    done: bool = False

    @property
    def ret(self) -> float:
        return self.exit / self.entry - 1 if self.done and self.entry > 0 else M.NAN


@dataclass
class Verdict:
    ok: bool = False
    veto: bool = False
    reason: str = ""
    confidence: float = 0.0
    risk: float = M.NAN


class Nexus08LlmJudgeVeto(NexusLlmStrategy):
    NAME = "Nexus08_LlmJudgeVeto"
    DESCRIPTION = ("Fiche 8 - Candidats momentum (fiches 1-3) soumis a un LLM 'pessimiste strict' : veto si confiance >= 0.7 "
                   "(bloquer ou /2), option classement ; suivi fantome des trades bloques vs acceptes.")
    DEFAULTS = dict(
        symbols="SPY,QQQ,XLF,XLV,XLE,XLI,XLY,XLP,XLU,XLB,XLRE,XLC,AAPL,MSFT,NVDA,AMZN,GOOGL,META,JPM,JNJ,XOM,UNH,V,PG,HD",
        sizing_mode="natif",
        llm_max_tokens=400,
        source="union",                     # tsmom_fiche1 | xsmom_fiche2 | multifacteur_fiche3 | union
        judge_mode="veto",                  # veto | classement | veto_puis_classement
        veto_action="bloquer",              # bloquer | reduire_de_moitie
        veto_confidence=0.7,
        rank_remove_pct=25.0,
        headline_days=7,
        max_veto_rate_pct=25.0,
        min_vetos_for_test=30,
        shadow_hold_days=21,
        rejudge_days=5,                     # un verdict vaut N jours tant que le symbole reste candidat (0 = chaque jour, comme le C#)
        lookback_days=252,
        skip_days=21,
        target_vol_pct=12.0,
        vol_window_days=126,
        xs_top=0,
        xs_buffer=0,
        mf_top=5,
        mf_buffer=8,
        fundamentals_file="",
        atr_multiplier=3.0,
        stop_min_pct=2.0,
        stop_max_pct=8.0,
        barometer="SPY",
        use_panic_state=True,
        panic_multiplier=0.5,
    )

    def required_references(self):
        return [self.p.barometer]

    def on_llm_data_loaded(self):
        p = self.p
        if p.source not in SOURCES:
            raise ValueError(f"source inconnue '{p.source}' ({', '.join(SOURCES)})")
        self.fund = self.mf_engine = None
        if self.uses("multifacteur_fiche3"):
            self.fund = D.Fundamentals(p.fundamentals_file if p.fundamentals_file and os.path.exists(p.fundamentals_file) else None)
            self.nx("Fondamentaux (fiche 3) : " + self.fund.message)
            self.mf_engine = S.MultiFactorEngine(self.fund)
        self.ts_set, self.xs_set, self.mf_set = set(), set(), set()
        self.shadows: list[Shadow] = []
        self.candidates = self.vetoes = self.halved = self.rank_removed = self.judge_errors = self.rebalances = 0
        self.verdicts: dict[str, tuple] = {}            # symbole -> (lot du verdict, Verdict, retire par classement)
        self.reused_verdicts = 0

    def uses(self, src: str) -> bool:
        return self.p.source == src or self.p.source == "union"

    def on_batch(self, day):
        p = self.p
        self.update_shadows()
        traded = self.traded_syms
        if not traded:
            return
        baro = self.sym(p.barometer)
        mom = {}
        for s in traded:
            m = S.return_12_1(s.hist, p.lookback_days, p.skip_days)
            if M.ok(m):
                mom[s.name] = m
        if len(mom) < 4:
            return
        panic = False
        if p.use_panic_state and baro is not None:
            panic, _ = S.panic_state(baro.hist, 504, 21, 252)

        # --- Ensembles desires par source (memes regles que les fiches 1, 2, 3).
        monthly = (self.uses("tsmom_fiche1") or self.uses("xsmom_fiche2")) and self.is_rebalance_day(day, "mensuel", baro or traded[0])
        held = {s.name for s in traded if s.qty > 0 or s.target_qty > 0}
        if monthly:
            self.rebalances += 1
            for s in traded:
                s.stopped_out = False
            if self.uses("tsmom_fiche1"):
                self.ts_set = {k for k, v in mom.items() if v > 0}
            if self.uses("xsmom_fiche2"):
                n = len(mom)
                top = p.xs_top if p.xs_top > 0 else max(1, int(round(n / 4.0)))
                buf = max(top, p.xs_buffer) if p.xs_buffer > 0 else max(top, int(round(n * 0.36)))
                self.xs_set = set(S.select_with_buffer(mom, held & self.xs_set, top, buf))
        if self.uses("multifacteur_fiche3") and self.mf_engine is not None:
            stocks = {s.name: s.hist for s in traded if s.asset_class == "Action"}
            res = self.mf_engine.update(day, stocks, baro.hist if baro is not None else None)
            if stocks and res.scored >= min(8, len(stocks)):
                self.mf_set = set(S.select_with_buffer(res.composite, held & self.mf_set, p.mf_top, p.mf_buffer))
        desired = set()
        if self.uses("tsmom_fiche1"):
            desired |= self.ts_set
        if self.uses("xsmom_fiche2"):
            desired |= self.xs_set
        if self.uses("multifacteur_fiche3"):
            desired |= self.mf_set

        # --- Sorties : le juge n intervient pas (il ne peut que bloquer des entrees).
        for s in traded:
            if (s.qty > 0 or s.target_qty > 0) and s.name not in desired:
                self.set_target(s, 0, M.NAN, f"plus candidat ({p.source})")

        # --- Nouveaux candidats -> juge (verdict reutilise rejudge_days jours tant que le symbole reste candidat).
        for name in [k for k in self.verdicts if k not in desired or (self.sym(k) is not None and self.sym(k).qty != 0)]:
            del self.verdicts[name]
        cands = [s for s in traded if s.name in desired and s.qty == 0 and s.target_qty == 0 and not s.stopped_out]
        if not cands or self.warming_up:
            return
        fresh = [c for c in cands if c.name not in self.verdicts or p.rejudge_days <= 0
                 or self.batch_count - self.verdicts[c.name][0] >= p.rejudge_days]
        if fresh:
            self.candidates += len(fresh)
            verdicts = self.judge(fresh, day)
            removed_by_rank = set()
            if p.judge_mode != "veto":
                ranked = sorted([c for c in fresh if verdicts[c.name].ok and M.ok(verdicts[c.name].risk)],
                                key=lambda c: -verdicts[c.name].risk)
                k = int(np.ceil(len(ranked) * p.rank_remove_pct / 100.0))
                removed_by_rank = {c.name for c in ranked[:k]}
            for c in fresh:
                self.verdicts[c.name] = (self.batch_count, verdicts[c.name], c.name in removed_by_rank)
        fresh_names = {c.name for c in fresh}
        self.reused_verdicts += len(cands) - len(fresh)

        n_valid = len(mom)
        for s in cands:
            _, v, ranked = self.verdicts[s.name]
            is_new = s.name in fresh_names
            vetoed = p.judge_mode != "classement" and v.ok and v.veto and v.confidence >= p.veto_confidence
            dist = S.atr_stop_distance(s.last_price, s.hist.atr, p.atr_multiplier, p.stop_min_pct / 100, p.stop_max_pct / 100)
            blocked = ranked or (vetoed and p.veto_action == "bloquer")
            if is_new:
                self.shadows.append(Shadow(s.name, day, s.hist.count, dist, blocked,
                                           f"classement : quart le plus risque (risque {v.risk:.2f})" if ranked else v.reason, v.confidence))
                if vetoed:
                    self.vetoes += 1
                if ranked:
                    self.rank_removed += 1
            if blocked:
                if is_new:
                    why = "classement" if ranked else v.reason
                    self.signal(self.now, s.name, "veto", f"{why} (confiance {v.confidence:.2f})")
                    self.nx(f"VETO {day:%Y-%m-%d} {s.name} : {'quart le plus risque' if ranked else v.reason} (confiance {v.confidence:.2f})")
                continue
            w = S.inverse_vol_weight(s.hist, p.target_vol_pct / 100.0, p.vol_window_days, n_valid, 0)
            if not M.ok(w):
                continue
            if panic and (self.uses("tsmom_fiche1") or self.uses("xsmom_fiche2")):
                w *= p.panic_multiplier
            if vetoed and p.veto_action == "reduire_de_moitie":
                w *= 0.5
                if is_new:
                    self.halved += 1
            q, det = self.size_qty(s, w, s.last_price)
            self.set_target(s, q, s.last_price - dist if M.ok(dist) else M.NAN,
                            f"candidat {p.source} accepte par le juge{' (taille /2)' if vetoed else ''}")
            if is_new:
                self.signal(self.now, s.name, "juge_ok", f"veto={v.veto} conf={v.confidence:.2f} risque={v.risk:.2f} | {v.reason} | {det}")
        rate = (self.vetoes + self.rank_removed) / self.candidates if self.candidates else 0.0
        if self.candidates >= 8 and rate > p.max_veto_rate_pct / 100.0:
            self.nx_once(f"vetorate{int(rate * 10)}", f"ATTENTION : taux de veto {rate:.0%} > {p.max_veto_rate_pct:.0f} % des candidats -> "
                                                      "le juge transforme le momentum en faible exposition ; revoir la consigne.")

    def judge(self, cands, day) -> dict:
        p = self.p
        jobs = []
        for c in cands:
            heads = self.recent_headlines(c, day, p.headline_days)
            nxt = self.earnings.next_date(c.name, day)
            earn = f"{nxt:%Y-%m-%d}" if nxt is not None else ""

            def job(c=c, heads=heads, earn=earn):
                v = Verdict()
                company = self.company_of(c.name)
                if p.judge_mode != "classement":
                    r = self.call_llm(self.main_llm, L.Prompts.JUDGE_SYSTEM,
                                      L.Prompts.judge_user(c.name, company, p.source, 21, day, earn, heads), "fiche8_veto")
                    parsed = L.Prompts.parse_judge(r.text) if r.ok else None
                    if parsed is not None:
                        v.ok, (v.veto, v.reason, v.confidence) = True, parsed
                    else:
                        v.reason = "JSON illisible" if r.ok else (r.error or "")
                if p.judge_mode != "veto":
                    r = self.call_llm(self.main_llm, L.Prompts.JUDGE_SYSTEM,
                                      L.Prompts.risk_rank_user(c.name, company, p.source, day, earn, heads), "fiche8_classement")
                    parsed = L.Prompts.parse_risk(r.text) if r.ok else None
                    if parsed is not None:
                        v.ok, v.risk = True, parsed[0]
                        if not v.reason:
                            v.reason = parsed[1]
                return v
            jobs.append(job)
        out = self.run_all(jobs)
        self.flush_bg_log()
        res = {}
        for c, v in zip(cands, out):
            v = v or Verdict(reason="delai depasse")
            if not v.ok:
                self.judge_errors += 1       # pas de reponse : le trade passe tel quel (le juge ne fait que bloquer)
            res[c.name] = v
        return res

    def update_shadows(self):
        hold = self.p.shadow_hold_days
        for sh in self.shadows:
            if sh.done:
                continue
            s = self.sym(sh.symbol)
            if s is None:
                sh.done = True
                continue
            h = s.hist
            if sh.entry_index < 0:
                if h.count <= sh.start_index:
                    continue
                sh.entry_index = sh.start_index
                sh.entry = float(h.open[sh.entry_index])
                sh.stop = sh.entry - (sh.stop_distance if M.ok(sh.stop_distance) else 0.08 * sh.entry)
            for i in range(sh.entry_index, h.count):
                if h.low[i] <= sh.stop:
                    sh.exit, sh.done = min(float(h.open[i]), sh.stop), True
                elif i - sh.entry_index + 1 >= hold:
                    sh.exit, sh.done = float(h.close[i]), True
                if sh.done:
                    break

    def report_extras(self, lines):
        p = self.p
        self.update_shadows()
        self.flush_bg_log()
        blocked = [x.ret for x in self.shadows if x.vetoed and x.done and M.ok(x.ret)]
        accepted = [x.ret for x in self.shadows if not x.vetoed and x.done and M.ok(x.ret)]
        rate = (self.vetoes + self.rank_removed) / self.candidates if self.candidates else 0.0
        lines.append(f"Source : {p.source} | mode : {p.judge_mode} / {p.veto_action} | reequilibrages {self.rebalances}")
        lines.append(f"Candidats juges : {self.candidates} | vetos (conf >= {p.veto_confidence:.2f}) : {self.vetoes} | retires par classement : "
                     f"{self.rank_removed} | tailles /2 : {self.halved} | sans reponse : {self.judge_errors} | taux {rate:.1%}")
        lines.append(f"Verdicts reutilises (rejudge_days={p.rejudge_days}) : {self.reused_verdicts} candidat-jours sans nouvel appel")
        if self.judge_errors and not p.api_calls_in_backtest:
            lines.append("NOTE : candidats sans reponse du juge (cache vide) -> ils passent tels quels. Relancer une fois avec "
                         "-p api_calls_in_backtest=true pour remplir le cache.")
        if rate > p.max_veto_rate_pct / 100.0:
            lines.append(f"ALERTE : taux de veto > {p.max_veto_rate_pct} % -> revoir la consigne (juge trop severe).")
        t = M.welch_t(blocked, accepted)
        avg = lambda v: f"{np.mean(v):.2%}" if v else "n/d"
        lines.append(f"Trades fantomes ({p.shadow_hold_days} j, stop ATR) : bloques {len(blocked)} (moy {avg(blocked)}) vs acceptes "
                     f"{len(accepted)} (moy {avg(accepted)}) | t de Welch {f'{t:.2f}' if M.ok(t) else 'n/d'}")
        if len(blocked) < p.min_vetos_for_test:
            lines.append(f"Moins de {p.min_vetos_for_test} vetos resolus : pas encore de conclusion sur l utilite du juge.")
        elif M.ok(t) and t < -2:
            lines.append("CONCLUSION : les trades bloques font nettement moins bien -> GARDER le juge.")
        else:
            lines.append("CONCLUSION : pas de difference nette -> le juge ne fait que reduire l exposition au hasard ; le retirer.")
        for sh in [x for x in self.shadows if x.vetoed][-10:]:
            lines.append(f"  veto {sh.decision:%Y-%m-%d} {sh.symbol:<6} {f'{sh.ret:.2%}' if M.ok(sh.ret) else 'en cours':>8} : "
                         f"{N.one_line(sh.reason, 100)}")
        lines += self.llm_cost_lines()
