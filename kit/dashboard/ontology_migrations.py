"""Migrazioni conservative su byte: mai dump YAML o sostituzioni nel testo libero."""
import difflib
import hashlib
import html
import re

from .contracts import ContractError, content_hash
from .read_api import _parser


def migration_id(item):
    return content_hash({key: item[key] for key in ('page', 'kind', 'from', 'to')})


def migrate(data, item):
    parser = _parser()
    text = data.decode('utf-8')
    fm, _ = parser.leggi_testo(text, item['page'])
    source = text.lstrip('\ufeff')
    end = source.find('\n---', 3) if source.startswith('---') else -1
    if end < 0:
        raise ContractError('migration_manual', 'Frontmatter non riconosciuto')
    header = source[3:end]
    prop = 'tipo' if item['kind'] == 'rename_type' else item['from']
    pattern = re.compile(r'^' + re.escape(prop) + r':[^\r\n]*', re.M)
    matches = list(pattern.finditer(header))
    if len(matches) != 1 or re.search(r'^[^\r\n]*[&*]|^<<:', header, re.M):
        raise ContractError('migration_manual', 'Chiavi duplicate, anchor o YAML complesso: revisione manuale')
    match = matches[0]
    if item['kind'] == 'rename_relation':
        if item['to'] in fm:
            raise ContractError('migration_collision', 'Proprietà destinazione già presente')
        replacement = item['to'] + match[0][len(prop):]
    elif item['kind'] == 'rename_type':
        if fm.get('tipo') != item['from']:
            raise ContractError('migration_manual', 'Tipo base non corrispondente')
        value = re.fullmatch(r'tipo:([ \t]*)([\w-]+|"[\w-]+"|\'[\w-]+\')([ \t]*(?:#.*)?)', match[0])
        if not value:
            raise ContractError('migration_manual', 'Tipo scalare complesso: revisione manuale')
        token = value[2]
        replacement = 'tipo:' + value[1] + (token[0] + item['to'] + token[-1] if token[0] in "\"'" else item['to']) + value[3]
    else:
        raise ContractError('migration_manual', 'Migrazione non supportata')
    at = len(text) - len(source) + 3
    candidate = text[:at + match.start()] + replacement + text[at + match.end():]
    checked, _ = parser.leggi_testo(candidate, item['page'])
    expected = dict(fm)
    if item['kind'] == 'rename_relation':
        expected[item['to']] = expected.pop(item['from'])
    else:
        expected['tipo'] = item['to']
    if checked != expected:
        raise ContractError('migration_manual', 'Migrazione non rappresentabile senza ambiguità')
    return candidate.encode('utf-8')


def describe(data, item):
    candidate = migrate(data, item)
    diff = ''.join(difflib.unified_diff(data.decode('utf-8').splitlines(keepends=True),
        candidate.decode('utf-8').splitlines(keepends=True), fromfile=item['page'] + ' (base)', tofile=item['page'] + ' (proposta)'))
    return {'migration_id': migration_id(item), 'candidate_sha256': hashlib.sha256(candidate).hexdigest(),
            'diff': html.escape(diff, quote=False), 'text_format': 'escaped_markdown'}
