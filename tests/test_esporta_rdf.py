"""Fase 5 di doc/17: export Turtle dello schema (`esporta_rdf.py`), deterministico e di sola lettura."""
import _shortpath  # noqa: F401
from contextlib import redirect_stdout
import io
from pathlib import Path
import re
import shutil
import sqlite3
import sys
import tempfile
import unittest

from kit.graph import build_graph

KIT = Path(__file__).resolve().parents[1] / 'kit'
FIXTURE = Path(__file__).resolve().parent / 'fixtures' / 'rdf' / 'schema.ttl'
sys.path.insert(0, str(KIT / 'graph'))
import esporta_rdf  # noqa: E402

BASE = 'https://example.org/teseo/'
SCHEMA = '''# Schema

## Tipi ammessi
| Tipo | Descrizione | Sottotipo di |
| --- | --- | --- |
| `sistema` | Strumenti | |
| `servizio` | Servizi web | sistema |
| `processo` | Attività | |
| `persona` | Persone | |
| `fonte` | Fonti | |

## Relazioni tipizzate
| Relazione | Da (tipo) | A (tipo) | Significato | Esempio |
| --- | --- | --- | --- | --- |
| `usa` | processo | sistema | X funziona tramite Y | A → B |
| `richiede` | processo, sistema | qualsiasi | X non parte senza Y | A → B |
| `variante_di` | qualsiasi | stesso tipo | X è gemello di Y | B → A |
| `referente` | qualsiasi | persona | Y è la persona di X | A → B |

## Categorie
| Categoria | Più ampia | Descrizione |
| --- | --- | --- |
| amministrazione | | Processi amministrativi |
| fatturazione | amministrazione | Fatture |
| rischio | | Livello di rischio |

## Semantica delle relazioni
| Relazione | Ruolo | Inversa | Proprietà |
| --- | --- | --- | --- |
| `usa` | dipendenza | è usato da | |
| `richiede` | dipendenza | è richiesto da | transitiva |
| `variante_di` | | | simmetrica |

## Sinonimi
| Nome | Sinonimi |
| --- | --- |
| `fatturazione` | billing; contabilità clienti |
| `servizio` | SPV |

## Corrispondenze
| Nome | Corrispondenza | Vocabolario | Esattezza |
| --- | --- | --- | --- |
| `servizio` | fibo-fnd:Service | fibo | esatta |
| `fatturazione` | https://example.org/Invoicing | fibo | vicina |

## Attributi
| Attributo | Di (tipo) | Valore | Descrizione |
| --- | --- | --- | --- |
| `data_liquidazione_prevista` | processo | data | Quando si liquida |
| `importo_previsto` | processo | importo | Importo atteso |
| `utenti` | sistema | numero | Utenti attivi |
| `critico` | servizio | sì/no | Da presidiare |
| `livello` | sistema | categoria:rischio | Rischio |
| `nota` | sistema | testo | Appunto |
| `nota` | processo | testo | Appunto |

## Chiavi delle fonti
| `nota-utente` | Precisazione |
| `fibo` | Vocabolario FIBO |
'''


def costruisci(test, schema=SCHEMA):
    cartella = Path(tempfile.mkdtemp())
    test.addCleanup(shutil.rmtree, cartella, True)
    parsed = build_graph.parse_documents({'Wiki reference.md': schema})
    test.assertEqual(parsed['problemi'], ())
    candidato = Path(build_graph.build_candidate(parsed, cartella / 'graph.sqlite'))
    db = sqlite3.connect(candidato)
    test.addCleanup(db.close)
    return db, candidato


def righe(testo):
    return set(testo.splitlines())


class Contenuto(unittest.TestCase):
    def setUp(self):
        self.db, self.percorso = costruisci(self, SCHEMA)
        self.testo = esporta_rdf.esporta(self.db, BASE)
        self.righe = righe(self.testo)

    def ha(self, soggetto, predicato, oggetto):
        self.assertIn(f'{soggetto} {predicato} {oggetto} .', self.righe)

    def non_ha(self, soggetto, predicato):
        self.assertFalse([r for r in self.righe if r.startswith(f'{soggetto} {predicato} ')], (soggetto, predicato))

    def test_ontologia_e_prefissi(self):
        self.ha(f'<{BASE}>', 'rdf:type', 'owl:Ontology')
        for prefisso in ('owl', 'prov', 'rdf', 'rdfs', 'skos', 'xsd'):
            self.assertTrue(any(r.startswith(f'@prefix {prefisso}: <') for r in self.righe), prefisso)

    def test_tipi(self):
        sistema, servizio = f'<{BASE}tipo/sistema>', f'<{BASE}tipo/servizio>'
        self.ha(sistema, 'rdf:type', 'owl:Class')
        self.ha(sistema, 'rdfs:label', '"sistema"')
        self.ha(sistema, 'rdfs:comment', '"Strumenti"@it')
        self.ha(servizio, 'rdfs:subClassOf', sistema)
        self.non_ha(sistema, 'rdfs:subClassOf')

    def test_categorie(self):
        fatturazione = f'<{BASE}categoria/fatturazione>'
        self.ha(fatturazione, 'rdf:type', 'skos:Concept')
        self.ha(fatturazione, 'skos:prefLabel', '"fatturazione"@it')
        self.ha(fatturazione, 'skos:definition', '"Fatture"@it')
        self.ha(fatturazione, 'skos:broader', f'<{BASE}categoria/amministrazione>')
        self.non_ha(f'<{BASE}categoria/amministrazione>', 'skos:broader')

    def test_relazioni_dominio_e_codominio_solo_se_univoci(self):
        usa = f'<{BASE}relazione/usa>'
        self.ha(usa, 'rdf:type', 'owl:ObjectProperty')
        self.ha(usa, 'rdfs:domain', f'<{BASE}tipo/processo>')
        self.ha(usa, 'rdfs:range', f'<{BASE}tipo/sistema>')
        self.ha(usa, 'rdfs:comment', '"X funziona tramite Y"@it')
        richiede = f'<{BASE}relazione/richiede>'
        self.non_ha(richiede, 'rdfs:domain')  # due tipi
        self.non_ha(richiede, 'rdfs:range')  # qualsiasi
        variante = f'<{BASE}relazione/variante_di>'
        self.non_ha(variante, 'rdfs:domain')
        self.non_ha(variante, 'rdfs:range')  # stesso tipo
        referente = f'<{BASE}relazione/referente>'
        self.non_ha(referente, 'rdfs:domain')
        self.ha(referente, 'rdfs:range', f'<{BASE}tipo/persona>')

    def test_proprieta_transitiva_e_simmetrica_senza_inverse(self):
        self.ha(f'<{BASE}relazione/richiede>', 'rdf:type', 'owl:TransitiveProperty')
        self.ha(f'<{BASE}relazione/variante_di>', 'rdf:type', 'owl:SymmetricProperty')
        self.assertNotIn(f'<{BASE}relazione/usa> rdf:type owl:TransitiveProperty .', self.righe)
        self.assertNotIn('owl:inverseOf', self.testo)  # l'inversa è un nome di lettura, non un IRI (C3)
        self.assertNotIn('è usato da', self.testo)

    def test_attributi(self):
        data = f'<{BASE}attributo/data_liquidazione_prevista>'
        self.ha(data, 'rdf:type', 'owl:DatatypeProperty')
        self.ha(data, 'rdfs:domain', f'<{BASE}tipo/processo>')
        self.ha(data, 'rdfs:range', 'xsd:date')
        self.ha(f'<{BASE}attributo/utenti>', 'rdfs:range', 'xsd:decimal')
        self.ha(f'<{BASE}attributo/critico>', 'rdfs:range', 'xsd:boolean')
        self.ha(f'<{BASE}attributo/importo_previsto>', 'rdfs:range', 'xsd:string')
        self.ha(f'<{BASE}attributo/livello>', 'rdfs:range', 'skos:Concept')
        nota = f'<{BASE}attributo/nota>'  # lo stesso nome su due tipi: nessun dominio
        self.ha(nota, 'rdf:type', 'owl:DatatypeProperty')
        self.non_ha(nota, 'rdfs:domain')

    def test_sinonimi(self):
        fatturazione = f'<{BASE}categoria/fatturazione>'
        self.ha(fatturazione, 'skos:altLabel', '"billing"@it')
        self.ha(fatturazione, 'skos:altLabel', '"contabilità clienti"@it')
        self.ha(f'<{BASE}tipo/servizio>', 'skos:altLabel', '"SPV"@it')

    def test_corrispondenze_e_provenienza(self):
        servizio = f'<{BASE}tipo/servizio>'
        self.ha(servizio, 'skos:exactMatch', '<urn:curie:fibo-fnd:Service>')
        self.ha(servizio, 'prov:wasDerivedFrom', f'<{BASE}fonte/fibo>')
        fatturazione = f'<{BASE}categoria/fatturazione>'
        self.ha(fatturazione, 'skos:closeMatch', '<https://example.org/Invoicing>')
        self.ha(fatturazione, 'prov:wasDerivedFrom', f'<{BASE}fonte/fibo>')

    def test_solo_lo_schema_nessuna_pagina(self):
        self.assertNotIn('/pagina/', self.testo)
        self.assertNotIn('Rilascio', self.testo)


class Forma(unittest.TestCase):
    RIGA = re.compile(
        r'^(?:@prefix [a-z]+: <[^>\s]+> \.'
        r'|<[^>\s]+> [a-z]+:[A-Za-z]+ (?:<[^>\s]+>|[a-z]+:[A-Za-z]+|"(?:[^"\\\n]|\\.)*"(?:@it)?) \.'
        r'|)$')

    def setUp(self):
        self.db, self.percorso = costruisci(self, SCHEMA)
        self.testo = esporta_rdf.esporta(self.db, BASE)

    def test_ogni_riga_e_una_tripla_o_un_prefisso(self):
        for numero, riga in enumerate(self.testo.splitlines(), 1):
            with self.subTest(numero):
                self.assertRegex(riga, self.RIGA)

    def test_ordine_totale_e_nessun_duplicato(self):
        triple = [r for r in self.testo.splitlines() if r.startswith('<')]
        self.assertEqual(triple, sorted(triple))
        self.assertEqual(len(triple), len(set(triple)))

    def test_due_esecuzioni_byte_identiche(self):
        db, _ = costruisci(self, SCHEMA)
        self.assertEqual(esporta_rdf.esporta(db, BASE).encode('utf-8'), self.testo.encode('utf-8'))

    def test_nessuna_data_e_fine_riga_lf(self):
        self.assertNotRegex(self.testo, r'20\d\d-\d\d-\d\d')
        self.assertNotIn('\r', self.testo)
        self.assertTrue(self.testo.endswith('\n'))

    def test_golden_file(self):
        self.assertEqual(FIXTURE.read_text(encoding='utf-8'), self.testo)

    def test_letterale_con_le_fughe(self):
        self.assertEqual(esporta_rdf.letterale('a"b\\c\nd\te\rf\x01'), '"a\\"b\\\\c\\nd\\te\\rf\\u0001"')
        self.assertEqual(esporta_rdf.letterale('ciao', 'it'), '"ciao"@it')

    def test_iri_codificati_in_percentuale(self):
        self.assertEqual(esporta_rdf.iri(BASE, 'tipo', 'città'), f'<{BASE}tipo/citt%C3%A0>')
        self.assertEqual(esporta_rdf.iri(BASE, 'tipo', 'a b'), f'<{BASE}tipo/a%20b>')

    def test_curie_e_iri_assoluti(self):
        self.assertEqual(esporta_rdf.iri_esterno('fibo-fnd:Service'), '<urn:curie:fibo-fnd:Service>')
        self.assertEqual(esporta_rdf.iri_esterno('https://example.org/X'), '<https://example.org/X>')
        self.assertEqual(esporta_rdf.iri_esterno('urn:isbn:123'), '<urn:isbn:123>')


class Robustezza(unittest.TestCase):
    def test_base_non_valida(self):
        db, _ = costruisci(self, SCHEMA)
        for base in ('example.org/', 'ftp://x/', 'https://example.org/senza-chiusura', ''):
            with self.subTest(base):
                with self.assertRaises(ValueError):
                    esporta_rdf.esporta(db, base)
        self.assertTrue(esporta_rdf.esporta(db, 'https://example.org/ns#').startswith('@prefix'))

    def test_senza_le_sezioni_nuove(self):
        schema = SCHEMA[:SCHEMA.index('## Semantica')] + SCHEMA[SCHEMA.index('## Chiavi'):]
        db, _ = costruisci(self, schema)
        testo = esporta_rdf.esporta(db, BASE)
        self.assertIn(f'<{BASE}tipo/sistema> rdf:type owl:Class .', testo)
        for assente in ('skos:altLabel', 'skos:exactMatch', 'owl:DatatypeProperty', 'owl:TransitiveProperty'):
            self.assertNotIn(assente, testo)

    def test_generazione_senza_le_tabelle(self):
        db = sqlite3.connect(':memory:')
        self.addCleanup(db.close)
        db.executescript("CREATE TABLE onto_tipi (nome TEXT, descrizione TEXT, dichiarato INTEGER, posizione INTEGER, padre TEXT);"
                         "INSERT INTO onto_tipi VALUES ('sistema', 'Strumenti', 1, 0, NULL);")
        testo = esporta_rdf.esporta(db, BASE)
        self.assertIn(f'<{BASE}tipo/sistema> rdf:type owl:Class .', testo)
        self.assertNotIn('owl:ObjectProperty', testo)
        self.assertEqual(esporta_rdf.esporta(sqlite3.connect(':memory:'), BASE).count('owl:Class'), 0)

    def test_sinonimi_e_corrispondenze_di_nomi_non_dichiarati_si_saltano(self):
        db = sqlite3.connect(':memory:')
        self.addCleanup(db.close)
        db.executescript("CREATE TABLE onto_tipi (nome TEXT, descrizione TEXT, dichiarato INTEGER, posizione INTEGER, padre TEXT);"
                         "CREATE TABLE onto_sinonimi (nome TEXT, sinonimo TEXT, posizione INTEGER);"
                         "CREATE TABLE onto_corrispondenze (nome TEXT, iri TEXT, vocabolario TEXT, esattezza TEXT, posizione INTEGER);"
                         "INSERT INTO onto_tipi VALUES ('sistema', '', 1, 0, NULL);"
                         "INSERT INTO onto_sinonimi VALUES ('fantasma', 'spettro', 0);"
                         "INSERT INTO onto_corrispondenze VALUES ('fantasma', 'x:Y', 'fibo', 'esatta', 0);")
        testo = esporta_rdf.esporta(db, BASE)
        self.assertNotIn('spettro', testo)
        self.assertNotIn('fantasma', testo)

    def test_riga_da_riga_il_grafo_non_cambia(self):
        _, percorso = costruisci(self, SCHEMA)
        prima = percorso.read_bytes()
        with redirect_stdout(io.StringIO()):
            esporta_rdf.main(['--db', str(percorso), '--base', BASE])
        self.assertEqual(percorso.read_bytes(), prima)


class Riga(unittest.TestCase):
    def setUp(self):
        _, self.percorso = costruisci(self, SCHEMA)

    def esegui(self, *argomenti):
        uscita = io.StringIO()
        with redirect_stdout(uscita):
            codice = esporta_rdf.main(['--db', str(self.percorso), *argomenti])
        return codice, uscita.getvalue()

    def test_stdout(self):
        codice, testo = self.esegui('--base', BASE)
        self.assertEqual(codice, 0)
        self.assertEqual(testo, FIXTURE.read_text(encoding='utf-8'))

    def test_out_scrive_un_file_lf(self):
        destinazione = self.percorso.parent / 'schema.ttl'
        codice, testo = self.esegui('--base', BASE, '--out', str(destinazione))
        self.assertEqual((codice, testo), (0, ''))
        dati = destinazione.read_bytes()
        self.assertNotIn(b'\r', dati)
        self.assertEqual(dati.decode('utf-8'), FIXTURE.read_text(encoding='utf-8'))

    def test_base_di_default(self):
        _, testo = self.esegui()
        self.assertIn(f'<{esporta_rdf.BASE_DEFAULT}> rdf:type owl:Ontology .', testo)

    def test_base_non_valida_esce_con_2(self):
        codice, testo = self.esegui('--base', 'non-un-iri')
        self.assertEqual((codice, testo), (2, ''))

    def test_grafo_assente_esce_con_2(self):
        uscita = io.StringIO()
        with redirect_stdout(uscita):
            codice = esporta_rdf.main(['--db', str(self.percorso.parent / 'manca.sqlite')])
        self.assertEqual(codice, 2)


class Installazione(unittest.TestCase):
    def test_e_un_file_facoltativo_del_kit(self):
        sorgente = (Path(__file__).resolve().parents[1] / 'installa.py').read_text(encoding='utf-8')
        self.assertRegex(sorgente, r'FACOLTATIVI = \{[^}]*"esporta_rdf\.py"')


if __name__ == '__main__':
    unittest.main()
