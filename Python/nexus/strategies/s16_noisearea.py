"""FICHE 16 - Noise Area Intraday Momentum (Zarattini, Aziz & Barbon 2024, SSRN 4824172).

Liste de recherche "fiche 02" ; la fiche 01 (rebalancement des ETF a levier) est la fiche 15 du depot.

Regles (barres 1 minute, seance cash 9:30-16:00 heure de New York) :
  1. sigma(t) = moyenne sur les N jours PRECEDENTS de |Close(t) / Open - 1| a la meme minute t
     (Open = ouverture de la premiere minute cash ; le jour courant n entre jamais dans sa moyenne) ;
  2. Upper(t) = max(Open, PrevClose) x (1 + k sigma(t)), Lower(t) = min(Open, PrevClose) x (1 - k sigma(t)),
     PrevClose = cloture 16:00 de la veille (ajustee du dividende le jour ex si un fichier est fourni) ;
  3. controle uniquement toutes les M minutes depuis l ouverture (10:00, 10:30, ... pour M = 30) ;
  4. long si Close > Upper, short si Close < Lower ; par defaut l entree exige aussi Close > VWAP (resp. <),
     comme le code de replication des auteurs (signal recalcule a chaque controle = condition de maintien) ;
  5. stop suiveur : un long sort quand Close < max(Upper, VWAP), un short quand Close > min(Lower, VWAP)
     (au controle suivant, comme dans le papier ; option : verification chaque minute) ;
  6. toute position est fermee a la cloture (16:00, 13:00 les demi-seances ; option 15:50) ;
  7. taille fixee a l ouverture : AUM de la veille x min(vol cible / vol 14 j, levier max) / Open.

Execution : ordre decide a la cloture de la barre de controle, execute a l OUVERTURE de la barre
suivante (pas au prix du franchissement) ; sortie de fin de seance a la cloture (ordre MOC).
Couts : commission par unite (minimum par ordre) + glissement en ticks, par instrument (SPY : les
hypotheses du papier, 0,0035 $/action, min 0,35 $, glissement 0,001 $ ; futures : $/contrat et 1/2 tick).
"""
from __future__ import annotations

import math
import os
import re
from types import SimpleNamespace

import numpy as np
import pandas as pd

from .. import data as D
from .. import intraday as I
from .. import mathx as M
from .. import validation as V
from ..engine import BacktestResult, NexusStrategy, split_list
from ..risk import CircuitBreaker, TradeRecord, stress_test

try:
    import numba as nb
    _njit = nb.njit(cache=True)
except ImportError:  # pragma: no cover
    def _njit(f):
        return f

# Instruments : classe, $/point, tick, commission par unite et par ordre (minimum), glissement en ticks.
SPECS = {
    "SPY": ("Etf", 1.0, 0.01, 0.0035, 0.35, 0.1), "QQQ": ("Etf", 1.0, 0.01, 0.0035, 0.35, 0.1),
    "IWM": ("Etf", 1.0, 0.01, 0.0035, 0.35, 0.1), "DIA": ("Etf", 1.0, 0.01, 0.0035, 0.35, 0.1),
    "ES": ("Future", 50.0, 0.25, 2.25, 0.0, 0.5), "MES": ("Future", 5.0, 0.25, 0.62, 0.0, 0.5),
    "NQ": ("Future", 20.0, 0.25, 2.25, 0.0, 0.5), "MNQ": ("Future", 2.0, 0.25, 0.62, 0.0, 0.5),
    "RTY": ("Future", 50.0, 0.10, 2.25, 0.0, 0.5), "M2K": ("Future", 5.0, 0.10, 0.62, 0.0, 0.5),
    "YM": ("Future", 5.0, 1.0, 2.25, 0.0, 0.5), "MYM": ("Future", 0.5, 1.0, 0.62, 0.0, 0.5),
}
EXEC_MODES = {"ouverture_suivante": 0, "cloture": 1, "cloture_suivante": 2}
ENTRY_REASONS = {1: "cassure haute", -1: "cassure basse"}
FILL_REASONS = {11: "cassure haute", 12: "cassure basse", 1: "stop bande", 2: "stop VWAP", 3: "inversion",
                4: "stop minute", 5: "fin de seance"}
EXIT_REASONS = {1: "stop bande", 2: "stop VWAP", 3: "inversion", 4: "stop minute", 5: "fin de seance"}

# Colonnes des tableaux produits par le noyau
T_DAY, T_ESLOT, T_ECLOSE, T_XSLOT, T_XCLOSE, T_DIR, T_QTY, T_EPX, T_XPX, T_GROSS, T_COST, T_XR = range(12)
F_DAY, F_SLOT, F_CLOSE, F_QTY, F_PX, F_COST, F_R = range(7)
# Etat du noyau
S_POS, S_REF, S_GROSS, S_COST, S_TOPEN, S_TDIR, S_TQTY, S_TEPX, S_TESLOT, S_TECLOSE, S_TCOST, S_NT, S_NF = range(13)


@_njit
def _fill(st, target, px, d, s, at_close, reason, pv, comm_unit, comm_min, slip_px, T, F):
    pos = st[S_POS]
    q = target - pos
    if q == 0.0:
        return
    st[S_GROSS] += pos * (px - st[S_REF]) * pv
    st[S_REF] = px
    cost = max(comm_min, comm_unit * abs(q)) + slip_px * abs(q) * pv
    st[S_COST] += cost
    nf = int(st[S_NF])
    F[nf, F_DAY], F[nf, F_SLOT], F[nf, F_CLOSE], F[nf, F_QTY] = d, s, at_close, q
    F[nf, F_PX], F[nf, F_COST], F[nf, F_R] = px, cost, reason
    st[S_NF] = nf + 1
    open_cost = cost
    if pos != 0.0:
        part = cost * abs(pos) / abs(q)
        open_cost = cost - part
        nt = int(st[S_NT])
        T[nt, T_DAY], T[nt, T_ESLOT], T[nt, T_ECLOSE] = d, st[S_TESLOT], st[S_TECLOSE]
        T[nt, T_XSLOT], T[nt, T_XCLOSE], T[nt, T_DIR], T[nt, T_QTY] = s, at_close, st[S_TDIR], st[S_TQTY]
        T[nt, T_EPX], T[nt, T_XPX] = st[S_TEPX], px
        T[nt, T_GROSS] = st[S_TDIR] * st[S_TQTY] * (px - st[S_TEPX]) * pv
        T[nt, T_COST], T[nt, T_XR] = st[S_TCOST] + part, reason
        st[S_NT] = nt + 1
        st[S_TOPEN] = 0.0
    if target != 0.0:
        st[S_TOPEN] = 1.0
        st[S_TDIR] = 1.0 if target > 0 else -1.0
        st[S_TQTY] = abs(target)
        st[S_TEPX] = px
        st[S_TESLOT] = s
        st[S_TECLOSE] = at_close
        st[S_TCOST] = open_cost
    st[S_POS] = target


@_njit
def _kernel(o, c, sigma, vwap, last_slot, exit_dec, dec_mask, tradable, lev, day_open, prev_close,
            init_eq, pv, band_mult, use_vwap, vwap_entry, allow_short, exec_mode, stop_minute, comm_unit, comm_min, slip_px,
            fractional, max_entries, use_breakers, daily_loss, dd_trip, reset_peak, T, F):
    nd = o.shape[0]
    eq_day = np.empty(nd)
    gross_day = np.zeros(nd)
    cost_day = np.zeros(nd)
    expo_day = np.zeros(nd)
    units_day = np.zeros(nd)
    ntr_day = np.zeros(nd)
    st = np.zeros(13)
    eq = init_eq
    peak = init_eq
    block_until = -1
    trips_daily = 0
    trips_dd = 0
    for d in range(nd):
        ls = last_slot[d]
        if (not tradable[d]) or ls < 0 or not (day_open[d] > 0.0) or not (lev[d] > 0.0):
            eq_day[d] = eq
            continue
        aum = eq
        x = aum * lev[d] / (day_open[d] * pv)
        u = x if fractional else math.floor(x + 0.5)
        units_day[d] = u
        if u <= 0.0:
            eq_day[d] = eq
            continue
        nt0 = st[S_NT]
        st[S_POS] = 0.0
        st[S_REF] = day_open[d]
        st[S_GROSS] = 0.0
        st[S_COST] = 0.0
        st[S_TOPEN] = 0.0
        hi_ref = max(day_open[d], prev_close[d])
        lo_ref = min(day_open[d], prev_close[d])
        pend = False
        pend_target = 0.0
        pend_slot = -1
        pend_close = 0.0
        pend_reason = 0.0
        entries = 0
        dd_blocked = False
        daily_blocked = False
        xd = exit_dec[d]
        expo = 0.0
        for s in range(ls + 1):
            # 1. ordre en attente execute a l ouverture de la barre
            if pend and pend_slot == s and pend_close == 0.0:
                _fill(st, pend_target, o[d, s], d, s, 0.0, pend_reason, pv, comm_unit, comm_min, slip_px, T, F)
                pend = False
            # 2. marque a la cloture, ordre en attente execute a la cloture (mode cloture suivante)
            cs = c[d, s]
            st[S_GROSS] += st[S_POS] * (cs - st[S_REF]) * pv
            st[S_REF] = cs
            if pend and pend_slot == s and pend_close == 1.0:
                _fill(st, pend_target, cs, d, s, 1.0, pend_reason, pv, comm_unit, comm_min, slip_px, T, F)
                pend = False
            # 3. disjoncteurs (module C) : bloquent les entrees, jamais les sorties
            if use_breakers:
                eq_run = aum + st[S_GROSS] - st[S_COST]
                if eq_run > peak:
                    peak = eq_run
                if (not daily_blocked) and eq_run <= aum * (1.0 - daily_loss):
                    daily_blocked = True
                    trips_daily += 1
                    block_until = d + 1
                if (not dd_blocked) and eq_run <= peak * (1.0 - dd_trip):
                    dd_blocked = True
                    trips_dd += 1
            # 4. decisions a la cloture de la barre s
            pos = st[S_POS]
            cur = 0.0 if pos == 0.0 else (1.0 if pos > 0.0 else -1.0)
            if s == xd:
                pend = False
                if pos != 0.0:
                    if s == ls or exec_mode == 1:
                        _fill(st, 0.0, cs, d, s, 1.0, 5.0, pv, comm_unit, comm_min, slip_px, T, F)
                    else:
                        pend, pend_target, pend_reason = True, 0.0, 5.0
                        pend_slot = s + 1
                        pend_close = 0.0 if exec_mode == 0 else 1.0
            elif s < xd:
                sg = sigma[d, s]
                vw = vwap[d, s]
                vw_ok = use_vwap and vw == vw
                if dec_mask[s] and sg == sg:
                    ub = hi_ref * (1.0 + band_mult * sg)
                    lb = lo_ref * (1.0 - band_mult * sg)
                    # tenir : au-dela de max(Upper, VWAP) / min(Lower, VWAP) ; entrer : VWAP exige si vwap_entry
                    up = cs > ub and ((not vw_ok) or cs > vw or (cur <= 0.0 and not vwap_entry))
                    dn = cs < lb and ((not vw_ok) or cs < vw or (cur >= 0.0 and not vwap_entry))
                    want = 1.0 if up else (-1.0 if (dn and allow_short) else 0.0)
                    if want != 0.0 and want != cur:
                        blocked = dd_blocked or daily_blocked or d == block_until
                        if blocked or (max_entries > 0 and entries >= max_entries):
                            want = 0.0
                    if want != cur:
                        if cur != 0.0 and want == -cur:
                            reason = 3.0
                        elif cur > 0.0:
                            reason = 2.0 if (vw_ok and vw > ub) else 1.0
                        elif cur < 0.0:
                            reason = 2.0 if (vw_ok and vw < lb) else 1.0
                        else:
                            reason = 11.0 if want > 0.0 else 12.0
                        if want != 0.0:
                            entries += 1
                        if exec_mode == 1:
                            _fill(st, want * u, cs, d, s, 1.0, reason, pv, comm_unit, comm_min, slip_px, T, F)
                        else:
                            pend, pend_target, pend_reason = True, want * u, reason
                            pend_slot = s + 1
                            pend_close = 0.0 if exec_mode == 0 else 1.0
                elif stop_minute and pos != 0.0 and sg == sg and not pend:
                    ub = hi_ref * (1.0 + band_mult * sg)
                    lb = lo_ref * (1.0 - band_mult * sg)
                    lvl_l = max(ub, vw) if vw_ok else ub
                    lvl_s = min(lb, vw) if vw_ok else lb
                    if (pos > 0.0 and cs < lvl_l) or (pos < 0.0 and cs > lvl_s):
                        if exec_mode == 1:
                            _fill(st, 0.0, cs, d, s, 1.0, 4.0, pv, comm_unit, comm_min, slip_px, T, F)
                        else:
                            pend, pend_target, pend_reason = True, 0.0, 4.0
                            pend_slot = s + 1
                            pend_close = 0.0 if exec_mode == 0 else 1.0
            expo += abs(st[S_POS]) * cs * pv / aum
        if st[S_POS] != 0.0:          # securite : jamais de position la nuit
            _fill(st, 0.0, c[d, ls], d, ls, 1.0, 5.0, pv, comm_unit, comm_min, slip_px, T, F)
        gross_day[d] = st[S_GROSS]
        cost_day[d] = st[S_COST]
        eq = aum + st[S_GROSS] - st[S_COST]
        eq_day[d] = eq
        expo_day[d] = expo / (ls + 1)
        ntr_day[d] = st[S_NT] - nt0
        if use_breakers and dd_blocked and reset_peak:
            peak = eq
    return eq_day, gross_day, cost_day, expo_day, units_day, ntr_day, int(st[S_NT]), int(st[S_NF]), trips_daily, trips_dd


# =============================================================================
_GRID_CACHE: dict = {}


def _grid_for(df: pd.DataFrame, tz: str, label: str, roll: str = "aucun"):
    """Grille de seance mise en cache pour les grilles de parametres (meme DataFrame, meme fuseau).
    -> (grille, note sur l horodatage, table des rolls ajustes)."""
    key = (id(df), tz, label, roll)
    hit = _GRID_CACHE.get(key)
    if hit is None or hit[0] is not df:          # la reference gardee empeche la reutilisation de l id
        if len(_GRID_CACHE) >= 2:
            _GRID_CACHE.pop(next(iter(_GRID_CACHE)))
        src, rolls = (I.adjust_rolls_midnight_utc(df, tz) if roll == "minuit_utc"
                      else (df, pd.DataFrame(columns=["utc", "bar", "saut_bp", "second_bp"])))
        mins, note = I.prepare_minutes(src, tz, label)
        hit = _GRID_CACHE[key] = (df, I.build_grid(mins), note, rolls)
    return hit[1], hit[2], hit[3]


def _find_series(data: dict, name: str):
    up = name.upper()
    for k, v in data.items():
        if k.upper() in (up, up + "##-##"):
            return v
    contracts = sorted(k for k in data if re.fullmatch(re.escape(up) + r"\d{2}-\d{2}", k.upper()))
    if contracts:
        raise ValueError(f"seuls des contrats individuels de {name} sont presents ({', '.join(contracts[:4])}...) : "
                         f"exporter la serie continue '{name} ##-##' ajustee des rolls (NinjaTrader : Merge Back Adjusted)")
    return None


def _read_dated_csv(path: str) -> pd.DataFrame | None:
    if not path or not os.path.exists(path):
        return None
    df = pd.read_csv(path, comment="#", skip_blank_lines=True)
    if df.empty:
        return None
    df.columns = [str(c).strip().lower() for c in df.columns]
    date_col = next((c for c in df.columns if c in ("date", "ex_date", "exdate", "day", "jour")), df.columns[0])
    df["date"] = pd.to_datetime(df[date_col], errors="coerce").dt.normalize()
    return df.dropna(subset=["date"])


def _sharpe(r) -> float:
    return V.annualized_sharpe(np.asarray(r, float))


def _cagr(r) -> float:
    r = np.asarray(r, float)
    r = r[np.isfinite(r)]
    if r.size < 2:
        return M.NAN
    tot = float(np.prod(1 + r))
    return tot ** (252.0 / r.size) - 1 if tot > 0 else -1.0


def _mdd(r) -> float:
    r = np.asarray(r, float)
    return V.max_drawdown(np.concatenate([[1.0], np.cumprod(1 + np.nan_to_num(r))]))


def _f(x, d=2):
    return f"{x:.{d}f}" if M.ok(x) else "n/a"


def _p(x, d=1):
    return f"{x:.{d}%}" if M.ok(x) else "n/a"


class Nexus16NoiseArea(NexusStrategy):
    NAME = "Nexus16_NoiseAreaMomentum"
    DESCRIPTION = "Fiche 16 - Noise Area intraday momentum (Zarattini-Aziz-Barbon) : bandes de bruit 14 j, controle 30 min, stop max(bande, VWAP)."
    INTRADAY = True
    TOUT_SYMBOLS = ("SPY", "QQQ", "IWM", "DIA", "ES", "NQ", "YM", "RTY", "MES", "MNQ", "M2K", "MYM")   # recapitulatif `tout`
    DEFAULTS = dict(
        symbols="SPY",
        allow_short_selling=True,
        use_circuit_breakers=False,          # absent du papier ; module C disponible (entrees bloquees)
        # --- Regles ---
        lookback_days=14,
        band_mult=1.0,
        check_interval_min=30,
        first_check_min=0,                   # 0 = premier controle apres un intervalle (10:00 pour 30 min)
        use_vwap_stop=True,
        vwap_entry_filter=True,              # entree exige aussi Close > VWAP (code des auteurs) ; false = Close > Upper seul
        stop_check="controle",               # controle (papier) | minute
        execution="ouverture_suivante",      # ouverture_suivante | cloture (prix du franchissement) | cloture_suivante
        exit_minutes_before_close=0,         # 0 = cloture (MOC) ; 10 = sortie a 15:50
        max_entries_per_day=0,               # 0 = illimite (re-entrees possibles)
        # --- Taille ---
        sizing="vol_cible",                  # vol_cible | fixe
        target_daily_vol_pct=2.0,
        vol_lookback_days=14,
        max_leverage=4.0,
        fixed_leverage=1.0,
        fractional_units=False,
        # --- Instrument et couts (vide = table SPECS) ---
        point_value=None,
        tick_size=None,
        commission_per_unit=None,
        commission_min_per_order=None,
        slippage_ticks=None,
        # --- Donnees ---
        data_timezone="auto",                # auto (UTC si le fichier porte un fuseau, sinon New York) | Europe/Paris | UTC...
        bar_label="auto",                    # auto | debut | fin
        roll_adjust="auto",                  # auto (minuit_utc pour un future dont le fichier est en UTC, ex. Databento) | minuit_utc | aucun
        exchange_calendar="NYSE",            # NYSE (feries exclus : seance futures raccourcie sans seance cash) | aucun
        dividends_file="",                   # CSV date,dividend (jour ex) : PrevClose ajuste
        # --- Analyse ---
        publication_date="2024-06-01",
        crisis_years="2008,2020,2022",
        vix_symbol="^VIX",
        vix_bounds="15,20,30",
        gex_file="",                         # meme format que la fiche 15 : date[,underlying],gex[,gex_ref]
        gamma_filter="aucun",                # aucun | court (G<0) | long (G>0)
        gamma_unknown="trader",              # trader | pas_de_trade
    )
    REPORT_KEYS = ("symbols", "initial_bankroll", "use_circuit_breakers", "monte_carlo_sims") + tuple(DEFAULTS)

    def required_references(self) -> list[str]:
        return [self.p.vix_symbol] if self.p.vix_symbol else []

    def data_symbols(self) -> list[str]:
        return list(dict.fromkeys(split_list(self.p.symbols)[:1] + self.required_references()))

    # =========================================================================
    def _spec(self, sym: str):
        p = self.p
        base = SPECS.get(sym.upper())
        if base is None:
            self.nx(f"instrument {sym} absent de la table : action/ETF suppose (1 $/point, tick 0.01, couts du papier)")
            base = ("Etf", 1.0, 0.01, 0.0035, 0.35, 0.1)
        cls, pv, tick, cu, cm, sl = base
        pv = float(p.point_value) if p.point_value is not None else pv
        tick = float(p.tick_size) if p.tick_size is not None else tick
        cu = float(p.commission_per_unit) if p.commission_per_unit is not None else cu
        cm = float(p.commission_min_per_order) if p.commission_min_per_order is not None else cm
        sl = float(p.slippage_ticks) if p.slippage_ticks is not None else sl
        return SimpleNamespace(asset_class=cls, point_value=pv, tick_size=tick, comm_unit=cu, comm_min=cm, slip_ticks=sl)

    def _daily_series(self, data: dict, name: str) -> pd.Series | None:
        if not name:
            return None
        df = None
        for k, v in data.items():
            if k.upper() in (name.upper(), name.upper().lstrip("^"), "^" + name.upper().lstrip("^")):
                df = v
                break
        if df is None or df.empty:
            return None
        return D.to_daily(df)["close"]

    # =========================================================================
    def run(self, data: dict, start=None, end=None, trade_start=None, report: bool = True) -> BacktestResult:
        p = self.p
        syms = split_list(p.symbols)
        if not syms:
            raise ValueError(f"{self.NAME} : aucun symbole")
        if len(syms) > 1:
            self.nx(f"un seul instrument par run : {syms[0]} (lancer un run par symbole pour {', '.join(syms[1:])})")
        sym = syms[0]
        df = _find_series(data, sym)
        if df is None or df.empty:
            raise ValueError(f"{self.NAME} : {sym} introuvable dans les donnees")
        if not I.is_intraday(df):
            raise ValueError(f"{self.NAME} : {sym} n a pas de barres intrajournalieres (barres 1 minute requises)")
        if p.execution not in EXEC_MODES:
            raise ValueError(f"execution inconnue '{p.execution}' ({', '.join(EXEC_MODES)})")
        spec = self._spec(sym)
        tz = df.attrs.get("fuseau", I.NY) if p.data_timezone == "auto" else p.data_timezone
        if p.roll_adjust not in ("auto", "aucun", "minuit_utc"):
            raise ValueError(f"roll_adjust inconnu '{p.roll_adjust}' (auto | aucun | minuit_utc)")
        roll = p.roll_adjust
        if roll == "auto":         # contrats continus Databento (.v.0) : fichier Parquet horodate en UTC, sans ajustement
            roll = "minuit_utc" if spec.asset_class == "Future" and df.attrs.get("fuseau") == "UTC" else "aucun"
        grid, note, rolls = _grid_for(df, tz, p.bar_label, roll)
        self.symbol, self.spec, self.data_note, self.tz, self.rolls = sym, spec, note, tz, rolls
        self.nx(f"{sym} : {note}, fuseau source {tz}")
        if len(rolls):
            self.nx(f"{sym} : {len(rolls)} rolls ajustes a 00:00 UTC (saut moyen {rolls['saut_bp'].abs().mean():.0f} bp)")
        if grid.valid.mean() < 0.5:
            raise ValueError(f"{self.NAME} : moins de la moitie des jours ont une seance cash complete - fuseau des donnees "
                             f"('{p.data_timezone}') ou horodatage incorrect ? Ex. -p data_timezone=Europe/Paris")

        # --- bornes de donnees ---
        days = grid.days
        lo = np.searchsorted(days.values, np.datetime64(pd.Timestamp(start))) if start is not None else 0
        hi = np.searchsorted(days.values, np.datetime64(pd.Timestamp(end)), side="right") if end is not None else len(days)
        sl = slice(lo, hi)
        days = days[sl]
        o, c, valid = grid.o[sl], grid.c[sl], grid.valid[sl].copy()
        last_slot, half = grid.last_slot[sl], grid.half_day[sl]
        n = len(days)
        holiday = np.zeros(n, bool)
        if p.exchange_calendar == "NYSE" and n:
            holiday = np.asarray(days.isin(I.nyse_holidays(days[0], days[-1])))
            valid &= ~holiday
            half = half & valid
        if n < int(p.lookback_days) + 1:
            raise ValueError(f"{self.NAME} : historique trop court ({n} jours)")
        g = I.SessionGrid(days, o, grid.h[sl], grid.l[sl], c, grid.v[sl], last_slot, valid, half, grid.first_slot[sl])

        # --- Open, PrevClose (16:00 de la veille, ajuste du dividende), vol journaliere ---
        day_open = g.day_open.copy()
        close_d = np.where(valid, g.day_close, np.nan)
        prev_close = pd.Series(close_d).ffill().shift(1).to_numpy()
        divs = np.zeros(n)
        dv = _read_dated_csv(p.dividends_file)
        if dv is not None:
            col = next((x for x in dv.columns if x in ("dividend", "dividende", "amount", "div", "value")), dv.columns[-1])
            ser = dv.groupby("date")[col].sum()
            divs = ser.reindex(days).fillna(0.0).to_numpy(float)
            self.nx(f"dividendes : {int((divs > 0).sum())} jours ex dans la periode ({p.dividends_file})")
        prev_close = prev_close - divs
        day_ret = np.where(valid, close_d / prev_close - 1.0, np.nan)
        r_valid = pd.Series(day_ret[valid])
        vol_v = r_valid.rolling(int(p.vol_lookback_days)).std().shift(1).to_numpy()
        vol = np.full(n, np.nan)
        vol[valid] = vol_v
        if p.sizing == "vol_cible":
            with np.errstate(divide="ignore", invalid="ignore"):
                lev = np.minimum(p.target_daily_vol_pct / 100.0 / vol, float(p.max_leverage))
        elif p.sizing == "fixe":
            lev = np.full(n, float(p.fixed_leverage))
        else:
            raise ValueError(f"sizing inconnu '{p.sizing}' (vol_cible | fixe)")

        # --- zone de bruit et VWAP ---
        with np.errstate(divide="ignore", invalid="ignore"):
            move = np.abs(c / day_open[:, None] - 1.0)
        move[~valid] = np.nan
        sigma = I.slot_mean_prev(move, int(p.lookback_days))
        vwap = I.session_vwap(g)
        has_volume = bool(np.nansum(g.v) > 0)
        if p.use_vwap_stop and not has_volume:
            self.nx("volume absent : VWAP indisponible, stop suiveur sur la bande seule")
        minutes = np.arange(I.SESSION_MINUTES) + 1
        step = max(1, int(p.check_interval_min))
        first = int(p.first_check_min) if int(p.first_check_min) > 0 else step
        dec_mask = (minutes % step == 0) & (minutes >= first)
        exit_dec = np.maximum(0, last_slot - int(p.exit_minutes_before_close)).astype(np.int64)

        # --- regimes : VIX de la veille, GEX du jour ---
        vix = self._daily_series(data, p.vix_symbol)
        vix_prev = np.full(n, np.nan)
        if vix is not None:
            vix_prev = pd.Series(vix.to_numpy(float), index=pd.DatetimeIndex(vix.index).normalize())
            vix_prev = vix_prev[~vix_prev.index.duplicated(keep="last")].sort_index()
            vix_prev = vix_prev.reindex(vix_prev.index.union(days)).ffill().shift(1).reindex(days).to_numpy(float)
        gex = np.full(n, np.nan)
        gx = _read_dated_csv(p.gex_file)
        if gx is not None:
            col = next((x for x in gx.columns if x in ("gex", "gex_usd", "gex_usd_per_pct", "net_gex", "gamma", "value")), None)
            if col is not None:
                gex = pd.to_numeric(gx[col], errors="coerce").groupby(gx["date"]).sum(min_count=1).reindex(days).to_numpy(float)
                self.nx(f"GEX : {int(np.isfinite(gex).sum())} jours connus dans la periode ({p.gex_file})")

        # --- jours tradables ---
        ts = pd.Timestamp(trade_start).normalize() if trade_start is not None else None
        dec_idx = np.flatnonzero(dec_mask)
        sig_ok = np.zeros(n, bool)
        for d in range(n):
            if valid[d]:
                ds = dec_idx[dec_idx < exit_dec[d]]
                sig_ok[d] = len(ds) > 0 and bool(np.isfinite(sigma[d, ds]).all())
        tradable = valid & sig_ok & np.isfinite(lev) & (lev > 0) & np.isfinite(prev_close) & (day_open > 0)
        warm = int((valid & ~tradable).sum())
        if ts is not None:
            tradable &= np.asarray(days >= ts)
        gamma_skip = 0
        if p.gamma_filter != "aucun":
            if not np.isfinite(gex).any():
                self.nx("filtre gamma demande mais aucun GEX (gex_file) : filtre ignore")
            else:
                ok = (gex < 0) if p.gamma_filter == "court" else (gex > 0)
                known = np.isfinite(gex)
                allow = np.where(known, ok, p.gamma_unknown != "pas_de_trade")
                gamma_skip = int((tradable & ~allow).sum())
                tradable &= allow

        # --- noyau ---
        n_dec = int(dec_mask.sum())
        cap = n * (n_dec + 3) + 16
        T = np.zeros((cap, 12))
        F = np.zeros((2 * cap, 7))
        bp = (p.use_circuit_breakers, p.daily_loss_pct / 100.0, p.drawdown_trip_pct / 100.0, p.reset_peak_after_cooldown)
        eq_day, gross_day, cost_day, expo_day, units_day, ntr_day, nt, nf, trips_d, trips_dd = _kernel(
            o, c, sigma, vwap, last_slot.astype(np.int64), exit_dec, dec_mask, tradable, np.nan_to_num(lev, nan=0.0),
            np.nan_to_num(day_open), np.nan_to_num(prev_close), float(p.initial_bankroll), spec.point_value,
            float(p.band_mult), bool(p.use_vwap_stop and has_volume), bool(p.vwap_entry_filter), bool(p.allow_short_selling),
            EXEC_MODES[p.execution],
            p.stop_check == "minute", spec.comm_unit, spec.comm_min, spec.slip_ticks * spec.tick_size,
            bool(p.fractional_units), int(p.max_entries_per_day), bool(bp[0]), float(bp[1]), float(bp[2]), bool(bp[3]), T, F)
        T, F = T[:nt], F[:nf]

        # --- resultats au format du moteur ---
        self.syms = [SimpleNamespace(name=sym, traded=True, asset_class=spec.asset_class)]
        self.costs = SimpleNamespace(describe=lambda: (
            f"commission {spec.comm_unit:g} $/unite (min {spec.comm_min:g} $/ordre) + glissement {spec.slip_ticks:g} tick "
            f"({spec.slip_ticks * spec.tick_size:g} pt = {spec.slip_ticks * spec.tick_size * spec.point_value:g} $/unite) par execution"))
        self.breaker = CircuitBreaker(p.use_circuit_breakers)
        self.breaker.daily_trips, self.breaker.drawdown_trips = int(trips_d), int(trips_dd)
        keep = valid & (np.asarray(days >= ts) if ts is not None else True)
        eq = pd.Series(eq_day[keep], index=days[keep], name="equity")
        expo = pd.Series(expo_day[keep], index=days[keep], name="exposition_brute")
        prev_eq = np.r_[float(p.initial_bankroll), eq_day[:-1]]
        rets = pd.Series((eq_day / prev_eq - 1.0)[keep], index=days[keep], name="rendement")

        def stamp(dd, ss, at_close):
            return days[int(dd)] + pd.Timedelta(minutes=9 * 60 + 30 + int(ss) + (1 if at_close else 0))

        trades = []
        for row in T:
            qty, epx, pv = row[T_QTY], row[T_EPX], spec.point_value
            notional = qty * epx * pv
            net = row[T_GROSS] - row[T_COST]
            et = stamp(row[T_DAY], row[T_ESLOT], row[T_ECLOSE])
            xt = stamp(row[T_DAY], row[T_XSLOT], row[T_XCLOSE])
            trades.append(TradeRecord(self.strategy_id, sym, spec.asset_class, int(row[T_DIR]), qty, et, xt, epx, row[T_XPX],
                                      notional, row[T_GROSS], row[T_COST], net, net / notional if notional > 0 else 0.0,
                                      row[T_GROSS] / notional if notional > 0 else 0.0,
                                      ENTRY_REASONS.get(int(row[T_DIR]), ""), EXIT_REASONS.get(int(row[T_XR]), ""), "",
                                      dict(minutes=(xt - et).total_seconds() / 60.0, levier=float(lev[int(row[T_DAY])]))))
        fills = pd.DataFrame({"time": [stamp(r[F_DAY], r[F_SLOT], r[F_CLOSE]) for r in F],
                              "symbol": sym, "qty": F[:, F_QTY] if len(F) else [], "price": F[:, F_PX] if len(F) else [],
                              "cost": F[:, F_COST] if len(F) else [],
                              "reason": [FILL_REASONS.get(int(r[F_R]), "") for r in F],
                              "moment": np.where(F[:, F_CLOSE] > 0, "cloture", "ouverture") if len(F) else []},
                             columns=["time", "symbol", "qty", "price", "cost", "reason", "moment"])
        panel = pd.DataFrame({
            "open": day_open, "prev_close": prev_close, "gap": day_open / prev_close - 1, "cloture": close_d,
            "vol_14j": vol, "levier": lev, "unites": units_day, "trades": ntr_day, "pnl_brut": gross_day, "couts": cost_day,
            "equity": eq_day, "exposition": expo_day, "vix_veille": vix_prev, "gex": gex,
            "sigma_premier_controle": sigma[:, dec_idx[0]] if len(dec_idx) else np.nan,
            "demi_seance": half, "valide": valid, "trade": tradable}, index=days)
        panel.index.name = "date"
        panel["rendement"] = np.where(valid, eq_day / prev_eq - 1, np.nan)
        panel["rendement_brut"] = np.where(valid, gross_day / prev_eq, np.nan)
        panel["cout_rel"] = np.where(valid, cost_day / prev_eq, np.nan)

        self.log_counts = dict(valid=int(valid.sum()), half=int(half.sum()), invalid=int((~valid & ~holiday).sum()),
                               holidays=int(holiday.sum()),
                               warm=warm, tradable=int(tradable.sum()), gamma_skip=gamma_skip,
                               n_dec=int((dec_idx < I.SESSION_MINUTES - 1 - int(p.exit_minutes_before_close)).sum()))
        self.panel = panel[keep]
        self.closed_trades = trades
        res = BacktestResult(strategy=self, name=self.strategy_id,
                             params={k: self.params[k] for k in self.REPORT_KEYS if k in self.params},
                             equity=eq, returns=rets, trades=trades, fills=fills, log=list(self.log), signals=[],
                             breaker_events=[], exposure=expo, report="", intraday=True, grid=g, day_mask=keep,
                             daily_panel=self.panel, point_value=spec.point_value)
        res.open_positions = {}
        res.stress = stress_test([], float(eq.iloc[-1]) if len(eq) else float(p.initial_bankroll),
                                 p.stress_shock_pct / 100.0, p.stress_worst_n)
        self.result = res
        if report:
            from ..report import build_report
            extras: list[str] = []
            self.report_extras(extras)
            res.report = build_report(res, extras)
        return res

    # =========================================================================
    #  Rapport specifique
    # =========================================================================
    def report_extras(self, lines: list[str]):
        p, spec, res = self.p, self.spec, self.result
        pan = self.panel
        lc = self.log_counts
        tr = res.trades
        r = pan["rendement"].dropna()
        lines.append(f"Instrument {self.symbol} ({spec.asset_class}, {spec.point_value:g} $/point, tick {spec.tick_size:g}) ; "
                     f"donnees : {self.data_note}, fuseau source {self.tz}")
        if len(self.rolls):
            rb = self.rolls["saut_bp"]
            lines.append(f"Rolls ajustes (00:00 UTC, proportionnel) : {len(rb)}, saut moyen {rb.abs().mean():.0f} bp, "
                         f"max {rb.abs().max():.0f} bp, du {self.rolls['utc'].iloc[0]:%Y-%m-%d} au {self.rolls['utc'].iloc[-1]:%Y-%m-%d}")
        lines.append(f"Seances : {lc['valid']} valides (dont {lc['half']} demi-seances), {lc['holidays']} feries NYSE exclus, "
                     f"{lc['invalid']} incompletes ignorees, "
                     f"{lc['tradable']} tradables (chauffage {lc['warm']}" + (f", {lc['gamma_skip']} exclues par le filtre gamma" if lc["gamma_skip"] else "") + ")")
        first = int(p.first_check_min) if int(p.first_check_min) > 0 else int(p.check_interval_min)
        exit_txt = "cloture (MOC)" if int(p.exit_minutes_before_close) == 0 else f"{p.exit_minutes_before_close} min avant la cloture"
        lines.append(f"Regles : sigma {p.lookback_days} j (jour courant exclu), bandes max/min(Open, PrevClose) x (1 +/- {p.band_mult:g} sigma), "
                     f"controles toutes les {p.check_interval_min} min des {I.slot_time(first - 1)} ({lc['n_dec']} par seance), "
                     f"entree {'bande et VWAP' if p.use_vwap_stop and p.vwap_entry_filter else 'bande seule'}, "
                     f"stop {'max(bande, VWAP)' if p.use_vwap_stop else 'bande'} verifie {'chaque minute' if p.stop_check == 'minute' else 'aux controles'}, "
                     f"execution {p.execution.replace('_', ' ')}, sortie {exit_txt}, short {'oui' if p.allow_short_selling else 'non'}")
        traded = pan[pan["trade"]]
        lv = traded["levier"]
        if p.sizing == "vol_cible":
            capped = float((lv >= float(p.max_leverage) - 1e-12).mean()) if len(lv) else M.NAN
            lines.append(f"Taille : vol cible {p.target_daily_vol_pct:g} %/jour (vol {p.vol_lookback_days} j), levier max {p.max_leverage:g} -> "
                         f"levier moyen {_f(lv.mean())}, median {_f(lv.median())}, plafonne {_p(capped)} des jours")
        else:
            lines.append(f"Taille : levier fixe {p.fixed_leverage:g}")
        zero_units = int((traded["unites"] <= 0).sum())
        if zero_units:
            lines.append(f"  ATTENTION : {zero_units} jours sans trade faute de capital pour 1 unite (fractional_units ou micro-contrat)")
        if not tr:
            lines.append("Aucun trade.")
            return
        tf = pd.DataFrame({"jour": [t.entry_time.normalize() for t in tr], "dir": [t.direction for t in tr],
                           "net": [t.net_pnl for t in tr], "brut": [t.gross_pnl for t in tr], "cout": [t.costs for t in tr],
                           "notionnel": [t.max_notional for t in tr], "sortie": [t.exit_reason for t in tr],
                           "minutes": [t.extra["minutes"] for t in tr]})
        nt_day = traded["trades"]
        dist = nt_day.value_counts(normalize=True).sort_index()
        dist_txt = " ".join(f"{int(k)}:{v:.0%}" for k, v in dist.items() if k < 4)
        dist_txt += f" 4+:{dist[dist.index >= 4].sum():.0%}" if (dist.index >= 4).any() else ""
        flips = int((tf["sortie"] == "inversion").sum())
        lines.append(f"Trades par seance tradable : moyenne {_f(nt_day.mean())} (sur les seances avec trade {_f(nt_day[nt_day > 0].mean())}) ; "
                     f"repartition {dist_txt} ; inversions {flips}")
        ex = tf["sortie"].value_counts(normalize=True)
        lines.append(f"Allers-retours : {len(tf)} (long {int((tf['dir'] > 0).sum())} / short {int((tf['dir'] < 0).sum())}), "
                     f"duree moyenne {tf['minutes'].mean():.0f} min ; sorties : " + ", ".join(f"{k} {v:.0%}" for k, v in ex.items()))
        lines.append(f"PnL net long / short : {tf.loc[tf['dir'] > 0, 'net'].sum():.0f} / {tf.loc[tf['dir'] < 0, 'net'].sum():.0f} $")
        gross, cost = tf["brut"].sum(), tf["cout"].sum()
        bp_rt = cost / tf["notionnel"].sum() * 1e4 if tf["notionnel"].sum() > 0 else M.NAN
        rb, rc = pan["rendement_brut"].fillna(0.0), pan["cout_rel"].fillna(0.0)
        sh = [_sharpe(rb - k * rc) for k in (0.0, 1.0, 2.0, 3.0)]
        lines.append(f"Couts : total {cost:.0f} $ ({_p(cost / gross if gross > 0 else M.NAN)} du PnL brut), {_f(bp_rt)} bp du notionnel par aller-retour, "
                     f"{_f(cost / max(1, len(traded)))} $/seance")
        lines.append(f"Sharpe selon les couts (x0 / x1 / x2 / x3) : {' / '.join(_f(x) for x in sh)}")
        bh = (pan["cloture"] / pan["prev_close"] - 1).where(pan["valide"]).reindex(r.index)
        corr = float(np.corrcoef(bh.fillna(0), r.fillna(0))[0, 1]) if len(r) > 10 else M.NAN
        lines.append(f"Buy & hold {self.symbol} (cloture a cloture) : Sharpe {_f(_sharpe(bh.dropna()))}, CAGR {_p(_cagr(bh.dropna()))}, "
                     f"DD max {_p(_mdd(bh.dropna()))} ; correlation des rendements journaliers {_f(corr)}")

        # --- periodes ---
        pub = pd.Timestamp(p.publication_date) if p.publication_date else None
        lines.append("")
        lines.append(f"Periodes (publication {pub:%Y-%m-%d}) :" if pub is not None else "Periodes :")
        post = r[r.index >= pub] if pub is not None else r.iloc[0:0]
        for lab, rr in (("avant", r[r.index < pub] if pub is not None else r), ("apres", post)):
            if len(rr) == 0:
                lines.append(f"  {lab:6}: aucune seance")
                continue
            lines.append(f"  {lab:6}: {rr.index[0]:%Y-%m-%d} -> {rr.index[-1]:%Y-%m-%d}  {len(rr):5d} j  Sharpe {_f(_sharpe(rr)):>5}  "
                         f"CAGR {_p(_cagr(rr)):>7}  DD max {_p(_mdd(rr)):>6}  trades {int(pan.loc[rr.index, 'trades'].sum())}")
        lines.append("Par annee :  annee  seances  rendement  Sharpe  DD max  trades/seance  levier moy.")
        for y, rr in r.groupby(r.index.year):
            sub = pan.loc[rr.index]
            lines.append(f"             {y}  {len(rr):7d}  {_p(float(np.prod(1 + rr) - 1)):>9}  {_f(_sharpe(rr)):>6}  {_p(_mdd(rr)):>6}  "
                         f"{_f(sub['trades'].mean()):>13}  {_f(sub.loc[sub['trade'], 'levier'].mean()):>11}")

        # --- robustesse ---
        lines.append("Robustesse :")
        k = max(1, int(math.ceil(0.01 * len(r))))
        r_wo = r.drop(r.nlargest(k).index)
        crisis = [int(x) for x in split_list(p.crisis_years) if str(x).strip().isdigit()]
        r_nc = r[~r.index.year.isin(crisis)]
        sh_all, sh_wo, sh_nc = _sharpe(r), _sharpe(r_wo), _sharpe(r_nc)
        lines.append(f"  toutes les seances               : Sharpe {_f(sh_all)}  CAGR {_p(_cagr(r))}")
        lines.append(f"  sans le top 1 % des seances ({k:3d}) : Sharpe {_f(sh_wo)}  CAGR {_p(_cagr(r_wo))}")
        lines.append(f"  hors {', '.join(map(str, crisis))}            : Sharpe {_f(sh_nc)}  CAGR {_p(_cagr(r_nc))}  ({len(r_nc)} seances)")
        top = r.nlargest(min(5, len(r)))
        lines.append("  meilleures seances : " + ", ".join(f"{d:%Y-%m-%d} {v:+.1%}" for d, v in top.items()))

        # --- regimes ---
        def regime_table(title, labels):
            lines.append(title)
            tot = r.sum()
            for lab in pd.unique(labels.dropna()):
                rr = r[labels.reindex(r.index) == lab]
                if len(rr) == 0:
                    continue
                lines.append(f"  {str(lab):12} {len(rr):5d} seances  rdt moyen {rr.mean() * 1e4:6.1f} bp  Sharpe {_f(_sharpe(rr)):>5}  "
                             f"seances gagnantes {_p((rr > 0).mean()):>6}  part du rendement {_p(rr.sum() / tot if tot else M.NAN):>7}")

        vx = pan["vix_veille"]
        if vx.notna().any():
            b = sorted(float(x) for x in split_list(p.vix_bounds))
            edges = [-np.inf] + b + [np.inf]
            names = [f"VIX<{b[0]:g}"] + [f"{b[i]:g}-{b[i + 1]:g}" for i in range(len(b) - 1)] + [f"VIX>={b[-1]:g}"]
            lab = pd.cut(vx, edges, labels=names, right=False).astype(object)
            regime_table(f"Regime VIX (cloture de la veille, {p.vix_symbol}) :", lab)
        else:
            lines.append(f"Regime VIX : {p.vix_symbol} absent des donnees (ajouter ^VIX.csv au dossier)")
            rv = (pan["cloture"] / pan["prev_close"] - 1).rolling(20).std().shift(1) * np.sqrt(252)
            if rv.notna().sum() > 60:
                q = rv.quantile([1 / 3, 2 / 3]).to_numpy()
                lab = pd.cut(rv, [-np.inf, q[0], q[1], np.inf], right=False,
                             labels=[f"vol<{q[0]:.0%}", f"{q[0]:.0%}-{q[1]:.0%}", f"vol>={q[1]:.0%}"]).astype(object)
                regime_table(f"  proxy : vol realisee 20 j de {self.symbol} a la veille (terciles de la periode) :", lab)
        gx = pan["gex"]
        if gx.notna().any():
            lab = pd.Series(np.where(gx.isna(), "inconnu", np.where(gx < 0, "court gamma", "long gamma")), index=gx.index)
            regime_table("Regime gamma (GEX des dealers, fiche 15) :", lab)
        else:
            lines.append("Regime gamma : pas de GEX (gex_file, format de Data/gex.csv de la fiche 15)")

        # --- donnees futures : rolls ---
        if spec.asset_class == "Future":
            gap = (pan["open"] / pan["prev_close"] - 1).abs().where(pan["valide"]).dropna()
            if len(gap) > 100:
                roll = gap.index.month.isin([3, 6, 9, 12]) & (gap.index.day >= 7) & (gap.index.day <= 16)
                big = gap > 4 * gap.median()
                share_big, share_all = float(roll[big].mean()) if big.any() else 0.0, float(roll.mean())
                warn = big.sum() >= 4 and share_big > 2.5 * share_all
                lines.append(f"Rolls : {_p(share_big)} des gaps > 4x la mediane tombent en fenetre de roll (attendu {_p(share_all)})"
                             + ("  -> DONNEES PROBABLEMENT NON AJUSTEES (NinjaTrader : Merge Back Adjusted ; "
                                "Databento .v.0 : -p roll_adjust=minuit_utc)" if warn else ""))

        # --- criteres de rejet ---
        lines.append("")
        lines.append("Criteres de rejet de la fiche :")
        if len(post) >= 60:
            sp = _sharpe(post)
            lines.append(("[OK]    " if sp >= 0.5 else "[REJET] ") + f"Sharpe net apres publication >= 0.50 : {_f(sp)} ({len(post)} seances)")
        else:
            lines.append(f"[ ]     Sharpe net apres publication : n/a ({len(post)} seances apres {p.publication_date})")
        lines.append(("[OK]    " if M.ok(sh_wo) and sh_wo >= 0.5 else "[ALERTE] ") +
                     f"performance hors top 1 % des seances : Sharpe {_f(sh_wo)} (contre {_f(sh_all)})")
        lines.append(("[OK]    " if M.ok(sh_nc) and sh_nc >= 0.5 else "[ALERTE] ") +
                     f"performance hors annees de crise : Sharpe {_f(sh_nc)}")
        lines.append("[ ]     plateau de parametres : python -m nexus grille -s 16 -p lookback_days=7,14,21,30 "
                     "-p band_mult=0.8,1,1.2,1.5 (tableaux croises + Sharpe des voisins)")
