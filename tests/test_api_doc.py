"""doc/api.md deve essere sempre allineata ai docstring del codice."""
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class ApiDocAggiornata(unittest.TestCase):
    def test_check(self):
        run = subprocess.run([sys.executable, str(ROOT / "script" / "genera_api_doc.py"), "--check"],
                             capture_output=True, timeout=60)
        self.assertEqual(run.returncode, 0,
                         "doc/api.md non aggiornata: esegui python script/genera_api_doc.py\n"
                         + run.stdout.decode("utf-8", "replace"))

    def test_deterministica(self):
        run = subprocess.run([sys.executable, "-c",
                              "import sys; sys.path.insert(0, r'script'); "
                              "import genera_api_doc as g; print(repr(g.genera() == g.genera()))"],
                             cwd=ROOT, capture_output=True, timeout=60)
        self.assertIn("True", run.stdout.decode())


if __name__ == "__main__":
    unittest.main()
