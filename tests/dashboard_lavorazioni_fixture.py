"""Vault sintetico per tests/dashboard_lavorazioni_smoke.js: lavorazioni in stati diversi, server locale, nessun dato reale.

Uso: python tests/dashboard_lavorazioni_fixture.py DIRECTORY_NUOVA   (stampa l'URL autenticato e resta in ascolto, Ctrl+C per uscire)
"""
import argparse
import http.client
import json
from pathlib import Path
import shutil
import subprocess
import sys
import threading

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from kit.dashboard.server import DashboardServer


def kit(vault, script, *argomenti):
    fatto = subprocess.run([sys.executable, str(ROOT / 'kit/graph' / script), '--vault', str(vault), *argomenti], capture_output=True, timeout=120)
    assert fatto.returncode == 0, fatto.stdout + fatto.stderr


def create(destination):
    """Vault con tre lavorazioni: una completata, una con la raccolta da rifare, una con la definizione rotta."""
    root = Path(destination).resolve()
    root.mkdir()  # Fail closed: mai sovrascrivere una directory esistente.
    shutil.copytree(ROOT / 'kit/esempio/wiki', root / 'wiki')
    shutil.copytree(ROOT / 'kit/esempio/raw', root / 'raw')
    for nome in ('Wiki reference.md', 'index.md', 'log.md'):
        shutil.copy(ROOT / 'kit/vault' / nome, root / nome)
    (root / '.graph').mkdir()
    kit(root, 'build_graph.py', '--out', str(root / '.graph/graph.sqlite'))
    modelli = ['--modelli', str(ROOT / 'kit/lavorazioni')]
    kit(root, 'lavorazioni.py', 'nuova', 'completa', '--da', 'report-periodico', *modelli)
    kit(root, 'lavorazioni.py', 'avvia', 'completa', '--oggi', '2026-10-23')
    kit(root, 'lavorazioni.py', 'nuova', 'scheda-rilascio', '--da', 'scheda-argomento', *modelli)
    kit(root, 'lavorazioni.py', 'avvia', 'scheda-rilascio', '--param', 'argomento=Rilascio in produzione', '--oggi', '2026-10-23')
    pagina = root / 'wiki/Console di rilascio.md'
    pagina.write_text(pagina.read_text(encoding='utf-8') + '\nFatto aggiunto dopo la raccolta.\n', encoding='utf-8')
    kit(root, 'lavorazioni.py', 'nuova', 'rotta', '--da', 'report-periodico', *modelli)
    (root / 'lavorazioni/rotta/config.md').unlink()
    return root


def serve(root):
    server = DashboardServer()
    threading.Thread(target=server.serve_forever, kwargs={'poll_interval': 0.05}, daemon=True).start()
    connessione = http.client.HTTPConnection('127.0.0.1', server.server_port, timeout=10)
    connessione.request('POST', '/api/v1/vaults/attach', body=json.dumps({'path': str(root)}),
                        headers={'X-Teseo-Session': server.session_token, 'Origin': server.origin,
                                 'Content-Type': 'application/json', 'X-Teseo-CSRF': server.csrf_token})
    assert connessione.getresponse().status == 200
    return server


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('destination', help='Nuova directory sintetica, deve essere assente')
    server = serve(create(parser.parse_args().destination))
    print(server.launch_url, flush=True)
    try:
        threading.Event().wait()
    except KeyboardInterrupt:
        server.shutdown()
