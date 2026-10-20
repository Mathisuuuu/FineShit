// Tableau de bord Nexus : page « Profil horaire ». Heures ou les strategies fiables sont en position sur les 365 derniers
// jours de donnees (heure de New York, demi-heures), plages vides, et hypotheses testees pour les remplir.
// Donnees : python -m nexus.profil_horaire (appele par python -m nexus tableau) -> donnees/profil.json.
"use strict";

const Profil = (function () {
  var D = null, promesse = null;

  async function charger(statique) {
    if (D) return D;
    if (!promesse) {
      promesse = (async function () {
        var r = await fetch(statique ? "donnees/profil.json" : "/api/annexe/profil", { cache: "no-store" });
        if (!r.ok) throw new Error("profil horaire absent : lancer python -m nexus.profil_horaire (depuis Python/)");
        D = await r.json();
        return D;
      })();
      promesse.catch(function () { promesse = null; });
    }
    return promesse;
  }
  function oublier() { D = null; promesse = null; }
  function nb(v, d) { return v == null || !isFinite(v) ? "–" : v.toLocaleString("fr-FR", { minimumFractionDigits: d, maximumFractionDigits: d }); }
  function pc(v, d) { return v == null || !isFinite(v) ? "–" : nb(v * 100, d == null ? 0 : d) + " %"; }

  async function page(statique) {
    $("#contenu").innerHTML = '<p class="vide">Chargement du profil horaire…</p>';
    await charger(statique);
    var F = D.fiables;
    var hyp = D.hypotheses || [];
    var autres = Object.keys(D.profils).filter(function (i) { return !D.fiabilite[i]; });
    // pour chaque plage vide : les strategies non fiables qui y sont en position (part moyenne des jours)
    var vide = D.couverture.map(function (v) { return v < D.seuil_vide; });
    var dansVide = autres.map(function (i) {
      var p = D.profils[i], s = 0, k = 0;
      p.forEach(function (v, j) { if (vide[j]) { s += v; k++; } });
      return { id: i, part: k ? s / k : 0 };
    }).filter(function (x) { return x.part > 0.005; }).sort(function (a, b) { return b.part - a.part; });
    $("#contenu").innerHTML = `<div class="archive"><div class="entete"><h2>Profil horaire sur un an</h2></div>
      <p class="resume">Demi-heures (heure de New York) ou les <strong>strategies fiables</strong> du tableau de bord sont en position, du
      ${esc(D.debut)} au ${esc(D.fin)}. Fiable = borne basse de l'IC a 95 % du Sharpe au-dessus de 0 et Sharpe positif sur les deux moities
      (statistiques vectorbt de l'onglet Prop firm). Plages vides (moins de ${pc(D.seuil_vide)} des jours couverts) :
      <strong>${esc(D.vides.join(", ") || "aucune")}</strong>.</p>
      <div class="kpis">${F.map(function (f) {
        var p = D.profils[f.id] || [], tot = p.reduce(function (a, b) { return a + b; }, 0) * D.pas_minutes / 60;
        return `<div class="kpi"><span class="lib">${esc(f.titre)}</span><span class="val">${nb(tot, 1)} h</span><span class="aide">en position par jour en moyenne ; ${esc((f.instruments || []).join(", "))}</span></div>`;
      }).join("")}<div class="kpi"><span class="lib">Couverture d'une journee</span><span class="val">${nb(D.couverture.reduce(function (a, b) { return a + b; }, 0) * D.pas_minutes / 60, 1)} h</span><span class="aide">heures avec au moins une strategie fiable, en moyenne par jour</span></div></div>
      <div class="panneau"><h3>Carte de l'annee</h3><p class="sous">Une ligne par jour, une colonne par demi-heure (New York). Couleur = nombre de
        strategies fiables en position ; survol : lesquelles.</p><div class="graph" id="g-pr-carte" style="height:620px"></div></div>
      <div class="panneau"><h3>Part des jours en position, par demi-heure</h3><p class="sous">Strategies fiables empilees ; trait : au moins une
        strategie fiable en position.</p><div class="graph" id="g-pr-barres" style="height:300px"></div></div>
      <div class="grille2">
        <div class="panneau"><h3>Hypotheses testees pour les plages vides</h3><p class="sous">Lot « creneaux vides » (<code>nexus/perso/creneaux.py</code>),
          protocole ecrit avant chaque calcul, criteres de la methode et filtre de fiabilite du tableau de bord.</p>
          <div class="tablebox"><table><thead><tr><th>Code</th><th>Hypothese</th><th>Heures</th><th class="num">Net / trade</th><th class="num">Sharpe</th><th>Verdict</th></tr></thead>
          <tbody>${hyp.map(function (h) {
            return `<tr class="fixe"><td><strong>${esc(h.code)}</strong></td><td class="rq">${esc(h.titre)}</td><td class="src">${esc(h.heures)}</td>
              <td class="num ${h.net < 0 ? "neg" : ""}">${nb(h.net, 2)} pb</td><td class="num ${h.sharpe < 0 ? "neg" : ""}">${nb(h.sharpe, 2)}</td>
              <td>${h.retenue ? '<span class="puce bon"><i>✓</i>retenue</span>' : (h.fiable ? '<span class="puce moyen"><i>~</i>fiable, criteres non remplis</span>' : '<span class="puce mauvais"><i>✕</i>rejetee</span>')}</td></tr>`;
          }).join("") || '<tr class="fixe"><td colspan="6" class="vide-a">aucune hypothese testee</td></tr>'}</tbody></table></div></div>
        <div class="panneau"><h3>Strategies non fiables deja presentes dans les plages vides</h3><p class="sous">Part moyenne des jours en position
          sur les demi-heures vides ; elles ne passent pas le filtre de fiabilite.</p>
          <div class="tablebox"><table><thead><tr><th>Strategie</th><th>Contrats</th><th class="num">Part</th></tr></thead><tbody>${dansVide.map(function (x) {
            return `<tr class="fixe"><td><a href="#" data-route="s/${encodeURIComponent(x.id)}/apercu">${esc(D.titres[x.id])}</a></td>
              <td>${esc((D.instruments[x.id] || []).join(", "))}</td><td class="num">${pc(x.part, 1)}</td></tr>`;
          }).join("") || '<tr class="fixe"><td colspan="3" class="vide-a">aucune</td></tr>'}</tbody></table></div></div>
      </div></div>`;
    var c = couleurs();
    var noms = function (m) { var out = []; F.forEach(function (f, k) { if (m & (1 << k)) out.push(f.titre); }); return out.join(" + ") || "aucune"; };
    var texte = D.masque.map(function (r) { return r.map(noms); });
    trace($("#g-pr-carte"), [{ z: D.nombre, x: D.creneaux, y: D.jours, type: "heatmap", text: texte,
      colorscale: [[0, c.surface2], [0.34, c.accent], [1, c.vert]], zmin: 0, zmax: Math.max(1, F.length), showscale: true,
      colorbar: { title: { text: "fiables" }, thickness: 10 },
      hovertemplate: "%{y} %{x}<br>%{text}<extra></extra>" }],
    { hovermode: "closest", margin: { l: 80, r: 10, t: 10, b: 40 }, yaxis: { autorange: "reversed", type: "category", nticks: 13 },
      xaxis: { type: "category", tickangle: -45 } });
    var tons = [c.accent, c.vert, "#a855f7", "#0ea5e9", c.rouge];
    var barres = F.map(function (f, k) {
      return { x: D.creneaux, y: (D.profils[f.id] || []).map(function (v) { return v * 100; }), type: "bar", name: f.titre, marker: { color: tons[k % tons.length] } };
    });
    barres.push({ x: D.creneaux, y: D.couverture.map(function (v) { return v * 100; }), type: "scatter", mode: "lines", name: "au moins une",
      line: { color: c.texte, width: 1.5 } });
    trace($("#g-pr-barres"), barres, { barmode: "stack", showlegend: true, hovermode: "x unified", yaxis: { ticksuffix: " %" },
      xaxis: { type: "category", tickangle: -45 }, legend: { orientation: "h", y: 1.15 } });
  }

  return { page: page, oublier: oublier };
})();
