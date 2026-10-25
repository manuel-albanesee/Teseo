# Verifica ECC — passo 7

Windows, 25 ottobre 2026. Solo fixture sintetiche: due clone Git e remoto bare
locale. Nessun repository GitHub dati contattato, nessun vault utente modificato.

Strumenti ECC: lo sviluppo e le prove fino ai commit `0027bd4` e `c4604d2` sono
di Codex con workflow ECC e agenti delegati per core, review e UI. La review
finale del diff è di python-reviewer e security-reviewer; le correzioni sono
state verificate con test mirati e controllo sintattico del JavaScript.

## Risultati

Regressioni isolate senza Git reale (`regressions.json`, eseguite da Codex prima
delle ultime correzioni): **315 test, 314 superati, 1 saltato (symlink Windows),
0 failure, 0 error**. Alcuni moduli hanno richiesto una riprova per cleanup
Windows transitorio. I log grezzi (`regression-logs/`, citati da
`regressions.json`) restano solo nel working tree locale e non sono versionati:
contengono traceback e percorsi locali dell'utente.
Installer `python installa.py --prova --dashboard`: superato.

Suite con Git reale, separate dalle precedenti: `test_dashboard_git_sync` e
`test_sync_pipeline`, 25 test superati (356 s, Codex). Ricezione dopo le
correzioni della review: `test_receiver_apply` classe `Receive` 9 test superati
(185 s), fault injection `test_receiver_apply_faults` 7 test superati (172 s),
`test_receiver_http` 4 test, `test_dashboard_receiver` 22 test.
Sintassi JavaScript del pannello verificata con `node --check`.

Non è stata rieseguita l'intera suite dopo le correzioni della review: i moduli
non toccati dalle correzioni conservano l'esito delle regressioni di Codex.
Copertura misurata solo per `receiver.py`: 94% prima dell'introduzione della
preview limitata; il valore aggiornato non è stato misurato. Nessuna copertura
dell'intero kit è dichiarata. Il repository non configura type checker o linter.

## Prove di integrazione

- Rilevamento: pausa, ripresa, riavvio, backoff, sospensione su errore di
  autenticazione e vault occupato; il polling continua con la scheda chiusa.
- Adozione manuale: note, index e HEAD convergono sulla revisione ricevuta;
  stato personale invariato; un lettore SQLite già aperto vede la vecchia
  generazione; l'esito è idempotente.
- Fault injection (7 casi): ref esterna prima del CAS, index mancante, crash dei
  metadati, sostituzione parziale con rollback, ripristino esterno durante la
  ricostruzione, preparazione orfana, crash dopo journal terminale.
- Note ed eventi condivisi ricevuti insieme convergono sulla stessa revisione e
  ricostruiscono la proiezione.
- Un difetto trovato dalla prova reale: timestamp decimali incompatibili con il
  JSON canonico v1 (`error.json`). Corretto con regressione dedicata.

## Prove renderizzate

Chrome DevTools ECC, 1440×900 e 390×844, descritte in
[ui-verification.md](ui-verification.md) con artefatti JSON: stati loading, empty,
pending, success, errore remoto, preview troncata, polling in background e
immutabilità del DB personale. Nessun overflow, controlli di almeno 44 px,
nessuna animazione, nessun campo password/token. Le correzioni UI della review
finale (sotto) non sono state riprovate nel browser.

## Correzioni dalla review finale

Python reviewer e security reviewer non hanno trovato problemi bloccanti.
Corretti, con regressioni:

- `preview` azzerata dopo `finish`, `rollback` e negli stati `diverged` e
  `incompatible`: la UI non mostra più una revisione di un candidato già
  applicato, annullato o superato.
- `GET /sync/status` non fallisce più se lo stato del receiver o della
  transazione non è leggibile (symlink rifiutato, SQLite corrotto): l'errore è
  riportato nel solo campo interessato, senza dettagli interni.
- `ReceiverApplyService.apply` rifiuta preview assente o troncata
  (`receiver_preview_incomplete`) anche senza passare dalla UI; il digest deve
  essere esadecimale minuscolo di 64 caratteri.
- UI: il consenso esclusivo è consumato a ogni tentativo di adozione o recovery
  (non resta spuntato dopo un errore); `recovery_required` del receiver abilita
  finish/rollback; il messaggio "candidato isolato" richiede un candidato reale.

## Limiti materiali

Apply automatico non qualificato e disabilitato: buffer non salvati e salvataggi
di editor non cooperanti non sono rilevabili; l'adozione richiede sospensione
manuale degli scrittori. Ricezione verificata solo su Windows con volume locale
fisso. Nessuno smoke GitHub reale, nessun client AI autenticato, nessun audit
screen reader o cross-browser, nessuna verifica strumentale completa del contrasto.

Rilievi noti non risolti: `resume` non richiede un consenso lato server (il
polling riparte al riavvio del servizio dopo il consenso UI); ogni fetch crea
una ref `refs/teseo/fetch/<uuid>` che non viene eliminata (codice precedente);
il cleanup dei test in `test_dashboard_git_sync` usa `shutil.rmtree(onerror=...)`,
deprecato da Python 3.12. Non esiste un test del markup JS del pannello: la
logica dei pulsanti è verificata solo dalla prova renderizzata.
