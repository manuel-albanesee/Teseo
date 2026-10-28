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


if __name__ == '__main__':
    unittest.main()
