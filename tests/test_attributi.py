"""Fase 4 di doc/17: attributi di pagina (sezione «Attributi», chiave `attributi`), nei fatti del recall e nei vincoli."""
import _shortpath  # noqa: F401
from contextlib import redirect_stdout
import datetime
import io
from pathlib import Path
import shutil
import sqlite3
import sys
import tempfile
import unittest
from unittest import mock

import test_dashboard_queries as fixture
from kit.dashboard import graph_edit, ontology_preview
from kit.dashboard.contracts import ContractError
from kit.dashboard.graph_service import rebuild
from kit.graph import build_graph, correzioni, ontology
from kit.graph.ontology import AttributeDef, TypeDef, parse, serialize

KIT = Path(__file__).resolve().parents[1] / 'kit'
sys.path.insert(0, str(KIT / 'graph'))
import domande  # noqa: E402
import recall  # noqa: E402
from graph_db import connect_graph  # noqa: E402

TIPI = ('## Tipi ammessi\n| Tipo | Descrizione | Sottotipo di |\n| --- | --- | --- |\n'
        '| `sistema` | Strumenti | |\n| `servizio` | Servizi web | sistema |\n| `processo` | Attività | |\n'
        '| `fonte` | Fonti | |\n')
RELAZIONI = ('## Relazioni tipizzate\n| Relazione | Da (tipo) | A (tipo) | Significato | Esempio |\n'
             '| --- | --- | --- | --- | --- |\n| `usa` | processo | sistema | X funziona tramite Y | A → B |\n')
CATEGORIE = ('## Categorie\n| Categoria | Più ampia | Descrizione |\n| --- | --- | --- |\n'
             '| rischio | | Livello di rischio |\n| alto | rischio | Rischio alto |\n| generale | | Tutto |\n')
ATTRIBUTI = ('## Attributi\n| Attributo | Di (tipo) | Valore | Descrizione |\n| --- | --- | --- | --- |\n'
             '| `data_liquidazione_prevista` | processo | data | Quando si liquida |\n'
             '| `importo_previsto` | processo | importo | Importo atteso |\n'
             '| `codice_progetto` | sistema | codice | Codice interno |\n'
             '| `livello` | sistema | categoria:rischio | Rischio |\n'
             '| `critico` | servizio | sì/no | Da presidiare |\n'
             '| `utenti` | sistema | numero | Utenti attivi |\n'
             '| `nota` | sistema | testo | Appunto libero |\n')
FONTI = '## Chiavi delle fonti\n| `nota-utente` | Precisazione |\n'
BASE = '# Schema\n' + TIPI + RELAZIONI + CATEGORIE + FONTI
SCHEMA = '# Schema\n' + TIPI + RELAZIONI + CATEGORIE + ATTRIBUTI + FONTI
VINCOLO = ('## Vincoli\n| Tipo | Relazione o attributo | Minimo | Massimo | Se manca |\n| --- | --- | --- | --- | --- |\n'
           '| `processo` | `data_liquidazione_prevista` | 1 | | domanda |\n')


def pagina(tipo, attributi=None, **righe):
    """Frontmatter di una pagina; `attributi` è il testo YAML della mappa (già indentato dal chiamante)."""
    testo = ''.join('%s: %s\n' % (k, v) for k, v in righe.items())
    if attributi is not None:
        testo += 'attributi:\n' + ''.join('  %s: %s\n' % (k, v) for k, v in attributi.items())
    return '---\ntipo: %s\n%s---\ntesto\n' % (tipo, testo)


def documenti(schema, **pagine):
    return {'Wiki reference.md': schema, **{'wiki/%s.md' % nome: testo for nome, testo in pagine.items()}}


def codici(schema):
    return {i.code for i in parse(schema).issues if i.severity == 'error'}


def problemi(schema, **pagine):
    return {d['code'] for d in build_graph.parse_documents(documenti(schema, **pagine))['problem_details']}


def crea_vault(test, schema, **pagine):
    temp = tempfile.TemporaryDirectory()
    test.addCleanup(temp.cleanup)
    vault = Path(temp.name)
    (vault / 'wiki').mkdir()
    (vault / '.graph').mkdir()
    (vault / 'Wiki reference.md').write_text(schema, encoding='utf-8')
    for nome in ('index.md', 'log.md'):
        (vault / nome).write_text('# ' + nome + '\n', encoding='utf-8')
    for nome, testo in pagine.items():
        (vault / 'wiki' / (nome + '.md')).write_text(testo, encoding='utf-8')
    with redirect_stdout(io.StringIO()):
        build_graph.costruisci(vault, vault / '.graph/graph.sqlite')
    db = connect_graph(vault / '.graph/graph.sqlite')
    test.addCleanup(db.close)
    return vault, db


class Parser(unittest.TestCase):
    def test_sezione(self):
        document = parse(SCHEMA)
        self.assertEqual([i for i in document.issues if i.severity == 'error'], [])
        self.assertEqual(document.attributes[0], AttributeDef('data_liquidazione_prevista', 'processo', 'data', 'Quando si liquida'))
        self.assertEqual(document.attributes[3].value_type, 'categoria:rischio')
        self.assertEqual(len(document.attributes), 7)
        self.assertTrue(document.editable)
        self.assertEqual(set(document.source_spans), {'types', 'relations', 'categories', 'attributes'})

    def test_senza_sezione_resta_none(self):
        self.assertIsNone(parse(BASE).attributes)

    def test_roundtrip_e_sezione_conservata_byte_per_byte(self):
        document = parse(SCHEMA)
        self.assertEqual(serialize(document), SCHEMA.encode())
        candidate = serialize(document, types=document.types + (TypeDef('entita', 'Altro'),))
        self.assertIn(ATTRIBUTI.encode(), candidate)
        self.assertNotIn(b'data_liquidazione_prevista', document.opaque_bytes())

    def test_errori(self):
        casi = {
            'invalid_attribute': SCHEMA.replace('| `utenti` |', '| `1utenti` |'),
            'duplicate_attribute': SCHEMA.replace('| `nota` | sistema', '| `utenti` | sistema'),
            'unknown_type': SCHEMA.replace('| processo | data |', '| inventato | data |'),
            'unknown_name': SCHEMA.replace('categoria:rischio', 'categoria:inventata'),
            'invalid_value_type': SCHEMA.replace('| numero |', '| colore |'),
            'reserved_attribute': SCHEMA.replace('| `nota` |', '| `tipo` |'),
            'unrecognized_table': SCHEMA.replace('| Attributo | Di (tipo) |', '| Proprietà | Di (tipo) |'),
        }
        for codice, schema in casi.items():
            with self.subTest(codice):
                self.assertIn(codice, codici(schema))

    def test_un_attributo_non_puo_chiamarsi_come_una_relazione(self):
        self.assertIn('reserved_attribute', codici(SCHEMA.replace('| `nota` |', '| `usa` |')))

    def test_lo_stesso_attributo_su_tipi_diversi_e_ammesso(self):
        schema = SCHEMA.replace('| `nota` | sistema | testo |', '| `utenti` | processo | numero |')
        self.assertNotIn('duplicate_attribute', codici(schema))

    def test_un_vincolo_puo_citare_un_attributo(self):
        schema = BASE.replace(FONTI, ATTRIBUTI + VINCOLO + FONTI)
        self.assertEqual(codici(schema), set())
        self.assertIn('unknown_relation', codici(schema.replace('`data_liquidazione_prevista` | 1', '`inventato` | 1')))
        self.assertIn('invalid_cardinality', codici(schema.replace('| 1 | | domanda |', '| 1 | 2 | domanda |')))

    def test_la_chiave_attributi_e_riservata_in_quattro_posti(self):
        for nome, insieme in (('ontology.SPECIAL', ontology.SPECIAL), ('build_graph.NON_RELAZIONI', build_graph.NON_RELAZIONI),
                              ('correzioni.NON_RELAZIONI', correzioni.NON_RELAZIONI), ('graph_edit.RESERVED', graph_edit.RESERVED)):
            with self.subTest(nome):
                self.assertIn('attributi', insieme)

    def test_una_relazione_chiamata_attributi_e_riservata(self):
        schema = BASE.replace('| `usa` | processo | sistema |', '| `attributi` | processo | sistema |')
        self.assertIn('reserved_relation', codici(schema))


class Preview(unittest.TestCase):
    def patch(self, *operazioni):
        candidate, renames, _ = ontology_preview._patch(parse(SCHEMA), list(operazioni), [])
        return parse(candidate), renames

    def test_aggiungere_un_tipo_conserva_la_sezione(self):
        after, _ = self.patch({'op': 'add_type', 'name': 'app', 'value': {'description': 'App', 'parent': 'servizio'}})
        self.assertEqual(after.attributes, parse(SCHEMA).attributes)

    def test_rinominare_un_tipo_citato_e_rifiutato(self):
        with self.assertRaises(ContractError) as errore:
            self.patch({'op': 'rename_type', 'name': 'processo', 'to': 'attivita'})
        self.assertIn('unknown_type', {d['code'] for d in errore.exception.details})


class Build(unittest.TestCase):
    def costruisci(self, schema, **pagine):
        cartella = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, cartella, True)
        parsed = build_graph.parse_documents(documenti(schema, **pagine))
        self.assertEqual(parsed['problemi'], ())
        db = sqlite3.connect(build_graph.build_candidate(parsed, cartella / 'graph.sqlite'))
        self.addCleanup(db.close)
        return db

    def test_valori_normalizzati_e_tabelle(self):
        db = self.costruisci(SCHEMA,
                             Rilascio=pagina('processo', {'data_liquidazione_prevista': '2031-12-31',
                                                          'importo_previsto': '250000 EUR'}),
                             Console=pagina('sistema', {'codice_progetto': 'PRJ-42', 'livello': 'alto', 'utenti': '1500',
                                                        'nota': 'da rivedere'}),
                             Gateway=pagina('servizio', {'critico': 'true', 'codice_progetto': '12345'}))
        valori = dict(((e, a), v) for e, a, v in db.execute('SELECT entity_id, attributo, valore FROM entity_attributi'))
        self.assertEqual(valori[('Rilascio', 'data_liquidazione_prevista')], '2031-12-31')
        self.assertEqual(valori[('Rilascio', 'importo_previsto')], '250000 EUR')
        self.assertEqual(valori[('Console', 'utenti')], '1500')
        self.assertEqual(valori[('Console', 'livello')], 'alto')
        self.assertEqual(valori[('Gateway', 'critico')], 'sì')  # un sottotipo eredita gli attributi del tipo
        self.assertEqual(valori[('Gateway', 'codice_progetto')], '12345')
        self.assertEqual(db.execute('SELECT nome, tipo, valore, descrizione, posizione FROM onto_attributi '
                                    'ORDER BY posizione LIMIT 2').fetchall(),
                         [('data_liquidazione_prevista', 'processo', 'data', 'Quando si liquida', 0),
                          ('importo_previsto', 'processo', 'importo', 'Importo atteso', 1)])
        metadati = dict(db.execute('SELECT chiave, valore FROM onto_metadata'))
        self.assertEqual(metadati['attributi'], 'presenti')

    def test_la_data_di_yaml_si_normalizza(self):
        # YAML legge 2031-12-31 senza apici come datetime.date
        testo = '---\ntipo: processo\nattributi:\n  data_liquidazione_prevista: 2031-12-31\n---\ntesto\n'
        self.assertIsInstance(build_graph.leggi_testo(testo, 'P')[0]['attributi']['data_liquidazione_prevista'], datetime.date)
        db = self.costruisci(SCHEMA, P=testo)
        self.assertEqual(db.execute("SELECT valore FROM entity_attributi").fetchone(), ('2031-12-31',))

    def test_senza_sezione_la_mappa_si_ignora(self):
        db = self.costruisci(BASE, P=pagina('processo', {'qualunque': 'cosa'}))
        self.assertEqual(db.execute('SELECT count(*) FROM entity_attributi').fetchone(), (0,))
        self.assertEqual(db.execute('SELECT count(*) FROM onto_attributi').fetchone(), (0,))
        self.assertEqual(dict(db.execute('SELECT chiave, valore FROM onto_metadata'))['attributi'], 'assenti')

    def test_attributi_non_e_una_relazione(self):
        db = self.costruisci(SCHEMA, P=pagina('processo', {'importo_previsto': '1 EUR'}))
        self.assertEqual(db.execute("SELECT count(*) FROM relations WHERE type = 'attributi'").fetchone(), (0,))

    def test_errori_per_pagina(self):
        casi = {
            'unknown_attribute': ('processo', {'inventato': 'x'}),
            'unknown_attribute ': ('processo', {'codice_progetto': 'X1'}),  # dichiarato per sistema, non per processo
            'attribute_type': ('sistema', {'utenti': 'molti'}),
            'attribute_value': ('processo', {'data_liquidazione_prevista': '2031-13-45'}),
            'attribute_value ': ('processo', {'importo_previsto': 'tanto'}),
            'attribute_value  ': ('sistema', {'livello': 'generale'}),  # esiste ma non è sotto «rischio»
            'attribute_value   ': ('sistema', {'codice_progetto': '"con spazi"'}),
            'attribute_value    ': ('servizio', {'critico': 'forse'}),
        }
        for etichetta, (tipo, attributi) in casi.items():
            with self.subTest(etichetta):
                self.assertIn(etichetta.strip(), problemi(SCHEMA, P=pagina(tipo, attributi)))

    def test_attributi_deve_essere_una_mappa(self):
        testo = '---\ntipo: processo\nattributi: [uno, due]\n---\ntesto\n'
        self.assertIn('attribute_type', problemi(SCHEMA, P=testo))

    def test_una_categoria_sotto_quella_indicata_vale(self):
        self.assertEqual(problemi(SCHEMA, P=pagina('sistema', {'livello': 'rischio'})), set())
        self.assertEqual(problemi(SCHEMA, P=pagina('sistema', {'livello': 'alto'})), set())


class Recall(unittest.TestCase):
    def contesto(self, schema, domanda, **pagine):
        _, db = crea_vault(self, schema, **pagine)
        semi, fatti, omessi = recall.richiama(db, domanda)
        info = {id_: (tipo, descr) for id_, tipo, descr in db.execute('SELECT id, tipo, descrizione FROM entities')}
        return recall.formatta(semi, fatti, info, omessi, db), recall.formatta(semi, fatti, info, omessi)

    PAGINE = dict(Rilascio=pagina('processo', {'data_liquidazione_prevista': '2031-12-31', 'importo_previsto': '250000 EUR'}),
                  Console=pagina('sistema'))

    def test_gli_attributi_sotto_il_seme(self):
        con, senza = self.contesto(SCHEMA, 'quando si liquida Rilascio?', **self.PAGINE)
        self.assertIn('- Rilascio [processo]: \n  · data_liquidazione_prevista: 2031-12-31; importo_previsto: 250000 EUR', con)
        self.assertNotIn('2031-12-31', senza)  # senza il grafo il contesto è quello di prima

    def test_nell_ordine_della_sezione_e_con_un_tetto(self):
        with mock.patch.object(recall, 'MAX_ATTRIBUTI', 1):
            con, _ = self.contesto(SCHEMA, 'quando si liquida Rilascio?', **self.PAGINE)
        self.assertIn('  · data_liquidazione_prevista: 2031-12-31\n', con)
        self.assertNotIn('importo_previsto', con)

    def test_una_pagina_senza_attributi_non_ha_righe(self):
        con, _ = self.contesto(SCHEMA, 'cosa fa la Console?', **self.PAGINE)
        self.assertNotIn('  · ', con)

    def test_senza_la_sezione_il_contesto_non_cambia(self):
        con, senza = self.contesto(BASE, 'quando si liquida Rilascio?', Rilascio=pagina('processo'), Console=pagina('sistema'))
        self.assertEqual(con, senza)

    def test_grafo_senza_la_tabella(self):
        db = sqlite3.connect(':memory:')
        self.addCleanup(db.close)
        self.assertEqual(recall.attributi_delle_pagine(db, ['A']), {})


class Vincoli(unittest.TestCase):
    def rileva(self, schema, **pagine):
        vault, db = crea_vault(self, schema, **pagine)
        originale = domande.apri
        with mock.patch.object(domande, 'apri', lambda path=':memory:': originale(':memory:')):
            return domande.rileva(db, vault)

    SCHEMA = BASE.replace(FONTI, ATTRIBUTI + VINCOLO + FONTI)

    def test_attributo_obbligatorio_mancante_e_una_domanda(self):
        risultato = self.rileva(self.SCHEMA, P=pagina('processo'),
                                Q=pagina('processo', {'data_liquidazione_prevista': '2031-12-31'}))
        self.assertNotIn('Q', risultato)
        self.assertEqual([(s, k) for s, _, k in risultato['P']], [('vincolo', 'vincolo|P|data_liquidazione_prevista min')])
        self.assertIn('data_liquidazione_prevista', risultato['P'][0][1])

    def test_se_manca_nulla(self):
        schema = self.SCHEMA.replace('| 1 | | domanda |', '| 1 | | nulla |')
        self.assertEqual(self.rileva(schema, P=pagina('processo')), {})

    def test_un_sottotipo_eredita(self):
        schema = self.SCHEMA.replace('| `processo` | `data_liquidazione_prevista`', '| `sistema` | `codice_progetto`')
        risultato = self.rileva(schema, G=pagina('servizio'))
        self.assertEqual([(s, k) for s, _, k in risultato['G']], [('vincolo', 'vincolo|G|codice_progetto min')])


class Api(unittest.TestCase):
    stop = fixture.Queries.stop
    request = fixture.Queries.request
    manifest = fixture.Queries.manifest
    hashes = fixture.Queries.hashes
    attach = fixture.Queries.attach
    get = fixture.Queries.get

    def setUp(self):
        fixture.Queries.setUp(self)
        (self.root / 'Wiki reference.md').write_text(SCHEMA, encoding='utf-8')
        for path in (self.root / 'wiki').glob('*.md'):
            path.unlink()
        (self.root / 'wiki' / 'Console.md').write_text(pagina('sistema', {'utenti': '5'}), encoding='utf-8')
        self.reference = rebuild(self.root)

    def test_ontology_espone_gli_attributi(self):
        status, _, body = self.get('ontology')
        self.assertEqual(status, 200, body)
        self.assertEqual(body['attributes'][0], {'name': 'data_liquidazione_prevista', 'of_type': 'processo',
                                                 'value_type': 'data', 'description': 'Quando si liquida'})


if __name__ == '__main__':
    unittest.main()
