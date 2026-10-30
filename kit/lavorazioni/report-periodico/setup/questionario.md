# Impostazione del report periodico

Fai tutte le domande insieme, in un solo messaggio. Ogni domanda ha un valore predefinito: chi non risponde lo accetta.
Scrivi le risposte in `config.md` e non chiedere di nuovo ciò che non cambia.

1. Che periodo copre di norma il report? (predefinito: 7g; esempi: 14g, 2s) → `parametri.periodo`
2. Per chi è scritto? (predefinito: team operativo) → `parametri.destinatari`
3. Quante pagine al massimo? (predefinito: 40) → `selezione.massimo`
4. Quali tipi di pagina includere? (predefinito: tutti; esempi: processo, sistema) → `selezione.tipi`
5. Che tono? (predefinito: sobrio) → sezione «Stile» di `config.md`

Il periodo di una singola esecuzione si cambia con `--param periodo=...`, senza toccare `config.md`.
