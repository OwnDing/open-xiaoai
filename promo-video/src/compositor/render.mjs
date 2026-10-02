// Drive the HTML compositor in headless Edge and capture frames.
//   node render.mjs --stills 120,480 [--outdir ../../build/stills]
//   node render.mjs [--from 0] [--to N] [--out ../../build/video.mp4]
import http from 'node:http';
import fs from 'node:fs';
import path from 'node:path';
import { spawn } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import puppeteer from 'puppeteer-core';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..');
const EDGE = process.env.CHROME || '/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge';
const args = Object.fromEntries(process.argv.slice(2).reduce((acc, a, i, arr) => {
  if (a.startsWith('--')) acc.push([a.slice(2), arr[i + 1] && !arr[i + 1].startsWith('--') ? arr[i + 1] : true]);
  return acc;
}, []));

const TYPES = { '.html': 'text/html', '.js': 'text/javascript', '.css': 'text/css', '.jpg': 'image/jpeg', '.png': 'image/png', '.json': 'application/json' };
// Proxies are rendered on every 3rd frame: serve the nearest earlier frame.
function proxyFallback(p) {
  const m = p.match(/^(.*\/build\/proxy\/[^/]+\/)(\d{4})\.jpg$/);
  if (!m) return p;
  for (let f = Number(m[2]); f > 0 && Number(m[2]) - f < 6; f--) {
    const q = `${m[1]}${String(f).padStart(4, '0')}.jpg`;
    if (fs.existsSync(q)) return q;
  }
  return p;
}
const server = http.createServer((req, res) => {
  const p = proxyFallback(path.join(ROOT, decodeURIComponent(req.url.split('?')[0])));
  if (!p.startsWith(ROOT) || !fs.existsSync(p) || fs.statSync(p).isDirectory()) { res.writeHead(404); res.end(); return; }
  res.writeHead(200, { 'Content-Type': TYPES[path.extname(p)] || 'application/octet-stream', 'Cache-Control': 'max-age=3600' });
  fs.createReadStream(p).pipe(res);
});
await new Promise((r) => server.listen(0, '127.0.0.1', r));
const port = server.address().port;

const readJson = (p) => JSON.parse(fs.readFileSync(path.join(ROOT, p), 'utf8'));
const timeline = readJson('build/timeline.json');
const meta = readJson('build/audio/voice/meta.json');
const anchors = {};
// --proxy: use the quarter-res stand-ins in build/proxy wherever a final plate is missing.
const plateBase = {};
for (const pid of Object.keys(timeline.plates)) {
  const final = path.join(ROOT, 'build/plates', pid);
  const proxy = path.join(ROOT, 'build/proxy', pid);
  const done = fs.existsSync(final) && fs.readdirSync(final).filter((f) => f.endsWith('.jpg')).length >= timeline.plates[pid].frames + 2 * timeline.handle;
  const dir = args.proxy && !done && fs.existsSync(proxy) ? proxy : final;
  plateBase[pid] = '/' + path.relative(ROOT, dir);
  const f = path.join(dir, 'anchors.json');
  if (fs.existsSync(f)) anchors[pid] = JSON.parse(fs.readFileSync(f, 'utf8'));
}

const browser = await puppeteer.launch({
  executablePath: EDGE,
  headless: true,
  defaultViewport: { width: 1920, height: 1080, deviceScaleFactor: 1 },
  args: ['--force-color-profile=srgb', '--hide-scrollbars', '--font-render-hinting=none', '--enable-gpu-rasterization'],
});
const page = await browser.newPage();
page.on('pageerror', (e) => console.error('page error:', e.message));
page.on('console', (m) => { if (m.type() === 'error') console.error('console:', m.text()); });
await page.goto(`http://127.0.0.1:${port}/src/compositor/index.html`, { waitUntil: 'load' });
await page.evaluate((d) => window.init(d), { timeline, meta, anchors, plateBase });
await page.evaluate(() => document.fonts.ready);

const shot = async (g, type = 'jpeg') => {
  await page.evaluate((g) => window.renderFrame(g), g);
  return page.screenshot(type === 'png' ? { type: 'png' } : { type: 'jpeg', quality: 93, optimizeForSpeed: true });
};

if (args.stills) {
  const outdir = path.resolve(args.outdir || path.join(ROOT, 'build/stills'));
  fs.mkdirSync(outdir, { recursive: true });
  for (const g of String(args.stills).split(',').map(Number)) {
    fs.writeFileSync(path.join(outdir, `f${String(g).padStart(4, '0')}.jpg`), await shot(g));
  }
  console.log('stills written to', outdir);
} else {
  const from = Number(args.from || 0), to = Number(args.to || timeline.frames);
  const out = path.resolve(args.out || path.join(ROOT, 'build/video.mp4'));
  const ff = spawn('ffmpeg', ['-y', '-v', 'error', '-f', 'image2pipe', '-framerate', String(timeline.fps), '-c:v', 'mjpeg', '-i', '-',
    '-c:v', 'libx264', '-preset', 'slow', '-crf', '12', '-pix_fmt', 'yuv420p', '-color_primaries', 'bt709', '-color_trc', 'bt709', '-colorspace', 'bt709', out],
    { stdio: ['pipe', 'inherit', 'inherit'] });
  const t0 = Date.now();
  for (let g = from; g < to; g++) {
    const buf = await shot(g);
    if (!ff.stdin.write(buf)) await new Promise((r) => ff.stdin.once('drain', r));
    if (g % 150 === 0) console.log(`frame ${g}/${to}  ${((Date.now() - t0) / 1000).toFixed(0)}s`);
  }
  ff.stdin.end();
  await new Promise((r) => ff.on('close', r));
  console.log('video written to', out);
}
await browser.close();
server.close();
