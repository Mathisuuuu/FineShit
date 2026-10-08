# =============================================================================
#  Installer.ps1 - installe les strategies Nexus dans NinjaTrader 8
#
#  Usage (PowerShell, depuis ce dossier) :
#      powershell -ExecutionPolicy Bypass -File .\Installer.ps1
#      powershell -ExecutionPolicy Bypass -File .\Installer.ps1 -ForceData   (ecrase aussi les modeles de donnees)
#
#  1. Copie AddOns\*.cs     -> Documents\NinjaTrader 8\bin\Custom\AddOns
#  2. Copie Strategies\*.cs -> Documents\NinjaTrader 8\bin\Custom\Strategies
#  3. Cree Documents\NinjaTrader 8\Nexus\{data,journal,reports,cache,returns,state,tools}
#  4. Copie les modeles Data\* dans Nexus\data SANS ecraser vos fichiers existants
#  5. Copie Tools\* dans Nexus\tools
#  Ensuite : NinjaTrader > New > NinjaScript Editor > F5 (compiler).
# =============================================================================
param([switch]$ForceData)

$ErrorActionPreference = 'Stop'
$src = Split-Path -Parent $MyInvocation.MyCommand.Path
$nt = Join-Path ([Environment]::GetFolderPath('MyDocuments')) 'NinjaTrader 8'
$custom = Join-Path $nt 'bin\Custom'
if (-not (Test-Path $custom)) { Write-Error "Dossier NinjaTrader 8 introuvable : $custom"; exit 1 }

$addons = Join-Path $custom 'AddOns'
$strats = Join-Path $custom 'Strategies'
New-Item -ItemType Directory -Force $addons | Out-Null
New-Item -ItemType Directory -Force $strats | Out-Null

Copy-Item (Join-Path $src 'AddOns\*.cs') $addons -Force
Copy-Item (Join-Path $src 'Strategies\*.cs') $strats -Force
Write-Host ("Code copie : {0} fichiers AddOns, {1} fichiers Strategies" -f `
    (Get-ChildItem (Join-Path $src 'AddOns') -Filter *.cs).Count, (Get-ChildItem (Join-Path $src 'Strategies') -Filter *.cs).Count)

$nexus = Join-Path $nt 'Nexus'
foreach ($d in 'data', 'journal', 'reports', 'cache', 'returns', 'state', 'tools') {
    New-Item -ItemType Directory -Force (Join-Path $nexus $d) | Out-Null
}
foreach ($f in Get-ChildItem (Join-Path $src 'Data') -File) {
    $dst = Join-Path $nexus ('data\' + $f.Name)
    if ((-not (Test-Path $dst)) -or $ForceData) { Copy-Item $f.FullName $dst -Force; Write-Host "Modele copie : $dst" }
    else { Write-Host "Conserve (existant) : $dst" }
}
Copy-Item (Join-Path $src 'Tools\*') (Join-Path $nexus 'tools') -Force

Write-Host ""
Write-Host "Installation terminee."
Write-Host " - Compiler : NinjaTrader > New > NinjaScript Editor > F5"
Write-Host " - Cles API : copier $nexus\data\keys.txt.example en $nexus\keys.txt et le remplir"
Write-Host " - Interrupteur global : creer le fichier $nexus\KILL_SWITCH (ou strategie NexusC_PortfolioMonitor)"
