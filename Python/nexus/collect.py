"""Collecte d actualites et audit par une seconde IA (ce que le C# faisait en temps reel / en fin de run).

    collect_news   NewsAPI (requetes groupees par 8 symboles) + Reddit -> news_live.csv (dedoublonne avec news.csv),
                   Fear & Greed (cache), calendrier des resultats Alpha Vantage -> earnings.csv
    prescore       pre-notation des titres collectes (fiches 7, 9, 10) : le cache est chaud au backtest suivant
    audit_report   module C : relecture d un rapport de backtest par un second LLM (biais, surapprentissage...)

Ces fonctions appellent des services externes (cles API requises) : elles ne sont lancees que sur demande
explicite (commandes "actualites" et "audit").
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

from . import llm as L
from . import news as N
from .engine import parse_map, split_list

REDDIT_SUBS = "stocks,investing,wallstreetbets,CryptoCurrency"


def collect_news(symbols: list[str], data_dir: str, company_names: str, use_newsapi: bool = True, use_reddit: bool = False,
                 reddit_subs: str = REDDIT_SUBS, hours: int = 24, fear_greed: bool = True, alpha_vantage: bool = False,
                 newsapi_key: str = "", alpha_vantage_key: str = "", log=print) -> list[N.NewsItem]:
    """Collecte et ajoute les titres nouveaux a data_dir/news_live.csv. -> titres nouveaux."""
    os.makedirs(data_dir, exist_ok=True)
    live = os.path.join(data_dir, "news_live.csv")
    store = N.NewsStore()
    for f in (os.path.join(data_dir, "news.csv"), live):
        if os.path.exists(f):
            store.load_csv(f, symbols)
    companies = {k.upper(): v for k, v in parse_map(company_names).items()}
    since = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(hours=hours)
    fresh: list[N.NewsItem] = []
    if use_newsapi:
        key = L.resolve_secret(newsapi_key, "NEWSAPI_KEY")
        q = [(s, companies.get(s.upper()) or s) for s in symbols]
        for i in range(0, len(q), 8):
            items, err = L.fetch_newsapi_batch(key, dict(q[i:i + 8]), since)
            fresh += [it for it in items if store.add(it)]
            if err:
                log(f"NewsAPI : {err}")
                if "absente" in err:
                    break
    if use_reddit:
        subs = split_list(reddit_subs)
        for s in symbols:
            items, err = L.fetch_reddit(s, subs)
            fresh += [it for it in items if store.add(it)]
            if err:
                log(f"Reddit ({s}) : {err}")
    store.append_csv(live, fresh)
    log(f"{len(fresh)} nouveaux titres ajoutes a {live}" + (f" ({', '.join(sorted({x.symbol for x in fresh}))})" if fresh else ""))
    if fear_greed:
        fg = N.FearGreed()
        fg.load_cache()
        ok, err = fg.refresh()
        log(f"Fear & Greed : {fg.count} jours en cache" if ok else f"Fear & Greed : {err}")
    if alpha_vantage:
        n, err = L.fetch_alpha_vantage_earnings(L.resolve_secret(alpha_vantage_key, "ALPHAVANTAGE_KEY"), os.path.join(data_dir, "earnings.csv"))
        log(f"Alpha Vantage : {n} dates de resultats ajoutees" if err is None else f"Alpha Vantage : {err}")
    return fresh


def prescore(strategy, items: list[N.NewsItem], log=print):
    """Pre-note des titres avec la consigne exacte de la fiche (7 : LLM, 9 : consensus, 10 : FinBERT) -> cache chaud.
    `strategy` : instance de fiche 7, 9 ou 10 deja preparee (on_data_loaded appele)."""
    by_sym: dict[str, list] = {}
    for it in items:
        if strategy.p.include_social_in_score or not it.is_social:
            by_sym.setdefault(it.symbol.upper(), []).append(it)
    code = strategy.NAME[5:7]
    for sym, lst in by_sym.items():
        s = strategy.sym(sym)
        if s is None:
            continue
        if code == "07":
            strategy.label(s, lst, True)
        elif code == "09":
            strategy.consensus(s, lst, True)
        elif code == "10":
            strategy.finbert.score([x.headline for x in lst], True)
    strategy.flush_bg_log()
    t = L.AiLedger.totals(strategy.strategy_id)
    log(f"Pre-notation {strategy.NAME} : {sum(len(v) for v in by_sym.values())} titres, {int(t[3])} appels API, {t[2]:.4f} $")
    for line in strategy.log[-10:]:
        if "Erreur" in line:
            log(line)


def audit_report(report_path: str, provider: str = "claude", model: str = "", api_key: str = "", log=print) -> str | None:
    """Module C : relecture du rapport par une seconde IA -> fichier *_audit_<fournisseur>.txt a cote du rapport."""
    with open(report_path, encoding="utf-8") as f:
        txt = f.read()
    cfg = L.LlmConfig.build(provider, model, api_key, 0.0, 1500, 120)
    log(f"Audit du rapport demande a {cfg.label} (cle {L.mask(cfg.api_key)})")
    r = L.complete(cfg, L.Prompts.AUDIT_SYSTEM, L.Prompts.audit_user(txt), None, L.Prompts.VERSION)
    L.AiLedger.record("audit", cfg, r, "audit_rapport")
    out = os.path.splitext(report_path)[0] + f"_audit_{cfg.provider}.txt"
    with open(out, "w", encoding="utf-8") as f:
        f.write(r.text if r.ok else f"Audit impossible : {r.error}")
    log(("Audit ecrit : " if r.ok else "Audit impossible (" + str(r.error) + ") : ") + out)
    return out if r.ok else None


def default_data_dir() -> str:
    return os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "..", "Data"))

