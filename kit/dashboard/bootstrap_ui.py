"""Pagina statica di collegamento. Dati del vault inseriti solo con textContent."""

PAGE = """<!doctype html>
<html lang="it"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Teseo · Collega un vault</title>
<style nonce="__NONCE__">
body{font:17px system-ui,sans-serif;background:#f7f5ef;color:#242b2c;margin:0}
main{max-width:760px;margin:8vh auto;padding:32px}h1{font-size:2.4rem;margin-bottom:12px}
p{line-height:1.6}label{display:block;font-weight:600;margin-bottom:8px}
input{box-sizing:border-box;width:100%;padding:12px;border:1px solid #687672;border-radius:5px;font:inherit}
button{font:inherit;background:#205c53;color:white;padding:12px 22px;border:0;border-radius:5px;margin-top:16px}
button:disabled{opacity:.5}input:focus-visible,button:focus-visible{outline:3px solid #d28622;outline-offset:3px}
article{border-top:1px solid #b7c6be;padding:18px 0;overflow-wrap:anywhere}
#message{min-height:2em}small{color:#435754}h2{font-size:1.2rem}
</style></head><body><main>
<small>TESEO / SERVIZIO LOCALE</small><h1>Collega il tuo vault</h1>
<p>Controlla la cartella e la compatibilità in sola lettura. La consultazione del grafo arriverà nel prossimo incremento.</p>
<form id="attach"><label for="path">Percorso assoluto della cartella vault</label>
<input id="path" name="path" autocomplete="off" spellcheck="false" required placeholder="C:/Obsidian/MioVault">
<button id="connect" disabled>Collega vault</button></form>
<p id="message" role="status" aria-live="polite"></p><section id="vaults" aria-label="Vault collegati"></section>
<p><small>Chiudere questa scheda lascia il servizio attivo. Per arrestarlo usa Ctrl+C nel terminale del launcher.</small></p>
</main><script nonce="__NONCE__">
(() => {
 const token = new URLSearchParams(location.hash.slice(1)).get('session');
 history.replaceState(null, '', location.pathname);
 const message = document.getElementById('message');
 let csrf = '';
 async function api(path, data) {
   const headers = {'X-Teseo-Session': token};
   const options = {headers, cache: 'no-store'};
   if (data !== undefined) {
     options.method = 'POST'; headers['Content-Type'] = 'application/json';
     if (csrf) headers['X-Teseo-CSRF'] = csrf;
     options.body = JSON.stringify(data);
   }
   const response = await fetch(path, options);
   const body = await response.json();
   if (!response.ok) throw new Error(body.error?.message || 'Servizio non disponibile');
   return body;
 }
 async function refresh() {
   const body = await api('/api/v1/vaults');
   const container = document.getElementById('vaults'); container.replaceChildren();
   for (const vault of body.vaults) {
     const article = document.createElement('article');
     const title = document.createElement('h2'); title.textContent = vault.path;
     const state = document.createElement('p');
     state.textContent = 'Sola lettura · ' + (vault.compatibility === 'legacy_readonly' ? 'Vault legacy' : 'Formato compatibile');
     article.append(title, state); container.append(article);
   }
 }
 document.getElementById('attach').addEventListener('submit', async event => {
   event.preventDefault(); const button = document.getElementById('connect'); button.disabled = true;
   try {
     await api('/api/v1/vaults/attach', {path: document.getElementById('path').value});
     await refresh(); message.textContent = 'Vault collegato. Nessun file modificato.';
   } catch (error) { message.textContent = error.message; }
   finally { button.disabled = false; }
 });
 (async () => {
   if (!token) { message.textContent = 'Apri il collegamento completo stampato dal launcher per iniziare una sessione.'; return; }
   try {
     csrf = (await api('/api/v1/session', {})).csrf_token;
     await refresh(); document.getElementById('connect').disabled = false;
     message.textContent = 'Servizio pronto. Indica la cartella del vault.';
   } catch (error) { message.textContent = error.message; }
 })();
})();
</script></body></html>"""
