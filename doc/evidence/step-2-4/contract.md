# Contratto UI e distribuzione 2.4

Riferimento: workbench locale 2.3. Stessa carta crema, verde e focus arancio;
nessuna dipendenza o risorsa esterna. Primaria azione esplicita Ricostruisci grafo,
adiacente ad Aggiorna vista. Esito separato dai dati pubblicati, vecchia vista
consultabile durante il job. Arresta servizio nella colonna del collegamento.
Viewport 1440x900 e 390x844; controlli impilati/wrapping, focus tastiera e nessun
overflow documento. Note e DB personali non vengono modificati dal rebuild.

Stati: richiesta/caricamento con pulsante disabilitato, grafo mancante con azione
compatibile disponibile, errore parsing/semantica con ultima vista intatta,
dati parziali e job in corso, successo con refresh esplicito, legacy/sessione
assente con controlli non disponibili. Arresto richiede sessione e CSRF e attende
i worker cooperanti. Registro solo su opzione CLI, mai implicito nell'attach.

Installazione nuova: --dashboard esplicito su cartella vuota. Legacy non adottati.
Aggiornamento --aggiorna con backup runtime; nessuna migrazione di note o DB.
