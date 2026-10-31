# Compilation de MioGtaTool (Windows).
# Prerequis : Git et le SDK .NET 8 (https://dotnet.microsoft.com/download/dotnet/8.0).
# Usage :  powershell -ExecutionPolicy Bypass -File build.ps1
# Resultat : companion\publish\win-x64\MioGtaTool.exe (autonome, ne necessite pas d'installer .NET pour l'executer).

$ErrorActionPreference = "Stop"
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$commit = (Get-Content (Join-Path $here "CODEWALKER_COMMIT.txt") -Raw).Trim()
$cw = Join-Path $here "third_party\CodeWalker"

if (-not (Get-Command git -ErrorAction SilentlyContinue)) { throw "Git est requis pour recuperer CodeWalker." }
if (-not (Get-Command dotnet -ErrorAction SilentlyContinue)) { throw "Le SDK .NET 8 est requis (dotnet introuvable)." }

if (-not (Test-Path (Join-Path $cw "CodeWalker.Core\CodeWalker.Core.csproj"))) {
    Write-Host "Recuperation de CodeWalker (dexyfex/CodeWalker) au commit $commit ..."
    New-Item -ItemType Directory -Force -Path (Join-Path $here "third_party") | Out-Null
    git clone https://github.com/dexyfex/CodeWalker.git $cw
}
Push-Location $cw
git fetch --depth 1 origin $commit 2>$null
git checkout --quiet $commit
Pop-Location

$out = Join-Path $here "publish\win-x64"
dotnet publish (Join-Path $here "MioGtaTool\MioGtaTool.csproj") -c Release -r win-x64 --self-contained true `
    -p:PublishSingleFile=true -p:IncludeNativeLibrariesForSelfExtract=true -o $out
if ($LASTEXITCODE -ne 0) { throw "La compilation a echoue." }

& (Join-Path $out "MioGtaTool.exe") version
Write-Host ""
Write-Host "OK. Dans Blender > Preferences > Add-ons > Mio Mapping Studio, indique :"
Write-Host "  $(Join-Path $out 'MioGtaTool.exe')"
