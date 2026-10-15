// Tableau de bord Nexus : interface (JavaScript sans framework, graphiques Plotly).
// Toutes les valeurs affichees viennent des fichiers JSON exportes par le moteur Python (vectorbt, scipy).
"use strict";

const etat = { index: null, fiches: {}, id: null, onglet: "apercu", statique: false, trades: { page: 0, tri: "entree", sens: -1, filtre: "" } };
const ONGLETS = [["apercu", "Vue d'ensemble"], ["fonctionnement", "Fonctionnement"], ["vectorbt", "Statistiques vectorbt"],
  ["trades", "Trades"], ["tests", "Tests et Monte Carlo"]];
const $ = (s, r = document) => r.querySelector(s);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

// ------------------------------------------------------------------ formats
const nf = (d) => new Intl.NumberFormat("fr-FR", { minimumFractionDigits: d, maximumFractionDigits: d });
const num = (x, d = 2) => (x === null || x === undefined || Number.isNaN(x) ? "–" : nf(d).format(x));
const pct = (x, d = 1) => (x === null || x === undefined ? "–" : `${nf(d).format(x * 100)} %`);
const signe = (x) => (x === null || x === undefined ? "" : x >= 0 ? "positif" : "negatif");

const FR = {
  "Start": "Debut", "End": "Fin", "Period": "Periode", "Total Return [%]": "Rendement total [%]",
  "Annualized Return [%]": "Rendement annualise [%]", "Annualized Volatility [%]": "Volatilite annualisee [%]",
  "Max Drawdown [%]": "Perte maximale [%]", "Max Drawdown Duration": "Duree de la perte maximale", "Sharpe Ratio": "Ratio de Sharpe",
  "Calmar Ratio": "Ratio de Calmar", "Omega Ratio": "Ratio Omega", "Sortino Ratio": "Ratio de Sortino", "Skew": "Asymetrie",
  "Kurtosis": "Kurtosis (queues)", "Tail Ratio": "Ratio des queues", "Common Sense Ratio": "Ratio de bon sens",
  "Value at Risk": "Valeur a risque (5 %)", "Cond. Value at Risk": "Valeur a risque conditionnelle (5 %)", "Downside Risk": "Risque baissier",
  "Coverage [%]": "Temps passe en perte [%]", "Total Records": "Nombre", "Total Recovered Drawdowns": "Pertes recuperees",
  "Total Active Drawdowns": "Pertes en cours", "Active Drawdown [%]": "Perte en cours [%]", "Active Duration": "Duree de la perte en cours",
  "Active Recovery [%]": "Recuperation en cours [%]", "Active Recovery Return [%]": "Rendement de recuperation en cours [%]",
  "Active Recovery Duration": "Duree de recuperation en cours", "Avg Drawdown [%]": "Perte moyenne [%]",
  "Avg Drawdown Duration": "Duree moyenne d'une perte", "Max Recovery Return [%]": "Plus forte remontee [%]",
  "Avg Recovery Return [%]": "Remontee moyenne [%]", "Max Recovery Duration": "Plus longue remontee",
  "Avg Recovery Duration": "Duree moyenne de remontee", "Avg Recovery Duration Ratio": "Duree remontee / duree baisse",
  "First Trade Start": "Premier trade", "Last Trade End": "Fin du dernier trade", "Coverage": "Temps en position",
  "Overlap Coverage": "Chevauchement", "Total Fees Paid": "Frais payes ($)", "Total Trades": "Trades", "Total Closed Trades": "Trades fermes",
  "Total Open Trades": "Trades ouverts", "Open Trade PnL": "PnL des trades ouverts", "Win Rate [%]": "Trades gagnants [%]",
  "Max Win Streak": "Plus longue serie gagnante", "Max Loss Streak": "Plus longue serie perdante", "Best Trade [%]": "Meilleur trade [%]",
  "Worst Trade [%]": "Pire trade [%]", "Avg Winning Trade [%]": "Gain moyen [%]", "Avg Losing Trade [%]": "Perte moyenne [%]",
  "Avg Winning Trade Duration": "Duree moyenne d'un gain", "Avg Losing Trade Duration": "Duree moyenne d'une perte",
  "Profit Factor": "Facteur de profit", "Expectancy": "Esperance par trade ($)", "SQN": "SQN (qualite du systeme)",
  "Total Buy Orders": "Ordres d'achat", "Total Sell Orders": "Ordres de vente", "Min Size": "Taille minimale", "Max Size": "Taille maximale",
  "Avg Size": "Taille moyenne", "Avg Buy Size": "Taille moyenne a l'achat", "Avg Sell Size": "Taille moyenne a la vente",
  "Avg Buy Price": "Prix moyen d'achat", "Avg Sell Price": "Prix moyen de vente", "Total Fees": "Frais ($)", "Min Fees": "Frais minimum",
  "Max Fees": "Frais maximum", "Avg Fees": "Frais moyens", "Avg Buy Fees": "Frais moyens a l'achat", "Avg Sell Fees": "Frais moyens a la vente",
};
const BLOCS_VBT = [
  ["rendements", "Rendements journaliers", "returns.vbt.returns(freq='1D', year_freq='252 days').stats()"],
  ["drawdowns", "Pertes (drawdowns)", "valeur.vbt.drawdowns.stats()"],
  ["trades", "Trades", "pf.trades.stats()"],
  ["positions", "Positions", "pf.positions.stats()"],
  ["ordres", "Ordres", "pf.orders.stats()"],
  ["portefeuille", "Portefeuille", "pf.stats()"],
];

function valeurStat(nom, v) {
  if (v === null || v === undefined) return "–";
  if (typeof v === "number") {
    if (/\[%\]/.test(nom)) return `${num(v, 2)} %`;
    if (Number.isInteger(v)) return num(v, 0);
    return Math.abs(v) >= 1000 ? num(v, 0) : Math.abs(v) < 0.01 ? num(v, 5) : num(v, 3);
  }
  return esc(v);
}

// ------------------------------------------------------------------ graphiques
function couleurs() {
  const cs = getComputedStyle(document.documentElement);
  const g = (n) => cs.getPropertyValue(n).trim();
  return { texte: g("--texte"), texte2: g("--texte-2"), bord: g("--bord"), accent: g("--accent"), vert: g("--vert"), rouge: g("--rouge"),
    surface: g("--surface"), surface2: g("--surface-2") };
}
// echelle divergente aux couleurs du theme : perte (rouge) -> neutre -> gain (vert)
const echelle = (c, haut) => [[0, c.rouge], [0.5, c.surface2], [1, haut || c.vert]];
const virgule = (v, d = 1) => (v === null || v === undefined ? "" : v.toFixed(d).replace(".", ","));
function trace(el, data, layout = {}) {
  if (!window.Plotly || !el) return;
  const c = couleurs();
  const base = {
    paper_bgcolor: "rgba(0,0,0,0)", plot_bgcolor: "rgba(0,0,0,0)", font: { color: c.texte, size: 12, family: "system-ui, sans-serif" },
    margin: { l: 56, r: 16, t: 10, b: 40 }, hovermode: "x unified", showlegend: false,
    xaxis: { gridcolor: c.bord, zerolinecolor: c.bord, linecolor: c.bord },
    yaxis: { gridcolor: c.bord, zerolinecolor: c.bord, linecolor: c.bord },
    legend: { orientation: "h", y: 1.12, x: 0 },
  };
  const lay = { ...base, ...layout, xaxis: { ...base.xaxis, ...(layout.xaxis || {}) }, yaxis: { ...base.yaxis, ...(layout.yaxis || {}) } };
  window.Plotly.react(el, data, lay, { responsive: true, displaylogo: false, locale: "fr" });
}
function histo(el, series, { titre = "", observe = null, fmt = ".1%", noms = [] } = {}) {
  const c = couleurs();
  const tons = [c.accent, c.rouge, c.vert];
  const data = series.map((s, i) => ({ type: "histogram", x: s, name: noms[i] || "", opacity: series.length > 1 ? 0.6 : 0.85, marker: { color: tons[i % 3] }, nbinsx: 60 }));
  const shapes = observe === null ? [] : [{ type: "line", x0: observe, x1: observe, yref: "paper", y0: 0, y1: 1, line: { color: c.texte, width: 2, dash: "dash" } }];
  trace(el, data, { barmode: "overlay", shapes, showlegend: noms.length > 1, hovermode: "closest", xaxis: { tickformat: fmt, title: { text: titre } },
    legend: { orientation: "h", x: 0, y: -0.28 }, margin: { l: 56, r: 16, t: 10, b: noms.length > 1 ? 70 : 44 },
    annotations: observe === null ? [] : [{ x: observe, yref: "paper", y: 0.98, text: " observe", showarrow: false, xanchor: "left", yanchor: "top", font: { size: 11, color: c.texte } }] });
}

// ------------------------------------------------------------------ donnees
async function json(url) {
  const r = await fetch(url, { cache: "no-store" });
  if (!r.ok) throw new Error(`${url} : ${r.status}`);
  return r.json();
}
async function fiche(id) {
  if (!etat.fiches[id]) {
    etat.fiches[id] = await json(etat.statique ? `donnees/${encodeURIComponent(id)}.json` : `/api/strategies/${encodeURIComponent(id)}`);
  }
  return etat.fiches[id];
}
// Avec le serveur Node : API /api/... ; sans serveur (copie statique) : fichiers donnees/*.json a cote de la page.
async function chargerIndex() {
  try {
    const r = await fetch("/api/strategies", { cache: "no-store" });
    if (r.ok && (r.headers.get("content-type") || "").includes("json")) return [await r.json(), false];
  } catch (e) { /* pas de serveur */ }
  return [await json("donnees/index.json"), true];
}

// ------------------------------------------------------------------ liste
function rendreListe() {
  const nav = $("#liste");
  const s = etat.index?.strategies || [];
  const carte = (x) => {
    const k = x.kpi || {};
    const badge = x.statut === "validee" ? `<span class="badge validee">Validee</span>` : `<span class="badge candidate">Candidate</span>`;
    return `<a class="carte-strat ${etat.id === x.id ? "active" : ""}" href="#" data-route="s/${encodeURIComponent(x.id)}/${etat.onglet}">
      <div class="nom"><span>${esc(x.titre)}</span>${badge}</div>
      <div class="ligne"><span>Sharpe ${num(k.sharpe)}</span><span>perte max ${pct(k.perte_max)}</span></div>
      <div class="ligne"><span class="badge ok">${x.ok} ok</span><span class="badge alerte">${x.alertes} alerte(s)</span></div></a>`;
  };
  const val = s.filter((x) => x.statut === "validee");
  const cand = s.filter((x) => x.statut !== "validee");
  nav.innerHTML = `
    <a class="carte-strat ${etat.id === null ? "active" : ""}" href="#" data-route="comparaison"><div class="nom"><span>Comparaison</span></div>
      <div class="ligne">toutes les strategies, correlations, portefeuille combine</div></a>
    <div class="titre-liste">Strategies validees (${val.length})</div>${val.map(carte).join("") || '<p class="discret">aucune</p>'}
    <div class="titre-liste">Candidates a l'etude (${cand.length})</div>${cand.map(carte).join("") || '<p class="discret">aucune</p>'}`;
}

// ------------------------------------------------------------------ pages
function entete(f) {
  const statut = f.statut === "validee" ? `<span class="badge validee">Validee le ${esc(f.valide_le)}</span>` : `<span class="badge candidate">Candidate, non validee</span>`;
  const onglets = ONGLETS.map(([k, l]) => `<a href="#" data-route="s/${encodeURIComponent(f.id)}/${k}" class="${etat.onglet === k ? "actif" : ""}">${l}</a>`).join("");
  return `<div class="entete"><h2>${esc(f.titre)}</h2>${statut}</div>
    <p class="resume">${esc(f.resume)} <span class="discret">· calcule le ${esc(f.genere_le)}</span></p>
    <nav class="onglets">${onglets}</nav>`;
}

function kpis(k, cap) {
  const items = [
    ["Sharpe", num(k.sharpe)], ["Sortino", num(k.sortino)], ["Calmar", num(k.calmar)], ["Rendement annuel", pct(k.rendement_annuel)],
    ["Volatilite annuelle", pct(k.volatilite)], ["Perte maximale", pct(k.perte_max)], ["Rendement total", pct(k.rendement_total, 0)],
    ["Trades", num(k.trades, 0)], ["Trades gagnants", pct(k.gagnants, 0)], ["Gain net par trade (notionnel)", `${num(k.bp_par_trade)} bp`],
    ["Gain net par trade (capital)", `${num(k.bp_capital_par_trade)} bp`],
  ];
  return `<div class="kpis">${items.map(([l, v]) => `<div class="kpi"><div class="v">${v}</div><div class="l">${l}</div></div>`).join("")}</div>
    <p class="discret">Capital de depart ${num(cap.initial, 0)} ${esc(cap.unite)} (${esc(cap.note)}). Periode ${esc(k.debut)} → ${esc(k.fin)}.</p>`;
}

function pageApercu(f) {
  const s = f.series;
  $("#contenu").innerHTML = entete(f) + kpis(f.kpi, f.capital) + `
    <div class="panneau"><h3>Valeur du capital</h3><p class="sous">pf.value() de vectorbt en fin de journee ; zones grisees : les 5 pertes les plus profondes (drawdowns.records)</p><div id="g-valeur" class="graph haut"></div></div>
    <div class="panneau"><h3>Perte depuis le plus haut (underwater)</h3><div id="g-dd" class="graph bas"></div></div>
    <div class="grille-2">
      <div class="panneau"><h3>Rendement par annee</h3><div id="g-ans" class="graph"></div></div>
      <div class="panneau"><h3>Rendement par mois</h3><div id="g-mois" class="graph"></div></div>
    </div>
    <div class="grille-2">
      <div class="panneau"><h3>Sharpe et Sortino glissants sur 1 an</h3><p class="sous">returns.vbt.returns.rolling_sharpe_ratio(252) / rolling_sortino_ratio(252)</p><div id="g-sh" class="graph"></div></div>
      <div class="panneau"><h3>Volatilite glissante sur 3 mois</h3><p class="sous">rolling_annualized_volatility(63)</p><div id="g-vol" class="graph"></div></div>
    </div>`;
  const c = couleurs();
  const shapes = (s.top_drawdowns || []).map((d) => ({ type: "rect", xref: "x", yref: "paper", x0: d.pic, x1: d.fin || s.dates[s.dates.length - 1], y0: 0, y1: 1, fillcolor: c.rouge, opacity: 0.08, line: { width: 0 } }));
  trace($("#g-valeur"), [{ x: s.dates, y: s.valeur, type: "scatter", mode: "lines", line: { color: c.accent, width: 1.6 }, name: "valeur" }],
    { shapes, yaxis: { tickformat: ".3~s" } });
  trace($("#g-dd"), [{ x: s.dates, y: s.drawdown, type: "scatter", mode: "lines", fill: "tozeroy", line: { color: c.rouge, width: 1 }, name: "perte" }],
    { yaxis: { tickformat: ".0%" } });
  trace($("#g-ans"), [{ x: s.annuel.annees, y: s.annuel.rendement, type: "bar", marker: { color: s.annuel.rendement.map((v) => (v >= 0 ? c.vert : c.rouge)) },
    text: s.annuel.rendement.map((v) => pct(v)), textposition: "outside", hovertemplate: "%{x} : %{y:.2%}<extra></extra>" }],
    { yaxis: { tickformat: ".0%" }, hovermode: "closest" });
  const mois = ["janv.", "fevr.", "mars", "avr.", "mai", "juin", "juil.", "aout", "sept.", "oct.", "nov.", "dec."];
  trace($("#g-mois"), [{ z: s.mensuel.z, x: mois, y: s.mensuel.annees.map(String), type: "heatmap", colorscale: echelle(c), zmid: 0,
    text: s.mensuel.z.map((r) => r.map((v) => (v === null ? "" : virgule(v * 100)))), texttemplate: "%{text}", hovertemplate: "%{y} %{x} : %{z:.2%}<extra></extra>", showscale: false }],
    { yaxis: { autorange: "reversed", type: "category" }, hovermode: "closest", margin: { l: 48, r: 8, t: 8, b: 30 } });
  trace($("#g-sh"), [
    { x: s.dates, y: s.sharpe_1an, type: "scatter", mode: "lines", line: { color: c.accent, width: 1.4 }, name: "Sharpe 1 an" },
    { x: s.dates, y: s.sortino_1an, type: "scatter", mode: "lines", line: { color: c.vert, width: 1 }, name: "Sortino 1 an" }],
  { showlegend: true });
  trace($("#g-vol"), [{ x: s.dates, y: s.vol_3mois, type: "scatter", mode: "lines", line: { color: c.texte2, width: 1.2 }, name: "volatilite" }],
    { yaxis: { tickformat: ".1%" } });
}

function pageFonctionnement(f) {
  const lignes = (o) => Object.entries(o || {}).map(([k, v]) => `<tr><td>${esc(k)}</td><td>${esc(typeof v === "number" ? num(v, Number.isInteger(v) ? 0 : 4) : v)}</td></tr>`).join("");
  $("#contenu").innerHTML = entete(f) + `
    <div class="grille-2">
      <div>
        <div class="panneau"><h3>Comment ca marche</h3><ol class="etapes">${(f.fonctionnement || []).map((x) => `<li>${esc(x)}</li>`).join("")}</ol>
          <div class="encadre"><strong>Pourquoi ca marcherait.</strong> ${esc(f.pourquoi)}</div></div>
        <div class="panneau"><h3>Sources</h3><ul>${(f.sources || []).map((s) => `<li><a href="${esc(s.lien)}" target="_blank" rel="noopener">${esc(s.titre)}</a></li>`).join("")}</ul></div>
      </div>
      <div>
        <div class="panneau"><h3>Donnees utilisees</h3><table><tbody>${lignes(f.donnees)}</tbody></table></div>
        <div class="panneau"><h3>Parametres ${f.statut === "validee" ? "(figes)" : ""}</h3><table><tbody>${lignes(f.parametres)}</tbody></table></div>
      </div>
    </div>`;
}

function pageVectorbt(f) {
  const bloc = ([cle, titre, fn]) => {
    const rows = (f.vectorbt[cle] || []).map(([k, v]) => `<tr><td>${esc(FR[k] || k)}<div class="nom-vbt">${esc(k)}</div></td><td class="n">${valeurStat(k, v)}</td></tr>`).join("");
    return `<div class="panneau"><h3>${titre}</h3><p class="sous"><code>${esc(fn)}</code></p><table><tbody>${rows}</tbody></table></div>`;
  };
  $("#contenu").innerHTML = entete(f) + `<p class="discret">Sorties brutes des fonctions de statistiques de vectorbt (nom d'origine sous la traduction).
    Les ratios annualises sont calcules sur les rendements journaliers (252 seances par an) ; pf.stats() ne garde que les mesures de trades,
    les autres etant faussees par la frequence minute.</p><div class="grille-2">${BLOCS_VBT.map(bloc).join("")}</div>`;
}

function pageTrades(f) {
  const t = f.trades;
  const annees = [...new Set(t.map((x) => x.entree.slice(0, 4)))];
  $("#contenu").innerHTML = entete(f) + `
    <div class="grille-2">
      <div class="panneau"><h3>Distribution des gains par trade</h3><p class="sous">rendement net en points de base (0,01 %)</p><div id="g-th" class="graph"></div></div>
      <div class="panneau"><h3>Gain de chaque trade dans le temps</h3><p class="sous">equivalent de pf.trades.plot_pnl()</p><div id="g-tp" class="graph"></div></div>
    </div>
    <div class="grille-2">
      <div class="panneau"><h3>Gain cumule, trade apres trade</h3><div id="g-tc" class="graph"></div></div>
      <div class="panneau"><h3>Par heure d'entree (${esc(f.fuseau_trades)})</h3><div id="g-hr" class="graph"></div></div>
    </div>
    <div class="panneau"><h3>Liste des trades (${t.length})</h3>
      <div class="outils">
        <select id="f-annee"><option value="">toutes les annees</option>${annees.map((a) => `<option>${a}</option>`).join("")}</select>
        <select id="f-sens"><option value="">achats et ventes</option><option value="achat">achats</option><option value="vente">ventes</option></select>
        ${etat.statique ? "" : '<button class="bouton" id="csv">Telecharger en CSV</button>'}
        <span class="discret">heures : ${esc(f.fuseau_trades)} · cliquer un titre de colonne pour trier</span>
      </div>
      <div id="t-trades" class="table-defile"></div>
      <div class="pagination"><button class="bouton" id="prec">‹</button><span id="pg" class="discret"></span><button class="bouton" id="suiv">›</button></div>
    </div>`;
  const c = couleurs();
  const ach = t.filter((x) => x.sens === "achat"), ven = t.filter((x) => x.sens === "vente");
  histo($("#g-th"), [ach.map((x) => x.rendement_bp), ven.map((x) => x.rendement_bp)], { fmt: "", titre: "bp", noms: ["achats", "ventes"] });
  trace($("#g-tp"), [{ x: t.map((x) => x.sortie), y: t.map((x) => x.pnl), mode: "markers", type: "scattergl",
    marker: { size: 4, color: t.map((x) => (x.pnl >= 0 ? c.vert : c.rouge)) }, hovertemplate: "%{x}<br>%{y:,.0f} $<extra></extra>" }], { hovermode: "closest" });
  let cum = 0;
  trace($("#g-tc"), [{ y: t.map((x) => (cum += x.pnl)), type: "scatter", mode: "lines", line: { color: c.accent, width: 1.4 } }], { yaxis: { tickformat: ",.0f" } });
  const parH = {};
  t.forEach((x) => { const h = x.entree.slice(11, 13); (parH[h] = parH[h] || []).push(x.rendement_bp); });
  const hs = Object.keys(parH).sort();
  trace($("#g-hr"), [
    { x: hs.map((h) => `${h}h`), y: hs.map((h) => parH[h].length), type: "bar", name: "trades", marker: { color: c.bord } },
    { x: hs.map((h) => `${h}h`), y: hs.map((h) => parH[h].reduce((a, b) => a + b, 0) / parH[h].length), type: "scatter", mode: "lines+markers", name: "gain moyen (bp)", yaxis: "y2", line: { color: c.accent } }],
  { showlegend: true, yaxis2: { overlaying: "y", side: "right", showgrid: false, title: { text: "bp" } } });

  const cols = [["n", "#"], ["sens", "Sens"], ["entree", "Entree"], ["sortie", "Sortie"], ["prix_entree", "Prix d'entree"], ["prix_sortie", "Prix de sortie"],
    ["quantite", "Quantite"], ["pnl", "PnL ($)"], ["rendement_bp", "Net (bp)"], ["frais", "Frais ($)"], ["duree_min", "Duree (min)"]];
  const T = etat.trades;
  const rendre = () => {
    let rows = t.filter((x) => (!$("#f-annee").value || x.entree.startsWith($("#f-annee").value)) && (!$("#f-sens").value || x.sens === $("#f-sens").value));
    rows = rows.slice().sort((a, b) => (a[T.tri] > b[T.tri] ? 1 : a[T.tri] < b[T.tri] ? -1 : 0) * T.sens);
    const parPage = 50, pages = Math.max(1, Math.ceil(rows.length / parPage));
    T.page = Math.min(T.page, pages - 1);
    const vue = rows.slice(T.page * parPage, (T.page + 1) * parPage);
    const fmtc = (k, v) => (typeof v !== "number" ? esc(v) : k === "prix_entree" || k === "prix_sortie" ? (Math.abs(v) < 1 ? v.toPrecision(6) : num(v, 2)) : k === "quantite" ? num(v, v < 100 ? 2 : 0) : num(v, k === "n" ? 0 : 2));
    $("#t-trades").innerHTML = `<table><thead><tr>${cols.map(([k, l]) => `<th data-k="${k}" class="${["sens", "entree", "sortie"].includes(k) ? "" : "n"}" style="cursor:pointer">${l}${T.tri === k ? (T.sens > 0 ? " ▲" : " ▼") : ""}</th>`).join("")}</tr></thead>
      <tbody>${vue.map((x) => `<tr>${cols.map(([k]) => `<td class="${["sens", "entree", "sortie"].includes(k) ? "" : "n"} ${k === "pnl" || k === "rendement_bp" ? signe(x[k]) : ""}">${fmtc(k, x[k])}</td>`).join("")}</tr>`).join("")}</tbody></table>`;
    $("#pg").textContent = `page ${T.page + 1} / ${pages} · ${rows.length} trades`;
    $("#t-trades").querySelectorAll("th").forEach((th) => th.addEventListener("click", () => {
      T.sens = T.tri === th.dataset.k ? -T.sens : 1; T.tri = th.dataset.k; rendre();
    }));
    return rows;
  };
  let courant = rendre();
  $("#f-annee").onchange = $("#f-sens").onchange = () => { T.page = 0; courant = rendre(); };
  $("#prec").onclick = () => { T.page = Math.max(0, T.page - 1); courant = rendre(); };
  $("#suiv").onclick = () => { T.page += 1; courant = rendre(); };
  if ($("#csv")) $("#csv").onclick = () => {
    const lignes = [cols.map((c2) => c2[0]).join(";"), ...courant.map((x) => cols.map(([k]) => x[k]).join(";"))];
    const a = document.createElement("a");
    a.href = URL.createObjectURL(new Blob([lignes.join("\n")], { type: "text/csv" }));
    a.download = `${f.id}_trades.csv`;
    a.click();
  };
}

function pageTests(f) {
  const t = f.tests;
  const n = (v) => t.filter((x) => x.verdict === v).length;
  const familles = [...new Set(t.map((x) => x.famille))];
  const icone = { ok: "✓ ok", alerte: "⚠ alerte", info: "info" };
  const table = familles.map((fa) => `<tr class="groupe"><td colspan="4">${esc(fa)}</td></tr>` + t.filter((x) => x.famille === fa).map((x) =>
    `<tr><td>${esc(x.test)}</td><td><strong>${esc(x.resultat)}</strong></td><td class="discret">${esc(x.detail)}</td><td><span class="badge ${x.verdict}">${icone[x.verdict]}</span></td></tr>`).join("")).join("");
  const sens = f.sensibilite || [];
  const famSens = [...new Set(sens.map((x) => x.famille))];
  $("#contenu").innerHTML = entete(f) + `
    <div class="compte-tests"><span class="badge ok">${n("ok")} ok</span><span class="badge alerte">${n("alerte")} alerte(s)</span><span class="badge info">${n("info")} info</span></div>
    <div class="panneau"><h3>Tous les tests</h3><table><thead><tr><th>Test</th><th>Resultat</th><th>Detail</th><th>Verdict</th></tr></thead><tbody>${table}</tbody></table></div>
    <div class="grille-2">
      <div class="panneau"><h3>Monte Carlo : perte maximale</h3><p class="sous">trades remelanges (ordre) et retires avec remise ; trait = perte observee</p><div id="g-mcdd" class="graph"></div></div>
      <div class="panneau"><h3>Monte Carlo : eventail des trajectoires</h3><p class="sous">500 tirages avec remise : 5-95 %, 25-75 %, mediane, et trajectoire reelle</p><div id="g-fan" class="graph"></div></div>
    </div>
    <div class="grille-2">
      <div class="panneau"><h3>Bootstrap du Sharpe</h3><p class="sous">scipy.stats.bootstrap (BCa) sur les rendements journaliers</p><div id="g-shb" class="graph"></div></div>
      <div class="panneau"><h3>Monte Carlo : gain total</h3><p class="sous">trades tires avec remise</p><div id="g-gain" class="graph"></div></div>
    </div>
    ${famSens.length ? `<div class="grille-2">${famSens.map((fa, i) => `<div class="panneau"><h3>Sensibilite : ${esc(fa)}</h3><div id="g-sens-${i}" class="graph"></div></div>`).join("")}
      ${f.placebo ? `<div class="panneau"><h3>Placebo : memes heures, autres jours</h3><div id="g-plac" class="graph"></div></div>` : ""}</div>` : ""}
    ${f.grille ? `<div class="panneau"><h3>Plateau de parametres (Sharpe)</h3><div class="outils" id="grille-outils"></div><div id="g-grille" class="graph haut"></div></div>` : ""}
    ${f.walk_forward ? `<div class="panneau"><h3>Walk-forward : performance hors echantillon</h3><p class="sous">a chaque fenetre, le meilleur reglage des 3 annees precedentes est applique aux 6 mois suivants</p><div id="g-wf" class="graph"></div></div>` : ""}`;
  const c = couleurs();
  const mc = f.monte_carlo;
  histo($("#g-mcdd"), [mc.dd_ordre, mc.dd_remise], { observe: mc.dd_observe, noms: ["ordre melange", "tirage avec remise"] });
  const fan = mc.eventail;
  trace($("#g-fan"), [
    { x: fan.trade, y: fan.p95, mode: "lines", line: { width: 0 }, hoverinfo: "skip", showlegend: false },
    { x: fan.trade, y: fan.p5, mode: "lines", line: { width: 0 }, fill: "tonexty", fillcolor: "rgba(100,130,200,.15)", name: "5-95 %" },
    { x: fan.trade, y: fan.p75, mode: "lines", line: { width: 0 }, hoverinfo: "skip", showlegend: false },
    { x: fan.trade, y: fan.p25, mode: "lines", line: { width: 0 }, fill: "tonexty", fillcolor: "rgba(100,130,200,.3)", name: "25-75 %" },
    { x: fan.trade, y: fan.p50, mode: "lines", line: { color: c.accent, width: 1.2, dash: "dot" }, name: "mediane" },
    { x: fan.trade, y: fan.observe, mode: "lines", line: { color: c.texte, width: 1.6 }, name: "reel" }],
  { showlegend: true, xaxis: { title: { text: "trade n°" } }, yaxis: { tickformat: ".2f", title: { text: "capital (base 1)" } } });
  histo($("#g-shb"), [mc.sharpe_bootstrap], { observe: mc.sharpe, fmt: ".2f", titre: "Sharpe" });
  histo($("#g-gain"), [mc.gain_remise], { fmt: ".0%", titre: "gain total" });
  famSens.forEach((fa, i) => {
    const xs = sens.filter((x) => x.famille === fa);
    trace($(`#g-sens-${i}`), [
      { x: xs.map((x) => x.cas), y: xs.map((x) => x.sharpe), type: "bar", name: "Sharpe 2016-2026", marker: { color: c.accent } },
      { x: xs.map((x) => x.cas), y: xs.map((x) => x.sharpe_apres), type: "bar", name: "Sharpe apres publication", marker: { color: c.texte2 } }],
    { barmode: "group", showlegend: true, hovermode: "closest", margin: { l: 48, r: 8, t: 10, b: 20 }, xaxis: { automargin: true, tickangle: -25 } });
  });
  if (f.placebo) {
    trace($("#g-plac"), [{ x: f.placebo.map((x) => x.cas), y: f.placebo.map((x) => x.sharpe), type: "bar",
      marker: { color: f.placebo.map((x, i) => (i === 0 ? c.accent : x.sharpe >= 0 ? c.vert : c.rouge)) } }],
    { hovermode: "closest", margin: { l: 48, r: 8, t: 10, b: 20 }, xaxis: { automargin: true, tickangle: -25 } });
  }
  if (f.grille) rendreGrille(f);
  if (f.walk_forward) {
    const w = f.walk_forward;
    trace($("#g-wf"), [
      { x: w.dates, y: w.cumul, mode: "lines", name: "walk-forward (hors echantillon)", line: { color: c.accent } },
      { x: w.dates, y: w.retenu, mode: "lines", name: "reglage retenu", line: { color: c.texte2, dash: "dot" } }], { showlegend: true });
  }
}

function rendreGrille(f) {
  const g = f.grille;
  const axes = g.axes;
  const zone = $("#grille-outils");
  const choix = { x: axes[axes.length - 1], y: axes[0] };
  const autres = () => axes.filter((a) => a !== choix.x && a !== choix.y);
  const fixes = { ...g.reference };
  const sel = (id, v, opts) => `<label class="discret">${id} <select data-r="${id}">${opts.map((o) => `<option ${String(o) === String(v) ? "selected" : ""}>${esc(o)}</option>`).join("")}</select></label>`;
  const dessiner = () => {
    zone.innerHTML = sel("axe horizontal", choix.x, axes) + sel("axe vertical", choix.y, axes) +
      autres().map((a) => sel(a, fixes[a], g.valeurs[a])).join("") + `<span class="discret">cadre = reglage ${f.statut === "validee" ? "valide" : "etudie"}</span>`;
    zone.querySelectorAll("select").forEach((s) => s.addEventListener("change", () => {
      const r = s.dataset.r;
      if (r === "axe horizontal") choix.x = s.value; else if (r === "axe vertical") choix.y = s.value; else fixes[r] = s.value;
      if (choix.x === choix.y) choix.y = axes.find((a) => a !== choix.x);
      dessiner();
    }));
    const xs = g.valeurs[choix.x], ys = g.valeurs[choix.y];
    const z = ys.map((yv) => xs.map((xv) => {
      const p = g.points.find((q) => String(q[choix.x]) === String(xv) && String(q[choix.y]) === String(yv) && autres().every((a) => String(q[a]) === String(fixes[a])));
      return p ? p.sharpe : null;
    }));
    const c = couleurs();
    const ix = xs.findIndex((v) => String(v) === String(g.reference[choix.x])), iy = ys.findIndex((v) => String(v) === String(g.reference[choix.y]));
    const estRef = autres().every((a) => String(fixes[a]) === String(g.reference[a]));
    trace($("#g-grille"), [{ z, x: xs.map(String), y: ys.map(String), type: "heatmap", colorscale: echelle(c), zmid: 0,
      text: z.map((r) => r.map((v) => (v === null ? "" : virgule(v, 2)))), texttemplate: "%{text}", hovertemplate: `${choix.x} %{x}<br>${choix.y} %{y}<br>Sharpe %{z:.2f}<extra></extra>` }],
    { hovermode: "closest", xaxis: { title: { text: choix.x }, type: "category" }, yaxis: { title: { text: choix.y }, type: "category" },
      shapes: estRef && ix >= 0 && iy >= 0 ? [{ type: "rect", x0: ix - 0.5, x1: ix + 0.5, y0: iy - 0.5, y1: iy + 0.5, line: { color: c.texte, width: 3 } }] : [] });
  };
  dessiner();
}

async function pageComparaison() {
  const ix = etat.index;
  if (!ix || !ix.strategies.length) {
    $("#contenu").innerHTML = `<div class="panneau"><h3>Aucun resultat</h3><p>${esc(ix?.message || "")}</p>
      <p>Depuis le dossier <code>Python/</code> : <code>python -m nexus tableau --cotations CHEMIN_VERS_COTATIONS</code>, puis recharger la page.</p></div>`;
    return;
  }
  const rows = ix.strategies.map((s) => `<tr><td><a href="#" data-route="s/${encodeURIComponent(s.id)}/apercu">${esc(s.titre)}</a></td>
    <td>${s.statut === "validee" ? `<span class="badge validee">validee ${esc(s.valide_le)}</span>` : '<span class="badge candidate">candidate</span>'}</td>
    <td class="n">${num(s.kpi.sharpe)}</td><td class="n">${num(s.kpi.sortino)}</td><td class="n">${pct(s.kpi.rendement_annuel)}</td>
    <td class="n">${pct(s.kpi.volatilite)}</td><td class="n">${pct(s.kpi.perte_max)}</td><td class="n">${num(s.kpi.trades, 0)}</td>
    <td><span class="badge ok">${s.ok}</span> <span class="badge alerte">${s.alertes}</span></td></tr>`).join("");
  $("#contenu").innerHTML = `<div class="entete"><h2>Comparaison</h2></div>
    <p class="resume">Toutes les strategies exportees, leurs correlations et un portefeuille qui leur donne le meme risque. <span class="discret">${esc(ix.note || "")}</span></p>
    <div class="panneau"><h3>Strategies</h3><table><thead><tr><th>Strategie</th><th>Statut</th><th class="n">Sharpe</th><th class="n">Sortino</th><th class="n">Rendement annuel</th>
      <th class="n">Volatilite</th><th class="n">Perte max</th><th class="n">Trades</th><th>Tests</th></tr></thead><tbody>${rows}</tbody></table></div>
    <div class="grille-2">
      <div class="panneau"><h3>Correlation des rendements journaliers</h3><div id="g-corr" class="graph"></div></div>
      <div class="panneau"><h3>Correlation des rendements mensuels</h3><div id="g-corrm" class="graph"></div></div>
    </div>
    ${ix.combine ? `<div class="panneau"><h3>Portefeuille combine a risque egal</h3><p class="sous">Sharpe ${num(ix.combine.sharpe)}, perte max ${pct(ix.combine.perte_max)} ;
      chaque strategie seule est ramenee au meme risque pour comparer. ${esc(ix.combine.note || "")}</p><div id="g-comb" class="graph haut"></div></div>` : ""}`;
  const c = couleurs();
  const titres = Object.fromEntries(ix.strategies.map((s) => [s.id, s.titre]));
  for (const [id, cm] of [["#g-corr", ix.correlation], ["#g-corrm", ix.correlation_mensuelle]]) {
    if (!cm || !cm.ids.length) continue;
    const lab = cm.ids.map((i) => titres[i] || i);
    trace($(id), [{ z: cm.matrice, x: lab, y: lab, type: "heatmap", colorscale: echelle(c, c.accent), zmin: -1, zmax: 1,
      text: cm.matrice.map((r) => r.map((v) => (v === null ? "" : virgule(v, 2)))), texttemplate: "%{text}", hovertemplate: "%{x} / %{y} : %{z:.2f}<extra></extra>" }],
    { hovermode: "closest", margin: { l: 130, r: 10, t: 10, b: 80 } });
  }
  if (ix.combine) {
    const k = ix.combine;
    const tons = [c.vert, c.rouge, c.texte2, "#a855f7", "#0ea5e9"];
    trace($("#g-comb"), [{ x: k.dates, y: k.valeur, mode: "lines", name: "combine", line: { color: c.accent, width: 2 } },
      ...Object.entries(k.seules).map(([id, v], i) => ({ x: k.dates, y: v, mode: "lines", name: titres[id] || id, line: { color: tons[i % tons.length], width: 1 } }))],
    { showlegend: true, yaxis: { tickformat: ".2f" } });
  }
}

// ------------------------------------------------------------------ navigation
function aller(r) {
  try { history.replaceState(null, "", `#/${r}`); } catch (e) { /* cadre sans historique */ }
  route(r);
}

async function route(r) {
  const h = (r ?? location.hash.replace(/^#\/?/, "")).split("/");
  $("#liste").classList.remove("ouvert");
  try {
    if (h[0] === "s" && h[1]) {
      etat.id = decodeURIComponent(h[1]);
      etat.onglet = ONGLETS.some(([k]) => k === h[2]) ? h[2] : "apercu";
      rendreListe();
      $("#contenu").innerHTML = '<p class="vide">Chargement…</p>';
      const f = await fiche(etat.id);
      ({ apercu: pageApercu, fonctionnement: pageFonctionnement, vectorbt: pageVectorbt, trades: pageTrades, tests: pageTests })[etat.onglet](f);
    } else {
      etat.id = null;
      rendreListe();
      await pageComparaison();
    }
  } catch (e) {
    $("#contenu").innerHTML = `<div class="panneau"><h3>Erreur</h3><p>${esc(e.message)}</p></div>`;
  }
}

async function charger() {
  [etat.index, etat.statique] = await chargerIndex();
  etat.fiches = {};
  $("#genere").textContent = etat.index.genere_le ? `resultats du ${etat.index.genere_le}` : "";
  $("#recalculer").hidden = etat.statique;
  await route();
}

async function recalculer() {
  const dlg = $("#journal");
  const pre = $("#journal-texte");
  dlg.showModal();
  pre.textContent = "Demarrage…";
  const r = await fetch("/api/recalculer", { method: "POST", headers: { "Content-Type": "application/json" }, body: "{}" });
  const j = await r.json();
  if (!r.ok) { pre.textContent = j.message || "refuse"; return; }
  const suivre = async () => {
    const s = await json("/api/recalculer");
    pre.textContent = s.journal.join("\n");
    pre.scrollTop = pre.scrollHeight;
    if (s.enCours) setTimeout(suivre, 2000);
    else { pre.textContent += `\n\nTermine (code ${s.code}).`; if (s.code === 0) charger(); }
  };
  suivre();
}

window.addEventListener("hashchange", () => route());
document.addEventListener("click", (e) => {
  const a = e.target.closest("[data-route]");
  if (!a) return;
  e.preventDefault();
  aller(a.dataset.route);
});
window.addEventListener("DOMContentLoaded", () => {
  $("#menu").onclick = () => $("#liste").classList.toggle("ouvert");
  $("#recalculer").onclick = recalculer;
  charger().catch((e) => { $("#contenu").innerHTML = `<div class="panneau"><h3>Erreur</h3><p>${esc(e.message)}</p></div>`; });
});
