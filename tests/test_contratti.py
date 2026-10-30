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

    def test_cella_senza_apici_e_descrittiva(self):
        descrittiva = sostituisci(VALIDO, '`{esecuzione}/01-raccolta/raccolta.md`', 'il contesto del recall')
        self.assertEqual(self.codici(descrittiva), [])

    def test_senza_sezione_input_si_segnala_solo_la_mancanza(self):
        senza = VALIDO.replace('## Input', '## Ingresso')
        self.assertEqual(self.codici(senza), ['sezione_mancante'])

    def test_contratto_fuori_dalla_radice_risolve_gli_input_dalla_radice(self):
        # Caso delle skill: kit/skills/<nome>/SKILL.md controllata con --radice kit/vault.
        altrove = tempfile.TemporaryDirectory()
        self.addCleanup(altrove.cleanup)
        contratto = Path(altrove.name) / 'SKILL.md'
        contratto.write_text(VALIDO, encoding='utf-8')
        esito = contratti.valida(contratto, radice=self.radice)
        self.assertEqual(esito['errori'], [])
        self.assertEqual(esito['file'], str(contratto))

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


class SkillDelKit(unittest.TestCase):
    """Le skill distribuite ai vault sono contratti: stessa forma delle fasi delle lavorazioni."""
    KIT = Path(__file__).resolve().parents[1] / 'kit'

    def skill(self):
        elenco = sorted(self.KIT.glob('skills/*/SKILL.md'))
        self.assertGreaterEqual(len(elenco), 4, 'il test non deve passare a vuoto')
        return elenco

    def test_ogni_skill_ha_la_forma_canonica(self):
        for percorso in self.skill():
            with self.subTest(skill=percorso.parent.name):
                esito = contratti.valida(percorso, radice=self.KIT / 'vault')
                self.assertEqual([(p['codice'], p['messaggio']) for p in esito['errori']], [])

    def test_ogni_skill_dichiara_input_sul_file_di_schema(self):
        for percorso in self.skill():
            with self.subTest(skill=percorso.parent.name):
                self.assertIn('| `Wiki reference.md` |', percorso.read_text(encoding='utf-8'))

    def test_checkpoint_presente_dove_la_skill_chiede_all_utente(self):
        # Le quattro skill prevedono una scelta o una conferma dell'utente: il checkpoint è obbligatorio.
        for percorso in self.skill():
            with self.subTest(skill=percorso.parent.name):
                self.assertIn('\n## Checkpoint\n', percorso.read_text(encoding='utf-8'))


SCHEMA_PESO = ('# Wiki reference\n\nintroduzione\n\n## Convenzioni delle pagine (formato)\n\n' + 'c' * 400 + '\n\n### Frontmatter\n\n' + 'f' * 200 +
               '\n\n## Relazioni tipizzate\n\n' + 'r' * 800 + '\n\n```\n## Titolo nel codice\n```\n\n## Workflow\n\n' + 'w' * 400 + '\n')


class Peso(Base):
    """Quanto contesto carica un contratto: caratteri/4, per livello, con le sezioni degli Input."""

    def setUp(self):
        super().setUp()
        (self.radice / 'Wiki reference.md').write_text(SCHEMA_PESO, encoding='utf-8')
        (self.radice / 'altro.md').write_text('a' * 400, encoding='utf-8')

    def contratto(self, righe):
        return VALIDO.split('| 3 |')[0] + '\n'.join(righe) + '\n' + '\n## Processo' + VALIDO.split('## Processo')[1]

    def peso(self, righe):
        return contratti.peso(self.scrivi(self.contratto(righe)), radice=self.radice)

    def test_sezione_include_le_sottosezioni_e_si_ferma_al_titolo_di_pari_livello(self):
        testo = contratti.testo_sezione(SCHEMA_PESO, 'Convenzioni delle pagine')
        self.assertTrue(testo.startswith('## Convenzioni delle pagine (formato)'))
        self.assertIn('### Frontmatter', testo)
        self.assertNotIn('Relazioni tipizzate', testo)
        self.assertIsNone(contratti.testo_sezione(SCHEMA_PESO, 'Titolo nel codice'))
        self.assertIsNone(contratti.testo_sezione(SCHEMA_PESO, 'Convenzioni'))
        self.assertTrue(contratti.testo_sezione(SCHEMA_PESO, 'Frontmatter').startswith('### Frontmatter'))

    def test_file_intero_o_solo_le_sezioni_citate(self):
        intero = self.peso(['| 3 | `Wiki reference.md` | tutto | x |'])
        self.assertEqual(intero['livello3'], len(SCHEMA_PESO) // 4)
        scelte = self.peso(['| 3 | `Wiki reference.md` | «Relazioni tipizzate» | x |'])
        self.assertEqual(scelte['livello3'], len(contratti.testo_sezione(SCHEMA_PESO, 'Relazioni tipizzate')) // 4)
        self.assertLess(scelte['livello3'], intero['livello3'])

    def test_piu_sezioni_nella_stessa_riga_si_sommano(self):
        due = self.peso(['| 3 | `Wiki reference.md` | «Convenzioni delle pagine», «Workflow» | x |'])
        attesi = sum(len(contratti.testo_sezione(SCHEMA_PESO, s)) for s in ('Convenzioni delle pagine', 'Workflow')) // 4
        self.assertEqual(due['livello3'], attesi)

    def test_livelli_separati_e_file_inesistenti_non_contano(self):
        peso = self.peso(['| 3 | `Wiki reference.md` | «Workflow» | x |', '| 4 | `altro.md` | tutto | x |',
                          '| 4 | `non-c-e.md` | tutto | x |', '| 4 | `{esecuzione}/raccolta.md` | tutto | x |'])
        self.assertEqual(peso['livello4'], 100)
        self.assertGreater(peso['livello3'], 0)
        voci = {r['file']: r['token'] for r in peso['righe']}
        self.assertIsNone(voci['non-c-e.md'])
        self.assertNotIn('{esecuzione}/raccolta.md', voci)

    def test_senza_input_peso_zero(self):
        senza = contratti.peso(self.scrivi('## Processo\n1. x\n'), radice=self.radice)
        self.assertEqual((senza['livello3'], senza['livello4'], senza['righe']), (0, 0, []))

    def test_riga_di_comando(self):
        percorso = self.scrivi(self.contratto(['| 3 | `Wiki reference.md` | «Workflow» | x |']))
        uscita = io.StringIO()
        with redirect_stdout(uscita):
            codice = contratti.main([str(percorso), '--radice', str(self.radice), '--peso'])
        self.assertEqual(codice, 0)
        self.assertIn('Wiki reference.md', uscita.getvalue())
        self.assertIn('livello 3', uscita.getvalue())
        uscita = io.StringIO()
        with redirect_stdout(uscita):
            contratti.main([str(percorso), '--radice', str(self.radice), '--peso', '--json'])
        self.assertEqual(json.loads(uscita.getvalue())[0]['peso']['livello3'], contratti.peso(percorso, self.radice)['livello3'])


class SchemaSelettivo(unittest.TestCase):
    """Query e lacune leggono solo le sezioni di Wiki reference.md che usano; ingest e lint tutto il file."""
    KIT = Path(__file__).resolve().parents[1] / 'kit'

    def peso_schema(self, nome):
        esito = contratti.peso(self.KIT / 'skills' / f'obsidian-wiki-{nome}' / 'SKILL.md', radice=self.KIT / 'vault')
        return sum(r['token'] for r in esito['righe'] if r['file'] == 'Wiki reference.md' and r['token'])

    def test_query_e_lacune_caricano_meno_di_tre_quarti_dello_schema(self):
        completo = len((self.KIT / 'vault/Wiki reference.md').read_text(encoding='utf-8')) // 4
        for nome in ('query', 'fill-gaps'):
            with self.subTest(skill=nome):
                self.assertLessEqual(self.peso_schema(nome), completo * 0.75)

    def test_ingest_e_lint_leggono_tutto_lo_schema(self):
        completo = len((self.KIT / 'vault/Wiki reference.md').read_text(encoding='utf-8')) // 4
        for nome in ('ingest', 'lint'):
            with self.subTest(skill=nome):
                self.assertEqual(self.peso_schema(nome), completo)

    def test_le_regole_non_negoziabili_sono_sempre_caricate(self):
        for nome in ('query', 'fill-gaps'):
            with self.subTest(skill=nome):
                testo = (self.KIT / 'skills' / f'obsidian-wiki-{nome}' / 'SKILL.md').read_text(encoding='utf-8')
                self.assertIn('«Regole non negoziabili»', testo)

    def test_le_sezioni_tolte_non_servono_alle_due_skill(self):
        # Workflow, Manutenzione del vault e il modello a tre livelli descrivono ingest e lint, non query né lacune.
        for nome in ('query', 'fill-gaps'):
            testo = (self.KIT / 'skills' / f'obsidian-wiki-{nome}' / 'SKILL.md').read_text(encoding='utf-8')
            righe_schema = [r for r in testo.splitlines() if r.startswith('| 3 | `Wiki reference.md`')]
            self.assertTrue(righe_schema)
            for riga in righe_schema:
                for sezione in ('«Workflow»', '«Manutenzione del vault»', '«Modello a tre livelli'):
                    self.assertNotIn(sezione, riga)

    def test_le_skill_indicano_come_ripiegare_se_serve_altro(self):
        for nome in ('query', 'fill-gaps'):
            testo = (self.KIT / 'skills' / f'obsidian-wiki-{nome}' / 'SKILL.md').read_text(encoding='utf-8')
            self.assertIn('leggi `Wiki reference.md` per intero', testo)

    def test_i_file_di_livello_0_non_chiedono_piu_di_leggere_tutto_lo_schema_a_ogni_operazione(self):
        for nome in ('CLAUDE.md', 'AGENTS.md', 'copilot-instructions.md'):
            with self.subTest(file=nome):
                testo = (self.KIT / 'vault' / nome).read_text(encoding='utf-8')
                self.assertIn('le sezioni indicate dalla skill', testo)


def contratti_stderr():
    from contextlib import redirect_stderr
    return redirect_stderr(io.StringIO())


if __name__ == '__main__':
    unittest.main()
