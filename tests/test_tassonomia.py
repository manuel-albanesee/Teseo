"""Voce B1 di doc/16: sottotipi nei «Tipi ammessi», sezione «Categorie», tag controllati e faccetta per categoria."""
import _shortpath  # noqa: F401
import shutil
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

import test_dashboard_queries as fixture
import test_piano_ingest as piano_fixture
from kit.dashboard import ontology_preview
from kit.dashboard.contracts import ContractError, canonical_json, content_hash, file_hash
from kit.dashboard.graph_service import rebuild
from kit.graph import build_graph
from kit.graph.ontology import Category, TypeDef, parse, serialize

KIT = Path(__file__).resolve().parents[1] / 'kit'
sys.path.insert(0, str(KIT / 'graph'))
import build_graph as build_graph_installato  # noqa: E402  (stesso modulo che importa piano.py)

TIPI = ('## Tipi ammessi\n| Tipo | Descrizione | Sottotipo di |\n| --- | --- | --- |\n'
        '| `sistema` | Strumenti | |\n| `servizio` | Servizi web | sistema |\n| `portale` | Portali | servizio |\n'
        '| `persona` | Persone | |\n| `processo` | Attività | |\n| `fonte` | Fonti | |\n')
RELAZIONI = ('## Relazioni tipizzate\n| Relazione | Da (tipo) | A (tipo) | Significato | Esempio |\n'
             '| --- | --- | --- | --- | --- |\n'
             '| `usa` | processo | sistema | X funziona tramite Y | Rilascio → Console |\n'
             '| `variante_di` | qualsiasi | stesso tipo | X è un gemello di Y | B → A |\n')
CATEGORIE = ('## Categorie\n| Categoria | Più ampia | Descrizione |\n| --- | --- | --- |\n'
             '| amministrazione | | Processi amministrativi |\n| fatturazione | amministrazione | Fatture |\n'
             '| ciclo-passivo | fatturazione | Fatture ricevute |\n| rilasci | | Messa in produzione |\n')
FONTI = '## Chiavi delle fonti\n| `nota-utente` | Precisazione |\n'
SCHEMA = '# Schema\n' + TIPI + RELAZIONI + CATEGORIE + FONTI


def pagina(tipo, tags=(), **relazioni):
    righe = ''.join('%s: "[[%s]]"\n' % (k, v) for k, v in relazioni.items())
    etichette = 'tags: [%s]\n' % ', '.join(tags) if tags else ''
    return '---\ntipo: %s\n%s%s---\ntesto\n' % (tipo, etichette, righe)


def documenti(schema=SCHEMA, **pagine):
    return {'Wiki reference.md': schema, **{'wiki/%s.md' % nome: testo for nome, testo in pagine.items()}}


def codici(parsed):
    return {item['code'] for item in parsed['problem_details']}


class Parser(unittest.TestCase):
    def test_sottotipi_categorie_e_antenati(self):
        document = parse(SCHEMA)
        self.assertEqual([i for i in document.issues if i.severity == 'error'], [])
        self.assertEqual(document.types[1], TypeDef('servizio', 'Servizi web', 'sistema'))
        self.assertEqual(document.ancestors['portale'], ('servizio', 'sistema'))
        self.assertEqual(document.ancestors['sistema'], ())
        self.assertEqual(document.categories[2], Category('ciclo-passivo', 'fatturazione', 'Fatture ricevute'))
        self.assertTrue(document.editable)

    def test_roundtrip_e_categorie_conservate_byte_per_byte(self):
        document = parse(SCHEMA)
        self.assertEqual(serialize(document), SCHEMA.encode())
        candidate = serialize(document, types=document.types + (TypeDef('entita', 'Altro'),))
        after = parse(candidate)
        self.assertEqual(after.types[-1], TypeDef('entita', 'Altro'))
        self.assertIn(CATEGORIE.encode(), candidate)
        self.assertNotIn(b'| amministrazione |', document.opaque_bytes())  # non sono «Chiavi delle fonti»

    def test_terza_colonna_solo_se_serve(self):
        document = parse(SCHEMA)
        radici = tuple(TypeDef(t.name, t.description) for t in document.types)
        self.assertIn(b'| Tipo | Descrizione |\n| --- | --- |\n', serialize(document, types=radici))
        due = parse(SCHEMA.replace(TIPI, '## Tipi ammessi\n| Tipo | Descrizione |\n| --- | --- |\n'
                                   '| `sistema` | S |\n| `processo` | P |\n| `persona` | Q |\n| `fonte` | F |\n'))
        figli = due.types + (TypeDef('servizio', '', 'sistema'),)
        self.assertIn(b'| `servizio` |  | sistema |', serialize(due, types=figli))

    def test_errori_della_gerarchia(self):
        casi = {
            'unknown_parent': SCHEMA.replace('| `servizio` | Servizi web | sistema |', '| `servizio` | Servizi web | nessuno |'),
            'type_cycle': SCHEMA.replace('| `sistema` | Strumenti | |', '| `sistema` | Strumenti | portale |'),
            'unknown_broader': SCHEMA.replace('| fatturazione | amministrazione |', '| fatturazione | contabilita |'),
            'category_cycle': SCHEMA.replace('| amministrazione | |', '| amministrazione | ciclo-passivo |'),
            'duplicate_category': SCHEMA.replace('| rilasci | |', '| Fatturazione | |'),
            'unrecognized_table': SCHEMA.replace('| Categoria | Più ampia | Descrizione |', '| Nome | Padre | Descrizione |'),
        }
        for codice, schema in casi.items():
            with self.subTest(codice):
                self.assertIn(codice, {i.code for i in parse(schema).issues if i.severity == 'error'})
        self.assertIn('unknown_parent', {i.code for i in parse(SCHEMA.replace('| `processo` | Attività | |',
                                                                             '| `processo` | Attività | processo |')).issues})


class Builder(unittest.TestCase):
    def test_un_sottotipo_soddisfa_i_vincoli_degli_antenati(self):
        parsed = build_graph.parse_documents(documenti(Rilascio=pagina('processo', usa='Portale'),
                                                       Portale=pagina('portale')))
        self.assertEqual(parsed['problemi'], ())
        self.assertIn(('Rilascio', 'Portale', 'usa'), parsed['relazioni'])

    def test_stesso_tipo_resta_uguaglianza_esatta(self):
        parsed = build_graph.parse_documents(documenti(A=pagina('servizio', variante_di='B'), B=pagina('sistema')))
        self.assertEqual(codici(parsed), {'relation_types'})

    def test_senza_sottotipo_il_vincolo_resta_violato(self):
        parsed = build_graph.parse_documents(documenti(Rilascio=pagina('processo', usa='Anna'), Anna=pagina('persona')))
        self.assertEqual(codici(parsed), {'relation_types'})

    def test_tag_controllati_solo_con_la_sezione(self):
        pagine = dict(A=pagina('sistema', ['fatturazione', 'entropia', 'sintesi']), B=pagina('sistema', ['inventato']))
        parsed = build_graph.parse_documents(documenti(**pagine))
        self.assertEqual([(d['code'], d['page'], d['target']) for d in parsed['problem_details']],
                         [('unknown_tag', 'wiki/B.md', 'inventato')])
        libero = build_graph.parse_documents(documenti(SCHEMA.replace(CATEGORIE, ''), **pagine))
        self.assertEqual(libero['problemi'], ())

    def test_tabelle_della_tassonomia(self):
        cartella = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, cartella, True)
        snapshot = build_graph.parse_documents(documenti(
            Fatture=pagina('servizio', ['ciclo-passivo']), Gestionale=pagina('sistema', ['amministrazione', 'rilasci']),
            Console=pagina('sistema', ['rilasci']), Rilascio=pagina('processo', usa='Fatture')))
        db = sqlite3.connect(build_graph.build_candidate(snapshot, cartella / 'graph.sqlite'))
        self.addCleanup(db.close)
        self.assertEqual(dict(db.execute('SELECT nome, padre FROM onto_tipi')),
                         {'sistema': None, 'servizio': 'sistema', 'portale': 'servizio', 'persona': None,
                          'processo': None, 'fonte': None})
        self.assertEqual(db.execute('SELECT nome, padre, descrizione FROM categorie ORDER BY posizione').fetchall(),
                         [('amministrazione', None, 'Processi amministrativi'), ('fatturazione', 'amministrazione', 'Fatture'),
                          ('ciclo-passivo', 'fatturazione', 'Fatture ricevute'), ('rilasci', None, 'Messa in produzione')])
        self.assertEqual(db.execute('SELECT entity_id, tag FROM entity_tags ORDER BY 1, 2').fetchall(),
                         [('Console', 'rilasci'), ('Fatture', 'ciclo-passivo'), ('Gestionale', 'amministrazione'),
                          ('Gestionale', 'rilasci')])
        self.assertEqual(dict(db.execute('SELECT chiave, valore FROM onto_metadata'))['categorie'], 'presenti')
        sotto = [n for (n,) in db.execute(
            "WITH RECURSIVE sotto(nome) AS (SELECT 'amministrazione' UNION SELECT c.nome FROM categorie c "
            "JOIN sotto s ON c.padre = s.nome) SELECT DISTINCT entity_id FROM entity_tags "
            "WHERE tag IN (SELECT nome FROM sotto) ORDER BY 1")]
        self.assertEqual(sotto, ['Fatture', 'Gestionale'])


class Piano(piano_fixture.Base):
    catalogo = True

    def test_il_piano_accetta_un_sottotipo(self):
        schema = (self.vault / 'Wiki reference.md').read_text(encoding='utf-8')
        schema = schema.replace('| Tipo | Descrizione |\n| --- | --- |\n', '| Tipo | Descrizione | Sottotipo di |\n| --- | --- | --- |\n')
        schema = schema.replace('| tipo di prova |\n| `entita`', '| tipo di prova | |\n| `servizio` | Servizi | sistema |\n| `entita`', 1)
        schema = schema.replace(' | tipo di prova |\n', ' | tipo di prova | |\n')
        (self.vault / 'Wiki reference.md').write_text(schema, encoding='utf-8')
        testo = piano_fixture.PIANO.replace('[[Finestra di rilascio]] — tipo: processo', '[[Portale rilasci]] — tipo: servizio')
        testo = testo.replace('→ richiede → [[Finestra di rilascio]]', '→ usa → [[Portale rilasci]]')
        testo = testo.replace('- [[Finestra di rilascio]]: «slot di rilascio», «finestra»', '- nessuna')
        self.assertEqual(self.controlla(testo), [])
        self.assertIs(build_graph_installato.tipo_ammesso({'sistema'}, 'servizio', None, {'servizio': ('sistema',)}), True)


class Preview(unittest.TestCase):
    def patch(self, *operazioni):
        candidate, renames, _ = ontology_preview._patch(parse(SCHEMA), list(operazioni), [])
        return parse(candidate), renames

    def test_aggiungi_e_modifica_il_padre(self):
        after, _ = self.patch({'op': 'add_type', 'name': 'app', 'value': {'description': 'App', 'parent': 'servizio'}})
        self.assertEqual(after.ancestors['app'], ('servizio', 'sistema'))
        after, _ = self.patch({'op': 'update_type', 'name': 'portale', 'value': {'description': 'Portali'}})
        self.assertEqual(after.ancestors['portale'], ())  # definizione completa: padre omesso → radice

    def test_rinomina_aggiorna_i_padri_e_rimozione_del_padre_rifiutata(self):
        after, renames = self.patch({'op': 'rename_type', 'name': 'servizio', 'to': 'servizio_web'})
        self.assertEqual(after.ancestors['portale'], ('servizio_web', 'sistema'))
        with self.assertRaises(ContractError) as errore:
            self.patch({'op': 'remove_type', 'name': 'servizio'})
        self.assertIn('unknown_parent', {d['code'] for d in errore.exception.details})


class Faccetta(unittest.TestCase):
    stop = fixture.Queries.stop
    request = fixture.Queries.request
    manifest = fixture.Queries.manifest
    hashes = fixture.Queries.hashes
    attach = fixture.Queries.attach
    get = fixture.Queries.get

    def setUp(self):
        fixture.Queries.setUp(self)
        (self.root / 'Wiki reference.md').write_text(SCHEMA.replace('| `usa` | processo |', '| `usa` | qualsiasi |'),
                                                     encoding='utf-8')
        for nome in ('Anna Rossi', 'Bruno', 'Équipe'):
            (self.root / 'wiki' / (nome + '.md')).unlink()
        pagine = {'Fatture': pagina('servizio', ['ciclo-passivo'], usa='Gestionale'),
                  'Gestionale': pagina('sistema', ['amministrazione'], usa='Console'),
                  'Console': pagina('sistema', ['rilasci']), 'Anna': pagina('persona')}
        for nome, testo in pagine.items():
            (self.root / 'wiki' / (nome + '.md')).write_text(testo, encoding='utf-8')
        self.reference = rebuild(self.root)

    def test_categoria_con_sottocategorie_e_archi_interni(self):
        status, _, body = self.get('graph', {'category': 'amministrazione'})
        self.assertEqual(status, 200, body)
        self.assertEqual([n['id'] for n in body['nodes']], ['Fatture', 'Gestionale'])
        self.assertEqual([(e['source_id'], e['target_id']) for e in body['edges']], [('Fatture', 'Gestionale')])
        status, _, body = self.get('graph', {'category': 'ciclo-passivo'})
        self.assertEqual([n['id'] for n in body['nodes']], ['Fatture'])
        status, _, body = self.get('graph', {'category': 'sconosciuta'})
        self.assertEqual((status, body['nodes'], body['edges']), (200, [], []))
        self.assertEqual(self.get('graph', {'category': ''})[0], 400)

    def test_ontology_espone_gerarchie(self):
        status, _, body = self.get('ontology')
        self.assertEqual(status, 200, body)
        self.assertEqual(body['type_parents'], {'servizio': 'sistema', 'portale': 'servizio'})
        self.assertEqual(body['categories'][1], {'name': 'fatturazione', 'broader': 'amministrazione', 'description': 'Fatture'})

    def test_generazione_precedente_senza_tabelle(self):
        generation = content_hash({'content_revision': self.reference.content_revision, 'builder_version': 5, 'copia': 1})
        old = self.reference.path.with_name(generation + '.sqlite')
        shutil.copyfile(self.reference.path, old)
        db = sqlite3.connect(old)
        try:
            for tabella in ('categorie', 'entity_tags'):
                db.execute('DROP TABLE ' + tabella)
            db.executemany('UPDATE graph_metadata SET value=? WHERE key=?', [('5', 'builder_version'), (generation, 'generation')])
            db.commit()
        finally:
            db.close()
        (self.root / '.teseo/local/graph-current.json').write_bytes(canonical_json({
            'format_version': 1, 'content_revision': self.reference.content_revision, 'generation': generation,
            'sqlite_sha256': file_hash(old)}))
        status, _, body = self.get('graph', {'category': 'amministrazione'})
        self.assertEqual((status, body['error']['code']), (503, 'graph_upgrade_required'))
        status, _, body = self.get('ontology')
        self.assertEqual(status, 200, body)
        self.assertEqual(body['type_parents'], {'servizio': 'sistema', 'portale': 'servizio'})
        self.assertEqual(len(body['categories']), 4)


if __name__ == '__main__':
    unittest.main()
