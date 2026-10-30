# Verifiche dell'integrazione ICM (piano 14)

Data: 30 ottobre 2026. Branch `ICM_Integration`, da `codex/dashboard-foundations` (`0e8e440`). Metodo: ECC `tdd-workflow` (test per primi,
commit separato della fase rossa), `verification-loop` (lint, tipi, suite, ricerca di segreti, revisione del diff) e `security-review`.
Esiti e limiti di ogni voce: [piano 14](../../14-piano-icm.md#esiti).

## Risultati sull'intero branch (Linux, Python 3.13)

| Controllo | Esito |
| --- | --- |
| `ruff check .` | nessun rilievo |
| `mypy` (42 file) | nessun errore |
| `python -m unittest discover -s tests` | **849 test superati**, 4 saltati (i 4 già noti: collegamenti simbolici e Windows); 587 prima del piano |
| `python installa.py --prova` | tutto OK, nelle varianti predefinita, `--dashboard`, `--client codex`, `--client copilot`, `--client claude` |
| `python script/genera_api_doc.py --check` | `doc/api.md` aggiornato |
| `contratti.py` sulle 5 skill | tutte valide (restano avvisi di lunghezza, non errori) |
| Browser, Chromium 1440×900 e 390×844 | 28 controlli del pannello superati, nessun errore in console, nessuna richiesta di scrittura, nessun overflow ([screenshot](lavorazioni-desktop.png), [mobile](lavorazioni-mobile.png)) |

Il browser si riproduce con `python tests/dashboard_lavorazioni_fixture.py DIRECTORY_NUOVA` e `node tests/dashboard_lavorazioni_smoke.js URL`.

## Misure

- **Contesto di `Wiki reference.md`** (`contratti.py --peso`, caratteri/4): `ingest` e `lint` ~4.410 token; `query` e `lacune` ~3.089 (−30%); una
  `query` che non archivia ~839 (−81%).
- **Espressioni regolari con input ostili** (`security-review`): prima 2,8 s con 20.000 `[` su una riga e minuti con 200.000; dopo, 168 prove con
  input da 200.000 caratteri, caso peggiore 485 ms.

## Difetti trovati durante la verifica

1. Grafo non aperto nei vault gestiti dalla dashboard (`14fa53d`): lo vedeva solo `installa.py --prova --dashboard`; i test usavano vault non gestiti.
2. Espressioni regolari quadratiche in `verifica` e `piano.py`; `avvia` scriveva dentro `esecuzioni/` anche se era un collegamento simbolico (`829e417`).
3. `elenco` seguiva una lavorazione che era un collegamento simbolico verso l'esterno; `stato` leggeva fuori da `wiki/` o si rompeva con identificatori
   ostili o enormi nel registro dell'esecuzione (`a89c19d`).
4. Più errori miei nei test, scoperti dal loro stesso fallimento e corretti prima del codice: un'aspettativa che contraddiceva la regola «solo l'ultima
   mano conta» (A5), un nome file oltre il limite del filesystem, un codice HTTP sbagliato (400, non 422).

## Non provato

- **Nessun client AI autenticato**: il comportamento del modello con le skill riscritte (A2), con il piano di ingest (A3), con la lettura selettiva dello
  schema (A4) e nelle fasi di scrittura delle lavorazioni (B2) non è verificato. Non sono stati eseguiti `skill-comply` né le 10 domande del gate di A4.
- **Condivisione tra più persone**: B5 non è implementata nel repository dati; `correzioni.py` non è stato provato su un vault collaborativo reale.
- **Altri sistemi operativi e browser, lettori di schermo**: la CI (Linux, Windows, macOS) e gli altri browser non rientrano in questo documento.
