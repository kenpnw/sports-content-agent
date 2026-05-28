# Acknowledgments

As three years of master's study draw to a close, I look back on a path marked by the support of mentors, family, and friends, and offer my sincerest gratitude here.

First, I thank my advisor, Professor [advisor name]. From research direction selection to thesis finalization, my advisor has guided me with rigorous academic discipline and an open intellectual stance. At a critical juncture in choosing the system's initial architecture direction, his methodological guidance to "first build a complete end-to-end system, then optimize specific modules" saved me from the trap of "premature optimization" and helped me balance engineering depth with research value.

I thank all fellow students of Lab [lab name]. In repeated group meetings, the sharp questions raised by labmates — "how do you quantify hallucination?", "why not just use GPT-4?", "why isn't alignment accuracy 100%?" — repeatedly pushed me to refine vague claims into clear engineering metrics. I thank [senior student] for sharing experience on RAG system design and [junior student] for assistance debugging the video processing pipeline.

I thank the broader open-source community and platform providers whose work underlies this thesis: the DeepSeek language model API, NBA Live public API, EasyOCR open-source library, OpenCV vision processing library, and many other foundational technologies. Completing this research in the open ecosystem of AIGC engineering deeply taught me what it means to "stand on the shoulders of giants."

I thank the Paradoox AI team for the high-quality technical questions and equally insightful feedback throughout my interview process. Several engineering decisions in this work — "reviewer roles should not be the same LLM as the writer," "Prompt Contract rather than Prompt Engineering" — were directly inspired by team conversations, helping me rise from "how to write a system that works" to "how to write a system that earns trust."

I thank my parents and family. Over the past three years, they have provided unconditional emotional support and material security, enabling my focus on study. I thank my partner [name] for the understanding and companionship throughout countless late-night debugging sessions, rewrites, and re-rewrites.

Finally, I thank the sport of NBA basketball — and the global community of players, coaches, commentators, and content creators that sustains its culture. It is this love for the sport that has carried me through long engineering debugging sessions with sustained enthusiasm. Each time my system correctly identifies a "Spain PnR" or a step-back three-pointer, the joy comes doubled — engineering, plus the sport itself.

I dedicate this thesis to everyone who pours passion into this sport, on and off the court.

[Author Name]\
[Month] [Year]\
[University City]

\newpage

# Appendix A  Evidence of v15 → v16 Prompt Iteration

This appendix provides concrete evidence supporting the claims in Section 5.5 about the real effect of prompt engineering, enabling reviewers to compare v15 (old prompt) and v16 (new prompt with the "do not force tactical labels" rule + 30+ terminology glossary) outputs on identical input possessions.

## A.1 Turnover Possessions: From "Forced Tactical Label" to "Objective Description"

### Case A.1.1  Q1 6:36 SGA bad pass

**Raw PBP**: `S. Gilgeous-Alexander bad pass TURNOVER (1 TO)`

**v15 output (old prompt, forced "tactic")**:

> This possession belongs to the "passing-error tactic." After SGA dribbles at the top of the arc, he attempts a pass but is intercepted by the defense...

**v16 output (new prompt, objective)**:

> This possession is S. Gilgeous-Alexander's passing error. While dribbling at the top of the arc, he attempted to pass to a cutting teammate, but the passing lane was predicted and intercepted by Lakers defenders, causing a turnover. The cause of the turnover may have been an overly-obvious passing intent or defensive rotation arriving in time.

**Comment**: v15 incorrectly labels a "turnover" as a "tactic," making the commentary appear naive and unprofessional. Under v16's "strict prohibition" rule, it correctly writes "is X's passing error" and reasonably infers the cause.

### Case A.1.2  Q1 5:08 SGA lost ball

**Raw PBP**: `S. Gilgeous-Alexander lost ball TURNOVER (2 TO)`

**v16 output**:

> This possession is S. Gilgeous-Alexander's turnover. While dribbling, he was disturbed by a defender or experienced a self-induced dribbling error and lost the ball — a **personal ball-handling error with no clear tactical pattern**.

**Comment**: v16 explicitly acknowledges "no clear tactical pattern," reflecting the prompt-engineering principle of "rather say less than say wrong."

## A.2 Period-End Possessions: From "Pretentious" to "Factual"

### Case A.2.1  Q1 End

**Raw PBP**: `Period 1 end - clock 00:00.00 - SCORE: OKC 35 LAL 28`

**v15 output (template fill, generic)**:

> Q1 closing moment. This is the team's final possession before entering the next quarter. Specific tactical choice depends on remaining time and score margin.

**v16 output (LLM uses real scores)**:

> Q1 closing moment. OKC leads the Lakers 35-28; the first quarter ends as both teams head into the inter-period break.

**Comment**: v15's template fill, while not strictly hallucinated, is extremely empty. v16's LLM under the new prompt uses actual scores to generate concrete description.

## A.3 Tactical Possessions: From "Generic" to "Professional Terminology"

### Case A.3.1  Q1 10:30 Holmgren assists Dort three

**Raw PBP**: `L. Dort 25' 3PT (3 PTS) (C. Holmgren 1 AST)`

**v16 output**:

> This possession is a "1-5 PnR" tactic. Holmgren rises to set a screen for SGA. After Lakers defenders collapse, SGA passes to Holmgren popping out, who quickly swings the ball to weak-side open Dort, creating a three-point opportunity.

**Comment**: With the newly-added 30+ basketball terminology glossary, v16 can use specialized terms like "1-5 PnR" rather than generic "pick-and-roll combination."

### Case A.3.2  Q1 9:54 Holmgren weak-side cut dunk

**Raw PBP**: `C. Holmgren cutting DUNK (2 PTS) (A. Mitchell 1 AST)`

**v16 output**:

> This possession is a "Weak-side Cutting" tactic. Mitchell holds the ball at the top of the arc drawing defense; Holmgren cuts from the weak side along the baseline to the rim, receiving Mitchell's pass for a dunk. The defense failed to rotate in time, exposing a weakness in awareness of off-ball cuts.

## A.4 v16 Remaining Failure Cases (5/42 unsupported)

As Section 5.5.5 noted, 5 of v16's 42 segments are still judged unsupported by the independent judge. Below are representative failure modes.

### Case A.4.1  Fabricated cross-possession score (contradicts PBP)

**Generated content**:
> This possession is a "Spread PnR" tactic. SGA holds the ball at the top of the arc; J. Williams rises to screen and pops out to the three-point line. After SGA draws double-team and dishes, Williams' first shot is blocked by LaRavia, **but Williams crashes for an offensive rebound and converts the put-back**. The critical three-point make extends the lead to 8 points...

**Judge verdict**: unsupported

**Judge reason**: The commentary claims Williams' second shot made the basket and the margin extended to 8 points, but evidence shows after the three was blocked, Williams **only secured the rebound — no subsequent score or score-change record**.

**Failure mode**: Tempted by narrative flow, the LLM fabricated a "second-chance score" that does not exist in the PBP. This is a textbook "narrative-completion" hallucination.

### Case A.4.2  Wrong player attribution (Ayton wasn't even in the lineup)

**Generated content**:
> This possession is a "Wing PnR" tactic. L. James runs a pick-and-roll with **D. Ayton** on the right wing, drawing defense and dishing to corner Kennard...

**Judge verdict**: unsupported

**Judge reason**: The commentary claims L. James-Ayton PnR followed by assist to Kennard, but evidence shows **the assist is from L. James himself, and there is no record of D. Ayton involvement in any screen, nor is Ayton in this possession's lineup**.

**Failure mode**: The LLM filled in a player name from "general impression" (Ayton is mentally associated with James in many fans' minds), but Ayton in fact did not play in this game. This is a textbook "training-data entity bias."

### Case A.4.3  Mis-attributed turnover

**Generated content**:
> Turnover possession. **J. Williams was stripped by the opponent during dribbling**, causing loss of possession.

**Judge verdict**: unsupported

**Judge reason**: Evidence shows **J. Williams himself lost the ball (lost_ball turnover)**, and separately he also had a steal recorded, but the commentary describes being stripped by opponent — contradicting the evidence.

**Failure mode**: The LLM conflated "active turnover" (lost_ball) with "passive steal" (stolen_by). These are distinct fields in the PBP but the LLM blurred them in narrative.

## A.5 Improvement Paths

These 5 failure cases all point to three concrete improvement directions outlined in Chapter 6's Future Work:

1. **Geometric data extension** (addresses A.4.1-class issues): Extend the Fact Store to include player positions, release angles, defender distances. This gives the Writer factual basis when generating specific action descriptions rather than "narrative completion."
2. **Per-possession lineup validation** (addresses A.4.2-class issues): At the Researcher stage, inject a "10-player on-court whitelist for this possession" into the evidence packet, so Fact Checker can directly reject references to off-lineup players.
3. **PBP field disambiguation** (addresses A.4.3-class issues): Explicitly distinguish `lost_ball` / `bad_pass` / `stolen_by` turnover categories in the prompt, preventing the LLM from conflating them.

\newpage

# Appendix B  Key Code Module Inventory

This appendix lists key module organization of the system implementation. The full code is hosted publicly at https://github.com/kenpnw/sports-content-agent.

| Module Path | Lines | Functionality |
|-------------|-------|---------------|
| `ingestion/nba_live.py` | 800+ | NBA Live API ingestion: schedule, scoreboard, boxscore, PBP endpoint wrappers |
| `ingestion/nba_pbp_fetcher.py` | 300+ | PBP data fetching and normalization |
| `video_scout/video_time_mapper.py` | 700+ | OCR time mapping: ffmpeg frame sampling, EasyOCR calls, piecewise-linear interpolation |
| `video_scout/scoreboard_visibility_detector.py` | 500+ | Scoreboard visibility detection: OpenCV template matching + smoothing |
| `video_scout/auto_roi_detector.py` | 200+ | ROI auto-calibration (POC): Canny + rectangle contours |
| `video_scout/play_segment_detector.py` | 600+ | Play-segment detection and snap, including normalize_event_position |
| `video_scout/possession_boundary_detector.py` | 700+ | PBP possession boundary identification, event → observation normalization |
| `video_scout/tactic_analyzer.py` | 1000+ | 5-Agent protocol runtime, 4-stage LLM calls |
| `video_scout/demo_runner.py` | 2000+ | End-to-end pipeline orchestrator, integrating all modules |
| `video_scout/extract_clip_frames.py` | 100+ | Key-frame extraction |
| `video_scout/clip_overview_poster.py` | 200+ | 60-clip contact-sheet generation |
| `social_packager/repurpose.py` | 600+ | 4-platform social content packaging |
| `evaluation/run_experiment.py` | 400+ | Three-system ablation experiment framework |
| `evaluation/baselines.py` | 300+ | GPT-only and Highlight-only baseline implementations |
| `evaluation/metrics.py` | 500+ | Fact accuracy, hallucination rate, sentence-level trace rate metrics |
| `webapp/app.py` | 400+ | Flask backend providing /api/nba/recent_games etc. endpoints |
| `webapp/job_manager.py` | 300+ | Asynchronous task management |
| `webapp/templates/tactical_review.html` | 1800+ | React + Ant Design review interface |
| `webapp/templates/index.html` | 400+ | Console homepage |

\newpage
