"""Tests de bout en bout de Mio Mapping Studio (Blender en module, Sollumz 2.9.0, MioGtaTool/CodeWalker.Core).

Chaque test part d'une scène « importée » avec l'importeur officiel de Sollumz (XML CodeWalker des fixtures),
comme le ferait l'utilisateur, puis appelle les opérateurs de l'addon (les mêmes que les boutons).
Les fichiers produits sont relus avec CodeWalker.Core (MioGtaTool verify) et comparés à la géométrie Blender.
Résultats : $MIO_TEST_OUT/test_report.json
"""

import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
import traceback

import bl_env

bl_env.enable_addons()

import bmesh  # noqa: E402
import bpy  # noqa: E402
import numpy as np  # noqa: E402
from mathutils import Vector  # noqa: E402

OUT = bl_env.OUT
FIX = os.path.join(OUT, "fixtures")
SRC = os.path.join(FIX, "src_assets")
DDS = os.path.join(FIX, "dds")
GTA = os.path.join(FIX, "fake_gta")
TOOL = os.environ["MIO_GTA_TOOL"]
RESULTS = []
CURRENT = {"test": ""}


def check(name, cond, detail=""):
    RESULTS.append({"test": CURRENT["test"], "check": name, "ok": bool(cond), "detail": str(detail)[:600]})
    print(("  [OK]   " if cond else "  [ECHEC] ") + name + ("" if cond else f"  -> {detail}"))
    return bool(cond)


def tool(*args):
    p = subprocess.run([TOOL, *args], capture_output=True, text=True)
    lines = [l for l in p.stdout.splitlines() if l.startswith('{"type":"result"')]
    data = json.loads(lines[-1]) if lines else {"ok": False, "error": p.stderr[-500:]}
    return data


def verify(path):
    d = tool("verify", "--file", path)
    assert d.get("ok"), d
    return d["data"]["files"][0]


def tree_hash(root):
    h = hashlib.sha1()
    for dp, _ds, fs in sorted(os.walk(root)):
        for f in sorted(fs):
            p = os.path.join(dp, f)
            h.update(p.encode())
            with open(p, "rb") as fh:
                h.update(fh.read())
    return h.hexdigest()


def import_scene(cut_ground=True, with_collision=True):
    bpy.ops.wm.read_homefile(use_empty=True)
    files = [{"name": "tst_building.ydr.xml"}, {"name": "tst_ground.ydr.xml"}]
    if with_collision:
        files.append({"name": "tst_col.ybn.xml"})
    r = bpy.ops.sollumz.import_assets(directory=SRC, files=files, use_custom_settings=True, textures_mode="PACK",
                                      split_by_group=False)
    assert "FINISHED" in r
    bld = bpy.data.objects["tst_building"]
    bld.location = (100.0, 200.0, 30.0)  # placement monde (comme via un YMAP importé)
    bpy.context.view_layer.update()
    if cut_ground:  # « découpe manuelle » : on retire une bande du sol visible et de la collision
        g = bpy.data.objects["tst_ground.model"]
        _delete_faces(g.data, lambda c: c.x > 115.0)
        if with_collision:
            p = [o for o in bpy.data.objects if o.sollum_type == "sollumz_bound_poly_triangle"][0]
            mw = p.matrix_world
            _delete_faces(p.data, lambda c: (mw @ c).x > 115.0)
    return bld


def _delete_faces(mesh, pred):
    bm = bmesh.new()
    bm.from_mesh(mesh)
    faces = [f for f in bm.faces if pred(f.calc_center_median())]
    bmesh.ops.delete(bm, geom=faces, context="FACES")
    bm.to_mesh(mesh)
    bm.free()


def world_points(obj, mesh=None):
    mesh = mesh or obj.data
    co = np.array([v.co[:] for v in mesh.vertices], dtype=np.float64)
    m = np.array(obj.matrix_world)
    return co @ m[:3, :3].T + m[:3, 3]


def snapshot_visual():
    snap = {}
    for o in bpy.data.objects:
        if o.sollum_type != "sollumz_drawable_model":
            continue
        for lvl in ("very_high", "high", "medium", "low", "very_low"):
            lod = getattr(o.sz_lods, lvl)
            mesh = lod.mesh
            if mesh is None:
                continue
            uv = np.array([d.uv[:] for d in mesh.uv_layers[0].data]) if mesh.uv_layers else None
            cols = {ca.name: np.array([d.color[:] for d in ca.data]) for ca in mesh.color_attributes}
            snap[(o.get("mio_source_asset") or o.name.split(".")[0], lvl)] = {
                "world": world_points(o, mesh), "uv": uv, "colors": cols,
                "mats": [m.name.replace(".mio", "") if m else None for m in mesh.materials],
                "faces": len(mesh.polygons)}
    return snap


def collision_world_points():
    pts = []
    for o in bpy.data.objects:
        if o.type == "MESH" and o.sollum_type == "sollumz_bound_poly_triangle" and o.name in bpy.context.view_layer.objects:
            pts.append(world_points(o))
    return np.concatenate(pts) if pts else np.zeros((0, 3))


def settings(name="garage", mode="STATIC_EMBEDDED", export="export"):
    s = bpy.context.scene.mio_mapping
    s.mapping_name = name
    s.gta_path = GTA
    s.export_dir = os.path.join(OUT, export)
    s.export_mode = mode
    return s


def select(*objs):
    for o in bpy.context.view_layer.objects:
        o.select_set(False)
    for o in objs:
        o.select_set(True)
    bpy.context.view_layer.objects.active = objs[0] if objs else None


def step(s, key):
    st = getattr(s, f"step_{key}")
    return st.status, st.messages


def ref(s, name):
    for r in s.texture_refs:
        if r.name == name:
            return r
    return None


def chosen(r):
    return r.candidates[r.chosen] if r is not None and 0 <= r.chosen < len(r.candidates) else None


def dds_pixels(path):
    with open(path, "rb") as f:
        return f.read()[128:]


class _Ops:
    """MIO.* mais un rapport ERROR (qui lève RuntimeError depuis Python) n'interrompt pas le test :
    on vérifie ensuite l'état de l'étape, comme l'utilisateur dans l'interface."""

    def __getattr__(self, name):
        op = getattr(bpy.ops.mio, name)

        def call(**kw):
            try:
                return op(**kw)
            except RuntimeError as e:
                print("    (rapport d'erreur de l'opérateur :", str(e).splitlines()[0][:160], ")")
                return {"CANCELLED"}
        return call


MIO = _Ops()


def run_test(fn):
    CURRENT["test"] = fn.__name__
    print(f"\n=== {fn.__name__} : {fn.__doc__.strip().splitlines()[0]}")
    t0 = time.time()
    try:
        fn()
    except Exception as e:
        traceback.print_exc()
        check("exception", False, f"{type(e).__name__}: {e}")
    print(f"    ({time.time() - t0:.1f} s)")


# =====================================================================================================================

def test_static_imported_collision():
    """Mode statique : collisions importées réutilisées, terrain multicouche, textures, relance, export embedded."""
    gta_before = tree_hash(GTA)
    import_scene()
    before = snapshot_visual()
    col_before = collision_world_points()
    s = settings("Garage")
    check("nom normalisé « Garage » -> mio_garage", s.asset_name == "mio_garage", s.asset_name)
    s.mapping_name = "mio_garage"
    check("pas de double préfixe", s.asset_name == "mio_garage", s.asset_name)
    s.collision_root = bpy.data.objects["tst_col"]
    select(bpy.data.objects["tst_building"], bpy.data.objects["tst_ground"])
    MIO.prepare_mapping()
    st, msg = step(s, "prepare")
    check("préparer : pas d'erreur", st in ("READY", "WARNING"), msg)
    d = bpy.data.objects.get("mio_garage")
    check("Drawable mio_garage créé", d is not None and d.sollum_type == "sollumz_drawable")
    models = [c for c in d.children if c.sollum_type == "sollumz_drawable_model"]
    check("2 modèles regroupés, aucun mesh fusionné", len(models) == 2, [m.name for m in models])
    check("LOD Medium du bâtiment conservé",
          any(m.sz_lods.medium.mesh is not None for m in models))
    after = snapshot_visual()
    same = all(np.allclose(before[k]["world"], after[k]["world"], atol=1e-4) for k in before)
    check("positions mondiales des sommets inchangées (tous LOD)", same and set(before) == set(after),
          sorted(set(before) ^ set(after)))
    check("UV inchangées", all(np.allclose(before[k]["uv"], after[k]["uv"]) for k in before if before[k]["uv"] is not None))
    check("Color Attributes inchangés", all(
        set(before[k]["colors"]) == set(after[k]["colors"]) and
        all(np.allclose(before[k]["colors"][n], after[k]["colors"][n]) for n in before[k]["colors"]) for k in before))
    check("matériaux / slots inchangés", all(before[k]["mats"] == after[k]["mats"] for k in before))
    o = d.matrix_world.translation
    allv = np.concatenate([after[k]["world"] for k in after])
    mn, mx = allv.min(axis=0), allv.max(axis=0)
    check("origine = centre XY / point le plus bas du mapping (après découpe)",
          np.allclose([o.x, o.y, o.z], [(mn[0] + mx[0]) / 2, (mn[1] + mx[1]) / 2, mn[2]], atol=1e-4), (tuple(o), mn, mx))
    gnd = [m for m in models if m.get("mio_source_asset") == "tst_ground"][0]
    check("sol (matrice identité) ré-exprimé dans le repère du Drawable",
          not np.allclose(np.array(gnd.matrix_world), np.eye(4)))
    col = bpy.data.objects.get("mio_garage_col")
    check("collision importée renommée mio_garage_col", col is not None and col == s.collision_root)
    check("racine collision = Bound Composite", col is not None and col.sollum_type == "sollumz_bound_composite")
    check("collision non déplacée", np.allclose(np.sort(col_before, axis=0), np.sort(collision_world_points(), axis=0),
                                                atol=1e-4))

    # ---- textures
    MIO.find_textures()
    st, msg = step(s, "textures")
    names = {r.name for r in s.texture_refs}
    check("slot inutilisé ignoré (tst_unused)", "tst_unused" not in names, names)
    check("placeholder sans référence ignoré", "" not in names)
    expected = {"tst_brick", "tst_brick_n", "tst_brick_s", "tst_concrete", "tst_sign", "tst_decal", "tst_grass",
                "tst_grass_n", "tst_rock", "tst_rock_n", "tst_sand", "tst_sand_n", "tst_dirt", "tst_missing"}
    check("références nécessaires = textures réellement utilisées (8 du terrain multicouche incluses)",
          names == expected, sorted(names ^ expected))
    r = ref(s, "tst_brick")
    check("tst_brick trouvée via la provenance (tst_building_txd)", chosen(r) and chosen(r).dict_name == "tst_building_txd",
          r.reason if r else None)
    r = ref(s, "tst_sign")
    check("texture intégrée au modèle importé utilisée (SCENE)", chosen(r) and chosen(r).kind == "SCENE", r.reason)
    r = ref(s, "tst_grass")
    check("homonyme tst_grass résolu par provenance (tst_ground_txd, pas tst_other_txd)",
          chosen(r) and chosen(r).dict_name == "tst_ground_txd" and len(r.candidates) == 2, r.reason)
    r = ref(s, "tst_rock")
    check("copies identiques tst_rock : pas d'ambiguïté", r.status == "FOUND" and len(r.candidates) == 2, r.reason)
    r = ref(s, "tst_rock_n")
    check("dictionnaire parent gtxd (tst_shared_txd)", chosen(r) and chosen(r).dict_name == "tst_shared_txd", r.reason)
    r = ref(s, "tst_sand")
    check("versions base/DLC : la version DLC prioritaire est retenue",
          chosen(r) and "dlcpacks/tstdlc" in chosen(r).path, chosen(r).path if chosen(r) else r.reason)
    r = ref(s, "tst_dirt")
    check("vraie ambiguïté tst_dirt signalée (pas de choix arbitraire)", r.status == "AMBIGUOUS" and r.chosen == -1,
          r.status)
    r = ref(s, "tst_missing")
    check("texture absente signalée manquante", r.status == "MISSING", r.status)
    check("état de l'étape textures = Erreur (manquante)", st == "ERROR", st)
    check("bilan affiché", "Références nécessaires : 14" in s.texture_summary, s.texture_summary)
    ytd = s.ytd_work_path
    check("YTD binaire construit", ytd and os.path.isfile(ytd))
    info = verify(ytd)["info"]
    ytd_names = sorted(t["name"] for t in info["textures"])
    check("YTD relu par CodeWalker.Core : textures trouvées seulement, sans doublon",
          ytd_names == sorted(expected - {"tst_dirt", "tst_missing"}), ytd_names)
    # pixels identiques aux originaux (aucune recompression)
    ok = True
    for name, src in (("tst_sand", "tst_sand_dlc"), ("tst_grass", "tst_grass"), ("tst_brick_n", "tst_brick_n")):
        p = ref(s, name).dds_path
        ok &= dds_pixels(p) == dds_pixels(os.path.join(DDS, src + ".dds"))
    check("DDS extraits identiques aux originaux (formats, mips, alpha)", ok)
    img = bpy.data.images.get("tst_brick")
    check("image Blender rechargée depuis le DDS d'origine, nom de texture conservé",
          img is not None and os.path.isfile(bpy.path.abspath(img.filepath)) and
          os.path.basename(img.filepath) == "tst_brick.dds", img.filepath if img else None)
    check("UV/couleurs toujours inchangés après textures",
          all(np.allclose(before[k]["uv"], snapshot_visual()[k]["uv"]) for k in before if before[k]["uv"] is not None))

    # choix manuel de la source ambiguë
    r = ref(s, "tst_dirt")
    idx = next(i for i, c in enumerate(r.candidates) if c.dict_name == "tst_misc_b_txd")
    MIO.choose_texture_source(ref_index=list(s.texture_refs).index(r), candidate_index=idx)
    MIO.find_textures()
    r = ref(s, "tst_dirt")
    check("choix manuel mémorisé et appliqué (tst_misc_b_txd)", r.status == "FOUND" and
          chosen(r).dict_name == "tst_misc_b_txd" and dds_pixels(r.dds_path) == dds_pixels(os.path.join(DDS, "tst_dirt_b.dds")),
          r.reason)

    # ---- YTYP + intégration
    MIO.update_ytyp()
    MIO.integrate_collision()
    st, msg = step(s, "collision")
    check("collision intégrée (Bound Composite enfant direct du Drawable)", col.parent == d and st != "ERROR", msg)
    check("collision toujours à sa place après intégration",
          np.allclose(np.sort(col_before, axis=0), np.sort(collision_world_points(), axis=0), atol=1e-4))
    check("meshes visuels et collision restent séparés (pas de Ctrl+J)",
          all(c.sollum_type == "sollumz_drawable_model" for c in models) and
          all(not any(m and m.sollum_type == "sollumz_material_collision" for m in c.data.materials) for c in models))
    y = bpy.context.scene.ytyps[0]
    a = [x for x in y.archetypes if x.name == "mio_garage"]
    check("archetype Base unique mio_garage", len(a) == 1 and len(y.archetypes) == 1, [x.name for x in y.archetypes])
    a = a[0]
    check("Asset Name / Texture Dictionary / Physics Dictionary = mio_garage",
          a.asset_name == "mio_garage" and a.texture_dictionary == "mio_garage" and a.physics_dictionary == "mio_garage",
          (a.asset_name, a.texture_dictionary, a.physics_dictionary))

    # ---- export refusé tant qu'il manque une texture
    export_dir = s.export_dir
    if os.path.isdir(export_dir):
        shutil.rmtree(export_dir)
    MIO.verify_export()
    st, msg = step(s, "export")
    check("export complet refusé : texture manquante", st == "ERROR" and not os.path.exists(os.path.join(export_dir, "mio_garage.ydr")),
          msg[:300])

    # ---- export incomplet explicite
    MIO.verify_export(allow_incomplete=True)
    st, msg = step(s, "export")
    ydr = os.path.join(export_dir, "mio_garage.ydr")
    check("export incomplet : fichiers écrits et déclarés INCOMPLET", os.path.isfile(ydr) and "INCOMPLET" in msg, msg[:400])

    # ---- correction : DDS local pour la texture manquante (mode de secours)
    miss_path = os.path.join(OUT, "local_dds", "tst_missing.dds")
    os.makedirs(os.path.dirname(miss_path), exist_ok=True)
    shutil.copy(os.path.join(DDS, "tst_concrete.dds"), miss_path)
    im = bpy.data.images["tst_missing"]
    im.filepath = miss_path
    MIO.find_textures()
    r = ref(s, "tst_missing")
    check("DDS local utilisé en mode secours et signalé comme tel",
          r.status == "FOUND" and chosen(r).kind == "LOCAL" and step(s, "textures")[0] == "WARNING", r.reason)
    MIO.update_ytyp()
    MIO.verify_export()
    st, msg = step(s, "export")
    check("export COMPLET", st in ("READY", "WARNING") and "Export COMPLET" in msg, msg[:600])
    files = sorted(f for f in os.listdir(export_dir) if not f.startswith("."))
    check("3 livrables (+ rapport) : ydr, ytd, ytyp", files == ["mio_garage.ydr", "mio_garage.ytd", "mio_garage.ytyp",
                                                               "mio_garage_rapport.txt"], files)
    check("aucun XML dans l'export final", not any(f.endswith(".xml") for f in files))
    for f in ("mio_garage.ydr", "mio_garage.ytd", "mio_garage.ytyp"):
        with open(os.path.join(export_dir, f), "rb") as fh:
            check(f"{f} est une ressource binaire RSC7", fh.read(4) == b"RSC7")
    yinfo = verify(ydr)["info"]
    b = yinfo["bound"]
    check("YDR relu : collision intégrée de type Composite", b is not None and b["type"] == "Composite", b and b["type"])
    # alignement indépendant : AABB des sommets de collision relus (repère du Drawable) vs Blender
    exp = collision_world_points() - np.array(d.matrix_world.translation)
    got_min = np.array(b["children"][0]["bound"]["geometry_min"])
    got_max = np.array(b["children"][0]["bound"]["geometry_max"])
    check("alignement collision/visuel : AABB relue = AABB Blender (repère du Drawable, ±1 cm)",
          np.allclose(got_min, exp.min(axis=0), atol=0.01) and np.allclose(got_max, exp.max(axis=0), atol=0.01),
          (got_min, exp.min(axis=0), got_max, exp.max(axis=0)))
    check("boîte BVH cohérente avec ses sommets", b["children"][0]["bound"]["box_consistent"] is True)
    vis = np.concatenate([after[k]["world"] for k in after]) - np.array(d.matrix_world.translation)
    check("bounds visuels du YDR = géométrie Blender", np.allclose(yinfo["bb_min"], vis.min(axis=0), atol=0.01) and
          np.allclose(yinfo["bb_max"], vis.max(axis=0), atol=0.01), (yinfo["bb_min"], vis.min(axis=0)))
    check("textures référencées par le YDR toutes dans le YTD",
          set(yinfo["referenced_textures"]) <= {t["name"] for t in verify(os.path.join(export_dir, "mio_garage.ytd"))["info"]["textures"]},
          yinfo["referenced_textures"])
    check("texture intégrée d'origine déplacée dans le YTD (pas de doublon dans le YDR)",
          yinfo["embedded_textures"] == [], yinfo["embedded_textures"])
    tinfo = verify(os.path.join(export_dir, "mio_garage.ytyp"))["info"]
    arch = tinfo["archetypes"]
    check("YTYP relu : 1 archetype Base, aucun MLO", len(arch) == 1 and arch[0]["kind"] == "CBaseArchetypeDef",
          [x["kind"] for x in arch])
    a0 = arch[0]
    check("YTYP : asset/txd/physics = mio_garage, ASSET_TYPE_DRAWABLE, flag Static",
          a0["asset_name"] == "mio_garage" and a0["texture_dictionary"] == "mio_garage" and
          a0["physics_dictionary"] == "mio_garage" and a0["asset_type"] == "ASSET_TYPE_DRAWABLE" and a0["flags"] & 32,
          a0)
    allpts = np.concatenate([vis, exp])
    check("YTYP : BBMin/BBMax = géométrie exportée (visuel + collision)",
          np.allclose(a0["bb_min"], allpts.min(axis=0), atol=0.02) and np.allclose(a0["bb_max"], allpts.max(axis=0), atol=0.02),
          (a0["bb_min"], allpts.min(axis=0)))

    # ---- relance complète : aucun doublon
    n_objs = len(bpy.data.objects)
    n_mats = len(bpy.data.materials)
    select(d)
    MIO.prepare_mapping()
    MIO.find_textures()
    MIO.update_ytyp()
    MIO.integrate_collision()
    MIO.verify_export()
    st, msg = step(s, "export")
    check("relance complète : export OK", "Export COMPLET" in msg, msg[:300])
    check("relance : aucun objet ni matériau dupliqué", len(bpy.data.objects) == n_objs and len(bpy.data.materials) == n_mats,
          (n_objs, len(bpy.data.objects), n_mats, len(bpy.data.materials)))
    check("relance : un seul YTYP / archetype", len(bpy.context.scene.ytyps) == 1 and len(bpy.context.scene.ytyps[0].archetypes) == 1)
    txds = [t for t in bpy.context.scene.sz_txds.texture_dictionaries if t.name == "mio_garage"]
    check("relance : un seul dictionnaire de textures Sollumz, sans doublon",
          len(txds) == 1 and len({t.name for t in txds[0].textures}) == len(txds[0].textures))
    check("relance : ancien export sauvegardé avant remplacement", os.path.isdir(os.path.join(export_dir, ".mio_backup")))
    check("relance : pas de dossier temporaire laissé", not any(f.startswith(".mio_staging") for f in os.listdir(export_dir)))
    check("installation GTA jamais modifiée", tree_hash(GTA) == gta_before)
    bpy.ops.wm.save_as_mainfile(filepath=os.path.join(OUT, "static_result.blend"))


def test_collision_from_visual():
    """Génération des collisions depuis le visuel (copie indépendante, matériau, flags, un seul LOD, décals exclus)."""
    import_scene(with_collision=False)
    s = settings("garage_gen", export="export_gen")
    select(bpy.data.objects["tst_building"], bpy.data.objects["tst_ground"])
    MIO.prepare_mapping()
    d = bpy.data.objects["mio_garage_gen"]
    models = [c for c in d.children if c.sollum_type == "sollumz_drawable_model"]
    vis_mats_before = {m.name: [x.name for x in m.data.materials] for m in models}
    s.collision_usage = "GENERAL"
    MIO.create_collision()
    st, msg = step(s, "prepare")
    col = bpy.data.objects.get("mio_garage_gen_col")
    check("Bound Composite mio_garage_gen_col créé", col is not None and col.sollum_type == "sollumz_bound_composite", msg)
    bvhs = [c for c in col.children if c.sollum_type == "sollumz_bound_geometrybvh"]
    polys = [p for b in bvhs for p in b.children if p.sollum_type == "sollumz_bound_poly_triangle"]
    check("structure Composite > BVH > Poly Mesh", len(bvhs) >= 1 and len(polys) >= 1)
    check("copie : seuls des matériaux de collision", all(all(m.sollum_type == "sollumz_material_collision"
                                                              for m in p.data.materials) for p in polys))
    mat = polys[0].data.materials[0]
    check("matériau de collision valide CONCRETE (index Sollumz)", mat.collision_properties.collision_index ==
          [i for i, (n) in enumerate(__import__("sollumz").ybn.collision_materials.collisionmats) if n.name == "CONCRETE"][0])
    check("flags preset « General (Default) » appliqués", all(b.composite_flags1.map_vehicle and b.composite_flags2.ped
                                                              for b in bvhs))
    check("visuel intact (matériaux d'origine conservés)",
          {m.name: [x.name for x in m.data.materials] for m in models} == vis_mats_before)
    check("données mesh indépendantes", not ({p.data.name for p in polys} & {mm.name for m in models
                                                                             for mm in [m.sz_lods.high.mesh] if mm}))
    bld = [m for m in models if m.get("mio_source_asset") == "tst_building"][0]
    hi = bld.sz_lods.high.mesh
    decal_idx = [i for i, m in enumerate(hi.materials) if m and m.shader_properties.filename == "decal.sps"][0]
    n_decal = sum(1 for p in hi.polygons if p.material_index == decal_idx)
    gnd = [m for m in models if m.get("mio_source_asset") == "tst_ground"][0]
    total = sum(len(p.data.polygons) for p in polys)
    check("un seul LOD copié (High) et faces de décal exclues",
          total == len(hi.polygons) - n_decal + len(gnd.data.polygons), (total, len(hi.polygons), n_decal, len(gnd.data.polygons)))
    pts = collision_world_points()
    vis = np.concatenate([world_points(m, m.sz_lods.high.mesh) for m in models])
    check("collision générée alignée sur le visuel (même AABB monde)", np.allclose(pts.min(axis=0), vis.min(axis=0), atol=1e-3)
          and np.allclose(pts.max(axis=0), vis.max(axis=0), atol=1e-3))
    check("avertissement copie détaillée / simplification manuelle", "simplifie" in msg.lower())
    # pas de remplacement implicite
    n = len(bpy.data.objects)
    MIO.create_collision()
    st, msg = step(s, "prepare")
    check("pas de remplacement sans action explicite", st == "ERROR" and len(bpy.data.objects) == n, msg[:200])
    s.collision_replace_existing = True
    MIO.create_collision()
    check("régénération explicite sans doublon", len(bpy.data.objects) == n and bpy.data.objects.get("mio_garage_gen_col.001") is None,
          (n, len(bpy.data.objects)))
    MIO.find_textures()
    MIO.update_ytyp()
    MIO.integrate_collision()
    s.generate_ymap = True
    s.generate_fivem = True
    MIO.verify_export(allow_incomplete=True)
    st, msg = step(s, "export")
    stream = os.path.join(s.export_dir, "mio_garage_gen", "stream")
    files = sorted(os.listdir(stream)) if os.path.isdir(stream) else []
    check("export (YMAP + ressource FiveM)", files == ["mio_garage_gen.ydr", "mio_garage_gen.ymap", "mio_garage_gen.ytd",
                                                       "mio_garage_gen.ytyp"], (files, msg[:400]))
    fx = os.path.join(s.export_dir, "mio_garage_gen", "fxmanifest.lua")
    check("fxmanifest.lua déclare le YTYP", os.path.isfile(fx) and "DLC_ITYP_REQUEST' 'stream/mio_garage_gen.ytyp'" in open(fx).read())
    if files:
        m = verify(os.path.join(stream, "mio_garage_gen.ymap"))["info"]
        e = m["entities"][0]
        check("YMAP : entité mio_garage_gen à l'origine du Drawable, sans MLO",
              e["archetype"] == "mio_garage_gen" and not e["mlo"] and np.allclose(e["position"], d.matrix_world.translation, atol=1e-3),
              e)
        b = verify(os.path.join(stream, "mio_garage_gen.ydr"))["info"]["bound"]
        check("YDR : collision générée intégrée et cohérente", b and b["type"] == "Composite" and
              all(c["bound"]["box_consistent"] for c in b["children"]))


def test_bvh_split():
    """Fractionnement BVH selon la limite réelle de l'exporteur (32767 sommets)."""
    bpy.ops.wm.read_homefile(use_empty=True)
    from sollumz.ydr.shader_materials import create_shader
    mat = create_shader("default.sps")
    bm = bmesh.new()
    bmesh.ops.create_grid(bm, x_segments=230, y_segments=230, size=50.0)
    me = bpy.data.meshes.new("big")
    bm.to_mesh(me)
    bm.free()
    me.materials.append(mat)
    me.uv_layers.new(name="UVMap")
    obj = bpy.data.objects.new("big_plane", me)
    bpy.context.collection.objects.link(obj)
    obj.location = (500, 500, 10)
    s = settings("bigplane", export="export_big")
    select(obj)
    MIO.prepare_mapping()
    st, msg = step(s, "prepare")
    check("mesh Blender avec matériau Sollumz converti en Drawable Model", obj.sollum_type == "sollumz_drawable_model", msg[:300])
    MIO.create_collision()
    col = bpy.data.objects["mio_bigplane_col"]
    bvhs = [c for c in col.children if c.sollum_type == "sollumz_bound_geometrybvh"]
    counts = [sum(len(p.data.vertices) for p in b.children) for b in bvhs]
    check(f"{len(me.vertices)} sommets fractionnés en BVH ≤ 32767", len(bvhs) >= 2 and max(counts) <= 32767, counts)
    MIO.integrate_collision()
    MIO.find_textures()
    MIO.update_ytyp()
    MIO.verify_export(allow_incomplete=True)
    ydr = os.path.join(s.export_dir, "mio_bigplane.ydr")
    ok = os.path.isfile(ydr)
    check("export du grand mapping", ok, step(s, "export")[1][:300])
    if ok:
        b = verify(ydr)["info"]["bound"]
        check("YDR : autant d'enfants de collision que de BVH, tous cohérents",
              len(b["children"]) == len(bvhs) and all(c["bound"]["box_consistent"] for c in b["children"]))


def test_mlo_mode():
    """Mode MLO limbo : archetype MLO relié au vrai YBN, room limbo (marge XY symétrique), entité, YMAP."""
    import_scene()
    s = settings("garage_mlo", mode="MLO_LIMBO", export="export_mlo")
    s.limbo_margin_xy = 0.5
    s.limbo_margin_z = 0.0
    s.collision_root = bpy.data.objects["tst_col"]
    select(bpy.data.objects["tst_building"], bpy.data.objects["tst_ground"])
    MIO.prepare_mapping()
    MIO.find_textures()
    MIO.update_ytyp()
    MIO.integrate_collision()
    st, msg = step(s, "collision")
    d = bpy.data.objects["mio_garage_mlo"]
    col = bpy.data.objects["mio_garage_mlo_col"]
    check("MLO : collision séparée et alignée sur le Drawable", col.parent is None and st != "ERROR" and
          (col.matrix_world.translation - d.matrix_world.translation).length < 1e-6, msg[:200])
    MIO.configure_mlo()
    st, msg = step(s, "mlo")
    check("configuration MLO sans erreur", st in ("READY", "WARNING"), msg[:300])
    y = bpy.context.scene.ytyps[0]
    mlo = [a for a in y.archetypes if a.name == "mio_garage_mlo_col"][0]
    limbo = [r for r in mlo.rooms if r.name == "limbo"]
    check("room nommée exactement « limbo »", len(limbo) == 1 and len(mlo.rooms) == 1)
    limbo = limbo[0]
    inv = np.array(col.matrix_world.inverted())
    pts = []
    for m in d.children:
        if m.sollum_type == "sollumz_drawable_model":
            for lvl in ("high", "medium"):
                mesh = getattr(m.sz_lods, lvl).mesh
                if mesh:
                    pts.append(world_points(m, mesh))
    pts.append(collision_world_points())
    loc = np.concatenate(pts) @ inv[:3, :3].T + inv[:3, 3]
    mn, mx = loc.min(axis=0), loc.max(axis=0)
    check("limbo : BBMin X/Y diminué de 0,50 et BBMax X/Y augmenté de 0,50 (repère local du MLO)",
          np.allclose(limbo.bb_min[:2], mn[:2] - 0.5, atol=1e-3) and np.allclose(limbo.bb_max[:2], mx[:2] + 0.5, atol=1e-3),
          (tuple(limbo.bb_min), mn, tuple(limbo.bb_max), mx))
    check("limbo : hauteur conservée (pas de marge Z par défaut)",
          abs(limbo.bb_min[2] - mn[2]) < 1e-3 and abs(limbo.bb_max[2] - mx[2]) < 1e-3)
    ents = [e for e in mlo.entities if e.archetype_name == "mio_garage_mlo"]
    check("entité mio_garage_mlo attachée à limbo", len(ents) == 1 and ents[0].attached_room_id == str(limbo.id))
    check("aucun portal créé", len(mlo.portals) == 0)
    base = [a for a in y.archetypes if a.name == "mio_garage_mlo"][0]
    check("archetype Base sans Physics Dictionary en mode MLO", base.physics_dictionary == "")
    MIO.verify_export(allow_incomplete=True)
    st, msg = step(s, "export")
    files = sorted(f for f in os.listdir(s.export_dir) if not f.startswith(".") and not f.endswith(".txt"))
    check("MLO : 5 fichiers réellement nécessaires", files == ["mio_garage_mlo.ydr", "mio_garage_mlo.ymap",
                                                             "mio_garage_mlo.ytd", "mio_garage_mlo.ytyp",
                                                             "mio_garage_mlo_col.ybn"], (files, msg[:500]))
    if len(files) == 5:
        yi = verify(os.path.join(s.export_dir, "mio_garage_mlo.ydr"))["info"]
        check("MLO : YDR sans collision intégrée (pas de doublon)", yi["bound"] is None)
        bi = verify(os.path.join(s.export_dir, "mio_garage_mlo_col.ybn"))["info"]["bound"]
        exp = collision_world_points() - np.array(col.matrix_world.translation)
        gmin = np.array(bi["children"][0]["bound"]["geometry_min"])
        check("MLO : YBN aligné (repère du MLO)", np.allclose(gmin, exp.min(axis=0), atol=0.01), (gmin, exp.min(axis=0)))
        ti = verify(os.path.join(s.export_dir, "mio_garage_mlo.ytyp"))["info"]
        kinds = {a["name"]: a for a in ti["archetypes"]}
        m = kinds.get("mio_garage_mlo_col", {})
        check("YTYP : archetype MLO mio_garage_mlo_col avec room limbo et entité attachée",
              m.get("kind") == "CMloArchetypeDef" and m["mlo"]["rooms"][0]["name"] == "limbo" and
              m["mlo"]["rooms"][0]["attached"] == [0] and m["mlo"]["entities"][0]["archetype"] == "mio_garage_mlo", m)
        check("YTYP : MLO ne référence que des fichiers exportés", "mio_garage_mlo_col.ybn" in files)
        mi = verify(os.path.join(s.export_dir, "mio_garage_mlo.ymap"))["info"]
        e = mi["entities"][0]
        check("YMAP : instance MLO mio_garage_mlo_col à l'origine de la collision",
              e["mlo"] and e["archetype"] == "mio_garage_mlo_col" and np.allclose(e["position"], col.matrix_world.translation, atol=1e-3), e)

    # Passage en mode statique avec l'archetype MLO encore présent : export refusé (pas d'export silencieux)
    s.export_mode = "STATIC_EMBEDDED"
    MIO.integrate_collision()
    MIO.update_ytyp()
    d2 = os.path.join(OUT, "export_invalid")
    s.export_dir = d2
    MIO.verify_export(allow_incomplete=True)
    st, msg = step(s, "export")
    check("montage invalide (MLO + statique) refusé, rien d'écrit", st == "ERROR" and "MLO" in msg and
          not os.path.exists(os.path.join(d2, "mio_garage_mlo.ydr")), msg[:300])
    MIO.remove_incoherent_mlo()
    MIO.update_ytyp()
    MIO.verify_export(allow_incomplete=True)
    st, msg = step(s, "export")
    check("après retrait du MLO : export statique accepté", os.path.isfile(os.path.join(d2, "mio_garage_mlo.ydr")), msg[:300])


def test_invalid_inputs():
    """Entrées invalides : rien n'est modifié silencieusement."""
    bpy.ops.wm.read_homefile(use_empty=True)
    bpy.ops.mesh.primitive_cube_add()
    cube = bpy.context.active_object
    s = settings("cube")
    select(cube)
    MIO.prepare_mapping()
    st, msg = step(s, "prepare")
    check("mesh sans matériau Sollumz refusé", st == "ERROR" and bpy.data.objects.get("mio_cube") is None, msg[:200])
    s.mapping_name = "  "
    MIO.prepare_mapping()
    check("nom vide refusé", step(s, "prepare")[0] == "ERROR")
    select()
    s.mapping_name = "cube"
    MIO.prepare_mapping()
    check("aucune sélection : refus (jamais tous les objets de la scène)", step(s, "prepare")[0] == "ERROR")


def test_named_collision_and_far_origin():
    """Cas réel signalé : collision « mio_xxxx_col » présente mais non désignée, Drawable à l'origine loin du mapping."""
    from mio_mapping_studio import diagnostics
    import_scene()
    s = settings("airport", export="export_airport")
    s.collision_root = None
    s.mapping_root = None
    bpy.data.objects["tst_col"].name = "mio_airport_col"
    gnd = bpy.data.objects["tst_ground"]   # Drawable fait à la main : origine (0,0,0), géométrie vers (100, 200)
    gnd.name = "mio_airport"
    bpy.context.view_layer.update()
    r = diagnostics.check_prepare(bpy.context, s)
    check("diagnostic : collision existante non désignée signalée (et non « aucune collision »)",
          any("existe mais n'est pas désignée" in w for w in r.warnings) and
          not any(w.startswith("Aucune collision") for w in r.warnings), r.warnings)
    check("diagnostic : origine éloignée de la géométrie signalée", any("de sa géométrie" in w for w in r.warnings),
          r.warnings)
    MIO.use_named_collision()
    check("bouton « Utiliser mio_airport_col » : collision désignée",
          s.collision_root is not None and s.collision_root.name == "mio_airport_col")
    s.collision_root = None
    s.origin_mode = "BOUNDS_BOTTOM_CENTER"
    select(gnd)
    MIO.prepare_mapping()
    check("Préparer : collision trouvée par son nom exact", s.collision_root is not None and
          s.collision_root.name == "mio_airport_col", step(s, "prepare")[1][:300])
    r = diagnostics.check_prepare(bpy.context, s)
    check("après Préparer : plus d'alerte d'origine ni de collision manquante",
          not any("de sa géométrie" in w or "Aucune collision" in w or "pas désignée" in w for w in r.warnings),
          r.warnings)


def _complete_textures(s):
    """Rend l'étape 2 complète : source choisie pour tst_dirt, DDS local pour tst_missing."""
    MIO.find_textures()
    r = ref(s, "tst_dirt")
    if r is not None and r.status == "AMBIGUOUS":
        idx = next(i for i, c in enumerate(r.candidates) if c.dict_name == "tst_misc_b_txd")
        MIO.choose_texture_source(ref_index=list(s.texture_refs).index(r), candidate_index=idx)
    miss = os.path.join(OUT, "local_dds", "tst_missing.dds")
    os.makedirs(os.path.dirname(miss), exist_ok=True)
    shutil.copy(os.path.join(DDS, "tst_concrete.dds"), miss)
    bpy.data.images["tst_missing"].filepath = miss
    MIO.find_textures()


def test_unused_slots_after_cut():
    """Cas réel signalé : matériaux sans face après découpe, exportés quand même par Sollumz (faux « textures absentes »)."""
    import_scene()
    bld_model = bpy.data.objects["tst_building.model"]
    hi = bld_model.sz_lods.high.mesh
    decal = [i for i, m in enumerate(hi.materials) if m and m.shader_properties.filename == "decal.sps"][0]
    _delete_faces_by_material(hi, decal)
    check("après découpe : le slot décal existe encore sans aucune face",
          decal < len(hi.materials) and not any(p.material_index == decal for p in hi.polygons))
    s = settings("garage_slots", export="export_slots")
    s.collision_root = bpy.data.objects["tst_col"]
    select(bpy.data.objects["tst_building"], bpy.data.objects["tst_ground"])
    MIO.prepare_mapping()
    _complete_textures(s)
    check("tst_decal (slot sans face) non demandée à l'étape 2", ref(s, "tst_decal") is None)
    MIO.update_ytyp()
    MIO.integrate_collision()
    MIO.verify_export()
    st, msg = step(s, "export")
    check("export COMPLET malgré le shader sans face exporté par Sollumz", "Export COMPLET" in msg, msg[:500])
    check("le rapport explique le shader sans face", "sans aucune face" in msg, msg[:500])
    ydr = os.path.join(s.export_dir, "mio_garage_slots.ydr")
    before = verify(ydr)["info"] if os.path.isfile(ydr) else {"shaders": []}
    check("avant nettoyage : Sollumz a bien exporté le shader décal mort",
          "tst_decal" in before.get("referenced_textures", []), before.get("referenced_textures"))
    d = bpy.data.objects["mio_garage_slots"]
    m = [c for c in d.children if c.get("mio_source_asset") == "tst_building"][0]
    faces_before = [m.sz_lods.high.mesh.materials[p.material_index].name for p in m.sz_lods.high.mesh.polygons]
    n_slots = len(m.sz_lods.high.mesh.materials)
    MIO.clean_unused_slots()
    mesh = m.sz_lods.high.mesh
    faces_after = [mesh.materials[p.material_index].name for p in mesh.polygons]
    check("nettoyage : slot inutilisé retiré", len(mesh.materials) == n_slots - 1, (n_slots, len(mesh.materials)))
    check("nettoyage : chaque face garde exactement son matériau", faces_before == faces_after)
    MIO.find_textures()
    MIO.update_ytyp()
    MIO.verify_export()
    st, msg = step(s, "export")
    after = verify(ydr)["info"]
    check("après nettoyage : export COMPLET, plus de shader mort",
          "Export COMPLET" in msg and "sans aucune face" not in msg and len(after["shaders"]) == len(before["shaders"]) - 1,
          (msg[:300], len(before["shaders"]), len(after["shaders"])))
    check("après nettoyage : tst_decal n'est plus référencée", "tst_decal" not in after["referenced_textures"])


def _delete_faces_by_material(mesh, index):
    bm = bmesh.new()
    bm.from_mesh(mesh)
    bmesh.ops.delete(bm, geom=[f for f in bm.faces if f.material_index == index], context="FACES")
    bm.to_mesh(mesh)
    bm.free()


def test_async_driver_and_cancel():
    """Pilote asynchrone (chemin de l'interface : progression, thread, processus séparé) et annulation."""
    import mio_mapping_studio.textures.pipeline as tp
    from mio_mapping_studio import companion
    import_scene()
    s = settings("garage_async", export="export_async")
    s.collision_root = bpy.data.objects["tst_col"]
    select(bpy.data.objects["tst_building"], bpy.data.objects["tst_ground"])
    MIO.prepare_mapping()
    drv = tp.AsyncDriver(tp.run(bpy.context, force_reindex=True))
    drv.start()
    seen = set()
    t0 = time.time()
    while not drv.done and time.time() - t0 < 120:
        drv.tick()
        seen.add(drv.message.split(" ")[0] if drv.message else "")
        time.sleep(0.02)
    check("pilote asynchrone terminé sans erreur", drv.done and drv.error is None, drv.error)
    check("progression rapportée pendant les étapes", len(seen) >= 2, seen)
    check("résultat identique au mode bloquant (14 références)", drv.result and
          drv.result["lines"][0] == "Références nécessaires : 14", drv.result and drv.result["lines"][:2])
    # annulation côté outil : fichier d'annulation présent -> arrêt, l'index existant n'est pas remplacé
    _job, ipath, _ = tp.index_job(bpy.context, force=True)
    before = os.path.getmtime(ipath)
    cancel_file = os.path.join(OUT, "cancel_now")
    open(cancel_file, "w").write("cancel")
    r = subprocess.run([TOOL, "index", "--gta", GTA, "--no-keys", "--out", str(ipath), "--cancel-file", cancel_file],
                       capture_output=True, text=True)
    os.remove(cancel_file)
    res = json.loads([l for l in r.stdout.splitlines() if l.startswith('{"type":"result"')][-1])
    check("annulation : l'outil s'arrête (code 3, « annulée »)", r.returncode == 3 and "annul" in res.get("error", "").lower(),
          (r.returncode, res))
    check("annulation : index existant intact (pas d'index partiel)", os.path.getmtime(ipath) == before and
          not os.path.exists(str(ipath) + ".tmp"))
    # annulation côté addon : un processus long est réellement arrêté
    job = companion.Job(["sleep"], ["30"], "long").start()
    t0 = time.time()
    job.cancel()
    job.poll()
    check("annulation : processus séparé arrêté par l'addon", job.proc.poll() is not None and time.time() - t0 < 10)
    job.cleanup()
    drv = tp.AsyncDriver(tp.index_only(bpy.context))
    drv.start()
    drv.cancel()
    check("annulation depuis l'interface (pilote)", drv.done and "annul" in (drv.error or ""))


class _MockLayout:
    def __init__(self, log, icons):
        self.log, self.icons = log, icons
        self.enabled = self.alert = True
        self.scale_y = 1.0

    def _icon(self, kw):
        ic = kw.get("icon", "NONE")
        if ic not in self.icons:
            self.log.append(f"icône inconnue {ic}")

    def row(self, **kw): return _MockLayout(self.log, self.icons)
    column = box = split = row

    def label(self, text="", **kw):
        self._icon(kw)

    def prop(self, data, prop, **kw):
        if prop not in data.bl_rna.properties:
            self.log.append(f"propriété inconnue {prop}")

    def operator(self, idname, **kw):
        self._icon(kw)
        mod, name = idname.split(".")
        if not hasattr(getattr(bpy.ops, mod), name):
            self.log.append(f"opérateur inconnu {idname}")

        class _P:
            pass
        return _P()

    def progress(self, **kw): pass
    def template_list(self, *a, **kw): pass
    prop_enum = prop


def test_ui_smoke():
    """Interface : chaque panneau s'exécute (layout simulé) avec des icônes, propriétés et opérateurs valides."""
    import mio_mapping_studio.ui as ui
    import_scene()
    s = settings("garage_ui", export="export_ui")
    s.collision_root = bpy.data.objects["tst_col"]
    select(bpy.data.objects["tst_building"], bpy.data.objects["tst_ground"])
    MIO.prepare_mapping()
    MIO.find_textures()
    icons = set(bpy.types.UILayout.bl_rna.functions["label"].parameters["icon"].enum_items.keys())
    log = []

    class Ctx:
        scene = bpy.context.scene
        window_manager = bpy.context.window_manager
        preferences = bpy.context.preferences
        region = None
    for mode in ("STATIC_EMBEDDED", "MLO_LIMBO"):
        s.export_mode = mode
        bpy.context.window_manager.mio_job.running = mode == "MLO_LIMBO"
        for cls in ui.CLASSES:
            if not issubclass(cls, bpy.types.Panel):
                continue
            panel = type("P", (), {})()
            panel.layout = _MockLayout(log, icons)
            try:
                cls.draw(panel, Ctx)
            except Exception as e:
                log.append(f"{cls.__name__}: {type(e).__name__}: {e}")
        for ul in (ui.MIO_UL_texture_refs, ui.MIO_UL_candidates):
            data = s if ul is ui.MIO_UL_texture_refs else s.texture_refs[0]
            items = s.texture_refs if ul is ui.MIO_UL_texture_refs else s.texture_refs[0].candidates
            for i, it in enumerate(items):
                try:
                    ul.draw_item(type("U", (), {})(), Ctx, _MockLayout(log, icons), data, it, 0, data, "", i)
                except Exception as e:
                    log.append(f"{ul.__name__}: {e}")
    bpy.context.window_manager.mio_job.running = False
    enum_icons = []
    from mio_mapping_studio import props
    for items in (props.STATUS_ITEMS, props.REF_STATUS_ITEMS):
        enum_icons += [it[3] for it in items if it[3] not in icons]
    check("panneaux dessinés sans erreur (2 modes, tâche en cours ou non)", not log, log[:10])
    check("icônes des énumérations valides", not enum_icons, enum_icons)


if __name__ == "__main__":
    only = sys.argv[1:]
    tests = [test_static_imported_collision, test_collision_from_visual, test_bvh_split, test_mlo_mode,
             test_invalid_inputs, test_named_collision_and_far_origin, test_unused_slots_after_cut, test_async_driver_and_cancel,
             test_ui_smoke]
    for t in tests:
        if not only or t.__name__ in only:
            run_test(t)
    ok = sum(1 for r in RESULTS if r["ok"])
    print(f"\n{ok}/{len(RESULTS)} vérifications réussies")
    with open(os.path.join(OUT, "test_report.json"), "w", encoding="utf-8") as f:
        json.dump({"blender": bpy.app.version_string, "results": RESULTS}, f, indent=1, ensure_ascii=False)
    sys.stdout.flush()
    # Le module bpy de Blender 4.5 peut rester bloqué à la fermeture de l'interpréteur : sortie explicite.
    os._exit(0 if ok == len(RESULTS) else 1)
