"""Decisioni 7-11 di doc/17: proprietà `aciclica`, segnale `ciclo`, colonna `via` dei fatti dedotti, inverse come nome di lettura."""
import _shortpath  # noqa: F401
from pathlib import Path
import sqlite3
import sys
import unittest
from unittest import mock

import test_semantica as ts
from kit.dashboard.graph_service import BUILDER_VERSION
from kit.graph.ontology import parse, serialize

KIT = Path(__file__).resolve().parents[1] / 'kit'
sys.path.insert(0, str(KIT / 'graph'))
import domande  # noqa: E402
import esporta_rdf  # noqa: E402
import recall  # noqa: E402
import semantica  # noqa: E402

pagina = ts.pagina
PRECEDE = '| `precede` | sequenza | segue | transitiva |'
PRECEDE_ACICLICA = '| `precede` | sequenza | segue | transitiva, aciclica |'
SCHEMA_C = ts.BASE + ts.SEMANTICA.replace(PRECEDE, PRECEDE_ACICLICA) + ts.VINCOLI
assert SCHEMA_C != ts.SCHEMA


def processi(**relazioni):
    """Pagine `processo` che `precede` altre: {nome: [bersagli]}."""
    return {nome: pagina('processo', precede=bersagli) if bersagli else pagina('processo')
            for nome, bersagli in relazioni.items()}


class Parser(unittest.TestCase):
    def test_aciclica_e_una_proprieta_valida(self):
        document = parse(SCHEMA_C)
        self.assertEqual([i for i in document.issues if i.severity == 'error'], [])
        precede = next(item for item in document.semantics if item.name == 'precede')
        self.assertEqual(precede.properties, ('transitiva', 'aciclica'))
        self.assertEqual(serialize(document), SCHEMA_C.encode())  # la sezione si conserva byte per byte

    def test_simmetrica_e_aciclica_insieme_sono_un_errore(self):
        schema = ts.SCHEMA.replace('| `variante_di` | | | simmetrica |', '| `variante_di` | | | simmetrica, aciclica |')
        self.assertNotEqual(schema, ts.SCHEMA)
        self.assertIn('symmetric_acyclic', ts.codici(schema))
        self.assertNotIn('symmetric_acyclic', ts.codici(SCHEMA_C))

    def test_una_proprieta_sconosciuta_resta_un_errore(self):
        self.assertIn('invalid_property', ts.codici(SCHEMA_C.replace('transitiva, aciclica', 'transitiva, ciclica')))

    def test_la_funzionalita_ciclo_c_e_solo_se_dichiarata(self):
        self.assertIn('cycle_questions', parse(SCHEMA_C).capabilities)
        self.assertNotIn('cycle_questions', parse(ts.SCHEMA).capabilities)
        self.assertEqual(parse(ts.BASE).capabilities, ())


class Tabelle(unittest.TestCase):
    costruisci = ts.Tabelle.costruisci

    def test_colonna_aciclica(self):
        db = self.costruisci(SCHEMA_C)
        self.assertEqual(dict(db.execute('SELECT nome, aciclica FROM onto_relazioni')),
                         {'usa': 0, 'richiede': 0, 'parte_di': 0, 'referente': 0, 'precede': 1, 'causa': 0, 'variante_di': 0})
        db = self.costruisci(ts.BASE)
        self.assertEqual(db.execute('SELECT count(*) FROM onto_relazioni WHERE aciclica').fetchone(), (0,))

    def test_un_ciclo_non_e_un_errore_di_build(self):
        db = self.costruisci(SCHEMA_C, **processi(A=['B'], B=['A']))  # costruisci() afferma problemi == ()
        self.assertEqual(db.execute('SELECT count(*) FROM relations WHERE type = "precede"').fetchone(), (2,))

    def test_la_versione_del_builder(self):
        self.assertEqual(BUILDER_VERSION, 10)

    def test_la_vista_ha_la_colonna_via_prima_di_origine(self):
        db = self.costruisci(ts.SCHEMA)
        colonne = [c[0] for c in db.execute('SELECT * FROM relazioni_dedotte').description]
        self.assertEqual(colonne, ['source_id', 'target_id', 'type', 'via', 'origine'])

    def test_via_elenca_le_pagine_intermedie_in_ordine(self):
        db = self.costruisci(ts.SCHEMA,
                             A=pagina('sistema', richiede='B'), B=pagina('sistema', richiede='C'),
                             C=pagina('sistema', richiede='D'), D=pagina('sistema'),
                             E=pagina('sistema', richiede='F'), F=pagina('sistema', richiede='E'),
                             X=pagina('sistema', variante_di='Y'), Y=pagina('sistema'))
        righe = db.execute('SELECT source_id, target_id, via FROM relazioni_dedotte ORDER BY 1, 2').fetchall()
        # A → C passa da B; A → D da B e C, nell'ordine; una simmetrica non ha pagine intermedie (via vuota, non NULL)
        self.assertEqual(righe, [('A', 'C', 'B'), ('A', 'D', 'B → C'), ('B', 'D', 'C'), ('Y', 'X', '')])

    def test_un_fatto_dedotto_in_due_modi_e_una_riga_sola(self):
        db = self.costruisci(ts.SCHEMA,
                             P=pagina('sistema', richiede=['Q', 'R']), Q=pagina('sistema', richiede='S'),
                             R=pagina('sistema', richiede='S'), S=pagina('sistema'))
        self.assertEqual(db.execute("SELECT source_id, target_id, via FROM relazioni_dedotte").fetchall(), [('P', 'S', 'Q')])

    def test_vince_il_percorso_piu_corto(self):
        # P → Z → S (2 passi) e P → A → B → S (3 passi): il percorso corto vince anche se «A → B» viene prima in ordine alfabetico
        db = self.costruisci(ts.SCHEMA,
                             P=pagina('sistema', richiede=['Z', 'A']), Z=pagina('sistema', richiede='S'),
                             A=pagina('sistema', richiede='B'), B=pagina('sistema', richiede='S'), S=pagina('sistema'))
        self.assertEqual(db.execute("SELECT via FROM relazioni_dedotte WHERE source_id = 'P' AND target_id = 'S'").fetchall(),
                         [('Z',)])

    def test_un_giro_non_produce_fatti_su_se_stessi(self):
        db = self.costruisci(SCHEMA_C, **processi(A=['B'], B=['C'], C=['A']))
        self.assertEqual(db.execute('SELECT count(*) FROM relazioni_dedotte WHERE source_id = target_id').fetchone(), (0,))

    def test_la_lettura_tollera_un_grafo_senza_la_colonna(self):
        db = sqlite3.connect(':memory:')
        db.execute('CREATE TABLE onto_relazioni (nome TEXT, ruolo TEXT, inversa TEXT, transitiva INTEGER, simmetrica INTEGER)')
        self.assertEqual(semantica.aciclice(db), ())
        db.close()

    def test_la_lettura_dalle_tabelle(self):
        db = self.costruisci(SCHEMA_C)
        self.assertEqual(semantica.aciclice(db), ('precede',))
        self.assertEqual(semantica.aciclice(self.costruisci(ts.BASE)), ())


class Cicli(unittest.TestCase):
    rileva = ts.Vincoli.rileva

    def cicli(self, schema, **pagine):
        """{chiave: {'testo', 'pagine'}} delle sole domande con segnale `ciclo`."""
        trovati = {}
        for pagina_, voci in self.rileva(schema, **pagine).items():
            for segnale, testo, chiave in voci:
                if segnale == 'ciclo':
                    voce = trovati.setdefault(chiave, {'testo': testo, 'pagine': []})
                    voce['pagine'].append(pagina_)
        for voce in trovati.values():
            voce['pagine'].sort()
        return trovati

    def test_due_pagine_che_si_precedono(self):
        self.assertEqual(self.cicli(SCHEMA_C, **processi(A=['B'], B=['A'])), {
            'ciclo|precede|A → B': {'testo': 'Ciclo su `precede`: A → B → A. Quale ordine è giusto?', 'pagine': ['A', 'B']}})

    def test_la_chiave_non_dipende_da_dove_si_comincia(self):
        # B → C → A → B: il ciclo si riporta a partire dalla pagina minore
        trovati = self.cicli(SCHEMA_C, **processi(B=['C'], C=['A'], A=['B']))
        self.assertEqual(list(trovati), ['ciclo|precede|A → B → C'])
        self.assertEqual(trovati['ciclo|precede|A → B → C']['testo'],
                         'Ciclo su `precede`: A → B → C → A. Quale ordine è giusto?')
        self.assertEqual(trovati['ciclo|precede|A → B → C']['pagine'], ['A', 'B', 'C'])

    def test_una_pagina_che_precede_se_stessa(self):
        self.assertEqual(self.cicli(SCHEMA_C, **processi(A=['A'])), {
            'ciclo|precede|A': {'testo': 'Ciclo su `precede`: A → A. Quale ordine è giusto?', 'pagine': ['A']}})

    def test_un_giro_lungo_e_una_domanda_sola(self):
        trovati = self.cicli(SCHEMA_C, **processi(A=['B'], B=['C'], C=['D'], D=['E'], E=['A']))
        self.assertEqual(list(trovati), ['ciclo|precede|A → B → C → D → E'])
        self.assertEqual(trovati['ciclo|precede|A → B → C → D → E']['pagine'], ['A', 'B', 'C', 'D', 'E'])

    def test_due_cicli_che_condividono_una_pagina_sono_due_domande(self):
        trovati = self.cicli(SCHEMA_C, **processi(A=['B', 'C'], B=['A'], C=['A']))
        self.assertEqual(sorted(trovati), ['ciclo|precede|A → B', 'ciclo|precede|A → C'])

    def test_senza_giri_nessuna_domanda(self):
        self.assertEqual(self.cicli(SCHEMA_C, **processi(A=['B'], B=['C'], C=[])), {})

    def test_una_relazione_non_aciclica_non_fa_domande(self):
        pagine = {'A': pagina('sistema', richiede='B'), 'B': pagina('sistema', richiede='A')}
        self.assertEqual(self.cicli(SCHEMA_C, **pagine), {})

    def test_senza_la_proprieta_nessuna_domanda(self):
        for schema in (ts.SCHEMA, ts.BASE):
            with self.subTest(schema[:30]):
                self.assertEqual(self.cicli(schema, **processi(A=['B'], B=['A'])), {})

    def test_il_numero_di_domande_per_relazione_ha_un_tetto(self):
        nomi = [f'P{i}' for i in range(5)]  # il grafo completo su 5 pagine ha 84 giri
        pagine = processi(**{n: [m for m in nomi if m != n] for n in nomi})
        with mock.patch.object(domande, 'MAX_CICLI', 3):
            trovati = self.cicli(SCHEMA_C, **pagine)
        self.assertEqual(len(trovati), 3)
        with mock.patch.object(domande, 'MAX_CICLI', 3):
            self.assertEqual(sorted(self.cicli(SCHEMA_C, **pagine)), sorted(trovati))  # lo stesso insieme a ogni giro

    def test_il_segnale_viene_dopo_il_vincolo(self):
        self.assertEqual(domande.ORDINE.index('ciclo'), domande.ORDINE.index('vincolo') + 1)


class Recall(unittest.TestCase):
    def contesto(self, schema, domanda, **pagine):
        pagine = pagine or {'Rilascio': pagina('processo', usa='Console'), 'Console': pagina('sistema')}
        _, db = ts.crea_vault(self, schema, **pagine)
        semi, fatti, omessi = recall.richiama(db, domanda)
        info = {id_: (tipo, descr) for id_, tipo, descr in db.execute('SELECT id, tipo, descrizione FROM entities')}
        return db, semi, fatti, info, omessi

    def test_un_fatto_a_ritroso_usa_il_nome_dell_inversa(self):
        db, semi, fatti, info, omessi = self.contesto(ts.SCHEMA, 'Console')
        con = recall.formatta(semi, fatti, info, omessi, db=db)
        self.assertIn('- Console ← usa (è usato da) ← Rilascio', con)
        self.assertNotIn('Rilascio → usa → Console', con)

    def test_un_fatto_in_avanti_non_cambia(self):
        db, semi, fatti, info, omessi = self.contesto(ts.SCHEMA, 'Rilascio')
        self.assertIn('- Rilascio → usa → Console', recall.formatta(semi, fatti, info, omessi, db=db))

    def test_senza_inversa_dichiarata_la_freccia_resta(self):
        pagine = {'Modulo': pagina('sistema', parte_di='Gestionale'), 'Gestionale': pagina('sistema')}
        db, semi, fatti, info, omessi = self.contesto(ts.SCHEMA, 'Gestionale', **pagine)
        self.assertIn('- Modulo → parte_di → Gestionale', recall.formatta(semi, fatti, info, omessi, db=db))

    def test_senza_db_o_senza_sezione_il_contesto_non_cambia(self):
        db, semi, fatti, info, omessi = self.contesto(ts.SCHEMA, 'Console')
        senza_db = recall.formatta(semi, fatti, info, omessi)
        self.assertIn('- Rilascio → usa → Console', senza_db)
        db, semi, fatti, info, omessi = self.contesto(ts.BASE, 'Console')
        self.assertEqual(recall.formatta(semi, fatti, info, omessi, db=db), recall.formatta(semi, fatti, info, omessi))

    def test_un_fatto_dedotto_dice_da_dove_viene(self):
        semi = [('A', 'sistema', 'prima')]
        info = {'A': ('sistema', 'prima'), 'C': ('sistema', 'terza')}
        fatto = {'s': 'A', 'tipo': 'richiede', 't': 'C', 'passo': 2, 'verso': 'avanti', 'reciproco': False,
                 'dedotto': True, 'via': 'B'}
        self.assertIn('- A → richiede → C (dedotto, via B)', recall.formatta(semi, [fatto], info))
        self.assertIn('- A → richiede → C (dedotto)', recall.formatta(semi, [{**fatto, 'via': ''}], info))
        self.assertNotIn('dedotto', recall.formatta(semi, [{k: v for k, v in fatto.items() if k not in ('dedotto', 'via')}], info))


class Esporta(unittest.TestCase):
    costruisci = ts.Tabelle.costruisci

    def test_aciclica_e_asimmetrica_in_owl(self):
        righe = esporta_rdf.esporta(self.costruisci(SCHEMA_C))
        self.assertIn(f'<{esporta_rdf.BASE_DEFAULT}relazione/precede> rdf:type owl:AsymmetricProperty .', righe.splitlines())
        self.assertEqual(righe.count('owl:AsymmetricProperty'), 1)  # solo la relazione dichiarata aciclica
        self.assertNotIn('owl:AsymmetricProperty', esporta_rdf.esporta(self.costruisci(ts.SCHEMA)))


class ModelloDelKit(unittest.TestCase):
    def test_semantica_di_default_con_relazioni_acicliche(self):
        testo = (KIT / 'vault' / 'Wiki reference.md').read_text(encoding='utf-8')
        document = parse(testo)
        self.assertEqual([i for i in document.issues if i.severity == 'error'], [])
        semantica_ = {item.name: item for item in document.semantics}
        self.assertEqual({nome: item.role for nome, item in semantica_.items()},
                         {'usa': 'dipendenza', 'richiede': 'dipendenza', 'referente': 'responsabile',
                          'parte_di': 'composizione', 'causa': 'causale', 'precede': '', 'sostituisce': ''})
        self.assertEqual({nome for nome, item in semantica_.items() if 'aciclica' in item.properties},
                         {'parte_di', 'precede', 'sostituisce'})
        self.assertEqual(serialize(document), testo.encode('utf-8'))


if __name__ == '__main__':
    unittest.main()
