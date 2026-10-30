# 02 — Sintesi

Scrive la bozza del report a partire dalla sola raccolta.

## Input

| Livello | File | Sezione | Perché |
| --- | --- | --- | --- |
| 3 | `../../config.md` | «Destinatari», «Stile» | per chi scrivere e con quali regole |
| 3 | `../../riferimenti/stile-report.md` | tutto | struttura del report |
| 4 | `{esecuzione}/01-raccolta/raccolta.md` | tutto | unica fonte dei fatti |

## Processo

1. Leggi la raccolta. Non leggere altre pagine della wiki e ignora il recall automatico: i fatti sono quelli della raccolta.
2. Raggruppa le pagine per tema, usando tipo e relazioni, e ordina i temi per importanza per i destinatari.
3. Scrivi per ogni tema che cosa è cambiato, con `[[Pagina]]` su ogni affermazione.
4. Riporta contraddizioni e `⚠️ da verificare` presenti nelle pagine, senza risolverli.
5. Elenca i punti aperti e le pagine considerate.

## Checkpoint

| Dopo il passo | L'agente presenta | L'utente decide |
| --- | --- | --- |
| 5 | la bozza, con l'elenco dei temi in testa | struttura, tono e cosa togliere prima della revisione |

## Verifica

| Controllo | Come | Esito atteso |
| --- | --- | --- |
| Ogni paragrafo cita almeno una pagina | rilettura della bozza | nessun paragrafo senza `[[Pagina]]` |
| Nessun fatto fuori dalla raccolta | confronto con `raccolta.md` | nessuno |
| Nessun «da verificare» risolto per conto proprio | ricerca del marcatore | marcatori invariati |

## Output

| Artefatto | Posizione | Formato |
| --- | --- | --- |
| Bozza | `{esecuzione}/02-sintesi/sintesi.md` | Markdown, struttura di `stile-report.md` |
