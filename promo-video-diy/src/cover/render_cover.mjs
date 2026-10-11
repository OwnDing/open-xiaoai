// Screenshot the cover page at B站 sizes: node src/cover/render_cover.mjs
import http from 'node:http';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { createRequire } from 'node:module';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..');
const require = createRequire(path.join(ROOT, 'src/compositor/package.json'));
const puppeteer = require('puppeteer-core');
const EDGE = process.env.CHROME || '/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge';
const TYPES = { '.html': 'text/html', '.png': 'image/png', '.jpg': 'image/jpeg' };
const server = http.createServer((req, res) => {
  const p = path.join(ROOT, decodeURIComponent(req.url.split('?')[0]));
  if (!p.startsWith(ROOT) || !fs.existsSync(p)) { res.writeHead(404); res.end(); return; }
  res.writeHead(200, { 'Content-Type': TYPES[path.extname(p)] || 'application/octet-stream' });
  fs.createReadStream(p).pipe(res);
});
await new Promise((r) => server.listen(0, '127.0.0.1', r));
const port = server.address().port;
const browser = await puppeteer.launch({ executablePath: EDGE, headless: true, args: ['--force-color-profile=srgb'] });
const page = await browser.newPage();
const covers = [
  { name: 'cover_16x9.jpg', w: 1920, h: 1080, bg: 'build/cover/bg_16x9.png', x: 96, y: 110, pre: 64, big: 122 },
  { name: 'cover_4x3.jpg', w: 1440, h: 1080, bg: 'build/cover/bg_4x3.png', x: 80, y: 110, pre: 60, big: 112 },
];
for (const c of covers) {
  await page.setViewport({ width: c.w, height: c.h, deviceScaleFactor: 1 });
  const q = new URLSearchParams({ w: c.w, h: c.h, bg: '/' + c.bg, x: c.x, y: c.y, pre: c.pre, big: c.big });
  await page.goto(`http://127.0.0.1:${port}/src/cover/cover.html?${q}`, { waitUntil: 'load' });
  await page.evaluate(() => Promise.all([document.fonts.ready, document.getElementById('bg').decode()]));
  await page.screenshot({ path: path.join(ROOT, 'output', c.name), type: 'jpeg', quality: 92 });
  console.log('->', c.name);
}
await browser.close();
server.close();
