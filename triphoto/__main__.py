"""python -m triphoto [--port N] [--no-import] [--open]"""

import argparse
import os
import subprocess
import sys


def ensure_packages():
    """Install what is missing (TriPhoto.ps1 does it too, this covers a direct launch)"""
    required = {'PIL': 'pillow', 'pillow_heif': 'pillow-heif', 'send2trash': 'send2trash'}
    missing = []
    for module, package in required.items():
        try:
            __import__(module)
        except ImportError:
            missing.append(package)
    if missing:
        print(f"Installation : {', '.join(missing)}…", flush=True)
        subprocess.run([sys.executable, '-m', 'pip', 'install', '--quiet', *missing],
                       creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
        import importlib
        importlib.invalidate_caches()


def main():
    parser = argparse.ArgumentParser(prog='triphoto')
    parser.add_argument('--port', type=int, default=0, help="0 = un port libre au hasard")
    parser.add_argument('--no-import', action='store_true',
                        help="ne pas vider pCloud au démarrage (tests)")
    parser.add_argument('--open', action='store_true', help="ouvrir le navigateur par défaut")
    args = parser.parse_args()
    ensure_packages()

    from . import server
    if args.open:
        import threading
        import webbrowser
        import time
        import json

        def opener():
            for _ in range(50):
                time.sleep(0.2)
                try:
                    with open(server.PORT_FILE, encoding='utf-8') as f:
                        port = json.load(f)['port']
                    webbrowser.open(f"http://127.0.0.1:{port}/")
                    return
                except Exception:
                    pass
        threading.Thread(target=opener, daemon=True).start()
    server.run(port=args.port, no_import=args.no_import)


if __name__ == '__main__':
    main()
