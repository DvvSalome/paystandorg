// Descarga la página renderizada y todos sus recursos (imágenes, fuentes, CSS) sin reescribir nada todavía.
const { chromium } = require('playwright'); const fs = require('fs'); const crypto = require('crypto');
const W = +process.argv[2] || 1440;
const ALLOWED = /^https:\/\/(www\.paystand\.org|static\.wixstatic\.com|static\.parastorage\.com|siteassets\.parastorage\.com|video\.wixstatic\.com)\//;
(async () => {
  const b = await chromium.launch(); const ctx = await b.newContext({ viewport: { width: W, height: 900 } }); const p = await ctx.newPage();
  const saved = fs.existsSync('cap/saved.json') ? JSON.parse(fs.readFileSync('cap/saved.json')) : {};   // se acumula entre anchos
  p.on('response', async r => {
    const url = r.url(); if (!ALLOWED.test(url) || r.request().method() !== 'GET') return;
    const ct = (r.headers()['content-type'] || '').split(';')[0];
    if (/text\/html|javascript|json/.test(ct) && !/\.css/.test(url)) return;
    try { const body = await r.body(); const h = crypto.createHash('md5').update(url).digest('hex').slice(0, 12);
      fs.writeFileSync(`cap/raw/${h}`, body); saved[url] = { file: h, type: ct, size: body.length }; } catch (e) {}
  });
  await p.goto('https://www.paystand.org/grantapplication', { waitUntil: 'networkidle', timeout: 90000 });
  // desplazar para que carguen imágenes perezosas
  for (let y = 0; y < 4000; y += 400) { await p.evaluate(v => window.scrollTo(0, v), y); await p.waitForTimeout(250); }
  await p.evaluate(() => window.scrollTo(0, 0)); await p.waitForTimeout(1500);
  fs.mkdirSync('cap/raw', { recursive: true }); fs.writeFileSync(`cap/page-${W}.html`, await p.evaluate(() => '<!DOCTYPE html>\n' + document.documentElement.outerHTML));
  fs.writeFileSync('cap/saved.json', JSON.stringify(saved, null, 1));
  
  console.log('recursos guardados:', Object.keys(saved).length, '| tamaño total KB:', Math.round(Object.values(saved).reduce((a, v) => a + v.size, 0) / 1024));
  const kinds = {}; Object.values(saved).forEach(v => { const k = v.type.split('/')[0] + '/' + (v.type.split('/')[1] || ''); kinds[k] = (kinds[k] || 0) + 1; }); console.log(kinds);
  await b.close();
})();
