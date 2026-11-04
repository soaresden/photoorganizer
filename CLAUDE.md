# TriPhoto — contexte pour Claude Code

Organiseur de photos/vidéos. Windows, mono-utilisateur (Denis). Dépôt :
`https://github.com/soaresden/photoorganizer`.

**Depuis la v7 : serveur Python local + interface HTML** (package `triphoto/`).
`TriPhoto.py` (Qt, ~3800 lignes) est l'ancienne version : gardée, plus
développée, mais c'est d'elle que vient toute la logique portée dans `core.py`.

```
TriPhoto.bat → TriPhoto.ps1   trouve Python, installe les deps, lance pythonw
                              -m triphoto caché, attend .cache/server.json,
                              ouvre Edge --app (profil %LOCALAPPDATA%\TriPhoto\AppWindow)
triphoto/core.py              logique pure, aucun effet de bord à l'import
triphoto/server.py            App (état + verrous) + handler HTTP, API JSON, SSE
triphoto/web/                 index.html · app.css · app.js (vanilla, sans build)
```

## Lancer / tester

```powershell
.\TriPhoto.bat -NoImport                    # comme l'utilisateur
python -m triphoto --port 8799 --no-import  # serveur seul, pour tester
```

**Toujours `--no-import` / `-NoImport` en test** : sinon le démarrage vide le
vrai dossier pCloud dans Camera. Rester en lecture seule sur les vraies données
(pas de corbeille, pas de déplacement) ; pour tester les écritures, pointer
`TRIPHOTO_DATA` vers un dossier jetable et `camera_path` vers une copie.

- Les POST exigent l'en-tête `X-Token` : il est dans `<meta name="tp-token">`
  de la page d'accueil.
- Le serveur s'arrête seul 20 s après la fermeture du dernier client SSE.
- Le journal est `triphoto.log` ; `.cache/server.json` donne port et pid.
- **Python du Microsoft Store** : il virtualise `%LOCALAPPDATA%`. C'est pour ça
  que le cache est dans `ROOT/.cache` et pas sous AppData (ffmpeg n'y voyait
  pas les fichiers, PowerShell ne voyait pas `server.json`).

Pas de suite de tests. Vérifier une modif = `ast.parse` des `.py`,
`node --check triphoto/web/app.js`, puis test dans le navigateur. Les fonctions
de `core.py` s'importent sans danger (`from triphoto import core`).

**Ne jamais `import TriPhoto`** (l'ancien) depuis un script : ça pip-installe et
charge Qt. `restore_screenshots.py` en extrait des fonctions via `ast`.

## Arborescence gérée

```
P:\AutoUpload\Xiaomi 2407FPN8EG\        <- racine pCloud (config: pcloud_root)
├── DCIM\
│   ├── Camera\                         <- base_path, le cœur
│   │   ├── 2023\
│   │   │   ├── 2023-Isabelle\          <- dossier d'événement
│   │   │   ├── !Screenshots_2023\WhatsApp\
│   │   │   └── !ScreenRecorder_2023\
│   │   ├── !duplicate\                 <- doublons, jamais supprimés
│   │   ├── (!temp\ !tempvideoscreen\)  <- caches de l'ancienne version, purgés au démarrage
│   ├── Screenshots\  ScreenRecorder\   <- vidés dans Camera à l'ouverture
└── Pictures\                           <- racine vidée, sous-dossiers INTOUCHÉS
```

## Les 4 onglets

1. **Renommage** — normalise les noms de dossiers d'événements
2. **Doublons** — détection + comparaison de contenu, radios de périmètre
   (Camera / Screenshots / ScreenRecorder)
3. **Tri des médias** — assignation fichier → dossier, radios de source
   (mêmes trois)
4. **Visualiseur** — années → dossiers → vignettes + frise chronologique

## Invariants à ne pas casser

Chacun vient d'un bug réel qui a fait perdre des données. **Les relire avant de
toucher au tri, aux déplacements, aux doublons ou aux tableaux.** Les noms entre
parenthèses renvoient à l'ancien `TriPhoto.py`.

### 1. Le serveur détient les données, le client n'envoie que des identifiants

(Qt : un dict dans `setData(UserRole)` revenait en **copie** → 149 assignations
perdues.) Dans la version web, `App.files` est la seule vérité ; le client
envoie des `uid` / `id`, jamais d'objet fichier à réécrire. Garder ce principe :
une route qui accepterait un objet complet du client recréerait le bug.

### 2. `core.safe_move()` refuse de déplacer un fichier sur lui-même

Sans ce garde-fou, un fichier déplacé vers son propre dossier se prenait pour son
propre doublon et partait dans `!duplicate` — **4059 captures y ont atterri**.
`api_sort_apply()` saute aussi explicitement les fichiers déjà à destination.

### 3. Sauvegarde des tags : jamais de rétrécissement silencieux

`App.save_edits()` écrit `triphoto_edits.json.bak` si le nouveau contenu est plus
petit que l'ancien (c'est ce qui a permis de récupérer les 149 tags). Il
**fusionne** avec les tags des autres sources et n'oublie que les noms déplacés
ou supprimés (`self.forgotten`). `api_sort_apply()` reçoit la vue du client et
la resynchronise (`sync_from_view`) avant de déplacer : **ce qui est à l'écran
fait foi**.

### 4. Import pCloud : une copie déjà rangée ailleurs n'est jamais doublée

`App.camera_index()` indexe tout Camera (nom + taille) avant de ranger les
captures. Si une capture existe déjà (par ex. dans `2023-Isabelle\`),
**l'arrivant** part dans `!duplicate`, jamais l'inverse.

### 5. Doublons : le lot ne jette jamais la seule vraie copie

- « Tout traiter » (`auto_rows`) écarte les lignes 🟠/🔴 (`related`/`diff`).
- Il écarte aussi les lignes dont la **Copie 1 fait 0 octet** (`kept_copy_empty`,
  lu sur le disque, pas dans le score) : la bibliothèque en contient réellement
  (des captures `2025-DATE`, `2025-SELF`… vides alors que la copie de
  `!Screenshots_2025` est bonne). Sans ça, le lot jetait les bonnes.
- `Suppr` envoie `side: 'auto'` : `trash_dup_side(side=None)` jette la Copie 2,
  ou la Copie 1 quand `kept_copy_empty` (même lecture disque). Un clic explicite
  sur « Corbeille » de la Copie 2 d'une ligne « 1 vide » demande confirmation.
- `Suppr` est global à l'onglet (pas seulement le tableau) et ne confirme
  qu'au-delà de `CONFIRM_ABOVE` (20) fichiers : tout passe par la corbeille.

### Thèmes

Chaque thème ne fait que redéfinir des variables CSS sous `[data-theme="…"]`
(fin de `app.css`) ; la liste et les pastilles sont dans `THEMES` (`app.js`).
**Aucune couleur en dur** dans les composants : passer par les variables ou
`color-mix(in srgb, var(--x) N%, transparent)`, sinon le thème clair (Violon)
casse. La frise lit ses couleurs avec `getComputedStyle`. Le serveur écrit le
thème dans `<html data-theme>` (`__THEME__`) pour éviter un flash au démarrage.

### 6. Tableaux : pas de retri sous les doigts, colonnes réglables

(Qt : `setSortingEnabled` retriait à chaque édition et renvoyait en haut.)
`VTable` ne retrie **que** sur clic d'en-tête ; une édition ou une suppression
garde l'ordre et le défilement (`removeKeys` passe la sélection à la ligne
suivante). Toutes les colonnes restent redimensionnables, largeurs et tris
sauvés dans la config (`ui`). `.vt-scroll` a `overflow-anchor: none` : sans ça,
Chrome décalait la vue de 70 px à l'ouverture.

### 7. Rien de bloquant, et deux verrous dans un ordre fixe

- Chaque requête HTTP a son thread. Toute mutation de fichiers prend `App.fs`,
  les tables en mémoire `App.state_lock` — **toujours `fs` puis `state_lock`**,
  sinon interblocage.
- La comparaison des doublons tourne en fond avec un compteur de génération
  (`compare_gen`) : un nouveau scan annule l'ancien sans `join`.
- Scores, progression et journal arrivent au client par SSE (`/api/events`).

## Points d'entrée utiles

| Sujet | Où |
|---|---|
| Import pCloud | `App.import_pcloud`, `move_media_files`, `camera_index` |
| Nom d'appli depuis une capture | `core.app_from_filename`, `APP_NAMES` |
| Date depuis un nom de fichier | `core.datetime_from_name`, `file_datetime` |
| Détection de copies `_1`, `(1)`… | `core.copy_original_name` |
| Comparaison de contenu | `core.fingerprint`, `compare_fingerprints`, `verdict_for` |
| Surlignage des différences | `core.diff_path_html` (classes `d-same` / `d-hot` / `d-sep`) |
| Vignettes, aperçus, images vidéo | `core.thumbnail_file`, `preview_bytes`, `grab_one_shot` |
| Frise chronologique | `Timeline`, `timelineTicks` dans `app.js` |
| Tableau virtualisé | `VTable` dans `app.js` |

Config dans `triphoto_config.json` : `camera_path`, `pcloud_root`,
`pcloud_autoimport`, `ffmpeg_dir`, `ui` (colonnes, tris, splitters).

## À faire

- [ ] Fichiers vides (0 octet) dans la bibliothèque : 8 paires dans Doublons où
      la Copie 1 (dossier d'événement) est vide et la Copie 2 bonne. À régler à
      la main (`Maj+Suppr`), ou ajouter une action « réparer » qui remplace la
      copie vide par la bonne.
- [ ] `app_from_filename` : enrichir `APP_NAMES` au fil des paquets rencontrés
      (« Companion » pour Home Assistant, « Lappli » pour Société Générale…).
- [ ] Pas de suite de tests. `core.py` s'importe sans effet de bord : les
      fonctions pures se prêtent directement à des tests unitaires.

### Fait récemment

- Captures du README (`docs/screenshots/`) : faites sur une **photothèque
  fictive** générée (Pillow), jamais sur la vraie — le dépôt est public. Pour
  les refaire : serveur lancé avec `TRIPHOTO_DATA` pointant vers une config dont
  `camera_path` est la démo, et **vérifier `/api/state` avant de capturer** (un
  `camera_path` absent retombe sur `DEFAULT_CAMERA_PATH`, la vraie photothèque).

- v7.0.0 : passage à l'interface web (`triphoto/`), lanceur `.bat`/`.ps1`,
  README réécrit.
- `!duplicate` a été vidé, les 4059 captures sont repêchées et rangées par appli.

## Style

Réponses en français. Commentaires de code en anglais, et seulement là où ils
expliquent un **pourquoi** non évident (typiquement : les invariants ci-dessus).
