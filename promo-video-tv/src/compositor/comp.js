// Frame-accurate compositor for 《遥控器退休了》. renderFrame(g) draws global frame g as a
// pure function of the timeline, so frames can be rendered in any order.
'use strict';

const W = 1920, HGT = 1080, BAR = 140, PH = 800;
let TL, META, ANCH, FPS, H, BASE, EYES;

// ------------------------------------------------------------------ helpers
const clamp = (x, a = 0, b = 1) => Math.max(a, Math.min(b, x));
const sm = (t, a, b) => { if (b <= a) return t >= a ? 1 : 0; const u = clamp((t - a) / (b - a)); return u * u * (3 - 2 * u); };
const eo = (u) => 1 - Math.pow(1 - clamp(u), 3);
const eio = (u) => { u = clamp(u); return u < 0.5 ? 4 * u * u * u : 1 - Math.pow(-2 * u + 2, 3) / 2; };
const back = (u) => { u = clamp(u); const c = 1.6; return 1 + (c + 1) * Math.pow(u - 1, 3) + c * Math.pow(u - 1, 2); };
const win = (t, a, b, fi = 0.3, fo = 0.3) => sm(t, a, a + fi) * (1 - sm(t, b - fo, b));
const lerp = (a, b, u) => a + (b - a) * u;

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
  tv: SVGP('<rect x="2.5" y="4" width="19" height="13" rx="1.5"/><path d="M8 21h8M12 17v4"/>'),
  ir: SVGP('<path d="M4 12h3M17 12h3M12 4v3M12 17v3"/><circle cx="12" cy="12" r="2.5"/><path d="M6.3 6.3l1.8 1.8M15.9 15.9l1.8 1.8M6.3 17.7l1.8-1.8M15.9 8.1l1.8-1.8"/>'),
  app: SVGP('<rect x="4" y="4" width="16" height="16" rx="4"/><path d="M10 9l5 3-5 3z"/>'),
  check: SVGP('<path d="M4 12l5 5L20 6"/>'),
  eye: SVGP('<path d="M2 12s3.6-7 10-7 10 7 10 7-3.6 7-10 7S2 12 2 12z"/><circle cx="12" cy="12" r="3"/>'),
  hand: SVGP('<path d="M8 13V5.5a1.5 1.5 0 0 1 3 0V11M11 10.5V4a1.5 1.5 0 0 1 3 0v7M14 10.5V5.5a1.5 1.5 0 0 1 3 0V13M17 11a1.5 1.5 0 0 1 3 0v3a7 7 0 0 1-7 7h-1a6 6 0 0 1-5-2.7L4 14.5a1.6 1.6 0 0 1 2.6-1.8L8 14"/>'),
  type: SVGP('<rect x="2" y="6" width="20" height="12" rx="2"/><path d="M6 10h.01M10 10h.01M14 10h.01M18 10h.01M7 14h10"/>'),
  click: SVGP('<path d="M9 9l11 4-5 2-2 5z"/><path d="M5 3v3M3 5h3M9.5 4.5L8 6M4.5 9.5L6 8"/>'),
  remote: SVGP('<rect x="8" y="2" width="8" height="20" rx="3"/><circle cx="12" cy="9" r="2.2"/><path d="M12 14v.01M12 17v.01"/>'),
  play: SVGP('<path d="M7 4l13 8-13 8z"/>'),
  next: SVGP('<path d="M5 5l10 7-10 7zM19 5v14"/>'),
  vol: SVGP('<path d="M4 9h4l5-4v14l-5-4H4z"/><path d="M16 9a4 4 0 0 1 0 6"/>'),
  ff: SVGP('<path d="M3 6l8 6-8 6zM12 6l8 6-8 6z"/>'),
  music: SVGP('<path d="M9 18V6l10-2v12"/><circle cx="6.5" cy="18" r="2.5"/><circle cx="16.5" cy="16" r="2.5"/>'),
  globe: SVGP('<circle cx="12" cy="12" r="9"/><path d="M3 12h18M12 3c3 3.5 3 14.5 0 18M12 3c-3 3.5-3 14.5 0 18"/>'),
  hermes: SVGP('<path d="M12 3l1.8 5.2L19 10l-5.2 1.8L12 17l-1.8-5.2L5 10l5.2-1.8z"/>'),
  power: SVGP('<path d="M12 3v8M6.3 7a8 8 0 1 0 11.4 0"/>'),
  home: SVGP('<path d="M3 11l9-7 9 7v9a1 1 0 0 1-1 1h-5v-6h-6v6H4a1 1 0 0 1-1-1z"/>'),
  lan: SVGP('<rect x="9" y="2" width="6" height="5" rx="1"/><rect x="2" y="17" width="6" height="5" rx="1"/><rect x="16" y="17" width="6" height="5" rx="1"/><path d="M12 7v5M5 17v-3h14v3"/>'),
  moon: SVGP('<path d="M20 14.5A8 8 0 1 1 9.5 4 6.5 6.5 0 0 0 20 14.5z"/>'),
};
const KEYICON = { left: '←', right: '→', up: '↑', down: '↓', ok: 'OK' };

// ------------------------------------------------------------------ data access
const shotById = (id) => TL.shots.find((s) => s.id === id);
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
  scrim.style.background = 'linear-gradient(90deg, rgba(0,8,20,0.78), rgba(0,8,20,0.38) 45%, rgba(0,0,0,0) 70%)';
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
    const gl = t > t0 && t < t0 + 0.25 ? Math.sin(t * 140) * 6 : 0;
    p.style.transform = `translateX(${gl}px)`;
  };
}

function bigLabel(parent, n, h, d, chips, pos) {
  // The label sits over a full-frame TV picture: darken and soften the left of it so the text reads.
  const scrim = div('layer', parent);
  scrim.style.background = 'linear-gradient(90deg, rgba(0,0,0,0.84), rgba(0,0,0,0.7) 30%, rgba(0,0,0,0.3) 46%, rgba(0,0,0,0) 60%)';
  scrim.style.backdropFilter = 'blur(8px)';
  scrim.style.webkitMaskImage = 'linear-gradient(90deg, #000 40%, transparent 58%)';
  const e = div('big-label', parent,
    `<div class="n">${n}</div><div class="h">${h}</div><div class="d">${d}</div>` +
    (chips ? `<div class="chips">${chips.map((c) => `<span>${c}</span>`).join('')}</div>` : ''));
  css(e, pos);
  const parts = [...e.children];
  const chipEls = e.querySelector('.chips') ? [...e.querySelector('.chips').children] : [];
  const f = (t, t0, t1 = 1e9) => {
    const out = 1 - sm(t, t1 - 0.4, t1);
    scrim.style.opacity = sm(t, t0 - 0.2, t0 + 0.4) * out;
    parts.forEach((p, i) => {
      const k = eo((t - t0 - 0.12 * i) / 0.55);
      p.style.opacity = k * out;
      p.style.transform = `translateY(${(1 - k) * 20}px)`;
    });
  };
  f.chips = chipEls;
  f.el = e;
  return f;
}

// ------------------------------------------------------------------ 小七's eyes and hands on a TV screen

// Which TV in the plate shows which rendered screen (mirrors SCREENS in plates.py).
const SCREEN_OF = {
  P01: { tv: 'main' }, P04: { tv: 'main' }, P05: { tv: 'main' }, P06: { ta: 'a', tb: 'c', tc: 'b' },
  P09: { trtv: 'studio' }, P10: { trtv: 'studio' }, P13: { tv: 'main' }, P14: { tv: 'main' }, P15: { tv: 'main' },
  P16: { tv: 'main' }, P17: { tv: 'main' },
};

// Projective map of the unit square onto the screen quad (Heckbert).
function homography(A, prefix) {
  const q = ['tl', 'tr', 'br', 'bl'].map((k) => A(`${prefix}_${k}`));
  if (q.some((p) => !p || p.z <= 0)) return null;
  const [p0, p1, p2, p3] = q;
  const dx1 = p1.x - p2.x, dx2 = p3.x - p2.x, dx3 = p0.x - p1.x + p2.x - p3.x;
  const dy1 = p1.y - p2.y, dy2 = p3.y - p2.y, dy3 = p0.y - p1.y + p2.y - p3.y;
  const den = dx1 * dy2 - dy1 * dx2;
  const g = (dx3 * dy2 - dy3 * dx2) / den, h = (dx1 * dy3 - dy1 * dx3) / den;
  const a = p1.x - p0.x + g * p1.x, b = p3.x - p0.x + h * p3.x, c = p0.x;
  const d = p1.y - p0.y + g * p1.y, e = p3.y - p0.y + h * p3.y, f = p0.y;
  return (x, y) => { const u = x / 1920, v = y / 1080, w = g * u + h * v + 1; return [(a * u + b * v + c) / w, (d * u + e * v + f) / w]; };
}

function screenFx(parent) {
  const svg = lineSvg(parent);
  svg.style.overflow = 'hidden';
  const defs = svgEl('defs', svg);
  const flt = svgEl('filter', defs, { id: 'eyeglow', x: '-20%', y: '-20%', width: '140%', height: '140%' });
  svgEl('feGaussianBlur', flt, { stdDeviation: 3, result: 'b' });
  const mg = svgEl('feMerge', flt);
  svgEl('feMergeNode', mg, { in: 'b' }); svgEl('feMergeNode', mg, { in: 'SourceGraphic' });
  const pool = [], rings = [];
  const label = div('eye-ok', parent, `<span>${ICON.check}</span>已核对`);
  return (ctx, prefix, opts = {}) => {
    const hmap = homography(ctx.A, prefix);
    const data = ctx.eyes(prefix) || {};
    let n = 0, r = 0;
    label.style.opacity = 0;
    if (hmap && data.e) {
      for (const [x, y, w, h, k, verify] of data.e) {
        const pts = [[x - 4, y - 4], [x + w + 4, y - 4], [x + w + 4, y + h + 4], [x - 4, y + h + 4]].map(([a, b]) => hmap(a, b));
        let p = pool[n];
        if (!p) { p = svgEl('polygon', svg, { fill: 'rgba(255,179,107,0.07)', stroke: '#ffb36b', 'stroke-width': 2, filter: 'url(#eyeglow)', 'stroke-linejoin': 'round' }); pool.push(p); }
        p.setAttribute('points', pts.map((q) => q.join(',')).join(' '));
        p.setAttribute('opacity', k * (opts.gain ?? 1));
        p.setAttribute('stroke', verify ? '#7dffb0' : '#ffb36b');
        p.setAttribute('stroke-width', verify ? 3 : 2);
        p.style.display = 'block';
        n++;
        if (verify && k > 0.05) {
          const [lx, ly] = pts[1];
          css(label, { left: lx + 14 + 'px', top: ly - 6 + 'px', opacity: k });
        }
      }
    }
    for (; n < pool.length; n++) pool[n].style.display = 'none';
    if (hmap && data.c) {
      for (const [x, y, w, h, k] of data.c) {
        const [cx, cy] = hmap(x + w / 2, y + h / 2);
        const scale = Math.hypot(...hmap(x + w, y + h).map((v, i) => v - [cx, cy][i]));
        for (let j = 0; j < 2; j++) {
          const kk = clamp(k * 1.3 - j * 0.3);
          let c = rings[r];
          if (!c) { c = svgEl('ellipse', svg, { fill: 'none', stroke: '#fff', 'stroke-width': 3 }); rings.push(c); }
          c.setAttribute('cx', cx); c.setAttribute('cy', cy);
          const rad = 8 + kk * (40 + scale * 0.6);
          c.setAttribute('rx', rad); c.setAttribute('ry', rad * 0.8);
          c.setAttribute('opacity', (1 - kk) * 0.9);
          c.style.display = 'block';
          r++;
        }
      }
    }
    for (; r < rings.length; r++) rings[r].style.display = 'none';
  };
}

// A vertical list of steps that tick off one by one.
function steps(parent, title, kicker, items, pos) {
  const e = div('steps', parent, `<div class="k">${kicker}</div><div class="h">${title}</div>`);
  css(e, pos);
  const rows = items.map((it, i) => div('st', e, `<i>${i + 1}</i><span>${it}</span><b>${ICON.check}</b>`));
  const head = [...e.children].slice(0, 2);
  return (t, t0, times, t1 = 1e9) => {
    const out = 1 - sm(t, t1 - 0.4, t1);
    head.forEach((h, i) => { const k = eo((t - t0 - 0.1 * i) / 0.5); h.style.opacity = k * out; h.style.transform = `translateY(${(1 - k) * 14}px)`; });
    rows.forEach((r, i) => {
      const k = eo((t - times[i] + 0.25) / 0.4);
      r.style.opacity = (0.25 + 0.75 * k) * out * sm(t, t0, t0 + 0.4);
      r.classList.toggle('on', t >= times[i] - 0.05);
      r.querySelector('b').style.transform = `scale(${back((t - times[i] - 0.25) / 0.35)})`;
      r.querySelector('b').style.opacity = t >= times[i] + 0.25 ? 1 : 0;
    });
  };
}

// A row of chips that light up at their times.
function chipRow(parent, items, pos) {
  const e = div('chiprow', parent);
  css(e, pos);
  const C = items.map(([icon, label]) => div('chip', e, `<span>${ICON[icon]}</span>${label}`));
  return (t, t0, times, t1 = 1e9) => {
    const out = 1 - sm(t, t1 - 0.4, t1);
    C.forEach((c, i) => {
      const k = eo((t - t0 - 0.08 * i) / 0.5);
      c.style.opacity = k * out;
      c.style.transform = `translateY(${(1 - k) * 12}px) scale(${1 + 0.08 * Math.exp(-Math.max(0, t - times[i]) * 5) * (t >= times[i] ? 1 : 0)})`;
      c.classList.toggle('on', t >= times[i]);
    });
  };
}

// ------------------------------------------------------------------ shots
const SHOTS = {};
const MARK = (shot, name) => shot.marks[name];
const END = (shot) => shot.frames / FPS;

// S02: the TV wakes and plays -- tags as each step lands, and the episode check.
SHOTS.S02 = {
  build(root, shot) {
    const svg = lineSvg(root);
    const fx = screenFx(root);
    const m = shot.marks;
    const tags = [
      [tag(root, svg, { icon: 'ir', text: '电视 · 红外开机', brand: '先确认电视关着', state: '✓', dx: -90, dy: 70, color: '#ff8a7a' }), 'tv_led', m.tv_on + 0.2],
      [tag(root, svg, { icon: 'app', text: '银河奇异果', brand: '打开应用', state: '✓', dx: -80, dy: -40, color: '#5be38f' }), 'tv_tl', m.app + 0.05],
      [tag(root, svg, { icon: 'play', text: '《雾港》第 2 集', brand: '读屏核对', state: '✓', dx: 80, dy: -30, color: '#ffcf8a' }), 'tv_tr', m.verify + 0.1],
    ];
    return (t, ctx) => {
      for (const [tg, a, t0] of tags) tg.update(t, ctx.A(a), t0, END(shot) + 0.2);
      fx(ctx, 'tv');
    };
  },
};

// S03: the title over the remote nobody touched.
SHOTS.S03 = {
  build(root, shot) {
    const scrim = div('layer', root);
    scrim.style.background = 'radial-gradient(ellipse 60% 45% at 50% 24%, rgba(0,0,0,0.55), rgba(0,0,0,0) 100%)';
    const tm = div('title-main', root, '遥控器退休了');
    const ln = div('title-line', root);
    const ts = div('title-sub', root, '让小七，接管你家的电视');
    const t0 = MARK(shot, 'title');
    const end = END(shot);
    return (t) => {
      const out = 1 - sm(t, end - 0.5, end + 0.2);
      const a = eo((t - t0) / 1.2);
      scrim.style.opacity = sm(t, t0 - 0.3, t0 + 0.6) * out;
      tm.style.opacity = a * out;
      tm.style.letterSpacing = lerp(48, 24, eo((t - t0) / 2.5)) + 'px';
      tm.style.filter = `blur(${(1 - a) * 14}px)`;
      const sw = clamp((t - t0 - 0.4) / 2.2);
      tm.style.backgroundImage = `linear-gradient(100deg, #fff ${sw * 140 - 40}%, #ffd2aa ${sw * 140 - 20}%, #fff ${sw * 140}%, #ffe6cf 100%)`;
      ln.style.opacity = sm(t, t0 + 0.5, t0 + 1.2) * out;
      ln.style.transform = `scaleX(${eo((t - t0 - 0.5) / 1.2)})`;
      ts.style.opacity = sm(t, t0 + 0.8, t0 + 1.6) * out;
      ts.style.letterSpacing = lerp(16, 10, eo((t - t0 - 0.8) / 2)) + 'px';
    };
  },
};

// S04: pain 1 -- the TV is only a switch.
SHOTS.S04 = {
  plateFilter: (t, shot) => {
    const f = shot.marks.fail;
    return t > f && t < f + 0.35 ? `contrast(1.2) hue-rotate(${Math.sin(t * 90) * 25}deg)` : 'none';
  },
  plateShift: (t, shot) => { const f = shot.marks.fail; return t > f && t < f + 0.35 ? Math.sin(t * 110) * 14 * (1 - (t - f) / 0.35) : 0; },
  build(root, shot) {
    const svg = lineSvg(root);
    const m = shot.marks;
    const on = tag(root, svg, { icon: 'power', text: '开机 · 红外', brand: '能做的，就这一步', state: '✓', dx: 90, dy: 80, color: '#9cc8ff' });
    const no = tag(root, svg, { icon: 'play', text: '找片 · 选集', brand: '做不到', state: '✕', warn: true, dx: 90, dy: -40, color: '#9cc8ff' });
    const card = painCard(root, '01', '只会开关', '电视在它眼里，只是一个开关');
    return (t, ctx) => {
      on.update(t, ctx.A('tv_br'), m.tv_on + 0.6, m.card - 0.1);
      no.update(t, ctx.A('tv_br'), m.fail + 0.1, m.card - 0.1);
      card(t, m.card, END(shot) + 0.3);
    };
  },
};

// S05: 37 presses of the remote.
SHOTS.S05 = {
  build(root, shot) {
    const presses = shot.data.presses;
    const cnt = div('counter', root, '<div class="l">按键</div><div class="n"><span>×</span><b>0</b></div><div class="s">示意 · 实际要按将近一分钟</div>');
    const key = div('keyflash', root);
    const card = painCard(root, '02', '还得靠遥控器', '找一部剧，按了 37 下');
    const m = shot.marks;
    return (t) => {
      let n = 0, last = null;
      for (const p of presses) if (p[0] <= t) { n++; last = p; }
      cnt.querySelector('b').textContent = n;
      cnt.style.opacity = sm(t, presses[0][0] - 0.3, presses[0][0]) * (1 - sm(t, m.card + 1.0, m.card + 1.4));
      const bump = last ? Math.exp(-(t - last[0]) * 14) : 0;
      cnt.querySelector('b').style.transform = `scale(${1 + 0.25 * bump})`;
      cnt.classList.toggle('done', n === presses.length);
      key.textContent = last ? KEYICON[last[1]] : '';
      key.style.opacity = last ? Math.exp(-(t - last[0]) * 6) * (1 - sm(t, m.card - 0.2, m.card)) : 0;
      card(t, m.card, END(shot) + 0.3);
    };
  },
};

// S06: three TVs, three voices; the smart speaker only reaches them with on/off.
SHOTS.S06 = {
  build(root, shot) {
    const m = shot.marks;
    const pills = ['ta', 'tb', 'tc'].map(() => div('onoff', root, '开 / 关'));
    const hub = div('hublabel', root, '智能家居 · 只能开关');
    const card = painCard(root, '03', '各说各话', '一个牌子一套语音，进不了家');
    return (t, ctx) => {
      ['ta', 'tb', 'tc'].forEach((n, i) => {
        const a = ctx.A(`hub_${n}_mid`);
        const k = sm(t, m.c + 0.3 + 0.15 * i, m.c + 0.6 + 0.15 * i) * (1 - sm(t, m.card - 0.3, m.card));
        if (a && a.ok) css(pills[i], { left: a.x + 'px', top: a.y + 'px', opacity: k });
        else pills[i].style.opacity = 0;
      });
      const h = ctx.A('hubsp');
      if (h && h.ok) css(hub, { left: h.x + 'px', top: h.y + 70 + 'px', opacity: sm(t, m.c, m.c + 0.4) * (1 - sm(t, m.card - 0.3, m.card)) });
      card(t, m.card, END(shot) + 0.3);
    };
  },
};

// S07: three words slam, then collapse into a point of light.
SHOTS.S07 = {
  plateFilter: () => 'brightness(0.35) blur(6px) saturate(0.4)',
  build(root, shot) {
    const X = [250, 760, 1270];
    const words = ['只会开关', '还得遥控', '各说各话'].map((w, i) => { const e = div('slam', root, w); e.style.left = X[i] + 'px'; return e; });
    const pt = div('point', root);
    const m = shot.marks;
    return (t) => {
      const col = sm(t, m.collapse - 0.35, m.collapse);
      words.forEach((e, i) => {
        const t0 = m[`w${i + 1}`];
        const k = clamp((t - t0) / 0.18);
        const sc = lerp(1.8, 1, eo(k));
        const cx = 960 - (X[i] + 200);
        e.style.opacity = sm(t, t0, t0 + 0.08) * (1 - col);
        e.style.transform = `translateX(${cx * col}px) scale(${sc * (1 - 0.9 * col)})`;
        e.style.filter = `blur(${(1 - k) * 8 + col * 6}px)`;
      });
      pt.style.opacity = sm(t, m.collapse - 0.15, m.collapse);
      pt.style.transform = `scale(${0.3 + 1.2 * sm(t, m.collapse - 0.1, m.collapse + 0.1)})`;
    };
  },
};

// S08: the point lands as the standby light; the middle TV wakes warm and 小七 reads it.
SHOTS.S08 = {
  build(root, shot) {
    const fx = screenFx(root);
    const pt = div('point', root);
    const c = div('claim', root, '电视，交给小七');
    css(c, { top: '158px', fontSize: '62px' });
    const m = shot.marks;
    return (t, ctx) => {
      const led = ctx.A('tb_led');
      const u = eio(clamp(t / 0.3));
      const x = led && led.ok ? lerp(960, led.x, u) : 960, y = led && led.ok ? lerp(540, led.y, u) : 540;
      css(pt, { left: x + 'px', top: y + 'px', opacity: 1 - sm(t, m.led, m.led + 0.25), transform: `scale(${1 - 0.6 * u})` });
      fx(ctx, 'tb');
      const a = eo((t - m.claim) / 0.9);
      c.style.opacity = a * (1 - sm(t, END(shot) - 0.3, END(shot) + 0.2));
      c.style.letterSpacing = lerp(30, 16, eo((t - m.claim) / 2)) + 'px';
      c.style.filter = `blur(${(1 - a) * 10}px) drop-shadow(0 3px 14px rgba(0,0,0,0.8))`;
    };
  },
};

// S09: the trio, numbered.
SHOTS.S09 = {
  build(root, shot) {
    const m = shot.marks;
    const items = [['tr_sp', '1', '音箱', '听你说', m.b1], ['tr_pc', '2', 'mini PC', '小七在这里', m.b2], ['trtv_c', '3', '电视助手', '新', m.b3]];
    const B = items.map(([a, n, h, s]) => ({ a, e: div('trio', root, `<div class="num-badge">${n}</div><div class="h">${h}</div><div class="s">${s}</div>`) }));
    const k = div('toptitle', root, '<span class="k">还是那一套</span>多了一个<span class="g">电视助手</span>');
    return (t, ctx) => {
      B.forEach(({ a, e }, i) => {
        const p = ctx.A(a);
        const t0 = items[i][4];
        const v = p && p.ok;
        const dy = i === 2 ? -10 : -150;
        css(e, { left: (v ? p.x : -999) + 'px', top: (v ? p.y + dy : -999) + 'px', opacity: eo((t - t0) / 0.4) });
        e.firstChild.style.transform = `scale(${back((t - t0) / 0.45)})`;
      });
      const kk = eo((t - m.b3 - 0.3) / 0.6);
      k.style.opacity = kk; k.style.transform = `translateY(${(1 - kk) * 16}px)`;
    };
  },
};

// S10: 小七's eyes -- every text on the screen read in under 0.3 s (shown slowed down).
SHOTS.S10 = {
  build(root, shot) {
    const fx = screenFx(root);
    const L = bigLabel(root, '<span class="ico-svg" style="display:inline-block;width:110px;height:110px;color:#ffb36b">' + ICON.eye + '</span>', '小七的眼睛', '一次读完整块屏幕上的文字', null, { left: '110px', top: '360px' });
    const timer = div('timer', root, '<b>0.00</b> 秒<small>慢放示意</small>');
    const m = shot.marks;
    return (t, ctx) => {
      L(t, 0.3, END(shot) + 0.3);
      fx(ctx, 'trtv');
      const u = clamp((t - m.scan) / 1.2);
      timer.querySelector('b').textContent = (0.28 * u).toFixed(2);
      timer.style.opacity = sm(t, m.scan - 0.2, m.scan) * (1 - sm(t, END(shot) - 0.2, END(shot) + 0.2));
      timer.classList.toggle('done', u >= 1);
    };
  },
};

// S11: 小七's hands -- type, click, keys, playback.
SHOTS.S11 = {
  build(root, shot) {
    const fx = screenFx(root);
    const m = shot.marks;
    const L = bigLabel(root, '<span class="ico-svg" style="display:inline-block;width:110px;height:110px;color:#ff6f8e">' + ICON.hand + '</span>', '小七的手', '替你在屏幕上操作', null, { left: '110px', top: '300px' });
    const chips = chipRow(root, [['type', '打字'], ['click', '点击'], ['remote', '按键'], ['play', '播放控制']], { left: '114px', top: '640px' });
    const keys = div('keyflash small', root);
    return (t, ctx) => {
      L(t, 0.15, END(shot) + 0.3);
      chips(t, 0.4, [m.type, m.click, m.keys, m.media], END(shot) + 0.3);
      fx(ctx, 'trtv');
      const kt = [[m.keys, '→'], [m.keys + 0.45, 'OK']];
      let cur = null;
      for (const [k0, s] of kt) if (t >= k0) cur = [k0, s];
      keys.textContent = cur ? cur[1] : '';
      keys.style.opacity = cur ? Math.exp(-(t - cur[0]) * 4) : 0;
    };
  },
};

// S12: the chain -- speaker, 小七 on the mini PC, the TV helper; all on the home network.
SHOTS.S12 = {
  plateFilter: () => 'blur(9px) brightness(0.38) saturate(0.8)',
  build(root, shot) {
    const m = shot.marks;
    const lan = div('lan', root, `<div class="lab"><span>${ICON.lan}</span>家里的局域网 · 不经过云端</div>`);
    const node = (x, icon, color, h, s, notes) => {
      const n = div('ex-node wide', root, `<div class="c" style="color:${color}">${ICON[icon]}</div><div class="l">${h}</div><div class="s">${s}</div>` +
        (notes ? `<div class="note">${notes}</div>` : ''));
      css(n, { left: x + 'px', top: '330px' });
      return n;
    };
    const n1 = node(430, 'speaker', '#ffcf9a', '音箱', '听你说 · 红外开机', '<b>红外是开关切换</b><br>电视关着才发，开着就不发');
    const n2 = node(960, 'hermes', '#9b7bff', 'mini PC · 小七', '理解 · 规划 · 核对');
    const n3 = node(1490, 'tv', '#ffb36b', '电视助手', '读屏 · 点击 · 按键 · 打字 · 播放', '<b>关机</b> 直接让电视待机');
    const cv = el('canvas', null, root);
    cv.width = W; cv.height = HGT;
    css(cv, { position: 'absolute', left: 0, top: 0 });
    const g = cv.getContext('2d');
    const pop = (e, t0, t) => { const k = back((t - t0) / 0.45); e.style.opacity = sm(t, t0, t0 + 0.15); e.style.transform = `scale(${Math.max(0, k)})`; };
    return (t) => {
      const fin = 1 - sm(t, END(shot) - 0.3, END(shot) + 0.3);
      root.style.opacity = sm(t, 0.0, 0.4) * fin;
      pop(n1, m.n1, t); pop(n2, m.n2, t); pop(n3, m.n3, t);
      [n1, n3].forEach((n, i) => { const note = n.querySelector('.note'); if (note) note.style.opacity = sm(t, i ? m.lan - 0.6 : m.ir + 0.1, (i ? m.lan - 0.6 : m.ir + 0.1) + 0.4); });
      const lk = sm(t, m.lan - 0.2, m.lan + 0.4);
      lan.style.opacity = lk;
      lan.style.transform = `scale(${1.04 - 0.04 * lk})`;
      g.clearRect(0, 0, W, HGT);
      const link = (x0, x1, t0, col) => {
        const u = eo((t - t0) / 0.5);
        if (u <= 0) return;
        g.strokeStyle = col; g.lineWidth = 3; g.setLineDash([8, 10]); g.lineDashOffset = -t * 40;
        g.beginPath(); g.moveTo(x0, 378); g.lineTo(lerp(x0, x1, u), 378); g.stroke();
        g.setLineDash([]);
        for (let i = 0; i < 3; i++) {
          const v = ((t * 0.7 + i / 3) % 1);
          if (u < 1) continue;
          g.fillStyle = col; g.beginPath(); g.arc(lerp(x0, x1, v), 378, 5, 0, 6.283); g.fill();
        }
      };
      link(510, 880, m.n2, 'rgba(255,179,107,0.9)');
      link(1040, 1410, m.n3, 'rgba(155,123,255,0.9)');
    };
  },
};

// S13: the opening sentence, step by step.
SHOTS.S13 = {
  build(root, shot) {
    const fx = screenFx(root);
    const m = shot.marks;
    const scrim = div('layer', root);
    scrim.style.background = 'linear-gradient(90deg, rgba(0,0,0,0.72), rgba(0,0,0,0.35) 32%, rgba(0,0,0,0) 48%)';
    const st = steps(root, '“开电视，我想看《雾港》第二集”', '慢放那一句', ['电视关着 → 红外开机', '打开奇异果', '搜索“雾港”', '点“播放”', '切到第 2 集', '读屏核对：第 2 集'],
      { left: '96px', top: '196px' });
    const fin = div('stepsok', root, `<span>${ICON.check}</span>开始播放`);
    return (t, ctx) => {
      scrim.style.opacity = sm(t, 0, 0.5) * (1 - sm(t, END(shot) - 0.2, END(shot) + 0.3));
      st(t, 0.15, [1, 2, 3, 4, 5, 6].map((i) => m[`k${i}`]), END(shot) + 0.3);
      const k = eo((t - m.ok) / 0.45);
      fin.style.opacity = k * (1 - sm(t, END(shot) - 0.2, END(shot) + 0.3));
      fin.style.transform = `translateY(${(1 - k) * 12}px)`;
      fx(ctx, 'tv');
    };
  },
};

// S14: during playback -- seek, next, volume.
SHOTS.S14 = {
  build(root, shot) {
    const svg = lineSvg(root);
    const m = shot.marks;
    const title = topTitle(root, '不用找遥控器', '播放中，<span class="g">随时说</span>');
    const T = [
      [tag(root, svg, { icon: 'ff', text: '快进到 14:20', brand: '报出播到哪', state: '✓', color: '#5be38f' }), m.seek + 0.5],
      [tag(root, svg, { icon: 'next', text: '第 3 集', brand: '下一集', state: '✓', color: '#5be38f' }), m.next + 0.5],
      [tag(root, svg, { icon: 'vol', text: '音量 12', brand: '声音小一点', state: '✓', color: '#5be38f' }), m.vol + 0.4],
    ];
    return (t) => {
      title(t, 0.2, END(shot) + 0.3);
      T.forEach(([tg, t0], i) => tg.update(t, null, t0, END(shot) + 0.3, { x: 110, y: 560 + i * 98 }));
    };
  },
};

// S15: no button for it -- step by step in the music app.
SHOTS.S15 = {
  build(root, shot) {
    const fx = screenFx(root);
    const m = shot.marks;
    const title = topTitle(root, '网易云音乐 · 每日推荐', '没有现成的按钮，<span class="g">就一步步点</span>');
    const chips = chipRow(root, [['music', '打开网易云音乐'], ['click', '点“每日推荐”'], ['play', '点“播放全部”']], { left: '114px', top: '345px' });
    return (t, ctx) => {
      title(t, 0.25, END(shot) + 0.3);
      chips(t, 0.6, [m.app, m.daily, m.all], END(shot) + 0.3);
      fx(ctx, 'tv');
    };
  },
};

// S16: the browser -- one sentence typed in one go.
SHOTS.S16 = {
  build(root, shot) {
    const fx = screenFx(root);
    const m = shot.marks;
    const title = topTitle(root, '浏览器也能用', '整句<span class="g">一次输完</span>');
    const sub = div('subnote', root, '不用再一个字母一个字母地按');
    // The white browser page fills the left; the dark wall on the right takes the words.
    css(title.el, { left: '1290px' });
    css(sub, { left: '1292px' });
    return (t, ctx) => {
      title(t, 0.25, END(shot) + 0.3);
      const k = eo((t - m.type - 0.2) / 0.5) * (1 - sm(t, END(shot) - 0.2, END(shot) + 0.3));
      sub.style.opacity = k; sub.style.transform = `translateY(${(1 - k) * 10}px)`;
      fx(ctx, 'tv');
    };
  },
};

// S17: good night.
SHOTS.S17 = {
  build(root, shot) {
    const svg = lineSvg(root);
    const off = tag(root, svg, { icon: 'moon', text: '电视 · 待机', brand: '关电视', state: '✓', dx: 90, dy: -80, color: '#ffcf8a' });
    return (t, ctx) => off.update(t, ctx.A('tv_led'), MARK(shot, 'off') + 0.5, END(shot) + 0.3);
  },
};

// S18: the museum -- five words, then the claim.
SHOTS.S18 = {
  build(root, shot) {
    const m = shot.marks;
    const X = [330, 600, 870, 1140, 1410];
    const words = ['开机', '找片', '选集', '上网', '听歌'].map((w, i) => {
      const e = div('slam soft', root, w);
      css(e, { top: '232px', left: X[i] + 'px' });
      return e;
    });
    const claim = div('claim', root, '遥控器，可以退休了');
    claim.style.top = '206px';
    return (t) => {
      words.forEach((e, i) => {
        const t0 = m[`k${i + 1}`];
        const k = eo((t - t0) / 0.5);
        e.style.opacity = k * (1 - sm(t, m.retire - 0.6, m.retire - 0.1));
        e.style.transform = `translateY(${(1 - k) * 20}px)`;
        e.style.filter = `blur(${(1 - k) * 8}px) drop-shadow(0 2px 10px rgba(0,0,0,0.8))`;
      });
      const c = eo((t - m.retire) / 0.9);
      claim.style.opacity = c * (1 - sm(t, END(shot) - 0.2, END(shot) + 0.4));
      claim.style.letterSpacing = lerp(30, 16, eo((t - m.retire) / 2.2)) + 'px';
      claim.style.filter = `blur(${(1 - c) * 10}px) drop-shadow(0 3px 14px rgba(0,0,0,0.85))`;
    };
  },
};

// S19: end card.
SHOTS.S19 = {
  noPlate: true,
  build(root, shot) {
    const e = div('end', root,
      '<div class="t">遥控器退休了</div><div class="b">Open-XiaoAI · 小七</div>' +
      '<div class="r">小爱音箱 + mini PC + 小七电视助手（开源）</div>' +
      '<div class="gh">github.com/OwnDing/open-xiaoai</div>' +
      '<div class="disc">目前在 TCL 雷鸟（Android 11）上验收，适用于开启 ADB 调试的安卓电视 · 片中剧集《雾港》与歌曲均为虚构<br>' +
      '银河奇异果、网易云音乐等为各自公司的商标，本项目与其无隶属关系</div>');
    const parts = [...e.children];
    return (t) => {
      parts.forEach((p, i) => {
        const k = eo((t - 0.3 - 0.35 * i) / 0.9);
        p.style.opacity = k;
        p.style.filter = `blur(${(1 - k) * 8}px)`;
      });
      parts[0].style.letterSpacing = lerp(40, 24, eo((t - 0.3) / 3)) + 'px';
    };
  },
};

// ------------------------------------------------------------------ transitions, grade, subtitles

// Incoming transition per shot: [type, frames]. "cut" keeps continuous plates seamless.
const TRANS = {
  S02: ['cut', 0], S03: ['cut', 0], S04: ['black', 22], S05: ['cross', 14], S06: ['cross', 18], S07: ['cut', 0],
  S08: ['cut', 0], S09: ['cross', 18], S10: ['cross', 14], S11: ['cut', 0], S12: ['cut', 0], S13: ['black', 20],
  S14: ['cross', 16], S15: ['cross', 16], S16: ['cross', 16], S17: ['cross', 16], S18: ['black', 24], S19: ['black', 24],
};

// Colour grade: cold and desaturated from the pain points until the turn.
function grade(T) {
  const cold0 = gtime('S04', null) - 0.4, cold1 = gtime('S08', 'wake');
  const cold = sm(T, cold0, cold0 + 0.6) * (1 - sm(T, cold1, cold1 + 1.4));
  return {
    filter: `saturate(${1.04 - 0.5 * cold}) contrast(${1.05 + 0.05 * cold}) brightness(${1 - 0.04 * cold})`,
    tint: cold > 0.001 ? `rgba(30, 80, 140, ${0.3 * cold})` : 'rgba(255, 150, 90, 0.05)',
  };
}

const NOSUB = new Set(['N13', 'N14']);
const wlen = (str) => [...str].reduce((n, c) => n + (/[\x00-\x7f]/.test(c) ? 0.5 : 1), 0);
function subtitleCues() {
  const cues = [];
  for (const s of TL.shots) {
    for (const l of s.lines) {
      if (NOSUB.has(l.id)) continue;
      const text = META[l.id].text;
      const times = charTimes(l.id);
      const t0 = s.start / FPS + l.t;
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
const ROLE = { user: '我', xiaoqi: '小七', generic: '音箱' };

// ------------------------------------------------------------------ frame loop
let CUES = [];
const stage = {};
const shotUI = {};

window.init = function (data) {
  TL = data.timeline; META = data.meta; ANCH = data.anchors; FPS = TL.fps; H = TL.handle; BASE = data.plateBase; EYES = data.eyes || {};
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
function eyesFn(shot, g) {
  if (!shot.plate) return () => null;
  const f = plateFrame(shot, g);
  const map = SCREEN_OF[shot.plate] || {};
  return (prefix) => {
    const sid = map[prefix];
    const tbl = sid && EYES[shot.plate] && EYES[shot.plate][sid];
    return tbl ? tbl[f] : null;
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
    ui.update(t, { A: anchorFn(it.shot, g), eyes: eyesFn(it.shot, g), flags: row._flags || {} });
  }

  let best = null, op = 0;
  for (const c of CUES) {
    const v = win(T, c.a, c.b, 0.12, 0.15);
    if (v > op) { op = v; best = c; }
  }
  const html = best ? (best.role !== 'narrator' ? `<span class="who ${best.role}">${ROLE[best.role]}</span>` : '') + `<span>${best.text}</span>` : '';
  if (stage.sub.dataset.h !== html) { stage.sub.innerHTML = html; stage.sub.dataset.h = html; }
  stage.sub.style.opacity = op;

  // fades: open from black, a spark on the turn, close to black
  const end = TL.frames / FPS;
  const open = 1 - sm(T, 0.3, 1.8);
  const close = sm(T, end - 1.2, end);
  const spark = gtime('S08', null);
  const hit = T >= spark ? Math.exp(-(T - spark) * 5) : 0;
  stage.black.style.opacity = Math.max(black, open, close);
  stage.flash.style.opacity = Math.max(flash * 0.85, hit * 0.5);
  return true;
};
