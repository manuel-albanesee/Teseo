# Verifica ECC — passo 3.1

Data: 23 ottobre 2026. Branch: `codex/dashboard-foundations`.
Fixture sintetiche; nessun vault personale coinvolto.

## Comandi ed esiti

| Verifica | Esito |
| --- | --- |
| `python -m unittest discover -s tests -v` | 154 test, 153 pass, 1 skip symlink Windows; 182,147 s |
| `python -m unittest discover -s tests -p test_dashboard_queries.py -v` | 14 pass |
| `python -m unittest discover -s tests -p test_dashboard_ontology.py -v` | 18 pass sul parser finale; 14,093 s |
| `python installa.py --prova` | PASS, inclusi builder/recall/routing/sintesi/hook installati |
| `python installa.py --prova --dashboard` | PASS, generazione v3 installata e consultabile |
| `python -m compileall -q kit/graph/ontology.py kit/graph/build_graph.py kit/dashboard/graph_service.py kit/dashboard/read_api.py tests/test_dashboard_ontology.py` | PASS |
| `git diff --check` | PASS |

Su questo host Python e le fixture con server loopback richiedono esecuzione
fuori sandbox. TMP/TEMP puntano alla root del repository per le directory
sacrificabili; unittest e installer effettuano il proprio cleanup.

## Evidenze riproducibili

[Suite ontologia](../../../tests/test_dashboard_ontology.py): 12 test di modello
e 6 integrazioni. Il roundtrip verifica tutte le combinazioni BOM sì/no,
LF/CRLF/CR, newline finale sì/no. Una modifica delle relazioni confronta byte
per byte prefisso e suffisso esterni allo span; una modifica dei tipi conserva
la tabella relazioni. Il template del kit resta legacy e identico al no-op.

La proposta di catalogo verifica hash base, determinismo e byte originali dopo
rimozione del solo inserimento. L'integrazione confronta gli hash dei file del
vault prima/dopo proposta e GET. Le API espongono gli stessi digest/span letti
dal builder, compresi CRLF e caratteri multibyte. Nessun campo aggiunto al manifest.

Nomi riservati, duplicati, vincoli sconosciuti, inversione, celle multilinea,
catalogo vuoto, UTF-8 invalido, dimensioni e Markdown ambiguo sono respinti.
Fence/commenti/HTML/codice indentato non diventano schema. Catalogo e relazioni
non possono fare da censimento fonti. Tipo pagina assente/sconosciuto/non scalare
e schema invalido falliscono senza sostituire la generazione precedente.

Una generazione di prova con metadati v2 e hash coerente resta leggibile senza
scritture, segnala l'upgrade e passa a v3 solo dopo rebuild esplicito. L'aggiunta
di `approva` prova `qualsiasi`/`stesso tipo` e il rifiuto degli archi incompatibili.

## Revisione e limiti

ECC verification-loop: build Python, test, scansione di sicurezza e diff rivisti.
ECC security-review applicata a input schema, risorse limitate, testo inerte,
escaping delle risposte e assenza di nuove scritture/SQL dinamico. Il modulo puro
non importa I/O, subprocess, evaluator o deserializzatori eseguibili; le API
caricano il parser del servizio, mai script dal vault collegato. Confini delle
sezioni calcolati una volta, senza scansione quadratica dei titoli.

ECC conventional-commit-review per il commit finale, secondo la convenzione
`feat(scope): ...` usata nella cronologia del repository.
Type checker, linter e coverage dedicati non configurati: non sono gate
dichiarati superati. Nessuna nuova dipendenza o audit online delle dipendenze.
Nessuna modifica UI di layout e nessuno smoke browser nuovo.

Parser intenzionalmente limitato, con fallback manuale. Non interpreta il
significato di descrizioni/esempi. Proposta in memoria senza endpoint preview,
apply, migrazioni o inferenze automatiche: questi appartengono ai prossimi punti.
