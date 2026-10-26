"""Roundtrip byte, proposte pure, validazione builder e generazioni HTTP coerenti."""
import _shortpath  # noqa: F401
from dataclasses import replace
import hashlib
from pathlib import Path
import shutil
import sqlite3
import unittest

import test_dashboard_queries as fixture
from kit.graph import build_graph
from kit.graph.ontology import (parse, serialize, propose_type_catalog, validate, TypeDef,
                               Relation, OntologyError, MAX_BYTES)
from kit.dashboard.contracts import canonical_json, content_hash, file_hash
from kit.dashboard.graph_service import rebuild

ROOT = Path(__file__).resolve().parents[1]
TYPES = ('## Tipi ammessi\n\n| Tipo | Descrizione |\n| --- | --- |\n'
         '| `persona` | Persone |\n| `sistema` | Sistemi |\n| `fonte` | Fonti |\n\n')
RELATIONS = ('## Relazioni tipizzate\n\nIntroduzione intatta.\n\n'
             '| Relazione | Da (tipo) | A (tipo) | Significato | Esempio |\n'
             '| --- | --- | --- | --- | --- |\n'
             '| `usa` | persona | persona | X usa Y | Anna → Bruno |\n\n')
OPAQUE = '## Fonti\n| `nota-utente` | Precisazione utente |\n<!-- conserva → è -->\n<script>inert()</script>\n'


class Lossless(unittest.TestCase):
    def assert_code(self, code, function, *args, **kwargs):
        with self.assertRaises(OntologyError) as error:
            function(*args, **kwargs)
        self.assertEqual(error.exception.code, code)

    def test_noop_bytes_bom_newlines_unicode_no_final_newline_and_opaque_documents(self):
        for newline in ('\n', '\r\n', '\r'):
            for bom in ('', '\ufeff'):
                for final in (True, False):
                    source = (bom + '# Schema 🧭\n' + TYPES + RELATIONS + OPAQUE).replace('\n', newline)
                    raw = (source if final else source.rstrip('\r\n')).encode('utf-8')
                    document = parse(raw)
                    self.assertTrue(document.editable, document.issues)
                    self.assertEqual(serialize(document), raw)
                    self.assertEqual(document.digest, hashlib.sha256(raw).hexdigest())
        for raw in (b'', b'Custom schema', b'\xef\xbb\xbfTest\r\n<!-- comment -->', b'## Tipi ammessi\nUnrecognized'):
            self.assertEqual(serialize(parse(raw)), raw)

    def test_existing_template_is_legacy_and_not_rewritten(self):
        raw = (ROOT / 'kit/vault/Wiki reference.md').read_bytes()
        document = parse(raw)
        self.assertIsNone(document.types)
        self.assertFalse(document.editable)
        self.assertTrue(document.structurally_editable)
        self.assertEqual(len(document.relations), 9)
        self.assertIn('persona', document.convention_types)
        self.assertEqual(serialize(document), raw)

    def test_edit_replaces_only_relation_table_and_preserves_utf8_offsets(self):
        raw = ('\ufeff# È 🧭\r\n' + TYPES.replace('\n', '\r\n') + RELATIONS.replace('\n', '\r\n') + OPAQUE).encode('utf-8')
        document = parse(raw)
        span = document.relations_span
        changed = (replace(document.relations[0], meaning='X approva Y | testo \\ letterale', example='Équipe → Bruno'),)
        candidate = serialize(document, relations=changed)
        after = parse(candidate)
        self.assertEqual(after.relations, changed)
        self.assertEqual(candidate[:after.relations_span.start], raw[:span.start])
        self.assertEqual(candidate[after.relations_span.end:], raw[span.end:])
        self.assertIn(b'\r\n', candidate[after.relations_span.start:after.relations_span.end])
        self.assertEqual(serialize(after), candidate)

    def test_type_only_edit_keeps_relation_table_and_comments_identical(self):
        raw = (TYPES + RELATIONS + OPAQUE).encode()
        document = parse(raw)
        candidate = serialize(document, types=tuple(replace(item, description='Nuovo è | valore') if item.name == 'persona' else item for item in document.types))
        after = parse(candidate)
        self.assertEqual(candidate[after.relations_span.start:], raw[document.relations_span.start:])
        self.assertEqual(after.types[0].description, 'Nuovo è | valore')

    def test_fences_comments_html_and_indented_code_are_not_schema(self):
        decoys = ('```markdown\n' + TYPES + RELATIONS + '```\n'
                  '<!--\n' + TYPES + RELATIONS + '-->\n'
                  '<script>\n' + TYPES + RELATIONS + '</script>\n'
                  '    ## Tipi ammessi\n    | `ignora` | falso |\n')
        document = parse((decoys + TYPES + RELATIONS + OPAQUE).encode())
        self.assertTrue(document.editable, document.issues)
        self.assertEqual([item.name for item in document.types], ['persona', 'sistema', 'fonte'])
        self.assertEqual(len(document.relations), 1)

    def test_ambiguous_tables_duplicate_sections_and_unsupported_markdown_stay_manual(self):
        invalid = [TYPES + TYPES + RELATIONS,
                   TYPES + RELATIONS + RELATIONS,
                   TYPES + RELATIONS.replace('| --- | --- | --- | --- | --- |', '| invalid |'),
                   TYPES + RELATIONS.replace('X usa Y', 'X | Y'),
                   TYPES + RELATIONS.replace('| `usa`', '<!-- comment -->\n| `usa`'),
                   TYPES + RELATIONS.replace('X usa Y', 'X <!-- comment --> Y'),
                   TYPES.replace('## Tipi ammessi', 'Tipi ammessi\n---') + RELATIONS,
                   TYPES.replace('## Tipi ammessi', '### Tipi ammessi') + RELATIONS]
        for source in invalid:
            with self.subTest(source=source[:50]):
                document = parse(source)
                self.assertFalse(document.editable)
                self.assertTrue(any(issue.severity == 'error' for issue in document.issues), document.issues)
                self.assertEqual(serialize(document), source.encode())
                self.assert_code('ontology_manual', serialize, document, relations=(Relation('approva', ('persona',), ('persona',)),))

    def test_names_reserved_collisions_unknown_types_direction_and_unsafe_cells(self):
        document = parse(TYPES + RELATIONS)
        for name in ('tipo', 'tags', 'fonti', 'aggiornato', 'aliases', 'menziona', 'documentato_in', 'Tipo'):
            self.assert_code('reserved_relation', serialize, document, relations=(replace(document.relations[0], name=name),))
        self.assert_code('duplicate_relation', serialize, document, relations=(document.relations[0], replace(document.relations[0], name='USA')))
        self.assert_code('duplicate_type', serialize, document, types=document.types + (TypeDef('Persona'),))
        self.assert_code('unknown_type', serialize, document, relations=(replace(document.relations[0], to_types=('ignoto',)),))
        self.assert_code('invalid_direction', serialize, document, relations=(replace(document.relations[0], direction='target_to_source'),))
        self.assert_code('invalid_relation', serialize, document, relations=(replace(document.relations[0], meaning='riga\nnuova'),))
        self.assert_code('invalid_type', serialize, document, types=(TypeDef('stesso tipo'),))
        self.assert_code('catalog_limit', serialize, document, types=())

    def test_duplicate_declared_relation_and_reserved_name_do_not_get_last_row_wins(self):
        for name in ('usa', 'USA', 'tipo', 'menziona'):
            document = parse(TYPES + RELATIONS.replace('\n\nIntroduzione', '\n\nIntroduzione') + f'| `{name}` | persona | persona | testo | X → Y |\n')
            self.assertFalse(document.editable, name)

    def test_catalog_adoption_is_pure_deterministic_and_preserves_all_old_bytes(self):
        raw = ('\ufeff```yaml\ntipo: persona | sistema\n```\n' + RELATIONS + OPAQUE).replace('\n', '\r\n').encode()
        document = parse(raw)
        first = propose_type_catalog(document, ('fonte', 'episodio', 'persona'))
        second = propose_type_catalog(document, ('persona', 'episodio', 'fonte'))
        self.assertEqual(first, second)
        self.assertTrue(first.requires_confirmation)
        self.assertEqual(first.base_digest, document.digest)
        self.assertEqual(document.source, raw)
        self.assertEqual([item.name for item in first.types], ['episodio', 'fonte', 'persona', 'sistema'])
        at = document.adoption_offset
        inserted = len(first.candidate) - len(raw)
        self.assertEqual(first.candidate[:at] + first.candidate[at + inserted:], raw)
        self.assertTrue(parse(first.candidate).editable)
        self.assert_code('catalog_adoption_required', serialize, document, types=first.types)
        self.assert_code('catalog_exists', propose_type_catalog, parse(first.candidate), ())

    def test_bom_before_first_heading_adopts_without_moving_bom(self):
        raw = ('\ufeff' + RELATIONS.rstrip()).encode()
        candidate = propose_type_catalog(parse(raw), ('persona',)).candidate
        self.assertTrue(candidate.startswith(b'\xef\xbb\xbf## Tipi ammessi'))
        self.assertTrue(parse(candidate).editable)

    def test_ambiguous_conventions_or_unknown_observed_types_require_manual_resolution(self):
        source = '```yaml\ntipo: persona | sistema\n```\n```yaml\ntipo: persona | episodio\n```\n' + RELATIONS
        self.assert_code('ontology_manual', propose_type_catalog, parse(source), ())
        self.assert_code('invalid_type', propose_type_catalog, parse(RELATIONS), ('tipo con spazi',))

    def test_limits_invalid_utf8_and_invalid_model_are_rejected(self):
        self.assert_code('ontology_size', parse, b'x' * (MAX_BYTES + 1))
        self.assert_code('ontology_encoding', parse, b'\xff')
        self.assertTrue(validate((TypeDef([]),), ()))
        self.assertTrue(validate((TypeDef('persona'),), (Relation('usa', (), ('persona',)),)))


class Integration(unittest.TestCase):
    stop = fixture.Queries.stop
    request = fixture.Queries.request
    manifest = fixture.Queries.manifest
    hashes = fixture.Queries.hashes
    attach = fixture.Queries.attach
    get = fixture.Queries.get
    setUp = fixture.Queries.setUp

    def canonical(self):
        source = ('# Schema 🧭\n' + TYPES + RELATIONS + OPAQUE).replace('\n', '\r\n').encode()
        (self.root / 'Wiki reference.md').write_bytes(source)
        reference = rebuild(self.root)
        return source, reference

    def test_canonical_api_uses_same_model_spans_hash_and_generation_without_writes(self):
        source, reference = self.canonical()
        before = self.hashes()
        status, _, body = self.get('ontology', {'generation': reference.generation})
        self.assertEqual(status, 200, body)
        self.assertTrue(body['editable'])
        self.assertFalse(body['catalog_adoption_required'])
        self.assertEqual(body['types_source'], 'declared')
        self.assertEqual(body['schema_digest'], hashlib.sha256(source).hexdigest())
        self.assertEqual(body['schema_issues'], [])
        self.assertEqual(body['source_spans']['relations']['start'], parse(source).relations_span.start)
        self.assertEqual(body['graph_generation'], reference.generation)
        self.assertEqual(self.hashes(), before)
        with_body = build_graph.parse_snapshot(self.root)
        self.assertEqual(with_body['ontology'].digest, body['schema_digest'])

    def test_unknown_or_missing_page_type_and_invalid_schema_preserve_previous_generation(self):
        source, _ = self.canonical()
        marker = self.root / '.teseo/local/graph-current.json'
        previous = marker.read_bytes()
        original = self.page.read_bytes()
        for content in ('---\ntipo: ignoto\n---\nAnna', 'Anna senza tipo', '---\ntipo: [persona]\n---\nAnna'):
            self.page.write_text(content, encoding='utf-8')
            with self.assertRaises(build_graph.GraphValidationError):
                rebuild(self.root)
            self.assertEqual(marker.read_bytes(), previous)
        self.page.write_bytes(original)
        for schema in (source.replace(b'| `persona` | Persone |', b'| `qualsiasi` | wildcard |'),
                       source.replace(b'| `usa`', b'| `tipo`'),
                       source + TYPES.encode()):
            (self.root / 'Wiki reference.md').write_bytes(schema)
            with self.assertRaises(build_graph.GraphValidationError):
                rebuild(self.root)
            self.assertEqual(marker.read_bytes(), previous)

    def test_catalog_not_a_source_census_and_source_type_must_be_declared(self):
        source, _ = self.canonical()
        documents = {'Wiki reference.md': source.decode(), 'wiki/Anna.md': '---\ntipo: persona\nfonti: [persona]\n---\nAnna'}
        problems = build_graph.validate_snapshot(build_graph.parse_documents(documents))
        self.assertTrue(any("fonte 'persona' usata ma non censita" in message for message in problems))
        documents['Wiki reference.md'] = source.decode().replace('| `fonte` | Fonti |\r\n', '')
        problems = build_graph.validate_snapshot(build_graph.parse_documents(documents))
        self.assertTrue(any("tipo 'fonte' non dichiarato" in message for message in problems))

    def test_new_relation_same_type_and_restriction_validate_without_inventing_inference(self):
        source, _ = self.canonical()
        document = parse(source)
        relation = Relation('approva', ('qualsiasi',), ('stesso tipo',), 'X approva Y', 'Anna → Bruno')
        candidate = serialize(document, relations=document.relations + (relation,))
        documents = {'Wiki reference.md': candidate.decode(), 'wiki/Anna.md': '---\ntipo: persona\napprova: "[[Bruno]]"\n---\nAnna',
                     'wiki/Bruno.md': '---\ntipo: persona\n---\nBruno'}
        self.assertEqual(build_graph.validate_snapshot(build_graph.parse_documents(documents)), ())
        documents['wiki/Bruno.md'] = '---\ntipo: sistema\n---\nBruno'
        self.assertTrue(any('tipi non ammessi' in message for message in build_graph.validate_snapshot(build_graph.parse_documents(documents))))

    def test_legacy_proposal_never_modifies_vault_or_adds_manifest_fields(self):
        before = self.hashes()
        document = parse((self.root / 'Wiki reference.md').read_bytes())
        proposal = propose_type_catalog(document, ('persona', 'sistema', 'fonte'))
        self.assertTrue(proposal.requires_confirmation)
        self.assertEqual(self.hashes(), before)
        status, _, body = self.get('ontology')
        self.assertEqual(status, 200)
        self.assertEqual(body['types_source'], 'observed_and_constraints')
        self.assertTrue(body['catalog_adoption_required'])
        self.assertFalse(body['editable'])

    def test_v2_generation_remains_readable_until_explicit_v3_rebuild(self):
        digest = self.reference.content_revision
        generation = content_hash({'content_revision': digest, 'builder_version': 2})
        old_path = self.reference.path.with_name(generation + '.sqlite')
        shutil.copyfile(self.reference.path, old_path)
        db = sqlite3.connect(old_path)
        try:
            db.executemany('UPDATE graph_metadata SET value=? WHERE key=?', [('2', 'builder_version'), (generation, 'generation')])
            db.commit()
        finally:
            db.close()
        marker = self.root / '.teseo/local/graph-current.json'
        marker.write_bytes(canonical_json({'format_version': 1, 'content_revision': digest,
            'generation': generation, 'sqlite_sha256': file_hash(old_path)}))
        before = self.hashes()
        status, _, body = self.get('status')
        self.assertEqual(status, 200)
        self.assertEqual(body['validation_version'], 2)
        self.assertIn('graph_validation_upgrade', {issue['code'] for issue in body['issues']})
        self.assertEqual(self.get('graph', {'generation': generation})[0], 200)
        self.assertEqual(self.hashes(), before)
        current = rebuild(self.root)
        self.assertNotEqual(current.generation, generation)
        self.assertEqual(self.get('status')[2]['validation_version'], 3)


if __name__ == '__main__':
    unittest.main()
