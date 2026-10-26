// Tableau de bord Nexus : onglet « Prop firm ». Combinaisons de strategies futures intraday classees par FIABILITE.
// Les statistiques (Sharpe, IC bootstrap du Sharpe, Sharpe de chaque moitie, Sharpe deflate, perte max) sont calculees
// par vectorbt a l export (python -m nexus tableau -> nexus/prop_combinaisons.py -> donnees/prop.json) ; le navigateur
// ne fait que filtrer et recalculer le taux de reussite de l evaluation pour les regles du compte choisies (memes regles
// que nexus/perso/portefeuille.py : depart chaque jour, reussite si l objectif est atteint avant une violation).
"use strict";

const Prop = (function () {
  var P = null, promesse = null;
  var etatP = { preset: 0, regles: null, lignes: null, sel: 0,
    filtres: { taille: 4, corr: 0.3, conflit: 0.02, membres: true, fiable: true, tri: "ic" } };

  async function charger(statique) {
    if (P) return P;
    if (!promesse) {
      promesse = (async function () {
        var r = await fetch(statique ? "donnees/prop.json" : "/api/annexe/prop", { cache: "no-store" });
        if (!r.ok) throw new Error("donnees prop firm absentes : lancer python -m nexus tableau (depuis Python/)");
        P = await r.json();
        P.parId = {};
        P.candidats.forEach(function (c, i) { P.parId[c.id] = c; c.i = i; });
        return P;
      })();
      promesse.catch(function () { promesse = null; });
    }
    return promesse;
  }
  function oublier() { P = null; promesse = null; etatP.lignes = null; }

  // ---------- formats ----------
  var nf0 = new Intl.NumberFormat("fr-FR", { maximumFractionDigits: 0 });
  function nb(v, d) { return v == null || !isFinite(v) ? "–" : v.toLocaleString("fr-FR", { minimumFractionDigits: d, maximumFractionDigits: d }); }
  function pc(v, d) { return v == null || !isFinite(v) ? "–" : nb(v * 100, d == null ? 0 : d) + " %"; }
  function usd(v) { return v == null || !isFinite(v) ? "–" : (v < 0 ? "−" : "") + nf0.format(Math.abs(v)) + " $"; }
  function titre(id) { var c = P.parId[id]; return c ? c.titre : id; }
  function badgeFiable(ok) { return ok ? '<span class="puce bon"><i>✓</i>fiable</span>' : '<span class="puce neutre"><i>–</i>non prouvée</span>'; }
  function ic(m) { return m.ic_bas == null ? "–" : "[" + nb(m.ic_bas, 2) + " ; " + nb(m.ic_haut, 2) + "]"; }

  // ---------- evaluation (memes regles que nexus/perso/portefeuille.py et nexus/prop_combinaisons.py) ----------
  function evaluer(x, k, R) {
    var H = R.horizon, n = x.length - H;
    if (n < 20) return { reussite: NaN, echec: NaN, non_conclu: NaN, jours_median: NaN, avantage: NaN, departs: 0 };
    var ok = 0, ko = 0, jours = [];
    for (var s = 0; s < n; s++) {
      var cum = 0, pic = 0;
      for (var t = 0; t < H; t++) {
        var v = x[s + t] * k; cum += v; if (cum > pic) pic = cum;
        if (cum < Math.min(pic, R.dd) - R.dd || v < -R.perte) { ko++; break; }
        if (cum >= R.objectif) { ok++; jours.push(t + 1); break; }
      }
    }
    jours.sort(function (a, b) { return a - b; });
    var m = jours.length ? (jours.length % 2 ? jours[(jours.length - 1) / 2] : (jours[jours.length / 2 - 1] + jours[jours.length / 2]) / 2) : NaN;
    return { reussite: ok / n, echec: ko / n, non_conclu: (n - ok - ko) / n, jours_median: m, departs: n,
      avantage: ok + ko ? ok / (ok + ko) - R.dd / (R.objectif + R.dd) : NaN };
  }
  function sansViolation(x, k, R) {
    var eq = R.compte, pic = -Infinity;
    for (var i = 0; i < x.length; i++) {
      var v = x[i] * k; eq += v; if (eq > pic) pic = eq;
      if (eq < Math.min(pic, R.compte + R.dd) - R.dd || v < -R.perte) return false;
    }
    return true;
  }
  function tailleMax(x, R) {
    if (sansViolation(x, 20, R)) return 20;
    var lo = 0, hi = 20;
    for (var i = 0; i < 25; i++) { var mid = (lo + hi) / 2; if (sansViolation(x, mid, R)) lo = mid; else hi = mid; }
    return lo;
  }
  // P&L journalier en $ a la taille x1 : moyenne des strategies ramenees au meme risque (comme serie_combo en Python)
  function serieGroupe(ids, compte) {
    var cols = ids.map(function (i) { return P.rendements[i]; });
    var w = ids.map(function (i) { return P.sigma_ref / P.parId[i].vol; });
    var x = [], d = [];
    for (var t = 0; t < P.dates.length; t++) {
      var s = 0, ok = true;
      for (var j = 0; j < cols.length; j++) { var v = cols[j][t]; if (v == null) { ok = false; break; } s += v * w[j]; }
      if (ok) { x.push(compte * s / cols.length); d.push(P.dates[t]); }
    }
    return { x: x, dates: d, poids: w };
  }
  function perteMax(x, k) {
    var c = 0, pic = 0, dd = 0;
    for (var i = 0; i < x.length; i++) { c += x[i] * k; if (c > pic) pic = c; if (pic - c > dd) dd = pic - c; }
    return dd;
  }
  function evaluerLigne(L, R) {
    var g = serieGroupe(L.ids, R.compte);
    var parTaille = P.multiplicateurs.map(function (k) { return evaluer(g.x, k, R); });
    var bi = 0;
    for (var m = 1; m < parTaille.length; m++) {
      var a = parTaille[m], b = parTaille[bi];
      var ja = isFinite(a.jours_median) ? a.jours_median : 1e9, jb = isFinite(b.jours_median) ? b.jours_median : 1e9;
      if (a.reussite > b.reussite || (a.reussite === b.reussite && ja < jb)) bi = m;
    }
    L.g = g; L.parTaille = parTaille; L.k = P.multiplicateurs[bi]; L.best = parTaille[bi];
    L.kmax = tailleMax(g.x, R); L.dd = perteMax(g.x, L.k);
  }

  // ---------- filtres et classement ----------
  function filtrer() {
    var F = etatP.filtres;
    var rows = (P.combinaisons || []).filter(function (m) {
      return m.ids.length <= F.taille && m.corr_max <= F.corr + 1e-9 && m.conflit_max <= F.conflit + 1e-9
        && (!F.membres || m.membres_fiables === m.ids.length) && (!F.fiable || m.fiable);
    });
    return rows;
  }
  function recalculer() {
    var R = etatP.regles, F = etatP.filtres;
    var rows = filtrer();
    if (F.tri === "heure") rows = rows.slice().sort(function (a, b) { return (b.par_100h || -9) - (a.par_100h || -9); });
    rows = rows.slice(0, F.tri === "reussite" ? 200 : 25);
    rows.forEach(function (L) { evaluerLigne(L, R); });
    if (F.tri === "reussite") rows.sort(function (a, b) { return (b.best.reussite || 0) - (a.best.reussite || 0); });
    etatP.lignes = rows.slice(0, 25);
    etatP.sel = 0;
  }

  // ---------- page ----------
  function lireRegles() {
    var p = P.presets[etatP.preset];
    var v = function (id, d) { var x = +document.getElementById(id).value; return isFinite(x) && x > 0 ? x : d; };
    etatP.regles = { compte: p.compte, objectif: v("p-objectif", p.objectif), perte: v("p-perte", p.perte_jour), dd: v("p-dd", p.dd),
      horizon: Math.round(v("p-horizon", P.horizon)) };
    var F = etatP.filtres;
    F.taille = Math.max(1, Math.min(4, Math.round(+document.getElementById("p-taille").value || 4)));
    F.corr = Math.max(0, +document.getElementById("p-corr").value || 0);
    F.conflit = Math.max(0, (+document.getElementById("p-conflit").value || 0) / 100);
    F.membres = document.getElementById("p-membres").checked;
    F.fiable = document.getElementById("p-fiable").checked;
    F.tri = document.getElementById("p-tri").value;
  }
  function remplirRegles(reinit) {
    var p = P.presets[etatP.preset], R = etatP.regles, F = etatP.filtres;
    var v = function (id, x) { document.getElementById(id).value = x; };
    v("p-objectif", reinit || !R ? p.objectif : R.objectif); v("p-perte", reinit || !R ? p.perte_jour : R.perte);
    v("p-dd", reinit || !R ? p.dd : R.dd); v("p-horizon", reinit || !R ? P.horizon : R.horizon);
    v("p-taille", F.taille); v("p-corr", F.corr); v("p-conflit", F.conflit * 100); v("p-tri", F.tri);
    document.getElementById("p-membres").checked = F.membres;
    document.getElementById("p-fiable").checked = F.fiable;
    document.querySelectorAll("#p-presets button").forEach(function (b, j) { b.setAttribute("aria-pressed", String(j === etatP.preset)); });
  }

  async function page(statique) {
    $("#contenu").innerHTML = '<p class="vide">Chargement des donnees prop firm…</p>';
    await charger(statique);
    var nCand = P.candidats.length, nFiables = P.candidats.filter(function (c) { return c.stats && c.stats.fiable; }).length;
    $("#contenu").innerHTML = `<div class="archive"><div class="entete"><h2>Prop firm : la combinaison la plus fiable</h2></div>
      <p class="resume">Toutes les strategies du tableau qui tradent des <strong>futures en intraday</strong> (positions soldees avant la fin
      de seance CME de 17:00 New York) : ${nCand} sur ${etatIndex().length}. Chaque strategie et chaque combinaison est un portefeuille de
      rendements journaliers dont <strong>toutes les statistiques viennent de vectorbt</strong>. Une strategie est <em>fiable</em> si la borne
      basse de l'intervalle de confiance a 95 % de son Sharpe est au-dessus de 0 et si son Sharpe est positif sur les deux moities
      (avant / apres le ${esc(P.coupure || "2021-01-01")}) : ${nFiables} sur ${nCand}. Les combinaisons sont classees par la <strong>borne
      basse de l'IC du Sharpe</strong> (ce que l'historique permet de garantir), pas par le meilleur resultat passe ; le Sharpe deflate
      compte ${nf0.format(P.essais_combinaisons || 0)} essais (programme de recherche + toutes les combinaisons essayees).
      ${(P.filtres || {}).heures_max != null
        ? `Seules les strategies <strong>courtes</strong> (au plus ${nf0.format(P.filtres.heures_max)} h en position par an) entrent
      dans les combinaisons : les plus longues restent dans la liste, marquees « trop longue ».`
        : `Aucun plafond d'heures en position : deux strategies d'une combinaison ne doivent simplement pas tenir le meme contrat en
      meme temps (conflit de contrat au plus ${nf0.format(((P.filtres || {}).conflit_max || 0) * 100)} % du temps).`}
      ${(P.filtres || {}).retenues ? `Seules les strategies qui passent les <strong>24 criteres de la methode</strong> entrent dans les
      combinaisons (${P.filtres.retenues.length} sur ${nCand}) ; les autres restent dans la liste, marquees « hors methode ».` : ""}
      <em>% par 100 h</em> : rendement annuel a 10 % de volatilite, pour 100 heures en position (le temps a surveiller).</p>
      <div id="p-reco"></div>
      <div class="panneau"><div class="outils">
        <div><div class="note">Compte</div><div class="segment" id="p-presets" role="group" aria-label="Taille du compte">
          ${P.presets.map(function (p, i) { return `<button type="button" data-i="${i}">${esc(p.nom)}</button>`; }).join("")}</div></div>
        <label for="p-objectif">Objectif de profit ($)<input type="number" id="p-objectif" min="100" step="100"></label>
        <label for="p-perte">Perte max du jour ($)<input type="number" id="p-perte" min="100" step="100"></label>
        <label for="p-dd">Drawdown suiveur ($)<input type="number" id="p-dd" min="100" step="100"></label>
        <label for="p-horizon">Duree max (seances)<input type="number" id="p-horizon" min="20" step="10"></label>
      </div><div class="outils">
        <label for="p-taille">Strategies par groupe (max)<input type="number" id="p-taille" min="1" max="4" step="1"></label>
        <label for="p-corr">Correlation max entre deux<input type="number" id="p-corr" min="0" max="1" step="0.05"></label>
        <label for="p-conflit">Conflit de contrat max (% du temps)<input type="number" id="p-conflit" min="0" max="100" step="1"></label>
        <label class="case"><input type="checkbox" id="p-membres"> Seulement des strategies fiables</label>
        <label class="case"><input type="checkbox" id="p-fiable"> Combinaison fiable (IC &gt; 0, deux moities &gt; 0)</label>
        <label for="p-tri">Classer par<select id="p-tri"><option value="ic">fiabilite (borne basse de l'IC du Sharpe)</option><option value="heure">rendement par heure en position</option>
          <option value="reussite">taux de reussite de l'evaluation (optimiste)</option></select></label>
        <button class="bouton primaire" id="p-calcul" type="button">Recalculer</button><span class="note" id="p-etat"></span>
      </div><p class="note" id="p-hasard"></p></div>
      <div class="panneau"><h3>Combinaisons</h3><p class="sous">Statistiques vectorbt sur toute la periode commune ; reussite, taille et duree
        recalculees pour les regles ci-dessus. « Taille » = multiplicateur au meilleur taux de reussite ; « taille max » = plus grand
        multiplicateur sans aucune violation sur tout l'historique. Clique sur une ligne pour la detailler.</p>
        <div class="tablebox"><table id="p-table"><thead><tr><th>Rang</th><th>Combinaison</th><th>Periode commune</th>
          <th class="num">Sharpe [IC 95 %]</th><th class="num">1re / 2e moitie</th><th class="num">Sharpe deflate</th><th class="num">Perte max</th>
          <th class="num">Heures / an</th><th class="num">% par 100 h</th>
          <th class="num">Taille</th><th class="num">Taille max</th><th class="num">Reussite</th><th class="num">Echec</th><th class="num">Duree mediane</th>
        </tr></thead><tbody></tbody></table></div></div>
      <div id="p-detail"></div>
      <div id="p-validation"></div>
      <div class="panneau"><h3>Strategies candidates (${nCand})</h3><p class="sous">Futures intraday du tableau, statistiques vectorbt de chacune.
        Sharpe deflate : ${nf0.format(etatProgramme())} essais cumules du programme (figes a la date de validation pour les strategies validees), variance du Sharpe sous l'hypothese nulle.</p>
        <div class="tablebox"><table id="p-cands"><thead><tr><th>Strategie</th><th>Fiabilite</th><th>Contrats</th><th>Periode</th>
        <th class="num">Sharpe [IC 95 %]</th><th class="num">1re / 2e moitie</th><th class="num">P(Sharpe &gt; 0)</th><th class="num">Sharpe deflate</th>
        <th class="num">Perte max</th><th class="num">Heures / an</th><th class="num">% par 100 h</th></tr></thead><tbody></tbody></table></div>
        <p class="note">${esc(P.note || "")}</p></div></div>`;
    document.querySelectorAll("#p-presets button").forEach(function (b) {
      b.addEventListener("click", function () { etatP.preset = +b.dataset.i; remplirRegles(true); lancer(); });
    });
    $("#p-calcul").addEventListener("click", function () { lancer(); });
    remplirRegles(false);
    remplirCandidats();
    validation();
    lancer();
  }
  function etatIndex() { return (window.etat && window.etat.index && window.etat.index.strategies) || []; }
  function etatProgramme() { return (window.etat && window.etat.index && window.etat.index.essais_programme) || 0; }
  function remplirCandidats() {
    var tb = document.querySelector("#p-cands tbody");
    tb.innerHTML = P.candidats.slice().sort(function (a, b) {
      var x = a.stats || {}, y = b.stats || {};
      return ((y.retenue !== false) - (x.retenue !== false))
        || ((y.fiable && y.courte !== false) - (x.fiable && x.courte !== false)) || (y.fiable - x.fiable)
        || ((y.ic_bas == null ? -9 : y.ic_bas) - (x.ic_bas == null ? -9 : x.ic_bas));
    }).map(function (c) {
      var m = c.stats || {};
      return `<tr class="fixe"><td><a href="#" data-route="s/${encodeURIComponent(c.id)}/apercu">${esc(c.titre)}</a><div class="src">${badgeStatut(c.statut)}</div></td>
        <td>${badgeFiable(m.fiable)}${m.retenue === false ? '<div class="src"><span class="puce moyen"><i>!</i>hors methode</span></div>' : ""}</td><td>${esc((c.instruments || []).join(", "))}</td><td class="src">${esc(m.debut || c.debut)} → ${esc(m.fin || c.fin)}</td>
        <td class="num ${m.sharpe < 0 ? "neg" : ""}">${nb(m.sharpe, 2)}<div class="src">${ic(m)}</div></td>
        <td class="num">${nb(m.sharpe_p1, 2)} / ${nb(m.sharpe_p2, 2)}</td><td class="num">${pc(m.psr, 0)}</td>
        <td class="num">${pc(m.dsr, 1)}</td><td class="num">${pc(m.perte_max, 1)}</td>
        <td class="num">${nb(m.heures_an, 0)}${m.courte === false ? '<div class="src"><span class="puce moyen"><i>!</i>trop longue</span></div>' : ""}</td>
        <td class="num">${nb(m.par_100h * 100, 1)}</td></tr>`;
    }).join("");
  }
  function lancer() {
    lireRegles();
    var R = etatP.regles;
    $("#p-hasard").textContent = "Reference a battre : une strategie sans avantage reussit environ " + pc(R.dd / (R.objectif + R.dd))
      + " des evaluations conclues (drawdown ÷ (objectif + drawdown)). Une duree mediane de 1 a 3 seances signale un pari, pas une strategie.";
    var t0 = Date.now();
    recalculer();
    $("#p-etat").textContent = `${filtrer().length} combinaisons passent les filtres sur ${nf0.format((P.combinaisons || []).length)} ; `
      + `reussite recalculee en ${nb((Date.now() - t0) / 1000, 1)} s`;
    recommandation();
    afficher();
  }
  function recommandation() {
    var box = $("#p-reco"), r = P.recommandee;
    if (!r) { box.innerHTML = '<div class="panneau"><h3>Aucune combinaison fiable</h3><p class="note">Aucune combinaison de strategies fiables ne respecte les limites de correlation et de conflit.</p></div>'; return; }
    var m = (P.combinaisons || []).find(function (x) { return x.ids.join("|") === r.ids.join("|"); }) || {};
    var L = { ids: r.ids }; evaluerLigne(L, etatP.regles);
    var F = P.filtres || {};
    box.innerHTML = `<div class="panneau encadre-reco"><h3>Combinaison recommandee : ${r.ids.map(function (i) { return esc(titre(i)); }).join(" + ")}</h3>
      <p class="sous">La meilleure borne basse d'IC du Sharpe parmi les combinaisons de strategies fiables, avec une correlation de
      ${nb(F.corr_max, 2)} au plus et ${nb((F.conflit_max || 0) * 100, 0)} % de conflit de contrat au plus. Choisie par vectorbt a l'export, independamment
      des regles du compte ; la taille et la reussite ci-dessous suivent les regles choisies.</p>
      <div class="kpis">
        <div class="kpi"><span class="lib">Sharpe (vectorbt)</span><span class="val">${nb(m.sharpe, 2)}</span><span class="aide">IC 95 % ${ic(m)}</span></div>
        <div class="kpi"><span class="lib">Sharpe 1re / 2e moitie</span><span class="val">${nb(m.sharpe_p1, 2)} / ${nb(m.sharpe_p2, 2)}</span><span class="aide">avant / apres le ${esc(P.coupure)}</span></div>
        <div class="kpi"><span class="lib">Sharpe deflate</span><span class="val">${pc(m.dsr, 1)}</span><span class="aide">${nf0.format(P.essais_combinaisons || 0)} essais comptes</span></div>
        <div class="kpi"><span class="lib">Perte max (vectorbt)</span><span class="val">${pc(m.perte_max, 1)}</span><span class="aide">a 1 % d'ecart-type par strategie</span></div>
        <div class="kpi"><span class="lib">Taille / taille max</span><span class="val">x${nb(L.k, 2)} / x${nb(L.kmax, 2)}</span><span class="aide">meilleure reussite / sans violation</span></div>
        <div class="kpi"><span class="lib">Reussite de l'evaluation</span><span class="val">${pc(L.best.reussite)}</span><span class="aide">echec ${pc(L.best.echec)}, non conclu ${pc(L.best.non_conclu)} ; ${nf0.format(L.best.departs)} departs</span></div>
      </div></div>`;
  }
  function validation() {
    var v = P.validation, box = $("#p-validation");
    if (!v || !v.fiable) { box.innerHTML = ""; return; }
    var lig = function (nom, x, quoi) {
      if (!x || !x.choix) return `<tr class="fixe"><td>${nom}</td><td colspan="7" class="vide-a">aucun choix possible</td></tr>`;
      return `<tr class="fixe"><td><strong>${nom}</strong><div class="src">${quoi}</div></td>
        <td>${x.choix.map(function (i) { return `<div class="nom">${esc(titre(i))}</div>`; }).join("")}<div class="src">${x.membres} strategies admises, ${x.combinaisons} combinaisons</div></td>
        <td class="num">${nb(x.sharpe_a, 2)}</td><td class="num">${pc(x.reussite_a)}</td><td class="num">x${nb(x.taille, 2)}</td>
        <td class="num ${x.sharpe_b < 0 ? "neg" : ""}">${nb(x.sharpe_b, 2)}<div class="src">[${nb(x.ic_b[0], 2)} ; ${nb(x.ic_b[1], 2)}]</div></td>
        <td class="num">${pc(x.reussite_b)}</td><td class="num">${pc(x.perte_max_b, 1)}</td></tr>`;
    };
    var R = v.regles || {};
    box.innerHTML = `<div class="panneau"><h3>La methode de choix, testee hors echantillon</h3><p class="sous">Choix fait avec les seances
      d'avant le ${esc(P.coupure)} seulement (fiabilite des strategies, correlations, classement, taille), puis resultat sur les seances
      suivantes, jamais utilisees pour choisir. Regles du compte ${nf0.format(R.compte || 0)} $ (objectif ${nf0.format(R.objectif || 0)} $,
      perte du jour ${nf0.format(R.perte_jour || 0)} $, drawdown ${nf0.format(R.dd || 0)} $, ${R.horizon || 0} seances).</p>
      <div class="tablebox"><table><thead><tr><th>Methode</th><th>Combinaison choisie</th><th class="num">Sharpe avant</th><th class="num">Reussite avant</th>
      <th class="num">Taille</th><th class="num">Sharpe apres [IC 95 %]</th><th class="num">Reussite apres</th><th class="num">Perte max apres</th></tr></thead>
      <tbody>${lig("Fiabilite", v.fiable, "IC du Sharpe > 0 des strategies, meilleure borne basse d'IC")}
      ${lig("Ancienne", v.ancienne, "Sharpe ≥ 0,3, meilleur taux de reussite passe")}</tbody></table></div></div>`;
  }
  function afficher() {
    var rows = etatP.lignes, tb = document.querySelector("#p-table tbody");
    if (!rows.length) {
      tb.innerHTML = '<tr class="fixe"><td colspan="14" class="vide-a">Aucune combinaison ne passe les filtres : decoche « seulement des strategies '
        + "fiables » ou releve la correlation maximale.</td></tr>";
      $("#p-detail").innerHTML = "";
      return;
    }
    tb.innerHTML = rows.map(function (L, i) {
      return `<tr data-i="${i}" aria-selected="${i === etatP.sel}" tabindex="0"><td class="num"><span class="rang ${i === 0 ? "or" : ""}">${i + 1}</span></td>
        <td>${L.ids.map(function (id) { var s = P.parId[id].stats || {}; return `<div class="nom">${esc(titre(id))} ${s.fiable ? '<span class="puce bon"><i>✓</i></span>' : ""}</div>`; }).join("")}</td>
        <td class="src">${esc(L.debut)} → ${esc(L.fin)}<br>${nf0.format(L.n)} seances</td>
        <td class="num ${L.sharpe < 0 ? "neg" : ""}">${nb(L.sharpe, 2)}<div class="src">${ic(L)}</div></td>
        <td class="num">${nb(L.sharpe_p1, 2)} / ${nb(L.sharpe_p2, 2)}</td><td class="num">${pc(L.dsr, 1)}</td><td class="num">${pc(L.perte_max, 1)}</td>
        <td class="num">${nb(L.heures_an, 0)}</td><td class="num">${nb(L.par_100h * 100, 1)}</td>
        <td class="num">x${nb(L.k, 2)}</td><td class="num">x${nb(L.kmax, 2)}</td><td class="num">${pc(L.best.reussite)}</td><td class="num">${pc(L.best.echec)}</td>
        <td class="num">${isFinite(L.best.jours_median) ? nb(L.best.jours_median, 0) + " j" : "–"}${L.best.jours_median <= 3 ? ' <span class="puce moyen"><i>!</i>pari</span>' : ""}</td></tr>`;
    }).join("");
    tb.querySelectorAll("tr[data-i]").forEach(function (tr) {
      var go = function () { etatP.sel = +tr.dataset.i; afficher(); };
      tr.addEventListener("click", go); tr.addEventListener("keydown", function (e) { if (e.key === "Enter") go(); });
    });
    detail(rows[etatP.sel], etatP.regles);
  }
  function detail(L, R) {
    var expo = L.ids.map(function (id, j) {
      var c = P.parId[id];
      return { titre: c.titre, part: L.k * L.g.poids[j] / L.ids.length * R.compte / c.capital };
    });
    $("#p-detail").innerHTML = `<div class="panneau"><h3>Combinaison n° ${etatP.sel + 1} a la taille x${nb(L.k, 2)}</h3>
      <p class="sous">Taille de chaque strategie, en multiple de la taille de son backtest : ${expo.map(function (e) {
        return `<strong>${esc(e.titre)}</strong> ${nb(e.part, 3)}`; }).join(" ; ")}. Perte max a cette taille ${usd(L.dd)} ;
      ${nf0.format(L.best.departs)} departs evalues. Sortino ${nb(L.sortino, 2)}, rendement annuel ${pc(L.rendement_annuel, 1)} a la taille x1.</p>
      <div class="grille-2"><div><h3 class="h4">Issue de l'evaluation selon la taille</h3><div class="graph" id="g-p-issue" style="height:290px"></div></div>
      <div><h3 class="h4">Gain cumule a cette taille</h3><div class="graph" id="g-p-courbe" style="height:290px"></div></div></div>
      <div class="grille-2"><div><h3 class="h4">Correlations et conflits de contrat</h3><div class="graph" id="g-p-corr" style="height:260px"></div></div>
      <div><h3 class="h4">Profil horaire (part du temps en position, heure de New York)</h3><div class="graph" id="g-p-profil" style="height:260px"></div></div></div></div>`;
    var c = couleurs();
    var xs = P.multiplicateurs.map(function (k) { return "x" + nb(k, 2); });
    var serie = function (cle, nom, col) {
      return { type: "bar", x: xs, y: L.parTaille.map(function (q) { return (q[cle] || 0) * 100; }), name: nom, marker: { color: col },
        hovertemplate: "%{y:.0f} %<extra>" + nom + "</extra>" };
    };
    trace($("#g-p-issue"), [serie("reussite", "reussite", c.vert), serie("echec", "echec", c.rouge), serie("non_conclu", "non conclu", c.bord)],
      { barmode: "stack", showlegend: true, hovermode: "closest", yaxis: { range: [0, 100], ticksuffix: " %" }, xaxis: { type: "category" } });
    var cum = 0, y = L.g.x.map(function (v) { cum += v * L.k; return cum; });
    trace($("#g-p-courbe"), [{ x: L.g.dates, y: y, type: "scatter", mode: "lines", line: { color: c.accent, width: 1.6 }, name: "gain" }],
      { yaxis: { tickformat: ",.0f" }, shapes: [
        { type: "line", xref: "paper", x0: 0, x1: 1, y0: R.objectif, y1: R.objectif, line: { color: c.vert, width: 1, dash: "dot" } },
        { type: "line", xref: "paper", x0: 0, x1: 1, y0: -R.dd, y1: -R.dd, line: { color: c.rouge, width: 1, dash: "dot" } }] });
    var noms = L.ids.map(titre);
    var z = L.ids.map(function (a) { return L.ids.map(function (b) { return a === b ? null : P.correlation[P.parId[a].i][P.parId[b].i]; }); });
    var txt = L.ids.map(function (a) { return L.ids.map(function (b) {
      if (a === b) return "";
      var co = P.correlation[P.parId[a].i][P.parId[b].i], cf = P.conflits[P.parId[a].i][P.parId[b].i];
      return virgule(co, 2) + "<br>conflit " + nb((cf || 0) * 100, 1) + " %";
    }); });
    trace($("#g-p-corr"), [{ z: z, x: noms, y: noms, type: "heatmap", zmin: -1, zmax: 1, colorscale: echelle(c, c.accent), text: txt,
      texttemplate: "%{text}", hovertemplate: "%{x} / %{y}<br>correlation %{z:.2f}<extra></extra>", showscale: false }],
    { hovermode: "closest", margin: { l: 150, r: 10, t: 10, b: 90 } });
    var heures = []; for (var h = 0; h < 24; h++) heures.push(h + " h");
    trace($("#g-p-profil"), L.ids.map(function (id, j) {
      var pr = P.parId[id].profil || [];
      return { x: heures, y: pr.map(function (v) { return v * 100; }), type: "bar", name: noms[j] };
    }), { barmode: "group", showlegend: true, hovermode: "closest", yaxis: { ticksuffix: " %" } });
  }

  return { page: page, oublier: oublier };
})();
