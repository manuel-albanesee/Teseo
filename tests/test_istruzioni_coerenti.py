"""Le istruzioni duplicate per scelta (file dei client, passo «Sincronizza», elenco delle skill) devono restare identiche.

Ogni client carica il proprio file e l'installatore distribuisce le skill una per una, quindi alcune frasi esistono in più
copie. Chi ne cambia una deve cambiarle tutte: questo test lo ricorda. Non copre il blocco «Client:» né il passo
«Pubblica», che oggi differiscono per ragioni proprie.
"""
import _shortpath  # noqa: F401
from pathlib import Path
import re
import shutil
import tempfile
import unittest

KIT = Path(__file__).resolve().parents[1] / 'kit'
FILE_CLIENT = ('CLAUDE.md', 'AGENTS.md', 'copilot-instructions.md')
REGOLA_COLLABORATIVA = '- Vault collaborativo'
SINCRONIZZA = re.compile(r'^\s*\d+\.\s+(\*\*Sincronizza\.\*\*.*)$')
NOME_SKILL = re.compile(r'obsidian-wiki-[a-z-]+')


def righe(percorso):
    return percorso.read_text(encoding='utf-8').splitlines()


def differenze(kit):
    """Elenco dei punti in cui le copie volute divergono; vuoto se sono coerenti."""
    problemi = []
    skill = {p.name: p for p in sorted((kit / 'skills').iterdir()) if (p / 'SKILL.md').is_file()}

    regole = {}
    for nome in FILE_CLIENT:
        trovate = [r for r in righe(kit / 'vault' / nome) if r.startswith(REGOLA_COLLABORATIVA)]
        if len(trovate) != 1:
            problemi.append(f'{nome}: la regola «{REGOLA_COLLABORATIVA}» compare {len(trovate)} volte (attesa 1)')
        regole[nome] = trovate[0] if trovate else None
    if len(set(regole.values())) > 1:
        problemi.append('regola «Vault collaborativo» diversa fra ' + ', '.join(FILE_CLIENT))

    passi = {}
    for nome, cartella in skill.items():
        trovati = [m[1] for r in righe(cartella / 'SKILL.md') if (m := SINCRONIZZA.match(r))]
        if len(trovati) > 1:
            problemi.append(f'{nome}: il passo «Sincronizza» compare {len(trovati)} volte')
        if trovati:
            passi[nome] = re.sub(r'--skill [\w-]+', '--skill <skill>', trovati[0])
    if len(passi) < 2:
        problemi.append('il passo «Sincronizza» dovrebbe stare in almeno due skill: la guardia non controllerebbe nulla')
    if len(set(passi.values())) > 1:
        problemi.append('passo «Sincronizza» diverso fra ' + ', '.join(sorted(passi)))

    for nome in FILE_CLIENT:
        citate = set(NOME_SKILL.findall((kit / 'vault' / nome).read_text(encoding='utf-8')))
        if citate != set(skill):
            problemi.append(f'{nome}: skill citate {sorted(citate)} diverse da kit/skills {sorted(skill)}')
    return problemi


class Coerenza(unittest.TestCase):
    def test_kit_attuale_e_coerente(self):
        self.assertEqual(differenze(KIT), [])


class Rilevazione(unittest.TestCase):
    """La guardia deve fallire se si tocca una sola copia."""

    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.kit = Path(temp.name) / 'kit'
        for parte in ('vault', 'skills'):
            shutil.copytree(KIT / parte, self.kit / parte)

    def modifica(self, percorso, vecchio, nuovo):
        file = self.kit / percorso
        testo = file.read_text(encoding='utf-8')
        self.assertIn(vecchio, testo)
        file.write_text(testo.replace(vecchio, nuovo, 1), encoding='utf-8')

    def test_copia_integra_non_ha_differenze(self):
        self.assertEqual(differenze(self.kit), [])

    def test_regola_collaborativa_cambiata_in_un_solo_file(self):
        self.modifica('vault/AGENTS.md', 'Non usare `git` direttamente', 'Usa `git` direttamente')
        self.assertEqual([p for p in differenze(self.kit) if 'diversa' in p], ['regola «Vault collaborativo» diversa fra '
                                                                                'CLAUDE.md, AGENTS.md, copilot-instructions.md'])

    def test_regola_collaborativa_duplicata_o_assente(self):
        riga = next(r for r in righe(self.kit / 'vault/CLAUDE.md') if r.startswith(REGOLA_COLLABORATIVA))
        self.modifica('vault/CLAUDE.md', riga, riga + '\n' + riga)
        self.assertTrue(any('CLAUDE.md' in p and '2 volte' in p for p in differenze(self.kit)))
        self.modifica('vault/copilot-instructions.md', REGOLA_COLLABORATIVA, '- Vault condiviso')
        self.assertTrue(any('copilot-instructions.md' in p and '0 volte' in p for p in differenze(self.kit)))

    def test_passo_sincronizza_cambiato_in_una_skill(self):
        self.modifica('skills/obsidian-wiki-lint/SKILL.md', 'Exit 2: **fermati', 'Exit 2: continua e **fermati')
        self.assertTrue(any('Sincronizza' in p and 'lint' in p for p in differenze(self.kit)))

    def test_nome_della_skill_nel_comando_non_conta_come_differenza(self):
        self.modifica('skills/obsidian-wiki-lint/SKILL.md', '--skill lint', '--skill lint-parziale')
        self.assertEqual(differenze(self.kit), [])

    def test_numero_del_passo_non_conta_come_differenza(self):
        self.modifica('skills/obsidian-wiki-ingest/SKILL.md', '0. **Sincronizza.**', '2. **Sincronizza.**')
        self.assertEqual(differenze(self.kit), [])

    def test_skill_senza_sincronizza_non_e_un_errore_ma_troppo_poche_si(self):
        for nome in ('obsidian-wiki-lint', 'obsidian-wiki-fill-gaps'):
            self.modifica(f'skills/{nome}/SKILL.md', '**Sincronizza.**', '**Allinea.**')
        self.assertTrue(any('almeno due skill' in p for p in differenze(self.kit)))

    def test_skill_nuova_non_citata_nei_file_dei_client(self):
        nuova = self.kit / 'skills/obsidian-wiki-lavorazioni'
        nuova.mkdir()
        (nuova / 'SKILL.md').write_text('---\nname: obsidian-wiki-lavorazioni\n---\n', encoding='utf-8')
        problemi = differenze(self.kit)
        self.assertEqual(sum('skill citate' in p for p in problemi), len(FILE_CLIENT))

    def test_skill_rimossa_da_un_solo_file_dei_client(self):
        self.modifica('vault/copilot-instructions.md', '`obsidian-wiki-fill-gaps`', '`obsidian-wiki-lint`')
        problemi = differenze(self.kit)
        self.assertEqual(len(problemi), 1)
        self.assertIn('copilot-instructions.md', problemi[0])


if __name__ == '__main__':
    unittest.main()
