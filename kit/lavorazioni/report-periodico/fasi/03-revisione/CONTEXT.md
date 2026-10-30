# 03 — Revisione

Controlla la bozza contro la raccolta e produce il report finale.

## Input

| Livello | File | Sezione | Perché |
| --- | --- | --- | --- |
| 3 | `../../config.md` | «Stile» | regole da far rispettare |
| 4 | `{esecuzione}/02-sintesi/sintesi.md` | tutto, com'è sul disco dopo le correzioni dell'utente | testo da rivedere |
| 4 | `{esecuzione}/01-raccolta/raccolta.md` | tutto | riscontro di ogni affermazione |

## Processo

1. Per ogni affermazione trova nella raccolta la frase che la sostiene.
2. Correggi refusi, ripetizioni e collegamenti sbagliati; non cambiare il senso.
3. Elenca in `note-revisione.md` ciò che non regge o non trova riscontro, senza inventare.
4. Scrivi il report pulito, senza note di lavorazione.

## Checkpoint

| Dopo il passo | L'agente presenta | L'utente decide |
| --- | --- | --- |
| 3 | le affermazioni senza riscontro e le correzioni fatte | se toglierle, riscriverle o lasciarle come ipotesi |

## Verifica

| Controllo | Come | Esito atteso |
| --- | --- | --- |
| Ogni `[[Pagina]]` citata è nella raccolta | confronto dei collegamenti | nessun collegamento estraneo |
| Ogni affermazione ha un riscontro | rilettura contro `raccolta.md` | o è sostenuta, o è in `note-revisione.md` |

## Output

| Artefatto | Posizione | Formato |
| --- | --- | --- |
| Report | `{esecuzione}/03-revisione/report.md` | Markdown pulito |
| Note | `{esecuzione}/03-revisione/note-revisione.md` | elenco dei problemi non risolti |
