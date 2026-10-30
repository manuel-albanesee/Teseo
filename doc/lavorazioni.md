# Lavorazioni

Una **lavorazione** è una pipeline ripetibile che legge la wiki e produce un documento derivato (un report, una scheda, una
scaletta). Applica al vault il metodo ICM (Interpretable Context Methodology): cartelle numerate per le fasi, un contratto per
fase, file di testo che l'utente può leggere e correggere tra una fase e l'altra. La wiki resta la conoscenza; la lavorazione è il
lavoro che se ne ricava. Piano e motivazioni: [14](14-piano-icm.md), [analisi](analisi-icm-ecc.md).

**Non scrive mai** in `wiki/`, `raw/`, `index.md` o `log.md`. Un risultato entra nella wiki solo come nuova fonte in `raw/`,
seguita da un ingest.

## Struttura

```text
lavorazioni/report-periodico/
  CONTEXT.md              scopo, fasi, come si usa
  config.md               la «fabbrica»: frontmatter (selezione, parametri) e regole di stile
  setup/questionario.md   domande di impostazione, con predefiniti
  riferimenti/            regole stabili comuni alle fasi
  fasi/01-raccolta/CONTEXT.md   un contratto per fase (Input, Processo, Checkpoint, Verifica, Output)
        02-sintesi/  03-revisione/
  esecuzioni/2026-10-30-1/      il «prodotto» di ogni esecuzione
    esecuzione.json             parametri, selezione, impronte
    01-raccolta/raccolta.md     02-sintesi/sintesi.md …
```

La prima fase è la **raccolta** e la svolge lo script, non il modello. Sceglie le pagine dal grafo e le scrive in `raccolta.md`
con tipo, relazioni, fonti e impronta SHA-256. Le fasi successive leggono solo la raccolta: così la memoria di Teseo non registra
letture di `wiki/` che l'utente non ha chiesto, e ogni output è riconducibile alle pagine da cui nasce.

## Comandi

| Comando | Cosa fa |
| --- | --- |
| `python .graph/lavorazioni.py elenco` | lavorazioni del vault e ultima esecuzione |
| `python .graph/lavorazioni.py nuova NOME --da MODELLO` | crea da un modello (`.graph/modelli/`) o da un'altra lavorazione, senza le sue esecuzioni |
| `python .graph/lavorazioni.py valida NOME` | controlla config, fasi e contratti (anche con `contratti.py`) |
| `python .graph/lavorazioni.py avvia NOME [--param chiave=valore]` | nuova esecuzione e raccolta |
| `python .graph/lavorazioni.py stato NOME` | pipeline in ASCII (o `--json`) |

Le fasi dopo la raccolta le esegue il client AI con la skill `obsidian-wiki-lavorazioni` («esegui la lavorazione X»): legge il
contratto della fase, carica solo gli Input, scrive l'output, esegue la Verifica e si ferma ai Checkpoint.

## Configurazione

`config.md` ha un frontmatter con `selezione` e `parametri`; il resto è prosa con le regole di stile che le fasi caricano per sezione.

| Chiave di `selezione` | Significato |
| --- | --- |
| `collegate_a` | pagina di partenza, `"[[Pagina]]"` o `"Pagina"` (tra virgolette in YAML) |
| `domanda` | domanda i cui nomi di pagina riconosciuti dal recall sono punti di partenza |
| `profondita` | passi dalla partenza lungo le relazioni (predefinito 1) |
| `relazioni` | relazioni da seguire in entrambe le direzioni (predefinito: tutte le tipizzate, non `menziona` né `documentato_in`) |
| `tipi` | solo pagine di questi tipi |
| `modificate_da` | `7g` (giorni) o `2s` (settimane), sul campo `aggiornato` |
| `massimo` | tetto di pagine (predefinito 40); se taglia, la raccolta lo dichiara |

Senza punti di partenza si parte da tutte le pagine. Un valore `"{nome}"` è sostituito dal parametro omonimo; `--param` sovrascrive un
parametro (`--param periodo=14g`) o una chiave di selezione (`--param selezione.massimo=5`) **solo per quell'esecuzione** e la
registra in `esecuzione.json`. Gli override non usano YAML: il tipo lo decide la chiave, e `[[Pagina]]` resta un testo.

## Modelli inclusi

| Modello | Fasi | Checkpoint |
| --- | --- | --- |
| `report-periodico` | raccolta delle pagine aggiornate nel periodo → sintesi per temi → revisione | sulla bozza |
| `scheda-argomento` | raccolta del sottografo di una pagina → scaletta → stesura → verifica contro scaletta e raccolta | sulla scaletta, dove correggere costa meno, e sulla prima sezione |

La scheda richiede l'argomento a ogni esecuzione: `avvia NOME --param argomento="Nome della pagina"`.

## Limiti

- Le lavorazioni sono **personali**: `lavorazioni/` è esclusa da Git nei vault collaborativi, perché un file non tracciato
  fermerebbe la sincronizzazione prima di ogni skill. Condividerne le definizioni è una voce a parte del piano.
- Un'esecuzione alla volta per lavorazione; nessun ramo automatico fra fasi: decide l'utente.
- Il recall automatico arriva comunque a ogni prompt: la skill dice di ignorarlo durante le fasi.
- Il comportamento del modello nelle fasi di scrittura non è verificato da test automatici: sono provati il motore, i contratti e
  la raccolta.
