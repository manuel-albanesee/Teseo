# Contratto UI — editor ontologia 3.3

Scopo: preparare modifiche allo schema e capire conseguenze e direzione prima
di una futura applicazione. Pubblico: autore/manutentore del vault locale.
Azione primaria: «Genera preview», dopo composizione esplicita della patch.

Riferimento locale: workbench 2.3/2.4, tipografia di sistema, carta/verde, bordi
semplici, focus arancio. Nessun nuovo framework, asset remoto o animazione.
Gerarchia: confine preview/scrittura, base e adozione esplicita, form orientato
sorgente → destinazione, elenco modifiche, esito/diff/impatto e limiti semantici.

Viewport da provare: 1440x900 e 390x844. Campi a due colonne su desktop e
impilati su mobile, testo lungo a capo e pre con scorrimento confinato. Controlli
almeno 44 px, label connesse, errori annunciati, focus sul risultato e tastiera.

Stati: caricamento preview con invio duplicato disabilitato; lista vuota con
invito ad aggiungere una modifica o proporre il catalogo; errori con dettagli
pagina/proprietà/motivo e retry; schema pubblicato stale o assente distinguibile
dalla base corrente; successo con diff e nessuna inferenza/apply impliciti;
manifest legacy/sessione mancante con confine leggibile. Bozza conservata in
memoria per vault, nessun localStorage; risultati obsoleti e risposte tardive
non presentati come preview corrente. Applica non disponibile in questo passo.
