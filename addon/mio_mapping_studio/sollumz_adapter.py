"""Adaptateur Sollumz : SEUL module de l'addon qui importe du code Sollumz.

Versions prises en charge : Sollumz 2.9.x (testé : 2.9.0, août 2026).
Toutes les API utilisées ici ont été lues dans le code source officiel de Sollumz 2.9.0
(https://github.com/Sollumz/Sollumz, tag v2.9.0). Si une future version change ces API, c'est ce
fichier qu'il faut adapter ; le reste de l'addon passe par les fonctions ci-dessous.

Références (Sollumz 2.9.0) :
  - sollumz_properties.py : SollumType, MaterialType, ArchetypeType, AssetType, LODLevel, BOUND_TYPES
  - lods.py : Object.sz_lods (get_lod(level).mesh)
  - tools/blenderhelper.py : create_empty_object, create_blender_object
  - tools/drawablehelper.py : convert_obj_to_model
  - tools/boundhelper.py : apply_flag_preset (presets « General (Default) », « Stair mesh »...)
  - ybn/collision_materials.py : collisionmats, create_collision_material_from_index
  - ybn/ybnexport.py : MAX_VERTICES (32767 sommets par géométrie de collision)
  - ydr/ydrexport.py : create_embedded_bounds_asset (un seul Bound racine enfant direct du Drawable)
  - ytyp/properties/ytyp.py : Scene.ytyps, CMapTypesProperties.new_archetype, ArchetypeProperties.new_room/new_entity
  - ytyp/properties/mlo.py : MAX_LIMBO_ROOM_ENTITIES (12)
  - ytd/properties.py : Scene.sz_txds (dictionnaires de textures de la scène)
  - sollumz_operators.py : sollumz.export_assets (direct_export, use_custom_settings, target_formats/versions)
  - logger.py : use_logger / LoggerBase (capture des avertissements de l'export)
  - dependencies.py : IS_SZIO_NATIVE_AVAILABLE (export binaire natif via PyMateria)
"""

from __future__ import annotations

import importlib
import re
import sys
from pathlib import Path

import bpy

SUPPORTED_MIN = (2, 9, 0)
SUPPORTED_MAX_EXCLUSIVE = (2, 10, 0)
TESTED_VERSIONS = ("2.9.0",)


class SollumzUnavailable(RuntimeError):
    pass


def _find_package_name() -> str | None:
    """Sollumz peut être installé comme add-on (« sollumz ») ou extension (« bl_ext.<dépôt>.sollumz »)."""
    for key in bpy.context.preferences.addons.keys():
        if key == "sollumz" or key.endswith(".sollumz"):
            mod = sys.modules.get(key)
            if mod is not None:
                return key
    return None


def _parse_version(text: str) -> tuple[int, ...] | None:
    m = re.match(r"^\s*(\d+)\.(\d+)\.(\d+)", text or "")
    return tuple(int(x) for x in m.groups()) if m else None


class _Sollumz:
    """Accès paresseux aux modules Sollumz. Instancié par get()."""

    def __init__(self, package: str):
        self.package = package
        self.root = sys.modules[package]
        self.props = self._mod("sollumz_properties")
        self.lods = self._mod("lods")
        self.blenderhelper = self._mod("tools.blenderhelper")
        self.drawablehelper = self._mod("tools.drawablehelper")
        self.boundhelper = self._mod("tools.boundhelper")
        self.collision_materials = self._mod("ybn.collision_materials")
        self.ybnexport = self._mod("ybn.ybnexport")
        self.sollumz_helper = self._mod("sollumz_helper")
        self.logger = self._mod("logger")
        self.dependencies = self._mod("dependencies")
        self.meta = self._mod("meta")
        self.ytyp_mlo = self._mod("ytyp.properties.mlo")
        self.version_str = self.meta.sollumz_version()
        self.version = _parse_version(self.version_str)

        p = self.props
        self.SollumType = p.SollumType
        self.MaterialType = p.MaterialType
        self.ArchetypeType = p.ArchetypeType
        self.AssetType = p.AssetType
        self.LODLevel = p.LODLevel
        self.BOUND_TYPES = set(p.BOUND_TYPES)
        self.BOUND_POLYGON_TYPES = set(p.BOUND_POLYGON_TYPES)

    def _mod(self, name: str):
        return importlib.import_module(f"{self.package}.{name}")


_cache: _Sollumz | None = None


def get() -> _Sollumz:
    """Retourne l'adaptateur, ou lève SollumzUnavailable avec un message en français."""
    global _cache
    pkg = _find_package_name()
    if pkg is None:
        _cache = None
        raise SollumzUnavailable(
            "Sollumz n'est pas activé. Installe Sollumz 2.9.x et active-le dans Préférences > Add-ons."
        )
    if _cache is None or _cache.package != pkg:
        try:
            _cache = _Sollumz(pkg)
        except Exception as e:  # module manquant : version incompatible ou dépendances non installées
            _cache = None
            raise SollumzUnavailable(
                f"Sollumz est activé mais ses modules sont inaccessibles ({e}). Vérifie que ses dépendances "
                "(szio) sont installées depuis les préférences de Sollumz."
            ) from e
    return _cache


def status() -> tuple[bool, str]:
    """(compatible, message) pour l'interface."""
    try:
        sz = get()
    except SollumzUnavailable as e:
        return False, str(e)
    v = sz.version
    if v is None:
        return False, f"Version de Sollumz illisible ({sz.version_str})."
    if not (SUPPORTED_MIN <= v < SUPPORTED_MAX_EXCLUSIVE):
        return False, (
            f"Sollumz {sz.version_str} détecté : version non prise en charge. Mio Mapping Studio est validé avec "
            f"Sollumz 2.9.x (testé : {', '.join(TESTED_VERSIONS)})."
        )
    if not getattr(sz.dependencies, "IS_SZIO_AVAILABLE", False):
        return False, "La dépendance szio de Sollumz n'est pas installée (Préférences > Sollumz > Install)."
    return True, f"Sollumz {sz.version_str}"


def native_export_available() -> bool:
    """Export binaire direct (YDR/YBN/YTYP/YTD natifs) : nécessite PyMateria (Windows) dans Sollumz."""
    try:
        return bool(get().dependencies.IS_SZIO_NATIVE_AVAILABLE)
    except SollumzUnavailable:
        return False


# --------------------------------------------------------------------------------------------------------------------
# Types d'objets
# --------------------------------------------------------------------------------------------------------------------

def sollum_type(obj) -> str:
    return getattr(obj, "sollum_type", "sollumz_none") if obj is not None else "sollumz_none"


def is_drawable(obj) -> bool:
    return sollum_type(obj) == get().SollumType.DRAWABLE


def is_model(obj) -> bool:
    return sollum_type(obj) == get().SollumType.DRAWABLE_MODEL


def is_light(obj) -> bool:
    return sollum_type(obj) == get().SollumType.LIGHT


def is_composite(obj) -> bool:
    return sollum_type(obj) == get().SollumType.BOUND_COMPOSITE


def is_bound(obj) -> bool:
    sz = get()
    t = sollum_type(obj)
    return t in sz.BOUND_TYPES or t in sz.BOUND_POLYGON_TYPES


def is_bound_root_child(obj) -> bool:
    """Types autorisés comme enfants directs d'un Bound Composite."""
    sz = get()
    t = sollum_type(obj)
    return t in sz.BOUND_TYPES and t != sz.SollumType.BOUND_COMPOSITE


def is_bvh(obj) -> bool:
    return sollum_type(obj) == get().SollumType.BOUND_GEOMETRYBVH


def is_poly_mesh(obj) -> bool:
    return sollum_type(obj) == get().SollumType.BOUND_POLY_TRIANGLE


def is_bound_geometry(obj) -> bool:
    return sollum_type(obj) == get().SollumType.BOUND_GEOMETRY


def is_unsupported_root(obj) -> str | None:
    """Types que la fusion automatique ne prend pas en charge."""
    sz = get()
    t = sollum_type(obj)
    names = {
        sz.SollumType.FRAGMENT: "Fragment (YFT)",
        sz.SollumType.DRAWABLE_DICTIONARY: "Drawable Dictionary (YDD)",
        sz.SollumType.CLIP_DICTIONARY: "Clip Dictionary (YCD)",
    }
    return names.get(t)


def is_shader_material(mat) -> bool:
    return mat is not None and getattr(mat, "sollum_type", None) == get().MaterialType.SHADER


def is_collision_material(mat) -> bool:
    return mat is not None and getattr(mat, "sollum_type", None) == get().MaterialType.COLLISION


def find_sollumz_root(obj):
    return get().sollumz_helper.find_sollumz_parent(obj)


# --------------------------------------------------------------------------------------------------------------------
# Création d'objets / conversion
# --------------------------------------------------------------------------------------------------------------------

def create_empty(kind: str, name: str, collection=None):
    """kind: 'DRAWABLE' | 'BOUND_COMPOSITE' | 'BOUND_GEOMETRYBVH'."""
    sz = get()
    st = getattr(sz.SollumType, kind)
    obj = sz.blenderhelper.create_empty_object(st, name)
    if collection is not None:
        for c in list(obj.users_collection):
            c.objects.unlink(obj)
        collection.objects.link(obj)
    obj.name = name
    return obj


def create_poly_mesh_object(name: str, mesh, collection):
    sz = get()
    obj = bpy.data.objects.new(name, mesh)
    obj.sollum_type = sz.SollumType.BOUND_POLY_TRIANGLE
    collection.objects.link(obj)
    return obj


def convert_mesh_to_model(obj):
    """Utilise la conversion officielle Sollumz (mesh -> Drawable Model, LOD High = mesh courant)."""
    get().drawablehelper.convert_obj_to_model(obj)


def lod_levels():
    L = get().LODLevel
    return [L.VERYHIGH, L.HIGH, L.MEDIUM, L.LOW, L.VERYLOW]


def base_lod_levels():
    L = get().LODLevel
    return [L.HIGH, L.MEDIUM, L.LOW, L.VERYLOW]


def lod_meshes(model_obj) -> dict:
    """{niveau LOD: mesh} pour un Drawable Model (seulement les niveaux qui ont un mesh)."""
    out = {}
    lods = model_obj.sz_lods
    for level in lod_levels():
        m = lods.get_lod(level).mesh
        if m is not None:
            out[level] = m
    return out


def set_lod_mesh(model_obj, level, mesh):
    model_obj.sz_lods.get_lod(level).mesh = mesh


def lod_label(level) -> str:
    L = get().LODLevel
    return {L.VERYHIGH: "Very High", L.HIGH: "High", L.MEDIUM: "Medium", L.LOW: "Low", L.VERYLOW: "Very Low"}.get(level, str(level))


def lod_dist_props(drawable_obj):
    return drawable_obj.drawable_properties


# --------------------------------------------------------------------------------------------------------------------
# Matériaux et shaders
# --------------------------------------------------------------------------------------------------------------------

def shader_texture_nodes(mat):
    """[(nom du paramètre, node)] pour les paramètres de type texture du shader GTA du matériau.

    Même règle que l'exporteur Sollumz (ydr/ydrexport.py::create_shader) : seuls les nodes Image Texture dont le nom
    est un paramètre du shader sont exportés ; le nom de texture exporté est node.sollumz_texture_name
    (nom du fichier de l'image, sans extension).
    """
    from szio.gta5.shader import ShaderManager, ShaderParameterType  # dépendance de Sollumz

    shader_def = ShaderManager.find_shader(mat.shader_properties.filename)
    if shader_def is None or mat.node_tree is None:
        return []
    out = []
    for node in mat.node_tree.nodes:
        if not isinstance(node, bpy.types.ShaderNodeTexImage):
            continue
        pdef = shader_def.parameter_map.get(node.name)
        if pdef is None or pdef.type != ShaderParameterType.TEXTURE:
            continue
        out.append((pdef.name, node))
    return out


def shader_filename(mat) -> str:
    return (mat.shader_properties.filename or "").lower()


def texture_name_of_node(node) -> str:
    return node.sollumz_texture_name or ""


def is_node_embedded(node) -> bool:
    return bool(node.texture_properties.embedded)


def set_node_embedded(node, value: bool):
    node.texture_properties.embedded = value


def collision_material_defs():
    """[(index, nom interne, nom affiché)] des matériaux de collision GTA connus de Sollumz."""
    return [(i, m.name, m.ui_name) for i, m in enumerate(get().collision_materials.collisionmats)]


def collision_material_index(name: str) -> int | None:
    for i, m in enumerate(get().collision_materials.collisionmats):
        if m.name == name:
            return i
    return None


def create_collision_material(index: int):
    return get().collision_materials.create_collision_material_from_index(index)


def collision_material_index_of(mat) -> int:
    return int(mat.collision_properties.collision_index)


def apply_flag_preset(obj, preset_name: str) -> bool:
    """Applique un preset de flags Sollumz (composite_flags1/2) sur un objet bound."""
    sz = get()
    try:
        if sz.boundhelper.apply_flag_preset(obj, preset_name):
            return True
    except Exception:
        pass
    # Repli : lecture directe du fichier de presets livré avec Sollumz.
    import json
    path = Path(sz.root.__file__).parent / "ybn" / "gta5" / "presets" / "flag_presets.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except OSError:
        return False
    for p in data.get("presets", []):
        if p.get("name") == preset_name:
            f1 = p["data"].get("composite_flags1", {})
            f2 = p["data"].get("composite_flags2", {})
            for n in type(obj.composite_flags1).__annotations__:
                setattr(obj.composite_flags1, n, bool(f1.get(n, False)))
                setattr(obj.composite_flags2, n, bool(f2.get(n, False)))
            return True
    return False


def bound_flags_empty(obj) -> bool:
    names = list(type(obj.composite_flags1).__annotations__)
    return not any(getattr(obj.composite_flags1, n) for n in names) and not any(
        getattr(obj.composite_flags2, n) for n in names)


def bvh_max_vertices() -> int:
    return int(getattr(get().ybnexport, "MAX_VERTICES", 32767))


def max_limbo_entities() -> int:
    return int(getattr(get().ytyp_mlo, "MAX_LIMBO_ROOM_ENTITIES", 12))


# --------------------------------------------------------------------------------------------------------------------
# YTYP / archetypes / MLO
# --------------------------------------------------------------------------------------------------------------------

def find_ytyp(scene, name: str):
    for i, y in enumerate(scene.ytyps):
        if y.name.lower() == name.lower():
            return i, y
    return None, None


def ensure_ytyp(scene, name: str):
    idx, y = find_ytyp(scene, name)
    if y is None:
        y = scene.ytyps.add()
        y.name = name
        idx = len(scene.ytyps) - 1
    scene.ytyp_index = idx  # Sollumz résout les rooms/portals via le YTYP sélectionné
    return idx, y


def find_archetype(ytyp, name: str):
    for i, a in enumerate(ytyp.archetypes):
        if a.name.lower() == name.lower():
            return i, a
    return None, None


def new_archetype(ytyp, kind: str):
    sz = get()
    return ytyp.new_archetype(getattr(sz.ArchetypeType, kind))


def remove_archetype(ytyp, index: int):
    ytyp.archetypes.remove(index)
    if len(ytyp.archetypes):
        ytyp.archetypes.select(max(0, min(index, len(ytyp.archetypes) - 1)))


def archetype_kind(arch) -> str:
    sz = get()
    return {sz.ArchetypeType.BASE: "BASE", sz.ArchetypeType.MLO: "MLO", sz.ArchetypeType.TIME: "TIME"}.get(arch.type, "?")


def asset_type_value(kind: str):
    return getattr(get().AssetType, kind)


def set_flags_total(flags_pg, value: int):
    flags_pg.total = str(int(value))


def flags_total(flags_pg) -> int:
    try:
        return int(flags_pg.total)
    except (TypeError, ValueError):
        return 0


# --------------------------------------------------------------------------------------------------------------------
# Dictionnaires de textures de la scène (Sollumz 2.9)
# --------------------------------------------------------------------------------------------------------------------

def ensure_scene_txd(scene, name: str, images):
    """Crée/actualise le dictionnaire de textures Sollumz « name » avec exactement ces images (sans doublon)."""
    txds = scene.sz_txds
    txd = None
    for t in txds.texture_dictionaries:
        if t.name.lower() == name.lower():
            txd = t
            break
    if txd is None:
        txd = txds.new_texture_dictionary(name)
    while len(txd.textures):
        txd.textures.remove(len(txd.textures) - 1)
    for img in images:
        txd.new_texture(img)
    return txd


# --------------------------------------------------------------------------------------------------------------------
# Export Sollumz (opérateur officiel) avec capture des messages
# --------------------------------------------------------------------------------------------------------------------

def export_assets(context, directory: str, *, objects=(), ytyp_index: int | None = None, native: bool,
                  gen9: bool = False) -> tuple[bool, list[tuple[str, str]]]:
    """Exporte avec sollumz.export_assets (pas de réimplémentation de l'exporteur).

    Retourne (succès, [(niveau, message)]). Succès = opérateur FINISHED et aucune ERREUR rapportée.
    """
    sz = get()
    messages: list[tuple[str, str]] = []

    class _Capture(sz.logger.LoggerBase):
        def do_log(self, msg, level):
            messages.append((level, str(msg)))

    view_layer = context.view_layer
    prev_selected = [o for o in view_layer.objects if o.select_get()]
    prev_active = view_layer.objects.active
    prev_ytyp_index = context.scene.ytyp_index
    try:
        for o in prev_selected:
            o.select_set(False)
        for o in objects:
            o.hide_set(False)
            o.select_set(True)
        if objects:
            view_layer.objects.active = objects[0]
        if ytyp_index is not None:
            context.scene.ytyp_index = ytyp_index
        with sz.logger.use_logger(_Capture()):
            result = bpy.ops.sollumz.export_assets(
                directory=directory,
                direct_export=True,
                use_custom_settings=True,
                target_formats={"NATIVE" if native else "CWXML"},
                target_versions={"GEN9" if gen9 else "GEN8"},
                limit_to_selected=True,
                apply_transforms=False,
                exclude_skeleton=False,
                mesh_domain="FACE_CORNER",
                export_ytyps=ytyp_index is not None,
                export_ytyps_include="SELECTED",
                export_ymaps=False,
                export_ytds=False,
            )
    finally:
        for o in view_layer.objects:
            if o.select_get():
                o.select_set(False)
        for o in prev_selected:
            if o.name in view_layer.objects:
                o.select_set(True)
        view_layer.objects.active = prev_active
        context.scene.ytyp_index = prev_ytyp_index
    ok = "FINISHED" in result and not any(lvl == "ERROR" for lvl, _ in messages)
    return ok, messages
