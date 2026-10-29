"""Avviso di inizio sessione sugli aggiornamenti remoti: mai bloccante, mai scritture."""
import _shortpath  # noqa: F401
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'kit/graph'))
import avvisi


def done(payload, code=0):
    return subprocess.CompletedProcess([], code, stdout=json.dumps(payload).encode('utf-8') if payload is not None else b'not json')


class Notice(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.vault = Path(temp.name)
        (self.vault / '.teseo').mkdir()
        (self.vault / '.teseo/project.json').write_text('{}', encoding='utf-8')

    def test_updates_and_divergence_produce_a_message(self):
        for state in ('behind', 'diverged'):
            with self.subTest(state=state), mock.patch('subprocess.run', return_value=done({'state': state, 'message': 'Ci sono novità'})):
                self.assertEqual(avvisi.remoti(self.vault), 'Teseo: Ci sono novità')

    def test_quiet_states_and_every_failure_return_none(self):
        quiet = [done({'state': 'current', 'message': 'ok'}), done({'state': 'offline', 'message': 'x'}),
                 done({'state': 'disabled', 'message': 'x'}), done(None), done({'state': 'behind', 'message': 'x'}, code=2), done([1])]
        for result in quiet:
            with self.subTest(result=result.stdout), mock.patch('subprocess.run', return_value=result):
                self.assertIsNone(avvisi.remoti(self.vault))
        for error in (subprocess.TimeoutExpired('x', 8), OSError('no python')):
            with self.subTest(error=error), mock.patch('subprocess.run', side_effect=error):
                self.assertIsNone(avvisi.remoti(self.vault))

    def test_a_vault_without_manifest_never_starts_a_process(self):
        (self.vault / '.teseo/project.json').unlink()
        with mock.patch('subprocess.run', side_effect=AssertionError('nessun processo')):
            self.assertIsNone(avvisi.remoti(self.vault))

    def test_the_command_is_the_readonly_notice_with_a_bounded_timeout(self):
        with mock.patch('subprocess.run', return_value=done({'state': 'current', 'message': ''})) as run:
            avvisi.remoti(self.vault)
        command = run.call_args.args[0]
        self.assertEqual((command[2], run.call_args.kwargs['timeout']), ('avvisi', avvisi.TIMEOUT))
        self.assertLess(avvisi.TIMEOUT, 15)


class Cache(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.vault = Path(temp.name)
        (self.vault / '.teseo/local').mkdir(parents=True)
        (self.vault / '.teseo/project.json').write_text('{}', encoding='utf-8')
        self.now = 1000.0

    def call(self, result):
        with mock.patch('subprocess.run', return_value=result) as run:
            return avvisi.remoti(self.vault, adesso=lambda: self.now), run.call_count

    def test_a_recent_answer_is_reused_without_a_second_fetch_until_it_expires(self):
        behind = done({'state': 'behind', 'message': '2 aggiornamenti remoti'})
        self.assertEqual(self.call(behind), ('Teseo: 2 aggiornamenti remoti', 1))
        self.now += avvisi.VALIDITA - 1
        self.assertEqual(self.call(behind), ('Teseo: 2 aggiornamenti remoti', 0))
        self.now += 2
        self.assertEqual(self.call(done({'state': 'current', 'message': ''})), (None, 1))
        self.assertEqual(self.call(done({'state': 'behind', 'message': 'x'})), (None, 0))  # «current» è memorizzato

    def test_offline_and_failures_are_never_cached(self):
        self.assertEqual(self.call(done({'state': 'offline', 'message': 'x'})), (None, 1))
        self.assertEqual(self.call(done({'state': 'offline', 'message': 'x'})), (None, 1))
        self.assertEqual(self.call(done(None)), (None, 1))
        self.assertFalse((self.vault / avvisi.CACHE).exists())

    def test_a_corrupt_or_future_cache_is_ignored_and_a_vault_without_local_state_just_skips_it(self):
        for text in ('non json', '{"quando": "x"}', '{"quando": 5000.0, "messaggio": "Teseo: vecchio"}', '[]'):
            (self.vault / avvisi.CACHE).write_text(text, encoding='utf-8')
            with self.subTest(text=text):
                self.assertEqual(self.call(done({'state': 'current', 'message': ''})), (None, 1))
        import shutil
        shutil.rmtree(self.vault / '.teseo/local')
        self.assertEqual(self.call(done({'state': 'behind', 'message': 'x'})), ('Teseo: x', 1))
        self.assertEqual(self.call(done({'state': 'behind', 'message': 'x'})), ('Teseo: x', 1))


class SessionStartHook(unittest.TestCase):
    def run_hook(self, source):
        import contextlib
        import io
        import modello_hook
        out = io.StringIO()
        with mock.patch.object(modello_hook.avvisi, 'remoti', return_value='Teseo: 2 aggiornamenti') as notice, \
                mock.patch.object(modello_hook, 'avviso', return_value=None), contextlib.redirect_stdout(out):
            modello_hook.inizio_sessione({'source': source, 'model': 'claude-sonnet-5-5'}, {}, {}, {})
        return notice.called, out.getvalue()

    def test_the_notice_runs_on_startup_and_resume_but_not_on_clear_or_compact(self):
        for source, expected in (('startup', True), ('resume', True), ('clear', False), ('compact', False)):
            with self.subTest(source=source):
                called, output = self.run_hook(source)
                self.assertEqual((called, 'aggiornamenti' in output), (expected, expected))


if __name__ == '__main__':
    unittest.main()
