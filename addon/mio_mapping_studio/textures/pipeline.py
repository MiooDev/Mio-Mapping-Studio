"""Pipeline « Trouver les textures GTA et créer le YTD ».

Écrit comme un générateur : le code entre deux `yield` s'exécute dans le thread principal de Blender (accès bpy
autorisé). Les étapes longues sont déléguées :
  ("job", Job)        -> processus MioGtaTool (index RPF, extraction, construction du YTD) ;
  ("thread", fonction) -> calcul pur Python sans bpy (lecture en flux de l'index).
Le même générateur est piloté par l'opérateur modal (progression + annulation) ou par run_sync() (tests).
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import threading
from pathlib import Path

import bpy

from .. import companion, naming, prefs
from .. import sollumz_adapter as sza
from ..hierarchy import find_drawable, mapping_models
from ..sharing import ensure_local_materials
from . import index as tindex
from .refs import analyze, image_state
from .resolve import Resolution, resolve


class PipelineError(RuntimeError):
    pass


def work_dir(asset_name: str) -> Path:
    d = prefs.cache_dir() / "work" / asset_name
    d.mkdir(parents=True, exist_ok=True)
    return d


def texture_cache_file(path: str, name: str) -> Path:
    h = hashlib.sha1(path.lower().encode("utf-8")).hexdigest()[:12]
    return prefs.cache_dir() / "textures" / h / f"{name}.dds"


def _gen9(s) -> bool:
    return s.game_gen == "ENHANCED"


def _validate_gta(s) -> str:
    gta = bpy.path.abspath(s.gta_path)
    if not gta or not os.path.isdir(gta):
        raise PipelineError("Chemin GTA V invalide : indique le dossier d'installation du jeu.")
    exe = "GTA5_Enhanced.exe" if _gen9(s) else "GTA5.exe"
    if not os.path.isfile(os.path.join(gta, exe)) and not os.environ.get("MIO_DEV_NO_KEYS"):
        raise PipelineError(f"{exe} introuvable dans {gta} : vérifie le dossier et la génération (Legacy/Enhanced).")
    return gta


def _common_args(s) -> list[str]:
    args = []
    if _gen9(s):
        args.append("--gen9")
    if os.environ.get("MIO_DEV_NO_KEYS"):
        args.append("--no-keys")  # tests automatisés uniquement (archives non chiffrées)
    return args


def index_job(context, force=False):
    """Retourne (Job ou None, chemin de l'index, état)."""
    s = context.scene.mio_mapping
    cmd = prefs.companion_command(context)
    if not cmd:
        raise PipelineError("Outil compagnon non configuré (Préférences de l'addon > MioGtaTool).")
    gta = _validate_gta(s)
    path = tindex.index_file(prefs.cache_dir(context), gta, _gen9(s), s.index_include_mods, s.index_embedded)
    state, _meta = tindex.index_state(path, gta, s.index_include_mods, _gen9(s))
    if state == "OK" and not force:
        return None, path, state
    args = ["index", "--gta", gta, "--out", str(path)] + _common_args(s)
    if s.index_include_mods:
        args.append("--include-mods")
    if s.index_embedded:
        args.append("--embedded")
    return companion.Job(cmd, args, "index"), path, state


def index_only(context):
    job, path, state = index_job(context, force=True)
    res = yield ("job", job, "Construction de l'index des textures du jeu…")
    return {"index": str(path), "result": res}


def run(context, force_reindex=False):
    scene = context.scene
    s = scene.mio_mapping
    name = s.name_or_error()
    if not name:
        raise PipelineError("Indique un nom de mapping.")
    drawable = find_drawable(s)
    if drawable is None:
        raise PipelineError("Drawable du mapping introuvable : lance d'abord « Préparer le mapping ».")
    models = mapping_models(drawable)
    cmd = prefs.companion_command(context)
    if not cmd:
        raise PipelineError("Outil compagnon non configuré : compile companion/ (build.ps1) et indique MioGtaTool.exe "
                            "dans les préférences de l'addon. Sans lui, impossible de lire les RPF ou d'écrire un YTD "
                            "binaire.")

    yield ("progress", 0.02, "Analyse des matériaux utilisés…")
    refs, notes = analyze(models)
    if not refs:
        s.texture_refs.clear()
        s.ytd_work_path = ""
        s.ytd_size = 0
        s.texture_summary = "Aucune texture référencée par les matériaux utilisés."
        return {"status": "READY", "lines": [s.texture_summary] + notes}

    # Index (construit à la première utilisation, réutilisé ensuite)
    job, ipath, state = index_job(context, force_reindex)
    if job is not None:
        msg = ("Première utilisation : construction de l'index des textures du jeu (une fois)…" if state == "MISSING"
               else "Installation modifiée depuis le dernier index : actualisation…")
        yield ("job", job, msg)

    names = set(refs)
    hashes = {naming.joaat(src) for r in refs.values() for src in r.sources}
    sl = yield ("thread", lambda cancel: tindex.load_slice(ipath, names, hashes, cancel), "Lecture de l'index…")

    # Résolution (choix manuels conservés d'une exécution à l'autre)
    previous = {r.name: r.user_choice for r in s.texture_refs if r.user_choice}
    resolutions: dict[str, Resolution] = {n: resolve(refs[n], sl, previous.get(n, "")) for n in sorted(refs)}

    # Extraction des textures du jeu (cache réutilisé si l'empreinte correspond)
    requests = []
    for n, r in resolutions.items():
        c = r.chosen_candidate
        if r.status != "FOUND" or c is None or c.kind != "GAME":
            continue
        dest = texture_cache_file(c.path, n)
        meta = dest.with_suffix(".json")
        if dest.is_file() and meta.is_file():
            try:
                if json.loads(meta.read_text(encoding="utf-8")).get("hash") == c.data_hash:
                    continue
            except (OSError, json.JSONDecodeError):
                pass
        requests.append({"name": n, "path": c.path, "out": str(dest.relative_to(prefs.cache_dir() / "textures"))})
    extract_errors = {}
    if requests:
        req_file = work_dir(name) / "extract_requests.json"
        req_file.write_text(json.dumps(requests), encoding="utf-8")
        gta = _validate_gta(s)
        job = companion.Job(cmd, ["extract", "--gta", gta, "--requests", str(req_file), "--out",
                                  str(prefs.cache_dir() / "textures")] + _common_args(s), "extract")
        data = yield ("job", job, f"Extraction de {len(requests)} texture(s) d'origine…")
        for it in data.get("items", []):
            if not it.get("ok"):
                extract_errors[it["name"]] = it.get("error", "erreur")

    yield ("progress", 0.85, "Mise à jour des images Blender…")
    wd = work_dir(name)
    manifest = []
    apply_notes = []
    mats_to_unembed = set()
    for n, r in resolutions.items():
        c = r.chosen_candidate
        if r.status != "FOUND" or c is None:
            continue
        ref = refs[n]
        if n in extract_errors:
            r.status = "MISSING"
            r.reason = f"Extraction impossible : {extract_errors[n]}"
            continue
        if c.kind == "SCENE":
            if not s.move_embedded_textures and ref.embedded:
                continue  # reste intégrée au YDR : pas dans le YTD (pas de doublon)
            img = next((bpy.data.images[i] for i in ref.images
                        if bpy.data.images.get(i) and image_state(bpy.data.images[i])[0] == "PACKED_DDS"), None)
            if img is None:
                r.status, r.reason = "MISSING", "Image intégrée introuvable."
                continue
            dest = wd / "embedded" / f"{n}.dds"
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(bytes(img.packed_file.data))
            manifest.append({"name": n, "dds": str(dest)})
            if ref.embedded:
                mats_to_unembed.update(m for m, _node in ref.nodes)
        elif c.kind == "GAME":
            dest = texture_cache_file(c.path, n)
            manifest.append({"name": n, "dds": str(dest), "meta": str(dest.with_suffix(".json"))})
            _reload_images(ref, dest, apply_notes)
            if ref.embedded:
                mats_to_unembed.update(m for m, _node in ref.nodes)
        elif c.kind == "LOCAL":
            manifest.append({"name": n, "dds": c.path})
            if ref.embedded:
                mats_to_unembed.update(m for m, _node in ref.nodes)

    if mats_to_unembed:
        mats = [bpy.data.materials[m] for m in mats_to_unembed if bpy.data.materials.get(m)]
        apply_notes += ensure_local_materials(models, mats)
        moved = 0
        for model in models:
            for mesh in sza.lod_meshes(model).values():
                for mat in mesh.materials:
                    if mat is None or not sza.is_shader_material(mat):
                        continue
                    for _param, node in sza.shader_texture_nodes(mat):
                        tn = sza.texture_name_of_node(node).lower() if node.image else ""
                        if tn in resolutions and any(e["name"] == tn for e in manifest) and sza.is_node_embedded(node):
                            sza.set_node_embedded(node, False)
                            moved += 1
        if moved:
            apply_notes.append(f"{moved} paramètre(s) de texture intégrée basculé(s) vers mio_xxxx.ytd (pas de doublon "
                               "dans le YDR).")

    # Construction du YTD binaire
    ytd_path = wd / f"{name}.ytd"
    s.ytd_work_path = ""
    s.ytd_size = 0
    built = None
    if manifest:
        man_file = wd / "ytd_manifest.json"
        man_file.write_text(json.dumps({"name": name, "textures": manifest}), encoding="utf-8")
        args = ["build-ytd", "--manifest", str(man_file), "--out", str(ytd_path)]
        job = companion.Job(cmd, args, "build-ytd")
        built = yield ("job", job, f"Construction de {name}.ytd ({len(manifest)} textures)…")
        s.ytd_work_path = str(ytd_path)
        s.ytd_size = int(built.get("size", 0))
        for w in built.get("warnings", []):
            apply_notes.append("YTD : " + w)
        images = []
        for e in manifest:
            for iname in refs[e["name"]].images:
                img = bpy.data.images.get(iname)
                if img is not None and image_state(img)[0] in ("PACKED_DDS", "FILE_DDS") and img not in images:
                    images.append(img)
                    break
        sza.ensure_scene_txd(scene, name, images)
    elif ytd_path.exists():
        ytd_path.unlink()

    # Mise à jour de l'interface
    s.texture_refs.clear()
    for n, r in resolutions.items():
        item = s.texture_refs.add()
        item.name = n
        item.status = r.status
        item.reason = r.reason
        item.used_by = ", ".join(sorted({f"{u.material}:{u.param}" for u in refs[n].uses}))[:400]
        item.sources = ", ".join(sorted(refs[n].sources))[:200]
        item.user_choice = previous.get(n, "")
        for c in r.candidates:
            ci = item.candidates.add()
            ci.kind, ci.path, ci.dict_name = c.kind, c.path, c.dict_name
            ci.width, ci.height, ci.fmt, ci.mips = c.width, c.height, c.fmt, c.mips
            ci.priority, ci.data_hash, ci.note = c.priority, c.data_hash, c.note
        item.chosen = r.chosen
        if r.status == "FOUND" and r.chosen_candidate is not None:
            cc = r.chosen_candidate
            item.dds_path = str(texture_cache_file(cc.path, n)) if cc.kind == "GAME" else (
                cc.path if cc.kind == "LOCAL" else str(wd / "embedded" / f"{n}.dds"))

    counts = {k: sum(1 for r in resolutions.values() if r.status == k) for k in ("FOUND", "AMBIGUOUS", "MISSING", "INVALID")}
    fallback = sum(1 for r in resolutions.values() if r.status == "FOUND" and r.chosen_candidate.kind == "LOCAL")
    in_ytd = len(manifest)
    lines = [
        f"Références nécessaires : {len(resolutions)}",
        f"Trouvées : {counts['FOUND']} (dont {fallback} en mode secours DDS local)",
        f"Ambiguës : {counts['AMBIGUOUS']}",
        f"Manquantes : {counts['MISSING'] + counts['INVALID']}",
        f"Dans {name}.ytd : {in_ytd} texture(s), {s.ytd_size / 1024:.1f} Kio" if built else "Aucun YTD construit.",
    ]
    s.texture_summary = " | ".join(lines)
    status = "READY"
    if counts["AMBIGUOUS"] or fallback:
        status = "WARNING"
    if counts["MISSING"] or counts["INVALID"]:
        status = "ERROR"
    if counts["MISSING"] or counts["INVALID"] or counts["AMBIGUOUS"]:
        lines.append("Export incomplet tant que des textures sont manquantes ou ambiguës.")
    if sl is not None and sl.errors:
        lines.append(f"{sl.errors} fichier(s) du jeu illisibles pendant l'indexation (voir l'index).")
    return {"status": status, "lines": lines + notes + apply_notes}


def _reload_images(ref, dds_path: Path, notes: list):
    """Recharge les images de la référence depuis le DDS d'origine, sans modifier les matériaux ni les UV.
    Le nom de fichier est conservé (« nom.dds ») : le nom de texture exporté par Sollumz ne change pas."""
    for iname in ref.images:
        img = bpy.data.images.get(iname)
        if img is None or img.packed_file is not None:
            continue
        current = bpy.path.abspath(img.filepath) if img.filepath else ""
        if current and os.path.normcase(os.path.abspath(current)) == os.path.normcase(str(dds_path)) and \
                img.source == "FILE":
            continue
        img.source = "FILE"
        img.filepath = str(dds_path)
        try:
            img.reload()
        except RuntimeError:
            notes.append(f"Blender ne sait pas afficher {dds_path.name} (format DDS), mais le fichier d'origine est "
                         "bien utilisé pour le YTD.")


# --------------------------------------------------------------------------------------------------------------------
# Pilotes
# --------------------------------------------------------------------------------------------------------------------

def run_sync(gen):
    """Exécute le générateur en bloquant (tests automatisés, mode arrière-plan sans boucle d'événements)."""
    value = None
    exc = None
    while True:
        try:
            step = gen.throw(exc) if exc is not None else gen.send(value)
        except StopIteration as e:
            return e.value
        exc = None
        value = None
        kind = step[0]
        if kind == "job":
            job = step[1].start()
            try:
                value = job.wait(timeout=None)
            except companion.CompanionError as e:
                exc = e
            finally:
                job.cleanup()
        elif kind == "thread":
            value = step[1](lambda: False)


class AsyncDriver:
    """Pilotage non bloquant par un opérateur modal (appelé sur événement TIMER, thread principal)."""

    def __init__(self, gen):
        self.gen = gen
        self.job = None
        self.thread = None
        self.thread_result = None
        self.thread_error = None
        self.message = ""
        self.progress = 0.0
        self.done = False
        self.result = None
        self.error = None
        self._cancel = False

    def _advance(self, value=None, exc=None):
        try:
            step = self.gen.throw(exc) if exc is not None else self.gen.send(value)
        except StopIteration as e:
            self.done = True
            self.result = e.value
            return
        except (PipelineError, companion.CompanionError, InterruptedError) as e:
            self.done = True
            self.error = str(e)
            return
        kind = step[0]
        if kind == "progress":
            self.progress, self.message = step[1], step[2]
            self._advance(None)
        elif kind == "job":
            self.job = step[1]
            self.message = step[2] if len(step) > 2 else ""
            try:
                self.job.start()
            except companion.CompanionError as e:
                self.job = None
                self._advance(exc=e)
        elif kind == "thread":
            fn = step[1]
            self.message = step[2] if len(step) > 2 else ""

            def target():
                try:
                    self.thread_result = fn(lambda: self._cancel)
                except BaseException as e:  # remonté au thread principal
                    self.thread_error = e
            self.thread = threading.Thread(target=target, daemon=True)
            self.thread.start()

    def start(self):
        self._advance(None)

    def tick(self):
        if self.done:
            return
        if self.job is not None:
            finished = self.job.poll()
            done, total, msg = self.job.progress
            if total:
                self.progress = done / total
            if msg:
                self.message = msg
            if finished:
                job, self.job = self.job, None
                try:
                    value = job.checked_result()
                except companion.CompanionError as e:
                    job.cleanup()
                    self._advance(exc=e)
                    return
                job.cleanup()
                self._advance(value)
        elif self.thread is not None and not self.thread.is_alive():
            self.thread = None
            if self.thread_error is not None:
                err, self.thread_error = self.thread_error, None
                self._advance(exc=err if isinstance(err, Exception) else RuntimeError(str(err)))
            else:
                self._advance(self.thread_result)

    def cancel(self):
        self._cancel = True
        if self.job is not None:
            self.job.cancel()
            self.job.poll()
            self.job.cleanup()
            self.job = None
        self.done = True
        self.error = "Opération annulée par l'utilisateur."
