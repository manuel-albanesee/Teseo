# Verifica ECC — apply manuale e recovery 3.4

Fixture sacrificabili Windows, nessun vault personale coinvolto. Skill ECC:
database-migrations (backup, candidato isolato e ripristino verificato),
verification-loop, frontend-design-direction/frontend-a11y già usate per il
workbench, conventional-commit-review per il commit finale.

## Copertura

`tests/test_dashboard_apply.py`: successo schema e replay persistente, rinomina
proprietà con byte note preservati, selezione parziale/sconosciuta respinta,
scadenza/hash/If-Match/conferme, sessione/CSRF, duplicato concorrente e conflitto,
fallimento prima/dopo replace, schema assente dopo errore parziale, recupero dopo
riavvio del registro, blocco rebuild e letture readonly. Crash reale del processo
con exit 23 dopo la prima nota di un candidato multi-file, poi rollback esplicito.
Test tipo scalare con BOM/CRLF/quote/commento e rifiuto di duplicati/anchor YAML.

Race tra hash e replace: dati estranei conservati nel backup nativo, successivi
finish/rollback bloccati. Modifica ulteriore dopo failure mai sovrascritta.
Gate piattaforma: processo esterno scrive sotto VaultLock cooperativo; risultato
non protetto, apply automatico sempre disabilitato. Non è una certificazione di
isolamento o una promessa di esclusione degli editor esterni.

Polling recovery: una prima prova browser ha rilevato che lo stato persistente
recovery_required faceva arrestare la UI prima della fine del worker; aggiunta
regressione e ripetuto il flusso installato fino a rolled_back.

## Browser e distribuzione

Runtime effettivamente installato con `--dashboard`, fixture di due note e
schema sintetico. Enter sul pulsante apply dopo due conferme ha applicato il
solo catalogo tipi, mostrando succeeded e file modificati. Fonti, note e DB
personali verificati identici. Rinomina successiva con fault controllato dopo
la prima nota: elenco persistente, conferma e «Ripristina base» fino a rolled_back,
nota ripristinata byte per byte. Nessun restore manuale delle note necessario.

Artefatti browser DOM renderizzato a 1440x900 e 390x844, label connesse, controlli
alti almeno 44 px, nessun overflow documento o animazione, tastiera Enter.
Nessuna cattura di vault reali, nessuna evidenza inviata a servizi esterni.
Report strutturato e checker ECC nel [report](report.json).

## Risultati riproducibili

| Controllo | Esito |
| --- | --- |
| `python -m unittest discover -s tests -v` | 189 test, 188 pass, 1 skip symlink Windows noto; 386.396 s |
| Quattro test mirati finali (successo/replay, gate esterno, due migrazioni byte) | 4 pass, 11.238 s; ripetuti dopo aggiunta gate volume locale |
| `python installa.py --prova --dashboard` | Tutti i controlli pass, fixture rimossa |
| `python -m compileall -q kit/dashboard tests/test_dashboard_apply.py tests/test_dashboard_preview.py` | Pass |
| `node --check` del client assemblato | Pass |
| Revisione diff e ricerca segreti/esecuzione shell nelle nuove implementazioni | Nessun rilievo |
| Checker ECC `frontend-design-direction/scripts/check-evidence.js` sul report | Pass; verifica completezza degli artefatti, non certifica qualità visiva |

Il gate del volume usa [GetDriveTypeW](https://learn.microsoft.com/en-us/windows/win32/api/fileapi/nf-fileapi-getdrivetypew)
e accetta soltanto DRIVE_FIXED. I backup usano
[ReplaceFileW](https://learn.microsoft.com/windows/win32/api/winbase/nf-winbase-replacefilew),
con fault injection anche sul caso di destinazione temporaneamente assente.

## Limiti dell'apply

Atomicità logica con journal, non multi-file nativa. Backup anche della versione
effettivamente rimpiazzata, ma nessun isolamento garantito da editor attivi.
Serve sospensione esplicita di editor/hook per il percorso manuale. Mapping
di pagine/eventi richiede il passo 5; dati condivisi presenti bloccano apply.
Snapshot e backup conservati, retention futura. Niente replay automatico dopo
crash o rollback cieco di modifiche estranee. Percorso testato Windows locale,
non altre piattaforme/filesystem remoti, screen reader o cross-browser.
Coverage, type checker e linter dedicati non configurati; nessuna nuova dipendenza.
