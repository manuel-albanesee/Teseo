# Il recall come KPI della salute del vault

Il recall dice se, a una domanda fatta con parole normali, il grafo porta nel contesto del modello le pagine
giuste. Se il recall cala, il modello risponde da pagine sbagliate o cerca alla cieca anche quando il vault
contiene la risposta. Per questo il recall sul banco è un indicatore della salute del vault, accanto a
`build_graph.py --check`, alle domande aperte e a `sintesi.py --verifica` (tabella «Segnali di salute»
di `Wiki reference.md`).

Riferimenti: [architettura del motore](architettura-motore.md), §4 (pipeline di recall);
`kit/graph/misura.py`, `kit/graph/banco.py` e `kit/graph/candidati.py` (le docstring sono la specifica).

## Due misure diverse

| Misura | Dove | Ruolo |
| --- | --- | --- |
| Domande di prova | `DOMANDE`, `NEGATIVI`, `TESTO` in `.graph/misura.py` | **Regressione**: poche domande scritte con i nomi delle pagine. Il valore sano è il massimo (tutte le pagine attese, semi spuri 0, exit 0). Se fallisce, si è rotto qualcosa. |
| Banco | `.graph/banco.json` | **KPI**: domande scritte *senza* le parole dei titoli, come le farebbe un collega. Non arriva mai al 100% e non fa uscire con 1: si segue nel tempo. |

Questo documento riguarda il banco.

## Cosa si misura

`python .graph/misura.py --solo-banco` stampa per ogni domanda e poi in sintesi:

```
banco: pagine attese portate 88/134 (66%), dal solo grafo 34 · domande complete 69/106 ·
rumore medio 13.7 pagine · token medio 582 · domande con 0 semi dal grafo: 77 (di cui 51 con il ripiego T)
```

| Metrica | Significato | Verso buono |
| --- | --- | --- |
| Pagine attese portate | Pagine attese che il recall mette nel contesto, su tutte le domande | ↑ |
| Dal solo grafo | Quante arrivano da nomi, alias e relazioni, senza il ripiego sul testo | ↑ |
| Domande complete | Domande per cui arrivano *tutte* le pagine attese | ↑ |
| Rumore medio | Pagine portate ma non attese, in media per domanda | ↓ |
| Token medio | Peso del contesto aggiunto (caratteri/4) | stabile o ↓ |
| Domande con 0 semi dal grafo | Il grafo non riconosce nulla: ci si affida al ripiego (`T`) | ↓ |

La percentuale da sola inganna: un recall che porta tutto ha il 100% e un rumore inutilizzabile.
Pagine portate, domande complete e rumore vanno lette insieme.

## Perché il massimo non è un numero fisso

Il denominatore è la **somma delle pagine `attese` di tutte le domande del banco**. Nel vault ISP, il
27-10-2026: 106 domande, di cui 74 con una pagina attesa, 20 con due, 4 con tre, 2 con quattro e 6 con
nessuna (casi negativi: la domanda è fuori tema e il recall non deve portare nulla). Il totale è
74 + 40 + 12 + 8 = **134**.

Il massimo cambia ogni volta che una domanda entra, esce o cambia le sue `attese`. Per questo:

- si confrontano solo misure fatte **sullo stesso banco**;
- quando il banco cambia si salva una nuova baseline, senza sovrascrivere la vecchia (nome con la data);
- un calo dopo aver aggiunto domande difficili non è un peggioramento del vault.

## Come e quando misurare

```bash
python .graph/misura.py --solo-banco --banco-salva .graph/banco_base_AAAA-MM-GG.json      # baseline
python .graph/misura.py --solo-banco --banco-confronta .graph/banco_base_AAAA-MM-GG.json  # confronto
```

Il confronto classifica ogni domanda come MIGLIORATA, PEGGIORATA o invariata (pagine attese, poi rumore e
token) e chiude con un saldo. Va lanciato:

- alla fine di ogni lint (la skill lo prevede quando scrive pagine per entropia);
- dopo un ingest che aggiunge o rinomina pagine;
- dopo modifiche ad `aliases`, relazioni tipizzate, `PAROLE_COMUNI` o agli script di `.graph/`;
- dopo un aggiornamento del kit che tocca `recall.py`.

Regola: **pagine portate e domande complete non calano, il rumore non cresce, ogni domanda PEGGIORATA ha
un motivo noto**. Se il calo è il prezzo accettato di una scelta di precisione, si annota il motivo nel
`log.md` del vault e si salva una nuova baseline datata.

Esempio reale: dal 9-10 al 27-10-2026 il vault ISP è sceso da 95/134 a 88/134 con il rumore medio in
crescita. Le pagine perse sono quasi tutte domande parafrasate senza semi dal grafo («il sistemino che cerca
gli errori», «il codice della settimana», «quando i file atterrano in data\in») che prima il ripiego sul
testo agganciava. Il ripiego è diventato più severo: esclude le parole troppo frequenti e chiede parole
vicine entro `FINESTRA_TESTO`. Guadagna precisione, ma queste pagine ora vanno recuperate dal grafo con
alias e relazioni.

## Strategie per migliorarlo

In ordine di resa. Dopo ogni gruppo di modifiche: `build_graph.py --check`, poi il confronto con la baseline.

1. **Leggere il banco per domanda, non il totale.** Le domande KO senza semi dal grafo (`semi` = 0) sono un
   problema di vocabolario; quelle con semi che perdono pagine sono un problema di relazioni. Nel vault ISP
   29 domande su 34 KO non avevano semi: la leva principale è il vocabolario.
2. **Alias dal parlato.** Per ogni pagina mancata spesso, aggiungere ad `aliases` le forme con cui la si
   chiama davvero: abbreviazioni («prod» per Rilascio in produzione), parafrasi ricorrenti («manifesto di
   collaudo», «codice della settimana»), cognomi e nomi brevi delle persone. Un alias deve indicare una sola
   pagina: niente parole comuni (finirebbero in `PAROLE_COMUNI`) né forme condivise.
3. **`candidati.py`** (sola lettura) propone alias, termini e relazioni ricavati dalle pagine e dal banco,
   con le avvertenze `ambiguo`, `conflitto`, `parola_comune`, `condivisa`. Si accettano a mano solo quelli
   senza avvertenze e confermati dal testo della pagina.
4. **Relazioni tipizzate su hub e pagine isolate.** Il cammino oltre il primo passo segue solo relazioni
   tipizzate: una pagina senza `parte_di`, `usa`, `richiede`, `referente` non porta i suoi vicini. Si
   dichiarano solo le relazioni che il testo afferma.
5. **Memoria promossa.** Le domande ricorrenti in `python .graph/memoria.py` sono vocabolario reale:
   si promuovono ad `aliases` della pagina giusta.
6. **Ridurre il rumore.** Le domande con il rumore più alto indicano nomi troppo generici o hub con troppi
   link: si aggiunge la parola a `PAROLE_COMUNI` (vale come nome solo con la maiuscola) o si separa l'hub.
   I limiti `MAX_MENZIONA` e `MAX_TIPIZZATE` si toccano solo misurando prima e dopo.
7. **Pagine per entropia.** Una pagina che risponde a una domanda trasversale linka tutte le pagine della
   risposta: nominata una volta, porta l'intera catena.
8. **Far crescere il banco con domande vere.** Le domande arrivate in chat e risposte male entrano nel banco
   (`banco.py --semi` dà il materiale, `banco.py --verifica` controlla che non contengano le parole dei
   titoli). Un banco che copre solo ciò che funziona già non misura nulla. Dopo, nuova baseline.

Le varianti del motore (ripiego a cascata, fusione grafo + testo, PageRank personalizzato, limiti) sono
misurate in [analisi-retrieval-ecc.md](analisi-retrieval-ecc.md).

Da evitare: alias che copiano le domande del banco parola per parola (si misura il banco, non il vault),
alias generici che alzano il rumore, relazioni che il testo non afferma.
