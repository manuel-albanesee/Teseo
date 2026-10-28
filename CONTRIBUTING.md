# Contribuire a Teseo

Grazie per l'interesse. Questa guida copre ambiente, controlli e convenzioni.
Per segnalare un problema o proporre una funzione apri una
[issue](https://github.com/manuel-albanesee/Teseo/issues); per una correzione, una pull request.

## Ambiente di sviluppo

```sh
git clone https://github.com/manuel-albanesee/Teseo.git
cd Teseo
python -m venv .venv          # Windows: py -3 -m venv .venv
# Windows: .\.venv\Scripts\Activate.ps1   ·   macOS/Linux: source .venv/bin/activate
python -m pip install -r kit/vault/requirements.txt
python -m pip install pytest ruff mypy
```

L'unica dipendenza di runtime è PyYAML; pytest, ruff e mypy servono solo per lo sviluppo.

## Controlli prima di una PR

Esegui dalla radice del repository, con l'ambiente attivo:

```sh
python installa.py --prova                  # installazione e controlli end-to-end, senza modelli
python -m unittest discover -s tests -v     # suite completa di regressione
ruff check .                                # lint (configurazione in ruff.toml)
mypy                                        # type check (configurazione in mypy.ini)
python script/genera_api_doc.py --check     # doc/api.md aggiornato
```

Nessuno di questi comandi chiama modelli o servizi esterni. I test usano vault e repository
Git reali in cartelle temporanee; su Windows usano percorsi brevi (`tests/_shortpath.py`).

## Convenzioni

- **Lingua**: codice, docstring, documentazione e messaggi di commit sono in italiano
  (parti della storia recente sono in inglese; per i nuovi contributi vale l'italiano).
- **Docstring**: ogni modulo Python inizia con un docstring che ne descrive il contratto.
  Le funzioni pubbliche hanno un docstring con la prima riga autonoma: finisce in `doc/api.md`.
- **Stile**: `ruff.toml` dichiara le eccezioni volute (es. E701/E702 per lo stile compatto);
  non «correggere» ciò che la configurazione esclude.
- **Dipendenze**: nessuna nuova dipendenza senza discussione in issue; il kit installato nei
  vault deve restare leggero (oggi: solo PyYAML).
- **Dati dei test**: niente fixture con dati personali o riservati; il vault d'esempio
  (`kit/esempio/`) è fittizio e deve restare tale.
- **Commit**: messaggi nel formato `tipo(scope): descrizione` (es. `feat(dashboard): ...`,
  `fix(graph): ...`, `docs: ...`), come nella storia del repository.

## Modificare la documentazione

| Modifica | File da aggiornare |
| --- | --- |
| Comportamento visibile all'utente | `README.md` e, se riguarda un vault esistente, `ADATTA.md` |
| Modulo o funzione pubblica | docstring nel codice, poi `python script/genera_api_doc.py` |
| Architettura del motore (grafo, recall, memoria, hook) | `doc/architettura-motore.md` |
| Piano dashboard/collaborazione | il documento del passo in `doc/` e il registro `doc/08-analisi-avanzamento.md` |
| Funzionalità consegnata | voce in `CHANGELOG.md` sotto «Non rilasciato» |
| Skill del vault | `kit/skills/<nome>/SKILL.md` e le istruzioni client in `kit/vault/` |

## Cosa aspettarsi dalla revisione

Ogni PR deve dichiarare il comportamento atteso e i controlli eseguiti. Per contratti,
migrazioni e sincronizzazione (passi 1, 4, 5, 6, 7 di `doc/`) la revisione è approfondita;
per UI readonly e fixture è ordinaria. Le modifiche agli hook dei client devono mantenere
la convivenza fra Claude Code, Codex e Copilot CLI: i test `test_codex.py` e
`test_copilot.py` sono il riferimento.
