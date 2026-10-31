"""Contrôle des dépendances au démarrage (non bloquant).

Quelques secondes après l'activation de l'addon : statut de Sollumz (version prise en charge, szio), de l'export
natif (PyMateria) et de l'outil compagnon (lancé en processus séparé avec « version », suivi par un timer).
Le résultat est affiché en tête de l'onglet et dans les préférences.
"""

import bpy

from . import companion, prefs
from . import sollumz_adapter as sza

_state = {"job": None, "t": 0.0}


def _set(lines, ok_companion):
    wm = bpy.context.window_manager
    if wm is None:
        return
    wm.mio_job.companion_status = "\n".join(lines)
    wm.mio_job.companion_ok = ok_companion


def _base_lines():
    ok, msg = sza.status()
    lines = [("OK  " if ok else "ERREUR  ") + msg]
    if ok:
        lines.append("Export binaire natif (PyMateria) : " + ("disponible" if sza.native_export_available()
                                                               else "absent -> XML CodeWalker compilé par MioGtaTool"))
    return lines


def _poll():
    job = _state["job"]
    if job is None:
        return None
    _state["t"] += 0.5
    if job.poll() or _state["t"] > 60:
        try:
            data = job.checked_result()
            line = f"OK  MioGtaTool {data.get('version')} (CodeWalker {str(data.get('codewalker_commit', ''))[:10]})"
            ok = True
        except companion.CompanionError as e:
            line, ok = f"ERREUR  Outil compagnon : {e}", False
        job.cleanup()
        _state["job"] = None
        _set(_base_lines() + [line], ok)
        return None
    return 0.5


def _start():
    try:
        lines = _base_lines()
        cmd = prefs.companion_command()
        if not cmd:
            _set(lines + ["ERREUR  Outil compagnon non configuré (Préférences de l'addon > MioGtaTool.exe)."], False)
            return None
        _state["job"] = companion.Job(cmd, ["version"], "version").start()
        _state["t"] = 0.0
        _set(lines + ["…  Vérification de l'outil compagnon"], False)
        bpy.app.timers.register(_poll, first_interval=0.5)
    except companion.CompanionError as e:
        _set(_base_lines() + [f"ERREUR  {e}"], False)
    except Exception as e:  # le contrôle ne doit jamais empêcher l'addon de se charger
        print("Mio Mapping Studio : contrôle des dépendances impossible :", e)
    return None


def register():
    if not bpy.app.background:
        bpy.app.timers.register(_start, first_interval=2.0)


def unregister():
    if bpy.app.timers.is_registered(_poll):
        bpy.app.timers.unregister(_poll)
    if bpy.app.timers.is_registered(_start):
        bpy.app.timers.unregister(_start)
    job = _state.get("job")
    if job is not None:
        job.cancel()
        job.cleanup()
        _state["job"] = None
