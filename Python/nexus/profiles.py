"""Profils de parametres par jeu de donnees.

Les fiches ont ete ecrites pour des actions/ETF US et de la crypto. Le profil "futures" les adapte au
dossier Cotations (10 contrats continus Databento : ES, NQ, YM, FDAX, GC, CL, 6E, 6B, 6J, 6A) :

  - univers et barometre (ES remplace SPY, NQ remplace QQQ) ;
  - micro-contrats (MES, MNQ, MGC, M6E...) et capital de 1 000 000 $ : avec un contrat standard
    (ES = 50 $ x ~6 500 points ~ 325 000 $ de notionnel), une volatilite cible de 12 % repartie sur
    10 marches demande plusieurs millions ; avec les micros, 1 M$ donne des quantites realistes ;
  - plafonds du module B : ils sont exprimes en NOTIONNEL (3 % / 10 % / 30 % / 50 % du capital),
    calibres pour des actions sans levier. Sur futures, le notionnel n est pas le capital engage :
    on garde seulement un plafond d exposition brute de 300 % (levier 3) et la taille propre a chaque
    fiche (volatilite cible, risque au stop) ;
  - frais : 2.50 $ par contrat et par ordre (commission + frais de bourse, ordre de grandeur) en plus
    du glissement de 0.05 % du module C ;
  - fiche 6 : vente a decouvert autorisee (pas d emprunt de titres sur futures) et paires par secteur ;
  - fiche 13 : les 8 actifs de la fiche en futures (6E, 6B, 6J, 6A, GC, ES, NQ, FDAX).

Les fiches 3 (fondamentaux), 4A (ETF sectoriels), 4B (crypto 15 min), 7 a 10 (actualites) et 11
(options sur actions) n ont pas d equivalent futures : elles ne font pas partie du profil.
Tout parametre passe en ligne de commande (-p nom=valeur) remplace celui du profil.
"""
from __future__ import annotations

FUTURES_ALL = "ES,NQ,YM,FDAX,GC,CL,6E,6B,6J,6A"

_FUTURES_COMMON = dict(
    futures_micro=True,
    initial_bankroll=1_000_000.0,
    per_contract_fee=2.5,
    max_trade_pct=0.0,
    max_symbol_pct=0.0,
    max_class_pct=0.0,
    max_total_pct=300.0,
)

PROFILES: dict[str, dict[str, dict]] = {
    "futures": {
        "01": dict(_FUTURES_COMMON, symbols=FUTURES_ALL, barometer="ES"),
        "02": dict(_FUTURES_COMMON, symbols=FUTURES_ALL, barometer="ES"),
        "05": dict(_FUTURES_COMMON, symbols="ES,NQ", allocation_per_asset_pct=50.0),
        "06": dict(_FUTURES_COMMON, symbols=FUTURES_ALL, allow_short_selling=True,
                   pairs_list="ES/NQ,ES/YM,NQ/YM,ES/FDAX,6E/6B,6E/6A,6B/6A,6E/6J,GC/6A"),
        "12": dict(_FUTURES_COMMON, symbols=FUTURES_ALL, barometer="ES"),
        "13": dict(_FUTURES_COMMON, symbols="6E,6B,6J,6A,GC,ES,NQ,FDAX", max_total_pct=0.0,
                   currency_map="6E=EUR;6B=GBP;6J=JPY;6A=AUD;GC=USD;ES=USD;NQ=USD;FDAX=EUR"),
        "14": dict(_FUTURES_COMMON, symbols=FUTURES_ALL, barometer="ES", exclude_if_no_earnings_data=False),
    },
}

DESCRIPTIONS = {
    "futures": "Dossier Cotations (futures Databento) : micro-contrats, 1 M$, barometre ES, plafonds de notionnel leves (levier max 3).",
}


def available_profiles() -> list[str]:
    return sorted(PROFILES)


def profile_params(profile: str | None, code: str) -> dict | None:
    """Parametres du profil pour une fiche ; {} si pas de profil ; None si la fiche n est pas couverte."""
    if not profile:
        return {}
    prof = PROFILES.get(profile.lower())
    if prof is None:
        raise KeyError(f"profil inconnu '{profile}'. Disponibles : {', '.join(available_profiles())}")
    return dict(prof[code]) if code in prof else None


def profile_codes(profile: str | None) -> list[str] | None:
    if not profile:
        return None
    return list(PROFILES[profile.lower()])
