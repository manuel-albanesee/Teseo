"""Preview su snapshot corrente: schema candidato e impatto, nessuna scrittura."""
from collections import Counter
from copy import deepcopy
from dataclasses import asdict, replace
import difflib
import hashlib
import html
import json
import re
import threading
import time
from uuid import uuid4

from .contracts import ContractError, content_hash
from .storage import capture_snapshot
from .read_api import _parser
from .ontology_migrations import describe, migration_id

MAX_RESPONSE = 2 * 1024 * 1024
MAX_ITEMS = 20000


def _ontology_module():
    try:
        from ..graph import ontology
    except ImportError:
        import ontology
    return ontology


def _fields(value, required, optional=()):
    if not isinstance(value, dict) or not set(required) <= set(value) or set(value) - set(required) - set(optional):
        raise ContractError('invalid_patch', 'Campi della patch non validi')


def _located_error(code, reason, page, prop='frontmatter'):
    error = ContractError(code, reason)
    error.details = [{'code': code, 'page': page, 'property': prop, 'reason': reason, 'target': None}]
    return error


def _patch(document, operations, observed):
    ontology = _ontology_module()
    types, relations = document.types, document.relations
    current, renames, changes = document, [], []
    for index, operation in enumerate(operations):
        if not isinstance(operation, dict) or not isinstance(operation.get('op'), str):
            raise ContractError('invalid_patch', 'Richiesta operazione dichiarativa')
        kind = operation['op']
        if kind == 'adopt_types':
            _fields(operation, ('op',))
            if index != 0:
                raise ContractError('invalid_patch', 'Adozione ammessa solo come prima operazione')
            current = ontology.parse(ontology.propose_type_catalog(current, observed).candidate)
            types = current.types
        elif kind in ('add_type', 'update_type', 'remove_type', 'rename_type',
                      'add_relation', 'update_relation', 'remove_relation', 'rename_relation'):
            if types is None:
                raise ContractError('catalog_adoption_required', 'Proporre esplicitamente adopt_types prima delle modifiche')
            action, category = kind.split('_', 1)
            _fields(operation, ('op', 'name'), ('value',) if action in ('add', 'update') else ('to',) if action == 'rename' else ())
            name = operation['name']
            if not isinstance(name, str):
                raise ContractError('invalid_patch', 'Nome richiesto come stringa')
            if any(item['kind'] == category and name in (item['from'], item['to']) for item in renames):
                raise ContractError('invalid_patch', 'Separare le operazioni su nomi già rinominati in preview distinte')
            values = list(types if category == 'type' else relations)
            found = next((i for i, item in enumerate(values) if item.name == name), None)
            if (action == 'add' and found is not None) or (action != 'add' and found is None):
                raise ContractError('invalid_patch', 'Nome esistente per aggiunta o assente per modifica')
            if action in ('add', 'update'):
                value = operation.get('value')
                if category == 'type':
                    _fields(value, (), ('description',))
                    item = ontology.TypeDef(name, value.get('description', ''))
                else:
                    _fields(value, ('from_types', 'to_types'), ('meaning', 'example', 'direction'))
                    if any(not isinstance(value[key], list) or len(value[key]) > 128 for key in ('from_types', 'to_types')):
                        raise ContractError('invalid_patch', 'Vincoli richiesti come liste, massimo 128 tipi')
                    item = ontology.Relation(name, tuple(value['from_types']), tuple(value['to_types']),
                        value.get('meaning', ''), value.get('example', ''), value.get('direction', 'source_to_target'))
                if action == 'add':
                    values.append(item)
                else:
                    values[found] = item
            elif action == 'remove':
                values.pop(found)
            else:
                target = operation.get('to')
                if not isinstance(target, str):
                    raise ContractError('invalid_patch', 'Destinazione rinomina richiesta')
                if any(item['kind'] == category and target in (item['from'], item['to']) for item in renames):
                    raise ContractError('invalid_patch', 'Catene di rinomina non supportate in una sola preview')
                values[found] = replace(values[found], name=target)
                renames.append({'kind': category, 'from': name, 'to': target})
                if category == 'type':
                    relations = tuple(replace(item,
                        from_types=tuple(target if part == name else part for part in item.from_types),
                        to_types=tuple(target if part == name else part for part in item.to_types)) for item in relations)
            if category == 'type':
                types = tuple(values)
            else:
                relations = tuple(values)
        else:
            raise ContractError('invalid_patch', 'Operazione non supportata; rinomina pagine e inversione automatica escluse')
        changes.append(deepcopy(operation))
    issues = ontology.validate(types, relations)
    if issues:
        if len(issues) > 200:
            raise ContractError('preview_limit', 'Oltre 200 errori schema: ridurre la patch prima della preview')
        error = ContractError('invalid_schema', 'Schema candidato non valido')
        error.details = [{'code': issue.code, 'page': 'Wiki reference.md', 'property': 'ontology',
                          'reason': issue.message, 'target': None} for issue in issues]
        raise error
    candidate = ontology.serialize(current, types=types, relations=relations)
    return candidate, renames, changes


def _documents(snapshot):
    documents = {}
    for entry in snapshot.files:
        if entry.path in ('Wiki reference.md', 'index.md', 'log.md') or (
                entry.path.startswith('wiki/') and entry.path.count('/') == 1 and entry.path.endswith('.md')):
            if len(entry.data) > 2 * 1024 * 1024:
                raise ContractError('preview_limit', 'Documento oltre 2 MiB')
            try:
                documents[entry.path] = entry.data.decode('utf-8')
            except UnicodeError:
                raise _located_error('preview_encoding', 'Documento non UTF-8', entry.path, 'document') from None
    if len(documents) > 1000 or sum(len(text.encode('utf-8')) for text in documents.values()) > 8 * 1024 * 1024:
        raise ContractError('preview_limit', 'Preview limitata a 1000 documenti e 8 MiB Markdown')
    if 'Wiki reference.md' not in documents:
        raise ContractError('ontology_manual', 'Wiki reference.md richiesto per la preview')
    return documents


def analyze(snapshot, patch):
    """Funzione pura rispetto al filesystem: tutti i dati derivano dallo snapshot."""
    parser, ontology = _parser(), _ontology_module()
    documents = _documents(snapshot)
    document = ontology.parse(documents['Wiki reference.md'])
    if not document.structurally_editable:
        raise ContractError('ontology_manual', 'Schema ambiguo o invalido: editing manuale richiesto')
    # Parse each page first, so syntax failures always identify their document.
    for path, text in documents.items():
        if path.startswith('wiki/'):
            try:
                parser.leggi_testo(text, path)
            except (ValueError, TypeError, RecursionError):
                raise _located_error('preview_parse_failed', 'Frontmatter non analizzabile', path) from None
    try:
        base = parser.parse_documents(documents)
    except (ValueError, TypeError, RecursionError):
        raise ContractError('preview_parse_failed', 'Snapshot non analizzabile: controllare nomi, fonti e frontmatter') from None
    observed = [item[1] for item in base['entita'] if isinstance(item[1], str)]
    try:
        candidate, renames, changes = _patch(document, patch, observed)
    except ontology.OntologyError as error:
        raise ContractError(error.code, str(error)) from None
    after = ontology.parse(candidate)
    modified = dict(documents, **{'Wiki reference.md': candidate.decode('utf-8')})
    result = parser.parse_documents(modified)
    if len(result['relazioni']) > MAX_ITEMS or len(result['problem_details']) > MAX_ITEMS:
        raise ContractError('preview_limit', 'Troppi archi o violazioni per una preview completa')

    before_types = {item.name: item for item in document.types or ()}
    after_types = {item.name: item for item in after.types or ()}
    before_relations = {item.name: item for item in document.relations}
    after_relations = {item.name: item for item in after.relations}
    changed_types = {name for name in before_types.keys() | after_types.keys() if before_types.get(name) != after_types.get(name)}
    changed_relations = {name for name in before_relations.keys() | after_relations.keys() if before_relations.get(name) != after_relations.get(name)}
    type_counts, property_counts = Counter(), Counter()
    impacted, references, migrations = set(), [], []
    typed_links = {}
    for source, target, prop in base['tipizzate']:
        typed_links.setdefault((source, prop), []).append(target)
    bad_properties = {(item['page'], item['property']) for item in base['problem_details']}
    def reference(page, prop, target, kind):
        if len(references) >= MAX_ITEMS:
            raise ContractError('preview_limit', 'Troppi riferimenti per una preview completa')
        references.append({'page': page, 'property': prop, 'target': parser.bersaglio(target), 'kind': kind})

    usage = []
    for name, (fm, body) in sorted(base['pagine'].items()):
        path = 'wiki/' + name + '.md'
        if isinstance(fm.get('tipo'), str):
            type_counts[fm['tipo']] += 1
        properties = []
        for prop, value in fm.items():
            property_counts[str(prop)] += 1
            properties.append(str(prop))
            for raw in parser.valori(value):
                for target in parser.LINK.findall(raw):
                    reference(path, str(prop), target, 'frontmatter')
        for target in parser.LINK.findall(parser.CODICE.sub('', body)):
            reference(path, 'body', target, 'body')
        usage.append({'page': path, 'type': fm.get('tipo') if isinstance(fm.get('tipo'), str) else None, 'properties': sorted(properties),
                      'aliases': parser.valori(fm.get('aliases')), 'sources': parser.valori(fm.get('fonti'))})
        if (isinstance(fm.get('tipo'), str) and fm['tipo'] in changed_types) or changed_relations.intersection(properties):
            impacted.add(path)
        for rename in renames:
            old, new = rename['from'], rename['to']
            relevant = fm.get('tipo') == old if rename['kind'] == 'type' else old in fm
            if not relevant:
                continue
            prop = 'tipo' if rename['kind'] == 'type' else old
            collision = rename['kind'] == 'relation' and new in fm
            # Only simple block keys qualify; aliases, flow maps and duplicate keys require manual work.
            source = documents[path].lstrip('\ufeff')
            end = source.find('\n---', 3) if source.startswith('---') else -1
            source = source[3:end] if end >= 0 else ''
            simple = len(re.findall(r'^' + re.escape(prop) + r':[ \t]*', source, re.M)) == 1
            compatible = True
            if rename['kind'] == 'relation':
                rule = after_relations.get(new)
                for target_id in typed_links.get((name, old), ()):
                    target_type = base['pagine'][target_id][0].get('tipo')
                    compatible = (compatible and rule is not None
                        and parser.tipo_ammesso(set(rule.from_types), fm.get('tipo'), target_type)
                        and parser.tipo_ammesso(set(rule.to_types), target_type, fm.get('tipo')))
                compatible = compatible and (path, old) not in bad_properties
            migrations.append({'page': path, 'property': prop, 'kind': 'rename_' + rename['kind'],
                'from': old, 'to': new, 'deterministic': simple and not collision and compatible,
                'reason': 'Proprietà destinazione già presente' if collision else
                    'Struttura YAML da revisionare' if not simple else 'Vincoli o link incompatibili con la rinomina' if not compatible else 'Rinomina esatta da confermare; testo libero da revisionare',
                'requires_confirmation': True})
    for path in ('index.md', 'log.md', 'Wiki reference.md'):
        for target in parser.LINK.findall(documents.get(path, '')):
            reference(path, 'body', target, 'document')
    for migration in migrations:
        migration['migration_id'] = migration_id(migration)
        if migration['deterministic']:
            try:
                migration.update(describe(documents[migration['page']].encode('utf-8'), migration))
            except ContractError:
                migration.update(deterministic=False, reason='YAML complesso o ambiguo: migrazione manuale richiesta')
    entity_types = {item[0]: item[1] for item in base['entita']}
    changed_nodes = {name for name, tipo in entity_types.items() if isinstance(tipo, str) and tipo in changed_types}
    edges = [{'page': 'wiki/' + source + '.md', 'property': prop, 'target': target}
             for source, target, prop in sorted(base['relazioni'])
             if prop in changed_relations or source in changed_nodes or target in changed_nodes]
    impacted.update(edge['page'] for edge in edges)
    violations = list(result['problem_details'])
    for migration in migrations:
        if not migration['deterministic']:
            violations.append({'code': 'migration_manual', 'page': migration['page'],
                'property': migration['property'], 'target': migration['to'], 'reason': migration['reason']})
    shared = [entry.path for entry in snapshot.files if entry.path.startswith('.teseo/shared/')]
    if len(violations) + len(shared) > MAX_ITEMS:
        raise ContractError('preview_limit', 'Troppi record condivisi o violazioni per una preview completa')
    if candidate != document.source and shared:
        violations.extend({'code': 'shared_mapping_unavailable', 'page': path, 'property': 'shared_records',
                           'target': None, 'reason': 'Formato condiviso non ancora interpretabile: revisione/mapping del passo 5 richiesti'} for path in shared)
    for violation in violations:
        impacted.add(violation['page'])
    manual_review = []
    changed_names = changed_types | changed_relations
    if changed_names:
        names_pattern = re.compile(r'(?<![\w-])(?:' + '|'.join(re.escape(name) for name in sorted(changed_names)) + r')(?![\w-])', re.I)
        for path, text in sorted(documents.items()):
            if path.startswith('wiki/'):
                text = base['pagine'][path[5:-3]][1]
            elif path == 'Wiki reference.md':
                text = document.opaque_bytes().decode('utf-8')
            names = sorted(set(match.group(0) for match in names_pattern.finditer(text)))
            if names:
                manual_review.append({'page': path, 'property': 'body', 'names': names,
                    'reason': 'Occorrenze letterali nel testo libero: significato e sostituzioni da revisionare, nessuna riscrittura automatica'})
                impacted.add(path)
    added = sorted(after_relations.keys() - before_relations.keys())
    semantic = {'automatic_inference': False, 'new_relations': added,
        'requires_review': sorted(changed_relations),
        'message': 'Nessuna nuova inferenza automatica. Le euristiche di sintesi/domande sono codice del kit; rinomine, rimozioni e cambi di significato richiedono revisione.'}
    diff = ''.join(difflib.unified_diff(document.source.decode('utf-8').splitlines(keepends=True),
        candidate.decode('utf-8').splitlines(keepends=True), fromfile='Wiki reference.md (base)', tofile='Wiki reference.md (proposta)'))
    candidate_digest = hashlib.sha256(candidate).hexdigest()
    proposal_hash = content_hash({'base_content_digest': snapshot.digest, 'schema_digest': candidate_digest, 'patch': patch})
    return {'base_content_digest': snapshot.digest, 'content_revision': snapshot.digest, 'graph_generation': None,
        'base_schema_digest': document.digest, 'candidate_schema_digest': candidate_digest, 'proposal_hash': proposal_hash,
        'candidate_schema': html.escape(candidate.decode('utf-8'), quote=False), 'schema_diff': html.escape(diff, quote=False),
        'text_format': 'escaped_markdown', 'changes': changes,
        'model': {'types': [asdict(item) for item in after.types or ()], 'relations': [asdict(item) for item in after.relations]},
        'usage': {'types': dict(sorted(type_counts.items())), 'properties': dict(sorted(property_counts.items())),
                  'derived_types': dict(Counter(item[1] for item in base['entita'] if item[3] is None)), 'pages': usage},
        'impacted_pages': sorted(impacted), 'impacted_edges': edges, 'references': references,
        'shared_records': shared, 'violations': violations, 'migration_suggestions': migrations, 'manual_review': manual_review,
        'schema_only_valid': not violations, 'requires_migration': bool(violations or migrations),
        'requires_confirmation': True, 'apply_available': False, 'semantic_capabilities': semantic,
        'analysis_complete': True}


class PreviewService:
    """Cache di sessione limitata: niente journal, lock persistente o scritture vault."""
    def __init__(self, registry, capacity=16, ttl=900):
        self.registry, self.capacity, self.ttl = registry, capacity, ttl
        self._cache = {}
        self._lock = threading.Lock()
        self._slots = threading.BoundedSemaphore(2)

    def preview(self, vault_id, body):
        _fields(body, ('base_content_digest', 'idempotency_key', 'patch'))
        if (not isinstance(body['base_content_digest'], str) or not re.fullmatch('[0-9a-f]{64}', body['base_content_digest'])
                or not isinstance(body['idempotency_key'], str) or not re.fullmatch('[A-Za-z0-9_-]{8,128}', body['idempotency_key'])
                or not isinstance(body['patch'], list) or not 1 <= len(body['patch']) <= 64):
            raise ContractError('invalid_payload', 'Richiesti digest, chiave idempotente e 1–64 operazioni')
        if not self._slots.acquire(blocking=False):
            raise ContractError('preview_busy', 'Due preview già attive; riprovare')
        try:
            root = self.registry.root(vault_id)
            snapshot = capture_snapshot(root)
            if snapshot.digest != body['base_content_digest']:
                raise ContractError('preview_stale', 'Contenuti cambiati: rileggere la revisione e creare una nuova preview')
            key = (vault_id, body['idempotency_key'])
            request = content_hash(body)
            # Serialize cache reservation/computation to make concurrent retries exactly idempotent.
            with self._lock:
                now = time.monotonic()
                self._cache = {key: value for key, value in self._cache.items() if value[0] > now}
                if key in self._cache:
                    _, digest, record = self._cache[key]
                    if digest != request:
                        raise ContractError('idempotency_conflict', 'Chiave già usata con payload diverso')
                    snapshot.assert_unchanged(root)
                    return deepcopy(record)
                if len(self._cache) >= self.capacity:
                    raise ContractError('preview_limit', 'Cache preview piena; attendere la scadenza di sessione')
                record = analyze(snapshot, body['patch'])
                snapshot.assert_unchanged(root)
                self.registry.root(vault_id)  # Recheck bound identity after the analysis.
                record.update(preview_id=str(uuid4()), expires_at=int(time.time()) + self.ttl,
                              ttl_seconds=self.ttl, idempotency_scope='service_session')
                if len(json.dumps(record, ensure_ascii=True).encode('utf-8')) > MAX_RESPONSE:
                    raise ContractError('preview_limit', 'Risultato oltre 2 MiB; ridurre la patch o il vault')
                self._cache[key] = (time.monotonic() + self.ttl, request, record)
                return deepcopy(record)
        finally:
            self._slots.release()

    def proposal(self, vault_id, preview_id, proposal_hash):
        with self._lock:
            for (identifier, _), (expires, _, record) in self._cache.items():
                if identifier == vault_id and record['preview_id'] == preview_id:
                    if expires <= time.monotonic() or record['proposal_hash'] != proposal_hash:
                        break
                    return deepcopy(record)
        raise ContractError('preview_stale', 'Preview assente, scaduta o hash diverso; generare una nuova preview')
