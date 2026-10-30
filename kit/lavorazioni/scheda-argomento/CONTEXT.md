# Scheda di argomento

Una scheda su un argomento: la pagina scelta e quelle collegate, riordinate in una scaletta che l'utente può correggere prima
della stesura. Legge la wiki e non la scrive.

## Fasi

| Fase | Chi la svolge | Cosa produce |
| --- | --- | --- |
| `01-raccolta` | lo script | `raccolta.md`, la pagina e il suo sottografo |
| `02-scaletta` | l'agente, con checkpoint | `scaletta.md`, da correggere a mano |
| `03-stesura` | l'agente, con checkpoint | `scheda.md` |
| `04-verifica` | l'agente | `verifica.md`: la scheda contro scaletta e raccolta |

## Come si usa

- A ogni esecuzione chiedi l'argomento e passalo: `python .graph/lavorazioni.py avvia <nome> --param argomento="Nome della pagina"`.
- Configurazione stabile in `config.md` (profondità, massimo di pagine, destinatari, stile); per impostarla chiedi di «impostare» la lavorazione.
- La scaletta è il punto in cui correggere costa meno: la stesura segue il file com'è sul disco.
- La scheda rientra nella wiki solo come nuova fonte in `raw/`, seguita da un ingest.
