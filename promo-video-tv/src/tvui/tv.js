// The TV's screens for 《遥控器退休了》. renderScreen(plate, screen, t) draws what that TV shows at
// plate time t (a pure function of the timeline), and reports what 小七 is reading ("eyes") and
// pressing ("clicks") on it, in screen pixels, for the compositor's overlays.
'use strict';

const W = 1920, H = 1080;
let TL, META, FPS, HAND;

// ------------------------------------------------------------------ helpers
const clamp = (x, a = 0, b = 1) => Math.max(a, Math.min(b, x));
const sm = (t, a, b) => { if (b <= a) return t >= a ? 1 : 0; const u = clamp((t - a) / (b - a)); return u * u * (3 - 2 * u); };
const eo = (u) => 1 - Math.pow(1 - clamp(u), 3);
const lerp = (a, b, u) => a + (b - a) * u;
const win = (t, a, b, fi = 0.2, fo = 0.2) => sm(t, a, a + fi) * (1 - sm(t, b - fo, b));
function rng(seed) { let s = (seed * 2654435761) >>> 0 || 1; return () => { s = (s * 1664525 + 1013904223) >>> 0; return s / 4294967296; }; }
function el(tag, cls, parent, html) {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (html !== undefined) e.innerHTML = html;
  if (parent) parent.appendChild(e);
  return e;
}
const div = (cls, parent, html) => el('div', cls, parent, html);
function css(e, o) { for (const k in o) e.style[k] = o[k]; }
const mmss = (s) => { s = Math.max(0, Math.floor(s)); return `${String(Math.floor(s / 60)).padStart(2, '0')}:${String(s % 60).padStart(2, '0')}`; };
function canvas(w, h) { const c = document.createElement('canvas'); c.width = w; c.height = h; return c; }

const SVG = (d, fill = 'none') => `<svg viewBox="0 0 24 24" fill="${fill}" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">${d}</svg>`;
const IC = {
  play: SVG('<path d="M7 4l13 8-13 8z"/>', 'currentColor'),
  qy: SVG('<path d="M8 5.5l10 6.5-10 6.5z" fill="#fff" stroke="none"/><path d="M15 3c2 0 4 1.5 4.5 3.5" stroke="#fff"/>'),
  note: SVG('<path d="M9 18V6l10-2v12"/><circle cx="6.5" cy="18" r="2.5" fill="#fff"/><circle cx="16.5" cy="16" r="2.5" fill="#fff"/>'),
  globe: SVG('<circle cx="12" cy="12" r="9"/><path d="M3 12h18M12 3c3 3.5 3 14.5 0 18M12 3c-3 3.5-3 14.5 0 18"/>'),
  live: SVG('<rect x="3" y="6" width="18" height="12" rx="2"/><path d="M8 3l4 3 4-3M10 10l4 2-4 2z"/>'),
  photo: SVG('<rect x="3" y="5" width="18" height="14" rx="2"/><circle cx="9" cy="10" r="2"/><path d="M21 16l-5-5-8 8"/>'),
  store: SVG('<path d="M5 8h14l-1 12H6zM9 8V6a3 3 0 0 1 6 0v2"/>'),
  gear: SVG('<circle cx="12" cy="12" r="3"/><path d="M12 2v3M12 19v3M4.2 4.2l2.1 2.1M17.7 17.7l2.1 2.1M2 12h3M19 12h3M4.2 19.8l2.1-2.1M17.7 6.3l2.1-2.1"/>'),
  search: SVG('<circle cx="11" cy="11" r="7"/><path d="M20 20l-4-4"/>'),
  mic: SVG('<rect x="9" y="3" width="6" height="11" rx="3"/><path d="M5 11a7 7 0 0 0 14 0M12 18v3"/>'),
  heart: SVG('<path d="M12 20s-7-4.4-7-10a4 4 0 0 1 7-2.6A4 4 0 0 1 19 10c0 5.6-7 10-7 10z"/>'),
  list: SVG('<path d="M8 6h12M8 12h12M8 18h12M4 6h.01M4 12h.01M4 18h.01"/>'),
  pause: SVG('<path d="M8 5v14M16 5v14" stroke-width="3.2"/>'),
  ff: SVG('<path d="M3 6l8 6-8 6zM12 6l8 6-8 6z"/>', 'currentColor'),
  wifi: SVG('<path d="M2 9a15 15 0 0 1 20 0M5 12.5a10 10 0 0 1 14 0M8.5 16a5 5 0 0 1 7 0M12 19.5h.01"/>'),
  moon: SVG('<path d="M20 14.5A8 8 0 1 1 9.5 4 6.5 6.5 0 0 0 20 14.5z"/>'),
  tab: SVG('<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M3 9h18"/>'),
  lock: SVG('<rect x="5" y="11" width="14" height="9" rx="2"/><path d="M8 11V8a4 4 0 0 1 8 0v3"/>'),
  wave: SVG('<path d="M3 12h1M7 8v8M11 4v16M15 7v10M19 10v4M22 12h-1"/>'),
};

// ------------------------------------------------------------------ painters: the drama and the artwork

// 《雾港》 episode 2: a harbour town at night in fog; a man waits under a lamp at the end of the pier.
function drawHarbor(g, w, h, t, o = {}) {
  const X = (u) => u * w, Y = (v) => v * h, S = h / 1080;
  const pan = o.pan ?? 0.02 * Math.sin(t / 9);
  const sky = g.createLinearGradient(0, 0, 0, Y(0.58));
  sky.addColorStop(0, '#07121e'); sky.addColorStop(0.55, '#16324a'); sky.addColorStop(1, '#4a6e7c');
  g.fillStyle = sky; g.fillRect(0, 0, w, h);
  // Moon behind the fog.
  const mx = X(0.74 - pan * 0.2), my = Y(0.2);
  let rg = g.createRadialGradient(mx, my, 0, mx, my, Y(0.22));
  rg.addColorStop(0, 'rgba(235,240,230,0.95)'); rg.addColorStop(0.08, 'rgba(220,230,225,0.75)');
  rg.addColorStop(0.2, 'rgba(160,190,200,0.22)'); rg.addColorStop(1, 'rgba(120,160,180,0)');
  g.fillStyle = rg; g.fillRect(0, 0, w, h);
  // Far hills.
  const hills = (base, amp, col, sh, seed) => {
    g.beginPath(); g.moveTo(0, h);
    for (let i = 0; i <= 60; i++) {
      const u = i / 60;
      const uu = u + sh;
      g.lineTo(X(u), Y(base - amp * (0.5 + 0.5 * Math.sin(uu * 7 + seed)) * (0.6 + 0.4 * Math.sin(uu * 17 + seed * 2))));
    }
    g.lineTo(w, h); g.closePath(); g.fillStyle = col; g.fill();
  };
  hills(0.52, 0.09, '#1d3a4c', pan * 0.3, 1.0);
  hills(0.55, 0.05, '#142a38', pan * 0.45, 2.3);
  // Town lights along the shore and their reflections.
  const r = rng(5);
  const lights = [];
  for (let i = 0; i < 90; i++) {
    const u = ((r() * 1.3 - 0.15 - pan * 0.55) % 1.3 + 1.3) % 1.3 - 0.15;
    lights.push({ u, v: 0.548 + r() * 0.014, s: (1.2 + r() * 2.2) * S, warm: r() < 0.8, ph: r() * 6.28 });
  }
  const water = g.createLinearGradient(0, Y(0.565), 0, h);
  water.addColorStop(0, '#203a48'); water.addColorStop(0.4, '#0d1c26'); water.addColorStop(1, '#04090d');
  g.fillStyle = water; g.fillRect(0, Y(0.563), w, h);
  for (const L of lights) {
    const a = 0.65 + 0.35 * Math.sin(t * 1.7 + L.ph);
    g.fillStyle = L.warm ? `rgba(255,205,140,${a})` : `rgba(200,225,255,${a})`;
    g.beginPath(); g.arc(X(L.u), Y(L.v), L.s, 0, 6.283); g.fill();
    for (let j = 1; j < 9; j++) {
      const yy = Y(0.57 + j * 0.011);
      const xx = X(L.u) + Math.sin(t * 2.2 + j * 1.3 + L.ph) * 4 * S;
      g.globalAlpha = a * 0.35 * (1 - j / 9);
      g.fillRect(xx - L.s * 1.5, yy, L.s * 3, 2 * S);
    }
    g.globalAlpha = 1;
  }
  // Harbour cranes with blinking red lights.
  g.strokeStyle = '#0b161f'; g.fillStyle = '#0b161f'; g.lineWidth = 5 * S;
  [[0.12, 0.25], [0.27, 0.21], [0.83, 0.27]].forEach(([u0, ht], i) => {
    const u = u0 - pan * 0.6, x = X(u), b = Y(0.56), top = Y(0.56 - ht);
    g.beginPath();
    g.moveTo(x - 30 * S, b); g.lineTo(x - 18 * S, top); g.moveTo(x + 30 * S, b); g.lineTo(x + 18 * S, top);
    g.moveTo(x - 60 * S, top); g.lineTo(x + 140 * S, top); g.moveTo(x - 18 * S, top + 30 * S); g.lineTo(x + 18 * S, top + 30 * S);
    g.moveTo(x, top); g.lineTo(x, top - 40 * S); g.lineTo(x + 140 * S, top);
    g.stroke();
    if (Math.sin(t * 2.6 + i * 2) > 0) {
      const lg = g.createRadialGradient(x, top - 40 * S, 0, x, top - 40 * S, 16 * S);
      lg.addColorStop(0, 'rgba(255,60,50,1)'); lg.addColorStop(1, 'rgba(255,60,50,0)');
      g.fillStyle = lg; g.fillRect(x - 20 * S, top - 60 * S, 40 * S, 40 * S); g.fillStyle = '#0b161f';
    }
  });
  // A small boat crossing with a lamp.
  const bu = ((0.15 + t * 0.006 - pan * 0.7) % 1.3 + 1.3) % 1.3 - 0.15;
  const bx = X(bu), by = Y(0.61);
  g.fillStyle = '#070e14';
  g.beginPath(); g.moveTo(bx - 70 * S, by); g.lineTo(bx + 80 * S, by); g.lineTo(bx + 60 * S, by + 16 * S); g.lineTo(bx - 55 * S, by + 16 * S); g.fill();
  g.fillRect(bx - 20 * S, by - 26 * S, 40 * S, 26 * S);
  rg = g.createRadialGradient(bx + 30 * S, by - 30 * S, 0, bx + 30 * S, by - 30 * S, 40 * S);
  rg.addColorStop(0, 'rgba(255,200,120,0.95)'); rg.addColorStop(1, 'rgba(255,200,120,0)');
  g.fillStyle = rg; g.fillRect(bx - 20 * S, by - 80 * S, 100 * S, 100 * S);
  // The pier in the foreground, a lamp post and the waiting man.
  g.fillStyle = '#05090c';
  g.beginPath(); g.moveTo(X(0.56), h); g.lineTo(X(0.7), Y(0.775)); g.lineTo(X(1.0), Y(0.75)); g.lineTo(w, h); g.fill();
  for (const [u, v, hh] of [[0.63, 0.86, 0.12], [0.72, 0.79, 0.07], [0.95, 0.77, 0.07]]) g.fillRect(X(u), Y(v - hh), 10 * S, Y(hh) + 40 * S);
  const lx = X(0.86), ly = Y(0.43);
  g.fillRect(lx - 4 * S, ly, 8 * S, Y(0.34));
  g.fillRect(lx - 4 * S, ly, 40 * S, 6 * S);
  const flick = 0.92 + 0.08 * Math.sin(t * 13) * Math.sin(t * 5.3);
  rg = g.createRadialGradient(lx + 34 * S, ly + 12 * S, 0, lx + 34 * S, ly + 12 * S, Y(0.3));
  rg.addColorStop(0, `rgba(255,214,150,${0.95 * flick})`); rg.addColorStop(0.08, `rgba(255,190,120,${0.5 * flick})`);
  rg.addColorStop(0.4, `rgba(255,170,100,${0.12 * flick})`); rg.addColorStop(1, 'rgba(255,170,100,0)');
  g.fillStyle = rg; g.fillRect(0, 0, w, h);
  const cone = g.createLinearGradient(0, ly, 0, Y(0.8));
  cone.addColorStop(0, `rgba(255,205,140,${0.35 * flick})`); cone.addColorStop(1, 'rgba(255,205,140,0)');
  g.fillStyle = cone;
  g.beginPath(); g.moveTo(lx + 28 * S, ly + 10 * S); g.lineTo(lx + 42 * S, ly + 10 * S); g.lineTo(lx + 170 * S, Y(0.8)); g.lineTo(lx - 110 * S, Y(0.8)); g.fill();
  // The man in a long coat, back to us, a rim of lamplight on his shoulder.
  const fx = X(0.815), fy = Y(0.775), fs = S * 1.0;
  g.fillStyle = '#020406';
  g.beginPath(); g.moveTo(fx - 26 * fs, fy); g.lineTo(fx - 20 * fs, fy - 120 * fs); g.quadraticCurveTo(fx, fy - 140 * fs, fx + 22 * fs, fy - 120 * fs); g.lineTo(fx + 28 * fs, fy); g.fill();
  g.beginPath(); g.arc(fx + 1 * fs, fy - 150 * fs, 15 * fs, 0, 6.283); g.fill();
  g.fillRect(fx - 26 * fs, fy - 168 * fs, 54 * fs, 6 * fs);
  g.fillRect(fx - 15 * fs, fy - 186 * fs, 32 * fs, 20 * fs);
  g.strokeStyle = `rgba(255,200,140,${0.55 * flick})`; g.lineWidth = 2.5 * fs;
  g.beginPath(); g.moveTo(fx + 22 * fs, fy - 120 * fs); g.lineTo(fx + 28 * fs, fy - 10 * fs); g.stroke();
  // Fog banks drifting across.
  const fr = rng(11);
  for (let i = 0; i < 8; i++) {
    const sp = 0.004 + fr() * 0.008;
    const u = ((fr() + t * sp) % 1.6 + 1.6) % 1.6 - 0.3, v = 0.42 + fr() * 0.36, rr = X(0.22 + fr() * 0.25);
    const a = 0.06 + fr() * 0.09;
    const fg = g.createRadialGradient(X(u), Y(v), 0, X(u), Y(v), rr);
    fg.addColorStop(0, `rgba(185,205,215,${a})`); fg.addColorStop(1, 'rgba(185,205,215,0)');
    g.fillStyle = fg; g.fillRect(X(u) - rr, Y(v) - rr, 2 * rr, 2 * rr);
  }
  const haze = g.createLinearGradient(0, Y(0.4), 0, Y(0.7));
  haze.addColorStop(0, 'rgba(150,175,190,0)'); haze.addColorStop(0.55, 'rgba(150,175,190,0.16)'); haze.addColorStop(1, 'rgba(150,175,190,0)');
  g.fillStyle = haze; g.fillRect(0, 0, w, h);
  if (!o.noVignette) {
    const vg = g.createRadialGradient(w / 2, h / 2, h * 0.4, w / 2, h / 2, h * 1.0);
    vg.addColorStop(0, 'rgba(0,0,0,0)'); vg.addColorStop(1, 'rgba(0,0,0,0.55)');
    g.fillStyle = vg; g.fillRect(0, 0, w, h);
  }
}

// 《雾港》 episode 3: a rainy alley under neon signs; someone walks away under an umbrella.
function drawRain(g, w, h, t) {
  const X = (u) => u * w, Y = (v) => v * h, S = h / 1080;
  const bg = g.createLinearGradient(0, 0, 0, h);
  bg.addColorStop(0, '#0a0610'); bg.addColorStop(0.6, '#1a0f1e'); bg.addColorStop(1, '#07050a');
  g.fillStyle = bg; g.fillRect(0, 0, w, h);
  // Alley walls in perspective, a glow at the far end.
  const far = g.createRadialGradient(X(0.5), Y(0.5), 0, X(0.5), Y(0.5), X(0.25));
  far.addColorStop(0, 'rgba(255,150,90,0.35)'); far.addColorStop(1, 'rgba(255,150,90,0)');
  g.fillStyle = far; g.fillRect(0, 0, w, h);
  g.fillStyle = '#0c0810';
  g.beginPath(); g.moveTo(0, 0); g.lineTo(X(0.42), Y(0.36)); g.lineTo(X(0.42), Y(0.6)); g.lineTo(0, h); g.fill();
  g.beginPath(); g.moveTo(w, 0); g.lineTo(X(0.58), Y(0.36)); g.lineTo(X(0.58), Y(0.6)); g.lineTo(w, h); g.fill();
  // Windows on the walls.
  const wr = rng(3);
  for (let i = 0; i < 26; i++) {
    const side = i % 2 ? 1 : -1, d = wr();
    const u = 0.5 + side * (0.1 + d * 0.36), v = 0.2 + wr() * 0.3;
    if (wr() < 0.55) continue;
    g.fillStyle = `rgba(255,${170 + wr() * 60 | 0},110,${0.25 + 0.4 * wr()})`;
    g.fillRect(X(u), Y(v + (u - 0.5) * 0.1 * side), 18 * S * (0.5 + d), 26 * S * (0.5 + d));
  }
  const signs = [
    { txt: '茶', x: 0.16, y: 0.25, c: '255,70,95', s: 120 },
    { txt: '夜宵', x: 0.76, y: 0.2, c: '50,220,255', s: 96 },
    { txt: '旅馆', x: 0.87, y: 0.44, c: '255,120,220', s: 80, flick: true },
    { txt: '面', x: 0.3, y: 0.42, c: '255,180,70', s: 78 },
  ];
  g.textAlign = 'center'; g.textBaseline = 'middle';
  for (const s of signs) {
    const on = s.flick ? (Math.sin(t * 9) * Math.sin(t * 2.3) > -0.3 ? 1 : 0.25) : 1;
    g.font = `600 ${s.s * S}px "PingFang SC"`;
    g.shadowColor = `rgba(${s.c},${0.9 * on})`; g.shadowBlur = 40 * S;
    g.fillStyle = `rgba(${s.c},${on})`;
    g.fillText(s.txt, X(s.x), Y(s.y));
    g.lineWidth = 4 * S; g.strokeStyle = `rgba(${s.c},${0.8 * on})`;
    const tw = g.measureText(s.txt).width + 50 * S;
    g.strokeRect(X(s.x) - tw / 2, Y(s.y) - s.s * S * 0.75, tw, s.s * S * 1.5);
    g.shadowBlur = 0;
    // Reflections on the wet ground.
    const rg = g.createLinearGradient(0, Y(0.62), 0, h);
    rg.addColorStop(0, `rgba(${s.c},${0.32 * on})`); rg.addColorStop(1, `rgba(${s.c},0)`);
    g.fillStyle = rg;
    g.filter = `blur(${22 * S}px)`;
    g.fillRect(X(s.x) - tw * 0.3, Y(0.64), tw * 0.6, Y(0.36));
    g.filter = 'none';
  }
  // Wet street, a figure with an umbrella walking away.
  const ground = g.createLinearGradient(0, Y(0.6), 0, h);
  ground.addColorStop(0, 'rgba(30,20,35,0.5)'); ground.addColorStop(1, 'rgba(5,4,8,0.2)');
  g.fillStyle = ground; g.fillRect(0, Y(0.6), w, Y(0.4));
  const walk = (t * 0.012) % 0.6;
  const px = X(0.5 + 0.02 * Math.sin(t * 0.7)), py = Y(0.8 - walk * 0.25), ps = S * (1.2 - walk * 0.8);
  g.fillStyle = '#030205';
  g.beginPath(); g.ellipse(px, py - 150 * ps, 70 * ps, 26 * ps, 0, Math.PI, 0); g.fill();
  g.fillRect(px - 2 * ps, py - 150 * ps, 4 * ps, 40 * ps);
  g.beginPath(); g.moveTo(px - 24 * ps, py); g.lineTo(px - 20 * ps, py - 110 * ps); g.lineTo(px + 20 * ps, py - 110 * ps); g.lineTo(px + 24 * ps, py); g.fill();
  g.beginPath(); g.arc(px, py - 122 * ps, 13 * ps, 0, 6.283); g.fill();
  g.strokeStyle = 'rgba(255,130,200,0.5)'; g.lineWidth = 2 * ps;
  g.beginPath(); g.ellipse(px, py - 150 * ps, 70 * ps, 26 * ps, 0, Math.PI, 0); g.stroke();
  // Rain streaks and ripples.
  const rr = rng(17);
  g.strokeStyle = 'rgba(200,210,255,0.28)'; g.lineWidth = 1.6 * S;
  g.beginPath();
  for (let i = 0; i < 320; i++) {
    const x0 = rr() * 1.1, sp = 1.4 + rr() * 0.8, ph = rr();
    const v = ((ph + t * sp) % 1.15) - 0.08;
    const x = X(x0 - v * 0.06);
    g.moveTo(x, Y(v)); g.lineTo(x - 6 * S, Y(v) + 46 * S);
  }
  g.stroke();
  for (let i = 0; i < 26; i++) {
    const u = rr(), v = 0.66 + rr() * 0.32, ph = ((t * 1.3 + rr()) % 1);
    g.strokeStyle = `rgba(220,200,255,${0.35 * (1 - ph)})`; g.lineWidth = 1.5 * S;
    g.beginPath(); g.ellipse(X(u), Y(v), 40 * S * ph, 9 * S * ph, 0, 0, 6.283); g.stroke();
  }
  const vg = g.createRadialGradient(w / 2, h / 2, h * 0.35, w / 2, h / 2, h);
  vg.addColorStop(0, 'rgba(0,0,0,0)'); vg.addColorStop(1, 'rgba(0,0,0,0.6)');
  g.fillStyle = vg; g.fillRect(0, 0, w, h);
}

function harborArt(w, h, t = 3.0, o = {}) { const c = canvas(w, h); drawHarbor(c.getContext('2d'), w, h, t, o); return c; }

// Generic poster: a gradient sky, a motif, the title in big type.
function poster(title, sub, c1, c2, motif, seed, bare = false) {
  const w = 360, h = 504, c = canvas(w, h), g = c.getContext('2d');
  if (title === '雾港') {
    const wide = canvas(Math.round(w * 2.2), h);
    drawHarbor(wide.getContext('2d'), wide.width, h, 3.5, { pan: 0, noVignette: true });
    g.drawImage(wide, w * 1.05, 0, w, h, 0, 0, w, h);
  } else {
    const gr = g.createLinearGradient(0, 0, w * 0.4, h);
    gr.addColorStop(0, c1); gr.addColorStop(1, c2);
    g.fillStyle = gr; g.fillRect(0, 0, w, h);
    const r = rng(seed);
    g.fillStyle = 'rgba(255,255,255,0.85)';
    if (motif === 'sun') {
      const rg = g.createRadialGradient(w * 0.62, h * 0.32, 0, w * 0.62, h * 0.32, w * 0.42);
      rg.addColorStop(0, 'rgba(255,240,210,0.95)'); rg.addColorStop(0.3, 'rgba(255,200,150,0.5)'); rg.addColorStop(1, 'rgba(255,200,150,0)');
      g.fillStyle = rg; g.fillRect(0, 0, w, h);
    }
    if (motif === 'mount' || motif === 'sun') {
      for (let k = 0; k < 3; k++) {
        g.fillStyle = `rgba(0,0,0,${0.25 + 0.2 * k})`;
        g.beginPath(); g.moveTo(0, h);
        for (let i = 0; i <= 20; i++) g.lineTo(w * i / 20, h * (0.55 + 0.1 * k) - h * 0.12 * r() * (1 - k * 0.2));
        g.lineTo(w, h); g.fill();
      }
    }
    if (motif === 'city') {
      for (let i = 0; i < 18; i++) {
        const bw = 14 + r() * 30, bh = 60 + r() * 200, x = r() * w;
        g.fillStyle = `rgba(0,0,0,${0.35 + 0.3 * r()})`; g.fillRect(x, h * 0.75 - bh, bw, bh + h);
        g.fillStyle = 'rgba(255,220,150,0.7)';
        for (let j = 0; j < 6; j++) if (r() < 0.4) g.fillRect(x + 4, h * 0.75 - bh + 10 + j * 22, 4, 6);
      }
    }
    if (motif === 'stars') {
      for (let i = 0; i < 120; i++) { g.fillStyle = `rgba(255,255,255,${r()})`; g.fillRect(r() * w, r() * h * 0.7, 2, 2); }
      g.strokeStyle = 'rgba(255,255,255,0.5)'; g.lineWidth = 2; g.beginPath(); g.arc(w * 0.5, h * 1.1, w * 0.75, Math.PI * 1.1, Math.PI * 1.9); g.stroke();
    }
    if (motif === 'rail') {
      g.strokeStyle = 'rgba(255,255,255,0.5)'; g.lineWidth = 3;
      g.beginPath(); g.moveTo(w * 0.3, h); g.lineTo(w * 0.48, h * 0.45); g.moveTo(w * 0.7, h); g.lineTo(w * 0.52, h * 0.45); g.stroke();
      for (let i = 0; i < 9; i++) { const v = 0.48 + i * i * 0.0068; g.beginPath(); g.moveTo(w * (0.47 - (v - 0.45) * 0.4), h * v); g.lineTo(w * (0.53 + (v - 0.45) * 0.4), h * v); g.stroke(); }
    }
    if (motif === 'wave') {
      for (let k = 0; k < 7; k++) {
        g.strokeStyle = `rgba(255,255,255,${0.12 + 0.05 * k})`; g.lineWidth = 3; g.beginPath();
        for (let i = 0; i <= 40; i++) g.lineTo(w * i / 40, h * (0.55 + k * 0.05) + 10 * Math.sin(i * 0.5 + k));
        g.stroke();
      }
    }
  }
  if (bare) return c.toDataURL('image/jpeg', 0.9);
  const sh = g.createLinearGradient(0, h * 0.55, 0, h);
  sh.addColorStop(0, 'rgba(0,0,0,0)'); sh.addColorStop(1, 'rgba(0,0,0,0.78)');
  g.fillStyle = sh; g.fillRect(0, 0, w, h);
  g.fillStyle = '#fff'; g.textAlign = 'center'; g.textBaseline = 'alphabetic';
  g.shadowColor = 'rgba(0,0,0,0.6)'; g.shadowBlur = 16;
  const fs = title.length <= 2 ? 92 : title.length <= 3 ? 74 : 56;
  g.font = `600 ${fs}px "PingFang SC"`;
  g.fillText(title, w / 2, h * 0.86);
  g.font = '400 24px "PingFang SC"'; g.fillStyle = 'rgba(255,255,255,0.8)';
  g.fillText(sub, w / 2, h * 0.94);
  return c.toDataURL('image/jpeg', 0.9);
}

function cover(c1, c2, c3, seed, size = 400) {
  const c = canvas(size, size), g = c.getContext('2d'), r = rng(seed);
  const gr = g.createLinearGradient(0, 0, size, size);
  gr.addColorStop(0, c1); gr.addColorStop(1, c2);
  g.fillStyle = gr; g.fillRect(0, 0, size, size);
  for (let i = 0; i < 6; i++) {
    const x = r() * size, y = r() * size, rr = size * (0.15 + r() * 0.35);
    const rg = g.createRadialGradient(x, y, 0, x, y, rr);
    rg.addColorStop(0, c3); rg.addColorStop(1, 'rgba(0,0,0,0)');
    g.globalAlpha = 0.5 + 0.4 * r(); g.fillStyle = rg; g.fillRect(0, 0, size, size);
  }
  g.globalAlpha = 1;
  g.strokeStyle = 'rgba(255,255,255,0.35)'; g.lineWidth = size * 0.006;
  for (let i = 0; i < 4; i++) { g.beginPath(); g.arc(size * 0.5, size * 0.5, size * (0.18 + i * 0.07), r() * 6, r() * 6 + 2.5); g.stroke(); }
  return c.toDataURL('image/jpeg', 0.9);
}

// A bowl of braised pork for the recipe results.
function dish(w, h, seed = 1) {
  const c = canvas(w, h), g = c.getContext('2d'), r = rng(seed);
  const wood = g.createLinearGradient(0, 0, w, h);
  wood.addColorStop(0, '#6b4428'); wood.addColorStop(1, '#3d2414');
  g.fillStyle = wood; g.fillRect(0, 0, w, h);
  for (let i = 0; i < 20; i++) { g.fillStyle = `rgba(0,0,0,${0.05 + 0.08 * r()})`; g.fillRect(0, r() * h, w, 2 + r() * 4); }
  const cx = w * 0.5, cy = h * 0.55, rx = w * 0.36, ry = h * 0.36;
  g.fillStyle = 'rgba(0,0,0,0.35)'; g.beginPath(); g.ellipse(cx + 10, cy + 16, rx, ry, 0, 0, 6.283); g.fill();
  g.fillStyle = '#f3efe8'; g.beginPath(); g.ellipse(cx, cy, rx, ry, 0, 0, 6.283); g.fill();
  g.fillStyle = '#7a2e12'; g.beginPath(); g.ellipse(cx, cy, rx * 0.8, ry * 0.78, 0, 0, 6.283); g.fill();
  for (let i = 0; i < 14; i++) {
    const a = r() * 6.283, d = Math.sqrt(r()) * 0.6;
    const x = cx + Math.cos(a) * rx * d, y = cy + Math.sin(a) * ry * d, s = w * (0.07 + r() * 0.03);
    g.fillStyle = '#5e1d08'; g.beginPath(); g.roundRect(x - s, y - s * 0.8, 2 * s, 1.6 * s, s * 0.35); g.fill();
    g.fillStyle = '#a3471c'; g.beginPath(); g.roundRect(x - s * 0.9, y - s * 0.75, 1.8 * s, 0.7 * s, s * 0.3); g.fill();
    g.fillStyle = 'rgba(255,230,190,0.75)'; g.beginPath(); g.ellipse(x - s * 0.3, y - s * 0.5, s * 0.35, s * 0.12, -0.3, 0, 6.283); g.fill();
  }
  for (let i = 0; i < 16; i++) {
    g.fillStyle = r() < 0.5 ? '#4caf3a' : '#7fd35a';
    g.beginPath(); g.ellipse(cx + (r() - 0.5) * rx * 1.2, cy + (r() - 0.5) * ry * 1.1, 6, 3, r() * 3, 0, 6.283); g.fill();
  }
  return c.toDataURL('image/jpeg', 0.9);
}

// ------------------------------------------------------------------ catalogue
const SHOWS = [
  ['雾港', '全 32 集', '#1a3446', '#0b1620', 'harbor', 1],
  ['长街灯火', '全 40 集', '#7a3b1c', '#1f0d08', 'city', 2],
  ['北岸来信', '全 24 集', '#36506b', '#0f1a26', 'wave', 3],
  ['第七站', '全 18 集', '#4d2a5e', '#140a1c', 'rail', 4],
  ['白夜行舟', '全 36 集', '#2f5a52', '#0a1a17', 'mount', 5],
  ['云上的家', '全 30 集', '#b46a52', '#3a1e22', 'sun', 6],
];
const MOVIES = [['远航', '电影 · 2026', '#2a3f73', '#0b1024', 'stars', 7], ['归途', '电影 · 2025', '#8a5a2b', '#24150a', 'sun', 8]];
const RESULTS = {
  W: [['王冠', '电视剧 · 全 40 集', 2], ['晚歌', '电影 · 2024', 8], ['雾港', '电视剧 · 全 32 集', 0], ['无归', '纪录片 · 6 集', 4]],
  WG: [['雾港', '电视剧 · 全 32 集', 0], ['王冠', '电视剧 · 全 40 集', 2], ['晚歌', '电影 · 2024', 8], ['无归', '纪录片 · 6 集', 4]],
};
const KEYS = ['ABCDEF', 'GHIJKL', 'MNOPQR', 'STUVWX', 'YZ1234', '567890'];
const SONGS = [['晚风慢慢', '林小舟'], ['港口的灯', '苏念'], ['雾里的信', '陈远'], ['第七个夏天', '小鹿乐队'], ['慢一点回家', '周屿'], ['月光停靠', '南风']];
const LYRICS = ['晚风慢慢吹过窗台', '灯一盏一盏亮起来', '你说今天不赶时间', '我们就慢一点回来', '路口的猫在等夜', '桌上的茶还在冒热'];
const ART = {};

// ------------------------------------------------------------------ pages
const PAGES = {};
let STAGE;
function page(name, cls, build) {
  const root = div(`page ${cls}`, STAGE);
  const api = build(root) || {};
  PAGES[name] = { root, ...api };
}
function eyeable(e, label) { e.dataset.eye = label || e.textContent.trim().slice(0, 20); return e; }

function appTile(parent, label, icon, color) {
  const t = div('tile', parent);
  const ic = div('ic', t, IC[icon]); ic.style.background = color; ic.style.color = '#fff';
  eyeable(div(null, t, label));
  t.press = div('press', t);
  return t;
}
const APPS = [['奇异果', 'qy', '#14b85a'], ['网易云音乐', 'note', '#e33b3b'], ['浏览器', 'globe', '#2f6df6'], ['电视直播', 'live', '#f08a24'],
  ['相册', 'photo', '#8b5cf6'], ['应用商店', 'store', '#0fb5ae'], ['设置', 'gear', '#6b7280']];

function buildLauncher(root) {
  const top = div('topbar', root, `<div style="display:flex;gap:16px;align-items:center"><span style="width:30px;height:30px;color:#9cc8ff">${IC.moon}</span><span>18°</span></div>`);
  const r = div('r', top);
  div(null, r, `<span style="width:34px;height:34px;display:inline-block">${IC.wifi}</span>`);
  const clock = div('clock', r, '21:36');
  const hero = div('hero', root); css(hero, { left: '80px', top: '130px', width: '1180px', height: '560px' });
  hero.appendChild(harborArt(1180, 560, 3.2));
  div('shade', hero);
  const tx = div('txt', hero);
  div('chip', tx, '独家热播');
  eyeable(div('t', tx, '雾港'));
  eyeable(div('s', tx, '悬疑 · 剧情 · 全 32 集 · 每晚 20:00 更新'));
  const sides = [[MOVIES[0], '电影 · 星海里的一次远航'], [SHOWS[3], '新剧 · 末班车上的陌生人']].map(([s, cap], i) => {
    const c = div('side-card', root); css(c, { left: '1300px', top: `${130 + i * 295}px`, width: '540px', height: '265px' });
    const im = el('img', null, c); im.src = ART[s[0]];
    im.style.objectPosition = '50% 30%';
    eyeable(div('cap', c, `${s[0]}<small>${cap}</small>`), s[0]);
    return c;
  });
  eyeable(div('row-label', root, '我的应用')).style.cssText += 'left:84px;top:738px';
  const tiles = div('tiles', root); css(tiles, { left: '80px', top: '800px' });
  const T = APPS.map(([l, ic, c]) => appTile(tiles, l, ic, c));
  return {
    tiles: T, clock, sides,
    update(st) {
      clock.textContent = st.clock || '21:36';
      T.forEach((t, i) => {
        const f = st.focus === i;
        t.classList.toggle('focus', f);
        t.style.transform = f ? 'scale(1.1)' : 'none';
        t.press.style.background = `rgba(255,255,255,${f ? 0.5 * (st.flash || 0) : 0})`;
      });
    },
  };
}

function vbar(root, active) {
  const bar = div('vbar', root);
  const lg = div('logo', bar, `<i>${IC.qy}</i>`); eyeable(div(null, lg, '奇异果'));
  const tabs = ['搜索', '推荐', '电视剧', '电影', '综艺', '少儿', '纪录片'].map((n, i) => {
    const t = eyeable(div(`tab ${i === active ? 'on' : ''}`, bar, (i === 0 ? IC.search : '') + `<span>${n}</span>`), n);
    return t;
  });
  return tabs;
}

function buildVHome(root) {
  const tabs = vbar(root, 2);
  const hero = div('hero', root); css(hero, { left: '80px', top: '150px', width: '1760px', height: '380px' });
  hero.appendChild(harborArt(1760, 380, 5.0));
  div('shade', hero);
  const tx = div('txt', hero); tx.style.bottom = '44px';
  div('chip', tx, '今晚更新');
  eyeable(div('t', tx, '雾港')).style.fontSize = '84px';
  eyeable(div('s', tx, '第 2 集 · 雾里的那封信'));
  eyeable(div('row-label', root, '热播电视剧')).style.cssText += 'left:84px;top:566px';
  const row = div('posters', root); css(row, { left: '80px', top: '620px' });
  const P = SHOWS.map((s, i) => {
    const p = div('poster', row);
    const im = div('im', p); el('img', null, im).src = ART[s[0]];
    if (i < 2) div('badge', im, i === 0 ? '独播' : 'VIP');
    eyeable(div('tt', p, s[0])); div('mt', p, s[1]);
    return p;
  });
  return {
    tabs, posters: P,
    update(st) {
      tabs.forEach((t, i) => t.classList.toggle('focus', st.nav === i));
    },
  };
}

function buildVSearch(root) {
  vbar(root, 0);
  const f = div('field', root, IC.search);
  const txt = eyeable(div(null, f, ''), '搜索框');
  const caret = div('caret', f);
  const ph = div('ph', f, '输入片名首字母');
  div('hint', root, '支持首字母、全拼搜索');
  const kb = div('kb', root);
  const K = KEYS.map((row) => [...row].map((ch) => div('k', kb, ch)));
  const kb2 = div('kb2', root); div('k', kb2, '清空'); div('k', kb2, '删除');
  const head = div('res-h', root, '全部结果<small></small>');
  const hot = div('hot', root, SHOWS.slice(0, 5).map((s, i) => `<div><b>${i + 1}</b>${s[0]}</div>`).join(''));
  const grid = div('results', root);
  const cards = [0, 1, 2, 3].map(() => {
    const c = div('rcard', grid);
    const im = div('im', c); const img = el('img', null, im);
    const body = div(null, c);
    const tt = div('tt', body); const mt = div('mt', body);
    const play = div('play', body, IC.play.replace('<svg', '<svg style="width:26px;height:26px"') + '<span>播放</span>');
    play.press = div('press', play);
    return { c, img, tt, mt, play };
  });
  return {
    field: f, cards, keys: K,
    update(st) {
      const text = st.text || '';
      txt.textContent = text;
      ph.style.display = text ? 'none' : 'block';
      caret.style.opacity = st.caret ? (Math.sin(st.t * 7) > 0 ? 1 : 0) : 0;
      K.forEach((row, r) => row.forEach((k, c) => k.classList.toggle('focus', !!st.kb && st.kb[0] === r && st.kb[1] === c)));
      const res = text ? (text.length >= 2 || /[一-龥]/.test(text) ? RESULTS.WG : RESULTS.W) : null;
      hot.style.display = res ? 'none' : 'block';
      grid.style.display = res ? 'grid' : 'none';
      head.querySelector('small').textContent = res ? `“${text}” · 4 个结果` : '';
      head.firstChild.textContent = res ? '全部结果' : '热门搜索';
      if (res) cards.forEach((cd, i) => {
        const [n, m] = res[i];
        if (cd.img.dataset.n !== n) { cd.img.src = ART[n]; cd.img.dataset.n = n; }
        cd.tt.textContent = n; cd.mt.textContent = m;
        cd.c.classList.toggle('focus', st.res === i && !st.playFocus);
        cd.play.classList.toggle('focus', st.res === i && !!st.playFocus);
        eyeable(cd.tt, n);
        cd.play.press.style.background = `rgba(255,255,255,${st.res === i ? 0.5 * (st.flash || 0) : 0})`;
      });
    },
  };
}

function buildVDetail(root) {
  const back = div('back', root); back.appendChild(harborArt(1920, 1080, 7.0));
  div('shade', root);
  eyeable(div('t', root, '雾港'));
  eyeable(div('meta', root, '<b>9.1</b>2026 · 悬疑 / 剧情 · 全 32 集'), '9.1 分 · 全 32 集');
  eyeable(div('syn', root, '一座终年起雾的港城，一桩二十年前的旧案。退休的老港务员每晚守在码头，等一封迟到了二十年的信。'), '简介');
  const btns = div('btns', root);
  const B = [IC.play.replace('<svg', '<svg style="width:30px;height:30px"') + '<span>播放 第1集</span>', IC.list.replace('<svg', '<svg style="width:30px;height:30px"') + '<span>选集</span>',
    IC.heart.replace('<svg', '<svg style="width:30px;height:30px"') + '<span>收藏</span>'].map((h) => { const b = div('btn', btns, h); eyeable(b, b.textContent); b.press = div('press', b); return b; });
  eyeable(div('eps-l', root, '选集 · 全 32 集'));
  const eps = div('eps', root);
  const E = Array.from({ length: 12 }, (_, i) => eyeable(div('ep', eps, String(i + 1))));
  return {
    btns: B, eps: E,
    update(st) {
      B.forEach((b, i) => { b.classList.toggle('focus', st.btn === i); b.press.style.background = `rgba(255,255,255,${st.btn === i ? 0.5 * (st.flash || 0) : 0})`; });
      E.forEach((e, i) => e.classList.toggle('focus', st.ep === i));
    },
  };
}

const EP_LEN = [0, 2716, 2706, 2731];
function buildPlayer(root) {
  const cv = el('canvas', 'fill', root); cv.width = W; cv.height = H;
  const g = cv.getContext('2d');
  const gt = div('pl-grad-t', root), gb = div('pl-grad-b', root);
  const title = eyeable(div('pl-title', root, ''), '雾港 第2集');
  const prog = div('pl-prog', root);
  const bar = div('bar', prog), fill = div('fill', bar), knob = div('knob', bar);
  const tm = div('tm', prog);
  const panel = div('pl-panel', root);
  div('l', panel, '选集 · 雾港');
  const peps = div('eps', panel);
  const E = Array.from({ length: 12 }, (_, i) => eyeable(div('ep', peps, String(i + 1))));
  const toast = div('pl-toast', root);
  const vol = div('pl-vol', root);
  const vbar_ = div('bar', vol), vfill = div('fill', vbar_), vn = div('n', vol);
  const pause = div('pl-pause', root, IC.pause);
  const seek = div('pl-seek', root, `${IC.ff}<span></span>`);
  return {
    title, eps: E, panel,
    update(st) {
      if (st.ep >= 3) drawRain(g, W, H, st.sec); else drawHarbor(g, W, H, st.sec);
      const ov = Math.max(st.titleK || 0, st.progK || 0);
      gt.style.opacity = ov; gb.style.opacity = Math.max(st.progK || 0, 0);
      title.innerHTML = `雾港 · 第${st.ep}集<small>${['', '码头的灯', '雾里的那封信', '雨夜长街'][st.ep] || ''}</small>`;
      title.dataset.eye = `雾港 第${st.ep}集`;
      title.style.opacity = st.titleK || 0;
      prog.style.opacity = st.progK || 0;
      const L = EP_LEN[st.ep] || 2700;
      fill.style.width = `${(100 * st.sec) / L}%`; knob.style.left = `${(100 * st.sec) / L}%`;
      tm.innerHTML = `${mmss(st.sec)}<span> / ${mmss(L)}</span>`;
      panel.style.opacity = st.panelK || 0;
      panel.style.transform = `translateY(${(1 - eo(st.panelK || 0)) * 80}px)`;
      E.forEach((e, i) => { e.classList.toggle('focus', st.epFocus === i); e.classList.toggle('cur', st.ep === i + 1); });
      toast.style.opacity = st.toast ? st.toast.k : 0;
      if (st.toast) toast.innerHTML = st.toast.html;
      vol.style.opacity = st.vol ? st.vol.k : 0;
      if (st.vol) { vfill.style.height = `${(100 * st.vol.v) / 50}%`; vn.textContent = String(Math.round(st.vol.v)); }
      pause.style.opacity = st.pauseK || 0;
      seek.style.opacity = st.seek ? st.seek.k : 0;
      if (st.seek) seek.querySelector('span').textContent = st.seek.text;
    },
  };
}

function musicSide(root, on) {
  const s = div('m-side', root);
  div('m-logo', s, `<i>${IC.note}</i><span>网易云音乐</span>`);
  div('m-menu', s, ['推荐', '我的', '排行榜', '歌手', '电台'].map((n, i) => `<div class="${i === on ? 'on' : ''}">${n}</div>`).join(''));
}
function buildMHome(root) {
  musicSide(root, 0);
  eyeable(div('m-h', root, '推荐'));
  const tiles = div('m-tiles', root);
  const daily = div('m-tile', tiles); daily.style.background = 'linear-gradient(150deg, #f05a4f, #b8233f 60%, #6d1236)';
  div('date', daily, '24');
  eyeable(div('lb', daily, '每日推荐<small>根据你的口味 · 每天 6:00 更新</small>'), '每日推荐');
  daily.press = div('press', daily);
  const fm = div('m-tile', tiles); fm.style.background = 'linear-gradient(150deg, #3a6bd6, #1f2f6e)';
  eyeable(div('lb', fm, '私人 FM<small>猜你喜欢</small>'), '私人 FM');
  const nt = div('m-tile', tiles); nt.style.background = 'linear-gradient(150deg, #2f8c7a, #123a3a)';
  eyeable(div('lb', nt, '晚安轻音乐<small>歌单 · 128 首</small>'), '晚安轻音乐');
  const row = div('m-row', root);
  [['夜里开车听的歌', 11], ['港风老歌', 12], ['雨天咖啡馆', 13], ['钢琴与白噪音', 14], ['周末慢时光', 15]].forEach(([n, s], i) => {
    const c = div('m-card', row); el('img', null, div('im', c)).src = cover(['#5b3a8c', '#c0563a', '#3a6b8c', '#2a2a2a', '#8c7a3a'][i], '#111', 'rgba(255,220,180,0.9)', s, 260);
    eyeable(div('tt', c, n));
  });
  return {
    daily,
    update(st) { daily.classList.toggle('focus', !!st.focus); daily.style.outline = st.focus ? '5px solid #fff' : 'none'; daily.press.style.background = `rgba(255,255,255,${0.45 * (st.flash || 0)})`; },
  };
}
function buildMList(root) {
  musicSide(root, 0);
  const h = div('m-list-h', root);
  el('img', null, div('cov', h)).src = ART.daily;
  const tx = div(null, h);
  eyeable(div('t', tx, '每日推荐'));
  div('s', tx, '10 月 24 日 · 根据你的口味生成 · 30 首');
  const acts = div('acts', tx);
  const all = eyeable(div('m-btn red', acts, IC.play.replace('<svg', '<svg style="width:28px;height:28px"') + '<span>播放全部</span>'), '播放全部');
  all.press = div('press', all);
  div('m-btn', acts, IC.heart.replace('<svg', '<svg style="width:28px;height:28px"') + '<span>收藏</span>');
  const list = div('m-songs', root);
  const rows = SONGS.map(([n, a], i) => { const r = div('m-song', list, `<span class="n">${String(i + 1).padStart(2, '0')}</span><span>${n}</span><span class="a">${a}</span>`); eyeable(r, n); return r; });
  return {
    all,
    update(st) { all.classList.toggle('focus', !!st.focus); all.press.style.background = `rgba(255,255,255,${0.45 * (st.flash || 0)})`; rows[0].classList.toggle('cur', !!st.cur); },
  };
}
function buildMPlayer(root) {
  const bg = div('bg', root); el('img', null, bg).src = ART.song;
  const disc = div('m-disc', root);
  el('img', null, div('cov', disc)).src = ART.song;
  const now = div('m-now', root);
  eyeable(div('t', now, SONGS[0][0])); div('a', now, `${SONGS[0][1]} · 每日推荐`);
  const ly = div('m-lyr', root);
  const L = LYRICS.map((l) => div(null, ly, l));
  const pr = div('m-prog', root); const pf = div('fill', pr); const tm = div('tm', pr, '<span></span><span>03:52</span>');
  return {
    update(st) {
      disc.style.transform = `rotate(${st.sec * 14}deg)`;
      const cur = Math.floor(st.sec / 2.6) % L.length;
      L.forEach((l, i) => l.classList.toggle('cur', i === cur));
      pf.style.width = `${(100 * st.sec) / 232}%`;
      tm.firstChild.textContent = mmss(st.sec);
    },
  };
}

function bTabs(root, title) {
  div('b-tabs', root, `<div class="b-tab"><span style="width:24px;height:24px;display:inline-block;color:#2f6df6">${IC.globe}</span>${title}</div>`);
}
function buildBHome(root) {
  bTabs(root, '新标签页');
  const addr = div('b-addr', root, IC.search);
  const txt = eyeable(div(null, addr, '搜索或输入网址'), '搜索或输入网址');
  const caret = div('caret', addr);
  addr.press = div('press', addr); addr.press.style.borderRadius = '37px';
  const home = div('b-home', root);
  div('logo', home, '搜索');
  div('box', home, `${IC.search}<span>搜索网页、图片、视频</span>`);
  const q = div('b-quick', home);
  [['视频', '#ef4444'], ['新闻', '#3b82f6'], ['地图', '#10b981'], ['天气', '#f59e0b'], ['菜谱', '#8b5cf6'], ['书签', '#6b7280']].forEach(([n, c]) => { div(null, q, `<i style="background:${c}"></i>${n}`); });
  return {
    addr,
    update(st) {
      addr.classList.toggle('focus', !!st.focus);
      txt.textContent = st.text || '搜索或输入网址';
      txt.style.color = st.text ? '#1d1f23' : '#8a9099';
      caret.style.opacity = st.focus ? (Math.sin(st.t * 7) > 0 ? 1 : 0) : 0;
      caret.style.order = st.text ? 3 : 1;
      addr.press.style.background = `rgba(47,109,246,${0.25 * (st.flash || 0)})`;
    },
  };
}
function buildBRes(root) {
  bTabs(root, '红烧肉怎么做 - 网页搜索');
  div('b-addr', root, `${IC.lock}<span style="color:#1d1f23">红烧肉怎么做</span>`);
  const load = div('b-load', root);
  const res = div('b-res', root);
  div('sbar', res, `${IC.search}<span>红烧肉怎么做</span>`);
  div('stabs', res, '<span class="on">网页</span><span>图片</span><span>视频</span><span>菜谱</span><span>资讯</span>');
  const items = div('b-items', res);
  const R = [
    ['家常菜谱 › 红烧肉', '红烧肉的家常做法，肥而不腻、入口即化（附详细步骤图）', '五花肉切块冷水下锅焯水，冰糖小火炒出糖色，下肉翻炒上色，加生抽、老抽、料酒和热水，小火炖 1 小时，大火收汁……', 21],
    ['美食百科 › 本帮菜', '正宗红烧肉怎么做？记住这 3 个窍门，色泽红亮不发柴', '窍门一：选三层肥瘦相间的五花肉；窍门二：糖色要炒到琥珀色；窍门三：一次加足热水，中途不揭锅……', 22],
    ['视频 › 厨房小白', '10 分钟学会红烧肉 · 跟着做零失败', '全程跟拍，从选肉到收汁，新手也能一次成功。', 23],
  ].map(([u, h, p, s]) => {
    const it = div('b-item', items);
    const tx = div('tx', it);
    div('u', tx, u); eyeable(div('h', tx, h), h.slice(0, 12)); div('p', tx, p);
    el('img', null, div('th', it)).src = dish(230, 150, s);
    return it;
  });
  const card = div('b-card', res);
  el('img', null, div('im', card)).src = dish(620, 300, 9);
  const bd = div('bd', card);
  eyeable(div('t', bd, '红烧肉')); div('s', bd, '家常菜 · 约 80 分钟 · 难度 ★★');
  div('h2', bd, '食材');
  div('ing', bd, ['五花肉 500 克', '冰糖 30 克', '生抽', '老抽', '料酒', '葱姜', '八角'].map((x) => `<span>${x}</span>`).join(''));
  div('h2', bd, '步骤');
  el('ol', null, bd, ['五花肉切块，冷水下锅焯水', '冰糖小火炒出糖色', '下肉翻炒，裹匀糖色', '加调料和热水，小火炖 60 分钟', '大火收汁，撒葱花'].map((x) => `<li>${x}</li>`).join(''));
  return {
    update(st) {
      const k = st.load ?? 1;
      load.style.width = `${100 * eo(k)}%`; load.style.opacity = k < 1 ? 1 : 0;
      R.forEach((it, i) => { it.style.opacity = sm(k, 0.25 + 0.15 * i, 0.45 + 0.15 * i); });
      card.style.opacity = sm(k, 0.4, 0.7);
    },
  };
}

function buildBrand(root, o) {
  const b = div('brand', root);
  const bg = div('bg', b); bg.style.background = o.bg;
  div('bt', b, `${o.title}<span style="float:right;margin-left:900px;font-family:'Avenir Next';font-weight:500;opacity:0.8">21:36</span>`).style.color = o.ink;
  const grid = div('grid', b);
  grid.style.gridTemplateColumns = o.cols.map((c) => c + 'px').join(' ');
  o.cells.forEach(([h, c, label, art], i) => {
    const e = div('cell', grid);
    css(e, { height: h + 'px', background: c, position: 'relative', overflow: 'hidden' });
    if (art) { const im = el('img', null, e); im.src = ART[art + '_bare']; css(im, { position: 'absolute', inset: 0, width: '100%', height: '100%', objectFit: 'cover', opacity: 0.85 }); }
    const g = div(null, e, label);
    css(g, { position: 'absolute', left: '26px', bottom: '20px', fontSize: '34px', fontWeight: 600, letterSpacing: '3px', color: '#fff', textShadow: '0 2px 12px rgba(0,0,0,0.6)' });
  });
  const v = div('voice', b, `<i style="background:${o.accent};color:#fff">${o.icon}</i><span>${o.prompt}</span>`);
  return { update(st) { v.style.opacity = st.voice || 0; v.style.transform = `translateX(-50%) translateY(${(1 - eo(st.voice || 0)) * 40}px)`; } };
}

// ------------------------------------------------------------------ flows: what each TV shows, per plate

const OFF = { layers: [], power: 0 };
let CUR = null;   // plate being rendered (for marks)
function M(name) {
  const mk = CUR.marks;
  if (name in mk) return mk[name];
  const hits = Object.keys(mk).filter((k) => k.endsWith('.' + name));
  if (hits.length !== 1) throw new Error(`${CUR.id}: mark ${name}: ${hits.length} matches`);
  return mk[hits[0]];
}
const L = (p, st = {}, o = 1) => ({ p, st, o });
const ripple = (t, t0) => (t >= t0 && t < t0 + 0.75 ? (t - t0) / 0.75 : null);
const flash = (t, t0) => (t >= t0 ? Math.exp(-(t - t0) * 9) : 0);

// Fade between consecutive states: list of [t0, layer]; each new layer fades in over `fade` s.
function seq(t, steps, fade = 0.22) {
  let i = -1;
  for (let k = 0; k < steps.length; k++) if (t >= steps[k][0]) i = k;
  if (i < 0) return [];
  const cur = steps[i][1];
  const k = sm(t, steps[i][0], steps[i][0] + fade);
  if (i > 0 && k < 1 && steps[i - 1][1]) return [{ ...steps[i - 1][1], o: 1 }, { ...cur, o: k }];
  return [cur];
}

function boot(t, t0, dur = 0.65) {
  // power: black -> boot glow -> content.
  return { power: sm(t, t0, t0 + 0.12), boot: win(t, t0, t0 + dur, 0.15, 0.3) };
}

// The 小七 run of "开电视，我想看《雾港》第二集", as screen states at times a..f.
function xiaoqiRun(t, T, eyesOn) {
  const r = { eyes: [], clicks: [] };
  const P = (name) => PAGES[name];
  const ep1 = (tt) => ({ ep: 1, sec: Math.max(0, tt - T.play) + 1, titleK: win(tt, T.play + 0.1, T.ep2, 0.2, 0.15), progK: 0 });
  const st2 = (tt) => ({ ep: 2, sec: Math.max(0, tt - T.ep2) + 0.5, titleK: win(tt, T.ep2 + 0.05, T.ep2 + 4.2, 0.2, 0.6), progK: win(tt, T.ep2, T.ep2 + 4.2, 0.2, 0.6) * 0.9 });
  const steps = [
    [T.on + 0.45, L('launcher', { focus: 3 })],
    [T.app, L('vhome', {})],
    [T.search, L('vsearch', { text: '雾港', res: 0, playFocus: true, flash: flash(t, T.play - 0.25) })],
    [T.play, L('player', ep1(t))],
    [T.ep2, L('player', st2(t))],
  ];
  r.layers = seq(t, steps);
  // Inside the episode panel, before episode 2 starts.
  if (t >= T.ep && t < T.ep2) {
    const st = ep1(t);
    st.panelK = sm(t, T.ep, T.ep + 0.2);
    st.epFocus = t < T.ep + (T.ep2 - T.ep) * 0.45 ? 0 : 1;
    r.layers = [L('player', st)];
  }
  if (t >= T.ep2 && t < T.ep2 + 0.3) {
    const st = st2(t); st.panelK = 1 - sm(t, T.ep2, T.ep2 + 0.3); st.epFocus = 1;
    r.layers = [L('player', st)];
  }
  Object.assign(r, boot(t, T.on));
  if (t < T.on) r.power = 0;
  // Clicks: 小七 presses the app tile and 播放; eyes read before acting and check the episode.
  const c1 = ripple(t, T.app - 0.3); if (c1 !== null && t < T.app) r.clicks.push({ el: P('launcher').tiles[0], k: c1 });
  const c2 = ripple(t, T.play - 0.25); if (c2 !== null && t < T.play) r.clicks.push({ el: P('vsearch').cards[0].play, k: c2 });
  if (eyesOn) {
    const e = (el, a, b) => { const k = win(t, a, b, 0.12, 0.25); if (k > 0) r.eyes.push({ el, k }); };
    e(P('launcher').tiles[0], T.app - 0.65, T.app);
    e(P('vsearch').cards[0].tt, T.search + 0.15, T.play);
    e(P('vsearch').cards[0].play, T.search + 0.3, T.play);
    e(P('player').eps[1], T.ep + 0.15, T.ep2);
  }
  const ek = win(t, T.verify - 0.15, T.verify + (eyesOn ? 2.2 : 1.4), 0.15, 0.4);
  if (ek > 0 && t >= T.ep2) r.eyes.push({ el: P('player').title, k: ek, verify: true });
  return r;
}

function pressRun(t, presses) {
  // Replay the remote presses through the TV's menus.
  const st = { page: 'launcher', lf: 3, nav: null, kb: null, text: '', res: null, btn: 0, ep: null, pt: -9, load: -9 };
  for (const [pt, key] of presses) {
    if (pt > t) break;
    st.pt = pt;
    if (st.page === 'launcher') {
      if (key === 'left') st.lf = Math.max(0, st.lf - 1); else if (key === 'right') st.lf = Math.min(6, st.lf + 1);
      else if (key === 'ok') { st.page = 'vhome'; st.load = pt; }
    } else if (st.page === 'vhome') {
      if (key === 'up') st.nav = 2; else if (key === 'left') st.nav = Math.max(0, st.nav - 1);
      else if (key === 'ok') { st.page = 'vsearch'; st.kb = [0, 0]; st.load = pt; }
    } else if (st.page === 'vsearch') {
      if (st.res === null) {
        if (key === 'down') st.kb[0]++; else if (key === 'up') st.kb[0]--; else if (key === 'left') st.kb[1]--;
        else if (key === 'right') { if (st.kb[1] === 5) { st.res = 0; st.kb = null; } else st.kb[1]++; } else if (key === 'ok') st.text += KEYS[st.kb[0]][st.kb[1]];
      } else if (key === 'ok') { st.page = 'vdetail'; st.load = pt; st.btn = 0; }
    } else if (st.page === 'vdetail') {
      if (key === 'down') { st.btn = null; st.ep = 0; } else if (key === 'right') st.ep++; else if (key === 'left') st.ep--;
      else if (key === 'ok') { st.page = 'player'; st.load = pt; st.epn = st.ep + 1; }
    }
  }
  const fl = flash(t, st.pt) * 0.6;
  const map = {
    launcher: { focus: st.lf, flash: fl },
    vhome: { nav: st.nav },
    vsearch: { text: st.text, kb: st.kb, res: st.res, caret: true, t },
    vdetail: { btn: st.btn, ep: st.ep, flash: fl },
    player: { ep: st.epn || 2, sec: Math.max(0, t - st.load), titleK: sm(t, st.load + 0.2, st.load + 0.5) },
  };
  const layers = [L(st.page, map[st.page], sm(t, st.load + 0.08, st.load + 0.3))];
  if (t < st.load + 0.3 && st.load > 0) layers.unshift(L('blank', {}, 1));
  return { layers, power: 1 };
}

const SCREENS = {
  P01: {
    main(t) {
      const T = { on: M('tv_on'), app: M('app'), search: M('search'), play: M('play'), ep: M('ep'), ep2: M('ep2'), verify: M('verify') };
      return xiaoqiRun(t, T, false);
    },
  },
  P04: {
    main(t) {
      const on = M('tv_on');
      return { layers: t >= on + 0.45 ? [L('launcher', { focus: 3, clock: '21:12' }, sm(t, on + 0.45, on + 0.7))] : [], ...boot(t, on), ...(t < on ? { power: 0 } : {}) };
    },
  },
  P05: { main(t) { return pressRun(t, CUR.data['S05.presses']); } },
  P06: (() => {
    const BR = {
      a: { bg: 'radial-gradient(ellipse at 30% 20%, #1b4c8c, #081428 70%)', title: '品牌 A 电视', ink: '#cfe2ff', cols: [520, 520, 520],
        cells: [[300, '#2c64b8', '精选', '长街灯火'], [300, '#3d78cc', '电影', '远航'], [300, '#244f91', '少儿'], [220, '#1d3f75', '应用'], [220, '#2a5aa3', '游戏'], [220, '#1a3866', '设置']],
        accent: '#3d8bff', icon: IC.mic, prompt: '请按住遥控器上的语音键说话' },
      b: { bg: 'linear-gradient(160deg, #0f3d2e, #04140f 70%)', title: '品牌 B 电视', ink: '#c8f5df', cols: [380, 380, 380, 380],
        cells: [[250, '#1c7a55', '推荐', '白夜行舟'], [250, '#239066', '电视剧', '北岸来信'], [250, '#17654a', '电影', '归途'], [250, '#1f7d5a', '综艺'], [250, '#145740', '体育'], [250, '#1a6b4e', '少儿'], [250, '#22875f', '应用'], [250, '#125038', '设置']],
        accent: '#22c55e', icon: IC.wave, prompt: '请说“你好电视”唤醒我' },
      c: { bg: 'radial-gradient(ellipse at 70% 30%, #4a2370, #120822 70%)', title: '品牌 C 电视', ink: '#ead8ff', cols: [780, 380, 380],
        cells: [[420, '#6a3aa0', '今日推荐', '云上的家'], [420, '#5a2f8a', '影视', '第七站'], [420, '#4b2675', '音乐'], [200, '#3e1f63', '应用'], [200, '#552c80', '投屏'], [200, '#46236d', '设置']],
        accent: '#a855f7', icon: IC.mic, prompt: '抱歉，没有听清，请再说一遍' },
    };
    const brand = (id, t, at) => ({ layers: [L('brand_' + id, { voice: sm(t, at, at + 0.4) })], power: sm(t, M('tvs') - 0.6, M('tvs') + 0.1) });
    return {
      _brands: BR,
      a(t) { const r = brand('a', t, M('a')); r.power *= 1 - sm(t, M('led') - 0.1, M('led') + 0.5); return r; },
      b(t) { const r = brand('b', t, M('b')); r.power *= 1 - sm(t, M('led') - 0.1, M('led') + 0.5); return r; },
      c(t) {
        const spark = M('spark'), wake = M('wake'), scan = M('scan');
        if (t < spark + 0.1) {
          const r = brand('c', t, M('c')); r.power *= 1 - sm(t, spark - 0.05, spark + 0.1); return r;
        }
        const r = { layers: [L('launcher', { focus: null, clock: '21:36' })], ...boot(t, wake, 0.8), eyes: [] };
        if (t < wake) r.power = 0;
        if (t > scan - 0.1) {
          for (const e of PAGES.launcher.root.querySelectorAll('[data-eye]')) {
            const b = e.getBoundingClientRect();
            const a0 = scan + 1.5 * (b.left + b.width / 2) / W;
            const k = sm(t, a0, a0 + 0.15) * (1 - sm(t, M('S08.end') - 1.2, M('S08.end') - 0.4));
            if (k > 0) r.eyes.push({ el: e, k });
          }
        }
        return r;
      },
    };
  })(),
  P09: {
    studio(t) {
      const on = M('l3');
      return { layers: t >= on + 0.5 ? [L('launcher', { focus: 3 }, sm(t, on + 0.5, on + 0.8))] : [], ...boot(t, on + 0.1), ...(t < on + 0.1 ? { power: 0 } : {}) };
    },
  },
  P10: {
    studio(t) {
      const s11 = M('S11.start'), typ = M('type'), clk = M('click'), keys = M('keys'), media = M('media'), scan = M('S10.scan');
      const r = { power: 1, eyes: [], clicks: [] };
      const play0 = clk + 0.35, ep2 = keys + 0.75;
      const steps = [
        [-9, L('vhome', {})],
        [s11 + 0.05, L('vsearch', { text: t >= typ + 0.15 ? '雾港' : '', res: t >= typ + 0.15 ? 0 : null, playFocus: true, caret: t < typ + 0.15, t, flash: flash(t, clk) })],
        [play0, L('player', { ep: t < ep2 ? 1 : 2, sec: t - play0 + 1, titleK: 1, progK: sm(t, media, media + 0.2), panelK: win(t, play0 + 0.1, ep2 + 0.25, 0.2, 0.3),
          epFocus: t < keys + 0.3 ? 0 : 1, pauseK: win(t, media + 0.1, media + 1.6, 0.15, 0.3) })],
      ];
      r.layers = seq(t, steps);
      if (t < s11 + 0.05) {
        for (const e of PAGES.vhome.root.querySelectorAll('[data-eye]')) {
          const b = e.getBoundingClientRect();
          const a0 = scan + 1.1 * (b.top + b.height / 2) / H;
          const k = sm(t, a0, a0 + 0.1) * (1 - sm(t, s11 - 0.5, s11));
          if (k > 0) r.eyes.push({ el: e, k });
        }
      }
      const e = (el, a, b) => { const k = win(t, a, b, 0.12, 0.25); if (k > 0) r.eyes.push({ el, k }); };
      e(PAGES.vsearch.field, typ - 0.25, typ + 0.6);
      e(PAGES.vsearch.cards[0].play, clk - 0.4, play0);
      e(PAGES.player.eps[1], keys - 0.1, ep2);
      const c = ripple(t, clk); if (c !== null && t < play0) r.clicks.push({ el: PAGES.vsearch.cards[0].play, k: c });
      return r;
    },
  },
  P13: {
    main(t) {
      const k = [1, 2, 3, 4, 5, 6].map((i) => M('k' + i));
      const T = { on: k[0] + 0.15, app: k[1] + 0.25, search: k[2] + 0.2, play: k[3] + 0.3, ep: k[4] - 0.2, ep2: k[4] + 0.6, verify: k[5] };
      return xiaoqiRun(t, T, true);
    },
  },
  P14: {
    main(t) {
      const seek = M('seek'), next = M('next'), vol = M('vol');
      const nx = next + 0.35;
      const st = t < nx
        ? { ep: 2, sec: t < seek ? 740 + (t - seek) + 0.2 : 860 + (t - seek) }
        : { ep: 3, sec: 92 + (t - nx) };
      st.progK = win(t, seek - 0.1, seek + 2.6, 0.15, 0.4);
      st.seek = { text: '+2:00', k: win(t, seek, seek + 1.0, 0.1, 0.3) };
      st.titleK = Math.max(st.progK, win(t, nx, nx + 2.4, 0.2, 0.4));
      st.toast = { html: '即将播放 <b>第3集</b>', k: win(t, next - 0.05, nx + 0.9, 0.12, 0.3) };
      const v = t < vol ? 15 : lerp(15, 12, sm(t, vol, vol + 0.4));
      st.vol = { v, k: win(t, vol - 0.05, vol + 2.4, 0.12, 0.4) };
      return { layers: [L('player', st)], power: 1 };
    },
  },
  P15: {
    main(t) {
      const app = M('app'), daily = M('daily'), all = M('all');
      const r = { power: 1, eyes: [], clicks: [] };
      r.layers = seq(t, [
        [-9, L('launcher', { focus: 3, clock: '21:58' })],
        [app + 0.3, L('mhome', { focus: true, flash: flash(t, daily) })],
        [daily + 0.35, L('mlist', { focus: true, flash: flash(t, all), cur: t > all + 0.2 })],
        [all + 0.4, L('mplayer', { sec: Math.max(0, t - all - 0.4) + 2 })],
      ]);
      const e = (el, a, b) => { const k = win(t, a, b, 0.12, 0.25); if (k > 0) r.eyes.push({ el, k }); };
      e(PAGES.launcher.tiles[1], app - 0.45, app + 0.3);
      e(PAGES.mhome.daily, daily - 0.5, daily + 0.35);
      e(PAGES.mlist.all, all - 0.5, all + 0.4);
      for (const [el, t0, t1] of [[PAGES.launcher.tiles[1], app - 0.05, app + 0.3], [PAGES.mhome.daily, daily, daily + 0.35], [PAGES.mlist.all, all, all + 0.4]]) {
        const c = ripple(t, t0); if (c !== null && t < t1) r.clicks.push({ el, k: c });
      }
      return r;
    },
  },
  P16: {
    main(t) {
      const app = M('app'), click = M('click'), type = M('type'), enter = M('enter'), pg = M('page');
      const r = { power: 1, eyes: [], clicks: [] };
      r.layers = seq(t, [
        [-9, L('launcher', { focus: 3, clock: '18:40' })],
        [app + 0.3, L('bhome', { focus: t >= click + 0.1, text: t >= type ? '红烧肉怎么做' : '', t, flash: flash(t, click) })],
        [enter + 0.25, L('bres', { load: clamp((t - enter - 0.25) / (pg - enter + 0.3)) })],
      ], 0.18);
      const e = (el, a, b) => { const k = win(t, a, b, 0.12, 0.25); if (k > 0) r.eyes.push({ el, k }); };
      e(PAGES.launcher.tiles[2], app - 0.45, app + 0.3);
      e(PAGES.bhome.addr, click - 0.45, type + 0.5);
      for (const [el, t0, t1] of [[PAGES.launcher.tiles[2], app - 0.05, app + 0.3], [PAGES.bhome.addr, click, click + 0.75]]) {
        const c = ripple(t, t0); if (c !== null && t < t1) r.clicks.push({ el, k: c });
      }
      return r;
    },
  },
  P17: {
    main(t) {
      const off = M('off');
      return { layers: [L('player', { ep: 3, sec: 1310 + t })], power: 1 - sm(t, off, off + 0.25) };
    },
  },
};

// ------------------------------------------------------------------ render API

let BOOT, POWER;
window.initTV = function (data) {
  TL = data.timeline; META = data.meta; FPS = TL.fps; HAND = TL.handle;
  for (const s of [...SHOWS, ...MOVIES]) { ART[s[0]] = poster(...s); ART[s[0] + '_bare'] = poster(...s, true); }
  ART['王冠'] = poster('王冠', '全 40 集', '#6b5a2a', '#1a1408', 'sun', 12);
  ART['晚歌'] = poster('晚歌', '电影 · 2024', '#7a2f4a', '#1a0a12', 'wave', 13);
  ART['无归'] = poster('无归', '纪录片', '#3a4a5a', '#0a0f14', 'mount', 14);
  ART.daily = cover('#f05a4f', '#6d1236', 'rgba(255,210,170,0.9)', 31);
  ART.song = cover('#2b4c7e', '#d0745a', 'rgba(255,230,190,0.95)', 41, 600);
  STAGE = document.getElementById('tv');
  page('blank', 'vapp', () => ({ update() {} }));
  page('launcher', 'launcher', buildLauncher);
  page('vhome', 'vapp', buildVHome);
  page('vsearch', 'vapp vsearch', buildVSearch);
  page('vdetail', 'vapp vdetail', buildVDetail);
  page('player', 'player', buildPlayer);
  page('mhome', 'music', buildMHome);
  page('mlist', 'music', buildMList);
  page('mplayer', 'music m-player', buildMPlayer);
  page('bhome', 'browser', buildBHome);
  page('bres', 'browser', buildBRes);
  for (const id of ['a', 'b', 'c']) page('brand_' + id, 'brandp', (root) => buildBrand(root, SCREENS.P06._brands[id]));
  BOOT = div(null, STAGE); BOOT.id = 'boot'; div('logo', BOOT); BOOT.style.zIndex = 40;
  POWER = div(null, STAGE); POWER.id = 'power'; POWER.style.zIndex = 50;
  return Object.fromEntries(Object.entries(SCREENS).map(([p, s]) => [p, Object.keys(s).filter((k) => !k.startsWith('_'))]));
};

function rectOf(e) {
  const b = e.getBoundingClientRect();
  return [Math.round(b.left), Math.round(b.top), Math.round(b.width), Math.round(b.height)];
}

window.renderScreen = function (pid, sid, t) {
  CUR = TL.plates[pid];
  const r = SCREENS[pid][sid](t) || OFF;
  for (const name in PAGES) PAGES[name].root.style.display = 'none';
  (r.layers || []).forEach((ly, i) => {
    const P = PAGES[ly.p];
    P.root.style.display = 'block';
    P.root.style.opacity = ly.o;
    P.root.style.zIndex = i + 1;
    P.update(ly.st || {});
  });
  POWER.style.opacity = 1 - (r.power ?? 1);
  BOOT.style.opacity = r.boot || 0;
  BOOT.querySelector('.logo').style.transform = `scale(${0.85 + 0.15 * (r.boot || 0)})`;
  const out = {};
  if (r.eyes && r.eyes.length) out.e = r.eyes.filter((e) => e.el.offsetParent !== null || e.el.getClientRects().length).map((e) => [...rectOf(e.el), +e.k.toFixed(3), e.verify ? 1 : 0]);
  if (r.clicks && r.clicks.length) out.c = r.clicks.map((c) => [...rectOf(c.el), +c.k.toFixed(3)]);
  return out;
};
