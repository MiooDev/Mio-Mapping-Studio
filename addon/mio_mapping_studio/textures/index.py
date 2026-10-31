"""Index persistant des textures du jeu (fichier JSONL écrit par MioGtaTool index).

L'index est construit à la première utilisation puis réutilisé. Il est considéré périmé si la signature de
l'installation (liste des .rpf racines + tailles + dates, et l'exécutable) a changé : mise à jour du jeu, DLC...
Ce module n'importe pas bpy : il peut tourner dans un thread de travail.
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass, field
from pathlib import Path


def index_file(cache_dir: Path, gta_path: str, gen9: bool, include_mods: bool, embedded: bool) -> Path:
    key = f"{os.path.normcase(os.path.abspath(gta_path))}|{'gen9' if gen9 else 'gen8'}|{int(include_mods)}|{int(embedded)}"
    h = hashlib.sha1(key.encode("utf-8")).hexdigest()[:12]
    return Path(cache_dir) / "index" / f"textures_{h}.jsonl"


def compute_signature(gta_path: str, include_mods: bool, gen9: bool) -> str:
    """Doit rester identique à IndexCommand.ComputeSignature (C#)."""
    root = os.path.abspath(gta_path)
    lines = []
    for dirpath, _dirs, files in os.walk(root):
        for f in files:
            if not f.lower().endswith(".rpf"):
                continue
            full = os.path.join(dirpath, f)
            rel = os.path.relpath(full, root).replace("\\", "/").strip("/").lower()
            if not include_mods and rel.startswith("mods/"):
                continue
            st = os.stat(full)
            lines.append(f"{rel}|{st.st_size}|{int(st.st_mtime)}")
    exe_name = "GTA5_Enhanced.exe" if gen9 else "GTA5.exe"
    exe = os.path.join(root, exe_name)
    if os.path.isfile(exe):
        st = os.stat(exe)
        lines.append(f"{exe_name.lower()}|{st.st_size}|{int(st.st_mtime)}")
    lines.sort()
    return hashlib.sha1("\n".join(lines).encode("utf-8")).hexdigest()[:16]


def read_meta(path: Path) -> dict | None:
    try:
        with open(path, "r", encoding="utf-8") as f:
            first = f.readline()
        meta = json.loads(first)
        return meta if meta.get("k") == "meta" else None
    except (OSError, json.JSONDecodeError):
        return None


def index_state(path: Path, gta_path: str, include_mods: bool, gen9: bool) -> tuple[str, dict | None]:
    """("MISSING" | "STALE" | "OK", méta)."""
    if not path.is_file():
        return "MISSING", None
    meta = read_meta(path)
    if meta is None:
        return "STALE", None
    try:
        sig = compute_signature(gta_path, include_mods, gen9)
    except OSError:
        return "STALE", meta
    return ("OK" if meta.get("signature") == sig else "STALE"), meta


@dataclass
class IndexSlice:
    """Sous-ensemble utile de l'index pour une liste de textures."""
    textures: dict = field(default_factory=dict)    # nom -> [enregistrements tex]
    archetypes: dict = field(default_factory=dict)  # hash du nom -> enregistrement arch
    gtxd: dict = field(default_factory=dict)        # dictionnaire enfant -> parent
    dlc: dict = field(default_factory=dict)
    meta: dict | None = None
    errors: int = 0


def load_slice(path: Path, names: set, source_hashes: set, cancel=None) -> IndexSlice:
    """Lecture en flux : seules les lignes utiles sont décodées (index de plusieurs centaines de Mo possible)."""
    out = IndexSlice()
    tex_prefix = '{"k":"tex","n":"'
    arch_prefix = '{"k":"arch"'
    with open(path, "r", encoding="utf-8") as f:
        for i, line in enumerate(f):
            if cancel is not None and (i & 0xFFFF) == 0 and cancel():
                raise InterruptedError("annulé")
            if line.startswith(tex_prefix):
                end = line.find('"', len(tex_prefix))
                name = line[len(tex_prefix):end]
                if name in names:
                    out.textures.setdefault(name, []).append(json.loads(line))
            elif line.startswith(arch_prefix):
                rec = json.loads(line)
                if rec.get("nh") in source_hashes:
                    out.archetypes[rec["nh"]] = rec
            elif line.startswith('{"k":"gtxd"'):
                rec = json.loads(line)
                out.gtxd.setdefault(rec["c"], rec["p"])
            elif line.startswith('{"k":"dlc"'):
                rec = json.loads(line)
                out.dlc[rec["n"]] = rec["i"]
            elif line.startswith('{"k":"meta"'):
                out.meta = json.loads(line)
            elif line.startswith('{"k":"err"'):
                out.errors += 1
    return out
