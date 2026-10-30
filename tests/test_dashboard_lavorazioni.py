"""Pannello delle lavorazioni: rotta di sola lettura, interfaccia cablata e nessuna scrittura."""
import _shortpath  # noqa: F401
import hashlib
import http.client
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
from kit.dashboard.bootstrap_ui import PAGE
from kit.dashboard.server import DashboardServer
from kit.dashboard.ui_script import SCRIPT


def esegui(vault, script, *argomenti):
    fatto = subprocess.run([sys.executable, str(ROOT / 'kit/graph' / script), '--vault', str(vault), *argomenti],
                           capture_output=True, timeout=120)
    assert fatto.returncode == 0, fatto.stdout + fatto.stderr
    return fatto.stdout.decode('utf-8')


class RottaLavorazioni(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix='teseo lav ')
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name).resolve()
        shutil.copytree(ROOT / 'kit/esempio/wiki', self.root / 'wiki')
        shutil.copytree(ROOT / 'kit/esempio/raw', self.root / 'raw')
        for nome in ('Wiki reference.md', 'index.md', 'log.md'):
            shutil.copy(ROOT / 'kit/vault' / nome, self.root / nome)
        (self.root / '.graph').mkdir()
        esegui(self.root, 'build_graph.py', '--out', str(self.root / '.graph/graph.sqlite'))
        self.server = DashboardServer()
        self.thread = threading.Thread(target=self.server.serve_forever, kwargs={'poll_interval': 0.02})
        self.thread.start()
        self.addCleanup(self.stop)
        status, _, corpo = self.request('POST', '/api/v1/vaults/attach', {'path': str(self.root)})
        self.assertEqual(status, 200, corpo)
        self.vault_id = json.loads(corpo)['vault_id']

    def stop(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)

    def request(self, metodo, percorso, dati=None, autenticato=True):
        intestazioni = {'X-Teseo-Session': self.server.session_token} if autenticato else {}
        if metodo == 'POST':
            intestazioni.update({'Origin': self.server.origin, 'Content-Type': 'application/json',
                                 'X-Teseo-CSRF': self.server.csrf_token})
        connessione = http.client.HTTPConnection('127.0.0.1', self.server.server_port, timeout=10)
        try:
            connessione.request(metodo, percorso, body=json.dumps(dati).encode() if dati is not None else None, headers=intestazioni)
            risposta = connessione.getresponse()
            return risposta.status, dict(risposta.getheaders()), risposta.read()
        finally:
            connessione.close()

    def lavorazioni(self, query=''):
        return self.request('GET', f'/api/v1/vaults/{self.vault_id}/lavorazioni{query}')

    def impronte(self):
        return {p.relative_to(self.root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                for p in sorted(self.root.rglob('*')) if p.is_file() and p.name != 'graph.sqlite'}

    def crea_lavorazione(self):
        esegui(self.root, 'lavorazioni.py', 'nuova', 'rep', '--da', 'report-periodico', '--modelli', str(ROOT / 'kit/lavorazioni'))
        esegui(self.root, 'lavorazioni.py', 'avvia', 'rep', '--oggi', '2026-10-23')

    def test_senza_lavorazioni(self):
        stato, _, corpo = self.lavorazioni()
        self.assertEqual(stato, 200, corpo)
        self.assertEqual(json.loads(corpo), {'presente': False, 'troncato': False, 'lavorazioni': []})

    def test_mostra_stato_fasi_e_output(self):
        self.crea_lavorazione()
        stato, _, corpo = self.lavorazioni()
        self.assertEqual(stato, 200, corpo)
        voce = json.loads(corpo)['lavorazioni'][0]
        self.assertEqual((voce['nome'], voce['esecuzione'], voce['problemi']), ('rep', '2026-10-23-1', []))
        self.assertEqual([f['stato'] for f in voce['fasi']], ['COMPLETA', 'IN ATTESA', 'IN ATTESA'])
        self.assertEqual(voce['output'], ['lavorazioni/rep/esecuzioni/2026-10-23-1/01-raccolta/raccolta.md'])

    def test_fase_da_rifare_dopo_la_modifica_di_una_pagina(self):
        self.crea_lavorazione()
        pagina = self.root / 'wiki/ServiceDesk.md'
        pagina.write_text(pagina.read_text(encoding='utf-8') + '\nNuovo fatto.\n', encoding='utf-8')
        fase = json.loads(self.lavorazioni()[2])['lavorazioni'][0]['fasi'][0]
        self.assertEqual(fase['stato'], 'DA RIFARE')
        self.assertIn('ServiceDesk', fase['motivi'][0])

    def test_sola_lettura_e_nessun_processo_avviato(self):
        self.crea_lavorazione()
        prima = self.impronte()
        with mock.patch('subprocess.run', side_effect=AssertionError('nessuna esecuzione')), \
                mock.patch('subprocess.Popen', side_effect=AssertionError('nessuna esecuzione')):
            self.assertEqual(self.lavorazioni()[0], 200)
        self.assertEqual(self.impronte(), prima)

    def test_richiede_la_sessione_e_rifiuta_i_parametri(self):
        self.assertIn(self.lavorazioni_non_autenticata()[0], (401, 403))
        stato, _, corpo = self.lavorazioni('?generation=' + 'a' * 64)
        self.assertEqual(stato, 400, corpo)
        self.assertEqual(json.loads(corpo)['error']['code'], 'invalid_query')

    def lavorazioni_non_autenticata(self):
        return self.request('GET', f'/api/v1/vaults/{self.vault_id}/lavorazioni', autenticato=False)

    def test_vault_sconosciuto(self):
        stato, _, corpo = self.request('GET', '/api/v1/vaults/00000000-0000-4000-8000-000000000000/lavorazioni')
        self.assertGreaterEqual(stato, 400)
        self.assertNotIn(b'Traceback', corpo)

    def test_lavorazione_con_definizione_rotta_non_fa_cadere_la_rotta(self):
        self.crea_lavorazione()
        (self.root / 'lavorazioni/rep/config.md').unlink()
        stato, _, corpo = self.lavorazioni()
        self.assertEqual(stato, 200, corpo)
        self.assertIn('config_mancante', [q['codice'] for q in json.loads(corpo)['lavorazioni'][0]['problemi']])


class Interfaccia(unittest.TestCase):
    def test_il_pannello_e_nella_pagina_e_nello_script(self):
        self.assertIn('id="lavorazioni-panel"', PAGE)
        self.assertIn('<summary>Lavorazioni</summary>', PAGE)
        self.assertIn('function createLavorazioniPanel', SCRIPT)
        self.assertIn('lavorazioni.reset()', SCRIPT)
        self.assertIn('lavorazioni.mount(status)', SCRIPT)

    def test_il_pannello_scrive_solo_testo(self):
        from kit.dashboard.lavorazioni_ui import LAVORAZIONI_SCRIPT
        for vietato in ('innerHTML', 'outerHTML', 'insertAdjacentHTML', 'eval(', 'document.write'):
            self.assertNotIn(vietato, LAVORAZIONI_SCRIPT)

    def test_il_pannello_non_invia_richieste_di_scrittura(self):
        from kit.dashboard.lavorazioni_ui import LAVORAZIONI_SCRIPT
        self.assertNotRegex(LAVORAZIONI_SCRIPT, r"method\s*:\s*['\"](POST|PUT|PATCH|DELETE)")
        self.assertEqual(LAVORAZIONI_SCRIPT.count('api('), 1)

    def test_il_pannello_ha_un_messaggio_per_i_lettori_di_schermo(self):
        from kit.dashboard.lavorazioni_ui import LAVORAZIONI_SCRIPT
        self.assertIn("aria-live", LAVORAZIONI_SCRIPT)
        self.assertIn("role", LAVORAZIONI_SCRIPT)


if __name__ == '__main__':
    unittest.main()
