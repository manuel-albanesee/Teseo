"""Piano di ingest (kit/graph/piano.py): controllo deterministico del piano prima di scrivere le pagine."""
import _shortpath  # noqa: F401
import io
import json
from contextlib import redirect_stderr, redirect_stdout
import hashlib
from pathlib import Path
import shutil
import sys
import tempfile
import unittest

KIT = Path(__file__).resolve().parents[1] / 'kit'
sys.path.insert(0, str(KIT / 'graph'))
import build_graph
import piano

PIANO = """\
# Piano di ingest — raw/nuova-fonte.md

## Pagine da creare
- [[Finestra di rilascio]] — tipo: processo — orari e approvazioni (§2)

## Pagine da aggiornare
- [[Rilascio in produzione]] — aggiungere la finestra di rilascio

## Relazioni
- [[Rilascio in produzione]] → richiede → [[Finestra di rilascio]]

## Alias
- [[Finestra di rilascio]]: «slot di rilascio», «finestra»

## Contraddizioni con il vault
- nessuna
"""

TIPI = ('concetto', 'sistema', 'entita', 'persona', 'processo', 'progetto', 'episodio', 'fonte', 'documento', 'riferimento')


def sostituisci(testo, vecchio, nuovo):
    assert vecchio in testo, vecchio
    return testo.replace(vecchio, nuovo, 1)


class Base(unittest.TestCase):
    catalogo = False

    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.vault = Path(temp.name)
        shutil.copytree(KIT / 'esempio/wiki', self.vault / 'wiki')
        shutil.copytree(KIT / 'esempio/raw', self.vault / 'raw')
        (self.vault / 'raw/nuova-fonte.md').write_text('# Nuova fonte\n', encoding='utf-8')
        for nome in ('index.md', 'log.md'):
            shutil.copy(KIT / 'vault' / nome, self.vault / nome)
        schema = (KIT / 'vault/Wiki reference.md').read_text(encoding='utf-8')
        if self.catalogo:
            righe = ''.join(f'| `{t}` | tipo di prova |\n' for t in TIPI)
            schema = sostituisci(schema, '## Relazioni tipizzate', f'## Tipi ammessi\n\n| Tipo | Descrizione |\n| --- | --- |\n{righe}\n## Relazioni tipizzate')
        (self.vault / 'Wiki reference.md').write_text(schema, encoding='utf-8')
        (self.vault / '.graph').mkdir()
        with redirect_stdout(io.StringIO()):
            build_graph.costruisci(self.vault, self.vault / '.graph/graph.sqlite')

    def controlla(self, testo, nome='piano.md'):
        percorso = self.vault / nome
        percorso.write_text(testo, encoding='utf-8')
        return piano.controlla(self.vault, percorso)

    def codici(self, testo):
        return [p['codice'] for p in self.controlla(testo)]


class Forma(Base):
    def test_piano_valido(self):
        self.assertEqual(self.controlla(PIANO), [])

    def test_fonte_nel_titolo_deve_esistere_in_raw(self):
        self.assertIn('fonte_mancante', self.codici(sostituisci(PIANO, 'raw/nuova-fonte.md', 'raw/non-c-e.md')))
        self.assertIn('fonte_mancante', self.codici(sostituisci(PIANO, ' — raw/nuova-fonte.md', '')))
        self.assertIn('fonte_mancante', self.codici(sostituisci(PIANO, 'raw/nuova-fonte.md', 'raw/../wiki/Anna Rossi.md')))

    def test_sezioni_mancanti(self):
        for sezione in ('Pagine da creare', 'Pagine da aggiornare', 'Relazioni', 'Alias', 'Contraddizioni con il vault'):
            with self.subTest(sezione=sezione):
                senza = sostituisci(PIANO, f'## {sezione}', '## Altro')
                problemi = [p for p in self.controlla(senza) if p['codice'] == 'sezione_mancante']
                self.assertEqual(len(problemi), 1)
                self.assertIn(sezione, problemi[0]['messaggio'])

    def test_sezioni_vuote_sono_ammesse_se_dichiarate(self):
        vuoto = '# Piano di ingest — raw/nuova-fonte.md\n\n' + ''.join(
            f'## {s}\n- nessuna\n\n' for s in ('Pagine da creare', 'Pagine da aggiornare', 'Relazioni', 'Alias', 'Contraddizioni con il vault'))
        self.assertEqual(self.controlla(vuoto), [])

    def test_riga_senza_collegamento(self):
        self.assertIn('riga_non_valida', self.codici(sostituisci(PIANO, '- [[Rilascio in produzione]] — aggiungere', '- Rilascio — aggiungere')))

    def test_titoli_nei_blocchi_di_codice_non_contano(self):
        self.assertEqual(self.controlla(PIANO + '\n```\n## Altro\n- [[Pagina inventata]]\n```\n'), [])


class Pagine(Base):
    def test_da_creare_non_deve_esistere(self):
        problemi = self.controlla(sostituisci(PIANO, '[[Finestra di rilascio]] — tipo', '[[Anna Rossi]] — tipo'))
        self.assertIn('da_creare_esiste', [p['codice'] for p in problemi])
        self.assertIn('Pagine da aggiornare', [p['messaggio'] for p in problemi if p['codice'] == 'da_creare_esiste'][0])

    def test_da_creare_senza_tipo(self):
        self.assertIn('da_creare_senza_tipo', self.codici(sostituisci(PIANO, ' — tipo: processo', '')))

    def test_da_aggiornare_deve_esistere(self):
        self.assertIn('da_aggiornare_inesistente', self.codici(sostituisci(PIANO, '- [[Rilascio in produzione]] — aggiungere', '- [[Pagina inventata]] — aggiungere')))

    def test_maiuscole_come_nel_builder(self):
        self.assertEqual(self.controlla(sostituisci(PIANO, '- [[Rilascio in produzione]] — aggiungere', '- [[rilascio in produzione]] — aggiungere')), [])

    def test_duplicati(self):
        doppio = sostituisci(PIANO, '## Pagine da aggiornare', '- [[Finestra di rilascio]] — tipo: processo — di nuovo\n\n## Pagine da aggiornare')
        self.assertIn('duplicato', self.codici(doppio))
        sia = sostituisci(PIANO, '- [[Rilascio in produzione]] — aggiungere', '- [[Rilascio in produzione]] — aggiungere\n- [[Rilascio in produzione]] — ancora')
        self.assertIn('duplicato', self.codici(sia))

    def test_nome_non_valido(self):
        for nome in ('Finestra (nuova)', 'cartella/Finestra', 'Finestra#1'):
            with self.subTest(nome=nome):
                problemi = self.codici(sostituisci(PIANO, '[[Finestra di rilascio]] — tipo', f'[[{nome}]] — tipo'))
                self.assertIn('nome_non_valido', problemi)


class Relazioni(Base):
    def test_relazione_fuori_vocabolario(self):
        self.assertIn('relazione_fuori_vocabolario', self.codici(sostituisci(PIANO, '→ richiede →', '→ inventata →')))

    def test_pagina_ignota(self):
        self.assertIn('pagina_ignota', self.codici(sostituisci(PIANO, '→ [[Finestra di rilascio]]\n', '→ [[Pagina inventata]]\n')))

    def test_tipi_non_ammessi(self):
        # `usa` parte da processo/sistema/progetto e arriva a sistema/entita: un processo nuovo non è un arrivo valido.
        self.assertIn('tipi_non_ammessi', self.codici(sostituisci(PIANO, '→ richiede →', '→ usa →')))

    def test_relazione_valida_verso_una_pagina_esistente(self):
        self.assertEqual(self.controlla(sostituisci(PIANO, '→ richiede → [[Finestra di rilascio]]', '→ usa → [[Console di rilascio]]')), [])

    def test_la_pagina_di_partenza_deve_essere_nel_piano(self):
        fuori = sostituisci(PIANO, '- [[Rilascio in produzione]] → richiede', '- [[Incident settimanale]] → richiede')
        problemi = [p for p in self.controlla(fuori) if p['codice'] == 'pagina_non_in_piano']
        self.assertEqual(len(problemi), 1)
        self.assertIn('Incident settimanale', problemi[0]['messaggio'])

    def test_freccia_ascii_e_riga_malformata(self):
        self.assertEqual(self.controlla(sostituisci(PIANO, '→ richiede →', '-> richiede ->')), [])
        self.assertIn('riga_non_valida', self.codici(sostituisci(PIANO, '→ richiede → [[Finestra di rilascio]]', 'richiede [[Finestra di rilascio]]')))


class Alias(Base):
    def test_alias_di_una_pagina_fuori_dal_piano(self):
        self.assertIn('pagina_non_in_piano', self.codici(sostituisci(PIANO, '- [[Finestra di rilascio]]: «slot', '- [[Anna Rossi]]: «slot')))

    def test_alias_uguale_a_una_pagina_o_a_un_alias_esistente(self):
        self.assertIn('alias_duplicato', self.codici(sostituisci(PIANO, '«slot di rilascio»', '«Anna Rossi»')))
        self.assertIn('alias_duplicato', self.codici(sostituisci(PIANO, '«slot di rilascio»', '«console»')))
        self.assertIn('alias_duplicato', self.codici(sostituisci(PIANO, '«slot di rilascio»', '«Console di Rilascio»')))

    def test_alias_ripetuto_per_due_pagine_del_piano(self):
        doppio = sostituisci(PIANO, '## Contraddizioni', '- [[Rilascio in produzione]]: «finestra»\n\n## Contraddizioni')
        self.assertIn('alias_duplicato', self.codici(doppio))

    def test_alias_gia_della_stessa_pagina_non_e_un_errore(self):
        piano_alias = sostituisci(PIANO, '- [[Finestra di rilascio]]: «slot di rilascio», «finestra»',
                                  '- [[Anna Rossi]]: «Rossi Anna»').replace('## Pagine da aggiornare\n- [[Rilascio in produzione]]',
                                                                             '## Pagine da aggiornare\n- [[Anna Rossi]] — verifica\n- [[Rilascio in produzione]]')
        self.assertEqual(self.controlla(piano_alias), [])


class ConCatalogo(Base):
    catalogo = True

    def test_tipo_non_dichiarato_nel_catalogo(self):
        self.assertEqual(self.controlla(PIANO), [])
        self.assertIn('tipo_non_ammesso', self.codici(sostituisci(PIANO, 'tipo: processo', 'tipo: inventato')))


class Riga(Base):
    def esegui(self, *argomenti):
        uscita, errori = io.StringIO(), io.StringIO()
        with redirect_stdout(uscita), redirect_stderr(errori):
            try:
                codice = piano.main(['--vault', str(self.vault), *map(str, argomenti)])
            except SystemExit as chiusura:
                codice = chiusura.code
        return codice, uscita.getvalue(), errori.getvalue()

    def test_exit_zero_e_uno_con_righe_leggibili(self):
        (self.vault / 'piano.md').write_text(PIANO, encoding='utf-8')
        codice, uscita, _ = self.esegui(self.vault / 'piano.md')
        self.assertEqual((codice, 'ok' in uscita), (0, True))
        (self.vault / 'piano.md').write_text(sostituisci(PIANO, '→ richiede →', '→ inventata →'), encoding='utf-8')
        codice, uscita, _ = self.esegui(self.vault / 'piano.md')
        self.assertEqual(codice, 1)
        self.assertIn('relazione_fuori_vocabolario', uscita)
        self.assertRegex(uscita, r'piano\.md:\d+: ')

    def test_json(self):
        (self.vault / 'piano.md').write_text(sostituisci(PIANO, '→ richiede →', '→ inventata →'), encoding='utf-8')
        dati = json.loads(self.esegui(self.vault / 'piano.md', '--json')[1])
        self.assertEqual(dati[0]['codice'], 'relazione_fuori_vocabolario')

    def test_file_inesistente_e_grafo_assente(self):
        codice, _, errori = self.esegui(self.vault / 'non-c-e.md')
        self.assertEqual(codice, 1)
        self.assertIn('piano_illeggibile', errori)
        (self.vault / 'piano.md').write_text(PIANO, encoding='utf-8')
        (self.vault / '.graph/graph.sqlite').unlink()
        codice, _, errori = self.esegui(self.vault / 'piano.md')
        self.assertEqual(codice, 1)
        self.assertIn('build_graph.py', errori)

    def test_sola_lettura(self):
        (self.vault / 'piano.md').write_text(sostituisci(PIANO, '→ richiede →', '→ inventata →'), encoding='utf-8')

        def impronte():
            return {p.relative_to(self.vault).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                    for p in sorted(self.vault.rglob('*')) if p.is_file() and '.graph' not in p.parts}
        prima = impronte()
        self.esegui(self.vault / 'piano.md')
        self.assertEqual(prima, impronte())

    def test_senza_argomenti_e_un_errore_d_uso(self):
        self.assertEqual(self.esegui()[0], 2)


if __name__ == '__main__':
    unittest.main()
