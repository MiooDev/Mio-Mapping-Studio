"""Préférences de l'addon : outil compagnon, cache."""

import os
from pathlib import Path

import bpy
from bpy.props import StringProperty

ADDON_ID = __package__


def get_prefs(context=None):
    context = context or bpy.context
    addon = context.preferences.addons.get(ADDON_ID)
    return addon.preferences if addon else None


def default_cache_dir() -> Path:
    # Extension (Blender 4.2+) : dossier utilisateur dédié ; sinon dossier « datafiles » utilisateur.
    try:
        return Path(bpy.utils.extension_path_user(ADDON_ID, path="cache", create=True))
    except Exception:
        return Path(bpy.utils.user_resource("DATAFILES", path="mio_mapping_studio", create=True))


def cache_dir(context=None) -> Path:
    p = get_prefs(context)
    d = Path(bpy.path.abspath(p.cache_dir)) if p and p.cache_dir else default_cache_dir()
    d.mkdir(parents=True, exist_ok=True)
    return d


def companion_command(context=None) -> list[str] | None:
    """Commande à exécuter pour l'outil compagnon, ou None s'il n'est pas configuré."""
    p = get_prefs(context)
    path = (p.companion_path if p else "") or os.environ.get("MIO_GTA_TOOL", "")
    if not path:
        return None
    path = bpy.path.abspath(path)
    if path.lower().endswith(".dll"):
        return ["dotnet", path]
    return [path]


class MIO_AP_preferences(bpy.types.AddonPreferences):
    bl_idname = ADDON_ID

    companion_path: StringProperty(
        name="Outil compagnon MioGtaTool",
        description="Chemin de MioGtaTool.exe (compilé avec companion/build.ps1). Nécessaire pour lire les RPF, "
                    "créer le YTD binaire, compiler le XML CodeWalker et relire les exports",
        subtype="FILE_PATH", default="")
    cache_dir: StringProperty(
        name="Dossier de cache", description="Index des textures et textures extraites (vide : dossier utilisateur "
                                             "Blender)", subtype="DIR_PATH", default="")

    def draw(self, context):
        layout = self.layout
        layout.prop(self, "companion_path")
        layout.prop(self, "cache_dir")
        layout.label(text=f"Cache effectif : {cache_dir(context)}")
        row = layout.row()
        row.operator("mio.check_dependencies", icon="FILE_REFRESH")
        job = context.window_manager.mio_job
        if job.companion_status:
            box = layout.box()
            for line in job.companion_status.split("\n"):
                box.label(text=line)


CLASSES = (MIO_AP_preferences,)


def register():
    for c in CLASSES:
        bpy.utils.register_class(c)


def unregister():
    for c in reversed(CLASSES):
        bpy.utils.unregister_class(c)
