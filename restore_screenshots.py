#!/usr/bin/env python3
"""
Repechage des captures envoyees par erreur dans !duplicate.

Cause : l'onglet Tri pre-remplissait la colonne Dossier avec l'emplacement
courant du fichier. APPLIQUER deplacait donc chaque capture vers son propre
dossier ; safe_move voyait un fichier de meme nom et meme taille a l'arrivee
(le fichier lui-meme) et l'envoyait dans !duplicate.

Ce script les remet dans Camera\\ANNEE\\!Screenshots_ANNEE\\<Appli>.
Un fichier n'est PAS repeche s'il existe deja ailleurs dans l'arbre Camera
(meme nom, meme taille) : c'est un vrai doublon, il reste dans !duplicate.

Usage :
    python restore_screenshots.py                 # simulation, ne bouge rien
    python restore_screenshots.py --apply         # effectue les deplacements
"""
import ast
import os
import re
import shutil
import sys
from datetime import datetime

CAMERA = r"P:\AutoUpload\Xiaomi 2407FPN8EG\DCIM\Camera"
HERE = os.path.dirname(os.path.abspath(__file__))


def load_helpers():
    """Recupere app_from_filename et datetime_from_name depuis TriPhoto.py SANS
    l'importer : un import declencherait la verification des dependances et le
    chargement de Qt, inutiles ici."""
    src = open(os.path.join(HERE, 'TriPhoto.py'), encoding='utf-8').read()
    tree = ast.parse(src)
    lines = src.split('\n')
    ns = {'os': os, 're': re, 'datetime': datetime}
    want_assign = {'APP_NAMES', 'APP_NAMES_LOWER', 'GENERIC_SEGMENTS', 'DATETIME_PATTERNS'}
    want_def = {'app_from_filename', 'datetime_from_name'}
    for node in tree.body:
        name = None
        if isinstance(node, ast.Assign) and node.targets and hasattr(node.targets[0], 'id'):
            name = node.targets[0].id if node.targets[0].id in want_assign else None
        elif isinstance(node, ast.FunctionDef) and node.name in want_def:
            name = node.name
        if name:
            exec('\n'.join(lines[node.lineno - 1:node.end_lineno]), ns)
    missing = want_def - set(ns)
    if missing:
        raise RuntimeError(f"introuvables dans TriPhoto.py : {', '.join(sorted(missing))}")
    return ns['app_from_filename'], ns['datetime_from_name']


try:
    app_from_filename, datetime_from_name = load_helpers()
except Exception as exc:                                   # pragma: no cover
    print(f"Lecture de TriPhoto.py impossible : {exc}")
    sys.exit(1)


def bucket_for(name):
    """(annee, nom du vivier) d'apres le nom du fichier, ou (None, None)"""
    dt = datetime_from_name(name)
    if not dt:
        return None, None
    low = name.lower()
    if low.startswith('screenshot'):
        return str(dt.year), 'Screenshots'
    if low.startswith('screenrecorder') or low.startswith('screen_recorder'):
        return str(dt.year), 'ScreenRecorder'
    return None, None


def base_name(name):
    """'x_1.jpg' -> 'x.jpg' (suffixe ajoute par le compteur anti-collision)"""
    stem, ext = os.path.splitext(name)
    m = re.match(r'^(.+)_(\d{1,2})$', stem)
    return (m.group(1) + ext) if m else None


def index_camera(camera, dup_dir):
    """{nom de fichier: [(chemin, taille), ...]} pour tout l'arbre SAUF !duplicate.

    C'est ce qui permet de dire : cette capture existe deja ailleurs, donc elle
    reste dans !duplicate au lieu d'etre remise en double."""
    index = {}
    dup_norm = os.path.normcase(os.path.abspath(dup_dir))
    for current, dirs, files in os.walk(camera):
        if os.path.normcase(os.path.abspath(current)).startswith(dup_norm):
            dirs[:] = []
            continue
        for name in files:
            path = os.path.join(current, name)
            try:
                size = os.path.getsize(path)
            except OSError:
                size = -1
            index.setdefault(name, []).append((path, size))
    return index


def main(apply_changes):
    dup_dir = os.path.join(CAMERA, '!duplicate')
    if not os.path.isdir(dup_dir):
        print(f"Dossier introuvable : {dup_dir}")
        return

    print("Indexation de l'arbre Camera...")
    index = index_camera(CAMERA, dup_dir)
    print(f"  {len(index)} nom(s) de fichier deja presents ailleurs\n")

    restored = elsewhere = conflict = skipped = errors = 0
    for name in sorted(os.listdir(dup_dir)):
        src = os.path.join(dup_dir, name)
        if not os.path.isfile(src):
            continue
        year, kind = bucket_for(name)
        if not year:
            skipped += 1                                    # pas une capture
            continue
        try:
            size = os.path.getsize(src)
        except OSError:
            size = -1

        # Deja quelque part dans l'arbre ? (sous son nom, ou sans le suffixe _N)
        twin = base_name(name)
        candidates = index.get(name, []) + (index.get(twin, []) if twin else [])
        if candidates:
            if any(s == size for _p, s in candidates):
                elsewhere += 1                              # meme nom, meme taille
                continue
            conflict += 1                                   # meme nom, taille differente
            if conflict <= 5:
                where = os.path.relpath(candidates[0][0], CAMERA)
                print(f"  ? {name}\n      existe en {where} avec une taille differente"
                      f" -> laisse dans !duplicate")
            continue

        target_dir = os.path.join(CAMERA, year, f"!{kind}_{year}")
        app = app_from_filename(name) if kind == 'Screenshots' else None
        if app:
            target_dir = os.path.join(target_dir, app)

        if apply_changes:
            try:
                os.makedirs(target_dir, exist_ok=True)
                shutil.move(src, os.path.join(target_dir, name))
                restored += 1
            except Exception as exc:
                print(f"  ERREUR {name} : {exc}")
                errors += 1
        else:
            restored += 1
            if restored <= 15:
                print(f"  + {name}  ->  {year}\\!{kind}_{year}"
                      + (f"\\{app}" if app else ""))

    print()
    print(f"  a repecher                        : {restored}")
    print(f"  deja ailleurs -> reste !duplicate : {elsewhere}")
    print(f"  meme nom mais taille differente   : {conflict}")
    print(f"  ignores (pas une capture)         : {skipped}")
    if errors:
        print(f"  erreurs                           : {errors}")
    if not apply_changes:
        print("\nSimulation. Relance avec --apply pour effectuer les deplacements.")


if __name__ == '__main__':
    main('--apply' in sys.argv)
