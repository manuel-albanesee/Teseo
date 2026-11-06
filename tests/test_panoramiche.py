"""Voce B4 di doc/16: panoramiche di categoria in sintesi.py, nella verifica e nel recall."""
import _shortpath  # noqa: F401
from pathlib import Path
import sys
import unittest
from unittest import mock

KIT = Path(__file__).resolve().parents[1] / 'kit'
sys.path.insert(0, str(KIT / 'graph'))
import recall  # noqa: E402
import sintesi  # noqa: E402
from test_categoria_seme import SCHEMA, Base  # noqa: E402

SCHEMA_B4 = (SCHEMA.replace('| `fonte` | Fonti |', '| `riferimento` | Riferimenti |\n| `fonte` | Fonti |')
             .replace('| `usa` | processo | sistema | X funziona tramite Y | A → B |',
                      '| `usa` | processo | sistema | X funziona tramite Y | A → B |\n'
                      '| `riguarda` | riferimento | qualsiasi | X parla di Y | A → B |'))
SENZA_CATEGORIE = SCHEMA_B4.split('## Categorie')[0] + '## Chiavi delle fonti' + SCHEMA_B4.split('## Chiavi delle fonti')[1]
TUTTE_LE_SINTESI = 'Che cosa comprende fatturazione?'


def cartella(db):
    """La cartella .graph del vault di prova, da cui sintesi legge domande.sqlite e il vault."""
    return next(p for p in Path(db.execute('PRAGMA database_list').fetchone()[2]).parents if p.name == '.graph')


def panoramica(tags, link=('Fatture', 'Fornitori', 'Ordini'), domanda=TUTTE_LE_SINTESI):
    etichette = ', '.join(tags)
    return ('---\ntipo: riferimento\ntags: [%s]\nriguarda: [%s]\n---\n'
            '> Informazioni generate da entropia del vault. Risponde a: «%s»\n\n%s\n'
            % (etichette, ', '.join(f'"[[{p}]]"' for p in link), domanda, ' '.join(f'[[{p}]]' for p in link)))


class Famiglia(Base):
    def candidate(self, db, tutte=True):
        qui = cartella(db)
        return [c for c in sintesi.candidate(db, qui, tutte) if c['famiglia'] == 'categoria']

    def test_una_domanda_per_categoria_con_abbastanza_pagine(self):
        domande = {c['domanda']: c['pagine'] for c in self.candidate(self.vault(SCHEMA_B4))}
        # ciclo-passivo ha 2 pagine (meno di MIN_ALTRE + 1), generale supera SOGLIA_CATEGORIA
        self.assertEqual(sorted(domande), ['Che cosa comprende amministrazione?', 'Che cosa comprende fatturazione?',
                                           'Che cosa comprende rilasci?'])
        self.assertEqual(domande['Che cosa comprende fatturazione?'], ['Fatture', 'Fornitori', 'Ordini'])
        self.assertEqual(domande['Che cosa comprende amministrazione?'], ['Gestionale', 'Fatture', 'Fornitori', 'Ordini'])

    def test_percorso_categoria_e_sottocategoria(self):
        c = next(c for c in self.candidate(self.vault(SCHEMA_B4)) if c['domanda'] == TUTTE_LE_SINTESI)
        self.assertEqual(c['percorso'], ['Fatture → categoria → fatturazione', 'Fornitori → sottocategoria → fatturazione',
                                         'Ordini → sottocategoria → fatturazione'])
        self.assertEqual(c['categoria'], 'fatturazione')
        self.assertEqual(c['partenza'], 'Fatture')

    def test_ultime_per_priorita(self):
        db = self.vault(SCHEMA_B4)
        qui = cartella(db)
        famiglie = [c['famiglia'] for c in sintesi.candidate(db, qui, tutte=True)]
        self.assertEqual(famiglie[-3:], ['categoria'] * 3)
        self.assertEqual(sintesi.PRIORITA['categoria'], max(sintesi.PRIORITA.values()))

    def test_soglia_come_nel_recall(self):
        with mock.patch.object(recall, 'SOGLIA_CATEGORIA', 0.9):
            domande = [c['domanda'] for c in self.candidate(self.vault(SCHEMA_B4))]
        self.assertIn('Che cosa comprende generale?', domande)

    def test_minimo_di_pagine(self):
        with mock.patch.object(sintesi, 'MIN_ALTRE', 1):
            domande = [c['domanda'] for c in self.candidate(self.vault(SCHEMA_B4))]
        self.assertIn('Che cosa comprende ciclo-passivo?', domande)

    def test_senza_la_sezione_nessuna_panoramica(self):
        self.assertEqual(self.candidate(self.vault(SENZA_CATEGORIE)), [])

    def test_le_pagine_per_entropia_non_sono_nella_risposta(self):
        db = self.vault(SCHEMA_B4, **{'Panoramica fatture': panoramica(['entropia', 'fatturazione'])})
        c = next(c for c in self.candidate(db) if c['domanda'] == TUTTE_LE_SINTESI)
        self.assertNotIn('Panoramica fatture', c['pagine'])

    def test_coperta_dalla_panoramica(self):
        db = self.vault(SCHEMA_B4, **{'Panoramica fatture': panoramica(['entropia', 'fatturazione'])})
        c = next(c for c in self.candidate(db) if c['domanda'] == TUTTE_LE_SINTESI)
        self.assertEqual(c['coperta_da'], 'Panoramica fatture')
        self.assertNotIn(TUTTE_LE_SINTESI, [c['domanda'] for c in self.candidate(db, tutte=False)])


class Verifica(Base):
    def problemi(self, db):
        qui = cartella(db)
        return sintesi.verifica(db, qui)

    def test_panoramica_con_il_tag_della_categoria(self):
        db = self.vault(SCHEMA_B4, **{'Panoramica fatture': panoramica(['entropia', 'fatturazione'])})
        self.assertEqual(self.problemi(db), [])

    def test_panoramica_senza_il_tag_della_categoria(self):
        db = self.vault(SCHEMA_B4, **{'Panoramica fatture': panoramica(['entropia'])})
        self.assertEqual(self.problemi(db),
                         [('Panoramica fatture', 'manca il tag «fatturazione»: il recall non la trova dalla categoria')])


class Recall(Base):
    def semi(self, db, domanda):
        return [s[0] for s in recall.richiama(db, domanda)[0]]

    def test_la_panoramica_parte_con_la_categoria(self):
        db = self.vault(SCHEMA_B4, **{'Panoramica fatture': panoramica(['entropia', 'fatturazione'])})
        semi, fatti, _ = recall.richiama(db, 'che cosa comprende la fatturazione?')
        self.assertEqual([s[0] for s in semi], ['Panoramica fatture', 'fatturazione'])
        self.assertEqual(len([f for f in fatti if f['tipo'] == 'categoria']), 1)   # il fatto aggregato resta
        portate = {t for f in fatti if f['s'] == 'Panoramica fatture' for t in f['t']}
        self.assertTrue({'Fatture', 'Fornitori', 'Ordini'} <= portate)

    def test_solo_il_tag_diretto(self):
        db = self.vault(SCHEMA_B4, **{'Panoramica ciclo': panoramica(['entropia', 'ciclo-passivo'], ('Fornitori', 'Ordini'),
                                                                     'Che cosa comprende ciclo-passivo?')})
        self.assertNotIn('Panoramica ciclo', self.semi(db, 'che cosa comprende la fatturazione?'))
        self.assertIn('Panoramica ciclo', self.semi(db, 'chi gestisce il ciclo passivo?'))

    def test_un_altra_categoria_non_la_porta(self):
        db = self.vault(SCHEMA_B4, **{'Panoramica fatture': panoramica(['entropia', 'fatturazione'])})
        self.assertNotIn('Panoramica fatture', self.semi(db, 'cosa c\'è in rilasci?'))

    def test_una_pagina_normale_con_il_tag_non_parte(self):
        db = self.vault(SCHEMA_B4)
        self.assertEqual(self.semi(db, 'che cosa comprende la fatturazione?'), ['fatturazione'])

    def test_senza_categoria_nella_domanda_come_prima(self):
        db = self.vault(SCHEMA_B4, **{'Panoramica fatture': panoramica(['entropia', 'fatturazione'])})
        self.assertEqual(self.semi(db, 'che cosa fa il Gestionale?'), ['Gestionale'])


if __name__ == '__main__':
    unittest.main()
