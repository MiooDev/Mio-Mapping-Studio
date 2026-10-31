"""Étape 1 : préparation de la hiérarchie Sollumz du mapping.

Résultat : un seul Drawable « mio_xxxx » dont les enfants directs sont les Drawable Models du bâtiment, du sol et
des autres éléments visibles choisis. Les meshes ne sont PAS fusionnés : chaque modèle garde ses LOD, UV, Color
Attributes, matériaux et paramètres de shader. Les positions dans le monde ne changent pas.
"""

from __future__ import annotations

import bpy
import numpy as np
from mathutils import Matrix, Vector

from . import geom, naming
from . import sollumz_adapter as sza

ARCHIVE_PREFIX = "MIO_ARCHIVE_"


class StepResult:
    def __init__(self):
        self.errors: list[str] = []
        self.warnings: list[str] = []
        self.infos: list[str] = []
        self.status_override: str | None = None

    @property
    def status(self) -> str:
        if self.errors:
            return "ERROR"
        if self.warnings:
            return "WARNING"
        return "READY"

    def lines(self) -> list[str]:
        return ([f"Erreur : {e}" for e in self.errors] + [f"Attention : {w}" for w in self.warnings] + self.infos)

    def extend(self, other: "StepResult"):
        self.errors += other.errors
        self.warnings += other.warnings
        self.infos += other.infos


def archive_collection(scene, asset_name: str):
    """Collection exclue de la vue où l'on range (sans les supprimer) les objets sources vidés."""
    name = ARCHIVE_PREFIX + asset_name
    coll = bpy.data.collections.get(name)
    if coll is None:
        coll = bpy.data.collections.new(name)
        scene.collection.children.link(coll)
    for lc in _iter_layer_collections(bpy.context.view_layer.layer_collection):
        if lc.collection == coll:
            lc.exclude = True
    return coll


def _iter_layer_collections(lc):
    yield lc
    for c in lc.children:
        yield from _iter_layer_collections(c)


def move_to_collection(obj, coll):
    for c in list(obj.users_collection):
        c.objects.unlink(obj)
    coll.objects.link(obj)


def mapping_collection(scene, asset_name: str):
    coll = bpy.data.collections.get(asset_name)
    if coll is None:
        coll = bpy.data.collections.new(asset_name)
        scene.collection.children.link(coll)
    return coll


def find_drawable(settings):
    name = settings.name_or_error()
    if settings.mapping_root is not None and sza.is_drawable(settings.mapping_root):
        return settings.mapping_root
    obj = bpy.data.objects.get(name) if name else None
    if obj is not None and sza.is_drawable(obj):
        return obj
    return None


def find_named_collision(settings):
    """Bound Composite portant exactement le nom attendu « mio_xxxx_col », s'il existe."""
    name = settings.name_or_error()
    obj = bpy.data.objects.get(naming.collision_name(name)) if name else None
    return obj if (obj is not None and sza.is_composite(obj)) else None


def origin_far_from_geometry(drawable, margin=5.0):
    """Distance XY (m) entre l'origine du Drawable et la boîte de sa géométrie, ou 0 si l'origine est dedans."""
    box = models_world_aabb(mapping_models(drawable))
    if box is None:
        return 0.0
    o = drawable.matrix_world.translation
    dx = max(box[0][0] - margin - o.x, 0.0, o.x - box[1][0] - margin)
    dy = max(box[0][1] - margin - o.y, 0.0, o.y - box[1][1] - margin)
    return float((dx * dx + dy * dy) ** 0.5)


def mapping_models(drawable) -> list:
    return [c for c in drawable.children if sza.is_model(c)] if drawable else []


def models_world_aabb(models):
    box = None
    for m in models:
        for mesh in sza.lod_meshes(m).values():
            box = geom.merge_aabb(box, geom.aabb(geom.transform_points(geom.mesh_coords(mesh), m.matrix_world)))
    return box


def _collect(objs, res: StepResult):
    """Classe les objets sources en modèles visuels, lumières, drawables d'origine et collisions."""
    models, lights, src_drawables, collisions, to_convert = [], [], [], [], []
    seen = set()

    def visit(o):
        if o.name in seen:
            return
        seen.add(o.name)
        if o.instance_type == "COLLECTION" and o.instance_collection is not None:
            res.errors.append(f"« {o.name} » est une instance de collection : rends-la réelle "
                              "(Objet > Appliquer > Rendre les instances réelles) avant de préparer le mapping.")
            return
        bad = sza.is_unsupported_root(o)
        if bad:
            res.errors.append(f"« {o.name} » est un {bad} : non pris en charge par la fusion en mapping statique.")
            return
        if sza.is_drawable(o):
            if o.type == "ARMATURE":
                res.errors.append(f"« {o.name} » est un Drawable avec squelette : non pris en charge (un mapping "
                                  "statique ne doit pas être skinné).")
                return
            src_drawables.append(o)
            for c in o.children:
                if sza.is_model(c):
                    visit(c)
                elif sza.is_light(c):
                    lights.append(c)
                elif sza.is_drawable(c):
                    res.errors.append(f"Drawable imbriqué « {c.name} » sous « {o.name} » : hiérarchie invalide.")
                elif sza.is_bound(c):
                    res.infos.append(f"Collision intégrée d'origine trouvée sous « {o.name} » : « {c.name} ». "
                                     "Désigne-la comme objet racine collision pour la réutiliser.")
            return
        if sza.is_model(o):
            if o.type != "MESH":
                res.errors.append(f"Drawable Model « {o.name} » n'est pas un mesh.")
                return
            if o.vertex_groups and o.parent is not None and o.parent.type == "ARMATURE":
                res.errors.append(f"« {o.name} » est skinné (groupes de sommets liés à un squelette) : non pris en charge.")
                return
            if o.parent is not None and sza.is_drawable(o.parent) and o.parent not in src_drawables:
                src_drawables.append(o.parent)
            models.append(o)
            return
        if sza.is_light(o):
            lights.append(o)
            return
        if sza.is_bound(o):
            collisions.append(o)
            return
        if o.type == "MESH" and sza.sollum_type(o) == "sollumz_none":
            mats = [m for m in o.data.materials if m is not None]
            if not mats:
                res.errors.append(f"« {o.name} » n'a aucun matériau : impossible d'en faire un modèle GTA.")
            elif not all(sza.is_shader_material(m) for m in mats):
                res.errors.append(f"« {o.name} » utilise des matériaux non-Sollumz. Convertis-les avec Sollumz "
                                  "(Convertir le matériau en shader) avant de préparer le mapping.")
            else:
                to_convert.append(o)
            return
        if o.type == "EMPTY" and sza.sollum_type(o) == "sollumz_none":
            for c in o.children:
                visit(c)
            return
        res.warnings.append(f"« {o.name} » ignoré (type {o.type}/{sza.sollum_type(o)}).")

    for o in objs:
        visit(o)
    return models, lights, src_drawables, collisions, to_convert


def validate_models(models, res: StepResult):
    for m in models:
        lods = sza.lod_meshes(m)
        if not lods:
            res.errors.append(f"« {m.name} » n'a aucun mesh de LOD.")
            continue
        for level, mesh in lods.items():
            if not len(mesh.polygons):
                res.warnings.append(f"« {m.name} » LOD {sza.lod_label(level)} : mesh vide.")
            used = set()
            if len(mesh.polygons):
                idx = np.empty(len(mesh.polygons), dtype=np.int32)
                mesh.polygons.foreach_get("material_index", idx)
                used = set(np.unique(idx).tolist())
            for i in used:
                mat = mesh.materials[i] if i < len(mesh.materials) else None
                if mat is None:
                    res.errors.append(f"« {m.name} » LOD {sza.lod_label(level)} : des faces n'ont pas de matériau.")
                elif not sza.is_shader_material(mat):
                    res.errors.append(f"« {m.name} » : matériau « {mat.name} » non-Sollumz utilisé par des faces.")
            unused = [mesh.materials[i].name for i in range(len(mesh.materials))
                      if i not in used and mesh.materials[i] is not None]
            if unused:
                shown = ", ".join(unused[:4]) + (f"… (+{len(unused) - 4})" if len(unused) > 4 else "")
                res.infos.append(f"« {m.name} » LOD {sza.lod_label(level)} : {len(unused)} slot(s) de matériau plus utilisés "
                                 f"par aucune face (normal après découpe), ignorés pour les textures : {shown}.")


def prepare_mapping(context, s) -> StepResult:
    res = StepResult()
    name = s.name_or_error()
    if not name:
        res.errors.append("Indique un nom de mapping (ex. « garage » donnera « mio_garage »).")
        return res
    s.asset_name = name

    sources = []
    if s.mapping_root is not None:
        sources.append(s.mapping_root)
    for o in context.selected_objects:
        if o not in sources:
            sources.append(o)
    if s.collision_root is not None and s.collision_root in sources:
        sources.remove(s.collision_root)
    if not sources:
        res.errors.append("Aucun objet : sélectionne le bâtiment, le sol et les éléments visibles, ou choisis "
                          "l'objet racine du mapping. Les autres objets de la scène ne sont jamais pris.")
        return res

    models, lights, src_drawables, collision_objs, to_convert = _collect(sources, res)

    # Drawable cible
    target = None
    if s.mapping_root is not None and sza.is_drawable(s.mapping_root):
        target = s.mapping_root
    existing = bpy.data.objects.get(name)
    if existing is not None and existing is not target:
        if target is None and sza.is_drawable(existing):
            target = existing
        else:
            res.errors.append(f"Un objet « {name} » existe déjà et n'est pas le Drawable du mapping : renomme-le.")
    if target is not None:
        if target.type == "ARMATURE":
            res.errors.append(f"« {target.name} » a un squelette : non pris en charge.")
        if target.parent is not None:
            res.errors.append(f"Le Drawable « {target.name} » a un parent : un Drawable doit être une racine.")
        if s.origin_mode == "KEEP_ROOT" and geom.has_rotation_or_scale(target.matrix_world):
            res.errors.append(f"« {target.name} » a une rotation ou une échelle : utilise l'origine « Centre du "
                              "mapping » ou applique la rotation/échelle (le YMAP place l'entité sans échelle).")
        for m in mapping_models(target):
            if m not in models:
                models.append(m)
    validate_models(models, res)  # les meshes à convertir ont déjà été vérifiés (matériaux Sollumz) dans _collect
    if not models and not to_convert:
        res.errors.append("Aucun élément visuel (Drawable Model) trouvé dans la sélection.")
    if res.errors:
        return res

    # --- modifications (annulables par Ctrl+Z) ---
    scene = context.scene
    coll = mapping_collection(scene, name)
    created = False
    if target is None:
        target = sza.create_empty("DRAWABLE", name, coll)
        target["mio_generated"] = True
        created = True
        res.infos.append(f"Drawable « {name} » créé.")
    elif target.name != name:
        old = target.name
        target.name = name
        res.infos.append(f"Drawable « {old} » renommé en « {name} ».")
    target["mio_asset"] = name

    for o in to_convert:
        o["mio_source_asset"] = naming.strip_blender_suffix(o.name.lower())
        sza.convert_mesh_to_model(o)
        models.append(o)
        res.infos.append(f"« {o.name} » converti en Drawable Model (LOD High = mesh actuel).")

    worlds = geom.snapshot_worlds([target] + models + lights)
    moved = 0
    for m in models:
        if m.parent is not target:
            if "mio_source_asset" not in m:
                src = m.parent.name if (m.parent is not None and sza.is_drawable(m.parent)) else m.name
                m["mio_source_asset"] = naming.strip_blender_suffix(src.lower())
            geom.reparent_keep_world(m, target, worlds)
            moved += 1
    for light in lights:
        if light.parent is not target:
            geom.reparent_keep_world(light, target, worlds)
    if moved:
        res.infos.append(f"{moved} modèle(s) regroupé(s) sous « {name} » (positions mondiales conservées, aucun "
                         "mesh fusionné).")

    # Distances de LOD : on garde les plus grandes des drawables d'origine (rien ne disparaît plus tôt).
    dp = sza.lod_dist_props(target)
    others = [d for d in src_drawables if d is not target]
    for attr in ("lod_dist_high", "lod_dist_med", "lod_dist_low", "lod_dist_vlow"):
        vals = [getattr(sza.lod_dist_props(d), attr) for d in others]
        if vals:
            best = max(vals)
            setattr(dp, attr, best if created else max(getattr(dp, attr), best))

    # Origine
    if s.origin_mode == "BOUNDS_BOTTOM_CENTER":
        box = models_world_aabb(mapping_models(target))
        if box is not None:
            mn, mx = box
            new_origin = Matrix.Translation(Vector(((mn[0] + mx[0]) / 2, (mn[1] + mx[1]) / 2, mn[2])))
        else:
            new_origin = Matrix.Identity(4)
    else:
        loc = target.matrix_world.translation.copy()
        new_origin = Matrix.Translation(loc)
    rep = geom.rebase_root(target, new_origin, sza)
    if rep["rebased"]:
        res.infos.append(f"{len(rep['rebased'])} objet(s) à l'origine du monde exprimé(s) dans le repère du Drawable "
                         f"(sinon Sollumz les exporterait décalés) ; {rep['mesh_copies']} mesh partagé(s) copié(s).")
    o = target.matrix_world.translation
    res.infos.append(f"Origine de « {name} » : ({o.x:.3f}, {o.y:.3f}, {o.z:.3f}) — c'est la position de l'entité "
                     "dans le YMAP.")

    # Drawables d'origine vidés : rangés (pas supprimés) dans une collection exclue.
    arch = None
    for d in src_drawables:
        if d is target or any(sza.is_model(c) for c in d.children):
            continue
        if s.collision_root is not None and (s.collision_root == d or s.collision_root in d.children_recursive):
            continue
        arch = arch or archive_collection(scene, name)
        move_to_collection(d, arch)
        for c in d.children_recursive:
            move_to_collection(c, arch)
        res.infos.append(f"Drawable d'origine « {d.name} » vidé : rangé dans « {arch.name} » (non exporté).")

    if target.name not in coll.objects:
        move_to_collection(target, coll)
    s.mapping_root = target

    # Collisions désignées ou sélectionnées
    from . import collision
    col_sources = [s.collision_root] if s.collision_root is not None else collision_objs
    if not col_sources:
        named = find_named_collision(s)
        if named is not None:
            col_sources = [named]
            res.infos.append(f"Collision « {named.name} » trouvée par son nom exact et utilisée (le champ « Objet racine "
                             "collision » est maintenant rempli).")
    if col_sources:
        res.extend(collision.prepare_collision_root(context, s, col_sources, target))
    else:
        res.warnings.append("Aucune collision désignée : choisis l'objet racine collision (collision importée et "
                            "découpée) ou utilise « Créer les collisions depuis le mapping ».")
    return res
