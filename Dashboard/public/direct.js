// Tableau de bord Nexus : page « Groupe en direct ». Etat du compte demo et des strategies NinjaScript du Groupe, publie par
// l AddOn NexusPasserelle : passerelle, garde-fous, strategies du Groupe, cibles et positions, executions, journal.
// Donnees : Python/nexus/live -> donnees/live.json, relu toutes les 3 secondes. Lecture seule : le Groupe se modifie
// dans Python/nexus/live/groupe.json (relu par le moteur toutes les 5 s, sans redemarrage).
"use strict";

const Direct = (function () {
  var D = null, minuterie = null;

  function oublier() { D = null; }
  function nb(v, d) { return v == null || !isFinite(v) ? "–" : Number(v).toLocaleString("fr-FR", { minimumFractionDigits: d, maximumFractionDigits: d }); }
  function signe(v) { return v == null ? "–" : (v > 0 ? "+" + v : String(v)); }
  async function lire(statique) {
    var r = await fetch((statique ? "donnees/live.json" : "/api/annexe/live") + "?t=" + Date.now(), { cache: "no-store" });
    if (!r.ok) throw new Error("live.json absent : NinjaTrader (AddOn NexusTableau) ne publie pas encore l état du compte démo");
    return r.json();
  }

  async function page(statique) {
    $("#contenu").innerHTML = '<p class="vide">Chargement du Groupe en direct…</p>';
    D = await lire(statique);
    rendre();
    if (minuterie) clearInterval(minuterie);
    minuterie = setInterval(async function () {
      if (!window.etat || window.etat.page !== "direct" || window.etat.id) { clearInterval(minuterie); minuterie = null; return; }
      try {
        var n = await lire(statique);
        if (n.genere !== D.genere) { D = n; var y = window.scrollY; rendre(); window.scrollTo(0, y); }
      } catch (e) { /* fichier en cours d ecriture : reessai au prochain tour */ }
    }, 3000);
  }

  function puceStatut(s) {
    if (s === "active") return '<span class="puce bon"><i>✓</i>active</span>';
    if (s === "chauffe") return '<span class="puce moyen"><i>…</i>chauffe</span>';
    return '<span class="puce mauvais"><i>!</i>' + esc(s) + "</span>";
  }

  function rendre() {
    var P = D.passerelle || {}, S = D.strategies || [], I = D.instruments || {};
    var verrou = D.suspension ? "Groupe suspendu : " + D.suspension : (P.verrou ? P.verrou : "aucun");
    var compte = P.compte ? esc(P.compte) + (P.simulation ? " (simulation)" : " (REEL)") : "–";
    var alerte = P.hello && P.simulation === false
      ? '<div class="panneau encadre-reco"><h3>Compte non simule</h3><p>La passerelle refuse tout ordre sur ce compte tant que '
        + '"compte_reel_autorise" n est pas a true dans Documents\\NinjaTrader 8\\Nexus\\passerelle.json.</p></div>' : "";
    var lignesS = S.map(function (x) {
      var c = Object.keys(x.cibles || {}).map(function (k) { return esc(k) + " " + signe(x.cibles[k]); }).join(", ") || "à plat";
      var e = x.etat || {};
      var det = Object.keys(e).filter(function (k) { return e[k] != null && typeof e[k] !== "object"; })
        .map(function (k) { return esc(k.replace(/_/g, " ")) + " : " + esc(String(e[k])); }).join(" · ");
      return `<tr><td><strong>${esc(x.nom)}</strong><div class="discret">${esc(x.classe || "")}</div></td><td>${puceStatut(x.statut)}`
        + (x.remplacement_en_attente ? '<div class="discret">modifiee : remplacee une fois a plat</div>' : "")
        + (x.erreur ? `<div class="discret">${esc(x.erreur)}</div>` : "")
        + `</td><td>${esc((x.abonnements || []).join(", "))}</td><td>${c}</td><td class="discret">${det}</td></tr>`;
    }).join("") || '<tr><td colspan="5" class="discret">aucune strategie dans le registre</td></tr>';
    var lignesI = Object.keys(I).map(function (k) {
      var x = I[k], d = x.derniere_barre;
      var ecart = x.position != null && x.cible != null && x.position !== x.cible;
      return `<tr><td><strong>${esc(k)}</strong>${x.nom ? ' <span class="discret">' + esc(x.nom) + "</span>" : ""}</td>`
        + `<td>${signe(x.cible)}</td><td>${signe(x.position)}${ecart ? ' <span class="puce moyen"><i>…</i>en cours</span>' : ""}</td>`
        + `<td>${d ? esc(d.heure) + " ET · " + nb(d.c, 2) : "–"}</td></tr>`;
    }).join("") || '<tr><td colspan="4" class="discret">aucun instrument</td></tr>';
    var lignesX = (D.executions || []).slice().reverse().map(function (x) {
      return `<tr><td>${x.t ? new Date(x.t).toLocaleString("fr-FR", { timeZone: "America/New_York" }) + " ET" : "–"}</td><td>${esc(x.instrument)}</td><td>${signe(x.qty)}</td><td>${nb(x.prix, 2)}</td></tr>`;
    }).join("") || '<tr><td colspan="4" class="discret">aucune execution</td></tr>';
    var journal = (D.journal || []).slice().reverse().map(function (x) {
      return `<div><span class="discret">${esc(x.heure)} ET</span> ${x.strategie ? "<strong>[" + esc(x.strategie) + "]</strong> " : ""}${esc(x.texte)}</div>`;
    }).join("");
    $("#contenu").innerHTML = `<div class="archive direct-groupe"><div class="entete"><h2>Groupe en direct <span class="direct">● ${P.connecte ? "NinjaTrader connecté" : "NinjaTrader déconnecté"}</span></h2>
      <span class="discret">mis à jour le ${esc(D.genere || "–")} ET · relu toutes les 3 s</span></div>
      <p class="resume">Les stratégies du Groupe tournent <strong>dans NinjaTrader</strong> (NinjaScript <code>NexusGroupeS1</code>, <code>NexusGroupeGotobi</code>)
      sur le compte démo ; l'AddOn <strong>NexusTableau</strong> publie cet état toutes les 2 s. Garde-fous dans les stratégies : compte simulé seulement,
      plafond de contrats, interrupteur global. Activer ou désactiver une stratégie : onglet <strong>Strategies</strong> du Control Center ;
      tout arrêter : fenêtre <strong>Groupe</strong> (Control Center → New → Groupe).</p>
      ${alerte}
      <div class="kpis">
        <div class="kpi"><div class="v">${P.connecte ? "reliee" : "absente"}</div><div class="l">passerelle NinjaTrader</div></div>
        <div class="kpi"><div class="v">${compte}</div><div class="l">compte</div></div>
        <div class="kpi"><div class="v">${esc(verrou)}</div><div class="l">garde-fou actif</div></div>
        <div class="kpi"><div class="v">${nb(P.valeur_liquidative, 0)} $</div><div class="l">valeur liquidative</div></div>
        <div class="kpi"><div class="v">${nb(P.resultat_jour, 0)} $</div><div class="l">resultat depuis 18:00 ET</div></div>
        <div class="kpi"><div class="v">${esc(P.coupure_et || "–")}</div><div class="l">coupure (heure de New York)</div></div>
      </div>
      ${D.erreur_registre ? `<div class="panneau encadre-reco"><h3>Registre</h3><p>${esc(D.erreur_registre)}</p></div>` : ""}
      <div class="panneau"><h3>Strategies du Groupe</h3><div class="tablebox"><table><thead><tr><th>Strategie</th><th>Statut</th><th>Donnees</th>
        <th>Cible</th><th>Etat</th></tr></thead><tbody>${lignesS}</tbody></table></div></div>
      <div class="grille-2">
        <div class="panneau"><h3>Instruments</h3><div class="tablebox"><table><thead><tr><th>Instrument</th><th>Cible nette</th><th>Position</th>
          <th>Derniere barre</th></tr></thead><tbody>${lignesI}</tbody></table></div></div>
        <div class="panneau"><h3>Executions</h3><div class="tablebox"><table><thead><tr><th>Heure</th><th>Instrument</th><th>Quantite</th>
          <th>Prix</th></tr></thead><tbody>${lignesX}</tbody></table></div></div>
      </div>
      <div class="panneau"><h3>Journal</h3><div class="journal-direct">${journal || '<p class="discret">vide</p>'}</div></div></div>`;
  }

  return { page: page, oublier: oublier };
})();
