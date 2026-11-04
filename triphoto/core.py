"""
TriPhoto core: everything that touches files, names, dates and pixels.
No UI, no side effect at import time -> safe to import from a test or a script.

Ported from the Qt edition (TriPhoto.py). The invariants listed in CLAUDE.md
live here: safe_move() never moves a file onto itself, merges never delete,
duplicates always land in !duplicate.
"""

import os
import re
import json
import shutil
import zlib
import difflib
import filecmp
import hashlib
import threading
import subprocess
from collections import OrderedDict
from datetime import datetime, timedelta

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# TRIPHOTO_DATA points config + tags elsewhere: lets a test run on a sandbox tree
# without touching the real triphoto_edits.json
DATA_DIR = os.environ.get('TRIPHOTO_DATA') or ROOT
CONFIG_FILE = os.path.join(DATA_DIR, 'triphoto_config.json')
EDITS_FILE = os.path.join(DATA_DIR, 'triphoto_edits.json')
IGNORE_FILE = os.path.join(DATA_DIR, 'triphoto_ignore.json')
EXCLUSION_FILE = os.path.join(DATA_DIR, 'FolderDoublonExclusion.txt')
LOG_FILE = os.path.join(DATA_DIR, 'triphoto.log')

# Caches live OUTSIDE the photo tree: pCloud would otherwise upload them, and a
# local disk is much faster than the pCloud virtual drive.
# Not under %LOCALAPPDATA%: the Microsoft Store Python silently redirects writes
# there to a private folder that ffmpeg and PowerShell cannot see.
CACHE_DIR = os.environ.get('TRIPHOTO_CACHE') or os.path.join(ROOT, '.cache')
THUMB_DIR = os.path.join(CACHE_DIR, 'thumbs')     # persistent between sessions
FRAME_DIR = os.path.join(CACHE_DIR, 'frames')     # video frames, purged on exit
THUMB_CACHE_LIMIT = 2 * 1024 ** 3                 # bytes, pruned at startup

DEFAULT_CAMERA_PATH = r"P:\AutoUpload\Xiaomi 2407FPN8EG\DCIM\Camera"
DEFAULT_FFMPEG_DIR = r"P:\a-PC\a-Prg\Video\ffmpeg"

# Scopes (duplicates tab) and sources (sort tab): label -> prefix of the year bucket
SCOPES = [
    ("Camera", ''),
    ("Screenshots", '!Screenshots_'),
    ("ScreenRecorder", '!ScreenRecorder_'),
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

TECH_DIRS = ('!duplicate', '!temp', '!tempvideoscreen')

IMAGE_EXTS = {'.jpg', '.jpeg', '.png', '.gif', '.bmp', '.tiff', '.heic', '.heif', '.webp'}
VIDEO_EXTS = {'.mp4', '.avi', '.mov', '.wmv', '.flv', '.mkv', '.m4v', '.3gp', '.webm', '.mts'}
MEDIA_EXTS = IMAGE_EXTS | VIDEO_EXTS
VIDEO_PERCENTS = [0, 10, 15, 25, 30, 50, 65, 75, 85, 95, 100]
VIDEO_SAMPLE_POINTS = (10, 30, 50, 70, 90)      # duplicate slideshow + fingerprint
DEFAULT_SHOT_PCT = 25

PREVIEW_MAX = 1800
THUMB_MAX = 320

NO_WINDOW = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0


# ==================== LOG ====================

_log_listeners = []
_log_lock = threading.Lock()


def add_log_listener(fn):
    _log_listeners.append(fn)


LOG_MAX = 1024 * 1024


def rotate_log():
    """Lines only carry the time: past 1 MB, the log becomes triphoto.log.old
    (one generation kept), so it never grows without bound."""
    try:
        if os.path.getsize(LOG_FILE) > LOG_MAX:
            os.replace(LOG_FILE, LOG_FILE + '.old')
    except OSError:
        pass


def log(message):
    line = f"[{datetime.now().strftime('%H:%M:%S')}] {message}"
    with _log_lock:
        try:
            print(line, flush=True)
        except Exception:
            pass
        try:
            with open(LOG_FILE, 'a', encoding='utf-8') as f:
                f.write(line + '\n')
        except Exception:
            pass
    for fn in list(_log_listeners):
        try:
            fn(line)
        except Exception:
            pass


# ==================== OPTIONAL LIBS ====================

PIL_AVAILABLE = HEIF_AVAILABLE = False
try:
    from PIL import Image, ImageOps
    PIL_AVAILABLE = True
    try:
        from pillow_heif import register_heif_opener
        register_heif_opener()
        HEIF_AVAILABLE = True
    except ImportError:
        pass
except ImportError:
    Image = ImageOps = None

RESAMPLE_FAST = RESAMPLE_HQ = 2
if PIL_AVAILABLE:
    _res = getattr(Image, 'Resampling', Image)
    RESAMPLE_FAST = getattr(_res, 'BILINEAR', 2)
    RESAMPLE_HQ = getattr(_res, 'LANCZOS', 1)


# ==================== JSON ====================

def load_json(path, default):
    try:
        if os.path.exists(path):
            with open(path, 'r', encoding='utf-8') as f:
                return json.load(f)
    except Exception as e:
        log(f"❌ Lecture {os.path.basename(path)} : {e}")
    return default


def save_json(path, data):
    """Write to a temp file then swap: a crash mid-write can't truncate the file"""
    tmp = path + '.tmp'
    try:
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        os.replace(tmp, path)
    except Exception as e:
        log(f"❌ Écriture {os.path.basename(path)} : {e}")


def folder_hue(name):
    """Stable hue for a folder name (same formula as the Qt edition)"""
    return zlib.crc32(name.encode('utf-8')) % 360


def same_path(a, b):
    return os.path.normcase(os.path.abspath(a)) == os.path.normcase(os.path.abspath(b))


def is_under(path, root):
    """True when path is root itself or lies inside it"""
    if not path or not root:
        return False
    p = os.path.normcase(os.path.abspath(path))
    r = os.path.normcase(os.path.abspath(root)).rstrip('\\/')
    return p == r or p.startswith(r + os.sep)


# ==================== DATES ====================

# Only the timestamp matters (IMG_, VID_, Screenshot_... prefixes are ignored), so
# photos and videos of the same moment sit next to each other.
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


def file_datetime(filename, filepath, mtime=None):
    """Shooting date: the name first, the file's mtime as a fallback. Never None."""
    dt = datetime_from_name(filename)
    if dt:
        return dt
    try:
        return datetime.fromtimestamp(mtime if mtime is not None else os.path.getmtime(filepath))
    except Exception:
        return datetime(1970, 1, 1)


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
            with Image.open(filepath) as img:
                exif = img.getexif()
                dt = None
                try:
                    dt = exif.get_ifd(0x8769).get(36867)  # DateTimeOriginal
                except Exception:
                    pass
                if not dt:
                    dt = exif.get(306)  # DateTime
            if dt and re.match(r'^(19|20)\d{2}', str(dt)):
                return str(dt)[:4]
        except Exception:
            pass
    try:
        return str(datetime.fromtimestamp(os.path.getmtime(filepath)).year)
    except Exception:
        return None


# ==================== APP NAME FROM A SCREENSHOT ====================

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
    'com.openai.chatgpt': 'ChatGPT',
    'com.anthropic.claude': 'Claude',
    'io.homeassistant.companion.android': 'Home Assistant',
    'com.google.android.apps.messaging': 'Messages',
    'mobi.societegenerale.mobile.lappli': 'Société Générale',
    'com.android.updater': 'Mise à jour système',
    'fr.proxiserve.myconso': 'Proxiserve',
    'com.weroad.wemeet': 'WeMeet',
    'com.tribab.tricount.android': 'Tricount',
    'co.hinge.app': 'Hinge',
    'com.xiaomi.smarthome': 'Xiaomi Home',
    'com.stt.android.suunto': 'Suunto',
    'com.lonelycatgames.xplore': 'X-plore',
    'com.auchan.android': 'Auchan',
    'com.lidl.eci.lidlplus': 'Lidl Plus',
    'yqtrack.app': '17TRACK',
    'com.textra': 'Textra',
    'com.mi.globalbrowser': 'Mi Browser',
    'com.miui.securitycenter': 'Sécurité',
    'com.miui.calculator': 'Calculatrice',
    'com.android.incallui': 'Téléphone',
    'fr.geev.application': 'Geev',
    'com.mxtech.videoplayer.ad': 'MX Player',
    'com.miui.gallery': 'Galerie',
    'com.miui.home': 'Écran d\'accueil',
    'com.android.camera': 'Appareil photo',
}

APP_NAMES_LOWER = {k.lower(): v for k, v in APP_NAMES.items()}

# Screenshots that carry a tag instead of a package
SPECIAL_TAGS = {
    'lockscreen': 'Écran de verrouillage',
    'launcher': 'Écran d\'accueil',
    'home': 'Écran d\'accueil',
    'systemui': 'Système',
    'recents': 'Applis récentes',
}

# Segments that say nothing about the app: keep looking to their left
GENERIC_SEGMENTS = {'android', 'app', 'apps', 'mobile', 'main', 'client', 'shopping',
                    'browser', 'messenger', 'music', 'video', 'free', 'pro', 'lite',
                    'release', 'prod', 'ui', 'go'}

# Suffixes the phone appends after the package: -edit, -edit1, -crop...
EDIT_SUFFIX_RE = re.compile(r'-(edit|crop|copy|copie|mark)\d*$', re.IGNORECASE)


def app_from_filename(filename):
    """Readable app name from an Android screenshot filename, or None.

    'Screenshot_..._com.whatsapp.jpg'       -> 'WhatsApp'
    'Screenshot_..._com.whatsapp-edit.jpg'  -> 'WhatsApp'
    'Screenshot_..._lockscreen.jpg'         -> 'Écran de verrouillage'
    'Screenshot_..._com.tutteo.flat_1.jpg'  -> 'Flat'
    'IMG_20230829_190623.jpg'               -> None
    """
    stem = os.path.splitext(filename)[0]
    # A '_1' collision suffix must not be mistaken for the app segment
    stem = re.sub(r'_\d{1,2}$', '', stem)
    if '_' not in stem:
        return None
    tail = EDIT_SUFFIX_RE.sub('', stem.rsplit('_', 1)[1])
    if not tail or not re.match(r'^[A-Za-z]', tail):
        return None                                  # digits = a date, not an app
    if '.' not in tail:                              # 'lockscreen', 'launcher'...
        return SPECIAL_TAGS.get(tail.lower()) or (tail[:1].upper() + tail[1:])
    package = tail
    known = APP_NAMES_LOWER.get(package.lower())
    if known:
        return known
    parts = [p for p in package.split('.') if p]
    if len(parts) < 2:
        return None
    body = parts[1:]                                 # drop com / org / fr / app...
    for segment in reversed(body):
        if segment.lower() not in GENERIC_SEGMENTS and not segment.isdigit():
            return segment[:1].upper() + segment[1:]
    return body[-1][:1].upper() + body[-1][1:] if body else None


# ==================== MOVES ====================

def safe_move(src, target_folder, dup_dir=None):
    """Move file to folder with collision handling.
    If an identical file (same name + same size) already exists at destination
    and dup_dir is given, src goes to dup_dir instead (never duplicated with _1/_2)."""
    # A file already in the target folder has nothing to do: without this guard it
    # would collide with ITSELF and be sent to dup_dir (4059 screenshots once did).
    if same_path(os.path.dirname(src), target_folder):
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
    if same_path(src, dst):
        # Windows: same folder with different case -> NEVER merge into itself
        log(f"⚠️ Fusion refusée (même dossier, casse différente) : {src}")
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
            log(f"❌ Fusion {entry} : {e}")
            errors += 1
    try:
        if not os.listdir(src):
            os.rmdir(src)
    except Exception:
        pass
    return moved, dups, errors


def trash(path):
    """Recycle bin, never a hard delete"""
    from send2trash import send2trash
    send2trash(os.path.normpath(path))


def remove_empty_dirs(folder, keep_root=True):
    removed = 0
    for current, _dirs, _files in os.walk(folder, topdown=False):
        if keep_root and same_path(current, folder):
            continue
        try:
            if not os.listdir(current):
                os.rmdir(current)
                log(f"[PCLOUD]    🧹 dossier vide supprimé : {os.path.relpath(current, folder)}")
                removed += 1
        except OSError:
            pass
    return removed


# ==================== FOLDER NAMES ====================

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
    """Recursive file count (scandir: no extra stat call per file on Windows)"""
    total = 0
    try:
        with os.scandir(path) as it:
            for e in it:
                if e.is_dir(follow_symlinks=False):
                    total += count_files(e.path)
                else:
                    total += 1
    except OSError:
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
        log(f"❌ Lecture {os.path.basename(EXCLUSION_FILE)} : {e}")
    return pairs


def save_folder_exclusion(a, b):
    try:
        with open(EXCLUSION_FILE, 'a', encoding='utf-8') as f:
            f.write(f"{a} <> {b}\n")
    except Exception as e:
        log(f"❌ Écriture exclusion : {e}")


def month_of(name, year):
    m = re.match(rf'^{year}-(\d{{2}})', name)
    return m.group(1) if m else None


# ==================== PATH DIFF ====================

def _esc(s):
    return s.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')


def _dim(s):
    return f'<span class="d-same">{_esc(s)}</span>' if s else ''


def _hot(s):
    return f'<span class="d-hot">{_esc(s)}</span>' if s else ''


def _char_diff(a, b):
    """Character-level diff of two strings -> (html_a, html_b). When the strings
    are too far apart, highlighting a few shared letters would be confetti, so the
    whole segment lights up instead."""
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
    """Two relative paths -> (html_a, html_b) with only the differences highlighted"""
    parts_a = re.split(r'[\\/]', rel_a)
    parts_b = re.split(r'[\\/]', rel_b)
    out_a, out_b = [], []
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, parts_a, parts_b).get_opcodes():
        if tag == 'equal':
            out_a.extend(_dim(p) for p in parts_a[i1:i2])
            out_b.extend(_dim(p) for p in parts_b[j1:j2])
        elif tag == 'replace' and (i2 - i1) == (j2 - j1):
            for pa, pb in zip(parts_a[i1:i2], parts_b[j1:j2]):
                ha, hb = _char_diff(pa, pb)
                out_a.append(ha)
                out_b.append(hb)
        else:
            out_a.extend(_hot(p) for p in parts_a[i1:i2])
            out_b.extend(_hot(p) for p in parts_b[j1:j2])
    sep = '<span class="d-sep">\\</span>'
    return sep.join(out_a), sep.join(out_b)


# Markers Windows / phones / sync tools append when they duplicate a file:
#   photo_1.jpg   photo (1).jpg   photo - Copie.jpg   photo copy 2.jpg   photo~1.jpg
COPY_SUFFIX_RE = re.compile(
    r'^(?P<base>.+?)'
    r'(?:'
    r'[ _\-~]?\((?P<paren>\d{1,3})\)'
    r'|[ _\-~](?P<num>\d{1,3})'
    r'|[ _\-]?(?:copie|copy|kopie|copia)(?:[ _\-]?\d{1,3})?'
    r')$',
    re.IGNORECASE)


def copy_original_name(filename):
    """'x_1.jpg' -> 'x.jpg' when filename looks like a copy, else None"""
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


# ==================== FFMPEG ====================

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
    """configured folder -> default install -> app folder -> PATH -> imageio-ffmpeg"""
    global FFMPEG, FFPROBE, FFMPEG_TRIED
    FFMPEG_TRIED = []
    ffmpeg = ffprobe = None
    for folder in (extra_dir, DEFAULT_FFMPEG_DIR, ROOT):
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


_duration_cache = {}
_duration_lock = threading.Lock()


def video_duration(path):
    """Duration in seconds (ffprobe, else ffmpeg's banner). Cached per file version."""
    try:
        st = os.stat(path)
        key = (os.path.normcase(path), st.st_size, int(st.st_mtime))
    except OSError:
        return None
    with _duration_lock:
        if key in _duration_cache:
            return _duration_cache[key]
    duration = None
    if FFPROBE:
        try:
            r = subprocess.run([FFPROBE, '-v', 'error', '-show_entries', 'format=duration',
                                '-of', 'default=noprint_wrappers=1:nokey=1', path],
                               capture_output=True, text=True, timeout=15,
                               creationflags=NO_WINDOW)
            duration = float(r.stdout.strip())
        except Exception:
            duration = None
    if duration is None and FFMPEG:
        try:
            r = subprocess.run([FFMPEG, '-i', path], capture_output=True, text=True,
                               timeout=15, creationflags=NO_WINDOW)
            m = re.search(r'Duration:\s*(\d+):(\d\d):(\d\d\.\d+)', r.stderr or '')
            if m:
                duration = int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3))
        except Exception:
            pass
    with _duration_lock:
        _duration_cache[key] = duration
    return duration


def _file_key(path, extra=''):
    st = os.stat(path)
    raw = f"{os.path.normcase(os.path.abspath(path))}|{st.st_size}|{int(st.st_mtime)}|{extra}"
    return hashlib.sha1(raw.encode('utf-8')).hexdigest()


def shot_path(video_path, pct):
    """Where the frame at this percentage lives (existing or not)"""
    try:
        return os.path.join(FRAME_DIR, f"{_file_key(video_path)}_{pct:03d}.jpg")
    except OSError:
        return None


def grab_one_shot(video_path, pct):
    """One frame of the video, one ffmpeg call. Reused when already on disk."""
    out = shot_path(video_path, pct)
    if not FFMPEG or not out:
        return None
    if os.path.exists(out):
        return out
    duration = video_duration(video_path)
    if not duration or duration <= 0:
        return None
    try:
        os.makedirs(FRAME_DIR, exist_ok=True)
        ts = max(0, duration - 0.5) if pct >= 100 else (duration * pct) / 100
        tmp = out + f'.{threading.get_ident()}.jpg'
        subprocess.run([FFMPEG, '-v', 'error', '-ss', f"{ts:.3f}", '-i', video_path,
                        '-frames:v', '1', '-q:v', '3', '-y', tmp],
                       capture_output=True, timeout=25, creationflags=NO_WINDOW)
        if os.path.exists(tmp):
            os.replace(tmp, out)
    except Exception:
        return None
    return out if os.path.exists(out) else None


def purge_frames():
    """Video frames are cheap to rebuild: emptied on exit"""
    removed = 0
    if os.path.isdir(FRAME_DIR):
        for f in os.listdir(FRAME_DIR):
            try:
                os.remove(os.path.join(FRAME_DIR, f))
                removed += 1
            except OSError:
                pass
    return removed


def purge_legacy_temp(base_path):
    """The Qt edition kept its caches inside Camera: clean what it left behind"""
    for name in ('!temp', '!tempvideoscreen'):
        d = os.path.join(base_path, name)
        if not os.path.isdir(d):
            continue
        removed = 0
        for f in os.listdir(d):
            try:
                os.remove(os.path.join(d, f))
                removed += 1
            except OSError:
                pass
        try:
            os.rmdir(d)
        except OSError:
            pass
        if removed:
            log(f"🧹 {name} : {removed} fichier(s) temporaire(s) supprimé(s)")


# ==================== IMAGES ====================

def _open_scaled(path, max_side):
    """Decode downscaled: JPEG draft mode lets libjpeg skip most of the work"""
    img = Image.open(path)
    try:
        img.draft('RGB', (max_side, max_side))
    except Exception:
        pass
    img = ImageOps.exif_transpose(img)       # phones rely on the orientation tag
    img.thumbnail((max_side, max_side), RESAMPLE_FAST)
    if img.mode not in ('RGB', 'L'):
        img = img.convert('RGB')
    return img


def _jpeg_bytes(img, quality):
    from io import BytesIO
    buf = BytesIO()
    img.save(buf, 'JPEG', quality=quality, optimize=False)
    return buf.getvalue()


def thumbnail_file(path, size=THUMB_MAX):
    """Path of a cached JPEG thumbnail (built on first request, kept on disk)"""
    if not PIL_AVAILABLE:
        return None
    key = _file_key(path, f't{size}')
    out = os.path.join(THUMB_DIR, key[:2], key + '.jpg')
    if os.path.exists(out):
        return out
    source = path
    if os.path.splitext(path)[1].lower() in VIDEO_EXTS:
        source = grab_one_shot(path, DEFAULT_SHOT_PCT)
        if not source:
            return None
    img = _open_scaled(source, size)
    os.makedirs(os.path.dirname(out), exist_ok=True)
    tmp = out + f'.{threading.get_ident()}.tmp'
    with open(tmp, 'wb') as f:
        f.write(_jpeg_bytes(img, 82))
    os.replace(tmp, out)
    return out


_preview_cache = OrderedDict()
_preview_lock = threading.Lock()
PREVIEW_CACHE_MAX = 24


def preview_bytes(path, max_side=PREVIEW_MAX):
    """Screen-sized JPEG (HEIC included), kept in a small RAM LRU"""
    key = _file_key(path, f'p{max_side}')
    with _preview_lock:
        data = _preview_cache.get(key)
        if data is not None:
            _preview_cache.move_to_end(key)
            return data
    img = _open_scaled(path, max_side)
    data = _jpeg_bytes(img, 88)
    with _preview_lock:
        _preview_cache[key] = data
        while len(_preview_cache) > PREVIEW_CACHE_MAX:
            _preview_cache.popitem(last=False)
    return data


def prune_thumb_cache(limit=THUMB_CACHE_LIMIT):
    """Keep the persistent thumbnail cache under `limit` bytes (oldest go first)"""
    entries, total = [], 0
    for current, _dirs, files in os.walk(THUMB_DIR):
        for f in files:
            p = os.path.join(current, f)
            try:
                st = os.stat(p)
            except OSError:
                continue
            entries.append((st.st_atime, st.st_size, p))
            total += st.st_size
    if total <= limit:
        return 0
    removed = 0
    for _atime, size, p in sorted(entries):
        if total <= limit * 0.8:
            break
        try:
            os.remove(p)
            total -= size
            removed += 1
        except OSError:
            pass
    log(f"🧹 Cache vignettes : {removed} vignette(s) ancienne(s) supprimée(s)")
    return removed


# ==================== PERCEPTUAL COMPARISON ====================

HASH_SIZE = 8            # dHash grid -> 64 bits
SIM_IDENTICAL = 0.97     # visually the same shot
SIM_CLOSE = 0.88         # same scene, re-encoded / cropped a bit
SIM_RELATED = 0.72       # clearly related but not the same image


def dhash(img):
    small = img.convert('L').resize((HASH_SIZE + 1, HASH_SIZE), RESAMPLE_HQ)
    px = small.tobytes()
    bits = 0
    for r in range(HASH_SIZE):
        row = px[r * (HASH_SIZE + 1):(r + 1) * (HASH_SIZE + 1)]
        for c in range(HASH_SIZE):
            bits = (bits << 1) | (1 if row[c] < row[c + 1] else 0)
    return bits


def hash_similarity(h1, h2):
    return 1.0 - (bin(h1 ^ h2).count('1') / (HASH_SIZE * HASH_SIZE))


def hash_file(path):
    if not PIL_AVAILABLE:
        return None
    try:
        with Image.open(path) as img:
            try:
                img.draft('RGB', (256, 256))     # a hash needs 9x8 pixels, not 50 Mpx
            except Exception:
                pass
            return dhash(img)
    except Exception as e:
        log(f"❌ Empreinte {os.path.basename(path)} : {e}")
        return None


def human_size(n):
    if n is None:
        return "?"
    return f"{n / 1024:,.0f} Ko".replace(',', ' ') if n < 1024 * 1024 \
        else f"{n / 1048576:,.1f} Mo".replace(',', ' ')


def human_time(s):
    if s is None:
        return "?"
    return f"{int(s // 60)}:{int(s % 60):02d}" if s >= 60 else f"{s:.1f} s"


def fingerprint(path):
    """Size, duration (videos), visual hashes. Thread-safe."""
    fp = {'path': path, 'size': None, 'duration': None, 'hashes': [], 'kind': 'other'}
    try:
        fp['size'] = os.path.getsize(path)
    except OSError:
        return fp
    ext = os.path.splitext(path)[1].lower()
    if fp['size'] == 0:
        return fp                   # empty file (failed sync / copy): nothing to hash
    if ext in VIDEO_EXTS:
        fp['kind'] = 'video'
        fp['duration'] = video_duration(path)
        for pct in VIDEO_SAMPLE_POINTS:
            jpg = grab_one_shot(path, pct)
            h = hash_file(jpg) if jpg else None
            if h is not None:
                fp['hashes'].append(h)
    elif ext in IMAGE_EXTS:
        fp['kind'] = 'image'
        h = hash_file(path)
        if h is not None:
            fp['hashes'].append(h)
    return fp


def compare_fingerprints(fa, fb, identical_bytes=False):
    """Size, displayed content, duration -> one result. 'content' is the headline:
    two files can weigh the same and show something else entirely."""
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


def compare_files(pa, pb, cache=None):
    """Full comparison of two paths (byte check first, then fingerprints)"""
    identical = False
    if os.path.isfile(pa) and os.path.isfile(pb):
        try:
            identical = (os.path.getsize(pa) == os.path.getsize(pb)
                         and filecmp.cmp(pa, pb, shallow=False))
        except OSError:
            identical = False
    cache = cache if cache is not None else {}
    for p in (pa, pb):
        if p not in cache:
            cache[p] = fingerprint(p)
    return compare_fingerprints(cache[pa], cache[pb], identical)


def verdict_for(res):
    """level, short label, long label. level: same | close | related | diff | unknown"""
    if res and 0 in (res.get('size_a'), res.get('size_b')) and not res.get('identical'):
        if res.get('size_a') == 0:
            return 'unknown', "1 vide", ("La Copie 1 est un fichier vide (0 octet), la vraie image est la Copie 2. "
                                         "Maj+Suppr jette la Copie 1 — « Tout traiter » ne touche pas à cette ligne")
        return 'unknown', "2 vide", "La Copie 2 est un fichier vide (0 octet) — copie ratée, Suppr pour la jeter"
    if not res or res.get('content') is None:
        return 'unknown', "?", "Comparaison impossible (fichier illisible)"
    score = res['content']
    pct = f"{score * 100:.0f} %"
    dur_off = res.get('dur_ratio') is not None and res['dur_ratio'] < 0.98
    if res.get('identical'):
        return 'same', "100 %", "Fichiers identiques octet pour octet — doublon certain"
    if dur_off and score >= SIM_CLOSE:
        # Same imagery but one is longer: a trimmed or extended version, not a copy
        return ('related', pct,
                f"Images proches ({pct}) mais durées différentes "
                f"({human_time(res['dur_a'])} vs {human_time(res['dur_b'])}) — versions distinctes")
    if score >= SIM_IDENTICAL:
        return 'same', pct, f"Contenu identique ({pct}) — doublon confirmé"
    if score >= SIM_CLOSE:
        return 'close', pct, f"Très proche ({pct}) — même prise, encodage ou recadrage différent"
    if score >= SIM_RELATED:
        return 'related', pct, f"Lié mais différent ({pct}) — à vérifier à l'œil"
    return 'diff', pct, f"Contenu différent ({pct}) — ce n'est pas un doublon"


def verdict_details(res):
    if not res:
        return ""
    bits = []
    sa, sb = res.get('size_a'), res.get('size_b')
    if sa == sb and sa is not None:
        bits.append(f"taille identique ({human_size(sa)})")
    else:
        bits.append(f"taille {human_size(sa)} vs {human_size(sb)}")
    da, db = res.get('dur_a'), res.get('dur_b')
    if da or db:
        if da and db and abs(da - db) < 0.05:
            bits.append(f"durée identique ({human_time(da)})")
        else:
            bits.append(f"durée {human_time(da)} vs {human_time(db)}")
    c = res.get('content')
    bits.append(f"contenu {c * 100:.0f} %" if c is not None else "contenu illisible")
    return "  ·  ".join(bits)
