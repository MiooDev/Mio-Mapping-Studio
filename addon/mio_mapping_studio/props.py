"""Propriétés de scène de Mio Mapping Studio (Scene.mio_mapping)."""

import bpy
from bpy.props import (
    BoolProperty,
    CollectionProperty,
    EnumProperty,
    FloatProperty,
    IntProperty,
    PointerProperty,
    StringProperty,
)

from . import naming

STATUS_ITEMS = (
    ("TODO", "À faire", "Étape pas encore réalisée", "RADIOBUT_OFF", 0),
    ("READY", "Prêt", "Étape réalisée et vérifiée", "CHECKMARK", 1),
    ("WARNING", "Avertissement", "Étape réalisée avec des points à vérifier", "ERROR", 2),
    ("ERROR", "Erreur", "Étape bloquante : corriger avant l'export", "CANCEL", 3),
    ("NA", "Non applicable", "Étape sans objet dans ce mode", "REMOVE", 4),
)

EXPORT_MODE_ITEMS = (
    ("STATIC_EMBEDDED", "Mapping statique + collision intégrée",
     "Archetype Base mio_xxxx, collision Bound Composite intégrée au YDR (Physics Dictionary = mio_xxxx). "
     "Livrables : mio_xxxx.ydr, mio_xxxx.ytd, mio_xxxx.ytyp (+ YMAP de placement optionnel). Aucun MLO", 0),
    ("MLO_LIMBO", "MLO limbo + collision YBN",
     "Archetype Base mio_xxxx (sans collision intégrée) + archetype MLO mio_xxxx_col avec une room « limbo » et "
     "l'entité mio_xxxx. La collision est un fichier mio_xxxx_col.ybn séparé et l'intérieur doit être placé par un "
     "YMAP. Livrables : mio_xxxx.ydr, mio_xxxx.ytd, mio_xxxx_col.ybn, mio_xxxx.ytyp, mio_xxxx.ymap", 1),
)

GAME_GEN_ITEMS = (
    ("LEGACY", "GTA V Legacy", "Installation GTA5.exe (celle utilisée par FiveM)", 0),
    ("ENHANCED", "GTA V Enhanced", "Installation GTA5_Enhanced.exe : textures Gen9 lues puis réécrites au format "
     "Legacy pour FiveM", 1),
)

COLLISION_USAGE_ITEMS = (
    ("GENERAL", "Bâtiment / sol",
     "Preset Sollumz « General (Default) » (collision joueurs, véhicules, objets, armes, caméra) + matériau "
     "CONCRETE", 0),
    ("ROAD", "Route / parking",
     "Preset « General (Default) » + matériau TARMAC (bruit des roues, traces)", 1),
    ("TERRAIN", "Terrain naturel",
     "Preset « General (Default) » + matériau DIRT_TRACK", 2),
    ("STAIRS", "Escaliers",
     "Preset Sollumz « Stair mesh » (déplacement fluide des piétons) + matériau CONCRETE et flag STAIRS", 3),
)

ORIGIN_ITEMS = (
    ("BOUNDS_BOTTOM_CENTER", "Centre du mapping (bas)",
     "Origine du Drawable au centre XY et au point le plus bas du mapping. Recommandé : la distance d'affichage "
     "(LOD) est mesurée depuis la position de l'entité", 0),
    ("KEEP_ROOT", "Garder l'origine de la racine",
     "Conserve l'origine de l'objet racine du mapping (doit être un Drawable sans rotation ni échelle)", 1),
)

CANDIDATE_KIND_ITEMS = (
    ("SCENE", "Intégrée (scène)", "Texture intégrée au modèle importé, présente dans le .blend", 0),
    ("GAME", "Jeu (RPF)", "Texture d'origine trouvée dans l'installation GTA V", 1),
    ("LOCAL", "DDS local (secours)", "Fichier DDS déjà présent sur le disque : mode de secours, pas une recherche "
     "dans GTA", 2),
)

REF_STATUS_ITEMS = (
    ("FOUND", "Trouvée", "", "CHECKMARK", 0),
    ("AMBIGUOUS", "Ambiguë", "", "QUESTION", 1),
    ("MISSING", "Manquante", "", "CANCEL", 2),
    ("INVALID", "Invalide", "", "ERROR", 3),
)


class MIO_PG_step(bpy.types.PropertyGroup):
    status: EnumProperty(name="État", items=STATUS_ITEMS, default="TODO")
    messages: StringProperty(name="Diagnostic", default="")
    checked_at: StringProperty(default="")

    def set(self, status, messages, when=""):
        self.status = status
        self.messages = "\n".join(messages)
        self.checked_at = when


class MIO_PG_candidate(bpy.types.PropertyGroup):
    kind: EnumProperty(items=CANDIDATE_KIND_ITEMS, default="GAME")
    path: StringProperty(name="Source")
    dict_name: StringProperty(name="Dictionnaire")
    width: IntProperty()
    height: IntProperty()
    fmt: StringProperty()
    mips: IntProperty()
    priority: IntProperty()
    data_hash: StringProperty()
    note: StringProperty()


class MIO_PG_texture_ref(bpy.types.PropertyGroup):
    name: StringProperty(name="Texture")
    status: EnumProperty(items=REF_STATUS_ITEMS, default="MISSING")
    used_by: StringProperty(name="Utilisée par")
    sources: StringProperty(name="Modèles d'origine")
    reason: StringProperty(name="Décision")
    candidates: CollectionProperty(type=MIO_PG_candidate)
    candidates_index: IntProperty()
    chosen: IntProperty(default=-1)
    user_choice: StringProperty(default="", description="Clé de la source choisie manuellement")
    dds_path: StringProperty(subtype="FILE_PATH")
    meta_path: StringProperty(subtype="FILE_PATH")


def _on_name_update(self, context):
    self.asset_name = naming.normalize_mapping_name(self.mapping_name)


class MIO_PG_settings(bpy.types.PropertyGroup):
    mapping_name: StringProperty(
        name="Nom du mapping", description="Nom libre, par ex. « garage » : l'asset s'appellera « mio_garage »",
        default="", update=_on_name_update)
    asset_name: StringProperty(name="Nom de l'asset", default="")
    mapping_root: PointerProperty(
        name="Objet racine du mapping", type=bpy.types.Object,
        description="Drawable (ou objet) racine du mapping. Vide : la sélection est utilisée")
    collision_root: PointerProperty(
        name="Objet racine collision", type=bpy.types.Object,
        description="Collision importée et modifiée à réutiliser (Bound Composite de préférence). Vide : les "
                    "collisions présentes dans la sélection sont utilisées")
    gta_path: StringProperty(name="Chemin GTA V", subtype="DIR_PATH", default="",
                             description="Dossier d'installation contenant GTA5.exe ou GTA5_Enhanced.exe (lu seulement)")
    game_gen: EnumProperty(name="Génération du jeu", items=GAME_GEN_ITEMS, default="LEGACY")
    export_dir: StringProperty(name="Dossier d'export", subtype="DIR_PATH", default="")
    export_mode: EnumProperty(name="Mode d'export", items=EXPORT_MODE_ITEMS, default="STATIC_EMBEDDED")
    limbo_margin_xy: FloatProperty(name="Marge XY room limbo", default=0.5, min=0.0, soft_max=10.0, unit="LENGTH",
                                   description="Agrandit la room limbo de cette valeur de chaque côté en X et Y")
    limbo_margin_z: FloatProperty(name="Marge Z room limbo", default=0.0, min=0.0, soft_max=10.0, unit="LENGTH",
                                  description="Marge verticale optionnelle, indépendante de la marge XY")
    origin_mode: EnumProperty(name="Origine du Drawable", items=ORIGIN_ITEMS, default="BOUNDS_BOTTOM_CENTER")

    collision_usage: EnumProperty(name="Usage de la collision", items=COLLISION_USAGE_ITEMS, default="GENERAL")
    collision_replace_existing: BoolProperty(
        name="Remplacer la collision existante",
        description="Autorise « Créer les collisions depuis le mapping » à remplacer une collision existante "
                    "(une confirmation est demandée)", default=False)
    collision_decimate: BoolProperty(name="Simplifier la copie (Decimate)", default=False,
                                     description="Option explicite : réduit le nombre de triangles de la copie")
    collision_decimate_ratio: FloatProperty(name="Ratio", default=0.5, min=0.05, max=1.0)
    collision_skip_decals: BoolProperty(
        name="Ignorer décals / feuillages / eau", default=True,
        description="N'inclut pas dans la collision les faces utilisant des shaders décal, cable, herbe, "
                    "feuillage d'arbre ou eau")

    lod_dist: FloatProperty(name="Distance LOD de l'archetype", default=300.0, min=1.0, unit="LENGTH")
    hd_texture_dist: FloatProperty(name="Distance textures HD", default=100.0, min=0.0, unit="LENGTH")

    move_embedded_textures: BoolProperty(
        name="Mettre les textures intégrées dans le YTD", default=True,
        description="Les textures intégrées aux modèles importés sont placées dans mio_xxxx.ytd au lieu d'être "
                    "dupliquées dans le YDR")
    index_include_mods: BoolProperty(name="Inclure le dossier mods", default=False,
                                     description="Indexe aussi GTA V/mods (OpenIV). Désactivé : jeu d'origine seul")
    index_embedded: BoolProperty(name="Indexer les textures intégrées aux modèles (lent)", default=False,
                                 description="Lit aussi les .ydr/.ydd/.yft du jeu pour leurs textures intégrées")

    generate_ymap: BoolProperty(name="Générer le YMAP de placement", default=False,
                                description="Crée mio_xxxx.ymap qui place l'entité à sa position actuelle dans le "
                                            "monde (obligatoire et toujours généré en mode MLO)")
    generate_fivem: BoolProperty(name="Générer une ressource FiveM", default=False,
                                 description="Crée un dossier de ressource avec fxmanifest.lua et stream/")
    fivem_resource_name: StringProperty(name="Nom de la ressource", default="")

    texture_refs: CollectionProperty(type=MIO_PG_texture_ref)
    texture_refs_index: IntProperty()
    ytd_work_path: StringProperty(subtype="FILE_PATH")
    ytd_size: IntProperty()
    texture_summary: StringProperty()

    step_prepare: PointerProperty(type=MIO_PG_step)
    step_textures: PointerProperty(type=MIO_PG_step)
    step_ytyp: PointerProperty(type=MIO_PG_step)
    step_mlo: PointerProperty(type=MIO_PG_step)
    step_collision: PointerProperty(type=MIO_PG_step)
    step_export: PointerProperty(type=MIO_PG_step)

    last_report: StringProperty()

    def name_or_error(self) -> str:
        return self.asset_name or naming.normalize_mapping_name(self.mapping_name)


class MIO_PG_job(bpy.types.PropertyGroup):
    """État d'une tâche de fond (WindowManager, non sauvegardé)."""
    running: BoolProperty(default=False)
    progress: FloatProperty(default=0.0, min=0.0, max=1.0, subtype="FACTOR")
    message: StringProperty(default="")
    cancel_requested: BoolProperty(default=False)
    companion_status: StringProperty(default="")
    companion_ok: BoolProperty(default=False)


CLASSES = (MIO_PG_step, MIO_PG_candidate, MIO_PG_texture_ref, MIO_PG_settings, MIO_PG_job)


def register():
    for c in CLASSES:
        bpy.utils.register_class(c)
    bpy.types.Scene.mio_mapping = PointerProperty(type=MIO_PG_settings)
    bpy.types.WindowManager.mio_job = PointerProperty(type=MIO_PG_job)


def unregister():
    del bpy.types.WindowManager.mio_job
    del bpy.types.Scene.mio_mapping
    for c in reversed(CLASSES):
        bpy.utils.unregister_class(c)
