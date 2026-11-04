'use strict';
/* TriPhoto web UI. Vanilla JS, no build step.
   The server owns the data; the page keeps a copy of each table and sends every
   change back right away. Nothing moves on disk without an explicit click. */

const TOKEN = document.querySelector('meta[name="tp-token"]').content;
const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const icon = n => `<svg class="i"><use href="#i-${n}"/></svg>`;
const enc = encodeURIComponent;
// Everything goes to the Windows recycle bin, so Delete just acts; only a big batch asks first
const CONFIRM_ABOVE = 20;
const qs = o => new URLSearchParams(o).toString();
const hue = (h, s = 58, l = 62) => (h == null ? 'transparent' : `hsl(${h} ${s}% ${l}%)`);
const norm = s => String(s || '').normalize('NFD').replace(/[̀-ͯ]/g, '').toLowerCase();
const dirname = p => p.replace(/[\\/][^\\/]*$/, '');
const plural = (n, one, many) => `${n} ${n > 1 ? (many || one + 's') : one}`;
const pad = n => String(n).padStart(2, '0');
const collator = new Intl.Collator('fr', { numeric: true, sensitivity: 'base' });
const debounce = (fn, ms) => { let t; return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); }; };
const humanSize = n => n == null ? '?' : n < 1048576 ? `${Math.round(n / 1024)} Ko` : `${(n / 1048576).toFixed(1)} Mo`;
const U = {
  thumb: (p, m) => `/thumb?p=${enc(p)}&v=${m || 0}`,
  preview: (p, m, pct) => `/preview?p=${enc(p)}&v=${m || 0}` + (pct != null ? `&pct=${pct}` : ''),
  frame: (p, pct, m) => `/frame?p=${enc(p)}&pct=${pct}&v=${m || 0}`,
  media: p => `/media?p=${enc(p)}`,
};

const S = { state: null, ui: {}, view: null };

async function api(path, body) {
  const opt = body === undefined ? {} : {
    method: 'POST', headers: { 'Content-Type': 'application/json', 'X-Token': TOKEN }, body: JSON.stringify(body),
  };
  const r = await fetch(path, opt);
  let data = {};
  try { data = await r.json(); } catch (_) { /* empty body */ }
  if (!r.ok) throw new Error(data.error || `${r.status} ${r.statusText}`);
  return data;
}

const saveUi = debounce(() => api('/api/config', { ui: S.ui }).catch(() => {}), 700);
function uiSet(key, value) { S.ui[key] = value; saveUi(); }

// ============================================================ feedback

function toast(msg, type = 'info', ms = 3800) {
  const t = document.createElement('div');
  t.className = `toast ${type}`;
  t.textContent = msg;
  $('#toasts').appendChild(t);
  const kill = () => { t.classList.add('out'); setTimeout(() => t.remove(), 220); };
  setTimeout(kill, ms);
  t.onclick = kill;
}

function failed(e) { toast(e.message || String(e), 'err', 6000); }

const Task = {
  n: 0,
  async run(label, fn) {
    this.n++;
    $('#task').classList.remove('hidden');
    $('#task-label').textContent = label + '…';
    $('#task-bar').classList.add('indet');
    try { return await fn(); }
    finally {
      if (--this.n <= 0) { this.n = 0; $('#task').classList.add('hidden'); }
    }
  },
  progress(ev) {
    if ($('#splash') && !$('#splash').classList.contains('gone') && ev.label) {
      $('#splash-msg').textContent = `${ev.label}… ${ev.done || ''}`;
    }
    if (this.n <= 0 || ev.total < 0) return;
    const bar = $('#task-bar');
    if (ev.total > 0) {
      bar.classList.remove('indet');
      $('i', bar).style.width = `${Math.round(100 * ev.done / ev.total)}%`;
      $('#task-label').textContent = `${ev.label} ${ev.done}/${ev.total}`;
    } else {
      bar.classList.add('indet');
      $('#task-label').textContent = ev.done ? `${ev.label}… ${ev.done}` : `${ev.label}…`;
    }
  },
};

async function busy(btn, fn) {
  if (btn) btn.disabled = true;
  try { return await fn(); } catch (e) { failed(e); } finally { if (btn) btn.disabled = false; }
}

// ============================================================ modal / menu

function modal({ title, body = '', ok = 'OK', cancel = 'Annuler', danger = false, wide = false, collect, mount }) {
  return new Promise(resolve => {
    const bd = document.createElement('div');
    bd.className = 'backdrop';
    bd.innerHTML = `<div class="modal ${wide ? 'wide' : ''}" role="dialog"><h2>${esc(title)}</h2>
      <div class="body">${body}</div><div class="actions">
      ${cancel ? `<button class="btn ghost" data-v="0">${esc(cancel)}</button>` : ''}
      <button class="btn ${danger ? 'danger' : 'primary'}" data-v="1">${esc(ok)}</button></div></div>`;
    document.body.appendChild(bd);
    const prev = document.activeElement;
    const done = v => {
      bd.remove();
      document.removeEventListener('keydown', onKey, true);
      if (prev && prev.focus) prev.focus({ preventScroll: true });
      resolve(v);
    };
    const accept = () => {
      const v = collect ? collect(bd) : true;
      if (v !== undefined) done(v);
    };
    const onKey = e => {
      if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); done(null); }
      else if (e.key === 'Enter') { e.preventDefault(); e.stopPropagation(); accept(); }
      else e.stopPropagation();
    };
    bd.addEventListener('mousedown', e => { if (e.target === bd) done(null); });
    $$('[data-v]', bd).forEach(b => { b.onclick = () => (b.dataset.v === '1' ? accept() : done(null)); });
    document.addEventListener('keydown', onKey, true);
    if (mount) mount(bd, done);
    const input = $('input:not([type=checkbox])', bd);
    (input || $('[data-v="1"]', bd)).focus();
  });
}

function promptDlg(title, label, value, { ok = 'Renommer', stem = true } = {}) {
  return modal({
    title, ok,
    body: `<div class="field"><label>${esc(label)}</label><input class="input" spellcheck="false" value="${esc(value)}"></div>`,
    collect: bd => $('input', bd).value.trim(),
    mount: bd => {
      const i = $('input', bd);
      const dot = value.lastIndexOf('.');
      setTimeout(() => { i.focus(); i.setSelectionRange(0, stem && dot > 0 ? dot : value.length); });
    },
  });
}

const listHtml = (items, max = 12) => `<ul>${items.slice(0, max).map(x => `<li>${x}</li>`).join('')}${items.length > max ? `<li>… et ${items.length - max} autre(s)</li>` : ''}</ul>`;

let menuEl = null;
function closeMenu() { if (menuEl) { menuEl.remove(); menuEl = null; } }
function menu(e, items) {
  e.preventDefault();
  closeMenu();
  const m = document.createElement('div');
  m.className = 'menu';
  m.innerHTML = items.map((it, i) => (it === '-' ? '<hr>'
    : `<button data-i="${i}" ${it.disabled ? 'disabled' : ''} class="${it.danger ? 'danger' : ''}">${it.icon ? icon(it.icon) : ''}<span>${esc(it.label)}</span></button>`)).join('');
  document.body.appendChild(m);
  const r = m.getBoundingClientRect();
  m.style.left = `${Math.min(e.clientX, innerWidth - r.width - 8)}px`;
  m.style.top = `${Math.min(e.clientY, innerHeight - r.height - 8)}px`;
  m.onclick = ev => {
    const b = ev.target.closest('button');
    if (!b) return;
    closeMenu();
    items[+b.dataset.i].action();
  };
  menuEl = m;
}
document.addEventListener('mousedown', e => { if (menuEl && !menuEl.contains(e.target)) closeMenu(); });
document.addEventListener('keydown', e => { if (e.key === 'Escape') closeMenu(); });
window.addEventListener('blur', closeMenu);

const openPath = (path, reveal = false) => api('/api/open', { path, reveal }).catch(failed);

// ============================================================ virtual table

class VTable {
  constructor(el, o) {
    this.el = el;
    this.o = Object.assign({ rowHeight: 34, key: r => r.id, empty: 'Rien à afficher' }, o);
    const saved = (S.ui.tables || {})[o.id] || {};
    this.cols = o.columns.map(c => Object.assign({}, c, { width: (saved.w || {})[c.id] || c.width || 120 }));
    this.sort = saved.sort || o.sort || null;
    this.rows = []; this.view = []; this.filter = null;
    this.sel = new Set(); this.anchor = -1; this.cur = -1;
    el.classList.add('vt');
    el.tabIndex = 0;
    el.style.setProperty('--rh', `${this.o.rowHeight}px`);
    el.innerHTML = '<div class="vt-scroll"><div class="vt-head"></div><div class="vt-spacer"><div class="vt-rows"></div></div><div class="vt-empty hidden"></div></div>';
    this.scroll = $('.vt-scroll', el);
    this.head = $('.vt-head', el);
    this.spacer = $('.vt-spacer', el);
    this.win = $('.vt-rows', el);
    this.emptyEl = $('.vt-empty', el);
    this.renderHead();
    this.applyCols();
    this.scroll.addEventListener('scroll', () => this.schedule(), { passive: true });
    new ResizeObserver(() => this.schedule()).observe(this.scroll);
    this.win.addEventListener('mousedown', e => this.onMouseDown(e));
    this.win.addEventListener('dblclick', e => this.onDblClick(e));
    this.win.addEventListener('contextmenu', e => this.onContext(e));
    el.addEventListener('keydown', e => this.onKey(e));
  }

  renderHead() {
    this.head.innerHTML = this.cols.map((c, i) => {
      const arrow = this.sort && this.sort.col === c.id ? (this.sort.dir > 0 ? '▲' : '▼') : '';
      return `<div class="vt-th ${c.align === 'right' ? 'right' : ''}" data-i="${i}" title="${esc(c.title || '')}">${esc(c.label)}<span class="arrow">${arrow}</span><span class="rz" data-i="${i}"></span></div>`;
    }).join('');
    $$('.vt-th', this.head).forEach(th => th.addEventListener('click', e => {
      if (e.target.classList.contains('rz')) return;
      const c = this.cols[+th.dataset.i];
      if (c.sortable === false) return;
      this.setSort(c.id, this.sort && this.sort.col === c.id ? -this.sort.dir : 1);
    }));
    $$('.rz', this.head).forEach(h => h.addEventListener('mousedown', e => this.startResize(e, +h.dataset.i)));
  }

  applyCols() {
    const n = this.cols.length;
    this.el.style.setProperty('--cols', this.cols.map((c, i) => (i === n - 1 ? `minmax(${c.width}px, 1fr)` : `${c.width}px`)).join(' '));
    this.el.style.setProperty('--tw', `${this.cols.reduce((a, c) => a + c.width, 0)}px`);
  }

  startResize(e, i) {
    e.preventDefault();
    e.stopPropagation();
    const x0 = e.clientX, w0 = this.cols[i].width, h = e.target;
    h.classList.add('drag');
    const move = ev => { this.cols[i].width = Math.max(48, w0 + ev.clientX - x0); this.applyCols(); };
    const up = () => {
      document.removeEventListener('mousemove', move);
      document.removeEventListener('mouseup', up);
      h.classList.remove('drag');
      this.persist();
    };
    document.addEventListener('mousemove', move);
    document.addEventListener('mouseup', up);
  }

  persist() {
    const t = S.ui.tables || (S.ui.tables = {});
    t[this.o.id] = { w: Object.fromEntries(this.cols.map(c => [c.id, c.width])), sort: this.sort };
    saveUi();
  }

  key(r) { return this.o.key(r); }

  applySort() {
    const v = this.filter ? this.rows.filter(this.filter) : this.rows.slice();
    const c = this.sort && this.cols.find(x => x.id === this.sort.col);
    if (c) {
      const get = c.sortKey || c.get || (r => r[c.id]);
      const d = this.sort.dir;
      const idx = new Map(v.map((r, i) => [r, i]));
      v.sort((a, b) => {
        const x = get(a), y = get(b);
        const r = typeof x === 'number' && typeof y === 'number' ? x - y : collator.compare(String(x ?? ''), String(y ?? ''));
        return r ? r * d : idx.get(a) - idx.get(b);
      });
    }
    this.view = v;
  }

  // Re-sorting moves rows: only on an explicit click or a reload, never after an edit
  setSort(col, dir) {
    const cur = this.current();
    this.sort = { col, dir };
    this.renderHead();
    this.applySort();
    this.persist();
    this.cur = cur ? this.view.indexOf(cur) : -1;
    this.refresh();
    if (this.cur >= 0) this.ensureVisible(this.cur, true);
  }

  setRows(rows, { keep = true } = {}) {
    const curKey = keep && this.current() ? this.key(this.current()) : null;
    const top = this.scroll.scrollTop;
    this.rows = rows;
    this.applySort();
    if (!keep) {
      this.sel.clear(); this.cur = -1; this.anchor = -1;
      this.scroll.scrollTop = 0;
    } else {
      const keys = new Set(this.view.map(r => this.key(r)));
      for (const k of [...this.sel]) if (!keys.has(k)) this.sel.delete(k);
      this.cur = curKey != null ? this.view.findIndex(r => this.key(r) === curKey) : -1;
    }
    this.refresh();
    if (keep) this.scroll.scrollTop = top;
  }

  setFilter(fn) { this.filter = fn; this.setRows(this.rows); }

  refresh() {
    this.spacer.style.height = `${this.view.length * this.o.rowHeight}px`;
    this.emptyEl.textContent = this.o.empty;
    this.emptyEl.classList.toggle('hidden', this.view.length > 0);
    this.schedule();
  }

  schedule() {
    if (!this.raf) this.raf = requestAnimationFrame(() => { this.raf = 0; this.render(); });
  }

  render() {
    const rh = this.o.rowHeight, st = this.scroll.scrollTop, h = this.scroll.clientHeight, n = this.view.length;
    const start = Math.max(0, Math.floor(st / rh) - 6), end = Math.min(n, Math.ceil((st + h) / rh) + 6);
    let html = '';
    for (let i = start; i < end; i++) {
      const r = this.view[i];
      const extra = this.o.rowClass ? this.o.rowClass(r) || '' : '';
      html += `<div class="vt-row${this.sel.has(this.key(r)) ? ' sel' : ''}${i === this.cur ? ' cur' : ''} ${extra}" data-i="${i}" style="top:${i * rh}px">`;
      for (const c of this.cols) {
        const content = c.render ? c.render(r) : esc((c.get ? c.get(r) : r[c.id]) ?? '');
        html += `<div class="vt-cell ${c.cls || ''}">${content}</div>`;
      }
      html += '</div>';
    }
    this.win.innerHTML = html;
  }

  rowIndex(e) { const row = e.target.closest('.vt-row'); return row ? +row.dataset.i : -1; }

  onMouseDown(e) {
    const i = this.rowIndex(e);
    if (i < 0) return;
    if (e.button === 2 && this.sel.has(this.key(this.view[i]))) return;   // keep it for the menu
    if (e.shiftKey && this.anchor >= 0) this.selectRange(this.anchor, i, e.ctrlKey);
    else if (e.ctrlKey) this.toggle(i);
    else this.selectOnly(i, false);
    this.el.focus({ preventScroll: true });
  }

  onDblClick(e) {
    const i = this.rowIndex(e);
    if (i < 0) return;
    const cell = e.target.closest('.vt-cell');
    const c = cell ? this.cols[[...cell.parentNode.children].indexOf(cell)] : null;
    if (c && c.editable) return this.edit(i, c, cell);
    if (this.o.onActivate) this.o.onActivate(this.view[i], e);
  }

  onContext(e) {
    e.preventDefault();
    const i = this.rowIndex(e);
    if (i < 0) return;
    if (!this.sel.has(this.key(this.view[i]))) this.selectOnly(i, false);
    if (this.o.onContext) this.o.onContext(e, this.selected());
  }

  edit(i, c, cell) {
    const r = this.view[i];
    if (!cell) {
      this.ensureVisible(i);
      this.render();
      const row = $(`.vt-row[data-i="${i}"]`, this.win);
      cell = row && row.children[this.cols.indexOf(c)];
      if (!cell) return;
    }
    const input = document.createElement('input');
    input.className = 'vt-editor';
    input.spellcheck = false;
    input.value = c.editValue ? c.editValue(r) : (r[c.id] ?? '');
    const rc = cell.getBoundingClientRect(), base = this.el.getBoundingClientRect();
    Object.assign(input.style, { left: `${rc.left - base.left + 2}px`, top: `${rc.top - base.top + 2}px`, width: `${Math.max(120, rc.width - 4)}px` });
    this.el.appendChild(input);
    input.focus();
    input.select();
    let done = false;
    const finish = ok => {
      if (done) return;
      done = true;
      const v = input.value.trim();
      input.remove();
      this.el.focus({ preventScroll: true });
      if (ok) c.onEdit(r, v);
      this.schedule();
    };
    input.addEventListener('keydown', ev => {
      ev.stopPropagation();
      if (ev.key === 'Enter') finish(true);
      else if (ev.key === 'Escape') finish(false);
    });
    input.addEventListener('blur', () => finish(true));
    this.scroll.addEventListener('scroll', () => finish(true), { once: true });
  }

  editCurrent(colId) {
    const c = this.cols.find(x => x.id === colId);
    if (c && this.cur >= 0) this.edit(this.cur, c, null);
  }

  onKey(e) {
    if (e.target !== this.el) return;
    const n = this.view.length;
    const page = Math.max(1, Math.floor(this.scroll.clientHeight / this.o.rowHeight) - 1);
    let to = null;
    switch (e.key) {
      case 'ArrowDown': to = this.cur + 1; break;
      case 'ArrowUp': to = this.cur - 1; break;
      case 'PageDown': to = this.cur + page; break;
      case 'PageUp': to = this.cur - page; break;
      case 'Home': to = 0; break;
      case 'End': to = n - 1; break;
      case 'a': case 'A':
        if (e.ctrlKey) { e.preventDefault(); this.selectAll(); return; }
        break;
      default: break;
    }
    if (to != null && n) {
      e.preventDefault();
      to = Math.max(0, Math.min(n - 1, this.cur < 0 ? 0 : to));
      if (e.shiftKey) {
        if (this.anchor < 0) this.anchor = Math.max(0, this.cur);
        this.selectRange(this.anchor, to);
      } else this.selectOnly(to);
      return;
    }
    if (this.o.onKey) this.o.onKey(e);
  }

  selectOnly(i, scroll = true) {
    this.sel.clear();
    if (i >= 0 && i < this.view.length) {
      this.sel.add(this.key(this.view[i]));
      this.cur = i; this.anchor = i;
      if (scroll) this.ensureVisible(i);
    } else { this.cur = -1; this.anchor = -1; }
    this.changed();
  }

  toggle(i) {
    const k = this.key(this.view[i]);
    if (this.sel.has(k)) this.sel.delete(k); else this.sel.add(k);
    this.cur = i; this.anchor = i;
    this.changed();
  }

  selectRange(a, b, add = false) {
    if (!add) this.sel.clear();
    for (let i = Math.min(a, b); i <= Math.max(a, b); i++) this.sel.add(this.key(this.view[i]));
    this.cur = b;
    this.ensureVisible(b);
    this.changed();
  }

  selectAll() {
    this.view.forEach(r => this.sel.add(this.key(r)));
    if (this.cur < 0 && this.view.length) this.cur = 0;
    this.changed();
  }

  selectKeys(keys) {
    this.sel = new Set(keys);
    const i = this.view.findIndex(r => this.sel.has(this.key(r)));
    this.cur = i; this.anchor = i;
    if (i >= 0) this.ensureVisible(i, true);
    this.changed();
  }

  changed() {
    this.schedule();
    if (this.o.onSelect) this.o.onSelect(this.selected(), this.current());
  }

  selected() { return this.view.filter(r => this.sel.has(this.key(r))); }
  current() { return this.cur >= 0 ? this.view[this.cur] || null : null; }
  lastSelectedIndex() {
    let last = -1;
    this.view.forEach((r, i) => { if (this.sel.has(this.key(r))) last = i; });
    return last;
  }

  ensureVisible(i, center = false) {
    const rh = this.o.rowHeight, top = i * rh, st = this.scroll.scrollTop;
    const h = this.scroll.clientHeight - this.head.offsetHeight;
    if (center && (top < st || top + rh > st + h)) this.scroll.scrollTop = top - h / 2;
    else if (top < st) this.scroll.scrollTop = top;
    else if (top + rh > st + h) this.scroll.scrollTop = top + rh - h;
  }

  /* Rows that were acted upon disappear; the selection lands on the next one so
     you can chain without clicking. */
  removeKeys(keys) {
    const ks = new Set(keys);
    if (!ks.size) return;
    let first = this.view.findIndex(r => ks.has(this.key(r)));
    if (first < 0) first = this.cur;
    const top = this.scroll.scrollTop;
    this.rows = this.rows.filter(r => !ks.has(this.key(r)));
    this.applySort();
    for (const k of ks) this.sel.delete(k);
    this.refresh();
    this.scroll.scrollTop = top;
    this.selectOnly(Math.min(first, this.view.length - 1));
  }
}

// ============================================================ navigation

const VIEWS = {
  rename: { title: 'Renommage', sub: 'Normalise les noms des dossiers d’événements : chacun commence par son année.' },
  dup: { title: 'Doublons', sub: 'Mêmes noms, copies _1 / (1) / Copie : comparés sur le contenu réel, pas seulement le nom.' },
  sort: { title: 'Tri des médias', sub: 'Assigne chaque fichier à un dossier, puis applique les déplacements en une fois.' },
  viewer: { title: 'Visualiseur', sub: 'Années, dossiers, vignettes et frise chronologique.' },
};
const MODULES = {};

function show(view) {
  if (!VIEWS[view]) view = 'sort';
  S.view = view;
  $$('.nav-item[data-view]').forEach(b => b.classList.toggle('active', b.dataset.view === view));
  $$('.view').forEach(v => v.classList.toggle('active', v.id === `view-${view}`));
  $('#view-title').textContent = VIEWS[view].title;
  $('#view-sub').textContent = VIEWS[view].sub;
  uiSet('view', view);
  const m = MODULES[view];
  if (m && m.enter) m.enter();
}

function setBadge(id, n, hot = false) {
  const b = $(id);
  b.textContent = n ? String(n) : '';
  b.classList.toggle('hot', hot && n > 0);
}

// ============================================================ 1. rename

const STATUS = {
  ok: { label: 'OK', chip: 'c-muted', row: 't-dim', order: 9 },
  auto: { label: 'Auto', chip: 'c-ok', row: 't-auto', order: 3 },
  move: { label: r => `Déplacer → ${r.proposed.slice(0, 4)}`, chip: 'c-info', row: 't-auto', order: 3 },
  manual: { label: 'À voir', chip: 'c-warn', row: 't-warn', order: 1 },
  similar: { label: 'Doublon ?', chip: 'c-accent', row: 't-warn', order: 0 },
  edited: { label: 'Modifié', chip: 'c-ok', row: 't-auto', order: 2 },
  renamed: { label: 'Renommé', chip: 'c-info', row: 't-done', order: 8 },
  merged: { label: 'Fusionné', chip: 'c-info', row: 't-done', order: 8 },
  partial: { label: 'Fusion partielle', chip: 'c-orange', row: 't-bad', order: 0 },
  error: { label: 'Erreur', chip: 'c-bad', row: 't-bad', order: 0 },
};
const DONE = new Set(['ok', 'renamed', 'merged']);

const Rename = {
  rows: [], filter: 'todo', loaded: false,

  init() {
    this.t = new VTable($('#rn-table'), {
      id: 'rename', key: r => r.k, empty: 'Tous les dossiers sont bien nommés 🎉',
      sort: { col: 'status', dir: 1 },
      columns: [
        { id: 'year', label: 'Année', width: 72, cls: 'num' },
        { id: 'current', label: 'Nom actuel', width: 360 },
        { id: 'files', label: 'Fichiers', width: 86, cls: 'right', align: 'right', sortKey: r => r.files },
        {
          id: 'proposed', label: 'Proposition', width: 360, cls: 'edit', editable: true,
          render: r => (r.proposed ? esc(r.proposed) : '<span class="ph">double-clic pour proposer</span>'),
          editValue: r => r.proposed || r.current,
          onEdit: (r, v) => this.edit(r, v),
        },
        {
          id: 'status', label: 'Statut', width: 160, sortKey: r => (STATUS[r.status] || {}).order ?? 9,
          render: r => {
            const s = STATUS[r.status] || STATUS.ok;
            const label = typeof s.label === 'function' ? s.label(r) : s.label;
            return `<span class="chip ${s.chip}" title="${esc(r.msg || (r.partner ? 'proche de « ' + r.partner + ' »' : ''))}">${esc(label)}</span>`;
          },
        },
      ],
      rowClass: r => (STATUS[r.status] || {}).row,
      onKey: e => { if (e.key === 'F2') { e.preventDefault(); this.t.editCurrent('proposed'); } },
      onActivate: () => this.t.editCurrent('proposed'),
    });
    $$('#rn-filter button').forEach(b => b.onclick = () => {
      this.filter = b.dataset.f;
      $$('#rn-filter button').forEach(x => x.classList.toggle('on', x === b));
      this.render();
    });
    $('#rn-analyze').onclick = e => busy(e.currentTarget, () => this.load());
    $('#rn-apply').onclick = e => busy(e.currentTarget, () => this.apply());
    $('#rn-exclude').onclick = e => busy(e.currentTarget, () => this.exclude());
  },

  enter() { if (!this.loaded) this.load().catch(failed); },

  async load() {
    this.loaded = true;
    const d = await Task.run('Analyse des dossiers', () => api('/api/rename'));
    this.rows = d.rows.map(r => Object.assign(r, { k: `${r.year}/${r.current}`, orig: r.status, origProposed: r.proposed }));
    this.t.setRows(this.rows, { keep: false });
    this.render();
  },

  todo() { return this.rows.filter(r => r.proposed && r.proposed !== r.current && !DONE.has(r.status)); },

  render() {
    const pending = this.rows.filter(r => r.status !== 'ok');
    $('#rn-n-todo').textContent = pending.length;
    $('#rn-n-all').textContent = this.rows.length;
    this.t.o.empty = this.filter === 'todo' ? 'Tous les dossiers sont bien nommés 🎉' : 'Aucun dossier';
    this.t.setFilter(this.filter === 'todo' ? (r => r.status !== 'ok') : null);
    const c = {};
    this.rows.forEach(r => { c[r.status] = (c[r.status] || 0) + 1; });
    const stat = (n, label, color) => (n ? `<span class="stat"><i style="background:${color}"></i><b>${n}</b> ${label}</span>` : '');
    $('#rn-stats').innerHTML = stat((c.auto || 0) + (c.move || 0) + (c.edited || 0), 'à renommer', 'var(--ok)')
      + stat(c.similar, 'doublon(s) ?', 'var(--accent)') + stat(c.manual, 'à voir', 'var(--warn)')
      + stat((c.renamed || 0) + (c.merged || 0), 'fait(s)', 'var(--info)');
    const n = this.todo().length;
    $('#rn-n-apply').textContent = n;
    $('#rn-apply').disabled = !n;
    setBadge('#b-rename', this.rows.filter(r => !DONE.has(r.status)).length);
  },

  edit(r, v) {
    if (!v || v === r.current) {
      r.proposed = r.origProposed && v !== r.current ? r.origProposed : '';
      r.status = r.proposed ? r.orig : (r.orig === 'similar' || r.orig === 'manual' ? r.orig : 'ok');
    } else {
      r.proposed = v;
      r.status = 'edited';
    }
    this.render();
  },

  async apply() {
    const todo = this.todo();
    if (!todo.length) return toast('Aucune proposition à appliquer', 'warn');
    const ok = await modal({
      title: `Renommer ${plural(todo.length, 'dossier')} ?`, ok: 'Renommer',
      body: listHtml(todo.map(r => `${esc(r.year)} · ${esc(r.current)} → <b>${esc(r.proposed)}</b>`))
        + '<p class="hint">Un dossier cible déjà existant est fusionné ; les fichiers identiques partent dans !duplicate.</p>',
    });
    if (!ok) return;
    const d = await Task.run('Renommage', () => api('/api/rename/apply', {
      rows: todo.map(r => ({ year: r.year, current: r.current, proposed: r.proposed, status: r.status })),
    }));
    const byKey = new Map(this.rows.map(r => [r.k, r]));
    let done = 0, errors = 0;
    for (const res of d.results) {
      const r = byKey.get(`${res.year}/${res.current}`);
      if (!r || res.result === 'skip') continue;
      if (res.result === 'error' || res.result === 'partial') { r.status = res.result; r.msg = res.msg || ''; errors++; continue; }
      r.current = res.new; r.year = res.year || r.year; r.proposed = ''; r.status = res.result;
      r.k = `${r.year}/${r.current}`;
      done++;
    }
    this.t.setRows(this.rows);
    this.render();
    toast(`${plural(done, 'dossier renommé', 'dossiers renommés')}${errors ? `, ${errors} erreur(s)` : ''}`, errors ? 'warn' : 'ok');
    Viewer.stale = true;
  },

  async exclude() {
    const sel = this.t.selected().filter(r => r.partner);
    if (!sel.length) return toast('Sélectionne une ligne « Doublon ? » d’abord', 'warn');
    await api('/api/rename/exclude', { pairs: sel.map(r => [r.current, r.partner]) });
    sel.forEach(r => { r.status = 'ok'; r.proposed = ''; r.partner = ''; r.orig = 'ok'; r.origProposed = ''; });
    this.render();
    toast(`${plural(sel.length, 'paire exclue', 'paires exclues')} → FolderDoublonExclusion.txt`, 'ok');
  },
};
MODULES.rename = Rename;

// ============================================================ 2. duplicates

const KIND = {
  auto: { label: 'Auto', chip: 'c-ok', tip: 'Même fichier dans un dossier d’événement et dans un vivier de captures' },
  suffix: { label: 'Suffixe', chip: 'c-ok', tip: 'Copie _1 / (1) / Copie de même taille, dans le même dossier' },
  conflict: { label: 'Conflit', chip: 'c-bad', tip: 'Même nom dans deux dossiers d’événements : jamais traité automatiquement' },
  copy: { label: 'Copie ?', chip: 'c-orange', tip: 'Nom de copie mais taille différente : jamais traité automatiquement' },
  renamed: { label: 'Renommé', chip: 'c-info', tip: '' },
};
const LEVEL_CHIP = { same: 'c-ok', close: 'c-warn', related: 'c-orange', diff: 'c-bad', unknown: 'c-muted' };

const Dup = {
  scope: 0, loaded: false, detailId: null, slide: null, cmp: null, byId: new Map(),

  init() {
    this.scope = S.ui.dupScope || 0;
    this.t = new VTable($('#dup-table'), {
      id: 'dup', key: r => r.id, empty: 'Aucun doublon dans ce périmètre ✨',
      columns: [
        { id: 'name', label: 'Fichier', width: 290 },
        {
          id: 'kind', label: 'Type', width: 104, sortKey: r => r.kind_label,
          render: r => `<span class="chip ${KIND[r.kind].chip}" title="${esc(KIND[r.kind].tip)}">${KIND[r.kind].label}</span>`,
        },
        {
          id: 'score', label: 'Score', width: 96, sortKey: r => (r.score ? r.score.value : -2),
          render: r => (r.score
            ? `<span class="chip ${LEVEL_CHIP[r.score.level]}" title="${esc(`${r.score.long}\n${r.score.details}`)}">${esc(r.score.short)}</span>`
            : '<span class="ph">…</span>'),
        },
        { id: 'r1', label: 'Copie 1', width: 380, cls: 'path' },
        { id: 'r2', label: 'Copie 2', width: 380, cls: 'path' },
      ],
      rowClass: r => (r.score && r.score.level === 'diff' ? 't-bad'
        : r.kind === 'conflict' || r.kind === 'copy' ? 't-warn'
          : r.kind === 'renamed' ? 't-done' : 't-auto'),
      onSelect: (sel, cur) => { this.updateButtons(sel); this.loadDetailSoon(cur); },
      onContext: (e, sel) => this.menu(e, sel),
      onKey: e => {
        if (e.key === 'Delete') { e.preventDefault(); this.trash(e.shiftKey ? 0 : 'auto').catch(failed); }
      },
      onActivate: () => this.openSide(1),
    });
    $$('#dup-scope button').forEach(b => {
      b.classList.toggle('on', +b.dataset.s === this.scope);
      b.onclick = () => {
        if (+b.dataset.s === this.scope && this.loaded) return;
        this.scope = +b.dataset.s;
        uiSet('dupScope', this.scope);
        $$('#dup-scope button').forEach(x => x.classList.toggle('on', x === b));
        this.scan().catch(failed);
      };
    });
    $('#dup-scan').onclick = e => busy(e.currentTarget, () => this.scan());
    $('#dup-compare').onclick = e => busy(e.currentTarget, () => this.recompare());
    $('#dup-ignore').onclick = e => busy(e.currentTarget, () => this.ignore());
    $('#dup-auto').onclick = e => busy(e.currentTarget, () => this.auto());
    $$('#dup-compare-panel .side').forEach(side => {
      const s = +side.dataset.side;
      $('[data-act="trash"]', side).onclick = e => busy(e.currentTarget, () => this.trash(s));
      $('[data-act="reveal"]', side).onclick = () => this.reveal(s);
      $('[data-act="rename"]', side).onclick = () => this.renameSide(s).catch(failed);
      $('.stage', side).onclick = () => this.openSide(s);
    });
    this.loadDetailSoon = debounce(cur => this.loadDetail(cur), 70);
    this.resizeStage();
    window.addEventListener('resize', debounce(() => this.resizeStage(), 100));
  },

  resizeStage() {
    // Previews take what the table leaves, within reason
    const h = Math.max(150, Math.min(380, Math.round(innerHeight * 0.3)));
    $('#view-dup').style.setProperty('--stage-h', `${h}px`);
  },

  enter() { if (!this.loaded) this.scan().catch(failed); },

  async scan() {
    this.loaded = true;
    this.stopSlide();
    this.cmp = null;
    const d = await Task.run('Scan des doublons', () => api('/api/dup/scan', { scope: this.scope }));
    this.setRows(d.rows, false);
    if (d.rows.length) this.t.selectOnly(0);
    else this.loadDetail(null);
  },

  setRows(rows, keep) {
    this.byId = new Map(rows.map(r => [r.id, r]));
    this.t.setRows(rows, { keep });
    this.stats();
  },

  stats() {
    const rows = this.t.rows;
    const n = k => rows.filter(r => r.kind === k).length;
    const auto = n('auto') + n('suffix'), conflicts = n('conflict') + n('copy');
    const diff = rows.filter(r => r.score && r.score.level === 'diff').length;
    let html = `<span class="stat"><i style="background:var(--ok)"></i><b>${auto}</b> traitable(s)</span>`
      + `<span class="stat"><i style="background:var(--bad)"></i><b>${conflicts}</b> à vérifier</span>`;
    if (diff) html += `<span class="stat"><i style="background:var(--bad)"></i><b>${diff}</b> contenu différent</span>`;
    if (this.cmp && this.cmp.done < this.cmp.total) html += `<span class="stat"><div class="spinner" style="width:11px;height:11px"></div>comparaison <b>${this.cmp.done}/${this.cmp.total}</b></span>`;
    $('#dup-stats').innerHTML = html;
    setBadge('#b-dup', rows.length);
    $('#dup-auto').disabled = !auto;
  },

  updateButtons(sel) {
    $$('#dup-compare-panel .side').forEach(side => {
      const b = $('[data-act="trash"]', side);
      b.disabled = !sel.length;
      b.lastChild.textContent = sel.length > 1 ? `Corbeille (${sel.length})` : 'Corbeille';
    });
  },

  onScore(ev) {
    const r = this.byId.get(ev.id);
    if (ev.total) this.cmp = { done: ev.done, total: ev.total };
    if (r) {
      r.score = ev.score;
      this.t.schedule();
      if (this.detailId === ev.id) this.renderVerdict(ev.score);
    }
    this.statsSoon();
  },
  statsSoon: debounce(() => Dup.stats(), 250),

  async loadDetail(row) {
    this.stopSlide();
    const sides = $$('#dup-compare-panel .side');
    if (!row) {
      this.detailId = null;
      sides.forEach(s => { $('.stage', s).innerHTML = '<span class="empty">—</span>'; $('.caption', s).innerHTML = ''; });
      $('#dup-verdict').innerHTML = '<span class="det">Sélectionne une ligne pour comparer les deux copies.</span>';
      return;
    }
    const id = row.id;
    this.detailId = id;
    $('#dup-verdict').innerHTML = '<div class="spinner"></div><span class="det">Comparaison…</span>';
    let d;
    try { d = await api('/api/dup/detail?' + qs({ id })); } catch (e) { if (this.detailId === id) $('#dup-verdict').innerHTML = `<span class="det">${esc(e.message)}</span>`; return; }
    if (this.detailId !== id) return;
    this.detail = d;
    d.sides.forEach((s, i) => this.renderSide(sides[i], s, d));
    this.renderVerdict(d.score);
    if (d.sides.some(s => s.video && s.size != null)) this.startSlide(d);
  },

  renderSide(el, s, d) {
    const stage = $('.stage', el), cap = $('.caption', el);
    if (!s.path) { stage.innerHTML = '<span class="empty">—</span>'; cap.innerHTML = ''; return; }
    if (s.size == null) {
      stage.innerHTML = '<span class="empty">Fichier absent du disque</span>';
      cap.innerHTML = `<span class="lvl-diff">(absent)</span> ${s.html}`;
      return;
    }
    if (s.video) {
      stage.innerHTML = `<img alt=""><span class="pct"></span><span class="dots">${d.frames.map(() => '<i></i>').join('')}</span>`;
      d.frames.forEach(p => { new Image().src = U.frame(s.path, p, s.m); });   // extract all five in parallel
    } else if (s.image) {
      stage.innerHTML = `<img alt="" src="${U.preview(s.path, s.m)}">`;
    } else stage.innerHTML = '<span class="empty">Pas d’aperçu</span>';
    cap.innerHTML = `${s.html} <span class="${d.sizes_differ ? 'size-diff' : 'd-same'}">· ${esc(s.size_h)}</span>`
      + (s.others ? ` <span class="d-hot">+${s.others} autre(s)</span>` : '');
    el.title = s.path;
  },

  startSlide(d) {
    let k = 0;
    const step = () => {
      const pct = d.frames[k % d.frames.length];
      $$('#dup-compare-panel .side').forEach((el, i) => {
        const s = d.sides[i];
        if (!s.video || s.size == null) return;
        const img = $('.stage img', el);
        if (img) img.src = U.frame(s.path, pct, s.m);
        const lab = $('.stage .pct', el);
        if (lab) lab.textContent = `${pct} %`;
        $$('.stage .dots i', el).forEach((dot, j) => dot.classList.toggle('on', j === k % d.frames.length));
      });
      k++;
    };
    step();
    this.slide = setInterval(step, 900);
  },

  stopSlide() { if (this.slide) clearInterval(this.slide); this.slide = null; },

  renderVerdict(score) {
    const el = $('#dup-verdict');
    if (!score) { el.innerHTML = '<div class="spinner"></div><span class="det">Comparaison en cours…</span>'; return; }
    el.innerHTML = `<span class="big-dot lvl-${score.level}"></span><span class="lvl lvl-${score.level}">${esc(score.long)}</span><span class="det">${esc(score.details)}</span>`;
  },

  sidePaths(r, side) { return side ? r.p2 : r.p1; },

  /** side 0 = Copie 1, 1 = Copie 2, 'auto' = the bad one (Copie 2, or Copie 1 when it is the empty file) */
  async trash(side) {
    const sel = this.t.selected();
    if (!sel.length) return toast('Sélectionne au moins une ligne', 'warn');
    const auto = side === 'auto';
    const n = sel.reduce((a, r) => a + this.sidePaths(r, auto ? 1 : side).length, 0);
    if (n > CONFIRM_ABOVE && !await modal({ title: 'Mettre à la corbeille ?', ok: 'Corbeille', danger: true,
        body: `${auto ? 'La mauvaise copie' : `La <b>Copie ${side + 1}</b>`} de ${plural(sel.length, 'ligne')} (${plural(n, 'fichier')}) part dans la corbeille Windows.` })) return;
    // Explicit side only: the other copy is a 0-byte file, so this one is the only real image
    const otherEmpty = auto ? [] : sel.filter(r => r.score && r.score.short === (side === 1 ? '1 vide' : '2 vide'));
    if (otherEmpty.length && !await modal({ title: 'Jeter la seule vraie copie ?', ok: 'Corbeille quand même', danger: true,
        body: `Pour ${plural(otherEmpty.length, 'ligne')}, l'autre copie est un fichier <b>vide</b> (0 octet) : la Copie ${side + 1} est la seule image réelle.
          <b>Suppr</b> choisit tout seul la bonne copie à jeter.` })) return;
    this.stopSlide();
    const d = await Task.run('Corbeille', () => api('/api/dup/trash', { ids: sel.map(r => r.id), side }));
    d.removed.forEach(id => this.byId.delete(id));
    this.t.removeKeys(d.removed);
    this.stats();
    toast(d.msg, d.errors ? 'warn' : 'ok');
  },

  async auto() {
    const dry = await api('/api/dup/auto', { dry: true });
    if (!dry.rows) return toast(dry.empty ? `Rien à traiter en lot : ${plural(dry.empty, 'ligne')} avec une Copie 1 vide, à régler à la main (Maj+Suppr)` : 'Aucune ligne Auto / Suffixe à traiter', 'warn');
    const ok = await modal({
      title: 'Tout traiter ?', ok: `Corbeille (${dry.files})`, danger: true,
      body: `La <b>Copie 2</b> de ${plural(dry.rows, 'ligne')} Auto / Suffixe (${plural(dry.files, 'fichier')}) part dans la corbeille.
        Les conflits ne sont jamais touchés.`
        + (dry.skipped ? `<p>${plural(dry.skipped, 'ligne écartée', 'lignes écartées')} : le contenu ne correspond pas.</p>` : '')
        + (dry.empty ? `<p class="lvl-related">${plural(dry.empty, 'ligne écartée', 'lignes écartées')} : la Copie 1 est vide (0 octet), c'est la Copie 2 qu'il faut garder — Maj+Suppr sur ces lignes.</p>` : '')
        + (dry.unscored ? `<p class="lvl-related">⚠ ${plural(dry.unscored, 'ligne')} pas encore comparée(s) — attendre la fin de la comparaison est plus sûr.</p>` : ''),
    });
    if (!ok) return;
    const d = await Task.run('Corbeille', () => api('/api/dup/auto', { dry: false }));
    d.removed.forEach(id => this.byId.delete(id));
    this.t.removeKeys(d.removed);
    this.stats();
    toast(d.msg, d.errors ? 'warn' : 'ok');
  },

  async recompare() {
    const sel = this.t.selected();
    const rows = sel.length > 1 ? sel : this.t.rows;
    rows.forEach(r => { delete r.score; });
    this.t.schedule();
    await api('/api/dup/compare', { ids: rows.map(r => r.id) });
    toast(`Comparaison relancée sur ${plural(rows.length, 'ligne')}`);
    if (this.t.current()) this.loadDetail(this.t.current());
  },

  async ignore() {
    const sel = this.t.selected();
    if (!sel.length) return toast('Sélectionne au moins une ligne', 'warn');
    const d = await api('/api/dup/ignore', { ids: sel.map(r => r.id) });
    d.removed.forEach(id => this.byId.delete(id));
    this.t.removeKeys(d.removed);
    S.state.ignored = d.ignored;
    this.stats();
    toast(`${plural(sel.length, 'paire ignorée', 'paires ignorées')} (mémorisé)`, 'ok');
  },

  async forget() {
    const n = S.state.ignored;
    if (!n) return toast('Aucun doublon ignoré');
    if (!await modal({ title: 'Doublons ignorés', ok: 'Oublier', body: `Oublier les ${n} doublon(s) ignoré(s) ? Ils réapparaîtront au prochain scan.` })) return;
    await api('/api/dup/forget', {});
    S.state.ignored = 0;
    toast(`${n} doublon(s) oublié(s) — relance le scan`, 'ok');
  },

  async renameSide(side) {
    const r = this.t.current();
    if (!r) return;
    const old = this.sidePaths(r, side)[0];
    if (!old) return;
    const name = await promptDlg(`Renommer la Copie ${side + 1}`, dirname(old).replace(S.state.camera_path, 'Camera'), old.split('\\').pop());
    if (!name || name === old.split('\\').pop()) return;
    const d = await api('/api/dup/rename', { id: r.id, side, name });
    Object.assign(r, d.row);
    delete r.score;
    this.t.schedule();
    this.stats();
    this.loadDetail(r);
    toast(`Renommé en « ${name} »`, 'ok');
  },

  reveal(side) { const r = this.t.current(); if (r && this.sidePaths(r, side)[0]) openPath(this.sidePaths(r, side)[0], true); },
  openSide(side) { const r = this.t.current(); if (r && this.sidePaths(r, side)[0]) openPath(this.sidePaths(r, side)[0]); },

  menu(e, sel) {
    const one = sel.length === 1;
    menu(e, [
      { label: 'Renommer la Copie 1…', icon: 'rename', disabled: !one, action: () => this.renameSide(0).catch(failed) },
      { label: 'Renommer la Copie 2…', icon: 'rename', disabled: !one, action: () => this.renameSide(1).catch(failed) },
      '-',
      { label: 'Ouvrir la Copie 1', icon: 'external', disabled: !one, action: () => this.openSide(0) },
      { label: 'Ouvrir la Copie 2', icon: 'external', disabled: !one, action: () => this.openSide(1) },
      { label: 'Afficher la Copie 1 dans l’Explorateur', icon: 'folder', disabled: !one, action: () => this.reveal(0) },
      { label: 'Afficher la Copie 2 dans l’Explorateur', icon: 'folder', disabled: !one, action: () => this.reveal(1) },
      '-',
      { label: `Corbeille — Copie 1${one ? '' : ` (${sel.length})`}`, icon: 'trash', danger: true, action: () => this.trash(0).catch(failed) },
      { label: `Corbeille — Copie 2${one ? '' : ` (${sel.length})`}`, icon: 'trash', danger: true, action: () => this.trash(1).catch(failed) },
      '-',
      { label: 'Recomparer', icon: 'scan', action: () => this.recompare().catch(failed) },
      { label: 'Ignorer (mémorisé)', icon: 'eyeoff', action: () => this.ignore().catch(failed) },
      { label: `Oublier les ${S.state.ignored} ignoré(s)…`, icon: 'refresh', action: () => this.forget().catch(failed) },
    ]);
  },
};
MODULES.dup = Dup;

// ============================================================ 3. sort

const Sort = {
  source: 0, files: [], loaded: false, year: null, folders: [], visible: [], hl: 0,
  cur: null, pct: 25, pvToken: 0, zoom: 1,

  init() {
    this.source = S.ui.sortSource || 0;
    this.t = new VTable($('#sort-table'), {
      id: 'sort', key: r => r.uid, rowHeight: 36, sort: { col: 'dt', dir: 1 },
      empty: 'Rien à trier ici ✨',
      columns: [
        {
          id: 'name', label: 'Fichier', width: 255,
          render: r => `<div class="name-cell"><img loading="lazy" decoding="async" alt="" src="${U.thumb(r.path, r.m)}"><span>${esc(r.name)}</span>${r.video ? '<span class="vid-mark">▶</span>' : ''}</div>`,
        },
        { id: 'dt', label: 'Date et heure', width: 138, cls: 'num', sortKey: r => r.ts },
        { id: 'year', label: 'Année', width: 62, cls: 'num edit', editable: true, onEdit: (r, v) => this.setYear(r, v).catch(failed) },
        {
          id: 'folder', label: 'Dossier', width: 200,
          render: r => (r.folder ? `<span class="folder-chip" title="${esc(`→ ${r.year}\\${r.folder}\\${r.name}`)}"><i style="background:${hue(r.hue)}"></i><span>${esc(r.folder)}</span></span>` : '<span class="ph">—</span>'),
        },
      ],
      onSelect: (sel, cur) => this.onSelect(sel, cur),
      onActivate: (r, e) => { if (e && r) openPath(r.path); else $('#folder-filter').focus(); },
      onContext: (e, sel) => this.menu(e, sel),
      onKey: e => this.tableKey(e),
    });

    $$('#sort-source button').forEach(b => {
      b.classList.toggle('on', +b.dataset.s === this.source);
      b.onclick = () => {
        if (+b.dataset.s === this.source) return;
        this.source = +b.dataset.s;
        uiSet('sortSource', this.source);
        $$('#sort-source button').forEach(x => x.classList.toggle('on', x === b));
        this.load().catch(failed);
      };
    });
    $('#sort-reload').onclick = e => busy(e.currentTarget, () => this.load());
    $('#sort-apply').onclick = e => busy(e.currentTarget, () => this.apply());
    $('#sort-delete').onclick = e => busy(e.currentTarget, () => this.remove());
    $('#sort-byapp').onclick = e => busy(e.currentTarget, () => this.byApp());
    $('#sort-auto').onclick = e => busy(e.currentTarget, () => this.autoOrganize());

    const filter = $('#folder-filter');
    filter.addEventListener('input', () => { this.hl = 0; this.renderFolders(); });
    filter.addEventListener('keydown', e => this.filterKey(e));
    $('#sort-folders').addEventListener('click', e => {
      const f = e.target.closest('.folder');
      if (!f) return;
      if (f.dataset.create) this.createFolder($('#folder-filter').value.trim()).catch(failed);
      else this.assign(this.visible[+f.dataset.i].value).catch(failed);
    });
    $('#sort-folders').addEventListener('contextmenu', e => {
      const f = e.target.closest('.folder[data-i]');
      if (!f) return;
      const x = this.visible[+f.dataset.i];
      menu(e, [
        { label: 'Assigner la sélection', icon: 'check', action: () => this.assign(x.value).catch(failed) },
        { label: 'Renommer le dossier…', icon: 'rename', action: () => this.renameFolder(x).catch(failed) },
        { label: 'Ouvrir le dossier', icon: 'folder', action: () => openPath(`${S.state.camera_path}\\${this.year}\\${x.value}`) },
      ]);
    });

    const stage = $('#pv-stage');
    stage.addEventListener('dblclick', () => { if (this.cur) openPath(this.cur.path); });
    stage.addEventListener('wheel', e => this.wheel(e), { passive: false });
    $('#pv-play').onclick = () => this.playHere();
    $('#pv-pcts').innerHTML = S.state.video_percents.map(p => `<button data-p="${p}">${p === 0 ? 'Début' : p >= 100 ? 'Fin' : `${p} %`}</button>`).join('');
    $('#pv-pcts').onclick = e => { const b = e.target.closest('button'); if (b) this.showFrame(+b.dataset.p); };

    this.previewSoon = debounce(r => this.preview(r), 25);
    initSplitters($('#sort-layout'), 'sortPanes');
  },

  enter() { if (!this.loaded) this.load().catch(failed); },

  async load() {
    this.loaded = true;
    const d = await Task.run('Lecture des fichiers', () => api('/api/sort/files?' + qs({ source: this.source })));
    this.files = d.files;
    this.t.setRows(this.files, { keep: false });
    if (this.files.length) this.t.selectOnly(0); else this.onSelect([], null);
    this.stats();
  },

  base() { return S.state.camera_path.replace(/[\\/]+$/, ''); },

  pending() {
    const base = this.base().toLowerCase();
    return this.files.filter(f => f.year && f.folder
      && dirname(f.path).toLowerCase() !== `${base}\\${f.year}\\${f.folder}`.toLowerCase());
  },

  stats() {
    const assigned = this.files.filter(f => f.folder).length;
    const videos = this.files.filter(f => f.video).length;
    const sel = this.t.sel.size;
    const p = this.pending().length;
    $('#sort-stats').innerHTML = `<span class="stat"><b>${this.files.length}</b> fichier(s)</span>`
      + (videos ? `<span class="stat"><b>${videos}</b> vidéo(s)</span>` : '')
      + `<span class="stat"><i style="background:var(--accent)"></i><b>${assigned}</b> assigné(s)</span>`
      + (sel > 1 ? `<span class="stat"><b>${sel}</b> sélectionné(s)</span>` : '');
    $('#sort-n-apply').textContent = p;
    $('#sort-apply').disabled = !p;
    $('#sort-byapp').disabled = this.source === 0;
    if (this.source === 0) setBadge('#b-sort', this.files.length, true);
  },

  onSelect(sel, cur) {
    if (cur !== this.cur) this.previewSoon(cur);
    if (cur && cur.year && cur.year !== this.year) this.loadFolders(cur.year).catch(failed);
    if (!cur && !sel.length) this.preview(null);
    this.stats();
  },

  tableKey(e) {
    if (e.key === 'Delete') { e.preventDefault(); busy(null, () => this.remove()); return; }
    if (e.key === 'Enter') { e.preventDefault(); $('#folder-filter').focus(); return; }
    if (e.key === 'F2') { e.preventDefault(); this.t.editCurrent('year'); return; }
    // Typing a letter goes straight to the folder filter
    if (e.key.length === 1 && !e.ctrlKey && !e.altKey && !e.metaKey && e.key !== ' ') $('#folder-filter').focus();
  },

  // ----- folders
  async loadFolders(year) {
    this.year = year;
    $('#sort-year').textContent = year || '—';
    if (!year) { this.folders = []; this.renderFolders(); return; }
    const d = await api('/api/sort/folders?' + qs({ year }));
    if (this.year !== year) return;
    this.folders = d.folders;
    this.renderFolders();
  },

  renderFolders() {
    const raw = $('#folder-filter').value.trim(), f = norm(raw);
    this.visible = this.folders.filter(x => !f || norm(x.label).includes(f) || norm(x.value).includes(f));
    if (this.hl >= this.visible.length) this.hl = Math.max(0, this.visible.length - 1);
    const counts = {};
    this.files.forEach(x => { if (x.year === this.year && x.folder) counts[x.folder] = (counts[x.folder] || 0) + 1; });
    let html = this.visible.map((x, i) => `<div class="folder ${x.sub ? 'sub' : ''} ${f && i === this.hl ? 'hl' : ''}" data-i="${i}" title="${esc(`${this.year}\\${x.value}`)}">
      <i style="background:${hue(x.hue)}"></i><span>${esc(x.label)}</span>${counts[x.value] ? `<small>${counts[x.value]}</small>` : ''}</div>`).join('');
    const exists = this.folders.some(x => norm(x.value) === f || norm(x.label) === f);
    if (raw && !exists && this.year) {
      html += `<div class="folder create ${this.visible.length ? '' : 'hl'}" data-create="1"><i></i><span>Créer « ${esc(raw)} » dans ${esc(this.year)}</span></div>`;
    }
    $('#sort-folders').innerHTML = html || `<div class="empty">${this.year ? `Aucun dossier pour ${esc(this.year)}` : 'Sélectionne un fichier daté'}</div>`;
    const hl = $('#sort-folders .hl');
    if (hl) hl.scrollIntoView({ block: 'nearest' });
  },

  filterKey(e) {
    const filter = e.currentTarget;
    if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
      e.preventDefault();
      this.hl = Math.max(0, Math.min(this.visible.length - 1, this.hl + (e.key === 'ArrowDown' ? 1 : -1)));
      this.renderFolders();
    } else if (e.key === 'Enter') {
      e.preventDefault();
      const raw = filter.value.trim();
      if (!raw) return;
      const target = this.visible[this.hl];
      const p = target ? this.assign(target.value) : this.createFolder(raw);
      p.then(() => { filter.value = ''; this.renderFolders(); }).catch(failed);
    } else if (e.key === 'Escape') {
      e.preventDefault();
      filter.value = '';
      this.renderFolders();
      this.t.el.focus();
    } else if (e.key === 'Delete' && filter.selectionStart === filter.value.length && filter.selectionEnd === filter.value.length) {
      // Caret at the end: Delete has nothing to erase in the text, so it trashes the
      // current file, like in the table. Mid-text it still edits the filter.
      e.preventDefault();
      busy(null, () => this.remove());
    }
  },

  async assign(folder) {
    const sel = this.t.selected();
    if (!sel.length) return toast('Sélectionne d’abord des fichiers', 'warn');
    const entry = this.folders.find(x => x.value === folder);
    sel.forEach(r => { r.folder = folder; r.hue = entry ? entry.hue : r.hue; });
    this.t.schedule();
    const d = await api('/api/sort/assign', { uids: sel.map(r => r.uid), folder });
    sel.forEach(r => { r.hue = d.hue; });
    this.afterAssign(sel, folder);
  },

  afterAssign(sel, folder) {
    // Assigning is the last thing you do on a file: move on to the next one
    const last = this.t.lastSelectedIndex();
    if (last >= 0 && last + 1 < this.t.view.length) this.t.selectOnly(last + 1);
    else this.t.schedule();
    this.renderFolders();
    this.stats();
    if (sel.length > 1) toast(`${sel.length} fichiers → ${folder}`, 'ok', 2200);
  },

  async createFolder(name) {
    const sel = this.t.selected();
    if (!sel.length) return toast('Sélectionne d’abord des fichiers', 'warn');
    const year = sel[0].year;
    if (!year) return toast('Année inconnue pour le fichier sélectionné', 'err');
    const d = await api('/api/sort/newfolder', { year, name, uids: sel.map(r => r.uid) });
    sel.forEach(r => { r.folder = name; r.hue = d.hue; });
    await this.loadFolders(year);
    this.afterAssign(sel, name);
    toast(`Dossier « ${name} » créé`, 'ok');
  },

  async renameFolder(x) {
    const name = await promptDlg('Renommer le dossier', `Année ${this.year}`, x.label, { stem: false });
    if (!name || name === x.label) return;
    const d = await api('/api/folder/rename', { year: this.year, old: x.value, new: name });
    const followed = new Set(d.followed);
    this.files.forEach(f => { if (followed.has(f.uid)) { f.folder = d.value; f.hue = d.hue; } });
    await this.loadFolders(this.year);
    this.t.schedule();
    toast(`Dossier renommé en « ${name} »${followed.size ? ` (${followed.size} fichier(s) suivent)` : ''}`, 'ok');
    Viewer.stale = true;
  },

  async setYear(r, v) {
    if (v && !/^\d{4}$/.test(v)) return toast('Année sur 4 chiffres', 'warn');
    const rows = this.t.sel.has(r.uid) ? this.t.selected() : [r];
    rows.forEach(x => { x.year = v; });
    await api('/api/sort/year', { uids: rows.map(x => x.uid), year: v });
    if (this.t.current() && rows.includes(this.t.current())) this.loadFolders(v).catch(failed);
    this.t.schedule();
    this.stats();
  },

  // ----- actions
  async apply() {
    const todo = this.pending();
    if (!todo.length) return toast('Aucun fichier n’a d’année ET de dossier assignés', 'warn');
    const groups = {};
    todo.forEach(f => { const k = `${f.year}\\${f.folder}`; groups[k] = (groups[k] || 0) + 1; });
    const lines = Object.entries(groups).sort((a, b) => b[1] - a[1]).map(([k, n]) => `<b>${n}</b> → ${esc(k)}`);
    const ok = await modal({
      title: `Déplacer ${plural(todo.length, 'fichier')} ?`, ok: 'Déplacer',
      body: listHtml(lines, 10) + '<p class="hint">Un fichier identique déjà présent à destination part dans !duplicate, jamais écrasé.</p>',
    });
    if (!ok) return;
    const d = await Task.run('Déplacements', () => api('/api/sort/apply', {
      view: this.files.map(f => ({ uid: f.uid, year: f.year, folder: f.folder })),   // what you saw is what moves
    }));
    this.files = d.files;
    this.t.setRows(this.files);
    if (!this.t.current() && this.files.length) this.t.selectOnly(0);
    this.stats();
    this.loadFolders(this.year).catch(() => {});
    toast(`${plural(d.moved, 'fichier déplacé', 'fichiers déplacés')}${d.errors.length ? ` — ${d.errors.length} erreur(s)` : ''}`, d.errors.length ? 'warn' : 'ok');
    Viewer.stale = true;
  },

  async remove() {
    const sel = this.t.selected();
    if (!sel.length) return;
    if (sel.length > CONFIRM_ABOVE && !await modal({ title: 'Mettre à la corbeille ?', ok: 'Corbeille', danger: true,
      body: `${plural(sel.length, 'fichier')} part dans la corbeille Windows.` })) return;
    const d = await api('/api/sort/delete', { uids: sel.map(r => r.uid) });
    const gone = new Set(d.deleted);
    this.files = this.files.filter(f => !gone.has(f.uid));
    this.t.removeKeys(d.deleted);
    this.stats();
    toast(`${plural(d.deleted.length, 'fichier')} à la corbeille${d.errors ? `, ${d.errors} erreur(s)` : ''}`, d.errors ? 'warn' : 'ok', 2500);
  },

  async byApp() {
    const dry = await api('/api/sort/byapp', { dry: true });
    if (!dry.files) return toast(dry.seen ? `Aucune appli reconnue sur les ${dry.seen} fichier(s) à la racine des viviers` : 'Les viviers sont déjà rangés', 'warn');
    if (!await modal({ title: `Ranger ${plural(dry.files, 'capture')} par appli ?`, ok: 'Ranger',
      body: `${plural(dry.apps.length, 'dossier')} : ${esc(dry.apps.slice(0, 20).join(', '))}${dry.apps.length > 20 ? '…' : ''}` })) return;
    const d = await Task.run('Rangement par appli', () => api('/api/sort/byapp', { dry: false }));
    toast(`${plural(d.moved, 'capture rangée', 'captures rangées')} par appli`, d.errors ? 'warn' : 'ok');
    await this.load();
  },

  async autoOrganize() {
    if (!await modal({ title: 'Ranger les captures ?', ok: 'Ranger',
      body: 'Les captures et enregistrements d’écran à la racine de Camera, ainsi que DCIM\\ScreenRecorder et Pictures, vont dans <b>ANNÉE\\!Screenshots_ANNÉE</b> / <b>!ScreenRecorder_ANNÉE</b>.' })) return;
    const d = await Task.run('Rangement', () => api('/api/sort/auto', {}));
    toast(`${plural(d.moved, 'fichier rangé', 'fichiers rangés')}`, 'ok');
    await this.load();
  },

  menu(e, sel) {
    const one = sel.length === 1;
    menu(e, [
      { label: 'Ouvrir', icon: 'external', disabled: !one, action: () => openPath(sel[0].path) },
      { label: 'Afficher dans l’Explorateur', icon: 'folder', disabled: !one, action: () => openPath(sel[0].path, true) },
      { label: 'Corriger l’année…', icon: 'calendar', action: () => this.t.editCurrent('year') },
      { label: 'Retirer le dossier assigné', icon: 'x', action: () => this.assign('').catch(failed) },
      '-',
      { label: `Corbeille${one ? '' : ` (${sel.length})`}`, icon: 'trash', danger: true, action: () => busy(null, () => this.remove()) },
    ]);
  },

  // ----- preview
  preview(r) {
    this.cur = r;
    this.zoom = 1;
    const stage = $('#pv-stage');
    stage.classList.remove('zoomed');
    const info = $('#pv-info');
    $('#pv-video').classList.toggle('hidden', !(r && r.video));
    if (!r) { stage.innerHTML = '<div class="empty">Sélectionne un fichier</div>'; info.innerHTML = ''; return; }
    const dest = r.year && r.folder ? `→ ${r.year}\\${r.folder}` : 'Aucun dossier choisi';
    info.innerHTML = `<div class="n selectable" title="${esc(r.path)}">${esc(r.name)}</div>
      <div class="m">${esc(r.dt)} · ${humanSize(r.size)}</div>
      <div class="dest ${r.year && r.folder ? '' : 'none'}">${esc(dest)}</div>`;
    if (r.video) { this.pct = 25; this.markPct(); }
    this.loadImage(r.video ? U.preview(r.path, r.m, this.pct) : U.preview(r.path, r.m), r);
    this.prefetch();
  },

  loadImage(url, r) {
    const stage = $('#pv-stage');
    const token = ++this.pvToken;
    const img = new Image();
    img.alt = '';
    img.decoding = 'async';
    // Keep the previous picture until the new one is decoded: no black flash
    const spin = setTimeout(() => {
      if (token === this.pvToken && !$('.loading', stage)) stage.insertAdjacentHTML('beforeend', '<div class="spinner loading"></div>');
    }, 150);
    img.onload = () => {
      clearTimeout(spin);
      if (token !== this.pvToken) return;
      stage.replaceChildren(img);
      this.zoom = 1;
      stage.classList.remove('zoomed');
    };
    img.onerror = () => {
      clearTimeout(spin);
      if (token !== this.pvToken) return;
      stage.innerHTML = `<div class="empty">${r && r.video ? (S.state.ffmpeg ? 'Image non extractible' : 'ffmpeg introuvable : pas d’aperçu vidéo') : 'Pas d’aperçu pour ce fichier'}<br><br><button class="btn sm" onclick="Sort.cur && openPath(Sort.cur.path)">${icon('external')}Ouvrir</button></div>`;
    };
    img.src = url;
  },

  prefetch() {
    const i = this.t.cur;
    [1, 2, -1, 3].forEach(o => {
      const r = this.t.view[i + o];
      if (r) new Image().src = r.video ? U.preview(r.path, r.m, 25) : U.preview(r.path, r.m);
    });
  },

  markPct() { $$('#pv-pcts button').forEach(b => b.classList.toggle('on', +b.dataset.p === this.pct)); },

  showFrame(pct) {
    if (!this.cur || !this.cur.video) return;
    this.pct = pct;
    this.markPct();
    this.loadImage(U.preview(this.cur.path, this.cur.m, pct), this.cur);
  },

  playHere() {
    const r = this.cur;
    if (!r) return;
    ++this.pvToken;
    const stage = $('#pv-stage');
    stage.innerHTML = `<video src="${U.media(r.path)}" controls autoplay></video>`;
    $('video', stage).onerror = () => {
      toast('Format non lisible dans la fenêtre — ouverture dans le lecteur', 'warn');
      openPath(r.path);
    };
  },

  wheel(e) {
    if (!e.ctrlKey) return;
    e.preventDefault();
    const stage = $('#pv-stage'), img = $('img', stage);
    if (!img || !img.naturalWidth) return;
    const fit = Math.min(stage.clientWidth / img.naturalWidth, stage.clientHeight / img.naturalHeight, 1);
    const old = this.zoom;
    this.zoom = Math.max(1, Math.min(10, this.zoom * (e.deltaY < 0 ? 1.15 : 1 / 1.15)));
    if (this.zoom === 1) { stage.classList.remove('zoomed'); img.style.width = ''; return; }
    const rect = stage.getBoundingClientRect();
    const px = e.clientX - rect.left + stage.scrollLeft, py = e.clientY - rect.top + stage.scrollTop;
    stage.classList.add('zoomed');
    img.style.width = `${img.naturalWidth * fit * this.zoom}px`;
    const k = this.zoom / old;
    stage.scrollLeft = px * k - (e.clientX - rect.left);
    stage.scrollTop = py * k - (e.clientY - rect.top);
  },
};
MODULES.sort = Sort;

function initSplitters(layout, key) {
  const saved = S.ui[key] || {};
  Object.entries(saved).forEach(([k, v]) => layout.style.setProperty(k, v));
  $$('.splitter', layout).forEach(sp => {
    sp.addEventListener('mousedown', e => {
      e.preventDefault();
      const v = sp.dataset.var;
      const prev = sp.previousElementSibling;
      const x0 = e.clientX, w0 = prev.getBoundingClientRect().width;
      sp.classList.add('drag');
      const move = ev => layout.style.setProperty(v, `${Math.max(200, Math.min(innerWidth * 0.7, w0 + ev.clientX - x0))}px`);
      const up = () => {
        document.removeEventListener('mousemove', move);
        document.removeEventListener('mouseup', up);
        sp.classList.remove('drag');
        const cur = S.ui[key] || {};
        cur[v] = layout.style.getPropertyValue(v);
        uiSet(key, cur);
      };
      document.addEventListener('mousemove', move);
      document.addEventListener('mouseup', up);
    });
  });
}

// ============================================================ 4. viewer

function timelineTicks(lo, hi) {
  const span = (hi - lo) / 1000, day = 86400, out = [];
  if (span <= 2 * day) {
    const step = 3600 * (span <= 6 * 3600 ? 1 : span <= 12 * 3600 ? 3 : 6);
    const t = new Date(lo); t.setMinutes(0, 0, 0);
    for (let x = +t; x <= hi; x += step * 1000) if (x >= lo) out.push([x, `${new Date(x).getHours()}h`]);
  } else if (span <= 45 * day) {
    const sd = span <= 10 * day ? 1 : 7;
    const t = new Date(lo); t.setHours(0, 0, 0, 0);
    for (; +t <= hi; t.setDate(t.getDate() + sd)) if (+t >= lo) out.push([+t, `${pad(t.getDate())}/${pad(t.getMonth() + 1)}`]);
  } else if (span <= 800 * day) {
    const sm = span <= 400 * day ? 1 : 3;
    const d0 = new Date(lo);
    for (let t = new Date(d0.getFullYear(), d0.getMonth(), 1); +t <= hi; t = new Date(t.getFullYear(), t.getMonth() + sm, 1)) {
      if (+t >= lo) out.push([+t, `${t.toLocaleDateString('fr-FR', { month: 'short' }).replace('.', '')} ${String(t.getFullYear()).slice(2)}`]);
    }
  } else {
    const ys = Math.max(1, Math.round(span / (365 * day) / 8));
    for (let y = new Date(lo).getFullYear(); +new Date(y, 0, 1) <= hi; y += ys) {
      const x = +new Date(y, 0, 1);
      if (x >= lo) out.push([x, String(y)]);
    }
  }
  return out;
}

class Timeline {
  constructor(el, onPick) {
    this.el = el; this.cv = $('canvas', el); this.tip = $('.tl-tip', el); this.onPick = onPick;
    this.points = []; this.sel = -1; this.yearMode = false; this.year = null;
    new ResizeObserver(() => this.draw()).observe(el);
    this.cv.addEventListener('mousemove', e => this.hover(e));
    this.cv.addEventListener('mouseleave', () => this.tip.classList.add('hidden'));
    this.cv.addEventListener('click', e => { const i = this.indexAt(e); if (i >= 0) this.onPick(i); });
  }
  set(points, year) { this.points = points; this.year = year; this.sel = -1; this.draw(); }
  select(i) { this.sel = i; this.draw(); }
  span() {
    const ts = this.points.map(p => p.ts).filter(Boolean);
    if (!ts.length) return [null, null];
    if (this.yearMode) {
      const y = +this.year || new Date(Math.max(...ts)).getFullYear();
      return [+new Date(y, 0, 1), +new Date(y, 11, 31, 23, 59, 59)];
    }
    return [Math.min(...ts), Math.max(...ts)];
  }
  x(ts, lo, hi) {
    const M = 52, u = Math.max(1, this.w - 2 * M);
    return hi === lo ? M + u / 2 : M + (u * (ts - lo)) / (hi - lo);
  }
  indexAt(e) {
    const [lo, hi] = this.span();
    if (lo == null) return -1;
    const r = this.cv.getBoundingClientRect(), x = e.clientX - r.left, y = e.clientY - r.top;
    if (Math.abs(y - this.h / 2) > 20) return -1;
    let best = -1, bd = 10;
    this.points.forEach((p, i) => {
      if (!p.ts) return;
      const d = Math.abs(this.x(p.ts, lo, hi) - x);
      if (d < bd) { best = i; bd = d; }
    });
    return best;
  }
  hover(e) {
    const i = this.indexAt(e);
    if (i < 0) { this.tip.classList.add('hidden'); return; }
    const p = this.points[i];
    const [lo, hi] = this.span();
    this.tip.textContent = `${p.label} · ${new Date(p.ts).toLocaleString('fr-FR', { dateStyle: 'short', timeStyle: 'short' })}`;
    this.tip.style.left = `${this.x(p.ts, lo, hi)}px`;
    this.tip.style.top = `${this.h / 2 - 8}px`;
    this.tip.classList.remove('hidden');
  }
  draw() {
    const dpr = devicePixelRatio || 1, w = this.el.clientWidth, h = this.el.clientHeight;
    if (!w || !h) return;
    this.w = w; this.h = h;
    this.cv.width = w * dpr; this.cv.height = h * dpr;
    const g = this.cv.getContext('2d');
    g.setTransform(dpr, 0, 0, dpr, 0, 0);
    g.clearRect(0, 0, w, h);
    const mid = Math.round(h / 2) + 4;
    g.strokeStyle = '#2c3343'; g.lineWidth = 2;
    g.beginPath(); g.moveTo(52, mid); g.lineTo(w - 52, mid); g.stroke();
    g.font = '11px "Segoe UI", sans-serif';
    const [lo, hi] = this.span();
    if (lo == null) {
      g.fillStyle = '#6f7890'; g.textAlign = 'center';
      g.fillText(this.points.length ? 'Aucune date exploitable' : '', w / 2, mid - 10);
      return;
    }
    g.textAlign = 'center';
    let lastX = -1e9;
    for (const [t, label] of timelineTicks(lo, hi)) {
      const x = this.x(t, lo, hi);
      g.strokeStyle = '#2c3343'; g.lineWidth = 1;
      g.beginPath(); g.moveTo(x, mid - 7); g.lineTo(x, mid + 7); g.stroke();
      if (x - lastX > 38) { g.fillStyle = '#6f7890'; g.fillText(label, x, mid - 13); lastX = x; }
    }
    this.points.forEach((p, i) => {
      if (!p.ts || i === this.sel) return;
      g.fillStyle = p.video ? 'rgba(94,200,255,.85)' : 'rgba(139,124,255,.8)';
      g.beginPath(); g.arc(this.x(p.ts, lo, hi), mid, 3.6, 0, 7); g.fill();
    });
    if (this.sel >= 0 && this.points[this.sel] && this.points[this.sel].ts) {
      const x = this.x(this.points[this.sel].ts, lo, hi);
      g.fillStyle = '#ffd479'; g.strokeStyle = '#fff'; g.lineWidth = 1.5;
      g.beginPath(); g.arc(x, mid, 6.5, 0, 7); g.fill(); g.stroke();
    }
    const n = this.points.filter(p => p.ts).length;
    const days = Math.round((hi - lo) / 864e5);
    const fmt = t => new Date(t).toLocaleDateString('fr-FR') + (days ? '' : ` ${new Date(t).toLocaleTimeString('fr-FR', { hour: '2-digit', minute: '2-digit' })}`);
    g.fillStyle = '#aab2c3'; g.textAlign = 'left'; g.fillText(fmt(lo), 6, mid + 24);
    g.textAlign = 'right'; g.fillText(fmt(hi), w - 6, mid + 24);
    const real = this.points.filter(p => p.ts).map(p => p.ts);
    const realDays = Math.round((Math.max(...real) - Math.min(...real)) / 864e5);
    g.textAlign = 'center'; g.fillStyle = '#6f7890';
    g.fillText(`${n} média(s)${this.yearMode ? ` — année ${new Date(lo).getFullYear()}` : realDays ? ` — ${realDays} jour(s)` : ''}`, w / 2, 14);
  }
}

const Viewer = {
  years: [], year: null, folders: [], folder: null, sub: '', media: [], subs: [],
  sel: new Set(), cur: -1, anchor: -1, loaded: false, stale: false,

  init() {
    this.tl = new Timeline($('#vw-timeline'), i => { this.selectOnly(i); });
    $('#vw-years').addEventListener('click', e => { const b = e.target.closest('.year'); if (b) this.selectYear(b.dataset.y).catch(failed); });
    $('#vw-folders').addEventListener('click', e => { const f = e.target.closest('.folder'); if (f) this.openFolder(f.dataset.n).catch(failed); });
    $('#vw-folders').addEventListener('contextmenu', e => {
      const f = e.target.closest('.folder');
      if (!f) return;
      menu(e, [{ label: 'Ouvrir le dossier', icon: 'folder', action: () => openPath(`${S.state.camera_path}\\${this.year}\\${f.dataset.n}`) }]);
    });
    $('#vw-filter').addEventListener('input', () => this.renderFolders());
    const grid = $('#vw-grid');
    grid.addEventListener('mousedown', e => this.gridDown(e));
    grid.addEventListener('dblclick', e => { const t = e.target.closest('.tile'); if (t) this.lightbox(+t.dataset.i); });
    grid.addEventListener('contextmenu', e => this.gridMenu(e));
    grid.addEventListener('keydown', e => this.gridKey(e));
    $('#vw-crumbs').addEventListener('click', e => {
      const c = e.target.closest('[data-sub]');
      if (c) { this.sub = c.dataset.sub; this.loadMedia().catch(failed); }
    });
    const size = $('#vw-size');
    size.value = S.ui.tile || 168;
    grid.style.setProperty('--tile', `${size.value}px`);
    size.oninput = () => { grid.style.setProperty('--tile', `${size.value}px`); uiSet('tile', +size.value); };
    const fit = $('#vw-fit');
    fit.checked = !!S.ui.fit;
    grid.classList.toggle('fit', fit.checked);
    fit.onchange = () => { grid.classList.toggle('fit', fit.checked); uiSet('fit', fit.checked); };
    const ym = $('#vw-yearmode');
    ym.checked = !!S.ui.yearMode;
    this.tl.yearMode = ym.checked;
    ym.onchange = () => { this.tl.yearMode = ym.checked; uiSet('yearMode', ym.checked); this.tl.draw(); };
    $('#vw-open-folder').onclick = () => { const p = this.folderPath(); if (p) openPath(p); };
  },

  enter() {
    if (!this.loaded || this.stale) { this.stale = false; this.loadYears().catch(failed); }
  },

  folderPath() {
    if (!this.year || !this.folder) return null;
    return `${S.state.camera_path}\\${this.year}\\${this.folder}${this.sub ? `\\${this.sub}` : ''}`;
  },

  async loadYears() {
    this.loaded = true;
    const d = await api('/api/viewer/years');
    this.years = d.years;
    $('#vw-years').innerHTML = this.years.map(y => `<button class="year" data-y="${y.year}">${y.year}<small>${y.folders}</small></button>`).join('');
    const want = this.year || S.ui.vwYear;
    const y = this.years.find(x => x.year === want) ? want : (this.years[0] || {}).year;
    if (y) await this.selectYear(y, true);
  },

  async selectYear(y, keepFolder = false) {
    this.year = y;
    uiSet('vwYear', y);
    $$('#vw-years .year').forEach(b => b.classList.toggle('on', b.dataset.y === y));
    $('#vw-year').textContent = y;
    const d = await api('/api/viewer/folders?' + qs({ year: y }));
    if (this.year !== y) return;
    this.folders = d.folders;
    this.renderFolders();
    const want = keepFolder ? (this.folder || S.ui.vwFolder) : null;
    if (want && this.folders.some(f => f.name === want)) await this.openFolder(want, keepFolder);
    else if (this.folders.length) await this.openFolder(this.folders[0].name);
    else { this.folder = null; this.media = []; this.renderGrid(); }
  },

  renderFolders() {
    const f = norm($('#vw-filter').value.trim());
    const list = this.folders.filter(x => !f || norm(x.name).includes(f));
    $('#vw-folders').innerHTML = list.map(x => `<div class="folder ${x.special ? 'special' : ''} ${x.name === this.folder ? 'hl' : ''}" data-n="${esc(x.name)}" title="${esc(x.name)}">
      <i style="background:${x.special ? '#3a4152' : hue(x.hue)}"></i><span>${esc(x.name)}</span><small>${x.count || ''}</small></div>`).join('')
      || '<div class="empty">Aucun dossier</div>';
  },

  async openFolder(name, keepSub = false) {
    if (name !== this.folder || !keepSub) this.sub = '';
    this.folder = name;
    uiSet('vwFolder', name);
    this.renderFolders();
    await this.loadMedia();
  },

  async loadMedia() {
    const folder = this.sub ? `${this.folder}\\${this.sub}` : this.folder;
    const key = `${this.year}/${folder}`;
    this.loadingKey = key;
    const d = await api('/api/viewer/media?' + qs({ year: this.year, folder }));
    if (this.loadingKey !== key) return;
    this.media = d.media;
    this.subs = d.subfolders;
    this.sel.clear(); this.cur = -1; this.anchor = -1;
    this.renderGrid();
    $('#vw-grid').scrollTop = 0;
  },

  renderCrumbs() {
    let html = `<b>${esc(this.folder || '')}</b>`;
    if (this.sub) html = `<span class="chip plain c-muted" data-sub="">${esc(this.folder)}</span>${icon('right')}<b>${esc(this.sub)}</b>`;
    html += ` <span class="hint">${plural(this.media.length, 'média')}</span>`;
    if (!this.sub && this.subs.length) html += this.subs.slice(0, 40).map(s => `<span class="chip plain c-accent" data-sub="${esc(s)}">${esc(s)}</span>`).join('');
    $('#vw-crumbs').innerHTML = html;
  },

  renderGrid() {
    this.renderCrumbs();
    const grid = $('#vw-grid');
    grid.innerHTML = this.media.map((m, i) => `<div class="tile" data-i="${i}" title="${esc(`${m.name}\n${m.dt}`)}">
      <div class="ph"><img loading="lazy" decoding="async" alt="" src="${U.thumb(m.path, m.m)}" onload="this.classList.add('ok')"></div>
      <div class="cap">${esc(m.name)}</div>${m.video ? `<span class="play">${icon('play')}</span>` : ''}</div>`).join('')
      || '<div class="hint" style="padding:30px">Aucun média dans ce dossier.</div>';
    this.tl.set(this.media.map(m => ({ ts: m.ts * 1000, label: m.name, video: m.video })), this.year);
  },

  updateSel() {
    $$('#vw-grid .tile').forEach(t => {
      const i = +t.dataset.i;
      t.classList.toggle('sel', this.sel.has(i));
      t.classList.toggle('cur', i === this.cur);
    });
    this.tl.select(this.cur);
  },

  selectOnly(i) {
    if (i < 0 || i >= this.media.length) return;
    this.sel = new Set([i]); this.cur = i; this.anchor = i;
    this.updateSel();
    const t = $(`#vw-grid .tile[data-i="${i}"]`);
    if (t) t.scrollIntoView({ block: 'nearest' });
  },

  gridDown(e) {
    const t = e.target.closest('.tile');
    $('#vw-grid').focus({ preventScroll: true });
    if (!t) return;
    const i = +t.dataset.i;
    if (e.button === 2 && this.sel.has(i)) return;
    if (e.shiftKey && this.anchor >= 0) {
      if (!e.ctrlKey) this.sel.clear();
      for (let k = Math.min(this.anchor, i); k <= Math.max(this.anchor, i); k++) this.sel.add(k);
      this.cur = i;
    } else if (e.ctrlKey) {
      if (this.sel.has(i)) this.sel.delete(i); else this.sel.add(i);
      this.cur = i; this.anchor = i;
    } else { this.sel = new Set([i]); this.cur = i; this.anchor = i; }
    this.updateSel();
  },

  columns() { return getComputedStyle($('#vw-grid')).gridTemplateColumns.split(' ').length || 1; },

  gridKey(e) {
    const n = this.media.length;
    if (!n) return;
    const cols = this.columns();
    const moves = { ArrowRight: 1, ArrowLeft: -1, ArrowDown: cols, ArrowUp: -cols };
    if (moves[e.key] !== undefined) {
      e.preventDefault();
      const to = Math.max(0, Math.min(n - 1, (this.cur < 0 ? 0 : this.cur + moves[e.key])));
      if (e.shiftKey) {
        if (this.anchor < 0) this.anchor = Math.max(0, this.cur);
        this.sel.clear();
        for (let k = Math.min(this.anchor, to); k <= Math.max(this.anchor, to); k++) this.sel.add(k);
        this.cur = to;
        this.updateSel();
        const t = $(`#vw-grid .tile[data-i="${to}"]`);
        if (t) t.scrollIntoView({ block: 'nearest' });
      } else this.selectOnly(to);
    } else if (e.key === 'Home') { e.preventDefault(); this.selectOnly(0); }
    else if (e.key === 'End') { e.preventDefault(); this.selectOnly(n - 1); }
    else if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); if (this.cur >= 0) this.lightbox(this.cur); }
    else if (e.key === 'Delete') { e.preventDefault(); busy(null, () => this.trash()); }
    else if (e.key === 'F2') { e.preventDefault(); this.rename().catch(failed); }
    else if ((e.key === 'a' || e.key === 'A') && e.ctrlKey) { e.preventDefault(); this.sel = new Set(this.media.map((_, i) => i)); this.updateSel(); }
  },

  gridMenu(e) {
    const t = e.target.closest('.tile');
    if (!t) return e.preventDefault();
    const i = +t.dataset.i;
    if (!this.sel.has(i)) this.selectOnly(i);
    const paths = this.selectedPaths(), one = paths.length === 1;
    menu(e, [
      { label: 'Afficher', icon: 'images', disabled: !one, action: () => this.lightbox(i) },
      { label: 'Ouvrir', icon: 'external', action: () => paths.slice(0, 5).forEach(p => openPath(p)) },
      { label: 'Afficher dans l’Explorateur', icon: 'folder', disabled: !one, action: () => openPath(paths[0], true) },
      { label: 'Renommer…', icon: 'rename', disabled: !one, action: () => this.rename().catch(failed) },
      '-',
      { label: `Corbeille${one ? '' : ` (${paths.length})`}`, icon: 'trash', danger: true, action: () => busy(null, () => this.trash()) },
    ]);
  },

  selectedPaths() { return [...this.sel].sort((a, b) => a - b).map(i => this.media[i].path); },

  async rename(index = this.cur) {
    if (index < 0 || (this.sel.size > 1 && index === this.cur)) return toast('Sélectionne un seul média pour le renommer', 'warn');
    const m = this.media[index];
    const name = await promptDlg('Renommer', 'Nouveau nom', m.name);
    if (!name || name === m.name) return;
    const d = await api('/api/media/rename', { path: m.path, name });
    Object.assign(m, { path: d.path, name: d.name, m: d.m });
    const t = $(`#vw-grid .tile[data-i="${index}"]`);
    if (t) { $('.cap', t).textContent = d.name; t.title = d.name; }
    toast(`Renommé en « ${d.name} »`, 'ok');
  },

  async trash(paths = this.selectedPaths()) {
    if (!paths.length) return;
    if (paths.length > CONFIRM_ABOVE && !await modal({ title: 'Mettre à la corbeille ?', ok: 'Corbeille', danger: true, body: `${plural(paths.length, 'média')} part dans la corbeille Windows.` })) return;
    const first = Math.min(...[...this.sel]);
    const d = await api('/api/media/trash', { paths });
    const gone = new Set(d.deleted);
    this.media = this.media.filter(m => !gone.has(m.path));
    const scroll = $('#vw-grid').scrollTop;
    this.renderGrid();
    $('#vw-grid').scrollTop = scroll;
    this.sel.clear();
    if (this.media.length) this.selectOnly(Math.min(Number.isFinite(first) ? first : 0, this.media.length - 1));
    const f = this.folders.find(x => x.name === this.folder);
    if (f && !this.sub) { f.count = this.media.length; this.renderFolders(); }
    toast(`${plural(d.deleted.length, 'média')} à la corbeille${d.errors ? `, ${d.errors} erreur(s)` : ''}`, d.errors ? 'warn' : 'ok', 2500);
    return d;
  },

  lightbox(i) {
    Lightbox.open(this.media, i, {
      onIndex: k => this.selectOnly(k),
      onTrash: async k => { this.selectOnly(k); const d = await this.trash([this.media[k].path]); return d; },
      onRename: async k => { await this.rename(k); },
    });
  },
};
MODULES.viewer = Viewer;

const Lightbox = {
  open(list, i, hooks) {
    this.list = list; this.i = i; this.hooks = hooks;
    this.prev = document.activeElement;
    const el = document.createElement('div');
    el.id = 'lightbox';
    el.innerHTML = `<div class="lb-top"><div class="t"><b></b><small></small></div>
      <button class="btn sm ghost" data-a="rename">${icon('rename')}Renommer</button>
      <button class="btn sm ghost" data-a="reveal">${icon('folder')}Dossier</button>
      <button class="btn sm ghost" data-a="open">${icon('external')}Ouvrir</button>
      <button class="btn sm danger" data-a="trash">${icon('trash')}Corbeille</button>
      <button class="btn sm ghost" data-a="close">${icon('x')}</button></div>
      <div class="lb-stage"></div><div class="lb-foot">← → pour naviguer · Échap pour fermer · Suppr pour la corbeille</div>`;
    document.body.appendChild(el);
    this.el = el;
    el.addEventListener('click', e => {
      const b = e.target.closest('[data-a]');
      if (b) this.act(b.dataset.a);
      else if (e.target.closest('.nav-btn')) this.go(e.target.closest('.nav-btn').classList.contains('l') ? -1 : 1);
      else if (e.target.classList.contains('lb-stage')) this.close();
    });
    this.onKey = e => {
      if ($('.backdrop')) return;
      const k = { Escape: () => this.close(), ArrowLeft: () => this.go(-1), ArrowRight: () => this.go(1),
        Delete: () => this.act('trash'), F2: () => this.act('rename'), Enter: () => this.act('open') }[e.key];
      if (k) { e.preventDefault(); e.stopPropagation(); k(); }
    };
    document.addEventListener('keydown', this.onKey, true);
    this.render();
  },
  render() {
    const m = this.list[this.i];
    if (!m) return this.close();
    $('.t b', this.el).textContent = m.name;
    $('.t small', this.el).textContent = `${m.dt} · ${humanSize(m.size)} · ${this.i + 1} / ${this.list.length}`;
    const stage = $('.lb-stage', this.el);
    stage.innerHTML = (m.video ? `<video src="${U.media(m.path)}" controls autoplay poster="${U.preview(m.path, m.m, 25)}"></video>` : `<img alt="" src="${U.preview(m.path, m.m)}">`)
      + `<button class="nav-btn l">${icon('left')}</button><button class="nav-btn r">${icon('right')}</button>`;
    [-1, 1, 2].forEach(o => { const n = this.list[this.i + o]; if (n && !n.video) new Image().src = U.preview(n.path, n.m); });
    if (this.hooks.onIndex) this.hooks.onIndex(this.i);
  },
  go(d) { const j = this.i + d; if (j >= 0 && j < this.list.length) { this.i = j; this.render(); } },
  async act(a) {
    const m = this.list[this.i];
    if (a === 'close') return this.close();
    if (!m) return;
    if (a === 'open') openPath(m.path);
    else if (a === 'reveal') openPath(m.path, true);
    else if (a === 'rename') { await this.hooks.onRename(this.i).catch(failed); this.render(); }
    else if (a === 'trash') {
      const stage = $('.lb-stage video', this.el);
      if (stage) stage.pause();
      try {
        await this.hooks.onTrash(this.i);
        this.list = Viewer.media;
        if (!this.list.length) return this.close();
        this.i = Math.min(this.i, this.list.length - 1);
        this.render();
      } catch (e) { failed(e); }
    }
  },
  close() {
    if (!this.el) return;
    document.removeEventListener('keydown', this.onKey, true);
    this.el.remove();
    this.el = null;
    $('#vw-grid').focus({ preventScroll: true });
  },
};

// ============================================================ settings / log / import

async function openSettings(reason) {
  const st = S.state;
  const row = (k, v) => `<span>${k}</span><code>${esc(v || '—')}</code>`;
  const ok = await modal({
    title: 'Réglages', ok: 'Enregistrer', wide: true,
    body: `${reason ? `<p class="lvl-diff">${esc(reason)}</p>` : ''}
      <div class="field"><label>Dossier Camera</label><div class="row"><input class="input" id="set-cam" value="${esc(st.camera_path)}"><button class="btn" data-browse="set-cam">Parcourir…</button></div></div>
      <div class="field" style="margin-top:12px"><label>Dossier pCloud</label><div class="row"><input class="input" id="set-pc" value="${esc(st.pcloud_root_raw)}" placeholder="${esc(st.pcloud_root)} (déduit de Camera)"><button class="btn" data-browse="set-pc">Parcourir…</button></div>
        <span class="help">Le dossier qui contient DCIM\\ et Pictures\\. Vide = déduit du dossier Camera.</span></div>
      <label class="check" style="margin:12px 0"><input type="checkbox" id="set-auto" ${st.pcloud_autoimport ? 'checked' : ''}>Importer pCloud à l’ouverture (vide Pictures\\ et DCIM\\Screenshots / ScreenRecorder dans Camera)</label>
      <div class="status-grid">${row('ffmpeg', st.ffmpeg)}${row('ffprobe', st.ffprobe)}${row('Pillow', st.pil ? 'OK' : 'absent')}${row('HEIC', st.heif ? 'OK' : 'absent (pip install pillow-heif)')}${row('Doublons ignorés', String(st.ignored))}</div>`,
    collect: bd => ({ camera_path: $('#set-cam', bd).value.trim(), pcloud_root: $('#set-pc', bd).value.trim(), pcloud_autoimport: $('#set-auto', bd).checked }),
    mount: bd => {
      $$('[data-browse]', bd).forEach(b => b.onclick = async () => {
        const input = $(`#${b.dataset.browse}`, bd);
        const d = await api('/api/browse', { initial: input.value || st.camera_path, title: 'Choisir un dossier' }).catch(failed);
        if (d && d.path) input.value = d.path;
      });
    },
  });
  if (!ok) return;
  const changed = ok.camera_path !== st.camera_path;
  S.state = await api('/api/config', ok);
  toast('Réglages enregistrés', 'ok');
  if (changed) location.reload();
}

async function importNow() {
  if (!await modal({ title: 'Importer pCloud ?', ok: 'Importer',
    body: `Vide <b>Pictures\\</b> (fichiers à la racine) et <b>DCIM\\Screenshots / ScreenRecorder</b> dans Camera.
      Une capture déjà rangée ailleurs n’est jamais doublée : l’arrivant part dans !duplicate.` })) return;
  const d = await Task.run('Import pCloud', () => api('/api/import', {}));
  toast(`Import pCloud : ${plural(d.imported, 'fichier rangé', 'fichiers rangés')}`, 'ok');
  if (d.imported) {
    await Promise.all([Sort.load(), Rename.load()]);
    Dup.loaded = false; Viewer.stale = true;
    if (S.view === 'dup') Dup.enter();
    if (S.view === 'viewer') Viewer.enter();
  }
}

const Log = {
  add(line) {
    const pre = $('#log-pre');
    const span = document.createElement('span');
    span.className = /❌/.test(line) ? 'e' : /⚠️/.test(line) ? 'w' : /✅/.test(line) ? 'k' : '';
    span.textContent = line + '\n';
    const stick = pre.scrollTop + pre.clientHeight >= pre.scrollHeight - 30;
    pre.appendChild(span);
    while (pre.childNodes.length > 1500) pre.firstChild.remove();
    if (stick) pre.scrollTop = pre.scrollHeight;
    if (span.className === 'e' && !$('#log').classList.contains('open')) $('#log-err').classList.remove('hidden');
  },
  toggle(open = !$('#log').classList.contains('open')) {
    $('#log').classList.toggle('open', open);
    if (open) { $('#log-err').classList.add('hidden'); const pre = $('#log-pre'); pre.scrollTop = pre.scrollHeight; }
  },
};

function connectEvents() {
  const es = new EventSource('/api/events');
  es.onmessage = e => {
    let ev;
    try { ev = JSON.parse(e.data); } catch (_) { return; }
    if (ev.t === 'log') Log.add(ev.line);
    else if (ev.t === 'progress') Task.progress(ev);
    else if (ev.t === 'score') Dup.onScore(ev);
  };
}

// ============================================================ boot

async function boot() {
  try { S.state = await api('/api/state'); } catch (e) {
    $('#splash-msg').textContent = 'Serveur TriPhoto injoignable — relance TriPhoto.bat';
    return;
  }
  S.ui = S.state.ui || {};
  connectEvents();
  Rename.init(); Dup.init(); Sort.init(); Viewer.init();
  $$('.nav-item[data-view]').forEach(b => { b.onclick = () => show(b.dataset.view); });
  $('#btn-settings').onclick = () => openSettings().catch(failed);
  $('#btn-import').onclick = () => importNow().catch(failed);
  $('#btn-log').onclick = () => Log.toggle();
  $('#log-close').onclick = () => Log.toggle(false);
  $('#log-clear').onclick = () => { $('#log-pre').textContent = ''; };
  document.addEventListener('keydown', e => {
    if (e.ctrlKey && e.key >= '1' && e.key <= '4' && !$('.backdrop') && !$('#lightbox')) {
      e.preventDefault();
      show(['rename', 'dup', 'sort', 'viewer'][+e.key - 1]);
    }
  });
  if (!S.state.camera_ok) {
    $('#splash').classList.add('gone');
    show(S.ui.view);
    openSettings(`Dossier Camera introuvable : ${S.state.camera_path}`).catch(failed);
    return;
  }
  $('#splash-msg').textContent = S.state.pcloud_autoimport && !S.state.no_import ? 'Import pCloud…' : 'Chargement…';
  try {
    const r = await api('/api/startup', {});
    if (r.imported) toast(`Import pCloud : ${plural(r.imported, 'fichier rangé', 'fichiers rangés')}`, 'ok', 6000);
  } catch (e) { failed(e); }
  $('#splash').classList.add('gone');
  setTimeout(() => $('#splash').remove(), 400);
  show(S.ui.view || 'sort');
  // Like the Qt edition: names and files to sort are read at startup, so the badges are right
  if (!Sort.loaded) Sort.load().catch(failed);
  if (!Rename.loaded) Rename.load().catch(failed);
  const focus = { sort: () => Sort.t.el, rename: () => Rename.t.el, dup: () => Dup.t.el, viewer: () => $('#vw-grid') }[S.view];
  if (focus) setTimeout(() => focus().focus({ preventScroll: true }), 50);
}

boot();
  // Delete works wherever the focus is in the tab (preview, buttons, compare panel…),
  // not only on the table. Tables and the grid handle it first and preventDefault.
  document.addEventListener('keydown', e => {
    if (e.key !== 'Delete' || e.defaultPrevented || e.ctrlKey || e.altKey) return;
    if ($('.backdrop') || $('#lightbox') || $('.menu')) return;
    const t = e.target;
    if (t.closest && t.closest('input, textarea, select, [contenteditable="true"]')) return;
    const act = { dup: () => Dup.trash(e.shiftKey ? 0 : 'auto'), sort: () => Sort.remove(), viewer: () => Viewer.trash() }[S.view];
    if (!act) return;
    e.preventDefault();
    busy(null, act);
  });
