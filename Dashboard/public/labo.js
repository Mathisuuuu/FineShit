// Tableau de bord Nexus : page « Laboratoire » (en direct). Hypotheses testees par la recherche (papiers SSRN...), chacune
// rejouee dans vectorbt, et le calendrier d un mois rempli avec le plus de strategies fiables, toujours vivantes, courtes
// et non correlees. Donnees : Python/nexus/labo.py -> donnees/labo.json, relu toutes les 5 secondes.
"use strict";

const Labo = (function () {
  var D = null, minuterie = null, vue = { mois: null, autres: false, filtre: "toutes", seuil: "400" };
  var COUL = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#6250d6", "#e34948"];

  function oublier() { D = null; }
  function nb(v, d) { return v == null || !isFinite(v) ? "–" : v.toLocaleString("fr-FR", { minimumFractionDigits: d, maximumFractionDigits: d }); }
  function pc(v, d) { return v == null || !isFinite(v) ? "–" : nb(v * 100, d == null ? 0 : d) + " %"; }
  function hh(k) { return String(Math.floor(k / 2)).padStart(2, "0") + ":" + (k % 2 ? "30" : "00"); }
  async function lire(statique) {
    var r = await fetch((statique ? "donnees/labo.json" : "/api/annexe/labo") + "?t=" + Date.now(), { cache: "no-store" });
    if (!r.ok) throw new Error("labo.json absent : lancer python -m nexus.labo --remplir (depuis Python/)");
    return r.json();
  }
  function parId() { var o = {}; (D.strategies || []).forEach(function (x) { o[x.id] = x; }); return o; }
  function statut(x) {
    var s = x.statut, st = x.stats || {};
    if (s === "retenue") return '<span class="puce bon"><i>✓</i>retenue (methode)</span>';
    if (s === "fiable" || st.fiable) return st.vivante === false ? '<span class="puce moyen"><i>!</i>fiable, eteinte</span>'
      : (st.courte === false ? '<span class="puce moyen"><i>!</i>fiable, trop longue</span>' : '<span class="puce bon"><i>✓</i>fiable</span>');
    return '<span class="puce neutre"><i>–</i>rejetee</span>';
  }

  async function page(statique) {
    $("#contenu").innerHTML = '<p class="vide">Chargement du laboratoire…</p>';
    D = await lire(statique);
    rendre();
    if (minuterie) clearInterval(minuterie);
    minuterie = setInterval(async function () {
      if (!window.etat || window.etat.page !== "labo" || window.etat.id) { clearInterval(minuterie); minuterie = null; return; }
      try {
        var n = await lire(statique);
        if (n.genere !== D.genere) { D = n; var y = window.scrollY; rendre(); window.scrollTo(0, y); }
      } catch (e) { /* fichier en cours d ecriture : reessai au prochain tour */ }
    }, 5000);
  }

  function rendre() {
    var P = parId(), S = D.strategies || [], C = D.criteres || {};
    var seuils = D.seuils || ["400"];
    if (seuils.indexOf(vue.seuil) < 0) vue.seuil = seuils[0];
    var E = (D.ensembles || {})[vue.seuil] || null;
    var fiables = S.filter(function (x) { return (x.stats || {}).fiable; });
    var adm = (D.admissibles_par_seuil || {})[vue.seuil] || D.admissibles || [];
    var membres = E ? E.ids : [];
    var cours = D.en_cours ? `<div class="panneau encadre-reco"><h3>En cours : ${esc(D.en_cours.code)} · ${esc(D.en_cours.titre)}</h3>
      <p class="note">${esc(D.en_cours.etape)} (depuis ${esc(D.en_cours.depuis)})</p></div>` : "";
    $("#contenu").innerHTML = `<div class="archive labo"><div class="entete"><h2>Laboratoire <span class="direct">● en direct</span></h2>
      <span class="discret">mis a jour le ${esc(D.genere || "–")} · relu toutes les 5 s</span></div>
      <p class="resume">Chaque hypothese (regle fixee avant le calcul, d apres un papier) est rejouee dans <strong>vectorbt</strong> (ordres a
      l entree et a la sortie, frais par cote) ; toutes les statistiques viennent de vectorbt. Une strategie entre dans le calendrier si elle est
      <strong>fiable</strong> (borne basse de l IC du Sharpe &gt; 0, Sharpe &gt; 0 sur 2016-2020 et 2021-2026), <strong>toujours vivante</strong>
      (Sharpe &gt; 0 sur les 24 derniers mois) et si son <strong>temps a surveiller</strong> reste sous le seuil choisi : une strategie qui peut se
      declencher <em>tous les jours</em> occupe sa fenetre chaque jour de bourse (meme sans position) ; une strategie d <em>evenements</em> connus
      a l avance (jours gotobi, resultats) ne coute que ses jours. Le but : remplir le mois avec le plus de strategies possible, deux a deux non
      correlees (correlation ≤ ${nb(C.corr_max, 1)}, pas le meme contrat aux memes heures).</p>
      <div class="outils"><label>Temps a surveiller au plus, par strategie <select id="l-seuil">${seuils.map(function (k) {
        return `<option value="${k}">${k === "None" ? "sans limite" : k + " h par an"}</option>`; }).join("")}</select></label></div>
      ${cours}
      <div class="kpis">
        <div class="kpi"><div class="v">${S.length}</div><div class="l">strategies testees</div></div>
        <div class="kpi"><div class="v">${fiables.length}</div><div class="l">fiables</div></div>
        <div class="kpi"><div class="v">${adm.length}</div><div class="l">fiables, vivantes, sous le seuil de temps</div></div>
        <div class="kpi"><div class="v">${membres.length}</div><div class="l">dans le mois (non correlees)</div></div>
        <div class="kpi"><div class="v">${E ? nb(E.sharpe, 2) : "–"}</div><div class="l">Sharpe de l ensemble</div></div>
        <div class="kpi"><div class="v">${nf0(D.essais_programme)}</div><div class="l">essais comptes (Sharpe deflate)</div></div>
      </div>
      ${ensemble(E, P)}
      <div class="panneau"><h3>Le mois, jour par jour (heure de New York)</h3>
        <div class="outils"><label>Mois <select id="l-mois"></select></label>
        <label class="case"><input type="checkbox" id="l-autres"${vue.autres ? " checked" : ""}> Montrer aussi les autres strategies fiables (en gris)</label></div>
        <div id="l-cal"></div><div id="l-legende" class="legende-labo"></div></div>
      ${zones(P)}
      <div class="panneau"><h3>Toutes les strategies testees</h3>
        <div class="outils"><label>Afficher <select id="l-filtre"><option value="toutes">toutes</option><option value="fiables">fiables</option>
        <option value="admissibles">dans le calendrier possible (fiables, vivantes, sous le seuil)</option><option value="rejetees">rejetees</option></select></label></div>
        <div class="tablebox"><table><thead><tr><th>Strategie (hypothese)</th><th>Zone</th><th>Contrats</th><th>Verdict</th>
        <th class="num">Sharpe [IC 95 %]</th><th class="num">1re / 2e moitie</th><th class="num">12 / 24 derniers mois</th><th class="num">Sharpe deflate</th>
        <th class="num">Heures a surveiller / an</th><th class="num">En position / an</th><th class="num">% par 100 h</th><th>Testee le</th></tr></thead>
        <tbody id="l-table"></tbody></table></div></div>
      <div class="panneau"><h3>Journal</h3><div class="journal-labo">${(D.journal || []).slice(-40).reverse().map(function (j) {
        return `<div><span class="discret">${esc(j.t)}</span> ${esc(j.msg)}</div>`; }).join("")}</div></div></div>`;
    calendrierInit(P, membres, adm);
    $("#l-seuil").value = vue.seuil;
    $("#l-seuil").addEventListener("change", function () { vue.seuil = this.value; var y = window.scrollY; rendre(); window.scrollTo(0, y); });
    $("#l-filtre").value = vue.filtre;
    $("#l-filtre").addEventListener("change", function () { vue.filtre = this.value; table(P, adm); });
    table(P, adm);
  }
  function nf0(v) { return v == null ? "–" : Math.round(v).toLocaleString("fr-FR"); }

  function ensemble(E, P) {
    if (!E) return '<div class="panneau"><h3>Aucune strategie admissible</h3></div>';
    return `<div class="panneau encadre-reco"><h3>Le plus de strategies fiables et non correlees : ${E.ids.length}</h3>
      <div class="membres-labo">${E.ids.map(function (i, k) {
        var x = P[i] || {}, s = x.stats || {};
        return `<div class="membre"><span class="pastille" style="background:${COUL[k % COUL.length]}"></span><div>${lien(x)}
          <div class="src">${esc(zoneNom(x.zone))} · ${x.type_jours === "evenements" ? "jours d evenement (" + nb(x.jours_par_an, 0) + " par an)" : "tous les jours"}
          · ${nb(s.heures_surveillance, 0)} h a surveiller par an · Sharpe ${nb(s.sharpe, 2)} · 24 derniers mois ${nb(s.sharpe_24m, 2)}</div></div></div>`;
      }).join("")}</div>
      <div class="kpis">
        <div class="kpi"><div class="v">${nb(E.sharpe, 2)}</div><div class="l">Sharpe [${nb(E.ic_bas, 2)} ; ${nb(E.ic_haut, 2)}]</div></div>
        <div class="kpi"><div class="v">${nb(E.sharpe_p1, 2)} / ${nb(E.sharpe_p2, 2)}</div><div class="l">2016-2020 / 2021-2026</div></div>
        <div class="kpi"><div class="v">${nb(E.sharpe_12m, 2)} / ${nb(E.sharpe_24m, 2)}</div><div class="l">12 / 24 derniers mois</div></div>
        <div class="kpi"><div class="v">${pc(E.perte_max, 1)}</div><div class="l">perte max (meme risque)</div></div>
        <div class="kpi"><div class="v">${nb(E.heures_an, 0)} h</div><div class="l">a surveiller par an</div></div>
        <div class="kpi"><div class="v">${nb(E.corr_max, 2)}</div><div class="l">correlation max</div></div>
      </div></div>`;
  }
  function lien(x) {
    return x.origine === "tableau de bord" ? `<a href="#" data-route="s/${encodeURIComponent(x.id)}/apercu">${esc(x.nom || x.id)}</a>` : esc(x.nom || x.id);
  }
  function zoneNom(c) { var z = (D.zones || []).find(function (z) { return z.code === c; }); return z ? z.nom : (c || "–"); }

  function zones(P) {
    var S = D.strategies || [];
    return `<div class="panneau"><h3>Meilleure strategie par zone</h3><div class="zones-labo">${(D.zones || []).map(function (z) {
      var b = D.par_zone && D.par_zone[z.code] ? P[D.par_zone[z.code]] : null;
      var n = S.filter(function (x) { return x.zone === z.code; }).length;
      return `<div class="zone ${b ? "" : "vide"}"><div class="nomz">${esc(z.nom)} <span class="discret">${hh(z.debut / 30)}-${hh(z.fin / 30)}</span></div>
        ${b ? `<div>${esc(b.nom)}</div><div class="src">Sharpe ${nb(b.stats.sharpe, 2)} [${nb(b.stats.ic_bas, 2)} ; ${nb(b.stats.ic_haut, 2)}]</div>`
          : '<div class="src">aucune strategie fiable et vivante : a remplir</div>'}
        <div class="src">${n} strategie(s) testee(s) dans cette zone</div></div>`;
    }).join("")}</div></div>`;
  }

  function calendrierInit(P, membres, adm) {
    var montre = membres.slice();
    var gris = (D.strategies || []).filter(function (x) { return (x.stats || {}).fiable && x.occupation && montre.indexOf(x.id) < 0; }).map(function (x) { return x.id; });
    var moisSet = {};
    montre.concat(gris).forEach(function (i) { Object.keys((P[i] || {}).occupation || {}).forEach(function (d) { moisSet[d.slice(0, 7)] = 1; }); });
    var mois = Object.keys(moisSet).sort().reverse();
    if (!vue.mois || mois.indexOf(vue.mois) < 0) vue.mois = mois[0];
    $("#l-mois").innerHTML = mois.map(function (m) { return `<option value="${m}">${m}</option>`; }).join("");
    $("#l-mois").value = vue.mois;
    $("#l-mois").addEventListener("change", function () { vue.mois = this.value; calendrier(P, montre, gris); });
    $("#l-autres").addEventListener("change", function () { vue.autres = this.checked; calendrier(P, montre, gris); });
    calendrier(P, montre, gris);
  }

  function calendrier(P, montre, gris) {
    if (!vue.mois) { $("#l-cal").innerHTML = '<p class="vide">Aucune position.</p>'; return; }
    var ids = montre.concat(vue.autres ? gris : []);
    var a = +vue.mois.slice(0, 4), m = +vue.mois.slice(5, 7), n = new Date(a, m, 0).getDate();
    var bande = "", tete = "";
    for (var k = 0; k < 48; k++) {
      var mn = k * 30, z = (D.zones || []).find(function (z) { return z.debut < z.fin ? (mn >= z.debut && mn < z.fin) : (mn >= z.debut || mn < z.fin); });
      bande += `<div class="b" title="${z ? esc(z.nom) : "pause du CME"}" style="background:${z ? "var(--z-" + z.code + ")" : "transparent"}"></div>`;
      tete += `<div class="h">${k % 4 === 0 ? Math.floor(k / 2) + "h" : ""}</div>`;
    }
    var lignes = "", compte = {};
    for (var j = 1; j <= n; j++) {
      var d = vue.mois + "-" + String(j).padStart(2, "0"), dow = new Date(a, m - 1, j).getDay();
      var cells = "";
      for (var k2 = 0; k2 < 48; k2++) {
        var act = ids.filter(function (i) { var o = (P[i].occupation || {})[d]; return o && o.indexOf(k2) >= 0; });
        var fen = ids.filter(function (i) { return act.indexOf(i) < 0 && eligible(P[i], d, dow) && (P[i].fenetre || []).indexOf(k2) >= 0; });
        act.forEach(function (i) { compte[i] = compte[i] || {}; compte[i][d] = 1; });
        var bar = ids.filter(function (i) { return act.indexOf(i) >= 0 || fen.indexOf(i) >= 0; }).map(function (i) {
          var c = montre.indexOf(i) >= 0 ? COUL[montre.indexOf(i) % COUL.length] : "#9aa0a8";
          return `<span style="background:${c};opacity:${act.indexOf(i) >= 0 ? 1 : 0.28}"></span>`; }).join("");
        var tip = (act.length ? "en position : " + act.map(function (i) { return P[i].nom; }).join(", ") : "")
          + (fen.length ? (act.length ? " ; " : "") + "a surveiller : " + fen.map(function (i) { return P[i].nom; }).join(", ") : "");
        cells += `<div class="c${k2 === 34 || k2 === 35 ? " pause" : ""}" title="${d} ${hh(k2)}-${hh(k2 + 1)} : ${esc(tip || "rien")}">${bar}</div>`;
      }
      lignes += `<div class="j${dow === 0 || dow === 6 ? " we" : ""}">${["di", "lu", "ma", "me", "je", "ve", "sa"][dow]} ${j}</div>${cells}`;
    }
    $("#l-cal").innerHTML = `<div class="cal-labo"><div class="j"></div>${bande}<div class="j"></div>${tete}${lignes}</div>`;
    $("#l-legende").innerHTML = ids.map(function (i) {
      var c = montre.indexOf(i) >= 0 ? COUL[montre.indexOf(i) % COUL.length] : "#9aa0a8", x = P[i];
      return `<span><span class="pastille" style="background:${c}"></span>${esc(x.nom)} · ${x.type_jours === "evenements" ? "jours d evenement" : "tous les jours"}
        · en position ${Object.keys(compte[i] || {}).length} jour(s) ce mois</span>`;
    }).join("") + '<span class="discret">couleur pleine : en position · couleur claire : fenetre a surveiller</span>';
  }

  function eligible(x, d, dow) {
    if (x.type_jours === "evenements") return !!(x.occupation || {})[d];
    return dow >= 1 && dow <= 5;
  }

  function table(P, adm) {
    var S = (D.strategies || []).slice().sort(function (a, b) { return String(b.teste_le).localeCompare(String(a.teste_le)); });
    S = S.filter(function (x) {
      var s = x.stats || {};
      if (vue.filtre === "fiables") return s.fiable;
      if (vue.filtre === "admissibles") return adm.indexOf(x.id) >= 0;
      if (vue.filtre === "rejetees") return !s.fiable;
      return true;
    });
    $("#l-table").innerHTML = S.map(function (x) {
      var s = x.stats || {};
      var nom = lien(x);
      return `<tr class="fixe"><td>${nom}${x.lien ? `<div class="src"><a href="${esc(x.lien)}" target="_blank" rel="noopener">${esc(x.source || "source")}</a></div>`
          : (x.source ? `<div class="src">${esc(x.source)}</div>` : "")}</td>
        <td>${esc(zoneNom(x.zone))}${x.heures ? `<div class="src">${esc(x.heures)}</div>` : ""}</td><td>${esc((x.instruments || []).join(", "))}</td><td>${statut(x)}</td>
        <td class="num">${nb(s.sharpe, 2)}${s.ic_bas != null ? `<div class="src">[${nb(s.ic_bas, 2)} ; ${nb(s.ic_haut, 2)}]</div>` : ""}</td>
        <td class="num">${nb(s.sharpe_p1, 2)} / ${nb(s.sharpe_p2, 2)}</td><td class="num">${nb(s.sharpe_12m, 2)} / ${nb(s.sharpe_24m, 2)}</td>
        <td class="num">${pc(s.dsr, 1)}</td><td class="num">${nb(s.heures_surveillance, 0)}${x.type_jours ? `<div class="src">${x.type_jours === "evenements" ? "evenements" : "tous les jours"}</div>` : ""}</td>
        <td class="num">${nb(s.heures_an, 0)}</td><td class="num">${nb(s.par_100h * 100, 1)}</td>
        <td class="src">${esc(x.teste_le || "")}</td></tr>`;
    }).join("");
  }

  return { page: page, oublier: oublier };
})();
