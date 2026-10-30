# 13 — Decisione: apply automatico

Stato: **decisione confermata dal proprietario del progetto (2026-10-30): l'apply automatico resta non previsto, per scelta di prodotto.** Chiude il punto 12 di [11](11-piano-completamento.md). Se il proprietario sceglie diversamente, i criteri in fondo dicono che cosa servirebbe.

## Decisione

**L'apply automatico non è previsto.** Resta disabilitato in modo permanente: nessun flag di richiesta, di configurazione o di ambiente lo abilita, e le capacità `ontology_apply_automatic` ed `external_writer_exclusion` restano `false` per contratto. Ogni scrittura delle note da parte del servizio dashboard (apply dell'ontologia, apply delle skill, editor del grafo, ricezione manuale) richiede la conferma esplicita `mode: manual_paused` con editor e hook esterni sospesi e revisione dei cambiamenti.

## Che cosa è automatico e che cosa no

| Automatico (opt-in per vault, già in uso) | Sempre con conferma esplicita |
| --- | --- |
| `pre` (pull) e `post` (commit e push) chiamati dalle skill | Qualunque scrittura delle note da parte del servizio dashboard |
| Pubblicazione dopo una modifica dell'editor del grafo (se l'autosync è attivo, con consenso dato una volta) | Apply dell'ontologia, delle skill e dell'editor: `manual_paused` + revisione |
| Avviso di aggiornamenti remoti all'avvio della sessione (solo lettura) | Ricezione manuale di un candidato remoto, risoluzione dei conflitti, decisioni semantiche |

La distinzione è voluta: la sincronizzazione scambia commit già validati con regole deterministiche e si ferma su conflitti reali; l'apply riscrive file che un editor (Obsidian) può avere aperti con modifiche non salvate.

## Motivi

1. **Nessuna esclusione degli scrittori esterni.** Il lock del vault coordina il servizio e i client cooperanti; un processo esterno lo ignora (lo dimostra il test del processo esterno in `tests/test_dashboard_storage.py`). Hash e HEAD rilevano la scrittura concorrente dopo, non la impediscono.
2. **Perdita di lavoro non recuperabile.** Un apply automatico durante una modifica in Obsidian può sovrascrivere buffer non salvati: l'unica mitigazione oggi è la conferma umana che gli editor siano sospesi.
3. **Dati insufficienti.** La prova con editor non cooperanti reali (punto 5 di `doc/11`) non è stata svolta; il collaudo con GitHub reale ([rapporto](evidence/step-11/collaudo-github.md)) ha coperto la sincronizzazione, non l'apply sotto concorrenza con un editor.
4. **Il guadagno è piccolo.** L'apply manuale è un clic con una conferma; l'automazione che conta (pull e push) è già disponibile senza scrivere note a nome dell'utente.

## Criteri per riaprire la decisione

Un apply automatico si può proporre solo se, insieme: (a) esiste un'esclusione reale degli scrittori (per esempio un vault riservato con blocco a livello di sistema operativo rispettato dagli editor, o un editor integrato), provata su Windows, macOS e Linux; (b) il recovery supera 20 prove ripetute con Obsidian reale che salva durante l'apply, senza perdita di byte; (c) è un'opzione per vault, spenta di default, con consenso esplicito e revocabile, mostrata nell'interfaccia; (d) diventa un gate di rilascio con test e rapporto di evidenza; (e) il contratto dei dati ([01](01-contratto-dati-operazioni.md)) è aggiornato prima del codice.

## Effetti sul codice e sui test

Nessuna modifica: il comportamento attuale è quello deciso. I test che lo fissano restano (`capabilities.ontology_apply_automatic` e `external_writer_exclusion` falsi in `tests/test_dashboard_apply.py`; `manual_confirmation_required` per ogni apply senza conferma).
