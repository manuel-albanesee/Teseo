"""Export diagnostico per le segnalazioni: versioni, forma del vault, codici dei problemi e dei guasti. Mai contenuti.

Esclusi per costruzione: testo delle note e dei raw, nomi delle pagine, percorsi assoluti, URL del remoto, nomi di autori,
messaggi di errore liberi. Restano conteggi, codici stabili e identificatori che non rivelano contenuto (hash di generazione).
"""
from collections import Counter
from pathlib import Path
import platform
import sqlite3
import sys

from .contracts import KIT_VERSION, ContractError, parse_json
from .storage import _no_link

STATUS_KEYS = ('compatibility', 'schema_version', 'busy', 'stale', 'graph_generation', 'validation_version')
CAPABILITY_KEYS = ('graph', 'rebuild', 'ontology_preview', 'shared_state', 'ontology_apply', 'graph_edit',
                   'ontology_apply_automatic', 'external_writer_exclusion', 'sync', 'sync_automatic')


def _environment():
    try:
        import yaml
        yaml_version = yaml.__version__
    except ImportError:
        yaml_version = None
    return {'kit_version': KIT_VERSION, 'python': platform.python_version(), 'implementation': platform.python_implementation(),
            'system': platform.system(), 'release': platform.release(), 'machine': platform.machine(),
            'sqlite': sqlite3.sqlite_version, 'pyyaml': yaml_version, 'frozen': bool(getattr(sys, 'frozen', False))}


def _git_version():
    try:
        from .git_sync import _invoke
        out = _invoke(Path.cwd(), ['--version'], check=False).stdout.decode('utf-8', 'replace').strip()
        return out[:80] or None
    except (ContractError, OSError):
        return None


def _shape(root):
    pages = len(list((root / 'wiki').glob('*.md'))) if (root / 'wiki').is_dir() else 0
    raw_files = raw_bytes = binary = 0
    if (root / 'raw').is_dir():
        for path in (root / 'raw').rglob('*'):
            if path.is_file() and not path.is_symlink():
                raw_files += 1
                raw_bytes += path.stat().st_size
                binary += path.suffix.lower() not in ('.md', '.txt', '.csv', '.json', '.py', '.yaml', '.yml')
    return {'pages': pages, 'raw_files': raw_files, 'raw_bytes': raw_bytes, 'raw_non_text': binary,
            'has_git': (root / '.git').exists(), 'has_graph_kit': (root / '.graph').is_dir()}


def _journal(root):
    """Conteggi del journal per tipo e stato e gli ultimi codici d'errore; sola lettura, nessun testo libero."""
    try:
        for relative in ('.teseo', '.teseo/local', '.teseo/local/operations.sqlite'):
            _no_link(root / relative)
        path = root / '.teseo/local/operations.sqlite'
        if not path.is_file():
            return {'available': False}
        db = sqlite3.connect(path.as_uri() + '?mode=ro', uri=True, timeout=1)
        try:
            records = [parse_json(row[0]) for row in db.execute('SELECT record FROM operations WHERE length(record)<=5242880 ORDER BY rowid DESC LIMIT 200')]
        finally:
            db.close()
    except (ContractError, OSError, sqlite3.Error):
        return {'available': False}
    states = Counter(f"{item.get('kind')}:{item.get('state')}" for item in records)
    errors = Counter((item.get('error') or {}).get('code') for item in records if item.get('error'))
    return {'available': True, 'recent': len(records), 'by_kind_state': dict(sorted(states.items())),
            'error_codes': dict(sorted((str(code), count) for code, count in errors.items()))}


class DiagnosticsExporter:
    def __init__(self, registry, read_api, sync):
        self.registry, self.read_api, self.sync = registry, read_api, sync

    def export(self, vault_id, parameters=None):
        if parameters:
            raise ContractError('invalid_query', 'L’export non accetta parametri')
        root = self.registry.root(vault_id)
        status = self.read_api.status(vault_id)
        result = {'format': 1, 'environment': _environment() | {'git': _git_version()},
                  'vault': {key: status.get(key) for key in STATUS_KEYS} | {
                      'capabilities': {key: status['capabilities'].get(key) for key in CAPABILITY_KEYS},
                      'status_issue_codes': sorted({item['code'] for item in status.get('issues', [])})},
                  'shape': _shape(root), 'journal': _journal(root)}
        try:
            report = self.read_api.diagnostics(vault_id, {})
            counts = Counter((item['severity'], item['code']) for item in report['issues'])
            result['issues'] = {'total': len(report['issues']), 'truncated': report['truncated'],
                                'by_severity_code': {f'{severity}:{code}': count for (severity, code), count in sorted(counts.items())}}
        except ContractError as error:
            result['issues'] = {'unavailable': error.code}
        try:
            sync = self.sync.status(vault_id)
            config = sync.get('config') or {}
            url = config.get('remote_url') or ''
            result['sync'] = {'configured': sync.get('configured'), 'state': sync.get('state'), 'automatic': sync.get('automatic'),
                              'mode': config.get('mode'), 'transport': 'ssh' if url.startswith(('git@', 'ssh://')) else 'https' if url.startswith('https://') else None,
                              'error_code': ((sync.get('current_operation') or {}).get('error') or {}).get('code'),
                              'git_error_code': (sync.get('git_error') or {}).get('code')}
        except ContractError as error:
            result['sync'] = {'unavailable': error.code}
        return result
