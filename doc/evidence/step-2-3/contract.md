# Contratto UI 2.3

Consultare una generazione pubblicata: scegliere cartella, filtrare tipo/relazione,
selezionare nodo, leggere testo, fonti e problemi. Nessuna mutazione.
Riferimento locale: bootstrap esistente, carta crema e verde bosco; gerarchia
compatta da strumento di lavoro, senza immagini decorative o dipendenze esterne.

Viewport: 1440x900 e 390x844. Su mobile colonne impilate; lista equivalente al
grafo, etichette e focus visibile. Contenuti lunghi devono andare a capo.
Grafo limitato a 12 nodi/80 archi, pagine da 50, conteggi dei soli dati caricati.
Markdown mostrato come testo inerte. Ricerca limitata ai nodi caricati.

Stati: caricamento, vuoto, errore rete, parziale/paginazione, successo/dettaglio,
sessione assente, stale e cambio generazione con refresh esplicito.
Risposte tardive non devono contaminare la vista dopo cambio vault o dettaglio.
