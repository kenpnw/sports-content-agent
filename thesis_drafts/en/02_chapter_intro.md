# Chapter 1  Introduction

## 1.1 Background

### 1.1.1 The Digital Sports Content Ecosystem and Its Bottlenecks

Sports has become one of the central categories of global digital content consumption. The four major professional leagues — NBA, English Premier League, Formula 1, and NFL — together command an audience of more than 2.5 billion people worldwide, sustaining a vast ecosystem of pre-game previews, in-game interaction, and post-game analysis. In China specifically, platforms such as Hupu, Douyin, Bilibili, Xiaohongshu, Weibo, and Video Account produce hundreds of thousands of sports-related posts daily, forming a multi-tiered content matrix that spans professional outlets and self-media creators, long-form prose and short video, hard statistics and soft storytelling. During the 2025 NBA playoffs, a high-attention game such as the Finals G1 generated several thousand post-game discussion threads on Hupu's "Walking Street" board alone, with accompanying Douyin short videos easily reaching millions of plays. This volume reflects the multi-fold demand sports real-time content places on production speed, coverage breadth, and stylistic diversity.

Yet traditional sports content production is highly labor-intensive. A typical workflow of an experienced sports editor compiling a high-quality post-game tactical breakdown involves 30 to 90 minutes of focused work, spanning statistical fact-checking, video re-watching and segment selection, angle choice, platform-specific stylistic rewriting, and cover-image production. This labor model imposes three structural bottlenecks:

- **Limited timeliness.** The "golden distribution window" after a major sporting event is typically only 30 to 60 minutes; no single editor can high-quality cover multiple games simultaneously. The industry benchmark of "first deep tactical recap within 90 minutes of game end" forces editors into sustained pressure work.
- **Limited coverage breadth.** Mainstream sports outlets concentrate human resources on flagship leagues and star players, leaving long-tail leagues (CUBA, women's basketball, youth tournaments, foreign minor leagues) chronically under-served in professional tactical analysis. This structural imbalance further exacerbates the "Matthew effect" in the sports content market.
- **Stylistic fragmentation.** A single article rarely achieves equal traction across Hupu, Douyin, and Xiaohongshu. Hupu users prefer tactical depth and data detail; Douyin users prefer fast pacing and conflict points; Xiaohongshu users prefer image-rich, lifestyle-flavored narration. This forces editorial teams to write multiple platform-specific versions of the same story, further squeezing the marginal revenue of any single piece of content.

### 1.1.2 The New Possibilities Opened by Large Language Models

In recent years, large language models such as GPT [Brown 2020], PaLM [Chowdhery 2022], LLaMA [Touvron 2023], Qwen [Bai 2023], and DeepSeek [DeepSeek-AI 2024] have demonstrated unprecedented capabilities in natural language generation, opening new technical paths for automated content production. In the sports domain, several commercial products have attempted to apply LLMs to automated game reporting: international examples include Stats Perform's Automated Insights pipeline; domestic examples in China include Toutiao's "Xiaomingbot" and Xinhua News Agency's "Kuaibi Xiaoxin." Yet these attempts generally encounter three deep-rooted problems:

**(1) Factual hallucination.** This is the most lethal defect in news-style scenarios. Ji et al. [Ji 2023] systematically categorize LLM hallucinations into "intrinsic hallucinations" (output conflicts with input) and "extrinsic hallucinations" (output conflicts with established facts). In sports content, naked LLMs frequently produce wrong scores (writing 121-104 instead of the actual 119-102), fabricate key player performances (writing LeBron James with 30 points when his actual line was 27), or mis-apply tactical names (forcing a "pick-and-roll" label on a fast-break transition possession). Once such errors enter a published article, the damage to the publishing organization's professional credibility far outweighs whatever production-efficiency gains the AI provides.

**(2) Style drift.** A single LLM has difficulty maintaining stable boundaries across the styles required by different platforms. For instance, when prompted to "generate a Hupu-style post-game thread," the result frequently exhibits a "news-bulletin tone" — overly formal sentence structure, missing fan vernacular, lacking emotional color. When prompted for a "Douyin-style short-video script," the result is often too declarative and flat, lacking the conflict points and tonal turns that drive engagement. Although careful prompt engineering can mitigate the issue locally, the model's "understanding granularity" of style instructions remains coarse, and cross-platform style switching remains unreliable.

**(3) Invisible credibility.** Even when the generated content is accurate, the end reader has no way to distinguish which claims are grounded in real data and which are model conjecture. A statement such as "the Lakers' weakened rim protection at the 3 position allowed Oklahoma City to keep attacking the paint" — the reader cannot tell whether this is grounded in Synergy Sports tracking data or merely a model's inference from general knowledge. This opacity, as AIGC content occupies a growing share of public information space, has become a key barrier to scaling AI output in professional media.

### 1.1.3 What Makes Sports Content Especially Challenging

Several intertwined attributes make sports a uniquely demanding domain for LLM-based content generation:

- **High factual precision requirement.** Sports content is number-dense: scores, time codes, shooting percentages, possession counts appear in nearly every sentence. Numeric faithfulness is one of the weakest areas of LLM behavior [Min 2023].
- **Strong stylistic differentiation across platforms.** As described above, user aesthetics and content preferences differ sharply across platforms, and a single model output cannot satisfy all simultaneously.
- **Inseparable multimodality.** High-quality post-game content is typically delivered as the composite of "GIF clip + tactical commentary + statistical chart," and the GIF clip must be precisely aligned to the actual basketball possession — otherwise readers face the disorienting mismatch of "commentary describes a pick-and-roll while the clip shows a replay angle."
- **Strict timeliness constraints.** As described above, the post-game golden distribution window is only 30–60 minutes, within which the entire pipeline — video processing, content generation, multi-platform packaging, risk audit, publishing — must complete.
- **High density of specialized terminology.** Terms such as "1-5 pick-and-roll," "backdoor cut," "Spain PnR," "Hammer action," "Horns set," and "double drag screen" have precise tactical definitions in the playbooks of professional teams, and whether they are used accurately and proportionally is a key measure of professional credibility.

How to enable an LLM in a sports-like content scenario — with simultaneously high factual demand, strong style fragmentation, limited delivery time, and multimodal alignment requirements — to produce content that is trustworthy, controllable, traceable, and stylistically appropriate, remains an unsolved open problem in the practical engineering of AIGC. This thesis takes that problem head-on, proposing and implementing an end-to-end solution for the NBA post-game scenario specifically.

## 1.2 Significance

This research proposes and implements a multi-agent supervision framework that balances factual controllability, multimodal alignment accuracy, and generative diversity for the NBA post-game content scenario, with three categories of significance.

### 1.2.1 Academic Significance

This work sits at the intersection of three active research lines: trustworthy LLM generation, retrieval-augmented generation (RAG), and multi-agent LLM coordination. The original contributions are:

- The **Dual-Layer Knowledge Architecture** breaks the reliability ceiling that traditional single-vector-store RAG hits on numeric queries, offering a new retrieval routing paradigm for domains where structured and unstructured knowledge coexist.
- The **Multi-Agent Supervision Protocol** differs from debate-oriented multi-agent lines such as Multi-Agent Debate [Du 2023; Liang 2023], introducing reviewer roles with hard blocking authority. This offers a new coordination paradigm for multi-agent systems in high-factuality scenarios.
- The **Prompt Contract** formalization provides a verifiable engineering paradigm for constraining LLM output, advancing prompt engineering from "empirical craft" toward "engineering contract."
- The **OCR time mapping + scoreboard visibility detection** scheme offers a lightweight, interpretable, deep-learning-inference-free engineering solution to the long-standing "play-segment vs. non-play-segment" identification problem in video content automation.

### 1.2.2 Engineering Significance

This work provides reusable infrastructure for trustworthy content production for sports media organizations, content platforms, and self-media creators. In our internal tests, the system compresses end-to-end production of "raw material → four-platform finished articles" from a typical 4 hours (human-led) to 30–45 minutes (human-AI collaborative), a 6–8× efficiency gain. The system does not pursue full replacement of human editors; rather, it liberates editors from low-value high-repetition steps such as "find evidence, find tactic name, rewrite per platform," letting them focus on high-value activities like "topic selection, core viewpoint formation, and stylistic polish." This matches the dominant "human-AI collaborative" paradigm of AI-era content production.

### 1.2.3 Social Significance

As AIGC content occupies a growing share of public information space, the risk of misinformation proliferation grows accordingly. In high-volume high-frequency content scenarios like sports, an error in AI-generated content (wrong scores, fabricated player performances) — accepted with the implicit authority of "machine output is more objective" — can reach hundreds of thousands of readers within hours. The **visual provenance** mechanism proposed in this work lets the end reader assess in real time whether each claim is data-grounded (green verified state), inference-based (yellow partial state), or pure narrative (gray narrative state). This "visible trustworthiness" matters for the healthy development of the public content ecosystem and provides a viable compliance path for scaled AI content use in professional media.

## 1.3 Domestic and International Research Status

Detailed literature review is deferred to Chapter 2. This section offers a brief overview of four closely related directions to position this work in the literature.

**Large Language Models and Text Generation.** Since the Transformer architecture [Vaswani 2017] and the GPT family [Radford 2019; Brown 2020] were introduced, LLMs have made rapid progress on generation tasks. Instruction tuning [Wei 2022] and reinforcement learning from human feedback (RLHF) [Ouyang 2022] have further improved alignment with human intent. Yet hallucination in high-factuality scenarios remains a serious unsolved problem. Domestic open-source models such as DeepSeek-V2 [DeepSeek-AI 2024] and Qwen2 [Bai 2024] now achieve Chinese-scenario performance comparable to GPT-4 [OpenAI 2023], providing high-quality foundation models for the Chinese-language application targeted here.

**Retrieval-Augmented Generation.** The classic RAG framework proposed by Lewis et al. [Lewis 2020] combines external knowledge retrieval with LLM generation, significantly reducing hallucination rates. Subsequent work — Self-RAG [Asai 2023], CRAG [Yan 2024], HyDE [Gao 2023], GraphRAG [Edge 2024] — has improved retrieval quality, self-reflection, query rewriting, and graph-structured knowledge representation. Yet the vast majority of existing RAG work uniformly represents "knowledge" as a vector store of text, which struggles to guarantee precise recall of numeric values in domains like sports, finance, or e-commerce where numbers are central. The Dual-Layer Knowledge Architecture proposed in this thesis directly addresses this gap.

**LLM Hallucination Suppression.** Ji et al. [Ji 2023] provide a systematic taxonomy of LLM hallucinations (factuality vs. faithfulness). Evaluation tools such as SelfCheckGPT [Manakul 2023], FActScore [Min 2023], and TruthfulQA [Lin 2022] provide quantification methodology. For mitigation, generation-time methods such as Constitutional AI [Bai 2022] use principle-based self-correction, while external-verification methods such as Chain-of-Verification [Dhuliawala 2023] use multi-round self-questioning to reduce hallucination. Our Multi-Agent Supervision Protocol is conceptually related to CAI and CoVe but places stronger emphasis on **structured role boundaries and inviolable review blocking**, upgrading "self-reflection" to "inter-role hard supervision."

**Multi-Agent Large Language Model Systems.** AutoGen [Wu 2023], MetaGPT [Hong 2023], CAMEL [Li 2023], and ChatDev [Qian 2024] decompose complex tasks across multiple LLM roles. Multi-Agent Debate [Du 2023; Liang 2023] uses adversarial role-play to improve reasoning quality. These works primarily target general tasks like code generation or mathematical reasoning, with limited specialization for vertical domains like sports content. This thesis builds on that foundation while introducing domain-aware role specifications, explicit evidence contracts, and inviolable review blocking — extending multi-agent coordination from "improving reasoning quality" to "guaranteeing factual controllability."

**Sports Content Automatic Generation.** Early work such as STATS LLC's Automated Insights used template-based text-filling methods, yielding controllable but stylistically monotonic output. Recent work such as SportsBot [Smith 2022] combines statistical data with LLM short-text generation but does not address video alignment. Domestic systems like Xinhua's "Kuaibi Xiaoxin" and Toutiao's "Xiaomingbot" have achieved engineering practice in the Chinese-language scenario but with limited public technical detail. Among publicly published sports-content-generation work, this thesis is one of the few simultaneously covering **multimodal alignment, multi-agent supervision, multi-platform stylization, and end-to-end implementation** — all four dimensions.

## 1.4 Research Content and Innovations

### 1.4.1 Core Research Question

The core research question of this thesis is:

> **How can we generate sports real-time content that is factually correct, traceable, stylistically diverse, low-latency, platform-appropriate, and accurately video-aligned?**

Around this central question, the work covers: (1) requirements modeling and architecture design; (2) the Multi-Agent Supervision Protocol; (3) the Dual-Layer Knowledge Architecture; (4) the multi-modal time alignment scheme; (5) stylistic generation and platform adaptation; (6) visual provenance mechanism; (7) comprehensive evaluation experiments and ablation analyses.

### 1.4.2 Three Core Innovations

#### Innovation 1: Multi-Agent Supervision Protocol

We propose a coordination framework comprising five roles — Selector, Researcher, Writer, Fact Checker, and Risk Guard — each with clear responsibility boundaries and explicit output contracts. The roles operate in pipeline fashion. **Crucially, Fact Checker and Risk Guard hold hard blocking authority** over the pipeline: any failure on their review triggers correction loops or content downgrade. This differs sharply from multi-agent debate frameworks where roles are equal-weight discussants. Together with the **Prompt Contract** formal language (Innovation 1b), this makes every role's behavior boundary formal and auditable. Detailed design is presented in Section 3.4.

#### Innovation 2: Dual-Layer Knowledge Architecture

In response to the coexistence of "hard data + soft narrative" in sports content, we split knowledge storage and retrieval into two layers: (a) a SQLite-backed **Fact Store** carrying structured facts (scores, player stats, team records, head-to-head history, current standings); and (b) a vector-indexed **Text RAG** carrying narrative text (post-game commentary, interview snippets, injury notes, historical analysis). The accompanying routing rules ensure: numeric assertions must be backed by Fact Store; narrative framing may be drawn from Text RAG; hybrid assertions prefer hard data. This architecture provides significant improvements in numeric correctness over single-store vector RAG. Detailed design is presented in Section 3.3.

#### Innovation 3: Multi-Modal Alignment with Provenance-Aware Verification

This innovation combines two closely related mechanisms:

**(a) Multi-modal alignment.** A three-step "OCR time mapping + scoreboard visibility detection + play-segment snap" scheme maps each play-by-play event to its actual broadcast moment:
- OCR time mapping samples one frame per second, extracts (video-seconds, period, clock) triples via OCR, and constructs per-period piecewise-linear maps from ~95 samples.
- Scoreboard visibility detection uses OpenCV template matching against 12 per-period reference templates to classify each second as play or non-play.
- Play-segment snap shifts clip windows that land in non-play segments (replays, slow motion, ads) toward the nearest play segment.

**(b) Visual provenance.** Every generated sentence is annotated with one of three factual-grounding states (verified ✓ / partial ⚠ / unsupported ✗) and rendered as a color-coded UI element in the review interface. End readers can click to inspect the underlying evidence. This mechanism converts otherwise invisible engineering metrics into a user-visible product feature — the key bridge between "engineering-level trust" and "user-level trust." Detailed design is presented in Sections 3.5 and 3.6.

## 1.5 Organization of the Thesis

The thesis comprises six chapters, organized as follows:

**Chapter 1, Introduction**, motivates the research, reviews international and domestic literature briefly, and articulates the three core innovations.

**Chapter 2, Related Work**, conducts an in-depth literature review across five directions: LLMs and text generation; retrieval-augmented generation; LLM hallucination suppression; multi-agent LLM systems; and sports content automatic generation.

**Chapter 3, System Design**, presents the four-layer architecture, the Multi-Agent Supervision Protocol, the Prompt Contract specification, the Dual-Layer Knowledge Architecture, the multi-modal alignment design, the visual provenance mechanism, and the multi-platform stylization design.

**Chapter 4, Key Technical Implementation**, gives concrete implementation details for NBA Live API ingestion, video time mapping, scoreboard visibility detection, play-segment alignment, tactical commentary generation, multi-platform packaging, and the web review interface.

**Chapter 5, Experiments and Evaluation**, presents three-system ablation results, version-evolution clip alignment accuracy, judge-model hallucination rate evaluation, generalization tests on a second game, and qualitative case studies on the OKC vs. LAL G1 dataset.

**Chapter 6, Conclusion and Future Work**, summarizes contributions, analyzes current limitations, and outlines five concrete future-work directions: vision-LLM ROI auto-calibration, period-end OCR expansion, multi-game batch pipeline, cross-sport generalization, and user-feedback closed-loop learning.

\newpage
