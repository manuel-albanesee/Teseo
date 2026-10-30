/** Pannello delle lavorazioni nel browser (Playwright/Chromium): contenuto, accessibilità di base, nessuna scrittura.
 * Uso: node tests/dashboard_lavorazioni_smoke.js URL_AUTENTICATO [CARTELLA_SCREENSHOT]
 * L'URL lo stampa tests/dashboard_lavorazioni_fixture.py. Controlla 1440x900 e 390x844.
 */
const { chromium } = require('playwright');
(async () => {
  const [url, shots] = [process.argv[2], process.argv[3]];
  const browser = await chromium.launch(), checks = [];
  const expect = (condition, label) => { if (!condition) throw new Error('KO: ' + label); checks.push(label); };
  try {
    for (const [width, height, name] of [[1440, 900, 'desktop'], [390, 844, 'mobile']]) {
      const page = await browser.newPage({ viewport: { width, height } }), errors = [], writes = [];
      page.on('console', m => { if (m.type() === 'error') errors.push(m.text()); });
      page.on('pageerror', e => errors.push(String(e)));
      page.on('request', r => { if (r.url().includes('/lavorazioni') && r.method() !== 'GET') writes.push(r.method()); });
      await page.goto(url);
      await page.waitForFunction(() => document.getElementById('vault') && document.getElementById('vault').value);
      await page.waitForFunction(() => /sola lettura/.test((document.getElementById('lavorazioni-status') || {}).textContent || ''), null, { timeout: 20000 });
      await page.click('summary:has-text("Lavorazioni")');
      const panel = page.locator('#lavorazioni-panel');
      const text = await panel.innerText();
      expect(text.includes('3 lavorazioni') || (await page.locator('#lavorazioni-status').innerText()).includes('3 lavorazioni'), name + ': tre lavorazioni elencate');
      for (const nome of ['completa', 'scheda-rilascio', 'rotta']) expect(text.includes(nome), name + ': compare ' + nome);
      expect(/01-raccolta · COMPLETA/.test(text), name + ': fase completa');
      expect(/DA RIFARE/.test(text) && text.includes('Console di rilascio'), name + ': fase da rifare con il motivo');
      expect(text.includes('config_mancante'), name + ': definizione rotta segnalata');
      expect(text.includes('Sola lettura'), name + ': dichiara la sola lettura');
      expect(await page.locator('#lavorazioni-status[role="status"][aria-live="polite"]').count() === 1, name + ': messaggio per i lettori di schermo');
      const box = await page.locator('#lavorazioni-refresh').boundingBox();
      expect(box && box.height >= 24, name + ': pulsante raggiungibile (altezza ' + (box && Math.round(box.height)) + ' px)');
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth + 1), name + ': nessun overflow orizzontale');
      expect(await page.evaluate(() => !window.XSS_EXECUTED), name + ': nessuno script eseguito');
      await page.click('#lavorazioni-refresh');
      await page.waitForFunction(() => !document.getElementById('lavorazioni-refresh').disabled);
      expect(writes.length === 0, name + ': nessuna richiesta di scrittura a /lavorazioni');
      expect(errors.length === 0, name + ': nessun errore in console ' + JSON.stringify(errors));
      if (shots) await panel.screenshot({ path: `${shots}/lavorazioni-${name}.png` });
      await page.close();
    }
    console.log('OK ' + checks.length + ' controlli\n- ' + checks.join('\n- '));
  } finally { await browser.close(); }
})().catch(e => { console.error(String(e)); process.exit(1); });
