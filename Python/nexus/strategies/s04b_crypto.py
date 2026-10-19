"""FICHE 4 variante B - Retournement intraday crypto 15 min (port de Strategies/Nexus04B_CryptoIntradayReversal.cs).

[arXiv] 2608.21888 (Kitron, Wengrowicz 2026). Retour a la moyenne significatif sur ~90 % des paires Binance
a 15 min, mais avantage brut ~0.013 %/trade contre 0.2 % de frais aller-retour.
REGLE DE SURVIE : perdante seule aux frais standard -> mode "filtre_seulement" recommande.

REGLES
  - Barre 15 min ; z = rendement de la derniere barre / ecart-type des 96 barres precedentes (24 h).
  - Flux : volume taker VENDEUR > 60 % sur la barre de choc. Sources :
      klines        colonne taker_buy_volume des klines Binance (part vendeuse = 1 - taker_buy / volume) ;
      transactions  fichiers de transactions par symbole (trades_folder) : drapeau is_buyer_maker s il existe
                    (exact), sinon regle du tick (Lee-Ready : hausse = acheteur agressif, baisse = vendeur,
                    prix inchange = meme sens que la transaction precedente) ;
      desactive     condition de flux ignoree.
  - Entree long : z < -2 ET flux vendeur > 60 % ; ordre LIMITE maker au cours de cloture de la barre de choc
    (valable 1 barre) ou au marche (pire cas).
  - Sortie : limite au milieu de la barre de choc, ou au marche apres 4 barres.
  - Couts : 0.1 %/ordre (0.075 % avec BNB) + glissement (module C).
  - Mode filtre_seulement : aucun ordre ; chaque choc est publie (signaux + chocs.csv) et son AVANTAGE A TERME
    est mesure : rendement apres N barres, taux de retour au milieu, trade theorique maker (entree limite a la
    cloture du choc, sortie au milieu ou a N barres) compare aux frais.

Quantites crypto : unites de crypto_unit (0.0001 piece par defaut, voir le moteur).
"""
from __future__ import annotations

import glob
import math
import os

import numpy as np
import pandas as pd

from .. import mathx as M
from .. import signals as S
from ..engine import NexusStrategy

CRYPTO_20 = ("BTCUSD,ETHUSD,SOLUSD,XRPUSD,ADAUSD,DOGEUSD,AVAXUSD,LINKUSD,DOTUSD,LTCUSD,BCHUSD,UNIUSD,XLMUSD,ATOMUSD,"
             "ETCUSD,FILUSD,AAVEUSD,ALGOUSD,NEARUSD,SHIBUSD")


def taker_sell_share_from_trades(df: pd.DataFrame, minutes: int) -> pd.Series:
    """Part du volume taker vendeur par barre (index = FIN de barre, un tick pile sur la frontiere appartient a
    la barre suivante). Colonnes : time (ou timestamp / transact_time), price, quantity (ou qty / volume),
    is_buyer_maker optionnelle (True = l acheteur est maker -> le vendeur est l agresseur)."""
    cols = {c.lower().strip(): c for c in df.columns}
    ct = next((cols[k] for k in ("time", "timestamp", "transact_time", "datetime", "date") if k in cols), None)
    cp = next((cols[k] for k in ("price", "prix") if k in cols), None)
    cq = next((cols[k] for k in ("quantity", "qty", "volume", "size", "amount") if k in cols), None)
    if ct is None or cp is None or cq is None:
        raise ValueError("colonnes requises : time, price, quantity (is_buyer_maker optionnelle)")
    raw = df[ct]
    if pd.api.types.is_numeric_dtype(raw):
        v = raw.astype("int64")
        unit = "us" if v.abs().max() > 1e14 else ("ms" if v.abs().max() > 1e11 else "s")
        t = pd.to_datetime(v, unit=unit)
    else:
        t = pd.to_datetime(raw, utc=True, errors="coerce").dt.tz_convert("UTC").dt.tz_localize(None)
    px = pd.to_numeric(df[cp], errors="coerce").to_numpy(float)
    q = pd.to_numeric(df[cq], errors="coerce").to_numpy(float)
    order = np.argsort(t.to_numpy(), kind="stable")
    t, px, q = t.to_numpy()[order], px[order], q[order]
    cm = cols.get("is_buyer_maker") or cols.get("isbuyermaker")
    if cm is not None:
        m = df[cm].astype(str).str.strip().str.lower().isin(("true", "1", "yes")).to_numpy()[order]
        sign = np.where(m, -1, 1)
    else:
        # Regle du tick : +1 hausse, -1 baisse, inchange = signe precedent ; premier tick sans signe.
        d = np.sign(np.diff(px, prepend=np.nan))
        d[~np.isfinite(d)] = 0
        s = pd.Series(np.where(d == 0, np.nan, d)).ffill().fillna(0).to_numpy()
        sign = s.astype(int)
    ok = (sign != 0) & np.isfinite(q) & (q > 0) & ~pd.isna(t)
    span = pd.Timedelta(minutes=max(1, int(minutes)))
    ends = pd.DatetimeIndex(t[ok]).floor(span) + span
    vol = pd.DataFrame({"end": ends, "buy": np.where(sign[ok] > 0, q[ok], 0.0), "sell": np.where(sign[ok] < 0, q[ok], 0.0)})
    g = vol.groupby("end").sum()
    tot = g["buy"] + g["sell"]
    return (g["sell"] / tot).where(tot > 0)


class Nexus04BCryptoIntradayReversal(NexusStrategy):
    NAME = "Nexus04B_CryptoIntradayReversal"
    DESCRIPTION = ("Fiche 4B - Retournement crypto 15 min : z < -2 et flux taker vendeur > 60 %, entree limite maker, sortie au milieu "
                   "de la barre de choc ou apres 4 barres. Mode filtre recommande (mesure de l avantage a terme).")
    BATCH_MODE = False
    DEFAULTS = dict(
        symbols=CRYPTO_20,
        sizing_mode="demi_kelly",
        max_class_pct=30.0,
        stop_mode="logiciel",
        mode="filtre_seulement",            # filtre_seulement (recommande) | strategie
        bar_minutes=15,
        z_window_bars=96,
        z_entry=2.0,
        taker_source="klines",              # klines | transactions | desactive
        trades_folder="",                   # transactions par symbole (SYMBOLE*.csv / .parquet) si taker_source=transactions
        taker_sell_threshold_pct=60.0,
        entry_type="limite_maker",          # limite_maker | marche
        hold_bars=4,
        exit_at_shock_mid=True,
        shock_publish_minutes=60,
        use_atr_stop=False,
        atr_multiplier=3.0,
        shocks_file="",                     # export des chocs (time_utc,symbol,z,sell_share,mid,until_utc) ; vide = aucun
    )

    def bar_minutes(self) -> int:
        return max(1, int(self.p.bar_minutes))

    def on_data_loaded(self):
        p = self.p
        if p.mode not in ("filtre_seulement", "strategie"):
            raise ValueError("mode : filtre_seulement | strategie")
        self.shocks: dict[str, dict] = {}
        self.shock_rows: list[tuple] = []
        self.pending_fwd: list[dict] = []
        self.fwd_returns: list[float] = []
        self.fwd_mid_touch: list[bool] = []
        self.fwd_theoretical: list[float] = []
        self.shock_count = self.z_only_count = self.entries_submitted = self.mid_exits = self.time_exits = 0
        self.no_flow_bars = 0
        self.trade_shares: dict[str, pd.Series] = {}
        if p.taker_source == "transactions":
            self._load_trades()
        elif p.taker_source == "klines":
            missing = [s.name for s in self.traded_syms if "taker_buy_volume" not in s.hist.extra]
            if missing:
                self.nx("ATTENTION : pas de colonne taker_buy_volume (klines Binance) pour " + ", ".join(missing)
                        + " -> flux inconnu, aucun choc retenu (taker_source=desactive pour ignorer le flux).")

    def _load_trades(self):
        p = self.p
        if not p.trades_folder or not os.path.isdir(p.trades_folder):
            self.nx(f"taker_source=transactions mais dossier introuvable : '{p.trades_folder}'")
            return
        files = glob.glob(os.path.join(p.trades_folder, "*"))
        for s in self.traded_syms:
            key = s.name.upper().replace("USD", "")
            cand = [f for f in files if os.path.basename(f).upper().replace("-", "").replace("_", "").startswith((s.name.upper(), key + "USDT", key + "USD"))]
            if not cand:
                continue
            frames = []
            for f in sorted(cand):
                try:
                    frames.append(pd.read_parquet(f) if f.lower().endswith(".parquet") else pd.read_csv(f))
                except Exception as ex:
                    self.nx(f"Lecture impossible {f} : {ex}")
            if frames:
                try:
                    self.trade_shares[s.name] = taker_sell_share_from_trades(pd.concat(frames, ignore_index=True), self.bar_minutes())
                    self.nx(f"Flux taker {s.name} : {len(self.trade_shares[s.name])} barres depuis {len(frames)} fichier(s) de transactions")
                except ValueError as ex:
                    self.nx(f"Transactions {s.name} : {ex}")

    def sell_share(self, s, k: int) -> float:
        p = self.p
        if p.taker_source == "klines":
            tb = s.hist.extra.get("taker_buy_volume")
            vol = float(s.hist.volume[k])
            if tb is None or not M.ok(tb[k]) or not vol > 0:
                return M.NAN
            return M.clamp(1.0 - float(tb[k]) / vol, 0.0, 1.0)
        if p.taker_source == "transactions":
            ser = self.trade_shares.get(s.name)
            if ser is None:
                return M.NAN
            v = ser.get(s.hist.dates[k], np.nan)
            return float(v) if M.ok(v) else M.NAN
        return M.NAN

    def _resolve_forward(self, s):
        """Avantage a terme des chocs passes de ce symbole (barres suivantes desormais connues)."""
        h, p = s.hist, self.p
        keep = []
        for f in self.pending_fwd:
            if f["sym"] != s.name or h.count - 1 < f["k"] + p.hold_bars:
                keep.append(f)
                continue
            k, c, mid = f["k"], f["close"], f["mid"]
            end = k + p.hold_bars
            self.fwd_returns.append(float(h.close[end]) / c - 1)
            hi = float(np.max(h.high[k + 1:end + 1]))
            self.fwd_mid_touch.append(hi >= mid)
            # Trade theorique de la fiche : limite maker a la cloture du choc (remplie si la barre suivante passe dessous),
            # puis limite de sortie au milieu (active des la barre d apres, comme dans le moteur), sinon cloture de la N-ieme barre.
            if float(h.low[k + 1]) < c:
                ex_px = float(h.close[end])
                for i in range(k + 2, end + 1):
                    if float(h.high[i]) >= mid:
                        ex_px = mid
                        break
                self.fwd_theoretical.append(ex_px / c - 1)
        self.pending_fwd = keep

    def on_symbol_bar(self, s, day):
        if not s.traded:
            return
        p = self.p
        h = s.hist
        n = h.count
        self._resolve_forward(s)

        # --- Position ouverte : 4 barres max, ou retour au milieu de la barre de choc.
        if s.qty > 0:
            si = self.shocks.get(s.name)
            if s.bars_held >= p.hold_bars:
                self.set_target(s, 0, M.NAN, f"{p.hold_bars} barres ecoulees")
                self.time_exits += 1
                return
            if p.exit_at_shock_mid and si is not None and M.ok(si["mid"]) and s.target_qty != 0:
                self.set_target(s, 0, s.stop_price, "retour au milieu de la barre de choc", "limit", si["mid"],
                                max(1, p.hold_bars - s.bars_held))
                self.mid_exits += 1
            return
        if n < p.z_window_bars + 2:
            return

        # --- Detection du choc.
        r = h.log_return_at(n - 1)
        prev = h.logret[n - 1 - p.z_window_bars:n - 1]
        sd = M.std(prev)
        if not M.ok(r) or not M.ok(sd) or sd <= 0:
            return
        z = r / sd
        if z >= -p.z_entry:
            return
        self.z_only_count += 1
        share = self.sell_share(s, n - 1)
        if p.taker_source != "desactive" and not M.ok(share):
            self.no_flow_bars += 1
        flow_ok = p.taker_source == "desactive" or (M.ok(share) and share > p.taker_sell_threshold_pct / 100.0)
        if not flow_ok:
            return
        self.shock_count += 1
        mid = 0.5 * (float(h.high[n - 1]) + float(h.low[n - 1]))
        t_end = h.dates[n - 1]
        self.shocks[s.name] = {"mid": mid, "time": t_end}
        share_txt = f"{share:.0%}" if M.ok(share) else "n/d"
        why = f"choc z={z:.2f} flux vendeur {share_txt} milieu {mid:.6g}"
        self.signal(self.now, s.name, "choc_taker", why)
        self.shock_rows.append((t_end, s.name, z, share, mid, t_end + pd.Timedelta(minutes=p.shock_publish_minutes)))
        self.pending_fwd.append({"sym": s.name, "k": n - 1, "close": float(h.close[n - 1]), "mid": mid})
        if p.mode == "filtre_seulement" or s.target_qty != 0:
            return

        q, _ = self.size_qty(s, self.kelly_native_fraction(), s.last_price)
        stop = S.long_stop(s.last_price, h.atr, p.atr_multiplier, 0.002, 0.20) if p.use_atr_stop else M.NAN
        if p.entry_type == "limite_maker":
            self.set_target(s, q, stop, why, "limit", s.last_price, 1)
        else:
            self.set_target(s, q, stop, why)
        if q > 0:
            self.entries_submitted += 1

    def report_extras(self, lines):
        p = self.p
        rt_cost = 2 * (self.costs.slippage_pct + self.costs.fee_pct("Crypto")) / 100.0
        lines.append(f"Mode : {p.mode} | flux taker : {p.taker_source} | entree : {p.entry_type} | barres {self.bar_minutes()} min")
        lines.append(f"Barres z < -{p.z_entry} : {self.z_only_count} | chocs avec flux vendeur > {p.taker_sell_threshold_pct}% : "
                     f"{self.shock_count} | entrees soumises : {self.entries_submitted} | trades fermes : {len(self.closed_trades)}"
                     + (f" | barres z<-2 sans flux connu : {self.no_flow_bars}" if self.no_flow_bars else ""))
        if self.entries_submitted > 0:
            lines.append(f"Taux de remplissage des entrees : {len(self.closed_trades) / self.entries_submitted:.0%} (limites maker)")
        if self.closed_trades:
            g = float(np.mean([t.gross_return for t in self.closed_trades]))
            net = float(np.mean([t.net_return for t in self.closed_trades]))
            lines.append(f"Avantage brut moyen {g:.3%}/trade, net {net:.3%}/trade, cout aller-retour modelise {rt_cost:.3%}")
            lines.append("REGLE DE SURVIE : l avantage brut ne couvre pas les frais -> utiliser le mode filtre_seulement." if g < rt_cost
                         else "L avantage brut couvre les frais modelises sur cet echantillon (verifier la significativite).")
        lines.append(f"Sorties : au milieu de la barre de choc {self.mid_exits} ordres, au temps {self.time_exits}")
        # --- Avantage a terme des chocs (les deux modes).
        fr = np.array(self.fwd_returns)
        if fr.size:
            t = fr.mean() / (fr.std(ddof=1) / math.sqrt(fr.size)) if fr.size > 1 and fr.std(ddof=1) > 0 else M.NAN
            lines.append(f"Avantage a terme des chocs ({fr.size} resolus) : rendement moyen a {p.hold_bars} barres {fr.mean():.3%} "
                         f"(t = {t:.2f}), retour au milieu de la barre de choc {np.mean(self.fwd_mid_touch):.0%}")
            th = np.array(self.fwd_theoretical)
            if th.size:
                lines.append(f"Trade theorique maker (limite a la cloture, sortie milieu / {p.hold_bars} barres) : {th.size} remplis "
                             f"({th.size / fr.size:.0%}), brut moyen {th.mean():.3%} vs cout aller-retour {rt_cost:.3%} -> "
                             + ("couvre les frais" if th.mean() > rt_cost else "NE couvre PAS les frais (filtre de timing seulement)"))
        if p.shocks_file and self.shock_rows:
            pd.DataFrame(self.shock_rows, columns=["time_utc", "symbol", "z", "sell_share", "mid", "until_utc"]).to_csv(p.shocks_file, index=False)
            lines.append(f"Chocs exportes : {p.shocks_file}")
