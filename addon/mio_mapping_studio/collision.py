"""Collisions : racine Bound Composite « mio_xxxx_col », génération depuis le visuel, validation, intégration.

Structure Sollumz 2.9 (tools/boundhelper.py::convert_obj_to_bvh) :
    Bound Composite (empty) -> Bound Geometry BVH (empty, porte les flags) -> Bound Poly Mesh (mesh, matériaux de
    collision). L'exporteur YDR n'intègre qu'UN Bound racine enfant direct du Drawable (ydrexport.py) : d'où un
    Bound Composite unique.
Limites réelles :
    - 32767 sommets par géométrie de collision (ybn/ybnexport.py::MAX_VERTICES) ;
    - 65535 polygones max par géométrie : indices d'arêtes 16 bits (CodeWalker BoundPolygonTriangle, 0xFFFF = aucune).
"""

from __future__ import annotations

import bmesh
import bpy
import numpy as np
from mathutils import Matrix

from . import geom, naming
from . import sollumz_adapter as sza
from .hierarchy import StepResult, archive_collection, mapping_collection, mapping_models, move_to_collection

MAX_POLYGONS = 65534

USAGE_PRESETS = {
    # usage: (preset de flags Sollumz, matériau de collision GTA, flags matériau)
    "GENERAL": ("General (Default)", "CONCRETE", {}),
    "ROAD": ("General (Default)", "TARMAC", {}),
    "TERRAIN": ("General (Default)", "DIRT_TRACK", {}),
    "STAIRS": ("Stair mesh", "CONCRETE", {"stairs": True}),
}

# Shaders dont les faces ne doivent pas devenir de la collision (décals, câbles, herbe, feuillages, eau...).
EXCLUDED_SHADER_PREFIXES = ("decal", "cable", "grass", "trees", "water", "ptfx", "cloth", "mirror")


def is_excluded_shader(filename: str) -> bool:
    f = (filename or "").lower()
    return f.startswith(EXCLUDED_SHADER_PREFIXES) or "_decal" in f


# ----------------------------------------------------------------------------------------------------------------
# Validation
# ----------------------------------------------------------------------------------------------------------------

def bound_vertex_count(obj) -> int:
    if obj.type == "MESH":
        return len(obj.data.vertices)
    return sum(len(c.data.vertices) for c in obj.children_recursive if c.type == "MESH" and sza.is_bound(c))


def bound_polygon_count(obj) -> int:
    def tris(mesh):
        return sum(len(p.vertices) - 2 for p in mesh.polygons)
    if obj.type == "MESH":
        return tris(obj.data)
    return sum(tris(c.data) for c in obj.children_recursive if c.type == "MESH" and sza.is_bound(c))


def validate_collision_root(root, res: StepResult | None = None) -> StepResult:
    res = res or StepResult()
    if root is None:
        res.errors.append("Aucune collision.")
        return res
    if not sza.is_composite(root):
        res.errors.append(f"« {root.name} » n'est pas un Bound Composite : la racine collision doit en être un.")
        return res
    children = list(root.children)
    if not children:
        res.errors.append(f"Le Bound Composite « {root.name} » est vide.")
        return res
    maxv = sza.bvh_max_vertices()
    total_tris = 0
    for c in children:
        if sza.is_composite(c):
            res.errors.append(f"Bound Composite imbriqué « {c.name} » : non pris en charge par l'export.")
            continue
        if not sza.is_bound_root_child(c):
            res.errors.append(f"« {c.name} » (sous {root.name}) n'est pas un objet de collision Sollumz.")
            continue
        if sza.bound_flags_empty(c):
            res.warnings.append(f"« {c.name} » n'a aucun flag de collision : il ne bloquera rien en jeu "
                                "(utilise « Appliquer le preset d'usage »).")
        if sza.is_bvh(c):
            polys = [p for p in c.children_recursive if sza.is_bound(p)]
            if not polys:
                res.errors.append(f"BVH « {c.name} » sans Poly Mesh.")
                continue
            for p in polys:
                if p.type == "MESH":
                    _check_collision_materials(p, res)
        elif c.type == "MESH":
            _check_collision_materials(c, res)
        nv = bound_vertex_count(c)
        npoly = bound_polygon_count(c)
        total_tris += npoly
        if nv > maxv:
            res.errors.append(f"« {c.name} » : {nv} sommets > limite de l'exporteur ({maxv}). Fractionne cette "
                              "géométrie (Créer les collisions fractionne automatiquement).")
        if npoly > MAX_POLYGONS:
            res.errors.append(f"« {c.name} » : {npoly} triangles > {MAX_POLYGONS} (indices 16 bits).")
    if total_tris > 30000:
        res.warnings.append(f"Collision détaillée ({total_tris} triangles) : une simplification manuelle est "
                            "recommandée pour les performances.")
    return res


def _check_collision_materials(obj, res: StepResult):
    mats = [m for m in obj.data.materials]
    if not mats or any(m is None for m in mats):
        res.errors.append(f"« {obj.name} » : slot de matériau vide ; un matériau de collision est requis.")
        return
    bad = [m.name for m in mats if not sza.is_collision_material(m)]
    if bad:
        res.errors.append(f"« {obj.name} » utilise des matériaux visuels ({', '.join(bad)}) : seuls les matériaux de "
                          "collision sont exportables.")


# ----------------------------------------------------------------------------------------------------------------
# Racine collision à partir des collisions importées/modifiées
# ----------------------------------------------------------------------------------------------------------------

def _resolve_sources(objs, res: StepResult):
    composites, loose = [], []
    seen = set()

    def visit(o):
        if o is None or o.name in seen:
            return
        seen.add(o.name)
        if sza.is_composite(o):
            composites.append(o)
        elif sza.is_drawable(o):
            comps = [c for c in o.children if sza.is_composite(c)]
            if len(comps) == 1:
                composites.append(comps[0])
                res.infos.append(f"Collision intégrée « {comps[0].name} » du Drawable « {o.name} » utilisée.")
            elif not comps:
                res.errors.append(f"« {o.name} » est un Drawable : la racine collision doit être un Bound Composite, "
                                  "pas un Drawable renommé.")
            else:
                res.errors.append(f"« {o.name} » contient plusieurs Bound Composites : désigne celui à utiliser.")
        elif sza.is_bound_root_child(o):
            if o.parent is not None and sza.is_composite(o.parent) and o.parent in objs:
                return
            loose.append(o)
        elif sza.is_bound(o):  # Poly Mesh / primitive poly : on remonte à son BVH
            p = o.parent
            if p is not None and sza.is_bvh(p):
                visit(p)
            else:
                res.errors.append(f"« {o.name} » (poly de collision) n'a pas de BVH parent.")
        elif o.type == "EMPTY" and sza.sollum_type(o) == "sollumz_none":
            for c in o.children:
                visit(c)
        elif o.type == "MESH":
            res.errors.append(f"« {o.name} » est un mesh sans type collision Sollumz : utilise « Créer les "
                              "collisions depuis le mapping » ou convertis-le avec Sollumz.")
        else:
            res.warnings.append(f"« {o.name} » ignoré pour la collision.")

    for o in objs:
        visit(o)
    return composites, loose


def prepare_collision_root(context, s, objs, drawable) -> StepResult:
    res = StepResult()
    name = s.name_or_error()
    colname = naming.collision_name(name)
    composites, loose = _resolve_sources(objs, res)
    if not composites and not loose:
        if not res.errors:
            res.errors.append("Aucune collision exploitable dans les objets désignés.")
        return res
    existing = bpy.data.objects.get(colname)
    if existing is not None and existing not in composites and not sza.is_composite(existing):
        res.errors.append(f"Un objet « {colname} » existe déjà et n'est pas un Bound Composite.")
    if res.errors:
        return res

    scene = context.scene
    coll = mapping_collection(scene, name)
    if len(composites) == 1 and not loose:
        root = composites[0]
    else:
        root = existing if (existing is not None and sza.is_composite(existing)) else None
        if root is None:
            root = sza.create_empty("BOUND_COMPOSITE", colname, coll)
            root.matrix_world = drawable.matrix_world.copy()
        worlds = {}
        for comp in composites:
            if comp is root:
                continue
            for c in list(comp.children):
                worlds[c.name] = c.matrix_world.copy()
                geom.reparent_keep_world(c, root, worlds)
            arch = archive_collection(scene, name)
            move_to_collection(comp, arch)
            res.infos.append(f"Bound Composite « {comp.name} » fusionné dans « {colname} » (l'original vide est rangé "
                             f"dans {arch.name}).")
        for c in loose:
            worlds[c.name] = c.matrix_world.copy()
            geom.reparent_keep_world(c, root, worlds)
        bpy.context.view_layer.update()

    if root.parent is not None and root.parent is not drawable:
        w = root.matrix_world.copy()
        root.parent = None
        root.matrix_world = w
        res.infos.append(f"« {root.name} » détaché de son Drawable d'origine (position mondiale conservée).")
    if root.name != colname:
        old = root.name
        if existing is not None and existing is not root:
            arch = archive_collection(scene, name)
            existing.name = colname + ".old"
            move_to_collection(existing, arch)
        root.name = colname
        res.infos.append(f"Racine collision « {old} » renommée « {colname} ».")
    root["mio_role"] = "collision"
    root["mio_asset"] = name
    if root.name not in coll.objects and root.parent is None:
        move_to_collection(root, coll)

    rep = geom.rebase_root(root, drawable.matrix_world.copy(), sza)
    if rep["rebased"]:
        res.infos.append(f"{len(rep['rebased'])} objet(s) de collision exprimé(s) dans le repère du mapping (géométrie "
                         "inchangée dans le monde).")
    s.collision_root = root
    validate_collision_root(root, res)
    res.infos.append(f"Collision « {colname} » prête ({len(root.children)} élément(s)).")
    return res


# ----------------------------------------------------------------------------------------------------------------
# Génération depuis le visuel
# ----------------------------------------------------------------------------------------------------------------

def get_usage_material(usage: str):
    preset, mat_name, mat_flags = USAGE_PRESETS[usage]
    for m in bpy.data.materials:
        if m.get("mio_usage") == usage and sza.is_collision_material(m):
            return m
    idx = sza.collision_material_index(mat_name)
    if idx is None:
        idx = 0
    mat = sza.create_collision_material(idx)
    mat.name = f"mio_col_{mat_name.lower()}"
    mat["mio_usage"] = usage
    for k, v in mat_flags.items():
        setattr(mat.collision_flags, k, v)
    return mat


def _pick_lod_mesh(model):
    lods = sza.lod_meshes(model)
    L = sza.get().LODLevel
    for level in (L.HIGH, L.VERYHIGH, L.MEDIUM, L.LOW, L.VERYLOW):
        if level in lods:
            return level, lods[level]
    return None, None


def _copy_geometry(model, mesh, to_local: Matrix, skip_excluded: bool):
    """Copie indépendante de la géométrie (sommets dans le repère de la collision), sans matériaux visuels."""
    bm = bmesh.new()
    bm.from_mesh(mesh)
    bm.transform(to_local @ model.matrix_world)
    removed = 0
    if skip_excluded:
        bad_idx = {i for i, m in enumerate(mesh.materials)
                   if m is not None and sza.is_shader_material(m) and is_excluded_shader(sza.shader_filename(m))}
        if bad_idx:
            faces = [f for f in bm.faces if f.material_index in bad_idx]
            removed = len(faces)
            bmesh.ops.delete(bm, geom=faces, context="FACES_ONLY")
    loose_verts = [v for v in bm.verts if not v.link_faces]
    if loose_verts:
        bmesh.ops.delete(bm, geom=loose_verts, context="VERTS")
    loose_edges = [e for e in bm.edges if not e.link_faces]
    if loose_edges:
        bmesh.ops.delete(bm, geom=loose_edges, context="EDGES")
    for f in bm.faces:
        f.material_index = 0
    new = bpy.data.meshes.new(f"{naming.strip_blender_suffix(model.name)}.col")
    bm.to_mesh(new)
    bm.free()
    # aucune donnée visuelle sur la copie
    for uv in list(new.uv_layers):
        new.uv_layers.remove(uv)
    for ca in list(new.color_attributes):
        new.color_attributes.remove(ca)
    return new, removed


def _decimate(mesh, ratio: float):
    tmp = bpy.data.objects.new("mio_tmp_decimate", mesh)
    bpy.context.scene.collection.objects.link(tmp)
    mod = tmp.modifiers.new("decimate", "DECIMATE")
    mod.ratio = ratio
    dg = bpy.context.evaluated_depsgraph_get()
    ev = tmp.evaluated_get(dg)
    out = bpy.data.meshes.new_from_object(ev)
    bpy.data.objects.remove(tmp)
    out.name = mesh.name
    bpy.data.meshes.remove(mesh)
    return out


def split_mesh(mesh, max_verts: int, max_polys: int) -> list:
    """Fractionne spatialement (axe le plus long, médiane des centres de faces) jusqu'aux limites réelles."""
    nv, npoly = len(mesh.vertices), sum(len(p.vertices) - 2 for p in mesh.polygons)
    if nv <= max_verts and npoly <= max_polys:
        return [mesh]
    co = geom.mesh_coords(mesh)
    faces = [list(p.vertices) for p in mesh.polygons]
    centers = np.array([co[f].mean(axis=0) for f in faces])

    def build(face_ids, label):
        used = sorted({v for i in face_ids for v in faces[i]})
        remap = {v: j for j, v in enumerate(used)}
        m = bpy.data.meshes.new(label)
        m.from_pydata(co[used].tolist(), [], [[remap[v] for v in faces[i]] for i in face_ids])
        m.update()
        return m

    out = []
    stack = [(list(range(len(faces))), mesh.name)]
    while stack:
        ids, label = stack.pop()
        sub_verts = len({v for i in ids for v in faces[i]})
        sub_polys = sum(len(faces[i]) - 2 for i in ids)
        if (sub_verts <= max_verts and sub_polys <= max_polys) or len(ids) <= 1:
            out.append(build(ids, label))
            continue
        c = centers[ids]
        axis = int(np.argmax(c.max(axis=0) - c.min(axis=0)))
        order = np.argsort(c[:, axis], kind="stable")
        half = len(ids) // 2
        a = [ids[i] for i in order[:half]]
        b = [ids[i] for i in order[half:]]
        stack.append((b, label + "_b"))
        stack.append((a, label + "_a"))
    for i, m in enumerate(out):
        m.name = f"{naming.strip_blender_suffix(mesh.name)}.{i:02d}"
    bpy.data.meshes.remove(mesh)
    return out


def _delete_hierarchy(root):
    meshes = set()
    for o in [root] + list(root.children_recursive):
        if o.type == "MESH":
            meshes.add(o.data)
    for o in reversed([root] + list(root.children_recursive)):
        bpy.data.objects.remove(o, do_unlink=True)
    for m in meshes:
        if m.users == 0:
            bpy.data.meshes.remove(m)


def create_collision_from_mapping(context, s, drawable, replace: bool) -> StepResult:
    res = StepResult()
    name = s.name_or_error()
    colname = naming.collision_name(name)
    models = [m for m in mapping_models(drawable) if not m.hide_viewport]
    if not models:
        res.errors.append("Le Drawable du mapping n'a aucun modèle visible : lance d'abord « Préparer le mapping ».")
        return res
    existing = s.collision_root if s.collision_root is not None else bpy.data.objects.get(colname)
    if existing is not None and not replace:
        res.errors.append(f"Une collision existe déjà (« {existing.name} »). Elle n'est pas remplacée sans action "
                          "explicite : coche « Remplacer la collision existante » pour la régénérer.")
        return res

    scene = context.scene
    coll = mapping_collection(scene, name)
    if existing is not None:
        if existing.get("mio_generated"):
            _delete_hierarchy(existing)
            res.infos.append("Ancienne collision générée supprimée (régénération).")
        else:
            arch = archive_collection(scene, name)
            if existing.parent is not None:
                w = existing.matrix_world.copy()
                existing.parent = None
                existing.matrix_world = w
            existing.name = existing.name + ".remplacee"
            move_to_collection(existing, arch)
            for c in existing.children_recursive:
                move_to_collection(c, arch)
            res.infos.append(f"Collision désignée rangée (non supprimée) dans « {arch.name} ».")
        s.collision_root = None

    preset, mat_name, _ = USAGE_PRESETS[s.collision_usage]
    col_mat = get_usage_material(s.collision_usage)
    root = sza.create_empty("BOUND_COMPOSITE", colname, coll)
    root.matrix_world = drawable.matrix_world.copy()
    root["mio_generated"] = True
    root["mio_role"] = "collision"
    root["mio_asset"] = name
    to_local = drawable.matrix_world.inverted()

    maxv = sza.bvh_max_vertices()
    pieces = []
    removed_faces = 0
    lod_note = set()
    for m in models:
        level, mesh = _pick_lod_mesh(m)
        if mesh is None:
            continue
        lod_note.add(sza.lod_label(level))
        new, removed = _copy_geometry(m, mesh, to_local, s.collision_skip_decals)
        removed_faces += removed
        if not len(new.polygons):
            bpy.data.meshes.remove(new)
            continue
        if s.collision_decimate:
            new = _decimate(new, s.collision_decimate_ratio)
        new.materials.append(col_mat)
        pieces.extend(split_mesh(new, maxv, MAX_POLYGONS))
    for p in pieces:
        if not len(p.materials):
            p.materials.append(col_mat)
    if not pieces:
        bpy.data.objects.remove(root)
        res.errors.append("Aucune géométrie exploitable pour la collision.")
        return res

    # Regroupement en BVH sans dépasser les limites.
    groups, cur, cv, cp = [], [], 0, 0
    for p in pieces:
        nv = len(p.vertices)
        npoly = sum(len(f.vertices) - 2 for f in p.polygons)
        if cur and (cv + nv > maxv or cp + npoly > MAX_POLYGONS):
            groups.append(cur)
            cur, cv, cp = [], 0, 0
        cur.append(p)
        cv += nv
        cp += npoly
    if cur:
        groups.append(cur)

    total_tris = 0
    for gi, group in enumerate(groups):
        bvh = sza.create_empty("BOUND_GEOMETRYBVH", f"{colname}.bvh.{gi:02d}", coll)
        bvh.parent = root
        bvh.matrix_parent_inverse = Matrix.Identity(4)
        bvh.matrix_basis = Matrix.Identity(4)
        bvh["mio_generated"] = True
        if not sza.apply_flag_preset(bvh, preset):
            res.warnings.append(f"Preset de flags « {preset} » introuvable dans Sollumz.")
        for mesh in group:
            obj = sza.create_poly_mesh_object(f"{mesh.name}.poly_mesh", mesh, coll)
            obj.parent = bvh
            obj.matrix_parent_inverse = Matrix.Identity(4)
            obj.matrix_basis = Matrix.Identity(4)
            obj["mio_generated"] = True
            total_tris += sum(len(f.vertices) - 2 for f in mesh.polygons)
    bpy.context.view_layer.update()
    s.collision_root = root

    res.infos.append(f"Collision « {colname} » créée : {len(groups)} BVH, {len(pieces)} Poly Mesh, {total_tris} "
                     f"triangles, depuis le LOD {', '.join(sorted(lod_note))} seulement (pas de doublon entre LOD).")
    res.infos.append(f"Usage « {s.collision_usage} » : flags « {preset} », matériau {mat_name} "
                     f"(« {col_mat.name} », modifiable dans l'onglet matériau de Sollumz).")
    if removed_faces:
        res.infos.append(f"{removed_faces} face(s) de décals/feuillages/eau/câbles exclues de la collision.")
    if len(groups) > 1:
        res.infos.append(f"Géométrie fractionnée en {len(groups)} BVH (limite exporteur : {maxv} sommets, "
                         f"{MAX_POLYGONS} triangles).")
    if not s.collision_decimate:
        res.warnings.append("Copie fidèle du visuel, non simplifiée : vérifie-la et simplifie-la manuellement si elle "
                            "est trop détaillée (escaliers, détails fins, faces invisibles).")
    validate_collision_root(root, res)
    return res


def apply_usage_preset(context, s) -> StepResult:
    res = StepResult()
    root = s.collision_root
    if root is None or not sza.is_composite(root):
        res.errors.append("Aucune racine collision Bound Composite.")
        return res
    preset, mat_name, _ = USAGE_PRESETS[s.collision_usage]
    n = 0
    for c in root.children:
        if sza.is_bound_root_child(c) and sza.apply_flag_preset(c, preset):
            n += 1
    res.infos.append(f"Preset « {preset} » appliqué à {n} élément(s) de « {root.name} ».")
    return res


# ----------------------------------------------------------------------------------------------------------------
# Étape 5 : intégration
# ----------------------------------------------------------------------------------------------------------------

def integrate(context, s, drawable) -> StepResult:
    res = StepResult()
    root = s.collision_root
    if drawable is None:
        res.errors.append("Drawable du mapping introuvable : lance « Préparer le mapping ».")
        return res
    validate_collision_root(root, res)
    if res.errors:
        return res
    name = s.name_or_error()
    scene = context.scene
    if s.export_mode == "STATIC_EMBEDDED":
        others = [c for c in drawable.children if sza.is_bound(c) and c is not root]
        if others:
            arch = archive_collection(scene, name)
            for o in others:
                w = o.matrix_world.copy()
                o.parent = None
                o.matrix_world = w
                move_to_collection(o, arch)
                for c in o.children_recursive:
                    move_to_collection(c, arch)
                res.infos.append(f"Ancienne collision intégrée « {o.name} » retirée du Drawable (rangée dans "
                                 f"{arch.name}) : une seule collision est exportée par Sollumz.")
        if root.parent is not drawable:
            worlds = {}
            geom.reparent_keep_world(root, drawable, worlds)
        rep = geom.rebase_root(root, drawable.matrix_world.copy(), sza)
        bpy.context.view_layer.update()
        res.infos.append(f"« {root.name} » intégré au Drawable « {drawable.name} » (Bound Composite enfant direct : "
                         "collision embedded du YDR). Les meshes visuels et de collision restent séparés.")
        if rep["rebased"]:
            res.infos.append(f"{len(rep['rebased'])} objet(s) de collision ré-exprimé(s) dans le repère du Drawable.")
        dup = [o for o in bpy.data.objects if sza.is_composite(o) and o is not root and o.name.startswith(root.name)
               and o.name in context.view_layer.objects]
        if dup:
            res.warnings.append("Autre(s) collision(s) au nom proche encore actives : " + ", ".join(o.name for o in dup)
                                + ". Elles ne sont pas exportées mais peuvent prêter à confusion.")
    else:
        if root.parent is not None:
            w = root.matrix_world.copy()
            root.parent = None
            root.matrix_world = w
            res.infos.append(f"« {root.name} » détaché du Drawable : en mode MLO la collision est le fichier "
                             f"{root.name}.ybn référencé par l'archetype MLO.")
        embedded = [c for c in drawable.children if sza.is_bound(c)]
        if embedded:
            res.errors.append("Le Drawable contient encore une collision intégrée : en mode MLO elle doublerait la "
                              "collision YBN. Retire-la ou repasse en mode statique.")
        coll = mapping_collection(scene, name)
        if root.name not in coll.objects:
            move_to_collection(root, coll)
        rep = geom.rebase_root(root, drawable.matrix_world.copy(), sza)
        res.infos.append(f"Origine de « {root.name} » alignée sur celle de « {drawable.name} » : repère local du MLO = "
                         "position du Drawable.")
    return res
