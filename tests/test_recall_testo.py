"""Ripiego sul testo a due giri (recall.per_testo_a_cascata) su un vault minimo costruito con build_graph.py."""
import _shortpath  # noqa: F401
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "kit/graph"))
import recall  # noqa: E402
from recall_hook import ripiego_testo  # noqa: E402

RIEMPITIVO = ("alfa bravo charlie delta echo foxtrot golf hotel india juliet kilo lima mike november oscar papa "
              "quebec romeo sierra tango uniform victor whiskey xray yankee zulu").split()


def parole(n, da=0):
    return " ".join(f"{RIEMPITIVO[(da + i) % len(RIEMPITIVO)]}{(da + i) // len(RIEMPITIVO)}" for i in range(n))


class RipiegoACascata(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix="teseo recall ")
        radice = Path(cls.temp.name)
        (radice / "wiki").mkdir()
        (radice / ".graph").mkdir()
        for sorgente in (ROOT / "kit/graph").glob("*.py"):
            shutil.copyfile(sorgente, radice / ".graph" / sorgente.name)
        (radice / "Wiki reference.md").write_text("Schema di prova", encoding="utf-8")
        pagine = {
            # «copertura» e «guardia» a 38 parole: fuori da FINESTRA_TESTO, dentro FINESTRA_TESTO_LARGA
            "Turni notturni": f"La copertura {parole(36, 100)} della guardia.",
            # le stesse parole a 70: fuori anche dal secondo giro
            "Piano annuale": f"La copertura {parole(68, 300)} della guardia.",
        }
        # abbastanza pagine perché bm25 superi MIN_SCORE_TESTO, come in un vault vero
        for i in range(80):
            pagine[f"Pagina {i}"] = parole(20, 600 + 25 * i)
        for titolo, corpo in pagine.items():
            (radice / "wiki" / f"{titolo}.md").write_text(f"---\ntipo: processo\n---\n{corpo}\n", encoding="utf-8")
        esito = subprocess.run([sys.executable, str(radice / ".graph/build_graph.py")], cwd=radice,
                               capture_output=True, timeout=60, env={**os.environ, "PYTHONIOENCODING": "utf-8"})
        assert esito.returncode == 0, esito.stderr.decode("utf-8", "replace")
        cls.db = sqlite3.connect(radice / ".graph/graph.sqlite")

    @classmethod
    def tearDownClass(cls):
        cls.db.close()
        cls.temp.cleanup()

    def test_secondo_giro_trova_parole_un_po_piu_lontane(self):
        domanda = "chi organizza la copertura della guardia?"
        self.assertEqual(recall.per_testo(self.db, domanda), [])
        self.assertEqual(recall.per_testo_a_cascata(self.db, domanda), ["Turni notturni"])
        self.assertEqual(ripiego_testo(self.db, domanda, []), ["Turni notturni"])

    def test_secondo_giro_non_scatta_con_semi_o_comandi(self):
        self.assertEqual(ripiego_testo(self.db, "chi organizza la copertura della guardia?", ["Pagina 0"]), [])
        self.assertEqual(ripiego_testo(self.db, "ok procedi", []), [])


if __name__ == "__main__":
    unittest.main()
