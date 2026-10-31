"""Résolution d'une référence de texture vers UNE source, sans choix arbitraire.

Ordre de décision :
  1. choix manuel de l'utilisateur (si la source existe encore) ;
  2. texture intégrée au modèle importé, présente dans le .blend (provenance exacte) ;
  3. provenance via l'index : archetype d'origine du modèle -> son dictionnaire (YTYP) -> dictionnaires parents
     (gtxd), puis textures intégrées au modèle d'origine ;
  4. une seule source dans le jeu, ou plusieurs copies au contenu identique (même empreinte des pixels) ;
  5. sinon : AMBIGUË (plusieurs dictionnaires contiennent une texture homonyme différente) -> choix demandé.
Les « versions » d'un même dictionnaire (jeu de base, update.rpf, DLC, patch DLC) ne sont pas des homonymes : la
plus prioritaire selon l'ordre de chargement du jeu (dlclist.xml) l'emporte.
Mode de secours : un DDS déjà présent sur le disque n'est utilisé que si la texture est absente de l'index du jeu,
et il est signalé comme tel. Ce module n'importe pas bpy.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..naming import joaat
from .index import IndexSlice


@dataclass
class Candidate:
    kind: str                 # SCENE | GAME | LOCAL
    path: str                 # chemin RPF, "scene" ou chemin de fichier
    dict_name: str = ""
    source_type: str = ""     # ytd | ydr | ydd | yft
    width: int = 0
    height: int = 0
    fmt: str = ""
    mips: int = 0
    priority: int = 0
    data_hash: str = ""
    note: str = ""

    @property
    def key(self) -> str:
        return f"{self.kind}:{self.path}"


@dataclass
class Resolution:
    name: str
    status: str               # FOUND | AMBIGUOUS | MISSING | INVALID
    candidates: list = field(default_factory=list)
    chosen: int = -1
    reason: str = ""

    @property
    def chosen_candidate(self) -> Candidate | None:
        return self.candidates[self.chosen] if 0 <= self.chosen < len(self.candidates) else None


def txd_chain(source_asset: str, sl: IndexSlice) -> list[str]:
    """Dictionnaire de l'archetype d'origine puis ses parents (gtxd), sans boucle."""
    arch = sl.archetypes.get(joaat(source_asset))
    chain: list[str] = []
    cur = (arch or {}).get("t") or ""
    while cur and cur not in chain and len(chain) < 16:
        chain.append(cur)
        cur = sl.gtxd.get(cur, "")
    return chain


def game_candidates(name: str, sl: IndexSlice) -> list[Candidate]:
    """Une candidate par dictionnaire distinct ; pour un même dictionnaire, la version la plus prioritaire."""
    best: dict[tuple, dict] = {}
    versions: dict[tuple, int] = {}
    for r in sl.textures.get(name, []):
        k = (r.get("d", ""), r.get("s", ""))
        versions[k] = versions.get(k, 0) + 1
        if k not in best or r.get("pr", 0) > best[k].get("pr", 0) or (
                r.get("pr", 0) == best[k].get("pr", 0) and r.get("p", "") > best[k].get("p", "")):
            best[k] = r
    out = []
    for k, r in best.items():
        note = f"{versions[k]} version(s) ; la plus prioritaire est retenue" if versions[k] > 1 else ""
        out.append(Candidate("GAME", r["p"], r.get("d", ""), r.get("s", ""), r.get("w", 0), r.get("h", 0),
                             r.get("f", ""), r.get("m", 0), r.get("pr", 0), r.get("x", ""), note))
    out.sort(key=lambda c: (-c.priority, c.path))
    return out


def resolve(ref, sl: IndexSlice | None, user_choice: str = "") -> Resolution:
    """`ref` : textures.refs.TextureRef (ou objet équivalent)."""
    cands: list[Candidate] = []
    if ref.scene_state == "PACKED_DDS":
        cands.append(Candidate("SCENE", "scene", note="texture intégrée au modèle importé" if ref.embedded
                               else "image DDS empaquetée dans le .blend"))
    game = game_candidates(ref.name, sl) if sl is not None else []
    cands.extend(game)
    if ref.scene_state == "FILE_DDS":
        cands.append(Candidate("LOCAL", ref.scene_dds, note="DDS déjà présent sur le disque (secours)"))

    res = Resolution(ref.name, "MISSING", cands)

    def pick(c: Candidate, reason: str) -> Resolution:
        res.status = "FOUND"
        res.chosen = cands.index(c)
        res.reason = reason
        return res

    if user_choice:
        for c in cands:
            if c.key == user_choice:
                return pick(c, "Choix manuel")

    scene = [c for c in cands if c.kind == "SCENE"]
    if scene and ref.embedded:
        return pick(scene[0], "Texture intégrée au modèle importé (provenance exacte)")

    if game:
        best = None  # (profondeur, candidate, raison)
        for src in sorted(ref.sources):
            own = [c for c in game if c.dict_name == src and c.source_type in ("ydr", "ydd", "yft")]
            if own and (best is None or best[0] > -1):
                best = (-1, own[0], f"Texture intégrée au modèle d'origine « {src} »")
            for depth, txd in enumerate(txd_chain(src, sl)):
                m = [c for c in game if c.dict_name == txd]
                if m and (best is None or depth < best[0]):
                    why = (f"Dictionnaire de l'archetype d'origine « {src} » ({txd})" if depth == 0 else
                           f"Dictionnaire parent (gtxd) de « {src} » : {txd}")
                    best = (depth, m[0], why)
                    break
        if best is not None:
            return pick(best[1], best[2])
        if len(game) == 1:
            return pick(game[0], f"Unique dans l'installation ({game[0].dict_name})")
        hashes = {c.data_hash for c in game}
        if len(hashes) == 1 and "" not in hashes:
            return pick(game[0], f"{len(game)} copies identiques (mêmes pixels) : {game[0].dict_name} retenu")
        res.status = "AMBIGUOUS"
        res.reason = (f"{len(game)} dictionnaires contiennent une texture « {ref.name} » différente et la provenance "
                      "ne permet pas de trancher : choisis la source.")
        return res

    local = [c for c in cands if c.kind == "LOCAL"]
    if local:
        return pick(local[0], "Absente de l'index du jeu : DDS local utilisé (mode de secours, à vérifier)")
    if scene:
        return pick(scene[0], "Image DDS empaquetée dans le .blend (absente de l'index du jeu)")
    if ref.scene_state == "FILE_OTHER":
        res.status = "INVALID"
        res.reason = ("Image non-DDS et absente du jeu : convertis-la en DDS toi-même (aucune recompression "
                      "automatique).")
        return res
    res.status = "MISSING"
    res.reason = ("Introuvable dans l'index du jeu" if sl is not None else "Index du jeu indisponible") + \
        " : vérifie le chemin GTA V, la génération Legacy/Enhanced et l'option mods."
    return res
