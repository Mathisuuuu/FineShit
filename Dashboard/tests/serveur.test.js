"use strict";
const test = require("node:test");
const assert = require("node:assert/strict");
const path = require("node:path");
const { creerServeur } = require("../serveur.js");

async function demarrer(options) {
  const srv = creerServeur(options);
  await new Promise((r) => srv.listen(0, "127.0.0.1", r));
  const base = `http://127.0.0.1:${srv.address().port}`;
  return { srv, base };
}

test("liste des strategies et fiche JSON", async () => {
  const { srv, base } = await demarrer({ donnees: path.join(__dirname, "fixtures"), config: { python: "python3", cotations: "" } });
  try {
    const ix = await (await fetch(`${base}/api/strategies`)).json();
    assert.equal(ix.strategies.length, 1);
    assert.equal(ix.strategies[0].id, "Exemple_Test");
    const f = await fetch(`${base}/api/strategies/Exemple_Test`);
    assert.equal(f.status, 200);
    assert.equal((await f.json()).titre, "Exemple");
    assert.equal((await fetch(`${base}/api/strategies/Inconnue`)).status, 404);
  } finally {
    srv.close();
  }
});

test("chemins refuses (traversee de dossier, identifiants invalides)", async () => {
  const { srv, base } = await demarrer({ donnees: path.join(__dirname, "fixtures"), config: { python: "python3", cotations: "" } });
  try {
    assert.equal((await fetch(`${base}/api/strategies/..%2Fserveur`)).status, 400);
    assert.equal((await fetch(`${base}/api/strategies/a.b`)).status, 400);
    const r = await fetch(`${base}/..%2F..%2Fserveur.js`);
    assert.ok([403, 404].includes(r.status));
    assert.equal((await fetch(`${base}/api/inconnue`)).status, 404);
  } finally {
    srv.close();
  }
});

test("interface servie et donnees absentes signalees", async () => {
  const { srv, base } = await demarrer({ donnees: path.join(__dirname, "absent"), config: { python: "python3", cotations: "" } });
  try {
    const html = await (await fetch(`${base}/`)).text();
    assert.match(html, /Nexus/);
    assert.equal((await fetch(`${base}/app.js`)).headers.get("content-type"), "text/javascript; charset=utf-8");
    const ix = await (await fetch(`${base}/api/strategies`)).json();
    assert.equal(ix.strategies.length, 0);
    assert.match(ix.message, /nexus tableau/);
  } finally {
    srv.close();
  }
});

test("recalcul refuse sans dossier Cotations configure", async () => {
  const { srv, base } = await demarrer({ donnees: path.join(__dirname, "fixtures"), config: { python: "python3", cotations: "", simulations: 10 } });
  try {
    const r = await fetch(`${base}/api/recalculer`, { method: "POST", body: "{}" });
    assert.equal(r.status, 409);
    assert.match((await r.json()).message, /config.json/);
    const s = await (await fetch(`${base}/api/recalculer`)).json();
    assert.equal(s.enCours, false);
  } finally {
    srv.close();
  }
});

test("annexes communes servies en JSON (prop firm, comparaison, etudes)", async () => {
  const { srv, base } = await demarrer({ donnees: path.join(__dirname, "fixtures"), config: { python: "python3", cotations: "" } });
  const vide = await demarrer({ donnees: path.join(__dirname, "absent"), config: { python: "python3", cotations: "" } });
  try {
    const r = await fetch(`${base}/api/annexe/prop`);
    assert.equal(r.status, 200);
    assert.match(r.headers.get("content-type"), /application\/json/);
    assert.equal((await r.json()).candidats.length, 1);
    assert.equal((await fetch(`${base}/api/annexe/inconnue`)).status, 404);          // liste blanche
    assert.equal((await fetch(`${base}/api/annexe/..%2Findex`)).status, 404);
    const absente = await fetch(`${vide.base}/api/annexe/etudes`);
    assert.equal(absente.status, 404);
    assert.match((await absente.json()).erreur, /nexus tableau/);
    assert.equal((await fetch(`${base}/api/recherche`)).status, 404);                // ancienne archive separee supprimee
    const html = await (await fetch(`${base}/`)).text();
    assert.match(html, /prop\.js/);
    assert.doesNotMatch(html, /archive\.js/);
  } finally {
    srv.close();
    vide.srv.close();
  }
});

test("acces a distance : mot de passe obligatoire et blocage apres 5 essais rates", async () => {
  const { creerAcces, verifier } = require("../serveur.js");
  const acces = creerAcces("mathis", "un-mot-de-passe-de-test");
  assert.ok(verifier(acces, "mathis", "un-mot-de-passe-de-test"));
  assert.ok(!verifier(acces, "mathis", "faux"));
  assert.ok(!JSON.stringify(acces).includes("un-mot-de-passe-de-test"));
  const { srv, base } = await demarrer({ donnees: path.join(__dirname, "fixtures"), config: { python: "python3", cotations: "" }, acces });
  const basic = (u, p) => ({ authorization: "Basic " + Buffer.from(`${u}:${p}`).toString("base64") });
  try {
    const sans = await fetch(`${base}/api/strategies`);
    assert.equal(sans.status, 401);
    assert.match(sans.headers.get("www-authenticate"), /^Basic /);
    assert.equal((await fetch(`${base}/`)).status, 401);
    assert.equal((await fetch(`${base}/api/strategies`, { headers: basic("mathis", "un-mot-de-passe-de-test") })).status, 200);
    assert.equal((await fetch(`${base}/api/strategies`, { headers: basic("autre", "un-mot-de-passe-de-test") })).status, 401);
    for (let k = 0; k < 4; k++) await fetch(`${base}/api/strategies`, { headers: basic("mathis", "faux") });
    const bloque = await fetch(`${base}/api/strategies`, { headers: basic("mathis", "un-mot-de-passe-de-test") });
    assert.equal(bloque.status, 429);
  } finally {
    srv.close();
  }
});

test("tableau restreint (serveur distant) : seulement les fiches et pages permises", async () => {
  const config = { python: "python3", cotations: "", strategies: ["Exemple_Test"], pages: ["direct"] };
  const { srv, base } = await demarrer({ donnees: path.join(__dirname, "fixtures"), config });
  const autre = await demarrer({ donnees: path.join(__dirname, "fixtures"), config: { ...config, strategies: ["Autre"] } });
  try {
    const ix = await (await fetch(`${base}/api/strategies`)).json();
    assert.deepEqual(ix.strategies.map((s) => s.id), ["Exemple_Test"]);
    assert.deepEqual(ix.pages, ["direct"]);
    assert.equal((await fetch(`${base}/api/strategies/Exemple_Test`)).status, 200);
    assert.equal((await (await fetch(`${autre.base}/api/strategies`)).json()).strategies.length, 0);
    assert.equal((await fetch(`${autre.base}/api/strategies/Exemple_Test`)).status, 404);
    const prop = await (await fetch(`${base}/api/annexe/prop`)).json();
    assert.equal(prop.erreur, "annexe inconnue");
    assert.equal((await fetch(`${base}/api/recalculer`, { method: "POST", body: "{}" })).status, 403);
  } finally {
    srv.close();
    autre.srv.close();
  }
});
