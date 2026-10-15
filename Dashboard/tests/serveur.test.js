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
