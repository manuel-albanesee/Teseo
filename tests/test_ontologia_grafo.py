"""Fase A di doc/16: l'ontologia di Wiki reference copiata nel grafo (tabelle onto_*), interrogabile con i dati."""
import _shortpath  # noqa: F401
import shutil
import sqlite3
import tempfile
import unittest
from pathlib import Path

import test_dashboard_queries as fixture
from kit.dashboard.contracts import canonical_json, content_hash, file_hash
from kit.dashboard.graph_service import BUILDER_VERSION, rebuild
from kit.graph import build_graph
from kit.graph.ontology import parse

TIPI = ('## Tipi ammessi\n| Tipo | Descrizione |\n| --- | --- |\n'
        '| `sistema` | Strumenti |\n| `persona` | Persone |\n| `processo` | Attività |\n| `fonte` | Fonti |\n')
RELAZIONI = ('## Relazioni tipizzate\n| Relazione | Da (tipo) | A (tipo) | Significato | Esempio |\n'
             '| --- | --- | --- | --- | --- |\n'
             '| `usa` | processo, sistema | sistema | X funziona tramite Y | Rilascio → Console |\n'
             '| `referente` | qualsiasi | persona | Y è il riferimento per X | Console → Anna |\n'
             '| `variante_di` | qualsiasi | stesso tipo | X è un gemello di Y | B → A |\n')
FONTI = '## Chiavi delle fonti\n| `nota-utente` | Precisazione |\n'


def pagine(schema):
    return {'Wiki reference.md': schema,
            'wiki/Rilascio.md': '---\ntipo: processo\nfonti: [nota-utente]\nusa: "[[Console]]"\n---\n[[Anna]]',
            'wiki/Console.md': '---\ntipo: sistema\nreferente: "[[Anna]]"\n---\ntesto',
            'wiki/Anna.md': '---\ntipo: persona\n---\ntesto'}


def costruisci(documenti):
    """Il grafo candidato dei documenti, in una cartella temporanea: (connessione, cartella)."""
    cartella = Path(tempfile.mkdtemp())
    snapshot = build_graph.parse_documents(documenti)
    db = sqlite3.connect(build_graph.build_candidate(snapshot, cartella / 'graph.sqlite'))
    return db, cartella


class Tabelle(unittest.TestCase):
    def grafo(self, documenti):
        db, cartella = costruisci(documenti)
        self.addCleanup(shutil.rmtree, cartella, True)
        self.addCleanup(db.close)
        return db

    def test_catalogo_dichiarato_relazioni_vincoli_e_metadati(self):
        schema = '# Schema\n' + TIPI + RELAZIONI + FONTI
        db = self.grafo(pagine(schema))
        self.assertEqual(db.execute('SELECT nome, descrizione, dichiarato FROM onto_tipi ORDER BY posizione').fetchall(),
                         [('sistema', 'Strumenti', 1), ('persona', 'Persone', 1), ('processo', 'Attività', 1),
                          ('fonte', 'Fonti', 1)])
        self.assertEqual(db.execute('SELECT nome, significato, esempio, verso FROM onto_relazioni ORDER BY posizione').fetchall(),
                         [('usa', 'X funziona tramite Y', 'Rilascio → Console', 'source_to_target'),
                          ('referente', 'Y è il riferimento per X', 'Console → Anna', 'source_to_target'),
                          ('variante_di', 'X è un gemello di Y', 'B → A', 'source_to_target')])
        self.assertEqual(db.execute("SELECT lato, tipo FROM onto_vincoli WHERE relazione = 'usa' "
                                    "ORDER BY lato DESC, posizione").fetchall(),
                         [('da', 'processo'), ('da', 'sistema'), ('a', 'sistema')])
        self.assertEqual(db.execute("SELECT lato, tipo FROM onto_vincoli WHERE relazione = 'variante_di' "
                                    "ORDER BY lato DESC").fetchall(), [('da', 'qualsiasi'), ('a', 'stesso tipo')])
        self.assertEqual(dict(db.execute('SELECT chiave, valore FROM onto_metadata')),
                         {'formato': '1', 'schema_digest': parse(schema).digest, 'tipi': 'dichiarati',
                          'vocabolario': 'presente'})

    def test_senza_catalogo_i_tipi_sono_osservati_e_quelli_dei_vincoli(self):
        db = self.grafo(pagine(RELAZIONI + FONTI))
        self.assertEqual(db.execute('SELECT nome, descrizione, dichiarato FROM onto_tipi ORDER BY posizione').fetchall(),
                         [(nome, '', 0) for nome in ('fonte', 'persona', 'processo', 'sistema')])
        self.assertEqual(dict(db.execute('SELECT chiave, valore FROM onto_metadata'))['tipi'], 'osservati')

    def test_senza_schema_niente_vocabolario_ma_le_tabelle_ci_sono(self):
        documenti = pagine('')
        del documenti['Wiki reference.md']
        documenti['wiki/Rilascio.md'] = '---\ntipo: processo\n---\n[[Anna]]'
        documenti['wiki/Console.md'] = '---\ntipo: sistema\n---\ntesto'
        db = self.grafo(documenti)
        self.assertEqual(db.execute('SELECT count(*) FROM onto_relazioni').fetchone(), (0,))
        self.assertEqual(db.execute('SELECT count(*) FROM onto_vincoli').fetchone(), (0,))
        self.assertEqual([n for (n,) in db.execute('SELECT nome FROM onto_tipi ORDER BY posizione')],
                         ['persona', 'processo', 'sistema'])
        self.assertEqual(dict(db.execute('SELECT chiave, valore FROM onto_metadata')),
                         {'formato': '1', 'schema_digest': '', 'tipi': 'osservati', 'vocabolario': 'assente'})

    def test_archi_derivati_non_sono_relazioni_dell_ontologia(self):
        db = self.grafo(pagine(TIPI + RELAZIONI + FONTI))
        self.assertEqual(db.execute("SELECT count(*) FROM onto_relazioni WHERE nome IN ('menziona', 'documentato_in')")
                         .fetchone(), (0,))

    def test_una_query_su_ontologia_e_dati_insieme(self):
        db = self.grafo(pagine(TIPI + RELAZIONI + FONTI))
        righe = db.execute(
            "SELECT r.source_id, r.type, r.target_id, o.significato, group_concat(v.tipo, ', ') "
            "FROM relations r JOIN onto_relazioni o ON o.nome = r.type "
            "LEFT JOIN onto_vincoli v ON v.relazione = r.type AND v.lato = 'a' "
            "GROUP BY r.source_id, r.type, r.target_id ORDER BY r.source_id").fetchall()
        self.assertEqual(righe, [('Console', 'referente', 'Anna', 'Y è il riferimento per X', 'persona'),
                                 ('Rilascio', 'usa', 'Console', 'X funziona tramite Y', 'sistema')])

    def test_grafo_invalido_non_arriva_alle_tabelle(self):
        schema = TIPI + RELAZIONI.replace('| `variante_di`', '| `usa` | sistema | sistema | doppia | x |\n| `variante_di`')
        with self.assertRaises(build_graph.GraphValidationError):
            costruisci(pagine(schema + FONTI))


class Generazioni(unittest.TestCase):
    stop = fixture.Queries.stop
    request = fixture.Queries.request
    manifest = fixture.Queries.manifest
    hashes = fixture.Queries.hashes
    attach = fixture.Queries.attach
    get = fixture.Queries.get
    setUp = fixture.Queries.setUp

    def test_la_generazione_ha_le_tabelle_e_la_nuova_versione(self):
        self.assertEqual(BUILDER_VERSION, 5)
        db = sqlite3.connect(self.reference.path)
        try:
            self.assertEqual(dict(db.execute('SELECT key, value FROM graph_metadata'))['builder_version'], '5')
            self.assertEqual([n for (n,) in db.execute('SELECT nome FROM onto_relazioni')], ['usa'])
        finally:
            db.close()

    def generazione_v4_senza_tabelle(self):
        """Copia della generazione corrente come se l'avesse scritta il builder 4, senza le tabelle onto_*."""
        digest = self.reference.content_revision
        generation = content_hash({'content_revision': digest, 'builder_version': 4, 'copia': 'senza onto_*'})
        old = self.reference.path.with_name(generation + '.sqlite')
        shutil.copyfile(self.reference.path, old)
        db = sqlite3.connect(old)
        try:
            for tabella in ('onto_tipi', 'onto_relazioni', 'onto_vincoli', 'onto_metadata'):
                db.execute('DROP TABLE ' + tabella)
            db.executemany('UPDATE graph_metadata SET value=? WHERE key=?',
                           [('4', 'builder_version'), (generation, 'generation')])
            db.commit()
        finally:
            db.close()
        return generation, old

    def test_ontology_uguale_con_e_senza_tabelle(self):
        for catalogo in (False, True):
            with self.subTest(catalogo=catalogo):
                if catalogo:  # Anna Rossi (persona) usa Bruno (persona) non è ammesso da RELAZIONI: diventa referente
                    (self.root / 'Wiki reference.md').write_text(TIPI + RELAZIONI + FONTI, encoding='utf-8')
                    self.page.write_text(self.page.read_text(encoding='utf-8').replace('usa:', 'referente:'),
                                         encoding='utf-8')
                    self.reference = rebuild(self.root)
                status, _, nuova = self.get('ontology')
                self.assertEqual(status, 200, nuova)
                generation, old = self.generazione_v4_senza_tabelle()
                self.manifest_su(generation, old)
                status, _, vecchia = self.get('ontology', {'generation': generation})
                self.assertEqual(status, 200, vecchia)
                for campo in ('types', 'types_source', 'relations', 'schema_digest', 'editable'):
                    self.assertEqual(nuova[campo], vecchia[campo], campo)

    def manifest_su(self, generation, path):
        marker = self.root / '.teseo/local/graph-current.json'
        marker.write_bytes(canonical_json({'format_version': 1, 'content_revision': self.reference.content_revision,
                                           'generation': generation, 'sqlite_sha256': file_hash(path)}))


if __name__ == '__main__':
    unittest.main()
