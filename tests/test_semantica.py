"""Fase 2 di doc/17: semantica dichiarata (ruoli, inverse, transitive e simmetriche) e vincoli in Wiki reference.md."""
import _shortpath  # noqa: F401
from contextlib import redirect_stdout
import io
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

import test_dashboard_queries as fixture
from kit.dashboard import ontology_preview
from kit.dashboard.contracts import ContractError
from kit.dashboard.graph_service import rebuild
from kit.graph import build_graph
from kit.graph.ontology import Constraint, RelationSemantics, TypeDef, parse, serialize

KIT = Path(__file__).resolve().parents[1] / 'kit'
FIXTURE = Path(__file__).resolve().parent / 'fixtures' / 'semantica'
sys.path.insert(0, str(KIT / 'graph'))
import domande  # noqa: E402
import recall  # noqa: E402
import semantica  # noqa: E402
import sintesi  # noqa: E402
from graph_db import connect_graph  # noqa: E402

TIPI = ('## Tipi ammessi\n| Tipo | Descrizione | Sottotipo di |\n| --- | --- | --- |\n'
        '| `sistema` | Strumenti | |\n| `servizio` | Servizi web | sistema |\n| `portale` | Portali | servizio |\n'
        '| `persona` | Persone | |\n| `processo` | Attività | |\n| `fonte` | Fonti | |\n')
RELAZIONI = ('## Relazioni tipizzate\n| Relazione | Da (tipo) | A (tipo) | Significato | Esempio |\n'
             '| --- | --- | --- | --- | --- |\n'
             '| `usa` | processo | sistema | X funziona tramite Y | Rilascio → Console |\n'
             '| `richiede` | processo, sistema | qualsiasi | X non parte senza Y | Console → Incident |\n'
             '| `parte_di` | qualsiasi | sistema | X è parte di Y | Modulo → Gestionale |\n'
             '| `referente` | qualsiasi | persona | Y è la persona di X | Incident → Anna |\n'
             '| `precede` | processo, sistema | processo, sistema | X viene prima di Y | A → B |\n'
             '| `causa` | qualsiasi | qualsiasi | X causa Y | Guasto → Ritardo |\n'
             '| `variante_di` | qualsiasi | stesso tipo | X è gemello di Y | B → A |\n')
FONTI = '## Chiavi delle fonti\n| `nota-utente` | Precisazione |\n'
SEMANTICA = ('## Semantica delle relazioni\n| Relazione | Ruolo | Inversa | Proprietà |\n| --- | --- | --- | --- |\n'
             '| `usa` | dipendenza | è usato da | |\n| `richiede` | dipendenza | è richiesto da | transitiva |\n'
             '| `precede` | sequenza | segue | transitiva |\n| `variante_di` | | | simmetrica |\n')
VINCOLI = ('## Vincoli\n| Tipo | Relazione o attributo | Minimo | Massimo | Se manca |\n| --- | --- | --- | --- | --- |\n'
           '| `sistema` | `referente` | 1 | | domanda |\n| `processo` | `usa` | 1 | 2 | domanda |\n')
SOLO_USA = VINCOLI.replace('| `sistema` | `referente` | 1 | | domanda |\n', '')
BASE = '# Schema\n' + TIPI + RELAZIONI + FONTI
SCHEMA = BASE + SEMANTICA + VINCOLI


def pagina(tipo, **relazioni):
    """Frontmatter di una pagina; una relazione può avere un solo bersaglio o una lista."""
    righe = ''
    for nome, valore in relazioni.items():
        bersagli = valore if isinstance(valore, list) else [valore]
        righe += '%s: [%s]\n' % (nome, ', '.join('"[[%s]]"' % b for b in bersagli))
    return '---\ntipo: %s\n%s---\ntesto\n' % (tipo, righe)


def documenti(schema=SCHEMA, **pagine):
    return {'Wiki reference.md': schema, **{'wiki/%s.md' % nome: testo for nome, testo in pagine.items()}}


def codici(schema):
    return {i.code for i in parse(schema).issues if i.severity == 'error'}


def crea_vault(test, schema, **pagine):
    """Un vault con le pagine e il grafo costruito; (cartella, connessione al grafo)."""
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
    def test_semantica_e_vincoli(self):
        document = parse(SCHEMA)
        self.assertEqual([i for i in document.issues if i.severity == 'error'], [])
        self.assertEqual(document.semantics[0], RelationSemantics('usa', 'dipendenza', 'è usato da', ()))
        self.assertEqual(document.semantics[1].properties, ('transitiva',))
        self.assertEqual(document.semantics[3], RelationSemantics('variante_di', '', '', ('simmetrica',)))
        self.assertEqual(document.constraints[0], Constraint('sistema', 'referente', 1, None, 'domanda'))
        self.assertEqual(document.constraints[1], Constraint('processo', 'usa', 1, 2, 'domanda'))
        self.assertTrue(document.editable)
        self.assertEqual(set(document.source_spans), {'types', 'relations', 'semantics', 'constraints'})

    def test_senza_sezioni_restano_none(self):
        document = parse(BASE)
        self.assertIsNone(document.semantics)
        self.assertIsNone(document.constraints)
        self.assertEqual(document.capabilities, ())

    def test_roundtrip_e_sezioni_conservate_byte_per_byte(self):
        document = parse(SCHEMA)
        self.assertEqual(serialize(document), SCHEMA.encode())
        candidate = serialize(document, types=document.types + (TypeDef('entita', 'Altro'),))
        self.assertIn(SEMANTICA.encode(), candidate)
        self.assertIn(VINCOLI.encode(), candidate)
        self.assertNotIn(b'| `usa` | dipendenza', document.opaque_bytes())

    def test_funzionalita_attivate(self):
        self.assertEqual(parse(SCHEMA).capabilities, ('role_chains', 'inverse_labels', 'transitive_views',
                                                      'symmetric_views', 'cardinality_questions'))
        solo_inverse = BASE + SEMANTICA.replace('dipendenza', '').replace('sequenza', '').replace('transitiva', '') \
            .replace('simmetrica', '')
        self.assertEqual(parse(solo_inverse).capabilities, ('inverse_labels',))

    def test_errori(self):
        casi = {
            'unknown_relation': SCHEMA.replace('| `precede` | sequenza', '| `inventata` | sequenza'),
            'invalid_role': SCHEMA.replace('| dipendenza | è usato da', '| padrone | è usato da'),
            'invalid_property': SCHEMA.replace('| transitiva |', '| ricorsiva |'),
            'duplicate_semantics': SCHEMA.replace('| `precede` | sequenza', '| `usa` | sequenza'),
            'symmetric_with_inverse': SCHEMA.replace('| `variante_di` | | | simmetrica |',
                                                     '| `variante_di` | | gemello di | simmetrica |'),
            'invalid_cardinality': SCHEMA.replace('| 1 | 2 |', '| 3 | 2 |'),
            'invalid_if_missing': SCHEMA.replace('| 1 | 2 | domanda |', '| 1 | 2 | forse |'),
            'duplicate_cardinality': SCHEMA.replace('| `sistema` | `referente`', '| `processo` | `usa`'),
            'unknown_type': SCHEMA.replace('| `sistema` | `referente`', '| `stranio` | `referente`'),
            'unrecognized_table': SCHEMA.replace('| Relazione | Ruolo | Inversa | Proprietà |',
                                                 '| Relazione | Ruolo | Contrario | Proprietà |'),
        }
        for codice, schema in casi.items():
            with self.subTest(codice):
                self.assertIn(codice, codici(schema))

    def test_relazione_dei_vincoli_sconosciuta(self):
        self.assertIn('unknown_relation', codici(SCHEMA.replace('| `processo` | `usa` |', '| `processo` | `inventata` |')))

    def test_massimo_vuoto_e_minimo_vuoto(self):
        document = parse(SCHEMA.replace('| 1 | 2 | domanda |', '| | | nulla |'))
        self.assertEqual(document.constraints[1], Constraint('processo', 'usa', 0, None, 'nulla'))


class Preview(unittest.TestCase):
    def patch(self, *operazioni):
        candidate, renames, _ = ontology_preview._patch(parse(SCHEMA), list(operazioni), [])
        return parse(candidate), renames

    def test_aggiungere_un_tipo_conserva_le_sezioni(self):
        after, _ = self.patch({'op': 'add_type', 'name': 'app', 'value': {'description': 'App', 'parent': 'servizio'}})
        self.assertEqual(after.semantics, parse(SCHEMA).semantics)
        self.assertEqual(after.constraints, parse(SCHEMA).constraints)

    def test_rinominare_o_togliere_una_relazione_dichiarata_e_rifiutato(self):
        for operazione in ({'op': 'rename_relation', 'name': 'usa', 'to': 'impiega'},
                           {'op': 'remove_relation', 'name': 'usa'}):
            with self.subTest(operazione['op']):
                with self.assertRaises(ContractError) as errore:
                    self.patch(operazione)
                self.assertIn('unknown_relation', {d['code'] for d in errore.exception.details})

    def test_rinominare_un_tipo_dei_vincoli_e_rifiutato(self):
        with self.assertRaises(ContractError) as errore:
            self.patch({'op': 'rename_type', 'name': 'processo', 'to': 'attivita'})
        self.assertIn('unknown_type', {d['code'] for d in errore.exception.details})


class Tabelle(unittest.TestCase):
    def costruisci(self, schema, **pagine):
        cartella = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, cartella, True)
        parsed = build_graph.parse_documents(documenti(schema, **pagine))
        self.assertEqual(parsed['problemi'], ())
        db = sqlite3.connect(build_graph.build_candidate(parsed, cartella / 'graph.sqlite'))
        self.addCleanup(db.close)
        return db

    def test_onto_relazioni_e_cardinalita(self):
        db = self.costruisci(SCHEMA)
        righe = db.execute('SELECT nome, ruolo, inversa, transitiva, simmetrica FROM onto_relazioni ORDER BY posizione').fetchall()
        self.assertEqual(righe, [('usa', 'dipendenza', 'è usato da', 0, 0), ('richiede', 'dipendenza', 'è richiesto da', 1, 0),
                                 ('parte_di', None, None, 0, 0), ('referente', None, None, 0, 0),
                                 ('precede', 'sequenza', 'segue', 1, 0), ('causa', None, None, 0, 0),
                                 ('variante_di', None, None, 0, 1)])
        self.assertEqual(db.execute('SELECT tipo, relazione, minimo, massimo, se_manca FROM onto_cardinalita '
                                    'ORDER BY posizione').fetchall(),
                         [('sistema', 'referente', 1, None, 'domanda'), ('processo', 'usa', 1, 2, 'domanda')])
        metadati = dict(db.execute('SELECT chiave, valore FROM onto_metadata'))
        self.assertEqual((metadati['semantica'], metadati['vincoli']), ('presente', 'presente'))

    def test_senza_sezioni_nulla_di_dichiarato(self):
        db = self.costruisci(BASE)
        self.assertEqual(db.execute('SELECT count(*) FROM onto_relazioni WHERE ruolo IS NOT NULL OR inversa IS NOT NULL '
                                    'OR transitiva OR simmetrica').fetchone(), (0,))
        self.assertEqual(db.execute('SELECT count(*) FROM onto_cardinalita').fetchone(), (0,))
        metadati = dict(db.execute('SELECT chiave, valore FROM onto_metadata'))
        self.assertEqual((metadati['semantica'], metadati['vincoli']), ('assente', 'assente'))
        self.assertEqual(db.execute('SELECT count(*) FROM relazioni_dedotte').fetchone(), (0,))

    def test_vista_delle_relazioni_dedotte(self):
        db = self.costruisci(SCHEMA,
                             A=pagina('sistema', richiede='B'), B=pagina('sistema', richiede='C'),
                             C=pagina('sistema', richiede='D'), D=pagina('sistema'),
                             E=pagina('sistema', richiede='F'), F=pagina('sistema', richiede='E'),
                             X=pagina('sistema', variante_di='Y'), Y=pagina('sistema'))
        dedotte = db.execute('SELECT source_id, target_id, type, origine FROM relazioni_dedotte ORDER BY 1, 2').fetchall()
        self.assertEqual(dedotte, [('A', 'C', 'richiede', 'dedotto'), ('A', 'D', 'richiede', 'dedotto'),
                                   ('B', 'D', 'richiede', 'dedotto'), ('Y', 'X', 'variante_di', 'dedotto')])
        esplicite = {(s, t) for s, t, tipo in db.execute('SELECT source_id, target_id, type FROM relations')}
        self.assertFalse({(s, t) for s, t, _, _ in dedotte} & esplicite)  # mai ciò che la pagina già dichiara

    def test_dedotte_non_sono_scritte_nelle_relazioni(self):
        db = self.costruisci(SCHEMA, A=pagina('sistema', richiede='B'), B=pagina('sistema', richiede='C'),
                             C=pagina('sistema'))
        self.assertEqual(db.execute("SELECT count(*) FROM relations WHERE source_id = 'A' AND target_id = 'C'").fetchone(), (0,))


class Ruoli(unittest.TestCase):
    def test_default_senza_sezione(self):
        _, db = crea_vault(self, BASE)
        self.assertEqual(semantica.ruoli(db)['usa'], 'dipendenza')
        self.assertEqual(semantica.relazioni_con_ruolo(db, 'dipendenza', 'responsabile'), ('usa', 'richiede', 'referente'))
        self.assertEqual(semantica.relazioni_con_ruolo(db, 'composizione'), ('parte_di',))
        self.assertEqual(semantica.relazioni_con_ruolo(db, 'causale'), ('causa',))
        self.assertEqual(semantica.inverse(db), {})
        self.assertFalse(semantica.dichiarata(db))

    def test_il_dichiarato_sovrascrive_solo_le_relazioni_indicate(self):
        _, db = crea_vault(self, SCHEMA.replace('| `precede` | sequenza |', '| `precede` | dipendenza |'))
        self.assertEqual(semantica.relazioni_con_ruolo(db, 'dipendenza', 'responsabile'),
                         ('usa', 'richiede', 'precede', 'referente'))
        self.assertEqual(semantica.relazioni_con_ruolo(db, 'causale'), ('causa',))  # la sezione non la nomina: resta il default
        self.assertEqual(semantica.inverse(db), {'usa': 'è usato da', 'richiede': 'è richiesto da', 'precede': 'segue'})
        self.assertTrue(semantica.dichiarata(db))

    def test_generazione_senza_le_colonne_usa_i_default(self):
        db = sqlite3.connect(':memory:')
        self.addCleanup(db.close)
        db.executescript("CREATE TABLE onto_relazioni (nome TEXT, significato TEXT);"
                         "CREATE TABLE onto_metadata (chiave TEXT, valore TEXT);")
        self.assertEqual(semantica.relazioni_con_ruolo(db, 'composizione'), ('parte_di',))
        self.assertFalse(semantica.dichiarata(db))
        self.assertIsNone(semantica.vincoli(db))

    def test_catene_di_sintesi_dai_ruoli(self):
        pagine = dict(A=pagina('processo', precede='B'), B=pagina('sistema', precede='C'), C=pagina('sistema'))
        _, db = crea_vault(self, BASE, **pagine)
        self.assertEqual(list(sintesi.catene(db)), [])  # precede non è una dipendenza: come oggi
        _, db = crea_vault(self, SCHEMA.replace('| `precede` | sequenza |', '| `precede` | dipendenza |')
                           .replace(VINCOLI, ''), **pagine)
        catene = list(sintesi.catene(db))
        self.assertEqual([c['partenza'] for c in catene], ['A'])
        self.assertEqual(catene[0]['pagine'], ['A', 'B', 'C'])


def esegui_script(vault, *argv):
    ambiente = {**os.environ, 'PYTHONIOENCODING': 'utf-8'}
    esito = subprocess.run([sys.executable, '.graph/' + argv[0], *argv[1:]], cwd=vault, env=ambiente,
                           capture_output=True, timeout=120)
    if esito.returncode:
        raise AssertionError(esito.stderr.decode('utf-8', 'replace'))
    return json.loads(esito.stdout.decode('utf-8'))


class IdenticoAlDefault(unittest.TestCase):
    """Soglia della fase 2: senza le sezioni, o con sezioni che dichiarano ciò che il codice già fa, nulla cambia."""

    def vault(self, extra=''):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        vault = Path(temp.name)
        shutil.copytree(KIT / 'esempio/wiki', vault / 'wiki')
        shutil.copytree(KIT / 'esempio/raw', vault / 'raw')
        shutil.copytree(KIT / 'graph', vault / '.graph', ignore=shutil.ignore_patterns('__pycache__', '*.sqlite'))
        for nome in ('index.md', 'log.md'):
            shutil.copy(KIT / 'vault' / nome, vault / nome)
        schema = (KIT / 'vault/Wiki reference.md').read_text(encoding='utf-8')
        (vault / 'Wiki reference.md').write_text(schema.rstrip('\n') + '\n\n' + extra, encoding='utf-8')
        subprocess.run([sys.executable, '.graph/build_graph.py'], cwd=vault, check=True, capture_output=True)
        return vault

    def uscite(self, vault):
        dati = {'domande': esegui_script(vault, 'domande.py', '--json'),
                'domande-strutturali': esegui_script(vault, 'domande.py', '--json', '--strutturali'),
                'sintesi': esegui_script(vault, 'sintesi.py', '--tutte', '--json')}
        for voci in dati.values():
            for voce in voci:
                voce.pop('prima_vista', None)
        return dati

    def confronta(self, uscite):
        for nome in ('domande', 'domande-strutturali', 'sintesi'):
            with self.subTest(nome):
                attesa = json.loads((FIXTURE / f'{nome}-default.json').read_text(encoding='utf-8'))
                self.assertEqual(json.loads(json.dumps(uscite[nome], sort_keys=True)), attesa)

    def test_senza_sezioni(self):
        self.confronta(self.uscite(self.vault()))

    def test_con_sole_inverse_e_proprieta(self):
        extra = ('## Semantica delle relazioni\n| Relazione | Ruolo | Inversa | Proprietà |\n| --- | --- | --- | --- |\n'
                 '| `usa` | | è usato da | |\n| `richiede` | | è richiesto da | transitiva |\n')
        self.confronta(self.uscite(self.vault(extra)))

    def test_con_ruoli_e_vincolo_uguali_ai_default(self):
        extra = ('## Semantica delle relazioni\n| Relazione | Ruolo | Inversa | Proprietà |\n| --- | --- | --- | --- |\n'
                 '| `usa` | dipendenza | | |\n| `richiede` | dipendenza | | |\n| `referente` | responsabile | | |\n'
                 '| `parte_di` | composizione | | |\n| `causa` | causale | | |\n\n'
                 '## Vincoli\n| Tipo | Relazione o attributo | Minimo | Massimo | Se manca |\n| --- | --- | --- | --- | --- |\n'
                 '| `sistema` | `referente` | 1 | | domanda |\n| `processo` | `referente` | 1 | | domanda |\n'
                 '| `progetto` | `referente` | 1 | | domanda |\n')
        self.confronta(self.uscite(self.vault(extra)))


class Vincoli(unittest.TestCase):
    def rileva(self, schema, **pagine):
        vault, db = crea_vault(self, schema, **pagine)
        originale = domande.apri
        with mock.patch.object(domande, 'apri', lambda path=':memory:': originale(':memory:')):
            return domande.rileva(db, vault)

    def test_default_senza_sezione(self):
        risultato = self.rileva(BASE, A=pagina('sistema'), B=pagina('sistema', referente='Anna'),
                                Anna=pagina('persona'), C=pagina('sistema', parte_di='A'))
        self.assertEqual(risultato['A'], [('referente', 'Chi è il referente di [[A]]? '
                                           '(nessuna relazione `referente` nel frontmatter)', 'referente|A|')])
        self.assertEqual(set(risultato), {'A'})

    def test_il_referente_dichiarato_ha_lo_stesso_segnale_e_la_stessa_chiave(self):
        risultato = self.rileva(BASE + VINCOLI.split('| `processo`')[0], A=pagina('sistema'))
        self.assertEqual([(s, k) for s, _, k in risultato['A']], [('referente', 'referente|A|')])

    def test_la_sezione_sostituisce_il_default(self):
        risultato = self.rileva(BASE + SOLO_USA, A=pagina('sistema'), P=pagina('processo'),
                                Q=pagina('processo', usa='A'))
        self.assertNotIn('A', risultato)  # nessun vincolo sul referente dei sistemi
        self.assertNotIn('Q', risultato)
        self.assertEqual([(s, k) for s, _, k in risultato['P']], [('vincolo', 'vincolo|P|usa min')])

    def test_minimo_e_massimo(self):
        sistemi = {f'S{i}': pagina('sistema') for i in range(3)}
        risultato = self.rileva(BASE + SOLO_USA, P=pagina('processo'), Q=pagina('processo', usa=['S0']),
                                R=pagina('processo', usa=['S0', 'S1', 'S2']), **sistemi)
        self.assertNotIn('Q', risultato)
        self.assertIn('almeno 1', risultato['P'][0][1])
        self.assertEqual([(s, k) for s, _, k in risultato['R']], [('vincolo', 'vincolo|R|usa max')])
        self.assertIn('al più 2', risultato['R'][0][1])

    def test_se_manca_nulla_non_fa_domande(self):
        schema = BASE + SOLO_USA.replace('| 1 | 2 | domanda |', '| 1 | 2 | nulla |')
        self.assertEqual(self.rileva(schema, P=pagina('processo')), {})

    def test_un_sottotipo_eredita_il_vincolo(self):
        risultato = self.rileva(BASE + VINCOLI, P1=pagina('portale'))
        self.assertEqual([(s, k) for s, _, k in risultato['P1']], [('referente', 'referente|P1|')])

    def test_un_vincolo_nuovo_ha_il_segnale_vincolo_dopo_il_referente(self):
        self.assertEqual(domande.ORDINE.index('vincolo'), domande.ORDINE.index('referente') + 1)

    def test_il_vincolo_si_legge_dalla_tabella(self):
        _, db = crea_vault(self, SCHEMA)
        self.assertEqual(semantica.vincoli(db), [
            {'tipo': 'sistema', 'relazione': 'referente', 'minimo': 1, 'massimo': None, 'se_manca': 'domanda'},
            {'tipo': 'processo', 'relazione': 'usa', 'minimo': 1, 'massimo': 2, 'se_manca': 'domanda'}])
        _, db = crea_vault(self, BASE)
        self.assertIsNone(semantica.vincoli(db))


class Recall(unittest.TestCase):
    def contesto(self, schema):
        _, db = crea_vault(self, schema, Rilascio=pagina('processo', usa='Console'), Console=pagina('sistema'))
        semi, fatti, omessi = recall.richiama(db, 'Rilascio')
        info = {id_: (tipo, descr) for id_, tipo, descr in db.execute('SELECT id, tipo, descrizione FROM entities')}
        return db, semi, fatti, info, omessi

    def test_blocco_di_schema_solo_con_la_semantica_dichiarata(self):
        db, semi, fatti, info, omessi = self.contesto(SCHEMA)
        senza = recall.formatta(semi, fatti, info, omessi)
        con = recall.formatta(semi, fatti, info, omessi, db=db)
        self.assertNotIn('Schema pertinente', senza)
        self.assertTrue(con.startswith(senza))
        self.assertIn('Schema pertinente', con)
        self.assertIn('- usa (dipendenza; inversa: è usato da): X funziona tramite Y', con)
        self.assertNotIn('richiede', con.split('Schema pertinente')[1])  # solo le relazioni presenti nei fatti

    def test_senza_la_sezione_il_contesto_non_cambia(self):
        db, semi, fatti, info, omessi = self.contesto(BASE)
        self.assertEqual(recall.formatta(semi, fatti, info, omessi, db=db), recall.formatta(semi, fatti, info, omessi))

    def test_tetto_e_interruttore(self):
        db, semi, fatti, info, omessi = self.contesto(SCHEMA)
        self.assertEqual(semantica.schema_pertinente(db, fatti, massimo=5), '')
        with mock.patch.dict(os.environ, {'GRAFO_SENZA_SCHEMA': '1'}):
            self.assertNotIn('Schema pertinente', recall.formatta(semi, fatti, info, omessi, db=db))


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
        for nome, testo in {'Console': pagina('sistema'), 'Rilascio': pagina('processo', usa='Console')}.items():
            (self.root / 'wiki' / (nome + '.md')).write_text(testo, encoding='utf-8')
        self.reference = rebuild(self.root)

    def test_ontology_espone_semantica_e_vincoli(self):
        status, _, body = self.get('ontology')
        self.assertEqual(status, 200, body)
        self.assertEqual(body['semantics'][0], {'name': 'usa', 'role': 'dipendenza', 'inverse': 'è usato da',
                                                'properties': []})
        self.assertEqual(body['constraints'][1], {'type': 'processo', 'relation': 'usa', 'minimum': 1, 'maximum': 2,
                                                  'if_missing': 'domanda'})

    def test_causal_segue_il_ruolo_causale(self):
        schema = SCHEMA.replace('| `variante_di` | | | simmetrica |',
                                '| `variante_di` | | | simmetrica |\n| `precede` | causale | | |').replace(
            '| `precede` | sequenza | segue | transitiva |\n', '')
        (self.root / 'Wiki reference.md').write_text(schema, encoding='utf-8')
        (self.root / 'wiki' / 'Guasto.md').write_text(pagina('sistema', causa='Console', precede='Console'), encoding='utf-8')
        rebuild(self.root)
        status, _, body = self.get('causal', {'node': 'Guasto', 'depth': '1'})
        self.assertEqual(status, 200, body)
        self.assertEqual(sorted(e['type'] for e in body['edges']), ['causa', 'precede'])


if __name__ == '__main__':
    unittest.main()
