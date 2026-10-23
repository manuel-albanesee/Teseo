# Contratto UI e apply manuale 3.4

Scopo: applicare una proposta già revisionata e risolvere un'interruzione
senza cancellare modifiche estranee. Superficie: editor ontologia e registro
operazioni del workbench 3.3, palette e controlli esistenti, nessun nuovo asset.

Azione primaria dopo preview: selezionare le migrazioni con diff delle note,
confermare sospensione degli editor/hook e revisione semantica, applicare
manualmente. Avviso permanente: nessuna esclusione garantita degli editor,
nessun apply automatico. Il journal non è un mutex per Obsidian.

Risultato: operation_id e stato, elenco file modificati dopo successo e refresh
esplicito della generazione. Recovery: elenco persistente readonly, scelta
esplicita completa candidato/ripristina base, conferma e hash corrente.

Viewport 1440x900 e 390x844, tastiera, label, focus, almeno 44 px, messaggi e
digest a capo. Provare attesa, nessuna operazione, errore, recovery richiesto,
successo e apply disabilitato senza conferme; diff e dati del vault sempre testo.
Artefatti browser locali sufficienti, senza invio a servizi esterni.
