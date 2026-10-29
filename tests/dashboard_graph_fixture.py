"""Vault sintetico per tests/dashboard_graph_smoke.js: 120 nodi, catena causale, storia Git con due autori, server locale.

Uso: python tests/dashboard_graph_fixture.py <nuova-cartella> [--nodi N]   (crea il vault, avvia il servizio e stampa l'URL di sessione)
Con --nodi più grande di 120 ogni nodo ha anche un arco verso un altro nodo scelto in modo deterministico (grafo denso).
"""
import argparse
import os
from pathlib import Path
import random
import subprocess
import sys
import threading

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from kit.dashboard.graph_service import rebuild
from kit.dashboard.server import DashboardServer

SCHEMA = ('## Tipi ammessi\n| Tipo | Descrizione |\n| --- | --- |\n| `concetto` | Idea |\n| `episodio` | Fatto |\n'
          '## Relazioni tipizzate\n| Relazione | Da (tipo) | A (tipo) | Significato | Esempio |\n| --- | --- | --- | --- | --- |\n'
          '| `usa` | concetto | concetto | X usa Y | A → B |\n| `causa` | qualsiasi | qualsiasi | X causa Y | A → B |\n'
          '## Fonti\n| `nota-utente` | Precisazione utente |\n')


def git(root, *args, author='Ada'):
    env = {**os.environ, 'GIT_CONFIG_GLOBAL': os.devnull, 'GIT_CONFIG_NOSYSTEM': '1', 'GIT_AUTHOR_NAME': author,
           'GIT_AUTHOR_EMAIL': author.lower() + '@example.org', 'GIT_COMMITTER_NAME': author, 'GIT_COMMITTER_EMAIL': author.lower() + '@example.org'}
    subprocess.run(['git', *args], cwd=root, env=env, check=True, capture_output=True)


def create(destination, nodi=120):
    root = Path(destination).resolve()
    root.mkdir()
    for directory in ('wiki', 'raw', '.graph', '.teseo'):
        (root / directory).mkdir()
    (root / '.teseo/project.json').write_bytes((ROOT / 'tests/fixtures/dashboard/project-v1.json').read_bytes())
    (root / 'Wiki reference.md').write_text(SCHEMA, encoding='utf-8')
    for number in range(nodi):
        targets = [(number + 1) % nodi]
        if nodi > 120:
            chord = random.Random(number).randrange(nodi)
            if chord not in (number, targets[0]):
                targets.append(chord)
        usa = ', '.join(f'"[[Nodo {t:03}]]"' for t in targets)
        (root / f'wiki/Nodo {number:03}.md').write_text(
            f'---\ntipo: concetto\ntags: [sintetico]\naggiornato: 2026-10-01\nusa: [{usa}]\n---\n# Nodo {number:03}\nTesto.\n', encoding='utf-8')
    for number in range(4):
        effect = f'causa: "[[Evento {number + 1}]]"\n' if number < 3 else ''
        detail = 'relazioni_dettaglio:\n  "[[Evento 1]]": {confidenza: alta, evidenza: "Lo afferma la call"}\n' if number == 0 else ''
        (root / f'wiki/Evento {number}.md').write_text(f'---\ntipo: episodio\n{effect}{detail}---\nEvento {number}\n', encoding='utf-8')
    git(root, 'init', '-q', '-b', 'main')
    git(root, 'add', 'wiki')
    git(root, 'commit', '-q', '-m', 'inizio', author='Ada')
    page = root / 'wiki/Nodo 007.md'
    page.write_text(page.read_text(encoding='utf-8') + 'Aggiunta di Bruno.\n', encoding='utf-8')
    git(root, 'add', 'wiki')
    git(root, 'commit', '-q', '-m', 'modifica', author='Bruno')
    rebuild(root)
    return root


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('destination', help='Nuova directory sintetica, deve essere assente')
    parser.add_argument('--nodi', type=int, default=120, help='numero di pagine Nodo (predefinito 120)')
    arguments = parser.parse_args()
    vault = create(arguments.destination, arguments.nodi)
    server = DashboardServer()
    server.registry.attach(str(vault))
    print(server.launch_url, flush=True)
    threading.Thread(target=server.serve_forever, kwargs={'poll_interval': 0.1}, daemon=True).start()
    sys.stdin.read()
    server.request_stop()
