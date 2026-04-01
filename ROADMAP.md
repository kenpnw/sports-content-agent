# Sports Content Agent Roadmap

## Vision

Build a multi-sport content automation system that can:

- ingest trusted sports data
- detect storyworthy moments
- generate platform-native content
- create visuals and media packages
- publish safely to mainstream platforms


## Current Stage

The project is currently in MVP stage.

Current working scenario:

- NBA postgame
- local JSON input
- Hupu article package output
- Douyin short video script output


## Phase 1: Stable NBA Postgame MVP

Goal:

- make one realistic workflow stable and repeatable

Scope:

- normalized NBA postgame data model
- CLI workflow
- Hupu content package generation
- Douyin script package generation
- sample fixtures
- local artifact output

Exit criteria:

- same input always produces stable output structure
- output is readable and factually aligned
- failure modes are clear


## Phase 2: Real NBA Data Ingestion

Goal:

- stop relying on manual sample JSON

Scope:

- connect one trusted NBA data source
- build ingestion adapter
- normalize raw game data into internal schema
- generate postgame package from real completed games

Exit criteria:

- system can fetch at least one finished game automatically
- normalized data can drive the existing workflow without manual edits


## Phase 3: AI-Enhanced Analysis Layer

Goal:

- improve content quality without weakening factual safety

Scope:

- LLM-assisted angle selection
- tactical summary generation
- platform-specific phrasing refinement
- fallback template mode when LLM is unavailable

Exit criteria:

- output quality improves over template-only mode
- facts remain source-grounded
- LLM failures do not break the workflow


## Phase 4: Visual Asset Generation

Goal:

- add reusable visual content for postgame packages

Scope:

- scoreboard card
- player stat card
- standings or context card
- Douyin cover draft

Exit criteria:

- visuals are consistent with text output
- image generation works from normalized data


## Phase 5: Assisted Publishing

Goal:

- prepare content for real platform operations

Scope:

- publisher interface
- Hupu payload formatter
- Douyin publishing payload formatter
- review step before send
- publish logs and status tracking

Exit criteria:

- generated packages can be reviewed and approved quickly
- failed publish attempts are traceable


## Phase 6: Automated Scheduling

Goal:

- run workflows automatically after games finish

Scope:

- scheduler
- polling or webhook triggers
- retry jobs
- content queue

Exit criteria:

- the system can detect completed games and create content packages without manual launch


## Phase 7: Multi-Sport Expansion

Goal:

- prove the architecture is reusable

Suggested order:

- football
- F1
- NFL
- MLB

Scope:

- sport-specific ingestion adapters
- sport-specific analysis modules
- reuse platform packaging layer

Exit criteria:

- at least one non-NBA workflow ships without major architectural rewrites


## Technical Priorities

### Highest Priority

- data ingestion from a real NBA source
- stable normalized schemas
- template and AI hybrid content generation
- artifact packaging

### Medium Priority

- visuals
- publishing interfaces
- moderation and review gates

### Later Priority

- full automation
- analytics feedback loops
- engagement optimization


## Risks

- unreliable third-party sports data
- overly broad sport abstraction too early
- AI-generated wording drifting from facts
- platform publishing restrictions and rate limits


## Near-Term Next Steps

- add one real NBA data adapter
- define a raw-to-normalized conversion layer
- add tests for normalized postgame fixtures
- add optional AI rewrite mode on top of template output
- prepare a scoreboard visual generator
