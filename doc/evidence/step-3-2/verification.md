# Verifica ECC — passo 3.2

Data: 23 ottobre 2026. Branch `codex/dashboard-foundations`.
Nessun vault personale coinvolto, nessun merge.

## Esiti

| Controllo | Risultato |
| --- | --- |
| `python -m unittest discover -s tests -v` | 172 test, 171 pass, 1 skip symlink Windows noto; 194,736 s |
| `python -m unittest discover -s tests -p test_dashboard_preview.py -v` | 18 pass, rieseguiti sul modulo finale; 41,805 s |
| `python installa.py --prova` | PASS, builder/recall/routing/sintesi/hook installati |
| `python installa.py --prova --dashboard` | PASS, runtime dashboard distribuito e generazione valida |
| `python -m compileall -q kit/dashboard/ontology_preview.py kit/dashboard/server.py kit/dashboard/readonly.py kit/graph/build_graph.py tests/test_dashboard_preview.py` | PASS |
| `git diff --check` | PASS |

La suite completa è stata rieseguita dopo le nuove prove su testo libero,
rinomine e capacità. Dopo gli ultimi limiti sul numero di errori/record condivisi
e l'aggiunta del conteggio tipi derivati, compilazione e 18 regressioni preview
sono state nuovamente eseguite. La prima suite intermedia contava 169 test,
168 pass e lo stesso skip, prima dell'aggiunta degli ultimi tre casi.

Python e server loopback eseguiti fuori sandbox, necessari su questo host;
TMP/TEMP nella root del repository. Installer e unittest puliscono le proprie
directory sacrificabili. Log temporanei di esecuzione rimossi a fine verifica.

## Contratto e prove riproducibili

[Test HTTP](../../../tests/test_dashboard_preview.py) e
[contratto completo](../../03-editor-ontologia.md#api-preview-disponibile-32).
[Esempi effettivamente generati](examples.json) dalla funzione `analyze`, con
fixture incluse nel JSON: aggiunta `approva` valida senza nuove inferenze,
rimozione `usa` usata con pagina/proprietà/target/motivo e rinomina con
suggerimento, mantenendo le note originali. Esempi puri in memoria, senza
sessioni/token o percorsi personali; ID/scadenza sono aggiunti solo dal servizio.

Le 18 prove coprono adozione esplicita e determinismo/replay, candidato escaped
con HTML inerte, preservazione byte esterni alle tabelle, conteggi e violazioni,
`qualsiasi`/`stesso tipo`, rinomina tipo e vincoli, collisione proprietà, YAML
complesso, link/vincoli incompatibili e catene di rinomina rifiutate. Coperti
alias/fonti, link corpo/frontmatter/index, testo libero e record condivisi.

Confrontati hash di tutti i file della fixture prima/dopo preview e replay;
nessuno script del vault eseguito. Schema, note, raw, marker, manifest e DB
personali restano identici. Base stale e modifica durante analisi danno conflitto;
nel secondo caso il risultato non entra in cache. Anche retry di una preview
già pronta ricontrolla la revisione corrente.

Provati richieste concorrenti identiche, conflitto stessa chiave/payload diverso,
cache piena e scaduta, slot occupati, sessione/Origin/CSRF invalidi, JSON duplicato,
operazioni/campi fuori allowlist, body oltre 16 KiB, risposta oltre limite,
schema invalido con dettagli strutturati, frontmatter invalido, grafo assente e
vault legacy. `ontology/apply` rimane 404 e nessuna preview abilita scritture.

## Revisione e limiti

ECC api-design: endpoint v1, errori e precondizioni espliciti, campi allowlist,
idempotenza dichiarata di sessione, limiti e scadenza documentati. Le risposte
usano il digest dello snapshot corrente e `graph_generation: null`, evitando
di attribuire i nuovi contenuti a un vecchio grafo.

ECC security-review: protezioni HTTP esistenti applicate alla nuova POST,
snapshot con path validation e rifiuto link/junction, nessuna scrittura o
esecuzione dal vault. Nessun SQL o nuova dipendenza nel modulo preview.
Schema/diff escaped; modello e nomi sono dati JSON da rendere come testo nella
futura UI. Nessun token/log privato aggiunto alle evidenze. Riferimenti e risultati
limitati prima di dichiarare l'analisi completa; relazioni indicizzate per pagina
e proprietà per evitare scansioni ripetute durante i suggerimenti.

ECC verification-loop: compilazione, regressioni, controlli sicurezza e diff.
Type checker, linter e coverage dedicati non configurati; nessuna percentuale
di coverage o audit online delle dipendenze dichiarati. ECC
conventional-commit-review per il commit finale secondo la storia del repository.
Nessuna UI modificata o nuovo smoke browser, verifiche HTTP reali su loopback.

Preview e idempotenza vivono solo in memoria: riavvio/scadenza invalidano la
disponibilità del risultato. Nessuna conservazione transazionale di proposte
per un futuro apply. Snapshot/hash rilevano modifiche, senza garantire esclusione
atomica degli editor esterni. Analisi semantica del testo e mapping degli eventi
condivisi non implementati: revisione umana e blocchi espliciti, senza promesse
di inferenza automatica. UI 3.3 e apply/recovery 3.4 restano futuri.
