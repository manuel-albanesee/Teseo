"""Autori delle note dalla storia Git: la persona è l'autore del commit, agente e skill vengono dai trailer Teseo-*."""
import re
from pathlib import Path

from .contracts import ContractError
from .git_sync import _invoke

MAX_COMMITS = 10000
_CONTROL = re.compile(r'[\x00-\x1f\x7f]')
_AGENT = re.compile(r'^Teseo-Agent:[ \t]*([a-z][a-z0-9-]{0,31})[ \t]*$', re.M)


def _git(root, args):
    result = _invoke(root, args, check=False)
    return result.stdout.decode('utf-8', 'replace') if not result.returncode else None


def history_head(root):
    """OID di HEAD se root è un repository con almeno un commit, altrimenti None (copie isolate, vault senza Git)."""
    root = Path(root)
    if not (root / '.git').exists():
        return None
    try:
        out = _git(root, ['rev-parse', '--verify', '-q', 'HEAD'])
    except ContractError:
        return None
    out = (out or '').strip()
    return out if re.fullmatch(r'[0-9a-f]{40}|[0-9a-f]{64}', out) else None


def _name(value):
    return _CONTROL.sub('', value).strip()[:256] or None


def collect(root, pages):
    """[(entity_id, creato_da, creato_il, modificato_da, modificato_il, agente, modifiche)] per le pagine in `pages`.

    Una sola `git log --no-merges -M --name-status` su wiki/. I commit di merge (anche quelli `Teseo <teseo@localhost>`)
    non contano. Le rinomine si seguono all'indietro dal commit più recente: il nome finale è quello attuale della
    pagina. Con oltre MAX_COMMITS commit la data di creazione delle pagine più vecchie è la prima nota nella finestra.
    Senza repository, senza commit o con Git indisponibile la lista è vuota.
    """
    if history_head(root) is None:
        return []
    try:
        out = _git(Path(root), ['log', '--no-merges', '-M', '--name-status', '--max-count=%d' % MAX_COMMITS,
                                '--format=%x1e%H%x1f%an%x1f%aI%x1f%B%x1f', '--', 'wiki/'])
    except ContractError:
        return []
    if out is None:
        return []
    final_of, info = {}, {}
    for record in out.split('\x1e')[1:]:
        _, name, date, body, changes = (record.split('\x1f') + [''] * 5)[:5]
        agent = _AGENT.search(body)
        for line in changes.strip().splitlines():
            columns = line.split('\t')
            status, paths = columns[0][:1], columns[1:]
            if not status or not paths:
                continue
            if status in 'RC' and len(paths) == 2:
                final = final_of.get(paths[1], paths[1])
                final_of[paths[0]] = final
            elif status == 'D':
                continue
            else:
                final = final_of.get(paths[0], paths[0])
            page = final[5:-3] if final.startswith('wiki/') and final.endswith('.md') and final.count('/') == 1 else None
            if page not in pages:
                continue
            item = info.get(page)
            if item is None:
                item = info[page] = dict(modificato_da=_name(name), modificato_il=date, agente=agent.group(1) if agent else None,
                                         modifiche=0, closed=False)
            if item['closed']:
                continue
            item.update(creato_da=_name(name), creato_il=date, modifiche=item['modifiche'] + 1, closed=status == 'A')
    return sorted((page, item['creato_da'], item['creato_il'], item['modificato_da'], item['modificato_il'],
                   item['agente'], item['modifiche']) for page, item in info.items())
