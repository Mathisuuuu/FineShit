"""
finbert_server.py - Serveur FinBERT local pour les strategies Nexus (fiche 10, et
pre-filtre des fiches 7 et 9).

FinBERT (Araci, arXiv 1908.10063) : BERT pre-entraine sur un corpus financier et
affine sur le sentiment. Gratuit, execute en local (sur le VPS), sans cout par appel.

Protocole (attendu par NxFinBertClient dans AddOns/NexusLlm.cs) :
    POST http://127.0.0.1:8765/score
    corps   : {"texts": ["titre 1", "titre 2", ...]}
    reponse : {"results": [{"positive": p, "negative": n, "neutral": z}, ...]}
    GET  /health -> {"status": "ok", "model": "..."}

Installation (une fois) :
    python -m pip install torch transformers
Lancement :
    python finbert_server.py                 (modele ProsusAI/finbert, port 8765)
    python finbert_server.py --port 8765 --model ProsusAI/finbert --device cpu

Aucune dependance web supplementaire : serveur HTTP de la bibliotheque standard.
Ecoute uniquement sur 127.0.0.1 (pas d exposition reseau).
"""

import argparse
import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

try:
    import torch
    from transformers import AutoModelForSequenceClassification, AutoTokenizer
except ImportError:  # message clair si les dependances manquent
    sys.stderr.write("Dependances manquantes : python -m pip install torch transformers\n")
    raise

MODEL = None
TOKENIZER = None
LABELS = None
DEVICE = "cpu"
LOCK = threading.Lock()
MAX_BATCH = 64
MAX_TEXTS = 512


def load(model_name, device):
    global MODEL, TOKENIZER, LABELS, DEVICE
    DEVICE = device
    TOKENIZER = AutoTokenizer.from_pretrained(model_name)
    MODEL = AutoModelForSequenceClassification.from_pretrained(model_name).to(device)
    MODEL.eval()
    # ProsusAI/finbert : id2label = {0: positive, 1: negative, 2: neutral}
    LABELS = {i: str(l).lower() for i, l in MODEL.config.id2label.items()}
    print("FinBERT charge :", model_name, "labels", LABELS, "device", device, flush=True)


def score(texts):
    results = []
    with LOCK, torch.no_grad():
        for start in range(0, len(texts), MAX_BATCH):
            chunk = [str(t)[:1000] for t in texts[start:start + MAX_BATCH]]
            enc = TOKENIZER(chunk, padding=True, truncation=True, max_length=128, return_tensors="pt").to(DEVICE)
            probs = torch.softmax(MODEL(**enc).logits, dim=-1).cpu().tolist()
            for p in probs:
                d = {"positive": 0.0, "negative": 0.0, "neutral": 0.0}
                for i, v in enumerate(p):
                    name = LABELS.get(i, str(i))
                    if name in d:
                        d[name] = float(v)
                results.append(d)
    return results


class Handler(BaseHTTPRequestHandler):
    def _send(self, code, obj):
        body = json.dumps(obj).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path.rstrip("/") == "/health":
            self._send(200, {"status": "ok", "model": MODEL.config.name_or_path if MODEL else None})
        else:
            self._send(404, {"error": "inconnu"})

    def do_POST(self):
        if self.path.rstrip("/") != "/score":
            self._send(404, {"error": "inconnu"})
            return
        try:
            n = int(self.headers.get("Content-Length", "0"))
            payload = json.loads(self.rfile.read(n).decode("utf-8") or "{}")
            texts = payload.get("texts", [])
            if not isinstance(texts, list) or len(texts) > MAX_TEXTS:
                self._send(400, {"error": "texts doit etre une liste de %d elements au plus" % MAX_TEXTS})
                return
            self._send(200, {"results": score(texts)})
        except Exception as ex:  # reponse d erreur lisible par le client C#
            self._send(500, {"error": str(ex)})

    def log_message(self, fmt, *args):
        pass  # silencieux


def main():
    ap = argparse.ArgumentParser(description="Serveur FinBERT local (Nexus fiche 10)")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--model", default="ProsusAI/finbert")
    ap.add_argument("--device", default="cuda" if torch.cuda.is_available() else "cpu")
    args = ap.parse_args()
    load(args.model, args.device)
    srv = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    print("Serveur FinBERT : http://127.0.0.1:%d/score  (Ctrl+C pour arreter)" % args.port, flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
