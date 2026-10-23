# Contratto UI ECC · passo 5

Superficie: pannello «Risposte e decisioni condivise» nella dashboard locale.
Lettore: autore che vuole registrare una risposta, revisionare conflitti causali o scegliere righe legacy da condividere.
Direzione: strumento quieto e leggibile, con le stesse tipografie, colori e controlli del workbench esistente. Riferimenti locali: pannelli ontologia e cicli ingest/lint.

Azione principale: registrare una risposta solo dopo conferma esplicita della condivisione. Stati «registrata», «applicata alle note» e «pubblicata» distinti; nessuna pubblicazione attestata senza mapping del publisher del passo 6.

Vincoli verificabili:
- Testo del vault, JSON e righe legacy tramite textContent; nessun HTML eseguibile.
- Preview export separata dall'export. Selezione iniziale vuota; ogni riga deve essere scelta. Telemetria e memoria personale escluse per default.
- Avviso sulla riservatezza e sulla storia Git preesistente. Nessuna promessa di cancellazione dai clone.
- Conflitti visibili senza last-write-wins; nuova decisione riferita alle teste causali osservate, con motivo esplicito.
- Vault legacy consultabile, senza controlli di mutazione. Operazioni asincrone invalidate quando cambia vault o epoch.
- Etichette associate, messaggi aria-live, focus visibile, controlli almeno 44px secondo stile esistente; checkbox con dimensioni compatte e bersaglio etichettato.
- Desktop 1440x900 e mobile 390x844; testi lunghi e JSON non devono causare overflow della pagina.

| Stato | Trigger | Feedback | Azione successiva |
| --- | --- | --- | --- |
| Loading | Lettura o richiesta esplicita | Messaggio stabile aria-live; controlli temporaneamente disabilitati | Attendere esito; nessuna ripetizione automatica della scrittura |
| Empty | Nessuna risposta/conflitto/preview | Indicazione esplicita di assenza | Registrare risposta o richiedere preview |
| Error | API negata, conflitto o rete | Codice e motivo testuali; esito incerto mantiene identità richiesta | Riprovare stessa richiesta o aggiornare stato |
| Partial | Parent mancanti o stato non applicato | Pending e conflitti esposti separatamente | Importare dopo acquisizione parent o decisione causale |
| Success | Risposta/decisione/export accettato | Esito locale e identità restituita, pubblicazione distinta | Rileggere proiezione |
| Permission | Legacy o consenso assente | Spiegazione e pulsante disabilitato | Usare vault compatibile o selezionare consenso esplicito |

Il gate finale richiede osservazioni browser reali ai due viewport. Questo contratto non attesta da solo l'esecuzione del gate.
