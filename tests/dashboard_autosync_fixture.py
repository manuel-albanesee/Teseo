"""Vault collaborativo sintetico per tests/dashboard_autosync_smoke.js: kit installato, remoto bare locale, autosync attivo.

Uso: python tests/dashboard_autosync_fixture.py <nuova-cartella>   (crea tutto sotto la cartella, avvia il servizio, stampa l'URL)
"""
import argparse
import contextlib
import io
from pathlib import Path
import shutil
import subprocess
import sys
import threading

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import installa
from kit.dashboard.autosync import Autosync
from kit.dashboard.git_sync import GitRepository, write_local_excludes
from kit.dashboard.server import DashboardServer

LOCAL = ['.graph/', '.graph_backup/', '.claude/', '.codex/', '.agents/', '.github/', '.obsidian/', '.trash/', 'CLAUDE.md', 'AGENTS.md']


def git(cwd, *args):
    subprocess.run(['git', '-c', 'core.autocrlf=false', *args], cwd=cwd, check=True, capture_output=True)


def create(destination):
    home = Path(destination).resolve()
    home.mkdir()
    template, remote, vault = home / 't', home / 'remote.git', home / 'vault'
    with contextlib.redirect_stdout(io.StringIO()):
        installa.installa(template, skill='no', esempio=True, client='claude', dashboard=True)
    git(home, 'init', '--bare', '-b', 'main', str(remote))
    shutil.copytree(template, vault)
    git(vault, 'init', '-b', 'main')
    git(vault, 'config', 'user.name', 'Alice')
    git(vault, 'config', 'user.email', 'alice@example.invalid')
    write_local_excludes(vault, LOCAL)
    git(vault, 'add', '-A')
    git(vault, 'commit', '-m', 'base')
    git(vault, 'remote', 'add', 'origin', str(remote))
    git(vault, 'push', '-u', 'origin', 'main')
    Autosync(vault, allow_local_remote=True).enable()
    return vault


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('destination', help='Nuova directory, deve essere assente')
    vault = create(parser.parse_args().destination)
    server = DashboardServer()
    server.sync.repository_factory = lambda root: GitRepository(root, allow_local_remote=True)  # il remoto di prova è una cartella locale
    server.registry.attach(str(vault))
    print(server.launch_url, flush=True)
    threading.Thread(target=server.serve_forever, kwargs={'poll_interval': 0.1}, daemon=True).start()
    sys.stdin.read()
    server.request_stop()
