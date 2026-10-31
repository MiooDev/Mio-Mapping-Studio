"""Diagnostic en lecture seule de chaque étape (aucune modification de la scène)."""

from __future__ import annotations

import os
import time

import bpy

from . import geom, naming, prefs
from . import sollumz_adapter as sza
from .collision import validate_collision_root
from .hierarchy import (StepResult, find_drawable, find_named_collision, mapping_models, origin_far_from_geometry,
                        validate_models)

STEP_KEYS = ("prepare", "textures", "ytyp", "mlo", "collision", "export")


def check_prepare(context, s) -> StepResult:
    res = StepResult()
    name = s.name_or_error()
    if not name:
        res.errors.append("Nom du mapping vide.")
        return res
    d = find_drawable(s)
    if d is None:
        res.status_override = "TODO"
        res.infos.append(f"Drawable « {name} » pas encore préparé.")
        return res
    if d.name != name:
        res.errors.append(f"Le Drawable s'appelle « {d.name} » au lieu de « {name} ».")
    models = mapping_models(d)
    if not models:
        res.errors.append(f"« {d.name} » n'a aucun Drawable Model.")
    validate_models(models, res)
    nested = [o.name for o in d.children_recursive if sza.is_drawable(o)]
    if nested:
        res.errors.append(f"Drawables imbriqués (invalides) : {', '.join(nested)}.")
    if geom.has_rotation_or_scale(d.matrix_world):
        res.errors.append(f"« {d.name} » a une rotation ou une échelle : non pris en charge pour le placement.")
    bad = geom.find_identity_world_descendants(d)
    if bad:
        res.errors.append(f"{len(bad)} objet(s) sous « {d.name} » ont une matrice monde identité et seraient exportés "
                          "décalés par Sollumz : relance « Préparer le mapping ».")
    if not res.errors:
        res.infos.append(f"« {d.name} » : {len(models)} modèle(s), origine {tuple(round(v, 3) for v in d.matrix_world.translation)}.")
    far = origin_far_from_geometry(d)
    if far > 0:
        res.warnings.append(f"L'origine de « {d.name} » est à {far:.0f} m de sa géométrie : la distance d'affichage (LOD) "
                            "est mesurée depuis l'origine, le mapping risque de ne pas apparaître en jeu. Relance "
                            "« Préparer le mapping » avec l'origine « Centre du mapping (bas) ».")
    col = s.collision_root
    named = find_named_collision(s)
    if col is None and named is not None:
        res.warnings.append(f"La collision « {named.name} » existe mais n'est pas désignée : clique « Utiliser "
                            f"{named.name} » (étape 1) ou mets-la dans « Objet racine collision ».")
    elif col is None:
        res.warnings.append("Aucune collision : désigne la collision importée ou crée-la depuis le mapping.")
    else:
        vr = validate_collision_root(col)
        res.errors += vr.errors
        res.warnings += vr.warnings
    return res


def check_textures(context, s) -> StepResult:
    res = StepResult()
    refs = list(s.texture_refs)
    if not refs and not s.texture_summary:
        res.status_override = "TODO"
        res.infos.append("Textures pas encore recherchées.")
        return res
    miss = [r.name for r in refs if r.status in ("MISSING", "INVALID")]
    amb = [r.name for r in refs if r.status == "AMBIGUOUS"]
    if miss:
        res.errors.append(f"{len(miss)} texture(s) manquante(s) : {', '.join(miss[:8])}{'…' if len(miss) > 8 else ''}.")
    if amb:
        res.warnings.append(f"{len(amb)} texture(s) ambiguë(s) : choisis la source dans la liste puis relance.")
    fallback = [r.name for r in refs if r.status == "FOUND" and 0 <= r.chosen < len(r.candidates)
                and r.candidates[r.chosen].kind == "LOCAL"]
    if fallback:
        res.warnings.append(f"{len(fallback)} texture(s) en mode secours (DDS local, pas trouvées dans le jeu).")
    if s.ytd_work_path and not os.path.isfile(s.ytd_work_path):
        res.errors.append("Le YTD construit n'existe plus dans le cache : relance l'étape 2.")
    if s.texture_summary:
        res.infos.append(s.texture_summary)
    return res


def check_ytyp(context, s) -> StepResult:
    res = StepResult()
    name = s.name_or_error()
    _, ytyp = sza.find_ytyp(context.scene, name) if name else (None, None)
    if ytyp is None:
        res.status_override = "TODO"
        res.infos.append(f"{name}.ytyp pas encore créé.")
        return res
    bases = [a for a in ytyp.archetypes if a.name.lower() == name and sza.archetype_kind(a) == "BASE"]
    if not bases:
        res.status_override = "TODO"
        res.infos.append(f"Archetype Base « {name} » absent.")
        return res
    if len(bases) > 1:
        res.errors.append(f"{len(bases)} archetypes « {name} » : doublons (relance « Créer / mettre à jour »).")
    a = bases[0]
    if a.asset_name.lower() != name:
        res.errors.append(f"Asset Name = « {a.asset_name} » au lieu de « {name} ».")
    if a.asset_type != sza.asset_type_value("DRAWABLE"):
        res.errors.append("Asset Type doit être Drawable.")
    has_ytd = bool(s.ytd_work_path)
    if has_ytd and a.texture_dictionary.lower() != name:
        res.errors.append(f"Texture Dictionary = « {a.texture_dictionary} » au lieu de « {name} ».")
    if not has_ytd and a.texture_dictionary:
        res.errors.append(f"Texture Dictionary « {a.texture_dictionary} » mais aucun YTD construit.")
    d = find_drawable(s)
    embedded = d is not None and any(sza.is_composite(c) for c in d.children)
    if s.export_mode == "STATIC_EMBEDDED":
        if embedded and a.physics_dictionary.lower() != name:
            res.errors.append(f"Physics Dictionary doit valoir « {name} » (collision intégrée).")
        if not embedded and a.physics_dictionary:
            res.errors.append("Physics Dictionary renseigné alors que la collision n'est pas intégrée au YDR.")
        if not embedded:
            res.warnings.append("Collision pas encore intégrée (étape 5).")
        for x in ytyp.archetypes:
            if sza.archetype_kind(x) == "MLO":
                res.errors.append(f"Archetype MLO « {x.name} » présent en mode statique : il référencerait {x.name}.ybn "
                                  "qui ne sera pas exporté. Retire-le.")
    else:
        if a.physics_dictionary:
            res.errors.append("Mode MLO : Physics Dictionary doit être vide (collision dans le YBN du MLO).")
    if tuple(a.bb_min) == tuple(a.bb_max):
        res.errors.append("Bounds de l'archetype non calculés.")
    if not res.errors:
        res.infos.append(f"Archetype Base « {name} » : txd « {a.texture_dictionary or '-'} », physics « "
                         f"{a.physics_dictionary or '-'} », rayon {a.bs_radius:.2f} m.")
    return res


def check_mlo(context, s) -> StepResult:
    res = StepResult()
    name = s.name_or_error()
    colname = naming.collision_name(name) if name else ""
    _, ytyp = sza.find_ytyp(context.scene, name) if name else (None, None)
    if s.export_mode == "STATIC_EMBEDDED":
        res.status_override = "NA"
        res.infos.append("Mode statique : aucun MLO. La collision est intégrée au YDR (pas de mio_xxxx_col).")
        if ytyp is not None and any(sza.archetype_kind(a) == "MLO" for a in ytyp.archetypes):
            res.status_override = None
            res.errors.append("Un archetype MLO est présent dans le YTYP : incohérent en mode statique.")
        return res
    if ytyp is None:
        res.status_override = "TODO"
        return res
    _, mlo = sza.find_archetype(ytyp, colname)
    if mlo is None or sza.archetype_kind(mlo) != "MLO":
        res.status_override = "TODO"
        res.infos.append(f"Archetype MLO « {colname} » pas encore configuré.")
        return res
    col = s.collision_root
    if mlo.asset is None or mlo.asset != col or col is None or col.name != colname:
        res.errors.append(f"L'archetype MLO doit être relié au Bound Composite « {colname} » (exporté en {colname}.ybn).")
    rooms = [r for r in mlo.rooms if r.name == "limbo"]
    if not rooms:
        res.errors.append("Room « limbo » absente.")
    else:
        r = rooms[0]
        if any(r.bb_min[i] >= r.bb_max[i] for i in range(3)):
            res.errors.append("Bounds de la room limbo invalides.")
        ents = [e for e in mlo.entities if e.archetype_name.lower() == name]
        if not ents:
            res.errors.append(f"Entité « {name} » absente du MLO.")
        elif ents[0].attached_room_id != str(r.id):
            res.errors.append(f"L'entité « {name} » n'est pas attachée à la room limbo.")
    if len(mlo.rooms) > 1:
        res.warnings.append("Plusieurs rooms : limbo seul n'automatise pas un vrai intérieur (rooms/portals manuels).")
    if not res.errors:
        res.infos.append(f"MLO « {colname} » : room limbo + entité {name} ; collision {colname}.ybn.")
    return res


def check_collision(context, s) -> StepResult:
    res = StepResult()
    d = find_drawable(s)
    col = s.collision_root
    if d is None or col is None:
        res.status_override = "TODO"
        res.infos.append("Collision et/ou Drawable pas encore prêts.")
        return res
    validate_collision_root(col, res)
    if s.export_mode == "STATIC_EMBEDDED":
        if col.parent is not d:
            res.status_override = "TODO" if not res.errors else None
            res.infos.append("Collision pas encore intégrée au Drawable.")
        else:
            others = [c.name for c in d.children if sza.is_bound(c) and c is not col]
            if others:
                res.errors.append(f"Plusieurs collisions sous le Drawable ({', '.join(others)}) : Sollumz n'en exporte "
                                  "qu'une.")
            if geom.find_identity_world_descendants(col):
                res.errors.append("Des objets de collision seraient exportés décalés : relance l'intégration.")
            if not res.errors:
                res.infos.append(f"« {col.name} » intégré à « {d.name} » (collision embedded du YDR).")
    else:
        if col.parent is not None:
            res.errors.append("Mode MLO : la collision doit rester séparée (fichier YBN).")
        if any(sza.is_bound(c) for c in d.children):
            res.errors.append("Mode MLO : le Drawable contient une collision intégrée (doublon).")
        if (col.matrix_world.translation - d.matrix_world.translation).length > 1e-4:
            res.errors.append("Origine de la collision différente de celle du Drawable : lance l'étape 5.")
        if not res.errors:
            res.infos.append(f"« {col.name} » séparé et aligné : exporté en {col.name}.ybn.")
    return res


def check_export(context, s) -> StepResult:
    res = StepResult()
    ok, msg = sza.status()
    if not ok:
        res.errors.append(msg)
    if not s.export_dir:
        res.errors.append("Dossier d'export non défini.")
    elif not os.path.isdir(bpy.path.abspath(s.export_dir)):
        res.warnings.append("Le dossier d'export n'existe pas encore : il sera créé.")
    cmd = prefs.companion_command(context)
    if not cmd:
        res.errors.append("Outil compagnon non configuré : nécessaire pour le YTD binaire et la relecture des fichiers.")
    if ok and not sza.native_export_available():
        res.infos.append("PyMateria absent : Sollumz exporte en XML CodeWalker, compilé en binaire par MioGtaTool "
                         "(CodeWalker.Core). Aucun XML n'est renommé en binaire.")
    elif ok:
        res.infos.append("Export binaire natif Sollumz (PyMateria) disponible.")
    if s.last_report:
        res.infos.append(s.last_report.split("\n")[0])
    if not res.errors and not s.last_report:
        res.status_override = "TODO"
    return res


CHECKS = {
    "prepare": check_prepare,
    "textures": check_textures,
    "ytyp": check_ytyp,
    "mlo": check_mlo,
    "collision": check_collision,
    "export": check_export,
}


def status_of(res: StepResult) -> str:
    override = getattr(res, "status_override", None)
    if override and not res.errors:
        return override
    return res.status


def compute(context) -> dict:
    s = context.scene.mio_mapping
    out = {}
    try:
        sza.get()
    except sza.SollumzUnavailable as e:
        r = StepResult()
        r.errors.append(str(e))
        return {k: r for k in STEP_KEYS}
    for k in STEP_KEYS:
        try:
            out[k] = CHECKS[k](context, s)
        except Exception as e:  # le diagnostic ne doit jamais casser l'interface
            r = StepResult()
            r.errors.append(f"Diagnostic impossible : {e}")
            out[k] = r
    return out


def refresh(context, only: tuple = ()) -> dict:
    s = context.scene.mio_mapping
    results = compute(context)
    now = time.strftime("%H:%M:%S")
    for k, res in results.items():
        if only and k not in only:
            continue
        getattr(s, f"step_{k}").set(status_of(res), res.lines(), now)
    return results


def store(context, key: str, res: StepResult, extra_status: str | None = None):
    s = context.scene.mio_mapping
    st = extra_status or status_of(res)
    getattr(s, f"step_{key}").set(st, res.lines(), time.strftime("%H:%M:%S"))
