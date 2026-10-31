"""Démarrage de Blender (module bpy) pour les tests : active Sollumz puis Mio Mapping Studio.

Variables d'environnement attendues (voir tests/run_tests.sh) :
  BLENDER_USER_SCRIPTS : dossier scripts contenant addons/sollumz et addons/mio_mapping_studio
  MIO_GTA_TOOL         : exécutable MioGtaTool compilé
  MIO_TEST_OUT         : dossier de sortie des tests
"""

import os
import sys

import bpy
import addon_utils

TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, TESTS_DIR)
OUT = os.environ.get("MIO_TEST_OUT", os.path.join(TESTS_DIR, "_out"))
os.makedirs(OUT, exist_ok=True)


def enable_addons(with_mio=True):
    bpy.utils.refresh_script_paths()
    mod = addon_utils.enable("sollumz", default_set=True, handle_error=None)
    if mod is None:
        raise RuntimeError("Sollumz introuvable dans BLENDER_USER_SCRIPTS/addons")
    if with_mio:
        mod = addon_utils.enable("mio_mapping_studio", default_set=True, handle_error=None)
        if mod is None:
            raise RuntimeError("Mio Mapping Studio introuvable")
        prefs = bpy.context.preferences.addons["mio_mapping_studio"].preferences
        prefs.companion_path = os.environ["MIO_GTA_TOOL"]
        prefs.cache_dir = os.path.join(OUT, "cache")


def reset_scene():
    bpy.ops.wm.read_homefile(use_empty=True)
