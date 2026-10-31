# Étude technique

Sources examinées (code officiel, pas de mémoire ni de supposition) :

- **Sollumz 2.9.0** — https://github.com/Sollumz/Sollumz, tag `v2.9.0` (commit `389bd9b`, août 2026), et sa
  dépendance **szio 1.3.0.dev9** (PyPI, version exigée par `dependencies.py`).
- **CodeWalker** — https://github.com/dexyfex/CodeWalker, commit `485d56b` (avril 2025), projet `CodeWalker.Core`.

## 1. Versions

- `blender_manifest.toml` de Sollumz 2.9.0 : `blender_version_min = "4.2.0"`. L'addon ne vise donc que Blender ≥ 4.2.
  Testé réellement : Blender 5.2.3 LTS et 4.5.4 LTS (modules `bpy` officiels de PyPI).
- L'addon vérifie la version de Sollumz au démarrage (`sollumz_adapter.status()`), via `meta.sollumz_version()` de
  Sollumz, et refuse toute version hors de `2.9.x` avec un message en français.
- Sollumz s'appuie sur **szio** pour toutes les E/S ; le format binaire « natif » passe par **PyMateria**
  (dépendance optionnelle, `supported = sys.platform == "win32"`). Sans PyMateria, seul le XML CodeWalker est
  disponible (`IS_SZIO_NATIVE_AVAILABLE = False`).

## 2. API Sollumz réellement utilisées

| Besoin | API Sollumz 2.9.0 | Fichier |
|---|---|---|
| Types d'objets | `Object.sollum_type` = `SollumType.DRAWABLE`, `DRAWABLE_MODEL`, `BOUND_COMPOSITE`, `BOUND_GEOMETRYBVH`, `BOUND_POLY_TRIANGLE`... | `sollumz_properties.py` |
| Création d'objets | `create_empty_object(sollum_type, name)` | `tools/blenderhelper.py` |
| Conversion mesh → modèle | `convert_obj_to_model(obj)` (LOD High = mesh courant) | `tools/drawablehelper.py` |
| LOD | `obj.sz_lods.get_lod(LODLevel.X).mesh` (lecture/écriture) | `lods.py` |
| Matériaux visuels | `Material.sollum_type == MaterialType.SHADER`, `shader_properties.filename` | `ydr/properties.py` |
| Paramètres texture | nodes `ShaderNodeTexImage` dont le nom est un paramètre `TEXTURE` du shader (`ShaderManager.find_shader`) ; nom exporté = `node.sollumz_texture_name` (nom du fichier image) ; `node.texture_properties.embedded` | `ydr/ydrexport.py::create_shader`, `ydr/properties.py` |
| Matériaux de collision | `collisionmats`, `create_collision_material_from_index(i)` ; `collision_properties`, `collision_flags` | `ybn/collision_materials.py`, `ybn/properties.py` |
| Flags de collision | `composite_flags1/2` + presets `General (Default)`, `Stair mesh`... via `apply_flag_preset` | `tools/boundhelper.py`, `ybn/gta5/presets/flag_presets.json` |
| Structure collision | Composite > BVH (empty, porte les flags) > Poly Mesh (`convert_obj_to_bvh`) | `tools/boundhelper.py` |
| Collision intégrée | un seul Bound racine **enfant direct** du Drawable (`create_embedded_bounds_asset`) | `ydr/ydrexport.py` |
| Limites BVH | `MAX_VERTICES = 32767` (avertissement de l'exporteur) | `ybn/ybnexport.py` |
| YTYP | `Scene.ytyps`, `CMapTypesProperties.new_archetype(type)`, `ArchetypeProperties` (`asset_name`, `texture_dictionary`, `physics_dictionary`, `asset_type`, `flags`, `bb_min/bb_max/bs_center/bs_radius`) | `ytyp/properties/ytyp.py` |
| MLO | `new_room()`, `new_entity()`, `MloEntityProperties.attached_room_id`, `linked_object` ; `MAX_LIMBO_ROOM_ENTITIES = 12` | `ytyp/properties/mlo.py` |
| Dictionnaires de textures | `Scene.sz_txds.new_texture_dictionary(name)`, `txd.new_texture(image)` | `ytd/properties.py` |
| Export | `bpy.ops.sollumz.export_assets(directory, direct_export=True, use_custom_settings=True, target_formats, target_versions, limit_to_selected, export_ytyps...)` | `sollumz_operators.py` |
| Capture des messages | `logger.use_logger(LoggerBase)` | `logger.py` |

## 3. MLO + collision intégrée : le conflit

- `SOLLUMZ_OT_create_archetype_from_selected` refuse un asset MLO qui n'est pas un Bound Composite
  (`"MLO asset ... must be a Bound Composite!"`), avec `asset_type = ASSETLESS`. Le Bound Composite est exporté
  en `.ybn`.
- `calc_mlo_entity_transforms_from_object` calcule la position des entités du MLO **relativement à l'asset** du MLO
  (le Bound Composite) : c'est le repère local du MLO. `SOLLUMZ_OT_set_bounds_from_selection` soustrait aussi la
  position de l'asset aux bounds de room.
- CodeWalker (`WorldForm.RenderWorldCollisionMeshes`) charge la collision d'un MLO visible avec
  `gameFileCache.GetYbn(mlo.Archetype.Hash)` : **le YBN porte le nom de l'archetype MLO**.
- Collision intégrée : `create_embedded_bounds_asset` exporte le Bound Composite enfant du Drawable dans le YDR ;
  `ArchetypeProperties.update_asset` et CodeWalker `ProjectForm.NewArchetypesFromYdrs`
  (`if (ydr.Drawable.Bound != null) physicsDictionary = hash`) donnent `Physics Dictionary = nom du YDR`.

Conclusion : `mio_xxxx_col` (MLO) suppose `mio_xxxx_col.ybn`. Si la collision est intégrée à `mio_xxxx.ydr`, ce YBN
n'existe pas (référence morte) ; si on l'exporte aussi, la collision est en double. En outre un MLO exige un YMAP
(`CMloInstanceDef`) pour exister. D'où les deux modes séparés de l'addon (voir README).

## 4. Défaut d'export Sollumz corrigé par l'addon : objets à matrice monde identité

`sollumz_helper.get_parent_inverse(obj)` :

```python
if obj.matrix_world.is_identity or parent_obj is None:
    return Matrix()
```

Si un enfant du Drawable (modèle, BVH, poly mesh) a une matrice monde **identité** alors que le Drawable n'est pas à
l'origine, l'exporteur n'applique pas l'inverse de la transformation du Drawable. C'est exactement le cas d'un sol
ou d'un YBN importé à l'origine (sommets en coordonnées monde), regroupé sous un Drawable recentré.

Reproduction : [`tests/repro_sollumz_identity_offset.py`](../tests/repro_sollumz_identity_offset.py). Drawable à
(100, 200, 30), cube en coordonnées monde autour de (100, 200, 31) : attendu dans le repère du Drawable
`(-1,-1,0)..(1,1,2)`, **relu `(99,199,30)..(101,201,32)`** (visuel et collision), l'objet apparaîtrait à
(200, 400, 60) en jeu.

Correction (`geom.rebase_root`) : l'objet concerné prend la matrice monde de la racine et ses sommets sont exprimés
dans ce repère (translation pure, les normales/UV/couleurs ne changent pas), sur une **copie** du mesh s'il est
partagé. La géométrie ne bouge pas dans le monde (vérifié par les tests). L'export vérifie ensuite l'alignement en
relisant le binaire.

## 5. Origine du Drawable

CodeWalker mesure la distance de LOD d'une entité depuis sa **position** (`Renderer.cs` :
`ent.Distance = (ent.Position - Position).Length()`), pas depuis le centre de ses bounds. Garder l'origine à
(0, 0, 0) avec une géométrie loin de l'origine ferait disparaître le mapping. L'addon place donc par défaut l'origine
au centre XY / point le plus bas du mapping ; le YMAP place l'entité à cette position, sans rotation ni échelle.

## 6. Collisions : limites réelles

- 32 767 sommets par géométrie (`ybnexport.MAX_VERTICES`) ; l'exporteur se contente d'avertir : l'addon fractionne.
- Arêtes des polygones de collision sur 16 bits (`BoundPolygonTriangle`, `0xFFFF` = aucune) : l'addon limite à
  65 534 triangles par géométrie.
- BVH : Sollumz ignore volume et inertie (`volume = 1`, `inertia = 1`) ; l'avertissement numpy de division par un
  volume nul sur un plan ouvert est sans effet sur le fichier.
- Presets : `General (Default)` (bâtiment/sol/route/terrain), `Stair mesh` (escaliers) ; matériaux CONCRETE, TARMAC,
  DIRT_TRACK selon l'usage (modifiables ensuite dans Sollumz).

## 7. Textures

- Nom exporté = nom de fichier de l'image (`ytd/properties.get_texture_name`). L'import Sollumz crée, pour une
  texture non intégrée et absente, une image *placeholder* dont le chemin est `//nom.dds`. L'addon **recharge cette
  même image** depuis le DDS extrait (`nom.dds`) : matériaux, UV et Color Attributes ne sont pas modifiés et le nom
  exporté reste identique.
- Format RAGE Legacy : la taille de chaque mip est celle du précédent divisée par 4 (`TextureData.Read`, legacy) ;
  les niveaux < 4×4 d'un DDS BCn standard ne sont pas stockés (les textures du jeu s'arrêtent à 4×4, donc aucune
  perte pour elles ; MioGtaTool le signale pour un DDS externe).
- DDS ↔ YTD sans recompression : `DDSIO.GetDDSFile` / `DDSIO.GetTexture` recopient les données de pixels ;
  `build-ytd` relit le YTD écrit et compare l'empreinte des pixels de chaque texture.
- Priorité des versions : même logique que Sollumz `shared/game_assets/game_files.py` (ordre `dlclist.xml`,
  `dlcpacks` = 2·i, `dlc_patch` = 2·i+1), avec base < `update.rpf` < DLC.
- Homonymes : provenance (archetype d'origine → `textureDictionary` du YTYP → parents `gtxd.meta`/`gtxd.ymt`), puis
  copies identiques (même empreinte), sinon ambiguïté affichée et choix manuel mémorisé.
- Index : une ligne JSON par texture/archetype/relation gtxd ; signature = liste des `.rpf` racines (taille, date)
  + exécutable ; écrit dans un `.tmp` renommé à la fin (une annulation ne laisse pas d'index partiel).

## 8. Lecteur et compatibilité Legacy / Enhanced

- **CodeWalker.Core** (netstandard2.0, dépend de SharpDX 4.2.0) : compilé sans modification avec .NET 8 sous
  Linux et pour Windows x64. Il n'est pas importable depuis Python : l'addon l'appelle via l'exécutable
  **MioGtaTool** (processus séparé, sortie JSON ligne par ligne, annulation par fichier ou arrêt du processus).
- Clés : `GTA5Keys.LoadFromPath(dossier, gen9)` lit `gta5.exe` (Legacy) ou `gta5_enhanced.exe` (Enhanced) et le
  `magic.dat` intégré à CodeWalker.Core. `RpfManager.IsGen9` sélectionne la lecture des ressources Gen9.
- Textures Gen9 : `Texture.Read` convertit `G9_Format` en format Legacy (`GetLegacyFormat`) ; le DDS extrait puis le
  YTD reconstruit en mode Legacy (`RpfManager.IsGen9 = false`) sont au format attendu par FiveM.
- **FiveM utilise GTA V Legacy** : l'export vise toujours Gen8. L'option « Enhanced » ne concerne que la lecture.
- **Licence de CodeWalker** : pas de licence open source explicite dans le dépôt (`Readme_Src.txt` : « released for
  educational purposes only »). Il n'est donc pas redistribué ; `companion/build.*` le clone au commit épinglé.

## 9. Export binaire

- Avec PyMateria : Sollumz écrit directement les binaires (`target_formats={"NATIVE"}`).
- Sans PyMateria : Sollumz écrit le XML CodeWalker, compilé par `XmlMeta.GetData` de CodeWalker.Core (exactement le
  chemin d'import XML de l'interface CodeWalker, `ExploreForm`). Aucun XML n'est renommé : chaque fichier final est
  relu (en-tête RSC7 obligatoire) par `MioGtaTool verify`.
- YMAP de placement : construit avec `YmapFile`/`YmapEntityDef` de CodeWalker à partir du YTYP exporté
  (`CalcFlags`, `CalcExtents`), entité `ORPHANHD`, flag « Static entity » (32) ; instance `CMloInstanceDef` en mode MLO.
