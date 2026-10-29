/** Smoke del pulsante Autosync nel pannello «Pubblicazione Git dei dati» (Playwright + Chromium).
 * Uso: python tests/dashboard_autosync_fixture.py <cartella-nuova>   (stampa l'URL di sessione)
 *      node tests/dashboard_autosync_smoke.js "<URL di sessione>" [cartella-screenshot]
 * Il vault parte con autosync attivo: lo smoke lo disattiva, verifica il consenso obbligatorio e lo riattiva dalla UI.
 */
const { chromium } = require('playwright');
(async () => {
  const [url, shots = '.'] = process.argv.slice(2);
  const browser = await chromium.launch({ args: ['--no-sandbox'] });
  const page = await browser.newPage({ viewport: { width: 1280, height: 1000 } });
  const errors = [], checks = [];
  page.on('pageerror', e => errors.push(String(e.stack || e)));
  page.on('console', m => { if (m.type() === 'error') errors.push(m.text()); });
  const expect = (condition, label) => { if (!condition) throw new Error('FAIL ' + label); checks.push(label); };
  const wait = (fn, label) => page.waitForFunction(fn, null, { timeout: 20000 }).catch(() => { throw new Error('TIMEOUT ' + label); });
  const text = () => page.locator('#autosync-state').textContent();
  try {
    await page.goto(url);
    await wait(() => !document.getElementById('apply').disabled, 'vault loaded');
    await page.click('summary:has-text("Pubblicazione Git dei dati")');
    await wait(() => document.getElementById('autosync-state')?.textContent.includes('Autosync attivo'), 'active state shown');
    expect(await page.locator('button:has-text("Disattiva autosync")').count() === 1, 'disable button offered while active');
    await page.click('button:has-text("Disattiva autosync")');
    await wait(() => document.getElementById('autosync-state').textContent.includes('Autosync non attivo'), 'disabled');
    const enable = page.locator('button:has-text("Attiva autosync")');
    expect(await enable.isDisabled(), 'enable button needs the consent');
    await page.check('#autosync-consent');
    expect(!(await enable.isDisabled()), 'consent enables the button');
    await page.screenshot({ path: shots + '/autosync.png' });
    await enable.click();
    await wait(() => document.getElementById('autosync-state').textContent.includes('Autosync attivo'), 're-enabled');
    expect((await text()).includes('Disattiva') || await page.locator('button:has-text("Disattiva autosync")').count() === 1, 'back to active');
    expect(errors.length === 0, 'no console or page errors: ' + errors.join(' | '));
    console.log(JSON.stringify({ ok: true, checks }, null, 1));
  } catch (error) {
    await page.screenshot({ path: shots + '/autosync-failure.png' }).catch(() => {});
    console.log(JSON.stringify({ ok: false, error: String(error), checks, errors }, null, 1));
    process.exitCode = 1;
  } finally { await browser.close(); }
})();
