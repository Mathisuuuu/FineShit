#!/usr/bin/env node
// Tableau de bord Nexus : serveur Node.js sans dependance.
// Sert l interface (public/) et les resultats exportes par le moteur Python (donnees/*.json) :
//   python -m nexus tableau --cotations <dossier Cotations>      (depuis Python/)
//   node serveur.js                                               puis http://localhost:3000
"use strict";

const http = require("node:http");
const fs = require("node:fs");
const path = require("node:path");
const { spawn } = require("node:child_process");

const ICI = __dirname;
const TYPES = {
  ".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8", ".css": "text/css; charset=utf-8",
  ".json": "application/json; charset=utf-8", ".svg": "image/svg+xml", ".ico": "image/x-icon", ".png": "image/png",
};
const ID_VALIDE = /^[A-Za-z0-9_-]{1,80}$/;
const ANNEXES = new Set(["rendements", "prop", "etudes", "profil", "labo", "live"]);

function lireConfig(fichier) {
  // Par defaut : l environnement Python du projet (Python/.venv) et le dossier Cotations du depot, s ils existent.
  const venv = path.join(ICI, "..", "Python", ".venv", process.platform === "win32" ? "Scripts/python.exe" : "bin/python");
  const cotations = path.join(ICI, "..", "Cotations");
  const defaut = {
    python: fs.existsSync(venv) ? venv : process.platform === "win32" ? "python" : "python3",
    cotations: fs.existsSync(cotations) ? cotations : "", simulations: 2000, sans_grille: false,
  };
  try {
    return { ...defaut, ...JSON.parse(fs.readFileSync(fichier, "utf8")) };
  } catch {
    return defaut;
  }
}

function envoyer(res, code, corps, type = "application/json; charset=utf-8") {
  res.writeHead(code, { "Content-Type": type, "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff" });
  res.end(typeof corps === "string" || Buffer.isBuffer(corps) ? corps : JSON.stringify(corps));
}

function fichierStatique(res, racine, url) {
  const rel = decodeURIComponent(url.split("?")[0]).replace(/^\/+/, "") || "index.html";
  const cible = path.resolve(racine, rel);
  if (!cible.startsWith(path.resolve(racine) + path.sep) && cible !== path.resolve(racine, "index.html")) {
    return envoyer(res, 403, { erreur: "chemin refuse" });
  }
  fs.readFile(cible, (err, buf) => {
    if (err) return envoyer(res, 404, { erreur: "introuvable" });
    envoyer(res, 200, buf, TYPES[path.extname(cible).toLowerCase()] || "application/octet-stream");
  });
}

function creerServeur(options = {}) {
  const donnees = path.resolve(options.donnees || process.env.DONNEES || path.join(ICI, "donnees"));
  const publicDir = path.resolve(options.public || path.join(ICI, "public"));
  const config = options.config || lireConfig(path.join(ICI, "config.json"));
  const travail = { enCours: false, debut: null, fin: null, code: null, journal: [] };

  function recalculer(corps) {
    if (travail.enCours) return { ok: false, message: "un calcul est deja en cours" };
    const cotations = (corps && corps.cotations) || config.cotations;
    if (!cotations) return { ok: false, message: "dossier Cotations inconnu : renseigner \"cotations\" dans Dashboard/config.json" };
    const args = ["-m", "nexus", "tableau", "--cotations", cotations, "--sortie", donnees, "--simulations", String(config.simulations)];
    if (config.sans_grille) args.push("--sans-grille");
    Object.assign(travail, { enCours: true, debut: new Date().toISOString(), fin: null, code: null, journal: [`${config.python} ${args.join(" ")}`] });
    const p = spawn(config.python, args, { cwd: path.join(ICI, "..", "Python"), windowsHide: true });
    const ligne = (b) => b.toString().split(/\r?\n/).filter((l) => l && !/warn/i.test(l)).forEach((l) => {
      travail.journal.push(l);
      if (travail.journal.length > 400) travail.journal.shift();
    });
    p.stdout.on("data", ligne);
    p.stderr.on("data", ligne);
    p.on("error", (e) => { travail.journal.push(`erreur : ${e.message}`); travail.enCours = false; travail.code = -1; });
    p.on("close", (code) => { travail.enCours = false; travail.code = code; travail.fin = new Date().toISOString(); });
    return { ok: true, message: "calcul lance" };
  }

  return http.createServer((req, res) => {
    const url = req.url || "/";
    if (url === "/api/strategies" && req.method === "GET") {
      fs.readFile(path.join(donnees, "index.json"), "utf8", (err, txt) => {
        if (err) {
          return envoyer(res, 200, { strategies: [], message: "Aucun resultat exporte. Lancer : python -m nexus tableau --cotations <dossier>" });
        }
        envoyer(res, 200, txt);
      });
      return;
    }
    const m = url.match(/^\/api\/strategies\/([^/?#]+)$/);
    if (m && req.method === "GET") {
      const id = decodeURIComponent(m[1]);
      if (!ID_VALIDE.test(id)) return envoyer(res, 400, { erreur: "identifiant invalide" });
      fs.readFile(path.join(donnees, `${id}.json`), "utf8", (err, txt) => {
        if (err) return envoyer(res, 404, { erreur: `strategie ${id} introuvable` });
        envoyer(res, 200, txt);
      });
      return;
    }
    if (url === "/api/recalculer") {
      if (req.method === "GET") return envoyer(res, 200, travail);
      if (req.method === "POST") {
        let corps = "";
        req.on("data", (c) => { corps += c; if (corps.length > 1e4) req.destroy(); });
        req.on("end", () => {
          let json = {};
          try { json = corps ? JSON.parse(corps) : {}; } catch { return envoyer(res, 400, { erreur: "JSON invalide" }); }
          const r = recalculer(json);
          envoyer(res, r.ok ? 202 : 409, r);
        });
        return;
      }
      return envoyer(res, 405, { erreur: "methode non autorisee" });
    }
    const ax = url.split("?")[0].match(/^\/api\/annexe\/([a-z]+)$/);
    if (ax && req.method === "GET") {
      // fichiers communs ecrits par python -m nexus tableau : rendements (comparaison), prop (onglet Prop firm), etudes
      if (!ANNEXES.has(ax[1])) return envoyer(res, 404, { erreur: "annexe inconnue" });
      fs.readFile(path.join(donnees, `${ax[1]}.json`), "utf8", (err, txt) => {
        if (err) return envoyer(res, 404, { erreur: `${ax[1]}.json absent : lancer python -m nexus tableau (depuis Python/)` });
        envoyer(res, 200, txt);
      });
      return;
    }
    if (url.startsWith("/api/")) return envoyer(res, 404, { erreur: "route inconnue" });
    if (req.method !== "GET") return envoyer(res, 405, { erreur: "methode non autorisee" });
    fichierStatique(res, publicDir, url);
  });
}

module.exports = { creerServeur, lireConfig };

if (require.main === module) {
  const port = Number(process.env.PORT || 3000);
  const hote = process.env.HOTE || "127.0.0.1";
  creerServeur().listen(port, hote, () => {
    console.log(`Tableau de bord Nexus : http://${hote === "0.0.0.0" ? "localhost" : hote}:${port}`);
    console.log(`Resultats lus dans ${path.resolve(process.env.DONNEES || path.join(ICI, "donnees"))}`);
  });
}
