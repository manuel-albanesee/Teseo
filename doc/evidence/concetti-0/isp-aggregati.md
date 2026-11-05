# Basi della fase 0 sul vault ISP (solo numeri aggregati)

Misure del 5 novembre 2026 con il codice di `bd5eaaa` (branch `ICM_Integration`, prima della fase 1), su una copia del vault ISP fuori dal
repository: `wiki/` (217 pagine), `Wiki reference.md`, `index.md`, `log.md`. Nessun modello chiamato. Nel repository non
ci sono domande, nomi di pagina né testi del vault.

Adattamenti della copia, come nel vault: `recall.PAROLE_COMUNI` e `build_graph.PAROLE_COMUNI_NOMI` con «visto» e
«rapporto» (documentati nella Wiki reference del vault); le domande di `misura.py` sono quelle del vault (17 domande).

## Grafo

217 pagine, 69 fonti · 2030 menziona, 859 documentato_in, 224 tipizzate, 212 alias · `build_graph.py --check`: nessun
problema. Forme di nome per K1 (`coerenza.nomi_del_grafo`): 718, di cui 217 canoniche, nessuna pagina persa per forme
ambigue.

## Recall sulle domande del vault (`misura.py`)

| Misura | Base |
| --- | --- |
| Pagine attese portate | 41/41 sulle 17 domande · token medio ~862 |
| Semi spuri | 0/14 casi |
| Ripiego sul testo | 23/23 casi OK |
| Memoria, prompt in sospeso | 28/28 casi OK |
| Attesi falliti | 6 ancora KO · 0 ora OK |

## Banco (bozza del 5 novembre 2026, 69 voci, 9 parafrasi)

Il banco del 27 ottobre (106 domande, [kpi-recall](../../kpi-recall.md)) non è più nel vault. La bozza nuova è scritta
dal materiale di `banco.py --semi` senza le parole dei titoli (`banco.py --verifica`: nessun problema) ed è da rileggere
dall'autore: questi numeri non sono confrontabili con quelli del 27 ottobre e valgono come base solo dopo la rilettura.

| Misura | Tutte | Locali (65) | Globali (4) |
| --- | --- | --- | --- |
| Pagine attese portate | 62/110 (56%), dal solo grafo 22 | 54/89 (61%) | 8/21 (38%) |
| Domande complete | 40/69 | 39/65 | 1/4 |
| Rumore medio | 12.4 pagine | 12.5 | 10.8 |
| Token medio | 575 | 586 | 405 |
| Domande senza semi dal grafo | 53 (35 con il ripiego T) | 50 (34) | 3 (1) |

Le 2 domande fuori tema non portano pagine.

K3, stabilità fra parafrasi: 9 voci, 9 parafrasi · stabilità media 0.07 · stesso seme 0/9. Sette parafrasi su nove non
hanno semi né dal grafo né dal ripiego e non portano pagine; la domanda originale li aveva. Il recall dipende dalle
parole esatte: è il caso che la fase 3a (sinonimi interni) deve migliorare.

## Peso dello schema (K4, `contratti.py --peso --radice <vault>`)

Livello 3: ingest ~8275, lint ~8275, query ~7022, lacune ~7022 token (vault d'esempio: 4555, 4555, 3234, 3234).

## Mancano

K1 e K2: servono `claude -p` e il via dell'autore. Le stesse misure con il codice delle fasi 1–5 (il «dopo») non sono
ancora fatte.
