"""Validatore dei contratti (kit/graph/contratti.py): forma canonica Input / Processo / Checkpoint / Verifica / Output."""
import _shortpath  # noqa: F401
import io
import json
from contextlib import redirect_stdout
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'kit/graph'))
import contratti

VALIDO = """\
## Input
| Livello | File | Sezione | Perché |
| --- | --- | --- | --- |
| 3 | `Wiki reference.md` | «Relazioni tipizzate» | vocabolario ammesso |
| 4 | `{esecuzione}/01-raccolta/raccolta.md` | tutto | pagine selezionate |

## Processo
1. Scrivi la sintesi.

## Verifica
| Controllo | Comando | Esito atteso |
| --- | --- | --- |
| grafo | `python .graph/build_graph.py --check` | nessun problema |

## Output
| Artefatto | Posizione | Formato |
| --- | --- | --- |
| sintesi | `output/sintesi.md` | Markdown |
"""

SCHEMA = "# Wiki reference\n\n## Relazioni tipizzate\n\ntesto\n\n## Modello a tre livelli (metodo LLM Wiki)\n\ntesto\n"


def sostituisci(testo, vecchio, nuovo):
    assert vecchio in testo
    return testo.replace(vecchio, nuovo, 1)


class Base(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.radice = Path(temp.name)
        (self.radice / 'Wiki reference.md').write_text(SCHEMA, encoding='utf-8')

    def scrivi(self, testo, nome='CONTEXT.md'):
        percorso = self.radice / nome
        percorso.parent.mkdir(parents=True, exist_ok=True)
        percorso.write_text(testo, encoding='utf-8')
        return percorso

    def codici(self, testo, nome='CONTEXT.md', chiave='errori', **opzioni):
        esito = contratti.valida(self.scrivi(testo, nome), radice=self.radice, **opzioni)
        return [p['codice'] for p in esito[chiave]]


class Forma(Base):
    def test_contratto_valido_non_ha_problemi(self):
        esito = contratti.valida(self.scrivi(VALIDO), radice=self.radice)
        self.assertEqual((esito['errori'], esito['avvisi']), ([], []))

    def test_sezione_obbligatoria_mancante(self):
        senza = VALIDO.split('## Verifica')[0] + '## Output\n| a | b | c |\n'
        self.assertIn('sezione_mancante', self.codici(senza))

    def test_checkpoint_e_facoltativo_ma_se_presente_va_al_suo_posto(self):
        con = sostituisci(VALIDO, '## Verifica', '## Checkpoint\n| Dopo il passo | Presenta | Decide |\n\n## Verifica')
        self.assertEqual(self.codici(con), [])
        fuori = sostituisci(VALIDO, '## Output', '## Checkpoint\n| a | b | c |\n\n## Output')
        self.assertIn('sezioni_fuori_ordine', self.codici(fuori))

    def test_sezioni_fuori_ordine(self):
        invertito = sostituisci(VALIDO, '## Processo\n1. Scrivi la sintesi.\n\n', '')
        invertito += '\n## Processo\n1. Scrivi.\n'
        self.assertIn('sezioni_fuori_ordine', self.codici(invertito))

    def test_titoli_dentro_blocchi_di_codice_non_contano(self):
        con_codice = VALIDO + '\n```\n## Checkpoint\n## Altro\n```\n'
        self.assertEqual(self.codici(con_codice), [])
        solo_in_codice = sostituisci(VALIDO, '## Verifica', '```\n## Verifica\n```\n\n## Altro')
        self.assertIn('sezione_mancante', self.codici(solo_in_codice))

    def test_frontmatter_ignorato_e_righe_corrette(self):
        con_fm = '---\nname: prova\ndescription: x\n---\n\n' + VALIDO + '\nResta {{DA_COMPILARE}}\n'
        esito = contratti.valida(self.scrivi(con_fm), radice=self.radice)
        self.assertEqual([p['codice'] for p in esito['errori']], ['segnaposto'])
        self.assertEqual(esito['errori'][0]['riga'], len(con_fm.splitlines()))


class Input(Base):
    def test_input_senza_tabella(self):
        vuoto = sostituisci(VALIDO, VALIDO.split('## Processo')[0], '## Input\nSolo prosa.\n\n')
        self.assertIn('input_senza_tabella', self.codici(vuoto))

    def test_tabella_input_senza_colonna_file(self):
        senza = sostituisci(VALIDO, '| Livello | File | Sezione | Perché |', '| Livello | Dove | Sezione | Perché |')
        self.assertIn('input_colonne', self.codici(senza))

    def test_file_di_riferimento_inesistente(self):
        rotto = sostituisci(VALIDO, '`Wiki reference.md`', '`Regole.md`')
        self.assertIn('input_file_mancante', self.codici(rotto))

    def test_file_relativo_al_contratto_o_alla_radice(self):
        (self.radice / 'fasi/02-sintesi').mkdir(parents=True)
        (self.radice / 'fasi/02-sintesi/tono.md').write_text('# Tono\n', encoding='utf-8')
        relativo = sostituisci(VALIDO, '`Wiki reference.md`', '`tono.md`').replace(' «Relazioni tipizzate» ', ' tutto ')
        self.assertEqual(self.codici(relativo, 'fasi/02-sintesi/CONTEXT.md'), [])

    def test_livello_4_non_deve_esistere_prima_dell_esecuzione(self):
        self.assertFalse((self.radice / '{esecuzione}').exists())
        self.assertEqual(self.codici(VALIDO), [])
        rotto4 = sostituisci(VALIDO, '`{esecuzione}/01-raccolta/raccolta.md`', '`raw/non-esiste.md`')
        self.assertEqual(self.codici(rotto4), [])

    def test_celle_senza_apici_o_con_comandi_non_sono_file(self):
        descrittivo = sostituisci(VALIDO, '`{esecuzione}/01-raccolta/raccolta.md`', 'contesto del recall o `python .graph/recall.py "<domanda>"`')
        self.assertEqual(self.codici(descrittivo), [])

    def test_sezione_inesistente_nel_file_citato(self):
        rotta = sostituisci(VALIDO, '«Relazioni tipizzate»', '«Relazioni inventate»')
        self.assertIn('input_sezione_mancante', self.codici(rotta))

    def test_titolo_con_parentesi_si_cita_senza_la_parentesi(self):
        parentesi = sostituisci(VALIDO, '«Relazioni tipizzate»', '«Modello a tre livelli»')
        self.assertEqual(self.codici(parentesi), [])
        parziale = sostituisci(VALIDO, '«Relazioni tipizzate»', '«Modello»')
        self.assertIn('input_sezione_mancante', self.codici(parziale))

    def test_piu_sezioni_nella_stessa_cella(self):
        due = sostituisci(VALIDO, '«Relazioni tipizzate»', '«Relazioni tipizzate», «Modello a tre livelli»')
        self.assertEqual(self.codici(due), [])
        una_rotta = sostituisci(VALIDO, '«Relazioni tipizzate»', '«Relazioni tipizzate», «Nessuna»')
        self.assertEqual(self.codici(una_rotta), ['input_sezione_mancante'])


class Lavorazioni(Base):
    def fase(self, numero, riferimento):
        testo = sostituisci(VALIDO, '`{esecuzione}/01-raccolta/raccolta.md`', f'`{riferimento}`')
        return self.codici(testo, f'fasi/{numero}-nome/CONTEXT.md')

    def test_riferimento_a_una_fase_successiva(self):
        self.assertIn('riferimento_in_avanti', self.fase('02', '../03-revisione/output/x.md'))

    def test_riferimento_a_fase_precedente_o_alla_stessa_e_ammesso(self):
        self.assertEqual(self.fase('02', '../01-raccolta/output/x.md'), [])
        self.assertEqual(self.fase('02', '../02-nome/riferimenti/x.md'), [])

    def test_fuori_dalle_fasi_non_si_applica(self):
        self.assertEqual(self.codici(sostituisci(VALIDO, '`{esecuzione}/01-raccolta/raccolta.md`', '`../09-altro/x.md`')), [])


class Segnaposto(Base):
    def test_segnaposto_non_compilato(self):
        self.assertIn('segnaposto', self.codici(VALIDO + '\nDestinatari: {{DESTINATARI}}\n'))

    def test_segnaposto_in_blocco_di_codice_ammesso(self):
        self.assertEqual(self.codici(VALIDO + '\n```\n{{DESTINATARI}}\n```\n'), [])


class Lunghezza(Base):
    def test_contratto_lungo_e_solo_un_avviso(self):
        lungo = VALIDO + '\n'.join(f'riga {i}' for i in range(90))
        self.assertEqual(self.codici(lungo), [])
        self.assertEqual(self.codici(lungo, chiave='avvisi'), ['troppo_lungo'])
        self.assertEqual(self.codici(lungo, chiave='avvisi', max_righe=500), [])


class Riga(Base):
    def run_cli(self, *argomenti):
        uscita = io.StringIO()
        with redirect_stdout(uscita):
            codice = contratti.main([str(a) for a in argomenti])
        return codice, uscita.getvalue()

    def test_exit_zero_se_valido(self):
        codice, testo = self.run_cli(self.scrivi(VALIDO), '--radice', self.radice)
        self.assertEqual(codice, 0)
        self.assertIn('CONTEXT.md: ok', testo)

    def test_exit_uno_con_errori_e_messaggio_leggibile(self):
        codice, testo = self.run_cli(self.scrivi(VALIDO + '\n{{X}}\n'), '--radice', self.radice)
        self.assertEqual(codice, 1)
        self.assertIn('segnaposto', testo)

    def test_gli_avvisi_non_cambiano_l_exit(self):
        codice, testo = self.run_cli(self.scrivi(VALIDO + '\n'.join(['x'] * 100)), '--radice', self.radice)
        self.assertEqual(codice, 0)
        self.assertIn('troppo_lungo', testo)

    def test_json(self):
        buono, rotto = self.scrivi(VALIDO, 'a.md'), self.scrivi('## Input\n', 'b.md')
        codice, testo = self.run_cli(buono, rotto, '--radice', self.radice, '--json')
        dati = json.loads(testo)
        self.assertEqual(codice, 1)
        self.assertEqual([(d['file'], bool(d['errori'])) for d in dati], [('a.md', False), ('b.md', True)])

    def test_file_inesistente_e_un_errore_non_un_crash(self):
        codice, testo = self.run_cli(self.radice / 'non-c-e.md', '--radice', self.radice)
        self.assertEqual(codice, 1)
        self.assertIn('file_illeggibile', testo)

    def test_senza_file_e_un_errore_d_uso(self):
        with self.assertRaises(SystemExit) as uscita, redirect_stdout(io.StringIO()), contratti_stderr():
            contratti.main([])
        self.assertEqual(uscita.exception.code, 2)


def contratti_stderr():
    from contextlib import redirect_stderr
    return redirect_stderr(io.StringIO())


if __name__ == '__main__':
    unittest.main()
