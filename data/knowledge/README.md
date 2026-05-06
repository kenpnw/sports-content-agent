# Text RAG Documents

This folder is for text documents that should be searchable by the local Text RAG layer.

Recommended inputs:

- official game recap markdown
- postgame interview notes
- injury updates
- team press releases
- verified media reports

Recommended file format:

- `.md`
- `.txt`

Recommended frontmatter-like fields in the first lines when available:

- `sport: NBA`
- `league: NBA`
- `source_type: official_recap`
- `published_at: 2026-04-01`
- `teams: LAL,WAS`
- `uri: https://...`

If these fields are absent, the Text RAG store will still ingest the file, but the metadata quality will be lower.
