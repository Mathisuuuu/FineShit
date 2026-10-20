// Tableau de bord Nexus : page « Études sur papiers » (vue d'ensemble des 60 stratégies intraday et stratégies
// construites sur papiers, protocole écrit avant chaque calcul). Données : recherche/resultats_60.json, recopié par
// python -m nexus tableau dans donnees/etudes.json (/api/annexe/etudes). Les stratégies qui ont des trades sont, elles,
// des fiches du tableau comme les autres.
"use strict";

const Etudes = (function () {
  var R60 = null, promesse = null;

  async function charger(statique) {
    if (R60) return R60;
    if (!promesse) {
      promesse = (async function () {
        var r = await fetch(statique ? "donnees/etudes.json" : "/api/annexe/etudes", { cache: "no-store" });
        R60 = r.ok ? await r.json() : {};
        return R60;
      })();
      promesse.catch(function () { promesse = null; });
    }
    return promesse;
  }
  function oublier() { R60 = null; promesse = null; }
  // ---------- formats ----------
  var nf0 = new Intl.NumberFormat("fr-FR", { maximumFractionDigits: 0 });
  function usd(v) { return v == null || !isFinite(v) ? "—" : (v > 0 ? "+" : v < 0 ? "−" : "") + nf0.format(Math.abs(v)) + " $"; }
  function usdAbs(v) { return v == null || !isFinite(v) ? "—" : nf0.format(v) + " $"; }
  function nb(v, d) { return v == null || !isFinite(v) ? "—" : v.toLocaleString("fr-FR", { minimumFractionDigits: d, maximumFractionDigits: d }); }
  function pct(v, d) { return v == null || !isFinite(v) ? "—" : nb(v, d == null ? 0 : d) + " %"; }
  function signe(v, d) { return v == null || !isFinite(v) ? "—" : (v > 0 ? "+" : v < 0 ? "−" : "") + nb(Math.abs(v), d); }
  function pb(v) { return v == null ? "—" : signe(v, 2) + " pb"; }
  function duree(min) {
    if (min == null || !isFinite(min)) return "—";
    if (min < 1) return "< 1 min";
    if (Math.round(min) < 60) return Math.round(min) + " min";
    if (Math.round(min) < 1440) { var h = Math.floor(Math.round(min) / 60), m = Math.round(min) % 60; return h + " h" + (m ? " " + (m < 10 ? "0" : "") + m : ""); }
    var j = min / 1440;
    return nb(j, j < 10 ? 1 : 0) + " j";
  }
  function el(tag, cls, txt) { var e = document.createElement(tag); if (cls) e.className = cls; if (txt != null) e.textContent = txt; return e; }
  function id(x) { return document.getElementById(x); }

  var CATS = {
    bon: { lib: "Prometteuse", icone: "✓" }, moyen: { lib: "Positive mais faible", icone: "~" },
    mauvais: { lib: "Négative", icone: "✕" }, neutre: { lib: "Autre", icone: "–" },
  };
  function categorie(v) {
    v = v || "";
    if (v.indexOf("PROMETTEUSE") === 0) return "bon";
    if (v.indexOf("POSITIVE") === 0) return "moyen";
    if (v.indexOf("NEGATIVE") === 0) return "mauvais";
    return "neutre";
  }
  function libVerdict(v) {
    if (!v) return "—";
    v = v.toLowerCase();
    return v.charAt(0).toUpperCase() + v.slice(1);
  }
  function puce(verdict) {
    var c = categorie(verdict), p = el("span", "puce " + c), i = el("i", null, CATS[c].icone);
    i.setAttribute("aria-hidden", "true");
    p.appendChild(i);
    p.appendChild(document.createTextNode(c === "neutre" ? libVerdict(verdict) : CATS[c].lib));
    return p;
  }
  function puceSimple(cat, icone, texte) {
    var p = el("span", "puce " + cat), i = el("i", null, icone);
    i.setAttribute("aria-hidden", "true"); p.appendChild(i); p.appendChild(document.createTextNode(texte));
    return p;
  }

  // ---------- graphiques (couleurs du theme du tableau de bord) ----------
  function T() {
    var cs = getComputedStyle(document.documentElement);
    var g = function (n) { return cs.getPropertyValue(n).trim(); };
    return {
      surface: g("--surface"), ink: g("--texte"), ink2: g("--texte-2"), muted: g("--a-muted"), grid: g("--bord"), axis: g("--a-axe"),
      s1: g("--accent"), neg: g("--a-neg"), mid: g("--a-milieu"), pos: g("--accent"),
      q0: g("--a-seq-0"), q1: g("--a-seq-1"), q2: g("--a-seq-2"), q3: g("--a-seq-3"), good: g("--a-bon"), crit: g("--a-neg"),
      font: g("--police"),
    };
  }
  function alpha(c, a) {
    var h = String(c).replace("#", "");
    if (h.length !== 6) return c;
    return "rgba(" + parseInt(h.slice(0, 2), 16) + "," + parseInt(h.slice(2, 4), 16) + "," + parseInt(h.slice(4, 6), 16) + "," + a + ")";
  }
  function axe(t, extra) {
    return Object.assign({ gridcolor: t.grid, linecolor: t.axis, zerolinecolor: t.axis, tickcolor: t.axis, showline: false,
      tickfont: { color: t.muted, size: 11 }, automargin: true, zeroline: false }, extra || {});
  }
  function base(t, extra) {
    return Object.assign({
      paper_bgcolor: "rgba(0,0,0,0)", plot_bgcolor: "rgba(0,0,0,0)", separators: ", ",
      font: { family: t.font, size: 12, color: t.ink2 }, margin: { l: 56, r: 12, t: 6, b: 30 },
      hovermode: "x unified", showlegend: false,
      hoverlabel: { bgcolor: t.surface, bordercolor: t.axis, font: { color: t.ink, family: t.font, size: 12 } },
      xaxis: axe(t), yaxis: axe(t),
    }, extra || {});
  }
  var localeFr = false;
  var CONFIG = { displaylogo: false, responsive: true, displayModeBar: "hover",
    modeBarButtonsToRemove: ["select2d", "lasso2d", "autoScale2d", "toggleSpikelines", "hoverClosestCartesian", "hoverCompareCartesian"],
    locale: "fr" };
  function tracer(cible, traces, layout) {
    if (!window.Plotly) return;
    if (!localeFr) {
      localeFr = true;
      window.Plotly.register({ moduleType: "locale", name: "fr", dictionary: {}, format: {
        days: ["dimanche", "lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi"],
        shortDays: ["dim.", "lun.", "mar.", "mer.", "jeu.", "ven.", "sam."],
        months: ["janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août", "septembre", "octobre", "novembre", "décembre"],
        shortMonths: ["janv.", "févr.", "mars", "avr.", "mai", "juin", "juil.", "août", "sept.", "oct.", "nov.", "déc."],
        date: "%d/%m/%Y", decimal: ",", thousands: " " } });
    }
    window.Plotly.react(typeof cible === "string" ? id(cible) : cible, traces, layout, CONFIG);
  }
  function purger(x) { if (window.Plotly && id(x)) window.Plotly.purge(id(x)); }
  function legende(cible, items) {
    var box = id(cible); box.textContent = "";
    items.forEach(function (p) {
      var sp = el("span"), c = el("span", p[0]); c.style.background = p[1];
      sp.appendChild(c); sp.appendChild(document.createTextNode(p[2])); box.appendChild(sp);
    });
  }
  function kpi(box, lib, val, aide) {
    var c = el("div", "kpi");
    c.appendChild(el("span", "lib", lib)); c.appendChild(el("span", "val", val));
    if (aide) c.appendChild(el("span", "aide", aide));
    box.appendChild(c);
  }

  // ---------- cadre de la page ----------
  function cadre(titre, chapo, corps) {
    $("#contenu").innerHTML = '<div class="archive"><div class="entete"><h2>' + esc(titre) + '</h2></div>'
      + '<p class="resume">' + chapo + '</p>' + corps + '<p class="discret pied">Régénérer après chaque étude : <code>python -m nexus tableau</code> '
      + "(depuis <code>Python/</code>) recopie <code>recherche/resultats_60.json</code>. Protocoles dans l'en-tête de chaque module de "
      + "<code>nexus/perso/</code>.</p></div>";
  }

  // =========================================================================================== Etudes sur papiers
  var tri60 = "t", sens60 = -1;
  var COLS60 = [
    { k: "code", lib: "Code" }, { k: "etape", lib: "Niveau" }, { k: "definition", lib: "Définition (ma lecture du papier)" },
    { k: "n", lib: "Cas", num: true }, { k: "moyenne", lib: "Moyenne", num: true }, { k: "t", lib: "t", num: true },
    { k: "t1", lib: "t 2016-20", num: true }, { k: "t2", lib: "t 2021-26", num: true }, { k: "welch", lib: "Welch", num: true },
    { k: "net", lib: "Net", num: true }, { k: "passe", lib: "Verdict" },
  ];
  // parties de resultats_60.json affichees par un panneau dedie ; toutes les autres (format commun : titre, sous, lignes,
  // echecs, retenue) s affichent seules, dans l ordre ou elles ont ete exportees
  var DEDIEES = ["niveau_A", "niveaux_BC", "nq1", "derive_nocturne", "vol_geree", "cycle_fomc", "pression_cot"];
  function lignes60() {
    var out = [];
    if (!R60) return out;
    ["niveau_A", "niveaux_BC"].forEach(function (k) {
      ((R60[k] || {}).lignes || []).forEach(function (l) { out.push(Object.assign({}, l, { etape: k === "niveau_A" ? "A" : (l.niveau || "B/C") })); });
    });
    return out;
  }
  function tableHtml(tid, entetes, texte) {
    // texte : indices des colonnes de texte (les autres sont des nombres, alignes a droite)
    return '<div class="tablebox"><table id="' + tid + '"><thead><tr>' + entetes.map(function (h, k) {
      return "<th" + (texte.indexOf(k) >= 0 ? "" : ' class="num"') + ">" + h + "</th>";
    }).join("") + "</tr></thead><tbody></tbody></table></div>";
  }
  function pagePapiers() {
    if (!R60 || !Object.keys(R60).length) {
      cadre("Études sur papiers", "", '<p class="vide-a">Aucun résultat : lancer python -m nexus.perso.soixante, soixante_bc et nq1_variantes, puis python -m nexus tableau.</p>');
      return;
    }
    var L60 = lignes60();
    cadre("Études sur papiers", "Vue d'ensemble des « 60 stratégies intraday » (9 octobre 2026) : anomalies brutes, sans règles, stop ni taille, "
      + "testées par familles (si l'actif le mieux placé échoue, la famille entière est éliminée). Critères fixés avant le test : t ≥ 3 ; même "
      + "signe et t ≥ 1,5 sur les deux moitiés ; Welch ≥ 2 contre le témoin ; gain net de coûts &gt; 0, encore &gt; 0 sans les 3 meilleurs jours "
      + "(événements rares : t ≥ 2, net positif ≥ 65 % des années). Puis les stratégies construites sur papiers, chacune avec son protocole écrit "
      + "avant le calcul et le Sharpe déflaté pour le nombre cumulé d'essais.",
      '<div class="tuiles" id="t60-tuiles"></div>'
      + '<div class="panneau"><h3>Statistique t de chaque anomalie</h3><p class="sous">Rendement brut moyen dans le sens prévu ; seuil de 3 (tests '
      + "multiples, Harvey, Liu &amp; Zhu 2016). Un t élevé ne suffit pas : les autres critères (stabilité, témoin, coûts) doivent aussi passer.</p>"
      + '<div class="graph" id="g-60"></div></div>'
      + '<div class="panneau"><h3>Les anomalies testées</h3><p class="sous">En points de base par cas. Clique sur un en-tête pour trier.</p>'
      + '<div class="tablebox"><table id="table-60"><thead><tr></tr></thead><tbody></tbody></table></div></div>'
      + '<div class="panneau" id="p-nq1"><h3>NQ 1, la plus proche : variantes corrigées</h3><p class="sous" id="nq1-sous"></p>'
      + tableHtml("table-nq1", ["Version", "Jours", "Moyenne (t)", "2016-2020 / 2021-2026", "Welch", "Net", "Sharpe net", "Sharpe déflaté", "Verdict"], [0, 8])
      + '<details><summary>Contrôle de l\'heure du communiqué (B et C)</summary><ul id="nq1-controle"></ul></details></div>'
      + '<div class="panneau" id="p-dn"><h3>Stratégie construite sur les papiers de la Fed de New York : la dérive nocturne</h3><p class="sous">'
      + "Boyarchenko, Larsen &amp; Whelan, « The Overnight Drift » (Review of Financial Studies, 2023) et « The Disappearing Overnight Drift » "
      + "(Liberty Street Economics, juillet 2026). R0 = anomalie brute (achat 2:00 → 3:00 ET chaque nuit) ; V1 = « buy the dip » du papier "
      + "(1:30 → 3:30 ET après un déséquilibre vendeur à la clôture) ; V2 = version cohérente avec les deux papiers (seulement après un gros "
      + "déséquilibre vendeur et un VIX ≥ 20). Protocole : <code>nexus/perso/derive_nocturne.py</code>.</p>"
      + tableHtml("table-dn", ["Marché", "Version", "Nuits (2016-20 / 2021-26)", "Brut (t)", "t 2016-20 / 2021-26", "Welch", "Net", "Sharpe net", "Sharpe déflaté", "Verdict"], [0, 1, 9])
      + "</div>"
      + '<div class="panneau" id="p-vg"><h3>Stratégie construite sur neuf papiers : exposition gérée par la volatilité</h3><p class="sous">Moreira &amp; '
      + "Muir (Journal of Finance 2017) et ses critiques : Cederburg et al. (JFE 2020), Liu, Tang &amp; Zhou (2019), Barroso &amp; Detzel (JFE 2021), "
      + "Harvey et al. (Man Group, 2018), Bongaerts et al. (FAJ 2020), Wang &amp; Yan (2021), DeMiguel et al. (JF 2024), Moreira &amp; Muir (JFE 2019). "
      + "R1 = version classique en temps réel ; V = version conditionnelle de Bongaerts et al. Protocole : <code>nexus/perso/vol_geree.py</code>.</p>"
      + '<p class="note" id="vg-resume"></p>'
      + tableHtml("table-vg", ["Marché", "Version", "Alpha / an (t)", "t 2016-20 / 2021-26", "Sharpe net / détenu", "Perte max / détenu", "Rotation / an", "Sharpe déflaté"], [0, 1])
      + '<ul id="vg-criteres" class="liste60"></ul></div>'
      + '<div class="panneau" id="p-cf"><h3>Stratégie construite sur six travaux : le cycle du FOMC et le « Fed put »</h3><p class="sous">Cieslak, Morse '
      + "&amp; Vissing-Jorgensen (Journal of Finance 2019), Uppal (Imperial College, 2025), Cieslak &amp; Vissing-Jorgensen (Review of Financial "
      + "Studies 2021), Lucca &amp; Moench (Fed de New York), Kurov et al. (2021), FEDS Notes (Fed, 2020). Semaines 0, 2, 4, 6 du cycle ; « Fed put » "
      + "= semaine paire après une baisse des 5 séances dans le quintile bas. Protocole : <code>nexus/perso/cycle_fomc.py</code>.</p>"
      + tableHtml("table-cf1", ["Marché, période", "Semaine 0 (pb/j)", "Semaines 2-4-6 (pb/j)", "Fed put, semaine paire", "Fed put, semaine impaire"], [0])
      + tableHtml("table-cf2", ["Stratégie sur l'ES", "Jours", "Brut (t)", "t 2016-20 / 2021-26", "Témoin", "Net", "Sharpe net", "Sharpe déflaté"], [0])
      + '<p class="note" id="cf-verdict"></p></div>'
      + '<div class="panneau" id="p-cot"><h3>Stratégie construite sur huit travaux : pression de couverture et pression spéculative (COT)</h3>'
      + '<p class="sous">Kang, Rouwenhorst &amp; Tang (Journal of Finance 2020), Fan, Fernandez-Perez, Fuertes &amp; Miffre (Journal of Futures Markets '
      + "2020 ; 2017), Klitgaard &amp; Weir (Fed de New York 2004), Kearns &amp; Manners (Banque de réserve d'Australie 2004), Sanders et al. (2004), "
      + "de Roon et al. (Journal of Finance 2000), Maréchal (2023). Protocole : <code>nexus/perso/pression_cot.py</code>.</p>"
      + '<p class="note" id="cot-etape1"></p>'
      + tableHtml("table-cot", ["Portefeuille", "Net (pb/mois)", "t", "t 2016-20 / 2021-26", "Sharpe", "Sharpe déflaté"], [0])
      + '<p class="note" id="cot-verdict"></p></div>'
      + '<div id="p-generiques"></div>'
      + '<div class="grille2"><div class="panneau"><h3>Éliminées avec leur famille</h3><ul id="l60-elim" class="liste60"></ul></div>'
      + '<div class="panneau"><h3>En attente ou non testables</h3><ul id="l60-att" class="liste60"></ul></div></div>');
    var bc = R60.niveaux_BC || {}, elimIci = bc.eliminees_ici || {}, elim1 = bc.eliminees_etape1 || {}, att = bc.en_attente || {};
    var nElim = Object.keys(elimIci).length + Object.keys(elim1).length, nAtt = Object.keys(att).length;
    var nOk = L60.filter(function (l) { return l.passe; }).length;
    var box = id("t60-tuiles");
    [["Testées", L60.length, "anomalies brutes (A, B, C)"], ["Retenues", nOk, "tous les critères"],
      ["Éliminées par famille", nElim, "leur actif de tête a échoué"], ["En attente ou non testables", nAtt, "données manquantes, CL 3"],
      ["Total", L60.length + nElim + nAtt, "stratégies de la vue d'ensemble"]].forEach(function (d) {
      var b = el("div", "tuile fixe");
      b.appendChild(el("span", "lib", d[0])); b.appendChild(el("span", "val", String(d[1]))); b.appendChild(el("span", "det", d[2]));
      box.appendChild(b);
    });
    var ue = id("l60-elim");
    Object.keys(elimIci).concat(Object.keys(elim1)).forEach(function (m) {
      var li = el("li"); li.appendChild(el("b", null, m));
      li.appendChild(document.createTextNode(" : famille de " + (elimIci[m] || elim1[m]) + (elimIci[m] ? " (niveaux B et C)" : " (niveau A)"))); ue.appendChild(li);
    });
    var ua = id("l60-att");
    Object.keys(att).forEach(function (k) { var li = el("li"); li.appendChild(el("b", null, k)); li.appendChild(document.createTextNode(" : " + att[k])); ua.appendChild(li); });
    panneauNq1(R60.nq1); panneauDn(R60.derive_nocturne); panneauVg(R60.vol_geree); panneauCf(R60.cycle_fomc); panneauCot(R60.pression_cot);
    var gen = id("p-generiques");
    Object.keys(R60).forEach(function (cle) {
      var g = R60[cle];
      if (DEDIEES.indexOf(cle) >= 0 || !g || !g.lignes) return;
      gen.appendChild(panneauGenerique(cle, g));
    });
    entete60(L60); remplir60(L60); dessiner60(L60);
  }
  function entete60(L60) {
    var tr = document.querySelector("#table-60 thead tr"); tr.textContent = "";
    COLS60.forEach(function (c) {
      var th = el("th", c.num ? "num" : null); th.scope = "col";
      if (tri60 === c.k) th.setAttribute("aria-sort", sens60 > 0 ? "ascending" : "descending");
      var b = el("button", null, c.lib); b.type = "button";
      b.addEventListener("click", function () {
        if (tri60 === c.k) sens60 = -sens60; else { tri60 = c.k; sens60 = c.num ? -1 : 1; }
        entete60(L60); remplir60(L60);
      });
      th.appendChild(b); tr.appendChild(th);
    });
  }
  function remplir60(L60) {
    var rows = L60.slice().sort(function (a, b) {
      var x = a[tri60], y = b[tri60];
      if (x == null && y == null) return 0; if (x == null) return 1; if (y == null) return -1;
      if (typeof x === "string") return sens60 * x.localeCompare(y, "fr");
      return sens60 * (x - y);
    });
    var tb = document.querySelector("#table-60 tbody"); tb.textContent = "";
    rows.forEach(function (l) {
      var tr = el("tr"); tr.className = "fixe";
      var tdc = el("td"); tdc.appendChild(el("div", "nom", l.code)); tr.appendChild(tdc);
      tr.appendChild(el("td", null, l.etape));
      var td = el("td"); td.appendChild(el("div", "rq", l.definition));
      if (l.groupe) td.appendChild(el("div", "src", l.groupe + (l.role === "actif teste en premier" ? " · tête de famille" : "")));
      tr.appendChild(td);
      tr.appendChild(el("td", "num", l.n == null ? "—" : nf0.format(l.n)));
      tr.appendChild(el("td", "num" + (l.moyenne < 0 ? " neg" : ""), pb(l.moyenne)));
      tr.appendChild(el("td", "num" + (l.t < 0 ? " neg" : ""), signe(l.t, 1)));
      tr.appendChild(el("td", "num" + (l.t1 < 0 ? " neg" : ""), signe(l.t1, 1)));
      tr.appendChild(el("td", "num" + (l.t2 < 0 ? " neg" : ""), signe(l.t2, 1)));
      tr.appendChild(el("td", "num" + (l.welch < 0 ? " neg" : ""), signe(l.welch, 1)));
      var tdn = el("td", "num" + (l.net < 0 ? " neg" : ""), pb(l.net));
      tdn.appendChild(el("div", "src", "coût " + nb(l.cout, 2) + " pb")); tr.appendChild(tdn);
      var tv = el("td");
      tv.appendChild(puceSimple(l.passe ? "bon" : "mauvais", l.passe ? "✓" : "✕", l.passe ? "Passe" : "Échoue (" + l.echecs.length + ")"));
      if (!l.passe) { tv.title = "Critères manqués : " + l.echecs.join(" ; "); tv.appendChild(el("div", "src", l.echecs.join(" ; "))); }
      tr.appendChild(tv);
      tb.appendChild(tr);
    });
  }
  function dessiner60(L60) {
    if (!L60.length) return;
    var t = T(), rows = L60.filter(function (l) { return l.t != null; }).sort(function (a, b) { return a.t - b.t; });
    id("g-60").style.height = Math.max(260, rows.length * 20 + 50) + "px";
    tracer("g-60", [{
      type: "bar", orientation: "h", y: rows.map(function (l) { return l.code; }), x: rows.map(function (l) { return l.t; }),
      marker: { color: rows.map(function (l) { return l.t >= 0 ? t.pos : t.neg; }), line: { width: 0 } },
      customdata: rows.map(function (l) { return [l.definition, l.passe ? "passe" : "échoue", l.etape, nf0.format(l.n)]; }),
      hovertemplate: "<b>%{y}</b> (niveau %{customdata[2]}, %{customdata[3]} cas)<br>t = %{x:+.1f} · %{customdata[1]}<br>%{customdata[0]}<extra></extra>",
    }], base(t, {
      hovermode: "closest", bargap: 0.35, margin: { l: 64, r: 16, t: 18, b: 30 },
      yaxis: axe(t, { type: "category", tickfont: { color: t.ink2, size: 11 } }),
      xaxis: axe(t, { title: { text: "t", font: { color: t.muted, size: 11 } }, zeroline: false }),
      shapes: [{ type: "line", yref: "paper", y0: 0, y1: 1, x0: 0, x1: 0, line: { color: t.axis, width: 1 } },
        { type: "line", yref: "paper", y0: 0, y1: 1, x0: 3, x1: 3, line: { color: t.ink2, width: 1.5, dash: "dash" } }],
      annotations: [{ x: 3, y: 1, xref: "x", yref: "paper", yanchor: "bottom", text: "seuil t = 3", showarrow: false, font: { color: t.ink2, size: 11 } }],
    }));
  }
  function ligne(tb, cellules) {
    var tr = el("tr"); tr.className = "fixe";
    cellules.forEach(function (c) { tr.appendChild(el("td", c[0], c[1])); });
    tb.appendChild(tr);
    return tr;
  }
  function neg(v, cls) { return (cls || "num") + (v < 0 ? " neg" : ""); }
  function panneauNq1(nq) {
    if (!nq) { id("p-nq1").hidden = true; return; }
    id("nq1-sous").textContent = "Diffusion des résultats des grandes capitalisations (AAPL, MSFT, AMZN, GOOGL, META, NVDA) vers le NQ. "
      + "Protocole fixé avant le test ; retenue = critères ci-dessus et Sharpe déflaté ≥ " + nb(nq.seuil_dsr, 2) + " pour " + nq.n_essais
      + " essais. Sharpe net annualisé sur environ 15 publications par an.";
    var tb = document.querySelector("#table-nq1 tbody");
    nq.lignes.forEach(function (l) {
      var tr = ligne(tb, [[null, l.nom], ["num", nf0.format(l.n)], ["num", pb(l.moyenne) + " (" + signe(l.t, 1) + ")"],
        ["num", signe(l.t1, 1) + " / " + signe(l.t2, 1)], ["num", signe(l.welch, 1)], ["num", pb(l.net)], ["num", nb(l.sharpe_an, 2)], ["num", nb(l.dsr, 2)]]);
      var tv = el("td"), c = l.retenue ? "bon" : (l.invalide ? "neutre" : "mauvais");
      tv.appendChild(puceSimple(c, l.retenue ? "✓" : (l.invalide ? "!" : "✕"), l.retenue ? "Retenue" : (l.invalide ? "Invalide" : "Échoue")));
      tv.appendChild(el("div", "src", l.invalide ? "heure du communiqué mal reconstituée" : l.echecs.join(" ; ")));
      tr.appendChild(tv);
    });
    var uc = id("nq1-controle");
    (nq.controle || []).forEach(function (x) { uc.appendChild(el("li", null, x)); });
  }
  function panneauDn(dn) {
    if (!dn) { id("p-dn").hidden = true; return; }
    var tb = document.querySelector("#table-dn tbody");
    dn.lignes.forEach(function (l) {
      var tr = ligne(tb, [[null, l.marche], ["rq", l.nom], ["num", nf0.format(l.n) + " (" + nf0.format(l.n1) + " / " + nf0.format(l.n2) + ")"],
        [neg(l.moyenne), pb(l.moyenne) + " (" + signe(l.t, 1) + ")"], ["num", signe(l.t1, 1) + " / " + signe(l.t2, 1)],
        ["num", l.welch == null ? "—" : signe(l.welch, 1)], [neg(l.net), pb(l.net)], [neg(l.sharpe_an), nb(l.sharpe_an, 2)], ["num", nb(l.dsr, 2)]]);
      var tv = el("td");
      tv.appendChild(puceSimple(l.retenue ? "bon" : "mauvais", l.retenue ? "✓" : "✕", l.retenue ? "Retenue" : "Échoue (" + l.echecs.length + ")"));
      tv.title = l.echecs.join(" ; "); tr.appendChild(tv);
    });
  }
  function panneauVg(vg) {
    if (!vg) { id("p-vg").hidden = true; return; }
    id("vg-resume").textContent = "Marché américain 2017-2026 (jamais vu par ces papiers) : alpha de V " + signe(vg.marche_post.alpha * 100, 2)
      + " %/an (t " + signe(vg.marche_post.t, 2) + "). Témoin de Harvey et al. : gain de Sharpe moyen " + signe(vg.temoin.actions, 2)
      + " sur ES, NQ, YM contre " + signe(vg.temoin.autres, 2) + " sur l'or, le pétrole et les devises. Verdict de V sur l'ES : "
      + (vg.retenue ? "retenue." : "échoue.");
    var tb = document.querySelector("#table-vg tbody");
    vg.lignes.forEach(function (l) {
      ligne(tb, [[null, l.marche], [null, l.code], [neg(l.alpha), signe(l.alpha * 100, 2) + " % (" + signe(l.t, 2) + ")"],
        ["num", signe(l.t1, 2) + " / " + signe(l.t2, 2)], ["num", nb(l.sh, 2) + " / " + nb(l.sh_b, 2)],
        ["num", pct(l.pm * 100, 0) + " / " + pct(l.pm_b * 100, 0)], ["num", nb(l.rotation, 1)], ["num", nb(l.dsr, 2)]]);
    });
    var uv = id("vg-criteres");
    Object.keys(vg.criteres).forEach(function (k) {
      var li = el("li"); li.appendChild(el("b", null, vg.criteres[k] ? "✓ " : "✕ ")); li.appendChild(document.createTextNode(k)); uv.appendChild(li);
    });
  }
  function panneauCf(cf) {
    if (!cf) { id("p-cf").hidden = true; return; }
    var t1 = document.querySelector("#table-cf1 tbody");
    [["Marché américain", cf.etape1_marche], ["ES", cf.etape1_es]].forEach(function (grp) {
      Object.keys(grp[1]).forEach(function (per) {
        var x = grp[1][per];
        ligne(t1, [[null, grp[0] + ", " + per], [neg(x.s0), signe(x.s0, 1) + " (t " + signe(x.t0, 1) + ")"],
          [neg(x.s246), signe(x.s246, 1) + " (t " + signe(x.t246, 1) + ")"],
          [neg(x.put_paire), signe(x.put_paire, 1) + " (t " + signe(x.t_pp, 1) + ", " + x.n_pp + " j)"],
          [neg(x.put_impaire), signe(x.put_impaire, 1) + " (t " + signe(x.t_pi, 1) + ", " + x.n_pi + " j)"]]);
      });
    });
    var t2 = document.querySelector("#table-cf2 tbody");
    cf.lignes.forEach(function (l) {
      ligne(t2, [["rq", l.nom], ["num", nf0.format(l.n)], [neg(l.moyenne), pb(l.moyenne) + " (" + signe(l.t, 1) + ")"],
        ["num", signe(l.t1, 1) + " / " + signe(l.t2, 1)], ["num", pb(l.temoin)], [neg(l.net), pb(l.net)], [neg(l.sharpe_an), nb(l.sharpe_an, 2)], ["num", nb(l.dsr, 2)]]);
    });
    id("cf-verdict").textContent = "Verdict de V : " + (cf.retenue ? "retenue." : "échoue (" + cf.echecs.join(" ; ") + ").");
  }
  function panneauCot(ct) {
    if (!ct) { id("p-cot").hidden = true; return; }
    var e = ct.etape1 || {};
    id("cot-etape1").textContent = "Signal du mois -> rendement du mois suivant : 2016-2020 "
      + (e["1c_2016-2020"] ? signe(e["1c_2016-2020"].pente * 100, 2) + " % par écart-type (t " + signe(e["1c_2016-2020"].t, 2) + ")" : "—")
      + " ; 2021-2026 " + (e["1c_2021-2026"] ? signe(e["1c_2021-2026"].pente * 100, 2) + " % (t " + signe(e["1c_2021-2026"].t, 2) + ")" : "—")
      + ". Fan et al. prévoient une pente positive.";
    var tb = document.querySelector("#table-cot tbody");
    ct.lignes.forEach(function (l) {
      ligne(tb, [["rq", l.nom], [neg(l.moyenne), signe(l.moyenne, 1)], ["num", signe(l.t, 2)], ["num", signe(l.t1, 2) + " / " + signe(l.t2, 2)],
        [neg(l.sharpe_an), nb(l.sharpe_an, 2)], ["num", l.dsr == null ? "—" : nb(l.dsr, 2)]]);
    });
    id("cot-verdict").textContent = "Verdict de V : " + (ct.retenue ? "retenue." : "échoue (" + ct.echecs.join(" ; ") + ").");
  }
  function panneauGenerique(cle, g) {
    var p = el("div", "panneau");
    var h = el("h3", null, g.titre || cle);
    p.appendChild(h);
    if (g.sous) p.appendChild(el("p", "sous", g.sous));
    var box = el("div", "tablebox"), tab = el("table"), th = el("thead"), trh = el("tr");
    ["Version", "Cas", "Net (t)", "t 1re / 2e moitié", "Témoin", "Welch", "Sharpe net", "Sharpe déflaté"].forEach(function (x, k) {
      trh.appendChild(el("th", k ? "num" : null, x));
    });
    th.appendChild(trh); tab.appendChild(th);
    var tb = el("tbody");
    g.lignes.forEach(function (l) {
      ligne(tb, [["rq", l.nom || l.code], ["num", l.n == null ? "—" : nf0.format(l.n)], [neg(l.moyenne), signe(l.moyenne, 2) + " (" + signe(l.t, 2) + ")"],
        ["num", signe(l.t1, 2) + " / " + signe(l.t2, 2)], ["num", l.temoin == null ? "—" : signe(l.temoin, 2)],
        ["num", l.welch == null ? "—" : signe(l.welch, 2)], [neg(l.sharpe_an), nb(l.sharpe_an, 2)], ["num", l.dsr == null ? "—" : nb(l.dsr, 2)]]);
    });
    tab.appendChild(tb); box.appendChild(tab); p.appendChild(box);
    var v = el("p", "note");
    v.appendChild(puceSimple(g.retenue ? "bon" : "mauvais", g.retenue ? "✓" : "✕", g.retenue ? "Retenue" : "Rejetée"));
    if (!g.retenue && (g.echecs || []).length) v.appendChild(document.createTextNode(" " + g.echecs.join(" ; ")));
    if (g.genere) v.appendChild(el("span", "discret", " · calculé le " + g.genere));
    p.appendChild(v);
    return p;
  }

  async function page(statique) {
    $("#contenu").innerHTML = '<p class="vide">Chargement des études…</p>';
    await charger(statique);
    pagePapiers();
    window.scrollTo(0, 0);
  }

  return { page: page, oublier: oublier };
})();
