"""Adozione esplicita di un vault legacy: crea il manifest dati e lo stato locale, senza toccare note, raw, script né database.

Prima un'anteprima (che cosa si crea, quanti file, problemi del grafo), poi l'adozione con il digest dell'anteprima e un
consenso esplicito. Nessun file esistente si modifica o si sposta: per questo non serve un backup, e il ritorno al formato legacy
è la sola cancellazione di `.teseo/` (mai automatica). Un vault con `.teseo/` già presente ma senza manifest valido non si adotta.
"""
from pathlib import Path
from uuid import uuid4

from .contracts import (ContractError, DEFAULT_SHARED_PATHS, KIT_VERSION, canonical_json, check_path_budget, content_hash,
                        inspect_vault)

MAX_PROBLEMS = 50


def _parser():
    try:
        from ..graph import build_graph
    except ImportError:
        import build_graph
    return build_graph


def _counts(root):
    pages = sum(1 for path in (root / 'wiki').glob('*.md') if path.is_file())
    raw_files = raw_bytes = 0
    if (root / 'raw').is_dir():
        for path in (root / 'raw').rglob('*'):
            if path.is_file() and not path.is_symlink():
                raw_files += 1
                raw_bytes += path.stat().st_size
    return pages, raw_files, raw_bytes


def preview(root):
    """Che cosa creerebbe l'adozione e se il grafo si potrebbe costruire; nessuna scrittura."""
    root = Path(root).resolve(strict=True)
    compatibility = inspect_vault(root)
    if compatibility.mode == 'compatible':
        raise ContractError('already_adopted', 'Il vault ha già un manifest dati compatibile')
    if compatibility.mode != 'legacy_readonly':
        issue = compatibility.issues[0]['message'] if compatibility.issues else 'Formato non supportato'
        raise ContractError('adoption_unavailable', issue)
    if (root / '.teseo').exists():
        raise ContractError('adoption_conflict', 'Esiste già una cartella .teseo senza manifest valido: nessuna adozione automatica')
    check_path_budget(root)
    pages, raw_files, raw_bytes = _counts(root)
    try:
        problems = [{'code': item['code'], 'page': item['page']} for item in _parser().parse_snapshot(root)['problem_details'][:MAX_PROBLEMS]]
        parse_error = None
    except (ValueError, OSError) as error:
        problems, parse_error = [], str(error)[:300]
    files = [{'path': '.teseo/project.json', 'action': 'create'}, {'path': '.teseo/local/', 'action': 'create'}]
    plan = {'files': files, 'pages': pages, 'raw_files': raw_files, 'raw_bytes': raw_bytes, 'problems': problems,
            'parse_error': parse_error, 'graph_buildable': not problems and parse_error is None,
            'unchanged': 'Nessuna nota, fonte raw, script o database esistente viene modificato o spostato.'}
    plan['plan_digest'] = content_hash({'root': str(root), 'files': files, 'pages': pages, 'raw_files': raw_files,
                                        'problems': problems, 'parse_error': parse_error})
    return plan


def apply(root, plan_digest, confirm, *, rebuild=True):
    """Crea `.teseo/project.json` (nuovo vault_id) e, se il grafo è costruibile, la prima generazione."""
    if confirm is not True:
        raise ContractError('adoption_consent', 'Confermare esplicitamente l’adozione del vault')
    root = Path(root).resolve(strict=True)
    plan = preview(root)
    if plan['plan_digest'] != plan_digest:
        raise ContractError('preview_stale', 'Il vault è cambiato dall’anteprima: crearne una nuova')
    directory = root / '.teseo'
    directory.mkdir()  # FileExistsError se un altro processo l'ha creata nel frattempo: nessuna sovrascrittura
    vault_id = str(uuid4())
    with (directory / 'project.json').open('xb') as stream:
        stream.write(canonical_json({'format_version': 1, 'schema_version': 1, 'event_version': 1, 'minimum_kit_version': KIT_VERSION,
                                     'vault_id': vault_id, 'shared_paths': list(DEFAULT_SHARED_PATHS)}))
    graph = {'state': 'not_built', 'reason': 'rebuild non richiesto'}
    if rebuild and plan['graph_buildable']:
        from .graph_service import rebuild as build
        try:
            reference = build(root)
            graph = {'state': 'built', 'generation': reference.generation}
        except ContractError as error:
            graph = {'state': 'not_built', 'reason': error.code}
    elif rebuild:
        graph = {'state': 'not_built', 'reason': 'problemi nel vault: correggerli e ricostruire il grafo'}
    return {'vault_id': vault_id, 'created': [item['path'] for item in plan['files']], 'graph': graph}


class AdoptionService:
    def __init__(self, registry):
        self.registry = registry

    def preview(self, vault_id, body):
        if body != {}:
            raise ContractError('invalid_payload', 'Anteprima senza parametri')
        return preview(self.registry.root(vault_id))

    def apply(self, vault_id, body):
        if not isinstance(body, dict) or set(body) != {'plan_digest', 'confirm'} or not isinstance(body['plan_digest'], str):
            raise ContractError('invalid_payload', 'Richiesti plan_digest e confirm')
        root = self.registry.root(vault_id)
        result = apply(root, body['plan_digest'], body['confirm'])
        result['vault'] = self.registry.attach(str(root))  # l'identità passa dal percorso al vault_id del manifest
        return result
