"""Integration gates use isolated data snapshots, never candidate executables."""
import _shortpath  # noqa: F401
import json
from pathlib import Path
import shutil
import tempfile
import subprocess
import unittest
from unittest import mock
from uuid import uuid4

from kit.dashboard.contracts import ContractError
from kit.dashboard.sync_validation import validate_integration


class IntegrationValidation(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='teseo sync validation ')
        self.addCleanup(temporary.cleanup)
        directory = Path(temporary.name)
        self.base, self.local, self.remote, self.candidate = [directory / name for name in ('base', 'local', 'remote', 'candidate')]
        self.base.mkdir()
        (self.base / 'wiki').mkdir()
        (self.base / 'raw').mkdir()
        (self.base / '.teseo').mkdir()
        manifest = Path(__file__).parent / 'fixtures/dashboard/project-v1.json'
        shutil.copyfile(manifest, self.base / '.teseo/project.json')
        (self.base / 'Wiki reference.md').write_text('Schema legacy compatibile\n| `src` | fonte.txt |\n', encoding='utf-8')
        (self.base / 'raw/fonte.txt').write_text('Fonte originale', encoding='utf-8')
        for name in ('Anna', 'Bruno', 'Carla'):
            self.write(self.base, name, 'Versione originale')
        for root in (self.local, self.remote, self.candidate):
            shutil.copytree(self.base, root)

    def write(self, root, name, body, metadata=''):
        (root / f'wiki/{name}.md').write_text('---\ntipo: persona\n' + metadata + '---\n' + body, encoding='utf-8')

    def validate(self, **kwargs):
        return validate_integration(self.base, self.local, self.remote, self.candidate, **kwargs)

    def test_disjoint_edits_validate_and_build_candidate_graph(self):
        self.write(self.local, 'Anna', 'Locale')
        self.write(self.remote, 'Bruno', 'Remoto')
        self.write(self.candidate, 'Anna', 'Locale')
        self.write(self.candidate, 'Bruno', 'Remoto')
        result = self.validate()
        self.assertEqual(result['state'], 'validated')
        self.assertTrue(result['checks']['synthesis'])
        self.assertTrue((self.candidate / '.teseo/local/graph-current.json').is_file())

    def test_linked_pages_need_explicit_reconciliation(self):
        self.write(self.local, 'Anna', 'Locale [[Bruno]]')
        self.write(self.remote, 'Bruno', 'Remoto')
        self.write(self.candidate, 'Anna', 'Locale [[Bruno]]')
        self.write(self.candidate, 'Bruno', 'Remoto')
        result = self.validate()
        self.assertEqual(result['state'], 'needs_decision')
        self.assertEqual(result['scope'], ['wiki/Anna.md', 'wiki/Bruno.md'])
        self.assertEqual(len(result['key']), 64)

    def test_source_overlap_needs_decision(self):
        for root in (self.base, self.local, self.remote, self.candidate):
            for name in ('Anna', 'Bruno'):
                self.write(root, name, 'Originale', 'fonti: [src]\n')
        self.write(self.local, 'Anna', 'Locale', 'fonti: [src]\n')
        self.write(self.remote, 'Bruno', 'Remoto', 'fonti: [src]\n')
        self.write(self.candidate, 'Anna', 'Locale', 'fonti: [src]\n')
        self.write(self.candidate, 'Bruno', 'Remoto', 'fonti: [src]\n')
        self.assertEqual(self.validate()['state'], 'needs_decision')

    def test_changed_or_deleted_raw_from_either_parent_rejected(self):
        for source in (self.base, self.local, self.remote):
            with self.subTest(source=source.name):
                path = source / 'raw/fonte.txt'
                original = path.read_bytes()
                path.write_bytes(b'altro')
                with self.assertRaises(ContractError) as raised:
                    self.validate()
                self.assertEqual(raised.exception.code, 'immutable_raw_changed')
                path.write_bytes(original)

    def test_invalid_event_rejected_before_reconciliation(self):
        events = self.candidate / '.teseo/shared/events'
        events.mkdir(parents=True)
        (events / '00000000-0000-4000-8000-000000000001.json').write_text('{}', encoding='utf-8')
        with self.assertRaises(ContractError):
            self.validate()

    def test_bad_links_rejected(self):
        self.write(self.candidate, 'Anna', '[[Non esiste]]')
        with self.assertRaises(ContractError) as raised:
            self.validate()
        self.assertEqual(raised.exception.code, 'integration_invalid')

    def test_event_present_in_remote_cannot_be_removed(self):
        events = self.remote / '.teseo/shared/events'
        events.mkdir(parents=True)
        (events / '00000000-0000-4000-8000-000000000001.json').write_text('{}', encoding='utf-8')
        with self.assertRaises(ContractError) as raised:
            self.validate()
        self.assertEqual(raised.exception.code, 'immutable_event_changed')

    def test_manifest_identity_cannot_change(self):
        manifest = self.candidate / '.teseo/project.json'
        data = json.loads(manifest.read_bytes())
        data['vault_id'] = '00000000-0000-4000-8000-000000000001'
        manifest.write_text(json.dumps(data), encoding='utf-8')
        with self.assertRaises(ContractError) as raised:
            self.validate()
        self.assertEqual(raised.exception.code, 'manifest_changed')

    def test_global_schema_change_is_correlated(self):
        with (self.local / 'Wiki reference.md').open('a', encoding='utf-8') as stream:
            stream.write('\nDescrizione modificata')
        shutil.copyfile(self.local / 'Wiki reference.md', self.candidate / 'Wiki reference.md')
        self.write(self.remote, 'Anna', 'Remoto')
        self.write(self.candidate, 'Anna', 'Remoto')
        self.assertEqual(self.validate()['state'], 'needs_decision')

    def _append(self, root, path, text):
        with (root / path).open('a', encoding='utf-8', newline='\n') as stream:
            stream.write(text)

    def _logs(self, local_text, remote_text, candidate_text, path='log.md', base='# Log\n'):
        for root in (self.base, self.local, self.remote, self.candidate):
            (root / path).write_text(base, encoding='utf-8')
        for root, text in ((self.local, local_text), (self.remote, remote_text), (self.candidate, candidate_text)):
            self._append(root, path, text)

    def test_append_only_log_and_index_on_both_branches_need_no_decision(self):
        for path, local_line, remote_line in (('log.md', '## lint | locale\n', '## ingest | remoto\n'),
                                              ('index.md', '- [[Anna]]\n', '- [[Bruno]]\n')):
            self._logs(local_line, remote_line, local_line + remote_line, path, '# Titolo\n')
            self.assertEqual(self.validate()['state'], 'validated', path)

    def test_append_only_log_does_not_correlate_with_unrelated_notes(self):
        self._logs('## lint | locale\n', '', '## lint | locale\n')
        self.write(self.remote, 'Bruno', 'Remoto')
        self.write(self.candidate, 'Bruno', 'Remoto')
        self.assertEqual(self.validate()['state'], 'validated')

    def test_rewriting_or_deleting_log_and_index_lines_still_needs_a_decision(self):
        self._logs('', '## ingest | remoto\n', '## ingest | remoto\n', 'log.md', '# Log\n## prima\n')
        (self.local / 'log.md').write_text('# Log\n## riscritta\n', encoding='utf-8')
        self.assertEqual(self.validate()['state'], 'needs_decision')
        self._logs('', '- [[Bruno]]\n', '- [[Bruno]]\n', 'index.md', '# Titolo\n- [[Anna]]\n')
        (self.local / 'index.md').write_text('# Titolo\n', encoding='utf-8')
        self.assertEqual(self.validate()['state'], 'needs_decision')

    def test_additive_on_one_side_only_does_not_hide_a_rewrite_on_the_other(self):
        self._logs('## lint | locale\n', '', '## lint | locale\n', 'log.md', '# Log\n## prima\n')
        (self.remote / 'log.md').write_text('# Log\n## riscritta\n', encoding='utf-8')
        self.assertEqual(self.validate()['state'], 'needs_decision')

    def test_same_change_on_both_branches_needs_no_decision(self):
        for root in (self.local, self.remote, self.candidate):
            self.write(root, 'Anna', 'Uguale', 'aliases: [Annetta]\n')
        self.assertEqual(self.validate()['state'], 'validated')

    def test_synthesis_failure_and_timeout_block(self):
        for outcome in (subprocess.CompletedProcess([], 1), subprocess.TimeoutExpired([], 60), OSError()):
            with self.subTest(outcome=type(outcome).__name__):
                patch = (mock.patch('kit.dashboard.sync_validation.subprocess.run', side_effect=outcome)
                         if isinstance(outcome, Exception) else
                         mock.patch('kit.dashboard.sync_validation.subprocess.run', return_value=outcome))
                with patch as run, self.assertRaises(ContractError) as raised:
                    self.validate()
                self.assertEqual(raised.exception.code, 'synthesis_invalid')
                self.assertFalse(run.call_args.kwargs['shell'])
                self.assertNotIn(str(self.candidate), run.call_args.args[0][1])

    def test_duplicate_roots_rejected(self):
        with self.assertRaises(ContractError) as raised:
            validate_integration(self.base, self.local, self.remote, self.local)
        self.assertEqual(raised.exception.code, 'integration_roots')

    def test_correlation_work_is_bounded_per_branch(self):
        for index in range(513):
            self.write(self.local, f'Nuova {index}', 'Pagina nuova')
        with self.assertRaises(ContractError) as raised:
            self.validate()
        self.assertEqual(raised.exception.code, 'integration_limit')

    def test_non_utf8_and_malformed_page_are_rejected(self):
        path = self.candidate / 'wiki/Anna.md'
        for data in (b'\xff', b'---\ntipo: [persona]\n---\nCorpo'):
            path.write_bytes(data)
            with self.assertRaises(ContractError) as raised:
                self.validate()
            self.assertEqual(raised.exception.code, 'integration_invalid')

    def test_invalid_synthesis_is_rejected_even_with_correlated_changes(self):
        self.write(self.local, 'Anna', 'Locale')
        self.write(self.remote, 'Anna', 'Remoto')
        self.write(self.candidate, 'Anna', 'Sintesi senza avviso', 'tags: [entropia]\n')
        with self.assertRaises(ContractError) as raised:
            self.validate()
        self.assertEqual(raised.exception.code, 'synthesis_invalid')

    def test_shared_question_events_are_correlated_across_distinct_paths(self):
        question_id = str(uuid4())
        vault_id = json.loads((self.base / '.teseo/project.json').read_bytes())['vault_id']
        def event(kind, payload, parents=(), entity=None):
            return dict(format_version=1, vault_id=vault_id, event_id=str(uuid4()), kind=kind,
                        entity_id=entity or question_id, question_id=question_id, operation_id=str(uuid4()),
                        author_id=str(uuid4()), created_at='2026-10-24T10:00:00Z', parents=list(parents), payload=payload)
        registered = event('question.registered', {'text': 'Chi decide?', 'anchors': [{'page': 'Anna', 'signal': 'manca_referente'}]})
        answers = [event('answer.recorded', {'text': text, 'pages': ['Anna'], 'source': 'nota-utente'},
                         [registered['event_id']], str(uuid4())) for text in ('Anna', 'Bruno')]
        def save(root, item):
            directory = root / '.teseo/shared/events'
            directory.mkdir(parents=True, exist_ok=True)
            from kit.dashboard.contracts import canonical_json
            (directory / (item['event_id'] + '.json')).write_bytes(canonical_json(item))
        for root in (self.base, self.local, self.remote, self.candidate):
            save(root, registered)
        save(self.local, answers[0])
        save(self.remote, answers[1])
        for answer in answers:
            save(self.candidate, answer)
        result = self.validate()
        self.assertEqual(result['state'], 'needs_decision')
        self.assertEqual(len(result['scope']), 2)

    def test_callback_cannot_mutate_scope_to_authorize_itself(self):
        self.write(self.local, 'Anna', 'Locale')
        self.write(self.remote, 'Anna', 'Remoto')
        def mutate(request):
            request['scope'].clear()
            return dict(resolved=True, human_decision=True, input_key=request['key'],
                        scope=[], candidate_digest=request['candidate_digest'])
        self.assertEqual(self.validate(reconcile=mutate)['scope'], ['wiki/Anna.md'])

    def test_resolved_boolean_is_not_authorization(self):
        self.write(self.local, 'Anna', 'Locale')
        self.write(self.remote, 'Anna', 'Remoto')
        self.write(self.candidate, 'Anna', 'Scelto')
        self.assertEqual(self.validate(reconcile=lambda request: {'resolved': True})['state'], 'needs_decision')

    def test_frozen_human_decision_and_revalidation(self):
        self.write(self.local, 'Anna', 'Locale')
        self.write(self.remote, 'Anna', 'Remoto')
        self.write(self.candidate, 'Anna', 'Scelto')
        def human(request):
            return dict(resolved=True, human_decision=True, input_key=request['key'],
                        scope=request['scope'], candidate_digest=request['candidate_digest'])
        self.assertEqual(self.validate(reconcile=human)['state'], 'validated')
        def invalid(request):
            self.write(self.candidate, 'Anna', '[[Non esiste]]')
            return human(request)
        with self.assertRaises(ContractError):
            self.validate(reconcile=invalid)


if __name__ == '__main__':
    unittest.main()
