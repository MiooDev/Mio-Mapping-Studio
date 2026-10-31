# Bilan des tests

## Environnement réellement utilisé

| Élément | Version |
|---|---|
| Système | Linux (Ubuntu 24.04, conteneur, sans interface graphique) |
| Blender | module Python officiel `bpy` **5.2.3 LTS** (Python 3.13) et **4.5.4 LTS** (Python 3.11), PyPI |
| Sollumz | **2.9.0** (tag officiel `v2.9.0`), dépendance **szio 1.3.0.dev9** |
| PyMateria | **absent** (uniquement Windows) → chemin « XML CodeWalker + compilation MioGtaTool » |
| .NET | SDK 8.0.133 |
| MioGtaTool | compilé depuis ce dépôt + CodeWalker.Core commit `485d56b` (Linux x64 exécuté ; Windows x64 compilé seulement) |

Données de test : **100 % synthétiques**, aucun fichier Rockstar. `tests/make_fixtures.py` crée des assets avec
l'API de Sollumz, les exporte en XML CodeWalker, puis `tests/test_workflow.py` les **réimporte avec l'importeur
officiel de Sollumz** (comme un utilisateur) et pilote l'addon par ses opérateurs (les mêmes que les boutons).
Une fausse installation « GTA V » est construite avec de vraies archives RPF7 **non chiffrées** (format OpenIV,
`RpfEncryption.OPEN`), contenant des YTD, un YTYP, un `gtxd.meta`, un `dlclist.xml` et un DLC.

Commande : `tests/run_tests.sh` (voir l'en-tête du script). Rapports bruts :
[`tests/reports/`](../tests/reports/).

## Résultats

| Scénario | Vérifications | Blender 5.2.3 | Blender 4.5.4 |
|---|---|---|---|
| Mode statique : collisions importées, terrain multicouche, textures, relance, export embedded | 64 | ✅ 64/64 | ✅ 64/64 |
| Génération des collisions depuis le visuel + YMAP + ressource FiveM | 16 | ✅ 16/16 | ✅ 16/16 |
| Fractionnement BVH (53 361 sommets) | 4 | ✅ 4/4 | ✅ 4/4 |
| Mode MLO limbo (5 fichiers) + refus du montage MLO/statique invalide | 16 | ✅ 16/16 | ✅ 16/16 |
| Entrées invalides | 3 | ✅ 3/3 | ✅ 3/3 |
| Collision `mio_xxxx_col` existante non désignée + origine (0,0,0) loin du mapping (cas réel signalé) | 5 | ✅ 5/5 | non relancé |
| Pilote asynchrone (tâche de fond), progression, annulation | 7 | ✅ 7/7 | ✅ 7/7 |
| Interface : chaque panneau exécuté avec un layout simulé (icônes, propriétés, opérateurs) | 2 | ✅ 2/2 | ✅ 2/2 |
| **Total** | **117** | **117/117** | **112/112** (avant l'ajout du test ci-dessus) |

### Ce que couvrent ces vérifications
- **Collisions importées** : YBN importé par Sollumz (BVH à matrice identité), désigné comme racine, renommé
  `mio_garage_col`, non déplacé (sommets monde identiques à 1e-4), intégré au Drawable puis relu dans le YDR.
- **Génération depuis le visuel** : copie indépendante (meshes distincts), matériaux visuels absents de la copie,
  matériau CONCRETE valide, preset « General (Default) » appliqué, un seul LOD (High), faces de décal exclues,
  alignement monde, pas de remplacement sans action explicite, régénération sans doublon.
- **Terrain multicouche** : shader `terrain_cb_w_4lyr.sps`, les 8 paramètres de texture analysés.
- **Textures** : slot inutilisé ignoré ; homonyme résolu par la provenance (archetype → dictionnaire du YTYP) ;
  dictionnaire parent via `gtxd.meta` ; copies identiques sans ambiguïté ; version DLC prioritaire sur la base
  (ordre `dlclist.xml`) ; vraie ambiguïté signalée puis choix manuel mémorisé ; texture manquante signalée et
  export complet refusé ; mode secours DDS local signalé comme tel ; texture intégrée au modèle importé déplacée dans
  le YTD sans doublon ; **pixels DDS identiques octet pour octet aux originaux** ; images Blender rechargées sans
  changer le nom de texture, les UV ni les Color Attributes ; YTD binaire relu par CodeWalker.Core.
- **Hiérarchie** : 2 modèles regroupés sans fusion, LOD Medium conservé, UV / Color Attributes / matériaux
  inchangés, origine au centre bas, sol à l'origine ré-exprimé correctement.
- **Export embedded** : fichiers RSC7 (aucun XML renommé), collision Composite présente dans le YDR, **AABB de la
  collision relue = AABB Blender à ±1 cm dans le repère du Drawable**, boîtes BVH cohérentes avec leurs sommets,
  bounds visuels relus = géométrie, textures référencées toutes présentes, YTYP relu (Asset Name, Texture Dictionary,
  Physics Dictionary = `mio_garage`, `ASSET_TYPE_DRAWABLE`, flag Static, BBMin/BBMax = géométrie exportée).
- **Relance complète** : aucun objet, matériau, YTYP, archetype ou dictionnaire de textures dupliqué ; ancien export
  sauvegardé ; aucun dossier temporaire laissé ; **installation GTA inchangée** (empreinte de tous les fichiers).
- **MLO** : collision séparée alignée, room nommée exactement `limbo`, BBMin X/Y −0,50 et BBMax X/Y +0,50 dans le
  repère local du MLO, hauteur conservée, entité attachée, aucun portal, 5 fichiers, YDR sans collision, YBN aligné,
  YTYP relu (archetype `CMloArchetypeDef`, room limbo, entité attachée), YMAP avec instance MLO.
- **Montage invalide** : archetype MLO laissé en mode statique → export refusé, rien d'écrit ; accepté après retrait.

### Défaut Sollumz mis en évidence (et corrigé par l'addon)
[`tests/repro_sollumz_identity_offset.py`](../tests/repro_sollumz_identity_offset.py) : avec Sollumz 2.9.0, un enfant
à matrice monde identité sous un Drawable à (100, 200, 30) est exporté à `(99,199,30)..(101,201,32)` au lieu de
`(-1,-1,0)..(1,1,2)`. Les tests montrent que l'addon produit des fichiers alignés dans ce cas.

### Messages observés, sans effet
- Sollumz affiche un avertissement numpy (division par un volume nul) pour un plan de collision ouvert : pour un
  BVH, Sollumz n'utilise pas cette valeur (volume et inertie fixés à 1).
- Le module `bpy` de Blender 4.5 peut rester bloqué à la fermeture de l'interpréteur Python : les scripts de test se
  terminent par `os._exit`. Ce point concerne le module `bpy` en ligne de commande, pas Blender lancé normalement.

## Ce qui n'a PAS été testé (environnement indisponible)

- **Vraie installation GTA V** : archives chiffrées AES/NG, clés extraites de `GTA5.exe` / `GTA5_Enhanced.exe`,
  taille et durée réelles de l'index, vrais `gtxd`/`dlclist` Rockstar, textures Gen9 d'Enhanced. Le code de clés est
  celui de CodeWalker (`GTA5Keys.LoadFromPath`), mais il n'a pas été exécuté ici.
- **Windows** : `MioGtaTool.exe` (win-x64 autonome) a été **compilé** mais pas exécuté ; l'addon n'a pas tourné sous
  Windows.
- **Export natif PyMateria** (binaire direct par Sollumz) : non disponible sous Linux ; seul le chemin XML +
  compilation CodeWalker.Core a été testé.
- **Interface CodeWalker** (application WinForms/DirectX) : les fichiers ont été relus avec **CodeWalker.Core**
  (les mêmes chargeurs de fichiers que l'application), pas ouverts dans l'interface graphique de CodeWalker.
- **FiveM en jeu** : non disponible. Le chargement, la collision et l'affichage en jeu ne sont pas vérifiés.
- **Interface Blender réelle** : pas de fenêtre disponible. Les panneaux ont été exécutés avec un layout simulé et
  l'opérateur modal via son pilote asynchrone ; l'affichage visuel et les clics n'ont pas été testés.
- **Blender 4.2 LTS** : autorisé par le manifeste de Sollumz, non testé.
- Performances sur un vrai mapping volumineux.

À faire chez toi avant usage en production : compiler `MioGtaTool.exe`, lancer une première indexation sur ton
installation, ouvrir les fichiers exportés dans CodeWalker et tester la ressource dans FiveM.
