"""Jambes du book Kairos, deuxieme lot, testees sans papier (critere 1 assoupli le 2026-10-25) : TROIS essais, n° 441-443.

    python -m nexus.perso.kairos_jambes2 [--sortie resultats_kairos_jambes2.txt]

PROTOCOLE ECRIT LE 2026-10-26 AVANT LE CALCUL. Aucun parametre n est choisi apres avoir vu un resultat. Moteur, couts,
temoin, criteres et verifications : ceux de kairos_jambes.py (premier lot, essais 436-437), sans aucun changement.

Origine (demande de l utilisateur du 2026-10-26 : « combien de strategies pour egaler Kairos, fais tout ce qui est
possible pour trouver des strategies correspondantes »)
  Book de Kairos (registre n° 344-350) : 8-9 jambes, ≈ 4 NQ, 3 or, 1 ES, sur Asie, Londres et New York, une position a
  la fois ; « Kairos Max » (n° 350) : cassure d ouverture sur 6 micros dont MGC et MCL. Chez nous : S1 (NQ New York) et
  Gotobi (6J) valides ; M2 (NQ New York) a confirmer. Deja testes et rejetes : or Asie -> Londres (K1, 436), IB ES
  (K2, 437), momentum C (439), IntradayVolBreakout fiable non retenu (438, replique GC -0,04), filtre M2 sur GC (0,59),
  10 anomalies de l or (n° 69), or la nuit conforme (H10, deflate 0,19).
  Familles de leur book JAMAIS testees chez nous, retenues ici (regles standard des praticiens, aucune regle Kairos
  publiee) :
    - n° 351 : NQ la nuit, cassure Asie -> Londres (leurs jambes NQ hors New York) ;
    - n° 352 : or, cassure du range d ouverture du COMEX (famille ORB de « Kairos Max » sur MGC) ;
    - n° 353 : petrole, cassure du range d ouverture du NYMEX (famille ORB de « Kairos Max » sur MCL).
  Aucun chiffre d effet mesure sur le meme objet : pas de calcul de puissance (critere 6 : « quand un chiffre existe »).
  Papier contraire connu : Fetna 2026 (SSRN 7428398, registre n° 122) : aucune cassure d ouverture simple ne survit aux
  couts sur 9 futures americains en 16 ans ; nos ORB sur ES et YM ont deja echoue (n° 45), K1 et K2 aussi.
  Trois essais : ESSAIS_PROGRAMME 440 -> 443 (repliques et micros ne sont pas des essais).

Regles figees (heures de New York, barres 1 minute ; une barre « a l heure H » est celle qui COMMENCE a H)
  K6 (essai 441) - NQ, cassure Asie -> Londres (micro MNQ ; replique ES / MES, pas un essai) :
    exactement les heures de K1 pour le range et l entree : range 19:00 (la veille) -> 03:00, entree 03:00 -> 08:00,
    stop a l autre borne ; sortie a l ouverture de la barre de 09:25, AVANT l ouverture de New York, pour ne jamais
    tenir NQ en meme temps que S1 (premier controle 10:00) ni M2 (entree 9:35) : critere 19.
  K7 (essai 442) - or, cassure du range d ouverture du COMEX (micro MGC) :
    range 08:20 -> 08:35 (15 premieres minutes du COMEX), entree 08:35 -> 11:00, stop a l autre borne, sortie a
    l ouverture de la barre de 13:25 (avant la cloture du COMEX a 13:30).
  K8 (essai 443) - petrole, cassure du range d ouverture du NYMEX (micro MCL) :
    range 09:00 -> 09:15 (15 premieres minutes du NYMEX), entree 09:15 -> 11:30, stop a l autre borne, sortie a
    l ouverture de la barre de 14:25 (avant le reglement de 14:30).
  Ordres (comme K1) : stop d achat au plus haut + 1 tick, stop de vente au plus bas - 1 tick, le premier touche annule
  l autre, un trade par jour. Execution, exclusions (range < 80 % des minutes, prix absent a la sortie, changement
  d echeance), temoin neutre (memes jours, meme instant d entree, sortie a l heure, sans stop, sens au hasard, graine 7),
  couts (1 tick + 2,50 $ par cote, stress 2 ticks, micros au meme tarif par cote) : ceux de kairos_jambes.py.
  Conformite prop (critere 21) : a plat avant 16:10, jamais de week-end. Conflit de contrat (critere 19) : aucun avec S1
  (MNQ 9:30-16:00), M2 ni Gotobi (6J) ; K7 et K8 sont sur d autres contrats ; K6 sort avant 9:30.
Criteres : n° 10-14, 16-18 (Sharpe deflate avec 441, 442 puis 443 essais), 19, 20 (correlation avec S1 et Gotobi)
  seulement si le reste passe. Verification du calcul (critere 9, sans regarder le gain) : horodatage, anticipation,
  rejeu vectorbt, 5 trades tires au hasard, comptes ; un bug trouve se documente ici avec les deux executions.
Verification faite le 2026-10-26 AVANT tout calcul de gain : horodatage, anticipation et rejeu vectorbt bons pour les
  trois jambes ; trades tires au hasard verifies sur les barres brutes (K6 2022-09-21, K7 2019-10-11 : au tick pres).
  Particularite (pas un bug de regle) : la serie CL est ajustee par RATIO aux changements d echeance ; le prix reel
  (ajuste - decalage de la barre d entree) est donc reconstitue a quelques cents pres (0,01 $ sur le trade K8 du
  2024-01-02), sans effet sur le sens ni l heure des trades. Laisse tel quel, comme dans les autres etudes CL.
Si une jambe passe : elle reste CANDIDATE (pas de variante), on la met dans le simulateur prop avant toute decision.
"""
from __future__ import annotations

import argparse

from . import kairos_jambes as KJ

JAMBES = {
    "K6": dict(nom="NQ, cassure Asie -> Londres (sortie avant New York)", root="NQ", essai=441,
               range_=((19, 0), (3, 0)), veille=True, entree=((3, 0), (8, 0)), sortie=(9, 25), stop="borne"),
    "K7": dict(nom="Or, cassure du range d ouverture du COMEX (15 min)", root="GC", essai=442,
               range_=((8, 20), (8, 35)), veille=False, entree=((8, 35), (11, 0)), sortie=(13, 25), stop="borne"),
    "K8": dict(nom="Petrole, cassure du range d ouverture du NYMEX (15 min)", root="CL", essai=443,
               range_=((9, 0), (9, 15)), veille=False, entree=((9, 15), (11, 30)), sortie=(14, 25), stop="borne"),
}
REPLIQUES = {"K6": ["ES"]}
TITRE = [" JAMBES DU BOOK KAIROS SANS PAPIER, DEUXIEME LOT (critere 1 assoupli) - TROIS ESSAIS (n° 441, 442 et 443)",
         "K6 : NQ, range 19:00 -> 3:00 ET, cassure 3:00 -> 8:00, stop a l autre borne, sortie 9:25.",
         "K7 : GC, range 8:20 -> 8:35, cassure 8:35 -> 11:00, stop a l autre borne, sortie 13:25.",
         "K8 : CL, range 9:00 -> 9:15, cassure 9:15 -> 11:30, stop a l autre borne, sortie 14:25."]
KJ.REGISTRE.update(JAMBES)


def etude(sortie: str | None = None, log=print) -> dict:
    return KJ.etude(sortie, log, jambes=JAMBES, repliques=REPLIQUES, titre=TITRE, fichier="resultats_kairos_jambes2.txt")


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--sortie", default=None)
    a = ap.parse_args(argv)
    etude(a.sortie)


if __name__ == "__main__":
    main()
