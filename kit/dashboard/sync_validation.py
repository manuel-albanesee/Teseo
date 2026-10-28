"""Deterministic integration gates; semantic reconciliation needs a human verdict.

The optional callback belongs to the trusted service, never to vault data. It
attests an already reviewed, frozen candidate and cannot authorize new bytes.
Lexical/neighborhood overlap is conservative evidence, not semantic proof.
"""
from collections import Counter
from pathlib import Path
from copy import deepcopy
import subprocess
import sys

from .contracts import ContractError, content_hash, parse_json
from .storage import capture_snapshot, validate_raw_unchanged
from .read_api import _parser
from .shared_state import validate_snapshot
from .graph_service import rebuild


def _documents(snapshot):
    try:
        return {item.path: item.data.decode('utf-8') for item in snapshot.files
                if item.path in ('Wiki reference.md', 'index.md', 'log.md')
                or item.path.startswith('wiki/')}
    except UnicodeError as error:
        raise ContractError('integration_invalid', 'Documento non UTF-8') from error


def _parse(snapshot):
    try:
        parsed = _parser().parse_documents(_documents(snapshot))
    except (ValueError, TypeError) as error:
        raise ContractError('integration_invalid', 'Documenti o schema non validi') from error
    if parsed['problem_details']:
        raise ContractError('integration_invalid', 'Schema, link, tipi, alias o fonti non validi: '
                            + parsed['problem_details'][0]['code'])
    return parsed


def _structural(parents, candidate):
    for parent in parents:
        validate_raw_unchanged(parent, candidate)
        for path, digest in parent.hashes.items():
            if path.startswith('.teseo/shared/') and candidate.hashes.get(path) != digest:
                raise ContractError('immutable_event_changed', 'Evento preesistente alterato o rimosso', path)
        if parent.hashes.get('.teseo/project.json') != candidate.hashes.get('.teseo/project.json'):
            raise ContractError('manifest_changed', 'Identità o policy del vault cambiate')
    validate_snapshot(candidate)
    return _parse(candidate)


def _changed(base, branch):
    before, after = base.hashes, branch.hashes
    return {path for path in before.keys() | after.keys() if before.get(path) != after.get(path)}


def _neighborhoods(parsed_roots):
    tokens = {}
    adjacency = {}
    # Both historical and new neighborhoods matter: deleting a relation does not
    # make concurrent work independent. Aliases normalize through the runtime.
    parser = _parser()
    for parsed in parsed_roots:
        for page in parsed['pagine']:
            tokens.setdefault(f'wiki/{page}.md', set()).add('entity:' + parser.norm(page))
        for page, alias in parsed['alias']:
            tokens.setdefault(f'wiki/{page}.md', set()).add('entity:' + parser.norm(alias))
        for source, target, relation in parsed['relazioni']:
            token = ('source:' if relation == 'documentato_in' else 'entity:') + parser.norm(target)
            tokens.setdefault(f'wiki/{source}.md', set()).add(token)
            if relation != 'documentato_in':
                tokens.setdefault(f'wiki/{target}.md', set()).add('entity:' + parser.norm(source))
                source_id, target_id = parser.norm(source), parser.norm(target)
                adjacency.setdefault(source_id, set()).add(target_id)
                adjacency.setdefault(target_id, set()).add(source_id)
    # A whole connected neighborhood is conservative: synthesis may depend on a
    # chain rather than a direct edge. Component labels keep memory linear.
    components = {}
    for entity in sorted(adjacency):
        if entity in components:
            continue
        pending = [entity]
        components[entity] = entity
        while pending:
            for neighbor in adjacency[pending.pop()]:
                if neighbor not in components:
                    components[neighbor] = entity
                    pending.append(neighbor)
    for path, values in tokens.items():
        entity = parser.norm(Path(path).stem)
        if entity in components:
            values.add('neighborhood:' + components[entity])
    return tokens


def _scope(base, local, remote, parsed_roots):
    local_paths, remote_paths = _changed(base, local), _changed(base, remote)
    if max(len(local_paths), len(remote_paths)) > 512:
        raise ContractError('integration_limit', 'Integrazione oltre 512 percorsi cambiati per ramo; ridurre il perimetro')
    neighborhoods = _neighborhoods(parsed_roots)
    for snapshot in (base, local, remote):
        for item in snapshot.files:
            if item.path.startswith('.teseo/shared/events/'):
                event = parse_json(item.data)
                values = neighborhoods.setdefault(item.path, set())
                values.add('question:' + event['question_id'])
                payload = event['payload']
                pages = payload.get('pages', []) + [anchor['page'] for anchor in payload.get('anchors', [])]
                if event['kind'] == 'page.renamed':
                    pages += [payload['from'], payload['to']]
                for page in pages:
                    values.update(neighborhoods.get(f'wiki/{page}.md', {'entity:' + _parser().norm(page)}))
    scope = set()
    global_paths = {'Wiki reference.md', 'index.md', 'log.md'}
    contents = {name: {item.path: item.data for item in snapshot.files}
                for name, snapshot in (('base', base), ('local', local), ('remote', remote))}

    def additive(path, side):
        # Ogni skill aggiunge righe a log.md/index.md: se un lato non cancella né riscrive nulla, l'unione
        # dei due lati non può perdere informazione e il file non è più un punto di contatto semantico.
        if path not in ('log.md', 'index.md'):
            return False
        old, new = contents['base'].get(path, b''), contents[side].get(path, b'')
        if path == 'log.md':
            return new.startswith(old)
        return not Counter(old.splitlines()) - Counter(new.splitlines())

    for left in local_paths:
        for right in remote_paths:
            if left == right and local.hashes.get(left) == remote.hashes.get(right):
                continue
            if left == right and additive(left, 'local') and additive(right, 'remote'):
                continue
            left_global = left in global_paths and not additive(left, 'local')
            right_global = right in global_paths and not additive(right, 'remote')
            if (left == right or left_global or right_global
                    or neighborhoods.get(left, set()) & neighborhoods.get(right, set())):
                scope.update((left, right))
    return sorted(scope)


def _synthesis(root):
    runtime = Path(__file__).resolve().parents[1]
    helper = runtime / 'teseo_validate.py'
    if not helper.is_file():
        helper = runtime / 'graph/teseo_validate.py'
    try:
        checked = subprocess.run([sys.executable, str(helper), str(root)], cwd=helper.parent,
            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            timeout=60, shell=False, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    except (OSError, subprocess.TimeoutExpired) as error:
        raise ContractError('synthesis_invalid', 'Verifica sintesi non completata') from error
    if checked.returncode:
        raise ContractError('synthesis_invalid', 'Verifica deterministica delle sintesi fallita')


def validate_integration(base_root, local_root, remote_root, candidate_root, *, reconcile=None):
    """Validate isolated complete vaults; only candidate derived caches are written.

    Returns ``validated`` or ``needs_decision``. Structural violations raise
    ContractError. A trusted callback may attest ``human_decision=True``, exact
    ``input_key``, ``scope`` and ``candidate_digest``; resolved alone is ignored.
    The caller must authenticate that human decision and bind it to its own
    operation. This function never asks an LLM to approve an integration.
    """
    roots = tuple(Path(root).resolve(strict=True) for root in (base_root, local_root, remote_root, candidate_root))
    if len(set(roots)) != 4 or any(left in right.parents for left in roots for right in roots if left != right):
        raise ContractError('integration_roots', 'Richiesti quattro snapshot isolati distinti')
    snapshots = tuple(capture_snapshot(root) for root in roots)
    base, local, remote, candidate = snapshots
    parsed = _structural((base, local, remote), candidate)
    scope = _scope(base, local, remote, [_parse(item) for item in snapshots[:3]] + [parsed])
    frozen = {'base_digest': base.digest, 'local_digest': local.digest,
              'remote_digest': remote.digest, 'candidate_digest': candidate.digest, 'scope': scope}
    key = content_hash(frozen)
    result = dict(frozen, key=key, assurance='deterministic gates; correlation heuristic; human semantic review required',
                  checks={'raw_immutable': True, 'events_immutable': True,
                          'shared_events_valid': True, 'schema_links_aliases_sources': True})
    rebuild(roots[3])
    _synthesis(roots[3])
    for snapshot, root in zip(snapshots, roots):
        snapshot.assert_unchanged(root)
    result['checks'].update(graph=True, synthesis=True)
    if scope:
        request = dict(result, state='needs_decision')
        verdict = reconcile(deepcopy(request)) if reconcile is not None else None
        # A callback must not mutate parents or candidate after reviewing hashes.
        for snapshot, root in zip(snapshots, roots):
            snapshot.assert_unchanged(root)
        if (not isinstance(verdict, dict) or verdict.get('resolved') is not True
                or verdict.get('human_decision') is not True or verdict.get('input_key') != key
                or verdict.get('scope') != scope or verdict.get('candidate_digest') != candidate.digest):
            return request
        _structural((base, local, remote), capture_snapshot(roots[3]))
        result['assurance'] = 'human decision bound to frozen inputs; deterministic gates passed'
    return dict(result, state='validated')
