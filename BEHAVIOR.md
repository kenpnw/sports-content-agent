# Sports Content Agent Behavior Spec

## Purpose

This project generates sports content from structured game data and, in later stages, from live or near-real-time sports data feeds.

The system must help transform sports events into platform-ready content packages for Chinese mainstream platforms, starting with Hupu and Douyin.

The long-term goal is:

- ingest multi-sport data
- analyze games and narratives
- generate posts, scripts, and visuals
- publish content safely and consistently


## Product Scope

The system should support:

- NBA first
- later expansion to football, NFL, MLB, and F1
- postgame analysis first
- later expansion to pregame, live updates, and trend-based content

The system should output:

- Hupu-style postgame articles
- Douyin short video scripts
- structured content packages for later publishing


## Core Principles

### 1. Accuracy First

The system must not invent facts about games, players, scores, injuries, standings, or quotes.

Rules:

- only use facts present in trusted input data
- if a fact is missing, omit it instead of guessing
- clearly separate factual statements from interpretation
- never fabricate statistics to make content more dramatic


### 2. Platform Adaptation

The same game should be expressed differently depending on platform.

- Hupu: discussion-oriented, data-aware, basketball-fan tone
- Douyin: short, punchy, visual, hook-first, suitable for voice-over

Platform style must change, but facts must remain consistent across platforms.


### 3. Strong Sports Framing

Content should sound like sports media, not generic AI text.

Preferred characteristics:

- clear game angle
- strong sense of rhythm
- emphasis on turning points
- focus on key players and tactical reasons
- encourage discussion without clickbait lies

Avoid:

- empty hype
- repetitive generic praise
- corporate tone
- vague summaries with no basketball meaning


### 4. Structured Output

Every workflow should produce machine-readable output as well as human-readable output.

Minimum expectation:

- `package.json`
- platform-specific markdown or script file
- workflow summary


### 5. Safe Publishing

The system must be conservative before automatic publishing is enabled.

Rules:

- generated content should be reviewable before publication
- publishing connectors must support retries and failure reporting
- content with uncertain facts should be held for manual review
- sensitive, defamatory, or rumor-based content must never auto-publish


## Input Data Rules

Input data should be normalized before content generation.

For NBA postgame workflows, preferred fields include:

- game id
- date
- venue
- home team and away team
- final score
- team-level stats
- top player performances
- game flow notes
- analysis notes

If normalized data is incomplete:

- continue only if score, teams, and winner are known
- downgrade content richness gracefully
- do not fabricate missing tactical or player details


## Analysis Rules

The analysis layer should identify:

- who won and why
- the most important player performances
- the biggest turning point
- one to three discussion-worthy angles

Analysis should prefer:

- tactical explanation
- efficiency and shot profile implications
- lineup or rotation impact
- late-game execution

Analysis should avoid:

- fake insider language
- pretending to know locker room psychology
- overclaiming causality from weak evidence


## Hupu Content Rules

Hupu output should feel like a well-written postgame discussion thread.

Requirements:

- clear title
- opening summary in one to two sentences
- key player section
- game turning-point section
- discussion prompts for comments

Tone:

- informed
- direct
- discussion-friendly
- not overly formal

Avoid:

- excessive emoji
- fake controversy
- exaggerated certainty


## Douyin Content Rules

Douyin output should feel like a short-form sports recap script.

Requirements:

- strong first-line hook
- four to six short scenes
- voice-over lines that can be spoken naturally
- clear ending with discussion prompt or takeaway

Tone:

- concise
- energetic
- easy to speak aloud
- visually driven

Avoid:

- paragraphs that are too dense for voice-over
- too many numbers in a single sentence
- weak openings


## Visual Content Rules

When visual assets are generated, they should reflect the same story as the text content.

Requirements:

- scoreboard visuals must match the final score
- player cards must use valid player data only
- tactical diagrams must not imply events not supported by the input

If visual confidence is low:

- produce a simpler summary visual instead of a misleading tactical graphic


## Multi-Sport Expansion Rules

The project should remain sport-agnostic at the architecture level.

Rules:

- sport-specific logic belongs in sport-specific modules
- shared workflow orchestration should stay generic
- platform publishing should not depend on one sport
- normalized event models should be reusable across sports where possible


## Publishing Readiness Levels

### Level 1: Offline Generation

- generate local content packages only
- no external posting

### Level 2: Assisted Publishing

- prepare publish-ready payloads
- human confirms before sending

### Level 3: Auto Publishing

- publish automatically only for trusted workflows
- require logging, retries, and moderation gates

The project should stay at Level 1 or Level 2 until data quality and review quality are proven stable.


## Engineering Rules

- prefer simple, testable modules
- keep raw data ingestion separate from content generation
- keep platform formatting separate from sports analysis
- every new workflow should have a sample input fixture
- every generated artifact should be traceable back to its source input


## Definition of Done

A workflow is considered complete only when:

- it accepts a valid normalized input
- it produces stable platform output
- the output is factually consistent with the input
- the output is saved in a structured package
- failure cases are understandable


## Current MVP Direction

The current active scenario is:

- NBA postgame
- Hupu article package
- Douyin short video script package

Future work should extend this path instead of bypassing it.
