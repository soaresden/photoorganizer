# TriPhoto

**Ranger, dédoublonner et parcourir des dizaines de milliers de photos et vidéos — sans jamais en perdre une.**
*Sort, de-duplicate and browse tens of thousands of photos and videos — without ever losing one.*

![Python](https://img.shields.io/badge/python-3.10+-blue.svg)
![UI](https://img.shields.io/badge/UI-HTML%20%2F%20JS-8b7cff.svg)
![Platform](https://img.shields.io/badge/platform-Windows-lightgrey.svg)
![License](https://img.shields.io/badge/license-MIT-green.svg)

**[🇫🇷 Français](#-français) · [🇬🇧 English](#-english)**

---

## 🇫🇷 Français

TriPhoto reprend en main un dossier `DCIM\Camera` qui a débordé : il vide la
synchro du téléphone, range chaque média dans un dossier d'événement, traque les
doublons en comparant le **contenu réel**, et affiche le tout en vignettes avec
une frise chronologique.

Un petit serveur Python local fait le travail sur les fichiers ; l'interface est
une page HTML ouverte dans une fenêtre d'application Edge — fluide même sur
35 000 fichiers.

### Démarrer

```bash
git clone https://github.com/soaresden/photoorganizer.git
```

Puis **double-clic sur `TriPhoto.bat`**. Python 3 doit être installé ; le reste
(Pillow, pillow-heif, send2trash) s'installe tout seul au premier lancement.
Fermer la fenêtre arrête le serveur.

| Commande | Effet |
|---|---|
| `TriPhoto.bat -NoImport` | ne pas vider pCloud au démarrage |
| `TriPhoto.bat -Browser` | ouvrir dans le navigateur par défaut |
| `TriPhoto.bat -Shortcut` | créer un raccourci sur le Bureau |

Pour les aperçus vidéo, installer ffmpeg (`winget install Gyan.FFmpeg`) ou
indiquer son dossier dans les Réglages. Sans lui, tout le reste fonctionne.

### Les quatre onglets

| | Onglet | Rôle |
|---|---|---|
| 1 | **Renommage** | Normalise les noms de dossiers (`2024-08-15 Vacances`), repère ceux rangés dans la mauvaise année ou presque identiques |
| 2 | **Doublons** | Détecte les doublons de nom, de suffixe (`_1`, `(1)`, `- Copie`…) et les compare sur leur contenu |
| 3 | **Tri des médias** | Assigne chaque fichier en vrac à un dossier, avec aperçu, lecture vidéo et filtre au clavier |
| 4 | **Visualiseur** | Années → dossiers → vignettes, frise chronologique, visionneuse plein écran |

Doublons et Tri travaillent sur trois périmètres au choix : **Camera** (dossiers
d'événements), **Screenshots** et **ScreenRecorder** (les viviers
`!Screenshots_ANNÉE`, rangés par application).

### Ce qu'il fait pour vous

- **Import pCloud au démarrage** — `DCIM\Screenshots`, `DCIM\ScreenRecorder` et
  la racine de `Pictures\` sont vidés dans `Camera\ANNÉE\`. Les captures sont
  rangées par appli (`com.whatsapp` → `WhatsApp`). Une capture déjà classée
  ailleurs n'est jamais doublée : c'est l'arrivant qui part dans `!duplicate`.
- **Comparaison de contenu** — taille, empreinte visuelle (dHash, insensible au
  réencodage) et durée pour les vidéos, comparées image par image. Le verdict
  va de 🟢 *identique* à 🔴 *différent* ; un fichier vide (0 octet) est signalé.
  Le calcul tourne en fond, la colonne Score se remplit toute seule.
- **Dates fiables** — lues dans le nom quel que soit le format, puis l'EXIF,
  puis la date du fichier.

### Garde-fous

- Rien n'est effacé : tout passe par la **corbeille Windows** ou `!duplicate`.
- « Tout traiter » ne touche jamais une ligne 🟠 / 🔴, ni une ligne dont la
  Copie 1 est vide (la Copie 2 est alors la seule vraie image).
- Un fichier n'est jamais déplacé sur lui-même ni pris pour son propre doublon.
- Le fichier des dossiers assignés ne peut pas rétrécir sans laisser un `.bak`.
- Ce qui est affiché à l'écran au moment de « Appliquer » est ce qui est déplacé.

### Raccourcis

| Touche | Action |
|---|---|
| `Ctrl` + `1`…`4` | changer d'onglet |
| lettre (Tri) | filtrer les dossiers ; `↑` `↓` `Entrée` pour assigner |
| `Suppr` | corbeille, tout de suite, où que soit le curseur (même dans le filtre des dossiers). Dans Doublons : la **mauvaise** copie — la Copie 2, ou la Copie 1 si c'est elle qui est vide |
| `Maj` + `Suppr` | corbeille de la Copie 1 (Doublons) |
| `F2` | renommer (Visualiseur) · modifier l'année (Tri) |
| flèches, `Entrée` | naviguer, ouvrir en grand (Visualiseur) |
| clic droit | ouvrir, révéler dans l'Explorateur, renommer, ignorer… |

Une confirmation n'est demandée qu'au-delà de 20 fichiers : tout passe par la
corbeille Windows, donc tout se récupère.

### Thèmes

Cinq thèmes dans les Réglages, appliqués au clic : **Nuit** (par défaut),
**Plongée** (grand bleu, bulles), **Zelda** (forêt, parchemin et or),
**Violon** (thème clair, bois verni et portées) et **RetroGamer** (néon
d'arcade, lignes d'écran cathodique).

### Fichiers

| Fichier | Contenu |
|---|---|
| `triphoto_config.json` | dossier Camera, racine pCloud, ffmpeg, colonnes |
| `triphoto_edits.json` | dossiers assignés (sauvegarde auto, `.bak` anti-perte) |
| `triphoto_ignore.json` | paires de doublons ignorées |
| `.cache/` | vignettes (gardées, purgées au-delà de 2 Go) et images vidéo (vidées à la fermeture) |

Tous ignorés par git. `TRIPHOTO_DATA=<dossier>` les place ailleurs, pratique
pour tester sur une copie.

---

## 🇬🇧 English

TriPhoto tames an overflowing `DCIM\Camera` folder: it empties the phone sync
folder, files every media into an event folder, hunts duplicates by comparing
**actual content**, and shows everything as thumbnails on a timeline.

A small local Python server does the file work; the UI is an HTML page shown in
an Edge app window — smooth even over 35,000 files.

### Getting started

Clone the repo and **double-click `TriPhoto.bat`**. Python 3 is required;
everything else installs itself on first run. Closing the window stops the
server. Options: `-NoImport` (leave pCloud alone), `-Browser` (default
browser), `-Shortcut` (desktop shortcut). Video previews need ffmpeg
(`winget install Gyan.FFmpeg`).

### The four tabs

| | Tab | Purpose |
|---|---|---|
| 1 | **Renaming** | Normalises event folder names, flags wrong-year and near-identical folders |
| 2 | **Duplicates** | Finds name, suffix (`_1`, `(1)`, `- Copy`…) duplicates and compares their content |
| 3 | **Sorting** | Assigns loose files to folders, with preview, video playback and keyboard filter |
| 4 | **Viewer** | Years → folders → thumbnails, timeline, full-screen lightbox |

Duplicates and Sorting work on three scopes: **Camera**, **Screenshots** and
**ScreenRecorder** (the `!Screenshots_YEAR` buckets, grouped by app).

### Safety

- Nothing is erased: everything goes to the **Windows Recycle Bin** or `!duplicate`.
- "Process all" never touches a 🟠 / 🔴 row, nor one whose Copy 1 is empty.
- A file is never moved onto itself nor mistaken for its own duplicate.
- An incoming pCloud screenshot already filed elsewhere goes to `!duplicate` — never the filed copy.
- The assignments file cannot shrink without leaving a `.bak`.

### Shortcuts

`Ctrl+1…4` tabs · type a letter in Sorting to filter folders, `↑ ↓ Enter` to
assign · `Delete` recycles right away, wherever the focus is (in Duplicates:
the bad copy — Copy 2, or Copy 1 when it is the empty one) · `Shift+Delete`
recycles Copy 1 · `F2` renames · right-click for more. Five themes in the
settings: Nuit, Plongée, Zelda, Violon, RetroGamer.

---

## Architecture

```
TriPhoto.bat → TriPhoto.ps1          launcher: Python, deps, hidden server, app window
triphoto/
├── core.py                          pure logic: dates, moves, fingerprints, verdicts
├── server.py                        local HTTP server: JSON API + live events (SSE)
└── web/                             index.html · app.css · app.js (vanilla, no build)
TriPhoto.py                          former Qt UI (PySide6), kept but no longer developed
```

The server binds to `127.0.0.1` only, checks the `Host` header, requires a
per-session token for every write and only serves files from the Camera tree,
the pCloud root and its cache.

## License

MIT — see [LICENSE](LICENSE). Built with [Pillow](https://python-pillow.org/) ·
[pillow-heif](https://github.com/bigcat88/pillow_heif) ·
[send2trash](https://github.com/arsenetar/send2trash) · [FFmpeg](https://ffmpeg.org/)
