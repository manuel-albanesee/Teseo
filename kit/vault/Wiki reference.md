# Wiki reference — <nome del vault>

Schema e convenzioni di questo vault. **Leggere per primo.**

## Modello a tre livelli (metodo LLM Wiki, Karpathy)

| Livello | Cartella | Regola |
| --- | --- | --- |
| **Raw sources** | `raw/` | Materiale grezzo e **immutabile**: trascrizioni di call, specifiche, appunti. Non modificare mai, non riordinare, non rinominare. |
| **Wiki** | `wiki/` | Pagine markdown generate e possedute interamente dall'LLM. Riscrivibili, fondibili, cancellabili. |
| **Schema** | questo file + [[index]] + [[log]] | Struttura, convenzioni, indice e cronologia delle ingestion. |

## Ambito

<Di cosa parla il vault, in due righe: progetto, dominio, sistemi principali.>

## Convenzioni delle pagine

- **Una pagina = un concetto, entità, processo o episodio.** Stile enciclopedico, non riassunto lineare della fonte.
- Nomi file leggibili come compaiono nei `[[wikilink]]`. Niente parentesi tonde nei nomi.
- Collegare densamente: ogni pagina linka le entità che cita. Un link a una pagina che non esiste ancora è un segnaposto ammesso durante l'ingest, ma `build_graph.py --check` lo segnala finché non c'è la pagina: il lint lo chiude creandola o togliendo il link.
- Ogni affermazione non ovvia porta la fonte tra parentesi quadre, con il timestamp se c'è: `[call-2026-08-28 34:39]`.
- Le trascrizioni automatiche **contengono errori sui nomi tecnici**. Ogni nome trascritto in modo incerto va marcato con `⚠️ da verificare` e confermato su una fonte scritta prima di usarlo.
- Le fonti conversazionali si distillano: contenuto tecnico e decisioni. Chiacchiere e battute non entrano nella wiki.

### Frontmatter

```yaml
---
tipo: concetto | sistema | entita | persona | processo | progetto | episodio | fonte | documento | riferimento
tags: [...]
fonti: [chiave-fonte, ...]
aggiornato: AAAA-MM-GG
aliases: [...]                      # facoltativo, vedi sotto
parte_di: "[[Pagina]]"              # facoltativo: relazioni tipizzate, vedi sotto
usa: ["[[Pagina A]]", "[[Pagina B]]"]
---
```

`tipo`, `tags`, `fonti`, `aggiornato` e `aliases` hanno un ruolo fisso. **Ogni altra proprietà è una relazione tipizzata** e deve stare nella tabella qui sotto. Nel frontmatter i wikilink vanno tra virgolette.

Tassonomia facoltativa: se questo file ha la sezione «Categorie» (tabella `Categoria | Più ampia | Descrizione`), i `tags` di una pagina sono solo categorie di quella tabella, più i marcatori `entropia` e `sintesi`; si sceglie la categoria più specifica, la più ampia si deduce. Se la tabella «Tipi ammessi» ha la colonna «Sottotipo di», un sottotipo vale ovunque la tabella delle relazioni ammette il suo tipo padre.

### Pagine generate per entropia

Raccolgono in un punto una risposta che il vault ha già, ma sparsa su più pagine. Le scrive il modello durante il lint, **tutte e senza conferma**, una per ogni domanda di `.graph/sintesi.py` a cui le pagine sanno rispondere:

- `tipo: riferimento`, `tags` con `entropia`, `riguarda: "[[<pagina di partenza>]]"`;
- titolo come concetto, non come domanda: es. «Prerequisiti del rilascio in produzione». Per le domande su un termine (es. `TabellaConnessioni`), il termine come titolo o in `aliases`;
- in testa al corpo, subito sotto il titolo, l'avviso:

  ```markdown
  > [!info] Informazioni generate da entropia del vault
  > Pagina scritta dal lint il AAAA-MM-GG mettendo insieme le pagine linkate, senza fatti nuovi. Risponde a: «<domanda>».
  ```

- un `[[wikilink]]` a ogni pagina della risposta: è ciò che fa risultare la domanda coperta;
- ogni affermazione con la fonte originale presa dalla pagina da cui viene, e in `fonti` le sole chiavi citate;
- **nessun fatto nuovo**. Se manca un pezzo la pagina non si scrive: la domanda si scarta con `--scarta` e diventa una domanda aperta per l'autore.

L'entropia resta governata: le domande nascono solo dal grafo (catene `usa`/`richiede`/`referente`, termini condivisi, referenti, memoria), una pagina chiude la sua domanda e spesso quelle più piccole, e le pagine `entropia` non generano domande nuove. `python .graph/sintesi.py --verifica` controlla avviso, `riguarda`, copertura e fonti (nessuna fonte che non sia già in una pagina linkata).

## Relazioni tipizzate

I wikilink nel testo dicono solo che due pagine sono collegate. Le relazioni che contano per rispondere si dichiarano **anche** nel frontmatter della pagina di partenza (X), con una proprietà che ha il nome della relazione e come valore uno o più link **tra virgolette**. Solo le relazioni di questa tabella sono ammesse: `build_graph.py` legge le prime tre colonne per controllare i tipi.

| Relazione | Da (tipo) | A (tipo) | Significato | Esempio |
| --- | --- | --- | --- | --- |
| `parte_di` | qualsiasi | sistema, progetto, processo, entita | X è un componente o una fase di Y | Modulo fatture → Gestionale |
| `usa` | processo, sistema, progetto | sistema, entita | X si svolge o funziona tramite lo strumento Y | Rilascio in produzione → Console di rilascio |
| `richiede` | processo, sistema | qualsiasi | X non parte o non si completa senza Y | Console di rilascio → Incident settimanale |
| `precede` | processo, sistema | processo, sistema | Nella catena operativa X viene prima di Y | Censimento profili → Caricamento notturno |
| `causa` | qualsiasi | qualsiasi | X è causa di Y: se la fonte lo afferma, X provoca o produce Y | Backup fallito → Report mensile incompleto |
| `referente` | qualsiasi | persona | Y è la persona a cui ci si rivolge per X | Incident settimanale → Anna Rossi |
| `variante_di` | qualsiasi | stesso tipo | X è un gemello di Y per un caso particolare | Rilascio d'emergenza → Rilascio in produzione |
| `sostituisce` | sistema, progetto | sistema | X rifà o prende il posto di Y, anche se Y è ancora in uso | Portale 2026 → Portale 2019 |
| `riguarda` | episodio, documento, riferimento, progetto | qualsiasi | X ha Y come oggetto | Errore del 3 marzo → Rilascio in produzione |
| `da_non_confondere` | qualsiasi | stesso tipo | X e Y si scambiano facilmente ma sono diversi | Anna Rossi → Anna Rosso |

- `causa` si dichiara solo se la fonte afferma il nesso causale, mai per semplice sequenza o correlazione. Se la fonte dà il grado di certezza o la frase che lo sostiene, si registra in `relazioni_dettaglio` sulla pagina della causa: `relazioni_dettaglio: {"[[Y]]": {confidenza: alta, evidenza: "frase della fonte"}}` (`confidenza`: `alta`, `media`, `bassa`; `evidenza`: testo breve; Y deve essere un effetto dichiarato con `causa`).
- Una relazione si dichiara solo se la pagina la afferma. Se è incerta non si mette: resta il wikilink nel testo, con il suo `⚠️ da verificare`.
- La relazione sta sulla pagina da cui parte la freccia; l'inversa («è referente di») non si scrive, la calcola il grafo.
- **Alias** (`aliases`): altri nomi con cui una pagina compare nelle fonti — sigle sciolte, forme «Cognome Nome», errori di trascrizione già risolti. Mai un alias ambiguo (un nome di battesimo da solo) né uno non ancora verificato.

Gli script in `.graph/` lavorano così:

- `build_graph.py` costruisce da frontmatter, wikilink e `fonti` il grafo `.graph/graph.sqlite`, con il testo delle pagine nella tabella FTS5 `testo` e le grafie alternative dei nomi nella tabella `varianti` (ServiceDesk → «service desk»). `--check` segnala relazioni fuori tabella, tipi non ammessi, link non risolti, fonti non censite e alias duplicati; con un frontmatter YAML non valido si ferma e nomina la pagina.
- `recall.py "domanda"` restituisce i fatti del grafo legati alla domanda. Parte dalle pagine nominate per nome, per alias, per grafia alternativa o per le parole del titolo (almeno due, vicine tra loro, confrontate per radice con `stemmer.py`: «rilasciare» trova «Rilascio») e segue le relazioni tipizzate fino a 3 passi in avanti e 2 a ritroso; 3 o più «fratelli» (es. le pagine `parte_di` di un hub) diventano un fatto solo. Passano tutte le relazioni tipizzate (tetto di sicurezza `MAX_TIPIZZATE`) e al più `MAX_MENZIONA` link generici (`menziona`); in coda, «N link generici omessi». I nomi che sono anche parole comuni (`PAROLE_COMUNI`, es. «Portale») contano come nomi solo con la maiuscola. I blocchi `<pasted_content>` incollati e i rapporti dei sub agent `<agent-message>` non contano: né per i semi, né per memoria, domande aperte, pre-caricamento e routing.
- Ripiego sul testo: solo se né il grafo né la memoria danno semi e il prompt è una domanda sul contenuto (non un comando, una conferma o una domanda sul sistema), `recall.py` cerca nel testo delle pagine (FTS5, per identificatori, parole ridotte a radice e date come «10 settembre» mappate alle fonti `call-…`) fino a 3 pagine, e se non ne trova un secondo giro più largo fino a 2. È un aggancio debole, dichiarato come tale nel contesto: risponde Opus, su quelle pagine non escono domande aperte, ma la memoria impara comunque.
- `recall_hook.py` fa lo stesso a ogni prompt e mette i fatti nel contesto prima della risposta, ricostruendo il grafo se una pagina è più recente. Se non riconosce pagine, avvisa il modello di cercare in `wiki/`. I guasti sono visibili: se la ricostruzione fallisce (es. frontmatter YAML non valido) usa il grafo precedente e lo dichiara a utente e modello; se il recall fallisce, avvisa il modello. In questi casi risponde Opus.
- `modello_hook.py`, registrato come hook `SessionStart` e `UserPromptSubmit` in `.claude/settings.json`, chiama `recall_hook.py` e in una sessione Opus fa rispondere Haiku alle domande puntuali, con le pagine nominate già nel prompt. Lascia a Opus le domande ampie («cosa fa», «come funziona»…) e di elenco («elenca», «quali», «quanti»…), il solo nome di un hub, le modifiche al vault, le domande sul sistema, i guasti e le domande che il grafo non riconosce. All'avvio con Opus ricorda che il prefisso `@opus` salta Haiku.
- `memoria.py`, con `learn_hook.py` (hook `PostToolUse` su Read e `Stop`): le domande sul contenuto che il grafo non riconosce finiscono in `.graph/memoria.sqlite` con le pagine lette per rispondere; a una domanda simile quelle pagine diventano punti di partenza. Non impara da comandi, richieste di modifica, domande sul sistema e conferme. `python .graph/memoria.py` elenca le domande apprese (quelle ricorrenti si promuovono a mano ad `aliases`); `--dimentica "<testo>"` toglie una voce sbagliata; `--turni` mostra gli ultimi prompt con le pagine date dal grafo e quelle poi lette dal modello.
- `domande.py`: in coda ai fatti l'hook aggiunge al più 3 **domande aperte** del vault sulle pagine del prompt, sui loro vicini tipizzati e sulle pagine sorelle: voci dei punti aperti di [[index]], righe con `⚠️ da verificare`, sistemi e processi senza `referente`, domande che il lint ha scartato perché il vault non bastava. Sono le sole domande rivolte all'autore. Ognuna compare una sola volta per sessione (`.graph/domande.sqlite`). Le risposte dell'autore entrano come `[nota-utente]`; `python .graph/domande.py` le elenca tutte, per segnale. Ogni domanda è archiviata con stato e date nella tabella `aperte`, ma il calcolo dalle pagine comanda: una domanda che il calcolo non rileva più passa a `chiusa`, una che riappare si riapre. Se l'autore dice che per ora non può rispondere, la domanda si rinvia di 30 giorni con `python .graph/domande.py --rinvia "<chiave>"`. Dopo 3 rinvii non si rinvia più: la domanda va risolta nella pagina. `python .graph/domande.py --stato` le elenca per stato.
- `sintesi.py` elenca le domande a cui il vault risponde solo mettendo insieme più pagine (catene `usa`/`richiede`/`referente` di almeno due passi, identificatori citati in 3+ pagine di 3+ aree senza pagina propria, persone referenti di più pagine, domande apprese in `memoria.sqlite`) e le considera coperte quando una pagina linka tutte quelle della risposta: è la fonte delle pagine generate per entropia.
- `misura.py` misura il recall sulle domande di prova (`DOMANDE`), poi controlla i semi spuri (casi negativi), il ripiego sul testo, la memoria e i difetti noti (`ATTESI_FALLITI`, che non fanno fallire). `--routing` controlla le scelte di `modello_hook.py`; `--modello` confronta le risposte di un modello con e senza grafo.
- Facoltativi, per misurare e migliorare il grafo: `banco.py` prepara (`--semi`) e controlla (`--verifica`) il banco `.graph/banco.json`, domande scritte senza le parole dei titoli che `misura.py` misura in una sezione informativa; `candidati.py` propone, in sola lettura, alias, termini e relazioni che mancano (`.graph/candidati.md`). Non servono al funzionamento.

## Chiavi delle fonti

Ogni fonte citata in `fonti` deve avere una riga qui, con la chiave tra backtick nella prima colonna: `build_graph.py --check` segnala le chiavi usate ma non censite.

| Chiave | File sorgente | Data e natura |
| --- | --- | --- |
| `call-2026-09-10` | `raw/call-2026-09-10.md` | 10 set 2026, ~1h — esempio: walkthrough del rilascio |
| `manuale-rilascio` | `raw/manuale-rilascio.md` | esempio: manuale operativo |

### Correzioni dirette

| Chiave | Origine |
| --- | --- |
| `nota-utente` | Precisazioni date a voce dall'autore del vault, non presenti in `raw/`. Si citano senza timestamp, es. `[nota-utente]`. Prevalgono sulle fonti quando le correggono. |

## Workflow

1. **Ingest** — nuova fonte in `raw/`, distillazione in pagine atomiche, aggiornamento delle pagine esistenti, `index.md` e `log.md` (skill `obsidian-wiki-ingest`).
2. **Query** — interrogare la wiki, non i raw. Se la risposta non c'è, risalire al raw e poi *scrivere la pagina mancante* (skill `obsidian-wiki-query`).
3. **Lint** — cercare duplicati, pagine orfane, contraddizioni non segnalate, `⚠️ da verificare` risolvibili; scrivere le pagine per entropia. Eseguire `python .graph/domande.py --da-decidere` e riportare all'autore le domande rinviate 3 volte (skill `obsidian-wiki-lint`).
4. **Lacune** — smaltire le domande aperte con l'autore, una alla volta (skill `obsidian-wiki-fill-gaps`): ogni risposta va nelle pagine come `[nota-utente]`, si archivia localmente con `python .graph/domande.py --risposta "<chiave>" --testo "…"` e si verifica in piccolo (`build_graph.py --check`, altre pagine che ripetono lo stesso fatto). Per condividerla, scegliere esplicitamente le righe nella preview della dashboard; la memoria personale resta locale. Il lint su copia isolata dichiara soltanto gli UUID elaborati con `teseo_receipt.py --request <mandato> --outcome succeeded --consolida-id UUID --operazione UUID`; note ed eventi entrano nello stesso checkpoint dopo apply manuale. `--consolida` massivo è disabilitato e non modifica i DB originali. Oltre alle domande salvate, la skill chiede le lacune di struttura: sistemi, processi e progetti senza relazioni tipizzate (`--json --strutturali`).

## Manutenzione del vault

Il vault resta utile finché le pagine dicono il vero, il grafo le rispecchia e le domande aperte calano. Il ciclo è **ingest → lint → lacune**: dopo ogni ingest la skill propone lint e lacune, in quest'ordine, perché il lint chiude da solo ciò che il vault sa già e scopre le domande che solo l'autore può chiudere.

**Cadenza**
- **Dopo ogni ingest**: lint, anche parziale sulle pagine toccate. Senza lint le pagine nuove non generano pagine per entropia e le contraddizioni con il resto del vault non vengono registrate.
- **Ogni settimana**: una sessione di lacune breve, 10-15 domande. Meglio poche e spesso che un centinaio una volta.
- **Ogni due settimane, o dopo molte risposte**: un lint completo, che consolida le risposte archiviate e riporta le domande da decidere.

**Abitudini**
- Una precisazione data in chat va subito nella pagina come `[nota-utente]`: in chat si perde. Se arriva da una domanda aperta, va anche archiviata con `--risposta`.
- Correggere una riga `⚠️ da verificare` lasciando uguali le prime parole: la domanda resta la stessa e si chiude. Cambiando l'inizio della riga la vecchia si chiude e ne nasce una nuova, con il conteggio dei rinvii azzerato.
- Rinviare è lecito, rimandare all'infinito no: dopo 3 rinvii la domanda va decisa.
- Le contraddizioni tra fonti si registrano e si risolvono con l'autore, non si appianano. Le pagine generate per entropia non si correggono a mano: si corregge la pagina da cui vengono e il lint le riscrive.
- Le domande che il grafo non riconosce e che tornano spesso (`python .graph/memoria.py`) si promuovono ad `aliases` della pagina giusta. Una voce appresa sbagliata si toglie con `python .graph/memoria.py --dimentica "<testo>"`.
- Dopo modifiche a `.graph/` o a molti alias, `python .graph/misura.py` non deve peggiorare.
- `graph.sqlite` si rigenera dalle pagine; `memoria.sqlite` e `domande.sqlite` no: sono storia (domande apprese, rinvii, risposte) e vanno salvate insieme al vault.

**Segnali di salute**

| Indicatore | Comando | Valore sano |
| --- | --- | --- |
| Problemi del grafo | `python .graph/build_graph.py --check` | nessuno |
| Domande aperte | `python .graph/domande.py --stato` | in calo da un lint all'altro |
| Domande da decidere | `python .graph/domande.py --da-decidere` | 0 |
| Risposte da consolidare | `python .graph/domande.py --risposte` | 0 dopo ogni lint |
| Pagine per entropia valide | `python .graph/sintesi.py --verifica` | exit 0 |
| Recall | `python .graph/misura.py` | tutte le pagine attese, semi spuri 0, tutte le sezioni OK, exit 0 |
| Routing | `python .graph/misura.py --routing` | tutti OK, exit 0 |
| Memoria appresa | `python .graph/memoria.py` | solo domande, nessun comando |
| Recall sul banco (KPI, facoltativo) | `python .graph/misura.py --solo-banco --banco-confronta .graph/banco_base.json` | pagine attese portate e domande complete non in calo, rumore non in crescita, ogni domanda PEGGIORATA con un motivo; il massimo è la somma delle `attese` e cambia con il banco: nuova baseline quando il banco cambia |

## Regole non negoziabili

- Non modificare mai nulla dentro `raw/`.
- Non inventare nomi di tabelle, colonne, path o codici: se la fonte è incerta, dirlo.
- Le contraddizioni tra fonti non si appianano: si registrano esplicitamente nella pagina interessata e nei punti aperti di [[index]].
