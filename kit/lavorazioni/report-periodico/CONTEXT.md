# Report periodico

Un report su ciò che è cambiato nella wiki in un periodo: le pagine aggiornate di recente, raggruppate per tema, con
citazioni e punti aperti. Legge la wiki e non la scrive.

## Fasi

| Fase | Chi la svolge | Cosa produce |
| --- | --- | --- |
| `01-raccolta` | lo script | `raccolta.md`, le pagine aggiornate nel periodo |
| `02-sintesi` | l'agente, con checkpoint | `sintesi.md`, la bozza per temi |
| `03-revisione` | l'agente | `report.md` e `note-revisione.md` |

## Come si usa

- Configurazione: `config.md` (periodo, destinatari, massimo di pagine, stile). Per impostarla chiedi di «impostare» la lavorazione.
- Esecuzione: `python .graph/lavorazioni.py avvia <nome>`; per un solo periodo diverso `--param periodo=14g`.
- Avanzamento: `python .graph/lavorazioni.py stato <nome>`. Ogni file in `esecuzioni/` si può rileggere e correggere prima della fase successiva.
- Il report rientra nella wiki solo come nuova fonte in `raw/`, seguita da un ingest.
