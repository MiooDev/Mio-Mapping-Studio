"""Exécution de l'outil compagnon MioGtaTool dans un processus séparé.

Le processus écrit une ligne JSON par événement. Un thread lit stdout et pousse les événements dans une file ;
le thread principal de Blender les consomme (timer / opérateur modal). AUCUN appel bpy n'est fait depuis le thread.
"""

from __future__ import annotations

import json
import os
import queue
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path


class CompanionError(RuntimeError):
    pass


class Job:
    def __init__(self, command: list[str], args: list[str], label: str = ""):
        self.command = list(command)
        self.args = list(args)
        self.label = label
        self.events: queue.Queue = queue.Queue()
        self.proc: subprocess.Popen | None = None
        self.result: dict | None = None
        self.logs: list[tuple[str, str]] = []
        self.progress = (0, 0, "")
        self.stderr_tail: list[str] = []
        self.cancel_file = Path(tempfile.gettempdir()) / f"mio_cancel_{os.getpid()}_{id(self)}"
        self.returncode: int | None = None
        self._reader: threading.Thread | None = None
        self._err_reader: threading.Thread | None = None
        self.cancelled = False

    # -- lancement ---------------------------------------------------------------------------------------------------
    def start(self):
        if self.cancel_file.exists():
            self.cancel_file.unlink()
        argv = self.command + self.args + ["--cancel-file", str(self.cancel_file)]
        kwargs = {}
        if sys.platform == "win32":
            kwargs["creationflags"] = 0x08000000  # CREATE_NO_WINDOW
        try:
            self.proc = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE, stdin=subprocess.DEVNULL,
                                         text=True, encoding="utf-8", errors="replace", bufsize=1, **kwargs)
        except FileNotFoundError as e:
            raise CompanionError(f"Outil compagnon introuvable : {self.command[0]}") from e
        except OSError as e:
            raise CompanionError(f"Impossible de lancer l'outil compagnon : {e}") from e
        self._reader = threading.Thread(target=self._read_stdout, daemon=True)
        self._err_reader = threading.Thread(target=self._read_stderr, daemon=True)
        self._reader.start()
        self._err_reader.start()
        return self

    def _read_stdout(self):
        assert self.proc is not None
        for line in self.proc.stdout:
            line = line.strip()
            if not line:
                continue
            try:
                ev = json.loads(line)
            except json.JSONDecodeError:
                ev = {"type": "log", "level": "info", "message": line}
            self.events.put(ev)
        self.events.put({"type": "_eof"})

    def _read_stderr(self):
        assert self.proc is not None
        for line in self.proc.stderr:
            self.stderr_tail.append(line.rstrip())
            if len(self.stderr_tail) > 40:
                self.stderr_tail.pop(0)

    # -- suivi -------------------------------------------------------------------------------------------------------
    def poll(self) -> bool:
        """Consomme les événements disponibles. Retourne True quand la tâche est terminée."""
        finished = False
        while True:
            try:
                ev = self.events.get_nowait()
            except queue.Empty:
                break
            t = ev.get("type")
            if t == "progress":
                self.progress = (ev.get("done", 0), ev.get("total", 0), ev.get("message", ""))
            elif t == "log":
                self.logs.append((ev.get("level", "info"), ev.get("message", "")))
            elif t == "result":
                self.result = ev
            elif t == "_eof":
                finished = True
        if finished and self.proc is not None:
            self.returncode = self.proc.wait()
            if self._err_reader:
                self._err_reader.join(timeout=2)
        return finished

    def fraction(self) -> float:
        done, total, _ = self.progress
        return (done / total) if total else 0.0

    def cancel(self):
        """Annulation : fichier d'annulation lu par l'outil, puis arrêt du processus si nécessaire."""
        self.cancelled = True
        try:
            self.cancel_file.write_text("cancel")
        except OSError:
            pass
        if self.proc is not None and self.proc.poll() is None:
            try:
                self.proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self.proc.terminate()

    def wait(self, timeout: float | None = None) -> dict:
        """Exécution bloquante (tests, petites opérations). Retourne le résultat ou lève CompanionError."""
        t0 = time.time()
        while not self.poll():
            if timeout is not None and time.time() - t0 > timeout:
                self.cancel()
                raise CompanionError(f"Délai dépassé pour {self.label or self.args[:1]}")
            time.sleep(0.05)
        return self.checked_result()

    def checked_result(self) -> dict:
        if self.cancelled:
            raise CompanionError("Opération annulée.")
        if self.result is None:
            tail = "\n".join(self.stderr_tail[-5:])
            raise CompanionError(f"L'outil compagnon s'est arrêté sans résultat (code {self.returncode}). {tail}")
        if not self.result.get("ok"):
            raise CompanionError(self.result.get("error") or "Erreur inconnue de l'outil compagnon.")
        return self.result.get("data") or {}

    def cleanup(self):
        try:
            if self.cancel_file.exists():
                self.cancel_file.unlink()
        except OSError:
            pass


def run(command: list[str], args: list[str], timeout: float | None = 600, label: str = "") -> dict:
    job = Job(command, args, label).start()
    try:
        return job.wait(timeout)
    finally:
        job.cleanup()


def check(command: list[str] | None) -> tuple[bool, str]:
    if not command:
        return False, ("Outil compagnon non configuré : compile companion/ (build.ps1) puis indique MioGtaTool.exe "
                       "dans les préférences de l'addon.")
    try:
        data = run(command, ["version"], timeout=60, label="version")
    except CompanionError as e:
        return False, str(e)
    return True, f"MioGtaTool {data.get('version')} (CodeWalker {str(data.get('codewalker_commit', ''))[:10]})"
