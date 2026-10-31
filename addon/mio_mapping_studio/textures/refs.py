"""Analyse des références de textures réellement nécessaires au mapping.

Règles (alignées sur l'exporteur Sollumz 2.9.0) :
  - seuls les matériaux utilisés par des faces existantes (après découpe) sont analysés, sur tous les LOD exportés ;
  - seuls les nodes Image Texture correspondant à un paramètre texture du shader GTA sont pris en compte
    (DiffuseSampler, BumpSampler, SpecSampler, DetailSampler, TextureSampler_layer0..3, lookupSampler...) ;
  - le nom de texture est celui que Sollumz exporte : nom du fichier image sans extension (node.sollumz_texture_name) ;
  - un node sans image, ou une image sans chemin (aucun nom exporté), est un emplacement vide : écarté.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field

import bpy
import numpy as np

from .. import sollumz_adapter as sza


@dataclass
class TextureUse:
    material: str
    shader: str
    param: str
    model: str


@dataclass
class TextureRef:
    name: str
    uses: list = field(default_factory=list)
    images: list = field(default_factory=list)          # noms des Image Blender
    nodes: list = field(default_factory=list)            # (nom du matériau, nom du node)
    embedded: bool = False                               # marqué « embedded » dans un matériau importé
    sources: set = field(default_factory=set)            # assets d'origine (provenance)
    scene_dds: str = ""                                  # "packed" | chemin DDS existant | ""
    scene_state: str = "MISSING"                         # PACKED_DDS | FILE_DDS | FILE_OTHER | MISSING


def image_state(img) -> tuple[str, str]:
    if img is None:
        return "MISSING", ""
    pf = img.packed_file
    if pf is not None:
        try:
            data = pf.data
            if data[:4] == b"DDS ":
                return "PACKED_DDS", "packed"
            return "FILE_OTHER", "packed"
        except Exception:
            return "MISSING", ""
    path = bpy.path.abspath(img.filepath) if img.filepath else ""
    if path and os.path.isfile(path):
        try:
            with open(path, "rb") as f:
                head = f.read(4)
        except OSError:
            return "MISSING", ""
        return ("FILE_DDS", path) if head == b"DDS " else ("FILE_OTHER", path)
    return "MISSING", ""


def used_material_indices(mesh) -> set:
    if not len(mesh.polygons):
        return set()
    idx = np.empty(len(mesh.polygons), dtype=np.int32)
    mesh.polygons.foreach_get("material_index", idx)
    return set(np.unique(idx).tolist())


def analyze(models) -> tuple[dict, list[str]]:
    """Retourne ({nom texture: TextureRef}, messages)."""
    refs: dict[str, TextureRef] = {}
    msgs: list[str] = []
    unused_slots = 0
    for model in models:
        source = model.get("mio_source_asset") or model.name
        for level, mesh in sza.lod_meshes(model).items():
            used = used_material_indices(mesh)
            unused_slots += len([i for i in range(len(mesh.materials)) if i not in used])
            for i in sorted(used):
                if i >= len(mesh.materials):
                    continue
                mat = mesh.materials[i]
                if mat is None or not sza.is_shader_material(mat):
                    continue
                for param, node in sza.shader_texture_nodes(mat):
                    if node.image is None:
                        continue
                    tname = sza.texture_name_of_node(node).lower()
                    if not tname:
                        continue
                    ref = refs.setdefault(tname, TextureRef(tname))
                    ref.uses.append(TextureUse(mat.name, sza.shader_filename(mat), param, model.name))
                    if node.image.name not in ref.images:
                        ref.images.append(node.image.name)
                    key = (mat.name, node.name)
                    if key not in ref.nodes:
                        ref.nodes.append(key)
                    ref.embedded = ref.embedded or sza.is_node_embedded(node)
                    ref.sources.add(str(source).lower())
    for ref in refs.values():
        best = ("MISSING", "")
        for iname in ref.images:
            st = image_state(bpy.data.images.get(iname))
            order = {"PACKED_DDS": 3, "FILE_DDS": 2, "FILE_OTHER": 1, "MISSING": 0}
            if order[st[0]] > order[best[0]]:
                best = st
        ref.scene_state, ref.scene_dds = best
    if unused_slots:
        msgs.append(f"{unused_slots} slot(s) de matériau non utilisés par des faces : ignorés.")
    return refs, msgs


def materials_of(models) -> list:
    mats = []
    for model in models:
        for mesh in sza.lod_meshes(model).values():
            for i in used_material_indices(mesh):
                if i < len(mesh.materials):
                    m = mesh.materials[i]
                    if m is not None and m not in mats:
                        mats.append(m)
    return mats
