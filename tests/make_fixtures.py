"""Crée les données de test (100 % synthétiques, aucun fichier Rockstar) :

1. des assets « d'origine » construits avec Sollumz puis exportés en XML CodeWalker :
   - tst_building.ydr : bâtiment, 2 LOD, 5 slots de matériau (normal_spec, default, texture INTÉGRÉE tst_sign,
     décal, et un slot inutilisé), positionné ensuite dans le monde à (100, 200, 30) ;
   - tst_ground.ydr : sol en coordonnées monde (origine identité, cas « mal exporté » par Sollumz), shader
     multicouche terrain_cb_w_4lyr (8 textures, dont une manquante dans le jeu) et Color Attributes ;
   - tst_col.ybn : collision statique en coordonnées monde (Bound Composite > BVH > Poly Mesh) ;
   - tst.ytyp : archetypes tst_building / tst_ground (provenance -> dictionnaires de textures) ;
2. une fausse installation « GTA V » (archives RPF non chiffrées) contenant les YTD du jeu avec :
   homonymes (tst_grass dans 2 dictionnaires), copies identiques (tst_rock), dictionnaire parent gtxd
   (tst_rock_n), versions base/DLC (tst_sand), ambiguïté réelle (tst_dirt) et texture absente (tst_missing).
Usage : python make_fixtures.py   (variables d'environnement : voir bl_env.py)
"""

import json
import os
import shutil
import subprocess

import bl_env

bl_env.enable_addons(with_mio=False)

import bmesh  # noqa: E402
import bpy  # noqa: E402
from mathutils import Matrix, Vector  # noqa: E402

from dds_util import write_dds  # noqa: E402
from sollumz.sollumz_properties import SollumType, LODLevel  # noqa: E402
from sollumz.tools.blenderhelper import create_empty_object  # noqa: E402
from sollumz.ydr.shader_materials import create_shader  # noqa: E402
from sollumz.ybn.collision_materials import create_collision_material_from_index, collisionmats  # noqa: E402
from sollumz.tools.boundhelper import apply_flag_preset  # noqa: E402
from sollumz.tools.meshhelper import get_uv_map_name, get_color_attr_name  # noqa: E402

OUT = bl_env.OUT
FIX = os.path.join(OUT, "fixtures")
SRC = os.path.join(FIX, "src_assets")
DDS = os.path.join(FIX, "dds")
GTA = os.path.join(FIX, "fake_gta")
TOOL = os.environ["MIO_GTA_TOOL"]

for d in (SRC, DDS, GTA):
    if os.path.isdir(d):
        shutil.rmtree(d)
    os.makedirs(d)

# ---------------------------------------------------------------- DDS de test
TEX = {
    # nom: (w, h, format, couleur)
    "tst_brick": (256, 256, "DXT1", (180, 60, 40)),
    "tst_brick_n": (256, 256, "DXT5", (128, 128, 255)),
    "tst_brick_s": (128, 128, "DXT1", (40, 40, 40)),
    "tst_concrete": (128, 128, "DXT1", (150, 150, 150)),
    "tst_decal": (64, 64, "DXT5", (20, 20, 20)),
    "tst_sign": (128, 64, "A8R8G8B8", (250, 200, 0)),         # intégrée au YDR d'origine
    "tst_unused": (64, 64, "DXT1", (1, 2, 3)),                 # slot inutilisé : ne doit jamais être cherchée
    "tst_grass": (512, 512, "DXT1", (40, 160, 40)),            # version du dictionnaire du sol
    "tst_grass_other": (512, 512, "DXT1", (90, 90, 10)),       # homonyme d'un autre dictionnaire
    "tst_grass_n": (256, 256, "DXT5", (127, 127, 250)),
    "tst_rock": (256, 256, "DXT1", (120, 110, 100)),           # copie identique dans 2 dictionnaires
    "tst_rock_n": (256, 256, "DXT5", (126, 126, 251)),         # dans le dictionnaire PARENT (gtxd)
    "tst_sand_base": (256, 256, "DXT1", (200, 180, 120)),      # version de base
    "tst_sand_dlc": (256, 256, "DXT1", (210, 190, 130)),       # version DLC (prioritaire)
    "tst_sand_n": (256, 256, "DXT5", (125, 125, 252)),
    "tst_dirt_a": (256, 256, "DXT1", (100, 70, 40)),           # vraie ambiguïté
    "tst_dirt_b": (256, 256, "DXT1", (60, 40, 20)),
}
for n, (w, h, f, c) in TEX.items():
    write_dds(os.path.join(DDS, n + ".dds"), w, h, f, c)

# Images « source » nommées comme les textures GTA (le nom exporté = nom du fichier image)
NAMED = os.path.join(FIX, "named")
os.makedirs(NAMED, exist_ok=True)


SRC_KEY = {"tst_sand": "tst_sand_base", "tst_dirt": "tst_dirt_a"}


def image(name, src_key=None, embedded_dir=None):
    path = os.path.join(NAMED, name + ".dds")
    shutil.copy(os.path.join(DDS, (src_key or SRC_KEY.get(name, name)) + ".dds"), path)
    img = bpy.data.images.load(path, check_existing=True)
    return img


def shader(filename, name, textures, embedded=()):
    mat = create_shader(filename)
    mat.name = name
    for param, tex in textures.items():
        node = mat.node_tree.nodes[param]
        node.image = image(tex) if tex != "tst_missing" else _missing_image()
        node.texture_properties.embedded = tex in embedded
    return mat


def _missing_image():
    img = bpy.data.images.get("tst_missing") or bpy.data.images.new("tst_missing", 4, 4)
    img.source = "FILE"
    img.filepath = "//tst_missing.dds"
    return img


def mesh_from_bm(bm, name, materials):
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    for m in materials:
        me.materials.append(m)
    uv = me.uv_layers.new(name=get_uv_map_name(0))
    for loop in me.loops:
        co = me.vertices[loop.vertex_index].co
        uv.data[loop.index].uv = (co.x * 0.1, co.y * 0.1 + co.z * 0.1)
    for ci in range(2):
        ca = me.color_attributes.new(get_color_attr_name(ci), "BYTE_COLOR", "CORNER")
        for i, d in enumerate(ca.data):
            d.color = ((i * 37 % 255) / 255, (ci * 80 + i % 50) / 255, 0.5, 1.0)
    return me


def make_model(name, lods, parent):
    obj = bpy.data.objects.new(name, lods[LODLevel.HIGH])
    bpy.context.collection.objects.link(obj)
    obj.sollum_type = SollumType.DRAWABLE_MODEL
    for level, me in lods.items():
        obj.sz_lods.get_lod(level).mesh = me
    obj.sz_lods.active_lod_level = LODLevel.HIGH
    obj.parent = parent
    return obj


# ---------------------------------------------------------------- bâtiment
bpy.ops.wm.read_homefile(use_empty=True)
m_wall = shader("normal_spec.sps", "bld_wall", {"DiffuseSampler": "tst_brick", "BumpSampler": "tst_brick_n",
                                               "SpecSampler": "tst_brick_s"})
m_roof = shader("default.sps", "bld_roof", {"DiffuseSampler": "tst_concrete"})
m_sign = shader("default.sps", "bld_sign", {"DiffuseSampler": "tst_sign"}, embedded=("tst_sign",))
m_decal = shader("decal.sps", "bld_decal", {"DiffuseSampler": "tst_decal"})
m_unused = shader("default.sps", "bld_unused", {"DiffuseSampler": "tst_unused"})

bm = bmesh.new()
bmesh.ops.create_cube(bm, size=1.0)
bmesh.ops.scale(bm, vec=Vector((10, 8, 6)), verts=bm.verts)
bmesh.ops.translate(bm, vec=Vector((0, 0, 3)), verts=bm.verts)
bmesh.ops.subdivide_edges(bm, edges=bm.edges[:], cuts=3, use_grid_fill=True)
for f in bm.faces:
    n = f.normal
    c = f.calc_center_median()
    if n.z > 0.5:
        f.material_index = 1
    elif n.x > 0.5 and c.z > 4.0:
        f.material_index = 2
    elif n.y < -0.5 and c.z < 2.0:
        f.material_index = 3
    else:
        f.material_index = 0
hi = mesh_from_bm(bm, "tst_building_high", [m_wall, m_roof, m_sign, m_decal, m_unused])
bm.free()
bm = bmesh.new()
bmesh.ops.create_cube(bm, size=1.0)
bmesh.ops.scale(bm, vec=Vector((10, 8, 6)), verts=bm.verts)
bmesh.ops.translate(bm, vec=Vector((0, 0, 3)), verts=bm.verts)
for f in bm.faces:
    f.material_index = 1 if f.normal.z > 0.5 else 0
med = mesh_from_bm(bm, "tst_building_med", [m_wall, m_roof])
bm.free()
d_bld = create_empty_object(SollumType.DRAWABLE, "tst_building")
make_model("tst_building.model", {LODLevel.HIGH: hi, LODLevel.MEDIUM: med}, d_bld)
d_bld.drawable_properties.lod_dist_high = 120
d_bld.drawable_properties.lod_dist_med = 300

# ---------------------------------------------------------------- sol (coordonnées monde)
m_terrain = shader("terrain_cb_w_4lyr.sps", "ground_terrain", {
    "TextureSampler_layer0": "tst_grass", "BumpSampler_layer0": "tst_grass_n",
    "TextureSampler_layer1": "tst_rock", "BumpSampler_layer1": "tst_rock_n",
    "TextureSampler_layer2": "tst_sand", "BumpSampler_layer2": "tst_sand_n",
    "TextureSampler_layer3": "tst_dirt", "BumpSampler_layer3": "tst_missing",
})
bm = bmesh.new()
bmesh.ops.create_grid(bm, x_segments=16, y_segments=16, size=20.0)
for v in bm.verts:
    v.co.z = 29.9 + 0.05 * ((v.co.x * 0.3) % 1.0)
bmesh.ops.translate(bm, vec=Vector((100, 200, 0)), verts=bm.verts)
ground = mesh_from_bm(bm, "tst_ground_high", [m_terrain])
bm.free()
d_gnd = create_empty_object(SollumType.DRAWABLE, "tst_ground")
make_model("tst_ground.model", {LODLevel.HIGH: ground}, d_gnd)
d_gnd.drawable_properties.lod_dist_high = 500

# ---------------------------------------------------------------- collision statique (coordonnées monde)
idx_concrete = next(i for i, m in enumerate(collisionmats) if m.name == "CONCRETE")
cmat = create_collision_material_from_index(idx_concrete)
comp = create_empty_object(SollumType.BOUND_COMPOSITE, "tst_col")
bvh = create_empty_object(SollumType.BOUND_GEOMETRYBVH, "tst_col.bvh")
bvh.parent = comp
apply_flag_preset(bvh, "General (Default)")
bm = bmesh.new()
bmesh.ops.create_grid(bm, x_segments=8, y_segments=8, size=20.0)
for v in bm.verts:
    v.co.z = 29.9
bmesh.ops.translate(bm, vec=Vector((100, 200, 0)), verts=bm.verts)
geo = bmesh.ops.create_cube(bm, size=1.0)
cube_verts = geo["verts"]
bmesh.ops.scale(bm, vec=Vector((10, 8, 6)), verts=cube_verts)
bmesh.ops.translate(bm, vec=Vector((100, 200, 33)), verts=cube_verts)
me = bpy.data.meshes.new("tst_col_mesh")
bm.to_mesh(me)
bm.free()
me.materials.append(cmat)
poly = bpy.data.objects.new("tst_col.poly_mesh", me)
bpy.context.collection.objects.link(poly)
poly.sollum_type = SollumType.BOUND_POLY_TRIANGLE
poly.parent = bvh

# ---------------------------------------------------------------- YTYP des archetypes d'origine
y = bpy.context.scene.ytyps.add()
y.name = "tst"
from sollumz.sollumz_properties import ArchetypeType, AssetType  # noqa: E402
for an, txd in (("tst_building", "tst_building_txd"), ("tst_ground", "tst_ground_txd")):
    a = y.new_archetype(ArchetypeType.BASE)
    a.name = an
    a.asset_name = an
    a.texture_dictionary = txd
    a.asset_type = AssetType.DRAWABLE
    a.bb_min = (-1, -1, -1)
    a.bb_max = (1, 1, 1)
    a.bs_radius = 2

bpy.context.view_layer.update()
for o in bpy.context.view_layer.objects:
    o.select_set(False)
for o in (d_bld, d_gnd, comp):
    o.select_set(True)
r = bpy.ops.sollumz.export_assets(directory=SRC, direct_export=True, use_custom_settings=True,
                                  target_formats={"CWXML"}, target_versions={"GEN8"}, limit_to_selected=True,
                                  export_ytyps=True, export_ytyps_include="ALL")
print("export sources :", r, sorted(os.listdir(SRC)))
assert os.path.isfile(os.path.join(SRC, "tst_building.ydr.xml"))
assert os.path.isfile(os.path.join(SRC, "tst_building", "tst_sign.dds")), "texture intégrée non exportée"


def tool(*args):
    p = subprocess.run([TOOL, *args], capture_output=True, text=True)
    last = [l for l in p.stdout.splitlines() if l.startswith("{")][-1]
    data = json.loads(last)
    assert data.get("ok"), (args, data, p.stderr[-2000:])
    return data["data"]


tool("xml2bin", "--in", os.path.join(SRC, "tst.ytyp.xml"))

# ---------------------------------------------------------------- fausse installation GTA V
gtxd = """<?xml version="1.0" encoding="UTF-8"?>
<CMapParentTxds>
 <txdRelationships>
  <Item><parent>tst_shared_txd</parent><child>tst_ground_txd</child></Item>
 </txdRelationships>
</CMapParentTxds>
"""
dlclist = """<?xml version="1.0" encoding="UTF-8"?>
<SMandatoryPacksData>
 <Paths>
  <Item>platform:/dlcPacks/tstdlc/</Item>
 </Paths>
</SMandatoryPacksData>
"""


def ytd(*items):
    return [{"name": n, "dds": os.path.join(DDS, src + ".dds")} for n, src in items]


spec = {"archives": [
    {"path": "x64a.rpf", "files": [
        {"path": "common/data/gtxd.meta", "text": gtxd},
    ], "archives": [{"path": "levels/gta5/tst.rpf", "files": [
        {"path": "tst_building_txd.ytd", "ytd": ytd(("tst_brick", "tst_brick"), ("tst_brick_n", "tst_brick_n"),
                                                    ("tst_brick_s", "tst_brick_s"), ("tst_concrete", "tst_concrete"),
                                                    ("tst_decal", "tst_decal"))},
        {"path": "tst_ground_txd.ytd", "ytd": ytd(("tst_grass", "tst_grass"), ("tst_grass_n", "tst_grass_n"),
                                                  ("tst_sand_n", "tst_sand_n"))},
        {"path": "tst_other_txd.ytd", "ytd": ytd(("tst_grass", "tst_grass_other"))},
        {"path": "tst_props_a_txd.ytd", "ytd": ytd(("tst_rock", "tst_rock"))},
        {"path": "tst_props_b_txd.ytd", "ytd": ytd(("tst_rock", "tst_rock"))},
        {"path": "tst_shared_txd.ytd", "ytd": ytd(("tst_rock_n", "tst_rock_n"))},
        {"path": "tst_sand_txd.ytd", "ytd": ytd(("tst_sand", "tst_sand_base"))},
        {"path": "tst_misc_a_txd.ytd", "ytd": ytd(("tst_dirt", "tst_dirt_a"))},
        {"path": "tst_misc_b_txd.ytd", "ytd": ytd(("tst_dirt", "tst_dirt_b"))},
        {"path": "tst.ytyp", "bin": os.path.join(SRC, "tst.ytyp")},
    ]}]},
    {"path": "update/update.rpf", "files": [{"path": "common/data/dlclist.xml", "text": dlclist}]},
    {"path": "update/x64/dlcpacks/tstdlc/dlc.rpf", "files": [
        {"path": "x64/levels/tst/tst_sand_txd.ytd", "ytd": ytd(("tst_sand", "tst_sand_dlc"))},
    ]},
]}
spec_path = os.path.join(FIX, "fake_gta_spec.json")
with open(spec_path, "w") as f:
    json.dump(spec, f, indent=1)
print(tool("dev-make-rpf", "--spec", spec_path, "--out", GTA))
print("Fixtures OK :", FIX, flush=True)
# Le module bpy de Blender 4.5 peut rester bloqué à la fermeture de l'interpréteur : sortie explicite.
os._exit(0)
