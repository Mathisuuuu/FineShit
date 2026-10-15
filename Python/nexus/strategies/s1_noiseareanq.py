"""S1_NoiseAreaNQ : Noise Area Intraday Momentum sur NQ, reglage valide et FIGE.

Meme moteur que la fiche 16 (s16_noisearea), parametres de strategie verrouilles :
sigma sur 30 seances, controle toutes les 30 min, bande x 1,2, vol cible 2 %/jour (14 seances), levier max 4,
couts de la table SPECS (NQ : 20 $/point, 2,25 $ par contrat, 1/2 tick par execution).
Seuls les reglages de donnees (fuseau, horodatage, rolls, calendrier), le capital et les dates restent libres.
Pour explorer d autres reglages : fiche 16 (`-s 16`).

Valide le 2026-10-15. Reference (Cotations NQ_v0_1m, 2016-01-04 -> 2026-08-28, 1 M$) : equity finale
5 717 822 $, 1 828 allers-retours, Sharpe 1,32. Le fichier autonome Python/S1_NoiseAreaNQ.py donne le meme
resultat et le rejeu vectorbt des executions aussi.
"""
from __future__ import annotations

from .s16_noisearea import Nexus16NoiseArea

FROZEN = dict(
    symbols="NQ",
    allow_short_selling=True,
    use_circuit_breakers=False,
    lookback_days=30,
    band_mult=1.2,
    check_interval_min=30,
    first_check_min=0,
    use_vwap_stop=True,
    vwap_entry_filter=True,
    stop_check="controle",
    execution="ouverture_suivante",
    exit_minutes_before_close=0,
    max_entries_per_day=0,
    sizing="vol_cible",
    target_daily_vol_pct=2.0,
    vol_lookback_days=14,
    max_leverage=4.0,
    fixed_leverage=1.0,
    fractional_units=False,
    point_value=None,
    tick_size=None,
    commission_per_unit=None,
    commission_min_per_order=None,
    slippage_ticks=None,
    dividends_file="",
    gex_file="",
)

REFERENCE = dict(debut="2016-01-04", fin="2026-08-28", capital=1_000_000.0, equity_finale=5_717_821.79, allers_retours=1828,
                 sharpe=1.32)


class S1NoiseAreaNQ(Nexus16NoiseArea):
    NAME = "S1_NoiseAreaNQ"
    DESCRIPTION = "S1 - Noise Area NQ, reglage valide et fige (sigma 30 seances, controle 30 min, bande x1,2)."
    TOUT_SYMBOLS = ("NQ",)
    VALIDATED = "2026-10-15"
    DEFAULTS = dict(FROZEN)
    # --- tableau de bord (python -m nexus tableau) ---
    TITRE = "S1 · Noise Area NQ"
    RESUME = ("Suivre le Nasdaq quand il sort franchement de sa zone de bruit habituelle de la journee, "
              "et tout fermer le soir.")
    FONCTIONNEMENT = [
        "Chaque minute de la seance (9:30-16:00 a New York), on connait l ecart moyen entre le prix et l ouverture "
        "observe a la meme minute sur les 30 seances precedentes : c est la zone de bruit (sigma).",
        "Bornes du jour : max(ouverture, cloture de la veille) x (1 + 1,2 sigma) en haut, "
        "min(ouverture, cloture de la veille) x (1 - 1,2 sigma) en bas.",
        "Toutes les 30 minutes (10:00, 10:30 ... 15:30) : au-dessus de la borne haute ET du VWAP -> acheteur ; "
        "sous la borne basse ET sous le VWAP -> vendeur ; sinon a plat (stop suiveur).",
        "Ordre execute a l ouverture de la minute suivante ; tout est ferme a la cloture (16:00, 13:00 les demi-seances).",
        "Taille : 2 % de risque journalier vise (volatilite des 14 dernieres seances), levier maximum 4.",
        "Couts : 2,25 $ par contrat et par execution + 1/2 tick de glissement.",
    ]
    POURQUOI = ("Quand le marche sort de sa zone de bruit, des acteurs contraints (couverture gamma des teneurs de "
                "marche, fonds a effet de levier, suiveurs de tendance) achetent ou vendent dans le meme sens : "
                "le mouvement a tendance a se prolonger jusqu au soir.")
    SOURCES = [("Zarattini, Aziz & Barbon (2024), Beat the Market: An Effective Intraday Momentum Strategy, SSRN 4824172",
                "https://papers.ssrn.com/sol3/papers.cfm?abstract_id=4824172")]
    PUBLICATION = "2024-06-01"
    ESSAIS = 177                      # 3 contrats x 48 reglages + 30 variantes + 3 bases (fiche 16)
    VAR_SHARPE_ESSAIS_ANNUALISE = 0.206   # variance des Sharpe annualises des 144 reglages ES / NQ / YM (grilles du 2026-10-14)
    GRILLE_FICHE = "16"
    GRILLE = dict(lookback_days=[7, 14, 21, 30], check_interval_min=[15, 30, 60], band_mult=[0.8, 1.0, 1.2, 1.5])
    SENSIBILITE = {
        "Couts": [("x0", dict(commission_per_unit=0.0, slippage_ticks=0.0)), ("x1 (reference)", {}),
                  ("x2", dict(commission_per_unit=4.5, slippage_ticks=1.0)), ("x3", dict(commission_per_unit=6.75, slippage_ticks=1.5))],
        "Latence": [("prix du controle (sans delai)", dict(execution="cloture")), ("ouverture de la minute suivante (reference)", {}),
                    ("1 minute de plus", dict(execution="cloture_suivante"))],
    }

    def __init__(self, **params):
        changed = {k: v for k, v in params.items() if k in FROZEN and v != FROZEN[k]}
        if changed:
            raise ValueError(f"{self.NAME} est fige (valide le {self.VALIDATED}) : parametre(s) non modifiable(s) "
                             f"{changed}. Pour explorer un autre reglage, utiliser la fiche 16 (-s 16).")
        super().__init__(**params)
