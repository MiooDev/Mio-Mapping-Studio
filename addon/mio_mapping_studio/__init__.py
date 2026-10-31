# Mio Mapping Studio — préparation de mappings GTA V / FiveM avec Sollumz.
# Licence : GPL-3.0-or-later (voir LICENSE).

bl_info = {
    "name": "Mio Mapping Studio",
    "author": "MiooDev",
    "version": (1, 0, 0),
    "blender": (4, 2, 0),
    "location": "Vue 3D > Barre latérale (N) > Mio Mapping Studio",
    "description": "Hiérarchie Sollumz, collisions, textures GTA d'origine (YTD), YTYP et export vérifié pour FiveM",
    "category": "Import-Export",
    "doc_url": "https://github.com/MiooDev/mio-mapping-studio",
}

if "bpy" in locals():
    import importlib
    for _m in ("naming", "sollumz_adapter", "geom", "props", "prefs", "companion", "sharing", "hierarchy",
               "collision", "ytyp_tools", "diagnostics", "fivem", "export_pipeline", "operators", "ui", "startup"):
        if _m in locals():
            importlib.reload(locals()[_m])

import bpy  # noqa: E402

from . import props, prefs, operators, ui, startup  # noqa: E402

_MODULES = (props, prefs, operators, ui, startup)


def register():
    for m in _MODULES:
        m.register()


def unregister():
    for m in reversed(_MODULES):
        m.unregister()
