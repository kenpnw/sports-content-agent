# RAG Reference Standard

This project uses a dual-layer knowledge architecture:

- `Fact Store`: structured truth for scores, stats, form, and head-to-head history
- `Text RAG`: narrative context for recaps, interviews, injury notes, and verified reports

## Source Priority

Use sources in this order:

1. `official_stats`
2. `league_api`
3. `official_recap`
4. `team_release`
5. `verified_media`
6. `internal_archive`

## Routing Rule

- Structured numbers must come from the Fact Store.
- Narrative context may come from Text RAG.
- If a statement contains both hard facts and narrative framing, the hard facts still need Fact Store evidence.

## Mandatory Metadata

Every text document should carry:

- `sport`
- `league`
- `source_type`
- `published_at`
- `uri`
- `teams`

## Freshness Rule

- `postgame`: within 3 days
- `injury`: within 7 days
- `season_feature`: within 30 days

## Chunking Rule

- target chunk size: around 900 chars
- overlap: around 120 chars
- cap per document: 12 chunks

## Citation Rule

- Every generated claim should be traceable to source metadata.
- Fact-backed claims should expose the exact field used.
- Text-backed claims should expose title, source type, publish date, and uri when available.
