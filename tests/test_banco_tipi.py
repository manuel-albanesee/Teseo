"""Voce B2 di doc/16: il banco distingue domande locali e globali, misura.py le riepiloga e le confronta a parte."""
import _shortpath  # noqa: F401
from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest

KIT = Path(__file__).resolve().parents[1] / 'kit'
sys.path.insert(0, str(KIT / 'graph'))
import banco  # noqa: E402
import build_graph  # noqa: E402
import misura  # noqa: E402
from graph_db import connect_graph  # noqa: E402


def esito(domanda, tipo, attese, portate):
    return {'domanda': domanda, 'tipo': tipo, 'attese': attese, 'portate': portate, 'token': 10, 'semi_grafo': 1,
            'testo': False, 'mancanti': [p for p in attese if p not in portate],
            'rumore': len(set(portate) - set(attese))}


class Banco(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.vault = Path(temp.name)
        shutil.copytree(KIT / 'esempio/wiki', self.vault / 'wiki')
        for nome in ('Wiki reference.md', 'index.md', 'log.md'):
            shutil.copy(KIT / 'vault' / nome, self.vault / nome)
        (self.vault / '.graph').mkdir()
        self.banco = self.vault / '.graph/banco.json'
        shutil.copy(KIT / 'esempio/banco.json', self.banco)
        with redirect_stdout(io.StringIO()):
            build_graph.costruisci(self.vault, self.vault / '.graph/graph.sqlite')
        self.db = connect_graph(self.vault / '.graph/graph.sqlite')
        self.addCleanup(self.db.close)

    def misura(self):
        uscita = io.StringIO()
        with redirect_stdout(uscita):
            esiti = misura.misura_banco(self.db, self.banco)
        return esiti, uscita.getvalue()

    def test_riepilogo_totale_e_per_tipo(self):
        esiti, testo = self.misura()
        self.assertEqual([e['tipo'] for e in esiti], ['locale'] * 3 + ['globale'] * 2)
        righe = [r for r in testo.splitlines() if r.startswith(('banco:', '  locale:', '  globale:'))]
        self.assertEqual([r.split(':')[0] for r in righe], ['banco', '  locale', '  globale'])
        self.assertIn('domande complete ', righe[1])
        self.assertRegex(righe[1], r'/3 · ')   # tre domande locali
        self.assertRegex(righe[2], r'/2 · ')   # due globali
        self.assertRegex(righe[2], r'portate \d+/7 ')  # 4 + 3 pagine attese
        self.assertTrue(any(r.rstrip().endswith('G') or 'G   mancano' in r for r in testo.splitlines()
                            if r.startswith('elenca i sistemi')))

    def test_banco_di_un_solo_tipo_non_ripete_il_riepilogo(self):
        voci = [v for v in json.loads(self.banco.read_text(encoding='utf-8')) if v['tipo'] == 'locale']
        for voce in voci:
            del voce['tipo']  # predefinito: locale
        self.banco.write_text(json.dumps(voci), encoding='utf-8')
        esiti, testo = self.misura()
        self.assertEqual({e['tipo'] for e in esiti}, {'locale'})
        self.assertNotIn('  locale:', testo)

    def test_tipo_sconosciuto_rende_il_banco_non_valido(self):
        voci = json.loads(self.banco.read_text(encoding='utf-8'))
        voci[0]['tipo'] = 'regionale'
        self.banco.write_text(json.dumps(voci), encoding='utf-8')
        esiti, testo = self.misura()
        self.assertIsNone(esiti)
        self.assertIn('banco non valido', testo)
        problemi = banco.verifica(self.db, self.banco)
        self.assertIn(('ERRORE', 'voce 1 «a chi chiedo il ticket della settimana per poter r»: «tipo» deve essere'
                       ' uno tra locale, globale'), problemi)

    def test_il_banco_del_kit_supera_la_verifica(self):
        self.assertEqual([p for p in banco.verifica(self.db, self.banco) if p[0] == 'ERRORE'], [])

    def test_confronto_con_saldo_per_tipo(self):
        prima = [esito('a', 'locale', ['X'], ['X']), esito('b', 'globale', ['Y', 'Z'], ['Y'])]
        dopo = [esito('a', 'locale', ['X'], []), esito('b', 'globale', ['Y', 'Z'], ['Y', 'Z'])]
        uscita = io.StringIO()
        with redirect_stdout(uscita):
            misura.confronta_banco(dopo, prima)
        testo = uscita.getvalue()
        self.assertIn('saldo: 1 migliorate · 1 peggiorate', testo)
        self.assertIn('  saldo locale: 0 migliorate · 1 peggiorate · pagine attese -1', testo)
        self.assertIn('  saldo globale: 1 migliorate · 0 peggiorate · pagine attese +1', testo)

    def test_salvataggio_senza_tipo_vale_come_locale(self):
        prima = [{k: v for k, v in esito('a', 'locale', ['X'], ['X']).items() if k != 'tipo'}]
        uscita = io.StringIO()
        with redirect_stdout(uscita):
            misura.confronta_banco([esito('a', 'locale', ['X'], ['X'])], prima)
        self.assertNotIn('saldo locale', uscita.getvalue())
        self.assertIn('0 peggiorate', uscita.getvalue())


if __name__ == '__main__':
    unittest.main()
