"""Workbench locale: asset fidati, contenuti del vault inseriti come testo."""
from .ui_style import STYLE
from .ui_script import SCRIPT

PAGE = """<!doctype html>
<html lang="it"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Teseo · Consulta il vault</title><style nonce="__NONCE__">""" + STYLE + """</style></head>
<body><a class="skip" href="#workspace">Vai alla consultazione</a>
<header><strong>TESEO</strong><span>VAULT LOCALE</span><span class="badge">Scritture solo con apply manuale</span></header>
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
<details><summary>Operazioni persistenti e recovery</summary><button id="list-operations" type="button">Leggi operazioni del vault</button><div id="operation-list"></div></details>
<details id="pages-section" hidden><summary>Pagine · crea, rinomina, elimina</summary><div id="pages-panel"></div></details>
<details id="adopt-section" hidden><summary>Adotta questo vault</summary><div id="adopt-panel"></div></details>
<details><summary>Cicli ingest e lint</summary><div id="skill-panel"></div><button id="skill-dispatch" type="button">Ricontrolla coda</button></details>
<details><summary>Lavorazioni</summary><div id="lavorazioni-panel"></div></details>
<details><summary>Risposte e decisioni condivise</summary><div id="shared-panel"></div></details>
<details><summary>Pubblicazione Git dei dati</summary><div id="sync-panel"></div></details>
<nav aria-label="Viste del vault"><button data-view="graph" aria-pressed="true">Grafo</button><button data-view="ontology" aria-pressed="false">Ontologia</button><button data-view="diagnostics" aria-pressed="false">Diagnostica</button></nav>
<section id="graph" aria-label="Grafo">
<form id="filters" class="toolbar"><div><label for="type">Tipo</label><select id="type" disabled><option value="">Tutti i tipi</option></select></div>
<div><label for="relation">Relazione</label><select id="relation" disabled><option value="">Tutte le relazioni</option></select></div>
<div><label for="author">Autore</label><select id="author" disabled><option value="">Tutti gli autori</option></select></div>
<div><label for="category">Categoria</label><select id="category" disabled><option value="">Tutte le categorie</option></select></div>
<div><label for="search">Cerca nei nodi caricati</label><input id="search" type="search" disabled></div>
<div><label for="map-limit">Nodi nel disegno (12–2000)</label><input id="map-limit" type="number" min="12" max="2000" value="200" disabled></div><button id="apply" disabled>Applica filtri</button></form>
<p id="counts" class="hint">Nessun dato caricato.</p><div id="map"></div>
<div class="columns"><section aria-label="Elenco nodi"><h3>Nodi</h3><ul id="nodes" class="node-list"></ul><button id="more" hidden>Carica altri</button> <button id="load-all" hidden>Carica fino al limite del disegno</button></section>
<section id="detail" aria-label="Dettaglio nodo" tabindex="-1"><h3>Dettaglio nodo</h3><p>Seleziona un nodo dalla lista o dal grafo.</p></section></div>
<details><summary>Relazioni caricate · sorgente → destinazione</summary><ul id="edges"></ul></details>
</section>
<section id="ontology" aria-label="Ontologia" hidden><section id="ontology-editor" aria-label="Proposta ontologia"></section><details><summary>Vocabolario della generazione pubblicata</summary><div id="ontology-published"></div></details></section><section id="diagnostics" aria-label="Diagnostica" hidden></section>
</main></div><script nonce="__NONCE__">""" + SCRIPT + """</script></body></html>"""
