/** Smoke del disegno e degli strumenti del nodo in un browser reale (Playwright + Chromium).
 * Uso: python tests/dashboard_graph_fixture.py <cartella-nuova>   (stampa l'URL di sessione)
 *      node tests/dashboard_graph_smoke.js "<URL di sessione>" [cartella-screenshot]
 * Il vault è sintetico: 120 nodi `Nodo NNN`, catena causale `Evento 0..3`, storia Git con Ada e Bruno.
 * La modifica finale scrive davvero nel vault sintetico: non puntarlo mai a un vault reale.
 */
const { chromium } = require('playwright');
(async () => {
  const [url, shots = '.'] = process.argv.slice(2);
  const browser = await chromium.launch({ args: ['--no-sandbox'] });
  const page = await browser.newPage({ viewport: { width: 1280, height: 900 } });
  const errors = [], checks = [];
  page.on('pageerror', e => errors.push(String(e.stack || e)));
  page.on('console', m => { if (m.type() === 'error') errors.push(m.text()); });
  const expect = (condition, label) => { if (!condition) throw new Error('FAIL ' + label); checks.push(label); };
  const wait = (fn, label, arg) => page.waitForFunction(fn, arg, { timeout: 20000 }).catch(() => { throw new Error('TIMEOUT ' + label); });
  try {
    await page.goto(url);
    await wait(() => !document.getElementById('apply').disabled && document.getElementById('counts').textContent.includes('50 nodi'), 'first page');
    while (await page.locator('#more:not([hidden])').count()) {
      await page.click('#more'); await wait(() => !document.getElementById('more').disabled || document.getElementById('more').hidden, 'more');
    }
    expect((await page.locator('#nodes button').count()) === 124, 'all 124 nodes listed');
    await wait(() => document.querySelector('.map-tools span')?.textContent.includes('assestato'), 'layout settles');
    expect((await page.locator('#map > svg g[data-node]').count()) === 124, 'map draws every loaded node (limit 200)');
    const spread = await page.evaluate(() => { const xs = [...document.querySelectorAll('#map > svg g[data-node]')].map(g => g.getAttribute('transform')); return new Set(xs).size; });
    expect(spread > 100, 'force layout separates the nodes (' + spread + ' distinct positions)');
    expect((await page.locator('#map .legend li').count()) === 2, 'legend lists the two types');
    const fills = await page.evaluate(() => new Set([...document.querySelectorAll('#map circle.node-dot')].map(c => c.getAttribute('fill'))).size);
    expect(fills === 2, 'colour per type');
    const scale = () => page.evaluate(() => Number(/scale\(([\d.]+)\)/.exec(document.querySelector('#map > svg > g').getAttribute('transform'))[1]));
    const fitted = await scale();
    const inside = await page.evaluate(() => { const svg = document.querySelector('#map > svg').getBoundingClientRect(); return [...document.querySelectorAll('#map > svg g[data-node]')].every(g => { const r = g.getBoundingClientRect(); return r.left >= svg.left - 1 && r.right <= svg.right + 1 && r.top >= svg.top - 1 && r.bottom <= svg.bottom + 1; }); });
    expect(inside, 'auto-fit keeps every node inside the visible area (scale ' + fitted.toFixed(2) + ')');
    await page.click('button[aria-label="Ingrandisci il disegno"]');
    expect((await scale()) > fitted * 1.2, 'zoom in button');
    await page.click('button[aria-label="Reimposta zoom e posizione"]');
    expect(Math.abs((await scale()) - fitted) < 0.01, 'reset view returns to the fitted view');
    const box = await page.locator('#map > svg').boundingBox();
    await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2); await page.mouse.wheel(0, -300);
    expect((await scale()) > fitted * 1.05, 'wheel zoom');
    const before = await page.evaluate(() => document.querySelector('#map > svg > g').getAttribute('transform'));
    await page.mouse.move(box.x + 20, box.y + 20); await page.mouse.down(); await page.mouse.move(box.x + 120, box.y + 70, { steps: 6 }); await page.mouse.up();
    expect(before !== await page.evaluate(() => document.querySelector('#map > svg > g').getAttribute('transform')), 'drag pans the view');
    await page.screenshot({ path: shots + '/graph.png' });

    const authors = await page.locator('#author option').allTextContents();
    expect(authors.some(a => a.startsWith('Ada')) && authors.some(a => a.startsWith('Bruno')), 'author filter lists Ada and Bruno');
    await page.selectOption('#author', 'Bruno'); await page.click('#apply');
    await wait(() => document.querySelectorAll('#nodes button').length === 1, 'author filter result');
    expect((await page.locator('#nodes button').first().textContent()).startsWith('Nodo 007'), 'Bruno modified only Nodo 007');
    await page.selectOption('#author', ''); await page.click('#apply');
    await wait(() => document.querySelectorAll('#nodes button').length === 50, 'filter cleared');

    await page.fill('#search', 'Evento 0');
    await page.locator('#nodes button').first().click();
    await wait(() => document.querySelector('#detail pre'), 'event detail');
    expect((await page.locator('#detail').textContent()).includes('Creata da Ada'), 'authors shown in the detail');
    await page.click('text=Mostra gli effetti');
    await wait(() => document.querySelectorAll('#detail ul li').length >= 3, 'causal chain');
    const chain = await page.locator('#detail').textContent();
    expect(chain.includes('Evento 0 → causa → Evento 1') && chain.includes('confidenza alta') && chain.includes('Lo afferma la call'), 'chain with confidence and evidence');
    const marked = await page.evaluate(() => [...document.querySelectorAll('#map g[data-node]')].filter(g => g.getAttribute('opacity') === '1').length);
    expect(marked === 4, 'chain highlighted on the map (' + marked + ' nodes)');
    await page.screenshot({ path: shots + '/causal.png' });
    await page.click('text=Mostra le cause');
    await wait(() => document.querySelector('#detail').textContent.includes('Nessuna causa dichiarata'), 'no causes for the first event');

    await page.fill('#search', 'Nodo 001'); await page.locator('#nodes button').first().click();
    await wait(() => document.querySelector('#detail summary'), 'node detail');
    await page.click('text=Espandi il vicinato nel disegno');
    await wait(() => document.querySelector('#detail').textContent.includes('nodi aggiunti'), 'neighbourhood expanded');

    await page.click('text=Modifica il grafo');
    await page.selectOption('#detail select[aria-label="Tipo di modifica"]', 'set_tags');
    await page.fill('#detail details input', 'uno, due');
    await page.click('text=Aggiungi alla modifica'); await page.click('button:has-text("Anteprima")');
    await wait(() => document.querySelector('#detail pre') && document.querySelector('#detail').textContent.includes('Differenze nel frontmatter'), 'preview');
    expect((await page.locator('#detail').textContent()).includes('+tags: [uno, due]'), 'preview shows the frontmatter diff');
    await page.click('button:has-text("Applica la modifica")');
    expect((await page.locator('#detail').textContent()).includes('Conferma prima'), 'apply refused without confirmation');
    await page.check('#detail input[type=checkbox]'); await page.click('button:has-text("Applica la modifica")');
    await wait(() => document.getElementById('operation').textContent.includes('Modifica del grafo') && document.getElementById('operation').textContent.includes('succeeded'), 'edit applied');
    await page.screenshot({ path: shots + '/edit.png' });
    expect(errors.length === 0, 'no console or page errors: ' + errors.join(' | '));
    console.log(JSON.stringify({ ok: true, checks }, null, 1));
  } catch (error) {
    await page.screenshot({ path: shots + '/failure.png' }).catch(() => {});
    console.log(JSON.stringify({ ok: false, error: String(error), checks, errors }, null, 1));
    process.exitCode = 1;
  } finally { await browser.close(); }
})();
