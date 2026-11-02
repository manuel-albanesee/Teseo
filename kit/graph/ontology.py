"""Ontologia Markdown lossless: parser e proposte pure, nessun accesso al filesystem.

Grammatica volutamente limitata: sezioni ATX h2, una tabella contigua per sezione,
2/3 colonne per i tipi (la terza è «Sottotipo di»), 3/5 per le relazioni, 3 per le categorie
(«Categoria | Più ampia | Descrizione», doc/16), 4 per la semantica delle relazioni («Relazione | Ruolo | Inversa |
Proprietà», doc/17) e 5 per i vincoli («Tipo | Relazione o attributo | Minimo | Massimo | Se manca»), 2 per i sinonimi («Nome | Sinonimi»,
separati da `;`) e 4 per le corrispondenze («Nome | Corrispondenza | Vocabolario | Esattezza»). Contenuto ambiguo
resta manuale. Gli offset sono byte UTF-8; il serializer sostituisce solo tabelle riconosciute: categorie, semantica,
vincoli, sinonimi e corrispondenze si conservano byte per byte (e il serializer rifiuta una modifica che li lascerebbe
con nomi non più dichiarati).
"""
from dataclasses import dataclass
import hashlib
import re
import unicodedata

MAX_BYTES = 2 * 1024 * 1024
MAX_ROWS = 2048
SPECIAL = frozenset({'tipo', 'tags', 'fonti', 'aggiornato', 'aliases', 'relazioni_dettaglio', 'menziona', 'documentato_in'})
WILDCARDS = frozenset({'qualsiasi', 'stesso tipo'})
HEADINGS = {'Tipi ammessi': 'types', 'Relazioni tipizzate': 'relations', 'Categorie': 'categories',
            'Semantica delle relazioni': 'semantics', 'Vincoli': 'constraints',
            'Sinonimi': 'synonyms', 'Corrispondenze': 'matches'}
RUOLI = ('dipendenza', 'responsabile', 'composizione', 'causale', 'sequenza')  # insieme chiuso (doc/17, fase 2)
PROPRIETA = ('transitiva', 'simmetrica')
SE_MANCA = ('domanda', 'nulla')  # un vincolo violato diventa una domanda aperta per l'autore, oppure niente
ESATTEZZE = ('esatta', 'vicina')  # skos:exactMatch o skos:closeMatch (doc/17, fase 3a)
IRI = re.compile(r'[A-Za-z][A-Za-z0-9+.-]*:[^\s<>"{}|\\^`]+')  # un IRI assoluto o un CURIE (prefisso:nome locale)
CHIAVE_VOCABOLARIO = re.compile(r'[a-z][\w.-]*')  # come le «Chiavi delle fonti» (build_graph.RIGA_FONTE)


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
    parent: str = ''  # «Sottotipo di»: vuoto per un tipo radice


@dataclass(frozen=True)
class Category:
    name: str
    broader: str = ''  # «Più ampia» (skos:broader): vuota per una categoria radice
    description: str = ''


@dataclass(frozen=True)
class RelationSemantics:
    name: str
    role: str = ''  # uno di RUOLI, o vuoto: vale il ruolo di default del kit (semantica.RUOLI_DEFAULT)
    inverse: str = ''  # nome leggibile della relazione al contrario («è usato da»): mai un arco, mai nelle pagine
    properties: tuple[str, ...] = ()  # sottoinsieme di PROPRIETA


@dataclass(frozen=True)
class Constraint:
    type: str  # vale anche per i sottotipi
    relation: str
    minimum: int = 0
    maximum: int | None = None
    if_missing: str = 'domanda'


@dataclass(frozen=True)
class Synonyms:
    name: str  # un tipo o una categoria dichiarati
    synonyms: tuple[str, ...] = ()  # altre parole con cui la domanda può nominarlo (skos:altLabel)


@dataclass(frozen=True)
class Correspondence:
    name: str  # un tipo o una categoria dichiarati
    iri: str  # IRI o CURIE del concetto di un vocabolario esterno
    vocabulary: str  # chiave censita in «Chiavi delle fonti»
    exactness: str = 'esatta'  # uno di ESATTEZZE


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
    categories: tuple[Category, ...] | None = None
    categories_span: Span | None = None
    semantics: tuple[RelationSemantics, ...] | None = None
    semantics_span: Span | None = None
    constraints: tuple[Constraint, ...] | None = None
    constraints_span: Span | None = None
    synonyms: tuple[Synonyms, ...] | None = None
    synonyms_span: Span | None = None
    matches: tuple[Correspondence, ...] | None = None
    matches_span: Span | None = None

    @property
    def digest(self):
        return hashlib.sha256(self.source).hexdigest()

    @property
    def source_spans(self):
        return {key: span for key, span in (('types', self.types_span), ('relations', self.relations_span),
                                            ('categories', self.categories_span), ('semantics', self.semantics_span),
                                            ('constraints', self.constraints_span), ('synonyms', self.synonyms_span),
                                            ('matches', self.matches_span)) if span}

    @property
    def capabilities(self):
        """I comportamenti che le sezioni dichiarate attivano, in ordine fisso: nessuno senza le sezioni (doc/17)."""
        semantics = self.semantics or ()
        attive = (('role_chains', any(item.role for item in semantics)),
                  ('inverse_labels', any(item.inverse for item in semantics)),
                  ('transitive_views', any('transitiva' in item.properties for item in semantics)),
                  ('symmetric_views', any('simmetrica' in item.properties for item in semantics)),
                  ('cardinality_questions', any(item.if_missing == 'domanda' for item in self.constraints or ())),
                  ('synonym_seeds', bool(self.synonyms)))
        return tuple(nome for nome, attiva in attive if attiva)

    @property
    def structurally_editable(self):
        return self.relations_span is not None and not any(issue.severity == 'error' for issue in self.issues)

    @property
    def editable(self):
        return self.types is not None and self.structurally_editable

    @property
    def ancestors(self):
        """{tipo: (padre, nonno, …)} dei tipi dichiarati; vuoto senza catalogo. Un ciclo (errore dello schema) si ferma."""
        parents = {item.name: item.parent for item in self.types or () if item.parent}
        result = {}
        for item in self.types or ():
            chain, current = [], parents.get(item.name)
            while current and current not in chain and current != item.name:
                chain.append(current)
                current = parents.get(current)
            result[item.name] = tuple(chain)
        return result

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


def _norm(value):
    """Come build_graph.norm (un test li confronta): senza maiuscole, accenti e punteggiatura. Qui perché build_graph
    importa questo modulo e non il contrario."""
    value = ''.join(char for char in unicodedata.normalize('NFKD', str(value)) if not unicodedata.combining(char))
    return re.sub(r'[^a-z0-9]+', ' ', value.lower()).strip()


def _cycles(parents):
    """I nomi che stanno in un ciclo di `parents` ({figlio: padre})."""
    found = set()
    for start in parents:
        seen, current = [], start
        while current in parents and current not in seen:
            seen.append(current)
            current = parents[current]
        if current in seen:
            found.update(seen[seen.index(current):])
    return found


def validate(types, relations, categories=None, semantics=None, constraints=None, synonyms=None, matches=None):
    """Validazione del modello; impatto sulle pagine demandato al builder/preview.

    `semantics` e `constraints` (doc/17) sono le sezioni facoltative: i loro nomi devono restare dichiarati, quindi
    rinominare o togliere una relazione o un tipo che citano è un errore finché non si correggono a mano. Lo stesso vale
    per `synonyms` e `matches` (fase 3a), che citano tipi e categorie."""
    if (types is not None and not types) or len(types or ()) > MAX_ROWS or len(relations) > MAX_ROWS:
        return (Issue('catalog_limit', 'Catalogo vuoto o oltre 2048 righe'),)
    issues, seen = [], set()
    for item in types or ():
        if (not isinstance(item, TypeDef) or not _name(item.name) or item.name in WILDCARDS or not _text(item.description)
                or not isinstance(item.parent, str) or (item.parent and not _name(item.parent))):
            issues.append(Issue('invalid_type', 'Nome o descrizione tipo non rappresentabile nella tabella v1'))
            continue
        if item.name.casefold() in seen:
            issues.append(Issue('duplicate_type', 'Tipo duplicato: ' + item.name))
        seen.add(item.name.casefold())
    known = {item.name for item in types or () if isinstance(item, TypeDef) and isinstance(item.name, str)}
    parents = {item.name: item.parent for item in types or () if isinstance(item, TypeDef) and item.parent}
    for name, parent in parents.items():
        if parent not in known or parent == name:
            issues.append(Issue('unknown_parent', name + ': sottotipo di un tipo non dichiarato: ' + str(parent)))
    for name in sorted(_cycles(parents)):
        issues.append(Issue('type_cycle', 'Gerarchia dei tipi circolare: ' + name))
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
    if categories is not None:
        if not categories or len(categories) > MAX_ROWS:
            issues.append(Issue('catalog_limit', 'Categorie vuote o oltre 2048 righe'))
        names, seen = set(), set()
        for item in categories:
            if (not isinstance(item, Category) or not _name(item.name) or not _text(item.description)
                    or not isinstance(item.broader, str) or (item.broader and not _name(item.broader))):
                issues.append(Issue('invalid_category', 'Nome o descrizione categoria non rappresentabile nella tabella'))
                continue
            if item.name.casefold() in seen:
                issues.append(Issue('duplicate_category', 'Categoria duplicata: ' + item.name))
            seen.add(item.name.casefold())
            names.add(item.name)
        broader = {item.name: item.broader for item in categories if isinstance(item, Category) and item.broader}
        for name, parent in broader.items():
            if parent not in names or parent == name:
                issues.append(Issue('unknown_broader', name + ': categoria più ampia non dichiarata: ' + str(parent)))
        for name in sorted(_cycles(broader)):
            issues.append(Issue('category_cycle', 'Gerarchia delle categorie circolare: ' + name))
    relation_names = {item.name for item in relations if isinstance(item, Relation)}
    if semantics is not None:
        if not semantics or len(semantics) > MAX_ROWS:
            issues.append(Issue('catalog_limit', 'Semantica vuota o oltre 2048 righe'))
        seen = set()
        for item in semantics:
            if (not isinstance(item, RelationSemantics) or not isinstance(item.role, str) or not _text(item.inverse)
                    or not isinstance(item.properties, tuple)):
                issues.append(Issue('invalid_semantics', 'Riga della semantica non rappresentabile nella tabella'))
                continue
            if item.name not in relation_names:
                issues.append(Issue('unknown_relation', 'Semantica di una relazione non dichiarata: ' + str(item.name)))
            if item.name in seen:
                issues.append(Issue('duplicate_semantics', 'Semantica ripetuta: ' + item.name))
            seen.add(item.name)
            if item.role and item.role not in RUOLI:
                issues.append(Issue('invalid_role', item.name + ': ruolo atteso fra ' + ', '.join(RUOLI)))
            for proprieta in item.properties:
                if proprieta not in PROPRIETA:
                    issues.append(Issue('invalid_property', item.name + ': proprietà attesa fra ' + ', '.join(PROPRIETA)))
            if 'simmetrica' in item.properties and item.inverse:
                issues.append(Issue('symmetric_with_inverse', item.name + ': una relazione simmetrica non ha un nome inverso'))
    if constraints is not None:
        if not constraints or len(constraints) > MAX_ROWS:
            issues.append(Issue('catalog_limit', 'Vincoli vuoti o oltre 2048 righe'))
        seen = set()
        for item in constraints:
            if not isinstance(item, Constraint) or not isinstance(item.minimum, int) or isinstance(item.minimum, bool):
                issues.append(Issue('invalid_cardinality', 'Riga dei vincoli non rappresentabile nella tabella'))
                continue
            if types is not None and item.type not in known:
                issues.append(Issue('unknown_type', 'Vincolo su un tipo non dichiarato: ' + str(item.type)))
            if item.relation not in relation_names:
                issues.append(Issue('unknown_relation', 'Vincolo su una relazione non dichiarata: ' + str(item.relation)))
            if item.minimum < 0 or (item.maximum is not None and item.maximum < item.minimum):
                issues.append(Issue('invalid_cardinality', f'{item.type} · {item.relation}: minimo e massimo non coerenti'))
            if item.if_missing not in SE_MANCA:
                issues.append(Issue('invalid_if_missing', f'{item.type} · {item.relation}: «Se manca» atteso fra '
                                    + ', '.join(SE_MANCA)))
            if (item.type, item.relation) in seen:
                issues.append(Issue('duplicate_cardinality', f'Vincolo ripetuto: {item.type} · {item.relation}'))
            seen.add((item.type, item.relation))
    if synonyms is not None or matches is not None:
        declared = {item.name for item in types or () if isinstance(item, TypeDef)}
        declared |= {item.name for item in categories or () if isinstance(item, Category)}
        names_known = types is not None or categories is not None
    if synonyms is not None:
        if not synonyms or len(synonyms) > MAX_ROWS:
            issues.append(Issue('catalog_limit', 'Sinonimi vuoti o oltre 2048 righe'))
        owner = {_norm(name): name for name in declared}  # forma normalizzata → chi la usa (nome dichiarato o sinonimo)
        seen = set()
        for item in synonyms:
            if (not isinstance(item, Synonyms) or not isinstance(item.synonyms, tuple) or not item.synonyms
                    or any(not _text(word) or not _norm(word) for word in item.synonyms)):
                issues.append(Issue('invalid_synonyms', 'Riga dei sinonimi non rappresentabile nella tabella'))
                continue
            if names_known and item.name not in declared:
                issues.append(Issue('unknown_name', 'Sinonimi di un tipo o una categoria non dichiarati: ' + str(item.name)))
            if item.name in seen:
                issues.append(Issue('duplicate_synonyms', 'Sinonimi ripetuti: ' + item.name))
            seen.add(item.name)
            for word in item.synonyms:
                key = _norm(word)
                if key in owner:
                    issues.append(Issue('synonym_collision', f'{item.name}: «{word}» coincide con «{owner[key]}»'))
                owner.setdefault(key, item.name)
    if matches is not None:
        if not matches or len(matches) > MAX_ROWS:
            issues.append(Issue('catalog_limit', 'Corrispondenze vuote o oltre 2048 righe'))
        seen = set()
        for item in matches:
            if (not isinstance(item, Correspondence) or not isinstance(item.iri, str)
                    or not isinstance(item.vocabulary, str) or not isinstance(item.exactness, str)):
                issues.append(Issue('invalid_match', 'Riga delle corrispondenze non rappresentabile nella tabella'))
                continue
            if names_known and item.name not in declared:
                issues.append(Issue('unknown_name', 'Corrispondenza di un tipo o una categoria non dichiarati: '
                                    + str(item.name)))
            if len(item.iri) > 512 or not IRI.fullmatch(item.iri):
                issues.append(Issue('invalid_iri', f'{item.name}: atteso un IRI o un CURIE, non «{item.iri}»'))
            if not CHIAVE_VOCABOLARIO.fullmatch(item.vocabulary):
                issues.append(Issue('invalid_match', f'{item.name}: chiave del vocabolario non valida: «{item.vocabulary}»'))
            if item.exactness not in ESATTEZZE:
                issues.append(Issue('invalid_exactness', f'{item.name}: «Esattezza» attesa fra ' + ', '.join(ESATTEZZE)))
            if (item.name, item.iri) in seen:
                issues.append(Issue('duplicate_match', f'Corrispondenza ripetuta: {item.name} · {item.iri}'))
            seen.add((item.name, item.iri))
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


def _count(cell):
    """Un numero intero non negativo scritto in una cella, o None se la cella è vuota."""
    if not cell:
        return None
    if not cell.isdecimal() or len(cell) > 6:
        raise ValueError('Minimo e massimo attesi come numeri interi')
    return int(cell)


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
            if (key == 'types' and header not in (['tipo', 'descrizione'], ['nome', 'descrizione'],
                                                  ['tipo', 'descrizione', 'sottotipo di'], ['nome', 'descrizione', 'sottotipo di'])) or (
                    key == 'categories' and header != ['categoria', 'più ampia', 'descrizione']) or (
                    key == 'semantics' and header != ['relazione', 'ruolo', 'inversa', 'proprietà']) or (
                    key == 'constraints' and header != ['tipo', 'relazione o attributo', 'minimo', 'massimo', 'se manca']) or (
                    key == 'synonyms' and header != ['nome', 'sinonimi']) or (
                    key == 'matches' and header != ['nome', 'corrispondenza', 'vocabolario', 'esattezza']) or (key == 'relations' and (expected not in (3, 5) or header[0] not in ('nome', 'relazione') or header[1:3] != ['da', 'a'] or (expected == 5 and header[3:] != ['significato', 'esempio']))):
                raise ValueError('Intestazione tabella non riconosciuta')
            if len(table) < 2 or len(table[1]) != expected or not all(re.fullmatch(r':?-{3,}:?', cell) for cell in table[1]):
                raise ValueError('Separatore tabella non valido')
            if len(table) - 2 > MAX_ROWS or any(len(row) != expected for row in table):
                raise ValueError('Numero colonne o righe non supportato')
            if any('<!--' in lines[index][3] or '-->' in lines[index][3] for index in rows):
                raise ValueError('Commento nella tabella: usare editing manuale')
            if key == 'types':
                parsed[key] = tuple(TypeDef(_identifier(row[0]), row[1], _identifier(row[2]) if expected == 3 else '')
                                    for row in table[2:])
            elif key == 'categories':
                parsed[key] = tuple(Category(_identifier(row[0]), _identifier(row[1]), row[2]) for row in table[2:])
            elif key == 'semantics':
                parsed[key] = tuple(RelationSemantics(_identifier(row[0]), _identifier(row[1]), row[2],
                                                      tuple(item.strip() for item in row[3].split(',') if item.strip()))
                                    for row in table[2:])
            elif key == 'constraints':
                parsed[key] = tuple(Constraint(_identifier(row[0]), _identifier(row[1]), _count(row[2]) or 0,
                                               _count(row[3]), row[4] or 'domanda') for row in table[2:])
            elif key == 'synonyms':
                parsed[key] = tuple(Synonyms(_identifier(row[0]),
                                             tuple(word.strip() for word in row[1].split(';') if word.strip()))
                                    for row in table[2:])
            elif key == 'matches':
                parsed[key] = tuple(Correspondence(_identifier(row[0]), _identifier(row[1]), _identifier(row[2]),
                                                   _identifier(row[3])) for row in table[2:])
            else:
                parsed[key] = tuple(Relation(_identifier(row[0]), tuple(item.strip() for item in row[1].split(',')),
                    tuple(item.strip() for item in row[2].split(',')), row[3] if expected == 5 else '', row[4] if expected == 5 else '') for row in table[2:])
            spans[key] = Span(lines[rows[0]][0], lines[rows[-1]][1])
        except ValueError as error:
            issues.append(Issue('unrecognized_table', str(error), rows[0] + 1))
    types, relations, categories = parsed.get('types'), parsed.get('relations', ()), parsed.get('categories')
    semantics, constraints = parsed.get('semantics'), parsed.get('constraints')
    synonyms, matches = parsed.get('synonyms'), parsed.get('matches')
    issues.extend(validate(types, relations, categories, semantics, constraints, synonyms, matches))
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
                    (lines[sections['relations'][0]][0] + (3 if sections['relations'][0] == 0 and source.startswith(b'\xef\xbb\xbf') else 0)) if 'relations' in sections else None,
                    categories, spans.get('categories'), semantics, spans.get('semantics'),
                    constraints, spans.get('constraints'), synonyms, spans.get('synonyms'), matches, spans.get('matches'))


def _table(types=None, relations=None, newline=b'\n', trailing=True):
    escape = lambda value: value.replace('\\', '\\\\').replace('|', '\\|')
    if types is not None and any(item.parent for item in types):
        rows = [['Tipo', 'Descrizione', 'Sottotipo di'], ['---'] * 3] + [
            ['`' + item.name + '`', item.description, item.parent] for item in types]
    elif types is not None:
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
    issues = validate(types, relations, document.categories, document.semantics, document.constraints,
                      document.synonyms, document.matches)
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
