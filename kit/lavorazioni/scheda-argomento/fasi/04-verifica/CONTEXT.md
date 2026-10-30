# 04 — Verifica

Confronta la scheda con la scaletta e con la raccolta: la fase 4 si controlla contro le fasi 2 e 1, non solo contro la 3.

## Input

| Livello | File | Sezione | Perché |
| --- | --- | --- | --- |
| 4 | `{esecuzione}/03-stesura/scheda.md` | tutto | testo da verificare |
| 4 | `{esecuzione}/02-scaletta/scaletta.md` | tutto, com'è sul disco | struttura promessa |
| 4 | `{esecuzione}/01-raccolta/raccolta.md` | tutto | riscontro dei fatti |

## Processo

1. Controlla che la scheda abbia tutte e solo le sezioni della scaletta.
2. Per ogni affermazione trova nella raccolta la frase che la sostiene.
3. Controlla che lacune e `⚠️ da verificare` della raccolta siano dichiarati nella scheda.
4. Scrivi `verifica.md`: una riga per ogni discrepanza, con la sezione e il motivo. Non correggere la scheda.

## Verifica

| Controllo | Come | Esito atteso |
| --- | --- | --- |
| Sezioni coerenti con la scaletta | confronto dei titoli | nessuna differenza non dichiarata |
| Affermazioni con riscontro | confronto con `raccolta.md` | tutte, oppure elencate in `verifica.md` |
| Lacune dichiarate | ricerca dei marcatori nella scheda | tutte presenti |

## Output

| Artefatto | Posizione | Formato |
| --- | --- | --- |
| Esito | `{esecuzione}/04-verifica/verifica.md` | elenco delle discrepanze, vuoto se non ce ne sono |
