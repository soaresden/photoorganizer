# Changelog

Toutes les évolutions notables de TriPhoto. / All notable changes to TriPhoto.

Format : [Semantic Versioning](https://semver.org/)

---

## [v6.0.0] — 2026-08-04

Réécriture complète de l'interface en **PySide6 (Qt)** et ajout d'un moteur de
comparaison de contenu. / Full UI rewrite in **PySide6 (Qt)** plus a content
comparison engine.

### ⚠️ Changements incompatibles / Breaking changes
- Interface Tkinter remplacée par PySide6 — `pip install -r requirements.txt` requis.
  / Tkinter UI replaced by PySide6 — `pip install -r requirements.txt` required.
- Les doublons ignorés sont désormais mémorisés par **paire de chemins** et non par nom
  de fichier. Les anciennes entrées restent honorées.
  / Ignored duplicates are now keyed by **path pair** instead of filename. Legacy
  entries are still honoured.

### ✨ Ajouté / Added
- **Onglet Visualiseur** : arborescence années → dossiers → grille de vignettes triée
  alphabétiquement, avec renommage, ouverture et suppression sur la sélection.
  / **Viewer tab**: years → folders → alphabetically sorted thumbnail grid, with
  rename, open and delete on the selection.
- **Frise chronologique** : un point par média, graduations adaptatives (heures, jours,
  mois, années), interrupteur *vue année* (01/01 → 31/12), sélection croisée avec la
  grille. / **Timeline**: one dot per media, adaptive graduations, *year view* switch,
  two-way selection with the grid.
- **Comparaison de contenu** des doublons sur trois critères : taille, empreinte
  perceptuelle *dHash* de l'image affichée, durée pour les vidéos. Les vidéos sont
  comparées image par image sur 5 points de leur timeline.
  / **Content comparison** on three criteria: size, *dHash* perceptual fingerprint,
  duration for videos. Videos compared frame by frame at 5 timeline points.
- Colonne **Score** remplie en tâche de fond, triable numériquement.
  / **Score** column filled in the background, numerically sortable.
- **Diaporama vidéo** dans l'onglet Doublons (10/30/50/70/90 % de la durée), synchronisé
  entre les deux copies. / **Video slideshow** in the Duplicates tab, synced across both
  copies.
- **Surlignage des différences** entre deux chemins, jusqu'au caractère près.
  / **Difference highlighting** between two paths, down to the character.
- Détection élargie des copies : `_1`, `-1`, `~1`, `(1)`, `- Copie`, `_copy`, `copy 2`,
  `kopie`, `copia`. / Broader copy detection.
- Colonne **Date et heure** triable, tri chronologique par défaut.
  / Sortable **Date and time** column, chronological sort by default.
- Menus contextuels : renommer un média, un dossier, ouvrir, corbeille, ignorer.
  / Context menus: rename a media or a folder, open, recycle, ignore.
- Colonnes redimensionnables, déplaçables et triables ; largeurs et tri mémorisés.
  / Resizable, movable and sortable columns; widths and sort order remembered.
- Résolution de ffmpeg : dossier configuré → dossier du script → `PATH` →
  `imageio-ffmpeg`, avec journal des chemins testés.
  / ffmpeg resolution with a log of every path tried.
- Sauvegarde `.bak` automatique si le fichier de tags devait rétrécir.
  / Automatic `.bak` backup if the tag file would shrink.

### 🚀 Performances
- Décodage des images hors du thread graphique, en mode *draft* libjpeg.
  / Image decoding off the GUI thread, using libjpeg *draft* mode.
- Préchargement des photos voisines ; pool de 4 threads pour les vignettes ; caches
  mémoire. / Neighbour prefetching; 4-thread thumbnail pool; in-memory caches.
- Suppression sans reconstruction du tableau.
  / Deletion no longer rebuilds the whole table.
- Une seule image vidéo préchargée (25 %), les autres à la demande.
  / A single video frame prefetched (25 %), the rest on demand.
- Écriture des tags différée (600 ms) au lieu d'une écriture par clic.
  / Debounced tag writing (600 ms) instead of one write per click.

### 🐛 Corrigé / Fixed
- **Perte des dossiers assignés** : les lignes portaient le dictionnaire du fichier, que
  Qt recopiait — les modifications n'atteignaient jamais les données. Elles portent
  maintenant un identifiant entier. / **Assigned folders were lost**: rows carried the
  file dictionary, which Qt copied, so edits never reached the data. Rows now carry an
  integer id.
- Dates non reconnues hors du format `YYYYMMDD_HHMMSS` : photos et vidéos se retrouvaient
  séparées. / Dates outside `YYYYMMDD_HHMMSS` were unrecognised, splitting photos from
  videos.
- Largeur de colonne impossible à régler (`ResizeToContents` / `Stretch`).
  / Column widths could not be adjusted.
- Retour en haut de liste à chaque assignation de dossier (retri implicite).
  / The list jumped back to the top on every folder assignment.
- Aperçus vidéo absents : ffmpeg appelé par son nom sans être dans le `PATH`.
  / Video previews missing: ffmpeg called by name without being on `PATH`.
- Captures vidéo supprimées à chaque changement de fichier, rendant le cache inutile.
  / Video screenshots deleted on every file change, defeating the cache.
- Grille de vignettes désalignée (`setUniformItemSizes` calé sur une icône vide).
  / Misaligned thumbnail grid.
- Dossiers temporaires laissés dans le dossier photos.
  / Temp folders left behind in the photo folder.

### 🗑️ Retiré / Removed
- Colonne *Destination* (déplacée en infobulle). / *Destination* column (moved to tooltip).
- Dossier `.vscode/`. / `.vscode/` folder.

---

## [v5.0.0] — 2026-01-31

### 🎉 Version initiale / Initial release
- Détection automatique de l'année depuis le nom de fichier.
- Rangement en `ANNÉE/NOM_DOSSIER/`, doublons déplacés vers `!duplicate`.
- Interface Tkinter en trois panneaux, dossiers colorés, cache d'édition persistant.
- Aperçus vidéo par ffmpeg à 11 pourcentages, curseur cliquable.
- Visionneuse d'images avec zoom `Ctrl` + molette, support HEIC/HEIF.
- Opérations par lot, rangement automatique des captures d'écran.
- Détection des doublons avec liste d'ignorés permanente.
