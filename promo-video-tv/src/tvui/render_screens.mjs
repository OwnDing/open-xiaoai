// Render what every TV shows, frame by frame, as image sequences the Blender plates map onto the screens.
//   node src/tvui/render_screens.mjs [P01 P05 ...]          -> build/screens/<plate>/<screen>/####.jpg + eyes.json
//   node src/tvui/render_screens.mjs --stills P01:main:6.2,8 -> build/screen_stills/
import http from 'node:http';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { createRequire } from 'node:module';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..');
const require = createRequire(path.join(ROOT, 'src/compositor/package.json'));
const puppeteer = require('puppeteer-core');
const EDGE = process.env.CHROME || '/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge';
const argv = process.argv.slice(2);
const stills = argv.includes('--stills') ? argv.slice(argv.indexOf('--stills') + 1) : null;
const plates = stills ? [] : argv.filter((a) => !a.startsWith('--'));

const TYPES = { '.html': 'text/html', '.js': 'text/javascript', '.css': 'text/css', '.json': 'application/json' };
const server = http.createServer((req, res) => {
  const p = path.join(ROOT, decodeURIComponent(req.url.split('?')[0]));
  if (!p.startsWith(ROOT) || !fs.existsSync(p) || fs.statSync(p).isDirectory()) { res.writeHead(404); res.end(); return; }
  res.writeHead(200, { 'Content-Type': TYPES[path.extname(p)] || 'application/octet-stream' });
  fs.createReadStream(p).pipe(res);
});
await new Promise((r) => server.listen(0, '127.0.0.1', r));
const readJson = (p) => JSON.parse(fs.readFileSync(path.join(ROOT, p), 'utf8'));
const timeline = readJson('build/timeline.json');
const meta = readJson('build/audio/voice/meta.json');
const browser = await puppeteer.launch({
  executablePath: EDGE, headless: true,
  defaultViewport: { width: 1920, height: 1080, deviceScaleFactor: 1 },
  args: ['--force-color-profile=srgb', '--hide-scrollbars', '--font-render-hinting=none'],
});
const page = await browser.newPage();
page.on('pageerror', (e) => console.error('page error:', e.message));
page.on('console', (m) => { if (m.type() === 'error') console.error('console:', m.text()); });
await page.goto(`http://127.0.0.1:${server.address().port}/src/tvui/index.html`, { waitUntil: 'load' });
const screens = await page.evaluate((d) => window.initTV(d), { timeline, meta });
await page.evaluate(() => Promise.all([document.fonts.ready, ...[...document.images].map((i) => i.decode().catch(() => {}))]));

const frame = async (pid, sid, t) => {
  const info = await page.evaluate(async (pid, sid, t) => {
    const r = window.renderScreen(pid, sid, t);
    await Promise.all([...document.images].filter((i) => i.offsetParent).map((i) => i.decode().catch(() => {})));
    return r;
  }, pid, sid, t);
  const buf = await page.screenshot({ type: 'jpeg', quality: 90, optimizeForSpeed: true });
  return { info, buf };
};

if (stills) {
  const out = path.join(ROOT, 'build/screen_stills');
  fs.mkdirSync(out, { recursive: true });
  for (const spec of stills) {
    const [pid, sid, times] = spec.split(':');
    for (const t of times.split(',').map(Number)) {
      const { info, buf } = await frame(pid, sid, t);
      fs.writeFileSync(path.join(out, `${pid}_${sid}_${t.toFixed(2).padStart(6, '0')}.jpg`), buf);
      console.log(pid, sid, t, JSON.stringify(info).slice(0, 160));
    }
  }
} else {
  const { fps, handle } = timeline;
  for (const pid of (plates.length ? plates : Object.keys(screens))) {
    const n = timeline.plates[pid].frames + 2 * handle;
    for (const sid of screens[pid] || []) {
      const dir = path.join(ROOT, 'build/screens', pid, sid);
      fs.mkdirSync(dir, { recursive: true });
      const eyes = {};
      const t0 = Date.now();
      for (let f = 1; f <= n; f++) {
        const { info, buf } = await frame(pid, sid, (f - 1 - handle) / fps);
        fs.writeFileSync(path.join(dir, `${String(f).padStart(4, '0')}.jpg`), buf);
        if (info.e || info.c) eyes[f] = info;
      }
      fs.writeFileSync(path.join(dir, 'eyes.json'), JSON.stringify(eyes));
      console.log(`${pid}/${sid}: ${n} frames in ${((Date.now() - t0) / 1000).toFixed(0)}s`);
    }
  }
}
await browser.close();
server.close();
