"""Outils géométriques : sommets en repère monde, AABB, re-parentage sans déplacement, « rebase » d'origine.

Règle clé (exporteur Sollumz 2.9.0, sollumz_helper.get_parent_inverse) : si un objet a une matrice monde
IDENTITÉ, l'exporteur n'applique PAS l'inverse de la transformation du Drawable/Bound parent. Un terrain ou un YBN
importé à l'origine du monde et placé sous un Drawable recentré serait donc exporté décalé.
`rebase_root()` corrige ce cas sans déplacer la géométrie dans le monde : les sommets sont exprimés dans le repère
de la racine (copie du mesh si celui-ci est partagé) et l'objet prend la matrice monde de la racine.
"""

from __future__ import annotations

import numpy as np
import bpy
from mathutils import Matrix, Vector

IDENTITY_EPS = 1e-6


def is_identity(m: Matrix) -> bool:
    ident = Matrix.Identity(4)
    return all(abs(m[i][j] - ident[i][j]) <= IDENTITY_EPS for i in range(4) for j in range(4))


def has_rotation_or_scale(m: Matrix) -> bool:
    loc, rot, sca = m.decompose()
    return (rot.angle > 1e-5) or any(abs(s - 1.0) > 1e-5 for s in sca)


def mesh_coords(mesh) -> np.ndarray:
    n = len(mesh.vertices)
    co = np.empty(n * 3, dtype=np.float64)
    if n:
        mesh.vertices.foreach_get("co", co)
    return co.reshape(n, 3)


def transform_points(points: np.ndarray, m: Matrix) -> np.ndarray:
    if not len(points):
        return points
    mat = np.array(m, dtype=np.float64)
    return points @ mat[:3, :3].T + mat[:3, 3]


def aabb(points: np.ndarray):
    if not len(points):
        return None
    return points.min(axis=0), points.max(axis=0)


def merge_aabb(a, b):
    if a is None:
        return b
    if b is None:
        return a
    return np.minimum(a[0], b[0]), np.maximum(a[1], b[1])


def object_world_points(obj, mesh=None) -> np.ndarray:
    mesh = mesh or obj.data
    return transform_points(mesh_coords(mesh), obj.matrix_world)


def bbox_corner_points(obj) -> np.ndarray:
    pts = np.array([list(c) for c in obj.bound_box], dtype=np.float64)
    return transform_points(pts, obj.matrix_world)


def descendants(obj):
    return list(obj.children_recursive)


def depth_sorted(objs):
    def depth(o):
        d = 0
        p = o.parent
        while p is not None:
            d += 1
            p = p.parent
        return d
    return sorted(objs, key=depth)


def set_world(obj, world: Matrix, parent_world: Matrix | None):
    """Pose obj.matrix_basis pour obtenir `world`, en tenant compte du parent et de matrix_parent_inverse,
    sans dépendre d'une évaluation du depsgraph (on fournit la matrice monde du parent)."""
    if obj.parent is None or parent_world is None:
        obj.matrix_basis = world
    else:
        obj.matrix_basis = (parent_world @ obj.matrix_parent_inverse).inverted() @ world


def reparent_keep_world(obj, new_parent, world_of: dict):
    """Change le parent sans bouger l'objet dans le monde. `world_of` : matrices monde connues (mises à jour)."""
    w = world_of.get(obj.name, obj.matrix_world.copy())
    obj.parent = new_parent
    obj.matrix_parent_inverse = Matrix.Identity(4)
    pw = world_of.get(new_parent.name, new_parent.matrix_world.copy()) if new_parent is not None else None
    set_world(obj, w, pw)
    world_of[obj.name] = w


def snapshot_worlds(objs) -> dict:
    return {o.name: o.matrix_world.copy() for o in objs}


def model_mesh_users(mesh) -> list:
    """Objets qui référencent ce mesh (object.data ou LOD Sollumz)."""
    users = []
    for o in bpy.data.objects:
        if o.data == mesh:
            users.append(o)
            continue
        lods = getattr(o, "sz_lods", None)
        if lods is None:
            continue
        for attr in ("very_high", "high", "medium", "low", "very_low"):
            lod = getattr(lods, attr, None)
            if lod is not None and getattr(lod, "mesh_ref", None) == mesh:
                users.append(o)
                break
    return users


def translate_object_meshes(obj, offset: Matrix, sz_adapter=None) -> int:
    """Applique `offset` aux données de mesh de obj (tous ses LOD si c'est un Drawable Model).
    Les meshes partagés sont copiés d'abord : aucun autre objet n'est modifié. Retourne le nombre de copies."""
    copies = 0
    if sz_adapter is not None and sz_adapter.is_model(obj):
        lods = sz_adapter.lod_meshes(obj)
        done = {}
        for level, mesh in lods.items():
            if mesh.name in done:
                sz_adapter.set_lod_mesh(obj, level, done[mesh.name])
                continue
            others = [u for u in model_mesh_users(mesh) if u != obj]
            target = mesh
            if others:
                target = mesh.copy()
                copies += 1
            target.transform(offset)
            target.update()
            done[mesh.name] = target
            if target is not mesh:
                sz_adapter.set_lod_mesh(obj, level, target)
    elif obj.type == "MESH":
        mesh = obj.data
        if mesh.users > 1:
            mesh = mesh.copy()
            obj.data = mesh
            copies += 1
        mesh.transform(offset)
        mesh.update()
    return copies


def rebase_root(root, new_root_world: Matrix, sz_adapter=None) -> dict:
    """Déplace l'origine de `root` vers `new_root_world` SANS déplacer aucune géométrie dans le monde.

    - les enfants gardent leur matrice monde ;
    - tout descendant dont la matrice monde est l'identité (cas mal géré par l'exporteur, voir en-tête) reçoit la
      matrice monde de la racine et ses données de mesh sont exprimées dans ce repère (copie si partagé).
    Retourne un rapport {"rebased": [...], "mesh_copies": n}.
    """
    report = {"rebased": [], "mesh_copies": 0}
    objs = depth_sorted(descendants(root))
    old_world = snapshot_worlds([root] + objs)
    root_needs_fix = not is_identity(new_root_world)
    root.matrix_parent_inverse = Matrix.Identity(4) if root.parent is None else root.matrix_parent_inverse
    pw_root = root.parent.matrix_world.copy() if root.parent is not None else None
    set_world(root, new_root_world, pw_root)
    new_world = {root.name: new_root_world.copy()}
    for o in objs:
        w = old_world[o.name]
        if root_needs_fix and is_identity(w):
            inv = new_root_world.inverted()
            if o.type == "MESH":
                report["mesh_copies"] += translate_object_meshes(o, inv, sz_adapter)
            w = new_root_world.copy()
            report["rebased"].append(o.name)
        set_world(o, w, new_world.get(o.parent.name) if o.parent is not None else None)
        new_world[o.name] = w
    bpy.context.view_layer.update()
    return report


def find_identity_world_descendants(root) -> list:
    """Descendants qui seraient mal exportés (matrice monde identité alors que la racine ne l'est pas)."""
    if is_identity(root.matrix_world):
        return []
    return [o for o in root.children_recursive if is_identity(o.matrix_world)]
