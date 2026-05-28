# Chapter 3  System Design

This chapter presents the overall architecture of the **Multi-Modal Multi-Agent NBA Tactical Content Generation System** proposed in this thesis. Section 3.1 gives the four-layer architectural overview. Section 3.2 describes the data layer with multi-modal time alignment. Section 3.3 covers the dual-layer knowledge architecture. Section 3.4 details the 5-Agent supervision protocol. Section 3.5 formalizes the Prompt Contract. Section 3.6 describes the visual provenance mechanism. Section 3.7 covers the output layer with multi-platform stylization.

## 3.1 Overall Architecture

The system adopts a four-layer architecture: **Data Layer → Knowledge Layer → Agent Layer → Output Layer**. Layers communicate through explicit interface contracts; each layer's implementation can be independently replaced. The overall architecture is shown in Figure 3-1.

![Figure 3-1.  Overall system architecture. The Data Layer ingests NBA Live API feeds, full-game video, the tactical glossary, and player history. The Knowledge Layer separates structured Fact Store from narrative Text RAG. The Agent Layer contains five roles under a unified Prompt Contract. The Output Layer fans out to four social platforms and a tactical GIF collection.](../../thesis_figures/out/fig01_system_architecture.png)

The four-layer design follows these principles:

- **Data Layer.** Ingests raw external data: NBA Live API for play-by-play, local full-game video files, an embedded basketball glossary (30+ Chinese-English term pairs), and player history metadata. Auxiliary submodules — OCR time mapping and scoreboard visibility detection — provide upstream layers with a "play / non-play" binary signal and a "video-seconds ↔ game-clock" mapping function.
- **Knowledge Layer.** Organizes raw data into two knowledge carriers efficient for agent retrieval: the structured Fact Store (SQLite) and the narrative Text RAG (vector index). Different query interfaces serve different access patterns; routing policy decides which layer a given assertion should consult first.
- **Agent Layer.** Five roles (Selector, Researcher, Writer, Fact Checker, Risk Guard) advance the workflow in pipeline fashion. Each role's inputs, outputs, accessible tools, and accessible knowledge sources are explicitly constrained by the Prompt Contract.
- **Output Layer.** Packages the Agent Layer's final content into differentiated payloads for four target platforms (Hupu, Douyin, Weibo, Xiaohongshu) and a collection of 60 tactical GIFs.

### 3.1.1 Design Principles

Five core principles guide the architecture:

1. **Separation of concerns.** Each layer and each role focuses on its own sub-task; cross-layer and cross-role coupling occurs only through explicit interface contracts. This preserves maintainability and extensibility.
2. **Provenance awareness.** From Data Layer through Output Layer, every piece of generated content must trace back to a concrete original source. Records in Fact Store have unique IDs; Text RAG chunks have chunk_ids; Writer-generated segments must list the IDs used in the `evidence` field.
3. **Hard supervision over soft suggestions.** Reviewer roles (Fact Checker, Risk Guard) hold blocking authority over downstream consumers. Verification failures must be corrected or removed; no "passed despite issues" path exists.
4. **Domain awareness.** All prompts explicitly inject basketball domain knowledge — glossaries, canonical tactic names, negative rules. This distinguishes the system from generic conversational LLM applications.
5. **Human-in-the-loop.** The system does not pursue full replacement of human editors; the final pre-publication step is a "web review interface" for editorial selection and final approval. AI handles "evidence gathering, layout, draft writing"; humans handle "judgment and signing off."

### 3.1.2 End-to-End Pipeline Sequence

A complete end-to-end run comprises:

1. **Trigger.** A user selects a completed NBA game in the web console (via a game picker over the last 30 days), or a scheduler auto-triggers after a game ends.
2. **PBP ingestion.** The NBA Live API is called with the game_id to retrieve the full PBP feed (~500–700 events).
3. **Observation construction.** A rule engine filters from the PBP about 60 "high-content-value possessions," outputting 60 observations each carrying possession_id, time code, event description, participating players, and an initial tactical tag.
4. **Multi-modal alignment.** OCR time mapping and scoreboard visibility detection map each observation's time code to its true video-second, snapping observations falling on non-play segments to the nearest play segment.
5. **Clip extraction.** ffmpeg cuts 60 video clips of 8–12 seconds each at the aligned time windows.
6. **Agent orchestration.** The 5-role pipeline advances: Selector reviews the 60 observations; Researcher fetches evidence from Fact Store + Text RAG for each; Writer drafts tactical commentary; Fact Checker verifies each claim; Risk Guard scans for risk; the final report contains 60 fully populated key_segments.
7. **Multi-platform packaging.** The `social_packager` module synthesizes a `package.json` + Markdown draft for Hupu, Douyin, Weibo, and Xiaohongshu, drawing on key_segments and GIF assets.
8. **Web review.** The user inspects 60 possessions in `tactical_review.html` — GIFs, tactical commentary, quality scores — and one-click-exports a Hupu post draft.

End-to-end execution on OKC vs. LAL G1 (~2.5-hour full-game video) takes about 80–90 minutes, with video processing dominating (60–70 min), LLM calls taking 5–10 min, and remaining modules (PBP ingestion, social packaging, web rendering) accounting for the remainder.

## 3.2 Data Layer and Multi-Modal Time Alignment

The Data Layer ingests raw multi-modal data from external sources and normalizes it for upstream consumption. This section focuses on its most technically challenging submodule: multi-modal time alignment.

### 3.2.1 The Distinctive Difficulty of Sports Video Alignment

Alignment between NBA full-game video and PBP data appears straightforward but in fact involves two core difficulties:

- **Non-linear relationship between game clock and video clock.** In theory, N seconds of game time corresponds to N seconds of video advance. In practice, replays, slow motion, close-ups, commercials, and timeouts insert "non-play frames" at high frequency. Our statistics show about 40% of a standard NBA full-game broadcast is non-play frames.
- **Discontinuities at period ends, halftime, and timeouts.** Multi-minute pauses at the inter-period boundaries (Q1–Q2, halftime Q2–Q3, Q3–Q4) plus frequent in-period timeouts (up to 7 per period) make the "game-clock to video-clock" mapping severely discontinuous.

The traditional linear-mapping approach (each period gets equal video time) may pass within a single period but inevitably fails across periods.

### 3.2.2 A Three-Step Alignment Scheme

This thesis proposes a three-step "OCR time mapping + scoreboard visibility detection + play-segment snap" scheme. Its core idea is depicted in Figure 3-2.

![Figure 3-2.  Multi-modal time alignment pipeline (OKC vs LAL G1 Q1 excerpt). The top row shows PBP events on game-clock spacing; the middle row shows the same events on video-clock, stretched by interleaved replays and ads; the bottom row shows the OCR-detected scoreboard visibility curve. When a PBP event lands on a non-play segment, the clip window snaps to the nearest play segment.](../../thesis_figures/out/fig05_multimodal_alignment.png)

Concretely:

**Step 1: OCR time mapping.** One frame per second is extracted from the video (via an ffmpeg pipeline using `-vf fps=1`, far faster than seek-based extraction). OCR (EasyOCR) is performed on a pre-calibrated scoreboard ROI to extract a "period (1–4) + remaining game clock (MM:SS)" triple. On OKC vs LAL G1 — a 2.5-hour (~9000-second) video — this yielded about 95 valid OCR samples; the remainder corresponded to moments where the scoreboard was hidden or occluded. From these 95 (video_seconds, period, clock_remaining) triples, we construct per-period piecewise-linear interpolation for the "video-seconds ↔ game-clock-remaining" mapping (one map per period, Q1–Q4).

**Step 2: Scoreboard visibility detection.** Using OpenCV template matching, for each per-second sampled frame, we compare the current scoreboard ROI against 12 reference templates (three from each of the four periods) via normalized cross-correlation (`cv2.matchTemplate`, `TM_CCOEFF_NORMED`), taking the maximum similarity. If the score exceeds 0.65, the second is marked "play"; otherwise "non-play" (replay, slow motion, commercial). On OKC vs LAL G1, about 5400 of 9000 seconds (60%) are marked play, matching the expected ~40% non-play prior. The output is persisted as `play_segments.json` and `non_play_segments.json`.

**Step 3: Play-segment snap.** Each observation's expected video time (from Step 1) is checked against the play segments (Step 2):

- If it falls inside a play segment, that time is used as the clip center;
- If it falls inside a non-play segment (typical replay length: 4–8 seconds), the system searches outward for the nearest play segment and snaps the clip window to it;
- If the observation is in the very late period (clock < 15 seconds) and no OCR sample covers it, the snap is skipped, the best-effort linear extrapolation is used, and the clip is marked `extrapolated` for downstream filtering.

The snap operation uses "event-position normalization": the PBP event is set to appear at the 78% position of the clip (empirically the most natural narrative beat), with 8 seconds of lead-in and 2 seconds of follow-out, total length 10 seconds. This normalization gives all clips consistent pacing.

### 3.2.3 Generalization Challenge and Future Work

The biggest limitation of this scheme is that scoreboard ROI must be manually calibrated per video — different broadcasters (ESPN, TNT, ABC, Tencent) place the scoreboard differently, requiring 5–10 minutes of manual calibration per game. We implemented an `auto_roi_detector` module as a proof-of-concept (based on Canny edges + rectangle contours) that finds candidate ROIs within the approximate region, but precision is not yet production-ready. This is an explicit limitation; Chapter 6 discusses possible improvements using vision-LLM-based ROI prompting.

## 3.3 Dual-Layer Knowledge Architecture

### 3.3.1 Motivation

As Section 2.2.3 noted, traditional single-vector-store RAG has a natural ceiling on numeric queries. Sports content is extremely number-dense — a single typical sentence "the Lakers cut a 19-point first-three-quarter deficit to just 8 points in the fourth" contains three independent numbers (19, 3, 8) plus an implicit relation (19 − 8 = an 11-point comeback), and any single number being wrong falsifies the entire sentence. The Dual-Layer Knowledge Architecture proposed here separates numeric knowledge from narrative knowledge, letting the former pass through precision queries that guarantee numeric correctness.

### 3.3.2 Fact Store Design

The Fact Store is a SQLite-backed relational database carrying five categories of structured facts:

- **Game metadata** (`games` table): game_id, date, home/away teams, final score, venue, summary statistics.
- **Player performance** (`player_stats` table): per-game per-player full stat line (~30 fields including points, rebounds, assists, steals, blocks, threes made, shooting percentages).
- **Team performance** (`team_stats` table): per-game team-level stats (shooting percentages, three-point percentages, free-throw percentages, rebounds, assists, turnovers).
- **Possession events** (`possessions` table): possession-grained data derived from PBP, including possession_id, start/end times, offensive team, defensive team, players involved, scoring result.
- **Player profiles** (`player_profiles` table): basic information, current-season stats, career data, position, height, weight.

The Fact Store supports native SQL queries, invoked by the Researcher role when numeric evidence is needed. Queries are wrapped behind high-level functions (e.g., "fetch all stats for player X in game Y," "fetch X team's last-5-game record against Y"), so the Researcher does not write raw SQL.

### 3.3.3 Text RAG Design

The Text RAG uses SQLite FTS5 (Full-Text Search v5) extension for full-text retrieval over four narrative-text categories:

- **Post-game commentary articles**: snippets scraped from mainstream sports outlets (Hupu, Sina Sports, ESPN China);
- **Interview snippets**: key quotes from post-game player and coach interviews;
- **Injury reports**: team-official injury updates;
- **Historical analysis**: background material on players' or tactical patterns' history.

Each text is chunked into 300–500-character pieces and indexed. Queries support keyword search with BM25 ranking. We chose FTS5 over vector indices for two reasons: (1) with appropriate Chinese segmentation (e.g., jieba), FTS5 achieves adequate retrieval quality for our use case; (2) FTS5 deployment cost is minimal — a single SQLite file with no extra service to run.

### 3.3.4 Routing Policy

The Researcher role retrieves evidence for each observation following this routing policy:

- If the observation's `tactic_tags` include numeric labels (`three_point_made`, `fast_break`, `turnover`), first query the Fact Store for the precise possession data;
- If the possession involves "player background" (e.g., "this is SGA's Nth three-point attempt tonight"), first aggregate in Fact Store, then supplement narrative context from Text RAG;
- If the possession involves "tactic-name inference" (e.g., "is this a Spain PnR?"), skip Fact Store and query Text RAG for prior knowledge descriptions only;
- Results are wrapped in a single `evidence_packet` containing `fact_records` (structured) and `text_chunks` (unstructured).

### 3.3.5 Design Trade-offs

Splitting knowledge into two layers imposes two engineering trade-offs:

- **Pros**: numeric precision rises sharply; latency for different query types is controlled (SQL queries ~ms-scale, FTS5 retrieval ~100ms); knowledge updates can be handled separately (Fact Store updates in batch at game end; Text RAG updates on media-crawl cadence).
- **Cons**: routing policy needs manual maintenance; edge cases exist where a query routed to Text RAG should have gone to Fact Store; running two stores adds operations cost.

In practice, routing-policy maintenance averages 1–2 hours/week; edge cases are caught by Fact Checker's post-hoc verification; operations cost is negligible because both stores are SQLite files (no separate service required).

## 3.4 5-Agent Supervision Protocol

### 3.4.1 Protocol Overview

The protocol comprises five roles: Selector, Researcher, Writer, Fact Checker, and Risk Guard. Each role corresponds to one or more independent LLM calls with distinct system prompts, tool access, and knowledge-source access. The roles exchange structured messages along a pipeline, as shown in Figure 3-3.

![Figure 3-3.  5-Agent supervision protocol sequence diagram. Selector → Researcher → Writer flow forward; Fact Checker reviews Writer output, with rejection triggering a Writer revise loop (up to two iterations); Risk Guard performs final risk audit before publication, removing segments as needed.](../../thesis_figures/out/fig06_agent_sequence.png)

### 3.4.2 Per-Role Responsibilities

**Selector (selection agent).** Input: the 60 candidate observations. Output: the final accepted list (default: pass all 60; optionally filter by quality score, possession-type diversity rules). Selector's system prompt frames the role as "a sports content editor selecting the highest-value possessions from a given set," and is forbidden to consult any external knowledge — judgment is based solely on observation fields.

**Researcher (evidence agent).** Input: a Selector-passed observation. Output: an `evidence_packet` for that observation. Researcher holds permissions to call Fact Store and Text RAG and follows the routing policy of Section 3.3.4.

**Writer (writing agent).** Input: Researcher's `evidence_packet` plus observation metadata. Output: a tactical-commentary triple — `observation` (factual description, ~30 chars), `decision_analysis` (tactical analysis, 100–200 chars), `win_loss_impact` (impact on game outcome, 30–50 chars). Writer's system prompt injects the 30+ basketball glossary plus negative rules (see Section 4.5) and mandates an `evidence_id` field on every sentence.

**Fact Checker (verification agent).** Runs independently of Writer. Input: Writer's commentary triple plus the possession's evidence_packet. For each concrete claim in `decision_analysis`, Fact Checker verifies factual support. A pass routes downstream; a reject triggers a Writer revise loop (max two iterations; segments exceeding this are downgraded to "factual description only").

**Risk Guard (risk-audit agent).** Operates on Fact-Checker-passed content. Checks for business-sensitive issues: (a) personality-attack-style negative judgments of players or coaches; (b) inflammatory commentary on disputed officiating calls; (c) language touching on race, gender, or other sensitive topics. When detected, the segment is flagged or removed.

### 3.4.3 Key Differences from Multi-Agent Debate

The protocol differs from Multi-Agent Debate at three levels:

- **Pipeline, not debate.** Roles are not "representatives of different views on the same question" but distinct workstations in a production line.
- **Reviewer roles have blocking authority, not advisory authority.** Rejection signals from Fact Checker and Risk Guard cause substantive correction or removal, not optional suggestions to be considered.
- **Role boundaries are declared explicitly in prompts.** Each role's prompt explicitly states "what you may not do," preventing role overreach (e.g., Researcher shall not write tactical commentary; Writer shall not self-evaluate factual correctness).

## 3.5 Prompt Contract

### 3.5.1 Formal Definition

Each LLM call is modeled as a "prompt contract" with six fields (Figure 3-4):

![Figure 3-4.  The Prompt Contract six-field schema. Each LLM invocation must produce a payload satisfying all six fields; a schema gate validates the request before the LLM is called, and Fact Checker / Risk Guard re-check the output afterward.](../../thesis_figures/out/fig02_prompt_contract.png)

Field specifications:

- **`task`**: the task this call is to perform, as a verb-first single-sentence statement. Example: `"Generate tactical commentary for possession poss_p1_e20"`.
- **`source_scope`**: the whitelist of evidence sources for this call. Example: `["pbp_event:poss_p1_e20", "fact_store:player_stats[L.James]", "text_rag:chunk_12"]`. References outside this scope are considered out-of-bounds.
- **`evidence_requirements`**: per-claim evidence-binding rules. Example: `{"each_assertion": "must_attach_evidence_id", "unsupported_assertion": "reject_output"}`.
- **`forbidden_behaviors`**: a list of hard-block negative rules. Example: `["no fabricated player names", "no inflammatory referee commentary", "no forcing tactical labels on transition fast breaks"]`.
- **`output_contract`**: strict output shape (JSON schema). Example: `{"key_segments": [{"observation": str, "decision_analysis": str, "evidence": list[str]}]}`. Parse failure triggers regeneration.
- **`review_gate`**: downstream reviewer roles that may block or amend this output. Example: `["fact_checker", "risk_guard"]`.

### 3.5.2 Role in the Protocol

Each role's invocation has its prompt contract automatically constructed by the runtime, with two-time validation:

- **Pre-call**: the runtime validates the request itself (e.g., whether the source_scope is within the role's permissions);
- **Post-call**: the runtime compares the LLM output against `output_contract`; mismatch triggers regeneration; the output is sent to each role in `review_gate` for re-checking.

This mechanism shifts "prompt as empirical craft" toward "prompt as verifiable contract" — any contract violation is structurally caught at runtime rather than depending on manual review.

## 3.6 Visual Provenance

### 3.6.1 Motivation

As Section 1.1.2 noted, the rapid expansion of AIGC content in public information space introduces a new problem of "invisible credibility." This thesis raises "trustworthiness" from an engineering metric to a product feature, using sentence-level visual annotation so readers can directly assess each sentence's credibility while reading.

### 3.6.2 Three-State Annotation

Each generated segment's `decision_analysis` field is split into sentences, each annotated with one of three states:

- **Verified**: every concrete fact in the sentence (player names, scores, action types, time codes) is found in `evidence_packet`;
- **Partial**: main facts are correct but some details (specific feet, whether a cut occurred) cannot be verified;
- **Unsupported**: the sentence contains concrete facts not in `evidence_packet` or in clear contradiction — sentences in this state are rejected by Fact Checker and should not appear in final output (but are flagged in occasional missed cases).

### 3.6.3 Frontend Rendering

In the `tactical_review.html` web review interface, verified sentences are rendered with a green border, partial with yellow, unsupported with red; hovering reveals the linked `evidence_id` and original fact record. Readers can directly assess each segment's "trustworthiness composition" and decide whether to manually remove or revise individual segments before publication.

## 3.7 Output Layer and Multi-Platform Stylization

### 3.7.1 Platform-Difference Analysis

We summarize the stylistic differences across the four target platforms as follows:

- **Hupu**: prefers tactical depth and statistical detail; readers are mostly experienced fans tolerant of longer prose and dense terminology. Ideal format: a three-section "Observation → Decision → Impact" tactical analysis paired with GIF cutaway.
- **Douyin**: prefers fast pacing and conflict points; length 30–60 seconds, text serves as subtitle. Ideal format: "3-second hook + main story + close."
- **Weibo**: prefers short and quotable lines, ≤140 characters. Ideal format: "one core insight + one image + a few hashtags."
- **Xiaohongshu**: prefers image-rich, lifestyle-flavored narration; visual aesthetics matter. Ideal format: "cover image + 5–8 photos + short caption text."

### 3.7.2 The social_packager Module

The `social_packager` module takes `key_segments` and GIF files as input and generates a `package.json` + Markdown draft for each of the four platforms:

- Hupu package: retains all 60 segments' three-section triples, time-ordered, accompanied by 60 GIF links;
- Douyin package: picks 3–5 highest-conflict possessions from the 60 segments and combines them into a short-video script;
- Weibo package: picks one "most-quotable" sentence as the headline plus a companion image;
- Xiaohongshu package: picks 6–8 visually striking possessions, extracts key frames, and accompanies them with soft-style narration.

Each platform's selection strategy is encapsulated as configurable `selection_rules`, easy to adjust per business need.

## 3.8 Chapter Summary

This chapter has presented the four-layer architectural overview and the six core sub-module designs: multi-modal alignment, dual-layer knowledge, 5-agent protocol, prompt contract, visual provenance, and multi-platform output. The next chapter presents the concrete technical implementations.

\newpage
