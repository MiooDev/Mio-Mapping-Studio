"""Construit dist/mio_mapping_studio-<version>.zip (installable par Blender : Preferences > Add-ons > Install).

Le ZIP contient le dossier mio_mapping_studio/ (bl_info pour l'installation « add-on » et blender_manifest.toml
pour l'installation « extension »). Aucune texture GTA ni binaire CodeWalker n'y est inclus.
Usage : python scripts/build_zip.py
"""
import ast
import os
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "addon", "mio_mapping_studio")


def version():
    tree = ast.parse(open(os.path.join(SRC, "__init__.py"), encoding="utf-8").read())
    for node in tree.body:
        if isinstance(node, ast.Assign) and getattr(node.targets[0], "id", "") == "bl_info":
            return ".".join(str(v) for v in ast.literal_eval(node.value)["version"])
    raise SystemExit("bl_info introuvable")


def main():
    v = version()
    out = os.path.join(ROOT, "dist", f"mio_mapping_studio-{v}.zip")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for dp, dirs, files in os.walk(SRC):
            dirs[:] = sorted(d for d in dirs if d != "__pycache__")
            for f in sorted(files):
                if f.endswith((".pyc", ".pyo")):
                    continue
                full = os.path.join(dp, f)
                arc = os.path.join("mio_mapping_studio", os.path.relpath(full, SRC))
                info = zipfile.ZipInfo(arc.replace(os.sep, "/"), date_time=(2026, 1, 1, 0, 0, 0))
                info.compress_type = zipfile.ZIP_DEFLATED
                with open(full, "rb") as fh:
                    z.writestr(info, fh.read())
        z.write(os.path.join(ROOT, "LICENSE"), "mio_mapping_studio/LICENSE")
    print(out)


if __name__ == "__main__":
    main()
