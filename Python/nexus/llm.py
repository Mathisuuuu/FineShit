"""Connectivite externe des fiches 7, 8, 9, 10 et du module C (port de AddOns/NexusLlm.cs).

    http_request    requetes HTTP(S) avec relances (429 / 5xx / reseau), bibliotheque standard
    resolve_secret  cles API : valeur -> variable d environnement -> keys.txt
    LlmConfig       Claude (Anthropic Messages API), DeepSeek (compatible OpenAI), Gemini
                    (generateContent) ou tout point compatible OpenAI
    complete        appel bloquant, cache d abord
    LlmCache        cache disque des reponses : un backtest deja paye se rejoue gratuitement.
                    MEME FORMAT ET MEMES CLES que le C# (label|nx-v1|sha1[:20]|sha1[:20], texte en base64) :
                    le cache NinjaTrader (Documents/NinjaTrader 8/Nexus/cache/llm_cache.tsv) est relu s il existe
    AiLedger        journal des couts API -> .cache/ai_costs.csv
    Prompts         consignes et analyseurs de reponses (fiches 7, 8, 9, 13, audit du module C)
    FinBert         FinBERT (fiche 10) : serveur local Tools/finbert_server.py OU modele charge en memoire
                    (transformers + torch, ProsusAI/finbert), cache disque partage avec le C#
    fetch_newsapi_batch / fetch_reddit / fetch_alpha_vantage_earnings : collecte (commande "actualites")

SECURITE : ne jamais laisser une cle API dans un fichier partage. Preferer les variables d environnement
(ANTHROPIC_API_KEY, DEEPSEEK_API_KEY, GEMINI_API_KEY, NEWSAPI_KEY, ALPHAVANTAGE_KEY), ou un fichier NOM=valeur
exclu du depot par .gitignore : Python/keys.txt, .env.txt ou .env a la racine du depot (ou NEXUS_KEYS_FILE).
"""
from __future__ import annotations

import base64
import csv
import json
import os
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone

from . import data as D
from . import mathx as M
from .news import NewsItem, hash10, normalize, one_line

PYTHON_DIR = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
NT_NEXUS_DIR = os.path.join(os.path.expanduser("~"), "Documents", "NinjaTrader 8", "Nexus")
USER_AGENT = "NexusPython/1.0"


def cache_dir() -> str:
    d = os.environ.get("NEXUS_CACHE_DIR") or D.DEFAULT_CACHE
    os.makedirs(d, exist_ok=True)
    return d


# =============================================================================
#  HTTP
# =============================================================================
MAX_ATTEMPTS = 3
_RETRYABLE = {-1, 429, 500, 502, 503, 504, 529}


def http_request(method: str, url: str, headers: dict | None, body: str | None, timeout_s: float,
                 attempts: int | None = None) -> tuple[str | None, int, str | None]:
    """-> (corps, statut, erreur). Le corps est renvoye meme en cas d erreur HTTP ; None si echec reseau."""
    result, status, error = None, -1, None
    n = max(1, attempts or MAX_ATTEMPTS)
    for attempt in range(1, n + 1):
        result, status, error, retry_after = _once(method, url, headers, body, timeout_s)
        if status not in _RETRYABLE or attempt == n:
            break
        time.sleep(min(30, retry_after) if retry_after > 0 else attempt * attempt)
    return result, status, error


def _once(method, url, headers, body, timeout_s):
    h = {"User-Agent": USER_AGENT, "Accept-Encoding": "identity"}
    h.update(headers or {})
    data = body.encode("utf-8") if body is not None else None
    if data is not None and not any(k.lower() == "content-type" for k in h):
        h["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=h, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:
            return resp.read().decode("utf-8", errors="replace"), resp.status, None, 0
    except urllib.error.HTTPError as ex:
        ra = 0
        try:
            ra = int(ex.headers.get("Retry-After") or 0)
        except (TypeError, ValueError):
            pass
        try:
            b = ex.read().decode("utf-8", errors="replace")
        except Exception:
            b = None
        return b, ex.code, f"HTTP {ex.code} " + one_line(b or "", 400), ra
    except Exception as ex:  # reseau, delai, TLS
        return None, -1, f"{type(ex).__name__} {ex}", 0


# =============================================================================
#  Cles API
# =============================================================================
def keys_files() -> list[str]:
    out = []
    if os.environ.get("NEXUS_KEYS_FILE"):
        out.append(os.environ["NEXUS_KEYS_FILE"])
    repo = os.path.normpath(os.path.join(PYTHON_DIR, ".."))
    out += [os.path.join(PYTHON_DIR, "keys.txt"), os.path.join(repo, ".env.txt"), os.path.join(repo, ".env"),
            os.path.join(NT_NEXUS_DIR, "keys.txt")]
    return out


def resolve_secret(value: str | None, env_name: str | None) -> str | None:
    if value and str(value).strip():
        return str(value).strip()
    if not env_name:
        return None
    v = os.environ.get(env_name)
    if v and v.strip():
        return v.strip()
    for path in keys_files():
        try:
            with open(path, encoding="utf-8-sig") as f:
                for line in f:
                    l = line.strip()
                    if l.lower().startswith("export "):
                        l = l[7:].strip()
                    k = l.find("=")
                    if k > 0 and l[:k].strip().lower() == env_name.lower():
                        val = l[k + 1:].strip().strip('"').strip("'")
                        if val:
                            return val
        except OSError:
            continue
    return None


def mask(key: str | None) -> str:
    if not key:
        return "(aucune)"
    return "****" if len(key) <= 8 else key[:4] + "..." + key[-4:]


# =============================================================================
#  LLM
# =============================================================================
PROVIDERS = ("Claude", "DeepSeek", "Gemini", "CompatibleOpenAI")
_PROVIDER_ALIASES = {"claude": "Claude", "anthropic": "Claude", "deepseek": "DeepSeek", "gemini": "Gemini",
                     "google": "Gemini", "openai": "CompatibleOpenAI", "compatibleopenai": "CompatibleOpenAI",
                     "compatible_openai": "CompatibleOpenAI"}


def provider_name(p: str) -> str:
    v = _PROVIDER_ALIASES.get(str(p).strip().lower())
    if v is None:
        raise ValueError(f"fournisseur LLM inconnu '{p}' ({', '.join(PROVIDERS)})")
    return v


def default_env_var(provider: str) -> str:
    return {"Claude": "ANTHROPIC_API_KEY", "DeepSeek": "DEEPSEEK_API_KEY", "Gemini": "GEMINI_API_KEY"}.get(provider, "OPENAI_API_KEY")


def default_model(provider: str) -> str:
    return {"Claude": "claude-opus-5-5", "DeepSeek": "deepseek-chat", "Gemini": "gemini-2.5-flash"}.get(provider, "gpt-4o-mini")


@dataclass
class LlmConfig:
    provider: str = "Claude"
    model: str = "claude-opus-5-5"
    api_key: str | None = None
    endpoint: str = ""                 # vide = point par defaut du fournisseur
    temperature: float = 0.0           # < 0 => parametre omis
    max_tokens: int = 512
    timeout_sec: int = 60
    price_in_per_mtok: float = 0.0     # $ par million de tokens en entree (0 = inconnu)
    price_out_per_mtok: float = 0.0

    @property
    def label(self) -> str:
        return f"{self.provider}:{self.model}"

    @staticmethod
    def build(provider, model="", key="", temperature=0.0, max_tokens=512, timeout_sec=60, price_in=0.0, price_out=0.0,
              endpoint="") -> "LlmConfig":
        p = provider_name(provider)
        return LlmConfig(p, (model or "").strip() or default_model(p), resolve_secret(key, default_env_var(p)),
                         endpoint or "", float(temperature), int(max_tokens), int(timeout_sec), float(price_in), float(price_out))


@dataclass
class LlmResult:
    ok: bool = False
    text: str = ""
    error: str | None = None
    status: int = 0
    in_tokens: int = 0
    out_tokens: int = 0
    cost_usd: float = 0.0
    from_cache: bool = False


def cache_key(cfg: LlmConfig, system: str | None, user: str | None, prompt_version: str | None) -> str:
    return cfg.label + "|" + (prompt_version or "") + "|" + hash10(system or "") + "|" + hash10(user or "")


def complete(cfg: LlmConfig, system: str, user: str, cache: "LlmCache | None", prompt_version: str | None) -> LlmResult:
    """Appel bloquant ; le cache est consulte d abord et alimente apres un succes."""
    key = cache_key(cfg, system, user, prompt_version)
    if cache is not None:
        hit = cache.get(key)
        if hit is not None:
            return LlmResult(True, hit, None, 200, from_cache=True)
    if not cfg.api_key:
        return LlmResult(False, "", f"cle API absente pour {cfg.label} (variable {default_env_var(cfg.provider)})")
    if cfg.provider == "Claude":
        r = _call_claude(cfg, system, user, cfg.temperature >= 0)
    elif cfg.provider == "Gemini":
        r = _call_gemini(cfg, system, user)
    else:
        r = _call_openai_like(cfg, system, user)
    r.cost_usd = (r.in_tokens * cfg.price_in_per_mtok + r.out_tokens * cfg.price_out_per_mtok) / 1e6
    if r.ok and cache is not None and r.text:
        cache.put(key, r.text)
    return r


def _json(body):
    try:
        return json.loads(body) if body else None
    except ValueError:
        return None


def _at(o, path: str):
    """Acces type "choices[0].message.content" (None si absent)."""
    cur = o
    for part in re.findall(r"[^.\[\]]+|\[\d+\]", path):
        if part.startswith("["):
            i = int(part[1:-1])
            cur = cur[i] if isinstance(cur, list) and i < len(cur) else None
        else:
            cur = cur.get(part) if isinstance(cur, dict) else None
        if cur is None:
            return None
    return cur


def _num0(v) -> float:
    try:
        x = float(v)
        return x if M.ok(x) else 0.0
    except (TypeError, ValueError):
        return 0.0


def _call_claude(cfg: LlmConfig, system, user, with_temperature: bool) -> LlmResult:
    url = cfg.endpoint or "https://api.anthropic.com/v1/messages"
    payload = {"model": cfg.model, "max_tokens": max(16, cfg.max_tokens)}
    if with_temperature:
        payload["temperature"] = cfg.temperature
    if system:
        payload["system"] = system
    payload["messages"] = [{"role": "user", "content": user}]
    h = {"x-api-key": cfg.api_key, "anthropic-version": "2023-06-01", "Content-Type": "application/json"}
    body, status, err = http_request("POST", url, h, json.dumps(payload), cfg.timeout_sec)
    root = _json(body)
    r = LlmResult(status=status)
    if status != 200:
        msg = _at(root, "error.message") or err or "erreur inconnue"
        # Certains modeles refusent "temperature" : nouvel essai sans ce parametre.
        if with_temperature and status == 400 and "temperature" in str(msg).lower():
            return _call_claude(cfg, system, user, False)
        r.error = f"Claude HTTP {status} : {msg}"
        return r
    r.text = "".join(c.get("text", "") for c in (_at(root, "content") or []) if isinstance(c, dict) and c.get("type") == "text")
    r.in_tokens = int(_num0(_at(root, "usage.input_tokens")))
    r.out_tokens = int(_num0(_at(root, "usage.output_tokens")))
    r.ok = len(r.text) > 0
    if not r.ok:
        r.error = f"reponse Claude vide (stop_reason={_at(root, 'stop_reason')})"
    return r


def _call_openai_like(cfg: LlmConfig, system, user) -> LlmResult:
    url = cfg.endpoint or ("https://api.deepseek.com/chat/completions" if cfg.provider == "DeepSeek"
                           else "https://api.openai.com/v1/chat/completions")
    payload = {"model": cfg.model, "stream": False, "max_tokens": max(16, cfg.max_tokens)}
    if cfg.temperature >= 0:
        payload["temperature"] = cfg.temperature
    msgs = ([{"role": "system", "content": system}] if system else []) + [{"role": "user", "content": user}]
    payload["messages"] = msgs
    h = {"Authorization": "Bearer " + cfg.api_key, "Content-Type": "application/json"}
    body, status, err = http_request("POST", url, h, json.dumps(payload), cfg.timeout_sec)
    root = _json(body)
    r = LlmResult(status=status)
    if status != 200:
        r.error = f"{cfg.provider} HTTP {status} : {_at(root, 'error.message') or err or 'erreur inconnue'}"
        return r
    r.text = _at(root, "choices[0].message.content") or ""
    r.in_tokens = int(_num0(_at(root, "usage.prompt_tokens")))
    r.out_tokens = int(_num0(_at(root, "usage.completion_tokens")))
    r.ok = len(r.text) > 0
    if not r.ok:
        r.error = "reponse vide"
    return r


def _call_gemini(cfg: LlmConfig, system, user) -> LlmResult:
    url = cfg.endpoint or ("https://generativelanguage.googleapis.com/v1beta/models/"
                           + urllib.parse.quote(cfg.model, safe="") + ":generateContent")
    payload = {}
    if system:
        payload["systemInstruction"] = {"parts": [{"text": system}]}
    payload["contents"] = [{"role": "user", "parts": [{"text": user}]}]
    gen = {"maxOutputTokens": max(16, cfg.max_tokens)}
    if cfg.temperature >= 0:
        gen["temperature"] = cfg.temperature
    payload["generationConfig"] = gen
    h = {"x-goog-api-key": cfg.api_key, "Content-Type": "application/json"}
    body, status, err = http_request("POST", url, h, json.dumps(payload), cfg.timeout_sec)
    root = _json(body)
    r = LlmResult(status=status)
    if status != 200:
        r.error = f"Gemini HTTP {status} : {_at(root, 'error.message') or err or 'erreur inconnue'}"
        return r
    parts = _at(root, "candidates[0].content.parts") or []
    r.text = "".join(p.get("text", "") for p in parts if isinstance(p, dict) and not p.get("thought"))
    r.in_tokens = int(_num0(_at(root, "usageMetadata.promptTokenCount")))
    r.out_tokens = int(_num0(_at(root, "usageMetadata.candidatesTokenCount")) + _num0(_at(root, "usageMetadata.thoughtsTokenCount")))
    r.ok = len(r.text) > 0
    if not r.ok:
        r.error = f"reponse Gemini vide (finishReason={_at(root, 'candidates[0].finishReason')}) : augmenter max_tokens"
    return r


# =============================================================================
#  Cache disque des reponses LLM (cle -> texte en base64, une ligne par reponse)
# =============================================================================
class LlmCache:
    _instances: dict = {}
    _ilock = threading.Lock()

    def __init__(self, path: str, extra_read_paths=()):
        self.path = path
        self.map: dict[str, str] = {}
        self._lock = threading.Lock()
        for p in [*extra_read_paths, path]:
            self._read(p)

    def _read(self, p):
        if not p or not os.path.exists(p):
            return
        with open(p, encoding="utf-8", errors="replace") as f:
            for line in f:
                k = line.find("\t")
                if k <= 0:
                    continue
                try:
                    self.map[line[:k]] = base64.b64decode(line[k + 1:].strip()).decode("utf-8")
                except Exception:
                    continue

    @classmethod
    def get_instance(cls, path: str | None = None, import_ninjatrader: bool = True) -> "LlmCache":
        path = path or os.path.join(cache_dir(), "llm_cache.tsv")
        with cls._ilock:
            c = cls._instances.get(path)
            if c is None:
                extra = [os.path.join(NT_NEXUS_DIR, "cache", "llm_cache.tsv")] if import_ninjatrader else []
                c = cls(path, [p for p in extra if os.path.abspath(p) != os.path.abspath(path)])
                cls._instances[path] = c
            return c

    @property
    def count(self) -> int:
        with self._lock:
            return len(self.map)

    def get(self, key: str) -> str | None:
        with self._lock:
            return self.map.get(key)

    def put(self, key: str, text: str):
        with self._lock:
            if key in self.map:
                return
            self.map[key] = text
            os.makedirs(os.path.dirname(os.path.abspath(self.path)), exist_ok=True)
            with open(self.path, "a", encoding="utf-8", newline="") as f:
                f.write(key + "\t" + base64.b64encode((text or "").encode("utf-8")).decode("ascii") + "\n")


# =============================================================================
#  Journal des couts API (onglet "AI" de Nexus)
# =============================================================================
class AiLedger:
    _totals: dict[str, list[float]] = {}
    _lock = threading.Lock()
    HEADER = ["time_utc", "strategy", "provider", "model", "purpose", "in_tokens", "out_tokens", "cost_usd", "ok", "error"]

    @staticmethod
    def file_path() -> str:
        return os.path.join(cache_dir(), "ai_costs.csv")

    @classmethod
    def record(cls, strategy_id: str, cfg: LlmConfig, r: LlmResult, purpose: str, write_file: bool = True):
        if r is None or r.from_cache:
            return
        with cls._lock:
            t = cls._totals.setdefault(strategy_id, [0.0, 0.0, 0.0, 0.0])
            t[0] += r.in_tokens
            t[1] += r.out_tokens
            t[2] += r.cost_usd
            t[3] += 1
            if write_file:
                p = cls.file_path()
                new = not os.path.exists(p)
                with open(p, "a", encoding="utf-8", newline="") as f:
                    w = csv.writer(f)
                    if new:
                        w.writerow(cls.HEADER)
                    w.writerow([datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"), strategy_id, cfg.provider, cfg.model,
                                purpose, r.in_tokens, r.out_tokens, f"{r.cost_usd:.6f}", 1 if r.ok else 0, one_line(r.error, 200)])

    @classmethod
    def totals(cls, strategy_id: str) -> list[float]:
        """[tokens entree, tokens sortie, cout $, appels] de la strategie depuis le dernier reset."""
        with cls._lock:
            return list(cls._totals.get(strategy_id, [0.0, 0.0, 0.0, 0.0]))

    @classmethod
    def reset(cls, strategy_id: str):
        with cls._lock:
            cls._totals.pop(strategy_id, None)

    @classmethod
    def cost_of(cls, strategy_name: str) -> float:
        """Cout cumule journalise (toutes sessions) pour une strategie."""
        p = cls.file_path()
        if not os.path.exists(p):
            return 0.0
        tot = 0.0
        with open(p, encoding="utf-8") as f:
            for row in csv.DictReader(f):
                if (row.get("strategy") or "").lower() == strategy_name.lower():
                    tot += _num0(row.get("cost_usd"))
        return tot


# =============================================================================
#  Extraction JSON (NxJson.ExtractFirstObject)
# =============================================================================
def extract_first_object(text: str | None) -> dict | None:
    """Premier objet JSON valide du texte (accepte une reponse entouree de prose ou d un bloc de code)."""
    if not text:
        return None
    start = text.find("{")
    while start >= 0:
        depth, in_str, i = 0, False, start
        while i < len(text):
            c = text[i]
            if in_str:
                if c == "\\":
                    i += 2
                    continue
                if c == '"':
                    in_str = False
            elif c == '"':
                in_str = True
            elif c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
                if depth == 0:
                    try:
                        o = json.loads(text[start:i + 1])
                        if isinstance(o, dict):
                            return o
                    except ValueError:
                        pass
                    break
            i += 1
        start = text.find("{", start + 1)
    return None


def _to_bool(v) -> bool:
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)):
        return v != 0
    return str(v).strip().lower() in ("true", "yes", "1", "oui", "vrai")


def _to_float(v) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return M.NAN


# =============================================================================
#  Consignes (prompts) et analyse des reponses - textes IDENTIQUES au C# (cles de cache partagees)
# =============================================================================
class Prompts:
    VERSION = "nx-v1"

    HEADLINE_SYSTEM = ("You are a financial expert with stock and crypto recommendation experience. "
                       "You judge only the short-term (next trading day) price impact of a single headline on the named asset. "
                       "Follow the requested output format exactly.")

    @staticmethod
    def _name(symbol, company):
        return symbol if not (company or "").strip() else f"{company} ({symbol})"

    @staticmethod
    def headline3(symbol: str, company: str, headline: str, context: str) -> str:
        """Fiches 7 et 10 : bon / mauvais / sans effet (Lopez-Lira et Tang)."""
        return ("Is this headline good, bad, or of no effect for the price of " + Prompts._name(symbol, company) + " in the short term?\n"
                + "Headline: \"" + headline + "\"\n"
                + ("" if not (context or "").strip() else "Context: " + context + "\n")
                + "Answer on the first line with exactly one word: GOOD, BAD or NONE.\n"
                + "On the second line, give one short sentence of justification.")

    @staticmethod
    def parse_label3(text: str | None) -> int | None:
        """+1 / -1 / 0 ; None si illisible."""
        if not text or not text.strip():
            return None
        first = text.strip().split("\n")[0].strip().strip("*\"'.: ").upper()
        # Les mots neutres d abord ("NO EFFECT" commence par "NO").
        if first.startswith(("NONE", "UNKNOWN", "NEUTRAL", "SANS", "NO EFFECT", "IRRELEVANT")):
            return 0
        if first.startswith(("GOOD", "YES", "BON", "POSITIVE")):
            return 1
        if first.startswith(("BAD", "NO ", "MAUVAIS", "NEGATIVE")) or first == "NO":
            return -1
        m = re.search(r"\b(GOOD|BAD|NONE)\b", text.upper())
        if m:
            return {"GOOD": 1, "BAD": -1, "NONE": 0}[m.group(1)]
        return None

    @staticmethod
    def headline5(symbol: str, company: str, headline: str, context: str) -> str:
        """Fiche 9 : entier de -2 (tres mauvais) a +2 (tres bon)."""
        return ("Rate the likely short-term (next trading day) impact of this headline on the price of " + Prompts._name(symbol, company)
                + " on an integer scale from -2 (very bad) to +2 (very good), where 0 means no effect.\n"
                + "Headline: \"" + headline + "\"\n"
                + ("" if not (context or "").strip() else "Context: " + context + "\n")
                + "Answer on the first line with only the integer (-2, -1, 0, 1 or 2).\n"
                + "On the second line, give one short sentence of justification.")

    @staticmethod
    def parse_score5(text: str | None) -> int | None:
        if not text or not text.strip():
            return None
        m = re.match(r"^[\s*\"']*([+-]?\s?[0-2])\b", text.strip())
        if not m:
            m = re.search(r"(?<!\d)([+-]?[0-2])(?!\d)", text)
        if not m:
            return None
        try:
            v = int(m.group(1).replace(" ", ""))
        except ValueError:
            return None
        return v if -2 <= v <= 2 else None

    JUDGE_SYSTEM = ("You are a strict risk officer acting as a strict pessimist. A quantitative momentum model has ALREADY selected this trade. "
                    "You can only BLOCK it; you can never create a trade or increase its size. Look for what price-based models cannot see: "
                    "litigation, guidance cuts or forecast revisions, regulatory or criminal investigations, share dilution or large equity offerings, "
                    "management changes (CEO/CFO departure), mergers and acquisitions, accounting problems, earnings imminent within the holding period. "
                    "If the provided information contains no concrete evidence of such a risk, do not veto. Output strict JSON only.")

    @staticmethod
    def judge_user(symbol: str, company: str, source: str, horizon_days: int, day, next_earnings: str, headlines) -> str:
        sb = ["Candidate trade: BUY ", Prompts._name(symbol, company), ", source: ", source,
              ", expected holding period about ", str(horizon_days), " trading days.\n",
              "Decision date: ", pd_date(day), "\n",
              "Next earnings date: ", next_earnings if next_earnings else "unknown", "\n",
              "Headlines from the last 7 days (UTC time | source | title):\n"]
        if not headlines:
            sb.append("(none)\n")
        else:
            for h in sorted(headlines, key=lambda x: x.published_utc)[:40]:
                sb += ["- ", h.published_utc.strftime("%Y-%m-%d %H:%M"), " | ", h.source, " | ", one_line(h.headline, 250), "\n"]
        sb.append("\nRespond with strict JSON only, no prose and no code fence: ")
        sb.append("{\"veto\": true or false, \"reason\": \"one sentence\", \"confidence\": number between 0 and 1}")
        return "".join(sb)

    @staticmethod
    def risk_rank_user(symbol: str, company: str, source: str, day, next_earnings: str, headlines) -> str:
        u = Prompts.judge_user(symbol, company, source, 21, day, next_earnings, headlines)
        k = u.rfind("Respond with strict JSON")
        if k > 0:
            u = u[:k]
        return u + ("Rate the event risk of this long trade. Respond with strict JSON only: "
                    "{\"risk\": number between 0 (no identifiable risk) and 1 (severe risk), \"reason\": \"one sentence\"}")

    @staticmethod
    def parse_judge(text: str | None):
        """-> (veto, raison, confiance) ou None si illisible."""
        o = extract_first_object(text)
        if o is None:
            return None
        veto = _to_bool(o.get("veto", False))
        reason = str(o.get("reason") or "")
        conf = _to_float(o.get("confidence"))
        if not M.ok(conf):
            conf = 1.0 if veto else 0.0
        return veto, reason, M.clamp(conf, 0.0, 1.0)

    @staticmethod
    def parse_risk(text: str | None):
        """-> (risque 0..1, raison) ou None."""
        o = extract_first_object(text)
        if o is None:
            return None
        risk = _to_float(o.get("risk"))
        if not M.ok(risk):
            return None
        return M.clamp(risk, 0.0, 1.0), str(o.get("reason") or "")

    MACRO_SYSTEM = ("You are an event-risk filter for a systematic multi-horizon trend-following strategy on FX, gold and equity index CFDs "
                    "traded under prop-firm drawdown rules. You can only veto a new position, never create or enlarge one. Output strict JSON only.")

    @staticmethod
    def macro_user(symbol: str, direction: int, utc: datetime, events) -> str:
        sb = ["New position: ", "LONG " if direction > 0 else "SHORT ", symbol, " at ", utc.strftime("%Y-%m-%d %H:%M"), " UTC.\n",
              "Scheduled macro events within one hour of entry:\n"]
        if not events:
            sb.append("(none)\n")
        else:
            for e in events:
                sb += ["- ", str(e), "\n"]
        sb.append("Should this new position be vetoed because of event risk (central bank decision, major macro release within the hour)?\n")
        sb.append("Respond with strict JSON only: {\"veto\": true or false, \"reason\": \"one sentence\", \"confidence\": number between 0 and 1}")
        return "".join(sb)

    AUDIT_SYSTEM = ("You are a skeptical quantitative reviewer auditing a backtest report produced by an automated trading strategy. "
                    "Identify methodological flaws: look-ahead bias, tautological filters, survivorship bias, data snooping, too few trades, "
                    "unrealistic costs or fills, overfitting, regime dependence. Answer in French, as at most 15 short bullet points, most serious first.")

    @staticmethod
    def audit_user(report: str) -> str:
        return "Rapport a auditer :\n\n" + report


def pd_date(day) -> str:
    import pandas as pd
    return pd.Timestamp(day).strftime("%Y-%m-%d")


# =============================================================================
#  FinBERT (fiche 10) : serveur local (Tools/finbert_server.py) ou modele en memoire
#  Protocole serveur : POST {"texts": [...]} -> {"results": [{"positive":p,"negative":n,"neutral":z}, ...]}
# =============================================================================
class FinBert:
    def __init__(self, url: str = "http://127.0.0.1:8765/score", cache_path: str | None = None, mode: str = "auto",
                 model_name: str = "ProsusAI/finbert", timeout_s: float = 30.0, batch_size: int = 32):
        """mode : serveur (HTTP) | local (transformers en memoire) | auto (serveur, puis local si joignable echoue)."""
        self.url = url
        self.mode = mode
        self.model_name = model_name
        self.timeout_s = timeout_s
        self.batch_size = batch_size
        self.cache_path = cache_path or os.path.join(cache_dir(), "finbert_cache.csv")
        self.cache: dict[str, tuple] = {}
        self._lock = threading.Lock()
        self._pipe = None
        self._local_error = None
        self._server_down = False
        for p in [os.path.join(NT_NEXUS_DIR, "cache", "finbert_cache.csv"), self.cache_path]:
            self._read(p)

    def _read(self, p):
        if not p or not os.path.exists(p):
            return
        with open(p, encoding="utf-8") as f:
            for row in csv.DictReader(f):
                try:
                    self.cache[row["key"]] = (float(row["positive"]), float(row["negative"]), float(row["neutral"]))
                except (KeyError, TypeError, ValueError):
                    continue

    @staticmethod
    def key_of(text: str) -> str:
        return hash10("finbert|" + normalize(text))

    @staticmethod
    def score_of(p) -> float:
        """Score fiche 10 : P(positif) - P(negatif), entre -1 et +1."""
        return M.NAN if p is None else p[0] - p[1]

    def cached(self, text: str):
        with self._lock:
            return self.cache.get(self.key_of(text))

    def _store(self, text: str, p: tuple):
        key = self.key_of(text)
        with self._lock:
            if key in self.cache:
                return
            self.cache[key] = p
            os.makedirs(os.path.dirname(os.path.abspath(self.cache_path)), exist_ok=True)
            new = not os.path.exists(self.cache_path)
            with open(self.cache_path, "a", encoding="utf-8", newline="") as f:
                if new:
                    f.write("key,positive,negative,neutral\n")
                f.write(f"{key},{p[0]:.6f},{p[1]:.6f},{p[2]:.6f}\n")

    def _score_server(self, texts: list[str]):
        out = []
        for i in range(0, len(texts), self.batch_size):
            batch = texts[i:i + self.batch_size]
            body, status, err = http_request("POST", self.url, {"Content-Type": "application/json"},
                                             json.dumps({"texts": batch}), self.timeout_s, attempts=1)
            root = _json(body)
            res = _at(root, "results") if root is not None else None
            if body is None or status != 200 or not isinstance(res, list) or len(res) != len(batch):
                raise RuntimeError(f"serveur FinBERT injoignable ({self.url}) : {err or ('HTTP ' + str(status))}")
            out += [(_num0(r.get("positive")), _num0(r.get("negative")), _num0(r.get("neutral"))) for r in res]
        return out

    def _score_local(self, texts: list[str]):
        if self._pipe is None:
            if self._local_error:
                raise RuntimeError(self._local_error)
            try:
                from transformers import pipeline  # type: ignore
                self._pipe = pipeline("text-classification", model=self.model_name, top_k=None, truncation=True)
            except Exception as ex:
                self._local_error = (f"FinBERT local indisponible ({type(ex).__name__}: {ex}) - "
                                     "pip install transformers torch, ou lancer Tools/finbert_server.py")
                raise RuntimeError(self._local_error)
        out = []
        for i in range(0, len(texts), self.batch_size):
            for res in self._pipe(texts[i:i + self.batch_size]):
                d = {x["label"].lower(): float(x["score"]) for x in res}
                out.append((d.get("positive", 0.0), d.get("negative", 0.0), d.get("neutral", 0.0)))
        return out

    def score(self, texts: list[str], allow_compute: bool = True):
        """-> (probabilites [positif, negatif, neutre] ou None par texte, erreur). Calcule les textes non caches."""
        probs = [self.cached(t) for t in texts]
        missing = [i for i, p in enumerate(probs) if p is None]
        if not missing:
            return probs, None
        if not allow_compute:
            return probs, f"{len(missing)} titres non scores (cache FinBERT)"
        todo = [texts[i] for i in missing]
        res, err = None, None
        if self.mode in ("serveur", "auto") and not self._server_down:
            try:
                res = self._score_server(todo)
            except RuntimeError as ex:
                err = str(ex)
                if self.mode == "auto":
                    self._server_down = True
        if res is None and self.mode in ("local", "auto"):
            try:
                res = self._score_local(todo)
                err = None
            except RuntimeError as ex:
                err = (err + " ; " if err else "") + str(ex)
        if res is None:
            return probs, err
        for i, p in zip(missing, res):
            probs[i] = p
            self._store(texts[i], p)
        return probs, None


# =============================================================================
#  Collecte (commande "actualites")
# =============================================================================
def _parse_iso(s):
    import pandas as pd
    try:
        t = pd.Timestamp(s)
    except (TypeError, ValueError):
        return None
    if t is pd.NaT:
        return None
    if t.tzinfo is not None:
        t = t.tz_convert("UTC").tz_localize(None)
    return t.to_pydatetime()


def fetch_newsapi_batch(api_key: str | None, symbol_to_query: dict, from_utc: datetime):
    """NewsAPI groupe : une requete "nom1 OR nom2 OR ..." ; chaque article est attribue aux symboles
    dont le nom (ou le ticker) figure dans le titre ou la description. -> (titres, erreur)."""
    res: list[NewsItem] = []
    if not api_key:
        return res, "cle NewsAPI absente"
    if not symbol_to_query:
        return res, None
    q = " OR ".join(f'"{v}"' if " " in v else v for v in symbol_to_query.values())
    url = ("https://newsapi.org/v2/everything?q=" + urllib.parse.quote(q) + "&language=en&sortBy=publishedAt&pageSize=100"
           "&searchIn=title,description&from=" + urllib.parse.quote(from_utc.strftime("%Y-%m-%dT%H:%M:%S")))
    body, status, err = http_request("GET", url, {"X-Api-Key": api_key}, None, 20)
    root = _json(body)
    if root is None:
        return res, err or "reponse NewsAPI illisible"
    if status != 200:
        return res, f"NewsAPI HTTP {status} {root.get('message', '')}"
    for a in root.get("articles") or []:
        title = a.get("title")
        t = _parse_iso(a.get("publishedAt"))
        if not title or title == "[Removed]" or t is None:
            continue
        text = title + " " + (a.get("description") or "")
        for sym, name in symbol_to_query.items():
            by_name = name.lower() in text.lower()
            by_ticker = len(sym) >= 2 and re.search(r"(?<![A-Za-z])\$?" + re.escape(sym) + r"(?![A-Za-z])", text) is not None
            if by_name or by_ticker:
                res.append(NewsItem(t, sym, "newsapi:" + (_at(a, "source.name") or ""), title, a.get("url") or ""))
    return res, None


def fetch_reddit(symbol: str, subreddits, hours: int = 24):
    """Titres de posts Reddit (recherche par symbole dans les subreddits donnes, 24 h). -> (titres, erreur)."""
    res, error = [], None
    for sub in subreddits:
        url = ("https://www.reddit.com/r/" + urllib.parse.quote(sub.strip()) + "/search.json?q=" + urllib.parse.quote(symbol)
               + "&restrict_sr=1&sort=new&t=day&limit=25")
        body, status, err = http_request("GET", url, {"User-Agent": USER_AGENT + " (research)"}, None, 20)
        root = _json(body)
        if root is None or status != 200:
            error = err or f"Reddit HTTP {status}"
            continue
        for c in _at(root, "data.children") or []:
            ts, title = _at(c, "data.created_utc"), _at(c, "data.title")
            if ts is None or not title:
                continue
            res.append(NewsItem(datetime.fromtimestamp(float(ts), tz=timezone.utc).replace(tzinfo=None), symbol,
                                "reddit:r/" + sub.strip(), title, "https://www.reddit.com" + (_at(c, "data.permalink") or "")))
    return res, error


def fetch_alpha_vantage_earnings(api_key: str | None, path: str):
    """Ajoute au fichier des resultats le calendrier Alpha Vantage (EARNINGS_CALENDAR, 3 mois). -> (lignes ajoutees, erreur)."""
    if not api_key:
        return 0, "cle Alpha Vantage absente"
    body, status, err = http_request("GET", "https://www.alphavantage.co/query?function=EARNINGS_CALENDAR&horizon=3month&apikey="
                                     + urllib.parse.quote(api_key), None, None, 30)
    if body is None or status != 200 or not body.lower().startswith("symbol"):
        return 0, err or f"reponse inattendue HTTP {status}"
    existing = set()
    if os.path.exists(path):
        e = D.Earnings(path)
        existing = {f"{s}|{d:%Y-%m-%d}" for s, l in e.dates.items() for d in l}
    rows = []
    for rec in csv.reader(body.splitlines()[1:]):
        if len(rec) < 3:
            continue
        t = _parse_iso(rec[2])
        if t is None:
            continue
        key = f"{rec[0].upper()}|{t:%Y-%m-%d}"
        if key in existing:
            continue
        existing.add(key)
        rows.append(f"{rec[0]},{t:%Y-%m-%d}")
    if rows:
        new = not os.path.exists(path)
        with open(path, "a", encoding="utf-8", newline="") as f:
            if new:
                f.write("symbol,date\n")
            f.write("\n".join(rows) + "\n")
    return len(rows), None
