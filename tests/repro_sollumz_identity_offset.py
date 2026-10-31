"""Reproduction (Sollumz 2.9.0) : un enfant de Drawable dont la matrice monde est l'identité est exporté SANS retirer
la transformation du Drawable (sollumz_helper.get_parent_inverse retourne l'identité dans ce cas).

Scène : Drawable à (100, 200, 30) ; un modèle et une collision dont les sommets sont en coordonnées monde autour de
(100, 200, 31) et dont les objets sont à l'origine (cas d'un terrain ou d'un YBN importé puis regroupé).
Attendu dans le repère du Drawable : min (-1, -1, 0) max (1, 1, 2).
Résultat observé avec Sollumz 2.9.0 : min (99, 199, 30) max (101, 201, 32) -> décalage, l'objet apparaîtrait à
(200, 400, 60) en jeu. Mio Mapping Studio corrige ce cas (geom.rebase_root) et le vérifie à l'export.
"""
import json
import os
import subprocess

import bl_env

bl_env.enable_addons(with_mio=False)

import bmesh  # noqa: E402
import bpy  # noqa: E402
from mathutils import Matrix, Vector  # noqa: E402
from sollumz.sollumz_properties import SollumType, LODLevel  # noqa: E402
from sollumz.tools.blenderhelper import create_empty_object  # noqa: E402
from sollumz.ydr.shader_materials import create_shader  # noqa: E402
from sollumz.ybn.collision_materials import create_collision_material_from_index  # noqa: E402

bpy.ops.wm.read_homefile(use_empty=True)
mat = create_shader("default.sps")


def cube(name, off):
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=2.0)
    bmesh.ops.translate(bm, vec=Vector(off), verts=bm.verts)
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    bm.free()
    return me


d = create_empty_object(SollumType.DRAWABLE, "edgecase")
d.location = (100, 200, 30)
me = cube("vis", (100, 200, 31))
me.materials.append(mat)
me.uv_layers.new(name="UVMap 0")
m = bpy.data.objects.new("vis", me)
bpy.context.collection.objects.link(m)
m.sollum_type = SollumType.DRAWABLE_MODEL
m.sz_lods.get_lod(LODLevel.HIGH).mesh = me
m.sz_lods.active_lod_level = LODLevel.HIGH
comp = create_empty_object(SollumType.BOUND_COMPOSITE, "c")
bvh = create_empty_object(SollumType.BOUND_GEOMETRYBVH, "b")
cm = cube("colm", (100, 200, 31))
cm.materials.append(create_collision_material_from_index(1))
p = bpy.data.objects.new("p", cm)
bpy.context.collection.objects.link(p)
p.sollum_type = SollumType.BOUND_POLY_TRIANGLE
bpy.context.view_layer.update()
for child, parent in ((m, d), (comp, d), (bvh, comp), (p, bvh)):
    w = child.matrix_world.copy()
    child.parent = parent
    child.matrix_world = w
bpy.context.view_layer.update()
out = os.path.join(bl_env.OUT, "edgecase")
os.makedirs(out, exist_ok=True)
for o in bpy.context.view_layer.objects:
    o.select_set(False)
d.select_set(True)
bpy.ops.sollumz.export_assets(directory=out, direct_export=True, use_custom_settings=True, target_formats={"CWXML"},
                              target_versions={"GEN8"}, limit_to_selected=True)
T = os.environ["MIO_GTA_TOOL"]
subprocess.run([T, "xml2bin", "--in", os.path.join(out, "edgecase.ydr.xml")], capture_output=True)
r = subprocess.run([T, "verify", "--file", os.path.join(out, "edgecase.ydr")], capture_output=True, text=True)
info = json.loads([l for l in r.stdout.splitlines() if l.startswith('{"type":"result"')][-1])["data"]["files"][0]["info"]
b = info["bound"]["children"][0]["bound"]
print("attendu   : min (-1, -1, 0) max (1, 1, 2)")
print("visuel    :", info["bb_min"], info["bb_max"])
print("collision :", b["geometry_min"], b["geometry_max"])
