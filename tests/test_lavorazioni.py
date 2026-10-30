"""Lavorazioni (kit/graph/lavorazioni.py): pipeline ICM che leggono la wiki e producono documenti derivati."""
import _shortpath  # noqa: F401
import hashlib
import io
import json
import os
import re
import subprocess
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
import shutil
import sys
import tempfile
import unittest

KIT = Path(__file__).resolve().parents[1] / 'kit'
sys.path.insert(0, str(KIT / 'graph'))
import build_graph
import installa
import lavorazioni
import contratti

CONTRATTO = """\
## Input
| Livello | File | Sezione | Perché |
| --- | --- | --- | --- |
| 3 | `Wiki reference.md` | tutto | regole |
| 4 | `{esecuzione}/01-raccolta/raccolta.md` | tutto | pagine selezionate |

## Processo
1. Lavora.

## Verifica
| Controllo | Comando | Esito atteso |
| --- | --- | --- |
| esito | rilettura | ok |

## Output
| Artefatto | Posizione | Formato |
| --- | --- | --- |
| risultato | `{esecuzione}/NN/risultato.md` | Markdown |
"""

CONFIG = """\
---
selezione:
  collegate_a: "[[Rilascio in produzione]]"
  profondita: 1
  relazioni: [usa]
  massimo: 40
parametri:
  destinatari: team operativo
---

# Configurazione

Tono sobrio.
"""

FASI = ('01-raccolta', '02-sintesi', '03-revisione')


def hash_albero(radice):
    return {p.relative_to(radice).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(Path(radice).rglob('*')) if p.is_file() and '.graph' not in p.parts}


class Base(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.vault = Path(temp.name)
        shutil.copytree(KIT / 'esempio/wiki', self.vault / 'wiki')
        shutil.copytree(KIT / 'esempio/raw', self.vault / 'raw')
        for nome in ('Wiki reference.md', 'index.md', 'log.md'):
            shutil.copy(KIT / 'vault' / nome, self.vault / nome)
        (self.vault / '.graph').mkdir()
        with redirect_stdout(io.StringIO()):
            build_graph.costruisci(self.vault, self.vault / '.graph/graph.sqlite')

    def crea(self, nome='prova', config=CONFIG, fasi=FASI, contratto=CONTRATTO):
        base = self.vault / 'lavorazioni' / nome
        (base / 'fasi').mkdir(parents=True)
        (base / 'CONTEXT.md').write_text(f'# {nome}\n\nScopo di prova.\n', encoding='utf-8')
        if config is not None:
            (base / 'config.md').write_text(config, encoding='utf-8')
        for fase in fasi:
            (base / 'fasi' / fase).mkdir()
            if contratto is not None:
                (base / 'fasi' / fase / 'CONTEXT.md').write_text(contratto, encoding='utf-8')
        return base

    def codici(self, nome='prova'):
        return [p['codice'] for p in lavorazioni.valida(self.vault, nome)]

    def pagine(self, esecuzione):
        return sorted(json.loads((Path(esecuzione['percorso']) / 'esecuzione.json').read_text(encoding='utf-8'))['pagine'])


class Valida(Base):
    def test_lavorazione_completa_e_valida(self):
        self.crea()
        self.assertEqual(lavorazioni.valida(self.vault, 'prova'), [])

    def test_lavorazione_inesistente(self):
        with self.assertRaises(lavorazioni.LavorazioneError) as errore:
            lavorazioni.valida(self.vault, 'non-c-e')
        self.assertEqual(errore.exception.codice, 'lavorazione_inesistente')

    def test_nome_non_valido_non_esce_dalla_cartella(self):
        for nome in ('../fuori', 'A B', '', '.nascosta', 'a/b'):
            with self.subTest(nome=nome), self.assertRaises(lavorazioni.LavorazioneError) as errore:
                lavorazioni.valida(self.vault, nome)
            self.assertEqual(errore.exception.codice, 'nome_non_valido')

    def test_config_mancante(self):
        self.crea(config=None)
        self.assertIn('config_mancante', self.codici())

    def test_config_con_segnaposto(self):
        self.crea(config=CONFIG.replace('team operativo', '{{DESTINATARI}}'))
        self.assertIn('config_segnaposto', self.codici())

    def test_config_senza_frontmatter_valido(self):
        self.crea(config='nessun frontmatter\n')
        self.assertIn('config_non_valida', self.codici())

    def test_chiave_sconosciuta_nella_selezione(self):
        self.crea(config=CONFIG.replace('massimo: 40', 'massimo: 40\n  colore: blu'))
        self.assertIn('config_chiave', self.codici())

    def test_tipo_errato_nella_selezione(self):
        for sostituzione in (('profondita: 1', 'profondita: molta'), ('massimo: 40', 'massimo: 0'),
                             ('relazioni: [usa]', 'relazioni: usa'), ('profondita: 1', 'profondita: -1')):
            with self.subTest(sostituzione=sostituzione):
                self.crea(config=CONFIG.replace(*sostituzione))
                self.assertIn('config_tipo', self.codici())
                shutil.rmtree(self.vault / 'lavorazioni')

    def test_senza_fasi(self):
        self.crea(fasi=())
        self.assertIn('fasi_assenti', self.codici())

    def test_numerazione_delle_fasi_non_contigua(self):
        self.crea(fasi=('01-raccolta', '03-revisione'))
        self.assertIn('fasi_numerazione', self.codici())

    def test_nome_di_fase_non_valido(self):
        self.crea(fasi=('01-raccolta', 'sintesi'))
        self.assertIn('fasi_numerazione', self.codici())

    def test_fase_senza_contratto(self):
        self.crea(contratto=None)
        self.assertIn('fase_senza_contratto', self.codici())

    def test_errore_di_contratto_riporta_la_fase(self):
        base = self.crea()
        (base / 'fasi/02-sintesi/CONTEXT.md').write_text(CONTRATTO.replace('## Verifica', '## Altro'), encoding='utf-8')
        trovati = [p for p in lavorazioni.valida(self.vault, 'prova') if p['codice'] == 'contratto']
        self.assertEqual(len(trovati), 1)
        self.assertIn('02-sintesi', trovati[0]['messaggio'])
        self.assertIn('sezione_mancante', trovati[0]['messaggio'])

    def test_riferimento_in_avanti_tra_fasi(self):
        base = self.crea()
        avanti = CONTRATTO.replace('`{esecuzione}/01-raccolta/raccolta.md`', '`../03-revisione/x.md`')
        (base / 'fasi/02-sintesi/CONTEXT.md').write_text(avanti, encoding='utf-8')
        self.assertTrue(any('riferimento_in_avanti' in p['messaggio'] for p in lavorazioni.valida(self.vault, 'prova')))


class Elenco(Base):
    def test_elenca_le_lavorazioni_e_salta_le_cartelle_di_servizio(self):
        self.crea('alfa')
        self.crea('beta', fasi=FASI[:2])
        (self.vault / 'lavorazioni/_ingest').mkdir()
        trovate = lavorazioni.elenco(self.vault)
        self.assertEqual([(t['nome'], t['fasi'], t['esecuzione']) for t in trovate], [('alfa', 3, None), ('beta', 2, None)])

    def test_senza_cartella_lavorazioni(self):
        self.assertEqual(lavorazioni.elenco(self.vault), [])

    def test_indica_l_ultima_esecuzione(self):
        self.crea()
        lavorazioni.avvia(self.vault, 'prova', oggi='2026-10-30')
        lavorazioni.avvia(self.vault, 'prova', oggi='2026-10-30')
        self.assertEqual(lavorazioni.elenco(self.vault)[0]['esecuzione'], '2026-10-30-2')


class Nuova(Base):
    def modelli(self):
        cartella = self.vault / '.graph/modelli'
        modello = cartella / 'base'
        (modello / 'fasi').mkdir(parents=True)
        (modello / 'CONTEXT.md').write_text('# base\n', encoding='utf-8')
        (modello / 'config.md').write_text(CONFIG, encoding='utf-8')
        for fase in FASI:
            (modello / 'fasi' / fase).mkdir()
            (modello / 'fasi' / fase / 'CONTEXT.md').write_text(CONTRATTO, encoding='utf-8')
        (modello / 'esecuzioni/vecchia').mkdir(parents=True)
        (modello / 'esecuzioni/vecchia/x.md').write_text('non va copiata', encoding='utf-8')
        return cartella

    def test_crea_da_un_modello_senza_le_esecuzioni(self):
        destinazione = lavorazioni.nuova(self.vault, 'mia', 'base', modelli=self.modelli())
        self.assertEqual(destinazione, self.vault / 'lavorazioni/mia')
        self.assertTrue((destinazione / 'fasi/02-sintesi/CONTEXT.md').is_file())
        self.assertFalse((destinazione / 'esecuzioni').exists())
        self.assertEqual(self.codici('mia'), [])

    def test_crea_da_una_lavorazione_esistente(self):
        self.crea('origine')
        lavorazioni.avvia(self.vault, 'origine', oggi='2026-10-30')
        destinazione = lavorazioni.nuova(self.vault, 'copia', 'origine', modelli=self.modelli())
        self.assertTrue((destinazione / 'config.md').is_file())
        self.assertFalse((destinazione / 'esecuzioni').exists())

    def test_rifiuta_destinazione_esistente_modello_ignoto_e_nome_non_valido(self):
        modelli = self.modelli()
        lavorazioni.nuova(self.vault, 'mia', 'base', modelli=modelli)
        for nome, da, codice in (('mia', 'base', 'lavorazione_esistente'), ('altra', 'ignoto', 'modello_inesistente'),
                                 ('../x', 'base', 'nome_non_valido'), ('altra', '../base', 'nome_non_valido')):
            with self.subTest(nome=nome, da=da), self.assertRaises(lavorazioni.LavorazioneError) as errore:
                lavorazioni.nuova(self.vault, nome, da, modelli=modelli)
            self.assertEqual(errore.exception.codice, codice)

    def test_non_segue_i_collegamenti_simbolici_del_modello(self):
        modelli = self.modelli()
        fuori = self.vault / 'segreto.txt'
        fuori.write_text('riservato', encoding='utf-8')
        try:
            (modelli / 'base/leak.md').symlink_to(fuori)
        except OSError:
            self.skipTest('collegamenti simbolici non disponibili')
        destinazione = lavorazioni.nuova(self.vault, 'mia', 'base', modelli=modelli)
        self.assertFalse((destinazione / 'leak.md').exists())


class Raccolta(Base):
    def avvia(self, config=CONFIG, **opzioni):
        self.crea(config=config)
        opzioni.setdefault('oggi', '2026-10-30')
        return lavorazioni.avvia(self.vault, 'prova', **opzioni)

    def test_crea_esecuzione_e_raccolta(self):
        esecuzione = self.avvia()
        base = self.vault / 'lavorazioni/prova/esecuzioni/2026-10-30-1'
        self.assertEqual(Path(esecuzione['percorso']), base)
        self.assertTrue((base / 'esecuzione.json').is_file())
        raccolta = (base / '01-raccolta/raccolta.md').read_text(encoding='utf-8')
        self.assertIn('## [[Rilascio in produzione]]', raccolta)
        self.assertIn('## [[Console di rilascio]]', raccolta)

    def test_ogni_esecuzione_ha_il_suo_numero(self):
        self.avvia()
        secondo = lavorazioni.avvia(self.vault, 'prova', oggi='2026-10-30')
        altro_giorno = lavorazioni.avvia(self.vault, 'prova', oggi='2026-10-31')
        self.assertEqual((secondo['id'], altro_giorno['id']), ('2026-10-30-2', '2026-10-31-1'))

    def test_pagina_nella_raccolta_ha_corpo_relazioni_e_impronta_senza_frontmatter(self):
        esecuzione = self.avvia()
        raccolta = (Path(esecuzione['percorso']) / '01-raccolta/raccolta.md').read_text(encoding='utf-8')
        sorgente = (self.vault / 'wiki/Console di rilascio.md').read_text(encoding='utf-8')
        impronta = hashlib.sha256(sorgente.encode('utf-8')).hexdigest()
        self.assertIn(impronta[:12], raccolta)
        self.assertIn('tipo: sistema', raccolta)
        self.assertNotIn('aggiornato: 2026-10-05\n---', raccolta)
        corpo = sorgente.split('\n---', 1)[1].strip().splitlines()[0]
        self.assertIn(corpo, raccolta)
        self.assertIn('usa', raccolta)

    def test_esecuzione_json_registra_impronte_e_parametri(self):
        esecuzione = self.avvia()
        dati = json.loads((Path(esecuzione['percorso']) / 'esecuzione.json').read_text(encoding='utf-8'))
        self.assertEqual(dati['lavorazione'], 'prova')
        self.assertEqual(dati['id'], '2026-10-30-1')
        self.assertEqual(sorted(dati['pagine']), ['Console di rilascio', 'Rilascio in produzione'])
        self.assertEqual(dati['pagine']['Console di rilascio'],
                         hashlib.sha256((self.vault / 'wiki/Console di rilascio.md').read_bytes()).hexdigest())
        self.assertEqual(dati['parametri'], {'destinatari': 'team operativo'})
        self.assertEqual(dati['config_sha256'], hashlib.sha256((self.vault / 'lavorazioni/prova/config.md').read_bytes()).hexdigest())
        self.assertEqual(sorted(dati['contratti']), list(FASI))
        self.assertFalse(dati['troncata'])

    def test_selezione_per_sottografo_con_profondita_e_relazioni(self):
        cfg = CONFIG.replace('profondita: 1', 'profondita: 2').replace('[usa]', '[usa, richiede, parte_di, referente]')
        self.assertEqual(self.pagine(self.avvia(cfg)), ['Console di rilascio', 'Gestionale', 'Incident settimanale',
                                                       'Rilascio in produzione'])

    def test_profondita_zero_e_solo_la_pagina(self):
        self.assertEqual(self.pagine(self.avvia(CONFIG.replace('profondita: 1', 'profondita: 0'))), ['Rilascio in produzione'])

    def test_i_collegamenti_menziona_non_si_seguono_per_impostazione(self):
        cfg = CONFIG.replace('profondita: 1', 'profondita: 3').replace('  relazioni: [usa]\n', '')
        trovate = self.pagine(self.avvia(cfg))
        self.assertNotIn('call-2026-09-10', trovate)
        self.assertIn('Anna Rossi', trovate)

    def test_filtro_per_tipo(self):
        cfg = CONFIG.replace('profondita: 1', 'profondita: 3').replace('  relazioni: [usa]\n', '  tipi: [processo]\n')
        self.assertEqual(self.pagine(self.avvia(cfg)), ['Incident settimanale', 'Rilascio in produzione'])

    def test_senza_punto_di_partenza_si_prendono_tutte_le_pagine_del_filtro(self):
        cfg = '---\nselezione:\n  tipi: [persona]\n---\n'
        self.assertEqual(self.pagine(self.avvia(cfg)), ['Anna Rossi'])

    def test_filtro_per_data_di_aggiornamento(self):
        cfg = '---\nselezione:\n  modificate_da: 7g\n---\n'
        self.assertEqual(self.pagine(self.avvia(cfg, oggi='2026-10-23')), ['Incident settimanale', 'ServiceDesk'])
        self.assertEqual(self.pagine(lavorazioni.avvia(self.vault, 'prova', oggi='2026-11-30')), [])

    def test_massimo_taglia_e_lo_dichiara(self):
        cfg = '---\nselezione:\n  massimo: 3\n---\n'
        esecuzione = self.avvia(cfg)
        dati = json.loads((Path(esecuzione['percorso']) / 'esecuzione.json').read_text(encoding='utf-8'))
        self.assertEqual(len(dati['pagine']), 3)
        self.assertTrue(dati['troncata'])
        self.assertIn('troncata', (Path(esecuzione['percorso']) / '01-raccolta/raccolta.md').read_text(encoding='utf-8'))

    def test_selezione_da_domanda_usa_le_pagine_riconosciute(self):
        cfg = '---\nselezione:\n  domanda: "chi è Anna Rossi?"\n  profondita: 0\n---\n'
        self.assertEqual(self.pagine(self.avvia(cfg)), ['Anna Rossi'])

    def test_selezione_vuota_produce_una_raccolta_vuota_dichiarata(self):
        esecuzione = self.avvia('---\nselezione:\n  tipi: [progetto]\n---\n')
        raccolta = (Path(esecuzione['percorso']) / '01-raccolta/raccolta.md').read_text(encoding='utf-8')
        self.assertIn('Nessuna pagina selezionata', raccolta)

    def test_parametro_sovrascritto_per_una_sola_esecuzione(self):
        self.crea()
        prima = lavorazioni.avvia(self.vault, 'prova', override=['destinatari=direzione', 'selezione.massimo=1'], oggi='2026-10-30')
        dopo = lavorazioni.avvia(self.vault, 'prova', oggi='2026-10-30')
        dati = json.loads((Path(prima['percorso']) / 'esecuzione.json').read_text(encoding='utf-8'))
        self.assertEqual(dati['parametri'], {'destinatari': 'direzione'})
        self.assertEqual(dati['override'], ['destinatari=direzione', 'selezione.massimo=1'])
        self.assertEqual(len(dati['pagine']), 1)
        self.assertEqual(len(self.pagine(dopo)), 2)
        self.assertIn('team operativo', (self.vault / 'lavorazioni/prova/config.md').read_text(encoding='utf-8'))

    def test_override_malformato_o_su_chiave_sconosciuta(self):
        self.crea()
        for override in (['senza-uguale'], ['selezione.colore=blu'], ['selezione.massimo=molti'], ['=x']):
            with self.subTest(override=override), self.assertRaises(lavorazioni.LavorazioneError):
                lavorazioni.avvia(self.vault, 'prova', override=override, oggi='2026-10-30')
        self.assertFalse((self.vault / 'lavorazioni/prova/esecuzioni').exists())

    def test_la_selezione_puo_riferirsi_a_un_parametro(self):
        cfg = '---\nselezione:\n  modificate_da: "{periodo}"\nparametri:\n  periodo: 7g\n---\n'
        self.assertEqual(self.pagine(self.avvia(cfg, oggi='2026-10-23')), ['Incident settimanale', 'ServiceDesk'])
        self.assertEqual(self.pagine(lavorazioni.avvia(self.vault, 'prova', override=['periodo=30g'], oggi='2026-10-23')),
                         ['Acronimo del progetto', 'Anna Rossi', 'Console di rilascio', 'Gestionale',
                          'Incident settimanale', 'Modulo fatture', 'Rilascio in produzione', 'ServiceDesk'])

    def test_raccolta_deterministica(self):
        self.crea()
        a = lavorazioni.avvia(self.vault, 'prova', oggi='2026-10-30')
        b = lavorazioni.avvia(self.vault, 'prova', oggi='2026-10-30')
        def leggi(esecuzione):
            testo = (Path(esecuzione['percorso']) / '01-raccolta/raccolta.md').read_text(encoding='utf-8')
            return testo.replace(esecuzione['id'], 'ID')
        self.assertEqual(leggi(a), leggi(b))

    def test_override_con_doppie_parentesi_quadre_resta_un_testo(self):
        # YAML leggerebbe [[Pagina]] come una lista annidata: gli override non usano YAML.
        self.crea()
        e = lavorazioni.avvia(self.vault, 'prova', override=['selezione.collegate_a=[[Console di rilascio]]',
                                                              'selezione.profondita=0'], oggi='2026-10-30')
        self.assertEqual(self.pagine(e), ['Console di rilascio'])

    def test_override_di_elenchi_separati_da_virgola(self):
        self.crea()
        e = lavorazioni.avvia(self.vault, 'prova', override=['selezione.profondita=3', 'selezione.tipi=processo, persona',
                                                              'selezione.relazioni=usa, richiede, parte_di, referente'],
                              oggi='2026-10-30')
        self.assertEqual(self.pagine(e), ['Anna Rossi', 'Incident settimanale', 'Rilascio in produzione'])

    def test_un_parametro_numerico_resta_numerico(self):
        cfg = '---\nselezione:\n  massimo: "{quanti}"\nparametri:\n  quanti: 2\n---\n'
        self.crea(config=cfg)
        e = lavorazioni.avvia(self.vault, 'prova', override=['quanti=3'], oggi='2026-10-30')
        self.assertEqual(len(self.pagine(e)), 3)
        with self.assertRaises(lavorazioni.LavorazioneError):
            lavorazioni.avvia(self.vault, 'prova', override=['quanti=tre'], oggi='2026-10-30')

    def test_collegate_a_vuoto_chiede_la_pagina(self):
        cfg = '---\nselezione:\n  collegate_a: "{argomento}"\nparametri:\n  argomento: ""\n---\n'
        self.crea(config=cfg)
        with self.assertRaises(lavorazioni.LavorazioneError) as errore:
            lavorazioni.avvia(self.vault, 'prova', oggi='2026-10-30')
        self.assertEqual(errore.exception.codice, 'pagina_inesistente')
        self.assertIn('argomento', str(errore.exception))
        e = lavorazioni.avvia(self.vault, 'prova', override=['argomento=Anna Rossi'], oggi='2026-10-30')
        self.assertIn('Anna Rossi', self.pagine(e))

    def test_scrive_solo_dentro_l_esecuzione(self):
        self.crea()
        prima = hash_albero(self.vault)
        esecuzione = lavorazioni.avvia(self.vault, 'prova', oggi='2026-10-30')
        dopo = hash_albero(self.vault)
        nuovi = sorted(set(dopo) - set(prima))
        self.assertEqual(nuovi, ['lavorazioni/prova/esecuzioni/2026-10-30-1/01-raccolta/raccolta.md',
                                 'lavorazioni/prova/esecuzioni/2026-10-30-1/esecuzione.json'])
        self.assertEqual({k: v for k, v in prima.items()}, {k: dopo[k] for k in prima})
        self.assertEqual(esecuzione['id'], '2026-10-30-1')

    def test_rifiuta_una_lavorazione_non_valida(self):
        self.crea(config=None)
        with self.assertRaises(lavorazioni.LavorazioneError) as errore:
            lavorazioni.avvia(self.vault, 'prova', oggi='2026-10-30')
        self.assertEqual(errore.exception.codice, 'lavorazione_non_valida')
        self.assertFalse((self.vault / 'lavorazioni/prova/esecuzioni').exists())

    def test_senza_grafo_chiede_di_costruirlo(self):
        self.crea()
        (self.vault / '.graph/graph.sqlite').unlink()
        with self.assertRaises(lavorazioni.LavorazioneError) as errore:
            lavorazioni.avvia(self.vault, 'prova', oggi='2026-10-30')
        self.assertEqual(errore.exception.codice, 'grafo_assente')
        self.assertIn('build_graph.py', str(errore.exception))

    def test_data_non_valida(self):
        self.crea()
        with self.assertRaises(lavorazioni.LavorazioneError):
            lavorazioni.avvia(self.vault, 'prova', oggi='ieri')


MODELLI = KIT / 'lavorazioni'
NOMI_MODELLI = ['report-periodico', 'scheda-argomento']


class Modelli(Base):
    """I modelli inclusi nel kit: validi, brevi, configurabili e utilizzabili da riga di comando dopo l'installazione."""

    def da_modello(self, modello, nome=None):
        return lavorazioni.nuova(self.vault, nome or modello, modello, modelli=MODELLI)

    def test_ci_sono_i_due_modelli(self):
        self.assertEqual(sorted(p.name for p in MODELLI.iterdir() if p.is_dir()), NOMI_MODELLI)

    def test_ogni_modello_e_valido_appena_creato(self):
        for modello in NOMI_MODELLI:
            with self.subTest(modello=modello):
                self.da_modello(modello)
                self.assertEqual(lavorazioni.valida(self.vault, modello), [])

    def test_contratti_brevi_e_riferimenti_sotto_il_limite(self):
        for modello in NOMI_MODELLI:
            base = self.da_modello(modello)
            self.assertLessEqual(len((base / 'CONTEXT.md').read_text(encoding='utf-8').splitlines()), 80)
            for contratto in sorted((base / 'fasi').glob('*/CONTEXT.md')):
                with self.subTest(modello=modello, fase=contratto.parent.name):
                    esito = contratti.valida(contratto, radice=self.vault)
                    self.assertEqual((esito['errori'], esito['avvisi']), ([], []))
            for riferimento in sorted((base / 'riferimenti').glob('*.md')):
                self.assertLessEqual(len(riferimento.read_text(encoding='utf-8').splitlines()), 200, riferimento.name)

    def test_la_prima_fase_e_la_raccolta_e_le_creative_hanno_un_checkpoint(self):
        attese = {'report-periodico': ['02-sintesi'], 'scheda-argomento': ['02-scaletta', '03-stesura']}
        for modello in NOMI_MODELLI:
            base = self.da_modello(modello)
            fasi = sorted(p.name for p in (base / 'fasi').iterdir())
            self.assertEqual(fasi[0], '01-raccolta')
            for fase in attese[modello]:
                with self.subTest(modello=modello, fase=fase):
                    self.assertIn('\n## Checkpoint\n', (base / 'fasi' / fase / 'CONTEXT.md').read_text(encoding='utf-8'))

    def test_questionario_piatto_numerato_e_con_predefiniti(self):
        for modello in NOMI_MODELLI:
            with self.subTest(modello=modello):
                testo = (MODELLI / modello / 'setup/questionario.md').read_text(encoding='utf-8')
                domande = [r for r in testo.splitlines() if re.match(r'^\d+\. ', r)]
                self.assertGreaterEqual(len(domande), 3)
                self.assertTrue(all('predefinito' in r for r in domande), domande)

    def test_la_scheda_confronta_la_stesura_con_scaletta_e_raccolta(self):
        base = self.da_modello('scheda-argomento')
        verifica = (base / 'fasi/04-verifica/CONTEXT.md').read_text(encoding='utf-8')
        for fase in ('01-raccolta', '02-scaletta', '03-stesura'):
            self.assertIn(fase, verifica)

    def test_report_periodico_sull_esempio(self):
        self.da_modello('report-periodico')
        self.assertEqual(self.pagine(lavorazioni.avvia(self.vault, 'report-periodico', oggi='2026-10-23')),
                         ['Incident settimanale', 'ServiceDesk'])
        self.assertEqual(len(self.pagine(lavorazioni.avvia(self.vault, 'report-periodico', override=['periodo=30g'],
                                                          oggi='2026-10-23'))), 8)

    def test_scheda_argomento_chiede_la_pagina_e_poi_segue_le_relazioni(self):
        self.da_modello('scheda-argomento')
        with self.assertRaises(lavorazioni.LavorazioneError) as errore:
            lavorazioni.avvia(self.vault, 'scheda-argomento', oggi='2026-10-23')
        self.assertEqual(errore.exception.codice, 'pagina_inesistente')
        trovate = self.pagine(lavorazioni.avvia(self.vault, 'scheda-argomento', override=['argomento=Rilascio in produzione'],
                                                oggi='2026-10-23'))
        self.assertIn('Rilascio in produzione', trovate)
        self.assertIn('Console di rilascio', trovate)

    def test_i_modelli_indicano_l_output_finale_e_il_contratto_lo_produce(self):
        for modello, fase in (('report-periodico', '03-revisione'), ('scheda-argomento', '03-stesura')):
            with self.subTest(modello=modello):
                base = self.da_modello(modello)
                cornice, _ = build_graph.leggi_testo((base / 'config.md').read_text(encoding='utf-8'), 'config.md')
                self.assertTrue(cornice['finale'].startswith(fase + '/'), cornice['finale'])
                contratto = (base / 'fasi' / fase / 'CONTEXT.md').read_text(encoding='utf-8')
                self.assertIn('{esecuzione}/' + cornice['finale'], contratto)

    def test_le_fasi_di_scrittura_indicano_il_comando_di_verifica(self):
        for modello, fasi in (('report-periodico', ('02-sintesi', '03-revisione')),
                              ('scheda-argomento', ('02-scaletta', '03-stesura', '04-verifica'))):
            base = self.da_modello(modello)
            for fase in fasi:
                with self.subTest(modello=modello, fase=fase):
                    testo = (base / 'fasi' / fase / 'CONTEXT.md').read_text(encoding='utf-8')
                    self.assertIn(f'python .graph/lavorazioni.py verifica <nome> --fase {fase[:2]}', testo)

    def test_installazione_distribuisce_i_modelli_e_funziona_da_riga_di_comando(self):
        # Scenario completo senza modello AI: installa, crea da modello, valida, avvia, stato.
        destinazione = Path(tempfile.mkdtemp(prefix='teseo-lav-', dir=self.vault.parent))
        self.addCleanup(shutil.rmtree, destinazione, True)
        with redirect_stdout(io.StringIO()):
            installa.installa(destinazione, skill='no', client='claude', esempio=True)
        for modello in NOMI_MODELLI:
            self.assertTrue((destinazione / '.graph/modelli' / modello / 'config.md').is_file())

        def esegui(*argomenti):
            fatto = subprocess.run([sys.executable, *argomenti], cwd=destinazione, capture_output=True, timeout=120)
            return fatto.returncode, (fatto.stdout + fatto.stderr).decode('utf-8', 'replace')
        self.assertEqual(esegui('.graph/build_graph.py', '--check')[0], 0)
        self.assertIn('creata', esegui('.graph/lavorazioni.py', 'nuova', 'mio', '--da', 'report-periodico')[1])
        self.assertEqual(esegui('.graph/lavorazioni.py', 'valida', 'mio'), (0, 'mio: ok\n'))
        codice, uscita = esegui('.graph/lavorazioni.py', 'avvia', 'mio', '--oggi', '2026-10-23')
        self.assertEqual(codice, 0, uscita)
        self.assertIn('2 pagine', uscita)
        self.assertIn('COMPLETA', esegui('.graph/lavorazioni.py', 'stato', 'mio')[1])
        self.assertEqual(esegui('.graph/lavorazioni.py', 'avvia', 'mio', '--param', 'periodo=ieri')[0], 1)
        # Dal risultato alla wiki: verifica, promozione una sola volta, grafo ancora valido con il nuovo file in raw/.
        esecuzione = destinazione / 'lavorazioni/mio/esecuzioni/2026-10-23-1'
        (esecuzione / '02-sintesi').mkdir()
        (esecuzione / '02-sintesi/sintesi.md').write_text('Bozza su [[Incident settimanale]].\n', encoding='utf-8')
        (esecuzione / '03-revisione').mkdir()
        (esecuzione / '03-revisione/report.md').write_text('Il report cita l\'[[Incident settimanale]] [call-2026-09-10].\n', encoding='utf-8')
        self.assertEqual(esegui('.graph/lavorazioni.py', 'verifica', 'mio', '--fase', '03', '--citazioni')[0], 0)
        codice, uscita = esegui('.graph/lavorazioni.py', 'promuovi', 'mio')
        self.assertEqual(codice, 0, uscita)
        self.assertTrue((destinazione / 'raw/lavorazione-mio-2026-10-23-1.md').is_file())
        self.assertEqual(esegui('.graph/lavorazioni.py', 'promuovi', 'mio')[0], 1)
        self.assertEqual(esegui('.graph/build_graph.py', '--check')[0], 0)


class Stato(Base):
    def test_senza_esecuzioni_tutte_in_attesa(self):
        self.crea()
        stato = lavorazioni.stato(self.vault, 'prova')
        self.assertIsNone(stato['esecuzione'])
        self.assertEqual([f['stato'] for f in stato['fasi']], ['IN ATTESA'] * 3)

    def test_dopo_l_avvio_la_raccolta_e_completa(self):
        self.crea()
        lavorazioni.avvia(self.vault, 'prova', oggi='2026-10-30')
        stato = lavorazioni.stato(self.vault, 'prova')
        self.assertEqual(stato['esecuzione'], '2026-10-30-1')
        self.assertEqual([(f['nome'], f['stato']) for f in stato['fasi']],
                         [('01-raccolta', 'COMPLETA'), ('02-sintesi', 'IN ATTESA'), ('03-revisione', 'IN ATTESA')])
        self.assertEqual(stato['fasi'][0]['file'], ['raccolta.md'])

    def test_una_fase_con_output_e_completa_e_gitkeep_non_conta(self):
        self.crea()
        esecuzione = lavorazioni.avvia(self.vault, 'prova', oggi='2026-10-30')
        fase = Path(esecuzione['percorso']) / '02-sintesi'
        fase.mkdir()
        (fase / '.gitkeep').write_text('', encoding='utf-8')
        self.assertEqual(lavorazioni.stato(self.vault, 'prova')['fasi'][1]['stato'], 'IN ATTESA')
        (fase / 'sintesi.md').write_text('bozza', encoding='utf-8')
        self.assertEqual(lavorazioni.stato(self.vault, 'prova')['fasi'][1]['stato'], 'COMPLETA')

    def test_stato_di_un_esecuzione_precisa(self):
        self.crea()
        lavorazioni.avvia(self.vault, 'prova', oggi='2026-10-30')
        lavorazioni.avvia(self.vault, 'prova', oggi='2026-10-30')
        self.assertEqual(lavorazioni.stato(self.vault, 'prova', '2026-10-30-1')['esecuzione'], '2026-10-30-1')
        with self.assertRaises(lavorazioni.LavorazioneError):
            lavorazioni.stato(self.vault, 'prova', '2026-01-01-1')
        with self.assertRaises(lavorazioni.LavorazioneError):
            lavorazioni.stato(self.vault, 'prova', '../..')

    def test_disegno_ascii(self):
        self.crea()
        lavorazioni.avvia(self.vault, 'prova', oggi='2026-10-30')
        disegno = lavorazioni.disegna(lavorazioni.stato(self.vault, 'prova'))
        self.assertIn('prova · esecuzione 2026-10-30-1', disegno)
        self.assertIn('[01-raccolta] --> [02-sintesi] --> [03-revisione]', disegno)
        self.assertIn('COMPLETA', disegno)
        self.assertIn('IN ATTESA', disegno)


def scrivi_output(esecuzione, fase, nome, testo, ora):
    """Scrive un output di fase con una data di modifica precisa, per rendere deterministico il confronto fra fasi."""
    percorso = Path(esecuzione['percorso']) / fase / nome
    percorso.parent.mkdir(parents=True, exist_ok=True)
    percorso.write_text(testo, encoding='utf-8')
    os.utime(percorso, (ora, ora))
    return percorso


class Obsolescenza(Base):
    """Una fase è DA RIFARE se, dopo il suo output, è cambiato qualcosa da cui dipende."""

    T0 = 1_800_000_000

    def esecuzione(self):
        self.crea()
        e = lavorazioni.avvia(self.vault, 'prova', oggi='2026-10-30')
        raccolta = Path(e['percorso']) / '01-raccolta/raccolta.md'
        os.utime(raccolta, (self.T0, self.T0))
        scrivi_output(e, '02-sintesi', 'sintesi.md', 'bozza', self.T0 + 10)
        scrivi_output(e, '03-revisione', 'report.md', 'finale', self.T0 + 20)
        return e

    def stati(self):
        s = lavorazioni.stato(self.vault, 'prova')
        return {f['nome']: f['stato'] for f in s['fasi']}, {f['nome']: f['motivi'] for f in s['fasi']}

    def test_esecuzione_appena_fatta_non_ha_fasi_da_rifare(self):
        self.esecuzione()
        stati, motivi = self.stati()
        self.assertEqual(list(stati.values()), ['COMPLETA'] * 3)
        self.assertEqual(list(motivi.values()), [[], [], []])

    def test_pagina_della_raccolta_modificata_rende_da_rifare_la_raccolta_e_le_fasi_a_valle(self):
        self.esecuzione()
        pagina = self.vault / 'wiki/Console di rilascio.md'
        pagina.write_text(pagina.read_text(encoding='utf-8') + '\nNuovo fatto.\n', encoding='utf-8')
        stati, motivi = self.stati()
        self.assertEqual(list(stati.values()), ['DA RIFARE'] * 3)
        self.assertIn('Console di rilascio', motivi['01-raccolta'][0])
        self.assertIn('01-raccolta', motivi['02-sintesi'][0])

    def test_le_fasi_in_attesa_restano_in_attesa(self):
        e = self.esecuzione()
        shutil.rmtree(Path(e['percorso']) / '03-revisione')
        pagina = self.vault / 'wiki/Console di rilascio.md'
        pagina.write_text(pagina.read_text(encoding='utf-8') + '\nNuovo fatto.\n', encoding='utf-8')
        self.assertEqual(list(self.stati()[0].values()), ['DA RIFARE', 'DA RIFARE', 'IN ATTESA'])

    def test_pagina_fuori_dalla_raccolta_non_conta(self):
        self.esecuzione()
        pagina = self.vault / 'wiki/Anna Rossi.md'
        pagina.write_text(pagina.read_text(encoding='utf-8') + '\nNuovo fatto.\n', encoding='utf-8')
        self.assertEqual(list(self.stati()[0].values()), ['COMPLETA'] * 3)

    def test_pagina_rimossa(self):
        self.esecuzione()
        (self.vault / 'wiki/Console di rilascio.md').unlink()
        self.assertIn('rimossa', self.stati()[1]['01-raccolta'][0])

    def test_config_modificato(self):
        self.esecuzione()
        config = self.vault / 'lavorazioni/prova/config.md'
        config.write_text(config.read_text(encoding='utf-8') + '\nNuova regola.\n', encoding='utf-8')
        stati, motivi = self.stati()
        self.assertEqual(stati['01-raccolta'], 'DA RIFARE')
        self.assertIn('config.md', motivi['01-raccolta'][0])

    def test_contratto_modificato_rifa_quella_fase_e_le_successive_ma_non_le_precedenti(self):
        self.esecuzione()
        contratto = self.vault / 'lavorazioni/prova/fasi/02-sintesi/CONTEXT.md'
        contratto.write_text(contratto.read_text(encoding='utf-8') + '\n2. Nuovo passo.\n', encoding='utf-8')
        stati, motivi = self.stati()
        self.assertEqual(list(stati.values()), ['COMPLETA', 'DA RIFARE', 'DA RIFARE'])
        self.assertIn('contratto', motivi['02-sintesi'][0])

    def test_output_di_una_fase_modificato_dopo_quello_della_fase_successiva(self):
        e = self.esecuzione()
        scrivi_output(e, '02-sintesi', 'sintesi.md', 'bozza corretta dall\'utente', self.T0 + 30)
        stati, motivi = self.stati()
        self.assertEqual(list(stati.values()), ['COMPLETA', 'COMPLETA', 'DA RIFARE'])
        self.assertIn('02-sintesi', motivi['03-revisione'][0])

    def test_correzione_della_raccolta_dopo_la_sintesi(self):
        e = self.esecuzione()
        os.utime(Path(e['percorso']) / '01-raccolta/raccolta.md', (self.T0 + 15, self.T0 + 15))
        stati, _ = self.stati()
        self.assertEqual(list(stati.values()), ['COMPLETA', 'DA RIFARE', 'DA RIFARE'])

    def test_senza_registro_non_si_blocca(self):
        e = self.esecuzione()
        (Path(e['percorso']) / 'esecuzione.json').write_text('non è json', encoding='utf-8')
        self.assertEqual(list(self.stati()[0].values()), ['COMPLETA'] * 3)

    def test_disegno_indica_il_motivo(self):
        self.esecuzione()
        (self.vault / 'wiki/Console di rilascio.md').unlink()
        disegno = lavorazioni.disegna(lavorazioni.stato(self.vault, 'prova'))
        self.assertIn('DA RIFARE', disegno)
        self.assertIn('rimossa', disegno)

    def test_stato_json_da_riga_di_comando_ha_i_motivi(self):
        self.esecuzione()
        (self.vault / 'wiki/Console di rilascio.md').unlink()
        uscita = io.StringIO()
        with redirect_stdout(uscita):
            lavorazioni.main(['--vault', str(self.vault), 'stato', 'prova', '--json'])
        self.assertIn('rimossa', json.loads(uscita.getvalue())['fasi'][0]['motivi'][0])


class Verifica(Base):
    """Controlli deterministici sull'output di una fase; la coerenza di significato resta al modello."""

    def setUp(self):
        super().setUp()
        self.crea()
        self.e = lavorazioni.avvia(self.vault, 'prova', oggi='2026-10-30')

    def output(self, testo, fase='02-sintesi', nome='sintesi.md'):
        scrivi_output(self.e, fase, nome, testo, 1_800_000_100)

    def codici(self, fase='02', **opzioni):
        return [p['codice'] for p in lavorazioni.verifica(self.vault, 'prova', fase, **opzioni)]

    def test_output_con_link_alla_raccolta_e_valido(self):
        self.output('# Sintesi\n\nIl rilascio passa dalla [[Console di rilascio]] [call-2026-09-10 34:39] e da [[Rilascio in produzione]].\n')
        self.assertEqual(self.codici(), [])

    def test_link_a_una_pagina_inventata(self):
        self.output('Vedi [[Pagina inventata]].\n')
        self.assertEqual(self.codici(), ['link_inesistente'])

    def test_link_a_una_pagina_che_esiste_ma_non_e_nella_raccolta(self):
        self.output('Referente: [[Anna Rossi]].\n')
        self.assertEqual(self.codici(), ['link_fuori_raccolta'])

    def test_link_con_testo_sezione_alias_e_maiuscole(self):
        self.output('[[Console di rilascio|la console]] [[console di rilascio#Dettagli]] [[console]] [[wiki/Console di rilascio]]\n')
        self.assertEqual(self.codici(), [])

    def test_codice_non_conta(self):
        self.output('`[[Pagina inventata]]`\n\n```\n[[Altra inventata]] {{X}} [nota-fantasma]\n```\n')
        self.assertEqual(self.codici(), [])

    def test_fonte_non_censita_e_fonti_ammesse(self):
        self.output('Frase [nota-fantasma]. Altra [call-2026-09-10] e [nota-utente] e [x] e [testo-link](http://esempio.it).\n')
        problemi = lavorazioni.verifica(self.vault, 'prova', '02')
        self.assertEqual([(p['codice'], p['riga']) for p in problemi], [('fonte_non_censita', 1)])
        self.assertIn('nota-fantasma', problemi[0]['messaggio'])

    def test_segnaposto(self):
        self.output('Destinatari: {{DESTINATARI}}\n')
        self.assertEqual(self.codici(), ['segnaposto'])

    def test_fase_senza_output(self):
        self.assertEqual(self.codici(), ['fase_senza_output'])

    def test_citazioni_per_paragrafo_solo_se_richieste(self):
        self.output('# Titolo\n\nQuesto paragrafo è abbastanza lungo ma non cita nessuna pagina del vault.\n\n'
                    '| a | b |\n| --- | --- |\n\n> citazione lunga senza collegamento a nessuna pagina del vault qui\n\n'
                    'Breve.\n\nQuesto invece cita la [[Console di rilascio]] come richiesto dal contratto della fase.\n')
        self.assertEqual(self.codici(), [])
        problemi = lavorazioni.verifica(self.vault, 'prova', '02', citazioni=True)
        self.assertEqual([(p['codice'], p['riga']) for p in problemi], [('paragrafo_senza_citazione', 3)])

    def test_verifica_sulla_raccolta(self):
        self.assertEqual(self.codici('01'), [])
        (Path(self.e['percorso']) / '01-raccolta/raccolta.md').write_text('# Raccolta\n\nNessuna pagina selezionata: x.\n', encoding='utf-8')
        self.assertEqual(self.codici('01'), ['raccolta_vuota'])

    def test_la_fase_si_indica_con_numero_o_nome(self):
        self.output('ok [[Console di rilascio]]\n')
        self.assertEqual(self.codici('02'), self.codici('02-sintesi'))
        for fase in ('09', 'sintesi', '../x'):
            with self.subTest(fase=fase), self.assertRaises(lavorazioni.LavorazioneError) as errore:
                lavorazioni.verifica(self.vault, 'prova', fase)
            self.assertEqual(errore.exception.codice, 'fase_inesistente')

    def test_senza_registro_non_si_puo_verificare(self):
        self.output('ok\n')
        (Path(self.e['percorso']) / 'esecuzione.json').unlink()
        with self.assertRaises(lavorazioni.LavorazioneError) as errore:
            lavorazioni.verifica(self.vault, 'prova', '02')
        self.assertEqual(errore.exception.codice, 'registro_mancante')

    def test_non_scrive_nulla(self):
        self.output('Vedi [[Pagina inventata]].\n')
        prima = hash_albero(self.vault)
        self.codici()
        self.assertEqual(prima, hash_albero(self.vault))

    def test_i_problemi_escono_in_ordine_di_riga(self):
        self.output('Vedi [[Pagina inventata]] ancora.\n\nParagrafo lungo e senza alcun collegamento a una pagina qualsiasi.\n\n'
                    'Poi [[Altra inventata]].\n')
        problemi = lavorazioni.verifica(self.vault, 'prova', '02', citazioni=True)
        self.assertEqual([p['riga'] for p in problemi], [1, 3, 5])

    def test_un_esecuzione_precisa(self):
        self.output('ok [[Console di rilascio]]\n')
        seconda = lavorazioni.avvia(self.vault, 'prova', oggi='2026-10-30')
        self.assertEqual(self.codici('02', esecuzione=self.e['id']), [])
        self.assertEqual(self.codici('02', esecuzione=seconda['id']), ['fase_senza_output'])

    def test_riga_di_comando(self):
        uscita, errori = io.StringIO(), io.StringIO()

        def esegui(*argomenti):
            uscita.seek(0), uscita.truncate(), errori.seek(0), errori.truncate()
            with redirect_stdout(uscita), redirect_stderr(errori):
                return lavorazioni.main(['--vault', str(self.vault), 'verifica', 'prova', *argomenti])
        self.output('ok [[Console di rilascio]]\n')
        self.assertEqual(esegui('--fase', '02'), 0)
        self.assertIn('ok', uscita.getvalue())
        self.output('rotto [[Pagina inventata]]\n')
        self.assertEqual(esegui('--fase', '02'), 1)
        self.assertIn('link_inesistente', uscita.getvalue())
        self.assertEqual(json.loads((esegui('--fase', '02', '--json'), uscita.getvalue())[1])[0]['codice'], 'link_inesistente')
        self.assertEqual(esegui('--fase', '09'), 1)
        self.assertIn('fase_inesistente', errori.getvalue())


class Promozione(Base):
    """promuovi: l'output finale entra nella wiki solo come nuova fonte in raw/, con la provenienza, dopo ingest."""

    CONFIG_FINALE = CONFIG.replace('parametri:', 'finale: 03-revisione/report.md\nparametri:')

    def setUp(self):
        super().setUp()
        self.crea(config=self.CONFIG_FINALE)
        self.e = lavorazioni.avvia(self.vault, 'prova', oggi='2026-10-30')
        scrivi_output(self.e, '02-sintesi', 'sintesi.md', 'bozza [[Console di rilascio]]\n', 1_800_000_010)
        scrivi_output(self.e, '03-revisione', 'report.md', '# Report\n\nLa [[Console di rilascio]] [call-2026-09-10] regge il rilascio.\n',
                      1_800_000_020)
        os.utime(Path(self.e['percorso']) / '01-raccolta/raccolta.md', (1_800_000_000, 1_800_000_000))

    def promuovi(self, **opzioni):
        opzioni.setdefault('oggi', '2026-10-31')
        return lavorazioni.promuovi(self.vault, 'prova', **opzioni)

    def test_promuove_con_provenienza_e_senza_toccare_altro(self):
        prima = hash_albero(self.vault)
        esito = self.promuovi()
        destinazione = self.vault / 'raw/lavorazione-prova-2026-10-30-1.md'
        self.assertEqual(esito['percorso'], 'raw/lavorazione-prova-2026-10-30-1.md')
        self.assertEqual(esito['chiave'], 'lavorazione-prova-2026-10-30-1')
        self.assertEqual(sorted(set(hash_albero(self.vault)) - set(prima)), ['raw/lavorazione-prova-2026-10-30-1.md'])
        self.assertEqual({k: v for k, v in hash_albero(self.vault).items() if k in prima}, prima)
        testo = destinazione.read_text(encoding='utf-8')
        cornice, corpo = build_graph.leggi_testo(testo, destinazione.name)
        self.assertEqual((cornice['origine'], cornice['lavorazione'], cornice['esecuzione'], cornice['file']),
                         ('lavorazione', 'prova', '2026-10-30-1', '03-revisione/report.md'))
        self.assertEqual(cornice['generato_il'], '2026-10-31')
        registro = json.loads((Path(self.e['percorso']) / 'esecuzione.json').read_text(encoding='utf-8'))
        self.assertEqual(cornice['pagine'], registro['pagine'])
        self.assertIn('La [[Console di rilascio]] [call-2026-09-10] regge il rilascio.', corpo)
        self.assertIn('documento derivato', corpo.lower())

    def test_non_sovrascrive_mai_un_file_di_raw(self):
        self.promuovi()
        destinazione = self.vault / 'raw/lavorazione-prova-2026-10-30-1.md'
        prima = destinazione.read_bytes()
        with self.assertRaises(lavorazioni.LavorazioneError) as errore:
            self.promuovi(oggi='2026-11-02')
        self.assertEqual(errore.exception.codice, 'raw_esistente')
        self.assertEqual(destinazione.read_bytes(), prima)

    def test_due_esecuzioni_dello_stesso_giorno_hanno_file_diversi(self):
        self.promuovi()
        seconda = lavorazioni.avvia(self.vault, 'prova', oggi='2026-10-30')
        scrivi_output(seconda, '03-revisione', 'report.md', 'secondo [[Console di rilascio]]\n', 1_800_000_020)
        os.utime(Path(seconda['percorso']) / '01-raccolta/raccolta.md', (1_800_000_000, 1_800_000_000))
        self.assertEqual(self.promuovi(esecuzione=seconda['id'])['percorso'], 'raw/lavorazione-prova-2026-10-30-2.md')

    def test_senza_output_finale_in_config_serve_il_file(self):
        self.crea('altra')
        lavorazioni.avvia(self.vault, 'altra', oggi='2026-10-30')
        with self.assertRaises(lavorazioni.LavorazioneError) as errore:
            lavorazioni.promuovi(self.vault, 'altra', oggi='2026-10-31')
        self.assertEqual(errore.exception.codice, 'file_da_indicare')

    def test_file_indicato_a_mano_prevale_su_config(self):
        esito = self.promuovi(file='02-sintesi/sintesi.md')
        self.assertIn('bozza', (self.vault / esito['percorso']).read_text(encoding='utf-8'))

    def test_file_non_valido(self):
        for file in ('../../../wiki/Anna Rossi.md', '/etc/passwd', '03-revisione/non-c-e.md', '03-revisione/report.txt',
                     '03-revisione', 'esecuzione.json', 'report.md'):
            with self.subTest(file=file), self.assertRaises(lavorazioni.LavorazioneError) as errore:
                self.promuovi(file=file)
            self.assertEqual(errore.exception.codice, 'file_non_valido')
        self.assertEqual(list((self.vault / 'raw').glob('lavorazione-*')), [])

    def test_non_segue_collegamenti_simbolici_fuori_dall_esecuzione(self):
        fuori = self.vault / 'wiki/Anna Rossi.md'
        collegamento = Path(self.e['percorso']) / '03-revisione/furbo.md'
        try:
            collegamento.symlink_to(fuori)
        except OSError:
            self.skipTest('collegamenti simbolici non disponibili')
        with self.assertRaises(lavorazioni.LavorazioneError) as errore:
            self.promuovi(file='03-revisione/furbo.md')
        self.assertEqual(errore.exception.codice, 'file_non_valido')

    def test_rifiuta_un_output_che_non_supera_la_verifica(self):
        scrivi_output(self.e, '03-revisione', 'report.md', 'Vedi [[Pagina inventata]].\n', 1_800_000_020)
        with self.assertRaises(lavorazioni.LavorazioneError) as errore:
            self.promuovi()
        self.assertEqual(errore.exception.codice, 'verifica_fallita')
        self.assertIn('link_inesistente', str(errore.exception))
        self.assertEqual(list((self.vault / 'raw').glob('lavorazione-*')), [])

    def test_rifiuta_una_fase_da_rifare(self):
        pagina = self.vault / 'wiki/Console di rilascio.md'
        pagina.write_text(pagina.read_text(encoding='utf-8') + '\nCambiata.\n', encoding='utf-8')
        with self.assertRaises(lavorazioni.LavorazioneError) as errore:
            self.promuovi()
        self.assertEqual(errore.exception.codice, 'fase_da_rifare')
        self.assertIn('Console di rilascio', str(errore.exception))
        self.assertEqual(list((self.vault / 'raw').glob('lavorazione-*')), [])

    def test_senza_cartella_raw(self):
        shutil.rmtree(self.vault / 'raw')
        with self.assertRaises(lavorazioni.LavorazioneError) as errore:
            self.promuovi()
        self.assertEqual(errore.exception.codice, 'raw_assente')

    def test_il_grafo_resta_valido_dopo_la_promozione(self):
        self.promuovi()
        with redirect_stdout(io.StringIO()):
            problemi = build_graph.costruisci(self.vault, self.vault / '.graph/graph.sqlite')
        self.assertEqual(problemi, [])

    def test_finale_in_config_deve_essere_un_percorso_markdown_relativo(self):
        for valore in ('../x.md', '/x.md', 'x.txt', '', '03-revisione/../../x.md'):
            with self.subTest(valore=valore):
                self.crea('cfg', config=CONFIG.replace('parametri:', f'finale: "{valore}"\nparametri:'))
                self.assertIn('config_tipo', self.codici('cfg'))
                shutil.rmtree(self.vault / 'lavorazioni/cfg')

    def test_riga_di_comando_e_suggerimenti(self):
        def esegui(*argomenti):
            uscita, errori = io.StringIO(), io.StringIO()
            with redirect_stdout(uscita), redirect_stderr(errori):
                codice = lavorazioni.main(['--vault', str(self.vault), 'promuovi', 'prova', '--oggi', '2026-10-31', *argomenti])
            return codice, uscita.getvalue(), errori.getvalue()
        codice, uscita, _ = esegui()
        self.assertEqual(codice, 0)
        self.assertIn('raw/lavorazione-prova-2026-10-30-1.md', uscita)
        self.assertIn('| `lavorazione-prova-2026-10-30-1` | `raw/lavorazione-prova-2026-10-30-1.md` |', uscita)
        self.assertNotIn('teseo_git', uscita)
        codice, uscita, errori = esegui()
        self.assertEqual((codice, uscita), (1, ''))
        self.assertIn('raw_esistente', errori)

    def test_nei_vault_collaborativi_ricorda_di_pubblicare_prima_dell_ingest(self):
        (self.vault / '.graph/teseo_git.py').write_text('', encoding='utf-8')
        uscita = io.StringIO()
        with redirect_stdout(uscita):
            lavorazioni.main(['--vault', str(self.vault), 'promuovi', 'prova', '--oggi', '2026-10-31'])
        self.assertIn('teseo_git.py post --skill manuale --agente umano', uscita.getvalue())


class Esporta(Base):
    """Condividere una lavorazione senza toccare il contratto dati: si esporta la definizione in una cartella e si importa altrove."""

    def setUp(self):
        super().setUp()
        self.crea()
        base = self.vault / 'lavorazioni/prova'
        (base / 'setup').mkdir()
        (base / 'setup/questionario.md').write_text('1. Domanda? (predefinito: x)\n', encoding='utf-8')
        (base / 'riferimenti').mkdir()
        (base / 'riferimenti/stile.md').write_text('# Stile\n', encoding='utf-8')
        lavorazioni.avvia(self.vault, 'prova', oggi='2026-10-30')
        self.fuori = Path(tempfile.mkdtemp(prefix='teseo-esporta-', dir=self.vault.parent))
        self.addCleanup(shutil.rmtree, self.fuori, True)

    def elenco(self, cartella):
        return sorted(p.relative_to(cartella).as_posix() for p in Path(cartella).rglob('*') if p.is_file())

    def test_esporta_la_definizione_senza_le_esecuzioni(self):
        destinazione = lavorazioni.esporta(self.vault, 'prova', self.fuori)
        self.assertEqual(destinazione, self.fuori / 'prova')
        file = self.elenco(destinazione)
        self.assertIn('config.md', file)
        self.assertIn('fasi/02-sintesi/CONTEXT.md', file)
        self.assertIn('setup/questionario.md', file)
        self.assertIn('riferimenti/stile.md', file)
        self.assertFalse([f for f in file if f.startswith('esecuzioni')])

    def test_non_sovrascrive_e_non_scrive_dove_non_deve(self):
        lavorazioni.esporta(self.vault, 'prova', self.fuori)
        with self.assertRaises(lavorazioni.LavorazioneError) as errore:
            lavorazioni.esporta(self.vault, 'prova', self.fuori)
        self.assertEqual(errore.exception.codice, 'destinazione_esistente')
        for proibita in ('wiki', 'raw', '.graph', 'lavorazioni', 'lavorazioni/prova'):
            with self.subTest(destinazione=proibita), self.assertRaises(lavorazioni.LavorazioneError) as errore:
                lavorazioni.esporta(self.vault, 'prova', self.vault / proibita)
            self.assertEqual(errore.exception.codice, 'destinazione_non_valida')

    def test_non_copia_collegamenti_simbolici(self):
        segreto = self.vault / 'segreto.txt'
        segreto.write_text('riservato', encoding='utf-8')
        try:
            (self.vault / 'lavorazioni/prova/riferimenti/leak.md').symlink_to(segreto)
        except OSError:
            self.skipTest('collegamenti simbolici non disponibili')
        self.assertNotIn('riferimenti/leak.md', self.elenco(lavorazioni.esporta(self.vault, 'prova', self.fuori)))

    def test_lavorazione_inesistente(self):
        with self.assertRaises(lavorazioni.LavorazioneError):
            lavorazioni.esporta(self.vault, 'non-c-e', self.fuori)

    def test_andata_e_ritorno_dalla_cartella_esportata(self):
        lavorazioni.esporta(self.vault, 'prova', self.fuori)
        copia = lavorazioni.nuova(self.vault, 'copia', 'prova', modelli=self.fuori)
        self.assertEqual(self.elenco(copia), self.elenco(self.fuori / 'prova'))
        self.assertEqual(lavorazioni.valida(self.vault, 'copia'), [])

    def riga(self, *argomenti):
        uscita, errori = io.StringIO(), io.StringIO()
        with redirect_stdout(uscita), redirect_stderr(errori):
            codice = lavorazioni.main(['--vault', str(self.vault), *map(str, argomenti)])
        return codice, uscita.getvalue(), errori.getvalue()

    def test_riga_di_comando_esporta(self):
        codice, uscita, _ = self.riga('esporta', 'prova', self.fuori)
        self.assertEqual(codice, 0)
        self.assertIn(str(self.fuori / 'prova'), uscita)
        self.assertIn('--modelli', uscita)

    def test_importare_da_una_cartella_esterna_avverte_che_sono_istruzioni(self):
        lavorazioni.esporta(self.vault, 'prova', self.fuori)
        codice, uscita, _ = self.riga('nuova', 'importata', '--da', 'prova', '--modelli', self.fuori)
        self.assertEqual(codice, 0)
        self.assertIn('istruzioni', uscita)
        self.assertIn('fasi/02-sintesi/CONTEXT.md', uscita)
        self.assertIn('config.md', uscita)

    def test_da_una_lavorazione_del_vault_non_avverte(self):
        codice, uscita, _ = self.riga('nuova', 'locale', '--da', 'prova')
        self.assertEqual(codice, 0)
        self.assertNotIn('istruzioni', uscita)


class Pannello(Base):
    """Stato di tutte le lavorazioni per la dashboard: sola lettura, limitato e senza seguire collegamenti simbolici."""

    def test_senza_cartella_lavorazioni(self):
        self.assertEqual(lavorazioni.pannello(self.vault), {'presente': False, 'troncato': False, 'lavorazioni': []})

    def test_lavorazione_con_un_esecuzione(self):
        self.crea()
        lavorazioni.avvia(self.vault, 'prova', oggi='2026-10-30')
        voce = lavorazioni.pannello(self.vault)['lavorazioni'][0]
        self.assertEqual((voce['nome'], voce['esecuzione'], voce['problemi']), ('prova', '2026-10-30-1', []))
        self.assertEqual([(f['nome'], f['stato']) for f in voce['fasi']],
                         [('01-raccolta', 'COMPLETA'), ('02-sintesi', 'IN ATTESA'), ('03-revisione', 'IN ATTESA')])
        self.assertEqual(voce['output'], ['lavorazioni/prova/esecuzioni/2026-10-30-1/01-raccolta/raccolta.md'])
        json.dumps(voce)

    def test_fase_da_rifare_porta_i_motivi(self):
        self.crea()
        lavorazioni.avvia(self.vault, 'prova', oggi='2026-10-30')
        (self.vault / 'wiki/Console di rilascio.md').unlink()
        fase = lavorazioni.pannello(self.vault)['lavorazioni'][0]['fasi'][0]
        self.assertEqual(fase['stato'], 'DA RIFARE')
        self.assertIn('rimossa', fase['motivi'][0])

    def test_lavorazione_non_valida_mostra_i_problemi_senza_errori(self):
        self.crea(config=None)
        voce = lavorazioni.pannello(self.vault)['lavorazioni'][0]
        self.assertIn('config_mancante', [q['codice'] for q in voce['problemi']])
        self.assertIsNone(voce['esecuzione'])

    def test_massimo_di_lavorazioni(self):
        for n in range(7):
            self.crea(f'l{n}', fasi=('01-raccolta',))
        risposta = lavorazioni.pannello(self.vault, massimo=5)
        self.assertEqual((len(risposta['lavorazioni']), risposta['troncato']), (5, True))

    def test_testi_lunghi_sono_accorciati(self):
        self.assertEqual((len(lavorazioni._corto('x' * 500)), lavorazioni._corto('x' * 500)[-1]), (300, '…'))
        self.assertEqual(lavorazioni._corto('breve'), 'breve')

    def test_identificatore_enorme_nel_registro_non_rompe_lo_stato(self):
        # Un nome oltre il limite del filesystem farebbe lanciare OSError a is_file(): lo stato, anche da riga di comando, cadrebbe.
        self.crea()
        e = lavorazioni.avvia(self.vault, 'prova', oggi='2026-10-30')
        registro = Path(e['percorso']) / 'esecuzione.json'
        dati = json.loads(registro.read_text(encoding='utf-8'))
        dati['pagine'] = {'p' * 500: 'x', 'q' * 150: 'y'}
        registro.write_text(json.dumps(dati), encoding='utf-8')
        fase = lavorazioni.stato(self.vault, 'prova')['fasi'][0]
        self.assertEqual(fase['stato'], 'DA RIFARE')
        self.assertEqual(len(fase['motivi'][0]) < 300, True)
        self.assertNotIn('p' * 500, ' '.join(fase['motivi']))
        self.assertEqual(lavorazioni.pannello(self.vault)['lavorazioni'][0]['fasi'][0]['stato'], 'DA RIFARE')

    def test_non_segue_una_lavorazione_che_e_un_collegamento_simbolico(self):
        fuori = Path(tempfile.mkdtemp(prefix='teseo-fuori-', dir=self.vault.parent))
        self.addCleanup(shutil.rmtree, fuori, True)
        (fuori / 'fasi/01-raccolta').mkdir(parents=True)
        (fuori / 'CONTEXT.md').write_text('# fuori\n', encoding='utf-8')
        (self.vault / 'lavorazioni').mkdir()
        try:
            (self.vault / 'lavorazioni/esterna').symlink_to(fuori, target_is_directory=True)
        except OSError:
            self.skipTest('collegamenti simbolici non disponibili')
        self.assertEqual(lavorazioni.elenco(self.vault), [])
        self.assertEqual(lavorazioni.pannello(self.vault)['lavorazioni'], [])

    def test_identificatori_ostili_nel_registro_non_fanno_leggere_fuori_da_wiki(self):
        self.crea()
        e = lavorazioni.avvia(self.vault, 'prova', oggi='2026-10-30')
        registro = Path(e['percorso']) / 'esecuzione.json'
        dati = json.loads(registro.read_text(encoding='utf-8'))
        dati['pagine'] = {'../Wiki reference': 'x', '../../fuori': 'y', 'sotto/cartella': 'z', '..': 'w', '': 'v'}
        registro.write_text(json.dumps(dati), encoding='utf-8')
        fase = lavorazioni.stato(self.vault, 'prova')['fasi'][0]
        self.assertEqual((fase['stato'], fase['motivi']), ('COMPLETA', []))


class Riga(Base):
    def esegui(self, *argomenti):
        uscita, errori = io.StringIO(), io.StringIO()
        with redirect_stdout(uscita), redirect_stderr(errori):
            try:
                codice = lavorazioni.main(['--vault', str(self.vault), *map(str, argomenti)])
            except SystemExit as uscita_:
                codice = uscita_.code
        return codice, uscita.getvalue(), errori.getvalue()

    def test_valida_exit_zero_e_uno(self):
        self.crea()
        self.assertEqual(self.esegui('valida', 'prova')[0], 0)
        (self.vault / 'lavorazioni/prova/config.md').unlink()
        codice, testo, _ = self.esegui('valida', 'prova')
        self.assertEqual(codice, 1)
        self.assertIn('config_mancante', testo)

    def test_avvia_stampa_id_e_percorso(self):
        self.crea()
        codice, testo, _ = self.esegui('avvia', 'prova', '--oggi', '2026-10-30', '--param', 'selezione.massimo=1')
        self.assertEqual(codice, 0)
        self.assertIn('2026-10-30-1', testo)
        self.assertIn('1 pagine', testo)

    def test_errori_su_stderr_con_exit_uno(self):
        codice, testo, errori = self.esegui('avvia', 'non-c-e')
        self.assertEqual((codice, testo), (1, ''))
        self.assertIn('lavorazione_inesistente', errori)

    def test_stato_ascii_e_json(self):
        self.crea()
        self.esegui('avvia', 'prova', '--oggi', '2026-10-30')
        self.assertIn('COMPLETA', self.esegui('stato', 'prova')[1])
        dati = json.loads(self.esegui('stato', 'prova', '--json')[1])
        self.assertEqual(dati['fasi'][0]['stato'], 'COMPLETA')

    def test_elenco_json(self):
        self.crea()
        dati = json.loads(self.esegui('elenco', '--json')[1])
        self.assertEqual(dati[0]['nome'], 'prova')

    def test_senza_comando_e_un_errore_d_uso(self):
        self.assertEqual(self.esegui()[0], 2)


if __name__ == '__main__':
    unittest.main()
