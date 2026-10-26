"""FICHE 6 - Paires co-integrees (port de Strategies/Nexus06_PairsCointegration.cs).

Engle-Granger (MacKinnon N=2), p < 0.05 ; formation 12 mois / trading 6 mois ; entree |z| > 2 ;
sortie z -> 0 ou 20 j ; stop |z| > 4 ou p > 0.10 au recalcul mensuel ; une jambe = une paire.
Long seul par defaut (jambe sous-evaluee) ; allow_short_selling=True pour la version neutre.
"""
from __future__ import annotations

import math

import numpy as np

from .. import mathx as M
from ..engine import NexusStrategy, split_list


class _Pair:
    def __init__(self, a, b, alpha, beta, mu, sd, p):
        self.a, self.b, self.alpha, self.beta, self.mu, self.sd, self.p = a, b, alpha, beta, mu, sd, p
        self.pos = 0
        self.entry_batch = 0
        self.entry_z = M.NAN

    @property
    def key(self):
        return f"{self.a.name}/{self.b.name}"


class Nexus06PairsCointegration(NexusStrategy):
    NAME = "Nexus06_PairsCointegration"
    DESCRIPTION = "Fiche 6 - Paires co-integrees (Engle-Granger N=2), formation 12 mois / trading 6 mois, entree 2 sigma, sortie 0 ou 20 j."
    DEFAULTS = dict(
        symbols="KO,PEP,XOM,CVX,JPM,BAC,V,MA,HD,LOW,WMT,COST,UNH,CVS,MSFT,AAPL,GOOGL,META",
        sizing_mode="demi_kelly",
        allow_short_selling=False,
        stop_mode="aucun",
        mode="actions_journalier",
        pairs_list="",
        formation_bars=0,
        trading_bars=0,
        recheck_bars=0,
        max_hold_bars=0,
        p_value_max=0.05,
        recheck_p_value_max=0.10,
        entry_z=2.0,
        exit_z=0.0,
        stop_z=4.0,
        max_pairs=5,
        use_eg_critical_values=True,
    )

    @property
    def formation(self):
        return self.p.formation_bars or (30 * 24 if self.p.mode == "crypto_horaire" else 252)

    @property
    def trading(self):
        return self.p.trading_bars or (7 * 24 if self.p.mode == "crypto_horaire" else 126)

    @property
    def recheck(self):
        return self.p.recheck_bars or (7 * 24 if self.p.mode == "crypto_horaire" else 21)

    @property
    def max_hold(self):
        return self.p.max_hold_bars or (20 * 24 if self.p.mode == "crypto_horaire" else 20)

    def on_data_loaded(self):
        self.pairs: list[_Pair] = []
        self.bars_since_selection = 1 << 29
        self.bars_since_recheck = 0
        self.selections = self.entries = self.exits_zero = self.exits_time = self.exits_stop = self.exits_adf = self.tested_pairs = 0

    def _aligned_logs(self, a, b, n):
        ta, tb = a.hist.dates.values[: a.hist.count], b.hist.dates.values[max(0, b.hist.count - n * 2): b.hist.count]
        common = np.intersect1d(ta, tb, assume_unique=True)[-n:]
        if common.size < n * 0.8:
            return None, None
        ia = np.searchsorted(ta, common)
        ib = np.searchsorted(b.hist.dates.values[: b.hist.count], common)
        pa, pb = a.hist.close[ia], b.hist.close[ib]
        ok = (pa > 0) & (pb > 0)
        return np.log(pa[ok]), np.log(pb[ok])

    def _candidates(self):
        if self.p.pairs_list:
            res = []
            for pr in split_list(self.p.pairs_list):
                ab = pr.split("/")
                if len(ab) != 2:
                    continue
                a, b = self.sym(ab[0].strip()), self.sym(ab[1].strip())
                if a and b and a.traded and b.traded and a.asset_class == b.asset_class:
                    res.append((a, b))
                else:
                    self.nx_once("pair" + pr, "Paire ignoree (symbole absent ou classes differentes) : " + pr)
            return res
        t = self.traded_syms
        return [(t[i], t[j]) for i in range(len(t)) for j in range(i + 1, len(t)) if t[i].asset_class == t[j].asset_class]

    def _test_pair(self, a, b):
        la, lb = self._aligned_logs(a, b, self.formation)
        if la is None:
            return None
        adf, alpha, beta, resid = M.engle_granger(la, lb, self.p.use_eg_critical_values)
        if not adf.ok or resid is None or not beta > 0:
            return None
        mu, sd = M.mean(resid), M.std(resid)
        if not sd > 0:
            return None
        return _Pair(a, b, alpha, beta, mu, sd, adf.pvalue)

    def _select_pairs(self, key):
        for pr in self.pairs:
            self._close_pair(pr, "fin de la periode de trading")
        self.pairs = []
        ok = []
        cands = self._candidates()
        for a, b in cands:
            self.tested_pairs += 1
            pr = self._test_pair(a, b)
            if pr is not None and pr.p < self.p.p_value_max:
                ok.append(pr)
        used = set()
        for pr in sorted(ok, key=lambda x: x.p):
            if len(self.pairs) >= self.p.max_pairs:
                break
            if pr.a.name in used or pr.b.name in used:
                continue
            self.pairs.append(pr)
            used.update((pr.a.name, pr.b.name))
        self.selections += 1
        self.bars_since_selection = self.bars_since_recheck = 0
        self.nx(f"{key:%Y-%m-%d} selection : {len(ok)} paires co-integrees sur {len(cands)} candidates -> "
                + ", ".join(f"{p.key} (p={p.p:.3f}, b={p.beta:.2f})" for p in self.pairs))

    def _z_of(self, pr):
        pa, pb = pr.a.hist.last_close, pr.b.hist.last_close
        if not (pa > 0 and pb > 0):
            return M.NAN
        spread = math.log(pa) - (pr.alpha + pr.beta * math.log(pb))
        return (spread - pr.mu) / pr.sd

    def _open_pair(self, pr, z):
        long_leg, short_leg = (pr.a, pr.b) if z < 0 else (pr.b, pr.a)
        q_long, det = self.size_qty(long_leg, self.kelly_native_fraction(), long_leg.last_price)
        if q_long <= 0:
            return
        why = f"paire {pr.key} z={z:.2f} -> long {long_leg.name}"
        self.set_target(long_leg, q_long, M.NAN, why)
        if self.p.allow_short_selling:
            long_value = q_long * long_leg.last_price * self.value_per_point(long_leg)
            short_value = pr.beta * long_value if short_leg is pr.b else long_value / pr.beta
            lot = max(1, int(self.p.lot_size))
            q_short = int(math.floor(short_value / (short_leg.last_price * self.value_per_point(short_leg)) / lot)) * lot
            if q_short > 0:
                self.set_target(short_leg, -q_short, M.NAN, why + " / court " + short_leg.name)
        pr.pos = 1 if z < 0 else -1
        pr.entry_batch = self.batch_count
        pr.entry_z = z
        self.entries += 1

    def _close_pair(self, pr, reason):
        if pr.pos == 0:
            return
        for leg in (pr.a, pr.b):
            if leg.qty != 0 or leg.target_qty != 0:
                self.set_target(leg, 0, M.NAN, reason)
        pr.pos = 0

    def on_batch(self, key):
        self.bars_since_selection += 1
        self.bars_since_recheck += 1
        if sum(1 for s in self.traded_syms if s.hist.count >= self.formation) < 2:
            return
        if self.bars_since_selection >= self.trading:
            self._select_pairs(key)
            return
        if self.bars_since_recheck >= self.recheck:
            self.bars_since_recheck = 0
            for pr in list(self.pairs):
                fresh = self._test_pair(pr.a, pr.b)
                pv = fresh.p if fresh is not None else 1.0
                if pv > self.p.recheck_p_value_max:
                    if pr.pos != 0:
                        self.exits_adf += 1
                    self._close_pair(pr, f"co-integration perdue (p={pv:.3f} > {self.p.recheck_p_value_max:.2f})")
                    self.pairs.remove(pr)
        for pr in self.pairs:
            z = self._z_of(pr)
            if not M.ok(z):
                continue
            if pr.pos == 0:
                if self.p.entry_z < abs(z) < self.p.stop_z:
                    self._open_pair(pr, z)
                continue
            held = self.batch_count - pr.entry_batch
            if abs(z) > self.p.stop_z:
                self.exits_stop += 1
                self._close_pair(pr, f"stop : |z|={abs(z):.2f} > {self.p.stop_z:.1f}")
            elif (pr.pos > 0 and z >= -self.p.exit_z) or (pr.pos < 0 and z <= self.p.exit_z):
                self.exits_zero += 1
                self._close_pair(pr, f"convergence z={z:.2f}")
            elif held >= self.max_hold:
                self.exits_time += 1
                self._close_pair(pr, f"{held} barres sans convergence")

    def report_extras(self, lines):
        p = self.p
        lines.append(f"Mode {p.mode} | formation {self.formation} / trading {self.trading} / recalcul {self.recheck} barres | vente a decouvert : "
                     + ("oui (neutre au marche)" if p.allow_short_selling else "NON (long seul, pas neutre au marche)"))
        lines.append(f"Selections : {self.selections} | paires testees : {self.tested_pairs} | entrees : {self.entries} | sorties : convergence "
                     f"{self.exits_zero}, temps {self.exits_time}, stop 4 sigma {self.exits_stop}, p>0.10 {self.exits_adf}")
        lines.append("Paires actives : " + (", ".join(p.key + (" [en position]" if p.pos else "") for p in self.pairs) or "(aucune)"))
        if len(self.closed_trades) < 30:
            lines.append("Moins de 30 trades : aucune conclusion statistique possible.")
