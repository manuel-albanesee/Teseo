# Basi della fase 0 di doc/17 sul vault d'esempio

Misure del 5 novembre 2026 sul branch `ICM_Integration` (commit `a8bd949`), vault d'esempio installato in una cartella
temporanea con `python installa.py <cartella> --client claude --esempio`. Nessun modello chiamato.

| File | Comando | KPI |
| --- | --- | --- |
| `banco-esempio-base.txt`, `banco-esempio-base.json` | `python .graph/misura.py --solo-banco --banco-salva banco-esempio-base.json` (dal vault) | recall del banco, K3, token medio di K4 |
| `peso-skill.txt` | `python kit/graph/contratti.py kit/skills/*/SKILL.md --radice kit/vault --peso` (dal repository) | K4, token di livello 3 |

La colonna `ms` del banco varia da un lancio all'altro e non è una base. K1 e K2 mancano: richiedono `claude -p`
(costano, solo con il via dell'autore). Le basi del vault ISP (task 0.4b) mancano: il vault non è su questo computer.
