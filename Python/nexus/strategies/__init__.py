"""Registre des strategies portees (numero de fiche -> classe)."""
from __future__ import annotations

import importlib

_MODULES = {
    "01": ("s01_tsmom", "Nexus01TSMOM"),
    "02": ("s02_xsmom", "Nexus02XSMOM"),
    "03": ("s03_multifactor", "Nexus03MultiFactorRotation"),
    "04A": ("s04a_residual", "Nexus04AResidualMeanReversion"),
    "04B": ("s04b_crypto", "Nexus04BCryptoIntradayReversal"),
    "05": ("s05_volmr", "Nexus05VolatilityMeanReversion"),
    "06": ("s06_pairs", "Nexus06PairsCointegration"),
    "07": ("s07_newsllm", "Nexus07NewsLlmEvent"),
    "08": ("s08_judge", "Nexus08LlmJudgeVeto"),
    "09": ("s09_consensus", "Nexus09LlmConsensus"),
    "10": ("s10_finbert", "Nexus10FinBertSentiment"),
    "11": ("s11_wheel", "Nexus11OptionsWheel"),
    "12": ("s12_volregime", "Nexus12VolRegimeConditional"),
    "13": ("s13_proptrend", "Nexus13PropTrend8"),
    "14": ("s14_strictswing", "Nexus14StrictSwing"),
    "16": ("s16_noisearea", "Nexus16NoiseArea"),
    "S1": ("s1_noiseareanq", "S1NoiseAreaNQ"),
}

ALIASES = {"1": "01", "2": "02", "3": "03", "4A": "04A", "4a": "04A", "04a": "04A", "4B": "04B", "4b": "04B", "04b": "04B",
           "5": "05", "6": "06", "7": "07", "8": "08", "9": "09",
           "NA": "16", "na": "16", "noise": "16", "NOISE": "16", "s1": "S1"}


def available() -> list[str]:
    return list(_MODULES)


def get(code: str):
    """Classe de strategie par numero de fiche ("01", "4A"...) ou par nom ("Nexus01_TSMOM")."""
    c = str(code).strip()
    c = ALIASES.get(c, c)
    if c not in _MODULES:
        for k, (mod, cls) in _MODULES.items():
            klass = getattr(importlib.import_module(f"{__name__}.{mod}"), cls)
            if c.lower() in (klass.NAME.lower(), cls.lower()):
                return klass
        raise KeyError(f"strategie inconnue '{code}'. Disponibles : {', '.join(_MODULES)}")
    mod, cls = _MODULES[c]
    return getattr(importlib.import_module(f"{__name__}.{mod}"), cls)
