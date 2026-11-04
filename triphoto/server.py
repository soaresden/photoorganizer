"""
TriPhoto local server: a JSON API over core.py plus the web UI, bound to 127.0.0.1.

Threading model: every HTTP request runs in its own thread (ThreadingHTTPServer),
so a long action never freezes the interface. Anything that moves, renames or
deletes files takes `self.fs` first: two such actions never run at once.
Progress, logs and comparison scores are pushed to the page over SSE.
"""

import os
import re
import sys
import json
import time
import queue
import secrets
import threading
from collections import deque
import subprocess
import mimetypes
from datetime import datetime
from urllib.parse import urlparse, parse_qs
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler

from . import core
from .core import log

WEB_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'web')
PORT_FILE = os.path.join(core.CACHE_DIR, 'server.json')
KIND_LABELS = {'auto': 'Auto', 'suffix': 'Suffixe', 'conflict': 'Conflit',
               'copy': 'Copie ?', 'renamed': 'Renommé'}


class HttpError(Exception):
    def __init__(self, code, msg):
        super().__init__(msg)
        self.code = code
        self.msg = msg


class App:
    def __init__(self, no_import=False):
        self.fs = threading.RLock()          # serialises every file mutation
        self.state_lock = threading.RLock()  # in-memory tables
        self.no_import = no_import
        self.token = secrets.token_urlsafe(24)

        self.config = core.load_json(core.CONFIG_FILE, {"camera_path": core.DEFAULT_CAMERA_PATH})
        changed = False
        for key, default in (('ffmpeg_dir', core.DEFAULT_FFMPEG_DIR), ('pcloud_root', ''),
                             ('pcloud_autoimport', True)):
            if key not in self.config:
                self.config[key] = default
                changed = True
        if changed:
            core.save_json(core.CONFIG_FILE, self.config)
        core.resolve_ffmpeg(self.config.get('ffmpeg_dir'))

        self.ignore_list = set(core.load_json(core.IGNORE_FILE, []))
        self.imported_once = False

        # Sort tab
        self.files = []
        self.files_by_uid = {}
        self.next_uid = 1
        self.sort_prefix = ''
        self.forgotten = set()            # names moved / trashed: their tag must go
        self.save_timer = None
        self.prefetch_gen = 0

        # Duplicates tab
        self.dup_rows = {}                # id -> row (insertion order = scan order)
        self.next_dup_id = 1
        self.dup_prefix = ''
        self.compare_results = {}         # id -> result
        self.compare_gen = 0
        self.compare_progress = (0, 0)

        # SSE
        self.subscribers = []
        self.sub_lock = threading.Lock()
        self.had_client = False
        self.last_client_seen = time.time()
        self.httpd = None

        self.backlog = deque(maxlen=400)      # replayed to a page that (re)connects

        def on_log(line):
            self.backlog.append(line)
            self.emit({'t': 'log', 'line': line})
        core.add_log_listener(on_log)

    # ------------------------------------------------------------------ basics

    @property
    def base(self):
        return os.path.normpath(self.config.get('camera_path') or core.DEFAULT_CAMERA_PATH)

    @property
    def dup_dir(self):
        return os.path.join(self.base, '!duplicate')

    def pcloud_root(self):
        configured = (self.config.get('pcloud_root') or '').strip()
        if configured:
            return os.path.normpath(configured)
        # ...\<root>\DCIM\Camera  ->  ...\<root>
        return os.path.normpath(os.path.join(self.base, '..', '..'))

    def rel(self, path):
        try:
            return os.path.relpath(path, self.base)
        except ValueError:
            return path

    def emit(self, event):
        data = json.dumps(event, ensure_ascii=False)
        with self.sub_lock:
            subs = list(self.subscribers)
        for q in subs:
            try:
                q.put_nowait(data)
            except queue.Full:
                pass

    def progress(self, label, done, total):
        self.emit({'t': 'progress', 'label': label, 'done': done, 'total': total})

    def allowed(self, path):
        """Files the server agrees to read: the Camera tree, the pCloud root, our cache"""
        return bool(path) and (core.is_under(path, self.base) or core.is_under(path, self.pcloud_root())
                               or core.is_under(path, core.CACHE_DIR))

    def require_base(self):
        if not os.path.isdir(self.base):
            raise HttpError(400, f"Dossier Camera introuvable : {self.base}")

    def years(self):
        try:
            return sorted(e.name for e in os.scandir(self.base)
                          if e.is_dir() and re.match(r'^\d{4}$', e.name))
        except OSError:
            return []

    # ------------------------------------------------------------------ state

    def api_state(self, _q):
        return {
            'camera_path': self.base,
            'camera_ok': os.path.isdir(self.base),
            'pcloud_root': self.pcloud_root(),
            'pcloud_root_raw': self.config.get('pcloud_root') or '',
            'pcloud_autoimport': bool(self.config.get('pcloud_autoimport', True)),
            'ffmpeg': core.FFMPEG, 'ffprobe': core.FFPROBE,
            'pil': core.PIL_AVAILABLE, 'heif': core.HEIF_AVAILABLE,
            'ignored': len(self.ignore_list),
            'ui': self.config.get('ui') or {},
            'scopes': [label for label, _ in core.SCOPES],
            'video_percents': core.VIDEO_PERCENTS,
            'no_import': self.no_import,
        }

    def api_config(self, body):
        if 'camera_path' in body and body['camera_path']:
            path = os.path.normpath(body['camera_path'].strip())
            self.config['camera_path'] = path
            log(f"📁 Dossier Camera : {path}")
        if 'pcloud_root' in body:
            p = (body['pcloud_root'] or '').strip()
            self.config['pcloud_root'] = os.path.normpath(p) if p else ''
            log(f"[PCLOUD] Racine : {self.pcloud_root()}")
        if 'pcloud_autoimport' in body:
            self.config['pcloud_autoimport'] = bool(body['pcloud_autoimport'])
        if 'ui' in body and isinstance(body['ui'], dict):
            ui = self.config.get('ui') or {}
            ui.update(body['ui'])
            self.config['ui'] = ui
        core.save_json(core.CONFIG_FILE, self.config)
        return self.api_state(None)

    def api_browse(self, body):
        """Native folder picker (modern Windows dialog through tkinter, own process)"""
        initial = body.get('initial') or self.base
        script = ("import tkinter as tk, tkinter.filedialog as fd, sys\n"
                  "r=tk.Tk(); r.withdraw(); r.attributes('-topmost', True)\n"
                  "p=fd.askdirectory(initialdir=sys.argv[1], title=sys.argv[2], parent=r)\n"
                  "sys.stdout.write(p or '')\n")
        exe = sys.executable
        if exe.lower().endswith('pythonw.exe'):
            exe = exe[:-5] + '.exe' if os.path.exists(exe[:-5] + '.exe') else exe
        r = subprocess.run([exe, '-c', script, initial, body.get('title') or 'Choisir un dossier'],
                           capture_output=True, text=True, encoding='utf-8',
                           creationflags=core.NO_WINDOW)
        path = (r.stdout or '').strip()
        return {'path': os.path.normpath(path) if path else ''}

    def api_open(self, body):
        path = body.get('path') or ''
        if not self.allowed(path) or not os.path.exists(path):
            raise HttpError(404, "Introuvable")
        if body.get('reveal') and os.path.isfile(path):
            subprocess.Popen(['explorer', '/select,', os.path.normpath(path)])
        else:
            os.startfile(os.path.normpath(path))
        return {'ok': True}

    # ------------------------------------------------------------------ startup / pCloud

    def api_startup(self, _body):
        """Called once by the page: auto-import, then the page loads its tabs"""
        self.require_base()
        imported = 0
        if (self.config.get('pcloud_autoimport', True) and not self.imported_once
                and not self.no_import):
            try:
                imported = self.import_pcloud()
            except Exception as e:
                log(f"[PCLOUD] ❌ Import : {e}")
        self.imported_once = True
        return {'imported': imported}

    def api_import(self, _body):
        self.require_base()
        return {'imported': self.import_pcloud()}

    def import_pcloud(self):
        r"""Empty the pCloud sync folder into the Camera tree.
        1. Pictures\ : loose media at the root go to Camera\ (sub-folders untouched)
        2. DCIM\Screenshots, DCIM\ScreenRecorder : filed under
           Camera\YEAR\!Screenshots_YEAR\<App> (or !ScreenRecorder_YEAR)
        3. Emptied sub-folders are removed
        Duplicates (same name, same size) go to !duplicate, never overwritten."""
        with self.fs:
            root, base = self.pcloud_root(), self.base
            self._camera_index = None
            log("=" * 50)
            log(f"[PCLOUD] Racine : {root}")
            if not os.path.isdir(root):
                log("[PCLOUD] ❌ Racine introuvable, import annulé")
                return 0
            moved = skipped = errors = 0
            self.progress("Import pCloud", 0, 0)
            pictures = os.path.join(root, 'Pictures')
            if os.path.isdir(pictures):
                m, s_, e = self.move_media_files(pictures, lambda *_: base, "Pictures")
                moved, skipped, errors = moved + m, skipped + s_, errors + e
            else:
                log(f"[PCLOUD] Pictures : absent ({pictures})")
            dcim = os.path.join(root, 'DCIM')
            if os.path.isdir(dcim):
                for entry in sorted(os.listdir(dcim)):
                    kind = core.DCIM_SPECIAL_FOLDERS.get(entry)
                    if not kind:
                        continue
                    folder = os.path.join(dcim, entry)
                    if not os.path.isdir(folder) or core.same_path(folder, base):
                        continue
                    m, s_, e = self.move_media_files(
                        folder, lambda year, k=kind: os.path.join(base, year, f"!{k}_{year}"),
                        entry, recursive=True, by_app=True, guard_tree=True)
                    moved, skipped, errors = moved + m, skipped + s_, errors + e
                    core.remove_empty_dirs(folder, keep_root=True)
            else:
                log(f"[PCLOUD] DCIM : absent ({dcim})")
            log(f"[PCLOUD] ✅ {moved} fichier(s) rangé(s)"
                + (f", {skipped} ignoré(s)" if skipped else "")
                + (f", {errors} erreur(s)" if errors else ""))
            self.progress("", 0, -1)
            return moved

    def camera_index(self):
        """{lowercase name: [(path, size)]} for all of Camera except technical folders.
        Built once per import: a capture already filed elsewhere (e.g. in an event
        folder) is never shadowed by a second copy."""
        if getattr(self, '_camera_index', None) is not None:
            return self._camera_index
        index = {}

        def walk(folder):
            try:
                with os.scandir(folder) as it:
                    for e in it:
                        if e.is_dir(follow_symlinks=False):
                            if e.name not in core.TECH_DIRS:
                                walk(e.path)
                        else:
                            try:
                                index.setdefault(e.name.lower(), []).append((e.path, e.stat().st_size))
                            except OSError:
                                pass
            except OSError:
                pass
        walk(self.base)
        self._camera_index = index
        log(f"[PCLOUD] Index Camera : {len(index)} nom(s) de fichier connus")
        return index

    def existing_copy(self, filename, size):
        for path, existing_size in self.camera_index().get(filename.lower(), []):
            if existing_size == size:
                return path
        return None

    def move_media_files(self, source, target_for_year, label, recursive=False,
                         by_app=False, guard_tree=False):
        moved = skipped = errors = 0
        try:
            entries = sorted(os.listdir(source))
        except Exception as e:
            log(f"[PCLOUD] ❌ Lecture impossible {source} : {e}")
            return 0, 0, 1
        for name in entries:
            path = os.path.join(source, name)
            if os.path.isdir(path):
                if recursive and not name.startswith('!'):
                    m, s_, e = self.move_media_files(path, target_for_year, f"{label}\\{name}",
                                                     recursive=True, by_app=by_app,
                                                     guard_tree=guard_tree)
                    moved, skipped, errors = moved + m, skipped + s_, errors + e
                continue
            ext = os.path.splitext(name)[1].lower()
            if ext not in core.MEDIA_EXTS:
                log(f"[PCLOUD]    ~ ignoré (extension) : {label}\\{name}")
                skipped += 1
                continue
            year = core.get_year_from_file(name, path)
            if not year:
                log(f"[PCLOUD]    ⚠️ année inconnue, laissé sur place : {label}\\{name}")
                skipped += 1
                continue
            if guard_tree:
                try:
                    size = os.path.getsize(path)
                except OSError:
                    size = -1
                known = self.existing_copy(name, size)
                if known:
                    # The ARRIVING copy goes to !duplicate, never the filed one
                    try:
                        core.safe_move(path, self.dup_dir)
                        log(f"[PCLOUD]    ♻️ déjà rangé en {self.rel(known)} -> !duplicate : {label}\\{name}")
                        moved += 1
                    except Exception as e:
                        log(f"[PCLOUD]    ❌ {label}\\{name} : {e}")
                        errors += 1
                    continue
            target = target_for_year(year)
            if by_app:
                app = core.app_from_filename(name)
                if app:
                    target = os.path.join(target, app)
            try:
                dest = core.safe_move(path, target, dup_dir=self.dup_dir)
                if guard_tree:
                    try:
                        self.camera_index().setdefault(os.path.basename(dest).lower(), []).append(
                            (dest, os.path.getsize(dest)))
                    except OSError:
                        pass
                if core.same_path(os.path.dirname(dest), self.dup_dir):
                    log(f"[PCLOUD]    ♻️ doublon -> !duplicate : {label}\\{name}")
                else:
                    log(f"[PCLOUD]    → {label}\\{name}  ->  {self.rel(dest)}")
                moved += 1
                if moved % 25 == 0:
                    self.progress("Import pCloud", moved, 0)
            except Exception as e:
                log(f"[PCLOUD]    ❌ {label}\\{name} : {e}")
                errors += 1
        return moved, skipped, errors

    # ------------------------------------------------------------------ tab 1: rename

    def api_rename(self, _q):
        self.require_base()
        exclusions = core.load_folder_exclusions()      # hand-editable: reloaded each time
        rows = []
        for year in self.years():
            year_path = os.path.join(self.base, year)
            entries = []
            try:
                folders = sorted(e.name for e in os.scandir(year_path)
                                 if e.is_dir() and not e.name.startswith('!'))
            except OSError:
                continue
            for folder in folders:
                proposed, status = core.propose_folder_name(year, folder)
                entries.append({'year': year, 'current': folder,
                                'files': core.count_files(os.path.join(year_path, folder)),
                                'proposed': proposed, 'status': status, 'partner': ''})
            # Near-identical names within one year = probable duplicate events
            ok = [e for e in entries if e['status'] == 'ok']
            for i in range(len(ok)):
                for j in range(i + 1, len(ok)):
                    a, b = ok[i], ok[j]
                    if a['status'] != 'ok' or b['status'] != 'ok':
                        continue
                    if tuple(sorted((a['current'], b['current']))) in exclusions:
                        continue
                    ma, mb = core.month_of(a['current'], year), core.month_of(b['current'], year)
                    if ma and mb and ma != mb:
                        continue        # same name but different month = different events
                    if core.name_similarity(a['current'], b['current']) >= 0.8:
                        small, big = (a, b) if a['files'] <= b['files'] else (b, a)
                        small['proposed'] = big['current']    # merge into the bigger one
                        small['partner'] = big['current']
                        small['status'] = 'similar'
            rows.extend(entries)
        counts = {}
        for r in rows:
            counts[r['status']] = counts.get(r['status'], 0) + 1
        log(f"Analyse des noms : {len(rows)} dossier(s) — "
            + ", ".join(f"{v} {k}" for k, v in sorted(counts.items())))
        return {'rows': rows}

    def api_rename_apply(self, body):
        self.require_base()
        base = self.base
        results = []
        with self.fs:
            for r in body.get('rows', []):
                year, current = r.get('year', ''), r.get('current', '')
                proposed = (r.get('proposed') or '').strip()
                res = {'year': year, 'current': current, 'result': 'skip'}
                results.append(res)
                if not proposed or proposed == current or not re.match(r'^\d{4}$', year):
                    continue
                if re.search(r'[\\/:*?"<>|]', proposed):
                    res.update(result='error', msg="caractère interdit")
                    continue
                old_path = os.path.join(base, year, current)
                ym = re.match(r'^(20\d{2})', proposed)
                dest_year = ym.group(1) if ym else year
                new_path = os.path.join(base, dest_year, proposed)
                if not os.path.isdir(old_path) or old_path == new_path:
                    continue
                try:
                    if core.same_path(old_path, new_path):
                        os.rename(old_path, new_path)        # case only: direct, NO merge
                        res.update(result='renamed', new=proposed, year=dest_year)
                        log(f"✏️ Renommé (casse) : {year}/{current} -> {proposed}")
                    elif os.path.exists(new_path):
                        m, du, e = core.merge_folders(old_path, new_path, self.dup_dir)
                        log(f"🔀 Fusionné : {year}/{current} -> {proposed} "
                            f"({m} déplacé(s), {du} doublon(s) -> !duplicate, {e} erreur(s))")
                        res.update(result='merged' if not os.path.exists(old_path) else 'partial',
                                   new=proposed, year=dest_year)
                    else:
                        os.makedirs(os.path.dirname(new_path), exist_ok=True)
                        os.rename(old_path, new_path)
                        log(f"✏️ Renommé : {year}/{current} -> {dest_year}/{proposed}")
                        res.update(result='renamed', new=proposed, year=dest_year)
                except Exception as e:
                    log(f"❌ Renommage {year}/{current} : {e}")
                    res.update(result='error', msg=str(e))
        return {'results': results}

    def api_rename_exclude(self, body):
        count = 0
        for a, b in body.get('pairs', []):
            if a and b:
                a, b = sorted((a, b))
                core.save_folder_exclusion(a, b)
                log(f"🙈 Faux positif exclu : {a} <> {b}")
                count += 1
        return {'count': count}

    # ------------------------------------------------------------------ tab 2: duplicates

    def dup_scan_folders(self, prefix):
        """(folder, is_bucket) pairs to index.
        Camera: event folders + the !Screenshots_ / !ScreenRecorder_ buckets, so a
        capture filed into an event folder shows up against the bucket copy.
        Screenshots / ScreenRecorder: only that bucket tree, every dupe a conflict."""
        base = self.base
        for year in self.years():
            year_dir = os.path.join(base, year)
            if prefix:
                bucket = os.path.join(year_dir, f"{prefix}{year}")
                if os.path.isdir(bucket):
                    for current, _dirs, _files in os.walk(bucket):
                        yield current, False
                continue
            for e in sorted(os.scandir(year_dir), key=lambda e: e.name):
                if not e.is_dir():
                    continue
                if e.name.startswith('!Screenshot') or e.name.startswith('!ScreenRecorder'):
                    for current, _dirs, _files in os.walk(e.path):
                        yield current, True
                elif not e.name.startswith('!'):
                    yield e.path, False

    def pair_key(self, paths1, paths2):
        a = self.rel(paths1[0]) if paths1 else ''
        b = self.rel(paths2[0]) if paths2 else ''
        return f"{a} || {b}"

    def is_ignored(self, filename, paths1, paths2):
        return filename in self.ignore_list or self.pair_key(paths1, paths2) in self.ignore_list

    def dup_row_out(self, row):
        out = {'id': row['id'], 'name': row['name'], 'kind': row['kind'],
               'kind_label': KIND_LABELS.get(row['kind'], row['kind']),
               'p1': row['p1'], 'p2': row['p2'],
               'r1': '; '.join(self.rel(p) for p in row['p1']),
               'r2': '; '.join(self.rel(p) for p in row['p2'])}
        res = self.compare_results.get(row['id'])
        if res is not None:
            out['score'] = self.score_out(res)
        return out

    def score_out(self, res):
        level, short, long_label = core.verdict_for(res)
        return {'level': level, 'short': short, 'long': long_label,
                'details': core.verdict_details(res),
                'value': res.get('content') if res.get('content') is not None else -1}

    def api_dup_scan(self, body):
        self.require_base()
        scope = int(body.get('scope', 0))
        prefix = core.SCOPES[scope][1] if 0 <= scope < len(core.SCOPES) else ''
        self.compare_gen += 1                         # cancels the running comparison
        self.progress("Scan des doublons", 0, 0)
        file_index, bucket_folders, suffix_dupes = {}, [], []
        with self.state_lock:
            self.dup_prefix = prefix
            for folder_path, is_bucket in self.dup_scan_folders(prefix):
                if is_bucket:
                    bucket_folders.append(folder_path)
                local = {}
                try:
                    with os.scandir(folder_path) as it:
                        for e in it:
                            if e.is_file():
                                file_index.setdefault(e.name, []).append((e.path, is_bucket))
                                local[e.name] = e
                except OSError as e:
                    log(f"❌ Scan {folder_path} : {e}")
                # Same-folder copies: 'x_1.ext', 'x (1).ext', 'x - Copie.ext' next to 'x.ext'
                for name, entry in local.items():
                    original = core.copy_original_name(name)
                    if not original or original not in local:
                        continue
                    try:
                        same_size = entry.stat().st_size == local[original].stat().st_size
                    except OSError:
                        continue
                    suffix_dupes.append((name, entry.path, local[original].path, same_size))

            rows = []

            def add(name, kind, p1, p2):
                rows.append({'id': self.next_dup_id, 'name': name, 'kind': kind,
                             'p1': list(p1), 'p2': list(p2)})
                self.next_dup_id += 1

            for name, items in sorted(file_index.items()):
                if len(items) < 2:
                    continue
                buckets = [p for p, b in items if b]
                organized = [p for p, b in items if not b]
                if buckets and organized:
                    if not self.is_ignored(name, [organized[0]], buckets):
                        add(name, 'auto', [organized[0]], buckets)
                elif len(organized) >= 2:
                    if not self.is_ignored(name, [organized[0]], organized[1:]):
                        add(name, 'conflict', [organized[0]], organized[1:])
            for name, path, orig, same_size in suffix_dupes:
                if self.is_ignored(name, [orig], [path]):
                    continue
                # Copy marker + identical size: safe to batch. Different size: never automatic.
                add(name, 'suffix' if same_size else 'copy', [orig], [path])

            self.dup_rows = {r['id']: r for r in rows}
            self.compare_results = {}
        counts = {}
        for r in rows:
            counts[r['kind']] = counts.get(r['kind'], 0) + 1
        log(f"🔍 Doublons ({core.SCOPES[scope][0]}) : {len(rows)} ligne(s) — "
            + ", ".join(f"{v} {KIND_LABELS[k]}" for k, v in counts.items()))
        self.progress("", 0, -1)
        self.start_compare([r['id'] for r in rows])
        return {'rows': [self.dup_row_out(r) for r in rows], 'ignored': len(self.ignore_list)}

    def api_dup_rows(self, _q):
        with self.state_lock:
            return {'rows': [self.dup_row_out(r) for r in self.dup_rows.values()],
                    'ignored': len(self.ignore_list)}

    def start_compare(self, ids):
        """Score rows in the background: the Score column fills itself while you work"""
        self.compare_gen += 1
        gen = self.compare_gen
        jobs = []
        with self.state_lock:
            for i in ids:
                row = self.dup_rows.get(i)
                if row and row['p1'] and row['p2'] and i not in self.compare_results:
                    jobs.append((i, row['p1'][0], row['p2'][0]))
        if not jobs:
            return

        def run():
            cache = {}
            log(f"🔬 Comparaison en tâche de fond : {len(jobs)} ligne(s)")
            for n, (i, pa, pb) in enumerate(jobs):
                if gen != self.compare_gen:
                    return
                try:
                    res = core.compare_files(pa, pb, cache)
                except Exception as e:
                    res = {'content': None, 'error': str(e)}
                if gen != self.compare_gen:
                    return
                with self.state_lock:
                    if i not in self.dup_rows:
                        continue
                    self.compare_results[i] = res
                self.compare_progress = (n + 1, len(jobs))
                self.emit({'t': 'score', 'id': i, 'score': self.score_out(res),
                           'done': n + 1, 'total': len(jobs)})
                if len(cache) > 400:
                    cache.clear()
            log(f"🔬 Comparaison terminée : {len(jobs)} ligne(s)")
        threading.Thread(target=run, daemon=True, name='compare').start()

    def api_dup_compare(self, body):
        ids = body.get('ids') or list(self.dup_rows.keys())
        with self.state_lock:
            for i in ids:
                self.compare_results.pop(i, None)
        self.start_compare(ids)
        return {'ok': True, 'count': len(ids)}

    def api_dup_detail(self, q):
        """Both sides of a row: highlighted path diff, sizes, verdict"""
        i = int(q.get('id', 0))
        with self.state_lock:
            row = self.dup_rows.get(i)
        if not row:
            raise HttpError(404, "Ligne disparue")
        sides = []
        for paths in (row['p1'], row['p2']):
            path = paths[0] if paths else ''
            size = None
            try:
                size = os.path.getsize(path) if path and os.path.isfile(path) else None
            except OSError:
                pass
            ext = os.path.splitext(path)[1].lower()
            sides.append({'path': path, 'rel': self.rel(path) if path else '', 'size': size,
                          'size_h': core.human_size(size) if size is not None else '',
                          'others': len(paths) - 1,
                          'video': ext in core.VIDEO_EXTS, 'image': ext in core.IMAGE_EXTS,
                          'm': int(os.path.getmtime(path)) if size is not None else 0})
        if sides[0]['rel'] and sides[1]['rel']:
            h0, h1 = core.diff_path_html(sides[0]['rel'], sides[1]['rel'])
        else:
            h0 = core._dim(sides[0]['rel'])
            h1 = core._dim(sides[1]['rel'])
        sides[0]['html'], sides[1]['html'] = h0, h1
        res = self.compare_results.get(i)
        if res is None and sides[0]['size'] is not None and sides[1]['size'] is not None:
            # Not scored yet: do this one pair now (this request's own thread)
            res = core.compare_files(sides[0]['path'], sides[1]['path'])
            with self.state_lock:
                if i in self.dup_rows:
                    self.compare_results[i] = res
            self.emit({'t': 'score', 'id': i, 'score': self.score_out(res)})
        return {'id': i, 'sides': sides,
                'sizes_differ': (sides[0]['size'] is not None and sides[1]['size'] is not None
                                 and sides[0]['size'] != sides[1]['size']),
                'score': self.score_out(res) if res is not None else None,
                'frames': core.VIDEO_SAMPLE_POINTS}

    def trash_paths(self, paths):
        n = errors = 0
        for p in paths:
            try:
                core.trash(p)
                log(f"🗑️ Corbeille : {self.rel(p)}")
                n += 1
            except Exception as e:
                log(f"❌ Corbeille {os.path.basename(p)} : {e}")
                errors += 1
        return n, errors

    def trash_dup_side(self, ids, side):
        """side 0 = Copie 1, 1 = Copie 2, None = the bad one: Copie 2, unless
        Copie 1 is the empty file (then Copie 2 is the only real image)."""
        trashed = errors = skipped = 0
        removed, sides = [], set()
        with self.fs:
            for n, i in enumerate(ids):
                row = self.dup_rows.get(i)
                if not row:
                    continue
                s = side if side is not None else (0 if self.kept_copy_empty(row) else 1)
                sides.add(s)
                key = 'p1' if s == 0 else 'p2'
                existing = [p for p in row[key] if os.path.isfile(p)]
                if not existing:
                    skipped += 1                    # nothing left on disk: stale row
                    removed.append(i)
                    continue
                t, e = self.trash_paths(existing)
                trashed += t
                errors += e
                if e == 0:
                    removed.append(i)
                if len(ids) > 20 and n % 10 == 0:
                    self.progress("Corbeille", n + 1, len(ids))
        with self.state_lock:
            for i in removed:
                self.dup_rows.pop(i, None)
                self.compare_results.pop(i, None)
        self.progress("", 0, -1)
        msg = f"{trashed} fichier(s) à la corbeille"
        if len(sides) == 1:
            msg += f" (Copie {sides.pop() + 1})"
        elif sides:
            msg += " (Copie 2, ou Copie 1 quand elle était vide)"
        if skipped:
            msg += f", {skipped} ligne(s) obsolète(s) retirée(s)"
        if errors:
            msg += f", {errors} erreur(s)"
        log(f"🗑️ Doublons : {msg}")
        return {'removed': removed, 'trashed': trashed, 'errors': errors, 'msg': msg}

    def api_dup_trash(self, body):
        side = body.get('side', 1)
        return self.trash_dup_side([int(i) for i in body.get('ids', [])],
                                   None if side == 'auto' else int(side))

    @staticmethod
    def kept_copy_empty(row):
        """Copie 1 is 0 bytes while a Copie 2 has content: the batch would trash
        the only good copy. Read from disk, not from the comparison, so unscored
        rows are caught too. Unreadable -> treated as empty (never automate)."""
        try:
            return (os.path.getsize(row['p1'][0]) == 0
                    and any(os.path.getsize(p) > 0 for p in row['p2']))
        except (OSError, IndexError):
            return True

    def auto_rows(self):
        """Auto / Suffixe rows whose content was NOT flagged as different
        -> (eligible ids, skipped for content, skipped because Copie 1 is empty)"""
        eligible, skipped, empty = [], 0, 0
        for i, row in self.dup_rows.items():
            if row['kind'] not in ('auto', 'suffix'):
                continue
            if self.kept_copy_empty(row):
                empty += 1
                continue
            res = self.compare_results.get(i)
            level = core.verdict_for(res)[0] if res is not None else 'unknown'
            if level in ('diff', 'related'):
                skipped += 1
            else:
                eligible.append(i)
        return eligible, skipped, empty

    def api_dup_auto(self, body):
        with self.state_lock:
            eligible, skipped, empty = self.auto_rows()
            n_files = sum(len(self.dup_rows[i]['p2']) for i in eligible)
            pending = sum(1 for i in eligible if i not in self.compare_results)
        if body.get('dry', True):
            return {'rows': len(eligible), 'files': n_files, 'skipped': skipped,
                    'empty': empty, 'unscored': pending}
        return self.trash_dup_side(eligible, 1)

    def api_dup_ignore(self, body):
        ids = [int(i) for i in body.get('ids', [])]
        with self.state_lock:
            for i in ids:
                row = self.dup_rows.pop(i, None)
                if row:
                    key = self.pair_key(row['p1'], row['p2'])
                    self.ignore_list.add(key)
                    log(f"🙈 Doublon ignoré : {key}")
        core.save_json(core.IGNORE_FILE, sorted(self.ignore_list))
        return {'removed': ids, 'ignored': len(self.ignore_list)}

    def api_dup_forget(self, _body):
        n = len(self.ignore_list)
        self.ignore_list = set()
        core.save_json(core.IGNORE_FILE, [])
        log(f"♻️ Liste des doublons ignorés vidée ({n} entrée(s))")
        return {'forgotten': n}

    def api_dup_rename(self, body):
        """The usual fix when a '_1' is in fact a different shot with a lazy name"""
        i, side = int(body.get('id', 0)), int(body.get('side', 1))
        new_name = (body.get('name') or '').strip()
        with self.fs, self.state_lock:
            row = self.dup_rows.get(i)
            if not row:
                raise HttpError(404, "Ligne disparue")
            key = 'p1' if side == 0 else 'p2'
            old = row[key][0] if row[key] else ''
            new_path = self.rename_file(old, new_name)
            row[key] = [new_path] + row[key][1:]
            if side == 1:
                row['name'] = new_name
            row['kind'] = 'renamed'              # no longer a collision -> out of the batch
            self.compare_results.pop(i, None)
            return {'row': self.dup_row_out(row)}

    def rename_file(self, old, new_name):
        if not old or not os.path.isfile(old):
            raise HttpError(404, "Fichier introuvable")
        if not new_name or re.search(r'[\\/:*?"<>|]', new_name):
            raise HttpError(400, "Nom invalide")
        folder = os.path.dirname(old)
        new_path = os.path.join(folder, new_name)
        if os.path.exists(new_path) and not core.same_path(new_path, old):
            raise HttpError(409, f"« {new_name} » existe déjà dans ce dossier.")
        os.rename(old, new_path)
        log(f"✏️ Renommé : {self.rel(old)} -> {new_name}")
        return new_path

    # ------------------------------------------------------------------ tab 3: sort

    def iter_source_files(self, prefix):
        """(name, path, year, current_subfolder, stat) for the chosen source.
        ''      -> loose files at the root of Camera, year unknown
        prefix  -> everything under Camera\\YEAR\\<prefix>YEAR\\ (sub-folders included);
                   the year comes from the folder it sits in"""
        base = self.base
        if not prefix:
            for e in sorted(os.scandir(base), key=lambda e: e.name):
                if e.is_file():
                    yield e.name, e.path, '', '', e.stat()
            return
        for year in self.years():
            year_dir = os.path.join(base, year)
            bucket = os.path.join(year_dir, f"{prefix}{year}")
            if not os.path.isdir(bucket):
                continue

            def walk(folder):
                try:
                    entries = sorted(os.scandir(folder), key=lambda e: e.name)
                except OSError:
                    return
                for e in entries:
                    if e.is_dir(follow_symlinks=False):
                        yield from walk(e.path)
                    else:
                        # relative to the year, so it can be reused as a folder value
                        yield e.name, e.path, year, os.path.relpath(folder, year_dir), e.stat()
            yield from walk(bucket)

    def file_out(self, info):
        return {'uid': info['uid'], 'name': info['filename'], 'path': info['filepath'],
                'ts': info['ts'], 'dt': info['dt_text'], 'year': info['year'],
                'folder': info['folder'], 'video': info['ext'] in core.VIDEO_EXTS,
                'm': info['m'], 'size': info['size'],
                'hue': core.folder_hue(info['folder']) if info['folder'] else None}

    def api_sort_files(self, q):
        self.require_base()
        self.flush_edits()                    # tags of the previous source are safe on disk
        source = int(q.get('source', 0))
        prefix = core.SCOPES[source][1] if 0 <= source < len(core.SCOPES) else ''
        edits = core.load_json(core.EDITS_FILE, {})
        files = []
        with self.state_lock:
            for name, path, forced_year, here, st in self.iter_source_files(prefix):
                ext = os.path.splitext(name)[1].lower()
                if ext not in core.MEDIA_EXTS:
                    continue
                year = forced_year
                if not year:
                    m = re.search(r'(20\d{2})', name)
                    year = m.group(1) if m else (core.get_year_from_file(name, path) or '')
                dt = core.file_datetime(name, path, st.st_mtime)
                info = {'uid': self.next_uid, 'filename': name, 'filepath': path, 'ext': ext,
                        'ts': dt.timestamp() if dt.year > 1970 else 0,
                        'dt_text': dt.strftime('%Y-%m-%d %H:%M:%S'),
                        'year': year, 'm': int(st.st_mtime), 'size': st.st_size,
                        'folder': edits.get(name, here)}
                self.next_uid += 1
                files.append(info)
            files.sort(key=lambda x: (x['ts'], x['filename']))
            self.files = files
            self.files_by_uid = {f['uid']: f for f in files}
            self.sort_prefix = prefix
        log(f"[TRI] {core.SCOPES[source][0]} : {len(files)} fichier(s) à trier")
        self.start_prefetch([f['filepath'] for f in files if f['ext'] in core.VIDEO_EXTS])
        return {'files': [self.file_out(f) for f in files], 'source': source}

    def start_prefetch(self, videos):
        """One frame per video (25 %) in the background: previews are instant"""
        self.prefetch_gen += 1
        gen = self.prefetch_gen
        if not core.FFMPEG or not videos:
            return

        def run():
            for p in videos:
                if gen != self.prefetch_gen:
                    return
                try:
                    core.thumbnail_file(p)
                except Exception:
                    pass
        threading.Thread(target=run, daemon=True, name='prefetch').start()

    def api_sort_folders(self, q):
        year = q.get('year', '')
        year_folder = os.path.join(self.base, year)
        if not re.match(r'^\d{4}$', year) or not os.path.isdir(year_folder):
            return {'year': year, 'folders': []}
        entries = [{'value': e.name, 'label': e.name}
                   for e in sorted(os.scandir(year_folder), key=lambda e: e.name.lower())
                   if e.is_dir() and not e.name.startswith('!')]
        # Plus the sub-folders of the bucket being sorted, so a screenshot can stay
        # among screenshots or move out to a real event folder
        prefix = self.sort_prefix
        if prefix:
            bucket_name = f"{prefix}{year}"
            bucket = os.path.join(year_folder, bucket_name)
            if os.path.isdir(bucket):
                subs = [{'value': os.path.join(bucket_name, e.name), 'label': e.name, 'sub': True}
                        for e in sorted(os.scandir(bucket), key=lambda e: e.name.lower())
                        if e.is_dir() and not e.name.startswith('!')]
                entries = ([{'value': bucket_name, 'label': f"racine {bucket_name}", 'sub': True}]
                           + subs + entries)
        for e in entries:
            e['hue'] = core.folder_hue(e['value'])
        return {'year': year, 'folders': entries}

    def assign(self, uids, folder):
        with self.state_lock:
            for uid in uids:
                info = self.files_by_uid.get(int(uid))
                if info is not None:
                    info['folder'] = folder
        self.schedule_save()

    def api_sort_assign(self, body):
        folder = (body.get('folder') or '').strip()
        self.assign(body.get('uids', []), folder)
        return {'ok': True, 'hue': core.folder_hue(folder) if folder else None}

    def api_sort_year(self, body):
        year = (body.get('year') or '').strip()
        if year and not re.match(r'^\d{4}$', year):
            raise HttpError(400, "Année invalide")
        with self.state_lock:
            for uid in body.get('uids', []):
                info = self.files_by_uid.get(int(uid))
                if info is not None:
                    info['year'] = year
        return {'ok': True}

    def api_sort_newfolder(self, body):
        year, name = (body.get('year') or '').strip(), (body.get('name') or '').strip()
        if not re.match(r'^\d{4}$', year):
            raise HttpError(400, "Année inconnue pour le fichier sélectionné")
        if not name or re.search(r'[\\/:*?"<>|]', name) or name.startswith('!'):
            raise HttpError(400, "Nom de dossier invalide")
        with self.fs:
            os.makedirs(os.path.join(self.base, year, name), exist_ok=True)
        log(f"✨ Dossier créé : {year}/{name}")
        self.assign(body.get('uids', []), name)
        return {'ok': True, 'hue': core.folder_hue(name)}

    def api_folder_rename(self, body):
        year = body.get('year', '')
        old, new_name = body.get('old', ''), (body.get('new') or '').strip()
        old_path = os.path.join(self.base, year, old)
        if not re.match(r'^\d{4}$', year) or not os.path.isdir(old_path):
            raise HttpError(404, "Dossier introuvable")
        if not new_name or re.search(r'[\\/:*?"<>|]', new_name):
            raise HttpError(400, "Nom invalide")
        new_path = os.path.join(os.path.dirname(old_path), new_name)
        if os.path.exists(new_path) and not core.same_path(new_path, old_path):
            raise HttpError(409, f"« {new_name} » existe déjà pour cette année.")
        with self.fs:
            os.rename(old_path, new_path)
        parent = os.path.dirname(old)
        new_value = os.path.join(parent, new_name) if parent else new_name
        log(f"✏️ Dossier renommé : {year}/{old} -> {new_name}")
        # Files already assigned to the old name follow it
        followed = [f['uid'] for f in self.files if f['folder'] == old and f['year'] == year]
        self.assign(followed, new_value)
        return {'value': new_value, 'followed': followed, 'hue': core.folder_hue(new_value)}

    def schedule_save(self):
        """Debounced: assigning several folders in a row rewrites the file once"""
        if self.save_timer:
            self.save_timer.cancel()
        self.save_timer = threading.Timer(0.8, self.save_edits)
        self.save_timer.daemon = True
        self.save_timer.start()

    def flush_edits(self):
        if self.save_timer and self.save_timer.is_alive():
            self.save_timer.cancel()
            self.save_edits()
        self.save_timer = None

    def save_edits(self):
        with self.state_lock:
            previous = core.load_json(core.EDITS_FILE, {})
            current = {f['filename'] for f in self.files}
            # Tags of the OTHER sources stay; only what this listing shows is rewritten
            edits = {k: v for k, v in previous.items()
                     if k not in current and k not in self.forgotten}
            edits.update({f['filename']: f['folder'] for f in self.files if f['folder']})
            self.forgotten.clear()
            # Never silently shrink the file: keep a copy first, so a bug can't wipe
            # an afternoon of tagging.
            if previous and len(edits) < len(previous):
                core.save_json(core.EDITS_FILE + '.bak', previous)
                log(f"💾 {len(previous)} tag(s) copiés dans {os.path.basename(core.EDITS_FILE)}.bak "
                    f"(nouveau total : {len(edits)})")
            core.save_json(core.EDITS_FILE, edits)

    def sync_from_view(self, view):
        """What is on screen is what you trusted: the data must match it before
        anything is saved or moved."""
        fixed = 0
        with self.state_lock:
            for v in view or []:
                info = self.files_by_uid.get(int(v.get('uid', 0)))
                if info is None:
                    continue
                shown = (v.get('folder') or '').strip()
                if shown and info['folder'] != shown:
                    info['folder'] = shown
                    fixed += 1
                year = (v.get('year') or '').strip()
                if year and info['year'] != year:
                    info['year'] = year
                    fixed += 1
        if fixed:
            log(f"⚠️ {fixed} valeur(s) resynchronisée(s) depuis l'écran")
        return fixed

    def api_sort_apply(self, body):
        self.require_base()
        self.sync_from_view(body.get('view'))
        moved, errors = 0, []
        with self.fs:
            todo = [i for i in self.files if i['year'] and i['folder']]
            if not todo:
                return {'moved': 0, 'errors': [], 'files': [self.file_out(f) for f in self.files]}
            remaining = []
            for n, info in enumerate(self.files):
                if not (info['year'] and info['folder']):
                    remaining.append(info)
                    continue
                target = os.path.join(self.base, info['year'], info['folder'])
                if core.same_path(os.path.dirname(info['filepath']), target):
                    remaining.append(info)          # already there: leave it alone
                    continue
                try:
                    core.safe_move(info['filepath'], target, dup_dir=self.dup_dir)
                    log(f"📦 {info['filename']} -> {info['year']}/{info['folder']}/")
                    moved += 1
                    self.forgotten.add(info['filename'])
                except Exception as e:
                    errors.append(f"{info['filename']} : {e}")
                    log(f"❌ Déplacement {info['filename']} : {e}")
                    remaining.append(info)
                if n % 10 == 0:
                    self.progress("Déplacements", n + 1, len(self.files))
            with self.state_lock:
                self.files = remaining
                self.files_by_uid = {f['uid']: f for f in remaining}
            self.save_edits()
        self.progress("", 0, -1)
        log(f"✅ {moved} fichier(s) déplacé(s)" + (f", {len(errors)} erreur(s)" if errors else ""))
        return {'moved': moved, 'errors': errors, 'files': [self.file_out(f) for f in self.files]}

    def api_sort_delete(self, body):
        deleted, errors = [], 0
        with self.fs:
            for uid in body.get('uids', []):
                info = self.files_by_uid.get(int(uid))
                if info is None:
                    continue
                try:
                    core.trash(info['filepath'])
                    log(f"🗑️ Corbeille : {self.rel(info['filepath'])}")
                    deleted.append(info['uid'])
                    self.forgotten.add(info['filename'])
                except Exception as e:
                    log(f"❌ Suppression {info['filename']} : {e}")
                    errors += 1
        with self.state_lock:
            gone = set(deleted)
            self.files = [f for f in self.files if f['uid'] not in gone]
            for uid in gone:
                self.files_by_uid.pop(uid, None)
        if deleted:
            self.schedule_save()
        return {'deleted': deleted, 'errors': errors}

    def api_sort_byapp(self, body):
        """Screenshots sitting loose at the root of the buckets -> per-app folders"""
        prefix = self.sort_prefix
        if not prefix:
            raise HttpError(400, "Choisis la source Screenshots ou ScreenRecorder d'abord")
        plan, seen = [], 0
        for year in self.years():
            bucket = os.path.join(self.base, year, f"{prefix}{year}")
            if not os.path.isdir(bucket):
                continue
            for e in sorted(os.scandir(bucket), key=lambda e: e.name):
                if not e.is_file() or os.path.splitext(e.name)[1].lower() not in core.MEDIA_EXTS:
                    continue
                seen += 1
                app = core.app_from_filename(e.name)
                if app:
                    plan.append((e.path, os.path.join(bucket, app), app))
        apps = sorted({a for _p, _t, a in plan})
        if body.get('dry', True):
            return {'files': len(plan), 'seen': seen, 'apps': apps}
        moved = errors = 0
        with self.fs:
            for n, (path, target, _app) in enumerate(plan):
                try:
                    core.safe_move(path, target, dup_dir=self.dup_dir)
                    moved += 1
                except Exception as e:
                    log(f"[APPLIS] ❌ {os.path.basename(path)} : {e}")
                    errors += 1
                if n % 25 == 0:
                    self.progress("Rangement par appli", n + 1, len(plan))
        self.progress("", 0, -1)
        log(f"[APPLIS] {moved} capture(s) rangée(s) dans {len(apps)} dossier(s)"
            + (f", {errors} erreur(s)" if errors else ""))
        return {'moved': moved, 'errors': errors, 'apps': apps}

    def api_sort_auto(self, _body):
        """Camera root screenshots / recordings + DCIM\\ScreenRecorder + Pictures -> buckets"""
        self.require_base()
        base = self.base
        total = 0
        with self.fs:
            for src, prefix in ((os.path.normpath(os.path.join(base, '..', 'ScreenRecorder')), 'ScreenRecorder'),
                                (os.path.normpath(os.path.join(base, '..', '..', 'Pictures')), 'Pictures')):
                if not os.path.isdir(src):
                    log(f"⚠️ Dossier absent : {src}")
                    continue
                for e in list(os.scandir(src)):
                    if not e.is_file() or os.path.splitext(e.name)[1].lower() not in core.MEDIA_EXTS:
                        continue
                    year = core.get_year_from_file(e.name, e.path)
                    if not year:
                        log(f"⚠️ Année introuvable, ignoré : {e.name}")
                        continue
                    try:
                        core.safe_move(e.path, os.path.join(base, year, f"!{prefix}_{year}"),
                                       dup_dir=self.dup_dir)
                        total += 1
                    except Exception as ex:
                        log(f"❌ {e.name} : {ex}")
            for e in list(os.scandir(base)):
                if not e.is_file():
                    continue
                low = e.name.lower()
                is_shot = 'screenshot' in low
                is_rec = 'screen' in low and 'recorder' in low
                if not (is_shot or is_rec):
                    continue
                year = core.get_year_from_file(e.name, e.path)
                if not year:
                    continue
                folder = f"!Screenshots_{year}" if is_shot else f"!ScreenRecorder_{year}"
                try:
                    core.safe_move(e.path, os.path.join(base, year, folder), dup_dir=self.dup_dir)
                    log(f"📦 {e.name} -> {year}/{folder}/")
                    total += 1
                except Exception as ex:
                    log(f"❌ {e.name} : {ex}")
        log(f"⚡ Rangement automatique : {total} fichier(s)")
        return {'moved': total}

    # ------------------------------------------------------------------ tab 4: viewer

    def api_viewer_years(self, _q):
        out = []
        for y in reversed(self.years()):
            try:
                n = sum(1 for e in os.scandir(os.path.join(self.base, y))
                        if e.is_dir() and not e.name.startswith('!'))
            except OSError:
                n = 0
            out.append({'year': y, 'folders': n})
        return {'years': out}

    def api_viewer_folders(self, q):
        year = q.get('year', '')
        year_dir = os.path.join(self.base, year)
        if not re.match(r'^\d{4}$', year) or not os.path.isdir(year_dir):
            return {'folders': []}
        out = []
        for e in sorted(os.scandir(year_dir), key=lambda e: e.name.lower()):
            if not e.is_dir():
                continue
            try:
                n = sum(1 for f in os.scandir(e.path)
                        if f.is_file() and os.path.splitext(f.name)[1].lower() in core.MEDIA_EXTS)
            except OSError:
                n = 0
            out.append({'name': e.name, 'count': n, 'hue': core.folder_hue(e.name),
                        'special': e.name.startswith('!')})
        # Event folders first, buckets at the end
        out.sort(key=lambda f: (f['special'], f['name'].lower()))
        return {'folders': out}

    def api_viewer_media(self, q):
        year, folder = q.get('year', ''), q.get('folder', '')
        path = os.path.join(self.base, year, folder)
        if not self.allowed(path) or not os.path.isdir(path):
            return {'media': [], 'subfolders': []}
        media, subs = [], []
        for e in os.scandir(path):
            if e.is_dir():
                subs.append(e.name)
                continue
            ext = os.path.splitext(e.name)[1].lower()
            if ext not in core.MEDIA_EXTS:
                continue
            st = e.stat()
            dt = core.file_datetime(e.name, e.path, st.st_mtime)
            media.append({'name': e.name, 'path': e.path, 'video': ext in core.VIDEO_EXTS,
                          'ts': dt.timestamp() if dt.year > 1970 else 0,
                          'dt': dt.strftime('%d/%m/%Y %H:%M'), 'm': int(st.st_mtime),
                          'size': st.st_size})
        media.sort(key=lambda m: m['name'].lower())
        return {'media': media, 'subfolders': sorted(subs, key=str.lower)}

    def api_media_rename(self, body):
        with self.fs:
            new_path = self.rename_file(body.get('path', ''), (body.get('name') or '').strip())
        return {'path': new_path, 'name': os.path.basename(new_path),
                'm': int(os.path.getmtime(new_path))}

    def api_media_trash(self, body):
        deleted, errors = [], 0
        with self.fs:
            for p in body.get('paths', []):
                if not self.allowed(p) or not os.path.isfile(p):
                    errors += 1
                    continue
                try:
                    core.trash(p)
                    log(f"🗑️ Corbeille : {self.rel(p)}")
                    deleted.append(p)
                except Exception as e:
                    log(f"❌ Suppression {os.path.basename(p)} : {e}")
                    errors += 1
        return {'deleted': deleted, 'errors': errors}

    # ------------------------------------------------------------------ lifecycle

    def watchdog(self):
        """The window closed (no SSE client for a while) -> tidy up and exit"""
        while True:
            time.sleep(3)
            with self.sub_lock:
                n = len(self.subscribers)
            if n:
                self.last_client_seen = time.time()
            elif self.had_client and time.time() - self.last_client_seen > 20:
                log("👋 Fenêtre fermée : arrêt du serveur")
                self.shutdown()
                return

    def shutdown(self):
        self.flush_edits()
        self.compare_gen += 1
        self.prefetch_gen += 1
        n = core.purge_frames()
        if n:
            log(f"🧹 {n} image(s) vidéo temporaire(s) supprimée(s)")
        try:
            os.remove(PORT_FILE)
        except OSError:
            pass
        if self.httpd:
            threading.Thread(target=self.httpd.shutdown, daemon=True).start()


# ====================================================================== HTTP

GET_ROUTES = {
    '/api/state': 'api_state',
    '/api/rename': 'api_rename',
    '/api/dup': 'api_dup_rows',
    '/api/dup/detail': 'api_dup_detail',
    '/api/sort/files': 'api_sort_files',
    '/api/sort/folders': 'api_sort_folders',
    '/api/viewer/years': 'api_viewer_years',
    '/api/viewer/folders': 'api_viewer_folders',
    '/api/viewer/media': 'api_viewer_media',
}

POST_ROUTES = {
    '/api/config': 'api_config',
    '/api/browse': 'api_browse',
    '/api/open': 'api_open',
    '/api/startup': 'api_startup',
    '/api/import': 'api_import',
    '/api/rename/apply': 'api_rename_apply',
    '/api/rename/exclude': 'api_rename_exclude',
    '/api/dup/scan': 'api_dup_scan',
    '/api/dup/compare': 'api_dup_compare',
    '/api/dup/trash': 'api_dup_trash',
    '/api/dup/auto': 'api_dup_auto',
    '/api/dup/ignore': 'api_dup_ignore',
    '/api/dup/forget': 'api_dup_forget',
    '/api/dup/rename': 'api_dup_rename',
    '/api/sort/assign': 'api_sort_assign',
    '/api/sort/year': 'api_sort_year',
    '/api/sort/newfolder': 'api_sort_newfolder',
    '/api/sort/apply': 'api_sort_apply',
    '/api/sort/delete': 'api_sort_delete',
    '/api/sort/byapp': 'api_sort_byapp',
    '/api/sort/auto': 'api_sort_auto',
    '/api/folder/rename': 'api_folder_rename',
    '/api/media/rename': 'api_media_rename',
    '/api/media/trash': 'api_media_trash',
}


def make_handler(app):
    class Handler(BaseHTTPRequestHandler):
        protocol_version = 'HTTP/1.1'
        server_version = 'TriPhoto'

        def log_message(self, *args):
            pass

        # ---- helpers
        def send_bytes(self, data, ctype, code=200, cache=None, extra=None):
            self.send_response(code)
            self.send_header('Content-Type', ctype)
            self.send_header('Content-Length', str(len(data)))
            self.send_header('Cache-Control', cache or 'no-store')
            for k, v in (extra or {}).items():
                self.send_header(k, v)
            self.end_headers()
            if self.command != 'HEAD':
                self.wfile.write(data)

        def send_json(self, obj, code=200):
            self.send_bytes(json.dumps(obj, ensure_ascii=False).encode('utf-8'),
                            'application/json; charset=utf-8', code)

        def host_ok(self):
            # Blocks DNS-rebinding: only our own origin may talk to us
            host = (self.headers.get('Host') or '').split(':')[0]
            return host in ('127.0.0.1', 'localhost')

        def query(self):
            return {k: v[0] for k, v in parse_qs(urlparse(self.path).query).items()}

        # ---- verbs
        def do_HEAD(self):
            self.do_GET()

        def do_GET(self):
            if not self.host_ok():
                return self.send_json({'error': 'host'}, 403)
            path = urlparse(self.path).path
            q = self.query()
            try:
                if path == '/api/ping':
                    return self.send_json({'app': 'TriPhoto', 'pid': os.getpid()})
                if path == '/api/events':
                    return self.sse()
                if path in GET_ROUTES:
                    return self.send_json(getattr(app, GET_ROUTES[path])(q))
                if path == '/thumb':
                    return self.serve_thumb(q)
                if path == '/preview':
                    return self.serve_preview(q)
                if path == '/frame':
                    return self.serve_frame(q)
                if path == '/media':
                    return self.serve_media(q)
                return self.serve_static(path)
            except HttpError as e:
                return self.send_json({'error': e.msg}, e.code)
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                return
            except Exception as e:
                log(f"❌ GET {path} : {e}")
                try:
                    return self.send_json({'error': str(e)}, 500)
                except Exception:
                    return

        def do_POST(self):
            if not self.host_ok() or self.headers.get('X-Token') != app.token:
                return self.send_json({'error': 'forbidden'}, 403)
            path = urlparse(self.path).path
            try:
                length = int(self.headers.get('Content-Length') or 0)
                body = json.loads(self.rfile.read(length) or b'{}') if length else {}
                if path not in POST_ROUTES:
                    return self.send_json({'error': 'not found'}, 404)
                return self.send_json(getattr(app, POST_ROUTES[path])(body))
            except HttpError as e:
                return self.send_json({'error': e.msg}, e.code)
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                return
            except Exception as e:
                log(f"❌ {path} : {e}")
                return self.send_json({'error': str(e)}, 500)

        # ---- SSE
        def sse(self):
            q = queue.Queue(maxsize=2000)
            for line in list(app.backlog):
                q.put_nowait(json.dumps({'t': 'log', 'line': line}, ensure_ascii=False))
            with app.sub_lock:
                app.subscribers.append(q)
                app.had_client = True
            self.send_response(200)
            self.send_header('Content-Type', 'text/event-stream')
            self.send_header('Cache-Control', 'no-store')
            self.send_header('Connection', 'keep-alive')
            self.end_headers()
            self.close_connection = True
            try:
                self.wfile.write(b'retry: 1500\n\n')
                self.wfile.flush()
                while True:
                    try:
                        data = q.get(timeout=10)
                        self.wfile.write(f"data: {data}\n\n".encode('utf-8'))
                    except queue.Empty:
                        self.wfile.write(b': ping\n\n')
                    self.wfile.flush()
            except Exception:
                pass
            finally:
                with app.sub_lock:
                    if q in app.subscribers:
                        app.subscribers.remove(q)
                app.last_client_seen = time.time()

        # ---- files
        def media_path(self, q):
            p = q.get('p', '')
            if not app.allowed(p) or not os.path.isfile(p):
                raise HttpError(404, 'introuvable')
            return p

        def serve_thumb(self, q):
            p = self.media_path(q)
            try:
                out = core.thumbnail_file(p)
            except Exception as e:
                log(f"❌ Vignette {os.path.basename(p)} : {e}")
                out = None
            if not out:
                return self.send_bytes(b'', 'image/jpeg', 204)
            with open(out, 'rb') as f:
                data = f.read()
            self.send_bytes(data, 'image/jpeg', cache='private, max-age=604800')

        def serve_preview(self, q):
            p = self.media_path(q)
            ext = os.path.splitext(p)[1].lower()
            if ext in core.VIDEO_EXTS:
                jpg = core.grab_one_shot(p, int(q.get('pct', core.DEFAULT_SHOT_PCT)))
                if not jpg:
                    return self.send_bytes(b'', 'image/jpeg', 204)
                with open(jpg, 'rb') as f:
                    return self.send_bytes(f.read(), 'image/jpeg', cache='private, max-age=86400')
            data = core.preview_bytes(p)
            self.send_bytes(data, 'image/jpeg', cache='private, max-age=86400')

        def serve_frame(self, q):
            p = self.media_path(q)
            jpg = core.grab_one_shot(p, int(q.get('pct', 50)))
            if not jpg:
                return self.send_bytes(b'', 'image/jpeg', 204)
            with open(jpg, 'rb') as f:
                self.send_bytes(f.read(), 'image/jpeg', cache='private, max-age=86400')

        def serve_media(self, q):
            """Raw file with Range support, so <video> can seek"""
            p = self.media_path(q)
            size = os.path.getsize(p)
            ctype = mimetypes.guess_type(p)[0] or 'application/octet-stream'
            start, end = 0, size - 1
            rng = self.headers.get('Range')
            code = 200
            if rng:
                m = re.match(r'bytes=(\d*)-(\d*)', rng)
                if m:
                    if m.group(1):
                        start = int(m.group(1))
                        if m.group(2):
                            end = min(int(m.group(2)), size - 1)
                    elif m.group(2):
                        start = max(0, size - int(m.group(2)))
                    code = 206
            if start > end:
                self.send_response(416)
                self.send_header('Content-Range', f'bytes */{size}')
                self.send_header('Content-Length', '0')
                self.end_headers()
                return
            length = end - start + 1
            self.send_response(code)
            self.send_header('Content-Type', ctype)
            self.send_header('Accept-Ranges', 'bytes')
            self.send_header('Content-Length', str(length))
            self.send_header('Cache-Control', 'private, max-age=3600')
            if code == 206:
                self.send_header('Content-Range', f'bytes {start}-{end}/{size}')
            self.end_headers()
            if self.command == 'HEAD':
                return
            with open(p, 'rb') as f:
                f.seek(start)
                remaining = length
                while remaining > 0:
                    chunk = f.read(min(1024 * 512, remaining))
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    remaining -= len(chunk)

        def serve_static(self, path):
            if path in ('/', '/index.html'):
                with open(os.path.join(WEB_DIR, 'index.html'), 'r', encoding='utf-8') as f:
                    html = f.read().replace('__TOKEN__', app.token)
                # Theme baked into the page so the first paint is already right
                # (localStorage would not survive: the port, hence the origin, changes each launch)
                theme = str((app.config.get('ui') or {}).get('theme') or 'nuit')
                html = html.replace('__THEME__', re.sub(r'[^a-z0-9-]', '', theme.lower()) or 'nuit')
                return self.send_bytes(html.encode('utf-8'), 'text/html; charset=utf-8')
            rel = path.lstrip('/')
            full = os.path.normpath(os.path.join(WEB_DIR, rel))
            if not core.is_under(full, WEB_DIR) or not os.path.isfile(full):
                return self.send_json({'error': 'not found'}, 404)
            ctype = mimetypes.guess_type(full)[0] or 'application/octet-stream'
            if ctype.startswith('text/') or ctype in ('application/javascript',):
                ctype += '; charset=utf-8'
            with open(full, 'rb') as f:
                self.send_bytes(f.read(), ctype)

    return Handler


class Server(ThreadingHTTPServer):
    daemon_threads = True

    def handle_error(self, request, client_address):
        # The browser drops connections all the time (cancelled thumbnails,
        # video seeks, window closed): not worth a traceback in the log.
        exc = sys.exc_info()[1]
        if isinstance(exc, (ConnectionResetError, ConnectionAbortedError, BrokenPipeError)):
            return
        super().handle_error(request, client_address)


def run(port=0, no_import=False):
    mimetypes.add_type('application/javascript', '.js')
    mimetypes.add_type('text/css', '.css')
    os.makedirs(core.CACHE_DIR, exist_ok=True)
    core.rotate_log()
    app = App(no_import=no_import)
    log(f"=== TriPhoto (web) — {datetime.now():%Y-%m-%d} ===")
    log(f"Python : {sys.executable}")
    log(f"Camera : {app.base}")
    log(f"Cache : {core.CACHE_DIR}")
    if not core.PIL_AVAILABLE:
        log("⚠️ Pillow indisponible : pas d'aperçus")
    elif not core.HEIF_AVAILABLE:
        log("⚠️ pillow-heif indisponible : pas d'aperçus HEIC")
    if core.FFMPEG:
        log(f"🎬 ffmpeg : {core.FFMPEG}")
    else:
        log("⚠️ ffmpeg introuvable : aucun aperçu vidéo (\"ffmpeg_dir\" dans triphoto_config.json)")
    if os.path.isdir(app.base):
        core.purge_legacy_temp(app.base)
    threading.Thread(target=core.prune_thumb_cache, daemon=True).start()

    httpd = Server(('127.0.0.1', port), make_handler(app))
    app.httpd = httpd
    real_port = httpd.server_address[1]
    core.save_json(PORT_FILE, {'port': real_port, 'pid': os.getpid(),
                               'started': datetime.now().isoformat(timespec='seconds')})
    log(f"🌐 http://127.0.0.1:{real_port}/")
    threading.Thread(target=app.watchdog, daemon=True).start()
    try:
        httpd.serve_forever(poll_interval=0.5)
    except KeyboardInterrupt:
        app.shutdown()
    return real_port
