# Vault wiki a grafo

- Leggi per primo `Wiki reference.md`: convenzioni, chiavi delle fonti, vocabolario delle relazioni. Prevalgono su tutto il resto.
- Non modificare mai nulla in `raw/`.
- Le operazioni si fanno con le skill: `obsidian-wiki-ingest`, `obsidian-wiki-query`, `obsidian-wiki-lint`, `obsidian-wiki-fill-gaps`.
- Il contesto «Dal grafo della wiki…» che arriva con ogni domanda indica dove guardare: verifica sempre sulla pagina prima di citare.
- Dopo ogni modifica a frontmatter o link: `python .graph/build_graph.py --check` finché non restano problemi.
