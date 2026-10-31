"""Prova nel browser della voce B1 di doc/16: filtro «Categoria», gerarchie nel vocabolario, campo «Sottotipo di».

Vault sintetico a generazioni, servizio locale, poi dashboard_tassonomia_browser.js con il Playwright preinstallato
(desktop 1440×900 e mobile 390×844, schermate in CARTELLA). Non fa parte della suite unittest.
Uso: python tests/dashboard_tassonomia_browser.py CARTELLA"""
import http.client
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import threading

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'tests'))
from kit.dashboard.graph_service import rebuild  # noqa: E402
from kit.dashboard.server import DashboardServer  # noqa: E402
import test_tassonomia as t  # noqa: E402

root = Path(tempfile.mkdtemp()) / 'vault'
for d in ('wiki', 'raw', '.graph', '.teseo'):
    (root / d).mkdir(parents=True)
(root / '.teseo/project.json').write_bytes((ROOT / 'tests/fixtures/dashboard/project-v1.json').read_bytes())
(root / 'Wiki reference.md').write_text(t.SCHEMA.replace('| `usa` | processo |', '| `usa` | qualsiasi |'), encoding='utf-8')
for nome, testo in {'Fatture': t.pagina('servizio', ['ciclo-passivo'], usa='Gestionale'),
                    'Gestionale': t.pagina('sistema', ['amministrazione'], usa='Console'),
                    'Console': t.pagina('sistema', ['rilasci']), 'Anna': t.pagina('persona')}.items():
    (root / 'wiki' / (nome + '.md')).write_text(testo, encoding='utf-8')
rebuild(root)
server = DashboardServer()
threading.Thread(target=server.serve_forever, kwargs={'poll_interval': 0.05}, daemon=True).start()
c = http.client.HTTPConnection('127.0.0.1', server.server_port, timeout=10)
c.request('POST', '/api/v1/vaults/attach', body=json.dumps({'path': str(root)}),
          headers={'X-Teseo-Session': server.session_token, 'Origin': server.origin,
                   'Content-Type': 'application/json', 'X-Teseo-CSRF': server.csrf_token})
assert c.getresponse().status == 200
cartella = Path(sys.argv[1]).resolve()
cartella.mkdir(parents=True, exist_ok=True)
r = subprocess.run(['node', str(Path(__file__).with_name('dashboard_tassonomia_browser.js')), server.launch_url, str(cartella)],
                   cwd=str(cartella))
server.server_close()
sys.exit(r.returncode)
