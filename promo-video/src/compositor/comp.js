// Frame-accurate compositor. renderFrame(g) draws global frame g as a pure
// function of the timeline, so frames can be rendered in any order.
'use strict';

const W = 1920, HGT = 1080, BAR = 138;
let TL, META, ANCH, FPS, H, BASE;

// ------------------------------------------------------------------ helpers
const clamp = (x, a = 0, b = 1) => Math.max(a, Math.min(b, x));
const sm = (t, a, b) => { if (b <= a) return t >= a ? 1 : 0; const u = clamp((t - a) / (b - a)); return u * u * (3 - 2 * u); };
const eo = (u) => 1 - Math.pow(1 - clamp(u), 3);
const eio = (u) => { u = clamp(u); return u < 0.5 ? 4 * u * u * u : 1 - Math.pow(-2 * u + 2, 3) / 2; };
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

const SVGP = (d, extra = '') => `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" ${extra}>${d}</svg>`;
const ICON = {
  speaker: SVGP('<path d="M6 5.5v13c0 1.4 2.7 2.5 6 2.5s6-1.1 6-2.5v-13"/><ellipse cx="12" cy="5.5" rx="6" ry="2.5"/>'),
  wave: SVGP('<path d="M3 12h1M7 8v8M11 4v16M15 7v10M19 10v4M22 12h-1"/>'),
  spark: SVGP('<path d="M12 3l1.8 5.2L19 10l-5.2 1.8L12 17l-1.8-5.2L5 10l5.2-1.8z"/><path d="M19 15l.7 1.8 1.8.7-1.8.7L19 20l-.7-1.8-1.8-.7 1.8-.7z"/>'),
  brain: SVGP('<path d="M9 4a3 3 0 0 0-3 3 3 3 0 0 0-2 5 3 3 0 0 0 2 5 3 3 0 0 0 3 3 2 2 0 0 0 2-2V6a2 2 0 0 0-2-2zM15 4a3 3 0 0 1 3 3 3 3 0 0 1 2 5 3 3 0 0 1-2 5 3 3 0 0 1-3 3 2 2 0 0 1-2-2V6a2 2 0 0 1 2-2z"/>'),
  home: SVGP('<path d="M3 11l9-7 9 7v9a1 1 0 0 1-1 1h-5v-6h-6v6H4a1 1 0 0 1-1-1z"/>'),
  bulb: SVGP('<path d="M9 18h6M10 21h4M12 3a6 6 0 0 0-3.5 10.9c.6.5 1 1.2 1 2V17h5v-1.1c0-.8.4-1.5 1-2A6 6 0 0 0 12 3z"/>'),
  ac: SVGP('<rect x="2" y="5" width="20" height="8" rx="2"/><path d="M6 10h12M7 16l-1 3M12 16v3M17 16l1 3"/>'),
  curtain: SVGP('<path d="M3 3h18M5 3v18c2-4 3-10 4.5-18M19 3v18c-2-4-3-10-4.5-18"/>'),
  vacuum: SVGP('<circle cx="12" cy="12" r="9"/><circle cx="12" cy="9" r="2.5"/>'),
  lamp: SVGP('<path d="M7 21h10M12 21v-8M8 3h8l3 8H5z"/>'),
  window: SVGP('<rect x="4" y="3" width="16" height="18" rx="1"/><path d="M12 3v18M4 12h16"/>'),
  music: SVGP('<path d="M9 18V5l11-2v13"/><circle cx="6" cy="18" r="3"/><circle cx="17" cy="16" r="3"/>'),
  alarm: SVGP('<circle cx="12" cy="13" r="8"/><path d="M12 9v4l2.5 2M5 3L2 6M19 3l3 3"/>'),
  cloud: SVGP('<path d="M7 18a4 4 0 0 1-.5-8A6 6 0 0 1 18 9a4.5 4.5 0 0 1-.5 9z"/>'),
  chat: SVGP('<path d="M21 12a8 8 0 0 1-11.6 7.1L4 20l1-4.6A8 8 0 1 1 21 12z"/>'),
  globe: SVGP('<circle cx="12" cy="12" r="9"/><path d="M3 12h18M12 3c2.5 2.7 3.8 5.7 3.8 9S14.5 18.3 12 21c-2.5-2.7-3.8-5.7-3.8-9S9.5 5.7 12 3z"/>'),
  puzzle: SVGP('<path d="M10 3h4v2.5a2 2 0 1 0 4 0V3h3v7h-2.5a2 2 0 1 0 0 4H21v7h-7v-2.5a2 2 0 1 0-4 0V21H3v-7h2.5a2 2 0 1 0 0-4H3V3z"/>'),
  bell: SVGP('<path d="M6 16v-5a6 6 0 0 1 12 0v5l2 2H4zM10 20a2 2 0 0 0 4 0"/>'),
  moon: SVGP('<path d="M20 14.5A8 8 0 1 1 9.5 4a6.5 6.5 0 0 0 10.5 10.5z"/>'),
  code: SVGP('<path d="M8 6l-6 6 6 6M16 6l6 6-6 6M14 4l-4 16"/>'),
  voice: SVGP('<rect x="9" y="3" width="6" height="11" rx="3"/><path d="M5 11a7 7 0 0 0 14 0M12 18v3"/>'),
  link: SVGP('<path d="M10 14a4 4 0 0 0 5.7 0l3-3a4 4 0 0 0-5.7-5.7l-1 1M14 10a4 4 0 0 0-5.7 0l-3 3a4 4 0 0 0 5.7 5.7l1-1"/>'),
};

// ------------------------------------------------------------------ data access
function shotById(id) { return TL.shots.find((s) => s.id === id); }
function line(shot, id) { return shot.lines.find((l) => l.id === id); }
function wordTime(lid, prefix) {
  const w = META[lid].words.find((w) => w.text.startsWith(prefix));
  return Math.max(0, w.t);
}

// Per-character times from the TTS word boundaries.
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

function envAt(lid, lt) {
  const e = META[lid].env;
  const i = Math.floor(lt * FPS);
  return i >= 0 && i < e.length ? e[i] : 0;
}

// ------------------------------------------------------------------ components
const LABEL = { user: '我', xiaoai: '小爱', xiaoqi: '小七' };
const WAKE = ['你好小七', '小爱同学', '小七'];

function bubble(parent, shot, lid, pos) {
  const ln = line(shot, lid);
  const role = META[lid].role;
  const b = div(`bubble ${role} ${role === 'xiaoqi' ? 'gborder' : ''}`, parent);
  const who = div('who', b);
  div('dot', who);
  el('span', null, who, LABEL[role]);
  const wave = div('wave', who);
  const bars = [];
  for (let i = 0; i < 9; i++) bars.push(el('i', null, wave));
  const txt = div('txt', b);
  const text = META[lid].text;
  const times = charTimes(lid);
  const wake = WAKE.find((w) => text.startsWith(w));
  const spans = [...text].map((ch, i) => {
    const s = el('span', null, txt, ch === ' ' ? '&nbsp;' : ch);
    if (wake && i < wake.length) s.style.color = role === 'user' && wake.includes('小爱') ? 'var(--cold)' : 'var(--warm-a)';
    return s;
  });
  if (pos.right !== undefined) { b.style.right = pos.right + 'px'; b.style.left = 'auto'; } else b.style.left = pos.left + 'px';
  b.style.bottom = pos.bottom + 'px';
  if (pos.maxw) b.style.maxWidth = pos.maxw + 'px';
  if (pos.dark) b.classList.add('dark');
  return {
    el: b, line: ln,
    update(t, hideAt = 1e9, extra = {}) {
      const lt = t - ln.t;
      const a = eo((lt + 0.3) / 0.35);
      const out = sm(t, hideAt - 0.35, hideAt);
      b.style.opacity = a * (1 - out);
      b.style.transform = `translateY(${(1 - a) * 24 + out * -12}px) scale(${0.94 + 0.06 * a})`;
      spans.forEach((s, i) => {
        const u = sm(lt, times[i] - 0.03, times[i] + 0.13);
        s.style.opacity = u;
        s.style.transform = `translateY(${(1 - u) * 8}px)`;
        s.style.filter = u < 1 ? `blur(${(1 - u) * 4}px)` : 'none';
      });
      const speaking = lt > -0.05 && lt < ln.dur;
      bars.forEach((bar, i) => {
        const e = speaking ? envAt(lid, lt - i * 0.025) : 0;
        const h = 4 + 18 * e * (0.55 + 0.45 * Math.abs(Math.sin(i * 1.9 + lt * 7)));
        bar.style.height = h.toFixed(1) + 'px';
      });
      if (extra.fail !== undefined) {
        const f = extra.fail;
        b.classList.toggle('fail', f > 0);
        const shake = f > 0 && f < 0.5 ? Math.sin(f * 60) * 10 * (1 - f / 0.5) : 0;
        b.style.transform += ` translateX(${shake}px)`;
        if (f > 0) b.style.filter = `saturate(${1 - 0.8 * clamp(f / 0.3)})`;
      }
    },
  };
}

// A device status chip with a pin on the 3D anchor and a leader line.
function chip(parent, svg, opts) {
  const pin = div(`pin ${opts.pin || ''}`, parent);
  const ring = div('ring', pin);
  const c = div(`chip ${opts.cls || ''} ${(opts.cls || '').includes('ai') ? 'gborder' : ''}`, parent);
  const ico = div('ico', c, ICON[opts.icon] || '');
  if (opts.iconColor) ico.style.color = opts.iconColor;
  const body = div(null, c);
  div(null, body, opts.text);
  if (opts.sub) div('sub2', body, opts.sub);
  const st = opts.state ? div('state', c, opts.state) : null;
  const ln = document.createElementNS('http://www.w3.org/2000/svg', 'line');
  ln.setAttribute('stroke', 'rgba(255,255,255,0.7)');
  ln.setAttribute('stroke-width', '2');
  svg.appendChild(ln);
  return {
    update(t, anchor, t0, t1 = 1e9, dim = 1) {
      const a = eo((t - t0) / 0.4) * (1 - sm(t, t1 - 0.3, t1)) * dim;
      const vis = anchor && anchor.ok ? 1 : 0;
      const ax = anchor ? anchor.x : -999, ay = anchor ? anchor.y : -999;
      const dx = opts.dx ?? 60, dy = opts.dy ?? -80;
      pin.style.left = ax + 'px'; pin.style.top = ay + 'px';
      pin.style.opacity = a * vis;
      pin.style.transform = `scale(${0.4 + 0.6 * eo((t - t0) / 0.25)})`;
      const r = clamp((t - t0) / 0.9);
      ring.style.opacity = (1 - r) * vis;
      ring.style.transform = `scale(${1 + r * 1.6})`;
      const w = c.offsetWidth, hh = c.offsetHeight;
      let cx = ax + dx, cy = ay + dy - hh / 2;
      if (dx < 0) cx -= w;
      cx = clamp(cx, 40, W - w - 40); cy = clamp(cy, 150, HGT - hh - 150);
      const slide = (1 - eo((t - t0 - 0.08) / 0.45)) * (dx < 0 ? -20 : 20);
      c.style.left = cx + slide + 'px'; c.style.top = cy + 'px';
      c.style.opacity = a * vis;
      const ex = dx < 0 ? cx + w : cx, ey = cy + hh / 2;
      const lu = eo((t - t0) / 0.3);
      ln.setAttribute('x1', ax); ln.setAttribute('y1', ay);
      ln.setAttribute('x2', lerp(ax, ex, lu)); ln.setAttribute('y2', lerp(ay, ey, lu));
      ln.setAttribute('opacity', a * vis * 0.8);
      if (st) {
        const s = eo((t - t0 - 0.35) / 0.3);
        st.style.transform = `scale(${s})`;
      }
    },
  };
}

function lineSvg(parent) {
  const s = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  s.setAttribute('class', 'lines');
  s.setAttribute('viewBox', `0 0 ${W} ${HGT}`);
  parent.appendChild(s);
  return s;
}

function painCard(parent, num, title) {
  const scrim = div('layer', parent);
  scrim.style.background = 'linear-gradient(90deg, rgba(0,0,0,0.62), rgba(0,0,0,0.25) 55%, rgba(0,0,0,0) 80%)';
  scrim.style.opacity = 0;
  const p = div('painCard', parent);
  const tag = div('tag', p, `<b>${num}</b><span>痛点</span>`);
  const ln = div('line', p);
  const t = div('t', p, title);
  const g1 = div('t ghost', p, title); g1.style.color = '#ff3b5c';
  const g2 = div('t ghost', p, title); g2.style.color = '#3bd1ff';
  return (t0, t, end) => {
    const a = eo((t - t0) / 0.5) * (1 - sm(t, end - 0.3, end));
    p.style.opacity = a;
    scrim.style.opacity = a;
    p.style.transform = `translateX(${(1 - eo((t - t0) / 0.6)) * -40}px)`;
    ln.style.width = 520 * eo((t - t0 - 0.1) / 0.6) + 'px';
    const gl = t - t0 > 0.05 && t - t0 < 0.45 ? 1 : 0;
    const j = Math.sin((t - t0) * 90);
    g1.style.opacity = gl * 0.7; g2.style.opacity = gl * 0.7;
    g1.style.transform = `translate(${6 * j}px, ${-2 * j}px)`;
    g2.style.transform = `translate(${-6 * j}px, ${2 * j}px)`;
    tag.style.opacity = eo((t - t0) / 0.3);
  };
}

function topTitle(parent, text, ai) {
  const d = div(`topTitle ${ai ? 'ai' : ''}`, parent);
  div(ai ? 'gborder' : null, d, text);
  return (t, a, b) => {
    const v = win(t, a, b, 0.45, 0.4);
    d.style.opacity = v;
    d.style.transform = `translateY(${(1 - eo((t - a) / 0.5)) * -16}px)`;
  };
}

function timeCard(parent, k, s) {
  const d = div('timeCard', parent);
  div('k', d, k);
  div('s', d, s);
  return (t, a, b) => {
    const v = win(t, a, b, 0.35, 0.45);
    d.style.opacity = v;
    d.style.letterSpacing = '0px';
    d.firstChild.style.letterSpacing = 20 + 14 * (1 - eo((t - a) / 1.2)) + 'px';
    d.style.filter = `blur(${(1 - v) * 8}px)`;
  };
}

// ------------------------------------------------------------------ shots
const SHOTS = {};

SHOTS.S02 = {
  build(root, shot) {
    const q = div('bigq', root);
    const text = '它，真的懂你吗？';
    const spans = [...text].map((c) => el('span', null, q, c));
    const ln = line(shot, 'N02');
    const times = charTimes('N02').slice(1);  // skip the leading 可
    return (t) => {
      q.style.opacity = 1 - sm(t, shot.frames / FPS - 0.35, shot.frames / FPS);
      spans.forEach((s, i) => {
        const u = sm(t - ln.t, times[i] - 0.05, times[i] + 0.25);
        s.style.opacity = u;
        s.style.transform = `translateY(${(1 - u) * 14}px)`;
        s.style.filter = `blur(${(1 - u) * 8}px)`;
      });
    };
  },
};

function painShot(userId, aiId, num, title) {
  return {
    build(root, shot) {
      const u = bubble(root, shot, userId, { right: 170, bottom: 600 });
      const x = bubble(root, shot, aiId, { left: 170, bottom: 300 });
      const card = painCard(root, num, title);
      const m = shot.marks;
      const end = shot.frames / FPS;
      return (t) => {
        u.update(t, m.card);
        x.update(t, m.card, { fail: t - m.fail });
        card(m.card, t, end + 0.2);
      };
    },
  };
}
SHOTS.S03 = painShot('U01', 'X01', '01', '只会听指令，听不懂你的意思');
SHOTS.S04 = painShot('U02', 'X02', '02', '聊过就忘，没有记忆');

const APPS = {
  mijia: { name: '米家', color: '#ff8a3d' },
  a: { name: '品牌 A', color: '#35d0c0' },
  b: { name: '品牌 B', color: '#a58bff' },
  c: { name: '品牌 C', color: '#4da3ff' },
};
const SILO = [
  ['pendant', 'bulb', '客厅灯', 'mijia', -50, -150],
  ['ac_living', 'ac', '客厅空调', 'mijia', 50, -110],
  ['ac_bed', 'ac', '卧室空调', 'mijia', 50, -100],
  ['curtain', 'curtain', '电动窗帘', 'a', 70, 110],
  ['floorlamp', 'lamp', '落地灯', 'a', -60, 150],
  ['vacuum', 'vacuum', '扫地机器人', 'b', 60, 80],
  ['desklamp', 'lamp', '台灯', 'c', -50, -130],
  ['balcony', 'window', '门窗传感器', 'c', -60, 140],
];

SHOTS.S05 = {
  build(root, shot) {
    const svg = lineSvg(root);
    const links = [];
    const chips = SILO.map(([anc, icon, name, app, dx, dy]) => {
      const A = APPS[app];
      const c = chip(root, svg, {
        icon, iconColor: A.color, dx, dy, pin: '', cls: 'small',
        text: `${name}<span style="margin-left:10px;padding:2px 9px;border-radius:8px;font-size:17px;background:${A.color}33;color:${A.color};border:1px solid ${A.color}88">${A.name}</span>`,
      });
      const x = div(null, root, '✕');
      css(x, { position: 'absolute', width: '34px', height: '34px', borderRadius: '50%', background: 'var(--pain)', color: '#300', display: 'grid', placeItems: 'center', fontWeight: 700, fontSize: '20px', opacity: 0 });
      if (app === 'mijia') {
        const l = document.createElementNS('http://www.w3.org/2000/svg', 'line');
        l.setAttribute('stroke', A.color); l.setAttribute('stroke-width', '3'); l.setAttribute('stroke-dasharray', '10 8');
        svg.appendChild(l);
        links.push([anc, l]);
      }
      return { anc, app, c, x };
    });
    const card = painCard(root, '03', '设备各自为政，非米家设备管不了');
    const m = shot.marks;
    const n03 = line(shot, 'N03');
    const tXiaoai = n03.t + wordTime('N03', '小');
    return (t, ctx) => {
      const dim = 1 - 0.65 * sm(t, m.card, m.card + 0.4);
      chips.forEach((ch, i) => {
        const a = ctx.anchor(ch.anc);
        ch.c.update(t, a, m.silos + i * 0.18, 1e9, dim);
        const k = ch.app === 'mijia' ? 0 : eo((t - tXiaoai - 0.1 - i * 0.06) / 0.3);
        if (a) css(ch.x, { left: a.x - 17 + 'px', top: a.y - 17 + 'px', opacity: k * dim * (a.ok ? 1 : 0), transform: `scale(${0.5 + 0.5 * k})` });
      });
      const sp = ctx.anchor('sp');
      links.forEach(([anc, l], i) => {
        const a = ctx.anchor(anc);
        const u = eo((t - tXiaoai - i * 0.08) / 0.5);
        if (!a || !sp) return;
        l.setAttribute('x1', sp.x); l.setAttribute('y1', sp.y);
        l.setAttribute('x2', lerp(sp.x, a.x, u)); l.setAttribute('y2', lerp(sp.y, a.y, u));
        l.setAttribute('opacity', u * dim);
        l.setAttribute('stroke-dashoffset', -t * 40);
      });
      card(m.card, t, 1e9);
    };
  },
};

SHOTS.S06 = {
  build(root, shot) {
    const c = div('collapse', root);
    const items = ['听不懂', '没记忆', '管不全'].map((s) => div(null, c, s));
    const m = shot.marks;
    return (t) => {
      const k = sm(t, m.collapse, m.collapse + 0.55);
      c.style.opacity = eo(t / 0.4) * (1 - sm(t, m.collapse + 0.35, m.collapse + 0.6));
      items.forEach((d, i) => {
        const a = eo((t - i * 0.18) / 0.4);
        const jit = t > m.collapse - 0.25 ? Math.sin(t * 97 + i * 13) * 14 * (1 - k) : 0;
        d.style.opacity = a;
        d.style.transform = `translate(${(1 - i) * 320 * k + jit}px, ${(1 - a) * 30}px) scale(${1 - 0.9 * k}, ${1 - 0.97 * k})`;
      });
    };
  },
  plateFilter(t, shot) {
    const m = shot.marks;
    return `blur(${4 + 10 * sm(t, 0, 0.6)}px) brightness(${0.55 - 0.45 * sm(t, m.collapse, m.collapse + 0.6)})`;
  },
};

SHOTS.S07 = {
  build(root, shot) {
    const c = div('titleCard', root);
    const logo = div('logo', c, 'Open-XiaoAI');
    const sweep = div('shine', logo, 'Open-XiaoAI');
    const sl = div('sl', c, '给小爱，换一颗 AI 大脑');
    const m = shot.marks;
    return (t) => {
      const a = eo((t - m.impact) / 0.7);
      c.style.opacity = a;
      logo.style.transform = `scale(${1.08 - 0.08 * a})`;
      logo.style.filter = `blur(${(1 - a) * 12}px) drop-shadow(0 0 30px rgba(255,120,120,0.35))`;
      sweep.style.backgroundPosition = `${lerp(100, 0, eio((t - m.impact - 0.25) / 1.3))}% 0`;
      sl.style.opacity = eo((t - m.impact - 0.45) / 0.6);
      sl.style.letterSpacing = 10 + 10 * (1 - eo((t - m.impact - 0.45) / 1.2)) + 'px';
    };
  },
};

SHOTS.S08 = {
  build(root, shot) {
    const mk = (side, wake, role, desc, icons) => {
      const s = div(`side ${side}`, root);
      div(side === 'r' ? 'wake gborder' : 'wake', s, wake);
      div('role', s, role);
      div('desc', s, desc);
      const row = div('icons', s);
      const items = icons.map(([ic, name]) => div(null, row, ICON[ic] + `<span>${name}</span>`));
      return { s, items };
    };
    const L = mk('l', '“小爱同学”', '原生小爱', '原有功能，一个不少',
      [['music', '听音乐'], ['alarm', '定闹钟'], ['cloud', '查天气'], ['home', '控米家']]);
    const R = mk('r', '“你好小七”', 'AI 管家', '会思考 · 有记忆 · 管全屋',
      [['chat', '聊天'], ['brain', '记忆'], ['globe', '联网'], ['spark', '全屋智能']]);
    L.items.forEach((d) => { d.style.color = 'var(--cold)'; });
    R.items.forEach((d) => { d.style.color = 'var(--warm-a)'; });
    // Labels sit at the top, icon rows at the bottom, the speakers in between.
    L.s.style.top = R.s.style.top = '96px';
    const u = bubble(root, shot, 'U03', { left: 1010, bottom: 520 });
    const q = bubble(root, shot, 'Q00', { left: 1010, bottom: 380 });
    const dv = div('divider', root);
    const m = shot.marks;
    const end = shot.frames / FPS;
    return (t) => {
      const k = eio((t * FPS + 10) / 26);
      const cut = lerp(100, 50, k);
      dv.style.left = (cut / 100) * W - 1.5 + 'px';
      dv.style.transform = `rotate(${Math.atan2(0.04 * W, HGT) * 180 / Math.PI}deg)`;
      dv.style.opacity = sm(k, 0.02, 0.2) * (1 - sm(t, end - 0.3, end + 0.2));
      [[L, m.left], [R, m.right]].forEach(([S, t0]) => {
        const a = eo((t - t0 + 0.1) / 0.5) * (1 - sm(t, end - 0.3, end + 0.2));
        S.s.style.opacity = a;
        S.s.style.transform = `translateY(${(1 - a) * -20}px)`;
        S.items.forEach((d, i) => {
          const b = eo((t - t0 - 0.5 - i * 0.12) / 0.4) * (1 - sm(t, end - 0.3, end + 0.2));
          d.style.opacity = b;
          d.style.transform = `translateY(${(1 - b) * 20}px)`;
          d.style.position = 'relative';
          d.style.top = '540px';
        });
      });
      u.update(t, end + 0.2);
      q.update(t, end + 0.2);
    };
  },
  split: true,
};

// Architecture diagram.
SHOTS.S09 = {
  build(root, shot) {
    const arch = div('arch', root);
    const svg = lineSvg(arch);
    const Y = 540;
    const nodes = [
      { k: 'voice', x: 230, icon: 'speaker', n: '小爱音箱', d: '常驻进程 · 监听对话' },
      { k: 'asr', x: 600, icon: 'wave', n: '语音识别', d: '自定义 ASR 服务' },
      { k: 'hermes', x: 985, icon: 'spark', n: 'Hermes', d: 'AI 智能体', cls: 'hermes', en: true },
      { k: 'ha', x: 1375, icon: 'home', n: 'Home Assistant', d: '全屋设备中枢', en: true },
    ];
    nodes.forEach((nd) => {
      const e = div(`node ${nd.cls || ''}`, arch);
      const ic = div('ico', e, ICON[nd.icon]);
      ic.style.color = nd.k === 'hermes' ? 'var(--warm-b)' : '#fff';
      div(`n ${nd.en ? 'en' : ''}`, e, nd.n);
      div('d', e, nd.d);
      if (nd.k === 'hermes') {
        const sc = div('subchips', e);
        nd.subs = ['大模型', '长期记忆', '技能', '联网搜索'].map((s) => div(null, sc, s));
      }
      if (nd.k === 'ha') {
        nd.badge = div('badge', e, '小米账号授权 · 自动同步');
        if (nd.n.length > 10) e.querySelector('.n').style.fontSize = '30px';
      }
      nd.el = e;
    });
    const groups = [
      { k: 'mijia', y: 330, name: '米家设备', color: '#ff8a3d',
        items: [['bulb', '灯'], ['ac', '空调'], ['speaker', '音箱'], ['window', '传感器']] },
      { k: 'other', y: 620, name: '其他品牌', color: '#35d0c0',
        items: [['curtain', '窗帘'], ['vacuum', '扫地机'], ['lamp', '台灯']] },
    ];
    groups.forEach((g) => {
      const e = div('devgroup', arch);
      const h = div('h', e, `<i style="background:${g.color};box-shadow:0 0 10px ${g.color}"></i>${g.name}`);
      const row = div('row', e);
      g.spans = g.items.map(([ic, n]) => { const s = el('span', null, row, ICON[ic] + n); s.style.color = '#fff'; s.querySelector('svg').style.color = g.color; return s; });
      css(e, { left: '1600px', top: g.y + 'px' });
      g.el = e;
    });
    const mkPath = (color) => {
      const p = document.createElementNS('http://www.w3.org/2000/svg', 'path');
      p.setAttribute('fill', 'none'); p.setAttribute('stroke', color); p.setAttribute('stroke-width', '3');
      p.setAttribute('stroke-linecap', 'round');
      svg.appendChild(p);
      const dots = [];
      for (let i = 0; i < 3; i++) {
        const c = document.createElementNS('http://www.w3.org/2000/svg', 'circle');
        c.setAttribute('r', '7'); c.setAttribute('fill', '#fff');
        c.setAttribute('style', `filter: drop-shadow(0 0 8px ${color})`);
        svg.appendChild(c); dots.push(c);
      }
      return { p, dots };
    };
    const m = shot.marks;
    const links = [
      { from: 'voice', to: 'asr', t0: m.n_asr, color: 'rgba(255,255,255,0.6)' },
      { from: 'asr', to: 'hermes', t0: m.n_hermes, color: 'rgba(255,180,92,0.8)' },
      { from: 'hermes', to: 'ha', t0: m.n_ha, color: 'rgba(255,111,145,0.8)' },
      { from: 'ha', to: 'mijia', t0: m.n_devices, color: '#ff8a3d' },
      { from: 'ha', to: 'other', t0: m.n_devices + 0.25, color: '#35d0c0' },
    ].map((l) => Object.assign(l, mkPath(l.color)));
    const nodeT = { voice: m.n_voice, asr: m.n_asr, hermes: m.n_hermes, ha: m.n_ha };
    const end = shot.frames / FPS;
    return (t) => {
      const box = {};
      nodes.forEach((nd) => {
        const a = eo((t - nodeT[nd.k] + 0.15) / 0.5) * (1 - sm(t, end - 0.35, end + 0.1));
        const w = nd.el.offsetWidth, h = nd.el.offsetHeight;
        css(nd.el, { left: nd.x - w / 2 + 'px', top: Y - h / 2 + 'px', opacity: a, transform: `translateY(${(1 - a) * 30}px) scale(${0.92 + 0.08 * a})` });
        box[nd.k] = { x: nd.x, y: Y, w, h };
        if (nd.subs) nd.subs.forEach((s, i) => { s.style.opacity = eo((t - m.n_think - i * 0.15) / 0.35); });
        if (nd.badge) {
          const b = eo((t - m.n_login) / 0.4);
          nd.badge.style.opacity = b * (1 - sm(t, end - 0.35, end));
          nd.badge.style.transform = `translateX(-50%) translateY(${(1 - b) * 10}px)`;
        }
      });
      groups.forEach((g, gi) => {
        const t0 = gi === 0 ? m.n_devices : m.n_devices + 0.25;
        const a = eo((t - t0) / 0.5) * (1 - sm(t, end - 0.35, end + 0.1));
        g.el.style.opacity = a;
        g.el.style.transform = `translateX(${(1 - a) * 30}px)`;
        const t1 = gi === 0 ? m.n_mijia : m.n_other;
        g.spans.forEach((s, i) => {
          const b = Math.max(eo((t - t0 - 0.2 - i * 0.1) / 0.3) * 0.5, eo((t - t1 - i * 0.12) / 0.3));
          s.style.opacity = b;
          const pop = t > t1 ? Math.exp(-(t - t1 - i * 0.12) * 5) : 0;
          s.style.transform = `scale(${1 + 0.15 * clamp(pop)})`;
        });
        box[g.k] = { x: 1600, y: g.y + g.el.offsetHeight / 2, w: 0, h: 0, left: true };
      });
      links.forEach((l) => {
        const A = box[l.from], B = box[l.to];
        const x1 = A.x + A.w / 2, y1 = A.y;
        const x2 = B.left ? B.x : B.x - B.w / 2, y2 = B.y;
        const mx = (x1 + x2) / 2;
        const d = `M${x1},${y1} C${mx},${y1} ${mx},${y2} ${x2},${y2}`;
        l.p.setAttribute('d', d);
        const len = l.p.getTotalLength();
        const u = eo((t - l.t0) / 0.5);
        l.p.setAttribute('stroke-dasharray', `${len}`);
        l.p.setAttribute('stroke-dashoffset', `${len * (1 - u)}`);
        const fade = 1 - sm(t, end - 0.35, end + 0.1);
        l.p.setAttribute('opacity', fade);
        l.dots.forEach((c, i) => {
          const ph = ((t - l.t0) * 0.7 + i / 3) % 1;
          const pt = l.p.getPointAtLength(len * ph);
          c.setAttribute('cx', pt.x); c.setAttribute('cy', pt.y);
          c.setAttribute('opacity', u >= 1 ? fade * Math.sin(ph * Math.PI) : 0);
        });
      });
    };
  },
  plateFilter() { return 'blur(9px) brightness(0.42) saturate(1.1)'; },
  plateScale: 1.06,
};

SHOTS.S10 = {
  build(root, shot) {
    const svg = lineSvg(root);
    const title = topTitle(root, '同一句话，它听懂了', true);
    const u = bubble(root, shot, 'U04', { left: 130, bottom: 640, dark: true });
    const q = bubble(root, shot, 'Q01', { right: 110, bottom: 150, maxw: 700, dark: true });
    const ac = chip(root, svg, { icon: 'ac', iconColor: 'var(--cold)', text: '客厅空调 · 26°C', sub: '已调高两度', state: '✓', dx: -60, dy: 150, pin: 'warm', cls: 'ai' });
    const rm = chip(root, svg, { icon: 'bell', iconColor: 'var(--warm-a)', text: '22:30 睡前提醒', sub: '已设置', state: '✓', dx: -170, dy: -30, pin: 'warm', cls: 'ai' });
    const m = shot.marks;
    const end = shot.frames / FPS;
    return (t, ctx) => {
      title(t, 0.1, line(shot, 'U04').t + 2.2);
      u.update(t, end + 0.3);
      q.update(t, end + 0.3);
      ac.update(t, ctx.anchor('ac_living'), m.ac + 0.25, end + 0.3);
      rm.update(t, ctx.anchor('sp'), m.remind, end + 0.3);
    };
  },
};

SHOTS.S11 = {
  build(root, shot) {
    const svg = lineSvg(root);
    const u = bubble(root, shot, 'U05', { right: 140, bottom: 700, dark: true });
    const q = bubble(root, shot, 'Q02', { left: 140, bottom: 130, dark: true });
    const lt = chip(root, svg, { icon: 'bulb', iconColor: '#ff8a3d', text: '客厅主灯 · 米家', sub: '已关闭', state: '✓', dx: 70, dy: 40, pin: 'warm', cls: 'ai' });
    const cu = chip(root, svg, { icon: 'curtain', iconColor: '#35d0c0', text: '电动窗帘 · 其他品牌', sub: '已拉上 · 经 Home Assistant', state: '✓', dx: -80, dy: 190, pin: 'warm', cls: 'ai' });
    const title = topTitle(root, '一句话，跨品牌设备一起控', true);
    const m = shot.marks;
    const end = shot.frames / FPS;
    const q2 = line(shot, 'Q02');
    return (t, ctx) => {
      u.update(t, end + 0.3);
      q.update(t, end + 0.3);
      lt.update(t, ctx.anchor('pendant'), m.light_off + 0.1, end + 0.3);
      cu.update(t, ctx.anchor('curtain'), m.curtain + 0.5, end + 0.3);
      title(t, q2.t + q2.dur - 0.6, end + 0.3);
    };
  },
};

SHOTS.S12 = {
  build(root, shot) {
    const svg = lineSvg(root);
    const tc = timeCard(root, '三天前', 'THREE DAYS AGO · 16:40');
    const u = bubble(root, shot, 'U06', { right: 130, bottom: 700, maxw: 760, dark: true });
    const q = bubble(root, shot, 'Q03', { left: 130, bottom: 150, dark: true });
    const mem = chip(root, svg, { icon: 'brain', iconColor: 'var(--warm-c)', text: '长期记忆 · 已保存', sub: '睡觉时空调 25°C', state: '✓', dx: 120, dy: -120, pin: 'warm', cls: 'ai' });
    const m = shot.marks;
    const end = shot.frames / FPS;
    return (t, ctx) => {
      tc(t, 0.0, line(shot, 'U06').t - 0.05);
      u.update(t, end + 0.3);
      q.update(t, end + 0.3);
      mem.update(t, ctx.anchor('sp'), m.memory + 0.1, end + 0.3);
    };
  },
  plateFilter(t, shot) {
    const b = 1 - sm(t, line(shot, 'U06').t - 0.6, line(shot, 'U06').t);
    return `blur(${b * 10}px) brightness(${1 - 0.45 * b})`;
  },
};

SHOTS.S13 = {
  build(root, shot) {
    const svg = lineSvg(root);
    const tc = timeCard(root, '今晚 23:10', 'TONIGHT');
    const u = bubble(root, shot, 'U07', { right: 150, bottom: 760 });
    const q = bubble(root, shot, 'Q04', { left: 120, bottom: 110, maxw: 980 });
    const c1 = chip(root, svg, { icon: 'bulb', iconColor: '#ff8a3d', text: '书房灯', sub: '已关闭', state: '✓', dx: 60, dy: -90, pin: 'warm', cls: 'ai' });
    const c2 = chip(root, svg, { icon: 'bulb', iconColor: '#ff8a3d', text: '客厅灯', sub: '已关闭', state: '✓', dx: 60, dy: -110, pin: 'warm', cls: 'ai' });
    const c3 = chip(root, svg, { icon: 'ac', iconColor: 'var(--cold)', text: '卧室空调 · 25°C', sub: '按三天前记住的偏好', state: '✓', dx: -70, dy: -110, pin: 'warm', cls: 'ai' });
    const c4 = chip(root, svg, { icon: 'window', iconColor: 'var(--warn)', text: '阳台窗户未关', sub: '门窗传感器', state: '!', dx: -90, dy: 120, pin: 'warn', cls: 'warn' });
    const m = shot.marks;
    const end = shot.frames / FPS;
    return (t, ctx) => {
      tc(t, 0.0, line(shot, 'U07').t - 0.05);
      u.update(t, m.night + 0.2);
      q.update(t, end + 0.3);
      c1.update(t, ctx.anchor('study_light'), m.study_off + 0.05, m.night + 0.6);
      c2.update(t, ctx.anchor('pendant'), m.living_off + 0.05, m.night + 0.6);
      c3.update(t, ctx.anchor('ac_bed'), m.ac25 - 0.1, end + 0.3);
      c4.update(t, ctx.anchor('balcony'), m.window - 0.1, end + 0.3);
    };
  },
  plateFilter(t, shot) {
    const b = 1 - sm(t, line(shot, 'U07').t - 0.6, line(shot, 'U07').t);
    return `blur(${b * 10}px) brightness(${1 - 0.45 * b})`;
  },
};

SHOTS.S14 = {
  build(root, shot) {
    const cards = [
      ['globe', '联网搜索', '“今天有什么科技新闻？”'],
      ['bell', '定时提醒', '“十点半提醒我睡觉”'],
      ['puzzle', '技能扩展', '一句“我睡觉了”，一键睡眠模式'],
      ['brain', '长期记忆', '记得你的习惯和偏好'],
      ['home', '跨品牌控制', '米家与其他品牌，统一调度'],
      ['voice', '原生小爱音色', '熟悉的声音，更聪明的大脑'],
    ].map(([ic, h, d], i) => {
      const c = div('mcard', root);
      div('ico', c, ICON[ic]);
      div('h', c, h);
      div('d', c, d);
      css(c, { left: 170 + (i % 3) * 540 + 'px', top: 200 + Math.floor(i / 3) * 290 + 'px' });
      return c;
    });
    const m = shot.marks;
    const times = [m.card0, m.card1, m.card2 + 0.25, m.card3, m.card3 + 0.15, m.card3 + 0.3];
    const order = [0, 1, 3, 2, 4, 5];
    const end = shot.frames / FPS;
    return (t) => {
      cards.forEach((c, i) => {
        const t0 = times[order.indexOf(i)] - 0.1;
        const a = eo((t - t0) / 0.6) * (1 - sm(t, end - 0.4, end + 0.1));
        c.style.opacity = a;
        c.style.transform = `perspective(1400px) translateZ(${(1 - a) * -260}px) rotateX(${(1 - a) * 18}deg) translateY(${(1 - a) * 40}px)`;
      });
    };
  },
  plateFilter() { return 'blur(14px) brightness(0.45) saturate(1.2)'; },
  plateScale: 1.08,
};

SHOTS.S16 = {
  build(root, shot) {
    const e = div('endCard', root);
    const glow = div('glow', e);
    const logo = div('logo', e, 'Open-XiaoAI');
    const tag = div('tag', e, '让小爱，成为你的贴身家庭管家');
    const stack = div('stack', e, '<b>小爱音箱</b>&nbsp;&nbsp;×&nbsp;&nbsp;<b>AI 大模型</b>&nbsp;&nbsp;×&nbsp;&nbsp;<b>Home Assistant</b>');
    const gh = div('gh', e, ICON.code + '<span>github.com/OwnDing/open-xiaoai</span>');
    const models = div('models', e, '支持机型：小爱音箱 Pro（LX06） · Xiaomi 智能音箱 Pro（OH2P）');
    const legal = div('legal', e, '开源项目，仅供学习研究 · 与小米集团无隶属或合作关系');
    const items = [[logo, 0.3], [tag, 1.0], [stack, 1.7], [gh, 2.3], [models, 2.8], [legal, 3.2]];
    return (t) => {
      glow.style.opacity = eo(t / 1.5) * (0.8 + 0.2 * Math.sin(t * 1.3));
      items.forEach(([d, t0]) => {
        const a = eo((t - t0) / 0.8);
        d.style.opacity = a;
        d.style.filter = `blur(${(1 - a) * 10}px)`;
        if (d !== gh) d.style.transform = `translateY(${(1 - a) * 18}px)`;
      });
      logo.style.letterSpacing = 6 + 12 * (1 - eo((t - 0.3) / 2.0)) + 'px';
    };
  },
  noPlate: true,
};

// ------------------------------------------------------------------ ring glow
// Mirrors ring_drive() in plates.py so the 2D bloom breathes with the 3D ring.
function ringLevel(shot, t, voice) {
  const idle = 2.6 + 0.9 * Math.sin(2 * Math.PI * t / 3.4);
  let listen = 0, speak = 0;
  const L = shot.lines;
  L.forEach((l, i) => {
    const end = l.t + l.dur;
    if (l.role === 'user') {
      const reply = L.slice(i + 1).find((m) => m.role === voice);
      if (!reply) return;
      listen = Math.max(listen, sm(t, l.t - 0.05, l.t + 0.25) * (1 - sm(t, reply.t, reply.t + 0.2)));
    } else if (l.role === voice && t >= l.t - 0.1 && t <= end + 0.3) {
      speak = Math.max(speak, envAt(l.id, t - l.t) * (1 - sm(t, end, end + 0.3)));
      listen = Math.max(listen, 0.55 * (1 - sm(t, end, end + 0.4)));
    }
  });
  return idle * (1 - listen) + listen * 6.0 + 9.0 * speak;
}

const GLOW = {  // shot -> [anchor, strength]
  S01: ['sp', 0.9], S02: ['sp', 0.35], S03: ['sp', 1], S04: ['sp', 0.8], S05: ['sp', 1.2],
  S07: ['st', 0.6], S10: ['sp', 1], S11: ['sp', 1], S12: ['sp', 0.3], S13: ['sp', 1.3], S15: ['sp', 2.4],
};

function drawGlow(it, g, anchor) {
  const cfg = GLOW[it.shot.id];
  if (!cfg) return;
  const a = anchor(cfg[0]);
  if (!a || !a.ok || !a.z) return;
  const t = (g - it.shot.start) / FPS;
  const warm = it.shot.act >= 2 ? (it.shot.id === 'S07' ? sm(t, it.shot.marks.impact - 0.05, it.shot.marks.impact + 0.25) : 1) : 0;
  const level = ringLevel(it.shot, t, warm > 0.5 ? 'xiaoqi' : 'xiaoai');
  const r = Math.max(14, (0.05 / a.z) * (a.lens / 36) * W);
  const k = clamp(level / 11) * cfg[1] * (it.w ?? 1);
  const col = warm > 0.5 ? '255, 140, 110' : '170, 205, 255';
  const core = stage.glowCore, halo = stage.glowHalo;
  css(core, { left: a.x - r * 1.6 + 'px', top: a.y - r * 1.6 + 'px', width: r * 3.2 + 'px', height: r * 3.2 + 'px', opacity: Math.min(1, k * 1.1),
    background: `radial-gradient(closest-side, rgba(${col}, 0.55), rgba(${col}, 0.18) 45%, rgba(${col}, 0) 100%)` });
  css(halo, { left: a.x - r * 6 + 'px', top: a.y - r * 6 + 'px', width: r * 12 + 'px', height: r * 12 + 'px', opacity: Math.min(1, k * 0.8),
    background: `radial-gradient(closest-side, rgba(${col}, 0.16), rgba(${col}, 0) 100%)` });
}

// ------------------------------------------------------------------ transitions
// Keyed by the incoming shot: [type, length in frames].
const TRANS = {
  S02: ['cross', 16], S03: ['cross', 16], S04: ['cross', 14], S05: ['cross', 22], S06: ['cut', 0],
  S07: ['black', 16], S08: ['cross', 20], S09: ['cross', 22], S10: ['cross', 20], S11: ['cross', 14],
  S12: ['white', 24], S13: ['black', 26], S14: ['cross', 20], S15: ['cross', 24], S16: ['black', 30],
};

// ------------------------------------------------------------------ subtitles
// Narration is split into cues of at most ~16 characters: sentences first,
// then clauses, timed from the TTS word boundaries.
const wlen = (str) => [...str].reduce((n, c) => n + (/[\x00-\x7f]/.test(c) ? 0.5 : 1), 0);
function subtitleCues() {
  const cues = [];
  for (const s of TL.shots) {
    for (const l of s.lines) {
      if (l.role !== 'narrator' || l.id === 'N02' || l.id === 'N11') continue;
      const text = META[l.id].text;
      const times = charTimes(l.id);
      const base = s.start / FPS + l.t;
      // Sentences, then clauses inside long sentences.
      const pieces = [];
      let start = 0;
      for (let i = 0; i < text.length; i++) {
        if ('。？！'.includes(text[i]) || i === text.length - 1) {
          const sent = [];
          let cs = start;
          for (let j = start; j <= i; j++) {
            if ('，、'.includes(text[j]) && text[j] === '，' || j === i) { sent.push([cs, j]); cs = j + 1; }
          }
          // Merge clauses while they stay short.
          const merged = [];
          for (const c of sent) {
            const last = merged[merged.length - 1];
            if (last && wlen(text.slice(last[0], c[1] + 1)) <= 16) last[1] = c[1];
            else merged.push([...c]);
          }
          if (wlen(text.slice(start, i + 1)) <= 16) pieces.push([start, i]); else pieces.push(...merged);
          start = i + 1;
        }
      }
      pieces.forEach(([a, b], k) => {
        const t0 = base + times[a];
        const t1 = k + 1 < pieces.length ? base + times[pieces[k + 1][0]] : base + l.dur + 0.35;
        const str = text.slice(a, b + 1).replace(/[。，、]+$/, '').trim();
        if (str) cues.push({ a: t0 - 0.12, b: t1, text: str });
      });
    }
  }
  return cues;
}
let CUES = [];

// ------------------------------------------------------------------ stage
const stage = {};
const shotUI = {};

window.init = function (data) {
  TL = data.timeline; META = data.meta; ANCH = data.anchors; FPS = TL.fps; H = TL.handle; BASE = data.plateBase;
  const s = document.getElementById('stage');
  stage.plates = div('layer', s); stage.plates.id = 'plates';
  stage.imgA = el('img', 'plate', stage.plates);
  stage.imgB = el('img', 'plate', stage.plates);
  // Split screen: each half is a clipped wrapper holding a shifted copy of its plate.
  stage.split = div('layer', stage.plates);
  stage.halfL = div('layer', stage.split);
  stage.halfR = div('layer', stage.split);
  stage.splitL = el('img', 'plate', stage.halfL);
  stage.splitR = el('img', 'plate', stage.halfR);
  stage.tint = div('layer', s); stage.tint.id = 'tint';
  stage.vig = div('layer', s); stage.vig.id = 'vignette';
  stage.glow = div('layer', s);
  stage.glow.style.mixBlendMode = 'screen';
  stage.glowHalo = div(null, stage.glow);
  stage.glowCore = div(null, stage.glow);
  for (const e of [stage.glowHalo, stage.glowCore]) css(e, { position: 'absolute', borderRadius: '50%' });
  stage.ui = div('layer', s);
  stage.subs = div('layer', s); stage.subs.id = 'subs';
  stage.sub = div('sub', stage.subs);
  stage.bars = div('layer', s);
  stage.barT = div('bar top', stage.bars);
  stage.barB = div('bar bot', stage.bars);
  stage.flash = div('layer', s); stage.flash.id = 'flash';
  stage.black = div('layer', s); stage.black.id = 'black';
  // Subtitles sit above the letterbox bars.
  stage.subs.style.zIndex = 5;
  CUES = subtitleCues();
  for (const shot of TL.shots) {
    const def = SHOTS[shot.id];
    const root = div('layer', stage.ui);
    root.style.display = 'none';
    shotUI[shot.id] = { root, def, update: def ? def.build(root, shot) : null };
  }
  return true;
};

function plateUrl(pid, frame) {
  return `${BASE[pid]}/${String(frame).padStart(4, '0')}.jpg`;
}
function plateFrame(shot, g) {
  const p = TL.plates[shot.plate];
  const f = H + (shot.plate_offset || 0) + (g - shot.start) + 1;
  return Math.max(1, Math.min(p.frames + 2 * H, f));
}

async function setImg(img, url) {
  if (img.dataset.src === url) return;
  img.dataset.src = url;
  img.src = url;
  try { await img.decode(); } catch (e) { /* missing frame: leave blank */ }
}

function anchorFn(shot, g) {
  const pid = shot.plate;
  const tbl = pid && ANCH[pid];
  const row = tbl && tbl[plateFrame(shot, g)];
  const scale = SHOTS[shot.id]?.plateScale || 1;
  return (name) => {
    if (!row || !row[name]) return null;
    const [x, y, z] = row[name];
    const px = (x - 0.5) * scale * W + W / 2, py = (y - 0.5) * scale * HGT + HGT / 2;
    return { x: px, y: py, z, lens: row._lens || 35, ok: z > 0 && x > -0.05 && x < 1.05 && y > -0.05 && y < 1.05 };
  };
}

function gtime(sid, mark) {
  const s = shotById(sid);
  return s.start / FPS + s.marks[mark];
}

// Which shots are visible at frame g and with what weight.
function activeShots(g) {
  const shots = TL.shots;
  let i = shots.findIndex((s) => g >= s.start && g < s.start + s.frames);
  if (i < 0) i = g < 0 ? 0 : shots.length - 1;
  const cur = shots[i];
  const res = [{ shot: cur, w: 1 }];
  let black = 0, flash = 0;
  const tr = (inc) => TRANS[inc.id] || ['cross', 16];
  // Incoming transition at the start of the current shot.
  if (i > 0) {
    const [type, len] = tr(cur);
    const d = g - cur.start;
    if (len > 0 && d < len / 2) {
      const w = sm(d + len / 2, 0, len);
      if (type === 'cross') { res[0].w = 1; res.unshift({ shot: shots[i - 1], w: 1, under: true }); res[1].w = w; }
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
  const { list, black, flash, cur } = activeShots(g);
  // ---- plates
  const imgs = [stage.imgA, stage.imgB];
  const loads = [];
  let slot = 0;
  stage.split.style.opacity = 0;
  for (const img of imgs) img.style.opacity = 0;
  for (const [li, it] of list.entries()) {
    const def = SHOTS[it.shot.id] || {};
    if (def.noPlate || !it.shot.plate) continue;
    const t = (g - it.shot.start) / FPS;
    const filter = def.plateFilter ? def.plateFilter(t, it.shot) : 'none';
    const scale = def.plateScale || 1;
    if (def.split) {
      const k = eio((g - it.shot.start + 10) / 26);
      const f = plateFrame(it.shot, g);
      loads.push(setImg(stage.splitL, plateUrl('P07', f)), setImg(stage.splitR, plateUrl('P07B', f)));
      const cut = lerp(100, 50, k);
      stage.halfL.style.clipPath = `polygon(0 0, ${cut + 2}% 0, ${cut - 2}% 100%, 0 100%)`;
      stage.halfR.style.clipPath = `polygon(${cut + 2}% 0, 100% 0, 100% 100%, ${cut - 2}% 100%)`;
      css(stage.splitL, { opacity: 1, transform: `translate(${-480 * k}px, ${60 * k}px) scale(${1 - 0.1 * k})` });
      css(stage.splitR, { opacity: 1, transform: `translate(${480 * k}px, ${60 * k}px) scale(${1 - 0.1 * k})` });
      stage.split.style.opacity = it.w;
      stage.split.style.zIndex = li + 1;
      continue;
    }
    const img = imgs[slot++ % 2];
    loads.push(setImg(img, plateUrl(it.shot.plate, plateFrame(it.shot, g))));
    css(img, { opacity: it.w, filter, transform: `scale(${scale})`, zIndex: li + 1 });
  }
  await Promise.all(loads);

  // ---- grade: cold before the reveal, warm after.
  const impact = gtime('S07', 'impact');
  const cold = 1 - sm(T, impact - 0.05, impact + 0.7);
  stage.plates.style.filter = `saturate(${1 - 0.5 * cold}) brightness(${1 - 0.02 * cold}) contrast(${1 + 0.06 * cold + 0.04})`;
  stage.tint.style.background = cold > 0.001
    ? `rgba(40, 95, 150, ${0.55 * cold})`
    : 'rgba(255, 150, 80, 0.12)';

  // ---- ring glow (strongest visible shot wins)
  stage.glowCore.style.opacity = 0; stage.glowHalo.style.opacity = 0;
  const gl = [...list].sort((a, b) => b.w - a.w)[0];
  if (gl && gl.shot.plate) drawGlow(gl, g, anchorFn(gl.shot, g));

  // ---- overlays
  for (const id in shotUI) shotUI[id].root.style.display = 'none';
  for (const it of list) {
    const ui = shotUI[it.shot.id];
    if (!ui.update) continue;
    ui.root.style.display = 'block';
    ui.root.style.opacity = it.under ? 1 - (list[list.length - 1].w || 0) : it.w;
    const t = (g - it.shot.start) / FPS;
    ui.update(t, { anchor: anchorFn(it.shot, g) });
  }

  // ---- letterbox
  const bars = 1 - eio((T - impact - 0.1) / 0.9);
  stage.barT.style.transform = `translateY(${-(1 - bars) * BAR}px)`;
  stage.barB.style.transform = `translateY(${(1 - bars) * BAR}px)`;

  // ---- narration subtitles
  let subOp = 0, subText = '';
  for (const c of CUES) {
    const v = win(T, c.a, c.b, 0.12, 0.12);
    if (v > subOp) { subOp = v; subText = c.text; }
  }
  if (stage.sub.textContent !== subText) stage.sub.textContent = subText;
  stage.sub.style.opacity = subOp;
  stage.sub.style.bottom = lerp(78, 46, bars) + 'px';

  // ---- fades
  const end = TL.frames / FPS;
  const open = 1 - sm(T, 0.2, 1.6);
  const close = sm(T, end - 1.0, end);
  const hit = T >= impact ? Math.exp(-(T - impact) * 6) : 0;
  stage.black.style.opacity = Math.max(black, open, close);
  stage.flash.style.opacity = Math.max(flash * 0.9, hit * 0.55);
  return true;
};
