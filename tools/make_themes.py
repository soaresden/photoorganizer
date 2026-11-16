"""Generate TriPhoto's colour themes from compact palettes.

Each palette comes from one of Denis's other projects (named in `src`). Only the
seven base colours are written by hand; every other token (hover, borders,
status colours, text on accent...) is derived here, and contrasts are checked so
that no theme ends up unreadable. The output replaces two marked regions:

    triphoto/web/app.css   /* @themes:begin */ ... /* @themes:end */
    triphoto/web/app.js    // @themes:begin ... // @themes:end

Run:  python tools/make_themes.py
"""
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CSS = os.path.join(ROOT, 'triphoto', 'web', 'app.css')
JS = os.path.join(ROOT, 'triphoto', 'web', 'app.js')

SERIF = '"Palatino Linotype", "Book Antiqua", Georgia, serif'
COND = 'Bahnschrift, "Segoe UI Variable Display", "Arial Narrow", sans-serif'
MONO = '"Cascadia Mono", Consolas, "Lucida Console", monospace'
SCRIPT = '"Segoe Script", "Segoe Print", cursive'
HAND = '"Segoe Print", "Ink Free", cursive'
PUNCH = 'Impact, "Arial Black", sans-serif'
DISPLAY = '"Segoe UI Variable Display", "Segoe UI", system-ui, sans-serif'

H = '[data-theme="{id}"] :is(.topbar h1, .brand b)'

# id, name, group, source project, light?, bg, panel, line, text, muted, accent, accent-2, extras
# Themes marked manual=True are hand-written further down in app.css: only listed.
T = [
    # ------------------------------------------------------------- Sobres
    dict(id='nuit', name='Nuit', group='Sobres', src='TriPhoto', manual=True,
         c=['#0b0d12', '#151922', '#e8ebf2', '#8b7cff', '#5ec8ff']),
    dict(id='ardoise', name='Ardoise', group='Sobres', src='FuelTrajetMap',
         p='#16181c #1f2228 #3a3f48 #eceff3 #a0a7b3 #5aa9ff #f0b45a'),
    dict(id='amoled', name='AMOLED', group='Sobres', src='IX7TrackerPro',
         p='#000000 #121214 #2c2c30 #ffffff #8a8a93 #0a84ff #64d2ff', deco='none'),
    dict(id='encre', name='Encre', group='Sobres', src='myhtml',
         p='#12110f #1b1a17 #32302b #eeebe3 #a39d90 #e11d74 #e9a23b', font=DISPLAY),
    dict(id='papier', name='Papier', group='Sobres', src='myhtml', light=True,
         p='#f4f1ea #fffdf8 #e3ded3 #1c1b18 #6b665b #c8186a #0f7c74', font=DISPLAY),
    dict(id='clair', name='Clair', group='Sobres', src='IX7TrackerPro · PlongeeJournal', light=True,
         p='#f2f4f8 #ffffff #d8dee6 #13222f #4b6273 #0a6fc2 #0f8f73'),

    # ------------------------------------------------------------- Océan
    dict(id='plongee', name='Plongée', group='Océan & plongée', src='TriPhoto', manual=True,
         c=['#03141c', '#08303f', '#e0f7fb', '#22e3d3', '#3a8dff']),
    dict(id='abysses', name='Abysses', group='Océan & plongée', src='MN90Mobile · PlongeeJournal',
         p='#020409 #0b1120 #1f2b47 #dbe7ff #8d9cbd #5eead4 #a78bfa',
         deco='radial-gradient(circle at 8% 82%, #5eead433 0 2px, transparent 3px), '
              'radial-gradient(circle at 22% 64%, #a78bfa2e 0 1.5px, transparent 2.5px), '
              'radial-gradient(circle at 74% 88%, #5eead42a 0 2.5px, transparent 3.5px), '
              'radial-gradient(circle at 91% 40%, #a78bfa26 0 2px, transparent 3px), '
              'radial-gradient(circle at 55% 30%, #5eead41f 0 1.5px, transparent 2.5px), '
              'radial-gradient(ellipse 80% 60% at 50% 120%, #5eead414, transparent 70%)'),
    dict(id='grandsfonds', name='Grands fonds', group='Océan & plongée', src='MN90Mobile',
         p='#03101c #0a2236 #1f4a5e #dcf7f4 #86bdb6 #2dd4bf #38bdf8'),
    dict(id='recif', name='Récif corallien', group='Océan & plongée', src='PlongeeJournal',
         p='#1a0f1d #2a1830 #4a2c50 #fbe9ee #d1a9b8 #ff6f61 #4fd1c5'),
    dict(id='kelp', name='Forêt de kelp', group='Océan & plongée', src='PlongeeJournal',
         p='#071612 #0f2620 #22473a #e3f5ec #94c2ab #5fd39a #e3c55b',
         deco='linear-gradient(100deg, transparent 15%, #e3c55b0a 24%, transparent 33%, transparent 58%, #5fd39a08 66%, transparent 74%), '
              'radial-gradient(ellipse 90% 60% at 50% -10%, #5fd39a1c, transparent 70%)'),
    dict(id='epave', name='Épave', group='Océan & plongée', src='PlongeeJournal',
         p='#0f1512 #1b2420 #34433a #e9e4d6 #aaa58f #d99a3d #6fb3a3', font=SERIF),
    dict(id='nudibranche', name='Nudibranche', group='Océan & plongée', src='MN90Mobile · PlongeeJournal',
         p='#170d2b #271846 #4c2f7a #f4ecff #b3a2d4 #fb923c #c084fc'),
    dict(id='hippocampe', name='Hippocampe', group='Océan & plongée', src='MN90Mobile',
         p='#06212a #0e3442 #24596b #f4efe1 #b3ad98 #f5b83d #4fc3c9'),
    dict(id='lagon', name='Lagon', group='Océan & plongée', src='PlongeeJournal', light=True,
         p='#e7f8f6 #ffffff #bfe5e0 #0b3a3a #3e6b69 #088f86 #0a7fa8'),
    dict(id='cousteau', name='Cousteau', group='Océan & plongée', src='PlongeeJournal', light=True,
         p='#f3ecdc #fffaf0 #d9c9a6 #13243d #44546d #c8102e #1f4e79', font=SERIF,
         extra='[data-theme="{id}"] .brand .logo { background: #13243d; }'),
    dict(id='tortue', name='Tortue', group='Océan & plongée', src='MN90Mobile · PlongeeJournal', light=True,
         p='#eaf3e8 #ffffff #b5cfae #132313 #516d55 #2f6b3a #b8680f'),

    # ------------------------------------------------------------- Jeux vidéo
    dict(id='zelda', name='Zelda', group='Jeux vidéo', src='zelda-manager', manual=True,
         c=['#0d1710', '#1a2b1f', '#f2ebd3', '#d9b44a', '#63c06d']),
    dict(id='oracle', name='Oracle', group='Jeux vidéo', src='ZeldaOracleCombinedFR',
         p='#0d0a1a #17122f #2c2550 #f4f0ff #aaa2c8 #f2741a #5aa8f8', font=SERIF,
         extra=H + ' { color: #f0c45a; letter-spacing: .6px; }'),
    dict(id='koholint', name='Koholint', group='Jeux vidéo', src='ZeldaGullsOfLife · LADXR',
         p='#0d2459 #13307a #2b5fc0 #fdfaf2 #c7d6f2 #ffd23f #ff5a6a', radius='12px',
         deco='repeating-linear-gradient(180deg, transparent 0 38px, #e8f4ff10 38px 40px, transparent 40px 80px), '
              'radial-gradient(ellipse 120% 50% at 50% -15%, #8fc8f533, transparent 70%), '
              'linear-gradient(180deg, #183f8a 0%, #0d2459 100%)',
         extra=H + ' { color: #ffd23f; }'),
    dict(id='retrogamer', name='RetroGamer', group='Jeux vidéo', src='TriPhoto', manual=True,
         c=['#08040f', '#190f2e', '#f5f0ff', '#ff2fd0', '#22f0ff']),
    dict(id='gameboy', name='Game Boy', group='Jeux vidéo', src='XplosiveAdventures',
         p='#0f380f #184a1a #306230 #d6ea8a #8bac0f #9bbc0f #f2f8c8', font=MONO, radius='3px',
         deco='radial-gradient(#0f380f 1px, transparent 1.5px) 0 0 / 6px 6px, linear-gradient(#123f12, #0c300c)',
         extra=H + ' { text-transform: uppercase; letter-spacing: 1px; }'),
    dict(id='gtbleu', name='GT Bleu', group='Jeux vidéo', src='GranTurismo1-OverlayCheat',
         p='#060b18 #0c1530 #1f2c4f #eef2fb #9ba7c4 #3b7cf0 #6fd3ff', font=COND,
         deco='linear-gradient(115deg, transparent 58%, #2a5fcf1f 58% 61%, transparent 61% 63%, #2a5fcf14 63% 64.5%, transparent 64.5%), '
              'radial-gradient(ellipse 60% 50% at 100% 0%, #2f6fe026, transparent 70%)',
         extra=H + ' { font-style: italic; letter-spacing: .5px; }'),
    dict(id='gtorange', name='GT Orange', group='Jeux vidéo', src='GranTurismo2-OverlayCheat',
         p='#050505 #0f0f0f #2a2a2a #f4f4f4 #a9a9a9 #f39200 #8fb8e8', font=COND,
         deco='linear-gradient(115deg, transparent 58%, #c4570f24 58% 61%, transparent 61% 63%, #e07a1f18 63% 64.5%, transparent 64.5%), '
              'radial-gradient(ellipse 60% 50% at 100% 0%, #f3920018, transparent 70%)',
         extra=H + ' { font-style: italic; letter-spacing: .5px; }'),
    dict(id='mostwanted', name='Most Wanted', group='Jeux vidéo', src='MazdaMx5NDRF', font=COND,
         p='#090a07 #13140f #2c2e24 #f1f1ea #a9ab98 #f2c316 #9fd36b',
         deco='repeating-linear-gradient(135deg, #f2c3160a 0 14px, transparent 14px 28px)',
         extra=H + ' { text-transform: uppercase; letter-spacing: 1.5px; }'),
    dict(id='underground', name='Underground', group='Jeux vidéo', src='MazdaMx5NDRF', font=COND,
         p='#07050c #16141c #3a3644 #f0eef4 #b0aabd #c6ef4f #c35cff',
         deco='radial-gradient(ellipse 50% 40% at 0% 100%, #c35cff22, transparent 70%), '
              'radial-gradient(ellipse 45% 35% at 100% 0%, #f06bd71a, transparent 70%)',
         extra=H + ' { font-style: italic; text-shadow: 0 0 12px #c6ef4f55; }'),
    dict(id='shadowmoses', name='Shadow Moses', group='Jeux vidéo', src='SoundBoardHTMLMaker · MGS1-VOSTFR',
         p='#070a1f #111737 #2c3a78 #e3e8ff #9aa6d6 #7aa7ff #ff4d5e', font=COND,
         deco='repeating-linear-gradient(0deg, #7aa7ff08 0 1px, transparent 1px 4px), '
              'radial-gradient(ellipse 60% 50% at 0% 0%, #5b7cff1f, transparent 70%)',
         extra=H + ' { text-transform: uppercase; letter-spacing: 2px; }'),
    dict(id='codec', name='Codec', group='Jeux vidéo', src='MGS1-VOSTFR', light=True,
         p='#c9d5e2 #f3f6f9 #b7c4d2 #1d2733 #556474 #2d5f92 #1c8a52', font=COND,
         extra=H + ' { text-transform: uppercase; letter-spacing: 1.5px; }'),
    dict(id='manoir', name='Manoir', group='Jeux vidéo', src='Resident Evil 1 Hotkey',
         p='#141211 #1e1b19 #35302c #ece7e1 #a39b92 #c8392b #6fae5a', font=SERIF,
         deco='radial-gradient(ellipse 70% 60% at 50% 120%, #8f1d141f, transparent 70%)'),
    dict(id='anime', name='Anime', group='Jeux vidéo', src='DBZPokemonFR',
         p='#0d1530 #16214a #2b3768 #f3f5ff #a8b2d8 #ff8a1f #ffd23f', font=PUNCH,
         deco='radial-gradient(ellipse 70% 45% at 50% -10%, #2b3f8f66, transparent 70%)',
         extra=H + ' { letter-spacing: 1px; color: #ffd23f; text-shadow: 2px 2px 0 #ff8a1f88; }'),

    # ------------------------------------------------------------- Ambiances
    dict(id='violon', name='Violon', group='Ambiances', src='TriPhoto', manual=True, light=True,
         c=['#efe5d6', '#fbf7f0', '#2a1a0f', '#9c3f1b', '#c98a2b']),
    dict(id='moulinrouge', name='Moulin Rouge', group='Ambiances', src='Bodycount',
         p='#2a0409 #33060d #5c2418 #fff2e0 #d9a9a0 #ff2d46 #f5c04a', font=SERIF,
         deco='repeating-linear-gradient(90deg, #8e0a1c1c 0 26px, #c8102e10 26px 52px), '
              'radial-gradient(ellipse 50% 60% at 50% -5%, #f5c04a1f, transparent 70%)',
         extra=H + ' { color: #f5c04a; text-shadow: 0 0 10px #ff2d4666; }'),
    dict(id='glamour', name='Glamour', group='Ambiances', src='Bodycount',
         p='#0b0906 #12100b #3d3418 #f6ecd6 #a99c7e #d4af37 #f7e7b4', font=SERIF, radius='4px',
         deco='repeating-linear-gradient(45deg, #d4af3707 0 1px, transparent 1px 18px), '
              'repeating-linear-gradient(-45deg, #d4af3707 0 1px, transparent 1px 18px)',
         extra=H + ' { background: linear-gradient(90deg, #b8912a, #f7e7b4, #d4af37); '
                   '-webkit-background-clip: text; background-clip: text; color: transparent; }'),
    dict(id='synthwave', name='Synthwave', group='Ambiances', src='Bodycount',
         p='#07021a #0c0426 #3b1660 #f3ebff #9c8cc4 #ff2fd6 #19f0ff', font=DISPLAY,
         deco='linear-gradient(180deg, transparent 70%, #ff2fd614 100%), '
              'repeating-linear-gradient(90deg, #b14bff12 0 1px, transparent 1px 60px), '
              'linear-gradient(180deg, transparent 72%, #19f0ff0d 72.3%, transparent 72.6%)',
         extra=H + ' { text-shadow: 0 0 8px #ff2fd6, 0 0 20px #b14bff88; }'),
    dict(id='miami', name='Miami 86', group='Ambiances', src='Bodycount',
         p='#2a0e4a #36145c #5a2a7a #fff0f8 #c99bd0 #ff3ea5 #34e0e8', font=SCRIPT,
         deco='radial-gradient(ellipse 80% 50% at 50% 115%, #ff3ea52b, transparent 70%), '
              'radial-gradient(ellipse 40% 40% at 100% 0%, #34e0e81c, transparent 70%)',
         extra=H + ' { color: #34e0e8; text-shadow: 2px 2px 0 #ff3ea5; }'),
    dict(id='cyberpunk', name='Cyberpunk', group='Ambiances', src='Bodycount',
         p='#0b0b14 #10101c #3a3816 #e8f9ff #8aa0b0 #fcee0a #00f0ff', font=MONO, radius='2px',
         deco='linear-gradient(135deg, #fcee0a0d 0 10%, transparent 10%), '
              'repeating-linear-gradient(0deg, #00f0ff06 0 1px, transparent 1px 3px)',
         extra=H + ' { text-transform: uppercase; letter-spacing: 2px; color: #fcee0a; '
                   'text-shadow: -1.5px 0 #ff2d6f, 1.5px 0 #00f0ff; }'),
    dict(id='tuning', name='Tuning', group='Ambiances', src='Bodycount', font=COND,
         p='#0b0b10 #141418 #2e2e33 #f2f2f2 #9aa0a6 #ff5a00 #00e5ff',
         deco='repeating-conic-gradient(#ffffff05 0 25%, transparent 0 50%) 0 0 / 8px 8px, '
              'radial-gradient(ellipse 60% 30% at 50% 110%, #00e5ff1a, transparent 70%)',
         extra=H + ' { font-style: italic; text-transform: uppercase; letter-spacing: 1px; }'),
    dict(id='voyage', name='Voyageur', group='Ambiances', src='Bodycount', light=True,
         p='#efe2c4 #faf2df #d8c7a0 #3b2a1a #7a6248 #c0392b #1f4e79', font=SERIF,
         deco='radial-gradient(circle at 92% 86%, transparent 46px, #c0392b14 47px 49px, transparent 50px), '
              'radial-gradient(circle at 8% 14%, transparent 36px, #1f4e7912 37px 39px, transparent 40px)',
         extra=H + ' { font-style: italic; }'),
    dict(id='calin', name='Câlin', group='Ambiances', src='Bodycount', font=HAND, radius='14px',
         p='#2b1a1e #352227 #5a3a42 #fff4ec #d6b3ae #ff9eb5 #ffd8a8'),
    dict(id='pilipili', name='PiliPili', group='Ambiances', src='PiliPili Tab', font=PUNCH,
         p='#240b1f #3a1233 #5e2352 #fff4e3 #c89cbd #ff2e88 #14c8b4',
         deco='radial-gradient(circle at 15% 20%, #ffd23f14 0 60px, transparent 61px), '
              'radial-gradient(circle at 85% 75%, #14c8b412 0 90px, transparent 91px)',
         extra=H + ' { letter-spacing: 1px; text-shadow: 2px 2px 0 #ff2e88, 4px 4px 0 #12040e; }'),
    dict(id='halloween', name='Halloween', group='Ambiances', src='XplosiveAdventures',
         p='#1c1026 #2a1838 #5b3a7a #ffe8cc #b69ac8 #ff8c1a #b98ae6',
         deco='radial-gradient(circle at 88% 12%, #ffe8cc1c 0 34px, transparent 35px), '
              'radial-gradient(ellipse 70% 40% at 50% 115%, #ff8c1a1f, transparent 70%)'),
    dict(id='noel', name='Noël', group='Ambiances', src='XplosiveAdventures',
         p='#0f2a1c #163a27 #2e7d4f #ffffff #a9cdb5 #e0353f #f2c14e',
         deco='radial-gradient(circle at 10% 15%, #ffffff22 0 1.5px, transparent 2.5px), '
              'radial-gradient(circle at 30% 45%, #ffffff1a 0 2px, transparent 3px), '
              'radial-gradient(circle at 62% 22%, #ffffff1f 0 1.5px, transparent 2.5px), '
              'radial-gradient(circle at 84% 58%, #ffffff1a 0 2px, transparent 3px), '
              'radial-gradient(circle at 48% 80%, #ffffff17 0 1.5px, transparent 2.5px)'),
    dict(id='holi', name='Holi', group='Ambiances', src='PlongeeJournal', light=True,
         p='#fff8f2 #ffffff #f3d9e3 #2b1638 #6a4a72 #d0127a #10865a',
         deco='radial-gradient(circle at 0% 0%, #e0157f1a, transparent 30%), '
              'radial-gradient(circle at 100% 10%, #ff7a001a, transparent 28%), '
              'radial-gradient(circle at 90% 100%, #10965a17, transparent 30%), '
              'radial-gradient(circle at 10% 95%, #2d55dc14, transparent 28%)'),
    dict(id='coucher', name='Coucher de soleil', group='Ambiances', src='MN90Mobile', light=True,
         p='#fbf3ea #ffffff #e5c4a4 #2b1a08 #7a5333 #b23c0e #7d3c98',
         deco='linear-gradient(180deg, #ff925418 0%, transparent 35%)'),
    dict(id='lavande', name='Lavande', group='Ambiances', src='FuelTrajetMap', light=True,
         p='#f4f1fb #fdfcff #d7cdee #2a2140 #6b6190 #6f4ce0 #2a8f78'),
    dict(id='ambre', name='Ambre', group='Ambiances', src='FuelTrajetMap',
         p='#17130d #221c13 #4a3d27 #f1e3c2 #b49f76 #ffa53a #8fb3d9', font=SERIF),
]


# ------------------------------------------------------------------ colour maths

def rgb(h):
    h = h.lstrip('#')
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def hexc(c):
    return '#' + ''.join(f'{max(0, min(255, round(v))):02x}' for v in c)


def mix(a, b, t):
    """t = share of b"""
    a, b = rgb(a), rgb(b)
    return hexc(tuple(x + (y - x) * t for x, y in zip(a, b)))


def lum(h):
    def ch(v):
        v /= 255
        return v / 12.92 if v <= .03928 else ((v + .055) / 1.055) ** 2.4
    r, g, b = (ch(v) for v in rgb(h))
    return .2126 * r + .7152 * g + .0722 * b


def contrast(a, b):
    la, lb = sorted((lum(a), lum(b)), reverse=True)
    return (la + .05) / (lb + .05)


def push(color, against, toward, target):
    """Move color toward `toward` until it reaches `target` contrast with `against`"""
    t = 0
    c = color
    while contrast(c, against) < target and t < 1:
        t += .04
        c = mix(color, toward, t)
    return c


warnings = []


def build(th):
    bg, panel, line, text, muted, acc, acc2 = th['p'].split()
    light = th.get('light', False)
    toward = text  # pull towards the text colour when contrast is short
    muted = push(muted, panel, toward, 3.2)
    for name in ('acc', 'acc2'):
        c0 = locals()[name]
        c = push(c0, panel, toward if light else '#ffffff', 3.0)
        if c != c0:
            warnings.append(f"{th['id']}: {name} {c0} -> {c} (contraste)")
        if name == 'acc':
            acc = c
        else:
            acc2 = c
    if contrast(text, panel) < 7:
        warnings.append(f"{th['id']}: texte/panneau {contrast(text, panel):.1f}")
    dark_on = mix(acc, '#000000', .82)
    on_acc = '#ffffff' if contrast('#ffffff', acc) >= contrast(dark_on, acc) else dark_on
    if light:
        bg2 = mix(bg, panel, .3)
        panel2 = mix(panel, bg, .55)
        hover = mix(panel, line, .55)
        line2 = mix(line, text, .16)
        status = dict(ok='#1e8a4f', warn='#9a6a00', orange='#c25418', bad='#c1323e')
        stage = mix(text, '#000000', .35)
        nav = f'linear-gradient(180deg, {mix(bg, panel, .5)} 0%, {mix(bg, line, .35)} 100%)'
        shadow = f'0 10px 40px color-mix(in srgb, {text} 22%, transparent)'
    else:
        bg2 = mix(bg, panel, .25)
        panel2 = mix(panel, text, .035)
        hover = mix(panel, text, .08)
        line2 = mix(line, text, .12)
        status = dict(ok='#3ddc97', warn='#f5c451', orange='#ff9f5a', bad='#ff6b7a')
        stage = mix(bg, '#000000', .45)
        nav = f'linear-gradient(180deg, {mix(panel, bg, .45)} 0%, {bg} 100%)'
        shadow = None
    deco = th.get('deco') or (
        f'radial-gradient(ellipse 60% 45% at 100% 0%, color-mix(in srgb, {acc} {12 if light else 9}%, transparent), transparent 70%), '
        f'radial-gradient(ellipse 70% 50% at 0% 100%, color-mix(in srgb, {acc2} {10 if light else 7}%, transparent), transparent 70%)')
    tid = th['id']
    out = [f'/* {th["name"]} — couleurs de {th["src"]} */', f'[data-theme="{tid}"] {{']
    out.append(f'  --bg: {bg}; --bg-2: {bg2}; --panel: {panel}; --panel-2: {panel2}; --hover: {hover};')
    out.append(f'  --line: {line}; --line-2: {line2}; --text: {text}; --text-2: {mix(text, muted, .45)}; --muted: {muted};')
    out.append(f'  --accent: {acc}; --accent-2: {acc2}; --on-accent: {on_acc}; --info: {acc2};')
    out.append(f'  --accent-bg: color-mix(in srgb, {acc} 15%, transparent); --sel: color-mix(in srgb, {acc} 23%, transparent);')
    out.append('  ' + ' '.join(f'--{k}: {v};' for k, v in status.items()))
    out.append(f'  --nav-bg: {nav}; --stage: {stage};')
    if shadow:
        out.append(f'  --shadow: {shadow};')
    if th.get('radius'):
        r = th['radius']
        out.append(f'  --radius: {r}; --radius-s: calc({r} * .7);')
    if th.get('font'):
        out.append(f'  --font-head: {th["font"]};')
    out.append(f'  --deco: {deco};')
    if light:
        out.append('  color-scheme: light;')
    out.append('}')
    if th.get('extra'):
        out.append(th['extra'].replace('{id}', tid))
    th['c'] = [bg, panel, text, acc, acc2]
    return '\n'.join(out)


def main():
    blocks = [build(th) for th in T if not th.get('manual')]
    lights = [th['id'] for th in T if th.get('light')]
    sel = ', '.join(f'[data-theme="{i}"]' for i in lights)
    blocks.append(f'/* light themes: a lighter veil behind dialogs */\n:is({sel}) .backdrop '
                  '{ background: color-mix(in srgb, var(--text) 40%, transparent); }')
    css_block = '/* @themes:begin — generated by tools/make_themes.py, do not edit by hand */\n' \
                + '\n\n'.join(blocks) + '\n/* @themes:end */'

    js_lines = ['// @themes:begin — generated by tools/make_themes.py', 'const THEMES = [']
    for th in T:
        c = ', '.join(f"'{x}'" for x in th['c'])
        js_lines.append(f"  {{ id: '{th['id']}', name: '{th['name']}', group: '{th['group']}', "
                        f"from: '{th['src']}', c: [{c}] }},")
    js_lines += ['];', '// @themes:end']
    js_block = '\n'.join(js_lines)

    css = open(CSS, encoding='utf-8').read()
    css = re.sub(r'/\* @themes:begin.*?/\* @themes:end \*/', lambda _: css_block, css, flags=re.S)
    open(CSS, 'w', encoding='utf-8', newline='').write(css)
    js = open(JS, encoding='utf-8').read()
    js = re.sub(r'// @themes:begin.*?// @themes:end', lambda _: js_block, js, flags=re.S)
    open(JS, 'w', encoding='utf-8', newline='').write(js)

    ids = [th['id'] for th in T]
    assert len(ids) == len(set(ids)), 'id en double'
    print(f'{len(T)} thèmes ({len(T) - sum(1 for t in T if t.get("manual"))} générés)')
    for w in warnings:
        print('  ajusté :', w)


if __name__ == '__main__':
    main()
