# 15 — Decisione: condivisione delle lavorazioni

Stato: **proposta del 30 ottobre 2026 (voce B5 del [piano 14](14-piano-icm.md)). La condivisione delle lavorazioni tramite il repository
dati non è implementata: il contratto dati non cambia. È disponibile la condivisione manuale con `esporta` e `nuova --modelli`.**
Se il proprietario del progetto sceglie diversamente, i punti da modificare e i criteri per riaprire la decisione sono in fondo.

## Decisione

- Le lavorazioni restano **personali**: `lavorazioni/` è esclusa da Git nei vault collaborativi e non fa parte del perimetro dati
  ([01](01-contratto-dati-operazioni.md)).
- Per condividerne una: `python .graph/lavorazioni.py esporta NOME CARTELLA` copia la definizione (contratti, `config.md`, `setup/`,
  `riferimenti/`; mai le esecuzioni né i collegamenti simbolici) fuori dal vault. Chi la riceve la importa con
  `python .graph/lavorazioni.py nuova NOME --da NOME --modelli CARTELLA`, che **avvisa** che i `CONTEXT.md` sono istruzioni e elenca i
  file copiati. La skill chiede all'utente di leggerli prima di avviare.
- Il canale (posta, cartella condivisa, repository Git separato) è dell'utente e fuori dal perimetro di Teseo.

## Perché non nel repository dati

1. **Il perimetro dello snapshot non lo permette senza una modifica a cascata.** `storage._scan` percorre `DEFAULT_SHARED_PATHS` come
   perimetro dei dati, a prescindere dal manifest, e rifiuta con `unexpected_data_path` qualsiasi file di tipo sconosciuto. Una
   cartella `lavorazioni/` con un'esecuzione (`esecuzione.json`) lo farebbe fallire in ogni vault. Inoltre l'impronta dello snapshot è
   la base di concorrenza di job e apply: modificare un `config.md` diventerebbe un «cambiamento esterno» che li blocca.
2. **Sono istruzioni, non dati.** Il gate 6 del [piano dashboard](README.md) dice che i dati ricevuti non attivano script o hook. Un
   `CONTEXT.md` non è uno script, ma il modello lo segue: una pagina della wiki è un fatto da verificare, un contratto è un ordine.
   Condividerli nel repository dati darebbe a chiunque possa scrivere sul remoto (un collaboratore, un account compromesso) un modo
   per far eseguire istruzioni al modello di tutti gli altri. È una scelta di fiducia che spetta al proprietario, come la decisione
   sull'[apply automatico](13-decisione-apply-automatico.md).
3. **Non si può provare qui.** Servirebbero due account reali e un client AI autenticato ([12](12-piano-autenticazione-e-collaudo-avanzato.md)).
4. **Compatibilità.** Un manifest che elenca `lavorazioni/` in `shared_paths` verrebbe rifiutato dai kit attuali (`invalid_shared_paths`):
   servirebbe alzare `KIT_VERSION` e il `minimum_kit_version` del manifest.

## Che cosa servirebbe per farlo

| Punto | File | Cambiamento |
| --- | --- | --- |
| Allowlist opt-in | `kit/dashboard/contracts.py` | `OPTIONAL_SHARED_PATHS = ("lavorazioni/",)` accettata da `parse_manifest` ma **non** in `DEFAULT_SHARED_PATHS` (nessuna condivisione di istruzioni per impostazione predefinita) |
| Tipo di percorso | `contracts.py` | `PathKind.LAVORAZIONE` per contratti, `config.md`, `setup/` e `riferimenti/`; `esecuzioni/` e `_ingest/` restano `LOCAL` |
| Versione | `contracts.py`, manifest | `KIT_VERSION` 1.1.0; `minimum_kit_version` 1.1.0 nei manifest che abilitano la voce |
| Perimetro dello snapshot | `kit/dashboard/storage.py` (`_scan`, righe 184–185, 220, 234) | perimetro dal manifest, salto di `esecuzioni/` e `_ingest/`, nuovo tipo accettato |
| Pubblicazione e integrazione | `kit/dashboard/git_sync.py` (`_allowed`, riga 486) | nuovo tipo ammesso, solo testo, con i limiti di dimensione e la ricerca di segreti già in uso |
| Esclusioni Git | `installa.py` (`LOCALI`) | `lavorazioni/` non più esclusa per intero: solo `esecuzioni/` e `_ingest/` (pattern portabili) |
| Revisione prima dell'uso | `kit/graph/lavorazioni.py` | registro locale `.teseo/local/lavorazioni-approvate.json` con le impronte; `avvia` rifiuta una lavorazione condivisa la cui definizione è cambiata da altri finché non si esegue `approva NOME` dopo aver letto le differenze |
| Documenti e prove | [01](01-contratto-dati-operazioni.md), [05](05-stato-condiviso.md), [06](06-pubblicazione-github.md), [07](07-ricezione-automatica.md); test con due cloni | stessa nota modificata da due persone, esecuzioni mai pubblicate, definizione cambiata da altri |

## Quando riaprirla

- Una squadra usa davvero le stesse lavorazioni e copiarle a mano è diventato un costo.
- Il proprietario accetta che istruzioni circolino nel repository dati e stabilisce chi può modificarle (branch protetto, revisione
  obbligatoria).
- Il collaudo con due account e un client AI autenticato è tra le prove disponibili.

## Come si bilancia nel frattempo

Il rischio residuo dell'importazione manuale è lo stesso di qualunque file ricevuto da fuori: `nuova --modelli` non può sapere se i
contratti sono sicuri. L'avviso e la richiesta della skill di leggerli prima di avviare sono la misura; `valida` e `contratti.py`
controllano la forma, non le intenzioni.
