#!/usr/bin/env node
// Tableau de bord Nexus : serveur Node.js sans dependance.
// Sert l interface (public/) et les resultats exportes par le moteur Python (donnees/*.json) :
//   python -m nexus tableau --cotations <dossier Cotations>      (depuis Python/)
//   node serveur.js                                               puis http://localhost:3000
// Acces a distance (serveur) : "hote": "0.0.0.0" dans config.json ; le serveur refuse alors de demarrer sans mot de
// passe (node mot-de-passe.js -> acces.json : identifiant et empreinte scrypt, jamais le mot de passe en clair).
// Authentification HTTP Basic sur toutes les pages ; 5 essais rates depuis une adresse -> blocage de 15 minutes.
"use strict";

const http = require("node:http");
const fs = require("node:fs");
const path = require("node:path");
const crypto = require("node:crypto");
const { spawn } = require("node:child_process");

const ICI = __dirname;
const TYPES = {
  ".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8", ".css": "text/css; charset=utf-8",
  ".json": "application/json; charset=utf-8", ".svg": "image/svg+xml", ".ico": "image/x-icon", ".png": "image/png",
};
const ID_VALIDE = /^[A-Za-z0-9_-]{1,80}$/;
const ANNEXES = new Set(["rendements", "prop", "etudes", "profil", "labo", "live", "groupe"]);
const ANNEXE_DE_PAGE = { direct: "live", groupe: "groupe", comparaison: "rendements", prop: "prop", etudes: "etudes", profil: "profil", labo: "labo" };

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

// ---------------------------------------------------------------------------------------------------- acces
function empreinte(motDePasse, sel) {
  return crypto.scryptSync(String(motDePasse), Buffer.from(sel, "hex"), 64).toString("hex");
}

function creerAcces(utilisateur, motDePasse) {
  const sel = crypto.randomBytes(16).toString("hex");
  return { utilisateur, sel, empreinte: empreinte(motDePasse, sel), algo: "scrypt", cree: new Date().toISOString() };
}

function lireAcces(fichier) {
  try {
    const a = JSON.parse(fs.readFileSync(fichier, "utf8"));
    return a && a.utilisateur && a.sel && a.empreinte ? a : null;
  } catch {
    return null;
  }
}

function egal(a, b) {
  const x = crypto.createHash("sha256").update(String(a)).digest();
  const y = crypto.createHash("sha256").update(String(b)).digest();
  return crypto.timingSafeEqual(x, y);
}

function verifier(acces, utilisateur, motDePasse) {
  const ok = egal(empreinte(motDePasse, acces.sel), acces.empreinte);
  return egal(utilisateur, acces.utilisateur) && ok;
}

/** Garde HTTP Basic : vrai si la requete est autorisee, sinon repond 401 (ou 429 apres trop d essais) et rend faux. */
function creerGarde(acces, { essais = 5, blocageMs = 15 * 60 * 1000 } = {}) {
  const valides = new Set();                 // en-tetes deja verifies (empreinte sha256) : scrypt une seule fois
  const echecs = new Map();                  // adresse -> { n, jusqu }
  return function autoriser(req, res) {
    const ip = req.socket.remoteAddress || "?";
    const maintenant = Date.now();
    let e = echecs.get(ip);
    if (e && e.jusqu > maintenant) {
      envoyer(res, 429, { erreur: "trop d essais rates : reessayer dans 15 minutes" });
      return false;
    }
    const h = req.headers.authorization || "";
    const cle = crypto.createHash("sha256").update(h).digest("hex");
    if (h && valides.has(cle)) return true;
    const m = h.match(/^Basic ([A-Za-z0-9+/=]+)$/);
    let ok = false;
    if (m) {
      const txt = Buffer.from(m[1], "base64").toString("utf8");
      const i = txt.indexOf(":");
      ok = i >= 0 && verifier(acces, txt.slice(0, i), txt.slice(i + 1));
    }
    if (ok) {
      valides.add(cle);
      echecs.delete(ip);
      return true;
    }
    if (h) {
      if (!e || (e.jusqu && e.jusqu <= maintenant)) e = { n: 0, jusqu: 0 };
      e.n += 1;
      if (e.n >= essais) e.jusqu = maintenant + blocageMs;
      echecs.set(ip, e);
      console.warn(`${new Date().toISOString()} acces refuse pour ${ip} (${e.n} essai(s) rate(s))`);
    }
    res.writeHead(401, { "WWW-Authenticate": 'Basic realm="Tableau de bord Nexus", charset="UTF-8"',
                         "Content-Type": "text/plain; charset=utf-8", "Cache-Control": "no-store" });
    res.end("Identifiant et mot de passe requis.");
    return false;
  };
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
  const garde = options.acces ? creerGarde(options.acces, options.garde) : null;
  // Tableau de bord restreint (serveur distant) : "strategies" (identifiants des fiches visibles) et "pages" (pages fixes
  // visibles, ex. ["direct"]) dans config.json ; le reste est introuvable (404) et le recalcul est desactive.
  const autorisees = Array.isArray(config.strategies) ? new Set(config.strategies) : null;
  const pages = Array.isArray(config.pages) ? config.pages : null;
  const annexesPermises = pages ? new Set(pages.map((p) => ANNEXE_DE_PAGE[p]).filter(Boolean)) : null;
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
    if (garde && !garde(req, res)) return;
    const url = req.url || "/";
    if (url === "/api/strategies" && req.method === "GET") {
      fs.readFile(path.join(donnees, "index.json"), "utf8", (err, txt) => {
        if (err) {
          return envoyer(res, 200, { strategies: [], pages, message: "Aucun resultat exporte. Lancer : python -m nexus tableau --cotations <dossier>" });
        }
        if (!autorisees && !pages) return envoyer(res, 200, txt);
        let ix;
        try { ix = JSON.parse(txt); } catch { return envoyer(res, 500, { erreur: "index.json illisible" }); }
        if (autorisees) ix.strategies = (ix.strategies || []).filter((s) => autorisees.has(s.id));
        ix.non_testees = [];
        ix.prop_candidats = [];
        ix.pages = pages;
        envoyer(res, 200, ix);
      });
      return;
    }
    const m = url.match(/^\/api\/strategies\/([^/?#]+)$/);
    if (m && req.method === "GET") {
      const id = decodeURIComponent(m[1]);
      if (!ID_VALIDE.test(id)) return envoyer(res, 400, { erreur: "identifiant invalide" });
      if (autorisees && !autorisees.has(id)) return envoyer(res, 404, { erreur: `strategie ${id} introuvable` });
      fs.readFile(path.join(donnees, `${id}.json`), "utf8", (err, txt) => {
        if (err) return envoyer(res, 404, { erreur: `strategie ${id} introuvable` });
        envoyer(res, 200, txt);
      });
      return;
    }
    if (url === "/api/recalculer") {
      if (pages) return envoyer(res, 403, { erreur: "recalcul desactive sur ce tableau de bord restreint" });
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
    const gp = url.split("?")[0].match(/^\/api\/groupe\/prix\/([A-Za-z0-9]{1,8})\/(\d{4})$/);
    if (gp && req.method === "GET") {
      // prix minute autour des trades du Groupe (python -m nexus.live.rapport : groupe_prix_<instrument>_<annee>.json)
      if (annexesPermises && !annexesPermises.has("groupe")) return envoyer(res, 404, { erreur: "introuvable" });
      fs.readFile(path.join(donnees, `groupe_prix_${gp[1]}_${gp[2]}.json`), "utf8", (err, txt) => {
        if (err) return envoyer(res, 404, { erreur: `prix ${gp[1]} ${gp[2]} absents` });
        envoyer(res, 200, txt);
      });
      return;
    }
    const ax = url.split("?")[0].match(/^\/api\/annexe\/([a-z]+)$/);
    if (ax && req.method === "GET") {
      // fichiers communs ecrits par python -m nexus tableau : rendements (comparaison), prop (onglet Prop firm), etudes
      if (!ANNEXES.has(ax[1]) || (annexesPermises && !annexesPermises.has(ax[1]))) return envoyer(res, 404, { erreur: "annexe inconnue" });
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

module.exports = { creerServeur, lireConfig, creerAcces, lireAcces, verifier };

if (require.main === module) {
  const config = lireConfig(path.join(ICI, "config.json"));
  const port = Number(process.env.PORT || config.port || 3000);
  const hote = process.env.HOTE || config.hote || "127.0.0.1";
  const acces = lireAcces(path.join(ICI, "acces.json"));
  if (!["127.0.0.1", "::1", "localhost"].includes(hote) && !acces) {
    console.error(`Refus de demarrer sur ${hote} sans mot de passe : lancer d abord « node mot-de-passe.js » (cree acces.json).`);
    process.exit(1);
  }
  creerServeur({ config, acces }).listen(port, hote, () => {
    console.log(`Tableau de bord Nexus : http://${hote === "0.0.0.0" ? "localhost" : hote}:${port}`
                + (acces ? ` (mot de passe obligatoire, identifiant ${acces.utilisateur})` : ""));
    console.log(`Resultats lus dans ${path.resolve(process.env.DONNEES || path.join(ICI, "donnees"))}`);
  });
}
