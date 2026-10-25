# Verifica UI ECC — passo 7

25 ottobre 2026, Windows e Chrome DevTools ECC. Solo fixture sintetiche: due
clone Git e remoto bare locale, con factory `allow_local_remote` abilitata
esclusivamente nel processo di prova. Nessun repository GitHub dati contattato.

## Risultati osservati

- Receiver inizialmente idle/sospeso, consensi falsi e adozione disabilitata.
- Controllo esplicito: messaggio di caricamento e comandi disabilitati;
  successivamente pending, OID/hash e diff testuale della sola nota cambiata.
  La generazione consultata resta precedente fino alla conferma.
- Attivazione dal controllo dedicato e persistenza del poll dopo chiusura
  della scheda: ultimo controllo avanzato da 1792895316 a 1792895380, senza
  avanzare HEAD o modificare il DB personale sintetico. Pausa dalla UI riuscita.
- Consenso di adozione separato, focus visibile e attivazione con **Enter**:
  transazione `current`, HEAD fast-forward, Git pulito e `vault.updated`.
  **Aggiorna vista** mostra digest e generazione del checkpoint ricevuto.
- Nessun job AI: tabella operations vuota. Il journal può creare il DB locale
  delle operazioni; ciò non equivale all'avvio di ingest/lint.
- Bare remoto temporaneamente assente: `git_invalid_remote`, stato incompatible
  e diagnostica visibile; generazione applicata preservata e apply disabilitato.
  Remote ripristinato dopo la prova. Questo scenario non simula una vera
  interruzione di rete GitHub.
- Il marker del contenuto del DB personale non appare nella UI e i suoi byte
  restano identici. Nessun campo password/token è presente.
- Nuova nota remota con diff lungo: preview troncata a 20.000 caratteri,
  avviso esplicito e apply disabilitato anche con consenso. Markup script
  mostrato come testo, senza esecuzione e senza overflow mobile.

Viewport emulati e misurati: **1440x900** e **390x844**. Nessun overflow;
checkbox con label collegata e area cliccabile del testo, altezza dei controlli
almeno 44 px, focus desktop con outline visibile, nessuna animazione. Screenshot
mobile ispezionato: testi e pulsanti si adattano alla colonna. Nessun audit con
screen reader, cross-browser o verifica contrasto strumentale completa.

## Correzioni emerse

Il primo controllo con il clock reale ha trovato timestamp float incompatibili
con il JSON canonico v1 (`error.json`): corretti nel core e riprovati con successo.
La UI ora distingue preparazione da validazione/apply e rende diff e hash come
testo inerte. Preview incomplete o troncate bloccano l'adozione dalla vista.
Questo include sorgenti non rappresentabili nel formato della preview, come
testo non NFC; non è autorizzata la normalizzazione dei byte sorgente.
Il recovery usa B/R/digest della transazione originale, anche dopo cancellazione
del pending; il comportamento di recovery del filesystem è verificato nei test
del servizio, senza rivendicare una prova browser di ogni interruzione.

HTTP: tre test receiver superati in 0.301 s, con routing dei cinque POST e
guard sessione, Origin e CSRF. Sintassi JavaScript e whitespace verificati.
La suite generale, installer e prove Git del servizio sono riportati nella
verifica complessiva del root, non dedotti da questa prova UI.

Artefatti locali JSON: desktop, mobile, loading, empty, pending, success,
remote-error, background e immutability. Il report `ui-report.json` è validato
con il checker della skill ECC frontend-design-direction. Gli artefatti
descrivono osservazioni reali; il checker non sostituisce la revisione visiva.
