# TriPhoto — Smart Photo & Video Organizer

Application de bureau (Python / Qt) pour ranger, dédoublonner et visualiser des milliers de photos et vidéos.

A desktop app (Python / Qt) to sort, de-duplicate and browse thousands of photos and videos.

![Python](https://img.shields.io/badge/python-3.9+-blue.svg)
![Qt](https://img.shields.io/badge/UI-PySide6-41cd52.svg)
![License](https://img.shields.io/badge/license-MIT-green.svg)
![Platform](https://img.shields.io/badge/platform-Windows-lightgrey.svg)

**[🇫🇷 Français](#-français) · [🇬🇧 English](#-english)**

---

# 🇫🇷 Français

## Ce que fait TriPhoto

Quatre onglets, une seule idée : reprendre le contrôle d'un dossier `DCIM/Camera` qui a débordé.

| Onglet | Rôle |
|---|---|
| **1️⃣ Renommage** | Normalise les noms de dossiers d'événements et corrige ceux rangés dans la mauvaise année |
| **2️⃣ Doublons** | Détecte les doublons, **compare le contenu réel** et n'en supprime aucun sans preuve |
| **3️⃣ Tri des médias** | Assigne chaque photo/vidéo à un dossier d'année, avec aperçu instantané |
| **4️⃣ Visualiseur** | Parcourt l'existant en vignettes, avec une frise chronologique interactive |

## Points forts

### Import pCloud automatique

Au lancement, TriPhoto vide le dossier de synchronisation dans l'arborescence Camera :

- `Pictures\` → les médias posés **à la racine** rejoignent Camera. Les sous-dossiers (WhatsApp, Instagram…) ne sont **pas touchés**.
- `DCIM\Screenshots\` et `DCIM\ScreenRecorder\` → chaque média est classé dans `Camera\ANNÉE\!Screenshots_ANNÉE\` ou `!ScreenRecorder_ANNÉE\`, sous-dossiers compris, puis les dossiers vidés sont supprimés.

L'année est lue dans le nom, sinon dans l'EXIF, sinon dans la date du fichier.

Avant de ranger quoi que ce soit, l'arbre Camera entier est indexé : **si une capture est déjà rangée ailleurs** (par exemple dans un dossier d'événement), c'est l'arrivant qui part dans `!duplicate`, jamais la copie que vous aviez classée. Le journal indique où se trouve celle qui est conservée.

Désactivable par la case « Importer à l'ouverture », ou déclenchable à la demande.

### Captures rangées par application

Les captures Android portent le paquet de l'app en fin de nom. TriPhoto le traduit en nom lisible et crée un sous-dossier par application :

| Nom de fichier | Dossier |
|---|---|
| `Screenshot_…_com.whatsapp.jpg` | `WhatsApp` |
| `Screenshot_…_com.facebook.orca.jpg` | `Messenger` |
| `Screenshot_…_com.android.vending.jpg` | `Play Store` |
| `Screenshot_…_com.whatsapp-edit.jpg` | `WhatsApp` *(retouchée sur le téléphone)* |
| `Screenshot_…_lockscreen.jpg` | `Écran de verrouillage` |

Une table couvre une cinquantaine d'applications courantes ; les autres sont déduites du paquet. Appliqué à l'import, et rétroactivement par le bouton **« 🗂️ Ranger par appli »**.

### Trois périmètres de travail

Les onglets **Doublons** et **Tri** offrent les mêmes boutons radio :

- **📷 Camera** — les dossiers d'événements et les fichiers en vrac
- **🖼️ Screenshots** — le contenu des `!Screenshots_ANNÉE\`, sous-dossiers compris
- **🎬 ScreenRecorder** — idem pour les enregistrements d'écran

En mode Screenshots ou ScreenRecorder, la liste des dossiers de destination cumule les dossiers d'événements de l'année **et** les sous-dossiers du vivier (marqués `↳`) : une capture peut rester entre captures ou rejoindre un vrai dossier d'événement.

### Comparaison de contenu, pas seulement de nom

Deux fichiers qui portent le même nom, ou un suffixe `_1`, ne sont pas forcément identiques. TriPhoto le vérifie sur trois critères :

- ⚖️ **taille** des deux fichiers
- 🖼️ **contenu affiché** — empreinte perceptuelle *dHash*, insensible au réencodage et au redimensionnement, sensible à un changement de scène
- ⏱️ **durée** pour les vidéos

Les vidéos sont comparées **image par image** aux mêmes points de leur timeline : une version tronquée ou une autre prise ressort immédiatement. Le verdict va de 🟢 *doublon confirmé* à 🔴 *contenu différent*, et **une ligne 🟠 ou 🔴 n'est jamais supprimée par le traitement automatique**, même si son nom crie « copie ».

Le calcul tourne en tâche de fond : la colonne Score se remplit pendant que vous travaillez.

### Détection de copies

Reconnaît les marqueurs laissés par Windows, les téléphones et les outils de synchronisation : `_1`, `-1`, `~1`, `(1)`, ` (1)`, `- Copie`, `_copy`, `copy 2`, `kopie`, `copia`. L'original doit exister **dans le même dossier**, et les suffixes numériques sont limités à trois chiffres — `IMG_20190323_104548.jpg` n'est donc pas pris pour une copie.

### Différences surlignées

Les deux chemins d'un doublon sont comparés segment par segment, puis caractère par caractère quand ils se ressemblent. Seul ce qui diffère est surligné :

```
2024\!ScreenShots_2024\Screenshot_2024-04-13-10-12-33-965_mobi.lappli.jpg
2024\!ScreenShots_2024\Screenshot_2024-04-13-10-12-33-965_mobi.lappli[_1].jpg
                                                                     ^^^^
```

### Tri chronologique fiable

La date est extraite du nom quel que soit le format (`IMG_20250108_181456`, `2016-03-09 19.37.29`, `Screenshot_2024-04-13-10-12-33-965`, horodatage epoch…), avec repli sur la date de modification. **Le préfixe est ignoré** : photos et vidéos d'un même moment se suivent au lieu d'être séparées en deux blocs.

### Fluidité

- décodage des images dans des threads dédiés, jamais dans l'interface
- mode *draft* de libjpeg : décodage direct en taille réduite
- préchargement des photos voisines — la suivante est déjà prête
- vignettes du visualiseur chargées par un pool de 4 threads, avec cache mémoire
- une seule image vidéo (25 %) préchargée ; les autres pourcentages à la demande

### Frise chronologique

Un point par média, avec des graduations qui s'adaptent à l'étendue du dossier (heures, jours, mois, années). Un interrupteur **vue année** étale la frise du 01/01 au 31/12 : on voit immédiatement si les photos se concentrent en début ou en fin d'année. Cliquer un point sélectionne la vignette, et inversement.

## Installation

```bash
git clone https://github.com/soaresden/photoorganizer.git
cd photoorganizer
pip install -r requirements.txt
python TriPhoto.py
```

Les dépendances manquantes sont installées automatiquement au premier lancement.

### ffmpeg (aperçus vidéo)

Recherché dans l'ordre : dossier configuré → dossier du script → `PATH` → paquet `imageio-ffmpeg`.

```bash
winget install Gyan.FFmpeg     # ou : pip install imageio-ffmpeg
```

Sans ffmpeg, tout fonctionne sauf les aperçus vidéo. Le chemin est modifiable via la clé `ffmpeg_dir` du fichier de configuration.

## Structure attendue

```
Camera/
├── 2024/
│   ├── 2024-08-15 Vacances/
│   ├── !Screenshots_2024/        (rangé automatiquement)
│   └── !ScreenRecorder_2024/
├── 2025/
├── !duplicate/                   (doublons détectés au déplacement)
├── !temp/                        (temporaire, vidé à la fermeture)
└── !tempvideoscreen/             (temporaire, vidé à la fermeture)
```

## Raccourcis

| Raccourci | Action |
|---|---|
| `Suppr` | Corbeille (onglets Doublons, Tri, Visualiseur) |
| `F2` | Renommer le média sélectionné (Visualiseur) |
| `Ctrl` + molette | Zoom de l'aperçu |
| Double-clic | Ouvrir le fichier (Doublons, Visualiseur) |
| Clic droit | Menu contextuel : renommer, ouvrir, corbeille, ignorer |

## Sécurité des données

- toute suppression passe par la **corbeille Windows**, jamais par un effacement direct ;
- le fichier de tags ne peut pas rétrécir sans laisser une copie `.bak` ;
- avant tout déplacement, les dossiers assignés sont resynchronisés depuis le tableau : **ce que vous voyez fait foi** ;
- les doublons ignorés sont mémorisés **par paire de chemins**, pas par nom de fichier.

## Fichiers de configuration

Écrits à côté du script, ignorés par git :

| Fichier | Contenu |
|---|---|
| `triphoto_config.json` | dossier Camera, chemin ffmpeg, largeur et tri des colonnes |
| `triphoto_edits.json` | dossiers assignés, sauvegarde automatique |
| `triphoto_ignore.json` | doublons ignorés |

---

# 🇬🇧 English

## What TriPhoto does

Four tabs, one goal: regain control of a `DCIM/Camera` folder that got out of hand.

| Tab | Purpose |
|---|---|
| **1️⃣ Renaming** | Normalises event folder names and fixes those filed under the wrong year |
| **2️⃣ Duplicates** | Finds duplicates, **compares actual content**, deletes nothing without proof |
| **3️⃣ Media sorting** | Assigns every photo/video to a year folder, with instant preview |
| **4️⃣ Viewer** | Browses what is already filed as thumbnails, with an interactive timeline |

## Highlights

### Automatic pCloud import

On startup TriPhoto empties the sync folder into the Camera tree:

- `Pictures\` → media sitting **at the root** move to Camera. Sub-folders (WhatsApp, Instagram…) are **left alone**.
- `DCIM\Screenshots\` and `DCIM\ScreenRecorder\` → every media is filed under `Camera\YEAR\!Screenshots_YEAR\` or `!ScreenRecorder_YEAR\`, sub-folders included, then emptied folders are removed.

The year is read from the filename, then EXIF, then the file date.

Before filing anything the whole Camera tree is indexed: **if a screenshot is already filed elsewhere** (in an event folder, say), the incoming one goes to `!duplicate` — never the copy you sorted. The log says where the surviving one lives.

Switch it off with the "import on startup" checkbox, or trigger it on demand.

### Screenshots grouped by app

Android screenshots carry the app package at the end of their name. TriPhoto turns it into a readable name and creates one sub-folder per app:

| Filename | Folder |
|---|---|
| `Screenshot_…_com.whatsapp.jpg` | `WhatsApp` |
| `Screenshot_…_com.facebook.orca.jpg` | `Messenger` |
| `Screenshot_…_com.android.vending.jpg` | `Play Store` |
| `Screenshot_…_com.whatsapp-edit.jpg` | `WhatsApp` *(edited on the phone)* |
| `Screenshot_…_lockscreen.jpg` | `Écran de verrouillage` |

A table covers about fifty common apps; the rest are derived from the package. Applied on import, and retroactively through the **"🗂️ Ranger par appli"** button.

### Three working scopes

The **Duplicates** and **Sorting** tabs share the same radio buttons:

- **📷 Camera** — event folders and loose files
- **🖼️ Screenshots** — the contents of `!Screenshots_YEAR\`, sub-folders included
- **🎬 ScreenRecorder** — same for screen recordings

In Screenshots or ScreenRecorder mode, the destination list combines the year's event folders **and** the bucket's own sub-folders (marked `↳`): a capture can stay among captures or move out to a real event folder.

### Content comparison, not just names

Two files sharing a name — or one carrying a `_1` suffix — are not necessarily the same. TriPhoto checks three things:

- ⚖️ **file size** on both sides
- 🖼️ **displayed content** — a *dHash* perceptual fingerprint, immune to re-encoding and resizing, sensitive to a different scene
- ⏱️ **duration** for videos

Videos are compared **frame by frame** at matching points of their timeline, so a trimmed version or a different take stands out immediately. Verdicts run from 🟢 *confirmed duplicate* to 🔴 *different content*, and **a 🟠 or 🔴 row is never batch-deleted**, however loudly its name says "copy".

Scoring runs in the background: the Score column fills itself while you work.

### Copy detection

Recognises the markers left by Windows, phones and sync tools: `_1`, `-1`, `~1`, `(1)`, ` (1)`, `- Copie`, `_copy`, `copy 2`, `kopie`, `copia`. The original must exist **in the same folder**, and numeric suffixes are capped at three digits — so `IMG_20190323_104548.jpg` is never mistaken for a copy.

### Highlighted differences

Both paths are compared segment by segment, then character by character when segments are similar. Only what actually differs is highlighted:

```
2024\!ScreenShots_2024\Screenshot_2024-04-13-10-12-33-965_mobi.lappli.jpg
2024\!ScreenShots_2024\Screenshot_2024-04-13-10-12-33-965_mobi.lappli[_1].jpg
                                                                     ^^^^
```

### Reliable chronological sorting

Dates are read from the filename whatever the format (`IMG_20250108_181456`, `2016-03-09 19.37.29`, `Screenshot_2024-04-13-10-12-33-965`, epoch timestamps…), falling back to the file's modification time. **The prefix is ignored**, so photos and videos from the same moment sit next to each other instead of forming two separate blocks.

### Responsiveness

- images decoded in dedicated threads, never in the UI loop
- libjpeg *draft* mode: decoding straight to reduced size
- neighbouring photos prefetched — the next one is already decoded
- viewer thumbnails loaded by a 4-thread pool, with an in-memory cache
- a single video frame (25 %) prefetched; other percentages extracted on demand

### Timeline

One dot per media, with graduations that adapt to the folder's span (hours, days, months, years). A **year view** switch stretches the timeline from Jan 1st to Dec 31st, showing at a glance whether shots cluster early or late in the year. Clicking a dot selects the thumbnail, and vice versa.

## Installation

```bash
git clone https://github.com/soaresden/photoorganizer.git
cd photoorganizer
pip install -r requirements.txt
python TriPhoto.py
```

Missing dependencies are installed automatically on first run.

### ffmpeg (video previews)

Searched in order: configured folder → script folder → `PATH` → the `imageio-ffmpeg` package.

```bash
winget install Gyan.FFmpeg     # or: pip install imageio-ffmpeg
```

Without ffmpeg everything works except video previews. The path can be set through the `ffmpeg_dir` key of the config file.

## Expected layout

```
Camera/
├── 2024/
│   ├── 2024-08-15 Holiday/
│   ├── !Screenshots_2024/        (auto-filed)
│   └── !ScreenRecorder_2024/
├── 2025/
├── !duplicate/                   (duplicates found while moving)
├── !temp/                        (temporary, emptied on exit)
└── !tempvideoscreen/             (temporary, emptied on exit)
```

## Shortcuts

| Shortcut | Action |
|---|---|
| `Delete` | Recycle bin (Duplicates, Sorting, Viewer tabs) |
| `F2` | Rename the selected media (Viewer) |
| `Ctrl` + wheel | Zoom the preview |
| Double-click | Open the file (Duplicates, Viewer) |
| Right-click | Context menu: rename, open, recycle, ignore |

## Data safety

- every deletion goes through the **Windows Recycle Bin**, never a direct erase;
- the tag file cannot shrink without leaving a `.bak` copy;
- before any move, assigned folders are re-synced from the table: **what you see wins**;
- ignored duplicates are remembered **per path pair**, not per filename.

## Configuration files

Written next to the script, git-ignored:

| File | Contents |
|---|---|
| `triphoto_config.json` | camera folder, ffmpeg path, column widths and sort order |
| `triphoto_edits.json` | assigned folders, auto-saved |
| `triphoto_ignore.json` | ignored duplicates |

---

## 📄 License / Licence

MIT — see [LICENSE](LICENSE).

## 🙏 Credits

Built with [PySide6](https://doc.qt.io/qtforpython/) · [Pillow](https://python-pillow.org/) · [pillow-heif](https://github.com/bigcat88/pillow_heif) · [send2trash](https://github.com/arsenetar/send2trash) · [FFmpeg](https://ffmpeg.org/)
