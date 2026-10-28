# Analisi ECC: migliorare il retrieval dal grafo durante le query

Data: 2026-10-27. Vault di prova: ISP (213 pagine, banco di 106 domande, 134 pagine attese).
Riferimenti: [KPI del recall](kpi-recall.md), [architettura del motore](architettura-motore.md) §4.

## Metodo

Skill ECC (Everything Claude Code) applicate:

| Skill | Uso |
|-------|-----|
| `benchmark-optimization-loop` | baseline, gate di correttezza, una variante = una ipotesi, tabella delle varianti, gate di promozione |
| `eval-harness` | eval di capacità (banco) e di regressione (`misura.py`); holdout per l'overfitting |
| `iterative-retrieval` | ciclo dispatch → evaluate → refine con stop deterministico: varianti `T_rilassato`, `H_residui` |
| `search-first` | confronto con soluzioni note (ibrido BM25 + grafo, PageRank personalizzato tipo HippoRAG, query expansion) prima di costruire |

Le varianti girano dentro il processo, con `recall.py` invariato e `graph.sqlite` aperto in sola lettura. Per
ogni variante si cambia una costante, o si avvolge una sola funzione, e si misura:

- **banco**: pagine attese portate, domande complete, rumore medio (pagine portate ma non attese), token
  medi, ms. Per l'holdout il banco è diviso in metà pari e metà dispari: una variante deve migliorare entrambe;
- **confronto per domanda** con B0: migliorate e peggiorate, secondo la regola di `misura.py --banco-confronta`;
- **gate**, tutti obbligatori: le 41 domande di prova restano 41/41, 0 semi vietati sui `NEGATIVI`, anche dal
  ripiego, e 0 errori sui casi `TESTO` (pagine attese presenti, nessuna pagina sui prompt generici).

Gate di promozione: gate tutti verdi, **0 domande peggiorate**, miglioramento in entrambe le metà.

## Diagnosi di partenza

Su 106 domande, 77 non hanno semi dal grafo e 51 di queste sono coperte dal ripiego sul testo. Delle 34
domande che perdono pagine, 29 non hanno semi. Il collo di bottiglia è il **vocabolario**: la domanda non
nomina la pagina. Il cammino sul grafo e la potatura contano meno.

## Risultati

| Variante | Ipotesi | Pagine | Pari / dispari | Complete | Rumore | Token | Migl. / pegg. | Gate |
|----------|---------|-------:|---------------:|---------:|-------:|------:|--------------:|------|
| B0 | baseline | 88/134 (66%) | 42/64 · 46/70 | 72 | 13,7 | 582 | – | ok |
| T_n5 | ripiego fino a 5 pagine | 88 | 42 · 46 | 72 | 14,5 | 606 | 0 / 10 | ok |
| T_fin60 | `FINESTRA_TESTO` 60 sempre | 96 | 47 · 49 | 78 | 14,3 | 614 | 9 / 4 | ok |
| T_freq30 | `SOGLIA_FREQUENTE` 0,30 sempre | 92 | 41 · 51 | 75 | 13,9 | 604 | 11 / 8 | ok |
| T_score3 | `MIN_SCORE_TESTO` 3 | 95 | 47 · 48 | 77 | 14,7 | 625 | 7 / 3 | **KO** testo |
| **R45/0.25** | **2° giro rilassato (45 parole, 0,25), al più 2 pagine, solo se il 1° dà 0** | **102 (76%)** | **48 · 54** | **82** | 15,2 | 647 | **10 / 0** | **ok** |
| R45/0.30 | come sopra, 0,30 | 104 | 49 · 55 | 84 | 15,3 | 655 | 12 / 0 | **KO** testo |
| R60/0.30 | come sopra, 60 / 0,30 | 107 | 49 · 58 | 85 | 15,7 | 676 | 13 / 0 | **KO** testo |
| H_le1 | ripiego anche con 1 seme | 90 | 43 · 47 | 74 | 14,8 | 641 | 3 / 11 | ok |
| H_sempre | fusione grafo + testo sempre | 90 | 43 · 47 | 74 | 15,4 | 667 | 4 / 16 | **KO** neg |
| H_residui | 2° giro sulle parole che i semi non coprono | 91 | 43 · 48 | 75 | 14,5 | 624 | 5 / 10 | ok |
| R_men6 | `MAX_MENZIONA` 6 | 81 | 40 · 41 | 68 | 11,4 | 468 | 70 / 6 | ok |
| R_men4 | `MAX_MENZIONA` 4 | 77 | 39 · 38 | 67 | 10,1 | 406 | 73 / 7 | ok |
| P_ppr10 | 10 posti `menziona` scelti per PageRank personalizzato | 83 | 42 · 41 | 67 | 13,0 | 576 | 30 / 15 | ok |
| P_ppr6 | come sopra, 6 posti | 76 | 39 · 37 | 63 | 10,8 | 456 | 64 / 13 | ok |

Nella colonna «migl. / pegg.» delle varianti di rumore, «migliorata» comprende le domande con le stesse pagine
attese e meno rumore. Per questo `R_men*` e `P_ppr*` hanno molte migliorate pur perdendo pagine.

Il caso che blocca le versioni più larghe del 2° giro è «come gestisco un errore di timeout sul server?»: con
`SOGLIA_FREQUENTE` 0,30 «errore» e «server» tornano utili e il giro porta «Database annuali Portafoglio SEPA».
Gli `ATTESI_FALLITI` restano uguali alla baseline in R45/0.25.

## Lettura

1. **Il ripiego a cascata è l'unica variante promuovibile.** È un ciclo `iterative-retrieval` con lo stop
   fissato nel codice: al più 2 giri, il 2° solo se il 1° non trova nulla, al più 2 pagine. Recupera domande
   parafrasate come «manifesto di collaudo», «codice della settimana», «sistemino che cerca gli errori»,
   «Samira e Rossano». Il rumore sale solo su quelle domande, che prima non portavano niente. Anche le soglie
   restano deterministiche.
2. **La fusione grafo + testo non conviene** (`H_*`). Con semi veri il testo aggiunge pagine fuori tema e
   peggiora più domande di quante ne migliori. La fusione dei rank alla RRF, standard nei RAG ibridi, qui non
   rende: il grafo con semi è già preciso, manca solo quando non ci sono semi.
3. **Il PageRank personalizzato (stile HippoRAG) non batte il punteggio attuale.** A parità di posti perde 5
   pagine: il punteggio di `richiama` (passo, reciprocità, parole della domanda, grado) è più adatto a un grafo
   piccolo e tipizzato.
4. **Tagliare `MAX_MENZIONA` riduce rumore e token** (−30% di token con 4), ma perde 7-11 pagine. Non si
   promuove per il recall. Si può valutare solo come modalità «risparmio» separata.
5. **Il ripiego più largo (`T_n5`) non aiuta**: le pagine giuste mancano perché non passano le soglie, non
   perché finiscono i posti.

## Raccomandazioni, per resa e rischio

| # | Intervento | Resa attesa | Rischio | Deterministico |
|---|------------|-------------|---------|----------------|
| 1 | **Ripiego a cascata** in `recall_hook.ripiego_testo` (e quindi in `misura.esito_banco`): 2° giro con `FINESTRA_TESTO_LARGA = 45`, `SOGLIA_FREQUENTE_LARGA = 0,25`, `MAX_TESTO_LARGO = 2`, solo con 0 pagine dal 1° | +14 pagine (66% → 76%), 10 domande migliorate, 0 peggiorate | basso: gate verdi; aggiungere a `TESTO` un caso negativo come «errore di timeout sul server» per bloccare allargamenti futuri | sì |
| 2 | Alias dal testo dei link, filtrati (esperimento alias, braccio D') | +3 pagine, 0 peggiorate | basso | sì (`candidati.py`) |
| 3 | Domande reali in memoria come banco di holdout vero (oggi 6) | misura più affidabile, nessun guadagno diretto | nessuno | sì |
| 4 | Modalità «risparmio» con `MAX_MENZIONA` 6 per i client con contesto stretto | −20% token, −7 pagine | medio | sì |
| 5 | Gergo assente dal vault («rilascio in prod», «analisi statica») chiesto all'autore con fill-gaps | 2-3 pagine | nessuno | no: serve l'autore |

Da non fare: fusione grafo + testo sempre attiva, PageRank personalizzato al posto del punteggio, soglie del
1° giro allargate per tutti (`T_freq30`, `T_score3`).

## Avvertenze

- **Stato: la raccomandazione 1 è implementata nel kit** (`kit/graph/recall.py`: `per_testo_a_cascata` e
  le costanti `FINESTRA_TESTO_LARGA`, `SOGLIA_FREQUENTE_LARGA`, `MAX_TESTO_LARGO`; `kit/graph/recall_hook.py`:
  `ripiego_testo`; test in `tests/test_recall_testo.py`). È verificata sui dati del vault ISP in sola lettura:
  88 → 102/134, 10 domande migliorate, 0 peggiorate. I vault installati la ricevono con l'aggiornamento del kit.
- Le soglie del 2° giro sono scelte sullo stesso banco. Il controllo pari/dispari riduce il rischio di
  overfitting senza eliminarlo: va ripetuto sulle domande reali quando la memoria ne avrà abbastanza.
- Dopo l'adozione serve una nuova baseline (`misura.py --banco-salva .graph/banco_base_<data>.json`) e va
  aggiornata la riga KPI in `Wiki reference.md`.
- Il kit (`kit/graph/recall.py`, `kit/graph/recall_hook.py`) e il vault devono ricevere la stessa modifica.
