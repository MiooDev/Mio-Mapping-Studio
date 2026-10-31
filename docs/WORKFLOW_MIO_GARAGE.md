# Exemple de workflow : mio_garage

Objectif : reprendre un garage du jeu avec son sol et ses collisions, découpés, et l'exporter pour FiveM.

## 0. Travail manuel (avant l'addon)

1. Avec Sollumz, importe le YDR du garage, le(s) YDR du sol autour et le(s) YBN de collision de la zone
   (par ex. exportés en XML depuis CodeWalker, ou importés directement en binaire si PyMateria est installé).
   Place le garage à sa position monde (import du YMAP d'origine avec « instancier les entités », ou à la main).
2. Découpe toi-même le sol visible et les collisions pour ne garder que la zone voulue.
3. Si le sol est une instance de collection, rends-la réelle (Objet > Appliquer > Rendre les instances réelles).

## 1. Configuration

Onglet **Mio Mapping Studio** (N) :

| Champ | Valeur |
|---|---|
| Nom du mapping | `garage` → l'addon affiche « Asset : mio_garage » |
| Objet racine du mapping | vide (on utilise la sélection) |
| Objet racine collision | le Bound Composite du YBN importé (ex. `hei_cs1_..._col`) |
| Chemin GTA V | `C:\Program Files\Rockstar Games\Grand Theft Auto V` |
| Génération du jeu | GTA V Legacy |
| Dossier d'export | `D:\fivem\mio_garage_export` |
| Mode | Mapping statique + collision intégrée |

## 2. Étapes

1. Sélectionne le Drawable du garage et celui du sol → **Préparer le mapping**.
   Résultat : Drawable `mio_garage` (origine au centre bas du mapping), modèles d'origine dessous (non fusionnés),
   collision renommée `mio_garage_col`. Les Drawables d'origine vidés sont rangés dans `MIO_ARCHIVE_mio_garage`.
   *Pas de collision importée ?* Choisis l'usage (Bâtiment / sol) puis **Créer les collisions depuis le mapping**.
2. **Trouver les textures GTA et créer le YTD**. La première fois, l'index du jeu est construit (progression,
   Annuler possible). Dans la liste : vert = trouvée, « ? » = ambiguë (sélectionne-la, choisis la source,
   **Utiliser cette source**, puis relance le bouton), rouge = manquante.
3. **Créer / mettre à jour le YTYP** → archetype Base `mio_garage` (txd `mio_garage`).
4. Étape 4 : « Non applicable » en mode statique.
5. **Intégrer les collisions au mapping** → `mio_garage_col` devient l'enfant direct de `mio_garage` ;
   l'étape 3 est mise à jour automatiquement (Physics Dictionary = `mio_garage`).
6. Coche **Générer le YMAP de placement** et **Générer une ressource FiveM** (nom : `garage`), puis
   **Vérifier et exporter**.

Résultat :

```
D:\fivem\mio_garage_export\
  mio_garage\                 ressource FiveM
    fxmanifest.lua            this_is_a_map + data_file 'DLC_ITYP_REQUEST' 'stream/mio_garage.ytyp'
    LISEZMOI.txt
    stream\
      mio_garage.ydr          visuel + collision intégrée
      mio_garage.ytd          textures d'origine nécessaires
      mio_garage.ytyp         archetype Base mio_garage
      mio_garage.ymap         entité mio_garage à sa position monde
  mio_garage_rapport.txt      rapport de vérification
```

Copie le dossier `mio_garage` dans `resources/` de ton serveur et ajoute `ensure mio_garage` dans `server.cfg`.
Le garage et le sol d'origine de GTA restent présents en jeu : masque-les toi-même si tu veux éviter le doublon.

## Variante MLO (intérieur)

Mode **MLO limbo + collision YBN** :
1. Étapes 1 à 3 identiques.
2. Étape 5 : **Aligner la collision MLO** (la collision reste séparée, origine = celle du Drawable).
3. Étape 4 : **Configurer le MLO limbo** (marge XY 0,50 m) → archetype MLO `mio_garage_col`, room `limbo`, entité
   `mio_garage` attachée.
4. **Vérifier et exporter** → 5 fichiers : `mio_garage.ydr` (sans collision), `mio_garage.ytd`,
   `mio_garage_col.ybn`, `mio_garage.ytyp` (Base + MLO), `mio_garage.ymap` (instance du MLO).
