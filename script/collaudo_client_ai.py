"""Collaudo dei client AI (Claude Code, Codex, Copilot CLI) sul flusso collaborativo: la skill ingest chiama davvero `pre` e `post`?

Per ogni client installato e autenticato crea un vault collaborativo di prova (`installa.py --collabora`), poi ripete `--cicli`
volte: aggiunge una fonte sintetica in `raw/`, lancia il client in modo non interattivo con il prompt «applica la skill
obsidian-wiki-ingest» e controlla nel remoto che sia comparso il commit con i trailer `Teseo-Skill: ingest` e `Teseo-Agent:
<client>`. Se il client non ha pubblicato, lo registra come «post saltato» ed esegue `post` a mano per ripartire pulito.
Scrive un rapporto Markdown con versioni, comandi, esiti e le ultime righe di output di ogni ciclo.

Uso:
  python script/collaudo_client_ai.py --url https://github.com/<utente>/<repo-di-prova>.git --lavoro <cartella-nuova> \\
         [--clienti claude,codex,copilot] [--cicli 3] [--branch collaudo-ai] [--rapporto client-ai.md] [--tieni]

Il repository di prova deve esistere ed essere vostro (meglio privato); ogni client usa un branch nuovo `<branch>-<client>`, che a
fine collaudo si cancella (salvo --tieni). L'autenticazione di Git e dei client è quella già presente sulla macchina: lo script non
legge né salva credenziali. Le righe di output dei client finiscono nel rapporto: rileggerlo prima di condividerlo.
I comandi dei client cambiano tra versioni: ogni comando si sostituisce con `--comando-claude "..."` (e -codex, -copilot) usando
`{prompt}` come segnaposto.
"""
import argparse
from datetime import date
import json
import os
from pathlib import Path
import platform
import re
import shlex
import shutil
import subprocess
import sys
import time

RADICE = Path(__file__).resolve().parents[1]
CLIENTI = ('claude', 'codex', 'copilot')
COMANDI = {  # predefiniti: non interattivi, con i permessi minimi per scrivere file ed eseguire i comandi della skill
    'claude': 'claude -p {prompt} --permission-mode acceptEdits --allowedTools "Bash,Read,Write,Edit,Glob,Grep"',
    'codex': 'codex exec --full-auto {prompt}',
    'copilot': 'copilot -p {prompt} --allow-all-tools',
}
HOOK = {'claude': '.claude/settings.json', 'codex': '.codex/hooks.json', 'copilot': '.github/hooks'}
PROMPT = ('Applica la skill obsidian-wiki-ingest alla fonte raw/{fonte}. Esegui tutti i passaggi della skill, compresi `pre` (passo 0) '
          'e `post` (passo 9) di .graph/teseo_git.py con --agente {client}. Non chiedermi conferme: se un comando esce con codice 2 o 3 '
          'riporta il messaggio e fermati.')
FONTE = ('# Appunti di collaudo {client} {ciclo}\n\nIl progetto Alfa {ciclo} usa il componente Beta{ciclo}. Beta{ciclo} dipende dal servizio '
         'Gamma{ciclo}, che l\'ha introdotto dopo l\'incidente di marzo. Decisione: Beta{ciclo} resta, Gamma{ciclo} si sostituisce entro giugno.\n')


def esegui(argv, cwd=None, timeout=900, env=None):
    try:
        done = subprocess.run(argv, cwd=cwd, capture_output=True, timeout=timeout, env=env)
        return done.returncode, done.stdout.decode('utf-8', 'replace'), done.stderr.decode('utf-8', 'replace')
    except subprocess.TimeoutExpired as error:
        return 124, (error.stdout or b'').decode('utf-8', 'replace'), 'timeout di %d s' % timeout
    except OSError as error:
        return 127, '', str(error)


def coda(testo, righe=12):
    pezzi = [riga for riga in testo.strip().splitlines() if riga.strip()]
    return '\n'.join(pezzi[-righe:])[:1500]


def versione(client):
    codice, out, err = esegui([client, '--version'], timeout=30)
    return (out or err).strip().splitlines()[0] if codice == 0 and (out or err).strip() else 'non rilevata'


def git(vault, *args, timeout=120):
    return esegui(['git', *args], cwd=vault, timeout=timeout)


def trailer_remoti(vault, branch, da):
    """[(sha, skill, agente)] dei commit del branch remoto successivi a `da`, letti dai trailer."""
    git(vault, 'fetch', '-q', 'origin', branch)
    codice, out, _ = git(vault, 'log', f'{da}..origin/{branch}' if da else f'origin/{branch}', '--format=%H%x1f%B%x1e')
    risultato = []
    for blocco in out.split('\x1e'):
        if '\x1f' not in blocco:
            continue
        sha, corpo = blocco.strip().split('\x1f', 1)
        skill = re.search(r'^Teseo-Skill:\s*(\S+)', corpo, re.M)
        agente = re.search(r'^Teseo-Agent:\s*(\S+)', corpo, re.M)
        risultato.append((sha[:10], skill.group(1) if skill else None, agente.group(1) if agente else None))
    return risultato


def prova_client(client, args, lavoro):
    scheda = {'client': client, 'versione': versione(client), 'cicli': [], 'note': []}
    branch = f'{args.branch}-{client}'
    vault = lavoro / client
    comando = getattr(args, 'comando_' + client) or COMANDI[client]
    scheda['comando'] = comando
    codice, out, err = esegui([sys.executable, str(RADICE / 'installa.py'), str(vault), '--client', client, '--skill', 'vault', '--collabora', args.url,
                               '--branch', branch, '--si', '--esempio'], timeout=900)
    if codice != 0:
        scheda['note'].append('installazione non riuscita (codice %d): %s' % (codice, coda(out + err)))
        return scheda
    percorso = vault / HOOK[client]
    scheda['hook'] = 'presenti' if percorso.exists() else 'ASSENTI (%s)' % HOOK[client]
    if percorso.is_file():
        try:
            json.loads(percorso.read_text(encoding='utf-8'))
        except ValueError:
            scheda['hook'] = 'presenti ma JSON non valido'
    for ciclo in range(1, args.cicli + 1):
        fonte = f'collaudo-{client}-{ciclo}.md'
        (vault / 'raw' / fonte).write_text(FONTE.format(client=client, ciclo=ciclo), encoding='utf-8')
        git(vault, 'fetch', '-q', 'origin', branch)
        prima = git(vault, 'rev-parse', f'origin/{branch}')[1].strip()
        argv = [parte.replace('{prompt}', PROMPT.format(fonte=fonte, client=client)) for parte in shlex.split(comando, posix=os.name != 'nt')]
        if os.name == 'nt' and argv:  # i client npm sono .cmd: shutil.which li risolve
            argv[0] = shutil.which(argv[0]) or argv[0]
        inizio = time.monotonic()
        codice, out, err = esegui(argv, cwd=vault, timeout=args.timeout)
        durata = round(time.monotonic() - inizio)
        commit = [item for item in trailer_remoti(vault, branch, prima) if item[1] == 'ingest' and item[2] == client]
        riga = {'ciclo': ciclo, 'codice_client': codice, 'secondi': durata, 'pubblicato_dal_client': bool(commit), 'commit': commit[:1]}
        if not commit:
            codice_post, out_post, err_post = esegui([sys.executable, str(vault / '.graph/teseo_git.py'), 'post', '--skill', 'ingest', '--agente', client],
                                                     cwd=vault, timeout=300)
            riga['post_manuale'] = {'codice': codice_post, 'uscita': coda(out_post + err_post, 4)}
            riga['output_client'] = coda(out + err)
        riga['albero_sporco'] = len([r for r in git(vault, 'status', '--porcelain')[1].splitlines() if r.strip()])
        scheda['cicli'].append(riga)
        print(f'{client} ciclo {ciclo}: client={codice} {durata}s pubblicato={"sì" if commit else "NO"}', flush=True)
    if not args.tieni:
        git(vault, 'push', '-q', 'origin', '--delete', branch)
    return scheda


def rapporto(schede, args):
    righe = [f'# Collaudo dei client AI ({date.today().isoformat()})', '',
             f'- Sistema: {platform.platform()} · Python {platform.python_version()}',
             f'- Cicli per client: {args.cicli} · repository di prova: remoto privato dell\'utente (URL non riportato)', '',
             '| Client | Versione | Hook installati | Cicli | Pubblicati dal client | Post saltato |', '| --- | --- | --- | --- | --- | --- |']
    for scheda in schede:
        pubblicati = sum(1 for c in scheda['cicli'] if c['pubblicato_dal_client'])
        righe.append(f"| {scheda['client']} | {scheda['versione']} | {scheda.get('hook', '—')} | {len(scheda['cicli'])} | {pubblicati} | {len(scheda['cicli']) - pubblicati} |")
    for scheda in schede:
        righe += ['', f"## {scheda['client']}", '', f"Comando: `{scheda['comando']}`" if 'comando' in scheda else '']
        righe += [f'- {nota}' for nota in scheda['note']]
        for c in scheda['cicli']:
            stato = 'pubblicato dal client con i trailer attesi' if c['pubblicato_dal_client'] else 'NON pubblicato dal client'
            righe.append(f"- Ciclo {c['ciclo']}: codice client {c['codice_client']}, {c['secondi']} s, {stato}, file non pubblicati dopo il ciclo: {c['albero_sporco']}")
            if 'post_manuale' in c:
                righe += [f"  - post manuale: codice {c['post_manuale']['codice']}", '  - ultime righe del client:', '    ```', *['    ' + r for r in c['output_client'].splitlines()], '    ```']
    return '\n'.join(righe) + '\n'


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--url', required=True, help='repository di prova (esistente, vostro)')
    parser.add_argument('--lavoro', required=True, type=Path, help='cartella nuova di lavoro')
    parser.add_argument('--clienti', default=','.join(CLIENTI), help='client da provare (predefinito: tutti quelli nel PATH)')
    parser.add_argument('--cicli', type=int, default=3)
    parser.add_argument('--branch', default='collaudo-ai')
    parser.add_argument('--timeout', type=int, default=900, help='secondi massimi per ciclo di un client')
    parser.add_argument('--rapporto', default='client-ai.md')
    parser.add_argument('--tieni', action='store_true', help='non cancellare i branch di prova')
    for client in CLIENTI:
        parser.add_argument(f'--comando-{client}', help=f'comando di {client} con {{prompt}} (predefinito: {COMANDI[client]})')
    args = parser.parse_args(argv)
    if args.lavoro.exists():
        parser.error('--lavoro deve essere una cartella nuova')
    args.lavoro.mkdir(parents=True)
    scelti = [c.strip() for c in args.clienti.split(',') if c.strip()]
    schede = []
    for client in scelti:
        if client not in CLIENTI:
            parser.error('client sconosciuto: ' + client)
        if not shutil.which(client):
            print(f'{client}: non nel PATH, saltato')
            schede.append({'client': client, 'versione': 'non installato', 'cicli': [], 'note': ['eseguibile non trovato nel PATH: non provato']})
            continue
        schede.append(prova_client(client, args, args.lavoro))
    Path(args.rapporto).write_text(rapporto(schede, args), encoding='utf-8')
    provati = [s for s in schede if s['cicli']]
    pieno = bool(provati) and all(c['pubblicato_dal_client'] for s in provati for c in s['cicli'])
    print(f'\nRapporto: {Path(args.rapporto).resolve()} · {"tutti i cicli pubblicati dal client" if pieno else "ci sono cicli non pubblicati o client non provati: vedere il rapporto"}')
    return 0 if provati else 1


if __name__ == '__main__':
    sys.exit(main())
