# Contratto UI — pubblicazione dati

Superficie: pannello aggiunto al workbench esistente; nessuna libreria esterna.
Lettura stato → preview precisa → consenso → configurazione → pubblicazione
esplicita di un UUID validato. Inizializzazione locale distinta dal push.

Credenziali delegate a Git; visibilità dichiarata distinta dall'identità autore
e dal permesso remoto. Stato pubblicato distinto dall'adozione locale. B/L/R/C,
errore e perimetro correlato devono permettere una decisione recuperabile.

Preview senza selezioni implicite, byte/hash inclusi ed esclusioni visibili.
Selezione raw modificata invalida consenso e preview. Preview troncata blocca
conferma. Nessun upload arbitrario, merge del kit o force push.

Viewport obiettivo 1440×900 e 390×844, emulati con Chrome DevTools ECC.
Label collegate, aria-live, controlli di almeno 44 px, flusso da tastiera,
nessuna animazione richiesta, nessun overflow del documento. Testi da dati
inseriti con textContent; JSON tecnico bounded e scroll interno.

Stati: loading/disabilitato, non configurato, fallimento recuperabile,
checkpoint pendente, successo converged e consenso/legacy senza scrittura.
PR mode deve dire che apertura e merge PR restano manuali. Il primo rilascio
non attiva l'automazione continuativa o il receiver.
