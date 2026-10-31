"""Étape 6 : vérification et export.

1. Diagnostic complet ; toute erreur bloquante arrête avant d'écrire quoi que ce soit.
2. Export Sollumz dans un dossier temporaire (NATIF si PyMateria est disponible, sinon XML CodeWalker compilé en
   binaire par MioGtaTool/CodeWalker.Core : un XML n'est jamais renommé en binaire).
3. Relecture des binaires avec CodeWalker.Core : collision intégrée réellement présente, alignement collision/visuel,
   textures référencées présentes dans le YTD, archetypes cohérents et références vers des fichiers exportés.
4. Seulement si tout est valide : remplacement de l'export existant (l'ancien est sauvegardé dans .mio_backup).
Cible : GTA V Legacy / FiveM (Gen8).
"""

from __future__ import annotations

import json
import os
import shutil
import time
from pathlib import Path

import bpy
import numpy as np

from . import companion, diagnostics, fivem, naming, prefs
from . import sollumz_adapter as sza
from .hierarchy import StepResult, find_drawable
from .ytyp_tools import collision_bounds, drawable_space_bounds, update_base_archetype, configure_mlo

BLOCKING_STEPS = ("prepare", "ytyp", "mlo", "collision", "export")


def expected_files(s) -> list[str]:
    name = s.name_or_error() or "mio_xxxx"
    col = naming.collision_name(name)
    files = [f"{name}.ydr", f"{name}.ytd", f"{name}.ytyp"]
    if s.export_mode == "MLO_LIMBO":
        files.insert(2, f"{col}.ybn")
        files.append(f"{name}.ymap")
    elif s.generate_ymap:
        files.append(f"{name}.ymap")
    return files


def _tol(box) -> float:
    ext = float(np.max(np.asarray(box[1]) - np.asarray(box[0]))) if box is not None else 0.0
    return 0.01 + 2e-4 * ext


def _box_close(a, b, tol) -> bool:
    return bool(np.all(np.abs(np.asarray(a[0]) - np.asarray(b[0])) <= tol) and
                np.all(np.abs(np.asarray(a[1]) - np.asarray(b[1])) <= tol))


def _fmt_box(b) -> str:
    return "min " + str(tuple(round(float(v), 3) for v in b[0])) + " max " + str(tuple(round(float(v), 3) for v in b[1]))


def _bound_geometry_box(info):
    """AABB de toute la géométrie de collision relue (repère de l'asset)."""
    if info is None:
        return None
    box = None
    if info.get("geometry_min") is not None and info.get("vertices", 0) > 0:
        box = (np.array(info["geometry_min"]), np.array(info["geometry_max"]))
    for c in info.get("children", []):
        sub = _bound_geometry_box(c["bound"])
        if sub is not None:
            box = sub if box is None else (np.minimum(box[0], sub[0]), np.maximum(box[1], sub[1]))
    return box


def _inconsistent_boxes(info, path="") -> list[str]:
    """Géométries dont la boîte englobante (utilisée par la physique) ne contient pas les sommets."""
    if info is None:
        return []
    out = [path or "racine"] if info.get("box_consistent") is False else []
    for c in info.get("children", []):
        out += _inconsistent_boxes(c["bound"], f"{path}/{c['index']}")
    return out


def _count_bound_children(info) -> int:
    return len(info.get("children", [])) if info else 0


def _compile(cmd, xml_path: Path, res: StepResult) -> Path | None:
    try:
        data = companion.run(cmd, ["xml2bin", "--in", str(xml_path)], timeout=600, label="xml2bin")
    except companion.CompanionError as e:
        res.errors.append(f"Compilation de {xml_path.name} impossible : {e}")
        return None
    return Path(data["output"])


def _verify(cmd, files: list[Path], res: StepResult, names=()) -> dict:
    args = ["verify"]
    if names:
        args += ["--names", ",".join(names)]
    for f in files:
        args += ["--file", str(f)]
    try:
        data = companion.run(cmd, args, timeout=600, label="verify")
    except companion.CompanionError as e:
        res.errors.append(f"Relecture impossible : {e}")
        return {}
    out = {}
    for item in data.get("files", []):
        key = Path(item["file"]).name
        if not item.get("ok"):
            res.errors.append(f"{key} illisible par CodeWalker.Core : {item.get('error')}")
        out[key] = item.get("info")
    return out


def run(context, allow_incomplete: bool = False, dry_run: bool = False) -> StepResult:
    s = context.scene.mio_mapping
    res = StepResult()
    name = s.name_or_error()
    colname = naming.collision_name(name)

    diag = diagnostics.refresh(context)
    for k in BLOCKING_STEPS:
        st = diagnostics.status_of(diag[k])
        if diag[k].errors:
            res.errors += [f"[{k}] {e}" for e in diag[k].errors]
        elif st == "TODO" and not (k == "export" and not s.last_report):
            res.errors.append(f"[{k}] étape pas encore réalisée.")
    tex = diag["textures"]
    incomplete = bool(tex.errors) or any(r.status == "AMBIGUOUS" for r in s.texture_refs)
    if diagnostics.status_of(tex) == "TODO":
        res.errors.append("[textures] étape 2 pas encore réalisée.")
    if incomplete and not allow_incomplete:
        res.errors.append("Textures manquantes ou ambiguës : l'export serait incomplet. Corrige l'étape 2 ou coche "
                          "« Exporter même si incomplet ».")
    if res.errors:
        return res
    if dry_run:
        res.infos.append("Vérification préalable OK : rien n'a été écrit.")
        res.infos.append("Fichiers prévus : " + ", ".join(expected_files(s)))
        return res

    cmd = prefs.companion_command(context)
    native = sza.native_export_available()
    drawable = find_drawable(s)
    col = s.collision_root
    export_dir = Path(bpy.path.abspath(s.export_dir))
    export_dir.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d_%H%M%S")
    staging = export_dir / f".mio_staging_{name}_{stamp}"
    staging.mkdir(parents=True)
    res.infos.append(f"Dossier temporaire : {staging}")

    # 1. YDR (+ YBN en mode MLO)
    objs = [drawable] + ([col] if s.export_mode == "MLO_LIMBO" else [])
    ok, msgs = sza.export_assets(context, str(staging), objects=objs, native=native)
    for lvl, m in msgs:
        if lvl in ("WARNING", "ERROR"):
            (res.errors if lvl == "ERROR" else res.warnings).append(f"Sollumz : {m}")
    if not ok:
        res.errors.append("L'export Sollumz du modèle a échoué.")
        return res
    ydr = staging / f"{name}.ydr"
    ybn = staging / f"{colname}.ybn"
    if not native:
        if not (staging / f"{name}.ydr.xml").is_file():
            res.errors.append(f"Sollumz n'a pas produit {name}.ydr.xml.")
            return res
        _compile(cmd, staging / f"{name}.ydr.xml", res)
        if s.export_mode == "MLO_LIMBO":
            _compile(cmd, staging / f"{colname}.ybn.xml", res)
        if res.errors:
            return res
    if not ydr.is_file():
        res.errors.append(f"{ydr.name} absent après export.")
        return res

    files = [ydr] + ([ybn] if s.export_mode == "MLO_LIMBO" else [])
    info = _verify(cmd, files, res)
    if res.errors:
        return res
    ydr_info = info.get(ydr.name) or {}

    # 2. Contrôles du YDR
    expected_visual = drawable_space_bounds(drawable, include_collision=False)
    got_visual = (np.array(ydr_info["bb_min"]), np.array(ydr_info["bb_max"]))
    if expected_visual is not None and not _box_close(expected_visual, got_visual, _tol(expected_visual)):
        res.warnings.append(f"Bounds visuels relus ({_fmt_box(got_visual)}) différents de la géométrie Blender "
                            f"({_fmt_box(expected_visual)}).")
    bound = ydr_info.get("bound")
    exported_box = got_visual
    inv = drawable.matrix_world.inverted()
    if s.export_mode == "STATIC_EMBEDDED":
        if bound is None:
            res.errors.append(f"{ydr.name} ne contient AUCUNE collision intégrée alors que le mode l'exige.")
            return res
        if bound.get("type") != "Composite":
            res.errors.append(f"Collision intégrée de type {bound.get('type')} au lieu de Composite.")
        nchild = len([c for c in col.children if sza.is_bound_root_child(c)])
        if _count_bound_children(bound) != nchild:
            res.errors.append(f"Collision relue : {_count_bound_children(bound)} élément(s) au lieu de {nchild}.")
        bad = _inconsistent_boxes(bound)
        if bad:
            res.errors.append(f"Boîte englobante de collision incohérente avec ses sommets ({', '.join(bad)}).")
        got_col = _bound_geometry_box(bound)
        exp_col = collision_bounds(col, inv)
        if got_col is None or exp_col is None:
            res.errors.append("Géométrie de collision vide dans le YDR.")
        elif not _box_close(exp_col, got_col, _tol(exp_col)):
            res.errors.append(f"Collision désalignée : relue {_fmt_box(got_col)}, attendue {_fmt_box(exp_col)} "
                              "(repère du Drawable).")
        else:
            res.infos.append(f"Collision intégrée relue et alignée avec le visuel ({_fmt_box(got_col)}).")
            exported_box = (np.minimum(got_visual[0], got_col[0]), np.maximum(got_visual[1], got_col[1]))
    else:
        if bound is not None:
            res.errors.append(f"{ydr.name} contient une collision intégrée : doublon avec {ybn.name}.")
        ybn_info = info.get(ybn.name) or {}
        bad = _inconsistent_boxes(ybn_info.get("bound"))
        if bad:
            res.errors.append(f"{ybn.name} : boîte englobante incohérente avec les sommets ({', '.join(bad)}).")
        got_col = _bound_geometry_box(ybn_info.get("bound"))
        exp_col = collision_bounds(col, col.matrix_world.inverted())
        if got_col is None or exp_col is None or not _box_close(exp_col, got_col, _tol(exp_col)):
            res.errors.append(f"Collision {ybn.name} vide ou désalignée.")
        else:
            res.infos.append(f"{ybn.name} relu et aligné ({_fmt_box(got_col)}, repère du MLO).")
    if res.errors:
        return res

    # 3. YTD
    ytd = staging / f"{name}.ytd"
    ytd_textures = set()
    if s.ytd_work_path and os.path.isfile(s.ytd_work_path):
        shutil.copy2(s.ytd_work_path, ytd)
        yinfo = _verify(cmd, [ytd], res).get(ytd.name) or {}
        ytd_textures = {t["name"] for t in yinfo.get("textures", [])}
    referenced = set(ydr_info.get("referenced_textures", []))
    embedded = set(ydr_info.get("embedded_textures", []))
    dup = ytd_textures & embedded
    if dup:
        res.warnings.append(f"Textures à la fois intégrées au YDR et dans le YTD : {', '.join(sorted(dup))}.")
    missing_tex = sorted(referenced - ytd_textures - embedded)
    if missing_tex:
        incomplete = True
        (res.warnings if allow_incomplete else res.errors).append(
            f"Textures référencées par le YDR absentes du YTD : {', '.join(missing_tex)}.")
        if not allow_incomplete:
            return res

    # 4. YTYP : bounds = géométrie réellement exportée (visuel + collision intégrée)
    r = update_base_archetype(context, s, exported_bounds=exported_box if s.export_mode == "STATIC_EMBEDDED" else got_visual)
    if s.export_mode == "STATIC_EMBEDDED":
        if bound is not None:
            _, ytyp = sza.find_ytyp(context.scene, name)
            _, arch = sza.find_archetype(ytyp, name)
            arch.physics_dictionary = name
        if not ytd_textures:
            _, ytyp = sza.find_ytyp(context.scene, name)
            _, arch = sza.find_archetype(ytyp, name)
            arch.texture_dictionary = ""
    else:
        r.extend(configure_mlo(context, s))
    res.errors += r.errors
    if res.errors:
        return res
    yidx, _ = sza.find_ytyp(context.scene, name)
    ok, msgs = sza.export_assets(context, str(staging), objects=(), ytyp_index=yidx, native=native)
    for lvl, m in msgs:
        if lvl in ("WARNING", "ERROR"):
            (res.errors if lvl == "ERROR" else res.warnings).append(f"Sollumz (YTYP) : {m}")
    ytyp_file = staging / f"{name}.ytyp"
    if not native:
        _compile(cmd, staging / f"{name}.ytyp.xml", res)
    if not ok or not ytyp_file.is_file():
        res.errors.append("Export du YTYP impossible.")
        return res
    tinfo = _verify(cmd, [ytyp_file], res, names=(name, colname, "limbo")).get(ytyp_file.name) or {}
    exported = {p.name for p in staging.iterdir() if p.suffix in (".ydr", ".ybn", ".ytd")}
    for a in tinfo.get("archetypes", []):
        kind = a.get("kind")
        if kind == "CBaseArchetypeDef":
            if f"{a['asset_name']}.ydr" not in exported:
                res.errors.append(f"Archetype {a['name']} : asset {a['asset_name']}.ydr non exporté.")
            if a["texture_dictionary"] and f"{a['texture_dictionary']}.ytd" not in exported:
                res.errors.append(f"Archetype {a['name']} : dictionnaire {a['texture_dictionary']}.ytd non exporté.")
            if a["physics_dictionary"]:
                if s.export_mode != "STATIC_EMBEDDED" or a["physics_dictionary"] != a["asset_name"] or bound is None:
                    res.errors.append(f"Archetype {a['name']} : Physics Dictionary « {a['physics_dictionary']} » sans "
                                      "collision intégrée correspondante dans le YDR.")
            elif s.export_mode == "STATIC_EMBEDDED":
                res.errors.append(f"Archetype {a['name']} : Physics Dictionary vide malgré la collision intégrée.")
            if a["asset_type"] != "ASSET_TYPE_DRAWABLE":
                res.errors.append(f"Archetype {a['name']} : Asset Type {a['asset_type']}.")
        elif kind == "CMloArchetypeDef":
            if s.export_mode != "MLO_LIMBO":
                res.errors.append(f"Archetype MLO {a['name']} exporté en mode statique.")
            elif f"{a['name']}.ybn" not in exported:
                res.errors.append(f"Archetype MLO {a['name']} : collision {a['name']}.ybn non exportée.")
            mlo = a.get("mlo") or {}
            rooms = mlo.get("rooms") or []
            if not rooms or rooms[0]["name"] != "limbo" or 0 not in (rooms[0].get("attached") or []):
                res.errors.append("MLO : room limbo absente ou entité non attachée.")
            ents = [e["archetype"] for e in (mlo.get("entities") or [])]
            if name not in ents:
                res.errors.append(f"MLO : entité {name} absente.")
            for e in ents:
                if f"{e}.ydr" not in exported:
                    res.errors.append(f"MLO : l'entité {e} référence un asset non exporté.")
    if res.errors:
        return res
    res.infos.append(f"{ytyp_file.name} relu : " + ", ".join(f"{a['name']} ({a['kind'].replace('Def', '')})"
                                                      for a in tinfo.get("archetypes", [])))

    # 5. YMAP de placement
    if s.export_mode == "MLO_LIMBO" or s.generate_ymap:
        ymap = staging / f"{name}.ymap"
        if s.export_mode == "MLO_LIMBO":
            pos = col.matrix_world.translation
            ent = {"archetype": colname, "position": [pos.x, pos.y, pos.z], "rotation": [0, 0, 0, 1], "flags": 0,
                   "lod_dist": s.lod_dist, "mlo": True}
        else:
            pos = drawable.matrix_world.translation
            ent = {"archetype": name, "position": [pos.x, pos.y, pos.z], "rotation": [0, 0, 0, 1],
                   "flags": 32, "lod_dist": s.lod_dist, "mlo": False}
        spec = staging / "ymap_spec.json"
        spec.write_text(json.dumps({"name": name, "entities": [ent]}), encoding="utf-8")
        try:
            companion.run(cmd, ["make-ymap", "--spec", str(spec), "--ytyp", str(ytyp_file), "--out", str(ymap)],
                          timeout=300, label="make-ymap")
        except companion.CompanionError as e:
            res.errors.append(f"YMAP impossible : {e}")
            return res
        minfo = _verify(cmd, [ymap], res, names=(name, colname)).get(ymap.name) or {}
        res.infos.append(f"{ymap.name} relu : {len(minfo.get('entities', []))} entité(s) à "
                         f"{tuple(round(v, 3) for v in (pos.x, pos.y, pos.z))}.")
        spec.unlink()
    if res.errors:
        return res

    # 6. Remplacement de l'export existant (seulement après validation complète)
    deliver = [p for p in (staging / f for f in expected_files(s)) if p.is_file()]
    dest = export_dir
    if s.generate_fivem:
        rname = naming.normalize_mapping_name(s.fivem_resource_name) if s.fivem_resource_name else name
        dest = export_dir / rname / "stream"
    dest.mkdir(parents=True, exist_ok=True)
    backup = export_dir / ".mio_backup" / stamp
    for p in deliver:
        target = dest / p.name
        if target.exists():
            backup.mkdir(parents=True, exist_ok=True)
            shutil.move(str(target), str(backup / p.name))
        shutil.move(str(p), str(target))
    if backup.exists():
        res.infos.append(f"Ancien export sauvegardé dans {backup}.")
    if s.generate_fivem:
        fivem.write_resource(dest.parent, name, [p.name for p in deliver], s.export_mode)
        res.infos.append(f"Ressource FiveM : {dest.parent} (fxmanifest.lua + stream/).")
    shutil.rmtree(staging, ignore_errors=True)

    status = "INCOMPLET" if incomplete else "COMPLET"
    res.infos.insert(0, f"Export {status} : " + ", ".join(p.name for p in deliver) + f" -> {dest}")
    if incomplete:
        res.warnings.append("Export INCOMPLET : textures manquantes/ambiguës (voir étape 2).")
    res.infos.append(fivem.placement_notes(s.export_mode, s.generate_ymap or s.export_mode == "MLO_LIMBO"))
    report = "\n".join(res.lines())
    s.last_report = report
    try:
        (export_dir / f"{name}_rapport.txt").write_text(report, encoding="utf-8")
    except OSError:
        pass
    return res
