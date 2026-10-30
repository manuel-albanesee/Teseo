# 01 — Raccolta

Fase svolta dallo script, non dal modello: sceglie le pagine dal grafo secondo `config.md` e le raccoglie con la loro impronta.

## Input

| Livello | File | Sezione | Perché |
| --- | --- | --- | --- |
| 3 | `../../config.md` | tutto | selezione e parametri della lavorazione |
| 4 | `.graph/graph.sqlite` | pagine e relazioni | unica fonte della selezione |

## Processo

1. `python .graph/build_graph.py > /dev/null`, così il grafo rispecchia le pagine.
2. `python .graph/lavorazioni.py avvia <nome>` applica la selezione (con `--param` solo per questa volta).
3. Lo script scrive la raccolta e il registro dell'esecuzione; non scrive altro.

## Verifica

| Controllo | Come | Esito atteso |
| --- | --- | --- |
| Raccolta non vuota | lettura di `raccolta.md` | almeno una pagina, altrimenti rivedere la selezione |
| Troncamento dichiarato | riga «Pagine:» della raccolta | completa, oppure troncata e accettata dall'utente |

## Output

| Artefatto | Posizione | Formato |
| --- | --- | --- |
| Raccolta | `{esecuzione}/01-raccolta/raccolta.md` | Markdown: tipo, relazioni, fonti, impronta e testo di ogni pagina |
| Registro | `{esecuzione}/esecuzione.json` | JSON con parametri, selezione e impronte |
