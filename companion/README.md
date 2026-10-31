# MioGtaTool — outil compagnon de Mio Mapping Studio

Exécutable .NET 8 qui utilise **CodeWalker.Core** (https://github.com/dexyfex/CodeWalker) pour :

| Commande | Rôle |
|---|---|
| `index` | Parcourt toutes les archives `.rpf` (lecture seule) et écrit l'index JSONL des textures (`.ytd`, et `.ydr/.ydd/.yft` avec `--embedded`), des archetypes (`.ytyp`), des dictionnaires parents (`gtxd`) et de l'ordre des DLC. |
| `signature` | Signature de l'installation (détection d'un index périmé). |
| `extract` | Extrait des textures précises en DDS, sans recompression, + métadonnées d'origine (usage, flags). |
| `build-ytd` | Construit un `.ytd` binaire à partir de DDS et le relit pour vérifier pixels, formats et mips. |
| `xml2bin` | Compile un XML CodeWalker (`.ydr.xml`, `.ybn.xml`, `.ytyp.xml`, `.ytd.xml`, `.ymap.xml`) en binaire avec les importeurs de CodeWalker.Core. |
| `verify` | Relit des binaires et décrit leur contenu (bounds, collision intégrée, textures, archetypes, rooms, entités). |
| `make-ymap` | Crée un YMAP de placement à partir du YTYP exporté. |
| `dev-make-rpf` | **Tests uniquement** : fausse installation avec archives RPF non chiffrées. |

Sortie : une ligne JSON par événement (`progress`, `log`, `result`). Annulation : `--cancel-file F` (l'outil s'arrête
dès que le fichier existe) ou arrêt du processus. Un index n'est écrit qu'en fin de traitement (fichier `.tmp`
renommé).

## Compilation

CodeWalker.Core n'est **pas inclus** dans ce dépôt (aucune licence open source explicite : « released for
educational purposes only »). Les scripts le clonent depuis le dépôt officiel au commit de `CODEWALKER_COMMIT.txt`
(`485d56bec00262ed7fa472261cce7bbc6202b96e`) et compilent localement.

Prérequis : Git, SDK .NET 8.

Windows (exécutable autonome, ne nécessite pas d'installer .NET pour l'utiliser) :

```bash
powershell -ExecutionPolicy Bypass -File build.ps1
```

→ `publish\win-x64\MioGtaTool.exe`. Indique ce chemin dans les préférences de l'addon.

Linux / macOS (tests) :

```bash
./build.sh
```

## Clés de déchiffrement

`index` et `extract` chargent les clés comme CodeWalker : `GTA5Keys.LoadFromPath(<dossier GTA>, gen9)` lit
`GTA5.exe` (Legacy) ou `GTA5_Enhanced.exe` (`--gen9`) et le `magic.dat` intégré à CodeWalker.Core. L'installation
n'est jamais modifiée. `--no-keys` (tests) n'ouvre que les archives non chiffrées.
