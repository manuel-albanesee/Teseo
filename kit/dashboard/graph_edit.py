"""Editor del grafo: modifiche atomiche al frontmatter di una pagina, con preview e candidato già validato.

Sono modifiche di byte conservative (stesso criterio di ontology_migrations): si riscrive solo il blocco della chiave
toccata e il risultato deve riparsare esattamente nel frontmatter atteso, altrimenti la modifica è manuale.
Il corpo della pagina non si tocca mai. Nessuna scrittura sul vault: l'apply passa dal journal (ApplyService).
"""
from copy import deepcopy
from datetime import date
import difflib
import hashlib
import html
import json
import re
import threading
import time
from uuid import uuid4

import yaml

from .contracts import ContractError, content_hash
from .ontology_preview import _documents, _fields
from .read_api import _parser
from .storage import capture_snapshot

MAX_OPERATIONS = 16
MAX_RESPONSE = 2 * 1024 * 1024
MAX_ITEMS = 50
MAX_EVIDENCE = 500
CONFIDENCE = ('alta', 'media', 'bassa')
RESERVED = frozenset({'tipo', 'tags', 'fonti', 'aggiornato', 'aliases', 'relazioni_dettaglio', 'menziona', 'documentato_in'})
_PLAIN = re.compile(r'[A-Za-z_À-￿][\w\-/À-￿]*')
_WORDS = frozenset({'true', 'false', 'null', 'yes', 'no', 'on', 'off', 'y', 'n', '~'})
_TEXT = re.compile(r'[^\x00-\x1f\x7f]+')
_TOP = re.compile(r'^[^\s#\-]')
_KEY = re.compile(r'^([^\s#\-"\'][^:\n]*):(?:[ \t]|$)')


def _quote(text):
    return json.dumps(text, ensure_ascii=False)


def _word(text):
    return text if _PLAIN.fullmatch(text) and text.lower() not in _WORDS else _quote(text)


def _strings(value, label):
    if (not isinstance(value, list) or len(value) > MAX_ITEMS or len(set(value)) != len(value)
            or any(not isinstance(item, str) or not item.strip() or len(item) > 120 or not _TEXT.fullmatch(item)
                   or item != item.strip() for item in value)):
        raise ContractError('edit_invalid', f'{label}: attesa una lista senza duplicati di al più {MAX_ITEMS} testi brevi')
    return list(value)


def _render(key, value):
    if key == 'relazioni_dettaglio':
        lines = [key + ':']
        for target, detail in value.items():
            parts = ([f"confidenza: {detail['confidenza']}"] if detail.get('confidenza') else []) + (
                [f"evidenza: {_quote(detail['evidenza'])}"] if detail.get('evidenza') else [])
            lines.append(f'  {_quote(target)}: {{{", ".join(parts)}}}')
        return lines
    if key == 'aggiornato':
        return [f'aggiornato: {value.isoformat()}']
    if key == 'tipo':
        return [f'tipo: {_word(value)}']
    if key == 'tags':
        return [f'tags: [{", ".join(_word(item) for item in value)}]']
    if key == 'aliases':
        return [f'aliases: [{", ".join(_quote(item) for item in value)}]']
    if isinstance(value, str):
        return [f'{key}: {_quote(value)}']
    return [f'{key}: [{", ".join(_quote(item) for item in value)}]']


def _has_anchors(header):
    """True se il YAML ha anchor, alias o merge key (cercati negli eventi del parser, non nel testo: «R&D» è un valore)."""
    try:
        for event in yaml.parse(header):
            if isinstance(event, yaml.AliasEvent) or getattr(event, 'anchor', None):
                return True
            if isinstance(event, yaml.ScalarEvent) and event.value == '<<' and event.implicit[0]:
                return True
    except yaml.YAMLError:
        return True
    return False


def _splice(text, changes):
    """Sostituisce, toglie o aggiunge i soli blocchi top-level di `changes` ({chiave: righe | None})."""
    nl = '\r\n' if '\r\n' in text else '\n'
    source = text.lstrip('﻿')
    bom = text[:len(text) - len(source)]
    end = source.find(nl + '---', 3) if source.startswith('---') else -1
    if end < 0:
        raise ContractError('edit_manual', 'Frontmatter non riconosciuto')
    lines = source[3:end].split(nl)
    blocks = [[None, []]]  # [chiave, righe]; il primo blocco raccoglie commenti e righe vuote prima della prima chiave
    for line in lines[1:]:
        if _TOP.match(line):
            match = _KEY.match(line)
            blocks.append([match.group(1).strip() if match else '?', [line]])
        else:
            blocks[-1][1].append(line)
    if any(key == '?' for key, _ in blocks) or len({key for key, _ in blocks[1:]}) != len(blocks) - 1:
        raise ContractError('edit_manual', 'Chiavi duplicate o non riconosciute nel frontmatter: revisione manuale')
    if _has_anchors(nl.join(lines)):
        raise ContractError('edit_manual', 'Anchor, alias o merge key YAML: revisione manuale')
    for key, new in changes.items():
        index = next((n for n, block in enumerate(blocks) if block[0] == key), None)
        if index is None:
            if new is None:
                continue
            tail = []  # le righe vuote finali restano in coda, dopo la nuova chiave
            while len(blocks[-1][1]) > (1 if blocks[-1][0] else 0) and not blocks[-1][1][-1].strip():
                tail.insert(0, blocks[-1][1].pop())
            blocks.append([key, list(new) + tail])
            continue
        body = blocks[index][1]
        tail = []
        while len(body) > 1 and (not body[-1].strip() or body[-1].lstrip().startswith('#')):
            tail.insert(0, body.pop())
        blocks[index][1] = (list(new) if new is not None else []) + tail
    out = [lines[0]]
    for _, block in blocks:
        out.extend(block)
    return bom + '---' + nl.join(out) + source[end:]


def edit_page(text, name, vocabulary, pages, operations, today):
    """Nuovo testo della pagina `name` dopo le operazioni, oppure ContractError con codice edit_*."""
    parser = _parser()
    if not isinstance(operations, list) or not 1 <= len(operations) <= MAX_OPERATIONS:
        raise ContractError('invalid_payload', f'Richieste 1–{MAX_OPERATIONS} operazioni')
    fm, _ = parser.leggi_testo(text, name)
    expected = deepcopy(fm)

    def targets(value):
        return [(raw, parser.bersaglio(link)) for raw in parser.valori(value) for link in parser.LINK.findall(raw)]

    def relation_values(value):
        if value is not None and any(not isinstance(item, str) for item in (value if isinstance(value, list) else [value])):
            raise ContractError('edit_manual', 'Valore della relazione non rappresentabile: revisione manuale')
        return [str(item) for item in parser.valori(value)]

    def store(key, values):
        if values:
            expected[key] = values[0] if len(values) == 1 else values
        else:
            expected.pop(key, None)

    for operation in operations:
        if not isinstance(operation, dict) or not isinstance(operation.get('op'), str):
            raise ContractError('invalid_payload', 'Ogni operazione richiede il campo op')
        kind = operation['op']
        if kind in ('add_relation', 'remove_relation'):
            _fields(operation, ('op', 'relation', 'target'))
            relation, target = operation['relation'], operation['target']
            if not isinstance(relation, str) or not isinstance(target, str):
                raise ContractError('invalid_payload', 'relation e target devono essere testi')
            if vocabulary is None:
                raise ContractError('edit_manual', 'Vocabolario delle relazioni non definito in Wiki reference.md')
            if relation not in vocabulary or relation in RESERVED:
                raise ContractError('edit_unknown_relation', f"Relazione '{relation}' non nel vocabolario")
            current = relation_values(expected.get(relation))
            known = [name_ for _, name_ in targets(current)]
            if kind == 'add_relation':
                if target not in pages or target == name:
                    raise ContractError('edit_unknown_target', f"'{target}' non è un'altra pagina del vault")
                if target in known:
                    raise ContractError('edit_duplicate', f"{name} —{relation}→ {target} esiste già")
                store(relation, current + [f'[[{target}]]'])
            else:
                keep = [raw for raw in current if [n for _, n in targets(raw)] != [target]]
                if len(keep) == len(current):
                    raise ContractError('edit_missing', f"{name} —{relation}→ {target} non esiste")
                if any(target in [n for _, n in targets(raw)] for raw in keep):
                    raise ContractError('edit_manual', 'Un valore con più link: revisione manuale')
                store(relation, keep)
                detail = expected.get('relazioni_dettaglio')
                if relation == 'causa' and isinstance(detail, dict):
                    for key in [k for k in detail if parser.bersaglio((parser.LINK.findall(str(k)) or [''])[0]) == target]:
                        del detail[key]
                    if not detail:
                        expected.pop('relazioni_dettaglio')
        elif kind in ('set_aliases', 'set_tags'):
            field = 'aliases' if kind == 'set_aliases' else 'tags'
            _fields(operation, ('op', field))
            values = _strings(operation[field], field)
            if values or field == 'tags':
                expected[field] = values
            else:
                expected.pop(field, None)
        elif kind == 'set_tipo':
            _fields(operation, ('op', 'tipo'))
            if not isinstance(operation['tipo'], str) or not re.fullmatch(r'[\w-]{1,64}', operation['tipo']):
                raise ContractError('edit_invalid', 'tipo atteso come parola breve')
            expected['tipo'] = operation['tipo']
        elif kind == 'set_relation_detail':
            _fields(operation, ('op', 'target', 'confidenza', 'evidenza'))
            target, confidence, evidence = operation['target'], operation['confidenza'], operation['evidenza']
            if confidence is not None and confidence not in CONFIDENCE:
                raise ContractError('edit_invalid', 'confidenza attesa fra ' + ', '.join(CONFIDENCE))
            if evidence is not None and (not isinstance(evidence, str) or not evidence.strip() or len(evidence) > MAX_EVIDENCE
                                         or not _TEXT.fullmatch(evidence)):
                raise ContractError('edit_invalid', f'evidenza attesa come testo breve su una riga (massimo {MAX_EVIDENCE})')
            if target not in [n for _, n in targets(relation_values(expected.get('causa')))]:
                raise ContractError('edit_missing', f"{name} —causa→ {target} non esiste: dichiarare prima la causa")
            detail = expected.get('relazioni_dettaglio') or {}
            if not isinstance(detail, dict):
                raise ContractError('edit_manual', 'relazioni_dettaglio non è una mappa: revisione manuale')
            key = next((k for k in detail if parser.bersaglio((parser.LINK.findall(str(k)) or [''])[0]) == target), f'[[{target}]]')
            entry = {k: v for k, v in (('confidenza', confidence), ('evidenza', evidence)) if v is not None}
            if entry:
                detail[key] = entry
            else:
                detail.pop(key, None)
            if detail:
                expected['relazioni_dettaglio'] = detail
            else:
                expected.pop('relazioni_dettaglio', None)
        else:
            raise ContractError('invalid_patch', 'Operazione di modifica non supportata')

    if expected == fm:
        raise ContractError('edit_noop', 'Le operazioni non cambiano la pagina')
    if 'aggiornato' in fm:
        expected['aggiornato'] = today
    changes = {key: (_render(key, expected[key]) if key in expected else None)
               for key in dict.fromkeys([*fm, *expected]) if fm.get(key) != expected.get(key)}  # ordine stabile: nuove chiavi nell'ordine delle operazioni
    candidate = _splice(text, changes)
    checked, _ = parser.leggi_testo(candidate, name)
    if checked != expected:
        raise ContractError('edit_manual', 'Modifica non rappresentabile senza ambiguità nel frontmatter: revisione manuale')
    return candidate


def _parsed(documents):
    try:
        return _parser().parse_documents(documents)
    except (ValueError, TypeError, RecursionError):
        raise ContractError('preview_parse_failed', 'Vault non analizzabile: correggere frontmatter YAML o nomi di pagina in conflitto') from None


def _key(problem):
    return (problem['code'], problem['page'], problem['property'], problem['target'])


def analyze(snapshot, page, operations, today):
    """Preview deterministica: diff del frontmatter, candidato e problemi del grafo candidato (nessuna scrittura).

    `valid` richiede un candidato senza alcun problema: il grafo si ricostruisce solo da un vault valido, quindi anche un
    problema preesistente altrove impedisce l'apply. I problemi sono però separati in nuovi (introdotti da questa modifica)
    e preesistenti (già presenti nel vault) perché il messaggio dica che cosa correggere."""
    path = f'wiki/{page}.md'
    documents = _documents(snapshot)
    if path not in documents:
        raise ContractError('node_missing', 'Pagina non presente nel vault')
    base = _parsed(documents)
    try:
        candidate = edit_page(documents[path], page, base['vocabolario'], set(base['pagine']), operations, today)
    except (ValueError, TypeError, RecursionError):
        raise ContractError('preview_parse_failed', 'Frontmatter della pagina non analizzabile') from None
    result = _parsed(dict(documents, **{path: candidate}))
    known = {_key(item) for item in base['problem_details']}
    new = [item for item in result['problem_details'] if _key(item) not in known]
    old = [item for item in result['problem_details'] if _key(item) in known]
    diff = ''.join(difflib.unified_diff(documents[path].splitlines(keepends=True), candidate.splitlines(keepends=True),
                                        fromfile=path + ' (base)', tofile=path + ' (proposta)'))
    data = candidate.encode('utf-8')
    risk = None
    if new:
        risk = 'La modifica introduce problemi nel grafo: correggerla prima di applicare'
    elif old:
        risk = 'Il vault ha problemi preesistenti, anche fuori da questa pagina: il grafo non si ricostruisce finché non sono corretti'
    record = {'page': page, 'path': path, 'operations': operations, 'base_content_digest': snapshot.digest,
              'candidate_sha256': hashlib.sha256(data).hexdigest(), 'valid': not result['problem_details'],
              'problems': (new + old)[:200], 'new_problems': len(new), 'preexisting_problems': len(old),
              'problems_truncated': len(new) + len(old) > 200,
              'diff': html.escape(diff, quote=False), 'text_format': 'escaped_markdown',
              'relations_after': sorted([s, t, r] for s, t, r in result['relazioni'] if s == page and r not in ('menziona', 'documentato_in')),
              'risk': risk}
    record['proposal_hash'] = content_hash({key: record[key] for key in ('path', 'base_content_digest', 'candidate_sha256')})
    return record, data


class GraphEditService:
    """Cache di sessione limitata di proposte: niente journal, lock persistente o scritture nel vault."""
    def __init__(self, registry, capacity=16, ttl=900, clock=date.today):
        self.registry, self.capacity, self.ttl, self.clock = registry, capacity, ttl, clock
        self._cache = {}
        self._lock = threading.Lock()
        self._slots = threading.BoundedSemaphore(2)

    def preview(self, vault_id, node_id, body):
        _fields(body, ('base_content_digest', 'idempotency_key', 'operations'))
        if (not isinstance(body['base_content_digest'], str) or not re.fullmatch('[0-9a-f]{64}', body['base_content_digest'])
                or not isinstance(body['idempotency_key'], str) or not re.fullmatch('[A-Za-z0-9_-]{8,128}', body['idempotency_key'])):
            raise ContractError('invalid_payload', 'Richiesti digest e chiave idempotente validi')
        if not isinstance(node_id, str) or not node_id or '/' in node_id or '\\' in node_id or node_id in ('.', '..'):
            raise ContractError('invalid_node', 'ID nodo non valido')
        if not self._slots.acquire(blocking=False):
            raise ContractError('preview_busy', 'Due preview già attive; riprovare')
        try:
            root = self.registry.root(vault_id)
            snapshot = capture_snapshot(root)
            if snapshot.digest != body['base_content_digest']:
                raise ContractError('preview_stale', 'Contenuti cambiati: rileggere la revisione e creare una nuova preview')
            key, request = (vault_id, body['idempotency_key']), content_hash({'node': node_id, **body})
            cached = self._reserve(key, request)
            if cached is not None:
                snapshot.assert_unchanged(root)
                return cached
            record, data = analyze(snapshot, node_id, body['operations'], self.clock())  # fuori dal lock: il parse può durare secondi
            snapshot.assert_unchanged(root)
            self.registry.root(vault_id)  # identità del vault ricontrollata dopo l'analisi
            record.update(preview_id=str(uuid4()), expires_at=int(time.time()) + self.ttl, ttl_seconds=self.ttl)
            if len(json.dumps(record, ensure_ascii=True).encode('utf-8')) > MAX_RESPONSE:
                raise ContractError('preview_limit', 'Risultato oltre 2 MiB; ridurre le operazioni o il vault')
            with self._lock:
                if key in self._cache and self._cache[key][1] == request:  # un retry identico ha vinto la corsa: stesso esito
                    return deepcopy(self._cache[key][2])
                self._cache[key] = (time.monotonic() + self.ttl, request, record, data)
            return deepcopy(record)
        finally:
            self._slots.release()

    def _reserve(self, key, request):
        """Record già in cache per lo stesso payload; conflitto se la chiave porta un payload diverso; altrimenti None."""
        with self._lock:
            now = time.monotonic()
            self._cache = {k: v for k, v in self._cache.items() if v[0] > now}
            if key in self._cache:
                if self._cache[key][1] != request:
                    raise ContractError('idempotency_conflict', 'Chiave già usata con payload diverso')
                return deepcopy(self._cache[key][2])
            if len(self._cache) >= self.capacity:
                raise ContractError('preview_limit', 'Cache preview piena; attendere la scadenza di sessione')
            return None

    def proposal(self, vault_id, preview_id, proposal_hash):
        """(record, byte della pagina candidata) di una preview valida e non scaduta."""
        with self._lock:
            for (identifier, _), (expires, _, record, data) in self._cache.items():
                if identifier == vault_id and record['preview_id'] == preview_id:
                    if expires <= time.monotonic() or record['proposal_hash'] != proposal_hash:
                        break
                    return deepcopy(record), data
        raise ContractError('preview_stale', 'Preview assente, scaduta o hash diverso; generare una nuova preview')
