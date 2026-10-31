#!/usr/bin/env bash
# Lance les tests automatisés (Linux, Blender en module Python « bpy », Sollumz 2.9.0, MioGtaTool compilé).
# Prérequis :
#   PYTHON         : python d'un venv avec bpy==5.2.3 (ou 4.5.x LTS), szio==1.3.0.dev9 et numpy
#   SOLLUMZ_DIR    : clone de https://github.com/Sollumz/Sollumz au tag v2.9.0
#   MIO_GTA_TOOL   : companion/publish/linux-x64/MioGtaTool (./companion/build.sh)
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
repo="$(dirname "$here")"
: "${PYTHON:?PYTHON non défini}"
: "${SOLLUMZ_DIR:?SOLLUMZ_DIR non défini}"
export MIO_GTA_TOOL="${MIO_GTA_TOOL:-$repo/companion/publish/linux-x64/MioGtaTool}"
export MIO_TEST_OUT="${MIO_TEST_OUT:-$here/_out}"
export MIO_DEV_NO_KEYS=1   # fausse installation : archives RPF non chiffrées
scripts="$MIO_TEST_OUT/bl_user/scripts"
mkdir -p "$scripts/addons"
rm -rf "$scripts/addons/sollumz" "$scripts/addons/mio_mapping_studio"
cp -r "$SOLLUMZ_DIR" "$scripts/addons/sollumz"
rm -rf "$scripts/addons/sollumz/.git" "$scripts/addons/sollumz/tests"
cp -r "$repo/addon/mio_mapping_studio" "$scripts/addons/mio_mapping_studio"
export BLENDER_USER_SCRIPTS="$scripts"
cd "$here"
"$PYTHON" make_fixtures.py
"$PYTHON" test_workflow.py "$@"
