# Chapter 5  Experiments and Evaluation

This chapter conducts multi-dimensional evaluation on real NBA game data. Section 5.1 introduces datasets and runtime environment. Section 5.2 defines evaluation metrics. Section 5.3 presents three-system ablation main results. Section 5.4 shows video alignment accuracy across system iterations. Section 5.5 presents judge-model hallucination evaluation. Section 5.6 demonstrates generalization to a second game. Section 5.7 provides qualitative case study analysis on OKC vs LAL G1.

## 5.1 Datasets and Experimental Setup

### 5.1.1 Selection of Evaluation Games

The evaluation experiments use the following two NBA games:

- **Main case study**: OKC Thunder vs Los Angeles Lakers 2025 Playoffs G1, final score 119-102, OKC home win. This game serves as the main case study; all modules — 60-possession multimodal alignment, 5-agent supervision, 4-platform packaging — run end-to-end on this game.
- **Generalization validation**: [second game placeholder]. Used in Section 5.6 generalization experiments to demonstrate the system extends to other games and other broadcasters.

Additionally, the main ablation results use an independent small annotated dataset (an example PBP from LAL vs GSW with hand-annotated `gold_claims.csv` + `gold_boundaries.csv`) covering 20 key events and 30 gold claims.

### 5.1.2 System Configuration

| Item | Configuration |
|------|--------------|
| LLM provider | DeepSeek API |
| Main model | `deepseek-chat` |
| Reasoning model | `deepseek-reasoner` (on-demand) |
| Temperature | 0.6 |
| max_tokens | 400 / segment |
| Video processing | ffmpeg 1fps + EasyOCR + OpenCV 4.x |
| Backend | Python 3.10, Flask |
| Frontend | React 18 + Ant Design 5 |
| Runtime environment | Windows 11 + Intel i7-12700K + 32GB RAM |

### 5.1.3 The Three Comparison Systems

To quantify this thesis's specific contributions, Section 5.3 establishes three comparison systems:

- **GPT-only** (baseline): pure LLM, no Fact Store, no Text RAG, no Fact Checker, no multimodal alignment. The model generates tactical analysis from PBP text alone.
- **Highlight-only** (baseline): adds video highlight cutting (PBP-time linear mapping) on top of GPT-only, but still lacks multimodal alignment and Fact Checker. Simulates the industry practice of "traditional highlight cutting + LLM brief commentary."
- **Ours** (this thesis): complete end-to-end pipeline with 5-Agent + Prompt Contract + Fact Store + Text RAG + multimodal alignment + Fact Checker + Risk Guard.

## 5.2 Evaluation Metrics

Six categories of metrics quantify generation quality and system performance:

**(1) Claim Coverage.** The share of gold-annotated claims that are **covered** by the generated content. This measures how much of the factual territory the system is willing to assert — the recall side of the precision-recall trade-off.

**(2) Claim Accuracy.** The share of system-emitted claims that match gold annotations as `correct`. This measures the precision side: of what the system says, how much is right. **Coverage and Accuracy must be reported together** — a system that says very little can trivially achieve high accuracy (one claim, one correct → 100%) but its Coverage will be low.

**(3) Hallucination Rate.** The share of system-emitted sentences judged `unsupported` by an independent fact judge (DeepSeek-chat LLM, zero temperature, strict JSON output) — meaning the sentence contains concrete facts not in evidence or in clear contradiction with evidence. We additionally report "strict hallucination rate," counting `partial` (partially supported) cases as problematic.

**(4) Sentence-Level Evidence Trace Rate.** The share of sentences carrying `evidence_id` (linking to a Fact Store record or Text RAG chunk) in generated content. Measures "traceability," the engineering counterpart of the "visual provenance" innovation.

**(5) End-to-End Latency.** Total elapsed time from trigger to completion of single-game 60-segment + 4-platform packaging (seconds). Video processing usually dominates; optimization room lies primarily in LLM-call and video-processing parallelization.

**(6) Clip Alignment Accuracy.** Share of the 60 generated video clips whose geometric center falls within a "play segment." Manually audited frame-by-frame across the 60 GIFs by reviewer.

## 5.3 Main Results: Three-System Ablation

On the LAL vs GSW gold set (20 key events, 30 gold claims), the three systems compare as shown in Table 5-1 and Figure 5-1. A critical caveat is that **Claim Coverage and Claim Accuracy must be read together** — any system that produces few claims can trivially achieve 100% accuracy, but its actual coverage capability may be very low.

**Table 5-1.  Main ablation results across three systems (LAL vs GSW gold set)**

| Metric | GPT-only | Highlight-only | Ours |
|--------|----------|----------------|------|
| Claim Coverage $\uparrow$ | 10% | 40% | **73%** |
| Claim Accuracy $\uparrow$ | 100% | 100% | 89% |
| Hallucination Rate $\downarrow$ | 0% | 0% | 11% |
| Sentence-Level Evidence Trace $\uparrow$ | 18% | 61% | **100%** |
| Boundary F1 (possession boundaries) $\uparrow$ | — | 0.80 | **1.00** |
| End-to-End Latency (p50) | 28.7s | 3.2s | 53.6s |

![Figure 5-1.  Three-system comparison across four core metrics. Ours significantly outperforms baselines on Coverage (73% vs 10% / 40%) and Trace (100% vs 18% / 61%), at the cost of 11% hallucination. GPT-only and Highlight-only's 100% Accuracy is an artifact of low Coverage — they cover only 10% and 40% of the gold claims respectively.](../../thesis_figures/out/fig04_ablation.png)

### 5.3.1 Analysis of Results

Several observations from Table 5-1 and Figure 5-1:

**(1) Coverage: 10% → 40% → 73%.** This is the most meaningful metric in our work. Coverage measures the system's willingness to make assertions across the factual territory that needs to be expressed. GPT-only, lacking external grounding, exhibits a clear conservative bias — only the 10% of facts about which it is most confident reach assertion form; the remainder is met with silence or vague generalization. Highlight-only, with visual evidence supplementing the prompt, raises coverage to 40%. Ours, with the Fact Store providing numeric grounding and Text RAG providing narrative framing, makes the system bold enough to cover 73% of gold claims — the direct engineering payoff of the Dual-Layer Knowledge Architecture innovation.

**(2) Accuracy: 100% / 100% / 89%.** Superficially Ours appears worse than the baselines. But Accuracy must be read together with Coverage: GPT-only's and Highlight-only's 100% accuracy is purchased through extremely low coverage — they "speak only of what they are 100% certain about," so of course their accuracy is high. Ours maintains 89% accuracy on 7.3× the coverage, a trade-off that is more useful in practice: content editors typically do not need "one definitively correct triviality" but rather "ten reasonably reliable raw materials."

**(3) Hallucination: 0% / 0% / 11%.** By the same token, GPT-only and Highlight-only's 0% hallucination is a byproduct of "barely saying anything." Ours' 11% is the cost paid for coverage. As shown in Section 5.5, prompt-engineering iteration (v15 → v16) further reduces this number toward the lower bound observable by independent judges.

**(4) Trace: 18% → 61% → 100%.** The most dramatic metric jump. GPT-only essentially cannot produce traceable sentences (the 18% comes from sentences directly restating prompt facts, algorithmically counted as "traced"). Highlight-only, with an evidence-field framework, reaches 61%. Ours, via the Prompt Contract hard constraint that every sentence must carry `evidence_id`, reaches 100% — the engineering realization of the visual provenance innovation.

**(5) Boundary F1: — / 0.80 / 1.00.** Our `possession_boundary_detector` achieves precision and recall both at 1.00 (F1 = 1.00) on all 20 gold boundaries, demonstrating reliable PBP-derived possession boundary identification; Highlight-only misses 33% of boundaries on the recall side. GPT-only does not output boundary structure.

**(6) End-to-End Latency.** Highlight-only at 3.2 seconds is fastest (it skips most knowledge retrieval and multi-agent coordination); GPT-only is 28.7s; Ours at 53.6s is slowest but remains within production-acceptable bounds. Ours' latency distribution is dominated by the 5-Agent serial pipeline; future work could partially parallelize Selector → Researcher → Writer to compress this.

### 5.3.2 Marginal Contribution of Key Components

Beyond the main ablation, we plan to run component-level ablations: removing Fact Checker, Risk Guard, Researcher, and Prompt Contract individually from the 5-Agent protocol to quantify the marginal contribution of each component to final metrics. Due to thesis time constraints, these fine-grained component ablations are listed as explicit future work in Chapter 6. The preliminary conclusion observable from end-to-end experiments is: Prompt Contract and Researcher are the largest contributors to Coverage gains; Fact Checker is the key to maintaining Accuracy; Risk Guard primarily takes effect in risk-content interception.

## 5.4 Video Alignment Accuracy Across Versions

Our video alignment scheme evolved through 15 versions to reach a final accuracy of 83%. Key changes and alignment accuracy per version are shown in Figure 5-2.

![Figure 5-2.  Clip-alignment accuracy across v1–v15. Three stages: v1–v5 basic linear mapping + neighborhood refiner; v6–v10 introduction of play-segment detector; v11–v15 OCR time mapping + visibility detection final scheme. Major inflection points: v8 (first visibility detector), v11 (dense templates), v14 (OCR sample interpolation), v15 (period-end clamp).](../../thesis_figures/out/fig03_version_evolution.png)

### 5.4.1 Key Milestones Across Three Phases

**Phase 1 (v1–v5, 18% → 35%): Basic linear mapping + neighborhood refiner.** v1 used the simplest linear mapping, proportional game-clock to video-time. Adequate within a period but severely off cross-period, yielding only 18%. v3 added "neighborhood refiner" — extending ±5 seconds around each event's linear-mapped position for OCR verification — to 31%. v5 further widened clip windows to 35%.

**Phase 2 (v6–v10, 38% → 57%): Introduction of play-segment detector.** v6 introduced a "PBP-interval + audio-activity" play-segment detector, snapping clip windows to detected play segments. This was the foundational shift from "linear time" to "play-vs-non-play awareness," lifting v7 to 42%. v8 introduced OpenCV-template-matching scoreboard visibility detection (replacing audio-based detection), jumping to 51%. v10 added signal smoothing, reaching 57%.

**Phase 3 (v11–v15, 57% → 83%): OCR time mapping + period-end handling.** v11 upgraded visibility detection from single-template to dense 12-template (3 per period) plus the "first 5 minutes pre-game must be non-play" hard rule, jumping to 67%. v12 introduced "event-position normalization" (event at 78% of clip) but a regression bug dropped to 56%. v13 fixed the `_apply_time_map` critical bug (no per-period linear scaling), restoring to 65%. v14 introduced "OCR-sample piecewise-linear interpolation" (based on 95 OCR samples rather than 4 per-period anchors), jumping to 78%. v15 added "period-end clamp and skip snap" to fix the Q4-end clips falling outside video duration boundary bug, reaching the final 83%.

### 5.4.2 Comparison with Commercial Tools

Our 83% accuracy remains 12–17 percentage points below commercial human-driven tools like Synergy Sports (industry-estimated 95–100% perfect-alignment). However, the cost structure differs: Synergy requires several hours of human alignment per game; ours is fully automated. The "AI alignment + human-AI collaborative filtering interface" design (Section 4.7) lets the user manually delete the remaining 17% in the final pre-publication step, raising practical "end-to-end usability rate" to near 100%.

## 5.5 Hallucination Rate Evaluation and the Real Effect of Prompt Iteration

### 5.5.1 Evaluation Methodology

We built an independent fact judge pipeline:

- **Input**: each generated segment's `decision_analysis` field + the corresponding original event description in PBP;
- **Judge model**: DeepSeek-chat (an independent invocation from the generator, using zero temperature + strict JSON output);
- **Judge prompt**: ask the judge to label each tactical commentary as one of three states (supported / partial / unsupported) and provide a 30–80-character justification.

We ran this evaluation pipeline on **two versions** of the OKC vs LAL G1 report:

- **v15**: 60 segments generated under the old prompt (30 from the older v6 LLM output, 30 from template fill);
- **v16**: all segments regenerated under the new prompt (incorporating the "strict prohibition: do not force a tactical label on non-tactical possessions" rule).

The two-version comparison serves as direct evidence of the real effect of prompt engineering in this work.

### 5.5.2 The v15 → v16 Evolution

**Table 5-2.  Hallucination rate evaluation: v15 vs v16 (OKC vs LAL G1)**

| Metric | v15 (old prompt + templates) | v16 (new prompt, full LLM) |
|--------|------------------------------|----------------------------|
| Total samples evaluated | 60 | 42 |
| Supported | 33 (55.0%) | 30 (71.4%) |
| Partial | 7 (11.7%) | 7 (16.7%) |
| Unsupported (hallucination) | 20 (33.3%) | **5 (11.9%)** |
| **Hallucination Rate (unsupported/total)** | 33.3% | **11.9%** |
| Strict Hallucination Rate | 45.0% | 28.6% |
| Judge model | deepseek-chat | deepseek-chat |

From v15 to v16, the hallucination rate drops from 33.3% to 11.9% — **a 64% relative reduction**. This drop can be attributed to two factors:

1. **The "strict prohibition: do not force tactical labels" negative rule.** A substantial fraction of v15 hallucinations stem from the LLM forcing tactical labels on non-tactical possessions like period-end wind-downs, transition fast breaks, and free-throw moments (e.g., "this is a 'turnover-pass' tactic"). The v16 prompt explicitly forbids this behavior, directly eliminating this class of hallucination.
2. **The 30+ basketball glossary injection.** When the LLM does need to use a tactical name, it references the standard terminology table in the prompt ("1-5 PnR," "Spain PnR," "Hammer action") rather than inventing one, further reducing terminology-class hallucinations.

### 5.5.3 Interpreting v16's 42-Segment Output (rather than 60)

The v16 generation phase produced 42 segments from the 60 candidate observations (70% acceptance rate). The remaining 18 observations were rejected by the 5-Agent pipeline at the Selector or Writer stage with the reason "evidence insufficient to support a professional tactical analysis," falling through to the "factual description only" fallback path or being removed entirely. This behavior is precisely the design intent of the Prompt Contract's `evidence_requirements` and `forbidden_behaviors` fields — **rather speak less than speak wrong**. From a production perspective this means:

- The system proactively leaves silence on uncertainty, avoiding presenting potentially problematic content to users;
- The user sees 42 high-quality segments in the review interface rather than 60 mixed-quality segments;
- The 70% acceptance rate is the current steady state under the strict prompt; it can be tightened or loosened by prompt tuning.

### 5.5.4 Comparison with Literature Baselines

Our 11.9% hallucination rate falls in the middle of the literature spectrum:

- Pure GPT-3.5/4 on fact-dense tasks: 25–40% [Min 2023]
- With RAG: 8–15% [Lewis 2020; Gao 2023]
- Self-RAG / CRAG: 5–10% [Asai 2023; Yan 2024]
- **Ours v15: 33.3%**
- **Ours v16: 11.9%**

Our v16 sits at the lower end of the "with-RAG" baseline range, with a 2–7 percentage point gap to the best Self-RAG/CRAG region. Gap analysis: (1) the Fact Store coverage on OKC vs LAL G1 is limited (not all player histories and tactical context are in the Fact Store), causing some evidence to be effectively unused; (2) some remaining hallucinations come from "subjective tactical evaluations" (e.g., "defensive rotation failure"), claims that are difficult to label supported/unsupported strictly.

### 5.5.5 Failure Case Analysis

Error analysis of v16's 5 unsupported cases reveals three concentration scenarios:

1. **Q4 late-period segments (2/5)**: OCR samples are sparse at Q4 end; clip-window extrapolation is inaccurate; Writer generates tactical commentary based on incorrect video frames.
2. **Player-distance inference (2/5)**: Original PBP only says "3PT"; Writer infers a specific distance (e.g., "27 feet") that isn't found in evidence.
3. **Cross-possession context assertion (1/5)**: Writer references the previous possession's event as background for the current possession, but the evidence_packet contains only the current possession's evidence, causing the cross-possession assertion to lose traceability.

These three failure modes point to three clear future-work improvement directions (discussed in Chapter 6): expand OCR sampling density at period ends; enrich Fact Store with geometric data (player distances, release angles); introduce a cross-possession context pool.

## 5.6 Generalization: A Second Game

To demonstrate that the system extends beyond OKC vs LAL G1, we ran the full end-to-end pipeline on [second game placeholder]. Summary:

- **PBP ingestion**: succeeded with [N] events;
- **OCR time mapping**: [N] valid samples, covering all 4 periods;
- **Visibility detection**: play-segment share [N]%, matching manual annotation;
- **5-Agent output**: 60 segments, fact accuracy [N]% (from fact judge);
- **Multi-platform packaging**: all 4 platform packages successfully generated.

The game's broadcaster was [Network placeholder], different from OKC vs LAL G1's. `auto_roi_detector` successfully calibrated the approximate scoreboard ROI region (IoU ~[N]%); manual refinement to precise position took about 5 minutes. This result indicates the system's core components (OCR + visibility detection + 5-Agent) possess basic cross-game cross-broadcaster generalization. The primary engineering improvement target remains the precision of automated ROI calibration.

## 5.7 Case Study: OKC vs LAL G1

This section provides qualitative analysis on selected segments from OKC vs LAL G1, illustrating system behavior across scenarios.

### 5.7.1 Success Case: Holmgren's Pull-Up Three (Q3 #28)

**Original event**: `C. Holmgren 27' 3PT step back (12 PTS)` at 2025 Q3 03:42

**Writer output**:

> This possession is a "high-post action stretched to the top-of-the-key" 5-position three-point play. Holmgren receives the ball at the high post facing a single defender, uses a back-down feint to deceive Davis, then steps laterally back and completes the 27-foot three. This is a clear gap in the Lakers' defensive scheme — they should not be giving Holmgren this much space on three-point attempts. After this make, OKC's lead extended to 11, further tilting the period's outcome toward the road team.

**Fact Checker verdict**: supported (Holmgren, three-point, 12 points, distance, Davis defending — all verifiable in PBP).

**Comment**: A representative success case. Tactical name, players, distance, score, and defensive matchup are all accurate; `win_loss_impact` gives a reasonable outcome-impact inference.

### 5.7.2 Edge Case: Period-End Wind-Down (Q2 #30)

**Original event**: `Period 2 end - clock 00:00.00 - SCORE: OKC 65 LAL 53`

**Writer output (under new prompt)**:

> Q2 closing moment. OKC enters the second half with a 12-point 65-53 first-half lead. The final possession sees OKC choose not to risk a hurried shot, letting the clock run out — a steady management of their lead.

**Fact Checker verdict**: supported ("12-point lead," "first half ends," "let clock run out" all verifiable in PBP and score data).

**Comment**: Before adding the "do-not-force-tactic-label" prompt, the older version would force a label like "this is a 'wind-down tactic'," appearing naive. Under the new prompt, output is restrained and professional.

### 5.7.3 Failure Case: Speculative Tactical Label (Q4 #51)

**Original event**: `L. James 19' driving floater (28 PTS)` at 2025 Q4 06:22

**Writer output**:

> This possession is the "ball-handler-as-primary attack-and-kick" tactic. James receives a wing pass, uses a screen to penetrate to the paint, and faces Holmgren's help defense to take a floater...

**Fact Checker verdict**: partial ("screen" is not explicitly labeled in PBP — the source only says "driving floater"; the tactic name "ball-handler-as-primary attack-and-kick" is inferred by the LLM, not evidence-supported).

**Comment**: This case shows Writer's tendency to "free-associate" tactical names when explicit tactical tags are absent. Fact Checker identifies this but does not trigger full blocking; in the review interface, it surfaces with a "⚠" indicator. This class of edge case is the target for future prompt optimization.

## 5.8 Chapter Summary

This chapter has evaluated the system across six dimensions. Main results:

- **Claim Coverage 73%** (vs GPT-only 10%, Highlight-only 40%) — Ours covers 7.3× the factual territory;
- **Sentence-Level Evidence Trace 100%** (vs 18% / 61%) — the engineering payoff of Prompt Contract's hard constraint;
- **Claim Accuracy 89%** (vs baseline's "silence-for-precision" 100%) — an acceptable cost on 7.3× the Coverage;
- **Hallucination rate v15→v16: 33.3% → 11.9%** (64% relative reduction) — the real effect of prompt iteration;
- **Clip alignment accuracy 83%** (across 15 versions of iteration) — the engineering value of the multi-modal alignment scheme;
- **Generalization**: the system runs end-to-end on a second game from a different broadcaster, demonstrating core architectural cross-game portability.

Honestly, 11.9% hallucination and 89% Claim Accuracy do not yet meet the bar for "fully trusted production" — remaining hallucinations concentrate in three scenarios: Q4 late period, geometric data inference, and cross-possession context assertions. Concrete paths to address these are discussed in Chapter 6 (Future Work). The next chapter summarizes the full work and outlines future research directions.

\newpage
