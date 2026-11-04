# TriPhoto — contexte pour Claude Code

Organiseur de photos/vidéos en **Python + PySide6**, fichier unique `TriPhoto.py`
(~3800 lignes). Windows, mono-utilisateur (Denis). Dépôt :
`https://github.com/soaresden/photoorganizer`.

Session précédente : refonte complète de l'UI Tkinter → Qt, puis une dizaine
d'itérations sur la fluidité, la détection de doublons et l'import pCloud.

## Lancer / tester

```powershell
python TriPhoto.py
```

Les dépendances manquantes sont pip-installées automatiquement au démarrage
(`ensure_packages()`), **donc ne jamais `import TriPhoto` depuis un script** :
ça déclenche l'installation et le chargement de Qt. Voir `restore_screenshots.py`
qui extrait les fonctions dont il a besoin via `ast` sans exécuter le module.

Pas de suite de tests. Vérifier une modif = `python -c "import ast;
ast.parse(open('TriPhoto.py',encoding='utf-8').read())"` puis test manuel, ou
extraction des fonctions pures via `ast` dans un script jetable (méthode utilisée
tout au long de la session précédente).

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
│   │   ├── !temp\ !tempvideoscreen\    <- caches, vidés à la fermeture
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
toucher au tri, aux déplacements ou aux tableaux.**

### 1. Jamais de dict Python dans `setData(Qt.ItemDataRole.UserRole, …)`

PySide convertit un dict en `QVariantMap` : la relecture renvoie une **copie**.
Un bug a vidé 149 assignations de dossiers parce que les lignes portaient le dict
du fichier et que les modifications n'atteignaient jamais `self.files`.
→ les lignes portent un **entier** (`info['uid']`), résolu via `self.files_by_uid`
(voir `finfo()`). Les `str`, `int` et listes de `str` passent sans problème.

### 2. `safe_move()` refuse de déplacer un fichier sur lui-même

Sans ce garde-fou, un fichier déplacé vers son propre dossier se prenait pour son
propre doublon et partait dans `!duplicate` — **4059 captures y ont atterri**.
`apply_moves()` saute aussi explicitement les fichiers déjà à destination.

### 3. Sauvegarde des tags : jamais de rétrécissement silencieux

`save_edits()` écrit `triphoto_edits.json.bak` si le nouveau contenu est plus
petit que l'ancien. C'est ce qui a permis de récupérer les 149 tags perdus.
`sync_folders_from_table()` resynchronise depuis le tableau avant toute écriture
ou déplacement : **ce qui est à l'écran fait foi**.

### 4. Import pCloud : une copie déjà rangée ailleurs n'est jamais doublée

`camera_index()` indexe tout Camera (nom + taille) avant de ranger les captures.
Si une capture existe déjà (par ex. dans `2023-Isabelle\`), **l'arrivant** part
dans `!duplicate`, jamais l'inverse.

### 5. Tri du tableau et largeur de colonnes

- `setSortingEnabled(True)` fait **retrier à chaque modification de cellule** et
  renvoie la vue en haut → le désactiver pendant les mises à jour en masse et
  restaurer `verticalScrollBar().value()` (voir `assign_folder_to_rows`).
- Le tri doit être désactivé pendant le remplissage d'un tableau.
- `ResizeToContents` / `Stretch` empêchent l'utilisateur de régler la largeur →
  tout est en `Interactive` via `setup_header()`.
- Colonne Score : `SortableItem` trie sur la valeur numérique, pas sur l'emoji.

### 6. Rien de bloquant dans le thread graphique

- images décodées dans `PreviewLoader` (QThread, pile LIFO) avec `draft` libjpeg
- vignettes du visualiseur : `ThumbPool`, 4 QThread, file FIFO annulable
- comparaison des doublons : `CompareWorker`
- `stop_*()` ne fait `wait()` **qu'à la fermeture** — un `wait(3000)` dans le flux
  normal gelait l'UI
- un `QPixmap` ne se crée que dans le thread GUI ; les workers produisent des
  `QImage`

## Points d'entrée utiles

| Sujet | Fonction |
|---|---|
| Import pCloud | `import_pcloud`, `move_media_files`, `camera_index` |
| Nom d'appli depuis une capture | `app_from_filename`, `APP_NAMES` |
| Date depuis un nom de fichier | `datetime_from_name`, `file_datetime` |
| Détection de copies `_1`, `(1)`… | `copy_original_name` |
| Comparaison de contenu | `fingerprint`, `compare_fingerprints`, `verdict_for` |
| Surlignage des différences | `diff_path_html`, `_char_diff` |
| Frise chronologique | `Timeline`, `timeline_ticks` |

Config dans `triphoto_config.json` : `camera_path`, `pcloud_root`,
`pcloud_autoimport`, `ffmpeg_dir`, `columns`, `sorts`.

## À faire

- [ ] **La capture du README montre encore l'ancienne interface Tkinter.**
      À remplacer par une vue de la nouvelle (le visualiseur avec sa frise fait
      une bonne vitrine). Seul point qui demande une intervention manuelle.
- [ ] `app_from_filename` : enrichir `APP_NAMES` au fil des paquets rencontrés.
      La déduction automatique marche, mais donne « Companion » pour Home
      Assistant ou « Lappli » pour Société Générale tant que le paquet n'est pas
      dans la table.
- [ ] Pas de suite de tests. Les fonctions pures (`app_from_filename`,
      `datetime_from_name`, `copy_original_name`, `timeline_ticks`,
      `diff_path_html`, `compare_fingerprints`) s'extraient facilement via `ast`
      et se prêtent bien à des tests unitaires si le besoin se présente.

### Fait récemment

- `!duplicate` a été vidé, les 4059 captures sont repêchées et rangées par appli.
- README et CHANGELOG documentent l'import pCloud, le rangement par appli et les
  trois périmètres (entrée v6.1.0).

## Style

Réponses en français. Commentaires de code en anglais, et seulement là où ils
expliquent un **pourquoi** non évident (typiquement : les invariants ci-dessus).
