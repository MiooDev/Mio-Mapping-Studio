"""Étapes 3 et 4 : YTYP, archetype Base et (mode MLO uniquement) archetype MLO + room limbo.

Valeurs Sollumz utilisées (Sollumz 2.9.0) :
  - archetype Base : type ArchetypeType.BASE, asset_type AssetType.DRAWABLE, flags 32 (« Static », flag6) ;
  - Physics Dictionary = nom du YDR uniquement si la collision est intégrée au Drawable (même règle que
    Sollumz ArchetypeProperties.update_asset et CodeWalker NewArchetypesFromYdrs) ;
  - archetype MLO : asset = Bound Composite (exigence de Sollumz « MLO asset must be a Bound Composite »),
    asset_type ASSETLESS ; sa collision est le fichier <nom MLO>.ybn (CodeWalker charge la collision d'un
    intérieur par le nom de l'archetype MLO) ;
  - room « limbo » : bounds dans le repère local du MLO (= repère du Bound Composite), entité attachée à la room.
"""

from __future__ import annotations

import numpy as np
from mathutils import Vector

from . import geom, naming
from . import sollumz_adapter as sza
from .hierarchy import StepResult, find_drawable, mapping_models

STATIC_FLAG = 32          # ArchetypeFlags.flag6 « Static »
ENTITY_STATIC_FLAG = 32   # EntityFlags.flag6 « Static entity »
ENTITY_DISABLE_EMBEDDED_COLLISION = 4  # EntityFlags.flag3 : ne doit jamais être posé en mode collision intégrée


def drawable_space_bounds(drawable, include_collision=True):
    """AABB (repère du Drawable) de la géométrie exportée : tous les LOD des modèles + collision intégrée."""
    inv = drawable.matrix_world.inverted()
    box = None
    for m in mapping_models(drawable):
        for mesh in sza.lod_meshes(m).values():
            pts = geom.transform_points(geom.mesh_coords(mesh), inv @ m.matrix_world)
            box = geom.merge_aabb(box, geom.aabb(pts))
    if include_collision:
        for c in drawable.children:
            if sza.is_bound(c):
                box = geom.merge_aabb(box, collision_bounds(c, inv))
    return box


def collision_bounds(root, to_space):
    box = None
    for o in [root] + list(root.children_recursive):
        if o.type == "MESH" and sza.is_bound(o):
            pts = geom.transform_points(geom.mesh_coords(o.data), to_space @ o.matrix_world)
            box = geom.merge_aabb(box, geom.aabb(pts))
    return box


def sphere_from_box(box):
    mn, mx = (np.asarray(box[0]), np.asarray(box[1]))
    c = (mn + mx) / 2
    return c, float(np.linalg.norm(mx - c))


def has_embedded_collision(drawable) -> bool:
    return any(sza.is_composite(c) for c in drawable.children)


def update_base_archetype(context, s, exported_bounds=None) -> StepResult:
    """Crée ou met à jour (sans doublon) mio_xxxx.ytyp / archetype Base mio_xxxx."""
    res = StepResult()
    name = s.name_or_error()
    drawable = find_drawable(s)
    if not name or drawable is None:
        res.errors.append("Prépare d'abord le mapping (Drawable mio_xxxx introuvable).")
        return res
    scene = context.scene
    yidx, ytyp = sza.ensure_ytyp(scene, name)

    # Doublons éventuels du même archetype : on garde le premier.
    seen = False
    for i in reversed(range(len(ytyp.archetypes))):
        a = ytyp.archetypes[i]
        if a.name.lower() == name and sza.archetype_kind(a) == "BASE":
            if seen:
                sza.remove_archetype(ytyp, i)
                res.infos.append("Archetype en double supprimé.")
            seen = True
    _, arch = sza.find_archetype(ytyp, name)
    if arch is not None and sza.archetype_kind(arch) != "BASE":
        res.errors.append(f"Un archetype « {name} » existe mais n'est pas de type Base : renomme-le ou supprime-le.")
        return res
    if arch is None:
        arch = sza.new_archetype(ytyp, "BASE")
        res.infos.append(f"Archetype Base « {name} » créé dans {name}.ytyp.")
    else:
        res.infos.append(f"Archetype Base « {name} » mis à jour (pas de doublon).")

    arch.asset = None  # les bounds sont fournis explicitement (géométrie exportée), pas recalculés par Sollumz
    arch.name = name
    arch.asset_name = name
    arch.asset_type = sza.asset_type_value("DRAWABLE")
    arch.drawable_dictionary = ""
    arch.clip_dictionary = ""
    arch.special_attribute = "NOTHING_SPECIAL"
    arch.lod_dist = s.lod_dist
    arch.hd_texture_dist = s.hd_texture_dist
    sza.set_flags_total(arch.flags, STATIC_FLAG)

    has_ytd = bool(s.ytd_work_path) and any(r.status == "FOUND" for r in s.texture_refs)
    arch.texture_dictionary = name if has_ytd else ""
    if not has_ytd:
        res.warnings.append("Pas encore de YTD : Texture Dictionary laissé vide (lance l'étape 2).")

    if s.export_mode == "STATIC_EMBEDDED":
        if has_embedded_collision(drawable):
            arch.physics_dictionary = name
            res.infos.append(f"Physics Dictionary = {name} (collision intégrée au YDR ; revérifié à l'export).")
        else:
            arch.physics_dictionary = ""
            res.warnings.append("Collision pas encore intégrée : Physics Dictionary vide pour l'instant (étape 5).")
        for i, a in enumerate(ytyp.archetypes):
            if sza.archetype_kind(a) == "MLO":
                res.errors.append(f"Le YTYP contient l'archetype MLO « {a.name} » : en mode statique il référencerait "
                                  f"{a.name}.ybn qui ne sera pas exporté. Utilise « Retirer l'archetype MLO ».")
    else:
        arch.physics_dictionary = ""
        res.infos.append("Mode MLO : Physics Dictionary vide (la collision est le YBN de l'archetype MLO).")

    box = exported_bounds or drawable_space_bounds(drawable, include_collision=(s.export_mode == "STATIC_EMBEDDED"))
    if box is None:
        res.errors.append("Géométrie vide : bounds impossibles à calculer.")
        return res
    c, r = sphere_from_box(box)
    arch.bb_min = tuple(float(v) for v in box[0])
    arch.bb_max = tuple(float(v) for v in box[1])
    arch.bs_center = tuple(float(v) for v in c)
    arch.bs_radius = r
    res.infos.append(f"BBMin {tuple(round(float(v), 3) for v in box[0])}, BBMax {tuple(round(float(v), 3) for v in box[1])}, "
                     f"rayon {r:.2f} m ({'géométrie exportée relue' if exported_bounds else 'calcul Blender, repère du Drawable'}).")
    return res


def remove_incoherent_mlo(context, s) -> StepResult:
    res = StepResult()
    name = s.name_or_error()
    _, ytyp = sza.find_ytyp(context.scene, name)
    if ytyp is None:
        return res
    for i in reversed(range(len(ytyp.archetypes))):
        a = ytyp.archetypes[i]
        if sza.archetype_kind(a) == "MLO":
            n = a.name
            sza.remove_archetype(ytyp, i)
            res.infos.append(f"Archetype MLO « {n} » retiré du YTYP (mode statique).")
    return res


def configure_mlo(context, s) -> StepResult:
    res = StepResult()
    if s.export_mode != "MLO_LIMBO":
        res.errors.append("Le MLO limbo n'est utilisé qu'en mode « MLO limbo + collision YBN ».")
        return res
    name = s.name_or_error()
    colname = naming.collision_name(name)
    drawable = find_drawable(s)
    col = s.collision_root
    if drawable is None:
        res.errors.append("Prépare d'abord le mapping.")
        return res
    if col is None or not sza.is_composite(col):
        res.errors.append("Le MLO a besoin d'une vraie ressource collision : un Bound Composite « "
                          f"{colname} » (exporté en {colname}.ybn). Prépare ou crée la collision.")
        return res
    if col.name != colname:
        res.errors.append(f"La collision doit s'appeler « {colname} » (actuellement « {col.name} »).")
        return res
    if col.parent is not None:
        res.errors.append("En mode MLO la collision doit être séparée du Drawable : lance l'étape 5.")
        return res

    base = update_base_archetype(context, s)
    res.extend(base)
    if base.errors:
        return res
    scene = context.scene
    yidx, ytyp = sza.ensure_ytyp(scene, name)
    _, mlo = sza.find_archetype(ytyp, colname)
    if mlo is not None and sza.archetype_kind(mlo) != "MLO":
        res.errors.append(f"« {colname} » existe dans le YTYP mais n'est pas un archetype MLO.")
        return res
    if mlo is None:
        mlo = sza.new_archetype(ytyp, "MLO")
        res.infos.append(f"Archetype MLO « {colname} » créé.")
    mlo.asset = col                 # Sollumz : asset_name = nom du composite, asset_type ASSETLESS
    mlo.name = colname
    mlo.asset_name = colname
    mlo.asset_type = sza.asset_type_value("ASSETLESS")
    mlo.texture_dictionary = ""
    mlo.physics_dictionary = ""
    mlo.drawable_dictionary = ""

    # Room limbo : bounds dans le repère local du MLO (celui du Bound Composite).
    to_mlo = col.matrix_world.inverted()
    box = None
    for m in mapping_models(drawable):
        for mesh in sza.lod_meshes(m).values():
            box = geom.merge_aabb(box, geom.aabb(geom.transform_points(geom.mesh_coords(mesh), to_mlo @ m.matrix_world)))
    box = geom.merge_aabb(box, collision_bounds(col, to_mlo))
    if box is None:
        res.errors.append("Géométrie vide : bounds de la room impossibles à calculer.")
        return res
    mn = np.array(box[0], dtype=float)
    mx = np.array(box[1], dtype=float)
    mxy, mz = float(s.limbo_margin_xy), float(s.limbo_margin_z)
    mn[0] -= mxy
    mn[1] -= mxy
    mx[0] += mxy
    mx[1] += mxy
    mn[2] -= mz
    mx[2] += mz

    limbo = None
    for r in mlo.rooms:
        if r.name == "limbo":
            limbo = r
            break
    if limbo is None:
        limbo = mlo.new_room()
        limbo.name = "limbo"
        res.infos.append("Room « limbo » créée.")
    limbo.timecycle = ""
    limbo.bb_min = tuple(mn.tolist())
    limbo.bb_max = tuple(mx.tolist())
    others = [r.name for r in mlo.rooms if r.name != "limbo"]
    if others:
        res.warnings.append(f"Autres rooms présentes ({', '.join(others)}) : la room limbo seule n'automatise pas la "
                            "conception des rooms et portals d'un vrai intérieur.")
    if len(mlo.portals):
        res.warnings.append(f"{len(mlo.portals)} portal(s) existant(s) conservé(s) : aucun portal n'est créé pour un "
                            "espace extérieur.")

    # Entité mio_xxxx dans la room limbo
    ent = None
    for e in mlo.entities:
        if e.archetype_name.lower() == name or e.linked_object == drawable:
            ent = e
            break
    if ent is None:
        ent = mlo.new_entity()
        res.infos.append(f"Entité « {name} » ajoutée au MLO.")
    ent.archetype_name = name
    ent.linked_object = drawable
    sza.set_flags_total(ent.flags, ENTITY_STATIC_FLAG)
    ent.lod_dist = s.lod_dist
    ent.attached_room_id = str(limbo.id)
    n_in_limbo = sum(1 for e in mlo.entities if e.attached_room_id == str(limbo.id))
    if ent.attached_room_id != str(limbo.id):
        res.errors.append("Impossible d'attacher l'entité à la room limbo (Sollumz a refusé l'affectation).")
    if n_in_limbo > sza.max_limbo_entities():
        res.errors.append(f"{n_in_limbo} entités dans limbo : Sollumz/GTA en acceptent {sza.max_limbo_entities()} max.")
    off = drawable.matrix_world.translation - col.matrix_world.translation
    res.infos.append(f"Room limbo : min {tuple(round(v, 3) for v in mn)}, max {tuple(round(v, 3) for v in mx)} "
                     f"(marge XY ±{mxy:.2f} m, marge Z ±{mz:.2f} m) ; entité à ({off.x:.3f}, {off.y:.3f}, {off.z:.3f}) "
                     "dans le repère du MLO.")
    return res
