#!/usr/bin/env python3
"""
TriPhoto - Smart Photo/Video Organizer (Qt edition)
Assistant en 3 volets : renommage des dossiers, doublons, tri des médias.
Logs dans la console. Rien n'est exécuté sans validation.
"""

import os
import re
import sys
import json
import shutil
import zlib
import difflib
import filecmp
import threading
import subprocess
from collections import OrderedDict, deque
from datetime import timedelta
from datetime import datetime

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.join(SCRIPT_DIR, 'triphoto_config.json')
EDITS_FILE = os.path.join(SCRIPT_DIR, 'triphoto_edits.json')
IGNORE_FILE = os.path.join(SCRIPT_DIR, 'triphoto_ignore.json')
EXCLUSION_FILE = os.path.join(SCRIPT_DIR, 'FolderDoublonExclusion.txt')

DEFAULT_CAMERA_PATH = r"P:\AutoUpload\Xiaomi 2407FPN8EG\DCIM\Camera"

# pCloud sync root: the folder that holds DCIM/ and Pictures/.
# Deduced from the Camera folder when left empty (Camera -> DCIM -> root).
DEFAULT_PCLOUD_ROOT = ""

# Sources the sorting tab can work on: label -> prefix of the year sub-folder
# ('' = loose files at the root of Camera)
SORT_SOURCES = [
    ("📷 Camera", ''),
    ("🖼️ Screenshots", '!Screenshots_'),
    ("🎬 ScreenRecorder", '!ScreenRecorder_'),
]

# Sub-folders of DCIM emptied into Camera\YEAR\!<name>_YEAR
DCIM_SPECIAL_FOLDERS = {
    'Screenshots': 'Screenshots',
    'Screenshot': 'Screenshots',
    'ScreenRecorder': 'ScreenRecorder',
    'Screenrecorder': 'ScreenRecorder',
    'Screen Recorder': 'ScreenRecorder',
    'ScreenRecords': 'ScreenRecorder',
}

IMAGE_EXTS = {'.jpg', '.jpeg', '.png', '.gif', '.bmp', '.tiff', '.heic', '.heif'}
VIDEO_EXTS = {'.mp4', '.avi', '.mov', '.wmv', '.flv', '.mkv', '.m4v', '.3gp', '.webm', '.mts'}
VIDEO_PERCENTS = [0, 10, 15, 25, 30, 50, 65, 75, 85, 95, 100]


def log(message):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {message}")


# ==================== AUTO-INSTALL DEPENDENCIES ====================

def ensure_packages():
    """Detect missing packages and pip-install them automatically"""
    required = {
        'PIL': 'pillow',
        'pillow_heif': 'pillow-heif',
        'send2trash': 'send2trash',
        'PySide6': 'PySide6',
    }
    flags = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0

    missing = []
    for module, package in required.items():
        try:
            __import__(module)
            log(f"Deps: ✅ {package}: OK")
        except ImportError:
            missing.append((module, package))

    if not missing:
        return

    for module, package in missing:
        log(f"Deps: ⬇️ {package}: missing, installing (peut prendre quelques minutes)...")
        try:
            result = subprocess.run(
                [sys.executable, '-m', 'pip', 'install', package],
                capture_output=True, text=True, timeout=900, creationflags=flags
            )
            output = (result.stdout or '') + '\n' + (result.stderr or '')
            for line in output.splitlines():
                if 'Successfully installed' in line or 'already satisfied' in line:
                    log(f"Deps:    pip: {line.strip()}")
            if result.returncode != 0:
                tail = output.strip().splitlines()[-3:]
                log(f"Deps: ❌ {package}: pip failed -> " + " | ".join(tail))
        except Exception as e:
            log(f"Deps: ❌ {package}: install error -> {e}")

    # Refresh import system so freshly installed packages are found
    import importlib
    import site
    importlib.invalidate_caches()
    try:
        user_site = site.getusersitepackages()
        if user_site and os.path.isdir(user_site) and user_site not in sys.path:
            sys.path.insert(0, user_site)
            log(f"Deps: added to sys.path: {user_site}")
    except Exception:
        pass

    for module, package in missing:
        try:
            __import__(module)
            log(f"Deps: ✅ {package}: ready")
        except ImportError as e:
            log(f"Deps: ❌ {package}: still not importable ({e})")


ensure_packages()

PIL_AVAILABLE = False
HEIF_AVAILABLE = False
try:
    from PIL import Image
    PIL_AVAILABLE = True
    try:
        from pillow_heif import register_heif_opener
        register_heif_opener()
        HEIF_AVAILABLE = True
    except ImportError:
        pass
except ImportError:
    pass

# BILINEAR is several times faster than LANCZOS and indistinguishable once the
# result is scaled down again for the viewer.
RESAMPLE_FAST = 2
if PIL_AVAILABLE:
    _res = getattr(Image, 'Resampling', Image)
    RESAMPLE_FAST = getattr(_res, 'BILINEAR', 2)

try:
    from PySide6.QtWidgets import (
        QApplication, QMainWindow, QWidget, QTabWidget, QVBoxLayout, QHBoxLayout,
        QLabel, QLineEdit, QPushButton, QFileDialog, QTableWidget, QTableWidgetItem,
        QListWidget, QListWidgetItem, QSplitter, QAbstractItemView, QHeaderView,
        QScrollArea, QMessageBox, QStyleFactory, QSizePolicy, QMenu, QInputDialog,
        QRadioButton, QButtonGroup
    )
    from PySide6.QtGui import (QPalette, QColor, QImage, QPixmap, QShortcut, QKeySequence,
                               QPainter, QPen, QIcon)
    from PySide6.QtCore import QPointF, QObject
    from PySide6.QtWidgets import QCheckBox
    from PySide6.QtCore import Qt, QTimer, QEvent, QSize, Signal, QThread, QByteArray
except ImportError as e:
    log(f"❌ PySide6 introuvable: {e}")
    log("Relance le script (l'installation vient peut-être de finir), ou lance: pip install PySide6")
    try:
        input("Appuie sur Entrée pour quitter...")
    except EOFError:
        pass
    sys.exit(1)


# ==================== HELPERS ====================

def load_json(path, default):
    try:
        if os.path.exists(path):
            with open(path, 'r', encoding='utf-8') as f:
                return json.load(f)
    except Exception as e:
        log(f"❌ Error loading {os.path.basename(path)}: {e}")
    return default


def save_json(path, data):
    try:
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
    except Exception as e:
        log(f"❌ Error saving {os.path.basename(path)}: {e}")


def folder_color(name):
    """Stable dark pastel color for a folder name (readable with white text)"""
    hue = zlib.crc32(name.encode('utf-8')) % 360
    return QColor.fromHsl(hue, 90, 80)


# Date + time written in the filename, whatever the camera / app that produced it.
# The prefix (IMG_, VID_, PANO_, Screenshot_...) is deliberately ignored: only the
# timestamp matters, so photos and videos of the same moment sit next to each other.
DATETIME_PATTERNS = [
    # 20250108_181456   /  2025-01-08_18-14-56  /  2025-01-08 18.14.56
    r'(?<!\d)(20\d{2})[-_.]?(0[1-9]|1[0-2])[-_.]?(0[1-9]|[12]\d|3[01])'
    r'[-_ T]?(([01]\d|2[0-3]))[-_.:]?([0-5]\d)[-_.:]?([0-5]\d)(?!\d)',
    # Screenshot_2024-04-13-10-12-33-965
    r'(?<!\d)(20\d{2})-(0[1-9]|1[0-2])-(0[1-9]|[12]\d|3[01])'
    r'-([01]\d|2[0-3])-([0-5]\d)-([0-5]\d)(?!\d)',
]


def datetime_from_name(filename):
    """Timestamp encoded in the name, or None"""
    for pattern in DATETIME_PATTERNS:
        m = re.search(pattern, filename)
        if not m:
            continue
        g = m.groups()
        parts = [g[0], g[1], g[2], g[3], g[-2], g[-1]]
        try:
            return datetime(*(int(p) for p in parts))
        except (ValueError, TypeError):
            continue
    stem = os.path.splitext(filename)[0]
    m = re.match(r'^(\d{13}|\d{10})$', stem)      # epoch, in seconds or milliseconds
    if m:
        ts = int(m.group(1))
        if len(m.group(1)) == 13:
            ts /= 1000
        try:
            return datetime.fromtimestamp(ts)
        except (ValueError, OSError):
            pass
    return None


def file_datetime(filename, filepath):
    """Shooting date and time: the name first, the file's mtime as a fallback.
    Never returns None, so sorting by date is always meaningful."""
    dt = datetime_from_name(filename)
    if dt:
        return dt
    try:
        return datetime.fromtimestamp(os.path.getmtime(filepath))
    except Exception:
        return datetime.min


def get_year_from_file(filename, filepath):
    """Year from: filename date, epoch timestamp name, EXIF date taken, file mtime"""
    m = re.search(r'(20\d{2})[-_]?(0[1-9]|1[0-2])[-_]?(0[1-9]|[12]\d|3[01])', filename)
    if m:
        return m.group(1)
    m = re.search(r'(20\d{2})', filename)
    if m:
        return m.group(1)
    stem = os.path.splitext(filename)[0]
    m = re.match(r'^(\d{13}|\d{10})$', stem)
    if m:
        ts = int(m.group(1))
        if len(m.group(1)) == 13:
            ts /= 1000
        try:
            return str(datetime.fromtimestamp(ts).year)
        except (ValueError, OSError):
            pass
    ext = os.path.splitext(filename)[1].lower()
    if PIL_AVAILABLE and ext in IMAGE_EXTS:
        try:
            img = Image.open(filepath)
            exif = img.getexif()
            dt = None
            try:
                dt = exif.get_ifd(0x8769).get(36867)  # DateTimeOriginal
            except Exception:
                pass
            if not dt:
                dt = exif.get(306)  # DateTime
            img.close()
            if dt and re.match(r'^(19|20)\d{2}', str(dt)):
                return str(dt)[:4]
        except Exception:
            pass
    try:
        return str(datetime.fromtimestamp(os.path.getmtime(filepath)).year)
    except Exception:
        return None


# Android screenshots end with the package of the app: Screenshot_..._com.whatsapp.jpg
APP_NAMES = {
    'com.whatsapp': 'WhatsApp',
    'com.whatsapp.w4b': 'WhatsApp Business',
    'com.facebook.katana': 'Facebook',
    'com.facebook.orca': 'Messenger',
    'com.instagram.android': 'Instagram',
    'com.google.android.gm': 'Gmail',
    'com.google.android.youtube': 'YouTube',
    'com.google.android.apps.maps': 'Google Maps',
    'com.google.android.apps.photos': 'Google Photos',
    'com.google.android.calendar': 'Google Agenda',
    'com.google.android.googlequicksearchbox': 'Google',
    'com.android.vending': 'Play Store',
    'com.android.chrome': 'Chrome',
    'com.android.settings': 'Paramètres',
    'com.android.systemui': 'Système',
    'com.brave.browser': 'Brave',
    'org.mozilla.firefox': 'Firefox',
    'com.amazon.mShop.android.shopping': 'Amazon',
    'com.alibaba.aliexpresshd': 'AliExpress',
    'com.einnovation.temu': 'Temu',
    'fr.leboncoin': 'Leboncoin',
    'com.vinted': 'Vinted',
    'org.telegram.messenger': 'Telegram',
    'org.thoughtcrime.securesms': 'Signal',
    'com.discord': 'Discord',
    'com.reddit.frontpage': 'Reddit',
    'com.twitter.android': 'X',
    'com.zhiliaoapp.musically': 'TikTok',
    'com.linkedin.android': 'LinkedIn',
    'com.snapchat.android': 'Snapchat',
    'com.spotify.music': 'Spotify',
    'com.netflix.mediaclient': 'Netflix',
    'tv.twitch.android.app': 'Twitch',
    'deezer.android.app': 'Deezer',
    'com.microsoft.teams': 'Teams',
    'com.microsoft.office.outlook': 'Outlook',
    'com.waze': 'Waze',
    'com.booking': 'Booking',
    'com.airbnb.android': 'Airbnb',
    'com.ubercab': 'Uber',
    'com.paypal.android.p2pmobile': 'PayPal',
    'com.revolut.revolut': 'Revolut',
    'fr.doctolib.www': 'Doctolib',
    'com.vsct.vsc.mobile.horaireetresa.android': 'SNCF Connect',
    'com.duolingo': 'Duolingo',
    'com.strava': 'Strava',
    'com.valvesoftware.android.steam.community': 'Steam',
    'com.miui.gallery': 'Galerie',
    'com.miui.home': 'Écran d\'accueil',
    'com.android.camera': 'Appareil photo',
}

APP_NAMES_LOWER = {k.lower(): v for k, v in APP_NAMES.items()}

# Segments that say nothing about the app: keep looking to their left
GENERIC_SEGMENTS = {'android', 'app', 'apps', 'mobile', 'main', 'client', 'shopping',
                    'browser', 'messenger', 'music', 'video', 'free', 'pro', 'lite',
                    'release', 'prod', 'ui', 'go'}


def app_from_filename(filename):
    """Readable app name from an Android screenshot filename, or None.

    'Screenshot_2026-04-17-12-43-54-918_com.whatsapp.jpg' -> 'WhatsApp'
    'Screenshot_..._com.tutteo.flat.jpg'                  -> 'Flat'
    """
    stem = os.path.splitext(filename)[0]
    m = re.search(r'_((?:[A-Za-z][\w]*\.){1,6}[A-Za-z][\w]*)$', stem)
    if not m:
        return None
    package = m.group(1)
    known = APP_NAMES_LOWER.get(package.lower())
    if known:
        return known
    parts = [p for p in package.split('.') if p]
    if len(parts) < 2:
        return None
    # Drop the TLD-ish prefix (com, org, net, fr, io, app, we...)
    body = parts[1:] if len(parts) > 2 else parts[1:]
    for segment in reversed(body):
        if segment.lower() not in GENERIC_SEGMENTS and not segment.isdigit():
            return segment[:1].upper() + segment[1:]
    return body[-1][:1].upper() + body[-1][1:] if body else None


def safe_move(src, target_folder, dup_dir=None):
    """Move file to folder with collision handling.
    If an identical file (same name + same size) already exists at destination
    and dup_dir is given, src goes to dup_dir instead (never duplicated with _1/_2)."""
    # A file already in the target folder has nothing to do: without this guard it
    # would collide with ITSELF and be sent to dup_dir.
    if os.path.normcase(os.path.abspath(os.path.dirname(src))) == \
            os.path.normcase(os.path.abspath(target_folder)):
        return src
    os.makedirs(target_folder, exist_ok=True)
    filename = os.path.basename(src)
    dest = os.path.join(target_folder, filename)
    if os.path.exists(dest) and dup_dir:
        try:
            if os.path.getsize(src) == os.path.getsize(dest):
                return safe_move(src, dup_dir)
        except OSError:
            pass
    counter = 1
    while os.path.exists(dest):
        name, ext = os.path.splitext(filename)
        dest = os.path.join(target_folder, f"{name}_{counter}{ext}")
        counter += 1
    shutil.move(src, dest)
    return dest


def merge_folders(src, dst, dup_dir):
    """Merge src folder into dst (collision-safe).
    Same-name same-size files go to dup_dir (never deleted).
    Emptied source (sub)folders are removed. Returns (moved, dups, errors)."""
    if os.path.normcase(os.path.abspath(src)) == os.path.normcase(os.path.abspath(dst)):
        # Windows: same folder with different case -> NEVER merge into itself
        log(f"⚠️ Merge refusé (même dossier, casse différente): {src}")
        return 0, 0, 1
    moved = dups = errors = 0
    os.makedirs(dst, exist_ok=True)
    for entry in os.listdir(src):
        s = os.path.join(src, entry)
        d = os.path.join(dst, entry)
        try:
            if os.path.isdir(s):
                if os.path.exists(d):
                    m, du, e = merge_folders(s, d, dup_dir)
                    moved += m
                    dups += du
                    errors += e
                else:
                    shutil.move(s, d)
                    moved += 1
            elif os.path.exists(d) and os.path.getsize(s) == os.path.getsize(d):
                safe_move(s, dup_dir)
                dups += 1
            else:
                safe_move(s, dst)
                moved += 1
        except Exception as e:
            log(f"❌ Merge error {entry}: {e}")
            errors += 1
    try:
        if not os.listdir(src):
            os.rmdir(src)
    except Exception:
        pass
    return moved, dups, errors


def pil_to_qimage(img):
    """PIL -> QImage. Safe to call from a worker thread (QPixmap is not)."""
    img = img.convert('RGBA')
    data = img.tobytes('raw', 'RGBA')
    qimg = QImage(data, img.width, img.height, img.width * 4, QImage.Format.Format_RGBA8888)
    return qimg.copy()          # detach from the Python buffer


def pil_to_pixmap(img):
    return QPixmap.fromImage(pil_to_qimage(img))


# Longest side we decode previews at: far cheaper than a 50 Mpx original and
# still sharper than any screen once zoomed a bit.
PREVIEW_MAX = 1800
PREVIEW_CACHE_MAX = 8       # decoded images kept in RAM (current + neighbours)
THUMB_MAX = 240             # grid thumbnails in the viewer tab
THUMB_W, THUMB_H = 200, 150  # every cell gets exactly this, so the grid lines up
THUMB_WORKERS = 4
THUMB_CACHE_MAX = 800        # framed thumbnails kept in RAM


def load_preview_qimage(path, max_side=PREVIEW_MAX):
    """Decode an image for display, downscaled during decoding.
    JPEG draft mode lets libjpeg skip most of the work, which is what makes
    stepping through a folder feel instant instead of chugging."""
    if not PIL_AVAILABLE:
        return None
    try:
        img = Image.open(path)
        try:
            img.draft('RGB', (max_side, max_side))         # no-op for non-JPEG
        except Exception:
            pass
        img.thumbnail((max_side, max_side), RESAMPLE_FAST)
        qimg = pil_to_qimage(img)
        img.close()
        return qimg
    except Exception as e:
        log(f"❌ Preview {os.path.basename(path)}: {e}")
        return None


def propose_folder_name(year, folder):
    """Return (proposed_name, status). status: 'ok' | 'auto' | 'manual' | 'move'"""
    m = re.match(r'^(20\d{2})', folder)
    if m and m.group(1) != year:
        # Correctly named but sitting in the wrong year folder -> propose moving it
        return folder, 'move'
    if folder.startswith(year):
        return '', 'ok'
    other_years = [y for y in re.findall(r'20\d{2}', folder) if y != year]
    if other_years:
        return '', 'manual'

    m = re.match(r'^(\d{1,2})[\s\-]+(\d{1,2})\s+(.+)$', folder)
    if m and 1 <= int(m.group(1)) <= 12 and 1 <= int(m.group(2)) <= 31:
        new_name = f"{year}-{int(m.group(1)):02d}-{int(m.group(2)):02d} {m.group(3)}"
    else:
        m = re.match(r'^(\d{1,2})\s*-\s*(.+)$', folder)
        if m and 1 <= int(m.group(1)) <= 12:
            new_name = f"{year}-{int(m.group(1)):02d} {m.group(2)}"
        else:
            new_name = f"{year}-{folder}"

    new_name = new_name[:7] + new_name[7:].replace(year, '')
    new_name = re.sub(r'\s{2,}', ' ', new_name).strip().rstrip('-').strip()
    return new_name, 'auto'


def count_files(path):
    """Recursive file count"""
    total = 0
    try:
        for _, _, files in os.walk(path):
            total += len(files)
    except Exception:
        pass
    return total


STOP_WORDS = ('janvier', 'fevrier', 'février', 'mars', 'avril', 'mai', 'juin', 'juillet',
              'aout', 'août', 'septembre', 'octobre', 'novembre', 'decembre', 'décembre',
              'le', 'la', 'les', 'de', 'du', 'des', 'et')


def name_similarity(a, b):
    """Similarity of folder names ignoring digits/punctuation/filler words (0..1)"""
    def norm(s):
        s = s.lower()
        for w in STOP_WORDS:
            s = re.sub(rf'\b{w}\b', '', s)
        return re.sub(r'[^a-z]', '', s)
    na, nb = norm(a), norm(b)
    if not na or not nb:
        return 0.0
    return difflib.SequenceMatcher(None, na, nb).ratio()


def load_folder_exclusions():
    """Pairs of folder names never to flag as duplicates (one 'nameA <> nameB' per line)"""
    pairs = set()
    try:
        if os.path.exists(EXCLUSION_FILE):
            with open(EXCLUSION_FILE, 'r', encoding='utf-8') as f:
                for line in f:
                    parts = [p.strip() for p in line.split('<>')]
                    if len(parts) == 2 and all(parts):
                        pairs.add(tuple(sorted(parts)))
    except Exception as e:
        log(f"❌ Error loading {os.path.basename(EXCLUSION_FILE)}: {e}")
    return pairs


def save_folder_exclusion(a, b):
    try:
        with open(EXCLUSION_FILE, 'a', encoding='utf-8') as f:
            f.write(f"{a} <> {b}\n")
    except Exception as e:
        log(f"❌ Error saving exclusion: {e}")


def month_of(name, year):
    """Month in 'YEAR-MM...' name, else None"""
    m = re.match(rf'^{year}-(\d{{2}})', name)
    return m.group(1) if m else None


# Row colors (dark theme)
COLOR_AUTO = QColor('#1f4d2e')
COLOR_MANUAL = QColor('#4d3d1f')
COLOR_DONE = QColor('#1f334d')
COLOR_CONFLICT = QColor('#4d1f1f')
COLOR_OK_FG = QColor('#888888')

# Diff highlighting for the duplicate captions
DIFF_STYLE = "background-color:#8a5a00; color:#ffe08a; font-weight:bold; padding:0 2px;"
SAME_STYLE = "color:#8a8a8a;"


def _esc(s):
    return s.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')


def _dim(s):
    return f'<span style="{SAME_STYLE}">{_esc(s)}</span>' if s else ''


def _hot(s):
    return f'<span style="{DIFF_STYLE}">{_esc(s)}</span>' if s else ''


def _char_diff(a, b):
    """Character-level diff of two strings -> (html_a, html_b).
    Only the characters that actually differ are highlighted, so 'photo_1.jpg'
    vs 'photo.jpg' lights up the '_1' and nothing else. When the two strings are
    too far apart (two unrelated folder names), highlighting a few shared letters
    would just produce confetti, so the whole segment is highlighted instead."""
    ops = difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes()
    changed = sum((i2 - i1) + (j2 - j1) for tag, i1, i2, j1, j2 in ops if tag != 'equal')
    if changed > max(6, 0.3 * max(len(a), len(b))):
        return _hot(a), _hot(b)
    out_a, out_b = [], []
    for tag, i1, i2, j1, j2 in ops:
        if tag == 'equal':
            out_a.append(_dim(a[i1:i2]))
            out_b.append(_dim(b[j1:j2]))
        else:
            out_a.append(_hot(a[i1:i2]))
            out_b.append(_hot(b[j1:j2]))
    return ''.join(out_a), ''.join(out_b)


def diff_path_html(rel_a, rel_b):
    """Compare two relative paths and return (html_a, html_b) with only the
    differences highlighted: whole segments when a folder is replaced, and
    down to the character when two segments merely differ (a '_1' suffix, a
    changed digit...). Everything identical stays dimmed."""
    parts_a = re.split(r'[\\/]', rel_a)
    parts_b = re.split(r'[\\/]', rel_b)
    out_a, out_b = [], []
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, parts_a, parts_b).get_opcodes():
        if tag == 'equal':
            out_a.extend(_dim(p) for p in parts_a[i1:i2])
            out_b.extend(_dim(p) for p in parts_b[j1:j2])
        elif tag == 'replace' and (i2 - i1) == (j2 - j1):
            # Same number of segments on both sides: compare them pairwise, char by char
            for pa, pb in zip(parts_a[i1:i2], parts_b[j1:j2]):
                ha, hb = _char_diff(pa, pb)
                out_a.append(ha)
                out_b.append(hb)
        else:
            out_a.extend(_hot(p) for p in parts_a[i1:i2])
            out_b.extend(_hot(p) for p in parts_b[j1:j2])
    sep = f'<span style="{SAME_STYLE}">\\</span>'
    return sep.join(out_a), sep.join(out_b)


# Markers Windows / phones / sync tools append when they duplicate a file:
#   photo_1.jpg   photo (1).jpg   photo - Copie.jpg   photo copy 2.jpg   photo~1.jpg
COPY_SUFFIX_RE = re.compile(
    r'^(?P<base>.+?)'
    r'(?:'
    r'[ _\-~]?\((?P<paren>\d{1,3})\)'                      # (1)  _(1)  -(1)
    r'|[ _\-~](?P<num>\d{1,3})'                            # _1   -1   ~1   " 1"
    r'|[ _\-]?(?:copie|copy|kopie|copia)(?:[ _\-]?\d{1,3})?'   # - Copie, _copy, copy 2
    r')$',
    re.IGNORECASE)


def copy_original_name(filename):
    """If filename looks like a copy of another file ('x_1.jpg' -> 'x.jpg'),
    return the original name, else None. Used to auto-flag same-folder copies."""
    stem, ext = os.path.splitext(filename)
    if not ext:
        return None
    m = COPY_SUFFIX_RE.match(stem)
    if not m:
        return None
    base = m.group('base').rstrip(' _-~')
    if not base:
        return None
    return base + ext


# ==================== VIDEO PREVIEW ====================

# Frames sampled for the video slideshow, as a fraction of the total duration
VIDEO_SAMPLE_POINTS = (0.10, 0.30, 0.50, 0.70, 0.90)
VIDEO_SLIDE_MS = 900
VIDEO_CACHE_MAX = 12

NO_WINDOW = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0


# Local ffmpeg install. Override with "ffmpeg_dir" in the config file.
DEFAULT_FFMPEG_DIR = r"P:\a-PC\a-Prg\Video\ffmpeg"

FFMPEG = FFPROBE = None
FFMPEG_TRIED = []


def _exe_in(folder, name):
    """Look for name(.exe) in folder, folder/bin, folder/*/bin (unpacked release layout)"""
    if not folder or not os.path.isdir(folder):
        return None
    exe = name + ('.exe' if os.name == 'nt' else '')
    candidates = [os.path.join(folder, exe), os.path.join(folder, 'bin', exe)]
    try:
        for sub in os.listdir(folder):
            sub_path = os.path.join(folder, sub)
            if os.path.isdir(sub_path):
                candidates.append(os.path.join(sub_path, exe))
                candidates.append(os.path.join(sub_path, 'bin', exe))
    except OSError:
        pass
    for c in candidates:
        FFMPEG_TRIED.append(c)
        if os.path.isfile(c):
            return c
    return None


def resolve_ffmpeg(extra_dir=None):
    """Locate ffmpeg/ffprobe and set the globals. Search order:
    configured folder -> script folder -> PATH -> imageio-ffmpeg wheel."""
    global FFMPEG, FFPROBE, FFMPEG_TRIED
    FFMPEG_TRIED = []
    ffmpeg = ffprobe = None
    here = os.path.dirname(os.path.abspath(__file__))
    for folder in (extra_dir, DEFAULT_FFMPEG_DIR, here):
        ffmpeg = ffmpeg or _exe_in(folder, 'ffmpeg')
        ffprobe = ffprobe or _exe_in(folder, 'ffprobe')
        if ffmpeg and ffprobe:
            break
    ffmpeg = ffmpeg or shutil.which('ffmpeg')
    ffprobe = ffprobe or shutil.which('ffprobe')
    if not ffmpeg:
        try:
            import imageio_ffmpeg
            ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
        except Exception:
            pass
    FFMPEG, FFPROBE = ffmpeg, ffprobe
    return ffmpeg, ffprobe


resolve_ffmpeg()


def video_duration(path):
    """Duration in seconds, via ffprobe or by parsing ffmpeg's banner. None if unknown."""
    if FFPROBE:
        try:
            r = subprocess.run([FFPROBE, '-v', 'error', '-show_entries', 'format=duration',
                                '-of', 'default=noprint_wrappers=1:nokey=1', path],
                               capture_output=True, text=True, timeout=15,
                               creationflags=NO_WINDOW)
            return float(r.stdout.strip())
        except Exception:
            pass
    if FFMPEG:
        try:
            r = subprocess.run([FFMPEG, '-i', path], capture_output=True, text=True,
                               timeout=15, creationflags=NO_WINDOW)
            m = re.search(r'Duration:\s*(\d+):(\d\d):(\d\d\.\d+)', r.stderr or '')
            if m:
                return int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3))
        except Exception:
            pass
    return None


def extract_video_jpgs(path, temp_dir, duration=None):
    """Sample the video into jpgs in temp_dir. Returns [(percent, jpg_path), ...].
    Pure file/subprocess work - no Qt - so a background thread can call it.
    Frames already on disk are reused, so the UI and the background pass share them."""
    if not FFMPEG:
        return []
    if duration is None:
        duration = video_duration(path)
    if not duration or duration <= 0:
        return []
    try:
        os.makedirs(temp_dir, exist_ok=True)
    except Exception:
        return []
    key = f"{zlib.crc32(path.encode('utf-8')):08x}"
    shots = []
    for point in VIDEO_SAMPLE_POINTS:
        pct = int(point * 100)
        out = os.path.join(temp_dir, f"slide_{key}_{pct:02d}.jpg")
        if not os.path.exists(out):
            try:
                subprocess.run([FFMPEG, '-ss', f"{duration * point:.3f}", '-i', path,
                                '-frames:v', '1', '-q:v', '3', '-y', out],
                               capture_output=True, timeout=25, creationflags=NO_WINDOW)
            except Exception:
                continue
        if os.path.exists(out):
            shots.append((pct, out))
    return shots


DEFAULT_SHOT_PCT = 25       # the only frame extracted up front; the others on demand


def shot_path(video_path, cache_dir, pct):
    """Where the screenshot at this percentage lives (existing or not)"""
    if not cache_dir:
        return None
    key = f"{zlib.crc32(video_path.encode('utf-8')):08x}"
    return os.path.join(cache_dir, f"{key}_{pct:03d}.jpg")


def grab_one_shot(video_path, cache_dir, pct, duration=None):
    """Extract a single frame: one ffmpeg call. No Qt, so a worker can call it."""
    out = shot_path(video_path, cache_dir, pct)
    if not FFMPEG or not out:
        return None
    if os.path.exists(out):
        return out
    if duration is None:
        duration = video_duration(video_path)
    if not duration or duration <= 0:
        return None
    try:
        os.makedirs(cache_dir, exist_ok=True)
        ts = max(0, duration - 0.5) if pct >= 100 else (duration * pct) / 100
        subprocess.run([FFMPEG, '-ss', str(ts), '-i', video_path, '-frames:v', '1',
                        '-q:v', '2', '-y', out],
                       capture_output=True, timeout=20, creationflags=NO_WINDOW)
    except Exception:
        return None
    return out if os.path.exists(out) else None


class PreviewLoader(QThread):
    """Single worker that decodes previews off the GUI thread.
    Newest request first: when you hold the arrow key down, the photo you
    stopped on is decoded before the ones you flew past."""
    image_ready = Signal(str, object)      # path, QImage
    shot_ready = Signal(str, int, object)  # video path, percent, jpg path
    thumb_ready = Signal(str, object)      # media path, small QImage

    def __init__(self, parent=None):
        super().__init__(parent)
        self._jobs = []                   # used as a stack
        self._lock = threading.Lock()
        self._wake = threading.Event()
        self._stop = False
        self._seen = set()

    def request(self, kind, path, extra=None):
        key = (kind, path, extra)      # same video at 50 % is a different job
        with self._lock:
            if key in self._seen:
                return
            self._seen.add(key)
            self._jobs.append((kind, path, extra))
        self._wake.set()

    def clear_pending(self):
        """Drop everything not started yet (the user moved on)"""
        with self._lock:
            self._jobs.clear()
            self._seen.clear()

    def stop(self):
        self._stop = True
        self._wake.set()

    def run(self):
        while not self._stop:
            with self._lock:
                job = self._jobs.pop() if self._jobs else None
            if job is None:
                self._wake.wait(0.15)
                self._wake.clear()
                continue
            kind, path, extra = job
            try:
                if kind == 'image':
                    img = load_preview_qimage(path)
                    if img is not None and not self._stop:
                        self.image_ready.emit(path, img)
                elif kind == 'shot':
                    cache_dir, pct = extra
                    jpg = grab_one_shot(path, cache_dir, pct)
                    if not self._stop:
                        self.shot_ready.emit(path, pct, jpg)
                elif kind == 'thumb':
                    source = path
                    if os.path.splitext(path)[1].lower() in VIDEO_EXTS:
                        source = grab_one_shot(path, extra, DEFAULT_SHOT_PCT)
                    img = load_preview_qimage(source, THUMB_MAX) if source else None
                    if not self._stop:
                        self.thumb_ready.emit(path, img)
            except Exception as e:
                log(f"❌ Preview worker {os.path.basename(path)}: {e}")
            finally:
                with self._lock:
                    self._seen.discard((kind, path, extra))


class PrefetchWorker(QThread):
    """Warms ONE frame per video - the 25 % one shown on selection. Extracting
    all eleven up front cost far more than it saved."""
    advanced = Signal(int, int)

    def __init__(self, videos, cache_dir, pct=DEFAULT_SHOT_PCT, parent=None):
        super().__init__(parent)
        self.videos = videos
        self.cache_dir = cache_dir
        self.pct = pct
        self._stop = False

    def stop(self):
        self._stop = True

    def run(self):
        for i, path in enumerate(self.videos):
            if self._stop:
                return
            try:
                grab_one_shot(path, self.cache_dir, self.pct)
            except Exception:
                pass
            self.advanced.emit(i + 1, len(self.videos))


def setup_header(table, widths, sortable=True):
    """Columns the user can widen, reorder and sort. Qt keeps logical indices
    stable when a column is dragged, so the code below can stay index-based."""
    h = table.horizontalHeader()
    h.setSectionsMovable(True)
    h.setSectionsClickable(True)
    h.setStretchLastSection(False)
    h.setMinimumSectionSize(40)
    for i, w in enumerate(widths):
        h.setSectionResizeMode(i, QHeaderView.ResizeMode.Interactive)
        table.setColumnWidth(i, w)
    h.setDefaultAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
    if sortable:
        table.setSortingEnabled(True)
        h.setSortIndicatorShown(True)


class SortableItem(QTableWidgetItem):
    """Table cell that sorts on a key instead of its label, so '🟢 100 %'
    and '🔴 45 %' order by score and not by emoji."""

    def __init__(self, text, key=None):
        super().__init__(text)
        self.sort_key = key

    def __lt__(self, other):
        mine = self.sort_key
        theirs = getattr(other, 'sort_key', None)
        if mine is None or theirs is None:
            return self.text() < other.text()
        try:
            return mine < theirs
        except TypeError:
            return str(mine) < str(theirs)


class ThumbPool(QObject):
    """Several worker threads pulling from one queue: thumbnails appear almost
    at once instead of trickling in from a single decoder."""
    ready = Signal(str, object)      # media path, QImage

    def __init__(self, cache_dir_getter, workers=THUMB_WORKERS, parent=None):
        super().__init__(parent)
        self._queue = deque()
        self._lock = threading.Lock()
        self._wake = threading.Event()
        self._stop = False
        self._generation = 0
        self._cache_dir_getter = cache_dir_getter
        # QThread rather than threading.Thread: signals emitted from a QThread are
        # queued to the GUI thread by Qt itself, which is the supported path.
        self._threads = [_PoolThread(self) for _ in range(max(1, workers))]
        for t in self._threads:
            t.start()

    def submit(self, paths):
        """Replace the queue: switching folder must not wait for the previous one"""
        with self._lock:
            self._generation += 1
            gen = self._generation
            self._queue.clear()
            self._queue.extend((gen, p) for p in paths)
        self._wake.set()

    def stop(self):
        self._stop = True
        self._wake.set()
        for t in self._threads:
            t.wait(1500)

    def _run(self):
        while not self._stop:
            with self._lock:
                job = self._queue.popleft() if self._queue else None
                current = self._generation
            if job is None:
                self._wake.wait(0.1)
                self._wake.clear()
                continue
            gen, path = job
            if gen != current:
                continue            # belongs to a folder you already left
            try:
                source = path
                if os.path.splitext(path)[1].lower() in VIDEO_EXTS:
                    source = grab_one_shot(path, self._cache_dir_getter(), DEFAULT_SHOT_PCT)
                img = load_preview_qimage(source, THUMB_MAX) if source else None
                if img is not None and not self._stop and gen == self._generation:
                    self.ready.emit(path, img)
            except Exception as e:
                log(f"❌ Vignette {os.path.basename(path)}: {e}")


class _PoolThread(QThread):
    def __init__(self, pool):
        super().__init__(pool)
        self.pool = pool

    def run(self):
        self.pool._run()


def month_floor(dt):
    return dt.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def add_months(dt, n):
    month = dt.month - 1 + n
    return dt.replace(year=dt.year + month // 12, month=month % 12 + 1)


def timeline_ticks(lo, hi):
    """Graduations matching the span: hours, days, months or years"""
    span = (hi - lo).total_seconds()
    ticks = []
    day = 86400
    if span <= 2 * day:
        step = 3600 * (1 if span <= 6 * 3600 else 3 if span <= 12 * 3600 else 6)
        t = lo.replace(minute=0, second=0, microsecond=0)
        while t <= hi:
            if t >= lo:
                ticks.append((t, t.strftime('%Hh')))
            t += timedelta(seconds=step)
    elif span <= 45 * day:
        step_days = 1 if span <= 10 * day else 7
        t = lo.replace(hour=0, minute=0, second=0, microsecond=0)
        while t <= hi:
            if t >= lo:
                ticks.append((t, t.strftime('%d/%m')))
            t += timedelta(days=step_days)
    elif span <= 800 * day:
        step_months = 1 if span <= 400 * day else 3      # a full year -> 12 months
        t = month_floor(lo)
        while t <= hi:
            if t >= lo:
                ticks.append((t, t.strftime('%b %y')))
            t = add_months(t, step_months)
    else:
        years = max(1, round(span / (365 * day) / 8))
        t = lo.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
        while t <= hi:
            if t >= lo:
                ticks.append((t, t.strftime('%Y')))
            t = t.replace(year=t.year + years)
    return ticks


class Timeline(QWidget):
    """One dot per media, placed on a time axis running from the oldest to the
    newest of the folder. Clicking a dot selects the corresponding thumbnail."""
    picked = Signal(int)

    MARGIN = 52
    HEIGHT = 92

    def __init__(self, parent=None):
        super().__init__(parent)
        self.points = []          # [(datetime, label), ...] in display order
        self.selected = -1
        self.year_mode = False    # False = fit the folder, True = 01/01 -> 31/12
        self.year = None
        self.setFixedHeight(self.HEIGHT)
        self.setMouseTracking(True)
        self.setToolTip("")

    def set_points(self, points, year=None):
        self.points = points
        self.selected = -1
        if year:
            self.year = year
        self.update()

    def set_year_mode(self, enabled, year=None):
        self.year_mode = bool(enabled)
        if year:
            self.year = year
        self.update()

    def set_selected(self, index):
        self.selected = index
        self.update()

    def _span(self):
        dates = [d for d, _ in self.points if d]
        if not dates:
            return None, None
        if self.year_mode:
            year = None
            try:
                year = int(self.year)
            except (TypeError, ValueError):
                year = max(dates).year
            return (datetime(year, 1, 1, 0, 0, 0),
                    datetime(year, 12, 31, 23, 59, 59))
        return min(dates), max(dates)

    def _x_for(self, dt, lo, hi):
        usable = max(1, self.width() - 2 * self.MARGIN)
        if hi == lo:
            return self.MARGIN + usable / 2
        return self.MARGIN + usable * ((dt - lo).total_seconds() / (hi - lo).total_seconds())

    def _index_at(self, x, y):
        lo, hi = self._span()
        if lo is None or abs(y - self.HEIGHT // 2) > 18:
            return -1
        best, best_dist = -1, 12
        for i, (dt, _label) in enumerate(self.points):
            if not dt:
                continue
            d = abs(self._x_for(dt, lo, hi) - x)
            if d < best_dist:
                best, best_dist = i, d
        return best

    def mousePressEvent(self, event):
        i = self._index_at(event.position().x(), event.position().y())
        if i >= 0:
            self.picked.emit(i)

    def mouseMoveEvent(self, event):
        i = self._index_at(event.position().x(), event.position().y())
        if i >= 0:
            dt, label = self.points[i]
            self.setToolTip(f"{label}\n{dt.strftime('%d/%m/%Y %H:%M:%S')}")
        else:
            self.setToolTip("")

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        mid = self.HEIGHT // 2
        lo, hi = self._span()
        painter.setPen(QPen(QColor('#4a4b50'), 2))
        painter.drawLine(self.MARGIN, mid, self.width() - self.MARGIN, mid)
        if lo is None:
            painter.setPen(QColor('#8a8a8a'))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter,
                             "Aucune date exploitable")
            return
        # Graduations
        font = painter.font()
        font.setPointSize(7)
        painter.setFont(font)
        for tick, label in timeline_ticks(lo, hi):
            x = self._x_for(tick, lo, hi)
            painter.setPen(QPen(QColor('#3a3b40'), 1))
            painter.drawLine(QPointF(x, mid - 8), QPointF(x, mid + 8))
            painter.setPen(QColor('#7c7e85'))
            width = painter.fontMetrics().horizontalAdvance(label)
            painter.drawText(QPointF(x - width / 2, mid - 13), label)
        # Dots
        for i, (dt, _label) in enumerate(self.points):
            if not dt:
                continue
            x = self._x_for(dt, lo, hi)
            if i == self.selected:
                painter.setBrush(QColor('#ffd479'))
                painter.setPen(QPen(QColor('#ffffff'), 1))
                painter.drawEllipse(QPointF(x, mid), 6.5, 6.5)
            else:
                painter.setBrush(QColor(120, 180, 255, 190))
                painter.setPen(Qt.PenStyle.NoPen)
                painter.drawEllipse(QPointF(x, mid), 3.6, 3.6)
        # Bounds
        painter.setPen(QColor('#b9bbc0'))
        font.setPointSize(8)
        painter.setFont(font)
        span_days = max(0, (hi - lo).days)
        fmt = '%d/%m/%Y' if span_days else '%d/%m/%Y %H:%M'
        painter.drawText(4, mid + 26, lo.strftime(fmt))
        right = hi.strftime(fmt)
        painter.drawText(self.width() - painter.fontMetrics().horizontalAdvance(right) - 4,
                         mid + 26, right)
        dates = [d for d, _ in self.points if d]
        title = f"{len(dates)} média(s)"
        if self.year_mode:
            title += f" — vue année {lo.year}"
        elif dates:
            real = max(dates) - min(dates)
            title += (f" — {real.days} jour(s)" if real.days
                      else f" — {real.seconds // 60} min")
        painter.setPen(QColor('#8a8a8a'))
        painter.drawText(self.rect().adjusted(0, 2, 0, 0),
                         Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop, title)


class ClickableLabel(QLabel):
    """QLabel that reports double-clicks, so the preview opens the actual file"""
    doubleClicked = Signal()

    def mouseDoubleClickEvent(self, event):
        self.doubleClicked.emit()
        super().mouseDoubleClickEvent(event)


# ==================== PERCEPTUAL COMPARISON ====================

HASH_SIZE = 8            # dHash grid -> 64 bits
SIM_IDENTICAL = 0.97     # visually the same shot
SIM_CLOSE = 0.88         # same scene, re-encoded / cropped a bit
SIM_RELATED = 0.72       # clearly related but not the same image

RESAMPLE = 1
if PIL_AVAILABLE:
    RESAMPLE = getattr(getattr(Image, 'Resampling', Image), 'LANCZOS', 1)


def dhash(img):
    """Difference hash: 64 bits describing the image's gradients.
    Robust to re-encoding and resizing, sensitive to a different shot."""
    small = img.convert('L').resize((HASH_SIZE + 1, HASH_SIZE), RESAMPLE)
    px = small.tobytes()   # mode 'L' -> one byte per pixel, row by row
    bits = 0
    for r in range(HASH_SIZE):
        row = px[r * (HASH_SIZE + 1):(r + 1) * (HASH_SIZE + 1)]
        for c in range(HASH_SIZE):
            bits = (bits << 1) | (1 if row[c] < row[c + 1] else 0)
    return bits


def hash_similarity(h1, h2):
    """1.0 = identical hashes, 0.0 = every bit differs"""
    return 1.0 - (bin(h1 ^ h2).count('1') / (HASH_SIZE * HASH_SIZE))


def hash_file(path):
    """dHash of a still image, or None"""
    if not PIL_AVAILABLE:
        return None
    try:
        with Image.open(path) as img:
            return dhash(img)
    except Exception as e:
        log(f"❌ Hash {os.path.basename(path)}: {e}")
        return None


def human_size(n):
    if n is None:
        return "?"
    return f"{n / 1024:,.0f} Ko" if n < 1024 * 1024 else f"{n / 1048576:,.1f} Mo"


def human_time(s):
    if s is None:
        return "?"
    return f"{int(s // 60)}:{int(s % 60):02d}" if s >= 60 else f"{s:.1f} s"


def fingerprint(path, temp_dir):
    """Everything we need to judge a file: size, duration (videos), visual hashes.
    No Qt inside - safe to call from a worker thread."""
    fp = {'path': path, 'size': None, 'duration': None, 'hashes': [], 'kind': 'other'}
    try:
        fp['size'] = os.path.getsize(path)
    except OSError:
        return fp
    ext = os.path.splitext(path)[1].lower()
    if ext in VIDEO_EXTS:
        fp['kind'] = 'video'
        fp['duration'] = video_duration(path)
        for _pct, jpg in extract_video_jpgs(path, temp_dir, fp['duration']):
            h = hash_file(jpg)
            if h is not None:
                fp['hashes'].append(h)
    elif ext in IMAGE_EXTS:
        fp['kind'] = 'image'
        h = hash_file(path)
        if h is not None:
            fp['hashes'].append(h)
    return fp


def compare_fingerprints(fa, fb, identical_bytes=False):
    """Three tests - size, displayed content, duration for videos - merged into
    one result dict. 'content' stays the headline: two files can weigh the same
    and show something else entirely."""
    res = {'size_a': fa['size'], 'size_b': fb['size'],
           'dur_a': fa['duration'], 'dur_b': fb['duration'],
           'content': None, 'size_ratio': None, 'dur_ratio': None,
           'identical': identical_bytes, 'kind': fa['kind']}
    if identical_bytes:
        res['content'] = 1.0
        res['size_ratio'] = 1.0
        res['dur_ratio'] = 1.0
        return res
    if fa['size'] and fb['size']:
        res['size_ratio'] = min(fa['size'], fb['size']) / max(fa['size'], fb['size'])
    if fa['duration'] and fb['duration']:
        res['dur_ratio'] = min(fa['duration'], fb['duration']) / max(fa['duration'], fb['duration'])
    ha, hb = fa['hashes'], fb['hashes']
    if ha and hb:
        pairs = min(len(ha), len(hb))
        res['content'] = sum(hash_similarity(ha[i], hb[i]) for i in range(pairs)) / pairs
    return res


def verdict_for(res):
    """(emoji, short label, long label, css color) from a comparison result"""
    if not res or res.get('content') is None:
        return "❔", "?", "Comparaison impossible (fichier illisible)", "#8a8a8a"
    score = res['content']
    pct = f"{score * 100:.0f} %"
    dur_off = res['dur_ratio'] is not None and res['dur_ratio'] < 0.98
    if res.get('identical'):
        return "🟢", "100 %", "Fichiers identiques octet pour octet — doublon certain", "#4ade80"
    if dur_off and score >= SIM_CLOSE:
        # Same imagery but one is longer: a trimmed or extended version, not a copy
        return ("🟠", pct,
                f"Images proches ({pct}) mais durées différentes "
                f"({human_time(res['dur_a'])} vs {human_time(res['dur_b'])}) — versions distinctes",
                "#fb923c")
    if score >= SIM_IDENTICAL:
        return "🟢", pct, f"Contenu identique ({pct}) — doublon confirmé", "#4ade80"
    if score >= SIM_CLOSE:
        return "🟡", pct, f"Très proche ({pct}) — même prise, encodage ou recadrage différent", "#fbbf24"
    if score >= SIM_RELATED:
        return "🟠", pct, f"Lié mais différent ({pct}) — à vérifier à l'œil", "#fb923c"
    return "🔴", pct, f"Contenu différent ({pct}) — ce n'est pas un doublon", "#f87171"


def verdict_details(res):
    """One line summarising the three tests, for the tooltip and the verdict bar"""
    if not res:
        return ""
    bits = []
    sa, sb = res.get('size_a'), res.get('size_b')
    if sa == sb and sa is not None:
        bits.append(f"⚖️ taille identique ({human_size(sa)})")
    else:
        bits.append(f"⚖️ taille {human_size(sa)} vs {human_size(sb)}")
    da, db = res.get('dur_a'), res.get('dur_b')
    if da or db:
        if da and db and abs(da - db) < 0.05:
            bits.append(f"⏱️ durée identique ({human_time(da)})")
        else:
            bits.append(f"⏱️ durée {human_time(da)} vs {human_time(db)}")
    c = res.get('content')
    bits.append(f"🖼️ contenu {c * 100:.0f} %" if c is not None else "🖼️ contenu illisible")
    return "   |   ".join(bits)


class CompareWorker(QThread):
    """Scores every pair in the background so the table fills up on its own.
    Only does file IO, ffmpeg and PIL work - never touches Qt widgets."""
    scored = Signal(int, dict)      # row token, result
    progressed = Signal(int, int)   # done, total

    def __init__(self, jobs, temp_dir, parent=None):
        super().__init__(parent)
        self.jobs = jobs            # [(token, path_a, path_b), ...]
        self.temp_dir = temp_dir
        self._stop = False

    def stop(self):
        self._stop = True

    def run(self):
        cache = {}
        for i, (token, pa, pb) in enumerate(self.jobs):
            if self._stop:
                return
            try:
                identical = False
                if os.path.isfile(pa) and os.path.isfile(pb):
                    try:
                        identical = (os.path.getsize(pa) == os.path.getsize(pb)
                                     and filecmp.cmp(pa, pb, shallow=False))
                    except OSError:
                        identical = False
                for p in (pa, pb):
                    if p not in cache:
                        cache[p] = fingerprint(p, self.temp_dir)
                res = compare_fingerprints(cache[pa], cache[pb], identical)
            except Exception as e:
                res = {'content': None, 'error': str(e)}
            self.scored.emit(token, res)
            self.progressed.emit(i + 1, len(self.jobs))


# ==================== MAIN WINDOW ====================

class TriPhotoWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("TriPhoto - Smart Photo Organizer")
        self.resize(1500, 850)

        # Config / state
        self.config = load_json(CONFIG_FILE, {"camera_path": DEFAULT_CAMERA_PATH})
        self.base_path = os.path.normpath(self.config.get("camera_path", DEFAULT_CAMERA_PATH))
        self.ignore_list = set(load_json(IGNORE_FILE, []))
        # ffmpeg: config folder wins, else the default install, else PATH
        self.ffmpeg_dir = self.config.get('ffmpeg_dir', DEFAULT_FFMPEG_DIR)
        changed = False
        if self.config.get('ffmpeg_dir') != self.ffmpeg_dir:
            self.config['ffmpeg_dir'] = self.ffmpeg_dir
            changed = True
        # pCloud sync root (holds DCIM/ and Pictures/); empty = deduced from Camera
        if 'pcloud_root' not in self.config:
            self.config['pcloud_root'] = DEFAULT_PCLOUD_ROOT
            changed = True
        if 'pcloud_autoimport' not in self.config:
            self.config['pcloud_autoimport'] = True
            changed = True
        if changed:
            save_json(CONFIG_FILE, self.config)
        resolve_ffmpeg(self.ffmpeg_dir)
        self.files = []            # list of dicts: filename, filepath, ext, datetime, year, folder
        self.dup_moves = {}        # {filename: [paths to move]}
        self.current_screenshots = []
        self.files_by_uid = {}     # uid -> entry of self.files (see fill_file_table)
        self.sort_source_index = 0   # 0 = Camera, 1 = Screenshots, 2 = ScreenRecorder
        self.dup_temp_files = []
        self.current_dup_row = None
        # Video slideshow state (duplicates tab)
        self.slide_frames = [[], []]     # per side: [(percent, QPixmap, jpg_path), ...]
        self.slide_index = 0
        self.video_frame_cache = {}      # path -> frames
        self.hash_cache = {}             # path -> [dHash, ...]
        # Background comparison
        self.row_token = 0
        self.compare_results = {}        # token -> result dict
        self.compare_worker = None
        self.compare_done = 0
        self.compare_total = 0
        self.prefetch_worker = None
        # Preview pipeline: decoded images kept in a small LRU, decoding done off-thread
        self.preview_cache = OrderedDict()
        self.loader = PreviewLoader(self)
        self.current_shot_pct = DEFAULT_SHOT_PCT
        self.loader.image_ready.connect(self.on_preview_ready)
        self.loader.shot_ready.connect(self.on_shot_ready)
        self.loader.thumb_ready.connect(self.on_thumb_ready)
        # Viewer thumbnails: their own little pool, so a folder fills up at once
        self.thumb_cache = OrderedDict()     # path -> QPixmap (already framed)
        self.thumb_rows = {}
        self._empty_thumb = None
        self.thumb_pool = ThumbPool(lambda: self.video_cache_dir, parent=self)
        self.thumb_pool.ready.connect(self.on_thumb_ready)
        self.loader.start()
        self.save_timer = QTimer(self)
        self.save_timer.setSingleShot(True)
        self.save_timer.timeout.connect(self.save_edits)
        self.slide_timer = QTimer(self)
        self.slide_timer.timeout.connect(self.advance_slideshow)
        self.current_pixmap = None
        self.current_filepath = None
        self.zoom = 1.0
        self._filling = False

        self.video_cache_dir = os.path.join(self.base_path, '!tempvideoscreen') if os.path.isdir(self.base_path) else None

        self.build_ui()
        self.restore_column_layout()
        log("=== TriPhoto started ===")
        log(f"Python: {sys.executable}")
        log(f"Camera folder: {self.base_path}")
        if not PIL_AVAILABLE:
            log("⚠️ Pillow indisponible - previews désactivées")
        elif not HEIF_AVAILABLE:
            log("⚠️ pillow-heif indisponible - previews HEIC/HEIF désactivées")
        if FFMPEG:
            log(f"🎬 ffmpeg: {FFMPEG}")
            log(f"🎬 ffprobe: {FFPROBE}" if FFPROBE else "🎬 ffprobe: absent (durée lue via ffmpeg)")
        else:
            log("⚠️ ffmpeg introuvable - aucun aperçu vidéo.")
            for c in FFMPEG_TRIED[:12]:
                log(f"   testé: {c}")
            log(f"   → mets le bon dossier dans \"ffmpeg_dir\" de {CONFIG_FILE}, "
                f"ou pose ffmpeg.exe à côté du script, ou: pip install imageio-ffmpeg")

        QTimer.singleShot(300, self.startup_load)

    # ---------- UI ----------

    def build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root_layout = QVBoxLayout(central)
        root_layout.setContentsMargins(10, 10, 10, 10)

        # Top bar: camera path
        top = QHBoxLayout()
        top.addWidget(QLabel("📁 Dossier Camera :"))
        self.path_edit = QLineEdit(self.base_path)
        self.path_edit.editingFinished.connect(self.on_path_edited)
        top.addWidget(self.path_edit, stretch=1)
        btn_browse = QPushButton("Parcourir…")
        btn_browse.clicked.connect(self.browse_folder)
        top.addWidget(btn_browse)
        btn_scan = QPushButton("🔄 Recharger")
        btn_scan.clicked.connect(self.startup_load)
        top.addWidget(btn_scan)
        root_layout.addLayout(top)

        # Second line: pCloud sync folder
        sync = QHBoxLayout()
        sync.addWidget(QLabel("☁️ Dossier pCloud :"))
        self.pcloud_edit = QLineEdit(self.pcloud_root())
        self.pcloud_edit.setToolTip("Dossier contenant DCIM\\ et Pictures\\.\n"
                                    "Vide = déduit du dossier Camera.")
        self.pcloud_edit.editingFinished.connect(self.on_pcloud_edited)
        sync.addWidget(self.pcloud_edit, stretch=1)
        btn_pcloud = QPushButton("Parcourir…")
        btn_pcloud.clicked.connect(self.browse_pcloud)
        sync.addWidget(btn_pcloud)
        self.autoimport_check = QCheckBox("Importer à l'ouverture")
        self.autoimport_check.setChecked(bool(self.config.get('pcloud_autoimport', True)))
        self.autoimport_check.setToolTip(
            "Vide Pictures\\ et DCIM\\Screenshots / ScreenRecorder dans Camera\\ "
            "à chaque lancement.")
        self.autoimport_check.toggled.connect(self.on_autoimport_toggled)
        sync.addWidget(self.autoimport_check)
        btn_import = QPushButton("📥 Importer maintenant")
        btn_import.clicked.connect(self.import_pcloud_now)
        sync.addWidget(btn_import)
        root_layout.addLayout(sync)

        # Tabs
        self.tabs = QTabWidget()
        root_layout.addWidget(self.tabs, stretch=1)

        self.tabs.addTab(self.build_rename_tab(), "1️⃣  Renommage")
        self.tabs.addTab(self.build_dup_tab(), "2️⃣  Doublons")
        self.tabs.addTab(self.build_sort_tab(), "3️⃣  Tri des médias")
        self.tabs.addTab(self.build_viewer_tab(), "4️⃣  Visualiseur")
        self.tabs.currentChanged.connect(self.on_tab_changed)

        self.statusBar().showMessage("Prêt")

    # ----- Tab 1: rename -----

    def build_rename_tab(self):
        w = QWidget()
        layout = QVBoxLayout(w)

        info = QLabel("Chaque dossier doit commencer par son année (ex : « 2015-11 Bruxelles WeekEnd »). "
                      "Double-clic sur une proposition pour la modifier. Rien n'est renommé sans « Appliquer ». "
                      "Si le dossier cible existe déjà, le contenu est fusionné (fichiers identiques → !duplicate).")
        info.setWordWrap(True)
        layout.addWidget(info)

        btns = QHBoxLayout()
        b_analyze = QPushButton("🔍 Analyser")
        b_analyze.clicked.connect(self.analyze_renames)
        btns.addWidget(b_analyze)
        b_apply = QPushButton("✏️ Appliquer les renommages")
        b_apply.clicked.connect(self.apply_renames)
        btns.addWidget(b_apply)
        b_fp = QPushButton("🙈 Faux positif (exclure)")
        b_fp.clicked.connect(self.exclude_similar)
        btns.addWidget(b_fp)
        self.rename_summary = QLabel("")
        btns.addWidget(self.rename_summary)
        btns.addStretch(1)
        layout.addLayout(btns)

        self.rename_table = QTableWidget(0, 5)
        self.rename_table.setHorizontalHeaderLabels(["Année", "Nom actuel", "Fichiers", "Proposition", "Statut"])
        self.rename_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.rename_table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.rename_table.setEditTriggers(QAbstractItemView.EditTrigger.DoubleClicked)
        self.rename_table.verticalHeader().setVisible(False)
        setup_header(self.rename_table, [70, 380, 130, 380, 130])
        self.rename_table.itemChanged.connect(self.on_rename_item_changed)
        self.rename_table.cellDoubleClicked.connect(self.on_rename_cell_double_clicked)
        layout.addWidget(self.rename_table, stretch=1)
        return w

    def on_rename_cell_double_clicked(self, row, col):
        """Empty proposition -> pre-fill with the current name before editing"""
        if col != 3:
            return
        it = self.rename_table.item(row, 3)
        if it and not it.text().strip():
            self._filling = True
            it.setText(self.rename_table.item(row, 1).text())
            self._filling = False

    def analyze_renames(self):
        base = self.base_path
        if not os.path.isdir(base):
            log(f"❌ Camera folder not found: {base}")
            return
        self._filling = True
        self.rename_table.setSortingEnabled(False)   # sorting while filling scrambles rows
        self.rename_table.setRowCount(0)
        self._folder_exclusions = load_folder_exclusions()  # reloaded each analysis (file is hand-editable)
        ok_count = auto_count = manual_count = similar_count = 0
        for item in sorted(os.listdir(base)):
            year_path = os.path.join(base, item)
            if not (os.path.isdir(year_path) and re.match(r'^\d{4}$', item)):
                continue
            # Collect folders of this year: [name, file_count, proposed, status]
            entries = []
            for folder in sorted(os.listdir(year_path)):
                folder_path = os.path.join(year_path, folder)
                if not os.path.isdir(folder_path) or folder.startswith('!'):
                    continue
                proposed, status = propose_folder_name(item, folder)
                entries.append([folder, count_files(folder_path), proposed, status])

            # Flag near-identical folder names within the same year (probable duplicates)
            exclusions = self._folder_exclusions
            ok_entries = [e for e in entries if e[3] == 'ok']
            for i in range(len(ok_entries)):
                for j in range(i + 1, len(ok_entries)):
                    a, b = ok_entries[i], ok_entries[j]
                    if a[3] != 'ok' or b[3] != 'ok':
                        continue
                    if tuple(sorted((a[0], b[0]))) in exclusions:
                        continue
                    ma, mb = month_of(a[0], item), month_of(b[0], item)
                    if ma and mb and ma != mb:
                        continue  # same name but different month = different events
                    if name_similarity(a[0], b[0]) >= 0.8:
                        small, big = (a, b) if a[1] <= b[1] else (b, a)
                        small[2] = big[0]   # proposition: merge into the bigger one
                        small[3] = 'similar'

            for folder, nfiles, proposed, status in entries:
                row = self.rename_table.rowCount()
                self.rename_table.insertRow(row)
                items = [QTableWidgetItem(item), QTableWidgetItem(folder),
                         QTableWidgetItem(str(nfiles)), QTableWidgetItem(proposed),
                         QTableWidgetItem('')]
                items[2].setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                for col, it in enumerate(items):
                    if col != 3:
                        it.setFlags(it.flags() & ~Qt.ItemFlag.ItemIsEditable)
                    self.rename_table.setItem(row, col, it)
                if status == 'ok':
                    ok_count += 1
                    items[4].setText('✅ OK')
                    for it in items:
                        it.setForeground(COLOR_OK_FG)
                elif status == 'similar':
                    similar_count += 1
                    items[4].setText('🔎 Doublon ?')
                    # Remember the detected pair so 'Exclure' works even after edits
                    items[1].setData(Qt.ItemDataRole.UserRole, proposed)
                    for it in items:
                        it.setBackground(COLOR_MANUAL)
                elif status == 'move':
                    auto_count += 1
                    items[4].setText(f'📦 → {proposed[:4]}')
                    for it in items:
                        it.setBackground(COLOR_AUTO)
                elif status == 'auto':
                    auto_count += 1
                    items[4].setText('🔄 Auto')
                    for it in items:
                        it.setBackground(COLOR_AUTO)
                else:
                    manual_count += 1
                    items[4].setText('⚠️ Manuel')
                    for it in items:
                        it.setBackground(COLOR_MANUAL)
        self._filling = False
        self.rename_table.setSortingEnabled(True)
        self.rename_summary.setText(f"✅ {ok_count} OK   |   🔄 {auto_count} auto   |   "
                                    f"🔎 {similar_count} doublon(s) ?   |   ⚠️ {manual_count} à voir")
        log(f"Rename analysis: {ok_count} OK, {auto_count} auto-detected, "
            f"{similar_count} similar, {manual_count} manual")

    def on_rename_item_changed(self, item):
        if self._filling or item.column() != 3:
            return
        row = item.row()
        status_item = self.rename_table.item(row, 4)
        if status_item and item.text().strip():
            log(f"✍️ Proposition: {self.rename_table.item(row, 1).text()} -> {item.text().strip()}")
            self._filling = True
            status_item.setText('✍️ Modifié')
            for col in range(5):
                it = self.rename_table.item(row, col)
                if it:
                    it.setBackground(COLOR_AUTO)
            self._filling = False

    def exclude_similar(self):
        """Mark selected 🔎 rows as false positives (saved to FolderDoublonExclusion.txt)"""
        rows = sorted({idx.row() for idx in self.rename_table.selectedIndexes()})
        count = 0
        self._filling = True
        for row in rows:
            name_item = self.rename_table.item(row, 1)
            partner = name_item.data(Qt.ItemDataRole.UserRole)
            if not partner:
                continue  # not a detected duplicate pair
            a, b = sorted((name_item.text(), partner))
            save_folder_exclusion(a, b)
            log(f"🙈 Faux positif exclu: {a} <> {b}")
            self._folder_exclusions = getattr(self, '_folder_exclusions', set())
            self._folder_exclusions.add((a, b))
            name_item.setData(Qt.ItemDataRole.UserRole, None)
            self.rename_table.item(row, 3).setText('')
            self.rename_table.item(row, 4).setText('✅ OK')
            for col in range(5):
                it = self.rename_table.item(row, col)
                it.setBackground(QColor(0, 0, 0, 0))
                it.setForeground(COLOR_OK_FG)
            count += 1
        self._filling = False
        if count:
            log(f"Folder duplicate exclusions added: {count} -> {EXCLUSION_FILE}")
            self.statusBar().showMessage(f"🙈 {count} paire(s) exclue(s) → FolderDoublonExclusion.txt")
        else:
            log("🙈 Exclure: aucune ligne '🔎 Doublon ?' dans la sélection - sélectionne la ligne flaggée avant de cliquer")
            self.statusBar().showMessage("🙈 Sélectionne une ligne 🔎 Doublon ? d'abord")

    def apply_renames(self):
        base = self.base_path
        renamed = errors = 0
        self._filling = True
        for row in range(self.rename_table.rowCount()):
            year = self.rename_table.item(row, 0).text()
            current = self.rename_table.item(row, 1).text()
            proposed = self.rename_table.item(row, 3).text().strip()
            if not proposed or (proposed == current and self.rename_table.item(row, 4).text().startswith('✅')):
                continue
            old_path = os.path.join(base, year, current)
            # Destination year = leading year of the proposed name (folder moves if different)
            ym = re.match(r'^(20\d{2})', proposed)
            dest_year = ym.group(1) if ym else year
            new_path = os.path.join(base, dest_year, proposed)
            if not os.path.isdir(old_path) or old_path == new_path:
                continue
            if os.path.normcase(old_path) == os.path.normcase(new_path):
                # Same folder, only the case changes -> direct rename, NO merge
                try:
                    os.rename(old_path, new_path)
                    log(f"Renamed (case): {year}/{current} -> {proposed}")
                    self.rename_table.item(row, 1).setText(proposed)
                    self.rename_table.item(row, 3).setText('')
                    self.rename_table.item(row, 4).setText('✅ Renommé')
                    for col in range(5):
                        self.rename_table.item(row, col).setBackground(COLOR_DONE)
                    renamed += 1
                except Exception as e:
                    self.rename_table.item(row, 4).setText('❌ Erreur')
                    log(f"❌ Rename error {year}/{current}: {e}")
                    errors += 1
                continue
            if os.path.exists(new_path):
                # Target already exists (e.g. pCloud sync recreated the old folder) -> merge
                m, du, e = merge_folders(old_path, new_path, os.path.join(base, '!duplicate'))
                log(f"🔀 Merged: {year}/{current} -> {proposed} "
                    f"({m} déplacé(s), {du} doublon(s) -> !duplicate, {e} erreur(s))")
                if not os.path.exists(old_path):
                    self.rename_table.item(row, 1).setText(proposed)
                    self.rename_table.item(row, 3).setText('')
                    self.rename_table.item(row, 4).setText('🔀 Fusionné')
                    for col in range(5):
                        self.rename_table.item(row, col).setBackground(COLOR_DONE)
                    renamed += 1
                else:
                    self.rename_table.item(row, 4).setText('⚠️ Fusion partielle')
                    errors += 1
                continue
            try:
                os.makedirs(os.path.dirname(new_path), exist_ok=True)
                os.rename(old_path, new_path)
                log(f"Renamed: {year}/{current} -> {dest_year}/{proposed}")
                self.rename_table.item(row, 1).setText(proposed)
                self.rename_table.item(row, 3).setText('')
                self.rename_table.item(row, 4).setText('✅ Renommé')
                for col in range(5):
                    self.rename_table.item(row, col).setBackground(COLOR_DONE)
                renamed += 1
            except Exception as e:
                self.rename_table.item(row, 4).setText('❌ Erreur')
                log(f"❌ Rename error {year}/{current}: {e}")
                errors += 1
        self._filling = False
        self.statusBar().showMessage(f"✏️ {renamed} dossier(s) renommé(s)" + (f", {errors} erreur(s)" if errors else ""))

    # ----- Tab 2: duplicates -----

    def build_dup_tab(self):
        w = QWidget()
        layout = QVBoxLayout(w)

        info = QLabel("Sélectionne une ou plusieurs lignes (Ctrl / Maj), puis choisis quel côté part à la corbeille "
                      "avec les boutons sous les aperçus (raccourci <b>Suppr</b> = Copie 2). "
                      "Sous les aperçus, ce qui <span style=\"" + DIFF_STYLE + "\">diffère</span> entre les deux "
                      "chemins est surligné. La colonne <b>Score</b> se remplit toute seule en tâche de fond "
                      "(taille + contenu affiché + durée pour les vidéos). Les vidéos défilent en diaporama "
                      "(10/30/50/70/90 % de la durée) et un <b>double-clic</b> sur un aperçu ouvre le fichier. "
                      "Les lignes traitées disparaissent et la sélection avance toute seule ; "
                      "« Scanner » reconstruit tout depuis le disque.")
        info.setTextFormat(Qt.TextFormat.RichText)
        info.setWordWrap(True)
        layout.addWidget(info)

        btns = QHBoxLayout()
        b_scan = QPushButton("🔍 Scanner")
        b_scan.clicked.connect(self.scan_duplicates)
        btns.addWidget(b_scan)
        b_go = QPushButton("🗑️ Tout traiter (Auto/Suffixe → Copie 2)")
        b_go.setToolTip("Envoie à la corbeille la Copie 2 de toutes les lignes 🔄 Auto et 🔄 Suffixe.\n"
                        "Les ⚠️ Conflits ne sont jamais traités automatiquement.")
        b_go.clicked.connect(self.process_auto)
        btns.addWidget(b_go)
        b_cmp = QPushButton("🔬 Recomparer")
        b_cmp.setToolTip("Relance la comparaison (taille + contenu + durée) sur les lignes\n"
                         "sélectionnées, ou sur tout le tableau si rien n'est sélectionné.\n"
                         "Elle démarre déjà toute seule après chaque scan.")
        b_cmp.clicked.connect(self.compare_selection)
        btns.addWidget(b_cmp)
        b_ignore = QPushButton("🙈 Ignorer sélection")
        b_ignore.clicked.connect(self.ignore_duplicates)
        btns.addWidget(b_ignore)
        self.dup_summary = QLabel("")
        btns.addWidget(self.dup_summary)
        btns.addStretch(1)
        layout.addLayout(btns)

        self.dup_table = QTableWidget(0, 5)
        self.dup_table.setHorizontalHeaderLabels(["Fichier", "Type", "Score", "Copie 1", "Copie 2"])
        self.dup_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.dup_table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.dup_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.dup_table.verticalHeader().setVisible(False)
        setup_header(self.dup_table, [340, 110, 90, 380, 380])
        self.dup_table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.dup_table.customContextMenuRequested.connect(self.dup_context_menu)
        QShortcut(QKeySequence(Qt.Key.Key_Delete), self.dup_table,
                  activated=lambda: self.trash_side(1),
                  context=Qt.ShortcutContext.WidgetShortcut)
        layout.addWidget(self.dup_table, stretch=1)

        # Side-by-side comparison of both copies with unit actions
        prev = QWidget()
        ph = QHBoxLayout(prev)
        ph.setContentsMargins(0, 4, 0, 0)
        self.dup_thumb_labels = []
        self.dup_caption_labels = []
        self.dup_trash_buttons = []
        for side, title in enumerate(("📁 Copie 1 (gardée par défaut)", "📁 Copie 2 (doublon présumé)")):
            box = QVBoxLayout()
            t = QLabel(title)
            t.setAlignment(Qt.AlignmentFlag.AlignCenter)
            t.setStyleSheet("font-weight: bold;")
            box.addWidget(t)
            img = ClickableLabel("—")
            img.setAlignment(Qt.AlignmentFlag.AlignCenter)
            img.setFixedHeight(220)
            img.setStyleSheet("background-color: #1a1a1c;")
            img.setToolTip("Double-clic : ouvrir le fichier")
            img.setCursor(Qt.CursorShape.PointingHandCursor)
            img.doubleClicked.connect(lambda s=side: self.open_file_side(s))
            box.addWidget(img)
            cap = QLabel("—")
            cap.setAlignment(Qt.AlignmentFlag.AlignCenter)
            cap.setTextFormat(Qt.TextFormat.RichText)
            cap.setWordWrap(True)
            cap.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            box.addWidget(cap)
            act = QHBoxLayout()
            b_trash = QPushButton(f"🗑️ Mise à la corbeille (Copie {side + 1})")
            b_trash.setToolTip(f"Envoie à la corbeille la Copie {side + 1} de TOUTES les lignes sélectionnées.")
            b_trash.clicked.connect(lambda checked, s=side: self.trash_side(s))
            act.addWidget(b_trash)
            b_open = QPushButton("📂 Ouvrir le dossier")
            b_open.clicked.connect(lambda checked, s=side: self.open_side(s))
            act.addWidget(b_open)
            box.addLayout(act)
            ph.addLayout(box)
            self.dup_thumb_labels.append(img)
            self.dup_caption_labels.append(cap)
            self.dup_trash_buttons.append(b_trash)
        layout.addWidget(prev)

        self.dup_verdict = QLabel("—")
        self.dup_verdict.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.dup_verdict.setTextFormat(Qt.TextFormat.RichText)
        self.dup_verdict.setStyleSheet("padding: 4px;")
        layout.addWidget(self.dup_verdict)

        self.dup_table.itemSelectionChanged.connect(self.update_dup_preview)
        return w

    def selected_dup_rows(self):
        return sorted({idx.row() for idx in self.dup_table.selectedIndexes()})

    def select_dup_row(self, row):
        """Select the given row (clamped to the table) and refresh the preview.
        Used to auto-advance after a deletion so you can chain without clicking."""
        count = self.dup_table.rowCount()
        self.dup_table.clearSelection()
        if count == 0:
            self.current_dup_row = None
            self.update_dup_preview()
            return
        row = max(0, min(row, count - 1))
        self.dup_table.blockSignals(True)   # avoid building the preview twice
        try:
            self.dup_table.selectRow(row)
        finally:
            self.dup_table.blockSignals(False)
        self.dup_table.scrollToItem(self.dup_table.item(row, 0),
                                    QAbstractItemView.ScrollHint.EnsureVisible)
        self.dup_table.setFocus()
        self.current_dup_row = row
        self.update_dup_preview()

    def refresh_dup_summary(self):
        """Recount from the table itself so the summary stays true after removals"""
        auto = suffix = conflict = 0
        for row in range(self.dup_table.rowCount()):
            kind = self.dup_table.item(row, 1).text()
            if kind.startswith('🔄 Suffixe'):
                suffix += 1
            elif kind.startswith('🔄'):
                auto += 1
            else:
                conflict += 1
        self.dup_summary.setText(f"🔄 {auto} déplaçable(s)   |   🔄 {suffix} copie(s) _N   "
                                 f"|   ⚠️ {conflict} conflit(s)")
        return auto, suffix, conflict

    def update_dup_preview(self):
        """Show thumbnails of both copies of the selected duplicate"""
        self.stop_slideshow()
        self.trim_video_cache()
        rows = self.selected_dup_rows()
        self.current_dup_row = rows[0] if rows else None
        # Buttons always name the side and show how many rows they will affect
        for side, btn in enumerate(self.dup_trash_buttons):
            suffix = f" — {len(rows)} lignes" if len(rows) > 1 else ""
            btn.setText(f"🗑️ Mise à la corbeille (Copie {side + 1}){suffix}")
            btn.setEnabled(bool(rows))
        if self.current_dup_row is None:
            for i in (0, 1):
                self.dup_thumb_labels[i].setPixmap(QPixmap())
                self.dup_thumb_labels[i].setText("—")
                self.dup_caption_labels[i].setText("—")
            self.dup_verdict.setText("—")
            return
        row = self.current_dup_row

        # --- captions: both paths compared side by side, differences highlighted ---
        sides = []
        for i in (0, 1):
            paths = self.dup_table.item(row, 3 + i).data(Qt.ItemDataRole.UserRole) or []
            path = paths[0] if paths else ''
            rel = os.path.relpath(path, self.base_path) if path else ''
            try:
                size = os.path.getsize(path) if path and os.path.isfile(path) else None
            except OSError:
                size = None
            sides.append({'paths': paths, 'path': path, 'rel': rel, 'size': size})

        if sides[0]['rel'] and sides[1]['rel']:
            html0, html1 = diff_path_html(sides[0]['rel'], sides[1]['rel'])
        else:
            html0 = f'<span style="{SAME_STYLE}">{_esc(sides[0]["rel"])}</span>'
            html1 = f'<span style="{SAME_STYLE}">{_esc(sides[1]["rel"])}</span>'
        htmls = [html0, html1]
        sizes_differ = (sides[0]['size'] is not None and sides[1]['size'] is not None
                        and sides[0]['size'] != sides[1]['size'])

        for i in (0, 1):
            cap_label = self.dup_caption_labels[i]
            s = sides[i]
            if not s['path']:
                cap_label.setText("—")
                continue
            if s['size'] is None:
                cap_label.setText(f"<span style=\"color:#ff6b6b;\">(fichier absent)</span> "
                                  f"{htmls[i]}")
                continue
            size_style = "color:#ff9b3d; font-weight:bold;" if sizes_differ else SAME_STYLE
            extra = (f'<span style="{DIFF_STYLE}">+{len(s["paths"]) - 1} autre(s)</span>'
                     if len(s['paths']) > 1 else '')
            cap_label.setText(
                f'{htmls[i]}'
                f'<span style="{size_style}">&nbsp;&nbsp;({s["size"] / 1024:,.0f} Ko)</span>'
                f'&nbsp;&nbsp;{extra}')

        # --- previews: still image, or a 5-frame slideshow for videos ---
        self.stop_slideshow()
        for i in (0, 1):
            img_label = self.dup_thumb_labels[i]
            path = sides[i]['path']
            if not path or not os.path.isfile(path):
                img_label.setPixmap(QPixmap())
                img_label.setText("—")
                continue
            ext = os.path.splitext(path)[1].lower()
            if ext in VIDEO_EXTS:
                frames = self.video_frames(path)
                self.slide_frames[i] = frames
                if frames:
                    self.show_frame(i, 0)
                else:
                    img_label.setPixmap(QPixmap())
                    img_label.setText("(pas d'aperçu vidéo — ffmpeg introuvable)"
                                      if not FFMPEG else "(pas d'aperçu vidéo)")
                continue
            pm = self.make_thumb(path)
            if pm:
                img_label.setText("")
                img_label.setPixmap(pm.scaled(QSize(420, 210),
                                              Qt.AspectRatioMode.KeepAspectRatio,
                                              Qt.TransformationMode.SmoothTransformation))
            else:
                img_label.setPixmap(QPixmap())
                img_label.setText("(pas d'aperçu)")
        if any(self.slide_frames):
            self.slide_index = 0
            self.slide_timer.start(VIDEO_SLIDE_MS)

        # --- verdict: do the two files actually hold the same picture? ---
        self.update_verdict(sides[0]['path'], sides[1]['path'])

    # ----- video slideshow -----

    def stop_slideshow(self):
        self.slide_timer.stop()
        self.slide_frames = [[], []]
        self.slide_index = 0

    def show_frame(self, side, index):
        frames = self.slide_frames[side]
        if not frames:
            return
        pct, pm, _ = frames[index % len(frames)]
        label = self.dup_thumb_labels[side]
        label.setText("")
        label.setPixmap(pm.scaled(QSize(420, 210),
                                  Qt.AspectRatioMode.KeepAspectRatio,
                                  Qt.TransformationMode.SmoothTransformation))
        label.setToolTip(f"🎬 {pct}% de la vidéo — double-clic : ouvrir le fichier")

    def advance_slideshow(self):
        self.slide_index += 1
        for side in (0, 1):
            self.show_frame(side, self.slide_index)

    def video_frames(self, path):
        """Extract frames at VIDEO_SAMPLE_POINTS. Returns [(percent, QPixmap, jpg_path), ...].
        Cached per file so re-selecting a row costs nothing."""
        if path in self.video_frame_cache:
            return self.video_frame_cache[path]
        frames = []
        if not FFMPEG:
            self.video_frame_cache[path] = frames
            return frames
        temp_dir = os.path.join(self.base_path, '!temp')
        self.statusBar().showMessage(f"🎬 Extraction des images de {os.path.basename(path)}…")
        QApplication.processEvents()
        # Shares the jpgs with the background comparison: whichever ran first wins
        for pct, jpg in extract_video_jpgs(path, temp_dir):
            pm = QPixmap(jpg)
            self.dup_temp_files.append(jpg)
            if not pm.isNull():
                frames.append((pct, pm, jpg))
        if not frames:
            log(f"❌ Aucune image extraite: {os.path.basename(path)}")
        self.video_frame_cache[path] = frames
        return frames

    # ----- content comparison -----

    def row_of_token(self, token):
        for row in range(self.dup_table.rowCount()):
            it = self.dup_table.item(row, 0)
            if it and it.data(Qt.ItemDataRole.UserRole) == token:
                return row
        return None

    def row_path_lists(self, row):
        return (self.dup_table.item(row, 3).data(Qt.ItemDataRole.UserRole) or [],
                self.dup_table.item(row, 4).data(Qt.ItemDataRole.UserRole) or [])

    def row_paths(self, row):
        p1, p2 = self.row_path_lists(row)
        return (p1[0] if p1 else ''), (p2[0] if p2 else '')

    def dup_context_menu(self, pos):
        row = self.dup_table.rowAt(pos.y())
        if row < 0:
            return
        if row not in self.selected_dup_rows():
            self.select_dup_row(row)
        rows = self.selected_dup_rows()
        single = len(rows) == 1
        menu = QMenu(self)
        for side in (0, 1):
            act = menu.addAction(f"✏️ Renommer la Copie {side + 1}…")
            act.setEnabled(single)
            act.triggered.connect(lambda _=False, s=side: self.rename_side(s))
        menu.addSeparator()
        for side in (0, 1):
            act = menu.addAction(f"📂 Ouvrir le dossier de la Copie {side + 1}")
            act.setEnabled(single)
            act.triggered.connect(lambda _=False, s=side: self.open_side(s))
        for side in (0, 1):
            act = menu.addAction(f"▶️ Ouvrir la Copie {side + 1}")
            act.setEnabled(single)
            act.triggered.connect(lambda _=False, s=side: self.open_file_side(s))
        menu.addSeparator()
        for side in (0, 1):
            act = menu.addAction(f"🗑️ Corbeille — Copie {side + 1}"
                                 + (f" ({len(rows)} lignes)" if not single else ""))
            act.triggered.connect(lambda _=False, s=side: self.trash_side(s))
        menu.addSeparator()
        menu.addAction("🔬 Recomparer ces lignes").triggered.connect(self.compare_selection)
        menu.addAction("🙈 Ignorer (mémorisé)").triggered.connect(self.ignore_duplicates)
        menu.addAction(f"♻️ Oublier les {len(self.ignore_list)} ignoré(s)…"
                       ).triggered.connect(self.forget_ignored)
        menu.exec(self.dup_table.viewport().mapToGlobal(pos))

    def rename_side(self, side):
        """Rename one of the two files: the usual fix when a '_1' is in fact a
        different shot that just got a lazy name."""
        row = self.current_dup_row
        if row is None or row >= self.dup_table.rowCount():
            return
        paths = self.dup_table.item(row, 3 + side).data(Qt.ItemDataRole.UserRole) or []
        old = paths[0] if paths else ''
        if not old or not os.path.isfile(old):
            self.statusBar().showMessage("Fichier introuvable")
            return
        folder, current = os.path.split(old)
        new_name, ok = QInputDialog.getText(
            self, f"Renommer la Copie {side + 1}",
            f"Dossier : {os.path.relpath(folder, self.base_path)}\n\nNouveau nom :",
            text=current)
        new_name = (new_name or '').strip()
        if not ok or not new_name or new_name == current:
            return
        new_path = os.path.join(folder, new_name)
        if os.path.exists(new_path):
            QMessageBox.warning(self, "Renommer", f"« {new_name} » existe déjà dans ce dossier.")
            return
        try:
            os.rename(old, new_path)
        except Exception as e:
            log(f"❌ Renommage {current}: {e}")
            QMessageBox.warning(self, "Renommer", f"Échec du renommage :\n{e}")
            return
        log(f"✏️ Renommé: {os.path.relpath(old, self.base_path)} -> {new_name}")
        rest = paths[1:]
        self.dup_table.item(row, 3 + side).setData(Qt.ItemDataRole.UserRole, [new_path] + rest)
        self.dup_table.item(row, 3 + side).setText(
            "; ".join(os.path.relpath(p, self.base_path) for p in [new_path] + rest))
        if side == 1:
            self.dup_table.item(row, 0).setText(new_name)
        # No longer a name collision -> out of the automatic batch
        self.dup_table.item(row, 1).setText('✏️ Renommé')
        for col in range(5):
            self.dup_table.item(row, col).setBackground(COLOR_DONE)
        self.update_dup_preview()
        self.statusBar().showMessage(f"✏️ Renommé en « {new_name} »")

    def start_background_compare(self, rows=None):
        """Score the rows in a worker thread. Called right after a scan, so the
        Score column fills itself while you already work on the first rows."""
        self.stop_background_compare()
        if rows is None:
            rows = [r for r in range(self.dup_table.rowCount())
                    if r not in self.scored_tokens_rows()]
        jobs = []
        for row in rows:
            token = self.dup_table.item(row, 0).data(Qt.ItemDataRole.UserRole)
            pa, pb = self.row_paths(row)
            if token is not None and pa and pb:
                jobs.append((token, pa, pb))
        if not jobs:
            return
        self.compare_total = len(jobs)
        self.compare_done = 0
        self.compare_worker = CompareWorker(jobs, os.path.join(self.base_path, '!temp'), self)
        self.compare_worker.scored.connect(self.apply_score)
        self.compare_worker.progressed.connect(self.on_compare_progress)
        self.compare_worker.finished.connect(self.on_compare_finished)
        self.compare_worker.start()
        log(f"🔬 Comparaison en tâche de fond: {len(jobs)} ligne(s)")

    def scored_tokens_rows(self):
        """Rows already carrying a result"""
        return {row for row in range(self.dup_table.rowCount())
                if self.dup_table.item(row, 2).text() not in ('…', '')}

    def stop_background_compare(self, blocking=False):
        w = getattr(self, 'compare_worker', None)
        if w and w.isRunning():
            w.stop()
            if blocking:
                w.wait(3000)
        self.compare_worker = None

    def on_compare_progress(self, done, total):
        self.compare_done = done
        if done % 5 == 0 or done == total:
            self.statusBar().showMessage(f"🔬 Comparaison en fond… {done}/{total}")

    def on_compare_finished(self):
        self.statusBar().showMessage(f"🔬 Comparaison terminée ({self.compare_done} ligne(s))")
        log(f"🔬 Comparaison terminée: {self.compare_done} ligne(s)")

    def apply_score(self, token, res):
        """A background result landed: write it into the Score column"""
        row = self.row_of_token(token)
        if row is None:
            return          # row was deleted meanwhile
        self.compare_results[token] = res
        emoji, short, long_label, color = verdict_for(res)
        item = self.dup_table.item(row, 2)
        item.setText(f"{emoji} {short}")
        if isinstance(item, SortableItem):
            item.sort_key = res.get('content') if res.get('content') is not None else -1.0
        item.setForeground(QColor(color))
        item.setToolTip(f"{long_label}\n{verdict_details(res)}")
        score = res.get('content')
        if score is not None and score < SIM_RELATED:
            for col in range(5):
                self.dup_table.item(row, col).setBackground(COLOR_CONFLICT)
        if row == self.current_dup_row:
            self.show_verdict(res)

    def show_verdict(self, res):
        emoji, _short, long_label, color = verdict_for(res)
        details = verdict_details(res)
        self.dup_verdict.setText(
            f'<span style="color:{color}; font-weight:bold;">{emoji} {long_label}</span>'
            f'<span style="{SAME_STYLE}">&nbsp;&nbsp;·&nbsp;&nbsp;{details}</span>')

    def update_verdict(self, path_a, path_b):
        """Verdict for the row on screen: reuse the background result if it already
        arrived, otherwise compute this one pair right away."""
        row = self.current_dup_row
        token = (self.dup_table.item(row, 0).data(Qt.ItemDataRole.UserRole)
                 if row is not None else None)
        if token is not None and token in self.compare_results:
            self.show_verdict(self.compare_results[token])
            return
        if not path_a or not path_b or not os.path.isfile(path_a) or not os.path.isfile(path_b):
            self.dup_verdict.setText("—")
            return
        temp_dir = os.path.join(self.base_path, '!temp')
        try:
            identical = (os.path.getsize(path_a) == os.path.getsize(path_b)
                         and filecmp.cmp(path_a, path_b, shallow=False))
        except OSError:
            identical = False
        res = compare_fingerprints(fingerprint(path_a, temp_dir),
                                   fingerprint(path_b, temp_dir), identical)
        if token is not None:
            self.compare_results[token] = res
            self.apply_score(token, res)
        else:
            self.show_verdict(res)

    def compare_selection(self):
        """Re-run the comparison on the selected rows (or restart the whole pass
        when nothing is selected)"""
        rows = self.selected_dup_rows()
        if not rows:
            rows = list(range(self.dup_table.rowCount()))
        for row in rows:
            token = self.dup_table.item(row, 0).data(Qt.ItemDataRole.UserRole)
            self.compare_results.pop(token, None)
            self.dup_table.item(row, 2).setText("…")
        self.start_background_compare(rows)

    def open_file_side(self, side):
        """Double-click on a preview: open the file itself"""
        row = self.current_dup_row
        if row is None or row >= self.dup_table.rowCount():
            return
        paths = self.dup_table.item(row, 3 + side).data(Qt.ItemDataRole.UserRole) or []
        if paths and os.path.isfile(paths[0]):
            try:
                os.startfile(paths[0])
            except Exception as e:
                log(f"❌ Ouverture {os.path.basename(paths[0])}: {e}")

    def make_thumb(self, path):
        """Still thumbnail for images (videos go through video_frames)"""
        ext = os.path.splitext(path)[1].lower()
        if ext in IMAGE_EXTS and PIL_AVAILABLE:
            try:
                img = Image.open(path)
                img.thumbnail((420, 280))
                pm = pil_to_pixmap(img)
                img.close()
                return pm
            except Exception as e:
                log(f"❌ Thumb error {os.path.basename(path)}: {e}")
        return None

    def trim_video_cache(self):
        """Keep a few videos' frames around (going back and forth between rows is common),
        but drop the temp jpgs once the cache grows."""
        if len(self.video_frame_cache) <= VIDEO_CACHE_MAX:
            return
        self.cleanup_dup_temp()

    def cleanup_dup_temp(self):
        """Frames no longer displayed -> delete from !temp"""
        self.slide_timer.stop()
        self.slide_frames = [[], []]
        self.video_frame_cache = {}
        self.hash_cache = {}
        for f in self.dup_temp_files:
            try:
                os.remove(f)
            except Exception:
                pass
        self.dup_temp_files = []

    def scan_duplicates(self):
        base = self.base_path
        if not os.path.isdir(base):
            log(f"❌ Camera folder not found: {base}")
            return
        self.statusBar().showMessage("🔍 Scan des doublons…")
        QApplication.processEvents()

        # Full rebuild: wipe the table, the preview and the temp thumbnails
        self.stop_background_compare()
        self.compare_results = {}
        self.cleanup_dup_temp()
        self.dup_table.clearSelection()
        self.dup_table.setSortingEnabled(False)   # re-enabled once the rows are in
        self.dup_table.setRowCount(0)
        self.current_dup_row = None
        self.update_dup_preview()

        file_index = {}
        screenshot_folders = set()
        organized_folders = set()
        suffix_dupes = []  # (copy_filename, copy_path, original_path, same_size)

        for item in os.listdir(base):
            item_path = os.path.join(base, item)
            if not os.path.isdir(item_path) or not re.match(r'^\d{4}$', item):
                continue
            for folder in os.listdir(item_path):
                folder_path = os.path.join(item_path, folder)
                if not os.path.isdir(folder_path):
                    continue
                if folder.startswith('!Screenshot') or folder.startswith('!ScreenRecorder'):
                    screenshot_folders.add(folder_path)
                elif not folder.startswith('!'):
                    organized_folders.add(folder_path)
                local = {}
                try:
                    for filename in os.listdir(folder_path):
                        filepath = os.path.join(folder_path, filename)
                        if os.path.isfile(filepath):
                            file_index.setdefault(filename, []).append(filepath)
                            local[filename] = filepath
                except Exception as e:
                    log(f"❌ Error scanning {folder_path}: {e}")
                # Same-folder copies: 'x_1.ext', 'x (1).ext', 'x - Copie.ext'... next to 'x.ext'
                for filename, filepath in local.items():
                    original = copy_original_name(filename)
                    if not original or original not in local:
                        continue
                    try:
                        same_size = os.path.getsize(filepath) == os.path.getsize(local[original])
                    except OSError:
                        continue
                    suffix_dupes.append((filename, filepath, local[original], same_size))

        auto_count = conflict_count = 0
        for filename, paths in sorted(file_index.items()):
            if len(paths) < 2:
                continue
            screenshot_paths = [p for p in paths if any(p.startswith(sf) for sf in screenshot_folders)]
            organized_paths = [p for p in paths if any(p.startswith(of) for of in organized_folders)]

            if screenshot_paths and organized_paths:
                if self.is_ignored(filename, [organized_paths[0]], screenshot_paths):
                    continue
                self.add_dup_row(filename, '🔄 Auto', [organized_paths[0]], screenshot_paths,
                                 COLOR_AUTO)
                auto_count += 1
            elif len(organized_paths) >= 2:
                if self.is_ignored(filename, [organized_paths[0]], organized_paths[1:]):
                    continue
                self.add_dup_row(filename, '⚠️ Conflit', [organized_paths[0]], organized_paths[1:],
                                 COLOR_CONFLICT)
                conflict_count += 1

        suffix_count = copy_doubt_count = 0
        for filename, filepath, orig_path, same_size in suffix_dupes:
            if self.is_ignored(filename, [orig_path], [filepath]):
                continue
            if same_size:
                # Copy marker + identical size: safe to batch-process
                self.add_dup_row(filename, '🔄 Suffixe', [orig_path], [filepath], COLOR_AUTO)
                suffix_count += 1
            else:
                # Looks like a copy but the sizes differ -> never touched automatically
                self.add_dup_row(filename, '⚠️ Copie ?', [orig_path], [filepath], COLOR_CONFLICT)
                copy_doubt_count += 1

        self.dup_table.setSortingEnabled(True)
        self.refresh_dup_summary()
        self.statusBar().showMessage(
            f"🔍 Doublons : {auto_count + suffix_count} déplaçables, "
            f"{conflict_count + copy_doubt_count} à vérifier"
            + (f"   |   🙈 {len(self.ignore_list)} ignoré(s)" if self.ignore_list else ""))
        log(f"Duplicate scan: {auto_count} auto-movable, {suffix_count} suffix copies, "
            f"{conflict_count} conflicts, {copy_doubt_count} copies with a different size")
        # Score everything in the background: the column fills itself while you work
        self.start_background_compare()

    def add_dup_row(self, filename, kind, paths1, paths2, color):
        base = self.base_path
        row = self.dup_table.rowCount()
        self.dup_table.insertRow(row)
        texts = [filename, kind, "…",
                 "; ".join(os.path.relpath(p, base) for p in paths1),
                 "; ".join(os.path.relpath(p, base) for p in paths2)]
        for col, text in enumerate(texts):
            # Score sorts on its numeric value, not on its emoji
            it = SortableItem(text, -1.0) if col == 2 else QTableWidgetItem(text)
            it.setFlags(it.flags() & ~Qt.ItemFlag.ItemIsEditable)
            it.setBackground(color)
            self.dup_table.setItem(row, col, it)
        self.dup_table.item(row, 3).setData(Qt.ItemDataRole.UserRole, list(paths1))
        self.dup_table.item(row, 4).setData(Qt.ItemDataRole.UserRole, list(paths2))
        # Stable id: rows shift as they are deleted, background results arrive later
        self.row_token += 1
        self.dup_table.item(row, 0).setData(Qt.ItemDataRole.UserRole, self.row_token)
        self.dup_table.item(row, 2).setTextAlignment(Qt.AlignmentFlag.AlignCenter)

    def trash_paths(self, paths):
        """Send files to recycle bin. Returns (trashed, errors)"""
        n = errors = 0
        for p in paths:
            try:
                from send2trash import send2trash
                send2trash(os.path.normpath(p))
                log(f"🗑️ Corbeille: {os.path.relpath(p, self.base_path)}")
                n += 1
            except Exception as e:
                log(f"❌ Erreur corbeille {os.path.basename(p)}: {e}")
                errors += 1
        return n, errors

    def trash_rows_side(self, rows, side):
        """Send the given side (0 = Copie 1, 1 = Copie 2) of each row to the recycle bin.
        Rows fully processed are removed from the table."""
        trashed = errors = skipped = 0
        todo = sorted(rows, reverse=True)
        # Block selection signals: removeRow() would otherwise rebuild the preview
        # (and regenerate video thumbnails) once per deleted row.
        self.dup_table.blockSignals(True)
        try:
            for i, row in enumerate(todo):
                paths = self.dup_table.item(row, 3 + side).data(Qt.ItemDataRole.UserRole) or []
                existing = [p for p in paths if os.path.isfile(p)]
                if not existing:
                    # Nothing left on disk: the row is stale, drop it
                    self.dup_table.removeRow(row)
                    skipped += 1
                    continue
                t, e = self.trash_paths(existing)
                trashed += t
                errors += e
                if e == 0:
                    self.dup_table.removeRow(row)
                if len(todo) > 20 and i % 20 == 0:
                    self.statusBar().showMessage(f"🗑️ Corbeille… {i + 1}/{len(todo)}")
                    QApplication.processEvents()
        finally:
            self.dup_table.blockSignals(False)
        self.refresh_dup_summary()
        # Jump straight to the next row so you can chain deletions without re-clicking
        self.select_dup_row(min(todo) if todo else 0)
        msg = f"🗑️ {trashed} fichier(s) à la corbeille (Copie {side + 1})"
        if skipped:
            msg += f", {skipped} ligne(s) obsolète(s) retirée(s)"
        if errors:
            msg += f", {errors} erreur(s)"
        log(f"Traitement doublons: {msg}")
        self.statusBar().showMessage(msg)
        return trashed, errors

    def process_auto(self):
        """Batch: every 🔄 Auto / 🔄 Suffixe row -> Copie 2 to recycle bin"""
        # A row the comparison flagged as visually different is never batch-deleted,
        # even if its name says "copy".
        rows = [r for r in range(self.dup_table.rowCount())
                if self.dup_table.item(r, 1).text().startswith('🔄')
                and '🔴' not in self.dup_table.item(r, 2).text()
                and '🟠' not in self.dup_table.item(r, 2).text()]
        skipped = sum(1 for r in range(self.dup_table.rowCount())
                      if self.dup_table.item(r, 1).text().startswith('🔄')) - len(rows)
        if not rows:
            self.statusBar().showMessage("Aucune ligne 🔄 Auto/Suffixe à traiter")
            return
        n_files = sum(len(self.dup_table.item(r, 4).data(Qt.ItemDataRole.UserRole) or [])
                      for r in rows)
        if QMessageBox.question(
                self, "Confirmer",
                f"Envoyer à la corbeille la Copie 2 de {len(rows)} ligne(s) 🔄 Auto/Suffixe "
                f"({n_files} fichier(s)) ?\n\nLes ⚠️ Conflits ne sont pas touchés."
                + (f"\n{skipped} ligne(s) écartée(s) : le contenu ne correspond pas (🟠/🔴)."
                   if skipped else ""),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No) != QMessageBox.StandardButton.Yes:
            return
        self.trash_rows_side(rows, 1)

    def trash_side(self, side):
        """Send the chosen side of every selected row to the recycle bin"""
        rows = self.selected_dup_rows()
        if not rows:
            self.statusBar().showMessage("Sélectionne au moins une ligne d'abord")
            return
        if len(rows) > 1:
            n_files = sum(len(self.dup_table.item(r, 3 + side).data(Qt.ItemDataRole.UserRole) or [])
                          for r in rows)
            if QMessageBox.question(
                    self, "Confirmer",
                    f"Envoyer à la corbeille la Copie {side + 1} de {len(rows)} ligne(s) "
                    f"({n_files} fichier(s)) ?",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.No) != QMessageBox.StandardButton.Yes:
                return
        self.trash_rows_side(rows, side)

    def open_side(self, side):
        """Unit action: open the folder of the displayed copy"""
        row = self.current_dup_row
        if row is None or row >= self.dup_table.rowCount():
            return
        paths = self.dup_table.item(row, 3 + side).data(Qt.ItemDataRole.UserRole) or []
        if paths:
            folder = os.path.dirname(paths[0])
            if os.path.isdir(folder):
                os.startfile(folder)

    def pair_key(self, paths1, paths2):
        """Identity of a duplicate pair, stable across scans and persisted to disk"""
        base = self.base_path
        a = os.path.relpath(paths1[0], base) if paths1 else ''
        b = os.path.relpath(paths2[0], base) if paths2 else ''
        return f"{a} || {b}"

    def is_ignored(self, filename, paths1, paths2):
        """Ignored pairs are remembered between sessions. Bare filenames are still
        honoured so the lists saved by earlier versions keep working."""
        return (filename in self.ignore_list
                or self.pair_key(paths1, paths2) in self.ignore_list)

    def forget_ignored(self):
        n = len(self.ignore_list)
        if not n:
            self.statusBar().showMessage("Aucun doublon ignoré")
            return
        if QMessageBox.question(
                self, "Doublons ignorés",
                f"Oublier les {n} doublon(s) ignoré(s) ?\nIls réapparaîtront au prochain scan.",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No) != QMessageBox.StandardButton.Yes:
            return
        self.ignore_list = set()
        save_json(IGNORE_FILE, [])
        log(f"♻️ Liste des doublons ignorés vidée ({n} entrée(s))")
        self.statusBar().showMessage(f"♻️ {n} doublon(s) ignoré(s) oublié(s) — relance le scan")

    def ignore_duplicates(self):
        rows = sorted(self.selected_dup_rows(), reverse=True)
        count = 0
        self.dup_table.blockSignals(True)
        try:
            for row in rows:
                filename = self.dup_table.item(row, 0).text()
                paths1, paths2 = self.row_path_lists(row)
                key = self.pair_key(paths1, paths2)
                self.ignore_list.add(key)
                log(f"🙈 Doublon ignoré: {key}")
                self.dup_table.removeRow(row)
                count += 1
        finally:
            self.dup_table.blockSignals(False)
        self.refresh_dup_summary()
        self.select_dup_row(min(rows) if rows else 0)
        if count:
            save_json(IGNORE_FILE, sorted(self.ignore_list))
            self.statusBar().showMessage(f"🙈 {count} fichier(s) ignoré(s)")

    # ----- Tab 3: sort media -----

    def build_sort_tab(self):
        w = QWidget()
        layout = QVBoxLayout(w)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        layout.addWidget(splitter, stretch=1)

        # Left: file table
        left = QWidget()
        lv = QVBoxLayout(left)
        lv.setContentsMargins(0, 0, 0, 0)
        # Which pool of files we are sorting
        source_bar = QHBoxLayout()
        source_bar.setContentsMargins(0, 0, 0, 0)
        source_bar.addWidget(QLabel("📂 Source :"))
        self.source_group = QButtonGroup(self)
        self.source_group.setExclusive(True)
        for i, (label, prefix) in enumerate(SORT_SOURCES):
            rb = QRadioButton(label)
            rb.setToolTip("Fichiers en vrac à la racine de Camera" if not prefix
                          else f"Médias parqués dans les dossiers {prefix}ANNÉE")
            if i == 0:
                rb.setChecked(True)
            self.source_group.addButton(rb, i)
            source_bar.addWidget(rb)
        source_bar.addStretch(1)
        self.source_group.idToggled.connect(
            lambda idx, checked: checked and self.on_sort_source_changed(idx))
        lv.addLayout(source_bar)
        lv.addWidget(QLabel("📋 Fichiers à trier (double-clic sur l'année pour corriger)"))
        self.file_table = QTableWidget(0, 4)
        self.file_table.setHorizontalHeaderLabels(
            ["Fichier", "Date et heure", "Année", "Dossier"])
        self.file_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.file_table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.file_table.setEditTriggers(QAbstractItemView.EditTrigger.DoubleClicked)
        self.file_table.verticalHeader().setVisible(False)
        setup_header(self.file_table, [380, 150, 60, 260])
        self.file_table.itemSelectionChanged.connect(self.on_file_selection)
        self.file_table.itemChanged.connect(self.on_file_item_changed)
        QShortcut(QKeySequence(Qt.Key.Key_Delete), self.file_table,
                  activated=self.delete_selected, context=Qt.ShortcutContext.WidgetShortcut)
        lv.addWidget(self.file_table)
        splitter.addWidget(left)

        # Middle: folders
        mid = QWidget()
        mv = QVBoxLayout(mid)
        mv.setContentsMargins(0, 0, 0, 0)
        self.folders_label = QLabel("📁 Dossiers")
        mv.addWidget(self.folders_label)
        self.folder_list = QListWidget()
        self.folder_list.itemClicked.connect(self.on_folder_clicked)
        self.folder_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.folder_list.customContextMenuRequested.connect(self.folder_context_menu)
        self.folder_list.setToolTip("Clic : assigner la sélection   |   Clic droit : renommer / ouvrir")
        mv.addWidget(self.folder_list, stretch=1)
        mv.addWidget(QLabel("✨ Nouveau dossier :"))
        self.new_folder_edit = QLineEdit()
        self.new_folder_edit.returnPressed.connect(self.create_new_folder)
        mv.addWidget(self.new_folder_edit)
        b_create = QPushButton("Créer et assigner")
        b_create.clicked.connect(self.create_new_folder)
        mv.addWidget(b_create)
        splitter.addWidget(mid)

        # Right: viewer
        right = QWidget()
        rv = QVBoxLayout(right)
        rv.setContentsMargins(0, 0, 0, 0)
        rv.addWidget(QLabel("🖼️ Aperçu (Ctrl+molette = zoom)"))
        self.viewer_scroll = QScrollArea()
        self.viewer_scroll.setWidgetResizable(True)
        self.viewer_label = QLabel("")
        self.viewer_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.viewer_label.setStyleSheet("background-color: #1a1a1c; color: #cccccc;")
        self.viewer_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Ignored)
        self.viewer_scroll.setWidget(self.viewer_label)
        self.viewer_scroll.viewport().installEventFilter(self)
        rv.addWidget(self.viewer_scroll, stretch=1)

        # Video controls: one radio per sampling point, named rather than numbered
        self.video_bar = QWidget()
        vb = QHBoxLayout(self.video_bar)
        vb.setContentsMargins(0, 6, 0, 0)
        vb.setSpacing(10)
        vb.addWidget(QLabel("🎬 Position :"))
        self.video_buttons = []
        self.video_group = QButtonGroup(self)
        self.video_group.setExclusive(True)
        for i, pct in enumerate(VIDEO_PERCENTS):
            label = "Début" if pct == 0 else "Fin" if pct >= 100 else f"{pct} %"
            b = QRadioButton(label)
            b.setToolTip(f"Image à {pct} % de la durée")
            b.toggled.connect(lambda checked, idx=i: checked and self.show_video_percent(idx))
            self.video_group.addButton(b, i)
            vb.addWidget(b)
            self.video_buttons.append(b)
        vb.addStretch(1)
        b_play = QPushButton("▶️ Lire la vidéo")
        b_play.clicked.connect(self.play_current_video)
        vb.addWidget(b_play)
        self.video_bar.setVisible(False)
        rv.addWidget(self.video_bar)

        self.file_label = QLabel("")
        self.file_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        rv.addWidget(self.file_label)
        splitter.addWidget(right)

        splitter.setSizes([560, 260, 640])

        # Action buttons
        actions = QHBoxLayout()
        b_auto = QPushButton("⚡ Ranger Screens/Recorder/Pictures")
        b_auto.clicked.connect(self.run_auto_organize)
        actions.addWidget(b_auto)
        b_apply = QPushButton("✅ APPLIQUER les déplacements")
        b_apply.clicked.connect(self.apply_moves)
        actions.addWidget(b_apply)
        b_delete = QPushButton("🗑️ Supprimer (corbeille)")
        b_delete.clicked.connect(self.delete_selected)
        actions.addWidget(b_delete)
        b_apps = QPushButton("🗂️ Ranger par appli")
        b_apps.setToolTip("Range les captures d'écran de la source affichée dans des\n"
                          "sous-dossiers portant le nom de l'application (WhatsApp, Brave…).")
        b_apps.clicked.connect(self.sort_by_app)
        actions.addWidget(b_apps)
        b_reset = QPushButton("❌ Recharger")
        b_reset.clicked.connect(self.scan_media)
        actions.addWidget(b_reset)
        actions.addStretch(1)
        layout.addLayout(actions)
        return w

    # ----- Tab 4: viewer -----

    def build_viewer_tab(self):
        w = QWidget()
        layout = QVBoxLayout(w)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        layout.addWidget(splitter, stretch=1)

        # Column 1: years
        left = QWidget()
        lv = QVBoxLayout(left)
        lv.setContentsMargins(0, 0, 0, 0)
        lv.addWidget(QLabel("📅 Années"))
        self.viewer_years = QListWidget()
        self.viewer_years.currentItemChanged.connect(self.on_viewer_year)
        lv.addWidget(self.viewer_years, stretch=1)
        b_refresh = QPushButton("🔄 Rafraîchir")
        b_refresh.clicked.connect(self.refresh_viewer_years)
        lv.addWidget(b_refresh)
        splitter.addWidget(left)

        # Column 2: folders of that year
        mid = QWidget()
        mv = QVBoxLayout(mid)
        mv.setContentsMargins(0, 0, 0, 0)
        self.viewer_folders_label = QLabel("📁 Dossiers")
        mv.addWidget(self.viewer_folders_label)
        self.viewer_folders = QListWidget()
        self.viewer_folders.currentItemChanged.connect(self.on_viewer_folder)
        self.viewer_folders.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.viewer_folders.customContextMenuRequested.connect(self.viewer_folder_menu)
        mv.addWidget(self.viewer_folders, stretch=1)
        splitter.addWidget(mid)

        # Column 3: thumbnails
        right = QWidget()
        rv = QVBoxLayout(right)
        rv.setContentsMargins(0, 0, 0, 0)
        self.viewer_count = QLabel("🖼️ Sélectionne un dossier")
        rv.addWidget(self.viewer_count)
        self.viewer_grid = QListWidget()
        self.viewer_grid.setViewMode(QListWidget.ViewMode.IconMode)
        self.viewer_grid.setIconSize(QSize(THUMB_W, THUMB_H))
        self.viewer_grid.setGridSize(QSize(THUMB_W + 18, THUMB_H + 42))
        self.viewer_grid.setResizeMode(QListWidget.ResizeMode.Adjust)
        self.viewer_grid.setMovement(QListWidget.Movement.Static)
        self.viewer_grid.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.viewer_grid.setWordWrap(True)
        self.viewer_grid.setUniformItemSizes(True)
        self.viewer_grid.setSpacing(2)
        self.viewer_grid.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.viewer_grid.customContextMenuRequested.connect(self.viewer_grid_menu)
        self.viewer_grid.itemSelectionChanged.connect(self.on_viewer_selection)
        self.viewer_grid.itemDoubleClicked.connect(lambda _it: self.viewer_open())
        QShortcut(QKeySequence(Qt.Key.Key_Delete), self.viewer_grid,
                  activated=self.viewer_delete, context=Qt.ShortcutContext.WidgetShortcut)
        QShortcut(QKeySequence(Qt.Key.Key_F2), self.viewer_grid,
                  activated=self.viewer_rename, context=Qt.ShortcutContext.WidgetShortcut)
        rv.addWidget(self.viewer_grid, stretch=1)
        splitter.addWidget(right)
        splitter.setSizes([150, 280, 900])

        # Bottom: chronological timeline
        self.viewer_timeline = Timeline()
        self.viewer_timeline.picked.connect(self.on_timeline_picked)
        layout.addWidget(self.viewer_timeline)

        actions = QHBoxLayout()
        for label, slot in (("✏️ Renommer (F2)", self.viewer_rename),
                            ("▶️ Ouvrir", self.viewer_open),
                            ("📂 Ouvrir le dossier", self.viewer_open_folder),
                            ("🗑️ Supprimer (Suppr)", self.viewer_delete)):
            b = QPushButton(label)
            b.clicked.connect(slot)
            actions.addWidget(b)
        actions.addStretch(1)
        self.year_view_check = QCheckBox("📅 Vue année entière (01/01 → 31/12)")
        self.year_view_check.setToolTip(
            "Étale la frise sur l'année complète : on voit tout de suite si les photos\n"
            "sont concentrées en début ou en fin d'année.")
        self.year_view_check.toggled.connect(self.on_year_view_toggled)
        actions.addWidget(self.year_view_check)
        layout.addLayout(actions)

        self.viewer_media = []          # [(path, datetime), ...] in display order
        return w

    def on_tab_changed(self, index):
        if self.tabs.tabText(index).startswith("4") and self.viewer_years.count() == 0:
            self.refresh_viewer_years()

    def refresh_viewer_years(self):
        self.viewer_years.clear()
        self.viewer_folders.clear()
        self.viewer_grid.clear()
        self.viewer_timeline.set_points([])
        base = self.base_path
        if not os.path.isdir(base):
            return
        years = sorted((d for d in os.listdir(base)
                        if os.path.isdir(os.path.join(base, d)) and re.match(r'^\d{4}$', d)),
                       reverse=True)
        for y in years:
            self.viewer_years.addItem(QListWidgetItem(y))
        if years:
            self.viewer_years.setCurrentRow(0)

    def on_viewer_year(self, current, _previous=None):
        self.viewer_folders.clear()
        self.viewer_grid.clear()
        self.viewer_timeline.set_points([])
        if current is None:
            return
        year = current.text()
        self.viewer_folders_label.setText(f"📁 Dossiers {year}")
        year_dir = os.path.join(self.base_path, year)
        if not os.path.isdir(year_dir):
            return
        for folder in sorted(os.listdir(year_dir)):
            if not os.path.isdir(os.path.join(year_dir, folder)) or folder.startswith('!'):
                continue
            it = QListWidgetItem(folder)
            it.setBackground(folder_color(folder))
            self.viewer_folders.addItem(it)

    def viewer_current_folder(self):
        year_it = self.viewer_years.currentItem()
        folder_it = self.viewer_folders.currentItem()
        if not year_it or not folder_it:
            return None
        return os.path.join(self.base_path, year_it.text(), folder_it.text())

    def on_viewer_folder(self, current, _previous=None):
        self.viewer_grid.clear()
        self.viewer_media = []
        self.thumb_rows = {}
        self.viewer_timeline.set_points([])
        folder = self.viewer_current_folder()
        if not folder or not os.path.isdir(folder):
            return
        names = sorted((f for f in os.listdir(folder)
                        if os.path.splitext(f)[1].lower() in (IMAGE_EXTS | VIDEO_EXTS)
                        and os.path.isfile(os.path.join(folder, f))),
                       key=str.lower)                      # alphabetical, as asked
        placeholder = QIcon(self.empty_thumb())
        cell = QSize(THUMB_W + 14, THUMB_H + 38)
        self.viewer_grid.setUpdatesEnabled(False)
        pending = []
        for name in names:
            path = os.path.join(folder, name)
            it = QListWidgetItem(placeholder, name)
            it.setData(Qt.ItemDataRole.UserRole, path)     # a str: safe through Qt
            it.setToolTip(path)
            it.setSizeHint(cell)                           # fixed cell = aligned grid
            it.setTextAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignBottom)
            self.viewer_grid.addItem(it)
            self.thumb_rows[path] = self.viewer_grid.count() - 1
            self.viewer_media.append((path, file_datetime(name, path)))
            cached = self.thumb_cache.get(path)
            if cached is not None:
                it.setIcon(QIcon(cached))
            else:
                pending.append(path)
        self.viewer_grid.setUpdatesEnabled(True)
        if pending:
            self.thumb_pool.submit(pending)
        year_item = self.viewer_years.currentItem()
        self.viewer_count.setText(f"🖼️ {len(names)} média(s) — {os.path.basename(folder)}")
        self.viewer_timeline.set_points(
            [(dt, os.path.basename(p)) for p, dt in self.viewer_media],
            year=year_item.text() if year_item else None)

    def empty_thumb(self):
        """Uniform placeholder so every cell has the same size from the start"""
        if getattr(self, '_empty_thumb', None) is None:
            pm = QPixmap(THUMB_W, THUMB_H)
            pm.fill(QColor('#232428'))
            self._empty_thumb = pm
        return self._empty_thumb

    def framed_thumb(self, qimage):
        """Center the image on a fixed canvas: identical icons, perfect alignment"""
        pm = QPixmap(THUMB_W, THUMB_H)
        pm.fill(QColor('#1a1a1c'))
        scaled = QPixmap.fromImage(qimage).scaled(
            THUMB_W, THUMB_H, Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation)
        painter = QPainter(pm)
        painter.drawPixmap((THUMB_W - scaled.width()) // 2,
                           (THUMB_H - scaled.height()) // 2, scaled)
        painter.end()
        return pm

    def on_thumb_ready(self, path, qimage):
        """Thumbnails arrive out of order: find the item that asked for this one"""
        if qimage is None:
            return
        pm = self.framed_thumb(qimage)
        self.thumb_cache[path] = pm
        while len(self.thumb_cache) > THUMB_CACHE_MAX:
            self.thumb_cache.popitem(last=False)
        row = self.thumb_rows.get(path)
        if row is not None and row < self.viewer_grid.count():
            it = self.viewer_grid.item(row)
            if it is not None and it.data(Qt.ItemDataRole.UserRole) == path:
                it.setIcon(QIcon(pm))
                return
        for row in range(self.viewer_grid.count()):     # rows moved (a deletion)
            it = self.viewer_grid.item(row)
            if it.data(Qt.ItemDataRole.UserRole) == path:
                it.setIcon(QIcon(pm))
                return

    def on_year_view_toggled(self, checked):
        year_item = self.viewer_years.currentItem()
        self.viewer_timeline.set_year_mode(checked,
                                           year_item.text() if year_item else None)

    def rebuild_timeline(self):
        """Timeline always mirrors the grid, in the same order"""
        known = dict(self.viewer_media)
        media = []
        for row in range(self.viewer_grid.count()):
            path = self.viewer_grid.item(row).data(Qt.ItemDataRole.UserRole)
            dt = known.get(path) or file_datetime(os.path.basename(path), path)
            media.append((path, dt))
        self.viewer_media = media
        year_item = self.viewer_years.currentItem()
        self.viewer_timeline.set_points([(dt, os.path.basename(p)) for p, dt in media],
                                        year=year_item.text() if year_item else None)

    def on_viewer_selection(self):
        rows = [i.row() for i in self.viewer_grid.selectedIndexes()]
        self.viewer_timeline.set_selected(rows[0] if rows else -1)

    def on_timeline_picked(self, index):
        if 0 <= index < self.viewer_grid.count():
            self.viewer_grid.setCurrentRow(index)
            self.viewer_grid.scrollToItem(self.viewer_grid.item(index),
                                          QAbstractItemView.ScrollHint.EnsureVisible)

    def viewer_selected_paths(self):
        return [it.data(Qt.ItemDataRole.UserRole) for it in self.viewer_grid.selectedItems()]

    def viewer_grid_menu(self, pos):
        it = self.viewer_grid.itemAt(pos)
        if it is None:
            return
        if it not in self.viewer_grid.selectedItems():
            self.viewer_grid.setCurrentItem(it)
        menu = QMenu(self)
        single = len(self.viewer_grid.selectedItems()) == 1
        act = menu.addAction("✏️ Renommer…")
        act.setEnabled(single)
        act.triggered.connect(self.viewer_rename)
        menu.addAction("▶️ Ouvrir").triggered.connect(self.viewer_open)
        menu.addAction("📂 Ouvrir le dossier").triggered.connect(self.viewer_open_folder)
        menu.addSeparator()
        menu.addAction("🗑️ Supprimer (corbeille)").triggered.connect(self.viewer_delete)
        menu.exec(self.viewer_grid.viewport().mapToGlobal(pos))

    def viewer_folder_menu(self, pos):
        it = self.viewer_folders.itemAt(pos)
        if it is None:
            return
        self.viewer_folders.setCurrentItem(it)
        menu = QMenu(self)
        menu.addAction("📂 Ouvrir le dossier").triggered.connect(
            lambda: os.startfile(self.viewer_current_folder()))
        menu.exec(self.viewer_folders.viewport().mapToGlobal(pos))

    def viewer_open(self):
        for path in self.viewer_selected_paths()[:5]:
            if path and os.path.isfile(path):
                try:
                    os.startfile(path)
                except Exception as e:
                    log(f"❌ Ouverture {os.path.basename(path)}: {e}")

    def viewer_open_folder(self):
        folder = self.viewer_current_folder()
        if folder and os.path.isdir(folder):
            os.startfile(folder)

    def viewer_rename(self):
        items = self.viewer_grid.selectedItems()
        if len(items) != 1:
            self.statusBar().showMessage("Sélectionne un seul média pour le renommer")
            return
        it = items[0]
        old = it.data(Qt.ItemDataRole.UserRole)
        if not old or not os.path.isfile(old):
            return
        folder, current = os.path.split(old)
        new_name, ok = QInputDialog.getText(self, "Renommer", "Nouveau nom :", text=current)
        new_name = (new_name or '').strip()
        if not ok or not new_name or new_name == current:
            return
        new_path = os.path.join(folder, new_name)
        if os.path.exists(new_path):
            QMessageBox.warning(self, "Renommer", f"« {new_name} » existe déjà ici.")
            return
        try:
            os.rename(old, new_path)
        except Exception as e:
            log(f"❌ Renommage {current}: {e}")
            QMessageBox.warning(self, "Renommer", f"Échec du renommage :\n{e}")
            return
        log(f"✏️ Renommé: {current} -> {new_name}")
        it.setText(new_name)
        it.setData(Qt.ItemDataRole.UserRole, new_path)
        it.setToolTip(new_path)
        row = self.viewer_grid.row(it)
        if 0 <= row < len(self.viewer_media):
            self.viewer_media[row] = (new_path, self.viewer_media[row][1])
        self.statusBar().showMessage(f"✏️ Renommé en « {new_name} »")

    def viewer_delete(self):
        items = self.viewer_grid.selectedItems()
        if not items:
            return
        if len(items) > 1 and QMessageBox.question(
                self, "Supprimer",
                f"Envoyer {len(items)} média(s) à la corbeille ?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No) != QMessageBox.StandardButton.Yes:
            return
        next_row = min(self.viewer_grid.row(it) for it in items)
        deleted = errors = 0
        for it in items:
            path = it.data(Qt.ItemDataRole.UserRole)
            try:
                from send2trash import send2trash
                send2trash(os.path.normpath(path))
                log(f"🗑️ Corbeille: {os.path.relpath(path, self.base_path)}")
                self.viewer_grid.takeItem(self.viewer_grid.row(it))
                deleted += 1
            except Exception as e:
                log(f"❌ Suppression {os.path.basename(path or '?')}: {e}")
                errors += 1
        self.rebuild_timeline()
        self.viewer_count.setText(f"🖼️ {self.viewer_grid.count()} média(s)")
        if self.viewer_grid.count():
            self.viewer_grid.setCurrentRow(min(next_row, self.viewer_grid.count() - 1))
        self.statusBar().showMessage(f"🗑️ {deleted} média(s) à la corbeille"
                                     + (f", {errors} erreur(s)" if errors else ""))

    # ---------- Startup / scan ----------

    def startup_load(self):
        base = self.base_path
        if not base or not os.path.isdir(base):
            log(f"❌ Camera folder not found: {base}")
            self.statusBar().showMessage(f"❌ Dossier introuvable : {base}")
            return
        self.video_cache_dir = os.path.join(base, '!tempvideoscreen')
        self.purge_video_cache()
        if self.config.get('pcloud_autoimport', True):
            try:
                self.import_pcloud(silent=True)     # before the scans read the folders
            except Exception as e:
                log(f"[PCLOUD] ❌ Import: {e}")
        try:
            self.analyze_renames()
        except Exception as e:
            log(f"❌ Rename analysis error: {e}")
        self.scan_media()

    def scan_media(self):
        base = self.base_path
        if not os.path.isdir(base):
            return
        log("[SCAN] ========== Starting folder scan ==========")
        self.statusBar().showMessage("🔄 Scan en cours…")
        QApplication.processEvents()

        edits = load_json(EDITS_FILE, {})
        self.files = []
        prefix = self.sort_prefix()
        for filename, filepath, forced_year, here in self.iter_source_files(prefix):
            ext = os.path.splitext(filename)[1].lower()
            if ext not in (IMAGE_EXTS | VIDEO_EXTS):
                continue
            year = forced_year
            if not year:
                m = re.search(r'(20\d{2})', filename)
                if m:
                    year = m.group(1)
                else:
                    year = get_year_from_file(filename, filepath) or ''
                    if year:
                        log(f"[SCAN] Year from EXIF/date for {filename}: {year}")
            dt = file_datetime(filename, filepath)
            self.files.append({
                'filename': filename, 'filepath': filepath, 'ext': ext,
                'datetime': dt, 'year': year,
                # 'here' = sub-folder it already sits in, shown as its current folder
                'folder': edits.get(filename, here)
            })
        # Chronological, photos and videos mixed together
        self.files.sort(key=lambda x: (x['datetime'] or datetime.min, x['filename']))
        log(f"[SCAN] Files to organize: {len(self.files)}")
        self.fill_file_table()
        self.statusBar().showMessage(f"🔄 {len(self.files)} fichier(s) à trier")

    def sort_prefix(self):
        """Prefix of the year sub-folder currently being sorted ('' = Camera root)"""
        index = getattr(self, 'sort_source_index', 0)
        return SORT_SOURCES[index][1] if 0 <= index < len(SORT_SOURCES) else ''

    def iter_source_files(self, prefix):
        """Yield (filename, filepath, year, current_subfolder) for the chosen source.

        prefix == ''  -> loose files at the root of Camera, year unknown
        otherwise     -> everything under Camera\\YEAR\\<prefix>YEAR\\, including its
                         sub-folders; the year comes from the folder it sits in."""
        base = self.base_path
        if not prefix:
            for filename in sorted(os.listdir(base)):
                path = os.path.join(base, filename)
                if not os.path.isdir(path):
                    yield filename, path, '', ''
            return
        for year in sorted(os.listdir(base)):
            year_dir = os.path.join(base, year)
            if not os.path.isdir(year_dir) or not re.match(r'^\d{4}$', year):
                continue
            bucket = os.path.join(year_dir, f"{prefix}{year}")
            if not os.path.isdir(bucket):
                continue
            for current, _dirs, files in os.walk(bucket):
                rel = os.path.relpath(current, year_dir)
                for filename in sorted(files):
                    # 'rel' is relative to the year, so it can be reused as a folder value
                    yield filename, os.path.join(current, filename), year, rel

    def on_sort_source_changed(self, index):
        if index == getattr(self, 'sort_source_index', 0):
            return
        self.sort_source_index = index
        log(f"[SCAN] Source de tri: {SORT_SOURCES[index][0]}")
        self.scan_media()

    def fill_file_table(self):
        self._filling = True
        self.file_table.setSortingEnabled(False)
        self.file_table.setRowCount(0)
        self.files_by_uid = {}
        for index, info in enumerate(self.files):
            row = self.file_table.rowCount()
            self.file_table.insertRow(row)
            it_name = QTableWidgetItem(info['filename'])
            # The row carries the entry's uid, NOT the dict itself: PySide converts a
            # Python dict to a QVariantMap, so reading it back gives a *copy* and every
            # edit made through the row would be silently lost.
            info.setdefault('uid', id(info))
            self.files_by_uid[info['uid']] = info
            it_name.setData(Qt.ItemDataRole.UserRole, int(info['uid']))
            it_name.setFlags(it_name.flags() & ~Qt.ItemFlag.ItemIsEditable)
            dt = info['datetime']
            # Sorts on the real timestamp, not on the displayed text
            it_dt = SortableItem(dt.strftime('%Y-%m-%d %H:%M:%S') if dt else '—',
                                 dt or datetime.min)
            it_dt.setFlags(it_dt.flags() & ~Qt.ItemFlag.ItemIsEditable)
            it_year = QTableWidgetItem(info['year'])
            it_folder = QTableWidgetItem(info['folder'])
            it_folder.setFlags(it_folder.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.file_table.setItem(row, 0, it_name)
            self.file_table.setItem(row, 1, it_dt)
            self.file_table.setItem(row, 2, it_year)
            self.file_table.setItem(row, 3, it_folder)
            self.update_row_dest(row)
            self.apply_row_color(row)
        self._filling = False
        self.file_table.setSortingEnabled(True)
        self.apply_saved_sort('files', self.file_table, 1)   # 1 = Date et heure
        if self.files:
            self.file_table.selectRow(0)
        self.start_prefetch()

    def finfo(self, row):
        """The real entry attached to a row - the same object as in self.files, so
        editing it actually changes what gets moved. Rows move (sorting) and vanish
        (deletion), so nothing here may rely on row numbers."""
        it = self.file_table.item(row, 0) if 0 <= row < self.file_table.rowCount() else None
        uid = it.data(Qt.ItemDataRole.UserRole) if it else None
        info = self.files_by_uid.get(uid) if uid is not None else None
        if info is not None:
            return info
        return self.files[row] if 0 <= row < len(self.files) else None

    def sync_folders_from_table(self):
        """The table is what you saw and trusted: make the data match it before
        saving or moving anything. Guards against any future desync."""
        fixed = 0
        for row in range(self.file_table.rowCount()):
            info = self.finfo(row)
            cell = self.file_table.item(row, 3)
            if info is None or cell is None:
                continue
            shown = cell.text().strip()
            if shown and info.get('folder') != shown:
                info['folder'] = shown
                fixed += 1
        if fixed:
            log(f"⚠️ {fixed} dossier(s) resynchronisé(s) depuis le tableau")
        return fixed

    def update_row_dest(self, row):
        """No Destination column any more: the target lives in the tooltip"""
        info = self.finfo(row)
        if info is None:
            return
        dest = (f"→ {info['year']}\\{info['folder']}\\{info['filename']}"
                if (info['year'] and info['folder']) else "⚠️ Aucun dossier choisi")
        it = self.file_table.item(row, 3)
        if it:
            it.setToolTip(dest)

    def apply_row_color(self, row):
        info = self.finfo(row)
        if info is None:
            return
        color = folder_color(info['folder']) if info['folder'] else None
        for col in range(4):
            it = self.file_table.item(row, col)
            if it:
                if color:
                    it.setBackground(color)
                else:
                    it.setBackground(QColor(0, 0, 0, 0))

    def on_file_item_changed(self, item):
        if self._filling or item.column() != 2:       # 2 = Année (the only editable one)
            return
        row = item.row()
        info = self.finfo(row)
        if info is not None:
            info['year'] = item.text().strip()
            self._filling = True
            self.update_row_dest(row)
            self._filling = False
            self.refresh_folder_list(info['year'])

    def on_file_selection(self):
        rows = sorted({idx.row() for idx in self.file_table.selectedIndexes()})
        if not rows:
            return
        info = self.finfo(rows[0])
        if info is None:
            return
        if info['year']:
            self.refresh_folder_list(info['year'])
        self.display_file(info)

    def refresh_folder_list(self, year):
        self.folders_label.setText(f"📁 Dossiers {year}")
        self.folder_list.clear()
        year_folder = os.path.join(self.base_path, year)
        if not os.path.isdir(year_folder):
            return
        # Normal event folders of the year
        entries = [(f, f) for f in sorted(os.listdir(year_folder))
                   if os.path.isdir(os.path.join(year_folder, f)) and not f.startswith('!')]
        # Plus the sub-folders living inside the bucket being sorted, so a screenshot
        # can stay among screenshots or move out to a real event folder
        prefix = self.sort_prefix()
        if prefix:
            bucket = os.path.join(year_folder, f"{prefix}{year}")
            if os.path.isdir(bucket):
                for sub in sorted(os.listdir(bucket)):
                    if os.path.isdir(os.path.join(bucket, sub)) and not sub.startswith('!'):
                        entries.append((os.path.join(f"{prefix}{year}", sub),
                                        f"↳ {sub}"))
                entries.insert(0, (f"{prefix}{year}", f"↳ (racine {prefix}{year})"))
        for value, label in entries:
            it = QListWidgetItem(label)
            it.setData(Qt.ItemDataRole.UserRole, value)     # str: safe through Qt
            it.setBackground(folder_color(value))
            it.setToolTip(f"{year}\\{value}")
            self.folder_list.addItem(it)

    def current_year(self):
        """Year of the folder list currently displayed"""
        return self.folders_label.text().replace("📁 Dossiers", "").strip()

    def folder_context_menu(self, pos):
        item = self.folder_list.itemAt(pos)
        if item is None:
            return
        self.folder_list.setCurrentItem(item)
        menu = QMenu(self)
        menu.addAction("✏️ Renommer le dossier…").triggered.connect(
            lambda: self.rename_folder(item))
        menu.addAction("📂 Ouvrir le dossier").triggered.connect(
            lambda: self.open_folder(item))
        menu.exec(self.folder_list.viewport().mapToGlobal(pos))

    def folder_path_of(self, item):
        year = self.current_year()
        return os.path.join(self.base_path, year, item.text()) if year else None

    def open_folder(self, item):
        path = self.folder_path_of(item)
        if path and os.path.isdir(path):
            os.startfile(path)

    def rename_folder(self, item):
        old_path = self.folder_path_of(item)
        if not old_path or not os.path.isdir(old_path):
            self.statusBar().showMessage("Dossier introuvable")
            return
        old_name = item.text()
        new_name, ok = QInputDialog.getText(self, "Renommer le dossier",
                                            f"Année {self.current_year()} :",
                                            text=old_name)
        new_name = (new_name or '').strip()
        if not ok or not new_name or new_name == old_name:
            return
        new_path = os.path.join(os.path.dirname(old_path), new_name)
        if os.path.exists(new_path):
            QMessageBox.warning(self, "Renommer",
                                f"« {new_name} » existe déjà pour cette année.")
            return
        try:
            os.rename(old_path, new_path)
        except Exception as e:
            log(f"❌ Renommage dossier {old_name}: {e}")
            QMessageBox.warning(self, "Renommer", f"Échec du renommage :\n{e}")
            return
        log(f"✏️ Dossier renommé: {old_name} -> {new_name}")
        item.setText(new_name)
        item.setBackground(folder_color(new_name))
        # Files already assigned to the old name follow it
        moved = 0
        for row in range(self.file_table.rowCount()):
            info = self.finfo(row)
            if info and info.get('folder') == old_name:
                self.assign_folder_to_rows([row], new_name)
                moved += 1
        self.statusBar().showMessage(f"✏️ Dossier renommé en « {new_name} »"
                                     + (f" ({moved} fichier(s) suivis)" if moved else ""))

    def on_folder_clicked(self, list_item):
        folder = list_item.data(Qt.ItemDataRole.UserRole) or list_item.text()
        rows = sorted({idx.row() for idx in self.file_table.selectedIndexes()})
        if not rows:
            self.statusBar().showMessage("Sélectionne d'abord des fichiers")
            return
        self.assign_folder_to_rows(rows, folder)
        self.statusBar().showMessage(f"📁 {len(rows)} fichier(s) → {folder}")
        self.select_next_file(rows[-1])

    def select_next_file(self, after_row):
        """Assigning is the last thing you do on a file: move on to the next one"""
        nxt = after_row + 1
        if nxt >= self.file_table.rowCount():
            return
        self.file_table.clearSelection()
        self.file_table.setCurrentCell(nxt, 0)
        self.file_table.scrollToItem(self.file_table.item(nxt, 0),
                                     QAbstractItemView.ScrollHint.EnsureVisible)
        self.file_table.setFocus()

    def assign_folder_to_rows(self, rows, folder):
        """Assign in one repaint instead of one per cell, and save on a timer:
        clicking a folder with 200 files selected was redrawing ~1000 cells."""
        self._filling = True
        # Changing a cell while sorting is on makes QTableWidget re-sort the whole
        # table, which throws the view back to the top. Turn it off for the update
        # and put the scrollbar back exactly where it was.
        was_sorting = self.file_table.isSortingEnabled()
        scroll = self.file_table.verticalScrollBar().value()
        self.file_table.setSortingEnabled(False)
        self.file_table.setUpdatesEnabled(False)
        self.file_table.blockSignals(True)
        try:
            for row in rows:
                info = self.finfo(row)
                if info is None:
                    continue
                info['folder'] = folder
                self.file_table.item(row, 3).setText(folder)
                self.update_row_dest(row)
                self.apply_row_color(row)
        finally:
            self.file_table.blockSignals(False)
            self.file_table.setSortingEnabled(was_sorting)
            self.file_table.setUpdatesEnabled(True)
            self.file_table.verticalScrollBar().setValue(scroll)
            self._filling = False
        self.schedule_save_edits()

    def schedule_save_edits(self):
        """Debounced write: assigning several folders in a row rewrites the file once"""
        self.save_timer.start(600)

    def create_new_folder(self):
        name = self.new_folder_edit.text().strip()
        if not name:
            return
        rows = sorted({idx.row() for idx in self.file_table.selectedIndexes()})
        if not rows:
            self.statusBar().showMessage("Sélectionne d'abord des fichiers")
            return
        first = self.finfo(rows[0])
        year = first['year'] if first else ''
        if not year:
            self.statusBar().showMessage("❌ Année inconnue pour le fichier sélectionné")
            return
        try:
            os.makedirs(os.path.join(self.base_path, year, name), exist_ok=True)
        except Exception as e:
            log(f"❌ Cannot create folder {name}: {e}")
            return
        self.assign_folder_to_rows(rows, name)
        self.refresh_folder_list(year)
        self.new_folder_edit.clear()
        self.statusBar().showMessage(f"✨ Créé et assigné à {len(rows)} fichier(s) : {name}")

    def sort_by_app(self):
        """Move the screenshots sitting loose in the buckets into per-app folders"""
        prefix = self.sort_prefix()
        if not prefix:
            self.statusBar().showMessage(
                "Choisis la source Screenshots ou ScreenRecorder d'abord")
            return
        base = self.base_path
        plan = []                       # (path, target folder, app)
        for year in sorted(os.listdir(base)):
            bucket = os.path.join(base, year, f"{prefix}{year}")
            if not re.match(r'^\d{4}$', year) or not os.path.isdir(bucket):
                continue
            for name in sorted(os.listdir(bucket)):
                path = os.path.join(bucket, name)
                if os.path.isdir(path):
                    continue
                if os.path.splitext(name)[1].lower() not in (IMAGE_EXTS | VIDEO_EXTS):
                    continue
                app = app_from_filename(name)
                if app:
                    plan.append((path, os.path.join(bucket, app), app))
        if not plan:
            self.statusBar().showMessage("Aucune capture à regrouper (nom d'appli absent)")
            return
        apps = sorted({app for _p, _t, app in plan})
        if QMessageBox.question(
                self, "Ranger par appli",
                f"Ranger {len(plan)} capture(s) dans {len(apps)} dossier(s) ?\n\n"
                + ", ".join(apps[:12]) + (" …" if len(apps) > 12 else ""),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.Yes) != QMessageBox.StandardButton.Yes:
            return
        dup_dir = os.path.join(base, '!duplicate')
        moved = errors = 0
        for n, (path, target, app) in enumerate(plan):
            try:
                safe_move(path, target, dup_dir=dup_dir)
                moved += 1
            except Exception as e:
                log(f"[APPS] ❌ {os.path.basename(path)}: {e}")
                errors += 1
            if n % 50 == 0:
                self.statusBar().showMessage(f"🗂️ Rangement… {n + 1}/{len(plan)}")
                QApplication.processEvents()
        log(f"[APPS] {moved} capture(s) rangée(s) dans {len(apps)} dossier(s) d'appli"
            + (f", {errors} erreur(s)" if errors else ""))
        self.statusBar().showMessage(f"🗂️ {moved} capture(s) rangée(s) par appli"
                                     + (f", {errors} erreur(s)" if errors else ""))
        self.scan_media()

    def save_edits(self):
        self.sync_folders_from_table()
        edits = {info['filename']: info['folder'] for info in self.files if info['folder']}
        previous = load_json(EDITS_FILE, {})
        # Never silently shrink the file: keep a copy first, so a bug can't wipe
        # an afternoon of tagging.
        if previous and len(edits) < len(previous):
            try:
                save_json(EDITS_FILE + '.bak', previous)
                log(f"💾 Sauvegarde: {len(previous)} tag(s) copiés dans "
                    f"{os.path.basename(EDITS_FILE)}.bak (nouveau total: {len(edits)})")
            except Exception as e:
                log(f"⚠️ Backup des tags impossible: {e}")
        save_json(EDITS_FILE, edits)

    # ---------- Actions ----------

    def apply_moves(self):
        self.sync_folders_from_table()      # trust what is on screen
        moved = 0
        errors = []
        remaining = []
        targets = sum(1 for i in self.files if i['year'] and i['folder'])
        if not targets:
            self.statusBar().showMessage("Aucun fichier n'a d'année ET de dossier assignés")
            log("⚠️ APPLIQUER: rien à déplacer")
            return
        for info in self.files:
            if info['year'] and info['folder']:
                target = os.path.join(self.base_path, info['year'], info['folder'])
                if os.path.normcase(os.path.abspath(os.path.dirname(info['filepath']))) == \
                        os.path.normcase(os.path.abspath(target)):
                    continue        # already there: leave it alone, keep it listed
                try:
                    safe_move(info['filepath'], target,
                              dup_dir=os.path.join(self.base_path, '!duplicate'))
                    log(f"Moved: {info['filename']} -> {info['year']}/{info['folder']}/")
                    moved += 1
                    continue
                except Exception as e:
                    errors.append(f"{info['filename']}: {e}")
                    log(f"❌ Error moving {info['filename']}: {e}")
            remaining.append(info)
        self.files = remaining
        self.fill_file_table()
        msg = f"✅ {moved} fichier(s) déplacé(s)"
        if errors:
            msg += f" — {len(errors)} erreur(s)"
        self.statusBar().showMessage(msg)

    def delete_selected(self):
        rows = sorted({idx.row() for idx in self.file_table.selectedIndexes()})
        if not rows:
            return
        next_row = rows[0]
        deleted = errors = 0
        removed = set()
        # Remove only the affected rows: rebuilding the whole table was what froze
        # the UI for a second on every delete.
        self.file_table.setUpdatesEnabled(False)
        self.file_table.blockSignals(True)
        try:
            for row in sorted(rows, reverse=True):
                info = self.finfo(row)
                if info is None:
                    continue
                path = os.path.normpath(info['filepath'])
                try:
                    try:
                        from send2trash import send2trash
                        send2trash(path)
                    except ImportError:
                        os.remove(path)
                    except Exception as e:
                        log(f"send2trash failed, direct delete: {e}")
                        os.remove(path)
                    removed.add(info.get('uid', id(info)))
                    self.preview_cache.pop(info['filepath'], None)
                    self.file_table.removeRow(row)
                    deleted += 1
                except Exception as e:
                    log(f"❌ Error deleting {info['filename']}: {e}")
                    errors += 1
        finally:
            self.file_table.blockSignals(False)
            self.file_table.setUpdatesEnabled(True)
        if removed:
            self.files = [f for f in self.files if f.get('uid', id(f)) not in removed]
            for uid in removed:
                self.files_by_uid.pop(uid, None)
        if self.file_table.rowCount():
            self.file_table.selectRow(min(next_row, self.file_table.rowCount() - 1))
        else:
            self.current_filepath = None
            self.current_pixmap = None
            self.viewer_label.setPixmap(QPixmap())
            self.viewer_label.setText("")
        self.statusBar().showMessage(f"🗑️ {deleted} fichier(s) supprimé(s)" + (f", {errors} erreur(s)" if errors else ""))

    def run_auto_organize(self):
        base = self.base_path
        log("--- Auto-organize started ---")
        recorder = os.path.normpath(os.path.join(base, '..', 'ScreenRecorder'))
        pictures = os.path.normpath(os.path.join(base, '..', '..', 'Pictures'))
        r_count = self.sort_external_folder(recorder, 'ScreenRecorder')
        p_count = self.sort_external_folder(pictures, 'Pictures')

        c_count = 0
        for filename in os.listdir(base):
            filepath = os.path.join(base, filename)
            if os.path.isdir(filepath):
                continue
            is_screenshot = 'screenshot' in filename.lower()
            is_recorder = 'screen' in filename.lower() and 'recorder' in filename.lower()
            if not (is_screenshot or is_recorder):
                continue
            year = get_year_from_file(filename, filepath)
            if not year:
                log(f"⚠️ No year found, skipped: {filename}")
                continue
            folder = f"!Screenshots_{year}" if is_screenshot else f"!ScreenRecorder_{year}"
            try:
                safe_move(filepath, os.path.join(base, year, folder),
                          dup_dir=os.path.join(base, '!duplicate'))
                log(f"Moved: {filename} -> {year}/{folder}/")
                c_count += 1
            except Exception as e:
                log(f"❌ Error moving {filename}: {e}")

        total = r_count + p_count + c_count
        log(f"--- Auto-organize done: {total} file(s) (Camera root: {c_count}, ScreenRecorder: {r_count}, Pictures: {p_count}) ---")
        self.statusBar().showMessage(f"⚡ {total} fichier(s) rangé(s)")
        self.scan_media()

    # ---------- pCloud import ----------

    def pcloud_root(self):
        """Folder holding DCIM/ and Pictures/. Configured, or deduced from Camera."""
        configured = (self.config.get('pcloud_root') or '').strip()
        if configured:
            return os.path.normpath(configured)
        # ...\<root>\DCIM\Camera  ->  ...\<root>
        return os.path.normpath(os.path.join(self.base_path, '..', '..'))

    def import_pcloud(self, silent=False):
        r"""Empty the pCloud sync folder into the Camera tree.

        1. Pictures\ : loose media at the root go to Camera\ (sub-folders untouched)
        2. DCIM\Screenshots and DCIM\ScreenRecorder : every media is filed under
           Camera\YEAR\!Screenshots_YEAR (or !ScreenRecorder_YEAR), year read from
           the filename, then EXIF, then the file date
        3. Emptied sub-folders are removed
        Duplicates (same name, same size) go to !duplicate, never overwritten."""
        root = self.pcloud_root()
        base = self.base_path
        log("=" * 62)
        log(f"[PCLOUD] Racine  : {root}")
        log(f"[PCLOUD] Camera  : {base}")
        if not os.path.isdir(root):
            log(f"[PCLOUD] ❌ Racine introuvable, import annulé")
            return 0
        if not os.path.isdir(base):
            log(f"[PCLOUD] ❌ Dossier Camera introuvable, import annulé")
            return 0

        moved = skipped = errors = 0

        # --- 1. Pictures: root files only, folders left strictly alone ---
        pictures = os.path.join(root, 'Pictures')
        if os.path.isdir(pictures):
            m, s_, e = self.move_media_files(pictures, lambda *_: base, "Pictures")
            moved += m
            skipped += s_
            errors += e
        else:
            log(f"[PCLOUD] Pictures: absent ({pictures})")

        # --- 2. DCIM\Screenshots and DCIM\ScreenRecorder, sub-folders included ---
        dcim = os.path.join(root, 'DCIM')
        if os.path.isdir(dcim):
            for entry in sorted(os.listdir(dcim)):
                kind = DCIM_SPECIAL_FOLDERS.get(entry)
                if not kind:
                    continue
                folder = os.path.join(dcim, entry)
                if not os.path.isdir(folder) or os.path.normcase(folder) == os.path.normcase(base):
                    continue
                m, s_, e = self.move_media_files(
                    folder,
                    lambda year, k=kind: os.path.join(base, year, f"!{k}_{year}"),
                    entry, recursive=True, by_app=True)
                moved += m
                skipped += s_
                errors += e
                self.remove_empty_dirs(folder, keep_root=True)
        else:
            log(f"[PCLOUD] DCIM: absent ({dcim})")

        log(f"[PCLOUD] ✅ {moved} fichier(s) rangé(s)"
            + (f", {skipped} ignoré(s)" if skipped else "")
            + (f", {errors} erreur(s)" if errors else ""))
        log("=" * 62)
        if not silent:
            self.statusBar().showMessage(
                f"📥 Import pCloud : {moved} fichier(s) rangé(s)"
                + (f", {errors} erreur(s)" if errors else ""))
        return moved

    def move_media_files(self, source, target_for_year, label, recursive=False,
                         by_app=False):
        """Move every media of `source` to target_for_year(year).
        recursive=False -> root files only (Pictures: its folders stay untouched).
        Returns (moved, skipped, errors)."""
        moved = skipped = errors = 0
        dup_dir = os.path.join(self.base_path, '!duplicate')
        try:
            entries = sorted(os.listdir(source))
        except Exception as e:
            log(f"[PCLOUD] ❌ Lecture impossible {source}: {e}")
            return 0, 0, 1
        for name in entries:
            path = os.path.join(source, name)
            if os.path.isdir(path):
                if recursive and not name.startswith('!'):
                    m, s_, e = self.move_media_files(path, target_for_year,
                                                     f"{label}\\{name}", recursive=True,
                                                     by_app=by_app)
                    moved += m
                    skipped += s_
                    errors += e
                continue
            ext = os.path.splitext(name)[1].lower()
            if ext not in (IMAGE_EXTS | VIDEO_EXTS):
                log(f"[PCLOUD]    ~ ignoré (extension): {label}\\{name}")
                skipped += 1
                continue
            year = get_year_from_file(name, path)
            if not year:
                log(f"[PCLOUD]    ⚠️ année inconnue, laissé sur place: {label}\\{name}")
                skipped += 1
                continue
            target = target_for_year(year)
            if by_app:
                # Screenshots carry the app package: group them by app
                app = app_from_filename(name)
                if app:
                    target = os.path.join(target, app)
            try:
                dest = safe_move(path, target, dup_dir=dup_dir)
                where = os.path.relpath(dest, self.base_path)
                if os.path.normcase(os.path.dirname(dest)) == os.path.normcase(dup_dir):
                    log(f"[PCLOUD]    ♻️ doublon -> !duplicate: {label}\\{name}")
                else:
                    log(f"[PCLOUD]    → {label}\\{name}  ->  {where}")
                moved += 1
            except Exception as e:
                log(f"[PCLOUD]    ❌ {label}\\{name}: {e}")
                errors += 1
        return moved, skipped, errors

    def remove_empty_dirs(self, folder, keep_root=True):
        """Delete the sub-folders left empty after the import"""
        removed = 0
        for current, dirs, _files in os.walk(folder, topdown=False):
            if keep_root and os.path.normcase(current) == os.path.normcase(folder):
                continue
            try:
                if not os.listdir(current):
                    os.rmdir(current)
                    log(f"[PCLOUD]    🧹 dossier vide supprimé: "
                        f"{os.path.relpath(current, folder)}")
                    removed += 1
            except OSError:
                pass
        return removed

    def sort_external_folder(self, source_folder, prefix):
        count = 0
        if not os.path.isdir(source_folder):
            log(f"⚠️ Folder not found: {source_folder}")
            return count
        log(f"Scanning: {source_folder}")
        try:
            entries = os.listdir(source_folder)
        except Exception as e:
            log(f"❌ Cannot list {source_folder}: {e}")
            return count
        for filename in entries:
            filepath = os.path.join(source_folder, filename)
            if os.path.isdir(filepath):
                continue
            ext = os.path.splitext(filename)[1].lower()
            if ext not in (IMAGE_EXTS | VIDEO_EXTS):
                log(f"   Skipped (extension): {filename}")
                continue
            year = get_year_from_file(filename, filepath)
            if not year:
                log(f"⚠️ No year found, skipped: {filename}")
                continue
            try:
                safe_move(filepath, os.path.join(self.base_path, year, f"!{prefix}_{year}"),
                          dup_dir=os.path.join(self.base_path, '!duplicate'))
                log(f"Moved: {filename} -> {year}/!{prefix}_{year}/")
                count += 1
            except Exception as e:
                log(f"❌ Error moving {filename}: {e}")
        return count

    # ---------- Viewer ----------

    def display_file(self, info):
        """Never blocks: shows whatever is cached and lets the worker deliver the rest"""
        self.cleanup_screenshots()
        path = info['filepath']
        self.current_filepath = path
        self.file_label.setText(info['filename'])
        self.zoom = 1.0
        self.video_bar.setVisible(False)

        if info['ext'] in VIDEO_EXTS:
            self.video_bar.setVisible(True)
            try:
                default_index = VIDEO_PERCENTS.index(DEFAULT_SHOT_PCT)
            except ValueError:
                default_index = 0
            self.show_video_percent(default_index)
            return

        if info['ext'] not in IMAGE_EXTS:
            self.current_pixmap = None
            self.viewer_label.setPixmap(QPixmap())
            self.viewer_label.setText("📄 Pas d'aperçu pour ce type de fichier")
            return

        if not PIL_AVAILABLE:
            self.viewer_label.setText("❌ Pillow non installé")
            return

        cached = self.preview_cache.get(path)
        if cached is not None:
            self.preview_cache.move_to_end(path)
            self.current_pixmap = QPixmap.fromImage(cached)
            self.render_image()
        else:
            # Keep the previous image on screen rather than flashing to black
            self.loader.request('image', path)
        self.prefetch_neighbours()

    def prefetch_neighbours(self):
        """Decode the next and previous photos while you look at this one"""
        rows = sorted({idx.row() for idx in self.file_table.selectedIndexes()})
        if not rows:
            return
        row = rows[0]
        for offset in (1, 2, -1, 3):
            r = row + offset
            if not (0 <= r < self.file_table.rowCount()):
                continue
            info = self.finfo(r)
            if not info or info['ext'] not in IMAGE_EXTS:
                continue
            if info['filepath'] not in self.preview_cache:
                self.loader.request('image', info['filepath'])

    def on_preview_ready(self, path, qimage):
        self.preview_cache[path] = qimage
        while len(self.preview_cache) > PREVIEW_CACHE_MAX:
            self.preview_cache.popitem(last=False)
        if path == self.current_filepath:
            self.current_pixmap = QPixmap.fromImage(qimage)
            self.render_image()

    def on_shot_ready(self, path, pct, jpg):
        """A frame requested on the fly arrived. Ignore it if you already moved on."""
        if path != self.current_filepath or pct != self.current_shot_pct:
            return
        if jpg and os.path.exists(jpg):
            self.current_pixmap = QPixmap(jpg)
            self.zoom = 1.0
            self.render_image()
        else:
            self.current_pixmap = None
            self.viewer_label.setPixmap(QPixmap())
            self.viewer_label.setText("▶️ Vidéo — double-clic pour ouvrir"
                                      if not FFMPEG else "❌ Image non extractible")

    def render_image(self):
        if not self.current_pixmap:
            return
        size = self.viewer_scroll.viewport().size()
        target = QSize(int(size.width() * self.zoom), int(size.height() * self.zoom))
        scaled = self.current_pixmap.scaled(target, Qt.AspectRatioMode.KeepAspectRatio,
                                            Qt.TransformationMode.SmoothTransformation)
        self.viewer_label.setText("")
        self.viewer_label.setPixmap(scaled)

    def eventFilter(self, obj, event):
        if obj is self.viewer_scroll.viewport() and event.type() == QEvent.Type.Wheel:
            if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
                self.zoom *= 1.1 if event.angleDelta().y() > 0 else 0.9
                self.zoom = max(0.2, min(self.zoom, 10.0))
                self.render_image()
                return True
        return super().eventFilter(obj, event)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.render_image()

    def show_video_percent(self, index):
        """Show the frame at that percentage, extracting it on the spot if needed.
        One ffmpeg call, in the background: no more waiting for eleven frames."""
        path = self.current_filepath
        if not path:
            return
        index = max(0, min(index, len(VIDEO_PERCENTS) - 1))
        pct = VIDEO_PERCENTS[index]
        # Checking a radio emits toggled, which would call us again
        for i, b in enumerate(self.video_buttons):
            if b.isChecked() != (i == index):
                b.blockSignals(True)
                b.setChecked(i == index)
                b.blockSignals(False)
        self.current_shot_pct = pct
        jpg = shot_path(path, self.video_cache_dir, pct)
        if jpg and os.path.exists(jpg):
            self.current_pixmap = QPixmap(jpg)
            self.zoom = 1.0
            self.render_image()
            return
        if not FFMPEG or not self.video_cache_dir:
            self.current_pixmap = None
            self.viewer_label.setPixmap(QPixmap())
            self.viewer_label.setText("▶️ Vidéo — double-clic pour ouvrir")
            return
        # Keep the current frame on screen while the new one is extracted
        self.statusBar().showMessage(f"🎬 Image à {pct} %…")
        self.loader.request('shot', path, (self.video_cache_dir, pct))

    def play_current_video(self):
        self.open_current_file()

    def open_current_file(self):
        """Double-click on the preview (image or video) opens the real file"""
        if self.current_filepath and os.path.exists(self.current_filepath):
            try:
                os.startfile(self.current_filepath)
            except Exception as e:
                log(f"❌ Ouverture {os.path.basename(self.current_filepath)}: {e}")

    # ----- background prefetch of the sort tab's video previews -----

    def start_prefetch(self):
        """One frame per video (25 %), in the background. The other percentages
        are extracted only when you click their button."""
        self.stop_prefetch()
        if not FFMPEG or not self.video_cache_dir:
            return
        pending = [i['filepath'] for i in self.files
                   if i['ext'] in VIDEO_EXTS
                   and not os.path.exists(shot_path(i['filepath'], self.video_cache_dir,
                                                    DEFAULT_SHOT_PCT) or '')]
        if not pending:
            return
        self.prefetch_worker = PrefetchWorker(pending, self.video_cache_dir,
                                              DEFAULT_SHOT_PCT, self)
        self.prefetch_worker.advanced.connect(self.on_prefetch_progress)
        self.prefetch_worker.finished.connect(
            lambda: self.statusBar().showMessage("🎬 Aperçus vidéo prêts"))
        self.prefetch_worker.start()
        log(f"🎬 Préchargement des aperçus: {len(pending)} vidéo(s)")

    def stop_prefetch(self, blocking=False):
        w = getattr(self, 'prefetch_worker', None)
        if w and w.isRunning():
            w.stop()
            if blocking:            # only on exit: waiting here would freeze the UI
                w.wait(3000)
        self.prefetch_worker = None

    def on_prefetch_progress(self, done, total):
        if done % 5 == 0 or done == total:
            self.statusBar().showMessage(f"🎬 Préchargement des aperçus… {done}/{total}")

    def cleanup_screenshots(self):
        """Stop showing them, but keep the jpgs: they are the cache that makes the
        next selection instant. The whole folder is emptied when the app closes."""
        self.current_screenshots = []

    def purge_video_cache(self, remove_dirs=True):
        """Empty the temp folders: !tempvideoscreen (video previews) and !temp
        (duplicate thumbnails). Called at startup and on exit, so nothing of ours
        is left sitting in your photo folder."""
        dirs = [self.video_cache_dir]
        if self.base_path:
            dirs.append(os.path.join(self.base_path, '!temp'))
        for d in dirs:
            if not d or not os.path.isdir(d):
                continue
            removed = 0
            for f in os.listdir(d):
                try:
                    os.remove(os.path.join(d, f))
                    removed += 1
                except Exception:
                    pass
            if removed:
                log(f"🧹 {os.path.basename(d)}: {removed} fichier(s) temporaire(s) supprimé(s)")
            if remove_dirs:
                try:
                    os.rmdir(d)          # only succeeds when actually empty
                    log(f"🧹 {os.path.basename(d)}: dossier supprimé")
                except OSError:
                    pass

    # ---------- Config ----------

    def on_path_edited(self):
        path = os.path.normpath(self.path_edit.text().strip())
        if path and path != self.base_path:
            self.base_path = path
            self.config['camera_path'] = path
            save_json(CONFIG_FILE, self.config)
            log(f"Camera folder set: {path}")

    def on_pcloud_edited(self):
        path = self.pcloud_edit.text().strip()
        self.config['pcloud_root'] = os.path.normpath(path) if path else ''
        save_json(CONFIG_FILE, self.config)
        log(f"[PCLOUD] Racine: {self.pcloud_root()}")

    def browse_pcloud(self):
        folder = QFileDialog.getExistingDirectory(self, "Choisir le dossier pCloud",
                                                  self.pcloud_root())
        if folder:
            self.pcloud_edit.setText(os.path.normpath(folder))
            self.on_pcloud_edited()

    def on_autoimport_toggled(self, checked):
        self.config['pcloud_autoimport'] = bool(checked)
        save_json(CONFIG_FILE, self.config)

    def import_pcloud_now(self):
        moved = self.import_pcloud()
        if moved:
            self.startup_load()

    def browse_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Choisir le dossier Camera", self.base_path)
        if folder:
            self.path_edit.setText(os.path.normpath(folder))
            self.on_path_edited()
            self.startup_load()

    # ---------- Column layout persistence ----------

    def header_states(self):
        return {'dup': self.dup_table, 'rename': self.rename_table, 'files': self.file_table}

    def save_column_layout(self):
        """Widths, order and sort of every table -> config file"""
        layout, sorts = {}, {}
        for name, table in self.header_states().items():
            try:
                h = table.horizontalHeader()
                layout[name] = bytes(h.saveState()).hex()
                sorts[name] = [h.sortIndicatorSection(), int(h.sortIndicatorOrder().value)]
            except Exception:
                pass
        if layout:
            self.config['columns'] = layout
            self.config['sorts'] = sorts
            save_json(CONFIG_FILE, self.config)

    def apply_saved_sort(self, name, table, default_col, default_desc=False):
        """Restore the user's sort, or fall back to the sensible default
        (chronological for the files to sort)."""
        saved = (self.config.get('sorts') or {}).get(name)
        col, order_value = (saved if isinstance(saved, list) and len(saved) == 2
                            else [default_col, 1 if default_desc else 0])
        if not (0 <= col < table.columnCount()):
            col, order_value = default_col, 1 if default_desc else 0
        order = (Qt.SortOrder.DescendingOrder if order_value
                 else Qt.SortOrder.AscendingOrder)
        table.sortItems(col, order)

    def restore_column_layout(self):
        layout = self.config.get('columns') or {}
        for name, table in self.header_states().items():
            blob = layout.get(name)
            if not blob:
                continue
            try:
                table.horizontalHeader().restoreState(QByteArray(bytes.fromhex(blob)))
            except Exception as e:
                log(f"⚠️ Colonnes {name}: état illisible ({e})")

    def closeEvent(self, event):
        if self.save_timer.isActive():     # flush a pending debounced save
            self.save_timer.stop()
            self.save_edits()
        self.save_column_layout()
        self.stop_background_compare(blocking=True)
        self.stop_prefetch(blocking=True)
        if self.loader.isRunning():
            self.loader.stop()
            self.loader.wait(2000)
        self.thumb_pool.stop()
        self.cleanup_screenshots()
        self.cleanup_dup_temp()
        self.purge_video_cache()
        event.accept()


# ==================== THEME ====================

def apply_dark_theme(app):
    app.setStyle(QStyleFactory.create('Fusion'))
    p = QPalette()
    window = QColor('#202124')
    base = QColor('#2a2b2e')
    text = QColor('#e8eaed')
    disabled = QColor('#777777')
    highlight = QColor('#0a84ff')
    p.setColor(QPalette.ColorRole.Window, window)
    p.setColor(QPalette.ColorRole.WindowText, text)
    p.setColor(QPalette.ColorRole.Base, base)
    p.setColor(QPalette.ColorRole.AlternateBase, window)
    p.setColor(QPalette.ColorRole.Text, text)
    p.setColor(QPalette.ColorRole.Button, QColor('#333438'))
    p.setColor(QPalette.ColorRole.ButtonText, text)
    p.setColor(QPalette.ColorRole.Highlight, highlight)
    p.setColor(QPalette.ColorRole.HighlightedText, QColor('#ffffff'))
    p.setColor(QPalette.ColorRole.ToolTipBase, base)
    p.setColor(QPalette.ColorRole.ToolTipText, text)
    p.setColor(QPalette.ColorRole.PlaceholderText, disabled)
    p.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text, disabled)
    p.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.ButtonText, disabled)
    app.setPalette(p)
    app.setStyleSheet("""
        QWidget { font-size: 10pt; }
        QTableWidget { gridline-color: #3a3b3e; }
        QHeaderView::section { background: #2a2b2e; color: #e8eaed; border: 0px; padding: 6px; }
        QTabBar::tab { padding: 8px 18px; }
        QPushButton { padding: 6px 14px; border-radius: 6px; background: #333438; border: 1px solid #444548; }
        QPushButton:hover { background: #44454a; }
        QPushButton:pressed, QPushButton:checked { background: #0a84ff; border-color: #0a84ff; }
        QLineEdit { padding: 5px; border-radius: 5px; background: #2a2b2e; border: 1px solid #444548; }
        QListWidget { border: 1px solid #3a3b3e; }
        QScrollArea { border: 1px solid #3a3b3e; }
    """)


if __name__ == '__main__':
    app = QApplication(sys.argv)
    apply_dark_theme(app)
    win = TriPhotoWindow()
    win.show()
    sys.exit(app.exec())
