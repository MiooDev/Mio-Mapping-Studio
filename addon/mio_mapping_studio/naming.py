"""Normalisation des noms d'assets.

« garage » -> « mio_garage » ; « Mio_Garage » -> « mio_garage » ; « mio_mio_garage » -> « mio_garage ».
Les noms GTA sont hachés (joaat) en minuscules : on n'utilise que [a-z0-9_].
"""

import re
import unicodedata

PREFIX = "mio_"
COLLISION_SUFFIX = "_col"
MAX_LEN = 48  # marge confortable sous les limites des noms de fichiers RPF / ressources FiveM


def _strip_accents(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c))


def normalize_mapping_name(raw: str) -> str:
    """Retourne le nom d'asset final (avec préfixe mio_), ou "" si le nom est vide/invalide."""
    s = _strip_accents((raw or "").strip().lower())
    s = re.sub(r"[\s\-\.]+", "_", s)
    s = re.sub(r"[^a-z0-9_]", "", s)
    s = re.sub(r"_+", "_", s).strip("_")
    # retire tous les préfixes mio_ répétés, puis en remet un seul
    while s.startswith(PREFIX):
        s = s[len(PREFIX):].lstrip("_")
    if s == "mio":
        s = ""
    if s.endswith(COLLISION_SUFFIX):
        # « garage_col » désigne la collision : le mapping s'appelle « garage »
        s = s[: -len(COLLISION_SUFFIX)].rstrip("_")
    if not s:
        return ""
    name = PREFIX + s
    return name[:MAX_LEN].rstrip("_")


def collision_name(asset_name: str) -> str:
    return asset_name + COLLISION_SUFFIX


def joaat(s: str) -> int:
    """Hash Jenkins one-at-a-time utilisé par RAGE (identique à CodeWalker JenkHash.GenHash)."""
    h = 0
    for c in s.lower().encode("utf-8"):
        h = (h + c) & 0xFFFFFFFF
        h = (h + (h << 10)) & 0xFFFFFFFF
        h ^= h >> 6
    h = (h + (h << 3)) & 0xFFFFFFFF
    h ^= h >> 11
    h = (h + (h << 15)) & 0xFFFFFFFF
    return h


def strip_blender_suffix(name: str) -> str:
    """« cs1_10_build.001 » -> « cs1_10_build » (même règle que Sollumz remove_number_suffix)."""
    m = re.search(r"\.[0-9]", name)
    return name if m is None else name[: m.start()]
