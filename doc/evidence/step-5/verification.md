# Verifica ECC — passo 5

Fixture sintetiche, Windows, 23 ottobre 2026. Nessun vault utente modificato.
Workflow ECC: schema e migrazione, revisione sicurezza, verification-loop,
direzione frontend e prove renderizzate con Chrome DevTools ECC.

- Suite generale: 252 test, 251 superati e un salto noto per symlink Windows,
  462.734 s. Dopo questa esecuzione: 18 test del proiettore e 9 del servizio
  superati con gli ultimi controlli su rinvii, cronologia e sidecar.
- Migrazione: 6 test superati, incluso conteggio storico dei rinvii.
- Pipeline: 11 test superati. Ultima prova clone ripetuta dopo rafforzamento del
  confronto entities/relations/aliases e chiusura esplicita SQLite: superata,
  28.216 s. Stesso digest, proiezione e grafo, senza DB personali.
- Installer `--prova --dashboard`: superato. Runtime realmente installato,
  aggiornato e avviato su loopback; nessun modello AI eseguito.
- Compilazione Python, sintassi JavaScript assemblato, revisione diff e controlli
  su esecuzione dinamica/segreti. Nessun type checker o linter configurato nel
  repository. Coverage del nucleo misurata prima degli ultimi rinforzi: 89%;
  non è coverage dell'intera consegna.

## Flussi osservati

Desktop 1440×900: stato vuoto, creazione con consenso ed Enter, due risposte
divergenti conservate, risoluzione causale esplicita, export selettivo con zero
righe inizialmente scelte. Lint con ricevuta UUID: diff nota/evento, conferma
manuale, checkpoint riuscito. Solo la risposta selezionata diventa applicata;
le altre restano archiviate. Pubblicazione sempre non verificata.

Mobile 390×844: nessun overflow, label collegate, controlli almeno 44 px,
nessuna animazione. Parent assente mostrato pending; vault legacy senza form
di scrittura. Rinvio dopo risoluzione conserva la decisione; il test copre una
nuova risposta divergente che riapre il conflitto. Cronologia conserva motivi.

Preview finale: provenienza non certificata visibile, zero selezioni, export
disabilitato e marker personale escluso. Hash invariati dei DB originali e dei
raw sintetici documentati in `immutability.json`.

Durante le prove un job con digest ormai vecchio è stato bloccato correttamente.
Un'esecuzione pipeline parallela alla suite generale ha superato il timeout HTTP
del solo test: aumentato il limite del client test, ripetuta con esito positivo.
La prova clone rafforzata inizialmente teneva aperte due connessioni nel test:
corretto il cleanup Windows e ripetuta con esito positivo.

## Limiti

File ricevuta inserito con DataTransfer sul vero JSON generato dalla CLI; picker
nativo non testato. Nessun audit screen reader o cross-browser. Nessuna prova
di AI nativa o pubblicazione Git dalla dashboard. Apply automatico disabilitato.
Il publisher e l'attribuzione UUID→commit restano al passo 6. La ricostruzione
confronta dati condivisi; la memoria personale resta locale.
