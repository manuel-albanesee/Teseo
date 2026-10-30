# Collaudo con editor non cooperante (2026-10-30)

- Sistema: Windows-11-10.0.26200-SP0 · Python 3.13.14 · Teseo 1.0.0
- Giri eseguiti: 20 di 20 · salvataggi dello scrittore: 505
- Obsidian aperto sul vault: sì, solo sul vault giro-1-R, aperto prima dell’avvio (confermato dall’utente)
- Esito: **SUPERATO** (nessun byte dello scrittore perso né sovrascritto; recovery_required: 40, rifiutato: 20)
- `recovery_required` è l'esito previsto quando un salvataggio arriva durante la scrittura: i dati sono salvi ma il vault resta fermo in `recovery_required` finché una persona non risolve.

| Giro | R (raffica: note estranee salvate di continuo durante preview e apply) | N (una nota estranea viene salvata proprio mentre l'apply scrive) | P (la pagina che l'apply sta per creare viene creata dall'editor mentre l'apply scrive) | Controllo |
| --- | --- | --- | --- | --- |
| 1 | rifiutato blocked_external_change | recovery_required recovery_conflict | recovery_required recovery_conflict | OK |
| 2 | rifiutato blocked_external_change | recovery_required recovery_conflict | recovery_required recovery_conflict | OK |
| 3 | rifiutato blocked_external_change | recovery_required recovery_conflict | recovery_required recovery_conflict | OK |
| 4 | rifiutato blocked_external_change | recovery_required recovery_conflict | recovery_required recovery_conflict | OK |
| 5 | rifiutato blocked_external_change | recovery_required recovery_conflict | recovery_required recovery_conflict | OK |
| 6 | rifiutato blocked_external_change | recovery_required recovery_conflict | recovery_required recovery_conflict | OK |
| 7 | rifiutato blocked_external_change | recovery_required recovery_conflict | recovery_required recovery_conflict | OK |
| 8 | rifiutato blocked_external_change | recovery_required recovery_conflict | recovery_required recovery_conflict | OK |
| 9 | rifiutato blocked_external_change | recovery_required recovery_conflict | recovery_required recovery_conflict | OK |
| 10 | rifiutato blocked_external_change | recovery_required recovery_conflict | recovery_required recovery_conflict | OK |
| 11 | rifiutato blocked_external_change | recovery_required recovery_conflict | recovery_required recovery_conflict | OK |
| 12 | rifiutato blocked_external_change | recovery_required recovery_conflict | recovery_required recovery_conflict | OK |
| 13 | rifiutato blocked_external_change | recovery_required recovery_conflict | recovery_required recovery_conflict | OK |
| 14 | rifiutato blocked_external_change | recovery_required recovery_conflict | recovery_required recovery_conflict | OK |
| 15 | rifiutato blocked_external_change | recovery_required recovery_conflict | recovery_required recovery_conflict | OK |
| 16 | rifiutato blocked_external_change | recovery_required recovery_conflict | recovery_required recovery_conflict | OK |
| 17 | rifiutato blocked_external_change | recovery_required recovery_conflict | recovery_required recovery_conflict | OK |
| 18 | rifiutato blocked_external_change | recovery_required recovery_conflict | recovery_required recovery_conflict | OK |
| 19 | rifiutato blocked_external_change | recovery_required recovery_conflict | recovery_required recovery_conflict | OK |
| 20 | rifiutato blocked_external_change | recovery_required recovery_conflict | recovery_required recovery_conflict | OK |

## Conclusioni

- **Nessun byte dell'editor perso o sovrascritto** in 20 giri e 505 salvataggi (Windows 11, Python 3.13, Obsidian aperto sul vault del primo giro).
- **R (raffica)**: l'apply è sempre rifiutato prima di scrivere (`blocked_external_change`).
- **N e P**: un salvataggio che arriva mentre l'apply scrive porta a `recovery_required` con `recovery_conflict`. I dati sono salvi ma il vault resta fermo finché una persona non risolve; finish e rollback sono rifiutati finché il file estraneo differisce dalla base. È coerente con la conferma `manual_paused` (editor sospesi) ma è un limite d'uso da dichiarare.
- Un primo run aveva segnato un apply appeso per 60 s nel giro 8 (scenario R) con un `PermissionError` dello scrittore; non si è ripetuto nel run successivo e non è stato spiegato. La caccia (`--scenari R --giri 100`) è facoltativa.
- Obsidian era aperto solo sul vault del primo giro: la misura dell'effetto dell'indicizzazione è limitata a quel giro.
