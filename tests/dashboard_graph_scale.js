/** Misura il disegno su un vault grande (Playwright + Chromium).
 * Uso: python tests/dashboard_graph_fixture.py <cartella-nuova> --nodi 2000   (stampa l'URL di sessione)
 *      node tests/dashboard_graph_scale.js "<URL>" [nodi-attesi=2000] [secondi-massimi-assestamento=20]
 * Controlla: il disegno arriva al limite impostato, il layout si assesta entro il tempo massimo, il browser resta reattivo
 * (nessun fotogramma bloccato oltre 500 ms durante il layout) e tutti i nodi stanno nell'area visibile.
 */
const { chromium } = require('playwright');
(async () => {
  const [url, expected = '2000', limit = '20'] = process.argv.slice(2);
  const browser = await chromium.launch({ args: ['--no-sandbox'] });
  const page = await browser.newPage({ viewport: { width: 1280, height: 900 } });
  const errors = [];
  page.on('pageerror', e => errors.push(String(e.stack || e)));
  try {
    await page.goto(url);
    await page.waitForFunction(() => !document.getElementById('apply').disabled && document.getElementById('counts').textContent.includes('nodi'), null, { timeout: 30000 });
    await page.evaluate(() => { window.__gaps = []; let last = performance.now(); const tick = now => { window.__gaps.push(now - last); last = now; requestAnimationFrame(tick); }; requestAnimationFrame(tick); });
    await page.fill('#map-limit', expected);
    await page.dispatchEvent('#map-limit', 'change');
    const loadStart = Date.now();
    await page.click('#load-all');
    await page.waitForFunction(n => document.querySelectorAll('#nodes button').length >= n || document.getElementById('load-all').hidden, Number(expected), { timeout: 120000 });
    const loaded = await page.locator('#nodes button').count();
    const loadSeconds = (Date.now() - loadStart) / 1000;
    const layoutStart = Date.now();
    await page.waitForFunction(n => document.querySelectorAll('#map > svg g[data-node]').length >= n && document.querySelector('.map-tools span')?.textContent.includes('assestato'), Number(expected), { timeout: 60000 });
    const settleSeconds = (Date.now() - layoutStart) / 1000;  // costruzione a blocchi + layout, dopo il caricamento dei dati
    const drawn = await page.locator('#map > svg g[data-node]').count();
    const inside = await page.evaluate(() => { const svg = document.querySelector('#map > svg').getBoundingClientRect(); const nodes = [...document.querySelectorAll('#map > svg g[data-node]')]; return nodes.filter(g => { const r = g.querySelector('circle').getBoundingClientRect(); return r.left >= svg.left - 2 && r.right <= svg.right + 2 && r.top >= svg.top - 2 && r.bottom <= svg.bottom + 2; }).length / nodes.length; });
    const worst = await page.evaluate(() => Math.max(...window.__gaps));
    const gaps = await page.evaluate(() => window.__gaps.slice().sort((a, b) => a - b)); const result = { frames: gaps.length, medianFrameMs: Math.round(gaps[gaps.length >> 1]), loaded, drawn, loadSeconds, settleSeconds, worstFrameMs: Math.round(worst), insideShare: Number(inside.toFixed(3)), errors };
    result.ok = drawn === Number(expected) && settleSeconds <= Number(limit) && worst < 500 && inside > 0.98 && errors.length === 0;
    console.log(JSON.stringify(result));
    process.exitCode = result.ok ? 0 : 1;
  } catch (error) {
    console.log(JSON.stringify({ ok: false, error: String(error), errors }));
    process.exitCode = 1;
  } finally { await browser.close(); }
})();
