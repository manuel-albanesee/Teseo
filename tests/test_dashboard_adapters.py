"""Probe senza sessioni AI e handoff dal solo runtime fidato."""
import _shortpath  # noqa: F401
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest import mock

from kit.dashboard.adapters import ManualAdapter, _which, default_adapters


class Adapters(unittest.TestCase):
    def test_version_probe_never_launches_a_model_or_shell(self):
        for name in ('codex','claude','copilot'):
            with self.subTest(name=name),mock.patch('shutil.which',return_value='C:/trusted/'+name+'.exe'),mock.patch('subprocess.run') as run:
                run.return_value=subprocess.CompletedProcess([],0,b'1.2.3\n',b'')
                probe=ManualAdapter(name).probe()
                self.assertEqual(probe['version'],'1.2.3')
                self.assertFalse(probe['automatic_launch'])
                self.assertFalse(probe['verified_isolation'])
                self.assertEqual(run.call_args.args[0],['C:/trusted/'+name+'.exe','--version'])
                self.assertFalse(run.call_args.kwargs['shell'])
                self.assertEqual(run.call_args.kwargs['timeout'],8)

    def test_absent_wrapper_or_timeout_uses_manual_fallback(self):
        with mock.patch('shutil.which',return_value=None),mock.patch('subprocess.run') as run:
            self.assertFalse(ManualAdapter('codex').probe()['installed'])
            run.assert_not_called()
        with mock.patch('shutil.which',return_value='C:/wrapper.cmd'),mock.patch('subprocess.run') as run:
            self.assertEqual(ManualAdapter('copilot').probe()['error'],'wrapper_not_executed')
            run.assert_not_called()
        with mock.patch('shutil.which',return_value='C:/claude.exe'),mock.patch('subprocess.run',side_effect=subprocess.TimeoutExpired('claude',8)):
            self.assertEqual(ManualAdapter('claude').probe()['error'],'version_unavailable')

    def test_handoff_contains_real_skill_and_no_native_callback_promise(self):
        with tempfile.TemporaryDirectory() as folder:
            workspace=Path(folder)/'workspace';workspace.mkdir()
            for name,adapter in default_adapters().items():
                result=adapter.prepare(workspace,Path(folder)/'request.json',{'scope':['wiki/'],'inputs':['raw/a.txt']},'lint')
                text=(workspace/'HANDOFF.md').read_text(encoding='utf-8')
                self.assertIn('Non correggere silenziosamente',text)
                self.assertIn('awaiting_user',text)
                self.assertIn('teseo_receipt.py',result['completion_command'])
                self.assertEqual(result['adapter'],name)
                self.assertFalse(result['automatic_launch'])
                self.assertFalse(adapter.cancel({})['external_session_stopped'])

    def test_executable_lookup_ignores_current_directory_and_relative_path_entries(self):
        seen = []
        def fake_which(candidate):
            seen.append(candidate)
            return None
        with mock.patch.dict('os.environ', {'PATH': os.pathsep.join(['', '.', 'relative', str(Path(tempfile.gettempdir()).resolve())])}),                 mock.patch('shutil.which', side_effect=fake_which):
            self.assertIsNone(_which('codex'))
        self.assertEqual(len(seen), 1)
        self.assertTrue(Path(seen[0]).is_absolute())
