"""Fase 0 di doc/17: KPI di coerenza (coerenza.py) e stabilità fra parafrasi del banco (banco.py, misura.py)."""
import _shortpath  # noqa: F401
from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

KIT = Path(__file__).resolve().parents[1] / 'kit'
sys.path.insert(0, str(KIT / 'graph'))
import banco  # noqa: E402
import build_graph  # noqa: E402
import coerenza  # noqa: E402
import misura  # noqa: E402
from graph_db import connect_graph  # noqa: E402


class VaultEsempio(unittest.TestCase):
    """Il vault d'esempio del kit in una cartella temporanea, con grafo e banco."""

    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.vault = Path(temp.name)
        shutil.copytree(KIT / 'esempio/wiki', self.vault / 'wiki')
        for nome in ('Wiki reference.md', 'index.md', 'log.md'):
            shutil.copy(KIT / 'vault' / nome, self.vault / nome)
        (self.vault / '.graph').mkdir()
        self.banco = self.vault / '.graph/banco.json'
        shutil.copy(KIT / 'esempio/banco.json', self.banco)
        self.db_path = self.vault / '.graph/graph.sqlite'
        with redirect_stdout(io.StringIO()):
            build_graph.costruisci(self.vault, self.db_path)
        self.db = connect_graph(self.db_path)
        self.addCleanup(self.db.close)
        self.nomi = coerenza.nomi_del_grafo(self.db)


class Jaccard(unittest.TestCase):
    def test_jaccard(self):
        self.assertAlmostEqual(coerenza.jaccard({'a', 'b'}, {'b', 'c'}), 1 / 3)
        self.assertEqual(coerenza.jaccard(set(), set()), 1.0)
        self.assertEqual(coerenza.jaccard({'a'}, set()), 0.0)


class Menzioni(VaultEsempio):
    def test_nomi_del_grafo_solo_pagine_della_wiki(self):
        self.assertEqual(self.nomi['anna rossi'], ('Anna Rossi', True))
        self.assertEqual(self.nomi['rossi anna'], ('Anna Rossi', False))      # alias
        self.assertEqual(self.nomi['service desk'], ('ServiceDesk', False))   # variante grafica
        self.assertNotIn('manuale rilascio', self.nomi)                       # fonte, non pagina della wiki

    def test_nomi_canonici(self):
        self.assertEqual(coerenza.menzioni('Anna Rossi e il Modulo fatture', self.nomi),
                         [('Anna Rossi', True), ('Modulo fatture', True)])

    def test_alias_e_variante_non_sono_canonici(self):
        self.assertEqual(coerenza.menzioni('Scrivi a Rossi Anna dal service desk.', self.nomi),
                         [('Anna Rossi', False), ('ServiceDesk', False)])

    def test_vince_la_forma_piu_lunga(self):
        # «file delle fatture» (alias) contiene «fatture» (alias): una sola menzione, la più lunga
        self.assertEqual(coerenza.menzioni('il file delle fatture non arriva', self.nomi),
                         [('Modulo fatture', False)])

    def test_maiuscole_e_accenti_non_contano(self):
        self.assertEqual(coerenza.menzioni('ANNA ROSSÌ risponde', self.nomi), [('Anna Rossi', True)])

    def test_parola_comune_solo_con_la_maiuscola(self):
        nomi = {'portale': ('Portale', True)}
        self.assertEqual(coerenza.menzioni('il portale è giù', nomi), [])
        self.assertEqual(coerenza.menzioni('il Portale è giù', nomi), [('Portale', True)])

    def test_forma_di_piu_pagine_si_scarta(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        import sqlite3
        db = sqlite3.connect(Path(temp.name) / 'g.sqlite')
        self.addCleanup(db.close)
        db.executescript("""
            CREATE TABLE entities (id TEXT PRIMARY KEY, tipo TEXT, descrizione TEXT, path TEXT, tags TEXT, aggiornato TEXT);
            CREATE TABLE aliases (entity_id TEXT, alias TEXT);
            CREATE TABLE varianti (entity_id TEXT, variante TEXT);
            INSERT INTO entities VALUES ('Alfa', 'sistema', '', 'wiki/Alfa.md', '', ''),
                                        ('Beta', 'sistema', '', 'wiki/Beta.md', '', '');
            INSERT INTO aliases VALUES ('Alfa', 'gemello'), ('Beta', 'gemello'), ('Alfa', 'Alfa');""")
        nomi = coerenza.nomi_del_grafo(db)
        self.assertNotIn('gemello', nomi)
        self.assertEqual(nomi['alfa'], ('Alfa', True))   # l'alias uguale al nome resta canonico

    def test_coerenza_nomi(self):
        risposte = [{'risposta': 'Anna Rossi segue il Modulo fatture'},
                    {'risposta': 'chiedi a Rossi Anna, referente di Modulo fatture'}]
        self.assertEqual(coerenza.coerenza_nomi(risposte, self.nomi),
                         {'menzioni': 4, 'canoniche': 3, 'quota': 0.75})

    def test_coerenza_senza_menzioni(self):
        self.assertEqual(coerenza.coerenza_nomi([{'risposta': 'non lo so'}], self.nomi),
                         {'menzioni': 0, 'canoniche': 0, 'quota': None})


class Risposte(VaultEsempio):
    def scrivi(self, cartella, nome, dati):
        (cartella / nome).write_text(dati if isinstance(dati, str) else json.dumps(dati), encoding='utf-8')

    def test_leggi_risposte(self):
        cartella = self.vault / 'risposte'
        cartella.mkdir()
        self.scrivi(cartella, '01-grafo-2.json', {'risposta': 'Modulo fatture', 'corretta': False})
        self.scrivi(cartella, '01-grafo-1.json', {'risposta': 'Anna Rossi', 'corretta': True})
        self.scrivi(cartella, '01-hook-1.json', {'risposta': 'Anna Rossi', 'regex': [True, False]})
        self.scrivi(cartella, '01-hook-1.md', 'Anna Rossi')        # copia leggibile scritta da --hook: ignorata
        self.scrivi(cartella, '02-ricerca-1.json', '{rotto')
        self.scrivi(cartella, '03-ricerca-1.json', {'corretta': True})   # senza «risposta»
        risposte, illeggibili = coerenza.leggi_risposte(cartella)
        self.assertEqual(sorted(risposte), [(1, 'grafo'), (1, 'hook')])
        self.assertEqual([r['risposta'] for r in risposte[(1, 'grafo')]], ['Anna Rossi', 'Modulo fatture'])
        self.assertEqual([r['esito'] for r in risposte[(1, 'grafo')]], [True, False])
        self.assertEqual(risposte[(1, 'hook')][0]['esito'], False)       # all(regex)
        self.assertEqual(illeggibili, ['02-ricerca-1.json', '03-ricerca-1.json'])

    def test_stabilita_giri(self):
        giri = [{'risposta': 'Anna Rossi e Modulo fatture', 'esito': True},
                {'risposta': 'Modulo fatture, Anna Rossi', 'esito': True},
                {'risposta': 'Anna Rossi', 'esito': False}]
        stabile = [{'risposta': 'ServiceDesk', 'esito': True}, {'risposta': 'ServiceDesk', 'esito': True}]
        un_giro = [{'risposta': 'Gestionale', 'esito': True}]
        risposte = {(1, 'grafo'): giri, (2, 'grafo'): stabile, (3, 'grafo'): un_giro, (1, 'ricerca'): un_giro}
        esito = coerenza.stabilita_giri(risposte, self.nomi)
        self.assertEqual(esito['grafo']['domande'], 2)               # solo le domande con almeno 2 giri
        self.assertAlmostEqual(esito['grafo']['jaccard_medio'], ((1 + 0.5 + 0.5) / 3 + 1) / 2)
        self.assertEqual(esito['grafo']['esito_stabile'], 1)
        self.assertEqual(esito['ricerca'], {'domande': 0, 'jaccard_medio': None, 'esito_stabile': 0})

    def cli(self, *argomenti):
        return subprocess.run([sys.executable, str(KIT / 'graph/coerenza.py'), *argomenti],
                              capture_output=True, text=True, encoding='utf-8')

    def test_cli_cartella_vuota_esce_con_2(self):
        cartella = self.vault / 'vuota'
        cartella.mkdir()
        run = self.cli('--risposte', str(cartella), '--db', str(self.db_path))
        self.assertEqual(run.returncode, 2, run.stdout + run.stderr)

    def test_cli_una_riga_per_condizione(self):
        cartella = self.vault / 'risposte'
        cartella.mkdir()
        for giro, risposta in enumerate(('Anna Rossi', 'Rossi Anna'), 1):
            self.scrivi(cartella, f'01-grafo-{giro}.json', {'risposta': risposta, 'corretta': True})
        self.scrivi(cartella, '01-ricerca-1.json', {'risposta': 'Modulo fatture', 'corretta': False})
        run = self.cli('--risposte', str(cartella), '--db', str(self.db_path))
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        righe = run.stdout.splitlines()
        self.assertIn('grafo: nomi canonici 1/2 (50%) · stabilità fra giri 1.00 · esito stabile 1/1 · 2 risposte', righe)
        self.assertIn('ricerca: nomi canonici 1/1 (100%) · stabilità fra giri n/d · esito stabile 0/0 · 1 risposte', righe)
        dati = json.loads(self.cli('--risposte', str(cartella), '--db', str(self.db_path), '--json').stdout)
        self.assertEqual(dati['condizioni']['grafo']['coerenza']['quota'], 0.5)
        self.assertEqual(dati['illeggibili'], [])


class Parafrasi(VaultEsempio):
    def voci(self):
        return json.loads(self.banco.read_text(encoding='utf-8'))

    def salva(self, voci):
        self.banco.write_text(json.dumps(voci, ensure_ascii=False), encoding='utf-8')

    def misura(self):
        uscita = io.StringIO()
        with redirect_stdout(uscita):
            esiti = misura.misura_banco(self.db, self.banco)
        return esiti, uscita.getvalue()

    def errori(self):
        return [t for livello, t in banco.verifica(self.db, self.banco) if livello == 'ERRORE']

    def test_il_banco_del_kit_ha_parafrasi_valide(self):
        voci = self.voci()
        self.assertGreaterEqual(sum(1 for v in voci if v.get('parafrasi')), 2)
        self.assertEqual(self.errori(), [])
        avvisi = [t for livello, t in banco.verifica(self.db, self.banco) if livello == 'AVVISO']
        self.assertFalse([t for t in avvisi if 'parafrasi' in t], avvisi)

    def test_parafrasi_non_lista(self):
        voci = self.voci()
        voci[0]['parafrasi'] = 'una sola domanda'
        self.salva(voci)
        self.assertIn('voce 1 «a chi chiedo il ticket della settimana per poter r»: «parafrasi» deve essere una lista '
                      'di domande', self.errori())
        esiti, testo = self.misura()
        self.assertIsNone(esiti)
        self.assertIn('banco non valido', testo)

    def test_parafrasi_uguale_a_una_domanda(self):
        voci = self.voci()
        voci[0]['parafrasi'] = [voci[2]['domanda'].upper()]
        voci[1]['parafrasi'] = ['Dove si aprono le segnalazioni']
        self.salva(voci)
        errori = self.errori()
        self.assertTrue(any(e.startswith('voce 1 ') and 'parafrasi uguale alla voce 3' in e for e in errori), errori)
        self.assertTrue(any(e.startswith('voce 2 ') and 'parafrasi uguale alla voce 2' in e for e in errori), errori)

    def test_parafrasi_ripetuta(self):
        voci = self.voci()
        voci[2]['parafrasi'] = ['che codice breve va nei ticket?', 'Che codice breve va nei ticket']
        self.salva(voci)
        self.assertTrue(any('parafrasi ripetuta' in e for e in self.errori()), self.errori())

    def test_parafrasi_con_le_parole_del_titolo_e_un_avviso(self):
        voci = self.voci()
        voci[2]['parafrasi'] = ["qual è l'acronimo del progetto?"]
        self.salva(voci)
        avvisi = [t for livello, t in banco.verifica(self.db, self.banco) if livello == 'AVVISO']
        self.assertTrue(any('parafrasi' in t and 'Acronimo del progetto' in t for t in avvisi), avvisi)

    def test_righe_del_banco_identiche_con_e_senza_parafrasi(self):
        _, con = self.misura()
        self.salva([{k: v for k, v in voce.items() if k != 'parafrasi'} for voce in self.voci()])
        _, senza = self.misura()
        def senza_ms(testo):  # la colonna ms varia da un lancio all'altro
            righe = []
            for r in testo.splitlines():
                campi = r[55:].split()
                righe.append(r[:55] + ' '.join(campi[:4] + campi[5:]) if len(campi) > 4 and campi[4].isdigit() else r)
            return righe
        self.assertEqual([r for r in senza_ms(con) if not r.startswith('parafrasi:')], senza_ms(senza))
        self.assertNotIn('parafrasi:', senza)

    def test_stabilita_fra_parafrasi(self):
        voci = self.voci()
        voci[0]['parafrasi'] = [voci[0]['domanda'] + ' grazie']   # stesse pagine, stessi semi
        voci[2]['parafrasi'] = ['come va oggi?']                  # nessuna pagina
        for voce in voci[1:2] + voci[3:]:
            voce.pop('parafrasi', None)
        self.salva(voci)
        esiti, testo = self.misura()
        self.assertEqual(esiti[0]['stabilita'], 1.0)
        self.assertEqual(esiti[0]['stesso_seme'], 1)
        self.assertEqual(esiti[0]['parafrasi'][0]['domanda'], voci[0]['parafrasi'][0])
        attesa = coerenza.jaccard(set(esiti[2]['portate']), set())
        self.assertEqual(esiti[2]['stabilita'], attesa)
        self.assertNotIn('stabilita', esiti[1])
        self.assertIn(f'parafrasi: 2 voci, 2 parafrasi · stabilità media {(1.0 + attesa) / 2:.2f} · stesso seme '
                      f'{1 + (not esiti[2]["semi"])}/2', testo)

    def test_confronto_della_stabilita(self):
        prima = [{'domanda': 'a', 'attese': [], 'mancanti': [], 'portate': [], 'token': 1, 'stabilita': 0.5},
                 {'domanda': 'b', 'attese': [], 'mancanti': [], 'portate': [], 'token': 1}]
        dopo = [{'domanda': 'a', 'attese': [], 'mancanti': [], 'portate': [], 'token': 1, 'stabilita': 0.75},
                {'domanda': 'b', 'attese': [], 'mancanti': [], 'portate': [], 'token': 1, 'stabilita': 1.0}]
        uscita = io.StringIO()
        with redirect_stdout(uscita):
            misura.confronta_banco(dopo, prima)
        righe = uscita.getvalue().splitlines()
        self.assertEqual(righe[-1], 'stabilità fra parafrasi: 0.50 → 0.75 (+0.25)')

    def test_salvataggio_vecchio_senza_stabilita(self):
        vecchio = [{'domanda': 'a', 'attese': [], 'mancanti': [], 'portate': [], 'token': 1}]
        uscita = io.StringIO()
        with redirect_stdout(uscita):
            misura.confronta_banco([dict(vecchio[0], stabilita=1.0)], vecchio)
        self.assertNotIn('stabilità fra parafrasi', uscita.getvalue())


if __name__ == '__main__':
    unittest.main()
