"""Garantit qu'on ne modifie jamais un matériau ou un mesh partagé avec des objets hors du mapping."""

from __future__ import annotations

import bpy

from . import sollumz_adapter as sza
from .geom import model_mesh_users


def mapping_meshes(models) -> dict:
    """{mesh: [(model, niveau LOD)]} pour tous les LOD des modèles du mapping."""
    out = {}
    for m in models:
        for level, mesh in sza.lod_meshes(m).items():
            out.setdefault(mesh, []).append((m, level))
    return out


def material_users_outside(mat, mapping_objects: set) -> list:
    users = []
    for mesh in bpy.data.meshes:
        if mat.name not in mesh.materials:
            continue
        if not any(slot == mat for slot in mesh.materials):
            continue
        for o in model_mesh_users(mesh):
            if o not in mapping_objects:
                users.append(o)
    return users


def ensure_local_materials(models, materials) -> list[str]:
    """Pour chaque matériau de `materials` utilisé hors du mapping, crée une copie réservée au mapping.
    Les meshes du mapping partagés avec l'extérieur sont copiés d'abord. Retourne les messages."""
    msgs = []
    mapping_objects = set(models)
    meshes = mapping_meshes(models)
    for mat in list(materials):
        outside = material_users_outside(mat, mapping_objects)
        if not outside:
            continue
        copy = mat.copy()
        copy.name = mat.name + ".mio"
        for mesh, uses in list(meshes.items()):
            if not any(s == mat for s in mesh.materials):
                continue
            target_mesh = mesh
            if any(u not in mapping_objects for u in model_mesh_users(mesh)):
                target_mesh = mesh.copy()
                for model, level in uses:
                    sza.set_lod_mesh(model, level, target_mesh)
                meshes[target_mesh] = uses
                del meshes[mesh]
                msgs.append(f"Mesh « {mesh.name} » partagé hors du mapping : copie « {target_mesh.name} » créée.")
            for i, s in enumerate(target_mesh.materials):
                if s == mat:
                    target_mesh.materials[i] = copy
        msgs.append(f"Matériau « {mat.name} » partagé avec {len(outside)} objet(s) hors du mapping : copie "
                    f"« {copy.name} » utilisée par le mapping.")
    return msgs
