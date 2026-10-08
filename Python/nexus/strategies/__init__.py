"""Registre des strategies portees (numero de fiche -> classe)."""
from __future__ import annotations

import importlib

_MODULES = {
    "01": ("s01_tsmom", "Nexus01TSMOM"),
    "02": ("s02_xsmom", "Nexus02XSMOM"),
    "03": ("s03_multifactor", "Nexus03MultiFactorRotation"),
    "04A": ("s04a_residual", "Nexus04AResidualMeanReversion"),
    "05": ("s05_volmr", "Nexus05VolatilityMeanReversion"),
    "06": ("s06_pairs", "Nexus06PairsCointegration"),
    "12": ("s12_volregime", "Nexus12VolRegimeConditional"),
    "13": ("s13_proptrend", "Nexus13PropTrend8"),
    "14": ("s14_strictswing", "Nexus14StrictSwing"),
}

ALIASES = {"1": "01", "2": "02", "3": "03", "4A": "04A", "4a": "04A", "04a": "04A", "5": "05", "6": "06"}


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
