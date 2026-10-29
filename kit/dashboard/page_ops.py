"""Crea, rinomina ed elimina pagine del grafo: preview multi-file con candidato già validato, apply dal journal.

Rinominare riscrive solo i bersagli dei link `[[Vecchio]]` (nel frontmatter, nel corpo, in index.md e log.md), conservando
cartella, sezione e testo del link. Eliminare toglie la pagina e la sua riga di index.md; se altre pagine la citano, la
proposta non è valida (link non risolti) e va corretta prima. Nessuna scrittura qui: l'apply è quello di `graph_edit`.
"""
import difflib
import hashlib
import html
import re

from .contracts import ContractError, content_hash, portable_path
from .graph_edit import GraphEditService, _parsed, _word, _key
from .ontology_preview import _documents, _fields
from .read_api import _parser

MAX_NAME = 120
MAX_DIFF = 200_000
_NAME = re.compile(r'[^\x00-\x1f\x7f/\\:*?"<>|#^\[\]]+')
_SCHEMA_DOCUMENTS = ('index.md', 'log.md')


def _name(value, label):
    if (not isinstance(value, str) or not 0 < len(value) <= MAX_NAME or value != value.strip() or not _NAME.fullmatch(value)
            or value.casefold() in ('index', 'log', 'wiki reference')):
        raise ContractError('edit_invalid', f'{label}: nome pagina non valido (niente / \\ : * ? " < > | # ^ [ ], spazi ai bordi o nomi riservati)')
    try:
        portable_path(f'wiki/{value}.md')
    except ContractError:
        raise ContractError('edit_invalid', f'{label}: nome non portabile su tutti i sistemi') from None
    return value


def _retarget(text, old, new):
    """Sostituisce il nome della pagina nei link che puntano a `old`; il resto del link (cartella, #sezione, |testo) resta."""
    parser = _parser()

    def replace(match):
        raw = match.group(1)
        if parser.bersaglio(raw) != old:
            return match.group(0)
        target = re.match(r'[^#|\\]*', raw).group(0)
        folder, slash, last = target.rpartition('/')
        renamed = (folder + slash) + last.replace(last.strip(), new, 1) + raw[len(target):]
        return match.group(0).replace('[[' + raw + ']]', '[[' + renamed + ']]', 1)
    return parser.LINK.sub(replace, text)


def _without_index_row(text, name):
    parser = _parser()
    lines = text.splitlines(keepends=True)
    keep = [line for line in lines if not (parser.RIGA_INDICE.fullmatch(line.rstrip('\r\n')) and parser.bersaglio(parser.RIGA_INDICE.fullmatch(line.rstrip('\r\n')).group(1)) == name)]
    return ''.join(keep)


def _new_page(name, tipo, today):
    head = [f'tipo: {_word(tipo)}'] if tipo else []
    return '---\n' + ''.join(line + '\n' for line in head) + f'aggiornato: {today.isoformat()}\n---\n\n# {name}\n'


def build_changes(documents, operation, today):
    """{percorso: nuovo testo | None (eliminato)} per l'operazione, oppure ContractError edit_*."""
    if not isinstance(operation, dict) or not isinstance(operation.get('op'), str):
        raise ContractError('invalid_payload', 'L’operazione richiede il campo op')
    kind = operation['op']
    pages = {path[5:-3]: path for path in documents if path.startswith('wiki/') and path.count('/') == 1 and path.endswith('.md')}
    taken = {name.casefold() for name in pages}
    if kind == 'create':
        _fields(operation, ('op', 'name', 'tipo'))
        name = _name(operation['name'], 'name')
        tipo = operation['tipo']
        if tipo is not None and (not isinstance(tipo, str) or not tipo.strip() or len(tipo) > 80 or tipo != tipo.strip() or re.search(r'[\x00-\x1f\x7f]', tipo)):
            raise ContractError('edit_invalid', 'tipo: atteso un testo breve')
        if name.casefold() in taken:
            raise ContractError('edit_duplicate', f"Esiste già una pagina '{name}' (anche solo per maiuscole)")
        return {f'wiki/{name}.md': _new_page(name, tipo, today)}
    if kind == 'rename':
        _fields(operation, ('op', 'page', 'new_name'))
        old, new = operation['page'], _name(operation['new_name'], 'new_name')
        if old not in pages:
            raise ContractError('node_missing', 'Pagina non presente nel vault')
        if new == old or new.casefold() in taken:
            raise ContractError('edit_duplicate', f"Esiste già una pagina '{new}' (anche solo per maiuscole): scegliere un altro nome")
        changes = {f'wiki/{new}.md': _retarget(documents[pages[old]], old, new), pages[old]: None}
        for path, text in documents.items():
            if path != pages[old] and (path in pages.values() or path in _SCHEMA_DOCUMENTS):
                updated = _retarget(text, old, new)
                if updated != text:
                    changes[path] = updated
        return changes
    if kind == 'delete':
        _fields(operation, ('op', 'page'))
        if operation['page'] not in pages:
            raise ContractError('node_missing', 'Pagina non presente nel vault')
        changes = {pages[operation['page']]: None}
        if 'index.md' in documents:
            updated = _without_index_row(documents['index.md'], operation['page'])
            if updated != documents['index.md']:
                changes['index.md'] = updated
        return changes
    raise ContractError('invalid_payload', 'Operazione sconosciuta: create, rename o delete')


def analyze(snapshot, operation, today):
    documents = _documents(snapshot)
    base = _parsed(documents)
    changes = build_changes(documents, operation, today)
    candidate = {path: text for path, text in documents.items() if path not in changes}
    candidate.update({path: text for path, text in changes.items() if text is not None})
    result = _parsed(candidate)
    known = {_key(item) for item in base['problem_details']}
    new = [item for item in result['problem_details'] if _key(item) not in known]
    old = [item for item in result['problem_details'] if _key(item) in known]
    diff = ''.join(''.join(difflib.unified_diff(documents.get(path, '').splitlines(keepends=True), (text or '').splitlines(keepends=True),
                                                fromfile=path + (' (base)' if path in documents else ' (assente)'),
                                                tofile=path + (' (proposta)' if text is not None else ' (eliminata)')))
                   for path, text in sorted(changes.items()))
    risk = None
    if new:
        risk = 'L’operazione introduce problemi nel grafo (per esempio link non risolti verso la pagina): correggerli prima di applicare'
    elif old:
        risk = 'Il vault ha problemi preesistenti, anche fuori da questa operazione: il grafo non si ricostruisce finché non sono corretti'
    data = {path: None if text is None else text.encode('utf-8') for path, text in changes.items()}
    digest = hashlib.sha256(b'\0'.join(path.encode() + b'\1' + (b'-' if value is None else value) for path, value in sorted(data.items()))).hexdigest()
    record = {'operation': operation, 'paths': sorted(changes), 'base_content_digest': snapshot.digest, 'candidate_sha256': digest,
              'valid': not result['problem_details'], 'problems': (new + old)[:200], 'new_problems': len(new),
              'preexisting_problems': len(old), 'problems_truncated': len(new) + len(old) > 200,
              'diff': html.escape(diff[:MAX_DIFF], quote=False), 'diff_truncated': len(diff) > MAX_DIFF, 'text_format': 'escaped_markdown',
              'risk': risk}
    record['proposal_hash'] = content_hash({key: record[key] for key in ('paths', 'base_content_digest', 'candidate_sha256')})
    return record, data


class PageOpsService(GraphEditService):
    """Stessa cache di proposte e stesso limite di preview concorrenti dell'editor del grafo; cambia solo l'analisi."""
    def preview(self, vault_id, body):
        _fields(body, ('base_content_digest', 'idempotency_key', 'operation'))
        # La validazione del payload e la cache sono quelle dell'editor; l'operazione entra nell'impronta della richiesta.
        return super().preview(vault_id, '*', {'base_content_digest': body['base_content_digest'], 'idempotency_key': body['idempotency_key'],
                                               'operations': body['operation']})

    def _analyze(self, snapshot, node_id, operations):
        return analyze(snapshot, operations, self.clock())
