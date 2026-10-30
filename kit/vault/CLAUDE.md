# Vault wiki a grafo

- Leggi per primo `Wiki reference.md`: convenzioni, chiavi delle fonti, vocabolario delle relazioni. Prevalgono su tutto il resto.
- Non modificare mai nulla in `raw/`.
- Le lavorazioni (`lavorazioni/`) leggono la wiki e producono documenti derivati: non scrivono mai in `wiki/`; in `raw/` solo `promuovi`, su richiesta e con un file nuovo. Non si pubblicano con l'autosync.
- Le operazioni si fanno con le skill: `obsidian-wiki-ingest`, `obsidian-wiki-query`, `obsidian-wiki-lint`, `obsidian-wiki-fill-gaps`, `obsidian-wiki-lavorazioni`.
- Il contesto «Dal grafo della wiki…» che arriva con ogni domanda indica dove guardare: verifica sempre sulla pagina prima di citare.
- Dopo ogni modifica a frontmatter o link: `python .graph/build_graph.py --check` finché non restano problemi.
- Vault collaborativo (esiste `.graph/teseo_git.py`): `pre` e `post` li eseguono le skill ingest, lint e lacune. Le modifiche fatte a mano fuori da una skill (per esempio in Obsidian) si pubblicano con `python .graph/teseo_git.py post --skill manuale --agente umano`. Non usare `git` direttamente nel vault.
