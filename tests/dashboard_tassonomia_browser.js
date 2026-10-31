/** Pilota di tests/dashboard_tassonomia_browser.py: URL autenticato e cartella delle schermate come argomenti. */
const { chromium } = require('playwright');
(async () => {
  const [url, out] = process.argv.slice(2), checks = [];
  const ok = (c, l) => { if (!c) throw new Error('FALLITO: ' + l); checks.push(l); };
  const browser = await chromium.launch();
  try {
    for (const [nome, w, h] of [['desktop', 1440, 900], ['mobile', 390, 844]]) {
      const page = await browser.newPage({ viewport: { width: w, height: h } }), errors = []; page.setDefaultTimeout(15000);
      page.on('pageerror', e => errors.push(String(e)));
      await page.goto(url);
      await page.waitForFunction(() => !document.getElementById('apply').disabled && document.getElementById('counts').textContent.includes('nodi'));
      const opzioni = await page.$$eval('#category option', os => os.map(o => o.value));
      ok(JSON.stringify(opzioni) === JSON.stringify(['', 'amministrazione', 'fatturazione', 'ciclo-passivo', 'rilasci']), nome + ': categorie nel filtro');
      await page.selectOption('#category', 'amministrazione');
      await page.click('#apply');
      await page.waitForFunction(() => document.querySelectorAll('#nodes button').length === 2);
      const nodi = await page.$$eval('#nodes button', bs => bs.map(b => b.firstChild.textContent).sort());
      ok(JSON.stringify(nodi) === '["Fatture","Gestionale"]', nome + ': filtro con sottocategorie');
      await page.screenshot({ path: out + '/b1-' + nome + '.png' });
      await page.click('[data-view="ontology"]');
      const testo = await page.textContent('#ontology-published');
      ok(testo.includes('servizio (sottotipo di sistema)') && testo.includes('fatturazione (in amministrazione)'), nome + ': gerarchie nel vocabolario pubblicato');
      await page.selectOption('#ontology-category', 'type');
      ok(await page.isVisible('#ontology-parent'), nome + ': campo «Sottotipo di» per i tipi');
      await page.selectOption('#ontology-category', 'relation');
      ok(!(await page.isVisible('#ontology-parent')), nome + ': campo nascosto per le relazioni');
      ok(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth), nome + ': nessuno scorrimento orizzontale');
      ok(!errors.length, nome + ': nessun errore JavaScript ' + errors.join(' '));
      await page.close();
    }
  } finally { await browser.close(); }
  console.log(checks.join('\n') + '\n' + checks.length + ' controlli OK');
})().catch(e => { console.error(e.message); process.exit(1); });
