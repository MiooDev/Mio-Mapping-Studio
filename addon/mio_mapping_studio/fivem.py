"""Ressource FiveM optionnelle et explications sur le placement.

Un export d'assets (YDR/YTD/YTYP) n'est PAS une map placée : rien n'apparaît en jeu sans YMAP qui place l'entité,
et le YTYP doit être déclaré à FiveM (data_file DLC_ITYP_REQUEST). Ce module ne supprime jamais d'objets ni de
collisions du monde GTA d'origine : le bâtiment et le sol d'origine restent en jeu tant que tu ne les masques pas
toi-même (édition des YMAP d'origine ou RemoveModelHide/CreateModelHide côté script).
"""

from __future__ import annotations

from pathlib import Path

FXMANIFEST = """-- Généré par Mio Mapping Studio
fx_version 'cerulean'
game 'gta5'

this_is_a_map 'yes'

-- Le YTYP déclare les archetypes : il doit être chargé pour que le YMAP puisse placer les entités.
{data_files}
"""


def write_resource(resource_dir: Path, name: str, files: list[str], mode: str):
    ytyps = [f for f in files if f.endswith(".ytyp")]
    data_files = "\n".join(f"data_file 'DLC_ITYP_REQUEST' 'stream/{y}'" for y in ytyps)
    (resource_dir / "fxmanifest.lua").write_text(FXMANIFEST.format(data_files=data_files), encoding="utf-8")
    has_ymap = any(f.endswith(".ymap") for f in files)
    readme = [
        f"Ressource {resource_dir.name} générée par Mio Mapping Studio.",
        "",
        "stream/ contient les fichiers streamés par FiveM :",
    ]
    readme += [f"  - {f}" for f in files]
    readme += [
        "",
        "Rôles :",
        "  - .ydr : modèle (et collision intégrée en mode statique) ;",
        "  - .ytd : textures ;",
        "  - .ybn : collision séparée (mode MLO) ;",
        "  - .ytyp : archetypes, déclaré par data_file DLC_ITYP_REQUEST dans fxmanifest.lua ;",
        "  - .ymap : placement des entités dans le monde." if has_ymap else
        "  - AUCUN .ymap : rien n'est placé en jeu. Place l'entité avec CodeWalker (ou relance l'export avec "
        "« Générer le YMAP de placement »).",
        "",
        "Les objets et collisions d'origine de GTA ne sont PAS retirés : masque-les toi-même si nécessaire.",
        "Ajoute « ensure " + resource_dir.name + " » dans server.cfg.",
    ]
    (resource_dir / "LISEZMOI.txt").write_text("\n".join(readme), encoding="utf-8")


def placement_notes(mode: str, has_ymap: bool) -> str:
    if has_ymap:
        base = ("Placement : le YMAP place l'entité à l'origine actuelle du Drawable/MLO. Pour FiveM, mets les fichiers "
                "dans stream/ et déclare le YTYP (data_file 'DLC_ITYP_REQUEST').")
    else:
        base = ("Aucun YMAP : ces fichiers sont des assets, pas une map placée. Il faut un YMAP qui place mio_xxxx "
                "(option « Générer le YMAP de placement » ou CodeWalker) et le YTYP déclaré dans fxmanifest.lua.")
    return base + " Les objets/collisions d'origine de GTA ne sont jamais supprimés automatiquement."
