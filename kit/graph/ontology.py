"""Ontologia Markdown lossless: parser e proposte pure, nessun accesso al filesystem.

Grammatica volutamente limitata: sezioni ATX h2, una tabella contigua per sezione,
2 colonne per i tipi e 3/5 per le relazioni. Contenuto ambiguo resta manuale.
Gli offset sono byte UTF-8; il serializer sostituisce solo tabelle riconosciute.
"""
from dataclasses import dataclass
import hashlib
import re
import unicodedata

MAX_BYTES = 2 * 1024 * 1024
MAX_ROWS = 2048
SPECIAL = frozenset({'tipo', 'tags', 'fonti', 'aggiornato', 'aliases', 'relazioni_dettaglio', 'menziona', 'documentato_in'})
WILDCARDS = frozenset({'qualsiasi', 'stesso tipo'})
HEADINGS = {'Tipi ammessi': 'types', 'Relazioni tipizzate': 'relations'}


class OntologyError(ValueError):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class Span:
    start: int
    end: int


@dataclass(frozen=True)
class Issue:
    code: str
    message: str
    line: int | None = None
    severity: str = 'error'


@dataclass(frozen=True)
class TypeDef:
    name: str
    description: str = ''


@dataclass(frozen=True)
class Relation:
    name: str
    from_types: tuple[str, ...]
    to_types: tuple[str, ...]
    meaning: str = ''
    example: str = ''
    direction: str = 'source_to_target'


@dataclass(frozen=True)
class Ontology:
    source: bytes
    types: tuple[TypeDef, ...] | None
    relations: tuple[Relation, ...]
    types_span: Span | None
    relations_span: Span | None
    opaque_sections: tuple[Span, ...]
    issues: tuple[Issue, ...]
    catalog_present: bool
    convention_types: tuple[str, ...]
    adoption_offset: int | None

    @property
    def digest(self):
        return hashlib.sha256(self.source).hexdigest()

    @property
    def source_spans(self):
        return {key: span for key, span in (('types', self.types_span), ('relations', self.relations_span)) if span}

    @property
    def structurally_editable(self):
        return self.relations_span is not None and not any(issue.severity == 'error' for issue in self.issues)

    @property
    def editable(self):
        return self.types is not None and self.structurally_editable

    @property
    def vocabulary(self):
        if self.relations_span is None and not self.catalog_present:
            return None
        return {item.name: (set(item.from_types), set(item.to_types)) for item in self.relations}

    def opaque_bytes(self):
        return b''.join(self.source[span.start:span.end] for span in self.opaque_sections)


@dataclass(frozen=True)
class CatalogProposal:
    base_digest: str
    candidate: bytes
    types: tuple[TypeDef, ...]
    requires_confirmation: bool = True


def _name(value):
    return (isinstance(value, str) and 0 < len(value) <= 64 and value[0].isalpha()
            and all(char.isalnum() or char in '_-' for char in value)
            and unicodedata.normalize('NFC', value) == value)


def _text(value):
    return (isinstance(value, str) and len(value) <= 4096
            and not any(ord(char) < 32 or 0xD800 <= ord(char) <= 0xDFFF for char in value))


def validate(types, relations):
    """Validazione del modello; impatto sulle pagine demandato al builder/preview."""
    if (types is not None and not types) or len(types or ()) > MAX_ROWS or len(relations) > MAX_ROWS:
        return (Issue('catalog_limit', 'Catalogo vuoto o oltre 2048 righe'),)
    issues, seen = [], set()
    for item in types or ():
        if not isinstance(item, TypeDef) or not _name(item.name) or item.name in WILDCARDS or not _text(item.description):
            issues.append(Issue('invalid_type', 'Nome o descrizione tipo non rappresentabile nella tabella v1'))
            continue
        if item.name.casefold() in seen:
            issues.append(Issue('duplicate_type', 'Tipo duplicato: ' + item.name))
        seen.add(item.name.casefold())
    known = {item.name for item in types or () if isinstance(item, TypeDef) and isinstance(item.name, str)}
    seen = set()
    for item in relations:
        if (not isinstance(item, Relation) or not _name(item.name) or not _text(item.meaning)
                or not _text(item.example)):
            issues.append(Issue('invalid_relation', 'Nome o testo relazione non rappresentabile nella tabella v1'))
            continue
        if item.name.casefold() in seen:
            issues.append(Issue('duplicate_relation', 'Relazione duplicata: ' + item.name))
        seen.add(item.name.casefold())
        if item.name.casefold() in SPECIAL:
            issues.append(Issue('reserved_relation', 'Proprietà speciale o arco derivato riservato: ' + item.name))
        if item.direction != 'source_to_target':
            issues.append(Issue('invalid_direction', 'Inversione automatica non consentita: ' + item.name))
        for allowed in (item.from_types, item.to_types):
            if (not isinstance(allowed, tuple) or not 0 < len(allowed) <= 128
                    or any(not isinstance(name, str) or (name not in WILDCARDS and not _name(name)) for name in allowed)):
                issues.append(Issue('invalid_constraint', 'Vincolo tipi non valido: ' + item.name))
                continue
            if len(set(allowed)) != len(allowed):
                issues.append(Issue('duplicate_constraint', 'Tipo ripetuto nel vincolo: ' + item.name))
            if types is not None:
                for name in allowed:
                    if name not in WILDCARDS and name not in known:
                        issues.append(Issue('unknown_type', item.name + ': tipo non dichiarato: ' + name))
    return tuple(issues)


def _cells(line):
    value = line.strip()
    if not value.startswith('|') or not value.endswith('|'):
        raise ValueError('Richiesti delimitatori iniziale e finale della tabella')
    cells, current, index = [], [], 1
    while index < len(value) - 1:
        char = value[index]
        if char == '\\' and index + 1 < len(value) - 1 and value[index + 1] in '|\\':
            current.append(value[index + 1])
            index += 2
            continue
        if char == '|':
            cells.append(''.join(current).strip())
            current = []
        else:
            current.append(char)
        index += 1
    return cells + [''.join(current).strip()]


def _identifier(cell):
    if cell.startswith('`') and cell.endswith('`'):
        return cell[1:-1]
    return cell


def _lines(source):
    """Linee visibili e offset originali; fence, HTML e commenti sono dati opachi."""
    result, conventions = [], set()
    offset, fence, comment, html = 0, None, False, None
    for number, raw in enumerate(source.splitlines(keepends=True), 1):
        text = raw.decode('utf-8').rstrip('\r\n')
        if number == 1:
            text = text.removeprefix('\ufeff')
        visible = text
        if fence:
            if re.fullmatch(r' {0,3}' + re.escape(fence[0]) + '{' + str(fence[1]) + r',}[ \t]*', text):
                fence = None
            elif fence[2] in ('yaml', 'yml'):
                match = re.fullmatch(r'tipo:[ \t]*([^#]+)(?:#.*)?', text)
                if match and '|' in match[1]:
                    names = tuple(name.strip() for name in match[1].split('|'))
                    if all(_name(name) for name in names):
                        conventions.add(names)
            visible = None
        elif html:
            if re.search(r'</' + re.escape(html) + r'\s*>', text, re.I):
                html = None
            visible = None
        else:
            # Mask inline comments for headings, but refuse to rewrite comment-bearing rows.
            pieces, rest = [], text
            while rest:
                if comment:
                    end = rest.find('-->')
                    if end < 0:
                        rest = ''
                    else:
                        comment, rest = False, rest[end + 3:]
                else:
                    start = rest.find('<!--')
                    if start < 0:
                        pieces.append(rest)
                        rest = ''
                    else:
                        pieces.append(rest[:start])
                        comment, rest = True, rest[start + 4:]
            visible = ''.join(pieces)
            opening = re.match(r' {0,3}(`{3,}|~{3,})(.*)$', visible)
            block = re.match(r' {0,3}<([a-zA-Z][\w-]*)\b[^>]*>', visible)
            if opening:
                fence = (opening[1][0], len(opening[1]), opening[2].strip().lower())
                visible = None
            elif block and block[1].lower() in {'script', 'style', 'pre', 'div', 'table', 'section',
                    'details', 'article', 'aside', 'blockquote', 'p', 'ul', 'ol', 'li', 'header',
                    'footer', 'main', 'nav', 'form', 'figure', 'address', 'iframe'}:
                tag = block[1].lower()
                if tag not in ('img', 'br', 'hr', 'input', 'meta', 'link') and not re.search(r'</' + re.escape(tag) + r'\s*>', visible, re.I) and not visible.rstrip().endswith('/>'):
                    html = tag
                visible = None
            elif text.startswith(('    ', '\t')):
                visible = None
        result.append((offset, offset + len(raw), visible, text))
        offset += len(raw)
    return result, conventions


def parse(source):
    if isinstance(source, str):
        try:
            source = source.encode('utf-8')
        except UnicodeError:
            raise OntologyError('ontology_encoding', 'Ontologia UTF-8 non valida') from None
    if not isinstance(source, bytes) or len(source) > MAX_BYTES:
        raise OntologyError('ontology_size', 'Ontologia richiesta come byte UTF-8, massimo 2 MiB')
    try:
        lines, conventions = _lines(source)
    except UnicodeError:
        raise OntologyError('ontology_encoding', 'Ontologia UTF-8 non valida') from None
    headings, sections, issues = [], {}, []
    catalog_present = False
    for index, (_, _, visible, _) in enumerate(lines):
        if visible is None:
            continue
        heading = re.fullmatch(r' {0,3}(#{1,6})[ \t]+(.*?)(?:[ \t]+#+)?[ \t]*', visible)
        if heading:
            level, title = len(heading[1]), heading[2]
            headings.append((index, level, title))
            if title in HEADINGS:
                catalog_present |= title == 'Tipi ammessi'
                if level != 2:
                    issues.append(Issue('noncanonical_heading', 'La sezione ' + title + ' richiede un titolo h2', index + 1))
        elif visible.strip() in HEADINGS and index + 1 < len(lines) and re.fullmatch(r' {0,3}(?:=+|-+)[ \t]*', lines[index + 1][2] or ''):
            catalog_present |= visible.strip() == 'Tipi ammessi'
            issues.append(Issue('noncanonical_heading', 'Titolo Setext non modificabile automaticamente', index + 1))
    # Compute boundaries once: a large document with many headings must stay linear.
    ends, boundary = {}, len(lines)
    for index, level, _ in reversed(headings):
        ends[index] = boundary
        if level <= 2:
            boundary = index
    for index, level, title in headings:
        if level != 2 or title not in HEADINGS:
            continue
        end = ends[index]
        key = HEADINGS[title]
        if key in sections:
            issues.append(Issue('duplicate_section', 'Sezione duplicata: ' + title, index + 1))
        else:
            sections[key] = (index, end)
    parsed, spans = {}, {}
    for key, (start, end) in sections.items():
        rows = [index for index in range(start + 1, end) if lines[index][2] is not None and lines[index][2].strip().startswith('|')]
        if not rows:
            issues.append(Issue('table_missing', 'Tabella non riconosciuta: ' + key, start + 1,
                                'error' if catalog_present else 'warning'))
            continue
        if rows != list(range(rows[0], rows[-1] + 1)):
            issues.append(Issue('ambiguous_table', 'Tabelle separate o commenti tra le righe: ' + key, rows[0] + 1))
            continue
        try:
            table = [_cells(lines[index][2]) for index in rows]
            header = [cell.casefold().replace(' (tipo)', '') for cell in table[0]]
            expected = len(header)
            if (key == 'types' and header not in (['tipo', 'descrizione'], ['nome', 'descrizione'])) or (key == 'relations' and (expected not in (3, 5) or header[0] not in ('nome', 'relazione') or header[1:3] != ['da', 'a'] or (expected == 5 and header[3:] != ['significato', 'esempio']))):
                raise ValueError('Intestazione tabella non riconosciuta')
            if len(table) < 2 or len(table[1]) != expected or not all(re.fullmatch(r':?-{3,}:?', cell) for cell in table[1]):
                raise ValueError('Separatore tabella non valido')
            if len(table) - 2 > MAX_ROWS or any(len(row) != expected for row in table):
                raise ValueError('Numero colonne o righe non supportato')
            if any('<!--' in lines[index][3] or '-->' in lines[index][3] for index in rows):
                raise ValueError('Commento nella tabella: usare editing manuale')
            if key == 'types':
                parsed[key] = tuple(TypeDef(_identifier(row[0]), row[1]) for row in table[2:])
            else:
                parsed[key] = tuple(Relation(_identifier(row[0]), tuple(item.strip() for item in row[1].split(',')),
                    tuple(item.strip() for item in row[2].split(',')), row[3] if expected == 5 else '', row[4] if expected == 5 else '') for row in table[2:])
            spans[key] = Span(lines[rows[0]][0], lines[rows[-1]][1])
        except ValueError as error:
            issues.append(Issue('unrecognized_table', str(error), rows[0] + 1))
    types, relations = parsed.get('types'), parsed.get('relations', ())
    issues.extend(validate(types, relations))
    if len(conventions) > 1:
        issues.append(Issue('ambiguous_conventions', 'Più elenchi tipo diversi negli esempi YAML', severity='warning'))
    opaque, offset = [], 0
    for span in sorted(spans.values(), key=lambda span: span.start):
        if offset < span.start:
            opaque.append(Span(offset, span.start))
        offset = span.end
    if offset < len(source):
        opaque.append(Span(offset, len(source)))
    return Ontology(source, types, relations, spans.get('types'), spans.get('relations'), tuple(opaque),
                    tuple(issues), catalog_present, next(iter(conventions)) if len(conventions) == 1 else (),
                    (lines[sections['relations'][0]][0] + (3 if sections['relations'][0] == 0 and source.startswith(b'\xef\xbb\xbf') else 0)) if 'relations' in sections else None)


def _table(types=None, relations=None, newline=b'\n', trailing=True):
    escape = lambda value: value.replace('\\', '\\\\').replace('|', '\\|')
    if types is not None:
        rows = [['Tipo', 'Descrizione'], ['---', '---']] + [['`' + item.name + '`', item.description] for item in types]
    else:
        rows = [['Relazione', 'Da (tipo)', 'A (tipo)', 'Significato', 'Esempio'], ['---'] * 5] + [
            ['`' + item.name + '`', ', '.join(item.from_types), ', '.join(item.to_types), item.meaning, item.example] for item in relations]
    return newline.join(('| ' + ' | '.join(escape(cell) for cell in row) + ' |').encode('utf-8') for row in rows) + (newline if trailing else b'')


def _newline(source):
    match = re.search(rb'\r\n|\n|\r', source)
    return match[0] if match else b'\n'


def serialize(document, *, types=None, relations=None):
    types = document.types if types is None else tuple(types)
    relations = document.relations if relations is None else tuple(relations)
    if types == document.types and relations == document.relations:
        return document.source  # no-op remains lossless even for opaque/manual documents
    if not document.structurally_editable:
        raise OntologyError('ontology_manual', 'Documento ambiguo o non valido: editing manuale richiesto')
    if document.types is None:
        raise OntologyError('catalog_adoption_required', 'Proporre e confermare prima il catalogo dei tipi')
    issues = validate(types, relations)
    if issues:
        raise OntologyError(issues[0].code, issues[0].message)
    replacements = []
    for key, old, new in (('types', document.types, types), ('relations', document.relations, relations)):
        if old != new:
            span = document.source_spans[key]
            original = document.source[span.start:span.end]
            replacements.append((span, _table(**{key: new}, newline=_newline(original), trailing=original.endswith((b'\n', b'\r')))))
    result = document.source
    for span, replacement in sorted(replacements, key=lambda item: item[0].start, reverse=True):
        result = result[:span.start] + replacement + result[span.end:]
    if len(result) > MAX_BYTES:
        raise OntologyError('ontology_size', 'Proposta oltre 2 MiB')
    checked = parse(result)
    if checked.types != types or checked.relations != relations or any(issue.severity == 'error' for issue in checked.issues):
        raise OntologyError('ontology_roundtrip', 'Proposta non rappresentabile senza ambiguità')
    return result


def propose_type_catalog(document, observed_types=()):
    if document.catalog_present:
        raise OntologyError('catalog_exists', 'Il documento contiene già un catalogo; nessuna adozione implicita')
    ambiguous = any(issue.code == 'ambiguous_conventions' for issue in document.issues)
    if not document.structurally_editable or document.adoption_offset is None or ambiguous:
        raise OntologyError('ontology_manual', 'Adozione richiede una tabella relazioni univoca e convenzioni non ambigue')
    names = set(document.convention_types)
    for name in observed_types:
        if not _name(name) or name in WILDCARDS:
            raise OntologyError('invalid_type', 'Tipo osservato non adottabile automaticamente')
        names.add(name)
    for relation in document.relations:
        names.update(set(relation.from_types + relation.to_types) - WILDCARDS)
    types = tuple(TypeDef(name) for name in sorted(names))
    issues = validate(types, document.relations)
    if issues:
        raise OntologyError(issues[0].code, issues[0].message)
    newline = _newline(document.source)
    at = document.adoption_offset
    prefix = newline if at and document.source[:at] != b'\xef\xbb\xbf' and not document.source[:at].endswith((b'\n', b'\r')) else b''
    inserted = prefix + b'## Tipi ammessi' + newline * 2 + _table(types=types, newline=newline) + newline
    candidate = document.source[:at] + inserted + document.source[at:]
    if len(candidate) > MAX_BYTES or not parse(candidate).editable:
        raise OntologyError('ontology_roundtrip', 'Catalogo proposto non rappresentabile')
    return CatalogProposal(document.digest, candidate, types)
