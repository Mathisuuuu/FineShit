// Tableau de bord Nexus : page « Groupe ». Tout vient de NinjaTrader (historique 1 minute archive par le moteur, ordres
// du compte demo) et tous les calculs de vectorbt (Python/nexus/live/rapport.py -> donnees/groupe.json) : combinaison
// sur les annees, drawdown, Sharpe cumule et glissant, rendements, correlation, Monte Carlo, statistiques, graphiques
// des actifs avec les trades aux prix, tous les ordres emis. Bandeau du compte demo relu toutes les 5 s (live.json),
// rapport relu toutes les 2 min.
"use strict";

const Groupe = (function () {
  let G = null, minuteries = [];
  const vue = { ordres: "demo", tout: false, jour: null, inst: null };
  const GRIS = ["#98a2b3", "#b9c0cc", "#7a8394"];

  function oublier() { G = null; minuteries.forEach(clearInterval); minuteries = []; }
  const pc = (v, d = 2) => (v === null || v === undefined || !isFinite(v) ? "–" : (v * 100).toFixed(d).replace(".", ",") + " %");
  const nb = (v, d = 2) => (v === null || v === undefined || !isFinite(v) ? "–" : Number(v).toLocaleString("fr-FR", { minimumFractionDigits: d, maximumFractionDigits: d }));
  const stat = (liste, nom) => { const x = (liste || []).find((s) => s[0] === nom); return x ? x[1] : null; };
  const val = (v) => (v === null || v === undefined ? "–" : typeof v === "number" ? nb(v, Math.abs(v) >= 1000 ? 0 : Math.abs(v) < 0.01 && v !== 0 ? 5 : 3) : esc(String(v)));
  const signe = (v) => (v === null || v === undefined || !isFinite(v) || v === 0 ? "" : v > 0 ? "pos" : "neg");
  const surPage = () => window.etat && window.etat.page === "groupe" && !window.etat.id;

  async function lire(url) {
    const r = await fetch(url + "?t=" + Date.now(), { cache: "no-store" });
    if (!r.ok) throw new Error(String(r.status));
    return r.json();
  }
  const urlGroupe = () => (G && G.statique ? "donnees/groupe.json" : "/api/annexe/groupe");

  async function page(statique) {
    oublier();
    $("#contenu").innerHTML = '<p class="vide">Chargement du Groupe…</p>';
    try {
      G = await lire(statique ? "donnees/groupe.json" : "/api/annexe/groupe");
    } catch (e) {
      G = { manquant: true };
    }
    G.statique = statique;
    rendre();
    bandeau();
    minuteries.push(setInterval(() => { if (surPage()) bandeau(); else oublier(); }, 5000));
    minuteries.push(setInterval(async () => {
      if (!surPage()) return oublier();
      try {
        const n = await lire(urlGroupe());
        if (n.genere !== G.genere) { n.statique = G.statique; G = n; const y = window.scrollY; rendre(); bandeau(); window.scrollTo(0, y); }
      } catch (e) { /* rapport en cours d ecriture */ }
    }, 120000));
  }

  // ------------------------------------------------------------------ bandeau du compte demo (live.json)
  async function bandeau() {
    const el = $("#gp-direct");
    if (!el) return;
    let L;
    try { L = await lire(G.statique ? "donnees/live.json" : "/api/annexe/live"); } catch (e) {
      el.innerHTML = '<span><span class="point rouge"></span>NinjaTrader ne publie pas encore l’état du compte démo (AddOn NexusTableau)</span>';
      return;
    }
    const P = L.passerelle || {};
    const verrou = L.suspension || P.verrou || "";
    const pos = Object.entries(L.instruments || {}).filter(([, x]) => x.position || x.cible)
      .map(([i, x]) => `<b class="${signe(x.position)}">${esc(i)} ${x.position > 0 ? "+" : ""}${x.position ?? 0}</b>`).join(" ") || "à plat";
    const derniere = Object.values(L.instruments || {}).map((x) => x.derniere_barre && x.derniere_barre.heure).filter(Boolean).sort().pop();
    el.innerHTML = `<span><span class="point ${P.connecte ? "vert" : "rouge"}"></span>${P.connecte ? "relié à NinjaTrader" : "NinjaTrader déconnecté"}</span>
      <span><span class="etiq">compte</span>${esc(P.compte || "–")}${P.simulation ? " (démo)" : P.compte ? " <b class='neg'>(réel)</b>" : ""}</span>
      <span><span class="etiq">garde-fou</span>${verrou ? `<span class="point orange"></span><span class="etat-garde">${esc(verrou)}</span>` : "aucun"}</span>
      <span><span class="etiq">positions</span>${pos}</span>
      <span><span class="etiq">jour</span><b class="${signe(P.resultat_jour)}">${P.resultat_jour > 0 ? "+" : ""}${nb(P.resultat_jour, 0)} $</b></span>
      <span><span class="etiq">liquidatif</span><b>${nb(P.valeur_liquidative, 0)} $</b></span>
      <span class="discret">dernière barre ${esc(derniere || "–")} ET · <a href="#/direct">détail</a></span>`;
  }

  // ------------------------------------------------------------------ page
  function tableStats(titre, liste) {
    return `<div class="panneau"><h3>${esc(titre)}</h3><div class="tablebox"><table><tbody>${(liste || []).map((s) =>
      `<tr><td>${esc(s[0])}</td><td class="num">${val(s[1])}</td></tr>`).join("")}</tbody></table></div></div>`;
  }

  const SECTIONS = [["synthese", "Synthèse"], ["courbes", "Combinaison"], ["risque", "Risque"], ["montecarlo", "Monte Carlo"],
    ["correlation", "Corrélation"], ["statistiques", "Statistiques"], ["actifs", "Actifs et trades"], ["ordres", "Ordres"]];

  function rendre() {
    const C = G.combinaison;
    const nav = `<nav class="nav-groupe">${SECTIONS.map(([k, l]) => `<a href="#" data-sec="${k}">${l}</a>`).join("")}</nav>`;
    const donnees = Object.entries(G.donnees || {}).map(([i, d]) => `${esc(i)} : ${nb(d.barres, 0)} barres 1 min, du ${esc(d.debut.slice(0, 10))} au ${esc(d.fin.slice(0, 10))}`).join(" · ");
    const remarques = [...(G.erreurs || []), ...(G.notes || [])];
    const erreurs = remarques.length ? `<div class="panneau"><h3>À noter</h3>${remarques.map((e) => `<p>${esc(e)}</p>`).join("")}</div>` : "";
    const depuis = G.debut_forward ? `forward depuis le ${esc(G.debut_forward.slice(0, 10))} · ` : "";
    const tete = (titre) => `<div class="entete"><h2>${titre}</h2>${G.genere ? `<span class="discret">${depuis}rapport du ${esc(G.genere.slice(0, 16).replace("T", " "))} UTC</span>` : ""}</div>
      <div id="gp-direct" class="direct-bandeau"><span class="discret">compte démo…</span></div>`;
    const panneauCompte = () => (G.compte && G.compte.x && G.compte.x.length
      ? `<div class="panneau"><h3>Valeur du compte démo NinjaTrader</h3><p class="sous">valeur liquidative relevée par le moteur toutes les 15 minutes</p><div id="gp-compte" class="graph"></div></div>` : "");
    const panneauxActifs = (avecTrades) => Object.keys(G.bougies || {}).map((i) => `<div class="panneau"><h3>${esc(i)} : bougies journalières${avecTrades ? " et trades" : ""}</h3>${avecTrades
      ? `<p class="sous"><span class="pos">▲ entrée longue</span> · <span class="neg">▼ entrée courte</span> · ✕ sortie, aux prix d'exécution du compte démo</p>` : ""}<div id="gp-act-${esc(i)}" class="graph haut"></div></div>`).join("");
    if (!C) {
      const msg = G.manquant ? "Le premier rapport arrive dans les 15 minutes qui suivent la connexion du moteur à NinjaTrader."
        : "Aucune exécution sur le compte démo pour l'instant : les courbes et statistiques apparaîtront après les premiers trades. " + esc(G.source || "");
      $("#contenu").innerHTML = `<div class="archive groupe">${tete("Forward test du Groupe")}<p class="resume">${msg}</p><p class="discret">${donnees}</p>${erreurs}
        ${G.manquant ? "" : panneauCompte() + `<section id="actifs">${panneauxActifs(false)}</section><section id="ordres">${blocOrdres()}</section>`}</div>`;
      if (!G.manquant) {
        dessinerCompte();
        for (const i of Object.keys(G.bougies || {})) dessinerActif(i);
        brancherOrdres();
      }
      return;
    }
    const s = C.stats, mc = C.monte_carlo;
    const kpi = (v, l, cl = "") => `<div class="kpi ${cl}"><div class="v">${v}</div><div class="l">${l}</div></div>`;
    const rt = stat(s, "Total Return [%]") / 100, ra = stat(s, "Annualized Return [%]") / 100, sh = stat(s, "Sharpe Ratio");
    const blocMC = mc ? `<p class="sous">${nb(mc.chemins, 0)} chemins, bootstrap par blocs de ${mc.bloc} jours ; bandes 25-75 % et 5-95 %, trait plein : le réel</p>
        <div class="kpis">
          ${kpi(pc(mc.final.proba_perte, 1), "probabilité de perte", mc.final.proba_perte > 0.05 ? "neg" : "pos")}
          ${kpi(pc(mc.final.p5, 1), "rendement final, 5 %", signe(mc.final.p5))}
          ${kpi(pc(mc.final.p50, 1), "rendement final, médiane", signe(mc.final.p50))}
          ${kpi(pc(mc.perte_max.p95, 1), "perte max, 95 %", "neg")}
          ${kpi(pc(mc.perte_max.p99, 1), "perte max, 99 %", "neg")}
          ${kpi(pc(mc.ordre_trades.p95, 1), "perte max, trades mélangés (95 %)", "neg")}
        </div>
        <div id="gp-mc" class="graph haut"></div>
        <div class="grille-2"><div id="gp-mcf" class="graph"></div><div id="gp-mcd" class="graph"></div></div>`
      : `<p class="discret">Disponible après 20 jours de forward (${nb(C.jours, 0)} pour l'instant).</p>`;
    $("#contenu").innerHTML = `<div class="archive groupe">${tete(`Forward test du Groupe <span class="discret">${C.membres.map(esc).join(" + ")}</span>`)}${nav}
      <p class="resume">${esc(G.source)}<br><span class="discret">${donnees}</span></p>${erreurs}
      <section id="synthese"><div class="kpis">
        ${kpi(pc(rt), "rendement total", signe(rt))}
        ${kpi(pc(ra), "rendement annuel", signe(ra))}
        ${kpi(nb(sh), "Sharpe", "accent")}
        ${kpi(nb(stat(s, "Sortino Ratio")), "Sortino")}
        ${kpi(pc(-stat(s, "Max Drawdown [%]") / 100), "perte max", "neg")}
        ${kpi(pc(stat(s, "Annualized Volatility [%]") / 100), "volatilité")}
        ${kpi(nb(C.capital, 0) + " $", "capital")}
        ${kpi(nb((G.trades || []).length, 0), "trades")}
      </div></section>
      <section id="courbes"><div class="panneau"><h3>Courbe du Groupe (forward, exécutions du compte démo)</h3><p class="sous">bleu : le Groupe ; gris : chaque stratégie sur son capital</p><div id="gp-eq" class="graph haut"></div></div>
      ${panneauCompte()}
      <div class="panneau"><h3>Rendements annuels</h3><div id="gp-an" class="graph"></div></div>
      <div class="panneau"><h3>Rendements mensuels du Groupe</h3>${tableMois(C.mensuels)}</div></section>
      <section id="risque" class="grille-2">
        <div class="panneau"><h3>Drawdown du Groupe</h3><div id="gp-dd" class="graph"></div></div>
        <div class="panneau"><h3>Sharpe cumulé et glissant (252 j)</h3><div id="gp-sh" class="graph"></div></div>
      </section>
      <section id="montecarlo"><div class="panneau"><h3>Monte Carlo du Groupe</h3>${blocMC}</div></section>
      <section id="correlation"><div class="panneau"><h3>Corrélation entre les stratégies</h3>${tableCorr(C.correlation)}${C.correlation_glissante && C.correlation_glissante.x ? '<div id="gp-corr" class="graph"></div>' : ""}</div></section>
      <section id="statistiques"><div class="grille-2">${tableStats("Groupe : statistiques vectorbt", s)}
        ${G.strategies.map((x) => tableStats(`${x.nom} (${x.instrument}) : rendements`, x.stats)).join("")}</div>
      <div class="grille-2">${G.strategies.map((x) => tableStats(`${x.nom} : portefeuille`, x.stats_portefeuille) + tableStats(`${x.nom} : trades`, x.stats_trades)).join("")}</div></section>
      <section id="actifs">${panneauxActifs(true)}
        <div class="panneau"><h3>Une journée minute par minute</h3>${choixJour()}<div id="gp-jour" class="graph haut"></div></div></section>
      <section id="ordres">${blocOrdres()}</section></div>`;
    document.querySelectorAll(".nav-groupe [data-sec]").forEach((a) => {
      a.onclick = (e) => { e.preventDefault(); const t = document.getElementById(a.dataset.sec); if (t) t.scrollIntoView({ behavior: "smooth", block: "start" }); };
    });
    dessiner();
    brancherOrdres();
    brancherJour();
  }

  function tableCorr(c) {
    if (!c) return "<p class='discret'>disponible quand au moins deux stratégies ont tradé sur 5 jours</p>";
    const cl = (v) => (Math.abs(v) >= 0.3 && v < 0.999 ? "neg" : "");
    return `<div class="tablebox"><table><thead><tr><th></th>${c.noms.map((n) => `<th>${esc(n)}</th>`).join("")}</tr></thead><tbody>${c.noms.map((n, i) =>
      `<tr><td>${esc(n)}</td>${c.m[i].map((v) => `<td class="num ${cl(v)}">${nb(v, 3)}</td>`).join("")}</tr>`).join("")}</tbody></table></div>`;
  }

  function tableMois(m) {
    const mois = ["janv", "févr", "mars", "avr", "mai", "juin", "juil", "août", "sept", "oct", "nov", "déc"];
    return `<div class="tablebox"><table><thead><tr><th>Année</th>${mois.map((x) => `<th>${x}</th>`).join("")}</tr></thead><tbody>${Object.keys(m || {}).sort().map((a) =>
      `<tr><td>${a}</td>${m[a].map((v) => `<td class="num ${signe(v)}">${v === null ? "" : pc(v, 1)}</td>`).join("")}</tr>`).join("")}</tbody></table></div>`;
  }

  function dessiner() {
    const C = G.combinaison, c = couleurs();
    const tirets = ["dash", "dot", "dashdot"];
    trace($("#gp-eq"), [...G.strategies.map((s, k) => ({ x: s.equity.x, y: s.equity.y, name: s.nom, line: { color: GRIS[k % 3], width: 1.2, dash: tirets[k % 3] } })),
      { x: C.equity.x, y: C.equity.y, name: "Groupe", line: { color: c.accent, width: 2.5 } }],
      { showlegend: true, yaxis: { tickformat: ",.0f", ticksuffix: " $" } });
    trace($("#gp-dd"), [{ x: C.drawdown.x, y: C.drawdown.y, fill: "tozeroy", line: { color: c.rouge, width: 1 }, fillcolor: "rgba(229,72,77,0.15)", name: "drawdown" }],
      { yaxis: { tickformat: ".1%" } });
    trace($("#gp-sh"), [{ x: C.sharpe_glissant.x, y: C.sharpe_glissant.y, name: "glissant 252 j", line: { color: GRIS[0], width: 1.2 } },
      { x: C.sharpe_cumule.x, y: C.sharpe_cumule.y, name: "cumulé", line: { color: c.accent, width: 2.5 } }],
      { showlegend: true, shapes: [{ type: "line", xref: "paper", x0: 0, x1: 1, y0: 0, y1: 0, line: { color: c.rouge, width: 1, dash: "dot" } }] });
    const annees = Object.keys(C.annuels).sort();
    trace($("#gp-an"), [{ type: "bar", x: annees, y: annees.map((a) => C.annuels[a]), name: "Groupe",
        marker: { color: annees.map((a) => (C.annuels[a] >= 0 ? c.vert : c.rouge)) }, text: annees.map((a) => pc(C.annuels[a], 1)), textposition: "outside" },
      ...G.strategies.map((s, k) => ({ type: "bar", x: annees, y: annees.map((a) => s.annuels[a] ?? null), name: s.nom, marker: { color: GRIS[k % 3] } }))],
      { barmode: "group", showlegend: true, yaxis: { tickformat: ".0%" }, hovermode: "closest" });
    const rc = C.correlation_glissante;
    if (rc && rc.x) trace($("#gp-corr"), [{ x: rc.x, y: rc.y, name: `${rc.paire[0]} / ${rc.paire[1]}`, line: { color: c.accent, width: 1.5 } }],
      { yaxis: { range: [-1, 1], title: { text: "corrélation glissante 126 j" } },
        shapes: [0.3, -0.3].map((y) => ({ type: "line", xref: "paper", x0: 0, x1: 1, y0: y, y1: y, line: { color: c.rouge, width: 1, dash: "dot" } })) });
    dessinerCompte();
    for (const i of Object.keys(G.bougies || {})) dessinerActif(i);
    if (!C.monte_carlo) return;
    const e = C.monte_carlo.eventail;
    trace($("#gp-mc"), [
      { x: e.x, y: e.p95, line: { width: 0 }, hoverinfo: "skip" },
      { x: e.x, y: e.p5, fill: "tonexty", fillcolor: "rgba(47,111,237,0.10)", line: { width: 0 }, name: "5-95 %" },
      { x: e.x, y: e.p75, line: { width: 0 }, hoverinfo: "skip" },
      { x: e.x, y: e.p25, fill: "tonexty", fillcolor: "rgba(47,111,237,0.22)", line: { width: 0 }, name: "25-75 %" },
      { x: e.x, y: e.p50, line: { color: c.accent, dash: "dash", width: 1 }, name: "médiane" },
      { x: e.x, y: e.reel, line: { color: c.texte, width: 2 }, name: "réel" }], { yaxis: { tickformat: ".2f", title: { text: "capital (1 = départ)" } } });
    const barres = (h, col) => ({ type: "bar", x: h.bords.slice(0, -1).map((b, i) => (b + h.bords[i + 1]) / 2), y: h.n, marker: { color: col } });
    const fin = C.monte_carlo.final;
    trace($("#gp-mcf"), [{ ...barres(fin, fin.bords.slice(0, -1).map((b) => (b < 0 ? c.rouge : c.vert))) }],
      { xaxis: { tickformat: ".0%", title: { text: "rendement final" } }, hovermode: "closest", bargap: 0.05 });
    const pm = C.monte_carlo.perte_max;
    trace($("#gp-mcd"), [barres(pm, GRIS[0])], { xaxis: { tickformat: ".1%", title: { text: "perte maximale" } }, hovermode: "closest", bargap: 0.05,
      shapes: [{ type: "line", x0: pm.p95, x1: pm.p95, yref: "paper", y0: 0, y1: 1, line: { color: c.rouge, width: 2, dash: "dash" } }],
      annotations: [{ x: pm.p95, yref: "paper", y: 1, text: " 95 %", showarrow: false, xanchor: "left", font: { color: c.rouge, size: 11 } }] });
  }

  function dessinerCompte() {
    const el = $("#gp-compte");
    if (!el || !G.compte || !G.compte.x.length) return;
    const c = couleurs();
    trace(el, [{ x: G.compte.x.map((h) => h.replace(" ", "T")), y: G.compte.y, name: "valeur liquidative", line: { color: c.accent, width: 2 }, fill: "tozeroy", fillcolor: "rgba(47,111,237,0.06)" }],
      { yaxis: { tickformat: ",.0f", ticksuffix: " $", autorange: true, rangemode: "normal" }, xaxis: { title: { text: "heure de New York" } } });
  }

  function sourceDe(nom) { const s = (G.strategies || []).find((x) => x.nom === nom); return s ? s.source_prix : null; }

  function marqueurs(trades, xEntree, xSortie) {
    const c = couleurs();
    const L = trades.filter((t) => t.sens === "long"), S = trades.filter((t) => t.sens === "short");
    const txt = (t) => `${t.strategie} ${t.sens} ${nb(t.contrats, 0)} @ ${nb(t.prix_entree, 5)} → ${nb(t.prix_sortie, 5)} : ${nb(t.pnl, 0)} $`;
    return [
      { type: "scatter", mode: "markers", x: L.map(xEntree), y: L.map((t) => t.prix_entree), name: "entrée longue", text: L.map(txt), hoverinfo: "text+x",
        marker: { symbol: "triangle-up", size: 10, color: c.vert } },
      { type: "scatter", mode: "markers", x: S.map(xEntree), y: S.map((t) => t.prix_entree), name: "entrée courte", text: S.map(txt), hoverinfo: "text+x",
        marker: { symbol: "triangle-down", size: 10, color: c.rouge } },
      { type: "scatter", mode: "markers", x: trades.map(xSortie), y: trades.map((t) => t.prix_sortie), name: "sortie", text: trades.map(txt), hoverinfo: "text+x",
        marker: { symbol: "x-thin", size: 9, color: c.texte, line: { color: c.texte, width: 1.5 } } }];
  }

  const jourNY = (iso) => new Date(iso).toLocaleDateString("sv-SE", { timeZone: "America/New_York" });
  const heureNY = (iso) => new Date(iso).toLocaleString("sv-SE", { timeZone: "America/New_York" }).replace(" ", "T");

  function bougies(x, o, h, l, cl) {
    return { type: "candlestick", x, open: o, high: h, low: l, close: cl, name: "prix",
      increasing: { line: { color: "#98a2b3", width: 1 }, fillcolor: "#ffffff" }, decreasing: { line: { color: "#667085", width: 1 }, fillcolor: "#98a2b3" } };
  }

  function dessinerActif(i) {
    const b = G.bougies[i];
    const tr = (G.trades || []).filter((t) => sourceDe(t.strategie) === i);
    trace($(`#gp-act-${i}`), [bougies(b.x, b.o, b.h, b.l, b.c), ...marqueurs(tr, (t) => jourNY(t.entree), (t) => jourNY(t.sortie))],
      { showlegend: true, hovermode: "closest", xaxis: { rangeslider: { visible: false }, type: "date" } });
  }

  function joursTrades() {
    const out = [];
    for (const t of G.trades || []) {
      const i = sourceDe(t.strategie), j = jourNY(t.entree);
      if (i && !out.some((x) => x.i === i && x.j === j)) out.push({ i, j });
    }
    return out.sort((a, b) => (a.j < b.j ? 1 : -1));
  }

  function choixJour() {
    const J = joursTrades();
    if (!J.length) return "<p class='discret'>aucun trade</p>";
    if (!vue.jour) { vue.jour = J[0].j; vue.inst = J[0].i; }
    return `<label>Journée : <select id="gp-choix">${J.map((x) => `<option value="${x.i}|${x.j}" ${x.i === vue.inst && x.j === vue.jour ? "selected" : ""}>${x.j} · ${esc(x.i)}</option>`).join("")}</select></label>`;
  }

  async function dessinerJour() {
    if (!vue.jour || !$("#gp-jour")) return;
    const an = vue.jour.slice(0, 4);
    G.cachePrix = G.cachePrix || {};
    const cle = `${vue.inst}_${an}`;
    if (!G.cachePrix[cle]) {
      const url = G.statique ? `donnees/groupe_prix_${vue.inst}_${an}.json` : `/api/groupe/prix/${encodeURIComponent(vue.inst)}/${an}`;
      try { G.cachePrix[cle] = await json(url); } catch (e) { $("#gp-jour").innerHTML = `<p class="discret">${esc(e.message)}</p>`; return; }
    }
    const barres = G.cachePrix[cle][vue.jour] || [];
    const x = barres.map((r) => heureNY(new Date(r[0]).toISOString()));
    const tr = (G.trades || []).filter((t) => sourceDe(t.strategie) === vue.inst && jourNY(t.entree) === vue.jour);
    trace($("#gp-jour"), [bougies(x, barres.map((r) => r[1]), barres.map((r) => r[2]), barres.map((r) => r[3]), barres.map((r) => r[4])),
      ...marqueurs(tr, (t) => heureNY(t.entree), (t) => heureNY(t.sortie))],
      { showlegend: true, hovermode: "closest", xaxis: { rangeslider: { visible: false }, type: "date", title: { text: "heure de New York" } } });
  }

  function brancherJour() {
    const s = $("#gp-choix");
    if (s) s.onchange = () => { [vue.inst, vue.jour] = s.value.split("|"); dessinerJour(); };
    dessinerJour();
  }

  // ------------------------------------------------------------------ ordres
  function blocOrdres() {
    const D = G.demo || {};
    const onglets = [["demo", `Compte démo (${(D.executions || []).length} exécutions)`], ["cibles", `Cibles envoyées (${(D.cibles || []).length})`],
      ["simules", `Ordres sur l'historique (${(G.ordres_simules || []).length})`], ["trades", `Trades (${(G.trades || []).length})`]];
    return `<div class="panneau"><h3>Tous les ordres émis</h3><div class="onglets-groupe">${onglets.map(([k, l]) =>
      `<button class="bouton ${vue.ordres === k ? "actif" : ""}" data-o="${k}">${esc(l)}</button>`).join("")}</div><div id="gp-ordres">${tableOrdres()}</div></div>`;
  }

  function lignes(L, cols) {
    const tri = L.slice().reverse();
    const vis = vue.tout ? tri : tri.slice(0, 300);
    const plus = tri.length > vis.length ? `<p><button class="bouton" id="gp-tout">Afficher les ${tri.length} lignes</button></p>` : "";
    return `<div class="tablebox"><table><thead><tr>${cols.map((c) => `<th>${c[0]}</th>`).join("")}</tr></thead><tbody>${vis.map((r) =>
      `<tr>${cols.map((c) => `<td class="${typeof c[2] === "function" ? c[2](r) : c[2] || ""}">${c[1](r)}</td>`).join("")}</tr>`).join("") || `<tr><td colspan="${cols.length}" class="discret">aucune ligne</td></tr>`}</tbody></table></div>${plus}`;
  }

  function tableOrdres() {
    const D = G.demo || {};
    const t = (r) => esc(r.heure_et || "");
    const etatCl = (r) => (r.etat === "Filled" ? "pos" : r.etat === "Rejected" || r.etat === "Cancelled" ? "neg" : "");
    if (vue.ordres === "demo") {
      return "<h4>Exécutions</h4>" + lignes(D.executions || [], [["Heure ET", t], ["Instrument", (r) => esc(r.instrument)], ["Quantité", (r) => val(r.qty), (r) => "num " + signe(r.qty)],
          ["Prix", (r) => val(r.prix), "num"], ["Ordre", (r) => esc(r.ordre)], ["Nom", (r) => esc(r.nom || "")]])
        + "<h4>Ordres (états renvoyés par NinjaTrader)</h4>" + lignes(D.ordres || [], [["Heure ET", t], ["Instrument", (r) => esc(r.instrument)], ["Ordre", (r) => esc(r.ordre)],
          ["État", (r) => esc(r.etat), etatCl], ["Rempli", (r) => val(r.rempli), "num"], ["Prix moyen", (r) => val(r.prix_moyen), "num"], ["Texte", (r) => esc(r.texte || "")]]);
    }
    if (vue.ordres === "cibles") {
      return lignes(D.cibles || [], [["Heure ET", t], ["Instrument", (r) => esc(r.instrument)], ["Cible nette", (r) => val(r.qty), (r) => "num " + signe(r.qty)], ["Stratégies", (r) => esc(r.ref || "")]]);
    }
    if (vue.ordres === "simules") {
      return lignes(G.ordres_simules || [], [["Heure ET", (r) => esc(heureNY(r.t).replace("T", " "))], ["Stratégie", (r) => esc(r.strategie)], ["Instrument", (r) => esc(r.instrument)],
        ["Côté", (r) => esc(r.cote), (r) => (r.cote === "achat" ? "pos" : "neg")], ["Contrats", (r) => val(r.contrats), "num"], ["Prix", (r) => val(r.prix), "num"], ["Frais $", (r) => val(r.frais), "num"]]);
    }
    return lignes(G.trades || [], [["Entrée ET", (r) => esc(heureNY(r.entree).replace("T", " "))], ["Sortie ET", (r) => esc(heureNY(r.sortie).replace("T", " "))],
      ["Stratégie", (r) => esc(r.strategie)], ["Sens", (r) => esc(r.sens), (r) => (r.sens === "long" ? "pos" : "neg")], ["Contrats", (r) => val(r.contrats), "num"],
      ["Prix entrée", (r) => val(r.prix_entree), "num"], ["Prix sortie", (r) => val(r.prix_sortie), "num"],
      ["P&L $", (r) => val(r.pnl), (r) => "num " + signe(r.pnl)], ["Rendement", (r) => pc(r.rendement), (r) => "num " + signe(r.rendement)]]);
  }

  function brancherOrdres() {
    document.querySelectorAll(".onglets-groupe [data-o]").forEach((b) => {
      b.onclick = () => { vue.ordres = b.dataset.o; vue.tout = false; rafraichirOrdres(); };
    });
    const tout = $("#gp-tout");
    if (tout) tout.onclick = () => { vue.tout = true; rafraichirOrdres(); };
  }

  function rafraichirOrdres() {
    $("#gp-ordres").innerHTML = tableOrdres();
    document.querySelectorAll(".onglets-groupe [data-o]").forEach((b) => b.classList.toggle("actif", b.dataset.o === vue.ordres));
    brancherOrdres();
  }

  return { page, oublier };
})();
