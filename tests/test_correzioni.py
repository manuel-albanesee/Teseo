"""Correzioni manuali ricorrenti (kit/graph/correzioni.py): segnale per migliorare schema e skill, in sola lettura."""
import _shortpath  # noqa: F401
import io
import json
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

KIT = Path(__file__).resolve().parents[1] / 'kit'
sys.path.insert(0, str(KIT / 'graph'))
import correzioni


def pagina(tipo='processo', usa=(), aliases=(), fonti=('call-1',), corpo='testo'):
    cornice = ['---', f'tipo: {tipo}', 'tags: [prova]', f'fonti: [{", ".join(fonti)}]', 'aggiornato: 2026-10-01']
    if aliases:
        cornice.append(f'aliases: [{", ".join(aliases)}]')
    if usa:
        cornice.append('usa: [' + ', '.join(f'"[[{u}]]"' for u in usa) + ']')
    return '\n'.join([*cornice, '---', '', '# Titolo', '', corpo, ''])


class Repo(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.vault = Path(temp.name)
        (self.vault / 'wiki').mkdir()
        self.git('init', '-q', '-b', 'main')

    def git(self, *args):
        fatto = subprocess.run(['git', '-c', 'core.autocrlf=false', '-c', 'user.name=Alice', '-c', 'user.email=alice@example.invalid',
                                '-c', 'commit.gpgSign=false', *args], cwd=self.vault, capture_output=True, check=True)
        return fatto.stdout.decode('utf-8').strip()

    def scrivi(self, nome, testo):
        (self.vault / 'wiki' / f'{nome}.md').write_text(testo, encoding='utf-8', newline='\n')

    def commit(self, skill, **pagine):
        """Un commit con i trailer Teseo-*; skill None = commit senza trailer."""
        for nome, testo in pagine.items():
            self.scrivi(nome.replace('_', ' '), testo)
        self.git('add', '-A')
        messaggio = f'prova {skill}' + (f'\n\nTeseo-Skill: {skill}\nTeseo-Agent: claude' if skill else '')
        self.git('commit', '-q', '-m', messaggio)

    def analizza(self, **opzioni):
        return correzioni.analizza(self.vault, **opzioni)

    def proposte(self, **opzioni):
        return [(p['categoria'], p['chiave'], p['occorrenze'], len(p['pagine'])) for p in self.analizza(**opzioni)['proposte']]


class Ricorrenze(Repo):
    def tre_pagine_scritte_dall_ingest(self, **extra):
        self.commit('ingest', P1=pagina(usa=['X'], **extra), P2=pagina(usa=['X'], **extra), P3=pagina(usa=['X'], **extra))

    def test_relazione_tolta_a_mano_su_tre_pagine_diventa_una_proposta(self):
        self.tre_pagine_scritte_dall_ingest()
        for nome in ('P1', 'P2', 'P3'):
            self.commit('manuale', **{nome: pagina()})
        esito = self.analizza()
        self.assertEqual(self.proposte(), [('relazione_tolta', 'usa', 3, 3)])
        self.assertEqual((esito['commit_manuali'], esito['correzioni'], esito['isolate']), (3, 3, 0))
        self.assertIn('usa', esito['proposte'][0]['proposta'])
        self.assertIn('Wiki reference.md', esito['proposte'][0]['proposta'])
        self.assertEqual(sorted(esito['proposte'][0]['pagine']), ['P1', 'P2', 'P3'])

    def test_relazione_aggiunta_a_mano(self):
        self.commit('lint', P1=pagina(), P2=pagina(), P3=pagina())
        for nome in ('P1', 'P2', 'P3'):
            self.commit('manuale', **{nome: pagina(usa=['Y'])})
        self.assertEqual(self.proposte(), [('relazione_aggiunta', 'usa', 3, 3)])

    def test_correzione_isolata_e_ignorata_ma_contata(self):
        self.tre_pagine_scritte_dall_ingest()
        self.commit('manuale', P1=pagina())
        esito = self.analizza()
        self.assertEqual((esito['proposte'], esito['correzioni'], esito['isolate']), ([], 1, 1))

    def test_serve_piu_di_una_pagina(self):
        # La stessa pagina corretta tre volte (l'ingest la riscrive ogni volta) è un caso, non una regola da cambiare.
        for _ in range(3):
            self.commit('ingest', P1=pagina(usa=['X']))
            self.commit('manuale', P1=pagina())
        self.assertEqual(self.proposte(), [])
        self.assertEqual(self.proposte(min_pagine=1), [('relazione_tolta', 'usa', 3, 1)])

    def test_soglie_configurabili(self):
        self.tre_pagine_scritte_dall_ingest()
        self.commit('manuale', P1=pagina())
        self.commit('manuale', P2=pagina())
        self.assertEqual(self.proposte(), [])
        self.assertEqual(self.proposte(min_occorrenze=2), [('relazione_tolta', 'usa', 2, 2)])

    def test_solo_le_pagine_scritte_da_ingest_o_lint_contano(self):
        self.commit('lacune', P1=pagina(usa=['X']), P2=pagina(usa=['X']), P3=pagina(usa=['X']))
        self.commit(None, P4=pagina(usa=['X']))
        self.commit('manuale', P5=pagina(usa=['X']))
        for nome in ('P1', 'P2', 'P3', 'P4', 'P5'):
            self.commit('manuale', **{nome: pagina()})
        esito = self.analizza()
        self.assertEqual((esito['proposte'], esito['correzioni']), ([], 0))
        self.assertEqual(esito['commit_manuali'], 6)

    def test_una_correzione_sposta_la_pagina_fuori_dal_segnale(self):
        # Dopo una modifica manuale l'ultima mano sulla pagina è l'utente: una seconda modifica non è una correzione dell'ingest.
        self.commit('ingest', P1=pagina(usa=['X']))
        self.commit('manuale', P1=pagina())
        self.commit('manuale', P1=pagina(usa=['Z']))
        self.assertEqual(self.analizza()['correzioni'], 1)

    def test_dopo_una_nuova_scrittura_della_skill_la_pagina_torna_correggibile(self):
        self.commit('ingest', P1=pagina(usa=['X']))
        self.commit('manuale', P1=pagina())
        self.commit('lint', P1=pagina(usa=['X']))
        self.commit('manuale', P1=pagina())
        self.assertEqual(self.analizza()['correzioni'], 2)

    def test_le_rinomine_seguono_la_pagina(self):
        self.commit('ingest', P1=pagina(usa=['X']))
        self.git('mv', 'wiki/P1.md', 'wiki/P1 bis.md')
        self.git('commit', '-q', '-m', 'rinomina\n\nTeseo-Skill: ingest\nTeseo-Agent: claude')
        self.commit('manuale', **{'P1 bis': pagina()})
        self.assertEqual(self.analizza()['correzioni'], 1)

    def test_pagine_nuove_o_cancellate_a_mano_non_sono_correzioni(self):
        self.commit('ingest', P1=pagina(usa=['X']))
        self.commit('manuale', P9=pagina())
        (self.vault / 'wiki/P1.md').unlink()
        self.git('add', '-A')
        self.git('commit', '-q', '-m', 'via\n\nTeseo-Skill: manuale\nTeseo-Agent: umano')
        self.assertEqual(self.analizza()['correzioni'], 0)

    def test_modifiche_al_solo_testo_non_sono_classificate(self):
        self.commit('ingest', P1=pagina(corpo='uno'), P2=pagina(corpo='uno'), P3=pagina(corpo='uno'))
        for nome in ('P1', 'P2', 'P3'):
            self.commit('manuale', **{nome: pagina(corpo='due')})
        esito = self.analizza()
        self.assertEqual((esito['proposte'], esito['correzioni']), ([], 0))


class Categorie(Repo):
    def ciclo(self, prima, dopo, tipo_prima='persona', tipo_dopo=None):
        self.commit('ingest', **{n: pagina(tipo=tipo_prima, **prima) for n in ('P1', 'P2', 'P3')})
        for n in ('P1', 'P2', 'P3'):
            self.commit('manuale', **{n: pagina(tipo=tipo_dopo or tipo_prima, **dopo)})

    def test_alias_aggiunti_a_mano_raggruppati_per_tipo_di_pagina(self):
        self.ciclo({}, {'aliases': ['"Rossi Anna"']})
        self.assertEqual(self.proposte(), [('alias_aggiunto', 'persona', 3, 3)])

    def test_alias_tolti(self):
        self.ciclo({'aliases': ['sigla']}, {})
        self.assertEqual(self.proposte(), [('alias_tolto', 'persona', 3, 3)])

    def test_tipo_cambiato(self):
        self.ciclo({}, {}, tipo_prima='concetto', tipo_dopo='sistema')
        self.assertEqual(self.proposte(), [('tipo_cambiato', 'concetto->sistema', 3, 3)])

    def test_fonti_cambiate(self):
        self.ciclo({}, {'fonti': ['call-1', 'call-2']})
        self.assertEqual(self.proposte(), [('fonti_aggiunte', '', 3, 3)])

    def test_piu_cambiamenti_nello_stesso_commit_sono_eventi_separati(self):
        self.commit('ingest', **{n: pagina(usa=['X']) for n in ('P1', 'P2', 'P3')})
        for n in ('P1', 'P2', 'P3'):
            self.commit('manuale', **{n: pagina(aliases=['alfa'])})
        self.assertEqual(sorted(self.proposte()), [('alias_aggiunto', 'processo', 3, 3), ('relazione_tolta', 'usa', 3, 3)])

    def test_togliere_due_destinazioni_e_un_solo_evento_per_relazione_e_pagina(self):
        self.commit('ingest', **{n: pagina(usa=['X', 'Y']) for n in ('P1', 'P2', 'P3')})
        for n in ('P1', 'P2', 'P3'):
            self.commit('manuale', **{n: pagina()})
        self.assertEqual(self.proposte(), [('relazione_tolta', 'usa', 3, 3)])

    def test_ordine_per_numero_di_occorrenze(self):
        self.commit('ingest', **{n: pagina(usa=['X']) for n in ('P1', 'P2', 'P3', 'P4')})
        for n in ('P1', 'P2', 'P3', 'P4'):
            self.commit('manuale', **{n: pagina()})
        for n in ('P1', 'P2', 'P3'):
            self.commit('lint', **{n: pagina(aliases=['x'])})
            self.commit('manuale', **{n: pagina()})
        self.assertEqual([p[:3] for p in self.proposte()], [('relazione_tolta', 'usa', 4), ('alias_tolto', 'processo', 3)])

    def test_frontmatter_non_valido_non_blocca(self):
        self.commit('ingest', P1='---\ntipo: [rotto\n---\ntesto\n', P2=pagina(usa=['X']))
        self.commit('manuale', P1=pagina(), P2=pagina())
        self.assertEqual(self.analizza()['correzioni'], 1)


class Ambiente(Repo):
    def test_senza_repository(self):
        with tempfile.TemporaryDirectory() as cartella:
            esito = correzioni.analizza(Path(cartella))
        self.assertEqual((esito['proposte'], esito['correzioni']), ([], 0))
        self.assertIn('Git', esito['messaggio'])

    def test_senza_commit_attribuiti(self):
        self.commit(None, P1=pagina(usa=['X']))
        self.commit(None, P1=pagina())
        esito = self.analizza()
        self.assertEqual((esito['proposte'], esito['commit_manuali']), ([], 0))
        self.assertIn('autosync', esito['messaggio'])

    def test_repository_senza_commit(self):
        self.assertEqual(self.analizza()['proposte'], [])

    def test_finestra_dei_commit(self):
        self.commit('ingest', **{n: pagina(usa=['X']) for n in ('P1', 'P2', 'P3')})
        for n in ('P1', 'P2', 'P3'):
            self.commit('manuale', **{n: pagina()})
        self.assertEqual(self.analizza(ultimi=2)['correzioni'], 0)
        self.assertEqual(self.analizza(ultimi=10)['correzioni'], 3)

    def test_sola_lettura(self):
        self.commit('ingest', **{n: pagina(usa=['X']) for n in ('P1', 'P2', 'P3')})
        for n in ('P1', 'P2', 'P3'):
            self.commit('manuale', **{n: pagina()})
        testa, stato = self.git('rev-parse', 'HEAD'), self.git('status', '--porcelain')
        self.analizza()
        self.assertEqual((self.git('rev-parse', 'HEAD'), self.git('status', '--porcelain')), (testa, stato))
        self.assertEqual(sorted(p.name for p in self.vault.iterdir()), ['.git', 'wiki'])


class Riga(Repo):
    def esegui(self, *argomenti):
        uscita = io.StringIO()
        with redirect_stdout(uscita):
            codice = correzioni.main(['--vault', str(self.vault), *map(str, argomenti)])
        return codice, uscita.getvalue()

    def ciclo(self):
        self.commit('ingest', **{n: pagina(usa=['X']) for n in ('P1', 'P2', 'P3')})
        for n in ('P1', 'P2', 'P3'):
            self.commit('manuale', **{n: pagina()})

    def test_testo_con_proposta_e_exit_zero(self):
        self.ciclo()
        codice, testo = self.esegui()
        self.assertEqual(codice, 0)
        self.assertIn('relazione_tolta', testo)
        self.assertIn('3 volte su 3 pagine', testo)

    def test_testo_senza_proposte(self):
        codice, testo = self.esegui()
        self.assertEqual(codice, 0)
        self.assertIn('nessuna correzione ricorrente', testo.lower())

    def test_json_e_soglie_da_riga_di_comando(self):
        self.ciclo()
        dati = json.loads(self.esegui('--json')[1])
        self.assertEqual(dati['proposte'][0]['categoria'], 'relazione_tolta')
        dati = json.loads(self.esegui('--json', '--min-occorrenze', '4')[1])
        self.assertEqual(dati['proposte'], [])

    def test_valori_non_validi(self):
        for argomenti in (['--min-occorrenze', '0'], ['--min-pagine', 'x'], ['--ultimi', '-1']):
            with self.subTest(argomenti=argomenti), self.assertRaises(SystemExit) as chiusura, redirect_stdout(io.StringIO()), \
                    redirect_stderr(io.StringIO()):
                correzioni.main(['--vault', str(self.vault), *argomenti])
            self.assertEqual(chiusura.exception.code, 2)


if __name__ == '__main__':
    unittest.main()
