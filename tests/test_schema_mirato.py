"""Fase 1 di doc/17: lo schema a fette (schema.py) e il suo peso nei contratti (contratti.py --peso)."""
import _shortpath  # noqa: F401
from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest

KIT = Path(__file__).resolve().parents[1] / 'kit'
sys.path.insert(0, str(KIT / 'graph'))
import contratti  # noqa: E402
import schema  # noqa: E402

SCHEMA = """# Schema

## Convenzioni delle pagine

Una pagina, un concetto.

### Pagine generate per entropia

Le scrive il lint senza fatti nuovi.

## Tipi ammessi

| Tipo | Descrizione | Sottotipo di |
| --- | --- | --- |
| `sistema` | Strumenti | |
| `servizio` | Servizi web | sistema |
| `portale` | Portali | servizio |
| `persona` | Persone | |
| `processo` | Attività | |
| `fonte` | Fonti | |

## Relazioni tipizzate

| Relazione | Da (tipo) | A (tipo) | Significato | Esempio |
| --- | --- | --- | --- | --- |
| `usa` | processo | sistema | X funziona tramite Y | Rilascio → Console |
| `parte_di` | qualsiasi | sistema | X è parte di Y | Modulo → Gestionale |
| `referente` | qualsiasi | persona | Y è la persona di X | Incident → Anna |
| `gestisce` | persona | processo | X gestisce Y | Anna → Incident |
| `variante_di` | qualsiasi | stesso tipo | X è gemello di Y | B → A |

Gli script lavorano così: testo lungo che non fa parte dello schema delle relazioni.

## Chiavi delle fonti

Ogni fonte citata in `fonti` ha una riga qui.

| Chiave | File sorgente | Data |
| --- | --- | --- |
| `call-a` | `raw/a.md` | prima |
| `call-b` | `raw/b.md` | seconda |

## Manutenzione del vault

Lint ogni settimana.

## Regole non negoziabili

- Non modificare mai nulla dentro `raw/`.
"""


def righe_tabella(testo, prima_colonna):
    return [r for r in testo.splitlines() if r.startswith(f'| `{prima_colonna}`')]


class Livello1(unittest.TestCase):
    def test_regole_convenzioni_e_indice_dei_nomi(self):
        esito = schema.fette(SCHEMA, livello=1)
        testo = esito['testo']
        self.assertIn('Non modificare mai nulla dentro `raw/`', testo)
        self.assertIn('Una pagina, un concetto.', testo)
        self.assertIn('Tipi: sistema, servizio, portale, persona, processo, fonte', testo)
        self.assertIn('Relazioni: usa, parte_di, referente, gestisce, variante_di', testo)
        self.assertEqual(esito['avvisi'], [])

    def test_senza_descrizioni_ne_tabelle_complete(self):
        testo = schema.fette(SCHEMA, livello=1)['testo']
        for assente in ('Servizi web', 'X funziona tramite Y', 'Pagine generate per entropia',
                        'Gli script lavorano così', 'Manutenzione del vault', '`raw/a.md`'):
            self.assertNotIn(assente, testo)
        self.assertIn('Ogni fonte citata in `fonti` ha una riga qui.', testo)  # il formato delle chiavi, non le chiavi

    def test_sezioni_e_entropia_su_richiesta(self):
        testo = schema.fette(SCHEMA, livello=1, entropia=True, sezioni=('Manutenzione del vault',))['testo']
        self.assertIn('Le scrive il lint senza fatti nuovi.', testo)
        self.assertIn('Lint ogni settimana.', testo)

    def test_sezione_inesistente_e_un_avviso(self):
        esito = schema.fette(SCHEMA, livello=1, sezioni=('Non esiste',))
        self.assertIn('sezione «Non esiste» assente', esito['avvisi'][0])

    def test_senza_catalogo_dei_tipi_l_indice_ha_solo_le_relazioni(self):
        esito = schema.fette(SCHEMA.replace('## Tipi ammessi', '## Altro'), livello=1)
        self.assertNotIn('Tipi:', esito['testo'])
        self.assertIn('Relazioni:', esito['testo'])

    def test_deterministico(self):
        self.assertEqual(schema.fette(SCHEMA, livello=1), schema.fette(SCHEMA, livello=1))

    def test_il_livello_1_del_kit_pesa_meno_di_tutto_lo_schema(self):
        completo = (KIT / 'vault/Wiki reference.md').read_text(encoding='utf-8')
        esito = schema.fette(completo, livello=1)
        self.assertLess(esito['token'], schema.TETTO_LIVELLO_1)
        self.assertLess(esito['token'], schema.stima_token(completo) // 2)
        self.assertIn('Regole non negoziabili', esito['testo'])
        self.assertEqual(esito['avvisi'], [])

    def test_tetto_superato_e_un_avviso_non_un_errore(self):
        esito = schema.fette(SCHEMA, livello=1, tetto=10)
        self.assertTrue(any('oltre il tetto di 10 token' in a for a in esito['avvisi']))
        self.assertIn('Non modificare', esito['testo'])


class Livello2(unittest.TestCase):
    def test_tipo_con_antenati_e_relazioni_applicabili(self):
        testo = schema.fette(SCHEMA, livello=2, tipi=('portale',))['testo']
        for tipo in ('portale', 'servizio', 'sistema'):
            self.assertEqual(len(righe_tabella(testo, tipo)), 1, tipo)
        self.assertIn('Servizi web', testo)
        self.assertNotIn('Persone', testo)
        for relazione in ('usa', 'parte_di', 'referente', 'variante_di'):
            self.assertTrue(righe_tabella(testo, relazione), relazione)
        self.assertFalse(righe_tabella(testo, 'gestisce'))  # parte da persona: non si applica a un portale

    def test_un_tipo_radice_non_porta_i_sottotipi(self):
        testo = schema.fette(SCHEMA, livello=2, tipi=('persona',))['testo']
        self.assertIn('Persone', testo)
        self.assertNotIn('Servizi web', testo)
        self.assertTrue(righe_tabella(testo, 'gestisce'))
        self.assertFalse(righe_tabella(testo, 'usa'))

    def test_fonti_citate(self):
        testo = schema.fette(SCHEMA, livello=2, fonti=('call-b',))['testo']
        self.assertTrue(righe_tabella(testo, 'call-b'))
        self.assertFalse(righe_tabella(testo, 'call-a'))

    def test_tipo_sconosciuto_e_un_avviso(self):
        esito = schema.fette(SCHEMA, livello=2, tipi=('inesistente',))
        self.assertIn('tipo «inesistente» non dichiarato', esito['avvisi'][0])

    def test_senza_catalogo_tutte_le_relazioni_e_un_avviso(self):
        senza = SCHEMA[:SCHEMA.index('## Tipi ammessi')] + SCHEMA[SCHEMA.index('## Relazioni tipizzate'):]
        esito = schema.fette(senza, livello=2, tipi=('portale',))
        self.assertTrue(any('catalogo dei tipi assente' in a for a in esito['avvisi']))
        self.assertTrue(righe_tabella(esito['testo'], 'gestisce'))

    def test_schema_con_errori_consiglia_di_leggere_tutto(self):
        rotto = SCHEMA.replace('| `servizio` | Servizi web | sistema |', '| `servizio` | Servizi web | nessuno |')
        esito = schema.fette(rotto, livello=2, tipi=('portale',))
        self.assertTrue(any('leggere Wiki reference.md per intero' in a for a in esito['avvisi']))


SEMANTICA = """
## Semantica delle relazioni

| Relazione | Ruolo | Inversa | Proprietà |
| --- | --- | --- | --- |
| `usa` | dipendenza | è usato da | |
| `gestisce` | responsabile | è gestito da | transitiva |

## Vincoli

| Tipo | Relazione o attributo | Minimo | Massimo | Se manca |
| --- | --- | --- | --- | --- |
| `sistema` | `referente` | 1 | | domanda |
| `persona` | `gestisce` | 0 | 3 | domanda |
"""


class Livello2ConSemantica(unittest.TestCase):
    """Dalla fase 2 di doc/17 le righe di ruoli, inverse e vincoli dei tipi toccati viaggiano con quelle dei tipi."""

    def test_semantica_e_vincoli_dei_tipi_toccati(self):
        testo = schema.fette(SCHEMA + SEMANTICA, livello=2, tipi=('portale',))['testo']
        self.assertTrue(righe_tabella(testo, 'usa'))
        self.assertIn('| `usa` | dipendenza | è usato da |', testo)
        self.assertNotIn('è gestito da', testo)  # gestisce parte da persona: non si applica a un portale
        self.assertIn('| `sistema` | `referente` | 1 |', testo)  # il vincolo del padre vale per il sottotipo
        self.assertNotIn('`persona` | `gestisce`', testo)

    def test_un_altro_tipo_porta_le_sue_righe(self):
        testo = schema.fette(SCHEMA + SEMANTICA, livello=2, tipi=('persona',))['testo']
        self.assertIn('| `gestisce` | responsabile | è gestito da | transitiva |', testo)
        self.assertIn('| `persona` | `gestisce` | 0 | 3 | domanda |', testo)
        self.assertNotIn('è usato da', testo)

    def test_senza_le_sezioni_nulla_in_piu(self):
        testo = schema.fette(SCHEMA, livello=2, tipi=('portale',))['testo']
        self.assertNotIn('## Semantica', testo)
        self.assertNotIn('## Vincoli', testo)

    def test_il_livello_1_non_le_porta(self):
        testo = schema.fette(SCHEMA + SEMANTICA, livello=1)['testo']
        self.assertNotIn('è usato da', testo)
        self.assertNotIn('Vincoli', testo)


class DaiDatiDelGrafo(unittest.TestCase):
    def test_tipi_delle_pagine(self):
        db = sqlite3.connect(':memory:')
        self.addCleanup(db.close)
        db.executescript("CREATE TABLE entities (id TEXT, tipo TEXT, path TEXT);"
                         "INSERT INTO entities VALUES ('Alfa', 'portale', 'wiki/Alfa.md'), ('Beta', 'persona', 'wiki/Beta.md'),"
                         "('Gamma', 'portale', 'wiki/Gamma.md'), ('call-a', 'fonte', NULL);")
        tipi, ignote = schema.tipi_delle_pagine(db, ['Alfa', 'Beta', 'Gamma', 'Nuova'])
        self.assertEqual(tipi, ('persona', 'portale'))
        self.assertEqual(ignote, ['Nuova'])


class Comando(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.vault = Path(temp.name)
        (self.vault / 'Wiki reference.md').write_text(SCHEMA, encoding='utf-8')

    def esegui(self, *argv):
        uscita = io.StringIO()
        with redirect_stdout(uscita):
            codice = schema.main(['--vault', str(self.vault), *argv])
        return codice, uscita.getvalue()

    def test_livello_1(self):
        codice, testo = self.esegui('--livello', '1')
        self.assertEqual(codice, 0)
        self.assertIn('Tipi: sistema', testo)

    def test_per_tipi_e_fonti_e_json(self):
        codice, testo = self.esegui('--per-tipi', 'portale', '--fonti', 'call-a', '--json')
        dati = json.loads(testo)
        self.assertEqual(codice, 0)
        self.assertIn('Servizi web', dati['testo'])
        self.assertTrue(righe_tabella(dati['testo'], 'call-a'))
        self.assertEqual(sorted(dati), ['avvisi', 'testo', 'token'])

    def test_schema_assente(self):
        (self.vault / 'Wiki reference.md').unlink()
        codice, _ = self.esegui('--livello', '1')
        self.assertEqual(codice, 2)

    def test_serve_un_livello_o_dei_tipi(self):
        with self.assertRaises(SystemExit):
            self.esegui()


CONTRATTO = """\
## Input

| Livello | File | Sezione | Perché |
| --- | --- | --- | --- |
| 3 | `python .graph/schema.py --livello 1` | tutto | regole e indice dei nomi |
| 3 | `python .graph/schema.py --per-pagine {pagine}` | tutto | righe dei tipi toccati |
| 3 | `python .graph/domande.py --stato` | tutto | non è lo schema |
| 4 | `index.md` | tutto | mappa |

## Processo

1. Fai.

## Verifica

- Controlla.

## Output

- Niente.
"""


class PesoNeiContratti(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.vault = Path(temp.name)
        (self.vault / 'Wiki reference.md').write_text(SCHEMA, encoding='utf-8')
        (self.vault / 'index.md').write_text('mappa', encoding='utf-8')
        self.contratto = self.vault / 'SKILL.md'
        self.contratto.write_text(CONTRATTO, encoding='utf-8')

    def test_il_comando_dello_schema_si_conta_in_processo(self):
        peso = contratti.peso(self.contratto, self.vault)
        righe = {r['file']: r for r in peso['righe']}
        livello1 = righe['python .graph/schema.py --livello 1']
        self.assertEqual(livello1['token'], schema.fette(SCHEMA, livello=1)['token'])
        mirata = righe['python .graph/schema.py --per-pagine {pagine}']
        self.assertEqual(mirata['token'], schema.TETTO_LIVELLO_2)
        self.assertTrue(mirata['stima'])
        self.assertNotIn('python .graph/domande.py --stato', righe)  # altri comandi ignorati come prima
        self.assertEqual(peso['livello3'], livello1['token'] + schema.TETTO_LIVELLO_2)

    def test_il_contratto_resta_valido(self):
        esito = contratti.valida(self.contratto, self.vault)
        self.assertEqual(esito['errori'], [])

    def test_stampa_con_peso(self):
        uscita = io.StringIO()
        with redirect_stdout(uscita):
            contratti.main([str(self.contratto), '--radice', str(self.vault), '--peso'])
        self.assertIn('schema.py --livello 1', uscita.getvalue())
        self.assertIn('(stima)', uscita.getvalue())

    def test_schema_assente_non_e_trovato(self):
        (self.vault / 'Wiki reference.md').unlink()
        righe = {r['file']: r for r in contratti.peso(self.contratto, self.vault)['righe']}
        self.assertIsNone(righe['python .graph/schema.py --livello 1']['token'])


if __name__ == '__main__':
    unittest.main()
