// Frame-accurate compositor for 《家的大脑》. renderFrame(g) draws global frame g as a
// pure function of the timeline, so frames can be rendered in any order.
'use strict';

const W = 1920, HGT = 1080, BAR = 140, PH = 800;
let TL, META, ANCH, FPS, H, BASE, LAYOUT;

// ------------------------------------------------------------------ helpers
const clamp = (x, a = 0, b = 1) => Math.max(a, Math.min(b, x));
const sm = (t, a, b) => { if (b <= a) return t >= a ? 1 : 0; const u = clamp((t - a) / (b - a)); return u * u * (3 - 2 * u); };
const eo = (u) => 1 - Math.pow(1 - clamp(u), 3);
const eio = (u) => { u = clamp(u); return u < 0.5 ? 4 * u * u * u : 1 - Math.pow(-2 * u + 2, 3) / 2; };
const back = (u) => { u = clamp(u); const c = 1.6; return 1 + (c + 1) * Math.pow(u - 1, 3) + c * Math.pow(u - 1, 2); };
const win = (t, a, b, fi = 0.3, fo = 0.3) => sm(t, a, a + fi) * (1 - sm(t, b - fo, b));
const lerp = (a, b, u) => a + (b - a) * u;
const hash = (n) => { const x = Math.sin(n * 127.1 + 311.7) * 43758.5453; return x - Math.floor(x); };

function el(tag, cls, parent, html) {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (html !== undefined) e.innerHTML = html;
  if (parent) parent.appendChild(e);
  return e;
}
const div = (cls, parent, html) => el('div', cls, parent, html);
function css(e, o) { for (const k in o) e.style[k] = o[k]; }
function svgEl(tag, parent, attrs = {}) {
  const e = document.createElementNS('http://www.w3.org/2000/svg', tag);
  for (const k in attrs) e.setAttribute(k, attrs[k]);
  parent.appendChild(e);
  return e;
}
function lineSvg(parent) {
  const s = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  s.setAttribute('class', 'lines');
  s.setAttribute('viewBox', `0 0 ${W} ${HGT}`);
  parent.appendChild(s);
  return s;
}

const SVGP = (d) => `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">${d}</svg>`;
const ICON = {
  speaker: SVGP('<path d="M5 12c0-3.3 3.1-5 7-5s7 1.7 7 5v4c0 1.7-3.1 3-7 3s-7-1.3-7-3z"/><ellipse cx="12" cy="10" rx="7" ry="2.6"/>'),
  mic: SVGP('<rect x="9" y="3" width="6" height="11" rx="3"/><path d="M5 11a7 7 0 0 0 14 0M12 18v3"/>'),
  wave: SVGP('<path d="M3 12h1M7 8v8M11 4v16M15 7v10M19 10v4M22 12h-1"/>'),
  text: SVGP('<path d="M4 6h16M4 12h10M4 18h13"/>'),
  brain: SVGP('<path d="M9 4a3 3 0 0 0-3 3 3 3 0 0 0-2 5 3 3 0 0 0 2 5 3 3 0 0 0 3 3 2 2 0 0 0 2-2V6a2 2 0 0 0-2-2zM15 4a3 3 0 0 1 3 3 3 3 0 0 1 2 5 3 3 0 0 1-2 5 3 3 0 0 1-3 3 2 2 0 0 1-2-2V6a2 2 0 0 1 2-2z"/>'),
  home: SVGP('<path d="M3 11l9-7 9 7v9a1 1 0 0 1-1 1h-5v-6h-6v6H4a1 1 0 0 1-1-1z"/>'),
  bulb: SVGP('<path d="M9 18h6M10 21h4M12 3a6 6 0 0 0-3.5 10.9c.6.5 1 1.2 1 2V17h5v-1.1c0-.8.4-1.5 1-2A6 6 0 0 0 12 3z"/>'),
  ac: SVGP('<rect x="2" y="5" width="20" height="8" rx="2"/><path d="M6 10h12M7 16l-1 3M12 16v3M17 16l1 3"/>'),
  curtain: SVGP('<path d="M3 3h18M5 3v18c2-4 3-10 4.5-18M19 3v18c-2-4-3-10-4.5-18"/>'),
  lamp: SVGP('<path d="M7 21h10M12 21v-8M8 3h8l3 8H5z"/>'),
  washer: SVGP('<rect x="4" y="2.5" width="16" height="19" rx="2"/><circle cx="12" cy="13" r="5"/><path d="M7 6h3"/>'),
  fridge: SVGP('<rect x="5" y="2.5" width="14" height="19" rx="2"/><path d="M5 10h14M8 6v2M8 13v3"/>'),
  vacuum: SVGP('<circle cx="12" cy="12" r="9"/><circle cx="12" cy="9" r="2.5"/>'),
  camera: SVGP('<rect x="3" y="6" width="13" height="12" rx="2"/><path d="M16 10l5-3v10l-5-3z"/>'),
  cloud: SVGP('<path d="M7 18a4 4 0 0 1-.5-8A6 6 0 0 1 18 9a4.5 4.5 0 0 1-.5 9z"/>'),
  shield: SVGP('<path d="M12 3l8 3v6c0 4.5-3.3 8-8 9-4.7-1-8-4.5-8-9V6z"/><path d="M9 12l2 2 4-4"/>'),
  bell: SVGP('<path d="M6 16v-5a6 6 0 0 1 12 0v5l2 2H4zM10 20a2 2 0 0 0 4 0"/>'),
  flame: SVGP('<path d="M12 3c1 4 5 5 5 10a5 5 0 0 1-10 0c0-2 1-3.5 2-4.5 0 2 1 3 2 3 0-3-1-5 1-8.5z"/>'),
  book: SVGP('<path d="M4 5a2 2 0 0 1 2-2h13v16H6a2 2 0 0 0-2 2zM4 21V5M8 7h7"/>'),
  memory: SVGP('<path d="M12 3a9 9 0 1 0 9 9"/><path d="M12 7v5l3 2M17 3h4v4"/>'),
  hermes: SVGP('<path d="M12 3l1.8 5.2L19 10l-5.2 1.8L12 17l-1.8-5.2L5 10l5.2-1.8z"/>'),
  ha: SVGP('<path d="M3 11l9-7 9 7"/><path d="M5 10v10h14V10"/><circle cx="12" cy="14" r="2"/><path d="M12 16v4M10.5 12.5L8 10M13.5 12.5L16 10"/>'),
  fast: SVGP('<path d="M4 6l7 6-7 6zM13 6l7 6-7 6z"/>'),
  lock: SVGP('<rect x="5" y="11" width="14" height="10" rx="2"/><path d="M8 11V8a4 4 0 0 1 8 0v3"/>'),
  code: SVGP('<path d="M8 6l-6 6 6 6M16 6l6 6-6 6M14 4l-4 16"/>'),
};

// ------------------------------------------------------------------ data access
const shotById = (id) => TL.shots.find((s) => s.id === id);
const lineOf = (shot, id) => shot.lines.find((l) => l.id === id);
function charTimes(lid) {
  const m = META[lid];
  const text = m.text;
  const times = new Array(text.length).fill(null);
  let cur = 0;
  for (const w of m.words) {
    const i = text.indexOf(w.text, cur);
    if (i < 0) continue;
    for (let k = 0; k < w.text.length; k++) times[i + k] = Math.max(0, w.t) + (k / w.text.length) * w.d;
    cur = i + w.text.length;
  }
  let last = 0;
  for (let i = 0; i < times.length; i++) { if (times[i] === null) times[i] = last; last = times[i]; }
  return times;
}

// ------------------------------------------------------------------ components

// A device tag: a pin on the 3D anchor, a leader line and a glass label.
function tag(parent, svg, o) {
  const pin = div('pin', parent);
  const ring = div('ring', pin);
  const c = div(`tag ${o.cls || ''}`, parent);
  const ico = div('ico', c, ICON[o.icon] || '');
  if (o.color) ico.style.color = o.color;
  const body = div(null, c);
  const main = div(null, body, o.text);
  const brand = o.brand !== undefined ? div('brand', body, o.brand) : null;
  const ok = o.state ? div(`ok ${o.warn ? 'warn' : ''}`, c, o.state) : null;
  const ln = svgEl('line', svg, { stroke: 'rgba(255,255,255,0.75)', 'stroke-width': 1.6 });
  return {
    main, brand,
    update(t, a, t0, t1 = 1e9, fixed = null) {
      const vis = fixed ? 1 : (a && a.ok ? 1 : 0);
      const k = eo((t - t0) / 0.45) * (1 - sm(t, t1 - 0.35, t1)) * vis;
      const ax = fixed ? fixed.x : a ? a.x : -999, ay = fixed ? fixed.y : a ? a.y : -999;
      const dx = o.dx ?? 70, dy = o.dy ?? -70;
      pin.style.display = fixed ? 'none' : 'block';
      pin.style.left = ax + 'px'; pin.style.top = ay + 'px';
      pin.style.opacity = k;
      const r = clamp((t - t0) / 0.9);
      ring.style.opacity = (1 - r);
      ring.style.transform = `scale(${1 + r * 1.8})`;
      const w = c.offsetWidth, hh = c.offsetHeight;
      let cx = fixed ? ax : ax + dx, cy = fixed ? ay : ay + dy - hh / 2;
      if (!fixed && dx < 0) cx -= w;
      cx = clamp(cx, 50, W - w - 50); cy = clamp(cy, BAR + 30, BAR + PH - hh - 30);
      const slide = (1 - eo((t - t0 - 0.05) / 0.5)) * (dx < 0 ? -24 : 24);
      c.style.left = cx + slide + 'px'; c.style.top = cy + 'px';
      c.style.opacity = k;
      const ex = dx < 0 ? cx + w : cx, ey = cy + hh / 2;
      const lu = eo((t - t0) / 0.35);
      ln.setAttribute('x1', ax); ln.setAttribute('y1', ay);
      ln.setAttribute('x2', lerp(ax, ex, lu)); ln.setAttribute('y2', lerp(ay, ey, lu));
      ln.setAttribute('opacity', fixed ? 0 : k * 0.8);
      if (ok) ok.style.transform = `scale(${back((t - t0 - 0.3) / 0.35)})`;
    },
  };
}

function topTitle(parent, kicker, html) {
  const e = div('toptitle', parent, `<span class="k">${kicker}</span>${html}`);
  const f = (t, t0, t1 = 1e9) => {
    const a = eo((t - t0) / 0.6) * (1 - sm(t, t1 - 0.4, t1));
    e.style.opacity = a;
    e.style.transform = `translateY(${(1 - a) * 18}px)`;
    e.style.filter = `blur(${(1 - a) * 6}px)`;
  };
  f.el = e;
  return f;
}

function corner(parent, html) {
  const e = div('corner', parent, html);
  const f = (t, t0, t1 = 1e9) => { e.style.opacity = win(t, t0, t1, 0.4, 0.4); };
  f.el = e;
  return f;
}

function painCard(parent, num, title, subtitle) {
  const scrim = div('layer', parent);
  scrim.style.background = 'linear-gradient(90deg, rgba(0,8,20,0.75), rgba(0,8,20,0.35) 45%, rgba(0,0,0,0) 70%)';
  const p = div('pain', parent);
  const n = div('num', p, num);
  const tt = div('ttl', p, title);
  const s = div('s', p, subtitle);
  const r = div('pline', p);
  return (t, t0, t1 = 1e9) => {
    const a = (1 - sm(t, t1 - 0.4, t1));
    scrim.style.opacity = sm(t, t0 - 0.1, t0 + 0.4) * a;
    const k = eo((t - t0) / 0.5);
    n.style.opacity = k * a; n.style.transform = `translateX(${(1 - k) * -40}px)`;
    const k2 = eo((t - t0 - 0.12) / 0.5);
    tt.style.opacity = k2 * a; tt.style.transform = `translateX(${(1 - k2) * -40}px)`;
    const k3 = eo((t - t0 - 0.3) / 0.5);
    s.style.opacity = k3 * a;
    r.style.width = 380 * eo((t - t0 - 0.2) / 0.7) + 'px';
    r.style.opacity = a;
    // a short glitch on entry
    const gl = t > t0 && t < t0 + 0.25 ? Math.sin(t * 140) * 6 : 0;
    p.style.transform = `translateX(${gl}px)`;
  };
}

function hud(parent, meta) {
  const h = div('hud', parent);
  for (const c of ['tl', 'tr', 'bl', 'br']) div(`cn ${c}`, h);
  const m = div('meta', h, meta);
  const rec = div('rec', h, '<i></i>REC');
  const scan = div('scan', h);
  return (t, on) => {
    h.style.opacity = on;
    rec.querySelector('i').style.opacity = Math.sin(t * 6) > 0 ? 1 : 0.15;
    scan.style.top = ((t * 0.35) % 1) * 720 + 'px';
    m.dataset.t = t;
  };
}

function detBox(parent, label) {
  const b = div('det', parent);
  const lb = div('lb', b, label);
  return {
    lb,
    update(t, t0, rect, t1 = 1e9) {
      const a = eo((t - t0) / 0.3) * (1 - sm(t, t1 - 0.2, t1));
      if (!rect) { b.style.opacity = 0; return; }
      const grow = 1 + 0.25 * (1 - eo((t - t0) / 0.35));
      const cx = (rect.x0 + rect.x1) / 2, cy = (rect.y0 + rect.y1) / 2;
      const w = (rect.x1 - rect.x0) * grow, hh = (rect.y1 - rect.y0) * grow;
      css(b, { left: cx - w / 2 + 'px', top: cy - hh / 2 + 'px', width: w + 'px', height: hh + 'px', opacity: a });
      lb.style.opacity = sm(t, t0 + 0.25, t0 + 0.45);
    },
  };
}

function rectOf(A, names, pad = 16) {
  const pts = names.map((n) => A(n)).filter((p) => p && p.z > 0);
  if (pts.length < names.length) return null;
  const xs = pts.map((p) => p.x), ys = pts.map((p) => p.y);
  return { x0: Math.min(...xs) - pad, x1: Math.max(...xs) + pad, y0: Math.min(...ys) - pad, y1: Math.max(...ys) + pad };
}

function sizedRect(a, metres, aspect = 1) {
  if (!a || a.z <= 0) return null;
  const px = metres * (a.lens / 36) * W / a.z;
  return { x0: a.x - px / 2, x1: a.x + px / 2, y0: a.y - px * aspect / 2, y1: a.y + px * aspect / 2 };
}

// ------------------------------------------------------------------ shots
const SHOTS = {};
const MARK = (shot, name) => shot.marks[name];

// S02: the home wakes up -- small brand tags as each device answers.
SHOTS.S02 = {
  build(root, shot) {
    const svg = lineSvg(root);
    const m = shot.marks;
    const tags = [
      [tag(root, svg, { icon: 'bulb', text: '客厅灯', brand: '米家', state: '✓', dx: 60, dy: -90, color: '#ffcf8a' }), 'pendant', m.pendant],
      [tag(root, svg, { icon: 'lamp', text: '落地灯', brand: '米家', state: '✓', dx: -60, dy: -60, color: '#ffcf8a' }), 'floorlamp', m.floor],
      [tag(root, svg, { icon: 'ac', text: '空调 26°C', brand: '海尔', state: '✓', dx: 70, dy: 60, color: '#9cc8ff' }), 'ac_living', m.ac],
      [tag(root, svg, { icon: 'curtain', text: '窗帘', brand: '其他品牌', state: '✓', dx: -70, dy: 90, color: '#ffb6c8' }), 'curtain', m.curtain],
    ];
    return (t, ctx) => {
      for (const [tg, a, t0] of tags) tg.update(t, ctx.A(a), t0 + 0.05, shot.frames / FPS + 0.2);
    };
  },
};

// S03: the title over the crane-out.
SHOTS.S03 = {
  build(root, shot) {
    const scrim = div('layer', root);
    scrim.style.background = 'radial-gradient(ellipse 60% 42% at 50% 22%, rgba(0,0,0,0.62), rgba(0,0,0,0) 100%)';
    const tm = div('title-main', root, '家的大脑');
    const ln = div('title-line', root);
    const ts = div('title-sub', root, '如何 DIY 一个全网最智能的 AI 家庭管家');
    const t0 = MARK(shot, 'title');
    const end = shot.frames / FPS;
    return (t) => {
      const out = 1 - sm(t, end - 0.5, end + 0.2);
      const a = eo((t - t0) / 1.2);
      scrim.style.opacity = sm(t, t0 - 0.3, t0 + 0.6) * out;
      tm.style.opacity = a * out;
      tm.style.letterSpacing = lerp(60, 34, eo((t - t0) / 2.5)) + 'px';
      tm.style.filter = `blur(${(1 - a) * 14}px)`;
      // a slow light sweep through the letters
      const sw = clamp((t - t0 - 0.4) / 2.2);
      tm.style.backgroundImage = `linear-gradient(100deg, #fff ${sw * 140 - 40}%, #ffd2aa ${sw * 140 - 20}%, #fff ${sw * 140}%, #ffe6cf 100%)`;
      ln.style.opacity = sm(t, t0 + 0.5, t0 + 1.2) * out;
      ln.style.transform = `scaleX(${eo((t - t0 - 0.5) / 1.2)})`;
      ts.style.opacity = sm(t, t0 + 0.8, t0 + 1.6) * out;
      ts.style.letterSpacing = lerp(16, 10, eo((t - t0 - 0.8) / 2)) + 'px';
    };
  },
};

// S04: pain 1.
SHOTS.S04 = {
  plateFilter: (t, shot) => {
    const f = shot.marks.fail;
    const g = t > f && t < f + 0.35 ? 1 : 0;
    return g ? `contrast(1.2) hue-rotate(${Math.sin(t * 90) * 25}deg)` : 'none';
  },
  plateShift: (t, shot) => { const f = shot.marks.fail; return t > f && t < f + 0.35 ? Math.sin(t * 110) * 14 * (1 - (t - f) / 0.35) : 0; },
  build(root, shot) {
    const card = painCard(root, '01', '不够聪明', '只认命令，听不懂意思');
    return (t) => card(t, MARK(shot, 'card'), shot.frames / FPS + 0.3);
  },
};

// S05: devices trapped in their own apps; links between them break.
const BRANDS = {
  mi: { name: '米家', color: 'var(--mi)', raw: '#ff8a3d' },
  haier: { name: '海尔智家', color: 'var(--haier)', raw: '#3d9bff' },
  bx: { name: '品牌 X', color: 'var(--bx)', raw: '#3ccf8e' },
  by: { name: '品牌 Y', color: 'var(--by)', raw: '#c77dff' },
};
const SILOS = [
  ['pendant', 'mi', 1.0], ['floorlamp', 'mi', 0.85], ['vacuum', 'mi', 0.8], ['kid_light', 'mi', 0.9],
  ['ac_living', 'haier', 0.95], ['washer', 'haier', 0.95], ['fridge', 'haier', 0.95],
  ['curtain', 'bx', 1.0], ['desklamp', 'by', 0.8], ['kitcam', 'by', 0.8], ['sp', 'bx', 0.75],
];
SHOTS.S05 = {
  build(root, shot) {
    const svg = lineSvg(root);
    const links = [];
    const pairs = [[0, 4], [4, 7], [1, 8], [5, 9], [2, 6], [7, 10], [3, 8]];
    for (const [a, b] of pairs) {
      links.push({ a, b, l: svgEl('line', svg, { stroke: '#ff6b6b', 'stroke-width': 2, 'stroke-dasharray': '10 8' }),
        x: svgEl('text', svg, { fill: '#ff6b6b', 'font-size': 30, 'font-weight': 700, 'text-anchor': 'middle' }) });
      links[links.length - 1].x.textContent = '×';
    }
    const silos = SILOS.map(([name, br, s], i) => {
      const e = div('silo', root);
      const B = BRANDS[br];
      css(e, { borderColor: B.raw, background: `radial-gradient(circle, ${B.raw}22, ${B.raw}08 70%)`, boxShadow: `0 0 30px ${B.raw}55` });
      const nm = div('nm', e, B.name + ' App');
      nm.style.background = B.raw;
      return { e, name, s, i };
    });
    const legend = div('legend', root);
    for (const k of ['mi', 'haier', 'bx', 'by']) {
      const r = div('app', legend, `<i style="background:${BRANDS[k].raw}">${BRANDS[k].name[0]}</i>${BRANDS[k].name}`);
      r.style.opacity = 0;
    }
    const card = painCard(root, '02', '各自为政', '一个品牌，一个 App，谁也不认识谁');
    const t0 = MARK(shot, 'silos');
    return (t, ctx) => {
      silos.forEach((s) => {
        const a = ctx.A(s.name);
        const k = back((t - t0 - 0.12 * s.i) / 0.45);
        const r = 60 * s.s * clamp(k, 0, 1.3);
        const ok = a && a.ok;
        css(s.e, { left: (ok ? a.x : -999) - r + 'px', top: (ok ? a.y : -999) - r + 'px', width: 2 * r + 'px', height: 2 * r + 'px',
          opacity: ok ? sm(t, t0 + 0.12 * s.i, t0 + 0.12 * s.i + 0.2) * (1 - sm(t, MARK(shot, 'card') - 0.2, MARK(shot, 'card') + 0.3) * 0.5) : 0 });
      });
      links.forEach((L, j) => {
        const a = ctx.A(SILOS[L.a][0]), b = ctx.A(SILOS[L.b][0]);
        if (!a || !b || !a.ok || !b.ok) { L.l.setAttribute('opacity', 0); L.x.setAttribute('opacity', 0); return; }
        const tj = t0 + 1.3 + 0.18 * j;
        const grow = eo((t - tj) / 0.4);
        const broken = sm(t, tj + 0.6, tj + 0.75);
        const mx = (a.x + b.x) / 2, my = (a.y + b.y) / 2;
        const gap = 26 * broken;
        const ux = (b.x - a.x), uy = (b.y - a.y), L2 = Math.hypot(ux, uy) || 1;
        // draw as one line with a gap in the middle (dash offset trick: two segments via path would be neater;
        // a single segment is shortened from both ends towards the break instead)
        L.l.setAttribute('x1', a.x); L.l.setAttribute('y1', a.y);
        L.l.setAttribute('x2', lerp(a.x, mx - ux / L2 * gap, grow)); L.l.setAttribute('y2', lerp(a.y, my - uy / L2 * gap, grow));
        L.l.setAttribute('opacity', sm(t, tj, tj + 0.2) * (0.5 + 0.5 * (1 - broken)) * (1 - sm(t, MARK(shot, 'card'), MARK(shot, 'card') + 0.4)));
        L.x.setAttribute('x', mx); L.x.setAttribute('y', my + 10);
        L.x.setAttribute('opacity', broken * (1 - sm(t, MARK(shot, 'card'), MARK(shot, 'card') + 0.4)));
      });
      [...legend.children].forEach((r, i) => {
        const k = eo((t - t0 - 0.5 - 0.15 * i) / 0.4);
        r.style.opacity = k * (1 - sm(t, MARK(shot, 'card') - 0.2, MARK(shot, 'card') + 0.2));
        r.style.transform = `translateX(${(1 - k) * 30}px)`;
      });
      card(t, MARK(shot, 'card'), shot.frames / FPS + 0.3);
    };
  },
};

// S06: what you say floats up into the cloud.
const FRAGS = ['“几点睡觉”', '“下周出差，家里没人”', '“孩子几点放学”', '“我有点冷”', '门锁 · 22:41 开',
  '卧室 · 有人', '“记住我的生日”', '“空调开 26 度”', '“孩子在写作业”', '“明早七点叫我”', '客厅 · 无人', '“医生说要少吃盐”'];
SHOTS.S06 = {
  build(root, shot) {
    const frags = FRAGS.map((txt, k) => {
      const e = div('frag', root, (k % 3 === 1 ? '<span class="rec"></span>' : '') + txt);
      return { e, k };
    });
    const card = painCard(root, '03', '没有秘密', '声音和习惯，都交给了云端');
    const rise = MARK(shot, 'rise');
    return (t, ctx) => {
      for (const f of frags) {
        const a = ctx.A(`frag${f.k}`);
        const head = ctx.flags[`frag${f.k}`] || 0;
        const vis = a && a.ok && head > 0.05 && head < 1.05 && t > rise + 0.3;
        f.e.style.opacity = vis ? sm(head, 0.05, 0.2) * (1 - sm(head, 0.75, 1.0)) * 0.95 : 0;
        if (vis) { f.e.style.left = a.x + 'px'; f.e.style.top = a.y + 'px'; }
      }
      card(t, MARK(shot, 'card'), shot.frames / FPS + 0.3);
    };
  },
};

// S07: three words slam, then collapse into a point of light.
SHOTS.S07 = {
  plateFilter: (t) => `brightness(${0.35}) blur(6px) saturate(0.4)`,
  build(root, shot) {
    const words = ['不够聪明', '各自为政', '没有秘密'].map((w, i) => {
      const e = div('slam', root, w);
      e.style.left = [250, 760, 1270][i] + 'px';
      return e;
    });
    const pt = div('point', root);
    const m = shot.marks;
    return (t) => {
      const col = sm(t, m.collapse - 0.35, m.collapse);
      words.forEach((e, i) => {
        const t0 = m[`w${i + 1}`];
        const k = clamp((t - t0) / 0.18);
        const sc = lerp(1.8, 1, eo(k));
        const cx = 960 - ([250, 760, 1270][i] + 200);
        e.style.opacity = sm(t, t0, t0 + 0.08) * (1 - col);
        e.style.transform = `translateX(${cx * col}px) scale(${sc * (1 - 0.9 * col)})`;
        e.style.filter = `blur(${(1 - k) * 8 + col * 6}px)`;
      });
      pt.style.opacity = sm(t, m.collapse - 0.15, m.collapse);
      pt.style.transform = `scale(${0.3 + 1.2 * sm(t, m.collapse - 0.1, m.collapse + 0.1)})`;
    };
  },
};

// S08: the turn -- the point becomes the spark, the claim lands.
SHOTS.S08 = {
  build(root, shot) {
    const pt = div('point', root);
    const c = div('claim', root, '家的大脑，就住在家里');
    css(c, { top: '168px', fontSize: '66px' });
    const t0 = MARK(shot, 'title');
    return (t) => {
      pt.style.opacity = 1 - sm(t, 0.05, 0.4);
      pt.style.transform = `scale(${1 + 6 * sm(t, 0, 0.35)})`;
      const a = eo((t - t0) / 0.9);
      c.style.opacity = a;
      c.style.letterSpacing = lerp(30, 16, eo((t - t0) / 2)) + 'px';
      c.style.filter = `blur(${(1 - a) * 10}px)`;
    };
  },
};

// S09: ① and ② over the two heroes.
SHOTS.S09 = {
  build(root, shot) {
    const b1 = div('num-badge', root, '1');
    const b2 = div('num-badge', root, '2');
    const k = div('toptitle', root, '<span class="k">DIY 配方</span>只需要<span class="g">两样东西</span>');
    return (t, ctx) => {
      const a = ctx.A('st_sp'), b = ctx.A('st_pc');
      for (const [e, p, t0] of [[b1, a, MARK(shot, 'light_l') + 0.3], [b2, b, MARK(shot, 'light_r') + 0.3]]) {
        const v = p && p.ok;
        e.style.left = (v ? p.x : -99) + 'px'; e.style.top = (v ? p.y - 120 : -99) + 'px';
        e.style.opacity = eo((t - t0) / 0.4);
        e.style.transform = `scale(${back((t - t0) / 0.45)})`;
      }
      const kk = eo((t - 1.6) / 0.6);
      k.style.opacity = kk; k.style.transform = `translateY(${(1 - kk) * 16}px)`;
    };
  },
};

function bigLabel(parent, n, h, d, chips, pos) {
  const scrim = div('layer', parent);
  scrim.style.background = 'linear-gradient(90deg, rgba(0,0,0,0.6), rgba(0,0,0,0) 45%)';
  const e = div('big-label', parent,
    `<div class="n">${n}</div><div class="h">${h}</div><div class="d">${d}</div>` +
    (chips ? `<div class="chips">${chips.map((c) => `<span>${c}</span>`).join('')}</div>` : ''));
  css(e, pos);
  const parts = [...e.children];
  return (t, t0, t1 = 1e9) => {
    const out = 1 - sm(t, t1 - 0.4, t1);
    scrim.style.opacity = sm(t, t0 - 0.2, t0 + 0.4) * out;
    parts.forEach((p, i) => {
      const k = eo((t - t0 - 0.12 * i) / 0.55);
      p.style.opacity = k * out;
      p.style.transform = `translateY(${(1 - k) * 20}px)`;
    });
  };
}

SHOTS.S10 = {
  build(root, shot) {
    const L = bigLabel(root, '①', '一台带麦克风的音箱', '家的耳朵和嘴巴', ['蓝牙音箱', 'USB 麦克风', '刷机的小爱音箱'],
      { left: '110px', top: '420px' });
    return (t) => L(t, 0.4, shot.frames / FPS + 0.3);
  },
};

SHOTS.S11 = {
  build(root, shot) {
    const L = bigLabel(root, '②', '一台常开的 mini PC', '家的大脑', ['放在家里', '24 小时在线'],
      { left: '110px', top: '420px' });
    return (t) => L(t, 0.5, shot.frames / FPS + 0.2);
  },
};

const LAYERS = [
  { h: '唤醒 · 你好小七', d: 'sherpa-onnx 关键词唤醒', loc: '本地', c: '#ffb36b', icon: 'mic' },
  { h: '语音识别 · SenseVoice', d: '说完约 0.2 秒出文字', loc: '本地', c: '#ff6f8e', icon: 'wave' },
  { h: 'Hermes 智能体', d: '理解 · 记忆 · 技能 · 定时', loc: '本地运行', c: '#9b7bff', icon: 'hermes' },
  { h: 'Home Assistant', d: '米家 · 海尔 · 更多品牌', loc: '本地', c: '#4cb6ff', icon: 'ha' },
];
SHOTS.S12 = {
  build(root, shot) {
    const svg = lineSvg(root);
    const tags = LAYERS.map((L, k) => {
      const e = div('layer-tag', root,
        `<div class="tag" style="position:relative"><div class="ico" style="color:${L.c}">${ICON[L.icon]}</div>` +
        `<div><div class="h">${L.h}</div><div class="d">${L.d}</div></div>` +
        `<div class="loc" style="color:${L.c};border-color:${L.c}">${L.loc}</div></div>`);
      const ln = svgEl('polyline', svg, { fill: 'none', stroke: L.c, 'stroke-width': 1.6, opacity: 0 });
      return { e, ln, k };
    });
    const api = div('layer-tag', root,
      `<div class="tag" style="position:relative"><div class="ico" style="color:#dfe9ff">${ICON.cloud}</div>` +
      `<div><div class="h">大模型 API</div><div class="d">DeepSeek 等，只收到文字</div></div></div>`);
    const open = corner(root, '<b>全部开源</b> · github.com/OwnDing/open-xiaoai');
    css(open.el, { top: '872px', right: 'auto', left: '70px' });
    const m = shot.marks;
    const times = [m.l1, m.l2, m.l3, m.l4];
    return (t, ctx) => {
      tags.forEach(({ e, ln, k }) => {
        const a = ctx.A(`layer${k}_r`);
        const t0 = times[k] + 0.35;
        const v = a && a.ok;
        const kk = eo((t - t0) / 0.45);
        const lx = 1180, ly = 700 - k * 125;
        e.style.left = lx + 'px'; e.style.top = ly - 40 + 'px';
        e.style.opacity = v ? kk : 0;
        e.style.transform = `translateX(${(1 - kk) * 30}px)`;
        if (v) {
          const u = eo((t - t0) / 0.35);
          const mx = lerp(a.x, lx - 40, 0.55);
          ln.setAttribute('points', `${a.x},${a.y} ${lerp(a.x, mx, u)},${lerp(a.y, ly, u)} ${lerp(a.x, lx - 8, u)},${lerp(a.y, ly, u)}`);
          ln.setAttribute('opacity', 0.85 * kk);
        } else ln.setAttribute('opacity', 0);
      });
      const ka = eo((t - m.api - 0.4) / 0.5);
      css(api, { left: '1180px', top: '190px', opacity: ka, transform: `translateY(${(1 - ka) * -16}px)` });
      open(t, 1.2);
    };
  },
};

// S13: the journey of one sentence -- what stays home and what leaves.
SHOTS.S13 = {
  plateFilter: () => 'blur(7px) brightness(0.42) saturate(0.85)',
  build(root, shot) {
    const m = shot.marks;
    const cv = el('canvas', null, root);
    cv.width = W; cv.height = HGT;
    css(cv, { position: 'absolute', left: 0, top: 0 });
    const ctx2 = cv.getContext('2d');
    const zl = div('ex-zone', root); css(zl, { left: '70px', top: '190px', width: '1120px', height: '700px',
      background: 'linear-gradient(160deg, rgba(255,170,100,0.10), rgba(255,120,140,0.04))', border: '1px solid rgba(255,190,140,0.28)' });
    const zr = div('ex-zone', root); css(zr, { left: '1310px', top: '190px', width: '540px', height: '700px',
      background: 'linear-gradient(160deg, rgba(120,170,255,0.08), rgba(80,120,200,0.03))', border: '1px solid rgba(156,200,255,0.22)' });
    const hl = div('ex-head', root, '家里 · 你的 mini PC'); css(hl, { left: '110px', top: '214px' });
    const hr = div('ex-head', root, '云端'); css(hr, { left: '1350px', top: '214px' });
    const wl = div('ex-wall-label', root, '家的边界'); css(wl, { left: '1262px', top: '470px' });
    const node = (x, y, icon, l, s, ok, color) => {
      const n = div('ex-node', root, `<div class="c" style="color:${color}">${ICON[icon]}</div><div class="l">${l}</div><div class="s">${s}</div>` + (ok ? '<div class="ok">✓</div>' : ''));
      css(n, { left: x + 'px', top: y - 48 + 'px' });
      return n;
    };
    const nSp = node(200, 400, 'speaker', '音箱', '你说的话', false, '#ffcf9a');
    const nWake = node(430, 400, 'mic', '唤醒', '本地', true, '#ffb36b');
    const nAsr = node(660, 400, 'wave', '语音识别', '本地 · 约 0.2 秒', true, '#ff6f8e');
    const nApi = node(1580, 400, 'cloud', '大模型 API', '只收到文字', false, '#cfe0ff');
    const nHa = node(980, 680, 'ha', 'Home Assistant', '本地', true, '#4cb6ff');
    const devs = [['ac', '空调', 760], ['bulb', '灯', 610], ['curtain', '窗帘', 460]].map(([ic, l, x]) => node(x, 680, ic, l, '', true, '#ffd8a8'));
    const pill = div('ex-pill', root); css(pill, { left: '830px', top: '372px' });
    const text = '我有点冷，还有点困';
    const chars = [...text].map((c) => el('span', null, pill, c));
    const fly = div('ex-pill', root, text);
    const reply = div('ex-pill reply', root, '空调 26°C · 22:30 提醒');
    const note = div('ex-note', root, '声音 · 不出家门'); css(note, { left: '890px', top: '500px', color: '#ffb36b', border: '1px solid rgba(255,179,107,0.6)' });
    const pop = (e, t0, t) => { const k = back((t - t0) / 0.45); e.style.opacity = sm(t, t0, t0 + 0.15); e.style.transform = `scale(${Math.max(0, k)})`; };
    return (t) => {
      const fin = 1 - sm(t, shot.frames / FPS - 0.3, shot.frames / FPS + 0.3);
      root.style.opacity = sm(t, 0.0, 0.5) * fin;
      const zk = eo(t / 0.7);
      zl.style.opacity = zk; zr.style.opacity = zk; hl.style.opacity = sm(t, 0.3, 0.8); hr.style.opacity = sm(t, 0.3, 0.8);
      wl.style.opacity = sm(t, m.wall - 0.2, m.wall + 0.3) * 0.5 + 0.5 * sm(t, 0.4, 1.0);
      pop(nSp, m.wave, t); pop(nWake, m.wake, t); pop(nAsr, m.asr, t);
      for (const n of [nWake, nAsr]) { const ok = n.querySelector('.ok'); ok.style.transform = `scale(${back((t - (n === nWake ? m.wake : m.asr) - 0.35) / 0.35)})`; }
      pop(nApi, m.api, t); pop(nHa, m.reply + 0.55, t);
      devs.forEach((d, i) => { pop(d, m.devices + 0.15 * i, t); d.querySelector('.ok').style.transform = `scale(${back((t - m.devices - 0.15 * i - 0.3) / 0.35)})`; });
      // The sentence crystallises out of the waveform.
      const tt = m.text;
      pill.style.opacity = sm(t, tt - 0.1, tt + 0.1);
      chars.forEach((c, i) => { const u = sm(t, tt + i * 0.07, tt + i * 0.07 + 0.2); c.style.opacity = u; c.style.filter = `blur(${(1 - u) * 6}px)`; });
      // It crosses the boundary alone.
      const sp = clamp((t - m.send) / 1.1);
      fly.style.opacity = t > m.send ? 1 : 0;
      const fx = lerp(830, 1440, eio(sp)), fy = lerp(372, 262, eio(sp)) - 50 * Math.sin(Math.PI * sp);
      css(fly, { left: fx + 'px', top: fy + 'px', transform: `scale(${1 - 0.15 * eio(sp)})`, transformOrigin: '0 50%' });
      // Reply returns to Home Assistant.
      const rp = clamp((t - m.reply) / 1.0);
      reply.style.opacity = t > m.reply ? (1 - sm(rp, 0.88, 1.0)) : 0;
      css(reply, { left: lerp(1460, 1000, eio(rp)) + 'px', top: lerp(420, 640, eio(rp)) + 'px' });
      note.style.opacity = sm(t, m.wall + 0.1, m.wall + 0.5);
      // Canvas: boundary line, wave particles that cannot leave, link lines.
      ctx2.clearRect(0, 0, W, HGT);
      const bx = 1250;
      const bk = eo(t / 1.0);
      const g = ctx2.createLinearGradient(0, 190, 0, 890);
      g.addColorStop(0, 'rgba(255,179,107,0)'); g.addColorStop(0.5, 'rgba(255,179,107,0.95)'); g.addColorStop(1, 'rgba(255,179,107,0)');
      ctx2.strokeStyle = g; ctx2.lineWidth = 3 + 3 * sm(t, m.wall, m.wall + 0.3) * (1 - sm(t, m.wall + 1.5, m.wall + 2.5));
      ctx2.shadowColor = 'rgba(255,170,90,0.9)'; ctx2.shadowBlur = 24;
      ctx2.beginPath(); ctx2.moveTo(bx, 540 - 350 * bk); ctx2.lineTo(bx, 540 + 350 * bk); ctx2.stroke();
      ctx2.shadowBlur = 0;
      // links between nodes
      ctx2.strokeStyle = 'rgba(255,255,255,0.25)'; ctx2.lineWidth = 2; ctx2.setLineDash([6, 8]);
      const seg = (x0, y0, x1, y1, t0) => { const u = eo((t - t0) / 0.5); if (u <= 0) return; ctx2.beginPath(); ctx2.moveTo(x0, y0); ctx2.lineTo(lerp(x0, x1, u), lerp(y0, y1, u)); ctx2.stroke(); };
      seg(260, 400, 370, 400, m.wake); seg(490, 400, 600, 400, m.asr); seg(720, 400, 820, 400, m.text);
      seg(1040, 640, 1480, 450, m.reply + 0.3);
      seg(920, 680, 830, 680, m.devices); seg(700, 680, 680, 680, m.devices);
      ctx2.setLineDash([]);
      // voice particles: stream from the speaker; after the wall cue some race right and stop dead at it.
      for (let i = 0; i < 90; i++) {
        const born = m.wave + (i / 90) * (m.text - m.wave + 1.6);
        const age = t - born;
        if (age < 0 || age > 2.4) continue;
        const toWall = born > m.wall - 1.2 && i % 3 === 0;
        const ph = hash(i);
        let x, y, a = 1;
        if (!toWall) {
          const u = clamp(age / 1.6);
          x = lerp(250, 840, u); y = 400 + Math.sin(u * 14 + ph * 6) * 28 * (1 - u) + (ph - 0.5) * 20;
          a = (1 - sm(u, 0.85, 1));
          if (t > m.text + 0.4) a *= 0;
        } else {
          const u = clamp(age / 1.1);
          x = Math.min(lerp(760, bx - 6, eo(u)), bx - 6); y = 420 + (ph - 0.5) * 300;
          a = 1 - sm(age, 1.1, 1.8);
        }
        const r = 2 + 2.5 * hash(i + 7);
        ctx2.fillStyle = `rgba(255,${150 + 60 * ph | 0},${110 + 60 * ph | 0},${0.85 * a})`;
        ctx2.beginPath(); ctx2.arc(x, y, r, 0, Math.PI * 2); ctx2.fill();
        if (toWall && x >= bx - 7 && a > 0) {   // a little splash on the wall
          ctx2.strokeStyle = `rgba(255,190,130,${0.6 * a})`; ctx2.lineWidth = 1.5;
          ctx2.beginPath(); ctx2.arc(bx, y, 6 + 14 * sm(age, 1.0, 1.6), Math.PI * 0.5, Math.PI * 1.5); ctx2.stroke();
        }
      }
    };
  },
};

// S14: the same sentence, understood.
SHOTS.S14 = {
  build(root, shot) {
    const svg = lineSvg(root);
    const title = topTitle(root, '同一句话', '<span class="g">听得懂意思</span>，不只是命令');
    const ac = tag(root, svg, { icon: 'ac', text: '空调 26°C', brand: '海尔 · 客厅', state: '✓', dx: -90, dy: 90, color: '#9cc8ff', cls: 'big' });
    const rm = tag(root, svg, { icon: 'bell', text: '22:30 睡前提醒', brand: '已安排', state: '✓', color: '#ffcf8a', cls: 'big' });
    const m = shot.marks;
    return (t, ctx) => {
      title(t, 0.3, m.ac - 0.4);
      ac.update(t, ctx.A('ac_living'), m.ac + 0.15, shot.frames / FPS + 0.3);
      rm.update(t, null, m.remind, shot.frames / FPS + 0.3, { x: 110, y: 760 });
    };
  },
};

// S15: the washer (another brand) reports through the speaker.
SHOTS.S15 = {
  build(root, shot) {
    const svg = lineSvg(root);
    const m = shot.marks;
    const w = tag(root, svg, { icon: 'washer', text: '洗衣机 · 洗涤中', brand: '海尔 · 剩余 42 分钟', dx: 260, dy: 60, color: '#4cb6ff', cls: 'big' });
    const sayTag = tag(root, svg, { icon: 'speaker', text: '小七播报', brand: '客厅音箱', state: '✓', color: '#ffb36b', cls: 'big' });
    const lapse = div('corner', root, '');
    css(lapse, { right: '70px', top: '190px', fontSize: '28px', padding: '10px 22px' });
    const title = topTitle(root, '海尔洗衣机 × 小七', '<span class="g">不同品牌</span>，一起联动');
    css(title.el, { left: 'auto', right: '110px', top: '742px', textAlign: 'right' });
    return (t, ctx) => {
      const lp = clamp((t - m.lapse) / (m.done - m.lapse));
      const mins = t < m.lapse ? 42 : Math.max(0, Math.round(42 * (1 - lp)));
      w.main.textContent = t >= m.done ? '洗衣机 · 洗涤完成' : '洗衣机 · 洗涤中';
      w.brand.textContent = t >= m.done ? '海尔 · 刚刚' : `海尔 · 剩余 ${mins} 分钟`;
      w.update(t, ctx.A('washer'), 0.3, shot.frames / FPS + 0.3);
      const on = win(t, m.lapse, m.done + 0.3, 0.2, 0.3);
      lapse.innerHTML = `<span style="display:inline-block;width:24px;height:24px;vertical-align:-4px;margin-right:10px;color:#ffb36b">${ICON.fast}</span>${Math.round(lp * 42)} 分钟后`;
      lapse.style.opacity = on;
      sayTag.update(t, null, m.arrive, shot.frames / FPS + 0.3, { x: 110, y: 760 });
      title(t, m.done + 0.2, shot.frames / FPS + 0.3);
    };
  },
};

// S16: three days ago -- a rule taught in one sentence.
SHOTS.S16 = {
  build(root, shot) {
    const svg = lineSvg(root);
    const m = shot.marks;
    const tc = div('timecard', root, '<div class="t">三天前</div><div class="s">周日 · 下午 3:20</div>');
    const card = div('rule', root,
      '<div class="k">新规则 · 场景</div><div class="q">“我回来了”</div><div class="arrow">→ 自动执行</div>' +
      '<div class="acts"><span>开灯</span><span>空调 26°C</span></div>');
    const saved = tag(root, svg, { icon: 'memory', text: '规则已保存', brand: '下次说“我回来了”就执行', state: '✓', dx: 80, dy: -110, color: '#ffb36b' });
    const title = topTitle(root, '不用 App · 不写自动化', '一句话，<span class="g">教会它家里的规矩</span>');
    title.el.style.left = 'auto'; title.el.style.right = '110px'; title.el.style.textAlign = 'right';
    const arrive = m.fly + 1.3;
    return (t, ctx) => {
      const k = eo((t - m.card) / 0.5) * (1 - sm(t, m.card + 2.6, m.card + 3.1));
      tc.style.opacity = k;
      tc.style.transform = `translateY(${(1 - k) * 14}px)`;
      // The card forms over the speaker, then shrinks and rides the thread into the mini PC.
      const sp = ctx.A('sp');
      const fl = ctx.A('flyer');
      const ka = eo((t - m.rule) / 0.6);
      const f = clamp((t - m.fly) / 1.3);
      let x = 1150, y = 260, s = 1;
      if (sp && sp.ok) { x = clamp(sp.x - 200, 60, 1400); y = clamp(sp.y - 330, 170, 600); }
      if (t > m.fly && fl && fl.z > 0) {
        const fx = clamp(fl.x, 40, W - 40), fy = clamp(fl.y, BAR + 30, BAR + PH - 30);
        x = lerp(x, fx, eio(f)); y = lerp(y, fy, eio(f)); s = lerp(1, 0.05, eio(f));
      }
      css(card, { left: x + 'px', top: y + 'px', opacity: ka * (1 - sm(f, 0.85, 1)), transform: `scale(${s * (0.92 + 0.08 * ka)})` });
      saved.update(t, ctx.A('pc'), arrive, shot.frames / FPS + 0.3);
      title(t, Math.max(m.app, m.fly + 1.5), shot.frames / FPS + 0.3);
    };
  },
};

// S17: the kitchen camera sees the fire.
SHOTS.S17 = {
  plateFilter: (t, shot, flags) => (flags.pov ? 'grayscale(0.55) contrast(1.25) brightness(1.15) sepia(0.2) hue-rotate(140deg) saturate(1.4)' : 'none'),
  build(root, shot) {
    const svg = lineSvg(root);
    const m = shot.marks;
    const pov = div('layer', root); css(pov, { top: BAR + 'px', height: PH + 'px' });
    const h = hud(pov, 'CAM 02 · 厨房 · 23:41:07');
    const det = detBox(root, '灶火 · 无人看管 10 分钟');
    const fire = tag(root, svg, { icon: 'flame', text: '燃气灶 · 火未关', brand: '厨房摄像头', state: '!', warn: true, dx: -90, dy: -110, color: '#ff9f43', cls: 'big' });
    const sent = tag(root, svg, { icon: 'bell', text: '已提醒小七', brand: '客厅音箱播报', state: '✓', dx: -80, dy: 90, color: '#ffb36b' });
    const ext = corner(root, '<b>扩展</b> · 摄像头');
    return (t, ctx) => {
      const on = ctx.flags.pov ? 1 : 0;
      h(t, on);
      det.update(t, m.detect, on ? sizedRect(ctx.A('stove'), 0.42, 0.85) : null);
      if (!on) det.update(t, 1e9, null);
      const after = !on && t > m.cam + 0.5;
      fire.update(t, after ? ctx.A('stove') : null, m.alert + 0.4, shot.frames / FPS + 0.3);
      sent.update(t, after ? ctx.A('kitcam') : null, m.alert + 1.2, shot.frames / FPS + 0.3);
      ext(t, 0.6);
      ext.el.style.opacity = on ? 0 : ext.el.style.opacity;
    };
  },
};

// S18: homework under the lamp.
SHOTS.S18 = {
  plateFilter: (t, shot, flags) => (flags.pov ? 'contrast(1.08) saturate(0.9) brightness(1.06)' : 'none'),
  build(root, shot) {
    const m = shot.marks;
    const pov = div('layer', root); css(pov, { top: BAR + 'px', height: PH + 'px' });
    const h = hud(pov, 'CAM 01 · 书桌 · 20:15:32');
    const det = detBox(root, '第 3 题 · 看图列算式');
    const apples = detBox(root, '先数一数');
    apples.lb.style.background = '#ff6f8e'; apples.lb.style.color = '#fff';
    const ext = corner(root, '<b>扩展</b> · 学习陪伴');
    return (t, ctx) => {
      const on = ctx.flags.pov ? 1 : 0;
      h(t, on);
      det.update(t, m.detect + 0.35, on ? rectOf(ctx.A, ['ws_p3_tl', 'ws_p3_tr', 'ws_p3_bl', 'ws_p3_br'], 10) : null);
      const ap = on ? rectOf(ctx.A, ['ws_apples_tl', 'ws_apples_tr', 'ws_apples_bl', 'ws_apples_br'], 4) : null;
      apples.update(t, m.count, ap);
      apples.lb.parentElement.style.borderColor = '#ff6f8e';
      ext(t, 0.6);
      ext.el.style.opacity = on ? 0 : ext.el.style.opacity;
    };
  },
};

// S19: the vision.
SHOTS.S19 = {
  build(root, shot) {
    const m = shot.marks;
    const words = ['听得懂', '管得好', '守得住'].map((w, i) => {
      const e = div('slam', root, w);
      css(e, { top: '250px', left: [520, 860, 1200][i] + 'px', fontSize: '64px', letterSpacing: '10px', color: '#fff', textShadow: '0 0 30px rgba(255,170,110,0.5)' });
      return e;
    });
    const claim = div('claim', root, '家的大脑，就该住在家里');
    claim.style.top = '230px';
    return (t) => {
      words.forEach((e, i) => {
        const t0 = m[`k${i + 1}`];
        const k = eo((t - t0) / 0.5);
        e.style.opacity = k * (1 - sm(t, m.claim - 0.6, m.claim - 0.1));
        e.style.transform = `translateY(${(1 - k) * 20}px)`;
        e.style.filter = `blur(${(1 - k) * 8}px) drop-shadow(0 2px 10px rgba(0,0,0,0.8))`;
      });
      const c = eo((t - m.claim) / 0.9);
      claim.style.opacity = c * (1 - sm(t, shot.frames / FPS - 0.2, shot.frames / FPS + 0.4));
      claim.style.letterSpacing = lerp(30, 16, eo((t - m.claim) / 2.2)) + 'px';
      claim.style.filter = `blur(${(1 - c) * 10}px) drop-shadow(0 3px 14px rgba(0,0,0,0.85))`;
    };
  },
};

// S20: end card.
SHOTS.S20 = {
  noPlate: true,
  build(root, shot) {
    const e = div('end', root,
      '<div class="t">家的大脑</div><div class="b">Open-XiaoAI · 小七</div>' +
      '<div class="r">一台带麦克风的音箱 + 一台 mini PC + 开源软件</div>' +
      '<div class="gh">github.com/OwnDing/open-xiaoai</div>' +
      '<div class="disc">开源项目 · 摄像头识别与学习陪伴为扩展方向<br>米家、海尔智家等为各自公司的商标，本项目与其无隶属关系</div>');
    const parts = [...e.children];
    return (t) => {
      parts.forEach((p, i) => {
        const k = eo((t - 0.3 - 0.35 * i) / 0.9);
        p.style.opacity = k;
        p.style.filter = `blur(${(1 - k) * 8}px)`;
      });
      parts[0].style.letterSpacing = lerp(50, 30, eo((t - 0.3) / 3)) + 'px';
    };
  },
};

// ------------------------------------------------------------------ transitions, grade, subtitles

// Incoming transition per shot: [type, frames]. "cut" keeps continuous plates seamless.
const TRANS = {
  S02: ['cut', 0], S03: ['cut', 0], S04: ['black', 22], S05: ['cross', 14], S06: ['cross', 18], S07: ['cut', 0],
  S08: ['cut', 0], S09: ['black', 18], S10: ['cross', 12], S11: ['cross', 14], S12: ['cut', 0], S13: ['cross', 18],
  S14: ['cross', 18], S15: ['cross', 16], S16: ['flash', 14], S17: ['black', 18], S18: ['cross', 16], S19: ['cross', 22],
  S20: ['black', 24],
};

// Colour grade per act: [saturate, contrast, brightness, tint rgba]
function grade(T) {
  const cold0 = gtime('S04', null) - 0.4, cold1 = gtime('S08', 'reverse') + 0.6;
  const cold = sm(T, cold0, cold0 + 0.6) * (1 - sm(T, cold1, cold1 + 1.6));
  return {
    filter: `saturate(${1.04 - 0.5 * cold}) contrast(${1.05 + 0.05 * cold}) brightness(${1 - 0.04 * cold})`,
    tint: cold > 0.001 ? `rgba(30, 80, 140, ${0.32 * cold})` : 'rgba(255, 150, 90, 0.05)',
  };
}

const NOSUB = new Set(['N18', 'N19']);
const wlen = (str) => [...str].reduce((n, c) => n + (/[\x00-\x7f]/.test(c) ? 0.5 : 1), 0);
function subtitleCues() {
  const cues = [];
  for (const s of TL.shots) {
    for (const l of s.lines) {
      if (NOSUB.has(l.id)) continue;
      const text = META[l.id].text;
      const times = charTimes(l.id);
      const t0 = s.start / FPS + l.t;
      // Split long lines at punctuation into cues of at most ~20 characters.
      const parts = [];
      let cur = '', start = 0;
      [...text].forEach((ch, i) => {
        cur += ch;
        const brk = /[，。：；？！]/.test(ch);
        if (brk && (wlen(cur) >= 9 || /[。？！]/.test(ch))) { parts.push([cur, start, i]); cur = ''; start = i + 1; }
      });
      if (cur) parts.push([cur, start, text.length - 1]);
      const merged = [];
      for (const p of parts) {
        const last = merged[merged.length - 1];
        if (last && wlen(last[0] + p[0]) <= 20 && !/[。？！]$/.test(last[0])) { last[0] += p[0]; last[2] = p[2]; } else merged.push([...p]);
      }
      merged.forEach(([txt, a, b], k) => {
        const ta = t0 + (k === 0 ? 0 : times[a] - 0.05);
        const tb = k === merged.length - 1 ? t0 + l.dur + 0.35 : t0 + times[merged[k + 1][1]] - 0.08;
        cues.push({ a: ta - 0.05, b: tb, text: txt.replace(/[，。：；]$/, ''), role: l.role });
      });
    }
  }
  return cues;
}
const ROLE = { user: '我', xiaoqi: '小七', child: '孩子', generic: '音箱' };

// ------------------------------------------------------------------ frame loop
let CUES = [];
const stage = {};
const shotUI = {};

window.init = function (data) {
  TL = data.timeline; META = data.meta; ANCH = data.anchors; FPS = TL.fps; H = TL.handle; BASE = data.plateBase;
  const s = document.getElementById('stage');
  stage.plates = div('layer', s); stage.plates.id = 'plates';
  stage.imgA = el('img', 'plate', stage.plates);
  stage.imgB = el('img', 'plate', stage.plates);
  stage.grade = div('layer', s); stage.grade.id = 'grade';
  stage.tint = div(null, stage.grade); stage.tint.id = 'tint';
  stage.vig = div(null, stage.grade); stage.vig.id = 'vignette';
  stage.ui = div('layer', s);
  stage.bars = div('layer', s);
  div('bar top', stage.bars); div('bar bot', stage.bars);
  stage.subs = div('layer', s); stage.subs.id = 'subs';
  stage.sub = div('sub', stage.subs);
  stage.flash = div('layer', s); stage.flash.id = 'flash';
  stage.black = div('layer', s); stage.black.id = 'black';
  CUES = subtitleCues();
  for (const shot of TL.shots) {
    const def = SHOTS[shot.id];
    const root = div('layer', stage.ui);
    root.style.display = 'none';
    shotUI[shot.id] = { root, def, update: def ? def.build(root, shot) : null };
  }
  return true;
};

const plateUrl = (pid, frame) => `${BASE[pid]}/${String(frame).padStart(4, '0')}.jpg`;
function plateFrame(shot, g) {
  const p = TL.plates[shot.plate];
  const f = H + (shot.plate_offset || 0) + (g - shot.start) + 1;
  return Math.max(1, Math.min(p.frames + 2 * H, f));
}
async function setImg(img, url) {
  if (img.dataset.src === url) return;
  img.dataset.src = url;
  img.src = url;
  try { await img.decode(); img.style.visibility = 'visible'; } catch (e) { img.style.visibility = 'hidden'; }
}
function rowOf(shot, g) {
  const tbl = shot.plate && ANCH[shot.plate];
  return tbl ? tbl[plateFrame(shot, g)] : null;
}
function anchorFn(shot, g) {
  const row = rowOf(shot, g);
  return (name) => {
    if (!row || !row[name]) return null;
    const [x, y, z] = row[name];
    return { x: x * W, y: BAR + y * PH, z, lens: row._lens || 35, ok: z > 0 && x > -0.02 && x < 1.02 && y > -0.02 && y < 1.02 };
  };
}
function gtime(sid, mark) {
  const s = shotById(sid);
  return s.start / FPS + (mark ? s.marks[mark] : 0);
}

function activeShots(g) {
  const shots = TL.shots;
  let i = shots.findIndex((s) => g >= s.start && g < s.start + s.frames);
  if (i < 0) i = g < 0 ? 0 : shots.length - 1;
  const cur = shots[i];
  const res = [{ shot: cur, w: 1 }];
  let black = 0, flash = 0;
  const tr = (inc) => TRANS[inc.id] || ['cross', 16];
  if (i > 0) {
    const [type, len] = tr(cur);
    const d = g - cur.start;
    if (len > 0 && d < len / 2) {
      const w = sm(d + len / 2, 0, len);
      if (type === 'cross') { res.unshift({ shot: shots[i - 1], w: 1, under: true }); res[1].w = w; }
      else { const k = 1 - Math.abs(2 * w - 1); if (type === 'black') black = k; else flash = k; }
    }
  }
  if (i < shots.length - 1) {
    const nxt = shots[i + 1];
    const [type, len] = tr(nxt);
    const d = nxt.start - g;
    if (len > 0 && d <= len / 2) {
      const w = sm(len / 2 - d, 0, len);
      if (type === 'cross') { res[res.length - 1].under = true; res.push({ shot: nxt, w }); }
      else { const k = 1 - Math.abs(2 * w - 1); if (type === 'black') black = Math.max(black, k); else flash = Math.max(flash, k); }
    }
  }
  return { list: res, black, flash, cur };
}

window.renderFrame = async function (g) {
  const T = g / FPS;
  const { list, black, flash } = activeShots(g);
  const imgs = [stage.imgA, stage.imgB];
  const loads = [];
  let slot = 0;
  for (const img of imgs) img.style.opacity = 0;
  for (const [li, it] of list.entries()) {
    const def = SHOTS[it.shot.id] || {};
    if (def.noPlate || !it.shot.plate) continue;
    const t = (g - it.shot.start) / FPS;
    const row = rowOf(it.shot, g) || {};
    const flags = row._flags || {};
    const filter = def.plateFilter ? def.plateFilter(t, it.shot, flags) : 'none';
    const shift = def.plateShift ? def.plateShift(t, it.shot) : 0;
    const img = imgs[slot++ % 2];
    loads.push(setImg(img, plateUrl(it.shot.plate, plateFrame(it.shot, g))));
    css(img, { opacity: it.w, filter, transform: `translateX(${shift}px)`, zIndex: li + 1 });
  }
  await Promise.all(loads);

  const gr = grade(T);
  stage.plates.style.filter = gr.filter;
  stage.tint.style.background = gr.tint;

  for (const id in shotUI) shotUI[id].root.style.display = 'none';
  for (const it of list) {
    const ui = shotUI[it.shot.id];
    if (!ui.update) continue;
    ui.root.style.display = 'block';
    ui.root.style.opacity = it.under ? 1 - (list[list.length - 1].w || 0) : it.w;
    const t = (g - it.shot.start) / FPS;
    const row = rowOf(it.shot, g) || {};
    ui.update(t, { A: anchorFn(it.shot, g), flags: row._flags || {} });
  }

  // subtitles in the lower bar
  let best = null, op = 0;
  for (const c of CUES) {
    const v = win(T, c.a, c.b, 0.12, 0.15);
    if (v > op) { op = v; best = c; }
  }
  const html = best ? (best.role !== 'narrator' ? `<span class="who ${best.role}">${ROLE[best.role]}</span>` : '') + `<span>${best.text}</span>` : '';
  if (stage.sub.dataset.h !== html) { stage.sub.innerHTML = html; stage.sub.dataset.h = html; }
  stage.sub.style.opacity = op;

  // fades: open from black, spark on the turn, close to black
  const end = TL.frames / FPS;
  const open = 1 - sm(T, 0.3, 1.8);
  const close = sm(T, end - 1.2, end);
  const spark = gtime('S08', null);
  const hit = T >= spark ? Math.exp(-(T - spark) * 5) : 0;
  stage.black.style.opacity = Math.max(black, open, close);
  stage.flash.style.opacity = Math.max(flash * 0.85, hit * 0.6);
  return true;
};
