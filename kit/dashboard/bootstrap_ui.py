"""Workbench locale: asset fidati, contenuti del vault inseriti come testo."""
from .ui_style import STYLE
from .ui_script import SCRIPT

PAGE = """<!doctype html>
<html lang="it"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Teseo · Consulta il vault</title><style nonce="__NONCE__">""" + STYLE + """</style></head>
<body><a class="skip" href="#workspace">Vai alla consultazione</a>
<header><strong>TESEO</strong><span>CONSULTAZIONE LOCALE</span><span class="badge">Note in sola lettura</span></header>
<div class="shell"><aside aria-label="Collegamento vault">
<h1>Il tuo vault</h1><label for="vault">Vault collegati</label><select id="vault" disabled><option value="">Nessun vault collegato</option></select>
<details><summary>Collega una cartella</summary><form id="attach">
<label for="path">Percorso assoluto del vault</label><input id="path" autocomplete="off" spellcheck="false" required placeholder="C:/Obsidian/MioVault">
<button id="connect" disabled>Collega vault</button></form></details>
<p id="message" role="status" aria-live="polite">Avvio della sessione…</p>
<button id="shutdown" disabled>Arresta servizio</button>
<p class="hint">Chiudere la scheda lascia il servizio attivo. Puoi arrestarlo qui oppure con Ctrl+C nel terminale.</p>
</aside><main id="workspace" tabindex="-1">
<div class="heading"><div><p class="eyebrow">ESPLORA LE CONNESSIONI</p><h2>Consultazione</h2></div><div class="actions"><button id="refresh" disabled>Aggiorna vista</button><button id="rebuild" disabled>Ricostruisci grafo</button></div></div>
<p id="root" class="path">Collega un vault per iniziare.</p><p id="revision" class="hint"></p>
<p id="notice" role="status" aria-live="polite"></p>
<p id="operation" role="status" aria-live="polite"></p>
<nav aria-label="Viste del vault"><button data-view="graph" aria-pressed="true">Grafo</button><button data-view="ontology" aria-pressed="false">Ontologia</button><button data-view="diagnostics" aria-pressed="false">Diagnostica</button></nav>
<section id="graph" aria-label="Grafo">
<form id="filters" class="toolbar"><div><label for="type">Tipo</label><select id="type" disabled><option value="">Tutti i tipi</option></select></div>
<div><label for="relation">Relazione</label><select id="relation" disabled><option value="">Tutte le relazioni</option></select></div>
<div><label for="search">Cerca nei nodi caricati</label><input id="search" type="search" disabled></div><button id="apply" disabled>Applica filtri</button></form>
<p id="counts" class="hint">Nessun dato caricato.</p><div id="map"></div>
<div class="columns"><section aria-label="Elenco nodi"><h3>Nodi</h3><ul id="nodes" class="node-list"></ul><button id="more" hidden>Carica altri</button></section>
<section id="detail" aria-label="Dettaglio nodo" tabindex="-1"><h3>Dettaglio nodo</h3><p>Seleziona un nodo dalla lista o dal grafo.</p></section></div>
<details><summary>Relazioni caricate · sorgente → destinazione</summary><ul id="edges"></ul></details>
</section>
<section id="ontology" aria-label="Ontologia" hidden></section><section id="diagnostics" aria-label="Diagnostica" hidden></section>
</main></div><script nonce="__NONCE__">""" + SCRIPT + """</script></body></html>"""
