# La coerenza delle risposte come KPI del vault

Il recall dice se il grafo porta nel contesto le pagine giuste ([KPI del recall](kpi-recall.md)). Non dice se le
risposte del modello usano **gli stessi nomi** e restano **le stesse** quando si ripete la domanda o la si formula con
altre parole. È ciò che un vocabolario condiviso, sinonimi e corrispondenze dovrebbero migliorare
([doc/17](17-concetti-grafo-aziendale.md)): senza misurarlo non si può decidere se tenerli.

Riferimenti: `kit/graph/coerenza.py`, `kit/graph/misura.py`, `kit/graph/banco.py`, `kit/graph/contratti.py` (le
docstring sono la specifica).

## Le quattro misure

| Misura | Cosa conta | Come si ottiene | Modello | Verso buono |
| --- | --- | --- | --- | --- |
| **K1 coerenza dei nomi** | Menzioni di pagine fatte con il nome della pagina, su tutte le menzioni (nome, alias o variante grafica) | `coerenza.py --risposte DIR` | sì | ↑ |
| **K2 stabilità fra giri** | Quanto coincidono le pagine nominate nei giri della stessa domanda (media della somiglianza di Jaccard a coppie); quota di domande con lo stesso esito in tutti i giri | `coerenza.py --risposte DIR` | sì | ↑ |
| **K3 stabilità fra parafrasi** | Quanto coincidono le pagine portate dal recall per una domanda del banco e per le sue `parafrasi`; quota di parafrasi con gli stessi semi | `misura.py --solo-banco` | no | ↑ |
| **K4 peso dello schema** | Token di livello 3 che le skill fanno caricare; token medio del contesto del recall | `contratti.py --peso`, `misura.py --solo-banco` | no | stabile o ↓ |

Dettagli che cambiano i numeri:

- **Menzione.** Un nome di pagina, un alias (`aliases`) o una variante (`varianti`, es. «service desk» per
  ServiceDesk) trovato nella risposta come sequenza di parole intere, senza maiuscole e accenti; vince la forma più
  lunga, senza sovrapposizioni. Una forma che appartiene a più pagine non conta. Un nome che è anche parola comune
  (`PAROLE_COMUNI` di `recall.py`) conta solo se scritto con la maiuscola, come nel recall.
- **Canonica.** La forma trovata è il nome della pagina. Dalla fase 3a di doc/17 valgono anche i nomi di tipo e
  categoria.
- **Jaccard di due insiemi vuoti = 1.** Due risposte che non nominano pagine sono d'accordo.
- **Esito.** Per K2 l'esito di un giro è il campo `corretta` delle risposte di `misura.py --modello` (regex sulla
  risposta, un'approssimazione) o, per le risposte di `--hook`, tutte le regex trovate.

## Come e quando misurare

K3 e K4 sono deterministici: si misurano come il recall, a ogni modifica, anche in CI.

```bash
python .graph/misura.py --solo-banco --banco-salva .graph/banco_base_AAAA-MM-GG.json      # baseline, con K3
python .graph/misura.py --solo-banco --banco-confronta .graph/banco_base_AAAA-MM-GG.json  # confronto
python .graph/contratti.py <skill>/SKILL.md --radice . --peso                               # K4
```

K1 e K2 chiamano un modello (`claude -p`), costano e variano da un giro all'altro: si misurano all'inizio e alla fine
di una fase di doc/17, sempre con lo stesso modello e almeno 3 giri, mai in CI.

```bash
python .graph/misura.py --modello claude-haiku-4-5-20251001 --out <cartella> --giri 3
python .graph/coerenza.py --risposte <cartella>
```

`coerenza.py` stampa una riga per condizione (`ricerca`, `grafo`, `hook`), per esempio:

```
grafo: nomi canonici 41/50 (82%) · stabilità fra giri 0.74 · esito stabile 4/5 · 15 risposte
```

Il banco accetta per ogni voce un campo facoltativo `parafrasi`: altre domande con la stessa risposta, scritte anche
loro senza le parole dei titoli (`banco.py --verifica` lo controlla). Le parafrasi non entrano nei numeri del recall:
`misura.py` aggiunge solo la riga `parafrasi: …` e, nel confronto, la variazione della stabilità.

## Regola

In una fase di doc/17 K1, K2 e K3 non calano e K4 non sale, salvo la fase che lo dichiara come prezzo (per esempio il
blocco «Schema pertinente» nel recall). Una variazione di K1 o K2 sotto 0,05 su 3 giri è rumore: si rimisura prima
di decidere. Come per il recall, si confrontano solo misure fatte sullo stesso banco e con lo stesso modello; quando
cambiano, nuova baseline datata.

## Limiti

- K1 conta i nomi, non giudica se la risposta è vera: resta da rileggere (le risposte stanno nella cartella `--out`).
- Un nome citato fra virgolette o in un elenco di «vedi anche» conta come menzione.
- K3 misura il recall, non il modello: due parafrasi possono portare le stesse pagine e ricevere risposte diverse
  (lo dice K2).
