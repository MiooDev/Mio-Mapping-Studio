"""Opérateurs de Mio Mapping Studio."""

from __future__ import annotations

import traceback

import bpy
from bpy.props import BoolProperty, IntProperty

from . import collision, companion, diagnostics, export_pipeline, hierarchy, prefs, ytyp_tools
from . import sollumz_adapter as sza
from .textures import pipeline as tpipe


def _poll_sollumz(cls, context) -> bool:
    ok, msg = sza.status()
    if not ok:
        cls.poll_message_set(msg)
    return ok


def _job_busy(context) -> bool:
    return context.window_manager.mio_job.running


def _finish(op, context, key, res, refresh_all=True):
    diagnostics.store(context, key, res)
    if refresh_all:
        others = tuple(k for k in diagnostics.STEP_KEYS if k != key)
        diagnostics.refresh(context, only=others)
    for line in res.errors:
        op.report({"ERROR"}, line)
    for line in res.warnings[:5]:
        op.report({"WARNING"}, line)
    if not res.errors:
        op.report({"INFO"}, res.infos[0] if res.infos else "Terminé.")
    # FINISHED même en cas d'erreur : une étape peut avoir modifié la scène avant l'erreur ; on garde ainsi un pas
    # d'annulation (Ctrl+Z) cohérent. L'état de l'étape affiche l'erreur.
    return {"FINISHED"}


def _safe(op, context, key, fn):
    try:
        res = fn()
    except Exception as e:  # message lisible + trace dans la console
        traceback.print_exc()
        res = hierarchy.StepResult()
        res.errors.append(f"Erreur inattendue : {e}")
    return _finish(op, context, key, res)


class MIO_OT_refresh(bpy.types.Operator):
    bl_idname = "mio.refresh_diagnostics"
    bl_label = "Actualiser le diagnostic"
    bl_description = "Revérifie toutes les étapes sans rien modifier"

    def execute(self, context):
        diagnostics.refresh(context)
        return {"FINISHED"}


class MIO_OT_check_dependencies(bpy.types.Operator):
    bl_idname = "mio.check_dependencies"
    bl_label = "Vérifier les dépendances"
    bl_description = "Vérifie Sollumz, PyMateria (export natif) et l'outil compagnon MioGtaTool"

    def execute(self, context):
        lines = []
        ok_sz, msg = sza.status()
        lines.append(("OK  " if ok_sz else "ERREUR  ") + msg)
        if ok_sz:
            lines.append("Export binaire natif (PyMateria) : " + ("disponible" if sza.native_export_available()
                                                                   else "absent -> XML CodeWalker + compilation MioGtaTool"))
        ok_c, cmsg = companion.check(prefs.companion_command(context))
        lines.append(("OK  " if ok_c else "ERREUR  ") + cmsg)
        job = context.window_manager.mio_job
        job.companion_ok = ok_c
        job.companion_status = "\n".join(lines)
        self.report({"INFO"} if ok_sz and ok_c else {"WARNING"}, " | ".join(lines))
        return {"FINISHED"}


class MIO_OT_prepare_mapping(bpy.types.Operator):
    bl_idname = "mio.prepare_mapping"
    bl_label = "Préparer le mapping"
    bl_description = ("Regroupe les objets choisis (ou sélectionnés) sous le Drawable mio_xxxx sans fusionner les meshes "
                      "ni les déplacer, et prépare la collision désignée en Bound Composite mio_xxxx_col")
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return _poll_sollumz(cls, context) and context.mode == "OBJECT"

    def execute(self, context):
        s = context.scene.mio_mapping
        return _safe(self, context, "prepare", lambda: hierarchy.prepare_mapping(context, s))


class MIO_OT_create_collision(bpy.types.Operator):
    bl_idname = "mio.create_collision"
    bl_label = "Créer les collisions depuis le mapping"
    bl_description = ("Duplique la géométrie visible (un seul LOD) en Poly Mesh de collision, sous un Bound Composite "
                      "mio_xxxx_col, avec un matériau de collision et les flags de l'usage choisi")
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return _poll_sollumz(cls, context) and context.mode == "OBJECT"

    def invoke(self, context, event):
        s = context.scene.mio_mapping
        if s.collision_root is not None and s.collision_replace_existing:
            return context.window_manager.invoke_confirm(
                self, event, title="Remplacer la collision existante ?",
                message=f"« {s.collision_root.name} » sera remplacée par une copie du visuel.")
        return self.execute(context)

    def execute(self, context):
        s = context.scene.mio_mapping
        d = hierarchy.find_drawable(s)
        if d is None:
            self.report({"ERROR"}, "Lance d'abord « Préparer le mapping ».")
            return {"CANCELLED"}
        return _safe(self, context, "prepare",
                     lambda: collision.create_collision_from_mapping(context, s, d, s.collision_replace_existing))


class MIO_OT_use_named_collision(bpy.types.Operator):
    bl_idname = "mio.use_named_collision"
    bl_label = "Utiliser la collision existante"
    bl_description = ("Désigne le Bound Composite « mio_xxxx_col » déjà présent comme objet racine collision et le "
                      "prépare (nom, origine alignée sur le Drawable, validation)")
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return _poll_sollumz(cls, context) and context.mode == "OBJECT"

    def execute(self, context):
        s = context.scene.mio_mapping

        def do():
            named = hierarchy.find_named_collision(s)
            r = hierarchy.StepResult()
            if named is None:
                r.errors.append("Aucun Bound Composite « mio_xxxx_col » trouvé.")
                return r
            d = hierarchy.find_drawable(s)
            if d is None:
                s.collision_root = named
                r.warnings.append(f"« {named.name} » désignée. Lance maintenant « Préparer le mapping ».")
                return r
            return collision.prepare_collision_root(context, s, [named], d)
        return _safe(self, context, "prepare", do)


class MIO_OT_clean_unused_slots(bpy.types.Operator):
    bl_idname = "mio.clean_unused_slots"
    bl_label = "Nettoyer les slots inutilisés"
    bl_description = ("Retire des meshes du mapping les slots de matériau qu'aucune face n'utilise plus (après découpe). "
                      "Sollumz exporte sinon ces matériaux dans le YDR comme shaders jamais rendus. Les faces gardent "
                      "leurs matériaux ; un mesh partagé hors du mapping est copié avant")
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return _poll_sollumz(cls, context) and context.mode == "OBJECT"

    def execute(self, context):
        from . import sharing
        s = context.scene.mio_mapping

        def do():
            r = hierarchy.StepResult()
            d = hierarchy.find_drawable(s)
            if d is None:
                r.errors.append("Lance d'abord « Préparer le mapping ».")
                return r
            n, msgs = sharing.remove_unused_slots(hierarchy.mapping_models(d))
            r.infos.append(f"{n} slot(s) de matériau inutilisé(s) retiré(s) (aucune face modifiée)." if n
                           else "Aucun slot inutilisé.")
            r.infos += msgs
            return r
        return _safe(self, context, "prepare", do)


class MIO_OT_apply_collision_preset(bpy.types.Operator):
    bl_idname = "mio.apply_collision_preset"
    bl_label = "Appliquer le preset d'usage"
    bl_description = "Applique les flags Sollumz de l'usage choisi à chaque élément de la collision"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return _poll_sollumz(cls, context)

    def execute(self, context):
        s = context.scene.mio_mapping
        return _safe(self, context, "prepare", lambda: collision.apply_usage_preset(context, s))


class _JobOperatorMixin:
    _driver = None
    _timer = None

    def _make_generator(self, context):
        raise NotImplementedError

    def _on_result(self, context, result):
        raise NotImplementedError

    def _on_error(self, context, message):
        raise NotImplementedError

    def execute(self, context):
        job = context.window_manager.mio_job
        if job.running:
            self.report({"ERROR"}, "Une tâche de fond est déjà en cours.")
            return {"CANCELLED"}
        try:
            gen = self._make_generator(context)
        except tpipe.PipelineError as e:
            self._on_error(context, str(e))
            self.report({"ERROR"}, str(e))
            return {"CANCELLED"}
        if bpy.app.background or not context.window_manager.windows:
            try:
                result = tpipe.run_sync(gen)
            except (tpipe.PipelineError, companion.CompanionError, InterruptedError) as e:
                self._on_error(context, str(e))
                self.report({"ERROR"}, str(e))
                return {"CANCELLED"}
            self._on_result(context, result)
            return {"FINISHED"}
        self._driver = tpipe.AsyncDriver(gen)
        job.running = True
        job.cancel_requested = False
        job.progress = 0.0
        job.message = "Démarrage…"
        self._driver.start()
        wm = context.window_manager
        self._timer = wm.event_timer_add(0.25, window=context.window)
        wm.modal_handler_add(self)
        return {"RUNNING_MODAL"}

    def _stop(self, context):
        wm = context.window_manager
        if self._timer is not None:
            wm.event_timer_remove(self._timer)
            self._timer = None
        wm.mio_job.running = False
        wm.mio_job.cancel_requested = False
        for area in context.screen.areas if context.screen else []:
            area.tag_redraw()

    def modal(self, context, event):
        job = context.window_manager.mio_job
        d = self._driver
        if event.type == "ESC" or job.cancel_requested:
            d.cancel()
            self._stop(context)
            self._on_error(context, "Opération annulée par l'utilisateur.")
            self.report({"WARNING"}, "Opération annulée.")
            return {"CANCELLED"}
        if event.type == "TIMER":
            try:
                d.tick()
            except Exception as e:
                traceback.print_exc()
                d.done, d.error = True, f"Erreur inattendue : {e}"
            job.progress = float(min(max(d.progress, 0.0), 1.0))
            job.message = d.message[:200]
            for area in context.screen.areas if context.screen else []:
                if area.type == "VIEW_3D":
                    area.tag_redraw()
            if d.done:
                self._stop(context)
                if d.error:
                    self._on_error(context, d.error)
                    self.report({"ERROR"}, d.error)
                    return {"CANCELLED"}
                self._on_result(context, d.result)
                return {"FINISHED"}
        return {"PASS_THROUGH"}


class MIO_OT_find_textures(_JobOperatorMixin, bpy.types.Operator):
    bl_idname = "mio.find_textures"
    bl_label = "Trouver les textures GTA et créer le YTD"
    bl_description = ("Analyse les matériaux réellement utilisés, retrouve les textures d'origine dans GTA V (index "
                      "persistant), extrait les DDS sans recompression et construit mio_xxxx.ytd (binaire)")
    bl_options = {"REGISTER", "UNDO"}

    force_reindex: BoolProperty(name="Reconstruire l'index", default=False, options={"SKIP_SAVE"})

    @classmethod
    def poll(cls, context):
        return _poll_sollumz(cls, context) and not _job_busy(context)

    def _make_generator(self, context):
        return tpipe.run(context, self.force_reindex)

    def _on_result(self, context, result):
        r = hierarchy.StepResult()
        st = result.get("status", "READY")
        if st == "ERROR":
            r.errors += result["lines"][:1]
        lines = result.get("lines", [])
        r.infos += lines
        diagnostics.store(context, "textures", r, extra_status=st)
        diagnostics.refresh(context, only=("ytyp", "export"))
        self.report({"INFO"} if st == "READY" else {"WARNING"}, " | ".join(lines[:4]))

    def _on_error(self, context, message):
        r = hierarchy.StepResult()
        r.errors.append(message)
        diagnostics.store(context, "textures", r)


class MIO_OT_rebuild_index(_JobOperatorMixin, bpy.types.Operator):
    bl_idname = "mio.rebuild_index"
    bl_label = "Reconstruire l'index"
    bl_description = "Relit toutes les archives RPF de l'installation GTA V (lecture seule) et reconstruit l'index"

    @classmethod
    def poll(cls, context):
        return not _job_busy(context)

    def _make_generator(self, context):
        return tpipe.index_only(context)

    def _on_result(self, context, result):
        data = result.get("result") or {}
        msg = (f"Index : {data.get('textures', 0)} textures, {data.get('archetypes', 0)} archetypes, "
               f"{data.get('errors', 0)} fichier(s) illisible(s).")
        r = hierarchy.StepResult()
        r.infos.append(msg)
        diagnostics.store(context, "textures", r, extra_status="TODO" if not context.scene.mio_mapping.texture_refs
                          else None)
        self.report({"INFO"}, msg)

    def _on_error(self, context, message):
        r = hierarchy.StepResult()
        r.errors.append(message)
        diagnostics.store(context, "textures", r)


class MIO_OT_cancel_job(bpy.types.Operator):
    bl_idname = "mio.cancel_job"
    bl_label = "Annuler"
    bl_description = "Annule la tâche de fond en cours"

    def execute(self, context):
        context.window_manager.mio_job.cancel_requested = True
        return {"FINISHED"}


class MIO_OT_choose_texture_source(bpy.types.Operator):
    bl_idname = "mio.choose_texture_source"
    bl_label = "Utiliser cette source"
    bl_description = "Choisit manuellement la source de la texture (mémorisé pour les relances)"
    bl_options = {"REGISTER", "UNDO"}

    ref_index: IntProperty(default=-1)
    candidate_index: IntProperty(default=-1)

    def execute(self, context):
        s = context.scene.mio_mapping
        if not (0 <= self.ref_index < len(s.texture_refs)):
            return {"CANCELLED"}
        ref = s.texture_refs[self.ref_index]
        if not (0 <= self.candidate_index < len(ref.candidates)):
            return {"CANCELLED"}
        c = ref.candidates[self.candidate_index]
        ref.user_choice = f"{c.kind}:{c.path}"
        ref.chosen = self.candidate_index
        ref.status = "FOUND"
        ref.reason = "Choix manuel (relance « Trouver les textures » pour extraire et reconstruire le YTD)"
        r = hierarchy.StepResult()
        r.warnings.append(f"Source de « {ref.name} » choisie : {c.dict_name or c.path}. Relance l'étape 2 pour "
                          "reconstruire le YTD.")
        diagnostics.store(context, "textures", r)
        return {"FINISHED"}


class MIO_OT_update_ytyp(bpy.types.Operator):
    bl_idname = "mio.update_ytyp"
    bl_label = "Créer / mettre à jour le YTYP"
    bl_description = "Crée mio_xxxx.ytyp et l'archetype Base mio_xxxx, ou le met à jour sans doublon"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return _poll_sollumz(cls, context)

    def execute(self, context):
        s = context.scene.mio_mapping
        return _safe(self, context, "ytyp", lambda: ytyp_tools.update_base_archetype(context, s))


class MIO_OT_remove_mlo(bpy.types.Operator):
    bl_idname = "mio.remove_incoherent_mlo"
    bl_label = "Retirer l'archetype MLO"
    bl_description = "Mode statique : retire du YTYP l'archetype MLO qui référencerait un YBN non exporté"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return _poll_sollumz(cls, context)

    def execute(self, context):
        s = context.scene.mio_mapping
        return _safe(self, context, "mlo", lambda: ytyp_tools.remove_incoherent_mlo(context, s))


class MIO_OT_configure_mlo(bpy.types.Operator):
    bl_idname = "mio.configure_mlo"
    bl_label = "Configurer le MLO limbo"
    bl_description = ("Mode MLO : archetype MLO mio_xxxx_col relié au Bound Composite mio_xxxx_col, room « limbo » "
                      "(bounds + marges) et entité mio_xxxx attachée")
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return _poll_sollumz(cls, context) and context.scene.mio_mapping.export_mode == "MLO_LIMBO"

    def execute(self, context):
        s = context.scene.mio_mapping
        return _safe(self, context, "mlo", lambda: ytyp_tools.configure_mlo(context, s))


class MIO_OT_integrate_collision(bpy.types.Operator):
    bl_idname = "mio.integrate_collision"
    bl_label = "Intégrer les collisions au mapping"
    bl_description = ("Mode statique : place le Bound Composite sous le Drawable (collision embedded du YDR), sans "
                      "fusionner de meshes ni déplacer la géométrie. Mode MLO : garde la collision séparée et alignée")
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return _poll_sollumz(cls, context) and context.mode == "OBJECT"

    def execute(self, context):
        s = context.scene.mio_mapping

        def do():
            r = collision.integrate(context, s, hierarchy.find_drawable(s))
            if not r.errors and s.export_mode == "STATIC_EMBEDDED":
                _, ytyp = sza.find_ytyp(context.scene, s.name_or_error())
                if ytyp is not None:
                    r.extend(ytyp_tools.update_base_archetype(context, s))
            return r
        return _safe(self, context, "collision", do)


class MIO_OT_export(bpy.types.Operator):
    bl_idname = "mio.verify_export"
    bl_label = "Vérifier et exporter"
    bl_description = ("Vérifie hiérarchie, noms, textures, matériaux, collisions, flags, limites BVH, bounds et "
                      "références YTYP, exporte dans un dossier temporaire, relit les binaires puis remplace l'export")
    bl_options = {"REGISTER", "UNDO"}

    dry_run: BoolProperty(name="Vérifier seulement", default=False, options={"SKIP_SAVE"})
    allow_incomplete: BoolProperty(name="Exporter même si incomplet", default=False, options={"SKIP_SAVE"})

    @classmethod
    def poll(cls, context):
        return _poll_sollumz(cls, context) and not _job_busy(context) and context.mode == "OBJECT"

    def execute(self, context):
        s = context.scene.mio_mapping
        return _safe(self, context, "export",
                     lambda: export_pipeline.run(context, allow_incomplete=self.allow_incomplete, dry_run=self.dry_run))


CLASSES = (
    MIO_OT_refresh, MIO_OT_check_dependencies, MIO_OT_prepare_mapping, MIO_OT_create_collision,
    MIO_OT_use_named_collision, MIO_OT_clean_unused_slots,
    MIO_OT_apply_collision_preset, MIO_OT_find_textures, MIO_OT_rebuild_index, MIO_OT_cancel_job,
    MIO_OT_choose_texture_source, MIO_OT_update_ytyp, MIO_OT_remove_mlo, MIO_OT_configure_mlo,
    MIO_OT_integrate_collision, MIO_OT_export,
)


def register():
    for c in CLASSES:
        bpy.utils.register_class(c)


def unregister():
    for c in reversed(CLASSES):
        bpy.utils.unregister_class(c)
