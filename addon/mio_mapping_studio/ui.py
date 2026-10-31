"""Interface : onglet « Mio Mapping Studio » de la barre latérale N de la vue 3D."""

import textwrap

import bpy

from . import naming, prefs
from . import sollumz_adapter as sza
from .export_pipeline import expected_files

CATEGORY = "Mio Mapping Studio"
STATUS_ICON = {"TODO": "RADIOBUT_OFF", "READY": "CHECKMARK", "WARNING": "ERROR", "ERROR": "CANCEL", "NA": "REMOVE"}
STATUS_LABEL = {"TODO": "À faire", "READY": "Prêt", "WARNING": "Avertissement", "ERROR": "Erreur", "NA": "Non applicable"}


def _wrap(layout, text, width=52, icon="NONE"):
    first = True
    for para in text.split("\n"):
        for line in textwrap.wrap(para, width) or [""]:
            layout.label(text=line, icon=icon if first else "BLANK1")
            first = False


def _width(context) -> int:
    return max(28, int(context.region.width / 7.2)) if context and context.region else 52


def draw_step(layout, context, step, max_lines=14):
    box = layout.box()
    row = box.row()
    row.label(text=f"État : {STATUS_LABEL.get(step.status, step.status)}", icon=STATUS_ICON.get(step.status, "NONE"))
    if step.checked_at:
        row.label(text=step.checked_at)
    if step.messages:
        col = box.column(align=True)
        col.scale_y = 0.8
        lines = step.messages.split("\n")
        for line in lines[:max_lines]:
            icon = "CANCEL" if line.startswith("Erreur") else "ERROR" if line.startswith("Attention") else "DOT"
            _wrap(col, line, _width(context), icon)
        if len(lines) > max_lines:
            col.label(text=f"… {len(lines) - max_lines} ligne(s) de plus (Info / console)")


class MIO_PT_base:
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = CATEGORY


class MIO_PT_main(MIO_PT_base, bpy.types.Panel):
    bl_idname = "MIO_PT_main"
    bl_label = "Mio Mapping Studio"

    def draw(self, context):
        layout = self.layout
        s = context.scene.mio_mapping
        ok, msg = sza.status()
        if not ok:
            box = layout.box()
            box.alert = True
            _wrap(box, msg, _width(context), "ERROR")
            box.operator("mio.check_dependencies", icon="FILE_REFRESH")
            return
        job = context.window_manager.mio_job
        if job.companion_status:
            dep = layout.box()
            dep.scale_y = 0.8
            for line in job.companion_status.split("\n"):
                icon = "CHECKMARK" if line.startswith("OK") else "ERROR" if line.startswith("ERREUR") else "INFO"
                _wrap(dep, line.replace("OK  ", "").replace("ERREUR  ", ""), _width(context), icon)
        col = layout.column()
        col.prop(s, "mapping_name")
        name = naming.normalize_mapping_name(s.mapping_name)
        if s.mapping_name:
            col.label(text=f"Asset : {name or 'nom invalide'}", icon="CHECKMARK" if name else "ERROR")
        col.prop(s, "mapping_root")
        col.prop(s, "collision_root")
        col.prop(s, "gta_path")
        col.prop(s, "game_gen")
        col.prop(s, "export_dir")
        col.prop(s, "export_mode", text="Mode")
        mode_box = layout.box()
        if s.export_mode == "STATIC_EMBEDDED":
            _wrap(mode_box, "Mapping statique : collision intégrée au YDR, Physics Dictionary = mio_xxxx, aucun MLO. "
                            "Un extérieur n'a pas besoin d'être un intérieur pour avoir une collision.", _width(context),
                  "INFO")
        else:
            _wrap(mode_box, "MLO limbo : la collision est un YBN séparé (mio_xxxx_col.ybn) référencé par l'archetype "
                            "MLO, et l'intérieur doit être placé par un YMAP. Plus de fichiers.", _width(context), "INFO")
        mode_box.label(text="Fichiers : " + ", ".join(expected_files(s)))
        row = layout.row()
        row.enabled = s.export_mode == "MLO_LIMBO"
        row.prop(s, "limbo_margin_xy")
        row = layout.row(align=True)
        row.operator("mio.refresh_diagnostics", icon="FILE_REFRESH")
        row.operator("mio.check_dependencies", text="", icon="PLUGIN")
        if job.running:
            box = layout.box()
            box.progress(factor=job.progress, text=job.message[:60] or "En cours…")
            box.operator("mio.cancel_job", icon="CANCEL")


class MIO_PT_step1(MIO_PT_base, bpy.types.Panel):
    bl_idname = "MIO_PT_step1"
    bl_label = "1. Préparer le mapping / collisions"
    bl_parent_id = "MIO_PT_main"

    @classmethod
    def poll(cls, context):
        return sza.status()[0]

    def draw(self, context):
        s = context.scene.mio_mapping
        layout = self.layout
        layout.prop(s, "origin_mode", text="Origine")
        layout.operator("mio.prepare_mapping", icon="OUTLINER_OB_EMPTY")
        layout.operator("mio.clean_unused_slots", icon="BRUSH_DATA")
        if s.collision_root is None:
            from .hierarchy import find_named_collision
            named = find_named_collision(s)
            if named is not None:
                layout.operator("mio.use_named_collision", text=f"Utiliser {named.name}", icon="MOD_PHYSICS")
        box = layout.box()
        box.label(text="Collision depuis le visuel", icon="MOD_PHYSICS")
        box.prop(s, "collision_usage", text="Usage")
        box.prop(s, "collision_skip_decals")
        row = box.row(align=True)
        row.prop(s, "collision_decimate")
        sub = row.row()
        sub.enabled = s.collision_decimate
        sub.prop(s, "collision_decimate_ratio")
        box.prop(s, "collision_replace_existing")
        box.operator("mio.create_collision", icon="MESH_ICOSPHERE")
        box.operator("mio.apply_collision_preset", icon="PRESET")
        draw_step(layout, context, s.step_prepare)


class MIO_UL_texture_refs(bpy.types.UIList):
    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index):
        icons = {"FOUND": "CHECKMARK", "AMBIGUOUS": "QUESTION", "MISSING": "CANCEL", "INVALID": "ERROR"}
        row = layout.row(align=True)
        row.label(text=item.name, icon=icons.get(item.status, "NONE"))
        kind = ""
        if 0 <= item.chosen < len(item.candidates):
            kind = {"SCENE": "intégrée", "GAME": item.candidates[item.chosen].dict_name, "LOCAL": "DDS local"}.get(
                item.candidates[item.chosen].kind, "")
        row.label(text=kind)


class MIO_UL_candidates(bpy.types.UIList):
    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index):
        row = layout.row(align=True)
        mark = "RADIOBUT_ON" if index == data.chosen else "RADIOBUT_OFF"
        label = item.dict_name or item.path
        if item.kind != "GAME":
            label = {"SCENE": "Intégrée (scène)", "LOCAL": "DDS local (secours)"}[item.kind]
        row.label(text=label, icon=mark)
        if item.kind == "GAME":
            row.label(text=f"{item.width}x{item.height} {item.fmt.replace('D3DFMT_', '')} p{item.priority}")


class MIO_PT_step2(MIO_PT_base, bpy.types.Panel):
    bl_idname = "MIO_PT_step2"
    bl_label = "2. Trouver les textures et créer le YTD"
    bl_parent_id = "MIO_PT_main"

    @classmethod
    def poll(cls, context):
        return sza.status()[0]

    def draw(self, context):
        s = context.scene.mio_mapping
        layout = self.layout
        job = context.window_manager.mio_job
        col = layout.column()
        col.enabled = not job.running
        col.operator("mio.find_textures", icon="TEXTURE")
        row = col.row(align=True)
        row.operator("mio.rebuild_index", icon="FILE_REFRESH")
        row.prop(s, "index_include_mods", text="mods")
        col.prop(s, "index_embedded")
        col.prop(s, "move_embedded_textures")
        if job.running:
            box = layout.box()
            box.progress(factor=job.progress, text=job.message[:60] or "En cours…")
            box.operator("mio.cancel_job", icon="CANCEL")
        if not prefs.companion_command(context):
            box = layout.box()
            box.alert = True
            _wrap(box, "Outil compagnon MioGtaTool non configuré (Préférences de l'addon). Il est nécessaire pour lire "
                       "les RPF du jeu et écrire le YTD binaire.", _width(context), "ERROR")
        if len(s.texture_refs):
            layout.template_list("MIO_UL_texture_refs", "", s, "texture_refs", s, "texture_refs_index", rows=5)
            if 0 <= s.texture_refs_index < len(s.texture_refs):
                ref = s.texture_refs[s.texture_refs_index]
                box = layout.box()
                _wrap(box, f"{ref.name} : {ref.reason}", _width(context), "INFO")
                if ref.used_by:
                    _wrap(box, "Utilisée par : " + ref.used_by, _width(context))
                if ref.sources:
                    _wrap(box, "Modèle(s) d'origine : " + ref.sources, _width(context))
                if len(ref.candidates):
                    box.template_list("MIO_UL_candidates", "", ref, "candidates", ref, "candidates_index", rows=3)
                    if 0 <= ref.candidates_index < len(ref.candidates):
                        c = ref.candidates[ref.candidates_index]
                        _wrap(box, c.path + (f" — {c.note}" if c.note else ""), _width(context))
                        op = box.operator("mio.choose_texture_source", icon="CHECKMARK")
                        op.ref_index = s.texture_refs_index
                        op.candidate_index = ref.candidates_index
        draw_step(layout, context, s.step_textures)


class MIO_PT_step3(MIO_PT_base, bpy.types.Panel):
    bl_idname = "MIO_PT_step3"
    bl_label = "3. Créer ou mettre à jour le YTYP"
    bl_parent_id = "MIO_PT_main"

    @classmethod
    def poll(cls, context):
        return sza.status()[0]

    def draw(self, context):
        s = context.scene.mio_mapping
        layout = self.layout
        layout.prop(s, "lod_dist")
        layout.prop(s, "hd_texture_dist")
        layout.operator("mio.update_ytyp", icon="FILE_NEW")
        draw_step(layout, context, s.step_ytyp)


class MIO_PT_step4(MIO_PT_base, bpy.types.Panel):
    bl_idname = "MIO_PT_step4"
    bl_label = "4. Configurer le MLO / limbo"
    bl_parent_id = "MIO_PT_main"

    @classmethod
    def poll(cls, context):
        return sza.status()[0]

    def draw(self, context):
        s = context.scene.mio_mapping
        layout = self.layout
        if s.export_mode == "STATIC_EMBEDDED":
            _wrap(layout, "Non applicable en mode statique : aucun archetype MLO n'est créé, la collision est intégrée "
                          "au YDR. Passe en mode « MLO limbo » seulement si tu veux un intérieur.", _width(context),
                  "INFO")
            layout.operator("mio.remove_incoherent_mlo", icon="TRASH")
        else:
            layout.prop(s, "limbo_margin_xy")
            layout.prop(s, "limbo_margin_z")
            layout.operator("mio.configure_mlo", icon="HOME")
            _wrap(layout, "Aucun portal n'est créé pour un espace extérieur. Pour un vrai intérieur à plusieurs pièces, "
                          "la room limbo seule ne conçoit pas les rooms/portals : fais-les dans Sollumz.",
                  _width(context), "INFO")
        draw_step(layout, context, s.step_mlo)


class MIO_PT_step5(MIO_PT_base, bpy.types.Panel):
    bl_idname = "MIO_PT_step5"
    bl_label = "5. Intégrer les collisions"
    bl_parent_id = "MIO_PT_main"

    @classmethod
    def poll(cls, context):
        return sza.status()[0]

    def draw(self, context):
        s = context.scene.mio_mapping
        layout = self.layout
        text = ("Intégrer les collisions au mapping" if s.export_mode == "STATIC_EMBEDDED"
                else "Aligner la collision MLO (YBN séparé)")
        layout.operator("mio.integrate_collision", text=text, icon="LINKED")
        draw_step(layout, context, s.step_collision)


class MIO_PT_step6(MIO_PT_base, bpy.types.Panel):
    bl_idname = "MIO_PT_step6"
    bl_label = "6. Vérifier et exporter"
    bl_parent_id = "MIO_PT_main"

    @classmethod
    def poll(cls, context):
        return sza.status()[0]

    def draw(self, context):
        s = context.scene.mio_mapping
        layout = self.layout
        row = layout.row()
        row.enabled = s.export_mode == "STATIC_EMBEDDED"
        row.prop(s, "generate_ymap")
        layout.prop(s, "generate_fivem")
        if s.generate_fivem:
            layout.prop(s, "fivem_resource_name")
        layout.label(text="Fichiers : " + ", ".join(expected_files(s)))
        row = layout.row(align=True)
        op = row.operator("mio.verify_export", text="Vérifier", icon="VIEWZOOM")
        op.dry_run = True
        op = row.operator("mio.verify_export", text="Vérifier et exporter", icon="EXPORT")
        op.dry_run = False
        op = layout.operator("mio.verify_export", text="Exporter même si incomplet", icon="ERROR")
        op.allow_incomplete = True
        box = layout.box()
        _wrap(box, "Rappel : ces fichiers sont des assets. Le YMAP place l'entité dans le monde, le YTYP doit être "
                   "déclaré (data_file DLC_ITYP_REQUEST) dans fxmanifest.lua, et les objets/collisions d'origine de GTA "
                   "ne sont jamais supprimés automatiquement.", _width(context), "INFO")
        draw_step(layout, context, s.step_export, max_lines=24)


CLASSES = (MIO_UL_texture_refs, MIO_UL_candidates, MIO_PT_main, MIO_PT_step1, MIO_PT_step2, MIO_PT_step3,
           MIO_PT_step4, MIO_PT_step5, MIO_PT_step6)


def register():
    for c in CLASSES:
        bpy.utils.register_class(c)


def unregister():
    for c in reversed(CLASSES):
        bpy.utils.unregister_class(c)
