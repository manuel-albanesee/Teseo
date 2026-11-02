"""Voce B3 di doc/16: una categoria nominata nella domanda è un solo seme e un solo fatto aggregato."""
import _shortpath  # noqa: F401
from contextlib import redirect_stdout
import io
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from unittest import mock

KIT = Path(__file__).resolve().parents[1] / 'kit'
sys.path.insert(0, str(KIT / 'graph'))
import build_graph  # noqa: E402
import recall  # noqa: E402
import recall_hook  # noqa: E402
from graph_db import connect_graph  # noqa: E402

SCHEMA = """# Schema

## Tipi ammessi
| Tipo | Descrizione |
| --- | --- |
| `sistema` | Strumenti |
| `servizio` | Servizi |
| `processo` | Attività |
| `fonte` | Fonti |

## Relazioni tipizzate
| Relazione | Da (tipo) | A (tipo) | Significato | Esempio |
| --- | --- | --- | --- | --- |
| `usa` | processo | sistema | X funziona tramite Y | A → B |

## Categorie
| Categoria | Più ampia | Descrizione |
| --- | --- | --- |
| amministrazione | | Processi amministrativi |
| fatturazione | amministrazione | Fatture |
| ciclo-passivo | fatturazione | Fatture ricevute |
| rilasci | | Messa in produzione |
| generale | | Tutto |

## Chiavi delle fonti
| `nota-utente` | Precisazione |
"""


def pagina(tipo, tags=()):
    etichette = 'tags: [%s]\n' % ', '.join(tags) if tags else ''
    return '---\ntipo: %s\n%s---\ntesto\n' % (tipo, etichette)


PAGINE = {
    'Fatture': pagina('servizio', ['fatturazione']),
    'Fornitori': pagina('processo', ['ciclo-passivo']),
    'Ordini': pagina('sistema', ['ciclo-passivo']),
    'Gestionale': pagina('sistema', ['amministrazione']),
    'Console': pagina('sistema', ['rilasci']),
    'Rilascio': pagina('processo', ['rilasci']),
    'Extra1': pagina('sistema', ['rilasci']),
    'Extra2': pagina('sistema', ['rilasci']),
    **{f'Filler{i}': pagina('sistema', ['generale']) for i in range(10)},
}


class Base(unittest.TestCase):
    def vault(self, schema=SCHEMA, **extra):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        vault = Path(temp.name)
        (vault / 'wiki').mkdir()
        (vault / '.graph').mkdir()
        (vault / 'Wiki reference.md').write_text(schema, encoding='utf-8')
        for nome in ('index.md', 'log.md'):
            (vault / nome).write_text('# ' + nome + '\n', encoding='utf-8')
        for nome, testo in {**PAGINE, **extra}.items():
            (vault / 'wiki' / (nome + '.md')).write_text(testo, encoding='utf-8')
        with redirect_stdout(io.StringIO()):
            build_graph.costruisci(vault, vault / '.graph/graph.sqlite')
        db = connect_graph(vault / '.graph/graph.sqlite')
        self.addCleanup(db.close)
        return db

    def categorie(self, db, domanda):
        semi, fatti, omessi = recall.richiama(db, domanda)
        return [s for s in semi if s[1].startswith('categoria')], [f for f in fatti if f['tipo'] == 'categoria']


class Seme(Base):
    def test_un_seme_e_un_solo_fatto(self):
        db = self.vault()
        semi, fatti = self.categorie(db, 'che cosa comprende la fatturazione?')
        self.assertEqual(semi, [('fatturazione', 'categoria, parte di amministrazione', 'Fatture')])
        self.assertEqual(len(fatti), 1)
        self.assertEqual(fatti[0]['s'], 'fatturazione')
        self.assertEqual(fatti[0]['t'][0], 'Fatture')  # la pagina del tag diretto prima delle sottocategorie
        self.assertEqual(sorted(fatti[0]['t']), ['Fatture', 'Fornitori', 'Ordini'])
        self.assertEqual(fatti[0]['omesse'], 0)

    def test_il_contesto_ha_il_seme_e_il_fatto_aggregato(self):
        db = self.vault()
        semi, fatti, omessi = recall.richiama(db, 'che cosa comprende la fatturazione?')
        info = {id_: (tipo, descr) for id_, tipo, descr in db.execute('SELECT id, tipo, descrizione FROM entities')}
        testo = recall.formatta(semi, fatti, info, omessi)
        self.assertIn('- fatturazione [categoria, parte di amministrazione]: Fatture', testo)
        self.assertIn('- fatturazione → categoria → 3 pagine (Fatture, ', testo)
        self.assertEqual(testo.count('→ categoria →'), 1)

    def test_una_categoria_radice_non_ha_il_genitore(self):
        semi, _ = self.categorie(self.vault(), 'cosa c\'è in rilasci?')
        self.assertEqual(semi[0][:2], ('rilasci', 'categoria'))

    def test_forma_ridotta_a_radici(self):
        semi, _ = self.categorie(self.vault(), 'quali sono le fatturazioni?')
        self.assertEqual([s[0] for s in semi], ['fatturazione'])

    def test_nome_composto(self):
        semi, fatti = self.categorie(self.vault(), 'chi gestisce il ciclo passivo?')
        self.assertEqual([s[0] for s in semi], ['ciclo-passivo'])
        self.assertEqual(sorted(fatti[0]['t']), ['Fornitori', 'Ordini'])

    def test_senza_la_categoria_nella_domanda_nulla(self):
        semi, fatti = self.categorie(self.vault(), 'che cosa fa il Gestionale?')
        self.assertEqual((semi, fatti), ([], []))


class Regole(Base):
    def test_troppo_generica_non_fa_da_seme(self):
        # «generale» ha 10 pagine su 18: oltre SOGLIA_CATEGORIA
        semi, fatti = self.categorie(self.vault(), 'cosa riguarda il generale?')
        self.assertEqual((semi, fatti), ([], []))

    def test_la_soglia_si_misura_sulle_pagine_del_vault(self):
        with mock.patch.object(recall, 'SOGLIA_CATEGORIA', 0.9):
            semi, _ = self.categorie(self.vault(), 'cosa riguarda il generale?')
        self.assertEqual([s[0] for s in semi], ['generale'])

    def test_il_nome_di_una_pagina_vince(self):
        db = self.vault(Rilasci=pagina('processo'))
        semi, fatti, _ = recall.richiama(db, 'cosa c\'è in rilasci?')
        self.assertIn('Rilasci', [s[0] for s in semi])
        self.assertEqual([s for s in semi if s[1].startswith('categoria')], [])
        self.assertEqual([f for f in fatti if f['tipo'] == 'categoria'], [])

    def test_pagina_e_categoria_insieme(self):
        db = self.vault()
        semi, fatti, _ = recall.richiama(db, 'il Gestionale e la fatturazione')
        self.assertEqual([s[0] for s in semi], ['Gestionale', 'fatturazione'])

    def test_tetto_e_conteggio_delle_omesse(self):
        with mock.patch.object(recall, 'MAX_CATEGORIA', 2):
            _, fatti = self.categorie(self.vault(), 'che cosa comprende la fatturazione?')
        self.assertEqual(fatti[0]['t'], ['Fatture', 'Fornitori'])
        self.assertEqual(fatti[0]['omesse'], 1)
        info = {'Fatture': ('servizio', '')}
        self.assertIn('· 1 altre omesse', recall.formatta([('fatturazione', 'categoria', '')], fatti, info))

    def test_diversita_nella_scelta(self):
        with mock.patch.object(recall, 'MAX_CATEGORIA', 3):
            _, fatti = self.categorie(self.vault(), 'cosa c\'è in rilasci?')
        # senza la diversità sarebbero le prime tre in ordine alfabetico: Console, Extra1, Extra2 (tutte sistema)
        self.assertEqual(fatti[0]['t'], ['Console', 'Rilascio', 'Extra1'])

    def test_le_pagine_per_entropia_non_contano(self):
        db = self.vault(Sintesi=pagina('processo', ['fatturazione', 'entropia']))
        _, fatti = self.categorie(db, 'che cosa comprende la fatturazione?')
        self.assertNotIn('Sintesi', fatti[0]['t'])


class Compatibilita(Base):
    def test_senza_categorie_nulla_cambia(self):
        schema = SCHEMA.replace(SCHEMA[SCHEMA.index('## Categorie'):SCHEMA.index('## Chiavi')], '')
        db = self.vault(schema, **{n: pagina('sistema') for n in PAGINE})
        semi, fatti = self.categorie(db, 'che cosa comprende la fatturazione?')
        self.assertEqual((semi, fatti), ([], []))

    def test_grafo_senza_la_tabella(self):
        db = sqlite3.connect(':memory:')
        self.addCleanup(db.close)
        db.executescript("CREATE TABLE entities (id TEXT, path TEXT, tags TEXT);")
        self.assertEqual(recall.categorie_nominate(db, 'la fatturazione'), [])

    def test_il_ripiego_sul_testo_non_scatta_se_la_domanda_nomina_una_categoria(self):
        db = self.vault()
        with mock.patch.object(recall_hook, 'per_testo_a_cascata', return_value=['X']):
            self.assertEqual(recall_hook.ripiego_testo(db, 'che cosa comprende la fatturazione?', []), [])
            self.assertEqual(recall_hook.ripiego_testo(db, 'che cosa comprende la contabilità?', []), ['X'])


if __name__ == '__main__':
    unittest.main()
