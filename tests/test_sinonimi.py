"""Fase 3a di doc/17: sinonimi e corrispondenze interni in Wiki reference.md, e il sinonimo come seme (B3 di doc/16)."""
import _shortpath  # noqa: F401
from contextlib import redirect_stdout
import io
from pathlib import Path
import shutil
import sqlite3
import sys
import tempfile
import unittest
from unittest import mock

import test_dashboard_queries as fixture
from kit.dashboard import ontology_preview
from kit.dashboard.contracts import ContractError
from kit.dashboard.graph_service import rebuild
from kit.graph import build_graph
from kit.graph.ontology import Correspondence, Synonyms, TypeDef, parse, serialize

KIT = Path(__file__).resolve().parents[1] / 'kit'
sys.path.insert(0, str(KIT / 'graph'))
import recall  # noqa: E402
import recall_hook  # noqa: E402
from graph_db import connect_graph  # noqa: E402

TIPI = ('## Tipi ammessi\n| Tipo | Descrizione | Sottotipo di |\n| --- | --- | --- |\n'
        '| `sistema` | Strumenti | |\n| `servizio` | Servizi web | sistema |\n| `processo` | Attività | |\n'
        '| `fonte` | Fonti | |\n')
RELAZIONI = ('## Relazioni tipizzate\n| Relazione | Da (tipo) | A (tipo) | Significato | Esempio |\n'
             '| --- | --- | --- | --- | --- |\n| `usa` | processo | sistema | X funziona tramite Y | A → B |\n')
CATEGORIE = ('## Categorie\n| Categoria | Più ampia | Descrizione |\n| --- | --- | --- |\n'
             '| amministrazione | | Processi amministrativi |\n| fatturazione | amministrazione | Fatture |\n'
             '| rilasci | | Messa in produzione |\n| generale | | Tutto |\n')
FONTI = '## Chiavi delle fonti\n| `nota-utente` | Precisazione |\n| `fibo` | Vocabolario FIBO |\n'
SINONIMI = ('## Sinonimi\n| Nome | Sinonimi |\n| --- | --- |\n'
            '| `fatturazione` | billing; contabilità clienti |\n| `servizio` | SPV; servizi web |\n'
            '| `sistema` | strumenti |\n')
CORRISPONDENZE = ('## Corrispondenze\n| Nome | Corrispondenza | Vocabolario | Esattezza |\n| --- | --- | --- | --- |\n'
                  '| `servizio` | fibo-fnd:Service | fibo | esatta |\n'
                  '| `fatturazione` | https://example.org/Invoicing | fibo | vicina |\n')
BASE = '# Schema\n' + TIPI + RELAZIONI + CATEGORIE + FONTI
SCHEMA = '# Schema\n' + TIPI + RELAZIONI + CATEGORIE + SINONIMI + CORRISPONDENZE + FONTI


def pagina(tipo, tags=(), alias=()):
    righe = ('tags: [%s]\n' % ', '.join(tags) if tags else '') + ('aliases: [%s]\n' % ', '.join(alias) if alias else '')
    return '---\ntipo: %s\n%s---\ntesto\n' % (tipo, righe)


PAGINE = {
    'Fatture': pagina('servizio', ['fatturazione']),
    'Fornitori': pagina('processo', ['fatturazione']),
    'Console': pagina('sistema'),
    'Gateway': pagina('servizio'),
    'Rilascio': pagina('processo', ['rilasci']),
    **{f'Filler{i}': pagina('sistema' if i < 4 else 'processo', ['generale']) for i in range(6)},
}


def codici(schema):
    return {i.code for i in parse(schema).issues if i.severity == 'error'}


def documenti(schema, **pagine):
    return {'Wiki reference.md': schema, **{'wiki/%s.md' % nome: testo for nome, testo in pagine.items()}}


class Base(unittest.TestCase):
    def vault(self, schema=SCHEMA, **extra):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        vault = Path(temp.name)
        (vault / 'wiki').mkdir()
        (vault / '.graph').mkdir()
        (vault / 'Wiki reference.md').write_text(schema, encoding='utf-8')
        for nome in ('index.md', 'log.md'):
            (vault / nome).write_text('# ' + nome + '\n', encoding='utf-8')
        for nome, testo in {**PAGINE, **extra}.items():
            (vault / 'wiki' / (nome + '.md')).write_text(testo, encoding='utf-8')
        with redirect_stdout(io.StringIO()):
            build_graph.costruisci(vault, vault / '.graph/graph.sqlite')
        db = connect_graph(vault / '.graph/graph.sqlite')
        self.addCleanup(db.close)
        return db

    def aggregati(self, db, domanda):
        semi, fatti, _ = recall.richiama(db, domanda)
        return ([s for s in semi if s[1].split(',')[0] in ('categoria', 'tipo')],
                [f for f in fatti if f['tipo'] in ('categoria', 'tipo')])


class Parser(unittest.TestCase):
    def test_sinonimi_e_corrispondenze(self):
        document = parse(SCHEMA)
        self.assertEqual([i for i in document.issues if i.severity == 'error'], [])
        self.assertEqual(document.synonyms[0], Synonyms('fatturazione', ('billing', 'contabilità clienti')))
        self.assertEqual(document.synonyms[1], Synonyms('servizio', ('SPV', 'servizi web')))
        self.assertEqual(document.matches[0], Correspondence('servizio', 'fibo-fnd:Service', 'fibo', 'esatta'))
        self.assertEqual(document.matches[1].exactness, 'vicina')
        self.assertTrue(document.editable)
        self.assertEqual(set(document.source_spans), {'types', 'relations', 'categories', 'synonyms', 'matches'})

    def test_senza_sezioni_restano_none(self):
        document = parse(BASE)
        self.assertIsNone(document.synonyms)
        self.assertIsNone(document.matches)
        self.assertNotIn('synonym_seeds', document.capabilities)

    def test_funzionalita_attivata(self):
        self.assertIn('synonym_seeds', parse(SCHEMA).capabilities)
        self.assertNotIn('synonym_seeds', parse(BASE + CORRISPONDENZE).capabilities)  # le sole corrispondenze non cambiano il recall

    def test_roundtrip_e_sezioni_conservate_byte_per_byte(self):
        document = parse(SCHEMA)
        self.assertEqual(serialize(document), SCHEMA.encode())
        candidate = serialize(document, types=document.types + (TypeDef('entita', 'Altro'),))
        self.assertIn(SINONIMI.encode(), candidate)
        self.assertIn(CORRISPONDENZE.encode(), candidate)
        self.assertNotIn(b'billing', document.opaque_bytes())

    def test_errori(self):
        casi = {
            'unknown_name': SCHEMA.replace('| `sistema` | strumenti |', '| `inventato` | strumenti |'),
            'duplicate_synonyms': SCHEMA.replace('| `sistema` | strumenti |', '| `servizio` | strumenti |'),
            'invalid_synonyms': SCHEMA.replace('| `sistema` | strumenti |', '| `sistema` | |'),
            'synonym_collision': SCHEMA.replace('| `sistema` | strumenti |', '| `sistema` | processo |'),  # il nome di un altro tipo
            'invalid_iri': SCHEMA.replace('fibo-fnd:Service', 'non un iri'),
            'invalid_exactness': SCHEMA.replace('| esatta |', '| quasi |'),
            'duplicate_match': SCHEMA.replace('https://example.org/Invoicing | fibo | vicina |\n',
                                              'https://example.org/Invoicing | fibo | vicina |\n'
                                              '| `fatturazione` | https://example.org/Invoicing | fibo | esatta |\n'),
            'unrecognized_table': SCHEMA.replace('| Nome | Sinonimi |', '| Nome | Alias |'),
        }
        for codice, schema in casi.items():
            with self.subTest(codice):
                self.assertIn(codice, codici(schema))

    def test_collisioni_fra_sinonimi_e_con_il_proprio_nome(self):
        diverso = SCHEMA.replace('| `sistema` | strumenti |', '| `sistema` | S.P.V. |')  # «s p v» non è «spv»
        self.assertNotIn('synonym_collision', codici(diverso))
        uguale = SCHEMA.replace('| `sistema` | strumenti |', '| `sistema` | Spv |')  # uguale a «SPV» dopo norm
        self.assertIn('synonym_collision', codici(uguale))
        proprio = SCHEMA.replace('| `sistema` | strumenti |', '| `sistema` | Sistema |')
        self.assertIn('synonym_collision', codici(proprio))

    def test_la_norma_dei_sinonimi_e_quella_del_builder(self):
        from kit.graph import ontology
        for testo in ('Contabilità Clienti', 'S.P.V.', 'ciclo-passivo', 'Èè ùà', 'a_b  c'):
            with self.subTest(testo):
                self.assertEqual(ontology._norm(testo), build_graph.norm(testo))

    def test_il_nome_puo_essere_una_categoria_o_un_tipo(self):
        self.assertEqual(codici(SCHEMA), set())
        self.assertIn('unknown_name', codici(SCHEMA.replace('| `fatturazione` | billing', '| `fatturazioni` | billing')))


class Preview(unittest.TestCase):
    def patch(self, *operazioni):
        candidate, renames, _ = ontology_preview._patch(parse(SCHEMA), list(operazioni), [])
        return parse(candidate), renames

    def test_aggiungere_un_tipo_conserva_le_sezioni(self):
        after, _ = self.patch({'op': 'add_type', 'name': 'app', 'value': {'description': 'App', 'parent': 'servizio'}})
        self.assertEqual(after.synonyms, parse(SCHEMA).synonyms)
        self.assertEqual(after.matches, parse(SCHEMA).matches)

    def test_rinominare_un_tipo_citato_e_rifiutato(self):
        with self.assertRaises(ContractError) as errore:
            self.patch({'op': 'rename_type', 'name': 'servizio', 'to': 'servizi'})
        self.assertIn('unknown_name', {d['code'] for d in errore.exception.details})


class Tabelle(unittest.TestCase):
    def costruisci(self, schema, **pagine):
        cartella = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, cartella, True)
        parsed = build_graph.parse_documents(documenti(schema, **pagine))
        db = sqlite3.connect(build_graph.build_candidate(parsed, cartella / 'graph.sqlite'))
        self.addCleanup(db.close)
        return parsed, db

    def test_tabelle_e_metadati(self):
        parsed, db = self.costruisci(SCHEMA)
        self.assertEqual(parsed['problemi'], ())
        self.assertEqual(db.execute('SELECT nome, sinonimo, posizione FROM onto_sinonimi ORDER BY posizione').fetchall(),
                         [('fatturazione', 'billing', 0), ('fatturazione', 'contabilità clienti', 1),
                          ('servizio', 'SPV', 2), ('servizio', 'servizi web', 3), ('sistema', 'strumenti', 4)])
        self.assertEqual(db.execute('SELECT nome, iri, vocabolario, esattezza, posizione FROM onto_corrispondenze '
                                    'ORDER BY posizione').fetchall(),
                         [('servizio', 'fibo-fnd:Service', 'fibo', 'esatta', 0),
                          ('fatturazione', 'https://example.org/Invoicing', 'fibo', 'vicina', 1)])
        metadati = dict(db.execute('SELECT chiave, valore FROM onto_metadata'))
        self.assertEqual((metadati['sinonimi'], metadati['corrispondenze']), ('presenti', 'presenti'))

    def test_senza_sezioni_tabelle_vuote(self):
        _, db = self.costruisci(BASE)
        self.assertEqual(db.execute('SELECT count(*) FROM onto_sinonimi').fetchone(), (0,))
        self.assertEqual(db.execute('SELECT count(*) FROM onto_corrispondenze').fetchone(), (0,))
        metadati = dict(db.execute('SELECT chiave, valore FROM onto_metadata'))
        self.assertEqual((metadati['sinonimi'], metadati['corrispondenze']), ('assenti', 'assenti'))

    def test_chiave_di_vocabolario_non_censita(self):
        parsed = build_graph.parse_documents(documenti(SCHEMA.replace('| `fibo` | Vocabolario FIBO |\n', '')))
        self.assertIn('unknown_vocabulary_key', {d['code'] for d in parsed['problem_details']})
        self.assertTrue(any('fibo' in p for p in parsed['problemi']))

    def test_la_pagina_vince_un_avviso_non_un_errore(self):
        parsed, _ = self.costruisci(SCHEMA, Billing=pagina('sistema'), Gateway=pagina('servizio', alias=['SPV']))
        self.assertEqual(parsed['problemi'], ())
        avvisi = ' '.join(parsed['avvisi'])
        self.assertIn('billing', avvisi)
        self.assertIn('SPV', avvisi)
        self.assertEqual(len(parsed['avvisi']), 2)

    def test_senza_collisioni_nessun_avviso(self):
        parsed, _ = self.costruisci(SCHEMA, **PAGINE)
        self.assertEqual(parsed['avvisi'], ())


class Seme(Base):
    def test_sinonimo_di_categoria_come_il_nome(self):
        db = self.vault()
        semi, fatti = self.aggregati(db, 'quanto costa il billing?')
        self.assertEqual(semi, [('fatturazione', 'categoria, parte di amministrazione', 'Fatture')])
        self.assertEqual(len(fatti), 1)
        self.assertEqual(sorted(fatti[0]['t']), ['Fatture', 'Fornitori'])

    def test_sinonimo_a_piu_parole(self):
        semi, _ = self.aggregati(self.vault(), 'chi gestisce la contabilità clienti?')
        self.assertEqual([s[0] for s in semi], ['fatturazione'])

    def test_le_parole_del_sinonimo_devono_essere_contigue(self):
        db = self.vault()
        self.assertEqual(self.aggregati(db, 'i servizi che usano il web'), ([], []))
        semi, _ = self.aggregati(db, 'quali servizi web ci sono?')
        self.assertEqual([s[0] for s in semi], ['servizio'])

    def test_nome_e_sinonimo_insieme_sono_un_solo_seme(self):
        semi, fatti = self.aggregati(self.vault(), 'la fatturazione, cioè il billing')
        self.assertEqual([s[0] for s in semi], ['fatturazione'])
        self.assertEqual(len(fatti), 1)

    def test_sinonimo_di_tipo(self):
        db = self.vault()
        semi, fatti = self.aggregati(db, 'cosa sono gli SPV?')
        self.assertEqual(semi, [('servizio', 'tipo, sottotipo di sistema', 'Servizi web')])
        self.assertEqual(len(fatti), 1)
        self.assertEqual((fatti[0]['s'], fatti[0]['tipo']), ('servizio', 'tipo'))
        self.assertEqual(sorted(fatti[0]['t']), ['Fatture', 'Gateway'])
        self.assertEqual(fatti[0]['omesse'], 0)

    def test_il_contesto_ha_il_seme_e_il_fatto(self):
        db = self.vault()
        semi, fatti, omessi = recall.richiama(db, 'cosa sono gli SPV?')
        info = {id_: (tipo, descr) for id_, tipo, descr in db.execute('SELECT id, tipo, descrizione FROM entities')}
        testo = recall.formatta(semi, fatti, info, omessi)
        self.assertIn('- servizio [tipo, sottotipo di sistema]: Servizi web', testo)
        self.assertIn('- servizio → tipo → 2 pagine (', testo)

    def test_tetto_e_omesse_valgono_anche_per_i_tipi(self):
        with mock.patch.object(recall, 'MAX_CATEGORIA', 1):
            _, fatti = self.aggregati(self.vault(), 'cosa sono gli SPV?')
        self.assertEqual((len(fatti[0]['t']), fatti[0]['omesse']), (1, 1))

    def test_un_tipo_troppo_generico_non_fa_da_seme(self):
        # «strumenti» è sinonimo di sistema, che con i sottotipi copre più di SOGLIA_CATEGORIA delle pagine
        semi, fatti = self.aggregati(self.vault(), 'quali strumenti ci sono?')
        self.assertEqual((semi, fatti), ([], []))

    def test_la_pagina_vince(self):
        db = self.vault(Billing=pagina('sistema'))
        semi, fatti, _ = recall.richiama(db, 'quanto costa il billing?')
        self.assertEqual([s[0] for s in semi], ['Billing'])
        self.assertEqual([f for f in fatti if f['tipo'] == 'categoria'], [])

    def test_un_alias_di_pagina_vince(self):
        db = self.vault(Gateway=pagina('servizio', alias=['SPV']))
        semi, fatti = self.aggregati(db, 'cosa sono gli SPV?')
        self.assertEqual((semi, fatti), ([], []))

    def test_un_sinonimo_dentro_il_nome_di_una_pagina_riconosciuta_non_conta(self):
        db = self.vault(**{'Billing SPV': pagina('sistema')})
        semi, fatti = self.aggregati(db, 'cosa fa Billing SPV?')
        self.assertEqual((semi, fatti), ([], []))

    def test_parole_comuni(self):
        db = self.vault()
        with mock.patch.object(recall, 'PAROLE_COMUNI', {'spv'}):
            self.assertEqual(self.aggregati(db, 'cosa sono gli spv?'), ([], []))
            semi, _ = self.aggregati(db, 'cosa sono gli SPV?')
        self.assertEqual([s[0] for s in semi], ['servizio'])

    def test_senza_le_sezioni_nulla_cambia(self):
        db = self.vault(BASE)
        self.assertEqual(self.aggregati(db, 'quanto costa il billing? cosa sono gli SPV?'), ([], []))

    def test_grafo_senza_le_tabelle(self):
        db = sqlite3.connect(':memory:')
        self.addCleanup(db.close)
        db.executescript('CREATE TABLE entities (id TEXT, tipo TEXT, tags TEXT, descrizione TEXT);')
        self.assertEqual(recall.tipi_nominati(db, 'gli SPV'), [])
        self.assertEqual(recall.categorie_nominate(db, 'il billing'), [])

    def test_il_ripiego_sul_testo_non_scatta(self):
        db = self.vault()
        with mock.patch.object(recall_hook, 'per_testo_a_cascata', return_value=['X']):
            self.assertEqual(recall_hook.ripiego_testo(db, 'come funzionano gli SPV?', []), [])
            self.assertEqual(recall_hook.ripiego_testo(db, 'quanto costa il billing?', []), [])
            self.assertEqual(recall_hook.ripiego_testo(db, 'che cosa comprende la contabilità?', []), ['X'])


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
        for nome, testo in {'Console': pagina('sistema'), 'Fatture': pagina('servizio', ['fatturazione'])}.items():
            (self.root / 'wiki' / (nome + '.md')).write_text(testo, encoding='utf-8')
        self.reference = rebuild(self.root)

    def test_ontology_espone_sinonimi_e_corrispondenze(self):
        status, _, body = self.get('ontology')
        self.assertEqual(status, 200, body)
        self.assertEqual(body['synonyms'][0], {'name': 'fatturazione', 'synonyms': ['billing', 'contabilità clienti']})
        self.assertEqual(body['matches'][0], {'name': 'servizio', 'iri': 'fibo-fnd:Service', 'vocabulary': 'fibo',
                                              'exactness': 'esatta'})


if __name__ == '__main__':
    unittest.main()
