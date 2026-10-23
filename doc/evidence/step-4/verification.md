# Verifica ECC — punto 4 completo

## Implementazioni

- 4.1 `86a654c`: registry/coda persistenti, fasi ingest e lint, snapshot e ricevute.
- 4.2 `e97faa4`: adapter manuali, probe versioni e launcher ricevute installato.
- 4.3 `7ad8ab7`: validazione/attribuzione, apply manuale e evento locale atomico.
- 4.4: UI, matrice capacità e queste evidenze; commit successivo sullo stesso branch.

ECC orch-add-feature per suddivisione e revisione, security-review,
verification-loop, frontend-design-direction per il contratto e il controllo UI,
conventional-commit-review per i commit. La delega iniziale ai sottoagenti è
fallita per limite d'uso: implementazione e revisione eseguite direttamente,
senza dichiarare una revisione indipendente inesistente.

## Risultati

| Verifica | Esito |
| --- | --- |
| Suite completa finale | 209 test: 208 pass, 1 skip symlink Windows noto; 323.495 s |
| Suite completa precedente | 206 test: 205 pass, 1 skip; 365.817 s |
| Test finali coordinator | 17 pass; 83.128 s, inclusi creazione atomica, limite ricevute ed errore prima dell'evento |
| Test adapter finali | 3 pass; 0.086 s, incluso launch_or_handoff senza processo |
| Installer `--prova --dashboard` | Tutti i controlli pass, fixture temporanea rimossa |
| Installazione e aggiornamento effettivi | Launcher, ricevute e validatore usati dal runtime installato |
| Python compileall e `node --check` client assemblato | Pass |
| Revisione diff e ricerca esecuzione shell/segreti nelle nuove implementazioni | Nessun rilievo; nessuna nuova dipendenza |

Il ciclo deterministico prova: ricevuta duplicata, token falso, contenuto diverso,
manifest alterato, selezione/scope, raw modificato o nuovo, identità cambiata,
eliminazione pagina, alias/link/fonti/schema, sintesi invalide e ID risposte
condivise respinti. Fasi distinte ingest riuscito/lint fallito, attesa umana,
continuazione esplicita/rifiuto, timeout, stop, coda e ripartenza del coordinator.
Apply solo dopo prepared e conferma manuale; race e crash del motore Windows
coperti anche dalle regressioni 3.4. Nuova nota applicata, guasto dopo tutti i
Markdown, rollback con backup e digest originale ripristinato. Guasto prima
dell'evento lascia recovery, finish esplicito emette una sola attestazione.

Gli script ostili nella fixture e nella copia non sono eseguiti; il verificatore
sintesi usa il codice fidato del runtime e una copia sacrificabile senza DB
personali. Ricevute/capacità sono locali e ignorate da Git, assenti dalle GET e
dalle evidenze. Body ordinari 16 KiB, ricevute 256 KiB, diff completi 256 KiB.

## Browser ECC reale

Launcher installato, poi aggiornato e riavviato sulla fixture sacrificabile.
Creazione lint con Enter, handoff Codex, ricevuta CLI awaiting_user, continuazione
esplicita, modifica della sola copia, ricevuta CLI riuscita, prepared senza
pubblicazione. Diff visibile e apply senza conferma rifiutato dalla UI; conferma
ed Enter portano a succeeded con un solo file attribuito e Pubblicabile: sì.

Runtime finale: fill_gaps con Copilot, ricevuta awaiting_user e rifiuto fino a
cancelled/Pubblicabile: no. Probe UI con caricamento e pulsante disabilitato,
versioni reali dei tre binari. Vault compatibile vuoto senza grafo: nessuna
operazione; fonte inesistente dà errore comprensibile. Vault legacy: form assente.

Desktop 1440x900 e mobile 390x844: DOM renderizzato, nessun overflow, label
collegate, controlli almeno 44 px e nessuna animazione. File picker MCP bloccato
dal suo perimetro: il JSON del vero launcher è stato inserito nel controllo File
tramite DataTransfer; esercitato il parser file della UI, non il picker nativo.
Artefatti strutturati locali, non screenshot. Servizi arrestati con uscita 0.

## Limiti e gate

Nessuna sessione AI o login provider avviati nelle prove: ricevute sintetiche,
probe reali e handoff reali. Le versioni sono osservazioni del 23 ottobre 2026,
non una certificazione di avvio/isolamento/callback nativi. Matrice per ogni
client in client-versions.json e nel documento del punto 4. Tutti usano fallback
manuale; verificare directory e consensi nella sessione del client.

Nessuna esclusione garantita di editor esterni; apply Windows locale fisso con
conferme e backup, automatico disabilitato. Semantica dichiarata dal client e
revisionata dall'utente; controlli del servizio deterministici, lint parziale
esplicito. Risposte/eventi condivisi e rinomine/eliminazioni di pagine attendono
il passo 5; pubblicazione Git è il passo 6. Nessun invio di dati a servizi esterni.
Snapshot, output e attestazioni conservati; retention futura. Nessun audit
screen reader/cross-browser. Coverage, type checker e linter dedicati non
configurati; non viene dichiarata una percentuale di coverage.
