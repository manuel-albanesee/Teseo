"""Fase 0 di doc/17: KPI di coerenza (coerenza.py) e parafrasi del banco (banco.py, misura.py)."""
import _shortpath  # noqa: F401
from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import shutil
import sqlite3
import sys
import tempfile
import unittest

KIT = Path(__file__).resolve().parents[1] / 'kit'
sys.path.insert(0, str(KIT / 'graph'))
import banco  # noqa: E402
import build_graph  # noqa: E402
import coerenza  # noqa: E402
import misura  # noqa: E402
from graph_db import connect_graph  # noqa: E402


class VaultEsempio(unittest.TestCase):
    """Il vault d'esempio del kit, con il grafo costruito, in una cartella temporanea."""

    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.vault = Path(temp.name)
        shutil.copytree(KIT / 'esempio/wiki', self.vault / 'wiki')
        for nome in ('Wiki reference.md', 'index.md', 'log.md'):
            shutil.copy(KIT / 'vault' / nome, self.vault / nome)
        (self.vault / '.graph').mkdir()
        self.grafo = self.vault / '.graph/graph.sqlite'
        self.banco = self.vault / '.graph/banco.json'
        shutil.copy(KIT / 'esempio/banco.json', self.banco)
        with redirect_stdout(io.StringIO()):
            build_graph.costruisci(self.vault, self.grafo)
        self.db = connect_graph(self.grafo)
        self.addCleanup(self.db.close)
        self.nomi = coerenza.nomi_del_grafo(self.db)


class Jaccard(unittest.TestCase):
    def test_jaccard(self):
        self.assertAlmostEqual(coerenza.jaccard({'a', 'b'}, {'b', 'c'}), 1 / 3)
        self.assertEqual(coerenza.jaccard(set(), set()), 1.0)  # nessuna menzione in entrambe: accordo
        self.assertEqual(coerenza.jaccard({'a'}, set()), 0.0)
        self.assertEqual(coerenza.jaccard(['a', 'a'], ['a']), 1.0)


class Menzioni(VaultEsempio):
    def test_nomi_canonici(self):
        self.assertEqual(coerenza.menzioni('Scrivi ad Anna Rossi per il Modulo fatture.', self.nomi),
                         [('Anna Rossi', True), ('Modulo fatture', True)])

    def test_alias_e_varianti_non_sono_canonici(self):
        self.assertEqual(coerenza.menzioni('Apri un ticket sul service desk e chiedi a Rossi Anna', self.nomi),
                         [('ServiceDesk', False), ('Anna Rossi', False)])

    def test_vince_la_forma_piu_lunga(self):
        self.assertEqual(coerenza.menzioni('non arriva il file delle fatture', self.nomi), [('Modulo fatture', False)])
        self.assertEqual(coerenza.menzioni('apri la Console di rilascio', self.nomi), [('Console di rilascio', True)])
        self.assertEqual(coerenza.menzioni('apri la console', self.nomi), [('Console di rilascio', False)])

    def test_accenti_e_maiuscole_non_contano(self):
        self.assertEqual(coerenza.menzioni('ANNA ROSSÌ', self.nomi), [('Anna Rossi', True)])

    def test_fonti_e_parole_parziali_non_sono_menzioni(self):
        self.assertEqual(coerenza.menzioni('le fatturazioni e la call-2026-09-10', self.nomi), [])

    def test_parola_comune_conta_solo_con_la_maiuscola(self):
        nomi = {'portale': ('Portale', True)}  # «portale» è in recall.PAROLE_COMUNI
        self.assertEqual(coerenza.menzioni('il portale è giù', nomi), [])
        self.assertEqual(coerenza.menzioni('il Portale è giù', nomi), [('Portale', True)])

    def test_coerenza_dei_nomi(self):
        esito = coerenza.coerenza_nomi(['Anna Rossi e il Modulo fatture', 'chiedi a Rossi Anna'], self.nomi)
        self.assertEqual(esito, {'menzioni': 3, 'canoniche': 2, 'quota': 2 / 3})
        self.assertEqual(coerenza.coerenza_nomi(['nessun nome qui'], self.nomi),
                         {'menzioni': 0, 'canoniche': 0, 'quota': None})


class NomiDelGrafo(unittest.TestCase):
    def test_una_forma_di_due_pagine_non_conta(self):
        db = sqlite3.connect(':memory:')
        self.addCleanup(db.close)
        db.executescript("""
            CREATE TABLE entities (id TEXT, path TEXT);
            CREATE TABLE aliases (entity_id TEXT, alias TEXT);
            CREATE TABLE varianti (entity_id TEXT, variante TEXT);
            INSERT INTO entities VALUES ('Alfa', 'wiki/Alfa.md'), ('Beta', 'wiki/Beta.md'), ('call-1', NULL);
            INSERT INTO aliases VALUES ('Alfa', 'comune'), ('Beta', 'Comune'), ('Beta', 'bi');
        """)
        nomi = coerenza.nomi_del_grafo(db)
        self.assertEqual(nomi, {'alfa': ('Alfa', True), 'beta': ('Beta', True), 'bi': ('Beta', False)})

    def test_grafo_senza_varianti(self):
        db = sqlite3.connect(':memory:')
        self.addCleanup(db.close)
        db.executescript("CREATE TABLE entities (id TEXT, path TEXT); CREATE TABLE aliases (entity_id TEXT, alias TEXT);"
                         "INSERT INTO entities VALUES ('Alfa', 'wiki/Alfa.md');")
        self.assertEqual(coerenza.nomi_del_grafo(db), {'alfa': ('Alfa', True)})


def scrivi(cartella, nome, dati):
    (cartella / nome).write_text(dati if isinstance(dati, str) else json.dumps(dati), encoding='utf-8')


class Risposte(VaultEsempio):
    def setUp(self):
        super().setUp()
        self.risposte = self.vault / 'risposte'
        self.risposte.mkdir()

    def test_leggi_risposte(self):
        scrivi(self.risposte, '01-grafo-2.json', {'domanda': 'd', 'risposta': 'Anna Rossi', 'corretta': False})
        scrivi(self.risposte, '01-grafo-1.json', {'domanda': 'd', 'risposta': 'Modulo fatture', 'corretta': True})
        scrivi(self.risposte, '01-hook-1.json', {'domanda': 'd', 'risposta': 'x', 'regex': [True, False]})
        scrivi(self.risposte, '02-grafo-1.json', '{rotto')
        scrivi(self.risposte, '03-grafo-1.json', {'domanda': 'd', 'risposta': '', 'errore': 'timeout'})
        scrivi(self.risposte, '01-hook-1.md', 'testo della risposta')
        risposte, scartate = coerenza.leggi_risposte(self.risposte)
        self.assertEqual(sorted(risposte), [(1, 'grafo'), (1, 'hook')])
        self.assertEqual([r['risposta'] for r in risposte[(1, 'grafo')]], ['Modulo fatture', 'Anna Rossi'])
        self.assertEqual([r['esito'] for r in risposte[(1, 'grafo')]], [True, False])
        self.assertEqual(risposte[(1, 'hook')][0]['esito'], False)
        self.assertEqual([nome for nome, _ in scartate], ['02-grafo-1.json', '03-grafo-1.json'])

    def test_stabilita_fra_giri(self):
        for giro, (testo, ok) in enumerate((('Anna Rossi e Modulo fatture', True), ('Modulo fatture, Anna Rossi', True),
                                            ('solo Anna Rossi', False)), 1):
            scrivi(self.risposte, f'01-grafo-{giro}.json', {'risposta': testo, 'corretta': ok})
        scrivi(self.risposte, '02-grafo-1.json', {'risposta': 'Gestionale', 'corretta': True})  # un solo giro: escluso
        for giro in (1, 2):
            scrivi(self.risposte, f'02-ricerca-{giro}.json', {'risposta': 'ServiceDesk', 'corretta': True})
        risposte, _ = coerenza.leggi_risposte(self.risposte)
        stabilita = coerenza.stabilita_giri(risposte, self.nomi)
        self.assertEqual(stabilita['grafo']['domande'], 1)
        self.assertAlmostEqual(stabilita['grafo']['jaccard_medio'], (1 + 0.5 + 0.5) / 3)
        self.assertEqual(stabilita['grafo']['esito_stabile'], 0)
        self.assertEqual(stabilita['ricerca'], {'domande': 1, 'jaccard_medio': 1.0, 'esito_stabile': 1})

    def esegui(self, *argv):
        uscita = io.StringIO()
        with redirect_stdout(uscita):
            codice = coerenza.main(['--risposte', str(self.risposte), '--db', str(self.grafo), *argv])
        return codice, uscita.getvalue()

    def test_riga_per_condizione(self):
        scrivi(self.risposte, '01-grafo-1.json', {'risposta': 'Anna Rossi e Rossi Anna', 'corretta': True})
        scrivi(self.risposte, '01-grafo-2.json', {'risposta': 'Anna Rossi', 'corretta': True})
        codice, testo = self.esegui()
        self.assertEqual(codice, 0)
        self.assertIn('grafo: nomi canonici 2/3 (67%) · stabilità fra giri 1.00 · esito stabile 1/1 · 2 risposte', testo)
        codice, testo = self.esegui('--json')
        self.assertEqual(json.loads(testo)['condizioni']['grafo']['menzioni'], 3)

    def test_cartella_senza_risposte(self):
        codice, testo = self.esegui()
        self.assertEqual(codice, 2)
        self.assertIn('nessuna risposta', testo)


class Parafrasi(VaultEsempio):
    def voci(self):
        return json.loads(self.banco.read_text(encoding='utf-8'))

    def salva(self, voci):
        self.banco.write_text(json.dumps(voci, ensure_ascii=False), encoding='utf-8')

    def misura(self):
        uscita = io.StringIO()
        with redirect_stdout(uscita):
            esiti = misura.misura_banco(self.db, self.banco)
        return esiti, uscita.getvalue()

    def test_il_banco_del_kit_ha_parafrasi_valide(self):
        self.assertTrue(any(v.get('parafrasi') for v in self.voci()))
        self.assertEqual([p for p in banco.verifica(self.db, self.banco) if 'parafrasi' in p[1]], [])

    def test_verifica_delle_parafrasi(self):
        voci = self.voci()
        voci[0]['parafrasi'] = 'non una lista'
        voci[1]['parafrasi'] = ['quale sigla va nelle richieste?']           # domanda della voce 3
        voci[2]['parafrasi'] = ['in che modo si scrive l\'acronimo del progetto?']  # parole del titolo
        self.salva(voci)
        problemi = banco.verifica(self.db, self.banco)
        self.assertIn(('ERRORE', 'voce 1 «a chi chiedo il ticket della settimana per poter r»: «parafrasi» deve'
                       ' essere una lista di domande'), problemi)
        self.assertIn(('ERRORE', 'voce 2 «dove si aprono le segnalazioni?»: parafrasi uguale alla voce 3'), problemi)
        self.assertIn(('AVVISO', 'voce 3 «quale sigla va nelle richieste?»: la parafrasi «in che modo si scrive'
                       ' l\'acronimo del progetto?» usa le parole del titolo di «Acronimo del progetto»'), problemi)

    def test_parafrasi_ripetuta_nella_stessa_voce(self):
        voci = self.voci()
        voci[1]['parafrasi'] = ['dove apro una richiesta di aiuto?', 'Dove apro una richiesta di aiuto']
        self.salva(voci)
        self.assertIn(('ERRORE', 'voce 2 «dove si aprono le segnalazioni?»: parafrasi ripetuta'),
                      banco.verifica(self.db, self.banco))

    def test_misura_della_stabilita_senza_cambiare_il_recall(self):
        esiti, testo = self.misura()
        righe = [r for r in testo.splitlines() if r.startswith(('banco:', '  locale:', '  globale:'))]
        self.assertRegex(testo, r'parafrasi: 2 voci, 2 parafrasi · stabilità media \d\.\d\d · stesso seme \d/2')
        con = [e for e in esiti if 'parafrasi' in e]
        self.assertEqual(len(con), 2)
        self.assertTrue(all(0.0 <= e['stabilita'] <= 1.0 and 0 <= e['stesso_seme'] <= 1 for e in con))
        self.assertEqual(set(con[0]['parafrasi'][0]), {'domanda', 'semi', 'portate'})
        voci = self.voci()
        for voce in voci:
            voce.pop('parafrasi', None)
        self.salva(voci)
        esiti_senza, testo_senza = self.misura()
        self.assertEqual(righe, [r for r in testo_senza.splitlines() if r.startswith(('banco:', '  locale:', '  globale:'))])
        self.assertNotIn('parafrasi:', testo_senza)
        self.assertTrue(all('stabilita' not in e for e in esiti_senza))

    def test_parafrasi_non_lista_rende_il_banco_non_valido(self):
        voci = self.voci()
        voci[0]['parafrasi'] = [1, 2]
        self.salva(voci)
        esiti, testo = self.misura()
        self.assertIsNone(esiti)
        self.assertIn('banco non valido', testo)

    def confronta(self, dopo, prima):
        uscita = io.StringIO()
        with redirect_stdout(uscita):
            misura.confronta_banco(dopo, prima)
        return uscita.getvalue()

    def test_confronto_della_stabilita(self):
        def esito(stabilita=None):
            e = {'domanda': 'a', 'tipo': 'locale', 'attese': ['X'], 'portate': ['X'], 'mancanti': [], 'token': 10}
            return e if stabilita is None else {**e, 'stabilita': stabilita}
        self.assertIn('stabilità fra parafrasi: 0.50 → 1.00 (+0.50)', self.confronta([esito(1.0)], [esito(0.5)]))
        self.assertNotIn('stabilità fra parafrasi', self.confronta([esito(1.0)], [esito()]))  # salvataggio vecchio


if __name__ == '__main__':
    unittest.main()
