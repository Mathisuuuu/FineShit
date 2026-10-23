@echo off
rem Double-cliquer sur ce fichier (sur le serveur) pour choisir l identifiant et le mot de passe du tableau de bord,
rem puis le tableau de bord redemarre avec ce mot de passe.
cd /d "%~dp0"
set "NODE=C:\Program Files\nodejs\node.exe"
if not exist "%NODE%" set "NODE=node"
"%NODE%" mot-de-passe.js
if errorlevel 1 goto fin
schtasks /End /TN "Nexus - Tableau de bord" >nul 2>&1
schtasks /Run /TN "Nexus - Tableau de bord" >nul 2>&1 && echo Tableau de bord demarre sur le port 3000 de ce serveur.
:fin
pause
