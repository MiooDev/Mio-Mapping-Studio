#!/usr/bin/env bash
# Compilation de MioGtaTool (Linux/macOS, utilise pour les tests automatises).
# Prerequis : git et le SDK .NET 8.
# Usage : ./build.sh [RID]   (RID par defaut : linux-x64 ; "win-x64" produit l'executable Windows autonome)
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
commit="$(tr -d '[:space:]' < "$here/CODEWALKER_COMMIT.txt")"
cw="$here/third_party/CodeWalker"
rid="${1:-linux-x64}"

command -v git >/dev/null || { echo "git est requis" >&2; exit 1; }
command -v dotnet >/dev/null || { echo "Le SDK .NET 8 est requis" >&2; exit 1; }

if [ ! -f "$cw/CodeWalker.Core/CodeWalker.Core.csproj" ]; then
  echo "Recuperation de CodeWalker au commit $commit ..."
  mkdir -p "$here/third_party"
  git clone https://github.com/dexyfex/CodeWalker.git "$cw"
fi
( cd "$cw" && (git fetch --depth 1 origin "$commit" 2>/dev/null || true) && git checkout --quiet "$commit" )

out="$here/publish/$rid"
if [ "$rid" = "win-x64" ]; then
  dotnet publish "$here/MioGtaTool/MioGtaTool.csproj" -c Release -r win-x64 --self-contained true \
    -p:PublishSingleFile=true -p:IncludeNativeLibrariesForSelfExtract=true -o "$out"
else
  dotnet publish "$here/MioGtaTool/MioGtaTool.csproj" -c Release -r "$rid" --self-contained false -o "$out"
  "$out/MioGtaTool" version
fi
echo "OK : $out"
