#!/usr/bin/env node
// Definit l identifiant et le mot de passe du tableau de bord (acces a distance) :
//   node mot-de-passe.js          (ou double-clic sur mot-de-passe.cmd, sur le serveur)
// Ecrit acces.json : identifiant, sel et empreinte scrypt. Le mot de passe n est jamais enregistre ni affiche.
// Redemarrer ensuite le tableau de bord pour qu il prenne le nouveau mot de passe.
"use strict";

const fs = require("node:fs");
const path = require("node:path");
const readline = require("node:readline");
const { creerAcces } = require("./serveur.js");

const FICHIER = path.join(__dirname, "acces.json");
const MIN = 12;

// une seule lecture du clavier pour toutes les questions ; chaque ligne recue attend sa question dans une file
// (sinon une saisie arrivee d un bloc, ou trop tot, est perdue)
const rl = readline.createInterface({ input: process.stdin, output: process.stdout, terminal: !!process.stdin.isTTY });
let muet = false;
rl._writeToOutput = (s) => { if (!muet) rl.output.write(s); };      // rien ne s affiche pendant la frappe du mot de passe
const lignes = [];
let attente = null;
rl.on("line", (l) => {
  if (attente) {
    const f = attente;
    attente = null;
    f(l);
  } else lignes.push(l);
});
rl.on("close", () => {
  if (attente) {
    const f = attente;
    attente = null;
    f(null);
  }
});

function demander(question, cache) {
  return new Promise((resolve) => {
    muet = false;
    rl.output.write(question);
    muet = cache;
    const fin = (r) => {
      muet = false;
      if (cache) rl.output.write("\n");
      resolve(r);
    };
    if (lignes.length) fin(lignes.shift());
    else attente = fin;
  });
}

function arreter(message, code) {
  (code ? console.error : console.log)(message);
  rl.close();
  process.exitCode = code;
}

(async () => {
  const id = await demander("Identifiant (Entree = mathis) : ", false);
  if (id === null) return arreter("Saisie interrompue. Rien n a ete change.", 1);
  const utilisateur = id.trim() || "mathis";
  const mdp = await demander(`Mot de passe (${MIN} caracteres minimum, rien ne s affiche) : `, true);
  if (mdp === null) return arreter("Saisie interrompue. Rien n a ete change.", 1);
  if (mdp.length < MIN) return arreter(`Trop court : ${MIN} caracteres minimum. Rien n a ete change.`, 1);
  const confirmation = await demander("Retapez le mot de passe : ", true);
  if (confirmation !== mdp) return arreter("Les deux saisies different. Rien n a ete change.", 1);
  fs.writeFileSync(FICHIER, JSON.stringify(creerAcces(utilisateur, mdp), null, 2) + "\n", { mode: 0o600 });
  arreter(`Enregistre dans ${FICHIER} (identifiant « ${utilisateur} »). Le tableau de bord va redemarrer avec ce mot de passe.`, 0);
})();
