# Contratto UI ECC — receiver

Superficie: pannello Git della dashboard locale, insieme al publisher già
disponibile. Scopo: vedere una revisione remota, revisionare un candidato
isolato e adottarlo con consenso esplicito. Nessun apply automatico.

Direzione: strumento operativo sobrio, con componenti, spaziatura e colori
esistenti. Gerarchia: checkpoint remoti e stato, diff/hash dei file, rilevamento
opt-in, adozione manuale separata. Nessun asset o dipendenza nuovi.

Viewport: **1440x900** e **390x844**, emulati e misurati nel browser. Verificare
assenza di overflow, label collegate, consenso inizialmente falso, focus visibile,
attivazione con tastiera, controlli alti almeno 44 px e nessuna animazione.

| Stato | Trigger, feedback e azione successiva |
| --- | --- |
| Loading | Controllo remoto esplicito; messaggio aria-live e comandi disabilitati |
| Empty | Receiver idle; campi non disponibili, attivazione solo dopo consenso |
| Error | Errore del controllo mostrato; dati correnti conservati e rilettura possibile |
| Partial | Pending e diff isolato; generazione consultata ancora precedente, apply separato |
| Success | Transazione current e vault.updated; Aggiorna vista rilegge la generazione |
| Permission | Manifest compatibile e configurazione necessari; consenso di rilevamento distinto da quello di adozione |

La preview usa solo testo e ha limiti espliciti. Preview incompleta o troncata
non autorizza l'apply dalla UI. Il recovery usa gli OID della transazione
originale, anche se il receiver ha già cancellato pending dopo un checkpoint.

Riferimenti locali: pannelli publisher/stato condiviso esistenti, contratti dei
passi 1, 6 e 7. Le prove usano fixture sintetiche e un remoto bare locale.
