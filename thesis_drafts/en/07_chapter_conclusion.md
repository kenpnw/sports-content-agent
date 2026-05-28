# Chapter 6  Conclusion and Future Work

## 6.1 Summary of Work

This thesis proposes and implements a multi-modal multi-agent supervision framework for the NBA post-game content generation scenario, balancing factual controllability, multimodal alignment accuracy, and stylistic diversity. Around the core research question — "How can we generate sports real-time content that is factually correct, traceable, stylistically diverse, low-latency, platform-appropriate, and accurately video-aligned?" — the main contributions are:

**(1) The 5-Agent Supervision Protocol** — five coordination roles (Selector, Researcher, Writer, Fact Checker, Risk Guard) with clear responsibility boundaries and explicit output contracts. Fact Checker and Risk Guard as blocking-authority reviewer roles ensure every pre-publication segment passes both factual and risk gates. Unlike the debate-oriented Multi-Agent Debate line, the protocol's "pipeline + hard supervision" combination better suits fact-controllable content generation scenarios.

**(2) The Dual-Layer Knowledge Architecture** — Fact Store (SQLite) carries structured numeric knowledge; Text RAG (FTS5) carries narrative knowledge. Accompanying routing policy ensures numeric assertions must be backed by Fact Store. On the LAL vs GSW gold set, this architecture raises Claim Coverage from GPT-only's 10% to 73%, shifting the system from passive silence to bold coverage — the most significant engineering metric improvement in this work.

**(3) The Multi-Modal Time Alignment Scheme** — "OCR time mapping + scoreboard visibility detection + play-segment snap" three-step scheme raised OKC vs LAL G1 clip alignment accuracy from 18% (basic linear mapping) to 83% (final scheme). Without deep-learning inference, using only classical computer-vision techniques like OpenCV template matching, deployment cost is extremely low.

**(4) The Prompt Contract** — explicit declaration of every LLM call's task, source scope, forbidden behaviors, output shape, and review gate, making every role's behavior boundary formal and auditable. This design shifts "prompt as empirical craft" toward "prompt as verifiable contract."

**(5) Visual Provenance** — sentence-level factual-grounding state annotation (verified / partial / unsupported) on generated content, converting otherwise invisible engineering metrics into user-visible product features. This mechanism bridges "engineering-level trust" and "user-level trust."

**(6) End-to-End Implementation and Multi-Dimensional Evaluation** — a 7000-line Python engineering implementation covering the complete pipeline from PBP ingestion to 4-platform packaging. In three-system ablation experiments, the system achieves fact accuracy 94%, hallucination rate 3%, sentence-level evidence trace rate 100%.

## 6.2 Limitations

Honest analysis of current system limitations:

### 6.2.1 The Remaining 17% Video-Alignment Errors

83% alignment accuracy significantly outperforms baselines but leaves about 17% of clips falling on non-game frames. Remaining errors concentrate in: (a) Q4-end segments with sparse OCR coverage; (b) period-end wind-downs and timeout boundaries; (c) broadcaster-inserted brief replays (high-frequency but short).

### 6.2.2 Cross-Game Engineering Cost

Each game's "scoreboard ROI calibration" requires 5–10 minutes of manual work. The `auto_roi_detector` module achieves proof-of-concept precision, but not production-ready. New games still require modest human intervention.

### 6.2.3 LLM Over-Inference on Period-End Wind-Down Possessions

As Section 5.7.3's failure case showed, Writer occasionally tends to "free-associate" tactical names when explicit tactical labels are absent. Fact Checker currently catches these, but fully eliminating the tendency requires further prompt engineering or fine-tuning.

### 6.2.4 Evaluation Dataset Size and Diversity

Primary evaluation runs on OKC vs LAL G1 and LAL vs GSW — limited coverage. Production-scale rollout would require systematic evaluation on dozens or hundreds of games; current sample size is insufficient for statistical significance.

### 6.2.5 Dependence on Human Annotation for Evaluation

Fact accuracy and hallucination rate evaluations depend on human-labeled `gold_claims` (or an independent LLM judge). The former is expensive; the latter may have evaluation bias. We adopt the "independent LLM judge" compromise; more reliable evaluation requires large-scale human annotation — a clear future-work direction.

## 6.3 Future Work

Based on the current limitations analysis, this thesis outlines five future-work directions:

### 6.3.1 Vision-LLM-Assisted ROI Calibration and Alignment

Introduce vision-understanding large models (GPT-4V, Qwen-VL, DeepSeek-VL) into ROI auto-calibration and play-segment detection. This direction can significantly lower cross-game engineering cost, with the goal of reducing per-game "manual preparation time" from 5–10 minutes to 0.

### 6.3.2 Auto-Expanded Period-End OCR Coverage

For Q4-end OCR-sparse segments, raise OCR sampling density from 1Hz to 5Hz in the final 2 minutes of each period, and switch OCR engines to more robust alternatives (such as Alibaba DAMO's ReadingBank or Microsoft TrOCR).

### 6.3.3 Multi-Game Batch Processing Pipeline

Extend the single-game pipeline to multi-game batch processing, supporting automatic production of 4-platform content packages for 8–10 games per evening within 60 minutes of game completion. This direction touches scheduling, resource management, error recovery — large engineering scope but significant commercial value.

### 6.3.4 Cross-Sport and Cross-Language Generalization

Extend the architecture from NBA basketball to NFL football, English Premier League soccer, Formula 1 racing. The architecture itself (5-Agent, Prompt Contract, dual-layer knowledge) is generic; main work consists of: (a) building tactical glossaries per sport; (b) adapting each sport's PBP interface; (c) adjusting visual alignment schemes per sport.

### 6.3.5 User-Feedback Closed Loop and Continuous Learning

Introduce user feedback on generated content (like / delete / edit), using DPO or similar preference optimization methods for continuous system fine-tuning. This closed loop allows the system to progressively improve through long-term use, evolving toward "self-evolving content production infrastructure."

## 6.4 Concluding Remarks

The core contribution of this thesis can be summarized in one sentence: **the goal is not to replace sports content editors with AI, but to compress high-repetition low-creativity steps such as "find evidence + find tactic name + format + align video" from 3 hours to 3 minutes, freeing editors to focus on truly high-value judgment and expression.** As large language models rapidly permeate every layer of content production, this paradigm — constraining LLMs through engineering frameworks, letting users assess AI trustworthiness through visual mechanisms, ensuring final quality through human-AI collaboration — offers reference value for many AIGC deployment scenarios beyond sports.

\newpage
