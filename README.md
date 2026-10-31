# Mio Mapping Studio

Addon Blender pour préparer un mapping GTA V / FiveM avec **Sollumz** : hiérarchie Drawable, collisions,
récupération des **textures originales** depuis ton installation GTA V, création du **YTD binaire**, du **YTYP**,
et **export vérifié** (relecture des fichiers binaires avec CodeWalker.Core).

Tu fais toi-même l'import du bâtiment, du sol et des collisions avec Sollumz, et la découpe. L'addon automatise
tout le reste, dans l'onglet **« Mio Mapping Studio »** de la barre latérale **N** de la vue 3D.

---

## Conclusion technique : MLO et collision intégrée

Le montage « archetype Base `mio_xxxx` + archetype MLO `mio_xxxx_col` avec room limbo + collision intégrée au
modèle, avec seulement `mio_xxxx.ydr`, `mio_xxxx.ytd` et `mio_xxxx.ytyp` » **n'est pas cohérent**. Vérifié dans le
code de Sollumz 2.9.0 et de CodeWalker :

1. **Un archetype MLO a pour asset un Bound Composite**, exporté en `.ybn` du même nom
   (Sollumz `ytyp/operators/ytyp.py` : *« MLO asset must be a Bound Composite »*, type d'asset `ASSETLESS`).
   CodeWalker charge la collision d'un intérieur **par le nom de l'archetype MLO**
   (`WorldForm.cs` : `gameFileCache.GetYbn(mlo.Archetype.Hash)`). `mio_xxxx_col` désigne donc le fichier
   `mio_xxxx_col.ybn`.
2. **Intégrer la collision au modèle** la place dans `mio_xxxx.ydr` (Bound Composite enfant direct du Drawable,
   Sollumz `ydr/ydrexport.py::create_embedded_bounds_asset`), avec `Physics Dictionary = mio_xxxx`
   (règle de Sollumz `ArchetypeProperties.update_asset` et de CodeWalker `NewArchetypesFromYdrs`).
3. Avec seulement 3 fichiers, l'archetype MLO pointerait vers un `mio_xxxx_col.ybn` **inexistant** ; et si on
   l'exportait en plus, la collision serait **en double**. Un MLO n'existe par ailleurs en jeu que s'il est
   **placé par un YMAP** (`CMloInstanceDef`), et son entité `mio_xxxx` doit être déclarée dans le MLO et attachée à
   la room limbo (12 entités max selon Sollumz).

L'addon propose donc **deux modes distincts, affichés dans l'interface** :

| Mode | Fichiers produits | Collision | MLO |
|---|---|---|---|
| **Mapping statique + collision intégrée** (défaut) | `mio_xxxx.ydr`, `mio_xxxx.ytd`, `mio_xxxx.ytyp` (+ `mio_xxxx.ymap` optionnel) | intégrée au YDR, `Physics Dictionary = mio_xxxx` | aucun |
| **MLO limbo + collision YBN** | `mio_xxxx.ydr`, `mio_xxxx.ytd`, `mio_xxxx_col.ybn`, `mio_xxxx.ytyp`, `mio_xxxx.ymap` | fichier séparé `mio_xxxx_col.ybn` | `mio_xxxx_col`, room `limbo`, entité `mio_xxxx` |

Un mapping extérieur n'a pas besoin d'être transformé en intérieur pour avoir une collision : utilise le mode
statique. Un montage invalide (par ex. un archetype MLO resté dans le YTYP en mode statique) **bloque l'export**
avec un message et un bouton de correction ; rien n'est exporté silencieusement.

Détails et références de code : [docs/ETUDE_TECHNIQUE.md](docs/ETUDE_TECHNIQUE.md).

---

## Versions prises en charge

| Composant | Pris en charge | Testé |
|---|---|---|
| Blender | **4.5 LTS et 5.2 LTS** ; 4.2 LTS accepté (minimum de Sollumz 2.9.0) mais non testé | **5.2.3 LTS** et **4.5.4 LTS** (module `bpy`, Linux, sans interface) — 112/112 vérifications chacune |
| Sollumz | **2.9.x uniquement** (vérifié au démarrage) | **2.9.0** |
| Export binaire | natif Sollumz (PyMateria, Windows) **ou** XML CodeWalker compilé par MioGtaTool | XML + MioGtaTool (PyMateria indisponible sous Linux) |
| Jeu lu | GTA V **Legacy** (`GTA5.exe`) et **Enhanced** (`GTA5_Enhanced.exe`, textures Gen9 relues en format Legacy) | archives de test non chiffrées uniquement (voir bilan) |
| Cible d'export | **GTA V Legacy / FiveM (Gen8)** — FiveM utilise la version Legacy | oui (relecture CodeWalker.Core) |
| Outil compagnon | MioGtaTool (.NET 8) basé sur CodeWalker.Core, commit `485d56b` | compilé pour Linux (testé) et Windows x64 (compilé, non exécuté) |

Toutes les différences d'API Sollumz sont centralisées dans
[`addon/mio_mapping_studio/sollumz_adapter.py`](addon/mio_mapping_studio/sollumz_adapter.py).

---

## Installation

### 1. Sollumz 2.9.x
Installe Sollumz 2.9 (https://docs.sollumz.org), active-le, puis installe ses dépendances depuis ses préférences.
Optionnel (Windows) : installe aussi **PyMateria** dans les préférences de Sollumz pour l'export binaire natif.
Sans PyMateria, Mio Mapping Studio exporte en XML CodeWalker et le compile en binaire avec MioGtaTool.

### 2. L'addon
`Edit > Preferences > Add-ons > Install from Disk…` et choisis
[`dist/mio_mapping_studio-1.0.0.zip`](dist/mio_mapping_studio-1.0.0.zip). Active « Mio Mapping Studio ».

### 3. L'outil compagnon MioGtaTool (obligatoire)
Il lit les archives RPF du jeu (en lecture seule), extrait les DDS d'origine, construit le YTD binaire, compile le
XML CodeWalker et relit les fichiers exportés. Il s'appuie sur **CodeWalker.Core**, qui n'a pas de licence open source
explicite (« released for educational purposes only ») : il n'est donc **pas redistribué** ici. Le script le
télécharge depuis le dépôt officiel au commit épinglé et compile sur ta machine.

Prérequis : [Git](https://git-scm.com) et le [SDK .NET 8](https://dotnet.microsoft.com/download/dotnet/8.0).

```bash
cd companion
```

```bash
powershell -ExecutionPolicy Bypass -File build.ps1
```

Résultat : `companion\publish\win-x64\MioGtaTool.exe` (autonome). Détails : [companion/README.md](companion/README.md).

### 4. Configuration initiale
1. `Preferences > Add-ons > Mio Mapping Studio` : indique le chemin de `MioGtaTool.exe`, puis clique
   **Vérifier les dépendances** (Sollumz, PyMateria, outil compagnon).
2. Dans l'onglet **Mio Mapping Studio** (touche N dans la vue 3D) : **Chemin GTA V** (dossier contenant
   `GTA5.exe` ou `GTA5_Enhanced.exe`), **Génération du jeu**, **Dossier d'export**, **Mode d'export**.
3. Première recherche de textures : l'index des textures du jeu est construit une fois (plusieurs minutes, avec
   progression et bouton **Annuler**), puis réutilisé. Il est reconstruit automatiquement si l'installation change
   (mise à jour, DLC), ou à la demande avec **Reconstruire l'index**.

---

## Utilisation (ordre de l'onglet)

Chaque étape affiche son état réel : **À faire / Prêt / Avertissement / Erreur** (+ « Non applicable ») et un
diagnostic en français. **Actualiser le diagnostic** revérifie tout sans rien modifier. Toutes les modifications de
scène sont annulables (Ctrl+Z).

1. **Préparer le mapping / collisions** — `Préparer le mapping` regroupe les objets choisis (objet racine) ou
   sélectionnés — jamais toute la scène — sous un Drawable `mio_xxxx`. Les meshes ne sont pas fusionnés ; UV,
   Color Attributes, matériaux, shaders, paramètres et LOD sont conservés ; les positions dans le monde ne changent
   pas. La collision désignée devient le Bound Composite `mio_xxxx_col`.
   `Créer les collisions depuis le mapping` crée une copie indépendante du visuel (un seul LOD), en Poly Mesh sous
   Composite > BVH, avec un vrai matériau de collision et les flags de l'usage choisi, fractionnée selon les limites
   réelles de l'exporteur (32 767 sommets). Elle ne remplace jamais une collision existante sans action explicite.
2. **Trouver les textures et créer le YTD** — analyse uniquement les matériaux utilisés par des faces, retrouve
   chaque texture par son nom GTA dans l'index (provenance, dictionnaires parents gtxd, versions DLC), affiche les
   ambiguïtés (tu choisis la source), extrait les DDS **sans recompression**, recharge les images Blender et
   construit `mio_xxxx.ytd` (binaire). Bilan : nécessaires / trouvées / ambiguës / manquantes / taille.
3. **Créer ou mettre à jour le YTYP** — archetype Base `mio_xxxx` (Asset Name, Texture Dictionary, Physics
   Dictionary, Asset Type Drawable, flag Static, bounds), sans doublon.
4. **Configurer le MLO / limbo** — mode MLO uniquement : archetype MLO `mio_xxxx_col` relié au Bound Composite,
   room `limbo` avec marge XY symétrique (0,50 m par défaut) et marge Z optionnelle, entité `mio_xxxx`. Aucun
   portal n'est créé.
5. **Intégrer les collisions** — mode statique : le Bound Composite devient l'enfant direct du Drawable
   (collision embedded), sans Ctrl+J. Mode MLO : la collision reste séparée et alignée.
6. **Vérifier et exporter** — vérifie tout, exporte dans un dossier temporaire, relit les binaires (collision
   présente et alignée, textures, références YTYP), puis remplace l'export existant (l'ancien est sauvegardé dans
   `.mio_backup`). Options : YMAP de placement, ressource FiveM (`fxmanifest.lua` + `stream/`).

Exemple complet : [docs/WORKFLOW_MIO_GARAGE.md](docs/WORKFLOW_MIO_GARAGE.md).

### Placement dans FiveM
Les fichiers exportés sont des **assets**, pas une map placée :
- le **YMAP** place l'entité (ou l'instance MLO) dans le monde ;
- le **YTYP** doit être chargé : `data_file 'DLC_ITYP_REQUEST' 'stream/mio_xxxx.ytyp'` dans `fxmanifest.lua` ;
- l'option « ressource FiveM » génère ce `fxmanifest.lua`, mais **ne retire jamais** les objets ni les collisions
  d'origine de GTA : masque-les toi-même si nécessaire.

---

## Ce que l'addon ne fait pas
- Pas d'éditeur de découpe (tu découpes toi-même).
- Pas de simplification automatique de la collision (option Decimate explicite seulement).
- Pas de conception de rooms/portals pour un vrai intérieur à plusieurs pièces.
- Pas de suppression d'objets du monde GTA d'origine.
- Aucune texture GTA n'est distribuée : elles sont extraites localement depuis ton installation, qui n'est
  jamais modifiée.

## Tests
Bilan détaillé et honnête : [docs/BILAN_TESTS.md](docs/BILAN_TESTS.md). Suite automatisée : [`tests/`](tests/).

## Structure
```
addon/mio_mapping_studio/   source de l'addon (sollumz_adapter.py = seul accès aux API Sollumz)
companion/                  outil compagnon MioGtaTool (C#, CodeWalker.Core récupéré à la compilation)
dist/                       ZIP installable
docs/                       étude technique, workflow, bilan des tests
tests/                      tests de bout en bout (Blender en module + fausse installation GTA)
scripts/build_zip.py        reconstruit le ZIP
```

## Licence
Addon et outil compagnon : GPL-3.0-or-later (voir [LICENSE](LICENSE)). Sollumz : GPL-3.0. CodeWalker : non
redistribué (voir ci-dessus).
