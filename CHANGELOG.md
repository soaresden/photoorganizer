# Changelog

Toutes les évolutions notables de TriPhoto. / All notable changes to TriPhoto.

Format : [Semantic Versioning](https://semver.org/)

---

## [v7.0.0] — 2026-11-04

Nouvelle interface web : un petit serveur Python local + une interface HTML
ouverte dans une fenêtre d'application Edge, lancée par `TriPhoto.bat`.
/ New web UI: a small local Python server + an HTML UI in an Edge app window.

### ✨ Ajouté / Added
- **Package `triphoto/`** : `core.py` (toute la logique, reprise de `TriPhoto.py`
  avec ses six garde-fous), `server.py` (API JSON, événements en direct),
  `web/` (interface). / **`triphoto/` package**: core logic, JSON API, web UI.
- **Lanceur `TriPhoto.bat` → `TriPhoto.ps1`** : trouve Python, installe les
  dépendances, démarre le serveur sans console, ouvre une fenêtre d'appli dédiée.
  Options `-NoImport`, `-Browser`, `-Shortcut`. Fermer la fenêtre arrête le
  serveur. / **Launcher** with options; closing the window stops the server.
- Tableaux virtualisés : défilement, tri et sélection instantanés quelle que soit
  la taille. Colonnes redimensionnables, largeurs et tris mémorisés.
  / Virtualised tables, resizable and remembered columns.
- Lecture des vidéos directement dans l'aperçu (Tri) et dans la visionneuse
  plein écran (Visualiseur). / Inline video playback.
- Visionneuse plein écran avec navigation au clavier, renommage et corbeille.
  / Full-screen lightbox.
- Journal, progression et scores de comparaison poussés en direct.
  / Live log, progress and comparison scores.
- Raccourcis : `Ctrl+1…4`, filtre de dossiers au clavier dans le Tri,
  `Maj+Suppr` pour la Copie 1 des doublons. / New keyboard shortcuts.
- Cache de vignettes persistant (`.cache/thumbs`, purgé au-delà de 2 Go).
  / Persistent thumbnail cache.

### 🛡️ Sécurité des données / Data safety
- **Fichiers vides (0 octet)** : verdict explicite « 1 vide » / « 2 vide ». Si la
  Copie 1 est vide, « Tout traiter » écarte la ligne (il aurait jeté la seule
  vraie image), et `Suppr` demande confirmation.
  / **Empty files** are flagged; the batch never trashes the only real copy.
- Le serveur n'écoute que sur `127.0.0.1`, vérifie l'en-tête `Host` et exige un
  jeton de session pour toute écriture. Les fichiers servis sont limités à
  l'arbre Camera, à pCloud et au cache.
  / Localhost only, Host check, session token, path allow-list.
- Les tags sont fusionnés plutôt qu'écrasés quand plusieurs actions se
  croisent ; la garde `.bak` anti-rétrécissement est conservée.
  / Tags are merged, the anti-shrink `.bak` guard is kept.

### 🔧 Modifié / Changed
- Les caches `!temp` / `!tempvideoscreen` ne sont plus créés dans Camera :
  tout va dans `.cache/` à côté du programme (les anciens sont purgés).
  / Caches moved out of the Camera tree into `.cache/`.
- `PySide6` n'est plus une dépendance ; `TriPhoto.py` (interface Qt) reste
  utilisable mais n'évolue plus. / PySide6 dropped; the Qt app is legacy.

---

## [v6.1.0] — 2026-11-04

Import automatique du dossier de synchronisation pCloud, rangement des captures
par application, et trois périmètres de travail.
/ Automatic pCloud sync import, screenshots grouped by app, three working scopes.

### ✨ Ajouté / Added
- **Import pCloud au démarrage** : `Pictures\` (racine seulement, sous-dossiers
  intouchés) et `DCIM\Screenshots` / `DCIM\ScreenRecorder` (sous-dossiers compris)
  sont vidés dans `Camera\ANNÉE\`. Dossier configurable, activable/désactivable,
  déclenchable à la demande. / **pCloud import on startup**, configurable and
  switchable.
- **Garde anti-doublon à l'import** : tout l'arbre Camera est indexé (nom + taille)
  avant de ranger. Si une capture est déjà classée ailleurs, c'est l'arrivant qui
  part dans `!duplicate` — jamais la copie que vous aviez rangée.
  / **Import duplicate guard**: the incoming file yields, never the filed copy.
- **Captures rangées par application** : le paquet Android est traduit en nom
  lisible (table d'une soixantaine d'applis + déduction), gère les suffixes
  `-edit` de Xiaomi et les étiquettes `lockscreen`. Appliqué à l'import et
  rétroactivement via le bouton « 🗂️ Ranger par appli ».
  / **Screenshots grouped by app**.
- **Trois périmètres** (Camera / Screenshots / ScreenRecorder) en boutons radio
  dans les onglets Doublons et Tri. En mode capture, la liste des destinations
  cumule les dossiers d'événements et les sous-dossiers du vivier.
  / **Three scopes** as radio buttons in the Duplicates and Sorting tabs.
- Passage automatique au média suivant après l'assignation d'un dossier.
  / Auto-advance to the next media after assigning a folder.
- `restore_screenshots.py` : repêche les captures envoyées par erreur dans
  `!duplicate`, en vérifiant d'abord qu'elles n'existent pas ailleurs.
  / Recovery script for screenshots wrongly sent to `!duplicate`.

### 🐛 Corrigé / Fixed
- **`safe_move()` pouvait envoyer un fichier dans `!duplicate` en le comparant à
  lui-même** lorsque la destination était son propre dossier — 4059 captures
  concernées. Le déplacement sur place est désormais refusé, et `apply_moves()`
  saute explicitement les fichiers déjà à destination.
  / **`safe_move()` could mistake a file for its own duplicate**.
- Le scan de doublons ne descendait que d'un niveau : depuis le rangement par
  appli, il ne voyait plus aucune capture. Les viviers sont parcourus en
  profondeur. / The duplicate scan only went one level deep.
- `app_from_filename` ratait `..._com.whatsapp-edit.jpg`, `..._lockscreen.jpg` et
  les copies `..._1.jpg`. / Three filename shapes were not recognised.
- La barre des positions vidéo (11 radios) imposait une largeur minimale qui
  bloquait le séparateur de l'onglet Tri. / The video position bar locked the
  splitter.
- Avertissement `SyntaxWarning: invalid escape sequence` sur une docstring.

### 🔧 Modifié / Changed
- Bouton « ▶️ Lire la vidéo » déplacé en tête de la barre des positions.
- Séparateurs : poignées à 8 px, minimums explicites, panneaux non repliables.

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
